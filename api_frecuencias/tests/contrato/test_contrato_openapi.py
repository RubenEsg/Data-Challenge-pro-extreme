"""Contrato OpenAPI (spec v1.5 §14.1 «Contrato»: esquemas, códigos y compatibilidad; §12.1 y §12.2).

Cada operación del documento OpenAPI que genera la API se llama con autenticación (X-API-Key) y datos reales:
- el código de estado debe estar documentado para esa operación;
- el cuerpo JSON se valida con jsonschema (Draft 2020-12, el dialecto de OpenAPI 3.1) contra el esquema documentado,
  resolviendo los $ref a #/components/schemas del mismo documento;
- toda respuesta devuelve X-Correlation-Id (§12.1);
- los errores (401, 403, 404, 409 y 422) siguen el formato uniforme {"error": {codigo, mensaje, detalle,
  correlation_id}} de §12.1 (esquema app.esquemas.RespuestaError).
El documento lo completa app/openapi_doc.py (errores uniformes por operación, 422 con RespuestaError, text/plain en
/metrics, text/csv y xlsx en las exportaciones, rol mínimo); estas pruebas lo verifican contra las respuestas reales y
contra el código de los routers, sin ningún xfail.
"""
from __future__ import annotations

import re
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

pytestmark = [pytest.mark.contrato, pytest.mark.integracion]

URN = "urn:sobusa:openapi"
CODIGOS_ERROR = {401, 403, 404, 409, 422, 503}
METODOS = ("get", "post", "put", "patch", "delete")
# §12.2 Endpoints mínimos: deben existir en el contrato publicado
MINIMOS_12_2 = {
    ("post", "/api/v1/frequency/executions"), ("get", "/api/v1/frequency/executions/{execution_id}"),
    ("post", "/api/v1/predictions/run"), ("get", "/api/v1/predictions"),
    ("post", "/api/v1/recommendations/calculate"), ("get", "/api/v1/recommendations"),
    ("get", "/api/v1/alerts"), ("patch", "/api/v1/alerts/{alert_id}/status"),
    ("get", "/api/v1/models"), ("post", "/api/v1/models/{model_id}/activate"),
}
BRECHAS: list[str] = []   # brechas de documentación observadas en las llamadas reales (deben quedar en cero)
FECHA_RESPUESTA = "2025-10-15"   # día laboral con variables del modelo en la serie empaquetada (§20)
# Errores propios de §5.1, §7.1, §9.3 y §12.1 que la API devuelve de verdad: (método, plantilla, url, cuerpo, consulta,
# estado, código). Cada uno debe venir con el error uniforme y estar declarado en «x-codigos-error» de su operación.
ERRORES_PROPIOS = [
    ("GET", "/api/v1/frequency/executions", "/api/v1/frequency/executions", None,
     {"desde": "2025-03-05", "hasta": "2025-03-01"}, 422, "rango_invalido"),
    ("POST", "/api/v1/models/{model_id}/activate", "/api/v1/models/{otro}/activate", {"aprobado_por": "contrato"},
     {"forzar": "true"}, 422, "motivo_requerido"),
    ("POST", "/api/v1/models/{model_id}/activate", "/api/v1/models/{otro}/activate",
     {"aprobado_por": "contrato", "motivo": "contrato: ventana dentro de la muestra", "validacion_desde": "2020-01-01",
      "validacion_hasta": "2020-01-28"}, {"forzar": "true"}, 422, "ventana_en_muestra"),
    ("GET", "/api/v1/respuesta", "/api/v1/respuesta", None, {"ruta": "CRA 54", "fecha": "2025-06-02"}, 404,
     "sin_calcular"),
    ("GET", "/api/v1/recommendations/plan", "/api/v1/recommendations/plan", None,
     {"ruta": "CL 72", "fecha": "2025-06-02"}, 404, "sin_calcular"),
    ("POST", "/api/v1/respuesta/calcular", "/api/v1/respuesta/calcular", {"fecha": "2030-01-01"}, None, 404,
     "sin_datos"),
]


def _con_urn(nodo: Any) -> Any:
    if isinstance(nodo, dict):
        return {k: (URN + v if k == "$ref" and isinstance(v, str) and v.startswith("#") else _con_urn(v))
                for k, v in nodo.items()}
    if isinstance(nodo, list):
        return [_con_urn(x) for x in nodo]
    return nodo


class Contrato:
    def __init__(self, doc: dict):
        self.doc = doc
        self.registro = Registry().with_resource(URN, Resource.from_contents(doc, default_specification=DRAFT202012))
        from app.esquemas import RespuestaError

        self.error_uniforme = Draft202012Validator(RespuestaError.model_json_schema())

    def operaciones(self, prefijo: str = ""):
        for plantilla, ops in self.doc["paths"].items():
            for metodo, op in ops.items():
                if metodo in METODOS and plantilla.startswith(prefijo):
                    yield metodo, plantilla, op

    def respuesta(self, metodo: str, plantilla: str, codigo: int) -> dict | None:
        return self.doc["paths"][plantilla][metodo.lower()]["responses"].get(str(codigo))

    def errores_esquema(self, esquema: dict, cuerpo: Any) -> list[str]:
        v = Draft202012Validator(_con_urn(esquema), registry=self.registro,
                                 format_checker=Draft202012Validator.FORMAT_CHECKER)
        return [f"{'/'.join(str(p) for p in e.absolute_path) or '<raíz>'}: {e.message[:200]}"
                for e in v.iter_errors(cuerpo)]

    def errores_uniforme(self, cuerpo: Any) -> list[str]:
        return [e.message[:200] for e in self.error_uniforme.iter_errors(cuerpo)]


@dataclass
class Caso:
    nombre: str
    metodo: str
    plantilla: str
    url: str | None = None
    json: Any = None
    params: dict = field(default_factory=dict)
    esperados: tuple[int, ...] = (200,)

    def __post_init__(self):
        self.url = self.url or self.plantilla


