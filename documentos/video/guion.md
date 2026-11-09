# Video de demostración (E11): guion

Video: `E11_video_demostracion.mp4` (288,4 s, 19,7 MB, 1920×1080, H.264 a 30 cuadros/s y audio AAC). Subtítulos en español: `E11_video_demostracion.srt` (archivo aparte; el video no los lleva quemados, el reproductor los carga si tienen el mismo nombre y están en la misma carpeta).

La narración es una voz sintética de Windows (Microsoft Sabina, español de México). Todo lo que se ve es la aplicación real: la API (FastAPI + PostgreSQL) en su página /docs y el tablero Dash, grabados con Edge y Playwright, más tres páginas que muestran literalmente las líneas de los archivos de evidencia que respaldan las cifras narradas. La clave de API nunca aparece en pantalla. El registro de producción, con herramientas, versiones, duraciones y comprobaciones, está en `api_frecuencias/docs/evidencias/video/registro.txt`.

Las escenas 11 y 12 se regrabaron el 9-11-2026 con las evidencias finales (commit b76546d): el ciclo de §14.2 corrido en la pila creada desde cero y las cifras finales de pruebas, SonarQube, integración continua, k6 y despliegue. Las demás escenas son las de la grabación del commit 8d4e651.

## Escenas

| # | Escena | Inicio | Segundos | Pantalla |
|---|---|---|---|---|
| 1 | El problema y la pregunta del reto | 0:00 | 25,3 | Tablero, pantalla Inicio (parte superior). |
| 2 | La tarjeta de Inicio que responde la pregunta | 0:25 | 17,0 | Tablero, Inicio: tarjeta «Respuesta a la pregunta del reto» (GET /api/v1/respuesta), ruta SILENCIO y luego CRA 54. |
| 3 | Llega un día nuevo (§14.2 paso 1) e integración sin interferir | 0:42 | 20,9 | Swagger /docs: POST /api/v1/frequency/executions con {"hasta": "2025-09-05"} y la respuesta 202 en cola (la clave viaja en la cabecera, nunca en pantalla). |
| 4 | Lectura incremental y calidad (§14.2 paso 2) | 1:03 | 16,2 | Swagger /docs: GET /api/v1/frequency/executions/{execution_id} de esa ejecución: marca de agua anterior y nueva, filas leídas y válidas. |
| 5 | El modelo frente a la línea base, con su banda de incertidumbre | 1:19 | 23,1 | Evidencia evaluacion_modelo.md (prueba reservada) y calibracion_condicional.md (banda P10–P90). |
| 6 | Pronóstico y horario en el tablero | 1:42 | 8,8 | Tablero: Pronóstico (real frente a pronosticado y regla manual) y Horario. |
| 7 | Despacho en tiempo real | 1:51 | 11,0 | Tablero: Despacho, mapa con los buses sobre las calles de su ruta y próximos despachos. |
| 8 | Alertas con explicación y gestión | 2:02 | 25,4 | Tablero: Alertas. Se abre una alerta, se reconoce, se asigna y se cierra con comentario; la bitácora lo registra. |
| 9 | Recomendaciones: objetivo de §10.2, viabilidad y plan D5 | 2:27 | 22,7 | Tablero: Recomendaciones. Plan del día (motor D5) y un escenario calculado por la API (POST /recommendations/calculate) que no es viable. |
| 10 | Monitoreo, retador en sombra y compuerta | 2:50 | 16,7 | Tablero: Monitoreo. Error móvil, sesgo, cobertura, PSI por variable, política y retador en sombra. |
| 11 | El ciclo completo de §14.2, pasos 1 a 6 | 3:07 | 48,0 | Evidencia demo_ciclo_api.txt (la demostración corrida en la pila de Docker Compose creada desde cero), recorrida paso a paso con las cifras resaltadas. |
| 12 | Ingeniería: pruebas, integración continua, SonarQube, k6 y Docker | 3:55 | 38,5 | Evidencias de ingeniería: suite completa, puerta de calidad de SonarQube, k6 (consultas y un año de resultados), integración continua en GitHub y arranque limpio con Docker Compose. |
| 13 | Cierre: el plan | 4:33 | 14,8 | Tarjeta de cierre con el plan en tres fases. |

