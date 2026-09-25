#!/usr/bin/env python3
import json
import os
import shutil
import time
import threading
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2


BASE_DIR = Path("/home/loic/people_counter")
CONFIG_FILE = BASE_DIR / "config/device_config.env"
DATA_DIR = BASE_DIR / "data"
PREVIEW_FILE = DATA_DIR / "preview.jpg"
DETECTIONS_FILE = DATA_DIR / "detections.json"
COUNTS_FILE = DATA_DIR / "counts.json"
CLIP_DIR = DATA_DIR / "video_debug_clips"

CLIP_DIR.mkdir(parents=True, exist_ok=True)


def load_env(path):
    cfg = {}
    if not path.exists():
        return cfg

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip().strip('"').strip("'")
    return cfg


def cfg_bool(cfg, key, default=False):
    raw = str(cfg.get(key, "1" if default else "0")).lower().strip()
    return raw in ("1", "true", "yes", "on")


def cfg_int(cfg, key, default):
    try:
        return int(cfg.get(key, default))
    except Exception:
        return default


def cfg_float(cfg, key, default):
    try:
        return float(cfg.get(key, default))
    except Exception:
        return default


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write_json(path, payload):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_total_count(counts):
    try:
        return int(counts.get("in", 0)) + int(counts.get("out", 0))
    except Exception:
        return 0


def get_detection_items(state):
    if isinstance(state, list):
        return state

    if isinstance(state, dict):
        detections = state.get("detections", [])
        if isinstance(detections, list):
            return detections

    return []


def get_track_items(state):
    tracks = []

    if isinstance(state, dict):
        for key in ("tracks", "finished_tracks"):
            items = state.get(key, [])
            if isinstance(items, list):
                tracks.extend([item for item in items if isinstance(item, dict)])

        for det in get_detection_items(state):
            if not isinstance(det, dict):
                continue
            track_state = det.get("track_state")
            if isinstance(track_state, dict):
                tracks.append(track_state)

    elif isinstance(state, list):
        for det in state:
            if not isinstance(det, dict):
                continue
            track_state = det.get("track_state")
            if isinstance(track_state, dict):
                tracks.append(track_state)

    return tracks


def cfg_calibration_mode(cfg):
    for key in (
        "CALIBRATION_MODE",
        "VIDEO_AGENT_CALIBRATION_MODE",
        "CAMERA_CALIBRATION",
        "LINE_CALIBRATION",
        "COUNTING_CALIBRATION",
    ):
        if cfg_bool(cfg, key, False):
            return True
    return False


def track_is_probable_missed(track):
    if not isinstance(track, dict):
        return False

    if track.get("already_counted") or track.get("counted_direction"):
        return False

    return bool(track.get("missed_candidate") or track.get("probable_crossing"))


def compact_track(track):
    keys = [
        "track_id",
        "first_position",
        "last_position",
        "start_side",
        "end_side",
        "duration_visible",
        "distance_travelled",
        "already_counted",
        "counted_direction",
        "counted_directions",
        "hits",
        "missed_frames",
        "probable_crossing",
        "probable_direction",
        "missed_candidate",
        "active",
        "finished_at",
        "finish_reason",
        "history",
        "stable_side",
        "candidate_side",
        "candidate_hits",
        "crossing_count",
        "recovery_count",
        "last_match_mode",
        "diagnostic_reasons",
    ]
    return {key: track.get(key) for key in keys if key in track}


