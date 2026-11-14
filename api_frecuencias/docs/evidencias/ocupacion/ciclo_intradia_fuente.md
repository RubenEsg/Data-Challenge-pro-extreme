# Carga en la fuente del ciclo intradía (§10.1, PLAN_INTRADIA_CRON)

Generado por `scripts/medir_ciclo_intradia.py` el 2026-11-13T22:25:39-05:00 en la réplica local, como `lector_ia` (READ ONLY, `statement_timeout`, ROLLBACK), con 5 repeticiones por lectura y el día 2023-02-08. `timbradas_segmentos` tiene 2.769.692 filas. La columna Filas es lo que trajo la última repetición (en los viajes del día, el contexto y los consolidados, cuántas lecturas devolvieron algo).

| Lectura | Mediana (s) | Rango (s) | Filas |
|---|---:|---|---:|
| incremental demanda_segmentos, todas las rutas, sin nada nuevo | 0,18 | 0,16 a 0,20 | 0 |
| incremental demanda_segmentos, una ruta (RNF-005), sin nada nuevo | 0,17 | 0,17 a 0,17 | 0 |
| ocupación por segmento de 4 h × 3 rutas (ciclo intradía a las 10:05) | 0,42 | 0,41 a 0,47 | 16.585 |
| ocupación por segmento de un día completo (51 franjas, ciclo de la madrugada) | 1,12 | 1,07 a 1,16 | 57.108 |
| viajes del día de las 3 rutas (progvehiculos, §5.3) | 2,00 | 1,97 a 2,04 | 3 |
| ubicación del despacho de las 3 rutas, Procesos y catálogos de la calidad | 0,09 | 0,09 a 0,11 | 5 |
| los 3 consolidados con su marca, sin nada nuevo (solo el ciclo diario) | 0,26 | 0,24 a 0,37 | 3 |
| ventana del refresco de segmentos (solo el ciclo diario y PLAN_SEGMENTOS_CRON) | 0,11 | 0,11 a 0,13 | 0 |

## Estimación por ciclo

- Ciclo intradía (lectura incremental, ocupación de sus 4 horas en curso contada dos veces, viajes del día y contexto): **3,1 s** de la fuente, el 0,09 % de la hora.
- Los 15 ciclos del cron por omisión («5 6-20 * * *»): 47 s al día.
- Ciclo diario (además, la ocupación de un día dos veces, dos días de viajes, los consolidados y la ventana del refresco de segmentos): 6,9 s. El día con los ciclos intradía lee 7,8 veces lo que leía solo con el diario.
- Proyección al histórico completo (unos 58 millones de filas, H12; 20,9 veces la réplica) sin los índices de la propuesta, escalando en proporción a las filas las lecturas que recorren `timbradas_segmentos` (también los viajes del día, que la cruzan por `id_viaje`): 63 s por ciclo intradía, el 1,8 % de la hora. Es una estimación, no una medición.

## Lectura

- El piso de cada ciclo es la lectura incremental: recorre `timbradas_segmentos` entera porque no tiene índice por `ultimaactualizacion` (H12). Un ciclo intradía sin datos nuevos solo paga eso (y la frescura): no rehace predicciones ni plan.
- El ciclo intradía no lee los consolidados ni la ventana del refresco de segmentos, y su ocupación es de sus horas cerradas en curso, no de un día.
- Con los índices de `docs/evidencias/replica/propuesta_indices.sql` (los de `timbradas_segmentos` por `ultimaactualizacion` y por `id_viaje`, y el de `progvehiculos` por ruta y hora de salida) la lectura de una hora deja de depender del tamaño de las tablas; sin ellos, el costo de los ciclos intradía crece con el histórico. Por eso PLAN_INTRADIA_CRON se puede espaciar (por ejemplo «5 6-20/2 * * *») o apagar (vacío) sin tocar el código.
- La efectividad dentro del día depende además de cuándo llegan las filas crudas a `conteo_pasajeros` (H10, H11): la sección «En tiempo real» de `backtest_restriccion_reactiva.md` lo mide.
