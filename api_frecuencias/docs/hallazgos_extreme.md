# Hallazgos para Extreme Technologies (scripts, triggers, datos y especificación)

Lo encontrado al ejecutar los 8 scripts de Extreme **sin modificarlos** sobre una réplica local de la base operacional
(PostgreSQL 14 + PostGIS, `docker-compose.yml` servicio `operacional`; scripts en `replica/extreme` con `SHA256SUMS`) y
al hacer llegar datos reales por su trigger. Ningún hallazgo se corrigió en los scripts: las correcciones mínimas para
poder ejecutarlos están aparte (`replica/errata`) y cada una tiene una prueba que muestra el fallo sin ella. Ninguna
consulta de este documento se hizo sobre la base compartida del reto.

Cada hallazgo trae la evidencia reproducible y **la pregunta exacta** para Extreme (§19 «Información que debe suministrar
Extreme»). Los cinco primeros bloquean o cambian la integración; los siguientes afectan la interpretación o el
rendimiento. H13 no sale de los scripts sino de los parámetros operativos (ciclo, flota, intervalo programado y límites
de headway) con que se calcula la recomendación. H14 a H16 son dudas sobre el texto de la especificación y sobre la
regla de despacho actual: mientras llega la respuesta, el sistema funciona con un supuesto declarado (S0, S12 y S14 en
la sección 0 de `documentos/mapeo_especificacion.md`, y la fila de las rutas en su sección 6). H17 sale del contraste
de los consolidados de Extreme con la agregación propia, que el ciclo hace desde la migración 0013. Al final, «Otras
preguntas para Extreme» reúne dos supuestos de la API que no salen de un hallazgo: a qué rutas aplica una novedad sin
filas en `novedades_viales_ruta` y quién recibe el reporte de unicidad de cada lote.

Las correcciones de la réplica tienen nombre propio y cada una cita su hallazgo en la cabecera: `E1_rutas_segmentos_config.sql`
corresponde a H2, `E2_unique_timbradas_segmentos.sql` a H3 y `H1_armonizar_estacionalidades.sql` a H1.

| # | Hallazgo | Severidad | Corrección en la réplica | Evidencia |
|---|---|---|---|---|
| H1 | `estacionalidades_anio` pertenece a otro proceso | Bloquea la liquidación | `replica/errata/H1_armonizar_estacionalidades.sql` | `docs/evidencias/replica/replica_errata.txt` |
| H2 | El script 1 no corre tal cual | Bloquea 6 tablas | `replica/errata/E1_rutas_segmentos_config.sql` | `replica_errata.txt` (E1: 6 errores sin la corrección, 1 con ella), `replica_carga.txt` (con E1, `rutas_segmentos_config` y `rutas_segmentos` cargan 22 y 2.695 filas) |
| H3 | Llave de `timbradas_segmentos` contradictoria | Pierde datos | `replica/errata/E2_unique_timbradas_segmentos.sql` | `replica_errata.txt` |
| H4 | Scripts 5, 6 y 99 filtran `cootransoriente` | No procesan nada | Ninguna (se ejecutan igual) | `replica_carga.txt` (scripts 99, 5 y 6 tal cual: las mismas filas antes y después), `docs/evidencias/consolidados/contraste_consolidados.md` (tablas por segmento sin filas de Sobusa) |
| H5 | Objetos que los scripts suponen y no se entregaron | Réplica inferida | DDL deducido del código | `replica_objetos.txt` |
| H6 | Viajes «aptos» sin fecha de fin: FALSE sin aviso | 7,8 % de viajes sin liquidar | Ninguna | `replica_llegada.json` y este documento |
| H7 | El cierre resella todo y sus promedios no coinciden con la exportación | Marca de agua inútil sola | Huella de contenido en la API | `replica_llegada.json` |
| H8 | Marcas sin zona y con la hora de inicio de la transacción | Lectura incremental puede perder filas | Solape + `SET LOCAL TimeZone` | `tests/replica/test_llegada.py` |
| H9 | `timbradas_segmentos.pasajeros` no es ocupación | Medida no interpretable | Se reporta tal cual; la ocupación se deriva en la capa propia de las subidas y bajadas por segmento (`docs/ocupacion_segmentos.md`) | este documento, `docs/evidencias/ocupacion/perfil_ocupacion_segmentos.md` |
| H10 | El trigger asigna el bloque por fila; el histórico, por fin de viaje | Semántica distinta | Se compara por sumas | `replica_llegada.json`, `docs/evidencias/consolidados/contraste_consolidados.md` («Por qué no por hora») |
| H11 | No se entregó quién llama la liquidación y el cierre | Orden supuesto | El simulador los llama en orden | — |
| H12 | Rendimiento: trigger, marcas sin índice, FK sin índice | Costo crece con el histórico | Propuesta de índices | `explain_incremental.txt`, `docs/evidencias/cola/lectura_por_ruta_replica.txt` |
| H13 | Ciclo, flota e intervalo programado no cuadran; el plan D5 admite 35 salidas por hora (1,71 min) frente al mínimo gobernado de 2 min | Cambia la viabilidad de la recomendación | Se reporta: horas «no viables» con su motivo; los valores oficiales se registran con `PUT /api/v1/catalogos/flota` | `docs/evidencias/respuesta/respuesta_reto.md` |
| H14 | La «espera máxima» de §5.1 (5 min) admite dos lecturas: intervalo entre despachos o espera media del pasajero | Cambia el headway máximo: 5 o 10 min | Supuesto S12: headway máximo efectivo = min(`headway_maximo_min`, 2 × `espera_max_min`) | `tests/unit/test_respuesta.py::test_espera_maxima_acota_el_headway_maximo_d1` |
| H15 | No hay un criterio escrito de cómo fija hoy Sobusa la frecuencia; la línea base B1 lo formaliza como el promedio de las ocho semanas anteriores. `rutas.frecuenciadespachos` no dice su unidad | Cambia la línea base contra la que se mide el modelo y el headway vigente con que se compara la recomendación | Supuestos S0 y S14 | `docs/evidencias/modelo/evaluacion_modelo.md` (B1), `docs/evidencias/gobierno/frecuenciadespachos.json` |
| H16 | §19 escribe «Silencio (14/15)», pero en la tabla `rutas` exportada SILENCIO es la ruta 2 con código 2, y el código 15 es de CL 72 | Identificación de la ruta | Se toman las rutas por su nombre | `datos/catalogo_rutas.json` |
| H17 | `timbradas_anio` cuenta viajes con más de una estacionalidad y las bajadas de CL 72 no cuadran | Cambia el consolidado: viajes por día y bajadas | Ninguna: el contraste lo registra (CONTR-001, bloqueante en su llave) | `docs/evidencias/consolidados/contraste_consolidados.md` |

