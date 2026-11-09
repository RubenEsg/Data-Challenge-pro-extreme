# Manual de despliegue · API de frecuencias Sobusa

Este manual cubre la instalación, la configuración y la operación del backend (FastAPI + PostgreSQL 14/PostGIS) en
los cuatro modos previstos: local con el venv, Docker Compose (aplicación y PostgreSQL), Docker con la réplica de la
base operacional de Extreme (modo integrado) y dos réplicas de la API sobre la misma cola. Responde a la
especificación v1.5: RNF-008 (ejecución reproducible con Docker Compose), RNF-001 (recuperación ante reinicios),
§14.2 «Instalación» y «Demostración», E09 (Dockerfile, Docker Compose y configuración por variables de entorno) y la
parte de despliegue de E10.

Las pruebas de despliegue se corrieron en el equipo de desarrollo (Windows 11, Docker Desktop 29.7.2, Docker Compose
5.5.1) y su evidencia está en `docs/evidencias/despliegue/`. Los modos de dos réplicas y Jaeger se validan aquí con
`docker compose config`; la prueba con dos réplicas y la caída de una está en `docs/evidencias/cola/`. Los comandos
de respaldo de la sección 7 no forman parte de la prueba automática.

| Evidencia | Qué muestra |
|---|---|
| `arranque_limpio.txt` | Pila creada desde cero en un proyecto aislado: tiempos de construcción, migración, `/health` y resumen de cada comprobación |
| `migraciones.txt` | `alembic upgrade head` sobre un volumen nuevo (0001 → head), versión, tablas, partición y el índice GiST |
| `demo_ciclo_api.txt` | La demostración de §14.2 en la pila Docker creada desde cero, con sus seis pasos numerados (también en `docs/evidencias/demo_ciclo.txt`). `verificar_despliegue.py` lo reescribe en cada corrida |
| `demo_esperado.md` | Qué tiene que mostrar cada paso de esa demostración y por qué esas fechas, con la salida de referencia contra la API en el venv (sección 8) |
| `reinicio.txt` | RNF-001: SIGKILL y reinicio ordenado de la API a mitad de una ejecución, sin perder ni duplicar nada |
| `imagen.txt` | Tamaño de la imagen, usuario sin privilegios, capas y ausencia de herramientas de desarrollo |
| `construccion_sin_cache.txt` | La primera construcción sin caché (todas las dependencias como ruedas binarias de CPython 3.11) |
| `modo_integrado.txt` | La API en contenedor contra la réplica: lee como `lector_ia` (solo lectura) y escribe como `escritor_ia` |
| `pytest_despliegue.txt` | La suite completa del 9-11-2026 a las 03:43, justo después de separar las dependencias: 0 fallas y 0 errores con las dependencias nuevas. La corrida vigente de la suite está en `docs/evidencias/README.md`, «Cifras vigentes» |
| `actualizacion_pila_en_vivo.txt` | La actualización de la pila en uso (`sobusa_api`) sin recrear su base: migraciones aditivas e imagen nueva |
| `verificacion_manuales.txt` | Contra la API en el venv (sección 3.2, `uvicorn`, 9-11-2026 a las 04:51), los comandos nuevos de los manuales: códigos de error, `x-rol-minimo`, filtro por lugar de las alertas y la respuesta del reto |

Una corrida anterior de la demostración contra la API en el venv, de las 05:08 y con la línea de tiempo de entonces,
pasó a `docs/evidencias/historial/demo_ciclo_api_uvicorn_9nov_0508.txt`; la reemplazan `demo_ciclo_api.txt` y
`demo_esperado.md`.

La prueba completa se repite con un solo comando (sección 8): `python scripts/verificar_despliegue.py`.

## 1. Requisitos

- Docker Desktop (Windows o macOS) o Docker Engine con el plugin `compose` v2 (Linux). Se probó con Docker 29.7.2 y
  Compose 5.5.1, contenedores Linux. La imagen usa unos 1,5 GB de disco (ver `imagen.txt`).
- Puertos libres del equipo (todos configurables): **8000** (API), **5433** (PostgreSQL de resultados), **5434**
  (réplica operacional, opcional), **8302** (API en modo integrado, opcional), **16686** (Jaeger, opcional).
- Sin Docker: Python 3.11 o más reciente y un PostgreSQL 14 con PostGIS 3.4 (el servicio `db` de Compose sirve).
- Dependencias: `requirements.txt` trae solo lo que corre (lo que instala la imagen) y `requirements-dev.txt` agrega
  pruebas, análisis estático y herramientas de documentación (`-r requirements.txt` incluido). Las dos con versiones
  exactas. `requisitos_congelados.txt` es el `pip freeze` de la imagen construida (lo regenera
  `scripts/verificar_despliegue.py`).

## 2. Variables de entorno

Todas viven en `.env.example` (plantilla versionada, sin secretos reales). El `.env` real no se versiona
(`.gitignore`) ni viaja en el paquete de entrega. En Docker Compose, la API recibe las del `.env` (o del archivo que
indique `API_ENV_FILE`) y `docker-compose.yml` fija explícitamente las que dependen del contenedor (`DATABASE_URL`,
`DATA_DIR`, `TZ`). «Secreto» = no debe aparecer en el repositorio, en logs ni en capturas.

