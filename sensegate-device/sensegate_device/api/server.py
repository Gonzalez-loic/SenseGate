from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, request, send_file
from waitress import serve


class ApiServer:
    def __init__(self, runtime):
        self.runtime = runtime
        self.app = Flask(__name__)
        self._register_routes()

    def _check_admin(self) -> bool:
        expected = self.runtime.config.security.admin_token
        if not expected or expected == "CHANGE_ME_LOCAL":
            return True
        token = request.headers.get("Authorization", "")
        return token == f"Bearer {expected}"

    def _register_routes(self) -> None:
        app = self.app
        runtime = self.runtime

        @app.get("/api/health")
        def health():
            return jsonify(runtime.health())

        @app.get("/api/stats")
        def stats():
            return jsonify(runtime.stats())

        @app.get("/api/config")
        def config():
            return jsonify(runtime.public_config())

        @app.get("/snapshot.jpg")
        def snapshot():
            path = runtime.snapshot_path
            if not path.exists():
                return jsonify({"error": "snapshot_unavailable"}), 404
            return send_file(path, mimetype="image/jpeg", max_age=0)

        @app.get("/stream.mjpg")
        def stream_mjpg():
            def generate():
                while True:
                    frame = runtime.get_annotated_frame_jpeg()
                    if frame is None:
                        time.sleep(0.1)
                        continue
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
                    time.sleep(max(0.01, 1.0 / max(runtime.config.app.stream_fps, 1)))

            return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.post("/api/reset")
        def reset():
            if not self._check_admin():
                return jsonify({"error": "unauthorized"}), 403
            runtime.reset()
            return jsonify({"status": "ok"})

        @app.post("/api/reload")
        def reload_config():
            if not self._check_admin():
                return jsonify({"error": "unauthorized"}), 403
            runtime.request_reload()
            return jsonify({"status": "reload_requested"})

    def serve_forever(self) -> None:
        serve(self.app, host=self.runtime.config.app.host, port=self.runtime.config.app.port, threads=8)
