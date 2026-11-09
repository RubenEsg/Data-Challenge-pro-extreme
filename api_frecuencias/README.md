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
| ¿Cuántos pasajeros se esperan? | Pronóstico a 30, 60 y 120 minutos con banda p10-p90, versión del modelo y explicación | `POST /api/v1/predictions/run` |
| ¿Cada cuánto despachar? | Headway y buses por hora con capacidad efectiva (50 × ocupación objetivo), frente a la frecuencia actual | `POST /api/v1/recommendations/calculate` |
| ¿Cuántos vehículos? | `ceil(tiempo_ciclo / headway)`, comparado con la flota disponible; si no alcanza, `viable = false` con el motivo | misma respuesta |
| ¿Qué requiere atención? | Alertas ALT-001 a ALT-010 con severidad, evidencia, umbral, explicación, recomendación y estado | `GET /api/v1/alerts` |
| ¿Por qué? | Fórmula aplicada, variables influyentes y versiones de datos, modelo y umbrales en cada salida | todas |

El plan del día completo sale del optimizador D5 del proyecto (MILP con PuLP/CBC), el mismo del laboratorio Dash.

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

| Módulo (`app/servicios/`) | Qué hace |
|---|---|
| `fuentes.py` | `FuenteParquet` (simula la llegada diaria de datos por fecha) y `FuentePostgresSoloLectura` (transacción `READ ONLY`, `statement_timeout`); ambas con `leer_incremental(marca_agua, hasta)`. |
| `calidad.py` | `validar_lote`: completitud, validez, unicidad, consistencia, oportunidad y relacional (§6.3); cada error con lote, fila, campo, código y detalle. |
| `datos.py` | Vista analítica `demanda_horaria` y catálogo de rutas (capacidad, ciclo, flota, frecuencia actual). |
| `inferencia.py` | Entrena, registra, carga (verifica el SHA-256 del artefacto), predice y evalúa (MAE, RMSE, WAPE por ruta, pico y valle). |
| `optimizacion.py` | `recomendar` (fórmulas de §10.3 con la demanda p90 y la flota) y `plan_dia_d5` (MILP D5 en `motor_d5/`). |
| `alertas.py` | Reglas ALT-001 a ALT-010, deduplicación y máquina de estados (reconocer, asignar, comentar, cerrar, descartar). |
| `notificaciones.py` | Adaptadores de correo y WhatsApp configurables; el envío es simulado y queda en `notification_log`. |
| `ejecucion.py` | Orquesta una ejecución como job con progreso y reintentos; todo queda ligado a `execution_id`, `model_id`, `feature_version`, versión de umbrales y `data_cutoff`. |

## Cómo correrla

**Con Docker (recomendado; aplicación y PostgreSQL):**

```
copy .env.example .env            (Windows; en macOS o Linux: cp .env.example .env) y cambie POSTGRES_PASSWORD
docker compose -p sobusa_api up -d --build
```

La API aplica las migraciones (`alembic upgrade head`) al arrancar y queda en **http://localhost:8000/docs** (Swagger).
La base queda en el puerto 5433 del equipo. Para apagar: `docker compose -p sobusa_api down` (agregue `-v` para borrar
la base).

**Comandos que se corrieron el 8-11-2026 para la evidencia** (Windows 11, Docker Desktop, venv con Python 3.13; la
imagen usa Python 3.11):

```
docker compose -p sobusa_api up -d --build                      (db en 5433 sana; api en 8000, migraciones aplicadas)
.venv\Scripts\python scripts\demo_ciclo.py --base http://127.0.0.1:8000 --salida docs\evidencias\demo_ciclo.txt
.venv\Scripts\python -m pytest tests --cov=app --cov-report=term --cov-report=xml:docs\evidencias\coverage.xml
.venv\Scripts\python -m ruff check app scripts tests            (docs\evidencias\ruff.txt)
.venv\Scripts\python -m bandit -r app                           (docs\evidencias\bandit.txt)
.venv\Scripts\python scripts\medir_rendimiento.py --salida docs\evidencias\rendimiento.txt
docker compose -p sobusa_api down                               (conserva el volumen de la base)
```

Las salidas quedaron en `docs/evidencias/` (ver «Evidencias» más abajo).

**Sin Docker para la API (entorno local):** hace falta un PostgreSQL 14 accesible en `DATABASE_URL`; el más simple es
el mismo servicio `db` de Compose (`docker compose -p sobusa_api up -d db`, puerto 5433).

```
python -m venv .venv
.venv\Scripts\activate             (Windows)   ·   source .venv/bin/activate   (macOS o Linux)
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --port 8000
```

**Variables de entorno** (todas en `.env.example`; el `.env` real no se versiona ni viaja en el ZIP):

