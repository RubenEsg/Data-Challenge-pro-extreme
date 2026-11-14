# E12 · Modelos fundacionales sin reentrenar: Chronos-Bolt, Chronos-2 y TimesFM 2.5

**Pregunta.** ¿Un modelo fundacional de series de tiempo, usado sin reentrenar (*zero-shot*) y corriendo en esta máquina, le gana a V4, el LightGBM de E11 (WAPE h = 7 = 13,94 %), con exactamente el mismo protocolo? ¿Y sirve como complemento de V4, como variable de un híbrido o como miembro de un ensamble?

**Respuesta corta**
- **Solo, ningún fundacional le gana a V4.**
  - El mejor es Chronos-2 con el calendario como covariables: 14,71 %, +0,77 puntos [+0,47; +1,14], mejor en 2 de 12 meses.
  - TimesFM 2.5 con calendario (XReg) llega a 14,96 %, +1,02 [+0,67; +1,43], sin ningún mes mejor.
  - Sin covariables, todos quedan entre 17,1 y 18,4 %.
- **Como variable dentro de V4, sí aporta.** El híbrido `hibrido_V4_chronos2cov` es el LightGBM de V4 con el pronóstico *zero-shot* de Chronos-2 como 4 variables más.
  - Logra **13,62 %, −0,32 puntos [−0,43; −0,22], mejor en 11 de 12 meses**: **cumple la regla de selección** (IC entero bajo 0 y al menos 7 de 12 meses).
  - La ganancia se repite en 2024 con pliegues equivalentes: −0,33 [−0,50; −0,14], 10 de 12 meses.
  - El ensamble NNLS sin fuga V4 + Chronos-2 también cumple la regla (13,79 %, −0,15 [−0,25; −0,03], 11 de 12), con menos ganancia.
- **Por qué pierden solos: el calendario.**
  - Sin covariables, entre el 68 y el 76 % de su desventaja sale de 28 días especiales (festivos, Carnaval, Semana Santa, 24-25 y 31 de diciembre, 1 de enero). En esos días pronostican casi el doble de pasajeros.
  - Con el calendario, la desventaja baja de unos 3-4 puntos a 0,8-1. Lo que queda está en esos mismos días (WAPE 35-38 % frente a 25 % de V4), en los domingos y en un sesgo al alza de +4 % en los laborales.
- **La formulación por ruta con 17 pasos por día rinde peor que la diaria en los tres modelos.** Chronos-Bolt fracasa del todo (43,7 % el small y 45,9 % el base) a cualquier antelación.

## 1. Qué se corrió

**Modelos.** Todos tienen pesos abiertos con licencia Apache-2.0.
- Los pesos se descargaron de Hugging Face a una carpeta `hf_cache` fuera del proyecto, sin credenciales.
- La inferencia es local, en la RTX 3050, en float32. Ningún dato salió de la máquina.
- Ningún modelo se reentrenó ni se ajustó con los datos de Sobusa.

| Modelo | Repositorio | Origen | Parámetros | Contexto máximo | Covariables |
|---|---|---|---|---|---|
| Chronos-Bolt small | `amazon/chronos-bolt-small` | Amazon | 47,7 M | 2.048 pasos; horizonte nativo 64 | No admite |
| Chronos-Bolt base | `amazon/chronos-bolt-base` | Amazon | 205,3 M | 2.048 pasos; horizonte nativo 64 | No admite |
| Chronos-2 | `amazon/chronos-2` | Amazon | 119,5 M | 8.192 pasos; horizonte nativo 1.024 | Pasadas y futuras, numéricas y categóricas; también multivariado |
| Chronos-2 small | `autogluon/chronos-2-small` | Amazon (AutoGluon) | 27,9 M | 8.192 pasos | Igual que Chronos-2 |
| TimesFM 2.5 | `google/timesfm-2.5-200m-pytorch` | Google | 231,3 M (transformador de 200 M + cabezas de salida) | 16.384 pasos entre contexto y horizonte | Con XReg: regresión lineal en contexto sobre las covariables |

Los parámetros se contaron en las cabeceras de los `safetensors` descargados.

**Formulaciones**
- **Diaria (51 series).** Una serie por ruta × hora de salida (3 rutas × 17 horas, de 4 a 20 h).
  - Para cada día d de 2025, el contexto es `y_ctx_imp` hasta d − 7, con toda la historia desde el 1-1-2023: de 725 a 1.089 días.
  - Se piden 7 pasos y se toma el 7.º (el día d). El pronóstico puntual es la mediana, que es lo que minimiza el error absoluto.
  - Son 365 días × 51 series = 18.615 pronósticos, uno por franja de prueba.
- **Por ruta con 17 pasos por día (`ruta17`).** Cada ruta es una sola serie con las horas 4..20 de cada día seguidas.
  - El contexto termina en d − 7 a las 20 h. Su largo depende del modelo: 120 días (2.040 pasos) en Chronos-Bolt, 481 días (8.177 pasos) en Chronos-2 y 956 días (16.252 pasos) en TimesFM.
  - Se piden 7 × 17 = 119 pasos y se toman los 17 últimos, que son las horas del día d.
- **Multivariada por ruta (`multiruta_cov`, solo Chronos-2).** Cada ruta es un ítem con 17 objetivos, sus 17 horas, que comparten información por la atención de grupo de Chronos-2. Lleva además el calendario.

