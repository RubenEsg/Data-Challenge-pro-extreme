# Evidencias de las pruebas y de la integración continua

Requisitos que cubren: §14.1 (niveles de prueba), §14.2 «Calidad del código: las pruebas automatizadas pasan en integración continua» y «se entrega su reporte de ejecución», RNF-007, RNF-013 (análisis estático) y RNF-014.

## Cómo corre la integración continua

El flujo de GitHub Actions es `.github/workflows/api_frecuencias.yml` en el repositorio del proyecto y `ci/github_actions_entrega.yml` en el repositorio de entrega (el mismo flujo, con `api_frecuencias/` en la raíz). Corre en Python 3.11 y 3.13, en una máquina limpia de Ubuntu 24.04 con PostGIS 14-3.4 como servicio:

1. `ruff check .` sobre todo el repositorio de la API.
2. `bandit -r app scripts -ll` (los `# nosec` llevan su motivo después de un segundo `#`).
3. Migraciones desde cero: `alembic upgrade head`, `downgrade base` y otra vez `upgrade head`.
4. `pytest` con cobertura de `app/` (incluido el motor D5) mayor o igual a 85 % y reporte junit.
5. OpenAPI sin deriva: `docs/openapi.json` igual al que genera el código.
6. Un segundo job mata la API a mitad de una ejecución y comprueba que se retoma (RNF-001, `tests/integracion/test_caida.py`), y deja correr el planificador cada minuto para comprobar que la ejecución programada procesa solo lo nuevo (§14.2, `tests/integracion/test_planificador_programado.py`).

`python scripts/ci_local.py` repite los pasos 1 a 5 en local con los mismos comandos.

En esa máquina no hay `.env`, ni la carpeta `datos/` de la raíz (las exportaciones del reto no se versionan), ni la réplica de Extreme. Por eso:

- las pruebas de `tests/replica` se omiten con su motivo («réplica no configurada…»); corren en la suite completa local, con la réplica en el puerto 5434;
- los catálogos que dependen de la réplica o de las exportaciones responden 503 `catalogo_no_disponible`, declarado en el OpenAPI, y las pruebas lo verifican (ver `../catalogos/README.md`, sección «Sin réplica ni exportaciones»).

## Archivos

| Archivo | Qué muestra |
|---|---|
| `ci_limpio.txt` | La corrida del CI en una **copia limpia** del repositorio, como la ve GitHub Actions o un jurado: cómo se armó la copia, los pasos con su código de salida y su tiempo, las pruebas por nivel, las omitidas agrupadas por motivo, la cobertura, el OpenAPI y el job de caída. |
| `ensayo_copia_limpia.py` | Repite ese ensayo con un comando: `.venv\Scripts\python docs\evidencias\pruebas\ensayo_copia_limpia.py --destino <carpeta temporal> --caida`. Copia solo lo que git versiona, con el fin de línea de Linux, quita las variables del proyecto, deja la réplica inalcanzable y corre `scripts/ci_local.py` y el job de caída. No escribe en el repositorio. |
| `ci_local.txt` | El log completo de `scripts/ci_local.py` de esa corrida. |
| `ci/pytest.xml` · `ci/coverage.xml` · `ci/pasos.json` · `ci/caida.txt` | El junit, la cobertura y los pasos de esa corrida (lo mismo que el flujo sube como artefacto: `reportes-api-frecuencias-py3.11` y `-py3.13`) y la salida del job de caída. |
| `ci_dependencias_y_acciones.txt` | Las dependencias fijadas se instalan con ruedas binarias en Linux (Python 3.11) y las versiones de las acciones y de las imágenes existen. |
| `hallazgos_contrato.txt` | Los hallazgos de las pruebas de contrato y su corrección. La corrida vigente del contrato está en `../contrato/`. |
| `k6_volumen.txt` · `k6_volumen.json` · `k6_en_frio.json` | **Carga con el volumen acordado** (RNF-002, §14.1 «Carga»): un año de resultados sembrado con `scripts/sembrar_volumen.py` (396 ejecuciones, 3.348 predicciones, 3.348 recomendaciones y 8.988 alertas). Consultas paginadas con 50 usuarios: p95 de 627,5 ms y 0 % de errores. Peticiones en frío por ruta, incluida `/segmentos/estadisticas` (no cumple: ver «Carga con el volumen acordado»). |
| `k6_consultas.txt` · `k6_consultas.json` | Corrida anterior de la carga, con un mes de resultados (279 predicciones y 749 alertas): p95 de 451 ms y 0 % de errores. |
| `k6_ingesta.txt` · `k6_ingesta.json` | Consultas mientras corre una ingesta: todas las comprobaciones bien (5.096 de 5.096). |

