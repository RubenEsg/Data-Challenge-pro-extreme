# Modelo de demanda: resumen para el jurado

Responde a §9 (inteligencia artificial y analítica), §14.1 «Datos/ML», §14.2 «el modelo supera la línea base» y al
criterio «Modelo predictivo: mejora sobre la línea base, error, robustez e incertidumbre» de §16. Cada cifra sale de un
archivo de evidencia del repositorio, citado al lado; ninguna se escribió a mano.

**Modelo activo:** `hgb_fv2_20250831_s42`, HistGradientBoostingRegressor con pérdida Poisson para el pronóstico puntual
y dos modelos de cuantiles (P10 y P90). Variables `fv2-2026-11-09`, corte de datos 2025-08-31, semilla 42, artefacto
`modelo.joblib` con SHA-256 `24c70b9c…` y exportación ONNX de las tres salidas
(`datos/modelos/hgb_fv2_20250831_s42/manifest.json`, `datos/modelos/registro.json`).

## 1. Protocolo sin fuga (§9.3)

| Partición | Fechas | Uso |
|---|---|---|
| Entrenamiento | 2023-01-08 a 2025-08-31 | ajustar el modelo |
| Validación | 2025-09-01 a 2025-10-31 (61 días) | elegir y activar el modelo, el peso del factor intradía y la calibración de la banda |
| Prueba reservada | 2025-11-01 a 2025-12-31 (3.111 horas-ruta) | reportar (informativa: ver abajo) |

Fuente: `manifest.json`, clave `particion`. La división es cronológica y sin solape, y ningún parámetro del modelo ni
de la banda se ajustó con la prueba reservada. **Pero la prueba no está intacta:** el entrenamiento de fv1 la midió
(WAPE 15,07 %) y fv2 se comparó con fv1 con esa cifra a la vista, así que se consultó al elegir entre los dos
(`decision_fv2.md`, «La prueba reservada: informativa, no intacta»). El criterio de selección es la validación más los
backtests congelados de 2024 y 2025 (sección 5). Desde ahora `inferencia.entrenar()` y la compuerta de
`scripts/entrenar.py` solo miden la validación; el informe de la prueba lo escribe únicamente `scripts/evaluar_modelo.py`.
Para una prueba limpia se pide a Extreme un periodo de 2026 que el equipo no haya visto.

Entrenar dos veces con la misma semilla da el mismo SHA-256 (`entrenamiento_fv2.json`,
`reproducibilidad.identico = true`). El manifiesto guarda el SHA-256 del código con fin de línea LF (igual en Windows
y Linux), el mismo sin el docstring del módulo y el commit de git (`codigo_sha256`, `codigo_sin_docstring_sha256`,
`codigo_commit`, `codigo_verificacion`; `scripts/evaluar_codigo_modelo.py`): el `variables.py` del entrenamiento es el
del commit `5f2d4b5` en adelante y coincide con el actual; el `inferencia.py` de ese momento no quedó en un commit, y
su equivalencia se comprueba reentrenando (mismo SHA-256 del artefacto). El estado del modelo (activo, candidato) no
va en el manifiesto: la fuente de verdad es `registro.json` y la tabla `model_registry`.

## 2. Mejora sobre las líneas base (§9.1, §14.2)

Prueba reservada, mismas 3.111 filas para todos (`evaluacion_modelo.md`; IC95 por bootstrap de bloques de 7 días,
B = 2.000, semilla 42):

| Modelo | MAE | RMSE | WAPE % | IC95 WAPE | sMAPE % | Sesgo % |
|---|---|---|---|---|---|---|
| **Activo (fv2)** | **96,27** | **140,86** | **14,77** | **13,10–16,87** | **22,23** | **2,75** |
| fv1 (versión anterior) | 98,20 | 146,02 | 15,07 | 13,22–17,43 | 22,44 | 2,54 |
| B1: regla manual de Sobusa (media de 8 semanas) | 138,06 | 225,99 | 21,18 | 16,61–26,79 | 26,28 | 5,85 |
| B2: misma hora hace 7 días | 172,05 | 279,22 | 26,40 | 22,77–30,57 | 33,72 | 3,84 |

