# Respuesta a la pregunta final del reto (§20): evidencia por día, ruta y franja

Generado con `scripts/respuesta_reto.py` con el código de producción: base temporal en el PostgreSQL local (migrada con `alembic upgrade head`), copia temporal de `datos/`, una corrida del ciclo diario y, para cada fecha, una ejecución de tipo «respuesta» en la cola (`POST /api/v1/respuesta/calcular`). Las cifras se leen después como `GET /api/v1/respuesta`, desde la foto guardada en `ai_frecuencias.respuesta_reto`. Cada día tiene su respuesta completa en `respuesta_<fecha>.json`.

> con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?

- Modelo: `hgb_fv2_20250831_s42` (variables `fv2-2026-11-09`, corte 2025-08-31, calibración de la banda P10–P90 `v2`).
- Pronóstico del plan: `modelo_activo`; versión de umbrales 9; datos hasta 2025-12-31.
- Ciclo diario previo: ejecución `709dd479-7c82-465d-9bea-ff14fae136c7`, estado ok, 28,6 s.
- Tiempo total de los cálculos de la respuesta en la cola: 5,8 s.

| Fecha | Tipo de día | Ejecución «respuesta» | Estado | Segundos | Generada |
|---|---|---|---|---|---|
| 2025-11-19 | Laboral | `b686506f-f5e9-44d4-8c73-436e5b11f800` | ok | 1,9 | 2026-11-13T22:26:53-05:00 |
| 2025-11-22 | Sábado | `0d6bf0f0-8e54-4abc-93c4-958333d37768` | ok | 1,6 | 2026-11-13T22:26:55-05:00 |
| 2025-11-23 | Domingo/festivo | `c43d62dc-1378-401f-bbcf-60bd39631d9a` | ok | 1,6 | 2026-11-13T22:26:56-05:00 |
| 2026-01-01 | Domingo/festivo | `c6696633-23f0-4d82-a936-aea036362b04` | ok | 0,7 | 2026-11-13T22:26:58-05:00 |

## Resumen por día y ruta

| Fecha | Tipo de día | Ruta | Salidas recomendadas / programadas | Headway pico / valle (min) | Pasajeros esperados (P10–P90) | Observados | Vehículos en ruta (pico) / flota | §10.3 | Vehículos-hora ahorrados | Costo operativo plan / hoy (millones COP) | Espera media plan / hoy (min) | Sobreocupación plan / hoy (pasajeros) | Recaudo esperado (millones COP) | Horas no viables |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-11-19 | Laboral | SILENCIO | 133 / 158,5 | 2,40 (5 h) / 8,57 | 11.469 (8.458–14.160) | 10.548 | 44 (8 h) / 45 | 86 | 101,2 | 30,82 / 36,68 | 5,37 / 4,41 | 62,3 / 37,8 | 36,49 | ninguna |
| 2025-11-19 | Laboral | CRA 54 | 245 / 290,2 | 2,00 (5 h) / 4,31 | 22.800 (19.054–26.560) | 22.492 | 79 (8 h) / 79 | 106 | 160,4 | 52,44 / 61,75 | 3,06 / 2,48 | 248,1 / 246,9 | 72,55 | 5 |
| 2025-11-19 | Laboral | CL 72 | 109 / 96,5 | 4,29 (5 h) / 10,00 | 7.525 (5.320–9.628) | 7.115 | 30 (18 h) / 45 | 44 | -51,6 | 23,75 / 20,97 | 5,88 / 6,76 | 14,1 / 26,4 | 23,94 | ninguna |
| 2025-11-22 | Sábado | SILENCIO | 109 / 145,9 | 5,45 (6 h) / 10,00 | 9.105 (7.017–11.174) | 8.867 | 31 (9 h) / 43 | 44 | 145,9 | 24,98 / 33,45 | 6,45 / 4,83 | 14,6 / 7,7 | 28,97 | ninguna |
| 2025-11-22 | Sábado | CRA 54 | 208 / 260,7 | 2,40 (6 h) / 5,00 | 19.117 (15.708–22.006) | 18.963 | 67 (7 h) / 75 | 91 | 191,3 | 43,45 / 54,42 | 3,53 / 2,73 | 61,8 / 94,1 | 60,83 | ninguna |
| 2025-11-22 | Sábado | CL 72 | 101 / 91,4 | 7,50 (5 h) / 10,00 | 6.002 (4.269–7.731) | 5.726 | 27 (13 h) / 43 | 27 | -37,5 | 21,63 / 19,55 | 6,29 / 6,98 | 4,0 / 2,2 | 19,10 | ninguna |
| 2025-11-23 | Domingo/festivo | SILENCIO | 92 / 109,7 | 10,00 (17 h) / 10,00 | 5.434 (3.884–7.022) | 5.314 | 21 (18 h) / 27 | 21 | 59,8 | 19,57 / 23,36 | 6,89 / 5,84 | 0,4 / 1,7 | 17,29 | ninguna |
| 2025-11-23 | Domingo/festivo | CRA 54 | 114 / 185,2 | 6,67 (8 h) / 8,57 | 10.130 (7.822–11.984) | 9.547 | 23 (8 h) / 45 | 26 | 203,4 | 21,40 / 34,76 | 5,47 / 3,37 | 27,7 / 30,7 | 32,23 | ninguna |
| 2025-11-23 | Domingo/festivo | CL 72 | 93 / 65,6 | 6,98 (19 h) / 10,00 | 3.424 (2.004–4.675) | 3.528 | 23 (19 h) / 27 | 21 | -89,0 | 18,47 / 13,00 | 6,03 / 8,70 | 4,6 / 13,6 | 10,90 | ninguna |
| 2026-01-01 | Domingo/festivo | SILENCIO | 92 / 109,7 | 10,00 (15 h) / 10,00 | 4.609 (2.933–5.874) | — | 21 (18 h) / 27 | 21 | 59,8 | 19,57 / 23,36 | 6,85 / 5,79 | 13,5 / 12,4 | 14,66 | ninguna |
| 2026-01-01 | Domingo/festivo | CRA 54 | 100 / 185,2 | 7,50 (15 h) / 10,00 | 7.509 (5.681–10.191) | — | 20 (17 h) / 45 | 24 | 243,1 | 18,78 / 34,76 | 6,24 / 3,39 | 80,6 / 28,1 | 23,89 | ninguna |
| 2026-01-01 | Domingo/festivo | CL 72 | 93 / 65,6 | 6,98 (19 h) / 10,00 | 3.007 (1.771–4.340) | — | 23 (19 h) / 27 | 21 | -89,0 | 18,47 / 13,00 | 6,01 / 8,73 | 7,5 / 18,7 | 9,57 | ninguna |

