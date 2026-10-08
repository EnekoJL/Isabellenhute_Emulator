"""Pure domain models for the IVT-S-U0 emulator.

No third-party imports allowed in this module (hexagonal core).
Reference: docs/datasheets/IVT-S_Datasheet_V1.03.pdf, chapter 8.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from enum import Enum, IntEnum, IntFlag

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1

MIN_CYCLE_MS = 1
MAX_CYCLE_MS = 100
# Datasheet 8.1: total output rate of all messages must not exceed 1000 msg/s.
MAX_TOTAL_MESSAGES_PER_S = 1000


class BusState(Enum):
    """CAN bus health as shown in the GUI status LED."""

    DISCONNECTED = "DISCONNECTED"
    BUS_OK = "BUS_OK"
    WARNING = "WARNING"  # error-passive or recent TX errors
    BUS_OFF = "BUS_OFF"


class Bitrate(IntEnum):
    """Bitrates supported by the IVT-S (datasheet 8, "Selectable bitrate")."""

    B250K = 250_000
    B500K = 500_000
    B1M = 1_000_000


class ResultState(IntFlag):
    """IVT_Result_state, high nibble of DB1 in every result message (datasheet 8.2)."""

    NONE = 0
    OCS = 0x1  # bit 0: overcurrent detection active
    OUT_OF_RANGE = 0x2  # bit 1: this result out of spec range / reduced precision / meas. error
    ANY_MEASUREMENT_ERROR = 0x4  # bit 2: any result has a measurement error
    SYSTEM_ERROR = 0x8  # bit 3: any result has a system error


class OperationMode(IntEnum):
    """Sensor operation mode (datasheet 8.5, SET_MODE 0x34)."""

    STOP = 0x00
    RUN = 0x01


class NominalRange(IntEnum):
    """IVT-S current variants in A (datasheet 7, ordering code IVT-S-<range>-U0-...)."""

    A100 = 100
    A300 = 300
    A500 = 500
    A1000 = 1000
    A2500 = 2500


@dataclass(frozen=True)
class CANFrame:
    """Classic CAN 2.0A frame (11-bit identifier, up to 8 data bytes)."""

    arbitration_id: int
    data: bytes
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.arbitration_id <= 0x7FF:
            raise ValueError(f"11-bit CAN id expected, got 0x{self.arbitration_id:X}")
        if len(self.data) > 8:
            raise ValueError(f"CAN 2.0 payload max 8 bytes, got {len(self.data)}")
        # Normalise bytearray/list to immutable bytes.
        object.__setattr__(self, "data", bytes(self.data))

    @property
    def dlc(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class BusStatus:
    """Snapshot of CAN adapter health, returned by CanBusPort.get_bus_status()."""

    state: BusState
    tx_count: int = 0
    rx_count: int = 0
    tx_errors: int = 0
    detail: str = ""


@dataclass(frozen=True)
class SensorReading:
    """One set of values the emulated sensor reports in a cycle.

    Sign convention: positive current = discharge (battery -> motor),
    negative = charge (regenerative braking / charger).
    """

    current_ma: int
    temperature_c: float = 25.0
    charge_as: float = 0.0
    state: ResultState = ResultState.NONE


@dataclass(frozen=True)
class IVTConfig:
    """Static configuration of the emulated IVT-S-U0 sensor and its bus."""

    channel: str = "0"
    bitrate: Bitrate = Bitrate.B500K
    current_period_ms: int = 20  # datasheet default
    temperature_period_ms: int = 100  # datasheet default
    charge_period_ms: int = 30  # datasheet default
    temperature_enabled: bool = True
    charge_enabled: bool = True
    serial_number: int = 0x00012345
    nominal_range: NominalRange = NominalRange.A1000
    send_alive_on_start: bool = True

    def __post_init__(self) -> None:
        for name in ("current_period_ms", "temperature_period_ms", "charge_period_ms"):
            value = getattr(self, name)
            if not MIN_CYCLE_MS <= value <= MAX_CYCLE_MS:
                raise ValueError(f"{name} must be {MIN_CYCLE_MS}..{MAX_CYCLE_MS} ms, got {value}")
        if not 0 <= self.serial_number <= 0xFFFFFFFF:
            raise ValueError("serial_number must fit in 32 bits")
        if self.total_messages_per_s() > MAX_TOTAL_MESSAGES_PER_S:
            raise ValueError(
                f"total output rate {self.total_messages_per_s():.0f} msg/s exceeds "
                f"{MAX_TOTAL_MESSAGES_PER_S} msg/s (datasheet 8.1)"
            )

    def total_messages_per_s(self) -> float:
        rate = 1000.0 / self.current_period_ms
        if self.temperature_enabled:
            rate += 1000.0 / self.temperature_period_ms
        if self.charge_enabled:
            rate += 1000.0 / self.charge_period_ms
        return rate


class MessageCounter:
    """4-bit cyclic counter IVT_MsgCount (0x0..0xF), one per result channel."""

    MODULO = 16

    def __init__(self, start: int = 0) -> None:
        if not 0 <= start < self.MODULO:
            raise ValueError("counter start must be 0..15")
        self._value = start

    @property
    def value(self) -> int:
        return self._value

    def next(self) -> int:
        """Return the current value and advance (wraps 0xF -> 0x0)."""
        current = self._value
        self._value = (self._value + 1) % self.MODULO
        return current

    def reset(self) -> None:
        self._value = 0


@dataclass(frozen=True)
class CurrentProfile:
    """Time/current curve, linearly interpolated, clamped at both ends.

    points: (time_s, current_ma) with strictly increasing time, at least 2 points.
    """

    name: str
    points: tuple[tuple[float, float], ...]
    _times: tuple[float, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("profile needs at least 2 points")
        times = tuple(float(t) for t, _ in self.points)
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("profile times must be strictly increasing")
        if times[0] < 0:
            raise ValueError("profile times must be >= 0")
        object.__setattr__(self, "points", tuple((float(t), float(i)) for t, i in self.points))
        object.__setattr__(self, "_times", times)

    @property
    def start_s(self) -> float:
        return self._times[0]

    @property
    def end_s(self) -> float:
        return self._times[-1]

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def current_at(self, t_s: float) -> float:
        """Linear interpolation of current (mA) at absolute profile time t_s."""
        if t_s <= self.start_s:
            return self.points[0][1]
        if t_s >= self.end_s:
            return self.points[-1][1]
        idx = bisect.bisect_right(self._times, t_s)
        (t0, i0), (t1, i1) = self.points[idx - 1], self.points[idx]
        return i0 + (i1 - i0) * (t_s - t0) / (t1 - t0)
