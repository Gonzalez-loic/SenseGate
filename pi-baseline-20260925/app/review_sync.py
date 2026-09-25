"""Copy locally retained evidence to the user's VPS; no AI calls or counter writes."""
import json
import os
from pathlib import Path
import secrets
import time
import urllib.request

BASE = Path('/home/loic/people_counter')
CLIPS = BASE / 'data/video_debug_clips'
CONFIG = BASE / 'config/device_config.env'
URL = 'https://sensegate.fr/api/review-clips/upload'
LIMIT = 16 * 1024**2


def config():
    result = {}
    for line in CONFIG.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def enabled(cfg):
    return all(str(cfg.get(k, '1')).lower() in ('1', 'true', 'yes', 'on') for k in ('VIDEO_AGENT_UPLOAD_ENABLED', 'VIDEO_AGENT_REVIEW_UPLOAD_ENABLED'))


def read(path):
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return {}


def write(path, data):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def upload(path, meta, cfg):
    video = path.with_suffix('.mp4')
    if video.stat().st_size > LIMIT:
        raise ValueError('clip exceeds review upload limit')
    boundary = 'SenseGateReview' + secrets.token_hex(12)
    def field(name, value):
        return f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    door = cfg.get('DEVICE_ID') or cfg.get('DOOR_ID') or 'porte-02'
    body = field('door_id', door) + field('meta', json.dumps(meta))
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.mp4"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
    body += video.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(URL, data=body, method='POST', headers={'Content-Type': 'multipart/form-data; boundary=' + boundary, 'X-SenseGate-Clip-Key': cfg['DETECTION_CLIP_UPLOAD_KEY'], 'User-Agent': 'SenseGateReviewSync/1'})
    with urllib.request.urlopen(req, timeout=90) as response:
        result = json.loads(response.read(16384))
    if result.get('ok') is not True:
        raise RuntimeError('No archive acknowledgement')
    return result


def sync_once():
    cfg = config()
    if not enabled(cfg) or not cfg.get('DETECTION_CLIP_UPLOAD_KEY'):
        return 0
    copied = 0
    for path in sorted(CLIPS.glob('miss_check_*.json'), reverse=True):
        if path.name.endswith('.upload.json'):
            continue
        meta = read(path)
        if not meta.get('local_retained_for_review') or not path.with_suffix('.mp4').is_file():
            continue
        if meta.get('start_timestamp', 0) + 72 * 3600 <= time.time():
            continue
        marker = path.with_suffix('.review-sync')
        prior = read(marker)
        if prior.get('ok') or prior.get('next_try', 0) > time.time():
            continue
        try:
            result = upload(path, meta, cfg)
            write(marker, {**result, 'uploaded_at': time.time()})
            copied += 1
            print(f'[REVIEW_SYNC] copied={meta.get("event_id")} archive={result.get("clip_id")}', flush=True)
        except Exception as exc:
            # Do not log URLs, headers, credentials or response bodies.
            write(marker, {'ok': False, 'next_try': time.time() + 300, 'error_type': type(exc).__name__})
            print(f'[REVIEW_SYNC] retry={path.stem} error={type(exc).__name__}', flush=True)
        if copied >= 5:
            break
    return copied


def run():
    last_success = None
    while True:
        try:
            copied = sync_once()
            if copied:
                last_success = time.time()
            write(BASE / 'data/review_sync_health.json', {'timestamp': time.time(), 'version': '2026-09-24-review-v1', 'last_copy_at': last_success, 'copied_last_batch': copied, 'enabled': enabled(config())})
        except Exception as exc:
            print(f'[REVIEW_SYNC] error={type(exc).__name__}', flush=True)
        time.sleep(15)
