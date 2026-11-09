# E11 · Modelo mejorado de pronóstico y pipeline de producción

**Pregunta.** ¿Se puede mejorar el LightGBM de E1 (WAPE 14,4 % con h = 7) añadiendo calendarios escolar y universitario, climatología y un mejor manejo de los días atípicos? ¿Cómo queda un pipeline que Sobusa pueda correr cada semana?

**Respuesta corta.**
- **Calendarios y climatología: casi nada.** Los calendarios bajan el WAPE 0,05 puntos y la climatología otros 0,03. Ninguna de las dos diferencias es significativa.
- **Lo que sí mejora es no aprender de datos corruptos.** Se bajó el peso, en el entrenamiento, de los días atípicos no predecibles y de las franjas con viajes sin registro (el equipo a bordo caído). El WAPE pasa de **14,40 % a 13,94 %** con h = 7: −0,46 puntos, IC 95 % [−0,60; −0,33], mejor en 10 de 12 meses. Con h = 1 pasa de 14,10 % a 13,83 %.
- **La mejora viene sobre todo de agosto de 2025.** Ese mes E1 se quedaba 10 % corto y la variante nueva solo 2 %. Sin agosto, la ganancia es de 0,21 puntos (prueba t por pliegue p = 0,10; Wilcoxon p = 0,003).
- **Clima observado y recencia no ayudan.** Conocer la lluvia del mismo día empata con la variante sin ella (−0,02 puntos), lo que confirma E9. Dar más peso a los datos recientes empeora 0,05 puntos.
- **El ajuste anidado de hiperparámetros empeora** (+0,07 puntos), así que se conservan los de E1.
- **Variante elegida: V4.** La regla de selección se fijó antes de ver resultados. V4 es V3 más rezagos corregidos por fallas, y empata con V3 (diferencia de 0,006 puntos).
- **Producción.** `modelo_final.py` entrena V4 con 2023–2025 para H = 7, 14, 21 y 28 días y pronostica cualquier rango futuro. Para las 4 primeras semanas de 2026 prevé 797.788 pasajeros en salidas de 4 a 20 h: −11,4 % frente a las mismas fechas de 2025 alineadas por día de la semana y −2,1 % frente al ensamble diario de E8. Según E8, en 2026 la demanda subió, así que este nivel probablemente queda corto (sección 5).

**Ejecución.**
- Comando: `PYTHONIOENCODING=utf-8 MPLBACKEND=Agg python experimentos/E11_modelo_mejorado/run.py` desde la carpeta del proyecto.
- Tiempos: la corrida completa tardó 25,4 min (`run.log`). La descomposición de pesos y las figuras finales se generaron con `E11_REUSAR=1`, reutilizando las predicciones de `cache/`: 3,5 min y 41 s (`run_reuso.log`). La caché solo se reutiliza si coinciden las variables, los parámetros y la configuración.
- Configuración: semilla 42, `n_jobs = 2`. No se conecta a la base de datos.
- Arranque: la carpeta no existía cuando se reanudó la tarea tras el cierre de las 01:55 y no había procesos de Python activos, así que todo se hizo desde cero.

## 1. Método

**Panel.** `comun_e11.py` reconstruye el conjunto ruta × día × hora de salida de E1: 55.896 filas, 4 a 20 h. Se verificó contra `E1_lgbm_salida/datos_modelado_salida.parquet` y la diferencia máxima en las 83 columnas de modelado es 0. El V0 reproduce E1 exactamente: **WAPE 14,40 %** con h = 7 y 14,10 % con h = 1. El panel se puede extender a fechas futuras, con los objetivos vacíos después del último día observado.

**Variables nuevas.** Todas se conocen con cualquier antelación, salvo el nowcast.

| Grupo | Variables | Fuente |
|---|---|---|
| Calendario escolar | `vac_escolar` (todos los recesos de los colegios oficiales de Barranquilla) | `E10/calendario_escolar.csv` y, para 2026, la Resolución 07248 del 24-10-2025 (`calendario_2026.csv`): receso hasta el 25-01-2026 y clases desde el 26-01 |
| Calendario universitario | `vac_univ`: fuera del consenso (mediana) de clases de las universidades de E10 | `E10/calendario_universitario.csv`; 2026 supuesto (confianza baja; en enero todos los días son de vacaciones) |
| Régimen de la ventana de rezagos | `frac_vac_escolar_ventana`, `frac_vac_univ_ventana`, `frac_especial_ventana`: fracción de los 4 días de referencia (d−7 … d−28, o d−H … d−H−21) en vacaciones o festivo / Carnaval / Semana Santa | calendario |
| Quincena | `dias_desde_pago`: días desde el último día 15 o último día del mes. Complementa `quincena` de E1 | calendario |
| Climatología | `temporada`, `clim_p_mes_hora`, `clim_prob_mes_hora`, `clim_p_viaje4` (lluvia esperada de h a h+3) | Open-Meteo 2013–2022 (copia de E9), anterior al periodo evaluado |
| Nowcast (solo la variante N) | `p_h`, `max_prev3`, `p_viaje4`, `p_dia_4_21`: lluvia observada en la hora, las 3 previas, durante el viaje y en el día | `datos/clima_barranquilla_2023_2025.parquet` |

