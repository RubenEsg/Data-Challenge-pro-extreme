# ALT-003 en todas las horas de servicio (ciclo desde las 5:00 hasta las 19:00, 2025-09-15 a 2025-12-31)

Generado 2026-11-10T20:10:50-05:00 con `scripts/backtest_alertas.py --alt003-todas-las-horas` (919,0 s): la robustez del protocolo de `backtest_alertas_pronostico.md` fuera de la franja de las 6:00.

## Diagnóstico y variantes

4860 franjas; tasa base (carga crítica real > capacidad efectiva): 0,121. Con ALT-001 en la misma franja: 597 franjas, 0,553 positivas (ahí ALT-003 no se emite: ALT-001 la incluye, §18). La regla anterior de ALT-003 (solo el nivel de servicio) en las demás: 994 franjas, 0,225 positivas. Sin alerta: 3269 franjas, 0,011 positivas. La señal de frecuencia insuficiente que ve el operador (ALT-003 sola o dentro de ALT-001): 0,348 positivas en 1591 franjas.

Validación 2025-09-15 a 2025-10-31; evaluación 2025-11-01 a 2025-12-31. Variante: alertar si la frecuencia actual no cumple el nivel de servicio y P(carga crítica > capacidad efectiva) ≥ p. «Elegible» = franjas donde ALT-003 puede emitirse (sin ALT-001).

| p | Validación: alertas | precisión | lift | lift elegible | Evaluación: alertas | precisión | lift | lift elegible |
|---|---|---|---|---|---|---|---|---|
| 0,10 (anterior) | 502 | 0,229 | 1,63 | 3,22 | 492 | 0,222 | 2,08 | 4,14 |
| 0,15 | 378 | 0,267 | 1,90 | 3,76 | 347 | 0,265 | 2,48 | 4,95 |
| 0,20 | 277 | 0,300 | 2,13 | 4,22 | 248 | 0,294 | 2,76 | 5,50 |
| 0,25 | 184 | 0,321 | 2,28 | 4,51 | 172 | 0,331 | 3,10 | 6,19 |
| 0,30 (adoptada) | 119 | 0,344 | 2,45 | 4,85 | 103 | 0,359 | 3,37 | 6,71 |
| 0,35 | 64 | 0,391 | 2,78 | 5,50 | 63 | 0,413 | 3,87 | 7,71 |
| 0,40 (elegida) | 27 | 0,444 | 3,17 | 6,25 | 44 | 0,455 | 4,26 | 8,49 |
| 0,50 | 5 | 0,600 | 4,27 | 8,44 | 18 | 0,444 | 4,16 | 8,30 |

Elegida en validación: p = 0,40 (mayor lift elegible con al menos 20 alertas). En evaluación: 44 alertas, precisión 0,455, lift elegible 8,49 [5,79; 11,70] y lift sobre todas las franjas 4,26 [2,86; 5,81] (IC bootstrap del 95 %, 2000 remuestreos de días). La regla anterior (p = 0,10) en la misma ventana: 492 alertas, precisión 0,222, lift elegible 4,14 [3,55; 5,03] y lift sobre todas las franjas 2,08 [1,74; 2,53].
La adoptada en threshold_config (p = 0,30, la elegida con el ciclo de las 6:00), en la misma ventana de evaluación: 103 alertas, precisión 0,359, lift elegible 6,71 [5,13; 8,79] y lift sobre todas las franjas 3,37 [2,50; 4,44].
