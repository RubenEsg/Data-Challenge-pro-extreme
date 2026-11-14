# Backtest de alertas observadas: ALT-002 (ocupación observada), ALT-005..ALT-009 y rupturas (2025-09-15 a 2025-12-31)

Generado 2026-11-10T10:19:40-05:00 con scripts/backtest_alertas.py. Modelo: modelo activo hgb_fv2_20250831_s42 (corte 2025-08-31). Banda P10-P90 calibrada en el 100,0 % de las horas. 324 días-ruta, 108 días.

Calibración de la banda: v2 — conformal de Mondrian por bloque (calibracion_v2.json, SHA-256 dae6b1a616ee…). ALT-005 y ALT-007 dependen de esa banda; ALT-006, ALT-008 y ALT-009 no.

**Antes del cambio** (calibración v1, corrida del 2026-11-09T02:07:46-05:00): 0,509 alertas observadas por ruta y día; ALT-005 0,1451 por ruta y día (precisión 0,359, lift 4,70); ALT-006 0,1265 por ruta y día (precisión 0,390, lift 8,30); ALT-007 0,1759 por ruta y día (precisión 0,255, lift 1,28); ALT-008 0,0617 por ruta y día (precisión 0,700, lift 3,78). Reglas anteriores: 6,083.

Festivos entre semana del periodo (5): 2025-10-13, 2025-11-03, 2025-11-17, 2025-12-08, 2025-12-25. Cuentan como domingo o festivo para la programación, el factor de carga y la referencia del consolidado.

Factor de carga de ALT-002 observada: optimizacion.factor_carga_franja, la del ciclo (alertas._factor_de_la_hora): mediana 2025 de carga crítica / abordajes por ruta × día de la semana de operación (7 = domingo o festivo) × hora, con el tipo de día como respaldo. Horas evaluadas con el de día de la semana: 5468; con el de tipo de día: 0; sin factor: 40.

No hay incidentes etiquetados: la precisión se aproxima con la persistencia de la condición en la hora siguiente a la DETECCIÓN, es decir, el episodio dura más horas que las necesarias para alertar (ALT-005/006/007), o con el día marcado como especial o excluido (ALT-008); lift = precisión / tasa base de la condición en una hora cualquiera. Una alerta no confirmada se cuenta como falso positivo (§18).

ALT-006: Procesos.toleranciatiempo = 0 en la exportación: se usa tolerancia_despacho_min.

## Umbrales por defecto (versionados en threshold_config por la migración 0003)

| Código | Alertas | Por ruta y día | Por día (3 rutas) | Precisión proxy | Tasa base | Lift | En días especiales |
|---|---|---|---|---|---|---|---|
| ALT-002 | 230 | 0,710 | 2,13 | 0,404 | 0,183 | 2,21 | 13,5 % |
| ALT-005 | 46 | 0,142 | 0,43 | 0,359 | 0,077 | 4,69 | 41,3 % |
| ALT-006 | 41 | 0,127 | 0,38 | 0,390 | 0,047 | 8,30 | 68,3 % |
| ALT-007 | 66 | 0,204 | 0,61 | 0,270 | 0,202 | 1,34 | 27,3 % |
| ALT-007 ruptura | 4 | 0,012 | 0,04 | 0,667 | — | — | 75,0 % |
| ALT-008 | 23 | 0,071 | 0,21 | 0,652 | 0,185 | 3,52 | 65,2 % |
| ALT-009 | 0 | 0,000 | 0,00 | — | — | — | — |

Alertas observadas por ruta y día (todas): 1,265; solo ALT-005 a ALT-009 (las que ya medía la versión anterior): 0,543.

- ALT-002 observada: ocupación = factor de carga de la franja × pasajeros / (salidas × puestos) ≥ 90 % en horas con al menos 2 salidas (no en la primera ni en la última hora de servicio); precisión proxy: el episodio sigue en la hora siguiente.
- ALT-007 ruptura (RF-009): CUSUM de dos lados sobre el residuo diario relativo; precisión proxy: el nivel nuevo se sostiene en los 14 días siguientes (ver la sección del detector).
- ALT-008 evalúa subidas (Σ pasajeros), bajadas (Σ bajadas_viajes, la misma definición) y número de viajes con el mismo z robusto y los mismos umbrales; campos con |z| sobre el umbral en las alertas: bajadas 21, nro_viajes 7, subidas 20. Sin evaluar las bajadas (como antes de la migración 0013): 20 alertas (0,0617 por ruta y día, precisión 0,700, lift 3,78).

