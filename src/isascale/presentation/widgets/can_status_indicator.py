"""CanStatusIndicator — bus state LED + measured 0x521 rate + TX/RX/error counters (passive)."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QWidget

from isascale.presentation import theme
from isascale.presentation.view_models import BusStatusViewModel, Tone

LED_SIZE = 18


class CanStatusIndicator(QGroupBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("CAN bus", parent)
        self._led = QLabel()
        self._led.setFixedSize(LED_SIZE, LED_SIZE)
        self._state_label = QLabel()
        self._state_label.setProperty("role", "value")
        self._rate = QLabel()
        self._counters = QLabel()
        self._detail = QLabel()
        self._detail.setProperty("role", "dim")

        head = QHBoxLayout()
        head.addWidget(self._led)
        head.addWidget(self._state_label, 1)
        grid = QGridLayout(self)
        grid.addLayout(head, 0, 0, 1, 2)
        grid.addWidget(self._dim("0x521 rate"), 1, 0)
        grid.addWidget(self._rate, 1, 1)
        grid.addWidget(self._dim("TX / RX / err"), 2, 0)
        grid.addWidget(self._counters, 2, 1)
        grid.addWidget(self._detail, 3, 0, 1, 2)
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
        color = theme.color(vm.tone)
        self._led.setStyleSheet(
            f"background-color: {color}; border-radius: {LED_SIZE // 2}px; border: 1px solid {theme.BORDER};"
        )
        self._state_label.setText(vm.state_text)
        self._state_label.setStyleSheet(f"color: {color};")
        self._rate.setText(vm.rate_text)
        self._counters.setText(vm.counters_text)
        self._detail.setText(vm.detail)
