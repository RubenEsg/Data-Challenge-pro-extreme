# Capa de segmentos: agregación materializada y refresco en la cola

Especificación v1.5: §6.1 (promedios, máximos y mínimos por segmento), §7.1 («las peticiones HTTP no se bloquean
durante lecturas masivas»), RNF-002 (consulta paginada con p95 < 2 s), RNF-004 (lecturas largas como jobs con
progreso y reintento) y RNF-005 (procesamiento particionable por fecha y ruta).

## Qué cambió

Hasta la migración 0007, `GET /api/v1/segmentos/estadisticas` agregaba `timbradas_segmentos` de la base de Extreme
(2,77 millones de filas en la réplica) dentro de cada petición: 8,8 s en frío y 11,9 s en caliente sin filtros, y
2,3 a 2,9 s con `idruta` (`docs/evidencias/pruebas/k6_volumen.txt`). Desde la migración 0008:

- la consulta lee una **agregación materializada** en el esquema propio `ai_frecuencias` y nunca toca la base de
  Extreme;
- la agregación la calcula un **trabajo de la cola** de tipo `segmentos` (`app/servicios/segmentos_refresco.py`), con
  la misma reserva, latido, reintento con espera, intentos auditados y cierre con cerca que los demás trabajos
  (`app/servicios/cola.py`);
- los resultados son **idénticos** a los de la agregación directa (el mismo JSON, fila por fila), que se conserva en
  `app/servicios/segmentos.py::estadisticas_directas` como referencia de las pruebas.

## Tablas (migración 0008, solo en `ai_frecuencias`)

| Tabla | Grano | Para qué |
|---|---|---|
| `segmento_estadistica_dia` | segmento × fecha × hora (llave primaria), con la estacionalidad vigente en la fecha y el día ISO | Medidas sumables por día: viajes, suma, máximo y mínimo de subidas, bajadas y pasajeros. Cualquier rango de fechas se vuelve a agregar exacto sin leer la base de Extreme. Índices por fecha y por ruta y fecha. |
| `segmento_estadistica` | segmento × estacionalidad × día ISO × hora (el de la respuesta) | Lo que sirve la API sin rango de fechas. Mismos campos y tipos que la agregación directa (promedios redondeados a 3 decimales, totales NUMERIC). Índice del orden por omisión (`idruta, nro_segmento, id_estacionalidad, id_dia_semana, hora, id_segmento`), por segmento y por día y hora. |
| `segmento_estadistica_refresco` | una fila por refresco terminado | Marca del refresco: ejecución, modo, `actualizado_en`, período cubierto, filas, fechas releídas, marca de agua de la fuente (`ultimaactualizacion`) y huella de los catálogos que fijan las dimensiones. |

`execution_log.tipo` admite `segmentos`: la migración lee la lista vigente de la restricción y le agrega el tipo (la
bajada lo quita), para no pisar tipos que agreguen otras migraciones encadenadas.

## Exactitud frente a la agregación directa

- Unidad de observación, estacionalidad (la vigente en la fecha para el proceso de la ruta, con el desempate de
  `fn_insert_timbradas_anio`) y día ISO: el mismo SQL de la agregación directa, sumado por fecha.
- Promedio: `ROUND(SUM(suma) / SUM(viajes), 3)`, que es la misma `numeric_div` de las mismas sumas y conteos que hace
  `AVG` sobre los viajes; máximos y mínimos: `MAX` y `MIN` de los diarios; días: filas diarias del grupo (una por
  fecha); totales y primera y última fecha: `SUM`, `MIN` y `MAX`.
- Con un rango de fechas que cubre todo el período agregado se usa el grano de la respuesta (el filtro no excluye
  nada); con otro rango se vuelve a agregar solo ese rango desde el grano diario.
- El orden termina siempre en `id_segmento`: dos segmentos de configuraciones distintas pueden compartir ruta y
  `nro_segmento`, y sin ese desempate el contenido de cada página quedaría al azar.

Pruebas: `tests/integracion/test_segmentos_materializados.py` (datos sintéticos con los casos borde: errata E2,
pasajeros negativos de H9, fechas sin estacionalidad, vigencias superpuestas y empatadas, ruta de otro proceso y
empates de `nro_segmento`) y `tests/replica/test_segmentos.py` (la réplica, en solo lectura). Evidencia:
`docs/evidencias/pruebas/segmentos_equivalencia.json`.

## El refresco

Lo encolan, siempre que la base operacional esté configurada (`FUENTE_DATABASE_URL`):

