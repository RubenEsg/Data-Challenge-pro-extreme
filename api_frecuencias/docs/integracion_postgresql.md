# Integración con PostgreSQL (E07)

Cómo lee la API los datos de Extreme sin interferir con la operación, dónde guarda sus resultados, cómo se comprobó
contra una réplica fiel de la base operacional y qué rendimiento tiene cada consulta. Referencias: especificación v1.5,
§6, §7.3, §8, §11, §14.1 y §18 (`documentos/especificacion_tecnica_reto_frecuencias_v1.5.md`). Los hallazgos sobre los
scripts y los datos de Extreme, con la pregunta exacta para cada uno, están en [`hallazgos_extreme.md`](hallazgos_extreme.md).

## 1. Arquitectura: una base operacional, dos usuarios técnicos

```
            captura de Extreme (extreme_dba)
                       │ INSERT conteo_pasajeros
                       ▼
   tg_timbrada_segmento ──► timbradas_segmentos (ultimaactualizacion = NOW())
   fn_insert_timbradas_anio (liquidación) ──► timbradas_anio, timbradas_segmentos_anio, trazabilidad
   fn_consolidar_timbradas_historicas (cierre) ──► timbradas_consolidado, timbradas_segmentos_consolidado
                       │
          ┌────────────┴─────────────┐  misma base «operacional»
          │ lector_ia: solo SELECT,   │  default_transaction_read_only=on, statement_timeout=30s,
          │ READ ONLY + timeout       │  idle_in_transaction_session_timeout=1min, lock_timeout=5s
          └────────────┬─────────────┘
                       ▼
        API (FastAPI): lectura incremental → calidad → histórico → modelo → optimizador → alertas
                       │
          ┌────────────┴─────────────┐
          │ escritor_ia: dueño SOLO   │  sin permisos sobre public, sin CREATE en la base
          │ del esquema ai_frecuencias│  (Alembic deja allí también alembic_version)
          └──────────────────────────┘
```

Una excepción declarada: `escritor_ia` tiene el permiso `TEMPORARY` en la base operacional
(`replica/initdb/30_roles.sh`), porque la ingesta usa una tabla temporal de paso (`COPY` + `INSERT … ON CONFLICT`). Una
tabla temporal vive solo en la sesión, en el esquema temporal de esa sesión, y no toca `public` ni los objetos de
Extreme. Si el DBA prefiere no darlo, el paso intermedio puede ir en una tabla `UNLOGGED` dentro de `ai_frecuencias`.

| Modo | Lectura (`FUENTE`, `FUENTE_DATABASE_URL`) | Resultados (`DATABASE_URL`) | Para qué |
|---|---|---|---|
| **Offline** (por omisión) | `parquet`: exportaciones de `datos/` | PostgreSQL propio (`db`, puerto 5433) | Demostración reproducible sin red |
| **Integrado** (`docker-compose.integracion.yml`) | `postgres` + `lector_ia@operacional` | `escritor_ia@operacional`, esquema `ai_frecuencias` | Lo que correría en Extreme: §8.1 y §11.3 |

La **réplica local** (`docker-compose.yml`, servicio `operacional`, perfil `integracion`, proyecto `sobusa_rep`, puerto
5434) es PostgreSQL 14 + PostGIS con las tablas existentes cargadas desde las exportaciones (3.379.899 filas) y los 8
scripts de Extreme copiados byte a byte (`replica/extreme`, `SHA256SUMS`); las correcciones mínimas para que corran van
en archivos aparte (`replica/errata`: E1, E2 y la armonización H1), cada una con una prueba que muestra el fallo sin
ella (`docs/evidencias/replica/replica_errata.txt`). Los roles los crea `replica/initdb/30_roles.sh`.

### Levantar el modo integrado

```bash
# 1) réplica (una vez) y su carga
docker compose -p sobusa_rep --profile integracion up -d operacional
.venv\Scripts\python -m scripts.replica_cargar
# 2) API integrada en el MISMO proyecto compose (comparte red y servicio «operacional»); puerto 8302.
#    --no-deps: no recrea ni reinicia el contenedor «operacional» ni su volumen (docs/despliegue.md, sección 3.3)
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion build api
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion run --rm --no-deps migrar
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion up -d --no-deps api
```

