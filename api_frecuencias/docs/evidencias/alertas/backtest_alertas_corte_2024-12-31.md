# Backtest de alertas observadas: ALT-002 (ocupación observada), ALT-005..ALT-009 y rupturas (2025-01-15 a 2025-12-31)

Generado 2026-11-10T10:22:06-05:00 con scripts/backtest_alertas.py. Modelo: fv2 temporal (corte 2024-12-31, semilla 42, en backtest_alertas_x5wu98ze) (corte 2024-12-31). Banda P10-P90 calibrada en el 100,0 % de las horas. 1053 días-ruta, 351 días.

Calibración de la banda: v2 — conformal de Mondrian por bloque (calibracion_v2.json, SHA-256 8839bccc0c29…). ALT-005 y ALT-007 dependen de esa banda; ALT-006, ALT-008 y ALT-009 no.

**Antes del cambio** (calibración v1, corrida del 2026-11-09T02:08:39-05:00): 0,451 alertas observadas por ruta y día; ALT-005 0,1149 por ruta y día (precisión 0,336, lift 4,58); ALT-006 0,0893 por ruta y día (precisión 0,394, lift 9,57); ALT-007 0,1852 por ruta y día (precisión 0,209, lift 1,14); ALT-008 0,0617 por ruta y día (precisión 0,677, lift 2,10). Reglas anteriores: 5,702.

Festivos entre semana del periodo (14): 2025-03-24, 2025-04-17, 2025-04-18, 2025-05-01, 2025-06-02, 2025-06-23, 2025-06-30, 2025-08-07, 2025-08-18, 2025-10-13, 2025-11-03, 2025-11-17, 2025-12-08, 2025-12-25. Cuentan como domingo o festivo para la programación, el factor de carga y la referencia del consolidado.

Factor de carga de ALT-002 observada: optimizacion.factor_carga_franja, la del ciclo (alertas._factor_de_la_hora): mediana 2025 de carga crítica / abordajes por ruta × día de la semana de operación (7 = domingo o festivo) × hora, con el tipo de día como respaldo. Horas evaluadas con el de día de la semana: 17773; con el de tipo de día: 0; sin factor: 128.

No hay incidentes etiquetados: la precisión se aproxima con la persistencia de la condición en la hora siguiente a la DETECCIÓN, es decir, el episodio dura más horas que las necesarias para alertar (ALT-005/006/007), o con el día marcado como especial o excluido (ALT-008); lift = precisión / tasa base de la condición en una hora cualquiera. Una alerta no confirmada se cuenta como falso positivo (§18).

ALT-006: Procesos.toleranciatiempo = 0 en la exportación: se usa tolerancia_despacho_min.

## Umbrales por defecto (versionados en threshold_config por la migración 0003)

| Código | Alertas | Por ruta y día | Por día (3 rutas) | Precisión proxy | Tasa base | Lift | En días especiales |
|---|---|---|---|---|---|---|---|
| ALT-002 | 772 | 0,733 | 2,20 | 0,421 | 0,183 | 2,30 | 18,1 % |
| ALT-005 | 110 | 0,104 | 0,31 | 0,330 | 0,068 | 4,87 | 44,5 % |
| ALT-006 | 94 | 0,089 | 0,27 | 0,394 | 0,041 | 9,57 | 63,8 % |
| ALT-007 | 125 | 0,119 | 0,36 | 0,202 | 0,152 | 1,33 | 44,0 % |
| ALT-007 ruptura | 27 | 0,026 | 0,08 | 0,480 | — | — | 55,6 % |
| ALT-008 | 69 | 0,066 | 0,20 | 0,652 | 0,322 | 2,03 | 65,2 % |
| ALT-009 | 0 | 0,000 | 0,00 | — | — | — | — |

Alertas observadas por ruta y día (todas): 1,137; solo ALT-005 a ALT-009 (las que ya medía la versión anterior): 0,378.

