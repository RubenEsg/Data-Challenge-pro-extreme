# Entrega final · ¿Cuántos buses despachar y cada cuánto?

**Data Challenge Pro Extreme – Sobusa 2026** · Machine Learning, Universidad del Norte
**Equipo:** Abrahan Basto Martínez, Rubén Esguerra Fernández y Paula Gómez

> **La propuesta en una frase: no quitar buses, cambiarlos de hora.**
> Un modelo pronostica cuántos pasajeros habrá en cada ruta y hora con una semana de antelación, y un optimizador reparte
> las salidas: menos en el valle y más en los picos, con casi las mismas horas de bus.

<!-- corto_plazo:inicio (bloque generado por pronostico_corto_plazo/escribir_readme.py: no editar a mano) -->
## Correcciones tras la retroalimentación del curso (17 de noviembre de 2026)

La retroalimentación señaló tres faltas de la entrega. Las tres se corrigieron en la carpeta [`pronostico_corto_plazo/`](pronostico_corto_plazo/README.md), que resuelve el problema tal como lo pide la especificación: **el pronóstico de las subidas de los siguientes 30, 60 y 120 minutos por ruta, sentido y segmento**. En el informe y en el cuaderno es la sección P.

| Lo que se señaló | Lo que se hizo | Resultado | Evidencia |
|---|---|---|---|
| Se pronosticaba a siete días por ruta y hora de salida: no es el problema que se pidió, y las cifras no se pueden comparar con las de otros equipos | Cada media hora, de 04:00 a 21:00, se pronostican las subidas de los siguientes 30, 60 y 120 minutos, con MAE, RMSE, WAPE y sMAPE por ruta y franja y frente a las líneas base del enunciado (promedio por día y hora y última semana) | Por ruta, en la prueba: WAPE de **7,34 % frente a 13,18 %** del promedio por día y hora a 60 minutos (diferencia con IC del 95 % de −7,95 a −4,08 puntos); 8,58 % frente a 14,36 % a 30 minutos y 6,63 % frente a 12,22 % a 120 | `pronostico_corto_plazo/resultados/prueba.json` |
| Los modelos se eligieron y se reportaron sobre los mismos meses de 2025 | El protocolo se confirmó en git antes de correr la validación: se entrena con 2023 y 2024, **se elige todo con enero a junio de 2025** y **se reporta una sola vez con julio a diciembre de 2025**, en tres commits ordenados del 17-11-2026: protocolo (`9844dae`, 19:26), validación (`fa04afb`, 20:23) y prueba (`546cffa`, 21:01) | En la validación, el modelo elegido falla 7,58 % por ruta a 60 minutos (el promedio, 16,21 %); en la prueba, que no se usó para elegir nada, 7,34 % (el promedio, 13,18 %) | `pronostico_corto_plazo/PROTOCOLO.md`, `pronostico_corto_plazo/resultados/validacion.json`, `pronostico_corto_plazo/resultados/seleccion.json` y el historial de git |
| El modelo por segmento se entrenó con 37 días: lo espacial no quedó validado | Se asignaron a su segmento las subidas de los tres años (44.871.165) con la regla de Extreme, que reproduce su tabla en los 58 días que la base trae (el 99,975 % de las subidas en el mismo segmento). El modelo por segmento se entrena con más de dos años y se prueba en seis meses | A 60 minutos: por sentido, 10,05 % frente a 16,10 %; por segmento, 37,63 % frente a 43,61 %, en 2.404.780 celdas de segmento e instante. El modelo gana al promedio en 332 de los 384 segmentos con subidas | `pronostico_corto_plazo/panel/verificacion_extreme.json`, `pronostico_corto_plazo/resultados/segmentos_prueba.csv` |

Lo que se conserva y lo que falta:

- **El pronóstico a siete días se conserva** porque es el que usa la programación semanal, pero ya no se presenta como el del enunciado. Con el protocolo nuevo, el modelo que solo usa lo que se sabe una semana antes falla 9,19 % por ruta a 60 minutos en la prueba; con lo observado en el mismo día, 7,34 %.
- **La prueba no es ciega en sentido estricto:** los meses de 2025 se conocían por los experimentos anteriores, con otro objetivo. Ninguna decisión del experimento nuevo usa julio a diciembre.
- **El sentido es una aproximación** (la mitad del ciclo), y se midió cuánto afecta (`pronostico_corto_plazo/panel/revision_sentido.json`).
- **Donde no gana: los domingos corrientes.** Por ruta a 60 minutos, el modelo falla 10,37 % y el promedio por día y hora 9,72 %; la pérdida está en CRA 54 (11,10 frente a 8,93). La ventaja del grupo «domingo o festivo» viene de los festivos, en que el promedio falla 101,05 % y el modelo 10,63 % (`pronostico_corto_plazo/resultados/desglose_domingos_festivos.json`, análisis posterior a la prueba).
- **Un registro imposible en la prueba.** La base trae 28.782 subidas en un solo segmento de CRA 54 en 15 minutos (05-07-2025, 07:45). El protocolo no previó filtrarlo, así que las cifras de la tabla lo incluyen; infla sobre todo el RMSE (303,9 por ruta a 60 minutos). En un análisis posterior, sin los 9 días que toca, el modelo falla 6,91 % y el promedio 12,51 %, con un RMSE de 73,7 (`pronostico_corto_plazo/resultados/sensibilidad_registro_anomalo.json`).
- **Falta llevarlo a la API.** La API sigue pronosticando por hora de salida, y su modelo por segmento es el de 37 días. Integrar este pronóstico es el primer pendiente de `PLAN_EVOLUCION.md` (sección 7).

