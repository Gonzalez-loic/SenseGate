"""Offline detection-only replay. No imports of the counter or sync client.

Input clips contain overlays and are not raw inference frames: this is a screening
benchmark, NOT a field-accuracy measurement. Run only with exclusive Hailo access.
"""
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from picamera2.devices import Hailo

STAGE = Path(__file__).resolve().parent


def prepare(image, width, height, mode):
    if mode.endswith('_rgb'):
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mode = mode[:-4]
    h, w = image.shape[:2]
    if mode == 'stretch':
        return np.ascontiguousarray(cv2.resize(image, (width, height))), (width/w, height/h, 0, 0)
    ratio = min(width/w, height/h)
    nw, nh = round(w*ratio), round(h*ratio)
    x, y = (width-nw)//2, (height-nh)//2
    result = np.full((height, width, 3), 114, np.uint8)
    result[y:y+nh, x:x+nw] = cv2.resize(image, (nw, nh))
    return result, (nw/w, nh/h, x, y)


def persons(output, width, height, transform, source_width, source_height):
    if isinstance(output, dict):
        raise ValueError('Raw multi-head model requires a separately validated decoder; not supported')
    sx, sy, px, py = transform
    found = []
    for box in output[0]:
        y0, x0, y1, x1, score = map(float, box[:5])
        if score < .2:
            continue
        bounds = [(x0*width-px)/sx, (y0*height-py)/sy, (x1*width-px)/sx, (y1*height-py)/sy]
        bounds = [max(0., min(limit, val)) for val, limit in zip(bounds, [source_width, source_height, source_width, source_height])]
        found.append({'score': score, 'bbox': bounds})
    return found


def run():
    start = time.monotonic()
    spec = json.loads((STAGE / 'benchmark-input.json').read_text())
    result = {'kind': 'screening-only-not-counting-accuracy', 'limitations': [
        'Rendered compressed clips, not original inference inputs',
        'Selected suspect clips are not representative of all traffic',
        'No human per-frame ground truth: no precision or recall claim',
        'More detections or higher scores do not establish better counting'],
        'started_at': time.time(), 'variants': [], 'clips': spec['clips']}
    for model, path in spec['models'].items():
        try:
            with Hailo(path) as hailo:
                mh, mw, _ = hailo.get_input_shape()
                for mode in spec.get('preprocessing', ['stretch', 'letterbox']):
                    variant = {'model': model, 'preprocessing': mode, 'frames': [], 'inference_ms': []}
                    for clip in spec['clips']:
                        if time.monotonic()-start > 240:
                            raise TimeoutError('screening exceeds 240-second bound')
                        cap = cv2.VideoCapture(clip['path'])
                        try:
                            if not cap.isOpened():
                                raise ValueError('video unavailable')
                            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            # Same evenly spaced real decoded frames for every variant.
                            indices = sorted(set(np.linspace(0, max(0, count-1), min(count, 32), dtype=int).tolist()))
                            for index in indices:
                                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                                ok, frame = cap.read()
                                if not ok:
                                    raise ValueError('frame decode failed')
                                h, w = frame.shape[:2]
                                prepared, transform = prepare(frame, mw, mh, mode)
                                begin = time.perf_counter()
                                raw = hailo.run(prepared)
                                elapsed = 1000*(time.perf_counter()-begin)
                                boxes = persons(raw, mw, mh, transform, w, h)
                                # Production min-size filter expressed in main 1280x720 coordinates.
                                accepted = [b for b in boxes if b['score'] >= .3 and
                                            (b['bbox'][2]-b['bbox'][0])*1280/w >= 30 and
                                            (b['bbox'][3]-b['bbox'][1])*720/h >= 30]
                                variant['inference_ms'].append(elapsed)
                                variant['frames'].append({'clip': clip['name'], 'index': index,
                                    'seconds': index/fps if fps else None, 'returned_persons': boxes,
                                    'accepted_count': len(accepted)})
                        finally:
                            cap.release()
                    scores = [b['score'] for f in variant['frames'] for b in f['returned_persons'] if b['score'] >= .3]
                    variant['summary'] = {'frames': len(variant['frames']),
                        'frames_with_accepted_person': sum(f['accepted_count'] > 0 for f in variant['frames']),
                        'accepted_detections': sum(f['accepted_count'] for f in variant['frames']),
                        'mean_returned_score_above_03': float(np.mean(scores)) if scores else None,
                        'median_inference_ms': float(np.median(variant['inference_ms'])),
                        'p95_inference_ms': float(np.percentile(variant['inference_ms'], 95))}
                    result['variants'].append(variant)
                    (STAGE / 'benchmark-results.json').write_text(json.dumps(result))
        except Exception as exc:
            result.setdefault('errors', []).append({'model': model, 'error': str(exc)})
    result['completed_at'] = time.time()
    (STAGE / 'benchmark-results.json').write_text(json.dumps(result))


if __name__ == '__main__':
    run()
