"""Internal state of the IVT-S that the BMS can read back: error counters, log data,
overcurrent detection and measurement range. Pure logic, no I/O, no clock.

Reference: docs/datasheets/IVT-S_Datasheet_V1.03.pdf
  - 3.4 Log data, 4.2 Overcurrent measurement (range switch)
  - 8.5 SET_THRESHOLD_POS / NEG (OCS), 8.6 Get Error- and Logdata
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from isascale.domain.models import (
    OVERCURRENT_RANGE_A,
    RANGE_RETURN_FACTOR,
    NominalRange,
    OcThresholds,
)

# One byte per counter in the responses ("max. 256" in the datasheet, 0..255 on the wire).
MAX_ERROR_COUNT = 0xFF
MEASUREMENT_ERROR_COUNT = 0x0F  # specific counters 0x01..0x0F (datasheet 8.6)
SYSTEM_ERROR_COUNT = 0x10  # specific counters 0x01..0x10
SYSTEM_ERROR_RESET_WATCHDOG = 0x0F  # every restart command counts here (datasheet 8.5)

# Temperature specification range of the sensor (datasheet 5.1 ambient).
TEMPERATURE_MIN_C = -40.0
TEMPERATURE_MAX_C = 105.0


class ErrorCounters:
    """Specific error counters 1..size, as read with Get measurement/system errors."""

    def __init__(self, size: int) -> None:
        self._counts = [0] * (size + 1)  # index 0 unused: counters are numbered from 1

    @property
    def size(self) -> int:
        return len(self._counts) - 1

    def is_valid(self, index: int) -> bool:
        return 1 <= index <= self.size

    def count(self, index: int) -> int:
        if not self.is_valid(index):
            raise ValueError(f"error counter must be 1..{self.size}, got {index}")
        return self._counts[index]

    def increment(self, index: int) -> None:
        self._counts[index] = min(MAX_ERROR_COUNT, self.count(index) + 1)

    def reset(self, index: int = 0) -> None:
        """index 0 = all counters (Reset Error- and Logdata DB2 = 0x00)."""
        if index == 0:
            self._counts = [0] * len(self._counts)
            return
        self.count(index)  # validates
        self._counts[index] = 0

    @property
    def any(self) -> bool:
        return any(self._counts)

    def bitmask(self) -> tuple[int, int]:
        """(DB2, DB3) of the bitmask response: counter 1..8 -> DB2 bit 0..7, 9..16 -> DB3 bit 0..7."""
        mask = 0
        for index in range(1, self.size + 1):
            if self._counts[index]:
                mask |= 1 << (index - 1)
        return mask & 0xFF, (mask >> 8) & 0xFF


class LogItem(IntEnum):
    """Log data items (datasheet 8.6, Get Overall Logdata / Logdata Since Reset DB1)."""

    AS_OVERALL = 0x01
    AS_CHARGING = 0x02
    AS_DISCHARGING = 0x03
    WH_OVERALL = 0x04
    WH_CHARGING = 0x05
    WH_DISCHARGING = 0x06
    RUNTIME_OVERALL = 0x10
    RUNTIME_I_IN = 0x11
    RUNTIME_I_OUT = 0x12
    RUNTIME_U1_IN = 0x13
    RUNTIME_U1_OUT = 0x14
    RUNTIME_U2_IN = 0x15
    RUNTIME_U2_OUT = 0x16
    RUNTIME_U3_IN = 0x17
    RUNTIME_U3_OUT = 0x18
    RUNTIME_T_IN = 0x19
    RUNTIME_T_OUT = 0x1A
    RUNTIME_OC_POS = 0x1B
    RUNTIME_OC_NEG = 0x1C
    I_MAX = 0x21
    I_MIN = 0x22
    U1_MAX = 0x23
    U1_MIN = 0x24
    U2_MAX = 0x25
    U2_MIN = 0x26
    U3_MAX = 0x27
    U3_MIN = 0x28
    T_MAX = 0x29
    T_MIN = 0x2A


@dataclass(frozen=True)
class LogSample:
    """What the log book needs from one measurement step."""

    current_ma: float
    temperature_c: float
    dt_s: float
    current_in_range: bool
    oc_positive: bool
    oc_negative: bool
    charge_counter_active: bool  # As items only count while the As result is enabled


class LogBook:
    """Log data counters (datasheet 3.4). A U0 sensor has no voltage: U and Wh items stay 0."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._as = {LogItem.AS_OVERALL: 0.0, LogItem.AS_CHARGING: 0.0, LogItem.AS_DISCHARGING: 0.0}
        self._runtime = {item: 0.0 for item in LogItem if 0x10 <= item <= 0x1C}
        self._extremes: dict[LogItem, int] = {}

    def update(self, sample: LogSample) -> None:
        dt = sample.dt_s
        if dt < 0:
            raise ValueError(f"dt must be >= 0, got {dt}")
        if sample.charge_counter_active:
            charge = sample.current_ma / 1000.0 * dt
            self._as[LogItem.AS_OVERALL] += charge
            # Sign convention of the emulator: + = discharge, - = charge.
            key = LogItem.AS_DISCHARGING if charge >= 0 else LogItem.AS_CHARGING
            self._as[key] += abs(charge)
        temperature_ok = TEMPERATURE_MIN_C <= sample.temperature_c <= TEMPERATURE_MAX_C
        self._runtime[LogItem.RUNTIME_OVERALL] += dt
        self._runtime[LogItem.RUNTIME_I_IN if sample.current_in_range else LogItem.RUNTIME_I_OUT] += dt
        self._runtime[LogItem.RUNTIME_T_IN if temperature_ok else LogItem.RUNTIME_T_OUT] += dt
        if sample.oc_positive:
            self._runtime[LogItem.RUNTIME_OC_POS] += dt
        if sample.oc_negative:
            self._runtime[LogItem.RUNTIME_OC_NEG] += dt
        self._track(LogItem.I_MAX, LogItem.I_MIN, round(sample.current_ma / 1000.0))
        self._track(LogItem.T_MAX, LogItem.T_MIN, round(sample.temperature_c * 10))

    def _track(self, high: LogItem, low: LogItem, value: int) -> None:
        self._extremes[high] = max(self._extremes.get(high, value), value)
        self._extremes[low] = min(self._extremes.get(low, value), value)

    def value(self, item: LogItem) -> int:
        """Integer value as sent in the 6-byte log data response."""
        if item in self._as:
            return round(self._as[item])
        if item in self._runtime:
            return int(self._runtime[item])
        return self._extremes.get(item, 0)


