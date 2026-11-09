# Esquema de los datos de la consola de despacho (replay)

Los genera `sistema_tiempo_real/generar_replay.py`. Son **días históricos de 2025 reproducidos como si fueran en vivo**: una foto
cada 5 min de 04:00 a 21:00 (205 fotos por día) para las tres rutas. En cada foto el motor solo usó información con marca de
tiempo ≤ t (salvo la posición del bus, interpolada para dibujarla; ver `meta.notas`). Los textos están en español y los números sin
formatear (la página debe mostrarlos con formato español: `1.234,5`).

Hay dos salidas con el **mismo objeto de día** (sección `dias`):

| Archivo | Qué trae | Cómo se genera |
|---|---|---|
| `replay_datos.js` | `window.REPLAY = { meta, mapa, dias }` con los **6 días de ejemplo** en un solo archivo (6,6 MB). Es el formato original; la consola lo usa solo como respaldo si falta `dias/indice.js` | `generar_replay.py` (2 procesos, ~2 min) |
| `dias/indice.js` + `dias/AAAA-MM-DD.js` | Un archivo por día de 2025 con GPS (todos menos el último de cada mes: 353 días) y un índice. La consola carga el índice al abrir y cada día solo cuando se elige, con una etiqueta `<script>` que inyecta (funciona con doble clic, `file://`, sin servidor) | `generar_replay.py --por-dia --baja-prioridad [--procesos 3]` (hasta 3 procesos; se puede interrumpir y retomar; `--estado` dice cuántos días están al día) |

**Versiones de los datos por día** (`meta.por_dia.version_datos`, `version` de cada día del índice y `version_datos` del objeto de
día): 2 = con `hechas` y `fallidas` (consola v2); 3 = correcciones de la verificación de la consola v2 (7-oct-2026): campos
marcados «v3» abajo y el motor corregido (modo plan semanal con datos malos, salidas contadas desde su registro); **4** (13-oct-2026)
= el plan semanal, el motor y el oráculo usan D5 con los **costos con fuente** de `costos/` (26.400 COP por bus-hora de conductor,
1.991 COP por km, tarifa neta 3.182; `comun.param_d5()`), el plan que reasigna salidas en vez de recortarlas (`x_corrida_1` de
`costos/resultados/d5_reoptimizado_decisiones.parquet`), y cada día y el meta traen `plan_param`. Los días de las versiones 2 y 3
tienen el plan con los supuestos iniciales de D5 (60.000 / 1.500 / 3.000, `x_D5`). La consola lee las tres: mientras una
regeneración no termina, el índice mezcla días de varias versiones (con un día anterior a la 4, la ayuda dice que su plan es el de
los supuestos). La regeneración con la versión 4 terminó la madrugada del 13-oct-2026: los 353 días están en esa versión.

Coordenadas: `[lat, lon]` en grados WGS84 con 5 decimales. Horas: cadenas `"HH:MM"`. Minutos del día: enteros desde la medianoche.
Segundos del día: enteros desde la medianoche. Vectores por hora: 17 posiciones, horas de salida 4 a 20 (`meta.horas`); el índice
`i` corresponde a la hora `4 + i`.

## `meta`

| Campo | Tipo | Contenido |
|---|---|---|
| `generado` | texto | fecha y hora de generación |
| `paso_min` | entero | 5 (minutos entre fotos) |
| `inicio`, `fin` | texto | `"04:00"`, `"21:00"` |
| `horas` | [int] | `[4, 5, …, 20]` |
| `capacidad` | entero | 50 pasajeros por bus (sentados + de pie) |
| `rutas` | [obj] | `{id, nombre, color, primer_punto}`: id 2 SILENCIO `#2f6fb3`, 16 CRA 54 `#d9731a`, 21 CL 72 `#6a3d9a`; `primer_punto` = punto de control donde se mide el apelotonamiento |
| `campos_bus` | [texto] | orden de los campos de cada bus en `snapshots[].rutas[ruta].buses` |
| `plan_param` | obj | **v4**: parámetros del plan semanal con que el generador produce los días: `{bus_hora, km, tarifa, elasticidad, penalidad, espera, fuente}` = COP por bus-hora de conductor (26.400,22), COP por km evitable (1.991,24), tarifa neta por pasajero (3.182), elasticidad de la demanda a la frecuencia (0,5), penalidad por pasajero sobre la capacidad (10.000), valor de la hora de espera (7.000) y el origen de los costos (`"costos con fuente (2026)"`; `"supuestos D5"` sería 60.000 / 1.500 / 3.000). Cada día trae los suyos (abajo) |
| `notas` | [texto] | advertencias para mostrar al pie de la consola. La quinta describe el plan semanal y los costos de `meta.plan_param`, y dice que un día de una versión anterior a la 4 se generó con los supuestos iniciales de D5. **Solo en `dias/indice.js`** y solo mientras conviven versiones (`por_dia.al_dia < por_dia.generados`): una sexta nota, «Regeneración pendiente: …», con cuántos días generados siguen con una versión anterior; desaparece cuando todos tienen la versión actual |
| `por_dia` | obj | **solo en `dias/indice.js`**: `{archivos, formato, version_datos, previstos, generados, pendientes, al_dia, generando, mb_total}`; `version_datos` = 4 (versión del generador; rehace los días de una versión anterior), `previstos` = días del catálogo (353), `al_dia` = días ya generados con esa versión (v4), `generando` = el generador sigue corriendo y quedan días sin archivo, `mb_total` = peso de los archivos por día (suma de los `kb` entre 1024: MiB, aunque `--estado` lo rotule «MB»; 120,6 con los 353 días de la versión 4, unos 126 MB) |

