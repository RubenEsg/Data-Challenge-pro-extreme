# Consolidados de Extreme en el ciclo diario y bajadas en el histórico

Migración 0013 y `app/servicios/consolidados.py`. Cubre §5.2 (ALT-008 «subidas, bajadas o número de viajes
atípicos»), §6.1 (bajadas, `nro_viajes`, `promedio_subidas`, `promedio_bajadas`, promedios por segmento y
`ultima_actualizacion` de `timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`), §6.3 (consistencia de los
promedios), §7.3 paso 3 (coherencia de subidas, bajadas, viajes, ruta, segmento, estacionalidad, día de la semana y
rango horario), §9.5 (subidas y bajadas en el histórico) y §11.2 (validar promedios, máximos y mínimos por segmento,
estacionalidad, día y rango horario).

## 1. Bajadas en el histórico propio

`demanda_observada` gana cuatro columnas (migración 0013). Las llena la ingesta (`app/servicios/ingesta.py`, el mismo
COPY y el mismo upsert de siempre) con lo que trae el lote:

| Columna | Qué es | De dónde sale |
|---|---|---|
| `bajadas_viajes` | Σ `numerobajadas` de los viajes válidos de la franja (finalizado `S`, no cancelado, dato <= 300, ceros incluidos): la definición de `pasajeros` aplicada a los descensos | Lectura integrada `demanda_segmentos` (`app/servicios/fuentes.py`) y, en modo offline, `datos/bajadas_horaria.parquet` (`scripts/preparar_datos_api.py --solo-bajadas`) |
| `subidas`, `bajadas` | Σ de `timbradas_segmentos` de los viajes de la franja (lo que escribe el trigger de Extreme) | Lectura integrada |
| `viajes_con_timbradas` | Viajes de la franja con timbradas (la cobertura de las dos anteriores) | Lectura integrada |

Por qué `bajadas_viajes` (`docs/evidencias/consolidados/definicion_bajadas.md`): en el solape de 2023, en los mismos
viajes, Σ bajadas de los segmentos y Σ `numerobajadas` difieren 0,1 %; en total difieren −5,3 % porque 1.529 viajes
válidos no tienen timbradas. Es lo mismo que pasó con pasajeros (`docs/evidencias/datos/definicion_pasajeros.md`).
`bajadas_viajes` cubre todo 2023-2025, así que es la que usan ALT-008, su backtest y el contraste con
`timbradas_consolidado`.

- La huella de la lectura integrada cambió de forma (`VERSION_ESTADO = 3`): la primera lectura después de migrar
  vuelve a entregar su ventana de solape, y el upsert completa las columnas nuevas de esas franjas.
- Una medida que el lote no trae (o que llega nula) no borra la que ya estaba: el upsert usa
  `COALESCE(EXCLUDED.x, d.x)`, y el `WHERE … IS DISTINCT FROM` sigue evitando reescribir filas iguales.
- Las filas que ya estaban quedan con las columnas nulas: la migración no lee la base de Extreme.

## 2. ALT-008 con bajadas

`ejecucion._consolidado_del_dia` suma por día `pasajeros` (subidas), `bajadas_viajes` (bajadas) y `salidas` (viajes).
Las bajadas de un día solo cuentan si todas sus horas las traen; la referencia del mismo tipo de día usa solo los días
con el dato completo. La regla es la misma para los tres campos (`alertas._observadas_008`: z robusto con la mediana y
1,4826·MAD, `z_anomalia`, `escala_minima_z`, `semanas_referencia` y `minimo_dias_referencia` de `threshold_config`).

Backtest (`scripts/backtest_alertas.py`, `docs/evidencias/alertas/backtest_alertas.md`, 2025-09-15 a 2025-12-31,
modelo activo): 23 alertas ALT-008 (0,071 por ruta y día, precisión 0,652, lift 3,52) frente a 20 sin evaluar las
bajadas (0,062; 0,700; 3,78); 21 de las 23 tienen las bajadas sobre el umbral. Las demás reglas no cambian.

## 3. Los consolidados de Extreme en el ciclo

