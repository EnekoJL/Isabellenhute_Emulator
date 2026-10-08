"""IVT-S protocol encoders/decoders vs datasheet V1.03 chapter 8 / 9."""

from __future__ import annotations

import pytest

from isascale.domain import ivt_protocol as proto
from isascale.domain.models import INT32_MAX, INT32_MIN, CANFrame, NominalRange, OperationMode, ResultState

# ----------------------------------------------------------------- 0x521 current


@pytest.mark.parametrize("counter", range(16))
def test_current_35000ma_encodes_exact_bytes_with_counter_in_low_nibble(counter):
    frame = proto.current_frame(35000, counter)

    assert frame.arbitration_id == 0x521
    assert frame.dlc == 6
    assert list(frame.data) == [0x00, counter, 0x00, 0x00, 0x88, 0xB8]
    assert frame.data[1] & 0x0F == counter
    assert frame.data[1] >> 4 == 0


def test_datasheet_example_u1_35000mv_counter_5():
    # Datasheet 8.2 example (Big Endian): 0x01 0x05 0x00 0x00 0x88 0xb8 = U1, msg #5, 35000 mV.
    assert proto.encode_result(0x01, 35000, 5) == bytes([0x01, 0x05, 0x00, 0x00, 0x88, 0xB8])
    decoded = proto.decode_result(bytes([0x01, 0x05, 0x00, 0x00, 0x88, 0xB8]))
    assert decoded == proto.ResultMessage(mux_id=0x01, counter=5, state=ResultState.NONE, value=35000)


@pytest.mark.parametrize(
    ("current_ma", "value_bytes"),
    [
        (0, [0x00, 0x00, 0x00, 0x00]),
        (1, [0x00, 0x00, 0x00, 0x01]),
        (-1, [0xFF, 0xFF, 0xFF, 0xFF]),
        (-35000, [0xFF, 0xFF, 0x77, 0x48]),
        (-120_000, [0xFF, 0xFE, 0x2B, 0x40]),
        (INT32_MAX, [0x7F, 0xFF, 0xFF, 0xFF]),
        (INT32_MIN, [0x80, 0x00, 0x00, 0x00]),
    ],
)
def test_current_value_is_int32_big_endian_twos_complement(current_ma, value_bytes):
    assert list(proto.current_frame(current_ma, 0).data[2:]) == value_bytes


@pytest.mark.parametrize("value", [INT32_MAX + 1, INT32_MIN - 1, 2**40])
def test_value_outside_int32_raises(value):
    with pytest.raises(ValueError):
        proto.encode_result(proto.MUX_I, value, 0)


@pytest.mark.parametrize("counter", [-1, 16, 255])
def test_counter_outside_nibble_raises(counter):
    with pytest.raises(ValueError):
        proto.encode_result(proto.MUX_I, 0, counter)


@pytest.mark.parametrize("mux", [-1, 0x08, 0x10, 0xFF])
def test_result_mux_outside_0_to_7_raises(mux):
    with pytest.raises(ValueError):
        proto.encode_result(mux, 0, 0)


def test_state_wider_than_4_bits_raises():
    with pytest.raises(ValueError):
        proto.encode_result(proto.MUX_I, 0, 0, 0x10)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("state", "high_nibble"),
    [
        (ResultState.NONE, 0x0),
        (ResultState.OCS, 0x1),
        (ResultState.OUT_OF_RANGE, 0x2),
        (ResultState.ANY_MEASUREMENT_ERROR, 0x4),
        (ResultState.SYSTEM_ERROR, 0x8),
        (ResultState.OCS | ResultState.SYSTEM_ERROR, 0x9),
        (ResultState(0xF), 0xF),
    ],
)
def test_state_goes_in_high_nibble_counter_in_low_nibble(state, high_nibble):
    data = proto.current_frame(35000, 0xA, state).data
    assert data[1] == (high_nibble << 4) | 0xA
    assert proto.decode_result(data).state == state


@pytest.mark.parametrize(
    "msg",
    [
        proto.ResultMessage(proto.MUX_I, 0, ResultState.NONE, 0),
        proto.ResultMessage(proto.MUX_I, 15, ResultState(0xF), -1),
        proto.ResultMessage(proto.MUX_T, 7, ResultState.OUT_OF_RANGE, -400),
        proto.ResultMessage(proto.MUX_AS, 3, ResultState.OCS, INT32_MAX),
        proto.ResultMessage(proto.MUX_AS, 9, ResultState.NONE, INT32_MIN),
    ],
)
def test_decode_is_inverse_of_encode(msg):
    assert proto.decode_result(proto.encode_result(msg.mux_id, msg.value, msg.counter, msg.state)) == msg


@pytest.mark.parametrize("length", [0, 5, 7, 8])
def test_decode_rejects_wrong_length(length):
    with pytest.raises(ValueError):
        proto.decode_result(bytes(length))


# ------------------------------------------------------------- 0x525 / 0x527


@pytest.mark.parametrize(
    ("temperature_c", "raw"),
    [(25.0, 250), (23.46, 235), (23.44, 234), (-5.5, -55), (0.04, 0), (-40.0, -400), (125.0, 1250)],
)
def test_temperature_frame_uses_0_1_degc_rounded(temperature_c, raw):
    frame = proto.temperature_frame(temperature_c, 4)
    assert frame.arbitration_id == 0x525
    assert frame.dlc == 6
    assert frame.data[0] == 0x04
    assert frame.data[1] == 0x04
    assert proto.decode_result(frame.data).value == raw