- Activo menos B1: −10,43 a −3,21 puntos de WAPE (IC95), P(mejora) = 1,00. Activo menos fv1: −0,64 a −0,04 puntos,
  P(mejora) = 0,99 (`evaluacion_modelo.md`).
- En validación, el activo tuvo WAPE 13,554 frente a 15,117 de B1 y 13,632 de fv1; la compuerta lo activó con esos
  números (`entrenamiento_fv2.json`, `compuerta`).
- La mejora sobre B1 no depende de la elección entre fv1 y fv2: fv1 también la tiene (−9,88 a −3,06 puntos) y los
  modelos congelados de 2024 y 2025 también (sección 5). La diferencia entre fv2 y fv1 en la prueba no se usa como
  argumento, porque esa comparación influyó en la elección.
- Estas cifras son del modelo de la API. Las del informe académico (experimento 11, LightGBM, 13,94 %, y experimento
  12, híbrido con Chronos-2, 13,62 %) son de otro protocolo: pronóstico a 7 días sobre todo 2025 con validación mensual
  expansiva, frente a nov–dic de 2025 con un solo corte aquí; por eso no se comparan número a número.

## 3. Error por ruta, franja, pico y condición (§9.3)

Prueba reservada (`evaluacion_modelo.md` y `evaluacion_modelo.json`):

| Ruta | WAPE activo | WAPE B1 | MAE activo | Sesgo activo |
|---|---|---|---|---|
| CL 72 | 19,23 | 25,27 | 67,45 | +3,15 % |
| CRA 54 | 13,04 | 19,79 | 140,47 | +3,01 % |
| SILENCIO | 15,33 | 21,30 | 80,90 | +1,96 % |

| Franja | WAPE activo | Sesgo activo | WAPE B1 |
|---|---|---|---|
| 04-05 | 10,65 | 2,08 | 24,94 |
| 06-08 pico | 10,79 | 0,79 | 16,92 |
| 09-16 valle | 15,45 | 2,63 | 20,78 |
| 17-19 pico | 22,65 | 8,34 | 25,01 |
| 20 | 34,68 | 5,27 | 42,47 |
| Pico (6-8 y 17-19 h) | 14,38 | 3,08 | 19,37 |
| Valle | 14,97 | 2,59 | 22,11 |

Por condición operacional (WAPE activo frente a B1): laboral 14,38 frente a 17,89; sábado 13,71 frente a 14,16;
domingo o festivo 18,61 frente a 50,89; festivo 21,11 frente a 145,99; vacaciones 19,87 frente a 32,01; lluvia de 5 mm
o más 14,87 frente a 24,73. Donde más falla: víspera de festivo (WAPE 30,28, sesgo +17,54 %) y Navidad (29,80, solo
51 horas). El sesgo por ruta y condición está en `evaluacion_modelo.json`, clave `prueba_reservada.sesgo_ruta_condicion`.

**Limitación de §9.3 por sentido y segmento.** El modelo pronostica por ruta y hora. El pronóstico por sentido y
segmento (`GET /predictions/segmentos`) reparte el de la ruta con las fracciones observadas del 2023-01-01 al
2023-02-27 (58 días). Lo que se midió es solo el error del reparto: las fracciones de enero aplicadas al total REAL de
febrero de 2023 dan un WAPE por segmento y hora de 40,96 % y por sentido y hora de 7,9 a 9,4 % según la ruta
(`docs/evidencias/monitoreo/desagregacion_segmentos.json`). No se midió el sesgo del pronóstico por sentido ni por
segmento, ni si esas fracciones siguen valiendo en 2025; el sentido es una aproximación geométrica (mitad de la
longitud del ciclo), porque las exportaciones no lo traen. Con subidas por segmento recientes se puede medir el error
combinado (pronóstico × reparto) con la misma función de evaluación.

## 4. Horizontes de 30, 60 y 120 minutos

Origen móvil en cada hora en punto de 6 a 20 h, con un fv2 congelado con datos hasta 2024-12-31, el peso del factor
intradía calibrado en enero y febrero de 2025 (0,3) y evaluación de marzo a diciembre de 2025 (`horizontes.json`):

