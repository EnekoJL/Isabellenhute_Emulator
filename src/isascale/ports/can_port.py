"""CAN bus port — the only CAN interface the core and the GUI may depend on."""

from __future__ import annotations

from abc import ABC, abstractmethod

from isascale.domain.models import Bitrate, BusStatus, CANFrame


class CanBusError(Exception):
    """Base error raised by CanBusPort implementations (wraps driver errors)."""


class CanConnectionError(CanBusError):
    """Connect failed, or an operation was attempted while disconnected."""


class CanTransmitError(CanBusError):
    """A frame could not be sent (bus-off, TX buffer full, driver error)."""


class CanBusPort(ABC):
    """Driven port for a classic CAN 2.0A bus.

    Contract:
      - connect() is idempotent-safe: calling it while connected raises CanConnectionError.
      - send_frame()/receive_frame() raise CanConnectionError when not connected.
      - send_frame() raises CanTransmitError on any driver/bus failure.
      - receive_frame() returns None on timeout; timeout_s=0 means non-blocking.
      - get_bus_status() never raises; returns BusState.DISCONNECTED when not connected.
      - disconnect() never raises and is safe to call twice.
    """

    @abstractmethod
    def connect(self, channel: str, bitrate: Bitrate) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def send_frame(self, frame: CANFrame) -> None: ...

    @abstractmethod
    def receive_frame(self, timeout_s: float = 0.0) -> CANFrame | None: ...

    @abstractmethod
    def get_bus_status(self) -> BusStatus: ...