@pytest.fixture(scope="module")
def contrato(app_contrato) -> Contrato:
    return Contrato(app_contrato.openapi())


@pytest.fixture(scope="module")
def anonimo(app_contrato):
    from fastapi.testclient import TestClient

    return TestClient(app_contrato)   # sin cabeceras por omisión (ni X-API-Key)


def verificar(contrato: Contrato, caso: Caso, r) -> list[str]:
    """Errores de contrato de una respuesta real; anota en BRECHAS lo que solo es documentación incompleta."""
    fallas: list[str] = []
    etiqueta = f"{caso.metodo} {caso.url} -> {r.status_code}"
    if r.status_code not in caso.esperados:
        fallas.append(f"{etiqueta}: se esperaba {caso.esperados}; cuerpo {r.text[:300]}")
    if not r.headers.get("X-Correlation-Id"):
        fallas.append(f"{etiqueta}: falta X-Correlation-Id (§12.1)")
    tipo = r.headers.get("content-type", "")
    documentada = contrato.respuesta(caso.metodo, caso.plantilla, r.status_code)
    if documentada is None:
        BRECHAS.append(f"{caso.metodo} {caso.plantilla}: código {r.status_code} no documentado")
        if r.status_code in CODIGOS_ERROR:
            fallas += [f"{etiqueta}: error no uniforme: {e}" for e in contrato.errores_uniforme(r.json())]
        else:
            fallas.append(f"{etiqueta}: código no documentado")
        return fallas
    contenido = documentada.get("content") or {}
    if "application/json" in contenido:
        if not tipo.startswith("application/json"):
            BRECHAS.append(f"{caso.metodo} {caso.plantilla}: documenta application/json y responde {tipo}")
        else:
            fallas += [f"{etiqueta}: {e}" for e in
                       contrato.errores_esquema(contenido["application/json"].get("schema", {}), r.json())]
    return fallas


def _casos(s: dict) -> list[Caso]:
    eid, pid, aid, mid = s["execution_id"], s["prediction_id"], s["alert_id"], s["model_id"]
    otro = next((m for m, e in s["modelos"].items() if e != "activo" and m.startswith("hgb_")), mid)
    e = "/api/v1/frequency/executions"
    return [
        Caso("crear_ejecucion", "POST", e, json={"hasta": "2025-03-03", "horizontes": [60]}, esperados=(202,)),
        Caso("listar_ejecuciones", "GET", e, params={"limite": 5, "orden": "-creado_en", "tipo": "frecuencia"}),
        Caso("detalle_ejecucion", "GET", e + "/{execution_id}", f"{e}/{eid}"),
        Caso("errores_ejecucion", "GET", e + "/{execution_id}/errors", f"{e}/{eid}/errors", params={"limite": 10}),
        Caso("predecir", "POST", "/api/v1/predictions/run",
             json={"ruta": "SILENCIO", "instante": "2025-03-03T07:00:00-05:00", "horizonte_min": 60},
             esperados=(201,)),
        Caso("listar_predicciones", "GET", "/api/v1/predictions",
             params={"ruta": "SILENCIO", "horizonte_min": 60, "limite": 10, "desplazamiento": 0}),
        Caso("exportar_predicciones", "GET", "/api/v1/predictions/export", params={"formato": "csv"}),
        Caso("una_prediccion", "GET", "/api/v1/predictions/{prediction_id}", f"/api/v1/predictions/{pid}"),
        Caso("calcular_recomendacion", "POST", "/api/v1/recommendations/calculate",
             json={"ruta": "SILENCIO", "hora": 7, "demanda_hora": 420.0, "demanda_p90": 480.0}, esperados=(201,)),
        Caso("listar_recomendaciones", "GET", "/api/v1/recommendations", params={"limite": 10}),
        Caso("exportar_recomendaciones", "GET", "/api/v1/recommendations/export", params={"formato": "xlsx"}),
        Caso("listar_alertas", "GET", "/api/v1/alerts", params={"estado": "nueva", "ruta": "SILENCIO"}),
        Caso("exportar_alertas", "GET", "/api/v1/alerts/export", params={"formato": "csv"}),
        Caso("una_alerta", "GET", "/api/v1/alerts/{alert_id}", f"/api/v1/alerts/{aid}"),
        Caso("reconocer_alerta", "PATCH", "/api/v1/alerts/{alert_id}/status", f"/api/v1/alerts/{aid}/status",
             json={"accion": "reconocer", "usuario": "contrato"}),
        Caso("historial_alerta", "GET", "/api/v1/alerts/{alert_id}/history", f"/api/v1/alerts/{aid}/history"),
        Caso("listar_modelos", "GET", "/api/v1/models", params={"limite": 20}),
        Caso("un_modelo", "GET", "/api/v1/models/{model_id}", f"/api/v1/models/{mid}"),
        Caso("entrenar", "POST", "/api/v1/models/train", json={"hasta": "2025-08-31", "semilla": 7},
             esperados=(202,)),
        Caso("umbrales", "GET", "/api/v1/thresholds"),
        Caso("cambiar_umbrales", "PUT", "/api/v1/thresholds",
             json={"valores": {"ocupacion_critica": 0.9}, "creado_por": "contrato", "motivo": "prueba de contrato"}),
        Caso("historial_umbrales", "GET", "/api/v1/thresholds/history", params={"nombre": "ocupacion_critica"}),
        Caso("planificador", "GET", "/api/v1/scheduler"),
        Caso("salud", "GET", "/health"),
        Caso("metricas", "GET", "/metrics"),
        # la gobernanza puede aprobar (200) o rechazar (409) según el WAPE en la misma ventana: ambos son contrato
        Caso("activar_modelo", "POST", "/api/v1/models/{model_id}/activate", f"/api/v1/models/{otro}/activate",
             json={"aprobado_por": "contrato", "motivo": "prueba de contrato"}, esperados=(200, 409)),
        Caso("revertir_modelo", "POST", "/api/v1/models/rollback", json={"usuario": "contrato", "motivo": "prueba"},
             esperados=(200, 409)),
        # operaciones agregadas después (plan D5, evaluación, catálogos y respuesta del reto): 404/409/503 documentados
        Caso("plan_dia", "GET", "/api/v1/recommendations/plan", params={"ruta": "SILENCIO", "fecha": "2025-03-03"},
             esperados=(200, 404)),
        Caso("evaluacion_modelo", "GET", "/api/v1/models/{model_id}/evaluation", f"/api/v1/models/{mid}/evaluation",
             esperados=(200, 404, 409)),
        Caso("importancia_modelo", "GET", "/api/v1/models/{model_id}/importance", f"/api/v1/models/{mid}/importance",
             esperados=(200, 404, 409)),
        Caso("una_ruta_catalogo", "GET", "/api/v1/catalogos/rutas/{idruta}", "/api/v1/catalogos/rutas/2",
             esperados=(200, 404, 503)),
        Caso("quitar_ajuste_capacidad", "PUT", "/api/v1/catalogos/capacidad",
             json={"idruta": 2, "capacidad": None, "motivo": "contrato: quitar un ajuste que no existe"},
             esperados=(200, 404)),
        Caso("respuesta_reto", "GET", "/api/v1/respuesta", esperados=(200, 404)),
        Caso("exportar_respuesta_reto", "GET", "/api/v1/respuesta/export", params={"formato": "csv"},
             esperados=(200, 404)),
        # escrituras nuevas: la foto de la respuesta del reto va a la cola (§7.1, 202) y la aprobación de umbrales
        # (§5.1); los roles, el 404 «sin_datos» y la idempotencia tienen su prueba propia más abajo
        Caso("calcular_respuesta", "POST", "/api/v1/respuesta/calcular",
             json={"fecha": FECHA_RESPUESTA, "rutas": ["SILENCIO"]}, esperados=(202,)),
        Caso("aprobar_umbrales", "POST", "/api/v1/thresholds/{version}/aprobar", "/api/v1/thresholds/1/aprobar",
             json={"comentario": "prueba de contrato"}),
    ]


