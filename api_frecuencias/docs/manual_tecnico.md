# Manual técnico · API de frecuencias

Este manual es para quien mantiene, despliega o extiende la API. Los otros documentos son:

- visión general, inicio rápido y tabla de endpoints: `../README.md`;
- uso diario del tablero y de la API: `manual_usuario.md`;
- despliegue con Docker Compose: `despliegue.md`;
- integración con la base operacional de Extreme: `integracion_postgresql.md`;
- hallazgos y preguntas para Extreme (H1 a H17): `hallazgos_extreme.md`;
- partición del ciclo por ruta (RNF-005, migración 0009): `particion_por_ruta.md`;
- capa de segmentos materializada y su refresco (migración 0008): `segmentos_materializados.md`;
- parámetros del plan, flota y ciclo gobernados (migración 0010): `gobierno_parametros.md`;
- ocupación por segmento, histórica y actual (§10.1, migración 0011): `ocupacion_segmentos.md`;
- retención de datos (§18, migración 0012): `retencion_datos.md`;
- consolidados de Extreme en el ciclo y bajadas en el histórico (§6.1, §6.3, §11.2, migración 0013):
  `consolidados_ciclo.md`;
- viaje, vehículo y conductor de las alertas (§5.3) y ALT-003 con su probabilidad mínima (migración 0014):
  `alertas_viajes_y_alt003.md`;
- modelo por segmento y sentido: `modelo_segmentos.md`;
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
                      │                                 │  respuesta_reto · marca_agua_ruta        │
                      │                                 │  segmento_estadistica (_dia, _refresco)  │
                      │                                 │  ocupacion_segmento · retencion_registro │
                      │                                 │  marca_agua_tabla                        │
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
| `fuentes.py` | `FuenteParquet` y `FuentePostgresSoloLectura`. La segunda valida que el SQL sea solo `SELECT`, abre `SET TRANSACTION READ ONLY` con `statement_timeout` y `TimeZone='America/Bogota'` y termina con `ROLLBACK`. Lee por marca de agua con una ventana de solape (`FUENTE_SOLAPE_MIN`) y una huella md5 por llave natural: una fila tardía o modificada se entrega una sola vez. `leer_particion(fuente, particion, hasta)` lee por ruta: un solo SELECT de la lista blanca con la variante fija `r.nombre = ANY(CAST(:rutas AS text[]))` y, a cada ruta, la regla de marca, solape y huella con su propia marca (`marca_agua_ruta`, RNF-005; `docs/particion_por_ruta.md`). `leer_carga_segmentos(franjas)` lee, para las franjas que acaba de entregar esa lectura, los viajes no cancelados con sus subidas y bajadas por segmento, el vehículo y el conductor, con otro SELECT constante de la lista blanca (`_SQL_CARGA_SEGMENTOS`, las franjas como arreglos enlazados); el conductor se seudonimiza al leer (`seudonimizar_conductores`). `viajes(ruta, desde, hasta)` lee los viajes de una ruta con salida programada en la ventana (`progvehiculos`, SELECT constante `sql_viajes_ruta`, con el conteo de `timbradas_segmentos` por viaje si la fuente lee la capa de segmentos) y reemplaza `idconductor` por su seudónimo antes de devolverlos (`seudonimizar_viajes`). `para_tabla(tabla)` da otra lectura de la lista blanca con la misma conexión y el mismo `statement_timeout` (la usan los consolidados). `demanda_segmentos` entrega además `bajadas_viajes`: Σ `numerobajadas` de los viajes válidos, con la regla de los pasajeros. | RF-001, RF-002, RF-013, RNF-005, §5.3, §6.1, §8.3, §10.1, §11.3 |
| `calidad.py` | `validar_lote(df, lote, catalogos, ahora, retraso_maximo)`: completitud, validez, unicidad, consistencia, oportunidad y relacional (§6.3). Cada error lleva lote, fila, llave del registro, campo, valor, código, dimensión, detalle y si bloquea. La tolerancia de oportunidad sale de la versión de umbrales del ciclo: `periodos_atraso` × `periodo_ingesta_min`, el umbral de §5.1 «datos atrasados» (`retraso_maximo_de`). Los esquemas `consolidado`, `segmentos_anio` y `segmentos_consolidado` validan los consolidados de Extreme: CONS-001 (el promedio es Σ / `nro_viajes` exacto, con 1 %, o el `CEIL` que escribe `fn_consolidar_timbradas_historicas`, H7), REL-004 y REL-006 (el segmento existe y es de la ruta de la fila), REL-007 y VAL-007 (el día de la semana existe y corresponde a la fecha o a las fechas de su estacionalidad) y VAL-008 (la hora es la del bloque). | RF-004, §5.1, §6.3, §7.3, §14.2 |
| `dimensiones.py` | Dimensiones de §8.3 de cada fila de resultados (`idruta`, `idempresa`, `idproceso`, `id_dia_semana` e `id_estacionalidad`), desde el catálogo empaquetado o, en modo integrado, desde la réplica. | §8.3 |
| `ingesta.py` | Incorpora las filas válidas a `demanda_observada` con `COPY` a una tabla de paso y un `INSERT … ON CONFLICT … WHERE … IS DISTINCT FROM`, en la misma transacción de la ejecución. Una carga repetida no duplica. Desde la migración 0013 guarda también las medidas opcionales que traiga el lote (`MEDIDAS`: `bajadas_viajes`, `subidas`, `bajadas` y `viajes_con_timbradas`); una medida que no llega, o que llega nula, no borra la guardada (`COALESCE` en el upsert). | RNF-003, §6.1, §9.5, §14.2 |
| `datos.py` | Vista analítica `demanda_horaria` y catálogo de rutas (capacidad, ciclo, flota y frecuencia actual). También los archivos opcionales, entre ellos las novedades por ruta (`novedades_por_ruta`; el archivo solo existe si `novedades_viales_ruta` trae filas), el perfil de ocupación por segmento (`ocupacion_segmentos_historica`) y las bajadas por ruta, fecha y hora (`bajadas_horaria`, `datos/bajadas_horaria.parquet`), que `FuenteParquet` agrega a la serie (`con_bajadas`). | §6.1 |
| `variables.py` | Variables del modelo por versión (`VERSIONES`: fv1 y fv2), sin información posterior al instante de predicción. | §9.2, §9.3 |
| `inferencia.py` | Entrena, registra, carga (verifica el SHA-256 y la versión de variables), predice con banda P10–P90 calibrada y explicación local SHAP, y evalúa (MAE, RMSE, WAPE, sMAPE y sesgo, por ruta, pico y valle). `variables_de` arma la tabla de variables y le pone encima las novedades por ruta: es el mismo paso al entrenar y al inferir. | RF-005, RF-006, RF-015, §9, §11.2 |
| `onnx_motor.py` | Motor ONNX Runtime alternativo (`MOTOR_INFERENCIA=onnx`). | §9.1, §9.2 |
| `modelo_segmentos.py` | Modelo supervisado de la demanda por segmento y sentido. Incluye el reparto fijo B0 (línea base), un HGB Poisson con exposición y sus variantes jerárquicas (sentido × reparto dentro del sentido), la banda P10–P90 conformal de Mondrian compuesta con la de la ruta, el artefacto con SHA-256 y el registro propio (`datos/modelos/segmentos/`). También desagrega una ventana y arma las filas por segmento de la foto de variables. Detalle en `docs/modelo_segmentos.md`. | §3.1, §7.3 paso 4, §9.1, §9.2, §9.3 |
| `optimizacion.py` | `recomendar` (línea base de §10.3), `optimizar` (función objetivo de §10.2 como MILP de la franja con PuLP/CBC), `recomendacion_franja`, comparación con la frecuencia programada y con el headway vigente de `rutas.frecuenciadespachos`, escenarios y sensibilidad, `plan_dia` (MILP D5 del día con el modelo activo y los parámetros de `PARAMETROS_PLAN` versionados) y `plan_dia_d5` (la reproducción de D5 con sus parámetros, copia en `motor_d5/`). `factor_carga_franja` es por ruta, día de la semana de operación y hora, con el tipo de día de respaldo; la franja y cada hora del plan traen `ocupacion_historica`, y `plan_dia(ocupacion_actual=…)` aplica la restricción reactiva (sección 7). | RF-007, RF-008, §5.1, §6.2, §10 |
| `alertas.py` | Reglas ALT-001 a ALT-010 (`evaluar_alertas` sobre el pronóstico y `evaluar_observadas` sobre los datos reales), episodios, deduplicación, máquina de estados `TRANSICIONES` y seudónimo del conductor. ALT-002 observada se mide en el segmento crítico cuando la hora trae la ocupación por segmento. `IDENTIFICACION_5_3` y `VARIANTES_5_3` dicen qué campos de §5.3 aplican a cada regla; `identificar_viaje_006` e `identificar_viajes_009` eligen el viaje de ALT-006 y ALT-009 entre los del día. ALT-003 exige `alt003_probabilidad_minima` y ALT-008 evalúa también las bajadas (sección 6). | RF-009, RF-010, RF-011, §5 |
| `consolidados.py` | Paso del ciclo para los consolidados de Extreme (`en_ciclo`, migración 0013): lee `timbradas_consolidado`, `timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`, cada una desde su marca (`marca_agua_tabla`), las valida (`calidad.validar_lote`) y las contrasta con la agregación propia con las tolerancias de la versión de umbrales de la ejecución (`tolerancias_de`). `validar_tolerancias` revisa en `PUT /thresholds` que 0 < `contraste_tolerancia` ≤ `contraste_tolerancia_grosera` ≤ 10 y que `contraste_viajes_minimos` sea un entero ≥ 1. Detalle en `docs/consolidados_ciclo.md`. | §6.1, §6.3, §7.3, §11.2, RF-004 |
| `notificaciones.py` | Adaptadores de correo y WhatsApp configurables. El envío se simula y queda en `notification_log`. Para §6.3, `reporte_unicidad` arma el reporte de las llaves duplicadas del lote (UNI-001: cada llave con sus filas y la ruta de la API que lista los errores) y `enviar_reporte_unicidad` lo manda por el canal de correo (`NotificadorReporteCalidad`) a `NOTIF_UNICIDAD_DESTINATARIOS`; sin destinatario queda `pendiente_destinatario` y no se reenvía después. | RF-012, §6.3 |
| `ocupacion.py` | Ocupación por segmento (§10.1), con el mismo método para el histórico y para el ciclo: carga al salir del segmento k = max(0, carga en k − 1 + subidas − bajadas), en el orden de `nro_segmento` (`cargas_por_segmento`, `cargas_en_el_tramo`). `segmento_critico_historico` lee `datos/ocupacion_segmentos_hora.parquet`; `del_ciclo` calcula y guarda la ocupación actual en `ocupacion_segmento`; `restriccion_reactiva` arma el piso del plan del día. Detalle en `docs/ocupacion_segmentos.md`. | §5.2, §10.1, §11.1 |
| `novedades.py` | Novedades viales por fecha, rango horario y ruta: una novedad con filas en `novedades_viales_ruta` afecta solo a sus rutas del catálogo; una sin filas, a todas (supuesto declarado para Sobusa). `aplicar_por_ruta` pone las de rutas dadas encima de la tabla de variables. | §6.1, §11.2, RF-003 |
| `retencion.py` | Trabajo `retencion` de la cola (sección 8, «Retención de datos»): reglas por grupo con SQL constante solo sobre `ai_frecuencias`, simulación en una transacción que se revierte, `lock_timeout` de 500 ms al separar una partición y bitácora en `retencion_registro`. | §18 |
| `monitoreo.py` | Monitoreo por ejecución: WAPE, MAE y sesgo móviles de 28 días, cobertura, PSI por variable, volumen y porcentaje de alertas descartadas. También guarda la foto de variables (`feature_snapshot`) con una fila por segmento y sentido de cada predicción (§7.3 paso 4). Esas filas van en su propio punto de guardado: si fallan, se omiten solo ellas. | §7.3, §9.4, §11.2 |
| `politica.py` | Aprendizaje continuo: cuándo reentrenar, retador en sombra, compuerta, activación auditada y reversión automática. | RF-018, RF-019, §9.5 |
| `ejecucion.py` | Orquesta el ciclo de frecuencia y el de entrenamiento, y la ejecución madre de una ejecución partida por ruta (`_ciclo_de_la_madre`). Todo queda ligado a `execution_id`, `model_id`, `feature_version`, `umbrales_version` y `data_cutoff`. `bloquear_umbrales` deja pasar un solo cambio del conjunto gobernado a la vez (sección 8), y `umbrales_de_la_ejecucion` da la versión de umbrales con que corre un ciclo (sección 3). `_ocupacion_actual` y `reportar_unicidad` son los pasos del ciclo de §10.1 y §6.3 (sección 3). `viajes_del_dia` trae los viajes del día de cada ruta para ALT-006 y ALT-009, y `consolidados_de_la_ejecucion` corre los consolidados de Extreme una vez por ejecución (sección 3). | RF-013, RNF-005, RNF-011, §5.1, §5.3 |
| `cola.py` | Cola de trabajos en PostgreSQL para N réplicas, con candado por ruta para los trabajos de frecuencia (sección 4). | RNF-001, RNF-004, RNF-005 |
| `planificador.py` | Planificador interno (APScheduler): ejecución diaria (partida por ruta con `PLAN_PARTICION=ruta`), revisión semanal del reentrenamiento, retención de datos (`tarea_retencion`, `PLAN_RETENCION_CRON`) y, con `FUENTE_DATABASE_URL`, refresco de la agregación de segmentos. | §7.2, §9.5, §18, RNF-005 |
| `circuito.py` | Circuit breaker de la base fuente y de los notificadores. | RNF-010 |
| `catalogos.py` | Catálogos de solo lectura (procesos, empresas, rutas, segmentos, vehículos, viajes y despachos) y ajuste local de capacidad, versionado en `threshold_config` (`versionar_ajustes` y `eventos_ajustes`, comunes con la flota y el ciclo). `viajes_para_alertas` da los viajes de ALT-006 y ALT-009 cuando la fuente del ciclo no los trae: de la réplica o de la exportación `progvehiculos.parquet`, con el conductor seudonimizado. | §3.1, §3.2, §5.3, §8.3 |
| `flota_ciclo.py` | Flota disponible y tiempo de ciclo gobernados por ruta, tipo de día y hora: claves `flota_override.<idruta>.<TIPO>` y `ciclo_override.<idruta>.<TIPO>.<HORA>` de `threshold_config`; prioridad (el tipo de día exacto sobre `TODOS` y la hora exacta sobre `TODAS`), validación, vista vigente e historial (`GET` y `PUT /api/v1/catalogos/flota`; `docs/gobierno_parametros.md`, sección 2). | §3.1, §5.1, §10.2 |
| `segmentos.py` | Capa analítica por segmento (§6.1), servida desde la agregación materializada del esquema propio, y por zona tarifaria (§6.2). Conserva la agregación directa (`estadisticas_directas`) como referencia de las pruebas. | §6.1, §6.2, §7.1, §11.2 |
| `segmentos_refresco.py` | Trabajo `segmentos` de la cola: lee `timbradas_segmentos` con el usuario de solo lectura por tramos de fechas que se parten solos si agotan el `statement_timeout` y rehace la agregación (modos `completo`, `incremental`, `rango` y `auto`; `docs/segmentos_materializados.md`). Desde la migración 0012 cada refresco guarda las huellas por fecha de su ventana de solape (`segmento_estadistica_refresco.huellas_solape`) y el siguiente solo relee las fechas que cambiaron: si ninguna cambió, termina `sin_cambios` sin escribir nada. Un incremental o un rango ya no rehace `segmento_estadistica` entera: solo vuelve a agregar las claves de las fechas releídas (`reagregar_faltantes`), con el mismo resultado. | §6.1, §7.1, RNF-002, RNF-004 |
| `tipologias_flota.json` | Tipologías de capacidad por ruta, sin placas (lo genera `scripts/preparar_tipologias.py`). | §10.1 |
| `respuesta.py` | Arma la respuesta a la pregunta final del reto por ruta y día con los servicios anteriores, sin modelar nada nuevo: plan del día, pronóstico con banda, vehículos frente a la flota, flota y recaudo, y alertas abiertas, con su trazabilidad. Lo usan `GET /api/v1/respuesta` y `GET /api/v1/respuesta/export` (una fila por ruta y hora, CSV o XLSX); una fecha sin plan responde 404 `sin_datos`. | §20 |

