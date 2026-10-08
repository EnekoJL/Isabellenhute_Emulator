"""Composition root: the only module that picks concrete adapters.

build_app() wires adapters + service + use cases + worker and is usable
without Qt (headless mode, tests). The GUI receives the same AppContext.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from isascale.application.builtin_profiles import BUILTIN_PROFILES
from isascale.application.emulator_service import EmulatorService, EmulatorSnapshot
from isascale.application.use_cases import (
    HandleBmsRequestsUseCase,
    RunCsvProfileEmulationUseCase,
    RunManualEmulationUseCase,
)
from isascale.domain.models import Bitrate, IVTConfig
from isascale.infrastructure.adapters.can_ixxat import IxxatCanAdapter
from isascale.infrastructure.adapters.can_virtual import VirtualCanAdapter
from isascale.infrastructure.adapters.csv_reader import CsvProfileAdapter
from isascale.infrastructure.concurrency.precision_timer import PrecisionTimer
from isascale.infrastructure.concurrency.worker_thread import TransmissionWorker
from isascale.ports.can_port import CanBusError, CanBusPort
from isascale.ports.profile_port import ProfileFormatError, ProfileReaderPort

INTERFACES = ("ixxat", "virtual")
DEFAULT_INTERFACE = "ixxat" if sys.platform == "win32" else "virtual"
SNAPSHOT_PERIOD_S = 1.0


@dataclass
class AppContext:
    """Everything the GUI or the headless runner needs."""

    args: argparse.Namespace
    config: IVTConfig
    can_port: CanBusPort
    timer: PrecisionTimer
    service: EmulatorService
    request_handler: HandleBmsRequestsUseCase
    profile_reader: ProfileReaderPort
    manual_uc: RunManualEmulationUseCase
    profile_uc: RunCsvProfileEmulationUseCase
    worker: TransmissionWorker

    def shutdown(self) -> None:
        """Stop transmission, the worker thread and close the bus. Safe to call twice."""
        self.service.stop()
        self.worker.stop()
        self.can_port.disconnect()
        self.timer.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="isascale-emulator", description="Isabellenhuette IVT-S-U0 CAN current sensor emulator"
    )
    parser.add_argument("--interface", choices=INTERFACES, default=DEFAULT_INTERFACE)
    parser.add_argument("--channel", default="0")
    parser.add_argument("--bitrate", type=int, choices=[int(b) for b in Bitrate], default=int(Bitrate.B500K))
    parser.add_argument("--headless", action="store_true", help="run without GUI (HIL / CI)")
    parser.add_argument(
        "--profile", default=None, help=f"built-in profile ({', '.join(BUILTIN_PROFILES)}) or path to a CSV file"
    )
    parser.add_argument("--current-a", type=float, default=10.0, help="manual current in A (when no --profile)")
    parser.add_argument("--loop", action="store_true", help="loop the profile instead of holding the last value")
    parser.add_argument("--duration", type=float, default=None, help="headless: exit after S seconds")
    return parser.parse_args(argv)


def make_can_port(interface: str) -> CanBusPort:
    if interface == "ixxat":
        return IxxatCanAdapter()
    if interface == "virtual":
        return VirtualCanAdapter()
    raise ValueError(f"unknown CAN interface {interface!r}")


def build_app(args: argparse.Namespace) -> AppContext:
    """Wire the application. Nothing is connected or started yet."""
    config = IVTConfig(channel=str(args.channel), bitrate=Bitrate(int(args.bitrate)))
    can_port = make_can_port(args.interface)
    timer = PrecisionTimer()
    request_handler = HandleBmsRequestsUseCase(config)
    service = EmulatorService(can_port, timer, config, request_handler)
    reader = CsvProfileAdapter()
    return AppContext(
        args=args,
        config=config,
        can_port=can_port,
        timer=timer,
        service=service,
        request_handler=request_handler,
        profile_reader=reader,
        manual_uc=RunManualEmulationUseCase(service),
        profile_uc=RunCsvProfileEmulationUseCase(service, reader),
        worker=TransmissionWorker(service, timer),
    )


# ------------------------------------------------------------------ headless


def format_snapshot(snap: EmulatorSnapshot) -> str:
    progress = "" if snap.source_progress is None else f" {snap.source_progress * 100:5.1f}%"
    return (
        f"t={snap.elapsed_s:7.2f}s {snap.mode.name:<4} I={snap.reading.current_ma / 1000:9.3f} A "
        f"T={snap.reading.temperature_c:5.1f} C As={snap.reading.charge_as:9.2f} "
        f"bus={snap.bus_status.state.value:<12} I-rate={snap.measured_current_rate_hz:5.1f} Hz "
        f"tx={snap.frames_sent} err={snap.send_errors} src={snap.source_name}{progress}"
    )


def start_source(ctx: AppContext) -> None:
    """Start the profile given by --profile, or manual mode at --current-a."""
    profile = ctx.args.profile
    if profile is None:
        ctx.manual_uc.start(ctx.args.current_a * 1000.0)
        return
    if profile in BUILTIN_PROFILES:
        ctx.profile_uc.use_builtin(profile)
    else:
        ctx.profile_uc.load(profile)
    ctx.profile_uc.start(loop=ctx.args.loop)


def run_headless(ctx: AppContext, out: Callable[[str], None] = print) -> int:
    """Connect, transmit and print a snapshot every second until --duration or Ctrl+C."""
    try:
        ctx.can_port.connect(ctx.config.channel, ctx.config.bitrate)
        ctx.worker.start()
        start_source(ctx)
    except (CanBusError, ProfileFormatError, ValueError, RuntimeError) as exc:
        out(f"error: {exc}")
        ctx.shutdown()
        return 2

    duration = ctx.args.duration
    t0 = time.monotonic()
    try:
        while duration is None or time.monotonic() - t0 < duration:
            remaining = SNAPSHOT_PERIOD_S if duration is None else min(SNAPSHOT_PERIOD_S, duration - (time.monotonic() - t0))
            time.sleep(max(0.0, remaining))
            out(format_snapshot(ctx.service.snapshot()))
    except KeyboardInterrupt:
        out("interrupted")
    finally:
        ctx.shutdown()
    return 0
