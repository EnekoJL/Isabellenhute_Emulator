"""Shared fixtures: deterministic clock, fake CAN port, config, service, unique virtual channel."""

from __future__ import annotations

import uuid

import pytest
from fakes import FakeCanPort, FakeTimer

from isascale.application.emulator_service import EmulatorService
from isascale.domain.models import IVTConfig


@pytest.fixture
def timer() -> FakeTimer:
    return FakeTimer(start=100.0)  # non-zero origin catches "absolute vs relative time" bugs


@pytest.fixture
def can_port(timer: FakeTimer) -> FakeCanPort:
    return FakeCanPort(clock=timer, connected=True)


@pytest.fixture
def config() -> IVTConfig:
    return IVTConfig()


@pytest.fixture
def service(can_port: FakeCanPort, timer: FakeTimer, config: IVTConfig) -> EmulatorService:
    return EmulatorService(can_port, timer, config)


@pytest.fixture
def virtual_channel() -> str:
    """Unique python-can virtual channel name: no cross-talk between tests."""
    return f"isascale-test-{uuid.uuid4().hex}"
