"""IVT-S CAN protocol encoders/decoders (Big Endian, default configuration).

Pure functions, no I/O. Reference: docs/datasheets/IVT-S_Datasheet_V1.03.pdf
  - 8.1 Messages overview (CAN ids, DLC)
  - 8.2 Result messages (MuxID, IVT_MsgCount, IVT_Result_state, signed long)
  - 8.5 / 8.7 Set/Get commands and their 0xBn responses
  - 9   Startup (alive message 0xBF)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from isascale.domain.models import (
    INT32_MAX,
    INT32_MIN,
    CANFrame,
    NominalRange,
    OperationMode,
    ResultState,
)

# --- CAN identifiers (datasheet 8.1, defaults) -------------------------------
CMD_ID = 0x411  # IVT_Msg_Command   (BMS/VCU -> sensor)
RESPONSE_ID = 0x511  # IVT_Msg_Response  (sensor -> BMS/VCU)
RESULT_I_ID = 0x521  # IVT_Msg_Result_I
RESULT_T_ID = 0x525  # IVT_Msg_Result_T
RESULT_AS_ID = 0x527  # IVT_Msg_Result_As

RESULT_DLC = 6
RESPONSE_DLC = 8

# --- MuxIDs of result messages (datasheet 8.2) --------------------------------
MUX_I = 0x00  # 1 mA
MUX_T = 0x04  # 0.1 degC
MUX_AS = 0x06  # 1 As

# --- Command codes, DB0 of 0x411 (datasheet 8.5 / 8.7) ------------------------
CMD_SET_MODE = 0x34
CMD_RESTART = 0x3F
CMD_GET_MODE = 0x74
CMD_GET_DEVICE_ID = 0x79
CMD_GET_SERIAL_NUMBER = 0x7B

# --- Response codes, DB0 of 0x511 ---------------------------------------------
RESP_MODE = 0xB4
RESP_DEVICE_ID = 0xB9
RESP_SERIAL_NUMBER = 0xBB
RESP_ALIVE = 0xBF  # alive message after start-up (datasheet 9)
RESP_ERROR = 0xFF  # not allowed / unknown command

# --- DEVICE_ID response fields (datasheet 8.7, Response "DEVICE_ID") ----------
DEVICE_TYPE_IVT_S = 0x02
FEATURE_ISOLATION = 0x03  # DB4 "I" variant as listed in the datasheet table
COMM_CAN1_TERMINATED = 0x01
SUPPLY_12_24V = 0x01


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
    """Decoded IVT_Msg_Command (0x411)."""

    code: int
    payload: bytes  # DB1..DB7


# --- Result messages ---------------------------------------------------------


def encode_result(mux_id: int, value: int, counter: int, state: ResultState = ResultState.NONE) -> bytes:
    """Build the 6-byte result payload: [mux, state<<4 | counter, int32 BE]."""
    if not 0 <= mux_id <= 0x07:
        raise ValueError(f"result MuxID must be 0x00..0x07, got 0x{mux_id:X}")
    if not 0 <= counter <= 0xF:
        raise ValueError(f"counter must be 0..15, got {counter}")
    state_bits = int(state)
    if not 0 <= state_bits <= 0xF:
        raise ValueError(f"state must be 4 bits, got {state_bits}")
    if not INT32_MIN <= value <= INT32_MAX:
        raise ValueError(f"value {value} does not fit in signed int32")
    return bytes([mux_id, (state_bits << 4) | counter]) + struct.pack(">i", value)


def decode_result(data: bytes) -> ResultMessage:
    if len(data) != RESULT_DLC:
        raise ValueError(f"result message must be {RESULT_DLC} bytes, got {len(data)}")
    (value,) = struct.unpack(">i", data[2:6])
    return ResultMessage(
        mux_id=data[0],
        counter=data[1] & 0x0F,
        state=ResultState(data[1] >> 4),
        value=value,
    )


def current_frame(current_ma: int, counter: int, state: ResultState = ResultState.NONE) -> CANFrame:
    return CANFrame(RESULT_I_ID, encode_result(MUX_I, int(current_ma), counter, state))


def temperature_frame(temperature_c: float, counter: int, state: ResultState = ResultState.NONE) -> CANFrame:
    return CANFrame(RESULT_T_ID, encode_result(MUX_T, int(round(temperature_c * 10)), counter, state))


def charge_frame(charge_as: int, counter: int, state: ResultState = ResultState.NONE) -> CANFrame:
    return CANFrame(RESULT_AS_ID, encode_result(MUX_AS, int(charge_as), counter, state))


# --- Response messages (0x511, 8 bytes, unused bytes = 0x00) -----------------


def _response(db: list[int]) -> CANFrame:
    return CANFrame(RESPONSE_ID, bytes(db + [0x00] * (RESPONSE_DLC - len(db))))


def alive_frame(serial_number: int, command_can_id: int = CMD_ID) -> CANFrame:
    """Alive message after start-up: [0xBF, cmd_id_hi, cmd_id_lo, serial BE32, 0x00]."""
    return _response([RESP_ALIVE, *command_can_id.to_bytes(2, "big"), *serial_number.to_bytes(4, "big")])


def device_id_frame(
    nominal_range: NominalRange,
    voltage_channels: int = 0,
    feature: int = FEATURE_ISOLATION,
    communication: int = COMM_CAN1_TERMINATED,
    supply: int = SUPPLY_12_24V,
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
        ]
    )


def serial_number_frame(serial_number: int) -> CANFrame:
    return _response([RESP_SERIAL_NUMBER, *serial_number.to_bytes(4, "big")])


def mode_frame(actual: OperationMode, startup: OperationMode = OperationMode.RUN) -> CANFrame:
    return _response([RESP_MODE, int(actual), int(startup), 0x00, 0x00])


def error_frame(invalid_mux: int) -> CANFrame:
    return _response([RESP_ERROR, invalid_mux & 0xFF])


# --- Commands -----------------------------------------------------------------


def parse_command(frame: CANFrame) -> Command | None:
    """Return the command if frame is an IVT_Msg_Command with data, else None."""
    if frame.arbitration_id != CMD_ID or frame.dlc == 0:
        return None
    return Command(code=frame.data[0], payload=frame.data[1:])