La corrida anterior de la suite sin Testcontainers (9-11-2026, 02:43; 2 fallas, 7 errores y 4 xfail, ya corregidos)
se movió a `../historial/pruebas_suite_normal_9nov_0243.txt` y `.xml`. La suite vigente es la que cita la tabla
«Cifras vigentes» de `../README.md`; en una máquina limpia, `ci_limpio.txt` y `ci/pytest.xml` (912 casos, 744
aprobados, 0 fallas, 0 errores y 168 omitidos con su motivo).

## Correr las pruebas sin ensuciar el checkout

- **Evidencia escrita por las pruebas.** Las pruebas que dejan un archivo de evidencia (matriz de roles, OpenAPI de seguridad, resiliencia, traza, caída, backtests, optimización) lo escriben con `tests/evidencia.py::guardar_evidencia`. Sin variables, el archivo va a un directorio temporal y el repositorio queda igual que antes de correr la suite (`git status` limpio). Para regenerar a propósito la evidencia versionada de `docs/evidencias/`: `GENERAR_EVIDENCIAS=1 pytest <módulo>`. `EVIDENCIAS_DIR=<carpeta>` elige el directorio temporal.
- **Sin base de datos.** Sin `TEST_DATABASE_URL` ni `DATABASE_URL` (por ejemplo, un checkout recién clonado sin `.env`), las pruebas de integración y de contrato se **omiten** con el motivo en el informe de pytest («no hay base local de pruebas. Defina TEST_DATABASE_URL…»), en vez de fallar. Con una URL que no apunta a `localhost`, `127.0.0.1` o `db`, también se omiten: nunca se conectan a otra base. La clave de la URL no se muestra: el fixture `migrada` la entrega completa para conectarse, pero su `repr` (lo que pytest imprime en un traceback o con `--showlocals`) la oculta.
- **Bases de prueba.** `TEST_DATABASE_NAME=<nombre>` elige la base local de la corrida (por omisión `ai_frecuencias_pruebas`); las pruebas la crean si falta y la migran desde cero.

## Carga con el volumen acordado (RNF-002, §14.1 «Carga»)

**Dataset acordado:** el volumen de **un año de operación del ciclo diario**. Se arma con `scripts/sembrar_volumen.py`, que replica filas reales de la API (ejecuciones con sus intentos, predicciones, recomendaciones, alertas con su historial y fotos de variables) con identificadores nuevos y fechas corridas, hasta llegar a 365 ejecuciones o más. En la medición vigente (`k6_volumen.txt`): 396 ejecuciones, 3.348 predicciones, 3.348 recomendaciones, 8.988 alertas, 8.988 entradas de historial y 4.464 fotos de variables (77 MB). Las alertas vienen de una base sembrada con las reglas anteriores, que generaban más alertas que las vigentes: para la carga es una cota conservadora.

Resultados (API de un solo proceso, equipo cargado con otros procesos):

| Prueba | Resultado | RNF-002 (p95 < 2 s) |
|---|---|---|
| `k6/consultas.js`: consultas paginadas de predicciones, recomendaciones, alertas, ejecuciones y modelos, rampa hasta 50 usuarios, 60 s | 2.873 peticiones, 0 % de errores; p95 de 627,5 ms (el peor recurso, predicciones, 729,7 ms) | Cumple |
| `k6/en_frio.js`: primera petición a cada ruta tras arrancar la API, sin caché | 17 de las 22 rutas medidas (resultados, umbrales, monitoreo, catálogos ligeros y zonas) responden en menos de 100 ms en frío | Cumple |
| `/api/v1/segmentos/estadisticas` (réplica operacional, sin caché) | 8,8 s en frío y 11,9 s en caliente; con `idruta`, 2,3 a 2,9 s | **No cumple** |
| `/api/v1/catalogos/segmentos` | 5,0 s solo la primera vez; después, 65 ms (caché) | No cumple en frío |
| Exportaciones CSV completas (`/predictions/export`, `/alerts/export`) | 3,4 a 5,2 s: descargas del conjunto entero, no consultas paginadas | Fuera de RNF-002 |

`/segmentos/estadisticas` agrega en cada petición la tabla `timbradas_segmentos` de la réplica. El arreglo es una caché con tiempo de vida, como la de los catálogos, o una agregación materializada que el ciclo refresque; hasta que exista, la consulta se documenta como fuera de RNF-002.

