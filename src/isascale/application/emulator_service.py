"""EmulatorService — orchestrates the cyclic send loop, clock, counters and requests.

Depends only on ports (CanBusPort, TimerPort) and the domain. Thread-safe: the
transmission worker calls tick() while the GUI thread calls setters/snapshot().
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Callable

from isascale.application.bms_requests import HandleBmsRequestsUseCase
from isascale.application.sources import ConstantSource, CurrentSource
from isascale.domain import ivt_protocol as proto
from isascale.domain.accumulator import BatteryStateCounter
from isascale.domain.models import (
    INT32_MAX,
    INT32_MIN,
    BusState,
    BusStatus,
    CANFrame,
    IVTConfig,
    MessageCounter,
    OperationMode,
    ResultState,
    SensorReading,
)
from isascale.ports.can_port import CanBusError, CanBusPort, CanConnectionError
from isascale.ports.timer_port import TimerPort

# Max command frames drained from the RX queue per tick (bounds tick duration).
MAX_RX_PER_TICK = 16
# When the service is idle (stopped or STOP mode) poll RX at this interval.
IDLE_POLL_S = 0.010
# Window used to compute the measured 0x521 rate.
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


@dataclass
class _Channel:
    """One cyclic result message with its own period, counter and next due time."""

    name: str
    period_s: float
    build: Callable[[int, ResultState], CANFrame]
    counter: MessageCounter = field(default_factory=MessageCounter)
    next_due_s: float = 0.0


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
        self._requests = request_handler or HandleBmsRequestsUseCase(self._config)
        self._lock = threading.RLock()

        self._running = False
        self._mode = OperationMode.RUN
        self._source: CurrentSource = ConstantSource(0.0)
        self._source_t0 = 0.0
        self._start_t = 0.0
        self._temperature_c = 25.0
        self._extra_state = ResultState.NONE
        self._accumulator = BatteryStateCounter()
        self._last_current_ma = 0
        self._frames_sent = 0
        self._send_errors = 0
        self._last_error = ""
        self._last_send_ok = True
        self._current_tx_times: deque[float] = deque()
        self._channels: list[_Channel] = []

    # ------------------------------------------------------------------ config

    @property
    def config(self) -> IVTConfig:
        return self._config

    def update_config(self, config: IVTConfig) -> None:
        """Replace the configuration; only allowed while stopped."""
        with self._lock:
            if self._running:
                raise RuntimeError("stop the emulator before changing its configuration")
            self._config = config
            self._requests.config = config

    @property
    def running(self) -> bool:
        return self._running

    @property
    def mode(self) -> OperationMode:
        return self._mode

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
        """Start cyclic transmission. Requires a connected CAN port."""
        with self._lock:
            if self._running:
                return
            if not self._can.is_connected:
                raise CanConnectionError("CAN bus not connected")
            now = self._timer.now()
            self._start_t = now
            self._source_t0 = now
            self._mode = self._requests.startup_mode
            self._frames_sent = 0
            self._send_errors = 0
            self._last_error = ""
            self._last_send_ok = True
            self._current_tx_times.clear()
            self._accumulator.reset(self._accumulator.charge_as)
            self._channels = self._build_channels(now)
            self._running = True
            if self._config.send_alive_on_start:
                self._send(proto.alive_frame(self._config.serial_number))

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._current_tx_times.clear()

    def _build_channels(self, now: float) -> list[_Channel]:
        cfg = self._config
        channels = [_Channel("I", cfg.current_period_ms / 1000.0, self._build_current, next_due_s=now)]
        if cfg.temperature_enabled:
            channels.append(_Channel("T", cfg.temperature_period_ms / 1000.0, self._build_temperature, next_due_s=now))
        if cfg.charge_enabled:
            channels.append(_Channel("As", cfg.charge_period_ms / 1000.0, self._build_charge, next_due_s=now))
        return channels

    # -------------------------------------------------------------------- tick

    def tick(self) -> float:
        """Run one scheduler step; return the absolute time of the next deadline.

        Never raises on bus errors: they are counted and exposed in snapshot().
        """
        with self._lock:
            now = self._timer.now()
            self._poll_requests(now)
            if not self._running or self._mode is OperationMode.STOP:
                return now + IDLE_POLL_S

            self._sample(now)
            for channel in self._channels:
                if now >= channel.next_due_s:
                    frame = channel.build(channel.counter.next(), self._extra_state)
                    if self._send(frame) and channel.name == "I":
                        self._record_current_tx(now)
                    channel.next_due_s += channel.period_s
                    # Fell behind by more than one period: resync instead of bursting.
                    if channel.next_due_s <= now:
                        channel.next_due_s = now + channel.period_s
            return min(c.next_due_s for c in self._channels)

    def _sample(self, now: float) -> None:
        elapsed = now - self._source_t0
        current = round(self._source.current_at(elapsed))
        self._last_current_ma = max(INT32_MIN, min(INT32_MAX, current))
        self._accumulator.update(self._last_current_ma, now)

    def _current_state(self) -> ResultState:
        state = self._extra_state
        if abs(self._last_current_ma) > int(self._config.nominal_range) * 1000:
            state |= ResultState.OUT_OF_RANGE
        return state

    def _build_current(self, counter: int, _: ResultState) -> CANFrame:
        return proto.current_frame(self._last_current_ma, counter, self._current_state())

    def _build_temperature(self, counter: int, state: ResultState) -> CANFrame:
        return proto.temperature_frame(self._temperature_c, counter, state)

    def _build_charge(self, counter: int, state: ResultState) -> CANFrame:
        return proto.charge_frame(self._accumulator.charge_as_int32, counter, state)

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
            outcome = self._requests.handle(frame, self._mode)
            if outcome is None:
                continue
            if outcome.restart:
                for channel in self._channels:
                    channel.counter.reset()
                    channel.next_due_s = now
            if outcome.new_mode is not None:
                self._mode = outcome.new_mode
            for response in outcome.responses:
                self._send(response)

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
                mode=self._mode,
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
            )