| Variable | Por omisión | Para qué |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://sobusa@localhost:5433/ai_frecuencias` | Base de resultados propia (esquema `ai_frecuencias`). |
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

## Endpoints

Base `/api/v1`, JSON UTF-8, fechas ISO-8601 con zona, errores uniformes, cabecera `X-Correlation-Id` en cada respuesta.
El contrato completo está en `/openapi.json` y en Swagger (`/docs`).

| Método | Ruta | Para qué |
|---|---|---|
| POST | `/api/v1/frequency/executions` | Lanza una ejecución (lectura incremental → calidad → predicción → recomendación → alertas); responde 202 con el `execution_id`. |
| GET | `/api/v1/frequency/executions` | Ejecuciones, paginadas. |
| GET | `/api/v1/frequency/executions/{id}` | Estado, etapa y progreso, corte de datos, marcas de agua, métricas y errores de calidad. |
| GET | `/api/v1/frequency/executions/{id}/errors` | Errores de calidad de esa ejecución, con lote, fila, campo, código y detalle. |
| POST | `/api/v1/predictions/run` | Pronóstico de una ruta y un horizonte (30, 60 o 120 min). |
| GET | `/api/v1/predictions` | Pronósticos guardados, con filtros (ruta, fechas, horizonte, modelo), paginación y orden. |
| GET | `/api/v1/predictions/export` | Los mismos filtros, en CSV o XLSX. |
| POST | `/api/v1/recommendations/calculate` | Headway, buses por hora y vehículos requeridos, con la frecuencia actual al lado. |
| GET | `/api/v1/recommendations` | Recomendaciones guardadas, con filtros. |
| GET | `/api/v1/recommendations/export` | Los mismos filtros, en CSV o XLSX. |
| GET | `/api/v1/alerts` | Alertas por estado, severidad, ruta y fecha. |
| GET | `/api/v1/alerts/{id}` · `/api/v1/alerts/{id}/history` | Una alerta y su bitácora de cambios. |
| PATCH | `/api/v1/alerts/{id}/status` | Reconocer, asignar, comentar, cerrar o descartar; queda en el historial. |
| GET | `/api/v1/models` · `/api/v1/models/{id}` | Registro de modelos: activo, candidatos, métricas, fecha de corte, SHA-256. |
| POST | `/api/v1/models/train` | Entrena un candidato con los datos validados hasta una fecha (job, responde 202). |
| POST | `/api/v1/models/{id}/activate` | Activa una versión solo si su WAPE es menor o igual que el del activo en la misma validación temporal; auditoría. |
| POST | `/api/v1/models/rollback` | Vuelve al modelo activo anterior. |
| GET · PUT | `/api/v1/thresholds` · `GET /api/v1/thresholds/history` | Umbrales de §5.1 vigentes; cambiarlos crea una versión nueva. |
| GET | `/health` · `/metrics` | Salud del servicio y de la base (503 si la base no responde) · métricas Prometheus. |

