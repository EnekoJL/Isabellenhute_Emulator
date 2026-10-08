"""PythonCanAdapter / IxxatCanAdapter with a mocked python-can bus_factory (plan section 3.1 / 3.2)."""

from __future__ import annotations

import pytest

can = pytest.importorskip("can")
can_python_can = pytest.importorskip("isascale.infrastructure.adapters.can_python_can")
PythonCanAdapter = can_python_can.PythonCanAdapter

from isascale.domain.models import Bitrate, BusState, CANFrame  # noqa: E402
from isascale.ports.can_port import CanBusPort, CanConnectionError, CanTransmitError  # noqa: E402


@pytest.fixture
def bus(mocker):
    bus = mocker.Mock(name="bus")
    bus.state = can.BusState.ACTIVE
    bus.recv.return_value = None
    return bus


@pytest.fixture
def factory(mocker, bus):
    return mocker.Mock(name="bus_factory", return_value=bus)


@pytest.fixture
def adapter(factory):
    return PythonCanAdapter("virtual", bus_factory=factory)


@pytest.fixture
def connected(adapter):
    adapter.connect("vcan0", Bitrate.B500K)
    return adapter


def test_is_a_can_bus_port(adapter):
    assert isinstance(adapter, CanBusPort)
    assert not adapter.is_connected


# ------------------------------------------------------------------- connect


@pytest.mark.parametrize("bitrate", list(Bitrate))
def test_connect_calls_factory_with_contract_kwargs(adapter, factory, bitrate):
    adapter.connect("vcan0", bitrate)
    factory.assert_called_once_with(
        interface="virtual", channel="vcan0", bitrate=int(bitrate), receive_own_messages=False
    )
    assert type(factory.call_args.kwargs["bitrate"]) is int
    assert adapter.is_connected


def test_connect_twice_raises(connected, factory):
    with pytest.raises(CanConnectionError):
        connected.connect("vcan0", Bitrate.B500K)
    assert factory.call_count == 1
    assert connected.is_connected


@pytest.mark.parametrize(
    "error",
    [can.CanError("driver"), OSError("no device"), ImportError("no ixxat dll"), ValueError("bad"), NotImplementedError()],
    ids=["CanError", "OSError", "ImportError", "ValueError", "NotImplementedError"],
)
def test_connect_errors_wrapped_in_can_connection_error(adapter, factory, error):
    factory.side_effect = error
    with pytest.raises(CanConnectionError) as info:
        adapter.connect("0", Bitrate.B500K)
    assert info.value.__cause__ is error
    assert not adapter.is_connected
    assert adapter.get_bus_status().state is BusState.DISCONNECTED


def test_connect_after_failed_connect_works(adapter, factory, bus):
    factory.side_effect = [OSError("unplugged"), bus]
    with pytest.raises(CanConnectionError):
        adapter.connect("0", Bitrate.B500K)
    adapter.connect("0", Bitrate.B500K)
    assert adapter.is_connected


# ---------------------------------------------------------------------- send


def test_send_when_disconnected_raises(adapter):
    with pytest.raises(CanConnectionError):
        adapter.send_frame(CANFrame(0x521, bytes(6)))


def test_send_builds_standard_message(connected, bus):
    connected.send_frame(CANFrame(0x521, bytes([0x00, 0x03, 0x00, 0x00, 0x88, 0xB8])))
    bus.send.assert_called_once()
    msg = bus.send.call_args.args[0]
    assert isinstance(msg, can.Message)
    assert msg.arbitration_id == 0x521
    assert bytes(msg.data) == bytes([0x00, 0x03, 0x00, 0x00, 0x88, 0xB8])
    assert msg.dlc == 6
    assert msg.is_extended_id is False
    timeout = bus.send.call_args.kwargs.get("timeout", bus.send.call_args.args[1:2] or [None])
    assert timeout == pytest.approx(0.01)


def test_send_counts_tx(connected):
    for _ in range(3):
        connected.send_frame(CANFrame(0x521, bytes(6)))
    status = connected.get_bus_status()
    assert (status.tx_count, status.tx_errors) == (3, 0)


