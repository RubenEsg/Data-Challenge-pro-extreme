# Evidencias de datos: calidad, linaje y definición de la medida

| Archivo | Qué muestra | Cómo se regenera |
|---|---|---|
| `linaje.md`, `linaje.json` | La serie empaquetada (`datos/demanda_horaria.parquet`: 55.896 franjas, 42.166.279 pasajeros) y el contexto (`datos/contexto_operacional.parquet`: 24.837 filas) se reconstruyen desde las tablas de Extreme en la réplica con contenido idéntico (mismo SHA-256 del contenido normalizado); SHA-256 de las entradas y de los archivos; cómo se hizo la exportación original. | `python -m scripts.reconstruir_desde_replica --linaje`; prueba `tests/replica/test_integrado.py::test_linaje_el_historico_empaquetado_se_reconstruye_identico_desde_la_replica` |
| `definicion_pasajeros.md`, `definicion_pasajeros.json` | Σ subidas de `timbradas_segmentos` frente a Σ `numeropasajeros` de los viajes válidos en el solape de 2023: −5,21 % en total, +0,22 % en los mismos viajes; la diferencia es de cobertura (1.529 viajes válidos sin timbradas). La lectura integrada usa la definición del modelo. | `python -m scripts.reconstruir_desde_replica --definicion-pasajeros` |
| `errores_lote.txt` | Una ejecución con un lote malo a propósito (7 defectos, uno por regla, que dan 8 errores: la llave duplicada marca sus dos filas) y lo que devuelve `GET /api/v1/frequency/executions/{id}/errors`: lote, fila, llave del registro, campo, valor, código, dimensión, causa y si bloquea. | `GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_errores_lote.py` |

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

Todas las lecturas de la réplica son de solo lectura (lector_ia, transacción READ ONLY con `statement_timeout`). Ningún
script se conecta a la base compartida del reto ni escribe en `datos/`.
