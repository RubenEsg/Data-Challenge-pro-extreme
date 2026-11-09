# E1 · LightGBM sobre la unidad de decisión (ruta × día × hora de salida)

Experimento nocturno del 2026-10-04 según `experimentos/protocolo_evaluacion.md`. Reproducible con
`python experimentos/E1_lgbm_salida/run.py` desde la carpeta del proyecto (26,9 min, `n_jobs = 2`, semilla 42).

## 1. Qué se hizo

- **Conjunto de datos** `datos_modelado_salida.parquet`: 55.896 filas = 3 rutas × 1.096 días (2023-01-01 a 2025-12-31) × 17 horas de salida
  programada (4 a 20 h). **No existe ninguna salida válida a las 21 h en los tres años**, por eso la rejilla termina a las 20 h aunque el
  protocolo diga 4–21 h; la franja de evaluación «16–21 h» contiene las salidas de 16 a 20 h.
- **Objetivos** (reglas R1, R3, R4, R9): `pasajeros_total` (suma de `numeropasajeros` de los viajes válidos con dato y ≤ 300, ceros incluidos;
  42.166.279 pasajeros en el periodo), `pasajeros_por_viaje` (media sobre `limpios`), `carga_max` (mediana de `ocupacion_max` de los viajes limpios
  con `ocupacion_min ≥ −3` y `ocupacion_max ≤ 300`) y `viajes_validos`. Las franjas sin ningún viaje tienen 0 pasajeros y 0 viajes (dato real); los
  promedios quedan vacíos (2,5 % de las filas en `pasajeros_por_viaje`, 6,8 % en `carga_max`).
- **Variables**: calendario (`tipo_dia`, `dia_semana`, `mes`, `dia_mes`, `dia_anio`, `semana_anio`, `tendencia`, `festivo`, `vacaciones`, `quincena`
  = días 14–16, 29–31 y 1), calendario especial (`carnaval`, `carnaval_central` = lunes y martes, `semana_santa`, `jueves_viernes_santo`,
  `primero_enero`, `navidad`), eventos de `novedades_viales` (`partido_dia`, `partido_franja`, `evento_otro_dia`, `evento_otro_franja`; la franja
  afectada va de `hora_inicio − 3 h` a `hora_fin` porque una salida recoge pasajeros durante unas 4 h), y rezagos **de los cuatro objetivos**:
  `lag7/14/21/28`, media de las 4 mismas semanas (`m4sem`), media móvil de los días 7–13 y 7–34 atrás, B1 (8 semanas, misma hora y día de la
  semana) y su desviación, mismo día hace 364 días, totales diarios de pasajeros y viajes rezagados 7 y 14 días. Con `h = 1` se añaden `lag1`,
  `lag2`, la media de los últimos 7 días y los totales de ayer. **La oferta de la franja entra solo rezagada** (`viajes_validos_lag7`, `_m4sem`,
  `_b1`…), nunca la contemporánea.
- **R5**: 2024-09-06 y 2024-09-22 se enmascaran antes de calcular rezagos (un `lag7` que cae en ellos queda vacío y `m4sem` lo ignora) y se excluyen
  del entrenamiento y de las líneas base.
- **Protocolo**: 12 pliegues mensuales de 2025 (entrenamiento estrictamente anterior a cada mes), horizontes `h = 1` y `h = 7`, líneas base
  B1 (manual, 8 semanas), B2 (hace 7 días), B3 (perfil ruta × hora × tipo de día × mes del histórico de cada pliegue).
