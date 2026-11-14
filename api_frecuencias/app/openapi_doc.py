"""Contrato OpenAPI veraz (spec v1.5 §12.1, §12.2 y RNF-009) y guarda contra el byte NUL.

El documento que genera FastAPI se completa en un solo lugar para que diga exactamente lo que la API responde:

- cada operación declara los errores que de verdad puede devolver, todos con el error uniforme ``RespuestaError``
  ({"error": {codigo, mensaje, detalle, correlation_id}}): 401 (sin clave o clave inválida), 403 (solo donde el rol
  mínimo de ``app.seguridad.POLITICA`` es mayor que operador), 404 (operaciones con parámetro de ruta y las que
  buscan una ruta, un modelo o un plan), 409 (conflictos de estado: activar, revertir, transiciones de alerta),
  422 (validación, en todas: la guarda NUL también mira las cabeceras), 503 (dependencia degradada, RNF-010) y 500;
- cada respuesta de error enumera en «x-codigos-error» los valores posibles del campo «codigo» (los generales y los
  propios de la operación, como «ventana_en_muestra», «requiere_forzar» o «sin_calcular»); los propios van también
  en la descripción;
- el 422 deja de documentarse como ``HTTPValidationError`` {"detail": [...]}: la API responde el error uniforme;
- /metrics se documenta como text/plain (formato de Prometheus) y cada exportación como text/csv y xlsx;
- los filtros que una operación exige «uno de varios» quedan en la descripción y en ``x-requiere-uno-de``;
- cada operación de /api/v1 lleva su rol mínimo en ``x-rol-minimo`` y en la descripción.

La guarda NUL (``GuardaNul``) rechaza con el 422 uniforme toda petición con el byte 0x00 (o %00) en la ruta, la
consulta, una cabecera o un cuerpo JSON: PostgreSQL no admite NUL en text ni en jsonb y, sin la guarda, el valor
llegaría a SQL y respondería 500. Con la misma idea, un valor que desborda la aritmética de fechas (OverflowError) o
que PostgreSQL no puede representar (SQLSTATE 22003 y 22008, p. ej. un entero de 64 bits en un filtro sin cota)
responde el 422 uniforme «fuera_de_rango», sin mostrar la sentencia SQL.

Las pruebas de tests/contrato/ verifican este documento contra las respuestas reales (Schemathesis y jsonschema) y
contra el código (cada ``ErrorApi(<código>)`` de un router está declarado en su operación).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import parse_qsl

from fastapi import FastAPI

PREFIJO = "/api/v1"
# Rutas que aparecen en varias tablas de este módulo (errores, códigos y filtros obligatorios por operación)
RUTA_PRONOSTICO_SEGMENTOS = "/api/v1/predictions/segmentos"
RUTA_CAPACIDAD = "/api/v1/catalogos/capacidad"
RUTA_REFRESCO_SEGMENTOS = "/api/v1/segmentos/estadisticas/refrescar"
RUTA_FLOTA = "/api/v1/catalogos/flota"
# Ajustes locales versionados (capacidad, flota y ciclo): leen el catálogo empaquetado y threshold_config, no la
# réplica, así que no llevan los códigos de error de los catálogos de Extreme.
RUTAS_AJUSTE_LOCAL = (RUTA_CAPACIDAD, RUTA_FLOTA)
XLSX ="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REF_ERROR = {"$ref": "#/components/schemas/RespuestaError"}
log = logging.getLogger("api_frecuencias.http")

DESCRIPCIONES = {
    400: "Cuerpo ilegible: no se pudo decodificar el cuerpo de la solicitud (p. ej. bytes que no son UTF-8); "
         "código «cuerpo_ilegible».",
    401: "Sin autenticación: falta la cabecera X-API-Key o la clave no es válida (código «no_autenticado»).",
    403: "Prohibido: el rol de la clave está por debajo del rol mínimo de la operación (código «prohibido»).",
    404: "No encontrado: el recurso indicado no existe (código «no_encontrado» u otro más específico).",
    409: "Conflicto con el estado actual del recurso (p. ej. transición de alerta no permitida o activación "
         "rechazada por la gobernanza del modelo).",
    422: "Validación: el cuerpo, la consulta, la ruta o una cabecera no es válida, incluido el byte NUL (código "
         "«validacion», con detalle [{campo, mensaje, tipo}], u otro más específico).",
    500: "Error no controlado: el cuerpo trae el correlation_id para ubicarlo en el log (código «error_interno»).",
    503: "Dependencia no disponible o no configurada (réplica, base operacional o archivo de insumos): degradación "
         "prevista con el error uniforme (RNF-010).",
}

# Errores propios de cada operación, además de las reglas generales (401/403/422/500 en toda /api/v1 y 404 donde hay
# parámetro de ruta). tests/contrato/test_contrato_openapi.py comprueba que todo código que lanza el código del
# router está aquí o en las reglas generales.
ERRORES_POR_OPERACION: dict[tuple[str, str], set[int]] = {
    ("post", "/api/v1/predictions/run"): {404},
    ("get", RUTA_PRONOSTICO_SEGMENTOS): {404, 503},
    ("post", "/api/v1/recommendations/calculate"): {404},
    ("get", "/api/v1/recommendations/plan"): {404},
    ("post", "/api/v1/models/rollback"): {404, 409},
    ("post", "/api/v1/models/{model_id}/activate"): {409},
    ("get", "/api/v1/models/{model_id}/evaluation"): {409},
    ("get", "/api/v1/models/{model_id}/importance"): {409},
    ("patch", "/api/v1/alerts/{alert_id}/status"): {409},
    ("get", RUTA_CAPACIDAD): {404},
    ("put", RUTA_CAPACIDAD): {404},
    ("get", RUTA_FLOTA): {404},
    ("put", RUTA_FLOTA): {404},
    ("get", "/api/v1/respuesta"): {404},
    ("post", "/api/v1/respuesta/calcular"): {404},
    ("get", "/api/v1/respuesta/export"): {404},
    ("post", RUTA_REFRESCO_SEGMENTOS): {503},
}
# Valores del campo «codigo» del error uniforme. Los GENERALES valen donde la operación declara su estado (el 404
# «no_encontrado», donde hay parámetro de ruta; «orden_invalido», donde hay parámetro «orden»); los PROPIOS salen del
# router de cada operación. Cada respuesta de error los enumera en «x-codigos-error» y los propios también en su
# descripción. tests/contrato/test_contrato_openapi.py comprueba que cada ErrorApi(<estado>, "<código>") que puede
# lanzar un endpoint (o sus auxiliares del mismo módulo) está declarado aquí, en su operación y con su estado.
CODIGOS_GENERALES: dict[int, tuple[str, ...]] = {
    400: ("cuerpo_ilegible",), 401: ("no_autenticado",), 403: ("prohibido",), 404: ("no_encontrado",),
    422: ("validacion", "fuera_de_rango"), 500: ("error_interno",)}
_CODIGOS_CATALOGOS = {422: ("filtro_invalido",), 500: ("operacion_no_permitida",),
                      503: ("catalogo_no_disponible", "fuente_no_disponible")}
_CODIGOS_SEGMENTOS = {422: ("parametro_invalido",), 503: ("fuente_no_disponible",)}
CODIGOS_POR_OPERACION: dict[tuple[str, str], dict[int, tuple[str, ...]]] = {
    ("get", "/api/v1/frequency/executions"): {422: ("rango_invalido",)},
    ("post", "/api/v1/frequency/executions"): {422: ("ruta_desconocida",)},     # RNF-005: partición por ruta
    ("post", "/api/v1/predictions/run"): {404: ("ruta_desconocida", "modelo_no_encontrado"),
                                          422: ("parametros_invalidos", "prediccion_invalida")},
    ("get", RUTA_PRONOSTICO_SEGMENTOS): {
        404: ("no_encontrado", "ruta_desconocida", "modelo_no_encontrado", "ruta_sin_segmentos"),
        422: ("parametros_requeridos", "horizonte_invalido", "prediccion_invalida"),
        503: ("reparto_no_disponible",)},
    ("post", "/api/v1/recommendations/calculate"): {404: ("no_encontrado", "ruta_desconocida"),
                                                    422: ("parametros_invalidos",)},
    ("get", "/api/v1/recommendations/plan"): {404: ("sin_calcular", "plan_no_disponible", "ruta_desconocida")},
    ("patch", "/api/v1/alerts/{alert_id}/status"): {409: ("transicion_invalida",), 422: ("datos_incompletos",)},
    ("post", "/api/v1/models/rollback"): {404: ("no_encontrado",), 409: ("sin_version_anterior",)},
    ("post", "/api/v1/models/{model_id}/activate"): {
        409: ("ya_activo", "requiere_forzar", "activacion_rechazada", "sin_datos_validacion", "validacion_fallida"),
        422: ("ventana_en_muestra", "motivo_requerido", "sin_ventana_validacion")},
    ("get", "/api/v1/models/{model_id}/evaluation"): {404: ("modelo_no_encontrado",), 409: ("integridad_modelo",),
                                                      422: ("ventana_invalida", "sin_datos")},
    ("get", "/api/v1/models/{model_id}/importance"): {404: ("modelo_no_encontrado",), 409: ("integridad_modelo",)},
    ("put", "/api/v1/thresholds"): {422: ("umbral_invalido",)},
    ("get", RUTA_CAPACIDAD): {404: ("no_encontrado",), 422: ("tipologia_invalida",)},
    ("put", RUTA_CAPACIDAD): {404: ("no_encontrado", "ajuste_inexistente"),
                              422: ("ruta_desconocida", "capacidad_invalida")},
    ("get", RUTA_FLOTA): {404: ("no_encontrado",)},
    ("put", RUTA_FLOTA): {404: ("ajuste_inexistente",), 422: ("ruta_desconocida", "ajuste_invalido")},
    ("get", "/api/v1/monitoring/feature-snapshots"): {422: ("filtro_requerido",)},
    ("get", "/api/v1/respuesta"): {404: ("sin_calcular",)},
    ("post", "/api/v1/respuesta/calcular"): {404: ("sin_datos",)},
    ("get", "/api/v1/respuesta/export"): {404: ("sin_calcular",)},
    ("get", "/api/v1/segmentos/estadisticas/export"): {503: ("agregacion_pendiente",)},
    ("post", RUTA_REFRESCO_SEGMENTOS): {422: ("parametro_invalido",),
                                        503: ("fuente_no_configurada", "fuente_no_disponible")},
}
# Lecturas que dependen de una fuente externa que puede degradarse (réplica de Extreme o base operacional): 503.
DEGRADABLES = ("/api/v1/catalogos", "/api/v1/segmentos")
# Operaciones que exigen al menos uno de varios filtros (OpenAPI no puede marcar «uno de» en parámetros).
UNO_DE: dict[tuple[str, str], list[list[str]]] = {
    ("get", RUTA_PRONOSTICO_SEGMENTOS): [["prediction_id"], ["ruta", "instante"]],
    ("get", "/api/v1/monitoring/feature-snapshots"): [["execution_id"], ["prediction_id"], ["ruta"]],
}
METODOS = ("get", "post", "put", "patch", "delete")
# §12.1: toda respuesta (éxito o error) lleva X-Correlation-Id; el 401 dice cómo autenticarse (RFC 9110 §11.6.1)
CABECERA_CORRELACION = {"X-Correlation-Id": {
    "description": "Identificador de correlación: el de la petición si se envió, o uno nuevo; aparece en el log y en "
                   "la traza (RNF-006)", "required": True, "schema": {"type": "string"}}}
CABECERA_AUTENTICACION = {"WWW-Authenticate": {"description": 'Siempre «ApiKey header="X-API-Key"»',
                                               "required": True, "schema": {"type": "string"}}}
CABECERA_ADJUNTO = {"Content-Disposition": {"description": "attachment; filename=\"<nombre>_<AAAAMMDD_HHMMSS>.<ext>\"",
                                            "schema": {"type": "string"}}}
ETIQUETAS = {
    "ejecuciones": "Ciclo completo por ejecución: lectura incremental, calidad, predicción, recomendación, alertas "
                   "y notificaciones (job en segundo plano con cola en PostgreSQL)",
    "predicciones y recomendaciones": "Pronóstico de demanda 30/60/120 min con banda P10-P90 y recomendación de "
                                      "frecuencia y flota (§10.2), plan D5 del día y exportaciones",
    "alertas": "Alertas ALT-001..ALT-010 (§5): consulta por filtros y por lugar, gestión de estado y bitácora",
    "modelos": "Registro de modelos: entrenamiento, evaluación, importancia, activación controlada y reversión",
    "umbrales": "Umbrales y pesos versionados (threshold_config)",
    "monitoreo del modelo": "Monitoreo (§9.4), foto de variables y política de aprendizaje continuo",
    "planificador": "Planificador interno y estado de la cola",
    "catálogos": "Catálogos operacionales de solo lectura (§3.1) y ajustes locales versionados de capacidad, flota "
                 "y tiempo de ciclo",
    "segmentos": "Capa analítica por segmento y zona (§6.1, §6.2)",
    "respuesta del reto": "Respuesta a la pregunta final del reto con la trazabilidad de cada cifra",
    "retención": "Política de retención de datos (§18): parámetros gobernados, tarea automática y su bitácora",
    "sistema": "Salud del servicio y métricas Prometheus",
}
DESCRIPCION_GENERAL = (
    "\n\n**Contrato.** Autenticación con la cabecera `X-API-Key` (roles operador, analista y admin; el rol mínimo de "
    "cada operación está en su descripción y en `x-rol-minimo`). Todo error responde el formato uniforme "
    "`{\"error\": {\"codigo\", \"mensaje\", \"detalle\", \"correlation_id\"}}` (esquema RespuestaError). Toda "
    "respuesta lleva `X-Correlation-Id`. Todo instante sale en ISO-8601 con la zona de America/Bogota (-05:00).")


def _con_cabeceras(respuesta: dict, codigo: str, ruta: str) -> dict:
    cabeceras = dict(CABECERA_CORRELACION)
    if codigo == "401":
        cabeceras.update(CABECERA_AUTENTICACION)
    if codigo == "200" and ruta.endswith("/export"):
        cabeceras.update(CABECERA_ADJUNTO)
    respuesta["headers"] = {**cabeceras, **(respuesta.get("headers") or {})}
    return respuesta


def codigos_de(metodo: str, ruta: str, estado: int, op: dict | None = None) -> tuple[list[str], list[str]]:
    """(todos, propios): valores de «codigo» que puede traer el error `estado` de una operación. Los propios son los
    que no son generales (los del grupo de rutas y los de CODIGOS_POR_OPERACION)."""
    generales = list(CODIGOS_GENERALES.get(estado, ()))
    if estado == 404 and "{" not in ruta:
        generales = []
    if estado == 422 and any(p.get("name") == "orden" for p in (op or {}).get("parameters", [])):
        generales.append("orden_invalido")
    grupo: dict[int, tuple[str, ...]] = {}
    if metodo == "get" and ruta.startswith("/api/v1/catalogos") and not ruta.startswith(RUTAS_AJUSTE_LOCAL):
        grupo = _CODIGOS_CATALOGOS
    elif metodo == "get" and ruta.startswith("/api/v1/segmentos"):
        grupo = _CODIGOS_SEGMENTOS
    propios: list[str] = []
    for c in (*grupo.get(estado, ()), *CODIGOS_POR_OPERACION.get((metodo, ruta), {}).get(estado, ())):
        if c not in propios and c not in generales:
            propios.append(c)
    return generales + propios, propios


def _respuesta_error(codigo: int, previa: dict | None = None,
                     codigos: tuple[list[str], list[str]] | None = None) -> dict:
    descripcion = DESCRIPCIONES[codigo]
    if previa and previa.get("description") and previa["description"] not in ("Validation Error",
                                                                              "Successful Response"):
        descripcion = previa["description"]
    todos, propios = codigos or ([], [])
    if propios:
        linea = "Códigos propios de esta operación: " + ", ".join(f"«{c}»" for c in propios) + "."
        if linea not in descripcion:
            descripcion = f"{descripcion} {linea}"
    respuesta = {"description": descripcion, "content": {"application/json": {"schema": dict(REF_ERROR)}}}
    if todos:
        respuesta["x-codigos-error"] = todos
    return respuesta


def _errores_de(metodo: str, ruta: str, op: dict) -> set[int]:
    from app.seguridad import rol_requerido

    codigos = {422, 500}
    if op.get("requestBody"):
        codigos.add(400)                                   # FastAPI no pudo leer el cuerpo (antes de validarlo)
    if ruta.startswith(PREFIJO):
        codigos.add(401)
        if rol_requerido(metodo, ruta) != "operador":
            codigos.add(403)
        if "{" in ruta:
            codigos.add(404)
        if metodo == "get" and ruta.startswith(DEGRADABLES):
            codigos.add(503)
    if ruta == "/metrics" and op.get("security"):
        codigos.add(401)                                   # METRICAS_PUBLICAS=false exige X-API-Key
    return codigos | ERRORES_POR_OPERACION.get((metodo, ruta), set())


def _componentes_error(esquema: dict) -> None:
    from app.esquemas import RespuestaError

    componentes = esquema.setdefault("components", {}).setdefault("schemas", {})
    generado = RespuestaError.model_json_schema(ref_template="#/components/schemas/{model}")
    for nombre, definicion in generado.pop("$defs", {}).items():
        componentes.setdefault(nombre, definicion)
    generado["description"] = "Error uniforme de la API (§12.1): toda respuesta 4xx y 5xx tiene esta forma."
    componentes["RespuestaError"] = generado


def _texto_rol(op: dict, rol: str) -> None:
    linea = f"Rol mínimo: **{rol}** (cabecera X-API-Key)."
    descripcion = op.get("description") or ""
    if linea not in descripcion:
        op["description"] = f"{descripcion}\n\n{linea}".strip()
    op["x-rol-minimo"] = rol


def _operaciones(esquema: dict):
    """(ruta, método, operación) de cada operación HTTP del documento."""
    for ruta, operaciones in esquema.get("paths", {}).items():
        for metodo, op in operaciones.items():
            if metodo in METODOS:
                yield ruta, metodo, op


def _ajustar_operacion(ruta: str, metodo: str, op: dict, rol_requerido) -> None:
    """Errores uniformes, rol mínimo, cuerpo de las exportaciones y filtro obligatorio de una operación."""
    respuestas = op.setdefault("responses", {})
    for codigo in sorted(_errores_de(metodo, ruta, op)):
        respuestas[str(codigo)] = _respuesta_error(codigo, respuestas.get(str(codigo)),
                                                   codigos_de(metodo, ruta, codigo, op))
    if ruta.startswith(PREFIJO):
        _texto_rol(op, rol_requerido(metodo, ruta))
    if ruta.endswith("/export"):
        cabeceras = (respuestas.get("200") or {}).get("headers")    # p. ej. X-Total-Count y X-Truncado
        respuestas["200"] = {
            "description": "Archivo con los registros filtrados (formato=csv, UTF-8 con BOM, o formato=xlsx)",
            "content": {"text/csv": {"schema": {"type": "string"}},
                        XLSX: {"schema": {"type": "string", "format": "binary"}}}}
        if cabeceras:
            respuestas["200"]["headers"] = cabeceras
    grupos = UNO_DE.get((metodo, ruta))
    if grupos:
        texto = " o ".join("+".join(g) for g in grupos)
        op["x-requiere-uno-de"] = grupos
        linea = f"Filtro obligatorio: indique {texto}; sin ninguno responde 422."
        if linea not in (op.get("description") or ""):
            op["description"] = f"{op.get('description') or ''}\n\n{linea}".strip()


def _ajustar_salud_y_metricas(esquema: dict) -> None:
    salud = esquema.get("paths", {}).get("/health", {}).get("get")
    if salud is not None:
        salud["responses"]["503"] = {"description": "Base de resultados sin conexión: el mismo cuerpo con "
                                                    "estado=degradado y base_datos=sin_conexion",
                                     "content": {"application/json": {"schema": {"type": "object"}}}}
    metricas = esquema.get("paths", {}).get("/metrics", {}).get("get")
    if metricas is not None:
        metricas["responses"]["200"] = {
            "description": "Métricas en el formato de texto de exposición de Prometheus (text/plain)",
            "content": {"text/plain": {"schema": {"type": "string"}}}}


def _quitar_esquemas_sin_uso(esquema: dict) -> None:
    """Los esquemas de validación de FastAPI salen del documento si ninguna operación los referencia."""
    componentes = esquema.get("components", {}).get("schemas", {})
    texto = json.dumps(esquema.get("paths", {}))
    for nombre in ("HTTPValidationError", "ValidationError"):
        if f"#/components/schemas/{nombre}\"" not in texto:
            componentes.pop(nombre, None)


def _descripcion_y_etiquetas(esquema: dict) -> None:
    info = esquema.setdefault("info", {})
    if DESCRIPCION_GENERAL.strip() not in (info.get("description") or ""):
        info["description"] = (info.get("description") or "") + DESCRIPCION_GENERAL
    usadas = {t for ops in esquema.get("paths", {}).values() for op in ops.values() if isinstance(op, dict)
              for t in op.get("tags", [])}
    esquema["tags"] = [{"name": n, "description": d} for n, d in ETIQUETAS.items() if n in usadas] + \
        [{"name": n} for n in sorted(usadas - set(ETIQUETAS))]


def ajustar(esquema: dict) -> dict:
    """Completa en el sitio el documento que generó FastAPI (idempotente)."""
    from app.seguridad import rol_requerido

    _componentes_error(esquema)
    for ruta, metodo, op in _operaciones(esquema):
        _ajustar_operacion(ruta, metodo, op, rol_requerido)
    _ajustar_salud_y_metricas(esquema)
    for ruta, _metodo, op in _operaciones(esquema):
        for codigo, respuesta in op.get("responses", {}).items():
            _con_cabeceras(respuesta, codigo, ruta)
    _quitar_esquemas_sin_uso(esquema)
    _descripcion_y_etiquetas(esquema)
    return esquema


def instalar(app: FastAPI) -> None:
    """Reemplaza app.openapi por la versión completada y agrega la guarda NUL (la más externa de la pila)."""
    generar = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            ajustar(generar())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    app.add_middleware(GuardaNul)
    app.add_exception_handler(OverflowError, _fuera_de_rango)
    from sqlalchemy.exc import DataError

    app.add_exception_handler(DataError, _dato_fuera_de_rango)


# SQLSTATE de PostgreSQL que solo produce un valor de la solicitud que la columna no puede representar
SQLSTATE_FUERA_DE_RANGO = {"22003": "numeric_value_out_of_range", "22008": "datetime_field_overflow"}


def _dato_fuera_de_rango(request, exc):
    """Red de seguridad: un entero o una fecha de la solicitud que PostgreSQL no puede representar (p. ej. un filtro
    entero sin cota con 9223372036854775808) es el mismo 422 uniforme «fuera_de_rango», no un 500. Cualquier otro
    DataError sigue su camino como error interno (500 con el correlation_id)."""
    if getattr(getattr(exc, "orig", None), "sqlstate", None) not in SQLSTATE_FUERA_DE_RANGO:
        raise exc
    return _fuera_de_rango(request, exc)


def _fuera_de_rango(request, exc: Exception):
    """Una fecha válida pero extrema (p. ej. hasta=9999-12-31) desborda la aritmética de fechas: es un 422 uniforme
    de validación, no un 500. Es síncrona (no espera nada): Starlette la ejecuta en su grupo de hilos."""
    from fastapi.responses import JSONResponse

    from app.observabilidad import correlation_id_var

    cid = getattr(request.state, "correlation_id", None) or correlation_id_var.get() or str(uuid.uuid4())
    # solo la primera línea del motivo: un DataError trae además la sentencia SQL, que no sale de la API
    causa = (str(getattr(exc, "orig", None) or exc).splitlines() or [type(exc).__name__])[0]
    log.warning("Valor fuera de rango en %s %s: %s", request.method, request.url.path, causa)
    return JSONResponse(status_code=422, headers={"X-Correlation-Id": cid},
                        content={"error": {"codigo": "fuera_de_rango", "mensaje": "Un valor de la solicitud está fuera "
                                           "del rango que la API puede procesar", "detalle": {"causa": causa},
                                           "correlation_id": cid}})


# ---------------------------------------------------------------- guarda contra el byte NUL
LIMITE_CUERPO = 2 * 1024 * 1024        # cuerpos JSON más grandes pasan sin revisar (los rechaza la validación)


def _nul_en_ruta(scope: dict) -> str | None:
    ruta = scope.get("path") or ""
    if "\x00" in ruta or b"%00" in (scope.get("raw_path") or b"").lower():
        return "path"
    return None


def _nul_en_consulta(scope: dict) -> str | None:
    consulta = (scope.get("query_string") or b"").decode("latin-1")
    if "\x00" not in consulta and "%00" not in consulta:
        return None
    for nombre, valor in parse_qsl(consulta, keep_blank_values=True):
        if "\x00" in nombre or "\x00" in valor:
            return f"query.{nombre.replace(chr(0), '')}"
    return "query"


def _nul_en_cabeceras(scope: dict) -> str | None:
    for nombre, valor in scope.get("headers") or []:
        if b"\x00" in valor or b"\x00" in nombre:
            limpio = nombre.replace(b"\x00", b"").decode("latin-1")
            return f"header.{limpio}"
    return None


def _campo_con_nul(scope: dict) -> str | None:
    """Primer lugar de la solicitud con el byte NUL: ruta, consulta (con el nombre del parámetro) o cabecera."""
    return _nul_en_ruta(scope) or _nul_en_consulta(scope) or _nul_en_cabeceras(scope)


def _es_json(scope: dict) -> bool:
    for nombre, valor in scope.get("headers") or []:
        if nombre == b"content-type":
            return b"json" in valor.lower()
    return False


async def _revisar_cuerpo(receive):
    """Lee el cuerpo JSON (hasta LIMITE_CUERPO) y busca el byte NUL. Devuelve («body» o None, un receive que repite
    los mensajes ya leídos y luego sigue con el original)."""
    mensajes, cuerpo, mas = [], b"", True
    while mas:
        mensaje = await receive()
        mensajes.append(mensaje)
        if mensaje.get("type") != "http.request":
            break
        cuerpo += mensaje.get("body", b"")
        mas = mensaje.get("more_body", False) and len(cuerpo) <= LIMITE_CUERPO
    campo = "body" if b"\x00" in cuerpo or b"\\u0000" in cuerpo else None
    pendientes = list(mensajes)

    async def receive_repetido():
        return pendientes.pop(0) if pendientes else await receive()

    return campo, receive_repetido


class GuardaNul:
    """Middleware ASGI: 422 uniforme ante el byte NUL en ruta, consulta, cabeceras o cuerpo JSON."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        campo = _campo_con_nul(scope)
        if campo is None and scope.get("method") in ("POST", "PUT", "PATCH") and _es_json(scope):
            campo, receive = await _revisar_cuerpo(receive)
        if campo is None:
            await self.app(scope, receive, send)
            return
        await self._rechazar(scope, receive, send, campo)

    @staticmethod
    async def _rechazar(scope, receive, send, campo: str) -> None:
        from fastapi.responses import JSONResponse

        cid = next((v.decode("latin-1") for n, v in scope.get("headers") or []
                    if n == b"x-correlation-id" and b"\x00" not in v and v), None) or str(uuid.uuid4())
        detalle = [{"campo": campo, "mensaje": "El valor contiene el byte NUL (0x00), que no se admite",
                    "tipo": "caracter_nulo"}]
        log.info("peticion", extra={"metodo": scope.get("method"), "ruta": (scope.get("path") or "").replace(
            "\x00", "%00"), "estado": 422, "motivo": "byte_nul", "campo": campo, "correlation_id": cid})
        respuesta = JSONResponse(status_code=422, headers={"X-Correlation-Id": cid},
                                 content={"error": {"codigo": "validacion", "mensaje": "La solicitud no es válida",
                                                    "detalle": detalle, "correlation_id": cid}})
        await respuesta(scope, receive, send)


__all__ = ["instalar", "ajustar", "codigos_de", "GuardaNul", "ERRORES_POR_OPERACION", "CODIGOS_GENERALES",
           "CODIGOS_POR_OPERACION", "DESCRIPCIONES", "XLSX"]