NOMBRES = [c.nombre for c in _casos({"execution_id": "e", "prediction_id": "p", "alert_id": "a", "model_id": "m",
                                      "modelos": {}})]


def _llamar(cliente, caso: Caso, **extra):
    return cliente.request(caso.metodo, caso.url, json=caso.json, params=caso.params or None, **extra)


def _concreta(plantilla: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), plantilla)


# ---------------------------------------------------------------- operaciones válidas, una por una
@pytest.mark.parametrize("nombre", NOMBRES)
def test_operacion_valida_cumple_el_contrato(nombre, contrato, cliente_contrato, sembrado, sin_trabajos):
    caso = next(c for c in _casos(sembrado) if c.nombre == nombre)
    assert caso.metodo.lower() in contrato.doc["paths"][caso.plantilla], f"{caso.plantilla} no está en OpenAPI"
    r = _llamar(cliente_contrato, caso, headers={"X-Correlation-Id": f"contrato-{nombre}"})
    assert r.headers.get("X-Correlation-Id") == f"contrato-{nombre}"
    fallas = verificar(contrato, caso, r)
    assert not fallas, "\n".join(fallas)


def test_endpoints_minimos_12_2_publicados(contrato):
    publicados = {(m, p) for m, p, _ in contrato.operaciones()}
    faltan = MINIMOS_12_2 - publicados
    assert not faltan, f"Faltan endpoints mínimos de §12.2 en OpenAPI: {sorted(faltan)}"
    sin_seguridad = [f"{m.upper()} {p}" for m, p, op in contrato.operaciones("/api/v1") if not op.get("security")]
    assert not sin_seguridad, f"Operaciones de /api/v1 sin esquema de seguridad declarado: {sin_seguridad}"


def test_operaciones_nuevas_get_sin_parametros_de_ruta(contrato, cliente_contrato, sembrado):
    """Toda operación GET que aún no tenga caso propio (p. ej. una ruta recién agregada) se valida igual."""
    cubiertas = {(c.metodo.lower(), c.plantilla) for c in _casos(sembrado)}
    fallas, sin_caso = [], []
    for metodo, plantilla, op in contrato.operaciones():
        if (metodo, plantilla) in cubiertas:
            continue
        obligatorios = [p for p in op.get("parameters", []) if p.get("required")]
        if metodo != "get" or "{" in plantilla or obligatorios:
            sin_caso.append(f"{metodo.upper()} {plantilla}")
            continue
        # sin filtros, una ruta puede exigir uno (422) o depender de la fuente integrada (503): se valida su formato
        caso = Caso(f"generico_{plantilla}", "GET", plantilla, esperados=(200, 422, 503))
        fallas += verificar(contrato, caso, _llamar(cliente_contrato, caso))
    if sin_caso:
        warnings.warn(f"Operaciones sin caso de contrato propio (agréguelas a _casos): {sin_caso}", stacklevel=1)
    assert not fallas, "\n".join(fallas)


# ---------------------------------------------------------------- autenticación y autorización
def test_401_sin_clave_o_clave_invalida_en_todas_las_operaciones(contrato, anonimo):
    fallas = []
    for metodo, plantilla, _ in contrato.operaciones("/api/v1"):
        url = _concreta(plantilla)
        for etiqueta, cabeceras in (("sin clave", {}), ("clave inválida", {"X-API-Key": "clave-que-no-existe-123"})):
            r = anonimo.request(metodo.upper(), url, headers=cabeceras)
            if r.status_code != 401:
                fallas.append(f"{metodo.upper()} {url} {etiqueta}: {r.status_code} (se esperaba 401)")
                continue
            if r.headers.get("WWW-Authenticate") != 'ApiKey header="X-API-Key"':
                fallas.append(f"{metodo.upper()} {url}: 401 sin WWW-Authenticate")
            fallas += [f"{metodo.upper()} {url}: {e}" for e in contrato.errores_uniforme(r.json())]
            assert r.json()["error"]["codigo"] == "no_autenticado"
    assert not fallas, "\n".join(fallas)


