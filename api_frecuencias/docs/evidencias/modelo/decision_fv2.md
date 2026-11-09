# Decisión: modelo fv2 (ruta ordinal + contexto operacional)

Fecha: 2026-11-09. Todas las cifras salen de los archivos de esta carpeta, generados con los scripts del repositorio
(`evaluacion_modelo.json` y `.md`, `entrenamiento_fv2.json`, `horizontes.json`, `explicacion_local_y_bandas.json`).

## Qué cambia frente a fv1

- **Variables fv2-2026-11-09** (`app/servicios/variables.py`): las de fv1 más `nov_impacto`, `nov_sube`,
  `vispera_festivo` y `post_festivo`. `ruta_cod` pasa a ser ordinal (sin `categorical_features`), lo que hace exacta la
  explicación SHAP y permite exportar a ONNX. Se descartaron FIESTA_ATLANTICO (empeora) y puente (no aporta).
- **Varias versiones**: `variables.VERSIONES` registra fv1 y fv2. `cargar()` acepta cualquier versión registrada y
  verifica que las variables del manifiesto coincidan, así que volver a `hgb_fv1_20250831_s42` sigue funcionando.
- **Contexto** (`datos/contexto_operacional.parquet`, generado por `scripts/preparar_datos_api.py --solo-contexto`):
  28 novedades viales en 25 días (246 horas de servicio con novedad) y los festivos FESTIVO_NACIONAL de
  `estacionalidades_anio` hasta 2026. `novedades_viales_ruta` está vacía: cada novedad aplica a las 3 rutas. Las
  novedades del día objetivo se usan como variable porque los 25 días son eventos programados (Carnaval y sus eventos
  previos, partidos de la Selección en el Metropolitano); el supuesto está escrito en el docstring de `variables.py`.
- **Banda P10-P90 calibrada.** La vigente es la **v2**: un cuantil conformal por bloque horario (conformal de Mondrian),
  ajustado solo con la validación y versionado junto al modelo (`calibracion_v2.json`, SHA-256 en el manifiesto). La
  v1 (conformal móvil por ruta, 56 días previos) queda como respaldo con `CALIBRACION_BANDA=v1`. `predecir()` devuelve
  p10/p90 calibrados, `p10_modelo`, `p90_modelo`, `ajuste_conformal` (q) y `calibracion_version`.
- **Perfil intrahorario** (`datos/perfil_intrahorario.parquet`): fracción de subidas en la primera media hora por
  ruta, tipo de día y hora (viajes de 2024, media 0,5175), en lugar del prorrateo 0,5 de las ventanas de 30/60/120 min.
- **Explicación local SHAP** en cada predicción fv2 (`explicacion_local`): la base, las 5 variables con factor
  multiplicativo exacto (exp φ), el efecto en pasajeros (suma = pronóstico − base), el factor resto y una frase.

## Reproducibilidad

`scripts/entrenar.py --hasta 2025-08-31 --semilla 42 --compuerta-activo --verificar-reproducible`
(`entrenamiento_fv2.json`): dos entrenamientos en carpetas temporales dan el **mismo SHA-256**
`24c70b9ca3f6855480d7592855544b82e60e51179b30b88129ab09aa7ed92010`, idéntico al del artefacto registrado. El
preprocesamiento es el mismo del entrenamiento: `codigo_sin_docstring_sha256` del manifiesto coincide con el
`variables.py` actual (prueba `test_preprocesamiento_es_el_del_entrenamiento_del_activo`); el SHA-256 del código se
calcula con fin de línea LF, igual en Windows y en Linux (`scripts/evaluar_codigo_modelo.py`).

## Cómo se eligió fv2: validación y backtests congelados

**Criterio de selección.** El que dice el protocolo: la validación temporal (2025-09-01 a 2025-10-31) y los backtests
con modelos congelados un año antes de 2024 y de 2025.

