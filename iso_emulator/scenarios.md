# Isolation Sensor Scenarios

Predefined test cases with realistic sensor values and status flags.

## Normal Operation
```
Isolation resistance > 1000 kΩ (safe)
Safe-to-start: ENABLED
Threshold: VALID
Voltage: VALID, Current: VALID, Temp: VALID
```

**Use case:** Baseline healthy system state. Safe to energize.

```bash
python main.py --scenario normal
```

---

## Charging (100A @ 35°C)
```
Isolation: 1200 kΩ (slightly lower under load)
Battery: 400V, Current: +100A
Temperature: 35°C (elevated under load)
Safe-to-start: SAFE
```

**Use case:** Active charging cycle with elevated temperature due to I²R losses.

```bash
python main.py --scenario charging
```

---

## Discharging (-80A @ 30°C)
```
Isolation: 1600 kΩ (improves as current flows)
Battery: 350V (discharging), Current: -80A
Temperature: 30°C
Safe-to-start: SAFE
```

**Use case:** Discharge operation, isolation actually improves slightly.

```bash
python main.py --scenario discharging
```

---

## Warning Threshold (800 kΩ)
```
Isolation: 800 kΩ (below nominal but above critical)
Threshold: WARN
Safe-to-start: NOT_SAFE
```

**Use case:** Degradation detected (e.g., moisture ingress). Prevents start but system not dead.

```bash
python main.py --scenario warning
```

---

## Critical Isolation (100 kΩ)
```
Isolation: 100 kΩ (critical fault)
Threshold: ERR
Safe-to-start: NOT_SAFE
```

**Use case:** Imminent short circuit. Must power down immediately.

```bash
python main.py --scenario low_iso
```

---

## Over Temperature (85°C)
```
Isolation: 1000 kΩ (nominal)
Temperature: 85°C (max safe limit)
Temp status: OT (Over Temperature)
Safe-to-start: SAFE (but thermal limit approaching)
```

**Use case:** Thermal alarm active. Monitor cooling; may derate power.

```bash
python main.py --scenario over_temp
```

---

## Startup (Resistance Measurement in Progress)
```
Isolation: 0 kΩ (not yet measured)
Res status: STARTUP
Safe-to-start: RUNNING (measurement active)
Threshold: NE (Not Executed)
```

**Use case:** Cold boot. Isolation sensor measuring resistance. Block load until complete.

```bash
python main.py --scenario startup
```

---

## Fault (Sensor Error)
```
All values: 0
Voltage status: ERROR
Temp status: ERROR
Safe-to-start: NOT_SAFE
```

**Use case:** Hardware failure (sensor disconnected, CAN dead, etc.). System must fail-safe.

```bash
python main.py --scenario fault
```

---

## Custom Scenario

Create new scenario in `main.py` SCENARIOS dict:

```python
SCENARIOS = {
    ...
    "custom": {
        "battery_V": 400.0,
        "current_A": 50.0,
        "iso_total_kohm": 2000,
        "temp_C": 40,
        "safe_to_start": SafeToStart.SAFE,
        "res_threshold": ResThreshold.VALID,
        "noise_scale": 0.02,
    }
}
```

Then:
```bash
python main.py --scenario custom
```

---

## Transition Testing

Simulate gradual degradation:

```bash
# Start healthy
python main.py --scenario normal &

# (after monitoring 30s)
# Kill and restart with warning
pkill main.py
python main.py --scenario warning &

# (monitor 30s)
# Critical
pkill main.py
python main.py --scenario low_iso
```

Monitor with:
```bash
python ../iso_monitor/main.py
```
