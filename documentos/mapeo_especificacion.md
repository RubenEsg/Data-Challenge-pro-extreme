# Mapeo de la especificación v1.5 a la evidencia (§1–§3, §17–§20)

**Data Challenge Pro Extreme – Sobusa 2026** · Universidad del Norte · Abrahan Basto Martínez, Rubén Esguerra
Fernández y Paula Gómez

Este documento toma, frase por frase, las secciones de la especificación de Extreme Technologies que no son una tabla
de requisitos con identificador: §1 Introducción, §2 Objetivos, §3 Alcance funcional, §17 Organización del trabajo,
§18 Riesgos, §19 Información que debe suministrar Extreme y §20 Resultado final esperado. Para cada una dice qué
hicimos y dónde puede comprobarlo el jurado: un archivo, un comando o una prueba automática. Los requisitos con
identificador (RF, RNF, E01–E12 y los apartados técnicos §4–§15) están en `MATRIZ_CUMPLIMIENTO.md`.

Convenciones:

- Las rutas son relativas a la carpeta de la entrega (`EntregaFinal/`, la raíz del repositorio de entrega).
- `api/` abrevia `api_frecuencias/` y `ev/` abrevia `api_frecuencias/docs/evidencias/`.
- Una prueba se cita como `archivo::función`. Todas corren con pytest desde `api_frecuencias/`
  (`docs/manual_tecnico.md`, sección 13).
- Ninguna cifra de este documento está escrita a mano: cada una viene del archivo que se cita al lado.

## 0. Cómo entendemos el problema (criterio «Comprensión del problema»)

**Formulación.** Cada semana Sobusa arma el horario de despacho de sus rutas. Según lo que vimos en la visita a la
empresa, hoy lo hace a mano, con promedios y la experiencia de los despachadores. Lo formalizamos como la regla manual
B1: el promedio de las ocho semanas anteriores para la misma ruta, hora y día. Es el supuesto S0 de la tabla de abajo,
porque no tenemos un criterio oficial escrito. El problema que resolvemos tiene tres partes:

1. Pronosticar los pasajeros de cada ruta y franja horaria, con su incertidumbre (banda P10–P90).
2. Convertir ese pronóstico en un intervalo de despacho y un número de vehículos. La conversión minimiza costo de
   operación, espera y sobreocupación, respeta la capacidad, la flota, el ciclo y los límites de headway, y dice cuándo
   una franja no es viable. El plan del día usa el pronóstico horario del modelo activo de la API
   (`hgb_fv2_20250831_s42`), el mismo que sirve `GET /api/v1/predictions`. El pronóstico híbrido del experimento 12
   del informe, precalculado para 2025, queda solo como opción (`pronostico=E12` en `GET /api/v1/recommendations/plan`
   y `MODELO_PLAN=E12` para la respuesta del reto).
3. Avisar, con una explicación en lenguaje operativo, cuándo la realidad se aparta de lo esperado.

La decisión sigue siendo del despachador: el sistema recomienda y alerta (§3.2). La formulación matemática está en el
informe técnico (`Informe_tecnico_Sobusa.pdf`, sección 3 «Metodología»: «Formulación del problema y notación» y «Del
pronóstico a la decisión de despacho») y la función objetivo de §10.2, en `ev/optimizacion/sensibilidad.md`.

**Supuestos explícitos.** Cada uno dice dónde está guardado o documentado y quién debe validarlo. Los valores numéricos
viven en archivos o en `threshold_config` y se cambian sin tocar el código.

| # | Supuesto | Dónde está | Quién debe validarlo |
|---|---|---|---|
| S0 | La frecuencia actual sale de una regla manual: el promedio de las ocho semanas anteriores para la misma ruta, día y hora (B1). La fuente es la visita del equipo a Sobusa, donde nos dijeron que la cantidad de buses «se estima manualmente» con «promedios y la experiencia» de los encargados. Las notas de la visita están solo en el proyecto completo. El número de semanas es nuestra formalización, no un criterio escrito. | Informe técnico, sección 1; `api/app/servicios/inferencia.py` (línea base B1); `api/docs/hallazgos_extreme.md` (H15) | Sobusa y Extreme (§19, criterio oficial de la frecuencia actual) |
| S1 | La demanda de una franja es la suma de pasajeros de los viajes válidos por hora de salida. | `api/datos/origen.json`; `api/README.md`, sección «Datos y modelos» | Extreme (§19, criterio oficial de subidas) |
| S2 | La capacidad base es de 50 puestos por bus, y la flota se divide en cuatro tipologías por número de puestos, sin placas. | `api/datos/catalogo_rutas.json`, `api/app/servicios/tipologias_flota.json` | Extreme (§19, capacidad) |
| S3 | Umbrales iniciales: los valores sugeridos en §5.1 (ocupación objetivo 65–85 %, crítica ≥ 90 %, baja < 30 %, espera máxima 5 min, error de pronóstico 15 %, datos atrasados 2 períodos). La espera máxima se interpreta como dice S12. El headway mínimo (2 min) y el máximo (10 min) no vienen en §5.1 («definido por la operación»): son valores supuestos del equipo. | `ai_frecuencias.threshold_config`, versión 1 de `api/alembic/versions/0001_esquema_ai_frecuencias.py`; `GET /api/v1/thresholds` | Área operativa (§5.1) |
| S4 | Nivel de servicio 0,90: la capacidad cubre el P90 calibrado de la demanda. | `api/app/servicios/optimizacion.py`; `ev/optimizacion/LEEME.md` | Área operativa |
| S5 | Pesos de la función objetivo α = β = γ = δ = 1 sobre términos en COP por hora. Tres costos tienen fuente: el bus-hora de conductor (26.400 COP), el km evitable (1.991 COP) y la tarifa neta (3.182 COP). Los otros tres son supuestos del equipo: el valor del tiempo de espera (7.000 COP por hora de pasajero), la penalidad por sobreocupación (10.000 COP por pasajero por encima de la ocupación crítica) y el costo de cambiar la frecuencia (26.400 COP por bus por hora de diferencia, un bus-hora de conductor por reprogramación). | `PARAMETROS_OBJETIVO` en `api/app/servicios/optimizacion.py`; `api/datos/costos_fuente.json`; la derivación de los costos con fuente, en el informe técnico, sección 3 «Del pronóstico a la decisión de despacho»; `ev/optimizacion/pesos_versionados.json` | Los costos con fuente, el área financiera de Sobusa; los tres supuestos, el área operativa de Sobusa con Extreme |
| S6 | El ciclo, la flota y el intervalo programado salen de las medianas por ruta, tipo de día y hora de los datos. No siempre cuadran entre sí (H13 en `api/docs/hallazgos_extreme.md`). | `api/datos/parametros_operativos_hora.parquet`; `ev/optimizacion/LEEME.md` | Extreme (§19, parámetros operativos y límites de headway) |
| S7 | La base del reto termina el 31-12-2025, así que la llegada de datos nuevos se simula con los días de 2025. | `api/README.md`, sección «Limitaciones»; `ev/demo_ciclo.txt` | — |
| S8 | `timbradas_segmentos.pasajeros` no se usa como ocupación, porque es la diferencia de contadores acumulados. | `api/docs/hallazgos_extreme.md` (H9) | Extreme (H9) |
| S9 | El sentido de un segmento se aproxima con la mitad del ciclo, porque las exportaciones no lo traen. | `ev/monitoreo/desagregacion_segmentos.json` | Extreme |
| S10 | Elasticidad de la demanda a la oferta: β estimada ≈ 0,70 por observación (rango 0,55–0,90; informe técnico, sección 4 «La demanda responde a la oferta»), sin validar en campo. El plan del día usa 0,5 por prudencia. La sensibilidad está en `ev/optimizacion/sensibilidad.md`, y el piloto la mide. | `Informe_tecnico_Sobusa.pdf`, sección 4 «Piloto para medir β»; `ELASTICIDAD` en `api/app/servicios/motor_d5/comun.py`; `PLAN_EVOLUCION.md` | Piloto con Extreme |
| S11 | El recaudo esperado es pasajeros esperados × tarifa neta de 3.182 COP (tarifa pública 2026 × 0,86), porque Extreme no suministró la tarifa. | `ev/respuesta/respuesta_reto.md` | Extreme o Sobusa |
| S12 | La «espera máxima» de §5.1 («tiempo máximo objetivo entre despachos», 5 min) se lee como la espera media del pasajero. Con llegadas aleatorias, esa espera es la mitad del headway. Por eso el headway máximo efectivo es min(`headway_maximo_min`, 2 × `espera_max_min`) = min(10, 2 × 5) = 10 min, tanto en la recomendación por franja como en el plan del día. Si Extreme confirma la lectura literal (5 min entre despachos), basta con versionar `espera_max_min` = 2,5 o `headway_maximo_min` = 5: la recomendación cambia sin tocar el código. | `REGLA_ESPERA` en `api/app/servicios/optimizacion.py`; `threshold_config` (`espera_max_min`, `headway_maximo_min`); `api/docs/hallazgos_extreme.md` (H14). Prueba: `api/tests/unit/test_respuesta.py::test_espera_maxima_acota_el_headway_maximo_d1` | Extreme y el área operativa (§19, tiempo máximo de espera) |
| S13 | El horizonte h de un pronóstico (30, 60 o 120 min) es la ventana [t, t + h]: los pasajeros que salen entre el instante t y t + h, con origen en t y sin antelación adicional. «30 min» no significa «media hora antes». | `ev/modelo/horizontes.json` (protocolo); `api/app/servicios/inferencia.py` (`predecir`) | Extreme (§9.1) |

