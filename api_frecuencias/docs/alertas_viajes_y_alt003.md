# Alertas: viaje, vehículo y conductor (§5.3) y ALT-003 con probabilidad y umbral gobernado

Especificación v1.5: §5.2 (catálogo de alertas), §5.3 («Empresa, ruta, sentido, viaje, conductor y vehículo, cuando
aplique»; «Probabilidad o puntuación de anomalía»), §5.1 (regla de gobierno), §8.3 (solo lectura e índices
aprobados), §9.3 (sin fuga), §16 («Optimización y alertas»: utilidad y explicabilidad) y §18 («Alertas excesivas» y
«Exposición de datos»).

## 1. Qué campos de identificación aplican a cada regla

`app/servicios/alertas.py` (`IDENTIFICACION_5_3` y `VARIANTES_5_3`). La empresa (catálogo) y la ruta (con su
`idruta`) aplican a todas. El **sentido no aplica** a las reglas por ruta de este motor: la serie es por ruta y cada
viaje recorre el circuito completo (ida y regreso); el sentido solo existe por segmento (supuesto S9 del modelo por
segmento). La excepción es la ALT-002 observada que se mide en el segmento crítico de la hora (§10.1,
`docs/ocupacion_segmentos.md`): lleva el sentido aproximado de ese segmento y el viaje más cargado en él, con su
vehículo y el seudónimo de su conductor (variante `segmento_critico`). Lo identifica también cuando la hora pico la
midió un ciclo anterior: busca el `id_viaje_max` guardado en `ocupacion_segmento` entre los viajes del día
(`identificacion_5_3.viaje_medido_por` = «ciclo_anterior»; `alertas._viaje_del_segmento`). Si ese viaje no está, la
alerta dice «segmento_sin_viaje».

| Código | Viaje, vehículo y conductor | Por qué |
|---|---|---|
| ALT-001, ALT-003, ALT-004 | no aplican | pronóstico de la ruta para una franja futura: todavía no hay un viaje que atribuirle |
| ALT-002 | no aplican | la ocupación es de la ruta en la franja (pronóstico) o en la hora con el factor de carga, con varios buses |
| ALT-002 medida en el segmento crítico | **aplican**, con el sentido aproximado | el viaje más cargado en el segmento crítico de la hora pico |
| ALT-005, ALT-007 | no aplican | demanda agregada de la ruta en la ventana (todos sus viajes) |
| ALT-006 | **aplican** | el despacho de la ventana que no salió o salió tarde |
| ALT-008 | no aplican | consolidado diario de la ruta |
| ALT-009 | **aplican** | el viaje de la ventana con datos faltantes |
| ALT-010 | no aplican | degradación del modelo de la ruta |

Toda alerta lleva `variables.identificacion_5_3 = {aplica, motivo, sentido[, variante, resultado, rol_viaje]}`: un
campo vacío dice por qué está vacío.

## 2. De dónde salen los viajes

`ejecucion.contexto_observado` agrega al contexto de las reglas observadas los viajes del día de la ruta
(`viajes_del_dia`), de `progvehiculos` y siempre en **solo lectura**:

1. la fuente operacional del ciclo (`FUENTE=postgres`): `fuentes.FuentePostgresSoloLectura.viajes`, un SELECT constante
   de la lista blanca (`fuentes.sql_viajes_ruta`) con parámetros enlazados, en la transacción `READ ONLY` con
   `statement_timeout`. Como el ciclo lee la capa de segmentos (`demanda_segmentos`), también cuenta las filas de
   `timbradas_segmentos` de cada viaje;
2. si la fuente del ciclo no los expone (la serie empaquetada es horaria), los catálogos
   (`catalogos.viajes_para_alertas`): la réplica (`CATALOGOS_DATABASE_URL` o `FUENTE_DATABASE_URL`) o la exportación
   `progvehiculos.parquet` (`CATALOGOS_DATOS_DIR`), sin conteo de segmentos;
3. sin ninguna, `None`: las alertas salen igual, con `identificacion_5_3.resultado = "fuente_sin_viajes"`. No es un fallo
   de la ejecución; un error de una fuente configurada sí queda en sus fallos (etapa «viajes»).
