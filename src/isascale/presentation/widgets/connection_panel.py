"""ConnectionPanel — CAN channel, bitrate, cycle periods and Connect/Disconnect button.

Styling aligned with CustomTkinter hardware configuration card in NMEA_GPS_simulator_uart.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from isascale.presentation.view_models import ConnectionForm, ConnectionOptions


class ConnectionPanel(QGroupBox):
    connect_toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Configuración CAN / Hardware", parent)

        self._channel = QLineEdit()
        self._channel.setPlaceholderText("Ej. can0, 0 o virtual")

        self._bitrate = QComboBox()

        self._period_i = QSpinBox()
        self._period_i.setSuffix(" ms")

        self._period_t = QSpinBox()
        self._period_t.setSuffix(" ms")

        self._period_as = QSpinBox()
        self._period_as.setSuffix(" ms")

        self._enable_t = QCheckBox("Activo")
        self._enable_as = QCheckBox("Activo")

        self.connect_button = QPushButton("Conectar Bus CAN")
        self.connect_button.setProperty("role", "blue")
        self.connect_button.setMinimumHeight(36)
        self.connect_button.clicked.connect(self.connect_toggled.emit)

        # Form layout with clean labels
        form = QFormLayout()
        form.setContentsMargins(4, 8, 4, 6)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(10)

        form.addRow(self._label("Canal CAN:"), self._channel)
        form.addRow(self._label("Velocidad:"), self._bitrate)
        form.addRow(self._label("0x521 I [ms]:"), self._period_i)
        form.addRow(self._label("0x525 T [ms]:"), self._row(self._period_t, self._enable_t))
        form.addRow(self._label("0x527 As [ms]:"), self._row(self._period_as, self._enable_as))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(self.connect_button)

    @staticmethod
    def _label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "dim")
        return lbl

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for w in widgets:
            layout.addWidget(w)
        return holder

    def set_form(self, form: ConnectionForm, options: ConnectionOptions) -> None:
        self._channel.setText(form.channel)
        self._bitrate.clear()
        for label, value in options.bitrates:
            self._bitrate.addItem(label, value)
        idx = self._bitrate.findData(form.bitrate)
        if idx >= 0:
            self._bitrate.setCurrentIndex(idx)
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
        bitrate_data = self._bitrate.currentData()
        bitrate = int(bitrate_data) if bitrate_data is not None else 500_000
        return ConnectionForm(
            channel=self._channel.text(),
            bitrate=bitrate,
            current_period_ms=self._period_i.value(),
            temperature_period_ms=self._period_t.value(),
            charge_period_ms=self._period_as.value(),
            temperature_enabled=self._enable_t.isChecked(),
            charge_enabled=self._enable_as.isChecked(),
        )

    def set_editable(self, editable: bool) -> None:
        for w in (
            self._channel,
            self._bitrate,
            self._period_i,
            self._period_t,
            self._period_as,
            self._enable_t,
            self._enable_as,
        ):
            w.setEnabled(editable)

    def set_connect_button(self, text: str, danger: bool) -> None:
        self.connect_button.setText(text)
        self.connect_button.setProperty("role", "danger" if danger else "blue")
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)
