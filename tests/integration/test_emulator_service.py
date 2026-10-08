"""EmulatorService + use cases driven with FakeTimer and FakeCanPort (deterministic, no bus, no threads)."""

from __future__ import annotations

import pytest
from fakes import FakeCanPort, FakeProfileReader, FakeTimer, run_for

from isascale.application import emulator_service as svc_mod
from isascale.application.emulator_service import EmulatorService
from isascale.application.sources import ConstantSource, ProfileSource
from isascale.application.use_cases import RunCsvProfileEmulationUseCase, RunManualEmulationUseCase
from isascale.domain import ivt_protocol as proto
from isascale.domain.models import (
    BusState,
    CurrentProfile,
    IVTConfig,
    NominalRange,
    OperationMode,
    ResultState,
)
from isascale.ports.can_port import CanConnectionError, CanTransmitError
from isascale.ports.profile_port import ProfileFormatError

I, T, AS, RESP = 0x521, 0x525, 0x527, 0x511


def decoded(port: FakeCanPort, can_id: int) -> list[proto.ResultMessage]:
    return [proto.decode_result(f.data) for f in port.frames(can_id)]


def counters(port: FakeCanPort, can_id: int) -> list[int]:
    return [m.counter for m in decoded(port, can_id)]


def periods(port: FakeCanPort, can_id: int) -> list[float]:
    ts = port.times(can_id)
    return [b - a for a, b in zip(ts, ts[1:])]


# ------------------------------------------------------------------ lifecycle


def test_start_without_connection_raises(timer):
    service = EmulatorService(FakeCanPort(clock=timer, connected=False), timer)
    with pytest.raises(CanConnectionError):
        service.start()
    assert not service.running


def test_start_sends_alive_message_first(service, can_port):
    service.start()
    assert service.running
    assert can_port.sent[0].frame.arbitration_id == RESP
    assert list(can_port.sent[0].frame.data) == [0xBF, 0x04, 0x11, 0x00, 0x01, 0x23, 0x45, 0x00]


def test_alive_can_be_disabled(can_port, timer):
    service = EmulatorService(can_port, timer, IVTConfig(send_alive_on_start=False))
    service.start()
    assert can_port.frames(RESP) == []


def test_start_twice_is_noop(service, can_port, timer):
    service.start()
    service.tick()
    sent = len(can_port.sent)
    service.start()
    assert len(can_port.sent) == sent  # no second alive, counters untouched


def test_not_started_sends_no_results(service, can_port, timer):
    deadline = service.tick()
    assert deadline == pytest.approx(timer.now() + svc_mod.IDLE_POLL_S)
    assert can_port.sent == []


def test_stop_halts_transmission(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.1)
    service.stop()
    can_port.clear()
    run_for(service, timer, 0.5)
    assert can_port.sent == []
    assert not service.running


def test_update_config_while_running_raises(service):
    service.start()
    with pytest.raises(RuntimeError):
        service.update_config(IVTConfig(current_period_ms=10))


def test_update_config_while_stopped_applies_to_channels_and_requests(service, can_port, timer):
    service.update_config(IVTConfig(current_period_ms=10, nominal_range=NominalRange.A300, temperature_enabled=False))
    assert service.config.current_period_ms == 10
    service.start()
    run_for(service, timer, 0.095)
    assert len(can_port.frames(I)) == 10
    assert can_port.frames(T) == []
    can_port.push_rx(0x411, [0x79, 0, 0, 0, 0, 0, 0, 0])
    service.tick()
    assert list(can_port.frames(RESP)[-1].data[:4]) == [0xB9, 0x02, 0x12, 0xC0]


# --------------------------------------------------------------- periods / rate


def test_default_periods_per_channel_are_exact(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.995)
    assert len(can_port.frames(I)) == 50  # 20 ms
    assert len(can_port.frames(T)) == 10  # 100 ms
    assert len(can_port.frames(AS)) == 34  # 30 ms: 0, 30, ..., 990
    assert periods(can_port, I) == pytest.approx([0.020] * 49)
    assert periods(can_port, T) == pytest.approx([0.100] * 9)
    assert periods(can_port, AS) == pytest.approx([0.030] * 33)


