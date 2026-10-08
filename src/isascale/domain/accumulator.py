"""Charge accumulator (As / Ah) — BatteryStateCounter.

Pure domain logic: trapezoidal integration of current over time.
"""

from __future__ import annotations

from isascale.domain.models import INT32_MAX, INT32_MIN

SECONDS_PER_HOUR = 3600.0


class BatteryStateCounter:
    """Integrates current (mA) over time (s) into charge (As, Ah).

    Usage: call update(current_ma, t_s) every cycle with a monotonic timestamp.
    The first call only sets the reference point. Positive current = discharge,
    so charge_as grows while discharging (same sign as IVT_Msg_Result_As).
    """

    def __init__(self, initial_as: float = 0.0) -> None:
        self._charge_as = float(initial_as)
        self._last_t: float | None = None
        self._last_ma: float | None = None

    @property
    def charge_as(self) -> float:
        return self._charge_as

    @property
    def charge_ah(self) -> float:
        return self._charge_as / SECONDS_PER_HOUR

    @property
    def charge_as_int32(self) -> int:
        """Value as sent in IVT_Msg_Result_As (1 As resolution, int32 saturated)."""
        value = int(round(self._charge_as))
        return max(INT32_MIN, min(INT32_MAX, value))

    def update(self, current_ma: float, t_s: float) -> float:
        """Add the trapezoid since the previous sample; return charge in As.

        Raises ValueError if time goes backwards.
        """
        if self._last_t is not None:
            dt = t_s - self._last_t
            if dt < 0:
                raise ValueError(f"time went backwards: {self._last_t} -> {t_s}")
            assert self._last_ma is not None
            self._charge_as += (self._last_ma + current_ma) / 2.0 / 1000.0 * dt
        self._last_t = t_s
        self._last_ma = float(current_ma)
        return self._charge_as

    def reset(self, initial_as: float = 0.0) -> None:
        """Clear the charge and the time reference (next update() restarts integration)."""
        self._charge_as = float(initial_as)
        self._last_t = None
        self._last_ma = None
