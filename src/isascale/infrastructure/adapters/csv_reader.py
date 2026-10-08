"""CsvProfileAdapter — loads a time/current profile from a CSV file (pandas + numpy).

Format: header row, '#' comments allowed, columns (case/space insensitive):
  time [s]  and either  current [A]  or  current_ma [mA]
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from isascale.domain.models import CurrentProfile
from isascale.ports.profile_port import ProfileFormatError, ProfileReaderPort

TIME_COLUMN = "time"
CURRENT_A_COLUMN = "current"
CURRENT_MA_COLUMN = "current_ma"


class CsvProfileAdapter(ProfileReaderPort):
    def load_profile(self, file_path: str | Path) -> CurrentProfile:
        path = Path(file_path)
        if not path.is_file():
            raise ProfileFormatError(f"profile file not found: {path}")
        frame = self._read(path)
        times = self._numeric_column(frame, TIME_COLUMN, path)
        currents_ma = self._current_ma(frame, path)
        self._validate(times, path)
        points = tuple((float(t), float(i)) for t, i in zip(times, currents_ma))
        try:
            return CurrentProfile(name=path.stem, points=points)
        except ValueError as exc:  # defensive: domain re-validates
            raise ProfileFormatError(f"{path.name}: {exc}") from exc

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        try:
            frame = pd.read_csv(path, comment="#", skipinitialspace=True)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
            raise ProfileFormatError(f"cannot read {path.name}: {exc}") from exc
        frame.columns = [str(c).strip().lower() for c in frame.columns]
        return frame

    def _current_ma(self, frame: pd.DataFrame, path: Path) -> np.ndarray:
        if CURRENT_MA_COLUMN in frame.columns:
            return self._numeric_column(frame, CURRENT_MA_COLUMN, path)
        if CURRENT_A_COLUMN in frame.columns:
            return self._numeric_column(frame, CURRENT_A_COLUMN, path) * 1000.0
        raise ProfileFormatError(
            f"{path.name}: missing current column ('{CURRENT_A_COLUMN}' [A] or '{CURRENT_MA_COLUMN}' [mA]); "
            f"found {list(frame.columns)}"
        )

    @staticmethod
    def _numeric_column(frame: pd.DataFrame, name: str, path: Path) -> np.ndarray:
        if name not in frame.columns:
            raise ProfileFormatError(f"{path.name}: missing column '{name}'; found {list(frame.columns)}")
        values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
        if np.isnan(values).any() or not np.isfinite(values).all():
            raise ProfileFormatError(f"{path.name}: column '{name}' has empty or non-numeric values")
        return values

    @staticmethod
    def _validate(times: np.ndarray, path: Path) -> None:
        if times.size < 2:
            raise ProfileFormatError(f"{path.name}: profile needs at least 2 rows, got {times.size}")
        if (times < 0).any():
            raise ProfileFormatError(f"{path.name}: time must be >= 0")
        if (np.diff(times) <= 0).any():
            raise ProfileFormatError(f"{path.name}: time must be strictly increasing")