Ejemplos (con la API en el puerto 8000; en `cmd`, `^` continúa la línea, en PowerShell `` ` `` y en bash `\`):

```
curl -X POST http://localhost:8000/api/v1/frequency/executions -H "Content-Type: application/json" ^
     -d "{\"hasta\": \"2025-06-10\"}"
curl http://localhost:8000/api/v1/frequency/executions/<execution_id>
curl http://localhost:8000/api/v1/frequency/executions/<execution_id>/errors

curl -X POST http://localhost:8000/api/v1/predictions/run -H "Content-Type: application/json" ^
     -d "{\"ruta\": \"CRA 54\", \"instante\": \"2025-06-10T07:00:00-05:00\", \"horizonte_min\": 60}"

curl -X POST http://localhost:8000/api/v1/recommendations/calculate -H "Content-Type: application/json" ^
     -d "{\"ruta\": \"CRA 54\", \"hora\": 7, \"demanda_hora\": 620, \"demanda_p90\": 700}"

curl "http://localhost:8000/api/v1/alerts?estado=nueva&severidad=critica&ruta=CL%2072"
curl -X PATCH http://localhost:8000/api/v1/alerts/<id>/status -H "Content-Type: application/json" ^
     -d "{\"accion\": \"reconocer\", \"usuario\": \"despachador1\", \"comentario\": \"Se envía un bus de refuerzo\"}"

curl -X POST http://localhost:8000/api/v1/models/train -H "Content-Type: application/json" ^
     -d "{\"hasta\": \"2025-06-30\", \"semilla\": 42}"
curl http://localhost:8000/api/v1/models
curl -X POST http://localhost:8000/api/v1/models/<model_id>/activate -H "Content-Type: application/json" ^
     -d "{\"aprobado_por\": \"jefe_operacion\", \"motivo\": \"WAPE menor que el activo en la validación temporal\"}"
curl -X POST http://localhost:8000/api/v1/models/rollback -H "Content-Type: application/json" ^
     -d "{\"usuario\": \"jefe_operacion\", \"motivo\": \"Prueba de reversión\"}"
```

Los campos de cada petición y respuesta están documentados en Swagger.

## El ciclo de la demostración (§14.2)

1. **Llega información nueva.** La fuente Parquet entrega solo los días hasta la fecha `hasta` de la petición, como si
   llegaran de los triggers de Extreme; subir `hasta` un día simula la llegada del día siguiente.
2. **Lectura incremental.** `POST /frequency/executions` lee solo lo que cumple `marca_agua < ultima_actualizacion ≤ corte`;
   repetir la ejecución con la misma marca no duplica filas.
3. **Evaluación del error.** El pronóstico guardado se compara con lo observado (WAPE, MAE, RMSE por ruta, pico y valle);
   si el error móvil supera la tolerancia se emite ALT-010.
4. **Modelo candidato.** `POST /models/train` entrena con los datos validados hasta el nuevo corte (semilla 42) y lo
   registra como candidato con su artefacto, SHA-256, métricas y fecha de corte.
5. **Comparación con el activo** en una ventana temporal posterior al corte (sin mezclar futuro y pasado).
6. **Activación o rechazo.** `POST /models/{id}/activate` solo activa si el WAPE del candidato es menor o igual que el del
   activo en la misma validación; si no, se rechaza y la decisión queda registrada. `POST /models/rollback` vuelve a la
   versión anterior.

El paso a paso con los comandos está en `docs/manual_usuario.md`.

## Pruebas

```
pytest -q                                     (unitarias e integración)
pytest --cov=app --cov-report=term-missing    (cobertura)
ruff check app tests
bandit -r app
```

- `tests/unit/`: reglas de negocio, fórmulas de §10.3, validaciones de calidad, máquina de estados de alertas,
  deduplicación, verificación del SHA-256, simulación de notificaciones, fuente Parquet incremental.
- `tests/integracion/`: API con HTTPX/TestClient, migraciones y repositorios contra la base local de `docker compose`.
  **Ninguna prueba se conecta a la base del reto.**
- Los reportes (pytest, cobertura, ruff, bandit) se guardan en `docs/evidencias/`; `sonar-project.properties` deja
  listo el análisis con SonarQube apuntando a esos archivos.

## Evidencias (8-11-2026, `docs/evidencias/`)

| Archivo | Qué muestra |
|---|---|
| `demo_ciclo.txt` | Ciclo completo contra la API en Docker (`scripts/demo_ciclo.py`). Pasos: registro de modelos; carga inicial (52.938 filas validadas, 0 errores); 9 predicciones por ejecución (3 rutas × 30/60/120 min) con P10/P90, `model_id`, `feature_version` y explicación; 9 recomendaciones con headway, buses/h, vehículos y viabilidad (las no viables dicen por qué: falta de flota); alertas con la estructura de §5.3 y su deduplicación (la repetición suma ocurrencias); reconocer → asignar → cerrar con historial y una transición inválida que responde 409; llegada del día siguiente (solo se leen las 51 filas nuevas, con la marca de agua) y evaluación del error; reentrenamiento como job, comparación con el activo en la misma ventana, activación, reversión y rechazo con motivo; exportación CSV y XLSX; notificaciones simuladas. |
| `export_predictions.csv`, `export_recommendations.xlsx` | Archivos exportados en la demostración. |
| `pytest.txt`, `coverage.xml` | **147 pruebas pasan** (unitarias e integración contra el PostgreSQL local de `docker compose`; base `ai_frecuencias_pruebas`). Cobertura de `app/`: **91 %**. |
| `ruff.txt`, `ruff.json` | 0 hallazgos de seguridad (reglas `S`); quedan 39 avisos de estilo, todos de líneas de más de 120 caracteres. |
| `bandit.txt`, `bandit.json` | 0 hallazgos. |
| `rendimiento.txt` | RNF-002: p95 de 50 GET paginados por recurso, entre 9 y 19 ms. RNF-003: ingesta de 111.792 filas en 154 s (lectura 0,9 s; calidad 0,4 s; *upsert* 152,6 s), memoria pico 102 MiB. El *upsert* fila a fila es el cuello de botella. |

Resultado del gobierno del modelo en la demostración (ventana 1-28 nov. 2025): el candidato reentrenado
`hgb_fv1_20251031_s42` (WAPE 12,67 %) superó al activo `hgb_fv1_20250831_s42` (12,76 %) y se activó. Luego se
revirtió con `POST /models/rollback`. El intento de volver a la regla manual B1 (16,95 %) se rechazó con 409 y quedó
el motivo. En el paso 11, con destinatarios de prueba, las 17 alertas críticas generaron 34 notificaciones simuladas
(correo y WhatsApp).
| `../openapi.json` | OpenAPI 3.1, 23 rutas. |

Notas de la corrida:

- En un volumen nuevo, el primer `alembic upgrade` de la API se adelantó al servidor definitivo de PostgreSQL y la
  política `restart` lo recuperó. El chequeo de salud de `db` ahora va por TCP (`pg_isready -h 127.0.0.1`) para que eso
  no pase.
- El volumen `modelos` se llena con los artefactos de la imagen solo la primera vez. Si un volumen viejo no tiene
  `hgb_fv1_20250831_s42`, el registro arranca con la línea base B1 activa. Para empezar limpio:
  `docker compose -p sobusa_api down -v`.
- Las notificaciones simuladas de correo y WhatsApp quedan activas por omisión en `docker-compose.yml`
  (`NOTIFICACIONES_CANALES`). Solo escriben en `notification_log`.

## Datos y modelos

| Qué | De dónde sale |
|---|---|
| Demanda por ruta, día y hora 2023-2025 (`datos/demanda_horaria.parquet`) | Exportación de la base del reto: suma de `numeropasajeros` de los viajes válidos de `progvehiculos` por hora de salida (`experimentos/E1_lgbm_salida`). Procedencia en `datos/origen.json`. |
| Pronósticos 2025 de los modelos del proyecto (`datos/pronosticos_2025.parquet`) | B1 regla manual (WAPE 20,04 %), E1 LightGBM (14,40 %), E11 modelo final (13,94 %), E12 híbrido (13,62 %), a 7 días. |
| Insumos del optimizador D5 (`datos/insumos_d5_2025.parquet`) y costos con fuente (`datos/costos_fuente.json`) | Experimento D5 y estudio de costos del proyecto (precios 2026). |
| Catálogo de rutas (`datos/catalogo_rutas.json`) | Tabla `rutas` y medianas de día laboral de `experimentos/D1_optimizacion/parametros_operativos.parquet`; capacidad 50 por bus. |
| Modelo de la API | `app/servicios/inferencia.py`: líneas base B1 (media de la misma hora y día de las 8 semanas anteriores) y B2 (misma hora hace 7 días), y el candidato `HistGradientBoostingRegressor` de scikit-learn (pérdida Poisson) con dos modelos de cuantiles para P10 y P90. División cronológica: entrenamiento hasta la fecha de corte, validación los 61 días siguientes, prueba el resto. Semilla 42. Artefacto en `datos/modelos/<model_id>/modelo.joblib` con `manifest.json` (SHA-256, `feature_version`, `data_cutoff`, métricas, hiperparámetros) y registro en `model_registry`. |

**Modelo activo que viaja en la entrega:** `hgb_fv1_20250831_s42` (entrenado hasta el 31-08-2025, validación
sep.-oct. y prueba reservada nov.-dic. de 2025). WAPE horario en la prueba: **15,07 %** frente a 21,18 % de la regla
manual B1 y 26,40 % de B2; cobertura de la banda P10-P90: 80,9 % (nominal 80 %). Las cifras salen de su
`manifest.json`; si se reentrena, cambian ahí y en `model_registry`.

La regla de gobierno de §5.1 se cumple guardando los umbrales en `ai_frecuencias.threshold_config`, con versión: se
cambian sin recompilar.

## Limitaciones

- La base del reto es histórica (termina el 31-12-2025): la «llegada de datos nuevos» se simula con los días de 2025.
- El modelo de la API pronostica la hora y la prorratea por minutos en la ventana pedida (30, 60 o 120 min), con un factor
  intradía (observado / esperado en las 2 h previas, recortado a 0,8-1,25) que solo usa horas ya cerradas. Los modelos del
  informe (E11, E12) se evaluaron a 7 días; aquí se usan como referencia y en el plan D5.
- La elasticidad β ≈ 0,70 (0,55-0,90) sale de fallas imprevistas, no de recortes planificados: el saldo económico del plan
  depende de ella y debe medirse con el piloto propuesto en el informe.
- Notificaciones simuladas; sin autenticación (prototipo académico); sin prueba de carga con k6 ni análisis en un
  servidor SonarQube todavía. Estado de cada requisito: `../MATRIZ_CUMPLIMIENTO.md`.

## Documentación

`docs/manual_tecnico.md` · `docs/manual_usuario.md` · `docs/despliegue.md` · `docs/integracion_postgresql.md` ·
`../PLAN_EVOLUCION.md` · `../MATRIZ_CUMPLIMIENTO.md`
