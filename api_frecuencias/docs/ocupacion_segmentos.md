# Ocupación por segmento, histórica y actual (§10.1)

§10.1 de la especificación v1.5 pide dos variables de decisión del optimizador:

- **10.1-c** «Ocupación histórica de los buses por segmento, estacionalidad, día de la semana y rango de horas».
- **10.1-d** «Ocupación actual por segmento, estacionalidad actual, día de la semana y hora».

Este documento dice cómo las mide la API, de dónde sale cada cifra, cómo las usa el optimizador y qué no se puede
afirmar con los datos que hay. El código está en `app/servicios/ocupacion.py`. Las evidencias están en
`docs/evidencias/ocupacion/`.

## 1. Por qué no sirve `timbradas_segmentos.pasajeros` y qué se usa en su lugar

El trigger de Extreme guarda en `pasajeros` la resta `acumulada_subida − acumulada_bajada` de los contadores
**acumulados del dispositivo** (hallazgo H9 de `docs/hallazgos_extreme.md`). No es la ocupación del bus: el 32 % de
las filas son negativas y la mediana es 4.380.

Las **subidas y bajadas** por segmento de cada viaje, en cambio, son conteos del viaje. En los 26.350 viajes del perfil
suman exactamente lo que cuenta el dispositivo: Σ subidas 2.241.832 en los dos lados, y lo mismo las bajadas. §11.1
permite «hacer en la capa analítica propia cualquier transformación adicional». Con eso la carga a bordo se deriva
en la capa propia, sin tocar el trigger.

## 2. Método (el mismo para el histórico y para el ciclo)

`ocupacion.cargas_por_segmento` y `ocupacion.cargas_en_el_tramo`:

1. **Unidad**: un viaje (`id_viaje` = `progvehiculos.idprogramacion`) en un segmento. Si el viaje cruza el segmento
   en dos bloques de 15 minutos (errata E2), se suman sus subidas y sus bajadas.
2. **Orden**: los segmentos del viaje por `nro_segmento`. Cada ruta es un ciclo (ida y regreso) que empieza en el
   segmento 1.
3. **Carga** al salir del segmento k: `carga_k = max(0, carga_(k−1) + subidas_k − bajadas_k)`, con carga 0 al
   empezar. Es la suma de (subidas − bajadas) de los segmentos 1..k, acotada en 0 en cada segmento. La API usa la
   forma cerrada `S_k − min(0, min_{j≤k} S_j)`.
4. **Tramo del viaje**: el viaje cuenta en los segmentos entre el primero y el último que registró. En un segmento sin
   eventos la carga es la del anterior.
5. **Segmento crítico del viaje**: el primero que alcanza su carga máxima. **Segmento crítico de una franja**: el de
   mayor carga media entre los viajes de esa franja.
6. **Ocupación** = carga / puestos por bus. Se usan los puestos con que el plan dimensiona: el ajuste local gobernado
   (`PUT /catalogos/capacidad`) o los 50 del catálogo.
7. **Sentido aproximado**: «ida» si el punto medio del segmento cae en la primera mitad de la longitud acumulada del
   ciclo, «regreso» si no. Es la regla de `scripts/preparar_segmentos.py`; una prueba comprueba que da el mismo
   sentido para los 386 segmentos.

### Por qué se acota en cada segmento

El trigger asigna cada evento al segmento **más cercano**. Donde la ida y el regreso van por la misma vía, algunos
eventos caen en el segmento del otro sentido, y al ordenar por `nro_segmento` aparece una bajada antes de su subida.

La suma sin acotar baja de −3 en el 21,9 % de los viajes; en el dispositivo, ordenado por la hora del evento, en el
18,0 %. Sobre los mismos 21.511 viajes con contadores consistentes, la carga máxima por viaje se comparó con la
ocupación máxima del dispositivo (`conteo_viajes.ocupacion_max`):

| Variante | Correlación | Razón mediana |
|---|---|---|
| Acotada en 0 en cada segmento (la que usa la API) | 0,961 | 0,952 |
| Literal max(0, Σ subidas − bajadas) | 0,930 | 0,933 |

La variante acotada en cada segmento se acerca más al dispositivo, y por eso es la que usa la API. Queda unos 5 %
por debajo: la agregación por segmento esconde picos dentro del segmento.

## 3. Histórico (10.1-c)