**Base de datos y puertos**

| Variable | Para qué | Por omisión | Secreto |
|---|---|---|---|
| `POSTGRES_DB`, `POSTGRES_USER` | Base y usuario del servicio `db` | `ai_frecuencias`, `sobusa` | No |
| `POSTGRES_PASSWORD` | Clave del servicio `db` (obligatoria; Compose se niega a arrancar sin ella) | — | **Sí** |
| `DATABASE_URL` | Base de resultados (esquema `ai_frecuencias`). En Compose se arma sola con `db:5432`; en el venv va en el `.env` (sin ella la API se detiene con un mensaje que remite a `.env.example`) | sin valor en el código | **Sí** (lleva la clave) |
| `DB_PUERTO_HOST`, `API_PUERTO_HOST` | Puertos publicados en el equipo | 5433, 8000 | No |
| `API_ENV_FILE` | Archivo de variables adicionales que Compose pasa a la API | `.env` | No |

**Fuente operacional (solo lectura) y datos**

| Variable | Para qué | Por omisión | Secreto |
|---|---|---|---|
| `FUENTE` | `parquet` (sin red, reproducible) o `postgres` (base de Extreme o réplica, solo lectura) | `parquet` | No |
| `FUENTE_DATABASE_URL` | Con `FUENTE=postgres`: usuario con solo `SELECT` (`lector_ia`) | vacía | **Sí** |
| `FUENTE_STATEMENT_TIMEOUT_MS` | Límite de cada consulta a la fuente | 30000 | No |
| `FUENTE_TABLA`, `FUENTE_PROCESO`, `FUENTE_SOLAPE_MIN` | Lectura que alimenta el ciclo (solo `demanda_segmentos` llega de punta a punta; otro valor detiene el arranque con un error claro), proceso que se lee y solape de la marca de agua (min) | `demanda_segmentos`, `sobusa`, 15 | No |
| `CATALOGOS_FUENTE` | `/api/v1/catalogos`: `auto`, `replica` o `archivos` | `auto` | No |
| `CATALOGOS_DATABASE_URL` | URL de solo lectura propia de los catálogos (vacía = `FUENTE_DATABASE_URL`) | vacía | **Sí** |
| `CATALOGOS_DATOS_DIR`, `CATALOGOS_FLOTA_CSV`, `CATALOGOS_CACHE_S` | Exportaciones Parquet, reporte de flota y caché (s) | `../../datos`, `../../insumos_sobusa/flota_sobusa.csv`, 300 | No |
| `DATA_DIR`, `MODELOS_DIR` | Carpeta de datos (Parquet/JSON) y de modelos | `./datos` (imagen: `/app/datos`), `DATA_DIR/modelos` | No |
| `TZ` | Zona de presentación (§8.1); en la base todo va con zona horaria | `America/Bogota` | No |

**Operación**

| Variable | Para qué | Por omisión | Secreto |
|---|---|---|---|
| `ENTORNO`, `DOCS_HABILITADOS` | Ambiente (`local`, `pruebas`, `demo`, `produccion`); Swagger solo fuera de producción | `local`, según `ENTORNO` | No |
| `MAX_REINTENTOS`, `REANUDAR_EJECUCIONES` | Reintentos por etapa y reanudación de trabajos tras un reinicio (RNF-001) | 3, `true` | No |
| `LOG_NIVEL` | Nivel de los logs JSON | `INFO` | No |
| `TRABAJADORES`, `LEASE_SEGUNDOS`, `SONDEO_COLA_SEGUNDOS`, `TRABAJADOR_ID` | Cola en PostgreSQL: hilos por réplica, reserva que vence, sondeo e identidad (vacía = nombre del contenedor) | 1, 30, 1, vacía | No |
| `PLANIFICADOR_HABILITADO` | Planificador interno (APScheduler) | `false` en el venv, `true` en Compose; en el modo integrado lo fija `PLANIFICADOR_HABILITADO_INTEGRADO` (`true` por omisión) | No |
| `PLAN_EJECUCION_CRON`, `PLAN_REENTRENAMIENTO_CRON` | Ejecución diaria y revisión semanal de reentrenamiento. La revisión aplica la política de `threshold_config` (`GET /api/v1/monitoring/policy`): reentrena si llegaron `reentreno_periodicidad_dias` días de datos nuevos (28), si el error se degradó, si hay deriva o si la cobertura bajó. Con `activacion_automatica` = 1 (por omisión), el retador que pasa la compuerta de sombra se activa solo, con auditoría | `15 5 * * *`, `0 4 * * 1` | No |
| `MODELO_PLAN` | Pronóstico de la foto de la respuesta del reto: el modelo activo o `E12` (el pronóstico precalculado de 2025 del experimento 12 del informe) | modelo activo | No |
| `INFERENCIA_SERIE` | `validada`: un script sin sesión de base arma las variables con el histórico validado de `demanda_observada` (la API y el ciclo ya lo hacen con su sesión) | vacía en el venv (serie empaquetada); `validada` en Compose y en `.env.example` (definirla vacía en el `.env` deja solo la serie empaquetada) | No |
| `MOTOR_INFERENCIA`, `CALIBRACION_BANDA` | `sklearn` u `onnx`; `v1` fuerza la banda conformal móvil en lugar de la calibración versionada | `sklearn`, vacía | No |
| `NOTIFICACIONES_CANALES`, `NOTIFICACIONES_SEVERIDAD` | Canales simulados (`correo,whatsapp`) y severidad mínima | vacío en el venv (`correo,whatsapp` en Compose), `critica` | No |
| `NOTIF_CORREO_DESTINATARIOS`, `NOTIF_CORREO_REMITENTE`, `NOTIF_WHATSAPP_NUMEROS` | Destinatarios (se enmascaran en logs; el envío es simulado) | vacíos (Compose: `despacho@example.com`, `+570000000000`) | Dato personal |
| `CIRCUITO_FUENTE_FALLOS_MAX`, `CIRCUITO_FUENTE_REINICIO_S`, `CIRCUITO_NOTIF_FALLOS_MAX`, `CIRCUITO_NOTIF_REINICIO_S` | Circuit breaker (RNF-010) | 3, 60, 5, 120 | No |
| `OTEL_EXPORTADOR`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` | Trazas OpenTelemetry (`ninguno`, `consola`, `otlp`) | `ninguno`, `api-frecuencias`, `http://jaeger:4318` | No |
| `METRICAS_PUBLICAS` | `/metrics` sin clave para Prometheus en la red interna | `true` | No |

