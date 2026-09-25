import json
import os
import re
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2


def _bool(cfg, key, default=False):
    raw = str(cfg.get(key, "1" if default else "0")).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _int(cfg, key, default):
    try:
        return int(cfg.get(key, default))
    except Exception:
        return default


def _float(cfg, key, default):
    try:
        return float(cfg.get(key, default))
    except Exception:
        return default


class DetectionClipAgent:
    def __init__(self, cfg, data_dir, counter):
        self.cfg = cfg
        self.counter = counter
        self.data_dir = Path(data_dir)

        self.enabled = _bool(cfg, "DETECTION_CLIP_ENABLED", True)
        self.pre_seconds = _float(cfg, "DETECTION_CLIP_PRE_SECONDS", 2.0)
        self.post_seconds = _float(cfg, "DETECTION_CLIP_POST_SECONDS", 2.0)
        self.fps = max(1, _int(cfg, "DETECTION_CLIP_FPS", 10))
        self.width = max(320, _int(cfg, "DETECTION_CLIP_WIDTH", 960))
        self.max_files = max(10, _int(cfg, "DETECTION_CLIP_MAX_FILES", 100))
        self.max_seconds = max(5.0, _float(cfg, "DETECTION_CLIP_MAX_SECONDS", 25.0))

        self.upload_enabled = _bool(cfg, "DETECTION_CLIP_UPLOAD_ENABLED", False)
        self.upload_url = str(cfg.get("DETECTION_CLIP_UPLOAD_URL", "")).strip()
        self.upload_key = str(cfg.get("DETECTION_CLIP_UPLOAD_KEY", "")).strip()
        self.delete_local_after_upload = _bool(cfg, "DETECTION_CLIP_DELETE_LOCAL_AFTER_UPLOAD", True)
        self.upload_timeout = _int(cfg, "DETECTION_CLIP_UPLOAD_TIMEOUT", 45)

        self.clip_dir = self.data_dir / "detection_clips"
        self.clip_dir.mkdir(parents=True, exist_ok=True)

        self.prebuffer = deque(maxlen=max(1, int(self.pre_seconds * self.fps)))
        self.last_buffer_ts = 0.0
        self.last_write_ts = 0.0

        self.writer = None
        self.active = False
        self.current_path = None
        self.current_meta_path = None
        self.start_ts = None
        self.last_detection_ts = None
        self.frames_written = 0
        self.frame_size = None
        self.start_counts = None
        self.max_persons_seen = 0

        print(
            f"[CLIP_AGENT] enabled={self.enabled} upload={self.upload_enabled} dir={self.clip_dir}",
            flush=True,
        )

    def _normalize_frame(self, frame):
        img = frame.copy()

        if len(img.shape) == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        h, w = img.shape[:2]
        if w != self.width:
            ratio = self.width / float(w)
            img = cv2.resize(img, (self.width, int(h * ratio)))

        return img

    def _safe_name(self, value):
        value = str(value or "unknown")
        value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)
        return value[:120] or "unknown"

    def _write_json(self, path, payload):
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _open_writer(self, frame):
        img = self._normalize_frame(frame)
        h, w = img.shape[:2]
        self.frame_size = (w, h)

        ts_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"detection_{ts_name}"

        mp4_path = self.clip_dir / f"{base}.mp4"
        writer = cv2.VideoWriter(
            str(mp4_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self.fps,
            self.frame_size,
        )

        if writer.isOpened():
            self.current_path = mp4_path
        else:
            avi_path = self.clip_dir / f"{base}.avi"
            writer = cv2.VideoWriter(
                str(avi_path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                self.fps,
                self.frame_size,
            )
            self.current_path = avi_path

        if not writer.isOpened():
            print("[CLIP_ERROR] impossible ouvrir VideoWriter", flush=True)
            return False

        self.writer = writer
        self.current_meta_path = self.current_path.with_suffix(".json")
        self.active = True
        self.start_ts = time.time()
        self.frames_written = 0
        self.start_counts = self.counter.get_counts()
        self.max_persons_seen = 0
        self.last_write_ts = 0.0

        print(f"[CLIP_START] {self.current_path}", flush=True)

        for buffered in list(self.prebuffer):
            self._write_frame(buffered, force=True)

        return True

    def _write_frame(self, frame, force=False):
        if not self.writer:
            return

        now = time.time()
        if not force and now - self.last_write_ts < 1.0 / float(self.fps):
            return

        img = self._normalize_frame(frame)

        if self.frame_size:
            w, h = self.frame_size
            if img.shape[1] != w or img.shape[0] != h:
                img = cv2.resize(img, (w, h))

        self.writer.write(img)
        self.frames_written += 1
        self.last_write_ts = now

    def _cleanup_old_files(self):
        clips = sorted(
            list(self.clip_dir.glob("detection_*.mp4")) + list(self.clip_dir.glob("detection_*.avi")),
            key=lambda p: p.stat().st_mtime,
        )

        extra = len(clips) - self.max_files
        if extra <= 0:
            return

        for clip in clips[:extra]:
            try:
                clip.unlink(missing_ok=True)
                clip.with_suffix(".json").unlink(missing_ok=True)
                print(f"[CLIP_CLEANUP] {clip}", flush=True)
            except Exception as e:
                print(f"[CLIP_CLEANUP_ERROR] {e}", flush=True)

    def _upload_worker(self, video_path, meta_path, meta_payload):
        try:
            if not self.upload_url or not self.upload_key:
                print("[CLIP_UPLOAD_ERROR] url ou clé manquante", flush=True)
                return

            video_path = Path(video_path)
            meta_path = Path(meta_path)

            if not video_path.exists():
                print(f"[CLIP_UPLOAD_ERROR] fichier absent {video_path}", flush=True)
                return

            door_id = str(
                self.cfg.get(
                    "DEVICE_ID",
                    self.cfg.get("DOOR_ID", self.cfg.get("DOOR_NAME", "unknown")),
                )
            )

            boundary = "----SenseGateBoundary" + str(int(time.time() * 1000))

            def field(name, value):
                return (
                    f"--{boundary}\r\n"
                    f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                    f"{value}\r\n"
                ).encode("utf-8")

            def file_field(name, filename, content_type, data):
                filename = filename.replace('"', "_")
                return (
                    f"--{boundary}\r\n"
                    f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8") + data + b"\r\n"

            meta_payload = dict(meta_payload or {})
            meta_payload["door_id"] = door_id
            meta_payload["pi_uploaded_at"] = time.time()

            content_type = "video/mp4" if video_path.suffix.lower() == ".mp4" else "video/x-msvideo"

            body = b""
            body += field("door_id", door_id)
            body += field("meta", json.dumps(meta_payload))
            body += file_field("file", video_path.name, content_type, video_path.read_bytes())
            body += f"--{boundary}--\r\n".encode("utf-8")

            req = urllib.request.Request(
                self.upload_url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "X-SenseGate-Clip-Key": self.upload_key,
                    "User-Agent": "SenseGatePiClipUploader/1.0",
                },
            )

            with urllib.request.urlopen(req, timeout=self.upload_timeout) as resp:
                response_body = resp.read().decode("utf-8", errors="replace")
                ok = 200 <= resp.status < 300
                status = resp.status

            print(
                f"[CLIP_UPLOAD] ok={ok} status={status} file={video_path.name} response={response_body[:250]}",
                flush=True,
            )

            if ok:
                local_meta = {}
                if meta_path.exists():
                    try:
                        local_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except Exception:
                        local_meta = {}

                local_meta["uploaded_to_vps"] = True
                local_meta["uploaded_at"] = time.time()
                local_meta["upload_response"] = response_body[:1000]

                if self.delete_local_after_upload:
                    video_path.unlink(missing_ok=True)
                    local_meta["local_video_deleted_after_upload"] = True

                self._write_json(meta_path, local_meta)

        except Exception as e:
            print(f"[CLIP_UPLOAD_ERROR] {e}", flush=True)

    def _close_writer(self):
        if not self.writer:
            return

        self.writer.release()

        end_counts = self.counter.get_counts()

        meta = {
            "file": str(self.current_path),
            "start_timestamp": self.start_ts,
            "end_timestamp": time.time(),
            "duration_seconds": round(time.time() - self.start_ts, 2) if self.start_ts else None,
            "frames_written": self.frames_written,
            "fps": self.fps,
            "start_counts": self.start_counts,
            "end_counts": end_counts,
            "max_persons_seen": self.max_persons_seen,
            "reason": "ai_detection_sequence",
        }

        try:
            self._write_json(self.current_meta_path, meta)
        except Exception as e:
            print(f"[CLIP_META_ERROR] {e}", flush=True)

        print(f"[CLIP_END] {self.current_path} frames={self.frames_written}", flush=True)

        video_path = self.current_path
        meta_path = self.current_meta_path

        self.writer = None
        self.active = False
        self.current_path = None
        self.current_meta_path = None
        self.start_ts = None
        self.last_detection_ts = None
        self.frames_written = 0
        self.frame_size = None
        self.start_counts = None
        self.max_persons_seen = 0

        if self.upload_enabled:
            t = threading.Thread(
                target=self._upload_worker,
                args=(video_path, meta_path, meta),
                daemon=True,
            )
            t.start()
        else:
            self._cleanup_old_files()

    def update(self, frame, detections):
        if not self.enabled:
            return

        now = time.time()
        has_detection = bool(detections)

        if now - self.last_buffer_ts >= 1.0 / float(self.fps):
            self.prebuffer.append(frame.copy())
            self.last_buffer_ts = now

        if has_detection:
            self.last_detection_ts = now
            self.max_persons_seen = max(self.max_persons_seen, len(detections))

            if not self.active:
                if not self._open_writer(frame):
                    return

        if self.active:
            self._write_frame(frame)

            too_long = self.start_ts and (now - self.start_ts) >= self.max_seconds
            ended = self.last_detection_ts and (now - self.last_detection_ts) >= self.post_seconds

            if too_long or ended:
                self._close_writer()
