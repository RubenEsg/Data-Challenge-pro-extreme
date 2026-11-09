# Manual técnico · API de frecuencias

Este manual es para quien mantiene, despliega o extiende la API. Los otros documentos son:

- visión general, inicio rápido y tabla de endpoints: `../README.md`;
- uso diario del tablero y de la API: `manual_usuario.md`;
- despliegue con Docker Compose: `despliegue.md`;
- integración con la base operacional de Extreme: `integracion_postgresql.md`;
- hallazgos y preguntas para Extreme (H1 a H16): `hallazgos_extreme.md`;
- índice de evidencias para el jurado: `evidencias/README.md`.

Todas las rutas de archivo de este manual son relativas a `api_frecuencias/`, salvo que se diga otra cosa.

## 1. Arquitectura

La especificación v1.5 (§7.1) pide una arquitectura modular. Cada etapa del flujo (ingesta, dominio operacional,
analítica, inferencia, optimización, alertas y exposición) es un módulo propio de `app/servicios/`. La API REST es una
capa delgada encima de ellos.

```
  Base operacional de Extreme (o su réplica)            Base de resultados (PostgreSQL 14 + PostGIS)
  ┌──────────────────────────────────────────┐          ┌──────────────────────────────────────────┐
  │ timbradas_segmentos, timbradas_anio,     │          │ esquema ai_frecuencias (Alembic 0001→)   │
  │ timbradas_consolidado, rutas, "Procesos",│          │  execution_log · execution_attempt       │
  │ progvehiculos, novedades_viales_*, ...   │          │  data_quality_error · demanda_observada  │
  │ triggers y funciones SIN CAMBIOS         │          │  prediction · feature_snapshot (mensual) │
  └───────────────────┬──────────────────────┘          │  recommendation · alert · alert_history  │
                      │ usuario lector_ia: SELECT,      │  model_registry · model_monitoring       │
                      │ READ ONLY, statement_timeout,   │  threshold_config · notification_log     │
                      │ marca de agua + solape + huella └───────────────────▲──────────────────────┘
                      ▼                                                     │ usuario escritor_ia
  ┌──────────────────────────────────────────────────────────────────────┐ │ (solo ai_frecuencias)
  │ API FastAPI (app/main.py) · N réplicas sin estado                    │─┘
  │  routers/  → validan, autorizan (X-API-Key y rol) y llaman a servicios│
  │  servicios/ → fuentes → calidad → ingesta → inferencia → optimización │──► /api/v1/... (OpenAPI 3, Swagger)
  │               → alertas → notificaciones → monitoreo → política       │──► /metrics (Prometheus) · /health
  │  cola en PostgreSQL + planificador interno (APScheduler)              │──► logs JSON · trazas OTLP (Jaeger)
  └──────────────────────────────────────────────────────────────────────┘
                      ▲
                      │ HTTP con X-API-Key (SOBUSA_API_URL, SOBUSA_API_KEY)
  Tablero Dash (../dash_app): pantallas Alertas, Recomendaciones, Operación y Monitoreo, y la tarjeta de Inicio
  con la respuesta a la pregunta del reto
```

Hay dos fuentes de datos, intercambiables por variable de entorno (`FUENTE`):

- **`parquet`** (por omisión): las exportaciones del reto en `datos/`. No usa red y es reproducible.
- **`postgres`**: la base de Extreme o su réplica, siempre en solo lectura.

Reglas del código:

- `app/servicios/` no importa FastAPI y se prueba solo.
- `app/routers/` no tiene lógica de negocio: valida la entrada, llama al servicio y guarda.
- Toda escritura va al esquema `ai_frecuencias`. Ningún módulo escribe en las tablas de Extreme (§8.3, §11.3).

## 2. Módulos

### 2.1 Núcleo (`app/`)

| Archivo | Responsabilidad |
|---|---|
| `main.py` | Aplicación FastAPI: registro de routers bajo `/api/v1` con `seguridad.autenticar`, middleware de `X-Correlation-Id`, manejo uniforme de errores, `/health` y `/metrics`. Al arrancar, recupera las ejecuciones interrumpidas y arranca la cola y el planificador. |
| `config.py` | `Ajustes` (pydantic-settings): toda la configuración sale de variables de entorno o del `.env` (§7.1). Las URL de base tienen `repr=False` para que nunca aparezcan en un log. |
| `db.py` | Motor SQLAlchemy 2 con psycopg 3, sesiones y `base_disponible()`. |
| `modelos_db.py` | Tablas ORM del esquema `ai_frecuencias`. |
| `esquemas.py` | Modelos Pydantic 2 de entrada y salida: son el contrato OpenAPI. |
| `openapi_doc.py` | Completa el OpenAPI para que diga exactamente lo que la API responde: los errores de cada operación con el esquema uniforme `RespuestaError`, `/metrics` como texto, las exportaciones como CSV y XLSX, el rol mínimo de cada operación (`x-rol-minimo`) y los filtros «uno de varios» (`x-requiere-uno-de`). Además instala la guarda `GuardaNul` (422 ante el byte NUL) y el manejador de valores fuera de rango (422 `fuera_de_rango`). Ver la sección 2.4. |
| `seguridad.py` | Claves de API por rol y matriz de permisos `POLITICA` (§7.2). |
| `observabilidad.py` | Logs JSON con structlog, variables de contexto (`correlation_id`, `execution_id`, `worker_id`) y trazas OpenTelemetry. |

### 2.2 Servicios de dominio (`app/servicios/`)

| Módulo | Qué hace | Requisitos |
|---|---|---|
| `fuentes.py` | `FuenteParquet` y `FuentePostgresSoloLectura`. La segunda valida que el SQL sea solo `SELECT`, abre `SET TRANSACTION READ ONLY` con `statement_timeout` y `TimeZone='America/Bogota'` y termina con `ROLLBACK`. Lee por marca de agua con una ventana de solape (`FUENTE_SOLAPE_MIN`) y una huella md5 por llave natural: una fila tardía o modificada se entrega una sola vez. | RF-001, RF-002, RF-013, §8.3, §11.3 |
| `calidad.py` | `validar_lote(df, lote, catalogos, ahora)`: completitud, validez, unicidad, consistencia, oportunidad y relacional (§6.3). Cada error lleva lote, fila, llave del registro, campo, valor, código, dimensión, detalle y si bloquea. | RF-004, §6.3, §14.2 |
| `dimensiones.py` | Dimensiones de §8.3 de cada fila de resultados (`idruta`, `idempresa`, `idproceso`, `id_dia_semana` e `id_estacionalidad`), desde el catálogo empaquetado o, en modo integrado, desde la réplica. | §8.3 |
| `ingesta.py` | Incorpora las filas válidas a `demanda_observada` con `COPY` a una tabla de paso y un `INSERT … ON CONFLICT … WHERE … IS DISTINCT FROM`, en la misma transacción de la ejecución. Una carga repetida no duplica. | RNF-003, §14.2 |
| `datos.py` | Vista analítica `demanda_horaria` y catálogo de rutas (capacidad, ciclo, flota y frecuencia actual). | §6.1 |
| `variables.py` | Variables del modelo por versión (`VERSIONES`: fv1 y fv2), sin información posterior al instante de predicción. | §9.2, §9.3 |
| `inferencia.py` | Entrena, registra, carga (verifica el SHA-256 y la versión de variables), predice con banda P10–P90 calibrada y explicación local SHAP, y evalúa (MAE, RMSE, WAPE, sMAPE y sesgo, por ruta, pico y valle). | RF-005, RF-006, RF-015, §9 |
| `onnx_motor.py` | Motor ONNX Runtime alternativo (`MOTOR_INFERENCIA=onnx`). | §9.1, §9.2 |
| `optimizacion.py` | `recomendar` (línea base de §10.3), `optimizar` (función objetivo de §10.2 como MILP de la franja con PuLP/CBC), `recomendacion_franja`, comparación con la frecuencia programada, escenarios y sensibilidad, y `plan_dia_d5` (MILP del día, copia en `motor_d5/`). | RF-007, RF-008, §10 |
| `alertas.py` | Reglas ALT-001 a ALT-010 (`evaluar_alertas` sobre el pronóstico y `evaluar_observadas` sobre los datos reales), episodios, deduplicación, máquina de estados `TRANSICIONES` y seudónimo del conductor. | RF-009, RF-010, RF-011, §5 |
| `notificaciones.py` | Adaptadores de correo y WhatsApp configurables. El envío se simula y queda en `notification_log`. | RF-012 |
| `monitoreo.py` | Monitoreo por ejecución: WAPE, MAE y sesgo móviles de 28 días, cobertura, PSI por variable, volumen y porcentaje de alertas descartadas. También guarda la foto de variables (`feature_snapshot`). | §9.4, §11.2 |
| `politica.py` | Aprendizaje continuo: cuándo reentrenar, retador en sombra, compuerta, activación auditada y reversión automática. | RF-018, RF-019, §9.5 |
| `ejecucion.py` | Orquesta el ciclo de frecuencia y el de entrenamiento. Todo queda ligado a `execution_id`, `model_id`, `feature_version`, `umbrales_version` y `data_cutoff`. | RF-013, RNF-011 |
| `cola.py` | Cola de trabajos en PostgreSQL para N réplicas. | RNF-001, RNF-004, RNF-005 |
| `planificador.py` | Planificador interno (APScheduler): ejecución diaria y revisión semanal del reentrenamiento. | §7.2, §9.5 |
| `circuito.py` | Circuit breaker de la base fuente y de los notificadores. | RNF-010 |
| `catalogos.py` | Catálogos de solo lectura (procesos, empresas, rutas, segmentos, vehículos, viajes y despachos) y ajuste local de capacidad, versionado en `threshold_config`. | §3.1, §3.2, §8.3 |
| `segmentos.py` | Capa analítica por segmento (§6.1) y por zona tarifaria (§6.2). | §6.1, §6.2, §11.2 |
| `tipologias_flota.json` | Tipologías de capacidad por ruta, sin placas (lo genera `scripts/preparar_tipologias.py`). | §10.1 |
| `respuesta.py` | Arma la respuesta a la pregunta final del reto por ruta y día con los servicios anteriores, sin modelar nada nuevo: plan del día, pronóstico con banda, vehículos frente a la flota, flota y recaudo, y alertas abiertas, con su trazabilidad. Lo usan `GET /api/v1/respuesta` y `GET /api/v1/respuesta/export` (una fila por ruta y hora, CSV o XLSX); una fecha sin plan responde 404 `sin_datos`. | §20 |

