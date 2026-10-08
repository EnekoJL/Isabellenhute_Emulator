"""View models — plain data the presenter pushes to the view (no Qt).

Texts are already formatted; colours are expressed as a Tone that the view maps
to its theme. The view never interprets domain objects itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Tone(Enum):
    NORMAL = "normal"
    DIM = "dim"
    NEUTRAL = "neutral"
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ConnectionForm:
    """Values of the connection form, read by the view and passed to the presenter."""

    channel: str
    bitrate: int
    current_period_ms: int
    temperature_period_ms: int
    charge_period_ms: int
    temperature_enabled: bool
    charge_enabled: bool


@dataclass(frozen=True)
class ConnectionOptions:
    bitrates: tuple[tuple[str, int], ...]  # (label, bit/s)
    period_min_ms: int
    period_max_ms: int


@dataclass(frozen=True)
class ControlsViewModel:
    connection_editable: bool
    connect_text: str
    connect_danger: bool
    start_manual_enabled: bool
    start_profile_enabled: bool
    stop_enabled: bool


@dataclass(frozen=True)
class BusStatusViewModel:
    state_text: str
    tone: Tone
    rate_text: str
    counters_text: str
    detail: str


@dataclass(frozen=True)
class TelemetryViewModel:
    current: str
    temperature: str
    charge_as: str
    charge_ah: str
    mode: str
    mode_tone: Tone
    frames: str
    frames_tone: Tone
    state: str
    state_tone: Tone
    source: str


@dataclass(frozen=True)
class ProfileChoice:
    key: str
    label: str


@dataclass(frozen=True)
class PlotViewModel:
    times_s: tuple[float, ...]
    current_a: tuple[float, ...]
