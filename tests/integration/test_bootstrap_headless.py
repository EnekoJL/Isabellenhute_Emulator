"""Composition root and headless runner (plan section 5) on the virtual bus."""

from __future__ import annotations

import pytest

pytest.importorskip("can")
bootstrap = pytest.importorskip("isascale.bootstrap")

from isascale.domain.models import Bitrate  # noqa: E402
from isascale.infrastructure.adapters.can_virtual import VirtualCanAdapter  # noqa: E402

pytestmark = pytest.mark.integration


def make_ctx(*argv: str):
    return bootstrap.build_app(bootstrap.parse_args(list(argv)))


def test_parse_args_defaults():
    args = bootstrap.parse_args([])
    assert args.bitrate == 500_000 and args.channel == "0" and not args.headless
    assert args.current_a == 10.0 and args.profile is None and not args.loop


@pytest.mark.parametrize("bitrate", ["125000", "800000"])
def test_parse_args_rejects_unsupported_bitrate(bitrate):
    with pytest.raises(SystemExit):
        bootstrap.parse_args(["--bitrate", bitrate])


def test_build_app_wires_but_does_not_connect_or_start(virtual_channel):
    ctx = make_ctx("--interface", "virtual", "--channel", virtual_channel, "--bitrate", "250000")
    try:
        assert isinstance(ctx.can_port, VirtualCanAdapter)
        assert not ctx.can_port.is_connected
        assert not ctx.worker.is_alive
        assert not ctx.service.running
        assert ctx.config.channel == virtual_channel
        assert ctx.config.bitrate is Bitrate.B250K
    finally:
        ctx.shutdown()
        ctx.shutdown()  # safe twice


def test_make_can_port_unknown_interface():
    with pytest.raises(ValueError):
        bootstrap.make_can_port("socketcan")


@pytest.mark.parametrize("profile", [None, "wot"])
def test_run_headless_transmits_and_exits_cleanly(virtual_channel, profile):
    argv = ["--interface", "virtual", "--channel", virtual_channel, "--headless", "--duration", "0.3"]
    if profile:
        argv += ["--profile", profile]
    ctx = make_ctx(*argv)
    lines: list[str] = []
    assert bootstrap.run_headless(ctx, out=lines.append) == 0
    assert lines and "I-rate" in lines[-1]
    assert not ctx.worker.is_alive and not ctx.can_port.is_connected


def test_run_headless_csv_profile(virtual_channel, tmp_path):
    csv = tmp_path / "lap.csv"
    csv.write_text("time,current\n0,10\n1,20\n")
    ctx = make_ctx("--interface", "virtual", "--channel", virtual_channel, "--profile", str(csv), "--duration", "0.2")
    lines: list[str] = []
    assert bootstrap.run_headless(ctx, out=lines.append) == 0
    assert "src=lap" in lines[-1]


def test_run_headless_connect_failure_exits_2(virtual_channel):
    ctx = make_ctx("--interface", "virtual", "--channel", virtual_channel, "--duration", "0.2")
    ctx.can_port.fail_next_connect = True
    lines: list[str] = []
    assert bootstrap.run_headless(ctx, out=lines.append) == 2
    assert lines[0].startswith("error:")
    assert not ctx.worker.is_alive


def test_run_headless_bad_profile_exits_2(virtual_channel, tmp_path):
    ctx = make_ctx("--interface", "virtual", "--channel", virtual_channel, "--profile", str(tmp_path / "nope.csv"))
    lines: list[str] = []
    assert bootstrap.run_headless(ctx, out=lines.append) == 2
    assert not ctx.can_port.is_connected