| Horizonte | n | WAPE modelo | WAPE con factor intradía | WAPE B1 |
|---|---|---|---|---|
| 30 min (reparto con el perfil intrahorario) | 13.212 | 19,43 | 19,43 | 23,12 |
| 60 min | 13.770 | 14,80 | 14,71 | 18,96 |
| 120 min | 12.852 | 10,94 | 10,87 | 15,44 |

El objetivo de 30 minutos es una aproximación: las exportaciones no traen el conteo por minuto y se usa la fracción
observada de subidas de los viajes que salen entre h:00 y h:29 (`horizontes.json`, `h30.nota`).

## 5. Robustez por periodo

Modelos congelados un año antes de cada periodo evaluado, misma semilla (`evaluacion_modelo.md`, sección «Robustez»):

| Año evaluado | Entrenado hasta | WAPE fv2 [IC95] | WAPE B1 | CL 72 / CRA 54 / SILENCIO (fv2) | Cobertura P10-P90: modelo → calibrada |
|---|---|---|---|---|---|
| 2024 | 2023-12-31 | 16,26 [14,97–17,91] | 21,55 | 20,67 / 13,98 / 17,99 | 67,67 % → 79,37 % |
| 2025 | 2024-12-31 | 14,48 [13,78–15,28] | 20,04 | 19,35 / 12,12 / 16,15 | 78,51 % → 80,12 % |
| 2025 nov-dic (activo) | 2025-08-31 | 14,77 [13,10–16,87] | 21,18 | 19,23 / 13,04 / 15,33 | 79,49 % → 77,82 % (v2) |

2023 no se puede evaluar fuera de muestra: es el primer año de la serie (el entrenamiento empieza el 2023-01-08) y no
hay datos anteriores para entrenar un modelo que lo pronostique. En los dos años evaluables el modelo supera a B1 en
las tres rutas, y la calibración conformal lleva la cobertura de 2024 de 67,67 % a 79,37 %.

## 6. Incertidumbre: banda P10-P90 y calibración conformal (§9.3, §9.4)

Prueba reservada, las mismas 3.111 horas-ruta (`evaluacion_modelo.md`, «Cobertura P10-P90»; el mismo resumen queda en
`manifest.json`, clave `evaluacion.prueba_reservada.cobertura` y `calibracion_vigente`):

| Banda | Cobertura | Bajo P10 | Sobre P90 | Ancho medio (pasajeros por hora) |
|---|---|---|---|---|
| Del modelo, sin calibrar | 79,49 % | 12,18 % | 8,33 % | 318,9 |
| Calibración v1 (conformal móvil por ruta, 56 días previos) | 77,88 % | 13,28 % | 8,84 % | 312,9 |
| **Calibración v2, la vigente** (la que la API aplica a cada predicción) | **77,82 %** | **12,95 %** | **9,23 %** | **303,4** |

Con la calibración vigente, la cobertura por ruta es CL 72 78,40 %, CRA 54 73,67 % y SILENCIO 81,39 %.

- **Calibración v2, la vigente** (conformal de Mondrian con un cuantil por bloque horario, ajustado solo con la
  validación; `calibracion_condicional.md` y `.json`):
  - se eligió con validación cruzada por semanas dentro de la validación: la peor desviación de la cobertura frente al
    80 % en los grupos por hora, ruta y tipo de día baja de 10,60 a 4,15 puntos y el ancho medio pasa de 322 a 319
    pasajeros por hora. La hora 4 (inicio del servicio) era el peor grupo de v1, con 69,4 %;
  - en la prueba reservada, que solo se reporta: cobertura global 77,82 % (v1 77,88 %) con un intervalo medio más
    angosto (312,9 → 303,4 pasajeros) y la hora 4 sube de 66,7 % a 84,2 %. La peor desviación no mejora (13,33 → 14,97
    puntos): las horas 18-20 y los días especiales de noviembre y diciembre quedan bajo el 80 % con cualquier banda,
    también la del modelo (20 h: 68,8 %). Es un cambio de temporada que ninguna calibración ajustada en septiembre y
    octubre puede anticipar; el monitoreo de §9.4 mide la cobertura móvil y la política de reentrenamiento la usa.