def test_temperature_25c_bytes():
    assert list(proto.temperature_frame(25.0, 1).data) == [0x04, 0x01, 0x00, 0x00, 0x00, 0xFA]


@pytest.mark.parametrize("charge_as", [0, 3600, -7200, INT32_MAX, INT32_MIN])
def test_charge_frame_mux_06_1_as(charge_as):
    frame = proto.charge_frame(charge_as, 2, ResultState.OCS)
    assert frame.arbitration_id == 0x527
    assert frame.dlc == 6
    decoded = proto.decode_result(frame.data)
    assert (decoded.mux_id, decoded.counter, decoded.state, decoded.value) == (0x06, 2, ResultState.OCS, charge_as)


def test_charge_3600_as_bytes():
    assert list(proto.charge_frame(3600, 0).data) == [0x06, 0x00, 0x00, 0x00, 0x0E, 0x10]


# ------------------------------------------------------------- 0x511 responses


def test_alive_frame_matches_datasheet_chapter_9():
    frame = proto.alive_frame(0x12345678)
    assert frame.arbitration_id == 0x511
    assert list(frame.data) == [0xBF, 0x04, 0x11, 0x12, 0x34, 0x56, 0x78, 0x00]


def test_alive_frame_custom_command_id():
    assert list(proto.alive_frame(0x00012345, command_can_id=0x7FF).data) == [
        0xBF, 0x07, 0xFF, 0x00, 0x01, 0x23, 0x45, 0x00,
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("nominal", "db2", "db3_high"),
    # Datasheet 8.7, Response "DEVICE_ID": DB2 = I_nom / 16, DB3 high nibble = I_nom % 16.
    [
        (NominalRange.A100, 0x06, 0x4),
        (NominalRange.A300, 0x12, 0xC),
        (NominalRange.A500, 0x1F, 0x4),
        (NominalRange.A1000, 0x3E, 0x8),
        (NominalRange.A2500, 0x9C, 0x4),
    ],
)
def test_device_id_frame_matches_datasheet_table(nominal, db2, db3_high):
    frame = proto.device_id_frame(nominal)
    assert frame.arbitration_id == 0x511
    assert frame.dlc == 8
    assert list(frame.data) == [0xB9, 0x02, db2, db3_high << 4 | 0x0, 0x03, 0x01, 0x01, 0x00]


def test_device_id_three_voltage_channels_in_db3_low_nibble():
    assert proto.device_id_frame(NominalRange.A1000, voltage_channels=3).data[3] == 0x83


@pytest.mark.parametrize("channels", [1, 2, 4])
def test_device_id_rejects_invalid_voltage_channel_count(channels):
    with pytest.raises(ValueError):
        proto.device_id_frame(NominalRange.A1000, voltage_channels=channels)


def test_serial_number_frame():
    frame = proto.serial_number_frame(0xA1B2C3D4)
    assert frame.arbitration_id == 0x511
    assert list(frame.data) == [0xBB, 0xA1, 0xB2, 0xC3, 0xD4, 0x00, 0x00, 0x00]


@pytest.mark.parametrize(
    ("actual", "startup", "expected"),
    [
        (OperationMode.RUN, OperationMode.RUN, [0xB4, 0x01, 0x01, 0, 0, 0, 0, 0]),
        (OperationMode.STOP, OperationMode.RUN, [0xB4, 0x00, 0x01, 0, 0, 0, 0, 0]),
        (OperationMode.STOP, OperationMode.STOP, [0xB4, 0x00, 0x00, 0, 0, 0, 0, 0]),
    ],
)
def test_mode_frame(actual, startup, expected):
    frame = proto.mode_frame(actual, startup)
    assert frame.arbitration_id == 0x511
    assert list(frame.data) == expected


@pytest.mark.parametrize("mux", [0x31, 0x12, 0x00, 0xFE])
def test_error_frame_carries_invalid_mux(mux):
    assert list(proto.error_frame(mux).data) == [0xFF, mux, 0, 0, 0, 0, 0, 0]


@pytest.mark.parametrize(
    ("command", "response"),
    [(0x34, 0xB4), (0x74, 0xB4), (0x79, 0xB9), (0x7B, 0xBB), (0x3F, 0xBF), (0x30, 0xB0)],
)
def test_response_code_for_set_get_commands(command, response):
    assert proto.response_code_for(command) == response


def test_constants_match_datasheet_defaults():
    assert (proto.CMD_ID, proto.RESPONSE_ID) == (0x411, 0x511)
    assert (proto.RESULT_I_ID, proto.RESULT_T_ID, proto.RESULT_AS_ID) == (0x521, 0x525, 0x527)
    assert (proto.MUX_I, proto.MUX_T, proto.MUX_AS) == (0x00, 0x04, 0x06)


# ------------------------------------------------------------------- commands


def test_parse_command_extracts_code_and_payload():
    cmd = proto.parse_command(CANFrame(0x411, bytes([0x34, 0x00, 0x01, 0, 0, 0, 0, 0])))
    assert cmd == proto.Command(code=0x34, payload=bytes([0x00, 0x01, 0, 0, 0, 0, 0]))


@pytest.mark.parametrize(
    "frame",
    [CANFrame(0x411, b""), CANFrame(0x521, bytes([0x79])), CANFrame(0x511, bytes([0x79, 0, 0, 0, 0, 0, 0, 0]))],
)
def test_parse_command_ignores_non_commands(frame):
    assert proto.parse_command(frame) is None
