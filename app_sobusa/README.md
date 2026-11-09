# Data Challenge Pro Extreme – Sobusa 2026

Análisis de la demanda y la operación de las rutas SILENCIO, CRA 54 y CL 72 de Sobusa (Soledad / Barranquilla), 2023–2025, como base para un modelo que decida **cuántos buses despachar y cada cuánto** según la demanda de cada momento.

## Por dónde empezar

1. `documentos/informe_resultados.md`: el informe ejecutivo (15 minutos de lectura): precisión de los modelos, escenarios de despacho, costos y ahorros, despacho en tiempo real, el mismo día con nuestro plan visto persona a persona, el piloto para medir β, recomendaciones, limitaciones y preguntas abiertas.
2. `app.html`: la app «Sobusa Despacho», una sola aplicación que reúne todo el proyecto en nueve pantallas (Inicio, Demanda, Modelo, Horario, Despacho, Ciudad, Resultado, Piloto y Método) y embebe las cinco páginas interactivas. Se abre con doble clic, sin internet. Ninguna cifra está escrita a mano: `app/generar_datos_app.py` genera `app/datos_app.js` desde los resultados de los experimentos y `app/verificar_datos_app.py` vuelve a leer cada cifra desde su archivo y su clave.
3. `documentos/propuesta_sobusa.md`: la propuesta de dos páginas para la gerencia de Sobusa.

## Cómo está organizado el proyecto

```
README.md                          esta guía
app.html + app/                    la app «Sobusa Despacho» (datos generados y verificados en app/)
EDA_visual.html                    tablero del EDA (datos: dashboard_datos.js, dashboard_salidas.js, dashboard_correlaciones.js)
planificador.html                  planificador de despachos (datos: planificador_datos.js)
consola_despacho.html              consola de despacho en tiempo real (replay de 2025)
vista_3d.html                      vista 3D del mismo día: buses por las calles y personas que suben y bajan
simulador_ahorro.html              simulador de ahorro por fecha real (datos en simulacion_ahorro/)
EDA_Sobusa.ipynb / .html           cuaderno del análisis exploratorio, ejecutado
02_Modelado_demanda.ipynb / .html  cuaderno de pronóstico, ejecutado
03_Despacho_recomendado.ipynb/.html cuaderno de decisión, ejecutado
conexion.py, credenciales_ejemplo.py, eda_preambulo.py   módulos comunes (conexión a la base y preámbulo de los cuadernos)
scripts/                           exportación de la base, agregados GPS, datos del tablero, modelo base, armado de cuadernos
documentos/                        informe, propuesta, estado del arte, investigación internacional, diccionario, notas de la visita
bitacoras/                         planes y bitácoras de las sesiones de trabajo y de la app
experimentos/                      E1–E13, D1–D6, P1, P2: run.py, README.md con verificación, resultados.json, figuras
costos/                            costos con fuente, ahorros y calculadora con fórmulas vivas
simulacion_ahorro/                 simulación de ahorro día a día de 2025 y conductores
sistema_tiempo_real/               motor de despacho en tiempo real, backtest, datos del replay y de la vista 3D
insumos_sobusa/                    lo que mandaron los organizadores el 2 de noviembre de 2026 y su análisis
Entrega1/                          Entregable 1 (ETL + EDA + Feature Engineering), carpeta de entrega cerrada
lib/, mapa_local/, video/          bibliotecas locales, mapa sin internet y videos de respaldo
datos/                             copias Parquet de la base y resúmenes GPS (no se versionan; ver «Datos»)
```

Los cuadernos y las páginas viven en la raíz porque leen `datos/`, `experimentos/`, `lib/` y `app/` con rutas relativas a esta carpeta: los cuadernos se abren y se ejecutan desde aquí, y las páginas se enlazan entre sí y la app las embebe.

## Páginas interactivas y app