### 2.3 Routers (`app/routers/`)

`ejecuciones.py` (`/frequency/executions` y `/frequency/watermarks`), `predicciones.py` (`/predictions` y
`/recommendations`), `pronostico_segmentos.py` (`/predictions/segmentos`, con el modelo de segmentos activo o el que
pida `modelo_segmentos`), `alertas.py` (`/alerts`), `modelos.py` (`/models`), `umbrales.py` (`/thresholds`),
`monitoreo.py` (`/monitoring`), `planificador.py` (`/scheduler`), `catalogos.py` (`/catalogos`, también la flota y el
ciclo), `segmentos.py` (`/segmentos`, con el refresco de la agregación), `respuesta.py` (`/respuesta`) y
`retencion.py` (`/retencion`: la política vigente con la última corrida y la corrida bajo demanda). `comun.py`
reúne la paginación (`ParametrosPagina`; `ordenar` agrega la llave primaria como desempate, para que LIMIT/OFFSET no
repita ni salte filas cuando hay empates), el error uniforme (`ErrorApi`) y las exportaciones CSV o XLSX. La lista
completa de rutas, con el rol que exige cada una, está en `../README.md`, sección «Endpoints».

### 2.4 Contrato de la API: errores, roles y filtros

El contrato está en `docs/openapi.json` (OpenAPI 3.1: 65 rutas y 69 operaciones, 67 bajo `/api/v1`) y lo verifican las
pruebas de `tests/contrato/` contra las respuestas reales (Schemathesis con cinco chequeos en cada operación). La
corrida registrada en `docs/evidencias/contrato/schemathesis.txt` (11-11-2026, con el contrato vigente) cubre las 69
operaciones: 69 de 69 sin fallas. Se regenera con `docs/evidencias/contrato/generar_evidencia_contrato.py`.

- **Error uniforme (§12.1).** Todo error responde `{"error": {"codigo", "mensaje", "detalle", "correlation_id"}}` con la
  cabecera `X-Correlation-Id`, también los que no pasan por un router:

  | Código HTTP | `codigo` | Cuándo |
  |---|---|---|
  | 400 | `cuerpo_ilegible` | El cuerpo no se puede decodificar (por ejemplo, bytes que no son UTF-8 en un JSON). Está documentado en las 14 operaciones con cuerpo. |
  | 401 | `no_autenticado` | Falta `X-API-Key` o la clave no es válida; trae `WWW-Authenticate`. |
  | 403 | `prohibido` | El rol de la clave está por debajo del rol mínimo; `detalle` trae `rol` y `rol_requerido`. |
  | 404 | `no_encontrado` (o uno más específico, como `sin_datos` o `sin_calcular`) | El recurso no existe. `sin_calcular`: el plan del día o la foto de la respuesta del reto todavía no están calculados para esa fecha; el error trae la pista de `POST /api/v1/respuesta/calcular`. |
  | 409 | `transicion_invalida`, `activacion_rechazada`, `requiere_forzar`, `ya_activo`, … | Conflicto con el estado actual. Cada operación enumera sus códigos en `x-codigos-error` del OpenAPI (`app/openapi_doc.py`, `CODIGOS_POR_OPERACION`; `docs/evidencias/contrato/operaciones_codigos.txt`). |
  | 422 | `validacion` | La entrada no es válida. `detalle` es una lista de `{campo, mensaje, tipo}`; el byte NUL (0x00 o `%00`) en la ruta, la consulta, una cabecera o un cuerpo JSON da `tipo` = `caracter_nulo` (guarda `GuardaNul`, antes de llegar a SQL). |
  | 422 | `fuera_de_rango` | Un valor válido pero imposible de procesar, como `hasta=9999-12-31` (desborde de fechas). |
  | 500 | `error_interno` | Error no controlado; el `correlation_id` lo ubica en el log. |
  | 503 | según la dependencia | Réplica, base operacional o archivo de insumos no disponible (RNF-010). |

- **Rol mínimo en el contrato.** Cada operación de `/api/v1` lleva su rol mínimo en `x-rol-minimo` y en una línea de su
  descripción (54 de operador, 6 de analista y 7 de admin). El 403 solo se declara donde ese rol es mayor que
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
`GET /api/v1/frequency/executions/{execution_id}`). Con `particion=ruta`, esa fila es la madre (`particion = 'ruta'`) y
en la misma transacción se crean sus trabajos por ruta (`ruta`, `padre_id`). Cada trabajo corre `_ciclo_frecuencia`
sobre su ruta; cuando terminan, la madre cierra una vez el monitoreo, la sombra y la política (`_ciclo_de_la_madre`,
`docs/particion_por_ruta.md`). Al crear la ejecución partida, la versión vigente de `threshold_config` queda fijada
en los parámetros de la madre y de sus trabajos (`umbrales_version`), y todos la leen
(`ejecucion.umbrales_de_la_ejecucion`): un `PUT /thresholds` a mitad de la ejecución no la parte en dos versiones de
umbrales ni de parámetros del plan, y la ejecución siguiente ya usa la nueva.

