# Sobusa Despacho · Laboratorio del modelo

App en Python (Dash) que muestra **el modelo funcionando en vivo**. La app HTML del proyecto (`app.html`) enseña los resultados ya calculados; aquí el pronóstico se puede cambiar de modelo y el optimizador de salidas (el MILP de D5) se resuelve en el momento con CBC, con la ruta, el día y los costos que se elijan.

Data Challenge Pro Extreme – Sobusa 2026 · Universidad del Norte · Abrahan Basto Martínez, Rubén Esguerra Fernández y Paula Gómez.

## Cómo instalar y correr

Hace falta Python 3.11 o más reciente (probado con 3.13 en Windows 11).

**En Windows:** doble clic en `iniciar_dash.bat`. La primera vez crea `.venv` en esta carpeta e instala `requirements.txt`
(alrededor de un minuto, con internet); después abre el navegador solo en http://127.0.0.1:8050. Para detener la app,
cierre la ventana negra.

**En cualquier sistema**, desde esta carpeta (`dash_app`):

```
python -m venv .venv
.venv\Scripts\activate              (Windows)
source .venv/bin/activate           (macOS o Linux)
pip install -r requirements.txt
python app.py
```

Abra **http://127.0.0.1:8050** en el navegador. Para detenerla, Ctrl+C en la terminal.

No necesita internet ni la base de datos (salvo las calles del mapa de Despacho, que se cargan de CARTO/OpenStreetMap): todo lo que usa está en `datos/` (unos 2,3 MB). El solucionador CBC viene dentro del paquete PuLP, no hay que instalarlo aparte.

## Las once pantallas

Arriba, la barra de navegación con las once pestañas (la activa en píldora negra; desde 1101 px van compactas y el chip
«Cálculo en vivo» queda solo con su icono, y entre 1101 y 1279 px queda el logo sin el nombre de la marca: así las once
caben desde 1101 px, medido con Edge sin interfaz; por debajo, como en el teléfono, se desplazan en horizontal). Cada pantalla abre con su pregunta en grande y, a la derecha, sus
controles en píldoras grises; debajo, un tablero de tarjetas. El botón redondo «…» de cada tarjeta abre la tabla con los
datos del gráfico («Ver los datos») y sus fuentes.

**Alertas, Recomendaciones, Operación y Monitoreo consumen la API del reto** (`api_frecuencias`, `/api/v1`) a través de
`cliente_api.py`; en Inicio, la tarjeta **«Respuesta a la pregunta del reto»** lee `GET /api/v1/respuesta`; en Pronóstico,
la sección **«Modelo activo (API)»** lee `GET /api/v1/predictions`, y El modelo lee la importancia del modelo activo
(`GET /api/v1/models/{id}/importance`). Lo demás sale de `datos/`. La clave del tablero es de **analista**: la tarjeta de
Inicio pide el cálculo de la respuesta cuando todavía no está (`POST /api/v1/respuesta/calcular`):

| Variable de entorno | Para qué | Por omisión |
|---|---|---|
| `SOBUSA_API_URL` | URL base de la API | `http://127.0.0.1:8000` |
| `SOBUSA_API_KEY` | Clave que viaja en la cabecera `X-API-Key` (la API fija el rol y el usuario auditado). Con el rol operador se lee todo y se gestionan las alertas; calcular un escenario, ejecutar el ciclo o entrenar un candidato piden analista; activar o revertir modelos y cambiar umbrales, admin. La clave se crea con `scripts/crear_api_key.py` de la API | vacía: sin cabecera |
| `SOBUSA_USUARIO` | Nombre que el tablero muestra y envía en las acciones (con autenticación manda el de la clave) | `operador.dash` |