- ALT-002 observada: ocupación = factor de carga de la franja × pasajeros / (salidas × puestos) ≥ 90 % en horas con al menos 2 salidas (no en la primera ni en la última hora de servicio); precisión proxy: el episodio sigue en la hora siguiente.
- ALT-007 ruptura (RF-009): CUSUM de dos lados sobre el residuo diario relativo; precisión proxy: el nivel nuevo se sostiene en los 14 días siguientes (ver la sección del detector).
- ALT-008 evalúa subidas (Σ pasajeros), bajadas (Σ bajadas_viajes, la misma definición) y número de viajes con el mismo z robusto y los mismos umbrales; campos con |z| sobre el umbral en las alertas: bajadas 59, nro_viajes 22, subidas 59. Sin evaluar las bajadas (como antes de la migración 0013): 65 alertas (0,0617 por ruta y día, precisión 0,677, lift 2,10).

## Detector de rupturas de comportamiento (RF-009)

CUSUM tabular de dos lados sobre el residuo diario relativo (real - pronóstico) / pronóstico de cada ruta, estandarizado con la mediana y 1,4826·MAD de los primeros 28 días; k = 0,5, h = 6,0, cambio mínimo 8 % y 7 días de espera tras cada detección (un cambio sostenido es una sola ruptura).

| Ruta | Inicio estimado | Detección | Sentido | Cambio medio | CUSUM | Se sostuvo 14 días |
|---|---|---|---|---|---|---|
| CL 72 | 2025-03-02 | 2025-03-04 | - | -23,6 % | 7,61 | no |
| CL 72 | 2025-06-24 | 2025-06-30 | + | 14,3 % | 9,37 | no |
| CL 72 | 2025-07-08 | 2025-07-13 | - | -11,8 % | 6,13 | sí |
| CL 72 | 2025-10-04 | 2025-10-11 | - | -10,8 % | 7,18 | no |
| CL 72 | 2025-10-20 | 2025-10-26 | + | 10,8 % | 6,25 | sí |
| CL 72 | 2025-12-24 | 2025-12-31 | - | -12,1 % | 8,49 | — |
| CRA 54 | 2025-03-02 | 2025-03-03 | - | -21,0 % | 10,19 | no |
| CRA 54 | 2025-03-11 | 2025-03-12 | + | 15,2 % | 7,11 | sí |
| CRA 54 | 2025-06-19 | 2025-06-19 | - | -36,5 % | 9,24 | no |
| CRA 54 | 2025-06-27 | 2025-06-28 | + | 13,9 % | 6,43 | sí |
| CRA 54 | 2025-07-06 | 2025-07-09 | - | -14,7 % | 13,65 | sí |
| CRA 54 | 2025-07-17 | 2025-07-20 | + | 20,9 % | 20,33 | sí |
| CRA 54 | 2025-07-28 | 2025-07-29 | - | -19,5 % | 9,39 | no |
| CRA 54 | 2025-08-06 | 2025-08-08 | + | 9,7 % | 6,26 | no |
| CRA 54 | 2025-10-06 | 2025-10-08 | - | -11,0 % | 7,32 | no |
| CRA 54 | 2025-10-16 | 2025-10-18 | + | 11,3 % | 7,54 | sí |
| CRA 54 | 2025-12-08 | 2025-12-09 | - | -14,9 % | 6,96 | no |
| CRA 54 | 2025-12-20 | 2025-12-22 | + | 12,3 % | 8,34 | no |
| CRA 54 | 2025-12-30 | 2025-12-31 | - | -16,1 % | 7,60 | — |
| SILENCIO | 2025-02-16 | 2025-02-23 | - | -14,1 % | 8,13 | sí |
| SILENCIO | 2025-03-05 | 2025-03-14 | + | 10,5 % | 6,21 | sí |
| SILENCIO | 2025-06-23 | 2025-06-29 | + | 15,3 % | 7,95 | no |
| SILENCIO | 2025-07-07 | 2025-07-13 | - | -13,3 % | 6,46 | sí |
| SILENCIO | 2025-08-03 | 2025-08-07 | + | 16,5 % | 6,35 | no |
| SILENCIO | 2025-08-22 | 2025-08-31 | - | -11,9 % | 7,77 | sí |
| SILENCIO | 2025-10-15 | 2025-10-24 | + | 10,4 % | 6,16 | no |
| SILENCIO | 2025-11-03 | 2025-11-20 | - | -8,1 % | 6,70 | sí |

