"""EmulatorService — the emulated IVT-S: power, start-up, result scheduling and requests.

Depends only on ports (CanBusPort, TimerPort) and the domain. Thread-safe: the
transmission worker calls tick() while the GUI thread calls setters/snapshot().

Behaviour modelled on the real sensor (datasheet 1.03):
  * start() = power on. The sensor is silent for its start-up time (5.1), then
    sends the alive message (9) and, in RUN, the first result one measurement
    interval later. stop() = power off: no frames, commands are not answered.
  * Each result is the average current over its measurement interval (4.1),
    saturated at the overcurrent range; state bit 1 while the extended range is
    in use, with the 5 % return hysteresis (4.2). OCS (bit 0) follows the
    overcurrent thresholds. Bits 2/3 follow the error counters when error-mask
    reporting is enabled (8.4); injected flags are always OR-ed in.
  * Restart commands: silent for the start-up time, then alive; each counts an
    "Error Reset Watchdog" system error (8.5).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field, replace

from isascale.application.bms_requests import (
    CommandOutcome,
    DeviceState,
    HandleBmsRequestsUseCase,
    RestartKind,
)
from isascale.application.sources import ConstantSource, CurrentSource
from isascale.domain import ivt_protocol as proto
from isascale.domain.accumulator import BatteryStateCounter
from isascale.domain.models import (
    EMULATED_CHANNELS,
    INT32_MAX,
    INT32_MIN,
    Bitrate,
    BusState,
    BusStatus,
    CANFrame,
    IVTConfig,
    MessageCounter,
    Mux,
    OperationMode,
    ResultState,
    SensorReading,
    SensorSettings,
    TriggerMode,
)
from isascale.domain.sensor_state import (
    SYSTEM_ERROR_RESET_WATCHDOG,
    TEMPERATURE_MAX_C,
    TEMPERATURE_MIN_C,
    LogSample,
    OcDetector,
    RangeTracker,
)
from isascale.ports.can_port import CanBusError, CanBusPort, CanConnectionError
from isascale.ports.timer_port import TimerPort

# Max command frames drained from the RX queue per tick (bounds tick duration).
MAX_RX_PER_TICK = 16
# When nothing is scheduled (powered off, booting, STOP mode) poll RX at this interval.
IDLE_POLL_S = 0.010
# Window used to compute the measured current-result rate.
RATE_WINDOW_S = 1.0


@dataclass(frozen=True)
class EmulatorSnapshot:
    """Read-only view for the GUI / CLI, taken under the service lock."""

    running: bool
    mode: OperationMode
    elapsed_s: float
    reading: SensorReading
    charge_ah: float
    bus_status: BusStatus
    measured_current_rate_hz: float
    frames_sent: int
    send_errors: int
    last_error: str
    source_name: str
    source_progress: float | None
    booting: bool = False
    settings: SensorSettings = field(default_factory=SensorSettings)


@dataclass
class _Channel:
    """One cyclic result channel with its period and next due time."""

    mux: Mux
    period_s: float
    next_due_s: float


class EmulatorService:
    def __init__(
        self,
        can: CanBusPort,
        timer: TimerPort,
        config: IVTConfig | None = None,
        request_handler: HandleBmsRequestsUseCase | None = None,
    ) -> None:
        self._can = can
        self._timer = timer
        self._config = config or IVTConfig()
        self._requests = request_handler or HandleBmsRequestsUseCase()
        self._lock = threading.RLock()
        settings = self._config.to_settings()
        self._device = DeviceState(
            serial_number=self._config.serial_number,
            nominal_range=self._config.nominal_range,
            bitrate=self._config.bitrate,
            stored=settings,
            active=settings,
            mode=settings.startup_mode,
        )

        self._running = False
        self._boot_end_s: float | None = None
        self._pending_restart: RestartKind | None = None
        self._pending_bitrate: Bitrate | None = None
        self._source: CurrentSource = ConstantSource(0.0)
        self._source_t0 = 0.0
        self._start_t = 0.0
        self._temperature_c = 25.0
        self._extra_state = ResultState.NONE
        self._accumulator = BatteryStateCounter()
        self._range = RangeTracker(self._config.nominal_range)
        self._oc = OcDetector()
        self._last_current_ma = 0
        self._last_sample_t: float | None = None
        self._window_mas = 0.0  # integral of the current since the last I result, mA*s
        self._window_s = 0.0
        self._frames_sent = 0
        self._send_errors = 0
        self._last_error = ""
        self._last_send_ok = True
        self._current_tx_times: deque[float] = deque()
        self._channels: list[_Channel] = []
        self._counters = {mux: MessageCounter() for mux in EMULATED_CHANNELS}
        self._delayed: list[tuple[float, CANFrame]] = []
        self._triggers: list[tuple[float, Mux]] = []

    # ------------------------------------------------------------------ config

    @property
    def config(self) -> IVTConfig:
        return self._config

    @property
    def device(self) -> DeviceState:
        """Internal sensor state (tests / diagnostics). Not thread-safe to mutate."""
        return self._device

    def update_config(self, config: IVTConfig) -> None:
        """Replace the configuration (= reprogram the sensor's memory); only allowed while stopped."""
        with self._lock:
            if self._running:
                raise RuntimeError("stop the emulator before changing its configuration")
            self._config = config
            settings = config.to_settings()
            device = self._device
            device.serial_number = config.serial_number
            device.nominal_range = config.nominal_range
            device.bitrate = config.bitrate
            device.stored = device.active = settings
            device.mode = settings.startup_mode
            self._range = RangeTracker(config.nominal_range)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def mode(self) -> OperationMode:
        return self._device.mode

    # ------------------------------------------------------------ live inputs

    def set_current_source(self, source: CurrentSource) -> None:
        """Swap the current source; its elapsed time restarts at 0."""
        with self._lock:
            self._source = source
            self._source_t0 = self._timer.now()

    @property
    def current_source(self) -> CurrentSource:
        return self._source

    def set_manual_current(self, current_ma: float) -> None:
        """Set a fixed current. Reuses the active ConstantSource (no time reset)."""
        with self._lock:
            if isinstance(self._source, ConstantSource):
                self._source.current_ma = float(current_ma)
            else:
                self.set_current_source(ConstantSource(current_ma))

    def set_temperature(self, temperature_c: float) -> None:
        with self._lock:
            self._temperature_c = float(temperature_c)

    def set_state_flags(self, flags: ResultState) -> None:
        """Fault injection: extra IVT_Result_state bits OR-ed into every result."""
        with self._lock:
            self._extra_state = ResultState(int(flags) & 0xF)

    def reset_charge(self, initial_as: float = 0.0) -> None:
        with self._lock:
            self._accumulator.reset(initial_as)

    # --------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Power the sensor on. Requires a connected CAN port."""
        with self._lock:
            if self._running:
                return
            if not self._can.is_connected:
                raise CanConnectionError("CAN bus not connected")
            now = self._timer.now()
            self._start_t = now
            self._source_t0 = now
            self._frames_sent = 0
            self._send_errors = 0
            self._last_error = ""
            self._last_send_ok = True
            self._current_tx_times.clear()
            self._running = True
            self._begin_boot(now, None)

    def stop(self) -> None:
        """Power the sensor off: pending responses, triggers and the boot are dropped."""
        with self._lock:
            self._running = False
            self._boot_end_s = None
            self._channels = []
            self._delayed.clear()
            self._triggers.clear()
            self._current_tx_times.clear()

    def _begin_boot(self, now: float, restart: RestartKind | None, bitrate: Bitrate | None = None) -> None:
        self._channels = []
        self._delayed.clear()
        self._triggers.clear()
        self._pending_restart = restart
        self._pending_bitrate = bitrate
        self._boot_end_s = now + self._config.startup_time_ms / 1000.0
        if self._config.startup_time_ms == 0:
            self._finish_boot(now)

    def _finish_boot(self, now: float) -> None:
        device = self._device
        if self._pending_restart is RestartKind.TO_DEFAULT:
            device.stored = SensorSettings()
        if self._pending_bitrate is not None:
            self._switch_bitrate(self._pending_bitrate)
        device.active = device.stored
        device.mode = device.active.startup_mode
        device.oc_test_end_s = 0.0
        device.store_busy_until_s = 0.0
        self._boot_end_s = None
        self._pending_restart = self._pending_bitrate = None
        for counter in self._counters.values():
            counter.reset()
        self._range.reset()
        self._oc.reset()
        if self._config.send_alive_on_start:
            self._send(proto.alive_frame(device.serial_number, device.active.command_id, device.active.response_id))
        self._resume_measurement(now)

    def _switch_bitrate(self, bitrate: Bitrate) -> None:
        """RESTART_to_Bitrate: the bitrate is stored and the sensor comes back at the new speed."""
        self._device.bitrate = bitrate
        self._config = replace(self._config, bitrate=bitrate)
        try:
            self._can.disconnect()
            self._can.connect(self._config.channel, bitrate)
        except CanBusError as exc:
            self._last_error = str(exc)

    def _resume_measurement(self, now: float) -> None:
        """(Re)start measuring: schedule the cyclic channels, drop the time references."""
        self._triggers.clear()
        self._last_sample_t = None
        self._window_mas = self._window_s = 0.0
        self._accumulator.reset(self._accumulator.charge_as)
        self._channels = []
        if self._device.mode is not OperationMode.RUN:
            return
        for mux in EMULATED_CHANNELS:
            config = self._device.active.channel(mux)
            if config.mode is TriggerMode.CYCLIC:
                period = config.cycle_ms / 1000.0
                self._channels.append(_Channel(mux, period, now + period))

    # -------------------------------------------------------------------- tick

    def tick(self) -> float:
        """Run one scheduler step; return the absolute time of the next deadline.

        Never raises on bus errors: they are counted and exposed in snapshot().
        """
        with self._lock:
            now = self._timer.now()
            if not self._running:
                self._drain_rx()
                return now + IDLE_POLL_S
            if self._boot_end_s is not None:
                self._drain_rx()
                if now < self._boot_end_s:
                    return min(self._boot_end_s, now + IDLE_POLL_S)
                self._finish_boot(now)
            self._poll_requests(now)
            if self._boot_end_s is not None:  # a restart command was received
                return min(self._boot_end_s, now + IDLE_POLL_S)
            self._send_due_responses(now)
            if self._device.mode is OperationMode.RUN:
                self._sample(now)
                self._send_due_results(now)
            return self._next_deadline(now)

    def _next_deadline(self, now: float) -> float:
        deadlines = [c.next_due_s for c in self._channels]
        deadlines += [due for due, _ in self._delayed] + [due for due, _ in self._triggers]
        return min(deadlines) if deadlines else now + IDLE_POLL_S

    def _send_due_results(self, now: float) -> None:
        for channel in self._channels:
            if now >= channel.next_due_s:
                self._send_result(channel.mux, now)
                channel.next_due_s += channel.period_s
                # Fell behind by more than one period: resync instead of bursting.
                if channel.next_due_s <= now:
                    channel.next_due_s = now + channel.period_s
        due = [mux for t, mux in self._triggers if now >= t]
        self._triggers = [(t, mux) for t, mux in self._triggers if now < t]
        for mux in due:
            self._send_result(mux, now)

    def _send_due_responses(self, now: float) -> None:
        due = [frame for t, frame in self._delayed if now >= t]
        self._delayed = [(t, frame) for t, frame in self._delayed if now < t]
        for frame in due:
            self._send(frame)

    # ------------------------------------------------------------- measurement

    def _sample(self, now: float) -> None:
        raw = round(self._source.current_at(now - self._source_t0))
        current = self._range.clamp(max(INT32_MIN, min(INT32_MAX, raw)))
        dt = 0.0 if self._last_sample_t is None else now - self._last_sample_t
        self._window_mas += (self._last_current_ma + current) / 2.0 * dt
        self._window_s += dt
        self._last_current_ma = current
        self._last_sample_t = now
        self._accumulator.update(current, now)
        in_extended = self._range.update(current)
        settings = self._device.active
        self._oc.update(current, settings.oc_positive, settings.oc_negative)
        sample = LogSample(
            current_ma=current,
            temperature_c=self._temperature_c,
            dt_s=dt,
            current_in_range=not in_extended,
            oc_positive=self._oc.positive,
            oc_negative=self._oc.negative,
            charge_counter_active=settings.channel(Mux.AS).mode is not TriggerMode.DISABLED,
        )
        self._device.log_overall.update(sample)
        self._device.log_since_reset.update(sample)

    def _common_state(self) -> ResultState:
        state = self._extra_state
        if self._oc.active:
            state |= ResultState.OCS
        if self._device.active.error_mask_reporting:
            if self._device.measurement_errors.any:
                state |= ResultState.ANY_MEASUREMENT_ERROR
            if self._device.system_errors.any:
                state |= ResultState.SYSTEM_ERROR
        return state

    def _current_state(self) -> ResultState:
        state = self._common_state()
        if self._range.extended:
            state |= ResultState.OUT_OF_RANGE
        return state

    def _temperature_state(self) -> ResultState:
        state = self._common_state()
        if not TEMPERATURE_MIN_C <= self._temperature_c <= TEMPERATURE_MAX_C:
            state |= ResultState.OUT_OF_RANGE
        return state

    def _take_average_current(self) -> int:
        """Mean current over the measurement interval since the last I result (datasheet 4.1)."""
        value = round(self._window_mas / self._window_s) if self._window_s > 0 else self._last_current_ma
        self._window_mas = self._window_s = 0.0
        return value

    def _result_value(self, mux: Mux) -> tuple[int, ResultState]:
        if mux is Mux.I:
            return self._take_average_current(), self._current_state()
        if mux is Mux.T:
            return round(self._temperature_c * 10), self._temperature_state()
        return self._accumulator.charge_as_int32, self._common_state()

    def _send_result(self, mux: Mux, now: float) -> None:
        settings = self._device.active
        value, state = self._result_value(mux)
        frame = proto.result_frame(
            settings.result_ids[mux], mux, value, self._counters[mux].next(), state, settings.channel(mux)
        )
        if self._send(frame) and mux is Mux.I:
            self._record_current_tx(now)

    def _send(self, frame: CANFrame) -> bool:
        try:
            self._can.send_frame(frame)
        except CanBusError as exc:
            self._send_errors += 1
            self._last_error = str(exc)
            self._last_send_ok = False
            return False
        self._frames_sent += 1
        self._last_send_ok = True
        return True

    def _record_current_tx(self, now: float) -> None:
        self._current_tx_times.append(now)
        while self._current_tx_times and now - self._current_tx_times[0] > RATE_WINDOW_S:
            self._current_tx_times.popleft()

    # ---------------------------------------------------------------- requests

    def _drain_rx(self) -> None:
        """Powered off or booting: frames on the bus are not processed."""
        if not self._can.is_connected:
            return
        for _ in range(MAX_RX_PER_TICK):
            try:
                if self._can.receive_frame(0.0) is None:
                    return
            except CanBusError as exc:
                self._last_error = str(exc)
                return

    def _poll_requests(self, now: float) -> None:
        if not self._can.is_connected:
            return
        for _ in range(MAX_RX_PER_TICK):
            try:
                frame = self._can.receive_frame(0.0)
            except CanBusError as exc:
                self._last_error = str(exc)
                return
            if frame is None:
                return
            outcome = self._requests.handle(frame, self._device, now)
            if outcome is None:
                continue
            self._apply(outcome, now)
            if outcome.restart is not None:
                return  # the sensor restarted: frames still queued are handled after the boot

    def _apply(self, outcome: CommandOutcome, now: float) -> None:
        for response in outcome.responses:
            self._send(response)
        for delay, frame in outcome.delayed:
            self._delayed.append((now + delay, frame))
        if outcome.mode_changed:
            self._resume_measurement(now)
        for mux in EMULATED_CHANNELS:
            config = self._device.active.channel(mux)
            if outcome.trigger_bits & (1 << mux) and config.mode is TriggerMode.TRIGGERED:
                self._triggers.append((now + config.cycle_ms / 1000.0, mux))
        if outcome.restart is not None:
            self._device.system_errors.increment(SYSTEM_ERROR_RESET_WATCHDOG)
            self._begin_boot(now, outcome.restart, outcome.new_bitrate)

    # ---------------------------------------------------------------- snapshot

    def measured_current_rate_hz(self) -> float:
        with self._lock:
            times = self._current_tx_times
            if len(times) < 2:
                return 0.0
            span = times[-1] - times[0]
            return (len(times) - 1) / span if span > 0 else 0.0

    def snapshot(self) -> EmulatorSnapshot:
        with self._lock:
            now = self._timer.now()
            elapsed_source = now - self._source_t0
            status = self._can.get_bus_status()
            if status.state is BusState.BUS_OK and not self._last_send_ok:
                status = replace(status, state=BusState.WARNING)
            return EmulatorSnapshot(
                running=self._running,
                mode=self._device.mode,
                elapsed_s=(now - self._start_t) if self._running else 0.0,
                reading=SensorReading(
                    current_ma=self._last_current_ma,
                    temperature_c=self._temperature_c,
                    charge_as=self._accumulator.charge_as,
                    state=self._current_state(),
                ),
                charge_ah=self._accumulator.charge_ah,
                bus_status=status,
                measured_current_rate_hz=self.measured_current_rate_hz(),
                frames_sent=self._frames_sent,
                send_errors=self._send_errors,
                last_error=self._last_error,
                source_name=self._source.name,
                source_progress=self._source.progress(elapsed_source),
                booting=self._boot_end_s is not None,
                settings=self._device.active,
            )
