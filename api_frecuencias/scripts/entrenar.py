"""Entrena el modelo candidato de demanda, lo compara con la línea base (y con el modelo activo) y lo registra.

Especificación §9, RF-018 y RF-019.

Uso:
    python scripts/entrenar.py                       # corte 2025-08-31, semilla 42, variables FEATURE_VERSION (fv2)
    python scripts/entrenar.py --hasta 2025-08-31 --semilla 42 --sin-activar
    python scripts/entrenar.py --version fv1-2026-11-08             # reentrenar con la versión anterior
    python scripts/entrenar.py --compuerta-activo                   # activa solo si no empeora al modelo activo
    python scripts/entrenar.py --verificar-reproducible             # entrena dos veces y compara el sha256

Escribe datos/modelos/<model_id>/modelo.joblib, manifest.json y actualiza datos/modelos/registro.json.
Sin --compuerta-activo, el candidato queda activo si mejora el WAPE de la regla manual (B1) en la validación temporal.
Con --compuerta-activo, además debe tener WAPE de validación <= el del modelo activo en la misma ventana y filas.
Con --compuerta-activo y --sin-activar, la compuerta se mide y se registra, pero el candidato no se activa: queda
para la sombra y la compuerta de la API (así se registró fv3, docs/evidencias/modelo/decision_fv3.md).
Todo se decide con la validación: este script no mide la prueba reservada (su informe es scripts/evaluar_modelo.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.servicios import inferencia, variables  # noqa: E402


def _version(v: str | None) -> str:
    if not v:
        return variables.FEATURE_VERSION
    for k in variables.VERSIONES:
        if k == v or k.split("-")[0] == v:
            return k
    raise SystemExit(f"Versión desconocida {v!r}: {sorted(variables.VERSIONES)}")


def verificar_reproducible(hasta: date, semilla: int, version: str) -> dict:
    """Entrena dos veces con la misma semilla en carpetas temporales: el sha256 del artefacto debe ser idéntico."""
    shas = []
    with tempfile.TemporaryDirectory() as d:
        for k in ("a", "b"):
            r = inferencia.entrenar(hasta, semilla, dir_modelos=Path(d) / k, activar_si_mejora=False, version=version)
            shas.append(r["sha256"])
    return {"sha256_1": shas[0], "sha256_2": shas[1], "identico": shas[0] == shas[1]}


def compuerta_activo(r: dict, hasta: date, activar: bool = True) -> dict:
    """Compara el candidato con el modelo activo en la MISMA ventana de validación y mismas filas (la prueba
    reservada no entra en la decisión ni se imprime). Con activar=False solo registra la decisión."""
    activo = inferencia.modelo_activo()
    val = r["metricas"]["validacion"]
    desde_v, hasta_v = date.fromisoformat(val["desde"]), date.fromisoformat(val["hasta"])
    out = {"activo_previo": activo, "candidato": r["model_id"]}
    m_act = inferencia.evaluar(activo, desde_v, hasta_v)
    out["wape_validacion"] = {"candidato": val["candidato"]["wape"], "activo": m_act["wape"],
                              "b1": val["b1_manual_8sem"]["wape"]}
    no_empeora = val["candidato"]["wape"] <= m_act["wape"]
    supera_b1 = bool(r["supera_linea_base"])
    out["decision"] = (
        "activar: mejora a B1 y no empeora al modelo activo en validación"
        if (no_empeora and supera_b1 and activo != r["model_id"])
        else "conservar el activo: " + ("no mejora a B1" if not supera_b1 else "empeora al activo en validación")
        if activo != r["model_id"] else "el candidato ya es el activo"
    )
    out["activado"] = bool(activar and out["decision"].startswith("activar"))
    if out["activado"]:
        inferencia.activar(r["model_id"], "entrenamiento (compuerta)", out["decision"])
    elif out["decision"].startswith("activar"):
        out["nota"] = "registrado sin activar (--sin-activar): pasa por la sombra y la compuerta de la API"
    out["ventana_validacion"] = f"{desde_v} a {hasta_v} ({hasta + timedelta(days=1)} en adelante)"
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Entrena y registra el modelo de demanda")
    ap.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 8, 31), help="último día de entrenamiento")
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--version", default=None,
                    help="versión de variables (fv1, fv2 o fv3; por defecto FEATURE_VERSION)")
    ap.add_argument("--sin-activar", action="store_true", help="registrar sin activar aunque mejore")
    ap.add_argument("--compuerta-activo", action="store_true", help="activar solo si no empeora al modelo activo")
    ap.add_argument("--verificar-reproducible", action="store_true", help="entrenar dos veces y comparar el sha256")
    ap.add_argument("--salida-json", type=Path, default=None, help="guardar el resumen en este archivo")
    args = ap.parse_args()
    version = _version(args.version)
    resumen: dict = {"version": version, "hasta": str(args.hasta), "semilla": args.semilla}
    if args.verificar_reproducible:
        resumen["reproducibilidad"] = verificar_reproducible(args.hasta, args.semilla, version)
        print("reproducibilidad:", json.dumps(resumen["reproducibilidad"]))
    activar = not (args.sin_activar or args.compuerta_activo)
    r = inferencia.entrenar(args.hasta, args.semilla, activar_si_mejora=activar, version=version)
    filas = []
    for parte in ("validacion",):
        m = r["metricas"].get(parte) or {}
        for nombre in ("candidato", "b1_manual_8sem", "b2_ultima_semana"):
            if nombre in m:
                x = m[nombre]
                filas.append(
                    f"{parte:10s} {nombre:18s} WAPE {x['wape']:6.2f} %  MAE {x['mae']:7.1f}  RMSE {x['rmse']:7.1f}"
                    f"  pico {x['pico']['wape']:6.2f} %  valle {x['valle']['wape']:6.2f} %"
                    + (f"  cobertura P10-P90 {x['cobertura_p10_p90']:.1f} %" if "cobertura_p10_p90" in x else "")
                )
    print(f"modelo {r['model_id']}  sha256 {r['sha256'][:16]}...  corte {r['data_cutoff']}  variables {version}")
    print("\n".join(filas))
    print(r["decision"])
    resumen.update({"model_id": r["model_id"], "sha256": r["sha256"], "decision_entrenamiento": r["decision"]})
    if args.compuerta_activo:
        resumen["compuerta"] = compuerta_activo(r, args.hasta, activar=not args.sin_activar)
        print("compuerta:", json.dumps(resumen["compuerta"], ensure_ascii=False))
    print(
        json.dumps(
            {
                p: {
                    n: v["por_ruta"]
                    for n, v in (r["metricas"].get(p) or {}).items()
                    if isinstance(v, dict) and "por_ruta" in v
                }
                for p in ("validacion",)
            },
            ensure_ascii=False,
        )[:1500]
    )
    if args.salida_json:
        args.salida_json.parent.mkdir(parents=True, exist_ok=True)
        args.salida_json.write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
