"""TelemetryPanel — live values reported by the emulated sensor (passive)."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QWidget

from isascale.presentation import theme
from isascale.presentation.view_models import TelemetryViewModel


class TelemetryPanel(QGroupBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Telemetry", parent)
        self._current = self._value("big")
        self._temperature = self._value()
        self._charge_as = self._value()
        self._charge_ah = self._value()
        self._mode = self._value()
        self._frames = self._value()
        self._state = self._value()
        self._source = QLabel()

        grid = QGridLayout(self)
        rows = [
            ("Current [A]", self._current),
            ("Temperature [°C]", self._temperature),
            ("Charge [As]", self._charge_as),
            ("Charge [Ah]", self._charge_ah),
            ("Mode", self._mode),
            ("Frames sent / errors", self._frames),
            ("Result state", self._state),
            ("Source", self._source),
        ]
        for row, (caption, widget) in enumerate(rows):
            label = QLabel(caption)
            label.setProperty("role", "dim")
            grid.addWidget(label, row, 0)
            grid.addWidget(widget, row, 1)
        grid.setColumnStretch(1, 1)

    @staticmethod
    def _value(role: str = "value") -> QLabel:
        label = QLabel("—")
        label.setProperty("role", role)
        return label

    @property
    def current_text(self) -> str:
        return self._current.text()

    def show_telemetry(self, vm: TelemetryViewModel) -> None:
        self._current.setText(vm.current)
        self._temperature.setText(vm.temperature)
        self._charge_as.setText(vm.charge_as)
        self._charge_ah.setText(vm.charge_ah)
        self._mode.setText(vm.mode)
        self._mode.setStyleSheet(f"color: {theme.color(vm.mode_tone)};")
        self._frames.setText(vm.frames)
        self._frames.setStyleSheet(f"color: {theme.color(vm.frames_tone)};")
        self._state.setText(vm.state)
        self._state.setStyleSheet(f"color: {theme.color(vm.state_tone)};")
        self._source.setText(vm.source)
