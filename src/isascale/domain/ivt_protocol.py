"""IVT-S CAN protocol encoders/decoders.

Pure functions, no I/O. Reference: docs/datasheets/IVT-S_Datasheet_V1.03.pdf
  - 8.1 Messages overview (CAN ids, DLC, unused bytes = 0x00)
  - 8.2 Result messages (MuxID, IVT_MsgCount, IVT_Result_state, signed long)
  - 8.3 Set CAN ID, 8.4 Config Result (endianness, sign)
  - 8.5 Set commands, 8.6 Get error/log data, 8.7 Get commands and 0xBn responses
  - 9   Startup (alive message 0xBF)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from isascale.domain.models import (
    DEFAULT_COMMAND_ID,
    DEFAULT_RESPONSE_ID,
    DEFAULT_RESULT_IDS,
    INT32_MAX,
    INT32_MIN,
    Bitrate,
    CANFrame,
    ChannelConfig,
    Mux,
    NominalRange,
    OcThresholds,
    OperationMode,
    ResultState,
    TriggerMode,
)

# --- CAN identifiers (datasheet 8.1, defaults) -------------------------------
CMD_ID = DEFAULT_COMMAND_ID  # IVT_Msg_Command   (BMS/VCU -> sensor)
RESPONSE_ID = DEFAULT_RESPONSE_ID  # IVT_Msg_Response  (sensor -> BMS/VCU)
RESULT_I_ID = DEFAULT_RESULT_IDS[Mux.I]  # IVT_Msg_Result_I
RESULT_T_ID = DEFAULT_RESULT_IDS[Mux.T]  # IVT_Msg_Result_T
RESULT_AS_ID = DEFAULT_RESULT_IDS[Mux.AS]  # IVT_Msg_Result_As

RESULT_DLC = 6
RESPONSE_DLC = 8

# --- MuxIDs of result messages (datasheet 8.2) --------------------------------
MUX_I = int(Mux.I)  # 1 mA
MUX_T = int(Mux.T)  # 0.1 degC
MUX_AS = int(Mux.AS)  # 1 As

# --- Command codes, DB0 of the command message (datasheet 8.3 .. 8.7) ---------
CMD_SET_CAN_ID = 0x10  # 0x1n, n = Mux, 0xD = command, 0xF = response
CMD_SET_CONFIG = 0x20  # 0x2n
CMD_RESET_ERRORS = 0x30
CMD_TRIGGER = 0x31
CMD_STORE = 0x32
CMD_START_OC_TEST = 0x33
CMD_SET_MODE = 0x34
CMD_SET_THRESHOLD_POS = 0x35
CMD_SET_THRESHOLD_NEG = 0x36
CMD_RESTART_TO_BITRATE = 0x3A
CMD_RESTART_TO_DEFAULT = 0x3D
CMD_RESTART = 0x3F
CMD_GET_MEASUREMENT_ERRORS = 0x40
CMD_GET_SYSTEM_ERRORS = 0x41
CMD_GET_LOG_OVERALL = 0x42
CMD_GET_LOG_SINCE_RESET = 0x43
CMD_GET_CAN_ID = 0x50  # 0x5n
CMD_GET_CONFIG = 0x60  # 0x6n
CMD_GET_OC_TESTTIME = 0x73
CMD_GET_MODE = 0x74
CMD_GET_THRESHOLD_POS = 0x75
CMD_GET_THRESHOLD_NEG = 0x76
CMD_GET_DEVICE_ID = 0x79
CMD_GET_SW_VERSION = 0x7A
CMD_GET_SERIAL_NUMBER = 0x7B
CMD_GET_ARTICLE_NUMBER = 0x7C

# Set/Get CAN ID low nibble for the command and response messages.
CAN_ID_INDEX_COMMAND = 0xD
CAN_ID_INDEX_RESPONSE = 0xF

# --- Response codes, DB0 of the response message --------------------------------
RESP_LOG_RESET = 0xB0
RESP_TRIGGER = 0xB1
RESP_STORE = 0xB2
RESP_OC_TEST = 0xB3
RESP_MODE = 0xB4
RESP_THRESHOLD_POS = 0xB5
RESP_THRESHOLD_NEG = 0xB6
RESP_DEVICE_ID = 0xB9
RESP_SW_VERSION = 0xBA
RESP_SERIAL_NUMBER = 0xBB
RESP_ARTICLE_NUMBER = 0xBC
RESP_ALIVE = 0xBF  # alive message after start-up (datasheet 9)
RESP_ERROR = 0xFF  # not allowed / unknown command

# Config Result DB1 high nibble flags (datasheet 8.4).
CONFIG_FLAG_ERROR_MASK = 0x2  # bit 5
CONFIG_FLAG_LITTLE_ENDIAN = 0x4  # bit 6
CONFIG_FLAG_INVERT_SIGN = 0x8  # bit 7

# RESTART_to_Bitrate DB1: CAN prescaler (datasheet 8.5).
PRESCALER_TO_BITRATE = {0x08: Bitrate.B250K, 0x04: Bitrate.B500K, 0x02: Bitrate.B1M}

# --- DEVICE_ID response fields (datasheet 8.7, Response "DEVICE_ID") ----------
DEVICE_TYPE_IVT_S = 0x02
FEATURE_ISOLATION = 0x03  # DB4 "I" variant as listed in the datasheet table
COMM_CAN1_TERMINATED = 0x01
SUPPLY_12_24V = 0x01

# Placeholders: the real values depend on the sensor unit (read them from it).
SW_VERSION = (1, 0, 0, 22, 6, 9)  # major, minor, rev, YY, MM, DD
ARTICLE_NUMBER = 0

LOG_VALUE_BYTES = 6


def response_code_for(command: int) -> int:
    """Set/Get commands 0x3n and 0x7n are answered with 0xBn (datasheet 8, mux table)."""
    return 0xB0 | (command & 0x0F)


@dataclass(frozen=True)
class ResultMessage:
    """Decoded IVT_Msg_Result_* payload."""

    mux_id: int
    counter: int
    state: ResultState
    value: int


@dataclass(frozen=True)
class Command:
    """Decoded command message."""

    code: int
    payload: bytes  # DB1..DB7, padded with 0x00 to 7 bytes

    def byte(self, db: int) -> int:
        """Data byte DBn (n >= 1) of the command."""
        return self.payload[db - 1]

    def u16(self, db: int) -> int:
        return (self.byte(db) << 8) | self.byte(db + 1)

    def i16(self, db: int) -> int:
        value = self.u16(db)
        return value - 0x10000 if value & 0x8000 else value

    def u32(self, db: int) -> int:
        return int.from_bytes(self.payload[db - 1 : db + 3], "big")


# --- Result messages ---------------------------------------------------------


def encode_result(
    mux_id: int,
    value: int,
    counter: int,
    state: ResultState = ResultState.NONE,
    little_endian: bool = False,
) -> bytes:
    """Build the 6-byte result payload: [mux, state<<4 | counter, int32]."""
    if not 0 <= mux_id <= 0x07:
        raise ValueError(f"result MuxID must be 0x00..0x07, got 0x{mux_id:X}")
    if not 0 <= counter <= 0xF:
        raise ValueError(f"counter must be 0..15, got {counter}")
    state_bits = int(state)
    if not 0 <= state_bits <= 0xF:
        raise ValueError(f"state must be 4 bits, got {state_bits}")
    if not INT32_MIN <= value <= INT32_MAX:
        raise ValueError(f"value {value} does not fit in signed int32")
    return bytes([mux_id, (state_bits << 4) | counter]) + struct.pack("<i" if little_endian else ">i", value)


def decode_result(data: bytes, little_endian: bool = False) -> ResultMessage:
    if len(data) != RESULT_DLC:
        raise ValueError(f"result message must be {RESULT_DLC} bytes, got {len(data)}")
    (value,) = struct.unpack("<i" if little_endian else ">i", data[2:6])
    return ResultMessage(
        mux_id=data[0],
        counter=data[1] & 0x0F,
        state=ResultState(data[1] >> 4),
        value=value,
    )


def result_frame(
    can_id: int, mux: Mux, value: int, counter: int, state: ResultState, config: ChannelConfig
) -> CANFrame:
    """Result message with the channel's sign and endianness flags applied (datasheet 8.4)."""
    if config.invert_sign:
        value = max(INT32_MIN, min(INT32_MAX, -value))
    return CANFrame(can_id, encode_result(int(mux), value, counter, state, config.little_endian))


