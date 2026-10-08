"""HandleBmsRequestsUseCase — answers IVT_Msg_Command (0x411) frames from the BMS/VCU.

Pure decision logic: returns the response frames and the side effects to apply;
EmulatorService applies them (keeps this use case free of threading and I/O).

Supported commands (datasheet 8.5 / 8.7):
  0x79 GET_DEVICE_ID     -> 0xB9 DEVICE_ID
  0x7B GET_SERIAL_NUMBER -> 0xBB SERIAL NUMBER
  0x34 SET_MODE          -> 0xB4 MODE (and switches RUN/STOP)
  0x74 GET_MODE          -> 0xB4 MODE
  0x3F RESTART           -> 0xBF alive message (counters reset)
  anything else          -> 0xFF error, DB1 = offending MuxID
"""

from __future__ import annotations

from dataclasses import dataclass

from isascale.domain import ivt_protocol as proto
from isascale.domain.models import CANFrame, IVTConfig, OperationMode


@dataclass(frozen=True)
class CommandOutcome:
    responses: tuple[CANFrame, ...] = ()
    new_mode: OperationMode | None = None
    restart: bool = False


class HandleBmsRequestsUseCase:
    def __init__(self, config: IVTConfig, startup_mode: OperationMode = OperationMode.RUN) -> None:
        self._config = config
        self.startup_mode = startup_mode

    @property
    def config(self) -> IVTConfig:
        return self._config

    @config.setter
    def config(self, config: IVTConfig) -> None:
        self._config = config

    def handle(self, frame: CANFrame, current_mode: OperationMode) -> CommandOutcome | None:
        """Return the outcome for a command frame, or None if frame is not a command."""
        command = proto.parse_command(frame)
        if command is None:
            return None

        code, payload = command.code, command.payload
        if code == proto.CMD_GET_DEVICE_ID:
            return CommandOutcome((proto.device_id_frame(self._config.nominal_range),))
        if code == proto.CMD_GET_SERIAL_NUMBER:
            return CommandOutcome((proto.serial_number_frame(self._config.serial_number),))
        if code == proto.CMD_GET_MODE:
            return CommandOutcome((proto.mode_frame(current_mode, self.startup_mode),))
        if code == proto.CMD_SET_MODE:
            return self._set_mode(payload, current_mode)
        if code == proto.CMD_RESTART:
            return CommandOutcome((proto.alive_frame(self._config.serial_number),), self.startup_mode, True)
        return CommandOutcome((proto.error_frame(code),))

    def _set_mode(self, payload: bytes, current_mode: OperationMode) -> CommandOutcome:
        try:
            actual = OperationMode(payload[0]) if len(payload) > 0 else current_mode
            startup = OperationMode(payload[1]) if len(payload) > 1 else self.startup_mode
        except ValueError:
            return CommandOutcome((proto.error_frame(proto.CMD_SET_MODE),))
        self.startup_mode = startup
        return CommandOutcome((proto.mode_frame(actual, startup),), new_mode=actual)
