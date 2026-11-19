# Retención de datos: política gobernada y tarea automática

Especificación v1.5, §18 «Exposición de datos → minimización, control de acceso, retención y anonimización». La
minimización, el control de acceso y la anonimización ya estaban (catálogos sin datos personales, claves por rol,
seudónimo HMAC del conductor). Desde la migración 0012 la retención deja de ser solo una política escrita: es un
trabajo de la cola de tipo `retencion` (`app/servicios/retencion.py`) que la aplica, lo programa el planificador, se
puede correr bajo demanda y deja una bitácora.

## La política

La documentada en `PLAN_EVOLUCION.md` (§2, «Particionamiento»: 13 meses en caliente; las particiones
viejas se separan con `DETACH PARTITION`) y en la especificación técnica E02 («Retención: particiones mensuales con
DETACH/DROP en la tabla de mayor volumen»), extendida a las demás tablas que crecen. El corte de cada grupo es el
instante de la corrida menos N meses del calendario de Bogotá; lo anterior al corte se borra.

| Grupo | Tablas | Qué hace con lo anterior al corte | Parámetro (meses) |
|---|---|---|---|
| foto | `feature_snapshot` | Separa (`DETACH PARTITION`) y borra (`DROP`) cada partición mensual cuyo rango termina antes del corte, cuyas filas se crearon todas antes del corte y en la que ninguna foto es de una predicción que la regla de resultados de la misma corrida conserva (una foto vive lo que vive su predicción; ver «Bordes»). Con `retencion_archivar_particiones = 1` la deja como `<partición>_archivo` (o `_archivo_2`, `_3`… si el mes ya se archivó antes) para archivarla con `pg_dump`, sin las llaves foráneas que clonó de `feature_snapshot` (a `prediction` y a `execution_log`, `ON DELETE CASCADE`): con ellas, la regla de resultados de la misma corrida, al borrar su predicción vieja, vaciaba el archivo en cascada. | `retencion_meses_foto` = 13 |
| resultados | `recommendation`, `prediction` (con su foto por llave foránea), `prediction_corto_plazo`, `respuesta_reto`, `segmento_estadistica_refresco` | Borra las filas por su fecha de creación. Nunca una predicción que sostiene una recomendación que se conserva, ni la última marca de refresco ni la del último completo. | `retencion_meses_resultados` = 13 |
| alertas | `notification_log`, `alert` cerradas o descartadas (con `alert_history`) | Borra por fecha; la alerta, por su última actualización. Una alerta abierta nunca se borra; tampoco una con una notificación que se conserva. | `retencion_meses_alertas` = 13 |
| ejecuciones | `execution_log` «ok» o «error» (con `execution_attempt`, `data_quality_error` y `model_monitoring`) | Borra las que ya no sostienen nada: ni una marca de agua (`marca_agua_ruta` o `marca_agua_tabla`, cuya llave foránea `ON DELETE CASCADE` se llevaría la marca), ni un modelo (`model_registry`), ni el histórico validado (`demanda_observada`), ni un resultado, una alerta o una notificación que se conservan, ni un trabajo por ruta que se conserva. Nunca la última de cada tipo. | `retencion_meses_ejecuciones` = 13 |
| derivada | `segmento_estadistica_dia`, `segmento_estadistica` | Se conservan: son derivadas de `timbradas_segmentos`, el refresco las iguala a la fuente y el refresco completo periódico (`SEGMENTOS_COMPLETO_DIAS`) las recalcula, así que su retención es la de Extreme. La bitácora deja en cada corrida sus filas, su período y su tamaño. | — |
| conservada | `demanda_observada`, `ocupacion_segmento`, `model_registry`, `threshold_config`, `marca_agua_ruta`, `marca_agua_tabla`, alertas abiertas, `retencion_registro` | Se conservan siempre: histórico validado del reentrenamiento (RF-018), la ocupación observada por segmento (§10.1, migración 0011; sin datos personales, es la serie para recalibrar la restricción reactiva y el perfil histórico), auditoría de modelos y parámetros, estado de la lectura incremental (por ruta y, para los consolidados de Extreme, por tabla: migración 0013, sin datos personales) y la bitácora de esta tarea. | — |

`0` meses en un grupo = ese grupo no se recorta. El mínimo distinto de 0 es 3 meses: menos rompería las ventanas que
el sistema lee hacia atrás (monitoreo de 28 días, sombra de 14, calibración conformal de 56). Volumen de la foto desde
la ola A (filas por segmento y sentido): unos 0,47 MB por ejecución, unos 14 MB por mes con una ejecución diaria; con
13 meses en caliente quedan unos 180 MB, y cada mes que sale del corte se va entero sin `DELETE` ni `VACUUM`.

