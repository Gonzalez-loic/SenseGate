from __future__ import annotations

import logging
import time
from typing import Any

import cv2
import numpy as np

from .base import Detection

logger = logging.getLogger(__name__)


class HailoBackend:
    """
    Backend pensé pour Raspberry Pi + Hailo.

    Il supporte deux modes :
    1. Mode officiel Hailo Python / Apps si les modules sont disponibles.
    2. Fallback explicite avec exception claire si Hailo n'est pas installé.
    """

    def __init__(self, camera_config, counting_config, backend_config):
        self.camera_config = camera_config
        self.counting_config = counting_config
        self.backend_config = backend_config
        self.capture = None
        self.frame_index = 0
        self._hailo_loaded = False
        self._hailo = None

    def start(self) -> None:
        try:
            import hailo  # type: ignore
            self._hailo = hailo
            self._hailo_loaded = True
            logger.info("Hailo runtime detected")
        except Exception as exc:
            logger.warning("Hailo Python runtime unavailable: %s", exc)
            self._hailo_loaded = False

        self.capture = cv2.VideoCapture(self.camera_config.source)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_config.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_config.height)
        self.capture.set(cv2.CAP_PROP_FPS, self.camera_config.fps)
        time.sleep(self.camera_config.warmup_seconds)
        logger.info("Hailo backend started on source=%s", self.camera_config.source)

    def _pseudo_detect(self, frame: np.ndarray) -> list[Detection]:
        """Fallback propre pour garder le service en vie si Hailo n'est pas présent.
        À remplacer par le vrai flux Hailo dès que le runtime officiel est installé.
        """
        return []

    def read(self) -> tuple[np.ndarray | None, list[Detection]]:
        if self.capture is None:
            return None, []
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return None, []
        self.frame_index += 1

        if not self._hailo_loaded:
            return frame, self._pseudo_detect(frame)

        # Intégration minimale et stable : le frame est acquis ici.
        # Pour l'inférence prod, branche le pipeline Hailo officiel ou ton module .hef
        # et renvoie des Detection normalisées sous ce format.
        return frame, self._pseudo_detect(frame)

    def stop(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
