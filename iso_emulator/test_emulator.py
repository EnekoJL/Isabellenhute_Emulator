#!/usr/bin/env python3
"""
Basic test of emulator encoding/decoding.
Verify messages can be created and would parse correctly.
"""

from sensor_emulator import (
    IsolationSensorEmulator,
    SensorReadings,
    MSG_IVT_HVBATTERY,
    VOLTAGE_RESOLUTION,
    VOLTAGE_OFFSET,
    CURRENT_RESOLUTION,
    CURRENT_OFFSET,
)


def _decode_voltage(raw: int) -> float:
    """Inverse of emulator encoding for verification."""
    return raw * VOLTAGE_RESOLUTION + VOLTAGE_OFFSET


def _decode_current(raw: int) -> float:
    """Inverse of emulator encoding for verification."""
    return raw * CURRENT_RESOLUTION + CURRENT_OFFSET


def test_hvbattery():
    """Test HV Battery message encoding."""
    readings = SensorReadings(
        battery_V=400.0,
        current_A=50.0,
    )
    emulator = IsolationSensorEmulator(readings)
    emulator.noise_enabled = False

    msg_id, data = emulator.make_hvbattery()
    assert msg_id == MSG_IVT_HVBATTERY
    assert len(data) == 8

    # Decode current (24-bit, little-endian across bytes)
    raw_i  = (data[1] & 0xF0) >> 4
    raw_i |= data[2] << 4
    raw_i |= data[3] << 12
    raw_i |= (data[4] & 0x0F) << 20

    decoded_current = _decode_current(raw_i)
    assert abs(decoded_current - 50.0) < 0.1, f"Current mismatch: {decoded_current} vs 50.0"

    # Decode voltage (20-bit, little-endian)
    raw_v  = data[5]
    raw_v |= data[6] << 8
    raw_v |= (data[7] & 0x0F) << 16

    decoded_voltage = _decode_voltage(raw_v)
    assert abs(decoded_voltage - 400.0) < 0.1, f"Voltage mismatch: {decoded_voltage} vs 400.0"

    print(f"✓ HV Battery: I={decoded_current:.3f}A (raw={raw_i}), V={decoded_voltage:.3f}V (raw={raw_v})")


def test_voltage_link():
    """Test Voltage Link message encoding."""
    readings = SensorReadings(
        link_plus_V=200.0,
        link_minus_V=-200.0,
    )
    emulator = IsolationSensorEmulator(readings)
    emulator.noise_enabled = False

    msg_id, data = emulator.make_voltagelink()
    assert len(data) == 8

    # Decode link_plus
    raw  = (data[1] & 0xF0) >> 4
    raw |= data[2] << 4
    raw |= data[3] << 12
    v_plus = _decode_voltage(raw)

    # Decode link_minus
    raw  = (data[4] & 0xF0) >> 4
    raw |= data[5] << 4
    raw |= data[6] << 12
    v_minus = _decode_voltage(raw)

    assert abs(v_plus - 200.0) < 0.1, f"Link+ mismatch: {v_plus} vs 200.0"
    assert abs(v_minus - (-200.0)) < 0.1, f"Link- mismatch: {v_minus} vs -200.0"

    print(f"✓ Voltage Link: V+={v_plus:.3f}V, V-={v_minus:.3f}V")


def test_resistance():
    """Test resistance message encoding."""
    readings = SensorReadings(
        iso_total_kohm=500,
        iso_pos_kohm=1000,
        iso_neg_kohm=1500,
    )
    emulator = IsolationSensorEmulator(readings)

    # IsoResTotal
    msg_id, data = emulator.make_isorestotal()
    assert len(data) == 8
    raw16 = data[3] | (data[4] << 8)
    decoded_total = raw16 // 5
    assert decoded_total == 500, f"Total resistance mismatch: {decoded_total} vs 500"

    # IsoResPosNeg
    msg_id, data = emulator.make_isoresposneg()
    assert len(data) == 6
    raw16  = data[2] | (data[3] << 8)
    decoded_pos = raw16 // 2
    raw16  = data[4] | (data[5] << 8)
    decoded_neg = raw16 // 2
    assert decoded_pos == 1000, f"Pos resistance mismatch: {decoded_pos} vs 1000"
    assert decoded_neg == 1500, f"Neg resistance mismatch: {decoded_neg} vs 1500"

    print(f"✓ Resistance: Total={decoded_total}kΩ, Pos={decoded_pos}kΩ, Neg={decoded_neg}kΩ")


def test_temperature():
    """Test temperature message encoding."""
    readings = SensorReadings(temp_C=45)
    emulator = IsolationSensorEmulator(readings)

    msg_id, data = emulator.make_temperature()
    assert len(data) == 3
    raw = (data[1] & 0xF0) >> 4
    raw |= (data[2] & 0x0F) << 4
    decoded_temp = raw - 50
    assert decoded_temp == 45, f"Temperature mismatch: {decoded_temp} vs 45"

    print(f"✓ Temperature: {decoded_temp}°C")


def test_counters():
    """Test message counter increment."""
    emulator = IsolationSensorEmulator()
    initial = emulator.counters.hvbattery

    for _ in range(20):
        emulator.make_hvbattery()

    final = emulator.counters.hvbattery
    assert (final - initial) % 16 == 4, "Counter should wrap at 16"
    print(f"✓ Counters: {initial} → {final} (wrapped correctly)")


if __name__ == "__main__":
    test_hvbattery()
    test_voltage_link()
    test_resistance()
    test_temperature()
    test_counters()
    print("\n✓ All tests passed!")
