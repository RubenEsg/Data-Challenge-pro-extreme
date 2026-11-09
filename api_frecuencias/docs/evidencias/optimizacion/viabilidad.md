# Viabilidad de la recomendación por ruta, hora y tipo de día (2025)

Generado por `scripts/viabilidad.py` el 2026-11-09T07:36:25-05:00 (244.2 s) con el modelo activo `hgb_fv2_20250831_s42` (P10/P50/P90 por hora, h = 60, sin factor intradía) y los umbrales de producción: headway 2 a 10 min (el máximo es min(headway_maximo_min, 2 × espera_max_min) con espera de 5 min), ocupación objetivo 65 % a 85 %, nivel de servicio 0,90 (P90 calibrado). Ciclo, flota e intervalo programado: mediana 2025 por ruta, tipo de día y hora (`datos/parametros_operativos_hora.parquet`); tipologías de `tipologias_flota.json`.

Una franja es **no viable** cuando ninguna mezcla de buses cumple a la vez el headway mínimo y máximo, la flota (repartida por tipología) con el ciclo de la hora y la capacidad para la carga crítica del P90 (§10.2). Entonces se informa la mejor aproximación ejecutable y su cobertura (§10.3, §18). Para cada franja no viable se cambia UNA condición a la vez; la causa es la que, sola, la vuelve viable:

- **reparto por tipología**: la flota total como única cota, sin el reparto fijo entre tipologías de `tipologias_ruta`;
- **banda P90**: dimensionar con la demanda puntual en lugar del P90 calibrado;
- **ciclo mediano**: el ciclo del percentil 25 de 2025 en lugar de la mediana;
- **headway mínimo**: headway mínimo de 1 min en lugar de 2.
- **combinada**: ninguna condición sola alcanza.

Una franja puede resolverse con más de una causa: por eso las causas pueden sumar más que las franjas.

## A. La franja del ciclo diario (hora de las 6, 15-sep a 31-dic de 2025)

El ciclo diario recomienda a las 06:00 la hora de las 6 en los tres horizontes. Sobre 324 franjas (3 rutas × 108 días) es viable el **46,0 % (149 de 324)**. El backtest de alertas (`docs/evidencias/alertas/backtest_alertas_pronostico.md`) informa 46,0 % con su propio pronóstico de ventana; esta tabla explica de dónde sale.

| Ruta | Tipo de día | Franjas | Viables | Causa de las no viables (franjas que la causa sola resuelve) |
|---|---|---|---|---|
| CL 72 | Domingo/festivo | 20 | 100,0 % | — |
| CL 72 | Laboral | 73 | 100,0 % | — |
| CL 72 | Sábado | 15 | 100,0 % | — |
| CRA 54 | Domingo/festivo | 20 | 100,0 % | — |
| CRA 54 | Laboral | 73 | 0,0 % | combinada 73 |
| CRA 54 | Sábado | 15 | 0,0 % | combinada 13, reparto por tipología 2 |
| SILENCIO | Domingo/festivo | 20 | 100,0 % | — |
| SILENCIO | Laboral | 73 | 0,0 % | reparto por tipología 73 |
| SILENCIO | Sábado | 15 | 6,7 % | reparto por tipología 14, banda P90 14 |

Por ruta: CL 72 100,0 %; CRA 54 18,5 %; SILENCIO 19,4 %.

**Lectura.** Las 175 franjas no viables están en CRA 54 laboral (73), CRA 54 sábado (15), SILENCIO laboral (73), SILENCIO sábado (14); CL 72 domingo/festivo, CL 72 laboral, CL 72 sábado, CRA 54 domingo/festivo, SILENCIO domingo/festivo son viables en todos los días. En CRA 54 laboral ninguna condición sola alcanza en 73 de 73: la hora pide más capacidad de la que sostienen juntas la flota, el ciclo y el headway mínimo (ver la hora pico de CRA 54). En CRA 54 sábado ninguna condición sola alcanza en 13 de 15: la hora pide más capacidad de la que sostienen juntas la flota, el ciclo y el headway mínimo (ver la hora pico de CRA 54). En SILENCIO laboral manda el reparto fijo de la flota entre tipologías: con la flota total como única cota se vuelven viables 73 de 73. En SILENCIO sábado manda el reparto fijo de la flota entre tipologías: con la flota total como única cota se vuelven viables 14 de 14.

En las 175 franjas no viables la mejor aproximación ejecutable cubre en mediana el 65,9 % de la carga del nivel de servicio (mínimo 50,4 %).

## B. Todas las horas de servicio, semanas representativas

Semanas del 2025-03-12, 2025-06-11, 2025-09-10, 2025-11-19 (miércoles, sábado y domingo de cada una).

### Franja de §10.2 por hora

