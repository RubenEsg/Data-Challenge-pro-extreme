# Plan de evolución (E12) · De prototipo a servicio en la plataforma de Extreme

**Data Challenge Pro Extreme – Sobusa 2026** · Universidad del Norte · Abrahan Basto Martínez, Rubén Esguerra
Fernández y Paula Gómez

Este plan cubre lo que pide E12: integración, escalabilidad, costos y riesgos. Además trae una hoja de ruta de 30, 60
y 90 días y los indicadores con que Extreme y Sobusa pueden decidir si el sistema se adopta. Las rutas de archivo son
relativas a esta carpeta, y `ev/` abrevia `api_frecuencias/docs/evidencias/`.

## Punto de partida

La API de frecuencias (`api_frecuencias/`) ya funciona y está medida:

- **Despliegue.** Corre en Docker Compose con su propio PostgreSQL 14 + PostGIS (esquema `ai_frecuencias`)
  (`api_frecuencias/docs/despliegue.md`).
- **Integración.** Se probó como correría en Extreme, contra una réplica local de la base operacional con sus 8
  scripts sin modificar. La API lee con un usuario de solo lectura y escribe solo en `ai_frecuencias`
  (`api_frecuencias/docs/integracion_postgresql.md`, `ev/replica/replica_llegada.txt`).
- **Escala.** Soporta varias réplicas sin duplicar trabajo (`ev/cola/replicas.txt`) y se recupera de una caída
  (`ev/cola/caida_rnf001_docker.txt`).
- **Rendimiento.** Las consultas paginadas cumplen p95 < 2 s con k6: p95 de 451 ms y 0 % de errores
  (`ev/rendimiento.txt`); con un año de resultados sembrado y 50 usuarios, p95 de 627,5 ms y 0 % de errores
  (`ev/pruebas/k6_volumen.txt`). `GET /segmentos/estadisticas` no cumple (8,8 s en frío y 11,9 s en caliente): agrega la
  tabla de segmentos en cada petición y necesita caché o una agregación materializada. El ciclo diario completo, con el plan del día, la
  foto de la respuesta y la serie de la ruptura, tarda 24,1 s en la carga inicial y 21,4 s con un día nuevo
  (`ev/rendimiento/ciclo_final.md`).
- **Calidad del pronóstico y de las alertas.** El modelo activo `hgb_fv2_20250831_s42` tiene un WAPE de 14,77 % (IC95
  13,10–16,87) en la prueba reservada, frente a 21,18 % de la regla manual B1 (`ev/modelo/evaluacion_modelo.md`). Su
  banda P10–P90 usa la calibración v2 por bloque horario: cobertura de 77,82 % con un ancho medio de 303,4 pasajeros
  (`ev/modelo/calibracion_condicional.md`). Del 15-09 al 31-12-2025, las reglas sobre datos observados dejan 1,238
  alertas por ruta y día (ALT-005 a ALT-009: 0,534, frente a 6,08 con las reglas anteriores;
  `ev/alertas/backtest_alertas.md`), y las de pronóstico, por hora, ALT-001 0,435, ALT-002 0,315, ALT-003 0,380 y
  ALT-004 0,031 (`ev/alertas/backtest_alertas_pronostico.md`): 2,399 por ruta y día en total. En una revisión doble de
  96 alertas, la kappa entre los dos revisores automatizados es 0,943 y la precisión reponderada, 0,839
  (`ev/alertas/revision_doble/conciliacion.json`). La prueba reservada se consultó al
  elegir las variables fv2, así que su cifra es informativa; se pide a Extreme un periodo de 2026 como prueba limpia
  (`documentos/mapeo_especificacion.md`, sección 6).
- **Pruebas.** La suite completa final (1.060 casos) pasa con 0 fallas, 0 errores y 5 omitidas a propósito
  (`ev/pruebas/suite_final.xml`), con una cobertura de `app/` de 94,27 %, `motor_d5/` incluido
  (`ev/pruebas/coverage_final.xml`). El flujo de integración continua está en `.github/workflows/api_frecuencias.yml`.