**Covariables.** Todas son calendario conocido de antemano; ninguna variable observada entra como covariable.
- **Conjunto base (`COV_CAL`).** Lo fijó la sesión anterior antes de ver resultados, por conocimiento del dominio: E11 mostró que V4 es, en esencia, "la media de las 4 mismas semanas corregida por calendario".
  - `tipo_dia`: categórica (laboral, sábado, domingo o festivo).
  - `festivo`, `vac_escolar`, `vac_univ`, `carnaval` y `semana_santa`.
- **Con día de la semana.** Las variantes `xreg_sem` y `xreg_serie` de TimesFM añaden `dia_semana` (categórica), a pedido del usuario.
- **Chronos-2.** Recibe las covariables como pasadas (alineadas con el contexto) y futuras (los 7 días de corte + 1 a d).
  - A las categóricas les aplica *target encoding* con el contexto del propio ítem.
  - En `ruta17_cov`, el calendario diario se repite en los 17 pasos de cada día y se añade la hora como categórica.
- **TimesFM 2.5.** Usa la regresión en contexto XReg (`forecast_with_covariates`, JAX en CPU). Tiene dos modos oficiales:
  - **"xreg + timesfm"** (el de las variantes `xreg`):
    1. normaliza el contexto de cada serie;
    2. ajusta una regresión lineal (MCO) sobre las covariables del contexto;
    3. TimesFM pronostica el residuo;
    4. al pronóstico se le suma la parte lineal de los días futuros.
  - **"timesfm + xreg"** (variante `xreg_tx`): TimesFM pronostica la serie original y la regresión se ajusta sobre los residuos de su retropronóstico.

**Variantes** (nombre en `resultados/` y `predicciones/`):

| Nombre | Modelo | Formulación | Contexto | Covariables |
|---|---|---|---|---|
| `chronos_bolt_small`, `chronos_bolt_base` | Chronos-Bolt | Diaria | `y_ctx_imp`, toda la historia | — |
| `chronos_bolt_small_ruta17`, `chronos_bolt_base_ruta17` | Chronos-Bolt | Por ruta, 17 pasos por día | 120 días | — |
| `chronos2` | Chronos-2 | Diaria | toda la historia | — |
| `chronos2_cov` | Chronos-2 | Diaria | toda la historia | `COV_CAL` |
| `chronos2_cov_sinfallas` | Chronos-2 | Diaria | `y_ctx` con las franjas con falla en NaN | `COV_CAL` |
| `chronos2_multiruta_cov` | Chronos-2 | Multivariada: ruta con 17 objetivos | toda la historia | `COV_CAL` |
| `chronos2_ruta17`, `chronos2_ruta17_cov` | Chronos-2 | Por ruta, 17 pasos por día | 481 días | — / `COV_CAL` + hora |
| `chronos2_small`, `chronos2_small_cov` | Chronos-2 small | Diaria | toda la historia | — / `COV_CAL` |
| `timesfm25` | TimesFM 2.5 | Diaria | toda la historia (`max_context` 1.120) | — |
| `timesfm25_xreg` | TimesFM 2.5 | Diaria | ídem | `COV_CAL`; XReg oficial "xreg + timesfm" con una regresión común a las 51 series de cada día |
| `timesfm25_xreg_sem` | TimesFM 2.5 | Diaria | ídem | `COV_CAL` + `dia_semana`; ídem |
| `timesfm25_xreg_serie` | TimesFM 2.5 | Diaria | ídem | `COV_CAL` + `dia_semana`; misma fórmula, una regresión por serie |
| `timesfm25_xreg_tx` | TimesFM 2.5 | Diaria | ídem | `COV_CAL`; modo oficial "timesfm + xreg" (exploratoria, añadida después de ver las otras) |
| `timesfm25_ruta17` | TimesFM 2.5 | Por ruta, 17 pasos por día | 956 días | — |
| `hibrido_V4_chronos2cov` | LightGBM V4 + Chronos-2 | Tabular, como V4 | — | Las 77 variables de V4 + 4 de Chronos-2 con calendario (sección 6) |
| `ens_V4_chronos2_cov_nnls`, `ens_V4_fundacionales_nnls` | Ensambles sin fuga | — | — | Sección 6 |

**XReg con una regresión por serie (`timesfm25_xreg_serie`).**
- **Por qué.** La API oficial ajusta **un solo** MCO con todas las series de cada llamada. Con las 51 series de un día, el efecto de un festivo queda igual, en unidades estandarizadas, para las 5 h que para el mediodía y para las tres rutas.
- **Qué hace.** Repite exactamente la fórmula de XReg con un MCO por serie:
  - objetivo normalizado por serie;
  - numéricas estandarizadas con el contexto;
  - categóricas one-hot sin la primera categoría;
  - intercepto y pseudoinversa.
- **Cómo es eficiente.** Las 51 series de un día comparten las filas de covariables, así que es un solo MCO con 51 columnas de objetivo. TimesFM pronostica los 51 residuos en lote.
- **Validación.** Antes de correr se compara con la API oficial llamada con una sola serie por llamada, lo que equivale a una regresión por serie. En las 102 series del 1-1-2025 y del 3-3-2025, la diferencia máxima de la mediana fue de 0,016 pasajeros (4·10⁻⁵ relativo), dentro de la precisión de JAX en float32 (`registro/timesfm25_xreg_serie.json`).

## 2. Cumplimiento del protocolo y tratamiento equivalente a V4

