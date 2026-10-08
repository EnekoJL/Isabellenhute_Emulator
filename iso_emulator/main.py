#!/usr/bin/env python3
"""
Isolation Sensor Emulator — transmits simulated IVT CAN messages via PCAN.

Usage:
    python main.py [--channel PCAN_USBBUS1] [--bitrate 500000] [--rate 10]

Options:
    --channel PCAN_USBBUS1   PCAN interface (default: PCAN_USBBUS1)
    --bitrate 500000         CAN bitrate in bps (default: 500000)
    --rate 10                Message group TX rate in Hz (default: 10)
    --scenario normal        Simulation scenario: normal, fault_current, over_temp, low_iso, etc.

Requirements:
    pip install python-can
    PEAK PCAN driver installed
"""

import argparse
import sys
import signal
import time
import can
from pathlib import Path

from sensor_emulator import (
    IsolationSensorEmulator,
    SensorReadings,
    CurrentStatus,
    VoltageStatus,
    ResThreshold,
    SafeToStart,
    ResStatus,
    TempStatus,
)


SCENARIOS = {
    "normal": {
        "battery_V": 400.0,
        "link_plus_V": 200.0,
        "link_minus_V": -200.0,
        "pack_plus_V": 200.0,
        "pack_minus_V": -200.0,
        "current_A": 0.0,
        "iso_total_kohm": 1500,
        "iso_pos_kohm": 3000,
        "iso_neg_kohm": 3000,
        "iso_pack_kohm": 7000,
        "iso_link_kohm": 7000,
        "temp_C": 25,
        "noise_scale": 0.02,
        "safe_to_start": SafeToStart.SAFE,
        "res_threshold": ResThreshold.VALID,
        "res_status": ResStatus.VALID,
        "voltage_status": VoltageStatus.VALID,
    },
    "charging": {
        "battery_V": 400.0,
        "link_plus_V": 200.0,
        "link_minus_V": -200.0,
        "pack_plus_V": 200.0,
        "pack_minus_V": -200.0,
        "current_A": 100.0,
        "iso_total_kohm": 1200,
        "iso_pos_kohm": 2500,
        "iso_neg_kohm": 2500,
        "iso_pack_kohm": 6000,
        "iso_link_kohm": 6000,
        "temp_C": 35,
        "noise_scale": 0.03,
        "safe_to_start": SafeToStart.SAFE,
        "res_threshold": ResThreshold.VALID,
        "res_status": ResStatus.VALID,
    },
    "discharging": {
        "battery_V": 350.0,
        "link_plus_V": 175.0,
        "link_minus_V": -175.0,
        "pack_plus_V": 175.0,
        "pack_minus_V": -175.0,
        "current_A": -80.0,
        "iso_total_kohm": 1600,
        "iso_pos_kohm": 3200,
        "iso_neg_kohm": 3200,
        "iso_pack_kohm": 8000,
        "iso_link_kohm": 8000,
        "temp_C": 30,
        "noise_scale": 0.02,
        "safe_to_start": SafeToStart.SAFE,
        "res_threshold": ResThreshold.VALID,
        "res_status": ResStatus.VALID,
    },
    "warning": {
        "battery_V": 400.0,
        "link_plus_V": 200.0,
        "link_minus_V": -200.0,
        "pack_plus_V": 200.0,
        "pack_minus_V": -200.0,
        "current_A": 0.0,
        "iso_total_kohm": 800,
        "iso_pos_kohm": 1500,
        "iso_neg_kohm": 1500,
        "iso_pack_kohm": 4000,
        "iso_link_kohm": 4000,
        "temp_C": 25,
        "noise_scale": 0.02,
        "safe_to_start": SafeToStart.NOT_SAFE,
        "res_threshold": ResThreshold.WARN,
        "res_status": ResStatus.VALID,
    },
    "low_iso": {
        "battery_V": 400.0,
        "link_plus_V": 200.0,
        "link_minus_V": -200.0,
        "pack_plus_V": 200.0,
        "pack_minus_V": -200.0,
        "current_A": 0.0,
        "iso_total_kohm": 100,
        "iso_pos_kohm": 200,
        "iso_neg_kohm": 200,
        "iso_pack_kohm": 500,
        "iso_link_kohm": 500,
        "temp_C": 25,
        "noise_scale": 0.01,
        "safe_to_start": SafeToStart.NOT_SAFE,
        "res_threshold": ResThreshold.ERR,
        "res_status": ResStatus.VALID,
    },
    "over_temp": {
        "battery_V": 400.0,
        "link_plus_V": 200.0,
        "link_minus_V": -200.0,
        "pack_plus_V": 200.0,
        "pack_minus_V": -200.0,
        "current_A": 0.0,
        "iso_total_kohm": 1000,
        "iso_pos_kohm": 2000,
        "iso_neg_kohm": 2000,
        "iso_pack_kohm": 5000,
        "iso_link_kohm": 5000,
        "temp_C": 85,
        "noise_scale": 0.02,
        "safe_to_start": SafeToStart.SAFE,
        "res_threshold": ResThreshold.VALID,
        "temp_status": TempStatus.OT,
    },
    "startup": {
        "battery_V": 400.0,
        "link_plus_V": 200.0,
        "link_minus_V": -200.0,
        "pack_plus_V": 200.0,
        "pack_minus_V": -200.0,
        "current_A": 0.0,
        "iso_total_kohm": 0,
        "iso_pos_kohm": 0,
        "iso_neg_kohm": 0,
        "iso_pack_kohm": 0,
        "iso_link_kohm": 0,
        "temp_C": 25,
        "noise_scale": 0.02,
        "safe_to_start": SafeToStart.RUNNING,
        "res_threshold": ResThreshold.NE,
        "res_status": ResStatus.STARTUP,
    },
    "fault": {
        "battery_V": 0.0,
        "link_plus_V": 0.0,
        "link_minus_V": 0.0,
        "pack_plus_V": 0.0,
        "pack_minus_V": 0.0,
        "current_A": 0.0,
        "iso_total_kohm": 0,
        "iso_pos_kohm": 0,
        "iso_neg_kohm": 0,
        "iso_pack_kohm": 0,
        "iso_link_kohm": 0,
        "temp_C": 25,
        "safe_to_start": SafeToStart.NOT_SAFE,
        "res_threshold": ResThreshold.ERR,
        "temp_status": TempStatus.ERROR,
        "voltage_status": VoltageStatus.ERROR,
    },
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Isolation Sensor CAN Emulator",
        epilog="Scenarios: " + ", ".join(SCENARIOS.keys())
    )
    p.add_argument(
        "--channel", default="PCAN_USBBUS1",
        help="PCAN interface (default: PCAN_USBBUS1)"
    )
    p.add_argument(
        "--bitrate", type=int, default=500000,
        help="CAN bitrate in bps (default: 500000)"
    )
    p.add_argument(
        "--rate", type=float, default=10.0,
        help="Message group TX rate in Hz (default: 10)"
    )
    p.add_argument(
        "--scenario", default="normal", choices=list(SCENARIOS.keys()),
        help="Simulation scenario (default: normal)"
    )
    p.add_argument(
        "--no-noise", action="store_true",
        help="Disable sensor noise simulation"
    )
    return p.parse_args()


