# Respuesta a la pregunta del reto

> **Pregunta que debe resolver el sistema (especificación v1.5, §20):** con los datos históricos y recientes, ¿cada
> cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos pasajeros y vehículos se esperan, y qué
> situaciones requieren atención inmediata?

El sistema contesta esta pregunta en un solo lugar, `GET /api/v1/respuesta` (rol operador). Con `ruta` (SILENCIO,
CRA 54 o CL 72) y `fecha` opcionales, devuelve para cada ruta las cuatro partes de la respuesta, la trazabilidad y las
limitaciones. `GET /api/v1/respuesta/export?formato=csv|xlsx` entrega lo mismo en una fila por ruta y hora.

**Cómo se calcula (§7.1, procesos largos asíncronos).** El pronóstico de cada hora y el MILP del plan no corren dentro
de la petición HTTP:

- `POST /api/v1/respuesta/calcular` (rol analista, cuerpo `{fecha, rutas}`) responde 202 con el `execution_id` de una
  ejecución de tipo «respuesta» en la cola de PostgreSQL;
- el trabajador de la cola calcula la respuesta con el modelo activo y los umbrales vigentes, y la guarda como una foto
  por ruta en `ai_frecuencias.respuesta_reto`;
- el ciclo diario hace lo mismo al cerrar, para el día siguiente al último dato;
- `GET /api/v1/respuesta` solo lee esa foto. Si no existe para la fecha, el modelo y los umbrales vigentes, responde
  404 `sin_calcular` con la pista `POST /api/v1/respuesta/calcular`.

**Con los datos históricos y recientes.** Sin `fecha`, la respuesta es para el día siguiente al último dato que tiene
la API: el último día de la serie empaquetada o de lo que el ciclo diario incorporó en
`ai_frecuencias.demanda_observada`, lo que sea más reciente. Con los datos de la entrega, la serie llega al
31-dic-2025, así que el día que hay que planear es el **jueves 1 de enero de 2026**, festivo de Año Nuevo, con tipo de
día «Domingo/festivo». El plan y los pasajeros salen del mismo pronóstico hora por hora del modelo activo, así que la
respuesta sirve para cualquier día con variables, no solo para 2025.

Todas las cifras de este documento salen de la evidencia generada con `scripts/respuesta_reto.py`. El script usa el
código de producción contra una base temporal del PostgreSQL local: corre una vez el ciclo diario, encola una
ejecución «respuesta» por fecha y lee cada respuesta como `GET /api/v1/respuesta`, desde la foto guardada. Los archivos
son:

- `api_frecuencias/docs/evidencias/respuesta/respuesta_reto.md`: tablas por día, ruta, franja y hora;
- `api_frecuencias/docs/evidencias/respuesta/respuesta_2025-11-19.json`, `respuesta_2025-11-22.json`,
  `respuesta_2025-11-23.json` y `respuesta_2026-01-01.json`: la respuesta completa de la API de cada día, con el
  `execution_id` que la calculó;
- `api_frecuencias/docs/evidencias/respuesta/api_en_vivo.txt`: la misma respuesta por HTTP.

Además del 1-ene-2026 se muestran un laboral, un sábado y un domingo de noviembre de 2025: el miércoles 19, el sábado
22 y el domingo 23. Son posteriores al corte del modelo (31-ago-2025) y tienen datos observados, así que el pronóstico
se puede contrastar con lo que pasó.

## Respuesta corta

**Mañana (1-ene-2026, festivo).** Cifras de `respuesta_2026-01-01.json`, calculado en la ejecución
`c90ed32c-30b4-49c9-b4f3-3dd4f139b4e7`:

- **SILENCIO.** Despachar cada 10 min en el pico de la mañana y en el valle (hoy se programa cada 7,60 y 8,55 min): 92
  salidas en el día (hoy 109,7). Se esperan 4.609 pasajeros (P10–P90: 2.933–5.874); bastan 21 de los 27 buses
  disponibles.
- **CRA 54.** Cada 9,00 min en el pico de la mañana, 9,60 en el valle y 9,43 en el pico de la tarde (hoy 4,46, 4,67
  y 7,03): 100 salidas (hoy 185,2). Se esperan 7.509 pasajeros (5.681–10.191), con 20 de los 45 buses.
- **CL 72.** Cada 10 min hasta las 16 h y cada 8,79 min en el pico de la tarde (hoy, entre 9,17 y 16,53 min): 93
  salidas (hoy 65,6). Se esperan 3.007 pasajeros (1.771–4.340), con 23 de los 27 buses.
- **Recaudo esperado del día:** 48.126.159 COP en las tres rutas, con la tarifa neta de 3.182 COP por pasajero.
- **Atención inmediata:** al consultar, había 21 alertas abiertas en las tres rutas, 7 críticas. Para el propio
  1-ene-2026 hay una alerta crítica ALT-010 (modelo degradado) en CL 72 (sección 5).

**Un día laboral típico (19-nov-2025).** Cifras de `respuesta_2025-11-19.json`:

