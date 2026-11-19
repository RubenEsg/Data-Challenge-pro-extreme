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
| Candidato `hgb_fv3_20250831_s42` (fv2 + calendario escolar y universitario), registrado y sin activar; elegido con la validación y los backtests congelados | Validación 12,96 % frente a 13,55 % de fv2. Backtests: 2024, 15,76 % frente a 16,26 % (diferencia de −0,81 a −0,25 pp, 11 de 12 meses); 2025, 14,08 % frente a 14,48 % (de −0,78 a −0,12 pp, 8 de 12 meses). Prueba reservada (informativa): 14,36 % (IC95 12,98–16,13) frente a 14,77 % de fv2 y 21,18 % de B1 | `modelo/decision_fv3.md`, `modelo/candidato_fv3/evaluacion_modelo.md` |
| El mismo modelo congelado al 31-12-2024, todo 2025 | WAPE 14,48 % (IC95 13,78–15,28) frente a 20,04 % de B1 | `modelo/evaluacion_modelo.md` («Robustez») |
| Error por horizonte, mar.–dic. 2025 | 30 min 19,43 %, 60 min 14,71 % y 120 min 10,87 % (B1: 23,12 %, 18,96 % y 15,44 %) | `modelo/horizontes.json` |
| Banda P10–P90, calibración v2 por bloque horario | Cobertura de 77,82 % (v1: 77,88 %), ancho medio de 303,4 pasajeros (v1: 312,9) | `modelo/calibracion_condicional.md` |
| Alertas observadas, backtest del 15-sep al 31-dic-2025 (324 días-ruta) con el modelo activo | 1,265 por ruta y día con todas las reglas observadas (ALT-002 observada, ALT-005 a ALT-009 y la ruptura de comportamiento), con el factor de carga del ciclo; solo ALT-005 a ALT-009: 0,543. ALT-008 evalúa subidas, bajadas y número de viajes: 0,071 por ruta y día | `alertas/backtest_alertas.md` |
| Alertas de pronóstico del ciclo diario, mismo periodo | ALT-001 0,438 (lift 1,81), ALT-002 0,306 (lift 2,03), ALT-003 0,164 (lift 1,05; 2,08 donde puede emitirse) y ALT-004 0,031 (lift 7,62) por ruta y día: 0,938. Con las observadas, 2,203 alertas por ruta y día (1,265 + 0,938) | `alertas/backtest_alertas_pronostico.md`; el total lo calcula `scripts/cifras_vigentes.py` con los conteos de los dos backtests |
| ALT-003 con el mínimo de probabilidad elegido sin fuga (0,30; validación del 15-sep al 31-oct, evaluación del 1-nov al 31-dic-2025) | En la evaluación, precisión 0,552, lift 2,08 [1,51; 2,99] donde puede emitirse y 1,16 [0,82; 1,51] sobre todas las franjas (IC bootstrap del 95 %) | `alertas/backtest_alertas_pronostico.md` («ALT-003: diagnóstico y elección del umbral sin fuga») |
| Revisión doble de una muestra de 96 alertas (dos revisores automatizados con un protocolo escrito; falta la validación del área operativa de Sobusa, que tiene listo el kit de `alertas/revision_doble/kit_humano/`) | Kappa de Cohen 0,943 (IC95 0,854–1,000) entre los revisores; precisión reponderada 0,839 (IC95 0,757–0,882) | `alertas/revision_doble/resumen.md` (`conciliacion.json`) |
| Pronóstico de corto plazo que sirve la API (`cp_lgbm_20250630_s42`, el de `../../../pronostico_corto_plazo/`), prueba reservada del 1-jul al 31-dic-2025, calculada una vez | Por ruta a 60 minutos, WAPE 7,34 % frente a 13,18 % del promedio por día y hora; por segmento, 37,63 % frente a 43,61 %. La API reproduce las 168.210 predicciones guardadas de esa prueba (diferencia máxima 0,0054 subidas) y el WAPE de los nueve niveles y horizontes | `modelo/corto_plazo_reproduccion.md`, `../../../pronostico_corto_plazo/resultados/prueba.json` |
| Modelo por segmento y sentido `seg_hgb_jerarquico_20230227_s42`, prueba única del 18 al 27-feb-2023 | WAPE por segmento y hora de 42,09 frente a 43,06 del reparto fijo B0 (IC95 de la diferencia de −1,60 a −0,02 pp); por sentido y hora, 8,19 frente a 8,20. Banda P10–P90 con el total real de la ruta: cobertura de 78,31 % por segmento y 83,40 % por sentido | `modelo/segmentos_modelo.md` (`segmentos_modelo.json`); el IC95, en `modelo/segmentos_banda_ventanas.json` |
| Suite completa final (unitarias, integración, réplica, contrato y datos/ML), la corrida que analiza SonarQube (18-11-2026) | 1.810 casos (1.121 unitarias, 223 de integración, 209 de réplica, 209 de contrato y 48 de datos/ML): 1.800 aprobados, 0 fallas, 0 errores y 10 omitidas: las pruebas pesadas que solo corren con `PRUEBA_CAIDA=1`, `PRUEBA_REPLICAS=1`, `PRUEBA_PLANIFICADOR=1` o `REPLICA_PRUEBAS_ESCRITURA=1`, que este cambio no toca (con ellas encendidas, la suite del 14-11-2026 pasó entera: 1.770 casos y 0 omitidas) | `pruebas/suite_final.xml` (idéntico a `sonarqube/pytest.xml`; resumen en `sonarqube/corrida.json`) |
| Cobertura de `app/`, con `motor_d5/`, en esa suite final | 95,76 % (15.464 de 16.148 líneas; umbral del CI: 85 %) | `pruebas/coverage_final.xml` (idéntico a `sonarqube/coverage.xml`) |
| SonarQube, puerta de calidad «Reto Sobusa v1.5» sobre todo el código (análisis del 18-11-2026, 21:29) | **OK** (aprobada): vulnerabilidades 0, bugs 0, hallazgos bloqueantes 0 y críticos 0 (umbral: 0), duplicación 0,0 % (umbral: 3 %) y cobertura 95,8 % (umbral: 85 %); 1 hallazgo de mantenibilidad aceptado con su justificación (la copia literal del solver D5, app/servicios/motor_d5/milp.py) (`scripts/sonar_decisiones.json`) | `sonarqube/quality_gate.json` (condición por condición en `sonarqube/resumen.md`) |
| Integración continua en una copia limpia (sin réplica, como un runner nuevo), sobre el código final (14-11-2026) | 7 de 7 pasos OK; pytest: 1.773 casos, 1.566 aprobados, 0 fallas, 0 errores y 207 omitidos (las pruebas de la réplica se omiten con su motivo); el trabajo de caída y ejecución programada, 3 de 3 | `pruebas/ci_limpio.txt`, `pruebas/ci/pytest.xml` |
| Cobertura de `app/`, con `motor_d5/`, en la copia limpia | 95,15 % (umbral del CI: 85 %) | `pruebas/ci/coverage.xml` |
| Ciclo diario (`POST /api/v1/frequency/executions`) con el plan del día, la foto de la respuesta y la serie de la ruptura | Carga inicial de 49.623 filas en 27,5 s, día nuevo de 51 filas en 20,7 s y repetición sin filas nuevas en 0,2 s (13-11-2026, 22:24), con las alertas observadas de 7 días, la foto por segmento y el plan con más detalle; mismo SHA-256 del resultado que el 11-11-2026 | `rendimiento/ciclo_final.md` |
| Carga con k6 (umbral: p95 < 2 s) | Medición vigente (13-11-2026, código final), con 1.056 ejecuciones sembradas desde el ciclo final (9.216 predicciones y 8.224 alertas) y 50 usuarios: p95 de 864,1 ms y 0 % de errores. `GET /segmentos/estadisticas` lee la agregación materializada: 20,8 ms en frío y 18,3 ms en caliente (antes de la migración 0008, 8,8 y 11,9 s); con 50 usuarios sobre la capa de segmentos y un refresco completo en curso, p95 de 372,3 ms (332,4 ms durante el refresco), con una petición fallida de 3.806. Durante una ingesta desde la réplica, p95 de 574,5 ms; la ingesta, 225,8 s. Mediciones anteriores: consultas con un mes de resultados, p95 de 451,3 ms; con un año (9-11-2026), 627,5 ms | `pruebas/k6_segmentos.txt` (vigente); `pruebas/k6_consultas.txt`, `pruebas/k6_volumen.txt` y `pruebas/revision_segmentos/` (anteriores) |
| Agregación materializada de segmentos frente a la agregación directa, en la réplica | 8 de 8 combinaciones de filtros, orden y paginación con los mismos ítems y el mismo total | `pruebas/segmentos_equivalencia.json` |
| Refresco incremental de la agregación de segmentos sin filas nuevas, en la réplica (RNF-004) | Sin huellas comparables relee 26 fechas (164.206 filas) en 10,5 s; con las huellas de la ventana de solape, 0 fechas y 0 filas en 0,5 s, sin escribir nada. Tras el refresco parcial, `segmento_estadistica` tiene 0 filas distintas de rehacerla entera | `pruebas/segmentos_sin_cambios.json` |
| Ocupación por segmento (§10.1), ene.–feb. 2023 | Carga a bordo derivada de las subidas y bajadas por segmento frente a la ocupación máxima del dispositivo: correlación 0,961 en 21.511 viajes. Restricción reactiva con los viajes completos (cota superior): 147 disparos, la hora siguiente sobre el umbral en el 28,6 % (tasa base: 5,9 %) y 457 salidas más, 292 de ellas en horas que no quedaron sobre el umbral; con los viajes en curso siguen 25 disparos a las (h+1):05 y 35 a las (h+1):30 | `ocupacion/perfil_ocupacion_segmentos.json` (`validacion`) y `ocupacion/backtest_restriccion_reactiva.md` |
| Consolidados de Extreme en el ciclo, en la réplica y en solo lectura (§6.1, §6.3, §11.2) | `timbradas_consolidado`: 10.731 filas leídas y válidas, sin errores de calidad; la segunda lectura las descarta por huella. Contraste con el histórico propio 2023-2025: 174 llaves, 160 comparadas, 31 incidencias y 11 groseras (H17). Las tablas por segmento no tienen filas de Sobusa (H4): con filas reales de la liquidación de tres viajes en una transacción que se revierte y `contraste_viajes_minimos` = 1, su contraste sin la hora del bloque (H10) compara 90 de 90 llaves, con 5 diferencias no bloqueantes y ninguna grosera; con la hora en el grano serían 129 groseras y 56 llaves bloqueadas | `consolidados/contraste_consolidados.md`, `consolidados/segmentos_filas_reales.json` |
| Bajadas del histórico frente a las de los segmentos, solape de 2023 | En los mismos viajes, Σ bajadas de los segmentos y Σ `numerobajadas` difieren 0,1 %; en total, −5,3 %, por cobertura | `consolidados/definicion_bajadas.md` |
| Ejecución partida por ruta con dos réplicas (RNF-005), 6 días | 24 de 24 trabajos `ok` (6 madres y 18 de ruta), 14 pares de rutas distintas a la vez, 0 cruces de la misma ruta, 0 duplicados y las mismas salidas que sin partir; lote en 55,8 s partido frente a 61,1 s sin partir (13-11-2026) | `cola/replicas_por_ruta.txt` |
| Contrato OpenAPI | `../openapi.json`: 70 rutas y 75 operaciones (73 de `/api/v1`). Schemathesis con cinco chequeos: 75 de 75 operaciones sin fallas. Nivel de contrato: 209 casos (134 pruebas y 75 subpruebas), 0 fallas, 0 errores y 0 omitidas (18-11-2026; la suite final vuelve a correr `tests/contrato`) | `contrato/operaciones_codigos.txt`, `contrato/schemathesis.txt`, `contrato/pytest_contrato.txt` |
| Migraciones de la base de resultados | 0001 → 0015 (`0015_prediccion_corto_plazo`), con una sola cabeza | `../../alembic/versions/` |
| Demostración de §14.2 (seis pasos) | El candidato `hgb_fv3_20250930_s42` y el activo se comparan en la sombra del 1 al 14-12-2025 (714 filas) con la compuerta de cuatro criterios: WAPE 13,58 % frente a 13,98 % y los cuatro criterios se cumplen, así que el candidato se activa; la demostración lo revierte al final con `POST /models/rollback` (18-11-2026) | `despliegue/demo_ciclo_api.txt` |
| Respuesta a la pregunta del reto | Por día, ruta y franja | `respuesta/respuesta_reto.md` y `../../../documentos/respuesta_pregunta_reto.md` |