- **Calidad de código.** La puerta de SonarQube «Reto Sobusa v1.5», sobre todo el código, queda aprobada (OK) en el
  análisis del 9-11-2026, 12:49: 0 vulnerabilidades, 0 bugs, 0 hallazgos bloqueantes y 0 críticos, duplicación de
  0,0 % y cobertura de 94,3 % (`ev/sonarqube/quality_gate.json`, `ev/sonarqube/resumen.md`).

El paso a producción no cambia el código: cambian las variables de entorno (`FUENTE`, `FUENTE_DATABASE_URL` y
`DATABASE_URL`) y el lugar donde corre.

## 1. Integración con la base real de Extreme

### 1.1 Pasos

Este archivo es la única fuente del calendario, de los costos y del criterio para salir del modo sombra. E01 y la
presentación toman de aquí sus cifras. El calendario cuenta en semanas, en tres fases: conexión en las semanas 1 a 4,
modo sombra en las 5 a 8 y piloto de ocho semanas en las 9 a 16.

| Semana | Paso | Quién | Criterio para seguir |
|---|---|---|---|
| 1 | Extreme responde las preguntas H1 a H16 (`api_frecuencias/docs/hallazgos_extreme.md`). Las más urgentes son H3 (llave de `timbradas_segmentos`), H6 (viajes aptos sin fecha de fin), H7 (resellado y promedios), H9 (`pasajeros`), H13 (ciclo, flota e intervalo programado que no cuadran, y el headway mínimo) y H14 (lectura de la espera máxima). | Extreme, con el equipo | Respuestas por escrito; si cambian la interpretación de un dato, se actualizan la regla de calidad o la variable. |
| 1 | El DBA crea los dos usuarios técnicos de §11.3 en la réplica de lectura (o en un ambiente de pruebas): `lector_ia` y `escritor_ia` (sección 1.2). | DBA de Extreme | `ev/replica/replica_roles.txt` repetido en su ambiente: 0 escrituras indebidas. |
| 2 | Se despliega la API con `FUENTE=postgres` contra esa réplica y se corre `alembic upgrade head` como `escritor_ia`. Ya probado en la réplica local: `tests/replica/test_integrado.py::test_alembic_upgrade_head_como_escritor_ia`. | Equipo | Esquema creado; `/health` en `ok`. |
| 2-4 | Lectura en paralelo con las exportaciones durante tres semanas de control. | Equipo | Mismos conteos por ruta, día y hora (como `ev/catalogos/fidelidad_y_relaciones.txt`). |
| 3 | **Ventana de prueba de índices** (sección 1.3). | DBA | p95 de la lectura diaria < 60 s sin subir la carga de la primaria. |
| 3-4 | Parámetros operativos reales: ciclo y flota por ruta, tipo de día y franja; capacidades; umbrales de §5.1 validados por la operación. | Operación de Sobusa | Versión nueva de `threshold_config` con motivo, responsable y aprobación. |
| 5-8 | **Modo sombra.** El job diario genera predicciones, recomendaciones, el plan del día siguiente y alertas, pero nadie despacha con ellos. | Equipo y supervisor de turno | El criterio de salida de la sección 6.3, por horizonte, durante las 4 semanas, y < 30 % de alertas descartadas. Decisión al cierre de la semana 8. |
| 9-16 | **Piloto controlado** de ocho semanas en CRA 54 y CL 72 (sección 6). | Comité de despacho | Aprobación de Extreme y de la operación (§3.2) para empezar y, al cierre de la semana 16, para adoptar. |

### 1.2 Permisos

Son los que se probaron en la réplica local (`api_frecuencias/replica/initdb/30_roles.sh`), con una diferencia: allí
`lector_ia` lee todo el esquema `public` y en producción solo leería las tablas y vistas autorizadas (§19). El DBA
aplica las sentencias; la aplicación nunca ejecuta DDL sobre el esquema operacional.