Ejemplo (PowerShell): `$env:SOBUSA_API_URL="http://127.0.0.1:8000"; $env:SOBUSA_API_KEY="…"; python app.py`. Las
peticiones tienen tiempos cortos (1,5 s para conectar, 8 s para leer) y llevan `X-Correlation-Id dash-…`. La respuesta del
reto es asíncrona (§7.1): `GET /respuesta` solo lee la foto que dejó el ciclo; si responde 404 «sin_calcular», la tarjeta
muestra «Calculando…», pide `POST /respuesta/calcular` (202 con el `execution_id`) y vuelve a consultar cada 3 s, hasta
60 s; si no termina, lo dice y la foto queda guardada para la próxima consulta. Si la API no
responde, esas pantallas muestran «La API no responde en …» y no inventan datos; lo que sale de `datos/` sigue igual. Con la
autenticación encendida, si falta la clave o no es válida (401) las pantallas dicen «La API pide una clave válida» y
qué hacer; si la clave no tiene el rol (403), «La clave no tiene el rol…»: nunca una traza ni un error de consola. Las
exportaciones pasan por el servidor del Dash, así que la clave nunca llega al navegador.

| Pantalla | Qué muestra |
|---|---|
| Inicio · ¿Qué proponemos? | La propuesta en una frase. La tarjeta protagonista, **ahorro en operación al año: +501 M COP** (−1,4 % en el costo de km y conductor), siempre con lo que se juega en pasajes, contado como la decisión que se propone (el ahorro no es ganancia): primero el piloto que lo mide (−51,9 M COP en sus ocho semanas si las salidas nuevas no atraen a nadie y +22,1 si atraen como se midió al quitar; con β = 0,90 serían −70,2, y una regla de parada detiene el piloto si se pierden más pasajeros que salidas en proporción, β = 1: −79,0); si atraen suficientes pasajeros, el plan se aplica y deja entre 0 y +1.600 M COP al año («suficientes» es cerca de un 5 % más de pasajeros por cada 10 % más de salidas; con un 7 %, lo que se midió al quitar, deja entre +1.056 y +1.600 según cómo se haga la cuenta); si atraen menos, no se aplica. Los −2.825 M COP de la contabilidad conservadora van dichos como lo que dejaría aplicar el plan sin medir, no como una cifra suelta. Debajo, el aviso «¿Qué tan probable es cada caso?»: no hay base para una probabilidad, porque esa respuesta nunca se ha medido y las pistas que hay (la literatura y los datos de 2026) caen en la misma franja que el umbral, que va de 4,4 a 5,3 % según la forma de la cuenta y de 3,3 a 6,6 % con todo el rango de β; dice también lo que el piloto puede decir (detecta casi con certeza si atraen pasajeros, pero mide cuánto con un margen ancho frente al umbral, así que lo más probable es que ocho semanas no basten si la respuesta queda cerca de él) y que antes de aplicar el plan falta un cupo de pasajeros por bus. El «…» de la tarjeta trae el umbral en sus tres formas de cuenta y con cada β, el del informe (6,2 %, que es la cuenta de un día de piloto), las pistas y las fuentes. Después, el ahorro en km (+413) y en horas de conductor (+88) en barras rayadas, y lo que cuestan los km y las horas de conductor, que pasa de 36.197 a 35.696 M COP al año. Al lado, las salidas al año: −3.276 (167.856 → 164.580), con las que quita (23.539) y pone (20.263), y la tarjeta de lectura por tipo de día. Después, «El pronóstico se equivoca menos»: la regla manual frente al modelo activo de la API en la prueba de nov–dic 2025, con su intervalo y la cobertura de su banda, y en una nota aparte los experimentos 11 y 12 del informe con su otro protocolo; el servicio: 317 → 267 pasajeros por día sobre la capacidad y 4,43 → 4,30 min de espera; y los accesos a las otras pantallas. Debajo, la tarjeta **«Respuesta a la pregunta del reto»** (`GET /api/v1/respuesta`, por ruta): la pregunta final de la especificación literal, cada cuánto despachar en la hora pico y en el valle frente a lo programado, las salidas del día, los pasajeros esperados con su banda P10–P90, los vehículos en la hora pico frente a la flota, el recaudo esperado y el costo del plan, lo que pide atención inmediata (alertas abiertas con nivel, explicación y qué hacer) y la trazabilidad (modelo, calibración de la banda, fuente del pronóstico del plan, versión de variables, corte, umbrales y ejecución); «Atención inmediata» son las alertas abiertas ahora; el «…» trae la tabla hora por hora y la respuesta se exporta en CSV y XLSX (`GET /api/v1/respuesta/export`). |
| Pronóstico · ¿Cuántos pasajeros habrá? | Dos partes rotuladas. **«Modelo activo (API)»**: con ruta, fecha y horizonte (30, 60 o 120 min), los pronósticos que guarda la API (`GET /api/v1/predictions`, 10 por página con «Anterior» y «Siguiente»): el modelo que los produjo y la versión de su calibración, la banda P10–P90 calibrada frente a lo real cuando ya se conoce (pasajeros validados de 2025, con la misma fracción de cada hora que usa la API), cuántas ventanas cayeron dentro de la banda y, del pronóstico elegido, las variables que más lo mueven (SHAP: factor y efecto en pasajeros, `GET /api/v1/predictions/{id}`); exporta CSV y XLSX (`GET /api/v1/predictions/export`). **«Laboratorio del informe académico: experimento 11 / experimento 12»**: los pronósticos fuera de muestra del informe (siete días de antelación, todo 2025) con su aviso de que no son el modelo de la API ni se comparan con sus cifras. |
| Horario · ¿Cuántos buses y cada cuánto? | Ruta, día, pronóstico y parámetros del plan (costo por bus-hora, costo por km, tarifa, elasticidad, penalidad por sobrecarga, valor de la espera e intervalo máximo). El optimizador corre en vivo y muestra el estado del cálculo, seis fichas (salidas, horas de bus, km, costo de operación, espera estimada y pasajeros sobre la capacidad), las salidas por hora (hoy en escalón gris, el plan en barras azules rayadas con la hora de más salidas sólida y, a elección, el plan que recorta y el oráculo), la carga del punto más lleno, el balance del día con las dos contabilidades (cada saldo dice qué supone: que las salidas nuevas no atraen a nadie, o que atraen lo mismo que se pierde al quitar) y el horario minuto a minuto (CSV descargable o copiable). |
| Despacho en vivo · ¿Qué sale ahora y en qué bus? | Un día de 2025 repetido como si fuera en vivo (la consola de despacho del proyecto; el subtítulo lo dice: muestra lo que vería el despachador y no despacha ni cambia la operación, §3.2), en una sola pantalla sin desplazarse (desde 1100 px de ancho; en el teléfono se apila). Arriba, el día, la ruta, seguir o pausar, la velocidad (tiempo real, x60, x300 o x900) y la barra de la hora (04:00 a 21:00). Debajo, tres columnas: el reloj con el estado de los datos, cuatro fichas (salidas frente al plan, buses en la calle, próximo despacho, pasajeros vistos frente a esperados) y las salidas por hora · el mapa en vivo de las rutas con los buses como puntos (al pasar el puntero: bus, ruta, ocupación y hora de salida) y las alertas del motor debajo · «Próximos despachos» (hora, «en N min», ruta, bus programado y estado: por salir, ajustada con el motivo, atrasada o plan semanal si los datos están caídos) y «Últimos despachos» (los últimos 15 min), o con el selector «Vehículos», la tabla de vehículos en la calle con su ocupación. El reloj corre en el navegador y el mapa solo actualiza los puntos de los buses, así que avanza sin saltos. A la hora del reloj nunca muestra nada que el despachador no pudiera saber. Datos: `sistema_tiempo_real/replay/dias/` del proyecto (353 días) o, sin el proyecto al lado, los 6 días de ejemplo de `datos/despacho/`; lo lee `despacho_datos.py`. |
| Modelo · ¿Qué modelo es y por qué? | Primero **el modelo del producto** (`datos/modelo_producto.json`, que `preparar_datos.py --solo-producto` arma con las evidencias de la API): su `model_id`, el error en la prueba de nov–dic 2025 frente a la regla manual con su intervalo del 95 %, la cobertura de la banda P10–P90 con la calibración v2 (y la v1), la versión anterior de las variables y la declaración honesta de esa prueba (se consultó al elegir; el criterio es la validación y los backtests congelados), y las variables que más pesan leídas de la API. Debajo, **el candidato sin activar** (fv3, con el calendario escolar y universitario): su error en los dos años congelados frente al activo, con el intervalo del 95 % de la diferencia y los meses en que mejora, su error en la misma prueba y por qué no está activo (sale de `candidato_fv3/evaluacion_modelo.json` en la misma ficha). Después, en su sección rotulada, **los experimentos del informe académico** (11: LightGBM; 12: con Chronos-2): el error de 2025, las dos fichas, sus variables y por qué el informe recomendaba el 12, con el aviso de que es otro protocolo. |
| Resultado · ¿Qué gana Sobusa? | De arriba abajo: (1) el ahorro en operación del plan recomendado, +501 M COP al año, siempre junto a lo que se juega en pasajes, en los mismos tres pasos de Inicio (el piloto; si las salidas nuevas atraen suficientes pasajeros, el plan se aplica; si atraen menos, no se aplica) y con el mismo aviso sobre qué tan probable es cada caso, y las fichas del año hoy → con el plan (salidas, horas de bus, km; 23.539 salidas quitadas y 20.263 puestas); (2) dónde se quitan y dónde se ponen salidas, hora por hora, con un control de tipo de día (laboral, sábado, domingo y festivo), y el cambio por ruta; (3) la cascada del ahorro al saldo (pasajes perdidos, pasajes ganados y la diferencia de regla de la simétrica), para el plan que reasigna o el que recorta con el mismo eje; (4) hoy, reasignar y recortar en una tabla, con el párrafo honesto: recortar ahorra más (+3.695 M COP) y deja más caja en las dos contabilidades, pero pierde 1.512 pasajeros netos por día aun en la simétrica y sube la sobrecarga (530) y la espera (4,74 min); (5) las palancas que pagan solas, sin sumarlas; (6) la sensibilidad del saldo a β (central 0,70; equilibrio del plan que recorta 0,53) y lo que falta saber. |
| Alertas · ¿Qué pide atención ahora? (API) | La bandeja de `GET /api/v1/alerts`: filtros por estado, nivel, ruta, código y fechas, 20 por página, en orden de prioridad (crítica → preventiva → informativa y, dentro de cada nivel, la más reciente primero: `orden=prioridad`), con el chip «Escalada» cuando la bitácora registra que la alerta subió de nivel al redetectarse, con nivel y estado en chips con icono y palabra. El detalle trae todos los campos de §5.3 agrupados (identificación con el origen, contexto con la ubicación —coordenadas y enlace al mapa cuando la fuente la trae—, tiempo, evidencia con el puntaje, la probabilidad y el método del puntaje, la tendencia con su pendiente y la serie reciente en un gráfico pequeño con su tabla en el «…», las variables influyentes del modelo —SHAP— ordenadas por su efecto en pasajeros, explicación, recomendación, asignación y comentarios) y la bitácora (`/history`). Acciones reconocer, asignar, comentar, cerrar y descartar (`PATCH /alerts/{id}/status`), activas según las transiciones de la API; el 409 `transicion_invalida` y el 422 se muestran en un aviso. Exporta CSV y XLSX con los mismos filtros (`GET /alerts/export`). |
| Recomendaciones · ¿Cada cuánto debe salir un bus? (API) | Ruta, viabilidad, ejecución y fecha (de `GET /recommendations` y `GET /frequency/executions`). Cifras de la hora pico: buses por hora recomendados frente a los programados, vehículos requeridos frente a la flota disponible y ocupación esperada frente al rango objetivo de los umbrales vigentes. Gráfico del headway recomendado frente a la **frecuencia actual (programada)** por hora, tabla por franja (demanda, P90, buses/h, headways, diferencia, vehículos, ocupación, viable y motivo con la fórmula) y el aviso de las franjas no viables con el motivo de la API. «Calcular escenario» (`POST /recommendations/calculate`, rol analista; demanda, P90, capacidad, ocupación, nivel de servicio y, opcionales, los pesos α, β, γ y δ) pone el resultado al lado de la recomendación vigente y lo explica: la función objetivo de §10.2 término por término (componente, peso, ponderado y la fuente de cada peso: código, `threshold_config vN` o la solicitud), las restricciones con su valor, su límite y su holgura y los límites que mandan, la mezcla de tipologías (§10.1), la frecuencia actual (programada) frente a la recomendada (RF-008) y, si no es viable, el motivo con sus cifras y la mejor aproximación ejecutable (§18). **Plan del día por hora** (`GET /recommendations/plan`: el plan que persiste el ciclo diario con el pronóstico del modelo activo, o el del experimento 12 como opción; si aún no está, 404 «sin_calcular» con la pista): salidas del día frente a las programadas, la hora con más salidas, los vehículos de la hora pico frente a la flota (la ficha muestra `vehiculos_hora_pico`, ⌈ciclo / headway⌉ de §10.3 en la hora más exigente, que puede pasar la flota; los buses en la calle a la vez con el plan, la cifra que la flota limita, vienen en `buses_en_ruta_pico` de la misma respuesta y `definicion_vehiculos` explica las dos), el costo del día por componente, el gráfico de salidas por hora (lo programado en escalón gris, el plan en barras azules) y la tabla hora por hora con los despachos minuto a minuto. Exporta CSV y XLSX. |
| Operación · ¿Cómo está corriendo el sistema? (API) | Cuatro vistas. **Ejecuciones**: marca de agua anterior → nueva, corte, filas leídas y válidas, lo producido y la duración; el detalle con WAPE, cobertura P10–P90 y los errores de calidad filtrables por lote, dimensión y código; «Ejecutar día siguiente» lanza el job y un `dcc.Interval` de 2 s sigue su progreso. **Modelos**: el registro (estado, corte, variables, sha256, WAPE de validación, aprobado por, anterior), la comparación con las líneas base, la auditoría en línea de tiempo y las acciones activar (el error de la API se muestra con su código y su motivo: 409 `activacion_rechazada` si la compuerta de cuatro criterios no aprueba, 409 `requiere_forzar` si el modelo ya fue rechazado o sigue en sombra, 422 `ventana_en_muestra` si la ventana cae dentro de lo que vio el candidato), revertir y entrenar candidato. **Umbrales**: la versión vigente, el historial por umbral y una versión nueva con su motivo (`PUT /thresholds`). **Salud del servicio**: `/health`, `/metrics` (peticiones, errores y p95 aproximado por ruta), alertas nuevas por nivel y el WAPE frente a su tolerancia, con el enlace a Monitoreo. Nada largo bloquea un callback: los jobs se siguen con el Interval y la activación corre en un hilo. |
| Monitoreo · ¿El modelo sigue sirviendo? (API) | El monitoreo del modelo en producción (`GET /api/v1/monitoring`, `/monitoring/policy`, `/thresholds` y `/models`): el estado general con sus motivos; WAPE, MAE y sesgo móviles de la ventana y la cobertura P10–P90, cada uno con sus umbrales versionados y un chip de estado (icono y palabra); la deriva de los datos (PSI de cada variable con su umbral de aviso y de alerta, su estado y si dispara el reentrenamiento); el volumen de predicciones y el % de alertas descartadas; la decisión de reentrenar con cada disparador (periodicidad, degradación, deriva y cobertura), sus motivos y bloqueos; el retador en sombra con sus fechas y los cuatro criterios de la compuerta (o la última compuerta decidida, criterio por criterio), y las últimas filas de monitoreo. Exporta CSV y XLSX (`GET /monitoring/export`). Cada tarjeta trae sus fuentes en el «…». |
| Anexos · ¿Qué más hay, aparte de este tablero? | El tablero es la entrada única y esta pantalla, el material de apoyo que no hace falta abrir para entender la propuesta: primero el informe técnico y el cuaderno, y qué es cada cosa; después, la misma propuesta sin conexión: `app.html` (con la consola de despacho y la vista 3D), a las páginas sueltas y a los documentos del proyecto, si están junto a esta carpeta. |

