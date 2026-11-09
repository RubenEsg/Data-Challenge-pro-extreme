# Índice de evidencias para el jurado

Cada archivo de resultados de esta carpeta es la salida de un script, de una corrida de pruebas o de una medición; no
se escribió a mano. Los documentos que los explican (los README, los LEEME y las decisiones) citan esos archivos. Para
cada archivo, el índice dice qué demuestra, a qué requisito de la especificación v1.5 responde y cómo se regenera.

Convenciones:

- Las rutas son relativas a esta carpeta (`api_frecuencias/docs/evidencias/`) y los comandos se corren desde
  `api_frecuencias/` con el entorno `.venv`.
- Las corridas de pruebas usan una base de pruebas propia en el PostgreSQL local (`TEST_DATABASE_NAME`) y copias
  temporales de `datos/`.
- Ninguna evidencia se generó contra la base compartida del reto. Las que necesitan la base operacional usan la
  réplica local (puerto 5434, `../integracion_postgresql.md`).
- Las corridas que ya no describen el estado actual (por ejemplo, suites con fallas o xfail que después se corrigieron)
  están en `historial/`, con lo que las reemplaza. Ninguna cifra vigente sale de esa carpeta.

Las tablas de requisitos y su estado están en `../../../MATRIZ_CUMPLIMIENTO.md`. El mapeo de §1–§3 y §17–§20 está en
`../../../documentos/mapeo_especificacion.md`.

## Cifras vigentes

Cada cifra vigente de la entrega está en esta tabla, con su archivo. Los demás documentos citan estas mismas cifras.

| Qué | Cifra vigente | Archivo |
|---|---|---|
| Modelo activo `hgb_fv2_20250831_s42`, prueba reservada nov.–dic. 2025 (informativa: se consultó al elegir fv2) | WAPE 14,77 % (IC95 13,10–16,87) frente a 21,18 % de la regla manual B1 y 15,07 % de la versión anterior fv1 | `modelo/evaluacion_modelo.md` |
| El mismo modelo congelado al 31-12-2024, todo 2025 | WAPE 14,48 % (IC95 13,78–15,28) frente a 20,04 % de B1 | `modelo/evaluacion_modelo.md` («Robustez») |
| Error por horizonte, mar.–dic. 2025 | 30 min 19,43 %, 60 min 14,71 % y 120 min 10,87 % (B1: 23,12 %, 18,96 % y 15,44 %) | `modelo/horizontes.json` |
| Banda P10–P90, calibración v2 por bloque horario | Cobertura de 77,82 % (v1: 77,88 %), ancho medio de 303,4 pasajeros (v1: 312,9) | `modelo/calibracion_condicional.md` |
| Alertas observadas, backtest del 15-sep al 31-dic-2025 (324 días-ruta) con el modelo activo | 1,238 por ruta y día con todas las reglas observadas (ALT-002 observada, ALT-005 a ALT-009 y la ruptura de comportamiento); solo ALT-005 a ALT-009: 0,534 | `alertas/backtest_alertas.md` |
| Alertas de pronóstico del ciclo diario, mismo periodo | ALT-001 0,435 (lift 1,77), ALT-002 0,315 (lift 2,01), ALT-003 0,380 (lift 0,75) y ALT-004 0,031 (lift 7,62) por ruta y día; con las observadas, 2,399 alertas por ruta y día | `alertas/backtest_alertas_pronostico.md`; el total, en `alertas/README.md` |
| Revisión doble de una muestra de 96 alertas (dos revisores automatizados con un protocolo escrito; falta la validación del área operativa de Sobusa) | Kappa de Cohen 0,943 (IC95 0,854–1,000) entre los revisores; precisión reponderada 0,839 (IC95 0,757–0,882) | `alertas/revision_doble/resumen.md` (`conciliacion.json`) |
| Suite completa final (unitarias, integración, réplica, contrato y datos/ML), la corrida que analiza SonarQube (9-11-2026, 12:36–12:49) | 1060 casos (567 unitarias, 106 de integración, 185 de réplica, 178 de contrato y 24 de datos/ML): 1055 aprobados, 0 fallas, 0 errores y 5 omitidos a propósito | `pruebas/suite_final.xml` (idéntico a `sonarqube/pytest.xml`; resumen en `sonarqube/corrida.json`) |
| Cobertura de `app/`, con `motor_d5/`, en esa suite final | 94,27 % (10.566 de 11.208 líneas; umbral del CI: 85 %) | `pruebas/coverage_final.xml` (idéntico a `sonarqube/coverage.xml`) |
| SonarQube, puerta de calidad «Reto Sobusa v1.5» sobre todo el código (análisis del 9-11-2026, 12:49) | **OK** (aprobada): vulnerabilidades 0, bugs 0, hallazgos bloqueantes 0 y críticos 0 (umbral: 0), duplicación 0,0 % (umbral: 3 %) y cobertura 94,3 % (umbral: 85 %); 1 hallazgo de mantenibilidad aceptado con su justificación (la copia literal del solver D5, app/servicios/motor_d5/milp.py) (`scripts/sonar_decisiones.json`) | `sonarqube/quality_gate.json` (condición por condición en `sonarqube/resumen.md`) |
| Integración continua en una copia limpia (sin réplica, como un runner nuevo) | 7 de 7 pasos OK; pytest: 912 casos, 744 aprobados, 0 fallas, 0 errores y 168 omitidos (las pruebas de la réplica se omiten con su motivo) | `pruebas/ci_limpio.txt`, `pruebas/ci/pytest.xml` |
| Cobertura de `app/`, con `motor_d5/`, en la copia limpia | 91,94 % (umbral del CI: 85 %) | `pruebas/ci/coverage.xml` |
| Ciclo diario (`POST /api/v1/frequency/executions`) con el plan del día, la foto de la respuesta y la serie de la ruptura | Carga inicial de 49.623 filas en 24,1 s, día nuevo de 51 filas en 21,4 s y repetición sin filas nuevas en 0,1 s | `rendimiento/ciclo_final.md` |
| Carga con k6 (umbral: p95 < 2 s) | Consultas paginadas: p95 451,3 ms y 0 % de errores. Con un año de resultados y 50 usuarios: p95 627,5 ms y 0 % de errores. En frío, `GET /segmentos/estadisticas` no cumple: 8,8 s (con `idruta`, 2,3 a 2,9 s) | `pruebas/k6_consultas.txt`, `pruebas/k6_volumen.txt` |
| Contrato OpenAPI | 59 rutas y 62 operaciones; Schemathesis con cinco chequeos, 62 de 62 operaciones sin fallas; nivel de contrato: 178 casos, 0 fallas | `contrato/operaciones_codigos.txt`, `contrato/schemathesis.txt`, `contrato/pytest_contrato.txt` |
| Migraciones de la base de resultados | 0001 → 0007 (`0007_umbrales_reglas_nuevas`) | `../../alembic/versions/` |
| Demostración de §14.2 (seis pasos) | El candidato `hgb_fv2_20250930_s42` y el activo se comparan en la sombra del 1 al 14-12-2025 (714 filas) con la compuerta de cuatro criterios: WAPE 14,11 % frente a 13,98 %, así que el candidato se rechaza y el activo sigue | `despliegue/demo_esperado.md` |
| Respuesta a la pregunta del reto | Por día, ruta y franja | `respuesta/respuesta_reto.md` y `../../../documentos/respuesta_pregunta_reto.md` |

Las cifras de los experimentos 11 y 12 del informe académico (13,94 % y 13,62 %) usan otro protocolo (7 días de
antelación, todo 2025 y reentrenamiento mensual) y no son cifras de este producto: la explicación está en el
`README.md` de la entrega, «Las cifras principales».

## Mapa rápido: requisito → carpeta

