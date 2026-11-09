# E6 · ¿Se mueven juntas las tres rutas? Modelo conjunto frente a modelo por ruta

Experimento del 2026-10-05 según `experimentos/protocolo_evaluacion.md`. Reproducible con
`python experimentos/E6_por_ruta/run.py` desde la carpeta del proyecto (11,0 min, `n_jobs = 2`, semilla 42).
Solo usa archivos Parquet locales: el conjunto de datos de E1 (`experimentos/E1_lgbm_salida/datos_modelado_salida.parquet`,
ruta × día × hora de salida, 2023-01-01 a 2025-12-31, 55.896 filas), que se construyó a partir de `datos/progvehiculos.parquet`.

**Preguntas.** (1) ¿La demanda de SILENCIO, CRA 54 y CL 72 responde a los mismos factores (calendario, choques comunes) o a factores
locales? (2) Para pronosticar pasajeros por hora de salida, ¿basta un modelo para las tres rutas o conviene uno por ruta? ¿Aporta algo
saber lo que pasó en las otras rutas?

## 1. Qué se hizo

- **Pasajeros diarios por ruta** = suma de `pasajeros_total` de las 17 horas de salida (4–20 h) del dataset de E1: viajes válidos con dato de
  pasajeros y ≤ 300 (`pax_ok`). Coincide exactamente con el total de `pax_ok` de `progvehiculos` (42.166.279 pasajeros; no hay ningún viaje
  válido con salida fuera de 4–20 h). Los dos días excluidos por R5 (2024-09-06 y 2024-09-22, caída simultánea del 80 % en las tres rutas)
  se dejan vacíos en todas las correlaciones: si se incluyeran, inflarían todos los coeficientes.
- **Parte 1 (correlación).** Matrices de Pearson 3 × 3 de los pasajeros diarios en niveles, en diferencias de 7 días (quita tendencia y ciclo
  semanal), desestacionalizados (resta la media de cada día de la semana por ruta) y de la media móvil de 28 días (tendencia). Además:
  desvío relativo frente al nivel esperado (B1 diario = media de las 8 semanas anteriores del mismo día de la semana), correlación por tipo
  de día, perfil horario laboral (media de pasajeros por hora de salida), correlación día a día de los vectores de participación horaria,
  correlación cruzada con rezago de 1 día (y parcial, controlando el propio ayer) y choques comunes (días en que las tres rutas quedan a la vez
  bajo su nivel esperado), clasificados por calendario.
- **Parte 2 (modelos).** Mismo protocolo que E1: 12 pliegues mensuales de 2025 (entrenamiento estrictamente anterior a cada mes),
  horizontes `h = 1` y `h = 7` (solo rezagos ≥ 7 días), LightGBM Poisson sobre `pasajeros_total` con los hiperparámetros fijos de E1
  (600 árboles, tasa 0,03, 31 hojas, `min_child_samples` 40, submuestreo 0,8/0,8, λ = 1) y las mismas variables de E1 en el mismo orden.
  Variantes: **V1** un modelo conjunto con `idruta` como variable categórica (reproduce la variante (a) de E1); **V2** tres modelos
  independientes, uno por ruta, con las mismas variables sin `idruta`; **V3** un modelo conjunto **sin** `idruta` (mide lo que aporta
  saber la ruta); **V4** = V1 + demanda rezagada de las otras rutas: `lag7` y media de 4 semanas de la misma hora de las tres rutas
  (`pax_lag7_*`, `pax_m4sem_*`; la columna de la propia ruta duplica una variable ya existente, así cada columna significa lo mismo en
  todas las filas), el desvío relativo de las otras dos rutas la semana pasada en esa hora (`otras_rel_lag7_hora` = Σ lag7 / Σ m4sem − 1) y
  en el total del día (`otras_rel_lag7_dia`); con `h = 1` se añaden `lag1` de las tres rutas y los desvíos de ayer frente a hace 8 días
  (`otras_rel_lag1_hora`, `otras_rel_lag1_dia`). Línea base **B1 por ruta** (promedio de 8 semanas, misma ruta, hora y día de la semana,
  con el relleno B3 de E1). Métricas WAPE y MAE globales, por ruta, por tipo de día, por ruta × tipo de día, por mes y sobre el total diario;
  comparación pareada por pliegue (diferencia de WAPE mensual, prueba t pareada y Wilcoxon sobre 12 meses) y tiempo de entrenamiento.

## 2. Parte 1 · Correlación entre rutas

### 2.1 Pasajeros diarios

Correlación de Pearson entre rutas (1.094 días; 1.066 para el desvío frente a B1, que necesita 8 semanas previas):