**Las tres definiciones de «vehículos».** La API cuenta los vehículos de tres maneras, y cada salida dice cuál usa:

| Definición | Fórmula | Dónde sale | Para qué sirve |
|---|---|---|---|
| Fórmula de §10.3 | `vehiculos_requeridos = ⌈ciclo / headway⌉` | `GET /api/v1/recommendations` y `POST /api/v1/recommendations/calculate` (campo `vehiculos_requeridos`, con la fórmula escrita en `explicacion`); en el plan del día, por hora | La flota simultánea de una franja con un headway constante, como la define la especificación |
| Por tipología de flota | Σ por tipología ⌈ciclo × buses por hora de esa tipología / 60⌉ (con dos o más tipologías puede dar uno más que la fórmula de §10.3: 51 frente a ⌈249,1 / 5⌉ = 50 en el ejemplo) | `POST /api/v1/recommendations/calculate` con tipologías (`ev/optimizacion/ejemplo_calculate.json`) | La flota cuando la franja mezcla buses de distinta capacidad |
| Buses en ruta a la vez | Máximo, en el día, de los buses en ruta cada 15 minutos con el plan y el ciclo de cada hora (conteo del optimizador D5) | `GET /api/v1/respuesta`, campo `vehiculos`: `requeridos_pico` frente a `flota_disponible`, `requeridos_programados` con el horario de hoy y, al lado, `requeridos_pico_10_3` con la fórmula de §10.3 | **Contesta la pregunta del reto** («¿cuántos vehículos se esperan?»): es la flota que de verdad tiene que estar en la calle en el momento más cargado del día |

La tercera puede diferir de la fórmula de §10.3, porque esa fórmula supone que la frecuencia de la hora se mantiene un
ciclo completo, y en el plan la frecuencia cambia de una hora a otra. `GET /api/v1/respuesta` entrega las dos cifras, y
las de cada día están en `ev/respuesta/respuesta_reto.md`.

**Contexto de §9.5.** La especificación lista los elementos del contexto. Este es el lugar de cada uno:

| Elemento de §9.5 | Dónde está | Nota |
|---|---|---|
| Ruta, día de la semana, franja (hora) y pasajeros | `ai_frecuencias.demanda_observada` (histórico validado: ruta, fecha, hora, pasajeros, salidas e `idruta`, `idempresa`, `idproceso`, `id_dia_semana` e `id_estacionalidad`); `api/datos/demanda_horaria.parquet` | La unidad del modelo es ruta × día × hora de salida (S1) |
| Variables exactas de cada pronóstico | `ai_frecuencias.feature_snapshot` (JSON de variables, `feature_version`, `data_cutoff`, con las mismas dimensiones), particionada por mes | Permite repetir cualquier predicción |
| Estacionalidad | `id_estacionalidad` en las tablas de resultados, nulo para Sobusa porque `estacionalidades_anio` es de otro proceso (H1); el calendario (festivos, Semana Santa, vacaciones, Navidad) en `api/datos/demanda_horaria.parquet` | Las variables de calendario sustituyen la estacionalidad que falta |
| Novedades viales | `api/datos/contexto_operacional.parquet` (`nov_impacto`, `nov_sube`, `festivo_oficial` por fecha y hora) | Leídas de `novedades` y sus rutas |
| Capacidad y vehículo | Capacidad base por ruta en `api/datos/catalogo_rutas.json`; ajustes versionados en `threshold_config` (`PUT /api/v1/catalogos/capacidad`); tipologías por número de puestos en `api/app/servicios/tipologias_flota.json` | Sin placas ni datos del vehículo (§18, exposición de datos) |
| Segmento y sentido | `api/datos/reparto_segmentos.parquet` (fracción de las subidas por segmento, tipo de día y hora, con su sentido aproximado) | Desagregación del pronóstico de la ruta, no un modelo propio (limitaciones, abajo) |
| Subidas, bajadas y viaje | En la fuente (consolidados y `timbradas_segmentos`); el histórico propio guarda solo la demanda horaria validada | §3.2: no duplicar los datos operativos. ALT-008 no evalúa las bajadas (limitaciones, abajo) |

**Alineación operacional.**

- Las salidas hablan el idioma del despacho: headway en minutos, buses por hora y vehículos frente a la flota.
- Cada recomendación se compara con la frecuencia programada de hoy.
- Las alertas siguen las acciones de §5.2 y se gestionan con los estados que usa un centro de control.
- Los horizontes de 30, 60 y 120 minutos sirven para reaccionar dentro del turno. El plan del día, con el modelo
  activo, y los experimentos a 7 días del informe sirven para armar el horario del día siguiente y el semanal.
- Manual del despachador: `api/docs/manual_usuario.md`.

## 1. Introducción (§1)

