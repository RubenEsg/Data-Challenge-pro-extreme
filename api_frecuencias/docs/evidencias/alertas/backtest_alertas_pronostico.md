# Alertas de pronóstico ALT-001..ALT-004 del ciclo diario (2025-09-15 a 2025-12-31)

Generado 2026-11-10T10:21:37-05:00 con `scripts/backtest_alertas.py --pronostico` (50,4 s). 324 días-ruta; instante 6:00 de cada día (el instante por omisión del ciclo diario); horizontes 30, 60 y 120 min; umbrales alertas.UMBRALES_POR_DEFECTO (versión 0003); banda calibrada v2; recomendación recomendacion_franja(): §10.2 (MILP) con la demanda por hora de la franja.

- **Antes de la corrección**: demanda de la VENTANA de 30/60/120 min frente a la capacidad POR HORA; ventana de la alerta = hora del fin de la ventana (7 h y 8 h en 60 y 120 min, no la hora recomendada); una alerta por horizonte.
- **Ahora**: alertas.contexto_pronostico + evaluar_pronostico (lo que hace hoy el ciclo): carga crítica POR HORA de la franja recomendada (factor de carga del optimizador × P10/P50/P90 por hora) frente a la capacidad POR HORA ofrecida; ALT-003 por el nivel de servicio de la frecuencia actual (comparacion_actual) con la probabilidad mínima de superar la capacidad efectiva (alt003_probabilidad_minima); ventana de la alerta = la hora recomendada; los horizontes que caen en la misma franja dan una sola alerta.

| Código | Antes: alertas | Antes: por ruta y día | Ahora: alertas | Ahora: por ruta y día |
|---|---|---|---|---|
| ALT-001 | 827 | 2,552 | 142 | 0,438 |
| ALT-002 | 764 | 2,358 | 99 | 0,306 |
| ALT-003 | 56 | 0,173 | 53 | 0,164 |
| ALT-004 | 1 | 0,003 | 10 | 0,031 |

Confirmación con la demanda real de la hora de la alerta (cada alerta se confirma con la demanda REAL de su hora, en las mismas unidades: carga crítica real = factor de carga × pasajeros reales; ALT-001 si superó la capacidad por hora (buses/h programados × 50 puestos), ALT-002 si la ocupación real llegó al 90 %, ALT-003 si superó la capacidad efectiva (× 85 %) y ALT-004 si la ocupación real quedó bajo el 30 %; la tasa base es la de esa condición en las horas que miran los contextos (lift = precisión / tasa base).) «Donde puede emitirse»: la tasa base de las franjas sin ALT-001, porque ALT-003 no se emite donde sale ALT-001 (§18, va incluida en ella); para los demás códigos es la misma tasa base.

| Código | Variante | Evaluables | Confirmadas | Precisión | Tasa base | Lift | Tasa base donde puede emitirse | Lift donde puede emitirse |
|---|---|---|---|---|---|---|---|---|
| ALT-001 | antes | 827 | 735 | 0,889 | 0,819 | 1,09 | 0,819 | 1,09 |
| ALT-001 | ahora | 142 | 42 | 0,296 | 0,164 | 1,81 | 0,164 | 1,81 |
| ALT-002 | antes | 764 | 717 | 0,939 | 0,871 | 1,08 | 0,871 | 1,08 |
| ALT-002 | ahora | 99 | 80 | 0,808 | 0,398 | 2,03 | 0,398 | 2,03 |
| ALT-003 | antes | 56 | 51 | 0,911 | 0,896 | 1,02 | 0,607 | 1,50 |
| ALT-003 | ahora | 53 | 26 | 0,491 | 0,469 | 1,05 | 0,236 | 2,08 |
| ALT-004 | antes | 1 | 0 | 0,000 | 0,003 | 0,00 | 0,003 | 0,00 |
| ALT-004 | ahora | 10 | 4 | 0,400 | 0,052 | 7,62 | 0,052 | 7,62 |

ALT-003 antes de la elección sin fuga (corrida del 2026-11-09T06:32:29-05:00, solo el nivel de servicio, lift contra todas las franjas): 123 alertas (0,380 por ruta y día), precisión 0,358, tasa base 0,478, lift 0,75.