| | **Niveles** | | | | **Diferencias de 7 días** | | | | **Desestacionalizada** | | |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | SILENCIO | CRA 54 | CL 72 | | SILENCIO | CRA 54 | CL 72 | | SILENCIO | CRA 54 | CL 72 |
| SILENCIO | 1,00 | 0,98 | 0,96 | | 1,00 | 0,96 | 0,93 | | 1,00 | 0,96 | 0,92 |
| CRA 54 | 0,98 | 1,00 | 0,97 | | 0,96 | 1,00 | 0,95 | | 0,96 | 1,00 | 0,94 |
| CL 72 | 0,96 | 0,97 | 1,00 | | 0,93 | 0,95 | 1,00 | | 0,92 | 0,94 | 1,00 |

| Par de rutas | Niveles | Dif. 7 días | Desestacionalizada | Media móvil 28 días (tendencia) | Desvío frente a B1 | Niveles, solo laborales | Solo sábados | Solo domingos/festivos |
|---|---|---|---|---|---|---|---|---|
| SILENCIO – CRA 54 | 0,98 | 0,96 | 0,96 | 0,97 | 0,94 | 0,93 | 0,90 | 0,81 |
| SILENCIO – CL 72 | 0,96 | 0,93 | 0,92 | 0,92 | 0,90 | 0,87 | 0,81 | 0,75 |
| CRA 54 – CL 72 | 0,97 | 0,95 | 0,94 | 0,93 | 0,93 | 0,90 | 0,83 | 0,81 |
| **Media de los tres pares** | **0,97** | **0,94** | **0,94** | **0,94** | **0,93** | 0,90 | 0,85 | 0,79 |

- La correlación en niveles (0,97) está inflada por el calendario (los domingos y festivos bajan en las tres rutas), pero **casi no cae al
  quitar el ciclo semanal y la tendencia**: 0,94 en diferencias de 7 días y 0,94 desestacionalizada. Incluso dentro de un mismo tipo de día
  (solo laborales) los niveles correlacionan 0,87–0,93.
- La **tendencia** es común: media móvil de 28 días con 0,92–0,97. Las tres rutas cayeron entre 2023 y 2025 (media diaria: SILENCIO de
  11.389 a 9.410 pasajeros, −17,4 %; CRA 54 de 23.329 a 19.596, −16,0 %; CL 72 de 7.215 a 6.261, −13,2 %). La única señal «local» de este
  bloque es que CL 72 cae algo menos (y por eso sus correlaciones con las otras dos son las más bajas, 0,92–0,93).
- El **desvío diario frente a lo esperado** (pasajeros / B1 − 1, desviación típica ≈ 20 % en las tres rutas) correlaciona 0,90–0,94; su
  primer componente principal explica el **95,1 %** de la varianza (96,2 % en las diferencias de 7 días). Es decir, los «errores» de la
  práctica manual son casi un único choque común a las tres rutas, no tres ruidos independientes.

### 2.2 Perfil horario

| Par de rutas | Perfil medio laboral (17 horas) | Perfil sábado | Perfil domingo/festivo | Participación horaria día a día (media) | … (percentil 10) | Covariación entre días de la forma horaria |
|---|---|---|---|---|---|---|
| SILENCIO – CRA 54 | 0,91 | 0,93 | 0,98 | 0,84 | 0,77 | 0,40 |
| SILENCIO – CL 72 | 0,98 | 0,98 | 0,99 | 0,85 | 0,76 | 0,27 |
| CRA 54 – CL 72 | 0,95 | 0,96 | 0,97 | 0,83 | 0,74 | 0,31 |

- La **forma del día es casi la misma** en las tres rutas (correlación del perfil medio 0,91–0,98): pico de las 5 h (del 10 % al 15 % de los
  pasajeros del día en una sola hora de salida), valle de 10–11 h, segundo pico de 13–14 h y caída desde las 16 h. CRA 54 tiene el pico
  matinal menos concentrado (10 % frente a 15 % en SILENCIO), de ahí que su correlación con SILENCIO sea la más baja (0,91). Las tres rutas
  mueven niveles muy distintos (CRA 54 ≈ 2 × SILENCIO ≈ 3 × CL 72), pero la participación de cada hora es casi idéntica.
- Día a día, los vectores de participación horaria de dos rutas correlacionan 0,83–0,85 en promedio (el 90 % de los días por encima de
  0,74). En cambio, **las desviaciones de la forma horaria respecto a su media covarían poco entre rutas (0,27–0,40)**: que una ruta
  concentre más pasajeros a las 6 h que de costumbre apenas dice nada de lo que hace otra ruta esa misma hora. La forma intradía depende
  sobre todo de la oferta despachada en cada franja (cuántos buses salieron), que es local.
