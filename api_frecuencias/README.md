# API de frecuencias · Sobusa

**Backend del reto** (especificación v1.5 de Extreme Technologies): Python 3.11+, FastAPI, PostgreSQL 14 + PostGIS,
SQLAlchemy 2, Alembic y Pydantic 2. Data Challenge Pro Extreme – Sobusa 2026 · Universidad del Norte · Abrahan Basto
Martínez, Rubén Esguerra Fernández y Paula Gómez.

## Qué responde

> Con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos
> pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata? (§20 de la especificación)

Para cada ruta (SILENCIO, CRA 54 y CL 72) y hora, la API entrega:

| Pregunta | Respuesta de la API | Dónde |
|---|---|---|
| ¿Cuántos pasajeros se esperan? | Pronóstico a 30, 60 y 120 minutos con banda P10–P90 calibrada, versión del modelo y explicación | `POST /api/v1/predictions/run`, `GET /api/v1/predictions` |
| ¿Cada cuánto despachar? | Headway y buses por hora con la función objetivo de §10.2 (costo, espera, sobreocupación y desviación), frente a la frecuencia programada | `POST /api/v1/recommendations/calculate`, `GET /api/v1/recommendations/plan` |
| ¿Cuántos vehículos? | Por franja, ⌈ciclo / headway⌉ (§10.3) frente a la flota disponible; para el día, los buses en ruta a la vez con el plan (`vehiculos.requeridos_pico` de `GET /api/v1/respuesta`); si no alcanza, `viable = false` con el motivo | las mismas y `GET /api/v1/respuesta` |
| ¿Qué requiere atención? | Alertas ALT-001 a ALT-010 con severidad, evidencia, umbral, explicación, recomendación y estado | `GET /api/v1/alerts` |
| ¿Por qué? | Fórmula aplicada, límites que mandan, variables influyentes y versiones de datos, modelo y umbrales en cada salida | todas |
| Todo junto, por ruta y día | Cada cuánto despachar por hora, pasajeros esperados, vehículos frente a la flota, flota y recaudo, y alertas que piden atención, con su trazabilidad | `GET /api/v1/respuesta` |

El plan del día completo sale del optimizador D5 del proyecto (MILP con PuLP/CBC), el mismo del laboratorio Dash,
alimentado con el pronóstico horario del modelo activo. El ciclo diario lo calcula para el día siguiente y lo guarda;
`GET /api/v1/recommendations/plan` y `GET /api/v1/respuesta` leen lo guardado (§7.1), y `POST /api/v1/respuesta/calcular`
lo pide para otra fecha. La respuesta completa, con sus cifras, está en `../documentos/respuesta_pregunta_reto.md` y en
`docs/evidencias/respuesta/`.

## Arquitectura

```
                fuente operacional                         base propia (servicio «db»)
   ┌──────────────────────────────────────┐        ┌───────────────────────────────────┐
   │ Parquet local (por omisión)          │        │ PostgreSQL 14 + PostGIS           │
   │   datos/demanda_horaria.parquet      │        │ esquema ai_frecuencias (Alembic)  │
   │ o PostgreSQL de Extreme (FUENTE=     │        │  model_registry · execution_log   │
   │   postgres): READ ONLY + timeout     │        │  demanda_observada · prediction   │
   └──────────────────┬───────────────────┘        │  recommendation · alert ·         │
                      │                            │  alert_history                    │
                      │ lectura incremental        │  data_quality_error · threshold_  │
                      ▼ (marca de agua)            │  config · notification_log        │
   ┌───────────────────────────────────────────┐   └─────────────────▲─────────────────┘
   │ API FastAPI (app/)                        │                     │ SQLAlchemy 2
   │  fuentes → calidad → inferencia →         │─────────────────────┘
   │  optimización → alertas → notificaciones  │
   │  (servicios/ejecucion.py, job de fondo)   │──► /api/v1/... (OpenAPI en /docs)
   └───────────────────────────────────────────┘──► /metrics (Prometheus) · logs JSON
```

El esquema `ai_frecuencias` tiene además `execution_attempt` (cola), `model_monitoring` y `feature_snapshot`
(monitoreo y foto de variables), `respuesta_reto` (foto de la respuesta del reto), `marca_agua_ruta` (marca de agua
por proceso y ruta), la agregación de la capa de segmentos (`segmento_estadistica_dia`, `segmento_estadistica` y
`segmento_estadistica_refresco`), `ocupacion_segmento` (ocupación actual por segmento, §10.1), `retencion_registro`
(bitácora de la retención de datos, §18) y `marca_agua_tabla` (marca de agua de los consolidados de Extreme por
proceso y tabla, §6.1); las migraciones 0001 a 0014 están descritas en `docs/manual_tecnico.md`, sección 8.

| Módulo (`app/servicios/`) | Qué hace |
|---|---|
| `fuentes.py` | `FuenteParquet` (simula la llegada diaria de datos por fecha) y `FuentePostgresSoloLectura` (transacción `READ ONLY`, `statement_timeout`); ambas con `leer_incremental(marca_agua, hasta)`. `leer_particion(fuente, particion, hasta)` lee una ruta o todas, cada una desde su propia marca de agua (RNF-005). `FuentePostgresSoloLectura.leer_carga_segmentos` lee, viaje por viaje, las subidas y bajadas por segmento de las franjas que acaba de entregar esa lectura, con el conductor seudonimizado al leer (§10.1). `FuentePostgresSoloLectura.viajes` lee los viajes de una ruta en una ventana de `progvehiculos` para el viaje, el vehículo y el conductor de ALT-006 y ALT-009, también con el conductor seudonimizado al leer (§5.3, §18). La lectura integrada trae además las bajadas de los viajes válidos (`bajadas_viajes`: la definición de pasajeros aplicada a los descensos). |
| `calidad.py` | `validar_lote`: completitud, validez, unicidad, consistencia, oportunidad y relacional (§6.3); cada error con lote, fila, campo, código y detalle. También valida los consolidados de Extreme: promedios coherentes con las sumas (CONS-001, exacto o el `CEIL` del cierre de Extreme), segmento de la ruta (REL-006), día de la semana (REL-007 y VAL-007) y hora del bloque (VAL-008). |
| `consolidados.py` | Paso del ciclo para los consolidados de Extreme (§6.1, §6.3, §11.2; migración 0013): una vez por ejecución lee `timbradas_consolidado`, `timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`, cada una desde su marca de agua (`marca_agua_tabla`), las valida y las contrasta con la agregación propia (CONTR-001 a CONTR-003 en `data_quality_error`). El resumen queda en `metricas.calidad.consolidados` (`docs/consolidados_ciclo.md`). |
| `datos.py` | Vista analítica `demanda_horaria` y catálogo de rutas (capacidad, ciclo, flota, frecuencia actual). Con `datos/bajadas_horaria.parquet`, la serie offline trae también las bajadas de los viajes válidos (`bajadas_viajes`). |
| `inferencia.py` | Entrena, registra, carga (verifica el SHA-256 del artefacto), predice y evalúa (MAE, RMSE, WAPE por ruta, pico y valle). |
| `optimizacion.py` | `optimizar`: función objetivo de §10.2 (min α·costo_operativo + β·tiempo_espera + γ·sobreocupación + δ·desviación) como MILP de la franja con PuLP/CBC, sujeta a capacidad sobre el P90 calibrado, flota, headway mínimo y máximo y ciclo; pesos versionados en `threshold_config`; tipologías de capacidad de `tipologias_flota.json` (§10.1); comparación con la frecuencia programada y con el headway vigente de `rutas.frecuenciadespachos`, «qué pasa si» y sensibilidad (RF-008). `recomendar` es la línea base de §10.3, `plan_dia` el MILP D5 del día con el modelo activo (tarifa, elasticidad y suavidad versionadas en `threshold_config`, `PARAMETROS_PLAN`) y `plan_dia_d5` la reproducción de laboratorio de D5 (`motor_d5/`). El factor de carga crítica (`factor_carga_franja`) es por ruta, día de la semana de operación y hora, con el tipo de día de respaldo; la franja y cada hora del plan traen su segmento crítico histórico (`ocupacion_historica`), y `plan_dia(ocupacion_actual=…)` aplica la restricción reactiva de la ocupación observada (§10.1). |
| `alertas.py` | Reglas ALT-001 a ALT-010, deduplicación y máquina de estados (reconocer, asignar, comentar, cerrar, descartar). ALT-002 observada se mide en el segmento crítico cuando la hora trae la ocupación por segmento. ALT-006 y ALT-009 llevan el viaje, el vehículo y el seudónimo del conductor cuando la fuente trae los viajes, y toda alerta dice en `variables.identificacion_5_3` qué campos de §5.3 le aplican y por qué. ALT-003 exige además una probabilidad mínima de superar la capacidad efectiva (`alt003_probabilidad_minima`, migración 0014; `docs/alertas_viajes_y_alt003.md`); con los viajes del día, ALT-009 no cuenta como faltante una hora sin ningún viaje programado no cancelado, y ALT-008 evalúa subidas, bajadas y número de viajes (`docs/consolidados_ciclo.md`). |
| `notificaciones.py` | Adaptadores de correo y WhatsApp configurables; el envío es simulado y queda en `notification_log`. También manda el reporte de las llaves duplicadas de cada lote (UNI-001) al responsable del consolidado (§6.3, `NOTIF_UNICIDAD_DESTINATARIOS`); sin destinatario queda `pendiente_destinatario`. |
| `ocupacion.py` | Ocupación por segmento (§10.1): la carga a bordo de cada viaje sale de sus subidas y bajadas por segmento, acotada en 0 en cada segmento. Da el segmento crítico histórico (`datos/ocupacion_segmentos_hora.parquet`), la ocupación actual que el ciclo guarda en `ocupacion_segmento` y la restricción reactiva del plan del día (`docs/ocupacion_segmentos.md`). |
| `novedades.py` | Novedades viales por fecha, rango horario y ruta (§11.2): una novedad con filas en `novedades_viales_ruta` afecta solo a sus rutas, y una sin filas, a todas. `inferencia.variables_de` aplica el mismo paso al entrenar y al inferir. |
| `retencion.py` | Trabajo `retencion` de la cola (§18): aplica o simula la política de 13 meses en caliente con los parámetros de `threshold_config` y deja cada acción en `retencion_registro` (`docs/retencion_datos.md`). |
| `ejecucion.py` | Orquesta una ejecución como job con progreso y reintentos; todo queda ligado a `execution_id`, `model_id`, `feature_version`, versión de umbrales y `data_cutoff`. Una ejecución partida por ruta es una madre con un trabajo por ruta, y todos usan la versión de umbrales vigente al crearla (`umbrales_de_la_ejecucion`). Al cerrar, una vez por ejecución (la de todas las rutas o la madre de una partida), corre el paso de los consolidados de Extreme. |
| `cola.py` | Cola de trabajos en PostgreSQL para N réplicas (RNF-005): reclamo con `SELECT … FOR UPDATE SKIP LOCKED`, reserva (*lease*) que vence y se renueva con un latido, reintento con espera exponencial, cierre con cerca (solo confirma quien aún tiene la reserva) y traza de cada intento en `execution_attempt`. Tipos de trabajo: `frecuencia`, `entrenamiento`, `respuesta`, `segmentos` y `retencion`. Dos trabajos de frecuencia de la misma ruta (o uno de todas las rutas) nunca corren a la vez; los de rutas distintas sí, en réplicas distintas. Los entrenamientos corren en paralelo. |
| `ingesta.py` | Ingesta al histórico propio con `COPY` a una tabla de paso + un `INSERT … ON CONFLICT … WHERE … IS DISTINCT FROM`, en la misma transacción de la ejecución (RNF-003). Desde la migración 0013 guarda también, si el lote las trae, las bajadas de los viajes válidos y las subidas, bajadas y cobertura de los segmentos; una medida que no llega no borra la guardada. |
| `planificador.py` | Planificador interno con APScheduler (§7.2): ejecución diaria (partida por ruta con `PLAN_PARTICION=ruta`), revisión de reentrenamiento, retención de datos (`PLAN_RETENCION_CRON`) y, con la base operacional configurada (`FUENTE_DATABASE_URL`), refresco de la agregación de segmentos, cada uno con su cron; encola una sola fila por franja aunque haya N réplicas (`GET /api/v1/scheduler`). |
| `variables.py` | Variables del modelo por versión (fv1 y fv2), sin información posterior al instante de predicción. |
| `monitoreo.py` · `politica.py` | Monitoreo por ejecución (error móvil, cobertura, PSI, volumen y alertas descartadas), foto de variables (por ruta y, además, una fila por segmento y sentido de cada predicción) y aprendizaje continuo: retador en sombra, compuerta, activación auditada y reversión automática. |
| `onnx_motor.py` | Motor de inferencia ONNX Runtime alternativo (`MOTOR_INFERENCIA=onnx`). |
| `modelo_segmentos.py` | Modelo de la demanda por segmento y sentido: HGB Poisson jerárquico con el reparto fijo B0 como línea base, banda P10–P90 conformal compuesta con la de la ruta, registro propio con SHA-256 (`datos/modelos/segmentos/`) y filas por segmento de la foto de variables (`docs/modelo_segmentos.md`). |
| `catalogos.py` · `segmentos.py` | Catálogos de solo lectura (§3.1 «Gestión operacional») con el ajuste local de capacidad, y capa analítica por segmento, servida desde una agregación materializada, y por zona (§6.1, §6.2). `catalogos.viajes_para_alertas` da los viajes de ALT-006 y ALT-009 cuando la fuente del ciclo no los trae: de la réplica o de la exportación `progvehiculos.parquet`. |
| `segmentos_refresco.py` | Trabajo `segmentos` de la cola: relee `timbradas_segmentos` con el usuario de solo lectura por tramos de fechas y rehace la agregación materializada (modos `auto`, `completo`, `incremental` y `rango`; `docs/segmentos_materializados.md`). Desde la migración 0012 compara las huellas de la ventana de solape (`huellas_solape`): si ninguna fecha cambió, termina `sin_cambios` sin escribir nada, y un incremental solo vuelve a agregar las claves de las fechas releídas (`reagregar_faltantes`). |
| `flota_ciclo.py` | Flota disponible y tiempo de ciclo por ruta, tipo de día y hora: el dato empaquetado o el ajuste local versionado en `threshold_config` (`GET` y `PUT /api/v1/catalogos/flota`; `docs/gobierno_parametros.md`). |
| `circuito.py` | Circuit breaker de la fuente y de los notificadores (RNF-010). |
| `respuesta.py` | Respuesta a la pregunta final del reto (§20) por ruta y día, armada con los servicios anteriores y con su trazabilidad (`GET /api/v1/respuesta` y `/respuesta/export`). |