| Frase de la especificación | Qué hicimos | Evidencia | Prueba |
|---|---|---|---|
| La información operativa ya está en PostgreSQL, alimentada por tablas y triggers de la compañía. | Montamos una réplica local de la base operacional con los 8 scripts de Extreme copiados byte a byte. El trigger de segmentación queda activo y los datos llegan por él. | `ev/replica/replica_errata.txt` (los scripts se ejecutan sin cambios, verificados con `SHA256SUMS`), `ev/replica/replica_carga.txt`, `ev/replica/replica_objetos.txt`, `ev/replica/replica_llegada.txt`, `api/docs/integracion_postgresql.md` | `api/tests/replica/test_scripts_extreme.py::test_hash_scripts_identicos`, `api/tests/replica/test_scripts_extreme.py::test_objetos_extreme` |
| Tomar decisiones operativas anticipadas con un sistema inteligente, reproducible e integrable. | Pronóstico a 30, 60 y 120 minutos y plan de despacho del día; ejecución reproducible con Docker Compose; integración en modo solo lectura. | `ev/modelo/horizontes.json`, `api/docs/despliegue.md`, `api/docker-compose.integracion.yml` | `api/tests/replica/test_integrado.py::test_ciclo_integrado_lee_exactamente_lo_nuevo_y_luego_nada` |
| El alcance es solo la frecuencia de despacho de viajes por ruta. | La API solo pronostica, recomienda frecuencia y flota, y alerta. No hay ningún endpoint que despache. | `api/README.md` (tabla «Endpoints») | `api/tests/contrato/test_contrato_openapi.py` |
| No basta con un cuaderno: producto mínimo viable con servicios REST, ejecución automática, trazabilidad, visualización y alertas. | REST con FastAPI (OpenAPI 3); planificador diario y cola de trabajos; trazabilidad de versiones en cada salida; tablero Dash que consume la API; motor de alertas ALT-001 a ALT-010. | `api/docs/openapi.json`, `ev/cola/planificador.txt`, `ev/seguridad/traza_ejecucion.json`, `ev/tablero/e2e_tablero.txt`, `ev/alertas/README.md` | `api/tests/integracion/test_api_integracion.py`, `api/tests/integracion/test_monitoreo_api.py::test_ciclo_guarda_monitoreo_foto_y_columnas_nuevas` |
| La salida debe contestar cuál debe ser el intervalo de despacho por rango de horas. | `headway_min` por franja en cada recomendación y plan del día por hora. | `ev/optimizacion/ejemplo_plan_d5.json`, `ev/optimizacion/ejemplo_calculate.json` | `api/tests/integracion/test_recomendaciones.py` |
| …cuántos vehículos se requieren. | Tres cuentas, cada una con su nombre (sección 0, «Las tres definiciones de vehículos»): `vehiculos_requeridos = ⌈ciclo / headway⌉` por franja, la suma por tipología y los buses en ruta a la vez del plan del día, que contesta la pregunta del reto. Todas se comparan con la flota disponible; si no alcanza, `viable = false` con el motivo. | `ev/optimizacion/ejemplo_calculate_no_viable.json`, `ev/respuesta/respuesta_reto.md` | `api/tests/unit/test_optimizacion_objetivo.py::test_inviable_porque_la_flota_no_cubre_el_nivel_de_servicio`, `api/tests/unit/test_respuesta.py::test_vehiculos_frente_a_la_flota` |
| …cuántos pasajeros se esperan. | Pronóstico con banda P10–P90 calibrada. En la prueba reservada (nov.–dic. 2025; cifra informativa, ver sección 6), el modelo activo tiene un WAPE de 14,77 % (IC95 13,10–16,87), frente a 21,18 % de la regla manual B1; con el modelo congelado al 31-12-2024, en todo 2025, 14,48 % frente a 20,04 %. La banda usa la calibración v2 por bloque horario, versionada con el modelo: cobertura de 77,82 % (v1: 77,88 %) con un ancho medio de 303,4 pasajeros (v1: 312,9). | `ev/modelo/evaluacion_modelo.md`, `ev/modelo/calibracion_condicional.md` | `api/tests/datos_ml/test_no_regresion.py::test_supera_a_las_lineas_base_en_la_prueba_reservada` |
| …por qué se generó la recomendación. | Cada pronóstico trae su explicación local SHAP; cada recomendación, la fórmula, los límites que mandan y la versión de umbrales; cada alerta, el observado, el esperado, el umbral, la tendencia y las variables influyentes. | `ev/modelo/explicacion_local_y_bandas.json`, `ev/optimizacion/ejemplo_calculate.json`, `ev/alertas/alertas_observadas_ejemplo.json` | `api/tests/unit/test_inferencia.py`, `api/tests/unit/test_alertas_observadas.py` |

## 2. Objetivos (§2)

### 2.1 Objetivo general

| Objetivo | Qué hicimos | Evidencia | Prueba |
|---|---|---|---|
| Consumir las tablas existentes en PostgreSQL. | `FuentePostgresSoloLectura` lee los consolidados y `timbradas_segmentos` por marca de agua, con transacción `READ ONLY`, `statement_timeout`, zona America/Bogota, ventana de solape y huella de contenido. | `api/app/servicios/fuentes.py`, `api/docs/integracion_postgresql.md` §3–§4, `ev/replica/replica_llegada.txt` | `api/tests/replica/test_integrado.py::test_la_fuente_de_la_api_es_de_solo_lectura_en_tres_capas`, `api/tests/unit/test_fuentes.py` |
| Predecir la demanda por ruta y franja horaria. | Modelo de gradient boosting (pérdida Poisson) con cuantiles P10 y P90, banda calibrada, explicación SHAP, horizontes de 30, 60 y 120 minutos y artefacto ONNX equivalente. | `ev/modelo/evaluacion_modelo.md`, `ev/modelo/horizontes.json`, `ev/monitoreo/onnx_paridad.json` | `api/tests/datos_ml/test_no_regresion.py`, `api/tests/unit/test_onnx.py` |
| Recomendar frecuencias de despacho. | MILP de la franja con la función objetivo de §10.2 (PuLP/CBC), línea base de §10.3 al lado y plan del día. | `ev/optimizacion/sensibilidad.md`, `ev/optimizacion/ejemplo_plan_d5.json` | `api/tests/unit/test_optimizacion_objetivo.py`, `api/tests/unit/test_optimizacion.py` |
| Detectar desviaciones y generar alertas operativas explicables. | ALT-001 a ALT-010 sobre el pronóstico y sobre lo observado, con la estructura de §5.3, episodios y deduplicación. | `ev/alertas/README.md`, `ev/alertas/alertas_observadas_ejemplo.json`, `ev/alertas/backtest_alertas.md` | `api/tests/unit/test_alertas.py`, `api/tests/integracion/test_alertas_observadas.py::test_ejecucion_con_datos_observados_produce_alt005_a_alt009` |
| El lenguaje principal es Python. | Backend en Python 3.11+ (imagen `python:3.11-slim`), FastAPI, SQLAlchemy 2, Alembic, scikit-learn, PuLP y ONNX Runtime. | `api/Dockerfile`, `api/pyproject.toml`, `api/requirements.txt`, `ev/modelo/docker_py311_shap.json` | CI con Python 3.11 y 3.13: `.github/workflows/api_frecuencias.yml` en la raíz del repositorio de entrega (la misma definición está en `api/ci/github_actions_entrega.yml`) |
| Los triggers, funciones y scripts que llenan las tablas de segmentación se conservan sin modificaciones. | Los scripts se ejecutan tal cual (verificados con `SHA256SUMS`). Las correcciones mínimas para que corran van en archivos aparte, y cada una tiene una prueba que muestra el fallo sin ella. Ningún usuario de la IA puede alterar el trigger ni las funciones. Una aclaración sobre RF-002: los scripts 5, 6 y 99 corren sobre la base vacía y filtran `proceso = 'cootransoriente'` (H4), así que con los datos de Sobusa no procesan ninguna fila. Por eso la segmentación histórica de la réplica viene de las exportaciones del reto, que es lo que esos scripts produjeron en la base de Extreme. Lo que sí pasa por el código de Extreme es la llegada nueva: el trigger del script 7 segmenta cada fila que entra. | `api/replica/extreme/`, `api/replica/errata/`, `ev/replica/replica_errata.txt`, `api/docs/hallazgos_extreme.md` | `api/tests/replica/test_integrado.py::test_nadie_de_la_ia_puede_deshabilitar_el_trigger_ni_tocar_funciones`, `api/tests/replica/test_scripts_extreme.py::test_script1_sin_errata_falla` |

