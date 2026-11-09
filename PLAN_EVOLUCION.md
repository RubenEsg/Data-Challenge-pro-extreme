# Plan de evolución (E12) · De prototipo a servicio en la plataforma de Extreme

**Data Challenge Pro Extreme – Sobusa 2026** · Abrahan Basto Martínez, Rubén Esguerra Fernández y Paula Gómez

Punto de partida: la API de frecuencias (`api_frecuencias/`) corre en Docker Compose con su propio PostgreSQL 14 + PostGIS
(esquema `ai_frecuencias`) y lee, por omisión, los datos del reto exportados a Parquet (2023-2025, tres rutas). El paso a
producción no cambia el código: cambia la fuente (variable de entorno) y la base de resultados.

## 1. Integración con la base de producción de Extreme (8 semanas)

| Semana | Paso | Criterio para seguir |
|---|---|---|
| 1 | Extreme crea una **réplica de lectura** (o un *standby* lógico) y dos usuarios: `ai_lector` (solo `SELECT` sobre las tablas autorizadas de §8.2) y `ai_frecuencias` (dueño solo del esquema `ai_frecuencias`, sin permisos sobre `public`). | Prueba de permisos: `INSERT` y DDL fallan con `ai_lector`. |
| 1-2 | Se apunta `FuentePostgresSoloLectura` a la réplica por variable de entorno (transacción `READ ONLY`, `statement_timeout`, cursor por lotes) y se corre la lectura incremental por `ultima_actualizacion` en paralelo con el Parquet. | Mismos conteos por ruta, día y hora que el Parquet en un mes de control. |
| 2-3 | El DBA revisa `EXPLAIN (ANALYZE, BUFFERS)` de las tres consultas incrementales y decide si crea índices por `ultima_actualizacion` (los crea él, nunca la aplicación). | p95 de la lectura diaria < 60 s sin subir la carga de la primaria. |
| 3-4 | Migraciones de Alembic sobre la base de resultados de Extreme; catálogo real de rutas (frecuencia vigente, capacidad, flota, tiempo de ciclo) en lugar de los valores derivados de los datos. | Parámetros validados por el área operativa (§5.1). |
| 4-8 | **Modo sombra**: el job diario genera predicciones, recomendaciones y alertas, pero nadie despacha con ellas. Se mide el error a 30/60/120 min, la cobertura de los intervalos y el porcentaje de alertas descartadas. | WAPE semanal ≤ 15 % y < 30 % de alertas descartadas durante 4 semanas. |
| 8+ | **Piloto controlado** en CRA 54 y CL 72 (el que propone el informe: días sorteados para medir la elasticidad β). El despachador decide; el sistema solo recomienda (§3.2). | Aprobación de Extreme y de la operación. |

## 2. Escalabilidad

- **Hoy:** 3 rutas × 17 horas × 365 días ≈ 18.600 filas por año en el consolidado horario: un solo proceso basta.
- **Más rutas:** la API no guarda estado entre peticiones; el procesamiento se parte por ruta y fecha (RNF-005), así que
  basta con más réplicas de la API detrás de un balanceador y un *worker* por grupo de rutas.
- **Jobs:** hoy corren como tareas de fondo dentro de la API. Con decenas de rutas, pasar a una cola (Celery o RQ con Redis,
  o APScheduler en un proceso aparte) para que un reentrenamiento no compita con las consultas.
- **Datos:** particionar por mes las tablas de predicciones y alertas de `ai_frecuencias` cuando pasen de unos millones de
  filas (§8.1); retención de 13 meses en caliente y el resto en archivo.
- **Modelos:** un modelo por ruta o uno global con la ruta como variable (el actual). Con muchas rutas, el global escala mejor.

## 3. Costos (orden de magnitud, precios 2026)

| Concepto | Supuesto | Costo mensual aproximado |
|---|---|---|
| Servidor de la API y los jobs | 2 vCPU, 4-8 GB de RAM (el MILP D5 de un día resuelve en segundos con CBC) | USD 40-80 |
| PostgreSQL de resultados (`ai_frecuencias`) | Instancia pequeña administrada o la misma de Extreme en otro esquema | USD 0-60 |
| Réplica de lectura | La pone Extreme; si no existe, es el costo más alto | USD 60-150 |
| Monitoreo (Prometheus + Grafana) | Autohospedado en el mismo servidor | USD 0 |
| Notificaciones | Correo con el servidor SMTP de la empresa; WhatsApp Business API por conversación | según volumen |

Todo el software es libre (Python, FastAPI, PostgreSQL, PuLP/CBC, scikit-learn); no hay licencias. El costo que más pesa es
el de las personas: un analista que revise las alertas y las recomendaciones durante el modo sombra y el piloto.

## 4. Riesgos y mitigaciones (§18 de la especificación)

| Riesgo | Qué pasa en este proyecto | Mitigación |
|---|---|---|
| Histórico insuficiente | Solo 3 años y 3 rutas; 2025 tiene 353 días con GPS. | Línea base B1 siempre calculada al lado del modelo; intervalos p10-p90; reentrenamiento con los datos nuevos validados. |
| Etiquetas incorrectas | Las subidas por hora vienen del conteo de los buses; hay días con conteos atípicos. | Validación por lote (6 dimensiones de §6.3) y alerta ALT-008; nunca se corrige la fuente, se reporta. |
| Fuga temporal | El modelo final usa rezagos de demanda. | Partición cronológica (entrenamiento hasta la fecha de corte, validación después); `data_cutoff` en cada predicción. |
| Alertas excesivas | Muchas alertas iguales cansan al despachador. | Clave de deduplicación por código, ruta y ventana; severidades; se mide el porcentaje de descartadas. |
| Consulta pesada | `conteo_pasajero` tiene 176 M filas y solo un índice por `idprogramacion`. | La API no la lee en línea: usa los consolidados por `ultima_actualizacion`, `statement_timeout`, réplica e índices aprobados por el DBA. |
| Recomendación inviable | La flota no alcanza para el headway que pide la demanda. | El optimizador devuelve `viable = false` con el motivo, en vez de forzar una cifra (§10.3). |
| Deriva | La demanda cambia (tarifas, obras, nuevas rutas). | Error móvil y alerta ALT-010; candidato frente al activo (champion/challenger) y reversión a la versión anterior. |
| Exposición de datos | Los datos operativos son de Sobusa. | La API no guarda datos personales de conductores ni pasajeros; credenciales solo en variables de entorno; `.env` fuera del repositorio. |
| Elasticidad sin medir | El saldo del plan depende de β (0,55-0,90): de −2.825 a +1.600 M COP al año. | El piloto de ocho semanas con días sorteados mide β antes de cambiar horarios. |

## 5. Lo que queda para la siguiente versión

Pruebas de carga con k6 sobre `/api/v1/predictions` y la ingesta; análisis en un servidor SonarQube (hoy: ruff y bandit);
pruebas de integración con Testcontainers; autenticación (OAuth2 o llaves por cliente) y Swagger restringido por ambiente;
trazas con OpenTelemetry; el video de 5 minutos de la demostración.
