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
(monitoreo y foto de variables); las migraciones 0001 a 0007 están descritas en `docs/manual_tecnico.md`, sección 8.

| Módulo (`app/servicios/`) | Qué hace |
|---|---|
| `fuentes.py` | `FuenteParquet` (simula la llegada diaria de datos por fecha) y `FuentePostgresSoloLectura` (transacción `READ ONLY`, `statement_timeout`); ambas con `leer_incremental(marca_agua, hasta)`. |
| `calidad.py` | `validar_lote`: completitud, validez, unicidad, consistencia, oportunidad y relacional (§6.3); cada error con lote, fila, campo, código y detalle. |
| `datos.py` | Vista analítica `demanda_horaria` y catálogo de rutas (capacidad, ciclo, flota, frecuencia actual). |
| `inferencia.py` | Entrena, registra, carga (verifica el SHA-256 del artefacto), predice y evalúa (MAE, RMSE, WAPE por ruta, pico y valle). |
| `optimizacion.py` | `optimizar`: función objetivo de §10.2 (min α·costo_operativo + β·tiempo_espera + γ·sobreocupación + δ·desviación) como MILP de la franja con PuLP/CBC, sujeta a capacidad sobre el P90 calibrado, flota, headway mínimo y máximo y ciclo; pesos versionados en `threshold_config`; tipologías de capacidad de `tipologias_flota.json` (§10.1); comparación con la frecuencia programada, «qué pasa si» y sensibilidad (RF-008). `recomendar` es la línea base de §10.3 y `plan_dia_d5` el MILP D5 del día (`motor_d5/`). |
| `alertas.py` | Reglas ALT-001 a ALT-010, deduplicación y máquina de estados (reconocer, asignar, comentar, cerrar, descartar). |
| `notificaciones.py` | Adaptadores de correo y WhatsApp configurables; el envío es simulado y queda en `notification_log`. |
| `ejecucion.py` | Orquesta una ejecución como job con progreso y reintentos; todo queda ligado a `execution_id`, `model_id`, `feature_version`, versión de umbrales y `data_cutoff`. |
| `cola.py` | Cola de trabajos en PostgreSQL para N réplicas (RNF-005): reclamo con `SELECT … FOR UPDATE SKIP LOCKED`, reserva (*lease*) que vence y se renueva con un latido, reintento con espera exponencial, cierre con cerca (solo confirma quien aún tiene la reserva) y traza de cada intento en `execution_attempt`. Las de frecuencia van de una en una (marca de agua); los entrenamientos, en paralelo. |
| `ingesta.py` | Ingesta al histórico propio con `COPY` a una tabla de paso + un `INSERT … ON CONFLICT … WHERE … IS DISTINCT FROM`, en la misma transacción de la ejecución (RNF-003). |
| `planificador.py` | Planificador interno con APScheduler (§7.2): ejecución diaria y revisión de reentrenamiento con cron configurable; encola una sola fila por franja aunque haya N réplicas (`GET /api/v1/scheduler`). |
| `variables.py` | Variables del modelo por versión (fv1 y fv2), sin información posterior al instante de predicción. |
| `monitoreo.py` · `politica.py` | Monitoreo por ejecución (error móvil, cobertura, PSI, volumen y alertas descartadas), foto de variables y aprendizaje continuo: retador en sombra, compuerta, activación auditada y reversión automática. |
| `onnx_motor.py` | Motor de inferencia ONNX Runtime alternativo (`MOTOR_INFERENCIA=onnx`). |
| `catalogos.py` · `segmentos.py` | Catálogos de solo lectura (§3.1 «Gestión operacional») y capa analítica por segmento y zona (§6.1, §6.2). |
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