- **SILENCIO.** Cada 2,40 min a las 5 h, la hora de más demanda (1.881 pasajeros esperados), y cada 8,18 y 8,00 min
  en el pico de la mañana y el valle (hoy 6,86 y 6,77): 135 salidas (hoy 158,5). Se esperan 11.469 pasajeros
  (8.458–14.160); se observaron 10.548. A las 8 h hay 44 buses en ruta de 45. El plan ahorra 93,4 vehículos-hora
  (5,40 millones COP de costo operativo) a cambio de 0,9 min más de espera media.
- **CRA 54.** Cada 3,00 min en el pico de la mañana (hoy 2,87), 4,00 en el valle (hoy 3,50) y 7,46 en el pico de la
  tarde (hoy 3,93): 247 salidas (hoy 290,2). Se esperan 22.800 pasajeros (19.054–26.560); se observaron 22.492. Usa
  los 79 buses de la flota a las 8 h. Ahorra 152,4 vehículos-hora (8,87 millones COP) con la misma sobreocupación
  esperada (267,2 frente a 266,7 pasajeros). La hora de las 5 sale no viable: la demanda pide 34 salidas (una cada
  1,76 min) y el headway mínimo gobernado de 2 min permite 30, que es lo que programa el plan.
- **CL 72.** Cada 10,00 min en el pico de la mañana (hoy 10,13), 9,41 en el valle (hoy 11,61) y 9,97 en el pico de la
  tarde (hoy 12,03): 110 salidas (hoy 96,5). Se esperan 7.525 pasajeros (5.320–9.628); se observaron 7.115. Usa 54,7
  vehículos-hora más (2,97 millones COP) y a cambio baja la espera media de 6,76 a 5,85 min y la sobreocupación
  esperada de 27,5 a 12,3 pasajeros.
- **Balance del día en las tres rutas:** 191,1 vehículos-hora menos que lo programado, 11,30 millones COP menos de costo
  operativo (108,10 frente a 119,40) y un recaudo esperado de 132.985.644 COP.

## Cómo se arma cada parte de la respuesta

| Parte | De dónde sale | Evidencia de la pieza |
|---|---|---|
| Cada cuánto despachar | Plan del día (`optimizacion.plan_dia`, el MILP de D5, el mismo de `GET /recommendations/plan`): salidas por hora de 4 a 20 h que minimizan costo operativo + espera + sobrecarga esperada + ingreso perdido, sujeto a la flota disponible, la suavidad y los dos límites gobernados de `threshold_config`: el headway mínimo (`headway_minimo_min`, 2 min; ninguna hora pasa de floor(minutos / mínimo) salidas) y el headway máximo efectivo, min(`headway_maximo_min`, 2 × `espera_max_min`) = 10 min (supuesto S12). Se compara con el intervalo programado (D1); un festivo se compara con la programación de domingo o festivo, el mismo tipo de día del plan | `api_frecuencias/docs/evidencias/optimizacion/` |
| Viabilidad | Una hora es viable si el solver terminó en óptimo, los buses en ruta no superan la flota (conteo cada 15 min), el intervalo queda entre el mínimo y el máximo efectivo, y la demanda no pide más salidas de las que permite el headway mínimo. Si no, sale `viable = false` con el motivo y el plan programa la mejor aproximación ejecutable, sin forzar una cifra (§10.3, §18). Cada hora trae además los límites activos, la demanda de diseño y el margen | `api_frecuencias/tests/unit/test_respuesta.py` |
| Cuántos pasajeros | Modelo activo `hgb_fv2_20250831_s42`, hora por hora (ventana de 60 min al inicio de cada hora), con la banda P10–P90 calibrada `v2`. Ese mismo pronóstico alimenta el plan, así que plan y pasajeros coinciden hora a hora. En la prueba de nov–dic 2025 el modelo tiene WAPE de 14,77 % (IC95 13,10–16,87) frente a 21,18 % de la regla manual B1 | `api_frecuencias/docs/evidencias/modelo/decision_fv2.md` |
| Cuántos vehículos | Máximo de buses en ruta a la vez con el plan, frente a la flota disponible; al lado, la fórmula de §10.3, ceil(ciclo / headway) | `api_frecuencias/docs/evidencias/respuesta/respuesta_reto.md` |
| Flota y recaudo | Vehículos-hora, costo operativo (26.400 COP por bus-hora y 1.991 COP por km), espera media y sobreocupación esperada del plan frente a lo programado, con las fórmulas del MILP; recaudo = pasajeros esperados × tarifa neta de 3.182 COP | `api_frecuencias/datos/costos_fuente.json` |
| Atención inmediata | Las alertas **abiertas ahora** en `ai_frecuencias.alert` (nueva, reconocida o asignada en el instante de la consulta), las críticas primero, y aparte las alertas detectadas en la fecha consultada | `api_frecuencias/docs/evidencias/alertas/` |
| Trazabilidad | `model_id`, `calibracion_version`, `fuente_pronostico`, `umbrales_version`, `execution_id` de la ejecución que calculó la foto, último ciclo diario, último día con datos y la fuente de cada cifra (RNF-011) | `api_frecuencias/docs/evidencias/respuesta/respuesta_<fecha>.json` |

