#!/usr/bin/env python3
import json, os, time
from pathlib import Path
from datetime import datetime
import cv2
from picamera2 import Picamera2
from picamera2.devices import Hailo
from libcamera import controls
from counter_logic import CounterLogic
from config_loader import load_config

cfg = load_config()
BASE_DIR = Path(cfg["INSTALL_DIR"])
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

COUNTS_FILE = DATA_DIR / "counts.json"
DETECTIONS_FILE = DATA_DIR / "detections.json"
PREVIEW_FILE = DATA_DIR / "preview.jpg"
RUNTIME_FILE = DATA_DIR / "runtime_state.json"
RESET_REQUEST_FILE = DATA_DIR / "reset_request.json"
CONFIG_FILE = BASE_DIR / "config" / "device_config.env"

counter = CounterLogic(cfg)
PERSON_CLASS_IDS = {0}


def save_json_atomic(path, payload):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def read_env_file(path):
    values = {}

    if not os.path.exists(path):
        return values

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    return values


def update_env_file(path, updates):
    lines = []
    existing_keys = set()

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue

        key, _ = stripped.split("=", 1)
        key = key.strip()

        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            existing_keys.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={value}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def force_counter_zero(reason="RESET"):
    global counter

    # Remise a zero des attributs possibles de CounterLogic
    for attr in ["in_count", "in_counter", "total_in", "count_in"]:
        if hasattr(counter, attr):
            setattr(counter, attr, 0)

    for attr in ["out_count", "out_counter", "total_out", "count_out"]:
        if hasattr(counter, attr):
            setattr(counter, attr, 0)

    for attr in ["occupancy", "current_occupancy", "current_inside", "inside"]:
        if hasattr(counter, attr):
            setattr(counter, attr, 0)

    if hasattr(counter, "last_event"):
        setattr(counter, "last_event", reason)

    # Nettoyage des tracks si la logique les conserve en memoire
    for attr in [
        "tracks",
        "track_history",
        "track_states",
        "counted_ids",
        "objects",
        "finished_tracks",
    ]:
        if hasattr(counter, attr):
            value = getattr(counter, attr)
            if hasattr(value, "clear"):
                value.clear()

    payload = {
        "in": 0,
        "out": 0,
        "occupancy": 0,
        "last_event": reason,
        "updated_at": time.time(),
    }

    save_json_atomic(COUNTS_FILE, payload)
    if hasattr(counter, "get_debug_snapshot"):
        save_json_atomic(DETECTIONS_FILE, counter.get_debug_snapshot([]))
    print(f"[RESET] Counters forced to zero reason={reason}", flush=True)


def restore_counts_from_disk():
    persist_enabled = str(cfg.get("PERSIST_COUNTS_ON_RESTART", "1")).lower() in [
        "1",
        "true",
        "yes",
        "on",
    ]

    if not persist_enabled:
        print("[COUNTS] Restart persistence disabled", flush=True)
        return False

    saved = read_json(COUNTS_FILE, {})

    if not isinstance(saved, dict):
        return False

    try:
        in_count = max(0, int(saved.get("in", 0) or 0))
        out_count = max(0, int(saved.get("out", 0) or 0))
    except Exception:
        return False

    if hasattr(counter, "in_count"):
        counter.in_count = in_count
    if hasattr(counter, "out_count"):
        counter.out_count = out_count
    if hasattr(counter, "last_event"):
        counter.last_event = saved.get("last_event")

    for attr in ["tracks", "finished_tracks"]:
        if hasattr(counter, attr):
            value = getattr(counter, attr)
            if hasattr(value, "clear"):
                value.clear()

    print(
        f"[COUNTS] Restored from disk in={in_count} out={out_count} "
        f"occupancy={max(0, in_count - out_count)}",
        flush=True,
    )
    return True


def apply_manual_reset_if_requested():
    if not os.path.exists(RESET_REQUEST_FILE):
        return False

    try:
        os.remove(RESET_REQUEST_FILE)
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"[RESET] Cannot remove reset request: {e}", flush=True)

    force_counter_zero("RESET")
    return True


def apply_auto_reset_if_needed():
    env = read_env_file(CONFIG_FILE)

    enabled = env.get("AUTO_RESET_ENABLED", "0").lower() in [
        "1",
        "true",
        "yes",
        "on",
    ]

    if not enabled:
        return False

    reset_time = env.get("AUTO_RESET_TIME", "04:00")
    last_date = env.get("AUTO_RESET_LAST_DATE", "")

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_hm = now.strftime("%H:%M")

    if today == last_date:
        return False

    if current_hm != reset_time:
        return False

    force_counter_zero("AUTO_RESET")
    update_env_file(CONFIG_FILE, {
        "AUTO_RESET_LAST_DATE": today,
    })

    print(f"[RESET] Auto reset applied at {reset_time} for {today}", flush=True)
    return True


