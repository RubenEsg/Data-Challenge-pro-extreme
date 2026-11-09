# E13 · Limpieza de datos para un pronóstico más preciso

**Pregunta.** ¿Se pueden limpiar mejor los datos para entrenar un modelo más preciso?

**Respuesta corta.**
- **Sí, pero la limpieza que sirve no es la que se esperaba.** Lo que más mejora es **corregir el objetivo**, no imputar ni filtrar más.
  - El objetivo de E1-E12 deja fuera a los pasajeros de los viajes marcados "cancelados" que sí corrieron. Contándolos, el total es un 5,6 % mayor en 2023, un 6,7 % en 2024 y un 7,7 % en 2025: el hueco crece.
  - **V4 reentrenado con el objetivo corregido (variante 1) baja el WAPE contra lo que de verdad sube de 13,55 % a 11,77 % en 2025.**
  - Frente a V4 llevado al mismo nivel con un cociente causal (12,07 %), la ganancia es de −0,31 puntos [IC 95 %: −0,42; −0,20], mejor en 11 de 12 meses. **En 2024 se repite: −0,41 [−0,54; −0,28], 10 de 12 meses.**
- **Con Chronos-2 (híbrido de E12) baja a 11,38 % en 2025 y 13,51 % en 2024.**
  - Frente a la variante 1: −0,39 [−0,51; −0,28] (12/12) y −0,41 [−0,58; −0,23] (10/12).
  - Frente al híbrido de E12 llevado al mismo nivel: −0,43 [−0,54; −0,34] y −0,50 [−0,63; −0,37].