`python scripts/verificar_despliegue.py --modo-integrado` repite estos pasos y deja el resultado en
`docs/evidencias/despliegue/modo_integrado.txt`: en esa corrida, `migrar` aplicó la migración aditiva 0004 → 0005 como
`escritor_ia` (de la 0006 a la 0014 también son aditivas y solo tocan `ai_frecuencias`: columnas de dimensiones,
restricciones y la tabla `respuesta_reto` la 0006; una versión nueva de `threshold_config` con los umbrales de la
ALT-002 observada y de la ruptura de RF-009 la 0007; las tres tablas de la agregación de segmentos y el tipo de
trabajo `segmentos` la 0008; las columnas de partición de `execution_log` y la tabla `marca_agua_ruta` la 0009; una
versión nueva de `threshold_config` con los parámetros del plan y dos columnas de `recommendation` la 0010; la tabla
`ocupacion_segmento` la 0011; el tipo de trabajo `retencion`, la tabla `retencion_registro`, la columna
`huellas_solape` de `segmento_estadistica_refresco` y una versión nueva de `threshold_config` con los parámetros de la
retención la 0012; cuatro columnas de `demanda_observada` (las bajadas y las medidas de los segmentos), la tabla
`marca_agua_tabla` y una versión nueva de `threshold_config` con las tolerancias del contraste de los consolidados la
0013; y otra versión de `threshold_config` con el mínimo de probabilidad de ALT-003 la 0014), la ejecución terminó
`ok`, `lector_ia` solo corrió `SELECT`/`WITH`, `SET` y `SHOW` en transacciones terminadas en `ROLLBACK` (según
`pg_stat_statements`) y la réplica quedó intacta (mismo contenedor, inicio y volumen).

Sin contenedores, el mismo modo con el venv: `DATABASE_URL=postgresql+psycopg://escritor_ia:…@localhost:5434/operacional`,
`FUENTE=postgres`, `FUENTE_DATABASE_URL=postgresql+psycopg://lector_ia:…@localhost:5434/operacional`,
`FUENTE_TABLA=demanda_segmentos`, `FUENTE_SOLAPE_MIN=15`, y `alembic upgrade head` (claves solo en el `.env` local).
`scripts/replica_simular_llegada.py --ciclo-api` lo hace todo en un proceso con datos y modelos en una copia temporal.

**Alembic como escritor_ia.** PostgreSQL revisa el permiso `CREATE` de la base antes de mirar el `IF NOT EXISTS` de
`CREATE SCHEMA`, y escritor_ia no lo tiene (42501). `alembic/env.py` y la migración `0001` solo crean el esquema si
`pg_namespace` no lo tiene; con eso `alembic upgrade head` aplica la cadena de migraciones como escritor_ia. La prueba
`tests/replica/test_integrado.py::test_alembic_upgrade_head_como_escritor_ia` lo repite en cada corrida de
`tests/replica`. Falta registrar en un archivo de evidencia su corrida con la cadena hasta la 0014.
La corrida registrada en `docs/evidencias/replica/replica_llegada.txt` y `.json` (`ciclo_api.preparacion`) es
anterior a la 0007: aplicó las 6 migraciones que había entonces (0001 a 0006) como escritor_ia en 2,23 s.

**Planificador en el modo integrado (§7.3, paso 2).** En `docker-compose.integracion.yml` el planificador queda
encendido por omisión (`PLANIFICADOR_HABILITADO_INTEGRADO=true`): la ejecución diaria lee la réplica con `lector_ia` sin
que nadie haga un POST. Que una franja programada procese solo lo nuevo o modificado y actualice predicciones,
recomendaciones y alertas está probado con la fuente Parquet y el PostgreSQL local en
`docs/evidencias/cola/planificador_programado.txt`
(`PRUEBA_PLANIFICADOR=1 pytest tests/integracion/test_planificador_programado.py`); la lectura incremental contra la
réplica, con la llegada real por el trigger, está en `docs/evidencias/replica/replica_llegada.txt`. La base de resultados del servicio
`db` de Compose arranca con `pg_stat_statements` precargada y `track_io_timing` encendido
(`docs/evidencias/despliegue/pg_stat_statements_db.txt`). Con `FUENTE_DATABASE_URL` definida, el planificador también
encola el refresco de la agregación de segmentos (`PLAN_SEGMENTOS_CRON`, sección 7), y con `PLAN_PARTICION=ruta` la
ejecución diaria se parte en un trabajo por ruta (sección 4). Encola además la retención de datos
(`PLAN_RETENCION_CRON`), que solo borra en `ai_frecuencias` (sección 5). Con la misma URL, cada ejecución lee al
cerrar los consolidados de Extreme (sección 4).

## 2. Mapa de tablas: §8.2 frente a la base del reto y la réplica