Una vez por ejecución: en la de todas las rutas, al cerrar (`ejecucion._cerrar_ciclo`); partida por ruta (RNF-005),
en la madre al cerrar (`ejecucion._ciclo_de_la_madre`), nunca en un trabajo de ruta. Usa la versión de umbrales de la
ejecución (`umbrales_de_la_ejecucion`): un `PUT /thresholds` mientras corre una ejecución partida no cambia sus
tolerancias. Lee la base operacional de la capa analítica (`FUENTE_DATABASE_URL`, la de
`app/servicios/segmentos.py`); sin ella, el resumen dice «sin_fuente». Un candado de asesoría de la transacción
(`CLAVE_CONSOLIDADOS`) serializa el paso entre dos ejecuciones que cierran a la vez (la madre de un día y un ciclo sin
partir): la segunda lee desde la marca que dejó la primera. Se toma después del candado del modelo, en el mismo orden
en el ciclo y en la madre, así que no hay interbloqueo.

Por cada tabla (`timbradas_consolidado`, `timbradas_segmentos_anio`, `timbradas_segmentos_consolidado`), en un punto
de guardado de la transacción del ciclo:

1. **Lectura incremental** con su marca de agua (`ai_frecuencias.marca_agua_tabla`, por proceso y tabla) y la regla
   exacta de `fuentes.FuentePostgresSoloLectura` (READ ONLY, `statement_timeout`, solape y huellas de contenido, que
   descartan el resellado sin cambios del cierre nocturno, H7). La marca nueva se guarda en la MISMA transacción del
   ciclo: un intento revertido no la mueve, nunca retrocede y su `execution_id` cambia solo si la movió.
   **Solo el proceso de la fuente** (`FUENTE_PROCESO`, `sobusa` por omisión): las tablas con columna `proceso`
   (`fuentes.TABLAS_CON_PROCESO`) se leen con `… WHERE ultima_actualizacion > :marca AND proceso = :proceso ORDER BY
   ultima_actualizacion LIMIT …`, una variante fija de la lista blanca con el proceso como parámetro enlazado. En la
   base de Extreme hay filas de otros operadores (las tablas por segmento son de `cootransoriente`, H4): esas filas no
   se leen, no entran en las huellas que se guardan en `marca_agua_tabla.estado_fuente` ni mueven la marca, y
   `lectura.leidas` cuenta solo las del proceso. Para Sobusa el resultado es el mismo que antes (en la réplica, las
   10.731 filas y la misma marca:
   `tests/replica/test_consolidados.py::test_la_lectura_filtra_el_proceso_en_el_sql_sin_cambiar_lo_de_sobusa`). Con
   `FUENTE_PROCESO=*` se leen todos los operadores, como antes.
   **Sin filas que contrastar, sin otra consulta**: cuando la lectura no trae nada, el resultado lo decide lo que ya
   hizo la lectura, sin el `count(*)` por tabla y proceso que se hacía en cada ejecución (en la base de Extreme no hay
   índice sobre `proceso` ni sobre `ultima_actualizacion`, H12: en las tablas grandes por segmento era un barrido
   completo por ciclo). Sin marca previa y sin filas leídas, la lectura empezó en la marca inicial (toda la tabla, solo
   el proceso) y no trajo nada: `sin_filas_fuente` (H4 en las de segmentos; la tabla no tiene filas del proceso con
   `ultima_actualizacion`). Con marca previa (la tabla ya entregó filas del proceso) o si la ventana solo trajo
   repetidas: `sin_cambios`. El resumen ya no trae `filas_fuente`. Medido en la réplica
   (`docs/evidencias/replica/indices_candidatos.md`, escenario del índice por proceso): el `count(*)` retirado y la
   lectura incremental del proceso, con y sin índice.
   **Antes y ahora, medido** (`scripts/replica_lectura_consolidados.py`,
   `docs/evidencias/consolidados/lectura_por_proceso.md`): en una ejecución sin novedades, cada tabla pasa de dos
   consultas a la fuente (la lectura sin filtrar el proceso y el `count(*)`) a una. En la réplica las tablas por
   segmento están vacías (H4), así que el volumen de otro operador se mide con una tabla TEMPORAL que, dentro de una
   transacción que se revierte, tapa a `timbradas_segmentos_consolidado` en esa sesión: 1.384.299 filas de
   `cootransoriente` (las de `timbradas_consolidado` de Sobusa por sus 129 segmentos promedio por ruta), todas con el
   sello del cierre (H7). Antes, cada ejecución leía 500.000 de esas filas (el límite de la lectura), las traía a la
   API (unos 6 s), calculaba sus huellas (unos 7 s) y guardaba 500.000 huellas en `marca_agua_tabla.estado_fuente`
   (unos 35 MB de JSON), porque con el sello del cierre toda la tabla cae en la ventana de solape; ahora la lectura no
   trae ninguna fila y no se guarda ninguna huella. La lectura sigue recorriendo la tabla en el servidor (sin índice
   sobre `proceso` ni sobre la marca, H12); lo que se quita es el segundo recorrido y las filas ajenas. La tabla real no
   se toca (sigue con 0 filas y 16 kB). En la misma transacción se midieron dos índices candidatos creados sobre la
   temporal: con el de la marca sola la lectura del proceso sigue recorriendo la tabla (todas las filas ajenas son
   posteriores a la marca inicial, y sin filas del proceso no hay marca guardada); con el de (`proceso`,
   `ultima_actualizacion`) baja a centésimas de milisegundo. Por eso la propuesta para el DBA
   (`docs/evidencias/replica/propuesta_indices.sql`, índice 6) trae ese índice para `timbradas_segmentos_anio` y
   `timbradas_segmentos_consolidado`; el de `timbradas_consolidado` (índice 4, Sobusa sí tiene filas) sigue por la
   marca, y el de proceso y marca es su alternativa si la tabla trae varios operadores
   (`docs/evidencias/replica/indices_candidatos.md`).