| Etapa (`etapa`) | Progreso | Qué hace | Dónde queda |
|---|---|---|---|
| `lectura_incremental` | 10 | `fuentes.leer_particion(fuente, particion, hasta)`: solo lo posterior a la marca de agua de cada ruta del trabajo (`ai_frecuencias.marca_agua_ruta`; la de la última ejecución exitosa que la movió), con solape y huella. Antes de leer, el trabajo toma el candado de su partición (`ejecucion.tomar_candados_particion`). | `metricas.lectura` (leídas, entregadas, nuevas, tardías, modificadas y repetidas en el solape) y `metricas.particion` |
| `calidad` | 25 | `calidad.validar_lote(df, lote, catalogos, ahora, retraso_maximo)` con los catálogos, el reloj del ciclo y la tolerancia de oportunidad de la versión de umbrales del ciclo (`periodos_atraso` × `periodo_ingesta_min`, §5.1 «datos atrasados»). Cada error trae `llave` (las columnas llave del registro, para encontrarlo sin depender del orden del lote), `valor` (el texto de la celda) y `bloqueante`. Las filas con un error bloqueante no siguen; los errores de oportunidad son informativos. En el consolidado, la llave es la de 7 columnas de `fuentes.LLAVES`, y `hora_fin = 00:00` cuenta como 24:00. El lote de un trabajo de ruta se llama `id:ruta:hasta`. Si el lote trae llaves duplicadas (UNI-001), `ejecucion.reportar_unicidad` manda su reporte al responsable del consolidado (§6.3) en la misma transacción; no corrige nada. | `data_quality_error` (`GET …/{execution_id}/errors`, filtrable por `idruta`); el reporte, en `notification_log` y `metricas.reporte_unicidad` |
| histórico | — | `ingesta`: las filas válidas pasan a `demanda_observada` sin duplicar, con `bajadas_viajes`, `subidas`, `bajadas` y `viajes_con_timbradas` cuando el lote las trae (una medida ausente no borra la guardada). | `metricas.incorporadas_historico` |
| evaluación | — | `inferencia.evaluar` del modelo activo sobre los días recién llegados (paso 3 del ciclo de §14.2). | `metricas.evaluacion_error` |
| monitoreo | — | `monitoreo.en_ciclo`: WAPE móvil por ruta (alimenta ALT-010), deriva y cobertura. Un trabajo de ruta solo calcula el WAPE móvil de su ruta para ALT-010; la fila de monitoreo la guarda su madre. | `model_monitoring` |
| ocupación por segmento | — | `ejecucion._ocupacion_actual` (§10.1): con la fuente PostgreSQL, lee viaje por viaje las franjas que trajo el lote en las últimas 24 h de cada ruta (`FuentePostgresSoloLectura.leer_carga_segmentos`) y reemplaza la ocupación por segmento de esas franjas. Va en un punto de guardado: si falla, queda en los fallos y el ciclo sigue sin ella. Con la fuente Parquet no hay viajes por segmento y solo deja la nota. | `ocupacion_segmento`, `metricas.ocupacion_segmentos` |
| `prediccion` | 45 | `inferencia.predecir` por ruta y horizonte (30, 60 y 120 min), seguida de la recomendación de la franja con `optimizacion.recomendacion_franja`: la función objetivo de §10.2 con la demanda por hora de la hora principal de la ventana y su banda calibrada. | `prediction`, `recommendation` |
| `alertas` | 70 | `alertas.evaluar_alertas` sobre cada pronóstico y `evaluar_observadas` (ALT-005 a ALT-009) sobre las horas cerradas del último día recibido. ALT-002 observada usa la ocupación del segmento crítico de la hora si el ciclo la midió (`ejecucion.con_ocupacion_por_segmento`). Para ALT-006 y ALT-009, `ejecucion.viajes_del_dia` lee en solo lectura los viajes del día de cada ruta (`FuentePostgresSoloLectura.viajes` o, si la fuente del ciclo no los trae, `catalogos.viajes_para_alertas`); sin ninguna fuente de viajes las alertas salen igual y lo dicen, y un error de una fuente configurada queda en los fallos (etapa «viajes»). Una alerta redetectada con más severidad se escala (sección 6). | `alert`, `alert_history` |
| `notificaciones` | 85 | Las alertas nuevas que alcanzan `NOTIFICACIONES_SEVERIDAD`, y las que se escalan a crítica, van a los canales configurados. | `notification_log` |
| `plan_dia` | 92 | El plan del día siguiente por ruta con el modelo activo (`optimizacion.plan_dia`, sección 7) y la foto de la respuesta del reto para esa fecha (`respuesta.precalcular`), en la misma transacción. La foto usa la versión de umbrales de su ejecución (`respuesta.precalcular(..., umbrales=)`) y reutiliza el plan que el ciclo acaba de guardar; en una ejecución partida es la versión fijada al crearla. Con ocupación observada de la ruta, el plan recibe la restricción reactiva (`_ocupacion_del_plan`, sección 7); sin ella se calcula igual que antes. Si este paso falla, la ejecución termina `ok` y la advertencia queda en `metricas`. | `recommendation` con `origen = 'plan_dia'` (una fila por ruta y hora), `respuesta_reto` |
| consolidados (en el cierre) | — | `ejecucion.consolidados_de_la_ejecucion` → `consolidados.en_ciclo`, una vez por ejecución: en la de todas las rutas al cerrar y, en una partida, en la madre (nunca en un trabajo de ruta), después del candado del modelo cuando la ejecución lo toma y con la versión de umbrales de la ejecución. Solo lee con `FUENTE_DATABASE_URL`; sin ella, cada tabla queda `sin_fuente`. Por tabla, en un punto de guardado: lectura desde su marca de agua (solape y huellas), calidad (CONS-001, REL-004, REL-006, REL-007, VAL-007 y VAL-008), contraste con la agregación propia (CONTR-001 a CONTR-003, con `contraste_tolerancia`, `contraste_tolerancia_grosera` y `contraste_viajes_minimos`) y la marca nueva en la misma transacción. Una tabla que falla no detiene el ciclo: no mueve su marca y queda en los fallos. | `data_quality_error` (lote `<8 caracteres del execution_id>:<tabla>`), `marca_agua_tabla`, `metricas.calidad.consolidados` |
| cierre | 100 | `monitoreo.cerrar_ciclo` (foto de variables, con las filas por segmento y sentido; retador en sombra y política), las marcas de agua de las rutas leídas y `cola.cerrar_ok`. Un trabajo de ruta guarda solo la foto de sus predicciones (`monitoreo.foto_del_ciclo`): el monitoreo, la sombra y la política los cierra la madre. Después de confirmar, si llegaron filas válidas, la ejecución sin partir o la madre (nunca un trabajo de ruta) pide una vez el refresco de la agregación de segmentos (`ejecucion._pedir_refresco_segmentos`). | `feature_snapshot`, `marca_agua_ruta`, `execution_log` |

Tres garantías del diseño:

- **Exactamente una vez.** El cierre `ok` (`cola.cerrar_ok`) va en la **misma transacción** que los resultados.
  Además, solo confirma quien todavía tiene la reserva del trabajo. Si el proceso muere antes, no queda nada a medias
  y otra réplica retoma el trabajo.
- **Sin datos nuevos no se reprocesa el histórico.** La ejecución termina con la nota «Sin datos nuevos desde la marca
  de agua». Aun así, revisa la frescura de los datos (ALT-009) y, al cerrar, lee los consolidados de Extreme desde su
  marca.
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
  exponencial (`espera_reintento`) hasta `MAX_REINTENTOS`. Cada intento queda en `execution_attempt`. Hay cinco tipos
  de trabajo (`execution_log.tipo`): `frecuencia` (el ciclo diario), `entrenamiento` (un candidato en sombra),
  `respuesta` (la foto de la respuesta del reto, que encola `POST /api/v1/respuesta/calcular`), `segmentos` (el
  refresco de la agregación de la capa de segmentos, migración 0008; `docs/segmentos_materializados.md`) y `retencion`
  (la retención de datos de §18, migración 0012; `retencion.ciclo_retencion`, sección 8).
  - Las ejecuciones de frecuencia se parten por ruta y fecha (RNF-005, migración 0009). Cada ruta tiene su marca de
    agua y sus huellas en `ai_frecuencias.marca_agua_ruta` y su candado, en el reclamo (`_RECLAMAR`) y con candados de
    asesoría dentro del ciclo (`ejecucion.tomar_candados_particion`): dos trabajos de la misma ruta nunca corren a la
    vez, y los de rutas distintas sí, en réplicas distintas. Una ejecución sin partir (por omisión) lee todas las
    rutas, cada una desde su marca, y espera a que no corra ningún trabajo de ruta; con solo ejecuciones sin partir
    rige la regla de antes, una a la vez en todo el clúster. La madre se reclama cuando ya no le queda ningún trabajo
    en cola ni corriendo. `GET /api/v1/frequency/watermarks` muestra las marcas. Detalle en
    `docs/particion_por_ruta.md`; evidencia con dos réplicas en `docs/evidencias/cola/replicas_por_ruta.txt`.
  - Los entrenamientos y las fotos de la respuesta pueden correr en paralelo. Dos refrescos de segmentos nunca corren a
    la vez (candado de asesoría de la transacción) y un refresco igual que ya está en cola no se duplica.
  - Los consolidados de Extreme los lee una ejecución a la vez en el clúster (`consolidados.CLAVE_CONSOLIDADOS`,
    candado de asesoría de la transacción): si la madre de un día y un ciclo sin partir cierran a la vez, la segunda
    espera y lee desde la marca que dejó la primera. Dentro de una ejecución los candados se toman siempre en el mismo
    orden (partición → modelo → consolidados), así que no se bloquean entre sí.
  - Una retención no se duplica: `POST /api/v1/retencion/aplicar` devuelve la que ya está en cola o corriendo
    (`retencion.solicitar`), y cada acción de la retención toma un candado de asesoría del clúster (`CLAVE_RETENCION`).
    Antes de cada acción comprueba que la réplica sigue teniendo la reserva; si la perdió, no borra ni anota nada y la
    cola lo trata como reserva perdida.