def extract_persons(hailo_output, frame_w, frame_h, threshold=0.5):
    persons = []

    for class_id, detections in enumerate(hailo_output):
        if class_id not in PERSON_CLASS_IDS:
            continue

        for detection in detections:
            score = float(detection[4])

            if score < threshold:
                continue

            y0, x0, y1, x1 = detection[:4]

            x0 = int(x0 * frame_w)
            y0 = int(y0 * frame_h)
            x1 = int(x1 * frame_w)
            y1 = int(y1 * frame_h)

            if x1-x0 < int(cfg.get("MIN_BOX_W",30)) or y1-y0 < int(cfg.get("MIN_BOX_H",30)):
                continue

            cx = int((x0 + x1) / 2)
            cy = int((y0 + y1) / 2)

            persons.append({
                "bbox": [x0, y0, x1, y1],
                "cx": cx,
                "cy": cy,
                "score": score,
                "class_id": class_id,
            })

    return persons



def draw_badge(img, center, text, color, label):
    x, y = center

    cv2.circle(img, (x, y), 28, color, -1)
    cv2.circle(img, (x, y), 30, (255, 255, 255), 2)

    cv2.putText(
        img,
        text,
        (x - 12, y + 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        (255, 255, 255),
        3,
    )

    cv2.putText(
        img,
        label,
        (x - 35, y + 48),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )



def draw_count_direction_markers(img, orientation, line_pos, enter_direction):
    h, w = img.shape[:2]

    orientation = str(orientation).lower().strip()
    enter_direction = str(enter_direction).lower().strip()

    # Placement a droite pour eviter le bloc noir des compteurs
    x = max(80, w - 120)

    if orientation == "horizontal":
        y_top = max(90, line_pos - 90)
        y_bottom = min(h - 90, line_pos + 90)

        if enter_direction == "up":
            plus_center = (x, y_top)
            minus_center = (x, y_bottom)
        else:
            plus_center = (x, y_bottom)
            minus_center = (x, y_top)

    else:
        y_top = max(90, h // 2 - 90)
        y_bottom = min(h - 90, h // 2 + 90)

        if enter_direction == "left":
            plus_center = (x, y_top)
            minus_center = (x, y_bottom)
        else:
            plus_center = (x, y_bottom)
            minus_center = (x, y_top)

    draw_badge(img, plus_center, "+", (0, 170, 0), "Entree")
    draw_badge(img, minus_center, "-", (0, 0, 220), "Sortie")



def draw_overlay(frame, detections):
    counts = counter.get_counts()
    orientation = cfg["LINE_ORIENTATION"]
    line_pos = int(cfg["LINE_POSITION"])
    enter_direction = cfg["ENTER_DIRECTION"]

    img = frame.copy()
    h, w = img.shape[:2]

    # Ligne de comptage
    if orientation == "horizontal":
        cv2.line(img, (0, line_pos), (w, line_pos), (0, 255, 255), 4)
    else:
        cv2.line(img, (line_pos, 0), (line_pos, h), (0, 255, 255), 4)

    # Bloc compteurs
    cv2.rectangle(img, (10, 10), (420, 225), (0, 0, 0), -1)
    cv2.putText(img, f"IN: {counts['in']}", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 0), 3)
    cv2.putText(img, f"OUT: {counts['out']}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 255), 3)
    balance = counts['in']-counts['out']
    cv2.putText(img, f"SOLDE: {balance}", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 210, 255), 2)
    occupancy_label = "OCC: INCERTAINE" if balance < 0 else f"OCC EST.: {counts['occupancy']}"
    cv2.putText(img, occupancy_label, (20, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(img, f"ENTER: {enter_direction}", (20, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    # Detections personnes
    for det in detections:
        x0, y0, x1, y1 = det["bbox"]
        cx, cy = det["cx"], det["cy"]
        score = det["score"]

        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 255), 4)
        cv2.circle(img, (cx, cy), 8, (255, 255, 0), -1)
        track_id = det.get("track_id")
        label = f"person {score:.2f}"
        if track_id is not None:
            label = f"id {track_id} {score:.2f}"

        cv2.putText(
            img,
            label,
            (x0 + 6, max(22, y0 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

    # ============================================================
    # MARQUEURS VISUELS DE SENS
    # + = ENTREE
    # - = SORTIE
    # Dessines volontairement a la fin pour etre visibles par-dessus tout
    # ============================================================

    orientation = str(orientation).lower().strip()
    enter_direction = str(enter_direction).lower().strip()

    if orientation == "horizontal":
        x_marker = w - 250
        y_above = max(230, line_pos - 110)
        y_below = min(h - 90, line_pos + 110)

        if enter_direction == "up":
            plus_pos = (x_marker, y_above)
            minus_pos = (x_marker, y_below)
        else:
            plus_pos = (x_marker, y_below)
            minus_pos = (x_marker, y_above)

    else:
        y_marker = h - 170
        x_left = max(170, line_pos - 140)
        x_right = min(w - 250, line_pos + 140)

        if enter_direction == "left":
            plus_pos = (x_left, y_marker)
            minus_pos = (x_right, y_marker)
        else:
            plus_pos = (x_right, y_marker)
            minus_pos = (x_left, y_marker)

    # Fond vert entree
    px, py = plus_pos
    cv2.rectangle(img, (px - 115, py - 45), (px + 175, py + 45), (0, 120, 0), -1)
    cv2.rectangle(img, (px - 115, py - 45), (px + 175, py + 45), (255, 255, 255), 2)
    cv2.putText(img, "+", (px - 95, py + 25), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (255, 255, 255), 5)
    cv2.putText(img, "ENTREE", (px - 20, py + 15), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)

    # Fond rouge sortie
    mx, my = minus_pos
    cv2.rectangle(img, (mx - 115, my - 45), (mx + 175, my + 45), (0, 0, 150), -1)
    cv2.rectangle(img, (mx - 115, my - 45), (mx + 175, my + 45), (255, 255, 255), 2)
    cv2.putText(img, "-", (mx - 88, my + 22), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (255, 255, 255), 5)
    cv2.putText(img, "SORTIE", (mx - 20, my + 15), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)

    tmp_preview = str(PREVIEW_FILE) + ".tmp.jpg"
    cv2.imwrite(tmp_preview, img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    os.replace(tmp_preview, PREVIEW_FILE)


def main():
    model_path = cfg["HAILO_HEF_PATH"]

    with Hailo(model_path) as hailo:
        model_h, model_w, _ = hailo.get_input_shape()

        video_w = int(cfg["CAM_WIDTH"])
        video_h = int(cfg["CAM_HEIGHT"])

        with Picamera2() as picam2:
            main_stream = {"size": (video_w, video_h), "format": "XRGB8888"}
            lores_stream = {"size": (model_w, model_h), "format": "RGB888"}
            controls_dict = {"FrameRate": int(cfg["FPS"])}

            camera_config = picam2.create_preview_configuration(
                main_stream,
                lores=lores_stream,
                controls=controls_dict,
            )

            picam2.configure(camera_config)
            picam2.start()

            restored_counts = restore_counts_from_disk()
            save_json_atomic(COUNTS_FILE, counter.get_counts())
            save_json_atomic(DETECTIONS_FILE, counter.get_debug_snapshot([]))
            save_json_atomic(RUNTIME_FILE, {
                "counting_engine": "hailo",
                "running": True,
                "counts_persisted": bool(
                    str(cfg.get("PERSIST_COUNTS_ON_RESTART", "1")).lower() in ["1", "true", "yes", "on"]
                ),
                "counts_restored_on_boot": restored_counts,
                "started_at": time.time(),
            })

            last_auto_reset_check = 0
            last_debug = last_persist = last_rate = time.monotonic()
            last_count_key = None
            rate_frames = 0
            processing_fps = 0.0

            while True:
                apply_manual_reset_if_requested()

                now = time.time()
                if now - last_auto_reset_check >= 5:
                    apply_auto_reset_if_needed()
                    last_auto_reset_check = now

                request = picam2.capture_request()
                try:
                    frame_main = request.make_array("main")
                    frame_lores = request.make_array("lores")
                finally:
                    request.release()

                results = hailo.run(frame_lores)

                detections = extract_persons(
                    results,
                    frame_w=video_w,
                    frame_h=video_h,
                    threshold=float(cfg.get("MIN_CONFIDENCE", 0.5)),
                )

                tracked_detections = counter.update(detections)

                tick = time.monotonic()
                counts = counter.get_counts()
                count_key = (counts["in"],counts["out"],counts["last_event"])
                if count_key != last_count_key or tick-last_persist >= 1.0:
                    save_json_atomic(COUNTS_FILE, counts)
                    last_persist, last_count_key = tick, count_key
                rate_frames += 1
                if tick-last_rate >= 2:
                    processing_fps = rate_frames/(tick-last_rate)
                    rate_frames, last_rate = 0, tick
                # Inference stays at camera rate; debug/preview must not dominate SD I/O.
                if tick-last_debug >= 1.0/max(1.0,float(cfg.get("DIAGNOSTIC_FPS",8))):
                    snapshot = counter.get_debug_snapshot(tracked_detections)
                    snapshot["processing_fps"] = round(processing_fps,2)
                    save_json_atomic(DETECTIONS_FILE,snapshot)
                    draw_overlay(frame_main, tracked_detections)
                    last_debug = tick

                time.sleep(0.01)


if __name__ == "__main__":
    main()
