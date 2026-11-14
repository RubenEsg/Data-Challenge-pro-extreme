# Evidencias del tablero (Dash)

El tablero (`EntregaFinal/dash_app`) es la cara de la API para la operación. Cubre el entregable E06 (prototipo con API,
tablero, predicción, recomendación y alertas), §3.1 «Consulta y tablero», RNF-012 y el criterio «Presentación y
adopción». Muestra primero el producto, es decir, el modelo que ejecuta la API. Los experimentos del informe académico
quedan aparte, rotulados «experimento 11 / experimento 12». Aquí está lo que se comprobó y con qué archivo.

**Cómo se corrió.**

- **API.** Una API de desarrollo (uvicorn) sobre una base de pruebas propia en el PostgreSQL local (puerto 5433,
  migrada con `alembic upgrade head` hasta la 0006). Usó una copia temporal de `datos/` y la autenticación encendida,
  con claves de prueba por rol.
- **Datos sembrados.** Un ciclo de demostración corto:
  - tres ejecuciones diarias, con datos hasta el 1, el 2 y el 3 de septiembre de 2025;
  - un candidato entrenado con datos hasta el 3 de septiembre, que quedó en sombra;
  - 69 pronósticos del modelo activo para el 4 de septiembre de 2025 con `POST /api/v1/predictions/run`: las tres
    rutas, cada hora de 4 a 20 h con 60 min y, a las 6, 12 y 17 h, también con 30 y 120 min. Así Pronóstico tiene un
    día completo para comparar con lo real.
- **Tablero.** Tres instancias leyeron esa API:
  - con la clave de analista, que es la del tablero porque pide el cálculo de la respuesta del reto;
  - con la de operador;
  - con una clave inválida.

Las cifras de las capturas son las de ese ciclo de demostración, no las de la operación real.

## Recorrido de punta a punta

`e2e_tablero_completo.txt` (y `.json` con el detalle): **135 de 135 comprobaciones bien** con Edge sin interfaz a 1600×900, el
9 de noviembre de 2026 de 07:05 a 07:08, con el código de la API del momento. El script es `e2e_tablero_completo.py`.

| Qué | Resultado |
|---|---|
| Las once pantallas | Cargan con su título, 0 errores de consola y sin desplazamiento horizontal |
| Teclado (RNF-012) | En **las once pantallas** Tab recorre la barra y después los controles de la pantalla en orden de lectura, siempre con el foco visible. También el botón de atribución del mapa de Despacho, que ahora usa el contorno de la app |
| Contraste (WCAG AA) | Todo el texto visible de las once pantallas pasa 4,5:1 (3:1 el texto grande); el mínimo medido es 3,45:1, en texto de 24 px o más |
| Pronóstico · «Modelo activo (API)» | Frente a `GET /api/v1/predictions` (ruta CRA 54, el 4 de septiembre de 2025, 60 min): una ventana por instante del día (17), el modelo `hgb_fv2_20250831_s42` y la calibración v2, la banda P10–P90 con el P50 y lo real, la paginación de la API («Siguiente» trae la página 2), las variables SHAP del pronóstico elegido con su efecto (iguales a `GET /predictions/{id}`) y su banda. Exporta CSV y XLSX (`export_predicciones_dash.csv` y `.xlsx`, de `GET /predictions/export`) |
| Pronóstico · laboratorio | Rotulado «Laboratorio del informe académico: experimento 11 / experimento 12», con el aviso de que no es el modelo de la API ni se compara con sus cifras. En toda la pantalla no aparece «modelo final» ni «E11/E12» a secas |
| El modelo | La primera tarjeta es el modelo del producto, con sus cifras iguales a `../modelo/evaluacion_modelo.json` (14,77 % frente a 21,18 % de la regla manual en nov–dic 2025) y a `../modelo/calibracion_condicional.json` (cobertura v2 77,82 %). Declara que esa prueba es un reporte informativo. Su importancia es igual a `GET /models/{id}/importance` (media de \|SHAP\|). Los experimentos del informe van después, en su sección rotulada |
| Inicio · respuesta del reto (§7.1) | Se crea una versión nueva de los umbrales con los mismos valores (`PUT /thresholds`). La foto de la respuesta queda vieja: `GET /respuesta` responde 404 «sin_calcular». La tarjeta muestra «Calculando…» (`dash_inicio_calculando.png`), pide `POST /respuesta/calcular`, que queda como una ejecución «respuesta» de la cola terminada en «ok», y vuelve a consultar cada 3 s hasta tener la respuesta (3,3 s desde que se abre la pantalla). Pasajeros esperados y vehículos de la hora pico iguales a la API. La trazabilidad nombra el modelo, la calibración de la banda y la fuente del pronóstico del plan, y «Atención inmediata» dice que son las alertas abiertas ahora. CRA 54 y CL 72 también pasan por «Calculando…». El «…» trae la tabla hora por hora. Exporta CSV y XLSX (`export_respuesta_dash.csv` y `.xlsx`) |
| Alertas (§3.1, §5.3, §7.2) | La bandeja va en orden de prioridad (crítica → preventiva → informativa) e igual a `GET /alerts?orden=prioridad`. El chip «Escalada» coincide con las alertas que tienen «escalar» en su bitácora: en este ciclo corto ninguna se redetectó con más severidad, así que hay 0 chips y 0 escaladas; la regla se prueba en `funciones_tablero.txt`. El detalle muestra los campos de §5.3 iguales a `GET /alerts/{id}` |
| Recomendaciones (§10.1, §10.2, RF-008, §18) | Escenario viable: la función objetivo término por término con la fuente de cada peso, las restricciones con su holgura y la frecuencia actual frente a la recomendada. Escenario no viable: el motivo y la mejor aproximación. Plan del día: el que guarda el ciclo con el pronóstico del modelo activo (`pronostico=activo`), con las salidas del día y una fila por hora iguales a `GET /recommendations/plan` |
| Monitoreo (§9.4, §9.5) | WAPE, MAE, sesgo y cobertura iguales a `GET /monitoring`; PSI por variable con su estado; la decisión de reentrenar igual a `/monitoring/policy`; el retador en sombra; exporta CSV y XLSX |
| Despacho (§3.2) | El subtítulo dice que es la repetición de un día de 2025 y que la consola no despacha ni cambia la operación |
| Operación › «Salud del servicio» | `/health` y `/metrics`, con 0 errores de consola (`dash_operacion_salud.png`) |
| Autenticación (§7.2) | Con la clave de operador, «Calcular escenario» muestra el 403 con el rol que falta y Monitoreo se sigue leyendo. Con una clave inválida, Inicio, Alertas, Recomendaciones, Operación y Monitoreo dicen «La API pide una clave válida» y qué hacer, sin trazas y con 0 errores de consola |