```sql
-- usuario de lectura: solo SELECT sobre las tablas autorizadas de §8.2, en transacciones de solo lectura
CREATE ROLE lector_ia LOGIN PASSWORD '<entregada por canal de Extreme>';
GRANT CONNECT ON DATABASE <base> TO lector_ia;
GRANT USAGE ON SCHEMA public TO lector_ia;
GRANT SELECT ON <tablas autorizadas> TO lector_ia;
ALTER ROLE lector_ia SET default_transaction_read_only = on;
ALTER ROLE lector_ia SET statement_timeout = '30s';
ALTER ROLE lector_ia SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE lector_ia SET lock_timeout = '5s';
-- usuario de resultados: dueño solo del esquema ai_frecuencias, sin permisos sobre public
CREATE ROLE escritor_ia LOGIN PASSWORD '<entregada por canal de Extreme>';
CREATE SCHEMA ai_frecuencias AUTHORIZATION escritor_ia;
GRANT USAGE ON SCHEMA ai_frecuencias TO lector_ia;
```

Las claves llegan por el canal de Extreme, se cargan como variables de entorno o en un gestor de secretos y nunca
entran al repositorio (§19).

### 1.3 Índices y ventana de prueba

La propuesta está en `ev/replica/propuesta_indices.sql`. Son siete `CREATE INDEX CONCURRENTLY`, ninguno cambia
tablas, triggers ni funciones, y cada uno se revierte con `DROP INDEX CONCURRENTLY`:

- `ultimaactualizacion` de `timbradas_segmentos`;
- `ultima_actualizacion` de `timbradas_consolidado`, `timbradas_anio`, `timbradas_segmentos_anio` y
  `timbradas_segmentos_consolidado`;
- la llave foránea `timbradas_segmentos.id_viaje`;
- `progvehiculos (idruta, date_trunc('hour', fechasalida))`.

Lo que se midió en la réplica (`ev/replica/explain_incremental.txt`, `EXPLAIN (ANALYZE, BUFFERS)` como `lector_ia`):

- Sin novedades, la lectura de `timbradas_segmentos` pasa de 239 ms (recorrido completo) a 0,01 ms (índice).
- Un bloque de 500.000 filas pasa de 454 ms a 245 ms.
- Sin índice, el costo crece con el histórico: hoy son 2,77 millones de filas y serían unos 58,4 millones con todos los
  viajes segmentados.

Ventana de prueba propuesta:

1. En la réplica de lectura o en un ambiente de pruebas de Extreme, nunca en la primaria.
2. En horario valle de la operación, con `pg_stat_statements` activo.
3. Medir `EXPLAIN (ANALYZE, BUFFERS)` antes y después con `api_frecuencias/scripts/replica_explain.py`, y el tiempo
   del trigger por fila.
4. Decidir con el DBA qué índices quedan.

El trigger no se deshabilita en ningún momento (§11.3).

## 2. Escalabilidad

