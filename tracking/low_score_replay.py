"""Standalone, standard-library-only comparison; never writes live counters."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import statistics
import time
from types import SimpleNamespace
from low_score_counter import make_low_score_counter

CFG=dict(LINE_POSITION=449,LINE_ORIENTATION='horizontal',ENTER_DIRECTION='down',
         COUNTING_BAND_SIZE=30,TRACK_SIDE_MARGIN=15,MIN_TRACK_HITS=3,
         MAX_DISTANCE=480,TRACK_MATCH_DISTANCE=180,MAX_DISAPPEARED=105,
         TRACK_HISTORY=32,COUNT_CONFIRM_FRAMES=2,COUNT_CONFIRM_SECONDS=.06,
         TRACK_MAX_AGE_SECONDS=.8,COUNT_MAX_GAP_SECONDS=.5)


def engine(source, cfg, candidate):
    spec=importlib.util.spec_from_file_location('isolated_low_score_baseline',source)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock=SimpleNamespace(value=1000.)
    module.time=SimpleNamespace(time=lambda:clock.value,monotonic=lambda:clock.value)
    counter=(make_low_score_counter(module.CounterLogic,cfg,lambda:clock.value,lambda:clock.value)
             if candidate else module.CounterLogic(dict(cfg)))
    return counter,clock


def run_clip(source,cfg,clip,candidate):
    counter,clock=engine(source,cfg,candidate)
    rows,events,timings=[],[],[]
    previous=(0,0)
    for frame in clip['frames']:
        clock.value=1000.+frame['time']
        detections=frame['detections'] if candidate else [d for d in frame['detections'] if d['score']>=.3]
        begin=time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            output=counter.update(detections)
        timings.append(1000*(time.perf_counter()-begin))
        counts=counter.in_count,counter.out_count
        if counts!=previous:
            events.append(dict(frame=frame['index'],time=frame['time'],delta_in=counts[0]-previous[0],delta_out=counts[1]-previous[1]))
        previous=counts
        rows.append(dict(frame=frame['index'],tracks=[dict(id=d['track_id'],bbox=d['bbox'],score=d['score'],weak=d.get('_weak_observation',False)) for d in output]))
    return dict(name=clip['name'],summary=dict(in_count=counter.in_count,out_count=counter.out_count,
                ids=counter.next_id-1,weak=getattr(counter,'weak_stats',{}),
                median_ms=statistics.median(timings),max_ms=max(timings)),events=events,frames=rows)


def compare(source,cfg,data):
    live='frames' in data
    clips=[dict(name='live',frames=data['frames'])] if live else data['clips']
    baseline=[run_clip(source,cfg,c,False) for c in clips]
    candidate=[run_clip(source,cfg,c,True) for c in clips]
    parity=None
    if live:
        assert not data['errors']
        frames=data['frames']
        prior=frames[0]['live_in'],frames[0]['live_out']
        events=[]
        for row in frames:
            current=row['live_in'],row['live_out']
            if current!=prior:
                events.append(dict(frame=row['index'],time=row['time'],delta_in=current[0]-prior[0],delta_out=current[1]-prior[1]))
            prior=current
        parity=baseline[0]['events']==events and all(
            [(d['id'],d['bbox']) for d in replayed['tracks']]==[(d['id'],d['bbox']) for d in observed['live_tracks']]
            for replayed,observed in zip(baseline[0]['frames'],frames))
    result=dict(kind='low-score-shadow-comparison-not-accuracy',baseline_live_parity=parity,
                baseline=baseline,candidate=candidate,production_changed=False)
    if parity is False:
        raise RuntimeError('baseline parity failed; comparison invalid')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists(),'do not overwrite evidence'
    result=compare(args.source,json.loads(args.config.read_text()),json.loads(args.input.read_text()))
    args.output.write_text(json.dumps(result))
    print(json.dumps(dict(baseline_live_parity=result['baseline_live_parity'],
                         baseline=[c['summary'] for c in result['baseline']],
                         candidate=[c['summary'] for c in result['candidate']])))


if __name__=='__main__':
    main()