**Seguridad y clientes**

| Variable | Para qué | Por omisión | Secreto |
|---|---|---|---|
| `AUTH_HABILITADA` | X-API-Key con roles operador < analista < admin (§7.2) | `true` | No |
| `API_KEYS` | JSON `{"<sha256>": {"usuario", "rol"}}`: solo los hashes de las claves | vacía | **Sí** (configuración de acceso) |
| `API_KEY_OPERADOR`, `API_KEY_ANALISTA`, `API_KEY_ADMIN` | Alternativa: una clave en claro por rol (mínimo 16 caracteres) | vacías | **Sí** |
| `SEUDONIMO_SECRETO` | Secreto del HMAC-SHA256 que seudonimiza al conductor en las alertas (§18); vacío = conductor `NULL` | marcador en `.env.example` | **Sí** |
| `SOBUSA_API_URL`, `SOBUSA_API_KEY` | Lo que usan los clientes (tablero Dash, k6, `scripts/demo_ciclo_api.py`, `scripts/medir_rendimiento.py`) | `http://127.0.0.1:8000`, vacía | La clave **sí** |
| `SOBUSA_API_KEY_DASH` | Clave de rol analista reservada para el tablero Dash local | vacía | **Sí** |

**Réplica operacional y variantes de Compose**

| Variable | Para qué | Por omisión | Secreto |
|---|---|---|---|
| `OPERACIONAL_PASSWORD`, `LECTOR_IA_PASSWORD`, `ESCRITOR_IA_PASSWORD` | Claves de `extreme_dba`, `lector_ia` y `escritor_ia` en la réplica (se fijan al crear su volumen) | valores de ejemplo | **Sí** |
| `OPERACIONAL_PUERTO_HOST`, `API_INTEGRADA_PUERTO_HOST` | Puertos de la réplica y de la API integrada | 5434, 8302 | No |
| `PLANIFICADOR_HABILITADO_INTEGRADO` | Planificador de la API integrada (§7.3, paso 2: el proceso programado lee la base operacional); `false` lo apaga | `true` | No |
| `REPLICA_ERRATA_E1`, `REPLICA_ERRATA_E2`, `REPLICA_ARMONIZAR_ESTACIONALIDADES`, `REPLICA_DATOS_HOST` | Correcciones y carga de la réplica | 1, 1, 1, `../../datos` | No |
| `API_PUERTO_HOST_DESDE`, `API_PUERTO_HOST_HASTA` | Rango de puertos de las dos réplicas | 8000, 8001 | No |
| `JAEGER_UI_PUERTO_HOST` | Interfaz de Jaeger | 16686 | No |

Variables solo de pruebas (ver `docs/manual_tecnico.md`, sección 13):

- `TEST_DATABASE_URL` (o, si no está, `DATABASE_URL`) y `TEST_DATABASE_NAME`: el PostgreSQL local y la base de pruebas
  propia. Sin ninguna URL, con una URL que no sea local o con el servidor apagado, las pruebas de integración y las de
  contrato que usan la base se omiten con su motivo, sin errores.
- `GENERAR_EVIDENCIAS=1`: las pruebas que dejan evidencia reescriben `docs/evidencias/`; sin ella escriben en un
  directorio temporal o en `EVIDENCIAS_DIR`, y el checkout no cambia.
