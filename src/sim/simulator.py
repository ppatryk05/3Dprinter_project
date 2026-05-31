from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Generator, List

from src.core.kinematics import ARC_SEGMENTS, KinematicsEngine
from src.core.thermal_model import ThermalModel
from src.core.types import (
    HEAT_WAIT_DT,
    MIN_EXTRUDE_TEMP,
    WAIT_STEP_S,
    MotionCommand,
    MotionState,
    PrinterConfig,
)
from src.sim.collision import CollisionDetector

STEP_MM = 1.0  # one visual frame per mm of movement


@dataclass(slots=True)
class SimulationFrame:
    state: MotionState
    issues: list[str]
    path_kind: str = "model"   # "model" | "support"


def _lerp_states(prev: MotionState, nxt: MotionState, steps: int) -> Generator[MotionState, None, None]:
    """Yield `steps` linearly-interpolated intermediate states from prev→nxt."""
    for i in range(1, steps + 1):
        t = i / steps
        yield replace(
            nxt,
            x=prev.x + t * (nxt.x - prev.x),
            y=prev.y + t * (nxt.y - prev.y),
            z=prev.z + t * (nxt.z - prev.z),
            e=prev.e + t * (nxt.e - prev.e),
            t=prev.t + t * (nxt.t - prev.t),
        )


class PrinterSimulator:
    def __init__(self, config: PrinterConfig | None = None) -> None:
        self.config = config or PrinterConfig()
        self.kinematics = KinematicsEngine(self.config)
        self.thermal = ThermalModel()
        self.collision = CollisionDetector(self.config)
        self.frames: List[SimulationFrame] = []

    def run(self, commands: List[MotionCommand]) -> List[SimulationFrame]:
        self.frames.clear()
        self.kinematics.reset()   # clear G90/G91/M82/M83 state from previous run
        self.thermal.reset()      # clear PID integrator and thermal rate from previous run
        prev = MotionState()
        self.frames.append(SimulationFrame(state=prev, issues=[], path_kind="model"))

        for cmd in commands:
            # ------------------------------------------------------------------
            # M109 / M190  — block until target temperature is reached
            # ------------------------------------------------------------------
            if cmd.kind == "M109" and cmd.nozzle_temp is not None:
                target = cmd.nozzle_temp
                wait_cmd = MotionCommand(kind="M104", nozzle_temp=target)
                while prev.nozzle_temp < target - 0.5:
                    wait_state = replace(prev, t=prev.t + WAIT_STEP_S)
                    wait_state = self.thermal.apply(wait_state, wait_cmd, HEAT_WAIT_DT)
                    self.frames.append(SimulationFrame(state=wait_state, issues=[], path_kind="model"))
                    prev = wait_state
                # Final frame at exactly the target
                snap = replace(prev, nozzle_temp=target)
                self.frames.append(SimulationFrame(state=snap, issues=[], path_kind="model"))
                prev = snap
                continue

            if cmd.kind == "M190" and cmd.bed_temp is not None:
                target = cmd.bed_temp
                wait_cmd = MotionCommand(kind="M140", bed_temp=target)
                while prev.bed_temp < target - 0.5:
                    wait_state = replace(prev, t=prev.t + WAIT_STEP_S)
                    wait_state = self.thermal.apply(wait_state, wait_cmd, HEAT_WAIT_DT)
                    self.frames.append(SimulationFrame(state=wait_state, issues=[], path_kind="model"))
                    prev = wait_state
                snap = replace(prev, bed_temp=target)
                self.frames.append(SimulationFrame(state=snap, issues=[], path_kind="model"))
                prev = snap
                continue

            # ------------------------------------------------------------------
            # All other commands — standard path
            # ------------------------------------------------------------------
            moved = self.kinematics.apply(prev, cmd)
            dt = max(moved.t - prev.t, 0.01)
            next_state = self.thermal.apply(moved, cmd, dt)
            issues = list(next_state.alarms) + self.collision.check(next_state)

            if cmd.kind in {"G0", "G1"}:
                delta_e = next_state.e - prev.e

                # Block cold extrusion: prevent E from advancing below threshold
                if delta_e > 0 and next_state.nozzle_temp < MIN_EXTRUDE_TEMP:
                    issues.append(
                        f"Cold extrusion blocked: nozzle below {MIN_EXTRUDE_TEMP:.0f}°C "
                        f"(currently {next_state.nozzle_temp:.0f}°C)"
                    )
                    next_state = replace(next_state, e=prev.e)

                distance = math.dist(
                    (prev.x, prev.y, prev.z),
                    (next_state.x, next_state.y, next_state.z),
                )
                steps = max(1, int(distance / STEP_MM))
                for interp in _lerp_states(prev, next_state, steps):
                    self.frames.append(SimulationFrame(
                        state=interp,
                        issues=issues,
                        path_kind=cmd.path_kind,
                    ))
                    prev = interp

            elif cmd.kind in {"G2", "G3"}:
                # Arc: kinematics already produced the final state via _arc_move.
                # Re-expand into ARC_SEGMENTS linear lerp steps for animation.
                delta_e = next_state.e - prev.e
                if delta_e > 0 and next_state.nozzle_temp < MIN_EXTRUDE_TEMP:
                    issues.append(
                        f"Cold extrusion blocked: nozzle below {MIN_EXTRUDE_TEMP:.0f}°C "
                        f"(currently {next_state.nozzle_temp:.0f}°C)"
                    )
                    next_state = replace(next_state, e=prev.e)

                for interp in _lerp_states(prev, next_state, ARC_SEGMENTS):
                    self.frames.append(SimulationFrame(
                        state=interp,
                        issues=issues,
                        path_kind=cmd.path_kind,
                    ))
                    prev = interp

            else:
                self.frames.append(SimulationFrame(
                    state=next_state,
                    issues=issues,
                    path_kind=cmd.path_kind,
                ))
                prev = next_state

        return self.frames