def test_403_rol_insuficiente_en_escrituras(contrato, anonimo, claves):
    from app.seguridad import NIVEL, ROLES, rol_requerido

    fallas, probadas = [], 0
    for metodo, plantilla, _ in contrato.operaciones("/api/v1"):
        requerido = rol_requerido(metodo, plantilla)
        for rol in ROLES[:NIVEL[requerido]]:            # cada rol por debajo del mínimo
            r = anonimo.request(metodo.upper(), _concreta(plantilla), headers={"X-API-Key": claves[rol]})
            probadas += 1
            if r.status_code != 403:
                fallas.append(f"{metodo.upper()} {plantilla} con {rol}: {r.status_code} (se esperaba 403)")
                continue
            cuerpo = r.json()
            fallas += [f"{metodo.upper()} {plantilla}: {e}" for e in contrato.errores_uniforme(cuerpo)]
            if cuerpo["error"]["detalle"] != {"rol": rol, "rol_requerido": requerido}:
                fallas.append(f"{metodo.upper()} {plantilla}: detalle 403 inesperado {cuerpo['error']['detalle']}")
    assert probadas >= 8 and not fallas, "\n".join(fallas)


# ---------------------------------------------------------------- escrituras nuevas: respuesta del reto y aprobación
def _ejecuciones_respuesta() -> int:
    from sqlalchemy import func, select

    from app.db import sesion_contexto
    from app.modelos_db import Ejecucion

    with sesion_contexto() as s:
        return s.scalar(select(func.count()).select_from(Ejecucion).where(Ejecucion.tipo == "respuesta"))


def test_calcular_respuesta_202_analista_403_operador_404_sin_datos(contrato, anonimo, claves, sin_trabajos):
    """POST /api/v1/respuesta/calcular (§7.1 y §20): 202 con la clave analista (esquema CalculoEnCola; la ejecución
    «respuesta» queda en la cola), 403 con la de operador y 404 «sin_datos» para 2030-01-01 sin encolar nada. Los
    errores llegan con el formato uniforme y están declarados en la operación."""
    plantilla = "/api/v1/respuesta/calcular"
    analista = {"X-API-Key": claves["analista"]}
    caso = Caso("calcular_respuesta_analista", "POST", plantilla, json={"fecha": FECHA_RESPUESTA, "rutas": ["CL 72"]},
                esperados=(202,))
    r = _llamar(anonimo, caso, headers=analista)
    fallas = verificar(contrato, caso, r)
    assert not fallas, "\n".join(fallas)
    cuerpo = r.json()
    assert cuerpo["tipo"] == "respuesta" and cuerpo["fecha"] == FECHA_RESPUESTA and cuerpo["rutas"] == ["CL 72"]
    assert cuerpo["consultar_estado"] == f"/api/v1/frequency/executions/{cuerpo['execution_id']}"
    assert cuerpo["consultar_respuesta"] == f"/api/v1/respuesta?fecha={FECHA_RESPUESTA}"
    assert anonimo.get(cuerpo["consultar_estado"], headers=analista).json()["tipo"] == "respuesta"

    r = anonimo.post(plantilla, json={"fecha": FECHA_RESPUESTA}, headers={"X-API-Key": claves["operador"]})
    assert r.status_code == 403 and not contrato.errores_uniforme(r.json()), r.text[:300]
    assert r.json()["error"]["detalle"] == {"rol": "operador", "rol_requerido": "analista"}

    antes = _ejecuciones_respuesta()
    caso = Caso("calcular_respuesta_2030", "POST", plantilla, json={"fecha": "2030-01-01"}, esperados=(404,))
    r = _llamar(anonimo, caso, headers=analista)
    fallas = verificar(contrato, caso, r)
    assert not fallas, "\n".join(fallas)
    error = r.json()["error"]
    assert error["codigo"] == "sin_datos" and error["detalle"]["fecha"] == "2030-01-01", error
    assert error["detalle"]["primera_fecha"] <= error["detalle"]["ultima_fecha"] < "2030-01-01"
    assert "sin_datos" in contrato.respuesta("post", plantilla, 404)["x-codigos-error"]
    assert _ejecuciones_respuesta() == antes, "una fecha sin datos no debe encolar ninguna ejecución"


def test_aprobar_umbrales_admin_idempotente_403_404_422(contrato, anonimo, claves):
    """POST /api/v1/thresholds/{version}/aprobar (§5.1, validación del área operativa): solo admin; firma aprobado_por y
    aprobado_en en la versión y es idempotente (conserva la primera firma); 403 con analista, 404 «no_encontrado» con
    una versión que no existe y 422 con una versión fuera de rango, siempre con el error uniforme."""
    plantilla = "/api/v1/thresholds/{version}/aprobar"
    admin = {"X-API-Key": claves["admin"]}
    nueva = anonimo.put("/api/v1/thresholds", headers=admin,
                        json={"valores": {"ocupacion_critica": 0.91}, "creado_por": "contrato",
                              "motivo": "contrato: versión por aprobar"})
    assert nueva.status_code == 200 and nueva.json()["estado"] == "propuesta", nueva.text[:300]
    version = nueva.json()["version"]
    caso = Caso("aprobar_umbrales_admin", "POST", plantilla, f"/api/v1/thresholds/{version}/aprobar",
                json={"comentario": "contrato: acta de validación"})
    primera = _llamar(anonimo, caso, headers=admin)
    fallas = verificar(contrato, caso, primera)
    assert not fallas, "\n".join(fallas)
    firmada = primera.json()
    assert firmada["version"] == version and firmada["estado"] == "aprobada" and firmada["aprobado_por"]
    # cada fila de la versión queda firmada; el detalle presenta el instante en -05:00 (§8.1)
    filas = firmada["detalle"]
    assert filas and all(f["aprobado_por"] == firmada["aprobado_por"] and f["aprobado_en"].endswith("-05:00")
                         for f in filas), filas
    assert datetime.fromisoformat(firmada["aprobado_en"]) == datetime.fromisoformat(filas[0]["aprobado_en"])
    segunda = _llamar(anonimo, caso, headers=admin)          # idempotente: el mismo instante de la primera firma
    assert segunda.status_code == 200, segunda.text[:300]
    assert datetime.fromisoformat(segunda.json()["aprobado_en"]) == datetime.fromisoformat(firmada["aprobado_en"])
    assert segunda.json()["aprobado_por"] == firmada["aprobado_por"]
    assert anonimo.get("/api/v1/thresholds", headers=admin).json()["estado"] == "aprobada"

    r = anonimo.post(caso.url, json={}, headers={"X-API-Key": claves["analista"]})
    assert r.status_code == 403 and not contrato.errores_uniforme(r.json()), r.text[:300]
    assert r.json()["error"]["detalle"] == {"rol": "analista", "rol_requerido": "admin"}
    caso = Caso("aprobar_umbrales_inexistente", "POST", plantilla, "/api/v1/thresholds/2147483647/aprobar", json={},
                esperados=(404,))
    r = _llamar(anonimo, caso, headers=admin)
    fallas = verificar(contrato, caso, r)
    assert not fallas and r.json()["error"]["codigo"] == "no_encontrado", fallas or r.text[:300]
    r = anonimo.post("/api/v1/thresholds/0/aprobar", json={}, headers=admin)
    assert r.status_code == 422 and not contrato.errores_uniforme(r.json()), r.text[:300]