def current_config_snapshot(cfg):
    return {
        "LINE_ORIENTATION": cfg.get("LINE_ORIENTATION"),
        "LINE_POSITION": cfg_int(cfg, "LINE_POSITION", cfg_int(cfg, "LINE_Y", 0)),
        "ENTER_DIRECTION": cfg.get("ENTER_DIRECTION"),
        "MIN_CONFIDENCE": cfg_float(cfg, "MIN_CONFIDENCE", 0.4),
        "MAX_DISTANCE": cfg_int(cfg, "MAX_DISTANCE", 300),
        "MAX_DISAPPEARED": cfg_int(cfg, "MAX_DISAPPEARED", 45),
        "COUNTING_BAND_SIZE": cfg_int(cfg, "COUNTING_BAND_SIZE", 20),
        "MIN_TRACK_HITS": cfg_int(cfg, "MIN_TRACK_HITS", 1),
        "COUNT_MODE": cfg.get("COUNT_MODE", "center"),
        "TRACK_MATCH_DISTANCE": cfg_float(cfg, "TRACK_MATCH_DISTANCE", 180),
        "TRACK_RECOVERY_MAX_DISTANCE": cfg_float(cfg, "TRACK_RECOVERY_MAX_DISTANCE", 280),
        "TRACK_RECOVERY_MAX_ERROR": cfg_float(cfg, "TRACK_RECOVERY_MAX_ERROR", 120),
        "COUNT_CONFIRM_FRAMES": cfg_int(cfg, "COUNT_CONFIRM_FRAMES", 2),
        "COUNT_CONFIRM_SECONDS": cfg_float(cfg, "COUNT_CONFIRM_SECONDS", 0.06),
        "COUNT_MAX_GAP_SECONDS": cfg_float(cfg, "COUNT_MAX_GAP_SECONDS", 0.5),
    }


def track_last_timestamp(track):
    if not isinstance(track, dict):
        return None

    for key in ("finished_at", "last_seen"):
        try:
            value = track.get(key)
            if value is not None:
                return float(value)
        except Exception:
            pass

    last_position = track.get("last_position")
    if isinstance(last_position, dict):
        try:
            value = last_position.get("timestamp")
            if value is not None:
                return float(value)
        except Exception:
            pass

    return None


def upload_json_event(meta_payload, cfg):
    upload_url = cfg.get(
        "VIDEO_AGENT_EVENT_URL",
        "https://sensegate.fr/api/debug/clips/event",
    ).strip()
    upload_key = cfg.get("DETECTION_CLIP_UPLOAD_KEY", "").strip()
    timeout = cfg_int(cfg, "DETECTION_CLIP_UPLOAD_TIMEOUT", 45)

    if not upload_url or not upload_key:
        print("[VIDEO_AGENT_EVENT_ERROR] url ou cle manquante", flush=True)
        return

    try:
        req = urllib.request.Request(
            upload_url,
            data=json.dumps(meta_payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-SenseGate-Clip-Key": upload_key,
                "User-Agent": "SenseGateVideoAgent/2.0",
            },
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            response = resp.read().decode("utf-8", errors="replace")
            ok = 200 <= resp.status < 300
            status = resp.status

        print(
            f"[VIDEO_AGENT_EVENT] ok={ok} status={status} event={meta_payload.get('event_id')} response={response[:160]}",
            flush=True,
        )
        return ok
    except Exception as exc:
        print(f"[VIDEO_AGENT_EVENT_ERROR] {exc}", flush=True)


def upload_clip(video_path, meta_path, meta_payload, cfg):
    upload_enabled = cfg_bool(cfg, "VIDEO_AGENT_UPLOAD_ENABLED", True)
    upload_url = cfg.get("DETECTION_CLIP_UPLOAD_URL", "").strip()
    upload_key = cfg.get("DETECTION_CLIP_UPLOAD_KEY", "").strip()
    timeout = cfg_int(cfg, "DETECTION_CLIP_UPLOAD_TIMEOUT", 45)
    delete_local = cfg_bool(cfg, "VIDEO_AGENT_DELETE_LOCAL_AFTER_UPLOAD", True)

    if not upload_enabled:
        return

    if not upload_url or not upload_key:
        print("[VIDEO_AGENT_UPLOAD_ERROR] url ou cle manquante", flush=True)
        return

    try:
        video_path = Path(video_path)
        meta_path = Path(meta_path)

        if not video_path.exists():
            print(f"[VIDEO_AGENT_UPLOAD_ERROR] fichier absent {video_path}", flush=True)
            return

        door_id = cfg.get("DEVICE_ID") or cfg.get("DOOR_ID") or "porte-02"
        boundary = "----SenseGateVideoAgent" + str(int(time.time() * 1000))

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
        meta_payload["agent"] = "sensegate_video_agent"

        body = b""
        body += field("door_id", door_id)
        body += field("meta", json.dumps(meta_payload))
        body += file_field("file", video_path.name, "video/mp4", video_path.read_bytes())
        body += f"--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            upload_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-SenseGate-Clip-Key": upload_key,
                "User-Agent": "SenseGateVideoAgent/2.0",
            },
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            response = resp.read().decode("utf-8", errors="replace")
            ok = 200 <= resp.status < 300
            status = resp.status

        print(
            f"[VIDEO_AGENT_UPLOAD] ok={ok} status={status} file={video_path.name} response={response[:250]}",
            flush=True,
        )

        local_meta = {}
        if meta_path.exists():
            try:
                local_meta = json.loads(meta_path.read_text())
            except Exception:
                local_meta = {}

        local_meta["uploaded_to_vps"] = ok
        local_meta["upload_status"] = status
        local_meta["upload_response"] = response[:1000]
        local_meta["uploaded_at"] = time.time()
        write_json(meta_path, local_meta)

        if ok and delete_local:
            video_path.unlink(missing_ok=True)
            local_meta["local_video_deleted_after_upload"] = True

        write_json(meta_path, local_meta)
        return ok
    except Exception as exc:
        print(f"[VIDEO_AGENT_UPLOAD_ERROR] {exc}", flush=True)