| Regla | Cómo se cumple |
|---|---|
| 12 pliegues mensuales de 2025, h = 7 | Cada día d usa un contexto que termina en d − 7 (`fund_comun.contextos_diarios` → `A.ventanas_contexto`, que nunca entrega datos posteriores al corte). Se pide un horizonte de 7 días y se toma el paso 7 |
| Corte de entrenamiento (días < inicio del mes) | No aplica a los modelos *zero-shot*: no ajustan nada con nuestros datos. Sí aplica al híbrido (LightGBM entrenado por pliegue con días < ini) y a los ensambles (pesos del mes m solo con los meses < m) |
| Corte verificado | Cada predicción lleva la columna `corte` = d − 7 y se evalúa con `A.evaluar(..., requiere_corte=True)`. El arnés comprobó d − corte ≥ 7 en todas (`corte_verificado = true`, `h_min_dias = 7`) |
| Sin fuga entre cortes | Chronos-2 corre con `cross_learning=False`: cada ítem es su propio grupo y no ve contextos de otros cortes. XReg de TimesFM ajusta una regresión con todas las series de una llamada, así que cada llamada lleva solo las 51 series de un mismo día, con el mismo corte |
| Contexto corregido como en V4 | `y_ctx_imp`: pasajeros corregidos por viajes sin registro, con los huecos imputados de forma causal. Es la serie de la que salen los rezagos de V4 (`lag7(y_ctx)` = `pasajeros_total_lag7`) |
| Pesos de V4 (0,25 atípicos, 0,1 fallas, 0 R5) | Sin entrenamiento no hay pérdida que ponderar. El análogo es `chronos2_cov_sinfallas`: contexto `y_ctx` con las franjas `falla` (≥ 25 % sin registro, regla mecánica observable el mismo día) en NaN, que Chronos-2 ignora. La etiqueta a posteriori `atipico` no se usa en ningún modelo. El híbrido usa las mismas filas y pesos que V4 |
| Misma prueba y métricas | Las 18.615 franjas contra `pasajeros_total` sin corregir, con `A.evaluar`: WAPE, MAE, RMSE, sesgo, desagregaciones y bootstrap pareado de días contra V4 (2.000 réplicas, semilla 42). Los negativos se recortan a 0: de 0 a 167 franjas de 18.615 según el modelo (120 en `chronos2_cov` y en `timesfm25_xreg`). Caen casi todos en las salidas de las 4 h, donde la mediana real es 0 pasajeros |
| Semilla e hilos | Semilla 42 (`A.dispositivo_torch()`), 2 hilos de CPU por proceso; JAX de XReg en CPU con 2 hilos |

## 3. Resultados (2025, h = 7, 18.615 franjas)

Ordenados por WAPE. La diferencia es WAPE del modelo − WAPE de V4, en puntos, con su IC 95 % por bootstrap pareado de días. "Meses mejor" cuenta los meses de 2025 en que el modelo tiene menor WAPE que V4. El tiempo es la corrida completa con la GPU compartida (sección 8).

| Modelo | WAPE h=7 | MAE | RMSE | Sesgo | Dif. con V4 [IC 95 %] | Meses mejor | Tiempo (s) | Archivo |
|---|---|---|---|---|---|---|---|---|
| `hibrido_V4_chronos2cov` | 13,62 % | 94,2 | 141,4 | +1,45 % | −0,32 [−0,43; −0,22] | 11/12 | 1209 | `predicciones/hibrido_V4_chronos2cov.parquet` |
| `ens_V4_chronos2_cov_nnls` | 13,79 % | 95,3 | 142,7 | +0,44 % | −0,15 [−0,25; −0,03] | 11/12 | — | `predicciones/ens_V4_chronos2_cov_nnls.parquet` |
| `V4_lightgbm` (referencia) | 13,94 % | 96,4 | 144,0 | +1,42 % | — | — | — | `predicciones/V4_lightgbm.parquet` |
| `ens_V4_fundacionales_nnls` | 13,96 % | 96,5 | 144,5 | +0,71 % | +0,02 [−0,19; +0,27] | 10/12 | — | `predicciones/ens_V4_fundacionales_nnls.parquet` |
| `chronos2_cov` | 14,71 % | 101,7 | 154,1 | +4,08 % | +0,77 [+0,47; +1,14] | 2/12 | 5444 | `predicciones/chronos2_cov.parquet` |
| `chronos2_cov_sinfallas` | 14,72 % | 101,8 | 155,1 | +4,32 % | +0,78 [+0,45; +1,18] | 3/12 | 751 | `predicciones/chronos2_cov_sinfallas.parquet` |
| `chronos2_multiruta_cov` | 14,72 % | 101,8 | 153,6 | +3,72 % | +0,78 [+0,43; +1,22] | 2/12 | 150 | `predicciones/chronos2_multiruta_cov.parquet` |
| `timesfm25_xreg` | 14,96 % | 103,5 | 155,1 | +3,82 % | +1,02 [+0,67; +1,43] | 0/12 | 351 | `predicciones/timesfm25_xreg.parquet` |
| `timesfm25_xreg_sem` | 14,99 % | 103,7 | 155,3 | +3,81 % | +1,05 [+0,69; +1,46] | 0/12 | 354 | `predicciones/timesfm25_xreg_sem.parquet` |
| `timesfm25_xreg_serie` | 15,24 % | 105,4 | 158,6 | +4,49 % | +1,30 [+0,90; +1,73] | 0/12 | 310 | `predicciones/timesfm25_xreg_serie.parquet` |
| `chronos2_small_cov` | 15,29 % | 105,7 | 157,4 | +4,08 % | +1,35 [+0,99; +1,77] | 1/12 | 208 | `predicciones/chronos2_small_cov.parquet` |
| `timesfm25_xreg_tx` | 16,00 % | 110,7 | 168,3 | +2,77 % | +2,06 [+1,66; +2,55] | 0/12 | 858 | `predicciones/timesfm25_xreg_tx.parquet` |
| `chronos2` | 17,08 % | 118,1 | 196,1 | +4,62 % | +3,14 [+2,04; +4,44] | 1/12 | 114 | `predicciones/chronos2.parquet` |
| `chronos2_ruta17_cov` | 17,20 % | 118,9 | 180,3 | +1,85 % | +3,26 [+2,72; +3,93] | 0/12 | 597 | `predicciones/chronos2_ruta17_cov.parquet` |
| `chronos2_small` | 17,60 % | 121,7 | 206,5 | +6,32 % | +3,66 [+2,37; +5,23] | 1/12 | 37 | `predicciones/chronos2_small.parquet` |
| `timesfm25` | 17,90 % | 123,7 | 208,2 | +4,52 % | +3,96 [+2,70; +5,45] | 1/12 | 285 | `predicciones/timesfm25.parquet` |
| `chronos_bolt_base` | 18,23 % | 126,1 | 208,5 | +3,46 % | +4,29 [+3,05; +5,73] | 0/12 | 4097 | `predicciones/chronos_bolt_base.parquet` |
| `chronos_bolt_small` | 18,40 % | 127,2 | 210,7 | +4,24 % | +4,46 [+3,15; +5,92] | 0/12 | 37 | `predicciones/chronos_bolt_small.parquet` |
| `chronos2_ruta17` | 19,85 % | 137,3 | 227,5 | +2,72 % | +5,91 [+4,54; +7,57] | 0/12 | 68 | `predicciones/chronos2_ruta17.parquet` |
| `timesfm25_ruta17` | 20,77 % | 143,6 | 235,8 | +5,19 % | +6,83 [+5,35; +8,53] | 0/12 | 439 | `predicciones/timesfm25_ruta17.parquet` |
| `chronos_bolt_small_ruta17` | 43,71 % | 302,3 | 435,7 | −7,90 % | +29,77 [+28,79; +30,87] | 0/12 | 410 | `predicciones/chronos_bolt_small_ruta17.parquet` |
| `chronos_bolt_base_ruta17` | 45,93 % | 317,6 | 444,8 | −0,17 % | +31,99 [+30,56; +33,57] | 0/12 | 132 | `predicciones/chronos_bolt_base_ruta17.parquet` |

