# Requisitos — Emulador CAN IVT-S-1K-U0

Fuente de verdad del protocolo: [`datasheets/IVT-S_Datasheet_V1.03.pdf`](datasheets/IVT-S_Datasheet_V1.03.pdf)
(cap. 8 CAN, cap. 9 Startup). Hoja comercial: [`datasheets/IVT-S.pdf`](datasheets/IVT-S.pdf).
Si este documento y el datasheet discrepan, manda el datasheet.

## 1. Alcance

Emular por CAN un sensor Isabellenhütte IVT-S **1000 A** variante **U0** (solo corriente; sin U1..U3,
sin W ni Wh) para banco de potencia / HIL / telemetría de moto eléctrica de competición, comportándose
lo más parecido posible al sensor real.

## 2. Requisitos funcionales

| ID | Requisito | Ref. datasheet |
|----|-----------|----------------|
| F-01 | Enviar `IVT_Msg_Result_I` ID `0x521`, DLC 6: DB0 = MuxID `0x00`, DB1 = `state<<4 \| counter`, DB2..5 = int32 Big Endian en mA. El valor es la **media del intervalo de medida** (integración trapezoidal entre muestras). | 4.1, 8.1, 8.2 |
| F-02 | Enviar `IVT_Msg_Result_T` ID `0x525`, MuxID `0x04`, int32, 0,1 °C. **Desactivado por defecto** (como en fábrica). | 8.1, 8.2 |
| F-03 | Enviar `IVT_Msg_Result_As` ID `0x527`, MuxID `0x06`, int32, 1 As (integración trapezoidal de I). **Desactivado por defecto.** | 8.1, 8.2 |
| F-04 | Contador cíclico 4 bits `IVT_MsgCount` **independiente por canal**, 0x0..0xF con desbordamiento a 0x0; vuelve a 0 en cada arranque/reinicio. | 8.2 |
| F-05 | `IVT_Result_state`: bit0 OCS (umbrales `0x35`/`0x36` con histéresis); bit1 I en rango extendido (\|I\| > nominal, vuelve por debajo del 95 %) o T fuera de −40..105 °C; bit2/bit3 si hay contadores de error de medida/sistema **y** el BMS activó el bit 5 de Config Result. Los bits inyectados desde la GUI se suman siempre. | 4.2, 8.2, 8.4 |
| F-06 | Periodo por canal 1..65535 ms (16 bits). Defaults datasheet: I 20 ms cíclico, T 100 ms y As 30 ms desactivados. La GUI rechaza > 1000 msg/s; por CAN se acepta (el sensor real también). | 8.1, 8.4 |
| F-07 | Bitrate 250 k / 500 k (default) / 1 M; `0x3A` lo cambia y el emulador se reconecta a la nueva velocidad tras el reinicio. | 8, 8.5 |
| F-08 | Arranque: silencio durante `startup_time_ms` (400 ms por defecto), luego alive `0x511` `[0xBF, cmd_id BE16, serial BE32, 0x00]`; el primer resultado llega un intervalo después. Las tramas recibidas durante el arranque se pierden. | 5.1, 9 |
| F-09 | Juego completo de comandos del capítulo 8 (ver README). Todo comando definido recibe respuesta aunque no se pueda aplicar en el modo actual (se responde con el valor sin cambiar). Comandos con número de serie (`0x1n`, `0x5n`, `0x30`) solo se atienden si el serie coincide (si no, silencio). Reinicios fuera de STOP, valores inválidos y comandos no definidos → `0xFF` con DB1 = MuxID. | 8.1, 8.3–8.7 |
| F-10 | Respuesta DEVICE_ID: DB1 = 0x02 (IVT-S), DB2 = I_nom // 16, DB3 = (I_nom % 16)<<4 \| nº canales tensión (0 en U0), DB4 = 0x03, DB5 = 0x01 (CAN1), DB6 = 0x01 (12/24 V). Para 1000 A: `B9 02 3E 80 03 01 01 00`. | 8.7 |
| F-11 | En modo STOP no se envían resultados ni se integra As, pero se siguen atendiendo comandos. Los cambios de configuración (CAN ID, Config Result, umbrales, STORE, OC test, `0x30`) solo se aplican en STOP. | 8.3–8.5 |
| F-12 | Modo manual: corriente fija ajustable en tiempo real. | — |
| F-13 | Modo perfil: CSV (`time` [s], `current` [A] **o** `current_ma` [mA]) interpolado linealmente; reproducción única (mantiene último valor) o en bucle; progreso 0..1. | — |
| F-14 | Perfiles integrados moto eléctrica: aceleración WOT, frenada regenerativa, consumo en reposo. | — |
| F-15 | Estado de bus visible: DISCONNECTED / BUS_OK / WARNING / BUS_OFF + tasa real medida de `0x521` en Hz. Modo del sensor IDLE / BOOT / RUN / STOP y canales activos según la configuración CAN. | — |
| F-16 | Fallo de bus (desconexión, bus-off, error TX) no detiene la aplicación: se cuenta, se muestra y se reintenta en el siguiente ciclo. | — |
| F-17 | Modo sin GUI (`--headless`) para HIL/CI. | — |
| F-18 | Memoria: ajustes "activos" (cambios por CAN) y "guardados" (`STORE`, o el formulario de la GUI al conectar). `0x3F` vuelve a los guardados, `0x3D` a los de fábrica. Lo guardado, los contadores de error y el log sobreviven a Stop/Start. Cada reinicio por comando suma el error de sistema 0x0F *Reset Watchdog*. | 8.5 |
| F-19 | Log data (`0x42`/`0x43`): As total/carga/descarga (solo con As activado), tiempos de funcionamiento (total, I y T dentro/fuera de especificación, OC +/−), I máx/mín (A), T máx/mín (0,1 °C). U y Wh = 0 (U0). `0x30` DB1=2 borra el log "desde reset". | 3.4, 8.6 |
| F-20 | **Configurador** (`isascale-configure`, lado BMS): `info` (serie, versión, DEVICE_ID, modo, Config Result de los 8 canales), `apply-ams` (STOP → Config Result de I/T/As con el bit 5 → STORE → RUN → relectura y comparación; periodos por defecto 20 / 1000 / 100 ms, configurables con `--current-ms`, `--temperature-ms`, `--charge-ms`; 1–65535 ms y ≤ 1000 msg/s en total, si no error sin conectar; aviso si I ≠ 20 ms porque el firmware del AMS lo espera), `reset-log` (`0x30` DB1 = 2 con el número de serie, pide `--yes`). Cada comando espera su respuesta (respeta los 2 ms entre comandos) y salta resultados y respuestas ajenas; `0xFF` para ese comando, sin respuesta o eco distinto = error. Siempre deja el sensor en RUN. | 8.1, 8.4, 8.5, 8.7 |

