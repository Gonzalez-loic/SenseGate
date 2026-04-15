from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import logging

from sensegate_device.detectors.base import Detection
from sensegate_device.utils.time_utils import utcnow_iso

logger = logging.getLogger(__name__)


@dataclass
class TrackState:
    track_id: str
    first_side: int | None = None
    last_side: int | None = None
    stable_hits: int = 0
    missing_frames: int = 0
    counted: bool = False
    last_center: tuple[int, int] | None = None
    first_seen_at: str = field(default_factory=utcnow_iso)
    last_seen_at: str = field(default_factory=utcnow_iso)


class CountingEngine:
    def __init__(self, config):
        self.config = config
        self.tracks: dict[str, TrackState] = {}
        self.in_count = 0
        self.out_count = 0
        self.line_px = None
        self.frame_shape = None

    def configure_from_frame(self, frame_shape: tuple[int, int, int]) -> None:
        self.frame_shape = frame_shape
        h, w = frame_shape[:2]
        if self.config.mode == "horizontal":
            self.line_px = int(h * self.config.line_position)
        else:
            self.line_px = int(w * self.config.line_position)

    def _side(self, center: tuple[int, int]) -> int:
        if self.line_px is None:
            raise RuntimeError("CountingEngine not configured from frame")
        if self.config.mode == "horizontal":
            return -1 if center[1] < self.line_px else 1
        return -1 if center[0] < self.line_px else 1

    def _movement_delta(self, previous: tuple[int, int], current: tuple[int, int]) -> float:
        if self.frame_shape is None:
            return 0.0
        h, w = self.frame_shape[:2]
        axis_size = h if self.config.mode == "horizontal" else w
        prev_val = previous[1] if self.config.mode == "horizontal" else previous[0]
        curr_val = current[1] if self.config.mode == "horizontal" else current[0]
        return abs(curr_val - prev_val) / max(axis_size, 1)

    def process(self, detections: list[Detection], frame_shape: tuple[int, int, int]) -> list[dict[str, Any]]:
        if self.line_px is None:
            self.configure_from_frame(frame_shape)

        events: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        frame_area = frame_shape[0] * frame_shape[1]

        for det in detections:
            if det.label != self.config.class_name:
                continue
            if det.confidence < self.config.min_confidence:
                continue
            if det.area / max(frame_area, 1) < self.config.min_box_area_ratio:
                continue

            seen_ids.add(det.track_id)
            center = det.center
            side = self._side(center)
            state = self.tracks.get(det.track_id)
            if state is None:
                state = TrackState(track_id=det.track_id, first_side=side, last_side=side, stable_hits=1, last_center=center)
                self.tracks[det.track_id] = state
                continue

            state.stable_hits += 1
            state.last_seen_at = utcnow_iso()
            previous_center = state.last_center or center
            state.last_center = center
            previous_side = state.last_side
            state.last_side = side
            state.missing_frames = 0

            if state.counted:
                continue
            if state.stable_hits < self.config.min_stable_hits:
                continue
            if previous_side is None or previous_side == side:
                continue
            if self._movement_delta(previous_center, center) < self.config.min_crossing_delta_ratio:
                continue

            direction = "in" if previous_side < side else "out"
            state.counted = True
            if direction == "in":
                self.in_count += 1
            else:
                self.out_count += 1
            event = {
                "timestamp": utcnow_iso(),
                "track_id": det.track_id,
                "direction": direction,
                "door_name": None,
                "confidence": det.confidence,
                "bbox": {"x1": det.x1, "y1": det.y1, "x2": det.x2, "y2": det.y2},
            }
            events.append(event)
            logger.info("[COUNT] track=%s direction=%s confidence=%.2f", det.track_id, direction, det.confidence)

        for track_id, state in list(self.tracks.items()):
            if track_id in seen_ids:
                continue
            state.missing_frames += 1
            if state.missing_frames > self.config.max_missing_frames:
                del self.tracks[track_id]

        return events

    def reset(self) -> None:
        self.in_count = 0
        self.out_count = 0
        self.tracks.clear()

    def stats(self) -> dict[str, int]:
        return {"in": self.in_count, "out": self.out_count}
