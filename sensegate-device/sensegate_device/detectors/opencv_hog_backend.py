from __future__ import annotations

import logging
import time

import cv2
import numpy as np
from picamera2 import Picamera2

from .base import Detection

logger = logging.getLogger(__name__)


class OpenCVHOGBackend:
    def __init__(self, camera_config, counting_config):
        self.camera_config = camera_config
        self.counting_config = counting_config
        self.picam2 = None
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.frame_index = 0

    def start(self) -> None:
        self.picam2 = Picamera2()

        video_config = self.picam2.create_video_configuration(
            main={
                "size": (int(self.camera_config.width), int(self.camera_config.height)),
                "format": "RGB888",
            },
            controls={
                "FrameDurationLimits": (
                    int(1_000_000 / max(1, int(self.camera_config.fps))),
                    int(1_000_000 / max(1, int(self.camera_config.fps))),
                )
            },
        )

        self.picam2.configure(video_config)
        self.picam2.start()
        logger.info(
            "Picamera2 backend started at %sx%s @ %sfps",
            self.camera_config.width,
            self.camera_config.height,
            self.camera_config.fps,
        )
        time.sleep(self.camera_config.warmup_seconds)

    def read(self) -> tuple[np.ndarray | None, list[Detection]]:
        if self.picam2 is None:
            return None, []

        try:
            frame_rgb = self.picam2.capture_array()
        except Exception as exc:
            logger.warning("Picamera2 capture failed: %s", exc)
            return None, []

        if frame_rgb is None:
            return None, []

        if len(frame_rgb.shape) != 3:
            return None, []

        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        self.frame_index += 1

        boxes, weights = self.hog.detectMultiScale(
            frame,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )

        detections: list[Detection] = []
        for idx, ((x, y, w, h), weight) in enumerate(zip(boxes, weights)):
            conf = float(weight)
            if conf < self.counting_config.min_confidence:
                continue

            detections.append(
                Detection(
                    track_id=f"hog-{self.frame_index}-{idx}",
                    label="person",
                    confidence=conf,
                    x1=int(x),
                    y1=int(y),
                    x2=int(x + w),
                    y2=int(y + h),
                )
            )

        return frame, detections

    def stop(self) -> None:
        if self.picam2 is not None:
            try:
                self.picam2.stop()
            except Exception:
                pass
            self.picam2 = None