## Gobierno

Los seis parámetros viven en `threshold_config` (la migración 0012 los siembra en una versión nueva del conjunto
completo; `app/servicios/retencion.py::PARAMETROS` tiene los mismos valores por omisión y una prueba verifica que
coinciden). `GET /api/v1/thresholds` los muestra con su historial; `PUT /api/v1/thresholds` (rol admin, auditado) los
cambia con su validación (meses enteros, 0 o entre 3 y 120; banderas 0 o 1) y `POST /api/v1/thresholds/{version}/aprobar`
aprueba la versión. `retencion_aplicar_programada = 0` deja la corrida programada en simulación (solo informa).

## La tarea

- **Programada**: el planificador encola una franja `retencion` con `PLAN_RETENCION_CRON` (por omisión
  `30 3 * * 0`, los domingos antes del ciclo diario; vacío la apaga), una sola fila por franja en todo el clúster.
- **Bajo demanda**: `POST /api/v1/retencion/aplicar` (rol admin) responde 202 con el `execution_id`; cuerpo opcional
  `{"simular": true | false, "motivo": "..."}`. Por omisión SIMULA. Si ya hay una corrida en cola o corriendo,
  devuelve esa (`nueva: false`). El progreso y el resumen se ven en `GET /api/v1/frequency/executions/{id}`.
- **Consulta**: `GET /api/v1/retencion` (rol operador) devuelve la política tabla por tabla con el corte de hoy, los
  parámetros y su versión, y la bitácora de la última corrida.

Cada acción va en su propia transacción corta con su fila en `retencion_registro` (bitácora: grupo, objeto, acción,
corte, filas, bytes, versión de los parámetros, si fue simulación y el detalle). Las filas se borran por lotes de
`LOTE_FILAS` (5.000) y la fila de bitácora de la tabla se actualiza en la transacción de cada lote, así que siempre
dice lo que de verdad se borró. Una madre de una ejecución partida por ruta solo es candidata cuando ya no le queda
ningún trabajo (se borra en un lote posterior; si un trabajo se conserva, ella también). Separar una partición pide
candados sobre `feature_snapshot` y sobre las tablas a las que apunta su llave foránea (medido en PostgreSQL 14: el
`DETACH` toma `ShareRowExclusive` sobre `prediction` y `execution_log`, y el `DROP`, o quitar las llaves del archivo,
`AccessExclusive`, que espera a cualquier transacción abierta que haya leído `execution_log`): con `lock_timeout` de
500 ms (`ESPERA_CANDADO`), si un ciclo los tiene, la acción queda «pospuesta» para la corrida siguiente y nadie espera
de más. La espera es menor que `deadlock_timeout` (1 s): si un ciclo queda esperando a la retención entre el `DETACH` y
el `DROP` mientras la retención lo espera a él, PostgreSQL aborta al primero que cumple `deadlock_timeout`; con 500 ms
cede siempre la retención (con 2 s caía el ciclo por «deadlock detected»). Todo es idempotente;
antes de cada acción se verifica que la reserva de la cola sigue siendo de la réplica (si la pierde, la que retoma el
trabajo sigue donde quedó).

**Simulación**: las particiones se planifican sin tocarlas y las filas se cuentan con los mismos `DELETE`, en el
mismo orden, dentro de una transacción que se revierte; así cuenta exactamente lo que se borraría, también lo que solo
queda libre al borrar lo de la regla anterior (una ejecución que sostenía una predicción vieja). Nada se borra; la
bitácora queda con `simulado = true`.

**Solo el esquema propio**: todo el SQL es constante (lista blanca) y nombra solo tablas de `ai_frecuencias` (y el
catálogo de PostgreSQL para listar las particiones y los archivos); los nombres de las particiones salen de
`pg_inherits` de `ai_frecuencias.feature_snapshot`, se validan con `^feature_snapshot_[0-9]{6}$` (los de los archivos,
con `^feature_snapshot_[0-9]{6}_archivo(_[0-9]{1,4})?$`) y van entre comillas.

## Bordes