## H1. `estacionalidades_anio` es de otro proceso y `"Procesos"` de Sobusa no tiene estacionalidad

**Qué pasa.** Las 231 filas de `estacionalidades_anio` tienen `proceso = 'cootransoriente'`, y la fila de Sobusa en
`"Procesos"` tiene `id_estacionalidad` y `ultima_estacionalidad` en NULL. `fn_insert_timbradas_anio` busca la
estacionalidad con `ea.proceso = v_progvehiculos.proceso` y, si no la encuentra, termina con `RETURN FALSE`.

**Evidencia.** Sobre 10 viajes reservados aptos, en transacciones que se deshacen: TRUE en 0 de 10 sin la armonización y
en 8 de 10 con ella (`replica_errata.txt`, sección H1). Los 2 FALSE restantes son H6.

La ocupación por segmento de §10.1 también la necesita: el perfil histórico agrupa por la estacionalidad, que con las
exportaciones queda nula para Sobusa (`docs/evidencias/ocupacion/perfil_ocupacion_segmentos.md`). Lo mismo el
contraste de los consolidados de Extreme (migración 0013): los días de cada estacionalidad salen de
`estacionalidades_anio`, y si el histórico propio no trae la estacionalidad, el contraste compara por ruta y día ISO,
sumando las estacionalidades de los dos lados (`docs/consolidados_ciclo.md`, sección 3).

**Pregunta.** ¿Cuál es la tabla de estacionalidades vigente para el proceso `sobusa`? ¿Las filas de `cootransoriente`
aplican también a Sobusa (y entonces `proceso` debería ser `sobusa`), o hay otra tabla o filtro que no se exportó?

## H2. El script «1. tablas.sql» tiene un error de sintaxis y le falta una columna

**Qué pasa.** En la línea 38 hay un `;` dentro de `CREATE TABLE rutas_segmentos_config` («syntax error at or near ";"»),
y a esa tabla le falta la columna `activo` que usan los scripts 2 y 7. El fallo arrastra a otras 5 tablas («relation …
does not exist»).

**Evidencia.** Sin E1: 6 errores y solo se crea `rutas_segmentos_porcion`. Con E1 (la tabla creada antes, con las columnas
de la exportación incluida `activo`): 1 error, el de sintaxis, y 6 `CREATE TABLE` (`replica_errata.txt`, E1).

**Pregunta.** ¿Pueden enviar el DDL real de `rutas_segmentos_config` (o `pg_dump --schema-only` de las tablas de
segmentación) y confirmar que `activo boolean NOT NULL DEFAULT true` existe en producción?

## H3. La llave única de `timbradas_segmentos` no coincide con la que usan el trigger y el script 5

**Qué pasa.** El script 1 define `UNIQUE (id_segmento, id_viaje)`; el `ON CONFLICT` del script 5 y la búsqueda del trigger
usan `(id_segmento, id_viaje, hora_inicio)`. Cuando un viaje pasa por el mismo segmento en dos bloques de 15 minutos, la
segunda fila se rechaza con «duplicate key … timbradas_segmentos_id_segmento_id_viaje_key» y la captura pierde datos.

**Evidencia.** Sin E2 se conserva 1 fila de 2 y Σ subidas = 3 de 5; con E2 (UNIQUE de 3 columnas) 2 de 2 y Σ = 5. En el
prototipo, 91 de 777 filas crudas (11,7 %) se perdieron sin E2. Con E2, la llegada de 584 filas reales reproduce la
exportación: 223 de 223 pares (segmento, viaje) iguales, Σ subidas 201 = 201 y Σ bajadas 209 = 209.

**Pregunta.** ¿Qué devuelve en producción
`SELECT indexdef FROM pg_indexes WHERE tablename = 'timbradas_segmentos';`? ¿La llave única tiene 2 o 3 columnas?

## H4. Los scripts 5, 6 y 99 están escritos para `cootransoriente`

**Qué pasa.** Los tres filtran `proceso = 'cootransoriente'`. Con los datos de Sobusa se ejecutan sin error pero no
procesan ninguna fila: en `docs/evidencias/replica/replica_carga.txt`, sección «Scripts 99, 5 y 6 de Extreme
ejecutados tal cual», los conteos de filas son los mismos antes y después de cada script. El histórico de
`timbradas_segmentos` se cargó desde la exportación, que es lo que esos scripts produjeron en la base de Extreme.