### 2.2 Objetivos específicos

| Objetivo específico | Qué hicimos | Evidencia | Prueba |
|---|---|---|---|
| Consumir, validar y completar los datos de rutas, viajes, timbradas, estacionalidades y novedades viales. | Lectura de solo lectura de los catálogos y del contexto (procesos, rutas, estacionalidades, novedades con sus rutas, segmentos, vehículos, viajes y despachos). Validación de las 6 dimensiones de §6.3. Lo que no existe en el DDL (máximos y mínimos por segmento) se deriva en la capa analítica propia. | `ev/catalogos/fidelidad_y_relaciones.txt`, `ev/replica/replica_contexto.json`, `api/app/servicios/calidad.py`, `api/app/servicios/segmentos.py` | `api/tests/unit/test_calidad.py`, `api/tests/replica/test_segmentos.py`, `api/tests/integracion/test_catalogos_api.py` |
| Construir variables analíticas reproducibles para el entrenamiento y la inferencia. | Variables versionadas (`VERSIONES` fv1 y fv2), con el mismo código para entrenar y predecir. La foto exacta de variables de cada predicción se guarda en `feature_snapshot`. Dos entrenamientos con la misma semilla dan el mismo SHA-256. | `api/app/servicios/variables.py`, `ev/modelo/entrenamiento_fv2.json` | `api/tests/datos_ml/test_distribucion.py`, `api/tests/datos_ml/test_fuga_temporal.py::test_variables_no_usan_datos_posteriores_al_corte` |
| Predecir la demanda a 30, 60 y 120 minutos. | `POST /api/v1/predictions/run` y el ciclo diario predicen los tres horizontes, con el perfil intrahorario. | `ev/modelo/horizontes.json`, `ev/optimizacion/ejemplo_prediccion_12_3.json` | `api/tests/unit/test_inferencia.py` |
| Calcular la frecuencia recomendada por franja y el número mínimo de vehículos bajo restricciones. | `optimizar` con capacidad por tipología, flota, ciclo y headway mínimo y máximo. | `ev/optimizacion/ejemplo_calculate.json`, `ev/optimizacion/sensibilidad.md` | `api/tests/unit/test_optimizacion_objetivo.py` |
| Detectar desviaciones, datos anómalos, sobreocupación, baja utilización y ausencia de información. | Desviación ALT-007 (y caída ALT-005), consolidado anómalo ALT-008, sobreocupación ALT-002, baja utilización ALT-004 y datos ausentes o atrasados ALT-009. | `ev/alertas/README.md`, `ev/alertas/backtest_alertas.md` | `api/tests/unit/test_alertas.py`, `api/tests/unit/test_alertas_observadas.py` |
| Exponer los resultados mediante una API REST y un tablero operativo con historial y gestión de alertas. | Los endpoints de `/api/v1` y las pantallas Alertas, Recomendaciones, Operación y Monitoreo del tablero, con bitácora y acciones. | `api/README.md` («Endpoints»), `ev/tablero/e2e_tablero_completo.txt` (135 de 135 comprobaciones, 0 fallas), `ev/tablero/alertas_detalle_1366x768.png` | `api/tests/integracion/test_api_integracion.py::test_alertas_deduplicadas_y_bitacora` |
| Medir precisión, estabilidad, tiempos de respuesta, explicabilidad y utilidad operativa. | Precisión en la prueba reservada; estabilidad con modelos congelados un año y monitoreo semanal; tiempos con k6; explicabilidad con SHAP exacta; utilidad con el backtest de alertas y la sensibilidad del optimizador. | `ev/modelo/evaluacion_modelo.md`, `ev/monitoreo/monitoreo_2025.json`, `ev/rendimiento.txt`, `ev/modelo/explicacion_local_y_bandas.json`, `ev/alertas/backtest_alertas.md`, `ev/optimizacion/sensibilidad.md` | `api/tests/datos_ml/`, `api/tests/unit/test_monitoreo.py` |

## 3. Alcance funcional (§3)

### 3.1 Módulos obligatorios

| Módulo | Responsabilidad que pide la especificación | Dónde está | Evidencia | Prueba |
|---|---|---|---|---|
| Acceso y calidad | Leer vistas y tablas existentes; validar disponibilidad, integridad y rangos sin duplicar los datos. | `api/app/servicios/fuentes.py`, `calidad.py`, `ingesta.py`; `GET /api/v1/frequency/executions/{id}/errors` | `ev/replica/replica_llegada.txt`, `ev/cola/ingesta.txt` | `api/tests/integracion/test_api_integracion.py::test_carga_repetida_no_duplica`, `api/tests/unit/test_calidad.py` |
| Gestión operacional | Administrar los catálogos de empresa, ruta, segmento, vehículo, capacidad, viaje y despacho. | `api/app/servicios/catalogos.py`, `GET /api/v1/catalogos/*`; ajuste local de capacidad con `PUT /api/v1/catalogos/capacidad` | `ev/catalogos/README.md`, `ev/catalogos/ajuste_capacidad.txt`, `ev/catalogos/sin_datos_personales.txt` | `api/tests/integracion/test_catalogos_api.py`, `api/tests/unit/test_catalogos.py` |
| Predicción de demanda | Estimar pasajeros por ruta, sentido, segmento y franja horaria, con pronóstico e intervalo de confianza. | `api/app/servicios/inferencia.py`; por segmento y sentido, `GET /api/v1/predictions/segmentos` | `ev/modelo/evaluacion_modelo.md`, `ev/monitoreo/desagregacion_segmentos.json` | `api/tests/integracion/test_monitoreo_api.py::test_pronostico_por_segmento_suma_la_ruta` |

**Cumplimiento parcial en segmento y sentido.** Por ruta y franja, el pronóstico tiene un modelo evaluado y una banda
P10–P90 calibrada. Por segmento y sentido es una desagregación, no un modelo propio. El pronóstico de la ruta se reparte
con las fracciones de subidas por segmento del 1-1-2023 al 27-2-2023 (58 días;
`api/datos/reparto_segmentos.parquet`, columna `periodo`), y el sentido es una aproximación geométrica (S9), porque las
exportaciones no lo traen. La banda por segmento es el P10 y el P90 de la ruta escalados por la fracción. No es un
intervalo de confianza del segmento y su cobertura no está medida. El error por segmento y hora está en
`ev/monitoreo/desagregacion_segmentos.json`, y no se midió si las fracciones de 2023 siguen valiendo en 2025.
| Optimización | Traducir la demanda en intervalo de despacho y vehículos requeridos: una recomendación operativa viable. | `api/app/servicios/optimizacion.py`, `motor_d5/` | `ev/optimizacion/LEEME.md` | `api/tests/unit/test_optimizacion_objetivo.py` |
| Anomalías y alertas | Evaluar reglas y modelos; priorizar, explicar y registrar eventos informativos, preventivos y críticos. | `api/app/servicios/alertas.py`, `GET`/`PATCH /api/v1/alerts` | `ev/alertas/README.md`, `ev/alertas/backtest_alertas.md` | `api/tests/unit/test_alertas.py`, `api/tests/integracion/test_alertas_observadas.py` |
| Consulta y tablero | Exponer indicadores, predicciones, recomendaciones y alertas, con interfaz operativa y exportación. | `dash_app/paginas/alertas.py`, `recomendaciones.py`, `operacion.py`, `monitoreo.py`; exportaciones `*/export` de la API | `ev/tablero/e2e_tablero_completo.txt`, `ev/tablero/export_alertas_dash.xlsx` | `api/tests/integracion/test_api_integracion.py::test_exportaciones_csv_y_xlsx`, `api/tests/integracion/test_export_alertas.py` |