**Días atípicos: solo como peso, nunca como variable.**
- Se tomaron los 31 días de `E10/dias_atipicos.csv` cuya causa no es de calendario: fallas de registro, Sibus, paro, aguaceros, día cívico y días sin explicación. Suman 1.547 filas, y reciben **peso 0,25 en el entrenamiento**.
- Las franjas con al menos 25 % de viajes válidos sin registro (0 pasajeros y menos de 30 eventos GPS, definición de E10) reciben **peso 0,1**. Son 1.412 franjas, el 2,5 %. Este criterio es mecánico y se puede calcular el mismo día.
- Los pesos se fijaron antes de correr y solo afectan a filas anteriores al mes de prueba. El conjunto de prueba se evalúa completo, con sus días atípicos.

**Variantes.** Todas usan LightGBM Poisson con los hiperparámetros de E1: 600 árboles, tasa 0,03 y 31 hojas.

| Clave | Qué añade |
|---|---|
| V0 | E1 base, variante (a) |
| V1 | + calendarios (las seis variables de calendario de la tabla) |
| V2 | V1 + climatología |
| V3 | V2 + pesos para días atípicos y franjas con fallas |
| V4 | V3 + rezagos calculados con pasajeros corregidos por viajes sin registro (pax × válidos / con registro; franja vacía si falla > 80 %). El objetivo evaluado no se corrige |
| V5 | V3 + pesos por recencia (vida media de 365 días) |
| N | V3 + clima observado. Es una **cota**, no es pronosticable con 7 días |

**Protocolo y selección.**
- Se usaron 12 pliegues mensuales de 2025, cada uno entrenado con todo lo estrictamente anterior, con h = 1 y h = 7. B1 es la regla manual de 8 semanas.
- Comparación con V0: (a) diferencia de WAPE con IC 95 % por bootstrap pareado de días, como en E9; (b) diferencia de WAPE mensual con prueba t pareada y Wilcoxon sobre los 12 meses, como en E6.
- **Regla de selección, fijada antes de ver resultados:** entre V1 y V5, la de menor WAPE con h = 7 cuyo IC de la diferencia con V0 quede por debajo de 0. Si ninguna cumple, se queda V0.
- **Ajuste anidado de hiperparámetros** para la elegida. Para cada mes de prueba m, se entrenaron tres configuraciones con datos anteriores a m−1 y se validaron en m−1. Luego se reentrenó la ganadora con datos anteriores a m. Las configuraciones son: C0 (E1); C1 (15 hojas, 900 árboles, `min_child_samples` 100, λ = 5); C2 (400 árboles, `min_child_samples` 150, λ = 20, `colsample` 0,6).
- **Horizontes H = 14, 21 y 28.** El bloque de rezagos de la fecha d se toma de d − (H − 7), que tiene el mismo día de la semana y la misma hora. Así todas las referencias tienen al menos H días. `lag364` queda fijo.

## 2. Resultados (pasajeros por hora de salida, 2025, 12 pliegues)

**Tabla 1. Variantes**