Vehículos en ruta (pico): máximo de buses en ruta a la vez con el plan (conteo de D5 cada 15 min). §10.3: máximo de ceil(ciclo / headway), que supone que la frecuencia de la hora dura un ciclo completo. Vehículos-hora ahorrados: programado menos recomendado (negativo = el plan usa más). Recaudo: pasajeros esperados × tarifa neta 3.182 COP (tarifa pública 2026 × 0,86; Extreme no suministró la tarifa, §19). Observados: «—» cuando el día no tiene datos (el día siguiente al último dato).

## Contraste con los pasajeros observados

| Fecha | Ruta | Observados | Esperados | Error del día | WAPE horario | Horas dentro de P10–P90 |
|---|---|---|---|---|---|---|
| 2025-11-19 | SILENCIO | 10.548 | 11.469 | 8,7 % | 20,5 % | 11 de 17 |
| 2025-11-19 | CRA 54 | 22.492 | 22.800 | 1,4 % | 14,6 % | 10 de 17 |
| 2025-11-19 | CL 72 | 7.115 | 7.525 | 5,8 % | 22,7 % | 12 de 17 |
| 2025-11-22 | SILENCIO | 8.867 | 9.105 | 2,7 % | 8,6 % | 16 de 17 |
| 2025-11-22 | CRA 54 | 18.963 | 19.117 | 0,8 % | 8,3 % | 16 de 17 |
| 2025-11-22 | CL 72 | 5.726 | 6.002 | 4,8 % | 16,8 % | 13 de 17 |
| 2025-11-23 | SILENCIO | 5.314 | 5.434 | 2,3 % | 12,3 % | 16 de 17 |
| 2025-11-23 | CRA 54 | 9.547 | 10.130 | 6,1 % | 12,8 % | 14 de 17 |
| 2025-11-23 | CL 72 | 3.528 | 3.424 | -2,9 % | 17,7 % | 16 de 17 |
| 2026-01-01 | SILENCIO | sin datos todavía | — | — | — | — |
| 2026-01-01 | CRA 54 | sin datos todavía | — | — | — | — |
| 2026-01-01 | CL 72 | sin datos todavía | — | — | — | — |

## Cada cuánto despachar, por franja

Headway de la franja = minutos operados / salidas de la franja (recomendado y programado).

