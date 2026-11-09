"""Regenera la evidencia del contrato OpenAPI (spec v1.5 §12.1, §12.2, §14.1 «Contrato» y RNF-009).

    python docs/evidencias/contrato/generar_evidencia_contrato.py                     -> los tres archivos
    python docs/evidencias/contrato/generar_evidencia_contrato.py --solo-operaciones  -> solo operaciones_codigos.txt

- operaciones_codigos.txt: cada operación del OpenAPI con su rol mínimo, los estados que declara, los tipos de
  contenido del éxito y los valores de «codigo» propios de cada error (x-codigos-error), desde app.openapi();
- schemathesis_junit.xml y schemathesis.txt: corre tests/contrato/test_schemathesis.py (cinco chequeos en todas las
  operaciones) y resume el junit, una línea por operación.

Necesita la base local de pruebas (TEST_DATABASE_NAME en el PostgreSQL de la 5433, como el resto de tests/contrato).
SCHEMATHESIS_EJEMPLOS fija los ejemplos por operación (5 por omisión en este script). Se corre desde
EntregaFinal/api_frecuencias; no escribe fuera de docs/evidencias/contrato.
"""
from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404
import sys
import time
import xml.etree.ElementTree as ET  # nosec B405  # solo lee el junit que escribe esta misma corrida  # noqa: S405
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
ZONA = ZoneInfo("America/Bogota")
METODOS = ("get", "post", "put", "patch", "delete")
PRUEBA = "tests/contrato/test_schemathesis.py::test_ninguna_entrada_produce_error_5xx_y_todo_cumple_el_contrato"
HISTORIA = """Historia de esta prueba:
- primera corrida (09-11-2026, chequeo not_a_server_error solo): 500 por enteros sin cota y por el byte NUL; corregidos;
- corrida estricta (cuatro chequeos): 2 operaciones respondían 400 no documentado con un cuerpo que no es
  UTF-8 (POST /models/{model_id}/activate y PUT /thresholds); se documentó el 400 «cuerpo_ilegible»;
- corridas siguientes (cinco chequeos, cabeceras incluidas): sin fallas; la de este archivo es la última."""


def _ahora() -> datetime:
    return datetime.now(ZONA)


def _fecha(d: datetime) -> str:
    return d.strftime("%d-%m-%Y, %H:%M:%S")


def operaciones() -> str:
    os.environ.setdefault("PLANIFICADOR_HABILITADO", "false")
    sys.path.insert(0, str(RAIZ))
    from app.main import app
    from app.openapi_doc import CODIGOS_GENERALES, codigos_de

    doc = app.openapi()
    filas, propios = [], []
    for ruta in sorted(doc["paths"]):
        for metodo, op in sorted(doc["paths"][ruta].items()):
            if metodo not in METODOS:
                continue
            respuestas = op.get("responses", {})
            exito = sorted({t for c, r in respuestas.items() if c.startswith("2") for t in (r.get("content") or {})})
            filas.append(f"{metodo.upper():<6} {ruta:<55} {op.get('x-rol-minimo', '-'):<9} "
                         f"{' '.join(sorted(respuestas)):<34} {','.join(exito) or '-'}")
            for estado in sorted(respuestas):
                lista = respuestas[estado].get("x-codigos-error") or []
                _todos, extra = codigos_de(metodo, ruta, int(estado), op)
                extra = [c for c in extra if c in lista]
                if extra:
                    propios.append(f"{metodo.upper():<6} {ruta:<55} {estado}  {', '.join(extra)}")
    generales = "; ".join(f"{e} {', '.join(c)}" for e, c in sorted(CODIGOS_GENERALES.items()))
    return "\n".join([
        "Operaciones del contrato OpenAPI y códigos de respuesta declarados (spec v1.5 §12.1, §12.2, RNF-009)",
        f"Generado desde app.openapi() (app/openapi_doc.py) el {_fecha(_ahora())} (Bogotá) | versión de la API "
        f"{doc['info']['version']} | OpenAPI {doc['openapi']}",
        f"{len(doc['paths'])} rutas y {len(filas)} operaciones. Todo 4xx/5xx declarado usa el esquema uniforme "
        "RespuestaError {error: {codigo, mensaje, detalle, correlation_id}}.",
        "Columnas: método, ruta, rol mínimo (x-rol-minimo), estados declarados, tipos de contenido del éxito.",
        "", *filas, "",
        "Valores de «codigo» propios de cada operación (x-codigos-error, además de los generales). Generales: "
        f"{generales}; «no_encontrado» en el 404 de las rutas con parámetro y «orden_invalido» en el 422 de las que "
        "aceptan «orden».",
        "Prueba: tests/contrato/test_contrato_openapi.py::test_codigos_que_lanza_el_codigo_estan_documentados (cada "
        "ErrorApi(<estado>, \"<código>\") del router está declarado) y ::test_errores_propios_en_vivo_son_uniformes_y_"
        "declarados (llamadas reales).",
        "", *propios, ""])


