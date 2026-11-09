# Manual técnico · API de frecuencias

Para quien mantiene o extiende la API. Visión general y ejecución: `../README.md`; base de datos de Extreme:
`integracion_postgresql.md`; despliegue: `despliegue.md`.

## 1. Estructura del código

```
api_frecuencias/
├── app/
│   ├── main.py              aplicación FastAPI: routers /api/v1, middleware de correlación, /metrics, manejo de errores
│   ├── config.py            Ajustes (pydantic-settings): variables de entorno o .env; ESQUEMA = "ai_frecuencias"
│   ├── db.py                motor SQLAlchemy 2 (psycopg 3), sesiones, base_disponible()
│   ├── modelos_db.py        tablas del esquema ai_frecuencias (ORM)
│   ├── esquemas.py          modelos Pydantic 2 de entrada y salida (contrato OpenAPI)
│   ├── routers/             ejecuciones, predicciones (y recomendaciones), alertas, modelos, umbrales; comun.py
│   └── servicios/           lógica de dominio, sin FastAPI (se prueba sola)
│       ├── fuentes.py       FuenteParquet · FuentePostgresSoloLectura → leer_incremental(marca_agua, hasta)
│       ├── calidad.py       validar_lote(df, lote_id) → (válidos, errores)
│       ├── datos.py         demanda_horaria(), catalogo_rutas()
│       ├── variables.py     variables del modelo (FEATURE_VERSION), sin información posterior al instante
│       ├── inferencia.py    entrenar · cargar (SHA-256) · predecir · evaluar
│       ├── optimizacion.py  recomendar (§10.3) · plan_dia_d5 (MILP en motor_d5/)
│       ├── alertas.py       reglas ALT-001…010, deduplicación, TRANSICIONES, cambiar_estado
│       ├── notificaciones.py NotificadorCorreo · NotificadorWhatsApp (simulados)
│       └── ejecucion.py     orquestación de una ejecución como job con progreso y reintentos
├── alembic/                 migraciones (0001_esquema_ai_frecuencias.py)
├── datos/                   Parquet y JSON del proyecto (procedencia en datos/origen.json) y modelos/<model_id>/
├── scripts/                 preparar_datos_api.py (copia los datos del proyecto), entrenar.py
└── tests/                   unit/ (sin base) e integracion/ (API y base local)
```

Regla: `servicios/` no importa FastAPI; `routers/` no tiene lógica de negocio, solo valida, llama al servicio y guarda.

## 2. Una ejecución por dentro (`servicios/ejecucion.py`)

`POST /api/v1/frequency/executions` crea una fila en `execution_log` (estado `en_cola`) y responde 202; el trabajo
corre en segundo plano y actualiza `estado`, `etapa` y `progreso`:

1. **Lectura incremental:** `ultima_marca_agua()` → `fuente.leer_incremental(marca_agua, hasta)`.
2. **Calidad:** `calidad.validar_lote`; los errores van a `data_quality_error` (lote, fila, campo, código, dimensión,
   detalle); solo las filas válidas siguen.
3. **Histórico:** las filas válidas se incorporan a `demanda_observada` (*upsert* por ruta, fecha y hora).
4. **Predicción:** modelo activo, horizontes 30, 60 y 120 min para cada ruta → `prediction`.
5. **Recomendación:** `optimizacion.recomendar` con la demanda y su p90, capacidad, ocupación objetivo, ciclo y flota
   del catálogo → `recommendation`.
6. **Alertas:** `alertas.evaluar_alertas` con los umbrales vigentes; deduplicación por `clave_dedup` → `alert`.
7. **Notificaciones:** alertas nuevas a los adaptadores configurados → `notification_log`.
8. **Cierre:** guarda `marca_agua_nueva`, `data_cutoff`, `model_id`, `feature_version`, versión de umbrales y métricas.

Cada etapa se reintenta hasta `MAX_REINTENTOS`; un `ErrorNoReintentable` (por ejemplo, un artefacto con hash distinto)
corta la ejecución. Al arrancar, `recuperar_interrumpidas()` retoma las que quedaron a medias (`REANUDAR_EJECUCIONES`).

## 3. Modelo de datos (`ai_frecuencias`)

| Tabla | Contenido |
|---|---|
| `model_registry` | `model_id`, versión, tipo, artefacto, `sha256`, `feature_version`, `data_cutoff`, métricas, estado (`candidato`, `activo`…), aprobación, `anterior_model_id`, auditoría |
| `execution_log` | `execution_id`, tipo, estado, etapa, progreso, marcas de agua, `data_cutoff`, `model_id`, `feature_version`, `correlation_id`, métricas y errores |
| `data_quality_error` | errores de calidad por lote y fila |
| `demanda_observada` | histórico analítico validado (ruta, fecha, hora, pasajeros, salidas) |
| `prediction` | pronóstico, p10, p90, horizonte, `model_id`, `feature_version`, `data_cutoff`, `generated_at`, latencia, explicación |
| `recommendation` | buses por hora, headway, vehículos requeridos, capacidad efectiva, ocupación esperada, viabilidad, motivo, frecuencia actual, diferencia, fórmula |
| `alert` / `alert_history` | alertas con la estructura de §5.3 y su bitácora de cambios de estado |
| `threshold_config` | umbrales de §5.1 versionados (se cambian sin recompilar) |
| `notification_log` | envíos simulados por canal |

