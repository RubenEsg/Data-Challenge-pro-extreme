# Backtest de la restricción reactiva de ocupación observada (§10.1)

Generado por `scripts/backtest_ocupacion_reactiva.py` el 2026-11-10T04:56:17-05:00 con los viajes por segmento de 2023-01-01 a 2023-02-27. Es una restricción de seguridad, no un re-pronóstico: el backtest del proyecto ya mostró que re-pronosticar dentro del día no mejora la precisión. Regla: si la ocupación observada del segmento crítico en una hora cerrada es ≥ 90 %, la hora siguiente no baja de ceil(carga crítica / (50 × 0,85)) salidas.

## Persistencia y efecto frente a la operación real

- Pares de horas seguidas medidos: 2523; disparos: 147 (CL 72: 29, CRA 54: 104, SILENCIO: 14).
- La hora siguiente queda sobre el umbral en el 28,6 % de los disparos, frente a una tasa base de 5,9 % (lift 4,84).
- La regla agregaría 457 salidas en 99 de los 147 disparos, sobre 2219 salidas reales en esas horas; 292 de ellas en horas que no quedaron sobre el umbral.
- Horas siguientes sobre el umbral: 42 sin la regla y 14 con ella; pasajeros por encima de la ocupación crítica en el segmento crítico: 3.490,0 sin la regla y 1.541,0 con ella.
- Supuesto: la carga crítica observada de la hora siguiente se reparte por igual entre sus salidas y no cambia con la oferta (aproximación contrafactual).

## Frente al plan del día con el modelo activo

- Días-ruta con disparo: 69 (errores del plan: 0).
- El piso sube la hora siguiente del plan en 83 de 147 disparos y agrega 500 salidas a 2271.
- Camino real del código en 12 disparos: todos óptimos = True; la hora queda en max(plan, piso) en 12.
- Cuando el piso sube la hora (9 casos), el MILP cambia también otras horas en 9 (la suavidad y la flota en ruta: con la flota activa el piso se cumple quitando salidas a otras horas) y el costo del día del MILP sube hasta 7.868.510 COP; es el precio de la seguridad, y la restricción lo dice en el plan.

| Ruta | Fecha | Hora | Ocupación observada | Piso | Plan sin piso | Plan con piso | Otras horas cambiadas | Δ salidas día | Δ costo día (COP) |
|---|---|---|---|---|---|---|---|---|---|
| CRA 54 | 2023-02-18 | 18 | 122 % | 21 | 11 | 21 | 5 | 22 | 1.181.385 |
| CRA 54 | 2023-02-21 | 17 | 116 % | 6 | 9 | 9 | 0 | 0 | 0 |
| CRA 54 | 2023-02-18 | 17 | 116 % | 20 | 17 | 20 | 3 | 10 | 183.153 |
| CL 72 | 2023-02-06 | 16 | 115 % | 3 | 12 | 12 | 0 | 0 | 0 |
| SILENCIO | 2023-02-23 | 5 | 114 % | 6 | 23 | 23 | 0 | 0 | 0 |
| CRA 54 | 2023-01-24 | 16 | 114 % | 21 | 18 | 21 | 4 | 1 | 586.430 |
| CRA 54 | 2023-02-03 | 16 | 114 % | 25 | 16 | 25 | 5 | 0 | 5.431.012 |
| CRA 54 | 2023-02-13 | 16 | 113 % | 26 | 19 | 26 | 7 | -5 | 7.706.863 |
| CRA 54 | 2023-02-06 | 16 | 113 % | 26 | 18 | 26 | 6 | -2 | 7.868.510 |
| CRA 54 | 2023-02-02 | 16 | 112 % | 26 | 17 | 26 | 7 | 0 | 7.288.994 |
| CRA 54 | 2023-02-23 | 16 | 112 % | 25 | 17 | 25 | 7 | -5 | 5.887.409 |
| CRA 54 | 2023-01-18 | 16 | 111 % | 20 | 17 | 20 | 4 | 2 | 310.959 |

## En tiempo real: la hora cerrada con sus viajes todavía en curso

Las cifras frente a la operación y frente al plan usan la hora cerrada con todos sus viajes completos. Un viaje dura unas 206 min (mediana), así que en un ciclo intradía los viajes de la hora h van por la mitad cuando se programa la hora siguiente. Supuesto: cada segmento llega por el trigger cuando el viaje lo termina de recorrer: salida + la fracción de la duración del viaje que corresponde al km del final del segmento; solo se mide la hora h (si tuviera menos de 2 viajes medidos, el ciclo miraría la anterior).

| Ciclo intradía a las | Disparos con viajes completos | Siguen disparando | Piso en tiempo real / piso completo | Disparos en tiempo real | Hora siguiente sobre el umbral si dispara |
|---|---|---|---|---|---|
| (h+1):05 | 147 | 25 | 0,42 | 39 | 15,4 % |
| (h+1):30 | 147 | 35 | 0,81 | 58 | 12,1 % |

Las cifras de efecto de las secciones anteriores son una cota superior: en la operación la regla actúa con los viajes que ya pasaron por el segmento crítico.

## Limitaciones

- Solo hay subidas y bajadas por segmento de 2023-01-01 a 2023-02-27; el efecto en otros meses no se midió.
- El efecto frente a la operación es contrafactual: supone que la carga de la hora siguiente se reparte por igual entre sus salidas y que la demanda no cambia con la oferta.
- La hora se mide por salida del viaje; en un ciclo intradía real la última hora cerrada llega con el retraso de la duración del viaje (la regla aplica a la siguiente hora todavía programable, a lo sumo 2 h después): la sección «En tiempo real» lo mide con el avance de cada viaje, y el camino real del código de la muestra usa la hora cerrada completa.
- El plan con el modelo activo en 2023 está dentro del periodo de entrenamiento del modelo: sirve para comprobar que el piso no rompe el MILP, no para medir la precisión.