Esa exportación solo trae subidas por segmento del 2023-01-01 al 2023-02-27. Con ellas se entrenó el modelo por
segmento y sentido, así que su error en 2025 no se puede medir (`docs/modelo_segmentos.md`, «Límites»), y con sus
subidas y bajadas se armó el perfil histórico de ocupación por segmento, que no ve otros meses
(`docs/ocupacion_segmentos.md`). El sentido del
segmento tampoco viene en las exportaciones: se aproxima con la mitad de la longitud del ciclo (supuesto S9).

Tampoco hay filas de Sobusa en `timbradas_segmentos_anio` ni en `timbradas_segmentos_consolidado`: el script 6 filtra
el mismo proceso y esas dos tablas no venían en la exportación. El paso de consolidados del ciclo (migración 0013) las
lee con su marca de agua y lo registra en `metricas.calidad.consolidados` como `sin_filas_fuente`, con este hallazgo.
Su contraste por segmento se probó con filas sintéticas
(`tests/integracion/test_consolidados_ciclo.py::test_segmentos_contrastados_con_la_agregacion_materializada`) y, en la
réplica, con filas reales de la liquidación de tres viajes dentro de una transacción que se revierte
(`tests/replica/test_consolidados_segmentos.py`, `docs/evidencias/consolidados/segmentos_filas_reales.json`). Que las
tablas siguen sin filas de Sobusa: `docs/evidencias/consolidados/contraste_consolidados.md` y
`tests/replica/test_consolidados.py::test_las_tablas_por_segmento_no_tienen_filas_de_sobusa_h4`.

**Pregunta.** ¿Con qué parámetros se ejecutaron los cargues iniciales para Sobusa? ¿Hay una versión de los scripts 5 y 6
para `sobusa`? ¿Se puede volver a ejecutar la segmentación para tener subidas por segmento de 2023 a 2025, y existe
en producción un campo con el sentido de cada segmento? ¿`timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`
tienen filas de Sobusa en producción?

## H5. Objetos que los scripts dan por existentes y que no se entregaron

**Qué pasa.** No vienen en las exportaciones ni en los scripts: `rutasgeograficas` (en la réplica se reconstruyó uniendo
los segmentos activos; las 3 líneas miden 67.217,7, 61.127,3 y 63.902,0 m, igual a la suma de `longitud_m`), `areascontrol`,
`rutas.zona_tolerancia_inicio/fin`, las tablas de trazabilidad y de zonas (`timbradas_anio_zonas`,
`timbradas_consolidado_zonas`, sus trazabilidades: DDL deducido del código de las funciones) y `conteo_pasajeros` (en el
reto se llama `conteo_pasajeros_destino`). Para Sobusa las tablas por zona quedan vacías: ninguna ruta tiene
`maneja_zonas = true` ni `id_tipo_tarifa = 2`, así que el bloque de zonas de `fn_insert_timbradas_anio` no se ejecuta;
`/api/v1/segmentos/zonas` lo explica en su respuesta.

**Pregunta.** ¿Pueden enviar el DDL de `rutasgeograficas`, `areascontrol`, `conteo_pasajeros` y las tablas de zonas y
trazabilidad? ¿Sobusa tendrá zonas tarifarias en algún momento (para mantener ese análisis de §6.2)?

## H6. Viajes «aptos» sin fecha de fin: la liquidación devuelve FALSE sin decir por qué

**Qué pasa.** `fn_insert_timbradas_anio` usa `fecha_fin_liquidacion` o, si falta, `fechafin`. Si ambas son NULL, la
búsqueda de estacionalidad con `fecha_inicio <= NULL` no encuentra nada y la función termina con `RETURN FALSE` en el
paso 5, **sin RAISE NOTICE** (es el único FALSE sin aviso).

**Evidencia.** Diagnóstico de los 2 viajes que seguían en FALSE con H1 (5141354 y 5141358), capturando los NOTICE: «[1]
progvehiculos cargado: … fechafin=<NULL>, fecha_fin_liquidacion=<NULL>», «[3] fecha_fin_real definida: <NULL>», «[4]
ultima_estacionalidad en Procesos: <NULL>» y FALSE. En toda la tabla: los 564.837 viajes tienen
`apto_estadisticas_historicas = TRUE` y **44.196 (7,8 %)** no tienen ni `fechafin` ni `fecha_fin_liquidacion`.

**Pregunta.** ¿Un viaje sin `fechafin` debe liquidarse (con qué fecha) o no debería estar marcado como apto? ¿Se puede
agregar un aviso antes de ese `RETURN FALSE` para que la liquidación deje rastro?

## H7. El cierre nocturno resella todo el consolidado y sus promedios no son los de la exportación

**Qué pasa.** `fn_consolidar_timbradas_historicas()` vuelve a escribir las 10.731 filas de `timbradas_consolidado` con una
`ultima_actualizacion` nueva, cambien o no. Además, calcula `promedio_subidas` y `promedio_bajadas` con
`CEIL(Σ / nro_viajes)` (entero hacia arriba), mientras la tabla exportada tiene promedios con decimales.

**Evidencia** (`replica_llegada.json`, `consolidacion` y `h7_resellado_visto_por_lector_ia`; diagnóstico en una
transacción que se deshace): 10.731 de 10.731 filas reselladas; subidas, bajadas y nro_viajes idénticos en todas;
`promedio_subidas` distinto en 6.712 filas y `promedio_bajadas` en 6.716, en promedio por 0,50. Por la marca de agua sola
la API reprocesaría la tabla entera cada noche; con la huella de contenido entrega solo las 7.952 filas que cambiaron y
descarta 2.779 resellos idénticos.

