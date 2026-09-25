"""Bounded Pi-only observation of ORIGINAL engine decisions, never a new tracker.

Run only via run_live_trace.py. The entrypoint has already restored itself on disk.
This adds two in-memory hooks to the verified source, leaving the original model,
counter, persistence, preview and sync path intact. Private evidence stays in STAGE.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

STAGE = Path(__file__).resolve().parent
APP = Path('/home/loic/people_counter/app')
EXPECTED = '6c665caf43db871297d4be7849bc6cda512f13f6026a4ad93386eb38f7ff2ba7'


def instrument(source):
    needle = '                tracked_detections = counter.update(detections)'
    assert source.count(needle) == 1
    source = source.replace(needle,
        '                _trace_mono = time.monotonic()\n' + needle + '\n'
        '                _trace.record(_trace_mono, results, frame_lores, detections, tracked_detections, counter)')
    needle = '                time.sleep(0.01)'
    assert source.count(needle) == 1
    # Leave through camera/Hailo context managers only AFTER normal persistence.
    return source.replace(needle, needle + '\n                if _trace.due():\n                    break')


class Recorder:
    def __init__(self, duration=180):
        self.duration = duration
        self.start = time.monotonic()
        self.rows = []
        self.errors = []
        self.overheads = []
        self.last_image = -1e10
        self.last_person = -1e10
        self.dropped_images = 0
        self.queue = queue.Queue(maxsize=4)
        self.directory = STAGE/'private-frames'
        self.directory.mkdir(mode=0o700, exist_ok=False)
        self.worker = threading.Thread(target=self.write_images, daemon=True)
        self.worker.start()

    def configure(self, namespace):
        self.extract = namespace['extract_persons']
        cfg = namespace['cfg']
        self.width, self.height = int(cfg['CAM_WIDTH']), int(cfg['CAM_HEIGHT'])
        self.threshold = float(cfg['MIN_CONFIDENCE'])

    def record(self, mono, results, frame, detections, tracked, counter):
        started = time.perf_counter()
        try:
            if self.errors or len(self.rows) >= 10000:
                return
            low = self.extract(results, self.width, self.height, threshold=.2)
            index = len(self.rows)
            row = {'index':index, 'time':mono-self.start, 'wall_time':time.time(),
                   'detections':low, 'primary_detections':detections,
                   'live_tracks':[{'id':d['track_id'], 'bbox':d['bbox'], 'score':d['score']} for d in tracked],
                   'live_in':counter.in_count, 'live_out':counter.out_count}
            self.rows.append(row)
            if low:
                self.last_person = mono
            # Bounded, asynchronous visual evidence, no second inference.
            if mono-self.last_image >= .20 and mono-self.last_person < 2.0:
                try:
                    self.queue.put_nowait((index, frame.copy()))
                    self.last_image = mono
                    row['private_frame'] = f'{index:06d}.jpg'
                except queue.Full:
                    self.dropped_images += 1
        except Exception as exc:
            # Never break production counting because evidence collection fails.
            self.errors.append(type(exc).__name__ + ': ' + str(exc))
        finally:
            self.overheads.append(1000*(time.perf_counter()-started))

    def write_images(self):
        import cv2
        total = 0
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                index, frame = item
                if total >= 96*1024*1024:
                    self.dropped_images += 1
                    continue
                ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    raw = encoded.tobytes()
                    (self.directory/f'{index:06d}.jpg').write_bytes(raw)
                    total += len(raw)
            except Exception as exc:
                self.errors.append('image: '+type(exc).__name__)
            finally:
                self.queue.task_done()

    def due(self):
        return time.monotonic()-self.start >= self.duration or bool(self.errors)

    def finish(self):
        import statistics
        self.queue.put(None, timeout=3)
        self.worker.join(timeout=5)
        if self.worker.is_alive():
            self.errors.append('image worker did not finish')
        rows = self.rows
        fps = (len(rows)-1)/(rows[-1]['time']-rows[0]['time']) if len(rows)>1 else 0
        result = {'kind':'live-primary-decision-trace', 'completed_at':time.time(),
                  'duration_seconds':time.monotonic()-self.start, 'fps':fps,
                  'primary_threshold':self.threshold, 'frames':rows, 'errors':self.errors,
                  'dropped_images':self.dropped_images,
                  'record_median_ms':statistics.median(self.overheads) if self.overheads else None,
                  'limitations':['A short capture is not a field accuracy estimate.',
                                 'Timestamps precede CounterLogic.update by a few microseconds.',
                                 'Raw input images are sampled at <=5 FPS; all detections are logged.']}
        temporary = STAGE/'live-trace.json.tmp'
        temporary.write_text(json.dumps(result))
        os.replace(temporary, STAGE/'live-trace.json')
        print(json.dumps({k:v for k,v in result.items() if k!='frames'}), flush=True)


def main():
    os.umask(0o077)
    raw = (APP/'people_counter_hailo.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED
    assert not (STAGE/'live-trace.json').exists(), 'one-shot capture'
    sys.path.insert(0, str(APP))
    trace = Recorder()
    namespace = {'__name__':'observed_primary_engine', '__file__':str(APP/'people_counter_hailo.py'), '_trace':trace}
    try:
        exec(compile(instrument(raw.decode()), str(APP/'people_counter_hailo.py'), 'exec'), namespace)
        trace.configure(namespace)
        (STAGE/'capture-started.json').write_text(json.dumps({'started_at':time.time()}))
        namespace['main']()
    finally:
        trace.finish()


if __name__ == '__main__':
    main()