Las cifras de los experimentos 11 y 12 del informe académico (13,94 % y 13,62 %) usan otro protocolo (7 días de
antelación, todo 2025 y reentrenamiento mensual) y no son cifras de este producto: la explicación está en el
`README.md` de la entrega, «Las cifras principales».

## Mapa rápido: requisito → carpeta

| Requisito de la especificación | Dónde está la evidencia |
|---|---|
| §2.2 «30, 60 y 120 minutos» · §3.1 M3 · RF-005 · §9.1 · §9.3: el pronóstico por ruta, sentido y segmento, con validación y prueba en meses distintos | `../../../pronostico_corto_plazo/` (abajo, «Fuera de esta carpeta»); en la API, `modelo/corto_plazo_reproduccion.md`; en el tablero, `tablero/e2e_corto_plazo.txt` |
| §3.1 Acceso y calidad · RF-001, RF-002, RF-004, RF-013, RF-014 · §8.2, §8.3, §11 · E07 | `replica/`, `catalogos/fidelidad_y_relaciones.txt`, `../integracion_postgresql.md`, `datos/` |
| §6.3 · §14.2 «errores por lote, con causa y fila» | `datos/errores_lote.txt`; el reporte de unicidad al responsable del consolidado, `datos/reporte_unicidad.json` |
| §5.2 ALT-008 con bajadas · §6.1 bajadas y consolidados (`nro_viajes`, promedios, `ultima_actualizacion`) · §6.3 consistencia de los promedios · §7.3 paso 3 · §11.2 | `consolidados/` (`../consolidados_ciclo.md`), `alertas/backtest_alertas.md` |
| §11.2 · §6.1 novedades viales por fecha, rango horario y ruta | `datos/novedades_por_ruta.json` (con y sin filas en `novedades_viales_ruta`), `replica/novedades_por_ruta_replica.json` (la réplica, con la tabla vacía) |
| Linaje de los datos empaquetados y definición de pasajeros | `datos/linaje.md`, `datos/definicion_pasajeros.md` |
| §18 «Etiquetas incorrectas» (muestra revisada dos veces) | `alertas/revision_doble/` |
| §8.3 dimensiones (`idruta`, `idempresa`, `idproceso`, `id_dia_semana`, `id_estacionalidad`) y filtros por `idruta` | `rendimiento/ciclo_dimensiones_plan.json`; pruebas `tests/integracion/test_api_integracion.py::test_migracion_0006_dimensiones_sube_baja_y_rellena`, `tests/unit/test_dimensiones.py` y `tests/integracion/test_export_alertas.py::test_filtro_por_idruta` |
| §7.1 procesos largos asíncronos (plan del día y respuesta del reto) | `respuesta/api_en_vivo.txt` (404 `sin_calcular`, 202 y lectura de la foto), `rendimiento/ciclo_dimensiones_plan_cierre.json` |
| §7.2 escalamiento de alertas | prueba `tests/integracion/test_api_integracion.py::test_redeteccion_mas_grave_escala_y_notifica` |
| §14.2 «la ejecución programada procesa lo nuevo» | `cola/planificador_programado.txt` (y su `.json` y su script `.py`), `cola/planificador.txt` |
| §3.1 Gestión operacional · §3.2 · §6.1, §6.2 | `catalogos/`, `replica/explain_incremental.txt`, `pruebas/segmentos_equivalencia.json` (agregación de segmentos) |
| §5.1 «Regla de gobierno» · §3.1 flota y tiempo de ciclo · §6.1 y §6.2 headway vigente de `rutas.frecuenciadespachos` · §6.3 oportunidad | `gobierno/` (`gobierno/indice.md`) |
| §3.1 Predicción · RF-003, RF-005, RF-006, RF-015 · §9.1–§9.4 · E05 | `modelo/resumen_modelo.md` (empezar aquí), `modelo/` (por segmento y sentido: `segmentos_protocolo.md`, `segmentos_modelo.md`, `segmentos_banda_ventanas.json`), `monitoreo/onnx_paridad.json`, `monitoreo/desagregacion_segmentos.json` |
| §7.3 paso 4 (variables por ruta, sentido, segmento y ventana) · §11.2 | `monitoreo/foto_segmentos.json`, `monitoreo/foto_segmentos_demo.txt`, `monitoreo/foto_segmentos_revision.txt` |
| §3.1 Optimización · RF-007, RF-008 · §10.1–§10.3 · §12.3 · §18 «Recomendación inviable» | `optimizacion/` |
| §10.1 ocupación histórica y actual por segmento · §5.2 ALT-002 observada | `ocupacion/` (`../ocupacion_segmentos.md`) |
| §18 «Exposición de datos → retención» | `retencion/` (`../retencion_datos.md`) |
| §3.1 Anomalías y alertas · RF-009, RF-010, RF-011, RF-012 · §5.1–§5.3 · §18 «Alertas excesivas» | `alertas/`, `demo_ciclo_8nov.txt`, `contrato/README.txt` (filtro espacial `cerca_de` y `radio_m`) |
| RF-006 · §9.3, §9.4 (banda P10–P90 calibrada) | `modelo/calibracion_condicional.md` (calibración v2 por bloque horario) |
| §3.1 Consulta y tablero · E06 · RF-016, RF-017 · RNF-012 | `tablero/` (también las exportaciones `tablero/export_*_dash.*`) |
| RF-018, RF-019 · §9.5 · §18 «Deriva» | `monitoreo/`, `modelo/decision_fv2.md` |
| §14.2 Demostración (ciclo completo) | `despliegue/demo_esperado.md` (qué muestra cada paso y por qué esas fechas), `demo_ciclo.txt` (pila creada desde cero), `despliegue/demo_ciclo_api.txt` (la misma corrida en la pila aislada, 13-11-2026, 23:07), `demo_ciclo_8nov.txt`, `cola/demo_ciclo_api_cola.txt` |
| RNF-001, RNF-003, RNF-004, RNF-005 · §7.2 planificador | `cola/`, `rendimiento.txt`, `rendimiento/` (duración del ciclo diario). RNF-005: las réplicas se reparten las ejecuciones (`cola/replicas.txt`) y una ejecución se parte por ruta y fecha (`cola/replicas_por_ruta.txt`, `cola/lectura_por_ruta_replica.txt`; `../particion_por_ruta.md`); la convivencia de la ejecución partida con la capa de segmentos y los umbrales gobernados, en la prueba `tests/integracion/test_convivencia_ciclo_segmentos.py`. RNF-004: el refresco de segmentos sin cambios, en `pruebas/segmentos_sin_cambios.json` |
| RNF-002 · §14.1 Carga | `rendimiento.txt`, `pruebas/k6_*.txt` (la capa de segmentos, en `pruebas/k6_segmentos.txt` y `pruebas/revision_segmentos/`), `catalogos/rendimiento.txt` |
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
| `rendimiento.txt` | p95 de las consultas paginadas con k6 (también durante una ingesta), medición secuencial e ingesta de 111.792 filas con `COPY` (tiempo y memoria). Su bloque «DATASET ACORDADO» define el volumen de un año y trae la medición vigente del 13-11-2026 (copiada de `pruebas/k6_segmentos.txt`), sin borrar la del 9-11-2026, que queda rotulada como anterior. | RNF-002, RNF-003, RNF-004, §14.1 «Carga» | `k6/consultas.js`, `k6/consultas_durante_ingesta.js`, `scripts/medir_rendimiento.py` y `scripts/medir_ingesta.py` |
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
| `alertas_observadas_ejemplo.json` | Cinco alertas observadas (ALT-005 a ALT-009) guardadas por PostgreSQL, con todos sus campos, la identificación de §5.3 y su bitácora: viaje, vehículo y seudónimo en ALT-006 y ALT-009, y el motivo en `variables.identificacion_5_3` en ALT-005, ALT-007 y ALT-008. | §5.3, RF-010 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_alertas_observadas.py` |
| `backtest_alertas.md` · `.json` | Alertas observadas por ruta y día del 15-sep al 31-dic-2025 (ALT-002 observada, ALT-005 a ALT-009 y la ruptura de comportamiento: 1,265 por ruta y día, con el factor de carga del ciclo) y su precisión aproximada por código, con el modelo activo; ALT-008 con subidas, bajadas y número de viajes, y lo que daba sin evaluar las bajadas; sensibilidad a cada umbral. | §18 «Alertas excesivas», §5.1, §5.2 ALT-008 | `scripts/backtest_alertas.py` |
| `backtest_alertas_corte_2024-12-31.md` · `.json` | Lo mismo con un modelo entrenado hasta el 31-12-2024 (más días evaluados). | §18, §9.3 | `scripts/backtest_alertas.py --corte 2024-12-31` (entrena en un directorio temporal) |
| `caso_silencio_7h.json` | Un caso real (SILENCIO, jueves 16-10-2025, 7 h: 669 pasajeros por hora, P90 759): la alerta de sobreocupación y la recomendación del optimizador dicen la misma ocupación, con y sin el factor de carga. | §5.2, §9.4, §10.2 | `tests/unit/test_alertas_optimizador.py::test_silencio_7h_la_alerta_y_la_recomendacion_dicen_la_misma_ocupacion` |
| `backtest_alertas_pronostico.md` · `.json` | Alertas de pronóstico ALT-001 a ALT-004 del ciclo diario del 15-sep al 31-dic-2025, antes y después de medir la carga crítica por hora de la franja recomendada (ahora: ALT-001 0,435, ALT-002 0,315, ALT-003 0,167 y ALT-004 0,031 por ruta y día), con su confirmación contra la demanda real, la tasa base donde puede emitirse cada código y la elección sin fuga del mínimo de probabilidad de ALT-003. | §18 «Alertas excesivas», §5.2, §9.3 | `scripts/backtest_alertas.py --pronostico` |
| `pytest_alertas_unitarias.txt` · `pytest_alertas_integracion.txt` | Cada regla con su caso «se dispara / no se dispara» en la frontera; ejecución real que produce ALT-005 a ALT-009; la base rechaza un conductor en claro. | RF-009, RF-010, §14.2 «las alertas se deduplican» | `pytest tests/unit/test_alertas*.py` y `tests/integracion/test_alertas_observadas.py` |
| `revision_doble` (carpeta) | La muestra de alertas etiquetada dos veces: el protocolo escrito (`protocolo.md`), la muestra (`muestra.json` y una ficha por alerta en `muestra/`), las etiquetas de dos revisores independientes (`etiquetas_A.json`, `etiquetas_B.json`), la conciliación (`conciliacion.json`, `conciliar.py`) y el resultado con el kappa de acuerdo (`resumen.md`; índice en `README.md`): kappa 0,943 y precisión reponderada 0,839. Los revisores fueron automatizados; falta la validación del área operativa de Sobusa. Para ella está `kit_humano/`: la página `revisar.html` (sin red y a ciegas), `conciliar_humanos.py` y las instrucciones (`kit_humano/INSTRUCCIONES.md`). | §18 «Etiquetas incorrectas», §19 | Flujo descrito en `revision_doble/protocolo.md`; el kit, con `kit_humano/generar_kit.py` (prueba: `tests/unit/test_kit_revision_humana.py`) |

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
| `pytest_catalogos.txt` | Pruebas de los catálogos operacionales, unitarias e integración, con la réplica local arriba: 46 de 46 pasan (37 unitarias y 9 de integración), 0 omitidas (13-11-2026). | RNF-014 | `scripts/evidencia_pytest.py` (comando en el archivo) |
| `generar_evidencias.py` | El script que produce los archivos de esta carpeta. | — | — |

## `cola/` · asincronía, réplicas, caídas e ingesta

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `caida_rnf001.txt` · `.json` | Se mata el proceso de la API en la lectura y en la predicción, y también muere la réplica dueña del trabajo. En los tres casos la ejecución termina `ok` con los mismos conteos que una corrida limpia, sin duplicados ni pérdidas. | RNF-001 | `scripts/prueba_caida.py` (también `PRUEBA_CAIDA=1 pytest tests/integracion/test_caida.py`) |
| `caida_rnf001_docker.txt` · `.json` | Lo mismo con réplicas en contenedores Linux de la imagen del código final y `docker kill` (SIGKILL real; 13-11-2026). | RNF-001, RNF-008 | `scripts/prueba_caida.py --docker <imagen>` |
| `replicas.txt` | Dos réplicas de la API procesan 20 ejecuciones: reparto 10/10, un intento `ok` por ejecución, 0 duplicados y marca de agua contigua. | RNF-005 | `scripts/prueba_replicas.py` |
| `replicas_por_ruta.txt` · `.json` | Dos réplicas reales con 6 días partidos por ruta: 24 de 24 trabajos `ok`, 14 pares de rutas distintas a la vez, 0 cruces de la misma ruta, 0 duplicados, marcas contiguas por ruta, y las mismas predicciones, recomendaciones, plan, alertas, foto de la respuesta, histórico y monitoreo que sin partir. | RNF-005 | `scripts/prueba_replicas_por_ruta.py --comparar-sin-partir` (también `PRUEBA_REPLICAS=1 pytest tests/integracion/test_replicas_por_ruta.py`) |
| `lectura_por_ruta_replica.txt` · `.json` | En la réplica, como `lector_ia` y en solo lectura, la lectura de cada ruta es exactamente la completa filtrada por esa ruta, desde la carga y desde una marca; EXPLAIN de las dos variantes (sin los índices propuestos, el SELECT de una ruta tarda casi lo mismo que el de todas: 3,4 s frente a 3,9 s). | RNF-005, §11.3 | `python -m scripts.replica_lectura_por_ruta` |
| `planificador.txt` | El planificador con dos réplicas encola una sola ejecución por franja. | §7.2, RF-013 | `scripts/prueba_replicas.py --planificador-minutos 3` (cron `*/1 * * * *`) |
| `ingesta.txt` | Ingesta de 111.792 filas con `COPY` (13-11-2026: 2,32 s, 48.205 filas por segundo y 61 MiB de memoria pico): tiempo, memoria pico, recarga idéntica sin cambios y recarga parcial que actualiza solo lo cambiado. | RNF-003, §14.2 «una carga repetida no duplica» | `scripts/medir_ingesta.py` |
| `demo_ciclo_api_cola.txt` | El ciclo de §14.2 pasando por la cola: tres ejecuciones y un entrenamiento. | §14.2, RNF-004 | `scripts/demo_ciclo_api.py` |
| `planificador_programado.txt` · `.json` | La ejecución PROGRAMADA de §14.2, sin ningún POST: el planificador (cron cada minuto) hace la carga inicial; después de la llegada de un día nuevo y de tres filas modificadas, la franja siguiente lee solo esas filas y deja predicciones, recomendaciones y alertas nuevas; la franja posterior, sin llegada, lee 0 filas y no reprocesa el histórico. | §14.2 «la ejecución programada procesa lo nuevo o modificado», §7.2, RF-013 | `planificador_programado.py` |
| `planificador_programado.py` | Script de la evidencia del planificador sin ningún POST manual: migra una base local desechable, arranca la API con el planificador cada minuto, hace llegar un día nuevo y tres filas modificadas, y comprueba que la franja siguiente lee solo lo nuevo y deja predicciones, recomendaciones y alertas, y que la posterior, sin llegada, lee 0 filas. | §14.2 «la ejecución programada procesa lo nuevo», §7.2, RF-013 | El script está en la carpeta (uso en su encabezado) |

## `consolidados/` · los consolidados de Extreme en el ciclo y las bajadas

El método, las decisiones y los límites están en `../consolidados_ciclo.md`; el índice de la carpeta, en
`consolidados/README.md`. El script lee la réplica local como `lector_ia`, en solo lectura, con las funciones del ciclo
(`app/servicios/consolidados.py` y `app/servicios/calidad.py`), y no consulta la base del reto.

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `contraste_consolidados.md` · `.json` | `timbradas_consolidado` por el camino del ciclo: lectura incremental desde la carga (10.731 filas), calidad de §6.3 sin errores, segunda lectura descartada por huella (H7) y contraste con el histórico propio por ruta × día ISO × estacionalidad (174 llaves, 160 comparadas, 31 incidencias y 11 groseras). Trae también por qué no se contrasta por hora (H10), de dónde salen las diferencias groseras de viajes por día (H17) y las tablas por segmento sin filas de Sobusa (H4). | §6.1, §6.3, §7.3 paso 3, §11.2 | `python -m scripts.contraste_consolidados`; pruebas en `tests/replica/test_consolidados.py` |
| `lectura_por_proceso.md` · `.json` | Lo que el ciclo le consulta a la base de Extreme por cada tabla consolidada en una ejecución sin novedades: antes, la lectura sin filtrar el proceso más `count(*)`; ahora, solo la lectura del proceso en el SQL. Medido con las tablas de la réplica y con el volumen de otro operador en una tabla temporal dentro de una transacción que se revierte; trae los índices candidatos de las tablas por segmento. | §6.1, §8.3, §18 «Consulta pesada» | `python -m scripts.replica_lectura_consolidados` (como `extreme_dba`, porque `lector_ia` no tiene el privilegio TEMP) |
| `segmentos_filas_reales.json` | El contraste por segmento del ciclo con filas reales de la liquidación de tres viajes, en una transacción que se revierte: sin la hora del bloque de Extreme (H10) compara las 90 llaves sin ninguna grosera, una diferencia sembrada bloquea solo su llave y, con la hora en el grano, saldrían 129 groseras falsas (13-11-2026). | §6.1, §11.2, H4, H10 | `REPLICA_PRUEBAS_ESCRITURA=1 GENERAR_EVIDENCIAS=1 pytest tests/replica/test_consolidados_segmentos.py` |
| `definicion_bajadas.md` · `.json` | Por qué el histórico guarda `bajadas_viajes` = Σ `numerobajadas` de los viajes válidos: en el solape de 2023, en los mismos viajes, difiere 0,1 % de las bajadas de los segmentos, y en total −5,3 %, por cobertura (como los pasajeros, `datos/definicion_pasajeros.md`). | §6.1 «Bajadas», §9.5 | ídem; prueba `tests/replica/test_consolidados.py::test_en_los_mismos_viajes_las_bajadas_de_los_segmentos_son_numerobajadas` |
| `README.md` | Índice de esta carpeta. | — | Documento del equipo |

## `datos/` · linaje, definición de pasajeros y errores por lote

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `linaje.md` · `.json` | De dónde sale cada archivo empaquetado en `datos/` de la API (la exportación única de la base del reto, en solo lectura) y su reconstrucción desde la réplica con `lector_ia`, con el SHA-256 de lo empaquetado y de lo reconstruido. Reconstruye idénticos `demanda_horaria`, `contexto_operacional` y `bajadas_horaria`, y `subidas_segmento_hora` salvo el día reservado de la réplica; de los demás archivos de `datos/` da el SHA-256 y el motivo por el que no se reconstruyen. | RF-001, RF-014, §8.2, E04 | `python -m scripts.reconstruir_desde_replica --linaje` |
| `definicion_pasajeros.md` · `.json` | La lectura integrada (`FUENTE_TABLA=demanda_segmentos`) usa la misma definición de pasajeros que el objetivo del modelo (Σ `numeropasajeros` de los viajes válidos por hora de salida); la Σ de subidas de `timbradas_segmentos` queda aparte, con la diferencia medida en el solape de 2023. | RF-001, RF-013, §9.5 | `python -m scripts.reconstruir_desde_replica --definicion-pasajeros` |
| `errores_lote.txt` | Un lote con un defecto por regla pasa por el ciclo y `GET /api/v1/frequency/executions/{execution_id}/errors` devuelve cada error con su lote, fila, llave, campo, valor, código, dimensión, causa y si bloquea; las filas bloqueadas no entran al histórico. | §6.3, §14.2 «errores por lote», RF-004 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_errores_lote.py` |
| `reporte_unicidad.json` | Un lote con una llave duplicada: el reporte al responsable del consolidado (la llave con sus filas, que no se corrigió nada y la ruta de la API con el detalle). Sin `NOTIF_UNICIDAD_DESTINATARIOS` queda `pendiente_destinatario` en `notification_log`; con un destinatario, sale por el correo simulado. Las filas duplicadas no entran al histórico. | §6.3 «reportar al responsable del consolidado; no corregir» | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_errores_lote.py::test_el_lote_con_duplicados_se_reporta_al_responsable_sin_corregir` |
| `novedades_por_ruta.json` | Dos novedades sintéticas leídas con `FuentePostgresSoloLectura` (READ ONLY) desde las tablas de novedades en la base local: con una fila en `novedades_viales_ruta`, esa novedad solo afecta a su ruta; sin filas, las dos afectan a todas. | §11.2, §6.1, RF-003 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_novedades_por_ruta.py` |
| `LEEME.md` | Índice de esta carpeta, con cómo se regenera cada archivo. | — | Documento del equipo |

