# Consolidados de Extreme en el ciclo: lectura, calidad y contraste con la agregación propia

Generado 2026-11-13T18:54:21-05:00 con `python -m scripts.contraste_consolidados` sobre la réplica local, en solo lectura (lector_ia), con las funciones del ciclo (`app/servicios/consolidados.py`).

## timbradas_consolidado

- Lectura incremental desde la carga: 10731 filas leídas y 10731 entregadas (marca 2026-08-14 11:29:05.057003-05:00). Segunda lectura con las huellas (misma marca, ventana de solape): 0 entregadas y 10731 descartadas por huella (H7).
- Calidad (§6.3, con los catálogos de la réplica: capacidades, dias_estacionalidad, dias_estacionalidad_anio, dias_semana, estacionalidades, idrutas, novedades, procesos, rutas, segmentos, segmentos_ruta): 10731 válidas; errores: ninguno.
- Contraste con el histórico propio por id_ruta × id_dia_semana × id_estacionalidad en 2023-01-01 a 2025-12-31 (años cerrados que suma el consolidado): 174 llaves, 160 comparadas, 6 sin histórico propio y 8 con menos de 30 viajes. Incidencias: 31 (11 groseras, bloqueantes) con tolerancia 15,0 % y grosera 50,0 %.

| Medida | Llaves | Mediana | p90 | Máximo |
|---|---|---|---|---|
| promedio_subidas | 160 | 1,4 % | 4,5 % | 15,6 % |
| promedio_bajadas | 160 | 1,3 % | 6,2 % | 189,1 % |
| viajes_por_dia | 160 | 1,7 % | 31,8 % | 111,8 % |

Totales 2023-2025 por ruta (Extreme frente al histórico propio):

| id_ruta | Subidas Extreme | Subidas propias | Bajadas Extreme | Bajadas propias | Viajes Extreme | Viajes propios |
|---|---|---|---|---|---|---|
| 2 | 11.745.383 | 11.335.063 | 11.466.959 | 11.064.990 | 152.379 | 146.416 |
| 16 | 24.319.445 | 23.379.495 | 25.311.039 | 22.948.117 | 293.054 | 282.685 |
| 21 | 7.730.303 | 7.451.721 | 11.710.210 | 7.403.174 | 95.156 | 91.537 |

Incidencias (las que el ciclo guarda en data_quality_error con lote, llave, valor y bloqueante):