| Archivo | Qué es |
|---|---|
| `app.html` + `app/` | **La app «Sobusa Despacho»**: barra lateral con nueve pantallas, cada una una pregunta (¿qué proponemos?, ¿cuántos pasajeros habrá?, ¿qué modelo es y por qué?, ¿qué horario?, ¿qué hacer hoy?, ¿cómo se ve en la ciudad?, ¿cuánto se gana?, ¿cómo lo comprobamos?, ¿cómo se hizo?). Embebe el tablero, el planificador, la consola, la vista 3D y el simulador con un interruptor Hoy / Con el modelo. Cada cifra lleva su archivo, su clave y si la revisó un verificador independiente (`app/DATOS.md` es el inventario legible). Diseño en `app/DISEÑO.md`; plan y bitácora en `bitacoras/plan_app.md`. Guía de una página para el jurado en `app/GUIA_JURADO.md`; pruebas automáticas en Edge sin interfaz y sin internet: `app/probar_app.py` (nueve pantallas × dos anchos: errores, desbordes, h1 y módulos cargados) y `app/probar_paginas.py` (las cinco páginas sueltas). |
| `EDA_visual.html` | **Tablero interactivo** (solo el mapa base necesita internet): mapa de subidas por celda y puntos de control, series diarias, calendario, perfiles por hora, intervalos, buses en ruta, ocupación por tramo y flota. Los datos están en `dashboard_datos.js` (generado por `scripts/preparar_dashboard.py`), `dashboard_salidas.js` (viajes de 2025 para la pestaña Salidas, generado por `scripts/preparar_salidas.py`) y `dashboard_correlaciones.js` (matriz de correlación entre rutas, tomada de `experimentos/E6_por_ruta/correlaciones.json`). |
| `planificador.html` | **Planificador interactivo de despachos** (datos en `planificador_datos.js`, generado por `experimentos/P1_planificador/run.py`): eliges ruta, tipo de día, factor de carga, intervalos, flota, costos y elasticidad, y muestra las salidas recomendadas por hora, los buses en ruta frente a la flota, los costos y el horario minuto a minuto. Por defecto usa los costos con fuente de `costos/` (26.400 COP por bus-hora de conductor, 1.991 COP por km, tarifa neta de 3.182 COP); el selector «Costos» también ofrece el pago por producido y los supuestos de D5, con los que reproduce exactamente la optimización D5. |
| `consola_despacho.html` | **Consola de despacho en tiempo real** (demostración): reproduce como si fueran en vivo cualquiera de los 353 días de 2025 con GPS, en tiempo real (1 s = 1 s) o acelerada hasta x900. Muestra el mapa de los buses en la calle y la lista de despachos en orden con las tres rutas mezcladas: hora exacta, bus, estado y motivo de cada ajuste; también las salidas por hora frente al plan semanal, los pasajeros vistos frente a los esperados y las alertas. El plan semanal es el de D5 con los costos con fuente de `costos/`, el que reasigna salidas en vez de recortarlas, el mismo del planificador y del simulador. Los datos de cada día están en `sistema_tiempo_real/replay/dias/` (unos 126 MB comprimidos, 353 días) y se cargan al elegirlo; no se conecta a Sobusa. |
| `vista_3d.html` | **Vista 3D del replay**: el mismo día de 2025 con edificios, buses en 3D que avanzan por las calles y personas que esperan, suben y bajan según los conteos de cada tramo. Con «Ver» se compara el día real con el mismo día con nuestro plan (modos **Real**, **Plan** y **Los dos**) y el panel «Hoy con el plan» pone las cifras del día y las de todo 2025. Luz según la hora del sol, alertas (buses pegados, llenos, paraderos con cola), modo cine (el día en 60 segundos) y recorrido guiado en seis escenas. Se abre desde la consola («Vista 3D →») en el mismo día y hora y funciona sin internet (`lib/` y `mapa_local/`). Método, verificación y límites en `sistema_tiempo_real/README.md`, sección «Vista 3D». |
| `simulador_ahorro.html` | **Simulador de ahorro por fecha real** (datos y método en `simulacion_ahorro/`): eliges un día de 2025 y compara la operación real con lo que habría programado el modelo; muestra salidas, buses-hora, km, galones, conductores necesarios y el ahorro del día, del mes y del año. Se ajustan el salario por conductor, la forma de pago, las horas por turno, el ACPM, el mantenimiento, la tarifa y la elasticidad, y se ven en rojo los pasajeros que un ahorro pone en riesgo. |

