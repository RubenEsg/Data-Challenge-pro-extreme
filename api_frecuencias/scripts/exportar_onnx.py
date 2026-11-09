"""Exporta un modelo fv2 (punto Poisson, P10 y P90) a ONNX con skl2onnx y prueba la paridad con scikit-learn.

§9.1 «Gradient Boosting exportado a ONNX» y §9.2 «el artefacto se carga con ONNX Runtime ... se verifica su hash».

- target_opset {'': 17, 'ai.onnx.ml': 3}; entrada X float32 [n, columnas de la versión] (variables.matriz_x).
- skl2onnx traduce el árbol del HistGradientBoostingRegressor pero NO el enlace de la pérdida Poisson: el grafo da el
  logaritmo. Se agrega un nodo Exp a la salida del punto (P10/P90 son de pérdida cuantil, enlace identidad).
- Cuña local (solo durante la conversión): protobuf 7.36 rechaza bool/np.bool_ en atributos enteros («Expected an int,
  got a boolean»); se convierten a int nativo en onnx.helper.make_attribute.
- onnx.checker valida cada grafo; los archivos quedan en datos/modelos/<id>/modelo_{punto,p10,p90}.onnx y su SHA-256
  en manifest['onnx'] (escritura atómica; el sha256 del joblib no cambia, así que el registro sigue válido).
- Paridad: diferencia absoluta (< 0,01 pasajeros) y relativa (< 1e-3, sobre max(|y|, 1)) máxima frente a scikit-learn
  en filas reales posteriores al corte, WAPE con ambos motores y latencia por fila y por lote. La diferencia viene de
  que ONNX compara los umbrales del árbol en float32.

Uso:  python scripts/exportar_onnx.py [--model-id hgb_fv2_20250831_s42] [--dir-modelos datos/modelos]
                                      [--filas 3000] [--evidencia docs/evidencias/monitoreo/onnx_paridad.json]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

OPSET = {"": 17, "ai.onnx.ml": 3}
TOLERANCIA_REL = 1e-3
TOLERANCIA_ABS = 0.01  # pasajeros: ONNX evalúa los umbrales del árbol en float32 y sklearn en float64


@contextlib.contextmanager
def cuna_bool_a_int():
    """protobuf 7.x: los atributos enteros no aceptan bool; se convierten (y los np.generic) a tipos nativos."""
    import onnx.helper as oh

    original = oh.make_attribute

    def _nativo(v):
        if isinstance(v, (bool, np.bool_)):
            return int(v)
        if isinstance(v, np.generic):
            return v.item()
        return v

    def make_attribute(key, value, *a, **k):
        if isinstance(value, (list, tuple, np.ndarray)):
            value = [_nativo(v) for v in value]
        else:
            value = _nativo(value)
        return original(key, value, *a, **k)

    oh.make_attribute = make_attribute
    try:
        yield
    finally:
        oh.make_attribute = original


def convertir(modelo, n_columnas: int, enlace_exp: bool):
    """Árbol de sklearn -> ModelProto (con Exp al final si la pérdida es Poisson)."""
    import onnx
    from onnx import helper
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    with cuna_bool_a_int():
        onx = convert_sklearn(modelo, initial_types=[("X", FloatTensorType([None, n_columnas]))], target_opset=OPSET)
    if enlace_exp:
        salida = onx.graph.output[0].name
        crudo = f"{salida}_log"
        for nodo in onx.graph.node:
            for i, o in enumerate(nodo.output):
                if o == salida:
                    nodo.output[i] = crudo
        onx.graph.node.append(helper.make_node("Exp", [crudo], [salida], name="enlace_poisson_exp"))
    onnx.checker.check_model(onx)
    return onx


def _guardar_json_atomico(ruta: Path, obj: dict) -> None:
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, ruta)


def exportar(model_id: str | None = None, dir_modelos: Path | None = None, filas: int = 3000,
             actualizar_manifiesto: bool = True) -> dict:
    """Exporta, verifica paridad y (si se pide) registra los SHA-256 en el manifiesto. Devuelve la evidencia."""
    import onnx
    import onnxruntime as ort
    import skl2onnx

    from app.servicios import datos, inferencia, onnx_motor, variables

    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    os.environ["MOTOR_INFERENCIA"] = "sklearn"
    modelo = inferencia.cargar(model_id, dm)  # verifica el sha256 del joblib
    if modelo["tipo"] == "linea_base":
        raise SystemExit("Las líneas base no tienen artefacto que exportar")
    version = modelo["feature_version"]
    if variables.categoricas(version):
        raise SystemExit(f"{modelo['model_id']} usa variables categóricas nativas ({version}): solo fv2 es exportable")
    carpeta = dm / modelo["model_id"]
    cols = variables.columnas(version)
    man_ruta = carpeta / "manifest.json"
    man = json.loads(man_ruta.read_text(encoding="utf-8"))

    archivos, parte_info = {}, {}
    for parte in onnx_motor.PARTES:
        sk = modelo[parte]
        onx = convertir(sk, len(cols), enlace_exp=(parte == "punto"))
        destino = carpeta / f"modelo_{parte}.onnx"
        destino.write_bytes(onx.SerializeToString())
        archivos[parte] = {"archivo": destino.name, "sha256": onnx_motor.sha256(destino),
                           "bytes": destino.stat().st_size,
                           "enlace": "exp (Poisson)" if parte == "punto" else "identidad"}

    # paridad con filas reales posteriores al corte (validación + prueba) y anteriores (entrenamiento)
    t = inferencia._filas_utiles(inferencia.tabla_variables())
    rng = np.random.default_rng(42)
    posteriores = t[t["fecha"] > modelo["data_cutoff"]]
    base = posteriores if len(posteriores) >= min(filas, 200) else t
    muestra = base.iloc[np.sort(rng.choice(len(base), size=min(filas, len(base)), replace=False))]
    x = variables.matriz_x(muestra, version)
    y = muestra["pasajeros"].to_numpy(float)
    paridad = {}
    for parte in onnx_motor.PARTES:
        m_onnx = onnx_motor.ModeloOnnx(carpeta / archivos[parte]["archivo"], archivos[parte]["sha256"])
        t0 = time.perf_counter()
        y_sk = modelo[parte].predict(x)
        ms_sk = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        y_on = m_onnx.predict(x)
        ms_on = (time.perf_counter() - t0) * 1000
        una = x.iloc[[0]]
        t0 = time.perf_counter()
        for _ in range(20):
            m_onnx.predict(una)
        ms_fila_on = (time.perf_counter() - t0) * 1000 / 20
        t0 = time.perf_counter()
        for _ in range(5):
            modelo[parte].predict(una)
        ms_fila_sk = (time.perf_counter() - t0) * 1000 / 5
        dif = np.abs(y_on - y_sk)
        rel = dif / np.maximum(np.abs(y_sk), 1.0)
        paridad[parte] = {
            "filas": int(len(x)),
            "max_abs": float(dif.max()),
            "max_rel": float(rel.max()),
            "p999_rel": float(np.quantile(rel, 0.999)),
            "wape_sklearn": round(float(np.abs(y_sk - y).sum() / y.sum() * 100), 4),
            "wape_onnx": round(float(np.abs(y_on - y).sum() / y.sum() * 100), 4),
            "ms_lote_sklearn": round(ms_sk, 2), "ms_lote_onnx": round(ms_on, 2),
            "ms_fila_sklearn": round(ms_fila_sk, 3), "ms_fila_onnx": round(ms_fila_on, 3),
            "aprobada": bool(rel.max() < TOLERANCIA_REL and dif.max() < TOLERANCIA_ABS),
        }
        parte_info[parte] = paridad[parte]["aprobada"]
    evidencia = {
        "model_id": modelo["model_id"], "feature_version": version, "columnas": cols,
        "sha256_joblib": modelo["sha256"], "opset": OPSET, "archivos": archivos, "paridad": paridad,
        "tolerancia_rel": TOLERANCIA_REL, "tolerancia_abs_pasajeros": TOLERANCIA_ABS,
        "aprobada": all(parte_info.values()),
        "muestra": {"desde": str(muestra["fecha"].min()), "hasta": str(muestra["fecha"].max()),
                    "posteriores_al_corte": bool(len(posteriores) >= min(filas, 200))},
        "versiones": {"skl2onnx": skl2onnx.__version__, "onnx": onnx.__version__, "onnxruntime": ort.__version__,
                      "sklearn": __import__("sklearn").__version__, "numpy": np.__version__,
                      "protobuf": __import__("google.protobuf").protobuf.__version__},
        "exportado_en": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if not evidencia["aprobada"]:
        for parte in onnx_motor.PARTES:
            (carpeta / archivos[parte]["archivo"]).unlink(missing_ok=True)
        raise SystemExit(f"Paridad ONNX no aprobada: {json.dumps(paridad, ensure_ascii=False)}")
    if actualizar_manifiesto:
        man["onnx"] = {k: evidencia[k] for k in ("opset", "archivos", "tolerancia_rel", "exportado_en", "versiones")}
        man["onnx"]["paridad_max_rel"] = {p: paridad[p]["max_rel"] for p in onnx_motor.PARTES}
        _guardar_json_atomico(man_ruta, man)
        inferencia.limpiar_cache()
    return evidencia


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model-id", default=None, help="por omisión, el activo del registro en disco")
    p.add_argument("--dir-modelos", type=Path, default=None)
    p.add_argument("--filas", type=int, default=3000)
    p.add_argument("--evidencia", type=Path, default=RAIZ / "docs" / "evidencias" / "monitoreo" / "onnx_paridad.json")
    a = p.parse_args()
    ev = exportar(a.model_id, a.dir_modelos, a.filas)
    a.evidencia.parent.mkdir(parents=True, exist_ok=True)
    a.evidencia.write_text(json.dumps(ev, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for parte, d in ev["paridad"].items():
        print(f"{parte}: max_abs {d['max_abs']:.2e}  max_rel {d['max_rel']:.2e}  WAPE sklearn {d['wape_sklearn']} "
              f"= onnx {d['wape_onnx']}  fila {d['ms_fila_sklearn']} ms -> {d['ms_fila_onnx']} ms")
    print("evidencia:", a.evidencia)


if __name__ == "__main__":
    main()
