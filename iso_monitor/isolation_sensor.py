"""
Isolation sensor CAN message parser.
Mirrors isolation_sensor.c logic from the SCS firmware.

All message IDs use extended 29-bit CAN frames (IDs > 0x7FF).
Counter is always buf[1] bits 0-3 (lower nibble).
"""

from dataclasses import dataclass, field
from enum import IntEnum


# ---------------------------------------------------------------------------
# CAN message IDs
# ---------------------------------------------------------------------------
MSG_IVT_HVBATTERY           = 0x1000
MSG_IVT_VOLTAGELINK         = 0x1010
MSG_IVT_VOLTAGEPACK         = 0x1020
MSG_IVT_VOLTAGELINKPRCHDIFF = 0x1030
MSG_IVT_ISORESTOTAL         = 0x1040
MSG_IVT_ISORESPOSNEG        = 0x1050
MSG_IVT_ISORESPACKLINK      = 0x1060
MSG_IVT_TEMPERATURE         = 0x1070

ALL_MSG_IDS = {
    MSG_IVT_HVBATTERY,
    MSG_IVT_VOLTAGELINK,
    MSG_IVT_VOLTAGEPACK,
    MSG_IVT_VOLTAGELINKPRCHDIFF,
    MSG_IVT_ISORESTOTAL,
    MSG_IVT_ISORESPOSNEG,
    MSG_IVT_ISORESPACKLINK,
    MSG_IVT_TEMPERATURE,
}

# ---------------------------------------------------------------------------
# Conversion constants
# ---------------------------------------------------------------------------
CURRENT_OFFSET     = -16777.216
CURRENT_RESOLUTION = 0.002
VOLTAGE_OFFSET     = -2097.152
VOLTAGE_RESOLUTION = 0.004


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class CurrentStatus(IntEnum):
    VALID         = 0x00
    INIT          = 0x01
    OC_L1         = 0x02
    OC_L2         = 0x03
    NOT_AVAILABLE = 0x0E
    ERROR         = 0x0F

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class VoltageStatus(IntEnum):
    VALID         = 0x00
    INIT          = 0x01
    OV_L1         = 0x02
    NOT_AVAILABLE = 0x0E
    ERROR         = 0x0F

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class ResThreshold(IntEnum):
    VALID = 0x00
    WARN  = 0x01
    ERR   = 0x02
    NE    = 0x03

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class SafeToStart(IntEnum):
    NOT_EXECUTED = 0x00
    RUNNING      = 0x01
    NOT_SAFE     = 0x02
    SAFE         = 0x03

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class ResStatus(IntEnum):
    VALID    = 0x00
    INIT     = 0x01
    STARTUP  = 0x02
    DISABLED = 0x03

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class EarthLiftStatus(IntEnum):
    OPEN   = 0x00
    CLOSED = 0x01

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class PosNegStatus(IntEnum):
    MEASUREMENT_POSSIBLE     = 0x00
    MEASUREMENT_NOT_POSSIBLE = 0x01
    POS_NOT_POSSIBLE         = 0x02
    NEG_NOT_POSSIBLE         = 0x03

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class PackLinkStatus(IntEnum):
    MEASUREMENT_POSSIBLE      = 0x00
    MEASUREMENT_NOT_POSSIBLE  = 0x01
    PACK_NOT_POSSIBLE         = 0x02
    LINK_NOT_POSSIBLE         = 0x03

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


class TempStatus(IntEnum):
    VALID         = 0x00
    INIT          = 0x01
    OT            = 0x02
    UT            = 0x03
    NOT_AVAILABLE = 0x0E
    ERROR         = 0x0F

    @classmethod
    def label(cls, val: int) -> str:
        try:
            return cls(val).name
        except ValueError:
            return f"0x{val:02X}"


# ---------------------------------------------------------------------------
# State dataclasses
# ---------------------------------------------------------------------------
@dataclass
class IsoVoltage:
    battery_V:          float = 0.0
    battery_status:     int   = 0
    link_plus_V:        float = 0.0
    link_plus_status:   int   = 0
    link_minus_V:       float = 0.0
    link_minus_status:  int   = 0
    pack_plus_V:        float = 0.0
    pack_plus_status:   int   = 0
    pack_minus_V:       float = 0.0
    pack_minus_status:  int   = 0
    prech_diff_V:       float = 0.0
    prech_diff_status:  int   = 0
    prech_V:            float = 0.0
    prech_status:       int   = 0


@dataclass
class IsoCurrent:
    current_A:      float = 0.0
    current_status: int   = 0


