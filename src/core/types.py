from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Shared simulation constants
# ---------------------------------------------------------------------------
MIN_EXTRUDE_TEMP: float = 160.0   # °C – below this E advancement is blocked
WAIT_STEP_S:      float = 0.25    # simulation-time step per heating frame (s)
HEAT_WAIT_DT:     float = 2.0     # thermal dt per heating frame (faster than real)


@dataclass(slots=True)
class MotionCommand:
    kind: str
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    e: Optional[float] = None
    f: Optional[float] = None
    nozzle_temp: Optional[float] = None
    bed_temp: Optional[float] = None
    path_kind: str = "model"      # "model" | "support" (from ;TYPE: comments)
    i: Optional[float] = None     # arc centre offset X (G2/G3)
    j: Optional[float] = None     # arc centre offset Y (G2/G3)


@dataclass(slots=True)
class MotionState:
    t: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    e: float = 0.0
    feed_rate: float = 1800.0
    nozzle_temp: float = 25.0
    bed_temp: float = 25.0
    alarms: List[str] = field(default_factory=list)


@dataclass(slots=True)
class PrinterConfig:
    build_x: float = 220.0
    build_y: float = 220.0
    build_z: float = 250.0
    max_feed_rate: float = 7200.0