## 1. ¿Cada cuánto despachar?

Headway de la franja = minutos operados / salidas de la franja, recomendado (plan) y programado hoy (D1). La API lo
devuelve en `resumen_despacho.por_franja` y el detalle hora por hora en `cada_cuanto_despachar`. Fuente:
`respuesta_reto.md`, sección «Cada cuánto despachar, por franja».

**SILENCIO**

| Tipo de día | Madrugada (4-5 h) | Pico mañana (6-8 h) | Valle (9-16 h) | Pico tarde (17-19 h) | Salidas del día |
|---|---|---|---|---|---|
| Laboral (19-nov-2025) | cada 2,99 min (hoy 3,00) | cada 8,18 min (hoy 6,86) | cada 8,00 min (hoy 6,77) | cada 9,97 min (hoy 7,26) | 135 (hoy 158,5) |
| Sábado (22-nov-2025) | cada 6,92 min (hoy 4,00) | cada 7,50 min (hoy 6,05) | cada 9,80 min (hoy 7,16) | cada 10,00 min (hoy 8,04) | 109 (hoy 145,9) |
| Domingo (23-nov-2025) | cada 8,60 min (hoy 5,59) | cada 10,00 min (hoy 7,60) | cada 10,00 min (hoy 8,55) | cada 9,91 min (hoy 9,60) | 92 (hoy 109,7) |
| Festivo (1-ene-2026) | cada 8,60 min (hoy 5,59) | cada 10,00 min (hoy 7,60) | cada 10,00 min (hoy 8,55) | cada 9,91 min (hoy 9,60) | 92 (hoy 109,7) |

**CRA 54**

| Tipo de día | Madrugada (4-5 h) | Pico mañana (6-8 h) | Valle (9-16 h) | Pico tarde (17-19 h) | Salidas del día |
|---|---|---|---|---|---|
| Laboral (19-nov-2025) | cada 2,43 min (hoy 2,51) | cada 3,00 min (hoy 2,87) | cada 4,00 min (hoy 3,50) | cada 7,46 min (hoy 3,93) | 247 (hoy 290,2) |
| Sábado (22-nov-2025) | cada 3,22 min (hoy 3,26) | cada 3,11 min (hoy 2,78) | cada 5,00 min (hoy 3,76) | cada 8,57 min (hoy 5,06) | 208 (hoy 260,7) |
| Domingo (23-nov-2025) | cada 5,86 min (hoy 4,14) | cada 7,20 min (hoy 4,46) | cada 8,73 min (hoy 4,67) | cada 8,53 min (hoy 7,03) | 114 (hoy 185,2) |
| Festivo (1-ene-2026) | cada 7,17 min (hoy 4,14) | cada 9,00 min (hoy 4,46) | cada 9,60 min (hoy 4,67) | cada 9,43 min (hoy 7,03) | 100 (hoy 185,2) |

**CL 72**

| Tipo de día | Madrugada (4-5 h) | Pico mañana (6-8 h) | Valle (9-16 h) | Pico tarde (17-19 h) | Salidas del día |
|---|---|---|---|---|---|
| Laboral (19-nov-2025) | cada 4,99 min (hoy 4,93) | cada 10,00 min (hoy 10,13) | cada 9,41 min (hoy 11,61) | cada 9,97 min (hoy 12,03) | 110 (hoy 96,5) |
| Sábado (22-nov-2025) | cada 7,54 min (hoy 6,16) | cada 10,00 min (hoy 9,09) | cada 10,00 min (hoy 11,81) | cada 10,00 min (hoy 13,31) | 101 (hoy 91,4) |
| Domingo (23-nov-2025) | cada 10,00 min (hoy 9,17) | cada 10,00 min (hoy 12,67) | cada 10,00 min (hoy 14,12) | cada 8,79 min (hoy 16,53) | 93 (hoy 65,6) |
| Festivo (1-ene-2026) | cada 10,00 min (hoy 9,17) | cada 10,00 min (hoy 12,67) | cada 10,00 min (hoy 14,12) | cada 8,79 min (hoy 16,53) | 93 (hoy 65,6) |

Lectura operativa:

- **Según el plan, en SILENCIO y CRA 54 sobra oferta fuera de la madrugada.** El plan conserva la frecuencia alta de
  las 5 h del día laboral, la hora de más demanda en las dos rutas: SILENCIO, 25 salidas, una cada 2,40 min, para
  1.881 pasajeros esperados; CRA 54, 30 salidas, el tope del headway mínimo, para 2.580. Después alarga el intervalo en
  el valle y en el pico de la tarde, donde la demanda baja. En CRA 54 el festivo pide menos que el domingo (100 frente a
  114 salidas), porque se esperan 7.509 pasajeros frente a 10.130.
- **CL 72 tiene menos servicio del que pide la regla de espera.** Hoy se programan intervalos de 11,61 a 12,03 min en el
  valle y la tarde del día laboral, y de 12,67 a 16,53 min el domingo. Todos superan el máximo efectivo de 10 min que
  sale de la espera máxima de 5 min (§5.1, leída como espera media = headway / 2, supuesto S12). El plan sube a 110
  salidas en el laboral (hoy 96,5) y a 93 en domingo y festivo (hoy 65,6).