@dataclass
class IsoResistance:
    threshold_status:  int = 0
    safe_to_start:     int = 0
    res_status:        int = 0
    earth_lift_status: int = 0
    posneg_status:     int = 0
    packlink_status:   int = 0
    total_kohm:        int = 0
    pos_kohm:          int = 0
    neg_kohm:          int = 0
    pack_kohm:         int = 0
    link_kohm:         int = 0


@dataclass
class IsoTemperature:
    temp_C:  int = 0
    status:  int = 0


@dataclass
class MsgCounters:
    hvbattery:    int = 0
    voltagelink:  int = 0
    voltagepack:  int = 0
    prech:        int = 0
    isorestotal:  int = 0
    isoresposneg: int = 0
    isorespacklink: int = 0
    temperature:  int = 0

    hvbattery_started:     bool = False
    voltagelink_started:   bool = False
    voltagepack_started:   bool = False
    prech_started:         bool = False
    isorestotal_started:   bool = False
    isoresposneg_started:  bool = False
    isorespacklink_started: bool = False
    temperature_started:   bool = False


@dataclass
class IsolationSensorState:
    voltage:     IsoVoltage     = field(default_factory=IsoVoltage)
    current:     IsoCurrent     = field(default_factory=IsoCurrent)
    resistance:  IsoResistance  = field(default_factory=IsoResistance)
    temperature: IsoTemperature = field(default_factory=IsoTemperature)
    _counters:   MsgCounters    = field(default_factory=MsgCounters, repr=False)
    last_msg_id: int            = 0
    msg_count:   int            = 0
    seq_errors:  int            = 0


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------
def _convert_voltage(raw: int) -> float:
    return raw * VOLTAGE_RESOLUTION + VOLTAGE_OFFSET


def _convert_current(raw: int) -> float:
    return raw * CURRENT_RESOLUTION + CURRENT_OFFSET