## Detector de rupturas de comportamiento (RF-009)

CUSUM tabular de dos lados sobre el residuo diario relativo (real - pronóstico) / pronóstico de cada ruta, estandarizado con la mediana y 1,4826·MAD de los primeros 28 días; k = 0,5, h = 6,0, cambio mínimo 8 % y 7 días de espera tras cada detección (un cambio sostenido es una sola ruptura).

| Ruta | Inicio estimado | Detección | Sentido | Cambio medio | CUSUM | Se sostuvo 14 días |
|---|---|---|---|---|---|---|
| CRA 54 | 2025-12-08 | 2025-12-08 | - | -24,2 % | 8,37 | sí |
| CRA 54 | 2025-12-16 | 2025-12-17 | + | 11,6 % | 7,49 | no |
| SILENCIO | 2025-10-29 | 2025-11-01 | - | -10,4 % | 6,64 | sí |
| SILENCIO | 2025-12-30 | 2025-12-31 | - | -18,7 % | 6,76 | — |

Falsas alarmas sin cambio (los días vigilados de cada ruta permutados 200 veces: misma distribución de residuos, sin ruptura): 789 detecciones en 48000 días-ruta = 1,644 por cada 100 días-ruta.

| Cambio inyectado | Casos | Detectados en 14 días | Tasa | Retardo mediano (días) |
|---|---|---|---|---|
| -10% | 9 | 4 | 0,444 | 5,5 |
| -20% | 9 | 9 | 1,000 | 6,0 |
| +15% | 9 | 7 | 0,778 | 4,0 |

Falsas alarmas sin cambio por cada 100 días-ruta según h y el cambio mínimo (50 permutaciones por ruta; la elección de los valores por omisión): h=4, cambio_minimo=5%: 4,092; h=4, cambio_minimo=8%: 2,642; h=5, cambio_minimo=5%: 3,342; h=5, cambio_minimo=8%: 2,117; h=6, cambio_minimo=5%: 2,858; h=6, cambio_minimo=8%: 1,825.

## Reglas anteriores (sin persistencia, sin P10, tolerancia de salidas 20 %, |z| 3,0)

| Código | Alertas | Por ruta y día | Por día (3 rutas) | Precisión proxy | Tasa base | Lift | En días especiales |
|---|---|---|---|---|---|---|---|
| ALT-002 | 230 | 0,710 | 2,13 | 0,404 | 0,183 | 2,21 | 13,5 % |
| ALT-005 | 420 | 1,296 | 3,89 | 0,168 | 0,095 | 1,77 | 26,4 % |
| ALT-006 | 923 | 2,849 | 8,55 | 0,369 | 0,281 | 1,31 | 16,8 % |
| ALT-007 | 594 | 1,833 | 5,50 | 0,157 | 0,202 | 0,78 | 18,5 % |
| ALT-007 ruptura | 4 | 0,012 | 0,04 | — | — | — | 75,0 % |
| ALT-008 | 34 | 0,105 | 0,32 | 0,500 | 0,185 | 2,70 | 50,0 % |
| ALT-009 | 0 | 0,000 | 0,00 | — | — | — | — |

Alertas observadas por ruta y día (todas): 6,806; solo ALT-005 a ALT-009: 6,083.

## Sensibilidad (un umbral a la vez; por ruta y día / precisión proxy / lift)