- **Variantes LightGBM** (600 árboles, tasa 0,03, 31 hojas, `min_child_samples` 40, submuestreo 0,8/0,8, λ = 1):
  (a) Poisson sobre `pasajeros_total` y (a') L2 como control; (b) modelos separados de `pasajeros_por_viaje` (L2) y `viajes_validos` (Poisson)
  multiplicados, con factor de calibración estimado en el histórico de cada pliegue (porque `pasajeros_total` incluye viajes fuera de `limpios`);
  (b*) la misma descomposición pero con los viajes realmente observados, como cota de cuánto error viene de no conocer la oferta; (c) sin los
  cuatro indicadores de novedades; (c') sin calendario especial; (d) búsqueda aleatoria de 20 combinaciones en 4 pliegues de `h = 7` (febrero, mayo,
  agosto, noviembre) re-evaluada en los 12 pliegues. Además un modelo L2 de `carga_max` para la métrica de decisión.

## 2. Resultados principales (pasajeros por hora de salida, 2025, 12 pliegues)

| Variante | WAPE h=1 | WAPE h=7 | MAE h=1 | MAE h=7 | RMSE h=7 |
|---|---|---|---|---|---|
| B1 manual (8 semanas) | 20,0 % | 20,0 % | 138,6 | 138,6 | 228,8 |
| B2 ingenua (hace 7 días) | 24,5 % | 24,5 % | 169,1 | 169,1 | 282,1 |
| B3 perfil histórico | 19,3 % | 19,3 % | 133,8 | 133,8 | 205,0 |
| (a) LightGBM Poisson | **14,1 %** | **14,4 %** | 97,5 | 99,6 | 147,9 |
| (a') LightGBM L2 (control) | 14,2 % | 14,7 % | 98,3 | 101,8 | 150,3 |
| (b) descompuesto: pasajeros/viaje × viajes previstos | 14,8 % | 15,0 % | 102,2 | 103,5 | 153,3 |
| (b*) descompuesto con oferta real (cota, no es pronóstico) | 13,2 % | 13,5 % | 91,0 | 93,1 | 139,0 |
| (c) Poisson sin indicadores de novedades | **14,1 %** | **14,4 %** | 97,3 | 99,5 | 147,7 |
| (c') Poisson sin calendario especial | 14,8 % | 15,9 % | 102,1 | 109,9 | 173,1 |
| (d) Poisson con hiperparámetros ajustados | 14,3 % | 14,5 % | 98,7 | 100,2 | 149,5 |

- El LightGBM Poisson reduce el error de la práctica manual (B1) de **20,0 % a 14,4 %** con horizonte de una semana (−28 % de error; MAE de
  139 a 100 pasajeros por franja) y la devianza de Poisson media de 62,7 a 31,2. El sesgo global es pequeño (−2,3 pasajeros por franja frente a
  +6,8 de B1). Agregado a **total diario por ruta** el WAPE baja a **5,5 %** (B1: 12,8 %).
- **El horizonte casi no importa**: `h = 1` solo mejora 0,3 puntos sobre `h = 7`. Saber lo que pasó ayer aporta poco frente a las cuatro mismas
  semanas anteriores: la programación semanal no pierde precisión por decidirse con una semana de antelación.
- **Poisson gana a L2** por 0,3 puntos en `h = 7` y es más estable en los meses con días atípicos (mejor manejo de la varianza proporcional a la media).
- **(b) descompuesto es peor que el total directo** (15,0 % frente a 14,4 %): multiplicar dos pronósticos suma errores y el modelo de viajes
  (WAPE 16,2 %) es el eslabón débil. Pero **con la oferta conocida** (b*) el error baja a 13,5 %: entre 1 y 1,5 puntos del error provienen de
  no saber cuántos buses saldrán realmente. En producción Sobusa conoce su programación, así que un modelo que reciba los viajes programados ×
  (1 − cancelación esperada) debería acercarse a esa cota.
- **Eventos (c)**: quitar partidos, Guacherna, Batalla y conciertos **no cambia nada** (14,38 % frente a 14,40 %, dentro del ruido; por eso
  `resultados.json` la marca como «mejor» por 0,02 puntos). Confirma la sección 5.4 del EDA: 8 partidos y 8 eventos en tres años no dejan señal
  aprovechable. **El calendario especial sí importa**: sin Carnaval, Semana Santa, 1 de enero y 25 de diciembre el WAPE sube a 15,9 % y el RMSE
  de 148 a 173.
- **Hiperparámetros (d)**: en los 4 pliegues de búsqueda la mejor combinación (63 hojas, 300 árboles, `min_child_samples` 150, λ = 20) daba
  13,43 % frente a 13,99 % de la base, pero **en los 12 pliegues queda en 14,50 %, peor que la base (14,40 %)**: la ganancia era sobreajuste a
  los meses de búsqueda. Los parámetros base se conservan; la búsqueda enseñó que las combinaciones con muchas hojas y poca regularización
  (127 hojas, λ = 0, tasa 0,1) empeoran hasta 15,3 %: el problema pide modelos **más simples**, no más capacidad.

### Desagregación de la variante Poisson (h = 7)

Cifras de la variante (c) —la guardada en `predicciones_2025.parquet`—; la variante (a) difiere como mucho en 0,1 puntos (Domingo/festivo 20,2 %).

| Ruta | B1 | LightGBM | | Tipo de día | B1 | LightGBM | | Franja | B1 | LightGBM |
|---|---|---|---|---|---|---|---|---|---|---|
| CRA 54 | 18,0 % | **12,0 %** | | Laboral | 17,6 % | **13,9 %** | | 4–8 h | 19,4 % | **12,2 %** |
| SILENCIO | 21,5 % | **16,0 %** | | Sábado | 15,1 % | **13,6 %** | | 9–15 h | 19,9 % | **14,5 %** |
| CL 72 | 24,3 % | **19,3 %** | | Domingo/festivo | 48,6 % | **20,1 %** | | 16–21 h | 21,7 % | **18,6 %** |

- La mayor ganancia está en **domingos y festivos** (de 48,6 % a 20,1 %): la media de 8 semanas mezcla domingos normales con festivos entre
  semana y nunca acierta un festivo. En los 17 festivos de 2025 el WAPE es 25,0 % frente a 145,8 % de B1; en los 4 días centrales de Carnaval,
  33,0 % frente a 96,8 %; en Semana Santa, 17,3 % frente a 65,5 %.
- CL 72 sigue siendo la ruta más difícil (19,3 %; 34 % en domingo/festivo por la tarde): menos viajes por franja (mediana 5, frente a 15 en CRA 54 y 7 en SILENCIO) y la utilización
  anómala de su flota (sección 9). Las **tardes (16–20 h)** son la franja peor en todas las rutas; ahí la oferta cambia más de un día a otro.
- Por mes (`h = 7`, variante (c) guardada en `predicciones_2025.parquet`): entre 12,6 % (febrero) y 16,7 % (agosto y diciembre; la variante (a)
  llega a 17,2 % en agosto); B1 oscila entre 13,9 % y 25,7 %. Junio–agosto y diciembre son los meses peores del modelo (vacaciones con oferta variable).

### Otros objetivos (h = 7; h = 1 entre paréntesis)

| Objetivo | B1 | B3 | LightGBM |
|---|---|---|---|
| `pasajeros_por_viaje` | 18,2 % | 17,3 % | **14,9 %** (14,6 %) — MAE 11,8 pasajeros |
| `carga_max` | 21,0 % | 18,8 % | **17,7 %** (17,4 %) — MAE 5,9 pasajeros a bordo |
| `viajes_validos` | 19,4 % | 18,9 % | **16,2 %** (15,9 %) — MAE 1,5 viajes |

La carga máxima es el objetivo más ruidoso (mediana de pocos viajes por franja): la ganancia sobre el perfil histórico B3 es de solo 1,1 puntos.

### Importancia de variables (Poisson, h = 7, % de la ganancia, promedio de 12 pliegues)

`pasajeros_total_m4sem` 60,2 %, `pasajeros_total_b1` 22,9 %, `tipo_dia` 2,8 %, `festivo` 2,1 %, `viajes_validos_m4sem` 1,8 %,
`pasajeros_total_lag7` 1,6 %, `pasajeros_total_roll7_h7` 1,6 %, `sd8sem` 0,7 %, `dia_anio` 0,6 %, `carnaval_central` 0,6 %. El modelo es,
en esencia, **la media de las 4 últimas semanas corregida por calendario**; la oferta rezagada aporta poco y los eventos nada.

## 3. Métrica de decisión

**Protocolo** (buses = ⌈`carga_max` / (50 × 0,85)⌉, comparado con el real; 17.248 horas de 2025 con carga observada):

| Pronóstico de `carga_max` | error medio (buses) | MAE | % sub-oferta | % sobre-oferta | % exacto |
|---|---|---|---|---|---|
| B1 manual | −0,049 | 0,182 | 11,6 % | 6,6 % | 81,8 % |
| B3 perfil | −0,001 | 0,155 | 7,8 % | 7,7 % | 84,6 % |
| LightGBM h=7 | −0,041 | 0,147 | **9,3 %** | 5,3 % | **85,4 %** |

Advertencia: como `carga_max` es la ocupación máxima mediana de **un** viaje (media 33,5; solo el 26,1 % de las horas supera 42,5), esta
métrica solo toma los valores 1 o 2 y mide si el bus de 50 basta, no cuántos buses despachar. Se añade la **traducción a salidas por hora**
de la sección 10.6 (`decision_complementaria.py`): salidas necesarias = ⌈`carga_max` × `viajes_validos` / 42,5⌉, con pronósticos de ambos
factores (media real 8,2 salidas por hora):

| Pronóstico | MAE (salidas) | WAPE | % horas con sub-oferta | % con sub-oferta de 2 o más | % exacto |
|---|---|---|---|---|---|
| B1 manual | 1,73 | 21,0 % | 36,4 % | 18,7 % | 25,3 % |
| LightGBM h=7 | **1,31** | **16,0 %** | 32,5 % | 14,9 % | 28,6 % |
| LightGBM h=7 con oferta conocida | 1,15 | 14,0 % | 30,7 % | 11,9 % | 32,1 % |

El modelo se equivoca en 1,3 salidas por hora en promedio (B1: 1,7) y es casi insesgado (+0,07 salidas). Esta traducción hereda el error del
pronóstico de viajes; con la programación conocida el MAE baja a 1,15.

## 4. Figuras

`fig1_wape_variantes.png` (WAPE por variante y horizonte), `fig2_wape_ruta_franja.png` (mapa ruta × tipo de día × franja, B1 frente a LightGBM),
`fig3_importancia.png`, `fig4_wape_mensual.png` (error por pliegue), `fig5_semana_ejemplo.png` (CRA 54, 10–16 de marzo de 2025: real, LightGBM
h = 7 y B1; se ve que el modelo sigue los picos de las 5 h y el valle del domingo pero subestima los picos más altos), `fig6_decision_buses.png`,
`fig7_hiperparametros.png`.

## 5. Limitaciones y advertencias

1. **La demanda observada depende de la oferta** (elasticidad 0,17–0,25 en el EDA). El modelo aprende pasajeros dados los buses que se enviaron;
   si Sobusa recorta salidas en una franja, los pasajeros que suben bajan algo (y la carga por bus sube más). Para simular escenarios hace falta
   un modelo con la oferta programada como entrada (ver b*) y la elasticidad estimada, no este pronóstico.
2. La selección «mejor variante» (c) sobre (a) es ruido (0,02 puntos); operativamente son el mismo modelo. La selección por WAPE medio de
   ambos horizontes sobre los mismos 12 pliegues que se reportan es optimista para la variante elegida (sin conjunto de prueba aparte).
3. El ajuste de hiperparámetros con 4 pliegues no generalizó; la elección de 600 árboles y 31 hojas sigue siendo un valor por defecto, no un óptimo.
4. `carga_max` por franja se basa en pocos viajes (mediana 6 con contadores consistentes) y excluye el 19,3 % de viajes con contadores
   inconsistentes (R9): es ruidoso y la métrica de decisión del protocolo, tal como está definida, apenas discrimina.
5. Hora 21 ausente; franja «16–21 h» = 16–20 h. Las medias móviles de 7 días de `h = 1` exigen 3 días con dato y las de 28 días, 10.
6. Los modelos guardados (`modelos/*.txt`) son los del último pliegue (entrenados hasta noviembre de 2025); para producción habría que
   reentrenar con todo 2025.
7. Tendencia (−8 %/año): los árboles no extrapolan; la caída la capturan los rezagos. En años con cambio brusco de nivel el modelo reaccionará
   con 1–4 semanas de retraso, igual que B1.
8. **Último día de cada mes sin conteos** (hallazgo de E2: los eventos GPS no cubren el último día del mes). `conteo_viajes` no tiene filas para esos
   viajes, así que `carga_max` está vacía en el 100 % de las filas del último día de mes (36 ruta-días y 612 filas de 2025) y esas horas quedan fuera
   de la evaluación de `carga_max` y de la métrica de decisión (17.248 horas en lugar de ~17.900). `pasajeros_total`, `pasajeros_por_viaje` y
   `viajes_validos` provienen de `progvehiculos.numeropasajeros` y **no** están afectados (media de 770 pasajeros por franja el último día frente a 754 el resto).
   Los rezagos de `carga_max` que caen en un fin de mes quedan vacíos (LightGBM los trata como faltantes).

## 6. Próximos pasos sugeridos

- **Modelo con oferta programada como entrada** (viajes programados × (1 − cancelación esperada por ruta × hora × tipo de día)): la cota (b*)
  dice que vale 1–1,5 puntos de WAPE y es lo que permite simular «¿qué pasa si mando 2 buses menos a las 10 h?».
- Pronosticar **`pasajeros_por_viaje` y `carga_max` condicionados al intervalo** (elasticidad), que es la pieza que convierte el pronóstico
  en decisión de frecuencia (sección 10.6).
- Modelos por ruta o con pesos por recencia (los últimos 12 meses pesan más) para CL 72 y para las tardes; cuantiles (p80/p90 de la carga) para
  dimensionar con margen en lugar de la mediana.
- Reemplazar `media_4sem` fija por una media ponderada aprendida y probar un `h = 7` que use también la semana del año anterior ajustada por tendencia.
- Verificar con `timbradas_anio` 2026 (R8) el perfil semanal previsto para enero–agosto de 2026 como comprobación externa.

## 7. Verificación independiente (2026-10-04)

Recalculado a partir de `predicciones_2025.parquet` y `datos_modelado_salida.parquet` con código propio (sin reentrenar): WAPE B1 20,04 %,
B2 24,45 %, B3 19,35 %; LightGBM (c) 14,08 % (h = 1) y 14,38 % (h = 7); total diario por ruta 5,50 % frente a 12,75 %; por ruta 12,0 / 16,0 / 19,3 %;
domingos y festivos 20,1 % frente a 48,6 %; festivos 25,0 % frente a 145,8 %; Carnaval (4 días) 33,0 % frente a 96,8 %; Semana Santa 17,3 % frente a 65,5 %;
métrica de decisión 85,4 % exacto y 9,3 % sub-oferta (B1 81,8 / 11,6 %); salidas por hora MAE 1,31 frente a 1,73. Todo coincide con las tablas anteriores.
Se corrigió el rango mensual (que mezclaba las variantes (a) y (c)) y se añadió la limitación 8 sobre el último día de mes.

## 8. Archivos

`run.py`, `decision_complementaria.py`, `resumen.py` (tablas del README), `datos_modelado_salida.parquet` (55.896 × 94), `predicciones_2025.parquet`
(37.230 filas: ruta, dia, hora, tipo_dia, real, prediccion, horizonte, más real/pred de los otros tres objetivos y la predicción B1),
`resultados.json`, `busqueda_hiperparametros.csv`, `modelos/lgbm_*_h{1,7}.txt` (Poisson total, pasajeros por viaje, viajes, carga máxima y la
variante ajustada), `run.log`, figuras `fig1`–`fig7`.
