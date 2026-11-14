# Índices candidatos medidos en la réplica, dentro de transacciones que se revierten

Generado 2026-11-13T19:37:11-05:00 con `python -m scripts.replica_indices_candidatos` como extreme_dba (el dueño de las tablas). Método: cada escenario en una transacción que se revierte: consultas sin el índice, CREATE INDEX, las mismas consultas, ROLLBACK; sin ANALYZE; lock_timeout 2s; la más rápida de 2 corridas por lado. La propuesta entera, en otra transacción que se revierte, con todas las consultas y ANALYZE en los dos lados. Volumen: 2,769,692 filas de timbradas_segmentos (539.6 MB) y 564,837 viajes de progvehiculos; marca de un día 2026-08-13T20:39:15.446600-05:00, última fecha 2023-02-27.

Índices `ix_ia_*` en la réplica antes de medir: ninguno; al terminar: ninguno (la réplica sigue fiel a Extreme).

Criterio: el índice se usa y baja al menos 30 % y 10 ms alguna de las consultas que lo justificarían, y ninguna empeora más de 15 % (una diferencia menor de 1 ms no cuenta). Ese «ningún empeoramiento» se evalúa además con la propuesta entera, más abajo.

| Escenario | Consulta | ms sin | ms con | Mejora | Usa el índice | Escaneos con el índice |
|---|---|---|---|---|---|---|
| ix_ia_timbradas_segmentos_ultimaactualizacion | demanda_segmentos_sin_novedades | 166,1 | 46,7 | 72 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion, Index Scan progvehiculos progvehiculos_pkey, Index Scan rutas rutas_pkey, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_ultimaactualizacion | demanda_segmentos_una_ruta_sin_novedades | 162,6 | 47,9 | 71 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion, Index Scan progvehiculos progvehiculos_pkey, Index Scan rutas rutas_pkey, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_ultimaactualizacion | demanda_segmentos_bloque | 3.537,2 | 3.411,6 | 4 % | sí | Seq Scan progvehiculos, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_ultimaactualizacion, Seq Scan Procesos, Seq Scan rutas, CTE Scan, Seq Scan progvehiculos, CTE Scan, Seq Scan estacionalidades_anio, CTE Scan, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_ultimaactualizacion | demanda_segmentos_una_ruta_bloque | 3.274,9 | 3.271,1 | 0 % | sí | Seq Scan progvehiculos, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_ultimaactualizacion, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_ultimaactualizacion | segmentos_ventana_sin_novedades | 116,0 | 0,0 | 100 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion |
| ix_ia_timbradas_segmentos_ultimaactualizacion | segmentos_ventana_bloque | 667,5 | 668,7 | −0 % | no | Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_ultimaactualizacion | segmentos_rango | 174,5 | 174,8 | −0 % | no | Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_id_viaje | demanda_segmentos_sin_novedades | 165,1 | 178,3 | −8 % | sí | Seq Scan timbradas_segmentos, Index Scan progvehiculos progvehiculos_pkey, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| ix_ia_timbradas_segmentos_id_viaje | demanda_segmentos_una_ruta_sin_novedades | 170,5 | 170,8 | −0 % | sí | Seq Scan timbradas_segmentos, Index Scan progvehiculos progvehiculos_pkey, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| ix_ia_timbradas_segmentos_id_viaje | demanda_segmentos_bloque | 3.592,0 | 3.517,5 | 2 % | sí | Seq Scan progvehiculos, Seq Scan timbradas_segmentos, Seq Scan Procesos, Seq Scan rutas, CTE Scan, Seq Scan progvehiculos, CTE Scan, Seq Scan estacionalidades_anio, CTE Scan, Subquery Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje, CTE Scan |
| ix_ia_timbradas_segmentos_id_viaje | demanda_segmentos_una_ruta_bloque | 3.353,9 | 3.288,8 | 2 % | no | Seq Scan progvehiculos, Seq Scan timbradas_segmentos, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_id_viaje | ocupacion_actual | 703,0 | 703,8 | −0 % | no | Seq Scan timbradas_segmentos, Seq Scan progvehiculos, Function Scan, Seq Scan rutas, Seq Scan rutas_segmentos |
| ix_ia_timbradas_segmentos_id_viaje | viajes_de_una_ruta | 803,2 | 89,5 | 89 % | sí | Seq Scan progvehiculos, Seq Scan rutas, CTE Scan, Subquery Scan, CTE Scan, Index Only Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| ix_ia_progvehiculos_ruta_hora_salida | demanda_segmentos_sin_novedades | 168,1 | 164,3 | 2 % | sí | Seq Scan timbradas_segmentos, Index Scan progvehiculos progvehiculos_pkey, Seq Scan rutas, Seq Scan Procesos, CTE Scan, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_hora_salida, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_progvehiculos_ruta_hora_salida | demanda_segmentos_una_ruta_sin_novedades | 166,6 | 166,6 | −0 % | sí | Seq Scan timbradas_segmentos, Index Scan progvehiculos progvehiculos_pkey, Seq Scan rutas, Seq Scan Procesos, CTE Scan, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_hora_salida, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_progvehiculos_ruta_hora_salida | demanda_segmentos_bloque | 3.560,5 | 3.590,4 | −1 % | no | Seq Scan progvehiculos, Seq Scan timbradas_segmentos, Seq Scan Procesos, Seq Scan rutas, CTE Scan, Seq Scan progvehiculos, CTE Scan, Seq Scan estacionalidades_anio, CTE Scan, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_progvehiculos_ruta_hora_salida | demanda_segmentos_una_ruta_bloque | 3.284,8 | 3.287,9 | −0 % | no | Seq Scan progvehiculos, Seq Scan timbradas_segmentos, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_progvehiculos_ruta_hora_salida | viajes_de_una_ruta | 807,6 | 728,8 | 10 % | sí | Seq Scan rutas, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_hora_salida, CTE Scan, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ix_ia_timbradas_segmentos_fecha | segmentos_grano_diario_1_fecha | 259,3 | 217,9 | 16 % | sí | Subquery Scan, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_fecha, Seq Scan rutas_segmentos, CTE Scan, Seq Scan rutas, Seq Scan estacionalidades_anio, CTE Scan |
| ix_ia_timbradas_segmentos_fecha | segmentos_grano_diario_7_fechas | 1.407,0 | 1.621,0 | −15 % | sí | Subquery Scan, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_fecha, Seq Scan rutas_segmentos, CTE Scan, Seq Scan rutas, Seq Scan estacionalidades_anio, CTE Scan |
| ix_ia_timbradas_segmentos_fecha | segmentos_rango | 177,6 | 176,7 | 0 % | no | Seq Scan timbradas_segmentos |
| ix_ia_progvehiculos_ruta_fechasalida | ocupacion_actual | 712,9 | 866,5 | −22 % | sí | Seq Scan timbradas_segmentos, Function Scan, Seq Scan rutas, Index Scan progvehiculos ix_ia_progvehiculos_ruta_fechasalida, Seq Scan rutas_segmentos |
| ix_ia_timbradas_consolidado_ultima_actualizacion | consolidado_sin_novedades | 1,3 | 0,0 | 99 % | sí | Index Scan timbradas_consolidado ix_ia_timbradas_consolidado_ultima_actualizacion |
| ix_ia_timbradas_consolidado_ultima_actualizacion | consolidado_resellado | 4,5 | 2,7 | 40 % | sí | Index Scan timbradas_consolidado ix_ia_timbradas_consolidado_ultima_actualizacion |
| ix_ia_timbradas_consolidado_ultima_actualizacion | consolidado_todos_los_procesos | 4,2 | 2,1 | 49 % | sí | Index Scan timbradas_consolidado ix_ia_timbradas_consolidado_ultima_actualizacion |
| ix_ia_timbradas_consolidado_proceso_ultima_actualizacion | consolidado_sin_novedades | 1,3 | 0,0 | 99 % | sí | Index Scan timbradas_consolidado ix_ia_timbradas_consolidado_proceso_ultima_actualizacion |
| ix_ia_timbradas_consolidado_proceso_ultima_actualizacion | consolidado_resellado | 4,4 | 2,1 | 51 % | sí | Index Scan timbradas_consolidado ix_ia_timbradas_consolidado_proceso_ultima_actualizacion |
| ix_ia_timbradas_consolidado_proceso_ultima_actualizacion | consolidado_conteo_del_proceso | 1,5 | 1,2 | 20 % | sí | Index Only Scan timbradas_consolidado ix_ia_timbradas_consolidado_proceso_ultima_actualizacion |
| ix_ia_timbradas_consolidado_proceso_ultima_actualizacion | consolidado_existe_el_proceso | 0,0 | 0,0 | 0 % | no | Seq Scan timbradas_consolidado |
| lectura_incremental_1_2_3 | demanda_segmentos_sin_novedades | 169,3 | 49,0 | 71 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion, Index Scan progvehiculos progvehiculos_pkey, Index Scan rutas rutas_pkey, Seq Scan Procesos, CTE Scan, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_hora_salida, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| lectura_incremental_1_2_3 | demanda_segmentos_una_ruta_sin_novedades | 181,9 | 46,9 | 74 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion, Index Scan progvehiculos progvehiculos_pkey, Index Scan rutas rutas_pkey, Seq Scan Procesos, CTE Scan, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_hora_salida, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| lectura_incremental_1_2_3 | demanda_segmentos_bloque | 3.734,9 | 3.453,8 | 8 % | sí | Seq Scan progvehiculos, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_ultimaactualizacion, Seq Scan Procesos, Seq Scan rutas, CTE Scan, Seq Scan progvehiculos, CTE Scan, Seq Scan estacionalidades_anio, CTE Scan, Subquery Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje, CTE Scan |
| lectura_incremental_1_2_3 | demanda_segmentos_una_ruta_bloque | 3.307,2 | 3.253,9 | 2 % | sí | Seq Scan progvehiculos, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_ultimaactualizacion, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| lectura_incremental_1_2_3 | segmentos_ventana_sin_novedades | 118,1 | 0,0 | 100 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion |
| lectura_incremental_1_2_3 | segmentos_ventana_bloque | 669,3 | 684,0 | −2 % | no | Seq Scan timbradas_segmentos |
| lectura_incremental_1_2_3 | segmentos_rango | 178,1 | 179,1 | −0 % | no | Seq Scan timbradas_segmentos |
| lectura_incremental_1_2_3 | ocupacion_actual | 744,3 | 716,5 | 4 % | no | Seq Scan timbradas_segmentos, Seq Scan progvehiculos, Function Scan, Seq Scan rutas, Seq Scan rutas_segmentos |
| lectura_incremental_1_2_3 | viajes_de_una_ruta | 824,3 | 8,9 | 99 % | sí | Seq Scan rutas, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_hora_salida, CTE Scan, Subquery Scan, CTE Scan, Index Only Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| refresco_segmentos_1_4 | demanda_segmentos_sin_novedades | 169,0 | 48,0 | 72 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion, Index Scan progvehiculos progvehiculos_pkey, Index Scan rutas rutas_pkey, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| refresco_segmentos_1_4 | demanda_segmentos_una_ruta_sin_novedades | 170,6 | 46,6 | 73 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion, Index Scan progvehiculos progvehiculos_pkey, Index Scan rutas rutas_pkey, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| refresco_segmentos_1_4 | demanda_segmentos_bloque | 3.539,2 | 3.455,6 | 2 % | sí | Seq Scan progvehiculos, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_ultimaactualizacion, Seq Scan Procesos, Seq Scan rutas, CTE Scan, Seq Scan progvehiculos, CTE Scan, Seq Scan estacionalidades_anio, CTE Scan, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| refresco_segmentos_1_4 | demanda_segmentos_una_ruta_bloque | 3.316,3 | 3.310,0 | 0 % | sí | Seq Scan progvehiculos, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_ultimaactualizacion, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| refresco_segmentos_1_4 | segmentos_ventana_sin_novedades | 118,6 | 0,0 | 100 % | sí | Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion |
| refresco_segmentos_1_4 | segmentos_ventana_bloque | 667,6 | 664,6 | 0 % | no | Seq Scan timbradas_segmentos |
| refresco_segmentos_1_4 | segmentos_grano_diario_1_fecha | 266,0 | 220,8 | 17 % | sí | Subquery Scan, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_fecha, Seq Scan rutas_segmentos, CTE Scan, Seq Scan rutas, Seq Scan estacionalidades_anio, CTE Scan |
| refresco_segmentos_1_4 | segmentos_grano_diario_7_fechas | 1.395,7 | 1.655,3 | −19 % | sí | Subquery Scan, Bitmap Heap Scan timbradas_segmentos, Bitmap Index Scan  ix_ia_timbradas_segmentos_fecha, Seq Scan rutas_segmentos, CTE Scan, Seq Scan rutas, Seq Scan estacionalidades_anio, CTE Scan |
| refresco_segmentos_1_4 | segmentos_rango | 177,6 | 0,0 | 100 % | sí | Index Only Scan timbradas_segmentos ix_ia_timbradas_segmentos_fecha, Index Only Scan timbradas_segmentos ix_ia_timbradas_segmentos_fecha, Index Only Scan timbradas_segmentos ix_ia_timbradas_segmentos_ultimaactualizacion |
| ocupacion_actual_2_5 | demanda_segmentos_sin_novedades | 164,8 | 165,6 | −0 % | sí | Seq Scan timbradas_segmentos, Index Scan progvehiculos progvehiculos_pkey, Seq Scan rutas, Seq Scan Procesos, CTE Scan, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_fechasalida, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| ocupacion_actual_2_5 | demanda_segmentos_una_ruta_sin_novedades | 200,8 | 161,1 | 20 % | sí | Seq Scan timbradas_segmentos, Index Scan progvehiculos progvehiculos_pkey, Seq Scan rutas, Seq Scan Procesos, CTE Scan, Bitmap Heap Scan progvehiculos, Bitmap Index Scan  ix_ia_progvehiculos_ruta_fechasalida, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |
| ocupacion_actual_2_5 | demanda_segmentos_bloque | 3.516,6 | 3.464,1 | 2 % | sí | Seq Scan progvehiculos, Seq Scan timbradas_segmentos, Seq Scan Procesos, Seq Scan rutas, CTE Scan, Seq Scan progvehiculos, CTE Scan, Seq Scan estacionalidades_anio, CTE Scan, Subquery Scan, Index Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje, CTE Scan |
| ocupacion_actual_2_5 | demanda_segmentos_una_ruta_bloque | 3.239,4 | 3.286,8 | −2 % | no | Seq Scan progvehiculos, Seq Scan timbradas_segmentos, Seq Scan rutas, Seq Scan Procesos, Seq Scan progvehiculos, CTE Scan, CTE Scan, CTE Scan, Seq Scan estacionalidades_anio, Subquery Scan, CTE Scan, Seq Scan timbradas_segmentos |
| ocupacion_actual_2_5 | ocupacion_actual | 711,2 | 880,3 | −24 % | sí | Seq Scan timbradas_segmentos, Function Scan, Seq Scan rutas, Index Scan progvehiculos ix_ia_progvehiculos_ruta_fechasalida, Seq Scan rutas_segmentos |
| ocupacion_actual_2_5 | viajes_de_una_ruta | 832,4 | 89,9 | 89 % | sí | Seq Scan progvehiculos, Seq Scan rutas, CTE Scan, Subquery Scan, CTE Scan, Index Only Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje |

## La propuesta entera, con las estadísticas al día (ANALYZE)

Una transacción que se revierte: ANALYZE de timbradas_segmentos, progvehiculos, timbradas_consolidado, timbradas_anio, timbradas_segmentos_anio, timbradas_segmentos_consolidado; todas las consultas; CREATE INDEX de los 7 índices de la propuesta; ANALYZE otra vez; las mismas consultas; ROLLBACK. Las estadísticas están al día en los dos lados, también las de la expresión del índice sobre `date_trunc('hour', fechasalida)`, que es lo que tendrá la base después de que el DBA cree los índices.

| Consulta | ms sin índices | ms con la propuesta | Mejora | Filas descartadas en uniones, sin → con | Empeora |
|---|---|---|---|---|---|
| demanda_segmentos_sin_novedades | 168,6 | 0,1 | 100 % | 0 → 0 | no |
| demanda_segmentos_una_ruta_sin_novedades | 168,4 | 0,1 | 100 % | 0 → 0 | no |
| demanda_segmentos_bloque | 3.613,2 | 1.537,7 | 57 % | 0 → 0 | no |
| demanda_segmentos_una_ruta_bloque | 3.347,2 | 1.168,5 | 65 % | 0 → 0 | no |
| demanda_segmentos_bloque_con_union_final_de_rutas (referencia) | 3.453,8 | 9.173,0 | −166 % | 0 → 87.967.780 | sí |
| segmentos_ventana_sin_novedades | 118,9 | 0,0 | 100 % | 0 → 0 | no |
| segmentos_ventana_bloque | 675,8 | 667,8 | 1 % | 0 → 0 | no |
| segmentos_grano_diario_1_fecha | 259,5 | 258,3 | 0 % | 0 → 0 | no |
| segmentos_grano_diario_7_fechas | 1.427,6 | 1.402,0 | 2 % | 0 → 0 | no |
| segmentos_rango | 177,7 | 175,6 | 1 % | 0 → 0 | no |
| ocupacion_actual | 707,0 | 697,5 | 1 % | 2.950.340 → 2.950.340 | no |
| viajes_de_una_ruta | 810,6 | 8,9 | 99 % | 0 → 0 | no |
| consolidado_sin_novedades | 1,3 | 0,0 | 99 % | 0 → 0 | no |
| consolidado_resellado | 4,4 | 2,8 | 37 % | 0 → 0 | no |
| consolidado_todos_los_procesos | 4,2 | 2,1 | 50 % | 0 → 0 | no |
| consolidado_carga_inicial | 4,4 | 2,6 | 40 % | 0 → 0 | no |
| consolidado_agregado_rutas | 3,9 | 4,0 | −3 % | 0 → 0 | no |
| consolidado_conteo_del_proceso | 1,5 | 1,5 | 3 % | 0 → 0 | no |
| consolidado_existe_el_proceso | 0,0 | 0,0 | 0 % | 0 → 0 | no |