| Fecha | Tipo de día | Ruta | Franja | Salidas recomendadas | Salidas programadas | Headway recomendado (min) | Headway programado (min) | Horas no viables |
|---|---|---|---|---|---|---|---|---|
| 2025-11-19 | Laboral | SILENCIO | madrugada (4-5 h) | 29 | 29,9 | 3,10 | 3,00 | ninguna |
| 2025-11-19 | Laboral | SILENCIO | pico mañana (6-8 h) | 22 | 26,2 | 8,18 | 6,86 | ninguna |
| 2025-11-19 | Laboral | SILENCIO | valle (9-16 h) | 59 | 71,0 | 8,13 | 6,77 | ninguna |
| 2025-11-19 | Laboral | SILENCIO | pico tarde (17-19 h) | 18 | 24,7 | 9,97 | 7,26 | ninguna |
| 2025-11-19 | Laboral | SILENCIO | cierre (20 h) | 5 | 6,7 | 9,69 | 7,24 | ninguna |
| 2025-11-19 | Laboral | CRA 54 | madrugada (4-5 h) | 37 | 35,9 | 2,43 | 2,51 | 5 |
| 2025-11-19 | Laboral | CRA 54 | pico mañana (6-8 h) | 60 | 62,7 | 3,00 | 2,87 | ninguna |
| 2025-11-19 | Laboral | CRA 54 | valle (9-16 h) | 118 | 137,2 | 4,07 | 3,50 | ninguna |
| 2025-11-19 | Laboral | CRA 54 | pico tarde (17-19 h) | 24 | 45,5 | 7,46 | 3,93 | ninguna |
| 2025-11-19 | Laboral | CRA 54 | cierre (20 h) | 6 | 8,8 | 8,49 | 5,75 | ninguna |
| 2025-11-19 | Laboral | CL 72 | madrugada (4-5 h) | 17 | 18,2 | 5,28 | 4,93 | ninguna |
| 2025-11-19 | Laboral | CL 72 | pico mañana (6-8 h) | 18 | 17,8 | 10,00 | 10,13 | ninguna |
| 2025-11-19 | Laboral | CL 72 | valle (9-16 h) | 51 | 41,4 | 9,41 | 11,61 | ninguna |
| 2025-11-19 | Laboral | CL 72 | pico tarde (17-19 h) | 18 | 14,9 | 9,97 | 12,03 | ninguna |
| 2025-11-19 | Laboral | CL 72 | cierre (20 h) | 5 | 4,3 | 9,04 | 10,53 | ninguna |
| 2025-11-22 | Sábado | SILENCIO | madrugada (4-5 h) | 13 | 22,5 | 6,92 | 4,00 | ninguna |
| 2025-11-22 | Sábado | SILENCIO | pico mañana (6-8 h) | 24 | 29,8 | 7,50 | 6,05 | ninguna |
| 2025-11-22 | Sábado | SILENCIO | valle (9-16 h) | 49 | 67,0 | 9,80 | 7,16 | ninguna |
| 2025-11-22 | Sábado | SILENCIO | pico tarde (17-19 h) | 18 | 22,4 | 10,00 | 8,04 | ninguna |
| 2025-11-22 | Sábado | SILENCIO | cierre (20 h) | 5 | 4,1 | 8,92 | 10,79 | ninguna |
| 2025-11-22 | Sábado | CRA 54 | madrugada (4-5 h) | 28 | 27,6 | 3,22 | 3,26 | ninguna |
| 2025-11-22 | Sábado | CRA 54 | pico mañana (6-8 h) | 58 | 64,8 | 3,11 | 2,78 | ninguna |
| 2025-11-22 | Sábado | CRA 54 | valle (9-16 h) | 96 | 127,7 | 5,00 | 3,76 | ninguna |
| 2025-11-22 | Sábado | CRA 54 | pico tarde (17-19 h) | 21 | 35,6 | 8,57 | 5,06 | ninguna |
| 2025-11-22 | Sábado | CRA 54 | cierre (20 h) | 5 | 5,0 | 9,60 | 9,63 | ninguna |
| 2025-11-22 | Sábado | CL 72 | madrugada (4-5 h) | 12 | 14,7 | 7,54 | 6,16 | ninguna |
| 2025-11-22 | Sábado | CL 72 | pico mañana (6-8 h) | 18 | 19,8 | 10,00 | 9,09 | ninguna |
| 2025-11-22 | Sábado | CL 72 | valle (9-16 h) | 48 | 40,6 | 10,00 | 11,81 | ninguna |
| 2025-11-22 | Sábado | CL 72 | pico tarde (17-19 h) | 18 | 13,5 | 10,00 | 13,31 | ninguna |
| 2025-11-22 | Sábado | CL 72 | cierre (20 h) | 5 | 2,7 | 8,54 | 15,66 | ninguna |
| 2025-11-23 | Domingo/festivo | SILENCIO | madrugada (4-5 h) | 7 | 10,7 | 8,60 | 5,59 | ninguna |
| 2025-11-23 | Domingo/festivo | SILENCIO | pico mañana (6-8 h) | 18 | 23,7 | 10,00 | 7,60 | ninguna |
| 2025-11-23 | Domingo/festivo | SILENCIO | valle (9-16 h) | 48 | 56,1 | 10,00 | 8,55 | ninguna |
| 2025-11-23 | Domingo/festivo | SILENCIO | pico tarde (17-19 h) | 18 | 18,6 | 9,91 | 9,60 | ninguna |
| 2025-11-23 | Domingo/festivo | SILENCIO | cierre (20 h) | 1 | 0,6 | 7,29 | 12,74 | ninguna |
| 2025-11-23 | Domingo/festivo | CRA 54 | madrugada (4-5 h) | 11 | 15,6 | 5,86 | 4,14 | ninguna |
| 2025-11-23 | Domingo/festivo | CRA 54 | pico mañana (6-8 h) | 25 | 40,4 | 7,20 | 4,46 | ninguna |
| 2025-11-23 | Domingo/festivo | CRA 54 | valle (9-16 h) | 55 | 102,8 | 8,73 | 4,67 | ninguna |
| 2025-11-23 | Domingo/festivo | CRA 54 | pico tarde (17-19 h) | 21 | 25,5 | 8,53 | 7,03 | ninguna |
| 2025-11-23 | Domingo/festivo | CRA 54 | cierre (20 h) | 2 | 0,8 | 4,88 | 11,47 | ninguna |
| 2025-11-23 | Domingo/festivo | CL 72 | madrugada (4-5 h) | 6 | 6,5 | 10,00 | 9,17 | ninguna |
| 2025-11-23 | Domingo/festivo | CL 72 | pico mañana (6-8 h) | 18 | 14,2 | 10,00 | 12,67 | ninguna |
| 2025-11-23 | Domingo/festivo | CL 72 | valle (9-16 h) | 48 | 34,0 | 10,00 | 14,12 | ninguna |
| 2025-11-23 | Domingo/festivo | CL 72 | pico tarde (17-19 h) | 20 | 10,6 | 8,79 | 16,53 | ninguna |
| 2025-11-23 | Domingo/festivo | CL 72 | cierre (20 h) | 1 | 0,2 | 4,29 | 23,12 | ninguna |
| 2026-01-01 | Domingo/festivo | SILENCIO | madrugada (4-5 h) | 7 | 10,7 | 8,60 | 5,59 | ninguna |
| 2026-01-01 | Domingo/festivo | SILENCIO | pico mañana (6-8 h) | 18 | 23,7 | 10,00 | 7,60 | ninguna |
| 2026-01-01 | Domingo/festivo | SILENCIO | valle (9-16 h) | 48 | 56,1 | 10,00 | 8,55 | ninguna |
| 2026-01-01 | Domingo/festivo | SILENCIO | pico tarde (17-19 h) | 18 | 18,6 | 9,91 | 9,60 | ninguna |
| 2026-01-01 | Domingo/festivo | SILENCIO | cierre (20 h) | 1 | 0,6 | 7,29 | 12,74 | ninguna |
| 2026-01-01 | Domingo/festivo | CRA 54 | madrugada (4-5 h) | 9 | 15,6 | 7,17 | 4,14 | ninguna |
| 2026-01-01 | Domingo/festivo | CRA 54 | pico mañana (6-8 h) | 20 | 40,4 | 9,00 | 4,46 | ninguna |
| 2026-01-01 | Domingo/festivo | CRA 54 | valle (9-16 h) | 50 | 102,8 | 9,60 | 4,67 | ninguna |
| 2026-01-01 | Domingo/festivo | CRA 54 | pico tarde (17-19 h) | 19 | 25,5 | 9,43 | 7,03 | ninguna |
| 2026-01-01 | Domingo/festivo | CRA 54 | cierre (20 h) | 2 | 0,8 | 4,88 | 11,47 | ninguna |
| 2026-01-01 | Domingo/festivo | CL 72 | madrugada (4-5 h) | 6 | 6,5 | 10,00 | 9,17 | ninguna |
| 2026-01-01 | Domingo/festivo | CL 72 | pico mañana (6-8 h) | 18 | 14,2 | 10,00 | 12,67 | ninguna |
| 2026-01-01 | Domingo/festivo | CL 72 | valle (9-16 h) | 48 | 34,0 | 10,00 | 14,12 | ninguna |
| 2026-01-01 | Domingo/festivo | CL 72 | pico tarde (17-19 h) | 20 | 10,6 | 8,79 | 16,53 | ninguna |
| 2026-01-01 | Domingo/festivo | CL 72 | cierre (20 h) | 1 | 0,2 | 4,29 | 23,12 | ninguna |

