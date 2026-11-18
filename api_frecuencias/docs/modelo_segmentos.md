# Modelo de demanda por segmento y sentido

Especificación v1.5: §3.1 «Predicción de demanda: por ruta, sentido, segmento y franja horaria → pronóstico e intervalo
de confianza», §9.1 (pronóstico supervisado por ruta, sentido, segmento y ventana), §9.2 (artefacto verificado y
versionado), §9.3 (partición cronológica, línea base, cuantiles y sesgo) y §7.3 paso 4 (variables por ruta, sentido,
segmento y ventana en un proceso programado).

## Qué pronostica

La fracción de las subidas de la ruta que cae en cada segmento en una hora de salida. El pronóstico de un segmento es
esa fracción por el pronóstico de la ruta (modelo activo de ruta, con su banda calibrada), hora por hora de la ventana
de 30, 60 o 120 minutos; el de un sentido es la suma de sus segmentos. La fracción se normaliza en cada hora, así que
la suma de los segmentos es exactamente el pronóstico de la ruta.

## Modelos registrados

`datos/modelos/segmentos/registro.json`, cada uno con `modelo.joblib` y `manifest.json` (SHA-256 que `cargar()`
verifica antes de usarlo, versión de variables `sv1-2026-11-09`, versión de datos, partición, regla de elección,
métricas, semilla, hiperparámetros y huella del código):

| model_id | Tipo | Estado | Qué hace |
|---|---|---|---|
| `seg_hgb_jerarquico_20230227_s42` | `hgb_jerarquico` | activo | fracción del sentido de un HGB Poisson por hora y sentido × reparto dentro del sentido de un HGB Poisson con exposición T |
| `seg_reparto_fijo_20230227` | `reparto_fijo` | línea base (B0) | fracción histórica por ruta, tipo de día y hora (con respaldo), el reparto que usaba la API |

Variables: ruta, número y posición del segmento en el ciclo, sentido, hora, tipo de día, día de la semana, festivo,
vacaciones, Carnaval, log de la fracción B0 y log de las subidas de su celda. Todas se conocen antes del día
pronosticado; en el entrenamiento la fracción B0 se calcula fuera de pliegue (7 días).

## Cómo se eligió y cuánto acierta

Protocolo fijado antes de mirar la prueba: `docs/evidencias/modelo/segmentos_protocolo.md` (entrenamiento 2023-01-01
a 2023-02-08, validación 2023-02-09 a 2023-02-17, prueba 2023-02-18 a 2023-02-27). Resultados:
`docs/evidencias/modelo/segmentos_modelo.md` y `.json` (WAPE y sesgo por segmento, sentido y ruta; banda P10-P90 con
cobertura medida en la prueba; sesgo por franja, tipo de día y Carnaval, y su composición con el sesgo de la ruta).

## Banda P10-P90

Conformal de Mondrian por tramo de la demanda esperada μ = T · f, puntaje (y − μ)/√(μ + 1), cuantiles 10 % y 90 %
ajustados en la validación, por separado para segmento y sentido, y compuesta en cuadratura con la banda de la ruta:
semiancho = √((f (P50 − P10))² + (q √(μ̂ + 1))²). Si el pronóstico de la ruta es 0 (fuera de servicio), la banda es
[0, 0].

La banda se ajustó con filas de una hora, pero la API la aplica a ventanas de 30, 60 y 120 minutos que pueden cruzar 2
o 3 horas. `scripts/evaluar_banda_ventanas_segmentos.py` mide esa misma regla en ventanas de horas consecutivas de la
prueba (modelos ajustados solo con el entrenamiento, banda de la validación, total real de la ruta;
`docs/evidencias/modelo/segmentos_banda_ventanas.json`). Es un análisis posterior a la prueba, agregado en la revisión:
no cambia la elección ni la banda.

| Ventana | Cobertura por segmento (activo) | Cobertura por sentido (activo) | Por segmento (B0) | Por sentido (B0) |
|---|---|---|---|---|
| 1 hora | 78,31 % | 83,40 % | 78,48 % | 80,75 % |
| 2 horas | 76,75 % | 80,22 % | 76,94 % | 79,67 % |
| 3 horas | 76,02 % | 80,54 % | 76,15 % | 79,37 % |