Duración total medida: 288,43 s (límite de la especificación: 300 s).

### 1. El problema y la pregunta del reto (0:00–0:25, 25,3 s)

**En pantalla.** Tablero, pantalla Inicio (parte superior).

**Narración.**

> Sobusa programa hoy cada hora con el promedio de las ocho semanas anteriores.
> Esa regla no mira la carga de la hora, ni avisa cuando algo se sale de lo normal.
> Extreme Technologies pregunta: ¿cada cuánto despachar buses en SILENCIO, CRA 54 y CL 72, para optimizar la flota y el recaudo?
> ¿Cuántos pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?

**Evidencia.** `documentos/especificacion_tecnica_reto_frecuencias_v1.5.md §20 (pregunta)`; `api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.md (fila «B1 regla manual 8 sem»)`

### 2. La tarjeta de Inicio que responde la pregunta (0:25–0:42, 17,0 s)

**En pantalla.** Tablero, Inicio: tarjeta «Respuesta a la pregunta del reto» (GET /api/v1/respuesta), ruta SILENCIO y luego CRA 54.

**Narración.**

> La pantalla de inicio responde con lo que entrega la API, por ruta y para un día laboral:
> las salidas recomendadas frente a las programadas, el intervalo en pico y en valle, y los pasajeros esperados con su banda;
> los vehículos de la hora pico frente a la flota, y las alertas abiertas.

**Evidencia.** `api_frecuencias/docs/evidencias/tablero/e2e_tablero_completo.txt (inicio: la tarjeta = API)`; `api_frecuencias/docs/evidencias/respuesta/`

### 3. Llega un día nuevo (§14.2 paso 1) e integración sin interferir (0:42–1:03, 20,9 s)

**En pantalla.** Swagger /docs: POST /api/v1/frequency/executions con {"hasta": "2025-09-05"} y la respuesta 202 en cola (la clave viaja en la cabecera, nunca en pantalla).

**Narración.**

> Así llega un día nuevo. La API, en FastAPI y PostgreSQL 14, recibe la orden y responde de inmediato con un trabajo en cola.
> Lee la fuente con un usuario de solo lectura, y escribe solo en su propio esquema, con migraciones.
> En la réplica con el trigger de Extreme, el usuario de lectura no pudo escribir ni una vez.

**Evidencia.** `api_frecuencias/docs/evidencias/video/registro.txt (respuesta de la API durante la grabación)`; `api_frecuencias/docs/evidencias/replica/replica_roles.txt`; `api_frecuencias/docs/evidencias/replica/replica_llegada.txt`

### 4. Lectura incremental y calidad (§14.2 paso 2) (1:03–1:19, 16,2 s)

**En pantalla.** Swagger /docs: GET /api/v1/frequency/executions/{execution_id} de esa ejecución: marca de agua anterior y nueva, filas leídas y válidas.

**Narración.**

> La ejecución termina: leyó solo las 51 filas posteriores a la marca de agua, las validó, y movió la marca al nuevo día.
> Cada error de calidad queda con su lote, su fila y su causa. Repetir la misma fecha no relee ni duplica nada.

**Evidencia.** `api_frecuencias/docs/evidencias/video/registro.txt (respuesta de la API durante la grabación)`; `api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt (paso 2 y la repetición sin datos nuevos)`

### 5. El modelo frente a la línea base, con su banda de incertidumbre (1:19–1:42, 23,1 s)

**En pantalla.** Evidencia evaluacion_modelo.md (prueba reservada) y calibracion_condicional.md (banda P10–P90).

**Narración.**

> El modelo activo es un Gradient Boosting con pérdida Poisson.
> En la prueba reservada de noviembre y diciembre de 2025, que nunca vio,
> su error es de 14,77 %; el de la regla manual, de 21,18 %.
> Cada pronóstico trae su banda del percentil 10 al 90, que en esa prueba cubre el 77,8 % de los casos.