- **Hora a hora** (misma hora del mismo día, residuo tras quitar la media por ruta × hora × día de la semana) la correlación entre rutas baja
  a 0,61–0,72 (SILENCIO – CRA 54 0,72; CRA 54 – CL 72 0,64; SILENCIO – CL 72 0,61): el choque común diario sigue ahí, pero a la escala de la
  franja se mezcla con el ruido de la oferta de cada ruta. Es la escala en la que trabaja el modelo de la parte 2.

### 2.3 ¿La desviación de una ruta predice la de otra?

Correlación cruzada con rezago de 1 día (fila = ruta hoy, columna = ruta ayer):

| Serie | Autocorrelación propia (diagonal) | Cruzada con las otras rutas | Parcial (controlando el propio ayer) |
|---|---|---|---|
| Desestacionalizada | 0,44 – 0,52 | 0,42 – 0,48 | −0,13 … +0,17 (media 0,02) |
| Desvío frente a B1 | 0,39 – 0,43 | 0,36 – 0,41 | −0,05 … +0,12 (media 0,04) |
| Diferencias de 7 días | véase `tablas.md` | | |

Lo que pasó ayer en otra ruta correlaciona con lo que pasa hoy en la propia (0,36–0,48), pero **solo porque también correlaciona el propio
ayer**: una vez conocida la desviación de la propia ruta, la de las otras no añade casi nada (correlación parcial entre −0,13 y +0,17,
sin signo consistente). El choque común ya está en los rezagos propios.

### 2.4 Choques comunes

Desvío diario frente a B1 (1.066 días). Si las rutas fueran independientes, las tres quedarían bajo lo esperado el 7,6 % de los días
(producto de las tres probabilidades marginales, 42–43 %); **ocurre el 27,3 %** (3,6 veces más). Las tres por encima: 41,7 % frente a
19,1 %. Las tres más de 10 % por debajo: 11,6 % de los días; alguna de las tres: 25,3 %.

| Categoría del día | Días | % con las tres bajo lo esperado | % con las tres > 10 % abajo | Desvío medio | Correlación media del desvío entre rutas |
|---|---|---|---|---|---|
| Laboral ordinario | 684 | 21,1 % | 4,8 % | +5,6 % | 0,89 |
| Sábado | 142 | 18,3 % | 4,9 % | +1,2 % | 0,72 |
| Domingo | 140 | 20,7 % | 3,6 % | +1,4 % | 0,54 |
| Festivo (entre semana o sábado) | 51 | 98,0 % | 96,1 % | −56,9 % | 0,95 |
| Carnaval | 12 | 91,7 % | 66,7 % | −35,4 % | 0,96 |
| Semana Santa (lunes a sábado no festivo) | 14 | 92,9 % | 71,4 % | −21,7 % | 0,90 |
| Navidad / Año Nuevo (24 dic – 2 ene) | 23 | 78,3 % | 52,2 % | −16,9 % | 0,93 |

- Los choques comunes **son el calendario**: los 15 peores días (desvío medio de −67 % a −89 %) son todos festivos o Carnaval (1 de enero,
  Jueves y Viernes Santo, 25 de diciembre, lunes y martes de Carnaval, 8 de diciembre…). B1 no los anticipa porque promedia 8 semanas
  normales; el modelo de E1 sí, con las variables de calendario.
- Fuera del calendario quedan **33 días laborales ordinarios (4,8 %)** con las tres rutas más de 10 % por debajo, casi todos en grupos que
  coinciden con vacaciones o recesos escolares (lista completa en `tablas.md`): comienzo de enero (3, 4 y 10 de enero de 2024; 3, 9 y 10 de
  enero de 2025), 30 de mayo a 18 de junio de 2024 (diez días laborales, −12 % a −33 %, primera temporada de lluvias y cierre del año escolar),
  junio-julio (8 y 15 de junio de 2023; 10 y 19 de junio, 9 y 29 de julio de 2025, estos tres últimos de −25 % a −46 %), la semana de receso
  de octubre (10 y 12 de octubre de 2023; 9 a 11 de octubre de 2024; 7, 8 y 10 de octubre de 2025) y días sueltos (15 de marzo de 2023,
  25 de septiembre de 2024 y el viernes 5 de julio de 2024, −40 % en las tres rutas, que no figura ni en festivos ni en `novedades_viales`).
  *(Texto corregido en la verificación: la versión anterior citaba solo 14 de los 33 días.)*
  El desvío medio positivo de los laborales ordinarios (+5,6 %) es el reverso: B1 mezcla festivos en su promedio y subestima los días normales.