- **En domingo y festivo manda el nivel de servicio, no la demanda.** SILENCIO y CL 72 tienen el mismo plan el
  23-nov-2025 y el 1-ene-2026: casi todas las horas quedan en el headway máximo efectivo de 10 min, porque la demanda
  esperada cabe con menos buses. Si el área operativa confirma otro máximo para esos días, basta con cambiar
  `headway_maximo_min` o `espera_max_min` con `PUT /api/v1/thresholds` (versión nueva) y volver a calcular.
- **Una hora no viable de 204 horas-ruta, explicada.** En CRA 54, a las 5 h del laboral, la demanda pide 34 salidas
  (una cada 1,76 min), más de las 30 que permite el headway mínimo gobernado de 2 min. El plan programa 30, cada
  2,00 min (la mejor aproximación ejecutable), y la respuesta marca la hora `viable = false` con el motivo, sin forzar
  una cifra (§10.3 y §18). En SILENCIO, a las 4 h del domingo y del festivo, la hora tiene 0,2 minutos operados y una
  sola salida: es viable, porque con una salida no hay intervalo entre salidas que medir dentro de la hora, y el plan del
  día y la respuesta aplican ahora la misma regla. Fuente: `respuesta_reto.md`, columna «Horas no viables».

## 2. ¿Cuántos pasajeros se esperan?

Pasajeros del día con la banda P10–P90 (suma de las bandas de cada hora) y lo que se observó ese día en la serie
empaquetada. Fuente: `respuesta_reto.md`, secciones «Resumen por día y ruta» y «Contraste con los pasajeros
observados».

| Día | Ruta | Esperados (P10–P90) | Observados | Error del día | Horas dentro de P10–P90 |
|---|---|---|---|---|---|
| Laboral 19-nov-2025 | SILENCIO | 11.469 (8.458–14.160) | 10.548 | 8,7 % | 11 de 17 |
| Laboral 19-nov-2025 | CRA 54 | 22.800 (19.054–26.560) | 22.492 | 1,4 % | 10 de 17 |
| Laboral 19-nov-2025 | CL 72 | 7.525 (5.320–9.628) | 7.115 | 5,8 % | 12 de 17 |
| Sábado 22-nov-2025 | SILENCIO | 9.105 (7.017–11.174) | 8.867 | 2,7 % | 16 de 17 |
| Sábado 22-nov-2025 | CRA 54 | 19.117 (15.708–22.006) | 18.963 | 0,8 % | 16 de 17 |
| Sábado 22-nov-2025 | CL 72 | 6.002 (4.269–7.731) | 5.726 | 4,8 % | 13 de 17 |
| Domingo 23-nov-2025 | SILENCIO | 5.434 (3.884–7.022) | 5.314 | 2,3 % | 16 de 17 |
| Domingo 23-nov-2025 | CRA 54 | 10.130 (7.822–11.984) | 9.547 | 6,1 % | 14 de 17 |
| Domingo 23-nov-2025 | CL 72 | 3.424 (2.004–4.675) | 3.528 | −2,9 % | 16 de 17 |
| Festivo 1-ene-2026 | SILENCIO | 4.609 (2.933–5.874) | sin datos todavía | — | — |
| Festivo 1-ene-2026 | CRA 54 | 7.509 (5.681–10.191) | sin datos todavía | — | — |
| Festivo 1-ene-2026 | CL 72 | 3.007 (1.771–4.340) | sin datos todavía | — | — |

Error del día = (esperados − observados) / observados; un valor positivo significa que el modelo esperaba más
pasajeros de los que llegaron. En los nueve días-ruta con datos, el total observado cae dentro de la banda del día y el
error del total va de −2,9 % a 8,7 %. Por hora, 124 de las 153 horas-ruta (81 %) quedan dentro de su banda P10–P90,
en línea con la cobertura objetivo de 80 %. El 1-ene-2026 todavía no tiene datos: es el día que se planea. La
respuesta trae además los pasajeros de cada hora con su P10 y P90 (`pasajeros_esperados.por_hora`).

## 3. ¿Cuántos vehículos se requieren?

«En ruta (pico)» es el máximo de buses en ruta a la vez con el plan, contado cada 15 minutos con el ciclo de cada
hora, como en la restricción de flota del MILP. «§10.3» es el máximo de ceil(ciclo / headway) en las horas completas:
supone que la frecuencia de la hora se mantiene un ciclo completo. «Programado hoy» es el mismo conteo en ruta con las
salidas programadas hoy. Fuente: `respuesta_reto.md` y `respuesta_<fecha>.json` (bloque `vehiculos`).