El detalle de cada módulo, el flujo de una ejecución, el ciclo de vida del modelo y cómo extender la API están en
`docs/manual_tecnico.md`.

## Inicio rápido

Con Docker Desktop abierto, desde `api_frecuencias/` (en Windows; en macOS o Linux use `cp` y `export`):

```
copy .env.example .env
python scripts\crear_api_key.py --rol admin --usuario demo
docker compose -p sobusa_api up -d --build
curl http://127.0.0.1:8000/health
curl -H "X-API-Key: <clave>" http://127.0.0.1:8000/api/v1/models
```

1. En el `.env`, cambie `POSTGRES_PASSWORD` y `SEUDONIMO_SECRETO`.
2. `crear_api_key.py` solo usa la biblioteca estándar de Python. Imprime la clave una sola vez y la entrada con su
   hash: pegue esa entrada en `API_KEYS` del `.env` antes de levantar la pila, y guarde la clave, que es la que va en
   `X-API-Key`.
3. `docker compose` crea la base, aplica las migraciones (servicio `migrar`) y deja la API en el puerto 8000. Swagger
   queda en http://127.0.0.1:8000/docs.
4. `/health` debe responder `{"estado": "ok", "base_datos": "ok", …}`, y `/api/v1/models` debe mostrar el modelo activo
   `hgb_fv2_20250831_s42`.

Para recorrer el ciclo completo de §14.2 contra esa API (necesita el entorno `.venv` con
`pip install -r requirements-dev.txt`, que trae el cliente HTTP de los scripts):
`set SOBUSA_API_KEY=<clave>` y `.venv\Scripts\python scripts\demo_ciclo_api.py --base http://127.0.0.1:8000`.
Las otras formas de correrla (venv, réplica, dos réplicas y Jaeger) están en `docs/despliegue.md`. El uso diario del
tablero y de la API está en `docs/manual_usuario.md`.

## Cómo correrla

**Con Docker (recomendado; aplicación y PostgreSQL):**

```
copy .env.example .env            (Windows; en macOS o Linux: cp .env.example .env)
                                  y cambie POSTGRES_PASSWORD y SEUDONIMO_SECRETO
docker compose -p sobusa_api up -d --build
```

`db` (PostgreSQL 14 + PostGIS) queda sano, el servicio `migrar` aplica las migraciones (`alembic upgrade head`) una
sola vez y luego arranca `api` en **http://localhost:8000/docs** (Swagger), con usuario sin privilegios y HEALTHCHECK
sobre `/health`. La base queda en el puerto 5433 del equipo. Para apagar: `docker compose -p sobusa_api down`
(agregue `-v` para borrar la base). La imagen (Python 3.11) instala solo `requirements.txt`; las herramientas de
pruebas están en `requirements-dev.txt`. Claves de API para el tablero, k6 y la demostración (`SOBUSA_API_KEY`):
`docs/despliegue.md`, sección 5.

**Prueba reproducible del despliegue (RNF-008, RNF-001; 13-11-2026)**, en un proyecto Compose aislado
(`sobusa_limpio`, puertos 8010 y 5440, volúmenes propios) que se crea desde cero y se borra al final:

```
.venv\Scripts\python scripts\verificar_despliegue.py                    (pila aislada: arranque, migraciones, claves,
                                                                         demostración §14.2, caída RNF-001, imagen)
.venv\Scripts\python scripts\verificar_despliegue.py --modo-integrado   (API contra la réplica, sin recrearla)
```

Las salidas quedan en `docs/evidencias/despliegue/` (`arranque_limpio.txt`, `migraciones.txt`, `demo_ciclo_api.txt`,
`reinicio.txt`, `imagen.txt`, `modo_integrado.txt`). Los comandos de pruebas y análisis están en «Pruebas».

**Sin Docker para la API (entorno local):** hace falta un PostgreSQL 14 accesible en `DATABASE_URL`; el más simple es
el mismo servicio `db` de Compose (`docker compose -p sobusa_api up -d db`, puerto 5433).

```
python -m venv .venv
.venv\Scripts\activate             (Windows)   ·   source .venv/bin/activate   (macOS o Linux)
pip install -r requirements-dev.txt          (incluye requirements.txt; para solo correr la API basta este último)
alembic upgrade head
uvicorn app.main:app --port 8000
```

**Variables de entorno** (todas en `.env.example`; el `.env` real no se versiona ni viaja en el ZIP). La tabla completa,
con cuáles son secretas, está en `docs/despliegue.md`, sección 2; las principales:

| Variable | Por omisión | Para qué |
|---|---|---|
| `DATABASE_URL` | sin valor en el código (en Compose la arma `docker-compose.yml`) | Base de resultados propia (esquema `ai_frecuencias`); en el venv va en el `.env`. Secreta: lleva la clave. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `ai_frecuencias`, `sobusa`, *(obligatoria)* | Credenciales del servicio `db` local. |
| `DB_PUERTO_HOST`, `API_PUERTO_HOST` | 5433, 8000 | Puertos publicados en el equipo. |
| `FUENTE` | `parquet` | `parquet` (sin red, reproducible) o `postgres` (base de Extreme, solo lectura). |
| `FUENTE_DATABASE_URL` | vacía | Base operacional con un usuario de solo `SELECT`: la lee el ciclo con `FUENTE=postgres`, y con ella corren también el refresco de segmentos y el paso de consolidados del ciclo. |
| `FUENTE_STATEMENT_TIMEOUT_MS` | 30000 | Límite de cada consulta a la fuente. |
| `DATA_DIR` | `./datos` | Carpeta con los Parquet y JSON del proyecto. |
| `ENTORNO`, `DOCS_HABILITADOS` | `local`, `true` | Swagger restringido por ambiente. |
| `MAX_REINTENTOS`, `REANUDAR_EJECUCIONES` | 3, `true` | Reintentos de cada etapa y reanudación de ejecuciones tras un reinicio. |
| `PLAN_PARTICION` | `ninguna` | `ruta` parte la ejecución diaria del planificador en una madre y un trabajo por ruta (RNF-005, `docs/particion_por_ruta.md`). |
| `PLAN_INTRADIA_CRON` | `5 6-20 * * *` | Ciclos intradía del planificador (§10.1, ocupación actual; 10.1-d). Encolan una ejecución de frecuencia con `instante` = la franja; el plan del día en curso y las recomendaciones de 30 y 60 min usan la ocupación de la última hora cerrada. Solo existen con `FUENTE=postgres` (captura en vivo); vacía los apaga (`docs/ocupacion_segmentos.md`). |
| `PLAN_SEGMENTOS_CRON`, `SEGMENTOS_DIAS_POR_LOTE`, `SEGMENTOS_COMPLETO_DIAS` | `45 5 * * *`, 31, 7 | Refresco de la agregación de segmentos: cron (solo con `FUENTE_DATABASE_URL`), días de `timbradas_segmentos` por lectura y días máximos entre dos refrescos completos (`docs/segmentos_materializados.md`). |
| `PLAN_RETENCION_CRON` | `30 3 * * 0` | Corrida programada de la retención de datos (§18), los domingos a las 03:30; vacía la apaga. Los meses en caliente y si esa corrida aplica o solo simula no son variables: son parámetros de `threshold_config` (`docs/retencion_datos.md`). |
| `FOTO_SEGMENTOS` | `true` | Una fila por segmento y sentido de cada predicción en la foto de variables; `false` la apaga. |
| `LOG_NIVEL`, `TZ` | `INFO`, `America/Bogota` | Logs JSON y zona de presentación (en la base todo va en UTC). |
| `NOTIFICACIONES_CANALES`, `NOTIFICACIONES_SEVERIDAD` | vacío (ninguno), `critica` | Canales simulados (`correo,whatsapp`) y severidad mínima que se notifica. |
| `NOTIF_CORREO_DESTINATARIOS`, `NOTIF_CORREO_REMITENTE`, `NOTIF_WHATSAPP_NUMEROS` | vacíos | Destinatarios (se enmascaran en los logs). No hay credenciales de envío: el envío es simulado. |
| `NOTIF_UNICIDAD_DESTINATARIOS` | vacía | Correos del responsable del consolidado, que recibe el reporte de llaves duplicadas de cada lote (§6.3; correo simulado). Lo define Extreme; sin él, el reporte queda en `notification_log` como `pendiente_destinatario`. |
| `AUTH_HABILITADA`, `API_KEYS` | `true`, vacía | X-API-Key con roles; `API_KEYS` lleva solo los hashes (`scripts/crear_api_key.py`). Secreta. |
| `SEUDONIMO_SECRETO` | marcador en `.env.example` | Secreto del HMAC que seudonimiza al conductor en las alertas (§18). Secreto. |
| `SOBUSA_API_URL`, `SOBUSA_API_KEY` | `http://127.0.0.1:8000`, vacía | Lo que usan los clientes (tablero Dash, k6, demostración). La clave es secreta. |

**Réplica local de la base operacional de Extreme (perfil `integracion`, puerto 5434).** Un PostgreSQL 14 + PostGIS
aparte (servicio `operacional`) con las tablas de Extreme creadas desde las exportaciones y sus 8 scripts copiados
byte a byte (`replica/extreme`, verificados con `SHA256SUMS`); las correcciones van en archivos aparte
(`replica/errata`: E1, E2 y H1, cada una con una prueba que muestra el fallo sin ella). Crea los usuarios técnicos
`lector_ia` (solo `SELECT`, transacciones de solo lectura, `statement_timeout` 30 s) y `escritor_ia` (solo el esquema
`ai_frecuencias`). Defina `OPERACIONAL_PASSWORD`, `LECTOR_IA_PASSWORD` y `ESCRITOR_IA_PASSWORD` en el `.env` y:

```
docker compose -p sobusa_rep --profile integracion up -d operacional     (inicializa en unos 2 s)
.venv\Scripts\python -m scripts.replica_cargar                           (3,38 millones de filas en 66-155 s)
  (o sin venv: docker compose -p sobusa_rep --profile integracion run --rm cargador_replica)
.venv\Scripts\python -m scripts.replica_evidencias                       (docs\evidencias\replica\)
.venv\Scripts\python -m pytest tests\replica                             (se omiten si la réplica no está arriba)
```

**Modo integrado (como correría en Extreme).** La API lee con `lector_ia` y escribe sus resultados en `ai_frecuencias`
con `escritor_ia`, en la misma base de la réplica (`docker-compose.integracion.yml`, puerto 8302):

```
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion build api
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion run --rm --no-deps migrar
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion up -d --no-deps api
  (--no-deps: no recrea ni reinicia el contenedor «operacional» ni su volumen; ver docs/despliegue.md, sección 3.3)
.venv\Scripts\python -m scripts.replica_simular_llegada --viajes 3 --liquidar --consolidar --ciclo-api   (llegada por el trigger y 3 ejecuciones)
.venv\Scripts\python -m scripts.replica_explain                          (EXPLAIN antes y después de la propuesta de índices)
.venv\Scripts\python -m scripts.replica_indices_candidatos               (cada índice candidato y la propuesta entera, en transacciones que se revierten)
.venv\Scripts\python -m scripts.replica_lectura_consolidados             (consolidados por proceso, con volumen de otro operador en una tabla temporal)
.venv\Scripts\python -m scripts.replica_contexto                         (contexto del modelo leído de la base)
REPLICA_PRUEBAS_ESCRITURA=1 .venv\Scripts\python -m pytest tests\replica  (incluye las pruebas que escriben en la réplica)
```

Detalle, controles de no interferencia con su prueba y rendimiento: `docs/integracion_postgresql.md`; hallazgos y
preguntas para Extreme: `docs/hallazgos_extreme.md`.

## Seguridad, resiliencia y observabilidad

- **Autenticación (§7.2).** Cada ruta de `/api/v1` exige la cabecera `X-API-Key`. Sin clave o con una clave inválida
  responde 401 (`no_autenticado`, con `WWW-Authenticate`); con un rol insuficiente, 403 (`prohibido`). Los roles son
  acumulativos. `operador` lee todo y cambia el estado de las alertas. `analista` además lanza ejecuciones,
  predicciones, recomendaciones, entrenamientos y el refresco de la agregación de segmentos. `admin` además activa o
  revierte modelos, cambia umbrales, la capacidad, la flota disponible y el tiempo de ciclo, y corre la retención de
  datos bajo demanda (`POST /api/v1/retencion/aplicar`). La
  matriz está en un solo lugar, `app/seguridad.py`: una escritura nueva sin rol asignado exige admin, y
  `tests/integracion/test_seguridad.py` falla hasta que alguien le asigne el rol.
- **Claves solo por entorno, nunca en el repositorio.** `python scripts/crear_api_key.py --rol analista --usuario ana`
  imprime la clave una sola vez y la entrada `{"<sha256>": {"usuario", "rol"}}` para `API_KEYS`. También se puede
  definir una clave por rol con `API_KEY_OPERADOR`, `API_KEY_ANALISTA` y `API_KEY_ADMIN`. Los clientes (scripts de
  demostración y de rendimiento, y el Dash) envían `SOBUSA_API_KEY`. La auditoría (`alert_history.usuario`,
  `model_registry.aprobado_por` y la auditoría de modelos y umbrales) registra al usuario autenticado, no el que
  viene en el cuerpo de la petición. `AUTH_HABILITADA=false` solo sirve para desarrollo local.
- **Swagger.** `/docs` y `/openapi.json` existen con `ENTORNO` = local, pruebas o demo. En producción responden 404.
  `/health` es público. `/metrics` también lo es, salvo con `METRICAS_PUBLICAS=false`.
- **Datos personales (§18).** Los catálogos nunca exponen placa, conductor, propietario ni contactos
  (`docs/evidencias/catalogos/sin_datos_personales.txt`). El conductor de una alerta solo se guarda como seudónimo
  HMAC-SHA256 con `SEUDONIMO_SECRETO`, y la base rechaza un valor en claro con un CHECK. Las lecturas de viajes (la de
  la ocupación por segmento y la de ALT-006 y ALT-009) lo seudonimizan al leer: el dato en claro no sale de la capa de
  lectura.
- **Retención (§18).** Un trabajo `retencion` de la cola aplica la política de 13 meses en caliente, solo en
  `ai_frecuencias`. Separa (`DETACH PARTITION`) y borra las particiones mensuales viejas de `feature_snapshot`, y borra
  por lotes los resultados, las alertas cerradas, las notificaciones y las ejecuciones que ya no sostienen nada.
  Conserva las alertas abiertas, el histórico validado, la ocupación por segmento, el registro de modelos, los
  umbrales, las marcas de agua y la agregación de segmentos. La programa el planificador (`PLAN_RETENCION_CRON`) y,
  con `PLANIFICADOR_HABILITADO=true`, esa corrida aplica por omisión (`retencion_aplicar_programada` = 1).
  `POST /api/v1/retencion/aplicar` (admin) simula por omisión. Cada acción queda en `retencion_registro`
  (`docs/retencion_datos.md`; corridas de ejemplo en `docs/evidencias/retencion/`).
- **Circuit breaker (RNF-010).** Protege la base fuente (`fuente_postgres`: 3 fallos y 60 s) y los notificadores
  (`notif_correo` y `notif_whatsapp`: 5 fallos y 120 s). Cuando un circuito está abierto, la llamada falla rápido sin
  tocar la integración. Después hace un ensayo en semiabierto y, si sale bien, se cierra. Los errores de datos no lo
  abren. Las notificaciones omitidas quedan en `notification_log` con estado `omitida_circuito_abierto`. Cada circuito
  aparece en `/health` (`integraciones`) y en `/metrics` (`api_circuito_estado`, donde 0 es cerrado, 1 semiabierto y
  2 abierto).
- **Logs y trazas (RNF-006).** Los logs salen en JSON (structlog) e incluyen `correlation_id`, `execution_id`,
  `worker_id`, `trace_id` y `span_id`. Las trazas OpenTelemetry cubren el HTTP, cada sentencia SQL y cada etapa de
  una ejecución (`ejecucion.lectura_incremental`, `calidad`, `prediccion`, `alertas`, `notificaciones`), también
  cuando la ejecución la toma el hilo de la cola. Si la toma otra réplica, esta continúa la misma traza desde
  `execution_log.traceparent`, y el atributo `traza_origen` del span lo deja dicho (`execution_log`; `memoria` si la
  corre la misma réplica) (`docs/evidencias/contrato/traza_entre_replicas.txt`). `OTEL_EXPORTADOR` puede ser
  `ninguno`, `consola` u `otlp`. Para
  usar Jaeger: `OTEL_EXPORTADOR=otlp docker compose -p sobusa_api --profile observabilidad up -d` y abrir
  http://localhost:16686.
- Las evidencias están en `docs/evidencias/seguridad/`: la matriz de roles, la resiliencia, la traza de Jaeger y los
  logs JSON.

## Endpoints

Base `/api/v1`, JSON UTF-8, fechas ISO-8601 con zona (-05:00), errores uniformes
(`{"error": {"codigo", "mensaje", "detalle", "correlation_id"}}`) y cabecera `X-Correlation-Id` en cada respuesta. Toda
ruta de `/api/v1` exige `X-API-Key`. La columna «Rol» es el rol mínimo (`app/seguridad.py`, `POLITICA`): los GET
exigen `operador` y una escritura sin entrada en la matriz exige `admin`. Las colecciones se paginan con `limite` y
`desplazamiento`, se ordenan con `orden` y se filtran por sus campos. En las de la base de resultados, la llave
primaria desempata el orden (`app/routers/comun.py`, `ordenar`), así las páginas no repiten ni saltan filas. Las
exportaciones aceptan `formato=csv|xlsx` y
responden con `X-Total-Count` (registros que cumplen el filtro) y `X-Truncado` (`true` si el archivo se cortó en el
tope de 100.000 filas).
El contrato completo (OpenAPI 3.1: 65 rutas y 69 operaciones) está en `docs/openapi.json` y en Swagger (`/docs`, fuera de
producción). Cada operación de `/api/v1` declara su rol mínimo en `x-rol-minimo` y los errores que de verdad puede
devolver, todos con el formato uniforme: 400 `cuerpo_ilegible` (cuerpo que no se puede decodificar), 401
`no_autenticado`, 403 `prohibido` (con `rol_requerido`), 404, 409, 422 `validacion` (con `tipo` = `caracter_nulo` si
algún valor trae el byte NUL) o `fuera_de_rango` (por ejemplo, `hasta=9999-12-31`), 500 y, en las lecturas que dependen
de una fuente externa, 503. Detalle en `docs/manual_tecnico.md`, sección 2.4.

**Ejecuciones y planificador**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| POST | `/api/v1/frequency/executions` | analista | Lanza una ejecución como job (lectura incremental → calidad → histórico → predicción → recomendación → alertas → notificaciones → plan del día siguiente y foto de la respuesta del reto); responde 202 con el `execution_id`. Con `"particion": "ruta"` crea una ejecución madre y un trabajo por ruta (las de `rutas` o todas las del catálogo; 422 `ruta_desconocida`), y la respuesta trae `trabajos` (RNF-005). Con un `instante` del día en curso es un ciclo intradía: el plan es de ese día y, con la fuente PostgreSQL, es el único caso en que actúa la restricción reactiva de la ocupación por segmento (§10.1). |
| GET | `/api/v1/frequency/executions` | operador | Ejecuciones, paginadas y filtradas (también por `ruta` y `padre_id`). |
| GET | `/api/v1/frequency/executions/{execution_id}` | operador | Estado, etapa y progreso, corte de datos, marcas de agua, métricas y errores; `ruta`, `padre_id` y `particion`, y en una madre, sus `trabajos`. `metricas.calidad.consolidados` resume el paso de los consolidados de Extreme. |
| GET | `/api/v1/frequency/executions/{execution_id}/errors` | operador | Errores de calidad por lote, fila, llave del registro, campo, valor, código, dimensión y si bloquea; filtrables por `lote`, `dimension`, `codigo`, `bloqueante` e `idruta`. Incluyen las incidencias del contraste de los consolidados (CONTR-001 a CONTR-003). |
| GET | `/api/v1/frequency/watermarks` | operador | Marca de agua de la lectura incremental por proceso y ruta (la fila `*` es la frontera de las lecturas de todas las rutas), con el trabajo que la dejó y cuántas huellas guarda (RNF-005). |
| GET | `/api/v1/scheduler` | operador | Planificador interno: próximas ejecuciones (también la retención de datos), últimas franjas encoladas, partición de la ejecución diaria (`PLAN_PARTICION`) y estado de la cola. |

**Pronósticos**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| POST | `/api/v1/predictions/run` | analista | Pronóstico de una ruta y un horizonte (30, 60 o 120 min) con banda P10–P90, explicación y la recomendación de la franja. Trae además las claves del ejemplo de §12.3 (`predictionId`, `routeId`, `generatedAt`, `horizonMinutes`, `predictedPassengers`, `confidenceInterval`, `modelVersion`, `recommendation`, `explanation`). |
| GET | `/api/v1/predictions` | operador | Pronósticos guardados, con filtros (ruta, fechas, horizonte, modelo), paginación y orden. |
| GET | `/api/v1/predictions/{prediction_id}` | operador | Una predicción con su trazabilidad (`model_id`, `feature_version`, `data_cutoff`, latencia y explicación local). |
| GET | `/api/v1/predictions/export` | operador | Los mismos filtros, en CSV o XLSX. |
| GET | `/api/v1/predictions/segmentos` | operador | Pronóstico por segmento y sentido con el modelo de segmentos activo (`seg_hgb_jerarquico_20230227_s42`, verificado por SHA-256) y banda P10–P90 por segmento y por sentido. `modelo_segmentos=` elige otra versión registrada, como el reparto fijo B0 (`seg_reparto_fijo_20230227`). |