Para repetir la medición: `python scripts/sembrar_volumen.py --base-datos ai_frecuencias_volumen --plantilla <base con ejecuciones reales> --ejecuciones 365 --recrear`, la API apuntando a esa base y los dos guiones de k6 (los comandos están al final de `k6_volumen.txt`). `en_frio.js` con `INCLUIR_PLAN=1` agrega `/recommendations/plan` y `/respuesta`.

## Ejecución programada que procesa lo nuevo (§14.2 «Ejecución incremental»)

`../cola/planificador_programado.txt` (y `.json`) lo muestra sin ningún POST manual: el planificador interno (APScheduler, `PLAN_EJECUCION_CRON='*/1 * * * *'`) encola una franja por minuto y la cola la procesa. La primera franja carga el histórico hasta el corte (54.009 filas); llega un día nuevo (51 filas) y se modifican 3 filas del día anterior; la franja programada siguiente lee solo esas 54 filas, avanza la marca de agua y deja 9 predicciones, 60 recomendaciones (9 de las franjas y 51 del plan del día siguiente: 3 rutas × 17 horas) y 8 alertas nuevas; las franjas sin llegada leen 0 filas. Las 3 filas modificadas se actualizan en su lugar (54.009 + 51 = 54.060 filas en `demanda_observada`). Se repite con `PRUEBA_PLANIFICADOR=1 pytest tests/integracion/test_planificador_programado.py` (unos 4 minutos; corre también en el job «caida» del CI; con `GENERAR_EVIDENCIAS=1` reescribe los dos archivos) o con el guion `python docs/evidencias/cola/planificador_programado.py --salida … --json …`. Ambos usan una base local desechable y una copia temporal de `datos/`.

## RNF-005: procesamiento particionable por ruta y fecha

Qué se cumple hoy, con evidencia:

- **Servicios sin estado y varias réplicas.** La API no guarda estado propio en memoria (solo cachés que se pueden perder sin efecto): la cola de trabajos, la marca de agua y los resultados viven en PostgreSQL. Dos o más réplicas comparten la cola (`FOR UPDATE SKIP LOCKED` y una reserva que vence) sin duplicar trabajos (`../cola/replicas.txt`, `tests/integracion/test_cola_replicas.py`), y el planificador encola una sola fila por franja aunque corra en todas (`../cola/planificador.txt`).
- **Partición por fecha.** Cada ejecución procesa un tramo de tiempo: lo nuevo desde la marca de agua y hasta `hasta` (o el `instante` pedido). Las fotos de variables están particionadas por mes (`feature_snapshot`, `PARTITION BY RANGE (ventana_inicio)`).
- **Partición por ruta en los resultados.** `POST /api/v1/frequency/executions` acepta `rutas`: la predicción, la recomendación, las alertas y el plan del día se calculan solo para esas rutas.

**Limitación declarada.** La lectura incremental y la ingesta **no** se parten por ruta: la marca de agua es una sola para la fuente (la mayor `marca_agua_nueva` de las ejecuciones `ok` de frecuencia), una ejecución con `rutas` lee e incorpora todas las rutas nuevas de la fuente, y las ejecuciones de frecuencia se procesan de una en una para que dos lecturas no compitan por la misma marca. Con tres rutas y unas 50 filas nuevas por día, el ciclo de un día nuevo tarda 21,4 s, con el plan del día y la foto de la respuesta incluidos (`../rendimiento/ciclo_final.md`), y la partición por ruta no cambia el resultado; pasa a importar al escalar a toda la red.

**Diseño para partir por ruta** (no se implementó ahora porque cambia la semántica de la marca de agua del ciclo y necesita una migración):

1. Marca de agua por (fuente, ruta) en una tabla propia de `ai_frecuencias`, con las huellas de la ventana de solape de cada ruta.
2. Una ejecución con `rutas` lee solo esas rutas (`WHERE idruta = ANY(:rutas)` en la fuente PostgreSQL; filtro equivalente en Parquet) y avanza solo sus marcas.
3. En la cola, dos ejecuciones de frecuencia pueden correr a la vez si sus rutas no se cruzan: cada una toma un candado por ruta (`pg_advisory_xact_lock`) en vez de esperar a que termine la otra.
4. Prueba de aceptación: dos réplicas procesan en paralelo dos grupos de rutas disjuntos, cada una lee solo sus filas, y el resultado (demanda incorporada, predicciones y alertas) es igual al de una sola ejecución con todas las rutas.