**Prueba reproducible del despliegue (RNF-008, RNF-001; 9-11-2026)**, en un proyecto Compose aislado
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
| `FUENTE_DATABASE_URL` | vacía | Solo con `FUENTE=postgres`: usuario con privilegios `SELECT`. |
| `FUENTE_STATEMENT_TIMEOUT_MS` | 30000 | Límite de cada consulta a la fuente. |
| `DATA_DIR` | `./datos` | Carpeta con los Parquet y JSON del proyecto. |
| `ENTORNO`, `DOCS_HABILITADOS` | `local`, `true` | Swagger restringido por ambiente. |
| `MAX_REINTENTOS`, `REANUDAR_EJECUCIONES` | 3, `true` | Reintentos de cada etapa y reanudación de ejecuciones tras un reinicio. |
| `LOG_NIVEL`, `TZ` | `INFO`, `America/Bogota` | Logs JSON y zona de presentación (en la base todo va en UTC). |
| `NOTIFICACIONES_CANALES`, `NOTIFICACIONES_SEVERIDAD` | vacío (ninguno), `critica` | Canales simulados (`correo,whatsapp`) y severidad mínima que se notifica. |
| `NOTIF_CORREO_DESTINATARIOS`, `NOTIF_CORREO_REMITENTE`, `NOTIF_WHATSAPP_NUMEROS` | vacíos | Destinatarios (se enmascaran en los logs). No hay credenciales de envío: el envío es simulado. |
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
.venv\Scripts\python -m scripts.replica_contexto                         (contexto del modelo leído de la base)
REPLICA_PRUEBAS_ESCRITURA=1 .venv\Scripts\python -m pytest tests\replica  (incluye las pruebas que escriben en la réplica)
```

Detalle, controles de no interferencia con su prueba y rendimiento: `docs/integracion_postgresql.md`; hallazgos y
preguntas para Extreme: `docs/hallazgos_extreme.md`.

## Seguridad, resiliencia y observabilidad

- **Autenticación (§7.2).** Cada ruta de `/api/v1` exige la cabecera `X-API-Key`. Sin clave o con una clave inválida
  responde 401 (`no_autenticado`, con `WWW-Authenticate`); con un rol insuficiente, 403 (`prohibido`). Los roles son
  acumulativos. `operador` lee todo y cambia el estado de las alertas. `analista` además lanza ejecuciones,
  predicciones, recomendaciones y entrenamientos. `admin` además activa o revierte modelos y cambia umbrales y la
  capacidad. La
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
  HMAC-SHA256 con `SEUDONIMO_SECRETO`, y la base rechaza un valor en claro con un CHECK.
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
`desplazamiento`, se ordenan con `orden` y se filtran por sus campos. Las exportaciones aceptan `formato=csv|xlsx` y
responden con `X-Total-Count` (registros que cumplen el filtro) y `X-Truncado` (`true` si el archivo se cortó en el
tope de 100.000 filas).
El contrato completo (OpenAPI 3.1: 59 rutas y 62 operaciones) está en `docs/openapi.json` y en Swagger (`/docs`, fuera de
producción). Cada operación de `/api/v1` declara su rol mínimo en `x-rol-minimo` y los errores que de verdad puede
devolver, todos con el formato uniforme: 400 `cuerpo_ilegible` (cuerpo que no se puede decodificar), 401
`no_autenticado`, 403 `prohibido` (con `rol_requerido`), 404, 409, 422 `validacion` (con `tipo` = `caracter_nulo` si
algún valor trae el byte NUL) o `fuera_de_rango` (por ejemplo, `hasta=9999-12-31`), 500 y, en las lecturas que dependen
de una fuente externa, 503. Detalle en `docs/manual_tecnico.md`, sección 2.4.

**Ejecuciones y planificador**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| POST | `/api/v1/frequency/executions` | analista | Lanza una ejecución como job (lectura incremental → calidad → histórico → predicción → recomendación → alertas → notificaciones → plan del día siguiente y foto de la respuesta del reto); responde 202 con el `execution_id`. |
| GET | `/api/v1/frequency/executions` | operador | Ejecuciones, paginadas y filtradas. |
| GET | `/api/v1/frequency/executions/{execution_id}` | operador | Estado, etapa y progreso, corte de datos, marcas de agua, métricas y errores. |
| GET | `/api/v1/frequency/executions/{execution_id}/errors` | operador | Errores de calidad por lote, fila, llave del registro, campo, valor, código, dimensión y si bloquea; filtrables por `idruta`. |
| GET | `/api/v1/scheduler` | operador | Planificador interno: próximas ejecuciones, últimas franjas encoladas y estado de la cola. |

**Pronósticos**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| POST | `/api/v1/predictions/run` | analista | Pronóstico de una ruta y un horizonte (30, 60 o 120 min) con banda P10–P90, explicación y la recomendación de la franja. Trae además las claves del ejemplo de §12.3 (`predictionId`, `routeId`, `generatedAt`, `horizonMinutes`, `predictedPassengers`, `confidenceInterval`, `modelVersion`, `recommendation`, `explanation`). |
| GET | `/api/v1/predictions` | operador | Pronósticos guardados, con filtros (ruta, fechas, horizonte, modelo), paginación y orden. |
| GET | `/api/v1/predictions/{prediction_id}` | operador | Una predicción con su trazabilidad (`model_id`, `feature_version`, `data_cutoff`, latencia y explicación local). |
| GET | `/api/v1/predictions/export` | operador | Los mismos filtros, en CSV o XLSX. |
| GET | `/api/v1/predictions/segmentos` | operador | Pronóstico por segmento y sentido: desagregación documentada del pronóstico de la ruta. |

**Recomendaciones**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| POST | `/api/v1/recommendations/calculate` | analista | Headway, buses por hora y vehículos con la función objetivo de §10.2: restricciones activas, límites que mandan, tipologías, línea base de §10.3, comparación con la frecuencia programada y, si se piden, `escenario` y `sensibilidad`. Una franja inviable sale `viable = false` con su motivo. |
| GET | `/api/v1/recommendations` | operador | Recomendaciones guardadas, con filtros. |
| GET | `/api/v1/recommendations/export` | operador | Los mismos filtros, en CSV o XLSX. |
| GET | `/api/v1/recommendations/plan` | operador | Plan D5 del día por hora (`ruta` y `fecha`) con el pronóstico del modelo activo, persistido por el ciclo diario: salidas, headway, vehículos, costo, límites que mandan, viabilidad con su motivo y comparación con lo programado. Cada hora trae `sin_intervalo` (una sola salida: el headway mínimo no aplica), `flota_disponible` y `costo_hora_cop`; el día trae `vehiculos_hora_pico` (⌈ciclo / headway⌉ de §10.3), `buses_en_ruta_pico` (buses en ruta a la vez, el conteo que limita la flota) y `definicion_vehiculos`, que explica las dos. 404 `sin_calcular` si el plan de esa fecha no está calculado. `pronostico=E12` usa el pronóstico precalculado de 2025 del experimento 12. |
| GET | `/api/v1/respuesta` · `/api/v1/respuesta/export` | operador | Respuesta a la pregunta final del reto (§20) en un solo lugar, por ruta (`ruta` y `fecha` opcionales), leída de la foto persistida: cada cuánto despachar por hora y franja frente a lo programado, con su viabilidad; pasajeros esperados con P10–P90; vehículos en ruta frente a la flota; balance de flota y recaudo; alertas abiertas, críticas primero. 404 `sin_calcular` si no hay foto para esa fecha con el modelo y los umbrales vigentes. La exportación da una fila por ruta y hora en CSV o XLSX. Evidencia en `docs/evidencias/respuesta/`. |
| POST | `/api/v1/respuesta/calcular` | analista | Calcula la foto de la respuesta para una fecha (y rutas) como trabajo de la cola: responde 202 con el `execution_id`; si ya hay un cálculo igual en cola o corriendo, devuelve ese. |

**Alertas**

| Método | Ruta | Rol | Para qué |
|---|---|---|---|
| GET | `/api/v1/alerts` | operador | Alertas por estado, severidad, ruta, código, fecha y lugar (`cerca_de=lat,lon` y `radio_m`, máximo 50 km: `ST_DWithin` sobre `geography` con índice GiST), con todos los campos de §5.3: origen, tendencia con su pendiente, serie reciente, probabilidad y método del puntaje, variables influyentes y ubicación. |
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
| PUT | `/api/v1/thresholds` | admin | Cambia umbrales o pesos: crea una versión nueva del conjunto, como propuesta. |
| POST | `/api/v1/thresholds/{version}/aprobar` | admin | El área operativa aprueba una versión: firma `aprobado_por` y `aprobado_en` (§5.1). |
| GET | `/api/v1/thresholds/history` | operador | Histórico de versiones de los umbrales. |
| GET | `/api/v1/monitoring` | operador | Monitoreo por ejecución: deriva (PSI), error móvil, cobertura, volumen y alertas descartadas. |
| GET | `/api/v1/monitoring/export` | operador | El monitoreo filtrado, en CSV o XLSX. |
| GET | `/api/v1/monitoring/policy` | operador | Política de aprendizaje continuo: si toca reentrenar, retadores en sombra y umbrales. |
| GET | `/api/v1/monitoring/feature-snapshots` | operador | Foto de variables (§11.2) por ejecución, predicción o ruta, con fecha de corte y versión. |

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
| GET | `/api/v1/segmentos/estadisticas` | operador | Promedio, máximo y mínimo de subidas, bajadas y pasajeros por segmento, estacionalidad, día y hora (§6.1). |
| GET | `/api/v1/segmentos/estadisticas/export` | operador | Las mismas estadísticas, en CSV o XLSX. |
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
2. **Lectura incremental.** `POST /frequency/executions` lee solo lo posterior a la marca de agua de la última
   ejecución exitosa, con una ventana de solape y una huella de contenido, así que una fila tardía o modificada se
   entrega una sola vez. Repetir la ejecución no duplica nada.
3. **Evaluación del error.** Los pronósticos se comparan con lo observado (WAPE, MAE, RMSE y sesgo, por ruta, pico y
   valle) y el monitoreo actualiza el error móvil. Si supera la tolerancia, se emite ALT-010.
4. **Modelo candidato.** `POST /models/train` entrena con los datos validados hasta el nuevo corte (semilla 42) y lo
   registra como candidato con su artefacto, SHA-256, métricas y fecha de corte. Nunca pisa al activo. Con
   `reentreno_en_ciclo` = 1, la propia política encola ese entrenamiento cuando toca (por ejemplo, por periodicidad), y
   la demostración espera ese trabajo en vez de pedir otro igual.
5. **Comparación con el activo** en la misma ventana, posterior a todo lo que vieron los dos modelos, sin mezclar
   futuro y pasado. Con `datos_hasta`, el candidato pasa además 14 días en sombra prediciendo en paralelo.
6. **Activación o rechazo.** Al cerrar la sombra decide la compuerta de cuatro criterios (`politica.compuerta`), la
   misma de `POST /models/{id}/activate`: WAPE ≤ el del activo y ≤ `wape_max`, cobertura P10–P90 en [75 %, 90 %] y
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
`docs/evidencias/demo_ciclo_8nov.txt`.

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

| Nivel (§14.1) | Carpeta | Qué cubre |
|---|---|---|
| Unitarias | `tests/unit/` | Reglas de negocio, fórmulas de §10.2 y §10.3, validaciones de calidad, estados de alertas, cola, circuito, seguridad, monitoreo, política y ONNX. |
| Integración | `tests/integracion/` | API con TestClient, migraciones, repositorios, roles, exportaciones, alertas observadas y monitoreo, contra el PostgreSQL local. `PRUEBA_CAIDA=1` agrega la prueba de caída con procesos reales, y `PRUEBA_PLANIFICADOR=1`, la ejecución programada de §14.2 (el planificador encola las franjas sin ningún POST). |
| Testcontainers | `tests/testcontainers/` | PostGIS 14-3.4 efímero: Alembic desde cero (upgrade, downgrade y upgrade), repositorios y API. Corre con `TESTCONTAINERS=1`. |
| Contrato | `tests/contrato/` | Cada operación del OpenAPI con autenticación: código documentado, esquema, errores uniformes 401/403/404/422, compatibilidad con `docs/openapi.json` y Schemathesis acotado para cazar errores 5xx. |
| Datos/ML | `tests/datos_ml/` | Rangos y NaN de las variables, PSI, no regresión del WAPE en la prueba reservada frente al manifiesto y a B1/B2, y fuga temporal en 3 cortes. |
| Réplica | `tests/replica/` | Contra la réplica de la base operacional (puerto 5434): roles, carga, scripts de Extreme, llegada por el trigger, EXPLAIN y capa de segmentos. Sin réplica se omiten con su motivo. |
| Carga | `k6/consultas.js`, `k6/consultas_durante_ingesta.js`, `k6/en_frio.js` | Consultas paginadas concurrentes, consultas durante una ingesta y la primera petición a cada ruta con la API recién arrancada, con la clave en `SOBUSA_API_KEY`. `scripts/sembrar_volumen.py` siembra un año de resultados en una base local aparte, replicando filas reales con identificadores nuevos (`docs/evidencias/rendimiento.txt` y `docs/evidencias/pruebas/k6_volumen.txt`). |

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
| Consultas paginadas con k6 (RNF-002) | 3.553 peticiones, 0,00 % de errores, p95 de 451,3 ms (umbral: 2 s) | `docs/evidencias/rendimiento.txt` |
| Las mismas consultas con un año de resultados (RNF-002, volumen acordado) | 2.873 peticiones con 50 usuarios, 0,00 % de errores, p95 de 627,5 ms. En frío, 17 de 22 rutas responden en menos de 100 ms; `GET /segmentos/estadisticas` pasa de 2 s (8,8 s en frío y 11,9 s en caliente), igual que la primera petición a `/catalogos/segmentos` (5,0 s) y las exportaciones CSV completas (3,4 a 5,2 s) | `docs/evidencias/pruebas/k6_volumen.txt` |
| Ciclo diario completo (RNF-004) | Carga inicial en 24,1 s y un día nuevo en 21,4 s, con el plan del día, la foto de la respuesta y la serie de la ruptura; la repetición, en 0,1 s | `docs/evidencias/rendimiento/ciclo_final.md` |
| Ingesta de 111.792 filas con `COPY` (RNF-003) | 4,07 s de ingesta y 53 MiB de memoria pico; la recarga idéntica no cambia nada | `docs/evidencias/rendimiento.txt` |
| Dos réplicas de la API (RNF-005) | 20 ejecuciones repartidas 10/10, 0 duplicados | `docs/evidencias/cola/replicas.txt` |
| Caídas con `docker kill` (RNF-001) | Los tres casos terminan `ok`, sin perder ni duplicar | `docs/evidencias/cola/caida_rnf001_docker.txt` |
| No interferencia con la base de Extreme (§11.3) | 0 escrituras indebidas permitidas en 36 intentos | `docs/evidencias/replica/replica_roles.txt` |
| Lectura incremental con llegada real por el trigger | Tras la llegada, de 1.263 filas leídas en la ventana se entrega exactamente 1 franja nueva | `docs/evidencias/replica/replica_llegada.txt` |
| Trazas de una ejecución (RNF-006) | Una sola traza con 39 spans en Jaeger | `docs/evidencias/seguridad/jaeger_resumen.txt` |
| Banda P10–P90 con la calibración v2 (prueba reservada) | Cobertura de 77,82 % (v1: 77,88 %) con un ancho medio de 303,4 pasajeros (v1: 312,9) | `docs/evidencias/modelo/calibracion_condicional.md` |
| Volumen de alertas (§18 «Alertas excesivas»), 15-09 a 31-12-2025 | 1,238 alertas observadas por ruta y día en total (con la ALT-002 observada, 0,691, y la ruptura de RF-009, 0,012); solo ALT-005 a ALT-009, 0,534, frente a 6,08 con las reglas anteriores. Con las de pronóstico, 2,399 por ruta y día | `docs/evidencias/alertas/backtest_alertas.md` |
| Revisión doble de 96 alertas (§18) | Kappa de 0,943 entre los dos revisores (automatizados) antes de conciliar; precisión reponderada de 0,839 (intervalo 95 %: 0,757–0,882) | `docs/evidencias/alertas/revision_doble/conciliacion.json` |
| Contrato OpenAPI (§12.1, §14.1) | Schemathesis con cinco chequeos en cada operación, sin fallas; 0 xfail | `docs/evidencias/contrato/schemathesis.txt` |
| Alertas de pronóstico por hora, mismo periodo | ALT-001 0,435, ALT-002 0,315, ALT-003 0,380 y ALT-004 0,031 por ruta y día (1,161 en total), con lift de 1,77, 2,01, 0,75 y 7,62 | `docs/evidencias/alertas/backtest_alertas_pronostico.md` |
| Suite completa final (unitarias, integración, réplica, contrato y datos/ML) | 1.060 casos: 1.055 aprobados, 0 fallas, 0 errores y 5 omitidas a propósito (`PRUEBA_CAIDA=1`, `PRUEBA_PLANIFICADOR=1` y 3 de `REPLICA_PRUEBAS_ESCRITURA=1`) | `docs/evidencias/pruebas/suite_final.xml` (la misma corrida que importa SonarQube) |
| Cobertura de `app/` (incluido `motor_d5/`) en esa suite | 94,27 % (10.566 de 11.208 líneas; mínimo exigido en el CI y en la puerta de SonarQube: 85 %) | `docs/evidencias/pruebas/coverage_final.xml` |
| Despliegue desde cero (RNF-008) | `scripts/verificar_despliegue.py` (9-11-2026, 08:27–08:32): «Resultado global: OK» en 5,7 min (arranque, migraciones 0001 → 0007, claves por rol, demostración de §14.2, reinicios sin pérdidas y limpieza) | `docs/evidencias/despliegue/arranque_limpio.txt` |
| Análisis con SonarQube (RNF-013) | Puerta «Reto Sobusa v1.5» **aprobada (OK)** en el análisis del 9-11-2026, 12:49, sobre todo el código: 0 vulnerabilidades, 0 bugs, 0 hallazgos bloqueantes y 0 críticos, duplicación de 0,0 % y cobertura de 94,3 %; 1 hallazgo de mantenibilidad aceptado con su justificación (la copia literal del solver D5, app/servicios/motor_d5/milp.py) | `docs/evidencias/sonarqube/quality_gate.json` (condición por condición en `resumen.md`) |

El mapeo de las secciones §1–§3 y §17–§20 de la especificación a esta evidencia está en
`../documentos/mapeo_especificacion.md`.

## Datos y modelos

| Qué | De dónde sale |
|---|---|
| Demanda por ruta, día y hora 2023-2025 (`datos/demanda_horaria.parquet`) | Exportación de la base del reto: suma de `numeropasajeros` de los viajes válidos de `progvehiculos` por hora de salida (`experimentos/E1_lgbm_salida`). Procedencia en `datos/origen.json`. |
| Pronósticos 2025 de los experimentos del informe académico (`datos/pronosticos_2025.parquet`) | B1 regla manual (WAPE 20,04 %), experimento 1 LightGBM (14,40 %), experimento 11 LightGBM mejorado (13,94 %) y experimento 12 híbrido (13,62 %): a 7 días de antelación, sobre todo 2025 y reentrenando cada mes. No son cifras del modelo de la API: en la misma ventana (2025) y frente a la misma B1, el modelo de la API congelado al 31-12-2024 da 14,48 % (`docs/evidencias/modelo/evaluacion_modelo.md`). El experimento 12 queda como opción del plan del día (`pronostico=E12`). |
| Insumos del optimizador D5 (`datos/insumos_d5_2025.parquet`) y costos con fuente (`datos/costos_fuente.json`) | Experimento D5 y estudio de costos del proyecto (precios 2026). |
| Catálogo de rutas (`datos/catalogo_rutas.json`) | Tabla `rutas` y medianas de día laboral de `experimentos/D1_optimizacion/parametros_operativos.parquet`; capacidad 50 por bus. |
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
- `scripts/evaluar_modelo.py` y `scripts/evaluar_horizontes.py`.

Las evidencias y la decisión están en `docs/evidencias/modelo/` (`decision_fv2.md`).

La regla de gobierno de §5.1 se cumple guardando los umbrales en `ai_frecuencias.threshold_config`, con versión: se
cambian sin recompilar.

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
  que vio el modelo, con `feature_version` y `data_cutoff`. Está particionada por mes en UTC (§8.1); el volumen
  previsto está justificado en la migración 0004. Se consulta en `GET /api/v1/monitoring/feature-snapshots`.
- **Aprendizaje continuo (RF-018, RF-019, §9.5; `app/servicios/politica.py`, `GET /api/v1/monitoring/policy`).**
  - Cuándo se reentrena: por periodicidad (28 días de datos nuevos), por degradación (3 ejecuciones seguidas con WAPE
    móvil > `wape_max`), por deriva o por cobertura < 70 %. Los umbrales están versionados en `threshold_config`.
  - Con qué se entrena: el candidato usa el histórico validado (`demanda_observada`) hasta los datos disponibles, con
    corte = datos - 61 días, y nunca pisa al activo.
  - La sombra: el candidato pasa 14 días prediciendo en paralelo. Después pasa la compuerta en esa ventana: WAPE ≤
    el del activo y ≤ `wape_max`, cobertura del 75 al 90 % y |sesgo| ≤ 5 %.
  - La decisión: la activación es auditada y se revierte sola si el modelo nuevo se degrada en sus primeros 7 días.
    El planificador semanal usa la misma política.
- **ONNX (§9.1, §9.2).** `scripts/exportar_onnx.py` exporta el fv2 (punto con nodo Exp, P10 y P90) y registra su
  SHA-256 en el manifiesto. `MOTOR_INFERENCIA=onnx` lo usa con ONNX Runtime.
  - Paridad: diferencia máxima de 0,003 pasajeros y el mismo WAPE con los dos motores.
  - Velocidad: unos 0,1 ms por fila, frente a 5-12 ms en scikit-learn (`onnx_paridad.json`).
- **Segmento y sentido (§9.1, §9.3; `GET /api/v1/predictions/segmentos`).** Es una desagregación del pronóstico de la
  ruta, no un modelo por segmento: usa el reparto de subidas de `timbradas_segmentos` (ene-feb 2023,
  `scripts/preparar_segmentos.py`), y la suma de los segmentos es la ruta.
  - Error del reparto en feb-2023 (enero como referencia): WAPE de 41 % por segmento y hora, y de 8 a 9 % por
    sentido y hora. El sesgo absoluto mediano por segmento va de 9 a 11 % (`desagregacion_segmentos.json`).
  - El sentido es una aproximación (la mitad del ciclo), porque las exportaciones no lo traen.

## Limitaciones

- La base del reto es histórica (termina el 31-12-2025): la «llegada de datos nuevos» se simula con los días de 2025.
  En la réplica local, los datos llegan de verdad por el trigger de Extreme, pero con viajes reservados de esos años.
- El modelo de la API pronostica la hora y la reparte en la ventana pedida (30, 60 o 120 min) con el perfil intrahorario
  de 2024 y un factor intradía que solo usa horas ya cerradas. Los experimentos 11 y 12 del informe académico se
  evaluaron a 7 días, sobre todo 2025 y reentrenando cada mes; aquí son una referencia, y el 12 queda como opción del
  plan del día (`pronostico=E12`).
- El pronóstico por segmento y sentido es una desagregación del de la ruta, no un modelo propio, y el sentido es una
  aproximación porque las exportaciones no lo traen. Las variables y las alertas se calculan por ruta y hora.
- La elasticidad β estimada ≈ 0,70 por observación (0,55–0,90) sale de fallas imprevistas, no de recortes planificados,
  y no está validada en campo. El plan del día usa 0,5 por prudencia; la sensibilidad está en
  `docs/evidencias/optimizacion/sensibilidad.md`, y el piloto la mide.
- La precisión de las alertas es aproximada: no hay incidentes etiquetados por Extreme. La muestra revisada dos veces
  (`docs/evidencias/alertas/revision_doble/`) la hicieron revisores automatizados; falta la del área operativa.
- ALT-008 (consolidado anómalo) evalúa las subidas y el número de viajes, no las bajadas: el histórico validado no las
  guarda.
- La marca de agua es una sola: las ejecuciones de frecuencia se serializan, y `rutas` limita la predicción, no la
  lectura (RNF-005, `../PLAN_EVOLUCION.md`, sección 2).
- `GET /api/v1/segmentos/estadisticas` agrega en cada petición la tabla de segmentos de la réplica, sin caché: tarda
  8,8 s en frío y 11,9 s en caliente (2,3 a 2,9 s con `idruta`), por encima de los 2 s de RNF-002
  (`docs/evidencias/pruebas/k6_volumen.txt`). Necesita una caché con vencimiento o una agregación materializada. Las
  consultas paginadas de resultados sí cumplen con un año de datos.
- Las notificaciones son simuladas (quedan en `notification_log`) y la autenticación es por clave y rol, no con el
  directorio de la empresa.
- Varios datos de Extreme tienen preguntas abiertas (H1 a H16 en `docs/hallazgos_extreme.md`). H14: la espera máxima
  de §5.1 se lee como espera media del pasajero (headway máximo efectivo de 10 min). H13: con la
  programación de hoy los buses en ruta superan la flota en algunas horas pico, y el plan D5 admite hasta 35 salidas
  por hora (1,71 min) frente al headway mínimo gobernado de 2 min; esas horas salen «no viables» con su motivo.

El estado de cada requisito está en `../MATRIZ_CUMPLIMIENTO.md`, y lo que falta para producción, en
`../PLAN_EVOLUCION.md`.

## Documentación

| Documento | Para qué |
|---|---|
| `docs/manual_usuario.md` | Despachadores y analistas: pantallas del tablero, gestión de alertas, lectura de recomendaciones, API con `curl`, exportaciones y preguntas frecuentes. |
| `docs/manual_tecnico.md` | Mantenimiento: arquitectura, módulos, flujo de una ejecución, cola, ciclo de vida del modelo, alertas, optimizador, base de datos, observabilidad, seguridad, cómo extender y cómo probar. |
| `docs/despliegue.md` | Despliegue con Docker Compose, venv, réplica, dos réplicas y Jaeger; variables de entorno; respaldo y solución de problemas. |
| `docs/openapi.json` | Contrato OpenAPI 3.1 de la API (el mismo de `/openapi.json` y Swagger): 59 rutas y 62 operaciones, cada una con su rol mínimo (`x-rol-minimo`) y sus errores. |
| `docs/integracion_postgresql.md` | Integración con la base operacional: usuarios técnicos, mapa de tablas, marca de agua, no interferencia y EXPLAIN. |
| `docs/hallazgos_extreme.md` | Hallazgos H1 a H16 sobre los scripts, los datos, los parámetros operativos y el texto de la especificación, con la pregunta exacta para Extreme. |
| `docs/evidencias/README.md` | Índice de evidencias para el jurado. |
| `../documentos/mapeo_especificacion.md` | Cada frase de §1–§3 y §17–§20 de la especificación con su evidencia. |
| `../PLAN_EVOLUCION.md` | Plan de evolución (E12): integración, escalabilidad, costos, riesgos, hoja de ruta y adopción. |
| `../MATRIZ_CUMPLIMIENTO.md` | Estado de cada requisito de la especificación. |
