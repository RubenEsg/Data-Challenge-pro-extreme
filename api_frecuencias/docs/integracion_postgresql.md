# Integración con PostgreSQL (E07)

Cómo lee la API los datos de Extreme sin interferir con la operación, dónde guarda sus resultados y qué falta para
conectarla a la base real. Referencias: especificación v1.5, §6, §8, §11 y §18 (`documentos/especificacion_tecnica_reto_frecuencias_v1.5.md`).

## 1. Dos bases, dos papeles

| Base | Papel | Quién escribe | Cómo se conecta la API |
|---|---|---|---|
| **Fuente operacional** (la del reto, o la réplica de Extreme) | Tablas `public.*`: rutas, progvehiculos, timbradas, novedades | Solo los triggers y scripts de Extreme | Adaptador `FuentePostgresSoloLectura` (`app/servicios/fuentes.py`), activo con `FUENTE=postgres` y la URL en `FUENTE_DATABASE_URL` (vacía en el repositorio). **Nunca** desde las pruebas. |
| **Resultados** (`ai_frecuencias`, PostgreSQL 14 + PostGIS propio, servicio `db` de Docker Compose) | Predicciones, recomendaciones, alertas y su historial, ejecuciones, errores de calidad, modelos, umbrales, marcas de agua | La API | `DATABASE_URL` (ver `.env.example`); el esquema lo crean las migraciones de Alembic. |

La fuente por omisión es **Parquet local** (`FuenteParquet`): los datos del reto exportados una vez (2023-2025, tres rutas),
para que la demostración sea reproducible sin internet y sin tocar la base compartida. La base del reto la comparten
todos los equipos y es de solo lectura por regla; el usuario del reto además *puede* crear objetos en `public`, así que la
protección no puede depender de los permisos del servidor: la pone el adaptador (transacción `READ ONLY`).

## 2. Mapa de tablas: esquema lógico de §8.2 frente a nuestras fuentes

| Tabla (§8.2) | En la base del reto | Exportada a Parquet | Uso en el proyecto y en la API |
|---|---|---|---|
| `procesos` | Sí (`Procesos`) | Sí | Contexto (proceso de Sobusa). |
| `rutas` | Sí (3 rutas: SILENCIO `idruta` 2, CRA 54 16, CL 72 21) | Sí | Catálogo de rutas: `idruta`, nombre, `frecuenciadespachos` (frecuencia vigente que se compara con la recomendada, RF-008). |
| `estacionalidades`, `estacionalidades_anio` | Sí | Sí | Calendario y tipo de día. `estacionalidades_anio` pertenece a otro proceso (`cootransoriente`), por eso el calendario se derivó de las fechas y festivos. |
| `timbradas_anio` | Sí (30.913 filas, 2023-2026) | Sí | Consolidado anual por ruta y franja; marca `ultima_actualizacion`. La columna `hora` es la hora de **fin** del viaje. |
| `timbradas_anio_zonas` | Sí (diccionario) | No | No se usa (sin zona tarifaria en el modelo). |
| `timbradas_consolidado` | Sí (10.731 filas) | Sí | Consolidado por día de semana y estacionalidad; candidato natural para la lectura incremental por `ultima_actualizacion`. |
| `timbradas_consolidado_zonas` | Sí (diccionario) | No | No se usa. |
| `novedades_viales`, `_fecha`, `_ruta` | Sí (fuera del diccionario) | Sí (28 ocurrencias) | Contexto: se cruzan por fecha, franja y ruta (RF-003). |
| `conteo_pasajero` | Como `conteo_pasajeros_destino`: **176 M filas, 41 GB, índice solo por `idprogramacion`** | No (se agregó en el servidor por lotes de 20.000 `idprogramacion`) | Subidas GPS por ruta, día y hora (`datos/tabla_modelado.parquet`), usadas en el análisis y en la vista 3D. La API no la consulta. |
| `progvehiculos` | Sí (564.837 viajes 2023-2025) | Sí | **Fuente de la demanda de la API**: por ruta, día y hora de salida, la suma de `numeropasajeros` de los viajes válidos (dato ≤ 300) y el número de salidas válidas (`datos/demanda_horaria.parquet`, 55.896 filas, vía `experimentos/E1_lgbm_salida`). |
| `rutas_segmentos_porcion` | Sí (6,7 M filas, 1,5 GB) | No | No se usa. |
| `rutas_segmentos_config`, `rutas_segmentos` | Sí | Sí | Geometría de las rutas (mapa del laboratorio y de la app). |
| `timbradas_segmentos` | Sí (solo enero-febrero de 2023) | Sí | Muy corta para modelar; se documenta como fuente posible por segmento. |
| `timbradas_segmentos_anio`, `_anio_trazabilidad`, `_consolidado` | Sí (diccionario) | No | No se usan; volumen en el servidor **por verificar**. |
| `ai_frecuencias.*` | **No**: va en nuestra base propia | — | Lo crea Alembic: modelos, predicciones, recomendaciones, alertas, historial de alertas, ejecuciones, errores de calidad, umbrales versionados, marcas de agua. |

