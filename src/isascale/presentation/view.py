"""EmulatorView — what the presenter may ask of the view (Passive View, no Qt).

A Protocol rather than an ABC: Qt widgets have their own metaclass, so
MainWindow satisfies this structurally. Tests use a plain fake.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from isascale.presentation.view_models import (
    BusStatusViewModel,
    ConnectionForm,
    ConnectionOptions,
    ControlsViewModel,
    PlotViewModel,
    ProfileChoice,
    TelemetryViewModel,
)


class EmulatorView(Protocol):
    def set_connection_form(self, form: ConnectionForm, options: ConnectionOptions) -> None: ...

    def set_current_limit(self, limit_a: float) -> None: ...

    def set_profile_choices(self, choices: Sequence[ProfileChoice], selected_key: str) -> None: ...

    def show_controls(self, vm: ControlsViewModel) -> None: ...

    def show_bus_status(self, vm: BusStatusViewModel) -> None: ...

    def show_telemetry(self, vm: TelemetryViewModel) -> None: ...

    def show_profile_plot(self, vm: PlotViewModel) -> None: ...

    def set_profile_cursor(self, time_s: float | None) -> None: ...

    def show_error(self, message: str) -> None: ...

    def show_info(self, message: str) -> None: ...