| Requisito de la especificación | Dónde está la evidencia |
|---|---|
| §3.1 Acceso y calidad · RF-001, RF-002, RF-004, RF-013, RF-014 · §8.2, §8.3, §11 · E07 | `replica/`, `catalogos/fidelidad_y_relaciones.txt`, `../integracion_postgresql.md`, `datos/` |
| §6.3 · §14.2 «errores por lote, con causa y fila» | `datos/errores_lote.txt` |
| Linaje de los datos empaquetados y definición de pasajeros | `datos/linaje.md`, `datos/definicion_pasajeros.md` |
| §18 «Etiquetas incorrectas» (muestra revisada dos veces) | `alertas/revision_doble/` |
| §8.3 dimensiones (`idruta`, `idempresa`, `idproceso`, `id_dia_semana`, `id_estacionalidad`) y filtros por `idruta` | `rendimiento/ciclo_dimensiones_plan.json`; pruebas `tests/integracion/test_api_integracion.py::test_migracion_0006_dimensiones_sube_baja_y_rellena`, `tests/unit/test_dimensiones.py` y `tests/integracion/test_export_alertas.py::test_filtro_por_idruta` |
| §7.1 procesos largos asíncronos (plan del día y respuesta del reto) | `respuesta/api_en_vivo.txt` (404 `sin_calcular`, 202 y lectura de la foto), `rendimiento/ciclo_dimensiones_plan_cierre.json` |
| §7.2 escalamiento de alertas | prueba `tests/integracion/test_api_integracion.py::test_redeteccion_mas_grave_escala_y_notifica` |
| §14.2 «la ejecución programada procesa lo nuevo» | `cola/planificador_programado.txt` (y su `.json` y su script `.py`), `cola/planificador.txt` |
| §3.1 Gestión operacional · §3.2 · §6.1, §6.2 | `catalogos/`, `replica/explain_incremental.txt` |
| §3.1 Predicción · RF-003, RF-005, RF-006, RF-015 · §9.1–§9.4 · E05 | `modelo/resumen_modelo.md` (empezar aquí), `modelo/`, `monitoreo/onnx_paridad.json`, `monitoreo/desagregacion_segmentos.json` |
| §3.1 Optimización · RF-007, RF-008 · §10.1–§10.3 · §12.3 · §18 «Recomendación inviable» | `optimizacion/` |
| §3.1 Anomalías y alertas · RF-009, RF-010, RF-011, RF-012 · §5.1–§5.3 · §18 «Alertas excesivas» | `alertas/`, `demo_ciclo_8nov.txt`, `contrato/README.txt` (filtro espacial `cerca_de` y `radio_m`) |
| RF-006 · §9.3, §9.4 (banda P10–P90 calibrada) | `modelo/calibracion_condicional.md` (calibración v2 por bloque horario) |
| §3.1 Consulta y tablero · E06 · RF-016, RF-017 · RNF-012 | `tablero/` (también las exportaciones `tablero/export_*_dash.*`) |
| RF-018, RF-019 · §9.5 · §18 «Deriva» | `monitoreo/`, `modelo/decision_fv2.md` |
| §14.2 Demostración (ciclo completo) | `despliegue/demo_esperado.md` (qué muestra cada paso y por qué esas fechas), `demo_ciclo.txt` (pila creada desde cero), `despliegue/demo_ciclo_api.txt` (la misma corrida en la pila aislada, 9-11-2026, 08:28–08:31), `demo_ciclo_8nov.txt`, `cola/demo_ciclo_api_cola.txt` |
| RNF-001, RNF-003, RNF-004, RNF-005 · §7.2 planificador | `cola/`, `rendimiento.txt`, `rendimiento/` (duración del ciclo diario). RNF-005: las réplicas se reparten las ejecuciones (`cola/replicas.txt`); partir una ejecución por ruta y fecha es una limitación declarada (`../../../PLAN_EVOLUCION.md`, sección 2) |
| RNF-002 · §14.1 Carga | `rendimiento.txt`, `pruebas/k6_*.txt`, `catalogos/rendimiento.txt` |
| RNF-006 · RNF-010 · §7.2 autenticación · §12.1 · §18 «Exposición de datos» | `seguridad/`, `contrato/traza_entre_replicas.txt` |
| §12.1, §12.2 · RNF-009 (API documentada y versionada) | `contrato/`, `../openapi.json` |
| §14.1 (todos los niveles) · RNF-007 · RNF-014 · E08 · §14.2 «Calidad del código» | `pruebas/`, `contrato/`, `calidad/` |
| RNF-013 · §14.2 «SonarQube» · E03 | `sonarqube/`, `calidad/` |
| RNF-008 · E09 · §14.2 «Instalación» | `despliegue/` |
| §20 · la pregunta final | `respuesta/` |
| E11 · video de máximo 5 minutos | `video/` (cómo se grabó y se verificó; el video está en `../../../documentos/video/`) |
| Corridas reemplazadas (no son evidencia vigente) | `historial/` |

## Raíz de la carpeta

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `demo_ciclo.txt` | El ciclo de §14.2 sobre una pila Docker Compose creada desde cero: llegada de información nueva, lectura incremental, evaluación del error, modelo candidato, comparación con el activo y decisión (el candidato se rechaza con 409 porque no mejora al activo, así que no hay reversión; la reversión se prueba en `tests/integracion/test_api_integracion.py::test_activacion_controlada_y_reversion`). Es copia de `despliegue/demo_ciclo_api.txt`. | §14.2 «Demostración», RF-013, RF-019 | `scripts/verificar_despliegue.py` |
| `demo_ciclo_8nov.txt` | La primera demostración completa contra la API en Docker (8-11-2026): además del ciclo, gestión de alertas con su bitácora y una transición inválida (409), exportaciones y notificaciones simuladas. Es de antes del modelo vigente: el activo era `hgb_fv1_20250831_s42` y su evaluación inicial era dentro de la muestra. El ciclo con el modelo vigente está en `despliegue/demo_ciclo_api.txt` y su salida de referencia, en `despliegue/demo_esperado.md`. | §14.2, RF-011, RF-012, RF-017 | `scripts/demo_ciclo.py --base http://127.0.0.1:8000` |
| `rendimiento.txt` | p95 de las consultas paginadas con k6 (también durante una ingesta), medición secuencial e ingesta de 111.792 filas con `COPY` (tiempo y memoria). | RNF-002, RNF-003, RNF-004, §14.1 «Carga» | `k6/consultas.js`, `k6/consultas_durante_ingesta.js`, `scripts/medir_rendimiento.py` y `scripts/medir_ingesta.py` |
| `ruff.txt` · `ruff.json` · `bandit.txt` · `bandit.json` | Copias idénticas de los análisis de `calidad/`, que `scripts/sonar_local.py` deja también aquí (la ruta que usaban versiones anteriores de `sonar-project.properties`). La fuente vigente es `calidad/`, que es la que lee `sonar-project.properties`. | RNF-007, RNF-013, E03 | `scripts/sonar_local.py` |

La primera corrida completa de la suite (8-11-2026, 147 pruebas), que estaba en esta raíz, se movió a `historial/`
(`historial/suite_8nov_pytest.txt`, `.xml` y `historial/suite_8nov_coverage.xml`). Las exportaciones que descargó la
demostración del 8-11-2026, con el modelo fv1 y el esquema de entonces, también se movieron a `historial/`
(`historial/demo_8nov_export_predictions.csv` y `historial/demo_8nov_export_recommendations.xlsx`); las vigentes están en `tablero/` (`export_*_dash.*`). La suite vigente es
la de la tabla «Cifras vigentes».

