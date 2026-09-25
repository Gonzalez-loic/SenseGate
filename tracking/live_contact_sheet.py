"""Private visual evidence around live count, never published in Git."""
import json
from pathlib import Path
import cv2
import numpy as np

stage = Path(__file__).resolve().parent
capture = json.loads((stage/'live-01/live-trace.json').read_text())
result = json.loads((stage/'live-tracking-results.json').read_text())
challenger = {r['frame']:r for r in result['variants'][1]['frames_detail']}
observed = {r['index']:r for r in capture['frames']}
available = sorted(int(p.stem) for p in (stage/'live-01/private-frames').glob('*.jpg'))
event = result['live_events'][0]['frame']
selected = sorted(set(min(available,key=lambda x:abs(x-target)) for target in [event-25,event-18,event-10,event-3,event+5,event+13]))
tiles=[]
for idx in selected:
    row=observed[idx]
    img=cv2.imread(str(stage/f'live-01/private-frames/{idx:06d}.jpg'))
    img=cv2.resize(img,(640,360))
    for tracks,color,prefix in [(row['live_tracks'],(0,0,255),'LIVE'),(challenger[idx]['tracks'],(255,255,0),'BT')]:
        for d in tracks:
            x0,y0,x1,y1=[int(x/2) for x in d['bbox']]
            cv2.rectangle(img,(x0,y0),(x1,y1),color,2)
            cv2.putText(img,f"{prefix} {d['id']} {d['score']:.2f}",(max(0,x0),max(15,y0)),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
    cv2.line(img,(0,round(449/2)),(640,round(449/2)),(0,255,255),1)
    band=np.zeros((30,640,3),np.uint8)
    cv2.putText(band,f"frame {idx} t={row['time']:.2f}s IN={row['live_in']} OUT={row['live_out']}",(5,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
    tiles.append(np.vstack([band,img]))
if len(tiles)%2:
    tiles.append(np.zeros_like(tiles[0]))
cv2.imwrite(str(stage/'private-live-event.jpg'),np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)]))
print(json.dumps({'selected_frames':selected,'live_event':event,'private_sheet':'private-live-event.jpg'}))
print(json.dumps([{'frame':idx,'t':r['time'],'low':r['detections'],'live':r['live_tracks'],'byte':challenger[idx]['tracks']}
                  for idx,r in observed.items() if event-30<=idx<=event+15 and (r['detections'] or idx%5==0)]))
