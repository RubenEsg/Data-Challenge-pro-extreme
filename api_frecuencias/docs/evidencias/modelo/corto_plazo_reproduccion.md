# La API reproduce la prueba reservada del pronóstico de corto plazo

Generado por `scripts/verificar_corto_plazo.py` el 2026-11-19 con el modelo `cp_lgbm_20250630_s42` (datos/modelos/corto_plazo). Detalle en `corto_plazo_reproduccion.json`.

Con el código de variables de la API y sus artefactos se pronosticó otra vez julio-diciembre de 2025 y se comparó con lo que guardó el experimento E14 la única vez que corrió su prueba (`pronostico_corto_plazo/resultados`). No se eligió nada con esto ni cambió ninguna cifra.

**Resultado: todo coincide.**

| Comparación | Filas | Diferencia máxima | Coincide |
|---|---|---|---|
| Predicciones por ruta (pronóstico, P10, P90, real y promedio) | 56.070 de 56.070 | 0,0054 subidas | sí |
| Predicciones por sentido (pronóstico, P10, P90, real y promedio) | 112.140 de 112.140 | 0,0051 subidas | sí |
| Total pronosticado por segmento y horizonte | 1.158 | 0,11 subidas | sí |
| Camino de un día de la API frente al periodo entero (12 días) | — | 0,0000 | sí |

| Nivel | Horizonte | WAPE con la API (%) | WAPE de la prueba (%) | Coincide |
|---|---|---|---|---|
| ruta | 30 min | 8,582 | 8,582 | sí |
| ruta | 60 min | 7,344 | 7,344 | sí |
| ruta | 120 min | 6,634 | 6,634 | sí |
| sentido | 30 min | 12,129 | 12,129 | sí |
| sentido | 60 min | 10,046 | 10,046 | sí |
| sentido | 120 min | 8,715 | 8,715 | sí |
| segmento | 30 min | 51,075 | 51,075 | sí |
| segmento | 60 min | 37,632 | 37,632 | sí |
| segmento | 120 min | 28,558 | 28,558 | sí |

Tolerancia de las predicciones: 0,006 subidas (el experimento las guardó redondeadas a dos decimales). Días del camino de un día: SILENCIO 2025-07-16, SILENCIO 2025-09-19, SILENCIO 2025-10-27, SILENCIO 2025-11-18, CRA 54 2025-07-17, CRA 54 2025-08-06, CRA 54 2025-10-05, CRA 54 2025-11-04, CL 72 2025-07-23, CL 72 2025-10-02, CL 72 2025-11-07, CL 72 2025-11-20.