**Lectura**
- **Candidatos que cumplen la regla:** el híbrido (13,62 %) y el ensamble V4 + Chronos-2 (13,79 %). El de menor WAPE es el híbrido.
  - La regla se fijó antes de ver resultados: IC 95 % de la diferencia entero bajo 0 y mejora en al menos 7 de 12 meses.
  - La decisión final entre familias es de `A.aplicar_regla` sobre todos los `resultados/`.
  - Con los 47 resultados que había en E12 el 7-10-2026 a las 06:30, la regla elige `hibrido_V4_chronos2cov`. Le siguen los ensambles de árboles `ens_arboles_media_gbm` (13,76 %) y `ens_arboles_nnls` (13,80 %) y el ensamble V4 + Chronos-2 (13,79 %), que también la cumplen. Otras familias pueden añadir resultados después.
- **Las covariables de calendario son lo que más pesa.** A Chronos-2 le bajan el WAPE de 17,08 a 14,71 %; a TimesFM, de 17,90 a 14,96 %; a Chronos-2 small, de 17,60 a 15,29 %.
- **El tamaño ayuda poco.**
  - Chronos-Bolt base (205 M parámetros) apenas mejora a small (48 M): 18,23 frente a 18,40 %.
  - Chronos-2 (120 M) le gana a su versión small (28 M) por 0,5-0,6 puntos.
- **Variantes que no cambian nada:**
  - ocultar las franjas con falla (`cov_sinfallas`: 14,72 %);
  - el modelo multivariado por ruta (`multiruta_cov`: 14,72 %);
  - el día de la semana en XReg (`xreg_sem`: 14,99 %).
- **Cobertura del intervalo q10-q90:** de 0,81 a 0,85 en los modelos diarios, frente a 0,80 nominal (`tabla_fundacionales.csv`). Los cuantiles están razonablemente calibrados.

## 4. TimesFM 2.5 (Google): qué tan bueno es y por qué

Se corrió completo con el protocolo: 51 series diarias ruta × hora, contexto hasta d − 7, paso 7, mediana. Se probó sin covariables, con calendario por XReg en sus dos modos oficiales, con y sin día de la semana, con una regresión común y con una por serie, y en la formulación por ruta.