def test_send_can_error_becomes_transmit_error_and_is_counted(connected, bus):
    error = can.CanOperationError("tx buffer full")
    bus.send.side_effect = error
    with pytest.raises(CanTransmitError) as info:
        connected.send_frame(CANFrame(0x521, bytes(6)))
    assert info.value.__cause__ is error
    status = connected.get_bus_status()
    assert (status.tx_count, status.tx_errors) == (0, 1)


def test_send_recovers_after_error(connected, bus):
    bus.send.side_effect = [can.CanError("boom"), None]
    with pytest.raises(CanTransmitError):
        connected.send_frame(CANFrame(0x521, bytes(6)))
    connected.send_frame(CANFrame(0x521, bytes(6)))
    status = connected.get_bus_status()
    assert (status.tx_count, status.tx_errors) == (1, 1)


# ------------------------------------------------------------------- receive


def test_receive_when_disconnected_raises(adapter):
    with pytest.raises(CanConnectionError):
        adapter.receive_frame(0.0)


def _recv_timeout(bus) -> float:
    call = bus.recv.call_args
    return call.kwargs["timeout"] if "timeout" in call.kwargs else call.args[0]


def test_receive_standard_frame(connected, bus):
    bus.recv.return_value = can.Message(arbitration_id=0x411, data=[0x79, 0, 0, 0, 0, 0, 0, 0], is_extended_id=False)
    frame = connected.receive_frame(0.05)
    assert frame == CANFrame(0x411, bytes([0x79, 0, 0, 0, 0, 0, 0, 0]), timestamp=frame.timestamp)
    assert _recv_timeout(bus) == pytest.approx(0.05)
    assert connected.get_bus_status().rx_count == 1


def test_receive_timeout_returns_none(connected, bus):
    bus.recv.return_value = None
    assert connected.receive_frame(0.0) is None
    assert connected.get_bus_status().rx_count == 0


@pytest.mark.parametrize(
    "msg",
    [
        can.Message(arbitration_id=0x18FF0411, data=[0x79], is_extended_id=True),
        can.Message(arbitration_id=0x411, is_remote_frame=True, is_extended_id=False),
        can.Message(arbitration_id=0x411, is_error_frame=True, is_extended_id=False),
    ],
    ids=["extended", "remote", "error"],
)
def test_receive_ignores_extended_remote_and_error_frames(connected, bus, msg):
    bus.recv.side_effect = [msg, None]
    assert connected.receive_frame(0.0) is None
    assert connected.get_bus_status().rx_count == 0


# -------------------------------------------------------------------- status


def test_status_disconnected(adapter):
    assert adapter.get_bus_status().state is BusState.DISCONNECTED


@pytest.mark.parametrize(
    ("can_state", "expected"),
    [(can.BusState.ACTIVE, BusState.BUS_OK), (can.BusState.PASSIVE, BusState.WARNING), (can.BusState.ERROR, BusState.BUS_OFF)],
)
def test_status_maps_python_can_state(connected, bus, can_state, expected):
    bus.state = can_state
    assert connected.get_bus_status().state is expected


@pytest.mark.parametrize("error", [NotImplementedError, AttributeError, can.CanError])
def test_status_without_backend_support_is_bus_ok_and_never_raises(connected, bus, mocker, error):
    type(bus).state = mocker.PropertyMock(side_effect=error)  # Mock gives each instance its own class
    assert connected.get_bus_status().state is BusState.BUS_OK


# ---------------------------------------------------------------- disconnect


def test_disconnect_shuts_down_bus(connected, bus):
    connected.disconnect()
    bus.shutdown.assert_called_once()
    assert not connected.is_connected
    assert connected.get_bus_status().state is BusState.DISCONNECTED


def test_disconnect_swallows_shutdown_errors(connected, bus):
    bus.shutdown.side_effect = can.CanError("driver died")
    connected.disconnect()
    assert not connected.is_connected


def test_disconnect_is_idempotent(connected, bus):
    connected.disconnect()
    connected.disconnect()
    bus.shutdown.assert_called_once()


def test_disconnect_never_connected_is_safe(adapter):
    adapter.disconnect()


def test_reconnect_after_disconnect(connected, factory):
    connected.disconnect()
    connected.connect("vcan0", Bitrate.B250K)
    assert factory.call_count == 2
    assert connected.is_connected