Convención de signo: **+ = descarga** (batería → motor), **− = carga** (regeneración). As crece al descargar.

## 3. Requisitos no funcionales

| ID | Requisito |
|----|-----------|
| NF-01 | Arquitectura hexagonal: `domain` sin dependencias externas; `application` solo depende de `domain` + `ports`. UI y casos de uso nunca importan `python-can`. |
| NF-02 | Adaptadores CAN: `IxxatCanAdapter` (`interface='ixxat'`, solo Windows con driver IXXAT) y `VirtualCanAdapter` (`interface='virtual'`, CI / sin hardware, con inyección de fallos). |
| NF-03 | Jitter objetivo del ciclo de I ≤ ±1 ms en PC de escritorio (hilo dedicado + espera híbrida sleep/spin). No verificable en CI. |
| NF-04 | Python ≥ 3.11. GUI PySide6 + pyqtgraph, tema oscuro. |
| NF-05 | Suite pytest + pytest-mock: unit (sin bus) + integración (bus virtual). Sin hardware en CI. |

## 4. Decisiones tomadas (revisar)

| # | Decisión | Motivo |
|---|----------|--------|
| D-1 | Petición de identificación = `0x79` (GET_DEVICE_ID); `0xB9` es la **respuesta**. | **Confirmado por el usuario 2026-10-08: seguir el datasheet.** |
| D-2 | ~~T y As activados por defecto~~ → **defaults del datasheet** (solo I). Se activan en la GUI o por CAN. | Usuario 2026-10-18: "que se parezca lo máximo posible al sensor real". |
| D-3 | ~~Solo F-09 reducido~~ → juego completo de comandos del capítulo 8. | Ídem. |
| D-4 | Variante IVT-S-1K-U0-I-CAN1-12/24 (1000 A, sin tensión, CAN1 con terminación). | **Confirmado por el usuario 2026-10-18** (albarán: material 164513, 2 unidades). |
| D-5 | GUI con PySide6 (LGPL) en lugar de PyQt6 (GPL/comercial). | Licencia más cómoda para uso en empresa. |
| D-6 | Perfiles integrados son estímulos representativos, no datos medidos. | Sustituir por CSV reales de la moto cuando existan. |
| D-7 | Supuestos donde el datasheet no dice nada: Set CAN ID se aplica al momento (en STOP); `0x3D` no cambia el bitrate; STORE responde a los 200 ms; OCS se libera por debajo del umbral de reset (o del de set si reset = 0); serie que no coincide = silencio; `SW_VERSION` y `ARTICLE_NUMBER` son valores de relleno. | Revisar con el sensor real. |
| D-8 | U1..U3, W, Wh: se guardan y se responden en Config/CAN ID pero nunca se envían (U0 no tiene entradas de tensión). | Variante U0. |
| D-9 | Perfil del AMS: I 20 ms, T 1000 ms, As 100 ms cíclicos, bit 5 activo, big endian, signo sin invertir. El configurador vive aquí (reutiliza protocolo, adaptadores y se prueba contra el propio emulador). No se pone a cero el As: el firmware usa diferencias. | Usuario 2026-11-18 (AMS: «quiero el Ah counter y el de temperatura»). |

## 5. Pendiente de validar con hardware

- Supuestos de D-7 (sobre todo si Set CAN ID se aplica al momento o tras STORE + reinicio).
- Si el bit 3 aparece tras cada reinicio con el bit 5 activado (nota "Error Reset Watchdog" del datasheet).
- Valores reales de DEVICE_ID, SW_VERSION y ARTICLE_NUMBER (¿el material 164513?) leídos del sensor.
- Tiempo real de arranque (350–400 ms) y de respuesta de STORE.
- Jitter real con IXXAT USB-to-CAN en Windows.
- Si `0x30` DB1 = 2 ("Logdata since reset") pone a cero también el resultado `0x527` (As) o solo el log; y si el As arranca de 0 o del último valor guardado (cada 15 min) tras un corte de alimentación.
- `isascale-configure apply-ams` contra el sensor real (tiempos de respuesta, eco de Config Result en STOP).
