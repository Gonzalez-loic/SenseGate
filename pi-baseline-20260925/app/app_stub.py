#!/usr/bin/env python3
import json
import os
import re
import subprocess
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_file, Response

from config_loader import load_config


ENV_PATH = Path(os.environ.get(
    "PEOPLE_COUNTER_ENV",
    "/home/loic/people_counter/config/device_config.env",
))

cfg = load_config()

BASE_DIR = Path(cfg.get("INSTALL_DIR", "/home/loic/people_counter"))
DATA_DIR = BASE_DIR / "data"

COUNTS_FILE = DATA_DIR / "counts.json"
DETECTIONS_FILE = DATA_DIR / "detections.json"
PREVIEW_FILE = DATA_DIR / "preview.jpg"

app = Flask(__name__)


ALLOWED_CONFIG_KEYS = {
    "LINE_ORIENTATION": "str",
    "LINE_POSITION": "int",
    "LINE_Y": "int",
    "ENTER_DIRECTION": "str",
    "COUNTING_BAND_SIZE": "int",
    "MIN_CONFIDENCE": "float",
    "MAX_DISTANCE": "int",
    "MAX_DISAPPEARED": "int",
    "MIN_TRACK_HITS": "int",
    "MIN_STEP_FOR_COUNT": "int",
    "MIN_TOTAL_TRAVEL": "int",
    "STABLE_SIDE_FRAMES": "int",
    "ROI_ENABLED": "int",
    "ROI_X1": "int",
    "ROI_Y1": "int",
    "ROI_X2": "int",
    "ROI_Y2": "int",
}


ALLOWED_SERVICES = {
    "web": "people_counter.service",
    "counter": "people_counter_hailo.service",
    "sync": "people_counter_sync.service",
}


def current_cfg():
    return load_config()


def require_install_key():
    cfg_now = current_cfg()
    install_key = str(cfg_now.get("INSTALL_API_KEY", "") or "").strip()

    # Si INSTALL_API_KEY est vide, on laisse ouvert pour l'installation terrain.
    # Plus tard, on pourra le remplir pour sécuriser.
    if not install_key:
        return None

    provided = request.headers.get("X-Install-Key", "")
    if provided != install_key:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    return None


def read_json(path, default):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def run_cmd(args, timeout=10, sudo=False):
    cmd = list(args)

    if sudo and os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd

    try:
        p = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": p.stdout.strip(),
            "stderr": p.stderr.strip(),
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": "",
            "stderr": "timeout",
            "cmd": " ".join(cmd),
        }
    except Exception as e:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": str(e),
            "cmd": " ".join(cmd),
        }


def parse_env_file():
    data = {}

    if not ENV_PATH.exists():
        return data

    for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")

    return data