### 3.2 Fuera del alcance del prototipo

| Exclusión | Cómo la respetamos | Evidencia | Prueba |
|---|---|---|---|
| Control directo de despachos o comandos automáticos sobre vehículos. | La API no tiene ningún endpoint que despache ni que hable con los vehículos. Las escrituras solo cambian el estado de una alerta, lanzan ejecuciones o entrenamientos, gobiernan modelos o versionan umbrales y capacidad. La pantalla «Despacho en vivo» del tablero y la consola de la app HTML no controlan nada: repiten un día de 2025 con el plan recomendado, sin mandos sobre los buses. | `api/app/seguridad.py` (`POLITICA`, la lista completa de escrituras); `api/docs/manual_usuario.md`, sección 9 | `api/tests/integracion/test_seguridad.py::test_toda_escritura_tiene_rol_explicito` |
| Reemplazo, desactivación o modificación de los triggers. | El trigger queda activo en la réplica y ningún usuario de la IA puede deshabilitarlo. | `ev/replica/replica_objetos.txt`, `ev/replica/replica_roles.txt` | `api/tests/replica/test_integrado.py::test_nadie_de_la_ia_puede_deshabilitar_el_trigger_ni_tocar_funciones` |
| Rediseño de las tablas operativas o duplicación innecesaria de sus datos. | Todo lo nuevo va en el esquema `ai_frecuencias`. El histórico propio guarda solo la demanda horaria validada (`demanda_observada`), no las filas crudas. El ajuste de capacidad se versiona en `threshold_config` y nunca en la tabla `rutas`. | `api/alembic/versions/`, `ev/catalogos/ajuste_capacidad.txt`, `api/docs/integracion_postgresql.md` §1 | `api/tests/replica/test_roles.py::test_escritor_no_toca_tablas_de_extreme`, `api/tests/replica/test_integrado.py::test_escritor_ia_no_puede_escribir_ni_alterar_tablas_de_extreme` |
| Despliegue productivo definitivo sin pruebas de carga y aprobación de Extreme. | Hicimos las pruebas de carga con k6. El paso a producción queda condicionado a un modo sombra y a un piloto con la aprobación de Extreme. En `ENTORNO=produccion`, Swagger no se publica. | `ev/rendimiento.txt`, `PLAN_EVOLUCION.md` §1 y §6 | `api/tests/integracion/test_seguridad.py::test_swagger_restringido_por_ambiente` |

## 4. Organización del trabajo (§17)

Las fechas salen del historial del repositorio del equipo y de la fecha que lleva cada evidencia. Los experimentos de
modelado (experimentos 1 a 12) y de optimización (D1 a D6) se respaldaron en el repositorio el 7-10-2026. El backend del reto se
construyó del 8 al 9 de noviembre de 2026, después de recibir la especificación v1.5.

| Fase | Qué hicimos | Cuándo | Evidencia |
|---|---|---|---|
| 1. Descubrimiento | Entendimiento operativo, diccionario y perfilamiento de los datos de 2023 a 2025; mapa de las tablas de §8.2 frente a la base del reto; hallazgos sobre los scripts y los datos. | Hasta octubre de 2026; el mapa de §8.2 y los hallazgos, el 9-11-2026 | `Informe_tecnico_Sobusa.pdf` (sección 2 «Datos» y sección 3 «Datos, análisis exploratorio y preprocesamiento»), `api/datos/origen.json`, `api/docs/integracion_postgresql.md` §2, `api/docs/hallazgos_extreme.md` |
| 2. Línea base | Regla manual B1 (8 semanas) y B2 (última semana) como referencia medible; reglas de alertas con los umbrales de §5.1; primera API mínima. | Octubre de 2026 (B1 en el informe) y 8-11-2026 (API) | `ev/modelo/evaluacion_modelo.md` (B1 y B2), `ev/demo_ciclo_8nov.txt`, `api/alembic/versions/0001_esquema_ai_frecuencias.py` |
| 3. Modelado | Variables, 51 modelos comparados con validación temporal (experimentos 1 a 12 del informe), modelo de la API fv1 → fv2, registro con SHA-256 y fecha de corte. | Octubre de 2026 (experimentos) y 9-11-2026 (fv2) | `Informe_tecnico_Sobusa.pdf` (secciones 3 y 4), `entrega_final.ipynb`, `ev/modelo/decision_fv2.md`, `ev/modelo/entrenamiento_fv2.json` |
| 4. Producto | Persistencia en `ai_frecuencias`, inferencia, optimización de §10.2, alertas de §5 y tablero conectado a la API. | 8 y 9-11-2026 | `api/alembic/versions/`, `ev/optimizacion/LEEME.md`, `ev/alertas/README.md`, `ev/tablero/e2e_tablero.txt` |
| 5. Integración | Lectura incremental sobre la réplica, llegada real por el trigger, EXPLAIN de las consultas y roles de solo lectura. | 9-11-2026 | `ev/replica/replica_llegada.txt`, `ev/replica/explain_incremental.txt`, `ev/replica/replica_roles.txt`, `ev/replica/pytest_replica.txt` |
| 6. Endurecimiento | Pruebas en seis niveles, CI, observabilidad (logs JSON, métricas y trazas), seguridad por roles, resiliencia y contenedores. | 9-11-2026 | `ev/pruebas/suite_final.xml` (suite completa final: 1.060 casos, 0 fallas, 0 errores, 5 omitidas a propósito), `ev/pruebas/coverage_final.xml` (cobertura de `app/`, con `motor_d5/`, de 94,27 %), `ev/sonarqube/quality_gate.json` (puerta de SonarQube «Reto Sobusa v1.5» aprobada: 0 vulnerabilidades, 0 bugs, 0 críticos, 0 bloqueantes), `ev/pruebas/ci_local.txt`, `.github/workflows/api_frecuencias.yml`, `ev/seguridad/`, `ev/cola/caida_rnf001_docker.txt`, `api/Dockerfile`, `api/docker-compose.yml` |
| 7. Cierre | Prueba reservada de nov.–dic. 2025 (no se usó para entrenar ni para calibrar, pero se consultó al elegir fv2 frente a fv1: queda como reporte informativo, ver sección 6), documentación y presentación. | 9-11-2026 | `ev/modelo/evaluacion_modelo.md`, `api/docs/manual_tecnico.md`, `api/docs/manual_usuario.md`, `ev/README.md`, `PLAN_EVOLUCION.md`, `documentos/` |

## 5. Riesgos y mitigaciones (§18)

