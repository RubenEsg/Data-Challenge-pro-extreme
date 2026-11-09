# E12 · Comparación de modelos: selección conjunta, ensambles y recomendación para producción

**Pregunta.** Con el mismo protocolo de E11 (12 pliegues mensuales de 2025, h = 7, las mismas 18.615 franjas ruta × día × hora de salida y el tratamiento de atípicos de V4), ¿algún modelo o ensamble de las cuatro familias probadas (árboles, clásicos, redes y fundacionales) le gana a V4, el LightGBM de E11 (WAPE h = 7 = 13,94 %)? ¿Cuál gana según la regla fijada de antemano, resiste la corrección por comparaciones múltiples y la prueba en otro año, y cuál conviene llevar a producción en Sobusa?

**Respuesta corta.**
- **Ningún modelo individual le gana a V4.** Las mejoras salen de combinar familias: los 12 candidatos que cumplen la regla son ensambles o el híbrido V4 + Chronos-2.
- **Ganador según la regla: `ens_conj_c_nnls_todos`**, el apilamiento rodante NNLS sobre los 40 modelos individuales. La regla de selección y los diseños (a), (b) y (c) quedaron escritos a la 01:21 del 7-oct-2026 en el guion del flujo de E12, antes de cualquier resultado de las familias. En cambio, el subconjunto «diverso» de (c) y la lista de enero se concretaron a las 06:05, ya conocidos los resultados de las familias en 2025 (limitación 1). Sus pesos no tienen fuga.
  - **13,39 %, −0,55 puntos [−0,69; −0,41] frente a V4, mejor en los 12 meses.**
  - Sobrevive la corrección por comparaciones múltiples: Holm y Bonferroni con los 51 candidatos, y Bonferroni con m = 89 si se suman los ensambles informativos que las familias no registraron.
  - Mejora en las 3 rutas, los 3 tipos de día y las 3 franjas, sin enero (−0,59) y frente a V4 con su escala corregida (−0,57).
  - Empata con el apilamiento del subconjunto diverso de 6 modelos: 13,42 %, −0,03 [−0,09; +0,02] entre ellos.
- **Finalistas:** `ens_conj_c_nnls_diverso` (13,42 %), `ens_conj_a_media_V4_mejor_familia` (13,59 %) y `hibrido_V4_chronos2cov` (13,62 %). El mejor ad hoc, V4 + TFT (13,48 %), cumple la regla, pero no es elegible: sus miembros se eligieron mirando 2025.
- **2024, fuera de la muestra de selección** (mismos pliegues mensuales; ~70 min de cómputo):
  - **Se sostienen el híbrido** (−0,33 [−0,50; −0,14], 10/12) **y la media simple (a)** (−0,49 [−0,71; −0,26], 10/12). Entre ellos no hay diferencia significativa en ningún año.
  - **No se sostienen los apilamientos NNLS con TFT.** El diverso queda en −0,23 [−0,49; +0,09] y V4 + TFT en −0,10 [−0,48; +0,42]. Sus pesos de febrero, estimados solo con un enero atípico, fallan, y TFT empeora mucho con un año menos de historia.
  - **El ganador no se pudo repetir:** exige sus 40 modelos, de 9 a 12 h de cómputo.
- **Recomendación para producción: el híbrido V4 + Chronos-2.** Su mejora de ~0,33 puntos se repite en dos años con el menor costo y riesgo: un LightGBM como V4 más un modelo preentrenado que solo se usa para pronosticar, sin GPU.
- **TimesFM 2.5 de Google no sirve para Sobusa.** Solo queda en +1,02 en 2025 y +0,72 en 2024, y en el apilamiento diverso recibe peso 0.

## 1. Protocolo y candidatos

### 1.1 Protocolo (el mismo para todos)

- **Arnés común** `comun_e12.py` (ver `HARNESS.md`): reproduce V4 con diferencia 0 en las 18.615 predicciones de E11.
  - El mes m se entrena solo con días anteriores a m.
  - La predicción del día d usa información hasta d − 7, y `evaluar` lo verifica con la columna `corte` (`corte_verificado = true` en los 55 resultados).
  - El objetivo es `pasajeros_total` sin corregir, en todas las franjas de prueba.
- **Comparación con V4.** Diferencia de WAPE (candidato − V4, en puntos) con IC 95 % por bootstrap pareado de días: 2.000 réplicas y semilla 42. También cuenta los meses en que el candidato mejora a V4.
- **Ensambles sin fuga.** Los pesos y los miembros del mes m se estiman solo con los meses < m de 2025. Enero, sin meses previos, usa pesos iguales sobre una lista fijada sin mirar 2025 (sección 1.4). El corte de un ensamble es el más reciente de sus miembros con peso, y el arnés también lo verifica.

### 1.2 Candidatos registrados (51)

Todos están en `predicciones/` y `resultados/`, en el formato del arnés.

| Grupo | Cuántos | Qué son |
|---|---|---|
| Modelos individuales | 39 | Árboles (7 además de V4), clásicos (8), redes (5, dos de ellas ablaciones), fundacionales sin reentrenar (18) y el híbrido V4 + Chronos-2 |
| Ensambles de familia ya guardados | 4 | `ens_arboles_media_gbm` y `ens_arboles_nnls` (fijados antes de ver 2025), `ens_V4_chronos2_cov_nnls` y `ens_V4_fundacionales_nnls` (método y regla de miembros fijados antes de ver resultados) |
| Ensambles ad hoc de las familias | 3 | `ens_adhoc_V4_prophet_semanal_nnls`, `ens_adhoc_V4_tft_nnls` y `ens_adhoc_V4_nhits_nnls`. Se registran ahora, marcados **"hallado después de ver 2025"**: las familias eligieron el socio y el método tras probar 25 (clásicos) y 6 (redes) ensambles con los 12 meses de 2025 |
| Ensambles conjuntos fijados de antemano | 5 | (a), (b) con k = 3 y k = 5, y (c) sobre todos y sobre el subconjunto diverso (sección 1.4) |

Las referencias (V4, V0 de E1, B1 regla manual, B2 ingenua y los clásicos de E4) aparecen en el ranking, pero no son candidatos.

### 1.3 Regla de selección y elegibilidad

**Regla (fijada antes de ver resultados).** Gana el candidato con menor WAPE h = 7 que cumpla dos condiciones:
- el IC 95 % de su diferencia con V4 queda entero por debajo de 0;
- mejora a V4 en al menos 7 de los 12 meses.

Los ensambles no pueden usar el mes evaluado para sus pesos ni para elegir miembros. Si ninguno cumple, V4 sigue.

**Elegibilidad.** Los tres ensambles ad hoc estiman sus pesos sin fuga, pero sus miembros y su método se eligieron mirando los 12 meses de 2025. Eso es justo lo que prohíbe la última cláusula, así que **figuran en el ranking pero no pueden ganar**.
- `A.aplicar_regla` del arnés no conoce esa cláusula. Aun así elige el mismo ganador, porque ningún ad hoc queda primero.
- Las variantes individuales añadidas después de ver 2025 (`mstl7_arima_x_stl_diaria`, `timesfm25_xreg_tx`, `_xreg_sem`, `_xreg_serie`) y las dos ablaciones de redes sí son elegibles: son modelos y su configuración no se eligió con 2025. Ninguna cumple la regla.

### 1.4 Ensambles conjuntos fijados de antemano

**Lista de enero, fijada sin mirar 2025.** Es el mejor modelo de cada familia según la evidencia previa a 2025, además de V4:

| Familia | Modelo | Evidencia previa a 2025 |
|---|---|---|
| Árboles | `lgbm_tweedie` | Único boosting validado antes de 2025: oct-dic 2024, 15,83 % frente a 15,86 % de V4 |
| Redes | `tft_global` | Piloto sep-dic 2024: 17,16 % (CNN 17,64 %, N-HiTS 17,69 %; V4 16,93 %) |
| Clásicos | `autoets_cal` | Validación jul-dic 2024: 17,33 % (Prophet mensual 17,95 %) |
| Fundacionales | `chronos2_cov` | Elegido a priori para el híbrido. Los modelos sin reentrenar no tienen evaluación previa a 2025 |

El orden de la lista (V4, `lgbm_tweedie`, `tft_global`, `autoets_cal`, `chronos2_cov`) es el de cercanía a V4 en esa evidencia: para k = 3 se toman los tres primeros. A posteriori, estos cuatro modelos también resultaron los mejores individuales de su familia en 2025, si el híbrido no se cuenta como fundacional.

**Pool de individuales (40).** Los 39 modelos individuales más V4. No entran las referencias V0, B1 y B2.

| Nombre | Definición | Pesos del mes m |
|---|---|---|
| `ens_conj_a_media_V4_mejor_familia` | (a) Media simple de V4 y el mejor individual de cada familia: la lista de enero | Iguales (1/5) todo el año |
| `ens_conj_b_top3_rodante` | (b) Media de los 3 individuales del pool con menor WAPE acumulado en los meses < m | 1/3. Enero: V4, `lgbm_tweedie` y `tft_global` |
| `ens_conj_b_top5_rodante` | (b) Ídem con los 5 mejores | 1/5. Enero: la lista de enero |
| `ens_conj_c_nnls_todos` | (c) Apilamiento rodante: mínimos cuadrados no negativos (NNLS, sin intercepto ni normalización) sobre los 40 individuales, con las filas de los meses < m | NNLS. Enero: pesos iguales sobre la lista de enero |
| `ens_conj_c_nnls_diverso` | (c) Ídem sobre el subconjunto diverso: V4, CatBoost, TFT, Prophet semanal, Chronos-2 con calendario y TimesFM 2.5 con XReg | NNLS. Enero: pesos iguales sobre los 6 |

`run_ensamble.py` reproduce `A.ensamble_sin_fuga` con diferencia máxima 0 (chequeo con V4 + Chronos-2 NNLS, incluido el ensamble ya guardado).

## 2. Ranking

Diferencia con V4 en puntos de WAPE (negativo = mejor), con IC 95 % por bootstrap pareado de días. **Regla**: cumple la regla de selección. **p de Holm** e **IC de Bonferroni**: corrección por las 51 comparaciones (sección 4). La tabla completa, con más columnas, está en `ranking.csv`; `tabla_modelos.csv` se regeneró con `A.resumen_modelos(guardar=True)`.