| Dimensión | Hoy | Cómo crece |
|---|---|---|
| **Más rutas** | Tres rutas y un modelo global con la ruta como variable. | El catálogo de rutas sale de la base. El modelo global escala mejor que uno por ruta: se reentrena con las rutas nuevas y la compuerta (`ev/monitoreo/compuerta_ejemplo.json`) decide si reemplaza al activo. |
| **Más empresas** | Un proceso (`sobusa`). | `proceso` es la partición lógica de §6.1. Cada empresa lleva su propia marca de agua, sus umbrales versionados y sus claves por rol. Los resultados ya llevan ruta y empresa. |
| **Réplicas de la API** | Probadas dos réplicas con la cola en PostgreSQL: 20 ejecuciones repartidas 10/10 y 0 duplicados (`ev/cola/replicas.txt`). | La API no guarda estado entre peticiones. Se agregan réplicas detrás de un balanceador (`api_frecuencias/docker-compose.replicas.yml`) y los entrenamientos corren en paralelo. |
| **Cola** | Las ejecuciones de frecuencia se serializan en todo el clúster, porque dependen de una marca de agua global; el parámetro `rutas` limita la predicción, no la lectura ni la ingesta. Es una limitación declarada frente a RNF-005 (procesamiento particionable por ruta y fecha): las réplicas reparten las ejecuciones sin duplicarlas, pero no parten una misma ejecución. | Una marca de agua por proceso y ruta permite partir cada ejecución en trabajos por ruta y fecha (RNF-005), con una prueba de dos réplicas procesando rutas distintas a la vez. El mecanismo (`SELECT … FOR UPDATE SKIP LOCKED` con reserva) no cambia. |
| **Particionamiento** | `feature_snapshot` ya está particionada por mes. Con el diseño completo de §9.1 (por segmento, sentido y hora) llegaría a unos 17 millones de filas por ruta y año (`api_frecuencias/alembic/versions/0004_monitoreo_y_trazabilidad.py`). | Particionar por mes `prediction`, `recommendation` y `alert` cuando pasen de unos millones de filas (§8.1). La retención es de 13 meses en caliente; las particiones viejas se separan con `DETACH PARTITION` y se archivan. |
| **Lectura de la fuente** | Una ejecución diaria lee unas 49.459 filas, el 0,085 % de `timbradas_segmentos` (`ev/replica/explain_incremental.txt`). | Con los índices de la sección 1.3, el costo de la lectura depende de lo nuevo y no del histórico. |
| **Inferencia** | El modelo exportado a ONNX da los mismos pronósticos y tarda unos 0,1 ms por fila, frente a 5–12 ms en scikit-learn (`ev/monitoreo/onnx_paridad.json`). | `MOTOR_INFERENCIA=onnx` para el pronóstico por segmento y para ejecuciones horarias. |
| **Ingesta** | 111.792 filas en unos 4 s con `COPY` y 53 MiB de memoria pico (`ev/rendimiento.txt`). | Lotes por ruta y fecha; el mismo `COPY` a una tabla de paso. |

## 3. Costos

### 3.1 Infraestructura mensual

Supuestos:

- Tasa de cambio supuesta: **1 USD = 4.000 COP**. Hay que actualizarla con la TRM del día.
- Precios de lista de nubes públicas para instancias equivalentes, sin descuentos por compromiso. Son un orden de
  magnitud para presupuestar, no una cotización.
- El tamaño sale de lo medido: un solo proceso de la API atendió 58,8 peticiones por segundo con p95 de 451 ms
  (`ev/rendimiento.txt`). Los volúmenes de `ai_frecuencias` son pequeños con tres rutas.

| Concepto | Supuesto | USD por mes | COP por mes |
|---|---|---:|---:|
| Cómputo de la API, la cola y el planificador | 1 máquina virtual de 2 vCPU y 8 GB, o 2 contenedores de 1 vCPU y 2 GB (el reentrenamiento usa la misma máquina fuera de horas pico) | 50–80 | 200.000–320.000 |
| PostgreSQL 14 de resultados (`ai_frecuencias`) | (A) la misma instancia de Extreme, en otro esquema; (B) una instancia administrada de 2 vCPU, 8 GB y 100 GB | (A) 0 · (B) 70–150 | (A) 0 · (B) 280.000–600.000 |
| Réplica de lectura | (A) la que ya tenga Extreme; (B) una réplica nueva del mismo tamaño | (A) 0 · (B) 70–150 | (A) 0 · (B) 280.000–600.000 |
| Almacenamiento y respaldos | 100 GB de disco SSD y copias diarias con 30 días de retención; con tres rutas, la foto de variables cabe con holgura | 10–25 | 40.000–100.000 |
| Monitoreo (Prometheus, Grafana y Jaeger) | Autohospedados en la misma máquina | 0 | 0 |
| Integración continua y SonarQube | GitHub Actions dentro de los minutos incluidos del plan; SonarQube Community Build autohospedado | 0 | 0 |
| Notificaciones | Correo con el servidor de la empresa; WhatsApp Business se cobra por conversación según el volumen | según el volumen | según el volumen |
| **Total, escenario A** (en la plataforma de Extreme) | | **60–105** | **240.000–420.000** |
| **Total, escenario B** (nube propia administrada) | | **200–405** | **800.000–1.620.000** |