| Riesgo | Mitigación implementada | Evidencia | Prueba |
|---|---|---|---|
| Histórico insuficiente | La línea base B1 se calcula siempre al lado del modelo. Los intervalos son bandas P10–P90 calibradas, y el WAPE se reporta con IC95 por bloques y con modelos congelados un año (2024 y 2025). Las limitaciones están declaradas. Para la recolección adicional, cada ejecución incorpora los datos nuevos validados al histórico, que alimenta el reentrenamiento. | `ev/modelo/evaluacion_modelo.md`, `api/README.md` («Limitaciones»), `ev/cola/ingesta.txt` | `api/tests/datos_ml/test_no_regresion.py::test_cobertura_de_la_banda_p10_p90_estable`, `api/tests/integracion/test_monitoreo_api.py::test_entrenamiento_usa_historial_validado_y_no_pisa_el_activo` |
| Etiquetas incorrectas | Hubo conciliación entre fuentes: el trigger frente a la exportación, la réplica frente a los archivos y el contexto leído de la base frente al de los archivos. Detectamos y reportamos dos medidas no interpretables: `pasajeros` (H9) y los promedios con CEIL (H7). La muestra de alertas etiquetada dos veces está en `ev/alertas/revision_doble/`: dos revisores independientes con un protocolo escrito, un conciliador y el kappa de acuerdo. Los revisores fueron automatizados, así que falta la validación del área operativa de Sobusa con incidentes reales (§19, abajo). | `ev/replica/replica_llegada.txt`, `ev/catalogos/fidelidad_y_relaciones.txt`, `ev/replica/replica_contexto.json`, `api/docs/hallazgos_extreme.md` (H7, H9), `ev/alertas/backtest_alertas.md`, `ev/alertas/revision_doble/` | `api/tests/replica/test_llegada.py`, `api/tests/replica/test_carga.py` |
| Fuga temporal | Partición cronológica (entrenamiento, validación de 61 días y prueba reservada). Ninguna variable usa información posterior al instante. Cada predicción guarda `data_cutoff`. | `ev/modelo/evaluacion_modelo.md`, `api/docs/manual_tecnico.md` §5 | `api/tests/datos_ml/test_fuga_temporal.py::test_variables_no_usan_datos_posteriores_al_corte`, `::test_particion_del_modelo_activo_es_cronologica` |
| Alertas excesivas | Episodios con clave estable y deduplicación; severidades; persistencia de 2 horas en las reglas observadas; ALT-009 una sola vez por ruta y día. Se miden las alertas por ruta y día y el porcentaje de descartadas (monitoreo). En el backtest del 15-09 al 31-12-2025 (324 días-ruta) quedan 1,238 alertas observadas por ruta y día, con la ALT-002 observada y la ruptura de RF-009; las que ya medía la versión anterior (ALT-005 a ALT-009) son 0,534, frente a 6,08 con las reglas anteriores. Las de pronóstico, que comparan la carga crítica por hora con los puestos por hora, se cuentan aparte: ALT-001 0,435, ALT-002 0,315, ALT-003 0,380 y ALT-004 0,031 por ruta y día; en total, 2,399. En la revisión doble de 96 alertas, la kappa entre los dos revisores automatizados es 0,943 y la precisión reponderada, 0,839. Un episodio que se redetecta con más severidad se escala (sube la severidad y queda en la bitácora) en lugar de abrir otra alerta. | `ev/alertas/backtest_alertas.md`, `ev/alertas/backtest_alertas_pronostico.md`, `ev/alertas/revision_doble/conciliacion.json`, `ev/alertas/README.md`, `ev/monitoreo/monitoreo_2025.json` | `api/tests/integracion/test_api_integracion.py::test_alertas_deduplicadas_y_bitacora`, `api/tests/unit/test_alertas_observadas.py` |
| Consulta pesada | Lectura incremental por marca de agua (una ejecución diaria lee una fracción mínima de la tabla); `statement_timeout` de 30 s, `lock_timeout` y circuit breaker; réplica para las pruebas; índices propuestos al DBA después de EXPLAIN, que aplica él y no la aplicación. | `ev/replica/explain_incremental.txt`, `ev/replica/propuesta_indices.sql`, `ev/replica/replica_roles.txt`, `ev/seguridad/resiliencia.txt` | `api/tests/replica/test_explain.py`, `api/tests/replica/test_roles.py::test_lector_configuracion_de_sesion` |
| Recomendación inviable | Restricciones explícitas (flota, ciclo, headway, capacidad por tipología). Si no alcanzan, la salida es `viable = false` con el motivo en cifras y la mejor aproximación ejecutable, sin forzar una cifra. | `ev/optimizacion/ejemplo_calculate_no_viable.json` | `api/tests/unit/test_optimizacion_objetivo.py::test_inviable_por_headway_minimo_sin_cifra_forzada` |
| Deriva | Monitoreo de PSI, error móvil y cobertura en cada ejecución; champion/challenger con el candidato en sombra y una compuerta de 4 criterios; reversión manual o automática en los primeros 7 días; ALT-010. | `ev/monitoreo/monitoreo_2025.json`, `ev/monitoreo/compuerta_ejemplo.json` | `api/tests/integracion/test_monitoreo_api.py::test_retador_en_sombra_compuerta_y_reversion`, `api/tests/unit/test_politica.py::test_compuerta_de_activacion` |
| Exposición de datos | **Minimización:** los catálogos nunca exponen placa, conductor, propietario, contactos, módem ni GPS. **Acceso:** clave por rol y auditoría del usuario autenticado. **Anonimización:** el conductor de una alerta es un seudónimo HMAC, y la base rechaza un valor en claro. **Retención:** `feature_snapshot` va por particiones mensuales que se pueden retirar, con la política en `PLAN_EVOLUCION.md`. **Sin credenciales** en el repositorio. | `ev/catalogos/sin_datos_personales.txt`, `ev/seguridad/matriz_roles.txt`, `ev/alertas/README.md` («§18 Exposición de datos»), `api/alembic/versions/0004_monitoreo_y_trazabilidad.py` | `api/tests/integracion/test_alertas_observadas.py::test_la_base_rechaza_un_conductor_en_claro`, `api/tests/integracion/test_seguridad.py::test_ninguna_clave_en_claro_en_el_entorno_ni_en_el_log` |

## 6. Información que debe suministrar Extreme Technologies (§19)

Para cada punto: qué recibimos, qué supusimos mientras tanto y qué falta, con la pregunta exacta. Las preguntas H1 a
H16 están desarrolladas, con su evidencia, en `api/docs/hallazgos_extreme.md`.