def _modelo_no_activo(cliente) -> str | None:
    modelos = cliente.get("/api/v1/models", params={"limite": 100}).json()["items"]
    return next((m["model_id"] for m in modelos if m["estado"] != "activo" and m.get("data_cutoff")), None)


@pytest.mark.parametrize(("metodo", "plantilla", "url", "cuerpo", "params", "estado", "codigo"), ERRORES_PROPIOS,
                         ids=[f"{m} {p} {e} {c}" for m, p, _u, _c, _q, e, c in ERRORES_PROPIOS])
def test_errores_propios_en_vivo_son_uniformes_y_declarados(metodo, plantilla, url, cuerpo, params, estado, codigo,
                                                            contrato, cliente_contrato, sembrado, sin_trabajos):
    """Los códigos propios que devuelve la API (422 «rango_invalido», «motivo_requerido» y «ventana_en_muestra»; 404
    «sin_calcular» y «sin_datos») llegan con el error uniforme y están declarados en «x-codigos-error» y en la
    descripción de su respuesta. La ventana dentro de la muestra se rechaza antes de evaluar: forzar no la salta."""
    if "{otro}" in url:
        otro = _modelo_no_activo(cliente_contrato)
        if otro is None:
            pytest.skip("el registro no tiene un modelo no activo con fecha de corte")
        url = url.replace("{otro}", otro)
    r = cliente_contrato.request(metodo, url, json=cuerpo, params=params)
    assert r.status_code == estado, r.text[:300]
    assert not contrato.errores_uniforme(r.json()) and r.headers.get("X-Correlation-Id"), r.text[:300]
    assert r.json()["error"]["codigo"] == codigo, r.text[:300]
    declarada = contrato.respuesta(metodo, plantilla, estado)
    assert declarada is not None and codigo in declarada.get("x-codigos-error", []), declarada
    assert f"«{codigo}»" in declarada["description"], declarada["description"]


# ---------------------------------------------------------------- 422 y 404 con el formato uniforme
INVALIDOS = [
    ("POST", "/api/v1/frequency/executions", {"horizontes": [45]}, None),
    ("POST", "/api/v1/predictions/run", {"ruta": "SILENCIO", "horizonte_min": 60}, None),
    ("POST", "/api/v1/recommendations/calculate", {"ruta": "SILENCIO", "hora": 25, "demanda_hora": -1}, None),
    ("PATCH", "/api/v1/alerts/{alert_id}/status", {"accion": "volar", "usuario": "x"}, None),
    ("POST", "/api/v1/models/train", {"hasta": "no-es-fecha"}, None),
    ("POST", "/api/v1/models/rollback", {"usuario": "x", "motivo": 5}, None),
    ("POST", "/api/v1/models/{model_id}/activate", {"aprobado_por": "x", "validacion_desde": "ayer"}, None),
    ("PUT", "/api/v1/thresholds", {"valores": "no-es-objeto", "creado_por": "x"}, None),
    ("GET", "/api/v1/predictions", None, {"limite": 0}),
    ("GET", "/api/v1/alerts", None, {"desde": "no-es-fecha"}),
    ("GET", "/api/v1/frequency/executions", None, {"desplazamiento": -1}),
    ("GET", "/api/v1/models", None, {"orden": "campo_que_no_existe"}),
]


@pytest.mark.parametrize(("metodo", "plantilla", "cuerpo", "params"), INVALIDOS,
                         ids=[f"{m} {p} {'cuerpo' if c is not None else 'consulta'}" for m, p, c, _ in INVALIDOS])
def test_422_formato_uniforme(metodo, plantilla, cuerpo, params, contrato, cliente_contrato, sembrado):
    url = plantilla.replace("{alert_id}", sembrado["alert_id"]).replace("{model_id}", sembrado["model_id"])
    r = cliente_contrato.request(metodo, url, json=cuerpo, params=params)
    assert r.status_code == 422, r.text
    assert not contrato.errores_uniforme(r.json()), r.text
    error = r.json()["error"]
    assert error["codigo"] in ("validacion", "orden_invalido") and error["correlation_id"]
    if error["codigo"] == "validacion":
        assert all({"campo", "mensaje", "tipo"} <= set(d) for d in error["detalle"]), error["detalle"]
    assert contrato.respuesta(metodo, plantilla, 422) is not None, "el 422 debe estar documentado"


