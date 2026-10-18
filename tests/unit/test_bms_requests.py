"""HandleBmsRequestsUseCase: every command of datasheet 8.3 .. 8.7, byte by byte."""

from __future__ import annotations

import pytest

from isascale.application import bms_requests as br
from isascale.application.bms_requests import CommandOutcome, DeviceState, HandleBmsRequestsUseCase, RestartKind
from isascale.domain.models import (
    Bitrate,
    CANFrame,
    ChannelConfig,
    IVTConfig,
    Mux,
    NominalRange,
    OcThresholds,
    OperationMode,
    SensorSettings,
    TriggerMode,
)
from isascale.domain.sensor_state import LogItem, LogSample

RUN, STOP = OperationMode.RUN, OperationMode.STOP
SERIAL = 0x0A0B0C0D
SN = [0x0A, 0x0B, 0x0C, 0x0D]
NOW = 50.0


def cmd(*db: int, can_id: int = 0x411) -> CANFrame:
    """Command message, 8 bytes, unused = 0x00 (datasheet 8.1)."""
    return CANFrame(can_id, bytes(list(db) + [0] * (8 - len(db))))


def make_device(mode: OperationMode = RUN, nominal: NominalRange = NominalRange.A1000) -> DeviceState:
    settings = IVTConfig().to_settings()
    return DeviceState(SERIAL, nominal, Bitrate.B500K, stored=settings, active=settings, mode=mode)


@pytest.fixture
def handler() -> HandleBmsRequestsUseCase:
    return HandleBmsRequestsUseCase()


@pytest.fixture
def run_dev() -> DeviceState:
    return make_device(RUN)


@pytest.fixture
def stop_dev() -> DeviceState:
    return make_device(STOP)


def only_response(outcome: CommandOutcome | None, response_id: int = 0x511) -> list[int]:
    assert outcome is not None
    assert len(outcome.responses) == 1 and not outcome.delayed
    frame = outcome.responses[0]
    assert frame.arbitration_id == response_id
    assert frame.dlc == 8
    return list(frame.data)


def delayed_response(outcome: CommandOutcome | None) -> tuple[float, list[int]]:
    assert outcome is not None and not outcome.responses
    ((delay, frame),) = outcome.delayed
    return delay, list(frame.data)


# --------------------------------------------------------------- identification


def test_get_device_id_0x79_answers_0xb9(handler, run_dev):
    outcome = handler.handle(cmd(0x79), run_dev, NOW)
    assert only_response(outcome) == [0xB9, 0x02, 0x3E, 0x80, 0x03, 0x01, 0x01, 0x00]  # IVT-S 1000 A, U0, CAN1
    assert outcome.restart is None


@pytest.mark.parametrize(
    ("nominal", "db2", "db3"),
    [
        (NominalRange.A100, 0x06, 0x40),
        (NominalRange.A300, 0x12, 0xC0),
        (NominalRange.A500, 0x1F, 0x40),
        (NominalRange.A2500, 0x9C, 0x40),
    ],
)
def test_device_id_follows_nominal_range(handler, nominal, db2, db3):
    assert only_response(handler.handle(cmd(0x79), make_device(nominal=nominal), NOW))[1:4] == [0x02, db2, db3]


def test_get_serial_number_0x7b_answers_0xbb(handler, run_dev):
    assert only_response(handler.handle(cmd(0x7B), run_dev, NOW)) == [0xBB, *SN, 0, 0, 0]


def test_get_sw_version_0x7a_answers_0xba(handler, run_dev):
    assert only_response(handler.handle(cmd(0x7A), run_dev, NOW)) == [0xBA, 1, 0, 0, 22, 6, 9, 0]


def test_get_article_number_0x7c_answers_0xbc(handler, run_dev):
    assert only_response(handler.handle(cmd(0x7C), run_dev, NOW)) == [0xBC, 0, 0, 0, 0, 0, 0, 0]


# ------------------------------------------------------------------------- mode


