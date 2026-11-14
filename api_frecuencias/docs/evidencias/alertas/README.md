# Alertas: estructura §5.3, reglas ALT-001 a ALT-010 y backtest 2025

Este documento cubre lo que la especificación v1.5 pide en §3.1 («priorizar»), §5.1, §5.2, §5.3, RF-009 (valores
fuera del patrón **y rupturas de comportamiento**), RF-010, RF-015, §8.1 (geography con índice GiST), §9.4 («una
alerta no puede depender solo de una etiqueta opaca») y §18 («Alertas excesivas» y «Exposición de datos»). Todo es
reproducible con los comandos del final; cada cifra dice de qué archivo sale.

## 1. Estructura obligatoria de una alerta (§5.3): dónde está cada campo

`ai_frecuencias.alert` venía de la migración 0001. La migración `alembic/versions/0003_alertas_estructura.py` agrega
lo que faltaba y documenta cada columna con `COMMENT ON COLUMN` (se ve con `\d+ ai_frecuencias.alert`).

| Exigencia de §5.3 | Columna | Notas |
|---|---|---|
| Identificador único y código | `alert_id`, `codigo` | `codigo` con CHECK `^ALT-0[0-9]{2}$` |
| Empresa, ruta, sentido, viaje, conductor y vehículo, cuando aplique | `empresa`, `ruta`, `sentido`, `viaje`, `conductor`, `vehiculo` | `viaje` = `progvehiculos.idprogramacion`. `conductor` solo admite un **seudónimo** (ver §18 abajo) |
| Fecha y hora de detección | `detectada_en` | TIMESTAMPTZ (UTC; se presenta en America/Bogota) |
| Ventana analizada y horizonte | `ventana_inicio`, `ventana_fin`, `horizonte_min` | `horizonte_min = 0` = dato observado; en las de pronóstico la ventana es la hora recomendada |
| Severidad, estado | `severidad`, `estado` | máquina de estados en `alertas.cambiar_estado` |
| Valor observado, esperado y umbral | `observado`, `esperado`, `umbral` | en las mismas unidades. En las de pronóstico `observado` va **vacío**: es una proyección, y la proyección va en `esperado` y en `variables` |
| Probabilidad o puntuación de anomalía | `probabilidad`, `puntaje`, `metodo_puntaje` | `metodo_puntaje` dice cómo se calculó (no es opaco) |
| Explicación en lenguaje operativo | `explicacion` | frase con real, esperado, umbral, unidades, factor de carga y persistencia |
| Variables influyentes | `variables_influyentes`, `variables` | SHAP del pronóstico (lista ordenada) + insumos de la regla |
| Recomendación | `recomendacion` | acción sugerida de §5.2 |
| Usuario asignado, comentarios | `asignado_a`, `comentarios` | `PATCH /api/v1/alerts/{id}/status`; la hora del comentario se guarda y se presenta en -05:00 |
| Bitácora de cambios | tabla `alert_history` | `crear`, `reconocer`, `asignar`, `comentar`, `cerrar`, `descartar` y `redeteccion`; `GET /api/v1/alerts/{id}/history` paginado (`limite`, `desplazamiento`, `orden`, `accion`; total en `X-Total-Count`) |
| §9.4 tendencia | `tendencia`, `tendencia_pendiente`, `serie_reciente` | `al_alza`, `a_la_baja`, `estable` o `sin_datos` |
| §8.1 geography + GiST | `ubicacion geography(Point,4326)` + `ix_alert_ubicacion USING GIST` | p. ej. el punto de despacho en ALT-006 |
| Origen | `origen` | `pronostico`, `observado`, `calidad_datos` o `modelo` |

**§3.1 Priorizar.** `GET /api/v1/alerts` ordena **por omisión por prioridad**: primero las críticas, después las
preventivas y las informativas, y dentro de cada severidad la más reciente primero (`orden=prioridad`). Cualquier
columna sigue disponible (`orden=-detectada_en`). La exportación acepta el mismo `orden=prioridad`. El filtro
`idruta` (§8.3) busca por `rutas.idruta` (columna `alert.idruta` o, en filas sin ella, el nombre que da el catálogo).