def current_frame(current_ma: int, counter: int, state: ResultState = ResultState.NONE) -> CANFrame:
    return CANFrame(RESULT_I_ID, encode_result(MUX_I, int(current_ma), counter, state))


def temperature_frame(temperature_c: float, counter: int, state: ResultState = ResultState.NONE) -> CANFrame:
    return CANFrame(RESULT_T_ID, encode_result(MUX_T, int(round(temperature_c * 10)), counter, state))


def charge_frame(charge_as: int, counter: int, state: ResultState = ResultState.NONE) -> CANFrame:
    return CANFrame(RESULT_AS_ID, encode_result(MUX_AS, int(charge_as), counter, state))


# --- Response messages (8 bytes, unused bytes = 0x00) -------------------------


def _response(db: list[int], response_id: int = RESPONSE_ID) -> CANFrame:
    return CANFrame(response_id, bytes(db + [0x00] * (RESPONSE_DLC - len(db))))


def _u16(value: int) -> list[int]:
    return list((value & 0xFFFF).to_bytes(2, "big"))


def _u32(value: int) -> list[int]:
    return list(value.to_bytes(4, "big"))


def alive_frame(serial_number: int, command_can_id: int = CMD_ID, response_id: int = RESPONSE_ID) -> CANFrame:
    """Alive message after start-up: [0xBF, cmd_id_hi, cmd_id_lo, serial BE32, 0x00]."""
    return _response([RESP_ALIVE, *_u16(command_can_id), *_u32(serial_number)], response_id)