| Variante | WAPE h=7 | WAPE h=1 | MAE h=7 | RMSE h=7 | Sesgo h=7 (pax/franja) | Total diario por ruta h=7 | Dif. vs V0 h=7 [IC 95 %] | Meses mejor |
|---|---|---|---|---|---|---|---|---|
| B1 manual (8 semanas) | 20,04 % | 20,04 % | 138,6 | 228,8 | +6,8 | 12,75 % | +5,65 [+4,38; +7,24] | 0/12 |
| V0 E1 | 14,40 % | 14,10 % | 99,6 | 147,9 | −2,3 | 5,55 % | — | — |
| V1 + calendarios | 14,35 % | 14,05 % | 99,2 | 147,0 | −2,8 | 5,43 % | −0,05 [−0,13; +0,03] | 6/12 |
| V2 + climatología | 14,32 % | 14,05 % | 99,1 | 146,9 | −2,7 | 5,42 % | −0,08 [−0,15; +0,00] | 7/12 |
| V3 + pesos atípicos | 13,95 % | 13,85 % | 96,4 | 143,7 | +9,0 | 4,89 % | −0,45 [−0,60; −0,33] | 11/12 |
| **V4 + rezagos corregidos (elegida)** | **13,94 %** | **13,83 %** | **96,4** | 144,0 | +9,8 | **4,86 %** | **−0,46 [−0,60; −0,33]** | 10/12 |
| V5 + recencia | 14,00 % | 13,88 % | 96,8 | 144,3 | +8,9 | 5,03 % | −0,40 [−0,53; −0,28] | 11/12 |
| N nowcast (cota) | 13,92 % | 13,85 % | 96,3 | 143,5 | +9,4 | 4,81 % | −0,48 [−0,60; −0,35] | 10/12 |
| V4 + ajuste anidado | 14,01 % | — | 96,9 | 144,6 | +9,8 | 4,94 % | −0,39 [−0,54; −0,25] | 9/12 |

- **Diferencias paso a paso con h = 7.** V1 frente a V0: −0,05 [−0,13; +0,02], p (t) = 0,47. V2 frente a V1: −0,03 [−0,07; +0,01]. **V3 frente a V2: −0,38 [−0,50; −0,26]**, 10/12 meses, p (Wilcoxon) = 0,016. V4 frente a V3: −0,01 [−0,05; +0,04]. V5 frente a V3: **+0,05 [+0,005; +0,09]**, peor. N frente a V3: −0,02 [−0,06; +0,01]. Con h = 1, el paso de los pesos vale −0,20 [−0,31; −0,11] y los demás pasos son nulos.
- **Pruebas por pliegue frente a V0, h = 7.** Para V4: prueba t p = 0,10, Wilcoxon p = 0,003. Diferencia mensual media −0,45 ± 0,87 puntos. El bootstrap de días da un IC estrecho, pero la prueba t por mes no es significativa porque la ganancia está concentrada en un mes (sección 3).
- **Selección.** V3, V4 y V5 cumplen la regla y V4 tiene el menor WAPE (13,939 % frente a 13,945 % de V3). **Operativamente V3 y V4 son el mismo modelo.** V4 solo añade la corrección de rezagos, que usa los eventos GPS del viaje.
- **Ajuste anidado.** La validación interna eligió C0 en 10 de 12 meses, C1 en enero y C2 en agosto. Resultado: 14,01 % frente a 13,94 %, es decir **+0,07 [+0,02; +0,13]: peor**. Con los 12 pliegues completos, C1 da 14,15 % y C2 14,19 %. Como en E1, el problema no pide otra capacidad; producción usa C0.

**Tabla 2. WAPE con h = 7 por ruta, tipo de día y franja**

| | SILENCIO | CRA 54 | CL 72 | Laboral | Sábado | Domingo/festivo | 4–8 h | 9–15 h | 16–20 h |
|---|---|---|---|---|---|---|---|---|---|
| B1 manual | 21,5 % | 18,0 % | 24,3 % | 17,6 % | 15,1 % | 48,6 % | 19,4 % | 19,9 % | 21,7 % |
| V0 E1 | 16,0 % | 12,0 % | 19,3 % | 13,9 % | 13,6 % | 20,2 % | 12,2 % | 14,5 % | 18,6 % |
| V2 + calend. + climat. | 15,9 % | 12,0 % | 19,3 % | 13,8 % | 13,7 % | 20,1 % | 12,0 % | 14,5 % | 18,7 % |
| **V4 elegida** | **15,5 %** | **11,5 %** | **19,1 %** | **13,4 %** | **13,5 %** | **19,7 %** | **11,4 %** | **14,2 %** | **18,4 %** |
| N nowcast (cota) | 15,5 % | 11,5 % | 19,1 % | 13,3 % | 13,4 % | 19,8 % | 11,4 % | 14,3 % | 18,2 % |

La mejora es pareja en las tres rutas: −0,5 puntos en SILENCIO y CRA 54 y −0,25 en CL 72. CL 72 y las tardes siguen siendo lo más difícil.

**Tabla 3. WAPE con h = 7 por tipo de día de prueba**