**§18 Exposición de datos.** `conductor` tiene un CHECK `conductor IS NULL OR conductor ~ '^cnd_[0-9a-f]{24}$'`: la base
rechaza un nombre o un documento (prueba `test_la_base_rechaza_un_conductor_en_claro`). El seudónimo es
HMAC-SHA256 con el secreto `SEUDONIMO_SECRETO` del entorno (`.env.example`); sin secreto se guarda NULL.

**PostGIS.** La migración usa la extensión si existe, la crea si el rol puede y, si no hay PostGIS (despliegue sin
Docker), deja `ubicacion` como EWKT en TEXT sin índice. En Docker (`postgis/postgis:14-3.4`) y en la réplica es
`geography(Point,4326)` con GiST; la prueba de integración hace una consulta `ST_DWithin` de 500 m.

## 2. Alertas de pronóstico ALT-001 a ALT-004: la misma ocupación que el optimizador

El ciclo (`ejecucion._ciclo_frecuencia`) pronostica cada ruta a 30, 60 y 120 min y recomienda con
`optimizacion.recomendacion_franja` la **franja** de cada ventana: la hora con más peso en la ventana, con su demanda
y su banda P10-P90 calibrada **por hora**. `alertas.contexto_pronostico` toma de esa recomendación lo que el
optimizador ya calculó: el **factor de carga crítica** de la franja (carga del tramo más cargado / abordajes, mediana
2025 por ruta, tipo de día y hora), la ocupación de la frecuencia actual (`comparacion_actual.actual`), su nivel de
servicio y la carga crítica de diseño. Así la alerta y la recomendación de la misma franja dicen la misma ocupación.

| Código | Condición (umbrales de `threshold_config`) | Unidades |
|---|---|---|
| ALT-001 | carga crítica proyectada = factor de carga × P90 por hora > capacidad ofrecida por hora (buses/h × puestos); crítica si también la del pronóstico puntual la supera; probabilidad con Normal(pronóstico, σ de la banda) | pasajeros/h en el tramo más cargado frente a puestos/h |
| ALT-002 | ocupación esperada = factor de carga × demanda por hora / capacidad ofrecida ≥ `ocupacion_critica` (90 %) — la misma `ocupacion_esperada` de `comparacion_actual` — o la **observada** (sección 3) | fracción |
| ALT-003 | la frecuencia actual **no cubre el nivel de servicio**: capacidad ofrecida × `ocupacion_objetivo_max` (85 %) < carga crítica de diseño (`comparacion_actual.actual.cumple_nivel_servicio = False`). Si la recomendación no es viable, lo dice y pide escalar | buses/h actuales frente a buses/h necesarios |
| ALT-004 | ocupación esperada (con el factor) < `baja_utilizacion` (30 %) y la oferta supera la recomendada | fracción |

Si en la misma franja sale ALT-001, ALT-003 no se emite aparte: es la misma situación con menos fuerza, y ALT-001 lo
anota (`variables.incluye_alt003` y una frase en la explicación). La ventana de la alerta es la **hora recomendada**
en los tres horizontes y `alertas.evaluar_pronostico` deja **una sola alerta** por código, ruta y franja.

**El caso de la verificación** (`caso_silencio_7h.json`, escrito por la prueba
`tests/unit/test_alertas_optimizador.py::test_silencio_7h_la_alerta_y_la_recomendacion_dicen_la_misma_ocupacion` con
el optimizador real y `GENERAR_EVIDENCIAS=1`): SILENCIO a las 7 h, 669 pasajeros/h (P90 759) y
8,13 buses/h programados. Antes, sin el factor, salían ALT-001 y ALT-002 «críticas» con una ocupación de 164,6 %.
Ahora la ocupación de la alerta es 71,9 %, la misma del optimizador (factor 0,437), que recomienda 7 buses/h con
70,9 %: no hay alerta que contradiga la recomendación.