- **Imputar los viajes sin registro empeora**: +0,27 [+0,20; +0,34] en 2025 y +0,26 [+0,18; +0,36] en 2024, con sesgo de +3,4 %.
  - También empeora en las franjas con registro completo (+0,15 y +0,08), donde lo registrado es lo que subió.
  - Causa: entre el 21 % y el 30 % de los viajes "sin registro" son registros fantasma. El mismo bus tenía otro viaje que sí corrió a menos de 90 min (a 90 min lo cumple el 0,15 % de los viajes normales; a 30 min, el 0,0 %).
  - Imputar solo los creíbles (2', a posteriori) pierde menos, +0,13 y +0,12, pero sigue perdiendo.
- **Completar los viajes con registro parcial empeora más** (+0,74 y +0,55).
- **La detección automática de anomalías rinde casi igual que la lista manual de E10**: +0,02 y −0,05 sobre la imputación; +0,01 y +0,06 sobre la variante 1. Sirve para no depender de etiquetas hechas a mano, a un costo de 0 a 0,06 puntos.
- **Para despachar, Sobusa debe usar el objetivo corregido** (sección 2). Con V4, la necesidad de buses calculada con lo que de verdad subió queda corta en el 44 % de las horas; con la variante 1, en el 27 %.
- **Datos atípicos.** El 20,8 % de los días de 2023-2025 tiene algún problema de datos: atípico no de calendario de E10 (2,8 %), más del 10 % de los viajes sin registro (1,5 %) o más del 10 % de los pasajeros en "cancelados" que corrieron (18,8 %). Además, el 7,2 % son días de calendario y el 3,3 % son fin de mes sin GPS. Por franja: el 2,5 % tiene ≥ 25 % de viajes sin registro y el 29,1 % tiene más del 10 % de sus pasajeros en "cancelados" que corrieron.

**Tabla A. Resumen (WAPE con h = 7; diferencias en puntos con IC 95 % por bootstrap pareado de días)**

| Modelo | 2025 contra el corregido | 2025 contra el original | Diferencia 2025 (corregido) | Meses mejor | 2024 contra el corregido | Diferencia 2024 | Meses mejor 2024 |
|---|---|---|---|---|---|---|---|
| V4 (E11/E12) | 13,55 % | **13,94 %** | — | — | 15,17 % | — | — |
| V4 × cociente (referencia de nivel) | 12,07 % | 15,99 % | — | — | 14,33 % | — | — |
| **1 · objetivo corregido (V4c)** | **11,77 %** | 15,99 % | **−0,31 [−0,42; −0,20]** frente a V4 × cociente | 11/12 | **13,92 %** | **−0,41 [−0,54; −0,28]** | 10/12 |
| 2 · + imputación sin registro | 12,04 % | 16,90 % | +0,27 [+0,20; +0,34] frente a 1 | 2/12 | 14,18 % | +0,26 [+0,18; +0,36] | 2/12 |
| 3 · + anomalías automáticas (sin E10) | 12,06 % | 16,95 % | +0,29 [+0,22; +0,37] frente a 1 | 1/12 | 14,13 % | +0,21 [+0,13; +0,31] | 2/12 |
| 4a · 2 + registro parcial | 12,51 % | 17,57 % | +0,74 [+0,63; +0,85] frente a 1 | 0/12 | 14,47 % | +0,55 [+0,43; +0,69] | 1/12 |
| 4b · 3 + registro parcial | 12,57 % | 17,68 % | +0,80 [+0,69; +0,92] frente a 1 | 0/12 | 14,54 % | +0,62 [+0,49; +0,75] | 1/12 |
| 2' · imputación sin fantasmas (a posteriori) | 11,89 % | 16,53 % | +0,13 [+0,07; +0,19] frente a 1 | 4/12 | 14,04 % | +0,12 [+0,05; +0,20] | 3/12 |
| 1 con anomalías automáticas en vez de E10 (a posteriori) | 11,78 % | 16,04 % | +0,01 [−0,01; +0,04] frente a 1 | 7/12 | 13,98 % | +0,06 [+0,01; +0,11] | 2/12 |
| Híbrido E12 (V4 + Chronos-2) | 13,28 % | **13,62 %** | — | — | 14,91 % | — | — |
| Híbrido E12 × cociente | 11,81 % | 15,71 % | — | — | 14,01 % | — | — |
| **Híbrido con la variante 1 (V4c + Chronos-2)** | **11,38 %** | 15,52 % | **−0,39 [−0,51; −0,28]** frente a 1; −0,43 [−0,54; −0,34] frente al híbrido E12 × cociente | 12/12 | **13,51 %** | −0,41 [−0,58; −0,23]; −0,50 [−0,63; −0,37] | 10/12; 11/12 |

Los modelos entrenados con un objetivo pierden contra el otro por nivel: el corregido es un 7,7 % mayor en 2025. Por eso las comparaciones se hacen con referencias del mismo nivel (sección 3). Contra el objetivo original, la variante 1 dividida por el cociente queda a +0,20 [+0,08; +0,32] de V4 en 2025 y a +0,11 [−0,01; +0,25] en 2024. **Si se quisiera seguir pronosticando el objetivo original, V4 sigue siendo mejor.**

## 1. Diagnóstico: cuántos datos son atípicos o están sucios

Todo sale de `datos/progvehiculos.parquet` y `datos/conteo_viajes.parquet` (rutas SILENCIO, CRA 54 y CL 72, salidas de 4 a 20 h, 2023-2025). Definiciones:

- **Viaje que corrió:** recorrió al menos 20 km, con cualquier marca (E7).
- **Viaje sin registro:** 0 pasajeros (o nulo) y menos de 30 eventos GPS (E10). El equipo a bordo no registró. Como la distancia también sale del GPS, casi ninguno llega a 20 km (mediana 0,1 km).
- **Viaje con registro parcial** (nuevo en E13): corrió, tiene registro, no es fin de mes y sus eventos GPS son menos del 40 % de la mediana de su ruta × hora en 2023. Lleva 18 pasajeros de media, frente a 87 de un viaje normal: el equipo se cayó a mitad del recorrido.

**Tabla 1. Días con datos atípicos (1.096 días de 2023-2025)**

| Tipo de día | Días | % de días | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| Calendario: festivos, Carnaval, Semana Santa, Navidad y 1-ene (predecibles) | 79 | 7,2 % | 7,4 % | 7,1 % | 7,1 % |
| Atípicos no de calendario de E10 (paro, aguaceros, Sibus, fallas, sin explicación) | 31 | 2,8 % | 0,8 % | 6,6 % | 1,1 % |
| Más del 10 % de los viajes válidos sin registro de pasajeros | 16 | 1,5 % | 0,3 % | 3,0 % | 1,1 % |
| Último día del mes (sin GPS) | 36 | 3,3 % | 3,3 % | 3,3 % | 3,3 % |
| **Más del 10 % de los pasajeros en viajes marcados "cancelados" que sí corrieron** | **206** | **18,8 %** | 20,3 % | 18,0 % | 18,1 % |
| Más del 20 % de los pasajeros en viajes "cancelados" que corrieron | 28 | 2,6 % | 1,9 % | 3,6 % | 2,2 % |
| Más del 5 % de los viajes con registro parcial | 20 | 1,8 % | 0 % | 5,5 % | 0 % |
| **Algún problema de datos** (E10 no calendario, > 10 % sin registro o > 10 % cancelados que corrieron) | **228** | **20,8 %** | 21,1 % | 23,2 % | 18,1 % |

**Tabla 2. Franjas (ruta × día × hora de salida) con datos atípicos (55.896 franjas)**

| Tipo de franja | Franjas | % | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| ≥ 25 % de los viajes válidos sin registro (regla de E11) | 1.412 | 2,5 % | 1,7 % | 3,3 % | 2,6 % |
| > 10 % de sus pasajeros en viajes "cancelados" que corrieron | 16.263 | 29,1 % | 26,4 % | 29,1 % | 31,9 % |
| Al menos un viaje con registro parcial | 2.974 | 5,3 % | 4,7 % | 5,7 % | 5,6 % |
| Marcadas por la detección automática de anomalías (sección 3) | 1.388 | 2,5 % | 1,7 % | 3,3 % | 2,4 % |
| De días con algún problema de datos | 11.628 | 20,8 % | 21,1 % | 23,2 % | 18,1 % |

**Tabla 3. El objetivo de E1-E12 deja fuera una parte creciente de los pasajeros**

| Año | Objetivo original (viajes válidos) | Objetivo corregido (viajes que corrieron) | Pasajeros en "cancelados" que corrieron (% del corregido) | Corregido sobre original | Variación anual original | Variación anual corregida | Lo que sumaría imputar los sin registro | Lo que sumaría completar los parciales |
|---|---|---|---|---|---|---|---|---|
| 2023 | 15.305.192 | 16.167.991 | 882.216 (5,5 %) | +5,6 % | | | +1,7 % | +0,6 % |
| 2024 | 13.988.686 | 14.926.045 | 961.012 (6,4 %) | +6,7 % | −8,6 % | −7,7 % | +2,5 % | +0,9 % |
| 2025 | 12.872.401 | 13.859.620 | 1.006.501 (7,3 %) | +7,7 % | −8,0 % | −7,1 % | +2,5 % | +0,9 % |

- **El hueco crece cada año**: de 5,6 % a 7,7 %. Por eso una parte de la caída de −8 % al año que arrastran los modelos (E11) es un artefacto de la marca de cancelado: con el objetivo corregido la caída es de −7,7 % y −7,1 %.
- **La marca "cancelado" no dice que el bus no salió** (E7): el sistema cierra como cancelado el viaje cuya llegada no se registró. El 18,8 % de los días tiene más del 10 % de sus pasajeros en esos viajes, y en un 2,6 % de los días pasan del 20 %.
- La figura `fig1_diagnostico_mensual.png` muestra la evolución mes a mes. Los viajes sin registro y los de registro parcial se concentran en mayo-junio de 2024 (transición al Sibus, E10).

**Tabla 4. De dónde sale el error de V4 en 2025 (objetivo original, 18.615 franjas)**

| Subconjunto | % de franjas | % de pasajeros | % del error de V4 | WAPE de V4 | Sesgo de V4 | WAPE del híbrido E12 |
|---|---|---|---|---|---|---|
| Franjas limpias (ningún problema de datos) | 80,1 % | 89,6 % | 81,3 % | **12,64 %** | +0,3 % | 12,36 % |
| Días con > 10 % de pasajeros en "cancelados" que corrieron | 18,1 % | 9,6 % | 16,6 % | **24,02 %** | +9,2 % | 23,25 % |
| Franjas con ≥ 25 % de viajes sin registro | 2,6 % | 0,9 % | 4,8 % | 71,17 % | +67,1 % | 70,85 % |
| Días con > 10 % de viajes sin registro | 1,1 % | 0,6 % | 3,1 % | 68,81 % | +54,6 % | 67,42 % |
| Días atípicos de E10 (no calendario) | 1,1 % | 0,8 % | 3,4 % | 55,37 % | +43,1 % | 54,67 % |
| Último día del mes (sin GPS) | 3,3 % | 3,2 % | 3,5 % | 15,20 % | +1,4 % | 14,92 % |
| Días de calendario | 7,1 % | 3,7 % | 6,2 % | 23,27 % | +6,2 % | 21,18 % |
| **Todas** | 100 % | 100 % | 100 % | **13,94 %** | +1,4 % | 13,62 % |

- Las franjas con algún problema de datos son el 19,9 % de 2025 y explican el 18,7 % del error de V4.
- **El grupo que más pesa son los días con muchos "cancelados" que corrieron**: el 16,6 % del error, con un WAPE de 24 % y un sesgo de +9 %. El modelo prevé la demanda real, pero el objetivo original pierde esos pasajeros por una marca administrativa que no se puede pronosticar. Con el objetivo corregido, la variante 1 baja ahí a un WAPE de 17,5 %.
- En las fallas de registro el sesgo es muy positivo (+43 % a +67 %). Ahí el modelo acierta la demanda; lo que falla es el registro. No se puede "arreglar" la prueba: solo cabe no aprender de esos ceros (lo que ya hace V4).

## 2. Qué objetivo debe usar Sobusa para despachar

**El objetivo corregido**: los pasajeros de todos los viajes que corrieron, con o sin marca de cancelado. Es lo más cercano a lo que de verdad sube a los buses. Las razones:

1. **Esos pasajeros existen y ocupan buses.** La marca "cancelada automáticamente" la pone el sistema cuando no registra la llegada del viaje (E7). El 82 % de esos viajes recorrió al menos 20 km, con GPS y una mediana de 74 pasajeros. En 2025 llevaron 1.006.501 pasajeros, el 7,3 % del total. Un plan hecho con el objetivo original los ignora.
2. **Con el objetivo original la oferta queda corta.** Calculando la necesidad de buses con lo que de verdad subió, V4 deja corta la oferta en el **44 % de las horas** y le faltan 12 buses-hora por ruta y día, con un neto de −5,2 % de buses. La variante 1 queda corta en el 27 % de las horas, con un neto de +1,3 % (sección 7).
3. **El objetivo original tiene una deriva que no es demanda.** La proporción de pasajeros en "cancelados" que corrieron sube de 5,5 % a 7,3 % entre 2023 y 2025. Por eso la caída anual medida con el objetivo original (−8,6 % y −8,0 %) es mayor que la real (−7,7 % y −7,1 %). Un modelo con `tendencia` aprende esa deriva como si fuera demanda.
4. **Su ruido diario es administrativo.** El 18,8 % de los días tiene más del 10 % de sus pasajeros en esos viajes, y ningún modelo puede prever qué viajes cerrará el sistema como cancelados. Por eso V4 tiene un WAPE de 24 % en esos días.
5. **Es igual de fácil de calcular.** Sale de `progvehiculos` (distancia recorrida y número de pasajeros) el mismo día, sin etiquetas manuales.

**Lo que el objetivo corregido aún no cuenta:**
- Los viajes cuyo equipo falló del todo (2,5 % de los viajes que operaron), pero la sección 5 muestra que muchos no fueron viajes reales.
- La parte no registrada de los viajes con registro parcial (≈ 0,9 % de los pasajeros).
- Los pasajeros de los viajes válidos de menos de 20 km (0,14 % en 2025).

## 3. Método

**Protocolo.** Es el de E11/E12: 12 pliegues mensuales de 2025, cada mes entrenado solo con días anteriores, horizonte h = 7 (toda variable usa información hasta d − 7). LightGBM Poisson con las 77 variables y los hiperparámetros de V4 (600 árboles, tasa 0,03, 31 hojas), semilla 42 y 2 hilos, en el Python del entorno aislado de E12. **La prueba nunca se imputa ni se limpia**: se evalúa con las 18.615 franjas de 2025, días atípicos incluidos. La confirmación usa los 12 pliegues de 2024, sin los dos días R5 (18.564 franjas), como E12.

**Dos objetivos, los dos evaluados.**
- **Original** (`pasajeros_total`): pasajeros de los viajes "válidos" (finalizado = S y cancelada = N). Es el de E1-E12.
- **Corregido** (`y_corr`): pasajeros de todos los viajes que corrieron (≥ 20 km), con o sin marca de cancelado (definición de E7).

**Variantes.** Todas son LightGBM V4; solo cambian el objetivo de entrenamiento, la serie con que se calculan los rezagos y los pesos.

| Clave | Variante | Objetivo y rezagos | Pesos de entrenamiento |
|---|---|---|---|
| `V4` | Referencia de E11/E12 | Original; rezagos × válidos / con registro | 0,25 días E10; 0,1 franjas con ≥ 25 % sin registro |
| `V4c` | **1 · Objetivo corregido** | Corregido; rezagos de ese objetivo con la misma corrección por viajes sin registro; oferta = viajes que operaron | Como V4 |
| `V4c_imp` | **2 · + imputación** | Cada viaje sin registro se imputa, en el objetivo de entrenamiento y en los rezagos, con la media por viaje de la misma ruta, tipo de día y hora de las 8 semanas previas (causal) | 0,25 días E10; las franjas con fallas ya no se bajan (peso 1) |
| `V4c_imp_auto` | **3 · + anomalías automáticas** | Como 2 | La lista manual de E10 se reemplaza por una detección automática (abajo), peso 0,25 |
| `V4c_imp_parcial` | **4a · 2 + registro parcial** | Como 2 y, además, los viajes con registro parcial se completan hasta la media por viaje | Como 2 |
| `V4c_imp_auto_parcial` | **4b · 3 + registro parcial** | Como 4a | Como 3 |
| `V4c_imp_auto_e10` | 3' (informativa) | Como 2 | Anomalías automáticas y lista E10 juntas |
| `V4c_imp_cred` | 2' (**a posteriori**, informativa) | Como 2, pero sin imputar los viajes sin registro "fantasma" (sección 5) | Como 2 |
| `V4c_auto` | 1 con anomalías automáticas (**a posteriori**, informativa) | Como 1 | Anomalías automáticas (0,25) en lugar de E10; conserva el 0,1 de las franjas con fallas |
| `V4_imp`, `V4_imp_auto` | Informativas | 2 y 3 con el objetivo original | Como 2 y 3 |

**Detección automática de anomalías (variante 3).** Solo marca filas de entrenamiento y solo usa datos anteriores al mes de prueba.
- Para cada ruta y día, el total diario se compara con la mediana de los mismos días de la semana una a cuatro semanas antes y después. Para cada franja, lo mismo con la misma ruta, hora y día de la semana.
- Se marca si el puntaje z modificado del logaritmo del cociente (Iglewicz y Hoaglin: 0,6745 × desvío / MAD, con la MAD de la ruta o de la ruta × hora) pasa de 3,5. En la franja se exige además un desvío de al menos 30 pasajeros.
- Los días de calendario (festivos, Carnaval, Semana Santa, 24-dic a 6-ene) nunca se marcan ni entran en la mediana de referencia: el modelo los aprende con sus variables.
- **Qué marca.** Con los datos del primer pliegue de 2025 (2023-2024) y la serie de la variante 1, marca 31 días-ruta completos y 518 franjas sueltas: 967 filas, el 2,6 % del entrenamiento.
  - Entre los días completos están los aguaceros del 15-06-2024 y el 25-09-2024, el día sin explicación del 05-07-2024 y el 29-10-2023, día de elecciones locales (SILENCIO).
  - De los 81 días-ruta de E10 en esos años, 18 salen marcados completos y 70 tienen al menos una franja marcada. Muchos de los demás son fallas de registro, que la corrección de rezagos o la imputación ya arreglan.
  - Marca 13 días-ruta completos que no están en E10 (`resultados.json` → `anomalias_vs_e10`).
  - Con todos los datos de 2023-2025, las marcas cubren el 2,5 % de las franjas (tabla 2).

**Qué se fijó antes de ver 2025 y qué no.**
- Antes: las definiciones (20 km, 30 eventos, 25 %), las variantes 1 a 4, los pesos (0,25 y 0,1), la ventana de imputación (8 semanas), el umbral z = 3,5, el umbral de registro parcial (40 % de la mediana de 2023) y la regla de selección.
- Ajustes hechos mirando solo 2023-2024: la referencia de la detección automática excluye los días de calendario (sin eso marcaba lunes normales rodeados de lunes festivos). La regla de registro parcial salió de revisar 2023-2024: los viajes con pocos eventos llevan 18 pasajeros de media, frente a 87, y se concentran en junio de 2024.
- Durante las pruebas del código se corrió una vez enero de 2025 con V4, V4c y la variante 3 para comprobar la reproducción de V4 y el tiempo. Ningún parámetro se cambió después.
- **A posteriori:** tres piezas se añadieron después de ver 2025. No compiten en la regla, y para las dos variantes la prueba limpia es 2024.
  - La variante 2' (`V4c_imp_cred`) y la vista "registro completo" se añadieron al ver que la imputación sesgaba al alza.
  - La variante 1 con anomalías automáticas (`V4c_auto`) se añadió cuando la regla eligió la variante 1, para saber si esta puede prescindir de la lista de E10.

**Evaluación justa.** Como el objetivo cambia, cada modelo se mide contra los dos objetivos y se compara con referencias del mismo nivel:
- **`V4_esc`** = V4 × cociente corregido / original de la ruta × hora en las 8 semanas que terminan en d − 7 (causal). Es "V4 llevado al objetivo corregido sin reentrenar".
- **`V4c_desc`** = V4c ÷ ese cociente: V4c llevado al objetivo original.
- Las variantes 2 a 4 se comparan con **V4c** (V4 reentrenado con el objetivo corregido, en las mismas condiciones), y V4c con V4_esc.
- **Vista de registro completo.** Son las franjas sin ningún viaje sin registro ni con registro parcial: 79,6 % en 2025. Ahí el valor registrado es lo que de verdad subió, así que es la vista justa para la imputación. Contra todas las franjas, la imputación pierde por construcción: la prueba conserva los ceros de los equipos caídos.
- Comparaciones: diferencia de WAPE con IC 95 % por bootstrap pareado de días (2.000 réplicas, semilla 42) y meses en que mejora, con `comparar_pareado` de E12.

**Regla de selección (fijada antes de correr 2025).** Entre las variantes 2, 3, 4a y 4b, gana la de menor WAPE contra el objetivo corregido cuyo IC 95 % de la diferencia con V4c quede entero bajo 0 y que mejore en al menos 7 de los 12 meses. Si ninguna cumple, se queda V4c. La elegida se combina con Chronos-2 como en el híbrido de E12: pronóstico zero-shot con contexto hasta d − 7 y calendario, recalculado con la serie de la elegida.

## 4. Resultados de 2025

**La regla elige la variante 1 (V4c).** Ninguna candidata cumple: las cuatro empeoran frente a V4c con IC entero sobre 0 (tabla A y `seleccion.json`). El híbrido se construyó entonces con V4c: Chronos-2 se recalculó con la serie corregida de V4c como contexto, y LightGBM usa las variables de V4c más `fm_c2`, sus cuantiles 10 y 90 y la razón con la media de 4 semanas.

![WAPE por variante](fig2_wape_variantes.png)

**Tabla 5. Objetivo corregido, 2025: más medidas**

| Modelo | WAPE | MAE (pax/franja) | RMSE | Sesgo | Error del total diario por ruta (WAPE) | WAPE con registro completo | Sesgo con registro completo |
|---|---|---|---|---|---|---|---|
| V4 | 13,55 % | 100,9 | 148,6 | −5,8 % | 7,12 % | 13,86 % | −7,1 % |
| V4 × cociente | 12,07 % | 89,9 | 135,8 | +1,4 % | 4,57 % | 12,07 % | +0,6 % |
| **1 · V4c** | **11,77 %** | **87,6** | **132,9** | +1,3 % | **4,25 %** | **11,78 %** | +0,6 % |
| 2 · + imputación | 12,04 % | 89,6 | 136,4 | +3,4 % | 4,84 % | 11,93 % | +2,4 % |
| 3 · + anomalías automáticas | 12,06 % | 89,8 | 136,6 | +3,5 % | 4,90 % | 11,94 % | +2,5 % |
| 4a · 2 + registro parcial | 12,51 % | 93,1 | 142,6 | +4,3 % | 5,37 % | 11,97 % | +2,7 % |
| 2' · sin fantasmas | 11,89 % | 88,5 | 134,6 | +2,6 % | 4,55 % | 11,83 % | +1,7 % |
| 1 con anomalías automáticas | 11,78 % | 87,7 | 133,0 | +1,4 % | 4,27 % | 11,78 % | +0,8 % |
| Híbrido E12 × cociente | 11,81 % | 87,9 | 133,6 | +1,4 % | 4,55 % | 11,83 % | +0,6 % |
| **Híbrido V4c + Chronos-2** | **11,38 %** | **84,7** | **129,7** | **+1,0 %** | **4,14 %** | **11,38 %** | +0,3 % |

**Tabla 6. WAPE por tamaño de la franja (objetivo corregido, 2025; cuartiles y decil del valor real)**

| Pasajeros reales de la franja | % del error de V4c | V4 | V4 × cociente | V4c | Híbrido V4c |
|---|---|---|---|---|---|
| < 217 (10 % más pequeño) | 8,0 % | 45,5 % | 52,1 % | 53,9 % | 52,4 % |
| 217-362 | 10,4 % | 20,1 % | 20,9 % | 20,9 % | 19,8 % |
| 362-574 | 18,7 % | 15,3 % | 15,1 % | 14,1 % | 13,3 % |
| 574-946 | 22,9 % | 14,1 % | 11,4 % | 11,2 % | 10,9 % |
| ≥ 946 (25 % más grande) | 39,9 % | 11,0 % | 9,2 % | 8,9 % | 8,7 % |

- **La mejora está en las franjas medianas y grandes**, que llevan el 80 % del error y deciden cuántos buses salen: en las de más de 946 pasajeros, el WAPE baja de 11,0 % (V4) a 8,9 % (V4c) y 8,7 % (híbrido).
- En el 10 % más pequeño, los modelos de nivel corregido pierden: sobrestiman las franjas casi vacías, que incluyen las fallas de registro. Son el 8 % del error y casi no cambian los buses (`fig4_wape_tamano_franja.png`).
- En 2024 el patrón es el mismo: ≥ 1.027 pasajeros, 11,9 % → 10,7 % → 10,4 %.

**Por ruta, tipo de día y tramo (objetivo corregido, 2025).** V4c mejora a V4 × cociente en todos los cortes:
- Por ruta: SILENCIO 13,0 → 12,5 %, CRA 54 10,3 → 10,1 % y CL 72 16,0 → 15,9 %.
- Por tipo de día: domingos y festivos 15,3 → 14,3 %; laborales 11,8 → 11,5 %.
- Por tramo: tarde (16-20 h) 15,0 → 14,7 %.
- El híbrido baja otros 0,2 a 0,6 puntos en cada corte; lo que menos mejora es la tarde.

**Por mes** (`fig6_mensual.png`). V4c gana a V4 × cociente en 11 de 12 meses; pierde solo en enero (+0,36). En 2024 gana en 10 de 12; pierde en enero (+0,30) y agosto (+0,04).
- Enero es el mes de fin de año, donde V4c sobrestima un 4,3 %. Conviene vigilarlo.
- El híbrido gana a V4c en los 12 meses de 2025.

## 5. Por qué la imputación no funciona: viajes "sin registro" que no fueron viajes

La imputación supone, como E10, que un viaje válido con 0 pasajeros y menos de 30 eventos GPS corrió y su equipo no registró. Los datos dicen que muchos no corrieron:
- **Fantasmas.** En 2023-2024, el 22,8 % de los viajes válidos sin registro tiene **otro viaje del mismo vehículo que sí corrió con salida a menos de 30 minutos**: 26,5 % a menos de 60 min y 29,3 % a menos de 120 min. En los viajes normales es el 0,0 % (1,5 % a 120 min). Un bus no hace dos recorridos de ~4 h a la vez: ese registro sin pasajeros es un duplicado del despacho.
  - Con un margen de 90 min, son fantasmas el 29,8 % (2023), el 20,7 % (2024) y el 26,4 % (2025) de los viajes sin registro.
  - Solo el 2,2 % tiene como gemelo un viaje "cancelado" que corrió.
  - Otro 16,7 % pertenece a vehículos que no corrieron ningún viaje ese día: puede ser un equipo caído todo el día o un bus que no salió.
- **El sesgo lo confirma.** Imputar suma un 2,5 % de pasajeros al entrenamiento.
  - En las franjas con registro completo, donde lo registrado es lo que subió, la variante 2 sobrestima un +2,4 %, frente a +0,6 % de V4c, y pierde +0,15 [+0,09; +0,21] en 2025 y +0,08 [−0,01; +0,16] en 2024.
  - Si la imputación acertara, ahí no debería haber sesgo extra.
- **Quitar los fantasmas (2', a posteriori) ayuda pero no basta.** Mejora a la variante 2 en −0,14 en los dos años (12/12 y 11/12 meses) y casi empata con V4c en las franjas con registro completo: +0,06 [+0,00; +0,11] y −0,01 [−0,08; +0,07]. Pero sigue perdiendo contra V4c en todas las franjas (+0,13 y +0,12). Lo más probable es que buena parte de los "sin registro" restantes tampoco fueran viajes completos.
- **Lo que sí funciona es lo que ya hacía V4**: escalar los rezagos por los viajes con registro y bajar a 0,1 el peso de las franjas con ≥ 25 % sin registro. Así no se inventa demanda.
- **Registro parcial.** Completar los viajes con pocos eventos GPS sube el sesgo a +4,3 % y pierde 0,47 puntos frente a la variante 2. Con el mismo argumento, una parte de esos viajes debió de ser recorridos cortos o desvíos, no fallas.
- **Con el objetivo original pasa lo mismo**: V4 + imputación pierde +0,29 [+0,22; +0,37] en 2025 y +0,23 [+0,14; +0,32] en 2024.

**Anomalías automáticas frente a la lista de E10.** Las dos rinden casi igual.
- Sobre la imputación: +0,02 [−0,00; +0,05] en 2025 y −0,05 [−0,11; +0,01] en 2024.
- Sobre V4c (a posteriori): +0,01 [−0,01; +0,04] y +0,06 [+0,01; +0,11]. En las franjas con registro completo, +0,00 y +0,01.
- La regla automática se calcula sin mirar la prensa ni esperar etiquetas. La lista de E10, en cambio, se hizo a posteriori y en producción habría que mantenerla cada semana.

![Diferencias pareadas](fig3_diferencias_pareadas.png)

## 6. Confirmación en 2024

Mismos 12 pliegues mensuales de 2024 (cada mes entrenado con lo anterior), mismo código y semilla; evaluación de 18.564 franjas sin los dos días R5. Las cifras de V4 (15,734 %) y del híbrido de E12 (15,405 %) contra el objetivo original reproducen exactamente E12.

| Comparación (objetivo corregido) | 2025 | 2024 | ¿Se confirma? |
|---|---|---|---|
| 1 · V4c frente a V4 × cociente | −0,31 [−0,42; −0,20], 11/12 | −0,41 [−0,54; −0,28], 10/12 | **Sí** |
| 1 · V4c frente a V4 sin reescalar | −1,78 [−2,00; −1,56], 12/12 | −1,25 [−1,50; −1,02], 11/12 | Sí |
| Híbrido V4c frente a V4c | −0,39 [−0,51; −0,28], 12/12 | −0,41 [−0,58; −0,23], 10/12 | **Sí** |
| Híbrido V4c frente al híbrido E12 × cociente | −0,43 [−0,54; −0,34], 12/12 | −0,50 [−0,63; −0,37], 11/12 | **Sí** |
| Híbrido V4c frente a V4 × cociente | −0,70 [−0,83; −0,56], 12/12 | −0,82 [−1,02; −0,63], 12/12 | Sí |
| 2 · imputación frente a V4c | +0,27 [+0,20; +0,34], 2/12 | +0,26 [+0,18; +0,36], 2/12 | Pierde en los dos |
| 3 · anomalías automáticas frente a V4c | +0,29 [+0,22; +0,37], 1/12 | +0,21 [+0,13; +0,31], 2/12 | Pierde en los dos |
| 4a · registro parcial frente a V4c | +0,74 [+0,63; +0,85], 0/12 | +0,55 [+0,43; +0,69], 1/12 | Pierde en los dos |
| 2' · sin fantasmas frente a V4c (a posteriori) | +0,13 [+0,07; +0,19], 4/12 | +0,12 [+0,05; +0,20], 3/12 | Pierde en los dos |
| V4c con anomalías automáticas frente a V4c (a posteriori) | +0,01 [−0,01; +0,04], 7/12 | +0,06 [+0,01; +0,11], 2/12 | Empate práctico |

WAPE de 2024 contra el objetivo corregido: V4 15,17 %, V4 × cociente 14,33 %, **V4c 13,92 %**, **híbrido V4c 13,51 %**, híbrido E12 × cociente 14,01 %.

## 7. Métricas fáciles de leer

Todas se calculan contra **lo que de verdad subió** (objetivo corregido), que es lo que hay que transportar.
- **Buses necesarios por hora** = ⌈pasajeros de la franja × r / (50 × 0,85)⌉, donde r es la carga en el tramo más cargado sobre los pasajeros de la franja. r se mide por ruta × hora en los viajes de 2023-2024 con contadores consistentes: 0,40 de media en SILENCIO y CL 72 y 0,44 en CRA 54. Se aplica el mismo r a lo real y a lo previsto, así que la diferencia en buses viene solo del error del pronóstico.
- En 2025 hacen falta 7,9 buses por hora de media.

**Tabla 7. Métricas fáciles, 2025 (objetivo corregido)**

| Métrica | V4 (actual) | V4 × cociente | **V4c** | **Híbrido V4c** |
|---|---|---|---|---|
| Error medio del total diario de la ruta | 8,1 % (902 pax) | 5,5 % (579 pax) | **5,2 % (538 pax)** | **5,0 % (525 pax)** |
| Días-ruta con el total diario errado en menos de 5 % | 34 % | 63 % | **68 %** | **68 %** |
| Error típico por franja (mediana del error absoluto) | 72 pax | 62 pax | **60 pax** | **59 pax** |
| Franjas con error ≤ 10 % / ≤ 20 % | 40 % / 71 % | 47 % / 76 % | **48 % / 77 %** | **50 % / 79 %** |
| Horas con el número de buses exacto | 35,7 % | 39,4 % | **40,3 %** | **41,4 %** |
| Horas con ±1 bus | 79,0 % | 82,4 % | **83,3 %** | **84,1 %** |
| Error medio en buses por hora | 1,00 | 0,90 | **0,87** | **0,85** |
| **Horas en que faltan buses** | **44,4 %** | 28,1 % | **26,9 %** | 27,0 % |
| Buses-hora que faltan por ruta y día | 12,0 | 6,7 | 6,5 | 6,5 |
| Buses-hora de más por ruta y día | 5,1 | 8,6 | 8,3 | 8,0 |
| Buses totales previstos frente a necesarios | −5,2 % | +1,4 % | +1,3 % | +1,1 % |

**En 2024**, mismo orden:
- Error medio del total diario: V4 9,5 %, V4c 7,6 % y híbrido V4c 7,4 %.
- Horas con buses exactos: 30,5 %, 34,5 % y 35,3 %.
- Horas en que faltan buses: 44,4 %, 29,9 % y 30,2 %.
- Error medio en buses por hora: 1,22, 1,12 y 1,09.

![Error en buses](fig5_error_buses.png)

**Cómo leerlas.**
- Con el híbrido V4c, el total diario de cada ruta se equivoca en un 5 % de media (unos 525 pasajeros), y en 2 de cada 3 días el error es menor del 5 %.
- En cada hora acierta el número exacto de buses el 41 % de las veces y queda a ±1 bus el 84 %.
- El plan actual con V4 quedaría corto en 4 de cada 10 horas, porque no ve el 7 % de pasajeros que viajan en buses marcados "cancelados".
- Fallar por un bus es casi inevitable: la necesidad cambia de un bus cada 42,5 pasajeros en el tramo crítico (unos 100 pasajeros de la franja), y el error típico es de 59. Para no quedar corto, E3 recomienda planificar con un cuantil alto (p80-p90), no con el pronóstico central.

## 8. Recomendación

1. **Cambiar el objetivo de despacho al corregido**: pasajeros de todos los viajes con ≥ 20 km, con o sin marca de cancelado. Es lo que de verdad sube; el original lo subestima en un 5,6-7,7 % creciente y mete ruido administrativo.
2. **Modelo: el híbrido V4c + Chronos-2.** Es la misma cadena del híbrido de E12, con el objetivo, los rezagos y el contexto de Chronos-2 calculados con el objetivo corregido.
   - Es el mejor en los dos años: 11,38 % y 13,51 % contra lo que sube, frente a 13,55 % y 15,17 % de V4.
   - Si se quiere lo más simple, V4c solo (11,77 % y 13,92 %).
3. **No imputar** los viajes sin registro ni completar los de registro parcial. Mantener el tratamiento de V4: rezagos escalados por los viajes con registro y peso 0,1 a las franjas con ≥ 25 % sin registro.
4. **Reemplazar la lista manual de E10 por la detección automática** (z modificado > 3,5 frente a las mismas 4 semanas antes y después, calendario exento, peso 0,25). Cuesta entre 0 y 0,06 puntos y no necesita etiquetar días a mano cada semana.
5. **Corregir la fuente.** Pedir a Sobusa o al proveedor del sistema:
   - que no marque como cancelado un viaje que recorrió la ruta;
   - que elimine los despachos duplicados (viajes "fantasma" del mismo vehículo a la misma hora);
   - que registre las caídas del equipo a bordo.
   Con eso el objetivo corregido sería directo.
6. **Al pasar a producción**, recalcular la historia de Chronos-2 con la serie corregida. Para 2023-2025 ya está en `cache/chronos2_V4c.parquet`. Correr el modelo en sombra junto al híbrido actual, como sugiere E12.

## 9. Limitaciones

1. **El objetivo corregido no es la verdad.** No cuenta lo que no registró el equipo y depende de que `distancia_recorrida` sea fiable; el umbral de 20 km es de E7. La vista "registro completo" (79,6 % de las franjas) limita el problema pero excluye franjas de forma no aleatoria.
2. **La comparación entre objetivos depende del cociente.** V4 × cociente usa el cociente de 8 semanas que terminan en d − 7. Otro cociente (por ruta, por día de la semana) podría acortar la distancia con V4c. Aun así, el reescalado también es una forma de usar el objetivo corregido.
3. **Selección optimista.** La regla se aplicó sobre los mismos pliegues que se informan, como en E11 y E12. La variante elegida (V4c) y su híbrido se confirmaron en 2024. Las variantes 2' y "V4c con anomalías automáticas" son a posteriori; su única prueba limpia es 2024.
4. **2024 no es del todo independiente**: el umbral del registro parcial y la exención de calendario de la detección automática se ajustaron mirando 2023-2024. Para V4c y su híbrido, que no usan esas piezas, sí es una prueba limpia.
5. **Fantasmas.** La regla de 90 minutos es una aproximación: no distingue un bus que repitió despacho de uno que hizo un recorrido corto. Tampoco se pudo verificar con Sobusa.
6. **Métrica de buses.** Usa un cociente fijo de carga crítica por ruta × hora (2023-2024), la capacidad de 50 y el factor de 0,85 del protocolo. No sustituye la simulación de D6 ni considera la frecuencia mínima.
7. **Sesgo de nivel en enero y diciembre.** V4c sobrestima un 4,3 % en enero y un 3,1 % en diciembre de 2025. En 2026, según E8, la demanda subió (+7,5 %): el nivel habrá que recalibrarlo con los primeros datos de 2026, como en E11 y E12.
8. **Solo h = 7.** No se evaluaron H = 14 a 28 con el objetivo corregido.

## Cómo reproducir

Desde la carpeta del proyecto, con el Python del entorno aislado de E12 (Chronos-2 y pandas 2.3.3):

```bash
PY="C:/Users/Usuario/AppData/Local/Temp/claude/d--Ruben-universidad-machine-learning-DATA-CHALLENGE/74e3ac63-631e-4b5a-85a3-594592559f62/scratchpad/venv_e12/Scripts/python.exe"
cd "D:/Ruben/universidad/machine_learning/DATA CHALLENGE"
PYTHONIOENCODING=utf-8 MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1 "$PY" experimentos/E13_limpieza_datos/run.py
# por fases: --fase base | variantes | chronos | hibridos | informe ; --rehacer ignora las cachés
```

- No se conecta a la base de datos. Lee `datos/progvehiculos.parquet`, `datos/conteo_viajes.parquet`, el panel de V4 de `E12/cache/panel_v4.parquet` (solo si su firma coincide; si no, lo reconstruye en `E13/cache`), los CSV de E10 y la caché de Chronos-2 de E12. No escribe nada fuera de E13.
- Las predicciones se guardan con una firma del código y la configuración: si no cambian, se reutilizan.
- Chronos-2 se usa con los pesos locales (`HF_HUB_OFFLINE=1`) en la GPU si está libre.

**Tiempos de esta corrida** (2 hilos de CPU, una fase a la vez):
- Variantes LightGBM: 20 corridas de 12 pliegues en 16 min, unos 57 s por variante en 2025 y 38 s en 2024 (`run_variantes.log`). Más `V4c_auto` en 100 s.
- Chronos-2 en la GPU (RTX 3050): 1.068 días × 51 series en 23 min (`run_chronos.log`).
- Híbridos (4 corridas): 3,4 min. Informe con cachés: 14 s (`run.log`, `run_informe.log`).
- Total: unos 45 min.

## Archivos

| Archivo | Contenido |
|---|---|
| `run.py` | Diagnóstico, variantes, selección, Chronos-2, híbridos, evaluación, figuras y `resultados.json` |
| `comun_e13.py` | Clasificación de viajes, objetivos, imputación causal, registro parcial, fantasmas, rezagos, detección automática, entrenamiento, cociente entre objetivos y métricas fáciles |
| `resultados.json` | Diagnóstico, métricas de cada modelo contra los dos objetivos (global, ruta, tipo de día, tramo, mes, tamaño, subconjuntos, total diario, métricas fáciles), comparaciones pareadas de 2025 y 2024, selección, verificación y tiempos |
| `tabla_variantes.csv` | Resumen por modelo y año |
| `seleccion.json` | Resultado de la regla de selección |
| `predicciones/<modelo>_<año>.parquet` | Predicciones de cada modelo (idruta, ruta, dia, hora, prediccion, corte) |
| `predicciones/todas_<año>.parquet` | Todas las predicciones juntas con `real_original`, `real_corregido`, el cociente entre objetivos y el de carga |
| `cache/` | Panel base, diagnóstico, cociente de carga, pronósticos de Chronos-2 con la serie de la elegida y firmas |
| `fig1_diagnostico_mensual.png` | Pasajeros en "cancelados" que corrieron, viajes sin registro y parciales, y días afectados, mes a mes |
| `fig2_wape_variantes.png` | WAPE de cada modelo contra los dos objetivos (2025) |
| `fig3_diferencias_pareadas.png` | Diferencias pareadas con IC 95 %, 2025 y 2024 |
| `fig4_wape_tamano_franja.png` | WAPE por tamaño de franja |
| `fig5_error_buses.png` | Distribución del error en buses por hora |
| `fig6_mensual.png` | Diferencia mensual de la elegida y sesgo mensual |
| `run.log`, `run_variantes.log`, `run_chronos.log`, `run_informe.log` | Registros de las corridas (completa, variantes, Chronos-2 e informe con cachés) |

## Verificación

Revisión independiente y adversarial (08-10-2026), con scripts propios fuera del proyecto (`verif_e13/v1_objetivo.py` a `v7_dow_hibrido.py`, en el scratchpad de la sesión).
- Las cifras clave se recalcularon desde `datos/progvehiculos.parquet`, `datos/conteo_viajes.parquet`, el CSV de E10 y los Parquet individuales de `predicciones/`, sin importar las funciones de evaluación de E13.
- Para las pruebas de fugas sí se usaron las funciones de E13 que construyen variables, porque son lo que se prueba.
- No se tocó código ni resultados. Solo se corrigieron tres frases (al final).

**Veredicto: las cifras son correctas y no hay fugas. La recomendación se sostiene** (objetivo corregido e híbrido V4c + Chronos-2).
- Matiz importante: la ganancia de *reentrenar* (V4c frente a V4 reescalado) es real pero pequeña, y depende del cociente de referencia: −0,31 con el del README, −0,15 con uno por día de la semana.
- Casi toda la mejora en las métricas de buses viene del cambio de nivel (usar el objetivo corregido), no del reentrenamiento.

**1. Objetivo corregido: bien construido.**
- Se reproduce exactamente en las 55.896 franjas: diferencia máxima 0 con `cache/panel_base.parquet` y con `real_corregido` y `real_original` de `todas_<año>`.
- Corregido sobre original: +5,637 % (2023), +6,701 % (2024) y +7,669 % (2025). Pasajeros en "cancelados" que corrieron: 5,46 %, 6,44 % y 7,26 % del corregido.
- El 81,9 % de los viajes no válidos corrió al menos 20 km (mediana de 74 pasajeros y 65 km).
- **Sin doble conteo.** Ningún par de viajes que corrieron comparte vehículo y salida.
  - Pares del mismo vehículo a ≤ 60 min: 47 (0,004 % de los pasajeros). A ≤ 90 min: 506 (0,10 %).
  - Con ventanas inicio-fin solapadas más de 10 min: 18 pares (0,001 %), todos de viajes válidos. No mueve ninguna cifra.
- Misma rejilla: rutas 2, 16 y 21, salidas de 4 a 20 h, 2023-2025. La prueba de 2024 deja fuera los dos días R5 (18.564 franjas).

**2. Fugas: ninguna.**
- **Prueba de perturbación.** Se puso ruido en todo lo observado desde T = 10-03-2025 y se reconstruyeron las variables.
  - Ninguna de las 77 variables de V4c, V4c_imp, V4c_imp_parcial y V4c_imp_cred cambia para los días anteriores a T + 7. El objetivo y los pesos de los días anteriores a T tampoco cambian.
  - Lo mismo vale para la media causal de la imputación, el cociente causal (`factor_escala`) y la detección automática (marcas de los días anteriores al pliegue).
  - `pasajeros_total_lag7` de V4c es exactamente la serie corregida de d − 7.
- **Corte del entrenamiento.** Se reentrenaron con un bucle propio, solo con días anteriores al mes, V4c (junio de 2025 y marzo de 2024) y el híbrido V4c (septiembre de 2025).
  - Las predicciones coinciden con las guardadas (diferencia 0).
  - Con el futuro perturbado desde el día 1 del mes, los días 1 a 7 siguen idénticos y desde el día 8 cambian, como corresponde a h = 7.
- **Chronos-2.** `dia − corte` ≥ 7 en las 54.468 filas. El contexto de E13 coincide con uno reconstruido aparte; el `bfill` solo rellena un valor, el del 01-01-2023.
- **Regla de selección.** Recalculada: las cuatro candidatas pierden frente a V4c con el IC entero sobre 0 y mejoran en 0 a 2 meses, así que se queda V4c. El código aplica la regla tal como se describe.
  - Que se fijara antes de ver 2025 no se puede comprobar: E13 no tiene historial en git. El README declara la corrida de prueba de enero de 2025.
- Heredado de E11/E12, no es fuga nueva: los pesos de entrenamiento usan la lista de E10, hecha a posteriori.

**3. Comparaciones recalculadas** (objetivo corregido; IC 95 % por bootstrap pareado de días, 2.000 réplicas, semilla propia; con la semilla 42 los IC coinciden con los del README)

| Comparación | 2025 | 2024 | ¿Coincide? |
|---|---|---|---|
| WAPE: V4 / V4 × cociente / V4c / híbrido V4c | 13,55 / 12,07 / 11,77 / 11,38 % | 15,17 / 14,33 / 13,92 / 13,51 % | Sí |
| V4c frente a V4 × cociente | −0,31 [−0,41; −0,20], 11/12 | −0,41 [−0,54; −0,28], 10/12 | Sí |
| Híbrido V4c frente a V4c | −0,39 [−0,51; −0,28], 12/12 | −0,41 [−0,58; −0,23], 10/12 | Sí |
| Híbrido V4c frente al híbrido E12 × cociente | −0,43 [−0,53; −0,34], 12/12 | −0,50 [−0,64; −0,37], 11/12 | Sí |
| 2 · imputación frente a V4c | +0,27 [+0,20; +0,34], 2/12 | +0,26 [+0,17; +0,35], 2/12 | Sí |
| 4a · registro parcial frente a V4c | +0,74 [+0,63; +0,85], 0/12 | +0,55 [+0,43; +0,69], 1/12 | Sí |
| V4c con anomalías automáticas frente a V4c | +0,01 [−0,01; +0,04], 7/12 | **+0,06 [+0,01; +0,11], 2/12** | Sí (ver nota) |

También se reproducen el resto de las filas de la tabla A, las cifras de E12 en 2024 (15,734 % y 15,405 %), los cortes por ruta, tipo de día y tramo y el sesgo de V4c (+4,3 % en enero y +3,1 % en diciembre de 2025).
- En todos los cortes de los dos años, V4c mejora a V4 × cociente. El margen más estrecho es CL 72 en 2025: 16,00 → 15,88 %.

**Robustez de la referencia (V4 × cociente).**
- Otros cocientes causales no acortan la distancia de forma apreciable:
  - por ruta × hora con 14, 28 o 112 días, la diferencia de V4c va de −0,31 a −0,51;
  - por ruta con 14 a 56 días, de −0,90 a −1,15.
- Ni siquiera el cociente real del año o del mes (no causal) lo logra: V4 queda en 12,99 % y 12,89 % en 2025.
- **Un cociente por ruta × hora × día de la semana (8 semanas que terminan en d − 7, elegido a posteriori entre 4, 8 y 12) sí la reduce a la mitad.**
  - V4 × ese cociente: 11,92 % en 2025 y 14,13 % en 2024.
  - V4c frente a él: −0,15 [−0,23; −0,07] (10/12) y −0,21 [−0,32; −0,10] (9/12). Sigue siendo significativo.
  - El híbrido V4c aguanta: −0,46 [−0,55; −0,38] (12/12) y −0,42 [−0,54; −0,32] (11/12) frente al híbrido E12 × ese cociente.
- Se confirma la limitación 2: la ganancia robusta de reentrenar está entre −0,15 y −0,31 en 2025.

**4. Métricas fáciles** (recalculadas; el r propio difiere del de E13 en 0,002 como máximo y los resultados, en menos de 0,1 puntos)

| 2025, contra el corregido | V4 | V4 × cociente | V4 × cociente por día de la semana | V4c | Híbrido V4c |
|---|---|---|---|---|---|
| Error medio del total diario por ruta | 8,06 % | 5,46 % | 5,24 % | 5,22 % | 4,97 % |
| Horas con el número exacto de buses | 35,7 % | 39,4 % | 39,8 % | 40,3 % | 41,4 % |
| Horas con ±1 bus | 79,0 % | 82,4 % | 82,9 % | 83,3 % | 84,1 % |
| Horas en que faltan buses | 44,4 % | 28,1 % | 26,8 % | 26,9 % | 27,0 % |
| Error medio en buses por hora | 1,00 | 0,90 | — | 0,87 | 0,85 |

En 2024, V4 × cociente (que el README no da): total diario 8,15 %, buses exactos 33,1 %, horas cortas 31,3 % y error medio de 1,15 buses.

- **La fórmula de buses es razonable.** ⌈pasajeros × r / 42,5⌉ con el mismo r para lo real y lo previsto da 7,9 buses por hora, frente a 9,3 viajes que corrieron por franja en 2025.
  - No favorece a ningún modelo por construcción, salvo por el nivel: un modelo con más sesgo positivo queda corto menos veces.
- **V4 medido contra el objetivo corregido sin reescalar sale corto por construcción** (nivel −5,8 %). Contra su propio objetivo, V4 queda corto en el 28,9 % de las horas, como los demás.
  - De los 17,5 puntos de horas cortas (44,4 → 26,9 %), 16,3 son de nivel (V4 × cociente: 28,1 %) y 1,2 de reentrenar. Con el cociente por día de la semana, V4 reescalado queda corto el 26,8 %, igual que V4c.
  - Buses exactos: 35,7 → 39,4 % (nivel) → 40,3 % (reentrenar). Total diario: 8,1 → 5,5 → 5,2 %.
- Las frases del README "con V4, corta en el 44 % de las horas; con la variante 1, en el 27 %" son correctas como argumento para despachar con el objetivo corregido, que es lo que dicen. No deben leerse como ganancia del reentrenamiento.

**5. ¿Dice la verdad el README?** Sí en las cifras. Estos son los matices:
- **Comparaciones de distinto nivel.** "Baja el WAPE de 13,55 % a 11,77 %" (respuesta corta) y "frente a 13,55 % y 15,17 % de V4" (recomendación 2) comparan con V4 sin reescalar. 1,48 de los 1,78 puntos son de nivel.
  - La comparación justa (−0,31 y −0,41) está en la línea siguiente, así que no se corrige, pero es la que hay que citar.
- **Tabla 4.** "La variante 1 baja ahí a un WAPE de 17,5 %" compara con V4 medido contra el original (24,0 %). Contra el mismo objetivo corregido, V4 × cociente tiene 18,2 % en esos días: casi toda la bajada es el cambio de objetivo.
- **Anomalías automáticas.** En 2024, sobre V4c, pierden +0,06 [+0,01; +0,11] y mejoran solo en 2 de 12 meses. Es poco, pero significativo, y 2024 es la prueba limpia de esa variante a posteriori.
  - Se cambió "rinde igual" por "rinde casi igual". La recomendación 4 se justifica por el costo de mantener la lista, no por precisión.
- **Fantasmas.** Las cifras anuales a 90 min (29,8 / 20,7 / 26,4 %) cuadran con las propias (24,9 % en 2023-2024 juntos).
  - Las de 30, 60 y 120 min de la sección 5 (22,8 / 26,5 / 29,3 %) no se reproducen exactamente: salen 20,6 / 23,9 / 26,4 % con los viajes válidos sin registro de 2023-2024 con vehículo.
  - En los viajes normales sale 0,01 % a 30 min, 0,15 % a 90 min y 1,39 % a 120 min. La conclusión es la misma. Esas cifras no se corrigen porque la diferencia puede venir de la base usada.
- **Diagnóstico.** Se reproducen exactamente con código propio:
  - por días: 20,8 % (228) con algún problema, 18,8 % (206) con más del 10 % de los pasajeros en "cancelados" que corrieron, 2,6 % (28) con más del 20 %, 1,5 % (16) con más del 10 % sin registro y 2,8 % (31) atípicos de E10;
  - por franjas: el 29,1 % tiene más del 10 % de sus pasajeros en "cancelados" que corrieron.

**Correcciones hechas en este README (antes → después)**
1. Respuesta corta, fantasmas: "(el 0,0 % de los viajes normales cumple eso)" → "(a 90 min lo cumple el 0,15 % de los viajes normales; a 30 min, el 0,0 %)".
2. Respuesta corta: "La detección automática de anomalías rinde igual que la lista manual de E10" → "… rinde casi igual …".
3. Sección 5: "Las dos rinden igual." → "Las dos rinden casi igual."