def enqueue_upload(meta, video_path, meta_path, needs_video):
    job = dict(meta=meta,video_path=str(video_path),meta_path=str(meta_path),
        needs_video=bool(needs_video),event_done=False,video_done=not needs_video,attempts=0,next_try=0)
    path = Path(meta_path).with_suffix(".upload.json")
    write_json(path, job)


def process_upload_job(path, cfg, now):
    job = read_json(path, None)
    if not isinstance(job,dict) or job.get("next_try",0)>now:
        return
    if not job["event_done"]:
        job["event_done"] = bool(upload_json_event(job["meta"],cfg))
        write_json(path,job)
    if job["needs_video"] and not job["video_done"]:
        local_meta = read_json(Path(job["meta_path"]),{})
        # The acknowledgement survives a crash after upload but before job completion.
        job["video_done"] = bool(local_meta.get("uploaded_to_vps")) or bool(upload_clip(
            Path(job["video_path"]),Path(job["meta_path"]),job["meta"],cfg))
    if job["event_done"] and job["video_done"]:
        path.unlink(missing_ok=True)
    else:
        job["attempts"] += 1
        job["next_try"] = now + min(300,5*2**min(job["attempts"],6))
        write_json(path,job)


def upload_worker():
    while True:
        try:
            cfg=load_env(CONFIG_FILE)
            for path in sorted(CLIP_DIR.glob("*.upload.json")):
                process_upload_job(path,cfg,time.time())
        except Exception as exc:
            print(f"[VIDEO_AGENT_QUEUE_ERROR] {exc}",flush=True)
        time.sleep(5)


