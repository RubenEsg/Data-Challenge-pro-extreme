# Lectura de los consolidados por proceso y sin count(*), medida en la réplica

Generado 2026-11-10T20:50:59-05:00 con `python -m scripts.replica_lectura_consolidados` como extreme_dba. Método: una transacción que se revierte; EXPLAIN (ANALYZE, BUFFERS), la más rápida de 2 corridas por consulta; lock_timeout 2s. Filas de sobusa en la réplica: timbradas_consolidado 10.731, timbradas_segmentos_anio 0, timbradas_segmentos_consolidado 0.

Antes: la lectura incremental sin filtrar el proceso (el filtro se hacía en Python) y, sin filas del proceso, el `count(*)` por tabla y proceso de `consolidados._sin_filas`. Ahora: la lectura con `proceso = :proceso` en el SQL (`fuentes.TABLAS_CON_PROCESO`) y ninguna otra consulta.

| Escenario | Lado | Consultas a la fuente | ms en el servidor | Filas leídas | Filas a la API | Huellas guardadas | estado_fuente |
|---|---|---|---|---|---|---|---|
| timbradas_consolidado | antes | 2 | 6,4 | 10.731 | — | — | — |
| timbradas_consolidado | ahora | 1 | 5,2 | 10.731 | — | — | — |
| timbradas_segmentos_anio | antes | 2 | 0,0 | 0 | — | — | — |
| timbradas_segmentos_anio | ahora | 1 | 0,0 | 0 | — | — | — |
| timbradas_segmentos_consolidado | antes | 2 | 0,0 | 0 | — | — | — |
| timbradas_segmentos_consolidado | ahora | 1 | 0,0 | 0 | — | — | — |
| timbradas_segmentos_consolidado_con_otro_operador | antes | 2 | 1.151,6 | 500.000 | 500.000 | 500.000 | 35,28 MB |
| timbradas_segmentos_consolidado_con_otro_operador | ahora | 1 | 272,8 | 0 | 0 | 0 | 0,00 MB |

Escenarios:

- `timbradas_consolidado`: timbradas_consolidado, sin novedades: desde la marca 2026-08-14T11:29:05.057003-05:00 menos el solape.
- `timbradas_segmentos_anio`: timbradas_segmentos_anio, sin filas del proceso en la réplica (H4): sin marca guardada, desde la marca inicial.
- `timbradas_segmentos_consolidado`: timbradas_segmentos_consolidado, sin filas del proceso en la réplica (H4): sin marca guardada, desde la marca inicial.
- `timbradas_segmentos_consolidado_con_otro_operador`: timbradas_segmentos_consolidado con 1.384.299 filas de cootransoriente y ninguna de sobusa (H4), todas con el sello del último cierre (H7): cada ejecución, desde la marca inicial.

La tabla temporal se cargó con 1.384.299 filas (129 segmentos por ruta × las filas de timbradas_consolidado de sobusa) en 2,00 s y existió solo en la transacción revertida: al terminar, `to_regclass('pg_temp.timbradas_segmentos_consolidado')` es nulo. Antes, la API traía 500.000 filas ajenas (la lectura llegaba al límite de filas) en 6,17 s, calculaba sus huellas en 6,87 s y guardaba 500.000 en `marca_agua_tabla.estado_fuente` (35,28 MB de JSON), en cada ejecución: con el sello del cierre (H7) toda la tabla cae en la ventana de solape. Ahora no trae ninguna.

Índices candidatos para las tablas por segmento, creados sobre la TEMPORAL dentro de la misma transacción (nunca sobre la tabla real) y medidos con la lectura de ahora (la del proceso desde la marca inicial):

| Índice | Columnas | ms | Filas | Escaneos |
|---|---|---|---|---|
| (ninguno) | — | 272,8 | 0 | Seq Scan timbradas_segmentos_consolidado |
| `ix_ia_tmp_marca` | ultima_actualizacion | 261,2 | 0 | Seq Scan timbradas_segmentos_consolidado |
| `ix_ia_tmp_proceso_marca` | proceso, ultima_actualizacion | 0,0 | 0 | Index Scan timbradas_segmentos_consolidado ix_ia_tmp_proceso_marca |

Cumple el criterio y es el más rápido `ix_ia_tmp_proceso_marca` (proceso, ultima_actualizacion): la lectura del proceso baja de 272,8 a 0,0 ms; `ix_ia_tmp_marca` (ultima_actualizacion): 261,2 ms (no cumple el criterio). La marca sola no sirve aquí: todas las filas de los otros operadores son posteriores a la marca inicial (sin filas del proceso no hay marca guardada), así que el índice no evita recorrerlas.

Las cifras absolutas dependen de la carga del equipo (la réplica corre en el mismo equipo que las pruebas). Sin índice sobre `proceso` ni sobre `ultima_actualizacion` (H12) la lectura sigue recorriendo la tabla; lo que se quita es el segundo recorrido (`count(*)`) y las filas de otros operadores que viajaban a la API. Crear índices es decisión de Extreme (`docs/evidencias/replica/propuesta_indices.sql`).
