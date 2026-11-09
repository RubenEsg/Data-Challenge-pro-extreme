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

## Las siete pantallas

Arriba, la barra de navegación con las siete pestañas (la activa en píldora negra). Cada pantalla abre con su pregunta en
grande y, a la derecha, sus controles en píldoras grises; debajo, un tablero de tarjetas. El botón redondo «…» de cada
tarjeta abre la tabla con los datos del gráfico («Ver los datos») y sus fuentes.

| Pantalla | Qué muestra |
|---|---|
| Inicio · ¿Qué proponemos? | La propuesta en una frase. La tarjeta protagonista, **ahorro en operación al año: +501 M COP** (−1,4 % del costo), siempre con sus dos saldos del año con β = 0,70 (−2.825 con la contabilidad conservadora y +1.600 con la simétrica: el ahorro no es ganancia), el ahorro en km (+413) y en horas de conductor (+88) en barras rayadas, y lo que cuestan los km y las horas de conductor, que pasa de 36.197 a 35.696 M COP al año. Al lado, las salidas al año: −3.276 (167.856 → 164.580), con las que quita (23.539) y pone (20.263), y la tarjeta de lectura por tipo de día. Después, el error de la regla manual 20,04 % → modelo final 13,94 % → híbrido 13,62 %; el servicio: 317 → 267 pasajeros por día sobre la capacidad y 4,43 → 4,30 min de espera; y los accesos a las otras pantallas. |
| Pronóstico · ¿Cuántos pasajeros habrá? | Ruta (o las tres), día de 2025 y modelo (modelo final E11 o híbrido E12): pasajeros reales frente a pronosticados hora por hora (el modelo en barras azules rayadas, la hora pico sólida con su banda, lo real en negro y la regla manual punteada en gris; la casilla «Comparar con el otro modelo»), la tarjeta del día elegido (error del día y de la semana, pasajeros del día), la serie diaria del mes, el error del mes y la lectura del año. Son pronósticos **fuera de muestra**: cada mes se pronosticó con un modelo entrenado solo con los días anteriores a ese mes, con 7 días de antelación. |
| Horario · ¿Cuántos buses y cada cuánto? | Ruta, día, pronóstico y parámetros del plan (costo por bus-hora, costo por km, tarifa, elasticidad, penalidad por sobrecarga, valor de la espera e intervalo máximo). El optimizador corre en vivo y muestra el estado del cálculo, seis fichas (salidas, horas de bus, km, costo de operación, espera estimada y pasajeros sobre la capacidad), las salidas por hora (hoy en escalón gris, el plan en barras azules rayadas con la hora de más salidas sólida y, a elección, el plan que recorta y el oráculo), la carga del punto más lleno, el balance del día con las dos contabilidades y el horario minuto a minuto (CSV descargable o copiable). |
| Despacho en vivo · ¿Qué sale ahora y en qué bus? | Un día de 2025 repetido como si fuera en vivo (la consola de despacho del proyecto), en una sola pantalla sin desplazarse (desde 1100 px de ancho; en el teléfono se apila). Arriba, el día, la ruta, seguir o pausar, la velocidad (tiempo real, x60, x300 o x900) y la barra de la hora (04:00 a 21:00). Debajo, tres columnas: el reloj con el estado de los datos, cuatro fichas (salidas frente al plan, buses en la calle, próximo despacho, pasajeros vistos frente a esperados) y las salidas por hora · el mapa en vivo de las rutas con los buses como puntos (al pasar el puntero: bus, ruta, ocupación y hora de salida) y las alertas del motor debajo · «Próximos despachos» (hora, «en N min», ruta, bus programado y estado: por salir, ajustada con el motivo, atrasada o plan semanal si los datos están caídos) y «Últimos despachos» (los últimos 15 min), o con el selector «Vehículos», la tabla de vehículos en la calle con su ocupación. El reloj corre en el navegador y el mapa solo actualiza los puntos de los buses, así que avanza sin saltos. A la hora del reloj nunca muestra nada que el despachador no pudiera saber. Datos: `sistema_tiempo_real/replay/dias/` del proyecto (353 días) o, sin el proyecto al lado, los 6 días de ejemplo de `datos/despacho/`; lo lee `despacho_datos.py`. |
| Modelo · ¿Qué modelo es y por qué? | El error de la regla manual, el primer modelo (E1), el modelo final (E11) y el híbrido (E12) en barras, con la lectura de la diferencia; la ficha de los dos modelos (qué son, error en 2025 y en 2024, sesgo, variables); qué variables pesan más; y por qué se recomienda el híbrido. |
| Resultado · ¿Qué gana Sobusa? | De arriba abajo: (1) el ahorro en operación del plan recomendado, +501 M COP al año, siempre junto a sus dos saldos (−2.825 con la contabilidad conservadora y +1.600 con la simétrica), y las fichas del año hoy → con el plan (salidas, horas de bus, km; 23.539 salidas quitadas y 20.263 puestas); (2) dónde se quitan y dónde se ponen salidas, hora por hora, con un control de tipo de día (laboral, sábado, domingo y festivo), y el cambio por ruta; (3) la cascada del ahorro al saldo (pasajes perdidos, pasajes ganados y la diferencia de regla de la simétrica), para el plan que reasigna o el que recorta con el mismo eje; (4) hoy, reasignar y recortar en una tabla, con el párrafo honesto: recortar ahorra más (+3.695 M COP) y deja más caja en las dos contabilidades, pero pierde 1.512 pasajeros netos por día aun en la simétrica y sube la sobrecarga (530) y la espera (4,74 min); (5) las palancas que pagan solas, sin sumarlas; (6) la sensibilidad del saldo a β (central 0,70; equilibrio del plan que recorta 0,53) y lo que falta saber. |
| Enlaces · ¿Dónde está el resto del proyecto? | Enlaces a `app.html` (con la consola de despacho y la vista 3D), a las páginas sueltas y a los documentos del proyecto, si están junto a esta carpeta. |

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

