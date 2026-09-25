#!/usr/bin/env python3
from __future__ import annotations
import os
from pathlib import Path

def _clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()

def load_env_file(env_path: str | Path) -> dict:
    env_path = Path(env_path)
    data = {}
    if not env_path.exists():
        return data
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _clean_value(value)
        if key:
            data[key] = value
    return data

def load_config(env_path: str | Path | None = None) -> dict:
    if env_path is None:
        env_path = os.environ.get("PEOPLE_COUNTER_ENV", "/home/loic/people_counter/config/device_config.env")
    file_config = load_env_file(env_path)
    def get(key: str, default: str = "") -> str:
        return os.environ.get(key, file_config.get(key, default))
    return {
        "DEVICE_ID": get("DEVICE_ID", "porte-001"),
        "DOOR_NAME": get("DOOR_NAME", "Porte 1"),
        "SITE_NAME": get("SITE_NAME", "Site principal"),
        "TAILSCALE_HOST": get("TAILSCALE_HOST", ""),
        "SERVER_URL": get("SERVER_URL", "https://sensegate.fr"),
        "SERVER_API_KEY": get("SERVER_API_KEY", ""),
        "WEB_HOST": get("WEB_HOST", "0.0.0.0"),
        "WEB_PORT": int(get("WEB_PORT", "5000")),
        "CAM_WIDTH": int(get("CAM_WIDTH", "1280")),
        "CAM_HEIGHT": int(get("CAM_HEIGHT", "720")),
        "FPS": int(get("FPS", "20")),
        "LINE_Y": int(get("LINE_Y", "360")),
        "MIN_BOX_W": int(get("MIN_BOX_W", "30")),
        "MIN_BOX_H": int(get("MIN_BOX_H", "30")),
        "MAX_DISAPPEARED": int(get("MAX_DISAPPEARED", "8")),
        "MAX_DISTANCE": int(get("MAX_DISTANCE", "100")),
        "LOG_LEVEL": get("LOG_LEVEL", "INFO"),
        "PROJECT_NAME": get("PROJECT_NAME", "people_counter"),
        "INSTALL_USER": get("INSTALL_USER", "loic"),
        "INSTALL_DIR": get("INSTALL_DIR", "/home/loic/people_counter"),
        "HAILO_HEF_PATH": get("HAILO_HEF_PATH", "/usr/share/hailo-models/yolov8s_h8.hef"),
        "LINE_ORIENTATION": get("LINE_ORIENTATION", "vertical"),
        "LINE_POSITION": int(get("LINE_POSITION", "640")),
        "ENTER_DIRECTION": get("ENTER_DIRECTION", "right"),
        "MIN_CONFIDENCE": float(get("MIN_CONFIDENCE", "0.5")),
        "COUNTING_BAND_SIZE": int(get("COUNTING_BAND_SIZE", "160")),
        "MIN_TRACK_HITS": int(get("MIN_TRACK_HITS", "3")),
        "MIN_STEP_FOR_COUNT": float(get("MIN_STEP_FOR_COUNT", "0")),
        "TRACK_HISTORY": int(get("TRACK_HISTORY", "32")),
        "TRACK_SIDE_MARGIN": int(get("TRACK_SIDE_MARGIN", str(max(4,int(get("COUNTING_BAND_SIZE", "30"))//2)))),
        "MIN_MISSED_TRAVEL": float(get("MIN_MISSED_TRAVEL", str(max(25,int(get("COUNTING_BAND_SIZE", "30")))))),
        "MIN_MISSED_TRACK_HITS": int(get("MIN_MISSED_TRACK_HITS", "3")),
        "MIN_MISSED_VISIBLE_SECONDS": float(get("MIN_MISSED_VISIBLE_SECONDS", "0.25")),
        "TRACK_MAX_AGE_SECONDS": float(get("TRACK_MAX_AGE_SECONDS", "0.8")),
        "TRACK_MATCH_DISTANCE": float(get("TRACK_MATCH_DISTANCE", "180")),
        "TRACK_RECOVERY_ENABLED": get("TRACK_RECOVERY_ENABLED", "1"),
        "TRACK_RECOVERY_MAX_DISTANCE": float(get("TRACK_RECOVERY_MAX_DISTANCE", "280")),
        "TRACK_RECOVERY_MAX_ERROR": float(get("TRACK_RECOVERY_MAX_ERROR", "120")),
        "COUNT_CONFIRM_FRAMES": int(get("COUNT_CONFIRM_FRAMES", "2")),
        "COUNT_CONFIRM_SECONDS": float(get("COUNT_CONFIRM_SECONDS", "0.06")),
        "COUNT_MAX_GAP_SECONDS": float(get("COUNT_MAX_GAP_SECONDS", "0.5")),
        "DIAGNOSTIC_FPS": float(get("DIAGNOSTIC_FPS", "8")),
        "SYNC_INTERVAL": int(get("SYNC_INTERVAL", "5")),
        "CLIENT_ID": int(get("CLIENT_ID", "1")),
        "DETECTION_CLIP_UPLOAD_KEY": get("DETECTION_CLIP_UPLOAD_KEY", ""),
        "PERSIST_COUNTS_ON_RESTART": get("PERSIST_COUNTS_ON_RESTART", "1"),
        "AUTO_RESET_ENABLED": get("AUTO_RESET_ENABLED", "0"),
        "AUTO_RESET_TIME": get("AUTO_RESET_TIME", "04:00"),
        "VIDEO_AGENT_UPLOAD_VALIDATED_EVERY_N": int(
            get("VIDEO_AGENT_UPLOAD_VALIDATED_EVERY_N", "0")
        ),
        "AI_AUTOTUNE_ENABLED": get("AI_AUTOTUNE_ENABLED", "0"),
        "AI_AUTOTUNE_POLL_SECONDS": int(get("AI_AUTOTUNE_POLL_SECONDS", "300")),
        "AI_AUTOTUNE_MIN_CONFIDENCE": float(
            get("AI_AUTOTUNE_MIN_CONFIDENCE", "0.8")
        ),
        "AI_AUTOTUNE_MIN_APPLY_INTERVAL_SECONDS": int(
            get("AI_AUTOTUNE_MIN_APPLY_INTERVAL_SECONDS", "21600")
        ),
        "AI_AUTOTUNE_ALLOWED_KEYS": get(
            "AI_AUTOTUNE_ALLOWED_KEYS",
            "LINE_POSITION,MIN_CONFIDENCE,MAX_DISTANCE,MAX_DISAPPEARED,COUNTING_BAND_SIZE,MIN_TRACK_HITS",
        ),
    }