- `TESTCONTAINERS=1`, `SCHEMATHESIS_EJEMPLOS`, `REPLICA_PRUEBAS_ESCRITURA=1`, `PRUEBA_CAIDA=1` (RNF-001 con procesos
  reales) y `PRUEBA_PLANIFICADOR=1` (la ejecución programada de §14.2).

## 3. Modos de ejecución

### 3.1 Docker Compose: aplicación y PostgreSQL (recomendado, RNF-008)

```
cd api_frecuencias
copy .env.example .env                 (macOS o Linux: cp .env.example .env)
```

Edite `.env`: cambie `POSTGRES_PASSWORD` y ponga un `SEUDONIMO_SECRETO` propio
(`python -c "import secrets; print(secrets.token_hex(32))"`). Luego:

```
docker compose -p sobusa_api up -d --build
docker compose -p sobusa_api ps        db «healthy», migrar «exited (0)», api «healthy»
curl http://127.0.0.1:8000/health      {"estado": "ok", "base_datos": "ok", ...}
```

Qué pasa al arrancar: `db` (PostGIS 14-3.4) queda sano; el servicio **`migrar`** corre `alembic upgrade head` una sola
vez y termina con código 0; solo entonces arranca **`api`** (uvicorn en el puerto 8000, usuario sin privilegios,
HEALTHCHECK contra `/health`). Al primer arranque, el registro de modelos se siembra desde
`datos/modelos/registro.json` con el modelo activo `hgb_fv2_20250831_s42`. Los modelos que se entrenen después quedan
en el volumen `modelos` y sobreviven a los reinicios. Swagger: http://127.0.0.1:8000/docs (fuera de producción).

| Tarea | Comando |
|---|---|
| Logs JSON de la API | `docker compose -p sobusa_api logs -f api` |
| Detener sin borrar datos | `docker compose -p sobusa_api down` |
| Borrar también la base y los modelos entrenados | `docker compose -p sobusa_api down -v` |
| Actualizar el código | `docker compose -p sobusa_api build api migrar`, `docker compose -p sobusa_api run --rm --no-deps migrar` y `docker compose -p sobusa_api up -d --no-deps --build api` (sección 9) |
| Pila aislada para probar | `API_PUERTO_HOST=8010 DB_PUERTO_HOST=5440 docker compose -p sobusa_limpio up -d --build` (bash); en PowerShell, `$env:API_PUERTO_HOST="8010"; $env:DB_PUERTO_HOST="5440"` antes del mismo comando |

Con `docker run` suelto (sin Compose), la imagen migra y arranca en un solo paso: su `CMD` es
`alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000`.

### 3.2 Local con el venv (desarrollo)

Hace falta un PostgreSQL 14 accesible en `DATABASE_URL`; el más simple es el servicio `db`:
`docker compose -p sobusa_api up -d db` (puerto 5433).

```
python -m venv .venv
.venv\Scripts\activate                 (Windows)   ·   source .venv/bin/activate   (macOS o Linux)
python -m pip install -r requirements-dev.txt        (solo para correr la API basta requirements.txt)
alembic upgrade head                   (usa DATABASE_URL del .env)
uvicorn app.main:app --port 8000
```

En el venv el planificador viene apagado (`PLANIFICADOR_HABILITADO=false`) y la API lee el `.env` con
pydantic-settings. Las claves de API se leen del entorno del proceso: defínalas en la sesión
(`set API_KEYS=...`) o use `API_KEY_<ROL>`.

Para la demostración de §14.2 contra esta API, con una clave de admin en `SOBUSA_API_KEY`:
`.venv\Scripts\python scripts\demo_ciclo_api.py --base http://127.0.0.1:8000 --revertir`. Para un ensayo que no toque
los datos del repositorio, apunte `DATA_DIR` y `MODELOS_DIR` a una copia de `datos/` y `DATABASE_URL` a una base de
pruebas: así se corrió la salida de referencia de `docs/evidencias/despliegue/demo_esperado.md`, que explica también
qué muestra cada paso.

### 3.3 Docker con la réplica de la base operacional (modo integrado)

La API corre como correría en Extreme: **lee** las tablas existentes de la réplica con `lector_ia` (solo `SELECT`,
transacciones `READ ONLY` por omisión, `statement_timeout`) y **escribe** sus resultados solo en el esquema
`ai_frecuencias` de la misma base con `escritor_ia` (dueño de ese esquema, sin permisos sobre las tablas de Extreme).
Va en el MISMO proyecto Compose de la réplica (`sobusa_rep`) para compartir su red; el puerto de la API es 8302.

1. Réplica (una vez) y su carga: `docker compose -p sobusa_rep --profile integracion up -d operacional` y
   `.venv\Scripts\python -m scripts.replica_cargar` (ver `docs/integracion_postgresql.md`).
2. API integrada **sin tocar el contenedor ni el volumen de la réplica** (`--no-deps`):

```
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion build api
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion run --rm --no-deps migrar
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion up -d --no-deps api
curl http://127.0.0.1:8302/health      {"estado": "ok", ..., "fuente": "postgres"}
```