## `alertas/` · reglas, estructura de §5.3 y volumen de alertas

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `README.md` | Dónde está cada campo de §5.3 (columna por columna), las reglas ALT-005 a ALT-009 con datos observados, los episodios y la deduplicación, el seudónimo del conductor y la ubicación `geography` con GiST. | §5.1–§5.3, RF-009, RF-010, RF-015, §8.1, §9.4, §18 | Documento del equipo; cita las pruebas. |
| `alertas_observadas_ejemplo.json` | Cinco alertas reales guardadas por PostgreSQL, con todos sus campos y su bitácora. | §5.3, RF-010 | `tests/integracion/test_alertas_observadas.py` |
| `backtest_alertas.md` · `.json` | Alertas observadas por ruta y día del 15-sep al 31-dic-2025 (ALT-002 observada, ALT-005 a ALT-009 y la ruptura de comportamiento: 1,238 por ruta y día) y su precisión aproximada por código, con el modelo activo; sensibilidad a cada umbral. | §18 «Alertas excesivas», §5.1 | `scripts/backtest_alertas.py` |
| `backtest_alertas_corte_2024-12-31.md` · `.json` | Lo mismo con un modelo entrenado hasta el 31-12-2024 (más días evaluados). | §18, §9.3 | `scripts/backtest_alertas.py --corte 2024-12-31` (entrena en un directorio temporal) |
| `caso_silencio_7h.json` | Un caso real (SILENCIO, jueves 16-10-2025, 7 h: 669 pasajeros por hora, P90 759): la alerta de sobreocupación y la recomendación del optimizador dicen la misma ocupación, con y sin el factor de carga. | §5.2, §9.4, §10.2 | `tests/unit/test_alertas_optimizador.py::test_silencio_7h_la_alerta_y_la_recomendacion_dicen_la_misma_ocupacion` |
| `backtest_alertas_pronostico.md` · `.json` | Alertas de pronóstico ALT-001 a ALT-004 del ciclo diario del 15-sep al 31-dic-2025, antes y después de medir la carga crítica por hora de la franja recomendada (ahora: ALT-001 0,435, ALT-002 0,315, ALT-003 0,380 y ALT-004 0,031 por ruta y día), con su confirmación contra la demanda real. | §18 «Alertas excesivas», §5.2 | `scripts/backtest_alertas.py --pronostico` |
| `pytest_alertas_unitarias.txt` · `pytest_alertas_integracion.txt` | Cada regla con su caso «se dispara / no se dispara» en la frontera; ejecución real que produce ALT-005 a ALT-009; la base rechaza un conductor en claro. | RF-009, RF-010, §14.2 «las alertas se deduplican» | `pytest tests/unit/test_alertas*.py` y `tests/integracion/test_alertas_observadas.py` |
| `revision_doble` (carpeta) | La muestra de alertas etiquetada dos veces: el protocolo escrito (`protocolo.md`), la muestra (`muestra.json` y una ficha por alerta en `muestra/`), las etiquetas de dos revisores independientes (`etiquetas_A.json`, `etiquetas_B.json`), la conciliación (`conciliacion.json`, `conciliar.py`) y el resultado con el kappa de acuerdo (`resumen.md`; índice en `README.md`): kappa 0,943 y precisión reponderada 0,839. Los revisores fueron automatizados; falta la validación del área operativa de Sobusa. | §18 «Etiquetas incorrectas», §19 | Flujo descrito en `revision_doble/protocolo.md` |

## `calidad/` · análisis estático vigente

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `ruff.txt` · `ruff.json` | Análisis con ruff de todo el repositorio de la API (reglas E, F, W, I, B, UP y S). | RNF-007, E03 | `scripts/sonar_local.py` (corre `ruff check .`) |
| `bandit.txt` · `bandit.json` | Análisis de seguridad con bandit de `app/` (y de `scripts/` en el `.txt`). `bandit.json` es el que importa SonarQube. | RNF-013, E03 | `scripts/sonar_local.py` (corre `bandit -r app` y `bandit -r scripts`) |
| `bandit_scripts.json` | El análisis de bandit sobre `scripts/`, en JSON. | RNF-013 | ídem |

## `catalogos/` · gestión operacional de solo lectura

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `README.md` | Qué catálogos hay, de dónde salen y cómo se regeneran. | §3.1 «Gestión operacional» | Documento del equipo |
| `fidelidad_y_relaciones.txt` | La réplica, leída con `lector_ia` (solo lectura, America/Bogota), da los mismos conteos que los archivos, y no hay viajes sin ruta ni sin vehículo. | RF-001, RF-014, §6.3 «Relacional» | `docs/evidencias/catalogos/generar_evidencias.py` |
| `catalogos_replica.json` · `catalogos_archivos.json` | Conteos y muestras de cada catálogo por fuente. | RF-016 | ídem |
| `rendimiento.txt` | p95 de cada catálogo, muy por debajo de 2 s. | RNF-002 | ídem |
| `medir_exportaciones.py` | El script de `rendimiento_exportaciones.txt` (mide en proceso, no escribe nada). | — | — |
| `rendimiento_exportaciones.txt` | Los dos catálogos más pesados antes y después de no convertir geometrías que se descartan: `GET /catalogos/segmentos?geometria=completa` pasa de 8,09 s a 1,68 s en la primera petición, y la exportación XLSX de despachos (tope de 100.000 filas), de 27,6–40,3 s a unos 18,4 s. Medido en proceso, con las funciones que llaman los routers. | RNF-002 | Medición descrita en el archivo |
| `sin_datos_personales.txt` | Columnas que nunca salen (placa, conductor, propietario, contactos, módem, GPS) y que no aparecen en ninguna respuesta. | §18 «Exposición de datos» | ídem |
| `ajuste_capacidad.txt` | El ajuste local de capacidad: solo admin, motivo obligatorio, versión nueva auditada y leída por el optimizador; nunca toca las tablas de Extreme. | §3.2, §8.3, RF-007 | ídem |
| `fechas_8_1.json` | Recorrido de todas las rutas GET de `/api/v1`: los instantes salen en ISO con -05:00; lista los casos pendientes de otras rutas. | §8.1, §12.1 | `tests/integracion/test_catalogos_api.py::test_toda_la_api_presenta_los_instantes_en_bogota` |
| `pytest_catalogos.txt` | Pruebas de los catálogos operacionales, unitarias e integración, con la réplica local arriba: 42 de 42 pasan, 0 omitidas (9-11-2026, 05:35–05:36). | RNF-014 | pytest |
| `generar_evidencias.py` | El script que produce los archivos de esta carpeta. | — | — |

## `cola/` · asincronía, réplicas, caídas e ingesta

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `caida_rnf001.txt` · `.json` | Se mata el proceso de la API en la lectura y en la predicción, y también muere la réplica dueña del trabajo. En los tres casos la ejecución termina `ok` con los mismos conteos que una corrida limpia, sin duplicados ni pérdidas. | RNF-001 | `scripts/prueba_caida.py` (también `PRUEBA_CAIDA=1 pytest tests/integracion/test_caida.py`) |
| `caida_rnf001_docker.txt` · `.json` | Lo mismo con réplicas en contenedores Linux y `docker kill` (SIGKILL real). | RNF-001, RNF-008 | `scripts/prueba_caida.py --docker <imagen>` |
| `replicas.txt` | Dos réplicas de la API procesan 20 ejecuciones: reparto 10/10, un intento `ok` por ejecución, 0 duplicados y marca de agua contigua. | RNF-005 | `scripts/prueba_replicas.py` |
| `planificador.txt` | El planificador con dos réplicas encola una sola ejecución por franja. | §7.2, RF-013 | `scripts/prueba_replicas.py --planificador-minutos 3` (cron `*/1 * * * *`) |
| `ingesta.txt` | Ingesta de 111.792 filas con `COPY`: tiempo, memoria pico, recarga idéntica sin cambios y recarga parcial que actualiza solo lo cambiado. | RNF-003, §14.2 «una carga repetida no duplica» | `scripts/medir_ingesta.py` |
| `demo_ciclo_api_cola.txt` | El ciclo de §14.2 pasando por la cola: tres ejecuciones y un entrenamiento. | §14.2, RNF-004 | `scripts/demo_ciclo_api.py` |
| `planificador_programado.txt` · `.json` | La ejecución PROGRAMADA de §14.2, sin ningún POST: el planificador (cron cada minuto) hace la carga inicial; después de la llegada de un día nuevo y de tres filas modificadas, la franja siguiente lee solo esas filas y deja predicciones, recomendaciones y alertas nuevas; la franja posterior, sin llegada, lee 0 filas y no reprocesa el histórico. | §14.2 «la ejecución programada procesa lo nuevo o modificado», §7.2, RF-013 | `planificador_programado.py` |
| `planificador_programado.py` | Script de la evidencia del planificador sin ningún POST manual: migra una base local desechable, arranca la API con el planificador cada minuto, hace llegar un día nuevo y tres filas modificadas, y comprueba que la franja siguiente lee solo lo nuevo y deja predicciones, recomendaciones y alertas, y que la posterior, sin llegada, lee 0 filas. | §14.2 «la ejecución programada procesa lo nuevo», §7.2, RF-013 | El script está en la carpeta (uso en su encabezado) |

