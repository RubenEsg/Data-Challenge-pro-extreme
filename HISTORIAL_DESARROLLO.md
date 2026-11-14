# Historial de desarrollo

Lista cronológica de **todos los commits** (235) del repositorio de desarrollo del equipo, desde el primero hasta `e61e999`, el commit al que apuntaba `main` al generarla. Responde al «historial» del entregable E03 (fila E03.3 de `MATRIZ_CUMPLIMIENTO.md`): el repositorio de entrega se arma con `empaquetar_entrega.py` a partir de `EntregaFinal/` y solo guarda sus sincronizaciones.

- **De dónde sale.** `historial_desarrollo.py` lee `git log` del repositorio de desarrollo, sin red, y escribe este archivo. Por cada commit publica la fecha y la hora del autor, el hash corto, el asunto, cuántos archivos y líneas cambia (`git log --numstat -M`) y cuántos de esos archivos están en `EntregaFinal/`, la carpeta que se convierte en el repositorio de entrega.
- **Qué no publica.** Correos, nombres de autor (todo el historial es de un solo contribuyente), cuerpos de los mensajes ni rutas de archivos. La revisión automática de los asuntos (claves, contraseñas, tokens, credenciales en URL, cadenas largas con aspecto aleatorio) no omitió ninguno.
- **Cómo verificarlo.** Los hashes son los del repositorio de desarrollo del equipo, que se muestra a quien evalúe si lo pide. Ahí, `git log --reverse --format="%h %aI %s" main` da la misma lista y `git show --numstat <hash>` las cifras de cada commit. Cada hash de git depende de todo lo anterior, así que el hash completo del último commit fija la cadena entera: `e61e99953adcda6817821b1cdee29df80c743e1e`. El primer commit es `6f885e83cae939c90cfc2796c13cc433dfce643a`.
- **Generado** el 14 de noviembre de 2026 a las 08:01 (−05:00), desde `main` (`e61e999`). Al integrar commits nuevos se vuelve a correr el script.

## Resumen

| Commits | Días con commits | Primer commit | Último commit | Tocan `EntregaFinal/` | Archivos cambiados (suma) | Líneas agregadas / quitadas |
|---|---|---|---|---|---|---|
| 235 | 17 | 2026-10-07 | 2026-11-14 | 196 | 6.313 | +1.342.408 / −114.183 |

Un archivo binario cuenta como archivo pero no suma líneas; un archivo renombrado cuenta una vez. Todas las horas tienen el mismo huso (−05:00). 13 commit(s) de fusión no traen cifras: git no muestra su diferencia.

## 2026-10-07 · miércoles · 6 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 10:13 | `6f885e8` | Respaldo 1/5: código, notebooks, páginas, informe, costos y simulador | 90 (10 binarios) | +121.748 / −0 | — |
| 10:17 | `0be99cd` | Respaldo 2/5: experimentos E2-E11, D1-D6 y P1 | 494 (261 binarios) | +175.569 / −0 | — |
| 10:17 | `93caa54` | Respaldo 3/5: experimento D4 (regularidad de intervalos) | 17 (10 binarios) | +6.187 / −0 | — |
| 10:18 | `17af048` | Respaldo 4/5: experimentos E1 y E12 (comparación de 51 modelos) | 626 (272 binarios) | +224.975 / −0 | — |
| 10:50 | `97bed96` | Respaldo 5/5: sistema en tiempo real, consola con 353 días y bitácora | 386 (7 binarios) | +14.230 / −0 | — |
| 10:51 | `1dd0d27` | Bitácora: respaldo completo en GitHub | 1 | +1 / −0 | — |

## 2026-10-08 · jueves · 1 commit

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 19:00 | `d7c0d4c` | E13: limpieza de datos y objetivo corregido | 78 (37 binarios) | +39.144 / −5 | — |

## 2026-10-09 · viernes · 2 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 23:18 | `048538d` | Entregable 1: ETL, EDA e ingeniería de variables | 128 (88 binarios) | +117.242 / −0 | — |
| 23:46 | `f610835` | Entregable 1: equipo por confirmar | 10 | +11 / −12 | — |

## 2026-10-11 · domingo · 6 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 12:34 | `7cb408d` | Entregable 1: un solo cuaderno de EDA | 28 (13 binarios) | +18.946 / −26.812 | — |
| 15:00 | `29b8ca5` | Entregable 1: equipo definitivo y un solo título por cuaderno | 8 | +19 / −19 | — |
| 15:14 | `a8bbb77` | Entregable 1: cuadernos independientes del proyecto (carpeta Entrega1) | 10 | +5.659 / −5.626 | — |
| 15:16 | `36c7ff1` | Entregable 1: salidas sin nombre de carpeta (01 y 03 re-ejecutados) | 124 (88 binarios) | +3.546 / −3.550 | — |
| 16:39 | `ec43bfd` | Entregable 1: sin rastros del proyecto de respaldo en los cuadernos | 16 | +5.653 / −5.661 | — |
| 18:26 | `e009396` | Entregable 1: texto explicativo en la sección 12 del EDA | 2 | +4 / −2 | — |

## 2026-10-12 · lunes · 1 commit

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 23:49 | `9d45b3d` | Consola de despacho: los buses avanzan por las calles | 359 | +1.179 / −7 | — |

## 2026-10-13 · martes · 2 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 00:28 | `0b9fde2` | Vista 3D: buses y pasajeros por las calles | 360 | +1.052 / −371 | — |
| 08:22 | `3b466ad` | Noche del 12 al 13 de octubre: plan con costos con fuente, el mismo día con nuestro plan, piloto para medir beta y propuesta | 812 (43 binarios) | +24.773 / −4.041 | — |

## 2026-10-18 · domingo · 1 commit

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 22:24 | `346519e` | App Sobusa Despacho: prototipo con datos verificados, Inicio, Modelo y Resultado | 31 | +17.304 / −32 | — |

## 2026-10-19 · lunes · 2 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 00:51 | `ab8e01d` | App: pulido de diseno con las guias de Vercel y Taste Skill (estilo Apple) | 14 | +854 / −348 | — |
| 01:30 | `9b6b8d2` | App: solo modo claro y paleta de colores por pantalla | 20 | +538 / −530 | — |