## `contrato/` · contrato OpenAPI

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `README.txt` | Qué garantiza el contrato y qué prueba lo demuestra. | §12.1, §12.2, RNF-009 | Documento del equipo |
| `operaciones_codigos.txt` | Cada una de las 75 operaciones (70 rutas) del OpenAPI vigente (18-11-2026) con su rol mínimo, los códigos que declara (todos los errores con el esquema uniforme) y los tipos de contenido del éxito. | §12.1, §12.2, RNF-009 | Generado desde `app.openapi()` (`app/openapi_doc.py`) por `generar_evidencia_contrato.py` |
| `schemathesis.txt` · `schemathesis_junit.xml` | Schemathesis sobre todas las operaciones con cinco chequeos (sin errores 5xx, códigos, tipos de contenido, esquemas y cabeceras documentados), con una subprueba por operación: 75 de 75 sin fallas (18-11-2026). | §14.1 «Contrato», §12.1 | `tests/contrato/test_schemathesis.py`, desde `generar_evidencia_contrato.py` |
| `generar_evidencia_contrato.py` | El script que regenera `operaciones_codigos.txt`, `schemathesis.txt` y `schemathesis_junit.xml` con la base local de pruebas. | — | `python docs/evidencias/contrato/generar_evidencia_contrato.py` |
| `traza_entre_replicas.txt` | La réplica que toma un trabajo de la cola continúa la traza W3C de la petición que lo encoló. | RNF-006 | `tests/integracion/test_traza_entre_replicas.py` |
| `en_vivo_uvicorn.txt` | Contra un servidor real: el byte NUL y los valores fuera de rango responden 422 con el error uniforme y la cabecera `X-Correlation-Id`, y cada respuesta trae el tipo de contenido documentado. | §12.1, RNF-009 | `uvicorn app.main:app` y peticiones HTTP (comandos en el archivo) |
| `pytest_contrato.txt` | El nivel «Contrato» completo (`tests/contrato`) con el contrato estricto (18-11-2026): 209 casos (134 pruebas y 75 subpruebas de Schemathesis), 0 fallas, 0 errores, 0 omitidas y sin xfail. | §14.1 «Contrato», §12.1, RNF-009 | `pytest tests/contrato` (comando completo en el archivo) |
| `suite_completa_junit.xml` | Histórico: junit de una corrida intermedia de la suite completa (unitarias, integración, réplica, contrato y datos/ML) del 9-11-2026 a las 03:42: 828 pruebas, 0 fallas, 0 errores y 4 omitidas. La suite vigente es la de la tabla «Cifras vigentes». | §14.1, RNF-014 | `pytest tests/unit tests/integracion tests/replica tests/contrato tests/datos_ml --junitxml=…` |