## `datos/` · linaje, definición de pasajeros y errores por lote

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `linaje.md` · `.json` | De dónde sale cada archivo empaquetado en `datos/` de la API (la exportación única de la base del reto, en solo lectura) y su reconstrucción desde la réplica con `lector_ia`, con el SHA-256 de lo empaquetado y de lo reconstruido. | RF-001, RF-014, §8.2, E04 | `python -m scripts.reconstruir_desde_replica --linaje` |
| `definicion_pasajeros.md` · `.json` | La lectura integrada (`FUENTE_TABLA=demanda_segmentos`) usa la misma definición de pasajeros que el objetivo del modelo (Σ `numeropasajeros` de los viajes válidos por hora de salida); la Σ de subidas de `timbradas_segmentos` queda aparte, con la diferencia medida en el solape de 2023. | RF-001, RF-013, §9.5 | `python -m scripts.reconstruir_desde_replica --definicion-pasajeros` |
| `errores_lote.txt` | Un lote con un defecto por regla pasa por el ciclo y `GET /api/v1/frequency/executions/{id}/errors` devuelve cada error con su lote, fila, llave, campo, valor, código, dimensión, causa y si bloquea; las filas bloqueadas no entran al histórico. | §6.3, §14.2 «errores por lote», RF-004 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_errores_lote.py` |
| `LEEME.md` | Índice de esta carpeta, con cómo se regenera cada archivo. | — | Documento del equipo |

## `contrato/` · contrato OpenAPI

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `README.txt` | Qué garantiza el contrato y qué prueba lo demuestra. | §12.1, §12.2, RNF-009 | Documento del equipo |
| `operaciones_codigos.txt` | Cada una de las 62 operaciones (59 rutas) del OpenAPI con su rol mínimo, los códigos que declara (todos los errores con el esquema uniforme) y los tipos de contenido del éxito. | §12.1, §12.2, RNF-009 | Generado desde `app.openapi()` (`app/openapi_doc.py`) por `generar_evidencia_contrato.py` |
| `schemathesis.txt` · `schemathesis_junit.xml` | Schemathesis sobre todas las operaciones con cinco chequeos (sin errores 5xx, códigos, tipos de contenido, esquemas y cabeceras documentados), con una subprueba por operación: 62 de 62 sin fallas (9-11-2026, 07:47–07:49). | §14.1 «Contrato», §12.1 | `tests/contrato/test_schemathesis.py`, desde `generar_evidencia_contrato.py` |
| `generar_evidencia_contrato.py` | El script que regenera `operaciones_codigos.txt`, `schemathesis.txt` y `schemathesis_junit.xml` con la base local de pruebas. | — | `python docs/evidencias/contrato/generar_evidencia_contrato.py` |
| `traza_entre_replicas.txt` | La réplica que toma un trabajo de la cola continúa la traza W3C de la petición que lo encoló. | RNF-006 | `tests/integracion/test_traza_entre_replicas.py` |
| `en_vivo_uvicorn.txt` | Contra un servidor real: el byte NUL y los valores fuera de rango responden 422 con el error uniforme y la cabecera `X-Correlation-Id`, y cada respuesta trae el tipo de contenido documentado. | §12.1, RNF-009 | `uvicorn app.main:app` y peticiones HTTP (comandos en el archivo) |
| `pytest_contrato.txt` | El nivel «Contrato» completo (`tests/contrato`) con el contrato estricto (9-11-2026, 07:49–07:51): 178 casos (116 pruebas y 62 subpruebas de Schemathesis), 0 fallas, 0 errores, 0 omitidas y sin xfail. | §14.1 «Contrato», §12.1, RNF-009 | `pytest tests/contrato` (comando completo en el archivo) |
| `suite_completa_junit.xml` | Junit de una corrida intermedia de la suite completa (unitarias, integración, réplica, contrato y datos/ML) del 9-11-2026 a las 03:42: 828 pruebas, 0 fallas, 0 errores y 4 omitidas. La suite vigente es la de la tabla «Cifras vigentes». | §14.1, RNF-014 | `pytest tests/unit tests/integracion tests/replica tests/contrato tests/datos_ml --junitxml=…` |

## `despliegue/` · contenedores y despliegue reproducible (E09)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `arranque_limpio.txt` | Registro de la verificación del despliegue en una pila Docker Compose aislada, desde volúmenes nuevos: tiempo de cada fase (construcción, base sana, migraciones, `/health`, claves de API creadas dentro del contenedor, demostración, reinicios y limpieza final) y, al final, el resultado de cada comprobación. | RNF-008, E09, §14.2 «Instalación» | `scripts/verificar_despliegue.py` |
| `migraciones.txt` | El servicio `migrar` aplica las migraciones desde cero sobre la base nueva (log de Alembic, versión, tablas y PostGIS). | E04, RNF-009 | ídem |
| `reinicio.txt` | La API en contenedor se recupera de un `docker kill` y de un reinicio ordenado a mitad de una ejecución, sin perder ni duplicar lotes, predicciones ni alertas. | RNF-001 | ídem |
| `construccion_sin_cache.txt` | La imagen se construye desde cero, con todas las dependencias como ruedas binarias para CPython 3.11. | RNF-008, E09 | `docker build` sin caché (comando en el archivo) |
| `pytest_despliegue.txt` | La suite completa después de separar las dependencias de ejecución (`requirements.txt`) y de desarrollo (`requirements-dev.txt`) y de rehacer el Dockerfile y los archivos de Compose, con los conteos por nivel. | RNF-014, E03, E09 | pytest con `TEST_DATABASE_NAME` propio (comando en el archivo) |
| `modo_integrado.txt` | La API en contenedor contra la réplica: migra como `escritor_ia`, lee como `lector_ia` y ejecuta el ciclo sin tocar las tablas de Extreme. | E07, E09, §11.3 | `docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml` (pasos en el archivo) |
| `demo_ciclo_api.txt` | El ciclo de §14.2 contra la API en contenedor, en la pila aislada: (1) llegada de información nueva, (2) lectura incremental, (3) evaluación del error, (4) modelo candidato, (5) comparación con el activo y (6) decisión: la compuerta de cuatro criterios rechaza al candidato `hgb_fv2_20250930_s42` (WAPE 14,108 % frente a 13,982 % del activo en 2025-12-01..14), activarlo sin forzar responde 409 y el activo sigue. Corrida del 9-11-2026, 08:28–08:31, código 0 en 190,9 s. | §14.2 «Demostración», E11 | `scripts/verificar_despliegue.py` (que corre `scripts/demo_ciclo_api.py`) |
| `demo_esperado.md` | Qué tiene que mostrar cada uno de los seis pasos de la demostración y por qué esas fechas, con la salida de referencia contra la API sin Docker (9-11-2026, 07:30, base nueva migrada hasta la 0007): carga inicial de 49.623 filas, día nuevo de 51, candidato `hgb_fv2_20250930_s42` en sombra del 1 al 14-12-2025 (714 filas) y la compuerta de cuatro criterios, que lo rechaza (WAPE 14,11 % frente a 13,98 % del activo). | §14.2 «Demostración», RF-018, RF-019 | `scripts/demo_ciclo_api.py --hasta 2025-08-30 --corte 2025-09-30 --revertir` (montaje en el archivo) |
| `verificacion_manuales.txt` | Los comandos nuevos de los manuales, contra un servidor propio con autenticación: 400 `cuerpo_ilegible`, 422 `caracter_nulo` y `fuera_de_rango`, `x-rol-minimo` en el OpenAPI de entonces (50 de operador, 4 de analista y 4 de admin; 57 rutas y 60 operaciones, antes de `POST /respuesta/calcular` y `POST /thresholds/{version}/aprobar`), 401 y 403 con `rol_requerido`, los campos nuevos de la alerta, el filtro por lugar (422 por encima de 50 km), `GET /respuesta` y `/respuesta/export` (entonces, 404 `sin_datos` sin plan; hoy, 404 `sin_calcular` sin foto: `respuesta/api_en_vivo.txt`) y la calibración v2 en la predicción. Es del 9-11-2026 a las 04:51; la demostración que cita con el mismo montaje está ahora en `historial/demo_ciclo_api_uvicorn_9nov_0508.txt`. | E10, §12.1, RNF-009 | Peticiones HTTP contra `uvicorn` (montaje en el encabezado del archivo) |
| `imagen.txt` | La imagen de la API: tamaño (365,8 MB de capas, 1,51 GB en disco), usuario sin privilegios `sobusa` (uid 10001), HEALTHCHECK, variables (ninguna secreta), sin herramientas de desarrollo, y el `pip freeze` de la imagen igual a `requirements.txt`. | RNF-008, E09, §7.1 «dependencias reproducibles» | `scripts/verificar_despliegue.py` |
| `pg_stat_statements_db.txt` | La base de resultados del servicio `db` arranca con `pg_stat_statements` cargado (pila aislada `sobusa_limpio`, volumen nuevo), para medir las consultas de la API. | RNF-002, §14.1 «Rendimiento», E09 | `docker compose -p sobusa_limpio up -d db` y consultas descritas en el archivo |
| `actualizacion_pila_en_vivo.txt` | La pila local `sobusa_api` se actualizó sin perder datos: migraciones aditivas 0001 → 0005 con el servicio `migrar` y solo la API recreada; el contenedor de la base quedó igual (mismo Id, inicio e imagen). | RNF-008, §8.1, E04 | Procedimiento de `../despliegue.md`, sección 9 («Actualizar una pila en uso sin perder datos») |

## `modelo/` · modelo de demanda (E05)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `resumen_modelo.md` | Resumen del modelo para el jurado: protocolo sin fuga, mejora sobre la línea base, error, robustez e incertidumbre, cada cifra con su archivo. | §9, §16 «Modelo predictivo» | Documento del equipo, con cifras de esta carpeta |
| `calibracion_condicional.md` · `.json` | Comparación de la calibración v1 de la banda P10–P90 (conformal móvil por ruta) con calibraciones por grupo, elegida solo con la validación; la prueba reservada solo se reporta. La adoptada (v2, por bloque horario, versionada junto al modelo en `calibracion_v2.json`) da en la prueba reservada una cobertura de 77,82 % (v1: 77,88 %) con un ancho medio de 303,4 pasajeros (v1: 312,9). `CALIBRACION_BANDA=v1` vuelve a la v1. | RF-006, §9.3, §9.4 | `scripts/calibrar_por_grupo.py` |
| `calibracion_condicional_hgb_fv1_20250831_s42.md` · `.json` | La misma comparación, con el mismo criterio, para el modelo de reversión `hgb_fv1_20250831_s42`, para que también tenga su calibración elegida solo con la validación. | RF-006, RF-019 (reversión), §9.4 | `scripts/calibrar_por_grupo.py` con ese modelo |
| `ciclo_recomendacion_franja.json` | El ciclo diario antes y después de recomendar con la función objetivo de §10.2 (demanda por hora y banda calibrada) en lugar de la línea base de §10.3. | RF-007, §10.2, §7.3 | Tres ejecuciones seguidas contra una base local de pruebas (protocolo en el archivo) |
| `pesos_objetivo_0005.json` | La migración 0005 deja visibles y versionados los pesos y costos de §10.2 desde la instalación. | §5.1 «Regla de gobierno», §10.2 | `alembic upgrade head` sobre una base local de pruebas |
| `evaluacion_modelo.md` · `.json` | Prueba reservada nov.–dic. 2025: MAE, RMSE, WAPE con IC95, sMAPE y sesgo del modelo activo frente a fv1 y a las líneas base B1 y B2, por ruta, franja, pico y valle; cobertura P10–P90; robustez con modelos congelados un año. | §9.3, §14.2 «el modelo supera la línea base», §16 «Modelo» | `scripts/evaluar_modelo.py` |
| `decision_fv2.md` | Por qué se activó fv2 y qué cambió: variables, bandas calibradas, perfil intrahorario y explicación SHAP. | RF-019, §9.5 | Documento del equipo, con cifras de los archivos de esta carpeta |
| `entrenamiento_fv2.json` | Dos entrenamientos con la misma semilla, en carpetas temporales, dan un artefacto con el mismo SHA-256, igual al registrado. | §9.3 «Registrar semilla…», E05 | `scripts/entrenar.py --hasta 2025-08-31 --semilla 42 --compuerta-activo --verificar-reproducible` |
| `horizontes.json` | Error a 30, 60 y 120 minutos. | RF-005, §2.2 | `scripts/evaluar_horizontes.py` |
| `pytest_datos_recientes_y_activacion.txt` | Pruebas del modelo con los datos validados recientes en la inferencia (el Parquet empaquetado más `demanda_observada`), la activación gobernada y la prueba reservada como reporte informativo: integración y unitarias, 0 fallos. | RF-013, RF-018, RF-019, §9.3, §9.5 | pytest (comandos en el archivo) |
| `predecir_horas_lote.json` | El pronóstico en lote de todas las horas de un día (`predecir_horas`, el que usa el ciclo) da lo mismo que pronosticar hora por hora y es unas 15 veces más rápido por ruta. | RNF-004, §9.2 | `scripts/evaluar_lote_inferencia.py` |
| `explicacion_local_y_bandas.json` | La explicación SHAP reconstruye el pronóstico de las 3.111 horas de la prueba reservada (base × factores = pronóstico); latencia de SHAP y de `predecir()` y un ejemplo. | RF-006, RF-015, §9.4 | Medición del equipo descrita en `modelo/decision_fv2.md` («Explicación local»); la exactitud la verifica `tests/unit/test_inferencia.py` |
| `contexto_operacional.json` | Novedades viales, festivos y vísperas usados como contexto del pronóstico. | RF-003 | `scripts/preparar_datos_api.py --solo-contexto` |
| `docker_py311_shap.json` | La imagen `python:3.11-slim` construye y predice con SHAP. | §7.1 «Python 3.11 o superior», RNF-008 | Construcción de prueba de la imagen |
| `pytest_modelo.txt` | Corrida de las pruebas del modelo y de la suite. | RNF-014 | pytest |

La corrida de la suite completa de las 05:32 que estaba aquí (`pytest_suite_modelo.txt`, 904 pruebas y 0 fallas) se
movió a `historial/modelo_suite_9nov_0532.txt`; la suite vigente es la de la tabla «Cifras vigentes».

## `monitoreo/` · monitoreo, aprendizaje continuo, ONNX y segmentos

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `monitoreo_2025.json` | Monitoreo semanal de sep.–dic. 2025: WAPE móvil, cobertura, PSI por variable y estado. | §9.4, §18 «Deriva» | `scripts/evidencias_monitoreo.py` |
| `psi_dia_lag7.json` | Por qué `dia_lag7` tiene un umbral de deriva calibrado con su propio ruido. | §9.4 | ídem |
| `compuerta_ejemplo.json` | Un candidato en sombra pasa por la compuerta de 4 criterios; se activa y se revierte solo si se degrada. | RF-018, RF-019, §9.5, §14.2 «Activación» | ídem |
| `onnx_paridad.json` | El modelo exportado a ONNX da los mismos pronósticos que scikit-learn y es más rápido. | §9.1, §9.2 | `scripts/exportar_onnx.py` |
| `desagregacion_segmentos.json` | Error del reparto del pronóstico por segmento y sentido. | §9.1, §9.3 «Analizar el sesgo por … segmento» | `scripts/preparar_segmentos.py` y `scripts/evidencias_monitoreo.py` |

La corrida de la suite completa de las 05:32 que estaba aquí (`pytest_suite.txt` y `.xml`, la misma que
`historial/modelo_suite_9nov_0532.txt`) se movió a `historial/monitoreo_suite_9nov_0532.txt` y `.xml`. La corrida de las 05:33 que estaba en `alertas/` está en
`historial/alertas_suite_9nov_0533.txt`.

## `optimizacion/` · frecuencia y flota

El índice detallado está en `optimizacion/LEEME.md`.

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `sensibilidad.md` · `.json` | Formulación de §10.2 y 13 franjas reales (3 rutas, con el lunes festivo 17-nov-2025): recomendación, límites que mandan, líneas base de §10.3, frecuencia programada, variaciones que cambian la recomendación y MILP = enumeración exacta. | §10.2, §10.3, RF-008 | `scripts/sensibilidad.py` |
| `ejemplo_calculate.json` | Una recomendación viable con pesos, restricciones, tipologías, comparación con lo programado y explicación. | RF-007, RF-015, §10.1 | `tests/integracion/test_recomendaciones.py` |
| `ejemplo_calculate_no_viable.json` | Franja inviable: `viable = false`, motivo en cifras y mejor aproximación ejecutable. | §10.3, §18 «Recomendación inviable» | ídem |
| `ejemplo_escenario_y_sensibilidad.json` | «Qué pasa si» y sensibilidad en la respuesta. | RF-008 | ídem |
| `pesos_versionados.json` | Los pesos de §10.2 se versionan en `threshold_config` y cambian la recomendación. | §5.1 «Regla de gobierno», §10.2 | ídem |
| `ejemplo_plan_d5.json` | Plan del día por hora con el MILP D5. | RF-007, §10.1 | ídem |
| `ejemplo_prediccion_12_3.json` | `POST /predictions/run` con las claves exactas del ejemplo de §12.3. | §12.3 | ídem |
| `ejemplo_prediccion_12_3_no_viable.json` | El mismo contrato de §12.3 cuando la franja no es viable: cifras nulas, `viable = false` y el motivo. | §12.3, §18 «Recomendación inviable» | ídem |
| `viabilidad.md` · `.json` | Qué franjas de 2025 salen no viables por ruta, hora y tipo de día con el modelo activo y los umbrales vigentes, y qué condición las volvería viables (reparto por tipología, P90 frente a la demanda puntual, ciclo, headway mínimo o varias a la vez). | §10.3, §18 «Recomendación inviable», §19 | `scripts/viabilidad.py` |
| `pytest_optimizacion.txt` | Pruebas del optimizador con el código final (9-11-2026, 07:39–07:41): 81 unitarias del área y 12 de integración de `test_recomendaciones.py` pasan, 30 de los módulos vecinos que consumen el plan, las 566 unitarias y 6 de compatibilidad del contrato; 0 fallas. | RNF-014 | pytest (comandos en el archivo) |
| `LEEME.md` | Índice de esta carpeta, con cómo se regenera cada archivo. | — | Documento del equipo |

## `pruebas/` · niveles de §14.1 e integración continua

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `README.md` | Índice de esta carpeta: cómo corre la integración continua (GitHub Actions y el ensayo local con `scripts/ci_local.py`), qué se omite en una máquina limpia y por qué, y qué muestra cada archivo. | §14.2 «Calidad del código», RNF-014 | Documento del equipo |
| `ci_local.txt` · `ci` (carpeta: `ci/pytest.xml`, `ci/coverage.xml`, `ci/pasos.json` y `ci/caida.txt`) | Los mismos pasos del CI ejecutados en local: ruff, bandit, Alembic de ida y vuelta, pytest con cobertura y Testcontainers, y el resultado de cada paso. En la copia limpia de `ci_limpio.txt`, `ci/pytest.xml` registra 912 casos, 744 aprobados, 0 fallas, 0 errores y 168 omitidos, y `ci/coverage.xml`, 91,94 % de `app/`. | §14.2 «Calidad del código», RNF-007, RNF-014 | `scripts/ci_local.py todo` |
| `hallazgos_contrato.txt` | Defectos que encontraron las pruebas de contrato (Schemathesis), con la petición exacta que los reproduce. | §14.1 «Contrato» | `tests/contrato/` |
| `k6_consultas.txt` · `.json` | Carga con k6 sobre las consultas paginadas: p95 de 451,3 ms y 0 % de errores, con el p95 de cada recurso. | RNF-002, §14.1 «Carga» | `k6/consultas.js` |
| `k6_ingesta.txt` · `.json` | Consultas mientras corre una ingesta como job. | RNF-002, RNF-004 | `k6/consultas_durante_ingesta.js` |
| `ci_dependencias_y_acciones.txt` | Las dependencias fijadas instalan con ruedas binarias en `python:3.11-slim` y las versiones de las acciones del CI existen. | §7.1, E03 | Ensayo del paso de dependencias del CI |
| `ci_limpio.txt` | La integración continua en una copia limpia, como la ve GitHub Actions o un jurado al clonar: solo lo que git versiona, fin de línea de Linux, sin `.env` ni los datos de la raíz, y el resultado de cada paso del flujo. | §14.2 «las pruebas automatizadas pasan en integración continua», RNF-007, RNF-014 | `ensayo_copia_limpia.py` |
| `ensayo_copia_limpia.py` | El script de `ci_limpio.txt`: arma la copia limpia y corre en ella `scripts/ci_local.py` (y, con `--caida`, la prueba de caída). | — | — |
| `k6_volumen.txt` · `.json` | Carga con k6 sobre el volumen acordado: un año de resultados del ciclo diario sembrado con filas reales (`scripts/sembrar_volumen.py`). Con 50 usuarios, p95 de 627,5 ms y 0 % de errores. En frío, `GET /segmentos/estadisticas` no cumple (8,8 s; con `idruta`, 2,3 a 2,9 s), con el arreglo propuesto en el archivo. | RNF-002, §14.1 «Carga» | `k6/` contra una base local aparte (comandos en el archivo) |
| `k6_en_frio.json` | Resumen de k6 de la prueba en frío: la API recién arrancada, la primera petición a cada ruta sin calentamiento y una segunda pasada inmediata. | RNF-002 | `k6/en_frio.js` (descrito en `k6_volumen.txt`, sección 4) |

## `rendimiento/` · duración del ciclo diario

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `ciclo_antes_despues.md` · `.json` | Duración del ciclo diario (`POST /api/v1/frequency/executions`) con los mismos cortes de la demostración de §14.2 (carga inicial de 49.623 filas, día nuevo de 51 filas y repetición sin filas nuevas), antes y después de quitar el recorrido cuadrático de `contexto_observado` y la optimización repetida por horizonte, sin cambiar los resultados; cada corrida con una base local nueva y una copia temporal de `datos/`. | RNF-004, §14.2 «Demostración» | `scripts/medir_ciclo.py` |
| `perfil_ciclo_antes.txt` · `perfil_ciclo_despues.txt` | Las 25 funciones con más tiempo según cProfile en cada versión (de dónde se iba el tiempo). | RNF-004 | ídem, con el perfilador |
| `ciclo_dimensiones_plan.md` | La lectura de esa medición: qué agrega cada ejecución desde esta versión y cuánto tarda cada etapa. | RNF-004, §7.1, §8.3 | `scripts/medir_ciclo.py` |
| `ciclo_dimensiones_plan.json` | La misma medición del ciclo diario con lo que se agregó después: las dimensiones de §8.3 en cada fila y, al cierre, el plan del día siguiente y la foto de la respuesta del reto; con los conteos y el SHA-256 del resultado. | RNF-004, §7.1, §8.3 | `scripts/medir_ciclo.py` |
| `ciclo_dimensiones_plan_cierre.json` | Las duraciones internas del cierre del ciclo (plan del día y foto de la respuesta), leídas de `execution_log.metricas` en esa misma corrida. | RNF-004 | ídem |
| `ciclo_final.md` · `.json` | **La medición vigente del ciclo diario** (9-11-2026, 07:29), con los mismos cortes: la foto de la respuesta reutiliza el plan del día, la serie de la ruptura de comportamiento (RF-009) corre en cada ciclo y los umbrales nuevos quedan versionados (migración 0007). Carga inicial de 49.623 filas en 24,1 s (antes, 103,4 s), día nuevo de 51 filas en 21,4 s (antes, 50,9 s) y repetición en 0,1 s; las predicciones tienen el mismo SHA-256 que `ciclo_dimensiones_plan.json`. | RNF-004, RF-009, §7.1, §14.2 «Demostración» | `scripts/medir_ciclo.py --etiqueta final_plan_reutilizado --salida docs/evidencias/rendimiento/ciclo_final.json` |

## `replica/` · integración con la base operacional (E07)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `replica_init.log` · `replica_objetos.txt` | La réplica (PostgreSQL 14 + PostGIS) se inicializa con los 8 scripts de Extreme sin modificar (`SHA256SUMS`); quedan sus funciones y su trigger activo. | RF-002, §6.1, §11.1 | `docker compose -p sobusa_rep --profile integracion up -d operacional` |
| `replica_errata.txt` | Cada corrección mínima (E1, E2, H1) con la prueba del fallo sin ella. | RF-002, §19 | `scripts/replica_evidencias.py` |
| `replica_carga.txt` · `.json` · `replica_carga_historial.txt` | Carga de 3,38 millones de filas desde las exportaciones: conteos iguales, llaves foráneas sin huérfanos, tiempo y memoria. | RNF-003, §8.2 | `scripts/replica_cargar.py` |
| `replica_roles.txt` | `lector_ia` no puede escribir nada (32 intentos rechazados) y `escritor_ia` solo escribe en `ai_frecuencias`. | §8.3, §11.3, §18 | `scripts/replica_evidencias.py` |
| `replica_llegada.txt` · `.json` | Llegan datos por el trigger de Extreme y la lectura incremental entrega exactamente lo nuevo, y después nada; equivalencia trigger ↔ exportación. | RF-013, §9.5, §11.2, §14.2 «Ejecución incremental» | `scripts/replica_simular_llegada.py --viajes 3 --liquidar --consolidar --ciclo-api` |
| `explain_incremental.txt` · `.json` | `EXPLAIN (ANALYZE, BUFFERS)` de las consultas incrementales como `lector_ia`, antes y después de la propuesta de índices. | §8.3, §14.1 «Rendimiento», §18 «Consulta pesada» | `scripts/replica_explain.py` |
| `explain_misma_carga.txt` | La lectura incremental `demanda_segmentos` con la definición de pasajeros del modelo, la unión con `"Procesos"` y la estacionalidad vigente cuesta lo mismo que la consulta anterior (diferencia dentro del ruido), medidas en el mismo proceso y con la misma carga. | §8.3, §11.2, §14.1 «Rendimiento» | Medición descrita en el archivo |
| `propuesta_indices.sql` | Índices `CREATE INDEX CONCURRENTLY` propuestos al DBA de Extreme; ninguno cambia tablas, triggers ni funciones. | §8.3 | `scripts/replica_explain.py` |
| `replica_contexto.json` | El contexto del modelo, reconstruido desde la base, es idéntico al de los archivos. | RF-003 | `scripts/replica_contexto.py` |
| `pytest_replica.txt` | Pruebas contra la réplica (roles, carga, scripts, llegada, EXPLAIN y segmentos), también las que escriben en ella: 184 aprobadas, 0 fallidas, 0 omitidas. La corrida de la suite completa que acompañaba la versión anterior de este archivo está en `historial/` (describía 2 fallas y 4 xfail ya corregidos). | §14.1 «Integración», RF-002 | `pytest tests/replica` con `REPLICA_PRUEBAS_ESCRITURA=1` (comando en el archivo) |

## `respuesta/` · la pregunta final del reto (§20)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `respuesta_reto.md` | Por día, ruta y franja: cada cuánto despachar frente a lo programado, pasajeros esperados con P10–P90 frente a los observados, vehículos frente a la flota, costo, espera, sobreocupación y recaudo. | §20, §1 | `scripts/respuesta_reto.py` (el mismo servicio de `GET /api/v1/respuesta`) |
| `respuesta_<fecha>.json` | La respuesta completa de `GET /api/v1/respuesta` para cada día de ejemplo, con su trazabilidad: un laboral, un sábado y un domingo de noviembre de 2025 (19, 22 y 23) y el 1-ene-2026, el día siguiente al último dato (festivo de Año Nuevo, pronóstico del modelo activo). | §20, RNF-011 | ídem |
| `api_en_vivo.txt` · `api_respuesta_CRA54_2025-11-19.json` | La misma respuesta por HTTP, con la autenticación encendida: 401 sin clave, 403 si un operador pide el cálculo, 404 `sin_calcular` cuando no hay foto, el cálculo en la cola con `POST /api/v1/respuesta/calcular` (202), 200 con clave de operador, latencia, exportación y alertas abiertas reales. | §20, §12.1, §7.1 | Servidor de prueba contra una base local con el ciclo diario ya corrido (protocolo en el archivo) |
| `pytest_respuesta.txt` | Pruebas unitarias y de integración de la respuesta. | §20, RNF-014 | `pytest tests/unit/test_respuesta.py tests/integracion/test_respuesta_api.py` |
| `LEEME.md` | Índice de esta carpeta. | — | Documento del equipo |

## `seguridad/` · autenticación, resiliencia y observabilidad

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `matriz_roles.txt` | Cada ruta con 5 identidades (sin clave, clave inválida, operador, analista y admin): 401, 403 o permitido, según la matriz. | §7.2, §12.1 | `tests/integracion/test_seguridad.py` |
| `openapi_seguridad.json` | Todas las operaciones de `/api/v1` declaran el esquema de seguridad `ApiKey`. | §12.1 | OpenAPI de la aplicación |
| `resiliencia.txt` | El circuit breaker de la fuente se abre tras 3 fallos, falla rápido, pasa a semiabierto y se cierra; `/health` y `/metrics` lo reflejan. | RNF-010 | `tests/integracion/test_circuito_integracion.py` |
| `traza_ejecucion.json` · `logs_json_ejecucion.txt` | Una ejecución completa es una sola traza OpenTelemetry (HTTP, SQL y cada etapa) y sus logs JSON llevan `correlation_id`, `execution_id`, `worker_id`, `trace_id` y `span_id`. | RNF-006, §12.1 «Correlation-Id» | `tests/integracion/test_observabilidad_ejecucion.py` |
| `jaeger_traza_ejecucion.json` · `jaeger_resumen.txt` · `logs_api_jaeger.txt` · `log_api_evidencia_jaeger.txt` | La misma traza vista en Jaeger (39 spans), con los 401 y 403 previos y los logs de la API de esa corrida. | RNF-006 | `docs/evidencias/seguridad/generar_evidencia_jaeger.py` |
| `generar_evidencia_jaeger.py` | El script de la evidencia de Jaeger. | — | — |

La continuidad de la traza cuando otra réplica toma el trabajo de la cola (atributo `traza_origen` = `execution_log`) está
en `contrato/traza_entre_replicas.txt`. La corrida de la suite del 9-11-2026 a las 01:13 que estaba aquí
(`pytest_suite.txt` y `.xml`, 348 pruebas) se movió a `historial/`.

## `sonarqube/` · análisis con SonarQube

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `resumen.md` | Servidor, perfil de calidad, resultado de la puerta de calidad condición por condición y medidas del análisis. | RNF-013, §14.2 «SonarQube», E03 | `scripts/sonar_local.py` |
| `quality_gate.json` · `measures.json` · `issues.json` · `hotspots.json` · `perfil_calidad.json` | Lo que devuelve la API de SonarQube para ese análisis. | RNF-013 | ídem |
| `scanner.log` | Log del escáner. | RNF-013 | ídem |
| `corrida.json` | Resumen de la corrida: resultado de pytest (pruebas, fallas, omitidas, duración), del análisis estático (`lint`) y código de salida del escáner. | RNF-013, RNF-014 | ídem |
| `pytest.xml` · `pytest.log` · `coverage.xml` | La corrida de pruebas con cobertura que se le entrega a SonarQube en ese análisis; es la suite final de la tabla «Cifras vigentes» (9-11-2026, 12:36–12:49: 1060 casos, 0 fallas, 0 errores y 5 omitidos; cobertura de `app/` de 94,27 %). `pytest.xml` y `coverage.xml` son idénticos byte a byte a `pruebas/suite_final.xml` y `pruebas/coverage_final.xml`. | RNF-014, RNF-013 | ídem |
| `tablero_sonarqube.png` · `hallazgos_sonarqube.png` | Capturas del proyecto en SonarQube. | RNF-013 | ídem |

## `tablero/` · el tablero que consume la API (E06)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `alertas_1366x768.png` · `alertas_completa.png` · `alertas_detalle_1366x768.png` · `alertas_409_1366x768.png` · `alertas_sin_api_1366x768.png` | Bandeja y detalle de alertas con los campos de §5.3, aviso de transición inválida y comportamiento con la API caída. | §3.1 «Consulta y tablero», RF-011, RF-016 | Capturas del recorrido automático con navegador |
| `recomendaciones_*.png` | Recomendación frente a la frecuencia programada, escenario y API caída. | RF-007, RF-008 | ídem |
| `operacion_*.png` | Ejecuciones, modelos, umbrales y monitoreo; bloqueo de acciones con rol operador (403). | RF-016, RF-019, §5.1 | ídem |
| `barra_1280.png` | Barra de navegación a 1280 px. | RNF-012 | ídem |
| `e2e_tablero.txt` · `e2e_tablero.json` · `e2e_tablero_auth.json` | Cada paso del recorrido (filtros, paginación, detalle, acciones, exportaciones, errores 409 y 422 visibles), también con la autenticación encendida. | E06, RF-011, RF-017 | Recorrido automático con navegador contra el tablero y la API |
| `export_alertas_dash.csv` · `.xlsx` · `export_recomendaciones_dash.csv` · `.xlsx` | Exportaciones descargadas desde el tablero. | RF-017 | ídem |
| `pytest_export_alertas.txt` | La exportación de alertas respeta los filtros y abre en Excel con los encabezados de §5.3. | RF-017 | `tests/integracion/test_export_alertas.py` |
| `siete_pantallas_8205.txt` | Las siete pantallas del laboratorio siguen funcionando con las pantallas nuevas. | E06 | Pruebas de las pantallas contra un tablero de prueba |
| `verificar_estilo_estatico.txt` · `verificar_estilo_vivo_api_arriba.txt` · `verificar_estilo_vivo_api_caida.txt` | Contraste mínimo de cada par de colores, colores solo por rol, tamaños de la escala y 0 errores de consola, con la API arriba y caída. | RNF-012 | `dash_app/verificar_estilo.py` |
| `LEEME.md` | Índice de esta carpeta: qué se comprobó del tablero y con qué archivo. | E06 | Documento del equipo |
| `e2e_tablero_completo.txt` · `.json` · `.py` | Recorrido automático de las once pantallas con Edge sin interfaz a 1600×900, con clave de analista, de operador y una clave inválida: 135 de 135 comprobaciones bien, 0 fallas (9-11-2026, 07:05–07:08). | E06, RF-011, RF-016, RF-017, RNF-012 | `e2e_tablero_completo.py` (el script está en la carpeta) |
| `export_monitoreo_dash.csv` · `.xlsx` · `export_respuesta_dash.csv` · `.xlsx` | Exportaciones descargadas desde las pantallas Monitoreo (`GET /monitoring/export`) e Inicio (la respuesta del reto, `GET /respuesta/export`) en ese recorrido. | RF-017, §20 | ídem |
| `dash_*.png` | Capturas de cada pantalla en ese recorrido: Inicio (también la tarjeta de la respuesta del reto), Pronóstico, Horario, Despacho, El modelo, Resultado, Enlaces, Alertas (bandeja y detalle), Recomendaciones (escenario, plan del día y franja no viable), Operación y Monitoreo (con la política); y los avisos de 401 y 403. | E06, §20, RNF-012 | ídem |
| `barra_once_pestanas.txt` | La barra de navegación con las once pestañas cabe sin desbordarse desde 1101 px. | RNF-012 | Medición con el navegador sin interfaz |
| `verificar_estilo_estatico_once.txt` · `verificar_estilo_vivo_once.txt` | La verificación del sistema de diseño con las once pantallas: pasa, con 0 fallas. | RNF-012 | `dash_app/verificar_estilo.py` |
| `despacho_carga_en_frio.txt` · `.py` | La consola Despacho en cinco cargas en frío (contexto nuevo, sin caché): 5 de 5 sin errores de consola y con los buses en el mapa. El mapa espera a que MapLibre cargue su estilo antes de recibir los buses; la corrida anterior al arreglo (2 errores «Style is not done loading») está en `historial/`. | RNF-012, E06 | `despacho_carga_en_frio.py` (el script está en la carpeta) |
| `export_predicciones_dash.csv` · `.xlsx` | Los pronósticos del modelo activo exportados desde la sección «Modelo activo (API)» de Pronóstico (`GET /api/v1/predictions/export`), con el esquema vigente (`model_id`, `feature_version`, `data_cutoff`, banda y explicación). | RF-017, §9.2 | Recorrido del tablero contra la API |
| `funciones_tablero.txt` · `.py` | Las funciones nuevas del tablero, sin servidor: el orden de prioridad y el aviso «Escalada» de Alertas, los nombres de los experimentos del informe en El modelo y la lectura de lo real por ventana en Pronóstico (9 de 9 bien). | E06, §7.2, RNF-012 | `funciones_tablero.py` (el script está en la carpeta) |
| `verificar_ahorro_once.txt` | Las cifras de ahorro del tablero coinciden con sus archivos de origen: 342 comprobaciones bien, 0 fallas. | E06 | `dash_app/verificar_ahorro.py` |

## `video/` · cómo se grabó el video de E11

El video está en `../../../documentos/video/E11_video_demostracion.mp4` (menos de 5 minutos), con sus subtítulos
(`.srt`) y su guion (`guion.md`: escena, segundos, narración, pantalla y evidencia de cada cifra).

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `registro.txt` | Cómo se grabó: herramientas y versiones, entorno aislado (API y tablero del código entregado, base de pruebas propia, copia temporal de `datos/`, claves de prueba que no aparecen en pantalla), la ejecución en vivo y la tabla de escenas con sus tiempos y 0 errores de consola. | E11, §16 «Presentación y adopción» | Grabación automática con el navegador y narración sintetizada (detalle en el archivo) |
| `verificacion_video.json` | La verificación del archivo final: duración, resolución, audio, número de cuadros y los cuadros revisados por escena. | E11 | `ffmpeg` sobre el MP4 final |
| `plan_mezcla.json` | El montaje: de qué toma y de qué tramo sale cada escena, y su duración frente a la de la narración. | E11 | Script de montaje del video |
| `cuadros` (carpeta) | Un cuadro por escena (14 PNG), para revisar el contenido sin reproducir el video. | E11 | Extraídos del MP4 final |

## `historial/` · corridas reemplazadas

`historial/README.md` dice, archivo por archivo, qué era, de dónde se movió y qué lo reemplaza. Ninguna cifra vigente
sale de aquí.

| Archivo | Qué era | Lo reemplaza |
|---|---|---|
| `README.md` | Índice de la carpeta. | — |
| `suite_8nov_pytest.txt` · `suite_8nov_pytest.xml` · `suite_8nov_coverage.xml` | Primera corrida de la suite (8-11-2026): 147 pruebas, cobertura de 90,96 %. | `contrato/suite_completa_junit.xml`, `sonarqube/pytest.xml` y `sonarqube/coverage.xml` |
| `seguridad_suite_9nov_0113.txt` · `seguridad_suite_9nov_0113.xml` | Unitarias e integración al agregar las pruebas de seguridad (9-11-2026, 01:13): 348 pruebas. | Las mismas suites vigentes; la evidencia de seguridad sigue en `seguridad/` |
| `replica_suite_9nov_0244.txt` | Suite completa del 9-11-2026 a las 02:44: 683 aprobadas, 2 fallidas y 4 xfail, ya corregidos. | `contrato/pytest_contrato.txt` y `replica/pytest_replica.txt` |
| `pruebas_suite_normal_9nov_0243.txt` · `pruebas_suite_normal_9nov_0243.xml` | Suite completa sin Testcontainers del 9-11-2026 a las 02:43: 734 pasan, 2 fallan, 7 con error y 4 xfail de contrato, ya corregidos (estaba en `pruebas/`). | La suite final de la tabla «Cifras vigentes» y `pruebas/ci/pytest.xml` |
| `alertas_suite_9nov_0533.txt` | Suite completa del 9-11-2026 a las 05:33 con el detalle de las pruebas de alertas: 904 casos, 0 fallas (estaba en `alertas/`). | La suite final de la tabla «Cifras vigentes»; las pruebas de alertas solas, en `alertas/pytest_alertas_*.txt` |
| `monitoreo_suite_9nov_0532.txt` · `monitoreo_suite_9nov_0532.xml` · `modelo_suite_9nov_0532.txt` | Suite completa del 9-11-2026 a las 05:32 con el detalle de las pruebas del modelo, el monitoreo y la política: 904 pruebas, 0 fallas (estaba en `monitoreo/` y en `modelo/`). | La suite final de la tabla «Cifras vigentes»; las pruebas del modelo solas, en `modelo/pytest_modelo.txt` |
| `demo_8nov_export_predictions.csv` · `demo_8nov_export_recommendations.xlsx` | Exportaciones de la demostración del 8-11-2026, con el modelo fv1 y el esquema de entonces (estaban en la raíz). | `tablero/export_predicciones_dash.*` y `tablero/export_recomendaciones_dash.*` |
| `demo_ciclo_api_uvicorn_9nov_0508.txt` | La demostración de §14.2 contra la API sin Docker del 9-11-2026 a las 05:08, con la línea de tiempo de entonces (base hasta la 0005, comparación en 2025-10-01..2025-10-28; estaba en `despliegue/`). | `despliegue/demo_ciclo_api.txt` y `despliegue/demo_esperado.md` |
| `tablero_estilo_vivo_intento_despacho_en_frio.txt` | Verificación en vivo del tablero antes del arreglo del mapa de Despacho: 2 fallas. | `tablero/despacho_carga_en_frio.txt` y `tablero/verificar_estilo_vivo_once.txt` |
