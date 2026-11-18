# Protocolo: pronóstico de corto plazo por ruta, sentido y segmento

Escrito el 17 de noviembre de 2026, **antes de entrenar ningún modelo de este experimento**. Se confirma en git en dos
momentos, para que el historial pruebe el orden:

1. este protocolo y el código, antes de correr la validación;
2. los resultados de la validación y lo elegido (`resultados/seleccion.json`), antes de correr la prueba.

La prueba se calcula una sola vez, con lo elegido, y se reporta tal como salga.

## 1. Por qué existe este experimento

La retroalimentación del curso (17-nov-2026) señaló tres cosas de la entrega:

1. El pronóstico era a siete días por ruta y hora de salida, que no es el problema que se pidió.
2. Los modelos se eligieron y se reportaron sobre los mismos meses de 2025.
3. El modelo por segmento se entrenó con 37 días, así que lo espacial no quedó validado.

Este experimento resuelve el problema tal como lo pide la especificación v1.5 de Extreme Technologies: «predecir la
demanda para horizontes configurables de 30, 60 y 120 minutos» (§2.2, RF-005) «por ruta, sentido, segmento y franja
horaria» (§3.1, §9.1), con «división cronológica en entrenamiento, validación y prueba reservada» (§9.3).

## 2. El problema

- **Qué se pronostica.** En cada instante *t* (cada media hora, de 04:00 a 21:00: 35 instantes por día), las subidas
  de los siguientes **30, 60 y 120 minutos**, es decir, las de las ventanas [*t*, *t* + 30), [*t*, *t* + 60) y
  [*t*, *t* + 120).
- **A qué nivel.** Tres niveles, con los mismos instantes y las mismas ventanas:
  - la ruta (3 rutas);
  - el sentido (ida y regreso de cada ruta);
  - el segmento (los 386 segmentos oficiales de 500 m de `rutas_segmentos`: 135, 123 y 128).
- **Con qué información.** Solo lo ocurrido antes de *t* y lo que se conoce por adelantado (calendario). Ninguna
  variable usa nada del instante *t* en adelante.
- **Qué es una subida y cuándo cuenta.** Cada evento de conteo con `cantidad_subida > 0`, en el bloque de 15 minutos
  del instante en que ocurrió (como el disparador en vivo de Extreme, `7. trigger de conteo.sql`). Entran los eventos
  de todos los viajes, sin filtrar por la marca de cancelado.

## 3. Datos

- **Fuente.** Los eventos de conteo de la base del reto (`conteo_pasajeros_destino`), exportados en solo lectura con
  `exportar_eventos_subida.py`: instante, posición y cantidad de cada subida de 2023 a 2025 (44.185.831 eventos).
- **Segmento de cada subida.** La regla de Extreme (`5. cargue inicial timbradas_segmentos.sql`): el segmento activo
  más cercano de la ruta. La tabla `timbradas_segmentos` de la base solo cubre del 2023-01-01 al 2023-02-27; el
  panel de este experimento aplica la misma regla a los tres años y se verifica contra esa tabla en los 58 días que
  sí trae (`panel/verificacion_extreme.json`).
- **Sentido.** No viene en los datos: la geometría de cada ruta es el ciclo completo. «Ida» son los segmentos cuyo
  punto medio cae en la primera mitad de la longitud del ciclo; «regreso», el resto. Es la misma aproximación que usa
  la API y se declara como tal.
- **Días sin datos.** Un día de una ruta se trata como «sin datos» si tiene menos del 5 % de las subidas habituales
  (la mediana del mismo día de la semana en las 8 semanas anteriores). Son los días en que la base no trae eventos de
  conteo (en 2025, el último día de casi todos los meses). Esos días no se entrenan ni se evalúan y no entran en los
  promedios de las semanas siguientes.
- **Arranque.** Los primeros 56 días (2023-01-01 a 2023-02-25) no se entrenan ni se evalúan: la línea base de 8
  semanas necesita esa historia.

## 4. Partición

| Parte | Fechas | Para qué |
|---|---|---|
| Entrenamiento | 2023-01-01 a 2024-12-31 | ajustar los modelos |
| Validación | 2025-01-01 a 2025-06-30 | elegir todo: variables, hiperparámetros, estructura y banda |
| Prueba | 2025-07-01 a 2025-12-31 | reportar, una sola vez |

- La validación y la prueba son meses distintos. Nada se elige mirando la prueba.
- El modelo que se prueba es lo elegido en la validación, **reentrenado con todo lo anterior al 1 de julio de 2025**
  (entrenamiento más validación). No se vuelve a ajustar nada después.