Todo el software es libre (Python, FastAPI, PostgreSQL, PostGIS, PuLP/CBC, scikit-learn, ONNX Runtime, Prometheus y
Jaeger), así que no hay licencias.

### 3.2 Personas

Supuestos: costo empresa mensual de un analista de datos de COP 7–9 millones y hora de DBA de COP 60.000–80.000, en
Barranquilla. Son supuestos del equipo, a validar con Extreme.

| Rol | Dedicación | Cuándo | COP por mes |
|---|---|---|---:|
| Analista de datos (mantiene la API, revisa alertas y recomendaciones, reentrena) | 50 % | Integración, sombra y piloto (semanas 1 a 16) | 3,5–4,5 millones |
| Analista de datos | 25 % | Operación después del piloto | 1,75–2,25 millones |
| DBA de Extreme (usuarios, índices, ventana de prueba) | 8 horas | Primer mes; después, 2 horas al mes | 480.000–640.000 (primer mes) |
| Supervisor de turno (valida recomendaciones y alertas en el piloto) | 2 horas por semana | Piloto | dentro de su turno |
| Despachadores (capacitación) | 4 horas por persona, una vez | Antes del piloto | dentro de su turno |

El costo que más pesa es el de las personas, no el de la infraestructura.

## 4. Riesgos

Los ocho riesgos de §18, con la mitigación implementada, su evidencia y su prueba, están en
`documentos/mapeo_especificacion.md`, sección 5. Para la adopción hay riesgos nuevos:

| Riesgo | Qué puede pasar | Mitigación |
|---|---|---|
| Fatiga de alertas | El despachador deja de mirar la bandeja. | Episodios y deduplicación (una alerta por episodio, no por hora); umbrales versionados que se ajustan con el backtest (`ev/alertas/backtest_alertas.md`). Meta: < 30 % de alertas descartadas (sección 6.3). |
| Datos de Extreme con otra semántica | Las respuestas a H1–H16 cambian una variable, una regla, un umbral o un parámetro operativo (por ejemplo, H14 cambia el headway máximo de 10 a 5 min). | Variables versionadas: una versión nueva se reentrena y pasa por la compuerta sin tocar la anterior. |
| Elasticidad sin medir | El saldo del plan depende de β (0,55–0,90): de −2.825 a +1.600 M COP al año (`README.md`, «Las cifras principales»). | El piloto con días sorteados mide β antes de cambiar horarios de forma permanente (sección 6). |
| Dependencia de la disponibilidad de la API | El tablero no muestra recomendaciones si la API cae. | El tablero lo dice («La API no responde») y no inventa cifras. La API se recupera sola de una caída (`ev/cola/caida_rnf001_docker.txt`) y `/health` se vigila con Prometheus. El horario vigente sigue siendo el de siempre. |
| Parámetros operativos inconsistentes | El ciclo, la flota y el intervalo programado no cuadran en algunas franjas (`documentos/mapeo_especificacion.md`, sección 6). | La recomendación sale `viable = false` con el motivo y no fuerza una cifra; se pide a Extreme el ciclo y la flota por franja. |

## 5. Hoja de ruta de 30, 60 y 90 días

Es el mismo calendario de la sección 1.1, contado en días. Las semanas mandan: la semana n va del día 7n − 6 al 7n.