## Cómo se calcula el horario en vivo

- **Optimizador.** `motor/milp.py` es una copia exacta de `experimentos/D5_optimizacion_milp/milp.py`. Para cada ruta y día elige cuántas salidas hacer en cada hora de 4 a 20 h minimizando operación (bus-hora y km) + espera valorada + sobrecarga esperada + pasajes perdidos o ganados por la elasticidad, con suavidad entre horas y la flota disponible. Se resuelve con CBC (PuLP 2.9).
- **Valores por defecto.** Los de `comun.param_d5()`: 26.400 COP por bus-hora, 1.991 COP por km y 3.182 COP de tarifa neta (costos con fuente, precios 2026), elasticidad 0,5, penalidad 10.000 COP por pasajero sobre la capacidad, espera 7.000 COP por hora, intervalo máximo de 10 min (15 los domingos y festivos).
- **Pronóstico del modelo elegido.** D5 se calibró con el pronóstico de E1, y la carga del punto más lleno de cada hora es una lognormal (mu, s). Para planear con otro modelo se hace lo mismo que `sistema_tiempo_real/motor.py`: se usa su pronóstico como pasajeros previstos y se corre la carga en la misma proporción, hora por hora:
  `c = max(pronóstico del modelo, 1) / max(pronóstico de E1, 1)`, `mu' = mu + log(c)` (s no cambia). Con E1, c = 1.