## `mapa`

| Campo | Tipo | Contenido |
|---|---|---|
| `centro` | [lat, lon] | centro sugerido del mapa (Barranquilla) |
| `rutas` | {nombre: [[lat, lon], …]} | trazado de cada ruta (simplificado, ida y vuelta), clave = nombre de la ruta |
| `puntos` | {nombre: [{id, lat, lon, minuto}]} | puntos de control de la ruta; `minuto` = minuto típico de paso desde la salida |

## Archivos por día (`dias/`)

**`dias/indice.js`** define `window.REPLAY_INDICE = { meta, mapa, dias, pendientes, sin_gps }`. Se reescribe después de cada día
generado (escritura atómica), así que la consola ve los días nuevos al recargar o al volver a abrir el calendario.

| Campo | Tipo | Contenido |
|---|---|---|
| `dias` | [obj] | días ya generados, en orden de fecha: `{fecha, etiqueta, grupo, contexto, ejemplo, dia_semana, tipo_dia, kb}` (`kb` = peso del archivo del día) y, v3, `etiqueta_previa` (ver abajo) y `version` |
| `pendientes` | [texto] | fechas del catálogo que todavía no se generaron |
| `sin_gps` | [texto] | últimos días de cada mes (no tienen GPS: no se pueden reproducir) |

**`dias/AAAA-MM-DD.js`** define `window.REPLAY_DIA_GZ["AAAA-MM-DD"] = "<base64>"`: el objeto de día de la sección `dias` (abajo) en
JSON UTF-8, comprimido con gzip y pasado a base64. Pesa unos 380-420 KB un laboral, 360 KB un sábado y 120-250 KB un domingo o
festivo (1,0-1,6 MB sin comprimir). La consola lo descomprime en el navegador con `DecompressionStream('gzip')`. Para leerlo en
Python:

```python
import base64, gzip, json, re
s = open("sistema_tiempo_real/replay/dias/2025-06-03.js", encoding="utf-8").read()
dia = json.loads(gzip.decompress(base64.b64decode(re.findall(r'"([A-Za-z0-9+/=]{100,})"', s)[-1])))
```

`dias/catalogo.json` (metadatos de los días generados, para retomar), `dias/generar.log` (un renglón por día: peso y segundos, con
el proceso que lo hizo) y `dias/.generando/` (reclamos de días y procesos vivos mientras corre con varios procesos) son del
generador; la consola no los usa. Cada día se escribe en un archivo temporal que reemplaza al anterior de forma atómica, así que la
consola nunca lee un archivo a medio escribir.

## `dias` (objeto de día)