## Atención inmediata en el momento de la consulta

| Fecha consultada | Ruta | Abiertas ahora (por severidad) | Detectadas en la fecha consultada |
|---|---|---|---|
| 2025-11-19 | SILENCIO | 12 (critica 6, preventiva 6) | 0 |
| 2025-11-19 | CRA 54 | 14 (critica 4, preventiva 10) | 0 |
| 2025-11-19 | CL 72 | 13 (critica 6, preventiva 7) | 0 |
| 2025-11-22 | SILENCIO | 12 (critica 6, preventiva 6) | 0 |
| 2025-11-22 | CRA 54 | 14 (critica 4, preventiva 10) | 0 |
| 2025-11-22 | CL 72 | 13 (critica 6, preventiva 7) | 0 |
| 2025-11-23 | SILENCIO | 12 (critica 6, preventiva 6) | 0 |
| 2025-11-23 | CRA 54 | 14 (critica 4, preventiva 10) | 0 |
| 2025-11-23 | CL 72 | 13 (critica 6, preventiva 7) | 0 |
| 2026-01-01 | SILENCIO | 12 (critica 6, preventiva 6) | 0 |
| 2026-01-01 | CRA 54 | 14 (critica 4, preventiva 10) | 0 |
| 2026-01-01 | CL 72 | 13 (critica 6, preventiva 7) | 1 |

«Abiertas ahora»: alertas sin cerrar ni descartar en `ai_frecuencias.alert` en el instante de la consulta, de cualquier fecha (las dejó el ciclo diario previo). «Detectadas en la fecha consultada»: las de ese día de Bogotá, en cualquier estado.

### SILENCIO (2025-11-19, laboral): detalle por hora