## Capturas a 1600×900

Una por pantalla:

- `dash_inicio.png`, `dash_pronostico.png`, `dash_horario.png`, `dash_despacho.png`;
- `dash_alertas.png`, `dash_recomendaciones.png`, `dash_operacion.png`, `dash_monitoreo.png`;
- `dash_modelo.png`, `dash_resultado.png` y `dash_enlaces.png`.

De las partes nuevas o revisadas:

- `dash_pronostico_api.png`: la sección «Modelo activo (API)»;
- `dash_inicio_calculando.png` y `dash_inicio_respuesta.png`: la respuesta asíncrona y la tarjeta llena;
- `dash_operacion_salud.png`: «Salud del servicio»;
- `dash_alertas_detalle.png`;
- `dash_recomendaciones_escenario.png`, `dash_recomendaciones_no_viable.png` y `dash_recomendaciones_plan.png`;
- `dash_monitoreo_politica.png`;
- `dash_auth_operador_403.png`, `dash_auth_401_inicio.png` y `dash_auth_401_alertas.png`.

Cada pantalla tiene además su captura de página completa (`dash_<pantalla>_completa.png`).

**Nota del 14-11-2026.** Las capturas de Inicio, Horario y Resultado son anteriores a un cambio de presentación. En
Inicio y en Resultado, las dos tarjetas del saldo («contabilidad conservadora», con un chip rojo de «saldo negativo», y
«contabilidad simétrica») pasaron a ser la decisión que se propone, en tres pasos: primero el piloto que lo mide (−51,9
M COP en sus ocho semanas si las salidas nuevas no atraen a nadie); si atraen suficientes pasajeros, el plan se aplica
(0 a +1.600 M COP al año); si atraen menos, no se aplica. Debajo va el aviso «¿Qué tan probable es cada caso?», que dice
que no hay base para una probabilidad y lo que el piloto puede y no puede decir en ocho semanas. En Horario, cada uno
de los dos saldos del día dice qué supone, con chip neutro. Las cifras son las mismas (−2.825 y +1.600 M COP al año) y
hay nuevas: el umbral de la respuesta de los pasajeros a las salidas que se ponen (0,44 a 0,53 según la forma de la
cuenta; 0,33 a 0,66 con todo el rango de β), las pistas que hay de esa respuesta y lo que deja el piloto con otras β
(−70,2 con β = 0,90; −79,0 con la pérdida proporcional, β = 1, a partir de la cual una regla de parada lo detiene). Las
comprueba `dash_app/verificar_ahorro.py`. Las capturas de la presentación nueva, tomadas el 14-11-2026 del tablero en
marcha, son `dash_inicio_decision.png` (su «…», en `dash_inicio_decision_datos.png`; a 400 px, en
`dash_inicio_decision_400.png`), `dash_resultado_decision.png` y `dash_horario_balance.png`.

