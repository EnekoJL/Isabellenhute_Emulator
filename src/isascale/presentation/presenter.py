"""EmulatorPresenter — all GUI logic (MVP, Passive View). No Qt imports.

The view forwards every user event to an on_* method here and only renders
what the presenter pushes through the EmulatorView protocol. The presenter
talks to the core through the service, the use cases and the CanBusPort.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import Protocol

from isascale.application.builtin_profiles import BUILTIN_PROFILES
from isascale.application.emulator_service import EmulatorService, EmulatorSnapshot
from isascale.application.use_cases import RunCsvProfileEmulationUseCase, RunManualEmulationUseCase
from isascale.domain.models import (
    MAX_CYCLE_MS,
    MIN_CYCLE_MS,
    Bitrate,
    BusState,
    BusStatus,
    CurrentProfile,
    IVTConfig,
    OperationMode,
    ResultState,
)
from isascale.ports.can_port import CanBusError, CanBusPort
from isascale.ports.profile_port import ProfileFormatError
from isascale.presentation.view import EmulatorView
from isascale.presentation.view_models import (
    BusStatusViewModel,
    ConnectionForm,
    ConnectionOptions,
    ControlsViewModel,
    PlotViewModel,
    ProfileChoice,
    TelemetryViewModel,
    Tone,
)

# Exceptions a user action may raise; shown to the user, never propagated.
USER_ERRORS = (CanBusError, ProfileFormatError, ValueError, RuntimeError, KeyError)
# Manual range = nominal range x this factor, to be able to trigger OUT_OF_RANGE.
CURRENT_RANGE_FACTOR = 1.2
CSV_PREFIX = "csv:"

BITRATE_OPTIONS = (("250 kbit/s", int(Bitrate.B250K)), ("500 kbit/s", int(Bitrate.B500K)), ("1 Mbit/s", int(Bitrate.B1M)))
BUS_TONES = {
    BusState.DISCONNECTED: Tone.NEUTRAL,
    BusState.BUS_OK: Tone.OK,
    BusState.WARNING: Tone.WARNING,
    BusState.BUS_OFF: Tone.ERROR,
}


class BackgroundWorker(Protocol):
    """The transmission worker as seen by the presenter (runs service.tick())."""

    def start(self) -> None: ...

    def stop(self, timeout: float = ...) -> None: ...


class ActiveMode(Enum):
    NONE = "none"
    MANUAL = "manual"
    PROFILE = "profile"


class EmulatorPresenter:
    def __init__(
        self,
        view: EmulatorView,
        service: EmulatorService,
        manual_uc: RunManualEmulationUseCase,
        profile_uc: RunCsvProfileEmulationUseCase,
        can_port: CanBusPort,
        worker: BackgroundWorker,
    ) -> None:
        self._view = view
        self._service = service
        self._manual_uc = manual_uc
        self._profile_uc = profile_uc
        self._can = can_port
        self._worker = worker
        self._active = ActiveMode.NONE
        self._last_error_shown = ""
        self._closed = False
        self._csv_choices: dict[str, str] = {}  # combo key -> label, CSVs loaded so far

    @property
    def active_mode(self) -> ActiveMode:
        return self._active

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Push the initial state to the view and start the worker.

        The worker also serves BMS requests while stopped, so it lives as long as the view.
        """
        config = self._service.config
        self._view.set_connection_form(
            form_from_config(config), ConnectionOptions(BITRATE_OPTIONS, MIN_CYCLE_MS, MAX_CYCLE_MS)
        )
        self._view.set_current_limit(int(config.nominal_range) * CURRENT_RANGE_FACTOR)
        choices = [ProfileChoice(key, factory().name) for key, factory in BUILTIN_PROFILES.items()]
        first = choices[0].key
        self._view.set_profile_choices(choices, first)
        self.on_profile_selected(first)
        self._worker.start()
        self.on_refresh()

    def on_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._service.stop()
        self._worker.stop()
        self._can.disconnect()

    # ------------------------------------------------------------- connection

    def on_connect_toggled(self, form: ConnectionForm) -> bool:
        """Connect with the form values, or disconnect if already connected."""
        if self._can.is_connected:
            self._service.stop()
            self._can.disconnect()
            self._active = ActiveMode.NONE
            self._view.show_info("Disconnected")
            self.on_refresh()
            return True
        try:
            config = config_from_form(self._service.config, form)
            self._service.stop()
            self._service.update_config(config)
            self._can.connect(config.channel, config.bitrate)
        except USER_ERRORS as exc:
            self._view.show_error(f"Connect failed: {exc}")
            self.on_refresh()
            return False
        self._view.show_info(f"Connected to channel {config.channel} @ {int(config.bitrate) // 1000} kbit/s")
        self.on_refresh()
        return True

    # -------------------------------------------------------------- emulation

    def on_start_manual(self, current_a: float, temperature_c: float) -> bool:
        try:
            self._service.set_temperature(temperature_c)
            self._manual_uc.start(current_a * 1000.0)
        except USER_ERRORS as exc:
            self._view.show_error(f"Cannot start manual mode: {exc}")
            return False
        self._active = ActiveMode.MANUAL
        self._view.show_info("Manual mode running")
        self.on_refresh()
        return True

    def on_start_profile(self, loop: bool) -> bool:
        try:
            self._profile_uc.start(loop=loop)
        except USER_ERRORS as exc:
            self._view.show_error(f"Cannot start profile: {exc}")
            return False
        self._active = ActiveMode.PROFILE
        self._view.show_info(f"Profile '{self._profile_uc.profile.name}' running")  # type: ignore[union-attr]
        self.on_refresh()
        return True

    def on_stop(self) -> None:
        self._service.stop()
        self._active = ActiveMode.NONE
        self._view.show_info("Stopped")
        self.on_refresh()

    def on_current_changed(self, current_a: float) -> None:
        # Only forwarded in manual mode: set_manual_current would replace a playing profile.
        if self._active is ActiveMode.MANUAL and self._service.running:
            self._manual_uc.set_current(current_a * 1000.0)

    def on_temperature_changed(self, temperature_c: float) -> None:
        self._service.set_temperature(temperature_c)

    def on_flags_changed(self, ocs: bool, measurement_error: bool, system_error: bool) -> None:
        flags = ResultState.NONE
        if ocs:
            flags |= ResultState.OCS
        if measurement_error:
            flags |= ResultState.ANY_MEASUREMENT_ERROR
        if system_error:
            flags |= ResultState.SYSTEM_ERROR
        self._service.set_state_flags(flags)

    def on_reset_charge(self) -> None:
        self._service.reset_charge()

    # ---------------------------------------------------------------- profile

    def on_profile_selected(self, key: str) -> bool:
        """Built-in key ('wot', ...) or CSV_PREFIX + path of a CSV loaded earlier."""
        if key.startswith(CSV_PREFIX):
            return self.on_csv_selected(key[len(CSV_PREFIX):])
        try:
            profile = self._profile_uc.use_builtin(key)
        except KeyError:
            self._view.show_error(f"Unknown profile '{key}'")
            return False
        self._show_profile(profile)
        return True

    def on_csv_selected(self, path: str) -> bool:
        try:
            profile = self._profile_uc.load(path)
        except ProfileFormatError as exc:
            self._view.show_error(f"Profile error: {exc}")
            return False
        self._view.set_profile_choices(self._choices_with_csv(path, profile), CSV_PREFIX + path)
        self._show_profile(profile)
        self._view.show_info(f"Loaded {profile.name} ({len(profile.points)} points, {profile.duration_s:.1f} s)")
        return True

    def _choices_with_csv(self, path: str, profile: CurrentProfile) -> list[ProfileChoice]:
        choices = [ProfileChoice(key, factory().name) for key, factory in BUILTIN_PROFILES.items()]
        self._csv_choices[CSV_PREFIX + path] = f"CSV: {profile.name}"
        choices += [ProfileChoice(key, label) for key, label in self._csv_choices.items()]
        return choices

    def _show_profile(self, profile: CurrentProfile) -> None:
        self._view.show_profile_plot(
            PlotViewModel(tuple(t for t, _ in profile.points), tuple(i / 1000.0 for _, i in profile.points))
        )
        self._view.set_profile_cursor(None)

    # ---------------------------------------------------------------- refresh

    def on_refresh(self) -> None:
        """Periodic (10 Hz): pull a snapshot and push all read-only view models."""
        try:
            snap = self._service.snapshot()
        except Exception as exc:  # noqa: BLE001 - the GUI must survive anything here
            self._view.show_error(f"Snapshot failed: {exc}")
            return
        connected = self._can.is_connected
        self._view.show_controls(controls_vm(connected, snap.running))
        self._view.show_bus_status(bus_status_vm(snap.bus_status, snap.measured_current_rate_hz))
        self._view.show_telemetry(telemetry_vm(snap))
        self._view.set_profile_cursor(self._cursor_time(snap))
        if snap.last_error and snap.last_error != self._last_error_shown:
            self._last_error_shown = snap.last_error
            self._view.show_error(f"Bus error: {snap.last_error}")

    def _cursor_time(self, snap: EmulatorSnapshot) -> float | None:
        profile = self._profile_uc.profile
        if self._active is not ActiveMode.PROFILE or profile is None or snap.source_progress is None:
            return None
        return profile.start_s + snap.source_progress * profile.duration_s


