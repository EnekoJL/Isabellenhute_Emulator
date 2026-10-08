"""CurrentControlPanel — manual current, temperature, injected state flags, As reset (passive).

Emits engineering units (A, degC) and raw checkbox states; the presenter decides.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QWidget,
)


class CurrentControlPanel(QGroupBox):
    current_changed = Signal(float)  # A
    temperature_changed = Signal(float)  # degC
    flags_changed = Signal(bool, bool, bool)  # OCS, measurement error, system error
    reset_charge_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Manual current", parent)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._spin = QDoubleSpinBox()
        self._spin.setDecimals(1)
        self._spin.setSingleStep(1.0)
        self._spin.setSuffix(" A")
        self._slider.valueChanged.connect(self._on_slider)
        self._spin.valueChanged.connect(self._on_spin)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(-40.0, 125.0)
        self._temperature.setDecimals(1)
        self._temperature.setValue(25.0)
        self._temperature.setSuffix(" °C")
        self._temperature.valueChanged.connect(self.temperature_changed.emit)

        self._ocs = QCheckBox("OCS")
        self._meas_error = QCheckBox("Meas. error")
        self._sys_error = QCheckBox("System error")
        flags_row = QHBoxLayout()
        for box in (self._ocs, self._meas_error, self._sys_error):
            box.toggled.connect(self._on_flags)
            flags_row.addWidget(box)

        reset = QPushButton("Reset As")
        reset.clicked.connect(self.reset_charge_requested.emit)

        current_row = QHBoxLayout()
        current_row.addWidget(self._slider, 1)
        current_row.addWidget(self._spin)
        form = QFormLayout(self)
        form.addRow("Current (+ discharge)", current_row)
        form.addRow("Temperature", self._temperature)
        form.addRow("Inject state", flags_row)
        form.addRow(reset)

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
        # Keep slider and spinbox in sync (pure widget behaviour).
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(value)))
        self._slider.blockSignals(False)
        self.current_changed.emit(value)

    def _on_flags(self) -> None:
        self.flags_changed.emit(self._ocs.isChecked(), self._meas_error.isChecked(), self._sys_error.isChecked())
