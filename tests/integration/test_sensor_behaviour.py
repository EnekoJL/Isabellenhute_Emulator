"""EmulatorService behaving like the real IVT-S: start-up, restarts, CAN reconfiguration,
trigger mode, OCS, error bits and log data (FakeTimer + FakeCanPort, deterministic)."""

from __future__ import annotations

import pytest
from fakes import FakeCanPort, cfg, run_for

from isascale.application import bms_requests as br
from isascale.application.emulator_service import EmulatorService
from isascale.domain import ivt_protocol as proto
from isascale.domain.models import Bitrate, IVTConfig, Mux, OperationMode, ResultState, TriggerMode

I, T, AS, RESP = 0x521, 0x525, 0x527, 0x511
SN = [0x00, 0x01, 0x23, 0x45]


def results(port: FakeCanPort, can_id: int, little_endian: bool = False) -> list[proto.ResultMessage]:
    return [proto.decode_result(f.data, little_endian) for f in port.frames(can_id)]


def responses(port: FakeCanPort, response_id: int = RESP) -> list[list[int]]:
    return [list(f.data) for f in port.frames(response_id)]


def command(port: FakeCanPort, service: EmulatorService, *db: int, can_id: int = 0x411) -> None:
    port.push_rx(can_id, list(db) + [0] * (8 - len(db)))
    service.tick()


def stop_mode(port: FakeCanPort, service: EmulatorService) -> None:
    command(port, service, 0x34, 0x00, 0x01)


def run_mode(port: FakeCanPort, service: EmulatorService) -> None:
    command(port, service, 0x34, 0x01, 0x01)


# -------------------------------------------------------------- datasheet defaults


def test_default_sensor_sends_only_the_current_result(can_port, timer):
    service = EmulatorService(can_port, timer, IVTConfig(startup_time_ms=0))
    service.start()
    run_for(service, timer, 1.001)
    assert len(can_port.frames(I)) == 50
    assert can_port.frames(T) == can_port.frames(AS) == []


# ------------------------------------------------------------------------ start-up


def test_startup_is_silent_for_400_ms_then_alive_then_results(can_port, timer):
    service = EmulatorService(can_port, timer, IVTConfig())
    t0 = timer.now()
    service.start()
    assert service.snapshot().booting
    can_port.push_rx(0x411, [0x79] + [0] * 7)
    run_for(service, timer, 0.399)
    assert can_port.sent == []  # not ready: no alive, no results, no answers
    assert not can_port.rx_queue
    run_for(service, timer, 0.022)
    assert can_port.sent[0].frame.data[0] == 0xBF
    assert can_port.sent[0].t == pytest.approx(t0 + 0.400)
    assert can_port.times(I) == [pytest.approx(t0 + 0.420)]
    assert not service.snapshot().booting


def test_power_off_drops_pending_delayed_responses(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x30, 0x01, 0x00, *SN)  # answered after 1.2 s
    service.stop()
    service.start()
    can_port.clear()
    run_for(service, timer, 2.0)
    assert [r for r in responses(can_port) if r[0] == 0xB0] == []


def test_stop_during_boot_cancels_it(can_port, timer):
    service = EmulatorService(can_port, timer, IVTConfig())
    service.start()
    run_for(service, timer, 0.1)
    service.stop()
    run_for(service, timer, 1.0)
    assert can_port.sent == []


# ------------------------------------------------------------------------ restarts


def test_restart_is_silent_for_startup_time_and_counts_watchdog(can_port, timer):
    service = EmulatorService(can_port, timer, cfg(startup_time_ms=400))
    service.start()
    run_for(service, timer, 0.5)
    can_port.clear()
    t_cmd = timer.now()
    command(can_port, service, 0x3F)
    run_for(service, timer, 0.399)
    assert can_port.sent == []
    run_for(service, timer, 0.002)
    assert can_port.sent[0].frame.data[0] == 0xBF
    assert can_port.sent[0].t == pytest.approx(t_cmd + 0.400)
    assert service.device.system_errors.count(0x0F) == 1


def test_commands_sent_during_restart_are_lost(can_port, timer):
    service = EmulatorService(can_port, timer, cfg(startup_time_ms=400))
    service.start()
    run_for(service, timer, 0.5)
    can_port.clear()
    can_port.push_rx(0x411, [0x3F] + [0] * 7)
    can_port.push_rx(0x411, [0x79] + [0] * 7)
    run_for(service, timer, 0.5)
    assert [r[0] for r in responses(can_port)] == [0xBF]  # alive only, 0x79 lost while restarting