Por segmento la cobertura baja 1,6 a 2,3 puntos en ventanas de 2 y 3 horas (lo esperable si el error del reparto de
un segmento se repite en horas seguidas); por sentido se mantiene cerca del 80 %. Las ventanas de 30 minutos no se
pueden medir: las subidas por segmento son por hora de salida. En la misma prueba, el IC95 bootstrap por días de la
diferencia de WAPE por segmento y hora del activo frente a B0 es −0,97 pp [−1,60; −0,02].

## Dónde se usa

- `GET /api/v1/predictions/segmentos` (`app/routers/pronostico_segmentos.py`): pronóstico por segmento y por sentido
  con P10 y P90, la fracción del reparto fijo para comparar (`fraccion_reparto`) y la ficha del modelo
  (`modelo_segmentos`: model_id, SHA-256, versión de variables, periodo de datos, cobertura medida). El parámetro
  opcional `modelo_segmentos` elige otra versión registrada (por ejemplo `seg_reparto_fijo_20230227`); un id que no
  está en el registro da 404 `modelo_no_encontrado` y un artefacto alterado, 503 `reparto_no_disponible`.
- Ciclo programado (`app/servicios/monitoreo.py`, `guardar_snapshot`): por cada predicción guarda en
  `ai_frecuencias.feature_snapshot` una fila por segmento con `sentido` y `segmento` llenos (número de segmento,
  fracción B0 y subidas de su celda, fracción prevista, pasajeros, P10 y P90; la hora y el calendario de la ventana
  van en las filas de la ruta). Son 1.158 filas y unos 0,47 MB por ejecución de 9 predicciones
  (`docs/evidencias/monitoreo/foto_segmentos.json`). `FOTO_SEGMENTOS=false` las apaga. Si fallan, solo se omiten
  ellas y las métricas de la ejecución lo dicen en `monitoreo.feature_snapshot_segmentos`: un modelo de segmentos que
  no carga (registro o manifiesto que no son JSON válido incluidos) deja la foto por segmento «omitida», y si la base
  rechaza sus filas se deshace solo su punto de guardado (las de la ruta quedan; estado «fallo»).

## Reentrenar

```
python scripts/preparar_segmentos.py --origen <carpeta de las exportaciones> --solo-celdas   # datos/subidas_segmento_hora.parquet
python scripts/entrenar_segmentos.py --sin-prueba     # entrenamiento y validación, sin mirar la prueba ni guardar
python scripts/entrenar_segmentos.py                  # prueba única, reentreno con los 56 días y registro
python scripts/evaluar_banda_ventanas_segmentos.py    # cobertura de la banda en ventanas de 1, 2 y 3 horas
```

`tests/datos_ml/test_segmentos_modelo.py` comprueba que la partición sea cronológica, que no haya fuga, que el
artefacto pase la verificación y que reentrenar reproduzca la validación registrada. Si cambia el código de
`app/servicios/modelo_segmentos.py`, hay que volver a entrenar (la huella del código está en el manifiesto).

## Límites

- La tabla `timbradas_segmentos` solo trae subidas por segmento del 2023-01-01 al 2023-02-27 (los triggers de
  segmentación no se volvieron a ejecutar), y este modelo se entrenó con ellas: su error en 2025 no está medido.
- El 17-11-2026 se reconstruyeron las subidas por segmento de 2023 a 2025 aplicando la misma regla a los eventos de
  conteo, y con ese panel se entrenó y se probó aparte el pronóstico por segmento a 30, 60 y 120 minutos
  (`../../pronostico_corto_plazo/README.md`). Reentrenar este modelo con el panel es el primer pendiente de
  `../../PLAN_EVOLUCION.md` (sección 7).
- El sentido es una aproximación geométrica (supuesto S9): mitad de la longitud acumulada del ciclo.
- No hay pronósticos fuera de muestra del modelo de ruta activo para 2023: la cobertura de punta a punta se midió con
  B2 (la misma hora de la semana anterior) y, como análisis adicional, con errores reales del modelo de ruta de 2025.