**Backtest** (`backtest_alertas_pronostico.md` / `.json`; ciclo de las 6:00, 15/09 a 31/12/2025, 324 días-ruta,
banda v2, con los 5 festivos entre semana del periodo tratados como domingo o festivo). Cada alerta se confirma con
la demanda **real** de su hora en las mismas unidades (carga crítica real = factor × pasajeros reales):

| Código | Por ruta y día | Precisión real | Tasa base | Lift | Antes (sin factor): por ruta y día |
|---|---|---|---|---|---|
| ALT-001 | **0,438** | 0,296 (42 de 142) | 0,164 | 1,81 | 0,889 |
| ALT-002 | **0,306** | 0,808 (80 de 99) | 0,398 | 2,03 | 0,858 |
| ALT-003 | **0,164** | 0,491 (26 de 53) | 0,469 (0,236 donde puede emitirse) | 1,05 (2,08 donde puede emitirse) | 0,318 (por número de buses) |
| ALT-004 | **0,031** | 0,400 (4 de 10) | 0,052 | 7,62 | 0,000 |
| Todas las de pronóstico | **0,938** (304 alertas en 324 días-ruta) | | | | 2,065 |

Regenerado con el código final de la ola B: el factor de carga crítica de la franja es el de ruta × día de la semana
de operación × hora (`optimizacion.factor_carga_franja`, con el tipo de día como respaldo) y ALT-003 exige además la
probabilidad mínima gobernada (`alt003_probabilidad_minima` = 0,30, migración 0014;
`../../alertas_viajes_y_alt003.md`). Lectura: con el factor de carga hay menos de la mitad de alertas de pronóstico
(0,938 frente a 2,065 por ruta y día) y discriminan más que la variante anterior por ventana (lift de ALT-001 1,09 →
1,81 y de ALT-002 1,08 → 2,03, tabla de confirmación de `backtest_alertas_pronostico.md`). ALT-003 nunca se emite donde
sale ALT-001 (§18, va incluida en ella), así que su tasa base es la de las franjas donde puede emitirse: con la
probabilidad mínima su lift es 2,08 ahí y 1,05 sobre todas las franjas (el 54 % de las franjas del ciclo de las 6:00 no
tiene una recomendación viable: `recomendaciones_viables_pct` = 46,0 %). Antes de la comparación por hora (ventana de
30/60/120 min frente a la capacidad por hora) eran 2,552 / 2,358 alertas por ruta y día de ALT-001 / ALT-002.

## 3. Reglas con datos observados (`app/servicios/alertas.py`, `evaluar_observadas`)

El ciclo (paso «3b») arma por ruta un contexto observado con `ejecucion.contexto_observado()`:

- **horas**: las horas cerradas del último día recibido, cada una con el real (`demanda_observada`), el **pronóstico
  del modelo para esa hora y su banda P10-P90 calibrada** y las salidas observadas frente a `60 / intervalo
  programado` (`parametros_operativos_hora`).
- **consolidado**: subidas y número de viajes del último día completo frente al mismo tipo de día de las 8 semanas
  previas (mediana y 1,4826·MAD).
- **datos**: minutos desde la última llegada frente al «ahora» de la ejecución, campos obligatorios faltantes y horas
  de servicio sin registro.
- **tolerancia_tiempo_min**: `Procesos.toleranciatiempo` cuando la fuente lo expone; si vale 0 o no viene, se usa
  `tolerancia_despacho_min` de `threshold_config`, y la alerta dice cuál usó.
- **serie_diaria** (opcional): real y pronóstico por día de la ruta, para la ruptura de comportamiento.