class VideoAgent:
    def __init__(self):
        self.cfg = load_env(CONFIG_FILE)

        self.enabled = cfg_bool(self.cfg, "VIDEO_AGENT_ENABLED", True)
        self.fps = cfg_int(self.cfg, "VIDEO_AGENT_FPS", 6)
        self.pre_seconds = cfg_float(self.cfg, "VIDEO_AGENT_PRE_SECONDS", 2.0)
        self.post_seconds = cfg_float(self.cfg, "VIDEO_AGENT_POST_SECONDS", 2.0)
        self.max_seconds = cfg_float(self.cfg, "VIDEO_AGENT_MAX_SECONDS", 25.0)
        self.width = cfg_int(self.cfg, "VIDEO_AGENT_WIDTH", 960)
        self.max_files = cfg_int(self.cfg, "VIDEO_AGENT_MAX_FILES", 100)

        self.missed_only = cfg_bool(self.cfg, "VIDEO_AGENT_ONLY_MISSED_COUNTS", True)
        self.upload_validated_every_n = cfg_int(
            self.cfg,
            "VIDEO_AGENT_UPLOAD_VALIDATED_EVERY_N",
            0,
        )

        self.prebuffer = deque(maxlen=max(1, int(self.pre_seconds * self.fps)))
        self.writer = None
        self.active = False
        self.current_path = None
        self.current_meta_path = None
        self.current_event_id = None

        self.start_ts = None
        self.last_detection_ts = None
        self.frames_written = 0
        self.frame_size = None
        self.max_persons_seen = 0
        self.last_frame_ts = 0

        self.start_counts = {}
        self.start_total_count = 0
        self.sequence_tracks = {}
        self.sequence_probable_tracks = {}
        self.sequence_calibration_mode = False
        self.validated_clip_counter = 0

        print(
            f"[VIDEO_AGENT] enabled={self.enabled} fps={self.fps} upload={cfg_bool(self.cfg, 'VIDEO_AGENT_UPLOAD_ENABLED', True)} missed_only={self.missed_only} validated_every_n={self.upload_validated_every_n} dir={CLIP_DIR}",
            flush=True,
        )

    def normalize_frame(self, frame):
        if frame is None:
            return None

        height, width = frame.shape[:2]
        if width != self.width:
            ratio = self.width / float(width)
            frame = cv2.resize(frame, (self.width, int(height * ratio)))
        return frame

    def read_preview(self):
        if not PREVIEW_FILE.exists() or time.time()-PREVIEW_FILE.stat().st_mtime > 3:
            return None
        return self.normalize_frame(cv2.imread(str(PREVIEW_FILE)))

    def has_detection(self):
        state = read_json(DETECTIONS_FILE, [])
        if not isinstance(state,dict) or time.time()-float(state.get("timestamp",0)) > 3:
            return False, 0, {}
        detections = get_detection_items(state)
        return len(detections) > 0, len(detections), state

    def reset_sequence_tracking(self):
        self.sequence_tracks = {}
        self.sequence_probable_tracks = {}
        self.sequence_calibration_mode = cfg_calibration_mode(self.cfg)

    def observe_detection_state(self, state):
        if not self.active:
            return

        if cfg_calibration_mode(self.cfg):
            self.sequence_calibration_mode = True

        for track in get_track_items(state):
            track_id = track.get("track_id")
            if track_id is None:
                continue

            last_ts = track_last_timestamp(track)
            if self.start_ts and last_ts and last_ts < self.start_ts - self.pre_seconds - 0.5:
                continue

            key = str(track_id)
            compact = compact_track(track)
            self.sequence_tracks[key] = compact

            if track_is_probable_missed(track):
                self.sequence_probable_tracks[key] = compact
            else:
                self.sequence_probable_tracks.pop(key, None)

    def open_writer(self, frame):
        self.cleanup_old()
        if self.storage_full():
            if time.time()-getattr(self,"last_storage_warning",0)>30:
                print("[VIDEO_AGENT_STORAGE_FULL] collecte suspendue, comptage maintenu", flush=True)
                self.last_storage_warning=time.time()
            return False
        if len(list(CLIP_DIR.glob("*.upload.json"))) >= self.max_files:
            if time.time()-getattr(self,"last_queue_warning",0)>30:
                print("[VIDEO_AGENT_QUEUE_FULL] collecte suspendue, envois en attente conserves",flush=True)
                self.last_queue_warning=time.time()
            return False
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_event_id = f"seq_{ts}"
        path = CLIP_DIR / f"miss_check_{ts}.mp4"

        height, width = frame.shape[:2]
        self.frame_size = (width, height)

        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self.fps,
            self.frame_size,
        )

        if not writer.isOpened():
            print("[VIDEO_AGENT_ERROR] impossible ouvrir VideoWriter", flush=True)
            return False

        self.writer = writer
        self.current_path = path
        self.current_meta_path = path.with_suffix(".json")
        self.active = True
        self.start_ts = time.time()
        self.frames_written = 0
        self.max_persons_seen = 0
        self.last_frame_ts = 0

        self.start_counts = read_json(COUNTS_FILE, {})
        self.start_total_count = get_total_count(self.start_counts)
        self.reset_sequence_tracking()

        print(f"[VIDEO_AGENT_START] {path} start_total={self.start_total_count}", flush=True)

        for buffered in list(self.prebuffer):
            self.write_frame(buffered, force=True)

        return True

    def write_frame(self, frame, force=False):
        if not self.writer or frame is None:
            return

        now = time.time()
        if not force and now - self.last_frame_ts < 1.0 / float(self.fps):
            return

        if self.frame_size:
            width, height = self.frame_size
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height))

        self.writer.write(frame)
        self.frames_written += 1
        self.last_frame_ts = now

    def cleanup_old(self):
        clips = sorted(CLIP_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        sizes = {p:p.stat().st_size for p in clips if p.exists()}
        total, count = sum(sizes.values()), len(sizes)
        cap = max(128, cfg_int(self.cfg, "VIDEO_AGENT_STORAGE_MB", 2048))*1024*1024
        for clip in clips:
            if clip == self.current_path or clip.with_suffix(".upload.json").exists():
                continue
            meta = read_json(clip.with_suffix(".json"), {})
            expiry = meta.get("local_retain_until")
            # Only expire the new, explicitly retained evidence. Never purge old
            # user files or an upload in progress; metadata is always kept.
            if not isinstance(expiry, (int,float)):
                continue
            expired = expiry < time.time()
            pressure = total >= cap or count >= self.max_files
            if not expired and not pressure:
                continue
            clip.unlink(missing_ok=True)
            total -= sizes.get(clip,0)
            count -= 1
            meta["local_video_deleted_reason"] = "retention_expired" if expired else "storage_limit"
            meta["local_video_deleted_at"] = time.time()
            write_json(clip.with_suffix(".json"), meta)
            print(f"[VIDEO_AGENT_RETENTION] {clip.name} reason={meta['local_video_deleted_reason']}", flush=True)

    def storage_full(self):
        clips = list(CLIP_DIR.glob("*.mp4"))
        used = sum(p.stat().st_size for p in clips if p.exists())
        cap = max(128, cfg_int(self.cfg, "VIDEO_AGENT_STORAGE_MB", 2048))*1024*1024
        # Reserve space for the current bounded clip and avoid filling the Pi.
        return (len(clips) >= self.max_files or used >= cap
                or shutil.disk_usage(CLIP_DIR).free < 512*1024*1024)

    def should_upload_validated_clip(self):
        if self.upload_validated_every_n <= 0:
            return False

        self.validated_clip_counter += 1
        return self.validated_clip_counter % self.upload_validated_every_n == 0

    def close_writer(self):
        if not self.writer:
            return

        self.writer.release()

        end_counts = read_json(COUNTS_FILE, {})
        end_total_count = get_total_count(end_counts)
        count_delta = end_total_count - self.start_total_count
        counted = count_delta > 0
        probable_tracks = list(self.sequence_probable_tracks.values())
        calibration_mode = bool(
            self.sequence_calibration_mode or cfg_calibration_mode(self.cfg)
        )

        if calibration_mode:
            missed = False
            missed_decision_reason = "calibration_mode"
        elif probable_tracks:
            missed = True
            missed_decision_reason = "uncounted_track_in_sequence"
        elif counted:
            missed = False
            missed_decision_reason = "count_recorded_not_independently_validated"
        else:
            missed = False
            missed_decision_reason = "no_probable_line_crossing"

        sampled_validated_clip = counted and not self.missed_only and self.should_upload_validated_clip()
        review_reasons = sorted({reason for track in self.sequence_tracks.values()
            for reason in track.get("diagnostic_reasons", [])
            if reason in ("recovery_ambiguous", "opposite_side_not_confirmed", "detection_lost_near_line", "crossing_anchor_reset_after_gap")})
        needs_video = missed or sampled_validated_clip
        retain_local = not calibration_mode and not needs_video and (not counted or bool(review_reasons))
        door_id = self.cfg.get("DEVICE_ID") or self.cfg.get("DOOR_ID") or "porte-02"

        meta = {
            "event_id": self.current_event_id,
            "door_id": door_id,
            "file": str(self.current_path),
            "start_timestamp": self.start_ts,
            "end_timestamp": time.time(),
            "duration_seconds": round(time.time() - self.start_ts, 2),
            "frames_written": self.frames_written,
            "fps": self.fps,
            "max_persons_seen": self.max_persons_seen,
            "reason": "detection_sequence",
            "missed_only_mode": self.missed_only,
            "start_counts": self.start_counts,
            "end_counts": end_counts,
            "start_total_count": self.start_total_count,
            "end_total_count": end_total_count,
            "count_delta": count_delta,
            "count_delta_in": int(end_counts.get("in",0))-int(self.start_counts.get("in",0)),
            "count_delta_out": int(end_counts.get("out",0))-int(self.start_counts.get("out",0)),
            "independently_validated": False,
            "counted": counted,
            "missed": missed,
            "missed_decision_reason": missed_decision_reason,
            "sampled_validated_clip": sampled_validated_clip,
            "calibration_mode": calibration_mode,
            "review_reasons": review_reasons,
            "local_retained_for_review": retain_local,
            "local_retain_until": time.time()+min(72,max(1,cfg_int(self.cfg,"VIDEO_AGENT_RETAIN_HOURS",72)))*3600 if retain_local else None,
            "probable_crossing_tracks": probable_tracks,
            "sequence_tracks": list(self.sequence_tracks.values()),
            "config_snapshot": current_config_snapshot(self.cfg),
        }

        write_json(self.current_meta_path, meta)

        print(
            f"[VIDEO_AGENT_END] {self.current_path} frames={self.frames_written} count_delta={count_delta} missed={missed} reason={missed_decision_reason}",
            flush=True,
        )

        video_path = self.current_path
        meta_path = self.current_meta_path

        self.writer = None
        self.active = False
        self.current_path = None
        self.current_meta_path = None
        self.current_event_id = None
        self.start_ts = None
        self.last_detection_ts = None
        self.frames_written = 0
        self.frame_size = None
        self.max_persons_seen = 0
        self.start_counts = {}
        self.start_total_count = 0
        self.sequence_tracks = {}
        self.sequence_probable_tracks = {}
        self.sequence_calibration_mode = False

        enqueue_upload(meta, video_path, meta_path, needs_video)
        self.cleanup_old()

        if missed or sampled_validated_clip:
            if missed:
                print("[VIDEO_AGENT_MISSED] clip envoye pour analyse IA", flush=True)
            else:
                print(
                    "[VIDEO_AGENT_VALIDATED_SAMPLE] clip valide echantillonne pour audit IA",
                    flush=True,
                )

        elif retain_local:
            print("[VIDEO_AGENT_LOCAL_REVIEW] preuve conservee localement, sans appel IA supplementaire", flush=True)
        else:
            print("[VIDEO_AGENT_UNAUDITED] sequence non echantillonnee, precision non verifiee", flush=True)
            try:
                Path(video_path).unlink(missing_ok=True)
            except Exception:
                pass

    def run(self):
        from review_sync import run as review_sync_run
        threading.Thread(target=review_sync_run, daemon=True, name='review-sync').start()
        threading.Thread(target=upload_worker,daemon=True).start()
        last_health = 0
        last_cleanup = 0
        while True:
            try:
                self.cfg = load_env(CONFIG_FILE)
                self.enabled = cfg_bool(self.cfg, "VIDEO_AGENT_ENABLED", True)
                self.missed_only = cfg_bool(self.cfg, "VIDEO_AGENT_ONLY_MISSED_COUNTS", True)
                self.upload_validated_every_n = cfg_int(
                    self.cfg,
                    "VIDEO_AGENT_UPLOAD_VALIDATED_EVERY_N",
                    self.upload_validated_every_n,
                )

                if time.time()-last_health >= 5:
                    pending = len(list(CLIP_DIR.glob("*.upload.json")))
                    write_json(DATA_DIR / "video_agent_health.json", dict(
                        timestamp=time.time(),enabled=self.enabled,pending_uploads=pending,
                        queue_full=pending>=self.max_files,storage_full=self.storage_full(),
                        active_sequence=self.active,version="2026-09-23-v2"))
                    last_health=time.time()
                if time.time()-last_cleanup >= 60:
                    self.cleanup_old()
                    last_cleanup=time.time()

                if not self.enabled:
                    time.sleep(1)
                    continue

                frame = self.read_preview()
                detected, nb, detection_state = self.has_detection()
                now = time.time()

                if frame is not None:
                    self.prebuffer.append(frame.copy())

                if detected and frame is not None:
                    self.last_detection_ts = now
                    self.max_persons_seen = max(self.max_persons_seen, nb)

                    if not self.active:
                        self.open_writer(frame)

                if self.active:
                    self.observe_detection_state(detection_state)
                    self.write_frame(frame)

                    too_long = self.start_ts and now - self.start_ts >= self.max_seconds
                    ended = (
                        self.last_detection_ts
                        and now - self.last_detection_ts >= self.post_seconds
                    )

                    if too_long or ended:
                        self.close_writer()

                time.sleep(max(0.05, 1.0 / float(self.fps)))
            except Exception as exc:
                print(f"[VIDEO_AGENT_ERROR] {exc}", flush=True)
                time.sleep(1)


if __name__ == "__main__":
    VideoAgent().run()