@pytest.mark.parametrize(("i_ms", "t_ms", "as_ms"), [(2, 100, 100), (10, 50, 25), (100, 100, 100), (7, 13, 99)])
def test_configurable_periods(can_port, timer, i_ms, t_ms, as_ms):
    service = EmulatorService(
        can_port, timer, IVTConfig(current_period_ms=i_ms, temperature_period_ms=t_ms, charge_period_ms=as_ms)
    )
    service.start()
    run_for(service, timer, 0.9995)
    for can_id, period_ms in ((I, i_ms), (T, t_ms), (AS, as_ms)):
        assert len(can_port.frames(can_id)) == pytest.approx(1000 / period_ms, abs=1)
        assert periods(can_port, can_id) == pytest.approx([period_ms / 1000] * (len(can_port.frames(can_id)) - 1))


@pytest.mark.parametrize(("t_on", "as_on"), [(False, False), (True, False), (False, True)])
def test_disabled_channels_are_not_sent(can_port, timer, t_on, as_on):
    service = EmulatorService(can_port, timer, IVTConfig(temperature_enabled=t_on, charge_enabled=as_on))
    service.start()
    run_for(service, timer, 0.5)
    assert bool(can_port.frames(T)) is t_on
    assert bool(can_port.frames(AS)) is as_on
    assert len(can_port.frames(I)) == 25


def test_tick_returns_next_deadline(service, timer):
    service.start()
    t0 = timer.now()
    assert service.tick() == pytest.approx(t0 + 0.020)


def test_fall_behind_resyncs_instead_of_bursting(service, can_port, timer):
    service.start()
    service.tick()
    timer.advance(0.5)  # worker stalled for 500 ms
    service.tick()
    service.tick()
    assert len(can_port.frames(I)) == 2  # one catch-up frame, no burst of 25
    assert service.tick() == pytest.approx(timer.now() + 0.020)


def test_measured_current_rate_is_50hz_for_20ms(service, timer):
    service.start()
    run_for(service, timer, 2.0)
    assert service.snapshot().measured_current_rate_hz == pytest.approx(50.0, rel=0.01)


def test_measured_rate_zero_before_two_frames_and_after_stop(service, timer):
    assert service.measured_current_rate_hz() == 0.0
    service.start()
    service.tick()
    assert service.measured_current_rate_hz() == 0.0
    run_for(service, timer, 0.2)
    service.stop()
    assert service.measured_current_rate_hz() == 0.0


# ------------------------------------------------------------------- counters


def test_counters_wrap_0xf_to_0x0_over_more_than_16_cycles(service, can_port, timer):
    service.start()
    run_for(service, timer, 40 * 0.020 - 0.001)  # 40 I frames
    assert counters(can_port, I) == [n % 16 for n in range(40)]


def test_counters_are_independent_per_channel(service, can_port, timer):
    service.start()
    run_for(service, timer, 3.4)  # I: 170, T: 34, As: 114 frames
    for can_id in (I, T, AS):
        values = counters(can_port, can_id)
        assert len(values) > 16
        assert values == [n % 16 for n in range(len(values))], hex(can_id)
    assert len({len(counters(can_port, c)) for c in (I, T, AS)}) == 3  # really different sequences


def test_counter_continues_after_wrap_across_stop_start_starts_fresh(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.25)
    service.stop()
    can_port.clear()
    service.start()
    run_for(service, timer, 0.05)
    assert counters(can_port, I)[0] == 0


# ------------------------------------------------------------------- payloads


def test_manual_current_35a_payload(service, can_port, timer):
    service.set_manual_current(35_000)
    service.start()
    run_for(service, timer, 18 * 0.02 - 0.001)
    frames = can_port.frames(I)
    assert len(frames) == 18
    for n, frame in enumerate(frames):
        assert list(frame.data) == [0x00, n % 16, 0x00, 0x00, 0x88, 0xB8]


def test_manual_current_changes_in_real_time_without_time_reset(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.1)
    source = service.current_source
    service.set_manual_current(-20_000)
    assert service.current_source is source
    run_for(service, timer, 0.05)
    assert decoded(can_port, I)[-1].value == -20_000


def test_temperature_payload(service, can_port, timer):
    service.set_temperature(-12.34)
    service.start()
    service.tick()
    msg = decoded(can_port, T)[0]
    assert (msg.mux_id, msg.value) == (0x04, -123)


def test_charge_channel_integrates_current(service, can_port, timer):
    service.set_manual_current(10_000)  # 10 A
    service.start()
    run_for(service, timer, 2.0 + 0.001)
    snap = service.snapshot()
    assert snap.reading.charge_as == pytest.approx(20.0, abs=0.25)
    assert snap.charge_ah == pytest.approx(20.0 / 3600, abs=1e-4)
    last = decoded(can_port, AS)[-1]
    assert last.mux_id == 0x06
    assert last.value == pytest.approx(10.0 * (can_port.times(AS)[-1] - can_port.times(AS)[0]), abs=1)


