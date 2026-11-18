"""`isascale-configure` / `python -m isascale.configurator_cli`: configure a real IVT-S once.

Composition root of the configurator tool: picks the CAN adapter and runs one
SensorConfigurator operation.

  info       read serial number, software version, device id, mode and channel settings
  apply-ams  write the AMS profile (default I 20 ms, T 1 s, As 100 ms; --current-ms,
             --temperature-ms, --charge-ms change them), error bits on, and STORE it
  reset-log  clear the "since reset" log data (asks for --yes)
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Sequence

from isascale.application.sensor_configurator import (
    AMS_CHARGE_MS,
    AMS_CURRENT_MS,
    AMS_TEMPERATURE_MS,
    ConfiguratorError,
    SensorConfigurator,
    SensorIdentity,
    SensorProfile,
    ams_profile,
)
from isascale.bootstrap import DEFAULT_INTERFACE, INTERFACES, make_can_port
from isascale.domain.ivt_commands import ChannelSetting
from isascale.domain.models import Bitrate, Mux, TriggerMode
from isascale.ports.can_port import CanBusError, CanBusPort

Out = Callable[[str], None]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="isascale-configure", description="Configure a real IVT-S over CAN")
    parser.add_argument("--interface", choices=INTERFACES, default=DEFAULT_INTERFACE)
    parser.add_argument("--channel", default="0")
    parser.add_argument("--bitrate", type=int, choices=[int(b) for b in Bitrate], default=int(Bitrate.B500K))
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("info", help="read identity and channel settings (changes nothing)")
    apply = sub.add_parser("apply-ams", help="write and STORE the AMS profile")
    apply.add_argument("--current-ms", type=int, default=AMS_CURRENT_MS, help="current I period (default %(default)s)")
    apply.add_argument("--temperature-ms", type=int, default=AMS_TEMPERATURE_MS,
                       help="temperature T period (default %(default)s)")
    apply.add_argument("--charge-ms", type=int, default=AMS_CHARGE_MS,
                       help="charge counter As period (default %(default)s)")
    reset = sub.add_parser("reset-log", help='clear the "since reset" log data')
    reset.add_argument("--yes", action="store_true", help="confirm: the sensor stops measuring for ~2 s")
    return parser.parse_args(argv)


def format_identity(identity: SensorIdentity) -> str:
    major, minor, revision, *date = identity.sw_version
    return (
        f"serial {identity.serial_number}  "
        f"IVT-S {identity.device.nominal_current_a} A U{identity.device.voltage_channels}  "
        f"sw {major}.{minor}.{revision} (20{date[0]:02d}-{date[1]:02d}-{date[2]:02d})  "
        f"mode {identity.mode.name} (start-up {identity.startup_mode.name})"
    )


def format_setting(setting: ChannelSetting) -> str:
    config = setting.config
    text = f"{setting.mux.name:<3} {config.mode.name:<9}"
    if config.mode is not TriggerMode.DISABLED:
        text += f" {config.cycle_ms:>5} ms"
    flags = [name for name, on in (("little-endian", config.little_endian), ("sign inverted", config.invert_sign))
             if on]
    return text + (f"  ({', '.join(flags)})" if flags else "")


def format_profile(profile: SensorProfile) -> list[str]:
    error_mask = profile.error_mask_reporting
    lines = [format_setting(ChannelSetting(mux, config, error_mask)) for mux, config in profile.channels.items()]
    return lines + [f"error bits in result state: {'on' if error_mask else 'off'}"]


def show_sensor(configurator: SensorConfigurator, out: Out) -> None:
    out(format_identity(configurator.read_identity()))
    settings = configurator.read_settings()
    for setting in settings.values():
        out("  " + format_setting(setting))
    out(f"  error bits in result state: {'on' if settings[Mux.I].error_mask_reporting else 'off'}")


def firmware_warnings(profile: SensorProfile) -> list[str]:
    """What the AMS firmware will not like about this profile."""
    current_ms = profile.channels[Mux.I].cycle_ms
    if current_ms == AMS_CURRENT_MS:
        return []
    return [
        f"warning: the AMS firmware expects the current every {AMS_CURRENT_MS} ms "
        f"(pack_current is stale after 100 ms{', so it will always read stale' if current_ms > 100 else ''}): "
        "change BROKER_MAX_AGE_PACK_CURRENT_MS / CAN_IVT_RESULT_PERIOD_MS to match"
    ]


def run(args: argparse.Namespace, can_port: CanBusPort, out: Out = print) -> int:
    """Connect, do the action, disconnect. 0 = done, 1 = sensor problem, 2 = usage / bus problem."""
    if args.action == "reset-log" and not args.yes:
        out("reset-log stops the sensor for ~2 s and clears its 'since reset' log: add --yes")
        return 2
    profile = None
    if args.action == "apply-ams":
        try:
            profile = ams_profile(args.current_ms, args.temperature_ms, args.charge_ms)
        except ValueError as exc:
            out(f"error: {exc}")
            return 2
    try:
        can_port.connect(args.channel, Bitrate(args.bitrate))
    except CanBusError as exc:
        out(f"error: {exc}")
        return 2
    configurator = SensorConfigurator(can_port)
    try:
        if profile is not None:
            out("writing the AMS profile:")
            for line in format_profile(profile):
                out("  " + line)
            for line in firmware_warnings(profile):
                out(line)
            configurator.apply_profile(profile)
            out("stored and read back OK")
        elif args.action == "reset-log":
            configurator.reset_log_since_reset()
            out("'since reset' log data cleared")
        show_sensor(configurator, out)
    except (ConfiguratorError, CanBusError) as exc:
        out(f"error: {exc}")
        return 1
    finally:
        can_port.disconnect()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args, make_can_port(args.interface))


if __name__ == "__main__":
    sys.exit(main())