- **Lo que hay que decir de 2025.** El equipo ya había usado los meses de 2025 en experimentos anteriores, con otro
  objetivo (pasajeros por hora de salida de los viajes válidos, a siete días). Ningún modelo de este problema (subidas
  por instante, horizonte corto, por segmento) se ha evaluado antes en julio–diciembre de 2025, y ninguna decisión de
  este experimento usa esos meses. Aun así, no es una prueba ciega en sentido estricto: se pidió a Extreme un periodo
  de 2026 para tenerla.

## 5. Líneas base y modelo candidato

**Líneas base** (las del enunciado, §9.1, y una más), en los tres niveles:

- **Promedio por día y hora:** la media de la misma ventana en el mismo día de la semana de las 8 semanas anteriores.
- **Última semana:** la misma ventana 7 días antes (si ese día no tiene datos, el promedio anterior).
- **Persistencia:** lo que subió en los mismos minutos justo antes de *t*. No está en el enunciado; se agrega porque es
  la referencia natural de un pronóstico de corto plazo.

**Candidato:** Gradient Boosting (LightGBM, pérdida de Poisson), un modelo por nivel, ruta y horizonte, semilla 42.

**Reglas de elección, todas con la validación** (`validar.py`):

- **A. Conjunto de información**, por nivel. Se elige el de menor WAPE medio de los tres horizontes, con las tres
  rutas juntas:
  - `semanal`: calendario y la misma ventana de las semanas anteriores (lo que se sabe con 7 días de antelación);
  - `con_hoy`: además, ayer, la última semana y lo observado hoy hasta *t*;
  - `completo`: además, las salidas ya despachadas y, por segmento, lo observado en los segmentos vecinos.
- **B. Hiperparámetros**, por nivel, entre tres configuraciones fijadas (`REJILLA` de `validar.py`): la de menor WAPE
  medio.
- **C. Estructura.**
  - Sentido: modelo directo o suma de los segmentos del sentido.
  - Segmento: modelo directo o conciliado con el pronóstico de la ruta (se reescala para que los segmentos sumen el
    pronóstico de la ruta).
  - En los dos casos gana el de menor WAPE medio.
- **D. Banda P10–P90.** Cuantiles conformales por tramo del pronóstico (4 tramos), ajustados con los errores de la
  validación de cada nivel, ruta y horizonte.

Para acotar el cómputo, en A y B el nivel de segmento se entrena con la mitad de las filas, elegidas al azar con
semilla 42. Lo elegido se vuelve a entrenar con todas las filas antes de C y D, y en la prueba.

## 6. Qué se reporta en la prueba

Todo sobre las mismas filas para todos los pronósticos (instantes de días con datos y con la línea base disponible):

- **Métricas** (§9.3): MAE, RMSE, WAPE, sMAPE y sesgo.
  - Por ruta y por franja (04–05, 06–08 pico, 09–16 valle, 17–19 pico, 20–21), y pico frente a valle.
  - Por sentido.
  - Por segmento: el WAPE sobre todas las celdas de segmento e instante y la distribución del sesgo por segmento.
- **Comparación con las líneas base:** diferencia de WAPE con su IC95 (bootstrap de bloques móviles de 7 días, 2.000
  réplicas, semilla 42).
- **Incertidumbre:** cobertura de la banda P10–P90 (objetivo 80 %), con el porcentaje bajo P10 y sobre P90.
- **La cifra principal** es el WAPE por ruta a 60 minutos frente al promedio por día y hora; los otros dos horizontes
  y los otros dos niveles se reportan igual.

**Análisis secundarios, declarados aquí** (se calculan en la misma corrida de la prueba; no cambian lo elegido):

1. Cuánto aporta la información del día: el conjunto `semanal` en la prueba, por ruta.
2. Sensibilidad al retraso de la captura: el modelo de ruta con lo observado solo hasta *t* − 15 y *t* − 30 minutos.
3. El error por mes y por tipo de día.

## 7. Lo que no se hace

- No se ajusta nada después de ver la prueba. Si un nivel o un horizonte sale mal, se reporta así.
- No se usa ninguna variable posterior a *t*: ni las salidas que todavía no han ocurrido ni el clima observado.
- No se comparan estas cifras con las del pronóstico a siete días del informe: son otro objetivo (subidas por
  instante frente a pasajeros por hora de salida) y otro horizonte.

## 8. Reproducibilidad

- `preparar_panel.py` arma `panel/` desde las exportaciones; `validar.py` y `probar.py` solo leen `panel/`.
- Semilla 42 en el modelo, en la submuestra y en el bootstrap. Las versiones de las bibliotecas quedan en
  `resultados/prueba.json`.
- El orden de los commits de este protocolo, de la validación y de la prueba es la evidencia de que la prueba no se
  usó para elegir.
- Antes de confirmar este protocolo solo se corrió una comprobación del código (`validar.py --rapido`: el 20 % de las
  filas, solo 60 minutos, medido en la validación). No se ha calculado nada sobre la prueba.
