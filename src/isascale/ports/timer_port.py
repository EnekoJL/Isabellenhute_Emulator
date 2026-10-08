"""Timer port — decouples the transmission loop from wall clock and GUI timers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TimerPort(ABC):
    @abstractmethod
    def now(self) -> float:
        """Monotonic time in seconds (arbitrary origin)."""

    @abstractmethod
    def sleep_until(self, deadline_s: float) -> None:
        """Block until now() >= deadline_s (return at once if already past)."""