def test_regen_current_decreases_charge(service, timer):
    service.set_manual_current(-50_000)
    service.start()
    run_for(service, timer, 1.0)
    assert service.snapshot().reading.charge_as == pytest.approx(-50.0, abs=1.5)


def test_reset_charge(service, can_port, timer):
    service.set_manual_current(100_000)
    service.start()
    run_for(service, timer, 1.0)
    service.reset_charge()
    assert service.snapshot().reading.charge_as == 0.0
    service.reset_charge(500.0)
    assert service.snapshot().reading.charge_as == 500.0


def test_charge_persists_across_stop_start_and_does_not_integrate_the_gap(service, timer):
    service.set_manual_current(10_000)
    service.start()
    run_for(service, timer, 1.0)
    before = service.snapshot().reading.charge_as
    service.stop()
    timer.advance(100.0)  # long pause while stopped
    service.start()
    service.tick()
    assert service.snapshot().reading.charge_as == pytest.approx(before, abs=0.25)


# --------------------------------------------------------------- state flags


def test_out_of_range_bit_only_above_nominal_range(service, can_port, timer):
    service.set_manual_current(1_000_000)  # exactly 1000 A nominal -> in range
    service.start()
    service.tick()
    assert decoded(can_port, I)[-1].state == ResultState.NONE
    service.set_manual_current(-1_000_001)
    run_for(service, timer, 0.021)
    assert decoded(can_port, I)[-1].state == ResultState.OUT_OF_RANGE
    assert service.snapshot().reading.state == ResultState.OUT_OF_RANGE


def test_out_of_range_bit_is_only_on_current_channel(service, can_port, timer):
    service.set_manual_current(1_500_000)
    service.start()
    service.tick()
    assert decoded(can_port, I)[0].state & ResultState.OUT_OF_RANGE
    assert decoded(can_port, T)[0].state == ResultState.NONE
    assert decoded(can_port, AS)[0].state == ResultState.NONE


@pytest.mark.parametrize(
    "flags",
    [ResultState.OCS, ResultState.ANY_MEASUREMENT_ERROR, ResultState.SYSTEM_ERROR, ResultState(0xD)],
)
def test_injected_flags_appear_in_every_result(service, can_port, timer, flags):
    service.set_state_flags(flags)
    service.start()
    run_for(service, timer, 0.2)
    for can_id in (I, T, AS):
        assert all(m.state == flags for m in decoded(can_port, can_id))
        assert all(f.data[1] >> 4 == int(flags) for f in can_port.frames(can_id))


def test_injected_flags_combine_with_out_of_range(service, can_port, timer):
    service.set_state_flags(ResultState.OCS)
    service.set_manual_current(2_000_000)
    service.start()
    service.tick()
    assert decoded(can_port, I)[0].state == ResultState.OCS | ResultState.OUT_OF_RANGE


def test_injected_flags_are_masked_to_4_bits(service, can_port):
    service.set_state_flags(ResultState(0xF))
    service.set_state_flags(0x1F)  # type: ignore[arg-type]
    service.start()
    service.tick()
    assert decoded(can_port, I)[0].state == ResultState(0xF)


def test_clearing_injected_flags(service, can_port, timer):
    service.set_state_flags(ResultState.SYSTEM_ERROR)
    service.start()
    service.tick()
    service.set_state_flags(ResultState.NONE)
    run_for(service, timer, 0.03)
    assert decoded(can_port, I)[-1].state == ResultState.NONE


def test_current_saturates_to_int32(service, can_port):
    service.set_current_source(ConstantSource(1e12))
    service.start()
    service.tick()
    assert decoded(can_port, I)[0].value == 2**31 - 1


# ------------------------------------------------------------ BMS requests


def test_get_device_id_request_is_answered(service, can_port):
    service.start()
    can_port.clear()
    can_port.push_rx(0x411, [0x79, 0, 0, 0, 0, 0, 0, 0])
    service.tick()
    assert list(can_port.frames(RESP)[0].data) == [0xB9, 0x02, 0x3E, 0x80, 0x03, 0x01, 0x01, 0x00]


def test_requests_answered_even_when_not_started(service, can_port):
    can_port.push_rx(0x411, [0x7B, 0, 0, 0, 0, 0, 0, 0])
    service.tick()
    assert list(can_port.frames(RESP)[0].data) == [0xBB, 0x00, 0x01, 0x23, 0x45, 0, 0, 0]


