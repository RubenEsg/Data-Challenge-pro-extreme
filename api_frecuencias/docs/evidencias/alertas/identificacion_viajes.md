# §5.3 Empresa, ruta, sentido, viaje, conductor y vehículo, cuando aplique

Generado 2026-11-10T10:50:06-05:00 con `scripts/evidencia_identificacion_alertas.py`, leyendo la réplica local en solo lectura como `lector_ia` (el mismo SELECT de la lista blanca que usa el ciclo, `fuentes.FuentePostgresSoloLectura.viajes`). El conductor solo sale como seudónimo (HMAC con `SEUDONIMO_SECRETO`, §18) y esta evidencia no copia ninguno.

## Qué campos aplican a cada regla (`alertas.IDENTIFICACION_5_3` y `alertas.VARIANTES_5_3`)

La empresa (catálogo) y la ruta (con su `idruta`) aplican a todas. El sentido no aplica a las reglas por ruta de este motor: la serie es por ruta y cada viaje recorre el circuito completo (ida y regreso); el sentido solo existe por segmento (supuesto S9) (medido en la sección C). La excepción son las variantes de `VARIANTES_5_3`: la ALT-002 observada medida en el segmento crítico de la hora (§10.1) lleva el sentido aproximado de ese segmento y el viaje más cargado en él (sección D). Cada alerta lo dice en `variables.identificacion_5_3`.

| Código | Alerta | Viaje, vehículo y conductor | Por qué |
|---|---|---|---|
| ALT-001 | Alta demanda prevista | no aplican | pronóstico de la ruta para una franja futura: todavía no hay un viaje, un vehículo ni un conductor que atribuirle |
| ALT-002 | Sobreocupación | no aplican | la ocupación es de la ruta en la franja (pronóstico) o en la hora con el factor de carga (observada sin la ocupación por segmento), con varios buses: no es de un viaje |
| ALT-003 | Frecuencia insuficiente | no aplican | pronóstico de la ruta para una franja futura: todavía no hay un viaje, un vehículo ni un conductor que atribuirle |
| ALT-004 | Frecuencia excesiva | no aplican | pronóstico de la ruta para una franja futura: todavía no hay un viaje, un vehículo ni un conductor que atribuirle |
| ALT-005 | Caída anormal de demanda | no aplican | la regla mide la demanda agregada de la ruta en la ventana (todos sus viajes), no un viaje |
| ALT-006 | Despacho ausente o tardío | aplican | el despacho de la ventana que no salió o salió tarde (progvehiculos): su viaje, su vehículo y el seudónimo de su conductor |
| ALT-007 | Desviación del pronóstico | no aplican | la regla mide la demanda agregada de la ruta en la ventana (todos sus viajes), no un viaje |
| ALT-008 | Consolidado anómalo | no aplican | consolidado diario de la ruta (subidas, bajadas y número de viajes del día), no un viaje |
| ALT-009 | Datos incompletos | aplican | el viaje de la ventana con datos faltantes (progvehiculos): su viaje, su vehículo y el seudónimo de su conductor |
| ALT-010 | Modelo degradado | no aplican | degradación del modelo de la ruta, no de un viaje |

| Código | Variante | Campos que aplican | Sentido | Por qué |
|---|---|---|---|---|
| ALT-002 | `segmento_critico` | sentido, viaje, vehiculo, conductor | aproximado: el del segmento crítico donde se midió la ocupación (§10.1); el sentido solo existe por segmento (supuesto S9) | la ocupación observada medida en el segmento crítico de la hora pico (§10.1): el sentido aproximado de ese segmento y el viaje más cargado en él, con su vehículo y el seudónimo de su conductor |

Cuando aplican, la alerta guarda el viaje (`progvehiculos.idprogramacion`), el vehículo (`idvehiculo`) y el seudónimo del conductor del viaje principal, y en `variables` la lista de los viajes de la ventana (hasta 10) con su estado, su retraso y su seudónimo.

## A. ALT-006 con los viajes reales (2025-09-15 a 2025-12-31)