**Evidencia.** `api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.md (filas activo y B1)`; `api_frecuencias/docs/evidencias/modelo/calibracion_condicional.md (cobertura v2 77,82 %)`; `api_frecuencias/docs/evidencias/modelo/resumen_modelo.md (pérdida Poisson)`

### 6. Pronóstico y horario en el tablero (1:42–1:51, 8,8 s)

**En pantalla.** Tablero: Pronóstico (real frente a pronosticado y regla manual) y Horario.

**Narración.**

> En el tablero, el pronóstico se compara hora a hora con lo real y con la regla manual,
> y el horario lo convierte en salidas por hora para cada ruta.

**Evidencia.** `api_frecuencias/docs/evidencias/tablero/dash_pronostico.png`; `api_frecuencias/docs/evidencias/tablero/dash_horario.png`

### 7. Despacho en tiempo real (1:51–2:02, 11,0 s)

**En pantalla.** Tablero: Despacho, mapa con los buses sobre las calles de su ruta y próximos despachos.

**Narración.**

> La consola de despacho lo muestra en tiempo real: cada punto es un bus que sigue su ruta por las calles,
> con lo que sale ahora, en qué bus, y qué ajustar si dos buses se juntan.

**Evidencia.** `api_frecuencias/docs/evidencias/tablero/dash_despacho.png`; `api_frecuencias/docs/evidencias/tablero/despacho_carga_en_frio.txt`

### 8. Alertas con explicación y gestión (2:02–2:27, 25,4 s)

**En pantalla.** Tablero: Alertas. Se abre una alerta, se reconoce, se asigna y se cierra con comentario; la bitácora lo registra.

**Narración.**

> Las alertas siguen el catálogo de diez códigos de la especificación.
> Cada una trae lo observado, lo esperado, el umbral, la tendencia, su puntaje y la acción sugerida.
> El despachador la reconoce, la asigna y la cierra con un comentario, y la bitácora guarda cada cambio.
> Con las reglas sobre datos observados, el volumen bajó de 6,08 a 0,53 alertas por ruta y día.

**Evidencia.** `api_frecuencias/docs/evidencias/alertas/backtest_alertas.md (6,083 → 0,534 alertas por ruta y día)`; `api_frecuencias/docs/evidencias/tablero/e2e_tablero_completo.txt (detalle de §5.3)`

### 9. Recomendaciones: objetivo de §10.2, viabilidad y plan D5 (2:27–2:50, 22,7 s)

**En pantalla.** Tablero: Recomendaciones. Plan del día (motor D5) y un escenario calculado por la API (POST /recommendations/calculate) que no es viable.

**Narración.**

> Las recomendaciones resuelven la función objetivo de la sección 10.2: costo, espera, sobreocupación y desviación,
> con el intervalo mínimo, el nivel de servicio, la flota y el ciclo como restricciones; y el plan del día sale del motor D5.
> Si la flota no alcanza, dice que no es viable, explica el motivo, y propone la mejor aproximación.

**Evidencia.** `api_frecuencias/docs/evidencias/optimizacion/`; `api_frecuencias/docs/evidencias/tablero/dash_recomendaciones_no_viable.png`

### 10. Monitoreo, retador en sombra y compuerta (2:50–3:07, 16,7 s)

**En pantalla.** Tablero: Monitoreo. Error móvil, sesgo, cobertura, PSI por variable, política y retador en sombra.

**Narración.**

> El monitoreo mide el error móvil, el sesgo, la cobertura y la deriva de cada variable.
> Un candidato pasa 14 días en sombra junto al activo, y una compuerta de cuatro criterios decide si entra.
> Aquí está el retador en sombra que entrenamos para esta demostración.

**Evidencia.** `api_frecuencias/docs/evidencias/video/registro.txt (política: retador en sombra)`; `api_frecuencias/docs/evidencias/monitoreo/`

### 11. El ciclo completo de §14.2, pasos 1 a 6 (3:07–3:55, 48,0 s)

**En pantalla.** Evidencia demo_ciclo_api.txt (la demostración corrida en la pila de Docker Compose creada desde cero), recorrida paso a paso con las cifras resaltadas.

