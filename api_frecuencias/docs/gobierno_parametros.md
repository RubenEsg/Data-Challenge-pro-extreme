# Gobierno de los parámetros del plan, de la flota y del tiempo de ciclo

Especificación v1.5: §5.1 «Regla de gobierno: todos los umbrales se guardan en PostgreSQL, se versionan y se pueden
modificar sin recompilar la aplicación», §3.1 «Gestión operacional: administrar los catálogos de empresa, ruta,
segmento, vehículo, capacidad, viaje y despacho», §6.1 «Frecuenciadespachos: frecuencia vigente, que se compara con
la recomendación», §6.2 «Headway vigente, tomado de la frecuencia de despachos, y su diferencia con la frecuencia
recomendada» y §10.2 (flota disponible y duración del ciclo como restricciones).

Este documento describe tres cambios y dónde se prueban:

1. La tarifa, la elasticidad y la suavidad del plan del día (MILP de D5) pasan a `threshold_config` (migración 0010).
2. La flota disponible y el tiempo de ciclo se administran por la API, con versión y auditoría.
3. La recomendación compara el headway recomendado también con `rutas.frecuenciadespachos`.

## 1. Parámetros del plan del día en `threshold_config`

Antes, el plan del día (`app/servicios/optimizacion.py`, `plan_dia`) leía de `threshold_config` los límites de
headway, la ocupación objetivo, el nivel de servicio y los costos y pesos de §10.2, pero la tarifa, la elasticidad y la
suavidad salían de `param_d5()` (`app/servicios/motor_d5/comun.py`). Desde la migración 0010 son parámetros gobernados
como los demás (`PARAMETROS_PLAN` en `app/servicios/optimizacion.py`):

| Parámetro (`threshold_config`) | Clave del MILP (`param_d5`) | Valor sembrado | Validación (`validar_parametros_plan`) | Qué hace |
|---|---|---|---|---|
| `tarifa_cop` | `TARIFA` | 3.182 COP (3.700 × 0,86, `datos/costos_fuente.json`) | ≥ 0 | Ingreso perdido del plan (§10.2) y recaudo de la respuesta del reto |
| `elasticidad` | `ELASTICIDAD` | 0,5 | entre 0 y 1 | Pasajeros que se pierden al recortar la oferta frente a la programada |
| `delta_suavidad` | `DELTA` | 6 | > 0 | Cambio máximo de salidas por hora entre dos horas seguidas |
| `hora_inicio_suavidad` | `HORA_INICIO_SUAVIDAD` | 7 | entero de 6 a 21 (21 = sin suavidad; desde 4 o 5 tomaría la apertura de las 4 h, que deja sin solución el domingo de SILENCIO) | Hora desde la que rige la suavidad |

- **Lectura.** `parametros_plan(umbrales, version)` toma cada valor de la versión vigente, con la fuente
  `threshold_config vN`; si una instalación sin migrar no lo trae, usa el de `param_d5` (fuente «código de D5»). `_p_milp`
  los pasa al MILP en las claves que este lee. `motor_d5` no cambia: la copia vendorizada sigue igual y la prueba de
  paridad (`tests/unit/test_motor_d5.py`) sigue en verde.
- **Paridad.** Los valores sembrados son exactamente los de `param_d5`, así que sin una versión nueva el plan es el
  mismo (`tests/unit/test_gobierno_parametros.py::test_sin_version_nueva_el_milp_recibe_exactamente_los_parametros_de_d5`).
- **Sin claves del código en el MILP.** Al resolver un plan, el MILP lee solo `COSTO_BUS_HORA`, `COSTO_KM`,
  `VALOR_TIEMPO_ESPERA`, `PENALIDAD_SOBRECARGA`, `TARIFA`, `ELASTICIDAD`, `DELTA` y `HORA_INICIO_SUAVIDAD`, y todas
  llegan de `threshold_config` (`tests/unit/test_gobierno_parametros.py::test_el_milp_del_plan_solo_lee_claves_gobernadas`,
  que registra cada clave que lee el MILP).
