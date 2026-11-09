# Calibración conformal condicional de la banda P10-P90 (hgb_fv1_20250831_s42)

Generado 2026-11-09T05:10:42-05:00 con `scripts/calibrar_por_grupo.py` (5,5 s). Validación (ventana de calibración): 2025-09-01 a 2025-10-31. Prueba reservada: 2025-11-01 a 2025-12-31 (solo se reporta; no se usa para ajustar ni para elegir).

Variantes: **modelo** = cuantiles P10/P90 del modelo sin calibrar; **v1** = calibración anterior, que queda como respaldo con CALIBRACION_BANDA=v1 (conformal móvil por ruta, 56 días previos, la misma función de la API); **mondrian_*** = un cuantil conformal por grupo, evaluado con validación cruzada por semanas ISO dentro de la validación. Ancho medio = P90 - P10 en pasajeros por hora.

Criterio: Se adopta una candidata solo si, en la validación cruzada por semanas, baja la peor desviación |cobertura - 80 %| de los grupos por hora, ruta y tipo de día frente a v1 y su ancho medio (pasajeros) no supera al de v1. La prueba reservada solo se reporta.

## Decisión

| Candidata | Grupos | Peor desviación (pp) | Cobertura global | Ancho medio | Baja la peor desviación | No ensancha | Cumple |
|---|---|---|---|---|---|---|---|
| mondrian_bloque | bloque | 5,25 | 79,8 % | 322 | sí | sí | sí |
| mondrian_ruta_bloque | ruta×bloque | 4,70 | 80,3 % | 326 | sí | sí | sí |
| mondrian_ruta_hora | ruta×hora | 7,87 | 81,0 % | 338 | sí | no | no |
| mondrian_tipo_bloque | tipo×bloque | 4,70 | 79,6 % | 327 | sí | no | no |

Referencia v1 en validación: peor desviación 10,60 pp, cobertura 80,1 %, ancho medio 327 (ajuste aplicado en el 77,0 % de las horas: los primeros 14 días no tienen historia fuera de muestra).

**Adoptada: mondrian_ruta_bloque** (conformal de Mondrian por ruta × bloque), ajustada con validación 2025-09-01 a 2025-10-31 (3111 horas); la prueba reservada no se usa. Para versionarla: `python scripts/calibrar_por_grupo.py --escribir`.

## Lectura

- En la validación, la calibración anterior (v1) deja la hora 4 en 69,4 % (inicio del servicio) y sobrecubre la mañana (7 h: 82,5 %, 8 h: 85,2 %): la cobertura global de 80 % esconde errores de hasta 10,60 pp por hora.
- La calibración por ruta × bloque baja esa peor desviación a 4,70 pp en la validación cruzada, con un intervalo medio de 326 pasajeros frente a 327.
- En la prueba reservada (solo reporte) la cobertura global queda igual (v1 78,59 %, v2 79,78 %) con un intervalo medio más angosto (316,3 → 315,1 pasajeros) y la hora 4 pasa de 65,6 % a 84,2 %. La peor desviación no mejora (15,52 → 11,15 pp): las horas finales quedan bajo el 80 % con cualquier banda (20 h: modelo 71,6 %, v1 64,5 %, v2 68,8 %) y los días especiales de noviembre y diciembre también (v1 73,7 %, v2 75,2 %). Es un cambio de temporada que una calibración ajustada con septiembre y octubre no puede anticipar; el monitoreo de §9.4 mide la cobertura móvil y la política de reentrenamiento la usa como disparador.
- Las 6 h en CRA 54: la banda horaria es angosta (P90 / P50 mediana 1,16 en la validación y 1,16 en la prueba; máximo 1,66 el 2025-12-25). La variación real entre días sí es grande (1988 ± 624 pasajeros), pero el modelo la explica con el tipo de día, el calendario y los rezagos. Una razón de 2,9 no aparece a las 6 h en ninguna ruta: solo en 28 (validación) y 50 (prueba) horas de borde ([4, 5, 20]) con P50 mediano de 15 pasajeros, donde el ajuste se escala con max(P50, 1). No es un artefacto de la calibración ni justifica ensanchar la banda de los picos.