### 2.3 Routers (`app/routers/`)

`ejecuciones.py` (`/frequency/executions`), `predicciones.py` (`/predictions` y `/recommendations`),
`pronostico_segmentos.py` (`/predictions/segmentos`), `alertas.py` (`/alerts`), `modelos.py` (`/models`),
`umbrales.py` (`/thresholds`), `monitoreo.py` (`/monitoring`), `planificador.py` (`/scheduler`), `catalogos.py`
(`/catalogos`), `segmentos.py` (`/segmentos`) y `respuesta.py` (`/respuesta`). `comun.py` reúne la paginación
(`ParametrosPagina`), el error uniforme (`ErrorApi`) y las exportaciones CSV o XLSX. La lista completa de rutas, con
el rol que exige cada una, está en `../README.md`, sección «Endpoints».

### 2.4 Contrato de la API: errores, roles y filtros

El contrato está en `docs/openapi.json` (OpenAPI 3.1: 59 rutas y 62 operaciones, 60 bajo `/api/v1`) y lo verifican las
pruebas de `tests/contrato/` contra las respuestas reales (Schemathesis con cinco chequeos en cada operación:
`docs/evidencias/contrato/schemathesis.txt`).

- **Error uniforme (§12.1).** Todo error responde `{"error": {"codigo", "mensaje", "detalle", "correlation_id"}}` con la
  cabecera `X-Correlation-Id`, también los que no pasan por un router:

  | Código HTTP | `codigo` | Cuándo |
  |---|---|---|
  | 400 | `cuerpo_ilegible` | El cuerpo no se puede decodificar (por ejemplo, bytes que no son UTF-8 en un JSON). Está documentado en las 9 operaciones con cuerpo. |
  | 401 | `no_autenticado` | Falta `X-API-Key` o la clave no es válida; trae `WWW-Authenticate`. |
  | 403 | `prohibido` | El rol de la clave está por debajo del rol mínimo; `detalle` trae `rol` y `rol_requerido`. |
  | 404 | `no_encontrado` (o uno más específico, como `sin_datos` o `sin_calcular`) | El recurso no existe. `sin_calcular`: el plan del día o la foto de la respuesta del reto todavía no están calculados para esa fecha; el error trae la pista de `POST /api/v1/respuesta/calcular`. |
  | 409 | `transicion_invalida`, `activacion_rechazada`, `requiere_forzar`, `ya_activo`, … | Conflicto con el estado actual. Cada operación enumera sus códigos en `x-codigos-error` del OpenAPI (`app/openapi_doc.py`, `CODIGOS_POR_OPERACION`; `docs/evidencias/contrato/operaciones_codigos.txt`). |
  | 422 | `validacion` | La entrada no es válida. `detalle` es una lista de `{campo, mensaje, tipo}`; el byte NUL (0x00 o `%00`) en la ruta, la consulta, una cabecera o un cuerpo JSON da `tipo` = `caracter_nulo` (guarda `GuardaNul`, antes de llegar a SQL). |
  | 422 | `fuera_de_rango` | Un valor válido pero imposible de procesar, como `hasta=9999-12-31` (desborde de fechas). |
  | 500 | `error_interno` | Error no controlado; el `correlation_id` lo ubica en el log. |
  | 503 | según la dependencia | Réplica, base operacional o archivo de insumos no disponible (RNF-010). |

- **Rol mínimo en el contrato.** Cada operación de `/api/v1` lleva su rol mínimo en `x-rol-minimo` y en una línea de su
  descripción (50 de operador, 5 de analista y 5 de admin). El 403 solo se declara donde ese rol es mayor que
  operador: un operador no puede recibir 403 en una lectura. Las operaciones que exigen uno de varios filtros
  (`/predictions/segmentos` y `/monitoring/feature-snapshots`) lo dicen en `x-requiere-uno-de`.
- **Filtro espacial de alertas (§8.1).** `GET /api/v1/alerts` y `/alerts/export` aceptan `cerca_de=lat,lon` (WGS84) y
  `radio_m` (por omisión 1.000 m; máximo 50 km, si no 422). Con PostGIS se resuelve con `ST_DWithin` sobre
  `ubicacion geography(Point,4326)` y su índice GiST `ix_alert_ubicacion`; sin PostGIS, con la distancia haversine sobre
  la ubicación guardada. Con la fuente Parquet las alertas no traen coordenadas, así que el filtro devuelve 0 alertas.
- **Instantes en Bogotá (§8.1).** Se guardan en UTC y salen en ISO-8601 con `-05:00`, también dentro de los campos JSON
  (comentarios, variables, métricas) y en las celdas de las exportaciones.
- **Exportaciones (`formato=csv|xlsx`).** Toda exportación que arma `exportar()` de `app/routers/comun.py` responde con dos
  cabeceras, declaradas en el OpenAPI: `X-Total-Count` (los registros que cumplen el filtro, aunque el archivo traiga
  menos) y `X-Truncado` (`true` si el archivo se cortó en el tope de 100.000 filas, `LIMITE_EXPORTACION`; entonces hay
  que afinar los filtros para exportar el resto).

Pruebas: `tests/contrato/test_contrato_openapi.py` (`test_cuerpo_ilegible_es_400_uniforme_y_documentado`,
`test_byte_nul_es_422_uniforme`, `test_valores_fuera_de_rango_son_422`, `test_filtro_espacial_de_alertas` y
`test_alerta_sin_postgis_usa_haversine`); contra un servidor real: `docs/evidencias/contrato/en_vivo_uvicorn.txt`.

## 3. Una ejecución por dentro

`POST /api/v1/frequency/executions` (rol analista) crea una fila en `execution_log` con estado `en_cola`, guarda el
`traceparent` W3C de la petición y responde 202 con el `execution_id`. Un trabajador de la cola la reclama y corre
`ejecucion._ciclo_frecuencia`, que actualiza `estado`, `etapa` y `progreso` (se ven en
`GET /api/v1/frequency/executions/{id}`):

