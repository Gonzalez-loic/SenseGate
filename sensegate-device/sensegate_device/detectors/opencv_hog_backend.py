from __future__ import annotations

import logging
import time
import cv2
import numpy as np

from .base import Detection

logger = logging.getLogger(__name__)


class OpenCVHOGBackend:
    def __init__(self, camera_config, counting_config):
        self.camera_config = camera_config
        self.counting_config = counting_config
        self.capture = None
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.frame_index = 0

    def start(self) -> None:
        source = self.camera_config.source
        self.capture = cv2.VideoCapture(source)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_config.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_config.height)
        self.capture.set(cv2.CAP_PROP_FPS, self.camera_config.fps)
        logger.info("OpenCV backend started on source=%s", source)
        time.sleep(self.camera_config.warmup_seconds)

    def read(self) -> tuple[np.ndarray | None, list[Detection]]:
        if self.capture is None:
            return None, []
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return None, []
        self.frame_index += 1

        boxes, weights = self.hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
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
        if self.capture is not None:
            self.capture.release()
            self.capture = None