| Subconjunto (días de 2025) | B1 | V0 | V2 | V4 | N |
|---|---|---|---|---|---|
| Vacaciones escolares (85 días) | 28,7 % | 16,3 % | 15,9 % | 15,8 % | 15,7 % |
| Clases escolares (280) | 17,9 % | 13,9 % | 13,9 % | 13,5 % | 13,5 % |
| Vacaciones universitarias (134) | 22,3 % | 15,6 % | 15,5 % | 15,2 % | 15,2 % |
| Transición de periodo (159)¹ | 22,6 % | 15,5 % | 15,4 % | 14,8 % | 14,7 % |
| Días lluviosos, ≥ 5 mm (82) | 18,0 % | 14,3 % | 14,2 % | 13,9 % | 13,8 % |
| Días secos, < 1 mm (173) | 21,4 % | 14,4 % | 14,4 % | 14,0 % | 14,0 % |
| Días atípicos no predecibles de E10 (4) | 63,7 % | 61,3 % | 61,8 % | 63,3 % | 62,5 % |
| Franjas con ≥ 25 % sin registro (475 franjas) | 82,8 % | 67,0 % | 67,5 % | 71,2 % | 70,5 % |
| Días normales, sin atípicos ni fallas (362) | 19,4 % | 13,8 % | 13,7 % | 13,3 % | 13,3 % |

¹ Al menos media ventana de rezagos con otro régimen de vacaciones que el día pronosticado.

- **Los calendarios se notan solo donde deben**: −0,4 puntos en vacaciones escolares (16,3 % → 15,9 %), pero ese subconjunto es el 23 % de los días. En las transiciones apenas cambian (15,5 % → 15,4 %); la ganancia de V4 en transición (14,8 %) viene de los pesos. El modelo de E1 ya aprendía las vacaciones a través de `vacaciones`, `mes` y los rezagos.
- **Lluvia.** V4 rinde igual en días lluviosos y secos (13,9 % y 14,0 %). El nowcast gana 0,06 puntos en días lluviosos: no hay señal aprovechable, como en E9.
- **Precio de los pesos.** En las franjas con fallas, que son errores de datos y no demanda real, V4 empeora de 67,0 % a 71,2 %: ya no aprende a prever casi cero. Es el comportamiento deseado. **Para el despacho conviene planificar la demanda real, no la caída del equipo.**

**Tabla 4. Descomposición de los pesos (h = 7, informativa; no participa en la selección)**

| Variante | WAPE | Dif. vs V2 [IC 95 %] | Sin agosto | Meses mejor |
|---|---|---|---|---|
| V3: peso 0,25 a días E10 y 0,1 a franjas con fallas | 13,95 % | −0,38 [−0,50; −0,26] | — | 10/12 |
| V3a: solo días atípicos de E10 | 13,94 % | −0,38 [−0,51; −0,28] | −0,15 | 11/12 |
| V3b: solo franjas con fallas (regla mecánica) | 14,00 % | −0,32 [−0,44; −0,21] | −0,08 | 10/12 |
| V3c: excluir ambos (peso 0) | 13,99 % | −0,33 [−0,46; −0,21] | −0,09 | 9/12 |

**La mejora no depende del peso exacto.** La regla mecánica sola (V3b), que no necesita las etiquetas de E10, ya da el 84 % de la ganancia. Las dos reglas corrigen en buena parte las mismas filas: los días de falla de julio de 2025 están en ambas listas.

**Tabla 5. WAPE por mes con h = 7**

| Mes | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 | 25,7 | 21,6 | 21,6 | 21,8 | 16,6 | 23,2 | 18,0 | 20,8 | 13,9 | 16,4 | 17,0 | 25,6 |
| V0 | 14,0 | 12,6 | 14,5 | 13,1 | 13,4 | 16,2 | 16,3 | 17,2 | 12,8 | 13,7 | 12,7 | 16,9 |
| V4 | 13,7 | 12,6 | 14,2 | 12,9 | 13,4 | 16,0 | 15,6 | **14,1** | 12,6 | 13,3 | 12,8 | 16,7 |

**Tabla 6. WAPE según la antigüedad mínima de los datos (H)**

| H | 7 días | 14 días | 21 días | 28 días |
|---|---|---|---|---|
| B1 manual (8 semanas que terminan H días antes) | 20,0 % | 20,5 % | 20,9 % | 21,2 % |
| V0 E1 | 14,4 % | 14,6 % | 14,8 % | 14,8 % |
| V4 elegida | 13,9 % | 14,1 % | 14,3 % | 14,4 % |