1. el planificador interno (`PLAN_SEGMENTOS_CRON`, por omisión `45 5 * * *`, después del ciclo diario de las 05:15),
   una sola fila por franja aunque corra en varias réplicas;
2. el ciclo diario de frecuencia, al terminar, si leyó datos nuevos;
3. `POST /api/v1/segmentos/estadisticas/refrescar` (rol analista; 202 con el `execution_id`; cuerpo opcional
   `{"modo": "auto" | "completo" | "incremental" | "rango", "desde", "hasta"}`);
4. `GET /api/v1/segmentos/estadisticas` cuando la agregación todavía no existe: responde 200 con
   `disponible: false` y el refresco en `refresco`, sin bloquear.

No se duplica: si ya hay uno igual en cola, se devuelve ese. Buscar y crear van bajo un candado de asesoría de
transacción (`7441009`), así que tampoco se duplica con peticiones simultáneas: sin él, 10 peticiones a la vez que
encontraban la agregación vacía dejaban de 5 a 8 trabajos repetidos
(`tests/integracion/test_segmentos_materializados.py::test_peticiones_simultaneas_no_duplican_el_refresco`). Dos
refrescos nunca corren a la vez (candado de asesoría de transacción `7441008`).

Modos:

| Modo | Qué relee de la fuente |
|---|---|
| `completo` | Todas las fechas de `timbradas_segmentos`. Es también el modo efectivo si no hay refresco anterior, si cambió la huella de `rutas_segmentos`, `rutas` o `estacionalidades_anio`, o (en `auto`) si el último completo tiene más de `SEGMENTOS_COMPLETO_DIAS` días (así se recogen las filas borradas). |
| `incremental` | La ventana de solape son las filas cuya `ultimaactualizacion` es posterior a la marca del refresco anterior menos `FUENTE_SOLAPE_MIN` minutos (la marca de Extreme es la hora de inicio de su transacción, hallazgos H7 y H10). Desde la migración 0012 cada refresco guarda las huellas por fecha de esa ventana (`segmento_estadistica_refresco.huellas_solape`) y el siguiente relee solo las fechas cuyas huellas cambiaron, entraron o salieron de la ventana. Si ninguna cambió, termina `sin_cambios` sin escribir una sola fila de la agregación (ver «Refresco sin cambios»). |
| `rango` | Las fechas pedidas, acotadas a las que existen en la fuente. |
| `auto` | Incremental, o completo según las reglas de arriba. Es el del planificador y el del ciclo. |

Lectura de la fuente: con el usuario de solo lectura (`FuentePostgresSoloLectura`: `SET TRANSACTION READ ONLY`,
`statement_timeout` de `FUENTE_STATEMENT_TIMEOUT_MS`, ROLLBACK y circuit breaker), por tramos de a lo sumo
`SEGMENTOS_DIAS_POR_LOTE` días (31 por omisión). Si un tramo agota el `statement_timeout` se parte solo: por mitades de
fecha y, en un solo día, por ruta (RNF-005), hasta `MAX_TIEMPOS_AGOTADOS` (12) veces por refresco; pasado ese tope la
fuente está sobrecargada y el trabajo vuelve a la cola con su espera. La fuente de esta capa se crea con
`cancelacion_responde=True`: el tiempo agotado sube como `SentenciaCancelada`, que el circuit breaker `fuente_postgres`
no cuenta como caída. Antes, el tercer tiempo agotado seguido abría ese circuito (el mismo de la ingesta y los
catálogos): la partición se cortaba con `CircuitoAbierto` y la fuente quedaba bloqueada 60 s para todos
(`tests/unit/test_segmentos.py::test_el_tiempo_agotado_no_abre_el_circuito_compartido_y_la_particion_llega_al_fondo`,
`tests/unit/test_circuito.py::test_tiempo_agotado_abre_el_circuito_salvo_con_cancelacion_responde`). En la réplica,
la lectura de un tramo de 31 días (194 mil filas del grano diario, de 1,4 millones de timbradas) tarda de 6 a 11 s
según la carga del equipo (10,6 s y 7,3 s para enero y febrero en la revisión), lejos de los 30 s del límite.

