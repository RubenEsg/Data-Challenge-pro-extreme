"""Tabla de endpoints de la especificación técnica (E02), generada desde la API para que no haya deriva.

    <python del venv de la API> EntregaFinal/documentos/tabla_api.py

Lee el OpenAPI de la aplicación FastAPI en vivo (app.main.app.openapi(), sin levantar servidor ni conectarse a ninguna
base) y el rol mínimo de cada operación con app.seguridad.rol_requerido. Si la aplicación no se puede importar (por
ejemplo, sin su venv), usa api_frecuencias/docs/openapi.json y la regla por omisión (lectura = operador; escritura =
admin salvo la política explícita). Escribe documentos/generado/tabla_api.tex y comprueba que tenga una fila por
operación.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
API = AQUI.parent / "api_frecuencias"
SALIDA = AQUI / "generado" / "tabla_api.tex"
METODOS = ("get", "post", "put", "patch", "delete")


def escapar(t: str) -> str:
    reemplazos = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                  "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(reemplazos.get(c, c) for c in t)


def openapi_y_roles():
    sys.path.insert(0, str(API))
    os.chdir(API)
    try:
        import logging
        logging.disable(logging.CRITICAL)
        from app.main import app
        from app.seguridad import rol_requerido
        return app.openapi(), rol_requerido, "la aplicación FastAPI (app.main)"
    except Exception as exc:  # noqa: BLE001  (respaldo documentado)
        print(f"AVISO: no se pudo importar la API ({exc!r}); se usa docs/openapi.json")
        doc = json.loads((API / "docs" / "openapi.json").read_text(encoding="utf-8"))

        def rol(metodo, ruta):
            return "operador" if metodo.upper() == "GET" else "analista/admin"
        return doc, rol, "api\\_frecuencias/docs/openapi.json"


def main():
    doc, rol_requerido, origen = openapi_y_roles()
    filas, raiz, n_ops = [], [], 0
    for ruta, ops in doc["paths"].items():
        for metodo, op in ops.items():
            if metodo not in METODOS:
                continue
            n_ops += 1
            publica = not ruta.startswith("/api/v1")
            rol = "pública" if publica else rol_requerido(metodo.upper(), ruta)
            corta = ruta.replace("/api/v1", "", 1) if not publica else ruta
            resumen = (op.get("summary") or "").strip().rstrip(".")
            if len(resumen) > 92:
                resumen = resumen[:90].rsplit(" ", 1)[0] + "…"
            # Las rutas fuera de /api/v1 (/health, /metrics) van aparte y con su ruta absoluta, en la raíz.
            (raiz if publica else filas).append(
                f"\\texttt{{{metodo.upper()}}} & \\path{{{corta}}} & {rol} & {escapar(resumen)} \\\\")
    if raiz:
        subtitulo = ("\\multicolumn{4}{@{}l}{\\emph{En la raíz del servidor, fuera de \\texttt{/api/v1}"
                     " (ruta absoluta)}} \\\\")
        filas += ["\\midrule", subtitulo, *raiz]
    version = doc.get("info", {}).get("version", "")
    n_v1 = sum(1 for ruta, ops in doc["paths"].items() if ruta.startswith("/api/v1") for m in ops if m in METODOS)
    (SALIDA.parent / "api_cifras.tex").parent.mkdir(exist_ok=True)
    (SALIDA.parent / "api_cifras.tex").write_text("\n".join([
        f"% Generado por documentos/tabla_api.py desde {origen}. No editar a mano.",
        f"\\newcommand{{\\NOperaciones}}{{{n_ops}}}",
        f"\\newcommand{{\\NOperacionesVuno}}{{{n_v1}}}",
        f"\\newcommand{{\\VersionAPI}}{{{escapar(version)}}}",
        f"\\newcommand{{\\OrigenTablaAPI}}{{{origen}}}"]) + "\n", encoding="utf-8")
    cuerpo = [
        f"% Generado por documentos/tabla_api.py desde {origen}: {n_ops} operaciones. No editar a mano.",
        "\\begin{longtable}{@{}l>{\\raggedright\\arraybackslash}p{5.3cm}l>{\\raggedright\\arraybackslash}p{7.2cm}@{}}",
        "\\toprule Método & Ruta (bajo \\texttt{/api/v1}) & Rol mínimo & Finalidad \\\\ \\midrule \\endhead",
        "\\bottomrule \\endfoot",
        *filas,
        "\\end{longtable}",
    ]
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text("\n".join(cuerpo) + "\n", encoding="utf-8")
    assert sum(1 for f in filas if f.startswith("\\texttt{")) == n_ops, "la tabla no tiene una fila por operación"
    print(f"tabla_api.tex: {n_ops} operaciones (fuente: {origen})")


if __name__ == "__main__":
    main()
