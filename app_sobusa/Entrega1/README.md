# Data Challenge: Entregable 1 (ETL+EDA+Feature Engineering)

**Sobusa 2026 · Universidad del Norte**

Curso de Machine Learning · Pregrado en Ciencia de Datos · Data Challenge Pro Extreme – Sobusa 2026.

Sobusa opera las rutas **SILENCIO** (`idruta` 2), **CRA 54** (16) y **CL 72** (21) entre Soledad y Barranquilla. El reto pide un modelo que decida **cuántos buses despachar y cada cuánto** según la demanda. Este entregable cubre las tres primeras etapas de ese trabajo con los datos de 2023 a 2025: la **extracción, transformación y carga** de la base de datos del reto (ETL), el **análisis exploratorio** (EDA) y la **ingeniería de variables** que deja lista la tabla de modelado. No entrena modelos ni calcula métricas de pronóstico: el modelado, la optimización del despacho y los costos quedan para las entregas siguientes (ver [Lo que no incluye](#lo-que-no-incluye-este-entregable-y-por-qué)).

## Equipo

| Integrante | Correo |
|---|---|
| Abrahan Basto Martínez | abrahanb@uninorte.edu.co |
| Rubén Esguerra Fernández | esguerrar@uninorte.edu.co |
| Paula Gómez | (correo por confirmar) |

Universidad del Norte, Barranquilla, Colombia. Los tres cuadernos llevan la misma cabecera.

## Orden de lectura

1. `01_etl.ipynb` — de dónde salen los datos y cómo se verificó la extracción.
2. `02_eda.ipynb` — el análisis exploratorio completo (12 secciones, 68 figuras); su sección 8 reúne lo que el curso pide y no estaba junto: estadística descriptiva, faltantes, atípicos, correlaciones, tamaños de efecto, autocorrelación y el diagnóstico de la marca «cancelada».
3. `03_feature_engineering.ipynb` — la tabla de modelado ruta × día × hora, su diccionario, la prueba de fugas, la transformación del objetivo y la partición temporal.

Cada cuaderno tiene su versión `.html`, que se abre en cualquier navegador sin instalar nada. El tablero interactivo `tablero/EDA_visual.html` acompaña al EDA (necesita internet para las librerías y el mapa).

## Contenido de la carpeta

124 archivos (incluido este README), 70,83 MB en total. Los Parquet de la base (`datos/`, unos 742 MB) **no** se incluyen (ver [Datos](#datos-no-incluidos)).

| Ruta | Qué contiene | Tamaño |
|---|---|---|
| `README.md` | Este documento. | — |
| `01_etl.ipynb` / `01_etl.html` | **ETL** ejecutado: 62 celdas (32 de código, todas con salida), 4 figuras, 0 errores. Fuentes, Extract, Transform, Load, validaciones, diagrama del flujo y reproducibilidad. | 0,81 / 1,35 MB |
| `02_eda.ipynb` / `02_eda.html` | **EDA** ejecutado: 262 celdas (118 de código, todas con salida), 68 figuras, 0 errores. Inventario y calidad, operación, demanda, calendario, tablas `timbradas`, análisis espacial GPS, complementos (sección 8: estadística descriptiva, faltantes, atípicos, correlaciones, tamaños de efecto, autocorrelación, marca «cancelada» y decisiones de preprocesamiento), síntesis, reglas de limpieza R1–R14 e implicaciones para el modelado. | 12,06 / 13,29 MB |
| `03_feature_engineering.ipynb` / `03_feature_engineering.html` | **Ingeniería de variables** ejecutada: 59 celdas (44 de código, todas con salida), 11 figuras (con pie numerado «Figura FE-n»), 0 errores. | 1,24 / 1,60 MB |
| `Diccionario de Variables.csv` | Diccionario del esquema de la base entregado con el reto (427 filas columna × tabla, 25 relaciones; copia idéntica a la del proyecto). | 0,03 MB |
| `codigo/` (10 archivos) | Scripts del ETL (copias byte a byte de los originales), módulo de ingeniería de variables, plantilla de credenciales, `requirements.txt` y un `README.md` que documenta cada script, sus funciones y argumentos. Detalle abajo. | 0,12 MB |
| `figuras_etl/` (5 archivos) | 4 PNG del cuaderno 01 (`fig_etl_01_flujo`, `_02_tiempos_por_tramo`, `_03_reglas_limpieza`, `_04_cobertura_gps`) e `inventario_datos.csv` (los 20 Parquet que produce el ETL: origen, filas, columnas, MB, compresión y periodo). | 0,55 MB |
| `figuras_eda/` (70 archivos) | Las figuras exportadas del EDA: 68 PNG de `02_eda`, nombradas `s<sección>_c<celda>_<descripción>.png` (las 13 de la sección 8 son las de los complementos), `indice.csv` (archivo, cuaderno, número de figura, sección, celda, encabezado y descripción) y `extraer_figuras.py`, que las extrae del `.ipynb` con rutas relativas al propio script. | 8,09 MB |
| `figuras_fe/` (11 archivos) | 11 PNG del cuaderno 03 (`fig_fe_01` a `fig_fe_11`: objetivos por año y por ruta, calendario, climatología, ventanas de rezagos, pesos, faltantes, perfil horario, correlaciones, regla manual frente al objetivo y pliegues). | 0,83 MB |
| `tablas/` (14 archivos) | `tabla_modelado.parquet` (55.896 filas × 129 columnas, 10,59 MB), `tabla_modelado_rezagos_corregidos.parquet` (misma tabla con los rezagos sobre el objetivo corregido, 10,73 MB), `diccionario_variables.csv` (129 filas: familia, tipo, definición, fuente, antelación, uso, horizonte, tipo de dato, % de nulos, causa y ejemplo), `tabla_modelado.json` (firma sha256 del módulo y metadatos), `resumen_fe.json` (cifras clave del cuaderno 03) e `insumos/` (9 archivos: calendario escolar, universitario y 2026, días atípicos de E10, climatología Open-Meteo 2013–2022 de E9, el clima observado de E9 que no produce el ETL, el calendario diario de E10 y las correlaciones entre rutas de E6 que contrasta la sección 8 de `02_eda`). | 25,43 MB |
| `tablero/` (6 archivos) | `EDA_visual.html` (tablero interactivo: mapa de subidas, series, calendario, perfiles por hora, salidas, ocupación por tramo y flota) con sus datos `dashboard_datos.js`, `dashboard_salidas.js` y `dashboard_correlaciones.js` (este último reducido a las correlaciones entre rutas de E6, sin resultados de modelos), y los scripts que los generan, `preparar_dashboard.py` y `preparar_salidas.py`. Los enlaces de la versión del proyecto al planificador, la consola y el simulador (entregas posteriores) se retiraron. | 5,42 MB |

### `codigo/`

| Archivo | Qué hace |
|---|---|
| `conexion.py` | Conexión de solo lectura a la base (SQLAlchemy + psycopg2); `consulta(sql)` devuelve un DataFrame. |
| `credenciales_ejemplo.py` | Plantilla de `credenciales.py` con valores ficticios (`HOST`, `PUERTO`, `BASE_DE_DATOS`, `USUARIO`, `CLAVE`). |
| `exportar_tablas.py` | **Extract**: exporta las 15 tablas analíticas a `datos/<tabla>.parquet` por lotes de 100.000 filas y verifica filas exportadas = filas en el servidor (`datos/_exportacion.json`). |
| `agregar_conteo.py` | **Transform en el servidor, 1.ª pasada**: agrega los eventos GPS (`conteo_pasajeros_destino`) por tramos de 20.000 `idprogramacion`: celdas de 0,001° por día, celdas de 0,01° por hora, resumen por viaje y pasos por puntos de control. Reanudable (marcas `.ok`). |
| `consolidar_conteo.py` | Une los parciales de la 1.ª pasada en `conteo_celdas_dia`, `conteo_celdas_hora`, `conteo_viajes` y `conteo_puntos_control`. |
| `agregar_tramos_control.py` | **2.ª pasada**: subidas, bajadas y ocupación por tramo entre puntos de control consecutivos de cada viaje; `--consolidar` produce `conteo_tramos_control.parquet`. |
| `eda_preambulo.py` | **Transform local**: carga los Parquet, construye el calendario (festivos de Colombia con `holidays`, Carnaval de `novedades_viales_fecha`) y define `prog`, `viajes` y `limpios`. |
| `ingenieria_variables.py` | Módulo de la ingeniería de variables (1.293 líneas, 39 funciones, todas con *docstring* NumPy en español): `cargar_viajes`, `agregar_franjas`, `construir_panel`, calendarios, climatología, rezagos sin fuga, pesos, `diccionario_variables`, `prueba_fuga`, `pliegues_mensuales`, `resumen_objetivo_transformacion`, `atipicos_z_modificado`, `comparar_con`. No entrena ningún modelo. `SEED = 42`, `N_JOBS = 2`. |
| `requirements.txt` | 22 paquetes con versión exacta (`pip freeze`, Python 3.13.3), incluidas las dependencias transitivas que condicionan resultados (`patsy`, `python-dateutil`, `tzdata`, `pillow`, `greenlet`); sin librerías de modelado. |
| `README.md` | Documentación de cada script: funciones, argumentos, salidas, tiempos, convenciones de tipos y datos sensibles. |

## Qué muestra cada cuaderno

Todas las cifras de esta sección están tomadas de las salidas ejecutadas de los cuadernos (ninguna se escribió a mano).

**Una misma cifra con dos universos.** Los cancelados son **44.156** en todo `progvehiculos` (01, 02) y **44.152** con salida entre las 4 y las 20 h (01 §3, 02 §8 y 03, que trabajan solo con esa ventana); igual con los cancelados con conteo (39.946 frente a 39.944) y los viajes válidos (520.639 frente a 520.638: el único válido fuera de la ventana salió a las 2:45). «Cancelado» es siempre `cancelada = 'S'` (42 viajes del periodo no son ni válidos ni cancelados), así que los cancelados que corrieron ≥ 20 km son 36.178 y sus pasajeros de 2024, 960.933, en 01, 02 y 03; los «fantasmas» se cuentan entre los válidos sin registro (3.160, 25,6 %). La `quincena` es la misma en 02 y 03 (días 14–16, 29 o más y 1).

### `01_etl.ipynb` — ETL

- **Fuente**: base PostgreSQL + PostGIS en Amazon RDS (44 GB), compartida por todos los equipos y de **solo lectura**; el diccionario del reto tiene 427 filas y 25 relaciones, pero solo 4 columnas con descripción.
- **Extract**: 15 tablas analíticas exportadas el 2026-10-03 (3.405.814 filas, 131,1 MB, 121 s de transferencia); filas exportadas = filas en el servidor = filas del Parquet en las 15.
- **Transform en el servidor**: la tabla de eventos GPS (175.855.828 eventos, 41 GB, un solo índice por `idprogramacion`) se agregó en 125 tramos de 20.000 ids, en dos pasadas (43,5 min y 19,3 min de reloj, 0 errores en los logs), y los parciales se consolidaron en 5 resúmenes (286,5 MB). La corrida completa del ETL duró 73,7 min.
- **Transform local**: calendario con 53 festivos (27 trasladados por la Ley Emiliani) y 12 días de Carnaval; reglas R1–R9 con su embudo de filas (564.837 programados → 520.639 válidos → 490.318 limpios) y la regla R1' de E13: de los 44.152 viajes marcados como cancelados (salida 4–20 h), el 81,9 % recorrió ≥ 20 km con una mediana de 74 pasajeros.
- **Load**: inventario de los 20 Parquet (21.659.095 filas), esquemas con porcentaje de nulos y la lista de columnas sensibles que no se usan.
- **Validaciones**: 8 de 8 comprobaciones críticas superadas (con `assert`) y 2 avisos; subidas GPS frente a `numeropasajeros` difieren un 0,21 % en 499.681 viajes (coinciden en ±2 en el 99,3–99,8 % según la ruta); cobertura GPS mensual mediana del 96,0 %, pero 0 % el último día de cada mes.
- **Reproducibilidad**: comandos, orden y tiempos de cada script; versiones instaladas iguales a `requirements.txt` (comprobado con `assert` sobre los 22 paquetes); semilla 42; comprobación de que `credenciales.py` e `info.txt` no están en el entregable.

### `02_eda.ipynb` — EDA

- Es el análisis exploratorio completo del proyecto (`EDA_Sobusa.ipynb`), reejecutado desde `Entrega1/` con cuatro cambios: localiza `datos/` en la carpeta padre, declara la semilla (`SEMILLA = 42`, propagada a `random` y `numpy`) y la **partición temporal antes de mirar el objetivo** (entrenamiento 2023–2024, 731 días; prueba 2025, 365 días), muestra las tablas con punto de miles y coma decimal, y su sección 11 describe la validación con los 12 pliegues mensuales de 2025 del proyecto y deja la conversión del pronóstico en decisiones de despacho para las entregas posteriores. Los complementos que pide el curso (antes un cuaderno aparte) son ahora su sección 8, y la síntesis, los problemas de calidad y las implicaciones pasan a ser las secciones 9, 10 y 11.
- **Datos**: 564.837 viajes programados, 520.639 válidos (92,2 %), 44.156 cancelados (7,8 %), 490.318 limpios; 1.096 días sin huecos (mediana de 506,5 viajes válidos por día); 30.985 viajes válidos con alguna anomalía (5,95 %): 18.081 duran más de 6 h y 10.785 registran 0 pasajeros.
- **Demanda**: 15,31 M de pasajeros en 2023, 13,99 M en 2024 (−8,6 %) y 12,87 M en 2025 (−8,0 %); CRA 54 aporta el 55,4 %; un viaje típico mueve 77–83 pasajeros; un sábado mueve el 81 % de un laboral y un domingo o festivo el 39–42 %; los festivos entre semana restan 62–65 %, el lunes y martes de Carnaval 61–79 % y los partidos de la Selección 19,6 % en su franja.
- **Operación**: el intervalo programado mediano en laboral es de 3 min en CRA 54, 6 en SILENCIO y 10 en CL 72 (el nominal del catálogo es 5); el 16,3 % de los inicios reales ocurre a menos de 1 min del anterior (buses en pelotón); la vuelta completa dura cerca de 4 h (231,8–249,7 min); operan 201 vehículos distintos por día.
- **Calidad**: la `hora` de las tablas `timbradas` es la hora de **fin** del viaje (correlación 0,999–1,000 con `fechafin`), `estacionalidades_anio` está etiquetada con otra empresa y `timbradas_segmentos` cubre solo 56 días; la sección 10 reúne los problemas de calidad y fija las reglas R1–R9; la sección 11 define la unidad de decisión (ruta × día × hora de salida, 4–20 h), los objetivos (los mismos de la tabla de modelado: `pasajeros_total` e `y_corr` como principales) y la validación temporal.

**Sección 8 de `02_eda.ipynb` — Complementos del EDA**

- **Descriptiva y composición**: de las 73 columnas de `progvehiculos`, 22 están vacías y 16 son constantes (35 con información); de 23 categóricas solo 4 son informativas; pasajeros por viaje: media 81,9, mediana 80, P99 174, máximo 97.199 (error del contador).
- **Faltantes y redundancia**: `numeropasajeros` y `numerobajadas` faltan juntos en 4.345 viajes válidos (0,83 %); `fechafin` falta solo en cancelados (estructural); las cuentas por puerta repiten el conteo en el 99,29 % de los viajes; no hay duplicados de `idprogramacion`.
- **Atípicos**: la regla IQR 1,5× marcaría como atípicos los buses llenos de la tarde (en CRA 54, 1.139 viajes válidos superan los 183 pasajeros, el 93,2 % en día laboral), por eso se mantienen los umbrales de dominio y no se eliminan observaciones (R14).
- **Relaciones (solo con el entrenamiento 2023–2024)**: Pearson frente a Spearman por viaje, por día y entre rutas (las tres rutas se mueven juntas: correlación ≥ 0,96 en niveles); la elasticidad al intervalo estimada con 2023–2024 (2,5, 4,2 y 2,1 pasajeros por minuto) reproduce la de los tres años; tamaños de efecto: por día manda el tipo de día (η² 0,73–0,79) y por franja la hora de salida (η² 0,46–0,51), mientras la lluvia (1,2 %) y la quincena (0,04 %, no significativa) explican casi nada.
- **Series**: la autocorrelación a 7 días (0,62–0,65) supera a la de 1 día (0,31–0,37) y sigue siendo apreciable a 364 días; la semana explica el 63–68 % de la varianza diaria (STL); la serie en niveles no es estacionaria (ADF/KPSS), lo que justifica los rezagos y la validación temporal.
- **Marca «cancelada»**: el 81,9 % de los 44.152 viajes cancelados recorrió ≥ 20 km y llevó 2.849.650 pasajeros en tres años (el 6,3 % del objetivo corregido); el 25,6 % de los viajes válidos «sin registro» son registros fantasma. **Externas**: la lluvia de más de 10 mm baja la demanda entre 1,2 % y 3,1 %, y las vacaciones universitarias entre 7,6 % y 12,8 % (las dos vacaciones juntas, entre 15,8 % y 21,4 %).
- **Decisiones**: tabla hallazgo → decisión con R1–R9 y las nuevas R10 (objetivo corregido, que corrige a R1), R11 (no imputar), R12 (partición temporal, sin fuga), R13 (columnas que entran; `idconductor` excluido) y R14 (atípicos: no se eliminan). Los contrastes con `experimentos/` (calendario diario de E10, lista de días atípicos, correlaciones entre rutas de E6) tienen copia en `tablas/insumos/`; el contraste con la tabla de E1 es opcional.

### `03_feature_engineering.ipynb` — Ingeniería de variables

- **Unidad y tabla**: una fila por ruta × día × hora de salida programada (4–20 h): 55.896 franjas = 3 rutas × 1.096 días × 17 horas, 129 columnas en 17 familias; horizontes h = 7 (77 variables) y h = 1 (92 variables). Toda la lógica está en `codigo/ingenieria_variables.py`; el cuaderno la importa y la orquesta. La sección 2 declara qué reglas del EDA se adoptan tal cual y cuál no (el filtro de distancia 45–80 km de R3: la tabla usa `limpios`, como E1–E13).
- **Objetivos**: `pasajeros_total`, `pasajeros_por_viaje`, `carga_max`, `viajes_validos` y el objetivo corregido `y_corr` (pasajeros de todos los viajes que recorrieron ≥ 20 km, con o sin marca de cancelado): 16.167.991, 14.926.045 y 13.859.620 pasajeros por año frente a 15.305.192, 13.988.686 y 12.872.401 del original (+5,6 %, +6,7 % y +7,7 %: el hueco crece cada año). **Transformación del objetivo**: es un conteo con 2,24 % de ceros reales y razón varianza/media de 489 en el entrenamiento (sobredispersión); `log1p` empeora la asimetría (de 1,40 a −2,96) por los ceros, así que la decisión documentada es no transformarlo y usar una pérdida de conteo (Poisson/Tweedie) ajustada dentro de cada pliegue, con métricas en pasajeros.
- **Calendario, eventos y climatología**: 53 festivos, 12 días de Carnaval, 21 de Semana Santa, 256 días de receso escolar y 385 de vacaciones universitarias (con resoluciones y calendarios oficiales como fuente), 8 días con partido y 8 con otros eventos, climatología mes × hora de Open-Meteo 2013–2022 (anterior al periodo: sin fuga).
- **Rezagos sin fuga**: 52 columnas de rezago (4 objetivos × 13) y 8 totales diarios rezagados (60 en total); cada rezago coincide con el desplazamiento exacto de k días y R5 deja vacías las referencias de los dos días excluidos. La réplica sin corregir (`panel_e1`, `corregir_fallas=False`) reproduce la tabla de E1 con diferencia 0 en 89 columnas comunes; la tabla guardada (V4) reproduce `panel_v4` de E12 en 109 de 109 columnas comunes y difiere de E1 solo en las 18 columnas de rezago de pasajeros que corrige V4.
- **Pesos**: 1.336 filas con peso 0,25 (31 días atípicos no predecibles de E10) y 1.412 con 0,1 (franjas con ≥ 25 % de viajes sin registro); el 95,1 % conserva peso 1. La alternativa automática propuesta en E13 (puntaje z modificado > 3,5 frente a las 4 mismas semanas antes y después) se implementa y compara: coincide con E10 en 12 días (los desplomes de un día), no detecta 19 (la transición al Sibus, con desvíos moderados durante semanas) y añade 22 (sobre todo domingos y vísperas de fin de año); se mantiene la lista de E10 para los pesos.
- **Análisis y prueba de fugas**: la variable más correlacionada con el objetivo es `pasajeros_total_b1`, la regla manual de Sobusa (ρ de Spearman 0,896–0,897; el valor de hace 7 días, 0,848); 56 pares con |ρ| > 0,9; la prueba de perturbación desde 2025-03-10 confirma que ninguna de las 77/92 variables del modelo cambia antes de T + h (h = 7 y h = 1); las cuatro columnas de clima observado quedan fuera de las listas por diseño; los 11 controles se cumplen. No se calcula ninguna métrica de pronóstico.
- **Partición y guardado**: 12 pliegues mensuales de 2025 (18.615 filas de prueba; entrenamiento de 36.821 a 53.855 filas); reconstrucción determinista con diferencia 0 y firma `ec58410b52c82be5` en `tablas/tabla_modelado.json`; el cuaderno copia a `tablas/insumos/` los calendarios, la climatología, el clima observado de E9 y los contrastes de la sección 8 de `02_eda` (de `correlaciones.json` de E6 solo las correlaciones entre rutas).

## Cómo reproducir

### Entorno

Python 3.13.3 (Windows 11) con las versiones exactas de `codigo/requirements.txt` (pandas 3.0.5, numpy 2.5.2, pyarrow 25.0.1, matplotlib 3.11.1, seaborn 0.13.2, holidays 0.105, scipy 1.18.1, statsmodels 0.15.0, jupyter 1.1.1, nbconvert 7.17.1, …; 22 paquetes, sin librerías de modelado). En otro equipo:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r codigo\requirements.txt
```

### Datos (no incluidos)

Los cuadernos **no se conectan a la base de datos**: leen los Parquet de la carpeta `datos/` del proyecto, que buscan en la carpeta del cuaderno y en sus padres (es decir, `..\datos` desde `Entrega1`). Esa carpeta no se incluye en el entregable ni en el repositorio por su tamaño (unos 742 MB, con archivos de más de 100 MB) y porque contiene datos sensibles; por la misma razón (el `.gitignore` excluye cualquier carpeta `datos/`) no hay un `datos/LEEME.md` dentro del entregable y esta sección hace sus veces. Hay dos formas de tenerla:

- **Con acceso a la base** (solo lectura, compartida por todos los equipos): copiar `codigo/credenciales_ejemplo.py` como `credenciales.py` en la raíz del proyecto, completar host, usuario y contraseña, y correr el ETL desde la raíz (unos 74 min en total; ver `codigo/README.md`):

  ```powershell
  $env:PYTHONIOENCODING = "utf-8"
  python exportar_tablas.py                  # 15 tablas, unos 2 minutos
  python agregar_conteo.py                   # 1.ª pasada GPS, 125 tramos, unos 44 minutos; reanudable
  python consolidar_conteo.py                # segundos
  python agregar_tramos_control.py           # 2.ª pasada GPS, unos 20 minutos; reanudable
  python agregar_tramos_control.py --consolidar
  ```

  El ETL es determinista (no usa aleatoriedad): repetirlo deja los mismos archivos. El cuaderno `01_etl.ipynb` también lee los logs (`datos/exportacion.log`, `agregacion.log`, `agregacion_tramos.log`), las marcas `.ok` de `datos/conteo_parciales/` y `conteo_parciales_tramos/`, y `datos/_exportacion.json`.
- **Sin acceso a la base**: pedir al equipo la carpeta `datos/` ya generada (se puede respaldar aparte, por ejemplo con Git LFS o en una nube personal) y colocarla en la raíz del proyecto.

**Clima observado (no lo produce el ETL).** `02_eda` (sección 8) lee `datos/clima_diario.parquet` y `03` lee `datos/clima_barranquilla_2023_2025.parquet`. Los dos los escribe `experimentos/E9_clima/run.py` (función `preparar_clima`) a partir de los JSON de Open-Meteo rastreados en git (`experimentos/E9_clima/clima_open_meteo_raw*.json`; solo descarga si faltan). Como ese script corre además el resto del experimento E9, el entregable incluye una **copia de los dos Parquet en `tablas/insumos/`** (539 KB y 21 KB) que `02_eda` (función `insumo`) y `03` (`ingenieria_variables.ruta_clima`) usan automáticamente cuando `datos/` no los tiene.

**Contrastes con `experimentos/`.** La sección 8 de `02_eda` contrasta sus cifras con `E10_dias_atipicos/{calendario_diario.parquet, dias_atipicos.csv}`, `E6_por_ruta/correlaciones.json` y, de forma opcional, `E1_lgbm_salida/datos_modelado_salida.parquet`; `03` busca los calendarios en `E10_dias_atipicos` y `E11_modelo_mejorado`, la climatología en `E9_clima` y, opcionalmente, las tablas de E1 y E12 para la réplica. Todos los insumos obligatorios tienen copia en `tablas/insumos/` (`03` la regenera al guardar), así que `02_eda` y `03` corren con solo `Entrega1/` y `datos/`; cuando falta un archivo opcional, la comparación se omite y lo dice. `01_etl` solo necesita `datos/`.

### Ejecutar los cuadernos

Desde `Entrega1`, en orden (cada uno es independiente de los demás, salvo que `03` escribe `tablas/` y `figuras_fe/`, y `01` escribe `figuras_etl/`):

```powershell
cd "D:\Ruben\universidad\machine_learning\DATA CHALLENGE\Entrega1"
$env:PYTHONIOENCODING = "utf-8"
Remove-Item Env:MPLBACKEND -ErrorAction SilentlyContinue   # ver la nota de abajo

python -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 01_etl.ipynb
python -m nbconvert --to html 01_etl.ipynb
python -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 02_eda.ipynb
python -m nbconvert --to html 02_eda.ipynb
python -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 03_feature_engineering.ipynb
python -m nbconvert --to html 03_feature_engineering.ipynb

python figuras_eda\extraer_figuras.py      # vuelve a extraer los 68 PNG y el indice.csv de 02_eda (rutas relativas al script)
```

**Nota sobre las figuras.** `02_eda` no fija `%matplotlib inline`: si la variable de entorno `MPLBACKEND` vale `Agg` al ejecutar nbconvert, el kernel no incrusta las figuras en el cuaderno (quedan 0 figuras). Hay que ejecutarlo sin esa variable; `01_etl` y `03` sí la fijan y no se ven afectados.

El tablero se abre con doble clic en `tablero/EDA_visual.html` (carga ECharts y Leaflet desde internet y las teselas de Esri). Sus datos se regeneran desde la raíz del proyecto con `python tablero\preparar_dashboard.py` y `python tablero\preparar_salidas.py` (leen `datos/` y `experimentos/` con rutas relativas a la raíz).

### Tiempos de ejecución

Medidos en los metadatos de ejecución que nbconvert guarda en cada celda (del inicio de la primera al fin de la última), en la reejecución final del 2026-10-11 (`02` incluye desde esta versión los complementos, que antes eran un cuaderno aparte).

| Cuaderno | Tiempo | Figuras | Celdas con error |
|---|---|---|---|
| `01_etl.ipynb` | 18,7 s | 4 | 0 |
| `02_eda.ipynb` | 124,0 s | 68 | 0 |
| `03_feature_engineering.ipynb` | 42,5 s | 11 | 0 |

Los tres cuadernos juntos tardan unos 3 minutos; el ETL completo contra la base, 73,7 min (corrida del 2026-10-03, de las 21:49 a las 23:03).

### Semilla y determinismo

- Semilla global única **42**, declarada en el preámbulo de cada cuaderno (`SEMILLA = 42` en `01` y `02`; `SEED = 42` en `codigo/ingenieria_variables.py` y `03`) y propagada a `random` y `numpy` en los tres. En el EDA solo afecta a la única muestra aleatoria (figura 27); en `03`, a la prueba de perturbación.
- El ETL y la tabla de modelado son deterministas: `03` reconstruye la tabla desde cero y la compara con el Parquet guardado (124 columnas, diferencia máxima 0) y guarda en `tablas/tabla_modelado.json` la firma sha256 del módulo y los tamaños de los Parquet de entrada.
- Números con coma decimal y punto de miles en los textos y en las tablas de los cuadernos (`display.float_format` en español en `02`; `tabla_es` en `03`); todo el código está comentado en español.

## Lo que no incluye este entregable y por qué

Este entregable termina donde empieza el modelado. Quedan para las entregas siguientes, y por eso no aparecen aquí aunque existan en el proyecto:

- **Modelos de pronóstico y sus métricas** (comparación de modelos, líneas base evaluadas, WAPE y métrica de decisión en buses) con los 12 pliegues mensuales de 2025: Entregable 2. Ningún cuaderno entrena un modelo ni reporta un error de pronóstico; `requirements.txt` no incluye librerías de modelado.
- **Optimización del despacho** (cuántos buses y cada cuánto), **costos y ahorros**, el **planificador**, el **simulador** y la **consola de despacho en tiempo real**: entregas posteriores, sobre la tabla de modelado y las reglas de este entregable. La sección 11.6 de `02_eda` solo enumera los insumos que el EDA deja medidos para esa etapa.
- **Los datos crudos** (`datos/`, 742 MB), las **credenciales** de la base (`credenciales.py`, `info.txt`) y cualquier **dato personal**: los cuadernos nunca muestran filas de `progvehiculos` ni de `vehiculos`; `idconductor` aparece únicamente como nombre de columna en las tablas de nulos y de composición, se descarta explícitamente en la tabla de modelado (R13) y las columnas de los equipos a bordo (`modem_*`, `sim_serie`, placas) se listan solo por nombre.

## Pendientes para la siguiente versión

Observaciones de la verificación interna que no se resolvieron en esta ronda (exigen cambios mayores a 30 minutos o tocar material que este entregable no modifica):

- *Docstrings* en los scripts del ETL: solo 3 de sus 16 funciones los tienen. Las copias de `codigo/` son byte a byte con los originales del proyecto (lo comprueba `01_etl` §7.3) y los originales no se tocan en este entregable; la descripción de parámetros y salidas está en `codigo/README.md`.
- Numeración uniforme de figuras y tablas en `02_eda` (los comentarios `# Figura n` reinician en cada sección; el número global está en `figuras_eda/indice.csv`) y numeración de las tablas de `03` (sus figuras ya llevan pie «Figura FE-n»; la sección 8 de `02_eda` numera C1–C13 y C1–C23).
- Un único módulo de formato para `02_eda`: `miles`, `dec` y `pct` se redefinen cinco veces con firmas ligeramente distintas (`pct` recibe proporción en unas y porcentaje en otras).
- Repetir la tabla resumen de efectos de calendario de `02_eda` §5.8 solo con el entrenamiento (la justificación está en la nota inicial; `02_eda` §8.9 y `03` §8 ya recalculan los efectos con 2023–2024).
- Una variable de referencia B3 (perfil histórico ruta × hora × tipo de día × mes) en la tabla de modelado; hoy solo están B1 (`b1_manual`, `*_b1`) y B2 (`*_lag7`).

## Repositorio

Esta carpeta va en `Entrega1/` del proyecto. El `.gitignore` del proyecto excluye `info.txt`, `credenciales.py` y `datos/`; todo lo demás de esta carpeta se versiona.
