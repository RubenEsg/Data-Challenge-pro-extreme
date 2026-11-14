# Partición del ciclo por ruta y fecha (RNF-005)

RNF-005 pide «servicios sin estado cuando aplique; procesamiento particionable por ruta y fecha». Las réplicas de la
API ya eran sin estado (la cola vive en PostgreSQL) y cada ejecución ya era una partición por fecha (`hasta`). Desde la
migración 0009 una ejecución también se parte **por ruta**: cada ruta tiene su marca de agua, su candado y su trabajo,
y las réplicas procesan rutas distintas a la vez.

## Cómo se usa

| Quién | Cómo | Qué pasa |
|---|---|---|
| API | `POST /api/v1/frequency/executions` con `{"hasta": "2025-03-04", "particion": "ruta"}` (y opcionalmente `rutas`) | Se crea la ejecución **madre** (`particion = "ruta"`) y un **trabajo por ruta** (`ruta`, `padre_id`); sin `rutas`, uno por cada ruta del catálogo. La respuesta 202 trae la lista `trabajos`. Una ruta que no está en el catálogo responde 422 `ruta_desconocida`. |
| Planificador | `PLAN_PARTICION=ruta` (por omisión `ninguna`) | La franja del cron encola la madre y sus trabajos en la misma transacción; con N réplicas sigue habiendo una sola madre por franja. |
| Consulta | `GET /api/v1/frequency/executions/{id}` | Cada ejecución muestra `ruta` (null = todas), `padre_id` y `particion`; la madre muestra `trabajos` y sus conteos suman los de sus trabajos. Filtros nuevos en el listado: `ruta` y `padre_id`. |
| Marcas | `GET /api/v1/frequency/watermarks` | La marca de agua de cada proceso y ruta (y la frontera `*`), con el trabajo que la dejó y cuántas huellas guarda. |

Sin `particion` (o con `"ninguna"`) todo sigue como antes: un solo trabajo de todas las rutas, y `rutas` limita la
predicción, no la lectura.

## Modelo de datos (alembic/versions/0009_particion_por_ruta.py)

- `execution_log.ruta`: la única ruta que el trabajo lee, procesa y bloquea (NULL = todas).
- `execution_log.padre_id`: la madre de un trabajo de ruta. `execution_log.particion`: en la madre, `ruta`.
- `marca_agua_ruta (proceso, ruta, marca_agua, estado_fuente, execution_id, origen, actualizado_en)`: la marca de agua
  y las huellas de la ventana de solape **por proceso y ruta**. La fila `ruta = '*'` es la **frontera** de las lecturas
  de todas las rutas del proceso: la usa una ruta que todavía no tiene marca propia.
- Siembra: la marca global de antes (la mayor `marca_agua_nueva` de las ejecuciones «ok», con sus huellas) pasa a cada
  ruta del histórico propio y a la frontera de su proceso y de «todos los procesos»; cada ruta recibe solo sus huellas
  (`ruta|fecha|hora`). Así, al migrar no se relee nada (`origen = migracion_0009`).
- Bajada: borra la tabla y las columnas. Si las marcas por ruta quedaron desfasadas, conviene correr antes una
  ejecución sin partir, que deja todas las rutas en la misma frontera (la marca global que vuelve a usar la 0008).

## Lectura incremental por ruta (app/servicios/fuentes.py)

`Particion` describe lo que lee un trabajo: el proceso, sus rutas (None = todas) y la marca y las huellas de cada ruta.
`leer_particion(fuente, particion, hasta)`:

- **PostgreSQL (solo lectura).** Un solo SELECT de la lista blanca: el mismo `demanda_segmentos` con la variante fija
  `r.nombre = ANY(CAST(:rutas AS text[]))` en las franjas, en la transacción `READ ONLY` con `statement_timeout`. Se lee
  desde la marca más antigua de las rutas del trabajo menos el solape y después se aplica a **cada ruta** la regla
  exacta de siempre con SU marca y SUS huellas: lo anterior a su ventana ya se le entregó, una fila repetida dentro de
  la ventana se descarta por huella y el tipo de llegada (nueva, tardía, modificada, carga inicial) es el de esa ruta.
- **Parquet.** Las filas de las rutas del trabajo con `fecha <= hasta`, cada una con `ultima_actualizacion` posterior
  a la marca de su ruta.
- **Todas las rutas.** Un trabajo sin ruta lee la fuente completa desde la marca más antigua (y la frontera) y deja
  todas las rutas conocidas y la frontera en la marca mayor de lo que **leyó** (filas posteriores a la marca de su
  ruta): con solo ejecuciones sin partir, el comportamiento es idéntico al de la marca global de antes
  (`tests/unit/test_particion.py::test_postgres_marcas_alineadas_entrega_lo_mismo_que_leer_incremental`). La marca
  propia de una ruta adelantada no cuenta: si un trabajo de todas las rutas corre con un `hasta` anterior a esa marca,
  las demás rutas quedan en lo que se les leyó y el trabajo siguiente lee sus días siguientes; y una ruta a la que no
  le pasó ninguna fila conserva sus huellas, así que su ventana de solape no se vuelve a entregar
  (`tests/unit/test_particion.py::test_postgres_ruta_adelantada_no_mueve_la_frontera_ni_pierde_sus_huellas`,
  `tests/integracion/test_particion_ruta.py::test_todas_las_rutas_con_hasta_anterior_a_una_ruta_adelantada_no_salta_ni_repite`).
