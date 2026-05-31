from __future__ import annotations

import math
from dataclasses import replace

from .types import MotionCommand, MotionState, PrinterConfig

# Number of linear segments used to approximate G2/G3 arcs.
ARC_SEGMENTS = 16


class KinematicsEngine:
    def __init__(self, config: PrinterConfig) -> None:
        self.config = config
        self._abs_mode: bool  = True    # G90=True (default), G91=False
        self._abs_e:    bool  = True    # M82=True (default), M83=False
        self._e_offset: float = 0.0    # cumulative E offset across G92 E resets

    def reset(self) -> None:
        """Reset stateful positioning modes to firmware defaults."""
        self._abs_mode = True
        self._abs_e    = True
        self._e_offset = 0.0

    def _clamp(self, value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _resolve_xyz(self, state: MotionState, cmd: MotionCommand
                     ) -> tuple[float, float, float, list[str]]:
        """Return (target_x, target_y, target_z, alarms) respecting abs/rel mode."""
        alarms: list[str] = []

        if self._abs_mode:
            raw_x = state.x if cmd.x is None else cmd.x
            raw_y = state.y if cmd.y is None else cmd.y
            raw_z = state.z if cmd.z is None else cmd.z
        else:
            raw_x = state.x + (cmd.x or 0.0)
            raw_y = state.y + (cmd.y or 0.0)
            raw_z = state.z + (cmd.z or 0.0)

        tx = self._clamp(raw_x, 0.0, self.config.build_x)
        ty = self._clamp(raw_y, 0.0, self.config.build_y)
        tz = self._clamp(raw_z, 0.0, self.config.build_z)

        if cmd.x is not None and not math.isclose(tx, raw_x):
            alarms.append("X soft-limit hit")
        if cmd.y is not None and not math.isclose(ty, raw_y):
            alarms.append("Y soft-limit hit")
        if cmd.z is not None and not math.isclose(tz, raw_z):
            alarms.append("Z soft-limit hit")

        return tx, ty, tz, alarms

    def _resolve_e(self, state: MotionState, cmd: MotionCommand) -> float:
        """Return target cumulative E respecting absolute/relative E mode.

        In absolute mode the G-code E value is relative to the last G92 reset,
        so we add _e_offset to convert it to the running total stored in state.e.
        In relative mode the delta is already accumulative.
        """
        if cmd.e is None:
            return state.e
        if self._abs_e:
            return self._e_offset + cmd.e   # firmware E + cumulative offset
        return state.e + cmd.e              # relative: just add the delta

    def _linear_move(self, state: MotionState, cmd: MotionCommand
                     ) -> MotionState:
        """Apply a single linear G0/G1 move."""
        next_state = replace(state)

        if cmd.f is not None:
            next_state.feed_rate = self._clamp(cmd.f, 1.0, self.config.max_feed_rate)

        tx, ty, tz, alarms = self._resolve_xyz(state, cmd)
        te = self._resolve_e(state, cmd)

        distance = math.dist((state.x, state.y, state.z), (tx, ty, tz))
        speed_mm_s = max(next_state.feed_rate / 60.0, 1e-6)
        dt = distance / speed_mm_s

        next_state.t += dt
        next_state.x  = tx
        next_state.y  = ty
        next_state.z  = tz
        next_state.e  = te
        next_state.alarms = alarms
        return next_state

    def apply(self, state: MotionState, cmd: MotionCommand) -> MotionState:
        next_state = replace(state)

        if cmd.f is not None and cmd.kind not in {"G2", "G3"}:
            next_state.feed_rate = self._clamp(cmd.f, 1.0, self.config.max_feed_rate)

        # ── Positioning mode ─────────────────────────────────────────────
        if cmd.kind == "G90":
            self._abs_mode = True
            next_state.alarms = []
            return next_state

        if cmd.kind == "G91":
            self._abs_mode = False
            next_state.alarms = []
            return next_state

        # ── E-axis mode ───────────────────────────────────────────────────
        if cmd.kind == "M82":
            self._abs_e = True
            next_state.alarms = []
            return next_state

        if cmd.kind == "M83":
            self._abs_e = False
            next_state.alarms = []
            return next_state

        # ── Set position (G92) ────────────────────────────────────────────
        if cmd.kind == "G92":
            if cmd.e is not None:
                # SET (not add) offset so that state.e stays equal to the running
                # cumulative total after each firmware reset.
                # Invariant: state.e = firmware_e + _e_offset
                # G92 E=v redefines firmware_e := v, so:
                #   new_e_offset = state.e - v  (keeps state.e unchanged)
                # Example: state.e=85.3, G92 E0 → _e_offset=85.3, state.e stays 85.3.
                # Next G1 E0.5 (abs): state.e = 85.3 + 0.5 = 85.8  ✓
                self._e_offset = next_state.e - cmd.e
                # state.e intentionally NOT changed — always shows total extrusion.
            if cmd.x is not None:
                next_state.x = cmd.x
            if cmd.y is not None:
                next_state.y = cmd.y
            if cmd.z is not None:
                next_state.z = cmd.z
            next_state.alarms = []
            return next_state

        # ── Homing (G28) ─────────────────────────────────────────────────
        if cmd.kind == "G28":
            if cmd.x is not None:
                next_state.x = 0.0
            if cmd.y is not None:
                next_state.y = 0.0
            if cmd.z is not None:
                next_state.z = 0.0
            next_state.alarms = []
            return next_state

        # ── Park head (G27) ───────────────────────────────────────────────
        if cmd.kind == "G27":
            park_z = min(next_state.z + 10.0, self.config.build_z)
            distance = park_z - next_state.z
            speed_mm_s = max(next_state.feed_rate / 60.0, 1e-6)
            next_state.t += distance / speed_mm_s
            next_state.z  = park_z
            next_state.alarms = []
            return next_state

        # ── Linear moves (G0/G1) ─────────────────────────────────────────
        if cmd.kind in {"G0", "G1"}:
            return self._linear_move(state, cmd)

        # ── Arc moves (G2/G3) ─────────────────────────────────────────────
        if cmd.kind in {"G2", "G3"}:
            return self._arc_move(state, cmd)

        # ── Fan / temperature / misc — no kinematic effect ────────────────
        next_state.alarms = []
        return next_state

    def _arc_move(self, state: MotionState, cmd: MotionCommand) -> MotionState:
        """
        Approximate a G2/G3 arc as ARC_SEGMENTS linear steps.
        I, J are the offsets from the current position to the arc centre.
        Returns the final state after traversing the arc.
        """
        if cmd.f is not None:
            state = replace(state,
                            feed_rate=self._clamp(cmd.f, 1.0, self.config.max_feed_rate))

        cx = state.x + (cmd.i or 0.0)
        cy = state.y + (cmd.j or 0.0)

        tx = cx + (state.x - cx) if cmd.x is None else cmd.x
        ty = cy + (state.y - cy) if cmd.y is None else cmd.y

        r  = math.hypot(state.x - cx, state.y - cy)
        a0 = math.atan2(state.y - cy, state.x - cx)
        a1 = math.atan2(ty - cy, tx - cx)

        if cmd.kind == "G2":   # clockwise
            if a1 > a0:
                a1 -= 2 * math.pi
        else:                  # G3 counter-clockwise
            if a1 < a0:
                a1 += 2 * math.pi

        # Total filament delta divided equally over segments
        e_start = state.e
        e_end   = self._resolve_e(state, cmd)
        de_per  = (e_end - e_start) / ARC_SEGMENTS

        cur = replace(state)
        for k in range(1, ARC_SEGMENTS + 1):
            t   = k / ARC_SEGMENTS
            ang = a0 + t * (a1 - a0)
            nx  = self._clamp(cx + r * math.cos(ang), 0.0, self.config.build_x)
            ny  = self._clamp(cy + r * math.sin(ang), 0.0, self.config.build_y)
            nz  = state.z if cmd.z is None else (
                state.z + t * (cmd.z - state.z))
            nz  = self._clamp(nz, 0.0, self.config.build_z)
            ne  = e_start + k * de_per

            dist = math.dist((cur.x, cur.y, cur.z), (nx, ny, nz))
            spd  = max(cur.feed_rate / 60.0, 1e-6)
            cur  = replace(cur, x=nx, y=ny, z=nz, e=ne,
                           t=cur.t + dist / spd, alarms=[])

        return cur