| # | Candidato | Tipo | WAPE h=7 | Dif. con V4 [IC 95 %] | Meses mejor | Regla | Elegible | p de Holm | IC de Bonferroni (99,90 %) | Sobrevive |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **`ens_conj_c_nnls_todos`** | conjunto | 13,39 % | −0,55 [−0,69; −0,41] | 12/12 | sí | sí | 0,002 | [−0,77; −0,28] | sí |
| 2 | `ens_conj_c_nnls_diverso` | conjunto | 13,42 % | −0,52 [−0,65; −0,38] | 12/12 | sí | sí | 0,002 | [−0,73; −0,26] | sí |
| 3 | `ens_adhoc_V4_tft_nnls` | **ad hoc** | 13,48 % | −0,46 [−0,59; −0,34] | 12/12 | sí | no | 0,002 | [−0,66; −0,25] | sí |
| 4 | `ens_conj_a_media_V4_mejor_familia` | conjunto | 13,59 % | −0,35 [−0,48; −0,21] | 12/12 | sí | sí | 0,002 | [−0,55; −0,10] | sí |
| 5 | `hibrido_V4_chronos2cov` | híbrido | 13,62 % | −0,32 [−0,43; −0,22] | 11/12 | sí | sí | 0,002 | [−0,51; −0,14] | sí |
| 6 | `ens_conj_b_top3_rodante` | conjunto | 13,63 % | −0,30 [−0,37; −0,24] | 12/12 | sí | sí | 0,002 | [−0,41; −0,19] | sí |
| 7 | `ens_adhoc_V4_prophet_semanal_nnls` | **ad hoc** | 13,72 % | −0,22 [−0,32; −0,11] | 11/12 | sí | no | 0,015 | [−0,39; −0,02] | sí |
| 8 | `ens_conj_b_top5_rodante` | conjunto | 13,73 % | −0,21 [−0,30; −0,10] | 12/12 | sí | sí | 0,038 | [−0,34; −0,004] | sí |
| 9 | `ens_adhoc_V4_nhits_nnls` | **ad hoc** | 13,75 % | −0,19 [−0,27; −0,11] | 11/12 | sí | no | 0,002 | [−0,32; −0,05] | sí |
| 10 | `ens_arboles_media_gbm` | ens. familia | 13,76 % | −0,18 [−0,23; −0,12] | 11/12 | sí | sí | 0,002 | [−0,28; −0,10] | sí |
| 11 | `ens_V4_chronos2_cov_nnls` | ens. familia | 13,79 % | −0,15 [−0,25; −0,03] | 11/12 | sí | sí | 0,691 | [−0,31; +0,07] | **no** |
| 12 | `ens_arboles_nnls` | ens. familia | 13,80 % | −0,14 [−0,20; −0,07] | 11/12 | sí | sí | 0,002 | [−0,24; −0,02] | sí |
| 13 | `lgbm_tweedie` | individual | 13,91 % | −0,03 [−0,08; +0,02] | 6/12 | no | sí | 1,000 | [−0,13; +0,05] | no |
| 14 | `lgbm_v4_bag5` | individual | 13,92 % | −0,01 [−0,03; +0,00] | 9/12 | no | sí | 1,000 | [−0,05; +0,02] | no |
| 15 | `hgb_poisson` | individual | 13,93 % | −0,00 [−0,08; +0,07] | 7/12 | no | sí | 1,000 | [−0,13; +0,12] | no |
| 16 | `xgboost_poisson` | individual | 13,94 % | −0,00 [−0,08; +0,06] | 4/12 | no | sí | 1,000 | [−0,13; +0,10] | no |
| 17 | `V4_lightgbm` | referencia | 13,94 % | — | — | — | — | — | — | — |
| 18 | `ens_V4_fundacionales_nnls` | ens. familia | 13,96 % | +0,02 [−0,19; +0,27] | 10/12 | no | sí | 1,000 | [−0,27; +0,47] | no |
| 19 | `catboost_poisson` | individual | 14,01 % | +0,07 [−0,06; +0,20] | 6/12 | no | sí | 1,000 | [−0,15; +0,28] | no |
| 20 | `tft_global` | individual | 14,19 % | +0,26 [+0,01; +0,50] | 5/12 | no | sí | 1,000 | [−0,12; +0,68] | no |
| 21 | `extra_trees` | individual | 14,21 % | +0,27 [+0,02; +0,57] | 6/12 | no | sí | 1,000 | [−0,11; +0,80] | no |
| 22 | `E4_E_GLM_SARIMA` | referencia E4 | 14,34 % | +0,40 [+0,17; +0,65] | 3/12 | — | — | — | — | — |
| 23 | `V0_E1` | referencia | 14,40 % | +0,46 [+0,33; +0,60] | 2/12 | — | — | — | — | — |
| 24 | `E4_SARIMA_perfil` | referencia E4 | 14,51 % | +0,57 [+0,32; +0,84] | 3/12 | — | — | — | — | — |
| 25 | `E4_GLM_lags` | referencia E4 | 14,59 % | +0,65 [+0,43; +0,92] | 2/12 | — | — | — | — | — |
| 26 | `E4_ETS_perfil` | referencia E4 | 14,59 % | +0,65 [+0,39; +0,94] | 3/12 | — | — | — | — | — |
| 27 | `autoets_cal` | individual | 14,62 % | +0,68 [+0,38; +1,04] | 2/12 | no | sí | 1,000 | [+0,20; +1,31] | no |
| 28 | `prophet_semanal` | individual | 14,67 % | +0,73 [+0,46; +1,02] | 0/12 | no | sí | 1,000 | [+0,30; +1,25] | no |
| 29 | `chronos2_cov` | individual | 14,71 % | +0,77 [+0,47; +1,14] | 2/12 | no | sí | 1,000 | [+0,30; +1,42] | no |
| 34 | `E4_GLM_cal` | referencia E4 | 14,86 % | +0,92 [+0,69; +1,17] | 1/12 | — | — | — | — | — |
| 35 | `timesfm25_xreg` | individual | 14,96 % | +1,02 [+0,67; +1,43] | 0/12 | no | sí | 1,000 | [+0,46; +1,78] | no |
| 55 | `B1_manual` | referencia | 20,04 % | +6,11 [+4,77; +7,65] | 0/12 | — | — | — | — | — |

<details><summary>Ranking completo (60 filas: 51 candidatos y 9 referencias)</summary>

| # | Candidato | Tipo | WAPE h=7 | Dif. con V4 [IC 95 %] | Meses mejor | Regla | Elegible | p de Holm | IC de Bonferroni (99,90 %) | Sobrevive |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **`ens_conj_c_nnls_todos`** | conjunto | 13,39 % | −0,55 [−0,69; −0,41] | 12/12 | sí | sí | 0,002 | [−0,77; −0,28] | sí |
| 2 | `ens_conj_c_nnls_diverso` | conjunto | 13,42 % | −0,52 [−0,65; −0,38] | 12/12 | sí | sí | 0,002 | [−0,73; −0,26] | sí |
| 3 | `ens_adhoc_V4_tft_nnls` | **ad hoc** | 13,48 % | −0,46 [−0,59; −0,34] | 12/12 | sí | no | 0,002 | [−0,66; −0,25] | sí |
| 4 | `ens_conj_a_media_V4_mejor_familia` | conjunto | 13,59 % | −0,35 [−0,48; −0,21] | 12/12 | sí | sí | 0,002 | [−0,55; −0,10] | sí |
| 5 | `hibrido_V4_chronos2cov` | híbrido | 13,62 % | −0,32 [−0,43; −0,22] | 11/12 | sí | sí | 0,002 | [−0,51; −0,14] | sí |
| 6 | `ens_conj_b_top3_rodante` | conjunto | 13,63 % | −0,30 [−0,37; −0,24] | 12/12 | sí | sí | 0,002 | [−0,41; −0,19] | sí |
| 7 | `ens_adhoc_V4_prophet_semanal_nnls` | **ad hoc** | 13,72 % | −0,22 [−0,32; −0,11] | 11/12 | sí | no | 0,015 | [−0,39; −0,02] | sí |
| 8 | `ens_conj_b_top5_rodante` | conjunto | 13,73 % | −0,21 [−0,30; −0,10] | 12/12 | sí | sí | 0,038 | [−0,34; −0,004] | sí |
| 9 | `ens_adhoc_V4_nhits_nnls` | **ad hoc** | 13,75 % | −0,19 [−0,27; −0,11] | 11/12 | sí | no | 0,002 | [−0,32; −0,05] | sí |
| 10 | `ens_arboles_media_gbm` | ens. familia | 13,76 % | −0,18 [−0,23; −0,12] | 11/12 | sí | sí | 0,002 | [−0,28; −0,10] | sí |
| 11 | `ens_V4_chronos2_cov_nnls` | ens. familia | 13,79 % | −0,15 [−0,25; −0,03] | 11/12 | sí | sí | 0,691 | [−0,31; +0,07] | no |
| 12 | `ens_arboles_nnls` | ens. familia | 13,80 % | −0,14 [−0,20; −0,07] | 11/12 | sí | sí | 0,002 | [−0,24; −0,02] | sí |
| 13 | `lgbm_tweedie` | individual | 13,91 % | −0,03 [−0,08; +0,02] | 6/12 | no | sí | 1,000 | [−0,13; +0,05] | no |
| 14 | `lgbm_v4_bag5` | individual | 13,92 % | −0,01 [−0,03; +0,00] | 9/12 | no | sí | 1,000 | [−0,05; +0,02] | no |
| 15 | `hgb_poisson` | individual | 13,93 % | −0,00 [−0,08; +0,07] | 7/12 | no | sí | 1,000 | [−0,13; +0,12] | no |
| 16 | `xgboost_poisson` | individual | 13,94 % | −0,00 [−0,08; +0,06] | 4/12 | no | sí | 1,000 | [−0,13; +0,10] | no |
| 17 | `V4_lightgbm` | referencia | 13,94 % | — | — | — | — | — | — | — |
| 18 | `ens_V4_fundacionales_nnls` | ens. familia | 13,96 % | +0,02 [−0,19; +0,27] | 10/12 | no | sí | 1,000 | [−0,27; +0,47] | no |
| 19 | `catboost_poisson` | individual | 14,01 % | +0,07 [−0,06; +0,20] | 6/12 | no | sí | 1,000 | [−0,15; +0,28] | no |
| 20 | `tft_global` | individual | 14,19 % | +0,26 [+0,01; +0,50] | 5/12 | no | sí | 1,000 | [−0,12; +0,68] | no |
| 21 | `extra_trees` | individual | 14,21 % | +0,27 [+0,02; +0,57] | 6/12 | no | sí | 1,000 | [−0,11; +0,80] | no |
| 22 | `E4_E_GLM_SARIMA` | referencia E4 | 14,34 % | +0,40 [+0,17; +0,65] | 3/12 | — | — | — | — | — |
| 23 | `V0_E1` | referencia | 14,40 % | +0,46 [+0,33; +0,60] | 2/12 | — | — | — | — | — |
| 24 | `E4_SARIMA_perfil` | referencia E4 | 14,51 % | +0,57 [+0,32; +0,84] | 3/12 | — | — | — | — | — |
| 25 | `E4_GLM_lags` | referencia E4 | 14,59 % | +0,65 [+0,43; +0,92] | 2/12 | — | — | — | — | — |
| 26 | `E4_ETS_perfil` | referencia E4 | 14,59 % | +0,65 [+0,39; +0,94] | 3/12 | — | — | — | — | — |
| 27 | `autoets_cal` | individual | 14,62 % | +0,68 [+0,38; +1,04] | 2/12 | no | sí | 1,000 | [+0,20; +1,31] | no |
| 28 | `prophet_semanal` | individual | 14,67 % | +0,73 [+0,46; +1,02] | 0/12 | no | sí | 1,000 | [+0,30; +1,25] | no |
| 29 | `chronos2_cov` | individual | 14,71 % | +0,77 [+0,47; +1,14] | 2/12 | no | sí | 1,000 | [+0,30; +1,42] | no |
| 30 | `chronos2_cov_sinfallas` | individual | 14,72 % | +0,78 [+0,45; +1,18] | 3/12 | no | sí | 1,000 | [+0,26; +1,53] | no |
| 31 | `chronos2_multiruta_cov` | individual | 14,72 % | +0,78 [+0,43; +1,22] | 2/12 | no | sí | 1,000 | [+0,24; +1,54] | no |
| 32 | `random_forest` | individual | 14,74 % | +0,80 [+0,38; +1,33] | 4/12 | no | sí | 1,000 | [+0,21; +1,74] | no |
| 33 | `prophet_mensual` | individual | 14,79 % | +0,86 [+0,59; +1,16] | 0/12 | no | sí | 1,000 | [+0,42; +1,39] | no |
| 34 | `E4_GLM_cal` | referencia E4 | 14,86 % | +0,92 [+0,69; +1,17] | 1/12 | — | — | — | — | — |
| 35 | `timesfm25_xreg` | individual | 14,96 % | +1,02 [+0,67; +1,43] | 0/12 | no | sí | 1,000 | [+0,46; +1,78] | no |
| 36 | `timesfm25_xreg_sem` | individual | 14,99 % | +1,05 [+0,69; +1,46] | 0/12 | no | sí | 1,000 | [+0,48; +1,81] | no |
| 37 | `cnn_cuadricula` | individual | 15,06 % | +1,13 [+0,87; +1,40] | 0/12 | no | sí | 1,000 | [+0,73; +1,61] | no |
| 38 | `cnn_cuadricula_anio` | individual | 15,12 % | +1,18 [+0,89; +1,51] | 1/12 | no | sí | 1,000 | [+0,73; +1,76] | no |
| 39 | `nhits_global` | individual | 15,17 % | +1,24 [+0,96; +1,55] | 0/12 | no | sí | 1,000 | [+0,76; +1,78] | no |
| 40 | `timesfm25_xreg_serie` | individual | 15,24 % | +1,30 [+0,90; +1,73] | 0/12 | no | sí | 1,000 | [+0,67; +2,10] | no |
| 41 | `chronos2_small_cov` | individual | 15,29 % | +1,35 [+0,99; +1,77] | 1/12 | no | sí | 1,000 | [+0,75; +2,07] | no |
| 42 | `nhits_anio` | individual | 15,33 % | +1,39 [+1,04; +1,79] | 0/12 | no | sí | 1,000 | [+0,81; +2,07] | no |
| 43 | `autoarima_x` | individual | 15,89 % | +1,95 [+1,49; +2,53] | 0/12 | no | sí | 1,000 | [+1,28; +3,05] | no |
| 44 | `timesfm25_xreg_tx` | individual | 16,00 % | +2,06 [+1,66; +2,55] | 0/12 | no | sí | 1,000 | [+1,38; +2,94] | no |
| 45 | `chronos2` | individual | 17,08 % | +3,14 [+2,04; +4,44] | 1/12 | no | sí | 1,000 | [+1,40; +5,40] | no |
| 46 | `chronos2_ruta17_cov` | individual | 17,20 % | +3,26 [+2,72; +3,93] | 0/12 | no | sí | 1,000 | [+2,44; +4,46] | no |
| 47 | `chronos2_small` | individual | 17,60 % | +3,66 [+2,37; +5,23] | 1/12 | no | sí | 1,000 | [+1,65; +6,35] | no |
| 48 | `mstl7_arima_x` | individual | 17,76 % | +3,82 [+3,28; +4,39] | 0/12 | no | sí | 1,000 | [+2,96; +4,88] | no |
| 49 | `timesfm25` | individual | 17,90 % | +3,96 [+2,70; +5,45] | 1/12 | no | sí | 1,000 | [+1,98; +6,48] | no |
| 50 | `mstl7_arima_x_stl_diaria` | individual | 18,05 % | +4,11 [+3,53; +4,76] | 0/12 | no | sí | 1,000 | [+3,16; +5,24] | no |
| 51 | `chronos_bolt_base` | individual | 18,23 % | +4,29 [+3,05; +5,73] | 0/12 | no | sí | 1,000 | [+2,37; +6,84] | no |
| 52 | `chronos_bolt_small` | individual | 18,40 % | +4,46 [+3,15; +5,92] | 0/12 | no | sí | 1,000 | [+2,47; +7,08] | no |
| 53 | `chronos2_ruta17` | individual | 19,85 % | +5,91 [+4,54; +7,57] | 0/12 | no | sí | 1,000 | [+3,71; +8,71] | no |
| 54 | `autoets_s7` | individual | 19,90 % | +5,96 [+4,72; +7,36] | 0/12 | no | sí | 1,000 | [+3,98; +8,53] | no |
| 55 | `B1_manual` | referencia | 20,04 % | +6,11 [+4,77; +7,65] | 0/12 | — | — | — | — | — |
| 56 | `timesfm25_ruta17` | individual | 20,77 % | +6,83 [+5,35; +8,53] | 0/12 | no | sí | 1,000 | [+4,50; +9,83] | no |
| 57 | `B2_ingenua_7d` | referencia | 24,74 % | +10,80 [+9,07; +12,77] | 0/12 | — | — | — | — | — |
| 58 | `mstl_arima_x` | individual | 25,51 % | +11,57 [+10,40; +12,71] | 0/12 | no | sí | 1,000 | [+9,75; +13,61] | no |
| 59 | `chronos_bolt_small_ruta17` | individual | 43,71 % | +29,77 [+28,79; +30,87] | 0/12 | no | sí | 1,000 | [+28,14; +31,70] | no |
| 60 | `chronos_bolt_base_ruta17` | individual | 45,93 % | +31,99 [+30,56; +33,57] | 0/12 | no | sí | 1,000 | [+29,72; +34,65] | no |

