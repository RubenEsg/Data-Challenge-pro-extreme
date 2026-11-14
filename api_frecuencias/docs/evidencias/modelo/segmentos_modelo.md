# Modelo por segmento y sentido: resultados

Generado por `scripts/entrenar_segmentos.py` con el protocolo de `segmentos_protocolo.md` (fijado antes de mirar la prueba). Detalle completo en `segmentos_modelo.json`.

Datos: `datos/subidas_segmento_hora.parquet` (341820 filas, 2263584 subidas, SHA-256 `b37c7238ffc39133…`). Partición: entrenamiento 2023-01-01 a 2023-02-08; validacion 2023-02-09 a 2023-02-17; prueba 2023-02-18 a 2023-02-27.

## Validación (elige el modelo)

| Modelo | Tipo | WAPE segmento-hora % | WAPE sentido-hora % | MAE segmento-hora | Sesgo absoluto mediano por segmento % | Sesgo absoluto p90 por segmento % | Δ WAPE vs B0 (IC95, pp) |
|---|---|---|---|---|---|---|---|
| B0 | reparto_fijo | 38,06 | 8,47 | 2,87 | 8,74 | 26,11 | — |
| M1 | hgb_offset_reparto | 37,25 | 9,23 | 2,81 | 7,45 | 26,19 | -0,82 [-1,53; 0,03] |
| M2 | hgb_offset_total | 36,93 | 9,04 | 2,79 | 7,07 | 23,82 | -1,14 [-1,79; -0,48] |
| M3 | hgb_dentro_del_sentido | 36,83 | 8,47 | 2,78 | 7,55 | 24,71 | -1,23 [-1,85; -0,58] |
| M4 | hgb_jerarquico | 36,80 | 8,34 | 2,78 | 7,50 | 24,39 | -1,27 [-1,88; -0,62] |

Regla: elegible si mejora el WAPE por segmento y hora de B0 con el IC95 bootstrap por días de la validación por debajo de 0 y no empeora el WAPE por sentido y hora en más de 0,25 pp; gana el elegible de menor WAPE; sin elegibles sigue B0. Salvaguarda: si el elegido es peor que B0 en la prueba, no se activa.

**Elegido en la validación: M4. Activo: seg_hgb_jerarquico_20230227_s42** (M4 cumple la regla en la validación y no empeora a B0 en la prueba).

## Prueba (una sola vez)

Con el total real de la ruta (error del reparto):

| Modelo | Tipo | WAPE segmento-hora % | WAPE sentido-hora % | MAE segmento-hora | Sesgo absoluto mediano por segmento % | Sesgo absoluto p90 por segmento % | Δ WAPE vs B0 (IC95, pp) |
|---|---|---|---|---|---|---|---|
| B0 | reparto_fijo | 43,06 | 8,20 | 2,55 | 7,98 | 25,33 | — |
| M1 | hgb_offset_reparto | 42,63 | 8,62 | 2,52 | 7,75 | 24,40 | — |
| M2 | hgb_offset_total | 42,12 | 8,55 | 2,49 | 7,55 | 21,99 | — |
| M3 | hgb_dentro_del_sentido | 42,11 | 8,20 | 2,49 | 7,64 | 21,08 | — |
| M4 | hgb_jerarquico | 42,09 | 8,19 | 2,49 | 7,57 | 21,19 | — |

De punta a punta con B2 (pronóstico de ruta de la misma hora hace 7 días, fuera de muestra):

| Modelo | Tipo | WAPE segmento-hora % | WAPE sentido-hora % | MAE segmento-hora | Sesgo absoluto mediano por segmento % | Sesgo absoluto p90 por segmento % | Δ WAPE vs B0 (IC95, pp) |
|---|---|---|---|---|---|---|---|
| B0 | reparto_fijo | 64,40 | 43,56 | 3,83 | 11,56 | 28,84 | — |
| M1 | hgb_offset_reparto | 64,32 | 43,73 | 3,82 | 10,21 | 30,54 | — |
| M2 | hgb_offset_total | 63,82 | 43,67 | 3,79 | 11,00 | 29,38 | — |
| M3 | hgb_dentro_del_sentido | 63,81 | 43,56 | 3,79 | 10,94 | 29,07 | — |
| M4 | hgb_jerarquico | 63,78 | 43,52 | 3,79 | 11,06 | 28,91 | — |

## Banda P10-P90 del activo (M4) en la prueba

