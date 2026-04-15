from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import numpy as np


@dataclass
class Detection:
    track_id: str
    label: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


class DetectorBackend(Protocol):
    def start(self) -> None: ...
    def read(self) -> tuple[np.ndarray | None, list[Detection]]: ...
    def stop(self) -> None: ...
