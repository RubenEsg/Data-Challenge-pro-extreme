# Demostración de §14.2: qué muestra cada paso y por qué

`scripts/demo_ciclo_api.py` recorre los seis pasos de la especificación v1.5, §14.2 «Demostración»:

1. llegada de información nueva;
2. lectura incremental;
3. evaluación del error;
4. modelo candidato;
5. comparación con el modelo activo;
6. decisión de activarlo o rechazarlo.

`scripts/verificar_despliegue.py` lo corre sobre la pila Docker Compose creada desde cero, con
`--hasta 2025-08-30 --corte 2025-09-30 --revertir`, y guarda la salida en `demo_ciclo_api.txt`. Este archivo explica
qué tiene que mostrar esa corrida y deja la salida de referencia contra la API sin Docker.

## Montaje de la corrida de referencia

- **Fecha:** 13-11-2026, 22:13 (America/Bogota).
- **API:** `uvicorn app.main:app` en 127.0.0.1:8362, con un trabajador de cola (`TRABAJADORES=1`, el valor por omisión).
- **Base de datos:** una base de pruebas nueva en el PostgreSQL local (puerto 5433), migrada con
  `alembic upgrade head` (0014, head). No había ejecuciones previas.
- **Datos:** `DATA_DIR` y `MODELOS_DIR` apuntan a una copia temporal de `datos/`. El registro del repositorio no
  cambia: el activo sigue siendo `hgb_fv2_20250831_s42`.
- **Autenticación:** encendida, con claves de prueba por rol creadas para la corrida. La clave admin llega solo por
  el entorno (`SOBUSA_API_KEY`) y no se imprime.
- **Notificaciones:** simuladas, con los destinatarios de prueba de `docker-compose.yml` (`despacho@example.com` y
  `+570000000000`), como en la pila aislada.
- **Comando:** `.venv\Scripts\python scripts\demo_ciclo_api.py --hasta 2025-08-30 --corte 2025-09-30 --revertir`.
- **Resultado:** código de salida 0 en 120 s. Imprime los pasos (1) a (6).
- **Confirmación:** una segunda corrida a las 22:16, otra vez sobre una base nueva (es
  `../cola/demo_ciclo_api_cola.txt`), dio la misma salida: las mismas filas, marcas de agua, métricas, criterios,
  decisión, alertas y notificaciones (simuladas 116, omitidas 72). Solo cambiaron los tiempos y los identificadores de
  las ejecuciones. Terminó con código 0 en 120 s. La corrida en la pila aislada de `verificar_despliegue.py` (23:07,
  `demo_ciclo_api.txt`) dio también la misma salida, salvo los tiempos, los identificadores y el sha256 del candidato
  (ver el paso 4).
- **Frente a la corrida de referencia del 11-11-2026 (06:48):** la salida es la misma línea por línea, salvo los
  tiempos y los identificadores. Entre las dos corridas cambió el código (el contraste por segmento, la lectura
  `demanda_segmentos` de la fuente y la política de reentrenamiento sin datos suficientes). Esta demostración usa la
  serie empaquetada y tiene histórico suficiente, así que la política encola el entrenamiento como antes.
- **Por qué cambiaron las cifras frente a la corrida de referencia del 9-11-2026 (07:30, base hasta la 0007):**
  las alertas observadas evalúan ahora hasta 7 días del lote (`VENTANA_OBSERVADA_DIAS`, paquete de cierre). La carga
  inicial pasa de 4 a 27 alertas, los días nuevos de 8 a 25 y la sombra de 6 a 33. El día nuevo pasa de 10 a 9: como en
  `../rendimiento/ciclo_final.md`, ya no sale la ALT-003 de pronóstico de CL 72, que desde la migración 0014 exige una
  probabilidad mínima. Las notificaciones cambian con las alertas y con los destinatarios de prueba (antes, simuladas 0
  y omitidas 56). Los umbrales son la versión 9. Las filas, las marcas de agua, los WAPE, el candidato y la decisión no
  cambian.

## La línea de tiempo y por qué esas fechas