- **Script**: `scripts/preparar_ocupacion_segmentos.py`. Lee las exportaciones (carpeta `datos/` de la raíz,
  git-ignorada); nada sale de la base del reto. Viajes del perfil: válidos, limpios (R3: 30 a 360 min y 1 a 300
  pasajeros) y con un tramo registrado de al menos el 50 % de la ruta. Son 26.350 de 27.025.
- **Archivo versionado**: `datos/ocupacion_segmentos_hora.parquet` (64.848 filas, 0,5 MB). Tiene una fila por ruta ×
  segmento × estacionalidad × nivel × hora de salida, con viajes, días, carga media, P50, P90 y máxima, y los viajes
  de los que fue el segmento crítico. Hay dos niveles:
  - `dia_semana`: el día de operación ISO. Los domingos y los festivos van juntos en el 7, igual que el tipo de día
    «Domingo/festivo» de D5.
  - `tipo_dia`: el respaldo cuando la celda del día tiene menos de 4 días o menos de 20 viajes.
- **Estacionalidad**: la columna existe y el perfil agrupa por ella. Para Sobusa es nula, porque las filas de
  `estacionalidades_anio` son de otro proceso (hallazgo H1). Cuando Extreme la entregue, basta con volver a correr
  el script.
- **Periodo**: solo 2023-01-01 a 2023-02-27, lo único que llenaron los triggers de segmentación.

### El factor de carga 2025: de dónde sale y su desagregación por día de la semana

El factor de carga crítica que usa el optimizador (carga del tramo más cargado / abordajes de la hora) es la mediana
de `L_real / real` en `datos/insumos_d5_2025.parquet`, en las horas con más de 20 abordajes.

- `L_real` = mediana de `conteo_viajes.ocupacion_max` de los viajes con contadores consistentes (R9) × viajes válidos.
  Lo calcula `experimentos/D1_optimizacion/run.py` con `carga_max` de `experimentos/E1_lgbm_salida/run.py`.
- `real` = Σ `numeropasajeros` de los viajes válidos.

El archivo trae la fecha de cada fila, así que la mediana se puede tomar por **día de la semana**. Con al menos 10
días por celda hay 355 celdas ruta × día de operación × hora; por tipo de día hay 151. Entre los días laborales de una
misma ruta y hora, el factor cambia en promedio 0,034 y como máximo 0,095.

`optimizacion.factor_carga_franja` usa ahora la celda del día de operación de la fecha (nivel `dia_semana`). Si esa
celda tiene menos de 10 días, o no hay fecha, usa la de antes por tipo de día (nivel `tipo_dia`). La salida dice qué
nivel se usó. Un festivo usa el día 7.

### Comparación con el factor 2025 (ruta × tipo de día × hora, 150 franjas)

| Comparación | Error absoluto medio | Sesgo | Correlación |
|---|---|---|---|
| Segmentos frente a dispositivo, mismos viajes, ene-feb 2023 | 0,029 | −0,028 | 0,93 |
| Dispositivo ene-feb 2023 frente al factor 2025 | 0,033 | −0,024 | 0,85 |
| Factor 2025 ene-feb frente al factor 2025 de todo el año | 0,019 | 0,000 | 0,91 |
| Segmentos ene-feb 2023 frente al factor 2025 | 0,062 | −0,060 | 0,80 |

La carga por segmentos y la del dispositivo cuentan lo mismo en los mismos viajes: la diferencia es de 0,03. El factor
de 2025 es unos 0,02 mayor que el de 2023, y ene-feb no se aparta del resto de 2025. Por eso el optimizador sigue
usando el **factor 2025 del dispositivo** (un año completo y reciente). Del perfil por segmentos toma el **segmento
crítico** y su ocupación, que el factor no tiene.

### Uso en el optimizador

- **Franja (§10.2)**: `recomendacion_franja` agrega `ocupacion_historica` (segmento, sentido, km, carga media, P50, P90
  y máxima, ocupación con los puestos de la recomendación, viajes, días y nivel). También agrega su frase al final de
  la explicación, por ejemplo: «Segmento crítico histórico de la franja: el 28 (ida, desde el km 13,5), con 44,8
  pasajeros a bordo en promedio al salir de él (90 % de 50 puestos; P90 57,0, 114 %) en 198 viajes de 7 días (los
  miércoles a las 6:00, 2023-01-01 a 2023-02-27); fue el tramo más cargado del 31 % de esos viajes». `POST
  /recommendations/calculate` lo devuelve.
