"""Pure domain models for the IVT-S-U0 emulator.

No third-party imports allowed in this module (hexagonal core).
Reference: docs/datasheets/IVT-S_Datasheet_V1.03.pdf, chapter 8.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field, replace
from enum import Enum, IntEnum, IntFlag

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1

MIN_CYCLE_MS = 1
# Config Result DB2..3 is a 16-bit cycle time in ms (datasheet 8.4).
MAX_CYCLE_MS = 0xFFFF
# Voltage results U1..U3 cannot be faster than 3 ms (datasheet 8.1, 4.1).
MIN_VOLTAGE_CYCLE_MS = 3
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


# Overcurrent (extended) measurement range in A per variant (datasheet 5.3).
OVERCURRENT_RANGE_A = {
    NominalRange.A100: 800,
    NominalRange.A300: 2500,
    NominalRange.A500: 6900,
    NominalRange.A1000: 12200,
    NominalRange.A2500: 48000,
}
# Back to the nominal range when |I| drops 5 % below its upper limit (datasheet 4.2).
RANGE_RETURN_FACTOR = 0.95


class Mux(IntEnum):
    """Result channel n: MuxID 0x0n, Set CAN ID 0x1n, Config 0x2n/0x6n/0xAn (datasheet 8.2)."""

    I = 0x0  # noqa: E741 - datasheet name
    U1 = 0x1
    U2 = 0x2
    U3 = 0x3
    T = 0x4
    W = 0x5
    AS = 0x6
    WH = 0x7


# Channels a U0 sensor actually measures (no voltage input: no U1..U3, W, Wh results).
EMULATED_CHANNELS = (Mux.I, Mux.T, Mux.AS)


class TriggerMode(IntEnum):
    """Config Result DB1 low nibble (datasheet 8.4)."""

    DISABLED = 0x0
    TRIGGERED = 0x1
    CYCLIC = 0x2


@dataclass(frozen=True)
class ChannelConfig:
    """Measurement configuration of one result channel (datasheet 8.4 Config Result).

    cycle_ms is the output cycle time (cyclic) or the trigger delay (triggered).
    The error-mask flag (bit 5) is global and lives in SensorSettings.
    """

    mode: TriggerMode
    cycle_ms: int
    little_endian: bool = False  # flag bit 6
    invert_sign: bool = False  # flag bit 7

    def __post_init__(self) -> None:
        if not MIN_CYCLE_MS <= self.cycle_ms <= MAX_CYCLE_MS:
            raise ValueError(f"cycle_ms must be {MIN_CYCLE_MS}..{MAX_CYCLE_MS}, got {self.cycle_ms}")


@dataclass(frozen=True)
class OcThresholds:
    """Overcurrent set / reset thresholds of one direction, in A; 0 = off (datasheet 8.5)."""

    set_a: int = 0
    reset_a: int = 0


DEFAULT_COMMAND_ID = 0x411
DEFAULT_RESPONSE_ID = 0x511
DEFAULT_RESULT_IDS = (0x521, 0x522, 0x523, 0x524, 0x525, 0x526, 0x527, 0x528)
# Datasheet 8.1 default output configuration, indexed by Mux.
DEFAULT_CHANNELS = (
    ChannelConfig(TriggerMode.CYCLIC, 20),  # I
    ChannelConfig(TriggerMode.CYCLIC, 60),  # U1
    ChannelConfig(TriggerMode.CYCLIC, 60),  # U2
    ChannelConfig(TriggerMode.CYCLIC, 60),  # U3
    ChannelConfig(TriggerMode.DISABLED, 100),  # T
    ChannelConfig(TriggerMode.DISABLED, 30),  # W
    ChannelConfig(TriggerMode.DISABLED, 30),  # As
    ChannelConfig(TriggerMode.DISABLED, 30),  # Wh
)


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
class SensorSettings:
    """Everything the sensor keeps in its configuration (and STOREs to non-volatile memory).

    channels and result_ids are indexed by Mux. Immutable: edit with the with_* helpers.
    """

    channels: tuple[ChannelConfig, ...] = DEFAULT_CHANNELS
    result_ids: tuple[int, ...] = DEFAULT_RESULT_IDS
    command_id: int = DEFAULT_COMMAND_ID
    response_id: int = DEFAULT_RESPONSE_ID
    error_mask_reporting: bool = False  # Config Result flag bit 5, global (datasheet 8.4)
    oc_positive: OcThresholds = field(default_factory=OcThresholds)
    oc_negative: OcThresholds = field(default_factory=OcThresholds)
    startup_mode: OperationMode = OperationMode.RUN

    def __post_init__(self) -> None:
        if len(self.channels) != len(Mux) or len(self.result_ids) != len(Mux):
            raise ValueError(f"channels and result_ids need {len(Mux)} entries (one per Mux)")
        for can_id in (*self.result_ids, self.command_id, self.response_id):
            if not 0 < can_id <= 0x7FF:
                raise ValueError(f"11-bit CAN id 0x001..0x7FF expected, got 0x{can_id:X}")

    def channel(self, mux: Mux) -> ChannelConfig:
        return self.channels[mux]

    def with_channel(self, mux: Mux, config: ChannelConfig) -> SensorSettings:
        channels = list(self.channels)
        channels[mux] = config
        return replace(self, channels=tuple(channels))

    def with_result_id(self, mux: Mux, can_id: int) -> SensorSettings:
        ids = list(self.result_ids)
        ids[mux] = can_id
        return replace(self, result_ids=tuple(ids))


@dataclass(frozen=True)
class IVTConfig:
    """Emulator configuration: bus, sensor identity and the settings stored in the sensor.

    Defaults follow datasheet 8.1 (only the current channel is enabled) and 5.1
    (start-up time). The periods are what the sensor holds in its non-volatile
    memory; the BMS can still change them at run time over CAN (Config Result).
    """

    channel: str = "0"
    bitrate: Bitrate = Bitrate.B500K
    current_period_ms: int = 20  # datasheet default
    temperature_period_ms: int = 100  # datasheet default
    charge_period_ms: int = 30  # datasheet default
    temperature_enabled: bool = False  # datasheet default: disabled
    charge_enabled: bool = False  # datasheet default: disabled
    serial_number: int = 0x00012345
    nominal_range: NominalRange = NominalRange.A1000
    send_alive_on_start: bool = True
    startup_mode: OperationMode = OperationMode.RUN
    startup_time_ms: int = 400  # datasheet 5.1: re-/start-up time 350..400 ms

    def __post_init__(self) -> None:
        for name in ("current_period_ms", "temperature_period_ms", "charge_period_ms"):
            value = getattr(self, name)
            if not MIN_CYCLE_MS <= value <= MAX_CYCLE_MS:
                raise ValueError(f"{name} must be {MIN_CYCLE_MS}..{MAX_CYCLE_MS} ms, got {value}")
        if not 0 <= self.serial_number <= 0xFFFFFFFF:
            raise ValueError("serial_number must fit in 32 bits")
        if not 0 <= self.startup_time_ms <= 10_000:
            raise ValueError(f"startup_time_ms must be 0..10000, got {self.startup_time_ms}")
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

    def to_settings(self) -> SensorSettings:
        """The sensor settings this configuration stands for (datasheet defaults elsewhere)."""

        def cyclic_if(enabled: bool) -> TriggerMode:
            return TriggerMode.CYCLIC if enabled else TriggerMode.DISABLED

        return (
            SensorSettings(startup_mode=self.startup_mode)
            .with_channel(Mux.I, ChannelConfig(TriggerMode.CYCLIC, self.current_period_ms))
            .with_channel(Mux.T, ChannelConfig(cyclic_if(self.temperature_enabled), self.temperature_period_ms))
            .with_channel(Mux.AS, ChannelConfig(cyclic_if(self.charge_enabled), self.charge_period_ms))
        )


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
