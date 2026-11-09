# Evaluación del modelo de demanda

Generado 2026-11-09T05:06:42-05:00 con `scripts/evaluar_modelo.py` (mismo protocolo y mismas filas para todos).

## Prueba reservada 2025-11-01 a 2025-12-31

| Modelo | n | MAE | RMSE | WAPE % | IC95 WAPE (bloques de 7 días) | sMAPE % | Sesgo % |
|---|---|---|---|---|---|---|---|
| activo (hgb_fv2_20250831_s42) | 3111 | 96,27 | 140,86 | 14,77 | 13,10–16,87 | 22,23 | 2,75 |
| fv1 (hgb_fv1_20250831_s42) | 3111 | 98,20 | 146,02 | 15,07 | 13,22–17,43 | 22,44 | 2,54 |
| B1 regla manual 8 sem | 3111 | 138,06 | 225,99 | 21,18 | 16,61–26,79 | 26,28 | 5,85 |
| B2 última semana | 3111 | 172,05 | 279,22 | 26,40 | 22,77–30,57 | 33,72 | 3,84 |

Diferencias de WAPE (puntos porcentuales, IC95 bootstrap; P(mejora) = fracción de réplicas < 0):

- cand_menos_b1: -10,43 a -3,21 pp, P(mejora) 1.00
- fv1_menos_b1: -9,88 a -3,06 pp, P(mejora) 1.00
- b2_menos_b1: 2,13 a 7,89 pp, P(mejora) 0.00
- cand_menos_fv1: -0,64 a -0,04 pp, P(mejora) 0.99
- b1_menos_fv1: 3,06 a 9,88 pp, P(mejora) 0.00
- b2_menos_fv1: 8,20 a 14,26 pp, P(mejora) 0.00

### Por ruta (WAPE %)

| Ruta | activo (hgb_fv2_20250831_s42) | fv1 (hgb_fv1_20250831_s42) | B1 regla manual 8 sem | B2 última semana |
|---|---|---|---|---|
| CL 72 | 19,23 | 19,48 | 25,27 | 33,12 |
| CRA 54 | 13,04 | 13,33 | 19,79 | 24,31 |
| SILENCIO | 15,33 | 15,68 | 21,30 | 26,18 |

### Por franja y pico/valle (WAPE % / sesgo % del activo)

| Franja | n | activo WAPE | activo sesgo | B1 WAPE |
|---|---|---|---|---|
| 04-05 | 366 | 10,65 | 2,08 | 24,94 |
| 06-08 pico | 549 | 10,79 | 0,79 | 16,92 |
| 09-16 valle | 1464 | 15,45 | 2,63 | 20,78 |
| 17-19 pico | 549 | 22,65 | 8,34 | 25,01 |
| 20 | 183 | 34,68 | 5,27 | 42,47 |
| pico | 1098 | 14,38 | 3,08 | 19,37 |
| valle | 2013 | 14,97 | 2,59 | 22,11 |

### Por condición (WAPE %; * = menos de 100 filas)

| Condición | n | activo | fv1 | B1 | sesgo activo |
|---|---|---|---|---|---|
| laboral | 1989 | 14,38 | 14,80 | 17,89 | 2,90 |
| sabado | 459 | 13,71 | 13,55 | 14,16 | 2,39 |
| domingo_festivo | 663 | 18,61 | 18,64 | 50,89 | 2,29 |
| festivo | 204 | 21,11 | 21,05 | 145,99 | 8,86 |
| vispera_festivo | 255 | 30,28 | 35,28 | 43,41 | 17,54 |
| post_festivo | 204 | 11,81 | 12,01 | 16,10 | 3,45 |
| vacaciones | 816 | 19,87 | 20,90 | 32,01 | 5,45 |
| navidad* | 51 | 29,80 | 30,42 | 273,68 | 12,22 |
| lluvia_5mm | 357 | 14,87 | 15,01 | 24,73 | 1,36 |
| seco | 1326 | 15,97 | 16,63 | 23,76 | 3,80 |

### Cobertura P10-P90 (objetivo 80 %)

Cobertura % (bajo P10 % / sobre P90 %) y ancho medio P90 - P10 en pasajeros por hora. **v1** = conformal móvil por ruta (56 días previos); **v2** = calibración versionada del modelo (conformal de Mondrian por bloque horario ajustado solo con la validación), la que la API aplica hoy en cada predicción.

| Modelo | Banda del modelo | Calibración v1 | Calibración vigente | Ancho medio: modelo / v1 / vigente |
|---|---|---|---|---|
| activo (hgb_fv2_20250831_s42) | 79,49 (12,18 / 8,33) | 77,88 (13,28 / 8,84) | v2: 77,82 (12,95 / 9,23) | 318,9 / 312,9 / 303,4 |
| fv1 (hgb_fv1_20250831_s42) | 80,94 (11,28 / 7,78) | 78,59 (12,86 / 8,55) | v1 (el modelo no trae calibración versionada) | 325,0 / 316,3 / — |

Calibración vigente del activo: conformal de Mondrian por bloque (v2), archivo `calibracion_v2.json` (SHA-256 `dae6b1a616ee0d89…`, verificado al cargar el modelo), validación 2025-09-01 a 2025-10-31 (3111 horas); la prueba reservada no se usa. Cobertura por ruta con la calibración vigente: CL 72 78,40 %, CRA 54 73,67 %, SILENCIO 81,39 %. Detalle por hora, ruta y tipo de día: docs/evidencias/modelo/calibracion_condicional.md.

## Robustez: modelos congelados un año (semilla 42)

| Año | fv2 WAPE [IC95] | fv1 WAPE [IC95] | B1 WAPE | fv2 − fv1 IC95 (pp) | cobertura fv2 modelo → conformal |
|---|---|---|---|---|---|
| 2024 | 16,26 [14,97–17,91] | 16,25 [14,97–17,90] | 21,55 | -0,08 a 0,09 | 67,67 → 79,37 |
| 2025 | 14,48 [13,78–15,28] | 14,53 [13,77–15,40] | 20,04 | -0,17 a 0,05 | 78,51 → 80,12 |

Horas afectadas por el contexto (WAPE %, fv1 → fv2):

- 2024 todas (n=18564): 16,25 → 16,26 (B1 21,55)
- 2024 horas_con_novedad (n=246): 28,06 → 25,15 (B1 58,00)
- 2024 vispera_festivo (n=918): 24,12 → 23,40 (B1 33,80)
- 2024 post_festivo (n=918): 20,22 → 20,28 (B1 29,49)
- 2025 todas (n=18615): 14,53 → 14,48 (B1 20,04)
- 2025 horas_con_novedad (n=255): 35,11 → 33,49 (B1 81,38)
- 2025 vispera_festivo (n=867): 21,31 → 20,18 (B1 33,40)
- 2025 post_festivo (n=867): 16,20 → 15,46 (B1 27,01)

Notas: la lluvia (clima_diario) es observada y diaria; aquí solo es condición de análisis. Las condiciones con menos de 100 filas tienen intervalos amplios.
