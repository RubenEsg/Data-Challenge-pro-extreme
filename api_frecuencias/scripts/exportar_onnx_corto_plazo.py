"""Exporta a ONNX los 18 árboles del modelo de corto plazo y comprueba su paridad con LightGBM (spec v1.5 §9.1
«candidato tabular exportado a ONNX», §9.2 «ONNX Runtime», RNF-011).

Para cada artefacto (nivel, horizonte y ruta) escribe datos/modelos/corto_plazo/<model_id>/onnx/<clave>.onnx.gz
(app/servicios/onnx_corto_plazo.py) y su SHA-256 en onnx/manifest_onnx.json. La paridad se mide con las variables
reales de días de la prueba reservada (uno por mes de julio a diciembre de 2025, todas las medias horas de 04:00 a
21:00, la ruta y cada segmento), más las mismas filas con un 10 % de valores faltantes: la diferencia relativa máxima
debe quedar en la precisión de float32 (≤ 1e-5). El modelo de LightGBM y su manifiesto no cambian.

Uso (desde api_frecuencias/):  python scripts/exportar_onnx_corto_plazo.py [--model-id ID]
Escribe además docs/evidencias/modelo/corto_plazo_onnx.json y .md.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import corto_plazo as CP  # noqa: E402
from app.servicios import onnx_corto_plazo as O  # noqa: E402

DIAS_PARIDAD = [date(2025, 7, 9), date(2025, 8, 13), date(2025, 9, 17), date(2025, 10, 15), date(2025, 11, 19),
                date(2025, 12, 10)]
TOLERANCIA_RELATIVA = 1e-5


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "modelo")
    a = ap.parse_args()
    t0 = time.time()
    with CP.sin_calidad():
        modelo = CP.cargar(a.model_id)
        mid = modelo["model_id"]
        carpeta = CP.carpeta_modelos() / mid / CP.CARPETA_ONNX
        carpeta.mkdir(parents=True, exist_ok=True)
        man: dict = {"model_id": mid, "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
                     "conversor": "app/servicios/onnx_corto_plazo.py (TreeEnsembleRegressor ai.onnx.ml 3 + Exp)",
                     "tolerancia_relativa": TOLERANCIA_RELATIVA, "dias_paridad": [d.isoformat() for d in DIAS_PARIDAD],
                     "artefactos": {}}
        rng = np.random.default_rng(42)
        for clave, booster in modelo["arboles"].items():
            nivel, h, r = clave.split("_")
            datos = O.convertir(booster, clave).SerializeToString()
            comprimido = gzip.compress(datos, mtime=0)
            archivo = carpeta / f"{clave}.onnx.gz"
            archivo.write_bytes(comprimido)
            sesion = O.sesion(datos)
            xs = []
            for d in DIAS_PARIDAD:
                dia = CP._dia(mid, int(r[1:]), CP.dia_de_fecha(d), int(h[1:]), niveles=(nivel,))
                xs.append(dia[nivel]["x"].reshape(-1, dia[nivel]["x"].shape[-1]))
            x = np.vstack(xs)
            x = np.vstack([x, np.where(rng.random(x.shape) < 0.1, np.nan, x)])
            p_lgb, p_onnx = booster.predict(x), O.predecir(sesion, x)
            rel = float(np.max(np.abs(p_lgb - p_onnx) / np.maximum(np.abs(p_lgb), 1e-9)))
            man["artefactos"][clave] = {
                "archivo": archivo.name, "sha256": hashlib.sha256(comprimido).hexdigest(), "bytes_onnx": len(datos),
                "bytes_gz": len(comprimido), "arboles": booster.num_trees(), "filas_paridad": int(len(x)),
                "diferencia_relativa_maxima": rel, "diferencia_absoluta_maxima": float(np.max(np.abs(p_lgb - p_onnx))),
                "paridad": rel <= TOLERANCIA_RELATIVA}
            print(f"  {clave}: {len(x)} filas, diferencia relativa máxima {rel:.2e}", flush=True)
    man["paridad"] = all(x["paridad"] for x in man["artefactos"].values())
    man["segundos"] = round(time.time() - t0, 1)
    (carpeta / CP.ARCHIVO_ONNX).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "corto_plazo_onnx.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.salida / "corto_plazo_onnx.md").write_text(markdown(man), encoding="utf-8")
    print(json.dumps({"paridad": man["paridad"], "segundos": man["segundos"]}, ensure_ascii=False))
    if not man["paridad"]:
        raise SystemExit(1)


def markdown(man: dict) -> str:
    filas = sorted(man["artefactos"].items())
    peor = max(x["diferencia_relativa_maxima"] for _, x in filas)
    n = sum(x["filas_paridad"] for _, x in filas)
    lineas = [
        "# Modelo de corto plazo en ONNX: exportación y paridad",
        "",
        f"Generado por `scripts/exportar_onnx_corto_plazo.py` el {man['generado_en'][:10]} para `{man['model_id']}` "
        f"(spec v1.5 §9.1 «candidato tabular exportado a ONNX», §9.2).",
        "",
        "Cada uno de los 18 artefactos de LightGBM (nivel ruta y segmento, horizontes de 30, 60 y 120 minutos, tres "
        "rutas) se tradujo a un modelo ONNX: un `TreeEnsembleRegressor` (ai.onnx.ml 3) con los mismos umbrales y "
        "hojas en doble precisión, la misma regla para los faltantes y un `Exp` (el objetivo es Poisson). Los archivos "
        "quedan comprimidos en `datos/modelos/corto_plazo/<model_id>/onnx/`, con su SHA-256 en `manifest_onnx.json`; "
        "con `MOTOR_INFERENCIA=onnx` la API pronostica con ONNX Runtime y verifica cada hash al cargar.",
        "",
        f"Paridad con LightGBM: {n:,} filas reales de seis días de la prueba reservada (uno por mes, todas las medias "
        f"horas de 04:00 a 21:00) más las mismas filas con un 10 % de valores faltantes. Diferencia relativa máxima: "
        f"**{peor:.1e}** (tolerancia {man['tolerancia_relativa']:.0e}, la precisión de float32). Paridad: "
        f"**{'sí' if man['paridad'] else 'no'}**.".replace(",", "."),
        "",
        "| Artefacto | Árboles | Filas | Diferencia relativa máxima | ONNX (MB, comprimido) | SHA-256 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for clave, x in filas:
        lineas.append(f"| `{clave}` | {x['arboles']} | {x['filas_paridad']:,} | "
                      f"{x['diferencia_relativa_maxima']:.1e} | {x['bytes_gz'] / 1e6:.2f} | "
                      f"`{x['sha256'][:16]}…` |".replace(",", "."))
    lineas += ["", "La explicación local (TreeSHAP) sigue saliendo de LightGBM (`pred_contrib`): ONNX solo da la "
               "predicción.", ""]
    return "\n".join(lineas)


if __name__ == "__main__":
    main()