## Cuadernos

| Archivo | Qué es |
|---|---|
| `EDA_Sobusa.ipynb` / `.html` | Análisis exploratorio completo, ejecutado (10 secciones, 55 figuras, 210 celdas). Cada cifra fue contrastada por un revisor independiente y el conjunto pasó por una revisión de coherencia, lenguaje, figuras y crítica experta. |
| `02_Modelado_demanda.ipynb` / `.html` | Pronóstico (secciones 2–11: E1–E6, E9, E10, E11, E8; 59 figuras). Carga los resultados guardados y se ejecuta en minutos. |
| `03_Despacho_recomendado.ipynb` / `.html` | Decisión (secciones 2–9: D1–D4, E7, D5, D6, P1; 43 figuras): frecuencia recomendada, flota, recorridos cortos, regularidad, elasticidad, optimización y simulación. |

Los HTML son exportaciones de Jupyter y se abren en cualquier navegador: sin internet se leen el texto, las tablas y las figuras, pero las fórmulas y los diagramas no se dibujan (MathJax y mermaid vienen de internet). Los cuadernos se ejecutan desde la raíz del proyecto (leen `datos/` y `experimentos/` con rutas relativas).

## Documentos (`documentos/`)

| Archivo | Qué es |
|---|---|
| `metodologia/` | **Sección de metodología del Entregable 2** (LaTeX + `main.pdf`), según la guía del curso: formulación, datos y preprocesamiento, modelo propuesto (LightGBM de Poisson con pesos y rezagos corregidos), entrenamiento, modelos de referencia, protocolo de evaluación, diseño de ablación y disponibilidad; tres figuras en PDF vectorial generadas por `figuras.py`; se compila con `compilar.py` (Tectonic). |
| `informe_resultados.md` | **Empieza por aquí.** Informe ejecutivo en español: precisión de los modelos, escenarios de despacho, costos y ahorros, despacho en tiempo real, el mismo día con nuestro plan visto persona a persona (vista 3D) y su hallazgo, el piloto para medir β, recomendaciones priorizadas para Sobusa, limitaciones y preguntas abiertas. |
| `propuesta_sobusa.md` | **Propuesta para Sobusa** (13 de octubre de 2026): dos páginas para la gerencia con lo que encontramos en sus datos, lo que proponemos (un horario semanal que reasigna en vez de recortar, la consola de despacho primero en modo sombra y un piloto de ocho semanas para medir β), lo que gana Sobusa, lo que necesitamos de la empresa, el piloto en una página, el cronograma de 12 semanas, los indicadores de éxito, los riesgos y lo que entregamos; cada cifra con su fuente al final. |
| `estado_del_arte_despacho_buses.md` | Cómo han resuelto el problema otras ciudades y empresas: 85 hallazgos con fuente verificada (modelos, pronóstico de demanda, control en tiempo real, resultados económicos, contexto colombiano). |
| `investigacion_internacional.md` | 69 hallazgos internacionales con fuente verificada, que complementan el estado del arte: qué modelos de pronóstico funcionan (incluidos TimesFM de Google y Chronos), cada cuánto reentrenar, cómo no perder clientes y cuánto se ha ahorrado en otros países, con casos de América Latina. |
| `Diccionario de Variables.csv` | Diccionario de las tablas de la base de datos (esquema PostgreSQL). |
| `posible_solucion.txt`, `visita_sobusa.txt` | Planteamiento del problema y notas de la visita a Sobusa. |

Presentación (borrador): 17 diapositivas con notas del orador, en una página privada de claude.ai: https://claude.ai/artifact/N27iEuwaCWbmhSL6vZpaFz (se descarga como PowerPoint o PDF; completar los nombres del equipo).

## Bitácoras (`bitacoras/`)

