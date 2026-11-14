# Evidencias de optimización (§5.1, §10.1-§10.3, RF-007, RF-008, RF-015, §12.3, §18)

| Archivo | Qué muestra | Cómo se regenera |
|---|---|---|
| `viabilidad.md` · `viabilidad.json` | Viabilidad de la recomendación por ruta, hora y tipo de día en 2025 con la condición que la impide (reparto de la flota por tipología, banda P90, ciclo mediano, headway mínimo). Parte A: la franja de las 6 h del ciclo diario (15-sep a 31-dic de 2025, 324 franjas), que explica el 46,0 % viable del backtest de alertas. Parte B: todas las horas de servicio de cuatro semanas representativas, para la franja de §10.2 y para el plan del día; al final, la hora pico de CRA 54 (H13) | `.venv\Scripts\python scripts/viabilidad.py` |
| `sensibilidad.md` · `sensibilidad.json` | Formulación de §10.2 y 13 franjas reales (3 rutas; laboral y sábado; pico y valle; y el lunes festivo 17-nov-2025, comparado con la programación de domingo o festivo): recomendación del MILP, límites que mandan, las dos líneas base de §10.3 (literal y ajustada), sobreoferta, frecuencia programada, 23 variaciones de un parámetro a la vez y verificación MILP = enumeración exacta. Al final, el tiempo de 51 franjas de un día en frío y con la memoria de soluciones del MILP | `.venv\Scripts\python scripts/sensibilidad.py` |
| `ejemplo_calculate.json` | `POST /recommendations/calculate` viable: pesos con su fuente, restricciones activas (con la fila informativa de ocupación objetivo mínima), asignación por tipología, las dos líneas base de §10.3 con su nombre, headway máximo efectivo, comparación con la frecuencia programada y explicación | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_recomendaciones.py` |
| `ejemplo_calculate_no_viable.json` | Franja inviable: `viable = false`, motivo con cifras y mejor aproximación ejecutable rotulada (respeta flota y headway; dice qué parte del nivel de servicio cubre) | ídem |
| `pesos_versionados.json` | `PUT /thresholds` con β y el nivel de servicio crea una versión; la recomendación la usa (`threshold_config vN`) y cambia; la solicitud puede probar otros pesos | ídem |
| `ejemplo_escenario_y_sensibilidad.json` | RF-008 «qué pasa si» (demanda × 1,3 y β = 3) y la sensibilidad completa en la respuesta | ídem |
| `ejemplo_plan_d5.json` | `GET /recommendations/plan` leído de las filas `origen = 'plan_dia'`: plan del día con el modelo activo (P10/P50/P90 por hora), salidas, despachos, headway, vehículos, límites activos, demanda de diseño, margen, viabilidad, sobreoferta, costo y comparación con lo programado | ídem |
| `ejemplo_prediccion_12_3.json` | `POST /predictions/run` con las claves del ejemplo de §12.3 (más `viable` y `reason` en `recommendation`) y la franja horaria que se recomendó | ídem |
| `ejemplo_prediccion_12_3_no_viable.json` | La misma petición con una franja inviable: el bloque §12.3 dice `viable = false` con el motivo y no muestra cifras; la mejor aproximación queda rotulada en la recomendación | ídem |
| `pytest_optimizacion.txt` | Corrida final de las pruebas de esta área | ver el encabezado del archivo |

Las pruebas escriben la evidencia con `tests/evidencia.guardar_evidencia`: solo con `GENERAR_EVIDENCIAS=1` va a esta
carpeta; sin la variable (la suite, el CI o un jurado que corre las pruebas) va a un directorio temporal y el
repositorio no cambia.

Reglas que fijan las pruebas (`tests/unit/test_optimizacion*.py` y `tests/integracion/test_recomendaciones.py`):

- **Plan del día con el modelo activo (§10.1-§10.3).** `optimizacion.plan_dia` resuelve el MILP de D5 (sin cambios en
  `motor_d5`) con el pronóstico P10/P50/P90 de cada hora del modelo activo (h = 60 al inicio de la hora, sin factor
  intradía) para cualquier fecha con variables, también de 2026; el pronóstico E12 de 2025 queda como opción de
  laboratorio. Cada hora trae los límites que mandan, la demanda de diseño, el margen (una salida menos o más), la
  viabilidad con su motivo y la sobreoferta (`test_plan_dia_usa_el_pronostico_horario_del_modelo_activo`,
  `test_plan_dia_explica_cada_hora`).
- **Parámetros gobernados (§5.1 «regla de gobierno»).** El headway mínimo y el máximo efectivo son las cotas de cada
  hora del MILP (nmin = ceil(minutos / headway máximo), tope = floor(minutos / headway mínimo)); los costos y los pesos
  α, β, γ salen de `threshold_config` y cada parámetro dice su fuente; un cambio de umbrales cambia el plan
  (`test_plan_dia_toma_los_umbrales_gobernados_como_cotas_del_milp`). La tarifa, la elasticidad y la suavidad del MILP
  también salen de `threshold_config` (migración 0010), y la flota, el ciclo y la capacidad, del ajuste local
  versionado si existe. Sin una versión nueva, el plan es el de D5
  (`tests/unit/test_gobierno_parametros.py::test_sin_version_nueva_el_milp_recibe_exactamente_los_parametros_de_d5`,
  `tests/unit/test_gobierno_parametros.py::test_la_flota_y_el_ciclo_gobernados_cambian_el_plan_del_dia`). Cada hora
  compara además su headway con `rutas.frecuenciadespachos` (`frecuenciadespachos_min`,
  `diferencia_frecuenciadespachos_min`); la evidencia de estas reglas está en `../gobierno/`.
- **Sin solución, no hay plan.** Si con la suavidad gobernada el MILP del día no tiene solución, `plan_dia` lanza un
  ValueError que nombra los parámetros que hay que revisar, y no se entrega ni se persiste un plan infactible
  (`tests/unit/test_gobierno_parametros.py::test_una_suavidad_gobernada_sin_solucion_no_entrega_un_plan`).
- **Una sola salida no tiene intervalo.** En una hora operada menos minutos que el headway mínimo (SILENCIO a las 4 h
  del domingo y del festivo: 0,2 min), el tope es 1 salida. Sin intervalo entre salidas no hay headway que verificar,
  así que la hora no es no viable por eso (`sin_intervalo = true`). Es la misma regla de la respuesta del reto. Con
  esta regla, en `viabilidad.md` las horas del plan de SILENCIO en domingo y festivo pasan de 94,1 % a 100 % viables
  (`test_una_sola_salida_no_tiene_intervalo_y_no_es_no_viable`).
- **Vehículos (§10.3) con su definición.** Cada hora pide ceil(ciclo / headway) vehículos, con headway = 60 / salidas
  por hora. En una hora completa es la fórmula literal. En una hora de apertura o cierre ya no da cientos de vehículos
  para una sola salida: antes daba 501 en SILENCIO a las 4 h del domingo. El plan trae dos cifras, y
  `definicion_vehiculos` dice qué mide cada una:
  - `vehiculos_hora_pico`, el máximo por hora de esa fórmula;
  - `buses_en_ruta_pico`, el máximo de buses en ruta a la vez (conteo de D5 cada 15 min), el que limita la flota del
    MILP y el que usa la respuesta del reto.

  En `ejemplo_plan_d5.json` (CRA 54, 19-nov-2025), la fórmula de régimen da 106 en la hora pico y en ruta hay como
  máximo 78,55 buses, de 79 disponibles (`test_vehiculos_con_el_ritmo_de_la_hora_y_su_definicion`).
- **El plan persistido muestra programadas, flota y costo.** Cada hora del plan lleva la flota del día y su costo. Así,
  `GET /recommendations/plan` rehace, desde las filas que guarda el ciclo diario, las salidas programadas, la flota, el
  costo del día y sus componentes (`test_plan_del_dia_con_las_filas_del_ciclo_trae_programadas_flota_y_costo`).
- **Espera máxima con efecto (supuesto S12).** Headway máximo efectivo = min(`headway_maximo_min`, 2 × `espera_max_min`),
  en la franja y en el plan: bajar la espera de 5 a 3 min baja el headway máximo de 10 a 6 min y sube la recomendación
  (`test_bajar_la_espera_maxima_cambia_la_recomendacion_de_franja`, `test_bajar_la_espera_maxima_cambia_el_plan`,
  `test_espera_maxima_gobernada_cambia_la_recomendacion` por HTTP).
- **Ocupación objetivo mínima (65 %).** Una recomendación con ocupación esperada menor sale con `sobreoferta = true` y
  su motivo, en la franja y en cada hora del plan; es informativa, no hace inviable la recomendación
  (`test_sobreoferta_en_la_franja`, `test_plan_dia_marca_sobreoferta_con_su_motivo`).
- **Líneas base de §10.3.** La literal (ceil(demanda puntual / capacidad efectiva), factor 1) y la ajustada (carga
  crítica = factor de carga × P90) van juntas, cada una con su nombre
  (`test_lineas_base_literal_y_ajustada_con_su_nombre`).
- **Recomendación inviable (§10.3 y §18).** El bloque §12.3 de `POST /predictions/run` no presenta la aproximación
  como recomendación (`test_predictions_run_con_franja_inviable_no_presenta_la_aproximacion`).
- **El GET no resuelve el MILP (§7.1).** `GET /recommendations/plan` lee lo que persistió el ciclo; si no hay, 404
  «sin_calcular» con la pista `POST /api/v1/respuesta/calcular`
  (`test_plan_del_dia_se_lee_de_lo_persistido_con_cada_rol`).
- **Headway mínimo gobernado en el plan del laboratorio.** `resumen_plan_d5` (E12 de 2025) conserva el tope: el
  19-nov-2025 a las 5 h, CRA 54 pedía 34 salidas (una cada 1,76 min) y el plan programa 30 (2,00 min)
  (`test_plan_d5_respeta_el_headway_minimo_gobernado`).
- **Festivos entre semana.** La programación de comparación, el contexto de la franja y el factor de carga usan el tipo
  de día «Domingo/festivo» en un festivo entre semana
  (`test_festivo_entre_semana_usa_la_programacion_de_domingo_o_festivo`).

Fuentes de datos: pronóstico y banda P10-P90 calibrada del modelo activo; ciclo, flota e intervalo programado por ruta,
tipo de día y hora (`datos/parametros_operativos_hora.parquet`, o el ajuste local de `PUT /api/v1/catalogos/flota` para
la flota y el ciclo); headway vigente de `rutas.frecuenciadespachos` (`datos/catalogo_rutas.json`, leído en minutos,
supuesto S14); minutos operados, km, CV de los intervalos y tasa de
viajes no válidos del plan (mediana 2025 de `datos/insumos_d5_2025.parquet`); factor de carga crítica por ruta, tipo de
día y hora (misma fuente); tipologías de capacidad de `app/servicios/tipologias_flota.json`; costos con fuente de
`datos/costos_fuente.json`. Ninguna corrida escribe en `datos/`.
