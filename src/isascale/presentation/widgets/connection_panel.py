"""ConnectionPanel — channel, bitrate, cycle periods and Connect/Disconnect.

Applies the configuration through service.update_config() and opens the bus
through the CanBusPort. Errors are emitted via `error`, never raised.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from isascale.application.emulator_service import EmulatorService
from isascale.domain.models import MAX_CYCLE_MS, MIN_CYCLE_MS, Bitrate, IVTConfig
from isascale.ports.can_port import CanBusError, CanBusPort

BITRATE_LABELS = {Bitrate.B250K: "250 kbit/s", Bitrate.B500K: "500 kbit/s", Bitrate.B1M: "1 Mbit/s"}


class ConnectionPanel(QGroupBox):
    connected = Signal()
    disconnected = Signal()
    error = Signal(str)
    info = Signal(str)

    def __init__(self, service: EmulatorService, can_port: CanBusPort, parent: QWidget | None = None) -> None:
        super().__init__("Connection", parent)
        self._service = service
        self._can = can_port
        cfg = service.config

        self._channel = QLineEdit(cfg.channel)
        self._bitrate = QComboBox()
        for bitrate, label in BITRATE_LABELS.items():
            self._bitrate.addItem(label, int(bitrate))
        self._bitrate.setCurrentIndex(self._bitrate.findData(int(cfg.bitrate)))
        self._period_i = self._period_box(cfg.current_period_ms)
        self._period_t = self._period_box(cfg.temperature_period_ms)
        self._period_as = self._period_box(cfg.charge_period_ms)
        self._enable_t = QCheckBox("on")
        self._enable_t.setChecked(cfg.temperature_enabled)
        self._enable_as = QCheckBox("on")
        self._enable_as.setChecked(cfg.charge_enabled)
        self._button = QPushButton()
        self._button.clicked.connect(self._toggle)

        form = QFormLayout(self)
        form.addRow("Channel", self._channel)
        form.addRow("Bitrate", self._bitrate)
        form.addRow("I 0x521 [ms]", self._period_i)
        form.addRow("T 0x525 [ms]", self._row(self._period_t, self._enable_t))
        form.addRow("As 0x527 [ms]", self._row(self._period_as, self._enable_as))
        form.addRow(self._button)
        self._refresh_enabled()

    @staticmethod
    def _period_box(value: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(MIN_CYCLE_MS, MAX_CYCLE_MS)
        box.setValue(value)
        return box

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            layout.addWidget(w)
        return holder

    def build_config(self) -> IVTConfig:
        """Config from the form (raises ValueError if invalid, e.g. > 1000 msg/s)."""
        return replace(
            self._service.config,
            channel=self._channel.text().strip() or "0",
            bitrate=Bitrate(int(self._bitrate.currentData())),
            current_period_ms=self._period_i.value(),
            temperature_period_ms=self._period_t.value(),
            charge_period_ms=self._period_as.value(),
            temperature_enabled=self._enable_t.isChecked(),
            charge_enabled=self._enable_as.isChecked(),
        )

    def connect_bus(self) -> bool:
        try:
            config = self.build_config()
            self._service.stop()
            self._service.update_config(config)
            self._can.connect(config.channel, config.bitrate)
        except (CanBusError, ValueError, RuntimeError) as exc:
            self.error.emit(f"Connect failed: {exc}")
            return False
        finally:
            self._refresh_enabled()
        self.info.emit(f"Connected to channel {config.channel} @ {int(config.bitrate) // 1000} kbit/s")
        self.connected.emit()
        return True

    def disconnect_bus(self) -> None:
        self._service.stop()
        self._can.disconnect()
        self._refresh_enabled()
        self.info.emit("Disconnected")
        self.disconnected.emit()

    def _toggle(self) -> None:
        if self._can.is_connected:
            self.disconnect_bus()
        else:
            self.connect_bus()

    def _refresh_enabled(self) -> None:
        connected = self._can.is_connected
        for w in (self._channel, self._bitrate, self._period_i, self._period_t, self._period_as,
                  self._enable_t, self._enable_as):
            w.setEnabled(not connected)
        self._button.setText("Disconnect" if connected else "Connect")
        self._button.setProperty("role", "danger" if connected else "primary")
        self._button.style().unpolish(self._button)
        self._button.style().polish(self._button)