</details>

![Ranking de candidatos](fig1_ranking_wape_ic.png)

**Lectura.**
- **Ningún modelo individual le gana a V4.** Los cuatro boosting con Poisson o Tweedie empatan con V4 (de −0,03 a 0,00 puntos); el resto pierde. Toda la ganancia viene de **combinar familias** o de meter otra familia dentro de V4 (el híbrido).
- **Los 12 candidatos que cumplen la regla son ensambles o el híbrido.** Los conjuntos fijados de antemano ocupan las posiciones 1, 2, 4, 6 y 8.
- **Los ad hoc no ganan nada que los conjuntos no logren sin elegir mirando 2025.** El mejor ad hoc (V4 + TFT, 13,48 %) queda detrás de los dos apilamientos (c), que llegan a TFT por su cuenta, mes a mes y sin fuga.

## 3. Ganador según la regla: `ens_conj_c_nnls_todos`

**Qué es.** Apilamiento rodante NNLS sobre los 40 modelos individuales: los pesos de cada mes se estiman con los meses anteriores de 2025. Enero usa pesos iguales sobre la lista fijada sin mirar 2025.

**Resultado.** **13,39 %, −0,55 puntos [−0,69; −0,41] frente a V4, mejor en los 12 meses.**
- Prueba t pareada por mes: p = 3·10⁻⁷; Wilcoxon: p = 0,0005.
- Sin su mes de mayor ganancia (julio): −0,53.
- MAE 92,6 frente a 96,4 pasajeros por franja; RMSE 139,2 frente a 144,0.
- Sesgo +0,22 % frente a +1,42 % de V4: los pesos suman de 0,97 a 0,98 y encogen un poco el pronóstico.

**Qué pesa de verdad.** De los 40 miembros, solo 14 reciben algún peso de febrero a diciembre, y 26 nunca. Pesos medios de febrero a diciembre:

| Miembro | Peso medio (máximo) | Comentario |
|---|---|---|
| `hibrido_V4_chronos2cov` | 0,32 (0,45) | Reemplaza a V4: V4 recibe 0 desde febrero |
| `tft_global` | 0,29 (0,42) | Sube de 0 en febrero a ~0,40 de agosto a diciembre, a medida que TFT acumula entrenamiento incremental |
| `catboost_poisson` | 0,10 (0,13) | El boosting con errores más distintos de V4 |
| `prophet_mensual` | 0,08 (0,13) | El clásico que mejor complementa a V4 |
| `hgb_poisson` | 0,08 (0,19) | Solo de febrero a agosto |
| `nhits_global` | 0,05 (0,08) | La red con errores menos parecidos a V4 |
| `lgbm_tweedie` | 0,04 (0,14) | Solo de febrero a agosto |
| Otros 7 (Chronos-2 small con y sin calendario, CNN, dos MSTL, XGBoost y TimesFM `xreg_tx`) | ≤ 0,012 (≤ 0,034) | Peso residual |

**Ganador frente a los demás finalistas** (bootstrap pareado de días; negativo = gana el ganador):

| Comparación | Diferencia [IC 95 %] | Meses mejor |
|---|---|---|
| frente a `ens_conj_c_nnls_diverso` | −0,03 [−0,09; +0,02] | 8/12 |
| frente a `ens_adhoc_V4_tft_nnls` | −0,09 [−0,15; −0,03] | 10/12 |
| frente a `ens_conj_a_media_V4_mejor_familia` | −0,20 [−0,30; −0,11] | 10/12 |
| frente a `hibrido_V4_chronos2cov` | −0,23 [−0,35; −0,09] | 10/12 |
| frente a `ens_arboles_media_gbm` | −0,38 [−0,52; −0,23] | 11/12 |

**El ganador y el apilamiento diverso de 6 modelos no se distinguen** (IC con el 0). El diverso sí es significativamente mejor que (a), por −0,17 [−0,26; −0,08], y que el híbrido, por −0,20 [−0,33; −0,04]. En cambio, (a) y el híbrido empatan: −0,03 [−0,16; +0,13].

## 4. Corrección por comparaciones múltiples

**Método.** Se repitió el bootstrap pareado de días con **50.000 réplicas** (mismo generador y semilla 42). Las 2.000 primeras reproducen exactamente los IC del arnés.
- **p-valor de cada candidato.** H₀: no mejora a V4. Se calcula el p unilateral (réplicas con diferencia ≥ 0 + 1) / 50.001 y se duplica, para que sea equivalente al IC 95 % bilateral de la regla.
- **Holm.** Corrección por paso descendente con α familiar = 0,05 sobre los **m = 51 candidatos** (todos los registrados salvo las referencias).
- **Bonferroni.** IC de nivel 1 − 0,05/51 = 99,90 %.
- **Versión amplia (m = 89).** Suma las comparaciones que las familias evaluaron en 2025 sin registrarlas: 25 ensambles de clásicos, 6 ensambles y un control de redes, 3 medias 50/50 de redes, 5 medias de 4 de árboles y 1 media de fundacionales, sin contar dos veces los 3 ad hoc. Su IC de Bonferroni es de 99,94 %.

**Resultado.**
- **Sobreviven 11 de los 12 que cumplen la regla**, tanto con Holm como con Bonferroni (m = 51): los 5 conjuntos, el híbrido, los 3 ad hoc y los 2 ensambles de árboles.
- **Cae `ens_V4_chronos2_cov_nnls`**: p de Holm 0,69 e IC de Bonferroni [−0,31; +0,07].
- **`ens_conj_b_top5_rodante` queda al borde.** Su IC de Bonferroni llega a −0,004 con m = 51 y cruza el 0 con m = 89.
- **El ganador sobrevive con holgura** en las dos versiones: [−0,77; −0,28] con m = 51.
- **La regla con el IC corregido** (Bonferroni con m = 51 y al menos 7 de 12 meses) elige el mismo ganador.

## 5. Robustez del ganador y los finalistas

**Finalistas.** Son los tres siguientes elegibles que cumplen la regla: `ens_conj_c_nnls_diverso`, `ens_conj_a_media_V4_mejor_familia` y `hibrido_V4_chronos2cov`. Se añaden, solo para comparar, el ad hoc V4 + TFT y la media de 5 boosting.

**"Con β".** En E12 no hay ningún β definido; en el proyecto, β es la elasticidad de E7, que no aplica a la exactitud del pronóstico. Aquí se interpretó como **un factor de escala β sin fuga**.
- **Cálculo.** β del mes m = Σ p·y / Σ p² con los meses < m (enero β = 1). Es el NNLS de una sola columna, la corrección de nivel que los apilamientos hacen implícitamente.
- **Pregunta que responde.** ¿La ganancia sobrevive si a V4 también se le corrige el nivel?
- **Respuesta: sí.** V4 × β no mejora a V4: +0,02 [−0,02; +0,05], con β de 0,975 a 0,992. Las ganancias frente a V4 × β son iguales o mayores que frente a V4. La ganancia no es una corrección de sesgo.

| Candidato | Global | Frente a V4 × β | Ambos con su β | Sin enero (11 meses) | Sesgo |
|---|---|---|---|---|---|
| `ens_conj_c_nnls_todos` (ganador) | −0,55 [−0,69; −0,41], 12/12 | −0,57 [−0,71; −0,43], 12/12 | −0,48 [−0,62; −0,34], 11/12 | −0,59 [−0,71; −0,48], 11/11 | +0,22 % |
| `ens_conj_c_nnls_diverso` | −0,52 [−0,65; −0,38], 12/12 | −0,54 [−0,67; −0,39], 12/12 | −0,49 [−0,62; −0,34], 12/12 | −0,53 [−0,64; −0,42], 11/11 | +0,24 % |
| `ens_conj_a_media_V4_mejor_familia` | −0,35 [−0,48; −0,21], 12/12 | −0,37 [−0,52; −0,21], 11/12 | −0,45 [−0,57; −0,30], 12/12 | −0,37 [−0,48; −0,27], 11/11 | +2,90 % |
| `hibrido_V4_chronos2cov` | −0,32 [−0,43; −0,22], 11/12 | −0,34 [−0,45; −0,23], 11/12 | −0,29 [−0,40; −0,18], 11/12 | −0,31 [−0,42; −0,21], 10/11 | +1,45 % |
| `ens_adhoc_V4_tft_nnls` (ad hoc) | −0,46 [−0,59; −0,34], 12/12 | −0,48 [−0,60; −0,36], 12/12 | −0,39 [−0,51; −0,26], 11/12 | −0,50 [−0,61; −0,39], 11/11 | +0,10 % |
| `ens_arboles_media_gbm` | −0,18 [−0,23; −0,12], 11/12 | −0,20 [−0,26; −0,14], 11/12 | −0,19 [−0,24; −0,14], 12/12 | −0,14 [−0,19; −0,10], 10/11 | +1,20 % |

**Lectura de "sin enero".**
- **Enero no explica las ganancias.** Sin él, la ganancia crece o se mantiene en los apilamientos, en (a), en el híbrido y en V4 + TFT. En enero el ganador solo gana −0,12, porque usa pesos iguales sobre la lista de enero.
- **Solo la media de 5 boosting depende algo de enero:** pasa de −0,18 a −0,14 sin él.
- **(a) mejora con β** (−0,45). Su sesgo de +2,9 % viene de la sobreestimación de TFT y Chronos-2.

**Por segmento** (WAPE del candidato frente al de V4; diferencia con IC 95 %; `fig2_finalistas_segmentos.png`):

| Segmento | V4 | Ganador | `c_nnls_diverso` | (a) | Híbrido |
|---|---|---|---|---|---|
| SILENCIO | 15,52 % | 15,01 %: −0,51 [−0,69; −0,34] | 15,02 %: −0,50 [−0,67; −0,34] | 15,11 %: −0,41 [−0,57; −0,26] | 15,32 %: −0,19 [−0,37; −0,02] |
| CRA 54 | 11,54 % | 11,02 %: −0,52 [−0,69; −0,35] | 11,06 %: −0,48 [−0,65; −0,31] | 11,26 %: −0,28 [−0,44; −0,10] | 11,15 %: −0,38 [−0,54; −0,24] |
| CL 72 | 19,08 % | 18,35 %: −0,72 [−0,89; −0,55] | 18,40 %: −0,68 [−0,86; −0,49] | 18,58 %: −0,50 [−0,65; −0,34] | 18,77 %: −0,31 [−0,49; −0,14] |
| Laboral | 13,36 % | 12,85 %: −0,51 [−0,66; −0,34] | 12,86 %: −0,49 [−0,64; −0,33] | 13,04 %: −0,31 [−0,46; −0,15] | 13,03 %: −0,33 [−0,44; −0,22] |
| Sábado | 13,45 % | 12,91 %: −0,54 [−0,76; −0,32] | 12,88 %: −0,56 [−0,74; −0,40] | 13,13 %: −0,32 [−0,54; −0,05] | 13,27 %: −0,17 [−0,43; +0,09] |
| Domingo o festivo | 19,74 % | 18,81 %: −0,93 [−1,63; −0,34] | 19,05 %: −0,70 [−1,44; −0,06] | 19,00 %: −0,75 [−1,38; −0,21] | 19,27 %: −0,48 [−1,01; +0,02] |
| 4-8 h | 11,37 % | 10,77 %: −0,60 [−0,77; −0,42] | 10,86 %: −0,51 [−0,68; −0,32] | 11,09 %: −0,28 [−0,46; −0,08] | 10,95 %: −0,42 [−0,59; −0,26] |
| 9-15 h | 14,24 % | 13,71 %: −0,53 [−0,68; −0,37] | 13,73 %: −0,51 [−0,67; −0,34] | 13,85 %: −0,39 [−0,53; −0,23] | 13,92 %: −0,33 [−0,46; −0,20] |
| 16-20 h | 18,35 % | 17,84 %: −0,52 [−0,72; −0,33] | 17,79 %: −0,56 [−0,75; −0,38] | 17,94 %: −0,42 [−0,59; −0,23] | 18,26 %: −0,10 [−0,30; +0,10] |
| Total diario por ruta | 4,86 % | 4,79 % | 4,75 % | 5,13 % | 4,92 % |

