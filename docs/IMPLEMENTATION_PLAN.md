# Plan de implementación — isascale-emulator

Requisitos: [REQUIREMENTS.md](REQUIREMENTS.md). Roles: **arquitecto** (domain, ports, application,
este plan), **developer** (infrastructure, presentation, arranque, README), **pytest** (tests/).

## 1. Capas y dependencias

```
presentation (PySide6) ──┐
__main__ / bootstrap ────┼──► application ──► ports (ABC) ◄── infrastructure (python-can, pandas, threads)
                         │         │
                         └─────────┴──► domain (puro, sin imports externos)
```

Regla: solo `infrastructure/` importa `can`, `pandas`, `numpy`. Solo `presentation/` importa Qt.
`__main__.py`/`bootstrap.py` es la raíz de composición: único sitio que instancia adaptadores concretos.

## 2. Árbol (raíz del repo = raíz del proyecto)

```
pyproject.toml  README.md  docs/
src/isascale/
  __init__.py  __main__.py  bootstrap.py
  domain/        models.py  ivt_protocol.py  accumulator.py          [HECHO - arquitecto]
  ports/         can_port.py  profile_port.py  timer_port.py         [HECHO - arquitecto]
  application/   emulator_service.py  use_cases.py  bms_requests.py
                 sources.py  builtin_profiles.py                      [HECHO - arquitecto]
  infrastructure/
    adapters/    can_python_can.py  can_ixxat.py  can_virtual.py  csv_reader.py   [developer]
    concurrency/ precision_timer.py  worker_thread.py                             [developer]
  presentation/  main_window.py  theme.py
    widgets/     can_status_indicator.py  connection_panel.py
                 current_control.py  profile_panel.py  telemetry_panel.py         [developer]
tests/
  conftest.py  fakes.py
  unit/          test_ivt_protocol.py  test_accumulator.py  test_models.py
                 test_sources.py  test_bms_requests.py  test_csv_reader.py
                 test_python_can_adapter.py  test_worker_thread.py                [pytest]
  integration/   test_virtual_can_pipeline.py  test_emulator_service.py
                 test_gui_smoke.py (marker gui, importorskip PySide6)             [pytest]
```

Diferencias con la estructura pedida (justificadas por SRP): `accumulator.py` (BatteryStateCounter),
`bms_requests.py` (HandleBmsRequestsUseCase, re-exportado en `use_cases.py`), `sources.py`,
`builtin_profiles.py`, `ports/timer_port.py`, `can_python_can.py` (base común IXXAT/virtual),
`precision_timer.py` (implementación de TimerPort).

## 3. Contratos de infraestructura (developer)

### 3.1 `can_python_can.PythonCanAdapter(CanBusPort)`
- `__init__(self, interface: str, bus_factory: Callable[..., can.BusABC] = can.Bus)` — factory inyectable para tests con mock.
- `connect(channel, bitrate)`: ya conectado → `CanConnectionError`. Llama
  `bus_factory(interface=..., channel=..., bitrate=int(bitrate), receive_own_messages=False)`;
  cualquier excepción (`can.CanError`, `OSError`, `ImportError`, `ValueError`, `NotImplementedError`) → `CanConnectionError` encadenada.
- `send_frame(frame)`: no conectado → `CanConnectionError`. `can.Message(arbitration_id, data, is_extended_id=False)`,
  `bus.send(msg, timeout=0.01)`; `can.CanError` → `CanTransmitError`. Cuenta `tx_count` / `tx_errors`.
- `receive_frame(timeout_s)`: `bus.recv(timeout_s)`; ignora tramas extendidas, remotas y de error; `None` si nada. `rx_count`.
- `get_bus_status()`: no conectado → `DISCONNECTED`. Mapea `bus.state`: `ACTIVE→BUS_OK`, `PASSIVE→WARNING`, `ERROR→BUS_OFF`;
  si el backend no soporta `state` → `BUS_OK`. Nunca lanza.
- `disconnect()`: `bus.shutdown()`, traga excepciones, idempotente.

### 3.2 `can_ixxat.IxxatCanAdapter(PythonCanAdapter)` — `interface="ixxat"`; channel `"0"` → `int`.
### 3.3 `can_virtual.VirtualCanAdapter(PythonCanAdapter)` — `interface="virtual"`, más inyección de fallos:
- `inject_fault(state: BusState | None)`: `BUS_OFF` → `send_frame` lanza `CanTransmitError` y status `BUS_OFF`;
  `WARNING` → envía pero status `WARNING`; `None` → limpia.
- `fail_next_connect: bool` → el siguiente `connect` lanza `CanConnectionError`.

### 3.4 `csv_reader.CsvProfileAdapter(ProfileReaderPort)`
- pandas `read_csv(comment="#")`, cabeceras sin espacios/insensible a mayúsculas.
- Columnas: `time` [s] + (`current` [A] → ×1000, o `current_ma` [mA]). Faltan → `ProfileFormatError`.
- No numérico / NaN / < 2 filas / tiempo no estrictamente creciente / tiempo < 0 / fichero inexistente → `ProfileFormatError`.
- Devuelve `CurrentProfile(name=<stem del fichero>, points=...)` (validación con numpy).

### 3.5 `precision_timer.PrecisionTimer(TimerPort)`
- `now()` = `time.perf_counter()`. `sleep_until(d)`: `time.sleep(rest - 0.002)` si rest > 2 ms, luego spin hasta `d`.
- Windows: `timeBeginPeriod(1)` vía ctypes si existe (best effort, sin fallar).