| Punto de §19 | Lo que Extreme suministró | Lo que supusimos | Lo pendiente y la pregunta exacta |
|---|---|---|---|
| Diccionario de datos y relaciones entre procesos, rutas, segmentos, estacionalidades, timbradas y sus tablas | Las exportaciones de las tablas del reto, los 8 scripts de segmentación y la descripción de §6 y §8.2. | Las relaciones que se leen en el código de las funciones; el DDL de los objetos no entregados se dedujo de ese código (`ev/replica/replica_objetos.txt`). | **H2:** «¿Pueden enviar el DDL real de `rutas_segmentos_config` (o `pg_dump --schema-only` de las tablas de segmentación) y confirmar que `activo boolean NOT NULL DEFAULT true` existe en producción?» **H5:** «¿Pueden enviar el DDL de `rutasgeograficas`, `areascontrol`, `conteo_pasajeros` y las tablas de zonas y trazabilidad?» **H1:** «¿Cuál es la tabla de estacionalidades vigente para el proceso `sobusa`?» |
| Definición de los triggers, su periodicidad y el significado de cada consolidado | El código del trigger y de las funciones de liquidación y cierre. | Llegada → liquidación por viaje → cierre (`api/scripts/replica_simular_llegada.py`); comparación por sumas por segmento y viaje. | **H11:** «¿Con qué periodicidad y en qué orden se ejecutan en producción la liquidación y el cierre, y desde dónde (cron, aplicación, pg_cron)?» **H10:** «¿Cuál es el bloque oficial de un segmento: la hora en que el bus pasa por él o la hora de fin del viaje?» **H7:** «¿El promedio oficial es `CEIL(Σ/n)` o el valor con decimales? ¿Puede el cierre actualizar solo las filas que cambian?» **H4:** «¿Hay una versión de los scripts 5 y 6 para `sobusa`?» |
| Criterio oficial para subidas, bajadas, número de viajes, capacidad y frecuencia actual | — | Supuestos S0, S1, S2 y S6 (sección 0); frecuencia actual = intervalo programado de los datos; regla con que se fija hoy = promedio de las ocho semanas anteriores (B1). | **H15:** «¿Con qué regla fija hoy Sobusa el número de salidas por ruta y hora? ¿Es el promedio de las ocho semanas anteriores para la misma ruta, día y hora, otro número de semanas u otro criterio?» **H9:** «¿`pasajeros` debe ser la ocupación a bordo? Si es así, ¿la resta debe hacerse contra los acumulados al inicio del viaje?» **H6:** «¿Un viaje sin `fechafin` debe liquidarse (con qué fecha) o no debería estar marcado como apto?» Capacidad: «¿Existen `cap_min_autorizada` y `cap_max_autorizada` en la tabla `rutas` de producción y qué significan `tipovehiculo` 1, 2 y 24?» (hoy salen nulas en `GET /api/v1/catalogos/rutas`). |
| Acceso controlado a PostgreSQL 14 con permisos de solo lectura | Acceso de solo lectura a la base del reto. El equipo exportó los datos una sola vez y ni la API ni las pruebas vuelven a consultarla. | Los usuarios técnicos de §11.3 se crearon y probaron en la réplica: `lector_ia` (solo `SELECT`, transacción de solo lectura, `statement_timeout` 30 s) y `escritor_ia` (solo `ai_frecuencias`). | «¿Pueden crear en su ambiente un usuario de solo lectura y otro dueño solo de `ai_frecuencias`, con los permisos de `ev/replica/replica_roles.txt`?» (pasos en `PLAN_EVOLUCION.md` §1). |
| Los datos de conexión llegan por un canal de Extreme y no van en el repositorio | Cumplido: no hay credenciales en el repositorio; `.env` está en `.gitignore`. | — | — |
| La aplicación lee la conexión desde variables de entorno | Cumplido: `api/app/config.py` (pydantic-settings, URL con `repr=False`), `api/.env.example`. Prueba: `api/tests/unit/test_seguridad.py`. | — | — |
| Períodos 2023, 2024 y 2025 | Recibidos los tres años. | — | — |
| Rutas KRA 54, Silencio y Calle 72 | Recibidas las tres rutas: `CRA 54` (idruta 16, código 10), `SILENCIO` (idruta 2, código 2) y `CL 72` (idruta 21, código 15) en `api/datos/catalogo_rutas.json`. | La especificación escribe «Silencio (14/15)», pero en la tabla `rutas` exportada SILENCIO es la ruta 2 con código 2, y el código 15 es CL 72. Tomamos las tres rutas por su nombre. | **H16:** «¿Qué significa “(14/15)” junto a Silencio en §19? ¿Son los códigos de otra tabla o de variantes de la ruta que no se exportaron?» Y también: «¿Por qué 2.309 de los 2.695 segmentos son de rutas que no están en la tabla `rutas` exportada?» (`ev/catalogos/README.md`). |
| Histórico suficiente y fechas de corte, con un conjunto de prueba reservado que no se entrega durante el desarrollo | Los datos llegan hasta el 31-12-2025; no recibimos un conjunto reservado aparte. | Reservamos nov.–dic. 2025 como prueba y 25.915 filas de `timbradas_segmentos` para simular la llegada por el trigger (`ev/replica/replica_carga.txt`). La prueba no se usó para entrenar ni para calibrar, pero se consultó al elegir fv2 frente a fv1 (`ev/modelo/decision_fv2.md`), así que ya no es «nunca vista». El criterio de selección fue la validación (sep.–oct. 2025) y los backtests con modelos congelados en 2024 y 2025. La cifra de la prueba (14,77 % frente a 21,18 % de B1) queda como reporte informativo. | «¿Pueden entregar al cierre un período reservado de 2026, posterior al 31-12-2025, para medir el modelo activo con el protocolo de `ev/modelo/evaluacion_modelo.md`? Sería la prueba limpia.» |
| Capacidad de los vehículos, duración de los ciclos, flota disponible y límites de headway | — | Supuestos S2 y S6; headway mínimo y máximo en los umbrales versionados. | **H13:** «¿Cuál es el ciclo y la flota disponible por ruta, tipo de día y franja?». Los datos no cuadran: en CRA 54 a las 7 h el intervalo programado de 2,94 min con el ciclo de 249,1 min exige ⌈249,1 / 2,94⌉ = 85 vehículos, y la flota disponible es de 79 (`ev/optimizacion/ejemplo_calculate.json` y `ejemplo_calculate_no_viable.json`); en la hora pico, con la programación de hoy, SILENCIO necesita 47 buses de 45 y CRA 54, 80 de 79 en día laboral, y SILENCIO, 29 de 27 en domingo (`ev/respuesta/respuesta_reto.md`, `vehiculos.requeridos_programados` en `ev/respuesta/respuesta_2025-11-19.json` y `respuesta_2025-11-23.json`). Límites de headway: «¿Cuál es el intervalo mínimo entre dos despachos?»: el plan D5 admite 35 salidas por hora (1,71 min) en la madrugada laboral de CRA 54, y el mínimo gobernado es de 2 min (`headway_minimo_min`); esas horas salen «no viables» con su motivo. |
| Definición oficial de ocupación objetivo, tiempo máximo de espera y severidades | — | Supuestos S3, S4, S5 y S12: valores de §5.1 versionados en `threshold_config`; la espera máxima de 5 min, como espera media del pasajero (headway máximo efectivo de 10 min). | **H14:** «¿La “espera máxima” de 5 min es el intervalo máximo entre dos despachos (headway ≤ 5 min) o la espera media del pasajero (headway ≤ 10 min)?» También: «¿Aprueba el área operativa los umbrales de la versión vigente de `GET /api/v1/thresholds`?» (cada versión registra quién la aprobó y cuándo) y «¿Pueden etiquetar incidentes reales (un mes) para medir la precisión de las alertas?» (`ev/alertas/backtest_alertas.md`, `ev/alertas/revision_doble/`). |
| Ambiente o recursos de ejecución, tamaño máximo de archivos y volumen esperado | — | Portátil con Docker; volumen medido: 2,77 millones de filas hoy en `timbradas_segmentos` y unos 58,4 millones con el histórico completo (`ev/replica/replica_carga.txt`). | «¿En qué ambiente correría el servicio (máquina virtual, contenedores administrados) y con qué límites?» (costos en `PLAN_EVOLUCION.md` §3). **H8:** «¿En qué zona corre el servidor de producción (`SHOW TimeZone`) y cuánto puede durar como máximo una transacción de la captura?» **H3:** «¿Qué devuelve `SELECT indexdef FROM pg_indexes WHERE tablename = 'timbradas_segmentos';`?» **H12:** «¿Pueden aplicar la propuesta `ev/replica/propuesta_indices.sql` o indicar qué índices existen ya?» |
| Tarifa (no está en §19, pero la pregunta de §20 pide optimizar el recaudo) | — | Supuesto S11 (sección 0). | «¿Cuál es la tarifa neta por pasajero de Sobusa (tarifa pública menos la participación que no queda a la empresa)?» |
| Responsables técnicos y operativos para resolver dudas y validar resultados | — | — | «¿Quién es el DBA que aplica los índices y crea los usuarios, y quién del área operativa valida los umbrales y el piloto?» (roles en `PLAN_EVOLUCION.md` §6). |

## 7. Resultado final esperado (§20)

