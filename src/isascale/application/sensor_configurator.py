"""SensorConfigurator — configures a real IVT-S over CAN, once, on the bench.

Plays the BMS side of the protocol through a CanBusPort: every command waits for its
response (which also keeps the 2 ms minimum gap between commands, datasheet 8.1).
Result frames and responses to other commands are skipped while waiting.

Changing the configuration needs STOP mode (datasheet 8.4, 8.5), and in STOP the
sensor measures nothing, so every operation that stops it puts it back in RUN on
the way out, even when a step fails.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping

from isascale.domain import ivt_commands as cmd
from isascale.domain import ivt_protocol as proto
from isascale.domain.models import CANFrame, ChannelConfig, Mux, OperationMode, TriggerMode
from isascale.ports.can_port import CanBusPort

RESPONSE_TIMEOUT_S = 1.0
# STORE answers "up to +1000 ms" later, Reset Error- and Logdata "at least +1200 ms" (datasheet 8.5).
STORE_TIMEOUT_S = 2.0
LOG_RESET_TIMEOUT_S = 3.0


class ConfiguratorError(Exception):
    """The sensor did not answer, refused a command or reports something else than asked."""


@dataclass(frozen=True)
class SensorProfile:
    """Channels to configure (the others are left as they are) and the global error-mask flag."""

    channels: Mapping[Mux, ChannelConfig]
    error_mask_reporting: bool


# What the AMS firmware reads (AMS repo, docs/architecture/CAN_Protocol.md §4): current
# every 20 ms (factory value), sensor temperature every 1 s, charge counter every 100 ms,
# measurement / system errors reported in IVT_Result_state bits 2 and 3. Big endian, sign
# as the sensor measures it (the firmware fixes the direction, board test E-2).
AMS_PROFILE = SensorProfile(
    channels={
        Mux.I: ChannelConfig(TriggerMode.CYCLIC, 20),
        Mux.T: ChannelConfig(TriggerMode.CYCLIC, 1000),
        Mux.AS: ChannelConfig(TriggerMode.CYCLIC, 100),
    },
    error_mask_reporting=True,
)


@dataclass(frozen=True)
class SensorIdentity:
    serial_number: int
    sw_version: tuple[int, ...]
    device: cmd.DeviceId
    mode: OperationMode
    startup_mode: OperationMode


class SensorConfigurator:
    def __init__(
        self,
        can_port: CanBusPort,
        clock: Callable[[], float] = time.monotonic,
        response_timeout_s: float = RESPONSE_TIMEOUT_S,
    ) -> None:
        self._can = can_port
        self._clock = clock
        self._timeout_s = response_timeout_s

    # ---------------------------------------------------------------- reading

    def read_identity(self) -> SensorIdentity:
        mode, startup = cmd.decode_mode(self._request(cmd.get_command(proto.CMD_GET_MODE)))
        return SensorIdentity(
            serial_number=self._read_serial_number(),
            sw_version=cmd.decode_sw_version(self._request(cmd.get_command(proto.CMD_GET_SW_VERSION))),
            device=cmd.decode_device_id(self._request(cmd.get_command(proto.CMD_GET_DEVICE_ID))),
            mode=mode,
            startup_mode=startup,
        )

    def read_settings(self, muxes: tuple[Mux, ...] = tuple(Mux)) -> dict[Mux, cmd.ChannelSetting]:
        return {mux: cmd.decode_config_result(self._request(cmd.get_config_command(mux))) for mux in muxes}

    # ---------------------------------------------------------------- writing

    def apply_profile(self, profile: SensorProfile) -> None:
        """STOP -> set every channel -> STORE -> RUN, then read the settings back."""
        with self._stopped():
            for mux, config in profile.channels.items():
                self._set_channel(mux, config, profile.error_mask_reporting)
            if not cmd.decode_store_ok(self._request(cmd.store_command(), STORE_TIMEOUT_S)):
                raise ConfiguratorError("STORE refused by the sensor")
        self._check_settings(profile)

    def reset_log_since_reset(self) -> None:
        """Clear the "since reset" log data (datasheet 3.4, 8.5). The overall log can only be
        cleared by Isabellenhuette; whether the 0x527 As result follows is not in the datasheet."""
        serial_number = self._read_serial_number()
        with self._stopped():
            self._request(cmd.reset_log_since_reset_command(serial_number), LOG_RESET_TIMEOUT_S)

    # ---------------------------------------------------------------- steps

    @contextmanager
    def _stopped(self) -> Iterator[None]:
        self._set_mode(OperationMode.STOP)
        try:
            yield
        finally:
            self._set_mode(OperationMode.RUN)

    def _set_mode(self, mode: OperationMode) -> None:
        actual, _ = cmd.decode_mode(self._request(cmd.set_mode_command(mode, OperationMode.RUN)))
        if actual is not mode:
            raise ConfiguratorError(f"sensor stayed in {actual.name}, asked {mode.name}")

    def _set_channel(self, mux: Mux, config: ChannelConfig, error_mask_reporting: bool) -> None:
        asked = cmd.ChannelSetting(mux, config, error_mask_reporting)
        echo = cmd.decode_config_result(self._request(cmd.set_config_command(mux, config, error_mask_reporting)))
        if echo != asked:
            raise ConfiguratorError(f"{mux.name}: sensor did not apply it (answered {echo}, asked {asked})")

    def _check_settings(self, profile: SensorProfile) -> None:
        for mux, setting in self.read_settings(tuple(profile.channels)).items():
            expected = cmd.ChannelSetting(mux, profile.channels[mux], profile.error_mask_reporting)
            if setting != expected:
                raise ConfiguratorError(f"{mux.name}: read back {setting}, expected {expected}")

    def _read_serial_number(self) -> int:
        return cmd.decode_serial_number(self._request(cmd.get_command(proto.CMD_GET_SERIAL_NUMBER)))

    def _request(self, frame: CANFrame, timeout_s: float | None = None) -> cmd.Response:
        """Send one command and wait for its response; skip every other frame."""
        code = frame.data[0]
        expected = cmd.expected_response_code(code)
        wait_s = self._timeout_s if timeout_s is None else timeout_s
        self._can.send_frame(frame)
        deadline = self._clock() + wait_s
        while (remaining := deadline - self._clock()) > 0:
            received = self._can.receive_frame(remaining)
            response = None if received is None else cmd.parse_response(received)
            if response is None:
                continue
            if response.code == expected:
                return response
            if cmd.is_error_for(response, code):
                raise ConfiguratorError(f"sensor refused command 0x{code:02X}")
        raise ConfiguratorError(f"no response to command 0x{code:02X} within {wait_s:.1f} s")