| Tabla (§8.2) | Base del reto | Réplica local | Uso en la API |
|---|---|---|---|
| `procesos` | `"Procesos"` (comillas y mayúscula) | 1 fila | Contexto; `FuentePostgresSoloLectura.procesos()` lee solo columnas operativas (no las credenciales de interfaces que tiene la tabla, §18). |
| `rutas` | 3 rutas (2 SILENCIO, 16 CRA 54, 21 CL 72) | 3 | Catálogo y `frecuenciadespachos`, que es el headway vigente de §6.2 (`frecuenciadespachos_min`, leído en minutos: supuesto S14, H15); nombre de ruta de la demanda. |
| `estacionalidades`, `estacionalidades_anio` | 24 y 231 (proceso `cootransoriente`, H1) | 24 y 231 (armonizadas a `sobusa` solo en la réplica) | Estacionalidad de cada fecha en la capa de segmentos, en la ocupación por segmento y en el contexto del modelo. En los consolidados, los días de cada estacionalidad (VAL-007 y el contraste; H17). |
| `timbradas_anio` | 30.913 | 30.913 | Lectura incremental por `ultima_actualizacion`. |
| `timbradas_anio_zonas`, `timbradas_consolidado_zonas` | Vacías para Sobusa (H5) | 0 | `/api/v1/segmentos/zonas` explica por qué no hay filas. |
| `timbradas_consolidado` | 10.731 | 10.731 | Lectura incremental con huella (se resella entero cada noche, H7). El paso de consolidados del ciclo la lee con su marca por tabla (`marca_agua_tabla`), la valida y la contrasta con el histórico propio (CONTR-001; sección 4, H17). |
| `novedades_viales`, `_fecha`, `_ruta` | 59, 28, 0 | 59, 28, 0 | Variables de impacto del modelo (`scripts/replica_contexto.py`), por fecha, rango horario y ruta (`app/servicios/novedades.py`): con `_ruta` vacía, cada novedad es de todas las rutas (sección 8). |
| `conteo_pasajero` | `conteo_pasajeros_destino`, 176 M filas | `conteo_pasajeros` (25 columnas), vacía con el trigger activo | La llena el simulador de llegada como lo haría la captura. |
| `progvehiculos` | 564.837 | 564.837 | Hora de salida y ruta de cada viaje (franja de la demanda); en la ocupación por segmento, además el vehículo y el conductor, que se seudonimiza al leer (sección 4). Las bajadas de los viajes válidos (`numerobajadas`) van al histórico desde la migración 0013, y los viajes de una ruta y un día dan el viaje, el vehículo y el conductor de ALT-006 y ALT-009 (`FuentePostgresSoloLectura.viajes`, §5.3; sección 4). |
| `rutas_segmentos_porcion`, `_config`, `rutas_segmentos` | 6,7 M, 22, 2.695 | 0, 22, 2.695 | Segmentos de la capa analítica. |
| `timbradas_segmentos` | 2.795.607 | 2.769.692 (sin los 265 viajes reservados) | **Fuente del ciclo integrado** (`demanda_segmentos`, también por ruta) y del trabajo `segmentos`, que mantiene en `ai_frecuencias` la agregación de `/api/v1/segmentos/estadisticas` (lectura por tramos de fechas con `lector_ia`). Sus subidas y bajadas por viaje dan la ocupación actual por segmento del ciclo (§10.1, sección 4). Marca `ultimaactualizacion`. |
| `timbradas_segmentos_anio`, `_consolidado` | No exportadas | Las llenan las funciones al liquidar; sin filas de Sobusa (H4) | El paso de consolidados del ciclo las lee con su marca por tabla y las contrasta con la agregación de segmentos por segmento × (año) × día ISO × estacionalidad (CONTR-002; por hora solo el rango, CONTR-003, que no bloquea: H10); sin filas, lo registra como `sin_filas_fuente`. |
| `timbradas_segmentos_anio_trazabilidad` | No exportada | La crea el script 1 (`replica/extreme/1. tablas.sql`) y está vacía al cargar (`docs/evidencias/replica/replica_objetos.txt`); la escribe la liquidación | No se lee: es la trazabilidad interna de la liquidación de Extreme. |
| `ai_frecuencias.*` | — | Las tablas de resultados de escritor_ia, entre ellas `respuesta_reto` desde la migración 0006, la agregación de segmentos desde la 0008, `marca_agua_ruta` desde la 0009 y `marca_agua_tabla` desde la 0013 | Resultados de la IA (Alembic). |

`FuentePostgresSoloLectura(tabla=…)` admite solo esta lista blanca (`TABLAS_PERMITIDAS` en `app/servicios/fuentes.py`).
Las tablas con marca se leen de forma incremental; los catálogos se leen completos. La lectura compuesta
**`demanda_segmentos`** entrega el contrato de demanda horaria del ciclo (ruta, fecha, hora de salida, pasajeros, salidas,
`ultima_actualizacion`): toma los viajes con timbradas nuevas o modificadas, marca sus franjas (ruta, hora de salida en
`progvehiculos`) y vuelve a agregar **completas** esas franjas (todos sus viajes), para no entregar sumas parciales. La
forma de la consulta importa: la primera versión unía `progvehiculos` por rango de hora y tardaba 35,9 s en la carga
inicial; con igualdad sobre `date_trunc('hour', fechasalida)` (unión hash) tarda 4,6 s sin índices nuevos.

La misma consulta une `rutas`, `"Procesos"` y `estacionalidades_anio` (§11.2): filtra por `FUENTE_PROCESO` y entrega,
para cada franja, el proceso, `idempresa` e `id_estacionalidad` (la vigente en la fecha). Así, en modo integrado, las
dimensiones de §8.3 de las tablas de resultados salen de la base y no del catálogo empaquetado. Los pasajeros se
definen igual que el objetivo del modelo y el histórico empaquetado: Σ `numeropasajeros` de los viajes válidos que
salen en esa hora; la Σ de subidas de `timbradas_segmentos` queda aparte, en la columna `subidas`
(`docs/evidencias/datos/definicion_pasajeros.md`). Las bajadas siguen la misma regla: `bajadas_viajes` = Σ
`numerobajadas` de los viajes válidos, y la Σ de bajadas de los segmentos queda en `bajadas`; en los mismos viajes
difieren 0,1 %, y en total, −5,3 % por cobertura (`docs/evidencias/consolidados/definicion_bajadas.md`). Desde la
migración 0013 el histórico propio guarda las cuatro medidas (`bajadas_viajes`, `subidas`, `bajadas` y
`viajes_con_timbradas`). La ubicación de una alerta (§5.3) se toma del inicio del segmento 1
de la ruta en `rutas_segmentos`, también en solo lectura (`FuentePostgresSoloLectura.ubicacion_despacho`).