@pytest.mark.parametrize(("mode", "db1"), [(RUN, 0x01), (STOP, 0x00)])
def test_get_mode_0x74_reports_current_and_startup_mode(handler, mode, db1):
    assert only_response(handler.handle(cmd(0x74), make_device(mode), NOW)) == [0xB4, db1, 0x01, 0, 0, 0, 0, 0]


def test_set_mode_stop_0x34(handler, run_dev):
    outcome = handler.handle(cmd(0x34, 0x00, 0x01), run_dev, NOW)
    assert only_response(outcome) == [0xB4, 0x00, 0x01, 0, 0, 0, 0, 0]
    assert run_dev.mode is STOP and outcome.mode_changed


def test_set_mode_same_mode_is_acknowledged_without_change(handler, run_dev):
    outcome = handler.handle(cmd(0x34, 0x01, 0x01), run_dev, NOW)
    assert only_response(outcome)[:3] == [0xB4, 0x01, 0x01]
    assert not outcome.mode_changed


def test_set_mode_startup_mode_is_active_until_store(handler, run_dev):
    handler.handle(cmd(0x34, 0x01, 0x00), run_dev, NOW)
    assert run_dev.active.startup_mode is STOP
    assert run_dev.stored.startup_mode is RUN  # needs STORE before reset (datasheet 8.5)
    assert only_response(handler.handle(cmd(0x74), run_dev, NOW))[:3] == [0xB4, 0x01, 0x00]


@pytest.mark.parametrize("payload", [(0x02, 0x01), (0x01, 0x07), (0xFF, 0xFF)])
def test_set_mode_invalid_value_answers_error(handler, run_dev, payload):
    assert only_response(handler.handle(cmd(0x34, *payload), run_dev, NOW)) == [0xFF, 0x34, 0, 0, 0, 0, 0, 0]
    assert run_dev.mode is RUN


# --------------------------------------------------------------------- restarts


@pytest.mark.parametrize("mode", [RUN, STOP])
def test_restart_0x3f_has_no_immediate_response_and_requests_restart(handler, mode):
    outcome = handler.handle(cmd(0x3F), make_device(mode), NOW)
    assert outcome.responses == () and outcome.restart is RestartKind.RESTART


def test_restart_to_default_0x3d_only_in_stop(handler, run_dev, stop_dev):
    assert only_response(handler.handle(cmd(0x3D), run_dev, NOW)) == [0xFF, 0x3D, 0, 0, 0, 0, 0, 0]
    assert handler.handle(cmd(0x3D), stop_dev, NOW).restart is RestartKind.TO_DEFAULT


@pytest.mark.parametrize(("prescaler", "bitrate"), [(0x08, Bitrate.B250K), (0x04, Bitrate.B500K), (0x02, Bitrate.B1M)])
def test_restart_to_bitrate_0x3a(handler, stop_dev, prescaler, bitrate):
    outcome = handler.handle(cmd(0x3A, prescaler), stop_dev, NOW)
    assert (outcome.restart, outcome.new_bitrate) == (RestartKind.TO_BITRATE, bitrate)


@pytest.mark.parametrize(("mode", "prescaler"), [(RUN, 0x04), (STOP, 0x03), (STOP, 0x00)])
def test_restart_to_bitrate_rejected_in_run_or_bad_prescaler(handler, mode, prescaler):
    outcome = handler.handle(cmd(0x3A, prescaler), make_device(mode), NOW)
    assert only_response(outcome) == [0xFF, 0x3A, 0, 0, 0, 0, 0, 0]
    assert outcome.restart is None


# ----------------------------------------------------------------- Config Result


def test_get_config_0x6n_reports_datasheet_defaults(handler, run_dev):
    assert only_response(handler.handle(cmd(0x60), run_dev, NOW)) == [0xA0, 0x02, 0x00, 20, 0, 0, 0, 0]  # I cyclic 20
    assert only_response(handler.handle(cmd(0x64), run_dev, NOW)) == [0xA4, 0x00, 0x00, 100, 0, 0, 0, 0]  # T off
    assert only_response(handler.handle(cmd(0x66), run_dev, NOW)) == [0xA6, 0x00, 0x00, 30, 0, 0, 0, 0]  # As off
    assert only_response(handler.handle(cmd(0x61), run_dev, NOW))[:4] == [0xA1, 0x02, 0x00, 60]  # U1 cyclic 60