def test_set_mode_stop_stops_results_but_keeps_answering(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.1)
    can_port.push_rx(0x411, [0x34, 0x00, 0x01, 0, 0, 0, 0, 0])
    service.tick()
    assert service.mode is OperationMode.STOP
    assert list(can_port.frames(RESP)[-1].data) == [0xB4, 0x00, 0x01, 0, 0, 0, 0, 0]
    can_port.clear()
    run_for(service, timer, 0.5)
    assert can_port.frames(I) == can_port.frames(T) == can_port.frames(AS) == []
    can_port.push_rx(0x411, [0x79, 0, 0, 0, 0, 0, 0, 0])
    service.tick()
    assert can_port.frames(RESP)[-1].data[0] == 0xB9
    assert service.snapshot().mode is OperationMode.STOP


def test_set_mode_run_resumes_results(service, can_port, timer):
    service.start()
    can_port.push_rx(0x411, [0x34, 0x00, 0x01])
    service.tick()
    can_port.clear()
    can_port.push_rx(0x411, [0x34, 0x01, 0x01])
    run_for(service, timer, 0.2)
    assert service.mode is OperationMode.RUN
    assert len(can_port.frames(I)) >= 9


def test_restart_resets_counters_and_sends_alive(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.25)
    assert counters(can_port, I)[-1] != 0
    can_port.clear()
    can_port.push_rx(0x411, [0x3F, 0, 0, 0, 0, 0, 0, 0])
    service.tick()
    assert can_port.sent[0].frame.data[0] == 0xBF
    for can_id in (I, T, AS):
        assert counters(can_port, can_id)[0] == 0


def test_restart_from_stop_returns_to_startup_run_mode(service, can_port, timer):
    service.start()
    can_port.push_rx(0x411, [0x34, 0x00, 0x01])
    service.tick()
    can_port.push_rx(0x411, [0x3F])
    service.tick()
    assert service.mode is OperationMode.RUN


def test_unknown_command_answered_with_0xff(service, can_port):
    can_port.push_rx(0x411, [0x31, 0x01, 0, 0, 0, 0, 0, 0])
    service.tick()
    assert list(can_port.frames(RESP)[0].data) == [0xFF, 0x31, 0, 0, 0, 0, 0, 0]


def test_non_command_frames_ignored(service, can_port):
    can_port.push_rx(0x123, [0x79])
    can_port.push_rx(0x521, [0x79, 0, 0, 0, 0, 0])
    service.tick()
    assert can_port.sent == []
    assert not can_port.rx_queue


def test_rx_drain_is_bounded_per_tick(service, can_port):
    for _ in range(svc_mod.MAX_RX_PER_TICK + 4):
        can_port.push_rx(0x411, [0x79])
    service.tick()
    assert len(can_port.frames(RESP)) == svc_mod.MAX_RX_PER_TICK
    service.tick()
    assert len(can_port.frames(RESP)) == svc_mod.MAX_RX_PER_TICK + 4


def test_startup_mode_stop_start_sends_no_results(can_port, timer):
    from isascale.application.bms_requests import HandleBmsRequestsUseCase

    cfg = IVTConfig()
    service = EmulatorService(can_port, timer, cfg, HandleBmsRequestsUseCase(cfg, startup_mode=OperationMode.STOP))
    service.start()
    run_for(service, timer, 0.2)
    assert service.mode is OperationMode.STOP
    assert can_port.frames(I) == []


# ---------------------------------------------------------------- bus failures


def test_tx_errors_are_counted_not_raised(service, can_port, timer):
    service.start()
    can_port.tx_always_fail = True
    run_for(service, timer, 0.2)  # must not raise
    snap = service.snapshot()
    assert snap.send_errors >= 10 + 2 + 7
    assert "TX" in snap.last_error
    assert snap.running


def test_tx_error_reports_warning_while_port_says_ok(service, can_port, timer):
    service.start()
    can_port.tx_failures = 1
    service.tick()  # first send (I) fails, T and As ok -> last send ok
    can_port.tx_always_fail = True
    run_for(service, timer, 0.021)
    assert service.snapshot().bus_status.state is BusState.WARNING


