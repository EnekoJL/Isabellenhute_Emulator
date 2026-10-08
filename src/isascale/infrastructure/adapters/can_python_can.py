"""PythonCanAdapter — CanBusPort implemented on top of python-can.

Common base for the IXXAT and virtual adapters. All bus access is serialised
with a lock so the GUI thread can disconnect while the worker thread is
sending/receiving.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import can

from isascale.domain.models import Bitrate, BusState, BusStatus, CANFrame
from isascale.ports.can_port import CanBusError, CanBusPort, CanConnectionError, CanTransmitError

# Max time bus.send() may block when the TX queue is full.
SEND_TIMEOUT_S = 0.01

# Exceptions python-can backends raise when a bus cannot be opened.
_CONNECT_ERRORS = (can.CanError, OSError, ImportError, ValueError, NotImplementedError, TypeError)

_STATE_MAP = {
    can.BusState.ACTIVE: BusState.BUS_OK,
    can.BusState.PASSIVE: BusState.WARNING,
    can.BusState.ERROR: BusState.BUS_OFF,
}


class PythonCanAdapter(CanBusPort):
    """Classic CAN 2.0A bus on any python-can interface."""

    def __init__(self, interface: str, bus_factory: Callable[..., can.BusABC] = can.Bus) -> None:
        self._interface = interface
        self._bus_factory = bus_factory
        self._bus: can.BusABC | None = None
        self._lock = threading.RLock()
        self._tx_count = 0
        self._rx_count = 0
        self._tx_errors = 0
        self._detail = ""

    @property
    def interface(self) -> str:
        return self._interface

    # -------------------------------------------------------------- lifecycle

    def connect(self, channel: str, bitrate: Bitrate) -> None:
        with self._lock:
            if self._bus is not None:
                raise CanConnectionError("already connected")
            try:
                self._bus = self._bus_factory(
                    interface=self._interface,
                    channel=self._bus_channel(channel),
                    bitrate=int(bitrate),
                    receive_own_messages=False,
                )
            except _CONNECT_ERRORS as exc:
                self._bus = None
                raise CanConnectionError(
                    f"cannot open {self._interface} channel {channel!r} @ {int(bitrate)} bit/s: {exc}"
                ) from exc
            self._tx_count = self._rx_count = self._tx_errors = 0
            self._detail = f"{self._interface}:{channel} @ {int(bitrate) // 1000} kbit/s"

    def disconnect(self) -> None:
        with self._lock:
            bus, self._bus = self._bus, None
            if bus is None:
                return
            try:
                bus.shutdown()
            except Exception:  # noqa: BLE001 - disconnect must never raise
                pass

    @property
    def is_connected(self) -> bool:
        return self._bus is not None

    def _bus_channel(self, channel: str) -> Any:
        """Hook: convert the GUI/CLI channel string to what the backend expects."""
        return channel

    def _require_bus(self) -> can.BusABC:
        if self._bus is None:
            raise CanConnectionError("CAN bus not connected")
        return self._bus

    # --------------------------------------------------------------------- IO

    def send_frame(self, frame: CANFrame) -> None:
        with self._lock:
            bus = self._require_bus()
            msg = can.Message(arbitration_id=frame.arbitration_id, data=frame.data, is_extended_id=False)
            try:
                bus.send(msg, timeout=SEND_TIMEOUT_S)
            except (can.CanError, OSError) as exc:
                self._tx_errors += 1
                raise CanTransmitError(f"TX 0x{frame.arbitration_id:03X} failed: {exc}") from exc
            self._tx_count += 1

    def receive_frame(self, timeout_s: float = 0.0) -> CANFrame | None:
        with self._lock:
            bus = self._require_bus()
            try:
                msg = bus.recv(timeout_s)
            except (can.CanError, OSError) as exc:
                raise CanBusError(f"RX failed: {exc}") from exc
            if msg is None or msg.is_extended_id or msg.is_remote_frame or msg.is_error_frame:
                return None
            self._rx_count += 1
            return CANFrame(msg.arbitration_id, bytes(msg.data[: msg.dlc]), timestamp=msg.timestamp or 0.0)

    # ----------------------------------------------------------------- status

    def get_bus_status(self) -> BusStatus:
        with self._lock:
            if self._bus is None:
                return BusStatus(BusState.DISCONNECTED, self._tx_count, self._rx_count, self._tx_errors)
            try:
                state = _STATE_MAP.get(self._bus.state, BusState.BUS_OK)
            except Exception:  # noqa: BLE001 - backend without state support; must never raise
                state = BusState.BUS_OK
            return BusStatus(state, self._tx_count, self._rx_count, self._tx_errors, self._detail)