| Campo | Tipo | Contenido |
|---|---|---|
| `fecha` | texto | `"2025-06-03"` |
| `etiqueta` | texto | días de ejemplo: Laboral normal, Sábado, Domingo, Festivo, Carnaval, Caída inesperada; demás días: Laboral, Sábado, Domingo, `Festivo · <nombre>`, `Carnaval · <día>`, Vacaciones escolares, Regreso a clases, Fin de semestre, Falla de registro, Receso escolar, Caída sin explicar, Lluvia fuerte, Mañana floja |
| `descripcion` | texto | una frase sobre el día; termina con «Pasajeros reales frente al pronóstico semanal: …». Cuenta también lo que solo se sabe después (caída de la demanda, falla de registro, lluvia caída, día atípico de E10): la consola la muestra solo al llegar a las 21:00 |
| `etiqueta_previa`, `descripcion_previa` | texto | **v3**: lo que se sabe del día antes de que empiece (calendario, festivo, Carnaval, periodo escolar, partido programado). Por ejemplo, el 10-oct: «Receso escolar» / «Viernes de la semana de receso escolar de octubre.» (al final: «Caída inesperada»); el 29-jul: «Laboral» / «Martes corriente de julio.» (al final: «Falla de registro»). La consola los muestra hasta las 21:00; con archivos de la versión 2 los deduce de la etiqueta y la descripción |
| `version_datos` | entero | **v3**: 3; **v4**: 4 |
| `plan_param` | obj | **v4**: los parámetros con que se calcularon `plan` (salidas, horario, oráculo) y las recomendaciones del motor de este día, con las mismas claves que `meta.plan_param` (en un archivo anterior a la v4 no existe: su plan es el de los supuestos iniciales de D5) |
| `dia_semana`, `tipo_dia` | texto | p. ej. `"martes"`, `"Laboral"` (`Laboral`, `Sábado`, `Domingo/festivo`) |
| `grupo` | texto | **solo en los archivos por día**: `laboral`, `sabado`, `domingo`, `festivo`, `carnaval` o `especial` (atípicos de E10, lluvia fuerte de E9, mañana floja del 20-nov) |
| `contexto` | texto o null | **solo en los archivos por día**: periodo del calendario escolar de Barranquilla (E10), p. ej. `"vacaciones escolares de mitad de año"` |
| `ejemplo` | bool | **solo en los archivos por día**: `true` en los 6 días de ejemplo |
| `plan` | {ruta: obj} | plan semanal de D5 para ese día (ver abajo) |
| `real` | {ruta: obj} | lo que pasó realmente (para el resumen al final del día y para la lista de salidas hechas; la consola no debe mostrar nada posterior a la hora del reloj) |
| `snapshots` | [obj] | 205 fotos, en orden (ver abajo) |

`plan[ruta]`: `salidas_hora` [17 int] salidas válidas por hora del plan semanal (**v4**: D5 con los costos con fuente, igual a
`x_corrida_1` de `costos/resultados/d5_reoptimizado_decisiones.parquet`; antes, `x_D5` con los supuestos); `horario` [texto] horario
minuto a minuto del plan; `pax_plan_hora` [17 int] pasajeros previstos por hora de salida (pronóstico semanal, definición E7);
`oraculo_hora` [17 int] salidas que D5 habría elegido conociendo la demanda real (referencia; solo para el resumen; **v4**: resuelto
con los mismos costos del plan, `plan_base.oraculo_ruta`; antes, `x_D5_oraculo` de D5 con los supuestos); `flota` entero, buses
disponibles del plan.

`real[ruta]`: `pax_hora` [17 int] pasajeros reales por hora de salida (E7); `salidas_hora` [17 int] salidas reales (no fallidas) por
hora; `salidas` [[`"HH:MM"`, vehículo]] todas las salidas reales del día en orden (la consola puede mostrar las que tengan hora ≤ t);
`salidas_seg` [int] (**campo nuevo**) el segundo del día de cada una de esas salidas, en el mismo orden: es la salida real que ve el
motor (`salida_real` ≤ t), así que la consola la muestra como «hecha» exactamente cuando el reloj pasa ese segundo;
`fallidas` [[`"HH:MM"`, vehículo, seg_salida, seg_se_sabe]] (**campo nuevo**) las salidas que al final del día resultan fallidas, con
el segundo en que el motor lo sabe (al cerrar con menos de 20 km, o 30 min después de salir sin pasar por un punto distinto del patio).
Hasta ese segundo el motor las cuenta como salidas hechas; `salidas` no las trae porque son las válidas del día completo. **v3**: un
quinto campo, `seg_se_conoce` (como `salidas_conoce`).
`salidas_conoce` [int] (**v3**) por cada salida de `salidas`, el primer segundo en que el motor la cuenta: el de la salida o, si el
viaje se registró después (`fecharegistro`; 0,85 % de las salidas), el del registro. `salidas_seg` sigue siendo la hora de la salida
(la que se muestra).
`fallas_temporales` [[seg_salida, vehículo, seg_desde, seg_hasta]] (**v3**) salidas que a los 30 min no habían pasado por ningún
punto distinto del patio (el motor deja de contarlas) y que pasaron después (vuelven a contar desde `seg_hasta`).
Los segundos de v3 son el primer segundo entero en que el motor ya lo sabe (las marcas de tiempo tienen fracción de segundo), así
que la lista de la consola coincide con el motor también en los bordes.

### `snapshots[k]`