- **Cambio sin reiniciar.** `PUT /api/v1/thresholds` (admin) crea una versión nueva «propuesta»; la aprueba
  `POST /api/v1/thresholds/{version}/aprobar`. El siguiente plan (ciclo diario o `POST /api/v1/respuesta/calcular`)
  usa los valores nuevos, queda ligado a `umbrales_version` y la respuesta del reto recauda con la tarifa nueva
  (`tests/integracion/test_gobierno_parametros.py::test_put_thresholds_cambia_tarifa_elasticidad_y_suavidad_y_el_siguiente_plan_los_usa`).
  Un valor fuera de rango responde 422 `umbral_invalido`.
- **El plan persistido dice con qué se calculó.** Las filas `origen = 'plan_dia'` guardan los parámetros con su fuente
  (`detalle.entradas.parametros`) y `GET /api/v1/recommendations/plan` los devuelve en `parametros`.
- **Sin solución, no hay plan.** Con la suavidad de D5 el MILP siempre tiene solución, porque la flota tiene holgura
  (se comprobó en los 1.095 días E12 de 2025 y en los nueve pares ruta × tipo de día del modelo activo). Una suavidad
  gobernada más estricta sí puede dejarlo sin solución: por ejemplo, `delta_suavidad` = 0,05, o la suavidad desde la
  transición de las 4 h un domingo de SILENCIO, que a las 4 h opera 0,18 min (una salida equivale a 333 salidas por
  hora). En ese caso `plan_dia` lanza un ValueError que nombra los parámetros que hay que revisar
  (`optimizacion._resolver_d5`). El ciclo diario lo registra como advertencia de la ruta, `GET
  /recommendations/plan` responde 404 y la respuesta del reto queda «sin datos». Antes salía un plan con estado
  «Infeasible» y horas marcadas viables, o el motor fallaba con «334 is not in list»
  (`tests/unit/test_gobierno_parametros.py::test_una_suavidad_gobernada_sin_solucion_no_entrega_un_plan`).

Lo que queda en `param_d5` no lo lee el MILP del plan con el modelo activo:

| Clave de `param_d5` | Por qué no es un umbral del plan |
|---|---|
| `COSTO_BUS_HORA`, `COSTO_KM`, `VALOR_TIEMPO_ESPERA`, `PENALIDAD_SOBRECARGA` | Se reemplazan por `costo_bus_hora_cop`, `costo_km_cop`, `valor_tiempo_espera_cop_h` y `penalidad_sobreocupacion_cop` de `threshold_config` (migración 0005), ponderados por α, β y γ |
| `INTERVALO_MIN`, `INTERVALO_MAX` | Mandan `headway_minimo_min`, `headway_maximo_min` y `espera_max_min` (migración 0001), como cotas de cada hora. `INTERVALO_MAX` solo lo usa el respaldo de la respuesta sin `plan_dia`, que no corre en esta versión |
| `CAPACIDAD` | La capacidad por bus sale de los insumos de cada hora (`parametros_operativos_hora.parquet`, 50 pasajeros) y, si hay, del ajuste local versionado de toda la ruta (`PUT /api/v1/catalogos/capacidad`), en la franja y en el plan del día (`flota_y_ciclo.capacidad_por_bus` dice la fuente) |
| `FACTOR_FLOTA`, `HORIZONTE`, `Z_CUANTILES` | Solo los usa el experimento D5 original; la API no los lee |

El plan de laboratorio que reproduce D5 con los pronósticos de 2025 (`plan_dia_d5` y `resumen_plan_d5`) sigue con
`param_d5` a propósito: es la referencia de paridad con el experimento, no el plan que usan el ciclo diario,
`GET /recommendations/plan` ni la respuesta del reto (todos con `plan_dia`).

Además, `tests/integracion/test_gobierno_parametros.py::test_todos_los_umbrales_que_usa_el_codigo_estan_en_postgresql`
comprueba que todo umbral con valor por omisión en el código (alertas, monitoreo, política de aprendizaje, función
objetivo, plan y oportunidad de la calidad) está en la versión vigente de `threshold_config`, con su descripción.