def test_service_recovers_after_tx_errors(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.1)
    sent_before = service.snapshot().frames_sent
    can_port.tx_always_fail = True
    run_for(service, timer, 0.1)
    errors = service.snapshot().send_errors
    assert errors > 0
    can_port.tx_always_fail = False
    can_port.clear()
    run_for(service, timer, 0.2)
    snap = service.snapshot()
    assert snap.send_errors == errors  # no new errors
    assert snap.frames_sent > sent_before
    assert snap.bus_status.state is BusState.BUS_OK
    assert len(can_port.frames(I)) == 10  # normal rate again
    assert periods(can_port, I) == pytest.approx([0.02] * 9)


def test_failed_frames_are_not_counted_in_rate_or_frames_sent(service, can_port, timer):
    service.start()
    sent_after_alive = service.snapshot().frames_sent
    can_port.tx_always_fail = True
    run_for(service, timer, 0.5)
    snap = service.snapshot()
    assert snap.frames_sent == sent_after_alive
    assert snap.measured_current_rate_hz == 0.0


@pytest.mark.parametrize("state", [BusState.WARNING, BusState.BUS_OFF])
def test_bus_status_from_port_is_reported(service, can_port, timer, state):
    service.start()
    can_port.state_override = state
    can_port.tx_always_fail = state is BusState.BUS_OFF
    run_for(service, timer, 0.1)
    assert service.snapshot().bus_status.state is state


def test_bus_off_then_recovery(service, can_port, timer):
    service.start()
    can_port.state_override = BusState.BUS_OFF
    can_port.tx_always_fail = True
    run_for(service, timer, 0.1)
    assert service.snapshot().bus_status.state is BusState.BUS_OFF
    can_port.state_override = None
    can_port.tx_always_fail = False
    run_for(service, timer, 0.1)
    assert service.snapshot().bus_status.state is BusState.BUS_OK


def test_disconnect_during_run_does_not_raise(service, can_port, timer):
    service.start()
    run_for(service, timer, 0.1)
    can_port.disconnect()
    run_for(service, timer, 0.2)  # sends raise CanConnectionError internally
    snap = service.snapshot()
    assert snap.send_errors > 0
    assert snap.bus_status.state is BusState.DISCONNECTED
    assert snap.running


def test_reconnect_after_disconnect_resumes(service, can_port, timer):
    service.start()
    can_port.disconnect()
    run_for(service, timer, 0.1)
    can_port.connect("0", service.config.bitrate)
    can_port.clear()
    run_for(service, timer, 0.1)
    assert len(can_port.frames(I)) == 5


def test_rx_error_is_recorded_not_raised(service, can_port):
    service.start()
    can_port.rx_error = CanTransmitError("rx exploded")
    service.tick()
    assert service.snapshot().last_error == "rx exploded"
    assert service.snapshot().send_errors == 0


def test_send_error_resets_counters_on_next_start(service, can_port, timer):
    service.start()
    can_port.tx_always_fail = True
    run_for(service, timer, 0.1)
    service.stop()
    can_port.tx_always_fail = False
    service.start()
    snap = service.snapshot()
    assert (snap.send_errors, snap.last_error) == (0, "")


# ------------------------------------------------------------------- snapshot


def test_snapshot_fields(service, timer):
    snap = service.snapshot()
    assert not snap.running and snap.elapsed_s == 0.0
    assert snap.source_name == "manual" and snap.source_progress is None
    service.set_manual_current(1234)
    service.set_temperature(31.5)
    service.start()
    run_for(service, timer, 0.5)
    snap = service.snapshot()
    assert snap.running
    assert snap.mode is OperationMode.RUN
    assert snap.elapsed_s == pytest.approx(0.5)
    assert snap.reading.current_ma == 1234
    assert snap.reading.temperature_c == 31.5
    assert snap.frames_sent == 1 + 25 + 5 + 17
    assert snap.bus_status.tx_count == snap.frames_sent


# --------------------------------------------------------- manual <-> profile


@pytest.fixture
def ramp() -> CurrentProfile:
    return CurrentProfile("ramp", ((0.0, 0.0), (1.0, 100_000.0)))


def test_profile_source_drives_current_from_activation_time(service, can_port, timer, ramp):
    service.start()
    run_for(service, timer, 5.0)  # source time must restart at 0 on activation
    service.set_current_source(ProfileSource(ramp))
    can_port.clear()
    run_for(service, timer, 1.2)
    values = [m.value for m in decoded(can_port, I)]
    assert values[0] == 0
    assert values[25] == pytest.approx(50_000, abs=1)  # 0.5 s into the profile
    assert values[-1] == 100_000  # holds last value
    assert service.snapshot().source_progress == 1.0
    assert service.snapshot().source_name == "ramp"