def test_restart_drops_unstored_settings(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x34, 0x00, 0x00)  # startup STOP, not stored
    command(can_port, service, 0x10, 0x01, 0x00, *SN)  # I -> 0x100, not stored
    command(can_port, service, 0x3F)
    assert service.mode is OperationMode.RUN
    assert service.device.active.result_ids[Mux.I] == I


def test_store_then_restart_keeps_settings(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x10, 0x01, 0x00, *SN)  # I -> 0x100
    command(can_port, service, 0x34, 0x00, 0x01)
    command(can_port, service, 0x32)
    run_for(service, timer, br.STORE_DELAY_S + 0.001)
    assert responses(can_port)[-1] == [0xB2, 0x00, *SN, 0, 0]
    command(can_port, service, 0x3F)
    can_port.clear()
    run_for(service, timer, 0.101)
    assert len(can_port.frames(0x100)) == 5 and can_port.frames(I) == []


def test_stored_settings_survive_power_cycle(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x24, 0x00, 0x00, 0x00)  # T disabled
    command(can_port, service, 0x32)
    run_for(service, timer, 0.3)
    service.stop()
    service.start()
    can_port.clear()
    run_for(service, timer, 0.5)
    assert can_port.frames(T) == []
    assert can_port.frames(I)


def test_restart_to_default_restores_factory_settings(service, can_port, timer):
    service.start()  # GUI config: T and As enabled
    stop_mode(can_port, service)
    command(can_port, service, 0x3D)
    can_port.clear()
    run_for(service, timer, 0.5)
    assert can_port.frames(I) and can_port.frames(T) == can_port.frames(AS) == []


def test_restart_to_bitrate_reconnects_at_new_speed(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x3A, 0x02)
    assert can_port.bitrate is Bitrate.B1M
    assert service.config.bitrate is Bitrate.B1M
    assert service.device.bitrate is Bitrate.B1M
    assert responses(can_port)[-1][0] == 0xBF


def test_restart_to_bitrate_connect_failure_is_recorded(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    can_port.fail_connect = True
    command(can_port, service, 0x3A, 0x08)  # must not raise
    assert not can_port.is_connected
    assert service.running and service.config.bitrate is Bitrate.B250K


# ---------------------------------------------------------- CAN reconfiguration


def test_bms_enables_temperature_over_can(can_port, timer):
    service = EmulatorService(can_port, timer, IVTConfig(startup_time_ms=0))
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x24, 0x02, 0x00, 0x32)  # T cyclic 50 ms
    run_mode(can_port, service)
    can_port.clear()
    run_for(service, timer, 0.201)
    assert len(can_port.frames(T)) == 4
    assert service.snapshot().settings.channel(Mux.T).cycle_ms == 50


def test_config_change_takes_effect_only_after_run(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x20, 0x02, 0x00, 0x0A)  # I 10 ms
    can_port.clear()
    run_for(service, timer, 0.2)
    assert can_port.frames(I) == []  # STOP: no results
    run_mode(can_port, service)
    run_for(service, timer, 0.101)
    assert len(can_port.frames(I)) == 10


def test_little_endian_and_inverted_sign_results(service, can_port, timer):
    service.set_manual_current(35_000)
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x20, 0xC2, 0x00, 0x14)  # little endian + sign change, 20 ms
    run_mode(can_port, service)
    can_port.clear()
    run_for(service, timer, 0.021)
    assert list(can_port.frames(I)[0].data[2:]) == [0x48, 0x77, 0xFF, 0xFF]  # -35000 LE
    assert results(can_port, I, little_endian=True)[0].value == -35_000


def test_new_result_id_is_used(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x10, 0x03, 0x21, *SN)
    run_mode(can_port, service)
    can_port.clear()
    run_for(service, timer, 0.101)
    assert len(can_port.frames(0x321)) == 5 and can_port.frames(I) == []


# ------------------------------------------------------------------- trigger


def test_triggered_channels_answer_trigger_after_delay(service, can_port, timer):
    service.set_manual_current(12_000)
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x20, 0x01, 0x00, 0x05)  # I triggered, 5 ms delay
    run_mode(can_port, service)
    can_port.clear()
    run_for(service, timer, 0.2)
    assert can_port.frames(I) == []  # no cyclic output
    t_trigger = timer.now()
    command(can_port, service, 0x31, 0x00, 0x11)  # trigger I and T (T is cyclic, not triggered)
    assert responses(can_port)[-1] == [0xB1, 0x00, 0x11, 0, 0, 0, 0, 0]
    run_for(service, timer, 0.01)
    assert can_port.times(I) == [pytest.approx(t_trigger + 0.005)]
    assert results(can_port, I)[0].value == 12_000


# ---------------------------------------------------------------- OCS / error bits