| Etapa (`etapa`) | Progreso | Qué hace | Dónde queda |
|---|---|---|---|
| `lectura_incremental` | 10 | `fuentes.leer_con_estado(fuente, marca_anterior, hasta, estado_anterior)`: solo lo posterior a la marca de agua de la última ejecución exitosa, con solape y huella. | `metricas.lectura` (leídas, entregadas, nuevas, tardías, modificadas y repetidas en el solape) |
| `calidad` | 25 | `calidad.validar_lote(df, lote, catalogos, ahora)` con los catálogos y el reloj del ciclo. Cada error trae `llave` (las columnas llave del registro, para encontrarlo sin depender del orden del lote), `valor` (el texto de la celda) y `bloqueante`. Las filas con un error bloqueante no siguen; los errores de oportunidad son informativos. En el consolidado, la llave es la de 7 columnas de `fuentes.LLAVES`, y `hora_fin = 00:00` cuenta como 24:00. | `data_quality_error` (`GET …/{id}/errors`, filtrable por `idruta`) |
| histórico | — | `ingesta`: las filas válidas pasan a `demanda_observada` sin duplicar. | `metricas.incorporadas_historico` |
| evaluación | — | `inferencia.evaluar` del modelo activo sobre los días recién llegados (paso 3 del ciclo de §14.2). | `metricas.evaluacion_error` |
| monitoreo | — | `monitoreo.en_ciclo`: WAPE móvil por ruta (alimenta ALT-010), deriva y cobertura. | `model_monitoring` |
| `prediccion` | 45 | `inferencia.predecir` por ruta y horizonte (30, 60 y 120 min), seguida de la recomendación de la franja con `optimizacion.recomendacion_franja`: la función objetivo de §10.2 con la demanda por hora de la hora principal de la ventana y su banda calibrada. | `prediction`, `recommendation` |
| `alertas` | 70 | `alertas.evaluar_alertas` sobre cada pronóstico y `evaluar_observadas` (ALT-005 a ALT-009) sobre las horas cerradas del último día recibido. Una alerta redetectada con más severidad se escala (sección 6). | `alert`, `alert_history` |
| `notificaciones` | 85 | Las alertas nuevas que alcanzan `NOTIFICACIONES_SEVERIDAD`, y las que se escalan a crítica, van a los canales configurados. | `notification_log` |
| `plan_dia` | 92 | El plan del día siguiente por ruta con el modelo activo (`optimizacion.plan_dia`, sección 7) y la foto de la respuesta del reto para esa fecha (`respuesta.precalcular`), en la misma transacción. Si este paso falla, la ejecución termina `ok` y la advertencia queda en `metricas`. | `recommendation` con `origen = 'plan_dia'` (una fila por ruta y hora), `respuesta_reto` |
| cierre | 100 | `monitoreo.cerrar_ciclo` (foto de variables, retador en sombra y política) y `cola.cerrar_ok`. | `feature_snapshot`, `execution_log` |

Tres garantías del diseño:

- **Exactamente una vez.** El cierre `ok` (`cola.cerrar_ok`) va en la **misma transacción** que los resultados.
  Además, solo confirma quien todavía tiene la reserva del trabajo. Si el proceso muere antes, no queda nada a medias
  y otra réplica retoma el trabajo.
- **Sin datos nuevos no se reprocesa el histórico.** La ejecución termina con la nota «Sin datos nuevos desde la marca
  de agua». Aun así, revisa la frescura de los datos (ALT-009).
- **Trazabilidad (RNF-011).** Cada predicción guarda `model_id`, `feature_version`, `data_cutoff`, `generated_at`,
  horizonte, latencia y explicación (§9.2). Cada recomendación de franja guarda su `prediction_id` y su
  `umbrales_version`; las del plan del día, su `origen` y la fuente del pronóstico. Cada alerta guarda su
  `execution_id`.
- **Dimensiones de §8.3.** `prediction`, `recommendation`, `alert`, `demanda_observada` y `feature_snapshot` guardan
  `idruta`, `idempresa` e `idproceso` (del catálogo `datos/catalogo_rutas.json` o de la réplica en modo integrado),
  `id_dia_semana` (ISO 1 a 7) e `id_estacionalidad` (nulo para Sobusa, porque `estacionalidades_anio` es de otro
  proceso: H1 de `hallazgos_extreme.md`). Las escribe `app/servicios/dimensiones.py`, y las consultas de predicciones,
  recomendaciones, alertas y errores de calidad aceptan el filtro `idruta`.

El ciclo de entrenamiento (`_ciclo_entrenamiento`) usa la misma cola: lo lanzan `POST /api/v1/models/train`, la
política o el planificador.

## 4. Trabajos asíncronos, cola y planificador

- **Cola en PostgreSQL** (`app/servicios/cola.py`, migración 0002). El reclamo usa `SELECT … FOR UPDATE SKIP LOCKED`.
  Cada trabajo tiene una reserva (*lease*, `LEASE_SEGUNDOS`) que un latido renueva. Los reintentos esperan de forma
  exponencial (`espera_reintento`) hasta `MAX_REINTENTOS`. Cada intento queda en `execution_attempt`. Hay tres tipos
  de trabajo (`execution_log.tipo`): `frecuencia` (el ciclo diario), `entrenamiento` (un candidato en sombra) y
  `respuesta` (la foto de la respuesta del reto, que encola `POST /api/v1/respuesta/calcular`).
  - Las ejecuciones de frecuencia se serializan en todo el clúster, porque dependen de una sola marca de agua. El
    parámetro `rutas` limita la predicción, no la lectura ni la ingesta. Frente a RNF-005 («particionable por ruta y
    fecha») es una limitación declarada: las réplicas se reparten las ejecuciones, pero no parten una misma ejecución
    (`PLAN_EVOLUCION.md`, sección 2).
  - Los entrenamientos y las fotos de la respuesta pueden correr en paralelo.
- **Recuperación tras un reinicio (RNF-001).** Al arrancar, `ejecucion.recuperar_interrumpidas()` devuelve a la cola
  lo que dejó a medias el proceso anterior y lo de reservas vencidas. Lo comprueban:
  - `docs/evidencias/cola/caida_rnf001.txt`, con procesos;
  - `docs/evidencias/cola/caida_rnf001_docker.txt`, con `docker kill`;
  - `PRUEBA_CAIDA=1 pytest tests/integracion/test_caida.py`.
- **N réplicas (RNF-005).** `docker-compose.replicas.yml` levanta dos réplicas de la API. Evidencia:
  `docs/evidencias/cola/replicas.txt` (20 ejecuciones repartidas 10/10, 0 duplicados).
- **Planificador (§7.2).** Con `PLANIFICADOR_HABILITADO=true`:
  - `PLAN_EJECUCION_CRON` programa la ejecución diaria (por omisión `15 5 * * *`);
  - `PLAN_REENTRENAMIENTO_CRON` programa la revisión de reentrenamiento (por omisión `0 4 * * 1`).
  - Aunque haya varias réplicas, cada franja se encola una sola vez. El estado se consulta en `GET /api/v1/scheduler`.
    Evidencia: `docs/evidencias/cola/planificador.txt`.

## 5. Ciclo de vida del modelo

```
 entrenar ──► candidato ──► sombra (14 días) ──► compuerta ──► activo ──► monitoreo ──► reversión
 (train)      (registro)    (predice aparte)     (4 criterios) (auditado) (model_monitoring)  (manual o automática)
```

1. **Entrenar.** Se entrena con `POST /api/v1/models/train` (job) o con `scripts/entrenar.py`.
   - Modelo: `HistGradientBoostingRegressor` de scikit-learn con pérdida Poisson para el punto, y dos modelos de
     cuantiles (0,1 y 0,9) para la banda.
   - Partición cronológica: entrenamiento hasta la fecha de corte, validación los 61 días siguientes y prueba
     reservada el resto (§9.3).
   - Semilla 42.
   - El artefacto queda en `datos/modelos/<model_id>/` (`modelo.joblib` y `manifest.json` con SHA-256,
     `feature_version`, `data_cutoff`, métricas e hiperparámetros) y en `model_registry`. `registrar_modelo` nunca
     sobrescribe al modelo activo.
2. **Cargar.** `inferencia.cargar()` lee el artefacto una sola vez y verifica el SHA-256 y la versión de variables.
   Si no coinciden, falla (§9.2). La calibración de la banda P10–P90 también es un archivo versionado junto al
   artefacto: `calibracion_v2.json` (calibración v2, conformal por grupo de bloque horario, con su SHA-256 en la clave
   `calibracion` del manifiesto). Cada predicción guarda qué versión produjo su banda (`calibracion_version`). Con
   `CALIBRACION_BANDA=v1` la API vuelve a la v1 (conformal móvil por ruta con los días previos), aunque el modelo traiga
   la v2. En la prueba reservada, la v2 da una cobertura de 77,82 % (v1: 77,88 %) con un ancho medio de 303,4
   pasajeros (v1: 312,9). Cómo se eligió, solo con la validación y sin tocar la prueba reservada:
   `docs/evidencias/modelo/calibracion_condicional.md` (`scripts/calibrar_por_grupo.py`).
   Con una sesión de la base de resultados (la del ciclo y la de la API), las variables y los valores reales de la
   inferencia, la evaluación, el monitoreo y la compuerta salen de `politica.serie_validada`: el Parquet empaquetado
   con las horas validadas de `demanda_observada` encima, recalculando solo los días tocados y los 56 siguientes. Así,
   un día nuevo que llega por el ciclo actualiza las variables (RF-013) y se puede pronosticar después del fin del
   Parquet. Sin sesión (los scripts de evidencia y las pruebas unitarias) se usa solo la serie empaquetada, y
   `INFERENCIA_SERIE=validada` hace que un proceso abra su propia sesión de solo lectura.
   El ciclo pronostica todas las horas de un día en lote (`inferencia.predecir_horas`), con el mismo resultado que hora
   por hora (`docs/evidencias/modelo/predecir_horas_lote.json`).
