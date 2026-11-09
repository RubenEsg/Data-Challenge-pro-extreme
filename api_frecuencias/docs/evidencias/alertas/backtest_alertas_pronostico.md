# Alertas de pronóstico ALT-001..ALT-004 del ciclo diario (2025-09-15 a 2025-12-31)

Generado 2026-11-09T06:32:29-05:00 con `scripts/backtest_alertas.py --pronostico` (197,5 s). 324 días-ruta; instante 6:00 de cada día (el instante por omisión del ciclo diario); horizontes 30, 60 y 120 min; umbrales alertas.UMBRALES_POR_DEFECTO (versión 0003); banda calibrada v2; recomendación recomendacion_franja(): §10.2 (MILP) con la demanda por hora de la franja.

- **Antes de la corrección**: demanda de la VENTANA de 30/60/120 min frente a la capacidad POR HORA; ventana de la alerta = hora del fin de la ventana (7 h y 8 h en 60 y 120 min, no la hora recomendada); una alerta por horizonte.
- **Ahora**: alertas.contexto_pronostico + evaluar_pronostico (lo que hace hoy el ciclo): carga crítica POR HORA de la franja recomendada (factor de carga del optimizador × P10/P50/P90 por hora) frente a la capacidad POR HORA ofrecida; ALT-003 por el nivel de servicio de la frecuencia actual (comparacion_actual); ventana de la alerta = la hora recomendada; los horizontes que caen en la misma franja dan una sola alerta.

| Código | Antes: alertas | Antes: por ruta y día | Ahora: alertas | Ahora: por ruta y día |
|---|---|---|---|---|
| ALT-001 | 827 | 2,552 | 141 | 0,435 |
| ALT-002 | 764 | 2,358 | 102 | 0,315 |
| ALT-003 | 81 | 0,250 | 123 | 0,380 |
| ALT-004 | 1 | 0,003 | 10 | 0,031 |

Confirmación con la demanda real de la hora de la alerta (cada alerta se confirma con la demanda REAL de su hora, en las mismas unidades: carga crítica real = factor de carga × pasajeros reales; ALT-001 si superó la capacidad por hora (buses/h programados × 50 puestos), ALT-002 si la ocupación real llegó al 90 %, ALT-003 si superó la capacidad efectiva (× 85 %) y ALT-004 si la ocupación real quedó bajo el 30 %; la tasa base es la de esa condición en las horas que miran los contextos (lift = precisión / tasa base).)

| Código | Variante | Evaluables | Confirmadas | Precisión | Tasa base | Lift |
|---|---|---|---|---|---|---|
| ALT-001 | antes | 827 | 735 | 0,889 | 0,819 | 1,09 |
| ALT-001 | ahora | 141 | 44 | 0,312 | 0,176 | 1,77 |
| ALT-002 | antes | 764 | 717 | 0,939 | 0,871 | 1,08 |
| ALT-002 | ahora | 102 | 81 | 0,794 | 0,395 | 2,01 |
| ALT-003 | antes | 81 | 61 | 0,753 | 0,896 | 0,84 |
| ALT-003 | ahora | 123 | 44 | 0,358 | 0,478 | 0,75 |
| ALT-004 | antes | 1 | 0 | 0,000 | 0,003 | 0,00 |
| ALT-004 | ahora | 10 | 4 | 0,400 | 0,052 | 7,62 |

Antes de medir con el factor de carga (corrida del 2026-11-09T05:03:33-05:00: ocupación = abordajes / capacidad, ALT-003 por número de buses): ALT-001 0,889, ALT-002 0,858, ALT-003 0,318, ALT-004 0,000 alertas por ruta y día.

Festivos entre semana del periodo (5, tratados como domingo o festivo en la programación y el factor de carga): 2025-10-13, 2025-11-03, 2025-11-17, 2025-12-08, 2025-12-25.

Franja recomendada por horizonte (horizonte -> hora principal de la ventana, número de predicciones): 30->06 h: 324, 60->06 h: 324, 120->06 h: 324.

Buses/h recomendados en promedio por horizonte: 30 min 9,96, 60 min 9,96, 120 min 9,96. Recomendaciones viables: 46,0 %. MILP: 324 franjas distintas, 0,072 s de media.

Antes de la recomendación por franja (corrida del 2026-11-09T03:40:52-05:00, recomendar() con la demanda de la ventana): ALT-001 2,744, ALT-002 2,648, ALT-003 2,157, ALT-004 0,006 alertas por ruta y día.