| Código | Condición | Severidad |
|---|---|---|
| ALT-002 observada | ocupación **observada** = factor de carga de la franja × pasajeros / (salidas × puestos) ≥ `ocupacion_critica` durante `persistencia_ocupacion_horas` (2) horas seguidas, en horas con al menos `salidas_minimas_ocupacion` (2) salidas y fuera de la primera y la última hora de servicio; origen `observado` | crítica |
| ALT-005 | real < (1 − `caida_demanda`) × esperado **y** real < P10 calibrado, con esperado ≥ `demanda_minima_patron`, durante `persistencia_horas` horas seguidas | preventiva |
| ALT-006 | por tiempo: minutos sin despacho (cota inferior = 60 × horas cerradas seguidas sin salidas) > headway programado + tolerancia; por conteo: déficit de salidas > `tolerancia_salidas` durante `persistencia_horas` horas. No se evalúa en la primera ni en la última hora de servicio | crítica |
| ALT-007 | real fuera de [P10, P90] calibrado con error ≥ `error_pronostico`, en el **mismo sentido** durante `persistencia_horas` horas; la parte por debajo se suprime donde ya hay ALT-005 | preventiva |
| ALT-007 ruptura (RF-009) | **CUSUM** tabular de dos lados sobre el residuo diario relativo (real − pronóstico) / pronóstico, estandarizado con la mediana y 1,4826·MAD de 28 días de referencia; alerta cuando el estadístico supera h = 6 (k = 0,5) y el cambio medio llega al 8 %; tras cada detección espera 7 días y toma el nivel nuevo (un cambio sostenido es UNA ruptura). `variables.variante = ruptura_comportamiento`, `metodo_puntaje` con el método | preventiva |
| ALT-008 | \|z robusto\| ≥ `z_anomalia` en subidas o viajes del día, con al menos `minimo_dias_referencia` días; o subidas con 0 viajes | preventiva |
| ALT-009 | sin datos durante ≥ `periodos_atraso` × `periodo_ingesta_min` (2 × 1.440 min = 2.880 min con el ciclo diario: el valor por omisión del código es el mismo de `threshold_config`), campos obligatorios faltantes u horas sin registro | crítica |
| ALT-010 | WAPE móvil > `wape_max`; clave `ALT-010|modelo|ruta|episodio`: una alerta por modelo y ruta mientras siga abierta, no una por día | crítica |

**Sin alertas excesivas (§18).** Las horas que cumplen se agrupan en **episodios**: una alerta por episodio, no por
hora. Su clave (`código|ruta|inicio del episodio|obs`) se mantiene mientras el episodio crece: la ejecución siguiente
actualiza la MISMA alerta, suma una ocurrencia y deja una entrada `redeteccion` en `alert_history`. La ruptura usa la
clave `ALT-007|ruta|inicio del cambio|ruptura` y solo se alerta el día en que se detecta.

## 4. Backtest 2025 de las observadas (`scripts/backtest_alertas.py`)

Reproduce el ciclo día a día y ruta a ruta con el pronóstico por hora y la banda calibrada vigente (**v2**, conformal
de Mondrian por bloque horario, `datos/modelos/hgb_fv2_20250831_s42/calibracion_v2.json`). No hay incidentes
etiquetados, así que la **precisión** se aproxima así: la condición sigue en la hora siguiente a la detección
(ALT-002, ALT-005, ALT-006, ALT-007), el día está marcado como especial o excluido (ALT-008) o el nivel nuevo se
sostiene 14 días (ruptura). Una alerta no confirmada cuenta como falso positivo. Lift = precisión / tasa base.

**A. Modelo activo `hgb_fv2_20250831_s42`, fuera de muestra (15/09 a 31/12/2025, 324 días-ruta)**:
`backtest_alertas.md` / `.json`.

| Código | Por ruta y día | Por día (3 rutas) | Precisión proxy | Lift | Reglas anteriores: por ruta y día |
|---|---|---|---|---|---|
| ALT-002 observada | 0,710 | 2,13 | 0,404 | 2,21 | 1,596 (sin persistencia) |
| ALT-005 | 0,142 | 0,43 | 0,359 | 4,69 | 1,296 |
| ALT-006 | 0,127 | 0,38 | 0,390 | 8,30 | 2,849 |
| ALT-007 | 0,204 | 0,61 | 0,270 | 1,34 | 1,833 |
| ALT-007 ruptura | 0,012 (4 detecciones) | 0,04 | 0,667 (2 de 3) | — | — |
| ALT-008 (con bajadas) | 0,071 | 0,21 | 0,652 | 3,52 | 0,105 |
| ALT-005 a ALT-009 | **0,543** | 1,63 | | | **6,083** |
| Todas las observadas | **1,265** (410 alertas) | 3,80 | | | |