## `despliegue/` · contenedores y despliegue reproducible (E09)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `arranque_limpio.txt` | Registro de la verificación del despliegue en una pila Docker Compose aislada, desde volúmenes nuevos (18-11-2026, 20:44; «Resultado global: OK» en 5,6 min): tiempo de cada fase (construcción, base sana, migraciones, `/health`, claves de API creadas dentro del contenedor, demostración, reinicios y limpieza final) y, al final, el resultado de cada comprobación. | RNF-008, E09, §14.2 «Instalación» | `scripts/verificar_despliegue.py` |
| `migraciones.txt` | El servicio `migrar` aplica las migraciones desde cero sobre la base nueva, de la 0001 a la 0014 (log de Alembic, versión, tablas y PostGIS). | E04, RNF-009 | ídem |
| `reinicio.txt` | La API en contenedor se recupera de un `docker kill` y de un reinicio ordenado a mitad de una ejecución, sin perder ni duplicar lotes, predicciones ni alertas. | RNF-001 | ídem |
| `construccion_sin_cache.txt` | La imagen se construye desde cero, con todas las dependencias como ruedas binarias para CPython 3.11. | RNF-008, E09 | `docker build` sin caché (comando en el archivo) |
| `pytest_despliegue.txt` | La suite completa después de separar las dependencias de ejecución (`requirements.txt`) y de desarrollo (`requirements-dev.txt`) y de rehacer el Dockerfile y los archivos de Compose, con los conteos por nivel. | RNF-014, E03, E09 | pytest con `TEST_DATABASE_NAME` propio (comando en el archivo) |
| `modo_integrado.txt` | La API en contenedor contra la réplica (13-11-2026): migra como `escritor_ia`, lee como `lector_ia` y ejecuta el ciclo sin tocar las tablas de Extreme. Hace una sola ejecución diaria: no muestra el ciclo intradía programado, cuya evidencia es `ocupacion/planificador_intradia.txt`. | E07, E09, §11.3 | `docker compose -p sobusa_rep -f docker-compose.yml -f docker-compose.integracion.yml` (pasos en el archivo) |
| `demo_ciclo_api.txt` | El ciclo de §14.2 contra la API en contenedor, en la pila aislada: (1) llegada de información nueva, (2) lectura incremental, (3) evaluación del error, (4) modelo candidato, (5) comparación con el activo y (6) decisión: la compuerta de cuatro criterios activa al candidato `hgb_fv3_20250930_s42` (WAPE 13,578 % frente a 13,982 % del activo en 2025-12-01..14; los cuatro criterios se cumplen) y la demostración lo revierte con `POST /models/rollback`. Corrida del 18-11-2026, 20:44, código 0 en 183,1 s. | §14.2 «Demostración», E11 | `scripts/verificar_despliegue.py` (que corre `scripts/demo_ciclo_api.py`) |
| `demo_esperado.md` | Qué tiene que mostrar cada uno de los seis pasos de la demostración y por qué esas fechas, con la salida de referencia contra la API sin Docker (9-11-2026, 07:30, base nueva migrada hasta la 0007): carga inicial de 49.623 filas, día nuevo de 51, candidato `hgb_fv2_20250930_s42` en sombra del 1 al 14-12-2025 (714 filas) y la compuerta de cuatro criterios, que lo rechaza (WAPE 14,11 % frente a 13,98 % del activo). Es de antes de fv3: desde el 15-11-2026 el entrenamiento usa las variables fv3, y la corrida vigente (`demo_ciclo_api.txt`) entrena `hgb_fv3_20250930_s42`, que pasa la compuerta. | §14.2 «Demostración», RF-018, RF-019 | `scripts/demo_ciclo_api.py --hasta 2025-08-30 --corte 2025-09-30 --revertir` (montaje en el archivo) |
| `verificacion_manuales.txt` | Los comandos nuevos de los manuales, contra un servidor propio con autenticación: 400 `cuerpo_ilegible`, 422 `caracter_nulo` y `fuera_de_rango`, `x-rol-minimo` en el OpenAPI de entonces (50 de operador, 4 de analista y 4 de admin; 57 rutas y 60 operaciones, antes de `POST /respuesta/calcular` y `POST /thresholds/{version}/aprobar`), 401 y 403 con `rol_requerido`, los campos nuevos de la alerta, el filtro por lugar (422 por encima de 50 km), `GET /respuesta` y `/respuesta/export` (entonces, 404 `sin_datos` sin plan; hoy, 404 `sin_calcular` sin foto: `respuesta/api_en_vivo.txt`) y la calibración v2 en la predicción. Es del 9-11-2026 a las 04:51; la demostración que cita con el mismo montaje está ahora en `historial/demo_ciclo_api_uvicorn_9nov_0508.txt`. | E10, §12.1, RNF-009 | Peticiones HTTP contra `uvicorn` (montaje en el encabezado del archivo) |
| `imagen.txt` | La imagen de la API: tamaño (365,8 MB de capas, 1,51 GB en disco), usuario sin privilegios `sobusa` (uid 10001), HEALTHCHECK, variables (ninguna secreta), sin herramientas de desarrollo, y el `pip freeze` de la imagen igual a `requirements.txt`. | RNF-008, E09, §7.1 «dependencias reproducibles» | `scripts/verificar_despliegue.py` |
| `pg_stat_statements_db.txt` | La base de resultados del servicio `db` arranca con `pg_stat_statements` cargado (pila aislada `sobusa_limpio`, volumen nuevo), para medir las consultas de la API. | RNF-002, §14.1 «Rendimiento», E09 | `docker compose -p sobusa_limpio up -d db` y consultas descritas en el archivo |
| `actualizacion_pila_en_vivo.txt` | La pila local `sobusa_api` se actualizó sin perder datos: migraciones aditivas 0001 → 0005 con el servicio `migrar` y solo la API recreada; el contenedor de la base quedó igual (mismo Id, inicio e imagen). | RNF-008, §8.1, E04 | Procedimiento de `../despliegue.md`, sección 9 («Actualizar una pila en uso sin perder datos») |

