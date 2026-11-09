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
`escritor_ia` (la 0006 y la 0007 también son aditivas y solo tocan `ai_frecuencias`: columnas de dimensiones,
restricciones y la tabla `respuesta_reto` la 0006, y una versión nueva de `threshold_config` con los umbrales de la
ALT-002 observada y de la ruptura de RF-009 la 0007), la ejecución terminó `ok`, `lector_ia` solo corrió `SELECT`/`WITH`, `SET` y `SHOW` en transacciones terminadas en
`ROLLBACK` (según `pg_stat_statements`) y la réplica quedó intacta (mismo contenedor, inicio y volumen).

Sin contenedores, el mismo modo con el venv: `DATABASE_URL=postgresql+psycopg://escritor_ia:…@localhost:5434/operacional`,
`FUENTE=postgres`, `FUENTE_DATABASE_URL=postgresql+psycopg://lector_ia:…@localhost:5434/operacional`,
`FUENTE_TABLA=demanda_segmentos`, `FUENTE_SOLAPE_MIN=15`, y `alembic upgrade head` (claves solo en el `.env` local).
`scripts/replica_simular_llegada.py --ciclo-api` lo hace todo en un proceso con datos y modelos en una copia temporal.

**Alembic como escritor_ia.** PostgreSQL revisa el permiso `CREATE` de la base antes de mirar el `IF NOT EXISTS` de
`CREATE SCHEMA`, y escritor_ia no lo tiene (42501). `alembic/env.py` y la migración `0001` solo crean el esquema si
`pg_namespace` no lo tiene; con eso `alembic upgrade head` aplica todas las migraciones, de la 0001 a la 0007, como
escritor_ia. La prueba `tests/replica/test_integrado.py::test_alembic_upgrade_head_como_escritor_ia` lo repite en cada
corrida. La corrida registrada en `docs/evidencias/replica/replica_llegada.txt` y `.json` (`ciclo_api.preparacion`) es
anterior a la 0007: aplicó las 6 migraciones que había entonces (0001 a 0006) como escritor_ia en 2,23 s.

**Planificador en el modo integrado (§7.3, paso 2).** En `docker-compose.integracion.yml` el planificador queda
encendido por omisión (`PLANIFICADOR_HABILITADO_INTEGRADO=true`): la ejecución diaria lee la réplica con `lector_ia` sin
que nadie haga un POST. Que una franja programada procese solo lo nuevo o modificado y actualice predicciones,
recomendaciones y alertas está probado con la fuente Parquet y el PostgreSQL local en
`docs/evidencias/cola/planificador_programado.txt`
(`PRUEBA_PLANIFICADOR=1 pytest tests/integracion/test_planificador_programado.py`); la lectura incremental contra la
réplica, con la llegada real por el trigger, está en `docs/evidencias/replica/replica_llegada.txt`. La base de resultados del servicio
`db` de Compose arranca con `pg_stat_statements` precargada y `track_io_timing` encendido
(`docs/evidencias/despliegue/pg_stat_statements_db.txt`).

## 2. Mapa de tablas: §8.2 frente a la base del reto y la réplica

