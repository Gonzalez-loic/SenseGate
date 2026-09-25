"""Freeze a small private screening set. No uploading or production modification."""
import hashlib
import json
from pathlib import Path
import shutil
import time

STAGE = Path(__file__).resolve().parent
SOURCE = Path('/home/loic/people_counter/data/video_debug_clips')


if __name__ == '__main__':
    target = STAGE / 'screening-clips'
    target.mkdir(mode=0o700, exist_ok=False)
    clips = sorted((p for p in SOURCE.glob('*.mp4') if time.time()-p.stat().st_mtime > 60), key=lambda p: p.stat().st_mtime, reverse=True)[:12]
    items = []
    for p in clips:
        dest = target / p.name
        shutil.copy2(p, dest)
        items.append({'name': p.name, 'path': str(dest), 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})
    spec = {'clips': items, 'models': {'yolov8s': '/usr/share/hailo-models/yolov8s_h8l.hef', 'yolov11s': str(STAGE/'models/yolov11s.hef')}}
    assert len(items) >= 3
    (STAGE/'benchmark-input.json').write_text(json.dumps(spec, indent=2))
    print(json.dumps({'private_screening_clips': len(items), 'models': list(spec['models']), 'production_unchanged': True}))