def device_id_frame(
    nominal_range: NominalRange,
    voltage_channels: int = 0,
    feature: int = FEATURE_ISOLATION,
    communication: int = COMM_CAN1_TERMINATED,
    supply: int = SUPPLY_12_24V,
    response_id: int = RESPONSE_ID,
) -> CANFrame:
    """Response DEVICE_ID: DB2 = I_nom // 16, DB3 = (I_nom % 16) << 4 | voltage channels."""
    if voltage_channels not in (0, 3):
        raise ValueError("IVT-S has 0 (U0) or 3 (U3) voltage channels")
    i_nom = int(nominal_range)
    return _response(
        [
            RESP_DEVICE_ID,
            DEVICE_TYPE_IVT_S,
            i_nom // 16,
            ((i_nom % 16) << 4) | voltage_channels,
            feature,
            communication,
            supply,
        ],
        response_id,
    )


def serial_number_frame(serial_number: int, response_id: int = RESPONSE_ID) -> CANFrame:
    return _response([RESP_SERIAL_NUMBER, *_u32(serial_number)], response_id)


def sw_version_frame(version: tuple[int, ...] = SW_VERSION, response_id: int = RESPONSE_ID) -> CANFrame:
    """Response SW_VERSION: major, minor, revision, YY, MM, DD, internal (0)."""
    return _response([RESP_SW_VERSION, *version], response_id)


def article_number_frame(article_number: int = ARTICLE_NUMBER, response_id: int = RESPONSE_ID) -> CANFrame:
    return _response([RESP_ARTICLE_NUMBER, *article_number.to_bytes(7, "big")], response_id)


def mode_frame(
    actual: OperationMode, startup: OperationMode = OperationMode.RUN, response_id: int = RESPONSE_ID
) -> CANFrame:
    return _response([RESP_MODE, int(actual), int(startup), 0x00, 0x00], response_id)


def can_id_frame(index: int, can_id: int, serial_number: int, response_id: int = RESPONSE_ID) -> CANFrame:
    """Response CAN_ID 0x9n: [0x9n, id hi, id lo, serial BE32]."""
    return _response([0x90 | index, *_u16(can_id), *_u32(serial_number)], response_id)


def config_flags(config: ChannelConfig, error_mask_reporting: bool) -> int:
    flags = CONFIG_FLAG_ERROR_MASK if error_mask_reporting else 0
    if config.little_endian:
        flags |= CONFIG_FLAG_LITTLE_ENDIAN
    if config.invert_sign:
        flags |= CONFIG_FLAG_INVERT_SIGN
    return flags