3. **Sombra.** Con `datos_hasta`, o cuando lo pide la política, el candidato predice en paralelo 14 días. Sus
   predicciones quedan en `model_monitoring` con rol `sombra` y no se mezclan con las del activo.
4. **Compuerta** (`politica.compuerta`). Exige cuatro criterios en la misma ventana:
   - WAPE ≤ el del activo;
   - WAPE ≤ `wape_max`;
   - cobertura P10–P90 entre 75 y 90 %;
   - |sesgo| ≤ 5 %.

   Ejemplo: `docs/evidencias/monitoreo/compuerta_ejemplo.json`. Ilustra el cálculo en una ventana que cae dentro de la
   validación de los dos modelos (2025-09-01..14), así que no es una evaluación fuera de muestra: aprueba a
   `hgb_fv1_20250831_s42` en el papel, pero no cambió el modelo activo, y `POST /activate` rechazaría esa ventana con
   422 `ventana_en_muestra`. La compuerta fuera de muestra de la demostración de §14.2 está en
   `docs/evidencias/despliegue/demo_esperado.md`.
5. **Activar** (`POST /api/v1/models/{id}/activate`, rol admin, `app/routers/modelos.py`). La activación manual no se
   salta la gobernanza:
   - aplica la misma compuerta de cuatro criterios, con los dos modelos en la misma ventana y cada uno con su banda
     calibrada, sobre la serie validada;
   - la ventana (`validacion_desde` y `validacion_hasta` en el cuerpo; por omisión, los 28 días siguientes) tiene que
     empezar después de todo lo que vio el candidato: su corte más los 61 días de validación o, si es mayor, el fin de
     su sombra. Si no, responde 422 `ventana_en_muestra` con `limite_en_muestra` en el detalle; si todavía no hay datos
     validados después de ese límite, 409 `sin_datos_validacion`;
   - si algún criterio falla, el candidato queda `rechazado` y responde 409 `activacion_rechazada` con la comparación;
   - un modelo ya rechazado o todavía en sombra responde 409 `requiere_forzar`: así no se puede probar una ventana tras
     otra hasta que alguna apruebe, ni saltarse la sombra;
   - `?forzar=true` lo activa aunque no apruebe, pero exige un `motivo` en el cuerpo (si falta, 422
     `motivo_requerido`) y deja en la auditoría el evento `activacion_forzada` con los criterios no cumplidos.

   La auditoría registra al usuario autenticado y guarda el activo anterior en `anterior_model_id`. Además, con
   `activacion_automatica` = 1 (el valor por omisión de `threshold_config`), la política activa sola al retador que pasa la compuerta de sombra, también con
   auditoría (`aprobado_por = politica_automatica`); con 0, el retador espera la aprobación de un admin.
6. **Monitorear** (`GET /api/v1/monitoring`). La deriva (PSI), el error móvil, la cobertura, el volumen y el
   porcentaje de alertas descartadas se miden en cada ejecución. ALT-010 se dispara si el WAPE móvil pasa la
   tolerancia.
7. **Revertir.** `POST /api/v1/models/rollback` (admin) vuelve al anterior. La política también revierte sola si el
   modelo nuevo se degrada en sus primeros 7 días.

Cuándo se reentrena (`GET /api/v1/monitoring/policy`): por periodicidad, por degradación (3 ejecuciones seguidas sobre
`wape_max`), por deriva o por cobertura baja. Los umbrales están versionados en `threshold_config`.

El modelo que viaja en la entrega es `hgb_fv2_20250831_s42` (activo en `datos/modelos/registro.json`). Su evaluación en
la prueba reservada (nov.–dic. 2025) está en `docs/evidencias/modelo/evaluacion_modelo.md`, y la decisión de usarlo, en
`docs/evidencias/modelo/decision_fv2.md`. Esa prueba se consultó al elegir fv2 frente a fv1, así que su cifra es
informativa: el criterio de selección fue la validación y los backtests con modelos congelados en 2024 y 2025, y se pide
a Extreme un periodo de 2026 como prueba limpia. Las métricas de la prueba solo las calcula `scripts/evaluar_modelo.py`. Para reproducir el entrenamiento:

```
.venv\Scripts\python scripts\entrenar.py --hasta 2025-08-31 --semilla 42 --compuerta-activo --verificar-reproducible
.venv\Scripts\python scripts\evaluar_modelo.py
.venv\Scripts\python scripts\evaluar_horizontes.py
.venv\Scripts\python scripts\exportar_onnx.py            (artefacto ONNX con su SHA-256 en el manifiesto)
```

Estos scripts escriben en `DATA_DIR` y `MODELOS_DIR`. Para un ensayo, apúntelos a una copia temporal: así el registro
del repositorio no cambia.

## 6. Motor de alertas (`app/servicios/alertas.py`)

- **Catálogo de §5.2.** Hay dos familias de reglas:
  - sobre el pronóstico: ALT-001 alta demanda, ALT-002 sobreocupación, ALT-003 frecuencia insuficiente, ALT-004
    frecuencia excesiva y ALT-010 modelo degradado;
  - sobre lo observado en las horas cerradas: ALT-005 caída, ALT-006 despacho ausente o tardío, ALT-007 desviación
    del pronóstico, ALT-008 consolidado anómalo y ALT-009 datos incompletos o atrasados.
- **Umbrales versionados (§5.1).** Los valores por omisión están en `UMBRALES_POR_DEFECTO`. Los vigentes se leen de
  `threshold_config`, y `PUT /api/v1/thresholds` (admin) crea una versión nueva sin recompilar. Una versión nueva es
  una propuesta hasta que el área operativa la aprueba con `POST /api/v1/thresholds/{version}/aprobar` (admin), que
  firma `aprobado_por` y `aprobado_en`; `GET /api/v1/thresholds` dice si la versión vigente está aprobada. Cada
  alerta guarda la versión que usó.
- **Estructura de §5.3.** Cada alerta guarda:
  - lo que identifica el caso: código, empresa, ruta, sentido, viaje, vehículo y conductor (solo un seudónimo);
  - el tiempo: detección, ventana y horizonte;
  - la evidencia: severidad, estado, observado, esperado, umbral, probabilidad o puntaje con su método, tendencia y
    serie reciente;
  - la lectura: explicación, variables influyentes (SHAP) y recomendación;
  - la gestión: asignado, comentarios y bitácora.

  La tabla campo por columna está en `docs/evidencias/alertas/README.md`.
- **Alertas de pronóstico por hora.** ALT-001 y ALT-002 comparan pasajeros por hora con puestos por hora en la hora
  recomendada: la ventana de la alerta es esa hora. Hay una alerta por franja, con los horizontes que la produjeron en
  `variables.horizontes_min`, y las variables traen `unidad_demanda` y `demanda_ventana`.
- **Episodios y deduplicación.** Las horas consecutivas que cumplen la misma condición forman un episodio con una clave
  estable. Hay una sola alerta abierta por clave: si el episodio sigue, se actualiza la misma alerta, suben las
  ocurrencias y la bitácora guarda `redeteccion`.
- **Escalamiento (§7.2).** Si la redetección trae una severidad mayor, la alerta abierta sube a esa severidad y la
  bitácora guarda una entrada `escalar` (el estado no cambia). Si queda crítica, se notifica al cerrar el ciclo. La
  severidad nunca baja sola: una redetección más leve solo suma la ocurrencia (`ejecucion.escalar_alerta`; prueba
  `tests/integracion/test_api_integracion.py::test_redeteccion_mas_grave_escala_y_notifica`).
- **Estados.** El flujo es `nueva` → `reconocida` → `asignada` → `cerrada`. Desde `nueva`, `reconocida` o `asignada`
  se puede `descartar`, y `comentar` no cambia el estado. Una transición no permitida responde 409
  `transicion_invalida`. Cada cambio queda en `alert_history` con el usuario autenticado.
- **Ubicación.** `ubicacion geography(Point,4326)` tiene un índice GiST (migración 0003, §8.1). `GET /api/v1/alerts` y
  `/alerts/export` filtran por lugar con `cerca_de=lat,lon` y `radio_m` (sección 2.4).