**Volumen total para el operador (§18)**: 1,265 observadas + 0,938 de pronóstico = **2,203 alertas por ruta y día**
(unas 6,6 por día para las tres rutas; `scripts/cifras_vigentes.py` lo calcula de los dos JSON, con el conteo de
alertas y los días-ruta), frente a 0,534 + 2,065 = 2,599 antes de medir con el factor de carga y antes de evaluar la
ocupación observada y las rupturas. Con las reglas iniciales solo las observadas ALT-005 a ALT-009 ya eran 6,083 por
ruta y día («Reglas anteriores» de `backtest_alertas.md`).

ALT-002 observada es nueva: el 18,3 % de las horas medibles tiene una ocupación observada ≥ 90 % (tasa base), así que
la sobreocupación es real en los picos; la persistencia de 2 h la baja de 1,596 a 0,710 alertas por ruta y día con un
lift parecido (2,43 → 2,21; sensibilidad de `backtest_alertas.md`). El backtest estima la ocupación con el **mismo factor
de carga que el ciclo** (`optimizacion.factor_carga_franja`: ruta × día de la semana de operación × hora, 7 = domingo o
festivo, con el tipo de día como respaldo; `scripts/backtest_alertas.py::factores_de_las_franjas`, sin copiar el
cálculo): 5.468 de las 5.508 horas evaluadas tienen el factor de su día de la semana y 40 no tienen factor. Con el
factor por tipo de día que usaba antes el backtest eran 224 alertas (0,691), precisión 0,411 y lift 2,24; las demás
reglas no cambian. Antes, con la banda v1, ALT-005 a ALT-009 daban 0,509 por ruta y día.

**Detector de rupturas (RF-009)** — sección «Detector de rupturas» de `backtest_alertas.md`:

- Detecciones reales: CRA 54 desde el 08/12/2025 (−24,2 %, se sostuvo), CRA 54 el 16/12 (+11,6 %, no se sostuvo),
  SILENCIO desde el 29/10 (−10,4 %, se sostuvo) y SILENCIO el 30/12 (−18,7 %, sin 14 días para medirlo).
- **Falsas alarmas sin cambio**: con los días vigilados de cada ruta permutados 200 veces (misma distribución de
  residuos, sin ruptura) da **1,644 detecciones por cada 100 días-ruta**.
- **Potencia** frente a cambios inyectados desde un día dado (9 casos cada uno): −20 % se detecta en el 100 % de los
  casos dentro de 14 días (mediana 6 días), +15 % en el 77,8 % (4 días) y −10 % en el 44,4 % (5,5 días). El detector
  es para cambios de nivel sostenidos; los desvíos de horas sueltas los cubren ALT-005 y ALT-007.

**B. fv2 temporal con corte 31/12/2024 (15/01 a 31/12/2025, 1.053 días-ruta)**: `backtest_alertas_corte_2024-12-31.md`
/ `.json`, regenerado con el código final (banda v2, el factor de carga del ciclo, ALT-002 observada, rupturas y
ALT-008 con bajadas). Todas las observadas: 1,137 por ruta y día (ALT-002 observada 0,733 con lift 2,30; ALT-005 0,105;
ALT-006 0,089; ALT-007 0,119; ALT-007 ruptura 0,026, 27 detecciones; ALT-008 0,066). Solo ALT-005 a ALT-009: 0,378 por
ruta y día frente a 5,382 con las reglas anteriores. La corrida anterior de esta variante (banda v1, sin ALT-002
observada ni rupturas, ALT-008 sin bajadas) daba 0,451 frente a 5,702; queda en «Antes del cambio» de su `.md`. El
factor de carga es la mediana de 2025: en esta variante cubre el mismo año que se evalúa (no es fuera de muestra).

**Umbrales afinados** (versión de `threshold_config` en la migración 0003; los nuevos de ALT-002 observada y de la
ruptura pasan a `threshold_config` con la migración 0007, `../rendimiento/ciclo_final.md`, y se cambian con
`PUT /api/v1/thresholds`):