- **Versionada y verificable:** `datos/modelos/hgb_fv2_20250831_s42/calibracion_v2.json`, con su SHA-256 en
  `manifest.json` (clave `calibracion`). La API la carga una vez, verifica el hash y la aplica después del modelo, igual
  con `MOTOR_INFERENCIA=sklearn` u `onnx`; el artefacto y los ONNX no cambian. Cada predicción dice qué versión produjo
  su banda (`calibracion_version` y `variables.conformal`). La calibración no cambia el pronóstico puntual ni el WAPE
  (`tests/unit/test_calibracion.py`, `tests/datos_ml/test_no_regresion.py`).
- **El caso de las 6 h en CRA 54:** la banda horaria es angosta (P90/P50 mediano 1,16 en validación y 1,15 en la
  prueba; máximo 1,61 el 25 de diciembre). La variación real entre días sí es grande (1.988 ± 624 pasajeros a las 6 h
  en validación), pero el modelo la explica con el tipo de día, el calendario y los rezagos. Una razón P90/P50 de 2,9
  o más no aparece a las 6 h en ninguna ruta: solo en 23 horas de la validación y 49 de la prueba, todas de borde
  (4, 5 y 20 h) y con un P50 mediano de unos 14 pasajeros (`calibracion_condicional.md`, «El caso de las 6 h»). La inviabilidad de los picos en la recomendación viene de la flota y del ciclo (por ejemplo,
  SILENCIO a las 6 h del 16-10-2025: 45 vehículos con un ciclo de 266,9 min sostienen 350 pasajeros/h de capacidad
  efectiva frente a una carga de 493 en el nivel de servicio, 71,1 % de cobertura; `ciclo_recomendacion_franja.json`,
  `despues.motivos_por_ruta_y_dia`), no del ancho de la banda.

### 6.1 El retador se compara igual con igual (§9.5, RF-018, RF-019)

- **Cada candidato entrenado trae su propia calibración.** `inferencia.entrenar` (lo usan `POST /models/train`, el
  reentrenamiento que dispara la política en el ciclo diario y `scripts/entrenar.py`) ajusta, con la validación de ESE
  candidato (los 61 días posteriores a su corte), la calibración por grupo con el mismo esquema de grupos que la del
  activo (hoy, bloque horario). La guarda como `calibracion_v2.json` junto a su `modelo.joblib`, con su SHA-256 en su
  `manifest.json` (clave `calibracion`); el artefacto y sus hashes no cambian. El ajuste y la escritura son las mismas
  funciones que usa `scripts/calibrar_por_grupo.py` (`inferencia.ajustar_calibracion_grupo`,
  `calibracion_de_validacion` y `escribir_calibracion`): con el modelo activo, el script reproduce exactamente los
  cuantiles versionados en su `calibracion_v2.json`.
- **La sombra y la compuerta usan esa banda.** En la sombra, el retador predice con su calibración (cada predicción
  dice `calibracion_version`); la compuerta (`politica.compuerta`) evalúa a cada modelo con su propia banda calibrada y
  registra cuál midió en cada uno (`calibracion: {candidato, activo, misma_version}`), junto a la cobertura v1 como
  referencia (`cobertura_p10_p90_conformal_v1`). La sombra también guarda el archivo y el SHA-256 de la calibración del
  retador (`metricas.sombra.calibracion`).
- **El análisis se puede repetir para cualquier modelo:** `python scripts/calibrar_por_grupo.py --model-id <id>`. Con
  el modelo fv1 (`calibracion_condicional_hgb_fv1_20250831_s42.md`), la validación cruzada adopta Mondrian por ruta ×
  bloque y, en la prueba reservada (solo reporte), la cobertura pasa de 78,59 % (v1) a 79,78 % con un ancho medio de
  316,3 → 315,1 pasajeros; sin `--escribir`, sus archivos no cambian.
