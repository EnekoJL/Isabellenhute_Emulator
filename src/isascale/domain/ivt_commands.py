"""IVT-S protocol, client side: command frames a BMS sends and the responses it reads back.

Pure functions, no I/O. The emulator side (results, responses it sends, parsing the
commands it receives) lives in ivt_protocol.py; this module is its mirror image and
reuses its constants. Reference: docs/datasheets/IVT-S_Datasheet_V1.03.pdf
  - 8.1 command 0x411 / response 0x511, 8 bytes, unused bytes = 0x00
  - 8.4 Config Result 0x2n (set) / 0x6n (get) -> response 0xAn
  - 8.5 Set commands 0x3n -> response 0xBn
  - 8.7 Get commands 0x7n -> response 0xBn; 0xFF = command not allowed / unknown
"""

from __future__ import annotations

from dataclasses import dataclass

from isascale.domain import ivt_protocol as proto
from isascale.domain.models import CANFrame, ChannelConfig, Mux, OperationMode, TriggerMode

COMMAND_DLC = 8

# Set Config Result (0x2n) and Get Config Result (0x6n) are answered with 0xAn (datasheet 8.4).
RESP_CONFIG_RESULT = 0xA0

# Reset Error- and Logdata DB1 (datasheet 8.5).
RESET_LOG_SINCE_RESET = 0x02
RESET_ALL_ITEMS = 0x00


@dataclass(frozen=True)
class Response:
    """Decoded IVT_Msg_Response: DB0 = response code, data = DB1..DB7."""

    code: int
    data: bytes

    def u16(self, db: int) -> int:
        return int.from_bytes(self.data[db - 1 : db + 1], "big")

    def u32(self, db: int) -> int:
        return int.from_bytes(self.data[db - 1 : db + 3], "big")


@dataclass(frozen=True)
class ChannelSetting:
    """Config Result of one channel as the sensor reports it (response 0xAn)."""

    mux: Mux
    config: ChannelConfig
    error_mask_reporting: bool  # flag bit 5, global for every channel (datasheet 8.4)


@dataclass(frozen=True)
class DeviceId:
    """Response DEVICE_ID 0xB9 (datasheet 8.7)."""

    nominal_current_a: int
    voltage_channels: int


# --- Commands -----------------------------------------------------------------


def _command(*db: int, command_id: int = proto.CMD_ID) -> CANFrame:
    return CANFrame(command_id, bytes(db).ljust(COMMAND_DLC, b"\x00"))


def set_mode_command(actual: OperationMode, startup: OperationMode = OperationMode.RUN) -> CANFrame:
    """SET_MODE 0x34: DB1 = mode now, DB2 = mode after the next start-up (needs STORE)."""
    return _command(proto.CMD_SET_MODE, int(actual), int(startup))


def set_config_command(mux: Mux, config: ChannelConfig, error_mask_reporting: bool) -> CANFrame:
    """Set Config Result 0x2n: DB1 = flags << 4 | trigger mode, DB2..3 = cycle time in ms."""
    db1 = (proto.config_flags(config, error_mask_reporting) << 4) | int(config.mode)
    return _command(proto.CMD_SET_CONFIG | int(mux), db1, *config.cycle_ms.to_bytes(2, "big"))


def get_config_command(mux: Mux) -> CANFrame:
    return _command(proto.CMD_GET_CONFIG | int(mux))


def store_command() -> CANFrame:
    """STORE 0x32: active settings -> non-volatile memory (STOP mode only, datasheet 8.5)."""
    return _command(proto.CMD_STORE)


def reset_log_since_reset_command(serial_number: int) -> CANFrame:
    """Reset Error- and Logdata 0x30, DB1 = 2 "Logdata since reset", DB2 = 0 all items,
    DB3..6 = serial number of the addressed sensor (datasheet 8.5)."""
    return _command(proto.CMD_RESET_ERRORS, RESET_LOG_SINCE_RESET, RESET_ALL_ITEMS, *serial_number.to_bytes(4, "big"))


def get_command(code: int) -> CANFrame:
    """Get command without arguments: 0x74 mode, 0x79 device id, 0x7A sw version, 0x7B serial."""
    return _command(code)


def expected_response_code(command_code: int) -> int:
    """Response code the sensor answers a command with (datasheet 8, mux table)."""
    group = command_code >> 4
    if group in (proto.CMD_SET_CONFIG >> 4, proto.CMD_GET_CONFIG >> 4):
        return RESP_CONFIG_RESULT | (command_code & 0x0F)
    return proto.response_code_for(command_code)


# --- Responses ----------------------------------------------------------------


def parse_response(frame: CANFrame, response_id: int = proto.RESPONSE_ID) -> Response | None:
    """Return the response if frame is a response message with data, else None (results, other nodes)."""
    if frame.arbitration_id != response_id or frame.dlc == 0:
        return None
    return Response(code=frame.data[0], data=frame.data[1:].ljust(COMMAND_DLC - 1, b"\x00"))


def is_error_for(response: Response, command_code: int) -> bool:
    """0xFF with DB1 = the received command code: the sensor refused that command."""
    return response.code == proto.RESP_ERROR and response.data[0] == command_code


def decode_config_result(response: Response) -> ChannelSetting:
    """Response 0xAn: [0xAn, flags << 4 | mode, cycle hi, cycle lo]."""
    if response.code & 0xF0 != RESP_CONFIG_RESULT or response.code & 0x0F > 0x7:
        raise ValueError(f"not a Config Result response: 0x{response.code:02X}")
    db1 = response.data[0]
    flags = db1 >> 4
    config = ChannelConfig(
        mode=TriggerMode(db1 & 0x0F),
        cycle_ms=response.u16(2),
        little_endian=bool(flags & proto.CONFIG_FLAG_LITTLE_ENDIAN),
        invert_sign=bool(flags & proto.CONFIG_FLAG_INVERT_SIGN),
    )
    return ChannelSetting(Mux(response.code & 0x0F), config, bool(flags & proto.CONFIG_FLAG_ERROR_MASK))


def decode_mode(response: Response) -> tuple[OperationMode, OperationMode]:
    """Response MODE 0xB4: (mode now, start-up mode)."""
    return OperationMode(response.data[0]), OperationMode(response.data[1])


def decode_store_ok(response: Response) -> bool:
    """Response STORE 0xB2: DB1 = 0x00 stored (datasheet 8.5)."""
    return response.data[0] == 0x00


def decode_serial_number(response: Response) -> int:
    """Response SERIAL_NUMBER 0xBB: DB1..4, big endian."""
    return response.u32(1)


def decode_sw_version(response: Response) -> tuple[int, ...]:
    """Response SW_VERSION 0xBA: major, minor, revision, YY, MM, DD."""
    return tuple(response.data[:6])


def decode_device_id(response: Response) -> DeviceId:
    """Response DEVICE_ID 0xB9: DB2 = I_nom // 16, DB3 = (I_nom % 16) << 4 | voltage channels."""
    return DeviceId(
        nominal_current_a=response.data[1] * 16 + (response.data[2] >> 4),
        voltage_channels=response.data[2] & 0x0F,
    )