- **El ganador y el diverso mejoran en todos los segmentos**, con el IC entero bajo 0 en cada uno.
- **El híbrido no alcanza significancia** en sábados, domingos o festivos y en la franja de 16-20 h.
- **Por mes** (`fig3_finalistas_mes.png`), el ganador mejora en los 12 meses: con IC entero bajo 0 en 10 de ellos. Enero (−0,12) y diciembre (−0,57) quedan con IC que toca el 0.
- **Subconjuntos de E11** (WAPE, ganador frente a V4): vacaciones escolares 15,25 % frente a 15,85 %; días normales 12,78 % frente a 13,32 %; transición de periodo 13,98 % frente a 14,77 %; franjas con fallas 68,8 % frente a 71,2 %; días atípicos 61,5 % frente a 63,3 %.

![Finalistas por segmento](fig2_finalistas_segmentos.png)

![Finalistas por mes](fig3_finalistas_mes.png)

## 6. Prueba fuera de la muestra de selección: 2024

**Diseño.** Es el mismo protocolo de 2025, con el año 2024 (`run_2024.py`).
- **Pliegues.** 12 pliegues mensuales: el mes m se entrena solo con días < m, así que enero de 2024 solo ve 2023.
- **h = 7.** Corte = d − 7, verificado en cada predicción.
- **Lo demás, igual que en 2025.** Mismas configuraciones, filas, pesos y tratamiento de V4, y mismo código de cada familia, sin modificarlo: solo se cambian en memoria los pliegues del arnés.
- **Ensambles.** Pesos del mes m con los meses < m de 2024; enero de 2024 con pesos iguales.
- **Evaluación.** Las 18.564 franjas de 364 días (sin los dos días R5), contra `pasajeros_total` sin corregir, con el mismo bootstrap pareado de días. 2024 no intervino en la elección del ganador ni de los finalistas, pero no es del todo virgen: con su segundo semestre las familias eligieron configuraciones (Tweedie en oct-dic, máscara de AutoETS y transformación de Prophet en jul-dic, configuración de TFT en el piloto de sep-dic) y se fijó la lista de enero que define (a). Para el híbrido, de diseño fijado a priori y con los hiperparámetros de V4, sí es una prueba fuera de la muestra.

**Viabilidad (presupuesto: ~75 min de cómputo).**
- **Ganador `ens_conj_c_nnls_todos`: no viable.** Exige repetir sus 40 miembros, que en 2025 sumaron unos 705 min de cómputo (~561 sin los dos desbordes de GPU): AutoARIMA 83 min, las tres MSTL 91 min, Prophet 30 min, las redes 130 min, los fundacionales y el híbrido 4,4 h… Tampoco sirve repetir solo los 14 miembros con peso: sería otro candidato, elegido mirando 2025.
- **Finalistas: sí.** `ens_conj_c_nnls_diverso` (6 miembros), `ens_conj_a_media_V4_mejor_familia` (5) y el híbrido (ya tenía su prueba; aquí se reprodujo).
  - Se corrieron V4, el híbrido, LightGBM Tweedie, CatBoost, TFT (3 semillas, incremental como en 2025), AutoETS con calendario, Prophet semanal y TimesFM con XReg. Chronos-2 con calendario se leyó de la caché del híbrido.
  - Cómputo: **~70 min de proceso en ~17 min de reloj**, con 5 procesos en paralelo: árboles 17 min, TFT 3 × 10 min en la GPU, Prophet 13 min, TimesFM 6 min y AutoETS 4 min.
  - Con esos miembros salen también, sin costo extra, los ad hoc V4 + TFT y V4 + Prophet y el ensamble de familia V4 + Chronos-2.
- **Chequeo.** V4 (15,734 %) y el híbrido (15,405 %; −0,33 [−0,50; −0,14]) reproducen exactamente `modelos_fundacionales/validacion_2024_hibrido.json`.

V4 en 2024: WAPE 15,73 %, sesgo +1,96 %.

| Candidato | 2025: dif. con V4 [IC 95 %], meses | 2024: WAPE | 2024: dif. con V4 [IC 95 %] | 2024: meses mejor | 2024 sin enero | ¿Cumpliría la regla en 2024? |
|---|---|---|---|---|---|---|
| `ens_conj_c_nnls_todos` (ganador) | −0,55 [−0,69; −0,41], 12/12 | no viable | — | — | — | — |
| `ens_conj_c_nnls_diverso` | −0,52 [−0,65; −0,38], 12/12 | 15,50 % | −0,23 [−0,49; +0,09] | 10/12 | −0,04 [−0,30; +0,26] | **no** |
| `ens_conj_a_media_V4_mejor_familia` | −0,35 [−0,48; −0,21], 12/12 | 15,24 % | **−0,49 [−0,71; −0,26]** | 10/12 | −0,30 [−0,50; −0,06] | **sí** |
| `hibrido_V4_chronos2cov` | −0,32 [−0,43; −0,22], 11/12 | 15,40 % | **−0,33 [−0,50; −0,14]** | 10/12 | −0,26 [−0,44; −0,07] | **sí** |
| `ens_adhoc_V4_tft_nnls` (ad hoc) | −0,46 [−0,59; −0,34], 12/12 | 15,63 % | −0,10 [−0,48; +0,42] | 11/12 | +0,01 [−0,41; +0,55] | no |
| `ens_adhoc_V4_prophet_semanal_nnls` (ad hoc) | −0,22 [−0,32; −0,11], 11/12 | 15,56 % | −0,17 [−0,38; +0,04] | 7/12 | +0,02 [−0,17; +0,22] | no |
| `ens_V4_chronos2_cov_nnls` | −0,15 [−0,25; −0,03], 11/12 | 15,54 % | −0,20 [−0,48; +0,19] | 10/12 | −0,03 [−0,34; +0,37] | no |
| `lgbm_tweedie` | −0,03 [−0,08; +0,02], 6/12 | 15,73 % | −0,00 [−0,07; +0,06] | 3/12 | −0,01 [−0,08; +0,06] | no |
| `catboost_poisson` | +0,07 [−0,06; +0,20], 6/12 | 16,55 % | +0,82 [+0,57; +1,07] | 1/12 | +0,54 [+0,30; +0,77] | no |
| `tft_global` | +0,26 [+0,01; +0,50], 5/12 | 17,47 % | +1,74 [+1,16; +2,46] | 3/12 | +1,91 [+1,30; +2,67] | no |
| `autoets_cal` | +0,68 [+0,38; +1,04], 2/12 | 15,90 % | +0,17 [−0,19; +0,60] | 4/12 | +0,44 [+0,09; +0,89] | no |
| `prophet_semanal` | +0,73 [+0,46; +1,02], 0/12 | 16,48 % | +0,74 [+0,40; +1,09] | 3/12 | +0,93 [+0,63; +1,30] | no |
| `chronos2_cov` | +0,77 [+0,47; +1,14], 2/12 | 16,28 % | +0,55 [+0,14; +1,09] | 2/12 | +0,80 [+0,38; +1,32] | no |
| `timesfm25_xreg` | +1,02 [+0,67; +1,43], 0/12 | 16,45 % | +0,72 [+0,36; +1,12] | 1/12 | +1,00 [+0,64; +1,41] | no |

**Finalistas entre sí en 2024** (negativo = gana el primero):

| Comparación | Diferencia [IC 95 %] | Meses mejor |
|---|---|---|
| `c_nnls_diverso` − híbrido | +0,09 [−0,21; +0,45] | 7/12 |
| (a) − híbrido | −0,16 [−0,43; +0,12] | 7/12 |
| `c_nnls_diverso` − (a) | +0,26 [+0,10; +0,45] | 6/12 |
| V4 + TFT (ad hoc) − híbrido | +0,23 [−0,20; +0,80] | 7/12 |

![2025 frente a 2024](fig4_2024_vs_2025.png)

**Lectura.**
1. **Se sostienen el híbrido y la media simple (a).**
   - El híbrido repite su ganancia casi exacta: −0,32 en 2025 y −0,33 en 2024, y −0,26 sin enero.
   - (a) gana incluso más en 2024 (−0,49), pero con más sesgo: +3,9 % frente a +1,5 % del híbrido.
   - Entre los dos no hay diferencia significativa en ningún año.
2. **No se sostienen los apilamientos NNLS con TFT.**
   - `c_nnls_diverso` baja a −0,23, con un IC que cruza el 0. Sin enero, la ganancia desaparece: −0,04.
   - El ad hoc V4 + TFT, el mejor ad hoc de 2025, cae a −0,10 [−0,48; +0,42]. La cláusula que lo dejó fuera de la elección estaba justificada.
3. **Por qué fallan los NNLS en 2024.**
   - **Enero de 2024 es atípico para V4.** Entrena solo con 2023 y marca 18,3 %, así que todos los ensambles ganan mucho ese mes (de −1,1 a −2,7 puntos).
   - **Los pesos de febrero se estiman solo con ese enero.** Por eso el NNLS apuesta por TFT: 0,88 en V4 + TFT, y 0,54 TFT con 0,36 Prophet en el diverso, con V4 en 0. En febrero TFT pierde +3,56 puntos, y los ensambles pierden +4,47 y +2,55.
   - **TFT es mucho peor en 2024** (+1,74; sesgo +10 %) que en 2025 (+0,26). Con un año menos de historia, el entrenamiento incremental arranca más débil, y además junio de 2024 es atípico (8,8 % de viajes sin registro; WAPE de V4 23,1 %).
   - **La lección.** Los pesos estimados con pocos meses son frágiles, y la media simple, que no estima nada, es más robusta. Es el conocido "rompecabezas de la combinación de pronósticos".
4. **Para el ganador.** Usa el mismo mecanismo (NNLS rodante con TFT entre sus miembros principales) y estima 40 pesos con los mismos pocos meses, así que lo más probable es que su ventaja de 2025 sobre el híbrido (−0,23) sea optimista. No se pudo comprobar.
5. **Los miembros cambian de un año a otro.**
   - AutoETS con calendario casi empata con V4 en 2024 (+0,17, sin significancia); CatBoost y TFT empeoran.
   - Chronos-2 y TimesFM quedan peor que V4 en ambos años.
   - LightGBM Tweedie empata con V4 en los dos.

## 7. Recomendación para producción

**Recomendación: llevar a producción el híbrido V4 + Chronos-2 (`hibrido_V4_chronos2cov`), no el ganador formal.**

**Por qué el híbrido.**
1. **Su ganancia se confirmó fuera de la muestra de selección.**
   - −0,32 [−0,43; −0,22] en 2025 y −0,33 [−0,50; −0,14] en 2024, mejor en 11 y 10 de 12 meses, y sin depender de enero.
   - Sobrevive la corrección por comparaciones múltiples.
   - Junto con (a), es el único de los candidatos repetidos en 2024 que cumple la regla en los dos años (6 de los 12 que la cumplen en 2025 no se repitieron, entre ellos el ganador); de los dos, es el más barato.
2. **Ninguna alternativa probada en 2024 le gana con significancia.**
   - (a) queda a −0,03 [−0,16; +0,13] en 2025 y a −0,16 [−0,43; +0,12] en 2024.
   - El apilamiento diverso queda a −0,20 [−0,33; −0,04] en 2025, pero a +0,09 [−0,21; +0,45] en 2024.
   - Lo que el ganador formal suma sobre el híbrido en 2025 (−0,23 [−0,35; −0,09]) lo aporta un mecanismo (NNLS rodante con TFT) que no se sostuvo en 2024.
