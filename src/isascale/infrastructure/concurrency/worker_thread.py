"""TransmissionWorker — dedicated thread that drives EmulatorService.tick()."""

from __future__ import annotations

import logging
import threading

from isascale.application.emulator_service import EmulatorService
from isascale.ports.timer_port import TimerPort

# Upper bound for one wait, so stop() and new commands are noticed quickly.
MAX_WAIT_S = 0.05

log = logging.getLogger(__name__)


class TransmissionWorker:
    """Runs `deadline = service.tick(); timer.sleep_until(deadline)` until stopped.

    An unexpected exception in tick() is logged and stored in last_exception;
    the loop keeps going so the emulator never dies silently.
    """

    def __init__(self, service: EmulatorService, timer: TimerPort) -> None:
        self._service = service
        self._timer = timer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_exception: BaseException | None = None
        self.exception_count = 0

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_alive:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ivt-tx-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                deadline = self._service.tick()
            except Exception as exc:  # noqa: BLE001 - keep the emulator alive
                self.last_exception = exc
                self.exception_count += 1
                log.exception("unexpected error in EmulatorService.tick()")
                deadline = self._timer.now() + MAX_WAIT_S
            self._timer.sleep_until(min(deadline, self._timer.now() + MAX_WAIT_S))