**Ninguna lectura de la API empeora** más de 15 % con la propuesta entera: el criterio se cumple también así. Mejoran al menos 30 % y 10 ms: `demanda_segmentos_sin_novedades`, `demanda_segmentos_una_ruta_sin_novedades`, `demanda_segmentos_bloque`, `demanda_segmentos_una_ruta_bloque`, `segmentos_ventana_sin_novedades`, `viajes_de_una_ruta`.

`demanda_segmentos_bloque_con_union_final_de_rutas` no es una lectura de la API: es la del bloque de llegada con la unión final de `rutas` que `fuentes._SQL_DEMANDA_SEGMENTOS` tenía hasta el 13-11-2026. Con la propuesta entera pasa de 3.453,8 a 9.173,0 ms y descarta 87.967.780 filas en el filtro de una unión: PostgreSQL estima `viajes ⋈ rutas` con el ndistinct por omisión de un CTE y, con las estadísticas de la expresión del índice 3, elige un ciclo anidado con Materialize. Por eso la lectura ya no vuelve a unir `rutas` (el nombre y la empresa viajan desde el CTE `franjas`): entrega las mismas filas en el mismo orden.

### La misma medición sin el índice 3 (cuál cambia el plan y qué se perdería sin él)

Otra transacción que se revierte, con ANALYZE en los dos lados y los 6 índices de la propuesta menos `ix_ia_progvehiculos_ruta_hora_salida`:

| Consulta | ms sin índices | ms sin el índice 3 | Mejora | Filas descartadas en uniones, sin → con | Empeora |
|---|---|---|---|---|---|
| demanda_segmentos_bloque | 3.628,9 | 3.396,1 | 6 % | 0 → 0 | no |
| demanda_segmentos_bloque_con_union_final_de_rutas (referencia) | 3.480,0 | 3.291,9 | 5 % | 0 → 0 | no |
| demanda_segmentos_sin_novedades | 172,1 | 49,6 | 71 % | 0 → 0 | no |
| viajes_de_una_ruta | 817,0 | 89,7 | 89 % | 0 → 0 | no |

Con las estadísticas al día: la formulación anterior del bloque, 3.291,9 ms sin el índice 3 frente a 9.173,0 ms con la propuesta entera; los viajes de una ruta y un día (§5.3), 89,7 ms sin el índice 3 frente a 8,9 ms con la propuesta entera; la lectura sin novedades de cada ciclo, 49,6 ms sin el índice 3 frente a 0,1 ms con la propuesta entera. El cambio de plan de la formulación anterior viene de las estadísticas de la expresión de ese índice; quitarlo lo evitaría, pero se perdería lo que aporta a los viajes de una ruta y al régimen sin novedades. Por eso el índice sigue en la propuesta y lo que se corrigió fue la lectura.