### 3.6 `worker_thread.TransmissionWorker`
- `__init__(service: EmulatorService, timer: TimerPort)`; `start()`, `stop(timeout=1.0)`, `is_alive`.
- Bucle: `deadline = service.tick(); timer.sleep_until(min(deadline, now + 0.05))` hasta `stop()` (threading.Event).
- Excepción inesperada en `tick()` → se guarda en `last_exception`, se registra con `logging` y el hilo sigue (no muere el emulador).

## 4. Presentación (developer)

- `MainWindow(service, manual_uc, profile_uc, can_port, worker, config)`; refresco 10 Hz con `QTimer` leyendo `service.snapshot()`.
- `ConnectionPanel`: canal, bitrate (250k/500k/1M), periodos I/T/As, botón Conectar/Desconectar (llama `can_port.connect`/`disconnect`,
  `service.update_config`), errores en barra de estado — nunca excepción sin capturar.
- `CanStatusIndicator`: LED (gris DISCONNECTED, verde BUS_OK, ámbar WARNING, rojo BUS_OFF) + texto + Hz medidos + TX/errores.
- `CurrentControlPanel`: slider + spinbox en A (± rango nominal ×1.2), temperatura, checkboxes OCS / error medida / error sistema,
  botón reset As.
- `ProfilePanel`: cargar CSV, combo perfiles integrados (WOT / Regen / Idle), checkbox bucle, gráfica pyqtgraph + `InfiniteLine` de progreso.
- `TelemetryPanel`: I [A], T [°C], As, Ah, modo RUN/STOP, tramas enviadas.
- `theme.py`: QSS oscuro "automoción" (fondo #121417, acento #00B4D8, alertas ámbar/rojo).
- Botones Start manual / Start perfil / Stop.

## 5. Arranque

`python -m isascale` o `isascale-emulator`:
```
--interface {ixxat,virtual}  (default ixxat en Windows, virtual resto)
--channel 0  --bitrate {250000,500000,1000000}
--headless   --profile {wot,regen,idle,<ruta.csv>}  --current-a 10.0  --loop  --duration S
```
`bootstrap.build_app(args) -> AppContext` crea adaptadores + servicio + casos de uso + worker (testeable sin Qt).
Headless: conecta, arranca, imprime snapshot cada 1 s, Ctrl+C → stop + disconnect limpios.

## 6. Plan de tests (pytest)

| Fichero | Qué valida |
|---------|-----------|
| `unit/test_ivt_protocol.py` | 35000 mA → `[00, 0N, 00, 00, 88, B8]` para N=0..F; ejemplo datasheet `01 05 00 00 88 b8`; negativos (complemento a 2); límites int32 y fuera → ValueError; state en nibble alto; T 0,1 °C con redondeo; As; decode(encode(x)) == x; alive, device_id (100/300/500/1000/2500 A vs tabla datasheet), serial, mode, error; parse_command. |
| `unit/test_models.py` | CANFrame (id > 0x7FF, > 8 bytes), IVTConfig (periodos 0/101, > 1000 msg/s), MessageCounter 0..F → 0, CurrentProfile (interpolación, extremos, no creciente). |
| `unit/test_accumulator.py` | Corriente constante 1 A·3600 s = 3600 As = 1 Ah; rampa (trapecio exacto); signo regen; reset; tiempo hacia atrás → ValueError; saturación int32. |
| `unit/test_sources.py`, `unit/test_bms_requests.py` | ConstantSource, ProfileSource (bucle, hold, progreso); cada comando F-09 byte a byte. |
| `unit/test_csv_reader.py` | CSV válido A y mA, comentarios, cabeceras con espacios; todos los errores de 3.4 (tmp_path). |
| `unit/test_python_can_adapter.py` | Con `bus_factory` mock (pytest-mock): errores de conexión, TX, mapeo de estados, filtrado RX. |
| `unit/test_worker_thread.py` | Worker llama tick, para limpio, sobrevive excepción. |
| `integration/test_emulator_service.py` | Con FakeTimer + fake CanBusPort: periodos exactos por canal, contador por canal con wrap, OUT_OF_RANGE, flags inyectados, STOP/RUN, RESTART, cambio manual↔perfil, fallo de bus (cuenta errores, no lanza, recupera), start sin conexión → CanConnectionError, update_config en marcha → RuntimeError. |
| `integration/test_virtual_can_pipeline.py` | VirtualCanAdapter + bus python-can virtual "BMS" en el mismo canal (canal único por test): emulador envía → BMS recibe y decodifica; BMS pide 0x79 → recibe 0xB9; inject_fault BUS_OFF → errores contados y estado BUS_OFF; recuperación. |
| `integration/test_gui_smoke.py` | `QT_QPA_PLATFORM=offscreen`; construye MainWindow con bus virtual, conecta, start/stop manual. |

Fixtures (`conftest.py`): `FakeTimer` (avance manual; `sleep_until` avanza el reloj), `FakeCanPort` en `tests/fakes.py`
(registro de tramas enviadas, cola RX, inyección de fallos), `config`, `service`, `virtual_channel` único.

## 7. Orden / criterio de hecho

1. Domain + ports + application (hecho). 2. Infra + tests unit en paralelo. 3. Integración. 4. GUI + smoke.
Hecho = `pytest` verde, cobertura domain+application ≥ 95 %, `python -m isascale --interface virtual --headless --profile wot --duration 3` funciona.
