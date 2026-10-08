"""PrecisionTimer — TimerPort with hybrid sleep/spin waiting (target jitter <= 1 ms)."""

from __future__ import annotations

import sys
import time

from isascale.ports.timer_port import TimerPort

# Below this remaining time we stop sleeping and spin (OS sleep granularity).
SPIN_THRESHOLD_S = 0.002


class PrecisionTimer(TimerPort):
    """perf_counter clock; sleeps coarsely, then spins the last ~2 ms.

    On Windows it requests a 1 ms system timer resolution (timeBeginPeriod),
    best effort: failures are ignored.
    """

    def __init__(self) -> None:
        self._win_period_set = False
        if sys.platform == "win32":
            self._win_period_set = self._time_period(begin=True)

    def now(self) -> float:
        return time.perf_counter()

    def sleep_until(self, deadline_s: float) -> None:
        remaining = deadline_s - time.perf_counter()
        if remaining > SPIN_THRESHOLD_S:
            time.sleep(remaining - SPIN_THRESHOLD_S)
        while time.perf_counter() < deadline_s:
            time.sleep(0)  # yield the GIL to the GUI thread while spinning

    def close(self) -> None:
        """Restore the Windows timer resolution (no-op elsewhere)."""
        if self._win_period_set:
            self._time_period(begin=False)
            self._win_period_set = False

    @staticmethod
    def _time_period(begin: bool) -> bool:
        try:
            import ctypes

            winmm = ctypes.WinDLL("winmm")  # type: ignore[attr-defined]
            fn = winmm.timeBeginPeriod if begin else winmm.timeEndPeriod
            return fn(1) == 0
        except Exception:  # noqa: BLE001 - best effort only
            return False