**Tolerancia de los datos tardíos de la calidad.** La regla OPOR-001 de §6.3 (dato que llega tarde frente al cierre de
su día, no bloqueante) usaba la cifra fija `calidad.RETRASO_MAXIMO` (2 días). Ahora el ciclo la toma de la versión
vigente: `periodos_atraso` × `periodo_ingesta_min`, el mismo umbral de §5.1 «datos atrasados» que usa ALT-009
(`calidad.retraso_maximo_de`, llamado desde `ejecucion.validar_calidad`). Con los valores sembrados la tolerancia es la
de antes (2 × 1.440 min); `RETRASO_MAXIMO` queda solo como valor por omisión si la versión no trae esos umbrales o no
son positivos. Lo prueban
`tests/unit/test_gobierno_parametros.py::test_la_tolerancia_de_oportunidad_es_el_umbral_gobernado_de_datos_atrasados`
y, con el ciclo completo por HTTP,
`tests/integracion/test_gobierno_parametros.py::test_el_ciclo_mide_los_datos_tardios_con_el_umbral_vigente_de_datos_atrasados`
(con 1 período, un registro que llegó 36 h tarde pasa a OPOR-001).

## 2. Flota disponible y tiempo de ciclo administrados por la API

**De dónde salían.** De `datos/parametros_operativos_hora.parquet`, la mediana 2025 de D1 por ruta, tipo de día y hora:
`tiempo_ciclo_min` de cada hora y la flota, que es la misma en todas las horas de un tipo de día (SILENCIO 45, 43 y 27
vehículos en día laboral, sábado y domingo o festivo; CRA 54, 79, 75 y 45; CL 72, 45, 43 y 27). Los leen la franja de
§10.2 (`optimizacion.contexto_franja`) y el plan del día (`optimizacion._insumos_modelo_activo`). La opción de
laboratorio E12 usa `datos/insumos_d5_2025.parquet` (el día de 2025); `datos/catalogo_rutas.json` trae los del día
laboral como respaldo de la franja, y `app/servicios/tipologias_flota.json` solo reparte la flota de la franja entre
tipologías. Cambiarlos exigía regenerar esos archivos.

**Ajuste local versionado** (`app/servicios/flota_ciclo.py`), con el mismo mecanismo que la capacidad: vive solo en
`ai_frecuencias.threshold_config`, cada cambio crea una versión nueva del conjunto completo con `creado_por`, `motivo` y
`creado_en`, y la versión queda en `umbrales_version` de cada recomendación y de cada hora del plan.

| Clave | Valor | Validación |
|---|---|---|
| `flota_override.<idruta>.<TIPO>` | vehículos disponibles | entero de 1 a 1.000 |
| `ciclo_override.<idruta>.<TIPO>.<HORA>` | minutos de vuelta completa | de 10 a 720 min |

`TIPO` es `LABORAL`, `SABADO`, `DOMINGO_FESTIVO` o `TODOS`; `HORA`, de 4 a 20 o `TODAS`. Manda el tipo de día exacto
sobre `TODOS` y, dentro de cada uno, la hora exacta sobre `TODAS`; sin ajuste rige el dato empaquetado. Un valor
inválido escrito a mano en la tabla se ignora y queda en el log.

**Un cambio a la vez.** `PUT /api/v1/thresholds`, `PUT /api/v1/catalogos/capacidad` y `PUT /api/v1/catalogos/flota`
toman el mismo candado de la transacción antes de leer la versión vigente (`ejecucion.bloquear_umbrales`, con
`pg_advisory_xact_lock`, que se suelta con el commit o el rollback). Si dos cambios llegan a la vez, el segundo espera
y parte de la versión que dejó el primero. Antes, el segundo ajuste dejaba una versión vigente con solo su parámetro:
el resto del conjunto dejaba de regir y ni siquiera se podía restituir por `PUT /thresholds`, que rechazaba los
umbrales como «desconocidos». Y un `PUT /thresholds` simultáneo con un ajuste chocaba con la unicidad de
`(nombre, version)` y respondía 500. Lo prueba, con dos sesiones en dos hilos,
`tests/integracion/test_gobierno_parametros.py::test_dos_cambios_simultaneos_del_conjunto_gobernado_no_pierden_parametros`.