<!-- corto_plazo:fin -->

## Guía para el jurado

**Empieza aquí: el tablero** (`dash_app/`; en Windows, doble clic en `dash_app/iniciar_dash.bat`, y en cualquier sistema,
los comandos de «Cómo correr el laboratorio Dash»). Es la entrada única: Inicio trae la propuesta, lo que se ahorra, lo que
se juega en pasajes y el piloto que lo mide, y sus pestañas llevan al pronóstico, al horario y al resultado. La app sin
conexión (`app_sobusa/app.html`) y sus páginas sueltas muestran lo mismo con resultados ya calculados: son anexos, y el
tablero los reúne en su pantalla «Anexos».

La especificación v1.5 de Extreme Technologies se revisa en cuatro documentos:

- `MATRIZ_CUMPLIMIENTO.md`: cada requisito (RF, RNF, §4–§15 y los criterios de §16) con su estado y su evidencia.
- `documentos/mapeo_especificacion.md`: cada frase de §1–§3 y §17–§20 con lo que hicimos, la evidencia y la prueba que
  lo comprueba, más la respuesta a la pregunta final. Su sección 0 lista los supuestos (S0 a S15) con quién debe
  validarlos, y su sección 9, las limitaciones declaradas.
- `api_frecuencias/docs/evidencias/README.md`: índice de todas las evidencias, con qué demuestra cada archivo y cómo se
  regenera.
- `documentos/respuesta_pregunta_reto.md`: la respuesta a la pregunta final de la especificación, con sus cifras y su
  trazabilidad. Sus cifras salen de `api_frecuencias/scripts/respuesta_reto.py`, que corre el ciclo diario con el código
  de producción y lee cada respuesta como `GET /api/v1/respuesta`; la evidencia está en
  `api_frecuencias/docs/evidencias/respuesta/`.

### Dónde está cada entregable (§15)

| Código | Entregable | Dónde está |
|---|---|---|
| E01 | Documento ejecutivo | `documentos/E01_documento_ejecutivo.pdf` |
| E02 | Especificación técnica | `documentos/E02_especificacion_tecnica.pdf` |
| E03 | Código fuente | `api_frecuencias/`: código en `app/`, dependencias en `pyproject.toml`, `requirements.txt` y `requisitos_congelados.txt`, pruebas en `tests/` y reporte de SonarQube en `docs/evidencias/sonarqube/` (`resumen.md`: puerta de calidad condición por condición; se repite con `scripts/sonar_local.py`). El historial de desarrollo, commit por commit, está en `HISTORIAL_DESARROLLO.md`, que genera `historial_desarrollo.py` desde el repositorio de desarrollo del equipo. |
| E04 | Base de datos | `api_frecuencias/alembic/versions/` (DDL del esquema `ai_frecuencias`, índices y datos semilla de umbrales). El registro de modelos se siembra desde `api_frecuencias/datos/modelos/registro.json`. |
| E05 | Modelo IA | `api_frecuencias/datos/modelos/hgb_fv2_20250831_s42/` (artefacto y manifiesto con SHA-256). Entrenamiento reproducible con `api_frecuencias/scripts/entrenar.py`; métricas en `api_frecuencias/docs/evidencias/modelo/`. Por segmento y sentido, `api_frecuencias/datos/modelos/segmentos/` (modelo activo `seg_hgb_jerarquico_20230227_s42`), entrenado con `api_frecuencias/scripts/entrenar_segmentos.py` según el protocolo de `api_frecuencias/docs/evidencias/modelo/segmentos_protocolo.md`. El pronóstico de corto plazo que pide el enunciado (30, 60 y 120 minutos por ruta, sentido y segmento) se elige con `pronostico_corto_plazo/validar.py` y se prueba con `pronostico_corto_plazo/probar.py`; sus modelos se vuelven a entrenar con esos dos guiones desde `pronostico_corto_plazo/panel/` y no dejan artefacto en la API. |
| E06 | Prototipo | API (`api_frecuencias/`) y tablero (`dash_app/`: las pantallas Alertas, Recomendaciones, Operación y Monitoreo, la sección «Modelo activo (API)» de Pronóstico y la tarjeta de Inicio con la respuesta del reto consumen la API). Capturas y recorrido en `api_frecuencias/docs/evidencias/tablero/`. |
| E07 | Integración PostgreSQL | `api_frecuencias/docs/integracion_postgresql.md` (consultas de solo lectura, marca de agua, mapa de tablas y EXPLAIN), `api_frecuencias/docs/evidencias/replica/` y `api_frecuencias/docs/hallazgos_extreme.md`. |
| E08 | Pruebas | `api_frecuencias/tests/` (unitarias, integración, contrato, datos/ML, réplica y Testcontainers), `api_frecuencias/k6/` (carga) y `api_frecuencias/docs/evidencias/pruebas/`. Integración continua: `.github/workflows/api_frecuencias.yml` en la raíz del repositorio de entrega (la misma definición está en `api_frecuencias/ci/github_actions_entrega.yml`). Los conteos de la suite, la cobertura y la carga con k6 están en la tabla «Cifras vigentes del backend», más abajo. |
| E09 | Contenedores | `api_frecuencias/Dockerfile`, `api_frecuencias/docker-compose.yml` (más `docker-compose.replicas.yml` y `docker-compose.integracion.yml`) y `api_frecuencias/.env.example`. |
| E10 | Documentación | `api_frecuencias/README.md`, `api_frecuencias/docs/openapi.json` (OpenAPI 3.1: 65 rutas y 69 operaciones, cada una con su rol mínimo y sus errores), `api_frecuencias/docs/manual_tecnico.md`, `api_frecuencias/docs/manual_usuario.md`, `api_frecuencias/docs/despliegue.md` y el índice de evidencias `api_frecuencias/docs/evidencias/README.md`. |
| E11 | Demostración | Video de menos de 5 minutos: `documentos/video/E11_video_demostracion.mp4`, con subtítulos (`.srt`) y guion (`documentos/video/guion.md`); cómo se grabó y se verificó, en `api_frecuencias/docs/evidencias/video/`. Presentación final: `documentos/presentacion_final.pdf` y `documentos/presentacion_final.pptx` (notas del orador en `documentos/notas_orador.txt`). La demostración reproducible está abajo. |
| E12 | Plan de evolución | `PLAN_EVOLUCION.md` |