def test_set_config_0x2n_in_stop_changes_active_settings(handler, stop_dev):
    outcome = handler.handle(cmd(0x26, 0x02, 0x00, 0x64), stop_dev, NOW)  # As cyclic 100 ms
    assert only_response(outcome) == [0xA6, 0x02, 0x00, 0x64, 0, 0, 0, 0]
    assert stop_dev.active.channel(Mux.AS) == ChannelConfig(TriggerMode.CYCLIC, 100)
    assert stop_dev.stored.channel(Mux.AS).mode is TriggerMode.DISABLED  # until STORE


def test_set_config_flags_endianness_sign_and_error_mask(handler, stop_dev):
    outcome = handler.handle(cmd(0x20, 0xE2, 0x00, 0x0A), stop_dev, NOW)  # bits 5, 6, 7 + cyclic, 10 ms
    assert only_response(outcome)[:4] == [0xA0, 0xE2, 0x00, 0x0A]
    config = stop_dev.active.channel(Mux.I)
    assert config.little_endian and config.invert_sign and config.cycle_ms == 10
    assert stop_dev.active.error_mask_reporting
    assert only_response(handler.handle(cmd(0x64), stop_dev, NOW))[1] == 0x20  # bit 5 is global


def test_set_config_in_run_answers_unchanged_config(handler, run_dev):
    outcome = handler.handle(cmd(0x24, 0x02, 0x00, 0x0A), run_dev, NOW)
    assert only_response(outcome)[:4] == [0xA4, 0x00, 0x00, 100]  # acknowledged, not applied
    assert run_dev.active.channel(Mux.T).mode is TriggerMode.DISABLED


def test_set_config_cycle_zero_is_ignored(handler, stop_dev):
    handler.handle(cmd(0x24, 0x02, 0x00, 0x00), stop_dev, NOW)
    assert stop_dev.active.channel(Mux.T) == ChannelConfig(TriggerMode.CYCLIC, 100)


def test_set_config_voltage_cycle_below_3_ms_is_raised_to_3(handler, stop_dev):
    handler.handle(cmd(0x21, 0x02, 0x00, 0x01), stop_dev, NOW)
    assert stop_dev.active.channel(Mux.U1).cycle_ms == 3


@pytest.mark.parametrize("frame", [cmd(0x20, 0x03, 0x00, 0x10), cmd(0x28, 0x02, 0x00, 0x10), cmd(0x6F)])
def test_config_invalid_mode_or_channel_answers_error(handler, stop_dev, frame):
    assert only_response(handler.handle(frame, stop_dev, NOW))[:2] == [0xFF, frame.data[0]]


# ------------------------------------------------------------------------ CAN ID


def test_get_can_id_0x5n_with_matching_serial(handler, run_dev):
    assert only_response(handler.handle(cmd(0x50, 0, 0, *SN), run_dev, NOW)) == [0x90, 0x05, 0x21, *SN, 0]
    assert only_response(handler.handle(cmd(0x5D, 0, 0, *SN), run_dev, NOW))[:3] == [0x9D, 0x04, 0x11]
    assert only_response(handler.handle(cmd(0x5F, 0, 0, *SN), run_dev, NOW))[:3] == [0x9F, 0x05, 0x11]


def test_can_id_commands_for_another_serial_are_ignored(handler, stop_dev):
    assert handler.handle(cmd(0x50, 0, 0, 1, 2, 3, 4), stop_dev, NOW) is None
    assert handler.handle(cmd(0x10, 0x01, 0x00, 1, 2, 3, 4), stop_dev, NOW) is None
    assert stop_dev.active.result_ids[Mux.I] == 0x521


