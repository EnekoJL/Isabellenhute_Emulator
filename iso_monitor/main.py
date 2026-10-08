#!/usr/bin/env python3
"""
Isolation Sensor Monitor — reads IVT CAN frames via PCAN and displays live data.

Usage:
    python main.py [--channel PCAN_USBBUS1] [--bitrate 500000]

Requirements:
    pip install python-can rich
    PEAK PCAN driver installed (pcan.sys / libpcanbasic.so)
"""

import argparse
import sys
import signal
import can

from isolation_sensor import IsolationSensorParser
from display import SensorDisplay


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Isolation Sensor CAN Monitor")
    p.add_argument("--channel",  default="PCAN_USBBUS1",
                   help="PCAN channel (default: PCAN_USBBUS1)")
    p.add_argument("--bitrate",  type=int, default=500000,
                   help="CAN bitrate in bps (default: 500000)")
    p.add_argument("--timeout",  type=float, default=0.1,
                   help="Receive timeout in seconds (default: 0.1)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Opening {args.channel} at {args.bitrate} bps …")

    try:
        bus = can.Bus(
            interface="pcan",
            channel=args.channel,
            bitrate=args.bitrate,
        )
    except can.CanInitializationError as exc:
        print(f"ERROR: Could not open CAN bus: {exc}", file=sys.stderr)
        sys.exit(1)

    parser  = IsolationSensorParser()
    running = True

    def _stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    print("Listening… Press Ctrl+C to exit.")

    with SensorDisplay(refresh_per_second=10) as display:
        while running:
            msg = bus.recv(timeout=args.timeout)
            if msg is None:
                display.update(parser.state)
                continue

            parser.process(msg.arbitration_id, bytes(msg.data))
            display.update(parser.state)

    bus.shutdown()
    print("Bus closed.")


if __name__ == "__main__":
    main()