2. **Calidad** de §6.3 sobre las filas leídas (`calidad.validar_lote`, esquemas `consolidado`, `segmentos_anio` y
   `segmentos_consolidado`):
   - CONS-001: promedio = Σ / `nro_viajes` exacto (1 %) o el `CEIL` que escribe `fn_consolidar_timbradas_historicas`
     (H7), para subidas, bajadas y pasajeros;
   - REL-004 (el segmento existe), REL-006 (el segmento es de la ruta de la fila, `rutas_segmentos.idruta`) y REL-007
     (el día existe en `dias_semana`);
   - VAL-007: `id_dia_semana` es el día ISO de la fecha o, sin fecha, uno de los días en que caen las fechas de su
     estacionalidad (`estacionalidades_anio`): un festivo de un solo día solo admite el día ISO de cada año;
   - VAL-008: la hora es la del bloque que empieza en `hora_inicio`;
   - `pasajeros` por segmento puede ser negativo (H9): se valida como número, no como conteo;
   - UNI-001 (llave natural duplicada): las filas se rechazan del análisis y **se reportan al responsable del
     consolidado** (§6.3 «reportar al responsable del consolidado; no corregir directamente», fila 6.3-06) igual que
     las del lote del ciclo: `consolidados._procesar_filas` llama a `ejecucion.reportar_unicidad` con el lote
     `id8:tabla`, así que el reporte sale por el mismo canal de correo (`NOTIF_UNICIDAD_DESTINATARIOS`; sin
     destinatario queda «pendiente_destinatario»), con el mismo formato (cada llave con sus filas y la ruta de la API
     que lista los errores) y queda en `notification_log` en la transacción del ciclo (el punto de guardado de la
     tabla: si la tabla falla, el reporte se revierte con ella). El resumen de la tabla trae `reporte_unicidad`
     (`tests/integracion/test_consolidados_ciclo.py::test_los_duplicados_de_un_consolidado_se_reportan_al_responsable`,
     `tests/unit/test_consolidados.py::test_los_duplicados_de_un_consolidado_se_reportan_al_responsable`). Una llave
     que la lectura incremental deduplicó (con columnas nulas en la llave, que UNIQUE permite) vuelve con todas sus filas
     a la calidad (`consolidados._con_las_llaves_repetidas`, `fuentes.filas_de_llaves_repetidas`): sale como UNI-001, sin
     elegir una, y se reporta; el resumen de la tabla trae `lectura.duplicadas_llave` y «filas» cuenta esas filas
     (`tests/unit/test_consolidados.py::test_una_llave_que_la_lectura_deduplico_vuelve_a_la_calidad_y_se_reporta`).
     Se reporta una sola vez: si la ventana de solape vuelve a traer la llave sin cambios, la tabla sale «sin_cambios», sin
     otro UNI-001 ni otro aviso
     (`tests/unit/test_consolidados.py::test_una_llave_repetida_ya_reportada_no_se_reporta_en_cada_ciclo`).