Falsas alarmas sin cambio (los días vigilados de cada ruta permutados 200 veces: misma distribución de residuos, sin ruptura): 2170 detecciones en 193800 días-ruta = 1,120 por cada 100 días-ruta.

| Cambio inyectado | Casos | Detectados en 14 días | Tasa | Retardo mediano (días) |
|---|---|---|---|---|
| -10% | 9 | 4 | 0,444 | 6,5 |
| -20% | 9 | 8 | 0,889 | 3,0 |
| +15% | 9 | 7 | 0,778 | 2,0 |

Falsas alarmas sin cambio por cada 100 días-ruta según h y el cambio mínimo (50 permutaciones por ruta; la elección de los valores por omisión): h=4, cambio_minimo=5%: 3,276; h=4, cambio_minimo=8%: 2,330; h=5, cambio_minimo=5%: 2,272; h=5, cambio_minimo=8%: 1,585; h=6, cambio_minimo=5%: 1,662; h=6, cambio_minimo=8%: 1,119.

## Reglas anteriores (sin persistencia, sin P10, tolerancia de salidas 20 %, |z| 3,0)

| Código | Alertas | Por ruta y día | Por día (3 rutas) | Precisión proxy | Tasa base | Lift | En días especiales |
|---|---|---|---|---|---|---|---|
| ALT-002 | 772 | 0,733 | 2,20 | 0,421 | 0,183 | 2,30 | 18,1 % |
| ALT-005 | 1393 | 1,323 | 3,97 | 0,173 | 0,096 | 1,80 | 35,0 % |
| ALT-006 | 2838 | 2,695 | 8,09 | 0,330 | 0,255 | 1,29 | 30,0 % |
| ALT-007 | 1338 | 1,271 | 3,81 | 0,120 | 0,152 | 0,79 | 33,3 % |
| ALT-007 ruptura | 27 | 0,026 | 0,08 | — | — | — | 55,6 % |
| ALT-008 | 98 | 0,093 | 0,28 | 0,571 | 0,322 | 1,77 | 57,1 % |
| ALT-009 | 0 | 0,000 | 0,00 | — | — | — | — |

Alertas observadas por ruta y día (todas): 6,141; solo ALT-005 a ALT-009: 5,382.

## Sensibilidad (un umbral a la vez; por ruta y día / precisión proxy / lift)

| Variación | ALT-002 | ALT-005 | ALT-006 | ALT-007 | ALT-007 ruptura | ALT-008 |
|---|---|---|---|---|---|---|
| persistencia_horas=1 | 0,733 / 0,421 / 2,300 | 0,982 / 0,116 / 1,710 | 0,509 / 0,166 / 4,040 | 1,271 / 0,120 / 0,790 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| persistencia_horas=2 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| persistencia_horas=3 | 0,733 / 0,421 / 2,300 | 0,032 / 0,452 / 6,660 | 0,044 / 0,348 / 8,460 | 0,026 / 0,259 / 1,710 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| persistencia_ocupacion_horas=1 | 1,547 / 0,474 / 2,590 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| persistencia_ocupacion_horas=2 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| persistencia_ocupacion_horas=3 | 0,309 / 0,382 / 2,080 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| ruptura_h=4.0 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,036 / 0,486 / — | 0,066 / 0,652 / 2,030 |
| ruptura_h=5.0 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,029 / 0,500 / — | 0,066 / 0,652 / 2,030 |
| ruptura_h=6.0 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| ruptura_cambio_minimo=0.05 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,030 / 0,600 / — | 0,066 / 0,652 / 2,030 |
| ruptura_cambio_minimo=0.08 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| alt005_exigir_p10=0 | 0,733 / 0,421 / 2,300 | 0,199 / 0,352 / 3,670 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| alt005_exigir_p10=1 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| caida_demanda=0.2 | 0,733 / 0,421 / 2,300 | 0,137 / 0,301 / 3,570 | 0,089 / 0,394 / 9,570 | 0,082 / 0,210 / 1,380 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| caida_demanda=0.3 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| caida_demanda=0.4 | 0,733 / 0,421 / 2,300 | 0,057 / 0,345 / 8,030 | 0,089 / 0,394 / 9,570 | 0,173 / 0,247 / 1,630 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| error_pronostico=0.15 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| error_pronostico=0.25 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,077 / 0,182 / 1,390 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| tolerancia_salidas=0.2 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,893 / 0,384 / 1,500 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| tolerancia_salidas=0.35 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,273 / 0,335 / 3,050 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| tolerancia_salidas=0.5 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| z_anomalia=3.0 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,093 / 0,571 / 1,770 |
| z_anomalia=3.5 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,066 / 0,652 / 2,030 |
| z_anomalia=4.0 | 0,733 / 0,421 / 2,300 | 0,104 / 0,330 / 4,870 | 0,089 / 0,394 / 9,570 | 0,119 / 0,202 / 1,330 | 0,026 / 0,480 / — | 0,046 / 0,796 / 2,470 |