- **Plan del día**: cada hora trae `ocupacion_historica`, y `GET /recommendations/plan` la devuelve. El factor de cada
  hora es el del día de la semana de la fecha del plan.

## 4. Actual (10.1-d)

### Lectura en el ciclo

Después del monitoreo y antes de las predicciones, el ciclo de frecuencia (`ejecucion._ocupacion_actual`) toma las
franjas (ruta, fecha, hora de salida) que acaba de entregar la lectura incremental en las últimas 24 h de cada ruta,
contadas hacia atrás desde su franja más reciente (`ocupacion.franjas_del_lote`), y de ellas solo las horas ya
cerradas a la referencia del ciclo (`cerradas_hasta`: inicio + 1 h <= referencia). La hora en curso no se lee ni se
guarda: ni la restricción reactiva ni ALT-002 la usan, y sus viajes siguen llegando, así que el ciclo siguiente la trae
otra vez en su lote. No basta el último día del lote: si la captura es en vivo, el ciclo programado de las 5:15 ya trae
la franja de las 4 h del día en curso, y con solo ese día nunca mediría ni guardaría el día que acaba de terminar. Lo
anterior a la ventana (la carga inicial o un dato tardío) no se relee viaje por viaje. Las alertas observadas también
evalúan cada día del lote (`ejecucion.contextos_observados`), cada uno con sus horas cerradas: ALT-002 del día que
acaba de terminar se mide en su segmento crítico aunque el lote cruce la medianoche. Esas franjas se leen viaje por
viaje con `FuentePostgresSoloLectura.leer_carga_segmentos`:

- es un SELECT constante de la lista blanca (`_SQL_CARGA_SEGMENTOS`) en la transacción READ ONLY de siempre, con
  `statement_timeout` y como `lector_ia`;
- las franjas van como tres arreglos enlazados;
- trae los viajes no cancelados de la franja, con sus subidas y bajadas por segmento, el vehículo y el conductor;
- el conductor se **seudonimiza al leer** (`seudonimizar_conductores`, HMAC con `SEUDONIMO_SECRETO`, §18); sin
  secreto queda vacío, y el dato en claro nunca sale de la capa de lectura.

La lectura depende de las franjas entregadas, no de una marca propia. Por eso convive con la marca de agua por ruta
(RNF-005): en una ejecución partida, cada trabajo de ruta lee solo las franjas de su ruta (lo prueba
`tests/integracion/test_ocupacion_ciclo.py`). Sobre la réplica, como `lector_ia`, las 4 franjas de la prueba se leen en
cerca de 1 s, y un día completo de las tres rutas (51 franjas, unas 60.000 filas viaje × segmento de 560 a 590
viajes) en unos 2,1 s, lejos del `statement_timeout` de 30 s y del límite de 500.000 filas. El costo lo domina el
recorrido de `timbradas_segmentos`, que no tiene índice por `id_viaje` (H12), igual que en la lectura de demanda.

En modo offline (`FuenteParquet`) no hay viajes por segmento. El ciclo lo dice en `metricas.ocupacion_segmentos.nota`
y sigue igual que antes.

### Dónde queda

En `ai_frecuencias.ocupacion_segmento` (migración 0011): una fila por ruta × fecha × hora de salida × segmento, con:

- viajes medidos, carga media y máxima, puestos y ocupación media y máxima;
- el viaje de la carga máxima y el sentido aproximado;
- `id_dia_semana` ISO de la fecha e `id_estacionalidad` actual: la que trae el lote de la lectura integrada para esa
  franja (`estacionalidades_anio` vigente en la fecha, la misma de `demanda_segmentos`) o, si el lote no la trae, la
  dimensión de §8.3 (nula para Sobusa con las exportaciones, H1);
- la marca `critico`, en el segmento de mayor carga media de la franja.

Una franja releída se borra y se vuelve a escribir en la misma transacción del ciclo: nunca queda duplicada ni a
medias. Las métricas de la ejecución dicen cuántas franjas, viajes y filas se escribieron.

### Uso: ALT-002 observada

