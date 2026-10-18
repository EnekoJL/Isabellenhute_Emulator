# isascale-emulator

Emulador por CAN del sensor de corriente **Isabellenhütte IVT-S-1K-U0-I-CAN1-12/24** (1000 A,
solo corriente, CAN1; la variante exacta del equipo, material 164513) para banco de potencia, HIL y telemetría de la moto eléctrica.

Se comporta como el sensor real (datasheet 1.03):

* **Arranque:** 400 ms en silencio, después alive `0xBF` en `0x511` y el primer resultado un
  intervalo más tarde. *Stop* en la GUI = sensor sin alimentación (no responde).
* **Resultados:** por defecto solo `0x521` (I, mA) cada 20 ms; `0x525` (T, 0,1 °C) y `0x527` (As)
  desactivados como en fábrica (se activan en la GUI o por CAN). Contador de 4 bits por canal.
  El valor de I es la **media del intervalo**, saturada a ±12 200 A (rango de sobrecorriente);
  bit 1 de estado en rango extendido (> 1000 A, vuelve por debajo de 950 A); bit 0 OCS según los
  umbrales `0x35`/`0x36`; bits 2/3 según los contadores de error si el BMS activa el bit 5.
* **Comandos `0x411`:** juego completo del capítulo 8: Set/Get CAN ID (`0x1n`/`0x5n`),
  Config Result (`0x2n`/`0x6n`: modo off/triggered/cyclic, periodo 1–65535 ms, endianness, signo),
  `0x30` reset errores/log (respuesta a 1,2 s), `0x31` TRIGGER, `0x32` STORE, `0x33`/`0x73` OC test,
  `0x34`/`0x74` modo, `0x35`/`0x36`/`0x75`/`0x76` umbrales, `0x3A` reinicio a otro bitrate, `0x3D`
  reinicio a fábrica, `0x3F` RESTART, `0x40`–`0x43` errores y log data, `0x79`/`0x7A`/`0x7B`/`0x7C`
  identificación. Lo no definido → `0xFF`.
* **Memoria:** los cambios por CAN valen hasta el siguiente reinicio salvo `STORE`; lo guardado
  sobrevive a *Stop/Start*. Cada reinicio por comando suma un error de sistema *Reset Watchdog*.

Tiene modo manual y modo perfil (CSV o perfiles integrados WOT / regen / idle), estado de bus e
inyección de fallos. Requisitos completos en [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

## Instalación

Python ≥ 3.11.

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[gui,dev]"
```

En Windows con IXXAT USB-to-CAN hace falta el driver IXXAT VCI instalado.

## Uso

```bash
# GUI (por defecto: ixxat en Windows, virtual en el resto)
python -m isascale
python -m isascale --interface ixxat --channel 0 --bitrate 500000

# Sin GUI (HIL / CI): imprime un snapshot por segundo; Ctrl+C para parar
python -m isascale --interface virtual --headless --profile wot --duration 10
python -m isascale --headless --current-a 120
python -m isascale --headless --profile examples/profiles/endurance_lap_a.csv --loop
```

Opciones: `--interface {ixxat,virtual}`, `--channel`, `--bitrate {250000,500000,1000000}`,
`--headless`, `--profile {wot,regen,idle,<ruta.csv>}`, `--current-a`, `--loop`, `--duration`.
También se instala el comando `isascale-emulator`.

Con `--interface virtual`, cualquier otro bus python-can `interface="virtual"` del mismo proceso y
mismo canal ve las tramas (útil para scripts de prueba que hacen de BMS).

En la GUI, *Canales activos (config. CAN)* muestra la configuración que el BMS haya dejado por CAN
(p. ej. `I 20ms · T off · As off`); el formulario de conexión es lo "guardado" en el sensor.

## Tests

```bash
pytest                       # unit + integración (bus virtual), sin hardware
pytest -m "not gui"          # sin la prueba de humo de la GUI
QT_QPA_PLATFORM=offscreen pytest -m gui
```

## Formato CSV de perfiles

Cabecera obligatoria, líneas `#` como comentario, cabeceras insensibles a mayúsculas/espacios.

| Columna | Unidad | |
|---|---|---|
| `time` | s | ≥ 0, estrictamente creciente, mínimo 2 filas |
| `current` | A | **o bien** |
| `current_ma` | mA | |

Signo: **+ = descarga** (tracción), **− = carga** (regeneración). Interpolación lineal entre puntos;
al final se mantiene el último valor, o vuelve a empezar con `--loop`.
Ejemplos en [examples/profiles/](examples/profiles/).

```csv
time,current
0.0,5
1.0,180
4.0,-80
```

## Arquitectura

Hexagonal: `domain` (puro) ← `application` (casos de uso, `EmulatorService`) → `ports` (ABC) ←
`infrastructure` (python-can, pandas, hilos) y `presentation` (PySide6). La raíz de composición es
`src/isascale/bootstrap.py`.

La GUI sigue **MVP (Model-View-Presenter, Passive View)**: `presentation/presenter.py` tiene toda la
lógica y no importa Qt (se testea con una vista falsa en `tests/unit/test_presenter.py`); `MainWindow`
y los widgets solo pintan los view models (`view_models.py`) y reenvían eventos al presenter.

Diagrama, contratos y plan de tests en
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Datasheets

Fuente de verdad del protocolo: [docs/datasheets/IVT-S_Datasheet_V1.03.pdf](docs/datasheets/IVT-S_Datasheet_V1.03.pdf)
(cap. 8 CAN, cap. 9 arranque). Hoja comercial: [docs/datasheets/IVT-S.pdf](docs/datasheets/IVT-S.pdf).
