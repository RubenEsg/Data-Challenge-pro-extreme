# Ciclo diario con dimensiones de §8.3, plan del día siguiente y foto de la respuesta

Medido el 2026-11-09T06:40:05 con `scripts/medir_ciclo.py` (misma secuencia y cortes que `ciclo_antes_despues.md`: carga inicial hasta el 30-08-2025, día nuevo 31-08 y repetición), en una base local desechable y una copia temporal de `datos/`. El equipo estaba compartido con otros procesos, así que las cifras absolutas tienen ruido; lo que importa es en qué etapa se va el tiempo.

Desde esta versión, cada ejecución con datos nuevos además:

- guarda en cada predicción, recomendación, alerta y fila del histórico las dimensiones de §8.3 (idruta, idempresa, idproceso, día ISO y estacionalidad);
- valida el lote con los catálogos y el reloj de la ejecución y guarda la llave, el valor y si el error bloquea;
- arma las variables con la serie validada (lo que llegó en la ejecución incluido, RF-013);
- pronostica en lote las horas cerradas de las alertas observadas;
- calcula y guarda el plan del día siguiente por ruta y hora con el modelo activo (17 horas por ruta, `recommendation.origen = 'plan_dia'`) y la foto de la respuesta del reto (`respuesta_reto`), en la misma transacción.

## Duración por corrida (segundos de la petición)

| Corrida | Filas leídas | Antes (sin plan) | Ahora | Plan del día | Respuesta |
|---|---:|---:|---:|---:|---:|
| carga_inicial | 49623 | 27,7 | 103,4 | 5,0 | 61,2 |
| dia_nuevo | 51 | 7,9 | 50,9 | 13,6 | 16,6 |
| repeticion | 0 | 0,1 | 0,2 | — | — |

## Duración por etapa (antes → ahora, segundos)

| Corrida | lectura_incremental | calidad | prediccion | alertas | notificaciones | plan_dia |
|---|---:|---:|---:|---:|---:|---:|
| carga_inicial | 0,4 → 0,3 | 7,6 → 13,1 | 5,4 → 21,3 | 14,0 → 1,8 | 0,2 → 0,0 | — → 66,8 |
| dia_nuevo | 0,1 → 0,1 | 0,9 → 6,7 | 1,3 → 7,3 | 5,5 → 6,0 | 0,2 → 0,0 | — → 30,7 |
| repeticion | 0,0 → 0,0 | 0,0 → 0,1 | — → — | — → — | — → — | — → — |

«Antes» es la corrida «después» de `ciclo_antes_despues.json` (el ciclo sin plan del día). La etapa «calidad» incluye también la evaluación del error y el monitoreo, que ahora leen la serie validada. La etapa «plan_dia» es la suma del plan del día y de la foto de la respuesta; su reparto sale de `execution_log.metricas` de la misma corrida (`ciclo_dimensiones_plan_cierre.json`).

## Lectura

- La etapa de alertas baja porque las horas cerradas se pronostican en un solo lote (`inferencia.predecir_horas`).
- El plan del día de las tres rutas (MILP de D5 con el pronóstico horario del modelo activo) toma entre 5 y 14 s. La foto de la respuesta toma entre 17 y 61 s porque vuelve a pronosticar cada hora y a resolver el plan por su cuenta; reutilizar el plan que el ciclo acaba de guardar es la mejora pendiente más rentable. Las dos corren en la cola, en segundo plano (§7.1): no bloquean ninguna petición HTTP, y `GET /respuesta` y `GET /recommendations/plan` solo leen lo guardado.
- Evaluación, monitoreo y predicción tardan más porque usan la serie validada (Parquet empaquetado con `demanda_observada` encima) en lugar de solo el Parquet: es el costo de cumplir RF-013.
- La repetición sin datos nuevos no recalcula nada (0 filas, sin plan).

Conteos del resultado de las tres corridas: 18 predicciones, 120 recomendaciones (18 de franja y 102 horas del plan del día: 17 horas × 3 rutas × 2 días), 13 alertas y 13 entradas de bitácora. SHA-256 del resultado normalizado: `29ed1cee1fb73f079824308ff53ed5a14110130d5f797e1c901a6a0deb4ede98`, distinto del de `ciclo_antes_despues.json` porque ahora también hay filas del plan del día y columnas nuevas.

Cada corrida con datos nuevos dejó 51 filas `plan_dia` y 3 fotos en `respuesta_reto`, todas con el modelo `hgb_fv2_20250831_s42`, la calibración `v2` y `fuente_pronostico = modelo_activo` (`ciclo_dimensiones_plan_cierre.json`).

Reproducir: `TEST_DATABASE_NAME=<base local desechable> python scripts/medir_ciclo.py --etiqueta dimensiones_y_plan_del_dia --salida docs/evidencias/rendimiento/ciclo_dimensiones_plan.json`.

> **Actualización.** La mejora pendiente de la foto de la respuesta (reutilizar el plan que el ciclo acaba de guardar) ya está aplicada: el plan y la foto bajan de 66,8 a 2,0 s en la carga inicial y de 30,7 a 2,2 s en el día nuevo, con los mismos resultados. Las cifras vigentes están en `ciclo_final.md` y `ciclo_final.json`.