## `gobierno/` · umbrales, parámetros del plan, flota y ciclo gobernados

Qué se cambió y por qué está en `../gobierno_parametros.md`; el índice de la carpeta, con la prueba que escribe cada
archivo, en `gobierno/indice.md`. Los JSON se regeneran con
`GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_gobierno_parametros.py`.

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `umbrales_en_postgresql.json` | Todo umbral o parámetro con valor por omisión en el código está en la versión vigente de `threshold_config`, con su descripción y quién creó la versión. Es la versión vigente 9, de la cabeza 0014, con los grupos de la retención y del contraste de los consolidados y `alt003_probabilidad_minima` (11-11-2026). | §5.1 «Regla de gobierno» | `tests/integracion/test_gobierno_parametros.py::test_todos_los_umbrales_que_usa_el_codigo_estan_en_postgresql` |
| `parametros_plan_gobernados.json` | El plan de CRA 54 antes y después de un `PUT /thresholds` con tarifa, elasticidad y suavidad nuevas: la fuente de cada parámetro, las salidas por hora y el recaudo de la respuesta. | §5.1, §10.2 | `tests/integracion/test_gobierno_parametros.py::test_put_thresholds_cambia_tarifa_elasticidad_y_suavidad_y_el_siguiente_plan_los_usa` |
| `ajuste_flota_ciclo.json` | `PUT /catalogos/flota`: roles, versión nueva, la franja de las 7 h y el plan del día con 40 vehículos, un ciclo de 150 min, validaciones, historial y retiro. | §3.1, §10.2 | `tests/integracion/test_gobierno_parametros.py::test_flota_y_ciclo_por_la_api_versionados_auditados_y_usados_por_la_franja_y_el_plan` |
| `frecuenciadespachos.json` | Una franja y un plan con las dos comparaciones del headway: el intervalo programado observado y `rutas.frecuenciadespachos` (leído en minutos, supuesto S14), la fila guardada y la cabecera de la exportación. | §6.1, §6.2, RF-008 | `tests/integracion/test_gobierno_parametros.py::test_la_recomendacion_guarda_el_headway_vigente_de_frecuenciadespachos` |
| `oportunidad_gobernada.json` | La tolerancia de los datos tardíos de la calidad sale del umbral gobernado de datos atrasados. | §5.1, §6.3 | `tests/integracion/test_gobierno_parametros.py::test_el_ciclo_mide_los_datos_tardios_con_el_umbral_vigente_de_datos_atrasados` |
| `pytest_gobierno_parametros.txt` · `revision_concurrencia_y_factibilidad.txt` | La corrida de las pruebas del cambio y la revisión de los cambios simultáneos y de la suavidad sin solución. | RNF-014, §5.1 | pytest (comandos en los archivos) |

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
| `decision_fv3.md` | Por qué fv3 (calendario escolar y universitario, `datos/calendario_academico.csv`) queda registrado como candidato y no se activa en esta entrega: validación y backtests congelados mejores que fv2 con el IC de la diferencia entero bajo cero, la prueba reservada como reporte, la banda, los horizontes, el factor intradía, ONNX, SHAP y la verificación de que el código nuevo no cambia el modelo activo. | RF-019, §9.3, §9.5 | Documento del equipo, con cifras de los archivos de esta carpeta |
| `entrenamiento_fv3.json` | Dos entrenamientos del candidato `hgb_fv3_20250831_s42` con la misma semilla dan el mismo SHA-256, igual al registrado. | §9.3 «Registrar semilla…», E05 | `scripts/entrenar.py --hasta 2025-08-31 --semilla 42 --compuerta-activo --sin-activar --verificar-reproducible --salida-json docs/evidencias/modelo/entrenamiento_fv3.json` |
| `candidato_fv3/evaluacion_modelo.md` · `.json` | La evaluación del candidato con el mismo protocolo y las mismas filas que la del activo: prueba reservada (informativa) frente a fv2 y a B1/B2, y backtests congelados de 2024 y 2025 con las variables fv3 frente a las fv2, por mes y en las horas que tocan el contexto y el calendario académico. | §9.3, §9.4, RF-019 | `scripts/evaluar_modelo.py --modelo hgb_fv3_20250831_s42 --anterior hgb_fv2_20250831_s42 --salida docs/evidencias/modelo/candidato_fv3` |
| `candidato_fv3/horizontes.json` · `candidato_fv3/explicacion_local_y_bandas.json` | Error a 30, 60 y 120 minutos con las variables fv3, y la explicación SHAP del candidato (reconstrucción exacta en las 3.111 horas de la prueba, latencias, un ejemplo y la reversión a fv2 y fv1). | RF-005, RF-006, RF-015, §9.4 | `scripts/evaluar_horizontes.py --version fv3-2026-11-16 --salida docs/evidencias/modelo/candidato_fv3` y `scripts/evidencia_explicacion_local.py --model-id hgb_fv3_20250831_s42 --salida docs/evidencias/modelo/candidato_fv3/explicacion_local_y_bandas.json` |
| `calibracion_condicional_hgb_fv3_20250831_s42.md` · `.json` | La elección de la calibración del candidato con el mismo criterio y solo con su validación: conformal de Mondrian por ruta × bloque horario, versionada en su carpeta. | RF-006, §9.4 | `scripts/calibrar_por_grupo.py --model-id hgb_fv3_20250831_s42 --escribir` |
| `horizontes.json` | Error a 30, 60 y 120 minutos. | RF-005, §2.2 | `scripts/evaluar_horizontes.py` |
| `pytest_datos_recientes_y_activacion.txt` | Pruebas del modelo con los datos validados recientes en la inferencia (el Parquet empaquetado más `demanda_observada`), la activación gobernada y la prueba reservada como reporte informativo: integración y unitarias, 0 fallos. | RF-013, RF-018, RF-019, §9.3, §9.5 | pytest (comandos en el archivo) |
| `predecir_horas_lote.json` | El pronóstico en lote de todas las horas de un día (`predecir_horas`, el que usa el ciclo) da lo mismo que pronosticar hora por hora y es unas 15 veces más rápido por ruta. | RNF-004, §9.2 | `scripts/evaluar_lote_inferencia.py` |
| `explicacion_local_y_bandas.json` | La explicación SHAP reconstruye el pronóstico de las 3.111 horas de la prueba reservada (base × factores = pronóstico); latencia de SHAP y de `predecir()` y un ejemplo. | RF-006, RF-015, §9.4 | Medición del equipo descrita en `modelo/decision_fv2.md` («Explicación local»); la exactitud la verifica `tests/unit/test_inferencia.py` |
| `contexto_operacional.json` | Novedades viales, festivos y vísperas usados como contexto del pronóstico. | RF-003 | `scripts/preparar_datos_api.py --solo-contexto` |
| `docker_py311_shap.json` | La imagen `python:3.11-slim` construye y predice con SHAP. | §7.1 «Python 3.11 o superior», RNF-008 | Construcción de prueba de la imagen |
| `pytest_modelo.txt` | Corrida de las pruebas del modelo y de la suite. | RNF-014 | pytest |
| `segmentos_protocolo.md` | Partición, candidatos y regla de elección del modelo por segmento y sentido, fijados antes de mirar la prueba; al reportar se agregó una nota marcada como posterior a la prueba, y el 18-11-2026 otra al inicio, que lleva a la validación con tres años del pronóstico de corto plazo. | §9.3 | Documento del equipo, versionado en el commit `5306de7`, antes de la prueba (la nota posterior, en `7682dbe`) |
| `corto_plazo_reproduccion.md` · `.json` | La API sirve el mismo modelo de corto plazo que se midió en la prueba reservada de E14: con su código de variables y sus 18 árboles reproduce las 56.070 predicciones por ruta y las 112.140 por sentido (pronóstico, P10, P90, lo real y el promedio; diferencia máxima 0,0054 subidas), los totales por segmento y el WAPE de los nueve niveles y horizontes; el camino de un día da lo mismo que el periodo entero. | §9.2 («el preprocesamiento del entrenamiento se reproduce exactamente»), §9.3, RNF-011 | `python scripts/verificar_corto_plazo.py` (también deja `datos/corto_plazo/muestra_prueba_e14.csv`, que recalcula `tests/datos_ml/test_corto_plazo_modelo.py`) |
| `segmentos_modelo.md` · `.json` | Modelo por segmento y sentido: validación, prueba única, banda P10–P90 con cobertura medida y sesgo por sentido, segmento y condición, frente al reparto fijo B0. | §3.1, §9.1, §9.3 | `scripts/entrenar_segmentos.py` |
| `segmentos_banda_ventanas.json` | Cobertura de la banda del modelo por segmento en ventanas de 1, 2 y 3 horas de la prueba y el IC95 de la mejora frente a B0 (análisis posterior a la prueba, que no cambia la elección). | §3.1, §9.3 | `scripts/evaluar_banda_ventanas_segmentos.py` |

La corrida de la suite completa de las 05:32 que estaba aquí (`pytest_suite_modelo.txt`, 904 pruebas y 0 fallas) se
movió a `historial/modelo_suite_9nov_0532.txt`; la suite vigente es la de la tabla «Cifras vigentes».

