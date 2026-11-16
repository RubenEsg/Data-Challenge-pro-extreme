# Calibración conformal condicional de la banda P10-P90 (hgb_fv3_20250831_s42)

Generado 2026-11-16T15:13:28-05:00 con `scripts/calibrar_por_grupo.py` (1,4 s). Validación (ventana de calibración): 2025-09-01 a 2025-10-31. Prueba reservada: 2025-11-01 a 2025-12-31 (solo se reporta; no se usa para ajustar ni para elegir).

Variantes: **modelo** = cuantiles P10/P90 del modelo sin calibrar; **v1** = calibración anterior, que queda como respaldo con CALIBRACION_BANDA=v1 (conformal móvil por ruta, 56 días previos, la misma función de la API); **mondrian_*** = un cuantil conformal por grupo, evaluado con validación cruzada por semanas ISO dentro de la validación. Ancho medio = P90 - P10 en pasajeros por hora.

Criterio: Se adopta una candidata solo si, en la validación cruzada por semanas, baja la peor desviación |cobertura - 80 %| de los grupos por hora, ruta y tipo de día frente a v1 y su ancho medio (pasajeros) no supera al de v1. La prueba reservada solo se reporta.

## Decisión

| Candidata | Grupos | Peor desviación (pp) | Cobertura global | Ancho medio | Baja la peor desviación | No ensancha | Cumple |
|---|---|---|---|---|---|---|---|
| mondrian_bloque | bloque | 6,89 | 79,7 % | 302 | sí | sí | sí |
| mondrian_ruta_bloque | ruta×bloque | 6,34 | 79,7 % | 306 | sí | sí | sí |
| mondrian_ruta_hora | ruta×hora | 8,42 | 80,5 % | 318 | sí | no | no |
| mondrian_tipo_bloque | tipo×bloque | 6,89 | 79,0 % | 303 | sí | sí | sí |

Referencia v1 en validación: peor desviación 10,05 pp, cobertura 80,5 %, ancho medio 311 (ajuste aplicado en el 77,0 % de las horas: los primeros 14 días no tienen historia fuera de muestra).

**Adoptada: mondrian_ruta_bloque** (conformal de Mondrian por ruta × bloque), ajustada con validación 2025-09-01 a 2025-10-31 (3111 horas); la prueba reservada no se usa. Archivo versionado: `datos/modelos/hgb_fv3_20250831_s42/calibracion_v2.json` (SHA-256 `d3092d2846d4fc44…`, registrado en manifest.json, clave «calibracion»).

## Lectura

- En la validación, la calibración anterior (v1) deja la hora 4 en 70,0 % (inicio del servicio) y sobrecubre la mañana (7 h: 82,5 %, 8 h: 84,7 %): la cobertura global de 80 % esconde errores de hasta 10,05 pp por hora.
- La calibración por ruta × bloque baja esa peor desviación a 6,34 pp en la validación cruzada, con un intervalo medio de 306 pasajeros frente a 311.
- En la prueba reservada (solo reporte) la cobertura global queda igual (v1 78,27 %, v2 77,95 %) con un intervalo medio más angosto (303,6 → 297,6 pasajeros) y la hora 4 pasa de 68,3 % a 79,8 %. La peor desviación no mejora (14,43 → 10,05 pp): las horas finales quedan bajo el 80 % con cualquier banda (20 h: modelo 70,0 %, v1 65,6 %, v2 70,0 %) y los días especiales de noviembre y diciembre también (v1 74,3 %, v2 74,2 %). Es un cambio de temporada que una calibración ajustada con septiembre y octubre no puede anticipar; el monitoreo de §9.4 mide la cobertura móvil y la política de reentrenamiento la usa como disparador.
- Las 6 h en CRA 54: la banda horaria es angosta (P90 / P50 mediana 1,16 en la validación y 1,16 en la prueba; máximo 1,76 el 2025-12-25). La variación real entre días sí es grande (1988 ± 624 pasajeros), pero el modelo la explica con el tipo de día, el calendario y los rezagos. Una razón de 2,9 no aparece a las 6 h en ninguna ruta: solo en 25 (validación) y 49 (prueba) horas de borde ([4, 5, 20]) con P50 mediano de 22 pasajeros, donde el ajuste se escala con max(P50, 1). No es un artefacto de la calibración ni justifica ensanchar la banda de los picos.

