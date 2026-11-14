# Linaje de los datos empaquetados

Generado el 2026-11-11T05:11:18-05:00 con `python -m scripts.reconstruir_desde_replica --linaje`. Datos completos en `linaje.json`.

## De dónde salen

Exportación del 2026-10-03 21:51:37 (scripts/exportar_tablas.py del repositorio del equipo, no se vuelve a ejecutar): una sesión de solo lectura (set_session(readonly=True)) sobre la base compartida del reto y, por cada una de las 15 tablas (Procesos, rutas, vehiculos, dias_semana, estacionalidades, estacionalidades_anio, novedades_viales, novedades_viales_fecha, novedades_viales_ruta, rutas_segmentos_config, rutas_segmentos, timbradas_consolidado, timbradas_anio, timbradas_segmentos y progvehiculos), un único SELECT de columnas explícitas FROM public."tabla" leído con un cursor de servidor en bloques de 100.000 filas, más un SELECT count(*) para comprobar que las filas exportadas coinciden con las del servidor (15 de 15 coinciden; progvehiculos 564.837 filas). Las credenciales viven fuera del repositorio. Desde entonces el proyecto solo usa esas exportaciones: la réplica local se cargó con ellas (scripts/replica_cargar.py).

## Reconstrucción desde la réplica (solo lectura, lector_ia)

| Archivo empaquetado | Filas | SHA-256 del contenido empaquetado | SHA-256 reconstruido | ¿Idéntico? |
|---|---:|---|---|---|
| `datos/demanda_horaria.parquet` (ruta, idruta, fecha, hora, pasajeros, salidas) | 55.896 | `76392ca4e92259b7…` | `76392ca4e92259b7…` | sí |
| `datos/contexto_operacional.parquet` (fecha, hora, nov_impacto, nov_sube, festivo_oficial) | 24.837 | `39e07d16040d301c…` | `39e07d16040d301c…` | sí |
| `datos/bajadas_horaria.parquet` (ruta, fecha, hora, bajadas_viajes) | 55.896 | `f8d15eb6740c5d4e…` | `f8d15eb6740c5d4e…` | sí |
| `datos/subidas_segmento_hora.parquet` (ruta, fecha, hora, tipo_dia, id_segmento, subidas, nro_segmento, sentido, km_inicio, longitud_m) | 341.820 | `928a64398a12188b…` | `34f3d499a58c6de8…` | no |

- Pasajeros: 55.896 franjas iguales y 0 distintas; suma empaquetada 42.166.279 frente a 42.166.279 reconstruida.
- Salidas: 55.896 iguales y 0 distintas.
- Filas solo en lo empaquetado: 0; solo en la reconstrucción: 0.
- No se reconstruye: calendario (tipo_dia, festivo, carnaval, semana_santa, vacaciones, navidad, primero_enero) y excluido: reglas propias del proyecto, no datos de Extreme.
- `bajadas_horaria`: SQL de las bajadas sobre progvehiculos (la regla de los pasajeros aplicada a numerobajadas) con la grilla de la serie. En las filas de los dos lados, bajadas_viajes: 55.896 iguales y 0 distintas (suma 41.416.281 frente a 41.416.281); filas solo en lo empaquetado: 0; solo en la reconstrucción: 0.
- `subidas_segmento_hora`: scripts/preparar_segmentos.py (cargar, sentidos y celdas_segmento_hora) sobre timbradas_segmentos, rutas_segmentos y progvehiculos de la réplica. En las filas de los dos lados, subidas: 337.572 iguales y 0 distintas (suma 2.238.743 frente a 2.238.743); filas solo en lo empaquetado: 4.248; solo en la reconstrucción: 0. Las 4.248 filas del 2023-02-07 de las rutas 2 y 21 solo están en lo empaquetado (en la réplica hay 0): son las de los viajes que la réplica deja fuera de timbradas_segmentos para simular su llegada por el trigger. Sin ese día, el contenido es idéntico (SHA-256 `34f3d499a58c6de8…` y `34f3d499a58c6de8…`).

## Huellas de las entradas (réplica)

