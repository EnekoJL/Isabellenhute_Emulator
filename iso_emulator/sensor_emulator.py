"""
Isolation sensor emulator — transmits simulated IVT CAN messages via PCAN.
Mirrors isolation_sensor.c message structure and encoding.
"""

from dataclasses import dataclass, field
from enum import IntEnum
import random
import math


# Message IDs (must match isolation_sensor.c)
MSG_IVT_HVBATTERY           = 0x1000
MSG_IVT_VOLTAGELINK         = 0x1010
MSG_IVT_VOLTAGEPACK         = 0x1020
MSG_IVT_VOLTAGELINKPRCHDIFF = 0x1030
MSG_IVT_ISORESTOTAL         = 0x1040
MSG_IVT_ISORESPOSNEG        = 0x1050
MSG_IVT_ISORESPACKLINK      = 0x1060
MSG_IVT_TEMPERATURE         = 0x1070

# Conversion constants (must match isolation_sensor.c)
CURRENT_OFFSET     = -16777.216
CURRENT_RESOLUTION = 0.002
VOLTAGE_OFFSET     = -2097.152
VOLTAGE_RESOLUTION = 0.004


class CurrentStatus(IntEnum):
    VALID         = 0x00
    INIT          = 0x01
    OC_L1         = 0x02
    OC_L2         = 0x03
    NOT_AVAILABLE = 0x0E
    ERROR         = 0x0F


class VoltageStatus(IntEnum):
    VALID         = 0x00
    INIT          = 0x01
    OV_L1         = 0x02
    NOT_AVAILABLE = 0x0E
    ERROR         = 0x0F


class ResThreshold(IntEnum):
    VALID = 0x00
    WARN  = 0x01
    ERR   = 0x02
    NE    = 0x03


class SafeToStart(IntEnum):
    NOT_EXECUTED = 0x00
    RUNNING      = 0x01
    NOT_SAFE     = 0x02
    SAFE         = 0x03


class ResStatus(IntEnum):
    VALID    = 0x00
    INIT     = 0x01
    STARTUP  = 0x02
    DISABLED = 0x03


class TempStatus(IntEnum):
    VALID         = 0x00
    INIT          = 0x01
    OT            = 0x02
    UT            = 0x03
    NOT_AVAILABLE = 0x0E
    ERROR         = 0x0F


@dataclass
class SensorReadings:
    """Simulated sensor values."""
    # Voltages (V)
    battery_V:      float = 400.0
    link_plus_V:    float = 200.0
    link_minus_V:   float = -200.0
    pack_plus_V:    float = 200.0
    pack_minus_V:   float = -200.0
    prech_diff_V:   float = 0.5
    prech_V:        float = 400.0

    # Current (A)
    current_A:      float = 0.0

    # Resistance (kohm)
    iso_total_kohm: int = 1000
    iso_pos_kohm:   int = 2000
    iso_neg_kohm:   int = 2000
    iso_pack_kohm:  int = 5000
    iso_link_kohm:  int = 5000

    # Temperature (C)
    temp_C:         int = 25

    # Status flags
    voltage_status:     VoltageStatus    = VoltageStatus.VALID
    current_status:     CurrentStatus    = CurrentStatus.VALID
    res_threshold:      ResThreshold     = ResThreshold.VALID
    safe_to_start:      SafeToStart      = SafeToStart.SAFE
    res_status:         ResStatus        = ResStatus.VALID
    temp_status:        TempStatus       = TempStatus.VALID
    earth_lift_open:    bool             = False
    connection_state:   int              = 1  # Connected


@dataclass
class MessageCounters:
    """Message sequence counters (4-bit, wrap at 16)."""
    hvbattery:      int = 0
    voltagelink:    int = 0
    voltagepack:    int = 0
    prech:          int = 0
    isorestotal:    int = 0
    isoresposneg:   int = 0
    isorespacklink: int = 0
    temperature:    int = 0

    def increment(self, msg_id: int) -> int:
        """Increment and return counter for a message type."""
        if msg_id == MSG_IVT_HVBATTERY:
            self.hvbattery = (self.hvbattery + 1) & 0x0F
            return self.hvbattery
        elif msg_id == MSG_IVT_VOLTAGELINK:
            self.voltagelink = (self.voltagelink + 1) & 0x0F
            return self.voltagelink
        elif msg_id == MSG_IVT_VOLTAGEPACK:
            self.voltagepack = (self.voltagepack + 1) & 0x0F
            return self.voltagepack
        elif msg_id == MSG_IVT_VOLTAGELINKPRCHDIFF:
            self.prech = (self.prech + 1) & 0x0F
            return self.prech
        elif msg_id == MSG_IVT_ISORESTOTAL:
            self.isorestotal = (self.isorestotal + 1) & 0x0F
            return self.isorestotal
        elif msg_id == MSG_IVT_ISORESPOSNEG:
            self.isoresposneg = (self.isoresposneg + 1) & 0x0F
            return self.isoresposneg
        elif msg_id == MSG_IVT_ISORESPACKLINK:
            self.isorespacklink = (self.isorespacklink + 1) & 0x0F
            return self.isorespacklink
        elif msg_id == MSG_IVT_TEMPERATURE:
            self.temperature = (self.temperature + 1) & 0x0F
            return self.temperature
        return 0