def config_result_frame(
    mux: Mux, config: ChannelConfig, error_mask_reporting: bool = False, response_id: int = RESPONSE_ID
) -> CANFrame:
    """Response CONFIG Result 0xAn: [0xAn, flags<<4 | mode, cycle hi, cycle lo]."""
    db1 = (config_flags(config, error_mask_reporting) << 4) | int(config.mode)
    return _response([0xA0 | int(mux), db1, *_u16(config.cycle_ms)], response_id)


def threshold_frame(code: int, thresholds: OcThresholds, response_id: int = RESPONSE_ID) -> CANFrame:
    """Response THRESHOLD_POS (0xB5) / THRESHOLD_NEG (0xB6): set, reset as int16 in A."""
    return _response([code, *_u16(thresholds.set_a), *_u16(thresholds.reset_a)], response_id)


def oc_test_frame(remaining_ms: int, response_id: int = RESPONSE_ID) -> CANFrame:
    return _response([RESP_OC_TEST, *_u16(max(0, min(0xFFFF, remaining_ms)))], response_id)


def trigger_frame(channel_bits: int, response_id: int = RESPONSE_ID) -> CANFrame:
    return _response([RESP_TRIGGER, *_u16(channel_bits & 0x00FF)], response_id)


def store_frame(ok: bool, serial_number: int, response_id: int = RESPONSE_ID) -> CANFrame:
    return _response([RESP_STORE, 0x00 if ok else 0x01, *_u32(serial_number)], response_id)


def log_reset_frame(kind: int, item: int, serial_number: int, response_id: int = RESPONSE_ID) -> CANFrame:
    return _response([RESP_LOG_RESET, kind, item, *_u32(serial_number)], response_id)


def error_bitmask_frame(code: int, db2: int, db3: int, response_id: int = RESPONSE_ID) -> CANFrame:
    """Response 0x80 / 0x81 with DB1 = 0x00: bitmask of counters != 0."""
    return _response([code, 0x00, db2, db3], response_id)


def error_counter_frame(code: int, index: int, count: int, response_id: int = RESPONSE_ID) -> CANFrame:
    """Response 0x80 / 0x81 with DB1 = counter number: DB2 = number of errors."""
    return _response([code, index, min(0xFF, count)], response_id)


def log_data_frame(code: int, item: int, value: int, response_id: int = RESPONSE_ID) -> CANFrame:
    """Response 0x82 / 0x83: DB2..DB7 = signed 48-bit value, highest byte first."""
    limit = 1 << (8 * LOG_VALUE_BYTES - 1)
    value = max(-limit, min(limit - 1, value))
    return _response([code, item, *value.to_bytes(LOG_VALUE_BYTES, "big", signed=True)], response_id)


def error_frame(invalid_mux: int, response_id: int = RESPONSE_ID) -> CANFrame:
    return _response([RESP_ERROR, invalid_mux & 0xFF], response_id)


# --- Commands -----------------------------------------------------------------


def parse_command(frame: CANFrame, command_id: int = CMD_ID) -> Command | None:
    """Return the command if frame is a command message with data, else None."""
    if frame.arbitration_id != command_id or frame.dlc == 0:
        return None
    return Command(code=frame.data[0], payload=frame.data[1:].ljust(RESPONSE_DLC - 1, b"\x00"))


def parse_channel_config(command: Command, current: ChannelConfig) -> tuple[ChannelConfig, bool] | None:
    """Set Config Result 0x2n -> (new channel config, error-mask flag), or None if invalid.

    A cycle time of 0x0000 is ignored (keeps the current one).
    """
    mode_bits, flags = command.byte(1) & 0x0F, command.byte(1) >> 4
    try:
        mode = TriggerMode(mode_bits)
    except ValueError:
        return None
    cycle_ms = command.u16(2) or current.cycle_ms
    config = ChannelConfig(
        mode=mode,
        cycle_ms=cycle_ms,
        little_endian=bool(flags & CONFIG_FLAG_LITTLE_ENDIAN),
        invert_sign=bool(flags & CONFIG_FLAG_INVERT_SIGN),
    )
    return config, bool(flags & CONFIG_FLAG_ERROR_MASK)