| Plazo | Entregable | Hito de control |
|---|---|---|
| **Días 1–30 (semanas 1–4, conexión)** | Respuestas a H1–H16; usuarios técnicos y ventana de prueba de índices; API desplegada contra la réplica de lectura de Extreme; tres semanas de control con conteos iguales; parámetros operativos y umbrales validados por la operación. | Día 28 (fin de la semana 4): lectura estable y no invasiva, y umbrales aprobados. Empieza la sombra. |
| **Días 31–60 (semanas 5–8, modo sombra)** | Cuatro semanas de modo sombra con medición semanal; capacitación de despachadores y supervisores con `api_frecuencias/docs/manual_usuario.md`; ajuste de umbrales con el backtest; diseño del sorteo de días del piloto. | Día 56 (fin de la semana 8): decisión de pasar a piloto con el criterio de salida de la sección 6.3. |
| **Días 61–90 (semanas 9–13, piloto)** | Semanas 1 a 5 del piloto de ocho semanas en CRA 54 y CL 72; primer reentrenamiento con datos del piloto por la compuerta; revisión intermedia de los indicadores con el comité. | Día 84 (fin de la semana 12, mitad del piloto): revisión intermedia. |
| **Días 91–112 (semanas 14–16, cierre del piloto)** | Semanas 6 a 8 del piloto; medición de β; informe al comité. | Día 112 (fin de la semana 16): decisión de adopción o de ajuste, y extensión a SILENCIO. |

## 6. Adopción y piloto

### 6.1 Roles

| Rol | Qué hace con el sistema |
|---|---|
| Despachador | Consulta en el tablero la recomendación de su franja y gestiona las alertas (reconocer, asignar, comentar y cerrar). Decide el despacho. |
| Supervisor de turno | Revisa las alertas críticas, aprueba los refuerzos y registra en los comentarios por qué se siguió o no una recomendación. |
| Analista de Extreme o del equipo | Lanza o revisa las ejecuciones, vigila el monitoreo, entrena candidatos y propone cambios de umbral con su motivo. |
| Administrador (comité de cambios) | Activa o revierte modelos y aprueba versiones de umbrales y capacidad. La auditoría registra quién y por qué. |
| DBA de Extreme | Crea los usuarios, aplica los índices aprobados y vigila la carga de la base. |

### 6.2 Calendario del piloto (8 semanas: semanas 9 a 16 del plan)

1. **Semana 0 del piloto (semana 8 del plan, en paralelo con el cierre de la sombra):** línea base de las rutas piloto
   con el horario vigente y capacitación (manual de usuario y video de la demostración).
2. **Sorteo de días:** días con el plan recomendado y días con el horario de siempre, para medir la elasticidad β con
   un grupo de control (`Informe_tecnico_Sobusa.pdf`, sección 4 «Piloto para medir β»).
3. **Semanas 1–8 del piloto (9–16 del plan):** operación con el tablero; reunión semanal de 30 minutos con los
   indicadores de la sección 6.3.
4. **Semana 8 del piloto (16 del plan):** medición de β, informe al comité y decisión.

### 6.3 Criterio de salida del modo sombra e indicadores de adopción

Las metas son propuestas del equipo y se acuerdan con Extreme antes de empezar.

**Criterio de salida del modo sombra, por horizonte y ventana.** Se mide al cierre de cada una de las cuatro semanas
de sombra (semanas 5 a 8). Para pasar al piloto, cada horizonte tiene que cumplir su meta y quedar por debajo de la
regla manual B1 en el mismo periodo:

| Horizonte | Qué se mide | Meta | Por qué ese valor |
|---|---|---|---|
| 60 min (el del plan del día y la recomendación) | WAPE móvil de 28 días del modelo activo (`GET /api/v1/monitoring`, `wape_movil`), en cada una de las 4 mediciones semanales | ≤ 15 % | Es el error de pronóstico de §5.1 (`error_pronostico` en `threshold_config`) y está dentro del IC95 de la prueba reservada (14,77 %, IC95 13,10–16,87; `ev/modelo/evaluacion_modelo.md`). En sep.–dic. de 2025, la misma medida quedó entre 12,59 % y 14,95 % en 13 de 14 semanas y subió a 16,04 % en la de Navidad (`ev/monitoreo/monitoreo_2025.json`). |
| 30 min | WAPE de las 4 semanas de sombra, con el protocolo de `ev/modelo/horizontes.json` | ≤ 20 % | Es la tolerancia `wape_max` de ALT-010 (20 %). El modelo dio 19,43 % a 30 min en mar.–dic. de 2025, frente a 23,12 % de B1 (`ev/modelo/horizontes.json`). |
| 120 min | WAPE de las 4 semanas de sombra, con el mismo protocolo | ≤ 15 % | El modelo dio 10,87 %, frente a 15,44 % de B1, en mar.–dic. de 2025 (`ev/modelo/horizontes.json`). |

Si una medición semanal a 60 min queda entre 15 % y 16,9 % (dentro del IC95 de la prueba), la sombra se alarga dos
semanas en lugar de fallar. Si pasa de 16,9 % (fuera del IC95), o de 20 % en cualquier horizonte, no se pasa al piloto
y el modelo se revisa por la compuerta de reentrenamiento. Además, menos del 30 % de las alertas pueden quedar
descartadas.

**Indicadores de adopción**, para la sombra y el piloto:

| Indicador | Fuente | Meta propuesta |
|---|---|---|
| WAPE del pronóstico por horizonte | `GET /api/v1/monitoring` (60 min) y el protocolo de `ev/modelo/horizontes.json` (30 y 120 min) | Las metas del criterio de salida, arriba |
| Cobertura de la banda P10–P90 | `GET /api/v1/monitoring` | entre 75 % y 90 % |
| Alertas descartadas | `GET /api/v1/monitoring` (porcentaje de descartadas) | < 30 % |
| Alertas críticas reconocidas en menos de 15 minutos | `GET /api/v1/alerts/{id}/history` | ≥ 90 % |
| Recomendaciones revisadas por el despachador (aplicadas, o no aplicadas con comentario) | Comentarios de las alertas y bitácora del piloto | ≥ 80 % |
| Pasajeros por día sobre la capacidad en las rutas piloto | Datos de la operación frente a la semana 0 | menos que la línea base (con el plan de 2025, 317 → 267 pasajeros por día en las tres rutas; `README.md`) |
| Espera media estimada | Optimizador frente a la semana 0 | sin aumento (con el plan de 2025, 4,43 → 4,30 min; `README.md`) |
| Días con la ejecución diaria en `ok` | `GET /api/v1/frequency/executions` | ≥ 99 % |
| Despachadores del turno que usan el tablero cada semana | Logs de la API (usuario por clave) | ≥ 80 % |

## 7. Lo que queda para la siguiente versión

- Autenticación con el directorio de Extreme (OAuth2 u OpenID Connect) en lugar de claves por rol.
- Envío real de notificaciones por correo y WhatsApp; hoy es simulado y queda en `notification_log`.
- Tabla durable de huellas de la lectura incremental con llave foránea a las rutas autorizadas; hoy el estado viaja en
  `execution_log.metricas`.
- Materialización nocturna de las estadísticas por segmento en `ai_frecuencias`, que hoy se calculan en cada consulta.
- Pronóstico propio por segmento y sentido cuando Extreme confirme el campo de sentido; hoy es una desagregación
  documentada (`ev/monitoreo/desagregacion_segmentos.json`).
- Precisión real de las alertas con incidentes etiquetados por Extreme (§18 «Etiquetas incorrectas»); la muestra
  etiquetada dos veces de `ev/alertas/revision_doble/` la hicieron revisores automatizados.
- Marca de agua por ruta y fecha, para partir una ejecución en trabajos paralelos (RNF-005, sección 2).
- Una prueba limpia del modelo con un periodo de 2026 entregado por Extreme, porque la de nov.–dic. 2025 se consultó al
  elegir las variables.
- Ingesta de las bajadas por segmento, para que ALT-008 las evalúe junto con las subidas y el número de viajes.