3. Para retirarla dejando la réplica encendida con sus datos:

```
docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml --profile integracion rm -s -f api migrar
```

Las claves `LECTOR_IA_PASSWORD` y `ESCRITOR_IA_PASSWORD` salen solo del `.env` local. En este modo el planificador
queda encendido por omisión (`PLANIFICADOR_HABILITADO_INTEGRADO=true`), así que la ejecución diaria lee la réplica sin
ningún POST, y `docker-compose.integracion.yml` pasa `FUENTE_PROCESO` (por omisión `sobusa`) al servicio de la API.
Evidencia: `modo_integrado.txt`.

### 3.4 Dos réplicas de la API (RNF-005)

```
docker compose -p sobusa_api -f docker-compose.yml -f docker-compose.replicas.yml up -d --build
```

Quedan en los puertos 8000 y 8001 sobre la misma base y la misma cola (SKIP LOCKED + reserva que vence); cada una
reclama trabajos con su propia identidad (el nombre del contenedor) y la migración la corre una sola vez `migrar`.
La prueba con dos réplicas y la caída de una está en `docs/evidencias/cola/` (`caida_rnf001_docker.txt`).

### 3.5 Trazas con Jaeger (RNF-006)

```
$env:OTEL_EXPORTADOR="otlp"; docker compose -p sobusa_api --profile observabilidad up -d      (PowerShell)
OTEL_EXPORTADOR=otlp docker compose -p sobusa_api --profile observabilidad up -d               (bash)
```

Interfaz en http://127.0.0.1:16686 (servicio `api-frecuencias`). El `traceparent` viaja de la petición al trabajo de
la cola y queda en `execution_log.traceparent`.

## 4. Migraciones (Alembic)

- El esquema `ai_frecuencias` lo crean solo las migraciones de `alembic/versions/` (0001 esquema base, 0002 cola de
  trabajos, 0003 estructura completa de alertas §5.3 con `geography(Point,4326)` e índice GiST, 0004 monitoreo,
  `feature_snapshot` particionada por mes y trazabilidad, 0005 pesos y costos versionados de la función objetivo de
  §10.2, 0006 dimensiones de §8.3, campos de trazabilidad de la calidad, aprobación de umbrales y la tabla
  `respuesta_reto`, 0007 los umbrales de la ALT-002 observada y del detector de rupturas de RF-009 versionados en
  `threshold_config`). Son aditivas: no borran datos. La 0007 crea una versión nueva del conjunto de umbrales, así que
  en una base nueva sin ningún `PUT /thresholds` la versión vigente es la 5.
- En Compose las aplica el servicio `migrar` (`alembic upgrade head`) antes de la API; con varias réplicas nadie
  compite por Alembic. Repetirla no hace nada (comprobado en `migraciones.txt`).
- Comandos útiles: `docker compose -p sobusa_api run --rm migrar alembic current`, `... alembic history`, y para
  volver atrás una versión `... alembic downgrade -1` (respalde antes, sección 7).
- Como `escritor_ia` en la réplica, `alembic/env.py` y la 0001 solo crean el esquema si `pg_namespace` no lo tiene
  (escritor_ia no tiene `CREATE` sobre la base); ver `docs/integracion_postgresql.md`.

## 5. Claves de API y clientes

La API exige `X-API-Key` en todo `/api/v1` (`AUTH_HABILITADA=true`). Roles (matriz `POLITICA` de `app/seguridad.py`):
**operador** (todas las consultas y los cambios de estado de las alertas), **analista** (además lanzar ejecuciones,
predicciones y recomendaciones a pedido y entrenar candidatos) y **admin** (además activar y revertir modelos, cambiar
umbrales y el catálogo de capacidad). La clave en claro nunca se guarda en el servidor: solo su SHA-256.

1. Crear la clave (dentro del contenedor, no hace falta el venv):

```
docker compose -p sobusa_api run --rm --no-deps api python scripts/crear_api_key.py --rol analista --usuario ana
```

   El script muestra la clave UNA vez y la entrada con el hash. Entregue la clave a su dueño por un canal seguro.
2. Pegue solo la entrada con el hash en `API_KEYS` del `.env` (varias entradas en el mismo objeto JSON):
   `API_KEYS={"<sha256>": {"usuario": "ana", "rol": "analista"}}`.
3. Recree la API para que lea las claves: `docker compose -p sobusa_api up -d --no-deps api`.
4. Los clientes envían la clave desde su propio entorno, nunca desde el código:

| Cliente | Cómo recibe la clave |
|---|---|
| Tablero Dash | `SOBUSA_API_URL=http://127.0.0.1:8000` y `SOBUSA_API_KEY=<clave analista>` (la del tablero local se guarda como `SOBUSA_API_KEY_DASH` en el `.env`) |
| Demostración | `$env:SOBUSA_API_URL="http://127.0.0.1:8000"; $env:SOBUSA_API_KEY="<clave admin>"` (PowerShell) y `python scripts/demo_ciclo_api.py` |
| k6 | `docker run --rm -v <k6>:/scripts -e BASE=http://host.docker.internal:8000 -e SOBUSA_API_KEY=<clave operador> grafana/k6:1.4.2 run /scripts/consultas.js` |
| curl | `curl -H "X-API-Key: <clave>" http://127.0.0.1:8000/api/v1/alerts` |