**Pronosticar con 4 semanas de antelación cuesta solo 0,5 puntos.** V4 con H = 28 rinde lo mismo que E1 con H = 7. Por ruta y con H = 28: SILENCIO 16,0 %, CRA 54 11,9 %, CL 72 19,7 %.

**Importancia de variables.** Promedio de los pliegues de V4, h = 7: las 10 variables nuevas suman el **0,7 % de la ganancia**. Las mayores son `vac_escolar` 0,26 %, `frac_especial_ventana` 0,13 % y `frac_vac_escolar_ventana` 0,06 %; la climatología suma 0,11 % y `dias_desde_pago` 0,05 %. Modelo final con H = 7: media de las 4 mismas semanas 57,5 %, B1 26,7 %, tipo de día 2,9 %, media de 7 días 2,1 %, festivo 1,9 %. **El modelo sigue siendo "la media de las 4 mismas semanas corregida por calendario".** E11 cambia sobre todo con qué filas se aprende la corrección, no las variables.

## 3. ¿De dónde sale la mejora?

**Agosto de 2025 se lleva casi toda la mejora.**
- V0 subestima agosto un **10,1 %** (1.006.003 pasajeros previstos frente a 1.118.882 reales). V2 se queda igual de corto (−10,2 %), mientras que V3 queda en −2,8 % y V4 en −2,3 %.
- El WAPE de agosto baja de 17,2 % a 14,1 % (−3,1 puntos). En los demás meses la mejora es de 0,0 a 0,8 puntos, y en febrero y noviembre empeora 0,06 y 0,13 puntos.

**Explicación probable** (no se probó variable por variable):
- El pliegue de agosto entrena con julio de 2025. Julio tiene dos días con fallas de registro masivas (09-07 y 29-07, −33 % y −29 %), vacaciones escolares y universitarias, y está al final de la serie.
- Con `tendencia` y `dia_anio` como variables, los árboles colocan esas últimas filas, con pasajeros mucho menores que sus rezagos, en hojas que se aplican a todo el mes siguiente.
- Bajarles el peso elimina ese arrastre. Por eso funciona igual con las etiquetas de E10 que con la regla mecánica de fallas.

**El costo es un sesgo positivo.** V4 sobrestima el total un **+1,4 %** con h = 7 (V0: −0,3 %). Diciembre llega a +4,9 %, enero a +3,3 % y julio a +2,7 %. Para despachar, pasarse un poco es preferible a quedarse corto: E1 y D1 muestran que la sub-oferta es el error caro. Aun así, conviene vigilarlo.

## 4. Pipeline de producción (`modelo_final.py`)

```
# entrenar (o reutilizar) y pronosticar las 4 primeras semanas de 2026
PYTHONIOENCODING=utf-8 MPLBACKEND=Agg python experimentos/E11_modelo_mejorado/modelo_final.py
# cualquier otro rango futuro, con reentrenamiento y lluvia observada opcional
... modelo_final.py --desde 2026-02-09 --hasta 2026-02-15 --salida otra_semana.parquet [--reentrenar] [--clima lluvia.parquet]
```

**(a) Entrenamiento.**
- Lee `seleccion.json` (V4, parámetros C0) y entrena con todos los días observados: 2023-01-01 a 2025-12-31, sin los dos días R5, con los pesos de V4 y rezagos corregidos.
- Genera un modelo por horizonte en `modelos/modelo_V4_H{7,14,21,28}.txt`, con 55.538, 55.181, 54.824 y 54.467 filas. Tarda 27 s.
- `modelos/metadatos.json` guarda la variante, los parámetros, la importancia y el resumen del pronóstico.

**(b) Pronóstico.**
- Cada fecha d usa el modelo H = 7 × ⌈(d − 31-12-2025) / 7⌉. Del 1 al 7 de enero usa H = 7, del 8 al 14 H = 14, del 15 al 21 H = 21 y del 22 al 28 H = 28.
- Fuera de 28 días entrena H = 35, 42… a pedido. Se probó con la semana de Carnaval 2026, que el script calcula desde la Pascua (14 al 17 de febrero), pero **esos horizontes no se evaluaron**.
- Los festivos salen del paquete `holidays` (incluye Reyes, observado el 12-01-2026). Los calendarios escolar y universitario salen de los CSV de E10 y de `calendario_2026.csv`. Para años siguientes basta añadir filas.
- Si hay fechas sin calendario documentado, el script avisa.
- Con `--clima` usa el modelo nowcast N para las fechas con H = 7 y lluvia disponible. **No se recomienda:** en la evaluación empata con V3.