| Campo | Tipo | Contenido |
|---|---|---|
| `t` | texto | hora de la foto, `"07:15"` |
| `factor_comun` | número | factor de demanda común de las 3 rutas (1 = como el plan; 1,10 = 10 % más) |
| `datos_ok` | bool | `false` si hay corte de GPS (`cobertura` < 0,5) o falla de datos de los contadores o del registro (guarda de datos): el motor recomienda el plan semanal (la falla de datos tiene memoria: sigue en `false` hasta que lo visto en las últimas 2 h vuelve a 0,8-1,25 de lo esperado). **v3**: con `datos_ok` falso, `salidas_reopt_hora` de la hora en curso y las siguientes = plan semanal, `proximas_60` = horario del plan entre la foto y 60 min después, sin ajuste ni alertas de hueco, cambio de plan, regularidad o flota al límite |
| `cobertura` | número | fracción de viajes recientes con evidencia GPS (0–1) |
| `rutas` | {ruta: obj} | estado y recomendación por ruta (claves `"SILENCIO"`, `"CRA 54"`, `"CL 72"`) |

`rutas[ruta]`:

| Campo | Tipo | Contenido |
|---|---|---|
| `buses` | [[vehiculo, lat, lon, ocupacion, ultimo_punto, salida_min]] | buses en la calle. `vehiculo` texto (número interno), `ocupacion` pasajeros a bordo según el contador al terminar la última visita (puede ser `null`; > 50 = sobrecupo), `ultimo_punto` id del punto de control actual, `salida_min` minuto del día en que salió |
| `en_ruta`, `en_patio`, `flota` | int | buses en la calle, disponibles en patio y flota disponible |
| `salidas_real`, `salidas_plan` | int | salidas hechas hasta t y salidas que el plan semanal tenía hasta t |
| `ultima_salida` | texto o null | hora de la última salida real |
| `pax_obs`, `pax_esp` | int | pasajeros ya vistos hoy (contadores + cierres) y los que se esperaban ver a esta hora según el plan |
| `factor`, `f10`, `f90` | número | factor de demanda de la ruta y su intervalo de 80 % |
| `pax_ajustado_hora`, `pax_p10_hora`, `pax_p90_hora` | [17 int] | pronóstico ajustado por hora de salida (E7) y su intervalo de 80 %; para comparar con `plan.pax_plan_hora` |
| `salidas_reopt_hora` | [17 int] | salidas por hora del plan reoptimizado (horas pasadas = realizadas; hora en curso = total de la hora) |
| `salidas_real_hora` | [17 int] | salidas realizadas hasta t por hora |
| `proximas` | [texto] | próximas 3 salidas recomendadas (`"HH:MM"`) |
| `ajuste` | [retraso_min, adelanto_min] | ajuste recomendado de la próxima salida (ya aplicado en `proximas[0]`) |
| `restantes_plan`, `restantes_reopt` | int | salidas que faltan hoy según el plan semanal y según el reoptimizado |
| `alertas` | [[tipo, nivel, mensaje]] | `tipo`: `demanda`, `hueco`, `sobrecupo`, `flota`, `regularidad`, `plan`, `datos`; `nivel`: `alta`, `media`, `info` |
| `proximas_60` | [texto] | **campo nuevo**: todas las salidas recomendadas de los siguientes 60 min (`proximas_salidas` del motor; la primera con el ajuste aplicado). `proximas` son sus 3 primeras |
| `ajuste_motivos` | [texto] | **campo nuevo**: el motivo de cada ajuste de la próxima salida (los mismos textos que las alertas de `regularidad`): buses pegados en el primer punto (retrasar) o último bus lleno (adelantar). Lista vacía si no hay ajuste |
| `programados` | [[`"HH:MM"`, vehículo]] | **campo nuevo**: programación de Sobusa conocida en t: viajes de la ruta ya registrados (`fecharegistro` ≤ t) que todavía no salen (salida real > t o nunca), con su hora programada (`fechasalida`) y su vehículo, en orden de hora programada; se omiten los programados hace más de 30 min. **v3**: también se omiten los viajes que ya arrancaron según su propio registro o el GPS (`fechainicio` o primera visita ≤ t, aunque el motor todavía no detecte la salida), y cada uno trae un tercer campo con el segundo en que arranca (si arranca ese día), para que la consola lo quite cuando el reloj pase ese segundo. La consola asigna a cada despacho el primer programado (en orden) cuya hora esté a ±15 min de la del despacho y sin salida; si no hay, «por asignar». El vehículo es el valor final del registro (no se conoce si se cambió después) |
| `hechas` | [[seg, vehículo]] | **campo nuevo**: salidas que el motor cuenta como hechas en t (no fallidas en t) con salida en los últimos 15 min, en orden; `seg` = segundo del día de la salida. Son exactamente las del estado del motor, también las que más tarde se declaran fallidas o las de un bus que todavía no se ha movido. **v3**: un tercer campo, si la salida se declara fallida después, con el segundo en que el motor lo sabe (la consola la quita de la lista en ese segundo) |