| Día | Ruta | En ruta (pico), plan | Hora | Flota disponible | §10.3 | Programado hoy |
|---|---|---|---|---|---|---|
| Laboral 19-nov-2025 | SILENCIO | 44 | 8 h | 45 | 86 | 47 |
| Laboral 19-nov-2025 | CRA 54 | 79 | 8 h | 79 | 106 | 80 |
| Laboral 19-nov-2025 | CL 72 | 30 | 18 h | 45 | 47 | 29 |
| Sábado 22-nov-2025 | SILENCIO | 31 | 9 h | 43 | 44 | 42 |
| Sábado 22-nov-2025 | CRA 54 | 67 | 7 h | 75 | 91 | 73 |
| Sábado 22-nov-2025 | CL 72 | 27 | 13 h | 43 | 27 | 25 |
| Domingo 23-nov-2025 | SILENCIO | 21 | 18 h | 27 | 21 | 29 |
| Domingo 23-nov-2025 | CRA 54 | 23 | 8 h | 45 | 26 | 39 |
| Domingo 23-nov-2025 | CL 72 | 23 | 19 h | 27 | 21 | 17 |
| Festivo 1-ene-2026 | SILENCIO | 21 | 18 h | 27 | 21 | 29 |
| Festivo 1-ene-2026 | CRA 54 | 20 | 17 h | 45 | 24 | 39 |
| Festivo 1-ene-2026 | CL 72 | 23 | 19 h | 27 | 21 | 17 |

- En el día laboral, CRA 54 usa toda la flota disponible en la hora pico (79 de 79) y SILENCIO casi toda (44 de 45).
  La programación de hoy pide 47 y 80 buses en ruta a la vez, más de los que hay; el plan no pasa la flota en ningún
  instante.
- En domingo y festivo, la programación de SILENCIO pide 29 buses con una flota de 27; el plan necesita 21.
- La fórmula de §10.3 da cifras mayores (86 y 106 en el laboral) porque supone que la frecuencia de la hora pico se
  mantiene un ciclo completo, que dura de 3 a casi 5 horas según la ruta y la hora. Por eso la respuesta informa como
  requerimiento el conteo de buses en ruta y deja la cifra de §10.3 al lado.
- Extreme debe confirmar el ciclo y la flota por franja (§19): son medianas de 2025 de D1 y no siempre cuadran entre
  sí, como muestra la columna «Programado hoy» cuando supera la flota disponible.

## 4. Flota y recaudo

Comparación del plan con lo programado hoy, con las mismas fórmulas de costo, espera y sobrecarga del MILP de D5.
Costos con fuente pública de 2026: 26.400 COP por bus-hora de conductor y 1.991 COP por km
(`api_frecuencias/datos/costos_fuente.json`). Fuente de las cifras: `respuesta_reto.md`, «Resumen por día y ruta».

| Día | Ruta | Vehículos-hora ahorrados | Costo operativo plan / hoy (millones COP) | Espera media plan / hoy (min) | Sobreocupación plan / hoy (pasajeros) | Recaudo esperado (millones COP) |
|---|---|---|---|---|---|---|
| Laboral 19-nov-2025 | SILENCIO | 93,4 | 31,28 / 36,68 | 5,29 / 4,41 | 50,2 / 33,5 | 36,49 |
| Laboral 19-nov-2025 | CRA 54 | 152,4 | 52,88 / 61,75 | 3,02 / 2,48 | 267,2 / 266,7 | 72,55 |
| Laboral 19-nov-2025 | CL 72 | −54,7 | 23,94 / 20,97 | 5,85 / 6,76 | 12,3 / 27,5 | 23,94 |
| Sábado 22-nov-2025 | SILENCIO | 145,9 | 24,98 / 33,45 | 6,45 / 4,83 | 14,6 / 7,7 | 28,97 |
| Sábado 22-nov-2025 | CRA 54 | 191,3 | 43,45 / 54,42 | 3,53 / 2,73 | 61,8 / 94,1 | 60,83 |
| Sábado 22-nov-2025 | CL 72 | −37,5 | 21,63 / 19,55 | 6,29 / 6,98 | 4,0 / 2,2 | 19,10 |
| Domingo 23-nov-2025 | SILENCIO | 59,8 | 19,57 / 23,36 | 6,89 / 5,84 | 0,4 / 1,7 | 17,29 |
| Domingo 23-nov-2025 | CRA 54 | 203,4 | 21,40 / 34,76 | 5,47 / 3,37 | 27,7 / 30,7 | 32,23 |
| Domingo 23-nov-2025 | CL 72 | −89,0 | 18,47 / 13,00 | 6,03 / 8,70 | 4,6 / 13,6 | 10,90 |
| Festivo 1-ene-2026 | SILENCIO | 59,8 | 19,57 / 23,36 | 6,85 / 5,79 | 13,5 / 12,4 | 14,66 |
| Festivo 1-ene-2026 | CRA 54 | 243,1 | 18,78 / 34,76 | 6,24 / 3,39 | 80,6 / 28,1 | 23,89 |
| Festivo 1-ene-2026 | CL 72 | −89,0 | 18,47 / 13,00 | 6,01 / 8,73 | 7,5 / 18,7 | 9,57 |

Vehículos-hora ahorrados = programado − recomendado; un valor negativo significa que el plan usa más.