**Qué hace la API.** El paso de consolidados del ciclo (migración 0013) lee `timbradas_consolidado` con su propia marca
de agua y la misma huella: en la réplica, la segunda lectura descarta las 10.731 filas por huella. La regla CONS-001 de
§6.3 acepta el promedio exacto y el `CEIL` que escribe la función, y las 10.731 filas pasan la calidad sin errores
(`docs/evidencias/consolidados/contraste_consolidados.md`).

**Pregunta.** ¿La versión de `fn_consolidar_timbradas_historicas` entregada es la de producción? ¿El promedio oficial es
`CEIL(Σ/n)` o el valor con decimales de la tabla actual? ¿Puede el cierre actualizar solo las filas que cambian
(`WHERE … IS DISTINCT FROM`), para que `ultima_actualizacion` signifique «modificado»?

## H8. Marcas sin zona horaria y con la hora de inicio de la transacción

**Qué pasa.** `ultimaactualizacion` y `ultima_actualizacion` son `timestamp without time zone` y se llenan con `NOW()` /
`CURRENT_TIMESTAMP`: la hora del servidor al **inicio** de la transacción. Una sesión en UTC comparando contra una marca
con zona se corre 5 horas; y una captura que empieza antes de la lectura y confirma después queda con una marca menor que
la ya leída.

**Evidencia.** `tests/replica/test_integrado.py::test_marca_sin_zona_se_compara_en_hora_de_bogota` (con TimeZone UTC el
conteo cambia) y `tests/replica/test_llegada.py::test_solape_recupera_la_captura_que_confirma_tarde_exactamente_una_vez`
(sin solape las filas tardías se pierden; con 15 min se entregan una sola vez). La API fija `SET LOCAL TimeZone =
'America/Bogota'` y lee con ventana de solape y huella (`docs/integracion_postgresql.md`, §4).

**Pregunta.** ¿En qué zona corre el servidor de producción (`SHOW TimeZone`)? ¿Cuánto puede durar como máximo una
transacción de la captura (para fijar `FUENTE_SOLAPE_MIN`)? ¿Se podría usar `clock_timestamp()` o `timestamptz`?

## H9. `timbradas_segmentos.pasajeros` no es la ocupación del bus

**Qué pasa.** El trigger guarda `pasajeros = acumulada_subida − acumulada_bajada` de la última fila cruda del bloque:
la diferencia de los contadores **acumulados del dispositivo** desde su instalación, no la ocupación del viaje.

**Evidencia** (las 2.769.692 filas cargadas): 887.880 negativas (32,1 %), 1.856.613 mayores que 200 (67,0 %), mínimo
−253.482, máximo 216.316 y mediana 4.380. La capa analítica (`/api/v1/segmentos/estadisticas`) la reporta tal cual, con
esta advertencia; el modelo no la usa.

**Qué hace la API.** Para la ocupación por segmento de §10.1 no usa `pasajeros`: deriva la carga a bordo en la capa
propia (§11.1) con las subidas y bajadas por segmento de cada viaje, sin tocar el trigger (`app/servicios/ocupacion.py`,
`docs/ocupacion_segmentos.md`). Esas subidas y bajadas sí cuadran con el dispositivo: en los 26.350 viajes del perfil
de ene.–feb. 2023, la Σ de subidas y la de bajadas son idénticas a las de `conteo_viajes`, y la carga derivada
correlaciona 0,961 con `conteo_viajes.ocupacion_max` en los 21.511 de ellos con contadores consistentes
(`docs/evidencias/ocupacion/perfil_ocupacion_segmentos.json`, `validacion`).

**Pregunta.** ¿`pasajeros` debe ser la ocupación a bordo? Si es así, ¿la resta debe hacerse contra los acumulados al
inicio del viaje (`progvehiculos.acumulada_subida/_bajada`)?

## H10. Bloque horario por fila en el trigger y por fin de viaje en el histórico

**Qué pasa.** El trigger asigna `hora_inicio` según la hora de cada fila cruda (8 a 16 bloques de 15 minutos por viaje);
el cargue inicial del script 5 usa un solo bloque, el del fin del viaje, y `fn_insert_timbradas_anio` (paso 13) también
asigna todos los segmentos al bloque de fin. Por eso la equivalencia con la exportación se verifica por sumas por
(segmento, viaje), no por bloque.

Por lo mismo, el paso de consolidados del ciclo no contrasta `timbradas_consolidado` por hora. En la réplica, su
promedio por viaje por ruta × día ISO × hora difiere 20,6 % en la mediana del de los viajes asignados a su hora de
salida (la del histórico propio) y 1,3 % del de los asignados a su hora de fin; por ruta × día ISO × estacionalidad
las dos asignaciones coinciden (`docs/evidencias/consolidados/contraste_consolidados.md`, «Por qué no por hora»;
`tests/replica/test_consolidados.py::test_por_hora_de_fin_el_consolidado_se_reproduce_y_por_hora_de_salida_no_h10`).

