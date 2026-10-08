"""EmulatorPresenter (MVP) tested without Qt: FakeView records everything pushed to it."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fakes import FakeCanPort, FakeProfileReader, FakeTimer, run_for

from isascale.application.builtin_profiles import BUILTIN_PROFILES
from isascale.application.emulator_service import EmulatorService
from isascale.application.use_cases import RunCsvProfileEmulationUseCase, RunManualEmulationUseCase
from isascale.domain import ivt_protocol as proto
from isascale.domain.models import Bitrate, BusState, BusStatus, CurrentProfile, IVTConfig, ResultState
from isascale.presentation.presenter import (
    CSV_PREFIX,
    ActiveMode,
    EmulatorPresenter,
    bus_status_vm,
    config_from_form,
    controls_vm,
    form_from_config,
    telemetry_vm,
)
from isascale.presentation.view_models import Tone


class FakeView:
    """Implements EmulatorView by recording the last value of every call."""

    def __init__(self) -> None:
        self.form = None
        self.options = None
        self.limit_a = None
        self.choices = []
        self.selected_key = None
        self.controls = None
        self.bus_status = None
        self.telemetry = None
        self.plot = None
        self.cursor = "unset"
        self.errors: list[str] = []
        self.infos: list[str] = []

    def set_connection_form(self, form, options):
        self.form, self.options = form, options

    def set_current_limit(self, limit_a):
        self.limit_a = limit_a

    def set_profile_choices(self, choices, selected_key):
        self.choices, self.selected_key = list(choices), selected_key

    def show_controls(self, vm):
        self.controls = vm

    def show_bus_status(self, vm):
        self.bus_status = vm

    def show_telemetry(self, vm):
        self.telemetry = vm

    def show_profile_plot(self, vm):
        self.plot = vm

    def set_profile_cursor(self, time_s):
        self.cursor = time_s

    def show_error(self, message):
        self.errors.append(message)

    def show_info(self, message):
        self.infos.append(message)


class FakeWorker:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self, timeout: float = 1.0) -> None:
        self.stopped += 1


CSV_PROFILE = CurrentProfile("bench", ((0.0, 0.0), (2.0, 100_000.0)))


@pytest.fixture
def port(timer: FakeTimer) -> FakeCanPort:
    return FakeCanPort(clock=timer, connected=False)


@pytest.fixture
def svc(port: FakeCanPort, timer: FakeTimer) -> EmulatorService:
    return EmulatorService(port, timer, IVTConfig())


@pytest.fixture
def view() -> FakeView:
    return FakeView()


@pytest.fixture
def worker() -> FakeWorker:
    return FakeWorker()


@pytest.fixture
def presenter(view, svc, port, worker) -> EmulatorPresenter:
    reader = FakeProfileReader({"bench.csv": CSV_PROFILE})
    p = EmulatorPresenter(
        view, svc, RunManualEmulationUseCase(svc), RunCsvProfileEmulationUseCase(svc, reader), port, worker
    )
    p.start()
    return p


@pytest.fixture
def connected(presenter, view) -> EmulatorPresenter:
    assert presenter.on_connect_toggled(view.form) is True
    return presenter


# ------------------------------------------------------------------- start / close


def test_start_pushes_initial_state_and_starts_worker(presenter, view, worker):
    assert view.form == form_from_config(IVTConfig())
    assert [label for label, _ in view.options.bitrates] == ["250 kbit/s", "500 kbit/s", "1 Mbit/s"]
    assert (view.options.period_min_ms, view.options.period_max_ms) == (1, 100)
    assert view.limit_a == pytest.approx(1200.0)  # 1000 A nominal x 1.2
    assert [c.key for c in view.choices] == list(BUILTIN_PROFILES)
    assert view.selected_key == "wot"
    assert view.plot is not None and view.plot.current_a[0] == pytest.approx(5.0)
    assert worker.started == 1
    assert view.controls == controls_vm(connected=False, running=False)
    assert view.bus_status.state_text == "DISCONNECTED"


def test_close_stops_everything_once(connected, view, port, worker, svc):
    connected.on_start_manual(10.0, 25.0)
    connected.on_close()
    connected.on_close()
    assert worker.stopped == 1
    assert port.disconnect_calls == 1
    assert not port.is_connected
    assert not svc.running


# ---------------------------------------------------------------------- connection


def test_connect_applies_form_and_reports(presenter, view, port, svc):
    form = replace(view.form, channel=" 1 ", bitrate=250_000, current_period_ms=10)
    assert presenter.on_connect_toggled(form) is True
    assert port.is_connected
    assert (port.channel, port.bitrate) == ("1", Bitrate.B250K)
    assert svc.config.current_period_ms == 10
    assert view.infos[-1] == "Connected to channel 1 @ 250 kbit/s"
    assert view.controls.connection_editable is False
    assert view.controls.connect_text == "Disconnect"
    assert view.controls.start_manual_enabled


def test_connect_with_invalid_form_shows_error(presenter, view, port):
    too_fast = replace(view.form, current_period_ms=1, temperature_period_ms=1, charge_period_ms=1)
    assert presenter.on_connect_toggled(too_fast) is False
    assert not port.is_connected
    assert view.errors[-1].startswith("Connect failed")


def test_connect_failure_from_port_shows_error(presenter, view, port):
    port.fail_connect = True
    assert presenter.on_connect_toggled(view.form) is False
    assert "injected connect failure" in view.errors[-1]


def test_toggle_while_connected_disconnects(connected, view, port, svc):
    connected.on_start_manual(5.0, 25.0)
    assert connected.on_connect_toggled(view.form) is True
    assert not port.is_connected
    assert not svc.running
    assert connected.active_mode is ActiveMode.NONE
    assert view.infos[-1] == "Disconnected"
    assert view.controls.connect_text == "Connect"


# ----------------------------------------------------------------------- emulation


def test_start_manual_without_connection_is_an_error(presenter, view, svc):
    assert presenter.on_start_manual(10.0, 25.0) is False
    assert not svc.running
    assert "Cannot start manual mode" in view.errors[-1]


def test_start_manual_sends_current_and_temperature(connected, svc, port, timer):
    assert connected.on_start_manual(35.0, 31.5) is True
    assert connected.active_mode is ActiveMode.MANUAL
    run_for(svc, timer, 0.1)
    assert proto.decode_result(port.frames(proto.RESULT_I_ID)[-1].data).value == 35_000
    assert proto.decode_result(port.frames(proto.RESULT_T_ID)[-1].data).value == 315


def test_current_change_forwarded_only_in_manual_mode(connected, svc, timer):
    connected.on_start_manual(1.0, 25.0)
    connected.on_current_changed(-20.0)
    run_for(svc, timer, 0.05)
    assert svc.snapshot().reading.current_ma == -20_000

    connected.on_start_profile(loop=False)
    source = svc.current_source
    connected.on_current_changed(99.0)
    assert svc.current_source is source  # profile not replaced by the slider


def test_current_change_ignored_when_stopped(connected, svc):
    connected.on_current_changed(50.0)
    assert not svc.running
    assert connected.active_mode is ActiveMode.NONE


def test_start_profile_and_progress_cursor(connected, view, svc, timer):
    assert connected.on_start_profile(loop=False) is True
    assert connected.active_mode is ActiveMode.PROFILE
    assert "WOT acceleration" in view.infos[-1]
    run_for(svc, timer, 3.0)
    connected.on_refresh()
    assert view.cursor == pytest.approx(3.0, abs=0.05)  # 6 s profile, half way


def test_cursor_hidden_outside_profile_mode(connected, view, svc, timer):
    connected.on_start_manual(1.0, 25.0)
    run_for(svc, timer, 0.1)
    connected.on_refresh()
    assert view.cursor is None


def test_start_profile_without_connection_is_an_error(presenter, view):
    assert presenter.on_start_profile(loop=True) is False
    assert "Cannot start profile" in view.errors[-1]


def test_stop(connected, view, svc):
    connected.on_start_manual(1.0, 25.0)
    connected.on_stop()
    assert not svc.running
    assert connected.active_mode is ActiveMode.NONE
    assert view.infos[-1] == "Stopped"
    assert view.controls.stop_enabled is False


@pytest.mark.parametrize(
    ("ocs", "meas", "sys_err", "expected"),
    [
        (False, False, False, ResultState.NONE),
        (True, False, False, ResultState.OCS),
        (False, True, False, ResultState.ANY_MEASUREMENT_ERROR),
        (False, False, True, ResultState.SYSTEM_ERROR),
        (True, True, True, ResultState.OCS | ResultState.ANY_MEASUREMENT_ERROR | ResultState.SYSTEM_ERROR),
    ],
)
def test_flags_mapping(connected, svc, ocs, meas, sys_err, expected):
    connected.on_flags_changed(ocs, meas, sys_err)
    assert svc.snapshot().reading.state == expected


def test_temperature_and_reset_charge(connected, svc, timer):
    connected.on_temperature_changed(-12.3)
    assert svc.snapshot().reading.temperature_c == pytest.approx(-12.3)
    connected.on_start_manual(100.0, -12.3)
    run_for(svc, timer, 1.0)
    assert svc.snapshot().reading.charge_as > 50
    connected.on_reset_charge()
    assert svc.snapshot().reading.charge_as == 0.0


# ------------------------------------------------------------------------ profiles


def test_select_builtin_profile_updates_plot(presenter, view):
    assert presenter.on_profile_selected("regen") is True
    assert min(view.plot.current_a) == pytest.approx(-120.0)
    assert view.cursor is None


def test_select_unknown_profile_is_an_error(presenter, view):
    assert presenter.on_profile_selected("nope") is False
    assert "Unknown profile" in view.errors[-1]


def test_load_csv_adds_and_selects_choice(presenter, view):
    assert presenter.on_csv_selected("bench.csv") is True
    assert view.selected_key == CSV_PREFIX + "bench.csv"
    assert view.choices[-1].label == "CSV: bench"
    assert [c.key for c in view.choices[: len(BUILTIN_PROFILES)]] == list(BUILTIN_PROFILES)
    assert view.plot.current_a == (0.0, 100.0)
    assert "2 points" in view.infos[-1]


def test_loading_same_csv_twice_does_not_duplicate(presenter, view):
    presenter.on_csv_selected("bench.csv")
    presenter.on_profile_selected("idle")
    assert presenter.on_profile_selected(CSV_PREFIX + "bench.csv") is True
    assert sum(c.key == CSV_PREFIX + "bench.csv" for c in view.choices) == 1


def test_bad_csv_shows_error(presenter, view):
    assert presenter.on_csv_selected("missing.csv") is False
    assert view.errors[-1].startswith("Profile error")


# ------------------------------------------------------------------------- refresh


def test_bus_error_shown_once(connected, view, svc, port, timer):
    connected.on_start_manual(1.0, 25.0)
    port.tx_always_fail = True
    run_for(svc, timer, 0.1)
    connected.on_refresh()
    connected.on_refresh()
    bus_errors = [e for e in view.errors if e.startswith("Bus error")]
    assert len(bus_errors) == 1
    assert view.bus_status.tone is Tone.WARNING


def test_refresh_survives_snapshot_failure(presenter, view, svc, mocker):
    mocker.patch.object(svc, "snapshot", side_effect=RuntimeError("boom"))
    presenter.on_refresh()
    assert view.errors[-1] == "Snapshot failed: boom"


# ------------------------------------------------------------------------- mappers


def test_form_config_round_trip():
    cfg = IVTConfig(channel="3", bitrate=Bitrate.B1M, current_period_ms=5, charge_enabled=False)
    assert config_from_form(IVTConfig(), form_from_config(cfg)) == cfg


def test_config_from_form_blank_channel_defaults_to_zero():
    form = replace(form_from_config(IVTConfig()), channel="  ")
    assert config_from_form(IVTConfig(), form).channel == "0"


def test_config_from_form_rejects_bad_bitrate():
    with pytest.raises(ValueError):
        config_from_form(IVTConfig(), replace(form_from_config(IVTConfig()), bitrate=125_000))


@pytest.mark.parametrize(
    ("state", "tone"),
    [
        (BusState.DISCONNECTED, Tone.NEUTRAL),
        (BusState.BUS_OK, Tone.OK),
        (BusState.WARNING, Tone.WARNING),
        (BusState.BUS_OFF, Tone.ERROR),
    ],
)
def test_bus_status_vm(state, tone):
    vm = bus_status_vm(BusStatus(state, tx_count=7, rx_count=2, tx_errors=1, detail="x"), 49.96)
    assert (vm.state_text, vm.tone) == (state.value, tone)
    assert vm.rate_text.strip() == "50.0 Hz"
    assert vm.counters_text == "7 / 2 / 1"
    assert vm.detail == "x"


def test_controls_vm():
    assert controls_vm(False, False) == controls_vm(connected=False, running=False)
    vm = controls_vm(connected=True, running=True)
    assert (vm.connection_editable, vm.connect_text, vm.connect_danger) == (False, "Disconnect", True)
    assert vm.start_manual_enabled and vm.start_profile_enabled and vm.stop_enabled


def test_telemetry_vm_idle_and_run(connected, svc, timer):
    idle = telemetry_vm(svc.snapshot())
    assert idle.mode.startswith("IDLE") and idle.mode_tone is Tone.DIM
    assert idle.state == "OK" and idle.state_tone is Tone.OK

    connected.on_start_manual(1500.0, 25.0)  # above 1000 A nominal -> OUT_OF_RANGE
    run_for(svc, timer, 0.1)
    vm = telemetry_vm(svc.snapshot())
    assert vm.mode.startswith("RUN") and vm.mode_tone is Tone.OK
    assert vm.current.strip() == "+1500.000"
    assert vm.state == "OUT_OF_RANGE" and vm.state_tone is Tone.WARNING
    assert vm.frames_tone is Tone.NORMAL
    assert vm.source == "manual"