El balance que propone el sistema:

- **SILENCIO y CRA 54: menos flota con un costo de espera acotado.** En el día laboral el plan ahorra 93,4 y 152,4
  vehículos-hora (5,40 y 8,87 millones COP de costo operativo). La espera media sube 0,9 y 0,5 min. En CRA 54 la
  sobreocupación esperada queda igual (267,2 frente a 266,7 pasajeros), porque el plan reparte las salidas según la
  demanda de cada hora; en SILENCIO sube de 33,5 a 50,2. En el festivo el ahorro de CRA 54 es mayor (243,1
  vehículos-hora, 15,98 millones COP), pero la espera media pasa de 3,39 a 6,24 min y la sobreocupación esperada de
  28,1 a 80,6 pasajeros. El valor del tiempo de espera (7.000 COP por hora) y la penalidad por sobreocupación (10.000
  COP por pasajero) deciden ese punto; son parámetros que debe validar el área operativa (§5.1), y con una penalidad
  mayor el plan programaría más salidas.
- **CL 72: más servicio donde hoy falta.** El plan agrega 54,7 vehículos-hora en el laboral (2,97 millones COP más de
  costo) y 89,0 en domingo y festivo (5,47 millones COP más). A cambio, la espera media baja de 6,76 a 5,85 min en el
  laboral y de 8,73 a 6,01 min en el festivo, y la sobreocupación esperada baja a menos de la mitad en el laboral, el
  domingo y el festivo (en el sábado sube de 2,2 a 4,0 pasajeros).
- **Balance del día laboral en las tres rutas:** 191,1 vehículos-hora y 11,30 millones COP menos de costo operativo
  (108,10 frente a 119,40 millones), con 0,9 min más de espera en SILENCIO, 0,5 en CRA 54 y 0,9 menos en CL 72.
- **Recaudo.** Extreme no suministró la tarifa (§19). La respuesta usa la tarifa pública 2026 del Área Metropolitana
  (3.700 COP) por 0,86 que retiene el operador: 3.182 COP netos por pasajero, la misma que usa el MILP de D5
  (`param_d5(fuente=True)`). Con ella, el recaudo esperado es de 132,99 millones COP el laboral 19-nov, 108,90 el sábado
  22-nov, 60,42 el domingo 23-nov y 48,13 el festivo 1-ene-2026. El MILP estima además el ingreso que se pierde o se
  gana al cambiar la oferta (campo `ingreso_perdido_cop`). Elasticidad: β estimada ≈ 0,70 por observación, sin validar
  en campo; el plan usa 0,5 por prudencia; la sensibilidad está en
  `api_frecuencias/docs/evidencias/optimizacion/sensibilidad.md`; el piloto la mide.

## 5. ¿Qué situaciones requieren atención inmediata?

La respuesta trae dos listas por ruta, rotuladas:

- `atencion_inmediata`: las alertas **abiertas ahora**, es decir, en estado nueva, reconocida o asignada en el instante
  de la consulta (`atencion_resumen.consultado_en`), de cualquier fecha, las críticas primero y luego las más
  recientes. Es lo que hay que atender ya; cada alerta se gestiona con `PATCH /api/v1/alerts/{id}/status`;
- `alertas_de_la_fecha`: las detectadas en la fecha consultada (día de Bogotá), en cualquier estado.

`atencion_resumen` da los conteos completos por severidad. En la evidencia, después de una corrida del ciclo diario
hasta el 31-dic-2025, había abiertas ahora 8 alertas en SILENCIO (3 críticas y 5 preventivas), 6 en CRA 54 (2 y 4) y 7
en CL 72 (2 y 5): 21 en total, 7 críticas. Para el 1-ene-2026 hay una alerta crítica ALT-010 (modelo degradado) en
CL 72 (`respuesta_2026-01-01.json`).

Situaciones que vigila el sistema, con sus umbrales vigentes (`app/servicios/alertas.py`, versionados en
`threshold_config`; la migración 0007 agrega los de la ALT-002 observada y de la ruptura), y cuántas alertas se esperan
por ruta y día con la banda calibrada `v2` en el backtest del 15-sep al 31-dic-2025 (324 días-ruta):

