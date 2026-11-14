# Procedencia de `motor_d5`

`motor_d5` es la copia, dentro de la API, del optimizador D5 del proyecto (MILP de salidas por hora con PuLP y CBC).
La cadena de copias es:

```
experimentos/D5_optimizacion_milp/milp.py  ->  EntregaFinal/dash_app/motor/milp.py  ->  app/servicios/motor_d5/milp.py
sistema_tiempo_real/plan_base.py  ->  EntregaFinal/dash_app/motor/plan_base.py (versión reducida)  ->  motor_d5/plan_base.py
sistema_tiempo_real/comun.py  ->  EntregaFinal/dash_app/motor/comun.py  ->  motor_d5/comun.py (carpeta de datos por DATA_DIR)
```

## Cambio deliberado (9 de noviembre de 2026)

SonarQube marcó en `milp.py` la regla `python:S8495` (una función no debe devolver tuplas de distinto largo):
`resolver_dia(..., devolver_detalle=False)` devolvía `(x, estado, holgura)` y, con `devolver_detalle=True`,
`(x, estado, holgura, componentes)`. Se separó en tres funciones, sin tocar la formulación:

| Función | Devuelve |
|---|---|
| `_resolver_milp(...)` | núcleo común: arma y resuelve el MILP; `(x, estado, holgura, niveles)` |
| `resolver_dia(...)` | `(x, estado, holgura)`, como antes |
| `resolver_dia_detalle(...)` | `(x, estado, holgura, componentes)`, lo que antes daba `devolver_detalle=True` |

`plan_base.py` cambia solo su única llamada: `milp.resolver_dia_detalle(...)` en lugar de
`milp.resolver_dia(..., devolver_detalle=True)`. `comun.py` no cambia.

Comprobación de paridad: con las tres rutas (SILENCIO, CRA 54 y CL 72) y tres fechas de 2025 (4 de marzo, 14 de junio y
21 de septiembre), la versión original de `dash_app/motor/milp.py` y esta copia dan el mismo plan `x`, el mismo estado
del solver, la misma holgura y los mismos cuatro componentes de costo (9 de 9 casos idénticos). La prueba
`tests/unit/test_motor_d5.py` deja fija esa paridad (largo de cada tupla y mismo plan que la versión original) y las
pruebas de `tests/unit/test_optimizacion.py` y `tests/unit/test_optimizacion_objetivo.py` siguen pasando.

## Huellas SHA-256

| Archivo | Antes del cambio (igual a `dash_app/motor/`) | Después del cambio |
|---|---|---|
| `milp.py` | `a04f0ac49534ec6ffe3f5013394c0ed88484b8af4817196c42e1d6bf6ed7ff99` | `1ac63706219f8e6a203d2e8f3b187bf30191c6a4ed6dabad27e4b80987378625` |
| `plan_base.py` | `2ad8ccf451ce27c6479f4cd8a77d54b8f84741618dc7979c8c0d839faaf6556d` | `346abddb29e73905b541f0ba86c3f6955bde169766a8cd1afcc0c2f1d3bca0d2` |

La huella «después» corresponde al contenido con el comentario de cabecera que explica el cambio. Ninguna prueba ni
manifiesto fija la huella de estos archivos; el modelo de demanda (`datos/modelos/`) no se toca.

## Headway mínimo gobernado (se aplica fuera de esta copia)

`insumos_d5_2025.parquet` trae para cada hora una cota `nmax` de salidas tomada de lo que la operación ya tuvo (hasta
35 por hora, un intervalo de 1,71 min), mientras que `param_d5()` declara `INTERVALO_MIN = 2.0` sin usarlo en el
MILP. Para que el plan respete el headway mínimo gobernado de `threshold_config` (`headway_minimo_min`, §10.2
«sujeto a headway mínimo»), `app/servicios/optimizacion.py` (`_plan_d5` y `_resolver_d5_acotado`) baja esa cota a
floor(minutos / headway mínimo) y vuelve a resolver el mismo MILP (`milp.resolver_dia_detalle`, mismos insumos,
costos, flota y suavidad) solo cuando alguna hora del plan de D5 pasa el tope. Esta copia (`milp.py`, `plan_base.py`
y `comun.py`) no cambia: si ninguna hora pasa el tope, el plan es exactamente el de `plan_base.plan_ruta`. Las horas
donde el tope corta lo que pedía D5 salen marcadas (`limitada_por_headway_minimo`) y la respuesta de
`GET /api/v1/respuesta` las informa «no viables» con su motivo (§10.3 y §18).

## Plan del día con el modelo activo (se arma fuera de esta copia)

`optimizacion.plan_dia` usa este mismo MILP (`milp.resolver_dia_detalle`, `milp.costos_por_nivel`,
`milp.fracciones_en_ruta`, `plan_base.entradas_d5` y `plan_base.horario`, sin cambios) con otros insumos, para
cualquier fecha con variables:

- pasajeros de cada hora = P50 del modelo activo (inferencia con h = 60 al inicio de la hora, sin factor intradía);
  la carga crítica es lognormal con mediana factor de carga × P50 y dispersión ln(P90 / P50) / z_0,90 de la banda
  calibrada (mínimo 0,02, la del oráculo de D5);
- minutos operados, km, CV de los intervalos y tasa de viajes no válidos: mediana 2025 de `insumos_d5_2025.parquet`
  por ruta, tipo de día y hora; ciclo, flota, capacidad por bus e intervalo programado:
  `parametros_operativos_hora.parquet`, con el ajuste local vigente encima (flota y ciclo de
  `app/servicios/flota_ciclo.py`, `PUT /api/v1/catalogos/flota`; capacidad de toda la ruta,
  `PUT /api/v1/catalogos/capacidad`); la oferta de referencia del ingreso perdido es la programada (minutos /
  intervalo programado);
- cotas de cada hora desde `threshold_config`: nmin = ceil(minutos / headway máximo efectivo), con headway máximo
  efectivo = min(headway_maximo_min, 2 × espera_max_min), y tope = floor(minutos / headway mínimo);
- costos del bus-hora, del km, del tiempo de espera y de la sobrecarga desde `threshold_config` (pesos α, β, γ
  aplicados a esos costos); desde la migración 0010, también la tarifa (`tarifa_cop`), la elasticidad
  (`elasticidad`, 0,5), la suavidad (`delta_suavidad`, 6) y la hora de inicio de la suavidad
  (`hora_inicio_suavidad`, 7), que `optimizacion._p_milp` pone en las claves `TARIFA`, `ELASTICIDAD`, `DELTA` y
  `HORA_INICIO_SUAVIDAD` del diccionario de parámetros del MILP (`optimizacion.PARAMETROS_PLAN`). Sin versión en la
  tabla rigen los de `param_d5()`, que son los mismos valores. Esta copia no cambia: el MILP sigue leyendo el mismo
  diccionario, ahora con las cifras gobernadas.
