"""Huella del código de cada modelo registrado, independiente del sistema operativo (§9.2, §9.3 «registrar código»).

Para cada modelo con artefacto en la carpeta de modelos (o el de --model-id), solo en su manifest.json:
- verifica que «codigo_sha256» sea el SHA-256 con fin de línea LF de los archivos con que se entrenó y busca en git los
  commits en los que cada archivo tiene ese mismo contenido;
- agrega «codigo_sin_docstring_sha256» (el código sin el docstring del módulo: la documentación puede cambiar sin
  cambiar el preprocesamiento), «codigo_normalizacion», «codigo_commit» y «codigo_verificacion»;
- quita «estado» (la fuente de verdad del estado es registro.json y model_registry) y saca de la sección de
  entrenamiento las métricas de la prueba reservada («metricas.prueba» y «nowcast.prueba»): su informe es la clave
  «evaluacion» que escribe scripts/evaluar_modelo.py. Deja constancia en «historial_prueba_reservada».

Nunca toca modelo.joblib, los ONNX ni la calibración: comprueba sus SHA-256 antes y después y se detiene si algo
cambiara. Uso: python scripts/evaluar_codigo_modelo.py [--model-id ID] [--escribir]
(sin --escribir solo muestra lo que haría).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess  # nosec B404
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import datos, inferencia  # noqa: E402

RUTA_GIT = "EntregaFinal/api_frecuencias/app/servicios/"
HISTORIAL_PRUEBA = (
    "Al entrenarse, inferencia.entrenar() también midió la prueba reservada ({prueba}) y esa cifra se consultó al "
    "comparar fv2 con fv1: la prueba quedó como reporte informativo, no como una muestra nunca vista "
    "(docs/evidencias/modelo/decision_fv2.md). Desde entonces entrenar() y la compuerta solo miden la validación; el "
    "informe de la prueba está en la clave «evaluacion» (scripts/evaluar_modelo.py)."
)
# modelos entrenados cuando entrenar() ya no medía la prueba: se consultó al comparar con el activo anterior
HISTORIAL_PRUEBA_COMPARACION = (
    "inferencia.entrenar() no midió la prueba reservada ({prueba}); sí se consultó al comparar este modelo con el "
    "activo anterior (docs/evidencias/modelo/decision_{version}.md), así que es un reporte informativo, no una muestra "
    "nunca vista. La elección se hizo con la validación y los backtests congelados de 2024 y 2025; el informe de la "
    "prueba está en la clave «evaluacion» (scripts/evaluar_modelo.py)."
)


def _git(*args: str) -> str | None:
    try:
        # argumentos fijos de este script (log y show): no hay entrada externa
        r = subprocess.run(["git", *args], cwd=RAIZ,  # noqa: S603, S607  # nosec B603 B607
                           capture_output=True, text=True, timeout=30, check=False, encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def commits_con_contenido(archivo: str, sha_lf: str) -> list[str]:
    """Commits (del más antiguo al más nuevo) en los que `archivo` tiene exactamente ese contenido (SHA-256 con LF)."""
    log = _git("log", "--format=%H", "--", ":/" + RUTA_GIT + archivo) or ""   # «:/» = ruta desde la raíz del repo
    encontrados = []
    for commit in log.split():
        texto = _git("show", f"{commit}:{RUTA_GIT}{archivo}")
        if texto is not None and inferencia.sha256_codigo(texto) == sha_lf:
            encontrados.append(commit)
    return list(reversed(encontrados))


NOTA_SIN_COMMIT = ("la versión con la que se entrenó no quedó en ningún commit (copia de trabajo sin confirmar); su "
                   "reproducibilidad se comprueba reentrenando y comparando el SHA-256 del artefacto")


def sin_doc_actual(nombre: str) -> str:
    """SHA-256 (LF) del archivo actual sin el docstring del módulo."""
    texto = Path(inferencia.__file__).with_name(nombre).read_text(encoding="utf-8")
    return inferencia.sha256_codigo(inferencia.sin_docstring_de_modulo(texto))


def _hashes_protegidos(carpeta: Path, man: dict) -> dict:
    """SHA-256 de los archivos que este script nunca debe cambiar (artefacto, ONNX y calibración)."""
    archivos = [man.get("artefacto")]
    archivos += [a.get("archivo") for a in ((man.get("onnx") or {}).get("archivos") or {}).values()]
    archivos.append((man.get("calibracion") or {}).get("archivo"))
    return {a: hashlib.sha256((carpeta / a).read_bytes()).hexdigest() for a in archivos if a and (carpeta / a).exists()}


def actualizar(carpeta: Path, escribir: bool) -> dict:
    ruta_man = carpeta / inferencia.ARCHIVO_MANIFIESTO
    man = json.loads(ruta_man.read_text(encoding="utf-8"))
    antes = _hashes_protegidos(carpeta, man)
    claves_antes = (man["sha256"], json.dumps(man.get("onnx"), sort_keys=True),
                    json.dumps(man.get("calibracion"), sort_keys=True))
    actuales = {n: Path(inferencia.__file__).with_name(n).read_text(encoding="utf-8")
                for n in inferencia.ARCHIVOS_CODIGO}
    verificacion, sin_doc = {}, {}
    for nombre, sha in (man.get("codigo_sha256") or {}).items():
        commits = commits_con_contenido(nombre, sha)
        texto = None
        if inferencia.sha256_codigo(actuales[nombre]) == sha:
            texto = actuales[nombre]
        elif commits:
            texto = _git("show", f"{commits[0]}:{RUTA_GIT}{nombre}")
        sin_doc[nombre] = None if texto is None else inferencia.sha256_codigo(inferencia.sin_docstring_de_modulo(texto))
        verificacion[nombre] = {
            "sha256_lf_de_entrenamiento": sha,
            "igual_al_archivo_actual": inferencia.sha256_codigo(actuales[nombre]) == sha,
            "sin_docstring_igual_al_actual": sin_doc[nombre] is not None and sin_doc[nombre] == sin_doc_actual(nombre),
            "primer_commit_con_ese_contenido": commits[0] if commits else None,
            "nota": None if commits else NOTA_SIN_COMMIT,
        }
    man.pop("estado", None)
    man["codigo_sin_docstring_sha256"] = sin_doc
    man["codigo_normalizacion"] = inferencia.NORMALIZACION_CODIGO
    todos = [v["primer_commit_con_ese_contenido"] for v in verificacion.values()]
    orden = (_git("log", "--format=%H") or "").split()   # del más nuevo al más antiguo
    # el primer commit en el que TODOS los archivos tienen el contenido del entrenamiento (None si alguno no quedó)
    man["codigo_commit"] = (min(todos, key=lambda c: orden.index(c) if c in orden else len(orden))
                            if todos and all(todos) else None)
    man["codigo_verificacion"] = verificacion
    prueba = (man.get("metricas") or {}).pop("prueba", None)
    (man.get("nowcast") or {}).pop("prueba", None)
    if prueba is not None or "historial_prueba_reservada" not in man:
        rango = (man.get("particion") or {}).get("prueba") or "nov-dic"
        plantilla = HISTORIAL_PRUEBA if prueba is not None else HISTORIAL_PRUEBA_COMPARACION
        man["historial_prueba_reservada"] = plantilla.format(
            prueba=rango, version=str(man.get("feature_version") or "").split("-")[0])
    man.setdefault("nota_prueba_reservada", "la prueba reservada no se evalúa al entrenar ni en la compuerta: su "
                                            "informe lo escribe scripts/evaluar_modelo.py en la clave «evaluacion»")
    if claves_antes != (man["sha256"], json.dumps(man.get("onnx"), sort_keys=True),
                        json.dumps(man.get("calibracion"), sort_keys=True)):
        raise RuntimeError("el script no puede cambiar el hash del artefacto, de los ONNX ni de la calibración")
    if escribir:
        ruta_man.write_text(json.dumps(man, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if _hashes_protegidos(carpeta, man) != antes:
        raise RuntimeError("cambió un archivo protegido (artefacto, ONNX o calibración)")
    return {"model_id": man.get("model_id"), "codigo_commit": man["codigo_commit"], "verificacion": verificacion,
            "protegidos_sin_cambio": sorted(antes), "escrito": escribir}


def texto_de_entrenamiento(nombre: str, sha_sin_doc: str) -> tuple[str, str] | None:
    """(commit, texto) más reciente de git en el que `nombre`, sin el docstring del módulo, tiene ese SHA-256 (LF)."""
    log = _git("log", "--format=%H", "--", ":/" + RUTA_GIT + nombre) or ""
    for commit in log.split():   # del más nuevo al más antiguo
        texto = _git("show", f"{commit}:{RUTA_GIT}{nombre}")
        if texto is not None and inferencia.sha256_codigo(inferencia.sin_docstring_de_modulo(texto)) == sha_sin_doc:
            return commit, texto
    return None


def compatibilidad(carpeta: Path, escribir: bool) -> dict:
    """Si variables.py cambió después de entrenar el modelo (por ejemplo, al registrar una versión de variables nueva),
    comprueba que el código actual da EXACTAMENTE las mismas variables y los mismos pronósticos (punto, P10 y P90) que
    el código con que se entrenó, tomado de git, en toda la serie empaquetada. Con --escribir y diferencia 0 lo deja en
    manifest «compatibilidad_codigo» (no toca el artefacto, los ONNX ni la calibración)."""
    import importlib.util
    import tempfile
    from datetime import UTC, datetime

    import numpy as np
    import pandas as pd

    from app.servicios import variables

    ruta_man = carpeta / inferencia.ARCHIVO_MANIFIESTO
    man = json.loads(ruta_man.read_text(encoding="utf-8"))
    antes = _hashes_protegidos(carpeta, man)
    sha_ent = (man.get("codigo_sin_docstring_sha256") or {}).get("variables.py")
    actual = sin_doc_actual("variables.py")
    if sha_ent == actual:
        return {"model_id": man["model_id"], "compatibilidad": "variables.py es el del entrenamiento"}
    ref = texto_de_entrenamiento("variables.py", sha_ent) if sha_ent else None
    if ref is None:
        raise SystemExit(f"{man['model_id']}: no está en git la versión de variables.py con que se entrenó")
    commit, texto = ref
    with tempfile.TemporaryDirectory() as d:
        archivo = Path(d) / "variables_entrenamiento.py"
        archivo.write_text(texto, encoding="utf-8")
        # dentro del paquete app.servicios, para que sus importaciones relativas (datos) sean las mismas
        spec = importlib.util.spec_from_file_location("app.servicios._variables_entrenamiento", archivo)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    serie = datos.demanda_horaria()
    cols, clave = list(man["variables"]), ["ruta", "fecha", "hora"]
    a = mod.construir_variables(serie).set_index(clave, drop=False)[cols].sort_index()
    b = variables.construir_variables(serie).set_index(clave, drop=False)[cols].sort_index()
    xa, xb = a.to_numpy(float), b.to_numpy(float)
    mismos_nan = bool(a.index.equals(b.index) and (np.isnan(xa) == np.isnan(xb)).all())
    dif = np.abs(np.nan_to_num(xa) - np.nan_to_num(xb))
    modelo = inferencia.cargar(man["model_id"], carpeta.parent)
    pred = {p: float(np.abs(modelo[p].predict(pd.DataFrame(xa, columns=cols))
                            - modelo[p].predict(pd.DataFrame(xb, columns=cols))).max())
            for p in ("punto", "p10", "p90")}
    res = {
        "variables_py_sin_docstring_sha256": actual,
        # el blob de git es el contenido mismo (igual en cualquier clon que lo tenga: git cat-file -p <blob>)
        "referencia": {"blob_git": (_git("rev-parse", f"{commit}:{RUTA_GIT}variables.py") or "").strip(),
                       "variables_py_sin_docstring_sha256": sha_ent},
        "filas": len(a), "columnas": len(cols), "mismas_filas_y_mismos_nan": mismos_nan,
        "max_dif_variables": float(dif.max()) if dif.size else 0.0, "max_dif_pronostico": pred,
        "verificado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "nota": ("variables.py cambió después de entrenar este modelo (se registró otra versión de variables); con "
                 "sus columnas, el código actual da las mismas variables y los mismos pronósticos que el del "
                 "entrenamiento"),
    }
    ok = mismos_nan and res["max_dif_variables"] == 0 and all(v == 0 for v in pred.values())
    if escribir and ok:
        man["compatibilidad_codigo"] = res
        ruta_man.write_text(json.dumps(man, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if _hashes_protegidos(carpeta, man) != antes:
        raise RuntimeError("cambió un archivo protegido (artefacto, ONNX o calibración)")
    return {"model_id": man["model_id"], "compatible": ok, "escrito": bool(escribir and ok), **res}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--escribir", action="store_true", help="escribe los manifest.json (sin esto, solo muestra)")
    ap.add_argument("--compatibilidad", action="store_true",
                    help="solo comprueba que el variables.py actual da las mismas variables y pronósticos que el del "
                         "entrenamiento (manifest «compatibilidad_codigo»)")
    a = ap.parse_args()
    raiz = datos.carpeta_modelos()
    carpetas = [raiz / a.model_id] if a.model_id else sorted(p.parent for p in raiz.glob("*/manifest.json"))
    if a.compatibilidad:
        print(json.dumps([compatibilidad(c, a.escribir) for c in carpetas], ensure_ascii=False, indent=2))
        return
    salida = [actualizar(c, a.escribir) for c in carpetas]
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