| Fecha | Qué es | Por qué |
|---|---|---|
| 2025-08-31 | Corte del modelo activo `hgb_fv2_20250831_s42` | Es el modelo empaquetado |
| 2025-10-31 | Último día que vio el activo | Su corte más los 61 días de validación con los que se calibró la banda P10-P90 |
| 2025-08-30 | Carga inicial (`--hasta`) | La primera ejecución no tiene marca de agua |
| 2025-08-31 | Un día nuevo | La lectura incremental más pequeña: 51 filas |
| 2025-11-30 | Marca de agua M = `--corte` + 61 días | El candidato se entrena con corte 2025-09-30 y `datos_hasta` = M: valida con los 61 días siguientes y solo ve lo que ya llegó |
| 2025-12-01 .. 2025-12-14 | Sombra y comparación | Los `sombra_dias` = 14 días siguientes a M. Es posterior a lo que vio el candidato (M) y a lo que vio el activo (2025-10-31), así que queda fuera de la muestra de los dos. Termina antes del 2025-12-31, último día de `datos/demanda_horaria.parquet`, así que tiene datos reales |

`POST /models/{id}/activate` exige una ventana posterior a lo que vio el candidato y responde 422
`ventana_en_muestra` si no lo es. Esta demostración nunca le pasa una ventana dentro de la muestra: la comparación
usa la ventana de la sombra.

## Qué muestra cada paso

### (1) Llegada de información nueva

Hay tres ejecuciones `POST /api/v1/frequency/executions`:

| Ejecución | Hasta | Filas leídas | Alertas |
|---|---|---|---|
| Carga inicial | 2025-08-30 | 49.623 | 27 |
| Un día nuevo | 2025-08-31 | 51 | 9 |
| Los días hasta M | 2025-11-30 | 4.641 | 25 |

Las alertas observadas evalúan hasta los 7 últimos días del lote (`VENTANA_OBSERVADA_DIAS`), cada uno con sus horas
cerradas. Por eso la carga inicial y los días hasta M abren más alertas que el día nuevo, cuyo lote es de un día.

Cada ejecución imprime sus predicciones, recomendaciones y alertas, y también «notificaciones simuladas N,
omitidas M», que sale de `metricas.notificaciones_por_estado`. En esta corrida las notificaciones fueron simuladas 116
y omitidas 72, una por alerta y canal (correo y WhatsApp): con `NOTIFICACIONES_SEVERIDAD=critica` solo se envían al
canal simulado las alertas críticas, y las demás quedan registradas como omitidas.

### (2) Lectura incremental

Para cada ejecución se imprime la marca de agua anterior y la nueva, y las filas leídas. Las marcas son
`None -> 2025-08-30T23:59:59-05:00 -> 2025-08-31T23:59:59-05:00 -> 2025-11-30T23:59:59-05:00`.

La repetición con la misma fecha lee 0 filas y crea 0 predicciones: no relee ni duplica nada. En esta corrida la
repetición esperó en la cola detrás del entrenamiento que encoló la política (ver el paso 4), por eso tardó más.

### (3) Evaluación del error

Error del modelo activo en lo recién llegado:

| Días | WAPE | Cobertura P10-P90 | n |
|---|---|---|---|
| 2025-08-31 | 26,485 % | 66,67 % | 51 |
| 2025-09-01 .. 2025-11-30 | 13,325 % | 80,13 % | 4.641 |
| 2025-11-01 .. 2025-11-30 (fuera de su muestra) | 12,83 % | 80,26 % | 1.530 |

El paso también imprime el monitoreo de §9.4 (WAPE móvil, cobertura y PSI) y la decisión de la política de
aprendizaje continuo. Al llegar 2025-11-30, la política decide reentrenar por «periodicidad: 30 días de datos nuevos
desde 2025-10-31 (cada 28)».

### (4) Modelo candidato

El candidato se entrena con `hasta` = 2025-09-30 y `datos_hasta` = 2025-11-30.

Con los umbrales vigentes (`reentreno_en_ciclo` = 1), la propia política ya encoló ese mismo entrenamiento al cerrar
la ejecución hasta M. El script espera ese job en vez de pedir otro igual con `POST /api/v1/models/train`, porque dos
entrenamientos con el mismo identificador competirían por el mismo artefacto. Si la política no lo hubiera encolado,
el script hace el `POST /api/v1/models/train` con esos dos parámetros.