| Operación | Rol | Qué hace |
|---|---|---|
| `GET /api/v1/catalogos/flota?idruta=&tipo_dia=` | operador | Flota y ciclo vigentes por ruta, tipo de día y hora, con el dato del catálogo, la fuente (`catalogo` o `ajuste_local`) y la clave que manda |
| `PUT /api/v1/catalogos/flota` | admin | Versión nueva: `{idruta, tipo_dia, flota?, tiempo_ciclo_min?, hora?, motivo}`; `null` retira el ajuste y un campo que no viene no cambia. Firma el usuario autenticado. Errores: 422 `ruta_desconocida`, 422 `ajuste_invalido` (sin cambios o `hora` sin ciclo), 404 `ajuste_inexistente` (retirar lo que no existe), 422 `validacion` (rangos) |
| `GET /api/v1/catalogos/flota/historial?idruta=` | operador | Cada cambio (creado, cambiado, retirado) con el valor anterior y el nuevo, quién, por qué y cuándo (-05:00); total en `X-Total-Count` |

**Quién lo usa.** La franja de §10.2 (`_con_ajuste_operativo`: `contexto_franja.flota_disponible`,
`contexto_franja.tiempo_ciclo_min` y `contexto_franja.ajuste_operativo` con la clave y la versión) y el plan del día,
con el modelo activo o E12 (`_aplicar_operacion`: la flota del MILP y el ciclo de cada hora; la salida trae
`flota_y_ciclo` con la fuente de cada uno). El reparto por tipologías usa la flota de la franja, así que también la
nueva. El plan del día toma además la capacidad por bus del ajuste local de toda la ruta (`PUT
/api/v1/catalogos/capacidad`), la misma que ya usaba la franja (`flota_y_ciclo.capacidad_por_bus`), y la respuesta
del reto compara las ofertas con esa capacidad
(`tests/unit/test_gobierno_parametros.py::test_la_capacidad_gobernada_tambien_rige_el_plan_del_dia`). El detalle de
una ruta (`GET /api/v1/catalogos/rutas/{idruta}`) trae la misma vista en `flota_y_ciclo`. Prueba por HTTP: `tests/integracion/test_gobierno_parametros.py::test_flota_y_ciclo_por_la_api_versionados_auditados_y_usados_por_la_franja_y_el_plan`
(con 40 vehículos en CRA 54 laboral la franja de las 7 h deja de ser viable y el plan cabe en 40 buses en ruta).

Cuando Extreme responda el hallazgo H13 (`docs/hallazgos_extreme.md`: ciclo oficial y flota disponible por ruta, tipo
de día y franja), los valores se registran con `PUT /api/v1/catalogos/flota`, sin regenerar datos ni reiniciar.

## 3. Headway vigente de `rutas.frecuenciadespachos`

La recomendación conserva la comparación con el intervalo programado observado (`frecuencia_actual_min`,
`diferencia_min`, mediana 2025 de D1 por ruta, tipo de día y hora) y agrega la del headway vigente que fija la tabla
`rutas` de Extreme (`frecuenciadespachos_tabla_rutas` de `datos/catalogo_rutas.json`, la exportación de la tabla
`rutas`; vale 5 en las tres rutas y se lee en minutos, igual que `frecuenciadespachos_min` de `GET /catalogos/rutas`):

| Campo | Dónde | Qué es |
|---|---|---|
| `frecuenciadespachos_min` | `POST /recommendations/calculate`, `POST /predictions/run` (`recomendacion`), `GET /recommendations`, exportaciones, columna de `recommendation` (migración 0010), cada hora del plan y su resumen | El headway vigente de `rutas.frecuenciadespachos` |
| `diferencia_frecuenciadespachos_min` | Los mismos | Headway recomendado − vigente (negativo: despachar más seguido); nulo si la franja no es viable o la hora no tiene salidas, como `diferencia_min` |
| `cambio_frecuenciadespachos` | `POST /recommendations/calculate` y cada hora del plan | `reducir_intervalo`, `ampliar_intervalo` o `mantener` (±0,05 min) |
| `fuente_frecuenciadespachos` | `POST /recommendations/calculate` y el plan | De dónde sale el valor |

La explicación de la franja agrega la frase con las dos cifras. Pruebas:
`tests/unit/test_gobierno_parametros.py::test_la_franja_compara_con_frecuenciadespachos_y_conserva_el_intervalo_programado`,
`tests/unit/test_gobierno_parametros.py::test_cada_hora_del_plan_compara_con_frecuenciadespachos_y_se_persiste` y
`tests/integracion/test_gobierno_parametros.py::test_la_recomendacion_guarda_el_headway_vigente_de_frecuenciadespachos`.