- En los días laborales ordinarios el desvío sigue correlacionando 0,89 entre rutas; en domingos, 0,54: la parte «local» del ruido es
  mayor los domingos (pocos viajes, oferta irregular).

### 2.5 Interpretación

Las tres rutas están gobernadas por los **mismos factores**: el calendario (día de la semana, festivos, Carnaval, Semana Santa, vacaciones y
fin de año explican casi todos los choques grandes), la misma tendencia descendente y un choque común residual que explica el 95 % de la
varianza de los desvíos. Lo **local** es pequeño y se concentra en (i) el nivel (CRA 54 mueve el doble que SILENCIO y el triple que CL 72),
(ii) una tendencia algo distinta en CL 72, (iii) la forma horaria día a día (covariación 0,3–0,4), que refleja la oferta despachada en
cada franja, y (iv) el ruido de los domingos. Para el pronóstico esto sugiere que un modelo conjunto con la ruta como desplazador de nivel
debe funcionar tan bien como tres modelos, y que la información de las otras rutas es redundante con los rezagos propios (sección 2.3).
Eso es exactamente lo que se comprueba en la parte 2.

## 3. Parte 2 · Modelo conjunto frente a modelo por ruta

### 3.1 Resultados (pasajeros por hora de salida, 2025, 12 pliegues mensuales)

| Variante | Variables (h=7 / h=1) | WAPE h=7 | WAPE h=1 | MAE h=7 | MAE h=1 | WAPE del total diario, h=7 | Entrenamiento h=7 | Entrenamiento h=1 |
|---|---|---|---|---|---|---|---|---|
| B1 manual por ruta (8 semanas) | — | 20,04 % | 20,04 % | 138,6 | 138,6 | 12,8 % | < 1 s | < 1 s |
| V1 conjunto, ruta categórica (= E1 (a)) | 67 / 82 | 14,40 % | 14,10 % | 99,6 | 97,5 | 5,5 % | 64 s | 76 s |
| V2 un modelo por ruta (3 modelos) | 66 / 81 | **14,25 %** | **14,03 %** | **98,5** | **97,0** | 5,5 % | 105 s | 112 s |
| V3 conjunto sin variable ruta | 66 / 81 | 14,48 % | 14,09 % | 100,1 | 97,5 | 5,7 % | 65 s | 73 s |
| V4 conjunto + demanda rezagada de otras rutas | 75 / 95 | 14,42 % | 14,07 % | 99,7 | 97,3 | 5,6 % | 75 s | 85 s |

V1 reproduce **exactamente** la variante (a) de E1 (14,40 % y 14,10 %; por ruta 16,0 / 12,0 / 19,3 %): mismas variables en el mismo orden,
mismos parámetros, misma semilla. Los tiempos son de entrenamiento puro (suma de los 12 pliegues; en V2, de los 36 modelos).

**Por ruta** (WAPE; MAE entre paréntesis):

| Variante | h | SILENCIO | CRA 54 | CL 72 |
|---|---|---|---|---|
| B1 manual | 7 y 1 | 21,5 % (119,1) | 18,0 % (207,2) | 24,3 % (89,6) |
| V1 conjunto | 7 | 16,0 % (88,8) | 12,0 % (138,8) | 19,3 % (71,2) |
| V2 por ruta | 7 | 15,9 % (87,9) | 11,9 % (137,3) | 19,1 % (70,4) |
| V3 conjunto sin ruta | 7 | 16,2 % (89,4) | 12,1 % (139,6) | 19,4 % (71,4) |
| V4 conjunto + otras rutas | 7 | 16,1 % (88,9) | 12,1 % (139,2) | 19,3 % (71,0) |
| V1 conjunto | 1 | 15,7 % (86,8) | 11,7 % (135,3) | 19,1 % (70,4) |
| V2 por ruta | 1 | 15,6 % (86,6) | 11,7 % (134,7) | 19,0 % (69,8) |
| V3 conjunto sin ruta | 1 | 15,7 % (87,0) | 11,7 % (135,0) | 19,1 % (70,4) |
| V4 conjunto + otras rutas | 1 | 15,7 % (86,9) | 11,7 % (134,8) | 19,1 % (70,2) |

**Por tipo de día** (WAPE, h = 7; h = 1 entre paréntesis):

