"""ProfilePanel — profile selector, CSV file dialog, loop option, plot with progress cursor.

Styled to match the dark plot and file loaders in NMEA_GPS_simulator_uart.
"""

from __future__ import annotations

from typing import Sequence

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from isascale.presentation import theme
from isascale.presentation.view_models import PlotViewModel, ProfileChoice


class ProfilePanel(QGroupBox):
    profile_selected = Signal(str)  # choice key
    csv_chosen = Signal(str)  # file path picked in the dialog

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Perfil de Corriente y Simulación", parent)

        # Profile selection toolbar
        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        self._combo.currentIndexChanged.connect(self._on_index_changed)

        load_btn = QPushButton("Explorar CSV…")
        load_btn.setProperty("role", "neutral")
        load_btn.clicked.connect(self._browse)

        self._loop = QCheckBox("Bucle continuo (Loop)")
        self._loop.setChecked(True)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 6)
        toolbar.setSpacing(10)

        lbl = QLabel("Perfil:")
        lbl.setProperty("role", "dim")
        toolbar.addWidget(lbl)
        toolbar.addWidget(self._combo, 1)
        toolbar.addWidget(load_btn)
        toolbar.addWidget(self._loop)

        # Plot Widget
        self._plot = pg.PlotWidget(background="#18181b")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("bottom", "Tiempo", units="s")
        self._plot.setLabel("left", "Corriente", units="A")
        self._plot.setMinimumHeight(240)
        self._plot.setStyleSheet("border: 1px solid #383838; border-radius: 8px;")

        # Plot curve and cursor
        self._curve = self._plot.plot(pen=pg.mkPen(theme.ACCENT, width=2.5))
        self._cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.WARNING, width=2))
        self._cursor.setVisible(False)
        self._plot.addItem(self._cursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(10)
        layout.addLayout(toolbar)
        layout.addWidget(self._plot)

    @property
    def loop(self) -> bool:
        return self._loop.isChecked()

    def set_choices(self, choices: Sequence[ProfileChoice], selected_key: str) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        for choice in choices:
            self._combo.addItem(choice.label, choice.key)
        idx = self._combo.findData(selected_key)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)

    def show_plot(self, vm: PlotViewModel) -> None:
        self._curve.setData(list(vm.times_s), list(vm.current_a))

    def set_cursor(self, time_s: float | None) -> None:
        self._cursor.setVisible(time_s is not None)
        if time_s is not None:
            self._cursor.setValue(time_s)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar Perfil de Corriente (CSV)", "", "Archivos CSV (*.csv);;Todos (*)"
        )
        if path:
            self.csv_chosen.emit(path)

    def _on_index_changed(self) -> None:
        key = self._combo.currentData()
        if key is not None:
            self.profile_selected.emit(str(key))