def write_env_updates(updates):
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    seen = set()

    if ENV_PATH.exists():
        existing = ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()

    new_lines = []

    for line in existing:
        if "=" not in line or line.strip().startswith("#"):
            new_lines.append(line)
            continue

        k = line.split("=", 1)[0].strip()

        if k in updates:
            new_lines.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")

    tmp = ENV_PATH.with_suffix(".env.tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.replace(tmp, ENV_PATH)


def validate_config_value(key, value):
    kind = ALLOWED_CONFIG_KEYS[key]

    if kind == "int":
        ivalue = int(value)

        if key == "COUNTING_BAND_SIZE" and not (1 <= ivalue <= 200):
            raise ValueError("COUNTING_BAND_SIZE doit être entre 1 et 200")

        if key == "LINE_POSITION" and not (0 <= ivalue <= 5000):
            raise ValueError("LINE_POSITION invalide")

        if key == "ROI_ENABLED" and ivalue not in (0, 1):
            raise ValueError("ROI_ENABLED doit être 0 ou 1")

        return str(ivalue)

    if kind == "float":
        fvalue = float(value)

        if key == "MIN_CONFIDENCE" and not (0.05 <= fvalue <= 0.95):
            raise ValueError("MIN_CONFIDENCE doit être entre 0.05 et 0.95")

        return str(fvalue)

    if kind == "str":
        svalue = str(value).strip()

        if key == "LINE_ORIENTATION" and svalue not in ("horizontal", "vertical"):
            raise ValueError("LINE_ORIENTATION doit être horizontal ou vertical")

        if key == "ENTER_DIRECTION" and svalue not in ("up", "down", "left", "right"):
            raise ValueError("ENTER_DIRECTION doit être up, down, left ou right")

        return svalue

    return str(value)


@app.route("/")
def index():
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SenseGate People Counter</title>
  <style>
    body { font-family: Arial, sans-serif; background:#111827; color:#f9fafb; margin:0; padding:20px; }
    h1 { margin-top:0; }
    .stats { font-size:24px; margin-bottom:15px; }
    .box { display:inline-block; margin-right:20px; padding:12px 18px; background:#1f2937; border-radius:10px; }
    img { max-width:100%; border:3px solid #374151; border-radius:10px; }
    .small { color:#9ca3af; font-size:14px; margin-top:10px; }
  </style>
</head>
<body>
  <h1>SenseGate - People Counter</h1>

  <div class="stats">
    <span class="box">IN: <b id="in">-</b></span>
    <span class="box">OUT: <b id="out">-</b></span>
    <span class="box">SOLDE: <b id="balance">-</b></span>
    <span class="box">OCC. ESTIMÉE: <b id="occ">-</b></span>
    <span class="box">LAST: <b id="last">-</b></span>
  </div>

  <div id="count-warning" role="status" style="color:#fbbf24;margin-bottom:12px"></div>
  <img id="preview" src="/api/preview?t=0">

  <div class="small">
    API: /api/stats — Preview: /api/preview — Wi-Fi: /api/wifi/status
  </div>

<script>
async function refreshStats() {
  try {
    const r = await fetch('/api/stats?t=' + Date.now());
    const s = await r.json();
    document.getElementById('in').innerText = s.in ?? 0;
    document.getElementById('out').innerText = s.out ?? 0;
    const balance = Number(s.in ?? 0) - Number(s.out ?? 0);
    document.getElementById('balance').innerText = balance;
    document.getElementById('occ').innerText = balance < 0 ? 'Incertaine' : (s.occupancy ?? 0);
    document.getElementById('count-warning').innerText = balance < 0
      ? 'Solde négatif : occupation incertaine. Vérifier les passages manqués ou comptés en trop.'
      : 'Occupation estimée à partir des compteurs ; précision terrain non mesurée.';
    document.getElementById('last').innerText = s.last_event ?? '-';
  } catch(e) {}
}

function refreshImage() {
  document.getElementById('preview').src = '/api/preview?t=' + Date.now();
}

setInterval(refreshStats, 1000);
setInterval(refreshImage, 800);
refreshStats();
refreshImage();
</script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")


@app.route("/health")
def health():
    cfg_now = current_cfg()
    tailscale = run_cmd(["tailscale", "ip", "-4"], timeout=3)
    hostname_ips = run_cmd(["hostname", "-I"], timeout=3)

    return jsonify({
        "ok": True,
        "service": "people_counter",
        "device_id": cfg_now.get("DEVICE_ID"),
        "door_name": cfg_now.get("DOOR_NAME"),
        "server_url": cfg_now.get("SERVER_URL"),
        "data_dir": str(DATA_DIR),
        "preview_exists": PREVIEW_FILE.exists(),
        "counts_exists": COUNTS_FILE.exists(),
        "tailscale_ip": tailscale["stdout"].splitlines()[0] if tailscale["ok"] and tailscale["stdout"] else "",
        "local_ips": hostname_ips["stdout"] if hostname_ips["ok"] else "",
        "ts": time.time(),
    })


@app.route("/api/stats")
def api_stats():
    data = read_json(COUNTS_FILE, {
        "in": 0,
        "out": 0,
        "occupancy": 0,
        "last_event": None
    })
    return jsonify(data)
@app.route("/api/counters/reset", methods=["POST"])
def api_counters_reset():
    data_dir = "/home/loic/people_counter/data"
    os.makedirs(data_dir, exist_ok=True)

    reset_file = os.path.join(data_dir, "reset_request.json")

    payload = {
        "requested": True,
        "ts": time.time(),
        "source": "local_api",
    }

    with open(reset_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    return jsonify({
        "ok": True,
        "message": "Reset request written",
        "reset_file": reset_file,
    })


@app.route("/api/reset/config", methods=["GET"])
def api_get_reset_config():
    config_path = "/home/loic/people_counter/config/device_config.env"

    values = {
        "AUTO_RESET_ENABLED": "0",
        "AUTO_RESET_TIME": "04:00",
        "AUTO_RESET_LAST_DATE": "",
    }

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                if key in values:
                    values[key] = value

    return jsonify({
        "ok": True,
        **values,
    })


@app.route("/api/reset/config", methods=["POST"])
def api_post_reset_config():
    payload = request.get_json(silent=True) or {}

    enabled = str(payload.get("AUTO_RESET_ENABLED", "0")).strip()
    reset_time = str(payload.get("AUTO_RESET_TIME", "04:00")).strip()

    if enabled.lower() in ["1", "true", "yes", "on"]:
        enabled = "1"
    else:
        enabled = "0"

    if len(reset_time) != 5 or reset_time[2] != ":":
        return jsonify({
            "ok": False,
            "error": "AUTO_RESET_TIME must be HH:MM",
        }), 400

    try:
        hour = int(reset_time[0:2])
        minute = int(reset_time[3:5])

        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError()
    except Exception:
        return jsonify({
            "ok": False,
            "error": "AUTO_RESET_TIME must be HH:MM",
        }), 400

    config_path = "/home/loic/people_counter/config/device_config.env"

    updates = {
        "AUTO_RESET_ENABLED": enabled,
        "AUTO_RESET_TIME": reset_time,
    }

    lines = []
    existing_keys = set()

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
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

    existing_after = set()

    for line in new_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _ = stripped.split("=", 1)
            existing_after.add(key.strip())

    if "AUTO_RESET_LAST_DATE" not in existing_after:
        new_lines.append("AUTO_RESET_LAST_DATE=\n")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return jsonify({
        "ok": True,
        "AUTO_RESET_ENABLED": enabled,
        "AUTO_RESET_TIME": reset_time,
    })

@app.route("/api/detections")
def api_detections():
    data = read_json(DETECTIONS_FILE, [])
    return jsonify(data)


@app.route("/api/preview")
@app.route("/preview.jpg")
def api_preview():
    if PREVIEW_FILE.exists():
        return send_file(str(PREVIEW_FILE), mimetype="image/jpeg", max_age=0)
    return Response("preview not ready", status=404)



@app.route("/video_feed")
def video_feed():
    def generate():
        import time

        while True:
            try:
                if PREVIEW_FILE.exists():
                    frame = PREVIEW_FILE.read_bytes()
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Cache-Control: no-cache\r\n\r\n" +
                        frame +
                        b"\r\n"
                    )
                time.sleep(0.15)
            except GeneratorExit:
                break
            except Exception:
                time.sleep(0.5)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )

@app.route("/api/config", methods=["GET"])
def api_config_get():
    cfg_file = parse_env_file()

    payload = {}
    for key in sorted(ALLOWED_CONFIG_KEYS.keys()):
        if key in cfg_file:
            payload[key] = cfg_file[key]
        else:
            payload[key] = current_cfg().get(key)

    return jsonify({
        "ok": True,
        "env_path": str(ENV_PATH),
        "config": payload,
        "allowed_keys": sorted(ALLOWED_CONFIG_KEYS.keys()),
    })


@app.route("/api/config", methods=["POST"])
def api_config_post():
    auth = require_install_key()
    if auth:
        return auth

    payload = request.get_json(silent=True) or {}
    updates = {}

    for key, value in payload.items():
        if key not in ALLOWED_CONFIG_KEYS:
            return jsonify({"ok": False, "error": f"Paramètre non autorisé: {key}"}), 400

        try:
            updates[key] = validate_config_value(key, value)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "key": key}), 400

    # Compatibilite compteur : certaines versions utilisent encore LINE_Y.
    # Si Flutter modifie LINE_POSITION, on synchronise LINE_Y automatiquement.
    if "LINE_POSITION" in updates and "LINE_Y" not in updates:
        updates["LINE_Y"] = updates["LINE_POSITION"]

    if not updates:
        return jsonify({"ok": False, "error": "Aucun paramètre à modifier"}), 400

    write_env_updates(updates)

    restart = bool(payload.get("restart", True)) if isinstance(payload, dict) else True

    restart_result = None
    if restart:
        restart_result = run_cmd(
            ["systemctl", "restart", "people_counter_hailo.service"],
            timeout=10,
            sudo=True,
        )

    return jsonify({
        "ok": True,
        "updated": updates,
        "restart_counter": restart,
        "restart_result": restart_result,
    })


@app.route("/api/wifi/status", methods=["GET"])
def wifi_status():
    device_status = run_cmd(
        ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"],
        timeout=6,
    )

    active_wifi = run_cmd(
        ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi"],
        timeout=8,
    )

    current = None
    if active_wifi["ok"]:
        for line in active_wifi["stdout"].splitlines():
            parts = line.split(":", 3)
            if len(parts) >= 4 and parts[0] == "yes":
                current = {
                    "ssid": parts[1],
                    "signal": parts[2],
                    "security": parts[3],
                }
                break

    tailscale = run_cmd(["tailscale", "ip", "-4"], timeout=3)
    hostname_ips = run_cmd(["hostname", "-I"], timeout=3)

    return jsonify({
        "ok": True,
        "current_wifi": current,
        "device_status_raw": device_status["stdout"],
        "tailscale_ip": tailscale["stdout"].splitlines()[0] if tailscale["ok"] and tailscale["stdout"] else "",
        "local_ips": hostname_ips["stdout"] if hostname_ips["ok"] else "",
    })


@app.route("/api/wifi/scan", methods=["GET"])
def wifi_scan():
    rescan = request.args.get("rescan", "1") != "0"

    args = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"]
    if rescan:
        args += ["--rescan", "yes"]

    result = run_cmd(args, timeout=15, sudo=False)

    if not result["ok"]:
        return jsonify({
            "ok": False,
            "error": result["stderr"],
            "stdout": result["stdout"],
        }), 500

    networks = {}
    for line in result["stdout"].splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue

        in_use, ssid, signal, security = parts
        ssid = ssid.strip()

        if not ssid:
            continue

        try:
            signal_int = int(signal)
        except Exception:
            signal_int = 0

        previous = networks.get(ssid)
        if previous is None or signal_int > previous["signal"]:
            networks[ssid] = {
                "ssid": ssid,
                "signal": signal_int,
                "security": security,
                "in_use": in_use == "*",
            }

    return jsonify({
        "ok": True,
        "networks": sorted(networks.values(), key=lambda x: x["signal"], reverse=True),
    })


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    auth = require_install_key()
    if auth:
        return auth

    payload = request.get_json(silent=True) or {}

    ssid = str(payload.get("ssid", "")).strip()
    password = str(payload.get("password", "") or "")
    iface = str(payload.get("iface", "wlan0")).strip() or "wlan0"
    hidden = bool(payload.get("hidden", False))

    if not ssid:
        return jsonify({"ok": False, "error": "SSID manquant"}), 400

    # Par défaut :
    # - SenseGate-Install = réseau secours terrain
    # - tout autre Wi-Fi = réseau client prioritaire
    priority = payload.get("priority")
    if priority is None:
        priority = 10 if ssid == "SenseGate-Install" else 100

    try:
        priority = int(priority)
    except Exception:
        priority = 100

    cmd = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", iface]

    if password:
        cmd += ["password", password]

    if hidden:
        cmd += ["hidden", "yes"]

    result = run_cmd(cmd, timeout=45, sudo=True)

    active_connection = ""
    priority_result = None

    if result["ok"]:
        status = run_cmd(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"],
            timeout=6,
        )

        if status["ok"]:
            for line in status["stdout"].splitlines():
                parts = line.split(":", 3)
                if len(parts) >= 4 and parts[0] == iface and parts[1] == "wifi":
                    active_connection = parts[3]
                    break

        connection_name = active_connection or ssid

        run_cmd(["nmcli", "connection", "modify", connection_name, "connection.autoconnect", "yes"], timeout=8, sudo=True)
        run_cmd(["nmcli", "connection", "modify", connection_name, "connection.autoconnect-retries", "-1"], timeout=8, sudo=True)
        priority_result = run_cmd(
            ["nmcli", "connection", "modify", connection_name, "connection.autoconnect-priority", str(priority)],
            timeout=8,
            sudo=True,
        )

    return jsonify({
        "ok": result["ok"],
        "ssid": ssid,
        "priority": priority,
        "active_connection": active_connection,
        "message": "Connexion demandée. Si le Pi change de réseau, la réponse peut être la dernière avant reconnexion.",
        "result": {
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        },
        "priority_result": priority_result,
    }), 200 if result["ok"] else 500


@app.route("/api/system/services", methods=["GET"])
def system_services():
    services = {}

    for short_name, service_name in ALLOWED_SERVICES.items():
        active = run_cmd(["systemctl", "is-active", service_name], timeout=5)
        enabled = run_cmd(["systemctl", "is-enabled", service_name], timeout=5)

        services[short_name] = {
            "service": service_name,
            "active": active["stdout"],
            "enabled": enabled["stdout"],
            "ok": active["stdout"] == "active",
        }

    return jsonify({
        "ok": True,
        "services": services,
    })


@app.route("/api/system/restart", methods=["POST"])
def system_restart():
    auth = require_install_key()
    if auth:
        return auth

    payload = request.get_json(silent=True) or {}
    target = str(payload.get("service", "")).strip()

    if target not in ALLOWED_SERVICES:
        return jsonify({
            "ok": False,
            "error": "Service non autorisé",
            "allowed": sorted(ALLOWED_SERVICES.keys()),
        }), 400

    service_name = ALLOWED_SERVICES[target]
    result = run_cmd(["systemctl", "restart", service_name], timeout=15, sudo=True)

    return jsonify({
        "ok": result["ok"],
        "service": service_name,
        "result": {
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }
    }), 200 if result["ok"] else 500


if __name__ == "__main__":
    cfg_now = current_cfg()
    host = cfg_now.get("WEB_HOST", "0.0.0.0")
    port = int(cfg_now.get("WEB_PORT", 5000))
    app.run(host=host, port=port, debug=False, threaded=True)
