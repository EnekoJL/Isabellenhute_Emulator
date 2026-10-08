"""TelemetryPanel — live values reported by the emulated sensor."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QWidget

from isascale.application.emulator_service import EmulatorSnapshot
from isascale.domain.models import OperationMode, ResultState
from isascale.presentation import theme


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

    def update_snapshot(self, snap: EmulatorSnapshot) -> None:
        reading = snap.reading
        self._current.setText(f"{reading.current_ma / 1000.0:+10.3f}")
        self._temperature.setText(f"{reading.temperature_c:6.1f}")
        self._charge_as.setText(f"{reading.charge_as:12.1f}")
        self._charge_ah.setText(f"{snap.charge_ah:10.4f}")

        if not snap.running:
            mode, color = "IDLE", theme.TEXT_DIM
        elif snap.mode is OperationMode.RUN:
            mode, color = "RUN", theme.OK
        else:
            mode, color = "STOP", theme.WARNING
        self._mode.setText(f"{mode}  {snap.elapsed_s:7.1f} s")
        self._mode.setStyleSheet(f"color: {color};")

        self._frames.setText(f"{snap.frames_sent} / {snap.send_errors}")
        self._frames.setStyleSheet(f"color: {theme.ERROR if snap.send_errors else theme.TEXT};")

        state = reading.state
        names = [str(f.name) for f in ResultState if f in state] or ["OK"]
        self._state.setText(" ".join(names))
        self._state.setStyleSheet(f"color: {theme.WARNING if state else theme.OK};")

        progress = "" if snap.source_progress is None else f"  {snap.source_progress * 100:5.1f} %"
        self._source.setText(f"{snap.source_name}{progress}")