class OcDetector:
    """OCS state (result state bit 0) from the overcurrent thresholds, with hysteresis.

    Positive side: set when I >= set threshold, cleared when I < reset threshold
    (or < set threshold if no reset threshold). Negative side mirrored. 0 = off.
    """

    def __init__(self) -> None:
        self.positive = False
        self.negative = False

    @property
    def active(self) -> bool:
        return self.positive or self.negative

    def reset(self) -> None:
        self.positive = self.negative = False

    def update(self, current_ma: float, pos: OcThresholds, neg: OcThresholds) -> bool:
        current_a = current_ma / 1000.0
        self.positive = _hysteresis(self.positive, current_a, pos, sign=1)
        self.negative = _hysteresis(self.negative, current_a, neg, sign=-1)
        return self.active


def _hysteresis(active: bool, current_a: float, th: OcThresholds, sign: int) -> bool:
    if th.set_a == 0:
        return False
    value = current_a * sign
    set_level = th.set_a * sign
    release_level = (th.reset_a or th.set_a) * sign
    if value >= set_level:
        return True
    if value < release_level:
        return False
    return active


class RangeTracker:
    """Nominal / extended measurement range of the current channel (datasheet 4.2).

    Switches to the extended range when |I| exceeds the nominal range and back
    when |I| falls 5 % below it. In the extended range the current result has
    reduced precision (result state bit 1). Values beyond the overcurrent range
    saturate at its limit.
    """

    def __init__(self, nominal: NominalRange) -> None:
        self.nominal = nominal
        self.extended = False

    @property
    def limit_ma(self) -> int:
        return OVERCURRENT_RANGE_A[self.nominal] * 1000

    def reset(self) -> None:
        self.extended = False

    def update(self, current_ma: float) -> bool:
        """Return True while the extended range is in use."""
        magnitude = abs(current_ma)
        nominal_ma = int(self.nominal) * 1000
        if magnitude > nominal_ma:
            self.extended = True
        elif magnitude < nominal_ma * RANGE_RETURN_FACTOR:
            self.extended = False
        return self.extended

    def clamp(self, current_ma: int) -> int:
        return max(-self.limit_ma, min(self.limit_ma, current_ma))