# --------------------------------------------------------------------- mappers
# Pure functions: domain/application data -> view models (unit-tested directly).


def form_from_config(config: IVTConfig) -> ConnectionForm:
    return ConnectionForm(
        channel=config.channel,
        bitrate=int(config.bitrate),
        current_period_ms=config.current_period_ms,
        temperature_period_ms=config.temperature_period_ms,
        charge_period_ms=config.charge_period_ms,
        temperature_enabled=config.temperature_enabled,
        charge_enabled=config.charge_enabled,
    )


def config_from_form(base: IVTConfig, form: ConnectionForm) -> IVTConfig:
    """Raises ValueError if the form is invalid (bad bitrate, period, > 1000 msg/s)."""
    return replace(
        base,
        channel=form.channel.strip() or "0",
        bitrate=Bitrate(int(form.bitrate)),
        current_period_ms=form.current_period_ms,
        temperature_period_ms=form.temperature_period_ms,
        charge_period_ms=form.charge_period_ms,
        temperature_enabled=form.temperature_enabled,
        charge_enabled=form.charge_enabled,
    )


def controls_vm(connected: bool, running: bool) -> ControlsViewModel:
    return ControlsViewModel(
        connection_editable=not connected,
        connect_text="Disconnect" if connected else "Connect",
        connect_danger=connected,
        start_manual_enabled=connected,
        start_profile_enabled=connected,
        stop_enabled=running,
    )