## `monitoreo/` · monitoreo, aprendizaje continuo, ONNX y segmentos

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `monitoreo_2025.json` | Monitoreo semanal de sep.–dic. 2025: WAPE móvil, cobertura, PSI por variable y estado. | §9.4, §18 «Deriva» | `scripts/evidencias_monitoreo.py` |
| `psi_dia_lag7.json` | Por qué `dia_lag7` tiene un umbral de deriva calibrado con su propio ruido. | §9.4 | ídem |
| `compuerta_ejemplo.json` | Un candidato en sombra pasa por la compuerta de 4 criterios; se activa y se revierte solo si se degrada. | RF-018, RF-019, §9.5, §14.2 «Activación» | ídem |
| `onnx_paridad.json` | El modelo exportado a ONNX da los mismos pronósticos que scikit-learn y es más rápido. | §9.1, §9.2 | `scripts/exportar_onnx.py` |
| `onnx_paridad_hgb_fv3_20250831_s42.json` | Lo mismo para el candidato fv3, con la regla de paridad de `numpy.isclose` (en cada fila, diferencia ≤ 0,01 pasajeros + 0,001 × valor; `modelo/decision_fv3.md`). | §9.1, §9.2 | `scripts/exportar_onnx.py --model-id hgb_fv3_20250831_s42 --evidencia docs/evidencias/monitoreo/onnx_paridad_hgb_fv3_20250831_s42.json` |
| `desagregacion_segmentos.json` | Error del reparto fijo B0 (la línea base del modelo por segmento): enero aplicado a febrero de 2023. | §9.1, §9.3 «Analizar el sesgo por … segmento» | `scripts/preparar_segmentos.py` y `scripts/evidencias_monitoreo.py` |
| `foto_segmentos.json` | Filas y bytes por ejecución de la foto por segmento y sentido (1.158 filas por segmento y 12 de la ruta en una ejecución de 9 predicciones). | §7.3 paso 4, §11.2 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_monitoreo_api.py::test_ciclo_guarda_variables_por_segmento_y_sentido` |
| `foto_segmentos_demo.txt` | La demostración de §14.2 y la ejecución programada real guardan las variables por segmento y sentido. | §7.3 paso 4, §14.2 | `scripts/demo_ciclo.py` y `PRUEBA_PLANIFICADOR=1 pytest tests/integracion/test_planificador_programado.py` (montaje en el archivo) |
| `foto_segmentos_revision.txt` | La foto por segmento bajo la prueba de caída de RNF-001 y en la ejecución programada, sin filas repetidas, y la paginación de la foto de una ejecución sin repetir ni saltar filas. | §7.3 paso 4, RNF-001 | `scripts/prueba_caida.py`, `PRUEBA_PLANIFICADOR=1` y consultas de solo lectura (descritas en el archivo) |

La corrida de la suite completa de las 05:32 que estaba aquí (`pytest_suite.txt` y `.xml`, la misma que
`historial/modelo_suite_9nov_0532.txt`) se movió a `historial/monitoreo_suite_9nov_0532.txt` y `.xml`. La corrida de las 05:33 que estaba en `alertas/` está en
`historial/alertas_suite_9nov_0533.txt`.

## `ocupacion/` · ocupación por segmento, histórica y actual (§10.1)

El método, las decisiones y los límites están en `../ocupacion_segmentos.md`; el índice de la carpeta, en
`ocupacion/README.md`. `preparar_ocupacion_segmentos.py` y `backtest_ocupacion_reactiva.py` leen las exportaciones de la carpeta
`datos/` de la raíz (git-ignorada) y no consultan la base del reto; `medir_ciclo_intradia.py` lee la réplica local en
solo lectura y `evidencia_planificador_intradia.py` usa una base local desechable.

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `perfil_ocupacion_segmentos.md` · `.json` | El perfil histórico por segmento, día de operación y hora (ene.–feb. 2023, 26.350 viajes) que la API empaqueta en `datos/ocupacion_segmentos_hora.parquet`. La validación del método: la carga derivada de las subidas y bajadas por segmento frente a la ocupación máxima del dispositivo en los mismos viajes (correlación 0,961 en 21.511 viajes) y la Σ de subidas y bajadas igual a la del dispositivo. La comparación con el factor de carga 2025 y su cobertura por día de la semana. | §10.1 «ocupación histórica por segmento», H9 | `python scripts/preparar_ocupacion_segmentos.py --origen ../../datos` |
| `planificador_intradia.txt` · `.json` | El ciclo intradía en la operación programada, con el planificador y la cola reales, en un día comprimido con la franja del cron por omisión: una sola fila por franja, cada ciclo lee solo la hora que llegó, y la restricción reactiva actúa en el plan del día en curso y en las recomendaciones de 30 y 60 min. Trae la duración de cada ciclo y la latencia de una consulta paginada con un ciclo en curso. La captura en vivo es de prueba. | §10.1 10.1-d, RNF-002, RNF-005 | `PRUEBA_PLANIFICADOR=1 GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_planificador_programado.py` (corre `scripts/evidencia_planificador_intradia.py`) |
| `ciclo_intradia_fuente.md` · `.json` | La carga en la base de Extreme de un ciclo intradía frente al diario, medida en la réplica como `lector_ia`, con la proyección al histórico completo sin los índices de H12 (13-11-2026). | §10.1, §9.5 «lectura sin interferir», H12 | `python scripts/medir_ciclo_intradia.py --repeticiones 5` |
| `backtest_restriccion_reactiva.md` · `.json` | El efecto de la restricción reactiva con datos reales: 147 disparos, la hora siguiente sobre el umbral en el 28,6 % (tasa base: 5,9 %) y, frente a la operación (contrafactual), 457 salidas más, 292 de ellas donde no hacía falta; frente al plan del día, 69 días-ruta sin errores. Es una cota superior: la sección «En tiempo real» repite la medición con los viajes todavía en curso (25 disparos a las (h+1):05 y 35 a las (h+1):30). | §10.1 «ocupación actual por segmento», §5.2 ALT-002 | `python scripts/backtest_ocupacion_reactiva.py --origen ../../datos --plan` |
| `README.md` | Índice de esta carpeta. | — | Documento del equipo |

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
| `pytest_optimizacion.txt` | Pruebas del optimizador con el código final (13-11-2026): 142 casos, 142 aprobados: 94 unitarias del área, 12 de `test_recomendaciones.py`, 30 de los módulos vecinos que consumen el plan y 6 de compatibilidad del contrato. | RNF-014 | `scripts/evidencia_pytest.py` (comando en el archivo) |
| `LEEME.md` | Índice de esta carpeta, con cómo se regenera cada archivo. | — | Documento del equipo |

## `pruebas/` · niveles de §14.1 e integración continua

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `README.md` | Índice de esta carpeta: cómo corre la integración continua (GitHub Actions y el ensayo local con `scripts/ci_local.py`), qué se omite en una máquina limpia y por qué, y qué muestra cada archivo. | §14.2 «Calidad del código», RNF-014 | Documento del equipo |
| `ci_local.txt` · `ci` (carpeta: `ci/pytest.xml`, `ci/coverage.xml`, `ci/pasos.json` y `ci/caida.txt`) | Los mismos pasos del CI ejecutados en local: ruff, bandit, Alembic de ida y vuelta, pytest con cobertura y Testcontainers, y el resultado de cada paso. En la copia limpia de `ci_limpio.txt` (14-11-2026, código final), `ci/pytest.xml` registra 1.773 casos, 1.566 aprobados, 0 fallas, 0 errores y 207 omitidos, y `ci/coverage.xml`, 95,15 % de `app/`; `ci/caida.txt`, la prueba de caída y las dos de ejecución programada (3 de 3). | §14.2 «Calidad del código», RNF-007, RNF-014 | `scripts/ci_local.py todo` |
| `hallazgos_contrato.txt` | Defectos que encontraron las pruebas de contrato (Schemathesis), con la petición exacta que los reproduce. | §14.1 «Contrato» | `tests/contrato/` |
| `k6_consultas.txt` · `.json` | Carga con k6 sobre las consultas paginadas: p95 de 451,3 ms y 0 % de errores, con el p95 de cada recurso. | RNF-002, §14.1 «Carga» | `k6/consultas.js` |
| `k6_ingesta.txt` · `.json` | Consultas mientras corre una ingesta como job. | RNF-002, RNF-004 | `k6/consultas_durante_ingesta.js` |
| `ci_dependencias_y_acciones.txt` | Las dependencias fijadas instalan con ruedas binarias en `python:3.11-slim` y las versiones de las acciones del CI existen. | §7.1, E03 | Ensayo del paso de dependencias del CI |
| `ci_limpio.txt` | La integración continua en una copia limpia, como la ve GitHub Actions o un jurado al clonar: solo lo que git versiona, fin de línea de Linux, sin `.env` ni los datos de la raíz, y el resultado de cada paso del flujo. | §14.2 «las pruebas automatizadas pasan en integración continua», RNF-007, RNF-014 | `ensayo_copia_limpia.py` |
| `ensayo_copia_limpia.py` | El script de `ci_limpio.txt`: arma la copia limpia y corre en ella `scripts/ci_local.py` (y, con `--caida`, la prueba de caída). | — | — |
| `k6_volumen.txt` · `.json` | Medición anterior (9-11-2026); la vigente es `k6_segmentos.txt`. Carga con k6 sobre el volumen acordado: un año de resultados del ciclo diario sembrado con filas reales (`scripts/sembrar_volumen.py`). Con 50 usuarios, p95 de 627,5 ms y 0 % de errores. Su medición en frío de `GET /segmentos/estadisticas` (8,8 s; con `idruta`, 2,3 a 2,9 s) es anterior a la agregación materializada; la vigente está en `k6_segmentos.txt`. | RNF-002, §14.1 «Carga» | `k6/` contra una base local aparte (comandos en el archivo) |
| `k6_en_frio.json` | Resumen de k6 de la prueba en frío: la API recién arrancada, la primera petición a cada ruta sin calentamiento y una segunda pasada inmediata. | RNF-002 | `k6/en_frio.js` (descrito en `k6_volumen.txt`, sección 4) |
| `k6_segmentos.txt` · `k6_segmentos_*.json` | Capa de segmentos y carga con el volumen acordado contra una API propia en modo integrado: refresco completo como trabajo de la cola, peticiones en frío y en caliente, 50 usuarios durante un refresco completo, consultas paginadas y consultas durante una ingesta desde la réplica. Todos los umbrales de k6 cumplen. | RNF-002, RNF-004, §7.1, §14.1 «Carga» | `python docs/evidencias/pruebas/plantilla_volumen.py <base>` (arma la base plantilla con 33 ejecuciones reales del ciclo final), `scripts/sembrar_volumen.py --ejecuciones 1056` y `python scripts/medir_segmentos.py --base-datos <base sembrada> --puerto <libre>` (13-11-2026) |
| `revision_segmentos/` | Medición anterior (10-11-2026); la vigente es `k6_segmentos.txt`. Los pasos 1 a 3 repetidos sobre el código revisado de entonces: refresco en 23,2 s; p95 de 189,9 ms en frío y 56,3 ms en caliente; con 50 usuarios durante un refresco, 1.163,1 ms. | RNF-002, §7.1 | `python scripts/medir_segmentos.py` con `--pasos refresco en_frio segmentos` y `--salida` |
| `segmentos_equivalencia.json` | Agregación materializada frente a agregación directa en la réplica: 8 combinaciones de filtros, orden y paginación con los mismos ítems y el mismo total. | §6.1, RNF-002 | `GENERAR_EVIDENCIAS=1 pytest tests/replica/test_segmentos.py` |
| `segmentos_sin_cambios.json` | El refresco incremental de la agregación de segmentos sin filas nuevas, en la réplica como `lector_ia`: sin huellas comparables relee 26 fechas (164.206 filas) en 10,5 s; con las huellas de la ventana de solape (migración 0012), 0 fechas y 0 filas en 0,5 s, sin escribir nada. Tras el refresco parcial, `segmento_estadistica` tiene 0 filas distintas de rehacerla entera, y coincide con la agregación directa (filtro `idruta` = 2). | §6.1, RNF-004 | `GENERAR_EVIDENCIAS=1 pytest tests/replica/test_segmentos.py::test_refresco_sin_cambios_no_relee_la_ventana_de_solape_y_mide_la_diferencia` |

## `rendimiento/` · duración del ciclo diario

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `ciclo_antes_despues.md` · `.json` | Duración del ciclo diario (`POST /api/v1/frequency/executions`) con los mismos cortes de la demostración de §14.2 (carga inicial de 49.623 filas, día nuevo de 51 filas y repetición sin filas nuevas), antes y después de quitar el recorrido cuadrático de `contexto_observado` y la optimización repetida por horizonte, sin cambiar los resultados; cada corrida con una base local nueva y una copia temporal de `datos/`. | RNF-004, §14.2 «Demostración» | `scripts/medir_ciclo.py` |
| `perfil_ciclo_antes.txt` · `perfil_ciclo_despues.txt` | Las 25 funciones con más tiempo según cProfile en cada versión (de dónde se iba el tiempo). | RNF-004 | ídem, con el perfilador |
| `ciclo_dimensiones_plan.md` | La lectura de esa medición: qué agrega cada ejecución desde esta versión y cuánto tarda cada etapa. | RNF-004, §7.1, §8.3 | `scripts/medir_ciclo.py` |
| `ciclo_dimensiones_plan.json` | La misma medición del ciclo diario con lo que se agregó después: las dimensiones de §8.3 en cada fila y, al cierre, el plan del día siguiente y la foto de la respuesta del reto; con los conteos y el SHA-256 del resultado. | RNF-004, §7.1, §8.3 | `scripts/medir_ciclo.py` |
| `ciclo_dimensiones_plan_cierre.json` | Las duraciones internas del cierre del ciclo (plan del día y foto de la respuesta), leídas de `execution_log.metricas` en esa misma corrida. | RNF-004 | ídem |
| `ciclo_final.md` · `.json` | **La medición vigente del ciclo diario** (13-11-2026, 22:24, código final), con los mismos cortes: la foto de la respuesta reutiliza el plan del día, la serie de la ruptura de comportamiento (RF-009) corre en cada ciclo y los umbrales nuevos quedan versionados (migración 0007). Con las alertas observadas de cada día del lote, la foto por segmento y el plan con más detalle: carga inicial de 49.623 filas en 27,5 s, día nuevo de 51 filas en 20,7 s y repetición en 0,2 s; el resultado tiene el mismo SHA-256 que el 11-11-2026. Para reproducirlo hace falta `CATALOGOS_DATOS_DIR`, como dice el archivo. | RNF-004, RF-009, §7.1, §14.2 «Demostración» | `scripts/medir_ciclo.py --etiqueta final_plan_reutilizado --salida docs/evidencias/rendimiento/ciclo_final.json` |

## `replica/` · integración con la base operacional (E07)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `replica_init.log` · `replica_objetos.txt` | La réplica (PostgreSQL 14 + PostGIS) se inicializa con los 8 scripts de Extreme sin modificar (`SHA256SUMS`); quedan sus funciones y su trigger activo. | RF-002, §6.1, §11.1 | `docker compose -p sobusa_rep --profile integracion up -d operacional` |
| `replica_errata.txt` | Cada corrección mínima (E1, E2, H1) con la prueba del fallo sin ella. | RF-002, §19 | `scripts/replica_evidencias.py` |
| `replica_carga.txt` · `.json` · `replica_carga_historial.txt` | Carga de 3,38 millones de filas desde las exportaciones: conteos iguales, llaves foráneas sin huérfanos, tiempo y memoria. | RNF-003, §8.2 | `scripts/replica_cargar.py` |
| `replica_roles.txt` | `lector_ia` no puede escribir nada (32 intentos rechazados) y `escritor_ia` solo escribe en `ai_frecuencias`. | §8.3, §11.3, §18 | `scripts/replica_evidencias.py` |
| `replica_llegada.txt` · `.json` | Llegan datos por el trigger de Extreme y la lectura incremental entrega exactamente lo nuevo, y después nada; equivalencia trigger ↔ exportación. | RF-013, §9.5, §11.2, §14.2 «Ejecución incremental» | `scripts/replica_simular_llegada.py --viajes 3 --liquidar --consolidar --ciclo-api` |
| `explain_incremental.txt` · `.json` | `EXPLAIN (ANALYZE, BUFFERS)` de las consultas incrementales como `lector_ia`, antes y después de la propuesta vigente (7 índices), aplicada como `extreme_dba` y borrada al terminar (13-11-2026; el informe nombra cada índice y las condiciones de la medición). | §8.3, §14.1 «Rendimiento», §18 «Consulta pesada» | `scripts/replica_explain.py` |
| `explain_misma_carga.txt` | Histórico (medición manual del 9-11-2026, con la lectura de entonces). La lectura incremental `demanda_segmentos` con la definición de pasajeros del modelo, la unión con `"Procesos"` y la estacionalidad vigente cuesta lo mismo que la consulta anterior (diferencia dentro del ruido), medidas en el mismo proceso y con la misma carga. | §8.3, §11.2, §14.1 «Rendimiento» | Medición descrita en el archivo |
| `propuesta_indices.sql` | Los siete índices `CREATE INDEX CONCURRENTLY` propuestos al DBA de Extreme, decididos con `indices_candidatos.md` y `lectura_por_proceso.md`; ninguno cambia tablas, triggers ni funciones. | §8.3 | `scripts/replica_indices_candidatos.py` (`propuesta_sql`; `scripts/replica_explain.py` la aplica) |
| `indices_candidatos.md` · `.json` | Cada índice candidato medido con las consultas reales de la API, sin él y con él, dentro de una transacción que se revierte, con el criterio y la decisión; y la propuesta entera con ANALYZE: ninguna lectura de la API empeora. Al terminar no queda ningún `ix_ia_*` (13-11-2026). | §8.3, §11.3, §14.1 «Rendimiento» | `python -m scripts.replica_indices_candidatos` (como `extreme_dba`) |
| `replica_contexto.json` | El contexto del modelo, reconstruido desde la base, es idéntico al de los archivos. | RF-003 | `scripts/replica_contexto.py` |
| `novedades_por_ruta_replica.json` | En la réplica, leída con `lector_ia`, `novedades_viales_ruta` está vacía: las 28 novedades son de todas las rutas, no hay novedades por ruta y el contexto es idéntico al empaquetado (24.837 filas). | §11.2, RF-003 | `GENERAR_EVIDENCIAS=1 pytest tests/replica/test_integrado.py::test_novedades_viales_ruta_vacia_en_la_replica_cada_novedad_es_de_todas_las_rutas` |
| `pytest_replica.txt` | Pruebas contra la réplica (roles, carga, scripts, llegada, EXPLAIN y segmentos), también las que escriben en ella: 209 aprobadas, 0 fallidas, 0 omitidas (14-11-2026, código final; lo escribe `scripts/evidencia_pytest.py`). La corrida de la suite completa que acompañaba la versión anterior de este archivo está en `historial/` (describía 2 fallas y 4 xfail ya corregidos). | §14.1 «Integración», RF-002 | `pytest tests/replica` con `REPLICA_PRUEBAS_ESCRITURA=1` (comando en el archivo) |

## `respuesta/` · la pregunta final del reto (§20)

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `respuesta_reto.md` | Por día, ruta y franja: cada cuánto despachar frente a lo programado, pasajeros esperados con P10–P90 frente a los observados, vehículos frente a la flota, costo, espera, sobreocupación y recaudo. | §20, §1 | `scripts/respuesta_reto.py` (el mismo servicio de `GET /api/v1/respuesta`) |
| `respuesta_<fecha>.json` | La respuesta completa de `GET /api/v1/respuesta` para cada día de ejemplo, con su trazabilidad: un laboral, un sábado y un domingo de noviembre de 2025 (19, 22 y 23) y el 1-ene-2026, el día siguiente al último dato (festivo de Año Nuevo, pronóstico del modelo activo). | §20, RNF-011 | ídem |
| `api_en_vivo.txt` · `api_respuesta_CRA54_2025-11-19.json` | La misma respuesta por HTTP, con la autenticación encendida: 401 sin clave, 403 si un operador pide el cálculo, 404 `sin_calcular` cuando no hay foto, el cálculo en la cola con `POST /api/v1/respuesta/calcular` (202), 200 con clave de operador, latencia, exportación y alertas abiertas reales. | §20, §12.1, §7.1 | Servidor de prueba contra una base local con el ciclo diario ya corrido (protocolo en el archivo) |
| `pytest_respuesta.txt` | Pruebas unitarias y de integración de la respuesta: 37 casos, 37 aprobados (13-11-2026). | §20, RNF-014 | `scripts/evidencia_pytest.py` con `tests/unit/test_respuesta.py tests/integracion/test_respuesta_api.py` |
| `LEEME.md` | Índice de esta carpeta. | — | Documento del equipo |

## `retencion/` · retención de datos (§18)

La política, la tarea y su operación están en `../retencion_datos.md`. Los cuatro archivos salen de cuatro pruebas de
`tests/integracion/test_retencion.py`; los dos primeros, con la misma siembra: filas y particiones a ambos lados del corte y tablas
centinela con los mismos nombres en otro esquema.

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `archivo_repetido.json` | El mismo mes archivado dos veces: el archivo nuevo toma el primer nombre libre y no choca con el anterior. | §18 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_retencion.py::test_el_mismo_mes_archivado_dos_veces_no_choca_con_su_archivo` |
| `foto_de_prediccion_conservada.json` | Una partición vieja con fotos de predicciones que la regla de resultados conserva se conserva entera. | §18 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_retencion.py::test_la_foto_de_una_prediccion_que_se_conserva_conserva_su_particion` |
| `corrida_simulada.json` | La corrida simulada: los cortes de cada grupo, la política vigente, cada acción que haría (la partición vieja de `feature_snapshot` que separaría y borraría, la que conserva porque tiene filas recientes, las filas de cada tabla) y sus totales, sin borrar nada. | §18 «Exposición de datos → retención» | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_retencion.py::test_simulacion_no_borra_nada_y_deja_en_la_bitacora_lo_que_borraria` |
| `corrida_aplicada.json` | La misma política aplicada, con el destino de cada fila sembrada (borrada o conservada): borra solo lo anterior al corte y solo en `ai_frecuencias`, nunca lo que todavía sostiene algo que se conserva; las tablas centinela del otro esquema quedan intactas. | §18, §11.3 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_retencion.py::test_aplicada_borra_solo_lo_anterior_al_corte_y_solo_en_ai_frecuencias` |

## `seguridad/` · autenticación, resiliencia y observabilidad

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `matriz_roles.txt` | Cada ruta con 5 identidades (sin clave, clave inválida, operador, analista y admin): 401, 403 o permitido, según la matriz. La corrida guardada (11-11-2026) tiene las 67 operaciones de `/api/v1`, cada una con las 5 identidades. | §7.2, §12.1 | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_seguridad.py` |
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
| `pytest.xml` · `pytest.log` · `coverage.xml` | La corrida de pruebas con cobertura que se le entrega a SonarQube en ese análisis; es la suite final de la tabla «Cifras vigentes» (18-11-2026: 1.810 casos, 0 fallas, 0 errores y 10 omitidos; cobertura de `app/` de 95,76 %). `pytest.xml` y `coverage.xml` son idénticos byte a byte a `pruebas/suite_final.xml` y `pruebas/coverage_final.xml`. | RNF-014, RNF-013 | ídem |
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
| `verificar_estilo_estatico_corto_plazo.txt` | La verificación estática del sistema de diseño con la sección nueva de Pronóstico (`dash_app/corto_plazo_vista.py`, revisada con las reglas de las páginas): pasa, con 0 fallas (18-11-2026). | RNF-012 | `dash_app/verificar_estilo.py` |
| `verificar_estilo_estatico_once.txt` · `verificar_estilo_vivo_once.txt` | La verificación del sistema de diseño con las once pantallas: pasa, con 0 fallas. | RNF-012 | `dash_app/verificar_estilo.py` |
| `despacho_carga_en_frio.txt` · `.py` | La consola Despacho en cinco cargas en frío (contexto nuevo, sin caché): 5 de 5 sin errores de consola y con los buses en el mapa. El mapa espera a que MapLibre cargue su estilo antes de recibir los buses; la corrida anterior al arreglo (2 errores «Style is not done loading») está en `historial/`. | RNF-012, E06 | `despacho_carga_en_frio.py` (el script está en la carpeta) |
| `e2e_corto_plazo.txt` · `.json` · `.py` | Pronóstico › «Lo que pide el enunciado» frente a la API, con Edge sin interfaz a 1600 y 400 px: las cifras del instante, la curva del día (35 instantes), el perfil por segmento (123 y 135), los dos sentidos y la primera variable de la explicación son los de `GET /api/v1/predictions/corto-plazo/calcular` y `/dia`, en CRA 54 y en SILENCIO; la prueba reservada es la de `dash_app/datos/corto_plazo.json`; 0 errores de consola y sin desborde: 21 de 21 comprobaciones bien (18-11-2026). Deja `dash_pronostico.png`, `dash_pronostico_completa.png` y `dash_pronostico_corto_plazo.png`. | §2.2, RF-005, §3.1 M3, E06, RNF-012 | `python e2e_corto_plazo.py PUERTO_TABLERO PUERTO_API CARPETA` (API de desarrollo sin autenticación) |
| `export_predicciones_dash.csv` · `.xlsx` | Los pronósticos del modelo activo exportados desde la sección del modelo horario de Pronóstico (`GET /api/v1/predictions/export`), con el esquema vigente (`model_id`, `feature_version`, `data_cutoff`, banda y explicación). | RF-017, §9.2 | Recorrido del tablero contra la API |
| `funciones_tablero.txt` · `.py` | Las funciones nuevas del tablero, sin servidor: el orden de prioridad y el aviso «Escalada» de Alertas, los nombres de los experimentos del informe en El modelo y la lectura de lo real por ventana en Pronóstico (9 de 9 bien). | E06, §7.2, RNF-012 | `funciones_tablero.py` (el script está en la carpeta) |
| `verificar_ahorro_once.txt` | Las cifras de ahorro del tablero coinciden con sus archivos de origen: 407 comprobaciones bien, 0 fallas. | E06 | `dash_app/verificar_ahorro.py` |