| Tabla (§8.2) | Base del reto | Réplica local | Uso en la API |
|---|---|---|---|
| `procesos` | `"Procesos"` (comillas y mayúscula) | 1 fila | Contexto; `FuentePostgresSoloLectura.procesos()` lee solo columnas operativas (no las credenciales de interfaces que tiene la tabla, §18). |
| `rutas` | 3 rutas (2 SILENCIO, 16 CRA 54, 21 CL 72) | 3 | Catálogo y `frecuenciadespachos`; nombre de ruta de la demanda. |
| `estacionalidades`, `estacionalidades_anio` | 24 y 231 (proceso `cootransoriente`, H1) | 24 y 231 (armonizadas a `sobusa` solo en la réplica) | Estacionalidad de cada fecha en la capa de segmentos y contexto del modelo. |
| `timbradas_anio` | 30.913 | 30.913 | Lectura incremental por `ultima_actualizacion`. |
| `timbradas_anio_zonas`, `timbradas_consolidado_zonas` | Vacías para Sobusa (H5) | 0 | `/api/v1/segmentos/zonas` explica por qué no hay filas. |
| `timbradas_consolidado` | 10.731 | 10.731 | Lectura incremental con huella (se resella entero cada noche, H7). |
| `novedades_viales`, `_fecha`, `_ruta` | 59, 28, 0 | 59, 28, 0 | Variables de impacto del modelo (`scripts/replica_contexto.py`). |
| `conteo_pasajero` | `conteo_pasajeros_destino`, 176 M filas | `conteo_pasajeros` (25 columnas), vacía con el trigger activo | La llena el simulador de llegada como lo haría la captura. |
| `progvehiculos` | 564.837 | 564.837 | Hora de salida y ruta de cada viaje (franja de la demanda). |
| `rutas_segmentos_porcion`, `_config`, `rutas_segmentos` | 6,7 M, 22, 2.695 | 0, 22, 2.695 | Segmentos de la capa analítica. |
| `timbradas_segmentos` | 2.795.607 | 2.769.692 (sin los 265 viajes reservados) | **Fuente del ciclo integrado** (`demanda_segmentos`) y de `/api/v1/segmentos/estadisticas`. Marca `ultimaactualizacion`. |
| `timbradas_segmentos_anio`, `_consolidado` | No exportadas | Las llenan las funciones al liquidar | Lectura incremental (lista blanca). |
| `timbradas_segmentos_anio_trazabilidad` | No exportada | La crea el script 1 (`replica/extreme/1. tablas.sql`) y está vacía al cargar (`docs/evidencias/replica/replica_objetos.txt`); la escribe la liquidación | No se lee: es la trazabilidad interna de la liquidación de Extreme. |
| `ai_frecuencias.*` | — | Las tablas de resultados de escritor_ia, entre ellas `respuesta_reto` desde la migración 0006 | Resultados de la IA (Alembic). |

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
(`docs/evidencias/datos/definicion_pasajeros.md`). La ubicación de una alerta (§5.3) se toma del inicio del segmento 1
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
*circuit breaker* (RNF-010). Las consultas de contexto (`CONSULTAS_CONTEXTO`) nombran columnas explícitas.

## 4. Marca de agua exacta: solape y huella de contenido (RF-013, §8.3, §9.5, §11.2)

1. La ejecución toma la última marca **exitosa** (`execution_log.marca_agua_nueva`) y el estado de huellas que guardó esa
   misma ejecución (`metricas.fuente_estado`), confirmado en la MISMA transacción que sus resultados (`cola.cerrar_ok`).
2. Lee `marca > marca_anterior − FUENTE_SOLAPE_MIN` (15 min). La ventana existe porque `NOW()` es la hora de **inicio**
   de la transacción de la captura: una transacción que empieza antes de la lectura y confirma después queda con una
   marca anterior a la ya leída y, sin solape, se perdería (H8; prueba `test_solape_recupera_la_captura_que_confirma_tarde…`).
3. Deduplica por llave natural (`LLAVES`) y calcula la huella (md5 de los valores sin la marca) de cada fila. Una fila cuya
   llave y huella ya se entregaron se descarta (`repetidas_solape`); una llave nueva con marca anterior es **tardía**; una
   llave conocida con otra huella es **modificada**. Así una fila tardía o modificada se entrega exactamente una vez y un
   resellado sin cambios no se reprocesa (H7).
4. La nueva marca es la mayor leída; el estado guarda las huellas de las filas dentro de la ventana de la nueva marca.
5. `metricas.lectura` de cada ejecución deja `leidas`, `entregadas`, `nuevas`, `tardias`, `modificadas` y
   `repetidas_solape`; `filas_leidas` es lo entregado a calidad e inferencia.

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
candado de la base (`pg_advisory_lock`) para no chocar con otras suites y restauran lo que insertan.

## 6. Rendimiento en la réplica (§14.1 «Rendimiento: SQL EXPLAIN y prueba de volumen»)

`scripts/replica_explain.py` explica, como lector_ia y en la misma sesión de la API, el SQL **exacto** que compila la
fuente para cada tabla, antes y después de aplicar (como extreme_dba, el dueño, §8.3) la propuesta
`docs/evidencias/replica/propuesta_indices.sql`, y luego la borra. Resultados en `docs/evidencias/replica/explain_incremental.txt`
y `.json` (ms de ejecución en el servidor; los tiempos varían con la carga del equipo):

