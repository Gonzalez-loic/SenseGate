"""Single bounded Hailo pass over every frame; no counting or server connection.

Installed as benchmark_pi.py in the dedicated maintenance staging directory.
Use the system interpreter, preserving production OpenCV/Hailo versions.
"""
import hashlib
import json
from pathlib import Path
import time
import cv2
from picamera2.devices import Hailo

STAGE = Path(__file__).resolve().parent
BASE = STAGE.parent/'bench-20260925'


def main():
    spec = json.loads((BASE/'benchmark-input.json').read_text())
    result = {'kind': 'all-decoded-frames-detection-cache', 'started_at': time.time(),
              'limitations': ['rendered compressed clips with overlays',
                              'video cadence differs from live inference cadence',
                              'selected suspect clips, no representative ground truth'],
              'model': '/usr/share/hailo-models/yolov8s_h8l.hef',
              'preprocessing': 'stretch_BGR_matches_current_memory_order', 'clips': []}
    start = time.monotonic()
    with Hailo(result['model']) as model:
        mh,mw,_ = model.get_input_shape()
        for source in spec['clips']:
            cap = cv2.VideoCapture(source['path'])
            assert cap.isOpened()
            fps = cap.get(cv2.CAP_PROP_FPS)
            assert 0 < fps <= 60
            clip = {'name': source['name'], 'sha256': source['sha256'], 'fps': fps, 'frames': []}
            index = 0
            try:
                while True:
                    if time.monotonic()-start > 220:
                        raise TimeoutError('cache inference exceeds safe duration')
                    ok, image = cap.read()
                    if not ok:
                        break
                    raw = model.run(cv2.resize(image,(mw,mh)))
                    observations = []
                    for item in raw[0]:
                        y0,x0,y1,x1,score = map(float,item[:5])
                        x0,x1,y0,y1 = int(x0*1280),int(x1*1280),int(y0*720),int(y1*720)
                        if score < .2 or x1-x0 < 30 or y1-y0 < 30:
                            continue
                        observations.append({'bbox':[x0,y0,x1,y1], 'cx':int((x0+x1)/2),
                                             'cy':int((y0+y1)/2), 'score':score, 'class_id':0})
                    clip['frames'].append({'index':index,'time':index/fps,'detections':observations})
                    index += 1
            finally:
                cap.release()
            result['clips'].append(clip)
            (STAGE/'detection-cache.json').write_text(json.dumps(result))
    result['completed_at'] = time.time()
    (STAGE/'detection-cache.json').write_text(json.dumps(result))
    summary = {'completed_at': result['completed_at'], 'clips': len(result['clips']),
               'frames': sum(len(c['frames']) for c in result['clips']),
               'cache_sha256': hashlib.sha256((STAGE/'detection-cache.json').read_bytes()).hexdigest()}
    (STAGE/'benchmark-results.json').write_text(json.dumps(summary))


if __name__ == '__main__':
    main()