- **Paleta por roles, validada.** El color solo codifica significado y cada entidad tiene el mismo color en las seis
  pantallas: **lo que proponemos** (el híbrido E12 y el plan que reasigna) en azul vivo `#2457f0` (sólido en foco, rayado
  en el resto de la familia); **hoy, la regla manual y las referencias** en gris `#858585` (rayado o línea gris); **lo
  que pasó** en casi negro `#141414`; **el plan que recorta** en rosa frambuesa `#b8235f`; el contexto en gris claro. Las
  rutas SILENCIO, CRA 54 y CL 72 tienen un trío fijo, solo como muestra junto al nombre. Verde, ámbar y rojo son solo
  para estados y siempre van con icono y palabra. Los conjuntos que se ven juntos se validaron con `validate_palette.js`
  del método dataviz sobre la tarjeta `#fafafa`; los grises claros de la referencia se oscurecieron lo justo para llegar
  a 4,5:1 en texto pequeño y 3:1 en texto grande y marcas.
- **Un solo estilo en las siete pantallas.** Los tokens viven en el `:root` de `assets/estilos.css`; `tokens.py` los lee
  y `ui.py` arma con ellos los componentes y la plantilla de Plotly. `paginas/*.py` solo usan componentes y roles, sin
  colores ni tamaños escritos a mano.
- **Cómo se comprueba.** `python verificar_estilo.py` revisa el código sin servidor (CSS sin literales, Python sin
  colores ni tamaños, roles, contraste y paleta); con `--vivo PUERTO` revisa además la app en marcha en Edge sin
  interfaz (errores de consola, tamaños, colores, encabezados, la protagonista con sus dos saldos y que nada se salga a
  400 px; necesita Playwright). Termina con código 1 si algo falla. Las cifras las comprueba `verificar_ahorro.py`
  (342 comprobaciones).

## Archivos

```
dash_app/
  app.py               entrada: python app.py
  ui.py                piezas de interfaz y plantilla de los gráficos Plotly
  controles.py         selector de día (con los días que tienen datos)
  datos_app.py         lectura de datos/
  paginas/             las siete pantallas (inicio, pronostico, horario, despacho, modelo, resultado, enlaces)
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

`python preparar_datos.py` (con el proyecto completo dos carpetas arriba, o `--proyecto RUTA`) vuelve a generar `datos/`. No consulta la base de datos ni copia datos personales: todo son agregados por ruta, día y hora. `datos/origen.json` lista el archivo de origen, las filas y el tamaño de cada uno.

| Archivo de `datos/` | Origen en el proyecto |
|---|---|
| `pronosticos_2025.parquet` | Pasajeros reales y pronósticos con 7 días de antelación: `experimentos/E11_modelo_mejorado/predicciones_2025.parquet` (regla manual y modelo final), `experimentos/E1_lgbm_salida/predicciones_2025.parquet` (E1) y `experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet` (híbrido, el mismo que usa `app/generar_datos_app.py`). |
| `insumos_d5_2025.parquet` | `experimentos/D5_optimizacion_milp/decisiones_2025.parquet` + oferta de referencia de E1 + capacidad y distancia de `experimentos/D1_optimizacion/parametros_operativos.parquet` + `x_corrida_1` de `costos/resultados/d5_reoptimizado_decisiones.parquet` (las mismas uniones de `sistema_tiempo_real/plan_base.py`). |
| `costos_fuente.json` | `costos/resultados/costos_unitarios.json` y `costos_para_planificador.json`. |
| `cifras_app.json` | `app/datos_app.js` (cada cifra con su archivo y clave de origen). |
| `ficha_modelos.json` | `app/ficha_modelos.json`. |
| `sensibilidad_beta.csv`, `beta_equilibrio.csv` | `simulacion_ahorro/resultados/` y `costos/resultados/`. |
| `ahorro_anual.json` | Las cifras del año de Inicio y «Qué gana Sobusa» (hoy, el plan que reasigna y el que recorta; por ruta, por hora y tipo de día; palancas aparte), cada una con su archivo y su clave en `origen`: `costos/resultados/` (d5_reoptimizado, decisiones, costos, ahorros por escenario, β de equilibrio, línea base), `experimentos/D5_optimizacion_milp/`, `simulacion_ahorro/resultados/` y `experimentos/D6_simulador/`. Lo comprueba `verificar_ahorro.py`. |

## La app completa desde aquí

Si esta carpeta está dentro del proyecto (o junto a `app.html`), la pantalla «App completa e informe» abre `app.html` y las demás páginas del proyecto a través del mismo servidor (`/proyecto/...`, solo archivos web; nunca `datos/`, credenciales ni archivos de texto). Si `app.html` está en otro lugar, indíquelo antes de arrancar con la variable `SOBUSA_PROYECTO`. Sin servidor, `app.html` también se abre con doble clic.

Para usar otro puerto: `PORT=8060 python app.py` (en PowerShell: `$env:PORT=8060; python app.py`).