Si una hora cerrada trae su segmento crítico con al menos `salidas_minimas_ocupacion` viajes medidos, ALT-002 mide la
ocupación **ahí**. Si no, la estima como antes, con el factor de carga. `variables.metodo_ocupacion` dice cuál se usó.
La alerta trae el segmento, el sentido aproximado y el viaje, el vehículo y el conductor (solo seudónimo) del viaje
más cargado (§5.3), y lo declara en `variables.identificacion_5_3` con la variante `segmento_critico`
(`alertas.VARIANTES_5_3`; con el factor de carga, la de la ruta, sin viaje ni sentido). Las horas de borde no se
evalúan con ningún método.

Cada hora lleva la medición de este ciclo o, si su lote no la trajo, la última que guardaron los ciclos anteriores en
`ocupacion_segmento` (`ejecucion.ocupacion_del_dia`; esa no trae el viaje más cargado, que la tabla no guarda
completo). Con la llegada progresiva de los ciclos intradía cada lote trae la hora que acaba de cerrar: sin la
guardada, la hora anterior del episodio quedaba sin medir y ALT-002 no juntaba nunca sus horas de persistencia
(`tests/integracion/test_ciclo_tiempo_real.py::test_alt002_junta_su_persistencia_con_la_ocupacion_que_guardo_el_ciclo_anterior`).

### Uso: restricción reactiva en el plan del día

`ocupacion.restriccion_reactiva` arma la restricción y `optimizacion.plan_dia(ocupacion_actual=…)` la aplica.

- **Cuándo aplica**: la ocupación observada del segmento crítico en la **última hora cerrada** del día del plan
  alcanza `ocupacion_critica`, la de la versión de umbrales de la ejecución (en una ejecución partida, la fijada al
  crearla). Una hora está cerrada cuando todas sus salidas ya ocurrieron (antes de la hora del instante del ciclo) y
  su segmento crítico tiene al menos `salidas_minimas_ocupacion` viajes medidos. Sus viajes pueden ir todavía en curso
  (un viaje dura unas 3,5 h): la ocupación y la carga son las de los viajes que ya pasaron por el segmento, y la
  restricción dice cuántos viajes de la hora habían terminado (`viajes_terminados`).
- **Dónde aplica**: en la hora siguiente que todavía se puede programar. Es la siguiente a la cerrada, o la del
  instante si esa ya pasó, a lo sumo 2 h después de la cerrada y nunca después de las 20 h.
- **Qué exige**: `x_h >= ceil(carga crítica observada × min(minutos, 60) / 60 / (puestos × ocupación objetivo
  máxima))`. Es la fórmula de §10.3 con la carga observada. Queda acotado por el tope del headway mínimo y entra al
  MILP de D5 como cota inferior (piso) de esa hora.
- Si con el piso el MILP no tiene solución por la suavidad gobernada, el plan se resuelve sin él y la restricción
  dice que no se pudo aplicar. Nunca se entrega un plan infactible.
- **Qué muestra**: el resumen del plan trae `ocupacion_actual` (si aplicó, en qué hora, con qué salidas mínimas y la
  fórmula, o por qué no). La hora trae `restriccion_reactiva`, y si el piso manda, `ocupacion_observada` aparece en
  `limites_activos`. La formulación del plan la nombra, y las métricas del ciclo la resumen por ruta.
- **Solo dentro del día**: con el ciclo nocturno (datos hasta ayer, plan de hoy), la última hora cerrada es de otro
  día y la restricción no aplica; lo dice. Actúa en los ciclos intradía que encola el planificador cada hora
  (`PLAN_INTRADIA_CRON`, más abajo) y en una ejecución pedida con `instante` del mismo día (`POST
  /frequency/executions`).
- **La foto de la respuesta**: si la foto (`respuesta.precalcular`) tiene que volver a resolver el plan del ciclo
  porque el modelo activo cambió a mitad de la ejecución, lo resuelve con la misma restricción
  (`respuesta._reactiva_del_plan`): el piso no se pierde
  (`tests/unit/test_respuesta.py::test_el_plan_vuelto_a_resolver_conserva_la_restriccion_reactiva_del_ciclo`).

### Uso: recomendaciones de 30, 60 y 120 min y la recomendación a pedido

La misma restricción llega a la recomendación de la franja (`ejecucion.recomendacion_con_ocupacion`), que es la que
optimiza el MILP de §10.2:

- **Cuándo**: si la restricción de la ruta aplica y la hora principal de la ventana de la predicción es la hora en que
  actúa. En un ciclo de las 9:05 que actúa a las 9 h, las de 30 min (9:05-9:35) y 60 min (9:05-10:05) la reciben; la
  de 120 min (hora principal, las 10 h) no.