## Validación: por hora

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| 4 | 71,6 % / 174 | 70,0 % / 167 | 80,9 % / 178 | 79,2 % / 182 | 71,6 % / 173 | 75,4 % / 179 |
| 5 | 78,7 % / 429 | 76,5 % / 401 | 79,8 % / 449 | 82,0 % / 466 | 78,7 % / 429 | 79,2 % / 453 |
| 6 | 84,2 % / 371 | 81,4 % / 353 | 77,0 % / 317 | 74,9 % / 316 | 82,0 % / 378 | 75,4 % / 322 |
| 7 | 84,7 % / 315 | 82,5 % / 301 | 79,2 % / 273 | 79,8 % / 271 | 84,7 % / 300 | 79,8 % / 277 |
| 8 | 85,8 % / 300 | 84,7 % / 286 | 81,4 % / 260 | 79,2 % / 258 | 83,6 % / 298 | 80,9 % / 263 |
| 9 | 84,7 % / 293 | 82,0 % / 280 | 79,8 % / 267 | 80,9 % / 272 | 82,0 % / 282 | 79,8 % / 267 |
| 10 | 83,1 % / 311 | 81,4 % / 299 | 79,8 % / 287 | 80,3 % / 292 | 81,4 % / 313 | 79,2 % / 287 |
| 11 | 78,1 % / 310 | 77,6 % / 298 | 76,5 % / 287 | 75,4 % / 291 | 78,1 % / 305 | 76,5 % / 286 |
| 12 | 89,1 % / 367 | 87,4 % / 353 | 86,9 % / 340 | 86,3 % / 345 | 84,7 % / 328 | 86,9 % / 339 |
| 13 | 85,8 % / 424 | 84,7 % / 408 | 83,1 % / 394 | 83,6 % / 400 | 84,7 % / 405 | 83,1 % / 393 |
| 14 | 80,3 % / 446 | 79,8 % / 430 | 77,6 % / 416 | 77,6 % / 422 | 82,0 % / 469 | 77,6 % / 415 |
| 15 | 77,6 % / 421 | 76,5 % / 407 | 75,4 % / 394 | 76,0 % / 399 | 79,2 % / 428 | 75,4 % / 394 |
| 16 | 80,9 % / 386 | 80,9 % / 373 | 78,7 % / 362 | 80,3 % / 366 | 78,7 % / 366 | 78,7 % / 361 |
| 17 | 83,1 % / 318 | 82,5 % / 308 | 81,4 % / 299 | 80,9 % / 301 | 80,9 % / 311 | 77,6 % / 300 |
| 18 | 80,9 % / 272 | 80,3 % / 265 | 78,1 % / 258 | 78,7 % / 260 | 81,4 % / 272 | 80,3 % / 259 |
| 19 | 83,1 % / 223 | 82,5 % / 217 | 82,0 % / 211 | 80,3 % / 213 | 76,0 % / 195 | 82,0 % / 212 |
| 20 | 79,2 % / 148 | 77,0 % / 144 | 77,6 % / 144 | 78,7 % / 150 | 78,7 % / 150 | 75,4 % / 142 |
| **Global** | 81,8 % / 324 | 80,5 % / 311 | 79,7 % / 302 | 79,7 % / 306 | 80,5 % / 318 | 79,0 % / 303 |
| Peor desviación de la partición | 9,07 pp | 10,05 pp | 6,89 pp | 6,34 pp | 8,42 pp | 6,89 pp |

