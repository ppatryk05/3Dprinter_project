from __future__ import annotations

from src.core.types import MotionState, PrinterConfig


class CollisionDetector:
    def __init__(self, config: PrinterConfig) -> None:
        self.config = config

    def check(self, state: MotionState) -> list[str]:
        issues: list[str] = []
        if not (0.0 <= state.x <= self.config.build_x):
            issues.append("Head out of bounds on X")
        if not (0.0 <= state.y <= self.config.build_y):
            issues.append("Head out of bounds on Y")
        if not (0.0 <= state.z <= self.config.build_z):
            issues.append("Head out of bounds on Z")
        return issues
