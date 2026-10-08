# isascale-emulator

Emulador por CAN del sensor de corriente **Isabellenhütte IVT-S variante U0** (solo corriente)
para banco de potencia, HIL y telemetría de la moto eléctrica.

Envía `0x521` (I, mA), `0x525` (T, 0,1 °C) y `0x527` (As) con contador de 4 bits por canal,
el mensaje alive `0x511` al arrancar, y atiende los comandos de `0x411`
(`0x79` DEVICE_ID → `0xB9`, `0x7B`, `0x74`, `0x34`, `0x3F`). Tiene modo manual y modo perfil (CSV o
perfiles integrados WOT / regen / idle), estado de bus e inyección de fallos.
Requisitos completos en [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

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