- **Recuperación tras un reinicio (RNF-001).** Al arrancar, `ejecucion.recuperar_interrumpidas()` devuelve a la cola
  lo que dejó a medias el proceso anterior y lo de reservas vencidas. Lo comprueban:
  - `docs/evidencias/cola/caida_rnf001.txt`, con procesos;
  - `docs/evidencias/cola/caida_rnf001_docker.txt`, con `docker kill`;
  - `PRUEBA_CAIDA=1 pytest tests/integracion/test_caida.py` (en un equipo compartido, `PRUEBA_CAIDA_PUERTOS="a,b"`
    fija los dos puertos de las réplicas; sin la variable usa dos libres).
- **N réplicas (RNF-005).** `docker-compose.replicas.yml` levanta dos réplicas de la API. Evidencia:
  `docs/evidencias/cola/replicas.txt` (20 ejecuciones repartidas 10/10, 0 duplicados) y, con la ejecución partida por
  ruta, `docs/evidencias/cola/replicas_por_ruta.txt` (`scripts/prueba_replicas_por_ruta.py --comparar-sin-partir`;
  también `PRUEBA_REPLICAS=1 pytest tests/integracion/test_replicas_por_ruta.py`, con `PRUEBA_REPLICAS_PUERTOS="a,b"`
  o dos puertos libres).
- **Planificador (§7.2).** Con `PLANIFICADOR_HABILITADO=true`:
  - `PLAN_EJECUCION_CRON` programa la ejecución diaria (por omisión `15 5 * * *`). Con `PLAN_PARTICION=ruta` (por
    omisión `ninguna`) la franja encola la madre y un trabajo por ruta del catálogo en la misma transacción;
  - `PLAN_INTRADIA_CRON` programa los ciclos intradía (`tarea_ciclo_intradia`; por omisión `5 6-20 * * *`; solo con
    `FUENTE=postgres`; vacío los apaga). Cada uno es una ejecución de frecuencia con `instante` = la franja y
    `parametros.intradia`, encolada con el mismo `INSERT … ON CONFLICT`: una fila por franja con N réplicas. Su plan es
    el del día en curso, y en él actúa la restricción reactiva. No evalúa el error del modelo, no guarda monitoreo,
    sombra ni política, no lee los consolidados y no pide el refresco de segmentos. Sin datos nuevos no rehace el
    plan. Una franja que tiene otra posterior en la cola se cierra «ok» sin leer
    (`ejecucion.franja_posterior_en_cola`). Valor por omisión, medición y bordes: `docs/ocupacion_segmentos.md`;
  - `PLAN_REENTRENAMIENTO_CRON` programa la revisión de reentrenamiento (por omisión `0 4 * * 1`). La política no
    encola un reentrenamiento cuyo corte no se puede entrenar: decide con la misma partición del entrenamiento y deja
    el motivo («reentrenamiento omitido: datos insuficientes antes del corte») en
    `metricas.monitoreo.politica.reentreno.bloqueos`, que sale en `GET /api/v1/monitoring/policy`;
  - `PLAN_SEGMENTOS_CRON` programa el refresco de la agregación de segmentos en modo `auto` (por omisión
    `45 5 * * *`; el trabajo `refresco_segmentos` solo existe con `FUENTE_DATABASE_URL`). El ciclo con datos nuevos y
    `POST /api/v1/segmentos/estadisticas/refrescar` también lo encolan.
  - `PLAN_RETENCION_CRON` programa la retención de datos (`tarea_retencion`; por omisión `30 3 * * 0`, los domingos a
    las 03:30; vacío la apaga). Esa corrida aplica la política si `retencion_aplicar_programada` = 1 (el valor que
    siembra la migración 0012) y solo la simula con 0.
  - El ciclo programado se encola sin `instante`: calcula el plan del día siguiente, así que la restricción reactiva
    de la ocupación por segmento no actúa en él (sección 7).
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
5. **Activar** (`POST /api/v1/models/{model_id}/activate`, rol admin, `app/routers/modelos.py`). La activación manual no
   se salta la gobernanza:
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
del repositorio no cambia. Los guiones que levantan réplicas reales (`scripts/prueba_replicas.py`,
`scripts/prueba_replicas_por_ruta.py`, `scripts/prueba_caida.py` y la API de `scripts/medir_segmentos.py`) ya corren así:
usan una copia temporal de `datos/` (`cola_servidor.datos_de_la_base`) y dejan `git status` limpio.

El modelo por segmento y sentido tiene su propio registro (`datos/modelos/segmentos/registro.json`; activo
`seg_hgb_jerarquico_20230227_s42`, con el reparto fijo `seg_reparto_fijo_20230227` como línea base) y no pasa por la
sombra ni por la compuerta del modelo de la ruta: lo elige `scripts/entrenar_segmentos.py` con la regla fijada antes
de mirar la prueba (`docs/evidencias/modelo/segmentos_protocolo.md`), y `modelo_segmentos.cargar()` verifica el
SHA-256 del artefacto y la versión de variables antes de usarlo (`docs/modelo_segmentos.md`).

## 6. Motor de alertas (`app/servicios/alertas.py`)

- **Catálogo de §5.2.** Hay dos familias de reglas:
  - sobre el pronóstico: ALT-001 alta demanda, ALT-002 sobreocupación, ALT-003 frecuencia insuficiente, ALT-004
    frecuencia excesiva y ALT-010 modelo degradado;
  - sobre lo observado en las horas cerradas: ALT-005 caída, ALT-006 despacho ausente o tardío, ALT-007 desviación
    del pronóstico, ALT-008 consolidado anómalo (subidas, bajadas y número de viajes del día) y ALT-009 datos
    incompletos o atrasados.
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

  La tabla campo por columna está en `docs/evidencias/alertas/README.md`. La empresa y la ruta van en todas. El viaje,
  el vehículo y el conductor (solo seudónimo) se llenan en ALT-006 (el despacho cancelado, tardío o sin finalizar de
  la ventana) y en ALT-009 (el viaje con datos faltantes) con los viajes del día de `progvehiculos`, en solo lectura;
  si el episodio sigue y la redetección identifica el viaje, la alerta abierta lo toma
  (`ejecucion._identificacion_del_episodio`). Toda alerta dice en `variables.identificacion_5_3` qué campos le aplican
  y por qué (`IDENTIFICACION_5_3`; sin fuente de viajes, `resultado` = `fuente_sin_viajes`). Detalle en
  `docs/alertas_viajes_y_alt003.md`.
- **Alertas de pronóstico por hora.** ALT-001 y ALT-002 comparan pasajeros por hora con puestos por hora en la hora
  recomendada: la ventana de la alerta es esa hora. Hay una alerta por franja, con los horizontes que la produjeron en
  `variables.horizontes_min`, y las variables traen `unidad_demanda` y `demanda_ventana`.
- **ALT-002 observada en el segmento crítico (§10.1).** Si una hora cerrada trae la ocupación medida en su segmento
  crítico con al menos `salidas_minimas_ocupacion` viajes, ALT-002 la mide ahí; si no, la estima con el factor de carga
  de la franja, como antes. `variables.metodo_ocupacion` dice cuál se usó (`segmento_critico` o `factor_carga`). Con la
  medida, la alerta llena el sentido (aproximado), el viaje, el vehículo y el conductor (solo seudónimo) del viaje más
  cargado en ese segmento, y lo declara en `variables.identificacion_5_3` con la variante `segmento_critico`
  (`VARIANTES_5_3`;
  `tests/unit/test_alertas_ocupacion_segmentos.py::test_la_hora_con_segmento_critico_se_mide_ahi_y_la_alerta_dice_el_viaje`).
- **ALT-003 con probabilidad mínima (§5.2, §5.3).** Además de que la frecuencia actual no cumpla el nivel de servicio,
  exige que P(carga crítica > capacidad efectiva), con la lognormal del optimizador, llegue a
  `alt003_probabilidad_minima` (0,30 en la versión propuesta que siembra la migración 0014); esa probabilidad va en el
  campo `probabilidad`. El mínimo se eligió en una validación anterior a la evaluación (`scripts/variantes_alt003.py`;
  `docs/alertas_viajes_y_alt003.md`, sección 4).
- **ALT-008 con bajadas.** Evalúa subidas, bajadas (`demanda_observada.bajadas_viajes`, migración 0013) y número de
  viajes con el mismo z robusto; un día sin las bajadas de todas sus horas no evalúa ese campo
  (`docs/consolidados_ciclo.md`, sección 2).
- **ALT-009 con los viajes programados.** Con los viajes del día, una hora faltante sin ningún viaje programado no
  cancelado no cuenta como dato faltante y queda en `variables.horas_sin_viajes_programados`. Si la fuente no trae
  viajes o no trae ninguno del día, toda hora faltante cuenta.
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
  precisión aproximada, con el mismo factor de carga que el ciclo (`optimizacion.factor_carga_franja`). Del 15-09 al
  31-12-2025 (324 días-ruta), con la calibración v2, las reglas sobre datos observados dejan 1,265 alertas por ruta y
  día en total, con la ALT-002 observada (0,710) y la ruptura de RF-009
  (0,012); las que ya medía la versión anterior (ALT-005 a ALT-009) son 0,543, frente a 6,08 con las reglas anteriores.
  ALT-008, con las bajadas, da 0,071 (`docs/evidencias/alertas/backtest_alertas.md`). Las de pronóstico, por hora de
  la franja recomendada, se cuentan aparte: ALT-001 0,438, ALT-002 0,306, ALT-003 0,164 y ALT-004 0,031 por ruta y día
  (0,938), con lift de 1,81, 2,03, 1,05 (2,08 donde puede emitirse) y 7,62
  (`docs/evidencias/alertas/backtest_alertas_pronostico.md`). En total, 2,203 alertas por ruta y día (1,265 + 0,938;
  `scripts/cifras_vigentes.py`). Las alertas observadas evalúan hasta `VENTANA_OBSERVADA_DIAS` = 7 días del lote, cada
  día con sus horas cerradas: después de una caída de varios días, el primer ciclo alerta los días que no se habían
  evaluado.
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
- **Headway vigente.** La especificación lo toma «de la frecuencia de despachos». La franja y cada hora del plan
  comparan el headway recomendado con dos referencias. La primera es el headway vigente de `rutas.frecuenciadespachos`
  (`frecuenciadespachos_min`, `diferencia_frecuenciadespachos_min` y `cambio_frecuenciadespachos`; migración 0010).
  Vale 5 en las tres rutas (`frecuenciadespachos_tabla_rutas` de `datos/catalogo_rutas.json`) y se lee en minutos,
  igual que en `GET /api/v1/catalogos/rutas` (supuesto S14, pregunta a Extreme en H15). En modo integrado
  (`FUENTE_DATABASE_URL`) se lee de la tabla `rutas` de la fuente, en solo lectura y con memoria de 5 min, con el catálogo
  empaquetado de respaldo; `fuente_frecuenciadespachos` dice de dónde salió, y las franjas del ciclo usan el mismo valor
  que el plan. La segunda es el intervalo
  programado que se observa en los datos (`frecuencia_actual_min` y `diferencia_min`), que sí cambia por hora: es la
  mediana de 2025 por ruta, tipo de día y hora (en día laboral, 7,2 min en SILENCIO, 3,5 min en CRA 54 y 11,6 min en
  CL 72). Las dos quedan en `recommendation`, en `GET /api/v1/recommendations` y en las exportaciones
  (`docs/gobierno_parametros.md`, sección 3).