## Estilo, cifras y funciones

| Archivo | Resultado |
|---|---|
| `verificar_estilo_estatico_once.txt` | `python verificar_estilo.py`: PASA · 27 bien · 2 avisos · 0 fallas (corrida del 14-11-2026). Los dos avisos son números sueltos en El modelo y Pronóstico, y ya estaban |
| `verificar_estilo_vivo_once.txt` | `python verificar_estilo.py --vivo PUERTO`: PASA · 49 bien · 2 avisos · 0 fallas en las once pantallas a 1366 y 400 px (corrida del 14-11-2026, ya con la tarjeta de la decisión). Como mucho 8 tamaños de letra, solo colores de la paleta, encabezados sin saltos y nada se sale a 400 px. Antes de esta corrida, un mensaje de error de la API con una ruta larga ensanchaba «El modelo» a 400 px; ahora una palabra que no cabe en su caja se parte (`overflow-wrap` en `body`) |
| `verificar_ahorro_once.txt` | `python verificar_ahorro.py`: 407 OK, 0 FALLA (corrida del 14-11-2026, con las comprobaciones del umbral, de las pistas y del saldo del piloto) |
| `funciones_tablero.py` · `.txt` | 9 de 9: el orden de prioridad, el chip «Escalada» (con y sin «escalar» en la bitácora), los nombres «experimento 11 / 12» y lo real de una ventana (una hora, dos horas y fuera de 2025) |
| `despacho_carga_en_frio.txt` · `.py` | Cinco cargas en frío de Despacho sin errores de consola y con los buses en el mapa. La corrida anterior al arreglo quedó en `../historial/tablero_estilo_vivo_intento_despacho_en_frio.txt` |
| `barra_once_pestanas.txt` | Con once pestañas, la barra no se desborda de 1101 a 1920 px |

## Lo que queda a la vista

- **Plan del día leído de la base.** `GET /recommendations/plan` arma el plan con las filas que guarda el ciclo
  (`origen = 'plan_dia'`). Llegan el tipo de día, el estado del solver, el modelo, la calibración y, por hora, las
  salidas, el headway, los pasajeros y los límites. Faltan las salidas programadas del día, la flota y el costo, así que
  esas fichas de Recomendaciones muestran «—».
- **Vehículos de la hora pico.** Ese plan cuenta los vehículos de cada hora como techo(ciclo / headway): 83 en SILENCIO
  a las 5 h del 4 de septiembre, con 24 salidas y un ciclo de 206 min. La respuesta del reto los cuenta como buses en
  ruta a la vez (conteo de D5). Son dos definiciones distintas, y la API debe unificarlas o rotularlas; el tablero
  muestra la cifra de cada recurso tal como llega.
- **Escalamiento.** El ciclo corto no produjo ninguna alerta escalada. El chip se probó con la función y con la
  bitácora de la API; se verá en cuanto una redetección suba la severidad.
- **Despacho en frío.** El mapa de calles necesita internet (CARTO sobre OpenStreetMap). Si MapLibre avisa «Style is
  not done loading» en la primera carga, el recorrido lo anota como AVISO y repite la carga.
- **Contraste.** El mínimo medido (3,45:1) es de texto grande, que pide 3:1.
- **Archivos de una versión anterior del tablero (diez pestañas).** No describen la versión actual y se conservan como
  historial:
  - las capturas `*_1366x768.png`, `alertas_completa.png`, `operacion_completa.png`, `recomendaciones_completa.png` y
    `barra_1280.png`;
  - `e2e_tablero.txt` y `.json`, `e2e_tablero_auth.json` y `siete_pantallas_8205.txt`;
  - `verificar_estilo_estatico.txt`, `verificar_estilo_vivo_api_arriba.txt` y `verificar_estilo_vivo_api_caida.txt`;
  - `export_alertas_dash.*`, `export_recomendaciones_dash.*` y `pytest_export_alertas.txt`.