Mínimo de probabilidad vigente de ALT-003 en esta corrida (alt003_probabilidad_minima): 0,30.

## ALT-003: diagnóstico y elección del umbral sin fuga

324 franjas; tasa base (carga crítica real > capacidad efectiva): 0,469. Con ALT-001 en la misma franja: 142 franjas, 0,768 positivas (ahí ALT-003 no se emite: ALT-001 la incluye, §18). La regla anterior de ALT-003 (solo el nivel de servicio) en las demás: 121 franjas, 0,355 positivas. Sin alerta: 61 franjas, 0,000 positivas. La señal de frecuencia insuficiente que ve el operador (ALT-003 sola o dentro de ALT-001): 0,578 positivas en 263 franjas.

Validación 2025-09-15 a 2025-10-31; evaluación 2025-11-01 a 2025-12-31. Variante: alertar si la frecuencia actual no cumple el nivel de servicio y P(carga crítica > capacidad efectiva) ≥ p. «Elegible» = franjas donde ALT-003 puede emitirse (sin ALT-001).

| p | Validación: alertas | precisión | lift | lift elegible | Evaluación: alertas | precisión | lift | lift elegible |
|---|---|---|---|---|---|---|---|---|
| 0,10 (anterior) | 62 | 0,274 | 0,59 | 1,35 | 59 | 0,441 | 0,93 | 1,66 |
| 0,15 | 56 | 0,304 | 0,66 | 1,50 | 55 | 0,455 | 0,96 | 1,71 |
| 0,20 | 45 | 0,356 | 0,77 | 1,76 | 48 | 0,417 | 0,88 | 1,57 |
| 0,25 | 36 | 0,361 | 0,78 | 1,78 | 39 | 0,462 | 0,97 | 1,74 |
| 0,30 (elegida y adoptada) | 24 | 0,417 | 0,90 | 2,06 | 29 | 0,552 | 1,16 | 2,08 |
| 0,35 | 12 | 0,500 | 1,08 | 2,47 | 21 | 0,619 | 1,30 | 2,33 |
| 0,40 | 7 | 0,714 | 1,55 | 3,53 | 15 | 0,733 | 1,54 | 2,76 |
| 0,50 | 2 | 0,500 | 1,08 | 2,47 | 8 | 0,625 | 1,31 | 2,36 |

Elegida en validación: p = 0,30 (mayor lift elegible con al menos 20 alertas). En evaluación: 29 alertas, precisión 0,552, lift elegible 2,08 [1,51; 2,99] y lift sobre todas las franjas 1,16 [0,82; 1,51] (IC bootstrap del 95 %, 2000 remuestreos de días). La regla anterior (p = 0,10) en la misma ventana: 59 alertas, precisión 0,441, lift elegible 1,66 [1,31; 2,21] y lift sobre todas las franjas 0,93 [0,69; 1,18].



Antes de medir con el factor de carga (corrida del 2026-11-09T05:03:33-05:00: ocupación = abordajes / capacidad, ALT-003 por número de buses): ALT-001 0,889, ALT-002 0,858, ALT-003 0,318, ALT-004 0,000 alertas por ruta y día.

Festivos entre semana del periodo (5, tratados como domingo o festivo en la programación y el factor de carga): 2025-10-13, 2025-11-03, 2025-11-17, 2025-12-08, 2025-12-25.

Franja recomendada por horizonte (horizonte -> hora principal de la ventana, número de predicciones): 30->06 h: 324, 60->06 h: 324, 120->06 h: 324.

Buses/h recomendados en promedio por horizonte: 30 min 9,97, 60 min 9,97, 120 min 9,97. Recomendaciones viables: 46,0 %. MILP: 324 franjas distintas, 0,062 s de media.

Antes de la recomendación por franja (corrida del 2026-11-09T03:40:52-05:00, recomendar() con la demanda de la ventana): ALT-001 2,744, ALT-002 2,648, ALT-003 2,157, ALT-004 0,006 alertas por ruta y día.