| Familia | Código | Situación | Nivel | Se activa cuando | Por ruta y día |
|---|---|---|---|---|---|
| Pronóstico | ALT-001 | Alta demanda prevista | Preventiva o crítica | La carga crítica P90 de la hora (factor de carga del optimizador × P90 de la demanda de la franja recomendada) supera la capacidad programada por hora (buses/h × capacidad); crítica si también la supera el pronóstico puntual | 0,435 |
| Pronóstico | ALT-002 | Sobreocupación | Crítica | La ocupación esperada en el punto de carga máxima, con el mismo factor de carga del optimizador, llega al 90 % | 0,315 |
| Pronóstico | ALT-003 | Frecuencia insuficiente | Preventiva | La frecuencia programada no cumple el nivel de servicio de la hora (la carga crítica P90 no cabe en la capacidad efectiva); va dentro de ALT-001 si las dos salen en la misma franja | 0,380 |
| Pronóstico | ALT-004 | Frecuencia excesiva | Informativa | La ocupación esperada en el punto de carga máxima queda bajo el 30 % y hay más buses que los recomendados | 0,031 |
| Observada | ALT-002 | Sobreocupación observada | Crítica | La ocupación observada (factor de carga × pasajeros / puestos ofrecidos) llega al 90 % en horas con al menos 2 salidas, 2 horas seguidas | 0,691 |
| Observada | ALT-005 | Caída anormal de demanda | Preventiva | La demanda real cae más del 30 % frente al patrón del modelo y bajo el P10, 2 horas seguidas | 0,142 |
| Observada | ALT-006 | Despacho ausente o tardío | Crítica | No hay despacho dentro del headway programado más la tolerancia (5 min), o faltan más del 50 % de las salidas esperadas | 0,127 |
| Observada | ALT-007 | Desviación del pronóstico | Preventiva | La demanda real sale de la banda P10–P90 con un error de al menos 15 %, 2 horas seguidas | 0,204 |
| Observada | ALT-007 (ruptura) | Ruptura de comportamiento (RF-009) | Preventiva | CUSUM de dos lados sobre el residuo diario relativo (real frente al pronóstico) de los últimos 56 días, con k = 0,5, h = 6, 28 días de referencia y un cambio medio de al menos 8 % | 0,012 |
| Observada | ALT-008 | Consolidado anómalo | Preventiva | Subidas, bajadas o viajes con un z robusto de 3,5 o más frente a las 8 semanas previas del mismo tipo de día | 0,062 |
| Observada | ALT-009 | Datos incompletos | Crítica | Falta información obligatoria o llega con 2 períodos de ingesta de atraso | 0,000 |
| Monitoreo | ALT-010 | Modelo degradado | Crítica | El WAPE móvil supera la tolerancia de 20 % (el WAPE de la regla manual) | se evalúa en cada ciclo con el monitoreo |

Fuentes: `api_frecuencias/docs/evidencias/alertas/backtest_alertas_pronostico.md` (ALT-001 a ALT-004 del ciclo de las
6:00) y `api_frecuencias/docs/evidencias/alertas/backtest_alertas.md` (ALT-002 observada, ALT-005 a ALT-009 y la
ruptura). Las cifras vigentes se comprueban con `api_frecuencias/scripts/cifras_vigentes.py`.

**Total: 2,399 alertas por ruta y día, unas 7,2 por día en las tres rutas.** Por familia:

- **de pronóstico, 1,161 por ruta y día:** ALT-001 0,435, ALT-002 0,315, ALT-003 0,380 y ALT-004 0,031. Antes de
  medir la carga con el factor de carga del optimizador eran 2,065 (0,889, 0,858, 0,318 y 0). El lift de ALT-001 sube
  de 1,12 a 1,77 y el de ALT-002 de 1,14 a 2,01: ahora la alerta y la recomendación usan la misma ocupación. ALT-003
  queda con lift 0,75 porque es una alerta de riesgo sobre el P90 y, cuando la recomendación no es viable, se cumple
  por definición;
- **observadas, 1,238 por ruta y día:** ALT-002 observada 0,691, ALT-005 0,142, ALT-006 0,127, ALT-007 0,204, ruptura
  0,012, ALT-008 0,062 y ALT-009 0. Sin las dos familias nuevas, ALT-005 a ALT-009 suman 0,534, frente a 6,077 con las
  reglas anteriores. Después de una ALT-006, el problema de despacho sigue en la hora siguiente 8,3 veces más a menudo
  que en una hora cualquiera (lift 8,30). La ruptura detectó 4 cambios en el periodo, con 1,644 falsas alarmas por cada
  100 días-ruta sin cambio; desde esta versión corre también en el ciclo diario de producción;
- **de monitoreo:** ALT-010 se evalúa en cada ciclo con el monitoreo del modelo, cuando el error móvil pasa la
  tolerancia; no entra en el backtest.

Sin incidentes etiquetados por Extreme, la precisión real no se puede medir todavía: los porcentajes de confirmación y
el lift son aproximaciones con la persistencia de la condición. La muestra etiquetada por dos revisores está en
`api_frecuencias/docs/evidencias/alertas/revision_doble/`.

## Limitaciones

Son las que la misma respuesta declara en `limitaciones` (`respuesta_2026-01-01.json`):

- El plan de despacho y los pasajeros esperados salen del mismo pronóstico horario del modelo activo
  `hgb_fv2_20250831_s42` (P10, P50 y P90 calibrados de cada hora). Se puede calcular cualquier día con variables,
  incluido el día siguiente al último dato.
- El headway mínimo gobernado en `threshold_config` (`headway_minimo_min`, 2 min por omisión) es una restricción
  explícita del plan (§10.2): ninguna hora programa más de floor(minutos / headway mínimo) salidas. Donde la demanda
  pediría más, la hora sale «no viable» con su motivo y el plan muestra la mejor aproximación ejecutable, sin forzar
  una cifra (§10.3 y §18).
