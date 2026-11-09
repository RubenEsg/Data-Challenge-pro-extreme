# Backtest de alertas observadas ALT-005..ALT-009 (2025-01-15 a 2025-12-31)

Generado 2026-11-09T02:08:39-05:00 con scripts/backtest_alertas.py. Modelo: fv2 temporal (corte 2024-12-31, semilla 42, en backtest_alertas_5e6dc3gb) (corte 2024-12-31). Banda P10-P90 calibrada en el 100,0 % de las horas. 1053 días-ruta, 351 días.

No hay incidentes etiquetados: la precisión se aproxima con la persistencia de la condición en la hora siguiente a la DETECCIÓN, es decir, el episodio dura más horas que las necesarias para alertar (ALT-005/006/007), o con el día marcado como especial o excluido (ALT-008); lift = precisión / tasa base de la condición en una hora cualquiera. Una alerta no confirmada se cuenta como falso positivo (§18).

ALT-006: Procesos.toleranciatiempo = 0 en la exportación: se usa tolerancia_despacho_min.

## Umbrales por defecto (versionados en threshold_config por la migración 0003)

| Código | Alertas | Por ruta y día | Por día (3 rutas) | Precisión proxy | Tasa base | Lift | En días especiales |
|---|---|---|---|---|---|---|---|
| ALT-005 | 121 | 0,115 | 0,34 | 0,336 | 0,073 | 4,58 | 46,3 % |
| ALT-006 | 94 | 0,089 | 0,27 | 0,394 | 0,041 | 9,57 | 63,8 % |
| ALT-007 | 195 | 0,185 | 0,56 | 0,209 | 0,183 | 1,14 | 42,1 % |
| ALT-008 | 65 | 0,062 | 0,18 | 0,677 | 0,322 | 2,10 | 67,7 % |
| ALT-009 | 0 | 0,000 | 0,00 | — | — | — | — |

Alertas observadas por ruta y día (todas): 0.451.

## Reglas anteriores (sin persistencia, sin P10, tolerancia de salidas 20 %, |z| 3,0)

| Código | Alertas | Por ruta y día | Por día (3 rutas) | Precisión proxy | Tasa base | Lift | En días especiales |
|---|---|---|---|---|---|---|---|
| ALT-005 | 1393 | 1,323 | 3,97 | 0,173 | 0,096 | 1,80 | 35,0 % |
| ALT-006 | 2838 | 2,695 | 8,09 | 0,330 | 0,255 | 1,29 | 30,0 % |
| ALT-007 | 1679 | 1,595 | 4,78 | 0,156 | 0,183 | 0,85 | 33,1 % |
| ALT-008 | 94 | 0,089 | 0,27 | 0,575 | 0,322 | 1,78 | 57,4 % |
| ALT-009 | 0 | 0,000 | 0,00 | — | — | — | — |

Alertas observadas por ruta y día (todas): 5.702.

## Un ejemplo por código (lo que vería el operador, §9.4)

| Código | Ruta | Ventana | Real | Esperado | Umbral | Tendencia | Explicación |
|---|---|---|---|---|---|---|---|
| ALT-005 | CL 72 | 2025-01-19 14:00-16:00 | 252.0 | 588.9715 | 412.28 | a_la_baja | Durante 2 hora(s) seguidas (14:00-16:00) la demanda real (252 pasajeros) cayó 57,2 % frente al patrón del modelo (589); el umbral de caída es 30,0 % (límite 412) y quedó bajo el P10 calibrado (326); persistencia exigida: 2 h. |
| ALT-006 | CL 72 | 2025-01-19 14:00-16:00 | 4.0 | 9.0502 | 4.5251 | a_la_baja | En 14:00-16:00 (2 h): salieron 4 de 9 despachos esperados (60 / intervalo programado). Despacho ausente o tardío: salieron 4 de 9 despachos esperados (déficit 55,8 %, tolerancia 50,0 %). |
| ALT-007 | CL 72 | 2025-02-17 17:00-19:00 | 916.0 | 713.1119 | 905.5546 | al_alza | Durante 2 hora(s) seguidas (17:00-19:00) la demanda real (916) quedó por encima del P90 del intervalo calibrado (906); pronóstico 713, error 28,5 % (umbral 15,0 %); persistencia exigida: 2 h. |
| ALT-008 | CL 72 | 2025-03-03 00:00-00:00 | 19.0 | 90.0 | 69.2436 | a_la_baja | Consolidado atípico: subidas = 1.770 frente a la mediana de 7.628,0 (z = -6,15); nro_viajes = 19 frente a la mediana de 90,0 (z = -11,97) (umbral |z| ≥ 3,5). Límite para nro_viajes: 69 (mediana 90 - 3,5 × 5,9). |

Duración: 50,5 s.