La API trabaja con una vista analítica única, `demanda_horaria` (`app/servicios/datos.py`): ruta, fecha, hora (4 a 20),
pasajeros, salidas y `ultima_actualizacion`. Con la fuente Parquet sale de `api_frecuencias/datos/demanda_horaria.parquet`
(2023-2025; procedencia de cada columna en `datos/origen.json`, generado por `scripts/preparar_datos_api.py`).

`FuentePostgresSoloLectura` lee hoy los consolidados de §8.2 que tienen `ultima_actualizacion` (por omisión
`timbradas_consolidado`; lista blanca `TABLAS_PERMITIDAS` en `fuentes.py`, más los catálogos pequeños, que se leen
completos): consulta (a) de la sección 3. `progvehiculos` y `conteo_pasajeros_destino` **no** están en esa lista blanca;
la consulta (b), que da la misma serie por fecha que usa el modelo, es el siguiente paso para producción y debe
agregarse a la lista blanca con la revisión del DBA. El catálogo de rutas (`datos/catalogo_rutas.json`) toma
`idruta`, `frecuenciadespachos` y el primer despacho de la tabla `rutas`, y el tiempo de ciclo, la flota y la frecuencia
programada de las medianas de día laboral (6 a 19 h) de `experimentos/D1_optimizacion/parametros_operativos.parquet`.

## 3. Consultas de solo lectura (referencia)

Todas corren dentro de una transacción de solo lectura y con límite de tiempo (`FUENTE_STATEMENT_TIMEOUT_MS`, 30.000 ms
por omisión); los parámetros van siempre enlazados (nunca concatenados en el SQL):

```sql
BEGIN;
SET TRANSACTION READ ONLY;
SET LOCAL statement_timeout = 30000;      -- FUENTE_STATEMENT_TIMEOUT_MS, entero validado (sin texto del usuario)
SELECT ...;                               -- solo SELECT sobre TABLAS_PERMITIDAS; otra sentencia se rechaza antes
ROLLBACK;                                 -- nunca COMMIT
```

Así lo hace `FuentePostgresSoloLectura._consultar` (`app/servicios/fuentes.py`). En producción conviene además
`application_name = 'ai_frecuencias_lector'` para que el DBA identifique la sesión.

**a) Consolidado nuevo o modificado desde la marca de agua** (§8.3, §11.2):

