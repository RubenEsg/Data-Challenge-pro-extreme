# Definición de pasajeros en el modo integrado

**Pregunta.** La lectura integrada del ciclo (`FUENTE=postgres`, `FUENTE_TABLA=demanda_segmentos`) sumaba las subidas de
`timbradas_segmentos` (lo que escribe el trigger `tg_timbrada_segmento`). El objetivo del modelo y el histórico
empaquetado (`datos/demanda_horaria.parquet`) son otra medida: la suma de `progvehiculos.numeropasajeros` de los viajes
válidos que salen en esa hora. Si las dos medidas difieren, `politica.serie_validada` pondría una encima de la otra en la
misma columna y el reentrenamiento mezclaría dos definiciones.

**Medición.** `python -m scripts.reconstruir_desde_replica --definicion-pasajeros`, en solo lectura (lector_ia) sobre la
réplica local, en todo el solape de `timbradas_segmentos` (2023-01-01 a 2023-02-27), horas de salida de 4 a 20 h. Las
cifras completas por ruta, por hora y por ruta y hora están en `definicion_pasajeros.json`.

| Ruta | Σ subidas (segmentos) | Σ numeropasajeros (viajes válidos) | Diferencia | Misma diferencia, solo viajes con timbradas | Viajes válidos sin timbradas | Franjas sin timbradas |
|---|---:|---:|---:|---:|---:|---:|
| SILENCIO | 590.542 | 632.928 | −6,70 % | +0,17 % | 511 de 7.880 | 52 |
| CRA 54 | 1.277.494 | 1.332.082 | −4,10 % | +0,20 % | 696 de 15.553 | 34 |
| CL 72 | 370.707 | 396.675 | −6,55 % | +0,41 % | 322 de 4.876 | 52 |
| **Total** | **2.238.743** | **2.361.685** | **−5,21 %** | **+0,22 %** | **1.529 de 28.309** | **138** |

- La diferencia es **material** (más de 5 % en total, en SILENCIO y en CL 72, y en 34 de las 51 celdas ruta × hora).
- Toda la diferencia viene de **cobertura**, no de la forma de contar: en los mismos viajes, Σ subidas y Σ
  numeropasajeros difieren 0,22 %. Los 127.960 pasajeros que faltan son de 1.529 viajes válidos que no tienen
  timbradas en `timbradas_segmentos`, y todos caen en 138 franjas (ruta, fecha, hora) donde ningún viaje tiene
  timbradas.
- Por hora la diferencia va de −4,28 % (19 h) a −6,33 % (4 h); por ruta y hora, `definicion_pasajeros.json`.

**Decisión (aplicada).** La lectura integrada usa la definición del modelo. En `app/servicios/fuentes.py`
(`DEFINICION_PASAJEROS = "numeropasajeros_viajes_validos_v2"`; la versión de la huella incremental pasa a 2):

- `pasajeros` = Σ `numeropasajeros` de los viajes válidos de la franja (`finalizado = 'S'`, `cancelada = 'N'`, dato
  ≤ 300, ceros incluidos), igual que el objetivo del modelo;
- `salidas` = número de viajes válidos de la franja;
- `subidas` y `bajadas` = Σ de los segmentos de esos viajes (informativas, para la capa de segmentos), y
  `viajes_con_timbradas` = cuántos viajes de la franja tienen timbradas;
- cada franja tocada por una timbrada nueva se vuelve a agregar completa, como antes.

**Comprobación.** `tests/replica/test_integrado.py::test_demanda_segmentos_usa_la_definicion_del_modelo_con_proceso_y_estacionalidad`
lee con la API las 2.757 franjas de la réplica y comprueba que `pasajeros` y `salidas` son iguales, franja por franja,
a los del histórico empaquetado (2.757 de 2.757). La reconstrucción completa del histórico desde la réplica
(`linaje.md`) también es idéntica.

**Límite que queda.** El lector incremental se dispara con las marcas de `timbradas_segmentos`: una franja en la que
ningún viaje tiene timbradas no se lee (138 de 2.895 franjas con viajes válidos en el solape, 4,8 %). Esas horas no
entran a `demanda_observada` y aparecen como horas de servicio sin registro en la regla de datos faltantes de las
alertas (ALT-009). Cerrar esa brecha requiere que Extreme confirme por qué esos viajes no tienen timbradas.