| Hora | Franja | Headway recomendado | Buses/h | Headway programado | Buses/h programados | Pasajeros esperados (P10–P90) | Viable | Motivo |
|---|---|---|---|---|---|---|---|---|
| 4 | madrugada (4-5 h) | 7,44 | 4 | 7,32 | 4,06 | 379 (239–472) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 4,0 buses en ruta de 45 disponibles. |
| 5 | madrugada (4-5 h) | 2,40 | 25 | 2,32 | 25,83 | 1.881 (1.517–2.332) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 29,0 buses en ruta de 45 disponibles. |
| 6 | pico mañana (6-8 h) | 6,67 | 9 | 6,08 | 9,86 | 849 (649–953) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 38,0 buses en ruta de 45 disponibles. |
| 7 | pico mañana (6-8 h) | 8,57 | 7 | 7,38 | 8,13 | 672 (527–783) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 43,0 buses en ruta de 45 disponibles. |
| 8 | pico mañana (6-8 h) | 10,00 | 6 | 7,29 | 8,23 | 678 (507–782) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 43,5 buses en ruta de 45 disponibles. |
| 9 | valle (9-16 h) | 10,00 | 6 | 6,48 | 9,25 | 641 (495–773) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 28,0 buses en ruta de 45 disponibles. |
| 10 | valle (9-16 h) | 10,00 | 6 | 6,67 | 9,00 | 667 (506–809) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 30,5 buses en ruta de 45 disponibles. |
| 11 | valle (9-16 h) | 10,00 | 6 | 8,03 | 7,47 | 608 (430–747) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 28,3 buses en ruta de 45 disponibles. |
| 12 | valle (9-16 h) | 8,57 | 7 | 7,41 | 8,10 | 738 (508–895) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 26,0 buses en ruta de 45 disponibles. |
| 13 | valle (9-16 h) | 7,50 | 8 | 6,20 | 9,67 | 757 (580–995) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 28,1 buses en ruta de 45 disponibles. |
| 14 | valle (9-16 h) | 5,45 | 11 | 5,81 | 10,33 | 925 (646–1.189) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 32,8 buses en ruta de 45 disponibles. |
| 15 | valle (9-16 h) | 7,50 | 8 | 6,48 | 9,27 | 688 (491–854) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 35,2 buses en ruta de 45 disponibles. |
| 16 | valle (9-16 h) | 8,57 | 7 | 7,63 | 7,86 | 694 (480–900) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 36,2 buses en ruta de 45 disponibles. |
| 17 | pico tarde (17-19 h) | 10,00 | 6 | 7,15 | 8,39 | 467 (329–596) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 37,0 buses en ruta de 45 disponibles. |
| 18 | pico tarde (17-19 h) | 9,99 | 6 | 7,24 | 8,28 | 393 (278–526) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 36,5 buses en ruta de 45 disponibles. |
| 19 | pico tarde (17-19 h) | 9,93 | 6 | 7,38 | 8,07 | 253 (167–339) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 34,7 buses en ruta de 45 disponibles. |
| 20 | cierre (20 h) | 9,69 | 5 | 7,24 | 6,69 | 180 (110–216) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 29,7 buses en ruta de 45 disponibles. |

### CRA 54 (2025-11-19, laboral): detalle por hora

| Hora | Franja | Headway recomendado | Buses/h | Headway programado | Buses/h programados | Pasajeros esperados (P10–P90) | Viable | Motivo |
|---|---|---|---|---|---|---|---|---|
| 4 | madrugada (4-5 h) | 4,28 | 7 | 4,65 | 6,44 | 559 (440–673) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 7,0 buses en ruta de 79 disponibles. |
| 5 | madrugada (4-5 h) | 2,00 | 30 | 2,04 | 29,48 | 2.580 (2.334–3.011) | no | No viable: la demanda prevista pide 32 salidas (una cada 1,88 min) y el headway mínimo gobernado de 2,00 min permite como máximo 30; el plan programa 30 salidas, la mejor aproximación ejecutable. |
| 6 | pico mañana (6-8 h) | 2,31 | 26 | 2,26 | 26,59 | 2.280 (2.045–2.539) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 63,0 buses en ruta de 79 disponibles. |
| 7 | pico mañana (6-8 h) | 3,00 | 20 | 2,94 | 20,43 | 1.654 (1.399–1.832) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 76,0 buses en ruta de 79 disponibles. |
| 8 | pico mañana (6-8 h) | 4,29 | 14 | 3,82 | 15,69 | 1.482 (1.243–1.640) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 78,6 buses en ruta de 79 disponibles. |
| 9 | valle (9-16 h) | 5,00 | 12 | 3,76 | 15,97 | 1.342 (1.133–1.491) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 72,0 buses en ruta de 79 disponibles. |
| 10 | valle (9-16 h) | 5,45 | 11 | 3,96 | 15,15 | 1.221 (974–1.399) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 69,9 buses en ruta de 79 disponibles. |
| 11 | valle (9-16 h) | 6,00 | 10 | 3,68 | 16,30 | 1.199 (997–1.409) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 57,5 buses en ruta de 79 disponibles. |
| 12 | valle (9-16 h) | 4,00 | 15 | 3,42 | 17,53 | 1.618 (1.355–1.880) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 48,1 buses en ruta de 79 disponibles. |
| 13 | valle (9-16 h) | 3,16 | 19 | 3,08 | 19,45 | 1.756 (1.519–2.074) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 53,7 buses en ruta de 79 disponibles. |
| 14 | valle (9-16 h) | 2,86 | 21 | 3,25 | 18,43 | 1.714 (1.385–2.078) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 64,4 buses en ruta de 79 disponibles. |
| 15 | valle (9-16 h) | 3,53 | 17 | 3,52 | 17,05 | 1.473 (1.173–1.772) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 72,0 buses en ruta de 79 disponibles. |
| 16 | valle (9-16 h) | 4,62 | 13 | 3,46 | 17,34 | 1.318 (1.107–1.587) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 71,5 buses en ruta de 79 disponibles. |
| 17 | pico tarde (17-19 h) | 6,64 | 9 | 3,53 | 16,91 | 947 (704–1.114) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 71,6 buses en ruta de 79 disponibles. |
| 18 | pico tarde (17-19 h) | 7,47 | 8 | 4,01 | 14,89 | 709 (552–875) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 62,2 buses en ruta de 79 disponibles. |
| 19 | pico tarde (17-19 h) | 8,52 | 7 | 4,34 | 13,72 | 618 (479–751) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 52,2 buses en ruta de 79 disponibles. |
| 20 | cierre (20 h) | 8,49 | 6 | 5,75 | 8,85 | 332 (214–434) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 35,1 buses en ruta de 79 disponibles. |