| Variante | WAPE | Dif. con V4 [IC 95 %] | Meses mejor | Días especiales | Domingos | Laborales de clases | Laborales de vacaciones | Sesgo laborales |
|---|---|---|---|---|---|---|---|---|
| V4 (referencia) | 13,94 % | — | — | 25,3 % | 18,1 % | 12,47 % | 14,29 % | +1,1 % |
| `timesfm25` (sin covariables) | 17,90 % | +3,96 [+2,70; +5,45] | 1/12 | 99,0 % | 20,8 % | 13,39 % | 15,19 % | +0,6 % |
| `timesfm25_xreg` (calendario, regresión común) | **14,96 %** | **+1,02 [+0,67; +1,43]** | 0/12 | 38,0 % | 23,2 % | **12,20 %** | 15,06 % | +3,9 % |
| `timesfm25_xreg_sem` (+ día de la semana) | 14,99 % | +1,05 [+0,69; +1,46] | 0/12 | 38,6 % | 23,2 % | 12,21 % | 15,07 % | +3,9 % |
| `timesfm25_xreg_serie` (una regresión por serie) | 15,24 % | +1,30 [+0,90; +1,73] | 0/12 | 37,6 % | 24,6 % | 12,35 % | 15,28 % | +5,2 % |
| `timesfm25_xreg_tx` (modo "timesfm + xreg") | 16,00 % | +2,06 [+1,66; +2,55] | 0/12 | 44,9 % | 22,4 % | 13,51 % | 15,24 % | +2,6 % |
| `timesfm25_ruta17` (por ruta, 119 pasos) | 20,77 % | +6,83 [+5,35; +8,53] | 0/12 | 113,0 % | 32,1 % | 14,21 % | 17,40 % | 0,0 % |

**Grupos de días** (`analisis_fundacionales.py`; disjuntos y fijados por calendario):
- **Especiales (28 días):** festivos que no caen en domingo, Carnaval, Semana Santa, 24, 25 y 31 de diciembre y 1 de enero.
- **Domingos:** 49. **Sábados:** 50.
- **Laborales:** 238, separados en clases y vacaciones escolares o universitarias.

**Qué tan bueno es**
- **Sin covariables (17,90 %).** Es un buen pronosticador del patrón semanal: en los laborales de clases queda a 0,9 puntos de V4. Supera a Chronos-Bolt (18,2-18,4 %) y queda cerca de Chronos-2 univariado (17,08 %). Pero no sabe nada del calendario.
- **Con el calendario por XReg (14,96 %).** Recupera tres cuartas partes de la desventaja (de +3,96 a +1,02 puntos) y en los laborales de clases **le gana a V4** (12,20 frente a 12,47 %). Es el segundo mejor fundacional, a 0,25 puntos de Chronos-2 con calendario.
- **Contra V4 no alcanza.** El IC queda entero por encima de 0, es peor en los 12 meses (de +0,15 en febrero a +3,48 en marzo) y no cumple la regla.
- **Combinado con V4.** No se probó un híbrido con TimesFM. En el ensamble NNLS de todos los fundacionales, las variantes de TimesFM con XReg reciben peso, pero ese ensamble no cumple la regla (sección 6).

**Por qué no le gana a V4.** De la desventaja de `timesfm25_xreg` (+1,02 puntos del WAPE total):
1. **Días especiales: +0,51 puntos, la mitad.**
   - Sin covariables, TimesFM los trata como días normales: WAPE 99 %, sesgo +93 %. De ahí salen 2,98 de los 3,96 puntos de `timesfm25`.
   - XReg los baja a 38 %, pero V4 logra 25 %.
   - XReg aprende cada efecto con una regresión lineal común a las 51 series del día y con pocos ejemplos en el contexto: 2 Carnavales, 2 Semanas Santas y unos 35 festivos. V4 aprende con árboles efectos distintos por ruta, hora y tipo de día, y además ve rezagos del mismo tipo de día.
2. **Domingos: +0,34 puntos.**
   - Con XReg empeoran respecto a TimesFM solo: 23,2 % frente a 20,8 % (V4: 18,1 %).
   - También empeoran con el día de la semana como covariable, así que no es por juntar domingos y festivos en `tipo_dia`.
   - Una explicación probable: la regresión común resta un perfil semanal medio de toda la historia, igual para todas las franjas, y el residuo que pronostica TimesFM no recupera bien el nivel propio de los domingos de cada franja. El sesgo en domingos es pequeño (−2 %), así que el problema es de dispersión.
3. **Vacaciones y sesgo: +0,20 puntos en los laborales de vacaciones.** Además, `timesfm25_xreg` sobreestima los laborales en un +3,9 % (V4: +1,1 %).
4. **Variantes que no ayudan:**
   - El **día de la semana** no aporta (14,99 %): TimesFM ya capta el ciclo semanal desde el contexto.
   - **Una regresión por serie** empeora (15,24 %): con unos 14 coeficientes por serie y pocos días especiales en el contexto, el MCO por serie sobreajusta. La regresión común actúa como regularización.
   - El modo **"timesfm + xreg"** empeora (16,00 %): la regresión sobre los residuos del retropronóstico corrige peor los días especiales (44,9 %).
   - La **formulación por ruta** (20,77 %) es la peor de todas.
5. **Costo.** `timesfm25_xreg` tardó 351 s para los 18.615 pronósticos: unos 19 ms por pronóstico en la GPU compartida, más la regresión de XReg en CPU.

## 5. Dónde pierden los fundacionales frente a V4

Exceso de error absoluto frente a V4, en puntos del WAPE total, por grupo de días (`analisis_fundacionales.csv`):