Sin clave la API responde 401; con un rol insuficiente, 403 (comprobado en `arranque_limpio.txt`).

## 6. Salud, métricas y trazas

| Qué | Dónde |
|---|---|
| Salud | `GET /health` → 200 `{"estado": "ok", "base_datos": "ok", "version", "fuente"}`; 503 si la base no responde. Es el HEALTHCHECK de la imagen (cada 15 s) |
| Métricas Prometheus | `GET /metrics` (pública en la red interna con `METRICAS_PUBLICAS=true`). Además de las peticiones y los circuitos, la cola y el ciclo: `api_ejecuciones_total`, `api_ejecucion_duracion_segundos`, `api_cola_reintentos_total`, `api_cola_trabajos` (por tipo y estado), `api_ejecucion_etapa_segundos` y `api_serie_diaria_segundos` (detalle en `docs/manual_tecnico.md`, sección 9) |
| Rendimiento de las consultas a la base de resultados | El servicio `db` arranca con `shared_preload_libraries=pg_stat_statements` y `track_io_timing=on`; la extensión la crea `initdb_resultados/10_pg_stat_statements.sql` en un volumen nuevo (`docs/evidencias/despliegue/pg_stat_statements_db.txt`). En un volumen que ya existía, se crea una vez con `CREATE EXTENSION IF NOT EXISTS pg_stat_statements` |
| Logs | JSON por línea (structlog) con `correlation_id`, `execution_id`, `worker_id`, `trace_id`: `docker compose logs api` |
| Trazas | OpenTelemetry → Jaeger (sección 3.5) |
| Trabajos | `GET /api/v1/frequency/executions/{id}` (estado, etapa, progreso, intentos) y `GET /api/v1/scheduler` |

## 7. Respaldo y restauración

```
docker compose -p sobusa_api exec -T db pg_dump -U sobusa -d ai_frecuencias -n ai_frecuencias -Fc > respaldo_ai_frecuencias.dump
docker compose -p sobusa_api exec -T db pg_restore -U sobusa -d ai_frecuencias --clean --if-exists < respaldo_ai_frecuencias.dump
```

Los modelos entrenados viven en el volumen `modelos` (`/app/datos/modelos`); para respaldarlos:
`docker compose -p sobusa_api cp api:/app/datos/modelos ./respaldo_modelos`. La réplica operacional no se respalda
desde aquí: es una copia que se reconstruye con `scripts/replica_cargar.py`.

## 8. Verificación reproducible del despliegue

```
.venv\Scripts\python scripts\verificar_despliegue.py                  (todo: 5,7 min el 9-11-2026 con la caché de BuildKit)
.venv\Scripts\python scripts\verificar_despliegue.py --sin-demo       (sin la demostración; RNF-001 con un día de referencia)
.venv\Scripts\python scripts\verificar_despliegue.py --modo-integrado (API contra la réplica que ya corre en sobusa_rep)
   otras opciones: --sin-cache (reconstruye la imagen), --sin-caida (omite RNF-001), --conservar (no baja la pila)
```

En un proyecto Compose **aislado** (`sobusa_limpio`, API en 8010, PostgreSQL en 5440, volúmenes propios; nunca toca
`sobusa_api` ni `sobusa_rep`) hace, desde cero: construcción y `up -d --build`; migraciones 0001 → head; `/health` y el
HEALTHCHECK; claves de API creadas con `scripts/crear_api_key.py` dentro del contenedor (solo viven en la memoria del
proceso); la demostración de §14.2 con `scripts/demo_ciclo_api.py --hasta 2025-08-30 --corte 2025-09-30 --revertir`
(ver abajo); la prueba RNF-001 (SIGKILL con `docker kill` + `docker start`, y reinicio
ordenado con `docker compose restart`, a mitad de una ejecución); la descripción de la imagen y el `pip freeze` de
`requisitos_congelados.txt`; y `down -v`, comprobando que no quedan contenedores ni volúmenes. Las claves de la base
de prueba se generan al azar en un archivo temporal que se borra al final. Devuelve 0 solo si todo pasa.

**La demostración de §14.2**, paso por paso (qué muestra cada uno y por qué esas fechas, en
`docs/evidencias/despliegue/demo_esperado.md`):

1. **Llegada de información nueva:** la carga inicial hasta el 30-08-2025 (49.623 filas), un día nuevo, el 31-08
   (51 filas), y los días hasta la marca de agua 2025-11-30, el corte del candidato más 61 días (4.641 filas).
2. **Lectura incremental:** cada ejecución imprime su marca de agua anterior y la nueva, y la repetición con la misma
   fecha lee 0 filas y crea 0 predicciones.
3. **Evaluación del error** del modelo activo `hgb_fv2_20250831_s42` en lo que llegó, con el monitoreo de §9.4 y la
   decisión de la política, que pide reentrenar por periodicidad.
