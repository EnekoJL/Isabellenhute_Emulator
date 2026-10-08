# Requisitos — Emulador CAN IVT-S-U0

Fuente de verdad del protocolo: [`datasheets/IVT-S_Datasheet_V1.03.pdf`](datasheets/IVT-S_Datasheet_V1.03.pdf)
(cap. 8 CAN, cap. 9 Startup). Hoja comercial: [`datasheets/IVT-S.pdf`](datasheets/IVT-S.pdf).
Si este documento y el datasheet discrepan, manda el datasheet.

## 1. Alcance

Emular por CAN un sensor Isabellenhütte IVT-S variante **U0** (solo corriente; sin U1..U3, sin W ni Wh)
para banco de potencia / HIL / telemetría de moto eléctrica de competición.

## 2. Requisitos funcionales

| ID | Requisito | Ref. datasheet |
|----|-----------|----------------|
| F-01 | Enviar `IVT_Msg_Result_I` ID `0x521`, DLC 6: DB0 = MuxID `0x00`, DB1 = `state<<4 \| counter`, DB2..5 = int32 Big Endian en mA. | 8.1, 8.2 |
| F-02 | Enviar `IVT_Msg_Result_T` ID `0x525`, MuxID `0x04`, int32, 0,1 °C. Activable/desactivable. | 8.2 |
| F-03 | Enviar `IVT_Msg_Result_As` ID `0x527`, MuxID `0x06`, int32, 1 As (integración trapezoidal de I). Activable/desactivable. | 8.2 |
| F-04 | Contador cíclico 4 bits `IVT_MsgCount` **independiente por canal**, 0x0..0xF con desbordamiento a 0x0. | 8.2 |
| F-05 | `IVT_Result_state` (nibble alto DB1): bit0 OCS, bit1 fuera de rango/precisión reducida, bit2 error de medida, bit3 error de sistema. Bit1 se activa solo si \|I\| > rango nominal; bits inyectables desde GUI. | 8.2 |
| F-06 | Periodo por canal configurable 1..100 ms. Defaults datasheet: I 20 ms, T 100 ms, As 30 ms. Rechazar configuración > 1000 msg/s totales. | 8.1 |
| F-07 | Bitrate 250 k / 500 k (default) / 1 M. | 8 |
| F-08 | Al arrancar enviar alive `0x511`: `[0xBF, 0x04, 0x11, serial BE32, 0x00]` (DB1..2 = CAN ID de comandos). | 9 |
| F-09 | Escuchar `0x411` y responder en `0x511` (8 bytes, no usados = 0x00): `0x79 GET_DEVICE_ID → 0xB9`, `0x7B GET_SERIAL_NUMBER → 0xBB`, `0x74 GET_MODE → 0xB4`, `0x34 SET_MODE → 0xB4` (+ RUN/STOP), `0x3F RESTART → 0xBF` (reinicia contadores), otro → `0xFF` con DB1 = MuxID recibido. | 8.5, 8.7 |
| F-10 | Respuesta DEVICE_ID: DB1 = 0x02 (IVT-S), DB2 = I_nom // 16, DB3 = (I_nom % 16)<<4 \| nº canales tensión (0 en U0), DB4 = 0x03, DB5 = 0x01 (CAN1), DB6 = 0x01 (12/24 V). | 8.7 |
| F-11 | En modo STOP no se envían resultados cíclicos, pero se siguen atendiendo comandos. | 8.5 |
| F-12 | Modo manual: corriente fija ajustable en tiempo real. | — |
| F-13 | Modo perfil: CSV (`time` [s], `current` [A] **o** `current_ma` [mA]) interpolado linealmente; reproducción única (mantiene último valor) o en bucle; progreso 0..1. | — |
| F-14 | Perfiles integrados moto eléctrica: aceleración WOT, frenada regenerativa, consumo en reposo. | — |
| F-15 | Estado de bus visible: DISCONNECTED / BUS_OK / WARNING / BUS_OFF + tasa real medida de `0x521` en Hz. | — |
| F-16 | Fallo de bus (desconexión, bus-off, error TX) no detiene la aplicación: se cuenta, se muestra y se reintenta en el siguiente ciclo. | — |
| F-17 | Modo sin GUI (`--headless`) para HIL/CI. | — |

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
| D-1 | Petición de identificación = `0x79` (GET_DEVICE_ID); `0xB9` es la **respuesta**. | El prompt original decía "solicita 0xB9"; el datasheet 8.7 define 0x79 → 0xB9. **Confirmado por el usuario 2026-10-08: seguir el datasheet.** |
| D-2 | T y As activados por defecto (en el sensor real vienen desactivados). | Lo pide la especificación del emulador. |
| D-3 | Solo se implementan los comandos de F-09; el resto responde 0xFF. | U0 sin tensión; Set CAN ID / Config Result / logdata fuera de alcance v0.1. |
| D-4 | Rango nominal por defecto 1000 A (IVT-S-1K-U0-I-CAN1). Configurable. | Variante habitual en tracción; confirmar con el sensor real del equipo. |
| D-5 | GUI con PySide6 (LGPL) en lugar de PyQt6 (GPL/comercial). | Licencia más cómoda para uso en empresa. |
| D-6 | Perfiles integrados son estímulos representativos, no datos medidos. | Sustituir por CSV reales de la moto cuando existan. |

## 5. Pendiente de validar con hardware

- Comportamiento real del sensor ante comandos no soportados en RUN (¿0xFF o silencio?).
- Valor real de DB4 en DEVICE_ID para la variante del equipo.
- Jitter real con IXXAT USB-to-CAN en Windows.
