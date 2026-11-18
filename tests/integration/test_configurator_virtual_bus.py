"""SensorConfigurator against the full emulator running in its own thread on a python-can virtual bus
(real time: the STORE answer comes 200 ms later, results keep flowing while it waits)."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("can")
from fakes import SleepTimer  # noqa: E402

from isascale.application.emulator_service import EmulatorService  # noqa: E402
from isascale.application.sensor_configurator import AMS_PROFILE, SensorConfigurator  # noqa: E402
from isascale.domain import ivt_protocol as proto  # noqa: E402
from isascale.domain.models import Bitrate, IVTConfig, Mux, OperationMode, TriggerMode  # noqa: E402
from isascale.infrastructure.adapters.can_virtual import VirtualCanAdapter  # noqa: E402
from isascale.infrastructure.concurrency.worker_thread import TransmissionWorker  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def sensor(virtual_channel):
    """Emulated IVT-S with the factory settings (only I), no start-up delay, running."""
    port = VirtualCanAdapter()
    port.connect(virtual_channel, Bitrate.B500K)
    timer = SleepTimer()
    service = EmulatorService(port, timer, IVTConfig(startup_time_ms=0))
    worker = TransmissionWorker(service, timer)
    worker.start()
    service.start()
    yield service
    service.stop()
    worker.stop()
    port.disconnect()


@pytest.fixture
def bms(virtual_channel):
    port = VirtualCanAdapter()
    port.connect(virtual_channel, Bitrate.B500K)
    yield port
    port.disconnect()


def received_ids(port, duration_s: float) -> set[int]:
    ids = set()
    end = time.monotonic() + duration_s
    while (remaining := end - time.monotonic()) > 0:
        frame = port.receive_frame(remaining)
        if frame is not None:
            ids.add(frame.arbitration_id)
    return ids


def test_apply_ams_profile_on_the_emulator(sensor, bms):
    configurator = SensorConfigurator(bms)
    assert configurator.read_identity().device.nominal_current_a == 1000

    configurator.apply_profile(AMS_PROFILE)

    stored = sensor.device.stored
    assert stored.channel(Mux.T).mode is TriggerMode.CYCLIC
    assert stored.channel(Mux.AS).cycle_ms == 100
    assert stored.error_mask_reporting
    assert sensor.mode is OperationMode.RUN
    ids = received_ids(bms, 1.2)  # T comes every 1 s
    assert {proto.RESULT_I_ID, proto.RESULT_T_ID, proto.RESULT_AS_ID} <= ids