| Consulta | Escenario B: ejecución sin novedades (antes → después) | Escenario A: bloque grande de llegada (antes → después) |
|---|---|---|
| `timbradas_segmentos` por marca | 239 ms Seq Scan → 0,01 ms Index Scan | 500.000 filas: 454 → 245 ms |
| `demanda_segmentos` (ciclo) | 269 ms → 0,07 ms | 1.262 franjas: 5,26 → 5,03 s |
| `timbradas_consolidado` | 1,6 → 0,01 ms | 10.731 filas: 6,1 → 4,3 ms |
| `timbradas_anio` | 4,9 → 0,01 ms | 22.542 filas: 17,0 → 4,8 ms |
| Estadísticas de segmento (ruta 2, todo el período) | 5,5 s (agregación completa; los índices no la cambian) | — |

**Argumento de volumen.** La réplica tiene 2.769.692 filas de `timbradas_segmentos` (536 MB) para 26.780 viajes
(103,4 filas por viaje, 56 días). Con los 564.837 viajes de 2023-2025 segmentados, la tabla tendría unos 58,4 millones
de filas; una ejecución diaria lee unas 49.459 (fracción 0,00085). Sin índice en la marca, **cada** ejecución programada
recorre la tabla entera aunque no haya llegado nada (escenario B: 239 ms hoy, unas 20 veces más con el histórico
completo); con el índice el costo depende solo de lo que llegó. En el escenario A el bloque no es selectivo (la carga se
selló en pocas transacciones y el bloque es medio histórico), por eso el índice casi no cambia la lectura compuesta.
La estadística por segmento es analítica y pesada por naturaleza: se pagina y se pide por ruta y rango de fechas; la
mejora natural es materializarla en `ai_frecuencias` por la noche (pendiente).

Otros datos medidos: el trigger de Extreme tarda unos 50 ms por fila cruda (36-81 ms según la carga) y
`fn_consolidar_timbradas_historicas` 0,35 s.

## 7. Capa analítica de segmentos y zonas (§6.1, §6.2, §11.2)

`app/servicios/segmentos.py` deriva, en solo lectura y sin tocar funciones ni scripts, los promedios, máximos y mínimos de
subidas, bajadas y pasajeros por segmento, estacionalidad (la vigente en la fecha, con el desempate de
`fn_insert_timbradas_anio`), día ISO y hora del bloque, a partir de `timbradas_segmentos` (unidad: viaje × segmento × hora).
Endpoints (X-API-Key, rol operador o superior, paginación `limite`/`desplazamiento`, orden con lista blanca):

- `GET /api/v1/segmentos/estadisticas` y `/estadisticas/export?formato=csv|xlsx`;
- `GET /api/v1/segmentos/zonas?nivel=anio|consolidado`: demanda por zona tarifaria; para Sobusa responde 0 filas y explica
  que ninguna ruta maneja zonas (H5).

Sin base operacional configurada (modo offline) los tres responden 200 con `"disponible": false` y la razón; una caída o
un *timeout* de la base responde 503. Los identificadores se validan contra el rango de INTEGER/BIGINT (422).

Pruebas: `tests/replica/test_segmentos.py` (mín ≤ promedio ≤ máx; Σ igual a un SQL directo; día ISO; estacionalidad;
401 sin clave, 200 con clave, 422 con día 9, CSV con el mismo total).

## 8. Contexto operacional desde la base

`scripts/replica_contexto.py` lee `novedades_viales_fecha`, `novedades_viales_ruta`, `estacionalidades_anio` y
`estacionalidades` con lector_ia y aplica la misma función de `scripts/preparar_datos_api.py`: el resultado es idéntico al
`datos/contexto_operacional.parquet` empaquetado (24.837 de 24.837 filas; 246 horas con novedad;
`docs/evidencias/replica/replica_contexto.json`). Las variables fv2 del modelo pueden venir de la base sin cambiar nada.

## 9. Lo que falta para la base real

- Que Extreme cree `lector_ia` y `escritor_ia` (o equivalentes) con los permisos de `replica/initdb/30_roles.sh` y el
  esquema `ai_frecuencias` con dueño escritor_ia.
- Que el DBA revise y aplique la propuesta de índices (CONCURRENTLY, no bloquea la captura).
- Las respuestas a las preguntas de `hallazgos_extreme.md`.