**Recomendaciones**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| POST | `/api/v1/recommendations/calculate` | analista | Headway, buses por hora y vehículos con la función objetivo de §10.2: restricciones activas, límites que mandan, tipologías, línea base de §10.3, comparación con la frecuencia programada y, si se piden, `escenario` y `sensibilidad`. Una franja inviable sale `viable = false` con su motivo. `ocupacion_historica` nombra el segmento crítico histórico de la franja y su ocupación (§10.1). |
| GET | `/api/v1/recommendations` | operador | Recomendaciones guardadas, con filtros. |
| GET | `/api/v1/recommendations/export` | operador | Los mismos filtros, en CSV o XLSX. |
| GET | `/api/v1/recommendations/plan` | operador | Plan D5 del día por hora (`ruta` y `fecha`) con el pronóstico del modelo activo, persistido por el ciclo diario: salidas, headway, vehículos, costo, límites que mandan, viabilidad con su motivo y comparación con lo programado. Cada hora trae `sin_intervalo` (una sola salida: el headway mínimo no aplica), `flota_disponible` y `costo_hora_cop`; el día trae `vehiculos_hora_pico` (⌈ciclo / headway⌉ de §10.3), `buses_en_ruta_pico` (buses en ruta a la vez, el conteo que limita la flota) y `definicion_vehiculos`, que explica las dos. Cada hora trae además `ocupacion_historica` (su segmento crítico histórico) y, solo en la hora en que actúa, `restriccion_reactiva`; el día trae `ocupacion_actual`, que dice si la restricción reactiva aplicó o por qué no (§10.1). 404 `sin_calcular` si el plan de esa fecha no está calculado. `pronostico=E12` usa el pronóstico precalculado de 2025 del experimento 12. |
| GET | `/api/v1/respuesta` · `/api/v1/respuesta/export` | operador | Respuesta a la pregunta final del reto (§20) en un solo lugar, por ruta (`ruta` y `fecha` opcionales), leída de la foto persistida: cada cuánto despachar por hora y franja frente a lo programado, con su viabilidad; pasajeros esperados con P10–P90; vehículos en ruta frente a la flota; balance de flota y recaudo; alertas abiertas, críticas primero. 404 `sin_calcular` si no hay foto para esa fecha con el modelo y los umbrales vigentes. La exportación da una fila por ruta y hora en CSV o XLSX. Evidencia en `docs/evidencias/respuesta/`. |
| POST | `/api/v1/respuesta/calcular` | analista | Calcula la foto de la respuesta para una fecha (y rutas) como trabajo de la cola: responde 202 con el `execution_id`; si ya hay un cálculo igual en cola o corriendo, devuelve ese. |

**Alertas**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| GET | `/api/v1/alerts` | operador | Alertas por estado, severidad, ruta, código, fecha y lugar (`cerca_de=lat,lon` y `radio_m`, máximo 50 km: `ST_DWithin` sobre `geography` con índice GiST), con todos los campos de §5.3: origen, tendencia con su pendiente, serie reciente, probabilidad y método del puntaje, variables influyentes y ubicación. ALT-006 y ALT-009 traen el viaje, el vehículo y el conductor (solo seudónimo) de `progvehiculos` cuando la fuente trae los viajes, y la ALT-002 observada medida en el segmento crítico, el sentido aproximado y el viaje más cargado. En cada alerta, `variables.identificacion_5_3` dice qué campos aplican y por qué. |
| GET | `/api/v1/alerts/export` | operador | Los mismos filtros (también por lugar), en CSV o XLSX. |
| GET | `/api/v1/alerts/{alert_id}` | operador | Una alerta. |
| GET | `/api/v1/alerts/{alert_id}/history` | operador | Bitácora de cambios de la alerta. |
| PATCH | `/api/v1/alerts/{alert_id}/status` | operador | Reconocer, asignar, comentar, cerrar o descartar; queda en la bitácora con el usuario de la clave. |

**Modelos, umbrales y monitoreo**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| GET | `/api/v1/models` | operador | Registro de modelos: activo, candidatos, métricas, fecha de corte y SHA-256. |
| GET | `/api/v1/models/{model_id}` | operador | Ficha de un modelo con su auditoría. |
| GET | `/api/v1/models/{model_id}/evaluation` | operador | Evaluación registrada y, con `desde`/`hasta`, la de una ventana sobre datos reales (MAE, RMSE, WAPE, sMAPE, sesgo y cobertura). |
| GET | `/api/v1/models/{model_id}/importance` | operador | Importancia global: permutación y media de \|SHAP\|. |
| POST | `/api/v1/models/train` | analista | Entrena un candidato con los datos validados hasta una fecha (job, 202). |
| POST | `/api/v1/models/{model_id}/activate` | admin | Activa una versión solo si pasa la compuerta de cuatro criterios (WAPE ≤ el del activo y ≤ `wape_max`, cobertura P10–P90 en [75 %, 90 %] y \|sesgo\| ≤ `sesgo_max`), con los dos modelos en la misma ventana, posterior a todo lo que vio el candidato (corte + 61 días de validación). Una ventana dentro de esa muestra da 422 `ventana_en_muestra`; si la compuerta no aprueba, 409 `activacion_rechazada` con el motivo; un modelo rechazado o todavía en sombra da 409 `requiere_forzar`. `?forzar=true` lo activa igual, pero exige un `motivo` (si falta, 422 `motivo_requerido`) y queda en la auditoría. |
| POST | `/api/v1/models/rollback` | admin | Vuelve al modelo activo anterior. |
| GET | `/api/v1/thresholds` | operador | Umbrales vigentes, su versión y si están aprobados. |
| PUT | `/api/v1/thresholds` | admin | Cambia umbrales, pesos o parámetros del plan del día (tarifa, elasticidad y suavidad): crea una versión nueva del conjunto, como propuesta. Un valor inválido responde 422 `umbral_invalido`; por ejemplo, tolerancias del contraste de los consolidados incoherentes o un `alt003_probabilidad_minima` fuera de (0; 1,5]. |
| POST | `/api/v1/thresholds/{version}/aprobar` | admin | El área operativa aprueba una versión: firma `aprobado_por` y `aprobado_en` (§5.1). |
| GET | `/api/v1/thresholds/history` | operador | Histórico de versiones de los umbrales. |
| GET | `/api/v1/monitoring` | operador | Monitoreo por ejecución: deriva (PSI), error móvil, cobertura, volumen y alertas descartadas. |
| GET | `/api/v1/monitoring/export` | operador | El monitoreo filtrado, en CSV o XLSX. |
| GET | `/api/v1/monitoring/policy` | operador | Política de aprendizaje continuo: si toca reentrenar, retadores en sombra y umbrales. |
| GET | `/api/v1/monitoring/feature-snapshots` | operador | Foto de variables (§11.2) por ejecución, predicción o ruta, con fecha de corte y versión. |

**Retención de datos (§18)**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| GET | `/api/v1/retencion` | operador | Política de retención vigente tabla por tabla (grupo, acción, parámetro, meses en caliente y corte de hoy), los parámetros con su versión de `threshold_config`, si la corrida programada aplica o solo simula y la bitácora de la última corrida (`retencion_registro`). |
| POST | `/api/v1/retencion/aplicar` | admin | Encola un trabajo `retencion` y responde 202 con el `execution_id`. Por omisión simula (cuenta lo que borraría sin borrar nada); aplica con `"simular": false`. Si ya hay una corrida en cola o corriendo, devuelve esa (`nueva: false`). |

**Catálogos y capa analítica (solo lectura de la base operacional)**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| GET | `/api/v1/catalogos` | operador | Catálogos disponibles y fuente configurada. |
| GET | `/api/v1/catalogos/procesos` · `/empresas` · `/rutas` · `/segmentos` · `/vehiculos` · `/viajes` · `/despachos` | operador | §3.1 «Gestión operacional»: filtros, paginación y orden; segmentos con GeoJSON; vehículos sin placa, conductor ni propietario. |
| GET | `/api/v1/catalogos/{catálogo}/export` (los siete anteriores) | operador | El catálogo filtrado, en CSV o XLSX. |
| GET | `/api/v1/catalogos/rutas/{idruta}` | operador | Una ruta con sus parámetros por hora. |
| GET | `/api/v1/catalogos/vehiculos/tipologias` | operador | Capacidad por ruta y tipología. |
| GET | `/api/v1/catalogos/capacidad` | operador | Capacidad vigente por ruta (catálogo o ajuste local) y por tipología. |
| PUT | `/api/v1/catalogos/capacidad` | admin | Ajuste local de capacidad, versionado y auditado en `ai_frecuencias`, nunca en las tablas de Extreme (§3.2, §8.3). |
| GET | `/api/v1/catalogos/capacidad/historial` | operador | Historial de ajustes de capacidad. |
| GET | `/api/v1/catalogos/flota` | operador | Flota disponible y tiempo de ciclo vigentes por ruta, tipo de día y hora: el dato empaquetado o el ajuste local, con la fuente y la clave de cada cifra. |
| PUT | `/api/v1/catalogos/flota` | admin | Versión nueva de la flota (por tipo de día) o del tiempo de ciclo (por tipo de día y hora) de una ruta, firmada y con motivo, en `ai_frecuencias.threshold_config`; `null` retira el ajuste. La franja de §10.2 y el plan del día usan la versión nueva desde el cálculo siguiente. |
| GET | `/api/v1/catalogos/flota/historial` | operador | Historial de la flota y del ciclo: creado, cambiado o retirado, con el valor anterior y el nuevo, quién y por qué. |
| GET | `/api/v1/segmentos/estadisticas` | operador | Promedio, máximo y mínimo de subidas, bajadas y pasajeros por segmento, estacionalidad, día y hora (§6.1), desde la agregación materializada del esquema propio (migración 0008). `actualizado_en` dice de cuándo es; si todavía no existe, responde 200 con `disponible: false` y el refresco encolado. |
| GET | `/api/v1/segmentos/estadisticas/export` | operador | Las mismas estadísticas, en CSV o XLSX; mientras la agregación se calcula por primera vez, 503 `agregacion_pendiente`. |
| POST | `/api/v1/segmentos/estadisticas/refrescar` | analista | Encola el refresco de la agregación (trabajo `segmentos` de la cola; 202 con el `execution_id`; modos `auto`, `completo`, `incremental` y `rango`). Sin la base operacional, 503 `fuente_no_configurada`. |
| GET | `/api/v1/segmentos/zonas` | operador | Demanda por zona tarifaria (§6.2); para Sobusa explica por qué no hay zonas. |

**Sistema (públicos)**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| GET | `/health` | — | Salud del servicio, de la base y de cada circuito (503 si la base no responde). |
| GET | `/metrics` | — | Métricas Prometheus (privadas con `METRICAS_PUBLICAS=false`): peticiones y latencia por ruta, autenticación, circuitos, la cola (`api_ejecuciones_total`, `api_ejecucion_duracion_segundos`, `api_cola_reintentos_total`, `api_cola_trabajos`) y el ciclo (`api_ejecucion_etapa_segundos`, `api_serie_diaria_segundos`); detalle en `docs/manual_tecnico.md`, sección 9. |

Ejemplos con `curl` y `X-API-Key`, para cada perfil de usuario: `docs/manual_usuario.md`, sección 7.

## El ciclo de la demostración (§14.2)

1. **Llega información nueva.** Con la fuente Parquet, la petición entrega solo los días hasta la fecha `hasta`, como si
   llegaran de los triggers de Extreme: subir `hasta` un día simula la llegada del día siguiente. En la réplica, los
   datos llegan de verdad por el trigger de Extreme (`scripts/replica_simular_llegada.py`).
2. **Lectura incremental.** `POST /frequency/executions` lee solo lo posterior a la marca de agua de cada ruta (la que
   dejó la última ejecución exitosa que la movió, en `ai_frecuencias.marca_agua_ruta`), con una ventana de solape y
   una huella de contenido, así que una fila tardía o modificada se entrega una sola vez. Repetir la ejecución no
   duplica nada.