Las dos tablas por segmento (`timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`) tampoco se contrastan por
hora. Con filas reales de la liquidación de tres viajes, todos los segmentos de cada viaje quedan en el bloque de su
fin (06:45 y 07:00) y la agregación propia los tiene en las horas de paso (5, 6 y 7). Con la hora en el grano, 100 de
las 162 llaves no encuentran la agregación propia y salen 129 diferencias groseras falsas; por segmento × día ISO ×
estacionalidad, las 90 llaves se comparan y no hay ninguna grosera
(`docs/evidencias/consolidados/segmentos_filas_reales.json`,
`tests/replica/test_consolidados_segmentos.py`). Por hora solo queda el rango (CONTR-003), que no bloquea
(`docs/consolidados_ciclo.md`, sección 3). En esa misma prueba, cuando un viaje tiene dos filas en `timbradas_segmentos`
para el mismo segmento (dos bloques de 15 minutos), la liquidación deja los conteos de una sola: 200 de las 201
subidas de los tres viajes.

**Por qué importa para la ocupación actual (§10.1).** La restricción reactiva del plan del día usa la ocupación de la
última hora cerrada, medida con los segmentos que ya llegaron de sus viajes. Si cada segmento llega cuando el bus lo
recorre, en un ciclo intradía solo están los tramos ya recorridos: un viaje dura unas 3,5 h (mediana de 206 min). En
el backtest de ene.–feb. 2023, de los 147 disparos con los viajes completos siguen 25 a las (h+1):05 y 35 a las
(h+1):30, con un piso de 0,42 y 0,81 veces el calculado con los viajes completos
(`docs/evidencias/ocupacion/backtest_restriccion_reactiva.md`, «En tiempo real»). Si las filas crudas llegan al
terminar el viaje, la ocupación de una hora llega unas 3,5 h después de sus salidas, fuera de la ventana de 2 h en que
la restricción puede actuar, y no actuaría dentro del día. Desde que el planificador encola los ciclos intradía
(`PLAN_INTRADIA_CRON`), la restricción se evalúa cada hora; cuánto actúa depende de esta latencia.
Cuándo llegan depende de cómo y cada cuánto inserta la captura en `conteo_pasajeros`, que no se entregó (H11).

**Pregunta.** ¿Cuál es el bloque oficial de un segmento: la hora en que el bus pasa por él o la hora de fin del viaje?
¿Las filas crudas de un viaje llegan a `conteo_pasajeros` mientras el bus avanza o todas al terminar el viaje, y con
qué retraso típico? Cuando un viaje tiene dos filas del mismo segmento en `timbradas_segmentos`, ¿la liquidación debe
sumarlas o dejar una sola?

## H11. Quién llama la liquidación y el cierre

**Qué pasa.** No se entregó el proceso que llama `fn_insert_timbradas_anio` (por viaje terminado) ni
`fn_consolidar_timbradas_historicas` (cierre). El simulador (`scripts/replica_simular_llegada.py`) los llama en ese orden:
llegada → liquidación por viaje → cierre. Tampoco se entregó la captura que inserta en `conteo_pasajeros`. La
ocupación actual por segmento (§10.1) lee `timbradas_segmentos`, que llena el trigger en cada inserción, así que no
espera a la liquidación ni al cierre; pero sí depende de cada cuánto inserta la captura (H10).

**Pregunta.** ¿Con qué periodicidad y en qué orden se ejecutan en producción, y desde dónde (cron, aplicación, pg_cron)?
¿Cada cuánto inserta la captura las filas crudas en `conteo_pasajeros` (en línea, por lotes o al terminar el viaje)?

## H12. Rendimiento de los objetos de Extreme

**Evidencia** (`docs/evidencias/replica/explain_incremental.txt`): ninguna tabla `timbradas_*` tiene índice por su
marca, así que cada lectura incremental recorre la tabla entera aunque no haya llegado nada (122 ms hoy en
`timbradas_segmentos`, con 2,77 M filas; con el histórico completo serían unos 58 M). La llave foránea
`timbradas_segmentos.id_viaje` no tiene índice. El trigger tarda unos 50 ms por fila cruda (36-81 ms según la carga).
`fn_segmentar_ruta` con porciones de 0,2 m pasó de 10 minutos en una sola ruta sin terminar (prototipo) y borra los
segmentos de su configuración, así que no se puede volver a segmentar con datos cargados (la llave foránea lo impide).

Tres lecturas nuevas de la API dependen de lo mismo. La lectura incremental de una sola ruta (RNF-005) recorre
`timbradas_segmentos` igual que la de todas: en la réplica, el SELECT de una ruta tardó de media 3,4 s frente a 3,9 s
el de todas (`docs/evidencias/cola/lectura_por_ruta_replica.txt`). El refresco de la agregación de segmentos
(`docs/segmentos_materializados.md`) busca las fechas cambiadas por `ultimaactualizacion` y relee esas fechas por
`fecha`, así que cada refresco son uno o más recorridos de la tabla. Y la lectura de la ocupación actual por segmento
(§10.1, `docs/ocupacion_segmentos.md`) cruza `timbradas_segmentos` por `id_viaje`, que no tiene índice.
Otras dos lecturas del ciclo también recorren tablas sin índice: los viajes de una ruta y un día que identifican el
viaje de ALT-006 y ALT-009 (`progvehiculos` por `date_trunc('hour', fechasalida)` y, en el ciclo integrado,
`timbradas_segmentos` por `id_viaje`; `docs/alertas_viajes_y_alt003.md`) y los consolidados de Extreme, que se leen
por `ultima_actualizacion` (`docs/consolidados_ciclo.md`).
Para `timbradas_segmentos`, la propuesta trae los índices por `ultimaactualizacion` y por `id_viaje`; no trae uno por
`fecha`. Trae también el de `progvehiculos` por ruta y hora de salida y los de `ultima_actualizacion` de los
consolidados. Con los índices, esas lecturas están medidas en `docs/evidencias/replica/indices_candidatos.md`: cada
índice en una transacción que se revierte y la propuesta entera con las estadísticas al día (ANALYZE). Con la
propuesta entera ninguna lectura de la API empeora: la lectura sin novedades baja de 169 a 0,1 ms, la del bloque
grande de 3,6 a 1,5 s y los viajes de una ruta de 811 a 9 ms; la ocupación actual no cambia (707 → 698 ms), porque
recorre `timbradas_segmentos` con un hash join. Sin índices, cada ciclo intradía recorre `timbradas_segmentos` en la
lectura incremental, en la ocupación por segmento y en los viajes del día de cada ruta: en la réplica son unos 3,1 s
por ciclo, y la proyección lineal al histórico completo da unos 63 s (`docs/evidencias/ocupacion/ciclo_intradia_fuente.md`).

