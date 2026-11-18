"""Client side of the IVT-S protocol: literal command bytes (datasheet 8) and response decoding,
cross-checked against the emulator's own response encoders (ivt_protocol)."""

from __future__ import annotations

import pytest

from isascale.domain import ivt_commands as cmd
from isascale.domain import ivt_protocol as proto
from isascale.domain.models import CANFrame, ChannelConfig, Mux, NominalRange, OperationMode, TriggerMode

STOP, RUN = OperationMode.STOP, OperationMode.RUN


def response(*db: int) -> cmd.Response:
    parsed = cmd.parse_response(CANFrame(0x511, bytes(db).ljust(8, b"\x00")))
    assert parsed is not None
    return parsed


# --- commands ----------------------------------------------------------------


def test_set_mode_stop_keeps_run_at_start_up():
    frame = cmd.set_mode_command(STOP)
    assert frame.arbitration_id == 0x411
    assert frame.data == bytes([0x34, 0x00, 0x01, 0, 0, 0, 0, 0])


def test_set_config_as_cyclic_100_ms_with_error_bits():
    frame = cmd.set_config_command(Mux.AS, ChannelConfig(TriggerMode.CYCLIC, 100), error_mask_reporting=True)
    # DB1 = bit 5 (error mask) << 4 | cyclic 0x2 ; DB2..3 = 100 ms big endian (datasheet 8.4)
    assert frame.data == bytes([0x26, 0x22, 0x00, 0x64, 0, 0, 0, 0])


def test_set_config_flags_little_endian_and_inverted_sign():
    config = ChannelConfig(TriggerMode.CYCLIC, 1000, little_endian=True, invert_sign=True)
    frame = cmd.set_config_command(Mux.T, config, error_mask_reporting=False)
    assert frame.data[:4] == bytes([0x24, 0xC2, 0x03, 0xE8])


def test_get_config_store_and_plain_get_commands():
    assert cmd.get_config_command(Mux.I).data == bytes([0x60]) + bytes(7)
    assert cmd.store_command().data == bytes([0x32]) + bytes(7)
    assert cmd.get_command(proto.CMD_GET_SERIAL_NUMBER).data == bytes([0x7B]) + bytes(7)


def test_reset_log_since_reset_carries_the_serial_number():
    frame = cmd.reset_log_since_reset_command(0x0A0B0C0D)
    assert frame.data == bytes([0x30, 0x02, 0x00, 0x0A, 0x0B, 0x0C, 0x0D, 0x00])


@pytest.mark.parametrize(
    ("command", "expected"),
    [(0x26, 0xA6), (0x60, 0xA0), (0x34, 0xB4), (0x32, 0xB2), (0x30, 0xB0), (0x7B, 0xBB), (0x74, 0xB4)],
)
def test_expected_response_code(command, expected):
    assert cmd.expected_response_code(command) == expected


# --- responses ---------------------------------------------------------------


def test_parse_response_ignores_results_other_ids_and_empty_frames():
    assert cmd.parse_response(CANFrame(0x521, bytes(6))) is None
    assert cmd.parse_response(CANFrame(0x511, b"")) is None
    parsed = cmd.parse_response(CANFrame(0x511, bytes([0xBB, 1, 2])))
    assert parsed == cmd.Response(0xBB, bytes([1, 2, 0, 0, 0, 0, 0]))


def test_error_response_matches_only_its_command():
    error = response(0xFF, 0x32)
    assert cmd.is_error_for(error, 0x32)
    assert not cmd.is_error_for(error, 0x34)
    assert not cmd.is_error_for(response(0xB2, 0x32), 0x32)


@pytest.mark.parametrize("error_mask", [False, True])
def test_config_result_round_trip_with_the_emulator_encoder(error_mask):
    config = ChannelConfig(TriggerMode.CYCLIC, 1000, little_endian=True, invert_sign=False)
    frame = proto.config_result_frame(Mux.T, config, error_mask)
    setting = cmd.decode_config_result(cmd.parse_response(frame))
    assert setting == cmd.ChannelSetting(Mux.T, config, error_mask)


@pytest.mark.parametrize("code", [0xB4, 0xA8, 0xAF])
def test_config_result_rejects_other_codes(code):
    with pytest.raises(ValueError):
        cmd.decode_config_result(response(code, 0x02, 0x00, 0x14))


def test_mode_store_serial_and_sw_version_from_the_emulator_encoders():
    assert cmd.decode_mode(cmd.parse_response(proto.mode_frame(STOP, RUN))) == (STOP, RUN)
    assert cmd.decode_store_ok(cmd.parse_response(proto.store_frame(True, 1)))
    assert not cmd.decode_store_ok(cmd.parse_response(proto.store_frame(False, 1)))
    assert cmd.decode_serial_number(cmd.parse_response(proto.serial_number_frame(0x0A0B0C0D))) == 0x0A0B0C0D
    assert cmd.decode_sw_version(cmd.parse_response(proto.sw_version_frame((1, 2, 3, 22, 6, 9)))) == (1, 2, 3, 22, 6, 9)


def test_device_id_of_the_team_sensor():
    # IVT-S-1K-U0: B9 02 3E 80 03 01 01 00 (datasheet 8.7, emulator F-10)
    device = cmd.decode_device_id(response(0xB9, 0x02, 0x3E, 0x80, 0x03, 0x01, 0x01))
    assert device == cmd.DeviceId(nominal_current_a=1000, voltage_channels=0)
    assert cmd.decode_device_id(cmd.parse_response(proto.device_id_frame(NominalRange.A1000))) == device


def test_response_u16_reads_big_endian():
    assert response(0xA0, 0x02, 0x03, 0xE8).u16(2) == 1000