- Las marcas nuevas se guardan con un upsert que nunca retrocede, en la MISMA transacción de los resultados y del
  cierre «ok» con cerca: un intento revertido no mueve ninguna marca. `execution_id` es el trabajo que movió la marca
  (§9.5, la marca de la última ejecución exitosa); un trabajo sin nada nuevo no lo cambia, y si se borra el trabajo que
  la movió, la marca se borra con él (la ruta vuelve a la frontera o a la carga inicial: nunca se salta datos).

## Candado por ruta

1. **En el reclamo** (`app/servicios/cola.py`, `_RECLAMAR`, serializado con `pg_advisory_xact_lock`): un trabajo de
   frecuencia se reclama solo si ningún otro cuya partición se cruce (la misma ruta, o uno de todas las rutas) está
   corriendo o espera un reintento llegado antes. Con `ORDER BY creado_en` cada ruta va en orden de fecha. Una
   ejecución de todas las rutas espera a que no corra ningún trabajo de ruta, y un trabajo de otra ruta que llegue
   mientras tanto puede adelantársele (no se cruza con nada que corra); después ella lee cada ruta desde su marca
   (`test_la_de_todas_las_rutas_espera_y_una_ruta_libre_que_llega_despues_se_le_adelanta`). La madre se reclama solo
   cuando ya no le queda ningún trabajo en cola ni corriendo. Con solo ejecuciones sin partir es la regla de siempre:
   una a la vez en todo el clúster.
2. **Dentro del ciclo** (`ejecucion.tomar_candados_particion`): candados de asesoría de transacción, el de la ruta
   (exclusivo) y el de «todas las rutas» (compartido para un trabajo de ruta, exclusivo para uno de todas). Garantizan
   la exclusión aunque una réplica que perdió la reserva siga viva; el segundo espera hasta dos reservas y, si no se
   libera, el intento se reintenta con espera (`ParticionOcupada`).
3. **Política del modelo** (`ejecucion.tomar_candado_modelo`): la reversión, la compuerta de sombra y el reentreno
   corren de a uno (madre de un día frente a ciclo sin partir).

## Qué hace cada trabajo y qué hace la madre

- **Trabajo de ruta:** lectura, calidad (lote `id:ruta:hasta`), histórico propio, evaluación del error y WAPE móvil de
  SU ruta para ALT-010 (sin guardar fila de monitoreo), predicciones 30/60/120, recomendaciones, alertas, notificaciones,
  plan del día, foto de la respuesta del reto y foto de variables de sus predicciones, con sus filas por segmento y
  sentido (§7.3 paso 4): cada fila se escribe una vez, en el trabajo de su ruta; la madre no guarda foto.
- **Madre:** cuando terminan sus trabajos, y con el candado del modelo, la fila de monitoreo (§9.4) hasta el último día
  de datos de sus trabajos, las predicciones del retador en sombra sobre las de sus trabajos y la política (RF-018,
  RF-019). Una fila de monitoreo por ejecución, como antes: «las últimas n ejecuciones» de la política siguen siendo
  días. Un trabajo en error no la detiene: queda contado en su mensaje, su ruta no movió la marca (la ejecución
  siguiente la vuelve a leer) y sus filas no se suman en las de la madre (`filas_leidas` y `filas_validas` son las de
  los trabajos «ok»). La madre termina «ok» aunque fallen todos sus trabajos; el estado de cada uno está en
  `trabajos`. Después de cerrar, y si sus trabajos trajeron filas válidas, la madre pide UNA vez el refresco de la
  agregación de segmentos (§6.1; ningún trabajo de ruta lo pide: cada refresco lee `timbradas_segmentos` en la base de
  Extreme).
- **Versión de umbrales:** al crear la ejecución partida, la versión vigente de `threshold_config` queda fijada en los
  parámetros de la madre y de sus trabajos (`umbrales_version`), y todos la leen (`ejecucion.umbrales_de_la_ejecucion`):
  un `PUT /thresholds` que llega mientras corren no parte el día en dos versiones de umbrales ni de parámetros del plan
  (§5.1); la ejecución siguiente usa la nueva. La foto de la respuesta del reto de cada trabajo también se calcula con
  esa versión (`respuesta.precalcular(..., umbrales=)` recibe la del ciclo) y reutiliza el plan que el trabajo acaba de
  guardar, así que `GET /respuesta` y `GET /recommendations/plan` dicen lo mismo. Antes, el trabajo que corría
  después del `PUT` guardaba su foto con la versión nueva y volvía a resolver el MILP: la respuesta del día quedaba con
  dos versiones y con otras salidas que el plan guardado. `GET /respuesta` lee la foto de la versión vigente: después
  de un `PUT /thresholds` responde 404 `sin_calcular` hasta la ejecución siguiente o un `POST /respuesta/calcular`.