4. una fuente que responde pero no trae ningún viaje del día (`[]`): como el día evaluado es el último con demanda de
   la ruta, esa fuente no cubre el día (réplica o exportación desfasada, `progvehiculos` incompleto). Las alertas salen
   igual, sin viaje, con `resultado = "fuente_sin_viajes_del_dia"`, y ALT-009 no descarta ninguna hora faltante: una
   fuente vacía no prueba que no hubo servicio.

**§18.** `idconductor` se lee solo para seudonimizarlo en la frontera de la fuente (`fuentes.seudonimizar_viajes`:
HMAC-SHA256 con `SEUDONIMO_SECRETO`, «cnd_» + 24 hex; el mismo seudónimo para 77 y 77.0) y nunca sale de ahí en claro.
La base lo vuelve a exigir con el CHECK de la migración 0003. Sin secreto, el conductor queda nulo.

**Costo e índices (§8.3).** La ventana va sobre `date_trunc('hour', fechasalida)` (la expresión del índice propuesto 3
de `docs/evidencias/replica/propuesta_indices.sql`) y el conteo por `id_viaje` usa el índice propuesto 2. En la réplica
una ruta y un día tardan ≈ 0,2 s sin el conteo de segmentos; con él, ≈ 0,87 s sin índices, ≈ 0,12 s con el índice 2 y
≈ 0,01 s con los índices 2 y 3 (medido con cada índice creado dentro de una transacción que se revierte,
`docs/evidencias/replica/indices_candidatos.md`; una lectura por ruta y ejecución).

## 3. Cómo se elige el viaje

- **ALT-006** (`identificar_viaje_006`): de los viajes con salida programada en la ventana del episodio, el primero
  **cancelado** (despacho ausente); si no hay, el más **tardío** fuera de la tolerancia (marcado con
  `excedeplazosalida` o con salida real − programada > `Procesos.toleranciatiempo` o `tolerancia_despacho_min`); si no,
  el primero **sin finalizar**. Si todos salieron a tiempo, el déficit es de programación: la alerta no inventa un viaje
  y deja en `variables.ultimo_despacho_previo` el último despacho antes de la ventana. `variables.viajes_ventana` cuenta
  los viajes por estado y lista hasta 10.
- **ALT-009** (`identificar_viajes_009`): los viajes del día con datos faltantes —sin finalizar, sin
  `numeropasajeros`, con `numeropasajeros` > 300 o, si la fuente cuenta los segmentos, sin filas en
  `timbradas_segmentos`—, primero los de las horas faltantes. Con los viajes del día, una hora faltante **sin ningún
  viaje programado no cancelado** no es un dato que falte (no hubo servicio que capturar): se descarta y queda en
  `variables.horas_sin_viajes_programados`. Solo se descarta si la fuente trae viajes de ese día (con `None` o `[]` toda
  hora faltante cuenta). ALT-009 solo por frescura no tiene viaje (`resultado = "solo_frescura"`).
- Si el episodio continúa en una ejecución posterior y la redetección identifica el viaje, la alerta abierta lo toma
  (`ejecucion._identificacion_del_episodio`).

Medición con datos reales: `docs/evidencias/alertas/identificacion_viajes.md` (`scripts/evidencia_identificacion_alertas.py`).
Su sección D mide la variante `segmento_critico` con la ocupación actual por segmento de la réplica (las 2.757 franjas
de la capa de segmentos, leídas viaje × segmento en solo lectura como en el ciclo integrado): el segmento crítico de
cada hora trae su sentido aproximado y su viaje más cargado, con vehículo y seudónimo del conductor, en el 100 % de las
horas, y salen 31 ALT-002 con la variante, todas con sentido, viaje y conductor seudonimizado.

## 4. ALT-003 de pronóstico: probabilidad y mínimo gobernado