## Decisión (`docs/evidencias/replica/propuesta_indices.sql`)

| Índice | Tabla (columnas) | Respaldado por la medición | En la propuesta | Por qué |
|---|---|---|---|---|
| `ix_ia_timbradas_segmentos_ultimaactualizacion` | timbradas_segmentos (ultimaactualizacion) | sí | sí (desde la ola A) | Se propone: sin novedades, la lectura incremental baja de unos 170 a 50 ms y la ventana de solape del refresco, de unos 120 a 0,02 ms (el costo fijo de cada ciclo y de cada refresco, que sin el índice recorre toda la tabla y crece con el histórico). |
| `ix_ia_timbradas_segmentos_id_viaje` | timbradas_segmentos (id_viaje) | sí | sí (desde la ola A) | Se propone: los viajes de una ruta y un día con su conteo de segmentos (§5.3) bajan de unos 800 a 90 ms y, con el índice 3, a 9 ms. |
| `ix_ia_progvehiculos_ruta_hora_salida` | progvehiculos (idruta, (date_trunc('hour', fechasalida))) | sí | sí (desde la ola A) | Se propone junto con el índice 2: los viajes de una ruta y un día bajan de unos 820 a 9 ms (solo, a unos 730 ms). Con las estadísticas al día, las de su expresión hacen que la lectura compuesta sin novedades baje a 0,1 ms y que la del bloque grande use los índices 1 y 2 (ver «La propuesta entera»). |
| `ix_ia_timbradas_segmentos_fecha` | timbradas_segmentos (fecha) | no | no | No se propone con esta medición: el grano diario de una fecha baja solo de unos 260 a 220 ms y el de 7 fechas (12,5 % de la réplica) empeora de unos 1.400 a 1.620 ms; con el de la marca, el rango de la fuente baja de unos 175 a 0,03 ms. Con el histórico completo (unos 58 millones de filas proyectadas, 7 fechas serían el 0,6 % de la tabla) conviene volver a medirlo con el volumen de producción (H12). |
| `ix_ia_progvehiculos_ruta_fechasalida` | progvehiculos (idruta, fechasalida) | no | no | No se propone: la ocupación actual de un día empeora de unos 710 a 870 ms (880 ms con el índice 2): el plan sigue recorriendo timbradas_segmentos con un hash join; esa lectura no se arregla con un índice. |
| `ix_ia_timbradas_consolidado_ultima_actualizacion` | timbradas_consolidado (ultima_actualizacion) | no | sí (desde la ola A) | Se mantiene por §8.3, con prioridad baja: a 10.731 filas la lectura sin novedades baja de 1,3 ms a 0,01 ms y tras el resellado de 4,5 a 2,7 ms (no cumple el ahorro mínimo de 10 ms a este volumen). |
| `ix_ia_timbradas_consolidado_proceso_ultima_actualizacion` | timbradas_consolidado (proceso, ultima_actualizacion) | no | no | No se propone: a este volumen da lo mismo que el de la marca sola (1,3 a 0,01 ms y 4,4 a 2,2 ms); con varios operadores en la tabla, sería la alternativa al índice 4. |