**Una foto vive lo que vive su predicción.** Una partición vieja (su rango termina antes del corte de la foto y sus
filas se crearon antes) no se separa si alguna de sus fotos es de una predicción que la regla de resultados de la MISMA
corrida conserva: una predicción creada desde el corte de resultados o una predicción vieja que sostiene una
recomendación que se conserva (creada desde ese corte). El plan de la foto corre antes que las reglas de filas, así que
lo decide con los cortes y no con lo que todavía existe: la recomendación que sale del corte en esta corrida ya no
protege a su predicción, y la partición se separa en la misma corrida en que se borran las dos. La acción queda
«conservar» con `fotos_de_predicciones_conservadas` y el motivo en la bitácora; la partición se vuelve a evaluar en
cada corrida (cuando su predicción se borra, su foto se va con ella por la llave foránea y la partición queda libre).
No se mueven filas antes del `DROP`: una partición mensual guarda las fotos de su rango de `ventana_inicio`, y sacar
una foto de ahí exigiría otra tabla o un `DELETE` con su `VACUUM`, justo lo que la partición evita. Con
`retencion_meses_resultados = 0` se conservan todas las predicciones y, con ellas, sus fotos: la foto solo se recorta
antes que los resultados si no tiene predicción. Prueba:
`tests/integracion/test_retencion.py::test_la_foto_de_una_prediccion_que_se_conserva_conserva_su_particion`
(evidencia `docs/evidencias/retencion/foto_de_prediccion_conservada.json`).

**El mismo mes archivado dos veces.** Si se reprocesan datos viejos, `asegurar_particion_feature_snapshot` vuelve a
crear la partición de un mes que ya se archivó y, cuando envejece, la retención la archiva otra vez. El `RENAME` a
`<partición>_archivo` chocaba con el archivo anterior y la acción quedaba «pospuesta» en cada corrida. Ahora el archivo
toma el primer nombre libre (`retencion.nombre_de_archivo`): `<partición>_archivo`, luego `<partición>_archivo_2`,
`_3`…; el anterior queda intacto y la bitácora dice el nombre (`detalle.archivo`). **Para el DBA**: los archivos de un
mes son todas las tablas `ai_frecuencias.feature_snapshot_AAAAMM_archivo*` (por ejemplo,
`pg_dump -t 'ai_frecuencias.feature_snapshot_*_archivo*'`); cada una es independiente, sin llaves foráneas, y se borra
con `DROP TABLE` cuando quede respaldada. Prueba:
`tests/integracion/test_retencion.py::test_el_mismo_mes_archivado_dos_veces_no_choca_con_su_archivo` (evidencia
`docs/evidencias/retencion/archivo_repetido.json`).

Las filas de los ciclos intradía (foto de variables, predicciones, recomendaciones y su ejecución) se borran por
antigüedad como las del ciclo diario, porque las reglas no miran el origen
(`tests/integracion/test_retencion.py::test_las_filas_de_los_ciclos_intradia_se_borran_por_antiguedad_como_las_del_diario`).
`ai_frecuencias.ocupacion_segmento` no tiene regla de retención: los ciclos intradía reemplazan las franjas del día y no
le agregan llaves.

## Pruebas

- `tests/unit/test_retencion.py`: parámetros iguales a los de la migración y su validación, el corte por meses, que
  todo el SQL solo nombra tablas de `ai_frecuencias`, la DDL de las particiones con el nombre validado, que la
  política cubre cada tabla del esquema, cuándo simula, el planificador, la cola y la matriz de permisos.
- `tests/integracion/test_retencion.py`: con filas y particiones sembradas a ambos lados del corte y tablas centinela
  con los mismos nombres en otro esquema, la simulación no borra nada y deja la bitácora; la aplicación borra solo lo
  anterior al corte y solo en `ai_frecuencias` (y es idempotente); el modo archivo con la política completa (el
  archivo conserva sus filas y no tiene llaves foráneas aunque la misma corrida borre su predicción); el mismo mes
  archivado dos veces (`_archivo_2`, sin posponer); la partición con la foto de una predicción que se conserva; la
  partición con candados ocupados queda pospuesta y se separa después; en un interbloqueo con un ciclo cede la
  retención y el ciclo inserta su predicción; el trabajo de la cola por la API (202, simula por omisión, no se
  duplica, 403 a quien no es admin); el gobierno en `threshold_config` (422 con 1 mes; con
  `retencion_aplicar_programada = 0` la corrida programada solo simula; la prueba deja `threshold_config` como lo
  encontró con `tests/integracion/conftest.py::restituir_umbrales`, así que puede correr antes que las pruebas de
  bajada de las migraciones 0005 y 0007) y la migración 0012 que sube y baja.
