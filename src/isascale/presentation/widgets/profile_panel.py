"""ProfilePanel — choose a built-in or CSV profile, loop option, plot with progress line."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from isascale.application.builtin_profiles import BUILTIN_PROFILES
from isascale.application.use_cases import RunCsvProfileEmulationUseCase
from isascale.domain.models import CurrentProfile
from isascale.ports.profile_port import ProfileFormatError
from isascale.presentation import theme

CSV_PREFIX = "csv:"


class ProfilePanel(QGroupBox):
    error = Signal(str)
    info = Signal(str)

    def __init__(self, profile_uc: RunCsvProfileEmulationUseCase, parent: QWidget | None = None) -> None:
        super().__init__("Profile", parent)
        self._uc = profile_uc

        self._combo = QComboBox()
        for key, factory in BUILTIN_PROFILES.items():
            self._combo.addItem(factory().name, key)
        self._combo.currentIndexChanged.connect(self._on_selected)
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
        self._plot.addItem(self._cursor)

        row = QHBoxLayout()
        row.addWidget(self._combo, 1)
        row.addWidget(load)
        row.addWidget(self._loop)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self._plot)
        self._on_selected()

    @property
    def loop(self) -> bool:
        return self._loop.isChecked()

    def load_csv(self, path: str) -> bool:
        """Load a CSV through the use case; on success add/select it in the combo."""
        try:
            profile = self._uc.load(path)
        except ProfileFormatError as exc:
            self.error.emit(f"Profile error: {exc}")
            return False
        data = CSV_PREFIX + path
        index = self._combo.findData(data)
        if index < 0:
            self._combo.addItem(f"CSV: {profile.name}", data)
            index = self._combo.count() - 1
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(index)
        self._combo.blockSignals(False)
        self._show(profile)
        self.info.emit(f"Loaded {profile.name} ({len(profile.points)} points, {profile.duration_s:.1f} s)")
        return True

    def set_progress(self, progress: float | None) -> None:
        profile = self._uc.profile
        if profile is None or progress is None:
            self._cursor.setVisible(False)
            return
        self._cursor.setVisible(True)
        self._cursor.setValue(profile.start_s + progress * profile.duration_s)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load current profile", "", "CSV files (*.csv);;All files (*)")
        if path:
            self.load_csv(path)

    def _on_selected(self) -> None:
        data = self._combo.currentData()
        if data is None:
            return
        if str(data).startswith(CSV_PREFIX):
            self.load_csv(str(data)[len(CSV_PREFIX):])
            return
        self._show(self._uc.use_builtin(str(data)))

    def _show(self, profile: CurrentProfile) -> None:
        times = [t for t, _ in profile.points]
        amps = [i / 1000.0 for _, i in profile.points]
        self._curve.setData(times, amps)
        self._cursor.setValue(profile.start_s)
        self._cursor.setVisible(False)