def test_set_can_id_0x1n_in_stop(handler, stop_dev):
    outcome = handler.handle(cmd(0x10, 0x01, 0x00, *SN), stop_dev, NOW)
    assert only_response(outcome) == [0x90, 0x01, 0x00, *SN, 0]
    assert stop_dev.active.result_ids[Mux.I] == 0x100
    assert stop_dev.stored.result_ids[Mux.I] == 0x521


def test_set_command_and_response_ids(handler, stop_dev):
    handler.handle(cmd(0x1F, 0x06, 0x00, *SN), stop_dev, NOW)  # response -> 0x600
    outcome = handler.handle(cmd(0x1D, 0x04, 0x00, *SN), stop_dev, NOW)  # command -> 0x400
    assert only_response(outcome, response_id=0x600)[:3] == [0x9D, 0x04, 0x00]
    assert handler.handle(cmd(0x79), stop_dev, NOW) is None  # 0x411 is no longer ours
    assert only_response(handler.handle(cmd(0x79, can_id=0x400), stop_dev, NOW), response_id=0x600)[0] == 0xB9


def test_set_can_id_in_run_answers_current_id(handler, run_dev):
    assert only_response(handler.handle(cmd(0x14, 0x01, 0x00, *SN), run_dev, NOW))[:3] == [0x94, 0x05, 0x25]
    assert run_dev.active.result_ids[Mux.T] == 0x525


@pytest.mark.parametrize("frame", [cmd(0x10, 0x00, 0x00, *SN), cmd(0x10, 0x08, 0x00, *SN), cmd(0x18, 0x01, 0, *SN)])
def test_set_can_id_invalid_answers_error(handler, stop_dev, frame):
    assert only_response(handler.handle(frame, stop_dev, NOW))[:2] == [0xFF, frame.data[0]]


def test_get_can_id_undefined_index_answers_error(handler, run_dev):
    assert only_response(handler.handle(cmd(0x5E, 0, 0, *SN), run_dev, NOW))[:2] == [0xFF, 0x5E]


# ------------------------------------------------------------------------ STORE


def test_store_0x32_in_stop_persists_active_settings(handler, stop_dev):
    handler.handle(cmd(0x26, 0x02, 0x00, 0x64), stop_dev, NOW)
    delay, data = delayed_response(handler.handle(cmd(0x32), stop_dev, NOW))
    assert (delay, data) == (br.STORE_DELAY_S, [0xB2, 0x00, *SN, 0, 0])
    assert stop_dev.stored == stop_dev.active


def test_commands_during_store_are_refused(handler, stop_dev):
    handler.handle(cmd(0x32), stop_dev, NOW)
    assert only_response(handler.handle(cmd(0x79), stop_dev, NOW + 0.1)) == [0xFF, 0x79, 0, 0, 0, 0, 0, 0]
    assert only_response(handler.handle(cmd(0x79), stop_dev, NOW + br.STORE_DELAY_S))[0] == 0xB9


def test_store_in_run_answers_error_status(handler, run_dev):
    assert only_response(handler.handle(cmd(0x32), run_dev, NOW)) == [0xB2, 0x01, *SN, 0, 0]


# -------------------------------------------------------------- OC thresholds / test


def test_set_threshold_pos_0x35_and_get_0x75(handler, stop_dev):
    outcome = handler.handle(cmd(0x35, 0x01, 0xF4, 0x01, 0xC2), stop_dev, NOW)  # set 500 A, reset 450 A
    assert only_response(outcome) == [0xB5, 0x01, 0xF4, 0x01, 0xC2, 0, 0, 0]
    assert stop_dev.active.oc_positive == OcThresholds(500, 450)
    assert only_response(handler.handle(cmd(0x75), stop_dev, NOW))[:5] == [0xB5, 0x01, 0xF4, 0x01, 0xC2]


def test_set_threshold_neg_0x36_signed(handler, stop_dev):
    outcome = handler.handle(cmd(0x36, 0xFE, 0x0C, 0xFE, 0x3E), stop_dev, NOW)  # -500 A, -450 A
    assert only_response(outcome)[:5] == [0xB6, 0xFE, 0x0C, 0xFE, 0x3E]
    assert stop_dev.active.oc_negative == OcThresholds(-500, -450)
    assert only_response(handler.handle(cmd(0x76), stop_dev, NOW))[0] == 0xB6


