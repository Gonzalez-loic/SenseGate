from flask import Flask, jsonify, send_file, request
import threading, time, cv2, json, requests, os

app = Flask(__name__)

with open("config.json") as f:
    config = json.load(f)

in_count = 0
out_count = 0

cap = cv2.VideoCapture(0)

def counter_loop():
    global in_count, out_count
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        time.sleep(1)

def sync_loop():
    while True:
        try:
            requests.post(
                f"{config['api_server']}/api/ingest/stats",
                json={
                    "door_id": config["door_id"],
                    "in": in_count,
                    "out": out_count
                },
                timeout=2
            )
        except:
            pass
        time.sleep(10)

@app.route("/api/stats")
def stats():
    return jsonify({
        "in": in_count,
        "out": out_count,
        "door": config["door_name"]
    })

@app.route("/api/reset", methods=["POST"])
def reset():
    global in_count, out_count
    in_count = 0
    out_count = 0
    return {"status": "reset_ok"}

@app.route("/snapshot.jpg")
def snapshot():
    ret, frame = cap.read()
    if ret:
        cv2.imwrite("snapshot.jpg", frame)
        return send_file("snapshot.jpg", mimetype='image/jpeg')
    return "error", 500

if __name__ == "__main__":
    threading.Thread(target=counter_loop, daemon=True).start()
    threading.Thread(target=sync_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)