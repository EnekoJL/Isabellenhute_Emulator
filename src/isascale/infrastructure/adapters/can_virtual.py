"""VirtualCanAdapter — python-can virtual bus with fault injection (CI, no hardware).

Virtual buses opened on the same channel in the same process see each other's
frames, so a test or the HIL script can play the BMS on a second bus.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

import can

from isascale.domain.models import Bitrate, BusState, BusStatus, CANFrame
from isascale.infrastructure.adapters.can_python_can import PythonCanAdapter
from isascale.ports.can_port import CanConnectionError, CanTransmitError


class VirtualCanAdapter(PythonCanAdapter):
    """python-can `interface="virtual"` plus injectable bus faults.

    inject_fault(BUS_OFF): send_frame raises CanTransmitError, status BUS_OFF.
    inject_fault(WARNING): frames still go out, status WARNING.
    inject_fault(None):    clears the fault.
    fail_next_connect:     the next connect() raises CanConnectionError (one shot).
    """

    INTERFACE = "virtual"

    def __init__(self, bus_factory: Callable[..., can.BusABC] = can.Bus) -> None:
        super().__init__(self.INTERFACE, bus_factory)
        self._fault: BusState | None = None
        self.fail_next_connect = False

    @property
    def fault(self) -> BusState | None:
        return self._fault

    def inject_fault(self, state: BusState | None) -> None:
        if state not in (None, BusState.BUS_OFF, BusState.WARNING):
            raise ValueError(f"only BUS_OFF, WARNING or None can be injected, got {state}")
        self._fault = state

    def connect(self, channel: str, bitrate: Bitrate) -> None:
        if self.fail_next_connect:
            self.fail_next_connect = False
            raise CanConnectionError("injected connection failure")
        super().connect(channel, bitrate)

    def send_frame(self, frame: CANFrame) -> None:
        with self._lock:
            self._require_bus()
            if self._fault is BusState.BUS_OFF:
                self._tx_errors += 1
                raise CanTransmitError(f"TX 0x{frame.arbitration_id:03X} failed: injected BUS_OFF")
            super().send_frame(frame)

    def get_bus_status(self) -> BusStatus:
        status = super().get_bus_status()
        if self._fault is None or status.state is BusState.DISCONNECTED:
            return status
        return replace(status, state=self._fault, detail=f"{status.detail} (injected {self._fault.value})")
