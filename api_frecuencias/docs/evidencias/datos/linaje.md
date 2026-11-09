# Linaje de los datos empaquetados

Generado el 2026-11-09T06:40:33-05:00 con `python -m scripts.reconstruir_desde_replica --linaje`. Datos completos en `linaje.json`.

## De dónde salen

Exportación del 2026-10-03 21:51:37 (scripts/exportar_tablas.py del repositorio del equipo, no se vuelve a ejecutar): una sesión de solo lectura (set_session(readonly=True)) sobre la base compartida del reto y, por cada una de las 15 tablas (Procesos, rutas, vehiculos, dias_semana, estacionalidades, estacionalidades_anio, novedades_viales, novedades_viales_fecha, novedades_viales_ruta, rutas_segmentos_config, rutas_segmentos, timbradas_consolidado, timbradas_anio, timbradas_segmentos y progvehiculos), un único SELECT de columnas explícitas FROM public."tabla" leído con un cursor de servidor en bloques de 100.000 filas, más un SELECT count(*) para comprobar que las filas exportadas coinciden con las del servidor (15 de 15 coinciden; progvehiculos 564.837 filas). Las credenciales viven fuera del repositorio. Desde entonces el proyecto solo usa esas exportaciones: la réplica local se cargó con ellas (scripts/replica_cargar.py).

## Reconstrucción desde la réplica (solo lectura, lector_ia)

| Archivo empaquetado | Filas | SHA-256 del contenido empaquetado | SHA-256 reconstruido | ¿Idéntico? |
|---|---:|---|---|---|
| `datos/demanda_horaria.parquet` (ruta, idruta, fecha, hora, pasajeros, salidas) | 55.896 | `76392ca4e92259b7…` | `76392ca4e92259b7…` | sí |
| `datos/contexto_operacional.parquet` (fecha, hora, nov_impacto, nov_sube, festivo_oficial) | 24.837 | `39e07d16040d301c…` | `39e07d16040d301c…` | sí |

- Pasajeros: 55.896 franjas iguales y 0 distintas; suma empaquetada 42.166.279 frente a 42.166.279 reconstruida.
- Salidas: 55.896 iguales y 0 distintas.
- Filas solo en lo empaquetado: 0; solo en la reconstrucción: 0.
- No se reconstruye: calendario (tipo_dia, festivo, carnaval, semana_santa, vacaciones, navidad, primero_enero) y excluido: reglas propias del proyecto, no datos de Extreme.

## Huellas de las entradas (réplica)

| Tabla | Filas | SHA-256 del contenido |
|---|---:|---|
| progvehiculos (2023-2025; idprogramacion, idruta, fechasalida, finalizado, cancelada, numeropasajeros) | 564.837 | `daf98150879d38c3a04d22aba8da6db40c6bbb043be7f7962d1c1656d9308022` |
| novedades_viales_fecha | 28 | `8e60d4bfd3910457cb48ec24bbc6f0c99570e58a7ed3d7cfa183cfcca309efcf` |
| novedades_viales_ruta | 0 | `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| estacionalidades_anio | 231 | `fa83493e12a8e414b52293d687099890de8e7253bd883dc6ebc4d9b84bfa438b` |
| estacionalidades | 24 | `b7228f42f823e93d9ab7bffab79a6e2fb8f91776acb22e7af0edc14f6c69f041` |

## Huellas de los archivos empaquetados

- `datos/demanda_horaria.parquet`: `f5b9435afd5d9b932da713e75198cb940077b9f12d9031922d377cd97e078a03`
- `datos/contexto_operacional.parquet`: `b2547486b08b57112de2834db0f6b9c303788abfeb2a557a3b27800253f0cd31`

## Reglas

- Viaje válido: `finalizado = 'S'` y `cancelada = 'N'` en progvehiculos; la hora es la de `fechasalida` (4 a 20 h: no hay salidas válidas a las 21 h en 2023-2025).
- `pasajeros` = Σ `numeropasajeros` de los viajes válidos con dato y ≤ 300 (ceros incluidos); `salidas` = número de viajes válidos; una franja sin viajes vale 0.
- Contexto: `preparar_datos_api.contexto_desde_tablas` (novedades viales por fecha y rango horario; novedades_viales_ruta tiene 0 filas, así que cada novedad aplica a las tres rutas; festivos oficiales = FESTIVO_NACIONAL de estacionalidades_anio).