- **Verificación.** Con el pronóstico «E1 (plan publicado)» y los valores por defecto, el plan coincide hora por hora con `x_corrida_1` de `costos/resultados/d5_reoptimizado_decisiones.parquet` (el plan que reasigna); con 60.000 / 1.500 / 3.000 coincide con `x_D5` de `decisiones_2025.parquet`. La pantalla lo dice con una etiqueta «Reproduce el plan publicado». Comprobado en 5 días × 3 rutas × 2 juegos de costos: 30 de 30.
- **Fichas y balance.** Se cuentan con la demanda que de verdad llegó, con la contabilidad ex post de D5 (`evaluar()` de `experimentos/D5_optimizacion_milp/run.py`, copiada en `motor/evaluacion.py`). «Hoy» son las salidas válidas que hizo Sobusa ese día.
- **Tiempo.** Cada ruta tarda entre 0,2 y 0,6 s; las tres rutas, alrededor de 1 s. Una combinación ya resuelta se reutiliza (la pantalla lo indica).

## Sistema de diseño

El aspecto sigue la referencia que eligió el equipo: el tablero **«Dashboard for payment and business analytics»** de
Outcrowd en Dribbble (<https://dribbble.com/shots/26446179-Dashboard-for-payment-and-business-analytics>). Página gris
claro, tarjetas casi blancas muy redondeadas con borde fino y sombra difusa, navegación arriba con la pestaña activa en
píldora negra, títulos enormes en peso normal, cifras grandes, chips en píldora blanca, barras rayadas con la columna en
foco sólida, barras de progreso rayadas y una tarjeta de lectura con degradado. Letra Inter (incluida en
`assets/fuentes/`, funciona sin internet). `DISENO.md` lo explica entero. Lo esencial:

- **Paleta por roles, validada.** El color solo codifica significado y cada entidad tiene el mismo color en las once
  pantallas: **lo que proponemos** (el híbrido del experimento 12 y el plan que reasigna) en azul vivo `#2457f0` (sólido en foco, rayado
  en el resto de la familia); **hoy, la regla manual y las referencias** en gris `#858585` (rayado o línea gris); **lo
  que pasó** en casi negro `#141414`; **el plan que recorta** en rosa frambuesa `#b8235f`; el contexto en gris claro. Las
  rutas SILENCIO, CRA 54 y CL 72 tienen un trío fijo, solo como muestra junto al nombre. Verde, ámbar y rojo son solo
  para estados y siempre van con icono y palabra. Los conjuntos que se ven juntos se validaron con `validate_palette.js`
  del método dataviz sobre la tarjeta `#fafafa`; los grises claros de la referencia se oscurecieron lo justo para llegar
  a 4,5:1 en texto pequeño y 3:1 en texto grande y marcas.
- **Un solo estilo en las once pantallas.** Los tokens viven en el `:root` de `assets/estilos.css`; `tokens.py` los lee
  y `ui.py` arma con ellos los componentes y la plantilla de Plotly. `paginas/*.py` solo usan componentes y roles, sin
  colores ni tamaños escritos a mano.
- **Cómo se comprueba.** `python verificar_estilo.py` revisa el código sin servidor (CSS sin literales, Python sin
  colores ni tamaños, roles, contraste y paleta); con `--vivo PUERTO` revisa además la app en marcha en Edge sin
  interfaz (errores de consola, tamaños, colores, encabezados, la protagonista con sus fichas de saldo y que nada se salga a
  400 px; necesita Playwright). Termina con código 1 si algo falla. Las cifras las comprueba `verificar_ahorro.py`
  (407 comprobaciones). El recorrido de punta a punta de las once pantallas contra la API (Edge sin interfaz a
  1600×900: consola, desborde, contraste, orden de Tab y foco visible, cada cifra nueva frente a la API y la autenticación
  con clave de operador y con una clave inválida) y sus capturas `dash_<pantalla>.png` están en
  `api_frecuencias/docs/evidencias/tablero/` (`e2e_tablero_completo.txt` y `LEEME.md`).

## Archivos

```
dash_app/
  app.py               entrada: python app.py
  ui.py                piezas de interfaz y plantilla de los gráficos Plotly
  controles.py         selector de día (con los días que tienen datos)
  datos_app.py         lectura de datos/
  paginas/             las once pantallas (inicio, pronostico, horario, despacho, alertas, recomendaciones, operacion,
                       monitoreo, modelo, resultado, enlaces); alertas, recomendaciones, operacion, monitoreo y la tarjeta
                       de la respuesta del reto en inicio leen la API del reto
  cliente_api.py       cliente de la API del reto (SOBUSA_API_URL, SOBUSA_API_KEY, SOBUSA_USUARIO); nunca lanza: (datos, error)
  despacho_datos.py    lee los días de la consola de despacho y arma el estado a la hora del reloj (solo biblioteca estándar)
  motor/               copias del optimizador del proyecto (ver abajo)
  assets/estilos.css   el diseño de la app HTML (tokens de app/tokens.css)
  assets/iconos/       los íconos de app/iconos.js
  datos/               los archivos pequeños que usa la app (los deja preparar_datos.py)
  datos/despacho/      6 días de ejemplo de la consola de despacho (.json.gz) e indice.json, por si falta el proyecto
  preparar_datos.py    copia y extrae esos archivos desde el proyecto completo
  verificar_ahorro.py  comprueba datos/ahorro_anual.json contra los archivos de resultados del proyecto
  requirements.txt     versiones exactas probadas
```

### De dónde sale el motor

| Archivo | Origen | Cambios |
|---|---|---|
| `motor/milp.py` | `experimentos/D5_optimizacion_milp/milp.py` | Ninguno (solo un comentario de origen). |
| `motor/comun.py` | `sistema_tiempo_real/comun.py` | Solo constantes, formato de números y `param_d5()`; los costos con fuente se leen ya calculados de `datos/costos_fuente.json`. |
| `motor/plan_base.py` | `sistema_tiempo_real/plan_base.py` | Lee `datos/insumos_d5_2025.parquet`; permite elegir el pronóstico (como `motor.py`) y el intervalo máximo; resuelve una ruta a la vez y guarda cada combinación ya resuelta. |
| `motor/evaluacion.py` | `evaluar()` de `experimentos/D5_optimizacion_milp/run.py` | Aplicada a un día, sin anualizar. |

### De dónde salen los datos

`python preparar_datos.py` (con el proyecto completo dos carpetas arriba, o `--proyecto RUTA`) vuelve a generar `datos/` (con `--solo-ahorro`, solo `ahorro_anual.json`). No consulta la base de datos ni copia datos personales: todo son agregados por ruta, día y hora. `datos/origen.json` lista el archivo de origen, las filas y el tamaño de cada uno.

| Archivo de `datos/` | Origen en el proyecto |
|---|---|
| `pronosticos_2025.parquet` | Pasajeros reales y pronósticos con 7 días de antelación: `experimentos/E11_modelo_mejorado/predicciones_2025.parquet` (regla manual y experimento 11), `experimentos/E1_lgbm_salida/predicciones_2025.parquet` (experimento 1) y `experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet` (experimento 12, el híbrido; el mismo que usa `app/generar_datos_app.py`). |
| `modelo_producto.json` | El modelo que ejecuta la API (`api_frecuencias/datos/modelos/registro.json`), su error en la prueba de nov–dic 2025 frente a la regla manual con el intervalo bootstrap (`api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.json`) y la cobertura de la banda con las calibraciones v2 y v1 (`…/modelo/calibracion_condicional.json`); cada cifra con su archivo y su clave en `origen`. Se regenera solo con `python preparar_datos.py --solo-producto`. |
| `insumos_d5_2025.parquet` | `experimentos/D5_optimizacion_milp/decisiones_2025.parquet` + oferta de referencia de E1 + capacidad y distancia de `experimentos/D1_optimizacion/parametros_operativos.parquet` + `x_corrida_1` de `costos/resultados/d5_reoptimizado_decisiones.parquet` (las mismas uniones de `sistema_tiempo_real/plan_base.py`). |
| `costos_fuente.json` | `costos/resultados/costos_unitarios.json` y `costos_para_planificador.json`. |
| `cifras_app.json` | `app/datos_app.js` (cada cifra con su archivo y clave de origen). |
| `ficha_modelos.json` | `app/ficha_modelos.json`. |
| `sensibilidad_beta.csv`, `beta_equilibrio.csv` | `simulacion_ahorro/resultados/` y `costos/resultados/`. |
| `ahorro_anual.json` | Las cifras del año de Inicio y «Qué gana Sobusa» (hoy, el plan que reasigna y el que recorta; por ruta, por hora y tipo de día; palancas aparte), cada una con su archivo y su clave en `origen`: `costos/resultados/` (d5_reoptimizado, decisiones, costos, ahorros por escenario, β de equilibrio, línea base), `experimentos/D5_optimizacion_milp/`, `simulacion_ahorro/resultados/` y `experimentos/D6_simulador/`. Trae también `respuesta_equilibrio` (desde qué respuesta de los pasajeros a las salidas que se ponen deja de perder cada plan, en tres formas de cuenta y con los extremos del rango de β), `saldo_respuesta_central_Mcop`, `pistas_respuesta` (lo poco que se sabe de esa respuesta: la literatura que cita `documentos/informe_resultados.md`, Tabla 2, y la asociación de 2026 de `experimentos/E8_validacion_2026/resultados.json`, con su reserva) y `piloto` (lo que deja el piloto si las salidas nuevas no atraen a nadie, con la β central, con la alta y con la pérdida proporcional, β = 1, a partir de la cual una regla de parada lo detiene, de `experimentos/P2_piloto_beta/resultados.json`). Lo comprueba `verificar_ahorro.py`. |

## La app completa desde aquí

Si esta carpeta está dentro del proyecto (o junto a `app.html`), la pantalla «App completa e informe» abre `app.html` y las demás páginas del proyecto a través del mismo servidor (`/proyecto/...`, solo archivos web; nunca `datos/`, credenciales ni archivos de texto). Si `app.html` está en otro lugar, indíquelo antes de arrancar con la variable `SOBUSA_PROYECTO`. Sin servidor, `app.html` también se abre con doble clic.

Para usar otro puerto: `PORT=8060 python app.py` (en PowerShell: `$env:PORT=8060; python app.py`).
