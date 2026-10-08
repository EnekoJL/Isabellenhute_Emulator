"""ConnectionPanel — channel, bitrate, cycle periods and Connect/Disconnect (passive).

Emits connect_toggled; the presenter reads form() and decides what to do.
"""

from __future__ import annotations

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

from isascale.presentation.view_models import ConnectionForm, ConnectionOptions


class ConnectionPanel(QGroupBox):
    connect_toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Connection", parent)
        self._channel = QLineEdit()
        self._bitrate = QComboBox()
        self._period_i = QSpinBox()
        self._period_t = QSpinBox()
        self._period_as = QSpinBox()
        self._enable_t = QCheckBox("on")
        self._enable_as = QCheckBox("on")
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_toggled.emit)

        form = QFormLayout(self)
        form.addRow("Channel", self._channel)
        form.addRow("Bitrate", self._bitrate)
        form.addRow("I 0x521 [ms]", self._period_i)
        form.addRow("T 0x525 [ms]", self._row(self._period_t, self._enable_t))
        form.addRow("As 0x527 [ms]", self._row(self._period_as, self._enable_as))
        form.addRow(self.connect_button)

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            layout.addWidget(w)
        return holder

    def set_form(self, form: ConnectionForm, options: ConnectionOptions) -> None:
        self._channel.setText(form.channel)
        self._bitrate.clear()
        for label, value in options.bitrates:
            self._bitrate.addItem(label, value)
        self._bitrate.setCurrentIndex(self._bitrate.findData(form.bitrate))
        for box, value in (
            (self._period_i, form.current_period_ms),
            (self._period_t, form.temperature_period_ms),
            (self._period_as, form.charge_period_ms),
        ):
            box.setRange(options.period_min_ms, options.period_max_ms)
            box.setValue(value)
        self._enable_t.setChecked(form.temperature_enabled)
        self._enable_as.setChecked(form.charge_enabled)

    def form(self) -> ConnectionForm:
        return ConnectionForm(
            channel=self._channel.text(),
            bitrate=int(self._bitrate.currentData()),
            current_period_ms=self._period_i.value(),
            temperature_period_ms=self._period_t.value(),
            charge_period_ms=self._period_as.value(),
            temperature_enabled=self._enable_t.isChecked(),
            charge_enabled=self._enable_as.isChecked(),
        )

    def set_editable(self, editable: bool) -> None:
        for w in (self._channel, self._bitrate, self._period_i, self._period_t, self._period_as,
                  self._enable_t, self._enable_as):
            w.setEnabled(editable)

    def set_connect_button(self, text: str, danger: bool) -> None:
        self.connect_button.setText(text)
        self.connect_button.setProperty("role", "danger" if danger else "primary")
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)
