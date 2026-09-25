"""Private visual review of every extra replay count, not public media."""
import json
from pathlib import Path
import cv2
import numpy as np

stage = Path(__file__).resolve().parent
result = json.loads((stage/'tracking-results.json').read_text())
variants = {v['name']:v for v in result['variants']}
spec = json.loads((stage.parent/'bench-20260925/benchmark-input.json').read_text())
paths = {c['name']:c['path'] for c in spec['clips']}
cases = [('miss_check_20260925_110351.mp4',57),('miss_check_20260925_102201.mp4',48)]
for case,(name,event) in enumerate(cases,1):
    clip = next(c for c in variants['byte_08_strict']['clips'] if c['clip']==name)
    details = {r['frame']:r for r in clip['frames_detail']}
    indices = [max(0,event+d) for d in [-8,-6,-4,-2,0,2]]
    tiles = []
    cap = cv2.VideoCapture(paths[name])
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES,idx)
        ok,img = cap.read()
        if not ok:
            img=np.zeros((360,640,3),np.uint8)
        h,w=img.shape[:2]
        for t in details.get(idx,{}).get('tracks',[]):
            x0,y0,x1,y1=t['bbox']
            a,b,c,d=round(x0*w/1280),round(y0*h/720),round(x1*w/1280),round(y1*h/720)
            cv2.rectangle(img,(a,b),(c,d),(255,255,0),2)
            cv2.putText(img,f"BT {t['id']} {t['score']:.2f}",(a,max(15,b)),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,0),1)
        img=cv2.resize(img,(640,360))
        band=np.zeros((30,640,3),np.uint8)
        cv2.putText(band,f"case {case} / frame {idx} / event {event}",(5,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
        tiles.append(np.vstack([band,img]))
    cap.release()
    sheet=np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,6,2)])
    cv2.imwrite(str(stage/f'private-event-{case}.jpg'),sheet)
print(json.dumps({'private_event_sheets':len(cases)}))