## Validación: por hora

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| 4 | 72,7 % / 179 | 69,4 % / 174 | 84,2 % / 191 | 83,1 % / 195 | 72,1 % / 176 | 75,4 % / 198 |
| 5 | 73,8 % / 469 | 72,1 % / 445 | 78,7 % / 521 | 80,9 % / 536 | 75,4 % / 498 | 80,3 % / 550 |
| 6 | 82,0 % / 377 | 80,3 % / 362 | 76,0 % / 325 | 75,4 % / 336 | 83,6 % / 414 | 77,0 % / 333 |
| 7 | 84,7 % / 320 | 82,5 % / 308 | 77,0 % / 279 | 79,2 % / 287 | 82,5 % / 310 | 79,8 % / 285 |
| 8 | 85,8 % / 315 | 85,2 % / 304 | 79,8 % / 277 | 80,9 % / 283 | 86,3 % / 330 | 80,3 % / 282 |
| 9 | 85,8 % / 308 | 83,1 % / 296 | 80,9 % / 289 | 80,9 % / 290 | 83,1 % / 294 | 80,3 % / 290 |
| 10 | 81,4 % / 329 | 80,3 % / 318 | 79,2 % / 312 | 79,2 % / 312 | 80,9 % / 329 | 78,7 % / 313 |
| 11 | 80,3 % / 325 | 78,1 % / 315 | 77,6 % / 308 | 78,1 % / 308 | 79,8 % / 322 | 77,6 % / 309 |
| 12 | 87,4 % / 384 | 85,8 % / 372 | 85,2 % / 364 | 84,7 % / 365 | 82,0 % / 351 | 84,2 % / 366 |
| 13 | 86,3 % / 438 | 85,2 % / 425 | 84,7 % / 417 | 84,2 % / 417 | 86,3 % / 430 | 84,7 % / 418 |
| 14 | 81,4 % / 464 | 79,8 % / 451 | 78,7 % / 442 | 79,2 % / 443 | 83,1 % / 491 | 79,8 % / 444 |
| 15 | 78,7 % / 439 | 77,0 % / 428 | 77,6 % / 421 | 77,6 % / 421 | 80,9 % / 450 | 77,6 % / 422 |
| 16 | 80,9 % / 406 | 79,2 % / 395 | 78,7 % / 389 | 78,7 % / 389 | 78,1 % / 384 | 78,7 % / 390 |
| 17 | 82,0 % / 324 | 80,9 % / 316 | 79,8 % / 307 | 81,4 % / 312 | 81,4 % / 329 | 79,8 % / 317 |
| 18 | 82,0 % / 280 | 82,0 % / 273 | 79,8 % / 267 | 80,3 % / 270 | 82,0 % / 280 | 80,3 % / 275 |
| 19 | 82,5 % / 226 | 81,4 % / 221 | 80,3 % / 215 | 80,9 % / 219 | 79,8 % / 211 | 82,0 % / 222 |
| 20 | 79,2 % / 152 | 78,7 % / 150 | 78,7 % / 152 | 80,3 % / 155 | 80,3 % / 155 | 77,0 % / 146 |
| **Global** | 81,6 % / 337 | 80,1 % / 327 | 79,8 % / 322 | 80,3 % / 326 | 81,0 % / 338 | 79,6 % / 327 |
| Peor desviación de la partición | 7,43 pp | 10,60 pp | 5,25 pp | 4,70 pp | 7,87 pp | 4,70 pp |

## Validación: por ruta

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| CL 72 | 81,1 % / 239 | 80,3 % / 234 | 79,8 % / 231 | 79,6 % / 230 | 81,1 % / 239 | 79,1 % / 234 |
| CRA 54 | 81,2 % / 461 | 79,9 % / 451 | 78,5 % / 434 | 80,7 % / 451 | 80,5 % / 464 | 78,5 % / 442 |
| SILENCIO | 82,5 % / 312 | 79,9 % / 295 | 81,1 % / 301 | 80,6 % / 296 | 81,5 % / 312 | 81,3 % / 306 |
| **Global** | 81,6 % / 337 | 80,1 % / 327 | 79,8 % / 322 | 80,3 % / 326 | 81,0 % / 338 | 79,6 % / 327 |
| Peor desviación de la partición | 2,45 pp | 0,33 pp | 1,50 pp | 0,71 pp | 1,49 pp | 1,50 pp |

## Validación: por tipo de día

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| Domingo/festivo | 78,4 % / 208 | 76,7 % / 203 | 80,4 % / 200 | 79,5 % / 201 | 79,1 % / 208 | 78,0 % / 210 |
| Laboral | 81,8 % / 371 | 80,2 % / 359 | 79,6 % / 354 | 80,5 % / 358 | 81,3 % / 372 | 80,2 % / 360 |
| Sábado | 84,1 % / 300 | 83,3 % / 290 | 80,2 % / 284 | 79,9 % / 287 | 81,9 % / 300 | 78,4 % / 277 |
| **Global** | 81,6 % / 337 | 80,1 % / 327 | 79,8 % / 322 | 80,3 % / 326 | 81,0 % / 338 | 79,6 % / 327 |
| Peor desviación de la partición | 4,07 pp | 3,33 pp | 0,39 pp | 0,53 pp | 1,86 pp | 2,00 pp |

## Validación: por calendario especial

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| especial | 86,3 % / 231 | 80,4 % / 227 | 84,3 % / 226 | 84,3 % / 227 | 80,4 % / 230 | 80,4 % / 239 |
| normal | 81,5 % / 339 | 80,1 % / 328 | 79,7 % / 324 | 80,2 % / 328 | 81,0 % / 340 | 79,6 % / 329 |
| **Global** | 81,6 % / 337 | 80,1 % / 327 | 79,8 % / 322 | 80,3 % / 326 | 81,0 % / 338 | 79,6 % / 327 |