Los campos nuevos no cambian ninguno de los anteriores: los 6 días de ejemplo regenerados con el generador nuevo dan exactamente los
mismos valores en todos los campos de `replay_datos.js`, incluidas etiqueta y descripción (comprobado campo por campo en los seis).

## Cómo los usa la consola (`consola_despacho.html`)

- **Día**: calendario de 2025 (marcas de festivo, Carnaval y día especial; los días de ejemplo con borde; los pendientes punteados y
  los sin GPS en gris), lista de festivos, Carnaval y días especiales, botones de día anterior y siguiente y los 6 días de ejemplo.
- **Reloj**: x1 = tiempo real (1 s del reloj = 1 s), x10, x60, x300 y x900. La foto vigente es la última con `t` ≤ reloj; entre
  fotos, cada bus se desliza de su posición en la foto k a la de la foto k+1, y los que salen entre las dos aparecen en el patio a su
  segundo exacto de salida (`salidas_seg`).
- **Despachos en orden** (las tres rutas mezcladas, filtro por ruta): hechos = `hechas` de la foto vigente (menos las que se saben
  fallidas antes del reloj) más las salidas del día (`salidas`, y `fallidas` hasta que se saben) que el motor conoce después de la
  foto (`salidas_conoce`) y antes del reloj; salidas hoy = `salidas_real` de la foto más el cambio de cada salida entre la foto y
  el reloj (conocidas, fallidas, `fallas_temporales`); próximos = `proximas_60` de la foto vigente menos las que ya cubrió una
  salida posterior a la foto; vehículo = el primer `programados` a ±15 min y sin salida (ni arranque antes del reloj); `ajuste` y
  `ajuste_motivos` para «ajustado»; «atrasado» si pasó más de 1 min de la hora recomendada sin salida (con el mensaje de `hueco` si
  lo hay). Con `datos_ok` falso, modo plan semanal: próximos = horario del plan entre el reloj y 60 min después (estado «plan»),
  aviso «No llegan los registros de despacho desde HH:MM…» (o «los datos de GPS» si `cobertura` < 0,5) y «Salidas hoy: sin datos».
  Así la lista coincide con el estado del motor en cada foto y entre fotos solo usa lo que se sabe a la hora del reloj (con datos
  v3, en 4 días y 5.937 instantes, 17.811 instantes-ruta: «hechos hoy» igual al motor en todos y la lista igual salvo 6 bordes de
  1 s del límite de 15 min).
- **Gráficos y alertas**: como antes, con la foto vigente: barras de `plan.salidas_hora` frente a `salidas_reopt_hora` (y
  `salidas_real_hora` para las horas pasadas); `pax_obs` frente a `pax_esp`; al final del día, `real.pax_hora` y `plan.oraculo_hora`.
  Con `datos_ok` falso, las barras de lo que falta usan el plan (en la hora en curso, el horario del plan desde la foto) y se ocultan
  las alertas de hueco, cambio de plan, regularidad y flota al límite que traen los archivos de la versión 2 (el motor de la versión
  3 ya no las emite con datos malos).
- **Descripción del día**: hasta las 21:00, `etiqueta_previa` y `descripcion_previa` (con archivos de la versión 2 se deducen de
  `etiqueta` y `descripcion`); a las 21:00, `etiqueta`, `descripcion` y el resultado real.
- **Plan del día**: la ayuda «Cómo funciona» muestra `plan_param` del día abierto (costos del plan); si el archivo es anterior a la
  versión 4, dice que ese día se generó con los supuestos iniciales de D5 (plan y motor). Las notas de `meta.notas` van al pie de
  la ayuda; con un día anterior a la versión 4, la nota del plan («Plan semanal = …») se reemplaza por la de ese día (supuestos
  iniciales de D5), y la nota «Regeneración pendiente» del índice se muestra tal cual mientras exista.

## Buses por las calles (`dias/calles/`)

Los genera `sistema_tiempo_real/calles.py` (y `generar_replay.py` al escribir cada día); la consola y la vista 3D (`vista_3d.html`)
los usan si existen. Versión actual de los archivos por día de `calles/` (numeración propia, distinta de la de `dias/AAAA-MM-DD.js`):
**3** (la 1 no traía `pax` ni la densidad; la vista 3D exige la 2; la 3 añade el mismo día con nuestro plan). `rutas.js` sigue en la
versión 2: no cambió.