## 3. Consultas de solo lectura

Toda lectura pasa por `FuentePostgresSoloLectura.consultar` (`app/servicios/fuentes.py`):

```sql
BEGIN;
SET TRANSACTION READ ONLY;
SET LOCAL statement_timeout = 30000;          -- FUENTE_STATEMENT_TIMEOUT_MS, entero validado
SET LOCAL TimeZone = 'America/Bogota';        -- las marcas de Extreme son timestamp SIN zona (H8)
SELECT …;                                     -- una sola sentencia SELECT/WITH de la lista blanca, parámetros enlazados
ROLLBACK;                                     -- nunca COMMIT
```

Antes de abrir la conexión, `validar_solo_select` rechaza cualquier sentencia que no sea un único SELECT (y palabras
como INSERT, UPDATE, COPY, LOCK, FOR UPDATE, SET, nextval o pg_sleep dentro de él). Solo la conexión pasa por el
*circuit breaker* (RNF-010). Las consultas de contexto (`CONSULTAS_CONTEXTO`) nombran columnas explícitas. Todas las
lecturas de la fuente pasan por el mismo circuito `fuente_postgres`: la incremental del ciclo, la de la ocupación por
segmento, la de los viajes de las alertas y la de los consolidados, así que un fallo de conexión de cualquiera cuenta
para abrirlo.

## 4. Marca de agua exacta: solape y huella de contenido (RF-013, §8.3, §9.5, §11.2)

1. Cada trabajo toma, de `ai_frecuencias.marca_agua_ruta` (migración 0009), la marca **exitosa** de cada ruta que lee
   y las huellas de su ventana de solape (`estado_fuente`); una ruta sin marca propia parte de la frontera del proceso
   (la fila `ruta = '*'`). Las dejó el último trabajo que las movió, en la MISMA transacción que sus resultados
   (`cola.cerrar_ok`), y la migración las sembró con la marca global de antes, así que al migrar no se relee nada.
2. Lee `marca > marca_anterior − FUENTE_SOLAPE_MIN` (15 min). La ventana existe porque `NOW()` es la hora de **inicio**
   de la transacción de la captura: una transacción que empieza antes de la lectura y confirma después queda con una
   marca anterior a la ya leída y, sin solape, se perdería (H8; prueba `test_solape_recupera_la_captura_que_confirma_tarde…`).
3. Deduplica por llave natural (`LLAVES`) y calcula la huella (md5 de los valores sin la marca) de cada fila. Una fila cuya
   llave y huella ya se entregaron se descarta (`repetidas_solape`); una llave nueva con marca anterior es **tardía**; una
   llave conocida con otra huella es **modificada**. Así una fila tardía o modificada se entrega exactamente una vez y un
   resellado sin cambios no se reprocesa (H7).
4. La nueva marca de cada ruta es la mayor leída de esa ruta; el estado guarda las huellas de las filas dentro de la
   ventana de la nueva marca. Una marca nunca retrocede.
5. `metricas.lectura` de cada ejecución deja `leidas`, `entregadas`, `nuevas`, `tardias`, `modificadas` y
   `repetidas_solape`; `filas_leidas` es lo entregado a calidad e inferencia. `GET /api/v1/frequency/watermarks`
   muestra la marca de cada proceso y ruta.

**Lectura por ruta (RNF-005).** Un trabajo de una ruta lee con un solo SELECT de la lista blanca, el mismo
`demanda_segmentos` con la variante fija `r.nombre = ANY(CAST(:rutas AS text[]))`, en la misma transacción `READ ONLY`
con `statement_timeout` (`fuentes.leer_particion`). En la réplica, como `lector_ia`, la lectura de cada ruta es
exactamente la lectura completa filtrada por esa ruta, desde la carga inicial y desde una marca intermedia
(`docs/evidencias/cola/lectura_por_ruta_replica.txt`, `tests/replica/test_particion_ruta.py`). Sin los índices
propuestos (sección 6), el SELECT de una ruta recorre `timbradas_segmentos` igual que el de todas, y en esa medición
tardó lo mismo o más. Madre, trabajos, candados y límites: `docs/particion_por_ruta.md`.