- **RF-008.** `comparacion_actual` pone la frecuencia programada frente a la recomendada. `escenario` responde «qué
  pasa si» y `sensibilidad` hace 23 variaciones de un parámetro a la vez.
- **Plan del día** (`plan_dia`): el MILP D5 del proyecto, copiado en `app/servicios/motor_d5/` (de dónde sale cada
  archivo y qué se cambió a propósito está en `app/servicios/motor_d5/PROCEDENCIA.md`), alimentado con el pronóstico
  horario P10/P50/P90 del modelo activo, de 4 a 20 h, para cualquier fecha que tenga variables.
  - Respeta la flota, el headway máximo efectivo y el headway mínimo gobernado, con los valores de `threshold_config`.
    La tarifa (`tarifa_cop`), la elasticidad (`elasticidad`) y la suavidad (`delta_suavidad` y
    `hora_inicio_suavidad`, de 6 a 21 h) también salen de la versión vigente (`PARAMETROS_PLAN`, migración 0010); sin
    una versión nueva son los de `param_d5`, así que el plan es el de D5. La salida trae `parametros` con la fuente de
    cada valor.
  - Usa la flota, el ciclo y la capacidad del ajuste local vigente (`PUT /api/v1/catalogos/flota` y
    `/catalogos/capacidad`), si existe; `flota_y_ciclo` dice de dónde salió cada cifra. Si con la suavidad gobernada el
    MILP del día no tiene solución, `plan_dia` lanza un ValueError que lo dice, y no se entrega ni se persiste un plan
    infactible (`optimizacion._resolver_d5`).
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
- **Ocupación por segmento (§10.1; `app/servicios/ocupacion.py`, `docs/ocupacion_segmentos.md`).**
  - `factor_carga_franja` toma el factor de carga crítica 2025 de la celda ruta × día de la semana de operación × hora
    (el 7 es domingo o festivo) si tiene al menos 10 días; si no, el de tipo de día. La salida dice qué nivel usó.
  - La franja y cada hora del plan traen `ocupacion_historica`: el segmento crítico histórico, su sentido aproximado,
    su carga media, P50, P90 y máxima y su ocupación con los puestos de la recomendación. Es explicación: no entra al
    cálculo de los buses.
  - `plan_dia(ocupacion_actual=…)` recibe la restricción reactiva que arma `ocupacion.restriccion_reactiva` con la
    ocupación observada del ciclo y los umbrales de su ejecución. Si el segmento crítico de la última hora cerrada
    alcanza `ocupacion_critica`, la hora siguiente que todavía se puede programar (a lo sumo 2 h después y nunca
    después de las 20 h) recibe un piso de salidas: la fórmula de §10.3 con la carga observada, acotada por el tope
    del headway mínimo (`_aplicar_reactiva`). Entra al MILP como cota inferior de esa hora (`_con_piso_reactivo`); si
    con el piso no hay solución, el plan se resuelve sin él y la restricción lo dice. Sin ocupación observada el MILP
    recibe la misma tabla
    (`tests/unit/test_optimizacion_ocupacion.py::test_sin_piso_el_milp_recibe_la_misma_tabla_y_el_plan_e12_no_cambia`).
  - La hora en que actúa trae `restriccion_reactiva` y, si el piso manda, `ocupacion_observada` en `limites_activos`; el
    día trae `ocupacion_actual`, que dice si aplicó y por qué no. Actúa en los ciclos intradía del planificador
    (`PLAN_INTRADIA_CRON`) y en un `POST /api/v1/frequency/executions` con `instante` del día en curso. En el ciclo
    diario, la última hora cerrada es de otro día y la restricción dice que no aplica.
  - La misma restricción llega a las recomendaciones de 30 y 60 min cuya hora principal es la hora en que actúa
    (`ejecucion.recomendacion_con_ocupacion`: `optimizar(buses_minimos=…)`, con el piso acotado por lo que la flota
    sostiene con el ciclo) y a `POST /api/v1/predictions/run`, con la ocupación medida antes de su instante
    (`ocupacion.reactiva_guardada`). `POST /api/v1/recommendations/calculate` no la usa: calcula con las entradas de
    la solicitud.
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
  66,8 s a 2,0 s en la carga inicial (`docs/evidencias/rendimiento/ciclo_final.md`). El ciclo le pasa a
  `respuesta.precalcular` la versión de umbrales de su ejecución (`umbrales=`), también en una ejecución partida, así
  que la foto y el plan quedan con la misma versión aunque llegue un `PUT /thresholds` mientras corre. Como
  `GET /api/v1/respuesta` lee la foto de la versión vigente, después de ese `PUT` responde 404 `sin_calcular` hasta la
  ejecución siguiente o un `POST /api/v1/respuesta/calcular`
  (`tests/unit/test_respuesta.py::test_la_foto_del_ciclo_queda_con_la_version_de_umbrales_del_ciclo`).
- **Vehículos.** Hay tres cuentas, cada una con su nombre: ⌈ciclo / headway⌉ por franja (§10.3), la suma por
  tipología y los buses en ruta a la vez del plan (`vehiculos.requeridos_pico` de `GET /api/v1/respuesta`, frente a
  `flota_disponible`). La tercera contesta la pregunta del reto (`documentos/mapeo_especificacion.md`, sección 0).
- **Elasticidad.** β estimada ≈ 0,70 por observación (informe técnico, sección 4), sin validar en campo. El plan usa
  0,5 por prudencia (`elasticidad` en `threshold_config`, migración 0010; se cambia con `PUT /api/v1/thresholds`, y
  `ELASTICIDAD` de `motor_d5/comun.py` queda como valor por omisión; ver `docs/gobierno_parametros.md`). La
  sensibilidad está en `docs/evidencias/optimizacion/sensibilidad.md`, y el piloto la mide.