### La demostración en cinco comandos

Con Python 3.11 o más reciente y Docker Desktop abierto, desde `api_frecuencias/`:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python scripts\verificar_despliegue.py
copy .env.example .env
docker compose -p sobusa_api up -d --build
```

- **`verificar_despliegue.py` (de 15 a 25 minutos).** Levanta una pila aislada desde cero (proyecto `sobusa_limpio`,
  puertos 8010 y 5440, volúmenes propios) y aplica las migraciones 0001 → 0014. Crea las claves de API y corre el ciclo
  completo de §14.2 con `scripts/demo_ciclo_api.py`:
  1. **llegada de información nueva:** carga inicial hasta el 30-08-2025 (49.623 filas), un día nuevo (51 filas) y los
     días hasta el 30-11-2025 (4.641 filas);
  2. **lectura incremental:** cada ejecución muestra su marca de agua anterior y la nueva, y la repetición lee 0 filas;
  3. **evaluación del error** del modelo activo en lo que llegó, con el monitoreo y la decisión de la política;
  4. **modelo candidato** `hgb_fv2_20250930_s42`, con corte 30-09-2025 y solo los datos ya llegados (la política lo
     encola sola por periodicidad, y el script espera ese trabajo en vez de pedir otro igual);
  5. **comparación** en la misma ventana para los dos, 2025-12-01..14, fuera de la muestra del candidato y del activo:
     WAPE 14,108 % del candidato frente a 13,982 % del activo;
  6. **decisión:** la compuerta de cuatro criterios lo rechaza porque no mejora al activo (los otros tres se cumplen), y
     activarlo sin forzar responde 409 `requiere_forzar`. El activo sigue siendo `hgb_fv2_20250831_s42`.

  Después prueba que la API sobrevive a un `docker kill` sin perder ni duplicar datos y lo borra todo al final. Qué
  muestra cada paso y por qué, con la salida de referencia, está en
  `api_frecuencias/docs/evidencias/despliegue/demo_esperado.md`. La salida de la corrida en Docker queda en
  `demo_ciclo_api.txt` de esa misma carpeta, que `verificar_despliegue.py` reescribe en cada corrida, y el arranque
  desde cero, en `arranque_limpio.txt` («Resultado global: OK»). Como el candidato no queda activo, no hay nada que
  revertir; la activación y la reversión se prueban aparte en
  `api_frecuencias/tests/integracion/test_api_integracion.py::test_activacion_controlada_y_reversion` y
  `api_frecuencias/tests/integracion/test_monitoreo_api.py::test_retador_en_sombra_compuerta_y_reversion`.
- **`copy` y `docker compose`.** Dejan la API en http://127.0.0.1:8000 para explorarla con Swagger (`/docs`). Si ya hay
  un `.env`, no lo copie encima: `copy` lo reemplaza. Antes de levantarla, cambie en el `.env` `POSTGRES_PASSWORD` y
  `SEUDONIMO_SECRETO` y cree una clave como dice `api_frecuencias/README.md` («Inicio rápido»).
- **El mismo ciclo sin Docker para la API.** Con la API corriendo en el venv (`uvicorn`, ver «Cómo correrla» en
  `api_frecuencias/README.md`) y una clave de admin en `SOBUSA_API_KEY`:
  `.venv\Scripts\python scripts\demo_ciclo_api.py --base http://127.0.0.1:8000 --revertir` (por omisión,
  `--hasta 2025-08-30 --corte 2025-09-30`). Se verificó el 13-11-2026 contra una base de pruebas nueva y una copia
  temporal de los datos: dos corridas con código 0 (120 s cada una) y la misma salida, con
  el mismo rechazo del candidato. La referencia está en
  `api_frecuencias/docs/evidencias/despliegue/demo_esperado.md`.