**Ocupación actual por segmento (§10.1).** Para las franjas que acaba de entregar la lectura, en las últimas 24 h de
cada ruta, el ciclo lee viaje por viaje sus subidas y bajadas por segmento con otro SELECT constante de la lista
blanca (`_SQL_CARGA_SEGMENTOS`, `FuentePostgresSoloLectura.leer_carga_segmentos`), en la misma transacción `READ ONLY`
con `statement_timeout`. Une `rutas`, `progvehiculos` (los viajes no cancelados de cada franja), `timbradas_segmentos`
y `rutas_segmentos`; las franjas van como arreglos enlazados y el conductor se seudonimiza al leer. No tiene marca de
agua propia: depende de las franjas entregadas, así que convive con la marca por ruta. El cruce con
`timbradas_segmentos` es por `id_viaje`, que no tiene índice (H12). La prueba
`tests/replica/test_ocupacion_segmentos.py::test_la_lectura_del_ciclo_como_lector_ia_trae_lo_mismo_que_las_exportaciones`
la corre como `lector_ia`; método, rendimiento y límites en `docs/ocupacion_segmentos.md`. El resultado se guarda en
`ai_frecuencias.ocupacion_segmento` (migración 0011).

**Viajes de las alertas (§5.3).** Para el viaje, el vehículo y el conductor de ALT-006 y ALT-009, el ciclo lee los
viajes del día de cada ruta con `FuentePostgresSoloLectura.viajes(ruta, desde, hasta)`: un SELECT constante de la
lista blanca (`sql_viajes_ruta`) con parámetros enlazados, en la misma transacción `READ ONLY` con
`statement_timeout`. La ventana va sobre `date_trunc('hour', fechasalida)` de `progvehiculos` (la expresión del índice
propuesto 3) y, en el ciclo integrado, cuenta las filas de `timbradas_segmentos` de cada viaje por `id_viaje` (índice
propuesto 2). `idconductor` se reemplaza por el HMAC antes de salir de la fuente (`seudonimizar_viajes`). La prueba
`tests/replica/test_alertas_viajes.py::test_viajes_de_la_replica_seudonimizados_y_coherentes_con_demanda_segmentos` la
corre como `lector_ia`; detalle en `docs/alertas_viajes_y_alt003.md`.

**Consolidados de Extreme (§6.1, §6.3, §11.2; migración 0013).** Una vez por ejecución, al cerrar, el ciclo lee
`timbradas_consolidado`, `timbradas_segmentos_anio` y `timbradas_segmentos_consolidado` con la base operacional de la
capa analítica (`FUENTE_DATABASE_URL`; `FuentePostgresSoloLectura.para_tabla`). Cada tabla tiene su propia marca de
agua y sus huellas en `ai_frecuencias.marca_agua_tabla`, por proceso y tabla, con la misma regla de solape y huella de
arriba, así que el resellado nocturno sin cambios no se reprocesa (H7). La marca nueva se guarda en la transacción del
ciclo y nunca retrocede. Lo leído pasa la calidad de §6.3 y se contrasta con la agregación propia (`demanda_observada`
para el consolidado por ruta, `segmento_estadistica_dia` para los de segmentos), con sumas que salen de la fuente en
otro SELECT constante. Las diferencias quedan en `data_quality_error` (CONTR-001 a CONTR-003) y el resumen, en
`metricas.calidad.consolidados`. La prueba
`tests/replica/test_consolidados.py::test_el_paso_del_ciclo_lee_la_replica_y_escribe_solo_en_la_base_local`
corre el mismo paso con la réplica como `lector_ia` y escribe solo en la base local de pruebas; el resultado con los
datos reales está en `docs/evidencias/consolidados/contraste_consolidados.md` y el método, en
`docs/consolidados_ciclo.md`.

**Demostración en la réplica** (`scripts/replica_simular_llegada.py --viajes 3 --liquidar --consolidar --ciclo-api`,
`docs/evidencias/replica/replica_llegada.json`):

| Paso | Resultado |
|---|---|
| Llegada: 584 filas crudas reales de 3 viajes reservados, un INSERT por fila como extreme_dba | 29,3 s (50,2 ms por fila en el trigger); 228 filas nuevas en `timbradas_segmentos` |
| Equivalencia trigger ↔ exportación (Σ por segmento y viaje) | 223 de 223 pares iguales; Σ subidas 201 = 201, Σ bajadas 209 = 209 |
| `fn_insert_timbradas_anio` (3 viajes) | TRUE en 3 de 3 (0,2 s cada uno): 2 filas de `timbradas_anio`, 162 de `timbradas_segmentos_anio` |
| `fn_consolidar_timbradas_historicas()` | TRUE en 0,35 s; resella 10.731 de 10.731 filas, 7.952 con otro contenido y 2.779 iguales |
| Lector con huella sobre el resellado | lee 10.731, entrega 7.952 (modificadas) y descarta 2.779 repetidas |
| Ejecución 1 de la API (carga inicial, marca de 1970) | 2.757 franjas leídas y validadas, 9 predicciones, 9 recomendaciones, 9,45 s |
| Ejecución 2 (después de la llegada) | relee 1.263 en la ventana, **entrega 1** (la franja SILENCIO 2023-02-07 05 h de los 3 viajes) y descarta 1.262 |
| Ejecución 3 (sin datos nuevos) | 0 filas: «Sin datos nuevos desde la marca de agua: no se reprocesa el histórico» |
| Restauración | La réplica vuelve al estado cargado (conteos y marcas iguales a los de antes) |