El resultado:
- `hgb_fv2_20250930_s42`, entrenado en 13,6 s por el trabajador de la cola;
- sha256 `1c280ae7910b…` en las dos corridas con el venv, el mismo de las corridas del 9-11 y del 11-11-2026. El
  sha256 es el del archivo del artefacto. En la imagen Docker (Python 3.11) no se repite de una corrida a otra:
  `8caa080bb0c4…` el 13-11-2026 a las 23:07 (y otro distinto en cada una de las tres corridas anteriores de ese día),
  `d92ba337c6bf…` el 11-11-2026 y `6a898a553dcd…` el 9-11-2026. La causa no está investigada. Las métricas del candidato y la decisión son las mismas en todas;
- su propia calibración v2 de la banda, ajustada con su validación 2025-10-01 .. 2025-11-30 (3.111 horas);
- queda «en_sombra» del 2025-12-01 al 2025-12-14.

### (5) Comparación con el modelo activo

Llegan los 14 días de la sombra (714 filas). En ese ciclo el candidato predice lo mismo que el activo, sin decidir
nada. Al completarse la ventana, la compuerta compara a los dos en ella. `GET /models/{id}/evaluation` da la misma
medida para los dos en la misma ventana:

| Modelo | WAPE | Sesgo | Cobertura P10-P90 | n |
|---|---|---|---|---|
| Candidato | 14,108 % | 3,163 % | 79,41 % | 714 |
| Activo | 13,982 % | 3,282 % | 78,85 % | 714 |

### (6) Decisión de activarlo o rechazarlo

La compuerta de cuatro criterios (`politica.compuerta`) se aplica en 2025-12-01 .. 2025-12-14, con la banda calibrada
v2 de cada modelo. El script imprime cada criterio:

| Criterio | Candidato | Referencia | Resultado |
|---|---|---|---|
| WAPE del candidato ≤ WAPE del activo | 14,11 % | 13,98 % | **No cumple** |
| WAPE ≤ `wape_max` | 14,11 % | 20 % | Cumple |
| Cobertura P10-P90 en [75 %, 90 %] | 79,41 % | — | Cumple |
| \|sesgo\| ≤ `sesgo_max` | 3,16 % | 5 % | Cumple |

El candidato queda **rechazado** con ese motivo y el activo sigue.

Activarlo sin forzar con `POST /models/{id}/activate` responde 409 `requiere_forzar`: un rechazado solo se activa
con `forzar=true` y un motivo, que queda en la auditoría.

Con `--revertir`, si la compuerta lo hubiera activado, el script lo revierte con `POST /api/v1/models/rollback`. Lo
mismo pasa si la compuerta aprueba con `activacion_automatica` = 0 y lo activa un admin en la misma ventana. En esta
corrida no hay nada que revertir, y el script lo dice.

## Qué cambia entre corridas y qué no

**No cambia**, porque la fuente es la serie empaquetada y el entrenamiento usa la semilla 42:
- las filas leídas, las marcas de agua y los WAPE de los pasos 3 y 5;
- el identificador del candidato, y su sha256 en las corridas con el venv (en la imagen Docker cambia, ver el
  paso 4);
- los criterios de la compuerta y la decisión.

**Puede cambiar:**
- los tiempos;
- los identificadores de las ejecuciones;
- el número de alertas, que depende de la hora de la corrida para la frescura (ALT-009);
- el número de notificaciones simuladas y omitidas, que depende además de los canales y destinatarios configurados.

`scripts/verificar_despliegue.py` exige código 0 y los pasos (1) a (6) impresos. Después, la prueba de reinicios
(RNF-001) sigue desde la última marca de agua de la demostración (2025-12-14) con un día nuevo por escenario
(2025-12-15 y 2025-12-16), que todavía están dentro de la serie empaquetada.

## Desde el 19-11-2026: el corto plazo dentro de cada ciclo

Con la migración 0016, cada ejecución de la demostración hace también lo que pide RF-005 para el pronóstico de 30, 60
y 120 minutos, y `demo_ciclo_api.txt` lo imprime bajo cada ejecución:

- **la lectura de 15 minutos** de los días que trajo la ejecución, en días-ruta: en la carga inicial, 2.919 días-ruta
  y 11.012.701 celdas, con las 2 celdas imposibles excluidas por VAL-009. Son días del panel empaquetado, así que no se
  copian a `subidas_15min` («0 guardadas»): `lectura_15min` dice hasta dónde se leyó cada uno. El día nuevo
  (2025-08-31) trae 1 celda válida en las tres rutas porque la fuente casi no tiene eventos de conteo de ese domingo,
  aunque sí tiene sus salidas;
