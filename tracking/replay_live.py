"""Compare trackers using exact live detector boxes, without video re-inference.

Requires baseline replay parity BEFORE interpreting challenger differences. This
does not label ground truth and never writes counts into production or the VPS.
"""
import json
from pathlib import Path
import replay


def main():
    stage = Path(__file__).resolve().parent
    replay.CFG = json.loads((stage/'counter-config.json').read_text())
    capture = json.loads((stage/'live-01/live-trace.json').read_text())
    assert not capture['errors']
    frames = capture['frames']
    assert frames
    clip = {'name':'live-01','fps':capture['fps'],'frames':frames}
    results = [replay.replay_clip(stage/'counter_baseline.py',clip,v) for v in replay.VARIANTS]
    start_in, start_out = frames[0]['live_in'],frames[0]['live_out']
    live_events = []
    prior = (start_in,start_out)
    for row in frames:
        now = row['live_in'],row['live_out']
        if now != prior:
            live_events.append({'frame':row['index'],'time':row['time'],
                                'delta_in':now[0]-prior[0],'delta_out':now[1]-prior[1]})
        prior = now
    baseline = results[0]
    mismatches = []
    for recorded,observed in zip(baseline['frames_detail'],frames):
        lhs = [(d['id'],d['bbox']) for d in recorded['tracks']]
        rhs = [(d['id'],d['bbox']) for d in observed['live_tracks']]
        if lhs != rhs:
            mismatches.append(observed['index'])
    parity = not mismatches and baseline['events'] == live_events
    result = {'kind':'live-shadow-tracker-replay-not-field-accuracy',
              'baseline_parity':parity,'baseline_mismatch_frames':mismatches,
              'live_count_delta':{'in':prior[0]-start_in,'out':prior[1]-start_out},
              'live_events':live_events,'duration_seconds':capture['duration_seconds'],
              'capture_fps':capture['fps'],'capture_hook_median_ms':capture['record_median_ms'],
              'variants':[{'name':v,**result} for v,result in zip(replay.VARIANTS,results)],
              'limitations':capture['limitations']+[
                  'Live count is the reference behavior, not human ground truth.',
                  'No accuracy or improvement percentage is inferred from track counts.']}
    (stage/'live-tracking-results.json').write_text(json.dumps(result))
    print(json.dumps({k:v for k,v in result.items() if k!='variants'}))
    print(json.dumps([{'name':v['name'],**v['summary'],'events':v['events']} for v in result['variants']]))
    if not parity:
        raise RuntimeError('baseline replay differs from live; challenger cannot be interpreted as a fair comparison')


if __name__ == '__main__':
    main()
