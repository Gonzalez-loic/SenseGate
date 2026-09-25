#!/usr/bin/env python3
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config_loader import load_config


BASE_DIR = Path("/home/loic/people_counter")
CONFIG_FILE = BASE_DIR / "config" / "device_config.env"
COUNTS_FILE = BASE_DIR / "data" / "counts.json"
STATE_FILE = BASE_DIR / "data" / "ai_autotune_state.json"

RESTART_SERVICES = [
    "people_counter.service",
    "people_counter_hailo.service",
    "sensegate_video_agent.service",
]

ALLOWED_TUNING_RULES = {
    "LINE_POSITION": {"type": "int", "min": 100, "max": 700, "max_delta": 20},
    "MIN_CONFIDENCE": {"type": "float", "min": 0.2, "max": 0.8, "max_delta": 0.10},
    "MAX_DISTANCE": {"type": "int", "min": 120, "max": 500, "max_delta": 40},
    "MAX_DISAPPEARED": {"type": "int", "min": 10, "max": 120, "max_delta": 15},
    "COUNTING_BAND_SIZE": {"type": "int", "min": 10, "max": 80, "max_delta": 10},
    "MIN_TRACK_HITS": {"type": "int", "min": 1, "max": 5, "max_delta": 1},
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


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


def cfg_bool(cfg, key, default=False):
    raw = str(cfg.get(key, "1" if default else "0")).lower().strip()
    return raw in ("1", "true", "yes", "on")


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, payload):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    Path(tmp).replace(path)


def read_counts():
    counts = read_json(COUNTS_FILE, None)
    if not isinstance(counts, dict) or not all(isinstance(counts.get(k),int) and counts[k]>=0 for k in ("in","out")):
        raise RuntimeError("Compteurs absents ou invalides : aucune valeur zero artificielle envoyee")
    return counts


def update_env_file(path, updates):
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines(True)

    new_lines = []
    seen = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue

        key, _ = stripped.split("=", 1)
        key = key.strip()

        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}\n")

    path.write_text("".join(new_lines), encoding="utf-8")


def build_payload(cfg):
    counts = read_counts()
    fresh = time.time() - COUNTS_FILE.stat().st_mtime < 15
    preview = BASE_DIR / "data" / "preview.jpg"
    camera_fresh = preview.exists() and time.time() - preview.stat().st_mtime < 15
    tailscale_host = cfg.get("TAILSCALE_HOST", "")

    return {
        "door_id": cfg["DEVICE_ID"],
        "name": cfg["DOOR_NAME"],
        "location": cfg.get("SITE_NAME", ""),
        "client_id": int(cfg.get("CLIENT_ID", 1)),
        "snapshot_url": f"http://{tailscale_host}:5000/api/camera/snapshot" if tailscale_host else None,
        "video_url": f"http://{tailscale_host}:5000/" if tailscale_host else None,
        "tailscale_host": tailscale_host or None,
        "pi_status": "online",
        "counting_status": "running" if fresh else "stale",
        "camera_status": "ok" if camera_fresh else "stale",
        "last_event": counts.get("last_event"),
        "video_agent_health": read_json(BASE_DIR / "data" / "video_agent_health.json", {}),
        "count_in": counts.get("in", 0),
        "count_out": counts.get("out", 0),
        "occupancy": counts.get("occupancy", 0),
        "timestamp": now_iso(),
    }


def get_systemctl_value(service_name, prop):
    try:
        response = requests.get("http://127.0.0.1:9", timeout=0.001)
        response.raise_for_status()
    except Exception:
        pass

    import subprocess

    out = subprocess.check_output(
        ["systemctl", "show", service_name, f"-p{prop}", "--value"],
        text=True,
    )
    return out.strip()


def restart_services():
    import subprocess

    for service_name in RESTART_SERVICES:
        try:
            pid = get_systemctl_value(service_name, "MainPID")
        except Exception:
            pid = "0"

        if pid and pid != "0":
            subprocess.run(["kill", pid], check=False)

    time.sleep(8)

    for service_name in RESTART_SERVICES:
        subprocess.check_call(["systemctl", "is-active", "--quiet", service_name])


def clamp_change(key, proposed, current):
    rule = ALLOWED_TUNING_RULES[key]
    if rule["type"] == "int":
        value = int(round(float(proposed)))
        current_value = int(round(float(current)))
    else:
        value = round(float(proposed), 3)
        current_value = float(current)

    min_value = rule["min"]
    max_value = rule["max"]
    max_delta = rule["max_delta"]

    low = max(min_value, current_value - max_delta)
    high = min(max_value, current_value + max_delta)
    value = min(high, max(low, value))

    if rule["type"] == "int":
        return str(int(value))

    return f"{value:.2f}".rstrip("0").rstrip(".")


def sanitize_changes(cfg, changes):
    if not isinstance(changes, dict):
        return {}

    allowed_keys = {
        item.strip()
        for item in str(
            cfg.get(
                "AI_AUTOTUNE_ALLOWED_KEYS",
                ",".join(ALLOWED_TUNING_RULES.keys()),
            )
        ).split(",")
        if item.strip()
    }

    sanitized = {}

    for key, proposed in changes.items():
        if key not in ALLOWED_TUNING_RULES or key not in allowed_keys:
            continue

        current = cfg.get(key)
        if current is None:
            continue

        try:
            sanitized[key] = clamp_change(key, proposed, current)
        except Exception:
            continue

    return sanitized


