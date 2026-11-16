"""Evidencia de la explicación local SHAP y de las bandas de un modelo registrado (RF-006, RF-015, §9.4).

Escribe un JSON (por omisión docs/evidencias/modelo/explicacion_local_y_bandas.json, el del modelo activo; con
--model-id, el de ese modelo, p. ej. el candidato fv3 en docs/evidencias/modelo/candidato_fv3/) con:
- reconstruccion_prueba_reservada: en las horas de la prueba reservada, exp(base + Σ phi) = pronóstico del modelo de
  punto (error relativo máximo y percentil 99). Es lo que permite dar factores multiplicativos exactos.
- importancia_media_abs_shap_prueba: media de |phi| (escala logarítmica) por variable en esas horas.
- latencia_shap_por_fila_ms (200 filas, de una en una) y latencia_predecir_ms (75 llamadas a predecir() completo:
  modelos, SHAP, calibración y factor intradía).
- ejemplo_CL72_2025_11_01_04h_60min: la respuesta de predecir() para CL 72 el 2025-11-01 a las 4 h (60 min).
- reversion_modelos_anteriores: los otros modelos del registro siguen cargando y prediciendo con el código actual
  (RF-019), cada uno con su versión de variables.

El archivo del modelo activo fv2 (explicacion_local_y_bandas.json) se midió el 9-11-2026 antes de este script, con
el mismo método (docs/evidencias/modelo/decision_fv2.md, «Explicación local»).

Uso: python scripts/evidencia_explicacion_local.py [--model-id ID] [--salida RUTA.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import inferencia, variables  # noqa: E402

RUTAS = ("SILENCIO", "CRA 54", "CL 72")
OTROS = ("hgb_fv3_20250831_s42", "hgb_fv2_20250831_s42", "hgb_fv1_20250831_s42")


def _percentiles(ms: list[float]) -> dict:
    a = np.asarray(ms, float)
    return {"n": int(len(a)), "p50": round(float(np.median(a)), 2), "p95": round(float(np.quantile(a, 0.95)), 2),
            "max": round(float(a.max()), 2)}


def medir(model_id: str | None = None) -> dict:
    t0 = time.perf_counter()
    out: dict = {"precalentar": inferencia.precalentar(model_id)}
    modelo = inferencia.cargar(model_id)
    mid = modelo["model_id"]
    man = modelo["manifiesto"]
    version = modelo["feature_version"]
    out["modelo"] = {"model_id": mid, "feature_version": version, "sha256": man["sha256"],
                     "estado": inferencia.registro()["modelos"].get(mid, {}).get("estado"),
                     "shap_exacto": not variables.categoricas(version)}
    desde = date.fromisoformat(man["particion"]["prueba"].split(" a ")[0])
    t = inferencia._filas_utiles(inferencia.tabla_variables())
    te = t[t["fecha"] >= desde].reset_index(drop=True)
    e = inferencia.explicar_filas(modelo, te)
    pred = modelo["punto"].predict(variables.matriz_x(te, version))
    rec = np.exp(e["base_log"] + e["phi"].sum(axis=1))
    err = np.abs(rec - pred) / np.maximum(np.abs(pred), 1e-12)
    out["reconstruccion_prueba_reservada"] = {
        "desde": str(desde), "hasta": str(te["fecha"].max()), "filas": int(len(te)),
        "error_rel_max": float(err.max()), "error_rel_p99": float(np.quantile(err, 0.99)),
        "base_pasajeros": round(float(np.exp(e["base_log"])), 1),
    }
    imp = np.abs(e["phi"]).mean(axis=0)
    out["importancia_media_abs_shap_prueba"] = [
        {"variable": c, "media_abs_log": round(float(v), 4)}
        for c, v in sorted(zip(e["columnas"], imp, strict=True), key=lambda x: -x[1])]
    ms = []
    for i in range(200):
        t1 = time.perf_counter()
        inferencia.explicar_filas(modelo, te.iloc[[i * (len(te) // 200)]])
        ms.append((time.perf_counter() - t1) * 1000)
    out["latencia_shap_por_fila_ms"] = _percentiles(ms)
    ms = []
    for i in range(75):
        inst = datetime(2025, 11, 3, 6, 0, tzinfo=inferencia.ZONA) + timedelta(days=i % 25, hours=i % 12)
        t1 = time.perf_counter()
        inferencia.predecir(RUTAS[i % 3], inst, 60, model_id=mid)
        ms.append((time.perf_counter() - t1) * 1000)
    out["latencia_predecir_ms"] = _percentiles(ms)
    r = inferencia.predecir("CL 72", datetime(2025, 11, 1, 4, 0, tzinfo=inferencia.ZONA), 60, model_id=mid)
    out["ejemplo_CL72_2025_11_01_04h_60min"] = {
        k: r.get(k) for k in ("pasajeros", "p10", "p90", "p10_modelo", "p90_modelo", "ajuste_conformal", "explicacion",
                              "explicacion_local")}
    reg = inferencia.registro()["modelos"]
    out["reversion_modelos_anteriores"] = []
    for otro in OTROS:
        if otro == mid or otro not in reg:
            continue
        r = inferencia.predecir("CL 72", datetime(2025, 11, 3, 7, 0, tzinfo=inferencia.ZONA), 60, model_id=otro)
        out["reversion_modelos_anteriores"].append({
            "model_id": otro, "estado": reg[otro].get("estado"),
            "feature_version": inferencia.cargar(otro)["feature_version"],
            "pasajeros": r["pasajeros"], "explicacion_local": (r.get("explicacion_local") or {}).get("metodo")})
    out["generado_en"] = datetime.now(inferencia.ZONA).isoformat(timespec="seconds")
    out["segundos"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-id", default=None, help="modelo a medir (por omisión, el activo)")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "docs" / "evidencias" / "modelo" / "explicacion_local_y_bandas.json")
    a = ap.parse_args()
    res = medir(a.model_id)
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    rc = res["reconstruccion_prueba_reservada"]
    print(f"{res['modelo']['model_id']}: reconstrucción en {rc['filas']} horas, error relativo máx. "
          f"{rc['error_rel_max']:.1e}; SHAP por fila p50 {res['latencia_shap_por_fila_ms']['p50']} ms; predecir p50 "
          f"{res['latencia_predecir_ms']['p50']} ms, p95 {res['latencia_predecir_ms']['p95']} ms")
    for r in res["reversion_modelos_anteriores"]:
        print(f"reversión {r['model_id']} ({r['feature_version']}): {r['pasajeros']} pasajeros, "
              f"{r['explicacion_local']}")


if __name__ == "__main__":
    main()
