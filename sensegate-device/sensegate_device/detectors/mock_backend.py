from __future__ import annotations

import time
import cv2
import numpy as np
from .base import Detection


class MockBackend:
    def __init__(self, camera_config, _counting_config):
        self.camera_config = camera_config
        self.capture = None
        self.t = 0

    def start(self) -> None:
        self.capture = cv2.VideoCapture(self.camera_config.source)
        time.sleep(self.camera_config.warmup_seconds)

    def read(self):
        if self.capture is None:
            return None, []
        ok, frame = self.capture.read()
        if not ok or frame is None:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.t += 1
        x = 100 + (self.t * 10) % 800
        y = 250
        det = Detection(track_id="mock-person", label="person", confidence=0.99, x1=x, y1=y, x2=x + 120, y2=y + 220)
        return frame, [det]

    def stop(self) -> None:
        if self.capture is not None:
            self.capture.release()
