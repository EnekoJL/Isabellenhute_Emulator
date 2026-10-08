"""MainWindow — composes the panels and forwards user actions to the core.

All calls into the core go through the service, the use cases or the
CanBusPort. The transmission worker thread runs tick(); this (GUI) thread only
reads service.snapshot() every 100 ms and never calls tick().
"""

from __future__ import annotations

import sys
from enum import Enum
from typing import TYPE_CHECKING

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

from isascale.application.emulator_service import EmulatorService
from isascale.application.use_cases import RunCsvProfileEmulationUseCase, RunManualEmulationUseCase
from isascale.domain.models import IVTConfig, ResultState
from isascale.ports.can_port import CanBusError, CanBusPort
from isascale.ports.profile_port import ProfileFormatError
from isascale.presentation import theme
from isascale.presentation.widgets.can_status_indicator import CanStatusIndicator
from isascale.presentation.widgets.connection_panel import ConnectionPanel
from isascale.presentation.widgets.current_control import CurrentControlPanel
from isascale.presentation.widgets.profile_panel import ProfilePanel
from isascale.presentation.widgets.telemetry_panel import TelemetryPanel

if TYPE_CHECKING:
    from isascale.bootstrap import AppContext
    from isascale.infrastructure.concurrency.worker_thread import TransmissionWorker

REFRESH_MS = 100
STATUS_TIMEOUT_MS = 8000
# Exceptions a user action may raise; shown in the status bar, never propagated.
USER_ERRORS = (CanBusError, ProfileFormatError, ValueError, RuntimeError, KeyError)


class ActiveMode(Enum):
    NONE = "none"
    MANUAL = "manual"
    PROFILE = "profile"


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: EmulatorService,
        manual_uc: RunManualEmulationUseCase,
        profile_uc: RunCsvProfileEmulationUseCase,
        can_port: CanBusPort,
        worker: TransmissionWorker,
        config: IVTConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._manual_uc = manual_uc
        self._profile_uc = profile_uc
        self._can = can_port
        self._worker = worker
        self._active = ActiveMode.NONE
        self._last_error_shown = ""

        self.setWindowTitle("IVT-S-U0 CAN emulator")
        self.connection_panel = ConnectionPanel(service, can_port)
        self.status_indicator = CanStatusIndicator()
        self.current_control = CurrentControlPanel(int(config.nominal_range))
        self.profile_panel = ProfilePanel(profile_uc)
        self.telemetry_panel = TelemetryPanel()
        self._build_layout()
        self._wire_signals()

        # The worker also serves BMS requests while stopped, so it lives as long as the window.
        self._worker.start()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

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

    def _wire_signals(self) -> None:
        self.start_manual_button.clicked.connect(self.start_manual)
        self.start_profile_button.clicked.connect(self.start_profile)
        self.stop_button.clicked.connect(self.stop_emulation)
        for panel in (self.connection_panel, self.profile_panel):
            panel.error.connect(self.show_error)
            panel.info.connect(self.show_info)
        self.connection_panel.disconnected.connect(self._on_disconnected)
        self.current_control.current_changed.connect(self._on_current_changed)
        self.current_control.temperature_changed.connect(self._service.set_temperature)
        self.current_control.flags_changed.connect(lambda bits: self._service.set_state_flags(ResultState(bits)))
        self.current_control.reset_charge_requested.connect(self._service.reset_charge)

    # ---------------------------------------------------------------- actions

    def start_manual(self) -> bool:
        try:
            self._service.set_temperature(self.current_control.temperature_c)
            self._manual_uc.start(self.current_control.current_a * 1000.0)
        except USER_ERRORS as exc:
            self.show_error(f"Cannot start manual mode: {exc}")
            return False
        self._active = ActiveMode.MANUAL
        self.show_info("Manual mode running")
        return True

    def start_profile(self) -> bool:
        try:
            self._profile_uc.start(loop=self.profile_panel.loop)
        except USER_ERRORS as exc:
            self.show_error(f"Cannot start profile: {exc}")
            return False
        self._active = ActiveMode.PROFILE
        self.show_info(f"Profile '{self._profile_uc.profile.name}' running")  # type: ignore[union-attr]
        return True

    def stop_emulation(self) -> None:
        self._service.stop()
        self._active = ActiveMode.NONE
        self.show_info("Stopped")

    def _on_current_changed(self, amps: float) -> None:
        # Only forwarded in manual mode: set_manual_current would replace a playing profile.
        if self._active is ActiveMode.MANUAL and self._service.running:
            self._manual_uc.set_current(amps * 1000.0)

    def _on_disconnected(self) -> None:
        self._active = ActiveMode.NONE

    # --------------------------------------------------------------- feedback

    def show_error(self, message: str) -> None:
        self.statusBar().setStyleSheet(f"color: {theme.ERROR};")
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def show_info(self, message: str) -> None:
        self.statusBar().setStyleSheet("")
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def refresh(self) -> None:
        """10 Hz: pull a snapshot from the service and update all read-only views."""
        try:
            snap = self._service.snapshot()
        except Exception as exc:  # noqa: BLE001 - the GUI must survive anything here
            self.show_error(f"Snapshot failed: {exc}")
            return
        self.status_indicator.update_status(snap.bus_status, snap.measured_current_rate_hz)
        self.telemetry_panel.update_snapshot(snap)
        self.profile_panel.set_progress(snap.source_progress if self._active is ActiveMode.PROFILE else None)
        if snap.last_error and snap.last_error != self._last_error_shown:
            self._last_error_shown = snap.last_error
            self.show_error(f"Bus error: {snap.last_error}")
        connected = self._can.is_connected
        self.start_manual_button.setEnabled(connected)
        self.start_profile_button.setEnabled(connected)
        self.stop_button.setEnabled(snap.running)

    # -------------------------------------------------------------- lifecycle

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self._refresh_timer.stop()
        self._service.stop()
        self._worker.stop()
        self._can.disconnect()
        super().closeEvent(event)


def create_main_window(ctx: AppContext) -> MainWindow:
    return MainWindow(ctx.service, ctx.manual_uc, ctx.profile_uc, ctx.can_port, ctx.worker, ctx.config)


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