Costo en la base de Extreme (§8.3, no interferencia): solo SELECT de solo lectura, nunca un objeto nuevo.
`timbradas_segmentos` no tiene índice por `fecha` ni por `ultimaactualizacion`. Para esa tabla la propuesta al DBA
(`docs/evidencias/replica/propuesta_indices.sql`) trae exactamente dos índices: por `ultimaactualizacion` (1) y por
`id_viaje` (2); **no** trae uno por `fecha`. Medido en la réplica con `EXPLAIN (ANALYZE, BUFFERS)`, cada índice creado
dentro de una transacción que se revierte (`scripts/replica_indices_candidatos.py`,
`docs/evidencias/replica/indices_candidatos.md`): con el de `ultimaactualizacion`, la ventana de solape de un refresco
sin novedades baja de unos 116 ms a 0,02 ms (deja de recorrer la tabla en cada refresco). Un índice por `fecha` no
mejora el grano diario a este volumen (una fecha, de 259 a 218 ms; siete fechas, el 12,5 % de la réplica, empeora de
1.407 a 1.621 ms) y por eso no se propone; con los dos índices, el rango de la fuente (`min`/`max` de `fecha` y de la
marca) bajaría de 178 a 0,03 ms. Con el histórico completo (unos 58 millones de filas proyectadas) siete fechas serían
el 0,6 % de la tabla: el índice por `fecha` queda para medirlo con el volumen de producción (pregunta de H12). Sin
índices, cada lectura del refresco recorre la tabla: un incremental son dos recorridos (la ventana y el grano diario de
las fechas cambiadas), uno completo, uno por tramo más el del rango; en la réplica, cada recorrido de los 537 MB tarda
de 0,1 a 6 s según la consulta y el tramo. La fuente entrega cada fila del grano diario como una línea
CSV armada por PostgreSQL, que el trabajo pasa tal cual a COPY: casi no convierte valores en objetos de Python, así que
el refresco le quita poco GIL a las peticiones que atiende el mismo proceso.

Escritura: cada tramo reemplaza sus fechas en `segmento_estadistica_dia` con COPY. Un refresco completo rehace
`segmento_estadistica` entera desde el grano diario; uno incremental o de rango solo vuelve a agregar las claves
(segmento × estacionalidad × día × hora) que tenían o traen las fechas releídas: cada tramo saca de
`segmento_estadistica` esas claves antes y después de reemplazar sus fechas y, al final, se agregan desde todo el grano
diario las claves que quedaron sin fila (`reagregar_faltantes`). Como la tabla era la agregación exacta del grano
diario, el resto no cambia y el resultado es el mismo que rehacerla entera
(`tests/integracion/test_segmentos_materializados.py::test_refrescos_parciales_seguidos_dan_lo_mismo_que_rehacer_todo`).
Después se deja la marca. Todo va en la MISMA transacción que el cierre con
cerca de la cola: si el intento falla o pierde la reserva, se revierte entero y la API sigue sirviendo la versión
anterior (nunca se borra antes de tener la nueva). Las consultas leen con MVCC, así que no esperan al refresco.

### Refresco sin cambios (migración 0012)

Con `FUENTE_SOLAPE_MIN=15` (por omisión) la ventana de solape nunca queda vacía mientras haya filas con la marca
máxima: hasta la migración 0011, cada ciclo releía todas sus fechas y rehacía `segmento_estadistica` entera aunque la
fuente no trajera nada nuevo. Ahora el refresco lee la ventana agrupada por fecha y marca (`SQL_FUENTE_VENTANA`: filas,
sumas de subidas, bajadas y pasajeros y la suma de `hashtext` del contenido de cada fila, en un solo recorrido de la
tabla, como la consulta de antes) y la compara con las huellas que dejó el refresco anterior para la misma ventana
(mismo solape y misma marca de inicio). Una fila nueva, cambiada (Extreme le vuelve a poner la marca) o borrada dentro
de la ventana cambia la huella de su fecha, y solo esa fecha se relee; una fila tardía con marca anterior al inicio de
la ventana sigue fuera, como antes (para eso está el solape), y las filas borradas fuera de la ventana las recoge el
refresco completo periódico (`SEGMENTOS_COMPLETO_DIAS`). Sin huellas comparables (un refresco anterior a la 0012 u
otro `FUENTE_SOLAPE_MIN`) relee la ventana entera, como antes, y deja las huellas para el siguiente.

Medido en la réplica, en solo lectura y sin filas nuevas (`docs/evidencias/pruebas/segmentos_sin_cambios.json`,
`tests/replica/test_segmentos.py::test_refresco_sin_cambios_no_relee_la_ventana_de_solape_y_mide_la_diferencia`):