| Pronóstico de la ruta | Nivel | Filas | Cobertura % | Bajo P10 % | Sobre P90 % | Ancho medio | Subidas medias |
|---|---|---|---|---|---|---|---|
| Total real de la ruta (solo reparto) | segmento | 63166 | 78,31 | 10,65 | 11,03 | 7,04 | 5,92 |
| Total real de la ruta (solo reparto) | sentido | 982 | 83,40 | 9,06 | 7,54 | 111,41 | 380,80 |
| De punta a punta con B2 (ruta fuera de muestra) | segmento | 62903 | 72,16 | 14,34 | 13,51 | 8,57 | 5,94 |
| De punta a punta con B2 (ruta fuera de muestra) | sentido | 978 | 54,81 | 25,77 | 19,43 | 285,55 | 382,23 |

La banda de la ruta B2 (conformal relativa ajustada en la validación) cubre 51,74 % de las 489 horas de la prueba (36,51 % en Carnaval y 61,33 % fuera de él: B2 es la misma hora de la semana anterior, así que sobreestima los días de Carnaval y subestima la semana siguiente). La banda compuesta hereda ese defecto de la ruta; la del reparto sola, con el total real, es la de las dos primeras filas de la tabla.

**Análisis adicional (no previsto en el protocolo).** Con errores reales del modelo de ruta activo (hgb_fv2_20250831_s42, banda calibrada vigente, fuera de muestra 2025-11-01 a 2025-12-31) asignados al azar a cada hora de la prueba dentro del mismo estrato (ruta, tipo de día, hora), 20 réplicas: la banda de la ruta cubre 77,66 % y la compuesta cubre 79,46 % por segmento (rango 78,94 a 79,80) y 80,82 % por sentido (rango 78,62 a 83,71). Supone independencia entre el error de la ruta y el del reparto.

## Sesgo por sentido, segmento y condición del activo (M4) en la prueba (§9.3)

| Condición | WAPE segmento-hora % | Sesgo ida % | Sesgo regreso % | Sesgo absoluto mediano por segmento % | Ida con B2 % | Regreso con B2 % | Sesgo ruta 2025 % | Ida compuesto % | Regreso compuesto % |
|---|---|---|---|---|---|---|---|---|---|
| franja=04-05 | 33,25 | 2,74 | -4,02 | 13,76 | 14,63 | 7,03 | 2,08 | 4,88 | -2,02 |
| franja=06-08 pico | 35,49 | 0,79 | -1,48 | 9,80 | 11,77 | 9,50 | 0,79 | 1,59 | -0,70 |
| franja=09-16 valle | 42,96 | -2,99 | 3,55 | 8,56 | 3,97 | 11,35 | 2,63 | -0,44 | 6,27 |
| franja=17-19 pico | 54,01 | 0,77 | -1,04 | 14,38 | 1,17 | -0,32 | 8,34 | 9,17 | 7,21 |
| franja=20 | 76,54 | 5,24 | -5,74 | 26,08 | 16,45 | 6,99 | 5,27 | 10,79 | -0,77 |
| tipo_dia=domingo_festivo | 53,49 | -0,97 | 1,39 | 10,51 | -0,65 | 1,89 | 2,29 | 1,30 | 3,71 |
| tipo_dia=laboral | 38,38 | -0,99 | 1,36 | 7,26 | 11,71 | 14,24 | 2,90 | 1,88 | 4,30 |
| tipo_dia=sabado | 48,52 | 0,15 | -0,19 | 15,38 | -5,11 | -4,80 | 2,39 | 2,54 | 2,20 |
| carnaval=carnaval | 61,45 | -1,59 | 2,19 | 16,45 | 78,97 | 83,35 | — | — | — |
| carnaval=sin_carnaval | 35,86 | -0,48 | 0,65 | 7,53 | -16,37 | -14,90 | — | — | — |

Sesgo = Σ(p − y)/Σ y. «Con B2»: de punta a punta con el pronóstico B2 de la ruta. «Compuesto»: (1 + sesgo de la ruta) · (1 + sesgo del reparto) − 1, con el sesgo del modelo de ruta activo (hgb_fv2_20250831_s42) medido fuera de muestra en 2025-11-01 a 2025-12-31 por franja y tipo de día; es una composición declarada, no una medición conjunta (no hay subidas por segmento en 2025).

## Limitaciones

- Las subidas por segmento solo existen del 2023-01-01 al 2023-02-27 (los triggers de segmentación no se volvieron a ejecutar): el modelo se aplica a fechas posteriores sin poder medir su error en ellas.
- El sentido es una aproximación geométrica (supuesto S9): mitad de la longitud acumulada del ciclo.
- No hay pronósticos fuera de muestra del modelo de ruta activo para 2023: la cobertura de punta a punta se midió con B2 y la composición con el sesgo de la ruta usa el medido en 2025.
- El Carnaval (18 a 21 de febrero) solo está en la prueba: ningún modelo lo vio al entrenar.