- **Qué exige**: `optimizar(buses_minimos=k)` sube la cota inferior del MILP a `k = ceil(carga crítica observada /
  (puestos × ocupación objetivo máxima))` con los puestos y la ocupación objetivo de la franja. Como en el plan, `k` no
  pasa del tope del headway mínimo; en la franja tampoco de lo que la flota sostiene con el ciclo (`floor(flota × 60 /
  ciclo)`), porque el MILP de la franja dimensiona la flota en régimen y el del plan sigue los buses en ruta cada 15
  minutos. Si con la flota de cada tipología `k` no es ejecutable, toma el mayor piso que sí lo es. La restricción
  `ocupacion_observada` aparece en `restricciones` y, si manda, en `limites_activos`; `salida.restriccion_reactiva`
  dice si se aplicó, las salidas pedidas, el piso, la fórmula y, si no se aplicó, por qué (ya cumplía, la flota no deja
  subir más o la franja no es viable ni sin piso). En la evidencia del planificador, a las 9:05 la carga de las 8 h pide
  15 buses/h: el plan del día pone 15 a las 9 h y, en la franja, la flota de cada tipología con el ciclo sostiene 9, así
  que las recomendaciones de 30 y 60 min suben de 6 a 9 y lo dicen (`limitada_por_flota`).
- **POST /predictions/run** (la recomendación a pedido) usa la ocupación actual que ya guardaron los ciclos para su ruta
  y su día (`ocupacion.reactiva_guardada`), solo la medida antes de su instante (`actualizado_en <= instante`): §9.3,
  ninguna variable posterior al instante, porque la medición de una hora se completa mientras sus viajes terminan. Así
  la recomendación a pedido de las 9:10 dice lo mismo que la del ciclo de las 9:05
  (`tests/integracion/test_ciclo_tiempo_real.py::test_la_recomendacion_a_pedido_usa_la_ocupacion_medida_antes_de_su_instante`).
- **POST /recommendations/calculate no la usa**: es la calculadora de §10.2 con la demanda, los parámetros, el escenario
  y la sensibilidad que trae la solicitud. Agregarle un piso que no está en la solicitud cambiaría sus cifras sin que
  quien pregunta lo pida; la ocupación observada de una franja ya está en su plan y en sus recomendaciones.

### El ciclo intradía programado (`PLAN_INTRADIA_CRON`)

El ciclo diario (5:15) no tiene `instante`: su plan es el del día siguiente, que todavía no tiene horas cerradas, así
que en la operación programada la restricción no actuaría nunca. El planificador tiene por eso un trabajo intradía
(`planificador.tarea_ciclo_intradia`): cada disparo de `PLAN_INTRADIA_CRON` encola una ejecución de frecuencia con
`instante` = la franja y `parametros.intradia`. Su plan es el del día EN CURSO y sus recomendaciones de 30, 60 y
120 min salen de la franja, con la ocupación de la última hora cerrada.

- **Idempotente con N réplicas**: el mismo `INSERT … ON CONFLICT` del ciclo diario sobre el índice único (tipo,
  `programada_para`); cada réplica dispara su planificador y solo la primera encola la franja. Una franja que coincide
  con la del ciclo diario no se encola (es del ciclo diario).
- **Partición por ruta y versión de umbrales** (RNF-005, §5.1): con `PLAN_PARTICION=ruta` la franja es la madre y, en
  la misma transacción, se encola un trabajo por ruta; la versión de umbrales queda fijada al crearla y la usan la madre
  y sus trabajos aunque llegue un `PUT /thresholds` antes de que corran.
- **Lo que no hace** (`ejecucion.NOTA_INTRADIA`): no evalúa el error del modelo, no guarda el monitoreo, la sombra ni
  la política (el día en curso está incompleto: con él, el error saldría inflado y la política decidiría con él), no lee
  los consolidados de Extreme y no pide el refresco de la agregación de segmentos. Esa agregación es una estadística
  histórica por día de la semana y hora: una hora más no la cambia de forma útil, y cada refresco recorre
  `timbradas_segmentos` (H12); la refrescan el ciclo diario y `PLAN_SEGMENTOS_CRON`, una vez al día. Sin datos nuevos
  desde la marca de agua no rehace predicciones, plan ni foto (sin ocupación nueva su plan sería el mismo): solo mide la
  frescura (ALT-009).