def test_ocs_bit_follows_thresholds_with_hysteresis(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x35, 0x01, 0xF4, 0x01, 0xC2)  # set 500 A, reset 450 A
    run_mode(can_port, service)

    def ocs_after(current_ma: int) -> bool:
        service.set_manual_current(current_ma)
        run_for(service, timer, 0.0201)
        return bool(results(can_port, I)[-1].state & ResultState.OCS)

    assert [ocs_after(i) for i in (400_000, 500_000, 460_000, 440_000)] == [False, True, True, False]
    assert service.device.log_overall.value(0x1B) == 0  # OC runtime in whole seconds: 40 ms so far


def test_ocs_bit_is_set_on_every_result(service, can_port, timer):
    service.set_manual_current(-600_000)
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x36, 0xFE, 0x0C)  # set -500 A, no reset threshold
    run_mode(can_port, service)
    run_for(service, timer, 0.101)
    for can_id in (I, T, AS):
        assert results(can_port, can_id)[-1].state & ResultState.OCS


def test_error_mask_reporting_shows_watchdog_after_restart(service, can_port, timer):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x20, 0x22, 0x00, 0x14)  # bit 5 on: report error masks
    command(can_port, service, 0x32)
    run_for(service, timer, 0.3)
    command(can_port, service, 0x3F)  # restart -> Error Reset Watchdog
    can_port.clear()
    run_for(service, timer, 0.101)
    assert all(m.state & ResultState.SYSTEM_ERROR for m in results(can_port, I))
    stop_mode(can_port, service)
    command(can_port, service, 0x30, 0x01, 0x00, *SN)  # reset system errors
    run_mode(can_port, service)
    run_for(service, timer, 1.3)
    assert responses(can_port)[-1][:3] == [0xB0, 0x01, 0x00]
    assert results(can_port, I)[-1].state == ResultState.NONE


def test_error_counters_hidden_without_error_mask_reporting(service, can_port, timer):
    service.start()
    command(can_port, service, 0x3F)
    can_port.clear()
    run_for(service, timer, 0.101)
    assert all(m.state == ResultState.NONE for m in results(can_port, I))
    command(can_port, service, 0x41, 0x0F)
    assert responses(can_port)[-1][:3] == [0x81, 0x0F, 0x01]


def test_measurement_error_counter_reported_with_mask(service, can_port, timer):
    service.device.measurement_errors.increment(0x06)  # Vref
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x20, 0x22, 0x00, 0x14)
    run_mode(can_port, service)
    run_for(service, timer, 0.021)
    assert results(can_port, I)[-1].state & ResultState.ANY_MEASUREMENT_ERROR


# ----------------------------------------------------------------------- log data


def test_log_data_counts_charge_runtime_and_extremes(can_port, timer):
    service = EmulatorService(can_port, timer, cfg())
    service.set_manual_current(10_000)
    service.set_temperature(30.0)
    service.start()
    run_for(service, timer, 10.0)
    service.set_manual_current(-20_000)
    service.set_temperature(-5.0)
    run_for(service, timer, 5.0)
    book = service.device.log_overall
    assert book.value(0x03) == pytest.approx(100, abs=1)  # As discharging
    assert book.value(0x02) == pytest.approx(100, abs=1)  # As charging
    assert book.value(0x01) == pytest.approx(0, abs=1)
    assert book.value(0x10) == 14  # runtime overall (s), int, 15 s minus the ramp sample
    assert (book.value(0x21), book.value(0x22)) == (10, -20)  # current max/min (A)
    assert (book.value(0x29), book.value(0x2A)) == (300, -50)  # temperature max/min (0.1 degC)
    command(can_port, service, 0x42, 0x03)
    assert responses(can_port)[-1][:2] == [0x82, 0x03]


def test_log_charge_counters_only_while_as_result_enabled(can_port, timer):
    service = EmulatorService(can_port, timer, IVTConfig(startup_time_ms=0))
    service.set_manual_current(10_000)
    service.start()
    run_for(service, timer, 5.0)
    assert service.device.log_overall.value(0x01) == 0
    assert service.device.log_overall.value(0x10) >= 4


def test_stop_mode_does_not_integrate_charge(service, can_port, timer):
    service.set_manual_current(10_000)
    service.start()
    run_for(service, timer, 1.0)
    before = service.snapshot().reading.charge_as
    stop_mode(can_port, service)
    run_for(service, timer, 5.0)
    run_mode(can_port, service)
    run_for(service, timer, 0.001)
    assert service.snapshot().reading.charge_as == pytest.approx(before, abs=0.3)


def test_channels_off_in_snapshot_settings(service, can_port):
    service.start()
    stop_mode(can_port, service)
    command(can_port, service, 0x26, 0x00, 0x00, 0x00)
    assert service.snapshot().settings.channel(Mux.AS).mode is TriggerMode.DISABLED