| Modelo | Exceso total | Días especiales | Domingos | Sábados | Laborales | WAPE en días especiales | Sesgo en días especiales | WAPE en laborales de clases |
|---|---|---|---|---|---|---|---|---|
| V4 | — | — | — | — | — | 25,3 % | +9,0 % | 12,47 % |
| `chronos_bolt_small` | +4,46 | +3,04 | +0,39 | +0,09 | +0,94 | 100,5 % | +97,6 % | 13,53 % |
| `chronos2` | +3,14 | +2,38 | +0,15 | +0,07 | +0,54 | 84,1 % | +75,1 % | 13,11 % |
| `timesfm25` | +3,96 | +2,98 | +0,18 | +0,10 | +0,70 | 99,0 % | +93,4 % | 13,39 % |
| `chronos2_cov` | +0,77 | +0,38 | +0,13 | +0,02 | +0,24 | 34,7 % | +15,7 % | 12,66 % |
| `chronos2_multiruta_cov` | +0,78 | +0,60 | +0,12 | +0,07 | −0,01 | 40,1 % | +27,5 % | 12,31 % |
| `timesfm25_xreg` | +1,02 | +0,51 | +0,34 | +0,11 | +0,07 | 38,0 % | +9,6 % | 12,20 % |
| `hibrido_V4_chronos2cov` | −0,32 | −0,06 | 0,00 | −0,02 | −0,24 | 23,7 % | +5,0 % | 12,19 % |

- **Sin covariables**, el 68-76 % de la desventaja sale de 28 días de 365. En los días normales los fundacionales quedan a menos de 1 punto de V4.
- **Con calendario**, la brecha se reparte entre los días especiales, los domingos y los laborales.
  - En los laborales de clases, Chronos-2 multivariado (12,31 %) y TimesFM con XReg (12,20 %) ya le ganan a V4 (12,47 %).
  - En los laborales de vacaciones, ninguno.
- **Por ruta y franja**, Chronos-2 con calendario pierde en todas: SILENCIO 16,48 frente a 15,52 %; CRA 54 12,27 frente a 11,54 %; CL 72 19,69 frente a 19,08 %. Su peor mes es marzo (+3,53 puntos, Carnaval).

## 6. Híbrido V4 + Chronos-2 y ensambles

**Híbrido (`hibrido_V4_chronos2cov`).** Diseño fijado por la sesión anterior antes de ver resultados.
- **Variables.** El pronóstico *zero-shot* de Chronos-2 con calendario (variante `cov`) del día t, hecho con contexto hasta t − 7 (el mismo corte que los rezagos de V4), entra como 4 variables más de V4:
  - mediana `fm_c2`, cuantiles `fm_c2_q10` y `fm_c2_q90`;
  - razón `fm_c2_ratio` = mediana / media de las 4 mismas semanas de V4.
- **Entrenamiento.** LightGBM Poisson con las mismas filas, pesos (0,25 atípicos, 0,1 fallas), hiperparámetros y semilla que V4, por pliegue con los días < inicio del mes.
- **Pronósticos de Chronos-2.**
  - Se calcularon para todos los días desde el 29-1-2023 (`cache/chronos2_cov_todos_los_dias.parquet`, 703 días en 1.142 s).
  - Los de 2025 se reutilizaron de `predicciones/chronos2_cov.parquet`, la misma variante con el mismo corte.
  - El lote de inferencia no cambia los pronósticos: `cross_learning=False`, el tiempo se codifica relativo al final del contexto y el relleno se enmascara. Se verificó recalculando enero con lote 64 frente a 256: diferencia máxima de la mediana 0,00085 pasajeros, sobre una media de 659 (`verificacion_lote_chronos2.json`).
- **Por qué no hay fuga.**
  - Ningún pronóstico usa datos posteriores a su t − 7; el script lo comprueba antes de entrenar.
  - Las covariables futuras son solo calendario.
  - Chronos-2 no se entrenó con datos de Sobusa.

| | WAPE | Dif. con V4 [IC 95 %] | Meses mejor | p (t pareada / Wilcoxon, por mes) |
|---|---|---|---|---|
| 2025 (protocolo) | 13,62 % | −0,32 [−0,43; −0,22] | 11/12 (solo marzo +0,16) | 0,0003 / 0,0015 |
| 2024 (robustez, `validacion_2024_hibrido.json`) | 15,41 % frente a 15,73 % de V4 | −0,33 [−0,50; −0,14] | 10/12 | 0,042 / 0,042 |

- **Dónde gana.** La mejora es amplia:
  - laborales de clases (12,19 frente a 12,47 %) y de vacaciones (13,94 frente a 14,29 %);
  - días especiales (23,7 frente a 25,3 %);
  - las 3 rutas y las 3 franjas.
  - Sin el mes de mayor ganancia sigue en −0,29 puntos. El total diario por ruta queda igual que V4: 4,92 frente a 4,86 %.
- **Peso en el modelo.** Las variables de Chronos-2 se llevan entre el 89,8 y el 91,9 % de la ganancia de los árboles según el pliegue. Chronos-2 resume en un número el nivel reciente, el patrón semanal y el calendario; LightGBM lo corrige con las variables de V4.
- **Validación en 2024.** Mismos pliegues mensuales con días < inicio del mes. Es un diagnóstico de robustez y no interviene en la selección.

**Ensambles sin fuga** (`A.ensamble_sin_fuga`, NNLS: los pesos del mes m solo usan los meses < m; enero usa pesos iguales). Método y regla de miembros fijados antes de ver resultados.
- **`ens_V4_chronos2_cov_nnls` (V4 + Chronos-2 con calendario): 13,79 %, −0,15 [−0,25; −0,03], 11/12. Cumple la regla.**
  - Pesos de febrero a diciembre: V4 de 0,58 a 0,80 y Chronos-2 de 0,19 a 0,40 según el mes. Enero usa 0,5 y 0,5.
  - Suman de 0,97 a 0,99: el ensamble encoge un poco el pronóstico y su sesgo queda en +0,44 % (V4: +1,42 %).
  - Pierde solo en marzo (+0,40).