- **La política mide la antigüedad en un solo reloj.** `GET /monitoring/policy` cuenta los días de datos nuevos entre
  el último día de datos que vio un modelo (fin de su serie o corte + 61 días) y la última marca de agua, ambos en
  fechas de America/Bogota. Si un modelo ya vio datos posteriores (el activo validó hasta el 2025-10-31), el resultado
  es 0 y no un número negativo, con la nota que lo explica (`reloj_antiguedad`, `nota_antiguedad`). Los instantes de la
  respuesta, también `en_sombra[].sombra.creado_en`, salen en -05:00 (§8.1).
- **La activación manual no se salta la gobernanza.** `POST /models/{id}/activate` aplica la misma compuerta de cuatro
  criterios que la sombra (`politica.compuerta`: WAPE ≤ el del activo y ≤ `wape_max`, cobertura P10-P90 calibrada entre
  `cobertura_aviso` y `cobertura_max`, |sesgo| ≤ `sesgo_max`), con los dos modelos en la misma ventana. La ventana debe
  empezar después de todo lo que vio el candidato (corte + 61 días de validación, o el fin de la serie de su sombra): si
  no, responde 422 `ventana_en_muestra`. Un modelo ya rechazado o con la sombra en curso solo se activa con
  `forzar=true` y un motivo, que queda en la auditoría (`activacion_forzada`, con los criterios que no cumplió); así no
  se puede probar una ventana tras otra hasta que alguna apruebe. La activación manual deja la misma traza que la
  automática (`metricas.activacion`), de modo que la reversión automática también la vigila.

### 6.2 El modelo usa los datos validados recientes (§9.5, RF-013)

- **Variables, error y monitoreo sobre lo que llega.** `inferencia.tabla_variables` arma las variables y los valores
  reales con `politica.serie_validada`: el Parquet empaquetado con las horas de `demanda_observada` encima (solo entran
  las que pasaron la calidad del lote). Solo se recalculan los días tocados por lo nuevo y los 56 días siguientes, porque
  los rezagos llegan hasta 8 semanas; la tabla queda en caché por la huella del histórico (filas, último día, última
  carga y suma de pasajeros). El resultado es idéntico a reconstruir toda la tabla
  (`test_variables_con_lo_validado_son_las_de_recalcular_toda_la_serie`).
- **Quién la usa.** La evaluación del error (`inferencia.evaluar`), el monitoreo (`monitoreo.registrar`), la foto de
  variables, las predicciones del retador en sombra, la compuerta y la reversión reciben la sesión del ciclo
  (`inferencia.con_sesion`), así que ven también lo que la transacción del ciclo todavía no confirma.
  `GET /models/{id}/evaluation` usa la sesión de la petición.
- **Prueba de integración.** Con solo el Parquet, `predecir` para el 2026-01-09 falla («Sin variables…») y `evaluar` del
  2026-01-08 dice «No hay datos reales». Al llegar el 2026-01-08 validado a `demanda_observada`, el pronóstico del día
  siguiente funciona con banda v2 y SHAP, el rezago de 7 días del 15 de enero es el valor recibido, el error se mide
  contra lo que llegó, el monitoreo cubre la ventana y la API evalúa ese día
  (`tests/integracion/test_monitoreo_api.py::test_un_dia_validado_despues_del_parquet_actualiza_variables_y_se_pronostica`).
- **En lote.** `inferencia.predecir_horas(ruta, inicios, model_id)` hace el pronóstico de varias horas con una llamada a
  los tres modelos y a SHAP, y devuelve exactamente los mismos diccionarios que `predecir` hora por hora
  (`test_predecir_horas_es_predecir_hora_por_hora`). En las 17 horas de servicio de un día, el lote es de 14,8 a 17,7
  veces más rápido que pedirlas una por una, con resultados idénticos en las tres rutas (`predecir_horas_lote.json`,
  medido con el equipo cargado: lo que vale es la razón, no los segundos). El ciclo diario lo usa para el contexto de
  las alertas observadas y el plan del día para sus 17 horas.