| Llave | Campo | Valor de Extreme | Bloqueante | Detalle |
|---|---|---|---|---|
| id_ruta=16, id_dia_semana=1, id_estacionalidad=3 | viajes_por_dia | 242.00 | sí | viajes_por_dia = 242.00 en timbradas_consolidado frente a 120.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 101.7% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=16, id_dia_semana=4, id_estacionalidad=4 | viajes_por_dia | 190.00 | sí | viajes_por_dia = 190.00 en timbradas_consolidado frente a 100.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 90.0% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=2, id_dia_semana=1, id_estacionalidad=20 | viajes_por_dia | 126.00 | sí | viajes_por_dia = 126.00 en timbradas_consolidado frente a 83.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 51.8% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=2, id_dia_semana=1, id_estacionalidad=3 | viajes_por_dia | 138.00 | sí | viajes_por_dia = 138.00 en timbradas_consolidado frente a 68.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 102.9% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=2, id_dia_semana=4, id_estacionalidad=4 | viajes_por_dia | 132.00 | sí | viajes_por_dia = 132.00 en timbradas_consolidado frente a 68.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 94.1% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=21, id_dia_semana=1, id_estacionalidad=20 | viajes_por_dia | 78.50 | sí | viajes_por_dia = 78.50 en timbradas_consolidado frente a 50.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 57.0% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=21, id_dia_semana=1, id_estacionalidad=3 | viajes_por_dia | 108.00 | sí | viajes_por_dia = 108.00 en timbradas_consolidado frente a 51.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 111.8% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=21, id_dia_semana=3, id_estacionalidad=25 | promedio_bajadas | 137.54 | sí | promedio_bajadas = 137.54 en timbradas_consolidado frente a 85.64 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 60.6% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=21, id_dia_semana=4, id_estacionalidad=25 | promedio_bajadas | 137.22 | sí | promedio_bajadas = 137.22 en timbradas_consolidado frente a 84.97 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 61.5% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=21, id_dia_semana=4, id_estacionalidad=4 | viajes_por_dia | 62.00 | sí | viajes_por_dia = 62.00 en timbradas_consolidado frente a 31.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 100.0% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=21, id_dia_semana=5, id_estacionalidad=25 | promedio_bajadas | 247.56 | sí | promedio_bajadas = 247.56 en timbradas_consolidado frente a 85.64 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 189.1% (tolerancia 15%; grosera desde 50%: la llave queda fuera del análisis) |
| id_ruta=16, id_dia_semana=1, id_estacionalidad=1 | viajes_por_dia | 229.33 | no | viajes_por_dia = 229.33 en timbradas_consolidado frente a 174.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 31.8% (tolerancia 15%) |
| id_ruta=16, id_dia_semana=1, id_estacionalidad=10 | viajes_por_dia | 377.50 | no | viajes_por_dia = 377.50 en timbradas_consolidado frente a 288.50 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 30.8% (tolerancia 15%) |
| id_ruta=16, id_dia_semana=1, id_estacionalidad=2 | viajes_por_dia | 226.00 | no | viajes_por_dia = 226.00 en timbradas_consolidado frente a 167.33 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 35.1% (tolerancia 15%) |
| id_ruta=16, id_dia_semana=1, id_estacionalidad=20 | viajes_por_dia | 216.50 | no | viajes_por_dia = 216.50 en timbradas_consolidado frente a 148.50 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 45.8% (tolerancia 15%) |
| id_ruta=16, id_dia_semana=1, id_estacionalidad=25 | viajes_por_dia | 335.66 | no | viajes_por_dia = 335.66 en timbradas_consolidado frente a 285.76 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 17.5% (tolerancia 15%) |
| id_ruta=16, id_dia_semana=3, id_estacionalidad=25 | promedio_bajadas | 98.24 | no | promedio_bajadas = 98.24 en timbradas_consolidado frente a 84.76 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 15.9% (tolerancia 15%) |
| id_ruta=16, id_dia_semana=7, id_estacionalidad=10 | viajes_por_dia | 134.50 | no | viajes_por_dia = 134.50 en timbradas_consolidado frente a 162.83 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 17.4% (tolerancia 15%) |
| id_ruta=16, id_dia_semana=7, id_estacionalidad=25 | promedio_bajadas | 88.37 | no | promedio_bajadas = 88.37 en timbradas_consolidado frente a 59.53 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 48.4% (tolerancia 15%) |
| id_ruta=2, id_dia_semana=1, id_estacionalidad=1 | viajes_por_dia | 122.33 | no | viajes_por_dia = 122.33 en timbradas_consolidado frente a 92.67 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 32.0% (tolerancia 15%) |
| id_ruta=2, id_dia_semana=1, id_estacionalidad=10 | viajes_por_dia | 212.00 | no | viajes_por_dia = 212.00 en timbradas_consolidado frente a 153.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 38.6% (tolerancia 15%) |
| id_ruta=2, id_dia_semana=1, id_estacionalidad=2 | viajes_por_dia | 123.67 | no | viajes_por_dia = 123.67 en timbradas_consolidado frente a 90.33 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 36.9% (tolerancia 15%) |
| id_ruta=2, id_dia_semana=1, id_estacionalidad=25 | viajes_por_dia | 173.10 | no | viajes_por_dia = 173.10 en timbradas_consolidado frente a 145.21 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 19.2% (tolerancia 15%) |
| id_ruta=2, id_dia_semana=4, id_estacionalidad=4 | promedio_bajadas | 58.20 | no | promedio_bajadas = 58.20 en timbradas_consolidado frente a 50.22 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 15.9% (tolerancia 15%) |
| id_ruta=2, id_dia_semana=4, id_estacionalidad=4 | promedio_subidas | 57.70 | no | promedio_subidas = 57.70 en timbradas_consolidado frente a 49.93 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 15.6% (tolerancia 15%) |
| id_ruta=2, id_dia_semana=7, id_estacionalidad=10 | viajes_por_dia | 73.67 | no | viajes_por_dia = 73.67 en timbradas_consolidado frente a 89.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 17.2% (tolerancia 15%) |
| id_ruta=21, id_dia_semana=1, id_estacionalidad=1 | viajes_por_dia | 80.67 | no | viajes_por_dia = 80.67 en timbradas_consolidado frente a 57.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 41.5% (tolerancia 15%) |
| id_ruta=21, id_dia_semana=1, id_estacionalidad=10 | viajes_por_dia | 125.00 | no | viajes_por_dia = 125.00 en timbradas_consolidado frente a 91.50 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 36.6% (tolerancia 15%) |
| id_ruta=21, id_dia_semana=1, id_estacionalidad=2 | viajes_por_dia | 64.00 | no | viajes_por_dia = 64.00 en timbradas_consolidado frente a 48.00 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 33.3% (tolerancia 15%) |
| id_ruta=21, id_dia_semana=1, id_estacionalidad=25 | viajes_por_dia | 105.62 | no | viajes_por_dia = 105.62 en timbradas_consolidado frente a 89.75 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 17.7% (tolerancia 15%) |
| id_ruta=21, id_dia_semana=6, id_estacionalidad=25 | promedio_bajadas | 104.47 | no | promedio_bajadas = 104.47 en timbradas_consolidado frente a 72.45 de la agregación propia (demanda_observada (pasajeros, bajadas_viajes y salidas)): diferencia 44.2% (tolerancia 15%) |

## De dónde salen las diferencias groseras de viajes por día (H17)

Festivos de un día con más de una fila en estacionalidades_anio: viajes que timbradas_anio guarda con cada fila frente a los viajes aptos (apto_estadisticas_historicas) con esa fecha de fin, todas las rutas:

| Fecha | id_estacionalidad_anio (id_estacionalidad) | Viajes en timbradas_anio por fila | Viajes aptos |
|---|---|---|---|
| 2019-07-01 | 57 (20), 218 (19) | 57: 0, 218: 0 | 0 |
| 2025-06-30 | 164 (20), 225 (19) | 164: 282, 225: 282 | 299 |
| 2025-11-03 | 1 (1), 169 (1) | 1: 317, 169: 317 | 321 |
| 2025-11-17 | 2 (2), 170 (2) | 2: 318, 170: 318 | 321 |
| 2025-12-08 | 3 (3), 171 (3) | 3: 244, 171: 244 | 244 |
| 2025-12-25 | 4 (4), 172 (4) | 4: 192, 172: 192 | 200 |

timbradas_anio frente a los viajes aptos por fecha de fin, por ruta y año (DIAS_CORRIENTES: la estacionalidad vigente de período más corto, la regla de fn_insert_timbradas_anio):

| idruta | Año | Viajes timbradas_anio | Aptos | Diferencia | DIAS_CORRIENTES en timbradas_anio | Aptos en días corrientes | Diferencia |
|---|---|---|---|---|---|---|---|
| 2 | 2023 | 52.179 | 50.268 | 3,8 % | 48.358 | 46.608 | 3,8 % |
| 2 | 2024 | 49.856 | 47.930 | 4,0 % | 45.933 | 44.192 | 3,9 % |
| 2 | 2025 | 50.344 | 48.202 | 4,4 % | 46.364 | 44.742 | 3,6 % |
| 16 | 2023 | 102.784 | 99.393 | 3,4 % | 95.538 | 92.396 | 3,4 % |
| 16 | 2024 | 96.186 | 93.136 | 3,3 % | 89.135 | 86.386 | 3,2 % |
| 16 | 2025 | 94.084 | 90.140 | 4,4 % | 86.682 | 83.663 | 3,6 % |
| 21 | 2023 | 32.053 | 30.997 | 3,4 % | 29.851 | 28.866 | 3,4 % |
| 21 | 2024 | 32.096 | 31.033 | 3,4 % | 29.747 | 28.803 | 3,3 % |
| 21 | 2025 | 31.007 | 29.498 | 5,1 % | 28.439 | 27.285 | 4,2 % |

Un viaje cuenta una vez con la regla de fn_insert_timbradas_anio (una sola estacionalidad por viaje, la de período más corto). En la exportación de timbradas_anio, los festivos con dos filas aparecen con las dos y los días corrientes suman más viajes que los aptos de esas fechas: son preguntas para Extreme, no diferencias del contraste.

## Por qué no por hora (hallazgo H10)

Promedio por viaje del consolidado por ruta × día ISO × hora frente a los viajes válidos de 2023-2025 asignados a la hora de SALIDA (la del histórico propio) o a la de FIN del viaje (la de fn_insert_timbradas_anio), en las celdas con al menos 30 viajes de cada lado:

| Asignación | Celdas | Subidas: mediana | Subidas: p90 | Bajadas: mediana | Bajadas: p90 |
|---|---|---|---|---|---|
| por hora de salida | 348 | 20,6 % | 87,1 % | 21,4 % | 98,0 % |
| por hora de fin | 432 | 1,3 % | 9,5 % | 1,2 % | 10,7 % |

Por hora de fin, el consolidado se reproduce casi exacto; por hora de salida, no, sin error de nadie. Por eso el ciclo contrasta por ruta × día ISO × estacionalidad, donde las dos asignaciones coinciden.

## timbradas_segmentos_anio y timbradas_segmentos_consolidado

- timbradas_segmentos_anio: 0 filas del proceso 'sobusa' → el ciclo registra «sin_filas_fuente» en metricas.calidad.consolidados (hallazgo H4: los scripts 5 y 6 de Extreme filtran el proceso «cootransoriente» y no llenan las tablas por segmento de Sobusa). Cuando las tenga, la comparación que puede bloquear (CONTR-002) va por id_segmento × ano × id_dia_semana × id_estacionalidad, y el rango (CONTR-003, no bloqueante), por id_segmento × ano × id_dia_semana × id_estacionalidad × hora.
- timbradas_segmentos_consolidado: 0 filas del proceso 'sobusa' → el ciclo registra «sin_filas_fuente» en metricas.calidad.consolidados (hallazgo H4: los scripts 5 y 6 de Extreme filtran el proceso «cootransoriente» y no llenan las tablas por segmento de Sobusa). Cuando las tenga, la comparación que puede bloquear (CONTR-002) va por id_segmento × id_dia_semana × id_estacionalidad, y el rango (CONTR-003, no bloqueante), por id_segmento × id_dia_semana × id_estacionalidad × hora.

El grano que puede bloquear: por segmento × día ISO × estacionalidad (y año en la anual) y no por hora: fn_insert_timbradas_anio pone todos los segmentos de un viaje en el bloque de 15 minutos de su fin (hallazgo H10) y la agregación propia, en la hora en que el bus pasó por cada segmento. Medido con filas reales de la liquidación, en una transacción que se revierte: `segmentos_filas_reales.json` (`tests/replica/test_consolidados_segmentos.py`).