class SensorEmulatorRunner:
    def __init__(self, bus: can.BusABC, rate_hz: float, scenario: dict, no_noise: bool = False):
        self.bus = bus
        self.rate_hz = rate_hz
        self.interval = 1.0 / rate_hz
        self.running = True
        self.tx_count = 0
        self.tx_bytes = 0
        self.start_time = time.time()

        readings = SensorReadings(**{k: v for k, v in scenario.items() if k != "noise_scale"})
        self.emulator = IsolationSensorEmulator(readings)
        self.emulator.noise_enabled = not no_noise
        if "noise_scale" in scenario:
            self.emulator.noise_scale = scenario["noise_scale"]

    def run(self) -> None:
        print(f"Transmitting at {self.rate_hz} Hz… Press Ctrl+C to exit.")

        next_send = time.time()
        while self.running:
            now = time.time()

            if now >= next_send:
                self._send_message_group()
                next_send = now + self.interval

            time.sleep(min(0.001, self.interval / 10))

    def _send_message_group(self) -> None:
        """Send all 8 isolation sensor messages."""
        messages = self.emulator.make_all_messages()

        for msg_id, data in messages:
            msg = can.Message(
                arbitration_id=msg_id,
                data=data,
                is_extended_id=True,
                is_fd=False
            )
            try:
                self.bus.send(msg)
                self.tx_count += 1
                self.tx_bytes += len(data)
            except can.CanOperationError as e:
                print(f"TX error: {e}", file=sys.stderr)
                self.running = False
                break

    def stop(self) -> None:
        self.running = False
        elapsed = time.time() - self.start_time
        print(f"\nStopped. TX {self.tx_count} messages ({self.tx_bytes} bytes) in {elapsed:.2f}s")


def main() -> None:
    args = parse_args()

    print(f"Opening {args.channel} at {args.bitrate} bps with {args.scenario} scenario…")
    if args.no_noise:
        print("Noise simulation disabled.")

    try:
        bus = can.Bus(
            interface="pcan",
            channel=args.channel,
            bitrate=args.bitrate,
        )
    except can.CanInitializationError as exc:
        print(f"ERROR: Could not open CAN bus: {exc}", file=sys.stderr)
        sys.exit(1)

    runner = SensorEmulatorRunner(
        bus,
        rate_hz=args.rate,
        scenario=SCENARIOS[args.scenario],
        no_noise=args.no_noise
    )

    def _stop(sig, frame):
        runner.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        runner.run()
    finally:
        bus.shutdown()
        print("Bus closed.")


if __name__ == "__main__":
    main()
