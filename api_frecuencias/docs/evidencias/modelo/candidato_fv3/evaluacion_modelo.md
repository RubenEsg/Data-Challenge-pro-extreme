# Evaluación del modelo de demanda

Generado 2026-11-16T15:13:31-05:00 con `scripts/evaluar_modelo.py` (mismo protocolo y mismas filas para todos).

## Prueba reservada 2025-11-01 a 2025-12-31

| Modelo | n | MAE | RMSE | WAPE % | IC95 WAPE (bloques de 7 días) | sMAPE % | Sesgo % |
|---|---|---|---|---|---|---|---|
| candidato (hgb_fv3_20250831_s42) | 3111 | 93,61 | 136,42 | 14,36 | 12,98–16,13 | 21,85 | 1,23 |
| anterior (hgb_fv2_20250831_s42) | 3111 | 96,27 | 140,86 | 14,77 | 13,10–16,87 | 22,23 | 2,75 |
| B1 regla manual 8 sem | 3111 | 138,06 | 225,99 | 21,18 | 16,61–26,79 | 26,28 | 5,85 |
| B2 última semana | 3111 | 172,05 | 279,22 | 26,40 | 22,77–30,57 | 33,72 | 3,84 |

Diferencias de WAPE (puntos porcentuales, IC95 bootstrap; P(mejora) = fracción de réplicas < 0):

- cand_menos_b1: -11,23 a -3,34 pp, P(mejora) 1.00
- anterior_menos_b1: -10,43 a -3,21 pp, P(mejora) 1.00
- b2_menos_b1: 2,13 a 7,89 pp, P(mejora) 0.00
- cand_menos_anterior: -1,02 a 0,06 pp, P(mejora) 0.94
- b1_menos_anterior: 3,21 a 10,43 pp, P(mejora) 0.00
- b2_menos_anterior: 8,47 a 14,70 pp, P(mejora) 0.00

### Por ruta (WAPE %)

| Ruta | candidato (hgb_fv3_20250831_s42) | anterior (hgb_fv2_20250831_s42) | B1 regla manual 8 sem | B2 última semana |
|---|---|---|---|---|
| CL 72 | 18,64 | 19,23 | 25,27 | 33,12 |
| CRA 54 | 12,69 | 13,04 | 19,79 | 24,31 |
| SILENCIO | 14,94 | 15,33 | 21,30 | 26,18 |

### Por franja y pico/valle (WAPE % / sesgo % del activo)

| Franja | n | activo WAPE | activo sesgo | B1 WAPE |
|---|---|---|---|---|
| 04-05 | 366 | 10,39 | 0,42 | 24,94 |
| 06-08 pico | 549 | 10,53 | -0,92 | 16,92 |
| 09-16 valle | 1464 | 14,94 | 1,16 | 20,78 |
| 17-19 pico | 549 | 22,29 | 7,23 | 25,01 |
| 20 | 183 | 33,72 | 3,60 | 42,47 |
| pico | 1098 | 14,09 | 1,55 | 19,37 |
| valle | 2013 | 14,50 | 1,07 | 22,11 |

### Por condición (WAPE %; * = menos de 100 filas)

| Condición | n | activo | anterior | B1 | sesgo activo |
|---|---|---|---|---|---|
| laboral | 1989 | 13,95 | 14,38 | 17,89 | 1,38 |
| sabado | 459 | 13,34 | 13,71 | 14,16 | 1,81 |
| domingo_festivo | 663 | 18,27 | 18,61 | 50,89 | -0,40 |
| festivo | 204 | 20,02 | 21,11 | 145,99 | 4,01 |
| vispera_festivo | 255 | 25,43 | 30,28 | 43,41 | 10,55 |
| post_festivo | 204 | 11,24 | 11,81 | 16,10 | 0,72 |
| vacaciones | 816 | 18,36 | 19,87 | 32,01 | 1,52 |
| navidad* | 51 | 27,39 | 29,80 | 273,68 | 5,50 |
| lluvia_5mm | 357 | 14,68 | 14,87 | 24,73 | 2,15 |
| seco | 1326 | 15,22 | 15,97 | 23,76 | 0,74 |