3. **Contraste con la agregación propia** de las llaves que tocó lo leído (sumadas en la fuente con un SELECT
   constante de la lista blanca):

   | Tabla | Grano de la comparación que puede bloquear | Agregación propia | Código |
   |---|---|---|---|
   | `timbradas_consolidado` | ruta × día ISO × estacionalidad | `demanda_observada` (pasajeros, `bajadas_viajes`, salidas) en el período del consolidado | CONTR-001 |
   | `timbradas_segmentos_consolidado` | segmento × día ISO × estacionalidad | `segmento_estadistica_dia` (agregación materializada del trabajo «segmentos») | CONTR-002; por hora, solo CONTR-003, que no bloquea |
   | `timbradas_segmentos_anio` | segmento × año × día ISO × estacionalidad | `segmento_estadistica_dia` por año | CONTR-002; por hora, solo CONTR-003, que no bloquea |

   Medidas, que no dependen de cuántos días cubre cada lado: promedio de subidas, de bajadas (y de pasajeros, en
   segmentos) por viaje y **viajes por día de operación**. Los días de cada lado dependen de la tabla
   (`dias_viajes_por_dia` en el resumen):
   - `timbradas_consolidado`: los días del calendario del período con ese día ISO y esa estacionalidad (la vigente de
     período más corto, como en `fn_insert_timbradas_anio`) frente a las fechas propias. Los años cerrados de
     `timbradas_anio` están completos y el histórico propio puede empezar después.
   - Tablas por segmento: los días de la agregación propia de la misma llave, en los dos lados: sus fechas distintas
     (`COUNT(DISTINCT fecha)`; sin la hora, una fecha trae una fila por cada hora de paso). Las tablas de Extreme
     (script 6 y `fn_insert_timbradas_anio`) y `segmento_estadistica_dia` salen de `timbradas_segmentos` y cubren las
     mismas fechas. Con el calendario, un año en curso o un histórico de segmentos que empieza a mitad de año (en la
     réplica, `timbradas_segmentos` solo trae 2023-01-01 a 2023-02-27) contaría días sin viajes de ningún lado y daría
     diferencias groseras falsas con los mismos datos. El año abierto de `timbradas_segmentos_anio` (el de la marca
     más reciente de Extreme) no compara los viajes por día, porque el refresco propio puede ir un ciclo atrás; sus
     promedios por viaje, sí.

   El período de `timbradas_consolidado` son los años cerrados que suma `fn_consolidar_timbradas_historicas`: del
   primer año de `timbradas_anio` al anterior al de su `ultima_actualizacion` (2023-2025 en la réplica).

   **Ninguna de las tres se contrasta por hora (H10).**
   - `timbradas_consolidado` asigna cada viaje al bloque de su fin y el histórico, a la hora de salida. En la réplica,
     el promedio por viaje por ruta × día × hora difiere 20,6 % en la mediana frente a la hora de salida y 1,3 % frente
     a la hora de fin; por ruta × día ISO × estacionalidad, 1,4 % (subidas) y 1,3 % (bajadas).
   - Las dos tablas por segmento tienen el mismo problema: `fn_insert_timbradas_anio` pone TODOS los segmentos de un
     viaje en el bloque de 15 minutos de su fin, y la agregación propia los tiene en la hora en que el bus pasó por
     cada segmento. Medido con filas reales de la liquidación de tres viajes
     (`docs/evidencias/consolidados/segmentos_filas_reales.json`): con la hora en el grano, 100 de las 162 llaves no
     encuentran la agregación propia y salen 129 diferencias groseras falsas, que dejarían 56 llaves fuera del
     análisis; sin la hora, las 90 llaves se comparan y no hay ninguna grosera. Por eso la comparación que puede
     bloquear (CONTR-002: promedios por viaje y viajes por día) suma los bloques de Extreme sin la hora.
   - **Por hora solo queda el rango (CONTR-003)**: el promedio por viaje de cada bloque de Extreme, sumado por hora,
     fuera del [mínimo, máximo] por viaje que la agregación propia vio en esa hora. Nunca bloquea, porque el bloque de
     Extreme puede ser otro, y su llave sí lleva la hora. Un bloque de Extreme sin agregación propia en esa hora no es
     una incidencia: solo se cuenta (`contraste.por_hora.sin_agregacion_propia`). Con muy pocos viajes el rango es
     estrecho y la diferencia de asignación lo saca con facilidad: 44 fuera de rango, ninguno bloqueante, en la prueba
     de los tres viajes con el mínimo en 1. Con el mínimo de viajes por defecto (30 de cada lado) no está medido,
     porque las tablas no tienen filas de Sobusa (H4).

   Si el histórico propio no trae ninguna estacionalidad (H1), los dos lados se suman sin ella, en los dos granos.