**Narración.**

> Este es el ciclo de la sección 14.2, contra la API recién desplegada.
> 1. Llegan datos nuevos: 49.623 filas de carga inicial, 51 de un día, y 4.641 más.
> 2. La lectura es incremental; repetir la misma fecha lee 0 filas.
> 3. Se mide el error del activo en lo recién llegado. 4. La política entrena un candidato solo con lo que ya llegó.
> 5. Los dos se comparan en la misma ventana, del 1 al 14 de diciembre, fuera de la muestra de ambos: 14,108 % el candidato, y 13,982 % el activo.
> 6. Como no mejora al activo, la compuerta de cuatro criterios lo rechaza, y el activo se conserva.

**Evidencia.** `api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt (pasos 1 a 6)`; `api_frecuencias/docs/evidencias/despliegue/demo_esperado.md (línea de tiempo y por qué esas fechas)`; `api_frecuencias/docs/evidencias/despliegue/arranque_limpio.txt (paso 5: la demostración corre en la pila creada desde cero)`

### 12. Ingeniería: pruebas, integración continua, SonarQube, k6 y Docker (3:55–4:33, 38,5 s)

**En pantalla.** Evidencias de ingeniería: suite completa, puerta de calidad de SonarQube, k6 (consultas y un año de resultados), integración continua en GitHub y arranque limpio con Docker Compose.

**Narración.**

> La ingeniería se puede auditar: 1.060 pruebas automáticas, sin fallas, y 94,3 % de cobertura.
> La integración continua pasa en verde en GitHub, en una máquina limpia, y SonarQube aprueba su puerta, con 0 bugs, 0 vulnerabilidades y 0 problemas críticos o bloqueantes.
> Con 50 usuarios simultáneos en k6, el percentil 95 es de 451,3 ms, y de 627,5 ms con un año de resultados, sin errores.
> Y Docker Compose levanta la API y su base desde volúmenes nuevos, y la comprobación completa sale bien.

**Evidencia.** `api_frecuencias/docs/evidencias/pruebas/suite_final.xml (1.060 casos, 0 fallas, 0 errores, 5 omitidos)`; `api_frecuencias/docs/evidencias/sonarqube/quality_gate.json (puerta «Reto Sobusa v1.5» en OK; cobertura 94,3 %; 0 bugs, 0 vulnerabilidades, 0 críticos, 0 bloqueantes)`; `api_frecuencias/docs/evidencias/pruebas/ci_github.txt (GitHub Actions en verde, runner limpio)`; `api_frecuencias/docs/evidencias/pruebas/k6_consultas.json y k6_volumen.json (p95 451,3 ms y 627,5 ms, 0,00 % de errores, 50 usuarios virtuales)`; `api_frecuencias/docs/evidencias/despliegue/arranque_limpio.txt (volúmenes nuevos, «Resultado global: OK»)`

### 13. Cierre: el plan (4:33–4:48, 14,8 s)

**En pantalla.** Tarjeta de cierre con el plan en tres fases.

**Narración.**

> El plan tiene tres fases: cuatro semanas de conexión con una réplica de lectura,
> cuatro semanas en modo sombra, y un piloto de ocho semanas en CRA 54 y CL 72, con el despachador al mando.
> Gracias.

**Evidencia.** `documentos/notas_orador.txt (diapositivas 13 y 14)`; `PLAN_EVOLUCION.md`

## De dónde sale cada cifra narrada