```sql
SELECT c.id_timbrada_consolidado, c.proceso, c.id_ruta, r.nombre AS ruta, r.frecuenciadespachos,
       c.id_dia_semana, c.id_estacionalidad, c.hora, c.hora_inicio, c.hora_fin,
       c.subidas, c.bajadas, c.nro_viajes, c.promedio_subidas, c.promedio_bajadas, c.ultima_actualizacion
FROM public.timbradas_consolidado AS c
JOIN public.rutas AS r ON r.idruta = c.id_ruta
WHERE c.ultima_actualizacion >  %(marca_agua)s
  AND c.ultima_actualizacion <= %(corte)s
ORDER BY c.ultima_actualizacion, c.id_timbrada_consolidado;
```

**b) Demanda por ruta, día y hora de salida** (la serie que usa la API; `progvehiculos` es pequeña, 565 mil filas):

```sql
SELECT p.idruta, p.fechasalida::date AS fecha, EXTRACT(HOUR FROM p.fechasalida)::int AS hora,
       SUM(p.numeropasajeros) FILTER (WHERE p.numeropasajeros <= 300) AS pasajeros,
       COUNT(*) FILTER (WHERE p.numeropasajeros <= 300)              AS salidas
FROM public.progvehiculos AS p
WHERE p.idruta = ANY(%(rutas)s)
  AND p.fechasalida >= %(desde)s AND p.fechasalida < %(hasta)s
GROUP BY 1, 2, 3;
```

La regla completa de «viaje válido» es la del proyecto (`experimentos/E1_lgbm_salida`); esta consulta es la referencia.

**c) Subidas GPS, si se quisieran por hora** (dos pasos, para no recorrer la tabla grande por fecha):

```sql
-- 1. Viajes de los días nuevos
SELECT p.idprogramacion
FROM public.progvehiculos AS p
WHERE p.idruta = ANY(%(rutas)s)
  AND p.fechasalida >= %(desde)s AND p.fechasalida < %(hasta)s;
-- 2. Subidas por ruta, día y hora de esos viajes, por lotes de hasta 20.000 idprogramacion
--    (filtra por el único índice de la tabla grande; es la agregación de scripts/agregar_conteo.py)
SELECT p.idruta, c.fecha::date AS dia, EXTRACT(HOUR FROM c.fecha)::int AS hora,
       SUM(c.cantidad_subida) AS subidas, SUM(c.cantidad_bajada) AS bajadas,
       COUNT(DISTINCT c.idprogramacion) AS viajes
FROM public.conteo_pasajeros_destino AS c
JOIN public.progvehiculos AS p ON p.idprogramacion = c.idprogramacion
WHERE c.idprogramacion = ANY(%(lote)s)
GROUP BY 1, 2, 3;
```

`progvehiculos` y `conteo_pasajeros_destino` no tienen `ultima_actualizacion`: sus días nuevos se detectan por
`progvehiculos.fechasalida` (la fuente Parquet marca cada día con `ultima_actualizacion` = 23:59:59 de ese día).
Las columnas salen del diccionario (`documentos/Diccionario de Variables.csv`) y de `scripts/agregar_conteo.py`, que hizo
esta agregación para el proyecto en modo de solo lectura (los dos en el repositorio del equipo, no en el ZIP). Lo que
ejecuta la API está en `app/servicios/fuentes.py`.

## 4. Marca de agua (lectura incremental, RF-013)

1. Cada ejecución lee la última marca **exitosa** de la fuente desde `ai_frecuencias.execution_log` (columna
   `marca_agua_nueva` de la última ejecución terminada; si no hay, lee desde el inicio del histórico configurado) y la
   guarda como `marca_agua_anterior` de la ejecución nueva.
2. Calcula el corte: `corte = ahora − margen` (unos minutos), para no leer transacciones que aún se están escribiendo.
3. Lee solo lo que cumple `marca_agua < ultima_actualizacion <= corte` (o, con Parquet, las fechas que «llegaron» después
   de la marca: la fuente simula la llegada diaria de datos nuevos).
4. Valida el lote (§6.3); las filas con error quedan en la tabla de errores con lote, fila, campo, código y detalle, y no
   pasan a la inferencia.