3. **Evaluación del error.** Los pronósticos se comparan con lo observado (WAPE, MAE, RMSE y sesgo, por ruta, pico y
   valle) y el monitoreo actualiza el error móvil. Si supera la tolerancia, se emite ALT-010.
4. **Modelo candidato.** `POST /models/train` entrena con los datos validados hasta el nuevo corte (semilla 42) y lo
   registra como candidato con su artefacto, SHA-256, métricas y fecha de corte. Nunca pisa al activo. Con
   `reentreno_en_ciclo` = 1, la propia política encola ese entrenamiento cuando toca (por ejemplo, por periodicidad), y
   la demostración espera ese trabajo en vez de pedir otro igual.
5. **Comparación con el activo** en la misma ventana, posterior a todo lo que vieron los dos modelos, sin mezclar
   futuro y pasado. Con `datos_hasta`, el candidato pasa además 14 días en sombra prediciendo en paralelo.
6. **Activación o rechazo.** Al cerrar la sombra decide la compuerta de cuatro criterios (`politica.compuerta`), la
   misma de `POST /models/{model_id}/activate`: WAPE ≤ el del activo y ≤ `wape_max`, cobertura P10–P90 en [75 %, 90 %] y
   |sesgo| ≤ `sesgo_max`. Si no aprueba, el candidato queda rechazado y el activo sigue; activarlo después sin forzar
   da 409 `requiere_forzar`. `POST /models/rollback` vuelve a la versión anterior.

`scripts/demo_ciclo_api.py` recorre los seis pasos contra una API en marcha (con `SOBUSA_API_KEY` de rol admin), y
`scripts/verificar_despliegue.py` lo hace sobre una pila creada desde cero. Con sus valores por omisión
(`--hasta 2025-08-30 --corte 2025-09-30`): llegan 49.623, 51 y 4.641 filas; la repetición lee 0; el candidato
`hgb_fv2_20250930_s42` se compara con el activo en 2025-12-01..14 (WAPE 14,108 % frente a 13,982 %) y la compuerta lo
rechaza. `docs/evidencias/despliegue/demo_esperado.md` explica qué muestra cada paso y por qué esas fechas, y trae la
salida de referencia contra la API en el venv. La corrida en Docker queda en
`docs/evidencias/despliegue/demo_ciclo_api.txt`, que `verificar_despliegue.py` reescribe en cada corrida.
`scripts/demo_ciclo.py` además gestiona alertas, exporta y notifica (`docs/evidencias/demo_ciclo.txt`); otras corridas
están en `docs/evidencias/cola/demo_ciclo_api_cola.txt` y, de antes del modelo fv2, en
`docs/evidencias/demo_ciclo_8nov.txt`. Los dos demos y `verificar_despliegue.py` hablan con la API por el cliente común
`scripts/cliente_http.py`: keep-alive de 2 s y un solo reintento, solo en GET y HEAD; las escrituras nunca se
reintentan. El reintento solo cubre los errores de la carrera del keep-alive (RemoteProtocolError, ConnectError,
ReadError y WriteError), nunca un tiempo agotado. No es `../dash_app/cliente_api.py`, el cliente del tablero. Las
corridas guardadas (13-11-2026) ya usan ese cliente.

## Pruebas

Desde `api_frecuencias/`, con el PostgreSQL local arriba (`docker compose -p sobusa_api up -d db`) y
`pip install -r requirements-dev.txt` en el entorno:

```
set TEST_DATABASE_NAME=ai_frecuencias_pruebas
set SCHEMATHESIS_EJEMPLOS=3
.venv\Scripts\python -m pytest tests\unit tests\integracion tests\replica tests\contrato tests\datos_ml
.venv\Scripts\python -m ruff check app scripts tests
.venv\Scripts\python -m bandit -r app -ll
.venv\Scripts\python scripts\ci_local.py todo          (los mismos pasos del CI, con cobertura y Testcontainers)
```

**Ninguna prueba se conecta a la base del reto.** La integración solo corre contra un PostgreSQL local y en su propia
base (`TEST_DATABASE_NAME`), y las pruebas trabajan sobre copias temporales de `datos/`.

- **La URL de la base de pruebas** sale de `TEST_DATABASE_URL` o, si no está, de `DATABASE_URL` (entorno o `.env`). Sin
  ninguna URL (un checkout limpio sin `.env`), con una URL que no sea local (`localhost`, `127.0.0.1`, `db`) o con el
  PostgreSQL local apagado, las pruebas de integración y las de contrato que usan la base se omiten con el motivo en el
  informe de pytest, sin errores
  (`tests/integracion/conftest.py`). La clave de esa URL no aparece en los tracebacks.
- **Las pruebas no ensucian el checkout.** Las que dejan un archivo de evidencia lo escriben con
  `tests/evidencia.py::guardar_evidencia`: por omisión, en un directorio temporal (o en `EVIDENCIAS_DIR`); solo con
  `GENERAR_EVIDENCIAS=1` reescriben `docs/evidencias/`, por ejemplo
  `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_seguridad.py`.
- **Desde una copia sin la carpeta `datos/` de la raíz** (las exportaciones del reto no se versionan; por ejemplo, un
  worktree de git), defina `REPLICA_DATOS_DIR` y `CATALOGOS_DATOS_DIR` con la carpeta de las exportaciones:
  `tests/replica/test_carga.py` y `scripts/replica_cargar.py` leen `REPLICA_DATOS_DIR`, y los catálogos,
  `CATALOGOS_DATOS_DIR` (o, si falta, `REPLICA_DATOS_DIR`).

| Nivel (§14.1) | Carpeta | Qué cubre |
|---|---|---|
| Unitarias | `tests/unit/` | Reglas de negocio, fórmulas de §10.2 y §10.3, validaciones de calidad, estados de alertas, cola, partición por ruta, circuito, seguridad, monitoreo, política, parámetros gobernados, modelo por segmento, ONNX, ocupación por segmento, novedades por ruta, reporte de unicidad y retención. También el contraste y la calidad de los consolidados (`test_consolidados.py`, `test_calidad_consolidados.py`), la identificación de §5.3 de las alertas (`test_alertas_identificacion.py`), ALT-003 con su probabilidad (`test_alertas_alt003.py`, `test_variantes_alt003.py`) y el cliente HTTP de la demostración (`test_cliente_http.py`). |
| Integración | `tests/integracion/` | API con TestClient, migraciones, repositorios, roles, exportaciones, alertas observadas, monitoreo, partición por ruta, agregación de segmentos y gobierno de parámetros, contra el PostgreSQL local. También la ocupación por segmento en el ciclo (`test_ocupacion_ciclo.py`), las novedades por ruta leídas en solo lectura (`test_novedades_por_ruta.py`), el reporte de unicidad del lote (`test_errores_lote.py`) y la retención (`test_retencion.py`, con tablas centinela en otro esquema). Los consolidados de Extreme en el ciclo, las bajadas en el histórico y la migración 0013 (`test_consolidados_ciclo.py`), el viaje y el conductor de ALT-006 y ALT-009 (`test_alertas_identificacion.py`), el mínimo de ALT-003 con la migración 0014 (`test_gobierno_alt003.py`) y la subida y bajada de la 0008 (`test_migracion_0008_segmentos.py`). `test_convivencia_ciclo_segmentos.py` corre el ciclo con la capa de segmentos sin partir y partido por ruta, con reservas perdidas y reintentos. Con procesos reales (se omiten sin su variable): `PRUEBA_CAIDA=1` (`test_caida.py`, puertos en `PRUEBA_CAIDA_PUERTOS="a,b"` o dos libres), `PRUEBA_REPLICAS=1` (`test_replicas_por_ruta.py`: dos réplicas con la ejecución partida por ruta, puertos en `PRUEBA_REPLICAS_PUERTOS="a,b"` o dos libres) y `PRUEBA_PLANIFICADOR=1` (`test_planificador_programado.py`: la ejecución programada de §14.2, el planificador encola las franjas sin ningún POST). |
| Testcontainers | `tests/testcontainers/` | PostGIS 14-3.4 efímero: Alembic desde cero (upgrade, downgrade y upgrade), repositorios y API. Corre con `TESTCONTAINERS=1`. |
| Contrato | `tests/contrato/` | Cada operación del OpenAPI con autenticación: código documentado, esquema, errores uniformes 401/403/404/422, compatibilidad con `docs/openapi.json` y Schemathesis acotado para cazar errores 5xx. |
| Datos/ML | `tests/datos_ml/` | Rangos y NaN de las variables, PSI, no regresión del WAPE en la prueba reservada frente al manifiesto y a B1/B2, fuga temporal en 3 cortes y, para el modelo por segmento, partición cronológica, artefacto íntegro y reentrenamiento reproducible (`test_segmentos_modelo.py`). También el protocolo sin fuga de ALT-003 (`test_alt003_protocolo.py`) y la evidencia de la identificación de §5.3 (`test_identificacion_viajes_evidencia.py`). |
| Réplica | `tests/replica/` | Contra la réplica de la base operacional (puerto 5434): roles, carga, scripts de Extreme, llegada por el trigger, EXPLAIN, lectura por ruta, capa de segmentos (agregación materializada igual a la directa y refresco sin cambios), novedades por ruta y la lectura de la ocupación por segmento como `lector_ia`. También los consolidados de Extreme y las bajadas (`test_consolidados.py`) y los viajes de las alertas (`test_alertas_viajes.py`), en solo lectura. Con `REPLICA_PRUEBAS_ESCRITURA=1` corren además las que hacen llegar datos por el trigger de Extreme: la llegada, el ciclo integrado y un viaje que se mide por segmento en una transacción revertida. Sin réplica se omiten con su motivo. |
| Carga | `k6/consultas.js`, `k6/consultas_durante_ingesta.js`, `k6/en_frio.js`, `k6/segmentos.js` | Consultas paginadas concurrentes, consultas durante una ingesta, la primera petición a cada ruta con la API recién arrancada y la capa de segmentos durante un refresco, con la clave en `SOBUSA_API_KEY`. `scripts/sembrar_volumen.py` siembra un año de resultados en una base local aparte, replicando filas reales con identificadores nuevos (`docs/evidencias/rendimiento.txt` y `docs/evidencias/pruebas/k6_volumen.txt`); `scripts/medir_segmentos.py` corre los guiones contra una API propia en modo integrado (`docs/evidencias/pruebas/k6_segmentos.txt`). |

El análisis estático con SonarQube usa `sonar-project.properties`, y su evidencia está en `docs/evidencias/sonarqube/`
(`resumen.md`: la puerta «Reto Sobusa v1.5» condición por condición). Se repite con `scripts/sonar_local.py`, que
levanta un SonarQube Community en Docker, corre las pruebas con cobertura, ruff y bandit y analiza (comando y opciones
en `docs/manual_tecnico.md`, sección 13); ruff y bandit quedan en `docs/evidencias/calidad/`.

- **Integración continua**:
  - flujo `.github/workflows/api_frecuencias.yml` en la raíz del proyecto, y `ci/github_actions_entrega.yml` para el
    repositorio de entrega;
  - pasos: ruff, bandit, Alembic de ida y vuelta, pytest con cobertura ≥ 85 % y junit, y verificación de que el
    OpenAPI no cambió sin versionarse;
  - ensayo local idéntico con `python scripts/ci_local.py`, cuyo log queda en `docs/evidencias/pruebas/ci_local.txt`.

## Evidencias

El índice completo, con qué demuestra cada archivo, a qué requisito responde y cómo se regenera, está en
`docs/evidencias/README.md`; su tabla «Cifras vigentes» es la referencia de cada cifra. Algunas cifras clave, cada una
con su archivo:

| Qué | Resultado | Archivo |
|---|---|---|
| Modelo en la prueba reservada (nov.–dic. 2025) | WAPE 14,77 % (IC95 13,10–16,87) frente a 21,18 % de la regla manual B1 y 26,40 % de B2 | `docs/evidencias/modelo/evaluacion_modelo.md` |
| Consultas paginadas con k6 (RNF-002), corrida del 9-11-2026 con un mes de resultados | 3.553 peticiones, 0,00 % de errores, p95 de 451,3 ms (umbral: 2 s) | `docs/evidencias/rendimiento.txt` |
| Las mismas consultas con el volumen acordado (RNF-002), 13-11-2026 | Base sembrada desde el ciclo final (1.056 ejecuciones, 9.216 predicciones y 8.224 alertas): 2.375 peticiones con 50 usuarios, 0,00 % de errores, p95 de 864,1 ms. `GET /segmentos/estadisticas` lee la agregación materializada: 20,8 ms en frío y 18,3 ms en caliente (antes de la migración 0008, 8,8 y 11,9 s), y `/catalogos/segmentos`, 169,8 ms en frío (antes, 5,0 s); con 50 usuarios sobre la capa de segmentos y un refresco completo en curso, p95 de 372,3 ms (332,4 ms durante el refresco), con una petición fallida de 3.806 (0,03 %; umbral: 1 %). Con 30 usuarios durante una ingesta desde la réplica, p95 de 574,5 ms; la ingesta termina «ok» en 225,8 s (el 9-11-2026, 93,8 s; la causa no está separada). Las exportaciones CSV completas (4,3 a 7,7 s) son descargas, fuera de RNF-002 | `docs/evidencias/pruebas/k6_segmentos.txt` (vigente); `docs/evidencias/pruebas/k6_volumen.txt` y `docs/evidencias/pruebas/revision_segmentos/` (corridas anteriores, del 9 y del 10-11-2026) |
| Ciclo diario completo (RNF-004) | Carga inicial de 49.623 filas en 27,5 s y un día nuevo en 20,7 s, con las alertas observadas de cada día del lote, la foto de variables por segmento, el plan del día y la foto de la respuesta; la repetición, en 0,2 s (13-11-2026, código final) | `docs/evidencias/rendimiento/ciclo_final.md` |
| Refresco de la agregación de segmentos sin filas nuevas (RNF-004), en la réplica | Sin huellas comparables relee 26 fechas (164.206 filas) en 10,5 s; con las huellas de la ventana de solape, 0 fechas y 0 filas en 0,5 s, sin escribir nada | `docs/evidencias/pruebas/segmentos_sin_cambios.json` |
| Ingesta de 111.792 filas con `COPY` (RNF-003) | 2,32 s de ingesta (48.205 filas por segundo) y 61 MiB de memoria pico; la recarga idéntica no cambia nada (13-11-2026) | `docs/evidencias/cola/ingesta.txt` |
| Dos réplicas de la API (RNF-005) | 20 ejecuciones repartidas 10/10, 0 duplicados | `docs/evidencias/cola/replicas.txt` |
| Ejecución partida por ruta con dos réplicas (RNF-005) | 6 días partidos por ruta: 24 de 24 trabajos `ok`, 14 pares de rutas distintas a la vez, 0 cruces de la misma ruta, 0 duplicados, marcas de agua contiguas y las mismas predicciones, plan, alertas, foto de la respuesta y monitoreo que sin partir | `docs/evidencias/cola/replicas_por_ruta.txt` |
| Caídas con `docker kill` (RNF-001) | Los tres casos terminan `ok`, sin perder ni duplicar | `docs/evidencias/cola/caida_rnf001_docker.txt` |
| No interferencia con la base de Extreme (§11.3) | 0 escrituras indebidas permitidas en 36 intentos | `docs/evidencias/replica/replica_roles.txt` |
| Lectura incremental con llegada real por el trigger | Tras la llegada de tres viajes por el trigger (584 filas crudas), la lectura entrega exactamente 1 franja nueva y la segunda lectura, ninguna | `docs/evidencias/replica/replica_llegada.txt` |
| Consolidados de Extreme en el ciclo (§6.1, §6.3, §11.2), en la réplica y en solo lectura | `timbradas_consolidado`: 10.731 filas leídas y válidas, y la segunda lectura las descarta por huella. Contraste con el histórico propio: 160 llaves comparadas, 31 incidencias y 11 groseras (H17). Las tablas por segmento no tienen filas de Sobusa (H4): su contraste va sin la hora del bloque de Extreme (H10) y, con filas reales de la liquidación de tres viajes en una transacción que se revierte (`contraste_viajes_minimos` = 1), compara 90 de 90 llaves sin ninguna diferencia grosera | `docs/evidencias/consolidados/contraste_consolidados.md`, `docs/evidencias/consolidados/segmentos_filas_reales.json` |
| Trazas de una ejecución (RNF-006) | Una sola traza con 39 spans en Jaeger | `docs/evidencias/seguridad/jaeger_resumen.txt` |
| Banda P10–P90 con la calibración v2 (prueba reservada) | Cobertura de 77,82 % (v1: 77,88 %) con un ancho medio de 303,4 pasajeros (v1: 312,9) | `docs/evidencias/modelo/calibracion_condicional.md` |
| Volumen de alertas (§18 «Alertas excesivas»), 15-09 a 31-12-2025 | 1,265 alertas observadas por ruta y día en total (con la ALT-002 observada, 0,710, y la ruptura de RF-009, 0,012); solo ALT-005 a ALT-009, 0,543, frente a 6,08 con las reglas anteriores. ALT-008, que evalúa también las bajadas, da 0,071. Con las de pronóstico, 2,203 por ruta y día (1,265 + 0,938; `scripts/cifras_vigentes.py`) | `docs/evidencias/alertas/backtest_alertas.md` (las de pronóstico, en `docs/evidencias/alertas/backtest_alertas_pronostico.md`) |
| Revisión doble de 96 alertas (§18) | Kappa de 0,943 entre los dos revisores (automatizados) antes de conciliar; precisión reponderada de 0,839 (intervalo 95 %: 0,757–0,882) | `docs/evidencias/alertas/revision_doble/conciliacion.json` |
| Contrato OpenAPI (§12.1, §14.1) | Schemathesis con cinco chequeos en las 69 operaciones (65 rutas) de `docs/openapi.json`, sin fallas; `tests/contrato`: 197 casos (128 pruebas y 69 subpruebas), 0 fallas, 0 omitidas y 0 xfail (11-11-2026; el contrato no cambió después) | `docs/evidencias/contrato/schemathesis.txt`, `docs/evidencias/contrato/pytest_contrato.txt` |
| Modelo por segmento y sentido, prueba del 18 al 27-feb-2023 | WAPE por segmento y hora de 42,09 frente a 43,06 del reparto fijo B0; banda P10–P90 con cobertura de 78,31 % por segmento y 83,40 % por sentido (con el total real de la ruta) | `docs/evidencias/modelo/segmentos_modelo.md` |
| Ocupación por segmento (§10.1), ene.–feb. 2023 | La carga a bordo derivada de las subidas y bajadas por segmento correlaciona 0,961 con la ocupación máxima del dispositivo en 21.511 viajes. La restricción reactiva, con los viajes completos (cota superior), dispara 147 veces y la hora siguiente queda sobre el umbral en el 28,6 % de los casos (tasa base: 5,9 %); con los viajes todavía en curso siguen 25 disparos a las (h+1):05 | `docs/evidencias/ocupacion/perfil_ocupacion_segmentos.json` (`validacion`) y `docs/evidencias/ocupacion/backtest_restriccion_reactiva.md` |
| Alertas de pronóstico por hora, mismo periodo | ALT-001 0,438, ALT-002 0,306, ALT-003 0,164 y ALT-004 0,031 por ruta y día (0,938 en total), con lift de 1,81, 2,03, 1,05 (2,08 donde puede emitirse) y 7,62. El mínimo de probabilidad de ALT-003 (0,30) se eligió en una validación anterior a la evaluación; en la evaluación, su lift es 2,08 [1,51; 2,99] donde puede emitirse y 1,16 [0,82; 1,51] sobre todas las franjas | `docs/evidencias/alertas/backtest_alertas_pronostico.md` |
| Suite completa final (unitarias, integración, réplica, contrato y datos/ML) | 1.770 casos (1.106 unitarias, 217 de integración, 209 de réplica, 197 de contrato y 41 de datos/ML): 1.770 aprobados, 0 fallas, 0 errores y 0 omitidas, en una sola sesión, con los procesos reales (`PRUEBA_CAIDA=1`, `PRUEBA_REPLICAS=1` y `PRUEBA_PLANIFICADOR=1`) y las pruebas de escritura en la réplica (`REPLICA_PRUEBAS_ESCRITURA=1`) (14-11-2026) | `docs/evidencias/pruebas/suite_final.xml` (la misma corrida que importa SonarQube) |
| Cobertura de `app/` (incluido `motor_d5/`) en esa suite | 95,70 % (14.656 de 15.314 líneas; mínimo exigido en el CI y en la puerta de SonarQube: 85 %) | `docs/evidencias/pruebas/coverage_final.xml` |
| Despliegue desde cero (RNF-008) | `scripts/verificar_despliegue.py` (13-11-2026, 23:07): «Resultado global: OK» en 4,0 min (arranque, migraciones 0001 → 0014, claves por rol, demostración de §14.2 con el cliente HTTP común, reinicios sin pérdidas y limpieza) | `docs/evidencias/despliegue/arranque_limpio.txt` |
| Análisis con SonarQube (RNF-013) | Puerta «Reto Sobusa v1.5» **aprobada (OK)** en el análisis del 14-11-2026, 00:56, sobre todo el código: 0 vulnerabilidades, 0 bugs, 0 hallazgos bloqueantes y 0 críticos, duplicación de 0,0 % y cobertura de 95,7 %; 1 hallazgo de mantenibilidad aceptado con su justificación (la copia literal del solver D5, app/servicios/motor_d5/milp.py) | `docs/evidencias/sonarqube/quality_gate.json` (condición por condición en `resumen.md`) |

El mapeo de las secciones §1–§3 y §17–§20 de la especificación a esta evidencia está en
`../documentos/mapeo_especificacion.md`.

## Datos y modelos

| Qué | De dónde sale |
|---|---|
| Demanda por ruta, día y hora 2023-2025 (`datos/demanda_horaria.parquet`) | Exportación de la base del reto: suma de `numeropasajeros` de los viajes válidos de `progvehiculos` por hora de salida (`experimentos/E1_lgbm_salida`). Procedencia en `datos/origen.json`. |
| Bajadas por ruta, día y hora 2023-2025 (`datos/bajadas_horaria.parquet`) | Exportación de la base del reto: suma de `numerobajadas` de los viajes válidos de `progvehiculos` por hora de salida, con la regla de los pasajeros (`scripts/preparar_datos_api.py --solo-bajadas`). La serie offline la entrega con la demanda y la usa ALT-008. Procedencia y SHA-256 en `datos/origen.json`; por qué esta definición, en `docs/evidencias/consolidados/definicion_bajadas.md`. |
| Pronósticos 2025 de los experimentos del informe académico (`datos/pronosticos_2025.parquet`) | B1 regla manual (WAPE 20,04 %), experimento 1 LightGBM (14,40 %), experimento 11 LightGBM mejorado (13,94 %) y experimento 12 híbrido (13,62 %): a 7 días de antelación, sobre todo 2025 y reentrenando cada mes. No son cifras del modelo de la API: en la misma ventana (2025) y frente a la misma B1, el modelo de la API congelado al 31-12-2024 da 14,48 % (`docs/evidencias/modelo/evaluacion_modelo.md`). El experimento 12 queda como opción del plan del día (`pronostico=E12`). |
| Insumos del optimizador D5 (`datos/insumos_d5_2025.parquet`) y costos con fuente (`datos/costos_fuente.json`) | Experimento D5 y estudio de costos del proyecto (precios 2026). |
| Catálogo de rutas (`datos/catalogo_rutas.json`) | Tabla `rutas` y medianas de día laboral de `experimentos/D1_optimizacion/parametros_operativos.parquet`; capacidad 50 por bus. |
| Ocupación histórica por segmento (`datos/ocupacion_segmentos_hora.parquet`) | Subidas y bajadas por segmento de cada viaje de `timbradas_segmentos` (exportación del 2023-01-01 al 2023-02-27, lo único que llenaron los triggers de segmentación): carga a bordo por segmento, día de operación y hora, con el tipo de día de respaldo (`scripts/preparar_ocupacion_segmentos.py`). |
| Novedades viales por ruta (`datos/novedades_por_ruta.parquet`) | Solo existe si `novedades_viales_ruta` trae filas (`scripts/preparar_datos_api.py`). En la base del reto y en la réplica la tabla está vacía, así que cada novedad es de todas las rutas y va en `datos/contexto_operacional.parquet`. |
| Modelo de la API | `app/servicios/inferencia.py`: líneas base B1 (media de la misma hora y día de las 8 semanas anteriores) y B2 (misma hora hace 7 días), y el candidato `HistGradientBoostingRegressor` de scikit-learn (pérdida Poisson) con dos modelos de cuantiles para P10 y P90. División cronológica: entrenamiento hasta la fecha de corte, validación los 61 días siguientes, prueba el resto. Semilla 42. Artefacto en `datos/modelos/<model_id>/modelo.joblib` con `manifest.json` (SHA-256, `feature_version`, `data_cutoff`, métricas, hiperparámetros) y registro en `model_registry`. |