## 2026-11-02 · lunes · 1 commit

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 23:11 | `3507ecd` | Insumos de Sobusa y orden de carpetas | 48 (1 binario) | +3.489 / −78 | — |

## 2026-11-03 · martes · 1 commit

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 00:38 | `f4ae97a` | App completa: nueve pantallas, pruebas en el proyecto y guia del jurado | 15 | +4.192 / −241 | — |

## 2026-11-06 · viernes · 1 commit

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 00:41 | `c27a512` | Sección de metodología del Entregable 2 (LaTeX, figuras y PDF) según la guía del curso | 12 (4 binarios) | +1.233 / −0 | — |

## 2026-11-08 · domingo · 7 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 13:57 | `83fafbb` | Entrega final: cuaderno ejecutado, laboratorio Dash, informe técnico en PDF y empaquetado | 93 (10 binarios) | +29.607 / −0 | sí (91) |
| 14:51 | `ef5bbc1` | Lanzador de doble clic para el laboratorio Dash (Windows) | 4 | +60 / −3 | sí (3) |
| 21:38 | `9adfc40` | Dash con el estilo zentra, ahorro del año y documentos alineados | 39 (3 binarios) | +7.646 / −1.197 | sí (29) |
| 23:21 | `5ad1ab3` | API del reto (FastAPI + PostgreSQL 14) y pantalla de despacho en vivo en el Dash | 109 (12 binarios) | +19.040 / −16 | sí (106) |
| 23:38 | `e159dcf` | Despacho: velocidad en tiempo real y mapa con calles | 4 | +104 / −42 | sí (3) |
| 23:46 | `7394074` | Despacho: los buses siguen la ruta por las calles | 12 (6 binarios) | +205 / −11 | sí (11) |
| 23:52 | `7bb37a5` | Matriz de cumplimiento al día (API en el repositorio, consola Despacho) | 1 | +2 / −2 | sí (1) |

## 2026-11-09 · lunes · 30 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 03:03 | `5f2d4b5` | Reto de frecuencias: olas 1 y 2 de la noche del 9 de noviembre | 292 (27 binarios) | +76.868 / −571 | sí (290) |
| 04:39 | `8d4e651` | Reto de frecuencias: ola 3 (contrato estricto, SonarQube, despliegue reproducible, calibración v2, documentos y respuesta a la pregunta) | 250 (49 binarios) | +67.459 / −5.068 | sí (248) |
| 04:47 | `0febf76` | Artefactos del modelo byte a byte en cualquier sistema (el SHA-256 de la calibración fallaba en Linux) | 5 | +1.951 / −1.947 | sí (4) |
| 05:52 | `3d6781d` | Reto de frecuencias: ola 4 (alertas por hora, ciclo 4× más rápido, calibración de candidatos, festivos, CI limpia, video E11) | 162 (15 binarios) | +20.448 / −6.974 | sí (160) |
| 08:41 | `3d2acf1` | Reto de frecuencias: ola 5 y cierre (§8.3, plan con el modelo activo, respuesta asíncrona, datos recientes, SonarQube en OK, matriz completa) | 433 (49 binarios) | +170.062 / −15.516 | sí (430) |
| 09:07 | `b76546d` | Reto de frecuencias: punto de control antes de la pausa (SonarQube en OK en los documentos, CI de GitHub en verde, matriz al día) | 14 | +164 / −102 | sí (13) |
| 12:56 | `f63cb3f` | Reto de frecuencias: entrega final (SonarQube OK sobre el código final, documentos recompilados, video al día) | 55 (17 binarios) | +612 / −531 | sí (55) |
| 13:57 | `1f3c2fd` | Evidencia de integración continua en el repositorio de entrega público | 14 (10 binarios) | +38 / −20 | sí (13) |
| 14:09 | `545a03c` | Bitácora: incidente de GitHub Actions y corrida pública en verde del repositorio de entrega | 1 | +4 / −0 | — |
| 19:26 | `fffd150` | Bitácora: plan de la ronda para cerrar filas Parcial (olas A y B) | 1 | +15 / −0 | — |
| 19:57 | `5306de7` | Modelo por segmento y sentido: protocolo fijado antes de mirar la prueba | 6 (1 binario) | +1.263 / −4 | sí (6) |
| 20:19 | `52c3ffd` | Gobierno de parámetros: tarifa, elasticidad y suavidad del plan en threshold_config, flota y ciclo por la API y headway vigente de rutas.frecuenciadespachos | 25 | +3.920 / −110 | sí (25) |
| 20:22 | `912a6d1` | Kit de revisión doble humana de alertas (18-R2) e historial verificable del desarrollo (E03.3) | 12 | +6.637 / −1 | sí (12) |
| 20:24 | `7682dbe` | Modelo por segmento y sentido: prueba única, registro y uso en la API y en la foto de variables | 19 (2 binarios) | +4.401 / −147 | sí (19) |
| 20:29 | `183f60a` | Catálogo de rutas con la flota y el ciclo vigentes y procedencia del motor D5 al día | 6 | +28 / −8 | sí (6) |
| 20:37 | `d81cf4a` | El plan del día usa también la capacidad gobernada de la ruta y se aprueba como cualquier umbral | 8 | +78 / −21 | sí (8) |
| 20:45 | `7bac9d5` | Modelo por segmento y sentido: pruebas de errores del contrato y del análisis de sesgo, documentación técnica | 5 | +166 / −2 | sí (5) |
| 20:57 | `be30713` | Evidencia: la ejecución programada real escribe las variables por segmento y sentido | 1 | +12 / −0 | sí (1) |
| 21:21 | `f409b14` | La tolerancia de los datos tardíos de la calidad sale del umbral gobernado de datos atrasados | 8 | +210 / −14 | sí (8) |
| 21:32 | `95a6447` | Evidencia de la corrida final del gobierno de parámetros: pruebas, cobertura, Alembic y despliegue aislado | 1 | +131 / −0 | sí (1) |
| 21:38 | `a64c61c` | Revisión del modelo por segmento: la foto por segmento no tumba el ciclo, errores 503 de la API y paginación estable | 6 | +152 / −21 | sí (6) |
| 21:38 | `003aceb` | Modelo por segmento: cobertura de la banda medida en ventanas de 2 y 3 horas e IC95 de la mejora en la prueba | 4 | +309 / −1 | sí (4) |
| 21:54 | `e3f947b` | Evidencia: la foto por segmento bajo la prueba de caída RNF-001 y en la ejecución programada real | 1 | +39 / −0 | sí (1) |
| 22:10 | `8cdb8e7` | Un cambio del conjunto gobernado a la vez: candado de la transacción en PUT /thresholds y en los ajustes locales | 4 | +114 / −8 | sí (4) |
| 22:10 | `50685c6` | El plan del día no se entrega con un MILP sin solución y la suavidad gobernada empieza desde las 6 h | 4 | +63 / −12 | sí (4) |
| 22:10 | `35198b2` | Catálogo de rutas: la flota y el ciclo del listado se describen como referencia del catálogo empaquetado | 2 | +14 / −6 | sí (2) |
| 22:12 | `f45b870` | Evidencia de la revisión del gobierno de parámetros: cambios simultáneos y suavidad sin solución | 2 | +95 / −0 | sí (2) |
| 22:30 | `b1fcb76` | Segmentos: agregación materializada con refresco en la cola; estadísticas y catálogo por debajo de 2 s (§7.1, RNF-002, RNF-004, §14.1) | 40 | +5.987 / −108 | sí (40) |
| 22:31 | `b216270` | Evidencia de la revisión: corrida final de las suites, compatibilidad con main y despliegue aislado | 1 | +28 / −0 | sí (1) |
| 23:38 | `45aa210` | Modelo por segmento y sentido: protocolo previo, prueba única, banda P10–P90 calibrada, registro y uso en la API y en la foto de variables (§3.1-M3, §9.1, §9.3, §7.3) | fusión | — | — |