def test_switch_profile_to_manual_and_back(service, can_port, timer, ramp):
    service.set_current_source(ProfileSource(ramp, loop=True))
    service.start()
    run_for(service, timer, 0.5)
    service.set_manual_current(7_000)  # profile active -> new ConstantSource
    assert isinstance(service.current_source, ConstantSource)
    run_for(service, timer, 0.05)
    assert decoded(can_port, I)[-1].value == 7_000
    t_activation = timer.now()
    service.set_current_source(ProfileSource(ramp))
    run_for(service, timer, 0.25)
    elapsed = can_port.times(I)[-1] - t_activation
    assert 0.2 < elapsed < 0.25
    assert decoded(can_port, I)[-1].value == pytest.approx(100_000 * elapsed, abs=1)


def test_manual_use_case(service, can_port, timer):
    uc = RunManualEmulationUseCase(service)
    uc.start(35_000)
    assert service.running
    run_for(service, timer, 0.05)
    uc.set_current(-1_000)
    run_for(service, timer, 0.05)
    assert decoded(can_port, I)[0].value == 35_000
    assert decoded(can_port, I)[-1].value == -1_000
    uc.stop()
    assert not service.running


def test_manual_use_case_start_without_connection_raises(timer):
    service = EmulatorService(FakeCanPort(clock=timer), timer)
    with pytest.raises(CanConnectionError):
        RunManualEmulationUseCase(service).start(1_000)


def test_profile_use_case_with_csv_reader(service, can_port, timer, ramp):
    reader = FakeProfileReader({"ramp.csv": ramp})
    uc = RunCsvProfileEmulationUseCase(service, reader)
    assert uc.profile is None
    assert uc.load("ramp.csv") is ramp
    uc.start(loop=False)
    assert service.running
    run_for(service, timer, 0.5)
    assert uc.progress() == pytest.approx(0.5)
    uc.stop()
    assert not service.running


def test_profile_use_case_propagates_format_error(service):
    uc = RunCsvProfileEmulationUseCase(service, FakeProfileReader())
    with pytest.raises(ProfileFormatError):
        uc.load("missing.csv")
    assert uc.profile is None


def test_profile_use_case_start_without_profile_raises(service):
    with pytest.raises(RuntimeError):
        RunCsvProfileEmulationUseCase(service, FakeProfileReader()).start()


@pytest.mark.parametrize(("key", "name"), [("wot", "WOT acceleration"), ("regen", "Regen braking"), ("idle", "Idle consumption")])
def test_profile_use_case_builtin(service, timer, key, name):
    uc = RunCsvProfileEmulationUseCase(service, FakeProfileReader())
    assert uc.use_builtin(key).name == name
    uc.start(loop=True)
    run_for(service, timer, 0.3)
    assert service.snapshot().source_name == name


def test_profile_use_case_unknown_builtin(service):
    with pytest.raises(KeyError):
        RunCsvProfileEmulationUseCase(service, FakeProfileReader()).use_builtin("drag")


def test_profile_use_case_start_while_running_switches_source_without_restart(service, can_port, timer, ramp):
    manual = RunManualEmulationUseCase(service)
    manual.start(5_000)
    run_for(service, timer, 0.1)
    alive_count = len(can_port.frames(RESP))
    uc = RunCsvProfileEmulationUseCase(service, FakeProfileReader())
    uc.use_builtin("regen")
    uc.start()
    run_for(service, timer, 0.1)
    assert len(can_port.frames(RESP)) == alive_count  # no new alive => no restart
    assert service.snapshot().source_name == "Regen braking"
    assert decoded(can_port, I)[-1].value == 80_000


def test_regen_profile_end_to_end_charge_goes_negative(service, timer):
    uc = RunCsvProfileEmulationUseCase(service, FakeProfileReader())
    uc.use_builtin("regen")
    uc.start()
    run_for(service, timer, 4.5)
    # cruise 0.5 s at 80 A (+40 As) is outweighed by ~-300 As of regen
    assert service.snapshot().reading.charge_as < -200
    assert uc.progress() == pytest.approx(1.0)


def test_fake_timer_is_used_not_wall_clock(service, timer):
    service.start()
    run_for(service, timer, 3600.0)  # one simulated hour runs instantly
    assert isinstance(timer, FakeTimer)
    assert service.snapshot().elapsed_s == pytest.approx(3600.0)