## Validación: por ruta

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| CL 72 | 81,4 % / 234 | 80,7 % / 229 | 79,7 % / 223 | 79,3 % / 219 | 80,4 % / 228 | 78,3 % / 223 |
| CRA 54 | 81,4 % / 436 | 80,1 % / 423 | 78,4 % / 399 | 80,3 % / 423 | 79,7 % / 430 | 77,9 % / 400 |
| SILENCIO | 82,6 % / 302 | 80,5 % / 282 | 81,1 % / 285 | 79,4 % / 276 | 81,4 % / 295 | 80,8 % / 286 |
| **Global** | 81,8 % / 324 | 80,5 % / 311 | 79,7 % / 302 | 79,7 % / 306 | 80,5 % / 318 | 79,0 % / 303 |
| Peor desviación de la partición | 2,64 pp | 0,71 pp | 1,60 pp | 0,73 pp | 1,39 pp | 2,08 pp |

## Validación: por tipo de día

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| Domingo/festivo | 78,4 % / 210 | 77,1 % / 204 | 81,0 % / 199 | 79,5 % / 200 | 79,1 % / 207 | 78,2 % / 207 |
| Laboral | 82,3 % / 354 | 80,9 % / 339 | 79,7 % / 330 | 79,8 % / 334 | 80,9 % / 347 | 79,5 % / 329 |
| Sábado | 83,1 % / 288 | 81,6 % / 276 | 78,4 % / 267 | 79,2 % / 270 | 79,9 % / 283 | 77,2 % / 266 |
| **Global** | 81,8 % / 324 | 80,5 % / 311 | 79,7 % / 302 | 79,7 % / 306 | 80,5 % / 318 | 79,0 % / 303 |
| Peor desviación de la partición | 3,09 pp | 2,88 pp | 1,57 pp | 0,83 pp | 0,92 pp | 2,79 pp |

## Validación: por calendario especial

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | mondrian_bloque: cobertura / ancho medio | mondrian_ruta_bloque: cobertura / ancho medio | mondrian_ruta_hora: cobertura / ancho medio | mondrian_tipo_bloque: cobertura / ancho medio |
|---|---|---|---|---|---|---|
| especial | 84,3 % / 252 | 76,5 % / 243 | 80,4 % / 241 | 80,4 % / 241 | 76,5 % / 242 | 76,5 % / 252 |
| normal | 81,8 % / 325 | 80,5 % / 312 | 79,7 % / 303 | 79,6 % / 307 | 80,6 % / 319 | 79,0 % / 304 |
| **Global** | 81,8 % / 324 | 80,5 % / 311 | 79,7 % / 302 | 79,7 % / 306 | 80,5 % / 318 | 79,0 % / 303 |

## Prueba reservada (solo reporte): por hora

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| 4 | 73,2 % / 143 | 68,3 % / 139 | 79,8 % / 147 |
| 5 | 83,6 % / 427 | 82,0 % / 407 | 86,3 % / 445 |
| 6 | 79,2 % / 393 | 77,6 % / 380 | 76,0 % / 356 |
| 7 | 89,6 % / 316 | 88,0 % / 306 | 82,5 % / 287 |
| 8 | 82,5 % / 295 | 80,3 % / 285 | 75,4 % / 268 |
| 9 | 79,8 % / 286 | 77,0 % / 277 | 74,3 % / 268 |
| 10 | 82,5 % / 295 | 82,0 % / 286 | 80,9 % / 278 |
| 11 | 83,6 % / 297 | 80,9 % / 288 | 80,9 % / 280 |
| 12 | 79,2 % / 347 | 79,2 % / 337 | 76,5 % / 328 |
| 13 | 80,9 % / 395 | 79,8 % / 384 | 79,2 % / 374 |
| 14 | 80,9 % / 437 | 79,8 % / 425 | 79,2 % / 415 |
| 15 | 84,2 % / 406 | 82,0 % / 396 | 80,3 % / 386 |
| 16 | 82,0 % / 354 | 80,3 % / 345 | 80,3 % / 337 |
| 17 | 81,4 % / 292 | 80,9 % / 285 | 78,1 % / 277 |
| 18 | 74,9 % / 249 | 72,7 % / 244 | 72,1 % / 238 |
| 19 | 76,5 % / 225 | 74,3 % / 221 | 73,2 % / 216 |
| 20 | 70,0 % / 159 | 65,6 % / 156 | 70,0 % / 159 |
| **Global** | 80,2 % / 313 | 78,3 % / 304 | 78,0 % / 298 |
| Peor desviación de la partición | 10,05 pp | 14,43 pp | 10,05 pp |