| Cifra | Archivo de evidencia |
|---|---|
| 51 filas leídas y válidas del día nuevo; marca de agua anterior y nueva | respuesta de GET /api/v1/frequency/executions/{id} durante la grabación (api_frecuencias/docs/evidencias/video/registro.txt, «Ejecución en vivo») y api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt, paso (2) |
| WAPE 14,77 % del modelo activo frente a 21,18 % de la regla manual (prueba reservada 2025-11-01 a 2025-12-31) | api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.md, filas «activo (hgb_fv2_20250831_s42)» y «B1 regla manual 8 sem» |
| Cobertura de la banda P10–P90 de 77,8 % en la prueba reservada (calibración v2: 77,82 %) | api_frecuencias/docs/evidencias/modelo/calibracion_condicional.md |
| Gradient Boosting con pérdida Poisson | api_frecuencias/docs/evidencias/modelo/resumen_modelo.md |
| Alertas por ruta y día: 6,08 con las reglas anteriores → 0,53 con las reglas sobre datos observados | api_frecuencias/docs/evidencias/alertas/backtest_alertas.md («Reglas anteriores: 6,083» y «Alertas observadas por ruta y día (todas): 0.534») |
| 14 días en sombra y compuerta de cuatro criterios | política de monitoreo de la API (GET /api/v1/monitoring/policy, umbral sombra_dias = 14) y pantalla Monitoreo |
| Ciclo §14.2, llegada y lectura incremental: 49.623 filas de carga inicial, 51 de un día nuevo y 4.641 más; la repetición de la misma fecha lee 0 | api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt, pasos (1) y (2) |
| Ciclo §14.2, comparación y decisión: en la misma ventana 2025-12-01 a 2025-12-14, fuera de la muestra de ambos, WAPE 14,108 % del candidato frente a 13,982 % del activo; la compuerta de cuatro criterios lo rechaza y el activo sigue | api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt, pasos (3) a (6), y demo_esperado.md |
| 1.060 pruebas automáticas sin fallas (0 fallas, 0 errores, 5 omitidas) | api_frecuencias/docs/evidencias/pruebas/suite_final.xml |
| 94,3 % de cobertura y puerta «Reto Sobusa v1.5» de SonarQube aprobada: 0 bugs, 0 vulnerabilidades, 0 críticos, 0 bloqueantes | api_frecuencias/docs/evidencias/sonarqube/quality_gate.json (status OK; coverage 94.3) |
| Integración continua en verde en GitHub, en un runner limpio | api_frecuencias/docs/evidencias/pruebas/ci_github.txt |
| k6 con 50 usuarios virtuales: p95 451,3 ms en consultas y 627,5 ms con un año de resultados, 0,00 % de errores | api_frecuencias/docs/evidencias/pruebas/k6_consultas.json y api_frecuencias/docs/evidencias/pruebas/k6_volumen.json |
| Docker Compose desde volúmenes nuevos, con la comprobación completa en OK | api_frecuencias/docs/evidencias/despliegue/arranque_limpio.txt («Resultado global: OK») |
| Plan: 4 semanas de conexión, 4 en modo sombra y piloto de 8 semanas en CRA 54 y CL 72 | documentos/notas_orador.txt (diapositiva 13) y PLAN_EVOLUCION.md |

Las cifras del tablero que se ven en pantalla (respuesta del día, plan, alertas, monitoreo) son las que devolvió la API durante la grabación; la narración no las repite para no depender de una corrida concreta.

## Cómo se produjo y cómo se repite

Los programas están en `documentos/video/produccion/` y corren con el entorno virtual de la API (Playwright, httpx e imageio-ffmpeg) en Windows con Edge y la voz Microsoft Sabina instalada:

1. Levantar la API con autenticación y una base PostgreSQL propia (migraciones con `alembic upgrade head` y una copia temporal de `datos/`), y el tablero apuntando a ella con una clave de analista. Las claves de prueba van en `claves.json` junto a los programas (no se versiona) y la API solo recibe sus hashes en `API_KEYS`.
2. `python sembrar.py`: tres ejecuciones diarias y un candidato que queda en sombra.
3. `python sintetizar.py`: narración por escena con las marcas de cada subtítulo.
4. `python visores.py`: páginas que muestran las líneas de evidencia citadas.
5. `python grabar.py 2025-09-05`: grabación con Edge; la clave viaja como cabecera y nunca se ve.
6. `python mezclar.py E11_video_demostracion.mp4 E11_video_demostracion.srt 28`: corte, unión, audio y subtítulos.
7. `python verificar.py ...` y `python documentar.py ...`: comprobaciones, este guion y el registro.
