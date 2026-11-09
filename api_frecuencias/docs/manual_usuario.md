# Manual de usuario · API de frecuencias

Para el despachador, el jefe de operación o el jurado. La API se usa desde el navegador en **Swagger**
(http://localhost:8000/docs): cada endpoint tiene «Try it out», un ejemplo de entrada y la respuesta. Cómo levantarla:
`../README.md` (dos comandos con Docker).

## 1. Las cuatro preguntas y dónde se ven

| Quiero saber… | Endpoint | Qué mirar en la respuesta |
|---|---|---|
| Cuántos pasajeros vienen en la próxima hora | `POST /api/v1/predictions/run` | pasajeros esperados, banda p10-p90, `model_id`, explicación |
| Cada cuánto despachar | `POST /api/v1/recommendations/calculate` | `headway_min`, `buses_hora`, frente a `frecuencia_actual_min` |
| Cuántos buses necesito | la misma | `vehiculos_requeridos` y `viable` (si es `false`, el `motivo`) |
| Qué requiere atención ya | `GET /api/v1/alerts?estado=nueva` | severidad, explicación, observado frente a esperado, recomendación |

Severidades: **crítica** (actuar ahora), **preventiva** (revisar en la hora), **informativa** (para planear).

## 2. Recorrido de la demostración (unos 5 minutos)

1. **Llegan datos nuevos y se procesan.** En `POST /api/v1/frequency/executions`, «Try it out», escriba
   `{"hasta": "2025-06-10"}` (los datos disponibles llegan hasta ese día) y «Execute». Copie el `execution_id` de la
   respuesta. Para simular el día siguiente, repita con `"hasta": "2025-06-11"`.
2. **Seguir la ejecución.** En `GET /api/v1/frequency/executions/{execution_id}` vea la etapa y el progreso, la marca de
   agua anterior y la nueva (solo se leyó lo nuevo) y cuántas filas se aceptaron o rechazaron. Los errores de calidad, con
   su lote, fila y causa, están en la lista de errores de esa ejecución.
3. **Repetir la ejecución.** Ejecute de nuevo el paso 1: no se duplica nada, porque no hay datos posteriores a la marca.
4. **Ver los resultados.** `GET /api/v1/predictions`, `GET /api/v1/recommendations` y `GET /api/v1/alerts`, filtrando
   por ruta (`SILENCIO`, `CRA 54` o `CL 72`).
5. **Gestionar una alerta.** En `PATCH /api/v1/alerts/{id}/status` envíe `reconocer` con su usuario y un comentario;
   después `asignar` (con `asignado_a`) y, resuelta, `cerrar`. Si no procede, `descartar` (en cualquier momento antes de
   cerrarla). `comentar` agrega una nota sin cambiar el estado. El historial de la alerta conserva cada cambio.
6. **Modelo candidato frente al activo.** `POST /api/v1/models/train` con `{"hasta": "2025-06-10"}` entrena un candidato
   con los datos ya validados. En `GET /api/v1/models` compare sus métricas (WAPE, MAE, RMSE, por ruta, pico y valle) con
   las del activo y su fecha de corte.
7. **Activar o rechazar.** `POST /api/v1/models/{id}/activate` con `aprobado_por` y el motivo. Si el WAPE del candidato
   no es menor o igual que el del activo en la misma validación, la API no lo activa y deja registrada la decisión; si lo
   activa, el anterior queda guardado y `POST /api/v1/models/rollback` vuelve a él.

## 3. Leer una recomendación

Ejemplo: CRA 54 a las 7 de la mañana con 620 pasajeros esperados (p90 = 700) y buses de 50 puestos llenos al 85 %:

- capacidad efectiva = 50 × 0,85 = 42,5 pasajeros por bus;
- buses por hora = ⌈700 / 42,5⌉ = 17 → un bus cada 60 / 17 ≈ 3,5 minutos;
- vehículos = ⌈tiempo de ciclo / headway⌉; si pasa de la flota disponible, la recomendación sale **no viable** y dice por
  qué, en lugar de inventar una cifra.

La respuesta trae esa misma cuenta en el campo `formula`.

## 4. Exportar

Las consultas de predicciones, recomendaciones y alertas se pueden exportar filtradas en CSV o XLSX (ver la sección de
exportación en Swagger); el archivo trae las mismas columnas que la respuesta JSON.

## 5. Si algo falla

| Síntoma | Qué hacer |
|---|---|
| Swagger no abre | Revise que `docker compose ps` muestre `api` y `db` en ejecución; vea `docker compose logs api`. |
| La ejecución queda en `error` | Abra `GET /frequency/executions/{id}`: el campo de errores dice la etapa y la causa. La marca de agua no avanzó, así que puede relanzarla. |
| `viable = false` | No alcanza la flota o el headway mínimo para esa demanda: el `motivo` lo explica. Es una respuesta válida. |
| Error 422 | Un campo de la petición no es válido (por ejemplo, un horizonte distinto de 30, 60 o 120); el mensaje dice cuál. |