NO_ENCONTRADOS = [
    ("GET", "/api/v1/frequency/executions/{id}", None),
    ("GET", "/api/v1/frequency/executions/{id}/errors", None),
    ("GET", "/api/v1/predictions/{id}", None),
    ("GET", "/api/v1/alerts/{id}", None),
    ("PATCH", "/api/v1/alerts/{id}/status", {"accion": "reconocer", "usuario": "contrato"}),
    ("GET", "/api/v1/alerts/{id}/history", None),
    ("GET", "/api/v1/models/{id}", None),
    ("POST", "/api/v1/models/{id}/activate", {"aprobado_por": "contrato"}),
]


@pytest.mark.parametrize(("metodo", "plantilla", "cuerpo"), NO_ENCONTRADOS,
                         ids=[f"{m} {p}" for m, p, _ in NO_ENCONTRADOS])
def test_404_formato_uniforme(metodo, plantilla, cuerpo, contrato, cliente_contrato):
    r = cliente_contrato.request(metodo, plantilla.replace("{id}", str(uuid.uuid4())), json=cuerpo)
    assert r.status_code == 404, r.text
    assert not contrato.errores_uniforme(r.json()), r.text
    assert r.json()["error"]["codigo"] == "no_encontrado" and r.headers["X-Correlation-Id"]


def test_ruta_inexistente_404_uniforme(contrato, cliente_contrato):
    r = cliente_contrato.get("/api/v1/no-existe")
    assert r.status_code == 404 and not contrato.errores_uniforme(r.json())


# ---------------------------------------------------------------- errores y tipos de contenido documentados
def test_errores_documentados_en_openapi(contrato):
    """401 en toda /api/v1, 403 donde el rol mínimo supera a operador, 404 con parámetro de ruta, 422 y 500 en todas,
    siempre con el esquema uniforme RespuestaError."""
    from app.seguridad import rol_requerido

    faltan, mal_esquema = [], []
    for metodo, plantilla, op in contrato.operaciones("/api/v1"):
        codigos = set(op["responses"])
        esperados = {"401", "422", "500"} | ({"403"} if rol_requerido(metodo, plantilla) != "operador" else set())
        if "{" in plantilla:
            esperados.add("404")
        faltan += [f"{metodo.upper()} {plantilla}: {c}" for c in sorted(esperados - codigos)]
        for c in (x for x in codigos if x[0] in "45"):
            esquema = op["responses"][c]["content"]["application/json"]["schema"]
            if esquema.get("$ref") != "#/components/schemas/RespuestaError":
                mal_esquema.append(f"{metodo.upper()} {plantilla} {c}: {esquema}")
        assert op.get("x-rol-minimo") == rol_requerido(metodo, plantilla)
    assert not faltan, f"{len(faltan)} códigos de error sin documentar, p. ej. {faltan[:6]}"
    assert not mal_esquema, mal_esquema[:5]


def test_409_documentado_en_conflictos_de_estado(contrato):
    for metodo, plantilla in (("post", "/api/v1/models/{model_id}/activate"), ("post", "/api/v1/models/rollback"),
                              ("patch", "/api/v1/alerts/{alert_id}/status")):
        assert contrato.respuesta(metodo, plantilla, 409) is not None, plantilla


def test_503_documentado_donde_la_ruta_se_degrada(contrato):
    degradables = [(m, p) for m, p, _ in contrato.operaciones("/api/v1") if m == "get" and
                   (p.startswith(("/api/v1/segmentos", "/api/v1/catalogos")) or p == "/api/v1/predictions/segmentos")]
    assert len(degradables) >= 10
    assert all(contrato.respuesta(m, p, 503) is not None for m, p in degradables)
    assert contrato.respuesta("get", "/health", 503) is not None


def test_422_documentado_con_el_formato_uniforme(contrato, cliente_contrato):
    r = cliente_contrato.get("/api/v1/predictions", params={"limite": 0})
    assert r.status_code == 422 and "error" in r.json()
    esquema = contrato.respuesta("get", "/api/v1/predictions", 422)["content"]["application/json"]["schema"]
    nombre = esquema.get("$ref", "").rsplit("/", 1)[-1]
    componente = contrato.doc["components"]["schemas"].get(nombre, esquema)
    # el esquema documentado EXIGE la envoltura «error» que la API realmente devuelve
    assert "error" in componente.get("required", []), f"422 documentado como {nombre}: {componente}"
    assert not contrato.errores_esquema(esquema, r.json())
    assert "HTTPValidationError" not in contrato.doc["components"]["schemas"]


def test_tipos_de_contenido_documentados(contrato):
    from app.openapi_doc import XLSX

    metricas = contrato.respuesta("get", "/metrics", 200).get("content", {})
    assert set(metricas) == {"text/plain"}
    exportaciones = [(m, p) for m, p, _ in contrato.operaciones() if p.endswith("/export")]
    assert len(exportaciones) >= 10
    for metodo, plantilla in exportaciones:
        contenido = contrato.respuesta(metodo, plantilla, 200)["content"]
        assert {"text/csv", XLSX} == set(contenido), plantilla


def test_cabeceras_y_etiquetas_documentadas(contrato):
    """§12.1: X-Correlation-Id declarado (obligatorio) en toda respuesta; WWW-Authenticate en el 401; las etiquetas
    tienen descripción y la descripción general resume el contrato (autenticación, errores, zona horaria)."""
    sin_cabecera = [f"{m.upper()} {p} {c}" for m, p, op in contrato.operaciones() for c, r in op["responses"].items()
                    if not (r.get("headers", {}).get("X-Correlation-Id") or {}).get("required")]
    assert not sin_cabecera, sin_cabecera[:5]
    assert all("WWW-Authenticate" in op["responses"]["401"]["headers"]
               for _, _, op in contrato.operaciones("/api/v1"))
    etiquetas = {t["name"]: t.get("description") for t in contrato.doc["tags"]}
    assert {"alertas", "ejecuciones", "sistema"} <= set(etiquetas) and all(etiquetas.values())
    assert "America/Bogota" in contrato.doc["info"]["description"]


