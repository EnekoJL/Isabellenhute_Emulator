# MEMORY.md — IVT-S emulator: state, learnings, roadmap

Update this file in the same commit as every change (see `CLAUDE.md` §0).

---

## 1. Current state

* **Last update:** 2026-10-18 (Claude). Datasheet-accuracy review applied
  (commit "feat: behave like the real IVT-S").
* **Sensor of the team:** **IVT-S-1K-U0-I-CAN1-12/24**, material number 164513, 2 units
  (delivery note 80703759/10, 2024-05-03; user, 2026-10-18). Exactly the emulated
  variant: 1000 A, no voltage channels, CAN1 (terminated), 12/24 V
  (`DEVICE_ID` = `B9 02 3E 80 03 01 01 00`).
  1000 A implies: overcurrent range ±12 200 A (results saturate there), extended
  range above 1000 A (state bit 1, back below 950 A), resolution 47 mA, offset
  125 mA, noise 70 mA RMS (noise/offset not emulated).
* **2026-11-18: configurator periods configurable** (user: «que no sea hardcoded»): `ams_profile(current_ms, temperature_ms, charge_ms)` (defaults 20 / 1000 / 100 = what the AMS firmware expects, `AMS_PROFILE` = defaults), `SensorProfile` refuses > 1000 msg/s (datasheet 8.1), CLI `apply-ams --current-ms --temperature-ms --charge-ms` (bad values → exit 2 before connecting; warning when I ≠ 20 ms). 651 pytest.
* **2026-11-18: configurator `isascale-configure`** (AMS user: «quiero el Ah counter y el de temperatura»): client side of the protocol in pure `domain/ivt_commands.py`, `application/sensor_configurator.py` (`SensorConfigurator`: `read_identity`, `read_settings`, `apply_profile`, `reset_log_since_reset`; STOP only inside a context manager that always returns to RUN; every command waits for its own response, skips results), `AMS_PROFILE` (I 20 ms, T 1 s, As 100 ms cyclic, error bits on), CLI `configurator_cli.py` (`info`, `apply-ams`, `reset-log --yes`). Tested against the emulator's own command handler (`fakes.EmulatedSensorPort`) and end to end on the virtual bus with the emulator thread. REQUIREMENTS F-20, D-9.
* **Tests:** 651 pytest, all passing (2026-11-18, + configurable periods); 640 with the configurator; before: 596 (2026-11-18: + `tests/unit/test_ams_firmware_contract.py`, the same 0x521 golden frames the AMS firmware decodes in `AMS_ivt_parser`); `domain/` and `application/` 100 % lines.
* **Behaviour now modelled (datasheet 1.03):**
  * Power on = 400 ms silent → alive `0xBF` → first result one interval later.
    GUI Stop = power off (no answers, RX drained).
  * Factory defaults: only I (20 ms) cyclic; T, As disabled. GUI form = what is
    stored in the sensor; BMS changes over CAN are "active" until `STORE`.
  * I result = mean over the measurement interval; clamp ±12 200 A; OCS from the
    `0x35`/`0x36` thresholds; bits 2/3 from error counters only with Config bit 5.
  * Full command set of chapter 8 (`0x1n`…`0x7C`), STOP-only rules, serial-number
    addressing, delayed responses (`0x30` 1.2 s, `STORE` 0.2 s), restarts (`0x3F`,
    `0x3D` factory, `0x3A` bitrate with reconnect), Reset Watchdog counter, log data.
  * Little endian / sign inversion per channel; configurable CAN IDs; trigger mode.
* **Assumptions (datasheet silent), REQUIREMENTS D-7:** Set CAN ID applies at once
  (in STOP); `0x3D` keeps the bitrate; STORE answers after 200 ms; OCS releases
  below the reset threshold (or the set threshold if reset = 0); wrong serial =
  silence; `SW_VERSION` 1.0.0 / 2022-06-09 and `ARTICLE_NUMBER` 0 are placeholders.

## 2. Important facts

* Datasheet: `docs/datasheets/IVT-S_Datasheet_V1.03.pdf`; chapter 8 = CAN (pages
  19–41), chapter 9 = start-up, 5.1 start-up time 350–400 ms, 5.3 ranges.
* Defaults (8.1): command `0x411`, response `0x511`, results `0x521`…`0x528`,
  500 kbit/s, big endian, result DLC 6, response DLC 8 (unused bytes 0x00).
* "Each defined command will report its response even if not allowed" (8.1):
  STOP-only commands sent in RUN are answered with the unchanged value.
* The datasheet's system-error lists disagree (0x41 vs 0x81 tables); the emulator
  uses the 0x81 response numbering (Reset Watchdog = 0x0F, bitmask DB3 bit 6).
* Sign convention of the emulator: + = discharge, − = charge (regen). The real
  sensor's sign depends on how it is mounted; Config bit 7 inverts it.

## 3. Learnings

1. **No PDF tools in WSL** (`pdftotext`, `pdftoppm` missing, so the Read tool can't
   render PDFs either). *Fix:* `pypdf` in a scratch venv,
   `extract_text(extraction_mode="layout")`.
2. **First result one interval after start** changed every "N frames in T" test:
   with `run_for` half-open, use `T + 0.001`.
3. **Averaging over the interval** makes a step change show a half-way value in the
   first frame after it; tests that read the last frame after a change must let
   one full interval pass.

## 4. Next steps

* Run `isascale-configure --interface ixxat apply-ams` on the team's real IVT-S (AMS board test E-2), then `info`; check whether `reset-log` zeroes the `0x527` As result and what As does after a power cut (stored every 15 min).
* Validate the D-7 assumptions with the real sensor on the bench (Set CAN ID timing,
  bit 3 after restart, STORE time, start-up time) and read its real `DEVICE_ID`,
  `SW_VERSION` and `ARTICLE_NUMBER` (maybe the material number 164513; encoding
  unknown, so the placeholder stays 0 until read from the sensor).
* Optional realism, not done: measurement noise/offset/resolution (47 mA in the
  nominal range, 376 mA in the extended range for 1000 A); temperature-driven
  system errors (≥ 105 °C / ≤ −40 °C); U3 variant (U1..U3, W, Wh results).
* Once the team's CAN map exists (AMS backlog Q3/P4), set the IDs the bike uses.