- **Medición del volumen de alertas (§18).** `scripts/backtest_alertas.py` cuenta las alertas por ruta y día y su
  precisión aproximada. Del 15-09 al 31-12-2025 (324 días-ruta), con la calibración v2, las reglas sobre datos
  observados dejan 1,238 alertas por ruta y día en total, con la ALT-002 observada (0,691) y la ruptura de RF-009
  (0,012); las que ya medía la versión anterior (ALT-005 a ALT-009) son 0,534, frente a 6,08 con las reglas anteriores
  (`docs/evidencias/alertas/backtest_alertas.md`). Las de pronóstico, por hora de la franja recomendada, se cuentan
  aparte: ALT-001 0,435, ALT-002 0,315, ALT-003 0,380 y ALT-004 0,031 por ruta y día (1,161), con lift de 1,77, 2,01,
  0,75 y 7,62 (`docs/evidencias/alertas/backtest_alertas_pronostico.md`). En total, 2,399 alertas por ruta y día.
- **Revisión doble (§18).** Una muestra de 96 alertas la etiquetaron dos revisores automatizados con el protocolo
  `docs/evidencias/alertas/revision_doble/protocolo.md`, y un tercero concilió los desacuerdos. Antes de conciliar, la
  kappa de Cohen es 0,943 (IC95 por bootstrap 0,854–1,0); la precisión reponderada por la población de cada código es
  0,839 (intervalo 95 %: 0,757–0,882), 0,922 en las de pronóstico y 0,509 en las observadas
  (`docs/evidencias/alertas/revision_doble/conciliacion.json`). Falta la validación del área operativa de Sobusa.

## 7. Optimizador (`app/servicios/optimizacion.py`)

- **Línea base de §10.3** (`recomendar`):
  - capacidad efectiva = capacidad × ocupación objetivo;
  - buses por hora = ⌈demanda de diseño / capacidad efectiva⌉, acotado por el headway mínimo y el máximo efectivo;
  - headway = 60 / buses por hora;
  - vehículos = ⌈ciclo / headway⌉.

  Sale siempre al lado de la recomendación optimizada, en dos versiones con su nombre:
  `linea_base_10_3_literal` (la fórmula de la especificación: factor de carga 1 y demanda puntual) y
  `linea_base_10_3` (la ajustada: demanda de diseño = factor de carga crítica de la ruta × P90, la que se compara con
  §10.2).
- **Headway máximo efectivo (supuesto S12).** min(`headway_maximo_min`, 2 × `espera_max_min`), porque la espera
  máxima de §5.1 se lee como la espera media del pasajero, igual a la mitad del headway con llegadas aleatorias
  (`headway_maximo_efectivo`, `REGLA_ESPERA`). Rige en la recomendación por franja y en el plan del día, y la
  respuesta dice qué umbral manda. En el plan del día entra además el máximo por tipo de día del optimizador D5 (10 min
  en laboral y sábado, 15 min en domingo y festivo), así que con los umbrales vigentes el máximo es de 10 min en todos
  los días. Bajar `espera_max_min` con `PUT /api/v1/thresholds` acorta el headway máximo y puede volver no viable una
  hora (`tests/unit/test_respuesta.py::test_espera_maxima_acota_el_headway_maximo_d1`). La duda va a Extreme como H14
  (`docs/hallazgos_extreme.md`).
- **Función objetivo de §10.2** (`optimizar`, MILP de la franja con PuLP/CBC). Minimiza α·costo_operativo +
  β·tiempo_espera + γ·penalización_sobreocupación + δ·desviación_frecuencia, sujeto a:
  - headway mínimo y máximo;
  - capacidad efectiva ≥ el cuantil del nivel de servicio (0,90 = el P90 calibrado);
  - flota y ciclo;
  - flota por tipología (§10.1).

  Los pesos están en `PARAMETROS_OBJETIVO` y se pueden versionar en `threshold_config`. La respuesta dice de dónde
  salió cada peso.
- **Inviable (§18).** La respuesta trae `viable = false` con el motivo y las cifras. Además da la mejor aproximación
  ejecutable, que nunca viola una restricción dura.
- **Headway vigente.** La especificación lo toma «de la frecuencia de despachos». La API usa el intervalo programado
  que se observa en los datos (mediana de 2025 por ruta, tipo de día y hora; en día laboral, 7,2 min en SILENCIO,
  3,5 min en CRA 54 y 11,6 min en CL 72, `datos/catalogo_rutas.json`). No usa `rutas.frecuenciadespachos`, porque vale
  5 en las tres rutas y no cambia por hora ni por tipo de día. Ese valor se conserva en el catálogo como
  `frecuenciadespachos_tabla_rutas`, para compararlo.
- **RF-008.** `comparacion_actual` pone la frecuencia programada frente a la recomendada. `escenario` responde «qué
  pasa si» y `sensibilidad` hace 23 variaciones de un parámetro a la vez.
- **Plan del día** (`plan_dia`): el MILP D5 del proyecto, copiado en `app/servicios/motor_d5/` (de dónde sale cada
  archivo y qué se cambió a propósito está en `app/servicios/motor_d5/PROCEDENCIA.md`), alimentado con el pronóstico
  horario P10/P50/P90 del modelo activo, de 4 a 20 h, para cualquier fecha que tenga variables.
  - Respeta la flota, el headway máximo efectivo y el headway mínimo gobernado, con los valores de `threshold_config`.
  - Cada hora trae `limites_activos`, `demanda_diseno`, `margen`, `viable` y `motivo`. Una hora que pide más salidas
    de las que permite el headway mínimo sale «no viable» con su mejor aproximación ejecutable.
  - Una hora con una sola salida trae `sin_intervalo = true`: no hay intervalo entre salidas que verificar, así que el
    headway mínimo no aplica y la hora no sale «no viable» por él. Cada hora trae además `flota_disponible` y
    `costo_hora_cop`.
  - Dos cifras de vehículos, explicadas en `definicion_vehiculos`: `vehiculos_hora_pico` es el máximo por hora de
    ⌈ciclo / headway⌉ de §10.3, con headway = 60 / salidas por hora (la flota que sostendría ese ritmo un ciclo
    completo), y `buses_en_ruta_pico` es el máximo de buses en ruta a la vez con el plan (el conteo de D5 cada 15 min,
    el que limita la flota del MILP). En `docs/evidencias/optimizacion/ejemplo_plan_d5.json` (CRA 54, 19-11-2025):
    106 y 78,55, con 79 buses disponibles.
  - La trazabilidad nombra el modelo (`model_id`), la calibración (`calibracion_version`) y la fuente del pronóstico
    (`fuente_pronostico`: `modelo_activo` o `E12`).
  - El pronóstico híbrido del experimento 12 del informe, precalculado para 2025, queda como opción
    (`pronostico=E12`).
- **Plan persistido y procesos largos (§7.1).** El ciclo diario calcula el plan del día siguiente y lo guarda en
  `recommendation` con `origen = 'plan_dia'` (sección 3). `GET /api/v1/recommendations/plan` lee ese plan y no
  resuelve el MILP dentro de la petición. Si no está calculado, responde 404 `sin_calcular` con la pista de
  `POST /api/v1/respuesta/calcular`. `GET /api/v1/recommendations?origen=plan_dia` lista las mismas filas.
- **Respuesta del reto** (`app/servicios/respuesta.py`). `respuesta.precalcular` arma la respuesta completa por ruta
  con el plan del día y la guarda en `respuesta_reto` (una fila por fecha, ruta, modelo y versión de umbrales).
  `GET /api/v1/respuesta` solo lee esa foto, y las alertas de «atención inmediata» se leen en el momento. Si no hay
  foto para la fecha con el modelo y los umbrales vigentes, responde 404 `sin_calcular`;
  `POST /api/v1/respuesta/calcular` (rol analista) responde 202 con el `execution_id` de un trabajo de tipo
  `respuesta`. La foto reutiliza tal cual el plan que el ciclo acaba de calcular y persistir, si es del mismo modelo y
  de la misma versión de umbrales, así que `GET /api/v1/respuesta` y `GET /api/v1/recommendations/plan` dicen las
  mismas salidas hora por hora; el trabajo `respuesta` también persiste ese plan. Con eso la etapa `plan_dia` bajó de
  66,8 s a 2,0 s en la carga inicial (`docs/evidencias/rendimiento/ciclo_final.md`).
- **Vehículos.** Hay tres cuentas, cada una con su nombre: ⌈ciclo / headway⌉ por franja (§10.3), la suma por
  tipología y los buses en ruta a la vez del plan (`vehiculos.requeridos_pico` de `GET /api/v1/respuesta`, frente a
  `flota_disponible`). La tercera contesta la pregunta del reto (`documentos/mapeo_especificacion.md`, sección 0).
- **Elasticidad.** β estimada ≈ 0,70 por observación (informe técnico, sección 4), sin validar en campo. El plan usa
  0,5 por prudencia (`ELASTICIDAD` en `motor_d5/comun.py`). La sensibilidad está en
  `docs/evidencias/optimizacion/sensibilidad.md`, y el piloto la mide.

