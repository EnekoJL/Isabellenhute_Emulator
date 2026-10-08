"""Emulator on a python-can virtual bus with a second bus playing the BMS (unique channel per test)."""

from __future__ import annotations

import time

import pytest

can = pytest.importorskip("can")
can_virtual = pytest.importorskip("isascale.infrastructure.adapters.can_virtual")
VirtualCanAdapter = can_virtual.VirtualCanAdapter

from fakes import FakeTimer, run_for  # noqa: E402

from isascale.application.emulator_service import EmulatorService  # noqa: E402
from isascale.domain import ivt_protocol as proto  # noqa: E402
from isascale.domain.models import Bitrate, BusState, CANFrame, IVTConfig, ResultState  # noqa: E402
from isascale.ports.can_port import CanConnectionError, CanTransmitError  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def adapter(virtual_channel):
    adapter = VirtualCanAdapter()
    adapter.connect(virtual_channel, Bitrate.B500K)
    yield adapter
    adapter.disconnect()


@pytest.fixture
def bms(virtual_channel):
    bus = can.Bus(interface="virtual", channel=virtual_channel, receive_own_messages=False)
    yield bus
    bus.shutdown()


@pytest.fixture
def fake_timer():
    return FakeTimer(start=0.0)


@pytest.fixture
def emulator(adapter, fake_timer):
    return EmulatorService(adapter, fake_timer, IVTConfig())


def drain(bus, timeout_s: float = 0.05) -> list[can.Message]:
    msgs = []
    while (msg := bus.recv(timeout_s)) is not None:
        msgs.append(msg)
    return msgs


def by_id(msgs, can_id):
    return [m for m in msgs if m.arbitration_id == can_id]


def send_cmd(bms, *db):
    bms.send(can.Message(arbitration_id=0x411, data=list(db) + [0] * (8 - len(db)), is_extended_id=False))


def test_bms_receives_and_decodes_current(emulator, bms, fake_timer):
    emulator.set_manual_current(35_000)
    emulator.start()
    run_for(emulator, fake_timer, 18 * 0.02 - 0.001)
    msgs = drain(bms)
    assert msgs[0].arbitration_id == 0x511 and msgs[0].data[0] == 0xBF  # alive first
    current = by_id(msgs, 0x521)
    assert len(current) == 18
    for n, msg in enumerate(current):
        assert not msg.is_extended_id
        assert msg.dlc == 6
        assert list(msg.data) == [0x00, n % 16, 0x00, 0x00, 0x88, 0xB8]
    assert by_id(msgs, 0x525) and by_id(msgs, 0x527)


def test_bms_device_id_request_answered(emulator, bms, fake_timer):
    send_cmd(bms, 0x79)
    emulator.tick()
    responses = by_id(drain(bms), 0x511)
    assert [list(m.data) for m in responses] == [[0xB9, 0x02, 0x3E, 0x80, 0x03, 0x01, 0x01, 0x00]]


def test_bms_set_mode_stop_then_get_mode(emulator, bms, fake_timer):
    emulator.start()
    send_cmd(bms, 0x34, 0x00, 0x01)
    run_for(emulator, fake_timer, 0.1)
    drain(bms)
    send_cmd(bms, 0x74)
    run_for(emulator, fake_timer, 0.2)
    msgs = drain(bms)
    assert by_id(msgs, 0x521) == []
    assert [list(m.data) for m in by_id(msgs, 0x511)] == [[0xB4, 0x00, 0x01, 0, 0, 0, 0, 0]]


def test_bms_ignores_extended_command_ids(emulator, bms):
    bms.send(can.Message(arbitration_id=0x411, data=[0x79] + [0] * 7, is_extended_id=True))
    emulator.tick()
    assert drain(bms) == []