**Salida `pronostico_2026_enero.parquet`.** Tiene 1.428 filas = 3 rutas × 28 días × 17 horas, con las columnas `idruta, ruta, dia, hora, dia_semana, tipo_dia, festivo, vac_escolar, vac_univ, carnaval, semana_santa, horizonte_dias, modelo, pasajeros_pred`. `pronostico_2026_enero_semanal.csv` trae los totales por semana.

**Tabla 7. Pronóstico del 1 al 28 de enero de 2026 (salidas de 4 a 20 h)**

| Ruta | Semana 1 (1–7, H=7) | Semana 2 (8–14, H=14) | Semana 3 (15–21, H=21) | Semana 4 (22–28, H=28) | Total | 2025 alineado (−364 días) | Variación | E8 ensamble diario |
|---|---|---|---|---|---|---|---|---|
| SILENCIO | 44.554 | 52.317 | 57.185 | 61.614 | 215.670 | 240.116 | −10,2 % | 221.685 |
| CRA 54 | 87.435 | 103.423 | 117.322 | 127.993 | 436.172 | 499.505 | −12,7 % | 446.519 |
| CL 72 | 30.066 | 34.805 | 39.333 | 41.742 | 145.946 | 160.723 | −9,2 % | 146.652 |
| **Total** | 162.055 | 190.545 | 213.840 | 231.349 | **797.788** | 900.344 | **−11,4 %** | 814.856 |

- **Promedio por día laboral de enero.** SILENCIO 9.006, CRA 54 18.465, CL 72 6.089. Los sábados: 7.218, 14.580 y 4.936. Los domingos y festivos: 4.114, 7.581 y 2.766.
- **Forma.** La demanda sube semana a semana con el fin de las vacaciones: la semana 4 tiene un 43 % más de pasajeros que la 1. El 26-01, día en que vuelven a clases los colegios oficiales, sube un 12 % frente al lunes anterior (+9 % en CL 72, +13 % en las otras dos rutas). El 1 de enero cae al 16–22 % de un día laboral medio y el 12 de enero (Reyes, festivo) queda un 7–13 % por debajo del domingo anterior (`fig4_pronostico_2026_enero.png`).
- **Variación frente a 2025.** De la caída del 11,4 %, una parte es calendario: en 2026 el 1 y el 12 de enero son festivos, mientras que sus pares alineados de 2025 (2 y 13 de enero) fueron laborales. La otra parte es la tendencia de −8 % al año que el modelo arrastra en los rezagos.
- **Contraste con E8.** El total coincide con el ensamble diario de E8 a −2,1 %, con un método completamente distinto (SARIMAX, ETS y regresión).
- **No se puede evaluar hora a hora.** Lo único disponible de 2026 son los agregados de `timbradas_anio`, que analiza E8. **Según E8, de enero a agosto de 2026 hubo un +7,5 % de subidas frente a 2025, y todos los modelos quedaron 7–17 % cortos.** Si ese aumento es real, este pronóstico también queda corto en ese orden. Antes de usarlo para recortar salidas en 2026 hay que recalibrar el nivel con los primeros datos de 2026.

## 5. Limitaciones

1. **Selección optimista.** La variante se eligió sobre los mismos 12 pliegues que se reportan, como en E1, E6 y E9. Entre V3 y V4 la diferencia es ruido (0,006 puntos).
2. **Ganancia concentrada.** El 55 % de la mejora sale de agosto de 2025. Sin agosto quedan −0,21 puntos (h = 7) y −0,09 (h = 1), y la prueba t por pliegue no es significativa (p = 0,10). La dirección es consistente (10 de 12 meses mejor; Wilcoxon p = 0,003), pero el tamaño típico de la mejora es de unos 0,2 puntos.
3. **Etiquetas de E10 con información posterior.** Se construyeron mirando la prensa después de los hechos. En producción haría falta etiquetar los días atípicos cada semana. La regla mecánica de fallas (V3b, −0,32 puntos) no necesita etiquetas y es la parte desplegable sin trabajo manual.
4. **Sesgo positivo** de +1,4 % (hasta +4,9 % en diciembre) tras quitar peso a los días con caídas de datos.
5. **Calendarios.** Solo colegios oficiales de Barranquilla: no se incluyen Soledad (sin dato de 2024) ni colegios privados. El calendario universitario de 2026 es un supuesto y Uninorte es aproximado en todos los años (E10).
6. **Variables de 2026 que se ponen a 0.** Los eventos de `novedades_viales` (partidos, conciertos) solo llegan hasta el 06-06-2025; en 2026 valen 0. E1 mostró que no aportan.
7. **Demanda servida, no latente.** El modelo no recibe la oferta programada. Según E1, ese es el siguiente punto de mejora (1 a 1,5 puntos).
8. **Horizontes mayores de 28 días** sin validar.
9. **Clima.** Climatología y nowcast vienen de un solo punto de Open-Meteo, que suaviza los aguaceros (E9).

