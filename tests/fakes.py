"""Test doubles for the hexagonal ports (no python-can, no threads, no wall clock)."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from isascale.domain.models import Bitrate, BusState, BusStatus, CANFrame, CurrentProfile
from isascale.ports.can_port import CanBusError, CanBusPort, CanConnectionError, CanTransmitError
from isascale.ports.profile_port import ProfileFormatError, ProfileReaderPort
from isascale.ports.timer_port import TimerPort


class FakeTimer(TimerPort):
    """Deterministic manual clock: sleep_until() jumps straight to the deadline."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = float(start)
        self.sleep_calls: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep_until(self, deadline_s: float) -> None:
        self.sleep_calls.append(deadline_s)
        if deadline_s > self.t:
            self.t = deadline_s

    def advance(self, dt_s: float) -> None:
        self.t += dt_s


class SleepTimer(TimerPort):
    """Real-time timer (monotonic + time.sleep) for thread tests; no spin."""

    def now(self) -> float:
        return time.monotonic()

    def sleep_until(self, deadline_s: float) -> None:
        rest = deadline_s - time.monotonic()
        if rest > 0:
            time.sleep(rest)


@dataclass(frozen=True)
class SentFrame:
    t: float
    frame: CANFrame


class FakeCanPort(CanBusPort):
    """In-memory CanBusPort with a sent-frames log, an RX queue and fault injection.

    Fault injection:
      - fail_connect: next connect() raises CanConnectionError (one-shot).
      - tx_failures: number of upcoming send_frame() calls that raise CanTransmitError.
      - tx_always_fail: every send_frame() raises CanTransmitError (e.g. bus-off).
      - rx_error: next receive_frame() raises it (one-shot).
      - state_override: BusState reported while connected (e.g. WARNING / BUS_OFF).
    """

    def __init__(self, clock: TimerPort | None = None, connected: bool = False) -> None:
        self._clock = clock
        self._connected = connected
        self.channel: str | None = None
        self.bitrate: Bitrate | None = None
        self.sent: list[SentFrame] = []
        self.rx_queue: deque[CANFrame] = deque()
        self.tx_count = 0
        self.rx_count = 0
        self.tx_errors = 0
        self.fail_connect = False
        self.tx_failures = 0
        self.tx_always_fail = False
        self.rx_error: CanBusError | None = None
        self.state_override: BusState | None = None
        self.connect_calls = 0
        self.disconnect_calls = 0

    # -- CanBusPort -------------------------------------------------------------
    def connect(self, channel: str, bitrate: Bitrate) -> None:
        self.connect_calls += 1
        if self._connected:
            raise CanConnectionError("already connected")
        if self.fail_connect:
            self.fail_connect = False
            raise CanConnectionError("injected connect failure")
        self.channel, self.bitrate = channel, bitrate
        self._connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def send_frame(self, frame: CANFrame) -> None:
        if not self._connected:
            raise CanConnectionError("not connected")
        if self.tx_always_fail or self.tx_failures > 0:
            if self.tx_failures > 0:
                self.tx_failures -= 1
            self.tx_errors += 1
            raise CanTransmitError("injected TX failure")
        self.tx_count += 1
        t = self._clock.now() if self._clock is not None else 0.0
        self.sent.append(SentFrame(t, frame))

    def receive_frame(self, timeout_s: float = 0.0) -> CANFrame | None:
        if not self._connected:
            raise CanConnectionError("not connected")
        if self.rx_error is not None:
            exc, self.rx_error = self.rx_error, None
            raise exc
        if not self.rx_queue:
            return None
        self.rx_count += 1
        return self.rx_queue.popleft()

    def get_bus_status(self) -> BusStatus:
        if not self._connected:
            state = BusState.DISCONNECTED
        else:
            state = self.state_override or BusState.BUS_OK
        return BusStatus(state, self.tx_count, self.rx_count, self.tx_errors)

    # -- helpers ----------------------------------------------------------------
    def push_rx(self, arbitration_id: int, data: bytes | list[int]) -> None:
        self.rx_queue.append(CANFrame(arbitration_id, bytes(data)))

    def frames(self, arbitration_id: int | None = None) -> list[CANFrame]:
        return [s.frame for s in self.sent if arbitration_id is None or s.frame.arbitration_id == arbitration_id]

    def times(self, arbitration_id: int) -> list[float]:
        return [s.t for s in self.sent if s.frame.arbitration_id == arbitration_id]

    def clear(self) -> None:
        self.sent.clear()


class FakeProfileReader(ProfileReaderPort):
    def __init__(self, profiles: dict[str, CurrentProfile] | None = None) -> None:
        self.profiles = profiles or {}
        self.loaded: list[str] = []

    def load_profile(self, file_path: str | Path) -> CurrentProfile:
        key = str(file_path)
        self.loaded.append(key)
        if key not in self.profiles:
            raise ProfileFormatError(f"no such profile: {key}")
        return self.profiles[key]


def run_for(service, timer: FakeTimer, duration_s: float) -> int:
    """Drive service.tick() like the worker would, until timer reaches now + duration_s.

    Half-open interval [now, now + duration_s): deadlines within 1 ns of the end are
    treated as "at the end" and not executed (immune to float accumulation of periods).
    Returns the number of ticks.
    """
    end = timer.now() + duration_s
    ticks = 0
    while True:
        deadline = service.tick()
        ticks += 1
        if deadline >= end - 1e-9:
            timer.sleep_until(end)
            return ticks
        timer.sleep_until(deadline)