Para ver el tablero conectado a esa API, desde `dash_app/`:

```
set SOBUSA_API_URL=http://127.0.0.1:8000
set SOBUSA_API_KEY=<clave>
python app.py
```

y abra http://127.0.0.1:8050. El recorrido por cada pantalla está en `api_frecuencias/docs/manual_usuario.md`.

## Qué hay en esta entrega

| Archivo o carpeta | Qué es | Cómo se abre |
|---|---|---|
| `Informe_tecnico_Sobusa.pdf` | **Informe técnico** (27 páginas): datos, el problema del enunciado (sección P), metodología, resultados, limitaciones, recomendaciones y referencias. | Cualquier lector de PDF. |
| `entrega_final.html` | **Cuaderno final ejecutado**, en HTML: resuelve el problema del enunciado (sección P), entrena el modelo semanal, lo evalúa, resuelve el despacho de un día y comprueba 169 cifras. | Doble clic (navegador). |
| `entrega_final.ipynb` | El mismo cuaderno, con sus salidas. | Jupyter o VS Code. Para volver a ejecutarlo hace falta el proyecto completo (abajo). |
| `dash_app/` | **Laboratorio del modelo** (Dash, Python): el pronóstico y el optimizador corren en vivo. | En Windows, doble clic en `dash_app/iniciar_dash.bat`; en cualquier sistema, `python app.py` (abajo). |
| `app_sobusa/app.html` | **App «Sobusa Despacho»**: nueve pantallas con todo el proyecto, la repetición de un día de 2025 en la consola (sin mandos sobre los buses) y la vista 3D. *Solo en el ZIP completo (`Entrega_final_Sobusa.zip`); no viene en el ZIP ligero.* | Doble clic, en Edge o Chrome, sin internet. |
| `pronostico_corto_plazo/` | **El pronóstico que pide el enunciado**: las subidas de los siguientes 30, 60 y 120 minutos por ruta, sentido y segmento, con el protocolo escrito antes de la validación, la validación, la prueba reservada y las subidas por segmento de 2023 a 2025. | Su `README.md`; para repetirlo, `python validar.py` y `python probar.py --repetir`. |
| `api_frecuencias/` | **Backend del reto** (FastAPI + PostgreSQL 14): ejecución incremental, pronóstico a 30/60/120 min, recomendación de frecuencia y flota, alertas y registro de modelos. | Con Docker, dos comandos (abajo). |
| `MATRIZ_CUMPLIMIENTO.md` · `PLAN_EVOLUCION.md` · `HISTORIAL_DESARROLLO.md` | Cada requisito de la especificación v1.5 con dónde se cumple y su estado; plan de integración, escalabilidad, costos, riesgos, hoja de ruta y adopción; lista de los commits del desarrollo. | Cualquier visor de Markdown. |
| `documentos/` | Documento ejecutivo (E01), especificación técnica (E02), presentación final y video de E11 (`video/`), la respuesta a la pregunta del reto (`respuesta_pregunta_reto.md`) y el mapeo de §1–§3 y §17–§20 de la especificación a la evidencia (`mapeo_especificacion.md`). | Lector de PDF, reproductor de video o visor de Markdown. |
| `informe/` | Fuentes LaTeX del informe, figuras y `compilar.py`. | `python informe/compilar.py` (usa Tectonic). |
| `requirements_cuaderno.txt` | Versiones exactas con que se ejecutó el cuaderno. | `pip install -r requirements_cuaderno.txt` |

**Orden sugerido:**

1. Lo que pide la especificación: `MATRIZ_CUMPLIMIENTO.md` y `documentos/mapeo_especificacion.md`; y el pronóstico tal como lo pide, en `pronostico_corto_plazo/README.md`.
2. El producto: E01 y E02 (`documentos/`), la API con la demostración de arriba y el tablero (`dash_app/`).
3. La parte académica: el informe técnico (10 minutos para el resumen, las tablas 1 y 3 y las recomendaciones) y el
   cuaderno, que es su prueba técnica: cada cifra se calcula ahí mismo o se lee de su archivo de resultados y se
   contrasta. La app sin conexión recorre el proyecto entero con resultados ya calculados; es un anexo del tablero.

## Cómo correr el laboratorio Dash

Hace falta Python 3.11 o más reciente (probado con 3.13 en Windows 11).

**En Windows:** descomprima el ZIP y dé doble clic en `dash_app/iniciar_dash.bat`. La primera vez crea el entorno `.venv`
e instala las dependencias (alrededor de un minuto, con internet); después abre el navegador solo. Para detener la app,
cierre la ventana negra.