# --------------------------------------------------------------------- IXXAT


def test_ixxat_adapter_uses_ixxat_interface_and_int_channel(factory):
    can_ixxat = pytest.importorskip("isascale.infrastructure.adapters.can_ixxat")
    adapter = can_ixxat.IxxatCanAdapter(bus_factory=factory)
    assert isinstance(adapter, PythonCanAdapter)
    adapter.connect("0", Bitrate.B1M)
    kwargs = factory.call_args.kwargs
    assert kwargs["interface"] == "ixxat"
    assert kwargs["channel"] == 0 and type(kwargs["channel"]) is int
    assert kwargs["bitrate"] == 1_000_000


def test_ixxat_driver_missing_is_connection_error(factory):
    can_ixxat = pytest.importorskip("isascale.infrastructure.adapters.can_ixxat")
    factory.side_effect = ImportError("vcinpl.dll not found")
    with pytest.raises(CanConnectionError):
        can_ixxat.IxxatCanAdapter(bus_factory=factory).connect("0", Bitrate.B500K)


def test_send_oserror_becomes_transmit_error(connected, bus):
    bus.send.side_effect = OSError("network down")
    with pytest.raises(CanTransmitError):
        connected.send_frame(CANFrame(0x521, bytes(6)))


def test_receive_driver_error_becomes_can_bus_error(connected, bus):
    from isascale.ports.can_port import CanBusError

    bus.recv.side_effect = can.CanOperationError("rx overrun")
    with pytest.raises(CanBusError):
        connected.receive_frame(0.0)


# ---------------------------------------------------------- virtual (mocked bus)


@pytest.fixture
def virtual(factory):
    can_virtual = pytest.importorskip("isascale.infrastructure.adapters.can_virtual")
    return can_virtual.VirtualCanAdapter(bus_factory=factory)


def test_virtual_adapter_uses_virtual_interface(virtual, factory):
    virtual.connect("chan", Bitrate.B500K)
    assert factory.call_args.kwargs["interface"] == "virtual"
    assert factory.call_args.kwargs["channel"] == "chan"


def test_virtual_fail_next_connect_is_one_shot(virtual, factory):
    virtual.fail_next_connect = True
    with pytest.raises(CanConnectionError):
        virtual.connect("chan", Bitrate.B500K)
    assert not virtual.is_connected
    factory.assert_not_called()
    virtual.connect("chan", Bitrate.B500K)
    assert virtual.is_connected


def test_virtual_bus_off_fault_blocks_tx_and_counts(virtual, bus):
    virtual.connect("chan", Bitrate.B500K)
    virtual.inject_fault(BusState.BUS_OFF)
    with pytest.raises(CanTransmitError):
        virtual.send_frame(CANFrame(0x521, bytes(6)))
    bus.send.assert_not_called()
    status = virtual.get_bus_status()
    assert (status.state, status.tx_errors) == (BusState.BUS_OFF, 1)


def test_virtual_warning_fault_still_sends(virtual, bus):
    virtual.connect("chan", Bitrate.B500K)
    virtual.inject_fault(BusState.WARNING)
    virtual.send_frame(CANFrame(0x521, bytes(6)))
    bus.send.assert_called_once()
    assert virtual.get_bus_status().state is BusState.WARNING


def test_virtual_clear_fault(virtual):
    virtual.connect("chan", Bitrate.B500K)
    virtual.inject_fault(BusState.BUS_OFF)
    virtual.inject_fault(None)
    virtual.send_frame(CANFrame(0x521, bytes(6)))
    assert virtual.get_bus_status().state is BusState.BUS_OK


def test_virtual_disconnected_reports_disconnected_even_with_fault(virtual):
    virtual.inject_fault(BusState.BUS_OFF)
    assert virtual.get_bus_status().state is BusState.DISCONNECTED
    with pytest.raises(CanConnectionError):
        virtual.send_frame(CANFrame(0x521, bytes(6)))


@pytest.mark.parametrize("state", [BusState.BUS_OK, BusState.DISCONNECTED])
def test_virtual_rejects_non_fault_states(virtual, state):
    with pytest.raises(ValueError):
        virtual.inject_fault(state)