4. **Modelo candidato:** `hgb_fv2_20250930_s42`, con corte 2025-09-30 y `datos_hasta` = 2025-11-30, así que solo ve lo
   que ya llegó. La política ya encoló ese entrenamiento al cerrar la ejecución; el script espera ese trabajo en vez de
   pedir otro igual con `POST /api/v1/models/train`, y solo lo pide si la política no lo encoló. Queda en sombra del
   2025-12-01 al 2025-12-14.
5. **Comparación con el modelo activo** en la misma ventana, 2025-12-01..14: posterior a todo lo que vieron los dos
   modelos y anterior al 2025-12-31, último día de la serie empaquetada. Llegan esos 14 días (714 filas) y
   `GET /api/v1/models/{id}/evaluation` da WAPE 14,108 % del candidato frente a 13,982 % del activo.
6. **Decisión:** la compuerta de cuatro criterios (`politica.compuerta`) imprime cada uno. Solo falla «WAPE del
   candidato ≤ WAPE del activo» (los de `wape_max`, cobertura P10–P90 y sesgo se cumplen), así que el candidato queda
   rechazado y el activo sigue. Activarlo sin forzar con `POST /api/v1/models/{id}/activate` responde 409
   `requiere_forzar`. Con `--revertir`, si la compuerta lo hubiera activado, se revierte con `POST /models/rollback`; en
   esta corrida no hay nada que revertir.

`POST /models/{id}/activate` exige una ventana posterior a lo que vio el candidato (corte + 61 días) y responde 422
`ventana_en_muestra` si no lo es; la demostración nunca le pasa una ventana dentro de la muestra. No cambian entre
corridas las filas, las marcas de agua, los WAPE, el identificador y el SHA-256 del candidato, los criterios ni la
decisión; sí, los tiempos, los identificadores de las ejecuciones y el número de alertas y de notificaciones omitidas.

**Dónde queda cada corrida.** La corrida en Docker sobre la pila creada desde cero queda en
`docs/evidencias/despliegue/demo_ciclo_api.txt`, que `verificar_despliegue.py` reescribe en cada corrida (y en
`docs/evidencias/demo_ciclo.txt`). La salida de referencia, contra la API en el venv con una base de pruebas nueva y una
copia temporal de `datos/`, está en `demo_esperado.md`: dos corridas del 9-11-2026 (07:30 y 07:40) con código 0, en 139
y 125 s, y la misma salida salvo los tiempos y los identificadores.

Los demás resultados de la tabla salen de la corrida completa de `verificar_despliegue.py` (con la demostración) del
9-11-2026, de 08:27 a 08:32, en el equipo de desarrollo: «Resultado global: OK» en 5,7 min, que dejó
`arranque_limpio.txt`, `migraciones.txt`, `demo_ciclo_api.txt`, `reinicio.txt` e `imagen.txt`. Los tiempos varían de
una corrida a otra; cada corrida reescribe esos archivos.

