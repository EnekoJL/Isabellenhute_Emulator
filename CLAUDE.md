# CLAUDE.md — Rules for Claude in the IVT-S emulator repository

CAN emulator of the **Isabellenhütte IVT-S current sensor** (the team's unit is the
**1000 A** version; variant emulated: U0, current only) for bench, HIL and telemetry
tests of the electric racing motorbike. Python ≥ 3.11, python-can (IXXAT on
Windows, virtual bus elsewhere), PySide6 GUI, pytest.

This repo is a git submodule of the AMS firmware repo (`tools/Isabellenhute_Emulator`
in `AMS_GitHub`). The AMS repo's rules (`AMS_GitHub/CLAUDE.md`) apply where this
file says nothing.

@MEMORY.md

---

## 0. Session protocol

**At the start:** `git status -sb` and `git pull`; read `MEMORY.md` §1 (state) and
§4 (next steps).

**At the end of every completed change — same commit:**
1. Tests pass (§2).
2. Docs updated: `README.md`, `docs/REQUIREMENTS.md` (requirements F-xx, decisions
   D-x, open points), `docs/IMPLEMENTATION_PLAN.md` (files and test plan).
3. **`MEMORY.md` updated** (state, learnings, next steps).

Then, in the parent repo, bump the submodule pointer and note it in the parent's
`MEMORY.md` (only those files: other agents work there in parallel, never
`git add -A` in the parent).

---

## 1. Source of truth: the datasheet

* `docs/datasheets/IVT-S_Datasheet_V1.03.pdf` (chapter 8 CAN, 9 start-up). Same file
  as `AMS_GitHub/docs/datasheets/current_sensor/Datasheet IVT-S V1.03.pdf`.
  **If the code or the docs disagree with the datasheet, the datasheet wins.**
* Goal set by the user (2026-10-18): **behave as close as possible to the real
  sensor.** Where the datasheet is silent, pick the least surprising behaviour,
  write it in `docs/REQUIREMENTS.md` D-7 ("assumptions") and in `MEMORY.md`.
* No PDF tools in WSL: extract text with `pypdf` in a throw-away venv in the
  scratchpad (`pdftotext`/`pdftoppm` are not installed).

## 2. Tests (mandatory, zero failures)

```bash
.venv/bin/python -m pytest -q                                  # all (GUI smoke uses offscreen Qt)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --cov=isascale --cov-report=term-missing
.venv/bin/python -m isascale --interface virtual --headless --profile wot --duration 3
```

* Every change to `domain/` or `application/` needs tests; keep both at **100 %
  line coverage** (presenter ≥ 99 %).
* Test fixtures: `config` = `fakes.ALL_CHANNELS` (I, T, As on, **0 ms start-up**) so
  scheduling tests stay short. Datasheet defaults (only I, 400 ms start-up) get their
  own tests (`tests/integration/test_sensor_behaviour.py`).
* `run_for(service, timer, d)` is half-open: a frame due exactly at `d` is **not**
  sent. The first result comes one interval after start, so "N frames in N × period"
  needs `N × period + 0.001`.

## 3. Architecture (hexagonal + MVP)

* `domain/` pure (no third-party imports): `models.py` (config, settings, enums),
  `ivt_protocol.py` (all encoders/decoders), `sensor_state.py` (error counters, log
  book, OCS detector, range tracker), `accumulator.py`.
* `application/`: `bms_requests.py` (command handler: edits `DeviceState`, returns
  responses + side effects), `emulator_service.py` (power, boot, scheduling,
  measurement; the only owner of time and of the CAN port), sources, use cases.
* `ports/` ABCs; `infrastructure/` python-can, pandas, threads; `presentation/`
  presenter without Qt + Qt widgets that only paint view models.
* Only `infrastructure/` imports `can`/`pandas`; only `presentation/` imports Qt;
  `bootstrap.py` is the composition root.

## 4. Style

* English for code, comments and new docs. Existing `README.md` and `docs/*.md` are
  in Spanish: keep the language of the file you edit.
* Comments cite the datasheet section (`# datasheet 8.4`).
* Talk to the user in Spanish, short and concrete.

## 5. Environment

* WSL checkout: `/home/eneko/workdir/AMS_GitHub/tools/Isabellenhute_Emulator`
  (private `.venv` with the `gui,dev` extras). No ruff in `.venv`: install it in a
  scratch venv if needed (`ruff check --select F,E,W --line-length 120`).
* Windows launcher: `AMS_GitHub/windows/isabellenhute/`.