| Incremental sin filas nuevas | Fechas releídas | Filas leídas de la fuente | Filas del grano de la respuesta reescritas | Versiones de fila escritas o quitadas (respuesta / diario) | Duración |
|---|---:|---:|---:|---:|---:|
| Sin huellas comparables (el primer incremental tras la 0012; relee la ventana como hasta la 0011) | 26 | 164.206 | 113.247 | 226.494 / 328.412 | 14,3 s |
| Ahora (con las huellas del refresco anterior) | 0 | 0 | 0 | 0 / 0 | 0,5 s |

La primera fila es el código nuevo sin huellas: lee lo mismo que cada ciclo hasta la 0011 (26 fechas, 164.206 filas),
pero ya reagrega solo las claves de esas fechas; hasta la 0011, además, se rehacía `segmento_estadistica` entera (sus
129.801 filas, borradas y vueltas a insertar) en cada ciclo.

El resultado sigue idéntico a la agregación directa (`docs/evidencias/pruebas/segmentos_equivalencia.json`) y, tras
el refresco parcial sin huellas (113.247 claves reagregadas), las 129.801 filas de `segmento_estadistica` son
exactamente las de rehacerla entera desde el grano diario (0 distintas, `EXCEPT` en los dos sentidos). Las duraciones
son de una corrida con otras suites usando el mismo PostgreSQL local: varían de una corrida a otra (en otra, 10,5 s y
0,4 s).

Progreso: `GET /api/v1/frequency/executions/{execution_id}` muestra la etapa (`planificacion`, `lectura_fuente i/n
(desde a hasta)`, `agregacion`, `registro`) y el porcentaje; las métricas del trabajo traen el modo efectivo, los
tramos, el detalle de cada tramo leído (`tramos_leidos`: tramo, fechas, filas, partes en que se partió por el
`statement_timeout` y segundos), las fechas releídas, las filas leídas, las filas de los dos granos, el período y la
duración. La métrica Prometheus `api_ejecucion_etapa_segundos` mide cada etapa con su nombre solo (`lectura_fuente`,
no el tramo ni las fechas): su etiqueta sale de un conjunto cerrado (`ejecucion.ETAPAS_METRICA`, lo demás cuenta en
`otra`), así que un refresco con otras fechas no crea una serie nueva. El tramo y las fechas de cada lectura quedan en
`tramos_leidos`, en el log (una línea por tramo) y como atributo `detalle` del span `ejecucion.lectura_fuente`. Lo
prueban `tests/unit/test_cola_metricas.py::test_etapas_con_fechas_distintas_no_crean_series_nuevas` y
`tests/integracion/test_segmentos_materializados.py::test_la_metrica_de_etapas_queda_acotada_y_el_detalle_de_los_tramos_en_el_trabajo`.

## La consulta

`GET /api/v1/segmentos/estadisticas` (filtros `idruta`, `desde`, `hasta`, `id_segmento`, `id_estacionalidad`,
`id_dia_semana`, `hora`; paginación `limite`/`desplazamiento`; `orden` con lista blanca) agrega a la respuesta de
siempre `disponible`, `fuente` (`agregacion_materializada`), `actualizado_en` (-05:00) y `materializacion`
(ejecución, modo, último completo, período, filas y marca de la fuente). Lee la marca y los datos en una sola
transacción `REPEATABLE READ, READ ONLY`; solo entran las condiciones de los filtros presentes, para que el plan use
los índices. El total es el real aunque la página quede después del final. La exportación CSV/XLSX lee la misma
agregación; mientras se calcula por primera vez responde 503 `agregacion_pendiente` con el refresco encolado.

Sin base operacional y sin agregación guardada, todo responde como antes en modo offline (200 con
`disponible: false` y la razón; la exportación sale vacía con sus columnas; el POST responde 503
`fuente_no_configurada`).

`GET /api/v1/catalogos/segmentos` filtra, ordena y pagina el catálogo SIN geometría y arma la geometría solo de los
segmentos de la página (`app/servicios/catalogos.py::geometria_de_pagina`). La geometría ya armada se guarda POR
SEGMENTO y modo (`_memorizadas`): la página pide a la fuente solo los segmentos que faltan y la memoria queda acotada
por el número de segmentos (2.695), no por las combinaciones de página. En la primera versión se guardaba por página:
cada desplazamiento nuevo era una entrada que nunca se borraba (con una réplica simulada, 825 entradas tras 1.000
páginas al azar de 50 segmentos) y, en modo
offline, cada página volvía a leer la columna de geometría del Parquet (0,55 a 1 s por página, frente a 35 ms con la
caché de la tabla entera de antes). Con la memoria por segmento, en modo offline la primera página tarda 1,2 s, una
página nueva 0,55 s y una ya vista menos de 1 ms (`tests/unit/test_catalogos.py`).

