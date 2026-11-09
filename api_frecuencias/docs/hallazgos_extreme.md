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
regla de despacho actual: mientras llega la respuesta, el sistema funciona con un supuesto declarado (S0 y S12 en la
sección 0 de `documentos/mapeo_especificacion.md`, y la fila de las rutas en su sección 6).

Las correcciones de la réplica tienen nombre propio y cada una cita su hallazgo en la cabecera: `E1_rutas_segmentos_config.sql`
corresponde a H2, `E2_unique_timbradas_segmentos.sql` a H3 y `H1_armonizar_estacionalidades.sql` a H1.

| # | Hallazgo | Severidad | Corrección en la réplica | Evidencia |
|---|---|---|---|---|
| H1 | `estacionalidades_anio` pertenece a otro proceso | Bloquea la liquidación | `replica/errata/H1_armonizar_estacionalidades.sql` | `docs/evidencias/replica/replica_errata.txt` |
| H2 | El script 1 no corre tal cual | Bloquea 6 tablas | `replica/errata/E1_rutas_segmentos_config.sql` | `replica_errata.txt` (E1: 6 errores sin la corrección, 1 con ella), `replica_carga.txt` (con E1, `rutas_segmentos_config` y `rutas_segmentos` cargan 22 y 2.695 filas) |
| H3 | Llave de `timbradas_segmentos` contradictoria | Pierde datos | `replica/errata/E2_unique_timbradas_segmentos.sql` | `replica_errata.txt` |
| H4 | Scripts 5, 6 y 99 filtran `cootransoriente` | No procesan nada | Ninguna (se ejecutan igual) | `replica_carga.txt` (scripts 99, 5 y 6 tal cual: las mismas filas antes y después) |
| H5 | Objetos que los scripts suponen y no se entregaron | Réplica inferida | DDL deducido del código | `replica_objetos.txt` |
| H6 | Viajes «aptos» sin fecha de fin: FALSE sin aviso | 7,8 % de viajes sin liquidar | Ninguna | `replica_llegada.json` y este documento |
| H7 | El cierre resella todo y sus promedios no coinciden con la exportación | Marca de agua inútil sola | Huella de contenido en la API | `replica_llegada.json` |
| H8 | Marcas sin zona y con la hora de inicio de la transacción | Lectura incremental puede perder filas | Solape + `SET LOCAL TimeZone` | `tests/replica/test_llegada.py` |
| H9 | `timbradas_segmentos.pasajeros` no es ocupación | Medida no interpretable | Se reporta tal cual | este documento |
| H10 | El trigger asigna el bloque por fila; el histórico, por fin de viaje | Semántica distinta | Se compara por sumas | `replica_llegada.json` |
| H11 | No se entregó quién llama la liquidación y el cierre | Orden supuesto | El simulador los llama en orden | — |
| H12 | Rendimiento: trigger, marcas sin índice, FK sin índice | Costo crece con el histórico | Propuesta de índices | `explain_incremental.txt` |
| H13 | Ciclo, flota e intervalo programado no cuadran; el plan D5 admite 35 salidas por hora (1,71 min) frente al mínimo gobernado de 2 min | Cambia la viabilidad de la recomendación | Se reporta: horas «no viables» con su motivo | `docs/evidencias/respuesta/respuesta_reto.md` |
| H14 | La «espera máxima» de §5.1 (5 min) admite dos lecturas: intervalo entre despachos o espera media del pasajero | Cambia el headway máximo: 5 o 10 min | Supuesto S12: headway máximo efectivo = min(`headway_maximo_min`, 2 × `espera_max_min`) | `tests/unit/test_respuesta.py::test_espera_maxima_acota_el_headway_maximo_d1` |
| H15 | No hay un criterio escrito de cómo fija hoy Sobusa la frecuencia; la línea base B1 lo formaliza como el promedio de las ocho semanas anteriores | Cambia la línea base contra la que se mide el modelo | Supuesto S0 | `docs/evidencias/modelo/evaluacion_modelo.md` (B1) |
| H16 | §19 escribe «Silencio (14/15)», pero en la tabla `rutas` exportada SILENCIO es la ruta 2 con código 2, y el código 15 es de CL 72 | Identificación de la ruta | Se toman las rutas por su nombre | `datos/catalogo_rutas.json` |

## H1. `estacionalidades_anio` es de otro proceso y `"Procesos"` de Sobusa no tiene estacionalidad