def test_filtros_uno_de_documentados(contrato):
    for plantilla, grupo in (("/api/v1/predictions/segmentos", ["prediction_id"]),
                             ("/api/v1/monitoring/feature-snapshots", ["ruta"])):
        op = contrato.doc["paths"][plantilla]["get"]
        assert grupo in op["x-requiere-uno-de"] and "Filtro obligatorio" in op["description"]
        assert contrato.respuesta("get", plantilla, 422) is not None


ERROR_API = re.compile(r"ErrorApi\(\s*(\d{3})(?:\s*,\s*[\"']([a-z_]+)[\"'])?")


def _codigos_en_codigo(funcion, modulo, vistos=None, profundidad=0) -> set[tuple[int, str | None]]:
    """(estado HTTP, «codigo») que lanza una función del router (ErrorApi(<estado>, "<código>") o no_encontrado),
    también en las funciones auxiliares del mismo módulo que llama (hasta dos niveles). Si el código no es un literal,
    queda None y solo se exige el estado."""
    import inspect

    vistos = vistos if vistos is not None else set()
    if funcion in vistos or profundidad > 2:
        return set()
    vistos.add(funcion)
    fuente = inspect.getsource(funcion)
    codigos = {(int(estado), codigo or None) for estado, codigo in ERROR_API.findall(fuente)}
    if "no_encontrado(" in fuente:
        codigos.add((404, "no_encontrado"))
    for nombre in set(re.findall(r"\b(_\w+)\(", fuente)):
        auxiliar = getattr(modulo, nombre, None)
        if inspect.isfunction(auxiliar) and auxiliar.__module__ == modulo.__name__:
            codigos |= _codigos_en_codigo(auxiliar, modulo, vistos, profundidad + 1)
    return codigos


def test_codigos_que_lanza_el_codigo_estan_documentados(contrato, app_contrato):
    """Cada ErrorApi(<estado>, "<código>") que puede lanzar el endpoint (o sus auxiliares) está declarado en su
    operación: el estado en «responses» y el código en «x-codigos-error» de ese estado (app/openapi_doc.py,
    CODIGOS_GENERALES y CODIGOS_POR_OPERACION). Entre ellos: 422 «ventana_en_muestra», «motivo_requerido» y
    «rango_invalido»; 409 «requiere_forzar»; 404 «sin_calcular» y «sin_datos»; y el 500 «operacion_no_permitida» de
    los catálogos (no debería ocurrir: las consultas son fijas)."""
    import sys

    from fastapi.routing import APIRoute

    faltan, sin_codigo, revisados = [], [], 0
    for ruta in app_contrato.routes:
        if not isinstance(ruta, APIRoute) or not ruta.include_in_schema:
            continue
        modulo = sys.modules[ruta.endpoint.__module__]
        for metodo in ruta.methods:
            op = contrato.doc["paths"][ruta.path][metodo.lower()]
            for estado, codigo in _codigos_en_codigo(ruta.endpoint, modulo):
                revisados += 1
                respuesta = op["responses"].get(str(estado))
                if respuesta is None:
                    faltan.append(f"{metodo} {ruta.path}: {estado}")
                elif codigo and codigo not in respuesta.get("x-codigos-error", []):
                    sin_codigo.append(f"{metodo} {ruta.path}: {estado} «{codigo}»")
    assert revisados >= 60, revisados
    assert not faltan, f"Estados que el código lanza y OpenAPI no declara: {faltan}"
    assert not sin_codigo, f"Códigos que el código lanza y OpenAPI no declara en x-codigos-error: {sin_codigo}"
    for metodo, plantilla, estado, codigo in (
            ("post", "/api/v1/models/{model_id}/activate", 422, "ventana_en_muestra"),
            ("post", "/api/v1/models/{model_id}/activate", 422, "motivo_requerido"),
            ("post", "/api/v1/models/{model_id}/activate", 409, "requiere_forzar"),
            ("get", "/api/v1/frequency/executions", 422, "rango_invalido"),
            ("get", "/api/v1/respuesta", 404, "sin_calcular"),
            ("get", "/api/v1/recommendations/plan", 404, "sin_calcular"),
            ("post", "/api/v1/respuesta/calcular", 404, "sin_datos")):
        declarada = contrato.respuesta(metodo, plantilla, estado)
        assert codigo in declarada["x-codigos-error"] and f"«{codigo}»" in declarada["description"], plantilla


def test_ajustar_el_documento_es_idempotente(contrato):
    """Completar otra vez el documento publicado no lo cambia: ni duplica las líneas de las descripciones (rol,
    filtro obligatorio, códigos propios) ni pierde las cabeceras X-Total-Count y X-Truncado de las exportaciones."""
    import copy

    from app.openapi_doc import ajustar

    assert ajustar(copy.deepcopy(contrato.doc)) == contrato.doc


def test_cada_error_declarado_enumera_sus_codigos(contrato):
    """Toda respuesta 4xx/5xx de /api/v1 enumera en «x-codigos-error» al menos un valor de «codigo» (401
    «no_autenticado», 422 «validacion», etc.), salvo un 503 genérico de lectura degradable sin código propio."""
    sin_lista = [f"{m.upper()} {p} {c}" for m, p, op in contrato.operaciones("/api/v1")
                 for c, r in op["responses"].items() if c[0] in "45" and not r.get("x-codigos-error") and c != "503"]
    assert not sin_lista, sin_lista[:10]


# ---------------------------------------------------------------- byte NUL y rangos (antes, errores 500 reales)
NUL = [
    ("GET", "/api/v1/alerts", {"params": {"codigo": "lease", "ruta": "\x00"}}, "query.ruta"),
    ("GET", "/api/v1/predictions", {"params": {"ruta": "SIL\x00ENCIO"}}, "query.ruta"),
    ("GET", "/api/v1/models/%00", {}, "path"),
    ("GET", "/health", {"headers": {"X-Otra": "a\x00b"}}, "header.x-otra"),
    ("PUT", "/api/v1/thresholds", {"json": {"valores": {"ocupacion_critica": 0.9}, "motivo": "a\u0000b"}}, "body"),
    ("PATCH", "/api/v1/alerts/{alert_id}/status", {"json": {"accion": "comentar", "comentario": "\u0000"}}, "body"),
]


