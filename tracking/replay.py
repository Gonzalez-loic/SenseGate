"""CPU-only replay against one immutable cache; no live state reads or writes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import statistics
import time
from types import SimpleNamespace
from byte_adapter import make_byte_counter

CFG = dict(LINE_POSITION=449, LINE_ORIENTATION='horizontal', ENTER_DIRECTION='down',
           COUNTING_BAND_SIZE=30, TRACK_SIDE_MARGIN=15, MIN_TRACK_HITS=3,
           MAX_DISTANCE=480, TRACK_MATCH_DISTANCE=180, MAX_DISAPPEARED=105,
           TRACK_HISTORY=32, COUNT_CONFIRM_FRAMES=2, COUNT_CONFIRM_SECONDS=.06,
           TRACK_MAX_AGE_SECONDS=.8, COUNT_MAX_GAP_SECONDS=.5)
VARIANTS = ['current', 'byte_08_strict', 'byte_15_strict', 'byte_15_confirmed_bridge',
            'byte_08_immediate', 'byte_15_immediate']


def engine(source, variant, fps):
    spec = importlib.util.spec_from_file_location('isolated_counter', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock = SimpleNamespace(value=1000.)
    module.time = SimpleNamespace(time=lambda: clock.value, monotonic=lambda: clock.value)
    if variant == 'current':
        counter = module.CounterLogic(dict(CFG))
    else:
        counter = make_byte_counter(module.CounterLogic, dict(CFG), fps,
                                    max_age=.8 if variant.startswith('byte_08') else 1.5,
                                    crossing_gap=1.5 if variant == 'byte_15_confirmed_bridge' else .5,
                                    immediate=variant.endswith('_immediate'))
    return counter, clock


def replay_clip(source, clip, variant):
    counter, clock = engine(source, variant, clip['fps'])
    rows, durations, seen, last, recovered = [], [], set(), {}, 0
    events = []
    old_count = (0,0)
    low = 0
    for frame in clip['frames']:
        clock.value = 1000.+frame['time']
        dets = [dict(d) for d in frame['detections'] if d['score'] >= (.3 if variant == 'current' else .2)]
        begin = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            output = counter.update(dets)
        durations.append(1000*(time.perf_counter()-begin))
        now_count = (counter.in_count,counter.out_count)
        if now_count != old_count:
            events.append({'frame':frame['index'],'time':frame['time'],'delta_in':now_count[0]-old_count[0],'delta_out':now_count[1]-old_count[1]})
        old_count = now_count
        for d in output:
            tid = d['track_id']
            if tid in last and frame['index']-last[tid] > 1:
                recovered += 1
            last[tid] = frame['index']
            seen.add(tid)
            low += d['score'] < .3
        rows.append({'frame':frame['index'],'time':frame['time'],
                     'tracks':[{'id':d['track_id'],'bbox':d['bbox'],'score':d['score']} for d in output]})
    return {'clip':clip['name'], 'frames':len(rows), 'fps':clip['fps'],
            'summary':{'in':counter.in_count,'out':counter.out_count,'new_ids':len(seen),
                       'observations_associated':sum(len(x['tracks']) for x in rows),
                       'frames_with_track':sum(bool(x['tracks']) for x in rows),
                       'low_score_associated':int(low),'same_id_return_after_empty_frames':recovered,
                       'tracker_median_ms':statistics.median(durations)},
            'events':events, 'frames_detail':rows}


def main():
    global CFG
    stage = Path(__file__).resolve().parent
    CFG = json.loads((stage/'counter-config.json').read_text())
    source = stage/'counter_baseline.py'
    cache = json.loads((stage/'detection-cache.json').read_text())
    assert cache.get('completed_at')
    output = {'kind':'tracking-screening-not-field-accuracy', 'variants':[],
              'source_limitations':cache['limitations'],
              'note':'New ID count is not an identity-switch metric without ground truth. A lower count can hide discarded people.'}
    for variant in VARIANTS:
        clips = [replay_clip(source,c,variant) for c in cache['clips']]
        keys = ['in','out','new_ids','observations_associated','frames_with_track','low_score_associated','same_id_return_after_empty_frames']
        output['variants'].append({'name':variant,'clips':clips,
                                   'totals':{k:sum(c['summary'][k] for c in clips) for k in keys},
                                   'median_clip_tracker_ms':statistics.median(c['summary']['tracker_median_ms'] for c in clips)})
    (stage/'tracking-results.json').write_text(json.dumps(output))
    print(json.dumps([{k:v for k,v in variant.items() if k != 'clips'} for variant in output['variants']]))


if __name__ == '__main__':
    main()