def bus_status_vm(status: BusStatus, rate_hz: float) -> BusStatusViewModel:
    return BusStatusViewModel(
        state_text=status.state.value,
        tone=BUS_TONES[status.state],
        rate_text=f"{rate_hz:6.1f} Hz",
        counters_text=f"{status.tx_count} / {status.rx_count} / {status.tx_errors}",
        detail=status.detail,
    )


def telemetry_vm(snap: EmulatorSnapshot) -> TelemetryViewModel:
    reading = snap.reading
    if not snap.running:
        mode, mode_tone = "IDLE", Tone.DIM
    elif snap.mode is OperationMode.RUN:
        mode, mode_tone = "RUN", Tone.OK
    else:
        mode, mode_tone = "STOP", Tone.WARNING
    state = reading.state
    state_names = [str(flag.name) for flag in ResultState if flag and flag in state] or ["OK"]
    progress = "" if snap.source_progress is None else f"  {snap.source_progress * 100:5.1f} %"
    return TelemetryViewModel(
        current=f"{reading.current_ma / 1000.0:+10.3f}",
        temperature=f"{reading.temperature_c:6.1f}",
        charge_as=f"{reading.charge_as:12.1f}",
        charge_ah=f"{snap.charge_ah:10.4f}",
        mode=f"{mode}  {snap.elapsed_s:7.1f} s",
        mode_tone=mode_tone,
        frames=f"{snap.frames_sent} / {snap.send_errors}",
        frames_tone=Tone.ERROR if snap.send_errors else Tone.NORMAL,
        state=" ".join(state_names),
        state_tone=Tone.WARNING if state else Tone.OK,
        source=f"{snap.source_name}{progress}",
    )