def _check_counter(buf: bytes, prev: int, started: bool) -> tuple[bool, int, bool]:
    """Returns (valid, new_counter, new_started)."""
    curr = buf[1] & 0x0F
    if not started:
        return True, curr, True
    expected = (prev + 1) & 0x0F
    valid = (curr == expected)
    return valid, curr, True


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------
class IsolationSensorParser:
    def __init__(self) -> None:
        self.state = IsolationSensorState()

    def process(self, arbitration_id: int, data: bytes) -> bool:
        """Parse a CAN frame. Returns True if recognized."""
        if arbitration_id not in ALL_MSG_IDS:
            return False

        self.state.msg_count += 1
        self.state.last_msg_id = arbitration_id

        dispatch = {
            MSG_IVT_HVBATTERY:           self._hvbattery,
            MSG_IVT_VOLTAGELINK:         self._voltagelink,
            MSG_IVT_VOLTAGEPACK:         self._voltagepack,
            MSG_IVT_VOLTAGELINKPRCHDIFF: self._prech,
            MSG_IVT_ISORESTOTAL:         self._isorestotal,
            MSG_IVT_ISORESPOSNEG:        self._isoresposneg,
            MSG_IVT_ISORESPACKLINK:      self._isorespacklink,
            MSG_IVT_TEMPERATURE:         self._temperature,
        }
        dispatch[arbitration_id](data)
        return True

    # --- HV Battery (8 bytes) ---
    def _hvbattery(self, buf: bytes) -> None:
        if len(buf) != 8:
            return
        c = self.state._counters
        valid, c.hvbattery, c.hvbattery_started = _check_counter(
            buf, c.hvbattery, c.hvbattery_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        raw_i  = (buf[1] & 0xF0) >> 4
        raw_i |= buf[2] << 4
        raw_i |= buf[3] << 12
        raw_i |= (buf[4] & 0x0F) << 20

        self.state.current.current_A      = _convert_current(raw_i)
        self.state.current.current_status = (buf[4] & 0xF0) >> 4

        raw_v  = buf[5]
        raw_v |= buf[6] << 8
        raw_v |= (buf[7] & 0x0F) << 16

        self.state.voltage.battery_V      = _convert_voltage(raw_v)
        self.state.voltage.battery_status = (buf[7] & 0xF0) >> 4

    # --- Voltage Link (8 bytes) ---
    def _voltagelink(self, buf: bytes) -> None:
        if len(buf) != 8:
            return
        c = self.state._counters
        valid, c.voltagelink, c.voltagelink_started = _check_counter(
            buf, c.voltagelink, c.voltagelink_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        raw  = (buf[1] & 0xF0) >> 4
        raw |= buf[2] << 4
        raw |= buf[3] << 12
        self.state.voltage.link_plus_V      = _convert_voltage(raw)
        self.state.voltage.link_plus_status = buf[4] & 0x0F

        raw  = (buf[4] & 0xF0) >> 4
        raw |= buf[5] << 4
        raw |= buf[6] << 12
        self.state.voltage.link_minus_V      = _convert_voltage(raw)
        self.state.voltage.link_minus_status = buf[7] & 0x0F

    # --- Voltage Pack (8 bytes) ---
    def _voltagepack(self, buf: bytes) -> None:
        if len(buf) != 8:
            return
        c = self.state._counters
        valid, c.voltagepack, c.voltagepack_started = _check_counter(
            buf, c.voltagepack, c.voltagepack_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        raw  = (buf[1] & 0xF0) >> 4
        raw |= buf[2] << 4
        raw |= buf[3] << 12
        self.state.voltage.pack_plus_V      = _convert_voltage(raw)
        self.state.voltage.pack_plus_status = buf[4] & 0x0F

        raw  = (buf[4] & 0xF0) >> 4
        raw |= buf[5] << 4
        raw |= buf[6] << 12
        self.state.voltage.pack_minus_V      = _convert_voltage(raw)
        self.state.voltage.pack_minus_status = buf[7] & 0x0F

    # --- Voltage Link PreChg Diff (8 bytes) ---
    def _prech(self, buf: bytes) -> None:
        if len(buf) != 8:
            return
        c = self.state._counters
        valid, c.prech, c.prech_started = _check_counter(
            buf, c.prech, c.prech_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        raw  = (buf[1] & 0xF0) >> 4
        raw |= buf[2] << 4
        raw |= buf[3] << 12
        self.state.voltage.prech_diff_V      = _convert_voltage(raw)
        self.state.voltage.prech_diff_status = buf[4] & 0x0F

        raw  = (buf[4] & 0xF0) >> 4
        raw |= buf[5] << 4
        raw |= buf[6] << 12
        self.state.voltage.prech_V      = _convert_voltage(raw)
        self.state.voltage.prech_status = buf[7] & 0x0F

    # --- ISO Resistance Total (8 bytes) ---
    def _isorestotal(self, buf: bytes) -> None:
        if len(buf) != 8:
            return
        c = self.state._counters
        valid, c.isorestotal, c.isorestotal_started = _check_counter(
            buf, c.isorestotal, c.isorestotal_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        r = self.state.resistance
        r.threshold_status  = (buf[1] & 0x30) >> 4
        r.safe_to_start     = (buf[1] & 0xC0) >> 6
        r.res_status        =  buf[2] & 0x03
        r.earth_lift_status = (buf[2] & 0x04) >> 2

        raw16  = buf[3]
        raw16 |= buf[4] << 8
        r.total_kohm = raw16 // 5

    # --- ISO Resistance Pos/Neg (6 bytes) ---
    def _isoresposneg(self, buf: bytes) -> None:
        if len(buf) != 6:
            return
        c = self.state._counters
        valid, c.isoresposneg, c.isoresposneg_started = _check_counter(
            buf, c.isoresposneg, c.isoresposneg_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        self.state.resistance.posneg_status = (buf[1] & 0xF0) >> 4

        raw16  = buf[2]
        raw16 |= buf[3] << 8
        self.state.resistance.pos_kohm = raw16 // 2

        raw16  = buf[4]
        raw16 |= buf[5] << 8
        self.state.resistance.neg_kohm = raw16 // 2

    # --- ISO Resistance Pack/Link (6 bytes) ---
    def _isorespacklink(self, buf: bytes) -> None:
        if len(buf) != 6:
            return
        c = self.state._counters
        valid, c.isorespacklink, c.isorespacklink_started = _check_counter(
            buf, c.isorespacklink, c.isorespacklink_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        self.state.resistance.packlink_status = (buf[1] & 0xF0) >> 4

        raw16  = buf[2]
        raw16 |= buf[3] << 8
        self.state.resistance.pack_kohm = raw16 // 2

        raw16  = buf[4]
        raw16 |= buf[5] << 8
        self.state.resistance.link_kohm = raw16 // 2

    # --- Temperature (3 bytes) ---
    def _temperature(self, buf: bytes) -> None:
        if len(buf) != 3:
            return
        c = self.state._counters
        valid, c.temperature, c.temperature_started = _check_counter(
            buf, c.temperature, c.temperature_started
        )
        if not valid:
            self.state.seq_errors += 1
            return

        raw  = (buf[1] & 0xF0) >> 4
        raw |= (buf[2] & 0x0F) << 4
        self.state.temperature.temp_C  = raw - 50
        self.state.temperature.status  = (buf[2] & 0xF0) >> 4