4. **Registro** en `data_quality_error`: lote `id8:tabla`, llave (las columnas del grano y el proceso), campo, valor de
   Extreme, detalle con el valor propio, la diferencia y la tolerancia, y `bloqueante`: no bloqueante sobre
   `contraste_tolerancia` (0,15) y bloqueante, la llave queda fuera del análisis, sobre `contraste_tolerancia_grosera`
   (0,50); con menos de `contraste_viajes_minimos` (30) viajes de un lado la llave no se compara. Las tres viven en
   `threshold_config` (migración 0013) y se cambian con `PUT /api/v1/thresholds`, que exige
   0 < tolerancia <= grosera <= 10 y un entero >= 1. Se guardan a lo sumo 2.000 incidencias por tabla y ejecución
   (primero las bloqueantes); el resumen cuenta todas. `GET /api/v1/frequency/executions/{id}/errors` las filtra por
   `lote`, `codigo` y `bloqueante`, y las de `timbradas_consolidado` también por `idruta` (su llave trae `id_ruta`;
   las de segmentos traen `id_segmento`). La llave de un CONTR-002 por segmento ya no lleva la hora; la de un
   CONTR-003, sí. Las filas de ejecuciones anteriores, con la hora en la llave de CONTR-002, siguen ahí hasta que la
   retención las borre: la llave es un JSON libre y la API las lista igual
   (`tests/integracion/test_consolidados_ciclo.py::test_una_incidencia_vieja_con_la_hora_en_la_llave_se_sigue_listando`).
5. **Resumen** en `metricas.calidad.consolidados` de la ejecución: por tabla, el resultado (`contrastado`,
   `sin_cambios`, `sin_filas_fuente`, `sin_fuente` o `error`), las marcas anterior y nueva, la lectura, los errores por
   código, las incidencias registradas, el contraste (grano, nota del grano, período, llaves, comparadas, sin
   agregación propia, diferencias, groseras y llaves bloqueadas) y, si hubo duplicados, `reporte_unicidad`. En las
   tablas por segmento, `contraste.por_hora` trae lo del rango: su grano (con la hora), los bloques de Extreme, los
   comparados, los que no tienen agregación propia en esa hora y los que quedaron fuera de rango. Sin filas del
   proceso lo dice explícitamente; en las de segmentos, con el hallazgo H4.

Una tabla que falla (la fuente se cae, un error de datos) no detiene el ciclo: se revierte solo su punto de guardado,
su marca no se mueve, queda como fallo parcial de la ejecución y la siguiente la vuelve a leer.

## 4. Resultado con los datos reales (réplica local, solo lectura)

`python -m scripts.contraste_consolidados` (`docs/evidencias/consolidados/contraste_consolidados.md`):

- `timbradas_consolidado`: 10.731 filas leídas, 10.731 válidas (ningún falso error de las reglas nuevas); la segunda
  lectura descarta las 10.731 por huella.