| Variación | ALT-002 | ALT-005 | ALT-006 | ALT-007 | ALT-007 ruptura | ALT-008 |
|---|---|---|---|---|---|---|
| persistencia_horas=1 | 0,710 / 0,404 / 2,210 | 1,068 / 0,151 / 1,970 | 0,565 / 0,202 / 4,300 | 1,833 / 0,157 / 0,780 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| persistencia_horas=2 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| persistencia_horas=3 | 0,710 / 0,404 / 2,210 | 0,043 / 0,615 / 8,030 | 0,068 / 0,318 / 6,770 | 0,065 / 0,238 / 1,180 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| persistencia_ocupacion_horas=1 | 1,596 / 0,445 / 2,430 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| persistencia_ocupacion_horas=2 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| persistencia_ocupacion_horas=3 | 0,287 / 0,409 / 2,230 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| ruptura_h=4.0 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,015 / 1,000 / — | 0,071 / 0,652 / 3,520 |
| ruptura_h=5.0 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,015 / 0,500 / — | 0,071 / 0,652 / 3,520 |
| ruptura_h=6.0 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| ruptura_cambio_minimo=0.05 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,022 / 0,600 / — | 0,071 / 0,652 / 3,520 |
| ruptura_cambio_minimo=0.08 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| alt005_exigir_p10=0 | 0,710 / 0,404 / 2,210 | 0,188 / 0,367 / 3,880 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| alt005_exigir_p10=1 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| caida_demanda=0.2 | 0,710 / 0,404 / 2,210 | 0,238 / 0,353 / 3,160 | 0,127 / 0,390 / 8,300 | 0,105 / 0,273 / 1,350 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| caida_demanda=0.3 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| caida_demanda=0.4 | 0,710 / 0,404 / 2,210 | 0,074 / 0,474 / 9,960 | 0,127 / 0,390 / 8,300 | 0,275 / 0,321 / 1,590 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| error_pronostico=0.15 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| error_pronostico=0.25 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,093 / 0,276 / 1,800 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| tolerancia_salidas=0.2 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 1,062 / 0,369 / 1,310 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| tolerancia_salidas=0.35 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,340 / 0,318 / 2,560 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| tolerancia_salidas=0.5 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| z_anomalia=3.0 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,105 / 0,500 / 2,700 |
| z_anomalia=3.5 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,071 / 0,652 / 3,520 |
| z_anomalia=4.0 | 0,710 / 0,404 / 2,210 | 0,142 / 0,359 / 4,690 | 0,127 / 0,390 / 8,300 | 0,204 / 0,270 / 1,340 | 0,012 / 0,667 / — | 0,049 / 0,812 / 4,390 |

## Un ejemplo por código (lo que vería el operador, §9.4)

| Código | Ruta | Ventana | Real | Esperado | Umbral | Tendencia | Explicación |
|---|---|---|---|---|---|---|---|
| ALT-002 | CL 72 | 2025-09-15 13:00-17:00 | 1.1244 | 0.8215 | 0.9 | sin_datos | La ocupación observada (112,4 %) alcanza o supera el umbral crítico (90,0 %). Esperada: 82,1 %; observada: 112,4 % (= factor de carga 0,441 × 637 pasajeros ÷ (5 salidas × 50 puestos) en 14:00-15:00). |
| ALT-005 | CL 72 | 2025-10-10 10:00-13:00 | 885.0 | 1371.0089 | 959.7063 | a_la_baja | Durante 3 hora(s) seguidas (10:00-13:00) la demanda real (885 pasajeros) cayó 35,4 % frente al patrón del modelo (1.371); el umbral de caída es 30,0 % (límite 960) y quedó bajo el P10 calibrado (993); persistencia exigida: 2 h. |
| ALT-006 | CL 72 | 2025-09-17 11:00-12:00 | 60.0 | 14.371 | 19.371 | a_la_baja | En 11:00-12:00 (1 h): salieron 0 de 4 despachos esperados (60 / intervalo programado). Despacho ausente o tardío: van al menos 60 min sin despacho (cota inferior: horas cerradas sin salidas), más que el headway programado (14,4 min) más la tolerancia (5 min, threshold_config.tolerancia_despacho_min); salieron 0 de 4 despachos esperados (déficit 100,0 %, tolerancia 50,0 %). |
| ALT-007 | CL 72 | 2025-09-18 04:00-06:00 | 749.0 | 1305.4442 | 990.152 | al_alza | Durante 2 hora(s) seguidas (04:00-06:00) la demanda real (749) quedó por debajo del P10 del intervalo calibrado (990); pronóstico 1.305, error 42,6 % (umbral 15,0 %); persistencia exigida: 2 h. |
| ALT-007 | CRA 54 | 2025-12-08 00:00-00:00 | -0.2391 | 0.0027 | -0.0773 | estable | Ruptura de comportamiento: desde el 08/12/2025 la demanda real diaria quedó por debajo del pronóstico de forma sostenida (1 día hasta la detección; residuo medio -23,9 % frente a 0,3 % del nivel anterior (referencia de 28 días: -1,0 %), cambio -24,2 %). El CUSUM llegó a 8,37 con umbral h = 6,0 (k = 0,5). No es una hora aislada: cambió el nivel de la demanda frente al patrón del modelo. |
| ALT-008 | CL 72 | 2025-10-10 00:00-00:00 | 5829.0 | 7508.0 | 5920.1354 | estable | Consolidado atípico: subidas = 5.829 frente a la mediana de 7.508,0 (z = -3,70) (umbral |z| ≥ 3,5). Límite para subidas: 5.920 (mediana 7.508 - 3,5 × 453,7). |

Duración: 10,3 s.