def test_set_threshold_in_run_answers_unchanged(handler, run_dev):
    assert only_response(handler.handle(cmd(0x35, 0x01, 0xF4), run_dev, NOW))[:5] == [0xB5, 0, 0, 0, 0]


def test_oc_test_0x33_and_remaining_time_0x73(handler, stop_dev):
    assert only_response(handler.handle(cmd(0x33, 0x03, 0xE8), stop_dev, NOW))[:3] == [0xB3, 0x03, 0xE8]  # 1000 ms
    assert only_response(handler.handle(cmd(0x73), stop_dev, NOW + 0.25))[:3] == [0xB3, 0x02, 0xEE]  # 750 ms
    assert only_response(handler.handle(cmd(0x73), stop_dev, NOW + 2.0))[:3] == [0xB3, 0x00, 0x00]


def test_oc_test_in_run_is_not_started(handler, run_dev):
    assert only_response(handler.handle(cmd(0x33, 0x03, 0xE8), run_dev, NOW))[:3] == [0xB3, 0x00, 0x00]


# ----------------------------------------------------------------------- TRIGGER


def test_trigger_0x31_in_run_echoes_and_requests_channels(handler, run_dev):
    outcome = handler.handle(cmd(0x31, 0x00, 0x51), run_dev, NOW)  # I, T, As
    assert only_response(outcome) == [0xB1, 0x00, 0x51, 0, 0, 0, 0, 0]
    assert outcome.trigger_bits == 0x51


def test_trigger_in_stop_is_acknowledged_but_not_executed(handler, stop_dev):
    outcome = handler.handle(cmd(0x31, 0xFF, 0x01), stop_dev, NOW)
    assert only_response(outcome)[:3] == [0xB1, 0x00, 0x01]  # undefined high bits answered as 0
    assert outcome.trigger_bits == 0


# -------------------------------------------------------- error and log data


def test_get_measurement_errors_bitmask_and_counter(handler, run_dev):
    run_dev.measurement_errors.increment(0x02)
    run_dev.measurement_errors.increment(0x09)
    assert only_response(handler.handle(cmd(0x40, 0x00), run_dev, NOW)) == [0x80, 0x00, 0x02, 0x01, 0, 0, 0, 0]
    assert only_response(handler.handle(cmd(0x40, 0x02), run_dev, NOW))[:3] == [0x80, 0x02, 0x01]


def test_get_system_errors_watchdog(handler, run_dev):
    for _ in range(3):
        run_dev.system_errors.increment(0x0F)
    assert only_response(handler.handle(cmd(0x41, 0x00), run_dev, NOW))[:4] == [0x81, 0x00, 0x00, 0x40]
    assert only_response(handler.handle(cmd(0x41, 0x0F), run_dev, NOW))[:3] == [0x81, 0x0F, 0x03]


@pytest.mark.parametrize("frame", [cmd(0x40, 0x10), cmd(0x41, 0x11)])
def test_get_errors_unknown_counter_answers_error(handler, run_dev, frame):
    assert only_response(handler.handle(frame, run_dev, NOW))[:2] == [0xFF, frame.data[0]]


def test_reset_errors_0x30_in_stop_is_answered_after_1200_ms(handler, stop_dev):
    stop_dev.system_errors.increment(0x0F)
    delay, data = delayed_response(handler.handle(cmd(0x30, 0x01, 0x00, *SN), stop_dev, NOW))
    assert (delay, data) == (1.2, [0xB0, 0x01, 0x00, *SN, 0])
    assert not stop_dev.system_errors.any


def test_reset_one_measurement_counter(handler, stop_dev):
    stop_dev.measurement_errors.increment(0x02)
    stop_dev.measurement_errors.increment(0x03)
    handler.handle(cmd(0x30, 0x00, 0x02, *SN), stop_dev, NOW)
    assert (stop_dev.measurement_errors.count(2), stop_dev.measurement_errors.count(3)) == (0, 1)