def fetch_recommendation(cfg):
    key = cfg.get("DETECTION_CLIP_UPLOAD_KEY", "").strip()
    if not key:
        return {"status": "disabled", "reason": "missing_clip_key"}

    url = (
        cfg["SERVER_URL"].rstrip("/")
        + f"/api/debug/clips/recommendation/{cfg['DEVICE_ID']}"
    )

    response = requests.get(
        url,
        headers={"X-SenseGate-Clip-Key": key},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def apply_recommendation(cfg, recommendation):
    if not cfg_bool(cfg, "AI_AUTOTUNE_ENABLED", False):
        return

    state = read_json(STATE_FILE, {})

    recommendation_id = str(recommendation.get("recommendation_id", "")).strip()
    status = recommendation.get("status")
    confidence = cfg_float(recommendation, "confidence", 0.0)
    min_confidence = cfg_float(cfg, "AI_AUTOTUNE_MIN_CONFIDENCE", 0.80)
    min_apply_interval = cfg_int(
        cfg,
        "AI_AUTOTUNE_MIN_APPLY_INTERVAL_SECONDS",
        21600,
    )

    if not recommendation_id or status != "proposed":
        return

    if state.get("last_applied_id") == recommendation_id:
        return

    last_apply_ts = float(state.get("last_apply_ts", 0) or 0)
    if time.time() - last_apply_ts < min_apply_interval:
        return

    if confidence < min_confidence:
        print(
            f"[AI_AUTOTUNE_SKIP] id={recommendation_id} confidence={confidence} < {min_confidence}",
            flush=True,
        )
        return

    changes = sanitize_changes(cfg, recommendation.get("changes", {}))
    if not changes:
        print(f"[AI_AUTOTUNE_SKIP] id={recommendation_id} no allowed changes", flush=True)
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.bak_ai_tune_{ts}")
    shutil.copy2(CONFIG_FILE, backup_path)

    previous_values = {key: cfg.get(key) for key in changes}
    write_json(
        STATE_FILE,
        {
            **state,
            "last_seen_id": recommendation_id,
            "pending_apply_id": recommendation_id,
            "backup_path": str(backup_path),
            "previous_values": previous_values,
            "proposed_changes": changes,
            "received_at": now_iso(),
        },
    )

    try:
        update_env_file(CONFIG_FILE, changes)
        restart_services()
    except Exception as exc:
        print(f"[AI_AUTOTUNE_ERROR] apply failed id={recommendation_id} err={exc}", flush=True)
        shutil.copy2(backup_path, CONFIG_FILE)
        try:
            restart_services()
        except Exception as rollback_exc:
            print(f"[AI_AUTOTUNE_ERROR] rollback restart failed err={rollback_exc}", flush=True)

        write_json(
            STATE_FILE,
            {
                **state,
                "last_seen_id": recommendation_id,
                "failed_apply_id": recommendation_id,
                "backup_path": str(backup_path),
                "previous_values": previous_values,
                "proposed_changes": changes,
                "failed_at": now_iso(),
                "error": str(exc),
            },
        )
        return

    write_json(
        STATE_FILE,
        {
            **state,
            "last_seen_id": recommendation_id,
            "last_applied_id": recommendation_id,
            "last_apply_ts": time.time(),
            "backup_path": str(backup_path),
            "previous_values": previous_values,
            "applied_changes": changes,
            "applied_at": now_iso(),
            "source_recommendation": recommendation,
        },
    )

    print(
        f"[AI_AUTOTUNE_APPLIED] id={recommendation_id} changes={json.dumps(changes, ensure_ascii=False)}",
        flush=True,
    )


def main():
    last_tune_check = 0

    while True:
        cfg = load_config()
        sync_interval = cfg_int(cfg, "SYNC_INTERVAL", 5)
        sync_url = cfg["SERVER_URL"].rstrip("/") + "/api/ingest/device-sync"

        try:
            payload = build_payload(cfg)
            response = requests.post(sync_url, json=payload, headers={
                "X-SenseGate-Clip-Key": cfg.get("DETECTION_CLIP_UPLOAD_KEY", "")
            }, timeout=5)
            response.raise_for_status()
            print("SYNC", response.status_code, response.text[:200], flush=True)
        except Exception as exc:
            print("SYNC ERROR", str(exc), flush=True)

        now = time.time()
        poll_seconds = cfg_int(cfg, "AI_AUTOTUNE_POLL_SECONDS", 300)
        if now - last_tune_check >= max(60, poll_seconds):
            try:
                recommendation = fetch_recommendation(cfg)
                apply_recommendation(cfg, recommendation)
            except Exception as exc:
                print(f"[AI_AUTOTUNE_ERROR] fetch failed err={exc}", flush=True)
            last_tune_check = now

        time.sleep(sync_interval)


if __name__ == "__main__":
    main()
