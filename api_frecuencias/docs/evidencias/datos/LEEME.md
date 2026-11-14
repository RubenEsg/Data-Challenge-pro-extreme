# Evidencias de datos: calidad, linaje y definición de la medida

| Archivo | Qué muestra | Cómo se regenera |
|---|---|---|
| `linaje.md`, `linaje.json` | La serie empaquetada (`datos/demanda_horaria.parquet`: 55.896 franjas, 42.166.279 pasajeros), el contexto (`datos/contexto_operacional.parquet`: 24.837 filas) y las bajadas (`datos/bajadas_horaria.parquet`: 55.896 franjas, 41.416.281 bajadas) se reconstruyen desde las tablas de Extreme en la réplica con contenido idéntico (mismo SHA-256 del contenido normalizado). Las subidas por segmento (`datos/subidas_segmento_hora.parquet`, con las mismas funciones de `scripts/preparar_segmentos.py`) también, salvo las 4.248 filas del 2023-02-07 de las rutas 2 y 21: son las de los viajes que la réplica deja fuera de `timbradas_segmentos` para simular su llegada. De los demás archivos de `datos/`, el SHA-256 y por qué no se reconstruyen; SHA-256 de las entradas; cómo se hizo la exportación original. | `python -m scripts.reconstruir_desde_replica --linaje`; pruebas `tests/replica/test_integrado.py::test_linaje_el_historico_empaquetado_se_reconstruye_identico_desde_la_replica` y `tests/unit/test_reconstruir_desde_replica.py` (cada `.parquet` de `datos/` tiene su linaje) |
| `definicion_pasajeros.md`, `definicion_pasajeros.json` | Σ subidas de `timbradas_segmentos` frente a Σ `numeropasajeros` de los viajes válidos en el solape de 2023: −5,21 % en total, +0,22 % en los mismos viajes; la diferencia es de cobertura (1.529 viajes válidos sin timbradas). La lectura integrada usa la definición del modelo. | `python -m scripts.reconstruir_desde_replica --definicion-pasajeros` |
| `errores_lote.txt` | Una ejecución con un lote malo a propósito (7 defectos, uno por regla, que dan 8 errores: la llave duplicada marca sus dos filas) y lo que devuelve `GET /api/v1/frequency/executions/{execution_id}/errors`: lote, fila, llave del registro, campo, valor, código, dimensión, causa y si bloquea. | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_errores_lote.py` |
| `reporte_unicidad.json` | §6.3 «reportar al responsable del consolidado; no corregir»: un lote con una llave duplicada genera el reporte (la llave con sus filas, que no se corrigió nada y la ruta de la API con el detalle). Sin `NOTIF_UNICIDAD_DESTINATARIOS` queda `pendiente_destinatario` en `notification_log`; con un destinatario sale por el correo simulado. Las dos filas no entran al histórico. | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_errores_lote.py::test_el_lote_con_duplicados_se_reporta_al_responsable_sin_corregir` |
| `novedades_por_ruta.json` | §11.2 «novedades por fecha, rango horario y ruta»: dos novedades sintéticas leídas con `FuentePostgresSoloLectura` (READ ONLY) desde una base local. Con una fila en `novedades_viales_ruta`, esa novedad solo afecta a su ruta; sin filas, las dos afectan a todas. La misma lectura en la réplica, con la tabla vacía, está en `../replica/novedades_por_ruta_replica.json`. | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_novedades_por_ruta.py` |

Calidad sobre datos reales (§6.3):

- La muestra `tests/fixtures/consolidado_muestra.csv` (531 filas de `timbradas_consolidado`, bloques de 15 minutos con
  las 27 filas del bloque 23:45–00:00; conteos agregados, sin datos personales) pasa sin errores:
  `tests/unit/test_calidad.py::test_muestra_real_sin_falsos_duplicados_ni_falsa_franja_a_medianoche`. Se extrae con
  `python -m scripts.reconstruir_desde_replica --muestra-consolidado`.
- Las 10.731 filas reales de `timbradas_consolidado` de la réplica pasan sin UNI-001 ni VAL-004 con la llave de 7
  columnas (antes: 10.343 UNI-001 y 27 VAL-004):
  `tests/replica/test_integrado.py::test_consolidado_real_sin_falsos_errores_de_calidad`.
- La lectura integrada entrega en las 2.757 franjas de la réplica los mismos pasajeros y salidas que el histórico
  empaquetado: `tests/replica/test_integrado.py::test_demanda_segmentos_usa_la_definicion_del_modelo_con_proceso_y_estacionalidad`.
- Las bajadas siguen la misma definición que los pasajeros (Σ `numerobajadas` de los viajes válidos; la decisión, en
  `../consolidados/definicion_bajadas.md`). Las empaquetadas (`datos/bajadas_horaria.parquet` de la API, con su
  procedencia y su SHA-256 en `datos/origen.json`) son las de la réplica franja por franja, y la lectura integrada trae
  las mismas: `tests/replica/test_consolidados.py::test_las_bajadas_empaquetadas_son_las_de_la_replica` y
  `tests/replica/test_consolidados.py::test_la_lectura_integrada_trae_las_bajadas_de_la_definicion_de_pasajeros`.
  `linaje.md` lo reconstruye desde la réplica con contenido idéntico.

Todas las lecturas de la réplica son de solo lectura (lector_ia, transacción READ ONLY con `statement_timeout`). Ningún
script se conecta a la base compartida del reto ni escribe en `datos/`.
