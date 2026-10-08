"""Use cases driven by the presentation layer (GUI / CLI)."""

from __future__ import annotations

from pathlib import Path

from isascale.application.bms_requests import CommandOutcome, HandleBmsRequestsUseCase
from isascale.application.builtin_profiles import BUILTIN_PROFILES
from isascale.application.emulator_service import EmulatorService
from isascale.application.sources import ConstantSource, ProfileSource
from isascale.domain.models import CurrentProfile
from isascale.ports.profile_port import ProfileReaderPort

__all__ = [
    "CommandOutcome",
    "HandleBmsRequestsUseCase",
    "RunCsvProfileEmulationUseCase",
    "RunManualEmulationUseCase",
]


class RunManualEmulationUseCase:
    """Cyclic transmission of a fixed current, adjustable in real time."""

    def __init__(self, service: EmulatorService) -> None:
        self._service = service

    def start(self, current_ma: float = 0.0) -> None:
        self._service.set_current_source(ConstantSource(current_ma))
        self._service.start()

    def set_current(self, current_ma: float) -> None:
        self._service.set_manual_current(current_ma)

    def stop(self) -> None:
        self._service.stop()


class RunCsvProfileEmulationUseCase:
    """Playback of a time/current profile (CSV file or built-in)."""

    def __init__(self, service: EmulatorService, reader: ProfileReaderPort) -> None:
        self._service = service
        self._reader = reader
        self._profile: CurrentProfile | None = None

    @property
    def profile(self) -> CurrentProfile | None:
        return self._profile

    def load(self, file_path: str | Path) -> CurrentProfile:
        """Load a CSV profile (raises ProfileFormatError)."""
        self._profile = self._reader.load_profile(file_path)
        return self._profile

    def use_builtin(self, key: str) -> CurrentProfile:
        """Select a built-in profile: 'wot', 'regen' or 'idle' (KeyError otherwise)."""
        self._profile = BUILTIN_PROFILES[key]()
        return self._profile

    def start(self, loop: bool = False) -> None:
        if self._profile is None:
            raise RuntimeError("no profile loaded")
        self._service.set_current_source(ProfileSource(self._profile, loop=loop))
        if not self._service.running:
            self._service.start()

    def progress(self) -> float | None:
        return self._service.snapshot().source_progress

    def stop(self) -> None:
        self._service.stop()