| Ruta | Tipo de día | Horas viables | Horas no viables y causa |
|---|---|---|---|
| CL 72 | Domingo/festivo | 100,0 % (68 de 68) | — |
| CL 72 | Laboral | 88,2 % (60 de 68) | 14 h (0 % viable; reparto por tipología 4, banda P90 4); 5 h (0 % viable; reparto por tipología 4) |
| CL 72 | Sábado | 100,0 % (68 de 68) | — |
| CRA 54 | Domingo/festivo | 100,0 % (68 de 68) | — |
| CRA 54 | Laboral | 66,2 % (45 de 68) | 13 h (0 % viable; reparto por tipología 4, banda P90 2); 14 h (0 % viable; combinada 2, reparto por tipología 2); 15 h (25 % viable; reparto por tipología 3, banda P90 2); 5 h (0 % viable; combinada 4); 6 h (0 % viable; combinada 4); 7 h (0 % viable; reparto por tipología 4, banda P90 3) |
| CRA 54 | Sábado | 86,8 % (59 de 68) | 5 h (75 % viable; reparto por tipología 1, banda P90 1); 6 h (0 % viable; combinada 3, reparto por tipología 1); 7 h (0 % viable; reparto por tipología 4, banda P90 2) |
| SILENCIO | Domingo/festivo | 52,9 % (36 de 68) | 10 h (0 % viable; reparto por tipología 4); 11 h (0 % viable; reparto por tipología 4); 12 h (0 % viable; reparto por tipología 4); 13 h (0 % viable; reparto por tipología 4); 14 h (0 % viable; reparto por tipología 4); 15 h (0 % viable; reparto por tipología 4); 16 h (0 % viable; reparto por tipología 4); 17 h (0 % viable; reparto por tipología 4) |
| SILENCIO | Laboral | 66,2 % (45 de 68) | 12 h (75 % viable; reparto por tipología 1, banda P90 1); 13 h (0 % viable; reparto por tipología 4, banda P90 4); 14 h (0 % viable; reparto por tipología 3, combinada 1); 15 h (0 % viable; reparto por tipología 4, banda P90 3); 16 h (50 % viable; reparto por tipología 2, banda P90 2); 5 h (0 % viable; combinada 4); 6 h (0 % viable; reparto por tipología 4) |
| SILENCIO | Sábado | 89,7 % (61 de 68) | 5 h (25 % viable; reparto por tipología 3, banda P90 3); 6 h (0 % viable; reparto por tipología 4, banda P90 4) |

### Plan del día (MILP de D5) por hora

En el plan la capacidad no es una restricción dura (la sobrecarga esperada se penaliza en el costo): una hora es no viable si la demanda pide más salidas de las que permite el headway mínimo o si la flota no sostiene las salidas mínimas.

| Ruta | Tipo de día | Horas viables | Horas no viables | Horas con sobreoferta |
|---|---|---|---|---|
| CL 72 | Domingo/festivo | 100,0 % (68 de 68) | — | 5 h, 6 h, 7 h, 8 h, 9 h, 10 h, 11 h, 12 h, 13 h, 14 h, 15 h, 16 h, 17 h, 18 h, 19 h, 20 h |
| CL 72 | Laboral | 100,0 % (68 de 68) | — | 4 h, 8 h, 9 h, 10 h, 11 h, 12 h, 15 h, 16 h, 17 h, 18 h, 19 h, 20 h |
| CL 72 | Sábado | 100,0 % (68 de 68) | — | 4 h, 7 h, 8 h, 9 h, 10 h, 11 h, 12 h, 13 h, 14 h, 15 h, 16 h, 17 h, 18 h, 19 h, 20 h |
| CRA 54 | Domingo/festivo | 100,0 % (68 de 68) | — | 4 h, 19 h, 20 h |
| CRA 54 | Laboral | 94,1 % (64 de 68) | 5 h | 20 h |
| CRA 54 | Sábado | 100,0 % (68 de 68) | — | 20 h |
| SILENCIO | Domingo/festivo | 100,0 % (68 de 68) | — | 4 h, 5 h, 6 h, 7 h, 8 h, 9 h, 10 h, 11 h, 12 h, 13 h, 14 h, 15 h, 16 h, 17 h, 18 h, 19 h, 20 h |
| SILENCIO | Laboral | 100,0 % (68 de 68) | — | 10 h, 11 h, 17 h, 18 h, 19 h, 20 h |
| SILENCIO | Sábado | 100,0 % (68 de 68) | — | 4 h, 11 h, 12 h, 13 h, 14 h, 15 h, 16 h, 17 h, 18 h, 19 h, 20 h |

## La hora pico de CRA 54 (hallazgo H13)

