"""SensorConfigurator against the emulator's command handler (EmulatedSensorPort, no threads)."""

from __future__ import annotations

import pytest
from fakes import EmulatedSensorPort

from isascale.application.bms_requests import CommandOutcome
from isascale.application.sensor_configurator import (
    AMS_PROFILE,
    ConfiguratorError,
    SensorConfigurator,
    SensorProfile,
)
from isascale.domain import ivt_protocol as proto
from isascale.domain.ivt_commands import ChannelSetting, DeviceId
from isascale.domain.models import CANFrame, ChannelConfig, Mux, OperationMode, TriggerMode
from isascale.domain.sensor_state import LogItem, LogSample

STOP, RUN = OperationMode.STOP, OperationMode.RUN


@pytest.fixture
def port() -> EmulatedSensorPort:
    return EmulatedSensorPort()


@pytest.fixture
def configurator(port: EmulatedSensorPort) -> SensorConfigurator:
    return SensorConfigurator(port, clock=port.clock.now)


# --- reading -----------------------------------------------------------------


def test_read_identity_of_the_team_sensor(configurator, port):
    identity = configurator.read_identity()
    assert identity.serial_number == 0x0A0B0C0D
    assert identity.device == DeviceId(nominal_current_a=1000, voltage_channels=0)
    assert identity.sw_version == proto.SW_VERSION
    assert (identity.mode, identity.startup_mode) == (RUN, RUN)
    assert port.commands() == [0x74, 0x7B, 0x7A, 0x79]


def test_read_settings_factory_defaults(configurator):
    settings = configurator.read_settings((Mux.I, Mux.T, Mux.AS))
    assert settings[Mux.I] == ChannelSetting(Mux.I, ChannelConfig(TriggerMode.CYCLIC, 20), False)
    assert settings[Mux.T].config.mode is TriggerMode.DISABLED
    assert settings[Mux.AS].config.mode is TriggerMode.DISABLED


def test_read_settings_skips_result_frames_and_other_responses(configurator, port):
    port.noise = [proto.current_frame(1000, 0), proto.serial_number_frame(1), CANFrame(0x181, bytes(8))]
    assert configurator.read_settings((Mux.I,))[Mux.I].config.cycle_ms == 20


# --- apply_profile -------------------------------------------------------------


def test_apply_ams_profile_stores_it_and_leaves_the_sensor_running(configurator, port):
    configurator.apply_profile(AMS_PROFILE)
    stored = port.device.stored
    assert stored.channel(Mux.I) == ChannelConfig(TriggerMode.CYCLIC, 20)
    assert stored.channel(Mux.T) == ChannelConfig(TriggerMode.CYCLIC, 1000)
    assert stored.channel(Mux.AS) == ChannelConfig(TriggerMode.CYCLIC, 100)
    assert stored.error_mask_reporting
    assert port.device.mode is RUN
    # STOP, I, T, As, STORE, RUN, then read back I, T, As
    assert port.commands() == [0x34, 0x20, 0x24, 0x26, 0x32, 0x34, 0x60, 0x64, 0x66]


def test_apply_profile_waits_for_the_delayed_store_answer(configurator, port):
    t0 = port.clock.now()
    configurator.apply_profile(AMS_PROFILE)
    assert port.clock.now() - t0 == pytest.approx(0.2)  # STORE answers 200 ms later (emulator D-7)


def test_sensor_that_does_not_stop_is_reported(configurator, port):
    port.rewrite = lambda f: proto.mode_frame(RUN) if f.data[0] == proto.RESP_MODE else f
    with pytest.raises(ConfiguratorError, match="stayed in RUN"):
        configurator.apply_profile(AMS_PROFILE)


def test_channel_not_applied_is_reported_and_the_sensor_restarts(configurator, port):
    # The sensor says STOP but stays in RUN: Config Result echoes the old value.
    real_handle = port._handler.handle

    def handle_without_stopping(frame, device, now):
        if frame.data[0] == proto.CMD_SET_MODE and frame.data[1] == int(STOP):
            return CommandOutcome(responses=(proto.mode_frame(STOP),))  # answers STOP, does nothing
        return real_handle(frame, device, now)

    port._handler.handle = handle_without_stopping
    with pytest.raises(ConfiguratorError, match="I: sensor did not apply"):
        configurator.apply_profile(AMS_PROFILE)
    assert port.commands()[-1] == proto.CMD_SET_MODE  # back to RUN even after the failure
    assert port.device.mode is RUN


def test_store_refused_is_reported_and_the_sensor_restarts(configurator, port):
    port.rewrite = lambda f: proto.store_frame(False, 1) if f.data[0] == proto.RESP_STORE else f
    with pytest.raises(ConfiguratorError, match="STORE refused"):
        configurator.apply_profile(SensorProfile(channels={}, error_mask_reporting=False))
    assert port.device.mode is RUN


def test_read_back_mismatch_is_reported(configurator, port):
    def disabled_on_read_back(frame):
        if frame.data[0] == 0xA6 and port.commands()[-1] == proto.CMD_GET_CONFIG | Mux.AS:
            return proto.config_result_frame(Mux.AS, ChannelConfig(TriggerMode.DISABLED, 30))
        return frame

    port.rewrite = disabled_on_read_back
    with pytest.raises(ConfiguratorError, match="AS: read back"):
        configurator.apply_profile(AMS_PROFILE)


def test_refused_command_is_reported(configurator, port):
    port.rewrite = lambda f: proto.error_frame(0x32) if f.data[0] == proto.RESP_STORE else f
    with pytest.raises(ConfiguratorError, match="refused command 0x32"):
        configurator.apply_profile(AMS_PROFILE)
    assert port.device.mode is RUN


def test_silent_sensor_times_out(configurator, port):
    port.silent = True
    t0 = port.clock.now()
    with pytest.raises(ConfiguratorError, match="no response to command 0x74 within 1.0 s"):
        configurator.read_identity()
    assert port.clock.now() - t0 == pytest.approx(1.0)


# --- reset_log_since_reset ----------------------------------------------------------


def test_reset_log_since_reset_clears_it_and_restarts(configurator, port):
    sample = LogSample(5000.0, 25.0, 10.0, True, False, False, charge_counter_active=True)
    port.device.log_since_reset.update(sample)
    port.device.log_overall.update(sample)
    configurator.reset_log_since_reset()
    assert port.device.log_since_reset.value(LogItem.AS_OVERALL) == 0
    assert port.device.log_overall.value(LogItem.AS_OVERALL) == 50  # only Isabellenhuette clears this one
    assert port.device.mode is RUN
    assert port.commands() == [0x7B, 0x34, 0x30, 0x34]
    assert port.sent[2].frame.data[3:7] == bytes([0x0A, 0x0B, 0x0C, 0x0D])
