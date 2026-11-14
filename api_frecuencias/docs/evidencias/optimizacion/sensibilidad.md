# Sensibilidad de la recomendación de frecuencia (§10.2, §10.3, RF-008)

Generado por `scripts/sensibilidad.py` el 2026-11-11T05:51:52-05:00 (20.5 s). Datos: pronóstico por hora y banda P10-P90 calibrada del modelo activo; ciclo, flota e intervalo programado de la hora (D1); factor de carga crítica por ruta, día de la semana y hora (mediana 2025 de los insumos de D5); tipologías de `tipologias_flota.json`; umbrales de la versión 1 y pesos por omisión del código.

## Formulación

min α·costo_operativo + β·tiempo_espera + γ·penalización_sobreocupación + δ·desviación_frecuencia, con (montos en COP por hora):

- costo_operativo = Σ_t n_t × (ciclo/60 × costo_bus_hora + km_ciclo × costo_km);
- tiempo_espera = pasajeros/h × (60/k)/2 × (1 + cv²) / 60 × valor_tiempo_espera;
- penalización = penalidad × E[(L − C × ocupación_crítica)+], L lognormal con mediana factor × demanda y dispersión del P90 calibrado;
- desviación = costo_cambio × |k − k_programado|.

Sujeto a: k = Σ_t n_t entre ceil(60/headway_max) y floor(60/headway_min); capacidad efectiva C × ocupación_objetivo ≥ cuantil del nivel de servicio de la carga crítica (0,90 = P90); vehículos Σ_t ceil(ciclo × n_t / 60) ≤ flota y n_t ≤ disponibles_t × 60 / ciclo por tipología. MILP de PuLP/CBC con una binaria por nivel k (espera) y cortes tangentes de la sobrecarga (convexa) en todas las capacidades alcanzables, verificado contra la enumeración exacta.

## Casos

Dos líneas base de §10.3: la **literal** (ceil(demanda puntual / capacidad efectiva), factor 1) y la **ajustada** (carga crítica = factor de carga × P90 calibrado, la que se compara con §10.2). El headway máximo es el efectivo, min(headway_maximo_min, 2 × espera_max_min) = 10 min; «sobreoferta» marca una ocupación esperada menor que ocupacion_objetivo_min (65 %).

| Ruta | Día | Hora | Demanda/h (P90) | Recomendada §10.2 | Viable | Límites que mandan | §10.3 literal | §10.3 ajustada | Sobreoferta | Programada | Variaciones que cambian | MILP = enumeración |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SILENCIO | Laboral 2025-03-11 | 7 | 669 (744) | 7 buses/h · 8,57 min · 33 veh. | sí | nivel_servicio, flota_T1, flota_T2, flota_T4 | 16 buses/h (no viable) | 8 buses/h (viable) | no | 8,1 buses/h | 5 de 23 | sí |
| SILENCIO | Laboral 2025-03-11 | 11 | 600 (735) | 6 buses/h · 10,00 min · 26 veh. | sí | headway_maximo, flota_T4 | 15 buses/h (no viable) | 7 buses/h (viable) | sí | 7,5 buses/h | 3 de 23 | sí |
| SILENCIO | Laboral 2025-03-11 | 17 | 536 (678) | 6 buses/h · 10,00 min · 26 veh. | sí | headway_maximo, flota_T4 | 13 buses/h (no viable) | 7 buses/h (viable) | sí | 8,4 buses/h | 3 de 23 | sí |
| SILENCIO | Sábado 2025-03-15 | 7 | 721 (820) | 7 buses/h · 8,57 min · 31 veh. | sí | nivel_servicio, flota_T1, flota_T2, flota_T4 | 17 buses/h (no viable) | 9 buses/h (viable) | no | 9,9 buses/h | 6 de 23 | sí |
| CRA 54 | Laboral 2025-03-11 | 7 | 1.751 (1.898) | 17 buses/h · 3,53 min · 72 veh. | no | — | 30 buses/h (no viable) | 23 buses/h (no viable) | no | 20,4 buses/h | 1 de 23 | sí |
| CRA 54 | Laboral 2025-03-11 | 11 | 1.261 (1.420) | 10 buses/h · 6,00 min · 40 veh. | sí | nivel_servicio, flota_T4 | 30 buses/h (no viable) | 13 buses/h (viable) | no | 16,3 buses/h | 7 de 23 | sí |
| CRA 54 | Laboral 2025-03-11 | 17 | 1.150 (1.283) | 11 buses/h · 5,45 min · 41 veh. | sí | nivel_servicio, flota_T3, flota_T4 | 28 buses/h (no viable) | 14 buses/h (viable) | no | 17,0 buses/h | 8 de 23 | sí |
| CRA 54 | Sábado 2025-03-15 | 7 | 1.756 (1.938) | 17 buses/h · 3,53 min · 68 veh. | no | — | 30 buses/h (no viable) | 22 buses/h (no viable) | no | 24,3 buses/h | 1 de 23 | sí |
| CL 72 | Laboral 2025-03-11 | 7 | 549 (636) | 6 buses/h · 10,00 min · 27 veh. | sí | headway_maximo, nivel_servicio, flota_T2, flota_T3 | 13 buses/h (no viable) | 7 buses/h (viable) | no | 5,8 buses/h | 7 de 23 | sí |
| CL 72 | Laboral 2025-03-11 | 11 | 398 (486) | 6 buses/h · 10,00 min · 26 veh. | sí | headway_maximo, flota_T2, flota_T3 | 10 buses/h (viable) | 6 buses/h (viable) | sí | 4,2 buses/h | 1 de 23 | sí |
| CL 72 | Laboral 2025-03-11 | 17 | 372 (478) | 6 buses/h · 10,00 min · 24 veh. | sí | headway_maximo, flota_T3, flota_T4 | 9 buses/h (viable) | 6 buses/h (viable) | sí | 5,0 buses/h | 2 de 23 | sí |
| CL 72 | Sábado 2025-03-15 | 7 | 435 (552) | 6 buses/h · 10,00 min · 27 veh. | sí | headway_maximo, nivel_servicio, flota_T2, flota_T3 | 11 buses/h (no viable) | 6 buses/h (viable) | sí | 6,8 buses/h | 5 de 23 | sí |
| SILENCIO | Domingo/festivo 2025-11-17 | 7 | 297 (399) | 6 buses/h · 10,00 min · 21 veh. | sí | headway_maximo, flota_T1, flota_T2, flota_T4 | 7 buses/h (viable) | 6 buses/h (viable) | sí | 7,9 buses/h | 0 de 23 | sí |