- 2025-03-12 (Laboral) 6 h: P50 2.405, P90 2.646; programada 26,5 buses/h, que con el ciclo de 243,8 min pide 108 vehículos; flota 79; no viable (causa: combinada).
- 2025-03-12 (Laboral) 7 h: P50 1.792, P90 1.951; programada 20,4 buses/h, que con el ciclo de 249,1 min pide 85 vehículos; flota 79; no viable (causa: reparto por tipología).
- 2025-03-15 (Sábado) 6 h: P50 2.103, P90 2.188; programada 22,4 buses/h, que con el ciclo de 217,8 min pide 82 vehículos; flota 75; no viable (causa: reparto por tipología).
- 2025-03-15 (Sábado) 7 h: P50 1.756, P90 1.938; programada 24,3 buses/h, que con el ciclo de 237,3 min pide 97 vehículos; flota 75; no viable (causa: reparto por tipología).
- 2025-03-16 (Domingo/festivo) 6 h: P50 600, P90 696; programada 13,2 buses/h, que con el ciclo de 164,3 min pide 37 vehículos; flota 45; viable.
- 2025-03-16 (Domingo/festivo) 7 h: P50 578, P90 706; programada 13,5 buses/h, que con el ciclo de 166,8 min pide 38 vehículos; flota 45; viable.
- 2025-06-11 (Laboral) 6 h: P50 2.301, P90 2.530; programada 26,5 buses/h, que con el ciclo de 243,8 min pide 108 vehículos; flota 79; no viable (causa: combinada).
- 2025-06-11 (Laboral) 7 h: P50 1.641, P90 1.805; programada 20,4 buses/h, que con el ciclo de 249,1 min pide 85 vehículos; flota 79; no viable (causa: reparto por tipología, banda P90).
- 2025-06-14 (Sábado) 6 h: P50 1.967, P90 2.234; programada 22,4 buses/h, que con el ciclo de 217,8 min pide 82 vehículos; flota 75; no viable (causa: combinada).
- 2025-06-14 (Sábado) 7 h: P50 1.643, P90 1.871; programada 24,3 buses/h, que con el ciclo de 237,3 min pide 97 vehículos; flota 75; no viable (causa: reparto por tipología, banda P90).
- 2025-06-15 (Domingo/festivo) 6 h: P50 572, P90 672; programada 13,2 buses/h, que con el ciclo de 164,3 min pide 37 vehículos; flota 45; viable.
- 2025-06-15 (Domingo/festivo) 7 h: P50 597, P90 682; programada 13,5 buses/h, que con el ciclo de 166,8 min pide 38 vehículos; flota 45; viable.
- 2025-09-10 (Laboral) 6 h: P50 2.242, P90 2.612; programada 26,5 buses/h, que con el ciclo de 243,8 min pide 108 vehículos; flota 79; no viable (causa: combinada).
- 2025-09-10 (Laboral) 7 h: P50 1.644, P90 1.827; programada 20,4 buses/h, que con el ciclo de 249,1 min pide 85 vehículos; flota 79; no viable (causa: reparto por tipología, banda P90).
- 2025-09-13 (Sábado) 6 h: P50 1.944, P90 2.229; programada 22,4 buses/h, que con el ciclo de 217,8 min pide 82 vehículos; flota 75; no viable (causa: combinada).
- 2025-09-13 (Sábado) 7 h: P50 1.680, P90 1.886; programada 24,3 buses/h, que con el ciclo de 237,3 min pide 97 vehículos; flota 75; no viable (causa: reparto por tipología, banda P90).
- 2025-09-14 (Domingo/festivo) 6 h: P50 639, P90 731; programada 13,2 buses/h, que con el ciclo de 164,3 min pide 37 vehículos; flota 45; viable.
- 2025-09-14 (Domingo/festivo) 7 h: P50 662, P90 768; programada 13,5 buses/h, que con el ciclo de 166,8 min pide 38 vehículos; flota 45; viable.
- 2025-11-19 (Laboral) 6 h: P50 2.280, P90 2.539; programada 26,5 buses/h, que con el ciclo de 243,8 min pide 108 vehículos; flota 79; no viable (causa: combinada).
- 2025-11-19 (Laboral) 7 h: P50 1.654, P90 1.832; programada 20,4 buses/h, que con el ciclo de 249,1 min pide 85 vehículos; flota 79; no viable (causa: reparto por tipología, banda P90).
- 2025-11-22 (Sábado) 6 h: P50 2.103, P90 2.302; programada 22,4 buses/h, que con el ciclo de 217,8 min pide 82 vehículos; flota 75; no viable (causa: combinada).
- 2025-11-22 (Sábado) 7 h: P50 1.751, P90 1.901; programada 24,3 buses/h, que con el ciclo de 237,3 min pide 97 vehículos; flota 75; no viable (causa: reparto por tipología).
- 2025-11-23 (Domingo/festivo) 6 h: P50 602, P90 708; programada 13,2 buses/h, que con el ciclo de 164,3 min pide 37 vehículos; flota 45; viable.
- 2025-11-23 (Domingo/festivo) 7 h: P50 694, P90 783; programada 13,5 buses/h, que con el ciclo de 166,8 min pide 38 vehículos; flota 45; viable.

La programación vigente de CRA 54 en la hora pico no cabe en la flota con el ciclo mediano: buses/h × ciclo / 60 pide de 82 a 108 vehículos frente a una flota de 75 y 79 (H13, `docs/hallazgos_extreme.md`). Por eso la franja sale no viable aunque la operación la corre hoy: o el ciclo real de la hora pico es más corto que la mediana de 2025, o hay más vehículos que los de la flota registrada. Se pide a Extreme el ciclo por franja y la flota disponible por tipo de día (§19).