Fechas en `TIMESTAMPTZ`, guardadas en UTC (la conexión fija `timezone=UTC`) y presentadas en America/Bogota.

## 4. Modelo de demanda (`servicios/inferencia.py`)

- **Líneas base:** B1, la regla manual (media de la misma hora y día de la semana en las 8 semanas anteriores), y B2, la
  misma hora hace 7 días. No tienen artefacto.
- **Candidato:** `HistGradientBoostingRegressor` (pérdida Poisson) para el punto y dos modelos de cuantiles (0,1 y 0,9)
  para la banda. Variables (`variables.py`, `FEATURE_VERSION`): ruta, hora, día de la semana, mes, calendario y rezagos de
  demanda conocidos antes del instante.
- **Partición cronológica:** entrenamiento hasta `hasta`, validación los 61 días siguientes y prueba el resto.
- **Artefacto:** `datos/modelos/<model_id>/modelo.joblib` + `manifest.json`. `cargar()` lo lee una sola vez, verifica el
  SHA-256 y la `feature_version`, y falla si no coinciden.
- **Predicción a 30, 60 y 120 min:** la demanda horaria se prorratea por minutos dentro de la ventana y se ajusta con un
  factor intradía (observado / esperado en las 2 horas cerradas anteriores, recortado a 0,8-1,25).
- **Activación:** un candidato solo pasa a activo si cumple los umbrales y mejora o mantiene la métrica del activo en la
  validación temporal; el activo anterior queda en `anterior_model_id` para revertir.

## 5. Optimización (`servicios/optimizacion.py`)

Línea base de §10.3, con la demanda p90 cuando existe:

```
capacidad_efectiva  = capacidad × ocupación_objetivo            (50 × 0,85 = 42,5)
buses_hora          = ceil(demanda / capacidad_efectiva), acotado por headway mín. y máx.
headway_min         = 60 / buses_hora
vehiculos_requeridos = ceil(tiempo_ciclo_min / headway_min)
viable              = vehiculos_requeridos ≤ flota_disponible   (si no, motivo explicado)
```

La respuesta trae la `formula` con los números usados y la diferencia frente a la frecuencia actual. Para el día
completo, `plan_dia_d5(ruta, fecha)` resuelve el MILP D5 del proyecto (PuLP + CBC; copia en `motor_d5/`).

## 6. Alertas (`servicios/alertas.py`)

Catálogo ALT-001 a ALT-010 de §5.2. Umbrales por omisión de §5.1 (`UMBRALES_POR_DEFECTO`: ocupación crítica 0,90, baja
utilización 0,30, error de pronóstico 0,15, entre otros); los vigentes se leen de `threshold_config`. Cada alerta guarda
observado, esperado, umbral, puntaje, explicación, variables, recomendación y `clave_dedup` (código + ruta + ventana):
una alerta abierta con la misma clave no se repite. Estados (`TRANSICIONES`): `nueva` → `reconocida` → `asignada` →
`cerrada`; desde cualquiera de los tres primeros se puede `descartar`; `comentar` no cambia el estado. Una transición no
permitida lanza `TransicionInvalida`. Cada cambio queda en `alert_history` con usuario, fecha y comentario.

## 7. Observabilidad y seguridad

- Logs JSON con `correlation_id`; la cabecera `X-Correlation-Id` se acepta o se genera y vuelve en la respuesta.
- `/metrics` en formato Prometheus (peticiones, latencias, ejecuciones).
- Sin secretos en el repositorio: `.env` está en `.gitignore` y fuera del ZIP; solo viaja `.env.example`.
- La fuente operacional se abre en transacción `READ ONLY` con `statement_timeout`; las pruebas nunca la usan.

## 8. Pruebas y calidad

```
pytest tests/unit -q                       reglas, fórmulas, validaciones, estados (sin base de datos)
pytest tests/integracion -q                API y base local (requiere docker compose up -d db)
pytest --cov=app --cov-report=xml:docs/evidencias/coverage.xml --junitxml=docs/evidencias/pytest.xml
ruff check app tests     ·     bandit -r app
```

`sonar-project.properties` toma esos reportes cuando haya un servidor SonarQube.

## 9. Cómo extender

- **Nueva alerta:** una función en `alertas.py` que devuelva el diccionario de §5.3, su código en el catálogo, una prueba
  en `tests/unit/test_alertas.py`.
- **Nuevo umbral:** se agrega a `UMBRALES_POR_DEFECTO` y se crea una versión nueva en `threshold_config`.
- **Nuevas variables:** se cambian en `variables.py` y se sube `FEATURE_VERSION`; los artefactos viejos dejan de cargar
  (a propósito) y hay que reentrenar.
- **Nueva tabla:** se agrega en `modelos_db.py` y se genera una migración: `alembic revision --autogenerate -m "..."`.