Las tablas de escritor_ia al terminar están todas en `ai_frecuencias` (16).

## 5. Controles de no interferencia (§11.3), cada uno con su prueba

| Control | Cómo se cumple | Prueba (tests/replica) |
|---|---|---|
| Usuario técnico con SELECT | lector_ia: `GRANT SELECT` en public, nada más | `test_privilegios_efectivos_de_los_usuarios_de_la_ia` (catálogo: SELECT en todas, ningún otro privilegio) |
| Usuario separado que escribe solo en ai_frecuencias | escritor_ia dueño del esquema; sin privilegios en public ni CREATE en la base | `test_escritor_ia_no_puede_escribir_ni_alterar_tablas_de_extreme` (14 tablas × 6 sentencias = 84 casos, todos 42501) |
| READ ONLY con timeout | La fuente abre READ ONLY + statement_timeout + TimeZone; el rol tiene los mismos valores por omisión | `test_la_fuente_de_la_api_es_de_solo_lectura_en_tres_capas` (validador sin conectar → 25006 → 42501); `test_roles.py` |
| Ningún DDL sobre el esquema operacional | Ni lector_ia ni escritor_ia pueden ALTER, CREATE INDEX, DROP o LOCK en public; Alembic solo toca ai_frecuencias | `test_escritor_ia_no_puede…`, `test_alembic_upgrade_head_como_escritor_ia` (0 objetos fuera de ai_frecuencias, sin `public.alembic_version`) |
| No deshabilitar triggers | `ALTER TABLE … DISABLE TRIGGER` y `DROP TRIGGER` fallan para ambos; el trigger sigue `tgenabled = 'O'` | `test_nadie_de_la_ia_puede_deshabilitar_el_trigger_ni_tocar_funciones` |
| No modificar funciones ni scripts; no agregar índices sin autorización | `CREATE OR REPLACE FUNCTION` falla; los índices son una **propuesta** que aplica extreme_dba solo en la réplica y se borran al medir | mismo test; `test_explain.py::test_la_replica_no_conserva_los_indices_propuestos`; `test_scripts_extreme.py` (SHA-256) |
| Consultas pesadas en una réplica | Todo lo medido aquí corre en la réplica local; la base compartida no se usa | `test_explain.py` |

Las pruebas que escriben en la réplica (llegada y ciclo completo) corren con `REPLICA_PRUEBAS_ESCRITURA=1`, toman un
candado de la base (`pg_advisory_lock`) para no chocar con otras suites y restauran lo que insertan. Con la misma
variable corre
`tests/replica/test_ocupacion_segmentos.py::test_un_viaje_que_llega_por_el_trigger_se_mide_en_una_transaccion_revertida`,
que inserta un viaje en `conteo_pasajeros` como extreme_dba dentro de una transacción que se revierte.

La retención de datos (§18, `docs/retencion_datos.md`) borra solo en `ai_frecuencias`: todo su SQL es constante y
nombra solo tablas de ese esquema
(`tests/unit/test_retencion.py::test_todo_el_sql_solo_nombra_tablas_del_esquema_ai_frecuencias`), y la prueba de
integración lo comprueba con tablas centinela del mismo nombre en otro esquema
(`tests/integracion/test_retencion.py::test_aplicada_borra_solo_lo_anterior_al_corte_y_solo_en_ai_frecuencias`).

## 6. Rendimiento en la réplica (§14.1 «Rendimiento: SQL EXPLAIN y prueba de volumen»)

`scripts/replica_explain.py` explica, como lector_ia y en la misma sesión de la API, el SQL **exacto** que compila la
fuente para cada tabla, antes y después de aplicar (como extreme_dba, el dueño, §8.3) la propuesta
`docs/evidencias/replica/propuesta_indices.sql`, y luego la borra. Aplica la propuesta ENTERA (7 índices) y mide con
las estadísticas al día (ANALYZE). Resultados en `docs/evidencias/replica/explain_incremental.txt` y `.json` (ms de
ejecución en el servidor, medición del 13-11-2026; los tiempos varían con la carga del equipo):

| Consulta | Escenario B: ejecución sin novedades (antes → después) | Escenario A: bloque grande de llegada (antes → después) |
|---|---|---|
| `timbradas_segmentos` por marca | 122 ms Seq Scan → 0,01 ms Index Scan | 500.000 filas: 378 → 101 ms |
| `demanda_segmentos` (ciclo) | 165 ms → 0,09 ms | 1.262 franjas: 3,54 → 1,51 s |
| `timbradas_consolidado` | 1,3 → 0,01 ms | 10.731 filas: 5,1 → 2,7 ms |
| `timbradas_anio` | 4,0 → 0,01 ms | 22.542 filas: 15,9 → 5,6 ms |
| Estadísticas de segmento (ruta 2, todo el período), agregación directa | 3,0 s (agregación completa; los índices no la cambian). Desde la migración 0008 ya no corre en la petición (sección 7) | — |

