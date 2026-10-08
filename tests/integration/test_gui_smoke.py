"""GUI smoke test: offscreen Qt, MainWindow on a virtual bus, connect + start/stop manual + profile."""

from __future__ import annotations

import os
import time

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.integration]

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
can = pytest.importorskip("can")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from isascale.bootstrap import build_app, parse_args  # noqa: E402
from isascale.domain import ivt_protocol as proto  # noqa: E402
from isascale.domain.models import BusState  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture
def ctx(virtual_channel):
    ctx = build_app(parse_args(["--interface", "virtual", "--channel", virtual_channel]))
    yield ctx
    ctx.shutdown()


@pytest.fixture
def bms(virtual_channel):
    bus = can.Bus(interface="virtual", channel=virtual_channel)
    yield bus
    bus.shutdown()


@pytest.fixture
def window(qapp, ctx):
    from isascale.presentation.main_window import create_main_window

    win = create_main_window(ctx)
    win.show()
    qapp.processEvents()
    yield win
    win.close()
    # Destroy the C++ widget tree now, while QApplication is alive; leaving top-level
    # widgets to interpreter shutdown makes PySide6/pyqtgraph abort (malloc/segfault).
    win.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def drain(bus):
    msgs = []
    while (m := bus.recv(0.01)) is not None:
        msgs.append(m)
    return msgs


def test_window_builds_and_starts_worker(window, ctx, qapp):
    assert window.windowTitle()
    assert ctx.worker.is_alive  # MainWindow owns the worker lifetime
    assert not ctx.can_port.is_connected
    assert not window.start_manual_button.isEnabled()
    assert window.status_indicator.state_text == BusState.DISCONNECTED.value


def test_start_manual_without_connection_shows_error_not_exception(window, ctx, qapp):
    assert window.start_manual() is False
    assert not ctx.service.running
    assert window.statusBar().currentMessage()


def test_connect_start_stop_manual(window, ctx, qapp, bms):
    assert window.connection_panel.connect_bus() is True
    assert ctx.can_port.is_connected
    pump(qapp, 0.15)
    assert window.start_manual_button.isEnabled()
    assert window.status_indicator.state_text == BusState.BUS_OK.value

    window.current_control.set_current_a(35.0)
    window.start_manual_button.click()
    pump(qapp, 0.4)
    assert ctx.service.running
    msgs = [m for m in drain(bms) if m.arbitration_id == 0x521]
    assert len(msgs) >= 10
    assert proto.decode_result(bytes(msgs[-1].data)).value == 35_000
    assert "35" in window.telemetry_panel.current_text

    window.stop_button.click()
    pump(qapp, 0.15)
    assert not ctx.service.running
    drain(bms)
    pump(qapp, 0.1)
    assert [m for m in drain(bms) if m.arbitration_id == 0x521] == []


def test_builtin_profile_start(window, ctx, qapp, bms):
    window.connection_panel.connect_bus()
    assert ctx.profile_uc.profile is not None  # combo pre-selects a built-in profile
    assert window.start_profile() is True
    pump(qapp, 0.3)
    assert ctx.service.snapshot().source_progress is not None
    assert [m for m in drain(bms) if m.arbitration_id == 0x521]


def test_bus_off_is_shown_and_gui_survives(window, ctx, qapp):
    window.connection_panel.connect_bus()
    window.start_manual()
    ctx.can_port.inject_fault(BusState.BUS_OFF)
    pump(qapp, 0.3)
    assert window.status_indicator.state_text == BusState.BUS_OFF.value
    assert ctx.service.snapshot().send_errors > 0
    ctx.can_port.inject_fault(None)
    pump(qapp, 0.2)
    assert window.status_indicator.state_text == BusState.BUS_OK.value


def test_connect_failure_is_reported_in_status_bar(window, ctx, qapp):
    ctx.can_port.fail_next_connect = True
    assert window.connection_panel.connect_bus() is False
    assert not ctx.can_port.is_connected
    assert "Connect failed" in window.statusBar().currentMessage()


def test_close_stops_worker_and_disconnects(window, ctx, qapp):
    window.connection_panel.connect_bus()
    window.start_manual()
    window.close()
    qapp.processEvents()
    assert not ctx.worker.is_alive
    assert not ctx.can_port.is_connected
    assert not ctx.service.running