- **Sin sesión** (scripts de evidencia y pruebas unitarias), la tabla es la del Parquet empaquetado, así que las cifras
  de esta carpeta no dependen del estado de ninguna base. Con `INFERENCIA_SERIE=validada`, un proceso sin sesión abre la
  suya (ve solo lo ya confirmado).

## 7. Explicabilidad (§9.4, RF-015)

Importancia global (media de |SHAP| en escala logarítmica, prueba reservada; `explicacion_local_y_bandas.json`):

| Variable | Media de abs(SHAP) | Qué es |
|---|---|---|
| b8 | 0,354 | media de la misma hora y día de las 8 semanas previas (la regla manual) |
| tipo_dia | 0,103 | laboral, sábado, domingo o festivo |
| m4 | 0,093 | media de 4 semanas |
| hora | 0,076 | hora del día |
| nivel_7_13 | 0,060 | nivel de la semana anterior |
| festivo | 0,055 | festivo nacional |
| sd8 | 0,046 | variabilidad de las 8 semanas |
| ruta_cod | 0,028 | ruta |
| mes | 0,026 | estacionalidad anual |
| vacaciones | 0,021 | temporada de vacaciones |

La explicación local de cada pronóstico (SHAP TreeExplainer) reconstruye el pronóstico de las 3.111 horas de la
prueba con un error relativo máximo de 2,2 × 10⁻¹⁴. Latencia de `predecir`: mediana 47,2 ms y P95 96,0 ms en 75
llamadas (`explicacion_local_y_bandas.json`).

## 8. Pruebas de fuga temporal y no regresión (§14.1 «Datos/ML»)

| Prueba | Qué garantiza |
|---|---|
| `tests/datos_ml/test_fuga_temporal.py` | alterar los pasajeros posteriores a un corte (2024-06-30, 2025-08-31, 2025-10-31) no cambia ninguna variable hasta corte + 7 días y sí desde corte + 8 (la prueba es sensible); el calendario no depende de los pasajeros; entrenamiento, validación y prueba son cronológicos y sin solape |
| `tests/datos_ml/test_no_regresion.py` | hash del artefacto; WAPE y MAE de la prueba reservada iguales al informe de `scripts/evaluar_modelo.py` (clave `evaluacion` del manifiesto, ±0,5 puntos); supera a B1 y a B2; cobertura de la banda estable (±2 puntos); la banda calibrada v2 reproduce su evidencia; la sección de entrenamiento no guarda métricas de la prueba |
| `tests/unit/test_inferencia.py` | `entrenar()` no mide la prueba reservada y el manifiesto no guarda el estado; SHA-256 del código igual con CRLF y con LF; el preprocesamiento es el del entrenamiento del activo; variables con lo validado iguales a recalcular toda la serie; `predecir_horas` igual a `predecir` hora por hora |
| `tests/datos_ml/test_distribucion.py` | distribución de las variables y de la serie |
| `tests/datos_ml/test_backtest_alertas.py` | el backtest de alertas publicado se reproduce con el código y la calibración vigentes |
| `tests/unit/test_calibracion.py` | hash de la calibración, aplicación por bloque, versión en cada predicción, igualdad sklearn/ONNX, mismo WAPE; cada candidato entrenado trae su calibración ajustada con su validación, la usa al predecir y al evaluar, y no cambia sus métricas |
| `tests/unit/test_politica.py` | compuerta con la banda calibrada de cada modelo, grupos de calibración del activo, antigüedad nunca negativa, `creado_en` de la sombra en -05:00 |
| `tests/integracion/test_monitoreo_api.py` | reentrenamiento con historial validado sembrado por la propia prueba (no depende del orden), `GET /monitoring/policy` en -05:00 y sin días negativos; un día validado posterior al Parquet permite pronosticar, evaluar y monitorear; la activación manual rechaza ventanas dentro de la muestra (422), aplica los cuatro criterios, exige `forzar=true` con motivo para un rechazado y no salta la sombra |

## 9. El modelo dentro del ciclo diario (§9.5, §10)