| Evidencia de selección | fv2 | fv1 | B1 (regla manual) |
|---|---|---|---|
| Validación 2025-09-01 a 2025-10-31, WAPE % | **13,55** | 13,63 | 15,12 |
| 2024, entrenado hasta 2023-12-31, WAPE % [IC95] | 16,26 [14,97–17,91] | 16,25 [14,97–17,90] | 21,55 |
| 2025, entrenado hasta 2024-12-31, WAPE % [IC95] | 14,48 [13,78–15,28] | 14,53 [13,77–15,40] | 20,04 |

- fv2 − fv1 en los backtests: 2024 de −0,08 a +0,09 pp (P 0,42); 2025 de −0,17 a +0,05 pp (P 0,77). **En el total, el
  contexto no gana: la diferencia está dentro del ruido.**
- Sí mejora las horas que el contexto toca (WAPE %, fv1 → fv2): con novedad vial 28,06 → 25,15 en 2024 (n = 246) y
  35,11 → 33,49 en 2025 (n = 255); víspera de festivo 24,12 → 23,40 y 21,31 → 20,18.
- Lo que inclina la decisión no es el error total sino lo que fv2 permite: explicación SHAP exacta, exportación ONNX
  y mejor comportamiento en las horas con novedad o víspera de festivo, sin empeorar la validación.

## La prueba reservada: informativa, no intacta

**Lo que pasó.** fv1 se registró primero (2026-11-09 03:39 UTC) y su entrenamiento midió también la prueba reservada
(nov–dic 2025: WAPE 15,067, `registro.json`). fv2 se diseñó y se comparó después, con esa cifra a la vista, y la
decisión original citaba la mejora en la prueba (14,77 % frente a 15,07 %). Por eso **la prueba de nov–dic 2025 ya no es
una muestra nunca vista**: se consultó al elegir entre fv1 y fv2. Se informa como reporte, no como garantía.

**Lo que se corrigió en el código.** `inferencia.entrenar()` y la compuerta de `scripts/entrenar.py` ya no calculan ni
imprimen métricas de la prueba; solo usan la validación. El informe de la prueba lo escribe únicamente
`scripts/evaluar_modelo.py` (clave `evaluacion` del manifiesto y `evaluacion_modelo.md`). Los manifiestos dejan
constancia en `historial_prueba_reservada` (prueba `test_entrenar_no_mide_la_prueba_reservada_y_el_manifiesto_no_guarda_estado`).

**Lo que se pide.** Un periodo de 2026 que el equipo no haya visto (por ejemplo, enero a marzo de 2026), entregado por
Extreme al final, para medir el modelo activo en una prueba limpia (`docs/hallazgos_extreme.md`).

Reporte de la prueba reservada (2025-11-01 a 2025-12-31, n = 3.111 horas, mismas filas para todos;
`evaluacion_modelo.md`):

| Modelo | WAPE % | IC95 (bloques de 7 días, B = 2000) | MAE | RMSE | sMAPE % | Sesgo % |
|---|---|---|---|---|---|---|
| fv2 `hgb_fv2_20250831_s42` | 14,77 | 13,10–16,87 | 96,27 | 140,86 | 22,23 | +2,75 |
| fv1 `hgb_fv1_20250831_s42` | 15,07 | 13,22–17,43 | 98,20 | 146,02 | 22,44 | +2,54 |
| B1, regla manual de 8 semanas | 21,18 | 16,61–26,79 | 138,06 | 225,99 | 26,28 | +5,85 |
| B2, última semana | 26,40 | 22,77–30,57 | 172,05 | 279,22 | 33,72 | +3,84 |

- fv2 − B1: de −10,43 a −3,21 pp, P(mejora) = 1,00. Esta conclusión no depende de la elección entre fv1 y fv2: fv1 da
  de −9,88 a −3,06 pp, y los dos backtests congelados también superan a B1 (16,26 frente a 21,55 y 14,48 frente a
  20,04).
- fv2 − fv1: de −0,64 a −0,04 pp. Como esta comparación influyó en la elección, no se usa como prueba de que fv2 sea
  mejor que fv1.