| Tabla | Filas | SHA-256 del contenido |
|---|---:|---|
| progvehiculos (2023-2025; idprogramacion, idruta, fechasalida, finalizado, cancelada, numeropasajeros) | 564.837 | `daf98150879d38c3a04d22aba8da6db40c6bbb043be7f7962d1c1656d9308022` |
| novedades_viales_fecha | 28 | `8e60d4bfd3910457cb48ec24bbc6f0c99570e58a7ed3d7cfa183cfcca309efcf` |
| novedades_viales_ruta | 0 | `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| estacionalidades_anio | 231 | `fa83493e12a8e414b52293d687099890de8e7253bd883dc6ebc4d9b84bfa438b` |
| estacionalidades | 24 | `b7228f42f823e93d9ab7bffab79a6e2fb8f91776acb22e7af0edc14f6c69f041` |
| progvehiculos (idprogramacion, fechasalida; la que leen las preparaciones por segmento) | 564.837 | `5153931b71d653fd2a1858bcbbed24c169116fbb8a9ff6cdef2c02131385a6af` |
| timbradas_segmentos (id_segmento, id_viaje, fecha, subidas; la que leen las preparaciones por segmento) | 2.769.692 | `6ba28a20ef4262e96cf938f1c03ac71399e03038c80a62fd154fb1f7658236cd` |
| rutas_segmentos (id, idruta, idrutageo, nro_segmento, longitud_m; la que leen las preparaciones por segmento) | 2.695 | `3f30a8b608a2c2b8d609adccb2775aab0c66544258be9a2eacefcc7b87242551` |

## Huellas de los archivos empaquetados

- `datos/demanda_horaria.parquet`: `f5b9435afd5d9b932da713e75198cb940077b9f12d9031922d377cd97e078a03`
- `datos/contexto_operacional.parquet`: `b2547486b08b57112de2834db0f6b9c303788abfeb2a557a3b27800253f0cd31`
- `datos/bajadas_horaria.parquet`: `ffba8d2ae3e135931817b0fdde8bf7adf3c55ca232b405dba8af7d209a181f63`
- `datos/subidas_segmento_hora.parquet`: `b37c7238ffc3913313022246ce96f336bff906022862af521e32ed9883466a56`

## Archivos de `datos/` que no se reconstruyen desde la réplica

| Archivo | SHA-256 | Por qué no se reconstruye desde la réplica |
|---|---|---|
| `datos/reparto_segmentos.parquet` | `0a184027657513a085b4213afb17ccf24d8374f41d3796538a300015ee8910b6` | Reparto fijo B0 de scripts/preparar_segmentos.py: agrega todo ene.-feb. de 2023. La réplica no tiene los 265 viajes reservados del 2023-02-07 de las rutas 2 y 21 en timbradas_segmentos (los deja para simular su llegada por el trigger), así que desde ella no da lo mismo. Su entrada por viaje y segmento sí es la de la réplica: subidas_segmento_hora es idéntica fuera de ese día. |
| `datos/ocupacion_segmentos_hora.parquet` | `af7a902636860a18b98272817bc2fa22bc5fcdc7444629c52c903a7fc1599167` | Perfil de scripts/preparar_ocupacion_segmentos.py: agrega todo ene.-feb. de 2023. La réplica no tiene los 265 viajes reservados del 2023-02-07 de las rutas 2 y 21 en timbradas_segmentos (los deja para simular su llegada por el trigger), así que desde ella no da lo mismo. Su entrada por viaje y segmento sí es la de la réplica: subidas_segmento_hora es idéntica fuera de ese día, y tests/replica/test_ocupacion_segmentos.py compara la lectura del ciclo con las exportaciones viaje por viaje. Además usa la estacionalidad de la exportación (nula para Sobusa, H1), que la réplica armoniza. |
| `datos/clima_diario.parquet` | `33728cc8059bca6ac09ebd6e79652feb5e89e78e82e73e5547a31acb6620ff26` | Clima diario de Barranquilla, una fuente externa al reto (scripts/preparar_datos_api.py): no es una tabla de Extreme y solo condiciona la evaluación. |
| `datos/perfil_intrahorario.parquet` | `8ffb14b01e2953de15b37a4a789941b48f70340aa4375f4e6375eb2eb5cd6722` | Sale de progvehiculos y de conteo_viajes de 2024 (scripts/preparar_datos_api.py). conteo_viajes es un agregado por viaje de conteo_pasajeros de la exportación, y la réplica no carga conteo_pasajeros. |
| `datos/parametros_operativos_hora.parquet` | `ea83901ab56f76596340f0d7076bbe379722a6915b2e6e71d1baf4e4e5779a57` | Parámetros del optimizador del proyecto (experimentos/D1_optimizacion) con los límites del MILP D5 (scripts/preparar_datos_api.py): no es una tabla de Extreme. |
| `datos/insumos_d5_2025.parquet` | `6c1e651a401692c3d9d65d32e9052ed9e88e32c4aec429cc9090dcc5daa142a5` | Insumos del MILP D5 del tablero (EntregaFinal/dash_app/datos), una salida del proyecto. |
| `datos/pronosticos_2025.parquet` | `225224b00965dabd6d72f34ac526993997dadcfc49b93f5d7872b02c285f47b9` | Pronósticos del tablero (EntregaFinal/dash_app/datos), una salida del proyecto. |

## Reglas

- Viaje válido: `finalizado = 'S'` y `cancelada = 'N'` en progvehiculos; la hora es la de `fechasalida` (4 a 20 h: no hay salidas válidas a las 21 h en 2023-2025).
- `pasajeros` = Σ `numeropasajeros` de los viajes válidos con dato y ≤ 300 (ceros incluidos); `salidas` = número de viajes válidos; una franja sin viajes vale 0.
- Contexto: `preparar_datos_api.contexto_desde_tablas` (novedades viales por fecha y rango horario; novedades_viales_ruta tiene 0 filas, así que cada novedad aplica a las tres rutas; festivos oficiales = FESTIVO_NACIONAL de estacionalidades_anio).
- `bajadas_viajes` = Σ `numerobajadas` de los viajes válidos con dato y ≤ 300 (ceros incluidos), por la hora de salida; una franja sin viajes vale 0 (la definición de pasajeros, `../consolidados/definicion_bajadas.md`).
- Subidas por segmento: las columnas que lee `scripts/preparar_segmentos.py` se leen de la réplica, se escriben como las exportaciones en una carpeta temporal y las mismas funciones arman el archivo desde ahí (subidas por ruta, fecha, hora de salida y segmento, con el tipo de día del calendario del proyecto).