**En cualquier sistema**, desde la carpeta `dash_app`:

```
python -m venv .venv
.venv\Scripts\activate              (Windows)
source .venv/bin/activate           (macOS o Linux)
pip install -r requirements.txt
python app.py
```

Abra **http://127.0.0.1:8050**. No necesita internet ni la base de datos (solo el mapa de calles de la pantalla Despacho se carga de internet): usa los 2,3 MB de `dash_app/datos/`. El
solucionador CBC viene dentro de PuLP. Las pantallas del laboratorio son:

- Inicio;
- Pronóstico (con la API, los pronósticos del modelo activo; sin ella, ruta, día y experimento del informe en 2025);
- **Horario en vivo** (el optimizador D5 resuelto en el momento, con los costos, la elasticidad y el intervalo que usted
  elija);
- Despacho en vivo (la repetición de un día de 2025 con el plan; no tiene mandos sobre los buses, como pide §3.2);
- El modelo (primero el modelo activo de la API; después, los experimentos del informe académico);
- Resultado (qué gana Sobusa);
- Anexos (el informe, el cuaderno y, si está la carpeta `app_sobusa/` del ZIP completo, la app sin conexión: material de
  apoyo que no hace falta abrir para entender la propuesta).

Las pantallas **Alertas, Recomendaciones, Operación y Monitoreo**, la sección «Modelo activo (API)» de Pronóstico y la
tarjeta de Inicio con la respuesta a la pregunta del reto consumen la API del reto. Para usarlas, levante la API (abajo) y defina `SOBUSA_API_URL` y
`SOBUSA_API_KEY`. Detalle en `dash_app/README.md` y en `api_frecuencias/docs/manual_usuario.md`.

## Backend del reto (FastAPI + PostgreSQL)

`api_frecuencias/` es el backend que pide la especificación de Extreme Technologies (Python, FastAPI y PostgreSQL 14 con
PostGIS): lee los datos nuevos por marca de agua, valida su calidad (también la de los consolidados de Extreme, que
contrasta con su propia agregación), pronostica la demanda a 30, 60 y 120 minutos con su banda p10-p90, recomienda
headway, buses por hora y vehículos (y dice si la flota alcanza), genera alertas ALT-001 a ALT-010 explicables y
gestionables (con el viaje, el vehículo y el seudónimo del conductor cuando la regla mira un viaje), y registra cada
modelo con su hash para activarlo o revertirlo con auditoría. Un modelo propio reparte el pronóstico de la ruta por
segmento y sentido, una ejecución se puede partir en un trabajo por ruta (con marca de agua y candado por ruta) y los
umbrales, los parámetros del plan, la flota y el ciclo se cambian por la API, versionados, sin recompilar. Guarda todo
en su propio esquema `ai_frecuencias`; por omisión lee los datos del reto ya exportados a Parquet, así que nunca
escribe en la base compartida. Con Docker Desktop abierto, desde `api_frecuencias/`:

```
copy .env.example .env               (cambie POSTGRES_PASSWORD y SEUDONIMO_SECRETO; en macOS o Linux: cp)
python scripts\crear_api_key.py --rol admin --usuario demo      (pegue en API_KEYS del .env la entrada con el hash)
docker compose -p sobusa_api up -d --build
```

Swagger queda en **http://localhost:8000/docs**, y cada petición a `/api/v1` lleva la cabecera `X-API-Key` con la clave
que imprimió el segundo comando. Inicio rápido, tabla de endpoints y ciclo de la demostración en
`api_frecuencias/README.md`; manuales en `api_frecuencias/docs/`; estado de cada requisito en `MATRIZ_CUMPLIMIENTO.md`.

Cifras vigentes del backend, cada una con su archivo en `api_frecuencias/docs/evidencias/`:

| Qué | Resultado | Archivo |
|---|---|---|
| Modelo activo `hgb_fv2_20250831_s42` en la prueba reservada (nov.–dic. 2025) | WAPE 14,77 % (IC95 13,10–16,87) frente a 21,18 % (16,61–26,79) de la regla manual B1 | `modelo/evaluacion_modelo.md` |
| Candidato `hgb_fv3_20250831_s42` (fv2 + calendario escolar y universitario), registrado sin activar | Mejora a fv2 en los dos años congelados: 2024, 15,76 % frente a 16,26 %, y 2025, 14,08 % frente a 14,48 %, con el IC95 de la diferencia entero bajo cero; en la prueba reservada (informativa), 14,36 % (IC95 12,98–16,13) | `modelo/decision_fv3.md` y `modelo/candidato_fv3/evaluacion_modelo.md` |
| Banda P10–P90 con la calibración v2 por bloque horario | Cobertura de 77,82 % (v1: 77,88 %) con un ancho medio de 303,4 pasajeros (v1: 312,9) | `modelo/calibracion_condicional.md` |
| Modelo por segmento y sentido `seg_hgb_jerarquico_20230227_s42` en su prueba (18 a 27-02-2023) | WAPE por segmento y hora de 42,09 % frente a 43,06 % del reparto fijo (IC95 de la diferencia: −1,60 a −0,02 puntos); banda P10–P90 con cobertura de 78,31 % por segmento y 83,40 % por sentido. La tabla de Extreme solo trae subidas por segmento de ene.–feb. 2023, y el error de este modelo en 2025 no está medido; el pronóstico por segmento validado con tres años está en `pronostico_corto_plazo/` | `modelo/segmentos_modelo.md`, `modelo/segmentos_banda_ventanas.json` |
| Volumen de alertas observadas (15-09 a 31-12-2025, 324 días-ruta) | 1,265 por ruta y día en total, con la ALT-002 observada (0,710, con el factor de carga del ciclo) y la ruptura de RF-009 (0,012); las que ya medía la versión anterior (ALT-005 a ALT-009) quedan en 0,543, frente a 6,08 con las reglas anteriores | `alertas/backtest_alertas.md` |
| Volumen de alertas de pronóstico (por hora, mismo periodo) | ALT-001 0,438, ALT-002 0,306, ALT-003 0,164 y ALT-004 0,031 por ruta y día (0,938); con las observadas, 2,203 por ruta y día (`scripts/cifras_vigentes.py`) | `alertas/backtest_alertas_pronostico.md` |
| Revisión doble de 96 alertas | Kappa de 0,943 entre los dos revisores (automatizados) antes de conciliar; precisión reponderada de 0,839 (intervalo 95 %: 0,757–0,882). Falta la validación del área operativa; el kit para que la hagan dos personas del área operativa de Sobusa, a ciegas y sin red, está en `alertas/revision_doble/kit_humano/` | `alertas/revision_doble/conciliacion.json` |
| Ciclo diario completo (con plan del día, foto de la respuesta y serie de la ruptura) | Carga inicial de 49.623 filas en 27,5 s, un día nuevo en 20,7 s y la repetición del mismo día en 0,2 s (13-11-2026, código final: con las alertas observadas de cada día del lote, la foto de variables por segmento y el plan con más detalle) | `rendimiento/ciclo_final.md` |
| Consolidados de Extreme en el ciclo (réplica, solo lectura) | `timbradas_consolidado` se lee por su marca de agua sin falsos errores de calidad y se contrasta con el histórico propio por ruta, día ISO y estacionalidad; las diferencias groseras apuntan a los datos de Extreme (hallazgo H17). Las tablas por segmento no tienen filas de Sobusa (H4): su contraste, que no depende del bloque horario de Extreme (H10), se probó con filas reales de la liquidación de tres viajes en una transacción que se revierte, sin diferencias groseras | `consolidados/contraste_consolidados.md`, `consolidados/segmentos_filas_reales.json` |
| Partición por ruta con dos réplicas (RNF-005) | 6 ejecuciones partidas en 18 trabajos de ruta: rutas distintas a la vez, la misma ruta nunca en paralelo, 0 duplicados y las mismas salidas que sin partir | `cola/replicas_por_ruta.txt` |
| Pruebas | Suite completa final (14-11-2026): 1.770 casos (1.106 unitarias, 217 de integración, 209 de réplica, 197 de contrato y 41 de datos/ML), 0 fallas, 0 errores y 0 omitidas, en una sola sesión, con los procesos reales (`PRUEBA_CAIDA=1`, `PRUEBA_REPLICAS=1` y `PRUEBA_PLANIFICADOR=1`) y las pruebas de escritura en la réplica (`REPLICA_PRUEBAS_ESCRITURA=1`); cobertura de `app/` (con `motor_d5/`) de 95,70 % (14.656 de 15.314 líneas) | `pruebas/suite_final.xml`, `pruebas/coverage_final.xml` (la misma corrida que importa SonarQube) |
| Carga con k6 | Consultas paginadas, corrida del 9-11-2026 con un mes de resultados: p95 de 451,3 ms con 0 % de errores (umbral: 2 s). Con el volumen sembrado desde el ciclo final (`scripts/sembrar_volumen.py`: 1.056 ejecuciones, más de un año del ciclo diario) y 50 usuarios, medido el 13-11-2026 sobre el código final: p95 de 864,1 ms y 0 % de errores (el 9-11-2026, con un año, 627,5 ms). `/segmentos/estadisticas` lee la agregación materializada de la migración 0008: con la API recién arrancada, 20,8 ms la primera petición y 18,3 ms la segunda (antes de la 0008, 8,8 s y 11,9 s); con hasta 50 usuarios sobre la capa de segmentos y un refresco completo en curso, p95 de 372,3 ms (332,4 ms durante el refresco) y 0,03 % de errores (una petición de 3.806; el umbral es 1 %). Ingesta integrada desde la réplica, «ok» con 30 usuarios consultando (p95 de 574,5 ms); la ingesta tardó 225,8 s, más que los 93,8 s del 9-11-2026, sin que la causa esté separada | `rendimiento.txt`, `pruebas/k6_segmentos.txt` (vigente), `pruebas/k6_volumen.txt` y `pruebas/revision_segmentos/` (anteriores) |
| Calidad de código | Puerta de SonarQube «Reto Sobusa v1.5» **aprobada (OK)** en el análisis del 14-11-2026, 00:56, sobre todo el código: 0 vulnerabilidades, 0 bugs, 0 hallazgos bloqueantes y 0 críticos (umbral: 0), duplicación de 0,0 % (umbral: 3 %) y cobertura de 95,7 % (umbral: 85 %); 1 hallazgo de mantenibilidad aceptado con su justificación (la copia literal del solver D5, app/servicios/motor_d5/milp.py) | `sonarqube/quality_gate.json`, `sonarqube/resumen.md` |