| Parámetro | Antes | Ahora | Por qué |
|---|---|---|---|
| `persistencia_horas` | — (1) | 2 | Con 1 h: ALT-005 1,068 y ALT-007 1,833 por ruta y día (lift 1,97 y 0,78). Con 2 h: 0,142 y 0,204 (lift 4,69 y 1,34) |
| `persistencia_ocupacion_horas` | — | 2 | ALT-002 observada: 1,596 → 0,710 por ruta y día con un lift parecido (2,43 → 2,21); con 3 h, 0,287 |
| `ruptura_h`, `ruptura_cambio_minimo` | — | 6,0 y 8 % | falsas alarmas sin cambio por 100 días-ruta (50 permutaciones, `backtest_alertas.md`): h = 4 y 5 % 4,092; h = 5 y 5 % 3,342; h = 6 y 8 % 1,825 (1,644 con 200 permutaciones), y un −20 % se sigue detectando en el 100 % de los casos |
| `alt005_exigir_p10` | — (0) | 1 | ALT-005 baja de 0,188 a 0,142 por ruta y día y el lift sube de 3,88 a 4,69 |
| `tolerancia_salidas` | 0,20 | 0,50 | ALT-006 baja de 1,062 a 0,127 por ruta y día y el lift sube de 1,31 a 8,30 |
| `z_anomalia` | 3,0 | 3,5 | ALT-008 (con bajadas) baja de 0,105 a 0,071 por ruta y día y la precisión sube de 0,50 a 0,65 |
| `periodo_ingesta_min` | 60 en el código | 1.440 | el mismo valor de `threshold_config` (migración 0001): ALT-009 por frescura a los 2.880 min |

## 5. Limitaciones (dichas con claridad)

- La precisión de las observadas es un **indicador aproximado**: no hay incidentes etiquetados. La muestra revisada
  por dos revisores está en `revision_doble/`.
- La ocupación observada compara los abordajes de la hora con las salidas de la misma hora: un bus que sale a las
  6:55 lleva pasajeros que suben a las 7:10. La persistencia de 2 h reduce ese ruido de borde.
- El factor de carga es la mediana 2025 (insumos D5) por ruta, día de la semana de operación (7 = domingo o festivo) y
  hora, con el tipo de día como respaldo (`optimizacion.factor_carga_franja`, el mismo del ciclo y del optimizador).
  Es del mismo año que se evalúa, así que en los backtests el factor no es fuera de muestra. Sin factor para una
  franja (menos de 10 días con datos), la ocupación observada de esa hora no se mide (40 de las 5.508 horas de 4.A).
- La ruptura necesita la serie diaria de la ruta (real y pronóstico por día) en el contexto observado; el backtest la
  arma con los mismos datos que el ciclo. Con menos de 29 días no se evalúa.
- La serie empaquetada es horaria: ALT-006 «por tiempo» usa una **cota inferior** (60 min por cada hora cerrada sin
  salidas). `Procesos.toleranciatiempo` vale 0 en la exportación de Sobusa: se usa `tolerancia_despacho_min` (5 min).
- ALT-008 evalúa subidas y número de viajes: las bajadas no vienen en `demanda_observada`.
- Entre el 14 % y el 75 % de las alertas observadas caen en días de calendario especial (columna «En días
  especiales» de `backtest_alertas.md`). Son eventos reales que el operador debe conocer, no ruido.

## 6. Cómo reproducir y pruebas