| Variante | Laboral | Sábado | Domingo/festivo |
|---|---|---|---|
| B1 manual | 17,6 % | 15,1 % | 48,6 % |
| V1 conjunto | 13,9 % (13,6 %) | 13,6 % (13,4 %) | 20,2 % (19,8 %) |
| V2 por ruta | 13,7 % (13,5 %) | 13,4 % (13,2 %) | 20,1 % (19,8 %) |
| V3 conjunto sin ruta | 14,0 % (13,6 %) | 13,7 % (13,4 %) | 20,2 % (19,8 %) |
| V4 conjunto + otras rutas | 13,9 % (13,5 %) | 13,7 % (13,5 %) | 20,3 % (19,9 %) |

- Las cuatro variantes LightGBM están **a menos de 0,3 puntos unas de otras** en el global, por ruta, por tipo de día y por franja; hasta
  0,4 puntos por ruta × tipo de día y hasta 2,2 puntos en un mes concreto (agosto, `h = 7`; véase `tablas.md`). Todas quedan a 5,6–6,0 puntos
  de B1. *(Corregido en la verificación: antes decía «0,2 puntos en todas las desagregaciones, incluido el mes».)* La celda más difícil sigue siendo CL 72 en domingo/festivo:
  B1 52,9 %, V1 27,9 %, V2 27,6 %. Por franja (h = 7) V2 es algo mejor por la mañana (4–8 h: 11,9 % frente a 12,2 %) y algo peor por la
  tarde (16–20 h: 18,7 % frente a 18,6 %).
- Otras métricas (h = 7): RMSE 147,9 (V1), 146,8 (V2), 148,9 (V3), 148,1 (V4); sesgo medio −2,3, +0,8, −3,9 y −2,6 pasajeros por franja; la
  **devianza de Poisson** (criterio de entrenamiento) es 31,17 (V1), 31,23 (V2), 31,45 (V3) y 31,23 (V4): en la métrica que optimizan los
  modelos, V2 **no** es mejor que V1. En el total diario por ruta V2 gana en SILENCIO y CRA 54 (5,85 % y 4,94 % frente a 5,93 % y 5,10 %)
  y pierde en CL 72 (6,63 % frente a 6,39 %).

### 3.2 ¿Son reales las diferencias? Comparación pareada por pliegue

Diferencia de WAPE mensual frente a V1 (12 meses de 2025; negativo = mejor que V1):

| Comparación | h = 7: dif. media ± desv. | meses mejor / peor | p (t pareada / Wilcoxon) | h = 1: dif. media ± desv. | meses mejor / peor | p (t / Wilcoxon) |
|---|---|---|---|---|---|---|
| V2 por ruta frente a V1 | −0,14 ± 0,52 pp | 8 / 4 | 0,36 / 0,62 | −0,06 ± 0,37 pp | 4 / 8 | 0,57 / 0,47 |
| V3 sin ruta frente a V1 | +0,08 ± 0,18 pp | 3 / 9 | 0,18 / 0,11 | −0,01 ± 0,05 pp | 5 / 7 | 0,70 / 1,00 |
| V4 + otras rutas frente a V1 | +0,01 ± 0,13 pp | 4 / 8 | 0,70 / 0,30 | −0,03 ± 0,09 pp | 8 / 4 | 0,26 / 0,42 |
| B1 frente a V1 | +5,73 ± 3,43 pp | 0 / 12 | < 0,001 / < 0,001 | +6,03 ± 3,33 pp | 0 / 12 | < 0,001 / < 0,001 |
| V2 frente a V1, solo SILENCIO | −0,15 ± 0,74 pp | 6 / 6 | 0,50 / 0,79 | −0,02 ± 0,71 pp | 4 / 8 | 0,94 / 0,30 |
| V2 frente a V1, solo CRA 54 | −0,12 ± 0,52 pp | 7 / 5 | 0,42 / 0,38 | −0,06 ± 0,33 pp | 6 / 6 | 0,57 / 1,00 |
| V2 frente a V1, solo CL 72 | −0,20 ± 0,38 pp | 9 / 3 | 0,10 / 0,11 | −0,15 ± 0,26 pp | 8 / 4 | 0,07 / 0,08 |

Ninguna diferencia entre variantes LightGBM es significativa: la ventaja global de V2 (0,14 puntos con `h = 7`) es la cuarta parte de la
dispersión mensual (0,52 puntos) y con `h = 1` V2 pierde en 8 de los 12 meses. El único patrón consistente es **CL 72**, donde el modelo
propio gana en 9 de 12 meses (`h = 7`) y 8 de 12 (`h = 1`) por 0,15–0,20 puntos (p ≈ 0,07–0,11): es la ruta con menos viajes por franja y
con la utilización de flota más particular (E1, sección 9), y su modelo propio da más peso a la oferta rezagada (abajo). La figura 7
muestra las cuatro curvas mensuales superpuestas; solo en agosto se separan (V2 15,6 % frente a 17,2 % de V1), un mes con la oferta de
vacaciones cambiando.