El ciclo diario ahora recomienda igual que `POST /predictions/run`: toma la hora principal de cada ventana de 30, 60 o
120 minutos (`variables.por_hora`), con su demanda por hora y su banda calibrada, y resuelve la función objetivo de
§10.2 (`optimizacion.recomendacion_franja`). Antes trataba la demanda de la ventana como si fuera horaria: en SILENCIO,
las tres ventanas que empiezan a las 6:00 del 16-10-2025 (30, 60 y 120 min) se recomendaban como las horas 6, 7 y 8
con 472, 848 y 1.471 pasajeros y daban 6, 10 y 18 buses/h. Ahora las tres usan la hora 6 con su demanda por hora (844
pasajeros, P90 1.019) y dan una sola recomendación de 7 buses/h, marcada como inviable por la flota y explicada
(`ciclo_recomendacion_franja.json`, segunda corrida). El ciclo completo sí era lento, sobre todo en la carga inicial:
el perfil mostró un recorrido cuadrático del lote al buscar los días completos y una recomendación resuelta una vez por
horizonte aunque los tres cayeran en la misma franja. Con dos ajustes que no cambian los resultados (los días se cuentan
en una pasada y se resuelve una recomendación por ruta y franja), con el mismo corte la carga inicial de 49.623 filas
pasó de 94,5 s en la versión 8d4e651 (109,8 s justo antes del ajuste) a 27,7 s, y un día nuevo de 51 filas de 18,9 s a
7,9 s (`docs/evidencias/rendimiento/ciclo_antes_despues.md`).

Alertas de pronóstico del 15-09 al 31-12-2025, a las 6:00 de cada día y con los tres horizontes (324 días-ruta;
`docs/evidencias/alertas/backtest_alertas_pronostico.md`). Antes se comparaba la demanda de la ventana de 30, 60 o
120 min con la capacidad por hora; ahora se compara la carga crítica por hora de la franja recomendada (factor de
carga × P10/P50/P90 por hora) con la capacidad por hora ofrecida:

| Alerta | Antes (por ruta y día) | Ahora (por ruta y día) |
|---|---|---|
| ALT-001 alta demanda prevista | 2,552 | 0,435 |
| ALT-002 sobreocupación | 2,358 | 0,315 |
| ALT-003 frecuencia insuficiente | 0,250 | 0,380 |
| ALT-004 frecuencia excesiva | 0,003 | 0,031 |

Los buses/h recomendados ya no dependen del horizonte (antes 8,22, 13,35 y 18,46 de media para 30, 60 y 120 min;
ahora 9,97 en los tres). El MILP tarda 0,065 s de media por franja. Con la calibración v2, las alertas observadas
ALT-005 a ALT-009 pasan de 0,509 a 0,534 por ruta y día (ALT-007 de 0,176 a 0,204, con lift 1,28 → 1,34;
`docs/evidencias/alertas/backtest_alertas.md`, línea «Antes del cambio»). Con todas las reglas observadas (también la
ALT-002 observada y la ruptura de comportamiento) son 1,238 por ruta y día.

## 10. Limitaciones

- Las horas 17-20 y las vísperas de festivo son las de mayor error (WAPE 22,65, 34,68 y 30,28) y, en noviembre y
  diciembre, las de menor cobertura de la banda.
- El objetivo de 30 minutos se aproxima con la fracción observada de subidas por media hora.
- Candidato temporal (tercer nivel de §9.1): se evaluaron en el informe académico, no en la API. La comparación de 51
  modelos del experimento 12 incluye un Temporal Fusion Transformer, N-HiTS y una red convolucional 3D propia sobre la
  cuadrícula semana × día × hora (`informe/secciones/03_metodologia.tex`, tabla de referencias;
  `informe/secciones/04_resultados.tex`, «Comparación de 51 modelos»). Con el mismo protocolo, la mejor red, el TFT,
  queda 0,26 puntos de WAPE peor que el LightGBM del experimento 11. No se integró en la API porque no mejora al
  tabular, necesita torch y neuralforecast en el contenedor de inferencia y no tiene una explicación local exacta ni
  exportación ONNX como la del HGB. Queda en el plan de evolución si llegan más años de datos.
