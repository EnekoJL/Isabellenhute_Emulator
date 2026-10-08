"""HandleBmsRequestsUseCase: every F-09 command, byte by byte (datasheet 8.5 / 8.7 / 9)."""

from __future__ import annotations

import pytest

from isascale.application.bms_requests import CommandOutcome, HandleBmsRequestsUseCase
from isascale.domain.models import CANFrame, IVTConfig, NominalRange, OperationMode

RUN, STOP = OperationMode.RUN, OperationMode.STOP


def cmd(*db: int) -> CANFrame:
    """IVT_Msg_Command 0x411, 8 bytes, unused = 0x00 (datasheet 8.1)."""
    return CANFrame(0x411, bytes(list(db) + [0] * (8 - len(db))))


@pytest.fixture
def handler() -> HandleBmsRequestsUseCase:
    return HandleBmsRequestsUseCase(IVTConfig(serial_number=0x0A0B0C0D, nominal_range=NominalRange.A1000))


def only_response(outcome: CommandOutcome | None) -> list[int]:
    assert outcome is not None
    assert len(outcome.responses) == 1
    frame = outcome.responses[0]
    assert frame.arbitration_id == 0x511
    assert frame.dlc == 8
    return list(frame.data)


def test_get_device_id_0x79_answers_0xb9(handler):
    outcome = handler.handle(cmd(0x79), RUN)
    assert only_response(outcome) == [0xB9, 0x02, 0x3E, 0x80, 0x03, 0x01, 0x01, 0x00]
    assert outcome.new_mode is None and not outcome.restart


@pytest.mark.parametrize(
    ("nominal", "db2", "db3"),
    [(NominalRange.A100, 0x06, 0x40), (NominalRange.A300, 0x12, 0xC0), (NominalRange.A2500, 0x9C, 0x40)],
)
def test_device_id_follows_configured_nominal_range(nominal, db2, db3):
    handler = HandleBmsRequestsUseCase(IVTConfig(nominal_range=nominal))
    assert only_response(handler.handle(cmd(0x79), RUN))[1:4] == [0x02, db2, db3]


def test_get_serial_number_0x7b_answers_0xbb(handler):
    assert only_response(handler.handle(cmd(0x7B), RUN)) == [0xBB, 0x0A, 0x0B, 0x0C, 0x0D, 0, 0, 0]


@pytest.mark.parametrize(("mode", "db1"), [(RUN, 0x01), (STOP, 0x00)])
def test_get_mode_0x74_reports_current_and_startup_mode(handler, mode, db1):
    outcome = handler.handle(cmd(0x74), mode)
    assert only_response(outcome) == [0xB4, db1, 0x01, 0, 0, 0, 0, 0]
    assert outcome.new_mode is None


def test_set_mode_stop_0x34(handler):
    outcome = handler.handle(cmd(0x34, 0x00, 0x01), RUN)
    assert only_response(outcome) == [0xB4, 0x00, 0x01, 0, 0, 0, 0, 0]
    assert outcome.new_mode is STOP
    assert not outcome.restart


def test_set_mode_run_0x34(handler):
    outcome = handler.handle(cmd(0x34, 0x01, 0x01), STOP)
    assert only_response(outcome) == [0xB4, 0x01, 0x01, 0, 0, 0, 0, 0]
    assert outcome.new_mode is RUN


def test_set_mode_updates_startup_mode_reported_by_get_mode(handler):
    handler.handle(cmd(0x34, 0x01, 0x00), RUN)
    assert handler.startup_mode is STOP
    assert only_response(handler.handle(cmd(0x74), RUN))[:3] == [0xB4, 0x01, 0x00]


def test_set_mode_with_short_payload_keeps_current_values(handler):
    outcome = handler.handle(CANFrame(0x411, bytes([0x34])), STOP)
    assert only_response(outcome)[:3] == [0xB4, 0x00, 0x01]
    assert outcome.new_mode is STOP


@pytest.mark.parametrize("payload", [(0x02, 0x01), (0x01, 0x07), (0xFF, 0xFF)])
def test_set_mode_invalid_value_answers_error_with_mux_0x34(handler, payload):
    outcome = handler.handle(cmd(0x34, *payload), RUN)
    assert only_response(outcome) == [0xFF, 0x34, 0, 0, 0, 0, 0, 0]
    assert outcome.new_mode is None
    assert handler.startup_mode is RUN


def test_restart_0x3f_answers_alive_and_requests_restart(handler):
    outcome = handler.handle(cmd(0x3F), STOP)
    assert only_response(outcome) == [0xBF, 0x04, 0x11, 0x0A, 0x0B, 0x0C, 0x0D, 0x00]
    assert outcome.restart
    assert outcome.new_mode is RUN  # back to startup mode


def test_restart_goes_to_configured_startup_mode():
    handler = HandleBmsRequestsUseCase(IVTConfig(), startup_mode=STOP)
    assert handler.handle(cmd(0x3F), RUN).new_mode is STOP


@pytest.mark.parametrize("code", [0x00, 0x10, 0x20, 0x31, 0x32, 0x3D, 0x40, 0x7A, 0x7C, 0xB9, 0xFF])
def test_unsupported_command_answers_0xff_with_received_mux(handler, code):
    outcome = handler.handle(cmd(code), RUN)
    assert only_response(outcome) == [0xFF, code, 0, 0, 0, 0, 0, 0]
    assert outcome.new_mode is None and not outcome.restart


@pytest.mark.parametrize(
    "frame",
    [CANFrame(0x521, bytes([0x79])), CANFrame(0x511, bytes(8)), CANFrame(0x411, b"")],
)
def test_non_command_frames_are_ignored(handler, frame):
    assert handler.handle(frame, RUN) is None


def test_config_setter_changes_answers(handler):
    handler.config = IVTConfig(serial_number=0x11223344)
    assert handler.config.serial_number == 0x11223344
    assert only_response(handler.handle(cmd(0x7B), RUN))[1:5] == [0x11, 0x22, 0x33, 0x44]
