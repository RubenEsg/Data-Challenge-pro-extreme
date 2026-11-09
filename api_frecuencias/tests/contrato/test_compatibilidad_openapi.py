"""Compatibilidad del contrato (spec v1.5 §14.1 «Contrato … compatibilidad», RNF-009 «API documentada y versionada»).

Compara el OpenAPI versionado en el repositorio (docs/openapi.json, lo que conocen los clientes) con el que genera
el código. Un cambio COMPATIBLE puede agregar rutas, campos de respuesta o parámetros opcionales; uno que ROMPE a
los clientes quita una operación, quita o cambia el tipo de un campo de respuesta, vuelve obligatorio un campo de
entrada o agrega un parámetro de consulta obligatorio. Aquí solo se prueba que no haya rupturas; que el archivo
versionado esté al día (deriva) lo verifica el paso «OpenAPI sin deriva» del CI (scripts/ci_local.py openapi).
No necesita base de datos.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contrato

VERSIONADO = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
METODOS = ("get", "post", "put", "patch", "delete")


@pytest.fixture(scope="module")
def documentos(entorno_contrato):
    from app.main import app

    return json.loads(VERSIONADO.read_text(encoding="utf-8")), app.openapi()


def _ref(esquema: dict) -> str | None:
    ref = esquema.get("$ref", "")
    return ref.rsplit("/", 1)[-1] if ref else None


def _componente_respuesta(op: dict, codigo: str) -> str | None:
    contenido = (op.get("responses", {}).get(codigo) or {}).get("content", {}).get("application/json", {})
    return _ref(contenido.get("schema", {}))


def _tipo(prop: dict) -> str:
    """Firma del tipo de una propiedad (anyOf de pydantic incluido) para detectar cambios de tipo."""
    if "$ref" in prop:
        return "ref:" + prop["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in prop:
        return "|".join(sorted(_tipo(p) for p in prop["anyOf"]))
    return f"{prop.get('type', 'any')}:{prop.get('format', '')}"


def test_versionado_es_openapi_3_y_misma_version_mayor(documentos):
    viejo, nuevo = documentos
    assert viejo["openapi"].startswith("3.") and nuevo["openapi"].startswith("3.")
    assert viejo["info"]["version"].split(".")[0] == nuevo["info"]["version"].split(".")[0], \
        "Un cambio de versión mayor exige publicar /api/v2 (§12.1 ruta base /api/v1)"


def test_no_se_quitan_operaciones(documentos):
    viejo, nuevo = documentos
    quitadas = [f"{m.upper()} {p}" for p, ops in viejo["paths"].items() for m in ops
                if m in METODOS and m not in nuevo["paths"].get(p, {})]
    assert not quitadas, f"Operaciones publicadas que ya no existen (rompen clientes): {quitadas}"


def test_no_cambian_los_codigos_de_exito(documentos):
    viejo, nuevo = documentos
    cambios = []
    for p, ops in viejo["paths"].items():
        for m, op in ops.items():
            if m not in METODOS or m not in nuevo["paths"].get(p, {}):
                continue
            exito_v = {c for c in op["responses"] if c.startswith("2")}
            exito_n = {c for c in nuevo["paths"][p][m]["responses"] if c.startswith("2")}
            if not exito_v <= exito_n:
                cambios.append(f"{m.upper()} {p}: {sorted(exito_v)} -> {sorted(exito_n)}")
    assert not cambios, f"Cambió el código de éxito documentado: {cambios}"


def test_no_aparecen_parametros_obligatorios_nuevos(documentos):
    viejo, nuevo = documentos
    nuevos = []
    for p, ops in viejo["paths"].items():
        for m, op in ops.items():
            if m not in METODOS or m not in nuevo["paths"].get(p, {}):
                continue
            antes = {(x["name"], x["in"]) for x in op.get("parameters", [])}
            for x in nuevo["paths"][p][m].get("parameters", []):
                if x.get("required") and (x["name"], x["in"]) not in antes:
                    nuevos.append(f"{m.upper()} {p}: {x['in']} {x['name']}")
    assert not nuevos, f"Parámetros obligatorios nuevos (rompen clientes): {nuevos}"


def test_entradas_no_exigen_campos_nuevos(documentos):
    viejo, nuevo = documentos
    rotos = []
    for nombre, esquema in viejo["components"]["schemas"].items():
        if not nombre.startswith("Solicitud") or nombre not in nuevo["components"]["schemas"]:
            continue
        antes, ahora = set(esquema.get("required", [])), set(nuevo["components"]["schemas"][nombre].get("required", []))
        if ahora - antes:
            rotos.append(f"{nombre}: ahora exige {sorted(ahora - antes)}")
    assert not rotos, f"Cuerpos de entrada con campos obligatorios nuevos: {rotos}"


def _campos_rotos(etiqueta: str, esquema_v: dict, esquema_n: dict) -> list[str]:
    """Campos de una respuesta que desaparecen o cambian de tipo (agregar campos es compatible)."""
    props_n = esquema_n.get("properties", {})
    rotos = []
    for campo, prop in esquema_v.get("properties", {}).items():
        if campo not in props_n:
            rotos.append(f"{etiqueta}.{campo}: se quitó")
        elif _tipo(prop) != _tipo(props_n[campo]):
            rotos.append(f"{etiqueta}.{campo}: tipo {_tipo(prop)} -> {_tipo(props_n[campo])}")
    return rotos


def test_respuestas_conservan_campos_y_tipos(documentos):
    viejo, nuevo = documentos
    comp_viejo, comp_nuevo = viejo["components"]["schemas"], nuevo["components"]["schemas"]
    rotos = []
    for p, ops in viejo["paths"].items():
        for m, op in ops.items():
            if m not in METODOS or m not in nuevo["paths"].get(p, {}):
                continue
            for codigo in (c for c in op["responses"] if c.startswith("2")):
                comp_v = _componente_respuesta(op, codigo)
                comp_n = _componente_respuesta(nuevo["paths"][p][m], codigo)
                if comp_v and comp_n and comp_v != comp_n:
                    # otro esquema es compatible si conserva cada campo y su tipo (p. ej. una subclase con más campos)
                    rotos += _campos_rotos(f"{m.upper()} {p} {codigo} {comp_v}->{comp_n}",
                                           comp_viejo[comp_v], comp_nuevo.get(comp_n, {}))
    for nombre, esquema in comp_viejo.items():
        if nombre.startswith("Solicitud") or nombre not in comp_nuevo:
            continue
        rotos += _campos_rotos(nombre, esquema, comp_nuevo[nombre])
    assert not rotos, "Cambios que rompen a los clientes:\n" + "\n".join(rotos)
