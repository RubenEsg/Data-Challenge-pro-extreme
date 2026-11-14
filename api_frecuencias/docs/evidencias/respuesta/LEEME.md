# Evidencia: respuesta a la pregunta final del reto (§20)

> con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos
> pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?

El sistema la contesta en `GET /api/v1/respuesta` (y en `GET /api/v1/respuesta/export` como tabla CSV o XLSX). El
cálculo es asíncrono (§7.1):

- `POST /api/v1/respuesta/calcular` (rol analista) encola una ejecución de tipo «respuesta» y responde 202 con su
  `execution_id`;
- el trabajador de la cola pronostica cada hora con el modelo activo, resuelve el plan del día con los umbrales
  vigentes y guarda una foto por ruta en `ai_frecuencias.respuesta_reto`. El ciclo diario hace lo mismo al cerrar,
  para el día siguiente al último dato;
- el GET solo lee la foto; sin foto responde 404 `sin_calcular` con la pista del POST.

El servicio es `app/servicios/respuesta.py` (`precalcular`, `leer`, `solicitar_calculo`); el contrato está en
`app/routers/respuesta.py`. La respuesta escrita para el jurado, con todas las cifras, está en
`../../../../documentos/respuesta_pregunta_reto.md`.

| Archivo | Qué muestra | Cómo se generó |
|---|---|---|
| `respuesta_reto.md` | Tablas por día, ruta, franja y hora: cada cuánto despachar frente a lo programado, viabilidad, pasajeros con P10–P90 y su contraste con lo observado, vehículos frente a la flota, flota y recaudo, alertas abiertas ahora y de la fecha, y la ejecución de la cola que calculó cada día | `python scripts/respuesta_reto.py --en-vivo`: base temporal en el PostgreSQL local (migrada con `alembic upgrade head` y borrada al final), copia temporal de `datos/`, una corrida del ciclo diario hasta el 31-dic-2025 y una ejecución «respuesta» por fecha |
| `respuesta_2025-11-19.json`, `respuesta_2025-11-22.json`, `respuesta_2025-11-23.json` | La respuesta completa de la API, leída desde la foto, para un laboral, un sábado y un domingo de noviembre de 2025, más `contraste_observado` (que la API no devuelve) y `calculo_en_la_cola` (ejecución, estado y segundos) | El mismo script |
| `respuesta_2026-01-01.json` | La respuesta para el día siguiente al último dato de la API (los datos llegan al 31-dic-2025): festivo de Año Nuevo, con tipo de día «Domingo/festivo» y `fuente_pronostico` `modelo_activo` | El mismo script |
| `api_en_vivo.txt` | La API por HTTP: sin clave 401, operador 403 en el POST, ruta fuera de la lista 422, fecha sin foto 404 `sin_calcular` con la pista, analista 202, sondeo de la ejecución hasta «ok», lectura desde la foto (mediana de 21 lecturas), trazabilidad, alertas abiertas ahora y exportación CSV y XLSX | El mismo script con `--en-vivo`: uvicorn en 127.0.0.1 (puerto 8503 o el de `RESPUESTA_RETO_PUERTO`; esta corrida usó 8361 y, para no compartir la base con otras corridas en curso, la base temporal `ai_frecuencias_pruebas_ev_despliegue_respuesta` en lugar de la de `BASE_TEMPORAL`) contra la base temporal, autenticación encendida, un trabajador de la cola y claves generadas para la corrida |
| `api_respuesta_CRA54_2025-11-19.json` | Una respuesta completa por HTTP (CRA 54, 19-nov-2025) con `atencion_inmediata` llena, `alertas_de_la_fecha`, `atencion_resumen` y el `execution_id` del cálculo | La misma corrida |
| `pytest_respuesta.txt` | Las pruebas unitarias y de integración de la respuesta | `pytest tests/unit/test_respuesta.py tests/integracion/test_respuesta_api.py -rA` |

Qué verifican las pruebas:

- el contrato completo y la pregunta literal de §20;
- que cada cifra coincide con el plan del día (`optimizacion.plan_dia`), con lo programado (D1) y con el modelo activo
  (`inferencia.predecir`), y que el plan y los pasajeros salen del mismo pronóstico;
- la viabilidad: una hora donde la demanda pide más salidas de las que permite el headway mínimo gobernado (el plan
  programa el tope), flota excedida o solver no óptimo salen `viable = false` con el motivo;
- la regla de la espera máxima (supuesto S12): bajar `espera_max_min` baja el headway máximo efectivo y vuelve no
  viable una hora que antes lo era;
- la fecha por omisión: el día siguiente al último dato de la serie empaquetada o de `demanda_observada`;
- el recaudo con la tarifa neta de `param_d5(fuente=True)` y la nota de §19;
- las alertas abiertas ahora (críticas primero, sin cerradas ni descartadas, rotuladas «abierta ahora») y las de la
  fecha consultada, en cualquier estado, con el día de Bogotá;
- §7.1: `POST /api/v1/respuesta/calcular` responde 202 y deja la ejecución «ok» en la cola; el GET responde 200 desde la
  foto sin pronosticar ni resolver el MILP (la prueba lo prohíbe durante el GET); una foto se reemplaza sin duplicarse
  y un cálculo igual en cola no se duplica;
- 404 `sin_calcular` con la pista, ruta fuera de la lista blanca 422, sin clave 401, operador 403 en el POST;
- un festivo usa la programación de domingo o festivo y la respuesta lo advierte;
- todo instante en America/Bogota (-05:00, §8.1).
