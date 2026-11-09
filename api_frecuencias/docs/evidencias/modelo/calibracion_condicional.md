# Calibración conformal condicional de la banda P10-P90 (hgb_fv2_20250831_s42)

Generado 2026-11-09T03:44:19-05:00 con `scripts/calibrar_por_grupo.py` (2,2 s). Validación (ventana de calibración): 2025-09-01 a 2025-10-31. Prueba reservada: 2025-11-01 a 2025-12-31 (solo se reporta; no se usa para ajustar ni para elegir).

Variantes: **modelo** = cuantiles P10/P90 del modelo sin calibrar; **v1** = calibración anterior, que queda como respaldo con CALIBRACION_BANDA=v1 (conformal móvil por ruta, 56 días previos, la misma función de la API); **mondrian_*** = un cuantil conformal por grupo, evaluado con validación cruzada por semanas ISO dentro de la validación. Ancho medio = P90 - P10 en pasajeros por hora.

Criterio: Se adopta una candidata solo si, en la validación cruzada por semanas, baja la peor desviación |cobertura - 80 %| de los grupos por hora, ruta y tipo de día frente a v1 y su ancho medio (pasajeros) no supera al de v1. La prueba reservada solo se reporta.

## Decisión

| Candidata | Grupos | Peor desviación (pp) | Cobertura global | Ancho medio | Baja la peor desviación | No ensancha | Cumple |
|---|---|---|---|---|---|---|---|
| mondrian_bloque | bloque | 4,15 | 79,8 % | 319 | sí | sí | sí |
| mondrian_ruta_bloque | ruta×bloque | 4,70 | 80,2 % | 322 | sí | sí | sí |
| mondrian_ruta_hora | ruta×hora | 8,42 | 81,1 % | 333 | sí | no | no |
| mondrian_tipo_bloque | tipo×bloque | 4,70 | 79,2 % | 322 | sí | sí | sí |

Referencia v1 en validación: peor desviación 10,60 pp, cobertura 80,0 %, ancho medio 322 (ajuste aplicado en el 77,0 % de las horas: los primeros 14 días no tienen historia fuera de muestra).

**Adoptada: mondrian_bloque** (conformal de Mondrian por bloque), ajustada con validación 2025-09-01 a 2025-10-31 (3111 horas); la prueba reservada no se usa. Archivo versionado: `datos/modelos/hgb_fv2_20250831_s42/calibracion_v2.json` (SHA-256 `dae6b1a616ee0d89…`, registrado en manifest.json, clave «calibracion»).

## Lectura

- En la validación, la calibración anterior (v1) deja la hora 4 en 69,4 % (inicio del servicio) y sobrecubre la mañana (7 h: 82,5 %, 8 h: 85,2 %): la cobertura global de 80 % esconde errores de hasta 10,60 pp por hora.
- La calibración por bloque baja esa peor desviación a 4,15 pp en la validación cruzada, con un intervalo medio de 319 pasajeros frente a 322.
- En la prueba reservada (solo reporte) la cobertura global queda igual (v1 77,88 %, v2 77,82 %) con un intervalo medio más angosto (312,9 → 303,4 pasajeros) y la hora 4 pasa de 66,7 % a 84,2 %. La peor desviación no mejora (13,33 → 14,97 pp): las horas finales quedan bajo el 80 % con cualquier banda (20 h: modelo 68,8 %, v1 66,7 %, v2 65,0 %) y los días especiales de noviembre y diciembre también (v1 73,3 %, v2 73,0 %). Es un cambio de temporada que una calibración ajustada con septiembre y octubre no puede anticipar; el monitoreo de §9.4 mide la cobertura móvil y la política de reentrenamiento la usa como disparador.
- Las 6 h en CRA 54: la banda horaria es angosta (P90 / P50 mediana 1,16 en la validación y 1,15 en la prueba; máximo 1,61 el 2025-12-25). La variación real entre días sí es grande (1988 ± 624 pasajeros), pero el modelo la explica con el tipo de día, el calendario y los rezagos. Una razón de 2,9 no aparece a las 6 h en ninguna ruta: solo en 23 (validación) y 49 (prueba) horas de borde ([4, 5, 20]) con P50 mediano de 14 pasajeros, donde el ajuste se escala con max(P50, 1). No es un artefacto de la calibración ni justifica ensanchar la banda de los picos.