- Contraste con el histórico de la serie empaquetada 2023-2025: 174 llaves, 160 comparadas, 31 incidencias y 11
  groseras. Las groseras dicen algo de los datos de Extreme: las bajadas de la ruta 21 (total +58 %, promedio por
  viaje +60 % los miércoles y jueves) y los festivos de un día, con el doble de viajes por día que los viajes válidos
  de esas fechas; los lunes corrientes traen 17 a 19 % más viajes por día. Son preguntas para Extreme, no errores del
  contraste: los promedios de subidas cuadran (mediana 1,4 %). La sección «De dónde salen las diferencias groseras de
  viajes por día (H17)» de la evidencia lo mide en la réplica: los cinco festivos de 2025 con dos filas en
  `estacionalidades_anio` (ids 1 a 4 y 169 a 172, y el 30 de junio con San Pedro y Sagrado Corazón) aparecen con las
  dos en `timbradas_anio`, cada una con los viajes aptos de la fecha; y `DIAS_CORRIENTES` suma de 3,2 a 4,2 % más
  viajes que los aptos de los días corrientes en cada ruta y año.
- `timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`: 0 filas de Sobusa (H4); el ciclo lo registra.

Con filas reales de la liquidación (`tests/replica/test_consolidados_segmentos.py`, con
`REPLICA_PRUEBAS_ESCRITURA=1`; `docs/evidencias/consolidados/segmentos_filas_reales.json`). En una transacción de
`extreme_dba` que se revierte llegan por el trigger tres viajes reservados, `fn_insert_timbradas_anio` los liquida y
`fn_consolidar_timbradas_historicas` cierra. Sobre esas filas corre el contraste del ciclo sin cambiarle nada
(`consolidados._contraste_de`), con la agregación propia de las mismas filas de `timbradas_segmentos`:

- Las 162 filas de cada tabla pasan la calidad de §6.3 sin errores, y los totales cuadran (223 frente a 224 viajes
  por segmento; 200 frente a 201 subidas).
- Las 90 llaves se comparan: 5 diferencias sobre la tolerancia, ninguna grosera y ninguna llave bloqueada. Con la
  hora en el grano salían 129 groseras falsas y 56 llaves bloqueadas.
- Esas 5 diferencias tienen causa medida. Salen en 2 segmentos (`segmentos_con_diferencias`), y los dos están entre
  los 5 donde un viaje tiene dos filas en `timbradas_segmentos`, porque pasó por el segmento en dos bloques de 15
  minutos (`segmentos_con_un_viaje_en_dos_bloques`; la prueba exige que no salgan en ningún otro). De ese par
  (segmento, viaje) la liquidación de Extreme cuenta un viaje y deja los conteos de una sola fila (200 de las 201
  subidas). La agregación propia suma las dos filas y, si caen en horas distintas, cuenta el viaje en cada hora (224
  frente a 223). Con solo tres viajes, una fila de diferencia ya pasa la tolerancia.
- Por hora: de los 162 bloques de Extreme, 100 no tienen agregación propia en esa hora; de los 62 comparados, 44
  quedan fuera de rango (CONTR-003), ninguno bloqueante.
- La diferencia real sigue saliendo: con las subidas de un segmento alteradas dentro de la misma transacción, esa
  llave, y solo esa, queda bloqueada (CONTR-002 `promedio_subidas`).
- Con las tolerancias por defecto (30 viajes de cada lado) tres viajes no alcanzan para comparar nada; la prueba
  baja `contraste_viajes_minimos` a 1.

`python -m scripts.replica_lectura_consolidados` (`docs/evidencias/consolidados/lectura_por_proceso.md`): lo que el
ciclo le consulta a la fuente por tabla en una ejecución sin novedades, antes y ahora (sección 3, «Antes y ahora,
medido»), con las tablas reales y con el volumen de otro operador en la tabla temporal.

## 5. Pruebas