Evidencias: `docs/evidencias/optimizacion/LEEME.md` (índice), `sensibilidad.md` (MILP = enumeración exacta en 12
franjas reales) y `ejemplo_calculate_no_viable.json`.

## 8. Base de datos y migraciones

Todo lo nuevo vive en el esquema `ai_frecuencias` (§8.1) y se crea con Alembic (`alembic upgrade head`). La API lo
aplica al arrancar en Docker con el servicio `migrar`.

| Migración | Qué crea o cambia |
|---|---|
| `0001_esquema_ai_frecuencias.py` | `model_registry`, `execution_log`, `data_quality_error`, `demanda_observada` (UNIQUE por ruta, fecha y hora), `prediction`, `recommendation`, `alert`, `alert_history`, `threshold_config` (umbrales de §5.1, versión 1) y `notification_log`; índices compuestos ruta-fecha y alertas-estado. Crea el esquema solo si no existe en `pg_namespace` (el usuario `escritor_ia` no tiene permiso CREATE en la base). |
| `0002_cola_trabajos.py` | Columnas de la cola en `execution_log` (`worker_id`, `lease_hasta`, `disponible_desde` y `programada_para`), sus índices (incluido el único de la franja programada) y la tabla `execution_attempt` con la traza de cada intento. |
| `0003_alertas_estructura.py` | Estructura completa de §5.3 en `alert`: origen, tendencia, serie reciente, probabilidad, método del puntaje, variables influyentes, `ubicacion geography(Point,4326)` con GiST y CHECK del seudónimo del conductor; nueva versión de umbrales. |
| `0004_monitoreo_y_trazabilidad.py` | `model_monitoring`; columnas `p10_modelo`, `p90_modelo`, `ajuste_conformal` y `explicacion_local` en `prediction`; `feature_snapshot` particionada por mes; `execution_log.traceparent`; umbrales de monitoreo y de la política. |
| `0005_pesos_objetivo.py` | Versión nueva de `threshold_config` con los pesos α, β, γ y δ, el nivel de servicio y los costos de la función objetivo de §10.2, para que `GET /thresholds` los muestre desde la instalación. Si un valor ya estaba vigente por un `PUT`, se conserva. |
| `0006_dimensiones_calidad_respuesta.py` | Dimensiones de §8.3 (`idruta`, `idempresa`, `idproceso`, `id_dia_semana` e `id_estacionalidad`) en `prediction`, `recommendation`, `alert`, `demanda_observada` y `feature_snapshot`, rellenadas desde el catálogo, con índices por `idruta`. En `recommendation`: `origen` (`franja` o `plan_dia`) y sus UNIQUE. En `alert`: CHECK de los estados e índice (viaje, detectada_en). En `data_quality_error`: `llave`, `valor` y `bloqueante`. En `threshold_config`: `aprobado_por` y `aprobado_en`. Tipo de trabajo `respuesta` y tabla nueva `respuesta_reto` (la foto de la respuesta por fecha y ruta, con modelo, calibración, versión de umbrales, ejecución y fuente del pronóstico). La subida, el relleno y la bajada los prueba `tests/integracion/test_api_integracion.py::test_migracion_0006_dimensiones_sube_baja_y_rellena`. |
| `0007_umbrales_reglas_nuevas.py` (head) | Versión nueva y completa de `threshold_config` con los 7 umbrales que el código usaba por omisión: los de la ALT-002 observada (`salidas_minimas_ocupacion` 2 y `persistencia_ocupacion_horas` 2) y los del detector de rupturas de RF-009 (`ruptura_k` 0,5, `ruptura_h` 6,0, `ruptura_dias_referencia` 28, `ruptura_cambio_minimo` 0,08 y `ruptura_dias_reinicio` 7). Así se ven en `GET /thresholds`, quedan ligados a `umbrales_version` y se cambian con `PUT /thresholds` como los demás. Un valor ya vigente se conserva. La bajada borra solo las filas que creó y conserva las versiones posteriores de un `PUT`. Prueba: `tests/integracion/test_api_integracion.py::test_migracion_0007_umbrales_de_las_reglas_nuevas_sube_y_baja`. |

Convenciones:

- Fechas en `TIMESTAMPTZ`, guardadas en UTC y presentadas en America/Bogota (§8.1). La API responde con `-05:00`, y
  `tests/integracion/test_catalogos_api.py` recorre todas las rutas GET para comprobarlo.
- Claves primarias UUID o BIGINT y claves naturales con UNIQUE.
- Para revisar una migración se baja y se vuelve a subir: `alembic downgrade base` y `alembic upgrade head`. El CI lo
  hace en cada corrida.

El mapa de las tablas de Extreme (§8.2) frente a la réplica, la marca de agua y los controles de no interferencia están
en `integracion_postgresql.md`.

## 9. Observabilidad (RNF-006)

- **Logs JSON** (structlog). Cada línea lleva `logger`, `mensaje`, `nivel`, `ts` (con -05:00), `correlation_id`,
  `execution_id`, `worker_id`, `trace_id` y `span_id`. Las peticiones agregan método, ruta, estado, duración, usuario
  y rol. Las claves y las URL de base nunca se escriben. Ejemplo: `docs/evidencias/seguridad/logs_json_ejecucion.txt`.
- **Correlation-Id (§12.1).** La cabecera `X-Correlation-Id` se acepta o se genera, y vuelve en cada respuesta y en
  cada error (`error.correlation_id`). Se guarda en `execution_log.correlation_id`.
- **Métricas Prometheus** en `/metrics`:
  - `api_peticiones_total` y `api_latencia_segundos`, por método, ruta y estado;
  - `api_autenticacion_total`, por resultado y rol;
  - `api_circuito_estado` (0 cerrado, 1 semiabierto, 2 abierto), `api_circuito_fallos_total`,
    `api_circuito_rechazos_total` y `api_circuito_transiciones_total`;
  - de la cola (`app/servicios/cola.py`): `api_ejecuciones_total` (intentos terminados, por `tipo` de trabajo y
    `resultado`: ok, reintento, error o reserva_perdida), `api_ejecucion_duracion_segundos` (duración de cada intento,
    por tipo y resultado; con `tipo=entrenamiento`, la de los entrenamientos), `api_cola_reintentos_total` (trabajos
    devueltos a la cola, por tipo y `motivo`: fallo, reserva_vencida o reinicio) y `api_cola_trabajos` (trabajos
    `en_cola` y `corriendo` por tipo, leídos de `execution_log` al consultar `/metrics`, con una caché de 5 s);
  - del ciclo (`app/servicios/ejecucion.py`): `api_ejecucion_etapa_segundos` (duración de cada etapa: lectura
    incremental, calidad, predicción, alertas, notificaciones, plan_dia, entrenamiento, registro y respuesta) y
    `api_serie_diaria_segundos` (la serie diaria de la ruptura de RF-009 por ruta, con `memoria="si"` o `"no"`).

  `/metrics` es público salvo con `METRICAS_PUBLICAS=false`.
- **Trazas OpenTelemetry.** Cubren el HTTP, cada sentencia SQL y cada etapa de la ejecución (`ejecucion.*`), también
  cuando la ejecuta el hilo de la cola. Si otra réplica toma el trabajo, continúa la misma traza: lee el
  `correlation_id` y el `traceparent` W3C de `execution_log` y abre el span `ejecucion.ciclo_frecuencia` como hijo remoto
  del span de la petición, con el mismo `trace_id`. El atributo `traza_origen` del span dice de dónde vino el contexto:
  `memoria` (lo corre la misma réplica), `execution_log` (lo tomó otra réplica u otro proceso tras un reinicio),
  `heredada` (ya había una traza activa) o `nueva` (sin contexto guardado, por ejemplo un traceparent inválido). Evidencia:
  `docs/evidencias/contrato/traza_entre_replicas.txt` (mismo `trace_id` en la petición y en el trabajador `replica-b:1`);
  prueba: `tests/integracion/test_traza_entre_replicas.py`. El exportador se elige con
  `OTEL_EXPORTADOR=ninguno|consola|otlp`. Con Jaeger:

  ```
  OTEL_EXPORTADOR=otlp docker compose -p sobusa_api --profile observabilidad up -d
  ```

  y abra http://localhost:16686. Una ejecución completa dio una sola traza con 39 spans
  (`docs/evidencias/seguridad/jaeger_resumen.txt` y `jaeger_traza_ejecucion.json`).
- **Salud.** `/health` informa el estado de la base y de cada circuito (`integraciones`) y responde 503 si la base no
  responde.

## 10. Seguridad