ALT-003 se emite cuando la frecuencia actual no cumple el nivel de servicio del optimizador **y** la probabilidad de que
la carga crítica supere la capacidad efectiva (buses/h × puestos × ocupación objetivo máxima) llega a
`alt003_probabilidad_minima` (`threshold_config`, migración 0014). La probabilidad usa la lognormal del optimizador
(mediana = factor de carga × demanda por hora, σ de la banda P10-P90 calibrada, `recommendation.detalle.demanda`) y va
en el campo `probabilidad` de la alerta (§5.3), en sus variables y en la explicación. Con 0,10 la regla es la anterior
(solo el nivel de servicio 0,90).

**Diagnóstico.** En el backtest del ciclo de las 6:00 (regenerado con el código final de la ola B: factor de carga por
día de la semana de operación) la regla anterior tenía una precisión (0,355) bajo la tasa base de todas las franjas
(0,469): lift 0,76. Pero ALT-003 nunca se emite donde sale ALT-001 (§18, va incluida en ella) y esas franjas son las de
más riesgo (0,768 positivas). Frente a la tasa base de las franjas donde sí puede emitirse (0,236) su lift era 1,50, y
las 61 franjas sin ninguna de las dos no tuvieron ninguna positiva.

**Elección sin fuga** (`scripts/variantes_alt003.py`): variantes p ∈ {0,10 … 0,50}; validación 15/09–31/10/2025,
evaluación 01/11–31/12/2025 (ambas después del corte del modelo); se elige en validación la de mayor lift elegible con
al menos 20 alertas y se adopta solo si supera 1; en evaluación, IC bootstrap del 95 % por días. Resultado: p = 0,30 —
en evaluación, precisión 0,552 (16 de 29), lift elegible 2,08 [1,51; 2,99] y lift sobre todas las franjas 1,16 [0,82;
1,51]; la regla anterior en la misma ventana: 1,66 [1,31; 2,21] y 0,93 [0,69; 1,18]. Robustez con el ciclo desde cada
hora de 5 a 19 h: `docs/evidencias/alertas/alt003_variantes_todas_las_horas.md`.

**Gobierno.** La migración 0014 crea una versión nueva del conjunto completo con `alt003_probabilidad_minima = 0,30`,
**propuesta** (sin aprobar): la aprueba el área operativa con `POST /api/v1/thresholds/{version}/aprobar` y la cambia
con `PUT /api/v1/thresholds` (fracción en (0; 1,5]). Como en las 0007 y 0010, la versión propuesta rige desde que se
aplica la migración (el sistema no tiene un estado «propuesta sin aplicar»). La migración toma el mismo candado de
transacción que `PUT /thresholds` (`ejecucion.bloquear_umbrales`), así que no se intercala con un cambio de otra
réplica. Una ejecución partida por ruta usa la versión fijada al crearla.

**Lo que mide cada tasa base.** «Donde puede emitirse» (franjas sin ALT-001) es la tasa base que corresponde a una
regla que §18 suprime donde sale ALT-001. Contra la tasa base de todas las franjas, la variante elegida tuvo lift 0,90
en validación (no la supera) y 1,16 [0,82; 1,51] en evaluación (el IC incluye 1): con esa otra tasa base ninguna
variante con al menos 20 alertas en validación la supera. La regla anterior ya superaba la tasa base donde puede
emitirse (lift 1,66 [1,31; 2,21] en evaluación), y los IC de la anterior y de la elegida se solapan.

## 5. Reproducir

```
cd EntregaFinal/api_frecuencias
.venv/Scripts/python scripts/backtest_alertas.py --pronostico               # backtest_alertas_pronostico.md/.json
.venv/Scripts/python scripts/backtest_alertas.py --alt003-todas-las-horas   # alt003_variantes_todas_las_horas (≈ 19 min)
.venv/Scripts/python scripts/evidencia_identificacion_alertas.py            # identificacion_viajes (réplica, lector_ia)
.venv/Scripts/python -m pytest tests/unit/test_alertas_identificacion.py tests/unit/test_alertas_alt003.py tests/unit/test_variantes_alt003.py
TEST_DATABASE_NAME=ai_frecuencias_pruebas_x .venv/Scripts/python -m pytest tests/integracion/test_alertas_identificacion.py
.venv/Scripts/python -m pytest tests/replica/test_alertas_viajes.py         # réplica local, solo lectura
```