Evidencias: `docs/evidencias/optimizacion/LEEME.md` (índice), `sensibilidad.md` (MILP = enumeración exacta en 12
franjas reales) y `ejemplo_calculate_no_viable.json`; los parámetros del plan, la flota y el ciclo gobernados y el
headway vigente, en `docs/evidencias/gobierno/indice.md`.

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
| `0007_umbrales_reglas_nuevas.py` | Versión nueva y completa de `threshold_config` con los 7 umbrales que el código usaba por omisión: los de la ALT-002 observada (`salidas_minimas_ocupacion` 2 y `persistencia_ocupacion_horas` 2) y los del detector de rupturas de RF-009 (`ruptura_k` 0,5, `ruptura_h` 6,0, `ruptura_dias_referencia` 28, `ruptura_cambio_minimo` 0,08 y `ruptura_dias_reinicio` 7). Así se ven en `GET /thresholds`, quedan ligados a `umbrales_version` y se cambian con `PUT /thresholds` como los demás. Un valor ya vigente se conserva. La bajada borra solo las filas que creó y conserva las versiones posteriores de un `PUT`. Prueba: `tests/integracion/test_api_integracion.py::test_migracion_0007_umbrales_de_las_reglas_nuevas_sube_y_baja`. |
| `0008_segmentos_materializados.py` | Agregación materializada de la capa de segmentos (§6.1, RNF-002): `segmento_estadistica_dia` (grano segmento × fecha × hora, con medidas sumables e índices por fecha y por ruta y fecha), `segmento_estadistica` (grano de la respuesta, con los índices de los filtros y del orden por omisión) y `segmento_estadistica_refresco` (la marca de cada refresco terminado). Agrega el tipo `segmentos` a la restricción de `execution_log.tipo`, leyendo la lista vigente. La bajada borra las tres tablas y las ejecuciones `segmentos` y quita el tipo. Detalle en `docs/segmentos_materializados.md`. Prueba: `tests/integracion/test_migracion_0008_segmentos.py::test_migracion_0008_segmentos_materializados_sube_y_baja`, en una base desechable: sube a 0008, siembra una ejecución `segmentos` con su intento y su refresco y una `frecuencia`, sube a head y baja a 0007 (se van las tres tablas, sus índices, el tipo y la ejecución `segmentos` con su intento; la `frecuencia` queda); después vuelve a 0008 y termina en head. |
| `0009_particion_por_ruta.py` | Partición por ruta (RNF-005): columnas `ruta`, `padre_id` y `particion` en `execution_log`, con sus índices, y la tabla `marca_agua_ruta` (proceso, ruta, marca, huellas, trabajo que la movió y origen), sembrada con la marca global vigente para no releer nada. La bajada borra la tabla y las columnas. Baja a la 0008. Prueba: `tests/integracion/test_particion_ruta.py::test_migracion_0009_siembra_la_marca_global_en_cada_ruta_y_baja`. |
| `0010_parametros_plan_y_frecuenciadespachos.py` | Versión nueva y completa de `threshold_config` con los parámetros del plan del día que seguían en el código: `tarifa_cop` 3.182, `elasticidad` 0,5, `delta_suavidad` 6 y `hora_inicio_suavidad` 7, los de `param_d5`; un valor ya vigente se conserva. Agrega a `recommendation` las columnas `frecuenciadespachos_min` y `diferencia_frecuenciadespachos_min`. La bajada borra solo sus filas y las dos columnas; si no queda una versión vigente, vuelve vigente la anterior. Baja a la 0009. Prueba: `tests/integracion/test_gobierno_parametros.py::test_migracion_0010_siembra_los_parametros_del_plan_y_las_columnas`. |
| `0011_ocupacion_segmentos.py` | Tabla `ocupacion_segmento` (§10.1): una fila por ruta, fecha, hora de salida y segmento (llave `ruta`, `fecha`, `hora`, `nro_segmento`), con los viajes medidos, la carga media y máxima, los puestos, la ocupación media y máxima, el viaje de la carga máxima, el sentido aproximado, `id_dia_semana`, `id_estacionalidad`, la marca `critico` y el `execution_id` (sin llave foránea, como `segmento_estadistica_dia`). Índices parcial por `critico`, por `idruta` y fecha y por `execution_id`. No agrega tipos de trabajo. La bajada borra la tabla. Baja a la 0010. Prueba de subida y bajada: la de la cadena completa, `tests/testcontainers/test_postgis_contenedor.py::test_alembic_upgrade_downgrade_upgrade_desde_cero` (la tabla está en las que exige); no tiene una prueba propia. |
| `0012_retencion_y_ventana_segmentos.py` | Retención de datos (§18) y refresco de segmentos sin cambios. Agrega el tipo de trabajo `retencion` a la restricción de `execution_log.tipo`, leyendo la lista vigente como la 0008. Crea `retencion_registro`, la bitácora de la retención (grupo, objeto, acción, corte, filas, bytes, versión de los parámetros, si fue simulación y el detalle; sin llave foránea a `execution_log`, para sobrevivir a la propia retención). Agrega `segmento_estadistica_refresco.huellas_solape`. Siembra una versión nueva y completa de `threshold_config` con los seis parámetros de la retención (`retencion_meses_foto`, `retencion_meses_resultados`, `retencion_meses_alertas` y `retencion_meses_ejecuciones` en 13, `retencion_archivar_particiones` en 0 y `retencion_aplicar_programada` en 1); un valor ya vigente se conserva. La bajada quita la columna, la tabla, las ejecuciones `retencion` y el tipo, y solo sus filas de `threshold_config`. Baja a la 0011. Al subir y al bajar toma el candado de `bloquear_umbrales`, como la 0013 y la 0014. Pruebas: `tests/integracion/test_retencion.py::test_migracion_0012_sube_y_baja`, `tests/unit/test_retencion.py::test_los_parametros_son_los_que_siembra_la_migracion_0012` y `tests/integracion/test_migracion_0012_candado.py::test_la_0012_espera_el_candado_de_threshold_config_al_bajar_y_al_subir`. |
| `0013_consolidados_ciclo.py` | Consolidados de Extreme en el ciclo (§6.1, §6.3, §9.5, §11.2). Agrega a `demanda_observada` las columnas `bajadas_viajes` (Σ `numerobajadas` de los viajes válidos de la franja), `subidas` y `bajadas` (Σ de `timbradas_segmentos`) y `viajes_con_timbradas` (su cobertura); las filas que ya estaban quedan con ellas nulas, porque la migración no lee la base de Extreme. Crea `marca_agua_tabla`: la marca de agua y las huellas de la ventana de solape de cada tabla consolidada por proceso, con el `execution_id` que la movió (llave foránea a `execution_log` con `ON DELETE CASCADE`). Siembra una versión nueva y completa de `threshold_config` con `contraste_tolerancia` 0,15, `contraste_tolerancia_grosera` 0,50 y `contraste_viajes_minimos` 30; un valor ya vigente se conserva. Al subir y al bajar toma el candado de `bloquear_umbrales`. La bajada borra la tabla, las cuatro columnas y solo sus filas de `threshold_config`; si no queda una versión vigente, vuelve vigente la anterior. Baja a la 0012. Prueba: `tests/integracion/test_consolidados_ciclo.py::test_migracion_0013_sube_y_baja` (sube y baja su propia revisión, sin suponer que es la cabeza). Detalle en `docs/consolidados_ciclo.md`. |
| `0014_alt003_probabilidad_minima.py` (head) | Versión nueva y completa de `threshold_config` con `alt003_probabilidad_minima` = 0,30, el mínimo de probabilidad de ALT-003 elegido sin fuga. Nace propuesta (`aprobado_por` nulo): la aprueba el área operativa con `POST /api/v1/thresholds/{version}/aprobar`. Un valor ya vigente se conserva. Toma el mismo candado de `bloquear_umbrales` al subir y al bajar. La bajada borra solo sus filas; si no queda una versión vigente, vuelve vigente la anterior. Baja a la 0013. Pruebas: `tests/integracion/test_gobierno_alt003.py::test_migracion_0014_versiona_el_minimo_de_alt003_como_propuesta_y_baja` (también que `PUT /thresholds` rechaza un 0 con 422) y `tests/unit/test_alertas_alt003.py::test_la_migracion_0014_siembra_el_valor_del_codigo`. Detalle en `docs/alertas_viajes_y_alt003.md`. |

Convenciones:

- Fechas en `TIMESTAMPTZ`, guardadas en UTC y presentadas en America/Bogota (§8.1). La API responde con `-05:00`, y
  `tests/integracion/test_catalogos_api.py` recorre todas las rutas GET para comprobarlo.
- Claves primarias UUID o BIGINT y claves naturales con UNIQUE.
- Un cambio del conjunto gobernado a la vez: `PUT /thresholds` y los ajustes de capacidad, flota y ciclo toman el
  mismo candado de la transacción (`ejecucion.bloquear_umbrales`, `pg_advisory_xact_lock`) antes de leer la versión
  vigente. Todo código nuevo que cree una versión de `threshold_config` debe usar `ejecucion.nueva_version_umbrales` o
  `catalogos.versionar_ajustes`, que lo toman. Las migraciones 0013 y 0014 toman el mismo candado (`CANDADO_UMBRALES`,
  copiado de `ejecucion.SQL_CANDADO_UMBRALES`; sus pruebas comprueban que es el mismo texto), así que un
  `PUT /thresholds` de otra réplica durante el despliegue espera y parte de la versión que deja la migración.
- En una base nueva sin ningún `PUT /thresholds`, la versión vigente de `threshold_config` es la 9, con 71
  parámetros: la crea la 0014 y nace propuesta. Crean versiones la 0001, la 0003, la 0004, la 0005, la 0007, la 0010,
  la 0012, la 0013 y la 0014.
- Una migración que agregue un tipo de trabajo lo suma a la restricción de `execution_log.tipo` leyendo la lista
  vigente, como la 0008 y la 0012, para no pisar los tipos de otras migraciones.
- Toda tabla de `ai_frecuencias` tiene que tener su regla de retención en `app/servicios/retencion.py` (se borra por
  sus filas, se separa por particiones, es derivada o se conserva):
  `tests/unit/test_retencion.py::test_la_politica_cubre_cada_tabla_del_esquema` falla si una tabla nueva no la tiene.
- Para revisar una migración se baja y se vuelve a subir: `alembic downgrade base` y `alembic upgrade head`. El CI lo
  hace en cada corrida.

### Retención de datos (§18)

La política, tabla por tabla, está en `docs/retencion_datos.md`; aquí va lo que importa para operarla.

- **Qué hace.** Con los parámetros por omisión (13 meses en caliente), separa (`DETACH PARTITION`) y borra (`DROP`)
  cada partición mensual de `feature_snapshot` cuyo rango y cuyas filas son anteriores al corte, y borra por lotes de
  5.000 las predicciones, las recomendaciones, las respuestas del reto, las marcas de refresco viejas, las
  notificaciones, las alertas cerradas o descartadas y las ejecuciones que ya no sostienen nada (tampoco la que movió
  una marca de agua por ruta o por tabla). Conserva `demanda_observada`, `ocupacion_segmento`, `model_registry`,
  `threshold_config`, `marca_agua_ruta`, `marca_agua_tabla`, las alertas abiertas y su propia bitácora; la agregación
  de segmentos es derivada y solo se informa. La edad se mide por la fecha en que se escribió cada fila (las alertas,
  por su última actualización), así que los datos históricos que se reprocesan hoy, como los de la demostración, no se
  borran.
- **La corrida programada aplica.** Con `PLANIFICADOR_HABILITADO=true` (el valor de Docker Compose), la franja de
  `PLAN_RETENCION_CRON` borra de verdad, porque la migración 0012 siembra `retencion_aplicar_programada` = 1. Para que
  solo informe, cree una versión con `retencion_aplicar_programada` = 0 con `PUT /api/v1/thresholds` (admin); para que
  no corra, deje `PLAN_RETENCION_CRON` vacía. `POST /api/v1/retencion/aplicar` simula por omisión y aplica con
  `"simular": false`. La simulación cuenta con los mismos `DELETE` dentro de una transacción que se revierte.
- **Candados.** Separar una partición pide candados sobre `feature_snapshot`, `prediction` y `execution_log`. Con
  `lock_timeout` de 500 ms (`ESPERA_CANDADO`, menor que el `deadlock_timeout` de 1 s), si un ciclo los tiene, la acción
  queda `pospuesta` para la corrida siguiente y PostgreSQL no aborta al ciclo
  (`tests/integracion/test_retencion.py::test_separar_cede_ante_un_ciclo_sin_que_postgresql_lo_aborte`).
- **Modo archivo.** Con `retencion_archivar_particiones` = 1, la partición vieja queda como
  `feature_snapshot_AAAAMM_archivo`, sin las llaves foráneas que clonó de `feature_snapshot`, para que el DBA la vuelque
  con `pg_dump` y la borre. Si el mismo mes se vuelve a archivar, el archivo nuevo toma el primer nombre libre
  (`feature_snapshot_AAAAMM_archivo_2`, `_3`…; `retencion.nombre_de_archivo`) y la bitácora dice cuál. Una partición
  vieja con fotos de predicciones que la regla de resultados de la misma corrida conserva se conserva entera. Una partición vieja con un nombre que no sigue el patrón
  `feature_snapshot_AAAAMM` se conserva para el DBA.
- **Permisos.** Separar y borrar una partición exige ser dueño de la tabla; en el modo integrado lo es `escritor_ia`,
  que corre las migraciones.
- **Caso borde.** Una partición cuyas filas se crearon todas antes del corte se borra aunque alguna foto sea de una
  predicción vieja que se conserva porque la sostiene una recomendación posterior al corte.
