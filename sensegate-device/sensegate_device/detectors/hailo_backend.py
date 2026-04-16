from __future__ import annotations

import logging
import time
from typing import Any

import cv2
import numpy as np
from picamera2 import Picamera2
from hailo_platform import (
    HEF,
    VDevice,
    Device,
    ConfigureParams,
    InputVStreamParams,
    OutputVStreamParams,
    InferVStreams,
    HailoStreamInterface,
)

from .base import Detection

logger = logging.getLogger(__name__)


class HailoBackend:
    PERSON_CLASS_ID = 0

    def __init__(self, camera_config, counting_config, backend_config):
        self.camera_config = camera_config
        self.counting_config = counting_config
        self.backend_config = backend_config

        self.picam2 = None
        self.frame_index = 0

        self.device_arch = None
        self.hef_path = None
        self.network_group = None
        self.network_group_params = None
        self.input_vstreams_params = None
        self.output_vstreams_params = None
        self.input_name = None
        self.output_name = None
        self.target = None

    def _detect_arch_and_model(self) -> tuple[str, str]:
        pci_devices = Device.scan()
        if not pci_devices:
            raise RuntimeError("No Hailo device detected")

        h8_model = "/usr/share/hailo-models/yolov8s_h8.hef"
        h8l_model = "/usr/share/hailo-models/yolov6n_h8l.hef"

        try:
            HEF(h8_model)
            logger.info("Using Hailo-8 model: %s", h8_model)
            return "HAILO8", h8_model
        except Exception:
            pass

        try:
            HEF(h8l_model)
            logger.info("Using Hailo-8L model: %s", h8l_model)
            return "HAILO8L", h8l_model
        except Exception:
            pass

        raise RuntimeError("No compatible Hailo HEF found for this device")

    def start(self) -> None:
        self.device_arch, self.hef_path = self._detect_arch_and_model()

        self.picam2 = Picamera2()
        cfg = self.picam2.create_video_configuration(
            main={"size": (640, 640), "format": "RGB888"}
        )
        self.picam2.configure(cfg)
        self.picam2.start()
        time.sleep(self.camera_config.warmup_seconds)

        hef = HEF(self.hef_path)
        configure_params = ConfigureParams.create_from_hef(
            hef, interface=HailoStreamInterface.PCIe
        )

        self.target = VDevice()
        self.network_group = self.target.configure(hef, configure_params)[0]
        self.network_group_params = self.network_group.create_params()

        self.input_vstreams_params = InputVStreamParams.make_from_network_group(
            self.network_group, quantized=False, format_type=None
        )
        self.output_vstreams_params = OutputVStreamParams.make_from_network_group(
            self.network_group, quantized=False, format_type=None
        )

        self.input_name = hef.get_input_vstream_infos()[0].name
        self.output_name = hef.get_output_vstream_infos()[0].name

        logger.info(
            "Hailo backend started | device=%s | hef=%s | input=%s | output=%s",
            self.device_arch,
            self.hef_path,
            self.input_name,
            self.output_name,
        )

    def _extract_person_detections(self, raw_output: Any) -> list[Detection]:
        detections: list[Detection] = []

        if not isinstance(raw_output, list) or not raw_output:
            return detections

        batch0 = raw_output[0]
        if not isinstance(batch0, list):
            return detections

        if len(batch0) <= self.PERSON_CLASS_ID:
            return detections

        person_boxes = batch0[self.PERSON_CLASS_ID]
        if person_boxes is None or len(person_boxes) == 0:
            return detections

        for idx, det in enumerate(person_boxes):
            if len(det) < 5:
                continue

            x1, y1, x2, y2, score = det[:5]
            score = float(score)
            if score < float(self.counting_config.min_confidence):
                continue

            detections.append(
                Detection(
                    track_id=f"hailo-{self.frame_index}-{idx}",
                    label="person",
                    confidence=score,
                    x1=int(float(x1) * 640),
                    y1=int(float(y1) * 640),
                    x2=int(float(x2) * 640),
                    y2=int(float(y2) * 640),
                )
            )

        return detections

    def read(self) -> tuple[np.ndarray | None, list[Detection]]:
        if self.picam2 is None or self.network_group is None:
            return None, []

        frame_rgb = self.picam2.capture_array()
        if frame_rgb is None:
            return None, []

        self.frame_index += 1
        input_data = np.expand_dims(frame_rgb, axis=0).astype(np.uint8)

        with InferVStreams(
            self.network_group,
            self.input_vstreams_params,
            self.output_vstreams_params,
        ) as infer_pipeline:
            with self.network_group.activate(self.network_group_params):
                result = infer_pipeline.infer({self.input_name: input_data})

        raw_output = result.get(self.output_name)
        detections = self._extract_person_detections(raw_output)

        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        return frame_bgr, detections

    def stop(self) -> None:
        try:
            if self.picam2 is not None:
                self.picam2.stop()
                self.picam2 = None
            self.network_group = None
            self.network_group_params = None
            self.input_vstreams_params = None
            self.output_vstreams_params = None
            self.target = None
        except Exception:
            pass
