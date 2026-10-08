"""MainWindow — the Qt view (MVP, Passive View).

Composes the panels, implements the EmulatorView protocol (pure rendering) and
forwards every user event to EmulatorPresenter. No decisions are taken here.
The only timing it owns is the 10 Hz QTimer that asks the presenter to refresh.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Sequence

import pyqtgraph as pg
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from isascale.presentation import theme
from isascale.presentation.presenter import EmulatorPresenter
from isascale.presentation.view_models import (
    BusStatusViewModel,
    ConnectionForm,
    ConnectionOptions,
    ControlsViewModel,
    PlotViewModel,
    ProfileChoice,
    TelemetryViewModel,
)
from isascale.presentation.widgets.can_status_indicator import CanStatusIndicator
from isascale.presentation.widgets.connection_panel import ConnectionPanel
from isascale.presentation.widgets.current_control import CurrentControlPanel
from isascale.presentation.widgets.profile_panel import ProfilePanel
from isascale.presentation.widgets.telemetry_panel import TelemetryPanel

if TYPE_CHECKING:
    from isascale.bootstrap import AppContext

REFRESH_MS = 100
STATUS_TIMEOUT_MS = 8000


class MainWindow(QMainWindow):
    """Implements isascale.presentation.view.EmulatorView."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.presenter: EmulatorPresenter | None = None
        self.setWindowTitle("IVT-S-U0 CAN emulator")
        self.connection_panel = ConnectionPanel()
        self.status_indicator = CanStatusIndicator()
        self.current_control = CurrentControlPanel()
        self.profile_panel = ProfilePanel()
        self.telemetry_panel = TelemetryPanel()
        self._build_layout()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_MS)

    def bind(self, presenter: EmulatorPresenter) -> None:
        """Wire widget events to the presenter, let it push the initial state, start refreshing."""
        self.presenter = presenter
        p = presenter
        self.connection_panel.connect_toggled.connect(lambda: p.on_connect_toggled(self.connection_panel.form()))
        self.start_manual_button.clicked.connect(
            lambda: p.on_start_manual(self.current_control.current_a, self.current_control.temperature_c)
        )
        self.start_profile_button.clicked.connect(lambda: p.on_start_profile(self.profile_panel.loop))
        self.stop_button.clicked.connect(p.on_stop)
        self.current_control.current_changed.connect(p.on_current_changed)
        self.current_control.temperature_changed.connect(p.on_temperature_changed)
        self.current_control.flags_changed.connect(p.on_flags_changed)
        self.current_control.reset_charge_requested.connect(p.on_reset_charge)
        self.profile_panel.profile_selected.connect(p.on_profile_selected)
        self.profile_panel.csv_chosen.connect(p.on_csv_selected)
        self._refresh_timer.timeout.connect(p.on_refresh)
        p.start()
        self._refresh_timer.start()

    # ----------------------------------------------------------------- layout

    def _build_layout(self) -> None:
        self.start_manual_button = QPushButton("Start manual")
        self.start_profile_button = QPushButton("Start profile")
        self.stop_button = QPushButton("Stop")
        self.start_manual_button.setProperty("role", "primary")
        self.start_profile_button.setProperty("role", "primary")
        self.stop_button.setProperty("role", "danger")
        controls = QGroupBox("Emulation")
        row = QHBoxLayout(controls)
        for button in (self.start_manual_button, self.start_profile_button, self.stop_button):
            row.addWidget(button)

        left = QVBoxLayout()
        left.addWidget(self.connection_panel)
        left.addWidget(self.status_indicator)
        left.addStretch(1)
        center = QVBoxLayout()
        center.addWidget(controls)
        center.addWidget(self.current_control)
        center.addWidget(self.profile_panel, 1)
        right = QVBoxLayout()
        right.addWidget(self.telemetry_panel)
        right.addStretch(1)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.addLayout(left)
        layout.addLayout(center, 2)
        layout.addLayout(right, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Disconnected — choose channel and bitrate, then Connect")
        self.resize(1280, 720)

    # ------------------------------------------------------- EmulatorView API

    def set_connection_form(self, form: ConnectionForm, options: ConnectionOptions) -> None:
        self.connection_panel.set_form(form, options)

    def set_current_limit(self, limit_a: float) -> None:
        self.current_control.set_limit(limit_a)

    def set_profile_choices(self, choices: Sequence[ProfileChoice], selected_key: str) -> None:
        self.profile_panel.set_choices(choices, selected_key)

    def show_controls(self, vm: ControlsViewModel) -> None:
        self.connection_panel.set_editable(vm.connection_editable)
        self.connection_panel.set_connect_button(vm.connect_text, vm.connect_danger)
        self.start_manual_button.setEnabled(vm.start_manual_enabled)
        self.start_profile_button.setEnabled(vm.start_profile_enabled)
        self.stop_button.setEnabled(vm.stop_enabled)

    def show_bus_status(self, vm: BusStatusViewModel) -> None:
        self.status_indicator.show_status(vm)

    def show_telemetry(self, vm: TelemetryViewModel) -> None:
        self.telemetry_panel.show_telemetry(vm)

    def show_profile_plot(self, vm: PlotViewModel) -> None:
        self.profile_panel.show_plot(vm)

    def set_profile_cursor(self, time_s: float | None) -> None:
        self.profile_panel.set_cursor(time_s)

    def show_error(self, message: str) -> None:
        self.statusBar().setStyleSheet(f"color: {theme.ERROR};")
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def show_info(self, message: str) -> None:
        self.statusBar().setStyleSheet("")
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    # -------------------------------------------------------------- lifecycle

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self._refresh_timer.stop()
        if self.presenter is not None:
            self.presenter.on_close()
        super().closeEvent(event)


def create_main_window(ctx: AppContext) -> MainWindow:
    """Composition of view + presenter (the presenter gets the core from the AppContext)."""
    window = MainWindow()
    presenter = EmulatorPresenter(window, ctx.service, ctx.manual_uc, ctx.profile_uc, ctx.can_port, ctx.worker)
    window.bind(presenter)
    return window


def run_gui(ctx: AppContext) -> int:
    """Create the QApplication, show the main window and run the event loop."""
    app = QApplication.instance() or QApplication(sys.argv)
    pg.setConfigOptions(antialias=True, foreground=theme.TEXT_DIM)
    theme.apply_theme(app)  # type: ignore[arg-type]
    window = create_main_window(ctx)
    window.show()
    try:
        return app.exec()
    finally:
        # Destroy the window while Qt is still alive; leaving it to Python's GC at
        # interpreter exit crashes (segfault/abort) during teardown.
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        ctx.shutdown()