### CL 72 (2025-11-19, laboral): detalle por hora

| Hora | Franja | Headway recomendado | Buses/h | Headway programado | Buses/h programados | Pasajeros esperados (P10–P90) | Viable | Motivo |
|---|---|---|---|---|---|---|---|---|
| 4 | madrugada (4-5 h) | 9,92 | 3 | 9,18 | 3,24 | 230 (138–312) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 3,0 buses en ruta de 45 disponibles. |
| 5 | madrugada (4-5 h) | 4,29 | 14 | 4,01 | 14,98 | 984 (718–1.213) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,0 buses en ruta de 45 disponibles. |
| 6 | pico mañana (6-8 h) | 10,00 | 6 | 9,43 | 6,37 | 546 (423–657) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 23,0 buses en ruta de 45 disponibles. |
| 7 | pico mañana (6-8 h) | 10,00 | 6 | 10,37 | 5,78 | 527 (408–635) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 26,9 buses en ruta de 45 disponibles. |
| 8 | pico mañana (6-8 h) | 10,00 | 6 | 10,68 | 5,62 | 516 (405–633) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 25,8 buses en ruta de 45 disponibles. |
| 9 | valle (9-16 h) | 10,00 | 6 | 10,72 | 5,60 | 434 (352–568) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 24,0 buses en ruta de 45 disponibles. |
| 10 | valle (9-16 h) | 10,00 | 6 | 12,38 | 4,85 | 422 (290–528) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 26,2 buses en ruta de 45 disponibles. |
| 11 | valle (9-16 h) | 10,00 | 6 | 14,37 | 4,18 | 443 (308–566) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 26,2 buses en ruta de 45 disponibles. |
| 12 | valle (9-16 h) | 8,57 | 7 | 12,51 | 4,80 | 523 (385–689) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 25,8 buses en ruta de 45 disponibles. |
| 13 | valle (9-16 h) | 8,57 | 7 | 10,19 | 5,89 | 570 (414–728) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 27,0 buses en ruta de 45 disponibles. |
| 14 | valle (9-16 h) | 8,57 | 7 | 9,53 | 6,30 | 542 (346–724) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 27,6 buses en ruta de 45 disponibles. |
| 15 | valle (9-16 h) | 10,00 | 6 | 11,24 | 5,34 | 487 (338–652) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 28,1 buses en ruta de 45 disponibles. |
| 16 | valle (9-16 h) | 10,00 | 6 | 13,63 | 4,40 | 425 (266–550) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 28,5 buses en ruta de 45 disponibles. |
| 17 | pico tarde (17-19 h) | 10,00 | 6 | 11,90 | 5,04 | 286 (170–357) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 29,0 buses en ruta de 45 disponibles. |
| 18 | pico tarde (17-19 h) | 9,97 | 6 | 12,23 | 4,89 | 234 (150–334) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 29,5 buses en ruta de 45 disponibles. |
| 19 | pico tarde (17-19 h) | 9,94 | 6 | 11,98 | 4,98 | 206 (131–273) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 29,0 buses en ruta de 45 disponibles. |
| 20 | cierre (20 h) | 9,04 | 5 | 10,53 | 4,29 | 148 (79–207) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 27,8 buses en ruta de 45 disponibles. |

### SILENCIO (2026-01-01, domingo/festivo): detalle por hora

| Hora | Franja | Headway recomendado | Buses/h | Headway programado | Buses/h programados | Pasajeros esperados (P10–P90) | Viable | Motivo |
|---|---|---|---|---|---|---|---|---|
| 4 | madrugada (4-5 h) | 0,18 | 1 | — | — | 8 (0–93) | sí | Viable: una sola salida en 0,2 min operados (no hay intervalo entre salidas dentro de la hora) y como máximo 1,0 buses en ruta de 27 disponibles. |
| 5 | madrugada (4-5 h) | 10,00 | 6 | 5,59 | 10,73 | 389 (232–619) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 6,5 buses en ruta de 27 disponibles. |
| 6 | pico mañana (6-8 h) | 10,00 | 6 | 6,38 | 9,41 | 366 (214–366) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 12,0 buses en ruta de 27 disponibles. |
| 7 | pico mañana (6-8 h) | 10,00 | 6 | 7,60 | 7,89 | 296 (195–349) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,0 buses en ruta de 27 disponibles. |
| 8 | pico mañana (6-8 h) | 10,00 | 6 | 9,42 | 6,37 | 268 (201–326) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,6 buses en ruta de 27 disponibles. |
| 9 | valle (9-16 h) | 10,00 | 6 | 8,41 | 7,13 | 258 (199–317) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,1 buses en ruta de 27 disponibles. |
| 10 | valle (9-16 h) | 10,00 | 6 | 8,04 | 7,47 | 246 (197–275) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,4 buses en ruta de 27 disponibles. |
| 11 | valle (9-16 h) | 10,00 | 6 | 8,70 | 6,89 | 247 (196–302) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,5 buses en ruta de 27 disponibles. |
| 12 | valle (9-16 h) | 10,00 | 6 | 9,36 | 6,41 | 293 (179–328) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,9 buses en ruta de 27 disponibles. |
| 13 | valle (9-16 h) | 10,00 | 6 | 9,02 | 6,66 | 299 (203–348) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,5 buses en ruta de 27 disponibles. |
| 14 | valle (9-16 h) | 10,00 | 6 | 8,15 | 7,36 | 350 (226–379) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,6 buses en ruta de 27 disponibles. |
| 15 | valle (9-16 h) | 10,00 | 6 | 7,76 | 7,74 | 394 (216–508) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,6 buses en ruta de 27 disponibles. |
| 16 | valle (9-16 h) | 10,00 | 6 | 9,24 | 6,49 | 355 (218–477) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,4 buses en ruta de 27 disponibles. |
| 17 | pico tarde (17-19 h) | 10,00 | 6 | 9,05 | 6,63 | 279 (190–372) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,4 buses en ruta de 27 disponibles. |
| 18 | pico tarde (17-19 h) | 10,00 | 6 | 9,64 | 6,23 | 274 (171–341) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,9 buses en ruta de 27 disponibles. |
| 19 | pico tarde (17-19 h) | 9,73 | 6 | 10,21 | 5,71 | 244 (95–313) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,9 buses en ruta de 27 disponibles. |
| 20 | cierre (20 h) | 7,29 | 1 | 12,74 | 0,57 | 43 (1–162) | sí | Viable: una sola salida en 7,3 min operados (no hay intervalo entre salidas dentro de la hora) y como máximo 19,6 buses en ruta de 27 disponibles. |

