"""ProfilePanel — profile selector, CSV file dialog, loop option, plot with progress line (passive)."""

from __future__ import annotations

from typing import Sequence

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from isascale.presentation import theme
from isascale.presentation.view_models import PlotViewModel, ProfileChoice


class ProfilePanel(QGroupBox):
    profile_selected = Signal(str)  # choice key
    csv_chosen = Signal(str)  # file path picked in the dialog

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Profile", parent)
        self._combo = QComboBox()
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        load = QPushButton("Load CSV…")
        load.clicked.connect(self._browse)
        self._loop = QCheckBox("Loop")

        self._plot = pg.PlotWidget(background=theme.SURFACE)
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("bottom", "time", units="s")
        self._plot.setLabel("left", "current", units="A")
        self._plot.setMinimumHeight(180)
        self._curve = self._plot.plot(pen=pg.mkPen(theme.ACCENT, width=2))
        self._cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.WARNING, width=2))
        self._cursor.setVisible(False)
        self._plot.addItem(self._cursor)

        row = QHBoxLayout()
        row.addWidget(self._combo, 1)
        row.addWidget(load)
        row.addWidget(self._loop)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self._plot)

    @property
    def loop(self) -> bool:
        return self._loop.isChecked()

    def set_choices(self, choices: Sequence[ProfileChoice], selected_key: str) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        for choice in choices:
            self._combo.addItem(choice.label, choice.key)
        self._combo.setCurrentIndex(max(0, self._combo.findData(selected_key)))
        self._combo.blockSignals(False)

    def show_plot(self, vm: PlotViewModel) -> None:
        self._curve.setData(list(vm.times_s), list(vm.current_a))

    def set_cursor(self, time_s: float | None) -> None:
        self._cursor.setVisible(time_s is not None)
        if time_s is not None:
            self._cursor.setValue(time_s)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load current profile", "", "CSV files (*.csv);;All files (*)")
        if path:
            self.csv_chosen.emit(path)

    def _on_index_changed(self) -> None:
        key = self._combo.currentData()
        if key is not None:
            self.profile_selected.emit(str(key))