**Modelo activo que viaja en la entrega:** `hgb_fv2_20250831_s42`, con variables fv2: ruta ordinal, novedades
viales y víspera o día posterior a festivo. Se entrenó hasta el 31-08-2025, se validó en sep.-oct. y la prueba
reservada es nov.-dic. de 2025. En esa prueba su WAPE horario es **14,77 %** (IC95 13,10-16,87), frente a 15,07 % de
fv1 `hgb_fv1_20250831_s42` (que se conserva para la reversión), 21,18 % de la regla manual B1 y 26,40 % de B2. La
prueba se consultó al elegir fv2 frente a fv1, así que su cifra es informativa: el criterio de selección fue la
validación y los backtests con modelos congelados en 2024 y 2025, y se pide a Extreme un periodo de 2026 como prueba
limpia.

Cada predicción trae dos añadidos:
- la banda P10-P90 calibrada (`p10_modelo`/`p90_modelo` guardan la banda sin calibrar). La calibración vigente es la
  v2, conformal por bloque horario, versionada junto al modelo (`calibracion_v2.json`, con su SHA-256 en el
  manifiesto): en la prueba reservada cubre el 77,82 % (v1: 77,88 %) con un ancho medio de 303,4 pasajeros (v1: 312,9)
  (`docs/evidencias/modelo/calibracion_condicional.md`). `CALIBRACION_BANDA=v1` vuelve al conformal móvil por ruta, y
  cada predicción guarda qué versión usó (`calibracion_version`);
- la explicación local SHAP exacta (`explicacion_local`).

Las ventanas de 30/60/120 min se reparten con el perfil intrahorario de 2024.

Para reproducir:
- `scripts/entrenar.py --compuerta-activo --verificar-reproducible`;
- `scripts/evaluar_modelo.py` y `scripts/evaluar_horizontes.py`;
- el modelo por segmento y sentido: `scripts/entrenar_segmentos.py` y `scripts/evaluar_banda_ventanas_segmentos.py`
  (`docs/modelo_segmentos.md`).

Las evidencias y la decisión están en `docs/evidencias/modelo/` (`decision_fv2.md`).

La regla de gobierno de §5.1 se cumple guardando los umbrales en `ai_frecuencias.threshold_config`, con versión. Eso
incluye la tarifa, la elasticidad y la suavidad del plan del día (migración 0010), la flota y el tiempo de ciclo por
ruta (`PUT /api/v1/catalogos/flota`), la tolerancia de los datos tardíos de la calidad, las tolerancias del contraste
de los consolidados (migración 0013) y el mínimo de probabilidad de ALT-003 (migración 0014, en una versión propuesta
hasta que el área operativa la apruebe). Se cambian sin recompilar ni reiniciar, y el cálculo siguiente los usa
(`docs/gobierno_parametros.md`, `docs/consolidados_ciclo.md` y `docs/alertas_viajes_y_alt003.md`).

### Monitoreo, aprendizaje continuo, ONNX y segmentos

- **Monitoreo (§9.4, `GET /api/v1/monitoring`, exportable a CSV/XLSX).** Cada ejecución con datos nuevos guarda en
  `ai_frecuencias.model_monitoring` el WAPE, el MAE y el sesgo móviles de 28 días, la cobertura P10-P90 calibrada,
  la deriva (PSI de lag7, b8, m4, sd8, nivel_7_34, dia_lag7, objetivo y predicción frente a los 365 días de
  entrenamiento), el volumen de predicciones y el porcentaje de alertas descartadas, con estado ok, aviso o alerta.
  El WAPE móvil por ruta alimenta ALT-010.
  - `dia_lag7` se investigó (`docs/evidencias/monitoreo/psi_dia_lag7.json`). Dentro del propio año de entrenamiento,
    28 días contiguos ya dan un PSI de hasta 1,6, porque la variable es diaria y estacional. Por eso tiene un umbral
    calibrado con ese ruido y no dispara el reentrenamiento.
  - En sep-dic de 2025 hubo 4 semanas en ok y 10 en aviso, todas por sd8 con PSI de 0,10 a 0,14. El WAPE móvil fue
    de 12,6 a 16,0 % y la cobertura con la calibración v2, de 76,7 a 82,8 % (`monitoreo_2025.json`).
- **Foto de variables (§11.2).** `ai_frecuencias.feature_snapshot` guarda, por predicción y hora, el vector exacto
  que vio el modelo, con `feature_version` y `data_cutoff`, y además una fila por segmento y sentido de cada
  predicción con el modelo de segmentos activo (§7.3 paso 4; `FOTO_SEGMENTOS=false` las apaga). Esas filas van en su
  propio punto de guardado: si fallan, se omiten solo ellas. Está particionada por mes en UTC (§8.1); el volumen
  previsto está justificado en la migración 0004, y el de las filas por segmento, en
  `docs/evidencias/monitoreo/foto_segmentos.json`. Se consulta en `GET /api/v1/monitoring/feature-snapshots`.
- **Aprendizaje continuo (RF-018, RF-019, §9.5; `app/servicios/politica.py`, `GET /api/v1/monitoring/policy`).**
  - Cuándo se reentrena: por periodicidad (28 días de datos nuevos), por degradación (3 ejecuciones seguidas con WAPE
    móvil > `wape_max`), por deriva o por cobertura < 70 %. Los umbrales están versionados en `threshold_config`.
  - Con qué se entrena: el candidato usa el histórico validado (`demanda_observada`) hasta los datos disponibles, con
    corte = datos - 61 días, y nunca pisa al activo. Si ese corte no se puede entrenar (no hay datos suficientes antes de
    él, por ejemplo al comienzo de la serie), la política no encola el reentrenamiento: decide con la misma partición
    del entrenamiento y deja el motivo («reentrenamiento omitido: datos insuficientes antes del corte») en
    `metricas.monitoreo.politica.reentreno.bloqueos`, que sale en `GET /api/v1/monitoring/policy`.
  - La sombra: el candidato pasa 14 días prediciendo en paralelo. Después pasa la compuerta en esa ventana: WAPE ≤
    el del activo y ≤ `wape_max`, cobertura del 75 al 90 % y |sesgo| ≤ 5 %.
  - La decisión: la activación es auditada y se revierte sola si el modelo nuevo se degrada en sus primeros 7 días.
    El planificador semanal usa la misma política.
- **ONNX (§9.1, §9.2).** `scripts/exportar_onnx.py` exporta el fv2 (punto con nodo Exp, P10 y P90) y registra su
  SHA-256 en el manifiesto. `MOTOR_INFERENCIA=onnx` lo usa con ONNX Runtime.
  - Paridad: diferencia máxima de 0,003 pasajeros y el mismo WAPE con los dos motores.
  - Velocidad: unos 0,1 ms por fila, frente a 5-12 ms en scikit-learn (`onnx_paridad.json`).
- **Segmento y sentido (§3.1, §9.1, §9.3; `GET /api/v1/predictions/segmentos`).** Hay un modelo supervisado propio
  (`app/servicios/modelo_segmentos.py`; `docs/modelo_segmentos.md`). La fracción del sentido sale de un HGB Poisson por
  hora y sentido, y el reparto dentro del sentido, de otro HGB Poisson con el total de la ruta como exposición. Se
  entrena con las subidas de `timbradas_segmentos` (ene-feb 2023, `datos/subidas_segmento_hora.parquet`,
  `scripts/preparar_segmentos.py`), y la suma de los segmentos es la ruta.
  - El protocolo se fijó antes de mirar la prueba (`docs/evidencias/modelo/segmentos_protocolo.md`): entrenamiento del
    1-ene al 8-feb, validación del 9 al 17-feb y prueba del 18 al 27-feb-2023, que incluye el Carnaval. En la prueba,
    el WAPE por segmento y hora baja de 43,06 (reparto fijo B0, la línea base) a 42,09, y el del sentido no empeora
    (8,20 → 8,19) (`docs/evidencias/modelo/segmentos_modelo.md`); el IC95 de la diferencia por segmento es de −1,60 a
    −0,02 pp (`docs/evidencias/modelo/segmentos_banda_ventanas.json`).
  - La banda P10–P90 es conformal y se compone con la de la ruta. Con el total real cubre 78,31 % por segmento y
    83,40 % por sentido en filas de una hora, y de 76,0 a 76,8 % y de 80,2 a 80,5 % en ventanas de 2 y 3 horas
    (`segmentos_banda_ventanas.json`).
  - El artefacto activo es `seg_hgb_jerarquico_20230227_s42` (registro en `datos/modelos/segmentos/registro.json`, con
    el reparto fijo `seg_reparto_fijo_20230227` como línea base). Su manifiesto guarda el SHA-256 del artefacto y la
    huella del código (`codigo_sha256`): si `app/servicios/modelo_segmentos.py` cambia fuera de su docstring,
    `tests/datos_ml/test_segmentos_modelo.py::test_artefacto_activo_integro_y_registro_con_linea_base` falla y hay que
    reentrenar con `scripts/entrenar_segmentos.py`.
  - El sentido es una aproximación (la mitad del ciclo, supuesto S9), porque las exportaciones no lo traen.

### Ocupación por segmento (§10.1)

`timbradas_segmentos.pasajeros` no es la ocupación del bus (H9). La API deriva la carga a bordo de cada viaje de sus
subidas y bajadas por segmento, con el mismo método para el histórico y para el ciclo (`app/servicios/ocupacion.py`).
Método, cifras y limitaciones: `docs/ocupacion_segmentos.md`; evidencias en `docs/evidencias/ocupacion/`.

- **Histórico.** `datos/ocupacion_segmentos_hora.parquet` (lo arma `scripts/preparar_ocupacion_segmentos.py`) tiene la
  carga por segmento, día de operación y hora de salida. `POST /api/v1/recommendations/calculate` y cada hora de
  `GET /api/v1/recommendations/plan` traen `ocupacion_historica`: el segmento crítico, su sentido aproximado y su
  ocupación. El factor de carga crítica 2025 con que dimensiona el optimizador es ahora por ruta, día de la semana de
  operación y hora, con el tipo de día de respaldo.
- **Actual.** Con la fuente PostgreSQL, cada ciclo lee en solo lectura los viajes de las franjas que trajo la lectura
  incremental en las últimas 24 h de cada ruta y guarda la ocupación por segmento en `ai_frecuencias.ocupacion_segmento`
  (migración 0011); `metricas.ocupacion_segmentos` de la ejecución lo resume. ALT-002 observada se mide en el segmento
  crítico. El plan del día la recibe como restricción reactiva de seguridad, no como un pronóstico nuevo: si el
  segmento crítico de la última hora cerrada alcanza `ocupacion_critica`, la hora siguiente que todavía se puede
  programar no baja de las salidas que exige esa carga (`restriccion_reactiva` en la hora y `ocupacion_actual` en el
  día). Con la fuente Parquet no hay viajes por segmento y el ciclo sigue igual.