## Prueba reservada (solo reporte): por ruta

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| CL 72 | 80,2 % / 225 | 78,7 % / 221 | 78,0 % / 212 |
| CRA 54 | 77,4 % / 432 | 77,3 % / 432 | 76,2 % / 421 |
| SILENCIO | 83,0 % / 282 | 78,8 % / 258 | 79,7 % / 260 |
| **Global** | 80,2 % / 313 | 78,3 % / 304 | 78,0 % / 298 |
| Peor desviación de la partición | 3,03 pp | 2,66 pp | 3,82 pp |

## Prueba reservada (solo reporte): por tipo de día

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| Domingo/festivo | 80,4 % / 233 | 78,1 % / 228 | 79,8 % / 224 |
| Laboral | 80,0 % / 344 | 78,2 % / 333 | 77,6 % / 327 |
| Sábado | 80,8 % / 293 | 78,9 % / 284 | 76,9 % / 277 |
| **Global** | 80,2 % / 313 | 78,3 % / 304 | 78,0 % / 298 |
| Peor desviación de la partición | 0,83 pp | 1,87 pp | 3,09 pp |

## Prueba reservada (solo reporte): por calendario especial

| Grupo | modelo: cobertura / ancho medio | v1: cobertura / ancho medio | v2: cobertura / ancho medio |
|---|---|---|---|
| especial | 76,1 % / 304 | 74,3 % / 300 | 74,2 % / 291 |
| normal | 82,1 % / 316 | 80,1 % / 305 | 79,7 % / 301 |
| **Global** | 80,2 % / 313 | 78,3 % / 304 | 78,0 % / 298 |

## El caso de las 6 h

**Validación** (banda v1, razón P90 / P50 de la hora):

| Ruta | Mediana a las 6 h | P95 | Máximo | Fecha del máximo | P50 / P90 / real en el máximo | Media y desviación observadas a las 6 h |
|---|---|---|---|---|---|---|
| CL 72 | 1,22 | 1,28 | 1,60 | 2025-10-13 | 193 / 310 / 177 | 484 ± 156 |
| CRA 54 | 1,16 | 1,22 | 1,24 | 2025-10-13 | 638 / 792 / 683 | 1988 ± 624 |
| SILENCIO | 1,20 | 1,28 | 1,38 | 2025-10-13 | 303 / 418 / 377 | 775 ± 203 |

Horas con P90 / P50 ≥ 2,9: 25 de 3111 (horas [4, 20]; P50 mediano 22,7 pasajeros; 20,0 % en días especiales).

**Prueba reservada** (banda v1, razón P90 / P50 de la hora):

| Ruta | Mediana a las 6 h | P95 | Máximo | Fecha del máximo | P50 / P90 / real en el máximo | Media y desviación observadas a las 6 h |
|---|---|---|---|---|---|---|
| CL 72 | 1,23 | 1,48 | 1,74 | 2025-12-08 | 175 / 304 / 155 | 493 ± 188 |
| CRA 54 | 1,16 | 1,36 | 1,76 | 2025-12-25 | 362 / 640 / 303 | 1788 ± 682 |
| SILENCIO | 1,16 | 1,34 | 2,51 | 2025-12-25 | 217 / 544 / 188 | 826 ± 275 |

Horas con P90 / P50 ≥ 2,9: 49 de 3111 (horas [4, 5, 20]; P50 mediano 22,1 pasajeros; 61,2 % en días especiales).