## 6. Próximos pasos

- **Detección automática de fallas de registro** en el flujo diario. Dos usos: pesar o excluir esas franjas al reentrenar, e imputar el objetivo histórico en lugar de solo bajarle el peso.
- **Recalibrar el nivel con 2026** apenas llegue `progvehiculos` de 2026. E8 sugiere un cambio de nivel que ningún modelo con rezagos de 2025 puede anticipar.
- **Añadir la oferta programada** (viajes programados × (1 − cancelación esperada)) como variable, como en la variante (b*) de E1.
- **Pasar los cuantiles de E3** a este modelo (pesos y H = 7 a 28) para dimensionar con p80.
- **Completar calendarios**: universidades 2026 y Soledad. Revisar si `tendencia` conviene reemplazarla por una variable de nivel reciente, para que no arrastre el final de la serie.

## 7. Archivos

| Archivo | Contenido |
|---|---|
| `run.py` | Evaluación completa: paneles, variantes, comparaciones, ajuste anidado, horizontes, descomposición, figuras 1, 2, 5 y 6; al final llama a `modelo_final.py` |
| `comun_e11.py` | Panel (réplica de E1 extensible al futuro), calendarios, clima, desplazamiento por horizonte, variantes, pesos y entrenamiento |
| `modelo_final.py` | Pipeline de producción (entrenar, guardar y pronosticar), figuras 3 y 4 |
| `calendario_2026.csv` | Recesos escolares 2026 de Barranquilla (Resolución 07248 de 2025) y supuesto universitario 2026 |
| `resultados.json` | Todas las métricas: global, por ruta, tipo de día, franja, mes y subconjunto; comparaciones pareadas y en cadena; ajuste anidado; horizontes; descomposición; sesgo mensual; selección |
| `tabla_variantes.csv`, `ajuste_anidado.csv` | Resumen por variante y horizonte; validación interna mes a mes |
| `seleccion.json` | Variante y parámetros que usa producción |
| `predicciones_2025.parquet` | V4 con h = 1 y h = 7 (real, predicción) más V0, B1 y nowcast por ruta × día × hora |
| `pronostico_2026_enero.parquet`, `pronostico_2026_enero_semanal.csv` | Pronóstico del 1 al 28 de enero de 2026 (el CSV semanal se regeneró en la verificación; ver sección 8) |
| `modelos/` | `modelo_V4_H7/14/21/28.txt` (LightGBM) y `metadatos.json` |
| `cache/` | Predicciones por variante para `E11_REUSAR=1` |
| `fig1_wape_variantes_ruta.png` | WAPE por variante (h = 1 y 7) y por ruta |
| `fig2_diferencia_pareada.png` | Diferencia con V0, IC 95 % y diferencias mensuales |
| `fig3_importancia_modelo_final.png` | Importancia del modelo final (H = 7) |
| `fig4_pronostico_2026_enero.png` | Pronóstico diario de enero de 2026 por ruta, frente a 2025 alineado y a E8 |
| `fig5_wape_horizonte.png` | WAPE según H |
| `fig6_wape_subconjuntos.png` | WAPE en vacaciones, transición, lluvia, días atípicos y días normales |
| `run.log`, `run_reuso.log` | Corrida completa (25,4 min) y corridas con caché (descomposición y figuras) |

## 8. Verificación (revisión adversarial, 05-10-2026)

**Veredicto: confiable con reservas.** No se encontró fuga de información. Los pesos y la corrección de rezagos solo tocan filas de entrenamiento anteriores al mes de prueba, y el objetivo evaluado no se corrige. Todas las variables de V1–V5 respetan h y H. El nowcast N está rotulado como cota. B1 es la misma regla que en E1 (diferencia 0 con sus predicciones guardadas).