### 3.3 Qué usan los modelos

- **V1** (h = 7, % de la ganancia): `pasajeros_total_m4sem` 59,4 %, `pasajeros_total_b1` 21,2 %, `lag7` 3,8 %, `tipo_dia` 3,0 %, `festivo`
  1,9 %, `roll7_h7` 1,9 %, `viajes_validos_m4sem` 1,5 %. `idruta` no aparece entre las 15 primeras: el nivel de cada ruta ya viene en sus
  rezagos, por eso **V3 (sin ruta) solo pierde 0,08 puntos** con `h = 7` y nada con `h = 1`.
- **V2**: los tres modelos usan la misma columna vertebral (media de 4 semanas + B1 + tipo de día), pero con pesos distintos: CRA 54 es
  casi solo `m4sem` (54,4 %) + B1 (16,6 %); SILENCIO y CL 72 reparten más y dan peso a la **oferta rezagada** (`viajes_validos_roll28_h7`
  6,0 % y 6,4 %, `viajes_validos_b1` 3,3 % en CL 72) y en CL 72 B1 pesa tanto como `m4sem` (29,3 % frente a 31,0 %). Esa es la pequeña
  «estructura local» que el modelo conjunto solo puede aproximar con interacciones.
- **V4**: las 8 variables cruzadas (`h = 7`) suman el **0,8 %** de la ganancia (la mayor, `pax_m4sem_cra54`, 0,24 %; `otras_rel_lag7_dia`
  0,21 %); con `h = 1` las 13 suman el 1,0 % (`pax_lag1_cra54` 0,21 %). El modelo las ignora porque la información que traen ya está en los
  rezagos propios: la parte 1 mostró que el desvío de las otras rutas tiene correlación parcial ≈ 0 con el propio una vez conocido el propio
  pasado, y el desvío de la semana pasada (propio o ajeno) apenas predice el de esta semana (correlación con el desvío de hoy frente a la
  media de 4 semanas, por hora de salida: 0,07 en 2025 y 0,14 en 2023–2025 para el propio; 0,04 y 0,14 para el de las otras rutas;
  cifras recalculadas en la verificación, la versión anterior daba solo «0,07» sin definición).

### 3.4 Semana de ejemplo (figura 6)

Semana del 24 al 30 de marzo de 2025 (lunes 24 festivo), `h = 7`. WAPE de la semana: SILENCIO V1 15,7 %, V2 14,9 %, B1 24,2 %; CRA 54 V1
10,1 %, V2 10,4 %, B1 19,6 %; CL 72 V1 18,0 %, V2 17,9 %, B1 25,6 %. Las curvas de V1 y V2 se superponen hora a hora en las tres rutas;
ambas anticipan el festivo (B1 pronostica un lunes normal, 2–3 veces la demanda real) y las dos subestiman los picos más altos de las 5 h
de CRA 54 (2.900 reales frente a ≈ 2.600 previstos) y el valle del jueves por la tarde.

## 4. Conclusiones

1. **Las tres rutas se mueven juntas.** Correlación de los pasajeros diarios de 0,96–0,98 en niveles, 0,93–0,96 en diferencias de 7 días,
   0,92–0,96 desestacionalizada y 0,92–0,97 en la tendencia; el perfil horario es casi idéntico (0,91–0,98). El 95 % de la varianza de los
   desvíos frente a lo esperado es un componente común, y las tres rutas caen a la vez el 27 % de los días (8 % si fueran independientes).
   Ese componente común es, casi por completo, el **calendario** (festivos, Carnaval, Semana Santa, fin de año: 96 % de los festivos tienen
   a las tres rutas más de 10 % por debajo) más una tendencia compartida (−13 % a −17 % de 2023 a 2025). Lo local es el nivel, la forma
   horaria de cada día (oferta) y el ruido de los domingos.
2. **Un modelo para las tres rutas es tan bueno como uno por ruta.** V2 mejora a V1 en 0,14 puntos de WAPE con `h = 7` (14,25 % frente a
   14,40 %) y 0,06 con `h = 1`, dentro del ruido entre pliegues (p = 0,36 y 0,57; 8/12 y 4/12 meses mejor), con la misma devianza de Poisson
   y 1,6 veces el tiempo de entrenamiento (105 s frente a 64 s) y tres modelos que mantener en lugar de uno. `resultados.json` marca V2
   como «mejor» por WAPE medio (14,14 % frente a 14,25 %), pero operativamente son el mismo modelo. Si se quisiera un modelo propio, el único
   candidato con señal consistente es CL 72 (−0,2 puntos, 9 de 12 meses).