`plan_nocturno.md`, `plan_nocturno_2.md`, `plan_nocturno_3.md` y `plan_nocturno_4.md` son los planes y bitácoras de las sesiones de trabajo (3–4, 5, 6, la noche del 6 al 7 y la del 12 al 13 de octubre): qué se hizo, en qué orden y con qué resultado. `plan_app.md` es el plan y la bitácora de la app (desde el 18 de octubre).

## Carpetas de trabajo

| Carpeta | Qué es |
|---|---|
| `experimentos/` | Experimentos reproducibles (`run.py` en cada carpeta, con `README.md`, `resultados.json`, figuras y tablas). Pronóstico: E1–E5, E6 (una ruta o todas), E9 (lluvia), E10 (días atípicos y calendarios escolares y universitarios, con fuentes), E11 (modelo mejorado y `modelo_final.py`, que pronostica cualquier semana futura), E8 (validación con los datos de 2026), E12 (comparación de 51 modelos con el mismo protocolo: árboles, redes neuronales, modelos fundacionales como TimesFM y Chronos, clásicos y combinaciones; usa un entorno de Python aparte descrito en su `HARNESS.md`; `modelo_final_hibrido.py` es el modelo recomendado para producción, LightGBM con las variables de Chronos-2, y corre en CPU), E13 (cuántos días y franjas tienen datos atípicos y qué limpieza sirve: el objetivo corregido, que cuenta los pasajeros de los viajes marcados como cancelados que sí corrieron, mejora el plan; imputar o depurar más empeora). Decisión: D1–D4, E7 (cuántos pasajeros se pierden al espaciar buses), D5 (optimización con programación entera; `horario_recomendado.csv`), D6 (simulador de la ruta, módulo `simulador.py`), P1 (pruebas del planificador), P2 (diseño del piloto para medir la elasticidad β en la calle: franjas, días alternos sorteados, potencia, simulación, riesgo, calendario y planilla; `run.py --analizar` analiza cada semana del piloto). Cada experimento fue verificado por un agente independiente (sección «Verificación» del README); el protocolo está en `protocolo_evaluacion.md`. |
| `costos/` | **Costos con fuente y ahorros**: costo por km (ACPM, mantenimiento, llantas, lubricantes) y por bus-hora de conductor, línea base 2025 (km, galones, CO2, costo total), ahorro neto de cada escenario de despacho y calculadora `calculadora_ahorros.xlsx` con fórmulas vivas. Explicación y fuentes en su `README.md`. |
| `simulacion_ahorro/` | Simulación de ahorro por fecha real de 2025 (datos del simulador) y análisis de conductores; método y verificación en su `README.md`. |
| `sistema_tiempo_real/` | **Prototipo del motor de despacho en tiempo real**: lee el estado del día sin mirar al futuro, reproduce el plan semanal de D5 (con los costos con fuente de `costos/`), reoptimiza las horas que faltan y entrega las próximas salidas y las alertas (`consultar.py --ruta 16 --fecha 2025-06-03 --hora 07:15`). Backtest en 79 días de 2025, los datos de la consola y de la vista 3D (`generar_replay.py`; `calles.py`, con el modelo «el mismo día con nuestro plan»; `resumen_calles.py`) y verificación independiente en su `README.md`. |
| `insumos_sobusa/` | **Lo que mandaron los organizadores el 2 de noviembre de 2026**: el reporte de flota de Sobusa en versión sin datos personales (`flota_sobusa.csv`: placa, ruta, modelo, marca, clase, carrocería, GPS, sentados y de pie; el `.xls` original no se versiona), el archivo de 40 vehículos, los 8 scripts SQL de Extreme (segmentación de rutas en porciones de 20 cm y timbradas por bloque de 15 min; solo de referencia, no se ejecutan), el estado del último día de cada mes en la base (solo el 31 de enero cargado) y el análisis de la flota (`analisis_flota.md`: la capacidad de 50 de D1 y D5 se sostiene). Su `README.md` dice qué se usó, qué no y qué habría que regenerar cuando carguen los 12 días que faltan. |
| `Entrega1/` | **Data Challenge: Entregable 1 (ETL+EDA+Feature Engineering)**: carpeta de entrega con los cuadernos ejecutados `01_etl.ipynb`, `02_eda.ipynb` y `03_feature_engineering.ipynb` (con sus HTML), el código del ETL y de la ingeniería de variables (`codigo/`, con `requirements.txt`), la tabla de modelado con su diccionario de 129 variables (`tablas/`), las figuras exportadas, su copia del tablero y su propio `README.md`. Se copia tal cual al repositorio formal: no se cambia. Verificado por revisores independientes el 9 de octubre de 2026. |
| `lib/` | Copias locales de las bibliotecas (MapLibre GL, deck.gl, ECharts, Leaflet) y de las fuentes (Barlow Condensed, IBM Plex Sans) que usan las páginas, para que todas abran sin conexión; origen y licencias en su `README.md`. |
| `mapa_local/` | Mapa base sin internet para `vista_3d.html`: el estilo liberty de OpenFreeMap con las teselas vectoriales de Barranquilla y Soledad (zoom 0-14, 22 MB en un solo archivo), los glifos y el sprite; la página lo usa cuando el mapa en línea no responde o al abrirla con `&local=1`. Detalles en su `README.md`. |
| `video/` | Videos de respaldo para la presentación (los tres reproducen el martes 3 de junio de 2025): `un_dia_en_60s.mp4`, `recorrido_guiado.mp4` y `consola_despacho.mp4`, MP4 sin sonido para PowerPoint, grabados en Edge con Playwright por `grabar_videos.py` (el resto en su `README.md`). Pesan entre 9 y 63 MB y no se suben al repositorio: se regeneran con el script. |

