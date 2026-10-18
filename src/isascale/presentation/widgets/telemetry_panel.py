"""TelemetryPanel — live values reported by the emulated current sensor.

Motorsport telemetry HUD design matching SEVCON and GPS simulator.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from isascale.presentation import theme
from isascale.presentation.view_models import TelemetryViewModel


class TelemetryPanel(QGroupBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Monitor de Telemetría (IVT-S)", parent)

        # 1. Hero Card: Current Readout
        hero_card = QFrame()
        hero_card.setStyleSheet(
            f"background-color: {theme.CARD}; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 6px;"
        )
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(12, 8, 12, 10)
        hero_layout.setSpacing(2)

        hero_title = QLabel("CORRIENTE DE SALIDA (0x521)")
        hero_title.setStyleSheet(f"font-size: 9pt; font-weight: bold; color: {theme.TEXT_DIM}; letter-spacing: 0.5px;")

        self._current = QLabel("— A")
        self._current.setProperty("role", "big")
        self._current.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 28pt; font-weight: bold; color: {theme.ACCENT};"
        )

        hero_layout.addWidget(hero_title)
        hero_layout.addWidget(self._current)

        # 2. Grid of Telemetry Parameter Cards
        grid = QGridLayout()
        grid.setSpacing(8)

        self._temperature = self._value()
        self._charge_as = self._value()
        self._charge_ah = self._value()
        self._mode = self._value()
        self._frames = self._value()
        self._state = self._value()
        self._source = self._value()
        self._channels = self._value()

        cards = [
            ("Temperatura [°C]", self._temperature),
            ("Carga [As]", self._charge_as),
            ("Carga [Ah]", self._charge_ah),
            ("Modo Emulador", self._mode),
            ("Tramas / Errores", self._frames),
            ("Estado Sensor", self._state),
            ("Origen de Datos", self._source),
            ("Canales activos (config. CAN)", self._channels),
        ]

        for i, (caption, widget) in enumerate(cards):
            card = self._make_card(caption, widget)
            row = i // 2
            col = i % 2
            if i == len(cards) - 1 and len(cards) % 2 != 0:
                grid.addWidget(card, row, col, 1, 2)
            else:
                grid.addWidget(card, row, col)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 14, 10, 10)
        main_layout.setSpacing(10)
        main_layout.addWidget(hero_card)
        main_layout.addLayout(grid)

    @staticmethod
    def _make_card(title: str, val_widget: QWidget) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background-color: {theme.CARD}; border: 1px solid {theme.BORDER}; border-radius: 6px;"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(2)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size: 8.5pt; color: {theme.TEXT_DIM};")
        lay.addWidget(lbl)
        lay.addWidget(val_widget)
        return card

    @staticmethod
    def _value(role: str = "value") -> QLabel:
        label = QLabel("—")
        label.setProperty("role", role)
        label.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 13pt; font-weight: bold; color: {theme.TEXT};"
        )
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
        self._mode.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 13pt; font-weight: bold; color: {theme.color(vm.mode_tone)};"
        )
        self._frames.setText(vm.frames)
        self._frames.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 13pt; font-weight: bold; color: {theme.color(vm.frames_tone)};"
        )
        self._state.setText(vm.state)
        self._state.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 13pt; font-weight: bold; color: {theme.color(vm.state_tone)};"
        )
        self._source.setText(vm.source)
        self._channels.setText(vm.channels)