### CRA 54 (2026-01-01, domingo/festivo): detalle por hora

| Hora | Franja | Headway recomendado | Buses/h | Headway programado | Buses/h programados | Pasajeros esperados (P10–P90) | Viable | Motivo |
|---|---|---|---|---|---|---|---|---|
| 4 | madrugada (4-5 h) | 4,49 | 1 | 5,00 | 0,90 | 6 (6–100) | sí | Viable: una sola salida en 4,5 min operados (no hay intervalo entre salidas dentro de la hora) y como máximo 1,0 buses en ruta de 45 disponibles. |
| 5 | madrugada (4-5 h) | 7,50 | 8 | 4,09 | 14,67 | 548 (515–764) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 9,0 buses en ruta de 45 disponibles. |
| 6 | pico mañana (6-8 h) | 8,57 | 7 | 4,56 | 13,17 | 532 (532–723) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 15,7 buses en ruta de 45 disponibles. |
| 7 | pico mañana (6-8 h) | 10,00 | 6 | 4,46 | 13,46 | 515 (506–515) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,9 buses en ruta de 45 disponibles. |
| 8 | pico mañana (6-8 h) | 8,57 | 7 | 4,36 | 13,77 | 502 (356–758) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,2 buses en ruta de 45 disponibles. |
| 9 | valle (9-16 h) | 10,00 | 6 | 4,35 | 13,79 | 480 (375–615) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,9 buses en ruta de 45 disponibles. |
| 10 | valle (9-16 h) | 10,00 | 6 | 4,45 | 13,49 | 464 (332–464) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,9 buses en ruta de 45 disponibles. |
| 11 | valle (9-16 h) | 10,00 | 6 | 4,77 | 12,58 | 458 (341–564) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,6 buses en ruta de 45 disponibles. |
| 12 | valle (9-16 h) | 10,00 | 6 | 4,86 | 12,34 | 500 (388–709) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,3 buses en ruta de 45 disponibles. |
| 13 | valle (9-16 h) | 10,00 | 6 | 4,43 | 13,54 | 499 (413–764) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,3 buses en ruta de 45 disponibles. |
| 14 | valle (9-16 h) | 10,00 | 6 | 4,59 | 13,06 | 518 (500–673) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,4 buses en ruta de 45 disponibles. |
| 15 | valle (9-16 h) | 7,50 | 8 | 4,91 | 12,23 | 567 (435–1.003) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,2 buses en ruta de 45 disponibles. |
| 16 | valle (9-16 h) | 10,00 | 6 | 5,08 | 11,81 | 540 (400–797) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,4 buses en ruta de 45 disponibles. |
| 17 | pico tarde (17-19 h) | 10,00 | 6 | 5,92 | 10,14 | 508 (250–528) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,6 buses en ruta de 45 disponibles. |
| 18 | pico tarde (17-19 h) | 10,00 | 6 | 6,91 | 8,68 | 463 (209–471) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,1 buses en ruta de 45 disponibles. |
| 19 | pico tarde (17-19 h) | 8,45 | 7 | 8,86 | 6,67 | 327 (122–498) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,6 buses en ruta de 45 disponibles. |
| 20 | cierre (20 h) | 4,88 | 2 | 11,47 | 0,85 | 82 (1–247) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 17,6 buses en ruta de 45 disponibles. |

### CL 72 (2026-01-01, domingo/festivo): detalle por hora