| Resultado esperado | Evidencia | Prueba |
|---|---|---|
| Lea los consolidados existentes y valide su calidad. | `ev/replica/replica_llegada.txt` (llega 1 franja nueva y se entrega exactamente esa), `ev/cola/ingesta.txt`, `GET /api/v1/frequency/executions/{id}/errors` | `api/tests/replica/test_integrado.py::test_ciclo_integrado_lee_exactamente_lo_nuevo_y_luego_nada`, `api/tests/unit/test_calidad.py` |
| Pronostique la demanda y recomiende despachos. | `ev/modelo/evaluacion_modelo.md`, `ev/optimizacion/ejemplo_plan_d5.json`, `ev/optimizacion/ejemplo_calculate.json` | `api/tests/datos_ml/test_no_regresion.py`, `api/tests/integracion/test_recomendaciones.py` |
| Genere alertas explicables. | `ev/alertas/alertas_observadas_ejemplo.json`, `ev/tablero/alertas_detalle_1366x768.png` | `api/tests/integracion/test_alertas_observadas.py::test_ejecucion_con_datos_observados_produce_alt005_a_alt009` |
| Conserve la trazabilidad en PostgreSQL. | Cada salida guarda `model_id`, `feature_version`, `data_cutoff`, `execution_id`, `umbrales_version`, `correlation_id` y `traceparent`; las variables exactas quedan en `feature_snapshot`. Ver `api/docs/manual_tecnico.md` §3 y §8 y `ev/seguridad/traza_ejecucion.json`. | `api/tests/integracion/test_monitoreo_api.py::test_ciclo_guarda_monitoreo_foto_y_columnas_nuevas`, `api/tests/integracion/test_api_integracion.py::test_activacion_controlada_y_reversion` |
| No modifique tablas, triggers, funciones ni scripts operativos. | `ev/replica/replica_roles.txt` (0 escrituras indebidas permitidas en 36 intentos), `api/replica/extreme/SHA256SUMS` | `api/tests/replica/test_integrado.py::test_escritor_ia_no_puede_escribir_ni_alterar_tablas_de_extreme`, `api/tests/replica/test_roles.py::test_lector_no_escribe_con_sesion_por_defecto` |
| La aplicación se ejecuta en Python, expone contratos REST con FastAPI y permite una demostración reproducible. | `api/docs/openapi.json`, `api/docs/despliegue.md` (sección 8, los seis pasos de §14.2), `ev/despliegue/demo_esperado.md` (qué muestra cada paso, con la salida de referencia), `ev/despliegue/demo_ciclo_api.txt` (la corrida en la pila Docker creada desde cero), `ev/demo_ciclo.txt`, `api/README.md` («Inicio rápido») | `api/tests/contrato/` (contrato y compatibilidad), `api/tests/testcontainers/test_postgis_contenedor.py` (esquema desde cero) |

## 8. La pregunta que debe resolver el sistema

> «Con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos
> pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?»

La respuesta completa, con sus cifras y su trazabilidad, está en `documentos/respuesta_pregunta_reto.md`. Las cifras
por día, ruta y franja salen de `GET /api/v1/respuesta` y quedan en `ev/respuesta/respuesta_reto.md` y en los
`ev/respuesta/respuesta_<fecha>.json`, generados con `api/scripts/respuesta_reto.py`.

El cálculo es asíncrono (§7.1). Al cerrar cada ejecución diaria, el ciclo calcula el plan del día siguiente por ruta
con el modelo activo y guarda la foto de la respuesta en `ai_frecuencias.respuesta_reto`. `GET /api/v1/respuesta` solo
lee esa foto. Si no la hay para esa fecha con el modelo y los umbrales vigentes, responde 404 con el código
`sin_calcular` y la pista de usar `POST /api/v1/respuesta/calcular` (rol analista). Ese POST responde 202 con el
`execution_id` de una ejecución de la cola. Cada parte sale de la API:

| Parte de la pregunta | Dónde se responde |
|---|---|
| Todo junto, por ruta y día | `GET /api/v1/respuesta` (`api/app/routers/respuesta.py`); tarjeta «Respuesta a la pregunta del reto» de la pantalla Inicio del tablero (`dash_app/paginas/inicio.py`), que pide el cálculo si falta. Pruebas: `api/tests/unit/test_respuesta.py`, `api/tests/integracion/test_respuesta_api.py::test_post_202_en_la_cola_y_get_200_desde_la_foto`, `api/tests/integracion/test_respuesta_api.py::test_404_sin_calcular_con_la_pista` y `api/tests/integracion/test_respuesta_api.py::test_atencion_abiertas_ahora_y_de_la_fecha` |
| ¿Cada cuánto despachar? | `GET /api/v1/recommendations/plan` (el plan del día por hora, persistido por el ciclo con el modelo activo) y `GET /api/v1/recommendations` (`headway_min` por franja); `ev/optimizacion/ejemplo_plan_d5.json` |
| …para optimizar la flota y el recaudo | Función objetivo de §10.2 con los costos de S5 y comparación con lo programado; `ev/optimizacion/sensibilidad.md`. El efecto en el recaudo está en el informe técnico (sección 4) y, por día, en el bloque `flota_y_recaudo` de `GET /api/v1/respuesta` |
| ¿Cuántos pasajeros se esperan? | `GET /api/v1/predictions` (con la banda P10–P90); el mismo pronóstico alimenta el plan, así que pasajeros y despachos coinciden hora a hora; `ev/modelo/evaluacion_modelo.md` |
| ¿Cuántos vehículos? | Los buses en ruta a la vez del plan frente a la flota (`vehiculos.requeridos_pico` de `GET /api/v1/respuesta`), con la fórmula de §10.3 al lado (sección 0, «Las tres definiciones de vehículos») |
| ¿Qué requiere atención inmediata? | `GET /api/v1/alerts?estado=nueva&severidad=critica`; el bloque de atención inmediata de `GET /api/v1/respuesta` (alertas abiertas ahora, las críticas primero); pantalla Alertas del tablero |

## 9. Limitaciones declaradas

- **Segmento y sentido.** El pronóstico, las variables de `feature_snapshot` y las alertas se calculan por ruta y hora.
  El segmento y el sentido salen de un reparto proporcional (sección 3.1), con el sentido aproximado (S9).
- **ALT-008 sin bajadas.** La regla de consolidado anómalo evalúa las subidas y el número de viajes. Las bajadas no se
  evalúan porque el histórico validado (`demanda_observada`) no las guarda (§3.2: no duplicar los datos operativos).
- **Parámetros operativos.** El ciclo, la flota y el intervalo programado son medianas de 2025 (S6) y no siempre cuadran
  (H13).
- **Prueba reservada consultada.** La cifra de nov.–dic. 2025 es informativa (sección 6); la prueba limpia sería un
  periodo de 2026.
- **Revisión de alertas.** La muestra etiquetada dos veces la hicieron revisores automatizados; falta la del área
  operativa (sección 5).
- **Datos históricos.** La base del reto termina el 31-12-2025: la llegada de datos nuevos se simula con días de 2025
  (S7).
- **Procesamiento por ruta y fecha (RNF-005).** La marca de agua es una sola para todo el proceso: las ejecuciones de
  frecuencia se serializan en el clúster, y el parámetro `rutas` limita la predicción, no la lectura ni la ingesta. Las
  réplicas reparten los trabajos de la cola sin duplicarlos, pero no parten una misma ejecución. Partir por ruta y
  fecha es el siguiente paso (`PLAN_EVOLUCION.md`, sección 2).
- **Estadísticas por segmento (RNF-002).** Con un año de resultados, las consultas paginadas cumplen (p95 de 627,5 ms),
  pero `GET /api/v1/segmentos/estadisticas` agrega la tabla de segmentos en cada petición y tarda 8,8 s en frío y
  11,9 s en caliente (`ev/pruebas/k6_volumen.txt`). Necesita una caché con vencimiento o una agregación materializada.