- La «espera máxima» de §5.1 se interpreta como la espera media del pasajero (headway / 2 con llegadas aleatorias): el
  headway máximo efectivo es min(`headway_maximo_min`, 2 × `espera_max_min`). Es el supuesto S12, con su pregunta a
  Extreme en `api_frecuencias/docs/hallazgos_extreme.md`.
- La banda P10–P90 del día suma las bandas de cada hora, así que es más ancha que la banda del total del día.
- La tarifa no la suministró Extreme (§19): el recaudo es una cifra de referencia.
- Ciclo, flota disponible e intervalo programado son medianas de 2025 por ruta, tipo de día y hora (D1). Extreme debe
  confirmarlos por franja (§19).
- El valor del tiempo de espera (7.000 COP/h) y la penalidad por pasajero sobre la capacidad (10.000 COP) son
  supuestos que debe validar el área operativa (§5.1); la elasticidad se explica en la sección 4.
- En un festivo (por ejemplo, el 1-ene-2026 o el lunes 17-nov-2025), el plan y la programación de comparación usan los
  parámetros de domingo o festivo, porque `parametros_operativos_hora` no tiene una programación propia para esos
  días; la respuesta lo advierte.
- La lista «abiertas ahora» depende del momento de la consulta, no de la fecha consultada; las alertas de la fecha van
  aparte, en `alertas_de_la_fecha`.

## La respuesta por HTTP

`api_frecuencias/docs/evidencias/respuesta/api_en_vivo.txt` registra la API levantada con uvicorn contra la base
temporal, con la autenticación encendida, un trabajador de la cola y el ciclo diario ya corrido:

- sin clave, `GET /api/v1/respuesta` responde 401; el operador recibe 403 en `POST /api/v1/respuesta/calcular`; una
  ruta fuera de la lista da 422;
- para una fecha sin foto (2025-03-04), 404 `sin_calcular` con la pista `POST /api/v1/respuesta/calcular`, el cuerpo
  sugerido y el rol analista;
- `POST /api/v1/respuesta/calcular {"fecha": "2026-01-01"}` (analista) responde 202 en 249 ms. La ejecución queda «ok»
  64,9 s después del POST, en segundo plano: el proceso recién arrancado carga el modelo, arma las variables con la
  serie validada, pronostica 51 horas-ruta, resuelve tres MILP y guarda la foto y las 51 filas del plan del día, con
  otros procesos de prueba corriendo en el mismo equipo de 6 núcleos. Con el proceso ya caliente, el cálculo de CRA 54
  del 19-nov-2025 queda «ok» 2,1 s después del POST, y en el proceso del script cada día de tres rutas tarda de 0,8 a
  2,7 s (`respuesta_reto.md`);
- después, 21 lecturas de `GET /api/v1/respuesta?fecha=2026-01-01` desde la foto tardan 32 ms de mediana y 60 ms como
  máximo; las de CRA 54 del 19-nov-2025, 17 ms de mediana;
- la trazabilidad trae `model_id` `hgb_fv2_20250831_s42`, `calibracion_version` `v2`, `fuente_pronostico`
  `modelo_activo`, la versión de umbrales (5 en la base de la evidencia), el `execution_id` del cálculo y `datos_hasta`
  2025-12-31;
- la exportación CSV del 1-ene-2026 trae 51 filas (3 rutas × 17 horas) y la XLSX, 10.650 bytes;
- `api_respuesta_CRA54_2025-11-19.json` es una respuesta completa por HTTP, con las alertas abiertas ahora.

## Cómo reproducirlo

```bash
cd api_frecuencias
python scripts/respuesta_reto.py --en-vivo           # base temporal local, copia de datos/; escribe docs/evidencias/respuesta/
uvicorn app.main:app --port 8000                     # con DATABASE_URL y «alembic upgrade head»
curl -X POST -H "X-API-Key: $CLAVE_ANALISTA" -H "Content-Type: application/json" \
     -d '{"fecha": "2026-01-01"}' "http://localhost:8000/api/v1/respuesta/calcular"
curl -H "X-API-Key: $CLAVE_OPERADOR" "http://localhost:8000/api/v1/respuesta?ruta=CRA%2054&fecha=2026-01-01"
curl -H "X-API-Key: $CLAVE_OPERADOR" -o respuesta.xlsx "http://localhost:8000/api/v1/respuesta/export?formato=xlsx"
```

`tests/unit/test_respuesta.py` y `tests/integracion/test_respuesta_api.py` verifican:

- el contrato y que cada cifra coincide con el plan del día y con el modelo activo;
- la viabilidad y que bajar `espera_max_min` baja el headway máximo efectivo;
- la fecha por omisión con los datos recientes;
- las alertas abiertas ahora y las de la fecha;
- los permisos: sin clave 401, operador 403 en el POST, analista 202 y lectura 200 desde la foto, sin pronóstico ni
  MILP dentro del GET;
- el 404 `sin_calcular` y que todo instante sale en America/Bogota (-05:00).

El resultado está en `api_frecuencias/docs/evidencias/respuesta/pytest_respuesta.txt`.