**Mapa base y uso sin internet.** Las páginas interactivas (`EDA_visual.html`, `planificador.html`, `simulador_ahorro.html`, `consola_despacho.html` y `vista_3d.html`) cargan sus bibliotecas (Leaflet, ECharts, MapLibre, deck.gl) y sus fuentes (Barlow Condensed, IBM Plex Sans) de `lib/`, copias locales de las mismas versiones que antes venían de los CDN, así que abren sin internet. Los HTML de los cuadernos (`EDA_Sobusa.html`, `02_Modelado_demanda.html`, `03_Despacho_recomendado.html` y los de `Entrega1/`) son exportaciones de Jupyter: sin conexión se leen el texto, las tablas y las figuras, pero las fórmulas y los diagramas no se dibujan (MathJax y mermaid vienen de internet); la copia del tablero de `Entrega1/tablero/` carga sus bibliotecas y fuentes de internet, como dice el `README.md` de esa entrega. Lo único que sigue necesitándolo en las páginas interactivas son las teselas gris claro y gris oscuro de Esri (ArcGIS Online) de los mapas de `EDA_visual.html` y `consola_despacho.html`, que no se pueden guardar en local; cargan al abrir la página con doble clic (las de OpenStreetMap se bloquean desde un archivo local porque la página no envía la cabecera Referer que exige su política de uso, y las de CARTO ahora piden clave). Sin conexión, la consola lo detecta antes de pedirlas (un sondeo con 6 s de tiempo límite), deja el mapa en gris liso con la nota «Sin mapa base: no hay internet» y sigue dibujando las rutas y los buses. Es un uso de demostración con la atribución que pide Esri ("Powered by Esri" y fuentes); si Sobusa usa la consola en su operación diaria, necesita una cuenta de ArcGIS (hay un nivel gratuito) o cambiar de proveedor. `vista_3d.html` usa las teselas vectoriales de OpenFreeMap (datos de OpenStreetMap, con edificios en 3D), que no piden clave y sí cargan desde un archivo local, y cuando no hay internet usa el mapa local de `mapa_local/` (teselas vectoriales de Barranquilla y Soledad guardadas en el proyecto).

## Repositorio (respaldo en GitHub)