El de `timbradas_anio` por `ultima_actualizacion` sigue en la propuesta por §8.3 con el argumento del de `timbradas_consolidado`. Para `timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`, que en la réplica no tienen filas de Sobusa (H4) y en la base de Extreme son de otros operadores, la propuesta trae el índice por (`proceso`, `ultima_actualizacion`): sin filas del proceso no hay marca guardada y la lectura del proceso empieza en la marca inicial, así que la marca sola no evita recorrer las filas ajenas. Se midió con ese volumen en una tabla temporal, dentro de una transacción que se revierte (`scripts/replica_lectura_consolidados.py`, `docs/evidencias/consolidados/lectura_por_proceso.md`). `explain_incremental.txt` (`scripts/replica_explain.py`) aplica esta propuesta entera como extreme_dba, con esos dos índices por (`proceso`, `ultima_actualizacion`), mide con las estadísticas al día (ANALYZE) y la borra al terminar; como en la réplica las dos tablas están vacías, su lectura es un Seq Scan con ellos y sin ellos.

Consultas medidas:

- `demanda_segmentos_sin_novedades`: Lectura incremental de la demanda horaria, todas las rutas, sin novedades (marca = la mayor) (`fuentes._SQL_DEMANDA_SEGMENTOS`).
- `demanda_segmentos_una_ruta_sin_novedades`: La misma lectura de UNA ruta (RNF-005, partición por ruta), sin novedades (marca = la mayor) (`fuentes._SQL_DEMANDA_SEGMENTOS + FILTRO_RUTAS_SEGMENTOS`).
- `demanda_segmentos_bloque`: Lectura incremental de la demanda horaria, todas las rutas, bloque de llegada de la réplica (`fuentes._SQL_DEMANDA_SEGMENTOS`).
- `demanda_segmentos_una_ruta_bloque`: La misma lectura de UNA ruta (RNF-005, partición por ruta), bloque de llegada de la réplica (`fuentes._SQL_DEMANDA_SEGMENTOS + FILTRO_RUTAS_SEGMENTOS`).
- `demanda_segmentos_bloque_con_union_final_de_rutas`: Referencia, no es una lectura de la API: la del bloque de llegada con la unión final de rutas que la consulta tenía antes (`formulación anterior de fuentes._SQL_DEMANDA_SEGMENTOS`).
- `segmentos_ventana_sin_novedades`: Refresco de segmentos: ventana de solape sin novedades (marca = la mayor), el costo fijo de cada refresco (`segmentos_refresco.SQL_FUENTE_VENTANA`).
- `segmentos_ventana_bloque`: Refresco de segmentos: ventana de solape desde el bloque de llegada de la réplica − 15 min (`segmentos_refresco.SQL_FUENTE_VENTANA`).
- `segmentos_grano_diario_1_fecha`: Refresco de segmentos: grano diario de la última fecha (lo que relee un incremental con una fecha cambiada) (`segmentos_refresco.SQL_FUENTE_DIA`).
- `segmentos_grano_diario_7_fechas`: Refresco de segmentos: grano diario de un tramo de 7 fechas (12,5 % de la réplica; con el histórico completo serían unas 7 de 1.095 fechas) (`segmentos_refresco.SQL_FUENTE_DIA`).
- `segmentos_rango`: Refresco de segmentos: rango de la fuente (min/max de fecha y marca) (`segmentos_refresco.SQL_FUENTE_RANGO`).
- `ocupacion_actual`: Ocupación actual por segmento: viaje × segmento de las 51 franjas de un día (§10.1) (`fuentes._SQL_CARGA_SEGMENTOS`).
- `viajes_de_una_ruta`: Viajes de una ruta y un día con su conteo de segmentos (§5.3, ALT-006 y ALT-009) (`fuentes.sql_viajes_ruta(con_segmentos=True)`).
- `consolidado_sin_novedades`: Consolidado: lectura incremental del proceso sin novedades (marca = la mayor), lo de cada ciclo entre dos cierres (`fuentes.consulta_incremental (TABLAS_CON_PROCESO)`).
- `consolidado_resellado`: Consolidado: la lectura del proceso tras el resellado nocturno (marca = la mayor − solape: fn_consolidar vuelve a sellar toda la tabla, H7; las huellas descartan lo repetido) (`fuentes.consulta_incremental (TABLAS_CON_PROCESO)`).
- `consolidado_todos_los_procesos`: Consolidado: la lectura tras el resellado sin filtrar el proceso (como antes de esta revisión) (`fuentes.consulta_incremental (proceso «*»)`).
- `consolidado_carga_inicial`: Consolidado: carga inicial del proceso (marca inicial, toda la tabla) (`fuentes.consulta_incremental (TABLAS_CON_PROCESO)`).
- `consolidado_agregado_rutas`: Consolidado: agregado de las rutas tocadas para el contraste (`consolidados._SQL_FUENTE[timbradas_consolidado]`).
- `consolidado_conteo_del_proceso`: Consolidado: el count(*) del proceso que hacía _sin_filas en cada ciclo sin cambios (ya no se hace) (`consolidados._SQL_CONTEO (retirado)`).
- `consolidado_existe_el_proceso`: Consolidado: EXISTS del proceso (alternativa al count(*)) (`alternativa medida`).

Las cifras absolutas dependen de la carga del equipo (la réplica corre en el mismo equipo que las pruebas); la comparación es la de cada transacción, con la misma carga. Crear los índices sigue siendo decisión de Extreme (§8.3).