## Las cifras principales

### El modelo del producto (la API del reto)

El modelo que corre en la API, y que evalúan E01, E02 y la presentación, es `hgb_fv2_20250831_s42`: gradient boosting
de scikit-learn con pérdida Poisson, cuantiles P10 y P90 y banda calibrada. Pronostica los pasajeros de cada ruta y
hora.

| Ventana de evaluación | Regla manual B1 | Modelo activo `hgb_fv2_20250831_s42` | Archivo |
|---|---|---|---|
| Prueba reservada, nov.–dic. 2025 (3.111 franjas de ruta y hora) | 21,18 % (IC95 16,61–26,79) | **14,77 %** (IC95 13,10–16,87) | `api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.md` |
| Todo 2025, con el modelo congelado al 31-12-2024 (18.615 franjas) | 20,04 % | 14,48 % (IC95 13,78–15,28) | el mismo archivo, sección «Robustez» |

Sobre la prueba reservada, con honestidad: la consultamos al elegir las variables fv2 frente a fv1
(`api_frecuencias/docs/evidencias/modelo/decision_fv2.md`), así que ya no es una prueba «nunca vista». El criterio de
selección fue la validación (sep.–oct. 2025) y los backtests con modelos congelados en 2024 y 2025. La cifra de
nov.–dic. queda como reporte informativo, y pedimos a Extreme un periodo de 2026 como prueba limpia
(`documentos/mapeo_especificacion.md`, sección 6).

**Un modelo mejor, registrado y sin activar.** El candidato `hgb_fv3_20250831_s42` es el mismo modelo con cinco
variables de calendario escolar y universitario (`api_frecuencias/datos/calendario_academico.csv`, cada periodo con
su fuente). Con el mismo protocolo se equivoca menos que fv2 en la validación (12,96 % frente a 13,55 %) y en los
dos años congelados, sobre todo en los recesos escolares (en 2025, de 17,36 % a 15,61 %). No lo activamos en esta
entrega porque cambiaría los pronósticos que usan el ciclo diario, las alertas y las respuestas al reto, medidos con
fv2. La API lo pone en sombra y su compuerta decide (`api_frecuencias/docs/evidencias/modelo/decision_fv3.md`).

### Los experimentos del informe académico

El informe técnico compara 51 modelos. Sus cifras usan otro protocolo, así que no se comparan uno a uno con las del
producto:

| WAPE a 7 días de antelación, todo 2025, reentrenando cada mes (18.615 franjas) | Resultado |
|---|---|
| Regla manual B1 (promedio de las ocho semanas anteriores) | 20,04 % |
| Experimento 1 (primer LightGBM) | 14,40 % |
| Experimento 11 (LightGBM mejorado) | 13,94 % |
| Experimento 12 (híbrido con el modelo fundacional Chronos-2) | 13,62 % |

Por qué difieren de la cifra del producto:

- **La ventana.** Los experimentos miden todo 2025; la prueba del producto mide solo noviembre y diciembre, con
  festivos y Navidad, donde también la regla manual empeora (21,18 % frente a 20,04 %).
- **El protocolo.** Los experimentos se reentrenan cada mes (doce pliegues con origen móvil). El producto es un solo
  modelo congelado en su fecha de corte, como funcionaría en producción hasta que la compuerta apruebe un retador.
- **El horizonte.** Los experimentos pronostican cada franja con 7 días de antelación para armar el horario semanal. El
  producto pronostica la hora con variables de 7 o más días de antigüedad y un ajuste intradía para las ventanas de 30,
  60 y 120 minutos (`api_frecuencias/docs/evidencias/modelo/horizontes.json`).
- **La métrica comparable.** En la misma ventana (todo 2025) y frente a la misma regla manual (20,04 %), el modelo del
  producto congelado da 14,48 %, entre el experimento 1 y el experimento 11.

Los experimentos 11 y 12 no se despliegan. El 12 depende de un modelo fundacional preentrenado (Chronos-2), pesado de
descargar y de correr sin GPU. El producto prefiere un modelo reproducible solo con scikit-learn, con paridad ONNX y
banda calibrada (E02, sección «Decisiones técnicas»). El tablero los muestra como experimentos del informe, aparte del
modelo activo de la API.

### El plan anual de 2025 del informe

| | Hoy (regla manual) | Con el plan del informe |
|---|---|---|
| Salidas válidas por día (tres rutas) | 460 | 451 |
| Horas de bus por día | 1.732 | 1.723 (−0,5 %) |
| Espera media | 4,43 min | 4,30 min |
| Pasajeros por día sobre la capacidad (50 por bus) | 317 | 267 |