- **Bordes del día en curso**: la ocupación solo se mide en horas cerradas y las alertas observadas solo evalúan horas
  cerradas; una hora cerrada con viajes todavía en curso va sin pasajeros ni salidas (sus conteos no son definitivos), y
  ALT-009 solo cuenta como faltantes las horas anteriores a la última cerrada con registro, así que ninguna alerta sale
  por horas que todavía no pasaron. A las 20:05 la última hora programable es la de las 20 h: una medición de la
  mañana no la restringe y lo dice.
- **Sin duplicar alertas**: el mismo día se evalúa en cada ciclo intradía y otra vez en el diario. La clave de un
  episodio observado es su inicio, así que la redetección actualiza la alerta abierta. Si la racha empieza en otra hora
  de un ciclo al siguiente (por ejemplo, una hora anterior que el lote vuelve a traer y ahora también supera el umbral,
  o una hora que se completa después que la siguiente), la detección toma la clave de la alerta del mismo código y ruta
  cuya ventana se cruza o se toca con la suya (`ejecucion.clave_del_episodio`) y actualiza esa alerta en lugar de abrir
  otra por las mismas horas
  (`tests/integracion/test_ciclo_tiempo_real.py::test_un_episodio_de_alt002_que_empieza_antes_en_el_ciclo_siguiente_no_se_duplica`).
  Cuando la racha empieza antes, la alerta actualizada pasa a empezar en el inicio menor y la bitácora «redeteccion» guarda
  la ventana de antes y la de ahora, sin notificar dos veces
  (`tests/unit/test_ciclo_intradia.py::test_un_episodio_que_crece_hacia_atras_mueve_el_inicio_de_su_alerta`).
  Un episodio que el área operativa cerró no se reabre si la detección no le agrega nada
  (`ejecucion.episodio_ya_cerrado`).
- **Dos ciclos a la vez y una franja con el ciclo diario corriendo**: la cola no entrega dos trabajos de frecuencia
  cuyas particiones se cruzan (`cola._RECLAMAR`) y los candados de partición lo garantizan en la base: la franja espera
  y, al tomarla, lee desde la marca que dejó el otro.
- **Una franja que quedó atrás en la cola** (la cola estuvo detenida, RNF-001, o un trabajo largo la retrasó): si al
  entregarla ya espera otra franja planificada posterior, intradía o diaria (`ejecucion.franja_posterior_en_cola`), se
  cierra «ok» sin leer la fuente ni mover la marca de agua, y la posterior lee lo mismo con su instante. Así, después de
  una caída, no se corren uno tras otro ciclos de horas que ya pasaron, y una franja de las 20:05 que sigue en la cola a
  las 5:15 no le consume al ciclo diario los datos de la noche que necesita para cerrar el día completo.
- **Cambio de día**: el cron por omisión no cruza la medianoche; el ciclo diario de las 5:15 cierra el día anterior
  completo (alertas de cada día del lote, consolidado, monitoreo y política) y los ciclos intradía empiezan a las 6:05.
- **Retención** (§18): sus ejecuciones, predicciones, recomendaciones y fotos son filas como las del ciclo diario y la
  política de retención las borra por antigüedad igual. Cada ciclo intradía de tres rutas escribe 9 predicciones, 60
  recomendaciones (9 de franja y 51 del plan) y unas 1.176 filas de la foto de variables (la de cada predicción, con
  sus segmentos): con el cron por omisión, unas 15 veces lo del ciclo diario. La ocupación por segmento no crece: una
  franja releída reemplaza la anterior.

**Valor por omisión: activo, `5 6-20 * * *`** (America/Bogota), solo donde hay captura en vivo: el trabajo existe con
`FUENTE=postgres` y el planificador encendido (`PLANIFICADOR_HABILITADO`); con la serie empaquetada (`FUENTE=parquet`,
la demostración) no hay datos dentro del día y no se registra. Vacío lo apaga y una expresión más espaciada (por
ejemplo `5 6-20/2 * * *`) lo reduce, sin tocar el código. Por qué:

- **Cubre el servicio sin chocar con el diario**: una franja a las :05 de 6 a 20 h; la primera cuando ya cerraron las
  4 y las 5 h, después del ciclo diario (5:15) y del refresco de segmentos (5:45); la última actúa sobre las 20 h, la
  última hora de servicio (una a las 21:05 ya no tendría hora que programar). Con la hora cerrada en el minuto 0, las
  :05 dejan llegar las últimas salidas de esa hora.