**La propuesta entera no empeora ninguna lectura.** `scripts/replica_indices_candidatos.py` mide cada índice
candidato dentro de una transacción que se revierte y, además, la propuesta ENTERA con ANALYZE en los dos lados
frente a todas las lecturas de la API (`docs/evidencias/replica/indices_candidatos.md`, «La propuesta entera»): el
criterio de «ninguna lectura empeora más de 15 %» se evalúa también ahí. Esa medición encontró un defecto que medir
cada índice por separado no veía. Con la propuesta entera y ANALYZE, la lectura `demanda_segmentos` del bloque grande,
tal como estaba escrita, pasaba de 3,5 a 9,2 s (la fila de referencia del informe): las estadísticas de la expresión
del índice 3 (`date_trunc('hour', fechasalida)`) bajaban la estimación de los viajes y, con el ndistinct por omisión de
un CTE en la unión final con `rutas`, PostgreSQL unía los segmentos con un ciclo anidado que descartaba 88 millones de
filas. El informe mide también la propuesta sin el índice 3: así el plan malo no aparece (3,3 s), pero se pierde lo
que ese índice aporta (los viajes de una ruta quedan en 90 ms en vez de 9, y la lectura sin novedades en 50 ms en vez
de 0,1). Por eso el índice sigue en la propuesta y lo que se corrigió fue la lectura:
`fuentes._SQL_DEMANDA_SEGMENTOS` ya no vuelve a unir `rutas` al final (el nombre y la empresa viajan desde el CTE
`franjas`). Entrega las mismas filas en el mismo orden; sin índices tarda lo mismo (3,6 s) y con la propuesta entera
baja a 1,5 s
(`tests/replica/test_explain.py::test_con_la_propuesta_entera_y_las_estadisticas_al_dia_la_lectura_compuesta_no_empeora`,
con `REPLICA_PRUEBAS_ESCRITURA=1`; `tests/replica/test_integrado.py::test_demanda_segmentos_usa_la_definicion_del_modelo_con_proceso_y_estacionalidad`).

**Argumento de volumen.** La réplica tiene 2.769.692 filas de `timbradas_segmentos` (540 MB) para 26.780 viajes
(103,4 filas por viaje, 56 días). Con los 564.837 viajes de 2023-2025 segmentados, la tabla tendría unos 58,4 millones
de filas; una ejecución diaria lee unas 49.459 (fracción 0,00085). Sin índice en la marca, **cada** ejecución programada
recorre la tabla entera aunque no haya llegado nada (escenario B: 122 ms hoy, unas 20 veces más con el histórico
completo); con el índice el costo depende solo de lo que llegó. En el escenario A el bloque no es selectivo (la carga se
selló en pocas transacciones y el bloque es medio histórico): la búsqueda de lo cambiado apenas mejora, y lo que baja
la lectura compuesta es volver a agregar los viajes tocados por el índice de `id_viaje` en vez de recorrer la tabla.
La estadística por segmento es analítica y pesada por naturaleza: desde la migración 0008 se materializa en
`ai_frecuencias` con un trabajo de la cola y la petición lee lo materializado (sección 7). Cada refresco sigue
recorriendo `timbradas_segmentos`: el incremental busca las fechas cambiadas por `ultimaactualizacion` y relee esas
fechas. La propuesta de índices trae el de `ultimaactualizacion` (y el de `id_viaje`), no uno por `fecha`
(`docs/segmentos_materializados.md`, H12).

Otros datos medidos: el trigger de Extreme tarda unos 50 ms por fila cruda (36-81 ms según la carga) y
`fn_consolidar_timbradas_historicas` 0,35 s.

## 7. Capa analítica de segmentos y zonas (§6.1, §6.2, §11.2)

`app/servicios/segmentos.py` deriva, en solo lectura y sin tocar funciones ni scripts, los promedios, máximos y mínimos de
subidas, bajadas y pasajeros por segmento, estacionalidad (la vigente en la fecha, con el desempate de
`fn_insert_timbradas_anio`), día ISO y hora del bloque, a partir de `timbradas_segmentos` (unidad: viaje × segmento × hora).
Desde la migración 0008 esa agregación no corre dentro de la petición: un trabajo `segmentos` de la cola
(`app/servicios/segmentos_refresco.py`) relee `timbradas_segmentos` con `lector_ia`, por tramos de fechas que caben en
el `statement_timeout`, y la guarda en `ai_frecuencias` (`segmento_estadistica_dia`, `segmento_estadistica` y
`segmento_estadistica_refresco`; `docs/segmentos_materializados.md`). La consulta lee esa agregación con el mismo
resultado que la directa (`docs/evidencias/pruebas/segmentos_equivalencia.json`). Desde la migración 0012 cada
refresco guarda las huellas por fecha de su ventana de solape (`segmento_estadistica_refresco.huellas_solape`), y el
siguiente relee solo las fechas que cambiaron: sin cambios, termina `sin_cambios` sin releer fechas ni escribir nada.
En la réplica, un incremental sin filas nuevas pasa de releer 26 fechas a 0
(`docs/evidencias/pruebas/segmentos_sin_cambios.json`).
Endpoints (X-API-Key, paginación `limite`/`desplazamiento`, orden con lista blanca):