- **`ens_V4_fundacionales_nnls` (V4 + los 13 fundacionales diarios): 13,96 %, +0,02 [−0,19; +0,27], 10/12. No cumple.**
  - Lo hunde enero, con pesos iguales entre 14 miembros: +1,56 puntos.
  - De febrero en adelante le gana a V4 en 10 de 11 meses. Pesos medios de febrero a diciembre:
    - V4: 0,63 (entre 0,53 y 0,74);
    - `chronos2_small_cov`: 0,12;
    - `timesfm25_xreg_serie`: 0,09;
    - `chronos2_cov`: 0,08;
    - `chronos2_cov_sinfallas`: 0,03;
    - `timesfm25_xreg_tx`: 0,02.
  - `xreg_sem`, `xreg_serie` y `xreg_tx` se corrieron después de fijar la regla de miembros y entran por esa misma regla.
- **Diagnóstico** (`diagnostico_ensambles.csv`, no son candidatos).
  - La correlación de errores con V4 es de 0,67-0,70 en los fundacionales sin covariables y de 0,86-0,89 con calendario (0,81 en `xreg_tx`).
  - La media simple 50/50 de V4 y Chronos-2 con calendario daría 13,86 %.

## 7. Formulación por ruta con 17 pasos por día

Es viable en los tres modelos, pero rinde peor que la diaria:

| Modelo | Diaria | `ruta17` |
|---|---|---|
| Chronos-Bolt small | 18,40 % | 43,71 % |
| Chronos-Bolt base | 18,23 % | 45,93 % |
| Chronos-2 | 17,08 % | 19,85 % |
| Chronos-2 con calendario (+ hora) | 14,71 % | 17,20 % |
| TimesFM 2.5 | 17,90 % | 20,77 % |

**Diagnóstico** (`diagnostico_horizonte.py` → `diagnostico_horizonte.json`; no es candidato). ¿Es un error al armar las series o un problema de horizonte? Para responderlo:
- Se tomaron 45 cortes cada 8 días y se midió el WAPE según los días de antelación, de 1 a 7. Con el paso de 8 días, cada antelación recorre los 7 días de la semana.
- **Chronos-Bolt small `ruta17` falla a cualquier antelación:** 42,7 % ya a 1 día y entre 42,7 y 50,9 % de 1 a 7 días. No es la degradación del encadenamiento autorregresivo más allá de 64 pasos: el modelo no capta la estructura de 17 pasos por día con 120 días de contexto. El base (45,9 % en la corrida completa) tampoco.
- **Chronos-2 `ruta17`** queda cerca de su versión diaria a todas las antelaciones (16,7 a 22,3 % frente a 14,9 a 22,0 %). Así que el armado de las series es correcto.
- **El error no crece de forma sistemática con la antelación** en ningún modelo. Lo dominan los días concretos: el 1 de enero cae en la antelación 1 de esta muestra.

## 8. Tiempos de inferencia

| Corrida | Carga (s) | Inferencia (s) | Nota |
|---|---|---|---|
| `chronos_bolt_small` | 8 | 29 | ~1,5 ms por pronóstico |
| `chronos_bolt_base` | 107 | 3.991 | GPU desbordada (ver abajo); con la GPU libre, enero tardó 9 s, unos 106 s el año |
| `chronos_bolt_small_ruta17` | 15 | 393 | 1.095 series de 2.040 pasos, 119 pasos de horizonte; GPU compartida |
| `chronos_bolt_base_ruta17` | 9 | 123 | lote 32, con la GPU libre (en la sesión anterior, con lote 256, se quedó sin memoria) |
| `chronos2` | 9 | 106 | lote 64 |
| `chronos2_cov` | 11 | 5.433 | lote 256 + GPU desbordada; la variante equivalente `cov_sinfallas` (lote 64) tardó 742 s |
| `chronos2_cov_sinfallas`, `chronos2_multiruta_cov` | 8 | 742 / 142 | lote 64 |
| `chronos2_ruta17`, `chronos2_ruta17_cov` | 9 | 60 / 588 | lote 32 |
| `chronos2_small`, `chronos2_small_cov` | 8 | 29 / 199 | lote 64 |
| `timesfm25` | 6 | 279 | ~15 ms por pronóstico (con la invariancia al signo, que duplica el cálculo) |
| `timesfm25_xreg`, `_xreg_sem` | 3 | 348 / 351 | XReg en CPU (JAX), una llamada por día |
| `timesfm25_xreg_serie` | 3 | 280 + 27 | 27 s de validación contra la API oficial |
| `timesfm25_xreg_tx` | 4 | 855 | compartiendo la GPU con los pronósticos del híbrido |
| `timesfm25_ruta17` | 3 | 436 | contextos de 16.252 pasos |
| Híbrido | — | 1.142 + 67 | Chronos-2 para 2023-01-29..2024-12-31 (2025 reutilizado) + LightGBM de los 12 pliegues en CPU |

**GPU compartida.** Los tiempos son orientativos: la RTX 3050 (6 GB) se compartió con el agente de redes neuronales y entre corridas propias.
- Cuando la memoria pedida pasa de los 6 GB, Windows desborda a memoria compartida y todo se vuelve de 10 a 40 veces más lento. Le pasó a `chronos_bolt_base` diaria en la sesión anterior y a `chronos2_cov`.
- Con lote 256, la atención de grupo de Chronos-2 crea matrices tiempo × lote × lote y el proceso llegó a ocupar 3,9 GB, más 1,2 GB desbordados.
- Por eso las corridas siguientes usaron lote 64. Con ese lote, Chronos-2 ocupa menos de 1 GB y va unas 5 veces más rápido, sin cambiar los pronósticos.