3. **Es el más barato y el de menor riesgo.**
   - Es la misma cadena de V4 con 4 columnas más: la mediana, los cuantiles 10 y 90 de Chronos-2 y la razón con la media de 4 semanas.
   - Chronos-2 se usa sin reentrenar (pesos abiertos Apache-2.0) y no necesita GPU: en CPU con 2 hilos, una semana de pronósticos (51 series × 7 días) tarda 228 s y difiere de la GPU en 0,16 pasajeros por franja de media (máximo 38, sobre una media de 735; `medir_chronos2_cpu.py`).
   - Si Chronos-2 falla, se vuelve a V4, que se puede seguir entrenando en paralelo por unos segundos.
4. **Sesgo como el de V4:** +1,45 % en 2025 y +1,47 % en 2024. (a) llega a +2,9 % y +3,9 % por la sobreestimación de TFT y Chronos-2.

**Por qué no los demás.**
- **Ganador `ens_conj_c_nnls_todos`.** Gana la regla en 2025, pero exige mantener 40 modelos de unas 10 librerías para reestimar sus pesos cada mes, aunque solo 14 reciban peso. No se pudo validar en otro año, y el apilamiento NNLS con TFT falló en 2024. Su ventaja sobre el diverso no es significativa (−0,03 [−0,09; +0,02]).
- **`ens_conj_c_nnls_diverso`.** En 2024 perdió la significancia y, sin enero, la ganancia: −0,04.
- **(a) media de 5.** Rinde igual que el híbrido (sin diferencia significativa en ningún año), pero con tres modelos más (Tweedie, TFT con 3 semillas y AutoETS), TFT en la GPU y el doble de sesgo. No compensa.
- **Media de 5 boosting.** Más cara (CatBoost) y con menos ganancia (−0,18), aunque solo use CPU.

**Cómo ponerlo en marcha.**
1. **Fijar versiones.** `chronos-forecasting` 2.3.2 y la revisión de `amazon/chronos-2` en el entorno de producción.
2. **Historia.** Los pronósticos de Chronos-2 de la historia ya están calculados: `modelos_fundacionales/cache/chronos2_cov_todos_los_dias.parquet` y `predicciones/chronos2_cov.parquet`, con corte t − 7.
3. **Cada semana.** Pronosticar con Chronos-2 los días nuevos, con el contexto hasta d − 7 y el calendario como covariables. Reentrenar el LightGBM del híbrido con las filas y los pesos de V4.
4. **Primeros meses de 2026.** Correr el híbrido en paralelo con V4 (en sombra) y comparar el WAPE semanal antes de reemplazarlo.
5. **Combinaciones.** Si más adelante se quieren probar combinaciones, conviene usar medias simples o pesos con encogimiento hacia pesos iguales, no NNLS estimado con pocos meses, y validarlas en dos años antes de adoptarlas.

**Costo, complejidad y riesgo.**
- **Cómputo.** Se mide por reentrenamiento: uno por semana en producción, o uno por mes como en el protocolo. Son tiempos medidos en E12 con 2 hilos de CPU y la máquina compartida; los de 2024 se midieron con 5 procesos en paralelo.
- **Inferencia.** Una semana son 51 series × 7 días.

| | V4 (actual) | Híbrido V4 + Chronos-2 | (a) media de 5 | `c_nnls_diverso` | Ganador `c_nnls_todos` |
|---|---|---|---|---|---|
| WAPE 2025 (dif. con V4) | 13,94 % | 13,62 % (−0,32) | 13,59 % (−0,35) | 13,42 % (−0,52) | 13,39 % (−0,55) |
| Prueba en 2024 | referencia | −0,33 [−0,50; −0,14], 10/12: **cumple** | −0,49 [−0,71; −0,26], 10/12: **cumple** | −0,23 [−0,49; +0,09], 10/12: **no cumple** | no viable (sección 6) |
| Modelos que hay que mantener | 1 LightGBM | 1 LightGBM + Chronos-2 congelado (solo inferencia) | 5: V4, Tweedie, TFT × 3 semillas, AutoETS, Chronos-2 | 6: V4, CatBoost, TFT × 3 semillas, Prophet (51 series), Chronos-2, TimesFM; más los pesos NNLS de cada mes | 40 modelos y sus pesos NNLS |
| Librerías | lightgbm | lightgbm, chronos-forecasting (torch, transformers) | lightgbm, neuralforecast (torch, lightning), statsforecast, chronos-forecasting | lightgbm, catboost, neuralforecast, prophet (cmdstan), chronos-forecasting, timesfm (JAX) | Las anteriores más xgboost, scikit-learn y las variantes de cada familia (~10 librerías) |
| GPU | No | Opcional: Chronos-2 en CPU, 228 s por semana con 2 hilos | Recomendable (TFT) | Sí, en la práctica (TFT; TimesFM) | Sí |
| Entrenamiento por reentrenamiento | 6-20 s | 5-10 s + Chronos-2 de los días nuevos | ≈ 2-4 min con GPU | ≈ 4-8 min con GPU (CatBoost 1-5 min en CPU; TFT 40 s por semilla incremental en GPU) | ≈ 30-60 min (AutoARIMA solo, ~7 min) |
| Puesta en marcha | — | Pronósticos de Chronos-2 de la historia: 703 días en 19 min de GPU (una vez) | TFT desde cero: ~2,5 min por semilla en GPU | Ídem, más CatBoost y Prophet | Las 40 cadenas |
| Riesgo operativo | Bajo | Bajo: un modelo; Chronos-2 es fijo (Apache-2.0, versión fijada). Si falla, V4 | Medio: 4 cadenas. Sesgo +2,9 % (2025) y +3,9 % (2024) | Medio-alto: 6 cadenas, estado incremental de TFT y pesos mensuales | Alto: 40 cadenas; pesos inestables entre meses |


## 8. Qué familias funcionan y por qué

| Familia | Solo | Como complemento de V4 | Por qué |
|---|---|---|---|
| **Árboles** (boosting) | Empatan con V4: de 13,91 a 14,01 %. Los bosques pierden (14,21 y 14,74 %) | La media de 5 gana −0,18; CatBoost es el miembro más útil | Ven las mismas 77 variables que V4, así que su información es la misma. La diversidad viene de la forma del árbol: los árboles simétricos de CatBoost y la hora como categórica. Los bosques no tienen enlace logarítmico y fallan en los cambios de calendario |
| **Clásicos** | De 14,62 % (AutoETS con calendario) a 25,5 % (MSTL anual) | Prophet aporta: −0,22 como ad hoc y ~0,08 de peso en el apilamiento | El calendario lo decide todo: sin regresores, AutoETS marca 19,90 %. Prophet modela feriados y estacionalidad como efectos suaves y sin el "eco" de d − 7, de forma distinta a V4 |
| **Redes** | TFT 14,19 %, CNN 15,06 %, N-HiTS 15,17 % | **TFT es el mejor socio de V4**: ~0,3-0,5 de peso en todos los apilamientos. N-HiTS aporta algo | TFT es casi tan preciso como V4 y se equivoca distinto (correlación de errores 0,91). Con el reentrenamiento incremental mejora a lo largo del año. Su sesgo de +6 % lo corrige el NNLS |
| **Fundacionales** sin reentrenar | Chronos-2 con calendario 14,71 %, TimesFM con XReg 14,96 %; sin covariables, de 17 a 18 % | **Como variables de V4 (híbrido): −0,32 en 2025 y −0,33 en 2024**, el mejor modelo único; en ensamble NNLS con V4, solo −0,15 | Resumen en un número el nivel reciente, el patrón semanal y el calendario. LightGBM corrige ese resumen con las variables de V4, que no ven los fundacionales (oferta, carga, totales del sistema) |

**El patrón general.** Ningún modelo nuevo le gana a V4 solo, porque V4 ya usa la mejor información disponible a 7 días: rezagos corregidos, oferta y calendario. Las ganancias de 0,3 a 0,55 puntos salen de **promediar errores poco correlacionados**:
- V4 o el híbrido ponen la base;
- TFT aporta otra lectura de la secuencia y del calendario;
- CatBoost y Prophet, otra forma de cortar las variables y el calendario.

Los pesos NNLS además corrigen el sesgo al alza de las redes y los fundacionales: suman de 0,96 a 0,98.

## 9. ¿Sirve TimesFM de Google?

**Para Sobusa, no.** Ni solo ni como miembro de un ensamble aporta algo que no den V4, TFT o Chronos-2.
- **Solo.** TimesFM 2.5 (200 M parámetros, Apache-2.0, sin reentrenar) marca 17,90 % sin covariables y **14,96 % con el calendario por XReg**: +1,02 [+0,67; +1,43] frente a V4, peor en los 12 meses. Le gana a V4 en los laborales de clases (12,20 % frente a 12,47 %), pero pierde en los días especiales (38 % frente a 25 %) y en los domingos (`modelos_fundacionales/README.md`, sección 4).
- **En 2024 se repite:** 16,45 % frente a 15,73 % de V4, +0,72 [+0,36; +1,12], mejor en 1 de 12 meses.
- **En ensamble.** En el apilamiento diverso, el NNLS le da **peso 0 de febrero a diciembre**. En el apilamiento de los 40, de sus seis variantes solo `xreg_tx` recibe algo: 0,001, en un único mes. Solo aportaba en el ensamble de fundacionales, donde no estaban TFT ni el híbrido (`timesfm25_xreg_serie` recibía un peso medio de 0,09).
- **Costo.** Es barato de correr: unos 351 s para los 18.615 pronósticos, ~1 s por día en la GPU más la regresión XReg en CPU. Pero suma dependencias (timesfm y JAX).
- **Licencia.** TimesFM 3.0 tiene licencia no comercial y no se probó.
- **Conclusión.** Como pronosticador de series genéricas es bueno (queda a 0,25 puntos de Chronos-2). Pero aquí el problema lo dominan el calendario local y la oferta, que un modelo sin reentrenar con una regresión lineal de calendario no capta tan bien como V4.

## 10. Limitaciones

1. **Selección implícita en el diseño de los conjuntos.**
   - La regla y los tres diseños de conjunto estaban escritos desde la 01:21, antes de cualquier resultado. Lo que se concretó a las 06:05, ya conocidos los resultados de las familias, fue el subconjunto diverso y la lista de «mejores de cada familia». El subconjunto diverso, por ejemplo, incluye a CatBoost y a Prophet semanal, señalados como complementarios tras ver 2025. El ganador, (c) sobre los 40 modelos, solo depende de esa lista en enero, cuando usa pesos iguales sobre ella; de febrero en adelante sus pesos salen de los meses anteriores.
   - Las reglas de pesos y miembros son sin fuga, pero la elección de qué conjuntos probar no es ciega. Por eso pesan la corrección múltiple y la prueba en 2024.
2. **La lista de enero se apoya en evidencia previa de distinto tipo:** validaciones de 2024 en ventanas distintas por familia, y ninguna para los fundacionales sin reentrenar.
3. **El ganador es poco práctico.** Exige mantener los 40 modelos para reestimar los pesos cada mes, aunque solo 14 reciban peso. Una versión reducida a esos 14 sería una elección a posteriori que no se evaluó.
4. **Pesos inestables entre meses.** Con 40 miembros muy correlacionados, el NNLS pasa peso de un boosting a otro. Por ejemplo, `hgb_poisson` baja de 0,19 a 0. El diverso es más estable.
5. **"Con β" es una interpretación** (sección 5): en E12 no había un β definido.
6. **Comparaciones múltiples aproximadas.** Holm y Bonferroni con el bootstrap de días tratan las 51 comparaciones como si fueran una familia cerrada. La versión amplia (m = 89) solo cuenta lo documentado por las familias.
7. **Tiempos con la máquina compartida.** Durante la corrida de 2024 había 5 procesos en paralelo y otro proceso ajeno, así que los costos de la sección 7 son orientativos.
8. **2024 es una prueba más dura que 2025 para los modelos que aprenden de la historia.**
   - Enero de 2024 se entrena solo con 2023, y V4 marca 18,3 % ese mes.
   - Junio de 2024 es atípico: 8,8 % de viajes sin registro y WAPE de 23 a 27 % en todos los modelos.
   - TFT y CatBoost empeoran mucho y AutoETS mejora. La prueba confirma o descarta ganancias frente a V4 en otro año, pero el tamaño de las diferencias depende del año.
9. **El ganador no tiene prueba fuera de la muestra de selección.** La conclusión sobre su fragilidad se infiere del apilamiento diverso y del ad hoc V4 + TFT, que comparten su mecanismo.
10. **Un solo protocolo de pesos.** No se probaron pesos con encogimiento hacia pesos iguales ni ventanas mínimas para el NNLS. Habría sido ajustar después de ver 2025 y 2024; queda como propuesta (sección 7).

## 11. Cómo reproducir y archivos