def schemathesis(ejemplos: int) -> str:
    junit = AQUI / "schemathesis_junit.xml"
    entorno = {**os.environ, "SCHEMATHESIS_EJEMPLOS": str(ejemplos)}
    inicio, t0 = _ahora(), time.perf_counter()
    salida = subprocess.run(  # noqa: S603  # nosec B603  # el intérprete actual y argumentos fijos
        [sys.executable, "-m", "pytest", PRUEBA, "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
        cwd=RAIZ, env=entorno, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    duracion, fin = time.perf_counter() - t0, _ahora()
    if not junit.is_file():
        raise SystemExit(f"pytest no dejó el junit (salida {salida.returncode}):\n{salida.stdout[-2000:]}")
    suite = ET.parse(junit).getroot()  # nosec B314  # XML local escrito por esta corrida  # noqa: S314
    suite = suite if suite.tag == "testsuite" else next(suite.iter("testsuite"))
    total = {k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}
    lineas, ok = [], 0
    for caso in suite.iter("testcase"):
        nombre = caso.get("name", "")
        if "[" not in nombre:
            continue
        operacion = nombre[nombre.index("[") + 1:-1]
        fallo = caso.find("failure") is not None or caso.find("error") is not None
        omitido = caso.find("skipped") is not None
        ok += not (fallo or omitido)
        lineas.append(f"{operacion:<62} {'FALLA' if fallo else 'omitida' if omitido else 'ok'}")
    version = _version_schemathesis()
    return "\n".join([
        f"Schemathesis {version}: contrato por propiedades en TODAS las operaciones del OpenAPI (spec v1.5 §14.1 "
        "«Contrato»)",
        f"Corrida: {_fecha(inicio)} a {fin.strftime('%H:%M:%S')} (hora de Bogotá), {duracion:.1f} s; base local de "
        f"pruebas PostgreSQL 14 + PostGIS 3.4; clave admin; {ejemplos} ejemplos por operación "
        f"(SCHEMATHESIS_EJEMPLOS={ejemplos}, derandomize). Código de salida de pytest: {salida.returncode}.",
        f"Prueba: {PRUEBA}",
        "Chequeos en cada respuesta: not_a_server_error, status_code_conformance, content_type_conformance,",
        "response_schema_conformance y response_headers_conformance (un 503 con el error uniforme solo se acepta si la",
        "operación lo declara). Sin lista de defectos conocidos ni xfail.",
        "Regenerar: python docs/evidencias/contrato/generar_evidencia_contrato.py (junit en schemathesis_junit.xml).",
        "",
        f"Resultado junit: {total['tests']} casos (1 prueba + {len(lineas)} subpruebas, una por operación), "
        f"{total['failures']} fallas, {total['errors']} errores, {total['skipped']} omitidas.",
        f"Operaciones sin ninguna falla: {ok} de {len(lineas)}.",
        "", f"{'Operación':<62} Resultado", *lineas, "", HISTORIA, ""])


def _version_schemathesis() -> str:
    try:
        from importlib.metadata import version

        return version("schemathesis")
    except Exception:  # noqa: BLE001 - solo es el rótulo del archivo
        return "(versión desconocida)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--solo-operaciones", action="store_true")
    parser.add_argument("--ejemplos", type=int, default=int(os.environ.get("SCHEMATHESIS_EJEMPLOS", "5")))
    args = parser.parse_args()
    (AQUI / "operaciones_codigos.txt").write_text(operaciones(), encoding="utf-8")
    print("operaciones_codigos.txt regenerado")
    if not args.solo_operaciones:
        texto = schemathesis(args.ejemplos)
        (AQUI / "schemathesis.txt").write_text(texto, encoding="utf-8")
        print("\n".join(texto.splitlines()[:9]))


if __name__ == "__main__":
    main()