## `video/` · cómo se grabó el video de E11

El video está en `../../../documentos/video/E11_video_demostracion.mp4` (menos de 5 minutos), con sus subtítulos
(`.srt`) y su guion (`guion.md`: escena, segundos, narración, pantalla y evidencia de cada cifra).

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `registro.txt` | Cómo se grabó: herramientas y versiones, entorno aislado (API y tablero del código entregado, base de pruebas propia, copia temporal de `datos/`, claves de prueba que no aparecen en pantalla), la ejecución en vivo y la tabla de escenas con sus tiempos y 0 errores de consola. | E11, §16 «Presentación y adopción» | Grabación automática con el navegador y narración sintetizada (detalle en el archivo) |
| `verificacion_video.json` | La verificación del archivo final: duración, resolución, audio, número de cuadros y los cuadros revisados por escena. | E11 | `ffmpeg` sobre el MP4 final |
| `plan_mezcla.json` | El montaje: de qué toma y de qué tramo sale cada escena, y su duración frente a la de la narración. | E11 | Script de montaje del video |
| `cuadros` (carpeta) | Un cuadro por escena (14 PNG), para revisar el contenido sin reproducir el video. | E11 | Extraídos del MP4 final |

## Fuera de esta carpeta · el pronóstico de corto plazo que pide el enunciado

