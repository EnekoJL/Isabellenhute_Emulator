"""MainWindow — the Qt view (MVP, Passive View).

Visual styling completely aligned with NMEA_GPS_simulator_uart and SEVCON:
- Top TitleBar with author branding, live CAN bus indicator dot and digital clock
- Preserves the original ergonomic 3-column workflow (Hardware & CAN left, Emulation & Controls center, Telemetry right)
  with zero tab switching or hidden controls
- Buttons, cards, sliders and indicators styled in CustomTkinter dark blue palette (#1a1a1a / #242424 / #2b2b2b)
"""

from __future__ import annotations

import datetime
import sys
from typing import TYPE_CHECKING, Sequence

import pyqtgraph as pg
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
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


class _TitleBar(QFrame):
    """Author title bar matching SEVCON and GPS simulator styling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"background-color: {theme.PANEL}; border-bottom: 1px solid {theme.BORDER}; padding: 6px 16px;"
        )
        self.setFixedHeight(54)

        # Left branding
        logo = QLabel("⚡")
        logo.setStyleSheet(f"font-size: 20pt; color: {theme.OK}; font-weight: bold;")

        title = QLabel("ISABELLENHÜTTE IVT-S")
        title.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 14.5pt; font-weight: bold; color: {theme.TEXT};"
        )

        subtitle = QLabel("  |  CAN CURRENT SENSOR EMULATOR")
        subtitle.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 10pt; font-weight: bold; color: {theme.TEXT_DIM};"
        )

        left_box = QHBoxLayout()
        left_box.setSpacing(8)
        left_box.addWidget(logo)
        left_box.addWidget(title)
        left_box.addWidget(subtitle)
        left_box.addStretch(1)

        # Right bus indicator dot + clock
        self._dot = QLabel()
        self._dot.setFixedSize(12, 12)
        self.set_can(False)

        can_lbl = QLabel("CAN BUS")
        can_lbl.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 10pt; font-weight: bold; color: {theme.TEXT_DIM};"
        )

        self._clock = QLabel("")
        self._clock.setStyleSheet(
            f"font-family: {theme.MONO_FONT}; font-size: 11pt; font-weight: bold; color: {theme.TEXT_DIM}; margin-left: 14px;"
        )

        right_box = QHBoxLayout()
        right_box.setSpacing(6)
        right_box.addWidget(self._dot)
        right_box.addWidget(can_lbl)
        right_box.addWidget(self._clock)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.addLayout(left_box, 1)
        layout.addLayout(right_box)

        self._update_clock()

    def _update_clock(self) -> None:
        self._clock.setText(datetime.datetime.now().strftime("%H:%M:%S"))

    def set_can(self, active: bool) -> None:
        color = theme.OK if active else theme.ERROR
        self._dot.setStyleSheet(
            f"background-color: {color}; border-radius: 6px; border: 1px solid rgba(255,255,255,0.2);"
        )


class MainWindow(QMainWindow):
    """Implements isascale.presentation.view.EmulatorView."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.presenter: EmulatorPresenter | None = None
        self.setWindowTitle("Simulador Sensor de Corriente IVT-S - AMS")

        self.connection_panel = ConnectionPanel()
        self.status_indicator = CanStatusIndicator()
        self.current_control = CurrentControlPanel()
        self.profile_panel = ProfilePanel()
        self.telemetry_panel = TelemetryPanel()

        self._build_layout()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_MS)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._titlebar._update_clock)
        self._clock_timer.start()

    def bind(self, presenter: EmulatorPresenter) -> None:
        """Wire widget events to presenter, let it push initial state, start refreshing."""
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
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Top TitleBar
        self._titlebar = _TitleBar(self)
        root_layout.addWidget(self._titlebar)

        # 2. Emulation Buttons (Row in Center Panel)
        self.start_manual_button = QPushButton("Iniciar Manual")
        self.start_profile_button = QPushButton("Iniciar Perfil")
        self.stop_button = QPushButton("Detener")

        self.start_manual_button.setProperty("role", "primary")
        self.start_manual_button.setMinimumHeight(36)

        self.start_profile_button.setProperty("role", "blue")
        self.start_profile_button.setMinimumHeight(36)

        self.stop_button.setProperty("role", "danger")
        self.stop_button.setMinimumHeight(36)

        controls_box = QGroupBox("Control de Emulación")
        controls_layout = QHBoxLayout(controls_box)
        controls_layout.setContentsMargins(10, 12, 10, 10)
        controls_layout.setSpacing(10)
        for button in (self.start_manual_button, self.start_profile_button, self.stop_button):
            controls_layout.addWidget(button)

        # 3. 3-Column Layout: Left (Hardware & CAN), Center (Controls & Curve), Right (Telemetry)
        left = QVBoxLayout()
        left.addWidget(self.connection_panel)
        left.addWidget(self.status_indicator)
        left.addStretch(1)

        center = QVBoxLayout()
        center.addWidget(controls_box)
        center.addWidget(self.current_control)
        center.addWidget(self.profile_panel, 1)

        right = QVBoxLayout()
        right.addWidget(self.telemetry_panel)
        right.addStretch(1)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)
        body_layout.addLayout(left, 1)
        body_layout.addLayout(center, 2)
        body_layout.addLayout(right, 1)

        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)

        self.statusBar().showMessage("Desconectado — elija canal y velocidad, luego pulse Conectar Bus CAN")
        self.resize(1340, 820)
        self.setMinimumSize(1100, 700)

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
        is_ok = "OK" in vm.state_text.upper()
        self._titlebar.set_can(is_ok)

    def show_telemetry(self, vm: TelemetryViewModel) -> None:
        self.telemetry_panel.show_telemetry(vm)

    def show_profile_plot(self, vm: PlotViewModel) -> None:
        self.profile_panel.show_plot(vm)

    def set_profile_cursor(self, time_s: float | None) -> None:
        self.profile_panel.set_cursor(time_s)

    def show_error(self, message: str) -> None:
        self.statusBar().setStyleSheet(f"color: {theme.ERROR}; font-weight: bold;")
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def show_info(self, message: str) -> None:
        self.statusBar().setStyleSheet("")
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    # -------------------------------------------------------------- lifecycle

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self._refresh_timer.stop()
        self._clock_timer.stop()
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
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        ctx.shutdown()
