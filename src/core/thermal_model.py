from __future__ import annotations

from dataclasses import replace

from .types import MotionCommand, MotionState


class _PIDChannel:
    """
    PD controller with steady-state feedforward for a thermal plant.

    Plant:  dT/dt = output * max_heat_rate - cool_coeff * (T - ambient)

    Feedforward pre-computes the heater fraction needed at steady state:
        ff = cool_coeff * (target - ambient) / max_heat_rate
    This eliminates steady-state error without an integral term and avoids
    the windup problem that arises when the plant has large initial errors.

    The derivative term damps overshoot as the temperature approaches target.

    Result: fast rise → small realistic overshoot (~5 °C) → stable settling.
    """

    _MAX_SUBSTEP: float = 0.10  # seconds

    def __init__(self,
                 kp: float,
                 max_heat_rate: float, cool_coeff: float,
                 inertia_tau: float = 0.0,
                 ambient: float = 25.0) -> None:
        self.kp            = kp
        self.max_heat_rate = max_heat_rate
        self.cool_coeff    = cool_coeff
        self.ambient       = ambient
        # inertia_tau: time constant (s) for thermal mass lag.
        # > 0 creates a realistic overshoot; 0 = no overshoot.
        self.inertia_tau   = inertia_tau

        self._rate: float = 0.0   # current temperature change rate (°C/s)

    def reset(self) -> None:
        self._rate = 0.0

    def step(self, current: float, target: float, dt: float) -> float:
        remaining = dt
        while remaining > 0.0:
            h = min(remaining, self._MAX_SUBSTEP)
            remaining -= h
            current = self._substep(current, target, h)
        return current

    def _substep(self, current: float, target: float, h: float) -> float:
        error = target - current

        # Feedforward: heater fraction needed to hold target temperature
        ff = self.cool_coeff * max(0.0, target - self.ambient) / self.max_heat_rate
        output = max(0.0, min(1.0, ff + self.kp * error))

        # Instantaneous desired temperature change rate
        desired_rate = (output * self.max_heat_rate
                        - self.cool_coeff * (current - self.ambient))

        if self.inertia_tau > 0:
            # First-order lag on heating rate → second-order plant → overshoot
            alpha = h / max(self.inertia_tau, h)
            self._rate += (desired_rate - self._rate) * alpha
            actual_rate = self._rate
        else:
            actual_rate = desired_rate

        return current + actual_rate * h


class ThermalModel:
    """
    PID-based thermal model.  Produces realistic heating curves:
      - nozzle: fast rise, ~5–10 °C overshoot, settles in ~15–20 s
      - bed: slow rise, minimal overshoot, settles in ~30–40 s
    """

    def __init__(self, ambient: float = 25.0) -> None:
        self.ambient        = ambient
        self.target_nozzle  = ambient
        self.target_bed     = ambient

        # Nozzle — small mass, fast heater; inertia_tau=1.2s gives ~8°C overshoot
        self._nozzle = _PIDChannel(
            kp=0.30,
            max_heat_rate=38.0, cool_coeff=0.09,
            inertia_tau=1.2,
            ambient=ambient,
        )
        # Bed — large mass, slow heater; inertia_tau=3s gives ~4°C overshoot
        self._bed = _PIDChannel(
            kp=0.25,
            max_heat_rate=5.0, cool_coeff=0.022,
            inertia_tau=3.0,
            ambient=ambient,
        )

    def reset(self) -> None:
        self._nozzle.reset()
        self._bed.reset()
        self.target_nozzle = self.ambient
        self.target_bed    = self.ambient

    def apply(self, state: MotionState, cmd: MotionCommand, dt: float) -> MotionState:
        next_state = replace(state)
        if cmd.nozzle_temp is not None:
            self.target_nozzle = cmd.nozzle_temp
        if cmd.bed_temp is not None:
            self.target_bed = cmd.bed_temp

        next_state.nozzle_temp = self._nozzle.step(
            next_state.nozzle_temp, self.target_nozzle, dt)
        next_state.bed_temp = self._bed.step(
            next_state.bed_temp, self.target_bed, dt)
        return next_state