| Archivo | Qué trae |
|---|---|
| `dias/calles/rutas.js` | `window.REPLAY_CALLES_RUTAS = {version, rutas: {nombre: {lat: [...], lon: [...], s: [...], largo_m, dens_paso_m, subidas: [...], bajadas: [...], subidas_fuera_del_trazado}}}`: el trazado de cada ruta por las calles (de `rutas_segmentos`, simplificado a 1 m) y los metros desde el inicio en cada vértice. Recorrido de ida y vuelta. **v2**: `subidas` y `bajadas` son las de todo 2025 en pasos de `dens_paso_m` = 50 m a lo largo del trazado (de `conteo_celdas_dia`: cada celda se reparte entre los pasos del trazado a menos de 120 m de su centro); `subidas_fuera_del_trazado` es la fracción de subidas en celdas a más de 120 m (2,8 %, 4,1 % y 4,3 %). Pesa 97 KB. |
| `dias/calles/AAAA-MM-DD.js` | `window.REPLAY_CALLES_GZ["AAAA-MM-DD"] = "<base64>"`: gzip de `{version, fecha, rutas: {nombre: {"<vehículo>\|<minuto de salida>": [[t0, s0, t1, s1, ...], ...]}}, pax: {...}}`, con t en segundos del día y s en metros desde el inicio del trazado. Los nudos son la salida y cada visita a un punto de control. La clave es la misma que la de `snapshots[].rutas[r].buses` (campos 0 y 5). Si hay más de una trayectoria con la misma clave (despacho duplicado), se usa la que pasa más cerca de la posición de la foto. **v2**: `pax` tiene las mismas claves y, por cada trayectoria, `[sub0, baj0, sub1, baj1, ...]`: subidas y bajadas del tramo entre el nudo i y el i+1 (cada visita de `cache/visitas.parquet` va al tramo que empieza en el último nudo anterior o igual a su inicio; la visita 0, al primero). **v3**: los campos de abajo (`perdidos`, `plan`, `pax_plan`, `resumen`, `plan_meta`); `rutas` y `pax` no cambian. Pesa unos 130 KB un laboral y 70 KB un domingo (65–70 y 40–45 KB en la versión 2). |
| `dias/calles/resumen_2025.js` | `window.REPLAY_CALLES_RESUMEN = {version, generado, dias, primera_fecha, ultima_fecha, pendientes, plan_meta, total, por_tipo_dia, por_hora}`: la suma del `resumen` de todos los archivos por día que están en la versión 3 (los de una versión anterior o sin `resumen` solo se cuentan en `pendientes`), que escribe `sistema_tiempo_real/resumen_calles.py` (la suma vigente, del 13-oct-2026 a las 07:43, tiene los 353 días y 0 pendientes) y lee `vista_3d.html` para el bloque «Todo 2025 con este modelo» del panel «Hoy con el plan». `total`, cada entrada de `por_tipo_dia` (claves `Laboral`, `Sábado` y `Domingo/festivo`, el `tipo_dia` del catálogo) y cada hora de `por_hora` (claves `"4"` … `"20"`, la hora de la salida registrada) traen `{dias, real: {total, por_dia}, plan: {total, por_dia}}`: `total` suma sobre los días los campos del resumen (`salidas`, `salidas_validas`, `salidas_programar`, `buses_hora`, `km`, `pax`, `sobre_capacidad`, `costo_Mcop`, `perdidos_beta`, `perdidos_sin_bus`, `ganados_simetrico`, `pasajes_perdidos_Mcop`; enteros donde el resumen los tiene enteros, una decimal en el resto; los campos que un lado no tiene valen 0: `salidas_programar` en `real`, `salidas_validas` en `plan`, y en `real` los cuatro últimos) y añade `espera_media_min`, la espera de todos los días ponderada por `pax`; `por_dia` es `total` dividido entre `dias`, con una decimal. `plan_meta` es el del primer día sumado. Pesa unos 25 KB. |
| `dias/calles/resumen_2025.csv` | Lo mismo en una tabla (separador `;`, coma decimal): una fila por grupo («Todo 2025» y cada tipo de día) y lado (`real`, `plan`) con los totales y la espera media. |

### Versión 3: el mismo día con nuestro plan

Junto a lo que pasó (`rutas`, `pax`), el archivo trae lo que habría pasado ese mismo día con el plan semanal del proyecto (D5 con los
costos con fuente, el que calcula `plan_base.plan_dia`): los buses del plan, las mismas personas reales tomando esos buses, las que
se pierden y un resumen real frente a plan. Cómo se calcula: `sistema_tiempo_real/README.md`, sección «El mismo día con nuestro
plan». Si el plan del día no se pudo calcular, el archivo se escribe en la versión 2 (sin estos campos) y la vista 3D sigue en modo
Real; al pedir el plan muestra un aviso corto.