@pytest.mark.parametrize(("metodo", "url", "extra", "campo"), NUL, ids=[f"{m} {u} {c}" for m, u, _, c in NUL])
def test_byte_nul_es_422_uniforme(metodo, url, extra, campo, contrato, cliente_contrato, sembrado):
    r = cliente_contrato.request(metodo, url.replace("{alert_id}", sembrado["alert_id"]), **extra)
    assert r.status_code == 422, r.text
    assert not contrato.errores_uniforme(r.json()) and r.headers.get("X-Correlation-Id")
    error = r.json()["error"]
    assert error["codigo"] == "validacion" and error["detalle"][0]["campo"] == campo
    assert error["detalle"][0]["tipo"] == "caracter_nulo"


def test_cuerpo_ilegible_es_400_uniforme_y_documentado(contrato, cliente_contrato):
    """Bytes que no son UTF-8 en un cuerpo JSON: FastAPI no puede leerlo (400, antes de validar). Lo encontró
    Schemathesis; ahora está documentado en toda operación con cuerpo y lleva el código «cuerpo_ilegible»."""
    r = cliente_contrato.put("/api/v1/thresholds", content=b"\x195\xff\xfe\x15\xff",
                             headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and not contrato.errores_uniforme(r.json())
    assert r.json()["error"]["codigo"] == "cuerpo_ilegible"
    con_cuerpo = [(m, p) for m, p, op in contrato.operaciones() if op.get("requestBody")]
    assert con_cuerpo and all(contrato.respuesta(m, p, 400) is not None for m, p in con_cuerpo)


FUERA_DE_RANGO = [
    ("/api/v1/predictions/export", {"formato": "csv", "horizonte_min": 9223372036854775808}),
    ("/api/v1/predictions", {"horizonte_min": 45}),
    ("/api/v1/predictions/segmentos", {"ruta": "SILENCIO", "horizonte_min": 9223372036854775808}),
    ("/api/v1/alerts", {"desplazamiento": 9223372036854775808}),
    ("/api/v1/alerts", {"hasta": "9999-12-31"}),
    ("/api/v1/alerts", {"cerca_de": "95.0,-74.8"}),
    ("/api/v1/alerts", {"cerca_de": "10.98,-74.80", "radio_m": 0}),
    # filtro idruta (§8.3) con un entero que PostgreSQL no representa: 422, nunca 500 (lo encontró Schemathesis)
    ("/api/v1/predictions", {"idruta": 9223372036854775808}),
    ("/api/v1/predictions/export", {"formato": "csv", "idruta": 9223372036854775808}),
    ("/api/v1/recommendations", {"idruta": 9223372036854775808}),
    ("/api/v1/recommendations/export", {"formato": "csv", "idruta": 9223372036854775808}),
]


@pytest.mark.parametrize(("url", "params"), FUERA_DE_RANGO, ids=[f"{u} {list(p)}" for u, p in FUERA_DE_RANGO])
def test_valores_fuera_de_rango_son_422(url, params, contrato, cliente_contrato):
    r = cliente_contrato.get(url, params=params)
    assert r.status_code == 422, r.text
    assert not contrato.errores_uniforme(r.json())
    assert r.json()["error"]["codigo"] in ("validacion", "fuera_de_rango", "horizonte_invalido"), r.text[:300]
    assert "SELECT" not in r.text, "el error no debe mostrar la sentencia SQL"


def test_filtro_espacial_de_alertas(cliente_contrato, sembrado):
    """cerca_de=lat,lon y radio_m con ST_DWithin sobre alert.ubicacion (o haversine sin PostGIS)."""
    from app.db import sesion_contexto
    from app.modelos_db import Alerta

    with sesion_contexto() as s:
        s.get(Alerta, uuid.UUID(sembrado["alert_id"])).ubicacion = {"type": "Point", "coordinates": [-74.801, 10.981]}
    cerca = cliente_contrato.get("/api/v1/alerts", params={"cerca_de": "10.9815,-74.8012", "radio_m": 200}).json()
    lejos = cliente_contrato.get("/api/v1/alerts", params={"cerca_de": "4.711,-74.0721", "radio_m": 5000}).json()
    assert sembrado["alert_id"] in {a["alert_id"] for a in cerca["items"]}
    assert sembrado["alert_id"] not in {a["alert_id"] for a in lejos["items"]}
    assert all(a["ubicacion"] for a in cerca["items"])


def test_patch_de_alerta_presenta_instantes_en_bogota(cliente_contrato, sembrado):
    """§8.1 en una escritura: el instante se guarda en UTC y la respuesta (y el historial) lo presenta en -05:00."""
    aid = sembrado["alert_id"]
    r = cliente_contrato.patch(f"/api/v1/alerts/{aid}/status", json={"accion": "comentar", "comentario": "zona"})
    assert r.status_code in (200, 409), r.text
    if r.status_code == 200:
        cuerpo = r.json()
        assert cuerpo["actualizado_en"].endswith("-05:00") and cuerpo["comentarios"][-1]["en"].endswith("-05:00")
    historial = cliente_contrato.get(f"/api/v1/alerts/{aid}/history").json()
    assert historial and all(h["creado_en"].endswith("-05:00") for h in historial)


def test_alerta_sin_postgis_usa_haversine(monkeypatch):
    from app.routers import alertas

    assert abs(alertas._distancia_m(10.981, -74.801, 10.9815, -74.8012) - 59.5) < 5
    assert alertas._distancia_m(10.981, -74.801, 4.711, -74.0721) > 690_000


def test_registro_de_brechas_observadas():
    """Las llamadas reales anteriores no dejaron ninguna brecha de documentación (código o tipo de contenido no
    declarado). Se ejecuta al final del módulo."""
    for b in sorted(set(BRECHAS)):
        warnings.warn(f"Brecha de documentación OpenAPI: {b}", stacklevel=1)
    assert not BRECHAS, sorted(set(BRECHAS))