## 2026-11-10 · martes · 76 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 00:02 | `8c0d067` | Partición del ciclo por ruta: marca de agua y candado por ruta, trabajos por ruta bajo una ejecución madre y evidencia con dos réplicas (RNF-005, §9.5) | 33 | +4.500 / −236 | sí (33) |
| 00:09 | `9dfb7bc` | Gobierno de parámetros: tarifa, elasticidad y suavidad del plan versionadas, flota y ciclo administrables por la API, candado de versiones y frecuencia vigente de rutas.frecuenciadespachos (§5.1, §3.1-M2, §6.1, §6.2) | fusión | — | — |
| 00:31 | `0175aee` | Integración: una ejecución partida por ruta usa una sola versión de umbrales, y las pruebas con procesos reales comprueban la foto por segmento | 9 | +167 / −34 | sí (9) |
| 00:32 | `0fd1ce9` | Integración: prueba de convivencia del ciclo con la capa de segmentos, sin partir y partida por ruta | 2 | +493 / −0 | sí (2) |
| 00:51 | `c76db7d` | Integración: la convivencia cubre la franja programada con PLAN_PARTICION=ruta y la prueba de caída acepta sus puertos | 2 | +63 / −6 | sí (2) |
| 01:02 | `ba2ac03` | Integración: las pruebas de carga de la réplica leen las exportaciones de REPLICA_DATOS_DIR | 1 | +5 / −1 | sí (1) |
| 01:35 | `f60c95e` | Integración: la foto de la respuesta del reto de cada trabajo usa la versión de umbrales fijada de su ejecución | 5 | +75 / −17 | sí (5) |
| 02:36 | `b60c62b` | Segmentos: el refresco incremental compara las huellas de la ventana de solape y termina sin reescribir nada si la fuente no trae cambios | 12 | +841 / −70 | sí (12) |
| 03:05 | `96d49a3` | Ocupación por segmento (§10.1): perfil histórico, factor de carga por día de la semana y ocupación actual en el ciclo, ALT-002 y el plan | 20 (1 binario) | +2.336 / −57 | sí (20) |
| 03:14 | `3fa0a3d` | Retención de datos: tarea automática y gobernada que aplica la política de §18 (13 meses en caliente) | 20 | +2.702 / −22 | sí (20) |
| 03:15 | `fcff379` | Calidad: el reporte de unicidad del lote se envía al responsable del consolidado por el canal de notificaciones | 5 | +256 / −2 | sí (5) |
| 03:18 | `f5d84a8` | Consolidados en el ciclo: bajadas en el histórico, lectura de los consolidados de Extreme y contraste con la agregación propia | 24 (1 binario) | +2.290 / −63 | sí (24) |
| 03:18 | `0efc36a` | Backtest de ALT-008 con bajadas: evidencia regenerada | 3 | +243 / −143 | sí (3) |
| 03:25 | `e44d63c` | Ocupación por segmento: estacionalidad actual de la lectura integrada, backtest de la restricción reactiva y documentación | 10 | +3.893 / −12 | sí (10) |
| 03:26 | `937d6a5` | Novedades viales por ruta: cada novedad con filas en novedades_viales_ruta afecta solo a sus rutas (§11.2) | 9 | +690 / −34 | sí (9) |
| 03:39 | `bdc6652` | Consolidados con datos reales: evidencia de la réplica, pruebas de solo lectura y documentación | 12 | +1.341 / −8 | sí (12) |
| 03:43 | `97c6034` | Novedades por ruta: la reconstrucción del contexto desde la réplica usa la misma preparación por ruta | 1 | +18 / −16 | sí (1) |
| 03:51 | `52820f1` | Alertas §5.3: viaje, vehículo y seudónimo del conductor en ALT-006 y ALT-009 con los viajes de progvehiculos | 10 | +1.680 / −13 | sí (10) |
| 03:51 | `7612b5e` | ALT-003 de pronóstico: probabilidad de superar la capacidad efectiva y mínimo gobernado elegido sin fuga (migración 0013) | 16 | +1.858 / −85 | sí (16) |
| 03:56 | `62eb5c0` | Matriz: filas de la ola A, Cifras vigentes nuevas y lo que queda abierto al día | 2 | +248 / −91 | sí (2) |
| 03:56 | `2b71009` | Documentación de la API: ola A en README, manuales, despliegue, hallazgos e índices de evidencias | 16 | +559 / −217 | sí (16) |
| 03:56 | `098efed` | Documentos de entrega: PLAN_EVOLUCION, README, mapeo, E01, E02 y presentación al día con la ola A | 23 (10 binarios) | +419 / −173 | sí (23) |
| 04:04 | `8d134a8` | Consolidados: las tolerancias del contraste que no son números responden 422, no 500 | 4 | +24 / −8 | sí (4) |
| 04:24 | `9ebd9de` | Documentación: rutas completas de k6 en la matriz, el bloque de rendimiento.txt y la partición por ruta como opción | 5 | +9 / −9 | sí (5) |
| 04:25 | `af59758` | Documentos: E01, E02 y presentación compilados sobre la ola A integrada | 10 (10 binarios) | +0 / −0 | sí (10) |
| 04:26 | `f2331d0` | Documentación: la fila 19-3 de la matriz cita también el supuesto S14 en su columna de ubicación | 1 | +1 / −1 | sí (1) |
| 04:45 | `3188ac4` | Kit de revisión humana (18-R2): revisan dos personas del área operativa de Sobusa, no el equipo | 4 | +45 / −16 | sí (4) |
| 04:46 | `5ea5671` | Retención: el archivo de una partición pierde sus llaves foráneas y la espera de candados cede ante un ciclo (§18) | 4 | +196 / −27 | sí (4) |
| 04:46 | `8d28094` | Segmentos: la tabla de la medición dice que la fila sin huellas es el código nuevo (hasta la 0010 se rehacía además toda la respuesta) | 1 | +5 / −1 | sí (1) |
| 04:49 | `d785d4d` | Unicidad: el docstring del reporte pendiente no promete un reenvío que no existe (queda en notification_log; los lotes siguientes salen al destinatario) | 1 | +3 / −1 | sí (1) |
| 04:54 | `05a7cdc` | Segmentos: la prueba de la réplica comprueba que, tras el refresco parcial, toda segmento_estadistica es la de rehacerla entera (0 filas distintas) | 3 | +31 / −10 | sí (3) |
| 04:56 | `246a2ab` | Consolidados: el documento técnico dice con qué filtros se consultan las incidencias | 1 | +2 / −1 | sí (1) |
| 05:07 | `984c975` | Demostración §14.2: cliente HTTP común con keep-alive de 2 s y un reintento solo en GET y HEAD | 5 | +195 / −20 | sí (5) |
| 05:08 | `c8da33b` | Pruebas: la migración 0008 (segmentos materializados) sube y baja en una base desechable | 1 | +142 / −0 | sí (1) |
| 05:08 | `c68dfd6` | Matriz: el parámetro de ruta de cada operación con el nombre del OpenAPI ({execution_id}, {alert_id}, {model_id}) | 1 | +9 / −9 | sí (1) |
| 05:09 | `8c83037` | Revisión de ocupación por segmento: ventana de 24 h para la ocupación actual y evidencia en tiempo real | 13 | +427 / −108 | sí (13) |
| 05:18 | `4d7aad4` | Revisión de alertas_mejoras: una fuente de viajes vacía no calla ALT-009, candado de umbrales en la 0013 y sentido medido | 9 | +233 / −23 | sí (9) |
| 05:24 | `3359a66` | Retención: pruebas de la reserva perdida (no borra ni anota nada y la cola lo ve como reserva_perdida) y de la partición con nombre no estándar (se conserva para el DBA) | 1 | +45 / −0 | sí (1) |
| 05:31 | `f467833` | Consolidados por segmento: los viajes por día se miden con los días de la agregación propia | 5 | +124 / −16 | sí (5) |
| 05:38 | `abf5d2c` | Consolidados: la evidencia muestra de dónde salen las diferencias groseras de viajes por día (H17 propuesto) | 7 | +367 / −6 | sí (7) |
| 05:39 | `f433a57` | Evidencia de alertas: corridas de pytest al día con las pruebas de §5.3 y de ALT-003 (201 unitarias y 18 de integración y datos, 0 fallas) | 2 | +57 / −6 | sí (2) |
| 05:41 | `317a8ec` | Consolidados por segmento: los días propios se toman en el grano efectivo, también sin estacionalidad (H1) | 2 | +42 / −16 | sí (2) |
| 05:44 | `e7b0e53` | Consolidados: ano_abierto en la API pública del módulo | 1 | +4 / −3 | sí (1) |
| 05:48 | `9427332` | Ocupación por segmento (§10.1): perfil histórico, factor de carga por día de la semana y ocupación actual en el ciclo | fusión | — | — |
| 06:00 | `cf75c81` | Operación: novedades viales por ruta (§11.2), retención automática (§18), reporte de unicidad al responsable (§6.3) y refresco de segmentos sin cambios | fusión | — | — |
| 06:03 | `15245a5` | Integración: la política de retención decide sobre ocupacion_segmento (se conserva, como la demanda observada) | 2 | +7 / −4 | sí (2) |
| 06:04 | `c4d6626` | Integración: la prueba de la réplica que inserta un viaje por el trigger solo corre con REPLICA_PRUEBAS_ESCRITURA=1 | 2 | +9 / −2 | sí (2) |
| 07:54 | `7f2840d` | Consolidados en el ciclo (§6.1, §6.3, §7.3, §11.2): bajadas en el histórico, ALT-008 con bajadas, lectura incremental de timbradas_consolidado y contraste con la agregación propia | fusión | — | — |
| 08:08 | `9cb9136` | Alertas (§5.2, §5.3): identificación de viaje, vehículo y conductor seudonimizado, probabilidad mínima de ALT-003 con protocolo y ALT-009 con viajes programados | fusión | — | — |
| 08:10 | `ecf70d8` | Arreglos previos: kit humano para el área operativa de Sobusa (18-R2), cliente HTTP común de la demostración (§14.2), prueba propia de la migración 0008 y parámetros de ruta del OpenAPI en la matriz | fusión | — | — |
| 08:12 | `619b823` | Integración: el cliente HTTP común de la demostración pasa a scripts/cliente_http.py (no choca con dash_app/cliente_api.py) | 5 | +25 / −19 | sí (5) |
| 08:14 | `e64a530` | Integración: la prueba de consolidados con la ejecución partida deja threshold_config como lo encontró | 1 | +12 / −3 | sí (1) |
| 08:17 | `e4c81aa` | Integración: los documentos técnicos de alertas y de ocupación dicen la identificación de §5.3 de la ALT-002 medida en el segmento crítico | 2 | +13 / −7 | sí (2) |
| 08:26 | `178b88d` | Matriz (ronda b1): ocupación por segmento, retención automática, novedades por ruta, reporte de unicidad y refresco sin cambios | 2 | +120 / −42 | sí (2) |
| 08:26 | `6546c76` | Documentación de la API (ronda b1): ocupación por segmento, retención, novedades por ruta y reporte de unicidad | 10 | +492 / −124 | sí (10) |
| 08:26 | `4bd8f15` | Documentos de entrega (ronda b1): ocupación por segmento, retención automática, novedades por ruta y reporte de unicidad | 22 (10 binarios) | +294 / −142 | sí (22) |
| 08:45 | `f33db93` | Documentación: la matriz cita el supuesto S15, el S8 y «Otras preguntas para Extreme» como el mapeo y los hallazgos | 1 | +12 / −10 | sí (1) |
| 08:50 | `7ce9804` | Documentación: el índice de evidencias dice que las dos corridas de retención salen de dos pruebas, y el manual técnico vuelve a 120 columnas | 2 | +6 / −5 | sí (2) |
| 08:52 | `e6c61e1` | Documentación: el README de la entrega y PLAN_EVOLUCION dicen, como el README de la API, que la medición del ciclo es anterior a la ocupación por segmento | 2 | +2 / −2 | sí (2) |
| 09:23 | `84c53f9` | Integración: la migración 0013 vuelve a escribir «MOTIVO = (» como en la rama de consolidados | 1 | +1 / −1 | sí (1) |
| 09:28 | `32db3e7` | Ronda b2 de la ola B en main: consolidados en el ciclo, alertas y arreglos previos | fusión | — | — |
| 10:38 | `9f1613a` | Matriz (ronda b2): consolidados en el ciclo, alertas con la identificación de §5.3, cadena de migraciones 0001 a 0014 y una sola regla de «Depende de Extreme» | 1 | +122 / −95 | sí (1) |
| 10:39 | `d6b7973` | Documentación de la API (ronda b2): paso de consolidados del ciclo, identificación de §5.3, ALT-003 con probabilidad mínima, migraciones 0013 y 0014 y hallazgo H17 | 11 | +396 / −137 | sí (11) |
| 10:39 | `23cb34c` | Documentos de entrega (ronda b2): consolidados en el ciclo, bajadas en el histórico, identificación de §5.3 y ALT-003 con probabilidad mínima | 21 (11 binarios) | +346 / −226 | sí (21) |
| 11:03 | `d749cf3` | Documentación: H17 ya está en hallazgos_extreme.md, así que la matriz dice H1 a H17 y los documentos lo citan sin «propuesto» | 8 | +18 / −18 | sí (8) |
| 11:03 | `263d0c0` | Documentación: las cifras de alertas del README de la entrega, PLAN_EVOLUCION, mapeo y respuesta_pregunta_reto son las de la evidencia vigente | 4 | +14 / −14 | sí (4) |
| 20:09 | `d3d2f11` | Documentación: el README de la API reajusta el párrafo de las preguntas abiertas (H17, H14 y H13) sin cortar líneas a la mitad | 1 | +4 / −4 | sí (1) |
| 20:11 | `15e56e7` | Documentación: la matriz aplica la regla de «Depende de Extreme» también a 11.2-01 y no manda a «Cifras vigentes» lo que el bloque no trae | 1 | +15 / −13 | sí (1) |
| 20:14 | `fd713f6` | Documentación: E02 lee de la evidencia el mínimo de ALT-003, las notas del orador reportan H17 sin «proponer» y los documentos se recompilan | 14 (10 binarios) | +8 / −5 | sí (14) |
| 20:22 | `6f5564d` | Documentación: 6.1-13 (ajuste por evento y ruta) pasa a Parcial con «Depende de Extreme», como 11.2-04 | 1 | +5 / −5 | sí (1) |
| 23:18 | `eee414b` | Cierre de operación en tiempo real (§10.1-d, §9.3, §5.2, RNF-006): ciclo intradía programado, alertas observadas de cada día del lote sin duplicar, ALT-002 con la ocupación guardada, planes reutilizados, métrica de etapas acotada, reintentos del cliente HTTP y candado de la 0012 | 35 | +3.694 / −248 | sí (35) |
| 23:21 | `2cb1b2f` | Cierre de lectura y evidencia (§6.1, §6.3, §8.3, §11.3, §18): consolidados filtrados por proceso en el SQL con sus UNI-001 reportados, índices medidos en transacciones revertidas, backtest de alertas con el factor del ciclo, frecuencia de la fuente, una sola seudonimización, bordes de la retención y total combinado de alertas | 49 | +10.384 / −1.176 | sí (49) |
| 23:48 | `53dcef4` | Integración: la franja y el plan dicen la fuente real del headway vigente (tabla rutas de la fuente o exportación empaquetada) | 2 | +114 / −10 | sí (2) |
| 23:48 | `f7b828e` | Integración: cifras_vigentes.py lee la evidencia del ciclo intradía (carga en la fuente, estimación sin índices, duración y consulta paginada con un ciclo en curso) | 2 | +105 / −1 | sí (2) |
| 23:49 | `3f99c40` | Integración: ninguna prueba de integración deja vigente una versión de umbrales que creó, en cualquier orden | 8 | +49 / −37 | sí (8) |
| 23:57 | `4034ba9` | Integración: una llave que la lectura incremental deduplicó en un consolidado se reporta como UNI-001 (6.3-06) | 4 | +176 / −14 | sí (4) |

## 2026-11-11 · miércoles · 37 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 00:06 | `b5b8176` | Integración: test_alertas_observadas.py escribe alertas_observadas_ejemplo.json con la identificación de §5.3 | 2 | +319 / −101 | sí (2) |
| 00:11 | `087ab6e` | Integración: una prueba unitaria recorre las etapas que escribe el código y fija que todas son etiquetas de ETAPAS_METRICA | 1 | +46 / −0 | sí (1) |
| 00:14 | `4f0ecd6` | Integración: la retención borra por antigüedad las filas de los ciclos intradía como las del diario (prueba) | 1 | +37 / −3 | sí (1) |
| 00:20 | `bcddd8f` | Integración: la alerta de un episodio que crece hacia atrás empieza en el menor de los dos inicios | 3 | +62 / −6 | sí (3) |
| 00:27 | `ab2fadd` | Integración: ALT-002 con la hora pico medida por un ciclo anterior identifica su viaje con los viajes del día | 4 | +125 / −9 | sí (4) |
| 00:54 | `3ce700a` | Integración: la prueba del 404 «sin_calcular» fija su precondición (sin foto guardada del 2025-03-04) | 1 | +7 / −1 | sí (1) |
| 01:58 | `5336a2b` | Integración: una llave repetida de un consolidado se reporta una vez, no en cada ciclo que la vuelve a leer sin cambios (6.3-06) | 3 | +72 / −9 | sí (3) |
| 02:03 | `a53015b` | Integración: las franjas del ciclo usan el headway vigente del plan, de la tabla rutas de la fuente en modo integrado (§6.1, §6.2) | 2 | +60 / −5 | sí (2) |
| 03:45 | `8bd7cf2` | Integración: test_caida corre prueba_caida.py en su propia base nueva, como las demás pruebas con procesos reales | 1 | +34 / −8 | sí (1) |
| 03:45 | `52c8c5c` | Integración: el log de las franjas del planificador sale de una sola función (SonarQube python:S1192, crítico) | 2 | +24 / −6 | sí (2) |
| 03:45 | `1c59b98` | Integración: la prueba de determinismo del historial compara dos corridas guardadas (SonarQube python:S5863, bug) | 1 | +2 / −1 | sí (1) |
| 04:25 | `4cf3c0b` | Evidencia: suite final y SonarQube sobre el código final | 22 (2 binarios) | +37.050 / −9.353 | sí (22) |
| 04:31 | `bb7a612` | Paquete de cierre en main (ronda c1): ciclos intradía programados, alertas de cada día del lote, lectura de consolidados por proceso, índices medidos, frecuencia de la fuente y la suite final con SonarQube | fusión | — | — |
| 04:52 | `d63455a` | Evidencia de réplica: explain_incremental con la propuesta de índices vigente | 6 | +695 / −603 | sí (6) |
| 04:55 | `9ab4ff8` | Evidencia de consolidados: H17 ya es un hallazgo numerado, sin «propuesto» | 8 | +12 / −12 | sí (8) |
| 04:57 | `907b51c` | Evidencia: contrato OpenAPI con el código final (65 rutas y 69 operaciones) | 5 | +59 / −31 | sí (5) |
| 04:59 | `6e67b36` | Evidencia: matriz de roles y seguridad del OpenAPI con las 67 operaciones de /api/v1 | 2 | +105 / −0 | sí (2) |
| 05:02 | `619a918` | Evidencia: gobierno de parámetros con la versión vigente final (9) y la cadena integrada 0001 → 0014 | 6 | +208 / −173 | sí (6) |
| 05:04 | `26a7c8d` | Evidencia: optimización (calculate, plan D5 y §12.3) con el código final | 7 | +970 / −394 | sí (7) |
| 05:12 | `a9678fa` | Linaje: las bajadas y las subidas por segmento empaquetadas se reconstruyen desde la réplica | 7 | +500 / −31 | sí (7) |
| 05:15 | `d9be4e3` | Evidencia de réplica: la llegada por el trigger con el código final y las 14 migraciones | 4 | +249 / −57 | sí (4) |
| 05:18 | `348a18a` | Evidencia: lo demás que escriben las pruebas de integración, con el código final | 10 | +1.890 / −632 | sí (10) |
| 05:26 | `9554286` | Evidencia de réplica: tests/replica completo con las pruebas de escritura (206 de 206) | 3 | +56 / −44 | sí (3) |
| 05:27 | `afc03b2` | Evidencia: ejecución programada y ciclo intradía programado con el código final | 4 | +83 / −104 | sí (4) |
| 05:30 | `ff40694` | Evidencia: prueba de caída (RNF-001) con el código final, en su propia base nueva | 2 | +55 / −49 | sí (2) |
| 05:32 | `22cd05a` | Réplica: el contraste por segmento con filas reales de la liquidación (H10 también por segmento) | 3 | +313 / −0 | sí (3) |
| 05:35 | `f411e30` | Evidencia: dos réplicas con la ejecución partida por ruta (RNF-005), con el código final | 2 | +151 / −139 | sí (2) |
| 05:39 | `0955a75` | Evidencia de réplica: lectura por ruta con el código final y las condiciones de la medición | 4 | +124 / −79 | sí (4) |
| 05:43 | `b03257a` | Evidencia: traza entre réplicas y comprobación con uvicorn, con el código final | 3 | +29 / −20 | sí (3) |
| 05:46 | `3960845` | Evidencia de réplica: tests/replica con la prueba nueva (207 de 207) y el contexto desde la base | 5 | +38 / −33 | sí (5) |
| 05:48 | `2e39823` | Evidencia de réplica: roles, erratas y objetos con el código final | 3 | +9 / −9 | sí (3) |
| 05:56 | `ed9a0b3` | Evidencia: sensibilidad de la franja con el código final; el texto dice el factor de carga por día de la semana | 3 | +1.638 / −1.152 | sí (3) |
| 05:57 | `6e84bc1` | Evidencia: viabilidad de la recomendación por ruta, hora y tipo de día con el código final | 2 | +735 / −717 | sí (2) |
| 06:14 | `73a07b9` | Evidencia: dos réplicas que comparten la cola y el planificador con dos réplicas, con el código final | 2 | +40 / −38 | sí (2) |
| 07:00 | `4d4a452` | Evidencia final de despliegue: pila aislada, modo integrado y demostración de §14.2 con el código final | 10 | +285 / −184 | sí (10) |
| 07:01 | `5a59c1f` | Evidencia final de rendimiento: ciclo diario y carga en la fuente del ciclo intradía con el código final | 4 | +20.141 / −3.041 | sí (4) |
| 07:01 | `75874cb` | Evidencia final de la respuesta del reto (§20) con el código final | 9 | +1.565 / −1.041 | sí (9) |

## 2026-11-13 · viernes · 43 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 18:22 | `6eb94aa` | Evidencia final de contrato y pruebas con el código final (rama ev-contrato) | fusión | — | — |
| 18:22 | `cf89dcd` | Evidencia final de réplica y datos con el código final (rama ev-replica) | fusión | — | — |
| 18:23 | `e74d16b` | Evidencia final de despliegue y rendimiento, primera parte (rama ev-despliegue) | fusión | — | — |
| 18:59 | `947554b` | Arreglo: el contraste por segmento no depende del bloque horario de Extreme (H10) | 15 | +913 / −284 | sí (15) |
| 19:45 | `90cb9f6` | Arreglo: la propuesta de índices entera ya no empeora la lectura compuesta, y se mide entera | 17 | +4.307 / −1.880 | sí (17) |
| 20:08 | `d3cd1dc` | Arreglo: las réplicas de los guiones corren sobre una copia temporal de datos/ | 8 | +184 / −18 | sí (8) |
| 20:09 | `6bdd0ee` | Arreglo: la política no encola un reentrenamiento cuyo corte no se puede entrenar | 11 | +521 / −175 | sí (11) |
| 20:31 | `9d44bd9` | Arreglo: particion_por_ruta.md con las cifras de la evidencia regenerada (réplicas por ruta y lectura por ruta) | 1 | +13 / −10 | sí (1) |
| 20:39 | `26d96b8` | Evidencia: tests/replica completo sobre los arreglos (208 casos, con las pruebas de escritura) | 4 | +28 / −26 | sí (4) |
| 20:49 | `577f830` | Evidencia: caída (RNF-001) y ciclo intradía programado sobre el código de los arreglos | 4 | +83 / −83 | sí (4) |
| 20:53 | `3e715bd` | Evidencia: ejecución programada de §14.2 sobre el código de los arreglos (commit 577f830) | 2 | +31 / −31 | sí (2) |
| 21:17 | `d0c863e` | Revisión: una serie vacía es un corte sin datos y no otro error en la decisión de la política | 4 | +23 / −5 | sí (4) |
| 21:17 | `65243f5` | Revisión: al sumar los bloques de Extreme sin la hora, una medida nula sigue nula | 2 | +35 / −5 | sí (2) |
| 21:17 | `daa7f92` | Revisión: prueba de réplica de que la lectura sin la unión final de rutas entrega las mismas filas | 1 | +21 / −0 | sí (1) |
| 21:24 | `2c36fde` | Revisión: las diferencias no bloqueantes del contraste con filas reales tienen causa medida | 4 | +54 / −6 | sí (4) |
| 21:24 | `98b2206` | Revisión: tests/replica completo sobre el código revisado (209 casos, con las pruebas de escritura) | 4 | +29 / −28 | sí (4) |
| 21:26 | `8fbae5f` | Revisión: consolidados_ciclo.md no afirma del rango por hora lo que no está medido | 1 | +4 / −3 | sí (1) |
| 22:01 | `e1b3a6b` | Evidencia de despliegue: pila aislada desde cero sobre el código de los arreglos y su revisión (8fbae5f) | 7 | +49 / −49 | sí (7) |
| 22:09 | `4192704` | Despliegue: --puerto-integrado es también el puerto que publica la API del modo integrado, con prueba | 2 | +30 / −1 | sí (2) |
| 22:10 | `6eb7dcc` | Evidencia: scripts/evidencia_pytest.py escribe los archivos pytest_&lt;área&gt;.txt desde la salida de pytest, con prueba | 2 | +141 / −0 | sí (2) |
| 22:13 | `51f3f16` | Evidencia de despliegue: modo integrado contra la réplica y pila aislada con el guion corregido | 8 | +56 / −52 | sí (8) |
| 22:22 | `1fe66cd` | Evidencia de la demostración de §14.2: corrida de referencia, paso por la cola y demostración ampliada sobre el código final | 2 | +41 / −32 | sí (2) |
| 22:25 | `daddbea` | Evidencia de rendimiento: ciclo diario medido sobre el código final (mismo SHA-256 del resultado que el 11-11) | 2 | +33 / −33 | sí (2) |
| 22:26 | `6f43cb7` | Evidencia de rendimiento: carga en la fuente del ciclo intradía con la lectura demanda_segmentos final | 2 | +42 / −42 | sí (2) |
| 22:28 | `189adc5` | Evidencia de la respuesta del reto (§20) sobre el código final; sus pruebas, con scripts/evidencia_pytest.py | 8 | +641 / −640 | sí (8) |
| 22:32 | `2991798` | Evidencia: pruebas de catálogos y de optimización sobre el código final; el generador solo cuenta las líneas del resumen de pytest | 4 | +215 / −121 | sí (4) |
| 23:03 | `b77ac60` | Evidencia de rendimiento: k6 de la capa de segmentos y de la carga con el volumen sembrado desde el ciclo final; rendimiento.txt dice la medición vigente | 9 | +986 / −863 | sí (9) |
| 23:04 | `9701266` | Evidencia de RNF-003: ingesta de 111.792 filas con COPY sobre el código final | 1 | +11 / −11 | sí (1) |
| 23:07 | `965a3ec` | Evidencia de RNF-001: caída con SIGKILL real en contenedores de la imagen del código final | 2 | +51 / −45 | sí (2) |
| 23:13 | `87d4895` | Evidencia de despliegue: pila aislada desde cero con la imagen del código y los guiones finales | 8 | +46 / −48 | sí (8) |
| 23:23 | `ab1386d` | Consolidación: cifras vigentes de la capa de segmentos desde la corrida del 13-11, casos por nivel, ciclo diario, contraste por segmento con filas reales y propuesta de índices entera, con pruebas | 2 | +202 / −5 | sí (2) |
| 23:23 | `d2c2c81` | Tablero: un viaje, vehículo o conductor vacío dice el motivo real de identificacion_5_3 y no siempre «no aplica», con prueba | 3 | +110 / −7 | sí (3) |
| 23:23 | `4ff1a0b` | Presentación: el texto alternativo de la diapositiva 3 nombra la tarjeta de consolidados | 1 | +3 / −2 | sí (1) |
| 23:25 | `f1aeb9f` | Consolidación: las dos corridas anteriores de k6 dicen que lo son en Cifras vigentes, con prueba | 2 | +17 / −2 | sí (2) |
| 23:30 | `9936843` | Matriz: filas de los revisores del cierre ajustadas con c1, el contraste por segmento sin la hora, la propuesta de índices entera y la evidencia del 13-11; «Lo que queda abierto» sin pendientes de nuestra parte | 1 | +82 / −69 | sí (1) |
| 23:33 | `aaeb85b` | Documentos: README de la entrega, de la API e índice de evidencias con las cifras de alertas, ciclo, carga, contrato, despliegue y ciclos intradía del código final | 3 | +51 / −39 | sí (3) |
| 23:38 | `0e2e105` | Documentos: plan de evolución, manual técnico, mapeo, respuesta del reto, E01, E02 y presentación con los ciclos intradía programados, la propuesta de índices entera y las cifras de alertas del código final | 9 | +109 / −81 | sí (9) |
| 23:42 | `713e207` | Documentos técnicos: hallazgos H10, H12 y H15, despliegue con la corrida del 13-11, consolidados, ocupación, retención y resumen del modelo con lo que cambió el cierre | 6 | +47 / −24 | sí (6) |
| 23:44 | `312dfb9` | Índice de evidencias: vigencias del 11 y del 13-11, filas nuevas de ocupación, réplica y consolidados, y mediciones anteriores rotuladas | 1 | +39 / −33 | sí (1) |
| 23:44 | `29f83ed` | Evidencias: índices de pruebas, catálogos, contrato e historial con la medición vigente del 13-11 y las anteriores rotuladas | 4 | +11 / −10 | sí (4) |
| 23:46 | `eaa8d9e` | Matriz: las filas de carga, asincronía, integración y migraciones citan la medición vigente del 13-11 y la cadena completa 0001 a 0014 | 1 | +10 / −10 | sí (1) |
| 23:46 | `b17cc6b` | Documentos: la política no encola un reentrenamiento que no se puede entrenar y los guiones de réplicas corren sobre una copia temporal | 2 | +7 / −2 | sí (2) |
| 23:48 | `22733b0` | Documentos: E02 y LEEME dicen el contraste por segmento con filas reales y la medición vigente de la capa de segmentos | 2 | +4 / −4 | sí (2) |

## 2026-11-14 · sábado · 18 commits

| Hora | Commit | Asunto | Archivos | Líneas | En `EntregaFinal/` |
|---|---|---|---|---|---|
| 00:16 | `ca39144` | Consolidación: el rango por hora de los consolidados recibe su configuración de una función con tipo declarado (SonarQube python:S5655, crítico) | 2 | +27 / −3 | sí (2) |
| 00:19 | `883cbdb` | Manual técnico: la 0012 toma el candado de los umbrales y la fila de la ejecución programada nombra el ciclo intradía | 1 | +2 / −2 | sí (1) |
| 00:57 | `e6f2843` | Evidencia: suite final y SonarQube sobre el código final | 22 (2 binarios) | +4.808 / −2.381 | sí (22) |
| 00:58 | `3ad1b46` | Cifras vigentes: matriz, README, plan, manual, índice de evidencias y mapeo con la suite final del 14-11 (1.770 casos, 95,70 %) y SonarQube en OK; nota fechada del video | 10 | +79 / −42 | sí (10) |
| 00:59 | `e073dc8` | Documentos: rendimiento del plan de evolución, índice de evidencias y despliegue con las mediciones vigentes | 4 | +12 / −13 | sí (4) |
| 01:03 | `f4640cb` | Evidencia de réplica: tests/replica completo sobre el código final (209 de 209), escrito por scripts/evidencia_pytest.py | 2 | +217 / −225 | sí (2) |
| 01:04 | `15e6a42` | Documentos: E01, E02 y presentación recompilados con las cifras finales (2, 16 y 14 páginas) | 13 (11 binarios) | +36 / −36 | sí (13) |
| 01:05 | `dc67bce` | Historial de desarrollo al día con la rama de evidencia final (224 commits, con las fusiones de las ramas de evidencia) | 1 | +209 / −6 | sí (1) |
| 01:08 | `47acba8` | Índice de evidencias: filas de los dos archivos de bordes de la retención | 1 | +2 / −0 | sí (1) |
| 01:08 | `19110d1` | Historial de desarrollo al día con el último commit de la consolidación | 1 | +7 / −5 | sí (1) |
| 01:20 | `2428d3e` | Auditoría: la matriz describe los arreglos de la política de reentrenamiento (RF-018c) y de los guiones con réplicas (RNF-005), y RF-018d dice dónde queda la aprobación | 1 | +3 / −3 | sí (1) |
| 01:20 | `67899da` | Auditoría: la corrida de k6 del 9-11 lleva su fecha en los README, el cliente HTTP y la etiqueta de etapas en despliegue.md, la ALT-002 de un ciclo anterior en el documento de alertas y el conteo viejo de ci_github.txt | 5 | +12 / −7 | sí (5) |
| 01:40 | `3916c95` | Auditoría: la integración continua en copia limpia se repite sobre el código final (14-11: 7 de 7 pasos, 1.773 casos sin fallas, 95,15 % y caída 3 de 3), con sus cifras en la matriz y en los índices de evidencia | 9 | +11.235 / −4.744 | sí (9) |
| 01:41 | `b31e17d` | Auditoría: E01, E02 y la presentación citan la corrida vigente de k6 (13-11, volumen de un año: p95 de 864 ms) y las 49 comprobaciones de la prueba de caída con Docker; recompilados (2, 16 y 14 páginas) | 16 (11 binarios) | +20 / −14 | sí (16) |
| 01:42 | `d71d40e` | Historial de desarrollo al día con los commits de la auditoría | 1 | +10 / −5 | sí (1) |
| 01:44 | `3390594` | Evidencia final en main: contrato, réplica, despliegue y rendimiento sobre el código final, cuatro arreglos con su revisión, documentos consolidados y auditoría | fusión | — | — |
| 01:45 | `e3168d7` | Historial de desarrollo al día con la fusión de la evidencia final en main | 1 | +8 / −6 | sí (1) |
| 08:00 | `e61e999` | Entrega pública: sin rutas de la máquina local ni menciones de otros repositorios, integración continua del 14-11 y anexo del informe con la disposición del repositorio de entrega | 31 (12 binarios) | +92 / −84 | sí (25) |