- **Autenticación por clave y rol (§7.2).** Toda ruta de `/api/v1` exige la cabecera `X-API-Key`. Sin clave o con una
  clave inválida responde 401 con `WWW-Authenticate`; con un rol insuficiente, 403 con el rol exigido. Los roles son
  acumulativos:
  - `operador` lee todo y cambia el estado de las alertas;
  - `analista` además lanza ejecuciones, predicciones, recomendaciones y entrenamientos;
  - `admin` además activa o revierte modelos y cambia umbrales y capacidad.
- **La matriz de permisos vive en un solo lugar.** Es `POLITICA`, en `app/seguridad.py`. Una escritura sin entrada
  exige admin (denegación por omisión), y `tests/integracion/test_seguridad.py` falla si alguien agrega una escritura
  sin declarar su rol. La matriz probada (sin clave, clave inválida y los tres roles en cada ruta) está en
  `docs/evidencias/seguridad/matriz_roles.txt`.
- **Claves.** `scripts/crear_api_key.py --rol <rol> --usuario <nombre>` imprime la clave una sola vez y la entrada con
  su hash para `API_KEYS`. En el entorno solo viaja el SHA-256. Los clientes (el tablero, las demostraciones y k6) leen
  la clave de `SOBUSA_API_KEY`. La auditoría registra al usuario de la clave, no el que venga en el cuerpo.
- **Swagger por ambiente (§12.1).** `/docs` y `/openapi.json` responden con `ENTORNO` = local, pruebas o demo, y dan 404
  en producción.
- **Datos personales (§18).** Los catálogos nunca exponen placa, conductor, propietario ni contactos
  (`docs/evidencias/catalogos/sin_datos_personales.txt`). El conductor de una alerta solo se guarda como seudónimo
  HMAC-SHA256 con `SEUDONIMO_SECRETO`, y la base rechaza un valor en claro con un CHECK.
- **Fuente de solo lectura (§11.3).** Ver la sección 2.2 (`fuentes.py`). En la réplica se probó que el usuario
  `lector_ia` no puede escribir: `docs/evidencias/replica/replica_roles.txt`.
- **Sin secretos en el repositorio.** `.env` está en `.gitignore`; solo viaja `.env.example`.

## 11. Configuración

Todas las variables están en `.env.example`, con su explicación, y se leen en `app/config.py`. Las más usadas:

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Base de resultados (esquema `ai_frecuencias`). |
| `FUENTE`, `FUENTE_DATABASE_URL`, `FUENTE_TABLA`, `FUENTE_PROCESO`, `FUENTE_SOLAPE_MIN`, `FUENTE_STATEMENT_TIMEOUT_MS` | Fuente de datos: `parquet` o `postgres` con un usuario de solo lectura. El ciclo diario solo procesa de punta a punta `FUENTE_TABLA=demanda_segmentos` (la demanda horaria que sale de `timbradas_segmentos`); otro valor detiene el arranque con un error claro. Las demás tablas de la lista blanca se leen para los catálogos, la capa de segmentos y las pruebas de la réplica. `FUENTE_PROCESO` elige el proceso de la tabla «Procesos» cuyas rutas se leen (por omisión `sobusa`; `*`, todos); `docker-compose.integracion.yml` la pasa explícita al servicio de la API. |
| `INFERENCIA_SERIE` | `validada` hace que un proceso sin sesión de base (un script) arme las variables con la serie validada (`demanda_observada` encima del Parquet) abriendo su propia sesión de solo lectura; vacía, usa la serie empaquetada. La API y el ciclo ya la usan con su sesión. En Docker Compose y en `.env.example` vale `validada`; definirla vacía en el `.env` deja solo la serie empaquetada. |
| `MODELO_PLAN` | Pronóstico con que se calcula la foto de la respuesta del reto: el modelo activo (por omisión) o `E12`, el pronóstico precalculado de 2025 del experimento 12. En `GET /api/v1/recommendations/plan` se elige con el parámetro `pronostico`. |
| `DATA_DIR`, `MODELOS_DIR` | Datos y artefactos de modelos (`app/servicios/datos.py`: por omisión, `datos/` y `<DATA_DIR>/modelos`). Las pruebas y los ensayos usan copias temporales. |
| `AUTH_HABILITADA`, `API_KEYS`, `API_KEY_OPERADOR`, `API_KEY_ANALISTA`, `API_KEY_ADMIN` | Autenticación. Apagarla solo sirve en desarrollo local. |
| `ENTORNO`, `DOCS_HABILITADOS`, `METRICAS_PUBLICAS` | Exposición de Swagger y de `/metrics`. |
| `MAX_REINTENTOS`, `REANUDAR_EJECUCIONES`, `TRABAJADORES`, `LEASE_SEGUNDOS` | Cola y reintentos. |
| `PLANIFICADOR_HABILITADO`, `PLAN_EJECUCION_CRON`, `PLAN_REENTRENAMIENTO_CRON` | Planificador interno. |
| `MOTOR_INFERENCIA`, `CALIBRACION_BANDA` | `sklearn` u `onnx`; `CALIBRACION_BANDA=v1` fuerza la calibración v1 de la banda (conformal móvil por ruta) en lugar de la v2 versionada con el modelo (vacía por omisión). |
| `OTEL_EXPORTADOR`, `OTEL_SERVICE_NAME`, `LOG_NIVEL`, `TZ` | Observabilidad y zona de presentación. |
| `NOTIFICACIONES_CANALES`, `NOTIFICACIONES_SEVERIDAD` | Notificaciones simuladas. |
| `SEUDONIMO_SECRETO` | Secreto del seudónimo del conductor. |

## 12. Cómo extender

- **Una ruta nueva.**
  1. Escriba la lógica en un servicio de `app/servicios/`, sin FastAPI, con su prueba unitaria.
  2. Cree o amplíe un router en `app/routers/`. Los modelos de respuesta van en Pydantic; use `ParametrosPagina` y
     las exportaciones de `comun.py`, y los parámetros con cotas (`ge`/`le`).
  3. Si es un router nuevo, regístrelo en `app/main.py` con `dependencies=[Depends(seguridad.autenticar)]`.
  4. Si es una escritura, declare su rol en `POLITICA` (`app/seguridad.py`) y en `ESPERADO_ESCRITURAS`
     (`tests/integracion/test_seguridad.py`).
  5. Regenere `docs/openapi.json` y corra `tests/contrato`: valida el contrato, los errores uniformes y la
     compatibilidad.
- **Un código de alerta nuevo.**
  1. Escriba una función `_altNNN(ctx, umbrales)` en `alertas.py` que devuelva el diccionario de §5.3 (observado,
     esperado, umbral, explicación, recomendación y clave de episodio).
  2. Agréguela a `evaluar_alertas` o a `evaluar_observadas`.
  3. Si usa un umbral nuevo, póngalo en `UMBRALES_POR_DEFECTO` y cree una versión de `threshold_config` con
     `PUT /thresholds`.
  4. Pruebe la frontera, con un caso que dispara y otro que no, en `tests/unit/test_alertas.py` o
     `test_alertas_observadas.py`.
  5. Vuelva a correr `scripts/backtest_alertas.py`.
- **Una variable nueva del modelo.**
  1. Agréguela en `variables.py` con una versión nueva en `VERSIONES`. No puede usar información posterior al
     instante de predicción.
  2. Compruebe la fuga temporal con `tests/datos_ml/test_fuga_temporal.py`.
  3. Reentrene: los artefactos de otra versión siguen cargando con su propia lista de variables.
- **Una tabla nueva de Extreme como fuente.**
  1. Agréguela a la lista blanca de `fuentes.py` (`TABLAS_CON_MARCA` o `TABLAS_SIN_MARCA`, y su columna de marca en
     `COLUMNA_MARCA` si no se llama `ultima_actualizacion`). `validar_solo_select` rechaza cualquier tabla que no
     esté en la lista.
  2. La API la lee con `FuentePostgresSoloLectura` y el usuario de solo lectura. Si va a alimentar el ciclo diario,
     tiene que entregar el contrato de demanda horaria (ruta, fecha, hora, pasajeros y salidas) y sumarse a las
     lecturas que acepta `validar_tabla_ciclo` (`FUENTE_TABLA`).
  3. Antes de pedir un índice al DBA, mida la consulta con `scripts/replica_explain.py` en la réplica.
  4. Pruebe la guarda en `tests/unit/test_fuentes.py` y la lectura en `tests/replica/`.
- **Una tabla o columna nueva.** Agréguela en `modelos_db.py` y genere una migración nueva en `alembic/versions/`
  (`alembic revision -m "..."`) con su `downgrade`. Pruebe `alembic downgrade base` y `alembic upgrade head`.

## 13. Cómo probar

Las pruebas nunca se conectan a la base del reto. La integración solo corre contra un PostgreSQL local y crea su propia
base, `TEST_DATABASE_NAME`. Las pruebas y los ensayos trabajan sobre copias temporales de `datos/`.