**Pregunta.** ¿Pueden aplicar la propuesta `docs/evidencias/replica/propuesta_indices.sql` (todos `CREATE INDEX
CONCURRENTLY`, ninguno cambia tablas, triggers ni funciones) o indicar qué índices existen ya en producción
(`SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = 'public'`)? ¿Hay en producción un índice por `fecha`
en `timbradas_segmentos`?

## H13. Ciclo, flota e intervalo programado no cuadran, y el plan D5 admite un intervalo menor que el mínimo gobernado

**Qué pasa.** La recomendación usa, por ruta, tipo de día y hora, tres parámetros operativos que Extreme no suministró y
que se tomaron como medianas de 2025 (insumos D1): el ciclo de la ruta, la flota disponible y el intervalo programado.
Los tres no siempre cuadran entre sí:

- **Con la programación de hoy, los buses en ruta superan la flota.** Los vehículos que exige el intervalo programado
  (ciclo / intervalo) son más que la flota disponible en la hora pico: en día laboral (19-11-2025), SILENCIO necesita 47
  de 45 y CRA 54, 80 de 79; en domingo (23-11-2025), SILENCIO necesita 29 de 27. Es decir, el horario actual no se
  podría cumplir con la flota que dicen los mismos datos, o el ciclo o la flota de esa hora no son los reales.
- **El plan D5 admite hasta 35 salidas por hora (un intervalo de 1,71 min).** Los insumos del optimizador D5
  (`datos/insumos_d5_2025.parquet`, columna `nmax`) permiten 35 salidas por hora en CRA 54 y 32 en SILENCIO a las 5 h
  de los días laborales, donde la operación ya las tuvo. En cambio, el headway mínimo gobernado de §5.1 es de 2 min
  (`headway_minimo_min` en `threshold_config`, migración 0001; valor supuesto del equipo), es decir, 30 salidas por
  hora. La API no fuerza una cifra: esas horas salen «no viables» con su motivo (§10.3 y §18). Ejemplo: CRA 54, 19-11-2025,
  5 h, 34 salidas recomendadas, «No viable: intervalo de 1,76 min, menor que el mínimo de 2,0 min».

**Evidencia.** `docs/evidencias/respuesta/respuesta_reto.md` (tablas por ruta y hora, y la nota sobre ciclo, flota e
intervalo programado) y los archivos `docs/evidencias/respuesta/respuesta_2025-11-19.json` y `respuesta_2025-11-23.json`,
campos `vehiculos.requeridos_programados` frente a `vehiculos.flota_disponible`. El mismo cálculo lo devuelve
`GET /api/v1/respuesta`; lo prueban `tests/unit/test_respuesta.py::test_vehiculos_frente_a_la_flota` y
`tests/unit/test_respuesta.py::test_headway_minimo_gobernado_cambia_la_viabilidad`. Los topes de salidas por hora
están en la columna `nmax` de `datos/insumos_d5_2025.parquet` (35 en CRA 54 y 32 en SILENCIO a las 5 h de los días
laborales de 2025). En el plan D5 de 2025 (`x_D5`), CRA 54 pasa de 30 salidas a las 5 h en 174 días y llega a 35 en
3 de ellos.

**Pregunta.**

1. Para cada ruta, tipo de día y hora: ¿cuál es el ciclo oficial (minutos de vuelta completa) y la flota disponible?
   ¿El intervalo programado que sale de los datos (mediana de 2025 por ruta, tipo de día y hora) es el vigente? Con
   esos valores, SILENCIO laboral (47 de 45), CRA 54
   laboral (80 de 79) y SILENCIO domingo (29 de 27) no cuadran: ¿cuál de los tres datos hay que corregir?
2. Límites de headway (§19): ¿cuál es el intervalo mínimo permitido entre dos despachos de la misma ruta? Si en la
   madrugada laboral se aceptan hasta 35 salidas por hora (1,71 min), el mínimo de 2 min de `threshold_config` debe
   bajar para esa franja; si el mínimo es 2 min, el plan D5 debe limitarse a 30 salidas por hora.

**Cómo se registra la respuesta.** Con `PUT /api/v1/catalogos/flota` (rol admin): la flota por tipo de día y el ciclo
por tipo de día y hora de cada ruta quedan como una versión nueva de `threshold_config`, con motivo y responsable, sin
regenerar datos ni reiniciar. La franja de §10.2 y el plan del día la usan desde el cálculo siguiente
(`docs/gobierno_parametros.md`, sección 2). El headway mínimo se cambia con `PUT /api/v1/thresholds`.

## H14. La «espera máxima» de §5.1 admite dos lecturas