Desde la carpeta del proyecto, con el Python del entorno aislado (`venv_e12`). Para que Lightning no escriba en el proyecto, `run_2024.py` se corre desde `scratchpad\trabajo_e12`.
```bash
PY="C:/Users/Usuario/AppData/Local/Temp/claude/d--Ruben-universidad-machine-learning-DATA-CHALLENGE/74e3ac63-631e-4b5a-85a3-594592559f62/scratchpad/venv_e12/Scripts/python.exe"
E12="D:/Ruben/universidad/machine_learning/DATA CHALLENGE/experimentos/E12_comparacion_modelos"
export PYTHONIOENCODING=utf-8 MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
"$PY" "$E12/run_ensamble.py" --fase registrar     # 8 ensambles nuevos -> predicciones/, resultados/   (~5 s)
"$PY" "$E12/run_ensamble.py" --fase ranking       # ranking.csv, tabla_modelos.csv, corrección múltiple (~5 s)
"$PY" "$E12/run_ensamble.py" --fase robustez      # segmentos, β, sin enero, parejas (~5 s)
# prueba en 2024 (en paralelo; TFT y TimesFM usan la GPU), desde una carpeta de trabajo fuera del proyecto:
cd "C:/Users/Usuario/AppData/Local/Temp/claude/d--Ruben-universidad-machine-learning-DATA-CHALLENGE/74e3ac63-631e-4b5a-85a3-594592559f62/scratchpad/trabajo_e12"
"$PY" "$E12/run_2024.py" --fase predecir --modelo chronos2_cov
"$PY" "$E12/run_2024.py" --fase predecir --modelo arboles            # V4, híbrido, Tweedie, CatBoost
"$PY" "$E12/run_2024.py" --fase predecir --modelo tft --semilla 42   # ídem 43 y 44; la última junta las 3
"$PY" "$E12/run_2024.py" --fase predecir --modelo autoets_cal
"$PY" "$E12/run_2024.py" --fase predecir --modelo prophet_semanal
"$PY" "$E12/run_2024.py" --fase predecir --modelo timesfm25_xreg
"$PY" "$E12/run_2024.py" --fase evaluar            # -> resultados.json["validacion_2024"]
CUDA_VISIBLE_DEVICES="" "$PY" "$E12/medir_chronos2_cpu.py"   # costo del híbrido sin GPU (~4 min)
"$PY" "$E12/run_ensamble.py" --fase produccion    # costos, evidencia y recomendación -> resultados.json
"$PY" "$E12/run_ensamble.py" --fase figuras       # fig1-fig4
```

| Archivo | Contenido |
|---|---|
| `run_ensamble.py` | Fases `registrar`, `ranking`, `robustez`, `produccion` y `figuras` (`--fase todo` las corre todas en ~10 s): definición de los ensambles (lista de enero, pool, (a), (b), (c), ad hoc), ensamble rodante sin fuga, corrección múltiple, robustez, costos de producción y figuras |
| `run_2024.py` | Prueba en 2024: reutiliza sin modificarlo el código de cada familia, con los pliegues del arnés cambiados en memoria a 2024. También arma los ensambles de 2024 y los compara con V4 |
| `medir_chronos2_cpu.py` | Costo de producción del híbrido: inferencia de Chronos-2 para una semana (51 series × 7 días) en CPU con 2 hilos, comparada con la GPU. Escribe `resultados.json["produccion"]` |
| `resultados.json` | `resumen` (ganador, finalistas, 2024 y recomendación); `registro` (definición, pesos por mes y métricas de los 8 ensambles nuevos); `ranking` (regla, ganador, finalistas, corrección); `robustez`; `validacion_2024`; `produccion` (costos, evidencia y la medición de Chronos-2 en CPU) |
| `ranking.csv` | Ranking completo: 51 candidatos y 9 referencias, con regla, elegibilidad, p de Holm e IC de Bonferroni (m = 51 y m = 89) |
| `tabla_modelos.csv` | Regenerada con `A.resumen_modelos(guardar=True)`: los 55 resultados del arnés |
| `fig1_ranking_wape_ic.png` | Los 24 mejores candidatos y las referencias: diferencia con V4, IC 95 % e IC de Bonferroni, y WAPE |
| `fig2_finalistas_segmentos.png`, `fig3_finalistas_mes.png` | Ganador, finalistas y V4 + TFT por ruta, tipo de día, franja y mes |
| `fig4_2024_vs_2025.png` | Diferencia con V4 en 2025 y en 2024 de los candidatos y miembros que se pudieron repetir |
| `validacion_2024/pred/`, `validacion_2024/cache/`, `validacion_2024/logs/` | Predicciones de 2024 por modelo (`idruta, dia, hora, prediccion, corte`), puntos de control y registros |
| `predicciones/ens_conj_*`, `predicciones/ens_adhoc_*` y sus `resultados/*.json` | Los 8 ensambles nuevos en el formato del arnés. Los pesos por mes están en `notas` |

## Verificación