El plan que reasigna ahorra poco en operación (+501 M COP al año); lo que decide si paga es cuántos pasajeros se pierden
donde se quitan salidas y cuántos se ganan donde se ponen. Con la elasticidad estimada por observación (β ≈ 0,70, rango
0,55–0,90, sin validar en campo; el plan del día de la API usa 0,5 por prudencia y la sensibilidad está en
`api_frecuencias/docs/evidencias/optimizacion/sensibilidad.md`) el saldo anual va de **−2.825 M COP** (contando solo los pasajeros perdidos: 2.864 al día en riesgo) a **+1.600 M COP** (contando
también los ganados: +946 netos al día). Por eso la recomendación incluye un **piloto de ocho semanas** en CRA 54 y CL 72
que mide β con días sorteados (potencia 0,89; arriesga 22.904 pasajeros, el 0,30 % del año de CRA 54). El plan no se
aplica antes de esa medición: se adopta solo si las salidas añadidas atraen suficientes pasajeros (el tablero, en
Inicio, da el umbral, lo que cuesta el piloto y lo que puede y no puede decir en ocho semanas).

El plan que recorta (quita 31.267 salidas al año y pone 13.519 en otras horas: 9,6 % menos horas de bus) ahorra más
en operación (+3.695 M COP al año) y deja más caja que reasignar en las dos contabilidades: **−1.029 M COP** contando
solo los perdidos (frente a −2.825; deja de pagar con β > 0,53) y **+1.939 M COP** contando también los ganados
(frente a +1.600). Pero aun contando los ganados pierde 1.512 pasajeros netos al día, tiene casi el doble de pasajeros
sobre la capacidad que el plan que reasigna (530 al día frente a 267; hoy, 317) y sube la espera a 4,74 min. Con los
costos con fuente, el optimizador, que también valora la espera y el hacinamiento (con supuestos del equipo), elige
reasignar.

## Lo que hay que saber

- El plan anual de 2025 del informe se calculó con el pronóstico del experimento 1 (14,40 %), no con el del
  experimento 11 ni con el híbrido del experimento 12: el optimizador se construyó antes. Con un pronóstico mejor sería
  algo mejor; el laboratorio Dash permite planear con cualquiera de los cuatro pronósticos. El plan del día de la API,
  en cambio, usa el pronóstico horario del modelo activo (`api_frecuencias/docs/manual_tecnico.md`, sección 7).
- El modelo persona a persona de la vista 3D, que no limita el cupo de cada bus, da saldos más extremos en las dos
  contabilidades (−3.212 M COP contando solo los perdidos y +2.312 contando también los ganados, en los 353 días de 2025
  con GPS, frente a −2.825 y +1.600 del optimizador en los 365 días) y muestra dónde el plan se queda corto: deja 2.742
  personas por día por encima de la capacidad (388 con el horario real). Hace falta una restricción de cupo por bus
  antes de llevar el plan a la calle. La vista 3D está en la app HTML del ZIP completo.
- El backtest en tiempo real (13 de octubre de 2026) y el modelo persona a persona no tuvieron revisor independiente.
- Los pasajeros que ganan los buses añadidos no se han medido; de ellos depende el signo del saldo. Eso mide el piloto.

## Reproducir

Todo se reproduce sin consultar la base del reto, que es compartida y de solo lectura: los datos se exportaron una vez a
Parquet.

**Desde este repositorio**, sin nada más:

- la API, sus pruebas y la demostración del ciclo: «La demostración en cinco comandos», arriba, y
  `api_frecuencias/docs/manual_tecnico.md`, sección 13 (la API trae sus datos derivados en `api_frecuencias/datos/`);
- el laboratorio Dash, con los datos que trae `dash_app/datos/`;
- los documentos de entrega, con `python documentos/compilar.py`, y el informe, con `python informe/compilar.py` (los dos
  usan Tectonic).

**Solo en el proyecto completo** (la carpeta de trabajo del equipo, que trae los experimentos y los datos exportados):

- volver a ejecutar el cuaderno (`python -m nbconvert --to notebook --execute --inplace entrega_final.ipynb`, con
  `requirements_cuaderno.txt`), porque lee los resultados de los experimentos;
- volver a copiar los datos del laboratorio (`dash_app/preparar_datos.py`, que lee la carpeta `experimentos/`);
- volver a exportar las tablas del reto a Parquet (`scripts/exportar_tablas.py`, la única lectura de la base del reto);
- regenerar y comprobar las 202 cifras de la app HTML (`app/generar_datos_app.py`, `app/DATOS.md` y
  `app/verificar_datos_app.py`; en el ZIP completo viajan copias en `app_sobusa/app/`, pero necesitan los resultados
  del proyecto para correr).

Ninguna cifra está escrita a mano: cada una se lee de su archivo de resultados, y el cuaderno contrasta 169 de ellas al
ejecutarse. Semilla 42 en todo el proyecto. Ningún archivo de la entrega trae credenciales ni datos personales de
conductores.