El proyecto se respalda en un repositorio privado de GitHub. Por seguridad y tamaño, `.gitignore` deja fuera:
- **Credenciales:** `info.txt` y `credenciales.py`. Los scripts que leen la base importan `credenciales.py` desde la raíz; en otro equipo se copia `credenciales_ejemplo.py` como `credenciales.py` y se completan los datos.
- **Datos crudos del reto:** `datos/` (unos 742 MB, con archivos de más de 100 MB). Se regeneran desde la base con los scripts de abajo, o se pueden respaldar aparte (por ejemplo con Git LFS o en una nube personal).
- **Datos personales:** `simulacion_ahorro/resultados/horas_por_conductor_mes.csv` y `conductor_dia_2025.parquet` (identificadores de conductores; se regeneran con `simulacion_ahorro/analisis_conductores.py`) y `insumos_sobusa/rptVehiculos338.xls` (nombres, cédulas y teléfonos; de él solo se deriva `flota_sobusa.csv`).
- **Cachés y pesados:** `sistema_tiempo_real/cache/` (`preparar_cache.py`, unos 10 s), `__pycache__`, los videos de `video/` y las capturas de prueba de la app.

## Datos (`datos/`)

La base de datos original (PostgreSQL + PostGIS en Amazon RDS, 44 GB, compartida y de **solo lectura**) no se descarga completa. En `datos/` quedan:

- `<tabla>.parquet`: copia completa de las 15 tablas analíticas (viajes, rutas, vehículos, agregados de Sobusa, catálogos). `_exportacion.json` registra filas exportadas y confirma que coinciden con el servidor.
- `conteo_celdas_dia.parquet`, `conteo_celdas_hora.parquet`, `conteo_viajes.parquet`, `conteo_puntos_control.parquet`, `conteo_tramos_control.parquet`: resúmenes de la tabla de 176 millones de eventos GPS (`conteo_pasajeros_destino`), calculados en el servidor por tramos de viajes y cubriendo el 100 % de los eventos. Los parciales por tramo están en `conteo_parciales/` y `conteo_parciales_tramos/`.

## Módulos comunes y scripts (`scripts/`)

En la raíz quedan los tres módulos que todo lo demás importa o ejecuta desde aquí:

| Módulo | Función |
|---|---|
| `conexion.py` | Conexión a la base de datos desde Python (`consulta(sql)` devuelve un DataFrame). |
| `credenciales_ejemplo.py` | Plantilla de `credenciales.py` (host, puerto, usuario, clave, base). |
| `eda_preambulo.py` | Carga y limpieza común de los cuadernos: define `prog`, `viajes`, `limpios`, catálogos, festivos y días de Carnaval. Se ejecuta desde la raíz: `exec(open("eda_preambulo.py", encoding="utf-8").read())`. |

Los scripts de preparación están en `scripts/` y se lanzan desde la raíz (`python scripts/<nombre>.py`); cada uno encuentra la raíz por su propia ruta, así que también funcionan desde otra carpeta.

| Script | Función |
|---|---|
| `exportar_tablas.py` | Exporta las tablas analíticas a Parquet y verifica el número de filas. |
| `agregar_conteo.py` | Primera pasada sobre los eventos GPS: celdas de 110 m por día, celdas de 1,1 km por hora, resumen por viaje (ocupación máxima) y pasos por puntos de control. Reanudable. |
| `consolidar_conteo.py` | Une los parciales de la primera pasada en los cuatro Parquet finales. |
| `agregar_tramos_control.py` | Segunda pasada: subidas, bajadas y ocupación por tramo entre puntos de control consecutivos de cada viaje (`--consolidar` une los parciales). |
| `preparar_dashboard.py` | Genera `dashboard_datos.js` (y `datos/dashboard_datos.json`) para el tablero, solo desde los Parquet locales. |
| `preparar_salidas.py` | Genera `dashboard_salidas.js` (todas las salidas válidas de 2025) para la pestaña Salidas del tablero. |
| `modelado_base.py` | Primera prueba rápida del modelo (un solo corte de prueba, por hora de abordaje). Sus cifras no son comparables con las de los experimentos; la comparación válida está en `experimentos/` (protocolo de 12 pliegues mensuales de 2025): regla manual de promedios WAPE 20,0 % frente a 14,4 % de LightGBM a una semana de anticipación. |
| `construir_notebook.py`, `construir_notebook_generico.py` | Ensamblan y ejecutan los cuadernos a partir de secciones (JSON) y el preámbulo; se conservan por reproducibilidad. |

