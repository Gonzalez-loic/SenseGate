"""Private visual QA of new detections, not a representative accuracy sample."""
import json
from pathlib import Path
import cv2
import numpy as np

stage = Path(__file__).resolve().parent
result = json.loads((stage/'benchmark-results.json').read_text())
a, b = result['variants'][:2]
base = {(f['clip'], f['index']): f for f in a['frames']}
choices, seen = [], set()
for f in b['frames']:
    key = f['clip'], f['index']
    if f['clip'] not in seen and f['accepted_count'] > 0 and base[key]['accepted_count'] == 0:
        choices.append(f)
        seen.add(f['clip'])
    if len(choices) >= 6:
        break
images, evidence = [], []
paths = {c['name']: c['path'] for c in result['clips']}
for i, frame in enumerate(choices):
    cap = cv2.VideoCapture(paths[frame['clip']])
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame['index'])
    ok, image = cap.read()
    cap.release()
    assert ok
    for box in frame['returned_persons']:
        if box['score'] >= .3:
            x0,y0,x1,y1 = map(round, box['bbox'])
            cv2.rectangle(image, (x0,y0), (x1,y1), (255,255,0), 2)
    image = cv2.resize(image, (640,360))
    banner = np.zeros((32,640,3), np.uint8)
    cv2.putText(banner, f"Sample {i+1} - letterbox only - frame {frame['index']}", (5,23), cv2.FONT_HERSHEY_SIMPLEX, .65, (255,255,255), 1)
    images.append(np.vstack([banner,image]))
    evidence.append({'sample': i+1, 'clip': frame['clip'], 'frame': frame['index']})
while len(images) < 6:
    images.append(np.zeros((392,640,3),np.uint8))
sheet = np.vstack([np.hstack(images[i:i+2]) for i in range(0,6,2)])
cv2.imwrite(str(stage/'private-contact-sheet.jpg'), sheet)
(stage/'private-contact-sheet.json').write_text(json.dumps(evidence,indent=2))
print(json.dumps({'private_samples': len(choices)}))