| Qué | Dónde |
|---|---|
| Contraste puro, tolerancias, calendario, medidas, sin estacionalidad, sin fuente; por segmento, el grano sin la hora, los bloques en la hora del fin del viaje sin groseras falsas (H10), la diferencia real sembrada y el rango por hora que no bloquea | `tests/unit/test_consolidados.py` |
| Calidad de los consolidados (CEIL, segmentos, REL-006, REL-007, VAL-007, VAL-008) | `tests/unit/test_calidad_consolidados.py` |
| Lectura integrada con `bajadas_viajes`, `para_tabla`, catálogos del día, fuente offline con bajadas | `tests/unit/test_fuentes.py`, `tests/unit/test_datos.py` |
| COPY y upsert con las medidas opcionales | `tests/unit/test_ingesta.py` |
| ALT-008 con bajadas en su frontera | `tests/unit/test_alertas_observadas.py` |
| El paso del ciclo contra un esquema sintético: calidad, contraste, marca, relectura, resellado, fila modificada, tolerancias de la versión, una tabla que falla, segmentos con los bloques de Extreme en la hora del fin del viaje (H10) y una incidencia vieja con la hora en la llave, ciclo sin partir y partido por ruta, PUT /thresholds, bajadas en el histórico y ALT-008, migración 0013; filas de otro proceso (no se leen, no entran en las huellas ni mueven la marca) y duplicados reportados al responsable | `tests/integracion/test_consolidados_ciclo.py` |
| La lectura por proceso en el SQL, `sin_filas_fuente` y `sin_cambios` sin consultar la fuente, el reporte de unicidad | `tests/unit/test_fuentes.py::test_la_lectura_incremental_de_los_consolidados_filtra_el_proceso_en_el_sql`, `tests/unit/test_consolidados.py` |
| La medición de antes y ahora: las consultas del ciclo, la tabla temporal en la transacción que se revierte, nada sobre `public` | `tests/unit/test_replica_lectura_consolidados.py` |
| Convivencia con la capa de segmentos (la madre lee los consolidados, una vez) | `tests/integracion/test_convivencia_ciclo_segmentos.py` |
| Réplica, solo lectura: consolidado real, H4, linaje de las bajadas empaquetadas, lectura integrada, H10, definición de bajadas, la lectura por proceso igual a filtrar después | `tests/replica/test_consolidados.py` |
| Réplica, en una transacción que se revierte (`REPLICA_PRUEBAS_ESCRITURA=1`): el contraste del ciclo con filas reales de la liquidación, sin groseras falsas, y la diferencia sembrada | `tests/replica/test_consolidados_segmentos.py` |
| Backtest de ALT-008 reproducible | `tests/datos_ml/test_backtest_alertas.py` |

## 6. Límites

- Las tablas por segmento están vacías para Sobusa (H4): en la base de Extreme el contraste por segmento todavía no
  ha corrido con filas de Sobusa. Está probado con filas sintéticas y, en la réplica, con filas reales de la
  liquidación de tres viajes en una transacción que se revierte (sección 4). Cuando Extreme las llene, el bloque de
  esas tablas depende de quién las escribió (el script 6 usa el bloque de cada fila; `fn_insert_timbradas_anio`, el
  del fin del viaje: H10). La comparación que puede bloquear no depende de ese bloque; el rango por hora (CONTR-003)
  sí puede mostrar diferencias de asignación, no de conteo, y por eso no bloquea. Además, el script 6 cuenta en
  `nro_viajes` una vez por bloque de 15 minutos (un viaje que cruza el segmento en dos bloques cuenta dos veces) y la
  agregación propia, una vez por viaje y hora (errata E2): con datos del script 6, los viajes por día y los promedios
  por viaje pueden diferir por esa definición. Con filas de `fn_insert_timbradas_anio` pasa algo parecido, medido en
  la sección 4: de un viaje con dos filas del mismo segmento Extreme deja los conteos de una sola, y la agregación
  propia, sin la hora, lo cuenta dos veces si las dos filas caen en horas distintas.
- Volumen: con millones de filas por segmento, la suma de las llaves tocadas sale de la fuente en un SELECT; el
  `statement_timeout` de `FUENTE_STATEMENT_TIMEOUT_MS` y el tope de 2.000 incidencias por tabla protegen el ciclo.
  Un resellado completo del cierre nocturno sin cambios no se reprocesa (huellas), pero uno con cambios vuelve a
  contrastar las rutas o los segmentos tocados.
- El período del consolidado se deduce de `timbradas_anio` y de la marca de la fila (la regla de
  `fn_consolidar_timbradas_historicas`); si Extreme consolida de otra forma, la medida de viajes por día lo mostraría.
- Los consolidados no alimentan el modelo (su objetivo es el histórico propio): «bloqueante» marca la llave como no apta
  para el análisis y queda para el responsable del consolidado (§6.3); no se corrige nada.