```
cd EntregaFinal/api_frecuencias
.venv/Scripts/python scripts/backtest_alertas.py                     # 4.A y el detector de rupturas (≈10 s)
.venv/Scripts/python scripts/backtest_alertas.py --corte 2024-12-31  # 4.B (entrena en un directorio temporal, ≈1 min)
.venv/Scripts/python scripts/backtest_alertas.py --pronostico        # sección 2 (≈1 min: un MILP por franja)
.venv/Scripts/python scripts/backtest_alertas.py --alt003-todas-las-horas   # robustez de ALT-003 (≈20 min)
.venv/Scripts/python scripts/evidencia_identificacion_alertas.py     # identificacion_viajes (réplica, lector_ia)
GENERAR_EVIDENCIAS=1 .venv/Scripts/python -m pytest tests/unit/test_alertas_optimizador.py   # caso_silencio_7h.json
# pytest_alertas_unitarias.txt: la salida literal de (la primera línea del archivo es el comando)
.venv/Scripts/python -m pytest tests/unit/test_alertas.py tests/unit/test_alertas_alt003.py tests/unit/test_alertas_identificacion.py tests/unit/test_alertas_observadas.py tests/unit/test_alertas_ocupacion_segmentos.py tests/unit/test_alertas_optimizador.py tests/unit/test_alertas_pronostico.py tests/unit/test_alertas_ruptura.py tests/unit/test_variantes_alt003.py -vv
# pytest_alertas_integracion.txt: la salida literal de (con la base local de pruebas propia en TEST_DATABASE_NAME)
.venv/Scripts/python -m pytest tests/datos_ml/test_alt003_protocolo.py tests/datos_ml/test_backtest_alertas.py tests/datos_ml/test_identificacion_viajes_evidencia.py tests/integracion/test_alertas_identificacion.py tests/integracion/test_alertas_observadas.py tests/integracion/test_export_alertas.py tests/integracion/test_gobierno_alt003.py -vv
```

`pyproject.toml` ya pone `-q` en `addopts`: con `-vv` queda una línea por prueba. Los dos archivos `pytest_alertas_*.txt`
son la salida tal cual de esos dos comandos (stdout), sin editar.

- `tests/unit/test_alertas_optimizador.py`: la alerta y la recomendación dicen la misma ocupación (optimizador real,
  SILENCIO 7 h), frontera de ALT-001 con el factor (P90 991 frente a 992), ALT-001 sin valor observado, ALT-003 por
  nivel de servicio en una franja **inviable** y ALT-003 dentro de ALT-001.
- `tests/unit/test_alertas_ruptura.py`: ocupación observada por hora (salidas mínimas, horas de borde), ALT-002
  observada con origen `observado`, episodios y persistencia, factor tomado del optimizador; CUSUM estable sin
  detecciones, caída y alza sostenidas detectadas con su inicio, un cambio sostenido = una ruptura, y la ALT-007
  variante con su método.
- `tests/unit/test_alertas.py`, `test_alertas_observadas.py`, `test_alertas_pronostico.py`: fronteras de cada regla,
  `periodo_ingesta_min` = 1.440 (2.879 frente a 2.880 min), clave de ALT-010 por episodio, persistencia, supresiones,
  seudónimo, tendencia y estados.
- `tests/integracion/test_alertas_observadas.py`: una ejecución real de la API produce ALT-002 observada, ALT-005,
  ALT-006, ALT-007, ALT-008 y ALT-009 con la estructura completa; las de pronóstico caen en la hora recomendada y
  ALT-002 de pronóstico sale **si y solo si** la ocupación que el optimizador guarda en `recommendation.detalle` es ≥
  90 %, con el mismo valor.
- `tests/integracion/test_export_alertas.py`: orden por prioridad por omisión, filtro `idruta`, historial paginado y
  comentarios en -05:00, además de la exportación CSV y XLSX.
- `tests/datos_ml/test_backtest_alertas.py`: el backtest reproduce `backtest_alertas.json` código por código y el
  detector (mismas rupturas y misma tasa de falsas alarmas); usa el factor de carga del ciclo
  (`test_el_backtest_usa_el_factor_de_carga_del_ciclo`); la evidencia de pronóstico es la del factor de carga. El
  resumen de la reproducción se guarda con `tests/evidencia.guardar_evidencia` (en `docs/evidencias` solo con
  `GENERAR_EVIDENCIAS=1`).
- `tests/datos_ml/test_identificacion_viajes_evidencia.py`: `identificacion_viajes.json` trae la tabla de
  `alertas.IDENTIFICACION_5_3` con sus motivos y la variante `segmento_critico` de `alertas.VARIANTES_5_3` (con el
  sentido), la medición de esa variante con la réplica y ningún seudónimo.
- Resultados de las corridas: `pytest_alertas_unitarias.txt` y `pytest_alertas_integracion.txt` (salida literal de
  los comandos de arriba).
