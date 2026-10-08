"""IxxatCanAdapter — IXXAT USB-to-CAN via python-can (Windows, IXXAT VCI driver required)."""

from __future__ import annotations

from typing import Any, Callable

import can

from isascale.infrastructure.adapters.can_python_can import PythonCanAdapter


class IxxatCanAdapter(PythonCanAdapter):
    """python-can `interface="ixxat"`; the channel is the integer controller index."""

    INTERFACE = "ixxat"

    def __init__(self, bus_factory: Callable[..., can.BusABC] = can.Bus) -> None:
        super().__init__(self.INTERFACE, bus_factory)

    def _bus_channel(self, channel: str) -> Any:
        """IXXAT expects an int channel: "0" -> 0. Non-numeric strings pass through."""
        text = str(channel).strip()
        return int(text) if text.isdigit() else text