- La partición mensual de `feature_snapshot` se crea antes de escribir predicciones y fuera de la transacción del
  ciclo, con `lock_timeout` menor que `deadlock_timeout` (`monitoreo.asegurar_particion_previa`): crear una partición
  clona sus llaves foráneas y bloquea `prediction` y `execution_log`, lo que dentro de dos trabajos a la vez era un
  interbloqueo (visto y corregido en la primera corrida con dos réplicas).

## Pruebas y evidencia

| Qué | Dónde |
|---|---|
| Unidad: partición, lectura por ruta (Parquet y PostgreSQL con mocks), marcas que deja cada trabajo, candados, planificador | `tests/unit/test_particion.py` |
| Integración: un trabajo por ruta con su marca; misma salida que sin partir (predicciones, plan, alertas, foto de la respuesta, monitoreo); sin partir después de una ruta lee solo lo que falta; falla de una ruta; reglas del reclamo; dos trabajadores a la vez; candado con una réplica viva sin reserva; planificador partido; migración 0009 en una base desechable | `tests/integracion/test_particion_ruta.py` |
| Réplica de Extreme, solo lectura: la lectura de una ruta es la completa filtrada por esa ruta, desde la carga y desde una marca; EXPLAIN de la variante | `tests/replica/test_particion_ruta.py`, `docs/evidencias/cola/lectura_por_ruta_replica.txt` |
| Dos réplicas reales (procesos uvicorn): rutas distintas a la vez, la misma ruta nunca en paralelo, sin duplicados, marcas contiguas y las mismas salidas que sin partir, también la foto de variables de la ruta y por segmento | `scripts/prueba_replicas_por_ruta.py`, `tests/integracion/test_replicas_por_ruta.py` (`PRUEBA_REPLICAS=1`), `docs/evidencias/cola/replicas_por_ruta.txt` |
| Convivencia con la capa de segmentos y con los umbrales gobernados: foto por segmento una vez por trabajo y en su partición, un solo refresco de segmentos pedido por la madre (también con un trabajo que pierde la reserva) y la misma versión de umbrales en toda la ejecución | `tests/integracion/test_convivencia_ciclo_segmentos.py` |

## Límites conocidos

- **Costo por trabajo.** Cada trabajo de ruta vuelve a calcular la serie validada y paga sus costos fijos: 5,2 s por
  trabajo de media (92,8 s en 18 trabajos) frente a unos 3,4 s por ruta sin partir (61,1 s en 6 ejecuciones de 3 rutas).
  Con tres rutas y dos réplicas, el lote de 6 días tardó 55,8 s partido frente a 61,1 s sin partir, con un paralelismo
  medio de 1,70 (`docs/evidencias/cola/replicas_por_ruta.txt`, corrida del 13-11-2026). La ventaja
  depende de la carga del equipo: en corridas anteriores fueron 41,5 s frente a 51,0 s, 44,0 s frente a 52,1 s, 37,4 s
  frente a 50,5 s y 63,4 s frente a 57,0 s. La partición sirve para repartir rutas entre réplicas y crecer en rutas; el
  planificador sigue sin partir por omisión.
- **Lectura de la fuente.** Cada trabajo de ruta hace su propia lectura. Sin los índices propuestos para Extreme
  (`docs/evidencias/replica/propuesta_indices.sql`, PLAN_EVOLUCION §1.3), cada lectura, de una ruta o de todas, recorre
  `timbradas_segmentos` completa: en la réplica, el SELECT de una ruta tardó del mismo orden que el de todas (el de
  todas, de 3,5 a 4,3 s; el de una ruta, de 3,2 a 3,6 s; medias de 3,9 s y 3,4 s,
  `docs/evidencias/cola/lectura_por_ruta_replica.txt`, con el equipo sin otras cargas). Partir por ruta multiplica esas
  lecturas por el número de rutas; con los índices, el costo depende de lo nuevo: con la propuesta entera y las
  estadísticas al día, la lectura de una ruta del bloque grande baja de 3,3 a 1,2 s y la de una ejecución sin novedades,
  de 168 a 0,1 ms (`docs/evidencias/replica/indices_candidatos.md`, «La propuesta entera»).
- **Instante por ruta.** Sin `instante` en la solicitud, cada trabajo pronostica desde el último día de datos de SU
  ruta; si una ruta va atrasada, su plan es para otro día que el de las demás (en la ejecución sin partir, todas usan el
  último día de cualquiera). Sin datos nuevos de una ruta, su trabajo solo mide la frescura (ALT-009).
- **Modelo activo.** Cada trabajo usa el modelo activo cuando empieza; si una madre activa un retador mientras corren
  trabajos del día siguiente, ese día puede mezclar modelos entre rutas (cada fila guarda su `model_id`).
- **Rutas sin marca propia.** Sin frontera (una base nueva donde solo corrieron ejecuciones partidas), un trabajo de
  todas las rutas parte de la marca inicial para las rutas que nunca se leyeron.
- **Monitoreo de la madre.** Se calcula al final del día y no al principio: cuenta también las alertas del día en
  `alertas_total` (el WAPE móvil, la cobertura y la deriva son los mismos).