**Cifras recalculadas de forma independiente.**
- **WAPE.** Con h = 7: V4 13,94 %, V0 14,40 %, B1 20,04 % y N 13,92 %. Con h = 1: V4 13,83 % y V0 14,10 %.
- **Objetivo real.** El de `predicciones_2025.parquet` coincide con el recalculado desde `progvehiculos` crudo (diferencia 0; 12.872.401 pasajeros en 2025).
- **Réplica de E1.** V0 coincide con la variante (a) de E1 (14,399 % y 14,098 %). El archivo `E1_lgbm_salida/predicciones_2025.parquet` guarda la variante (c), con WAPE 14,38 % y 14,08 %, y por eso difiere fila a fila.
- **Comparación pareada.** El bootstrap propio de días (otra semilla, 4.000 réplicas) da −0,46 [−0,60; −0,33]. Un bootstrap por semanas, más conservador ante la autocorrelación, da [−0,76; −0,22]: sigue siendo < 0. 10 de 12 meses mejoran (t p = 0,10; Wilcoxon p = 0,003). Sin agosto: −0,21 puntos.
- **Agosto.** Real 1.118.882 pasajeros, V0 1.006.003 (−10,1 %) y V4 1.093.251 (−2,3 %). Sesgo total: V4 +1,42 % y V0 −0,33 %.
- **Por ruta, tipo de día y franja (tabla 2).** Confirmados. Total diario por ruta: 5,55 % → 4,86 %.
- **Horizontes (H = 14, 21 y 28), descomposición V3a/b/c y ajuste anidado (14,01 %).** Confirmados desde `cache/`.
- **Importancia.** Las 10 variables nuevas suman el 0,68 % de la ganancia y la climatología el 0,11 %.
- **Pronóstico de enero de 2026.** 797.789 pasajeros: SILENCIO 215.670, CRA 54 436.172 y CL 72 145.946. Frente a 2025 alineado (900.344, recalculado desde el crudo) es −11,4 %, y frente a E8 (814.856) es −2,1 %. Semana 4 frente a semana 1: +42,8 %. El 26-01 frente al 19-01: +12,1 %.

**Correcciones.**
1. `pronostico_2026_enero_semanal.csv` tenía los totales de la prueba de Carnaval (9 al 17 de febrero), no los de enero, porque `modelo_final.py` escribía siempre el CSV semanal en esa ruta, fuera cual fuera `--salida`. Se regeneró desde `pronostico_2026_enero.parquet`, sin reentrenar, y coincide con `run.log`. Se corrigió el código: ahora el CSV semanal lleva el nombre del archivo de salida.
2. Tabla 3: el WAPE de V4 en vacaciones escolares es 15,8 % (15,846), no 15,9 %.
3. Sección 4: el 12 de enero queda un 7–13 % por debajo del domingo anterior (SILENCIO −12,5 %, CRA 54 −12,0 %, CL 72 −7,4 %), no un 7–12 %.
4. `resultados.json` → `tiempo_s` = 41 s corresponde a la corrida con caché. La corrida completa tardó 1.524 s (`run.log`).

**Reservas añadidas.**
- **La parte desplegable sin etiquetas es pequeña fuera de agosto.** Sin agosto, frente a V2: la regla mecánica (V3b) da −0,08 puntos, las etiquetas de E10 (V3a) −0,15 y ambas (V3) −0,13. El "84 % de la ganancia" de V3b es cierto en los 12 meses, pero fuera de agosto la ganancia típica es de 0,1 punto.
- **La evaluación de horizontes mezcla dos cosas.** Cada pliegue entrena con todo lo anterior al mes de prueba. Con H = 28, los primeros días del mes se pronostican con un modelo que ya vio hasta 27 días posteriores a la fecha en que se emitiría el pronóstico. En `modelo_final.py`, en cambio, el entrenamiento termina en la fecha de emisión. La cifra de H = 28 (14,4 %) puede ser algo optimista. Con H = 7 pasa lo contrario: el modelo de producción es más reciente que el de la evaluación.
- **Huecos del GPS.** Las tablas GPS no tienen el último día de cada mes, así que esos días todo viaje con 0 pasajeros cuenta como "sin registro". El 3,9 % de las franjas de esos días queda marcado como falla, frente al 2,5 % del resto: unas 25 franjas de más entre 1.412. El efecto es despreciable.
- **V4 necesita los eventos GPS del viaje** (`conteo_viajes.eventos`) para corregir rezagos. V3 rinde igual sin ellos y es más sencillo de desplegar.
- No se pudo verificar que la regla de selección y los pesos se fijaran antes de ver resultados. El código es coherente con lo que se declara.
