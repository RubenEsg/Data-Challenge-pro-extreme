# E9 · Clima: ¿la lluvia y los arroyos explican la demanda, los tiempos de ciclo y las cancelaciones?

Experimento nocturno del 5 de octubre de 2026. Datos locales (`datos/`), sin conexión a la base. Reproducible desde la carpeta
del proyecto con `PYTHONIOENCODING=utf-8 MPLBACKEND=Agg python experimentos/E9_clima/run.py` (8,7 min con n_jobs = 2, casi
todo en los 8 modelos LightGBM; con `E9_REUSAR_MODELOS=1` reutiliza las predicciones guardadas en `cache_modelos/` y tarda menos de 1 min).

## Respuesta corta

- **La lluvia explica muy poco de la variación día a día de la demanda.** Con la lluvia horaria de Open-Meteo, las variables de
  lluvia explican el **1,9 %** de la varianza del desvío diario de pasajeros frente a la línea base de calendario (2023–2025) y
  el **0,6 %** de la varianza del residuo diario del pronóstico E1 en 2025. A nivel de hora de salida, el 0,3 %.
- **Efecto sobre la demanda: pequeño y negativo.** Frente a una hora seca, una hora con lluvia moderada (2–10 mm/h) en la hora de
  salida o en las 3 previas tiene **−1,1 %** de pasajeros (−1,8 % frente a lo esperado, IC 95 % −2,9 a −0,7 %); con
  5–10 mm/h, unos **−2 %**; con > 10 mm/h, −2,6 % pero con solo 8 días y un IC que incluye 0. Los domingos y festivos el efecto
  es mayor (−2,4 % moderada; −12 % fuerte, con muy pocos datos). CL 72 es la ruta más sensible.
- **Efecto sobre el tiempo de ciclo: claro y monótono, pero modesto.** El ciclo mediano sube **+1 %** con 1–2 mm/h durante el
  viaje, **+1,8 %** con 2–5 mm/h, **+2,5 %** con 5–10 mm/h y ≈ **+3 %** sobre 10 mm/h (≈ 5–7 min sobre un ciclo de ~245 min).
- **Cancelaciones y retraso de salida: sin efecto detectable** (diferencias de 0,0–0,4 pp y de 0,0–0,2 min, con IC que
  incluyen 0).
- **Modelo:** añadir clima al LightGBM de E1 **no mejora** el pronóstico, ni siquiera con el clima observado (cota superior).
  Ver la sección 3.
- **Advertencia principal:** la lluvia de Open-Meteo es un producto de modelo/reanálisis en malla de ~9–25 km. Suaviza los
  aguaceros convectivos que forman los arroyos: su máximo horario en tres años es 19,4 mm/h, y el aguacero torrencial del
  15 de junio de 2024 (buses atrapados en arroyos según la prensa, pasajeros −30 % según E10) aparece como 9,7 mm en el día y
  4,6 mm/h de pico. Los efectos estimados aquí son **cotas inferiores** del efecto de los arroyos reales (sesgo de atenuación).

## Pregunta y datos

¿La lluvia y los arroyos de Barranquilla explican la demanda (pasajeros por ruta, día y hora de salida), los tiempos de ciclo y
las cancelaciones de SILENCIO, CRA 54 y CL 72? ¿Sirve añadir clima al modelo de demanda?

**Fuente del clima.** Open-Meteo Historical Weather API (`archive-api.open-meteo.com/v1/archive`), modelo por defecto
`best_match` (combina ECMWF IFS de 9 km y ERA5/ERA5-Land), punto solicitado 10,96 N −74,80 O (devuelto 10,93 N −74,77 O,
50 m), zona horaria America/Bogota, variables horarias `precipitation, rain, temperature_2m, relative_humidity_2m,
weather_code`. Licencia CC BY 4.0: *Zippenfeld, P. (2023). Open-Meteo.com Weather API. https://open-meteo.com/* y, para el
reanálisis, *Hersbach, H. et al. (2023). ERA5 hourly data on single levels from 1940 to present. Copernicus Climate Change
Service (C3S) Climate Data Store*. Archivos:

- `clima_open_meteo_raw.json` (2023–2025), `clima_open_meteo_raw_2013_2022.json` (para la climatología) y
  `clima_open_meteo_raw_era5.json` (2023–2025 con `models=era5`, solo para la sensibilidad) — respuestas JSON sin tocar.
- `datos/clima_barranquilla_2023_2025.parquet` (horario, 26.304 horas) y `datos/clima_diario.parquet` (fecha, precipitación
  diaria, horas con lluvia ≥ 0,1 mm, intensidad máxima horaria y su hora, lluvia 4–22 h, horas ≥ 2 mm/h).

**Convención horaria.** En Open-Meteo la precipitación con marca *T* es la acumulada en la hora anterior (T−1 h, T]. Se
re-indexa por el **inicio** de la hora, así que "hora de salida *h*" se cruza con la lluvia caída entre *h* y *h*+1.

**Panel operativo.** `E1_lgbm_salida/datos_modelado_salida.parquet` (ruta × día × hora de salida 4–20 h, 55.896 filas) más,
desde `progvehiculos`: viajes programados, cancelados (`cancelada = 'S'`), ciclo mediano de los viajes limpios (duración
`fechafin − fechainicio`, 30–360 min, 1–300 pasajeros) y retraso mediano de salida (`fechainicio − fechasalida`).

## Método

**Clases de lluvia** (mm/h): sin lluvia < 0,1; ligera 0,1–2; moderada 2–10; fuerte > 10. Exposiciones: la misma hora de salida;
el máximo de las 1–3 horas previas; el máximo de la hora o las 3 previas (la principal para demanda); y el máximo durante las
4 horas del viaje (*h*..*h*+3, la principal para el ciclo, que dura ~4 h).

**Lo esperado (línea base descriptiva, 2023–2025).** Para cada ruta × hora, la mediana del mismo valor el mismo día de la
semana 1, 2 y 3 semanas antes **y después** (mínimo 3 de 6), excluyendo de la referencia días especiales (festivos, Carnaval,
Semana Santa, 20 dic–10 ene, partidos, eventos y días excluidos en E1). Es centrada (usa el futuro) a propósito: es un
contrafactual descriptivo, no un pronóstico. El análisis descriptivo usa solo días normales (945 días). Para 2025 se usa además
el **residuo del pronóstico E1** (h = 7, `predicciones_2025.parquet`), que ya controla calendario y tendencia.

**Desvío.** Σ real / Σ esperado − 1 por clase (agregado, ponderado por pasajeros), con IC 95 % por bootstrap de días (400
réplicas). Como la línea base mediana tiene un pequeño sesgo (−0,7 % en horas secas), se reporta también el desvío **frente a
las horas secas**. Complemento: regresiones MCO de log(real/esperado) por hora (no ponderadas) con efecto fijo de ruta y errores
agrupados por día, con la lluvia de la misma hora y de las previas a la vez.

**Regla de umbral.** Para cada X ∈ {0,5; 1; 2; 3; 5; 8} mm/h, horas con lluvia ≥ X frente a horas secas (< 0,1).

**Eventos de aguacero ('arroyos').** Días con intensidad máxima ≥ 8 mm/h o lluvia diaria ≥ 20 mm (51 días; 48 normales). Para
cada uno: desvío del día y de la ventana de tormenta (3 h antes a 1 h después del pico en horario de operación), ciclo, viajes,
cancelaciones y retraso.

**Modelo (protocolo común).** El LightGBM Poisson agrupado de E1 (mismas variables, 600 árboles, lr 0,03, 31 hojas, 12 pliegues
mensuales de 2025, entrenamiento con todo lo anterior a cada mes; se reutiliza `E1_lgbm_salida/run.py`) con:

| Variante | Variables de clima añadidas |
|---|---|
| E1 base (a) | ninguna (réplica de E1) |
| (a) nowcast / cota superior | 13 observadas: lluvia en *h*, *h*−1, suma y máximo de *h*−3..*h*−1, suma y máximo de *h*..*h*+3, lluvia del día (total, 4–22 h, horas, máximo), lluvia del día anterior, temperatura y humedad |
| (a2) nowcast parsimonioso | 3 observadas: máximo de *h*−3..*h*, suma de *h*..*h*+3, lluvia del día 4–22 h |
| (a3) nowcast monótono | como (a2) con restricción monótona decreciente (más lluvia nunca sube la predicción) |
| (b) operativo h = 7 | solo climatología 2013–2022 (media y probabilidad de lluvia por mes × hora, lluvia del viaje, lluvia diaria del mes, probabilidad de día lluvioso) y temporada (seca dic–mar, 1.ª lluviosa abr–jun, veranillo jul–ago, 2.ª lluviosa sep–nov) |
| (b') operativo + rezagos | (b) + lluvia observada de d−13..d−7 y d−36..d−7 (permitido con h = 7) |

La climatología se calcula con 2013–2022, fuera del periodo de entrenamiento y de prueba: no hay fuga. Las variantes nowcast usan
información que no existe 7 días antes: miden **cuánto ganaría un pronóstico del tiempo perfecto**, no un modelo desplegable.
Diferencias de WAPE con IC 95 % por bootstrap pareado de días (1.000 réplicas).

## Resultados

### 1. Cuánto llueve y cuándo (`lluvia_mensual.csv`, `fig1_lluvia_mensual.png`)

- Precipitación anual (Open-Meteo): 2023 1.128 mm, 2024 1.516 mm, 2025 1.154 mm; climatología Open-Meteo 2013–2022 1.345 mm.
- Régimen bimodal típico del Caribe: diciembre–marzo casi seco (8–33 mm/mes, 3–9 días ≥ 1 mm), primera temporada de lluvias
  mayo–junio (~160 mm/mes), veranillo julio–agosto, y segunda temporada septiembre–noviembre (180–220 mm/mes, 25–29 días con
  lluvia, ~6–8 días al mes con algún aguacero ≥ 5 mm/h).
- La lluvia es **de mediodía**: llueve en el 40–50 % de las horas de 10 a 14 h y en menos del 9 % de las horas de 4 a 6 h y de
  18 a 21 h. Es decir, cae casi siempre en el valle de demanda entre picos, no en las horas pico de la mañana.
- En horario de operación (4–20 h, 2023–2025): 14.204 horas secas, 4.006 ligeras, 413 moderadas y solo **9 fuertes**.
- Días con lluvia ≥ 1 mm: 184, 202 y 192 por año — más de lo que registra un pluviómetro (Open-Meteo reparte llovizna de modelo).
  ERA5 puro (`models=era5`, punto 10,75 N) da 1.602–2.410 mm/año; su correlación diaria con `best_match` es 0,63 y coinciden en
  el 82 % de los días en la clasificación ≥ 5 mm. La fuente de lluvia es, por tanto, ruidosa.

### 2. Demanda (`desvio_demanda_por_lluvia.csv`, `desvio_residuos_e1_2025.csv`, `fig2_desvio_demanda_por_lluvia.png`, `fig2b_residuo_e1_por_lluvia.png`, `fig7_desvio_diario_vs_lluvia.png`)

Desvío de pasajeros por hora de salida frente a la línea base (días normales 2023–2025, IC 95 %):

| Lluvia (mm/h) | Misma hora | 1–3 h previas | Hora o 3 previas | ídem, frente a horas secas |
|---|---|---|---|---|
| Sin lluvia | −0,7 % [−1,2; −0,3] | −0,7 % | −0,7 % [−1,1; −0,2] | 0 |
| Ligera (0,1–2) | −0,7 % [−1,3; −0,1] | −0,5 % | −0,5 % [−1,2; 0,1] | +0,2 % |
| Moderada (2–10) | −2,1 % [−3,7; −0,6] | −1,9 % [−3,1; −0,8] | −1,8 % [−2,9; −0,7] | **−1,1 %** |
| Fuerte (> 10) | −4,5 % [−12,4; 5,5] (21 h, 7 días) | −2,9 % [−7,9; 2,2] | −3,2 % [−10,0; 1,6] (87 h, 8 días) | −2,6 % |

Por intensidad fina (hora o 3 previas, `ciclo_y_demanda_por_intensidad.csv`, panel derecho de `fig3`): 2–5 mm/h −1,4 %
[−2,7; −0,2]; 5–10 mm/h −2,5 % [−3,9; −0,6]; > 10 mm/h −3,3 % [−9,4; 1,6] (frente a −0,7 % en horas secas).

- **Viajes válidos**: con lluvia moderada en la misma hora salen −2,9 % de viajes frente a horas secas (−3,2 % [−4,7; −1,5]
  frente a lo esperado). Una parte de la caída de pasajeros es de **oferta** (menos buses salen o terminan), no de demanda:
  los pasajeros **por viaje** no cambian con lluvia ligera o moderada (regresión: +0,6 % y +0,8 %, IC incluye 0) y solo caen con
  lluvia fuerte (−5,3 % [−9,9; −0,4], 21 horas).
- **Por ruta** (hora o 3 previas, frente a horas secas): moderada SILENCIO −0,7 %, CRA 54 −0,8 %, **CL 72 −2,5 %**; fuerte
  −3,1 %, −1,7 %, −4,6 %. **Por tipo de día**: moderada laboral −1,0 %, sábado −1,1 %, **domingo/festivo −2,4 %**; fuerte
  laboral −2,1 %, domingo/festivo −12 % (solo 12 horas-ruta de un único día, el 2023-11-19). La demanda discrecional (fines de semana) es la que se queda en
  casa; la obligada (laboral) casi no cambia.
- **Residuo de E1 en 2025** (h = 7): sin lluvia +0,3 %, ligera +0,9 %, moderada −0,6 % [−3,2; 2,1], todos con IC que incluyen 0
  salvo en CL 72 (moderada −3,7 % [−5,7; −1,1] con la exposición hora o 3 previas). Solo 2 días de 2025 tuvieron alguna hora
  > 10 mm/h.
- **Regresión horaria** (log real/esperado, no ponderada, misma hora y previas a la vez): lluvia moderada en las 1–3 h previas
  −4,9 % [−8,4; −1,2]; moderada en la misma hora −2,5 % [−7,4; 2,6]; ligera en la misma hora +1,9 % [0,0; 3,8]. Las horas de
  poca demanda pesan igual que las de mucha, por eso estas cifras son mayores que el desvío agregado.
- **Variación explicada**: R² incremental de las variables de lluvia del día sobre el log-desvío diario por ruta = **0,019**
  (n = 2.823 ruta-días; DE del desvío diario 8,1 %); sobre el residuo diario de E1 en 2025 = **0,006** (n = 1.095, DE 10,2 %);
  horario = 0,003. `fig7` lo muestra: la nube de desvíos diarios es igual de ancha con y sin lluvia, y el promedio solo baja a
  ≈ −3 % con más de 10 mm en el día.

### 3. Tiempo de ciclo, cancelaciones y retraso (`desvio_operacion_por_lluvia.csv`, `fig3_ciclo_y_demanda_vs_lluvia.png`, `fig4_cancelaciones_retraso.png`)

Ciclo mediano frente a lo esperado según la lluvia máxima durante las 4 h del viaje (días normales, IC 95 %):

| Lluvia máx. en el viaje (mm/h) | 0 | 0,1–0,5 | 0,5–1 | 1–2 | 2–5 | 5–10 | > 10 |
|---|---|---|---|---|---|---|---|
| Desvío del ciclo | −0,2 % | +0,3 % | +0,4 % | +1,0 % | **+1,8 %** [1,1; 2,4] | **+2,5 %** [1,5; 3,5] | +2,8 % [−0,3; 5,7] |
| Horas ruta-hora | 27.021 | 11.041 | 2.970 | 2.318 | 2.433 | 1.112 | 84 |

- El efecto es **igual en las tres rutas** (5–10 mm/h: SILENCIO +2,6 %, CRA 54 +2,4 %, CL 72 +2,4 %); CL 72 llega a +4,1 %
  [0,8; 7,1] sobre 10 mm/h. En minutos: lluvia moderada durante el viaje = ciclo de 248,6 min frente a 244,0 esperados (+4,6 min).
- **Cancelaciones**: tasa media 8,7 % de los viajes programados (CRA 54 6,0 %; SILENCIO y CL 72 ≈ 10 %); diferencia frente a lo esperado de +0,0 pp (ligera),
  +0,2 a +0,4 pp (moderada) y +0,9 a +1,3 pp (fuerte), todas con IC que incluyen 0. Por ruta, solo CL 72 sube con lluvia fuerte
  (+3,4 pp, IC −1 a +7).
- **Retraso de salida**: los buses salen ~3 min antes de lo programado y eso no cambia con la lluvia (≤ 0,2 min).

### 4. Aguaceros y arroyos (`eventos_aguacero.csv`, `fig5_lineas_tiempo_aguaceros.png`)

51 días con pico ≥ 8 mm/h o ≥ 20 mm (48 en días normales). Mediana en días normales: pasajeros del día **−1,4 %**, pasajeros
en la ventana de tormenta **−2,1 %** (cuartiles −5,5 % y +3,2 %), viajes en la ventana −1,3 %, ciclo en la ventana **+2,1 %**
(cuartiles +0,2 % y +5,0 %), cancelación del día 7,6 % frente a 7,3 % esperado. Casos destacados:

- **2024-07-04 (jue, 34,5 mm; 3,7–4,9 mm/h de 17 a 18 h y 9,7 mm/h a las 21 h)**: pasajeros −26 % en la ventana de la tarde,
  ciclo +15 %, viajes −17 %. **2024-11-13 (mié, 12,3 mm/h a las 13 h)**: pasajeros −9 %, ciclo +10 %, viajes −15 %.
  **2023-11-19 (dom, 24,6 mm desde las 5 h)**: pasajeros del día −19 % (los días vecinos están entre −2 % y +7 %: es el caso
  más limpio). **2025-06-12 (jue, 8 mm/h a las 18 h)**: −19 % en la ventana de la tarde, −6 % en el día (la semana ya estaba 3–10 % abajo por el fin de semestre, E10).
- Casos con **confusión** (verificación cruzada con E10): **2024-05-30** (−12 % en el día, ciclo +14,6 %) cae en la semana de
  la transición al Sibus y del fin de semestre universitario (los días vecinos 29-05 a 02-06 están entre −4 % y −23 %);
  **2024-10-10** (7,4 mm/h a las 6 h, −20,5 %) cae en la semana de receso escolar de octubre, cuando toda la semana del 7 al 12
  está entre −8 % y −18 %. En estos dos días la lluvia explica, como mucho, una parte pequeña de la caída.
- El aguacero más intenso del registro, **2023-11-20 (lun, 19,4 mm/h a las 13 h)**, tuvo pasajeros +7 % y ciclo +1,9 %; y
  2025-05-31 (sáb, 13,5 mm/h) +1,3 %. **La hora del aguacero no ordena los efectos de forma sistemática**: en los 48 eventos
  de días normales, la mediana del desvío en la ventana de tormenta es −2,0 % cuando el pico cae en la hora pico de un día
  laboral (5–7 h o ≥ 17 h; 11 eventos), −3,0 % cuando cae en el valle (25 eventos) y +0,9 % en sábados y domingos (12 eventos).
  Las caídas de −18 % a −28 % son casos aislados (2023-11-19, 2024-07-04, 2025-06-12), no la regla.
- Los días 2025-05-01 (−56 %), 2024-06-10 (−70 %) y 2024-09-22 (−40 %) son festivos o días con falla de registro (E10): la caída
  no es de la lluvia.
- **Validación externa**: E10 (prensa) documenta un aguacero torrencial con buses atrapados en arroyos el **2024-06-15** (sábado,
  pasajeros −30 %). Open-Meteo lo registra como 9,7 mm en el día, con pico de 4,6 mm/h a las 7 h: no entra en la lista de
  aguaceros. El dato de lluvia no "ve" bien los arroyos reales.

### 5. Modelo con clima (`resultados.json → variantes`, `fig6_wape_variantes_clima.png`, `predicciones_2025.parquet`)

WAPE de pasajeros por ruta, día y hora de salida, 12 pliegues mensuales de 2025. Diferencia frente a E1 sin clima del mismo
horizonte, en puntos porcentuales, con IC 95 % por bootstrap pareado de días (positivo = peor). 2025 tuvo 82 días lluviosos
(≥ 5 mm) y 39 días con algún aguacero ≥ 5 mm/h.

| Variante | WAPE global | Dif. global (pp) | Días lluviosos ≥ 5 mm | Dif. días lluviosos | Días de aguacero ≥ 5 mm/h | SILENCIO | CRA 54 | CL 72 |
|---|---|---|---|---|---|---|---|---|
| **E1 base (a), h = 7** | **14,40 %** | — | 14,31 % | — | 13,66 % | 16,04 % | 12,04 % | 19,33 % |
| (a) nowcast, clima observado, h = 7 | 14,63 % | **+0,23** [+0,12; +0,36] | 15,00 % | **+0,69** | 14,44 % | 16,30 % | 12,27 % | 19,48 % |
| (a2) nowcast parsimonioso, h = 7 | 14,43 % | +0,03 [−0,03; +0,10] | 14,42 % | +0,11 | 13,76 % | 16,08 % | 12,06 % | 19,36 % |
| (a3) nowcast monótono, h = 7 | 14,37 % | −0,02 [−0,09; +0,04] | 14,54 % | +0,23 | 13,91 % | 16,01 % | 12,01 % | 19,30 % |
| **(b) operativo, climatología, h = 7** | 14,40 % | −0,00 [−0,05; +0,04] | 14,31 % | −0,00 | 13,65 % | 16,04 % | 12,03 % | 19,33 % |
| (b') climatología + lluvia rezagada ≥ 7 d | 14,47 % | +0,07 [−0,00; +0,14] | 14,39 % | +0,07 | 13,72 % | 16,15 % | 12,10 % | 19,37 % |
| E1 base (a), h = 1 | 14,10 % | — | 14,00 % | — | 13,29 % | 15,68 % | 11,74 % | 19,11 % |
| (a) nowcast, clima observado, h = 1 | 14,24 % | +0,14 [+0,03; +0,28] | 14,32 % | +0,32 | 13,85 % | 15,85 % | 11,87 % | 19,22 % |

WAPE en días lluviosos por ruta (h = 7): E1 15,83 / 11,94 / 19,51 %; nowcast 16,48 / 12,75 / 19,88 %; climatología
15,80 / 11,97 / 19,44 % (SILENCIO / CRA 54 / CL 72).

- **Ninguna variante con clima mejora a E1.** La climatología (b) empata exactamente: la estacionalidad de lluvias ya está en el
  mes, la semana del año y los rezagos de E1. Los rezagos de lluvia (b') empeoran levemente.
- **Ni el clima perfecto ayuda.** El nowcast completo (a) **empeora** 0,23 pp (0,69 pp en días lluviosos): las 13 variables de
  clima, ruidosas y con efecto real de 1–3 %, se usan para ajustar ruido de 2023–2024. Las versiones de 3 variables (a2) y
  monótona (a3) quedan en empate estadístico. Las variables de clima reciben solo el 0,1–0,4 % de la ganancia de los árboles.
- **Los días lluviosos no son más difíciles de pronosticar**: el WAPE de E1 en días lluviosos (14,31 %) y de aguacero (13,66 %)
  es igual o menor que el global. Esto coincide con el R² de 0,6 % sobre el residuo de E1.
- `resultados.json → mejor_variante` = E1 base (ninguna variante con clima tiene IC por debajo de 0).
  `predicciones_2025.parquet` guarda E1 base, (a) nowcast y (b) climatología (columna `variante`, h = 7).

## Conclusiones y regla operativa

1. **Cuánto explica la lluvia.** Con la lluvia disponible (Open-Meteo), casi nada de la variación día a día: 1,9 % de la
   varianza del desvío diario frente a la línea base y 0,6 % del residuo de E1. La lluvia de Barranquilla cae sobre todo al
   mediodía, en el valle de demanda, y la mayor parte de los viajes son obligados (trabajo, estudio).
2. **Regla operativa** (desvío frente a una hora seca comparable; días normales 2023–2025):

   | Lluvia máxima (mm/h) | Pasajeros (hora de salida o 3 previas) | Tiempo de ciclo (lluvia durante el viaje) | Cancelaciones | Frecuencia en 2023–2025 |
   |---|---|---|---|---|
   | < 2 | sin cambio (0,0 % a +0,7 %) | +0,5 % a +1,2 % | sin cambio | 21 % de las horas ruta-hora con ≥ 0,5 mm/h |
   | 2–5 | **−0,7 %** (agregado); −3,3 % [−6,7; 0,1] por hora (regresión ≥ 2 mm/h) | **+2,0 %** (≈ +5 min) | +0,3 pp (n. s.) | 8 % de las horas; ~91 días/año con alguna hora ≥ 2 mm/h entre 4 y 21 h (85 si se cuentan solo días normales) |
   | 5–10 | **−1,8 %**; −4,3 % [−9,7; 1,4] por hora (≥ 5 mm/h) | **+2,7 %** (≈ +6–7 min) | 0,0 pp | 2,6 % de las horas; ~34 días/año (31 normales) |
   | > 10 | −2,6 % (IC −9 a +2; 8 días) | +3,0 % (IC −0 a +6) | +0,9 pp (n. s.) | 0,65 % de las horas ≥ 8 mm/h; ~9 días/año |

   Domingos/festivos y CL 72 tienen el doble del efecto en pasajeros (−2,4 % y −2,5 % con lluvia moderada).
   **Traducción al despacho:** sobre 5 mm/h el ciclo crece ≈ 2,5–3 % y la carga por hora baja ≈ 2–4 %. Los dos efectos se
   compensan: hacen falta los mismos buses, y el intervalo real se estira ≈ 3 % si no se agregan. **No conviene recortar ni
   reforzar la programación semanal por el pronóstico de lluvia.** Lo razonable en el día es no retirar buses durante el
   aguacero (las vueltas tardan más); no hay evidencia para un ajuste distinto según la hora del aguacero.
3. **Arroyos.** Con este dato de lluvia no se pueden aislar: los aguaceros que el modelo meteorológico detecta tienen efectos de
   −2 % (mediana) en pasajeros y +2 % en ciclo, con unos pocos casos aislados de −18 a −28 % en la ventana de tormenta
   (2023-11-19, 2024-07-04, 2025-06-12); otros casos llamativos (2024-05-30, 2024-10-10) coinciden con otras causas (E10). El caso
   documentado por la prensa (2024-06-15, −30 %) casi no aparece en Open-Meteo. Los arroyos son eventos raros, de alto impacto,
   que conviene tratar como **contingencia** (como un día atípico de E10), no como una variable del pronóstico.
4. **Para el modelo de demanda:** quedarse con E1 sin clima. La climatología no aporta nada que el calendario no tenga, y el
   clima observado tampoco mejora con esta fuente.

## Limitaciones

- **Medición de la lluvia (la principal).** Open-Meteo `best_match` es salida de modelo en malla (~9 km IFS / ~25 km ERA5) para
  un solo punto; no es un pluviómetro. Suaviza y desplaza los aguaceros convectivos (máximo 19,4 mm/h en tres años; un aguacero
  de arroyo real supera con facilidad 30–50 mm/h), sobreestima los días de llovizna y puede fallar la hora. El caso del
  2024-06-15 lo confirma. El error de medición atenúa todos los efectos hacia 0: las cifras son **cotas inferiores**.
  ERA5 puro difiere bastante (correlación diaria 0,63).
- **Una sola ubicación** para rutas de 56–63 km que cruzan Barranquilla y Soledad: puede llover en un extremo y no en el otro.
- **Pocos eventos fuertes**: 9 horas > 10 mm/h en horario de operación en tres años; los IC de la clase fuerte son anchos.
- **Demanda observada = demanda servida.** Si llueve y salen menos buses, los pasajeros contados bajan aunque la gente quiera
  viajar; parte de la caída es de oferta (viajes válidos −2,9 % con lluvia moderada).
- La línea base centrada tiene un sesgo de −0,7 % en horas secas (mediana frente a media); por eso se reporta el desvío frente a
  horas secas. No hay datos de arroyos (sensores de nivel, reportes de cierre) para validar evento por evento.
- Las cancelaciones de `progvehiculos` no traen la causa; un efecto de lluvia concentrado en pocos viajes se diluye en la tasa
  por hora.

## Próximos pasos

1. Conseguir lluvia **observada** de alta resolución: estaciones IDEAM (aeropuerto Ernesto Cortissoz, Universidad del Norte),
   la red de pluviómetros del Distrito o el sistema de alerta de arroyos de Barranquilla, o productos satelitales (GPM IMERG
   media hora, 0,1°). Repetir este análisis con ella antes de descartar el clima.
2. Registrar en el despacho un campo "arroyo / lluvia" en `observacion` cuando se retienen buses: hoy no se puede distinguir.
3. Probar un ajuste intradía (nowcast real con radar o pronóstico de 0–6 h) solo para el ciclo de las salidas de la tarde
   de la temporada de lluvias, que es donde el efecto es medible.

## Verificación (revisión adversarial, 5 de octubre de 2026)

Se revisó `run.py` (protocolo, fugas, línea base, estadística) y se recalcularon las cifras clave con un script independiente
que no reutiliza funciones de `run.py`: la lluvia desde el JSON crudo de Open-Meteo, la línea base con cruces por fecha (no con
`shift`), el ciclo directamente desde `progvehiculos` y los WAPE desde `predicciones_2025.parquet` y `cache_modelos/`.

**Confirmado (coincide al decimal mostrado):** lluvia anual 1.128 / 1.516 / 1.154 mm; máximo horario 19,4 mm/h (2023-11-20,
13 h); 184 / 202 / 192 días ≥ 1 mm; horas de operación 14.204 / 4.006 / 413 / 9; 40–50 % de horas con lluvia de 10 a 14 h;
51 eventos de aguacero (48 normales); 2024-06-15 = 9,7 mm y pico 4,6 mm/h a las 7 h; correlación diaria con ERA5 0,63;
desvío de pasajeros por clase (seco −0,68 %, moderada −1,77 % → −1,1 % frente a seco; fuerte −2,6 % frente a seco, 8 días);
por ruta (CL 72 −2,5 %) y por tipo de día (domingo/festivo −2,4 %); viajes válidos −2,9 % con lluvia moderada en la misma hora;
ciclo por intensidad (+1,2 / +2,0 / +2,7 / +3,0 % frente a viaje seco; 248,5 frente a 243,7 min con 2–10 mm/h); R² diario
incremental 0,019 (n = 2.823); WAPE de las 8 variantes (14,40 / 14,63 / 14,40 / 14,47 / 14,43 / 14,37 / 14,10 / 14,24 %), por
ruta y en días lluviosos; diferencia nowcast +0,23 pp [0,12; 0,36] y climatología −0,00 pp [−0,05; 0,05] con otro bootstrap.
Protocolo: 12 pliegues mensuales, entrenamiento estrictamente anterior, sin parada temprana ni selección en el pliegue de prueba;
la climatología usa 2013–2022 (sin fuga); los rezagos de (b') son ≥ 7 días. La réplica de E1 no es idéntica al archivo de E1
(WAPE 14,40 % frente a 14,39 %; correlación de predicciones 0,9997), pero todas las comparaciones son contra la réplica, así que
son justas.

**Corregido en este README:**
- Sección 4: se quitó la afirmación "lo que importa es la hora". En los 48 eventos de días normales, la mediana del desvío en la
  ventana de tormenta es −2,0 % con pico en hora pico laboral (11), −3,0 % en el valle (25) y +0,9 % en fin de semana (12).
- 2024-10-10 (−20,5 %) y 2024-05-30 (−12 %) se presentaban como efectos de la lluvia; según E10 coinciden con el receso escolar
  de octubre (toda la semana −8 a −18 %) y con la transición al Sibus y el fin de semestre (días vecinos −4 a −23 %).
- Regla operativa: se retiró "aceptar menos salidas en los aguaceros de la madrugada y del final de la tarde" (no tiene apoyo).
- Días al año con alguna hora ≥ 2 / ≥ 5 mm/h: 91 / 34 contando todos los días (85 / 31 eran solo días normales).
- Tasa de cancelación media: 8,7 % (6,0 % CRA 54), no "8–10 %". Domingo/festivo con lluvia fuerte (−12 %) = un solo día.
- Tiempo de ejecución: 8,7 min (el docstring de `run.py` todavía dice ~25 min).

**Observación:** `run.py` escribe `datos/clima_barranquilla_2023_2025.parquet` y `datos/clima_diario.parquet` fuera de su
carpeta; E7 los usa, así que se mantienen, pero conviene documentarlo como tabla compartida.
