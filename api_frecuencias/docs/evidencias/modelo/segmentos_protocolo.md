# Modelo por segmento y sentido: protocolo fijado antes de mirar la prueba

Especificación v1.5: §3.1 «Predicción de demanda: por ruta, sentido, segmento y franja horaria → pronóstico e intervalo
de confianza», §9.1 «pronóstico supervisado … por ruta, sentido, segmento y ventana temporal», §9.3 (división
cronológica, sin fuga, línea base, cuantiles y sesgo por sentido, segmento y condición) y §7.3 paso 4.

Este archivo se escribió y se guardó en el repositorio (commit propio) ANTES de evaluar cualquier modelo en la ventana
de prueba. Las constantes que lo fijan están en `app/servicios/modelo_segmentos.py` (`PARTICION`, `REGLA_ELECCION`,
`HIPER_DEFECTO`, `CORTES_MU`) y las usa `scripts/entrenar_segmentos.py`. Los resultados van en
`segmentos_modelo.json` y `segmentos_modelo.md`, en un commit posterior.

## Datos

- `timbradas_segmentos` exportada (subidas por segmento y viaje): solo existe del 2023-01-01 al 2023-02-27, porque los
  triggers de segmentación no se volvieron a ejecutar. Faltan el 2023-01-31 y el 2023-02-01 (no hay filas).
- La hora es la de salida del viaje (`progvehiculos.fechasalida`), la misma «hora» del pronóstico por ruta; horas 4 a
  20; las 3 rutas del catálogo (CL 72: 128 segmentos, CRA 54: 123, SILENCIO: 135).
- Celda = (ruta, fecha, hora). Objetivo = subidas de cada segmento en la celda. T = total de la ruta en la celda (suma
  de sus segmentos).
- Archivo versionado: `datos/subidas_segmento_hora.parquet` (agregado por ruta, fecha, hora y segmento, sin viajes ni
  vehículos), generado por `scripts/preparar_segmentos.py` desde las exportaciones.
- Sentido: aproximación geométrica (supuesto S9): «ida» son los segmentos cuyo punto medio cae en la primera mitad de
  la longitud acumulada del ciclo. Las exportaciones no traen sentido.

## Partición cronológica (sin solape)

| Ventana | Fechas | Días con datos | Para qué |
|---|---|---|---|
| Entrenamiento | 2023-01-01 a 2023-02-08 | 37 | ajustar los modelos y la fracción B0 |
| Validación | 2023-02-09 a 2023-02-17 | 9 | elegir el modelo (regla de abajo) y calibrar la banda |
| Prueba | 2023-02-18 a 2023-02-27 | 10 | reportar una sola vez, al final |

Motivos del corte, decididos con el calendario y no con resultados: el entrenamiento incluye la semana de regreso a
clases (2023-02-02 a 2023-02-08, sin vacaciones escolares), para que la variable `vacaciones` tenga los dos valores; la
validación es la semana y media siguiente, sin vacaciones ni Carnaval; la prueba es lo último y contiene el Carnaval de
Barranquilla (18 a 21 de febrero), que se reporta aparte como condición operacional.

## Candidatos

- **B0, reparto fijo** (la línea base, lo que hoy usa la API): fracción de las subidas de la ruta por (ruta, tipo de
  día, hora), con respaldo (ruta, tipo de día) y (ruta) si la celda tiene menos de 200 subidas; suma 1 en cada celda.
- **M1, HGB Poisson con desplazamiento log(T · fracción B0)**: aprende una corrección multiplicativa del reparto fijo.
- **M2, HGB Poisson con desplazamiento log(T)**: aprende la fracción directamente (con la fracción B0 como variable).
- **M3, jerárquico con el sentido de B0** (agregado en la ronda 2, ver «Historial»): fracción del sentido de B0 ×
  reparto dentro del sentido de M2.
- **M4, jerárquico con un modelo de sentido** (agregado en la ronda 2): fracción del sentido de un segundo HGB Poisson
  por hora y sentido (exposición T · fracción B0 del sentido; variables: ruta, sentido, hora, calendario y log de la
  fracción B0 del sentido; learning_rate 0,05, max_iter 100, max_leaf_nodes 7, min_samples_leaf 200, l2 1,0) ×
  reparto dentro del sentido de M2.

Los HGB son HistGradientBoostingRegressor con pérdida de Poisson. Como no acepta desplazamiento, se ajusta y / e con
peso e (misma devianza que y con offset log e). La fracción prevista se normaliza a 1 en cada celda, así que la suma
de los segmentos sigue siendo exactamente el total de la ruta.

Variables (versión `sv1-2026-11-09`), todas conocidas antes del día pronosticado: ruta, número de segmento, posición
del segmento en el ciclo (0 a 1), sentido, hora, tipo de día, día de la semana, festivo, vacaciones, Carnaval,
log(fracción B0) y log(1 + subidas de la celda B0). La fracción B0 de las filas de entrenamiento se calcula fuera de
pliegue (pliegues de 7 días corridos, sin las fechas del propio pliegue); en validación y prueba sale del entrenamiento
completo.

Hiperparámetros fijos (no se ajustan con la prueba): learning_rate 0,05, max_iter 300, max_leaf_nodes 31,
min_samples_leaf 100, l2_regularization 1,0, sin parada temprana, semilla 42.

