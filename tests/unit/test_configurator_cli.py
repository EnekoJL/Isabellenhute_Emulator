"""isascale-configure CLI: arguments, output and exit codes (EmulatedSensorPort, no bus)."""

from __future__ import annotations

import pytest
from fakes import EmulatedSensorPort

from isascale import configurator_cli as cli
from isascale.domain import ivt_protocol as proto
from isascale.domain.models import Bitrate, Mux, TriggerMode


@pytest.fixture
def port() -> EmulatedSensorPort:
    return EmulatedSensorPort(connected=False)


def run(port, *argv: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = cli.run(cli.parse_args(["--interface", "virtual", *argv]), port, lines.append)
    return code, lines


def test_parse_args_defaults():
    args = cli.parse_args(["info"])
    assert (args.action, args.channel, args.bitrate) == ("info", "0", int(Bitrate.B500K))


def test_parse_args_needs_an_action():
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_info_prints_identity_and_settings_and_disconnects(port):
    code, lines = run(port, "info")
    assert code == 0
    assert lines[0].startswith("serial 168496141  IVT-S 1000 A U0  sw 1.0.0 (2022-06-09)  mode RUN")
    assert "  I   CYCLIC       20 ms" in lines
    assert "  T   DISABLED " in lines
    assert lines[-1] == "  error bits in result state: off"
    assert (port.channel, port.bitrate) == ("0", Bitrate.B500K)
    assert not port.is_connected


def test_apply_ams_writes_stores_and_shows_the_result(port):
    code, lines = run(port, "apply-ams")
    assert code == 0
    assert "stored and read back OK" in lines
    assert "  AS  CYCLIC      100 ms" in lines
    assert lines[-1] == "  error bits in result state: on"
    assert port.device.stored.channel(Mux.AS).mode is TriggerMode.CYCLIC


def test_reset_log_needs_yes(port):
    code, lines = run(port, "reset-log")
    assert code == 2
    assert "--yes" in lines[0]
    assert port.connect_calls == 0


def test_reset_log_with_yes(port):
    code, lines = run(port, "reset-log", "--yes")
    assert code == 0
    assert "'since reset' log data cleared" in lines


def test_connection_failure_is_exit_2(port):
    port.fail_connect = True
    code, lines = run(port, "info")
    assert code == 2
    assert lines == ["error: injected connect failure"]


def test_sensor_error_is_exit_1_and_disconnects(port):
    port.rewrite = lambda f: proto.error_frame(0x32) if f.data[0] == proto.RESP_STORE else f
    code, lines = run(port, "apply-ams")
    assert code == 1
    assert lines[-1] == "error: sensor refused command 0x32"
    assert not port.is_connected


def test_format_setting_flags():
    from isascale.domain.ivt_commands import ChannelSetting
    from isascale.domain.models import ChannelConfig

    setting = ChannelSetting(Mux.I, ChannelConfig(TriggerMode.CYCLIC, 20, little_endian=True, invert_sign=True), False)
    assert cli.format_setting(setting) == "I   CYCLIC       20 ms  (little-endian, sign inverted)"