- **Bitácora.** `GET /api/v1/retencion` muestra la política vigente con el corte de hoy y la última corrida, y
  `GET /api/v1/frequency/executions/{execution_id}` el resumen de cada corrida. Corridas de ejemplo, simulada y
  aplicada: `docs/evidencias/retencion/`.

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
  - del ciclo (`app/servicios/ejecucion.py`): `api_ejecucion_etapa_segundos` (su etiqueta `etapa` sale de un conjunto cerrado,
    `ejecucion.ETAPAS_METRICA`, y lo demás cuenta en `otra`, así que el tramo y las fechas del refresco de segmentos no
    crean series nuevas; duración de cada etapa: lectura
    incremental, calidad, predicción, alertas, notificaciones, plan_dia, entrenamiento, registro y respuesta; además,
    `cierre_modelo` de la ejecución madre y las etapas de los trabajos `segmentos` y `retencion`, que pasan por el
    mismo `_avance`) y
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
  - `analista` además lanza ejecuciones, predicciones, recomendaciones, entrenamientos y el refresco de la agregación
    de segmentos (`POST /api/v1/segmentos/estadisticas/refrescar`);
  - `admin` además activa o revierte modelos, cambia umbrales, capacidad, flota disponible y tiempo de ciclo
    (`PUT /api/v1/catalogos/flota`) y corre la retención de datos bajo demanda (`POST /api/v1/retencion/aplicar`, que
    borra datos viejos si se pide sin simular). `GET /api/v1/retencion` es una lectura más: rol operador.
- **La matriz de permisos vive en un solo lugar.** Es `POLITICA`, en `app/seguridad.py`. Una escritura sin entrada
  exige admin (denegación por omisión), y `tests/integracion/test_seguridad.py` falla si alguien agrega una escritura
  sin declarar su rol. La matriz probada (sin clave, clave inválida y los tres roles en cada ruta) está en
  `docs/evidencias/seguridad/matriz_roles.txt`; esa corrida es anterior a las rutas de la flota, de las marcas de agua,
  del refresco de segmentos y de la retención, que la prueba ya recorre
  (`GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_seguridad.py` la regenera).
- **Claves.** `scripts/crear_api_key.py --rol <rol> --usuario <nombre>` imprime la clave una sola vez y la entrada con
  su hash para `API_KEYS`. En el entorno solo viaja el SHA-256. Los clientes (el tablero, las demostraciones y k6) leen
  la clave de `SOBUSA_API_KEY`. La auditoría registra al usuario de la clave, no el que venga en el cuerpo.
- **Swagger por ambiente (§12.1).** `/docs` y `/openapi.json` responden con `ENTORNO` = local, pruebas o demo, y dan 404
  en producción.
- **Datos personales (§18).** Los catálogos nunca exponen placa, conductor, propietario ni contactos
  (`docs/evidencias/catalogos/sin_datos_personales.txt`). El conductor de una alerta solo se guarda como seudónimo
  HMAC-SHA256 con `SEUDONIMO_SECRETO`, y la base rechaza un valor en claro con un CHECK. La lectura de la ocupación
  por segmento seudonimiza al conductor al leer (`fuentes.seudonimizar_conductores`), y las de los viajes de ALT-006 y
  ALT-009 (`FuentePostgresSoloLectura.viajes` y `catalogos.viajes_para_alertas`) reemplazan `idconductor` por el HMAC
  antes de devolver los viajes (`fuentes.seudonimizar_viajes`): el dato en claro no sale de la capa de lectura. Las dos
  delegan en una sola función, `fuentes.seudonimos`, así que el mismo conductor da el mismo seudónimo por los dos caminos.
- **Retención (§18).** La aplica el trabajo `retencion` (sección 8). Todo su SQL es constante y nombra solo tablas de
  `ai_frecuencias` (`tests/unit/test_retencion.py::test_todo_el_sql_solo_nombra_tablas_del_esquema_ai_frecuencias`), y
  la prueba de integración lo comprueba con tablas centinela del mismo nombre en otro esquema
  (`tests/integracion/test_retencion.py::test_aplicada_borra_solo_lo_anterior_al_corte_y_solo_en_ai_frecuencias`).
- **Fuente de solo lectura (§11.3).** Ver la sección 2.2 (`fuentes.py`). En la réplica se probó que el usuario
  `lector_ia` no puede escribir: `docs/evidencias/replica/replica_roles.txt`.
- **Sin secretos en el repositorio.** `.env` está en `.gitignore`; solo viaja `.env.example`.

## 11. Configuración

Todas las variables están en `.env.example`, con su explicación, y se leen en `app/config.py`. Las más usadas:

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Base de resultados (esquema `ai_frecuencias`). |
| `FUENTE`, `FUENTE_DATABASE_URL`, `FUENTE_TABLA`, `FUENTE_PROCESO`, `FUENTE_SOLAPE_MIN`, `FUENTE_STATEMENT_TIMEOUT_MS` | Fuente de datos: `parquet` o `postgres` con un usuario de solo lectura. El ciclo diario solo procesa de punta a punta `FUENTE_TABLA=demanda_segmentos` (la demanda horaria que sale de `timbradas_segmentos`); otro valor detiene el arranque con un error claro. Las demás tablas de la lista blanca se leen para los catálogos, la capa de segmentos y las pruebas de la réplica. `FUENTE_PROCESO` elige el proceso de la tabla «Procesos» cuyas rutas se leen (por omisión `sobusa`; `*`, todos); `docker-compose.integracion.yml` la pasa explícita al servicio de la API. Con `FUENTE_DATABASE_URL`, el cierre de cada ejecución lee además los consolidados de Extreme (sección 3); sin ella, quedan `sin_fuente`. |
| `INFERENCIA_SERIE` | `validada` hace que un proceso sin sesión de base (un script) arme las variables con la serie validada (`demanda_observada` encima del Parquet) abriendo su propia sesión de solo lectura; vacía, usa la serie empaquetada. La API y el ciclo ya la usan con su sesión. En Docker Compose y en `.env.example` vale `validada`; definirla vacía en el `.env` deja solo la serie empaquetada. |
| `MODELO_PLAN` | Pronóstico con que se calcula la foto de la respuesta del reto: el modelo activo (por omisión) o `E12`, el pronóstico precalculado de 2025 del experimento 12. En `GET /api/v1/recommendations/plan` se elige con el parámetro `pronostico`. |
| `DATA_DIR`, `MODELOS_DIR` | Datos y artefactos de modelos (`app/servicios/datos.py`: por omisión, `datos/` y `<DATA_DIR>/modelos`). Las pruebas y los ensayos usan copias temporales. |
| `AUTH_HABILITADA`, `API_KEYS`, `API_KEY_OPERADOR`, `API_KEY_ANALISTA`, `API_KEY_ADMIN` | Autenticación. Apagarla solo sirve en desarrollo local. |
| `ENTORNO`, `DOCS_HABILITADOS`, `METRICAS_PUBLICAS` | Exposición de Swagger y de `/metrics`. |
| `MAX_REINTENTOS`, `REANUDAR_EJECUCIONES`, `TRABAJADORES`, `LEASE_SEGUNDOS` | Cola y reintentos. |
| `PLANIFICADOR_HABILITADO`, `PLAN_EJECUCION_CRON`, `PLAN_REENTRENAMIENTO_CRON`, `PLAN_PARTICION` | Planificador interno; `PLAN_PARTICION=ruta` parte la ejecución diaria en una madre y un trabajo por ruta (por omisión `ninguna`; otro valor lo rechaza la validación de `app/config.py`). |
| `PLAN_SEGMENTOS_CRON`, `SEGMENTOS_DIAS_POR_LOTE`, `SEGMENTOS_COMPLETO_DIAS` | Refresco de la agregación de segmentos: cron (por omisión `45 5 * * *`, solo con `FUENTE_DATABASE_URL`), días de `timbradas_segmentos` por lectura de la fuente (31) y días máximos entre dos refrescos completos en modo `auto` (7), los dos de 1 a 366 (`docs/segmentos_materializados.md`). |
| `PLAN_RETENCION_CRON` | Cron de la corrida programada de la retención de datos (§18; `tarea_retencion`): por omisión `30 3 * * 0`, los domingos a las 03:30; vacío no la programa. Los meses en caliente y si esa corrida aplica o solo simula son parámetros de `threshold_config` (`retencion_*`, sección 8), no variables de entorno. |
| `FOTO_SEGMENTOS` | `true` por omisión: la foto de variables guarda también una fila por segmento y sentido de cada predicción con el modelo de segmentos activo (`docs/evidencias/monitoreo/foto_segmentos.json` mide las filas y los bytes por ejecución). `false` la apaga y deja solo las filas de la ruta. |
| `MOTOR_INFERENCIA`, `CALIBRACION_BANDA` | `sklearn` u `onnx`; `CALIBRACION_BANDA=v1` fuerza la calibración v1 de la banda (conformal móvil por ruta) en lugar de la v2 versionada con el modelo (vacía por omisión). |
| `OTEL_EXPORTADOR`, `OTEL_SERVICE_NAME`, `LOG_NIVEL`, `TZ` | Observabilidad y zona de presentación. |
| `NOTIFICACIONES_CANALES`, `NOTIFICACIONES_SEVERIDAD` | Notificaciones simuladas. |
| `NOTIF_UNICIDAD_DESTINATARIOS` | Correos del responsable del consolidado para el reporte de llaves duplicadas de cada lote (§6.3). Vacía por omisión: el destinatario lo define Extreme y, sin él, el reporte queda `pendiente_destinatario` en `notification_log`. Como las demás `NOTIF_*`, la lee `app/servicios/notificaciones.py` del entorno del proceso, no `app/config.py`. |
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
  2. Agréguela a `evaluar_alertas` o a `evaluar_observadas`, y declare en `IDENTIFICACION_5_3` qué campos de
     identificación de §5.3 le aplican y por qué
     (`tests/unit/test_alertas_identificacion.py::test_tabla_de_identificacion_cubre_las_diez_reglas` falla si falta).
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
- **El modelo por segmento y sentido.** Si cambia `app/servicios/modelo_segmentos.py` fuera de su docstring, hay que
  reentrenar con `scripts/entrenar_segmentos.py` (`docs/modelo_segmentos.md`, «Reentrenar»): el manifiesto guarda la
  huella del código y `tests/datos_ml/test_segmentos_modelo.py::test_artefacto_activo_integro_y_registro_con_linea_base`
  la compara.
- **Un umbral o parámetro gobernado que se lee en el ciclo.** Léalo de la versión de la ejecución
  (`ejecucion.umbrales_de_la_ejecucion`), no de la vigente, para que una ejecución partida por ruta use una sola
  versión, y pruébelo también con `PLAN_PARTICION=ruta`. Para versionarlo, use `ejecucion.nueva_version_umbrales` o
  `catalogos.versionar_ajustes` (sección 8).