## Configuración

| Variable | Por omisión | Qué hace |
|---|---|---|
| `PLAN_SEGMENTOS_CRON` | `45 5 * * *` | Cron del refresco programado (America/Bogota); solo con `FUENTE_DATABASE_URL`. |
| `SEGMENTOS_DIAS_POR_LOTE` | 31 | Días de `timbradas_segmentos` por lectura (1 a 366). |
| `SEGMENTOS_COMPLETO_DIAS` | 7 | Días máximos entre dos refrescos completos en modo `auto` (1 a 366). |
| `FUENTE_STATEMENT_TIMEOUT_MS` | 30000 | Límite de cada lectura de la fuente (si un tramo lo agota, se parte). |
| `FUENTE_SOLAPE_MIN` | 15 | Ventana de solape del modo incremental. |

## Rendimiento medido

`docs/evidencias/pruebas/k6_segmentos.txt` (y los `k6_segmentos_*.json`), generado el 13-11-2026 con
`python scripts/medir_segmentos.py` contra una API propia de un solo proceso en modo integrado (réplica 5434 con
`lector_ia`, base propia sembrada con 1.056 ejecuciones del ciclo final: 9.216 predicciones, 61.440 recomendaciones y
8.224 alertas, más que el año acordado). Entre paréntesis, la medición del 9-11-2026, con 396 ejecuciones y el equipo
al 100 % de CPU por otros procesos:

| Prueba | Resultado |
|---|---|
| Refresco completo (2 tramos de 31 días, 358.091 filas del grano diario, 129.801 del de la respuesta) | «ok» a los 33,8 s del POST, como trabajo de la cola (32,6 s) |
| `GET /segmentos/estadisticas?limite=50` en frío / en caliente (antes de la agregación: 8.783 / 11.882 ms) | 20,8 / 18,3 ms (34,8 / 60,6 ms) |
| Lo mismo con `idruta=2` (antes de la agregación: 2.916 / 2.279 ms) | 16,5 / 15,0 ms (22,0 / 59,4 ms) |
| `GET /catalogos/segmentos?limite=50` en frío / en caliente (antes: 5.004 / 65,5 ms) | 169,8 / 35,0 ms (326,3 / 48,7 ms) |
| Las 20 consultas paginadas de `k6/en_frio.js` | p95 de 173,8 ms en frío y 83,3 ms en caliente (239,8 y 61,1 ms) |
| 50 usuarios sobre la capa de segmentos (9 consultas distintas) DURANTE un refresco completo (`k6/segmentos.js`) | p95 de 332,4 ms, la peor consulta 411,0 ms, 0 % de errores, 3.806 peticiones; el refresco, 25,7 s de trabajo (1.113,9 ms, 1.580,8 ms y 2.496 peticiones) |
| Consultas paginadas con el volumen sembrado (`k6/consultas.js`) | p95 de 864,1 ms, 0 % de errores (1.053,6 ms) |
| 30 usuarios durante una ingesta incremental desde la réplica (2.757 filas) | p95 de 574,5 ms durante la ingesta, 9.077 consultas, 0 % de errores, ingesta «ok» en 225,8 s (793,3 ms, 3.008 consultas y 93,8 s) |

La ingesta tarda más que el 9-11-2026 (225,8 s frente a 93,8 s). El ciclo hace hoy más trabajo (alertas observadas de
7 días, foto y ocupación por segmento, consolidados), la base tiene 2,7 veces más ejecuciones y 1,2 millones de fotos de variables, y la API atendió el triple de
consultas en el mismo proceso. Cuánto pesa cada causa no está medido.

Las exportaciones completas (`/predictions/export`, `/alerts/export`) tardan de 4,3 a 7,7 s con 9.216 predicciones y
8.224 alertas: son descargas del conjunto entero, no consultas paginadas, y se informan sin umbral.

Límite conocido: una consulta con un rango de fechas largo que no cubre todo el período vuelve a agregar el grano
diario de ese rango (unos 0,4 s por mes de datos de la réplica, sin concurrencia); si los rangos largos llegan a ser
el uso habitual, el paso siguiente es un grano mensual (meses completos del grano mensual y los bordes del diario).