| Campo | Tipo | Contenido |
|---|---|---|
| `perdidos` | {ruta: {clave: [[p0, p1, …], …]}} | por cada trayectoria real (mismas claves y misma estructura de listas que `pax`, un entero por tramo): personas que subieron a ese bus real en ese tramo pero que con el plan se van, por la regla de β o porque no pasa un bus del plan en 20 min. Los viajes reales con salida registrada (el minuto de la clave) fuera de 04:00–20:59 traen ceros (no entran en el modelo ni en el resumen, aunque su GPS empiece antes de las 21:00) |
| `plan` | {ruta: {`"P\|<minuto de salida>"`: [[t0, s0, t1, s1, …]]}} | viajes del plan; la clave es «P» y los minutos desde la medianoche de la salida del plan; una sola trayectoria por clave (si el plan tuviera dos salidas en el mismo minuto, la segunda lleva la clave `"P\|<minuto>\|2"`). La trayectoria copia la del viaje real completo (≥ 20 km) de la misma ruta y día que sale del patio más cerca en el tiempo, con todos los tiempos desplazados a la salida del plan |
| `pax_plan` | {ruta: {clave del plan: [[sub0, baj0, sub1, baj1, …]]}} | subidas y bajadas por tramo de cada viaje del plan: las personas reales que con el plan toman ese bus |
| `resumen` | obj | `{"dia": {"real": R, "plan": Q, "pronostico": F}, "por_hora": {"4": {"real": R, "plan": Q, "pronostico": F}, …, "20": {…}}}`; la hora es la de la **salida registrada** del viaje (4 a 20, como texto): el minuto de la clave (`"<vehículo>\|<minuto>"` en los reales, `"P\|<minuto>"` en los del plan) dividido entre 60, la misma hora con que D5 cuenta las salidas reales y con que la consola las muestra, y no la del primer nudo GPS (que en la mitad de los viajes se adelanta a la salida registrada: p50 3 min, hasta 59 min). Suma las tres rutas. `F` es el pronóstico con que se hizo el plan (abajo) |
| `plan_meta` | obj | `fuente` (texto: de dónde salen los costos del plan), `bus_hora`, `km`, `tarifa`, `elasticidad_plan` (los valores de D5 que de verdad usó el plan: `COSTO_BUS_HORA`, `COSTO_KM`, `TARIFA`, `ELASTICIDAD`), `beta` (0,70, la elasticidad de E7 con que se cuentan los perdidos), `espera_max_min` (20), `viajes_plan_sin_patio` (viajes del plan a los que se copió una trayectoria que no empieza en el patio porque ese día ninguna lo hacía) y `metodo` (texto corto) |

`R` y `Q` traen los mismos campos, salvo uno propio de cada lado: `R` trae `salidas_validas` (int: de sus `salidas`, las que son
salidas **válidas**, cerradas y no canceladas —`finalizado = S` y `cancelada = N`, la regla R1 de E1 con que D1 cuenta `n_S0` y en
cuya unidad D5 decide `x_h`; las demás son viajes que recorrieron la ruta con pasajeros pero el sistema marcó «CANCELADA
AUTOMATICAMENTE»: 548 de 600 el 3-jun, 331 de 402 el 8-jun) y `Q` trae `salidas_programar` (int: Σ por ruta de
ceil(`x_plan` / (1 − `tasa_no_valido`)) de la tabla de D5, los buses que Sobusa tendría que despachar en esa hora para que salgan
las `x_h` válidas del plan, con la tasa histórica de salidas programadas que no resultan válidas de la ruta, tipo de día y hora;
576 para 507 salidas el 3-jun). Los campos comunes: `salidas` (int), `buses_hora` (suma de las duraciones de los viajes, en horas: último nudo menos
primero según el GPS, aunque el primer nudo preceda a la salida registrada, y sin contar un nudo final que llega más de 2 h después
del anterior: una visita registrada cuando el viaje ya había terminado, p. ej. el patio al día siguiente; `rutas` conserva esos
nudos y la vista 3D aplica el mismo recorte al dibujar), `km` (suma de |Δs| entre nudos, en km, con el mismo recorte), `pax`
(personas que subieron), `espera_media_min` (promedio de la espera de quienes subieron), `sobre_capacidad` (suma por viaje de
max(0, ocupación máxima − 50), con la ocupación acumulada por tramo recortada en ≥ 0, como `aBordo` en la vista 3D), `costo_Mcop`
(= (`buses_hora` × `plan_meta.bus_hora` + `km` × `plan_meta.km`) / 10⁶, millones de COP), `perdidos_beta`, `perdidos_sin_bus`,
`ganados_simetrico` y `pasajes_perdidos_Mcop` (= (`perdidos_beta` + `perdidos_sin_bus`) × `tarifa` / 10⁶). En `R` los cuatro últimos
valen 0, para que el lector no distinga casos. En `Q`, `ganados_simetrico` = Σ_h pax_h × β × (x_h − n0_h) / n0_h en las horas con
más salidas en el plan que en la realidad (contabilidad simétrica; el resto del resumen es la conservadora del proyecto). En la
regla de β y en `ganados_simetrico`, `x_h` es la columna `x_plan` de la tabla de `plan_base.plan_dia` (la decisión de D5 por hora)
y `n0_h` las salidas **válidas** de la hora h entre los viajes del modelo (por ruta; sumadas las rutas es `salidas_validas` de
esa hora en `R`), la misma unidad en que D5 decide `x_h`: contar en `n0_h` también los viajes no válidos mezclaba unidades e
inflaba la pérdida (el 3-jun, 6.246 perdidos por β con todos los viajes frente a 4.974 con los válidos). Las personas de los viajes
no válidos sí entran al modelo (toman un bus del plan o se pierden). Desde que `plan_base.horario` no pasa una salida a la hora
siguiente, `x_h` coincide con las claves `P|min` del archivo contadas por hora (`--verificar` lo comprueba). Límite: `x_h` está
decidido por hora de salida **programada** (la tabla de D5) y `n0_h` se cuenta por hora de salida **registrada**; en el día casi
coinciden (548 frente a 565 el 3-jun) pero por hora no (hora 5: 58 frente a 81), y la pérdida por β cambia hasta un 8 % según la
base (README, «Supuestos y límites»).