### Cobertura P10-P90 (objetivo 80 %)

Cobertura % (bajo P10 % / sobre P90 %) y ancho medio P90 - P10 en pasajeros por hora. **v1** = conformal móvil por ruta (56 días previos); **v2** = calibración versionada del modelo (conformal de Mondrian por bloque horario ajustado solo con la validación), la que la API aplica hoy en cada predicción.

| Modelo | Banda del modelo | Calibración v1 | Calibración vigente | Ancho medio: modelo / v1 / vigente |
|---|---|---|---|---|
| candidato (hgb_fv3_20250831_s42) | 80,23 (10,80 / 8,97) | 78,27 (12,02 / 9,71) | v2: 77,95 (11,80 / 10,25) | 312,7 / 303,6 / 297,6 |
| anterior (hgb_fv2_20250831_s42) | 79,49 (12,18 / 8,33) | 77,88 (13,28 / 8,84) | v2: 77,82 (12,95 / 9,23) | 318,9 / 312,9 / 303,4 |

Calibración vigente del activo: conformal de Mondrian por ruta × bloque (v2), archivo `calibracion_v2.json` (SHA-256 `d3092d2846d4fc44…`, verificado al cargar el modelo), validación 2025-09-01 a 2025-10-31 (3111 horas); la prueba reservada no se usa. Cobertura por ruta con la calibración vigente: CL 72 78,01 %, CRA 54 76,18 %, SILENCIO 79,65 %. Detalle por hora, ruta y tipo de día: docs/evidencias/modelo/calibracion_condicional.md.

## Robustez: modelos congelados un año (semilla 42), fv3 (variables del activo) frente a fv2 (las del anterior)

| Año | fv3 WAPE [IC95] | fv2 WAPE [IC95] | B1 WAPE | fv3 − fv2 IC95 (pp) | meses fv3 mejor | cobertura fv3 modelo → conformal |
|---|---|---|---|---|---|---|
| 2024 | 15,76 [14,63–17,21] | 16,26 [14,97–17,91] | 21,55 | -0,81 a -0,25 | 11/12 | 67,46 → 79,26 |
| 2025 | 14,08 [13,52–14,69] | 14,48 [13,78–15,28] | 20,04 | -0,78 a -0,12 | 8/12 | 78,36 → 80,19 |

Horas afectadas por el contexto y el calendario académico (WAPE %, fv2 → fv3):

- 2024 todas (n=18564): 16,26 → 15,76 (B1 21,55)
- 2024 horas_con_novedad (n=246): 25,15 → 27,33 (B1 58,00)
- 2024 vispera_festivo (n=918): 23,40 → 22,13 (B1 33,80)
- 2024 post_festivo (n=918): 20,28 → 19,27 (B1 29,49)
- 2024 receso_escolar (n=4386): 20,17 → 18,27 (B1 27,23)
- 2024 vacaciones_universitarias (n=6579): 20,40 → 19,22 (B1 24,40)
- 2024 cambio_de_periodo (n=7497): 17,61 → 16,91 (B1 26,79)
- 2025 todas (n=18615): 14,48 → 14,08 (B1 20,04)
- 2025 horas_con_novedad (n=255): 33,49 → 32,77 (B1 81,38)
- 2025 vispera_festivo (n=867): 20,18 → 18,35 (B1 33,40)
- 2025 post_festivo (n=867): 15,46 → 14,49 (B1 27,01)
- 2025 receso_escolar (n=4335): 17,36 → 15,61 (B1 28,71)
- 2025 vacaciones_universitarias (n=6834): 16,07 → 15,46 (B1 22,32)
- 2025 cambio_de_periodo (n=8109): 15,28 → 14,87 (B1 22,60)

Notas: la lluvia (clima_diario) es observada y diaria; aquí solo es condición de análisis. Las condiciones con menos de 100 filas tienen intervalos amplios.