3. **La variable ruta aporta poco** (V3: +0,08 puntos con `h = 7`, 0 con `h = 1`): los rezagos propios ya identifican la ruta.
4. **La información de las otras rutas no ayuda** (V4 = V1 ± 0,03 puntos; las variables cruzadas reciben < 1 % de la ganancia). Es coherente
   con la parte 1: el choque común ya está en los rezagos propios (correlación parcial con rezago de 1 día ≈ 0) y los choques no explicados por
   el calendario (lluvias, eventos) no son predecibles con una semana de antelación desde ninguna ruta.
5. **Recomendación:** conservar el modelo conjunto de E1 (V1). Donde sí hay margen no es en separar por ruta sino en lo que E1 ya señaló:
   la oferta programada como entrada y el tratamiento de los domingos/festivos de CL 72.

## 5. Figuras

`fig1_dispersion_diaria.png` (pasajeros diarios por pares de rutas, coloreados por tipo de día, con las correlaciones de cada par),
`fig2_heatmaps_correlacion.png` (niveles, diferencias de 7 días, desestacionalizada, tendencia de 28 días), `fig3_series_normalizadas.png`
(índice 100 = media de 2023, media móvil de 7 días; franjas grises = Carnaval), `fig4_perfil_horario.png` (perfil laboral absoluto, en
participación y su correlación), `fig5_wape_ruta_variante.png` (WAPE por ruta y variante, `h = 7` y `h = 1`), `fig6_semana_ejemplo_rutas.png`
(24–30 de marzo de 2025 por ruta: real, V1, V2 y B1), `fig7_wape_mensual.png` (WAPE mensual por variante, `h = 7`). Los colores de ruta
(azul, naranja, aqua) y de variante se eligieron con una paleta validada para deficiencias de visión del color (la paleta azul/rojo/verde
del EDA no distingue CRA 54 de CL 72 en deuteranopía), por eso difieren de las figuras anteriores.

## 6. Limitaciones y advertencias

1. Con 12 pliegues, diferencias de 0,1–0,2 puntos de WAPE no son detectables (desviación mensual 0,4–0,5 puntos): «no significativo» no
   demuestra igualdad, pero sí que la ganancia de separar por ruta es, como mucho, de ese orden.
2. V2 usa los hiperparámetros de E1 (ajustados para el conjunto) en modelos con un tercio de los datos; un ajuste por ruta (menos hojas,
   más regularización) podría favorecer algo a V2, sobre todo en CL 72. No se probó para respetar la comparación «mismas variables y
   parámetros».
3. La selección de la «mejor variante» se hace sobre los mismos pliegues que se reportan (optimista), igual que en E1.
4. Las correlaciones de la parte 1 son de la demanda **observada**, que depende de la oferta (elasticidad 0,17–0,25 en el EDA): parte del
   co-movimiento puede venir de decisiones de despacho comunes (recortes simultáneos en festivos y vacaciones), no solo de la demanda.
5. El nivel «esperado» para los choques comunes es el B1 diario (8 semanas), que mezcla festivos; por eso los días laborales ordinarios
   quedan en promedio un 5,6 % por encima de lo esperado y el umbral del 10 % es conservador para ellos.
6. Las variables cruzadas de V4 son un diseño concreto (lag7, media de 4 semanas y desvíos relativos de las otras rutas); otras
   construcciones (p. ej. el residuo de un modelo de las otras rutas) podrían comportarse distinto, pero la correlación parcial ≈ 0 de la
   parte 1 sugiere que no.
7. Heredado de E1: hora 21 ausente, R5 excluidos, último día de mes sin conteos (no afecta a `pasajeros_total`).

## 7. Archivos

`run.py` (reproduce todo; `E6_RAPIDO=1` ejecuta una prueba de 2 pliegues y 30 árboles en otra carpeta), `resultados.json` (esquema del
protocolo: variantes con métricas globales, por ruta, tipo de día, franja, mes, ruta × tipo de día y total diario, importancias, comparación
pareada por pliegue, todas las matrices de correlación, choques comunes y tiempos), `correlaciones.json` (esquema pedido: `diaria_niveles`,
`diaria_dif7`, `diaria_desestacionalizada`, `tendencia_28d`, `perfil_horario`, `rutas`, `modelos`, `conclusiones`, más `extras`),
`tablas.md` (todas las tablas en formato español, generadas por `run.py`), `predicciones_2025.parquet` (18.615 filas = 3 rutas × 365 días × 17 horas, en formato ancho: ruta, día, hora,
tipo de día, real, B1 y las predicciones de V1–V4 para `h = 7` y `h = 1` como columnas), `run.log` y las figuras `fig1`–`fig7`.