- **Cuándo actúa la restricción reactiva.** En los ciclos intradía que el planificador encola cada hora
  (`PLAN_INTRADIA_CRON`, por omisión `5 6-20 * * *`, solo con `FUENTE=postgres`) y en una ejecución con `instante` del
  día en curso (`POST /api/v1/frequency/executions`). Actúa en el plan del día en curso, en las recomendaciones de 30 y
  60 min de la hora en que actúa (con el piso acotado además por la flota con el ciclo) y en `POST
  /api/v1/predictions/run`, con la ocupación medida antes de su instante. En el ciclo diario (5:15), que calcula el plan
  del día siguiente, no actúa. ALT-002 se mide en el segmento crítico con la ocupación de este ciclo o la que guardó uno
  anterior. Su efecto depende de la latencia de la captura de Extreme (H10, H11).
  `scripts/backtest_ocupacion_reactiva.py` mide su efecto con los datos de 2023
  (`docs/evidencias/ocupacion/backtest_restriccion_reactiva.md`). El ciclo programado está en
  `docs/evidencias/ocupacion/planificador_intradia.txt` y su carga en la fuente, en
  `docs/evidencias/ocupacion/ciclo_intradia_fuente.md`.

## Limitaciones

- La base del reto es histórica (termina el 31-12-2025): la «llegada de datos nuevos» se simula con los días de 2025.
  En la réplica local, los datos llegan de verdad por el trigger de Extreme, pero con viajes reservados de esos años.
- El modelo de la API pronostica la hora y la reparte en la ventana pedida (30, 60 o 120 min) con el perfil intrahorario
  de 2024 y un factor intradía que solo usa horas ya cerradas. Los experimentos 11 y 12 del informe académico se
  evaluaron a 7 días, sobre todo 2025 y reentrenando cada mes; aquí son una referencia, y el 12 queda como opción del
  plan del día (`pronostico=E12`).
- El modelo por segmento y sentido solo tiene subidas por segmento de ene-feb 2023, porque los triggers de
  segmentación no se volvieron a ejecutar: su error en 2025 no se puede medir. El sentido es una aproximación, porque
  las exportaciones no lo traen. La banda por segmento cubre algo menos del 80 % (78 % por hora y 76 a 77 % en
  ventanas de 2 y 3 horas), y de punta a punta depende de la banda de la ruta. Las alertas se calculan por ruta y hora.
- La ocupación por segmento tiene el mismo límite de datos: el perfil histórico es de ene.–feb. 2023 y la estacionalidad
  de Sobusa es nula (H1). La restricción reactiva actúa en los ciclos intradía que programa `PLAN_INTRADIA_CRON`; cada
  uno lee la fuente (unos 3,1 s en la réplica, más sin los índices de H12). En tiempo real dispara mucho menos que con los viajes completos, porque un viaje dura unas 3,5 h, y su
  efecto depende de la latencia con que llegan los datos de la captura (H10, H11). Tiene falsas alarmas: en el
  backtest con los viajes completos, 292 de las 457 salidas que agregaría caen en horas que no quedaron sobre el
  umbral. El umbral, la ocupación objetivo del piso y la ventana de 2 h no están validados con el área operativa
  (`docs/evidencias/ocupacion/backtest_restriccion_reactiva.md`).
- La elasticidad β estimada ≈ 0,70 por observación (0,55–0,90) sale de fallas imprevistas, no de recortes planificados,
  y no está validada en campo. El plan del día usa 0,5 por prudencia; la sensibilidad está en
  `docs/evidencias/optimizacion/sensibilidad.md`, y el piloto la mide.
- La precisión de las alertas es aproximada: no hay incidentes etiquetados por Extreme. La muestra revisada dos veces
  (`docs/evidencias/alertas/revision_doble/`) la hicieron revisores automatizados; falta la del área operativa, que
  tiene listo un kit para revisarla a ciegas y sin red
  (`docs/evidencias/alertas/revision_doble/kit_humano/INSTRUCCIONES.md`).
- ALT-008 (consolidado anómalo) evalúa subidas, bajadas y número de viajes desde la migración 0013. Las franjas que el
  histórico ya tenía antes de esa migración quedan sin bajadas (la migración no lee la base de Extreme), salvo las de
  la ventana de solape que la primera lectura vuelve a entregar, y un día sin las bajadas de todas sus horas no evalúa
  ese campo.
- Las tablas por segmento de Extreme (`timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`) no tienen filas
  de Sobusa (H4): el ciclo las lee con su marca y lo dice en `metricas.calidad.consolidados` (`sin_filas_fuente`), pero
  su contraste por segmento solo está probado con datos sintéticos y con filas reales de la liquidación de tres viajes en
  una transacción que se revierte, no con datos de producción. El de `timbradas_consolidado` encuentra 11
  diferencias groseras que se ven en las tablas de Extreme (H17); se registran sin corregir nada
  (`docs/consolidados_ciclo.md`).
- ALT-003 se adoptó con la tasa base de las franjas donde puede emitirse (las que no tienen ALT-001): ahí su lift en la
  evaluación es 2,08 [1,51; 2,99]. Contra la tasa base de todas las franjas, su lift fue 0,90 en la validación y su
  intervalo en la evaluación incluye 1 (1,16 [0,82; 1,51]). La versión de `threshold_config` que siembra su mínimo
  (migración 0014) está propuesta, sin aprobar (`docs/alertas_viajes_y_alt003.md`).
- El viaje, el vehículo y el conductor de ALT-006 y ALT-009 dependen de una fuente de viajes (la base operacional, la
  réplica o la exportación `progvehiculos.parquet`): sin ella quedan vacíos y la alerta lo dice
  (`identificacion_5_3.resultado` = `fuente_sin_viajes`). Sin los índices propuestos 2 y 3
  (`docs/evidencias/replica/propuesta_indices.sql`), esa lectura recorre las tablas (H12).
- La partición por ruta (RNF-005) está hecha, pero el planificador sigue sin partir por omisión
  (`PLAN_PARTICION=ninguna`): cada trabajo de ruta paga sus costos fijos y su propia lectura y, sin los índices
  propuestos para Extreme (`docs/evidencias/replica/propuesta_indices.sql`), el SELECT de una ruta tarda lo mismo o
  más que el de todas (`docs/evidencias/cola/lectura_por_ruta_replica.txt`; límites medidos en
  `docs/particion_por_ruta.md`).
- Una consulta de `/segmentos/estadisticas` con un rango de fechas largo que no cubre todo el período vuelve a agregar
  el grano diario de ese rango; si los rangos largos pasan a ser el uso habitual, el paso siguiente es un grano mensual
  (`docs/segmentos_materializados.md`). Cada refresco de la agregación recorre `timbradas_segmentos`, que en la
  réplica no tiene índices por `fecha` ni por `ultimaactualizacion` (H12); desde la 0012, si la ventana de solape no
  trae cambios, termina `sin_cambios` sin releer fechas ni reescribir la agregación
  (`docs/evidencias/pruebas/segmentos_sin_cambios.json`).
- El headway vigente de `rutas.frecuenciadespachos` (5 en las tres rutas) se lee en minutos; la unidad es un supuesto
  (S14) que debe confirmar Extreme (H15).
- Las notificaciones son simuladas (quedan en `notification_log`) y la autenticación es por clave y rol, no con el
  directorio de la empresa. El reporte de unicidad de cada lote queda `pendiente_destinatario` hasta que Extreme
  defina al responsable del consolidado (`NOTIF_UNICIDAD_DESTINATARIOS`), y un reporte pendiente no se reenvía: los
  lotes siguientes salen al destinatario cuando se configure.
- Una novedad vial sin filas en `novedades_viales_ruta` se aplica a todas las rutas. Es un supuesto: la tabla está
  vacía en la base del reto y en la réplica, y lo debe confirmar Extreme. Si la tabla se llena, hay que regenerar el
  contexto y reentrenar; el ciclo no lo hace solo.
- Varios datos de Extreme tienen preguntas abiertas (H1 a H17 en `docs/hallazgos_extreme.md`; al final de ese
  documento, las de los supuestos de las novedades por ruta y del destinatario del reporte de unicidad). H17: el
  consolidado de Sobusa cuenta viajes con más de una estacionalidad y las bajadas de CL 72 no cuadran con las de los
  viajes válidos. H14: la espera máxima de §5.1 se lee como espera media del pasajero (headway máximo efectivo de
  10 min). H13: con la programación de hoy los buses en ruta superan la flota en algunas horas pico, y el plan D5
  admite hasta 35 salidas por hora (1,71 min) frente al headway mínimo gobernado de 2 min; esas horas salen «no
  viables» con su motivo.

El estado de cada requisito está en `../MATRIZ_CUMPLIMIENTO.md`, y lo que falta para producción, en
`../PLAN_EVOLUCION.md`.

## Documentación

| Documento | Para qué |
|---|---|
| `docs/manual_usuario.md` | Despachadores y analistas: pantallas del tablero, gestión de alertas, lectura de recomendaciones, API con `curl`, exportaciones y preguntas frecuentes. |
| `docs/manual_tecnico.md` | Mantenimiento: arquitectura, módulos, flujo de una ejecución, cola, ciclo de vida del modelo, alertas, optimizador, base de datos, observabilidad, seguridad, cómo extender y cómo probar. |
| `docs/despliegue.md` | Despliegue con Docker Compose, venv, réplica, dos réplicas y Jaeger; variables de entorno; respaldo y solución de problemas. |
| `docs/openapi.json` | Contrato OpenAPI 3.1 de la API (el mismo de `/openapi.json` y Swagger): 65 rutas y 69 operaciones, cada una con su rol mínimo (`x-rol-minimo`) y sus errores. |
| `docs/integracion_postgresql.md` | Integración con la base operacional: usuarios técnicos, mapa de tablas, marca de agua, no interferencia y EXPLAIN. |
| `docs/particion_por_ruta.md` | Partición del ciclo por ruta y fecha (RNF-005, migración 0009): madre y trabajos, marca de agua y candado por ruta, límites medidos. |
| `docs/segmentos_materializados.md` | Capa de segmentos (migración 0008): agregación materializada, trabajo `segmentos` de la cola, modos del refresco, refresco sin cambios con las huellas de la ventana de solape (migración 0012) y rendimiento. |
| `docs/gobierno_parametros.md` | Parámetros del plan, flota y ciclo gobernados en `threshold_config` (migración 0010) y headway vigente de `rutas.frecuenciadespachos`. |
| `docs/ocupacion_segmentos.md` | Ocupación por segmento, histórica y actual (§10.1, migración 0011): método, validación contra el dispositivo, uso en ALT-002 y en el plan del día (restricción reactiva), efecto medido y límites. |
| `docs/retencion_datos.md` | Retención de datos (§18, migración 0012): la política por tabla, los parámetros gobernados, la tarea programada y bajo demanda, la simulación y la bitácora. |
| `docs/consolidados_ciclo.md` | Consolidados de Extreme en el ciclo y bajadas en el histórico (§6.1, §6.3, §7.3 paso 3, §11.2, migración 0013): lectura con marca por tabla, calidad, contraste con la agregación propia, tolerancias gobernadas, resultado con la réplica y límites. |
| `docs/alertas_viajes_y_alt003.md` | Viaje, vehículo y conductor de las alertas (§5.3) y ALT-003 con su probabilidad mínima elegida sin fuga (migración 0014): qué campos aplican a cada regla, de dónde salen los viajes y cómo se eligió el mínimo. |
| `docs/modelo_segmentos.md` | Modelo por segmento y sentido: qué pronostica, cómo se eligió, banda P10–P90, dónde se usa y cómo se reentrena. |
| `docs/hallazgos_extreme.md` | Hallazgos H1 a H17 sobre los scripts, los datos, los parámetros operativos y el texto de la especificación, con la pregunta exacta para Extreme. |
| `docs/evidencias/README.md` | Índice de evidencias para el jurado. |
| `../documentos/mapeo_especificacion.md` | Cada frase de §1–§3 y §17–§20 de la especificación con su evidencia. |
| `../PLAN_EVOLUCION.md` | Plan de evolución (E12): integración, escalabilidad, costos, riesgos, hoja de ruta y adopción. |
| `../MATRIZ_CUMPLIMIENTO.md` | Estado de cada requisito de la especificación. |