| Hora | Franja | Headway recomendado | Buses/h | Headway programado | Buses/h programados | Pasajeros esperados (P10–P90) | Viable | Motivo |
|---|---|---|---|---|---|---|---|---|
| 4 | madrugada (4-5 h) | — | 0 | — | — | 2 (0–51) | sí | Hora sin salidas en el plan (sin minutos operados o sin demanda que las justifique). |
| 5 | madrugada (4-5 h) | 10,00 | 6 | 9,17 | 6,54 | 215 (99–253) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 6,0 buses en ruta de 27 disponibles. |
| 6 | pico mañana (6-8 h) | 10,00 | 6 | 11,20 | 5,36 | 172 (136–303) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 12,0 buses en ruta de 27 disponibles. |
| 7 | pico mañana (6-8 h) | 10,00 | 6 | 12,13 | 4,95 | 169 (125–252) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,0 buses en ruta de 27 disponibles. |
| 8 | pico mañana (6-8 h) | 10,00 | 6 | 15,36 | 3,91 | 185 (121–217) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,0 buses en ruta de 27 disponibles. |
| 9 | valle (9-16 h) | 10,00 | 6 | 13,85 | 4,33 | 188 (109–223) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,3 buses en ruta de 27 disponibles. |
| 10 | valle (9-16 h) | 10,00 | 6 | 13,36 | 4,49 | 179 (104–237) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,5 buses en ruta de 27 disponibles. |
| 11 | valle (9-16 h) | 10,00 | 6 | 13,51 | 4,44 | 184 (106–251) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 18,7 buses en ruta de 27 disponibles. |
| 12 | valle (9-16 h) | 10,00 | 6 | 15,90 | 3,77 | 177 (107–249) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,3 buses en ruta de 27 disponibles. |
| 13 | valle (9-16 h) | 10,00 | 6 | 15,11 | 3,97 | 192 (132–321) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,6 buses en ruta de 27 disponibles. |
| 14 | valle (9-16 h) | 10,00 | 6 | 13,33 | 4,50 | 213 (158–338) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,8 buses en ruta de 27 disponibles. |
| 15 | valle (9-16 h) | 10,00 | 6 | 13,19 | 4,55 | 241 (154–330) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,8 buses en ruta de 27 disponibles. |
| 16 | valle (9-16 h) | 10,00 | 6 | 15,23 | 3,94 | 244 (130–326) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,6 buses en ruta de 27 disponibles. |
| 17 | pico tarde (17-19 h) | 10,00 | 6 | 16,12 | 3,72 | 252 (143–323) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 19,7 buses en ruta de 27 disponibles. |
| 18 | pico tarde (17-19 h) | 10,00 | 6 | 16,03 | 3,74 | 176 (71–265) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 20,0 buses en ruta de 27 disponibles. |
| 19 | pico tarde (17-19 h) | 6,98 | 8 | 17,59 | 3,18 | 196 (77–286) | sí | Viable: intervalo dentro de 2,0-10,0 min y como máximo 22,2 buses en ruta de 27 disponibles. |
| 20 | cierre (20 h) | 4,29 | 1 | 23,12 | 0,19 | 22 (0–116) | sí | Viable: una sola salida en 4,3 min operados (no hay intervalo entre salidas dentro de la hora) y como máximo 20,9 buses en ruta de 27 disponibles. |

## Limitaciones declaradas por la respuesta

- El plan de despacho y los pasajeros esperados salen del mismo pronóstico horario del modelo activo hgb_fv2_20250831_s42 (P10, P50 y P90 calibrados de cada hora): se puede calcular para cualquier día con variables, incluido el día siguiente al último dato.
- El headway mínimo gobernado en threshold_config (headway_minimo_min; 2 min por omisión) es una restricción explícita del plan (§10.2): ninguna hora programa más de floor(minutos / headway mínimo) salidas. Donde la demanda pediría más, la hora sale «no viable» con su motivo y el plan muestra la mejor aproximación ejecutable, sin forzar una cifra (§10.3 y §18).
- «Espera máxima» de §5.1 se interpreta como la espera media del pasajero (headway / 2 con llegadas aleatorias): el headway máximo efectivo es min(headway_maximo_min, 2 × espera_max_min) (supuesto S12, pregunta a Extreme en docs/hallazgos_extreme.md).
- La banda P10-P90 del día suma las bandas de cada hora: es más ancha que la banda del total del día.
- La tarifa no la suministró Extreme (§19): el recaudo usa la tarifa neta vigente de threshold_config (tarifa_cop; por omisión la tarifa pública 2026 del Área Metropolitana × 0,86, datos/costos_fuente.json) y es una cifra de referencia.
- Ciclo, flota disponible e intervalo programado son medianas de 2025 por ruta, tipo de día y hora (D1) y no siempre cuadran entre sí: con la programación de hoy, los buses en ruta pueden superar la flota (vehiculos.requeridos_programados). Extreme debe confirmar el ciclo y la flota por franja (§19); el valor oficial se registra sin regenerar datos con PUT /api/v1/catalogos/flota (ajuste local versionado).
- El valor del tiempo de espera (7.000 COP/h) y la penalidad por pasajero sobre la capacidad (10.000 COP) son supuestos de D5 que debe validar el área operativa (§5.1). Elasticidad: β estimada ≈ 0,70 por observación, sin validar en campo; el plan usa 0,5 por prudencia; la sensibilidad está en docs/evidencias/optimizacion/sensibilidad.md; el piloto la mide.
- Atención inmediata: la lista «abiertas ahora» son las alertas sin cerrar ni descartar en el momento de la consulta, de cualquier fecha; las de la fecha consultada van aparte en alertas_de_la_fecha.
- El 2026-01-01 es festivo: el plan y la frecuencia programada de comparación usan los parámetros de domingo o festivo (parametros_operativos_hora no tiene una programación propia para los festivos entre semana).