- **Una tabla nueva de Extreme como fuente.**
  1. Agréguela a la lista blanca de `fuentes.py` (`TABLAS_CON_MARCA` o `TABLAS_SIN_MARCA`, y su columna de marca en
     `COLUMNA_MARCA` si no se llama `ultima_actualizacion`). `validar_solo_select` rechaza cualquier tabla que no
     esté en la lista.
  2. La API la lee con `FuentePostgresSoloLectura` y el usuario de solo lectura. Si va a alimentar el ciclo diario,
     tiene que entregar el contrato de demanda horaria (ruta, fecha, hora, pasajeros y salidas) y sumarse a las
     lecturas que acepta `validar_tabla_ciclo` (`FUENTE_TABLA`).
  3. Antes de pedir un índice al DBA, mida cada candidato y la propuesta entera con
     `scripts/replica_indices_candidatos.py` en la réplica (los crea dentro de transacciones que se revierten) y, para una
     lectura por proceso con volumen de otro operador, con `scripts/replica_lectura_consolidados.py`.
     `scripts/replica_explain.py` aplica la propuesta entera fuera de una transacción y la borra al terminar.
  4. Pruebe la guarda en `tests/unit/test_fuentes.py` y la lectura en `tests/replica/`.
- **Una tabla o columna nueva.** Agréguela en `modelos_db.py` y genere una migración nueva en `alembic/versions/`
  (`alembic revision -m "..."`) con su `downgrade`. Pruebe `alembic downgrade base` y `alembic upgrade head`. Una tabla
  nueva necesita además su regla de retención en `app/servicios/retencion.py` (sección 8) y entra en los conjuntos
  `TABLAS` de `tests/integracion/test_api_integracion.py` y `tests/testcontainers/test_postgis_contenedor.py`.

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
| Unitarias | `tests/unit/` | Reglas, fórmulas, validaciones, estados, cola, partición por ruta, circuito, seguridad, monitoreo, política, parámetros gobernados, modelo por segmento, ONNX, ocupación por segmento, novedades por ruta, reporte de unicidad y retención. También el contraste y la calidad de los consolidados (`test_consolidados.py`, `test_calidad_consolidados.py`), la identificación de §5.3 (`test_alertas_identificacion.py`), ALT-003 con su probabilidad y su protocolo (`test_alertas_alt003.py`, `test_variantes_alt003.py`) y el cliente HTTP de la demostración (`test_cliente_http.py`) | Nada (sin base) |
| Integración | `tests/integracion/` | API con TestClient, repositorios, migraciones, roles, exportaciones, alertas observadas, monitoreo, partición por ruta, agregación de segmentos y gobierno de parámetros. `test_convivencia_ciclo_segmentos.py` comprueba el ciclo con la capa de segmentos, sin partir y partido por ruta: la foto por segmento una vez por trabajo y en su partición, un solo refresco de segmentos por ejecución (en una partida lo pide la madre), también cuando un intento pierde la reserva o falla en el cierre y con la franja programada partida, y la misma versión de umbrales en toda la ejecución partida. `test_ocupacion_ciclo.py` comprueba la ocupación por segmento en el ciclo (sin partir y partido por ruta), `test_novedades_por_ruta.py` las novedades por ruta leídas con `FuentePostgresSoloLectura`, `test_errores_lote.py` el reporte de unicidad y `test_retencion.py` la retención (simulada, aplicada, archivada, pospuesta, por la API y su migración). `test_consolidados_ciclo.py` comprueba el paso de consolidados contra un esquema sintético (calidad, contraste, marca, relectura, resellado, una tabla que falla, ciclo sin partir y partido, `PUT /thresholds`, bajadas en el histórico, ALT-008 y la migración 0013); `test_alertas_identificacion.py`, el viaje y el seudónimo del conductor en ALT-006 y ALT-009; `test_gobierno_alt003.py`, el mínimo de ALT-003 con la migración 0014 y la ejecución partida, y `test_migracion_0008_segmentos.py`, la subida y bajada de la 0008 | PostgreSQL local (`docker compose -p sobusa_api up -d db`) |
| Contrato | `tests/contrato/` | Cada operación del OpenAPI con autenticación, esquemas, 401/403/404/422 uniformes, compatibilidad con `docs/openapi.json` y Schemathesis | Igual que integración; `SCHEMATHESIS_EJEMPLOS` baja el número de ejemplos |
| Datos/ML | `tests/datos_ml/` | Contrato de la serie, rangos y NaN, PSI, no regresión del WAPE en la prueba reservada y fuga temporal en 3 cortes; para el modelo por segmento, partición cronológica, variables sin datos posteriores al corte, artefacto íntegro y reentrenamiento que reproduce la validación (`test_segmentos_modelo.py`); el protocolo sin fuga de ALT-003 (`test_alt003_protocolo.py`) y la evidencia de la identificación de §5.3 (`test_identificacion_viajes_evidencia.py`) | Nada (sin base) |
| Réplica | `tests/replica/` | Roles `lector_ia`/`escritor_ia`, carga, scripts de Extreme, llegada por el trigger, EXPLAIN, lectura por ruta (`test_particion_ruta.py`), capa de segmentos (la agregación materializada igual a la directa y el refresco sin cambios), novedades por ruta y la lectura de la ocupación por segmento como `lector_ia` (`test_ocupacion_segmentos.py`). En solo lectura, también los consolidados reales, H4, H10, H17 y el linaje de las bajadas empaquetadas (`test_consolidados.py`) y los viajes de las alertas (`test_alertas_viajes.py`) | Réplica en el puerto 5434; sin ella se omiten con su motivo. `REPLICA_PRUEBAS_ESCRITURA=1` agrega las que escriben en la réplica, entre ellas la de un viaje que llega por el trigger y se mide por segmento en una transacción revertida. Desde una copia sin la carpeta `datos/` de la raíz (un worktree), `REPLICA_DATOS_DIR` indica dónde están las exportaciones con que se cargó la réplica (`test_carga.py`) |
| Testcontainers | `tests/testcontainers/` | PostGIS 14-3.4 efímero: Alembic desde cero, repositorios y API | `TESTCONTAINERS=1` y Docker |
| Caída | `tests/integracion/test_caida.py` | RNF-001 con procesos reales; en cada caso la foto de variables (de la ruta y por segmento y sentido) queda igual a la de la referencia y sin filas repetidas | `PRUEBA_CAIDA=1` (unos 2 minutos); `PRUEBA_CAIDA_PUERTOS="a,b"` fija los dos puertos (sin ella, dos libres) |
| Dos réplicas por ruta | `tests/integracion/test_replicas_por_ruta.py` | RNF-005 con dos procesos uvicorn: rutas distintas a la vez, la misma ruta nunca en paralelo, sin duplicados, marcas contiguas y las mismas salidas que sin partir (`scripts/prueba_replicas_por_ruta.py`, `docs/evidencias/cola/replicas_por_ruta.txt`) | `PRUEBA_REPLICAS=1` (unos 3 minutos); `PRUEBA_REPLICAS_PUERTOS="a,b"` fija los dos puertos (sin ella, dos libres) |
| Ejecución programada | `tests/integracion/test_planificador_programado.py` | §14.2: el planificador (cron cada minuto, sin ningún POST) procesa solo lo nuevo o modificado y actualiza predicciones, recomendaciones y alertas (`docs/evidencias/cola/planificador_programado.txt`); y el ciclo intradía programado (`scripts/evidencia_planificador_intradia.py`, `docs/evidencias/ocupacion/planificador_intradia.txt`) | `PRUEBA_PLANIFICADOR=1` (unos 4 minutos) |
| Carga | `k6/consultas.js`, `k6/consultas_durante_ingesta.js`, `k6/en_frio.js`, `k6/segmentos.js` | RNF-002 con usuarios concurrentes; `en_frio.js` mide la primera petición a cada ruta con la API recién arrancada y una segunda pasada (`INCLUIR_PLAN=1` agrega `/recommendations/plan` y `/respuesta`); `segmentos.js` pone 50 usuarios sobre la capa de segmentos mientras corre un refresco completo | k6 y `SOBUSA_API_KEY`. Para el volumen de un año, `scripts/sembrar_volumen.py` replica filas reales con identificadores nuevos y fechas corridas en una base local aparte (solo corre en local); `consultas.js` exige ese volumen con `MIN_PREDICCIONES` y `MIN_ALERTAS` (`docs/evidencias/pruebas/k6_volumen.txt`). `scripts/medir_segmentos.py` corre los guiones contra una API propia en modo integrado (`docs/evidencias/pruebas/k6_segmentos.txt`) |

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
vigente (14-11-2026, 00:56) la puerta queda **aprobada (OK)**: 0 vulnerabilidades, 0 bugs, 0 hallazgos bloqueantes y 0
críticos, duplicación de 0,0 % y cobertura de 95,7 % (`security_hotspots_reviewed` no tiene valor porque no hay
security hotspots). La deuda de mantenibilidad aceptada va en `scripts/sonar_decisiones.json`, cada entrada con su
justificación (nunca bugs ni vulnerabilidades); en ese análisis queda 1 hallazgo de complejidad cognitiva
(`python:S3776`), en la copia literal del solver D5 (`app/servicios/motor_d5/milp.py`). `--sin-pruebas` reanaliza con la cobertura guardada y `--solo-exportar` solo rehace la evidencia.

Resultados vigentes de la suite completa final (los cinco niveles de arriba, la corrida con cobertura que alimenta el
análisis de SonarQube, 14-11-2026): 1.770 casos (1.106 unitarias, 217 de integración, 209 de réplica, 197 de contrato y 41 de datos/ML),
todos aprobados, con 0 fallas, 0 errores y 0 omitidas, en una sola sesión con los procesos reales (`PRUEBA_CAIDA=1`,
`PRUEBA_REPLICAS=1` y `PRUEBA_PLANIFICADOR=1`) y las pruebas de escritura en la réplica (`REPLICA_PRUEBAS_ESCRITURA=1`), en
`docs/evidencias/pruebas/suite_final.xml` (idéntico a `docs/evidencias/sonarqube/pytest.xml`); cobertura de `app/`,
con `motor_d5/`, de 95,70 %: 14.656 de 15.314 líneas (`docs/evidencias/pruebas/coverage_final.xml`, idéntico a
`docs/evidencias/sonarqube/coverage.xml`). Las corridas anteriores, que todavía describían xfail o fallas ya
corregidas, están en `docs/evidencias/historial/`.

Para regenerar el contrato después de cambiar rutas:

```
.venv\Scripts\python -c "import json; from app.main import app; open('docs/openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), ensure_ascii=False, indent=2))"
```