class IsolationSensorEmulator:
    """Emulates isolation sensor by generating CAN messages."""

    def __init__(self, readings: SensorReadings | None = None):
        self.readings = readings or SensorReadings()
        self.counters = MessageCounters()
        self.noise_enabled = True
        self.noise_scale = 0.02  # 2% noise

    def _raw_from_voltage(self, voltage_V: float) -> int:
        """Convert voltage (V) to raw 20-bit value."""
        raw = (voltage_V - VOLTAGE_OFFSET) / VOLTAGE_RESOLUTION
        return max(0, min(0xFFFFF, int(raw)))

    def _raw_from_current(self, current_A: float) -> int:
        """Convert current (A) to raw 24-bit value."""
        raw = (current_A - CURRENT_OFFSET) / CURRENT_RESOLUTION
        return max(0, min(0xFFFFFF, int(raw)))

    def _apply_noise(self, value: float, scale: float = None) -> float:
        """Add Gaussian noise to a value."""
        if not self.noise_enabled:
            return value
        scale = scale or self.noise_scale
        noise = random.gauss(0, abs(value) * scale)
        return value + noise

    def make_hvbattery(self) -> tuple[int, bytes]:
        """Create HV Battery message (8 bytes)."""
        counter = self.counters.increment(MSG_IVT_HVBATTERY)
        current = self._apply_noise(self.readings.current_A)
        raw_i = self._raw_from_current(current)
        raw_v = self._raw_from_voltage(self._apply_noise(self.readings.battery_V))

        buf = bytearray(8)
        buf[0] = 0
        buf[1] = counter | ((raw_i & 0x00F) << 4)
        buf[2] = (raw_i >> 4) & 0xFF
        buf[3] = (raw_i >> 12) & 0xFF
        buf[4] = (raw_i >> 20) & 0x0F | (self.readings.current_status << 4)
        buf[5] = raw_v & 0xFF
        buf[6] = (raw_v >> 8) & 0xFF
        buf[7] = (raw_v >> 16) & 0x0F | (self.readings.voltage_status << 4)

        return MSG_IVT_HVBATTERY, bytes(buf)

    def make_voltagelink(self) -> tuple[int, bytes]:
        """Create Voltage Link message (8 bytes)."""
        counter = self.counters.increment(MSG_IVT_VOLTAGELINK)
        raw_plus = self._raw_from_voltage(self._apply_noise(self.readings.link_plus_V))
        raw_minus = self._raw_from_voltage(self._apply_noise(self.readings.link_minus_V))

        buf = bytearray(8)
        buf[0] = 0
        buf[1] = counter | ((raw_plus & 0x00F) << 4)
        buf[2] = (raw_plus >> 4) & 0xFF
        buf[3] = (raw_plus >> 12) & 0x0F
        buf[4] = (self.readings.voltage_status & 0x0F) | ((raw_minus & 0x00F) << 4)
        buf[5] = (raw_minus >> 4) & 0xFF
        buf[6] = (raw_minus >> 12) & 0x0F
        buf[7] = self.readings.voltage_status & 0x0F

        return MSG_IVT_VOLTAGELINK, bytes(buf)

    def make_voltagepack(self) -> tuple[int, bytes]:
        """Create Voltage Pack message (8 bytes)."""
        counter = self.counters.increment(MSG_IVT_VOLTAGEPACK)
        raw_plus = self._raw_from_voltage(self._apply_noise(self.readings.pack_plus_V))
        raw_minus = self._raw_from_voltage(self._apply_noise(self.readings.pack_minus_V))

        buf = bytearray(8)
        buf[0] = 0
        buf[1] = counter | ((raw_plus & 0x00F) << 4)
        buf[2] = (raw_plus >> 4) & 0xFF
        buf[3] = (raw_plus >> 12) & 0x0F
        buf[4] = (self.readings.voltage_status & 0x0F) | ((raw_minus & 0x00F) << 4)
        buf[5] = (raw_minus >> 4) & 0xFF
        buf[6] = (raw_minus >> 12) & 0x0F
        buf[7] = self.readings.voltage_status & 0x0F

        return MSG_IVT_VOLTAGEPACK, bytes(buf)

    def make_prech(self) -> tuple[int, bytes]:
        """Create Voltage Link PreChg Diff message (8 bytes)."""
        counter = self.counters.increment(MSG_IVT_VOLTAGELINKPRCHDIFF)
        raw_diff = self._raw_from_voltage(self._apply_noise(self.readings.prech_diff_V))
        raw_prech = self._raw_from_voltage(self._apply_noise(self.readings.prech_V))

        buf = bytearray(8)
        buf[0] = 0
        buf[1] = counter | ((raw_diff & 0x00F) << 4)
        buf[2] = (raw_diff >> 4) & 0xFF
        buf[3] = (raw_diff >> 12) & 0x0F
        buf[4] = (self.readings.voltage_status & 0x0F) | ((raw_prech & 0x00F) << 4)
        buf[5] = (raw_prech >> 4) & 0xFF
        buf[6] = (raw_prech >> 12) & 0x0F
        buf[7] = self.readings.voltage_status & 0x0F

        return MSG_IVT_VOLTAGELINKPRCHDIFF, bytes(buf)

    def make_isorestotal(self) -> tuple[int, bytes]:
        """Create ISO Resistance Total message (8 bytes)."""
        counter = self.counters.increment(MSG_IVT_ISORESTOTAL)
        raw_res = self.readings.iso_total_kohm * 5

        buf = bytearray(8)
        buf[0] = 0
        buf[1] = counter | ((self.readings.res_threshold & 0x03) << 4) | ((self.readings.safe_to_start & 0x03) << 6)
        buf[2] = (self.readings.res_status & 0x03) | ((int(self.readings.earth_lift_open) & 0x01) << 2)
        buf[3] = raw_res & 0xFF
        buf[4] = (raw_res >> 8) & 0xFF
        buf[5] = 0
        buf[6] = 0
        buf[7] = 0

        return MSG_IVT_ISORESTOTAL, bytes(buf)

    def make_isoresposneg(self) -> tuple[int, bytes]:
        """Create ISO Resistance Pos/Neg message (6 bytes)."""
        counter = self.counters.increment(MSG_IVT_ISORESPOSNEG)
        raw_pos = self.readings.iso_pos_kohm * 2
        raw_neg = self.readings.iso_neg_kohm * 2

        buf = bytearray(6)
        buf[0] = 0
        buf[1] = counter | ((0 & 0x0F) << 4)  # posneg_status in upper nibble
        buf[2] = raw_pos & 0xFF
        buf[3] = (raw_pos >> 8) & 0xFF
        buf[4] = raw_neg & 0xFF
        buf[5] = (raw_neg >> 8) & 0xFF

        return MSG_IVT_ISORESPOSNEG, bytes(buf)

    def make_isorespacklink(self) -> tuple[int, bytes]:
        """Create ISO Resistance Pack/Link message (6 bytes)."""
        counter = self.counters.increment(MSG_IVT_ISORESPACKLINK)
        raw_pack = self.readings.iso_pack_kohm * 2
        raw_link = self.readings.iso_link_kohm * 2

        buf = bytearray(6)
        buf[0] = 0
        buf[1] = counter | ((0 & 0x0F) << 4)  # packlink_status in upper nibble
        buf[2] = raw_pack & 0xFF
        buf[3] = (raw_pack >> 8) & 0xFF
        buf[4] = raw_link & 0xFF
        buf[5] = (raw_link >> 8) & 0xFF

        return MSG_IVT_ISORESPACKLINK, bytes(buf)

    def make_temperature(self) -> tuple[int, bytes]:
        """Create Temperature message (3 bytes)."""
        counter = self.counters.increment(MSG_IVT_TEMPERATURE)
        temp_raw = (self.readings.temp_C + 50) & 0x0FF

        buf = bytearray(3)
        buf[0] = 0
        buf[1] = counter | ((temp_raw & 0x0F) << 4)
        buf[2] = ((temp_raw & 0x0F0) >> 4) | (self.readings.temp_status << 4)

        return MSG_IVT_TEMPERATURE, bytes(buf)

    def make_all_messages(self) -> list[tuple[int, bytes]]:
        """Generate all messages in sequence."""
        return [
            self.make_hvbattery(),
            self.make_voltagelink(),
            self.make_voltagepack(),
            self.make_prech(),
            self.make_isorestotal(),
            self.make_isoresposneg(),
            self.make_isorespacklink(),
            self.make_temperature(),
        ]
