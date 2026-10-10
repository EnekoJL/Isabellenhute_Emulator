"""CanStatusIndicator — CAN bus state LED + rate + TX/RX/error counters.

Matches the motorsport telemetry status style seen in SEVCON and GPS simulator.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from isascale.presentation import theme
from isascale.presentation.view_models import BusStatusViewModel, Tone

LED_SIZE = 14


class CanStatusIndicator(QGroupBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Estado Bus CAN", parent)

        # Header status row (LED + State text)
        status_card = QFrame()
        status_card.setStyleSheet(
            f"background-color: {theme.CARD}; border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 4px;"
        )
        card_layout = QHBoxLayout(status_card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(10)

        self._led = QLabel()
        self._led.setFixedSize(LED_SIZE, LED_SIZE)

        self._state_label = QLabel()
        self._state_label.setProperty("role", "value")
        self._state_label.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {theme.TEXT_DIM};")

        card_layout.addWidget(self._led)
        card_layout.addWidget(self._state_label, 1)

        # Metrics grid
        self._rate = QLabel()
        self._rate.setStyleSheet(f"font-family: {theme.MONO_FONT}; font-size: 11pt; font-weight: bold; color: {theme.ACCENT};")

        self._counters = QLabel()
        self._counters.setStyleSheet(f"font-family: {theme.MONO_FONT}; font-size: 10.5pt; font-weight: bold; color: {theme.TEXT};")

        self._detail = QLabel()
        self._detail.setProperty("role", "dim")
        self._detail.setWordWrap(True)

        grid = QGridLayout()
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(10)

        grid.addWidget(self._dim("Tasa 0x521:"), 0, 0)
        grid.addWidget(self._rate, 0, 1)
        grid.addWidget(self._dim("TX / RX / Err:"), 1, 0)
        grid.addWidget(self._counters, 1, 1)
        grid.addWidget(self._detail, 2, 0, 1, 2)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 14, 10, 10)
        main_layout.setSpacing(8)
        main_layout.addWidget(status_card)
        main_layout.addLayout(grid)

        self.show_status(BusStatusViewModel("DISCONNECTED", Tone.NEUTRAL, "0.0 Hz", "0 / 0 / 0", ""))

    @staticmethod
    def _dim(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "dim")
        return label

    @property
    def state_text(self) -> str:
        return self._state_label.text()

    def show_status(self, vm: BusStatusViewModel) -> None:
        c = theme.color(vm.tone)
        self._led.setStyleSheet(
            f"background-color: {c}; border-radius: {LED_SIZE // 2}px; border: 2px solid rgba(255, 255, 255, 0.2);"
        )
        self._state_label.setText(vm.state_text)
        self._state_label.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 13pt; font-weight: bold; color: {c};"
        )
        self._rate.setText(vm.rate_text)
        self._counters.setText(vm.counters_text)
        self._detail.setText(vm.detail)
