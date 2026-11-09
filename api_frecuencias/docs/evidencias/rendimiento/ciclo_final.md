# Ciclo diario final: la foto de la respuesta reutiliza el plan del día y la ruptura corre en producción

Medido el 2026-11-09 a las 07:29 con `scripts/medir_ciclo.py`, con la misma secuencia y los mismos cortes de `ciclo_dimensiones_plan.md`: carga inicial hasta el 30-08-2025, día nuevo 31-08 y repetición. Corrió en una base local desechable y sobre una copia temporal de `datos/`. El JSON completo, con el resultado normalizado y su SHA-256, está en `ciclo_final.json`. El equipo estaba compartido con otros procesos, así que las cifras absolutas tienen ruido.

Hay tres cambios frente a la medición anterior:

1. **La foto de la respuesta del reto ya no vuelve a resolver el plan.** El cierre del ciclo calcula el plan del día siguiente por ruta con `optimizacion.plan_dia` y lo persiste como filas `origen = 'plan_dia'`. Luego le pasa esos mismos planes a `respuesta.precalcular(..., planes=...)`, que los usa tal cual cuando son del mismo modelo activo y de la misma versión de umbrales. Las rutas sin plan se calculan con la misma llamada del ciclo, con `model_id`, que aprovecha su memoria. Así `GET /respuesta` y `GET /recommendations/plan` dicen las mismas salidas hora por hora. La prueba es `tests/unit/test_respuesta.py::test_la_foto_reutiliza_el_plan_que_el_ciclo_acaba_de_calcular`.
2. **RF-009 en producción.** `contexto_observado` agrega la serie diaria de la ruptura de comportamiento: 56 días completos, lo real frente al pronóstico del modelo activo. La regla CUSUM de `alertas.py` ya se evalúa en cada ciclo. La serie se guarda en memoria por ruta, día, modelo, días nuevos y huella de lo observado en la ventana.
3. **Umbrales versionados (migración 0007).** Las claves de la ALT-002 observada y de la ruptura pasan a `threshold_config`, que queda en la versión 5 de esta base.

## Duración por corrida (segundos de la petición)

| Corrida | Filas leídas | Sin plan (`ciclo_antes_despues`) | Con plan y foto (`ciclo_dimensiones_plan`) | **Final** |
|---|---:|---:|---:|---:|
| carga_inicial | 49.623 | 27,7 | 103,4 | **24,1** |
| dia_nuevo | 51 | 7,9 | 50,9 | **21,4** |
| repeticion | 0 | 0,1 | 0,2 | **0,1** |

## Duración por etapa (con plan y foto → final, segundos)

| Corrida | lectura_incremental | calidad | prediccion | alertas | notificaciones | plan_dia (plan + foto) |
|---|---:|---:|---:|---:|---:|---:|
| carga_inicial | 0,3 → 0,2 | 13,1 → 4,3 | 21,3 → 1,2 | 1,8 → 16,3 | 0,0 → 0,0 | **66,8 → 2,0** |
| dia_nuevo | 0,1 → 0,1 | 6,7 → 1,0 | 7,3 → 1,0 | 6,0 → 17,2 | 0,0 → 0,0 | **30,7 → 2,2** |
| repeticion | 0,0 → 0,0 | 0,1 → 0,1 | — | — | — | — |

## Lectura

- **Plan y foto: de 66,8 s a 2,0 s en la carga inicial y de 30,7 s a 2,2 s en el día nuevo.** Antes, la foto volvía a pronosticar cada hora y resolvía el MILP de D5 por su cuenta, con un pronóstico redondeado que no coincidía con la memoria del plan. Ahora la etapa resuelve el MILP una sola vez por ruta y la foto solo arma la respuesta.
- **El costo de RF-009 es de 5,2 a 5,9 s por ruta, unos 16 s por ciclo para las tres rutas.** Cada serie pronostica 56 días × 17 horas en un solo lote (`inferencia.predecir_horas`). Los tiempos por ruta salen del registro del ciclo («serie diaria de … en x s») y quedan además en el histograma Prometheus `api_serie_diaria_segundos{memoria="no|si"}`. Si se repite un día con los mismos datos, la serie sale de la memoria. La etapa de alertas pasa así de 1,8 a 16,3 s y de 6,0 a 17,2 s, y esta medición ya detecta una ruptura de comportamiento: ALT-007, variante `ruptura_comportamiento`, en SILENCIO.
- Las etapas de calidad y predicción bajan respecto de la medición anterior, que se tomó con el equipo más cargado. El código de esas etapas no cambió aquí.
- **El ciclo completo sigue muy por debajo de la medición anterior**: 24,1 s frente a 103,4 s en la carga inicial y 21,4 s frente a 50,9 s en el día nuevo. Todo corre en la cola, en segundo plano (§7.1), y los GET solo leen lo guardado.

## Los resultados no cambian

- **Predicciones:** el SHA-256 del resultado normalizado es idéntico al de `ciclo_dimensiones_plan.json` (`879d8ab2…e90601`).
- **Recomendaciones:** las 120 filas (18 de franja y 102 horas del plan del día) tienen los mismos valores. La única diferencia es la etiqueta de la versión de umbrales, que pasa de «threshold_config v4» a «v5» porque la migración 0007 crea una versión nueva del conjunto con los mismos valores para las claves que ya existían.
- **Alertas:** las 13 de antes más 1 nueva, la ruptura de comportamiento (RF-009), que antes no se evaluaba en el ciclo.
- **SHA-256 total del resultado:** `589dabf4638da39bb500a0e5691320254baf887bdc1802a198a93fffc104e763`.

Reproducir: `TEST_DATABASE_NAME=<base local desechable> python scripts/medir_ciclo.py --etiqueta final_plan_reutilizado --salida docs/evidencias/rendimiento/ciclo_final.json`.