## Prueba reservada (solo reporte): por hora

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| 4 | 71,6 % / 147 | 65,6 % / 143 | 84,2 % / 156 |
| 5 | 83,6 % / 458 | 81,4 % / 440 | 86,9 % / 503 |
| 6 | 78,7 % / 404 | 77,0 % / 392 | 76,5 % / 378 |
| 7 | 90,7 % / 330 | 88,5 % / 320 | 86,9 % / 309 |
| 8 | 85,8 % / 317 | 82,5 % / 308 | 81,4 % / 298 |
| 9 | 82,0 % / 304 | 81,4 % / 295 | 80,3 % / 288 |
| 10 | 84,7 % / 308 | 82,0 % / 300 | 82,0 % / 293 |
| 11 | 81,4 % / 311 | 79,8 % / 303 | 78,1 % / 296 |
| 12 | 80,3 % / 365 | 78,1 % / 355 | 76,5 % / 348 |
| 13 | 82,0 % / 408 | 80,9 % / 398 | 81,4 % / 390 |
| 14 | 81,4 % / 452 | 80,9 % / 441 | 80,9 % / 433 |
| 15 | 83,1 % / 419 | 80,3 % / 409 | 80,3 % / 402 |
| 16 | 82,0 % / 360 | 80,9 % / 351 | 79,8 % / 344 |
| 17 | 85,8 % / 298 | 84,7 % / 291 | 84,2 % / 289 |
| 18 | 76,0 % / 255 | 73,2 % / 250 | 74,3 % / 248 |
| 19 | 75,4 % / 227 | 74,3 % / 222 | 73,8 % / 221 |
| 20 | 71,6 % / 164 | 64,5 % / 162 | 68,8 % / 161 |
| **Global** | 80,9 % / 325 | 78,6 % / 316 | 79,8 % / 315 |
| Peor desviación de la partición | 10,71 pp | 15,52 pp | 11,15 pp |

## Prueba reservada (solo reporte): por ruta

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| CL 72 | 81,6 % / 233 | 78,7 % / 226 | 81,0 % / 224 |
| CRA 54 | 78,1 % / 455 | 77,5 % / 453 | 77,6 % / 450 |
| SILENCIO | 83,1 % / 287 | 79,6 % / 269 | 80,7 % / 271 |
| **Global** | 80,9 % / 325 | 78,6 % / 316 | 79,8 % / 315 |
| Peor desviación de la partición | 3,12 pp | 2,47 pp | 2,37 pp |

## Prueba reservada (solo reporte): por tipo de día

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| Domingo/festivo | 81,3 % / 233 | 77,8 % / 228 | 82,8 % / 226 |
| Laboral | 80,6 % / 361 | 78,9 % / 351 | 78,8 % / 350 |
| Sábado | 81,7 % / 301 | 78,4 % / 292 | 79,5 % / 290 |
| **Global** | 80,9 % / 325 | 78,6 % / 316 | 79,8 % / 315 |
| Peor desviación de la partición | 1,70 pp | 2,17 pp | 2,81 pp |

## Prueba reservada (solo reporte): por calendario especial

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| especial | 76,9 % / 327 | 73,7 % / 320 | 75,2 % / 318 |
| normal | 82,8 % / 324 | 80,8 % / 314 | 81,8 % / 314 |
| **Global** | 80,9 % / 325 | 78,6 % / 316 | 79,8 % / 315 |

## El caso de las 6 h

**Validación** (banda v1, razón P90 / P50 de la hora):

| Ruta | Mediana a las 6 h | P95 | Máximo | Fecha del máximo | P50 / P90 / real en el máximo | Media y desviación observadas a las 6 h |
|---|---|---|---|---|---|---|
| CL 72 | 1,23 | 1,30 | 1,57 | 2025-10-13 | 186 / 291 / 177 | 484 ± 156 |
| CRA 54 | 1,16 | 1,21 | 1,23 | 2025-10-13 | 618 / 756 / 683 | 1988 ± 624 |
| SILENCIO | 1,21 | 1,30 | 1,39 | 2025-10-13 | 305 / 422 / 377 | 775 ± 203 |

Horas con P90 / P50 ≥ 2,9: 28 de 3111 (horas [4, 20]; P50 mediano 16,4 pasajeros; 21,4 % en días especiales).

**Prueba reservada** (banda v1, razón P90 / P50 de la hora):

| Ruta | Mediana a las 6 h | P95 | Máximo | Fecha del máximo | P50 / P90 / real en el máximo | Media y desviación observadas a las 6 h |
|---|---|---|---|---|---|---|
| CL 72 | 1,24 | 1,60 | 1,71 | 2025-12-08 | 161 / 274 / 155 | 493 ± 188 |
| CRA 54 | 1,16 | 1,25 | 1,66 | 2025-12-25 | 402 / 668 / 303 | 1788 ± 682 |
| SILENCIO | 1,16 | 1,28 | 2,31 | 2025-12-25 | 201 / 466 / 188 | 826 ± 275 |

Horas con P90 / P50 ≥ 2,9: 50 de 3111 (horas [4, 5, 20]; P50 mediano 14,8 pasajeros; 60,0 % en días especiales).