## Efecto de cada variación (buses/h; «nv» = no viable)

| Variación | SILENCIO 7 h 03-11 | SILENCIO 11 h 03-11 | SILENCIO 17 h 03-11 | SILENCIO 7 h 03-15 | CRA 54 7 h 03-11 | CRA 54 11 h 03-11 | CRA 54 17 h 03-11 | CRA 54 7 h 03-15 | CL 72 7 h 03-11 | CL 72 11 h 03-11 | CL 72 17 h 03-11 | CL 72 7 h 03-15 | SILENCIO 7 h 11-17 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_costo_operativo × 0,0 | 7 | 8 | 8 | 7 | 17 nv | 17 | 17 | 17 nv | 8 | 8 | 8 | 8 | 6 |
| peso_costo_operativo × 0,5 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_costo_operativo × 2,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_costo_operativo × 5,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_tiempo_espera × 0,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_tiempo_espera × 0,5 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_tiempo_espera × 2,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_tiempo_espera × 5,0 | 7 | 8 | 8 | 7 | 17 nv | 13 | 13 | 17 nv | 7 | 6 | 6 | 7 | 6 |
| peso_sobreocupacion × 0,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_sobreocupacion × 0,5 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_sobreocupacion × 2,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_sobreocupacion × 5,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_desviacion_frecuencia × 0,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_desviacion_frecuencia × 0,5 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_desviacion_frecuencia × 2,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| peso_desviacion_frecuencia × 5,0 | 7 | 6 | 6 | 7 | 17 nv | 10 | 11 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| nivel_servicio = 0,80 | 7 | 6 | 6 | 7 | 17 nv | 10 | 10 | 17 nv | 6 | 6 | 6 | 6 | 6 |
| nivel_servicio = 0,95 | 7 | 6 | 6 | 7 nv | 17 nv | 10 | 11 | 17 nv | 7 | 6 | 6 | 6 | 6 |
| nivel_servicio = 0,99 | 7 nv | 6 | 6 | 7 nv | 17 nv | 11 | 12 | 17 nv | 7 | 6 | 6 | 7 | 6 |
| demanda × 0,80 | 6 | 6 | 6 | 6 | 16 | 8 | 8 | 15 | 6 | 6 | 6 | 6 | 6 |
| demanda × 1,20 | 7 nv | 6 | 6 | 7 nv | 17 nv | 12 | 13 | 17 nv | 8 | 6 | 6 | 7 | 6 |
| demanda × 1,50 | 7 nv | 8 | 8 | 7 nv | 17 nv | 16 | 17 | 17 nv | 8 nv | 6 | 7 | 8 | 6 |
| ocupacion_objetivo = 0,75 | 7 nv | 6 | 6 | 7 nv | 17 nv | 11 | 12 | 17 nv | 7 | 6 | 6 | 6 | 6 |

## Tiempo de cálculo: memoria de soluciones del MILP

Las 51 franjas de un día del ciclo (2025-11-19, 3 rutas × 17 horas, demanda y banda del modelo activo) se resolvieron dos veces con `recomendacion_franja`: 3,16 s en frío y 0,16 s cuando cada franja ya estaba resuelta (19,2 veces más rápido). Resultados idénticos (sin contar los tiempos): sí. Casi todo el tiempo de una franja es arrancar el proceso de CBC; la memoria guarda la solución por los datos exactos del problema (límites, demanda, banda, flota, tipologías, pesos y costos) y solo los estados que no dependen del tiempo (óptimo o infactible).

## Lectura

- Una franja no viable sale «no viable» con su motivo; sus cifras son la mejor aproximación ejecutable (respeta flota, ciclo y headway) y se informa qué parte del nivel de servicio cubre.
- Un festivo entre semana (17-nov-2025) usa el ciclo, la flota, el intervalo programado y el factor de carga de domingo o festivo, el mismo tipo de día con el que D5 planea ese día.
- El nivel de servicio usa el P90 calibrado del modelo: con bandas anchas la recomendación se vuelve conservadora, y la sensibilidad a «nivel_servicio» muestra cuánto pesa esa decisión.
- β (valor del tiempo de espera) y α (costo operativo) son los pesos que más mueven la frecuencia; δ ancla la recomendación a la programación vigente sin cruzar el nivel de servicio.
- Los pesos y costos se cambian con PUT /api/v1/thresholds (versión nueva) o por solicitud en POST /api/v1/recommendations/calculate (campo «pesos»).