## 8. Verificación (verificador adversarial, 2026-10-05)

**Veredicto: confiable con reservas.** Se revisaron `run.py`, este README y `resultados.json`, y se recalcularon de forma independiente
(código propio, sin reentrenar, ≈ 2 min) las cifras principales desde `datos/progvehiculos.parquet`, el dataset de E1 y `predicciones_2025.parquet`.

- **Protocolo y fuga.** Pliegues mensuales de 2025 con entrenamiento estrictamente anterior, hiperparámetros fijos de E1 (sin parada temprana ni
  selección en el pliegue de prueba), B1 por ruta idéntica a la de E1 (diferencia máxima 0). Los rezagos de E1 (`lag7`, `lag14`, `lag28`, `m4sem` =
  media de 7/14/21/28 días, `b1` = 8 semanas previas del mismo día) coinciden exactamente con desplazamientos recalculados. Prueba de perturbación
  de las variables cruzadas de V4: al alterar la demanda desde el 1 de junio de 2025, ninguna variable `h = 7` cambia antes del 8 de junio y
  ninguna `h = 1` antes del 2 de junio → **sin fuga**. La única selección optimista es la «mejor variante» sobre los mismos pliegues (ya declarada).
- **Confirmado** (recalculado): total de 42.166.279 pasajeros y series diarias idénticas a las de E1; correlaciones medias 0,97 (niveles),
  0,94 (dif. 7 días), 0,94 (desestacionalizada), 0,94 (tendencia), 0,93 (desvío frente a B1); componente común 95,1 % (96,2 % en dif. 7 días);
  27,3 % de días con las tres rutas bajo lo esperado frente a 7,6 % si fueran independientes; 11,6 % con las tres > 10 % abajo; caída
  2023→2025 de −17,4 / −16,0 / −13,2 %; perfil horario 0,91–0,98; correlación parcial con rezago de 1 día media 0,02–0,04; WAPE `h = 7`
  B1 20,04 %, V1 14,40 %, V2 14,25 %, V3 14,48 %, V4 14,42 % (y `h = 1` 14,10 / 14,03 / 14,09 / 14,07 %), por ruta, por tipo de día, por franja,
  MAE, RMSE, devianza de Poisson (31,17 frente a 31,23), total diario y las pruebas pareadas por pliegue (V2 frente a V1: −0,14 ± 0,52 puntos,
  8/4 meses, p = 0,36 / 0,62; CL 72: 9/3 meses, p = 0,10 / 0,11). V1 reproduce las métricas de la variante (a) de E1 (14,399 % y 14,098 %;
  por ruta idénticas); la comparación fila a fila no es posible porque `E1/predicciones_2025.parquet` guarda la variante (c).
- **Corregido** en este README: (1) los 15 peores días van de −67 % a −89 % (no −64 %); (2) los 33 días laborales ordinarios con las tres
  rutas > 10 % abajo no son solo los 14 citados: también hay grupos en enero de 2025, junio-julio de 2023 y 2025 y en la semana de receso de
  octubre de 2023, 2024 y 2025; el bloque mayo-junio de 2024 tiene diez días (no nueve) de −12 % a −33 %; (3) las variantes no están «a 0,2 puntos
  en todas las desagregaciones»: hasta 0,3 por ruta y tipo de día, 0,4 por ruta × tipo de día y 2,2 en agosto; (4) sesgo de V3 −3,9 (no −4,0);
  (5) la correlación «0,07» entre el desvío de la semana pasada y el de hoy solo se reproduce en 2025; en 2023–2025 es 0,14 (la conclusión
  cualitativa, «apenas predice», se mantiene).
- **Reservas.** (a) Las figuras usan la paleta propia del autor (azul #2a78d6, naranja #eb6834, aqua #1baf7a), no los colores de ruta acordados
  por el equipo (SILENCIO #2f6fb3, CRA 54 #d9731a, CL 72 #6a3d9a): CL 72 aparece en verde-aqua y no en morado; no se regeneraron. (b) Solo se
  modela `pasajeros_total`; no se reporta la métrica de decisión en buses del protocolo, así que «V1 ≈ V2» está probado en pasajeros, no en buses.
  (c) Con 12 pliegues la prueba pareada no detecta diferencias de 0,1–0,2 puntos (ya declarado). (d) No se verificaron la elasticidad 0,17–0,25
  del EDA ni la referencia a «E1, sección 9».
