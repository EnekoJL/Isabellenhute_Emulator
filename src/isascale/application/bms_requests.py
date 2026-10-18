"""HandleBmsRequestsUseCase — answers command frames from the BMS/VCU (datasheet 8.3 .. 8.7, 9).

Decision logic only: it edits the DeviceState it is given and returns the
response frames and the side effects that need the clock or the bus
(restart, trigger, delayed responses). EmulatorService applies them under its
lock, so this use case stays free of threading and I/O.

Rules taken from the datasheet:
  * Every defined command gets its response, even when it changed nothing or is
    not allowed in the current mode (8.1); "Stop-Mode only" commands sent in RUN
    are answered with the unchanged values.
  * Commands that carry the serial number (Set/Get CAN ID, Reset Error- and
    Logdata) are only for the sensor with that serial: others stay silent.
  * Restart commands have no response of their own: the sensor goes silent for
    its start-up time and then sends the alive message (9).
  * Undefined commands, invalid values, restart commands outside STOP mode and
    commands during a STORE -> 0xFF error with DB1 = received MuxID.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from isascale.domain import ivt_protocol as proto
from isascale.domain.models import (
    MIN_VOLTAGE_CYCLE_MS,
    Bitrate,
    CANFrame,
    Mux,
    NominalRange,
    OcThresholds,
    OperationMode,
    SensorSettings,
)
from isascale.domain.sensor_state import (
    MEASUREMENT_ERROR_COUNT,
    SYSTEM_ERROR_COUNT,
    ErrorCounters,
    LogBook,
    LogItem,
)

# Response delays (datasheet 8.5): Reset Error- and Logdata "at least +1200 ms";
# STORE "up to +1000 ms" (no further commands while storing).
LOG_RESET_DELAY_S = 1.2
STORE_DELAY_S = 0.2

RESET_KIND_MEASUREMENT = 0x00
RESET_KIND_SYSTEM = 0x01
RESET_KIND_LOG_SINCE_RESET = 0x02

# Command groups whose low nibble selects a channel: Set/Get CAN ID, Set/Get Config Result.
_CHANNEL_COMMAND_GROUPS = (0x1, 0x2, 0x5, 0x6)


class RestartKind(Enum):
    RESTART = "restart"  # 0x3F: back to the stored settings
    TO_DEFAULT = "default"  # 0x3D: factory settings
    TO_BITRATE = "bitrate"  # 0x3A: stored settings at a new bitrate


@dataclass
class DeviceState:
    """Everything the emulated sensor remembers. Owned and locked by EmulatorService.

    stored = non-volatile memory (survives power cycles and restarts);
    active = settings in use (BMS changes land here until STORE).
    """

    serial_number: int
    nominal_range: NominalRange
    bitrate: Bitrate
    stored: SensorSettings
    active: SensorSettings
    mode: OperationMode = OperationMode.RUN
    measurement_errors: ErrorCounters = field(default_factory=lambda: ErrorCounters(MEASUREMENT_ERROR_COUNT))
    system_errors: ErrorCounters = field(default_factory=lambda: ErrorCounters(SYSTEM_ERROR_COUNT))
    log_overall: LogBook = field(default_factory=LogBook)
    log_since_reset: LogBook = field(default_factory=LogBook)
    oc_test_end_s: float = 0.0
    store_busy_until_s: float = 0.0


@dataclass(frozen=True)
class CommandOutcome:
    responses: tuple[CANFrame, ...] = ()
    delayed: tuple[tuple[float, CANFrame], ...] = ()  # (delay in s, frame)
    restart: RestartKind | None = None
    new_bitrate: Bitrate | None = None
    trigger_bits: int = 0  # Mux bit field of a TRIGGER command accepted in RUN
    mode_changed: bool = False


class HandleBmsRequestsUseCase:
    def handle(self, frame: CANFrame, device: DeviceState, now_s: float) -> CommandOutcome | None:
        """Return the outcome for a command frame, or None if frame is not for this sensor."""
        command = proto.parse_command(frame, device.active.command_id)
        if command is None:
            return None
        code = command.code
        resp = device.active.response_id
        if now_s < device.store_busy_until_s:
            return _error(code, resp)
        handler = _HANDLERS.get(code)
        if handler is None and (code >> 4) in _CHANNEL_COMMAND_GROUPS:
            handler = _HANDLERS[code & 0xF0]
        if handler is None:
            return _error(code, resp)
        return handler(command, device, now_s)


def _ok(*frames: CANFrame, **kwargs) -> CommandOutcome:
    return CommandOutcome(responses=frames, **kwargs)


def _error(code: int, response_id: int) -> CommandOutcome:
    return _ok(proto.error_frame(code, response_id))


def _stopped(device: DeviceState) -> bool:
    return device.mode is OperationMode.STOP


# ------------------------------------------------------------- CAN ID (8.3)


def _can_id_index(code: int) -> int | None:
    """Mux 0..7, 0xD command, 0xF response; None for undefined low nibbles."""
    index = code & 0x0F
    return index if index <= 0x7 or index in (proto.CAN_ID_INDEX_COMMAND, proto.CAN_ID_INDEX_RESPONSE) else None


def _current_can_id(settings: SensorSettings, index: int) -> int:
    if index == proto.CAN_ID_INDEX_COMMAND:
        return settings.command_id
    if index == proto.CAN_ID_INDEX_RESPONSE:
        return settings.response_id
    return settings.result_ids[index]


def _with_can_id(settings: SensorSettings, index: int, can_id: int) -> SensorSettings:
    if index == proto.CAN_ID_INDEX_COMMAND:
        return replace(settings, command_id=can_id)
    if index == proto.CAN_ID_INDEX_RESPONSE:
        return replace(settings, response_id=can_id)
    return settings.with_result_id(Mux(index), can_id)


def _set_can_id(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome | None:
    index = _can_id_index(cmd.code)
    if cmd.u32(3) != device.serial_number:
        return None  # addressed to another sensor
    resp = device.active.response_id
    if index is None:
        return _error(cmd.code, resp)
    new_id = cmd.u16(1)
    if not 0 < new_id <= 0x7FF:
        return _error(cmd.code, resp)
    if _stopped(device):
        device.active = _with_can_id(device.active, index, new_id)
    return _ok(proto.can_id_frame(index, _current_can_id(device.active, index), device.serial_number, resp))


def _get_can_id(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome | None:
    index = _can_id_index(cmd.code)
    if cmd.u32(3) != device.serial_number:
        return None
    resp = device.active.response_id
    if index is None:
        return _error(cmd.code, resp)
    return _ok(proto.can_id_frame(index, _current_can_id(device.active, index), device.serial_number, resp))


# -------------------------------------------------------- Config Result (8.4)


def _config_response(device: DeviceState, mux: Mux) -> CANFrame:
    settings = device.active
    return proto.config_result_frame(mux, settings.channel(mux), settings.error_mask_reporting, settings.response_id)


def _set_config(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    mux_bits = cmd.code & 0x0F
    if mux_bits > 0x7:
        return _error(cmd.code, device.active.response_id)
    mux = Mux(mux_bits)
    parsed = proto.parse_channel_config(cmd, device.active.channel(mux))
    if parsed is None:
        return _error(cmd.code, device.active.response_id)
    config, error_mask = parsed
    if mux in (Mux.U1, Mux.U2, Mux.U3) and config.cycle_ms < MIN_VOLTAGE_CYCLE_MS:
        config = replace(config, cycle_ms=MIN_VOLTAGE_CYCLE_MS)
    if _stopped(device):
        device.active = replace(device.active.with_channel(mux, config), error_mask_reporting=error_mask)
    return _ok(_config_response(device, mux))


def _get_config(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    mux_bits = cmd.code & 0x0F
    if mux_bits > 0x7:
        return _error(cmd.code, device.active.response_id)
    return _ok(_config_response(device, Mux(mux_bits)))


# --------------------------------------------------------- Set commands (8.5)


def _reset_errors(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome | None:
    if cmd.u32(3) != device.serial_number:
        return None
    resp = device.active.response_id
    kind, item = cmd.byte(1), cmd.byte(2)
    target = {
        RESET_KIND_MEASUREMENT: device.measurement_errors,
        RESET_KIND_SYSTEM: device.system_errors,
    }.get(kind)
    if kind == RESET_KIND_LOG_SINCE_RESET:
        if item != 0 and item not in LogItem._value2member_map_:
            return _error(cmd.code, resp)
    elif target is None or (item != 0 and not target.is_valid(item)):
        return _error(cmd.code, resp)
    if _stopped(device):
        if target is not None:
            target.reset(item)
        else:
            device.log_since_reset.reset()  # one value at a time is not modelled: all of it
    frame = proto.log_reset_frame(kind, item, device.serial_number, resp)
    return CommandOutcome(delayed=((LOG_RESET_DELAY_S, frame),))


def _trigger(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    bits = cmd.u16(1) & 0x00FF
    accepted = bits if device.mode is OperationMode.RUN else 0
    return _ok(proto.trigger_frame(bits, device.active.response_id), trigger_bits=accepted)


def _store(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    resp = device.active.response_id
    if not _stopped(device):
        return _ok(proto.store_frame(False, device.serial_number, resp))
    device.stored = device.active
    device.store_busy_until_s = now_s + STORE_DELAY_S
    return CommandOutcome(delayed=((STORE_DELAY_S, proto.store_frame(True, device.serial_number, resp)),))


def _start_oc_test(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    if _stopped(device):
        device.oc_test_end_s = now_s + cmd.u16(1) / 1000.0
    return _get_oc_testtime(cmd, device, now_s)


def _set_mode(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    try:
        actual = OperationMode(cmd.byte(1))
        startup = OperationMode(cmd.byte(2))
    except ValueError:
        return _error(cmd.code, device.active.response_id)
    changed = actual is not device.mode
    device.mode = actual
    device.active = replace(device.active, startup_mode=startup)  # kept over a reset only after STORE
    return _ok(proto.mode_frame(actual, startup, device.active.response_id), mode_changed=changed)


def _set_threshold(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    positive = cmd.code == proto.CMD_SET_THRESHOLD_POS
    if _stopped(device):
        thresholds = OcThresholds(set_a=cmd.i16(1), reset_a=cmd.i16(3))
        field_name = "oc_positive" if positive else "oc_negative"
        device.active = replace(device.active, **{field_name: thresholds})
    return _get_threshold(cmd, device, now_s)


def _restart_to_bitrate(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    bitrate = proto.PRESCALER_TO_BITRATE.get(cmd.byte(1))
    if not _stopped(device) or bitrate is None:
        return _error(cmd.code, device.active.response_id)
    return CommandOutcome(restart=RestartKind.TO_BITRATE, new_bitrate=bitrate)


def _restart_to_default(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    if not _stopped(device):
        return _error(cmd.code, device.active.response_id)
    return CommandOutcome(restart=RestartKind.TO_DEFAULT)


def _restart(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    return CommandOutcome(restart=RestartKind.RESTART)


# ------------------------------------------------- Error and log data (8.6)


def _get_errors(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    measurement = cmd.code == proto.CMD_GET_MEASUREMENT_ERRORS
    counters = device.measurement_errors if measurement else device.system_errors
    code = 0x80 if measurement else 0x81
    resp = device.active.response_id
    index = cmd.byte(1)
    if index == 0:
        return _ok(proto.error_bitmask_frame(code, *counters.bitmask(), resp))
    if not counters.is_valid(index):
        return _error(cmd.code, resp)
    return _ok(proto.error_counter_frame(code, index, counters.count(index), resp))


def _get_log(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    overall = cmd.code == proto.CMD_GET_LOG_OVERALL
    resp = device.active.response_id
    try:
        item = LogItem(cmd.byte(1))
    except ValueError:
        return _error(cmd.code, resp)
    book = device.log_overall if overall else device.log_since_reset
    return _ok(proto.log_data_frame(0x82 if overall else 0x83, int(item), book.value(item), resp))


# --------------------------------------------------------- Get commands (8.7)


def _get_oc_testtime(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    remaining_ms = round(max(0.0, device.oc_test_end_s - now_s) * 1000)
    return _ok(proto.oc_test_frame(remaining_ms, device.active.response_id))


def _get_mode(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    return _ok(proto.mode_frame(device.mode, device.active.startup_mode, device.active.response_id))


def _get_threshold(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    positive = cmd.code in (proto.CMD_SET_THRESHOLD_POS, proto.CMD_GET_THRESHOLD_POS)
    thresholds = device.active.oc_positive if positive else device.active.oc_negative
    code = proto.RESP_THRESHOLD_POS if positive else proto.RESP_THRESHOLD_NEG
    return _ok(proto.threshold_frame(code, thresholds, device.active.response_id))


def _get_device_id(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    return _ok(proto.device_id_frame(device.nominal_range, response_id=device.active.response_id))


def _get_sw_version(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    return _ok(proto.sw_version_frame(response_id=device.active.response_id))


def _get_serial_number(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    return _ok(proto.serial_number_frame(device.serial_number, device.active.response_id))


def _get_article_number(cmd: proto.Command, device: DeviceState, now_s: float) -> CommandOutcome:
    return _ok(proto.article_number_frame(response_id=device.active.response_id))


_HANDLERS = {
    proto.CMD_SET_CAN_ID: _set_can_id,
    proto.CMD_SET_CONFIG: _set_config,
    proto.CMD_RESET_ERRORS: _reset_errors,
    proto.CMD_TRIGGER: _trigger,
    proto.CMD_STORE: _store,
    proto.CMD_START_OC_TEST: _start_oc_test,
    proto.CMD_SET_MODE: _set_mode,
    proto.CMD_SET_THRESHOLD_POS: _set_threshold,
    proto.CMD_SET_THRESHOLD_NEG: _set_threshold,
    proto.CMD_RESTART_TO_BITRATE: _restart_to_bitrate,
    proto.CMD_RESTART_TO_DEFAULT: _restart_to_default,
    proto.CMD_RESTART: _restart,
    proto.CMD_GET_MEASUREMENT_ERRORS: _get_errors,
    proto.CMD_GET_SYSTEM_ERRORS: _get_errors,
    proto.CMD_GET_LOG_OVERALL: _get_log,
    proto.CMD_GET_LOG_SINCE_RESET: _get_log,
    proto.CMD_GET_CAN_ID: _get_can_id,
    proto.CMD_GET_CONFIG: _get_config,
    proto.CMD_GET_OC_TESTTIME: _get_oc_testtime,
    proto.CMD_GET_MODE: _get_mode,
    proto.CMD_GET_THRESHOLD_POS: _get_threshold,
    proto.CMD_GET_THRESHOLD_NEG: _get_threshold,
    proto.CMD_GET_DEVICE_ID: _get_device_id,
    proto.CMD_GET_SW_VERSION: _get_sw_version,
    proto.CMD_GET_SERIAL_NUMBER: _get_serial_number,
    proto.CMD_GET_ARTICLE_NUMBER: _get_article_number,
}