## Un ejemplo por código (lo que vería el operador, §9.4)

| Código | Ruta | Ventana | Real | Esperado | Umbral | Tendencia | Explicación |
|---|---|---|---|---|---|---|---|
| ALT-002 | CL 72 | 2025-01-16 14:00-17:00 | 1.166 | 0.6962 | 0.9 | sin_datos | La ocupación observada (116,6 %) alcanza o supera el umbral crítico (90,0 %). Esperada: 69,6 %; observada: 116,6 % (= factor de carga 0,384 × 455 pasajeros ÷ (3 salidas × 50 puestos) en 16:00-17:00). |
| ALT-005 | CL 72 | 2025-01-19 14:00-16:00 | 252.0 | 588.9715 | 412.28 | a_la_baja | Durante 2 hora(s) seguidas (14:00-16:00) la demanda real (252 pasajeros) cayó 57,2 % frente al patrón del modelo (589); el umbral de caída es 30,0 % (límite 412) y quedó bajo el P10 calibrado (344); persistencia exigida: 2 h. |
| ALT-006 | CL 72 | 2025-01-19 14:00-16:00 | 4.0 | 9.0502 | 4.5251 | a_la_baja | En 14:00-16:00 (2 h): salieron 4 de 9 despachos esperados (60 / intervalo programado). Despacho ausente o tardío: salieron 4 de 9 despachos esperados (déficit 55,8 %, tolerancia 50,0 %). |
| ALT-007 | CL 72 | 2025-01-18 10:00-12:00 | 480.0 | 776.7934 | 592.6713 | a_la_baja | Durante 2 hora(s) seguidas (10:00-12:00) la demanda real (480) quedó por debajo del P10 del intervalo calibrado (593); pronóstico 777, error 38,2 % (umbral 15,0 %); persistencia exigida: 2 h. |
| ALT-007 | CL 72 | 2025-03-02 00:00-00:00 | -0.2651 | -0.0292 | -0.1092 | a_la_baja | Ruptura de comportamiento: desde el 02/03/2025 la demanda real diaria quedó por debajo del pronóstico de forma sostenida (3 días hasta la detección; residuo medio -26,5 % frente a -2,9 % del nivel anterior (referencia de 28 días: -2,9 %), cambio -23,6 %). El CUSUM llegó a 7,61 con umbral h = 6,0 (k = 0,5). No es una hora aislada: cambió el nivel de la demanda frente al patrón del modelo. |
| ALT-008 | CL 72 | 2025-03-03 00:00-00:00 | 19.0 | 90.0 | 69.2436 | a_la_baja | Consolidado atípico: subidas = 1.770 frente a la mediana de 7.628,0 (z = -6,15); bajadas = 1.777 frente a la mediana de 7.670,0 (z = -7,00); nro_viajes = 19 frente a la mediana de 90,0 (z = -11,97) (umbral |z| ≥ 3,5). Límite para nro_viajes: 69 (mediana 90 - 3,5 × 5,9). |

Duración: 49,5 s.