**De dónde sale en modo integrado.** La recomendación lee la frecuencia de la ruta con `datos.ruta_info`
(`app/servicios/datos.py::frecuencia_vigente`). En modo offline es la del catálogo empaquetado. En modo integrado
(la fuente de la capa analítica configurada, `FUENTE_DATABASE_URL`) es la de la tabla `rutas` de la base de Extreme,
leída en solo lectura con una consulta de la lista blanca de `app/servicios/fuentes.py`
(`CONSULTAS_CONTEXTO["frecuencias"]`: `SELECT idruta, nombre, frecuenciadespachos FROM rutas`, en la transacción
`READ ONLY` con `statement_timeout`; `fuentes.frecuencias_despacho` la guarda 5 minutos por fuente, también si no
responde, para no consultar en cada uso de la ruta ni sumarle intentos al circuit breaker). Si la fuente no responde,
no trae la columna (SQLSTATE 42703) o no trae un valor para la ruta, rige la del catálogo empaquetado. La información
de la ruta dice de dónde salió: `frecuencia_fuente` (`fuente` o `catalogo_empaquetado`) y `frecuencia_fuente_detalle`
(el motivo). La unidad sigue siendo el supuesto S14 (minutos entre despachos), que debe confirmar Extreme (H15).
Pruebas: `tests/unit/test_fuentes.py::test_frecuencias_de_la_fuente_con_respaldo_y_memoria`,
`tests/unit/test_fuentes.py::test_ruta_info_toma_la_frecuencia_de_la_fuente_en_modo_integrado` (fuente simulada) y
`tests/replica/test_consolidados.py::test_la_frecuencia_vigente_sale_de_la_tabla_rutas_de_la_replica` (réplica como
`lector_ia`, en solo lectura: el valor de la recomendación es el de `rutas.frecuenciadespachos`). Pendiente de la
integración: `fuente_frecuenciadespachos` de la recomendación y del plan todavía es el texto fijo de
`optimizacion.FUENTE_FRECUENCIADESPACHOS` («exportación empaquetada»); debería tomar `frecuencia_fuente` de la ruta
(cambio en `app/servicios/optimizacion.py`).

## Migración 0010

`alembic/versions/0010_parametros_plan_y_frecuenciadespachos.py` (revisión `0010`, sobre `0009`): versión nueva y
completa de `threshold_config` con los cuatro parámetros del plan (un valor ya vigente se conserva) y las columnas
`frecuenciadespachos_min` y `diferencia_frecuenciadespachos_min` en `recommendation`. La bajada borra solo sus filas
(si no queda ninguna vigente, vuelve vigente la versión anterior) y las dos columnas. La subida, la bajada y la
coincidencia de los valores con el código las prueba
`tests/integracion/test_gobierno_parametros.py::test_migracion_0010_siembra_los_parametros_del_plan_y_las_columnas`.

## Evidencias

En `docs/evidencias/gobierno/` (se regeneran con
`GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_gobierno_parametros.py`):

| Archivo | Qué muestra |
|---|---|
| `umbrales_en_postgresql.json` | Todos los umbrales y parámetros con valor por omisión en el código, por grupo, con su valor vigente, quién creó la versión y su descripción |
| `parametros_plan_gobernados.json` | El plan de CRA 54 antes y después de `PUT /thresholds` con tarifa 2.800, elasticidad 0,3 y suavidad 2: parámetros con su fuente, salidas por hora, componentes del costo y recaudo de la respuesta |
| `ajuste_flota_ciclo.json` | El flujo de `PUT /catalogos/flota`: roles, versión nueva, franja de las 7 h y plan del día con 40 vehículos, ciclo de 150 min a las 7 h, validaciones, historial y retiro |
| `frecuenciadespachos.json` | Una franja y un plan con las dos comparaciones (intervalo programado y `rutas.frecuenciadespachos`), la fila guardada y la cabecera de la exportación |
| `oportunidad_gobernada.json` | El ciclo con un registro que llegó 36 h tarde: sin OPOR-001 con la versión sembrada y con OPOR-001 (tolerancia de 1 día) tras `PUT /thresholds` con `periodos_atraso` = 1 |
| `pytest_gobierno_parametros.txt` | La corrida de las pruebas de este cambio |