def test_inject_bus_off_counts_errors_and_reports_bus_off(emulator, adapter, bms, fake_timer):
    emulator.start()
    drain(bms)
    adapter.inject_fault(BusState.BUS_OFF)
    run_for(emulator, fake_timer, 0.2)  # must not raise
    snap = emulator.snapshot()
    assert snap.bus_status.state is BusState.BUS_OFF
    assert snap.send_errors > 0
    assert snap.bus_status.tx_errors == snap.send_errors
    assert drain(bms) == []
    with pytest.raises(CanTransmitError):
        adapter.send_frame(CANFrame(0x521, bytes(6)))


def test_recovery_after_bus_off(emulator, adapter, bms, fake_timer):
    emulator.start()
    adapter.inject_fault(BusState.BUS_OFF)
    run_for(emulator, fake_timer, 0.1)
    errors = emulator.snapshot().send_errors
    adapter.inject_fault(None)
    drain(bms)
    run_for(emulator, fake_timer, 0.2)
    snap = emulator.snapshot()
    assert snap.bus_status.state is BusState.BUS_OK
    assert snap.send_errors == errors
    assert len(by_id(drain(bms), 0x521)) == 10


def test_inject_warning_keeps_sending(emulator, adapter, bms, fake_timer):
    emulator.start()
    adapter.inject_fault(BusState.WARNING)
    run_for(emulator, fake_timer, 0.1)
    assert emulator.snapshot().bus_status.state is BusState.WARNING
    assert len(by_id(drain(bms), 0x521)) == 5


def test_fail_next_connect(virtual_channel):
    adapter = VirtualCanAdapter()
    adapter.fail_next_connect = True
    with pytest.raises(CanConnectionError):
        adapter.connect(virtual_channel, Bitrate.B500K)
    adapter.connect(virtual_channel, Bitrate.B500K)
    try:
        assert adapter.get_bus_status().state is BusState.BUS_OK
    finally:
        adapter.disconnect()


def test_start_without_connection_on_virtual_adapter(fake_timer):
    service = EmulatorService(VirtualCanAdapter(), fake_timer)
    with pytest.raises(CanConnectionError):
        service.start()


def test_disconnect_during_run_then_reconnect(emulator, adapter, bms, fake_timer, virtual_channel):
    emulator.start()
    run_for(emulator, fake_timer, 0.05)
    adapter.disconnect()
    run_for(emulator, fake_timer, 0.1)
    assert emulator.snapshot().bus_status.state is BusState.DISCONNECTED
    assert emulator.snapshot().send_errors > 0
    adapter.connect(virtual_channel, Bitrate.B500K)
    drain(bms)
    run_for(emulator, fake_timer, 0.1)
    assert len(by_id(drain(bms), 0x521)) == 5


def test_channels_do_not_cross_talk(emulator, fake_timer):
    other = can.Bus(interface="virtual", channel="isascale-test-other-channel")
    try:
        emulator.start()
        run_for(emulator, fake_timer, 0.1)
        assert other.recv(0.01) is None
    finally:
        other.shutdown()


def test_real_time_worker_rate_and_bms_decode(virtual_channel, adapter, bms):
    worker_thread = pytest.importorskip("isascale.infrastructure.concurrency.worker_thread")
    precision_timer = pytest.importorskip("isascale.infrastructure.concurrency.precision_timer")
    timer = precision_timer.PrecisionTimer()
    service = EmulatorService(adapter, timer)
    worker = worker_thread.TransmissionWorker(service, timer)
    service.set_manual_current(-120_000)
    service.set_state_flags(ResultState.OCS)
    service.start()
    worker.start()
    try:
        time.sleep(0.6)
        rate = service.snapshot().measured_current_rate_hz
    finally:
        worker.stop()
        service.stop()
        timer.close()
    msgs = by_id(drain(bms, 0.01), 0x521)
    assert 40 <= rate <= 60, rate
    assert 20 <= len(msgs) <= 36, len(msgs)
    decoded = [proto.decode_result(bytes(m.data)) for m in msgs]
    assert all(d.value == -120_000 and d.state == ResultState.OCS for d in decoded)
    assert [d.counter for d in decoded] == [n % 16 for n in range(len(decoded))]
