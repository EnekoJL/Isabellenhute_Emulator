"""TransmissionWorker (plan 3.6) and PrecisionTimer (plan 3.5). Short real-thread tests."""

from __future__ import annotations

import threading
import time

import pytest
from fakes import FakeCanPort, SleepTimer

worker_thread = pytest.importorskip("isascale.infrastructure.concurrency.worker_thread")
precision_timer = pytest.importorskip("isascale.infrastructure.concurrency.precision_timer")
TransmissionWorker = worker_thread.TransmissionWorker
PrecisionTimer = precision_timer.PrecisionTimer

from isascale.application.emulator_service import EmulatorService  # noqa: E402
from isascale.ports.timer_port import TimerPort  # noqa: E402


class StubService:
    """Minimal tick() provider: deadline = now + period, optional exceptions."""

    def __init__(self, timer: TimerPort, period_s: float = 0.002, raise_on: set[int] | None = None) -> None:
        self.timer = timer
        self.period_s = period_s
        self.raise_on = raise_on or set()
        self.calls = 0
        self.threads: set[str] = set()
        self.called = threading.Event()

    def tick(self) -> float:
        self.calls += 1
        self.threads.add(threading.current_thread().name)
        self.called.set()
        if self.calls in self.raise_on:
            raise RuntimeError(f"boom #{self.calls}")
        return self.timer.now() + self.period_s


def wait_for(predicate, timeout_s: float = 1.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.002)
    return predicate()


@pytest.fixture
def timer() -> SleepTimer:  # overrides the FakeTimer fixture: real threads need real time
    return SleepTimer()


@pytest.fixture
def worker_factory():
    workers = []

    def make(service, timer):
        w = TransmissionWorker(service, timer)
        workers.append(w)
        return w

    yield make
    for w in workers:
        w.stop(timeout=1.0)


def test_worker_calls_tick_repeatedly_in_its_own_thread(timer, worker_factory):
    service = StubService(timer)
    worker = worker_factory(service, timer)
    assert not worker.is_alive
    worker.start()
    assert worker.is_alive
    assert wait_for(lambda: service.calls >= 10)
    assert threading.current_thread().name not in service.threads


def test_worker_stops_cleanly(timer, worker_factory):
    service = StubService(timer)
    worker = worker_factory(service, timer)
    worker.start()
    assert service.called.wait(1.0)
    assert worker.stop(timeout=1.0) is None
    assert not worker.is_alive
    calls = service.calls
    time.sleep(0.02)
    assert service.calls == calls


def test_stop_is_prompt_even_with_far_deadline(timer, worker_factory):
    service = StubService(timer, period_s=10.0)  # wait capped at 50 ms by contract
    worker = worker_factory(service, timer)
    worker.start()
    assert service.called.wait(1.0)
    t0 = time.monotonic()
    worker.stop(timeout=1.0)
    assert time.monotonic() - t0 < 0.3
    assert not worker.is_alive


def test_far_deadline_is_capped_so_tick_runs_at_least_every_50ms(timer, worker_factory):
    service = StubService(timer, period_s=10.0)
    worker = worker_factory(service, timer)
    worker.start()
    assert wait_for(lambda: service.calls >= 4, timeout_s=1.0)


def test_worker_survives_exception_in_tick(timer, worker_factory):
    service = StubService(timer, raise_on={1, 3})
    worker = worker_factory(service, timer)
    worker.start()
    assert wait_for(lambda: service.calls >= 6)
    assert worker.is_alive
    assert isinstance(worker.last_exception, RuntimeError)
    assert worker.exception_count == 2


def test_worker_exception_is_logged(timer, worker_factory, caplog):
    service = StubService(timer, raise_on={1})
    worker = worker_factory(service, timer)
    with caplog.at_level("ERROR"):
        worker.start()
        assert wait_for(lambda: service.calls >= 2)
    assert any("boom #1" in (r.exc_text or "") or r.exc_info for r in caplog.records)


def test_start_twice_does_not_spawn_second_thread(timer, worker_factory):
    service = StubService(timer)
    worker = worker_factory(service, timer)
    worker.start()
    worker.start()
    assert wait_for(lambda: service.calls >= 5)
    assert len(service.threads) == 1


def test_restart_after_stop(timer, worker_factory):
    service = StubService(timer)
    worker = worker_factory(service, timer)
    worker.start()
    worker.stop()
    calls = service.calls
    worker.start()
    assert wait_for(lambda: service.calls > calls + 3)


def test_stop_without_start_is_safe(timer):
    TransmissionWorker(StubService(timer), timer).stop()


def test_worker_drives_real_service_at_50hz():
    ptimer = PrecisionTimer()
    port = FakeCanPort(clock=ptimer, connected=True)
    service = EmulatorService(port, ptimer)
    worker = TransmissionWorker(service, ptimer)
    service.start()
    worker.start()
    try:
        time.sleep(0.5)
    finally:
        worker.stop()
        service.stop()
        ptimer.close()
    n = len(port.frames(0x521))
    assert 18 <= n <= 30, n  # nominal 25 in 0.5 s, CI-tolerant
    ts = port.times(0x521)
    rate = (len(ts) - 1) / (ts[-1] - ts[0])
    assert 40 <= rate <= 60


# ------------------------------------------------------------- PrecisionTimer


def test_precision_timer_is_timer_port_using_perf_counter():
    t = PrecisionTimer()
    assert isinstance(t, TimerPort)
    a = time.perf_counter()
    assert a <= t.now() <= time.perf_counter()
    t.close()
    t.close()  # idempotent


def test_precision_timer_past_deadline_returns_immediately():
    t = PrecisionTimer()
    t0 = time.perf_counter()
    t.sleep_until(t.now() - 1.0)
    assert time.perf_counter() - t0 < 0.005


@pytest.mark.parametrize("delay_s", [0.001, 0.005, 0.015])
def test_precision_timer_sleeps_until_deadline(delay_s):
    t = PrecisionTimer()
    deadline = t.now() + delay_s
    t.sleep_until(deadline)
    late = t.now() - deadline
    assert late >= 0
    assert late < 0.02  # generous: CI schedulers; real target is <= 1 ms (NF-03)