**Qué pasa.** La tabla de umbrales de §5.1 define la espera máxima como «tiempo máximo objetivo entre despachos» y le
da 5 minutos. Leída al pie de la letra, sería un headway máximo de 5 min. Pero se llama «espera», y la espera media de un
pasajero que llega al azar es la mitad del headway. Con la lectura literal, CL 72 (intervalo programado típico de 11,6 min
en día laboral, `datos/catalogo_rutas.json`) tendría que más que duplicar sus salidas en buena parte del día, aunque
la demanda no lo pida.

**Qué hace la API.** Usa la segunda lectura (supuesto S12 de `documentos/mapeo_especificacion.md`): headway máximo
efectivo = min(`headway_maximo_min`, 2 × `espera_max_min`) = min(10, 2 × 5) = 10 min. La regla se aplica en la
recomendación por franja y en el plan del día, y cada salida la escribe en su explicación (`REGLA_ESPERA` en
`app/servicios/optimizacion.py`). Los dos valores están versionados en `threshold_config`. Si Extreme confirma la
lectura literal, basta con una versión nueva de `espera_max_min` = 2,5 (o de `headway_maximo_min` = 5), sin tocar el
código.

**Pregunta.** ¿La «espera máxima» de 5 min es el intervalo máximo entre dos despachos de la misma ruta (headway ≤ 5
min) o la espera media del pasajero (headway ≤ 10 min)? ¿Es la misma en todas las rutas, tipos de día y franjas?

## H15. No hay un criterio escrito de cómo se fija hoy la frecuencia

**Qué pasa.** La formulación y la línea base B1 parten de que Sobusa fija hoy las salidas con el promedio de las ocho
semanas anteriores para la misma ruta, día y hora. La fuente es la visita del equipo a Sobusa. Allí nos dijeron que la
cantidad de buses «se estima manualmente» con «promedios y la experiencia» de los encargados, y que no usan un modelo
matemático ni predictivo. El número de semanas es nuestra formalización: no recibimos un documento con la regla.

**Por qué importa.** Todas las mejoras se miden frente a B1 (WAPE de 21,18 % en la prueba reservada y de 20,04 % en
todo 2025, `docs/evidencias/modelo/evaluacion_modelo.md`). Si la regla real es otra, la línea base cambia.

**La frecuencia vigente de la tabla `rutas`.** La recomendación compara su headway con dos referencias: el intervalo
programado que se observa en los datos (`frecuencia_actual_min`, mediana de 2025 por ruta, tipo de día y hora) y el
headway vigente de `rutas.frecuenciadespachos` (`frecuenciadespachos_min` y `diferencia_frecuenciadespachos_min`,
columnas de `recommendation` desde la migración 0010). `rutas.frecuenciadespachos` vale «5» en las tres rutas de la
exportación (`datos/catalogo_rutas.json`, `frecuenciadespachos_tabla_rutas`; en modo integrado la recomendación lo lee de
la tabla `rutas` de la fuente, con el catálogo de respaldo, y `fuente_frecuenciadespachos` dice de dónde salió), y la
tabla no dice su unidad. La API lo lee como minutos entre despachos (supuesto S14;
`app/servicios/optimizacion.py`, `frecuenciadespachos_min`, y `GET /api/v1/catalogos/rutas`), y usa el mismo valor en
todas las horas y tipos de día. De esa lectura dependen el headway vigente de §6.1 y §6.2 y su diferencia con el
recomendado (filas 6.1-11 y 6.2-02 de la matriz), la comparación de la frecuencia actual con la recomendada (RF-008) y
el criterio oficial de la frecuencia actual que pide §19 (fila 19-3). Detalle en `docs/gobierno_parametros.md`,
sección 3; evidencia en `docs/evidencias/gobierno/frecuenciadespachos.json`.

**Pregunta.** ¿Con qué regla fija hoy Sobusa el número de salidas por ruta y hora? ¿Es el promedio de las ocho semanas
anteriores para la misma ruta, día y hora, otro número de semanas u otro criterio? ¿Hay un registro del horario
programado de cada semana para compararlo con B1? ¿En qué unidad está `rutas.frecuenciadespachos`, que vale «5» en las
tres rutas: minutos entre despachos o despachos por hora? ¿Es el valor vigente para todas las horas y tipos de día?

## H16. «Silencio (14/15)» en §19

**Qué pasa.** §19 lista las rutas «KRA 54, Silencio (14/15) y Calle 72». En la tabla `rutas` exportada
(`datos/catalogo_rutas.json`), SILENCIO es la ruta con `idruta` 2 y código 2, CRA 54 tiene `idruta` 16 y código 10, y
CL 72 tiene `idruta` 21 y código 15. Ninguna tiene el código 14, y el 15 es de CL 72, no de SILENCIO. La API toma las
tres rutas por su nombre.

**Pregunta.** ¿Qué significa «(14/15)» junto a Silencio? ¿Son códigos de otra tabla, de las dos variantes o sentidos de
la ruta, o de rutas que no se exportaron? Si SILENCIO tiene variantes, ¿cuáles hay que incluir en el reto?

## H17. `timbradas_anio` cuenta viajes con más de una estacionalidad y las bajadas de CL 72 no cuadran

**Qué pasa.** El paso de consolidados del ciclo (migración 0013, `docs/consolidados_ciclo.md`) contrasta
`timbradas_consolidado` con el histórico propio por ruta × día ISO × estacionalidad, en los años cerrados 2023-2025.
En la réplica, los promedios por viaje cuadran (subidas: mediana 1,4 % y p90 4,5 %; bajadas: mediana 1,3 %), pero hay
31 incidencias y 11 son groseras (CONTR-001, bloqueante en su llave). Esto es lo que se ve en las tablas de Extreme:

- **Viajes con más de una estacionalidad.** Cinco festivos de 2025 tienen dos filas en `estacionalidades_anio`:
  2025-11-03, 2025-11-17, 2025-12-08 y 2025-12-25 (ids 1 a 4 y 169 a 172, cada par con la misma estacionalidad) y
  2025-06-30 (estacionalidades 19 y 20). `timbradas_anio` guarda los viajes de esas fechas con las dos filas, cada una
  con casi todos los viajes aptos de la fecha (2025-12-08: 244 y 244, frente a 244 aptos). Por eso el 8 y el 25 de
  diciembre salen con 90,0 a 111,8 % más viajes por día que los viajes válidos en las tres rutas, y los festivos de
  lunes (estacionalidades 1, 2 y 20), con 31,8 a 57,0 % más.
- **Días corrientes y lunes.** `DIAS_CORRIENTES` suma de 3,2 a 4,2 % más viajes que los aptos de los días corrientes
  en cada ruta y año de 2023 a 2025. En el contraste, los lunes también salen altos sin una fila repetida que lo
  explique: los de Semana Santa, con 30,8 a 38,6 % más viajes por día, y los corrientes, con 17,5 a 19,2 %.
- **Bajadas de CL 72.** En la ruta 21, el consolidado suma 11.710.210 bajadas en 2023-2025 frente a 7.403.174
  `numerobajadas` de los viajes válidos (+58 %), mientras sus subidas difieren +3,7 %. En los días corrientes, su
  promedio de bajadas por viaje sale 60,6 % más alto los miércoles, 61,5 % los jueves y 189,1 % los viernes.

Con la regla de `fn_insert_timbradas_anio`, cada viaje va a una sola estacionalidad (la de período más corto) y cuenta
una vez. El ciclo registra cada diferencia en `data_quality_error` y no corrige nada: con una diferencia grosera, la
llave queda fuera del análisis y la decisión es del responsable del consolidado (§6.3).

**Evidencia.** `docs/evidencias/consolidados/contraste_consolidados.md`: las incidencias, los totales por ruta y la
sección «De dónde salen las diferencias groseras de viajes por día (H17)», hechas con
`python -m scripts.contraste_consolidados` sobre la réplica, en solo lectura. Lo comprueban
`tests/replica/test_consolidados.py::test_h17_festivos_con_dos_filas_cuentan_dos_veces_y_los_dias_corrientes_suman_de_mas`
y, para las bajadas de la ruta 21,
`tests/replica/test_consolidados.py::test_el_ciclo_lee_valida_y_contrasta_el_consolidado_real_sin_romperse`.

**Pregunta.** ¿Con qué proceso se llenó `timbradas_anio` de Sobusa, si `fn_insert_timbradas_anio` asigna cada viaje a
una sola estacionalidad? ¿Las filas repetidas de 2025 en `estacionalidades_anio` (1 a 4 frente a 169 a 172, y las dos
del 30 de junio) son un error de carga, y cuál de cada par vale? ¿Un viaje de un festivo se cuenta también en
`DIAS_CORRIENTES`? ¿De dónde salen las bajadas de CL 72 de `timbradas_anio` (en `fn_insert_timbradas_anio`, la Σ de
`conteo_pasajeros.cantidad_bajada` del viaje), que no cuadran con `progvehiculos.numerobajadas` cuando las subidas sí?

## Otras preguntas para Extreme

Dos supuestos de la API que no salen de un hallazgo en los scripts. El sistema funciona con el supuesto declarado
mientras llega la respuesta.

1. **Novedades viales sin rutas.** §11.2 pide cruzar las novedades por fecha, rango horario y ruta. Una novedad con
   filas en `novedades_viales_ruta` afecta solo a esas rutas, y una sin filas se aplica a todas las rutas
   (`app/servicios/novedades.py`). En la base del reto y en la réplica la tabla está vacía y las 28 novedades de
   `novedades_viales_fecha` son de toda la ciudad (los días de Carnaval y sus eventos previos, y los partidos de la
   Selección en el Metropolitano), así que hoy todas aplican a las tres rutas
   (`docs/evidencias/replica/novedades_por_ruta_replica.json`). Si la tabla se llena, hay que regenerar el contexto
   (`scripts/preparar_datos_api.py` o `scripts/replica_contexto.py`) y reentrenar.
   **Pregunta.** Una novedad sin filas en `novedades_viales_ruta`, ¿aplica a todas las rutas o a ninguna? ¿La
   operación va a registrar las rutas afectadas de cada novedad?
2. **Destinatario del reporte de unicidad.** §6.3 pide reportar las llaves duplicadas al responsable del consolidado,
   sin corregirlas. Cada lote con duplicados (UNI-001) genera un reporte con cada llave y sus filas, que sale por el
   canal de correo simulado a `NOTIF_UNICIDAD_DESTINATARIOS`. Esa variable viene vacía, así que el reporte queda en
   `notification_log` como `pendiente_destinatario` (`docs/evidencias/datos/reporte_unicidad.json`); no se reenvía
   cuando se configure, y los lotes siguientes ya salen al destinatario.
   **Pregunta.** ¿Quién es el responsable del consolidado en Sobusa o en Extreme (§19, responsables técnicos) y a qué
   correo debe llegar el reporte?