- **9 pronósticos de corto plazo** (3 rutas × 3 horizontes) con su recomendación, en el primer instante del día
  siguiente a lo leído (04:00);
- **el monitoreo del corto plazo**: el WAPE móvil de 7 días y la cobertura P10-P90 del modelo `cp_lgbm_20250630_s42`.

El ciclo de vida que demuestra §14.2 sigue siendo el del modelo horario: el script toma el activo de la familia
`horario` (`GET /models?familia=horario`), y la compuerta compara al candidato con ese activo. En la corrida vigente
(19-11-2026, 03:20, en Docker), el candidato `hgb_fv3_20250930_s42` gana 13,578 % frente a 13,982 % de
`hgb_fv2_20250831_s42` en 2025-12-01..14 (714 filas), la compuerta lo activa y `--revertir` lo devuelve. El activo de
corto plazo no cambia. El registro del final muestra la familia de cada modelo. Cada ejecución tarda ahora entre 51 y
73 s (antes, unos 20 s), y el ciclo completo 294 s.

La corrida de referencia de abajo es del 13-11-2026, de antes de fv3 y del corto plazo dentro del ciclo: por eso
entrena `hgb_fv2_20250930_s42`, que la compuerta rechaza, y no imprime las líneas del corto plazo.

## La demostración ampliada (`scripts/demo_ciclo.py`)

`scripts/demo_ciclo.py` recorre además las predicciones, las recomendaciones, las alertas y su ciclo de vida, la
exportación y las notificaciones. Su paso 8 sigue la misma regla que esta demostración:

- el candidato se entrena con `datos_hasta` = la marca de agua (2025-11-04) y corte = marca menos 61 días
  (2025-09-04);
- activarlo antes de que termine la sombra responde 409 `requiere_forzar`;
- llegan los 14 días de la sombra (2025-11-05 .. 2025-11-18) y la compuerta imprime sus cuatro criterios;
- la línea base se intenta activar en los días ya llegados fuera de la muestra del activo (2025-11-01 .. 2025-11-18);
- el día de las notificaciones es el siguiente a la última marca de agua (2025-11-19);
- cada ejecución imprime «notificaciones simuladas N, omitidas M».

En la corrida del 13-11-2026 a las 22:18, con el mismo montaje de la corrida de referencia (API en 127.0.0.1:8364,
base nueva hasta la 0014 y copia temporal de `datos/`), igual que en las del 11-11-2026 a las 06:54 y del 9-11-2026
a las 07:37:
- código 0 en 118 s y «RESULTADO: OK, todos los pasos cumplidos»;
- el candidato `hgb_fv2_20250904_s42` se rechaza: WAPE 12,195 % frente a 12,111 % del activo; los otros tres
  criterios se cumplen;
- la línea base `b1_manual_8sem` se rechaza con 409 `activacion_rechazada`.

## Salida de la corrida de referencia