## 9. Limitaciones

1. **Solo *zero-shot*.** Chronos-2 y TimesFM admiten ajuste fino (`fit` en Chronos-2), que podría acercarlos más a V4. Quedó fuera del alcance ("sin reentrenar").
2. **Solo covariables de calendario.** No se usaron la climatología (`clim_*`) ni los eventos programados (`partido_dia`, `evento_otro_dia`), que también se conocen de antemano y que V4 sí usa.
3. **Muchas variantes evaluadas en 2025.** Son 18 variantes de fundacionales, el híbrido y 2 ensambles (21 candidatos), así que el mejor de muchos es optimista.
   - El híbrido se fijó antes de ver resultados y su ganancia se repite en 2024.
   - `xreg_sem`, `xreg_serie` y `xreg_tx` de TimesFM se añadieron después, a pedido del usuario o como exploración; ninguna cumple la regla.
4. **XReg es lineal y de pocos ejemplos.** Con 2 o 3 Carnavales y Semanas Santas en el contexto, los efectos de esos días quedan mal estimados, sea con una regresión común o con una por serie.
5. **Sesgo al alza.** Los fundacionales diarios con calendario sobreestiman en +3,7 a +4,5 % (`xreg_tx`: +2,8 %; V4: +1,4 %), sobre todo en los laborales. El ensamble NNLS lo atenúa con pesos que suman 0,97-0,99. No se probó una corrección de sesgo aparte.
6. **Tiempos con la máquina compartida** (sección 8).
7. **Pesos de V4.** Sin entrenamiento no hay pesos que aplicar; `cov_sinfallas` (su análogo) no cambió el resultado.

## 10. Lo que no se corrió

| Qué | Por qué |
|---|---|
| TimesFM 3.0 (`google/timesfm-3.0-pytorch`) | Licencia no comercial ("TimesFM Non-Commercial License v1.0"); la sesión anterior solo descargó el archivo de licencia. Se usó TimesFM 2.5, que es Apache-2.0 |
| Chronos-2 con `cross_learning=True` (las 51 series del mismo día compartiendo información) | No se corrió. La variante multivariada por ruta, que comparte información entre las 17 horas, no mejoró |
| Ajuste fino de Chronos-2 o TimesFM | Fuera del alcance (*zero-shot*) |
| Híbrido V4 + TimesFM | No estaba planeado. Tras ver resultados sería una elección a posteriori; el híbrido con Chronos-2 ya cumple la regla |
| XReg con *ridge* o con una regresión por ruta | Sería ajustar después de ver los resultados de 2025 |
| Otros fundacionales (Moirai 2, TiRex, Toto, Sundial) | No estaban en el encargo |

## 11. Cómo reproducir y archivos

Desde la carpeta del proyecto, con el Python del entorno aislado (`venv_e12`):
```
PYTHONIOENCODING=utf-8 MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1 <venv_e12>/Scripts/python.exe experimentos/E12_comparacion_modelos/modelos_fundacionales/<script> <opciones>
```
- `--meses 1,2` corre una prueba rápida: evaluación parcial que no guarda nada.
- Las corridas de GPU se hicieron de a una por vez, con una cola de trabajos.

| Archivo | Contenido |
|---|---|
| `fund_comun.py` | Contextos hasta d − 7, formulación `ruta17`, covariables de calendario, formato de salida y evaluación con el arnés (escribe `registro/`) |
| `chronos_bolt.py` | Chronos-Bolt (`--modelo small\|base`, `--formulacion diaria\|ruta17`, `--lote`) |
| `chronos2.py` | Chronos-2 (`--variante uni\|cov\|cov_sinfallas\|multiruta_cov\|ruta17\|ruta17_cov`, `--repo autogluon/chronos-2-small`, `--lote`) |
| `timesfm25.py` | TimesFM 2.5 (`--variante uni\|xreg\|xreg_sem\|xreg_serie\|xreg_tx\|ruta17`, `--forzar` para recalcular una variante ya guardada) |
| `hibrido_v4_chronos2.py` | Híbrido: `--solo-pronosticos` (GPU, caché en `cache/`) y luego sin opciones (LightGBM en CPU) |
| `resumen_fundacionales.py` | Ensambles sin fuga, `tabla_fundacionales.csv`, tabla en Markdown y `diagnostico_ensambles.csv/.json` (`--sin-ensambles` solo rehace la tabla) |
| `analisis_fundacionales.py` → `analisis_fundacionales.csv/.json` | WAPE, sesgo y exceso de error contra V4 por grupo de días |
| `diagnostico_horizonte.py` → `diagnostico_horizonte.json` | WAPE según la antelación (1-7 días), formulación diaria frente a `ruta17` |
| `verificar_lote_chronos2.py` → `verificacion_lote_chronos2.json` | Invariancia de Chronos-2 al lote de inferencia |
| `validacion_2024_hibrido.py` → `validacion_2024_hibrido.json` | Robustez del híbrido en 2024 |
| `registro/<modelo>.json` | Configuración, tiempos, métricas resumidas y cobertura q10-q90 de cada corrida |
| `logs/` | Salida de cada corrida |
| `../predicciones/<modelo>.parquet`, `../resultados/<modelo>.json` | Formato común del arnés: predicciones (con `corte`, `q10` y `q90`) y métricas completas con el bootstrap pareado contra V4 |