La URL del servidor de pruebas sale de `TEST_DATABASE_URL` o, si no está, de `DATABASE_URL` (entorno o `.env`). Las
pruebas de integración y las de contrato que usan la base se omiten, con el motivo en el informe de pytest y sin
errores, en tres casos: no hay ninguna
URL (un checkout limpio sin `.env`), la URL no apunta a `localhost`, `127.0.0.1` o `db`, o el PostgreSQL local no
responde (`tests/integracion/conftest.py`). La URL viaja como un texto cuyo `repr` oculta la clave, así que no aparece
en un traceback ni en el CI (`tests/integracion/test_seguridad.py::test_la_url_de_la_base_de_pruebas_no_muestra_su_clave`).

| Nivel (§14.1) | Carpeta | Qué cubre | Requisito para correr |
|---|---|---|---|
| Unitarias | `tests/unit/` | Reglas, fórmulas, validaciones, estados, cola, circuito, seguridad, monitoreo, política, ONNX | Nada (sin base) |
| Integración | `tests/integracion/` | API con TestClient, repositorios, migraciones, roles, exportaciones, alertas observadas, monitoreo | PostgreSQL local (`docker compose -p sobusa_api up -d db`) |
| Contrato | `tests/contrato/` | Cada operación del OpenAPI con autenticación, esquemas, 401/403/404/422 uniformes, compatibilidad con `docs/openapi.json` y Schemathesis | Igual que integración; `SCHEMATHESIS_EJEMPLOS` baja el número de ejemplos |
| Datos/ML | `tests/datos_ml/` | Contrato de la serie, rangos y NaN, PSI, no regresión del WAPE en la prueba reservada y fuga temporal en 3 cortes | Nada (sin base) |
| Réplica | `tests/replica/` | Roles `lector_ia`/`escritor_ia`, carga, scripts de Extreme, llegada por el trigger, EXPLAIN y capa de segmentos | Réplica en el puerto 5434; sin ella se omiten con su motivo. `REPLICA_PRUEBAS_ESCRITURA=1` agrega las que escriben en la réplica |
| Testcontainers | `tests/testcontainers/` | PostGIS 14-3.4 efímero: Alembic desde cero, repositorios y API | `TESTCONTAINERS=1` y Docker |
| Caída | `tests/integracion/test_caida.py` | RNF-001 con procesos reales | `PRUEBA_CAIDA=1` (unos 2 minutos) |
| Ejecución programada | `tests/integracion/test_planificador_programado.py` | §14.2: el planificador (cron cada minuto, sin ningún POST) procesa solo lo nuevo o modificado y actualiza predicciones, recomendaciones y alertas (`docs/evidencias/cola/planificador_programado.txt`) | `PRUEBA_PLANIFICADOR=1` (unos 4 minutos) |
| Carga | `k6/consultas.js`, `k6/consultas_durante_ingesta.js`, `k6/en_frio.js` | RNF-002 con usuarios concurrentes; `en_frio.js` mide la primera petición a cada ruta con la API recién arrancada y una segunda pasada (`INCLUIR_PLAN=1` agrega `/recommendations/plan` y `/respuesta`) | k6 y `SOBUSA_API_KEY`. Para el volumen de un año, `scripts/sembrar_volumen.py` replica filas reales con identificadores nuevos y fechas corridas en una base local aparte (solo corre en local); `consultas.js` exige ese volumen con `MIN_PREDICCIONES` y `MIN_ALERTAS` (`docs/evidencias/pruebas/k6_volumen.txt`) |

Las herramientas de prueba y de análisis (pytest, Schemathesis, Testcontainers, ruff y bandit) se instalan con
`pip install -r requirements-dev.txt`. Comandos (Windows; en macOS o Linux, `.venv/bin/python` y
`export VARIABLE=valor`):

```
set TEST_DATABASE_NAME=ai_frecuencias_pruebas
set SCHEMATHESIS_EJEMPLOS=3
.venv\Scripts\python -m pytest tests\unit tests\integracion tests\replica tests\contrato tests\datos_ml
.venv\Scripts\python -m pytest tests\unit -q                                  (solo unitarias, sin base)
.venv\Scripts\python -m pytest tests\unit tests\integracion --cov=app --cov-report=term-missing
.venv\Scripts\python -m ruff check app scripts tests
.venv\Scripts\python -m bandit -r app -ll
.venv\Scripts\python scripts\ci_local.py todo                                 (los mismos pasos del CI)
```

La integración continua corre en `.github/workflows/api_frecuencias.yml`, en la raíz del repositorio de entrega (la
misma definición está en `ci/github_actions_entrega.yml`). Corre:

- ruff y bandit;
- Alembic de ida y vuelta;
- pytest con cobertura mínima de 85 % y junit;
- Testcontainers;
- la verificación de que `docs/openapi.json` no cambió sin versionarse;
- en un trabajo aparte, la prueba de caída RNF-001 y la ejecución programada de §14.2 (`PRUEBA_CAIDA=1` y
  `PRUEBA_PLANIFICADOR=1`), y, si el repositorio define `SONAR_HOST_URL` y el secreto `SONAR_TOKEN`, el análisis de
  SonarQube con su puerta de calidad.

**Evidencia escrita por las pruebas.** Las pruebas que dejan un archivo de evidencia (la matriz de roles, la traza, la
resiliencia, los backtests) lo escriben con `guardar_evidencia` de `tests/evidencia.py`. Sin variables, el archivo va a
un directorio temporal (o a `EVIDENCIAS_DIR`), así que correr la suite no cambia el repositorio. Con
`GENERAR_EVIDENCIAS=1` va a `docs/evidencias/`, para regenerar la evidencia versionada a propósito:

```
set GENERAR_EVIDENCIAS=1
.venv\Scripts\python -m pytest tests\integracion\test_seguridad.py            (regenera docs/evidencias/seguridad/)
```

El ensayo local de esos pasos queda en `docs/evidencias/pruebas/ci_local.txt`. El análisis de SonarQube usa
`sonar-project.properties` y los reportes de cobertura y pruebas. `scripts/sonar_local.py` lo corre en local con un
SonarQube Community en Docker, junto con ruff y bandit, y deja la evidencia en `docs/evidencias/sonarqube/` y
`docs/evidencias/calidad/`:

```
.venv\Scripts\python scripts\sonar_local.py --archivo-clave <archivo con la clave de admin, fuera del repositorio>
```

La puerta de calidad «Reto Sobusa v1.5» se evalúa sobre todo el código y exige 0 vulnerabilidades, 0 bugs, 0 hallazgos
bloqueantes o críticos, 100 % de los security hotspots revisados, cobertura ≥ 85 % y duplicación ≤ 3 %. El estado de cada
análisis, condición por condición, está en `docs/evidencias/sonarqube/resumen.md` y `quality_gate.json`. En el análisis
vigente (9-11-2026, 12:49) la puerta queda **aprobada (OK)**: 0 vulnerabilidades, 0 bugs, 0 hallazgos bloqueantes y 0
críticos, duplicación de 0,0 % y cobertura de 94,3 % (`security_hotspots_reviewed` no tiene valor porque no hay
security hotspots). La deuda de mantenibilidad aceptada va en `scripts/sonar_decisiones.json`, cada entrada con su
justificación (nunca bugs ni vulnerabilidades); en ese análisis queda 1 hallazgo de complejidad cognitiva
(`python:S3776`), en la copia literal del solver D5 (`app/servicios/motor_d5/milp.py`). `--sin-pruebas` reanaliza con la cobertura guardada y `--solo-exportar` solo rehace la evidencia.

Resultados vigentes de la suite completa final (los cinco niveles de arriba, la corrida con cobertura que alimenta el
análisis de SonarQube): 1.060 casos (567 unitarias, 106 de integración, 185 de réplica, 178 de contrato y 24 de
datos/ML), 1.055 aprobados, 0 fallas, 0 errores y 5 omitidas a propósito (`test_caida` sin `PRUEBA_CAIDA=1`,
`test_planificador_programado` sin `PRUEBA_PLANIFICADOR=1` y 3 de la réplica sin `REPLICA_PRUEBAS_ESCRITURA=1`), en
`docs/evidencias/pruebas/suite_final.xml` (idéntico a `docs/evidencias/sonarqube/pytest.xml`); cobertura de `app/`,
con `motor_d5/`, de 94,27 %: 10.566 de 11.208 líneas (`docs/evidencias/pruebas/coverage_final.xml`, idéntico a
`docs/evidencias/sonarqube/coverage.xml`). Las corridas anteriores, que todavía describían xfail o fallas ya
corregidas, están en `docs/evidencias/historial/`.

Para regenerar el contrato después de cambiar rutas:

```
.venv\Scripts\python -c "import json; from app.main import app; open('docs/openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), ensure_ascii=False, indent=2))"
```
