from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2

from sensegate_device.api.server import ApiServer
from sensegate_device.core.config import DeviceConfig, load_config
from sensegate_device.core.logging_utils import configure_logging
from sensegate_device.counting.engine import CountingEngine
from sensegate_device.detectors.hailo_backend import HailoBackend
from sensegate_device.detectors.mock_backend import MockBackend
from sensegate_device.detectors.opencv_hog_backend import OpenCVHOGBackend
from sensegate_device.storage.db import DeviceDatabase
from sensegate_device.syncer.server_client import ServerClient
from sensegate_device.utils.time_utils import utcnow_iso

logger = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    last_frame_at: str | None = None
    last_server_sync_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error: str | None = None
    started_at: str = utcnow_iso()


class DeviceRuntime:
    def __init__(self, config: DeviceConfig):
        self.config = config
        configure_logging(config.root_dir / config.logging.file, config.logging.level)
        self.snapshot_path = config.root_dir / config.app.snapshot_path
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        self.db = DeviceDatabase(config.root_dir / config.storage.db_path)
        self.counter = CountingEngine(config.counting)
        persisted = self.db.load_stats()
        self.counter.in_count = int(persisted["in"])
        self.counter.out_count = int(persisted["out"])

        self.server_client = ServerClient(config.server)
        self.state = RuntimeState()
        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_jpeg = None
        self._stop_event = threading.Event()
        self._reload_requested = threading.Event()

        provider = config.backend.provider.lower()
        if provider == "hailo":
            self.detector = HailoBackend(config.camera, config.counting, config.backend)
        elif provider == "opencv_hog":
            self.detector = OpenCVHOGBackend(config.camera, config.counting)
        else:
            self.detector = MockBackend(config.camera, config.counting)

        self.api = ApiServer(self)

    def start(self) -> None:
        logger.info("Starting device runtime for %s", self.config.site.device_id)
        self.detector.start()

        workers = [
            threading.Thread(target=self._vision_loop, daemon=True, name="vision-loop"),
            threading.Thread(target=self._sync_loop, daemon=True, name="sync-loop"),
            threading.Thread(target=self._reload_loop, daemon=True, name="reload-loop"),
        ]

        heartbeat_path = (self.config.server.health_path or "").strip()
        if self.config.server.enabled and heartbeat_path and self.config.server.heartbeat_interval_seconds > 0:
            workers.append(
                threading.Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat-loop")
            )
        else:
            logger.info("Heartbeat loop disabled by configuration")

        for worker in workers:
            worker.start()

        self.api.serve_forever()

    def _vision_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                frame, detections = self.detector.read()
                if frame is None:
                    time.sleep(0.05)
                    continue

                events = self.counter.process(detections, frame.shape)
                for event in events:
                    event["device_id"] = self.config.site.device_id
                    event["door_name"] = self.config.site.door_name
                    event["site_name"] = self.config.site.site_name
                    self.db.enqueue("count_event", event, event["timestamp"])

                now = utcnow_iso()
                self.db.save_stats(self.counter.in_count, self.counter.out_count, now)

                annotated = self._annotate_frame(frame, detections)
                ok, buf = cv2.imencode(
                    ".jpg",
                    annotated,
                    [int(cv2.IMWRITE_JPEG_QUALITY), int(self.config.app.jpeg_quality)],
                )
                if ok:
                    jpeg = bytes(buf)
                    with self._lock:
                        self._latest_frame = annotated
                        self._latest_jpeg = jpeg
                    self.snapshot_path.write_bytes(jpeg)

                self.state.last_frame_at = now
            except Exception as exc:
                logger.exception("Vision loop error")
                self.state.last_error = str(exc)
                time.sleep(0.2)

    def _annotate_frame(self, frame, detections):
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        if self.counter.line_px is None:
            self.counter.configure_from_frame(annotated.shape)

        line = self.counter.line_px or 0
        if self.config.counting.mode == "horizontal":
            cv2.line(annotated, (0, line), (w, line), (0, 255, 255), 2)
        else:
            cv2.line(annotated, (line, 0), (line, h), (0, 255, 255), 2)

        for det in detections:
            cv2.rectangle(annotated, (det.x1, det.y1), (det.x2, det.y2), (0, 255, 0), 2)
            cx, cy = det.center
            cv2.circle(annotated, (cx, cy), 4, (0, 0, 255), -1)
            cv2.putText(
                annotated,
                f"{det.label} {det.confidence:.2f}",
                (det.x1, max(20, det.y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )

        cv2.putText(annotated, f"IN: {self.counter.in_count}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 0), 2)
        cv2.putText(annotated, f"OUT: {self.counter.out_count}", (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 255), 2)
        cv2.putText(annotated, self.config.site.door_name, (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        return annotated

    def _sync_loop(self) -> None:
        interval = max(2, self.config.server.sync_interval_seconds)
        while not self._stop_event.is_set():
            try:
                payload = {
                    "door_id": self.config.site.device_id,
                    "count_in": int(self.counter.in_count),
                    "count_out": int(self.counter.out_count),
                    "occupancy": max(int(self.counter.in_count) - int(self.counter.out_count), 0),
                    "timestamp": utcnow_iso(),
                }

                if self.server_client.push_stats(payload):
                    self.state.last_server_sync_at = utcnow_iso()

                time.sleep(interval)
            except Exception as exc:
                logger.exception("Sync loop error")
                self.state.last_error = str(exc)
                time.sleep(interval)

    def _heartbeat_loop(self) -> None:
        interval = max(5, self.config.server.heartbeat_interval_seconds)
        while not self._stop_event.is_set():
            try:
                payload = self.health()
                if self.server_client.heartbeat(payload):
                    self.state.last_heartbeat_at = utcnow_iso()
                time.sleep(interval)
            except Exception as exc:
                logger.exception("Heartbeat loop error")
                self.state.last_error = str(exc)
                time.sleep(interval)

    def _reload_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._reload_requested.wait(timeout=1):
                logger.warning("Reload requested. Restart the systemd service to apply config cleanly.")
                self._reload_requested.clear()

    def get_annotated_frame_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def reset(self) -> None:
        self.counter.reset()
        self.db.hard_reset()
        self.state.last_error = None

    def request_reload(self) -> None:
        self._reload_requested.set()

    def stats(self) -> dict[str, Any]:
        return {
            "device_id": self.config.site.device_id,
            "door_name": self.config.site.door_name,
            "site_name": self.config.site.site_name,
            "in": self.counter.in_count,
            "out": self.counter.out_count,
            "last_frame_at": self.state.last_frame_at,
            "last_server_sync_at": self.state.last_server_sync_at,
        }

    def public_config(self) -> dict[str, Any]:
        return {
            "device_id": self.config.site.device_id,
            "door_name": self.config.site.door_name,
            "site_name": self.config.site.site_name,
            "counting": {
                "mode": self.config.counting.mode,
                "line_position": self.config.counting.line_position,
                "min_confidence": self.config.counting.min_confidence,
            },
            "backend": self.config.backend.provider,
            "camera": {
                "width": self.config.camera.width,
                "height": self.config.camera.height,
                "fps": self.config.camera.fps,
            },
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.state.last_error is None else "degraded",
            "device_id": self.config.site.device_id,
            "door_name": self.config.site.door_name,
            "started_at": self.state.started_at,
            "last_frame_at": self.state.last_frame_at,
            "last_server_sync_at": self.state.last_server_sync_at,
            "last_heartbeat_at": self.state.last_heartbeat_at,
            "backend": self.config.backend.provider,
            "camera_source": self.config.camera.source,
            "error": self.state.last_error,
            "stats": self.counter.stats(),
        }


def build_runtime(config_path: str) -> DeviceRuntime:
    config = load_config(config_path)
    return DeviceRuntime(config)