| Paso | Resultado |
|---|---|
| Construcción | 173 s la primera vez sin caché (`construccion_sin_cache.txt`); 9,0 s reutilizando la caché de BuildKit (`arranque_limpio.txt`, paso 1) |
| `up -d --build` desde volúmenes nuevos | retorna en 17,7 s; `GET /health` = ok a los 24,3 s y HEALTHCHECK `healthy` a los 28,5 s; `db` sano y `migrar` termina con código 0 (`arranque_limpio.txt`, pasos 2 y 3) |
| Migraciones | 0001 → 0007 (head) en la base nueva; `alembic current` = 0007 (head); repetir `alembic upgrade head` no hace nada; 16 tablas en `ai_frecuencias`, la partición `feature_snapshot_202611`, el índice GiST `ix_alert_ubicacion` y `pg_stat_statements` cargado (`migraciones.txt`) |
| Claves y roles | 2 claves (admin y operador) creadas con `scripts/crear_api_key.py` dentro del contenedor; sin clave 401, operador 200, operador sobre una ruta de admin (`POST /api/v1/models/rollback`) 403, `/metrics` 200; `SEUDONIMO_SECRETO` llega al contenedor (64 caracteres, no se muestra) (`arranque_limpio.txt`, paso 4) |
| Demostración §14.2 (referencia con la API en el venv, `demo_esperado.md`) | pasos (1) a (6) con código 0 en 139 s (125 s en la confirmación): 49.623, 51 y 4.641 filas; repetición con 0 filas; candidato `hgb_fv2_20250930_s42` entrenado por el trabajador de la cola; 714 filas de la sombra; comparación en 2025-12-01..14 (WAPE 14,108 % del candidato frente a 13,982 % del activo); decisión: **rechazado** por la compuerta de sombra, y 409 `requiere_forzar` al intentar activarlo sin forzar; el activo sigue siendo `hgb_fv2_20250831_s42`; notificaciones simuladas 0 y omitidas 56 |
| Demostración §14.2 en Docker (`demo_ciclo_api.txt`) | sobre la pila creada desde cero (9-11-2026, 08:28–08:31), código 0 en 190,9 s con los seis pasos impresos: 49.623, 51 y 4.641 filas; repetición con 0 filas; candidato `hgb_fv2_20250930_s42` entrenado por el trabajador de la cola en 37,2 s; 714 filas de la sombra; comparación en 2025-12-01..14 (WAPE 14,108 % del candidato frente a 13,982 % del activo); decisión: **rechazado** por la compuerta de cuatro criterios (solo falla «WAPE del candidato ≤ WAPE del activo»), y 409 `requiere_forzar` al intentar activarlo sin forzar; el activo sigue siendo `hgb_fv2_20250831_s42`; notificaciones simuladas 16 y omitidas 40 |
| RNF-001 (`reinicio.txt`) | A) SIGKILL (`docker kill` + `docker start`) durante la etapa «calidad»: API de vuelta en 2,6 s, ejecución terminada 36,4 s después del corte con la traza de intentos [abandonado, ok]; B) `docker compose restart api` durante «calidad»: de vuelta en 1,8 s, terminada 51,1 s después, [abandonado, ok]. En los dos: 9 predicciones y 60 recomendaciones, las mismas de la ejecución de referencia, sin duplicados, una sola entrada «crear» por alerta, filas leídas = las del día y marca de agua contigua (11 de 11 comprobaciones); en toda la base, 0 predicciones duplicadas y 0 ejecuciones colgadas |
| Imagen (`imagen.txt`) | 1,51 GB en disco (365,8 MB de capas), usuario `sobusa` (uid 10001), sin herramientas de desarrollo; su `pip freeze` (72 paquetes, `requisitos_congelados.txt`) es idéntico a `requirements.txt` con los marcadores de Linux y Python 3.11 |
| `down -v` | 2,4 s; sin contenedores ni volúmenes del proyecto |
| Modo integrado (`modo_integrado.txt`) | migración 0004 → 0005 como `escritor_ia`; la API lee como `lector_ia` (solo `SELECT`/`WITH` en transacciones que terminan en `ROLLBACK`) y escribe solo en `ai_frecuencias` como `escritor_ia` (0 escrituras fuera del esquema); un `CREATE TABLE` como `lector_ia` se rechaza (`ReadOnlySqlTransaction`); el contenedor y el volumen de la réplica no cambian |

## 9. Actualizar una pila en uso sin perder datos

```
docker compose -p sobusa_api build api migrar                    (la misma imagen para los dos servicios)
docker compose -p sobusa_api run --rm --no-deps migrar           (migraciones aditivas sobre la base existente)
docker compose -p sobusa_api up -d --no-deps api                 (recrea solo la API; db sigue igual)
curl http://127.0.0.1:8000/health
```

`--no-deps` evita tocar el contenedor `db` (ya está corriendo y sano). Las ejecuciones que estaban corriendo se
retoman solas al arrancar (`REANUDAR_EJECUCIONES=true`, RNF-001).

## 10. Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `POSTGRES_PASSWORD` «Defina ... en el archivo .env» | Falta el `.env`: `copy .env.example .env` y cambie la clave |
| Toda ruta de `/api/v1` responde 401 y el log dice «AUTH_HABILITADA=true y no hay claves» | Cree una clave (sección 5) y recree la API; o `AUTH_HABILITADA=false` solo en local |
| 403 | La clave es válida pero su rol no alcanza (p. ej. activar un modelo exige admin) |
| `api` no arranca y `migrar` salió con código ≠ 0 | `docker compose -p sobusa_api logs migrar`: casi siempre la clave de `DATABASE_URL` no coincide con la del volumen existente (la clave se fija al crear el volumen; `down -v` lo borra) |
| `db` no llega a «healthy» | Puerto 5433 ocupado (`DB_PUERTO_HOST`), o volumen de otra versión de PostgreSQL |
| «port is already allocated» | Cambie `API_PUERTO_HOST` / `DB_PUERTO_HOST` (o use otro `-p` de proyecto) |
| `/api/v1/catalogos/...` responde 503 `catalogo_no_disponible` en Docker | La imagen no trae las exportaciones Parquet: defina `CATALOGOS_DATABASE_URL` (o use el modo integrado) o monte `CATALOGOS_DATOS_DIR` |
| El conductor sale `null` en las alertas | Falta `SEUDONIMO_SECRETO` en el `.env` (no se guarda nunca el dato en claro) |
| Una ejecución quedó «corriendo» tras apagar el equipo | Al arrancar, la API la retoma; si la réplica no vuelve, otra la toma al vencer la reserva (`LEASE_SEGUNDOS`) |
| En modo integrado aparece un segundo «operacional» vacío | Se levantó el perfil `integracion` con `-p sobusa_api`: use siempre `-p sobusa_rep` y `--no-deps` (sección 3.3) |
| La construcción falla al descargar ruedas | Sin red o sin rueda binaria para la plataforma: la imagen exige ruedas (`--only-binary=:all:`) para no compilar; use la caché de BuildKit o una red con salida a PyPI |