**Veredicto: confiable con reservas.** Verificación independiente del 07-10-2026, sin conexión a la base de datos y sin modificar código ni resultados. Todas las cifras clave se recalcularon con código propio, sin importar las funciones de evaluación del arnés: se leyeron los Parquet de `predicciones/` y `validacion_2024/pred/`, el objetivo de 2025 de `E11_modelo_mejorado/predicciones_2025.parquet` y el de 2024 de `cache/panel_v4.parquet`. Scripts y salidas: `scratchpad\verif_e12\` (`verif_2025.py`, `verif_ensambles.py`, `verif_ens_familia.py`, `verif_2024.py`, `verif_extra.py`, `verif_chronos.py`).

**Cobertura y cortes.**
- Los 55 Parquet de 2025 tienen exactamente las mismas 18.615 franjas de E11, sin duplicados, NaN ni infinitos, y el mismo `real`.
- En todos, `dia − corte` ≥ 7 (mínimo 7). V4, V0 y B1 coinciden con E11 con diferencia 0.
- Los 9 Parquet de 2024 tienen 366 × 51 franjas con horizonte ≥ 7. Sin los dos días R5 quedan 18.564 franjas de 364 días.

**Cifras recalculadas (2025).** WAPE, diferencia con V4, IC bootstrap pareado por días (2.000 réplicas, semilla 42), meses mejores y regla: coinciden en los 55 resultados con `resultados/*.json` (diferencia < 10⁻⁹) y con la tabla de la sección 2. Con otra semilla (2026) los extremos de los IC se mueven ≤ 0,04 puntos y ninguna conclusión cambia.

| Modelo | WAPE | Dif. con V4 [IC 95 %] | Meses mejor | p de Holm | IC de Bonferroni (m = 51) |
|---|---|---|---|---|---|
| `ens_conj_c_nnls_todos` | 13,385 % | −0,554 [−0,690; −0,415] | 12/12 | 0,002 | [−0,769; −0,284] |
| `ens_conj_c_nnls_diverso` | 13,418 % | −0,521 [−0,650; −0,376] | 12/12 | 0,002 | [−0,732; −0,263] |
| `ens_adhoc_V4_tft_nnls` (no elegible) | 13,475 % | −0,464 [−0,587; −0,339] | 12/12 | 0,002 | [−0,663; −0,246] |
| `ens_conj_a_media_V4_mejor_familia` | 13,586 % | −0,353 [−0,485; −0,211] | 12/12 | 0,002 | [−0,554; −0,102] |
| `hibrido_V4_chronos2cov` | 13,619 % | −0,320 [−0,430; −0,219] | 11/12 | 0,002 | [−0,507; −0,144] |
| `ens_conj_b_top3_rodante` | 13,634 % | −0,305 [−0,371; −0,236] | 12/12 | 0,002 | [−0,407; −0,192] |
| `ens_adhoc_V4_prophet_semanal_nnls` (no elegible) | 13,718 % | −0,222 [−0,322; −0,108] | 11/12 | 0,015 | [−0,389; −0,024] |
| `ens_conj_b_top5_rodante` | 13,727 % | −0,212 [−0,299; −0,098] | 12/12 | 0,038 | [−0,337; −0,004] |
| `ens_adhoc_V4_nhits_nnls` (no elegible) | 13,750 % | −0,189 [−0,268; −0,112] | 11/12 | 0,002 | [−0,319; −0,055] |
| `ens_arboles_media_gbm` | 13,763 % | −0,176 [−0,231; −0,125] | 11/12 | 0,002 | [−0,275; −0,100] |
| `V4_lightgbm` | 13,939 % | — | — | — | — |
| `B1_manual` | 20,045 % | +6,106 [+4,771; +7,654] | 0/12 | — | — |
| `timesfm25` / `timesfm25_xreg` | 17,896 % / 14,964 % | +3,957 / +1,025 [+0,670; +1,434] | 1/12 / 0/12 | 1 | — |

- **También coinciden** las cifras secundarias de 2025: parejas entre finalistas, "sin enero", los 9 segmentos, los IC por mes, las pruebas t (p = 2,9·10⁻⁷) y Wilcoxon (0,0005), el MAE, el RMSE, el sesgo y el total diario.
- **Pesos del ganador.** Con pesos en febrero-diciembre quedan 14 miembros, con los promedios de la sección 3. Los pesos suman de 0,966 a 0,980 y V4 tiene peso 0 desde febrero.
- **TimesFM.** Peso 0 en el diverso de febrero a diciembre. El costo en CPU de la sección 7 (228 s; diferencia media de 0,16 y máxima de 38 pasajeros) coincide con `resultados.json["produccion"]`.

**Fugas.** No se encontró ninguna.
- **(a) Corte d − 7.** Revisé el código:
  - arnés: `cortar`, `ventanas_contexto` y `pronostico_rodante`;
  - fundacionales: `contextos_diarios` y covariables solo de calendario. XReg de TimesFM ajusta una regresión por llamada, con las 51 series de un mismo corte;
  - redes: ventanas de entrenamiento que terminan antes de `ini`, contexto que termina en el corte y, como variables futuras, solo calendario y `lag364`;
  - clásicos: `pronostico_rodante` y regresores de calendario;
  - CNN: `ventanas_cuadricula`;
  - árboles: las 77 variables de V4.

  Todo cumple el corte d − 7.
- **(b) Híbrido.** La caché de Chronos-2 cubre del 29-1-2023 al 31-12-2025 con corte = d − 7 en todas sus filas. Coincide exactamente con `predicciones/chronos2_cov.parquet` (2025) y con `validacion_2024/pred/chronos2_cov.parquet` (2024).
  - **Prueba empírica en filas de entrenamiento.** Rehíce con código propio, en CPU, el pronóstico de Chronos-2 para el 14-6-2023, el 20-3-2024 y el 5-11-2024.
  - **Resultado.** Con contexto hasta d − 7 reproduce la caché con diferencia 0. Con contexto hasta d − 1, en cambio, difiere entre 16 y 35 pasajeros de media.
- **(c) Ensambles.** Reconstruí desde los miembros los 12 ensambles registrados (8 nuevos y 4 de familia), con pesos y miembros del mes m estimados solo con los meses < m.
  - **Resultado.** Reproducen los Parquet guardados con diferencia máxima 0.
  - **Pool.** Tiene los 40 individuales registrados, y la lista de enero está en el código.
  - **Evidencia de la lista de enero.** La comprobé en archivos anteriores a 2025:
    - Tweedie: 15,83 % frente a 15,86 % de V4 en oct-dic 2024;
    - TFT: 17,16 % en el piloto de sep-dic 2024;
    - AutoETS con calendario: 17,33 % y Prophet: 17,95 % en jul-dic 2024.
  - **Para comparar.** Con los pesos estimados con los 12 meses (con fuga), el ganador marcaría 13,24 %, no 13,39 %.
- **(d) Hiperparámetros.** Ninguno se eligió con 2025.
  - Árboles: oct-dic 2024. Clásicos: jul-dic 2024. Redes: piloto de sep-dic 2024.
  - Fundacionales: sin reentrenar, con covariables fijadas a priori.
  - Las variantes añadidas tras ver 2025 se registraron como candidatos aparte.

**Regla y corrección múltiple.**
- **Regla.** Está bien aplicada: cumplen 12 candidatos, el ganador es el de menor WAPE entre los elegibles y ningún ad hoc queda primero.
- **Holm.** Reimplementado en paso descendente, con 50.000 réplicas y semilla 42. Da los mismos p ajustados que `ranking.csv` (diferencia < 10⁻¹⁶), y la versión secuencial "de libro" rechaza los mismos 11.
- **Bonferroni.** Los IC al 99,90 % (m = 51) y al 99,94 % (m = 89) coinciden. Solo cae `ens_V4_chronos2_cov_nnls` (p de Holm 0,69), y `top5` cruza el 0 con m = 89.

**Prueba de 2024.**
- **Protocolo equivalente.** Pliegues mensuales con entrenamiento anterior a cada mes, h = 7 y mismas configuraciones, semillas de TFT, filas y pesos. Enero de 2024 solo ve 2023.
- **Cifras.** Se reproducen: V4 15,734 % (sesgo +1,96 %). Híbrido −0,329 [−0,504; −0,143], 10/12. (a) −0,493 [−0,706; −0,261], 10/12. Diverso −0,234 [−0,489; +0,088]. V4 + TFT −0,102 [−0,482; +0,424]. TimesFM con XReg +0,717 [+0,358; +1,119], 1/12. También se reproducen las parejas, los pesos de febrero y el "sin enero".
- **Estabilidad.** Con semillas 1 a 5, el IC del híbrido queda entre [−0,51; −0,15] y [−0,50; −0,14].

**Reservas.**
1. **2024 no es del todo independiente.** Con su segundo semestre se eligieron configuraciones de las familias y la lista de enero que define (a). Para el híbrido sí es una prueba limpia; para (a), el −0,49 de 2024 es algo optimista. Corregido en la sección 6.
2. **Los conjuntos no son ciegos a 2025.** La lista de enero y el subconjunto diverso los fijó alguien que ya conocía los resultados de 2025 (limitación 1). La regla de pesos no tiene fuga, pero "fijado de antemano" exagera. Corregido en la respuesta corta.
3. **El −0,55 del ganador probablemente es optimista.** Es el mejor de 51 sobre los mismos datos, y su mecanismo (NNLS con TFT) no se sostuvo en 2024. Holm y Bonferroni controlan que la mejora no sea un falso positivo, pero no el sesgo de su tamaño. El README ya lo advierte (secciones 6 y 10).
4. **"Único candidato que cumple en los dos años"** solo vale para los 6 candidatos repetidos en 2024. Corregido en la sección 7.
5. **Menores, sin efecto en las conclusiones.**
   - N-HiTS recibe `peso` como `insample_mask` en la predicción. Esa máscara incluye la etiqueta a posteriori `atipico` de días del contexto, cuando la regla del arnés dice no usarla como entrada. Su peso en el ganador es de solo 0,05.
   - En todo el protocolo, como en E11, el entrenamiento y los pesos llegan hasta el día anterior al mes, posterior al corte d − 7 de sus primeros 6 días. Afecta igual a V4 y a todos los candidatos.
   - El comentario de `hibrido_v4_chronos2.py` dice que el 29-1-2023 es el primer día con `pasajeros_total_m4sem`, pero hay 1.070 filas de entrenamiento anteriores (desde el 8-1-2023) sin las variables de Chronos-2. LightGBM las trata como NaN, así que no hay fuga.

**Correcciones al README (antes → después).**
- **Respuesta corta.**
  - Antes: "Se fijó de antemano y no tiene fuga."
  - Después: "Su regla se fijó antes de calcularlo, aunque ya se conocían los resultados de las familias en 2025 (limitación 1), y sus pesos no tienen fuga."
- **Sección 6.**
  - Antes: "2024 no intervino en ninguna elección: es una prueba fuera de la muestra de selección."
  - Después: "2024 no intervino en la elección del ganador ni de los finalistas, pero no es del todo virgen: con su segundo semestre las familias eligieron configuraciones (…) y se fijó la lista de enero que define (a). Para el híbrido (…) sí es una prueba fuera de la muestra."
- **Sección 7.**
  - Antes: "Junto con (a), es el único candidato que cumple la regla en los dos años"
  - Después: "Junto con (a), es el único de los candidatos repetidos en 2024 que cumple la regla en los dos años (6 de los 12 que la cumplen en 2025 no se repitieron, entre ellos el ganador)"

**Recomendación de producción: se sostiene.**
- **Diseño y fugas.** El híbrido tiene un diseño fijado a priori, no tiene fuga (verificado de forma empírica en las filas de entrenamiento) y su prueba en 2024 es limpia. Repite −0,32 / −0,33 con IC entero bajo 0 y su sesgo es como el de V4.
- **Frente a las alternativas.** En 2024 ninguna alternativa le gana con significancia. En 2025, el diverso y el ganador sí le ganan (−0,20 y −0,23), pero su mecanismo falló en 2024.
- **Costo.** El costo medido en CPU respalda la recomendación.

## Modelo para producción: `modelo_final_hibrido.py`

Es el equivalente de `E11_modelo_mejorado/modelo_final.py` para el híbrido recomendado en la sección 7 (`hibrido_V4_chronos2cov`). No se conecta a la base de datos ni modifica E11. Lee `datos/*.parquet`, los calendarios de E10, `E11_modelo_mejorado/calendario_2026.csv` y los pesos locales de `amazon/chronos-2`; fija `HF_HUB_OFFLINE=1`, así que no consulta la red.

**Qué hace.**
1. **Entrena un modelo por antelación H = 7, 14, 21 y 28 días.** Cada uno es LightGBM V4 con:
   - las 77 variables de V4 desplazadas a H (`comun_e11.desplazar_horizonte`; rezagos corregidos por viajes sin registro);
   - las mismas filas (desde 2023 hasta el origen, sin los días R5), pesos (0,25 en días atípicos de E10; 0,1 en franjas con ≥ 25 % sin registro), hiperparámetros y semilla 42;
   - las 4 variables de Chronos-2: `fm_c2`, `fm_c2_q10`, `fm_c2_q90` y `fm_c2_ratio`.

   En cada fila de entrenamiento d, Chronos-2 (variante `cov`, sin reentrenar) se corre con contexto hasta d − H y se toma el paso H:
   - **H = 7.** Se reutiliza la caché de E12 (`modelos_fundacionales/cache/chronos2_cov_todos_los_dias.parquet`), la misma del backtest.
   - **H = 14, 21 y 28.** Salen de `cache_hibrido/`. Cada corte da los 28 pasos, así que 1.061 cortes (22-01-2023 a 17-12-2025) cubren los tres modelos. El script calcula y guarda solo los cortes que faltan.
2. **Pronostica [desde, hasta] desde el origen**, el último día observado (por defecto, el 31-12-2025).
   - Cada fecha d usa el modelo H = 7 × ⌈(d − origen)/7⌉, como E11, o el que se fije con `--antelacion`.
   - Los rezagos de V4 quedan a H días.
   - Chronos-2 pronostica 28 días con contexto hasta el origen y el calendario de cada fecha como covariable futura:
     - festivos del paquete `holidays` (Reyes, el 12-01-2026);
     - Carnaval calculado desde la Pascua;
     - vacaciones de `calendario_2026.csv`: colegios hasta el 25-01 y universidades todo enero.
   - El pronóstico del origen se guarda en la caché: la semana siguiente pasa a ser historia.
3. **V4 en sombra.** En la misma corrida se entrena V4 con las mismas filas (columna `pasajeros_pred_V4`). Sirve para comparar semana a semana, como pide la sección 7, y de respaldo si Chronos-2 falla.

**Salidas.**
- **`pronostico_2026_enero_hibrido.parquet`** (y su `.csv`). Tiene 1.428 filas (3 rutas × 28 días × 17 horas de salida) con las columnas de E11 (`idruta, ruta, dia, hora, dia_semana, tipo_dia, festivo, vac_escolar, vac_univ, carnaval, semana_santa, horizonte_dias, modelo, pasajeros_pred`) más `pasajeros_pred_V4`, `fm_c2`, `fm_c2_q10` y `fm_c2_q90`.
- **`pronostico_2026_enero_hibrido_semanal.csv`.** Totales por ruta y semana del híbrido, V4 en sombra, E11, el ensamble diario de E8 y 2025 alineado (364 días antes).
- **`modelos_hibrido/`.** Un modelo por H (`modelo_hibrido_H*.txt`) y `metadatos_*.json`, con filas, ganancia de Chronos-2, totales y tiempos. Ahí también quedan los JSON de las comprobaciones.

**Cómo correrlo cada semana** (desde la carpeta del proyecto, con el Python del entorno aislado):
```bash
PY="C:/Users/Usuario/AppData/Local/Temp/claude/d--Ruben-universidad-machine-learning-DATA-CHALLENGE/74e3ac63-631e-4b5a-85a3-594592559f62/scratchpad/venv_e12/Scripts/python.exe"
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
# 4 primeras semanas de 2026 con datos hasta el 31-12-2025 (lo que se corrió aquí)
"$PY" experimentos/E12_comparacion_modelos/modelo_final_hibrido.py
# cada semana: 1) actualizar datos/progvehiculos.parquet y datos/conteo_viajes.parquet; 2) mover el origen
"$PY" experimentos/E12_comparacion_modelos/modelo_final_hibrido.py --origen 2026-01-07 --desde 2026-01-08 --hasta 2026-02-04 --salida experimentos/E12_comparacion_modelos/pronostico_2026-01-08.parquet
# el mismo modelo para todas las fechas (deben quedar a <= H días del origen)
"$PY" .../modelo_final_hibrido.py --origen 2026-01-07 --desde 2026-01-08 --hasta 2026-01-14 --antelacion 7 --salida ...
# comprobaciones
"$PY" .../modelo_final_hibrido.py --backtest 2025-03 [--panel-e12]   # protocolo de E12 en un mes frente a lo guardado
"$PY" .../modelo_final_hibrido.py --verificar-fuga                   # origen simulado: 30-11-2025
"$PY" .../modelo_final_hibrido.py --solo-historia --dispositivo cuda # precalcular la historia de Chronos-2 (una vez)
```
- **Origen.** Es el último día con datos completos. Antes de pronosticar, conviene revisar que la semana nueva no tenga caídas de registro masivas: la regla mecánica de fallas (peso 0,1) sí se aplica sola, pero las etiquetas de días atípicos de E10 no existen para las semanas nuevas.
- **Primeras semanas de 2026.** Correr en paralelo con V4 (la columna en sombra) y comparar el WAPE semanal antes de reemplazarlo (sección 7).

**Requisitos.**
- **Python.** El entorno aislado (`requisitos_e12.txt`): `chronos-forecasting` 2.3.2 (con torch 2.11; basta la versión de CPU), `lightgbm` 4.7.0, `pandas` 2.3.3, `holidays` y `pyarrow`.
- **Pesos.** Los de `amazon/chronos-2` en la caché local de Hugging Face. `comun_e12` apunta `HF_HOME` a `scratchpad/hf_cache`; en otra máquina hay que copiar esa carpeta o fijar `HF_HOME`.
- **Sin GPU.** `--dispositivo cpu` es el valor por defecto y usa 2 hilos (`comun_e12`). La GPU solo sirvió para precalcular la historia una vez.
- **Versiones fijas.** Hay que fijar la de `chronos-forecasting` y la revisión de los pesos (sección 7), y también la de pandas: con otra versión cambian en 10⁻¹⁴ algunas variables, y eso basta para mover unos pasajeros el pronóstico de LightGBM (comprobación a).

**Tiempos** (CPU, 2 hilos; medidos en esta máquina, a veces con otro proceso en paralelo).

| Paso | Tiempo |
|---|---|
| Panel (`comun_e11.construir_panel`) | 2-5 s |
| Pronóstico de Chronos-2 desde el origen (51 series × 28 días) | 25-46 s |
| 8 LightGBM (híbrido y V4 × 4 antelaciones) | 31-45 s |
| **Corrida completa** de 4 semanas con la historia ya calculada | **107 s** (enero de 2026: panel 2 s, importar y cargar Chronos-2 11 s, pronóstico del origen 46 s, 8 LightGBM 45 s); 70-73 s en las simulaciones de 2024 |
| Cada semana nueva | + 6 cortes de historia y el nuevo origen: 7 pronósticos de Chronos-2 (≈ 7 × 25-46 s ≈ 3-5 min). La primera vez (origen 07-01-2026) son 13 cortes, del 18 al 30-12-2025 (el 31-12 lo guardó la corrida de enero), más el origen |
| Historia completa, una vez (1.061 cortes) | 1.398 s (23 min) en la GPU (RTX 3050, lote 64); en CPU serían ≈ 7-13 h |

### Comprobaciones

**(a) Backtest de marzo de 2025** (`--backtest 2025-03`). Protocolo de E12: entrena con los días < 01-03-2025 y pronostica cada día d con rezagos y Chronos-2 hasta d − 7.
- **Con el panel guardado por el arnés** (`--panel-e12`, `cache/panel_v4.parquet`). Reproduce `predicciones/hibrido_V4_chronos2cov.parquet` con diferencia **0,0** en las 1.581 franjas: WAPE 14,403 % en los dos casos. El V4 en sombra también coincide con el de E11 con diferencia 0,0.
- **Con el panel reconstruido**, que es lo que hace el script en producción. La diferencia media es de 1,7 pasajeros por franja (máximo 16,5), con un total −0,02 % y un WAPE de 14,400 % frente a 14,403 %. El V4 en sombra difiere hasta en 34 pasajeros de E11.
- **Causa.**
  - El panel del arnés y las predicciones de E11 se calcularon con el Python global (pandas 3.0.5). El entorno aislado tiene pandas 2.3.3.
  - Las 4 desviaciones móviles `*_sd8sem` difieren en ≤ 6·10⁻¹⁴, y todas las demás variables coinciden exactamente.
  - Ese ruido cambia algún umbral de los histogramas de LightGBM, y con 600 árboles con submuestreo se nota en unos pasajeros.
  - No es un error del script. Para reproducir bit a bit hay que usar la misma versión de pandas que construyó el panel.

**(b) No usa información posterior al origen.**
- **En cada corrida, el script comprueba que:**
  - el panel no tenga objetivos después del origen (`construir_panel(fin_obs=origen)` ni siquiera lee esos viajes);
  - el contexto de Chronos-2 termine en el origen;
  - el pronóstico de las fechas futuras tenga corte = origen;
  - las variables de Chronos-2 de las filas de entrenamiento tengan corte = d − H.
- **Prueba empírica** (`--verificar-fuga`, origen simulado el 30-11-2025; `modelos_hibrido/verificacion_fuga.json`). Para las 28 fechas siguientes, cada una con su modelo H, las variables de V4 son **idénticas** (diferencia 0 y los mismos vacíos) con el panel observado hasta el origen y con el panel con todo diciembre.
  - El control positivo funciona: un rezago de 1 día, prohibido, sí cambia en 1.377 franjas.
  - Chronos-2 da exactamente lo mismo (diferencia 0) con la historia truncada en el origen que con la completa.
- **CPU frente a GPU.** El pronóstico del origen calculado en CPU coincide con el de la caché calculada en la GPU (simulación del 31-07-2024): diferencia máxima de 0,0009 pasajeros sobre una media de 783. Así, la historia calculada en la GPU vale para una producción solo con CPU.

**Simulación del modo producción** (no se pidió, pero prueba los modelos H = 14-28, que el protocolo de E12 no evaluó, y el uso real del script). En cada origen a fin de mes:
- los modelos (híbrido y V4) se entrenan solo hasta ese día;
- se pronostican desde ahí los 28 días siguientes, cada uno con su H;
- el resultado se compara con lo real.

**2025: 11 orígenes, del 31-01 al 30-11.** Son 44 semanas y 15.708 franjas (`modelos_hibrido/emulacion_produccion_2025.json`; script en `scratchpad/hibrido_prod/emulacion_2025.py`, 73-87 s por origen en CPU).

| Antelación | WAPE híbrido | WAPE V4 | Chronos-2 solo | Dif. | Semanas en que gana | Sesgo híbrido / V4 |
|---|---|---|---|---|---|---|
| H = 7 (días 1-7) | 13,48 % | 13,85 % | 14,52 % | −0,37 | 10 de 11 | −0,3 % / +0,7 % |
| H = 14 (días 8-14) | 13,41 % | 13,53 % | 14,31 % | −0,13 | 6 de 11 | +1,6 % / +0,9 % |
| H = 21 (días 15-21) | 14,37 % | 14,65 % | 15,54 % | −0,28 | 7 de 11 | +1,8 % / +2,1 % |
| H = 28 (días 22-28) | 13,56 % | 13,96 % | 14,16 % | −0,41 | 9 de 11 | 0,0 % / +0,5 % |
| **Total** | **13,70 %** | **13,99 %** | 14,63 % | **−0,30 [−0,45; −0,15]** | 32 de 44; 9 de 11 orígenes | +0,8 % / +1,0 % |

- **El IC** es el bootstrap pareado de días del arnés (2.000 réplicas, semilla 42).
- **La ganancia del modo producción (−0,30)** es la misma que la del protocolo de E12 con H = 7 (−0,32) y se mantiene en H = 14-28.
- **Dos orígenes pierden:** 28-02 (+0,21) y 30-11 (+0,24). Este último es el análogo más cercano a enero de 2026: diciembre, con fiestas, donde el híbrido pierde con H = 14 y 21 (+0,84 y +0,59). Conviene vigilar las semanas con fiestas.

**2024: 3 orígenes** (`scratchpad/hibrido_prod/evaluar_emulacion.py`):

| Origen | Fechas | WAPE híbrido | WAPE V4 | Chronos-2 solo | Semanas en que gana el híbrido (H = 7 / 14 / 21 / 28) |
|---|---|---|---|---|---|
| 31-07-2024 | 1-28 ago | 14,51 % | 15,36 % | 15,09 % | 4 de 4: −0,90 / −1,22 / −0,59 / −0,66 puntos |
| 31-08-2024 | 1-28 sep | 15,90 % | 16,17 % | 17,81 % | 4 de 4: −0,005 / −0,10 / −0,53 / −0,45 |
| 30-09-2024 | 1-28 oct | 15,73 % | 16,18 % | 16,10 % | 3 de 4: −0,34 / −2,09 / +0,32 / −0,03 |
| **3 orígenes** | 84 días | **15,38 %** (media) | **15,90 %** | 16,33 % | 11 de 12 semanas; −0,28 a −0,85 puntos por origen |

- **Sesgo.** El híbrido queda en −1,7 / −0,9 / −1,6 % y V4 en −2,9 / +0,05 / +1,9 %.
- **CPU frente a GPU.** En los tres orígenes, Chronos-2 en CPU coincide con la caché calculada en la GPU (diferencia máxima ≤ 0,001 pasajeros).
- **Alcance.** Son 3 orígenes, una evidencia limitada, pero coincide con 2025: la ventaja del híbrido no desaparece en H = 14-28.

**(c) Enero de 2026 frente a E11 y E8** (`pronostico_2026_enero_hibrido_semanal.csv`; datos hasta el 31-12-2025, salidas de 4 a 20 h).

| Ruta | Sem. 1 (1-7, H=7) | Sem. 2 (8-14, H=14) | Sem. 3 (15-21, H=21) | Sem. 4 (22-28, H=28) | Total híbrido | E11 (V4) | Dif. con E11 | 2025 alineado | Var. con 2025 | E8 ensamble diario |
|---|---|---|---|---|---|---|---|---|---|---|
| SILENCIO | 43.370 | 50.201 | 57.301 | 62.190 | 213.062 | 215.670 | −1,2 % | 240.116 | −11,3 % | 221.685 |
| CRA 54 | 83.781 | 97.894 | 114.958 | 124.469 | 421.103 | 436.172 | −3,5 % | 499.505 | −15,7 % | 446.519 |
| CL 72 | 28.714 | 33.884 | 38.279 | 41.047 | 141.925 | 145.946 | −2,8 % | 160.723 | −11,7 % | 146.652 |
| **Total** | 155.865 | 181.979 | 210.539 | 227.706 | **776.090** | 797.789 | **−2,7 %** | 900.344 | **−13,8 %** | 814.856 |
| E11 por semana | 162.055 | 190.544 | 213.840 | 231.349 | | | | | | |
| Híbrido frente a E11 | −3,8 % | −4,5 % | −1,5 % | −1,6 % | | | | | | |

- **El V4 en sombra es E11.** Da 797.953 frente a 797.789 (+0,02 %). Por franja difiere en 4,4 pasajeros de media (máximo 46), por la versión de pandas (comprobación a). La cadena de V4 del script es, por tanto, la de E11.
- **El híbrido queda un 2,7 % por debajo de E11.** Por franja difiere en 35 pasajeros de media.
  - Chronos-2 solo da 846.633 (+6,1 % sobre E11), pero LightGBM lo baja. En el entrenamiento, Chronos-2 con calendario sobrestima (`chronos2_cov`: sesgo de +4,1 % en 2025), y LightGBM aprendió a corregirlo.
  - Las diferencias mayores están en las semanas 1 y 2: vacaciones, Año Nuevo y Reyes.
  - Chronos-2 se lleva el 91-92 % de la ganancia de los árboles en los cuatro modelos, como en E12.
- **La forma es la de E11.**
  - La semana 4 tiene un 43-49 % más de pasajeros que la 1 (E11: +43 %).
  - El 26-01, vuelta a clases de los colegios oficiales, sube un 10-13 % frente al lunes 19-01 (E11: +12 %).
  - Reyes (12-01) queda entre −5,5 % y +7,3 % frente al domingo anterior (E11: entre −7 y −13 %).
- **Frente al pronóstico de E8:** −4,8 % sobre su ensamble diario (E11: −2,1 %).
- **Frente a lo real de 2026: no es comparable semana a semana.** Lo real que analizó E8 (`timbradas_anio`) solo trae agregados del 1-ene al 10-ago-2026 por ruta × día de la semana × categoría × hora de fin de viaje, sin fechas. No permite sacar el total del 1 al 28 de enero ni el de una semana. Lo único comparable es el nivel.
- **Error de nivel de 2026.**
  - **Lo que midió E8.** Del 1-ene al 10-ago-2026, frente a las mismas fechas de 2025: +7,5 % de subidas (SILENCIO +14,1 %, CRA 54 +2,5 %, CL 72 +13,2 %) y **+14,6 % de viajes** (SILENCIO y CL 72 cerca de +24 %). Todos sus modelos quedaron entre 7 y 17 % cortos.
  - **Lo que implica para enero.** Si enero de 2026 siguiera ese +7,5 %, el nivel real del 1 al 28 de enero rondaría los 967.900 pasajeros (900.344 × 1,075). El híbrido quedaría ≈ 20 % corto (E11 ≈ 18 %, E8 ≈ 16 %). Con la variación de cada ruta: SILENCIO −22 %, CRA 54 −18 % y CL 72 −22 %.
  - **De dónde sale el −13,8 % frente a 2025 alineado:**
    - calendario: el 1 y el 12 de enero son festivos en 2026, y sus pares alineados de 2025 fueron laborales;
    - la tendencia de −8 % anual que los modelos ven en los rezagos y en el contexto de Chronos-2 (diciembre de 2025: −10,4 % interanual);
    - el cambio de 2026 es sobre todo de oferta: Sobusa aumentó un 14,6 % los viajes. Ningún modelo entrenado hasta el 31-12-2025 lo puede anticipar, porque no reciben la oferta programada ni datos de 2026.
  - **El híbrido queda algo más lejos.** Como queda 2,7 % por debajo de V4, en enero de 2026 estaría unos 2 puntos más lejos del nivel que sugiere E8. Es un error de nivel común a todos los modelos, no de forma.
  - **Remedio.** Reentrenar cada semana con los datos de 2026: con 1-2 semanas, el modelo H = 7 y el contexto de Chronos-2 ya ven el nuevo nivel. Si Sobusa confirma el aumento de oferta, conviene agregar la oferta programada como variable.
  - **Reserva.** E8 advierte que parte de la subida podría venir del proceso de `timbradas_anio`. Solo `progvehiculos` de 2026 lo confirma.

**(d) Tiempo en CPU** (tabla de tiempos).
- La corrida de enero tarda **107 s** en CPU con 2 hilos, con la historia ya calculada.
- Una semana normal de producción suma 6 cortes de historia y el nuevo origen: 7 pronósticos de Chronos-2 de 25 a 46 s, unos **4-6 min en total**, en línea con los ~4 min por semana que midió E12 (228 s).
- Pronosticar 4 semanas desde un origen fijo cuesta un solo pronóstico de Chronos-2 de 28 pasos (46 s), no 28 pronósticos de 7 pasos.
- La única parte cara es la historia de H = 14-28, que se calcula una vez: 23 min en la GPU o ≈ 7-13 h en CPU. Queda guardada en `cache_hibrido/` (19 MB).

### Limitaciones

1. **Antelación de Chronos-2 en producción.**
   - Al entrenar, la variable siempre tiene antelación exactamente H. En producción, el pronóstico desde el origen tiene antelación k = d − origen, entre H − 6 y H: usa información algo más reciente que la que vio el modelo.
   - No es fuga, porque toda esa información es anterior al origen.
   - El modelo no aprendió con esas antelaciones, aunque en las simulaciones del modo producción (2024 y 2025) no se ve un problema.
2. **H = 14-28 no tienen la evaluación por pliegues de E12**, que solo midió H = 7. La evidencia son las simulaciones del modo producción: 11 orígenes de 2025, de los mismos datos con que E12 eligió el híbrido, y 3 de 2024. En H = 14 la ganancia es pequeña (−0,13; 6 de 11 semanas).
3. **Nivel de 2026.**
   - Ningún modelo entrenado con 2023-2025 (−8 % anual) puede anticipar el cambio que muestra `timbradas_anio`: +7,5 % de subidas y +14,6 % de viajes.
   - El híbrido solo se ajusta a través de los rezagos y del contexto de Chronos-2, y para eso necesita datos de 2026.
   - Con 1-2 semanas de `progvehiculos` de 2026 el modelo H = 7 ya ve el nuevo nivel. Los modelos H = 21-28 tardan 3-4 semanas.
4. **Sin etiquetas de días atípicos para las semanas nuevas.** Los pesos de E10 se construyeron a posteriori. En producción solo actúa la regla mecánica de fallas, igual que en V4.
5. **Mismas omisiones que V4.** No usa la oferta programada como variable, y los eventos de `novedades_viales` valen 0 en 2026.
6. **Reproducibilidad.** Depende de las versiones de pandas, LightGBM y `chronos-forecasting` (comprobación a). CPU y GPU dan pronósticos de Chronos-2 iguales a menos de 0,001 pasajeros.

