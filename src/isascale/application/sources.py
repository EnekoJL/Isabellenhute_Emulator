"""Current sources: what current the emulator reports at a given elapsed time."""

from __future__ import annotations

from abc import ABC, abstractmethod

from isascale.domain.models import CurrentProfile


class CurrentSource(ABC):
    """Strategy returning the current (mA) at elapsed_s since the source was activated."""

    name: str = "source"

    @abstractmethod
    def current_at(self, elapsed_s: float) -> float: ...

    @property
    def duration_s(self) -> float | None:
        """Finite duration for progress reporting; None = endless."""
        return None

    def progress(self, elapsed_s: float) -> float | None:
        """0.0..1.0 playback progress, or None for endless sources."""
        return None


class ConstantSource(CurrentSource):
    """Fixed current, adjustable in real time (manual mode)."""

    def __init__(self, current_ma: float = 0.0, name: str = "manual") -> None:
        self.current_ma = float(current_ma)
        self.name = name

    def current_at(self, elapsed_s: float) -> float:
        return self.current_ma


class ProfileSource(CurrentSource):
    """Plays a CurrentProfile from its first point; holds last value or loops at the end."""

    def __init__(self, profile: CurrentProfile, loop: bool = False) -> None:
        self.profile = profile
        self.loop = loop
        self.name = profile.name

    @property
    def duration_s(self) -> float | None:
        return self.profile.duration_s

    def _profile_time(self, elapsed_s: float) -> float:
        duration = self.profile.duration_s
        if self.loop and duration > 0:
            elapsed_s = elapsed_s % duration
        return self.profile.start_s + elapsed_s

    def current_at(self, elapsed_s: float) -> float:
        return self.profile.current_at(self._profile_time(elapsed_s))

    def progress(self, elapsed_s: float) -> float | None:
        duration = self.profile.duration_s
        if duration <= 0:
            return 1.0
        if self.loop:
            return (elapsed_s % duration) / duration
        return min(1.0, max(0.0, elapsed_s / duration))

    def finished(self, elapsed_s: float) -> bool:
        return not self.loop and elapsed_s >= self.profile.duration_s
