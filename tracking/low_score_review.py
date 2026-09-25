"""Private contact sheets for primary events during this bounded shadow capture."""
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    stage=Path(__file__).resolve().parent
    capture=json.loads((stage/'live-trace.json').read_text())
    frames=capture['frames']
    available=[r for r in frames if r.get('private_frame') and (stage/'private-frames'/r['private_frame']).exists()]
    events=[]
    prior=(frames[0]['live_in'],frames[0]['live_out'])
    for r in frames:
        current=(r['live_in'],r['live_out'])
        if current!=prior:
            events.append(r)
        prior=current
    for number,event in enumerate(events,1):
        selections=[min(available,key=lambda r:abs(r['time']-event['time']-dt)) for dt in [-.9,-.5,-.1,.2,.6,1.0]]
        tiles=[]
        for r in selections:
            img=cv2.imread(str(stage/'private-frames'/r['private_frame']))
            img=cv2.resize(img,(640,360))
            for track in r['shadow']['tracks']:
                x0,y0,x1,y1=[int(x/2) for x in track['bbox']]
                color=(255,255,0) if track['weak'] else (0,255,0)
                cv2.rectangle(img,(x0,y0),(x1,y1),color,2)
                cv2.putText(img,f"C{track['id']} {track['score']:.2f}",(max(0,x0),max(15,y0)),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
            cv2.line(img,(0,round(449/2)),(639,round(449/2)),(0,255,255),1)
            band=np.zeros((32,640,3),np.uint8)
            cv2.putText(band,f"f{r['index']} t{r['time']:.2f}s LIVE {r['live_in']}/{r['live_out']} CAND {r['shadow']['in_count']}/{r['shadow']['out_count']}",(5,23),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
            tiles.append(np.vstack([band,img]))
        cv2.imwrite(str(stage/f'private-low-score-event-{number}.jpg'),np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,6,2)]))
    print(json.dumps(dict(events=[dict(frame=r['index'],time=r['time'],in_count=r['live_in'],out_count=r['live_out']) for r in events],sheets=len(events))))


if __name__=='__main__':
    main()