## Validación: por hora

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| 4 | 72,7 % / 175 | 69,4 % / 169 | 84,2 % / 185 | 81,4 % / 187 | 71,6 % / 171 | 75,4 % / 188 |
| 5 | 75,4 % / 478 | 74,3 % / 450 | 78,1 % / 521 | 78,7 % / 526 | 76,5 % / 501 | 78,7 % / 534 |
| 6 | 83,6 % / 384 | 82,5 % / 367 | 77,6 % / 324 | 78,7 % / 334 | 85,8 % / 397 | 77,6 % / 330 |
| 7 | 85,2 % / 318 | 82,5 % / 304 | 76,5 % / 271 | 77,0 % / 278 | 84,7 % / 311 | 77,0 % / 276 |
| 8 | 86,3 % / 313 | 85,2 % / 299 | 79,2 % / 268 | 79,8 % / 274 | 85,8 % / 315 | 79,2 % / 272 |
| 9 | 85,8 % / 308 | 83,6 % / 295 | 84,2 % / 291 | 84,2 % / 292 | 82,5 % / 292 | 84,7 % / 292 |
| 10 | 82,5 % / 329 | 78,7 % / 317 | 78,7 % / 313 | 79,2 % / 314 | 82,5 % / 336 | 79,2 % / 314 |
| 11 | 78,1 % / 321 | 76,0 % / 310 | 76,5 % / 306 | 76,5 % / 306 | 78,7 % / 319 | 76,5 % / 307 |
| 12 | 87,4 % / 382 | 85,2 % / 369 | 84,2 % / 364 | 84,7 % / 365 | 84,2 % / 354 | 83,6 % / 366 |
| 13 | 84,7 % / 431 | 82,5 % / 416 | 82,0 % / 411 | 83,1 % / 412 | 84,2 % / 416 | 82,0 % / 414 |
| 14 | 82,0 % / 457 | 81,4 % / 442 | 79,2 % / 437 | 79,2 % / 438 | 83,6 % / 483 | 80,3 % / 439 |
| 15 | 78,1 % / 429 | 78,1 % / 416 | 76,5 % / 411 | 77,0 % / 412 | 79,8 % / 434 | 77,0 % / 413 |
| 16 | 79,8 % / 393 | 78,1 % / 380 | 77,0 % / 376 | 78,1 % / 377 | 76,0 % / 374 | 77,0 % / 378 |
| 17 | 83,1 % / 319 | 81,4 % / 310 | 83,1 % / 311 | 82,0 % / 313 | 82,5 % / 319 | 79,8 % / 316 |
| 18 | 80,9 % / 271 | 79,8 % / 264 | 79,2 % / 265 | 79,8 % / 266 | 80,9 % / 276 | 79,8 % / 269 |
| 19 | 82,0 % / 220 | 81,4 % / 214 | 81,4 % / 215 | 82,0 % / 216 | 78,7 % / 202 | 81,4 % / 218 |
| 20 | 82,0 % / 153 | 80,3 % / 150 | 79,8 % / 150 | 81,4 % / 156 | 81,4 % / 156 | 77,0 % / 146 |
| **Global** | 81,7 % / 334 | 80,0 % / 322 | 79,8 % / 319 | 80,2 % / 322 | 81,1 % / 333 | 79,2 % / 322 |
| Peor desviación de la partición | 7,43 pp | 10,60 pp | 4,15 pp | 4,70 pp | 8,42 pp | 4,70 pp |

## Validación: por ruta

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| CL 72 | 81,0 % / 238 | 80,2 % / 233 | 79,8 % / 230 | 79,8 % / 229 | 81,5 % / 241 | 78,9 % / 232 |
| CRA 54 | 82,0 % / 453 | 80,4 % / 439 | 79,2 % / 426 | 81,0 % / 443 | 80,3 % / 450 | 78,3 % / 431 |
| SILENCIO | 82,3 % / 311 | 79,5 % / 294 | 80,5 % / 300 | 79,8 % / 292 | 81,6 % / 307 | 80,4 % / 303 |
| **Global** | 81,7 % / 334 | 80,0 % / 322 | 79,8 % / 319 | 80,2 % / 322 | 81,1 % / 333 | 79,2 % / 322 |
| Peor desviación de la partición | 2,26 pp | 0,54 pp | 0,83 pp | 1,00 pp | 1,58 pp | 1,70 pp |

## Validación: por tipo de día

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| Domingo/festivo | 80,4 % / 213 | 79,3 % / 207 | 81,7 % / 205 | 81,7 % / 205 | 80,6 % / 212 | 77,8 % / 207 |
| Laboral | 81,7 % / 366 | 79,9 % / 352 | 79,6 % / 349 | 80,0 % / 352 | 81,2 % / 364 | 80,0 % / 355 |
| Sábado | 83,3 % / 296 | 81,9 % / 285 | 78,9 % / 279 | 79,2 % / 282 | 81,1 % / 294 | 76,5 % / 271 |
| **Global** | 81,7 % / 334 | 80,0 % / 322 | 79,8 % / 319 | 80,2 % / 322 | 81,1 % / 333 | 79,2 % / 322 |
| Peor desviación de la partición | 3,33 pp | 1,86 pp | 1,70 pp | 1,70 pp | 1,24 pp | 3,53 pp |

## Validación: por calendario especial

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| especial | 88,2 % / 243 | 84,3 % / 238 | 86,3 % / 238 | 86,3 % / 239 | 84,3 % / 240 | 82,3 % / 243 |
| normal | 81,6 % / 336 | 80,0 % / 323 | 79,7 % / 320 | 80,1 % / 323 | 81,1 % / 334 | 79,2 % / 323 |
| **Global** | 81,7 % / 334 | 80,0 % / 322 | 79,8 % / 319 | 80,2 % / 322 | 81,1 % / 333 | 79,2 % / 322 |