def test_reset_logdata_since_reset(handler, stop_dev):
    sample = LogSample(10_000, 25.0, 10.0, True, False, False, True)
    stop_dev.log_since_reset.update(sample)
    stop_dev.log_overall.update(sample)
    handler.handle(cmd(0x30, 0x02, 0x00, *SN), stop_dev, NOW)
    assert stop_dev.log_since_reset.value(LogItem.AS_OVERALL) == 0
    assert stop_dev.log_overall.value(LogItem.AS_OVERALL) == 100  # overall: reset only by Isabellenhuette


def test_reset_errors_in_run_answers_without_resetting(handler, run_dev):
    run_dev.system_errors.increment(0x0F)
    delayed_response(handler.handle(cmd(0x30, 0x01, 0x00, *SN), run_dev, NOW))
    assert run_dev.system_errors.any


def test_reset_errors_other_serial_is_ignored(handler, stop_dev):
    assert handler.handle(cmd(0x30, 0x01, 0x00, 1, 2, 3, 4), stop_dev, NOW) is None


@pytest.mark.parametrize("db", [(0x03, 0x00), (0x00, 0x10), (0x02, 0x07)])
def test_reset_errors_invalid_target_answers_error(handler, stop_dev, db):
    assert only_response(handler.handle(cmd(0x30, *db, *SN), stop_dev, NOW))[:2] == [0xFF, 0x30]


def test_get_log_overall_0x42_and_since_reset_0x43(handler, run_dev):
    run_dev.log_overall.update(LogSample(-20_000, 25.0, 10.0, True, False, False, True))  # 200 As charged
    assert only_response(handler.handle(cmd(0x42, 0x02), run_dev, NOW)) == [0x82, 0x02, 0, 0, 0, 0, 0, 200]
    overall = only_response(handler.handle(cmd(0x42, 0x01), run_dev, NOW))
    assert overall[2:] == list((-200).to_bytes(6, "big", signed=True))
    assert only_response(handler.handle(cmd(0x43, 0x01), run_dev, NOW)) == [0x83, 0x01, 0, 0, 0, 0, 0, 0]


def test_get_log_unknown_item_answers_error(handler, run_dev):
    assert only_response(handler.handle(cmd(0x42, 0x07), run_dev, NOW))[:2] == [0xFF, 0x42]


# ----------------------------------------------------------- errors / filtering


@pytest.mark.parametrize("code", [0x00, 0x07, 0x37, 0x3B, 0x44, 0x70, 0x7D, 0x80, 0xB9, 0xFF])
def test_undefined_command_answers_0xff_with_received_mux(handler, run_dev, code):
    outcome = handler.handle(cmd(code), run_dev, NOW)
    assert only_response(outcome) == [0xFF, code, 0, 0, 0, 0, 0, 0]
    assert outcome.restart is None


@pytest.mark.parametrize("frame", [CANFrame(0x521, bytes([0x79])), CANFrame(0x511, bytes(8)), CANFrame(0x411, b"")])
def test_non_command_frames_are_ignored(handler, run_dev, frame):
    assert handler.handle(frame, run_dev, NOW) is None


def test_short_command_is_padded_with_zeros(handler, stop_dev):
    outcome = handler.handle(CANFrame(0x411, bytes([0x34])), stop_dev, NOW)
    assert only_response(outcome)[:3] == [0xB4, 0x00, 0x00]  # DB1/DB2 read as 0x00 = STOP / STOP


def test_factory_settings_match_datasheet_defaults():
    settings = SensorSettings()
    assert settings.command_id == 0x411 and settings.response_id == 0x511
    assert settings.result_ids == (0x521, 0x522, 0x523, 0x524, 0x525, 0x526, 0x527, 0x528)
    assert settings.channel(Mux.I) == ChannelConfig(TriggerMode.CYCLIC, 20)
    assert [settings.channel(m).mode for m in (Mux.T, Mux.W, Mux.AS, Mux.WH)] == [TriggerMode.DISABLED] * 4
    assert settings.startup_mode is RUN and not settings.error_mask_reporting
