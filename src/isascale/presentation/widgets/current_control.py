"""CurrentControlPanel — manual current, temperature, injected state flags, As reset.

Styled to match the slider and parameter controls in NMEA_GPS_simulator_uart and SEVCON.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from isascale.presentation import theme


class CurrentControlPanel(QGroupBox):
    current_changed = Signal(float)  # A
    temperature_changed = Signal(float)  # degC
    flags_changed = Signal(bool, bool, bool)  # OCS, measurement error, system error
    reset_charge_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Control Manual de Sensor", parent)

        # 1. Current Slider & Value Header
        curr_header = QHBoxLayout()
        curr_lbl = QLabel("Corriente (+ Descarga):")
        curr_lbl.setStyleSheet("font-weight: bold;")
        self._lbl_curr_val = QLabel("+0.0 A")
        self._lbl_curr_val.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 11pt; font-weight: bold; color: {theme.ACCENT};"
        )
        curr_header.addWidget(curr_lbl)
        curr_header.addStretch(1)
        curr_header.addWidget(self._lbl_curr_val)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimumHeight(24)

        self._spin = QDoubleSpinBox()
        self._spin.setDecimals(1)
        self._spin.setSingleStep(1.0)
        self._spin.setSuffix(" A")
        self._spin.setFixedWidth(100)

        slider_row = QHBoxLayout()
        slider_row.addWidget(self._slider, 1)
        slider_row.addWidget(self._spin)

        self._slider.valueChanged.connect(self._on_slider)
        self._spin.valueChanged.connect(self._on_spin)

        # 2. Temperature Control
        temp_header = QHBoxLayout()
        temp_lbl = QLabel("Temperatura Shunt:")
        temp_lbl.setStyleSheet("font-weight: bold;")

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(-40.0, 125.0)
        self._temperature.setDecimals(1)
        self._temperature.setValue(25.0)
        self._temperature.setSuffix(" °C")
        self._temperature.setFixedWidth(100)
        self._temperature.valueChanged.connect(self.temperature_changed.emit)

        temp_header.addWidget(temp_lbl)
        temp_header.addStretch(1)
        temp_header.addWidget(self._temperature)

        # 3. Fault Injection Flags
        flags_card = QFrame()
        flags_card.setStyleSheet(
            f"background-color: {theme.CARD}; border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 2px;"
        )
        flags_layout = QVBoxLayout(flags_card)
        flags_layout.setContentsMargins(8, 6, 8, 6)
        flags_layout.setSpacing(6)

        flags_title = QLabel("Inyección de Estados / Fallos:")
        flags_title.setProperty("role", "dim")
        flags_layout.addWidget(flags_title)

        boxes_row = QHBoxLayout()
        boxes_row.setSpacing(12)
        self._ocs = QCheckBox("OCS")
        self._meas_error = QCheckBox("Error Medición")
        self._sys_error = QCheckBox("Error Sistema")

        for box in (self._ocs, self._meas_error, self._sys_error):
            box.toggled.connect(self._on_flags)
            boxes_row.addWidget(box)
        boxes_row.addStretch(1)
        flags_layout.addLayout(boxes_row)

        # 4. Reset Charge Button
        reset_btn = QPushButton("Reiniciar Carga (As / Ah)")
        reset_btn.setProperty("role", "neutral")
        reset_btn.setMinimumHeight(32)
        reset_btn.clicked.connect(self.reset_charge_requested.emit)

        # Main assembly
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(10)
        layout.addLayout(curr_header)
        layout.addLayout(slider_row)
        layout.addLayout(temp_header)
        layout.addWidget(flags_card)
        layout.addWidget(reset_btn)

    @property
    def current_a(self) -> float:
        return self._spin.value()

    @property
    def temperature_c(self) -> float:
        return self._temperature.value()

    def set_limit(self, limit_a: float) -> None:
        self._slider.setRange(int(-limit_a), int(limit_a))
        self._spin.setRange(-limit_a, limit_a)

    def set_current_a(self, value: float) -> None:
        self._spin.setValue(value)

    def _on_slider(self, value: int) -> None:
        if int(round(self._spin.value())) != value:
            self._spin.setValue(float(value))

    def _on_spin(self, value: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(value)))
        self._slider.blockSignals(False)
        prefix = "+" if value > 0 else ""
        self._lbl_curr_val.setText(f"{prefix}{value:.1f} A")
        self.current_changed.emit(value)

    def _on_flags(self) -> None:
        self.flags_changed.emit(self._ocs.isChecked(), self._meas_error.isChecked(), self._sys_error.isChecked())