## Prueba reservada (solo reporte): por hora

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| 4 | 72,1 % / 143 | 66,7 % / 140 | 84,2 % / 148 |
| 5 | 83,6 % / 485 | 81,4 % / 472 | 85,2 % / 511 |
| 6 | 77,6 % / 400 | 76,0 % / 392 | 74,9 % / 353 |
| 7 | 90,7 % / 312 | 89,6 % / 306 | 84,7 % / 275 |
| 8 | 84,2 % / 307 | 82,0 % / 301 | 76,5 % / 272 |
| 9 | 78,7 % / 294 | 77,6 % / 288 | 75,4 % / 277 |
| 10 | 82,0 % / 300 | 82,0 % / 294 | 78,7 % / 285 |
| 11 | 78,1 % / 301 | 77,6 % / 296 | 77,0 % / 286 |
| 12 | 79,2 % / 361 | 78,1 % / 354 | 77,6 % / 342 |
| 13 | 81,4 % / 398 | 80,3 % / 391 | 80,3 % / 378 |
| 14 | 79,8 % / 438 | 78,7 % / 430 | 78,1 % / 417 |
| 15 | 80,9 % / 409 | 80,3 % / 402 | 79,8 % / 391 |
| 16 | 82,5 % / 355 | 80,3 % / 349 | 79,8 % / 339 |
| 17 | 82,0 % / 292 | 81,4 % / 288 | 81,4 % / 280 |
| 18 | 75,4 % / 245 | 73,8 % / 241 | 73,8 % / 236 |
| 19 | 74,3 % / 223 | 71,6 % / 220 | 70,5 % / 214 |
| 20 | 68,8 % / 159 | 66,7 % / 157 | 65,0 % / 155 |
| **Global** | 79,5 % / 319 | 77,9 % / 313 | 77,8 % / 303 |
| Peor desviación de la partición | 11,15 pp | 13,33 pp | 14,97 pp |

## Prueba reservada (solo reporte): por ruta

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| CL 72 | 79,8 % / 226 | 78,1 % / 222 | 78,4 % / 218 |
| CRA 54 | 76,5 % / 443 | 76,2 % / 445 | 73,7 % / 416 |
| SILENCIO | 82,3 % / 288 | 79,4 % / 272 | 81,4 % / 276 |
| **Global** | 79,5 % / 319 | 77,9 % / 313 | 77,8 % / 303 |
| Peor desviación de la partición | 3,53 pp | 3,82 pp | 6,33 pp |

## Prueba reservada (solo reporte): por tipo de día

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| Domingo/festivo | 79,5 % / 228 | 77,7 % / 225 | 79,5 % / 219 |
| Laboral | 79,4 % / 355 | 77,9 % / 348 | 77,4 % / 338 |
| Sábado | 80,0 % / 293 | 78,2 % / 287 | 77,3 % / 277 |
| **Global** | 79,5 % / 319 | 77,9 % / 313 | 77,8 % / 303 |
| Peor desviación de la partición | 0,61 pp | 2,32 pp | 2,66 pp |

## Prueba reservada (solo reporte): por calendario especial

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| especial | 75,8 % / 317 | 73,3 % / 315 | 73,0 % / 304 |
| normal | 81,1 % / 320 | 80,0 % / 312 | 80,0 % / 303 |
| **Global** | 79,5 % / 319 | 77,9 % / 313 | 77,8 % / 303 |

## El caso de las 6 h

**Validación** (banda v1, razón P90 / P50 de la hora):

| Ruta | Mediana a las 6 h | P95 | Máximo | Fecha del máximo | P50 / P90 / real en el máximo | Media y desviación observadas a las 6 h |
|---|---|---|---|---|---|---|
| CL 72 | 1,23 | 1,31 | 1,40 | 2025-10-13 | 185 / 259 / 177 | 484 ± 156 |
| CRA 54 | 1,16 | 1,21 | 1,26 | 2025-10-13 | 632 / 794 / 683 | 1988 ± 624 |
| SILENCIO | 1,22 | 1,26 | 1,47 | 2025-10-13 | 316 / 463 / 377 | 775 ± 203 |

Horas con P90 / P50 ≥ 2,9: 23 de 3111 (horas [4, 20]; P50 mediano 14,3 pasajeros; 26,1 % en días especiales).

**Prueba reservada** (banda v1, razón P90 / P50 de la hora):

| Ruta | Mediana a las 6 h | P95 | Máximo | Fecha del máximo | P50 / P90 / real en el máximo | Media y desviación observadas a las 6 h |
|---|---|---|---|---|---|---|
| CL 72 | 1,23 | 1,38 | 1,76 | 2025-12-08 | 174 / 306 / 155 | 493 ± 188 |
| CRA 54 | 1,15 | 1,26 | 1,61 | 2025-12-25 | 411 / 664 / 303 | 1788 ± 682 |
| SILENCIO | 1,17 | 1,29 | 2,58 | 2025-12-25 | 240 / 619 / 188 | 826 ± 275 |

Horas con P90 / P50 ≥ 2,9: 49 de 3111 (horas [4, 5, 20]; P50 mediano 13,7 pasajeros; 61,2 % en días especiales).