- **Duración** (`docs/evidencias/ocupacion/planificador_intradia.txt`): con el planificador y la cola reales, un ciclo
  intradía de tres rutas con la hora que llegó tardó de 3,4 a 3,6 s en este equipo (predicciones, ocupación, plan del
  día y foto); el primero, con el histórico de tres días, 7,2 s. Es alrededor del 0,1 % de la hora.
- **Carga en la fuente** (`docs/evidencias/ocupacion/ciclo_intradia_fuente.md`, réplica como `lector_ia`): unos 3,5 s
  de lecturas por ciclo (el 0,10 % de la hora) y 52 s al día con el cron por omisión, frente a 7,6 s del ciclo diario.
  Con el histórico completo y sin los índices de H12, la estimación es de unos 71 s por ciclo (2,0 % de la hora): la
  lectura incremental, la ocupación por segmento y los viajes del día (su conteo de segmentos por viaje cruza
  `timbradas_segmentos` por `id_viaje`, y `progvehiculos` por la hora de salida) recorren tablas enteras. Con los
  índices de la propuesta (los de `timbradas_segmentos` por `ultimaactualizacion` y por `id_viaje` y el de
  `progvehiculos` por ruta y hora de salida) deja de depender de su tamaño.
- **No interfiere** (RNF-001, RNF-002, RNF-005): una sola fila por franja con N réplicas, un ciclo de frecuencia a la
  vez por partición y la consulta paginada `GET /api/v1/recommendations` con un ciclo intradía en curso respondió con un
  p95 de 0,048 s (0,042 s sin ciclo), lejos de los 2 s de RNF-002.

**Su efecto depende de la latencia de captura de Extreme (H10, H11)**: una hora cerrada solo trae la ocupación de los
viajes que ya registraron sus segmentos. Con los viajes todavía en curso la restricción dispara en muchos menos casos
que con los viajes completos (sección «En tiempo real» del backtest). Si la captura llega con horas de retraso, el
ciclo intradía no encuentra nada nuevo y solo paga la lectura incremental.

**No es un re-pronóstico.** Un backtest anterior del proyecto mostró que re-pronosticar dentro del día no mejora la
precisión. Esta regla no cambia el pronóstico: pone un piso de seguridad cuando lo observado ya superó el umbral.

**Paridad.** Sin ocupación observada, o si la restricción no aplica, el MILP recibe exactamente la misma tabla
(`_con_piso_reactivo` devuelve el mismo objeto) y el plan es el de siempre. Lo prueban:

- `tests/unit/test_optimizacion_ocupacion.py::test_sin_piso_el_milp_recibe_la_misma_tabla_y_el_plan_e12_no_cambia`;
- `tests/unit/test_optimizacion_ocupacion.py::test_sin_ocupacion_observada_o_si_no_aplica_el_plan_es_el_mismo`.

### Efecto medido (`docs/evidencias/ocupacion/backtest_restriccion_reactiva.md`)

Con las subidas y bajadas por segmento de ene-feb 2023 (2.523 pares de horas seguidas medidas; la regla dispara 147
veces):

- La hora siguiente a un disparo queda sobre el umbral en el 28,6 % de los casos, frente a una tasa base de 5,9 %
  (lift 4,8): la regla dispara sobre algo que persiste, no sobre ruido.
- **Frente a la operación real** (contrafactual: la carga se reparte entre las salidas y no cambia con la oferta), la
  regla agregaría 457 salidas a las 2.219 de esas horas.
  - Las horas siguientes sobre el umbral bajarían de 42 a 14.
  - Los pasajeros por encima de la ocupación crítica en el segmento crítico bajarían de 3.490 a 1.541.
  - 292 de las 457 salidas caerían en horas que no quedaron sobre el umbral: es una regla de seguridad con falsas
    alarmas.
- **Frente al plan del día** con el modelo activo (69 días-ruta con disparo, ningún error), el piso sube la hora
  siguiente en 83 de los 147 disparos. En los 12 casos de la muestra por el camino real del código, el MILP sale
  óptimo y la hora queda en max(plan, piso). Con la flota activa, el piso se cumple quitando salidas a otras horas y
  sube el costo del día del MILP.