- `GET /api/v1/segmentos/estadisticas` y `/estadisticas/export?formato=csv|xlsx` (rol operador): leen la agregación
  materializada; la respuesta trae `actualizado_en` y `materializacion`. Mientras la agregación se calcula por primera
  vez, la consulta responde 200 con `disponible: false` y el refresco encolado, y la exportación, 503
  `agregacion_pendiente`;
- `POST /api/v1/segmentos/estadisticas/refrescar` (rol analista): encola el refresco y responde 202 con el
  `execution_id` (modos `auto`, `completo`, `incremental` y `rango`). También lo encolan el planificador
  (`PLAN_SEGMENTOS_CRON`) y el ciclo diario cuando trae datos nuevos;
- `GET /api/v1/segmentos/zonas?nivel=anio|consolidado` (rol operador): demanda por zona tarifaria; para Sobusa responde
  0 filas y explica que ninguna ruta maneja zonas (H5).

Sin base operacional configurada (modo offline) y sin agregación guardada, la consulta y las zonas responden 200 con
`"disponible": false` y la razón, la exportación sale vacía con sus columnas y el POST responde 503
`fuente_no_configurada`; una caída o un *timeout* de la base responde 503. Los identificadores se validan contra el
rango de INTEGER/BIGINT (422).

Pruebas: `tests/replica/test_segmentos.py` (mín ≤ promedio ≤ máx; Σ igual a un SQL directo; día ISO; estacionalidad;
la agregación materializada igual a la directa; el refresco sin cambios; 401 sin clave, 200 con clave, 422 con día 9,
CSV con el mismo total) y `tests/integracion/test_segmentos_materializados.py` (casos borde, modos del refresco, cola y
planificador).

## 8. Contexto operacional desde la base

`scripts/replica_contexto.py` lee `novedades_viales_fecha`, `novedades_viales_ruta`, `estacionalidades_anio` y
`estacionalidades` con lector_ia y aplica la misma función de `scripts/preparar_datos_api.py`: el resultado es idéntico al
`datos/contexto_operacional.parquet` empaquetado (24.837 de 24.837 filas; 246 horas con novedad;
`docs/evidencias/replica/replica_contexto.json`). Las variables fv2 del modelo pueden venir de la base sin cambiar nada.

Las novedades se cruzan por fecha, rango horario y ruta (`app/servicios/novedades.py`): una novedad con filas en
`novedades_viales_ruta` afecta solo a esas rutas, y una sin filas, a todas. En la réplica la tabla está vacía y las
28 novedades son de todas las rutas, así que el contexto es el mismo
(`docs/evidencias/replica/novedades_por_ruta_replica.json`,
`tests/replica/test_integrado.py::test_novedades_viales_ruta_vacia_en_la_replica_cada_novedad_es_de_todas_las_rutas`).
Que una novedad sin filas sea de todas las rutas es un supuesto que debe confirmar Extreme (`hallazgos_extreme.md`,
«Otras preguntas para Extreme»). Si la tabla se llena, hay que regenerar el contexto y reentrenar: el ciclo no lo
relee solo.

## 9. Lo que falta para la base real

- Que Extreme cree `lector_ia` y `escritor_ia` (o equivalentes) con los permisos de `replica/initdb/30_roles.sh` y el
  esquema `ai_frecuencias` con dueño escritor_ia.
- Que el DBA revise y aplique la propuesta de índices (CONCURRENTLY, no bloquea la captura). Con ellos, la lectura
  incremental por marca deja de recorrer `timbradas_segmentos` (sección 6). La lectura de una ruta y el refresco de la
  agregación de segmentos buscan lo cambiado con la misma marca, pero no se midieron con los índices, y la relectura
  por fecha del refresco no tiene un índice propuesto. La lectura de la ocupación por segmento cruza por `id_viaje`,
  que tiene un índice en la propuesta y tampoco se midió con él. Tampoco se midieron con sus índices la lectura de los
  viajes de las alertas (propuestos 2 y 3) ni la de los consolidados por `ultima_actualizacion` (los del grupo 4).
- Las respuestas a las preguntas de `hallazgos_extreme.md`, entre ellas la unidad de `rutas.frecuenciadespachos` (H15),
  si se pueden volver a cargar las subidas por segmento posteriores a febrero de 2023 y si las tablas por segmento
  tienen filas de Sobusa en producción (H4), con qué latencia llegan los datos de la captura, de la que depende la
  ocupación actual por segmento (H10, H11), por qué el consolidado cuenta viajes con más de una estacionalidad y las
  bajadas de CL 72 no cuadran (H17), si una novedad sin filas en `novedades_viales_ruta` es de todas las rutas y quién
  recibe el reporte de unicidad de cada lote.
- El contraste por segmento con las filas de Sobusa de Extreme: las tablas por segmento de la réplica no las tienen
  (H4). Hoy está probado con filas sintéticas y con filas reales de la liquidación de tres viajes, dentro de una
  transacción que se revierte (`docs/evidencias/consolidados/segmentos_filas_reales.json`).