## Métricas

Con el total REAL de la ruta en cada celda (aísla el error del reparto): WAPE por segmento y hora (principal), WAPE por
sentido y hora, MAE por segmento y hora, y sesgo = Σ(p − y) / Σ y por segmento, por sentido y por ruta (mediana y p90
del sesgo absoluto por segmento).

## Regla de elección (en la validación; nunca con la prueba)

1. Un candidato es elegible si mejora el WAPE por segmento y hora de B0 con el intervalo de 95 % de la diferencia
   (bootstrap por días de la validación, 1.000 réplicas, semilla 42) por debajo de 0, y su WAPE por sentido y hora no
   empeora el de B0 en más de 0,25 puntos.
2. Entre los elegibles gana el de menor WAPE por segmento y hora. Si ninguno es elegible, B0 sigue activo.
3. Salvaguarda declarada: si el elegido resulta peor que B0 en el WAPE por segmento y hora de la prueba, no se activa
   (B0 sigue activo) y se reporta. La prueba solo puede vetar una activación, nunca elegir entre candidatos.

## Historial de la validación (antes de mirar la prueba)

La regla, la partición, las métricas y los hiperparámetros de M1 y M2 no cambiaron entre rondas, y la prueba no se
consultó en ninguna (`scripts/entrenar_segmentos.py --sin-prueba` no la lee ni guarda nada).

- **Ronda 1 (B0, M1, M2).** WAPE por segmento y hora: B0 38,06, M1 37,25, M2 36,93; por sentido y hora: B0 8,47, M1
  9,23, M2 9,04. Ninguno era elegible: M1 no mejoraba con significancia (IC95 de la diferencia −1,53 a +0,03 pp) y M2
  sí mejoraba (IC95 −1,79 a −0,48 pp) pero empeoraba el sentido en 0,57 pp. Diagnóstico, también en la validación: M2
  reduce el sesgo del sentido (CL 72 ida de −2,3 % a −0,9 %), pero su fracción del sentido es más ruidosa de una hora
  a otra.
- **Ronda 2.** Se agregaron M3 y M4, que separan la fracción del sentido del reparto dentro del sentido. Para el
  modelo de sentido de M4 se probaron dos configuraciones en la validación (15 hojas, 100 filas por hoja y 200
  iteraciones frente a 7 hojas, 200 filas por hoja y 100 iteraciones) y quedó la más simple, que también fue la mejor
  en el sentido (8,34 frente a 8,62). La elección con la regla de arriba se hace con los cinco candidatos.

## Banda P10-P90

- Conformal de Mondrian por tramo de la demanda esperada μ = T · f (cortes 1, 3, 10, 30, 100, 300 y 1.000), puntaje
  s = (y − μ) / √(μ + 1), cuantiles 10 % y 90 % con la corrección de muestra finita, ajustados en la validación con el
  modelo elegido, por separado para segmento y para sentido. Un tramo con menos de 50 filas usa los cuantiles globales.
- Con el pronóstico de la ruta (P10, P50, P90) la banda se compone en cuadratura (independencia entre el error de la
  ruta y el del reparto): μ̂ = f · P50, semiancho inferior √((f (P50 − P10))² + (q₁₀ √(μ̂ + 1))²) y el superior igual con
  P90 y q₉₀.
- Cobertura medida en la prueba de dos formas: (a) con el total real (banda del reparto sola) y (b) de punta a punta,
  compuesta con un pronóstico de ruta fuera de muestra real para 2023: B2 (la misma hora hace 7 días) con su banda
  conformal relativa ajustada en la validación. El modelo de ruta activo no tiene pronósticos fuera de muestra en 2023
  (su entrenamiento empieza el 2023-01-08), así que no se usan sus predicciones dentro de muestra.

## Sesgo por condición (§9.3)

En la prueba: sesgo y WAPE por sentido y segmento según franja (04-05, 06-08, 09-16, 17-19, 20), tipo de día y
Carnaval; de punta a punta con B2; y la composición (1 + sesgo de la ruta) · (1 + sesgo del reparto) − 1 con el sesgo
de ruta del modelo activo medido fuera de muestra en 2025 por franja y tipo de día
(`evaluacion_modelo.json`, `prueba_reservada`), declarada como composición.

## Después de la prueba (nota agregada al reportar)

La prueba se corrió una vez con el elegido de la validación (M4), que se activó porque no empeora a B0 en la prueba.
Al ver que la banda de B2 se rompe con el Carnaval (B2 es la misma hora de la semana anterior), se agregó un análisis
que no estaba en este protocolo: componer la banda con errores reales del modelo de ruta activo de nov-dic 2025
(`segmentos_modelo.md`, «Análisis adicional»). No cambió la elección, la activación ni la banda.

## Producción

El elegido se reentrena con los 56 días (2023-01-01 a 2023-02-27) con la misma configuración y la misma semilla; la
fracción B0 de inferencia sale de los 56 días; la banda usa los cuantiles ajustados en la validación. Se guarda en
`datos/modelos/segmentos/<model_id>/` (artefacto, manifiesto con SHA-256, versión de datos, partición, métricas, semilla,
hiperparámetros y huella del código) y se registra en `datos/modelos/segmentos/registro.json`.