- **En tiempo real** (sección 4 del backtest). Las cifras anteriores usan la hora cerrada con todos sus viajes
  completos, y son una cota superior. Un viaje dura unas 3,5 h (mediana 206 min), así que en un ciclo intradía los
  viajes de la hora cerrada van por la mitad. Con la hora a la que cada segmento llegaría por el trigger (salida más la
  fracción recorrida del viaje):
  - a las (h+1):05 siguen disparando 25 de los 147 disparos, con un piso de 0,42 veces el calculado con los viajes
    completos;
  - a las (h+1):30, 35 de 147, con 0,81 veces el piso;
  - de los disparos en tiempo real (39 y 58), la hora siguiente queda sobre el umbral en el 15,4 % y el 12,1 %, frente
    a una tasa base de 5,9 %.

## 5. Limitaciones y lo que debe confirmar Extreme

- **Periodo corto**: ene-feb 2023 es el único periodo con segmentos, con vacaciones escolares, inicio de clases y
  Carnaval. El perfil no ve Semana Santa, mitad de año ni diciembre.
- **Hora de salida**: la hora es la de salida del viaje, la franja que decide el despacho. Los segmentos del regreso
  se recorren una hora o más después.
- **Asignación al segmento más cercano**: el trigger asigna al segmento más cercano, y eso desordena algunos eventos
  donde la ida y el regreso comparten vía. La validación lo cuantifica.
- **Sentido**: es una aproximación geométrica, no un campo de Extreme.
- **Preguntas para Extreme**:
  - H9: ¿`pasajeros` debe ser la ocupación a bordo?
  - H1: ¿cuál es la estacionalidad vigente de Sobusa?
  - H10: ¿cuál es el bloque oficial de un segmento?
- **Retraso del dato**: en un ciclo intradía, la ocupación de una hora llega cuando sus viajes registran los
  segmentos, y un viaje dura unas 3,5 h. La regla solo usa horas cuyas salidas ya pasaron, pero sus viajes siguen en
  curso: en tiempo real dispara mucho menos y con un piso menor que en el backtest con viajes completos (sección 4).
  Cuánto llega a tiempo depende de cada cuánto inserta la captura en `conteo_pasajeros` y de quién llama la
  liquidación y el cierre (H10, H11), que no se entregaron: el ciclo intradía programado está probado con el
  planificador real y una captura en vivo de prueba, no con la captura real de Extreme.
- **Costo en la fuente sin índices**: cada ciclo intradía recorre `timbradas_segmentos` (H12) en la lectura
  incremental, en la ocupación por segmento y en los viajes del día de cada ruta. En la réplica son unos 3,5 s por
  ciclo; con el histórico completo y sin la propuesta de índices, una estimación de unos 71 s (2 % de cada hora de
  servicio). Si la base de producción lo resiente, `PLAN_INTRADIA_CRON` se espacia o se apaga sin tocar el código.
- **Lo que solo hace el ciclo diario**: el error del modelo, el monitoreo, la política, los consolidados y el refresco
  de la agregación de segmentos siguen siendo diarios. Un ciclo intradía tampoco re-pronostica: el plan del día en
  curso cambia solo por el piso de la hora en que actúa la restricción.

## 6. Cómo reproducir

```text
python scripts/preparar_ocupacion_segmentos.py --origen ../../datos      # perfil y evidencia del histórico
python scripts/backtest_ocupacion_reactiva.py --origen ../../datos --plan # efecto de la restricción reactiva
pytest tests/unit/test_ocupacion.py tests/unit/test_optimizacion_ocupacion.py tests/unit/test_alertas_ocupacion_segmentos.py
pytest tests/unit/test_ciclo_intradia.py tests/unit/test_planificador.py   # ciclo intradía, piso de la franja, cron
pytest tests/integracion/test_ocupacion_ciclo.py tests/integracion/test_ciclo_tiempo_real.py
pytest tests/replica/test_ocupacion_segmentos.py      # réplica local: la lectura como lector_ia
REPLICA_PRUEBAS_ESCRITURA=1 pytest tests/replica/test_ocupacion_segmentos.py   # y además la transacción revertida
python scripts/medir_ciclo_intradia.py                # réplica local: carga en la fuente del ciclo intradía
PRUEBA_PLANIFICADOR=1 GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_planificador_programado.py   # planificador real
```