- Las novedades viales del día objetivo se usan como variable porque las 25 de los datos son eventos programados; una
  novedad imprevista debería filtrarse por su fecha de registro, que la tabla de Extreme no trae (docstring de
  `app/servicios/variables.py`).
- La prueba reservada de nov–dic 2025 se consultó al elegir fv2 frente a fv1 (sección 1): es informativa. Se pide a
  Extreme un periodo de 2026 como prueba limpia.
- El histórico validado (`demanda_observada`) guarda ruta, fecha, hora, pasajeros y salidas; el sentido, el segmento,
  el viaje y el vehículo no están en él (sección 3). Por lo mismo, la foto de variables (`feature_snapshot`) es por
  ruta y hora: guarda las dimensiones de §8.3 (`idruta`, `idempresa`, `idproceso`, `id_dia_semana`,
  `id_estacionalidad`), pero `sentido` y `segmento` quedan nulos, porque el modelo no los usa (el reparto por segmento
  se aplica después del pronóstico).
- La calibración v2 del activo se ajustó con septiembre y octubre de 2025 y no anticipa el cambio de temporada de
  noviembre y diciembre. Cada reentrenamiento ajusta y versiona la suya con su propia validación (sección 6.1), así que
  un candidato entrenado con datos recientes trae una banda calibrada con esos datos.

## 11. Cómo reproducir cada cifra

| Evidencia | Se genera con |
|---|---|
| `evaluacion_modelo.md` y `.json` | `python scripts/evaluar_modelo.py` |
| `horizontes.json` | `python scripts/evaluar_horizontes.py` |
| `calibracion_condicional.md` y `.json`; `calibracion_v2.json` del modelo | `python scripts/calibrar_por_grupo.py --escribir` |
| `calibracion_condicional_hgb_fv1_20250831_s42.md` y `.json` | `python scripts/calibrar_por_grupo.py --model-id hgb_fv1_20250831_s42` |
| `calibracion_v2.json` de cada candidato nuevo | el propio entrenamiento (`inferencia.entrenar`, sección 6.1) |
| `explicacion_local_y_bandas.json` | pruebas y precalentamiento del modelo (`app/servicios/inferencia.py`) |
| `entrenamiento_fv2.json` | `python scripts/entrenar.py` (dos veces, mismo SHA-256) |
| `predecir_horas_lote.json` | `python scripts/evaluar_lote_inferencia.py` |
| `pytest_datos_recientes_y_activacion.txt` | las pruebas de integración del modelo (16) y las unitarias completas con datos/ML del modelo (567), con la lista de lo que demuestra cada prueba nueva |
| claves `codigo_*` e `historial_prueba_reservada` de cada `manifest.json` | `python scripts/evaluar_codigo_modelo.py --escribir` (no toca el artefacto, los ONNX ni la calibración: verifica sus SHA-256 antes y después) |
| `../monitoreo/monitoreo_2025.json` (con `calibracion_version` y `generado_en`), `../monitoreo/compuerta_ejemplo.json` (2025-09-01 a 2025-09-14, fuera de la prueba reservada) y `../monitoreo/psi_dia_lag7.json` | `python scripts/evidencias_monitoreo.py` |
| `ciclo_recomendacion_franja.json` | `POST /api/v1/frequency/executions` con la fuente Parquet de octubre de 2025, antes y después del cambio |
| `pesos_objetivo_0005.json` | `python scripts/evidencia_0005.py`: migración 0005 en una base local temporal (instalación, `GET /thresholds`, bajada y subida; la base se borra al terminar) |
| `../alertas/backtest_alertas.md` y `.json` | `python scripts/backtest_alertas.py` |
| `../alertas/backtest_alertas_pronostico.md` y `.json` | `python scripts/backtest_alertas.py --pronostico` |
| la suite completa de pruebas (unitarias, integración, réplica, contrato y datos/ML) | la suite final de la tabla «Cifras vigentes» de `../README.md`. La corrida de las 05:32 con el detalle de las pruebas del modelo (904 pruebas, 900 pasan, 0 fallos y 4 omitidas a propósito) está en `../historial/modelo_suite_9nov_0532.txt` |