Contextos del ciclo con la serie empaquetada (los del backtest de observadas) y los viajes de cada ruta y día con ALT-006 (36 días-ruta leídos en 8,6 s).

| Medida | Valor |
|---|---|
| ALT-006 | 41 |
| Con viaje, vehículo y conductor | 40 (97,6 %) |
| Con seudónimo del conductor | 40 |
| Rol del viaje: cancelado | 36 |
| Rol del viaje: sin_viaje_cancelado_ni_tardio | 1 |
| Rol del viaje: tardio | 4 |
| Viajes válidos de la ventana = salidas de la serie horaria | 41 de 41 |
| Con el último despacho antes de la ventana | 41 |

«cancelado»: el despacho programado de la ventana que se canceló (despacho ausente); «tardio»: salió fuera del plazo (`excedeplazosalida`) o con un retraso de la salida real mayor que la tolerancia; «sin_viaje_cancelado_ni_tardio»: todos los viajes programados salieron a tiempo, el déficit es de programación y la alerta no inventa un viaje (deja el último despacho en `variables`).

## B. ALT-009 con la lectura integrada de la réplica (2023-01-01 a 2023-02-27)

`demanda_segmentos` (lo que lee el ciclo con `FUENTE=postgres`): 2757 horas de 166 días-ruta; 36 días-ruta con 44 horas de servicio que no llegaron hasta la última que sí llegó (ningún viaje de la hora con timbradas de segmento, o ningún viaje). Con los viajes del día, ALT-009 descarta las horas sin ningún viaje programado no cancelado (no había servicio que capturar) y, en las que quedan, identifica el viaje con datos faltantes.

| Medida | Valor |
|---|---|
| Días-ruta sin ALT-009: ninguna de sus horas faltantes tenía un viaje programado no cancelado | 35 |
| Horas faltantes descartadas por no tener servicio programado | 43 |
| ALT-009 por horas faltantes | 1 |
| Con viaje, vehículo y conductor | 1 (100,0 %) |
| Con seudónimo del conductor | 1 |
| Viajes programados en las horas faltantes | 3 |
| Viajes con datos faltantes en esas horas | 1 |
| Viajes con datos faltantes en esos días | 2 |
| Resultado: identificado | 1 |
| Motivo (en la lista de cada alerta): sin_numeropasajeros | 2 |
| Motivo (en la lista de cada alerta): sin_timbradas_segmento | 2 |

## C. El sentido: cada viaje recorre el circuito (réplica, capa de segmentos)

Parte de los segmentos de su ruta que toca cada viaje en `timbradas_segmentos` (cota inferior: un segmento sin subidas ni bajadas puede no tener fila). El supuesto S9 parte el ciclo en dos mitades (ida y regreso): un viaje que toca más de la mitad recorre los dos sentidos, así que ni la alerta de un viaje ni la de la ruta tienen un solo sentido (medido en 2,0 s).

| Ruta | Viajes | Segmentos de la ruta | P10 de la parte tocada | Mediana | Viajes con más de medio circuito |
|---|---|---|---|---|---|
| CL 72 | 4554 | 128 | 0,766 | 0,867 | 94,5 % |
| CRA 54 | 14857 | 123 | 0,780 | 0,846 | 96,7 % |
| SILENCIO | 7369 | 135 | 0,719 | 0,822 | 96,1 % |

## D. ALT-002 medida en el segmento crítico (réplica, ocupación actual por segmento)

Las 2757 franjas de la capa de segmentos (56 días), leídas viaje × segmento con `fuentes.leer_carga_segmentos` (solo lectura, el conductor ya seudonimizado) y resumidas con `app/servicios/ocupacion.py` como en el ciclo integrado; cada hora lleva su segmento crítico (`ejecucion.con_ocupacion_por_segmento`) y se evalúan las reglas observadas (75,5 s).

| Medida | Valor |
|---|---|
| Horas con segmento crítico medido | 2757 |
| … con sentido aproximado | 2757 (100,0 %) |
| … con el viaje más cargado | 2757 (100,0 %) |
| … con su vehículo | 2757 |
| … con el seudónimo de su conductor | 2757 |
| Ocupación media máxima del segmento crítico en una hora | 184,0 % |
| ALT-002 observadas por método | segmento_critico: 31 |
| ALT-002 con la variante segmento_critico | 31 |
| … con sentido / viaje / conductor | 31 / 31 / 31 |

