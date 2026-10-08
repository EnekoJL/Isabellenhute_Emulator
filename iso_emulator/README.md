# Isolation Sensor CAN Emulator

Python project that emulates the IVT isolation sensor by transmitting simulated CAN messages via PCAN. Mirrors the firmware behavior from `isolation_sensor.c`.

## Overview

This emulator generates and transmits 8 CAN messages that replicate the isolation sensor protocol:
- HV Battery voltage & current
- Link Plus/Minus voltages
- Pack Plus/Minus voltages
- PreCharge voltage difference & voltage
- Total isolation resistance
- Positive/Negative isolation resistance
- Pack/Link isolation resistance
- Temperature

Each message includes a rolling 4-bit counter and status flags. All encoding matches the firmware's binary format exactly.

## Installation

```bash
pip install -r requirements.txt
```

Requires PEAK PCAN driver:
- **Linux**: `libpcanbasic.so` (from PCAN driver package)
- **Windows**: `pcan.sys` (from PEAK installer)
- **macOS**: Limited support; check PEAK documentation

## Usage

### Basic (normal scenario)
```bash
python main.py
```

### Custom bitrate & interface
```bash
python main.py --channel PCAN_USBBUS2 --bitrate 500000 --rate 20
```

### Scenarios
Predefined test scenarios with realistic isolation resistance & status flags:

| Scenario | V Batt | I | Iso Res | Status | Safe to Start |
|----------|--------|----|---------|---------|----|
| **normal** | 400V | 0A | 1500 kΩ | VALID | SAFE |
| **charging** | 400V | +100A | 1200 kΩ | VALID | SAFE |
| **discharging** | 350V | -80A | 1600 kΩ | VALID | SAFE |
| **warning** | 400V | 0A | 800 kΩ | WARN | NOT_SAFE |
| **low_iso** | 400V | 0A | 100 kΩ | ERROR | NOT_SAFE |
| **over_temp** | 400V | 0A | 1000 kΩ | VALID (temp OT) | SAFE |
| **startup** | 400V | 0A | 0 kΩ | STARTUP | RUNNING |
| **fault** | 0V | 0A | 0 kΩ | ERROR | NOT_SAFE |

Normal case meets safety requirements: >1000 kΩ isolation, all voltages valid, safe-to-start enabled.

Example:
```bash
python main.py --scenario over_temp --rate 5
```

## Message Format

All messages are 8-bit extended CAN frames. Encoding rules:

### Voltage Encoding (20-bit raw → 3 bytes)
- Raw value range: 0x00000–0xFFFFF (0–1,048,575)
- Conversion: `voltage_V = raw * 0.004 - 2097.152`
- Extraction from message: `buf[1] upper nibble, buf[2], buf[3] lower nibble`

### Current Encoding (24-bit raw → 3 bytes)
- Raw value range: 0x000000–0xFFFFFF (0–16,777,215)
- Conversion: `current_A = raw * 0.002 - 16777.216`
- Extraction: `buf[1] upper nibble, buf[2], buf[3], buf[4] lower nibble`

### Resistance Encoding (16-bit raw → 2 bytes, little-endian)
- Total: `raw / 5`
- Pos/Neg: `raw / 2`
- Pack/Link: `raw / 2`

### Temperature Encoding (8-bit raw → 1.5 bytes)
- Formula: `temp_C = raw - 50`
- Range: −50°C to +205°C

## Message IDs

| Message | ID | Len | Update Rate |
|---------|----|----|------------|
| HV Battery (current + voltage) | 0x1000 | 8 | ~1/group |
| Voltage Link (±) | 0x1010 | 8 | ~1/group |
| Voltage Pack (±) | 0x1020 | 8 | ~1/group |
| PreCharge (diff + voltage) | 0x1030 | 8 | ~1/group |
| ISO Resistance Total | 0x1040 | 8 | ~1/group |
| ISO Resistance Pos/Neg | 0x1050 | 6 | ~1/group |
| ISO Resistance Pack/Link | 0x1060 | 6 | ~1/group |
| Temperature | 0x1070 | 3 | ~1/group |

Each message contains a 4-bit counter (byte[1] bits 0–3) that increments per message type.

## Options

```
--channel PCAN_USBBUS1    PCAN interface to use (default: PCAN_USBBUS1)
--bitrate 500000          CAN bitrate in bps (default: 500000)
--rate 10                 Message group TX rate in Hz (default: 10)
--scenario normal         Simulation scenario (default: normal)
--no-noise                Disable simulated sensor noise
```

## Architecture

### `sensor_emulator.py`
- **`SensorReadings`**: Dataclass holding simulated sensor values
- **`IsolationSensorEmulator`**: Encodes readings into CAN message bytes
  - Handles voltage/current/resistance/temperature conversions
  - Manages 4-bit message counters
  - Optional noise injection (±2% Gaussian by default)
  - Message factory methods for each CAN frame type

### `main.py`
- **`SensorEmulatorRunner`**: TX loop + statistics
- Predefined scenarios for common test cases
- Signal handling for clean shutdown

## Testing

Use with the companion monitor (iso_monitor/) to visualize emulated data:

```bash
# Terminal 1: Run emulator
python iso_emulator/main.py --scenario charging

# Terminal 2: Run monitor
python iso_monitor/main.py
```

The monitor will display live sensor readings and verify message sequence integrity.

## Notes

- Messages are sent as groups (all 8 at once) at the specified rate
- Counters wrap at 16 (0x0F) per message type
- Noise is Gaussian (±std dev) on each sensor value; disabled with `--no-noise`
- Status flags (voltage/current/temp status) default to VALID; set via scenarios
- Extended CAN ID format (29-bit) required

## Firmware Reference

Emulator behavior mirrors:
- `isolation_sensor.c` — message parsing and status enums
- `isolation_sensor.h` — CAN message IDs and conversion macros

See `../iso_monitor/isolation_sensor.py` for the inverse (message parsing).