- Por ruta (fv2 / fv1 / B1): CL 72 19,23 / 19,48 / 25,27; CRA 54 13,04 / 13,33 / 19,79; SILENCIO 15,33 / 15,68 / 21,30.
- Por condición (fv2 / fv1 / B1): víspera de festivo 30,28 / 35,28 / 43,41 (n = 255; sesgo de fv2 +17,5 %);
  vacaciones 19,87 / 20,90 / 32,01; festivo 21,11 / 21,05 / 145,99; Navidad 29,80 / 30,42 / 273,68 (n = 51).
- La franja más débil sigue siendo 17-19 h: 22,65 %, con sesgo de +8,3 %.

### Cobertura P10-P90 (objetivo 80 %)

| Periodo | Banda del modelo | Calibración v1 (respaldo) | Calibración v2 (vigente) |
|---|---|---|---|
| 2024 congelado | 67,67 % | 79,37 % | — |
| 2025 congelado | 78,51 % | 80,12 % | — |
| Prueba reservada nov–dic 2025 | 79,49 % | 77,88 % | **77,82 %** (ancho medio 303,4 frente a 312,9 de v1) |

En la prueba reservada la banda del modelo ya estaba cerca del 80 %; las dos calibraciones, ajustadas en septiembre y
octubre (con más cobertura), la estrechan un poco. El ajuste muestra su valor cuando cambia el régimen: en 2024 la v1
lleva la cobertura de 67,7 % a 79,4 %. La v2 se eligió con validación cruzada por semanas dentro de la validación
(`calibracion_condicional.md`), no con la prueba.

## Horizontes (`horizontes.json`, mar–dic 2025, modelo fv2 congelado hasta el 2024-12-31, peso del factor intradía 0,3 calibrado en ene–feb)

| Horizonte | Sin ajuste | Con factor intradía | Con perfil intrahorario | Factor y perfil | B1 |
|---|---|---|---|---|---|
| 30 min (n = 13.212) | 20,02 | 20,03 | 19,43 | 19,43 | 23,79 (con perfil 23,12) |
| 60 min (n = 13.770) | 14,80 | 14,71 | — | — | 18,96 |
| 120 min (n = 12.852) | 10,94 | 10,87 | — | — | 15,44 |

El observado de 30 min es una aproximación: pasajeros de la hora por la fracción observada de subidas de los viajes
que salen entre h:00 y h:29, porque no hay conteo crudo por minuto en las exportaciones. La ganancia del factor
intradía es pequeña (~0,1 pp) y con peso 1,0 empeora (16,53 % a 60 min). La del perfil en 30 min es de −0,59 pp.

## Explicación local (`explicacion_local_y_bandas.json`)

- Reconstrucción base × Π factores = pronóstico en las 3.111 horas de la prueba: error relativo máximo 2,2e-14.
- SHAP por fila: p50 3,2 ms, p95 5,6 ms. `predecir()` completo (modelos, SHAP, calibración y factor intradía):
  p50 47,2 ms, p95 96,0 ms.
- Ejemplo: CL 72, 2025-11-01 a las 4 h. Pronóstico 165,4 = base 543,8 × b8 (153) 0,45 × hora 0,78 × m4 0,84 ×
  tipo_dia 1,19 × nivel_7_13 0,90 × resto 0,96.

## Decisión

**Se activa `hgb_fv2_20250831_s42`.** No empeora la validación (13,55 % ≤ 13,63 % de fv1), empata con fv1 en los dos
backtests congelados (diferencias dentro del ruido), mejora las horas con novedad vial y víspera de festivo, y da
explicación exacta, banda calibrada versionada y exportación ONNX. La prueba reservada se informa (14,77 %, IC95
13,10–16,87, frente a 21,18 % de B1), con la salvedad de que se consultó en esta comparación. La compuerta de
`scripts/entrenar.py --compuerta-activo` lo activó y lo dejó en `datos/modelos/registro.json` (historial de
activación). Para volver atrás: `POST /api/v1/models/rollback`, o activar `hgb_fv1_20250831_s42`, que sigue cargando y
prediciendo con el código fv2 (prueba `test_modelo_fv1_sigue_cargando_y_prediciendo_con_codigo_fv2`).