**Qué pasa.** Las 231 filas de `estacionalidades_anio` tienen `proceso = 'cootransoriente'`, y la fila de Sobusa en
`"Procesos"` tiene `id_estacionalidad` y `ultima_estacionalidad` en NULL. `fn_insert_timbradas_anio` busca la
estacionalidad con `ea.proceso = v_progvehiculos.proceso` y, si no la encuentra, termina con `RETURN FALSE`.

**Evidencia.** Sobre 10 viajes reservados aptos, en transacciones que se deshacen: TRUE en 0 de 10 sin la armonización y
en 8 de 10 con ella (`replica_errata.txt`, sección H1). Los 2 FALSE restantes son H6.

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

**Pregunta.** ¿Con qué parámetros se ejecutaron los cargues iniciales para Sobusa? ¿Hay una versión de los scripts 5 y 6
para `sobusa`?

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

**Pregunta.** ¿`pasajeros` debe ser la ocupación a bordo? Si es así, ¿la resta debe hacerse contra los acumulados al
inicio del viaje (`progvehiculos.acumulada_subida/_bajada`)?

## H10. Bloque horario por fila en el trigger y por fin de viaje en el histórico

**Qué pasa.** El trigger asigna `hora_inicio` según la hora de cada fila cruda (8 a 16 bloques de 15 minutos por viaje);
el cargue inicial del script 5 usa un solo bloque, el del fin del viaje, y `fn_insert_timbradas_anio` (paso 13) también
asigna todos los segmentos al bloque de fin. Por eso la equivalencia con la exportación se verifica por sumas por
(segmento, viaje), no por bloque.

**Pregunta.** ¿Cuál es el bloque oficial de un segmento: la hora en que el bus pasa por él o la hora de fin del viaje?

## H11. Quién llama la liquidación y el cierre

**Qué pasa.** No se entregó el proceso que llama `fn_insert_timbradas_anio` (por viaje terminado) ni
`fn_consolidar_timbradas_historicas` (cierre). El simulador (`scripts/replica_simular_llegada.py`) los llama en ese orden:
llegada → liquidación por viaje → cierre.

**Pregunta.** ¿Con qué periodicidad y en qué orden se ejecutan en producción, y desde dónde (cron, aplicación, pg_cron)?

## H12. Rendimiento de los objetos de Extreme

**Evidencia** (`docs/evidencias/replica/explain_incremental.txt`): ninguna tabla `timbradas_*` tiene índice por su
marca, así que cada lectura incremental recorre la tabla entera aunque no haya llegado nada (239 ms hoy en
`timbradas_segmentos`, con 2,77 M filas; con el histórico completo serían unos 58 M). La llave foránea
`timbradas_segmentos.id_viaje` no tiene índice. El trigger tarda unos 50 ms por fila cruda (36-81 ms según la carga).
`fn_segmentar_ruta` con porciones de 0,2 m pasó de 10 minutos en una sola ruta sin terminar (prototipo) y borra los
segmentos de su configuración, así que no se puede volver a segmentar con datos cargados (la llave foránea lo impide).

**Pregunta.** ¿Pueden aplicar la propuesta `docs/evidencias/replica/propuesta_indices.sql` (todos `CREATE INDEX
CONCURRENTLY`, ninguno cambia tablas, triggers ni funciones) o indicar qué índices existen ya en producción
(`SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = 'public'`)?

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

**Pregunta.** ¿Con qué regla fija hoy Sobusa el número de salidas por ruta y hora? ¿Es el promedio de las ocho semanas
anteriores para la misma ruta, día y hora, otro número de semanas u otro criterio? ¿Hay un registro del horario
programado de cada semana para compararlo con B1?

## H16. «Silencio (14/15)» en §19

**Qué pasa.** §19 lista las rutas «KRA 54, Silencio (14/15) y Calle 72». En la tabla `rutas` exportada
(`datos/catalogo_rutas.json`), SILENCIO es la ruta con `idruta` 2 y código 2, CRA 54 tiene `idruta` 16 y código 10, y
CL 72 tiene `idruta` 21 y código 15. Ninguna tiene el código 14, y el 15 es de CL 72, no de SILENCIO. La API toma las
tres rutas por su nombre.

**Pregunta.** ¿Qué significa «(14/15)» junto a Silencio? ¿Son códigos de otra tabla, de las dos variantes o sentidos de
la ruta, o de rutas que no se exportaron? Si SILENCIO tiene variantes, ¿cuáles hay que incluir en el reto?