5. Escribe con claves únicas (migración `0001_esquema_ai_frecuencias.py`): el histórico `demanda_observada` por
   (ruta, fecha, hora) con *upsert*, las predicciones por (execution_id, ruta, instante, horizonte) y las alertas abiertas
   por `clave_dedup` (índice único parcial). Repetir la carga no duplica eventos (§14.2).
6. **Solo al terminar bien** guarda la nueva marca (el máximo `ultima_actualizacion` leído) junto con `execution_id`,
   `data_cutoff`, `model_id`, `feature_version` y versión de umbrales. Si la ejecución falla, la marca no se mueve y la
   siguiente vuelve a leer el mismo tramo (RNF-001).

## 5. Controles de no interferencia (§11.3)

| Control de la especificación | Cómo se cumple |
|---|---|
| Usuario técnico solo con `SELECT` | La URL de la fuente viene de `FUENTE_DATABASE_URL`; en producción, un usuario `ai_lector` con `GRANT SELECT` sobre las tablas autorizadas (lo crea Extreme). |
| Usuario separado con escritura solo en `ai_frecuencias` | `DATABASE_URL` apunta a otra base (la nuestra) con un usuario dueño solo de ese esquema. |
| Transacciones `READ ONLY` con *timeout* | El adaptador abre siempre `SET TRANSACTION READ ONLY`, fija `statement_timeout` y termina con `ROLLBACK`; rechaza en el código toda sentencia que no sea `SELECT` y toda tabla fuera de la lista blanca, y aun si llegara al servidor, un `INSERT`, `UPDATE`, `DELETE` o DDL falla (`cannot execute ... in a read-only transaction`). |
| Ningún DDL sobre el esquema operacional | Alembic solo conoce `DATABASE_URL` y el esquema `ai_frecuencias`; no tiene la URL de la fuente. |
| No deshabilitar triggers | La API no ejecuta `ALTER TABLE` ni `session_replication_role`. |
| No tocar funciones, scripts ni índices | Los índices se piden al DBA después de `EXPLAIN (ANALYZE, BUFFERS)`; la API no los crea. |
| Consultas pesadas en réplica | Por omisión no hay ninguna consulta remota (fuente Parquet); el paso a producción apunta a una réplica (ver `../../PLAN_EVOLUCION.md`). |
| Las pruebas no tocan la base del reto | Las pruebas usan Parquet y la base local del `docker compose`; no reciben la URL de la fuente. |

## 6. Rendimiento

- **Volumen diario real:** 3 rutas × 17 horas ≈ 51 filas de demanda por día, unas 460 salidas en `progvehiculos` y del
  orden de 20.000 eventos de conteo. La lectura incremental diaria es pequeña; el riesgo está en la forma de la consulta.
- `conteo_pasajeros_destino` solo tiene índice por `idprogramacion`: filtrarla por fecha recorre 41 GB y llega al
  *timeout* de 60 s del servidor (lo medimos). Por eso se filtra por listas de `idprogramacion` sacadas de `progvehiculos`
  (en el proyecto: 125 lotes de 20.000, de 15 a 20 s cada uno, para los tres años completos).
- Si `timbradas_*` no tienen índice por `ultima_actualizacion`, la consulta (a) recorre la tabla entera; con 10-30 mil filas
  cuesta milisegundos, pero hay que confirmarlo con `EXPLAIN (ANALYZE, BUFFERS)` en la réplica y, si hace falta, pedir el
  índice al DBA.
- Cursor del lado del servidor y lectura por lotes (10.000 filas) para no cargar todo en memoria; RNF-003 (100.000
  registros con tiempo y memoria medidos) se mide sobre la fuente Parquet: resultado en el manual técnico (**por verificar**).
- Las consultas de la API sobre `ai_frecuencias` van paginadas e indexadas por (ruta, fecha), (estado, severidad) en
  alertas y (execution_id); el p95 < 2 s de RNF-002 está **por verificar** con una prueba de carga (k6, pendiente).
