"""Profile reader port — loads time/current curves from an external source."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from isascale.domain.models import CurrentProfile


class ProfileFormatError(Exception):
    """File missing, unreadable, wrong columns or invalid values."""


class ProfileReaderPort(ABC):
    @abstractmethod
    def load_profile(self, file_path: str | Path) -> CurrentProfile:
        """Load a profile; raise ProfileFormatError on any problem."""