## Ejemplos (sin el seudónimo)

- ALT-006 CL 72 (ALT-006|CL 72|2025-09-17T11:00:00-05:00|obs): viaje 7313342, vehículo SOBUSA180, conductor seudonimizado: sí. En 11:00-12:00 (1 h): salieron 0 de 4 despachos esperados (60 / intervalo programado). Despacho ausente o tardío: van al menos 60 min sin despacho (cota inferior: horas cerradas sin salidas), más que el headway programado (14,4 min) más la tolerancia (5 min, threshold_config.tolerancia_despacho_min); salieron 0 de 4 despachos esperados (déficit 100,0 %, tolerancia 50,0 %). Viaje 7313342 (vehículo SOBUSA180), salida programada 11:12: programado y cancelado (despacho ausente).
- ALT-006 CL 72 (ALT-006|CL 72|2025-09-17T18:00:00-05:00|obs): viaje 7314467, vehículo SOBUSA368, conductor seudonimizado: sí. En 18:00-20:00 (2 h): salieron 4 de 10 despachos esperados (60 / intervalo programado). Despacho ausente o tardío: salieron 4 de 10 despachos esperados (déficit 59,7 %, tolerancia 50,0 %). Viaje 7314467 (vehículo SOBUSA368), salida programada 19:24: programado y cancelado (despacho ausente).
- ALT-009 SILENCIO (ALT-009|SILENCIO|2023-01-01|faltantes): viaje 5061806, vehículo SOBUSA468, conductor seudonimizado: sí. Datos incompletos o retrasados: faltan 1 hora(s) de servicio sin registro: 01/01/2023 06:00. Viajes con datos faltantes: 2 (el primero, viaje 5061806 del vehículo SOBUSA468 a las 06:00: sin numeropasajeros, sin timbradas de segmento (no llegó a timbradas_segmentos)).
- ALT-002 CRA 54 (ALT-002|CRA 54|2023-01-01T16:00:00-05:00|obs): viaje 5062055, vehículo SOBUSA231, conductor seudonimizado: sí. La ocupación observada (96,7 %) alcanza o supera el umbral crítico (90,0 %). Esperada: —; observada: 96,7 % (= 48,3 pasajeros a bordo en promedio al salir del segmento crítico 85 (regreso) en 3 viajes ÷ 50 puestos en 17:00-18:00, medida con las subidas y bajadas por segmento).
- ALT-002 CRA 54 (ALT-002|CRA 54|2023-01-16T14:00:00-05:00|obs): viaje 5093236, vehículo SOBUSA495, conductor seudonimizado: sí. La ocupación observada (98,9 %) alcanza o supera el umbral crítico (90,0 %). Esperada: —; observada: 98,9 % (= 49,4 pasajeros a bordo en promedio al salir del segmento crítico 91 (regreso) en 18 viajes ÷ 50 puestos en 15:00-16:00, medida con las subidas y bajadas por segmento).

## Limitaciones

- En el modo empaquetado (sin réplica ni exportación de `progvehiculos`) la serie es horaria: las alertas salen igual, con `identificacion_5_3.resultado = fuente_sin_viajes`.
- El conteo de segmentos solo se usa cuando el ciclo lee la capa de segmentos (`demanda_segmentos`); con la serie empaquetada de 2025 no se informa, porque la capa de la réplica solo cubre enero y febrero de 2023.
- Sin `SEUDONIMO_SECRETO` el conductor queda nulo (nunca en claro).
- El descarte de las horas sin servicio programado solo se hace cuando la fuente trae los viajes del día; sin ellos (la fuente no los expone, o no trae ninguno de ese día: `fuente_sin_viajes_del_dia`), ALT-009 cuenta toda hora faltante, como antes.
- La sección C usa la capa de segmentos de la réplica (enero y febrero de 2023); el sentido por segmento es la aproximación geométrica del supuesto S9, que debe confirmar Extreme.