`F` (`pronostico`) es el pronóstico con que se hizo el plan, 7 días antes, para que el lector pueda decir «este día tuvo X % más
pasajeros de lo previsto»: sumado sobre las tres rutas, de la tabla de `plan_base.plan_dia(fecha)` y redondeado a enteros.
`pax_previsto` (columna `pax_pred`: la demanda prevista con que D5 decidió; `prediccion` si no estuviera), `pax_real_tabla`
(columna `real`: los pasajeros de ese día por hora de salida programada según D1/E1, la serie con que se mide el pronóstico; es
`null` si la tabla no la trae, p. ej. en fechas futuras), `salidas_validas_real` (columna `n_S0`: salidas válidas reales por hora
de salida programada; `null` si falta) y `salidas_plan` (columna `x_plan`; igual a `salidas` de `Q`). En `resumen.dia` lleva además
`fuente` (texto, `fuente_pronostico` de la tabla: «E1 fuera de muestra, h = 7 días» en 2025, «E11 modelo_final.py» en fechas
futuras) y cada campo del día es la suma de las horas. `pax_real_tabla` y `salidas_validas_real` no tienen por qué coincidir con
`pax` y `salidas_validas` de `R`: la tabla cuenta por hora de salida **programada** y todos los viajes válidos (565 el 3-jun),
mientras `R` cuenta por el minuto de la salida registrada y solo los viajes con trayectoria GPS y salida de 04:00 a 20:59 (548); y
`pax` de `R` son las subidas contadas en los tramos (46.980), no el `numeropasajeros` del cierre de los viajes válidos (43.128).
El 3-jun: 39.858 previstos frente a 43.128 reales (el pronóstico se quedó un 7,6 % corto).

Para leerlo en Python: `calles.leer_dia("2025-06-03")` devuelve el objeto, y `python sistema_tiempo_real/calles.py --verificar
2025-06-03` corre los chequeos de consistencia (el archivo es de la generación actual —trae `salidas_validas`, `salidas_programar`
y `pronostico`; si lo escribió un `calles.py` anterior se detiene ahí y pide regenerarlo—, cada persona real termina en un bus del
plan o perdida, bajadas = subidas del plan, salidas del resumen = viajes del archivo y del horario, salidas del plan por hora =
`x_plan` de D5, `salidas_validas` = viajes del modelo con `valido_e1` en la caché y ≤ `salidas` en cada hora, `salidas_programar`
≥ salidas del plan y = Σ ceil(`x_plan` / (1 − `tasa_no_valido`)) de la tabla, `pronostico` = el de la tabla con `salidas_plan` =
salidas del plan y el día = suma de las horas, perdidos del orden de la fórmula de β con `n0_h` en salidas válidas, costos y
pasajes coherentes). `python sistema_tiempo_real/calles.py --pendientes` lista los días de la consola cuyo archivo falta, no tiene
plan o lo escribió un `calles.py` anterior (`generar_replay.py --por-dia` importa el módulo una vez por proceso: una corrida que
arrancó antes de un cambio sigue escribiendo con el módulo viejo); `--todos` los rehace.