```text
=== Ciclo completo de la especificación v1.5 §14.2 «Demostración» · API http://127.0.0.1:8362 · 2026-11-13 22:13:59 -0500 (America/Bogota) ===
Estado: GET /health -> {'estado': 'ok', 'base_datos': 'ok', 'version': '1.0.0', 'fuente': 'parquet', 'integraciones': {'fuente_postgres': {'estado': 'cerrado', 'fallos_seguidos': 0, 'fallos_max': 3, 'reinicio_s': 60.0, 'reintento_en_s': None, 'ultimo_error': None}, 'notif_correo': {'estado': 'cerrado', 'fallos_seguidos': 0, 'fallos_max': 5, 'reinicio_s': 120.0, 'reintento_en_s': None, 'ultimo_error': None}, 'notif_whatsapp': {'estado': 'cerrado', 'fallos_seguidos': 0, 'fallos_max': 5, 'reinicio_s': 120.0, 'reintento_en_s': None, 'ultimo_error': None}}}
Modelo activo al empezar: hgb_fv2_20250831_s42 (variables fv2-2026-11-09, corte 2025-08-31; vio datos hasta 2025-10-31: corte + 61 días de validación, con los que se calibró su banda P10-P90)
Umbrales v9 (propuesta): sombra_dias 14, activacion_automatica 1, reentreno_en_ciclo 1, reentreno_periodicidad_dias 28, wape_max 0.2
Línea de tiempo: carga inicial hasta 2025-08-30; la información nueva llega hasta 2025-11-30 (corte del candidato 2025-09-30 + 61 días); sombra y comparación 2025-12-01 .. 2025-12-14.

(1) Llegada de información nueva
    Carga inicial: el histórico disponible hasta 2025-08-30 (primera ejecución, sin marca de agua).
    ... en_cola 0 %
    ... calidad 25 %
    ... prediccion 45 %
    ... alertas 70 %
    ... plan_dia 92 %
    ejecución eccd45b0-03b8-4b81-a4f7-901f9e0f4ec5 (carga-inicial, hasta 2025-08-30): ok en 29.0 s; filas leídas 49623, válidas 49623
    predicciones 9, recomendaciones 9, alertas 27; notificaciones simuladas 42, omitidas 12
    Llega un día nuevo: 2025-08-31 queda disponible en la fuente.
    ... en_cola 0 %
    ... calidad 25 %
    ... prediccion 45 %
    ... alertas 70 %
    ... plan_dia 92 %
    ejecución b3a19670-f62d-4964-80e8-bbf954e2589a (dia-nuevo, hasta 2025-08-31): ok en 21.8 s; filas leídas 51, válidas 51
    predicciones 9, recomendaciones 9, alertas 9; notificaciones simuladas 10, omitidas 8
    Siguen llegando días: 2025-09-01 .. 2025-11-30, hasta la marca de agua con la que se entrenará el candidato (su corte 2025-09-30 más 61 días de validación).
    ... en_cola 0 %
    ... calidad 25 %
    ... prediccion 45 %
    ... alertas 70 %
    ... plan_dia 92 %
    ejecución 7349c22b-d2ec-4998-a875-4c59ddddb11a (dias-nuevos, hasta 2025-11-30): ok en 25.4 s; filas leídas 4641, válidas 4641
    predicciones 9, recomendaciones 9, alertas 25; notificaciones simuladas 28, omitidas 22

(2) Lectura incremental
    POST /api/v1/frequency/executions lee SOLO lo posterior a la marca de agua (solo lectura de la fuente):
    carga inicial marca de agua None -> 2025-08-30T23:59:59-05:00: filas leídas 49623, válidas 49623
    día nuevo     marca de agua 2025-08-30T23:59:59-05:00 -> 2025-08-31T23:59:59-05:00: filas leídas 51, válidas 51
    días nuevos   marca de agua 2025-08-31T23:59:59-05:00 -> 2025-11-30T23:59:59-05:00: filas leídas 4641, válidas 4641
    Repetición sin datos nuevos (la misma fecha): no relee ni duplica nada
    ... en_cola 0 %
    ... lectura_incremental 10 %
    ejecución 1a7673c4-a921-4301-bf33-5d850c141656 (repeticion, hasta 2025-11-30): ok en 15.9 s; filas leídas 0, válidas 0
    predicciones 0, recomendaciones 0, alertas 0; notificaciones simuladas 0, omitidas 0
    repetición    marca de agua 2025-11-30T23:59:59-05:00 -> 2025-11-30T23:59:59-05:00: filas leídas 0, predicciones 0
    (la repetición esperó en la cola detrás del entrenamiento que encoló la política, ver (3) y (4))

(3) Evaluación del error
    Modelo activo en lo recién llegado, día nuevo (2025-08-31 .. 2025-08-31): WAPE 26.485 %, MAE 82.445, sesgo 13.601 %, cobertura P10-P90 66.67 %, n = 51
    Modelo activo en lo recién llegado, días nuevos (2025-09-01 .. 2025-11-30): WAPE 13.325 %, MAE 94.059, sesgo 1.24 %, cobertura P10-P90 80.13 %, n = 4641
    De esos días, los posteriores a su muestra (2025-11-01 .. 2025-11-30): WAPE 12.83 %, MAE 86.978, sesgo 1.346 %, cobertura P10-P90 80.26 %, n = 1530
    monitoreo 2025-11-30 hgb_fv2_20250831_s42 (activo): aviso; WAPE móvil 12.64 %, cobertura P10-P90 80.67 %, PSI máx 0.1265 (sd8)
    monitoreo 2025-08-31 hgb_fv2_20250831_s42 (activo): ok; WAPE móvil 13.05 %, cobertura P10-P90 76.96 %, PSI máx 0.052 (b8)
    monitoreo 2025-08-30 hgb_fv2_20250831_s42 (activo): ok; WAPE móvil 12.91 %, cobertura P10-P90 77.24 %, PSI máx 0.0524 (b8)
    política de aprendizaje continuo al cerrar la ejecución hasta 2025-11-30: reentrenar True, motivos ['periodicidad: 30 días de datos nuevos desde 2025-10-31 (cada 28)'], bloqueos []

(4) Modelo candidato
    La política ya encoló el entrenamiento al cerrar la ejecución (job 15b514da-feec-4a81-9511-3f442ebc5fa3, hasta 2025-09-30, datos_hasta 2025-11-30): es el mismo trabajo que POST /api/v1/models/train con esos parámetros, así que se espera ese job en vez de duplicarlo.
    entrenamiento ok en 13.6 s (trabajador de la cola): Candidato hgb_fv2_20250930_s42 registrado
    candidato hgb_fv2_20250930_s42: estado candidato, variables fv2-2026-11-09, corte 2025-09-30, datos hasta 2025-11-30, sha256 1c280ae7910b…
    sombra: en_sombra del 2025-12-01 al 2025-12-14 (14 días); banda P10-P90 con su propia calibración v2 por ['bloque'], validación 2025-10-01 a 2025-11-30 (3111 horas); la prueba reservada no se usa

(5) Comparación con el modelo activo
    Misma ventana para los dos: 2025-12-01 .. 2025-12-14. Por qué estas fechas: el candidato vio datos hasta 2025-11-30 (corte 2025-09-30 + 61 días) y el activo hasta 2025-10-31; la ventana empieza después de los dos (fuera de la muestra de ambos) y termina antes del 2025-12-31, el último día de la serie empaquetada, así que hay datos reales para medirlos.
    Llegan los 14 días de la sombra: en ese ciclo el candidato predice lo mismo que el activo (sin decidir nada) y, al completarse la ventana, la compuerta compara a los dos en ella.
    ... en_cola 0 %
    ... lectura_incremental 10 %
    ... calidad 25 %
    ... prediccion 45 %
    ... alertas 70 %
    ... plan_dia 92 %
    ejecución 064fbcfe-2b14-4e55-973d-fccbf8a70591 (sombra, hasta 2025-12-14): ok en 26.3 s; filas leídas 714, válidas 714
    predicciones 9, recomendaciones 9, alertas 33; notificaciones simuladas 36, omitidas 30
    candidato hgb_fv2_20250930_s42: WAPE 14.108 %, MAE 93.003, sesgo 3.163 %, cobertura P10-P90 79.41 %, n = 714
    activo    hgb_fv2_20250831_s42: WAPE 13.982 %, MAE 92.176, sesgo 3.282 %, cobertura P10-P90 78.85 %, n = 714
    compuerta de sombra de hgb_fv2_20250930_s42: rechazado

(6) Decisión de activarlo o rechazarlo
    Compuerta de cuatro criterios (politica.compuerta) en 2025-12-01 .. 2025-12-14, umbrales v9, banda calibrada v2 del candidato frente a v2 del activo:
    [NO cumple] WAPE del candidato ≤ WAPE del activo: candidato 14.11 %, referencia 13.98 %
    [cumple] WAPE ≤ wape_max (20%): candidato 14.11 %, referencia 20.00 %
    [cumple] cobertura P10-P90 en [75%, 90%]: candidato 79.41 %, referencia [75.00 %, 90.00 %]
    [cumple] |sesgo| ≤ sesgo_max (5%): candidato 3.16 %, referencia 5.00 %
    RECHAZADO hgb_fv2_20250930_s42: compuerta de sombra no aprobada: WAPE del candidato ≤ WAPE del activo. El activo hgb_fv2_20250831_s42 sigue.
    Intento de activarlo sin forzar (POST /api/v1/models/hgb_fv2_20250930_s42/activate): 409 requiere_forzar: la gobernanza no se salta sin forzar=true y un motivo auditado.
    --revertir: no hay nada que revertir, el candidato no llegó a activarse.
    registro de modelos: [('hgb_fv2_20250930_s42', 'rechazado'), ('hgb_fv1_20250831_s42', 'candidato'), ('b1_manual_8sem', 'candidato'), ('b2_ultima_semana', 'candidato'), ('hgb_fv2_20250831_s42', 'activo')]

Notificaciones de las ejecuciones (metricas.notificaciones_por_estado): simuladas 116, omitidas 72.
Ciclo completo en 119 s.
```