## Cómo reproducir

```powershell
pip install pandas pyarrow psycopg2-binary sqlalchemy matplotlib seaborn holidays jupyter nbformat nbconvert
python scripts/exportar_tablas.py              # tablas analíticas (unos 3 minutos)
python scripts/agregar_conteo.py               # primera pasada GPS (unos 40 minutos, reanudable)
python scripts/consolidar_conteo.py
python scripts/agregar_tramos_control.py       # segunda pasada GPS (unos 15 minutos)
python scripts/agregar_tramos_control.py --consolidar
python scripts/preparar_dashboard.py           # datos del tablero (unos minutos)
python scripts/preparar_salidas.py
```

Los módulos de costos y de tiempo real no se conectan a la base de datos; usan los Parquet de `datos/` y las salidas de los experimentos:

```powershell
$env:PYTHONIOENCODING = "utf-8"; $env:MPLBACKEND = "Agg"
python costos/modelo_costos.py                 # costos, ahorros, figuras y calculadora (segundos)
python costos/reoptimizar_d5.py                # opcional: D5 con los costos nuevos (unos 17 minutos)
python sistema_tiempo_real/preparar_cache.py   # caché del motor (unos 10 segundos)
python sistema_tiempo_real/calibrar_nowcast.py
python sistema_tiempo_real/backtest.py         # backtest en 79 días de 2025 (unos 11 minutos con 2 procesos de prioridad baja)
python sistema_tiempo_real/generar_replay.py   # datos de la consola de despacho (6 días de ejemplo, unos 2 minutos)
python sistema_tiempo_real/generar_replay.py --por-dia --baja-prioridad --procesos 3   # los 353 días de 2025 (unas 2 horas; se retoma)
python sistema_tiempo_real/calles.py --todos --procesos 3   # buses por las calles y el mismo día con nuestro plan (353 días, unos 6 minutos)
python sistema_tiempo_real/resumen_calles.py   # suma de todo 2025 para la vista 3D (segundos)
python simulacion_ahorro/analisis_conductores.py   # conductores 2025 (unos 20 segundos)
python simulacion_ahorro/simulacion_por_fecha.py   # simulación de ahorro por fecha y datos del simulador (unos 30 segundos)
python app/generar_datos_app.py                # datos de la app desde los resultados
python app/verificar_datos_app.py              # vuelve a leer cada cifra desde su archivo (debe terminar sin fallos)
python app/probar_app.py                       # prueba de humo de la app en Edge sin interfaz y sin internet (9 pantallas × 2 anchos, un minuto)
python app/probar_paginas.py                   # prueba de humo de las cinco páginas sueltas (unos 15 segundos)
```

La comparación de modelos (`experimentos/E12_comparacion_modelos/`) necesita un entorno de Python aparte con XGBoost, CatBoost, PyTorch, neuralforecast, Chronos, TimesFM, Prophet y statsforecast; las versiones están en `requisitos_e12.txt` y las instrucciones en `HARNESS.md`.

Para trabajar con los datos en un notebook propio basta con ejecutar el preámbulo desde la raíz:

```python
exec(open("eda_preambulo.py", encoding="utf-8").read())
viajes.groupby(["ruta", "hora_salida"])["numeropasajeros"].mean()
```

## Reglas de limpieza adoptadas

- `viajes`: finalizados y no cancelados (520.639 de 564.837).
- `limpios` (para promedios por viaje): además, duración entre 30 y 360 minutos y entre 1 y 300 pasajeros (490.318).
- El calendario de festivos se construye con el paquete `holidays` (Colombia) y los días de Carnaval con `novedades_viales_fecha`, porque `estacionalidades_anio` no tiene fechas verificadas para Sobusa.
- La hora de las tablas `timbradas` es la **hora de fin del viaje**, no la de abordaje.