Está en `../../../pronostico_corto_plazo/`, y las rutas de esta tabla son relativas a esa carpeta. Es el pronóstico de
las subidas de los siguientes 30, 60 y 120 minutos por ruta, sentido y segmento, elegido con ene.–jun. de 2025 y
probado una sola vez con jul.–dic. de 2025 (retroalimentación del curso del 17-11-2026). Desde el 18-11-2026 la API lo
sirve (`POST /api/v1/predictions/corto-plazo`) con los mismos árboles y reproduce estas predicciones
(`modelo/corto_plazo_reproduccion.md`). Sus cifras están en su `README.md`; los comandos se corren desde esa carpeta.

| Archivo | Qué demuestra | Requisito | Cómo se generó |
|---|---|---|---|
| `PROTOCOLO.md` | El problema, la partición, las líneas base, las reglas de elección y lo que se reporta, escrito y confirmado en git antes de correr la validación. | §9.3 (partición y prueba reservada) | Documento del equipo; el orden lo prueba el historial de git |
| `panel/verificacion_extreme.json` | Las subidas por segmento de 2023 a 2025, asignadas con la regla de Extreme, coinciden con `timbradas_segmentos` en los 58 días que la base trae. | §3.1, §9.1 (segmento) | `python preparar_panel.py` (necesita las exportaciones de la base, de solo lectura) |
| `panel/revision_sentido.json` | Cuánto confunde el sentido la regla del segmento más cercano. | §9.1, §9.3 (sentido) | `python revisar_sentido.py` |
| `resultados/comprobacion_fuga.json` | Al cambiar todo lo posterior a un instante, ninguna variable ni línea base anterior cambia. | §9.3 (sin información posterior) | `python comprobar_fuga.py` |
| `resultados/validacion.json` · `resultados/seleccion.json` | Las líneas base y las variantes del modelo en la validación, y lo que se eligió con ella. | §9.1, §9.3 | `python validar.py` |
| `resultados/prueba.json` | La prueba reservada: MAE, RMSE, WAPE, sMAPE y sesgo por nivel, horizonte, ruta, franja, sentido, mes y tipo de día; IC95 frente a las líneas base; cobertura de la banda P10–P90, y los análisis secundarios. | §2.2, §3.1, RF-005, §9.1, §9.3 | `python probar.py` (una sola vez) |
| `resultados/segmentos_prueba.csv` · `resultados/predicciones_ruta.parquet` · `resultados/predicciones_sentido.parquet` | El detalle por segmento (subidas reales y pronosticadas, sesgo y WAPE) y las predicciones por ruta y por sentido con su banda. | §9.3 (sesgo por ruta, sentido y segmento) | `python probar.py` |
| `resultados/sensibilidad_registro_anomalo.json` | Análisis posterior a la prueba, fuera del protocolo: las métricas por ruta y por sentido sin los nueve días que toca un registro imposible de la base (28.782 subidas en un segmento en 15 minutos). Las cifras de la prueba no cambian. | §9.3 (métricas), §3.1 (calidad del dato) | `python sensibilidad_registro_anomalo.py` |
| `resultados/desglose_domingos_festivos.json` | Análisis posterior a la prueba, fuera del protocolo: el error por ruta con domingos y festivos por separado. En los festivos el modelo gana por mucho; en los domingos corrientes no mejora al promedio por día y hora. | §9.3 (métricas por condición) | `python desglose_domingos_festivos.py` |
| `figuras/` | Las figuras del README de esa carpeta y del informe técnico. | — | `python figuras.py` |

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
