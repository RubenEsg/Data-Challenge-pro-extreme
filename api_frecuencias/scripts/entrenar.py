"""Entrena el modelo candidato de demanda, lo compara con la línea base y lo registra.

Especificación §9, RF-018 y RF-019.

Uso:
    python scripts/entrenar.py                       # corte 2025-08-31, semilla 42
    python scripts/entrenar.py --hasta 2025-08-31 --semilla 42 --sin-activar

Escribe datos/modelos/<model_id>/modelo.joblib, manifest.json y actualiza datos/modelos/registro.json.
El candidato solo queda activo si mejora el WAPE de la regla manual (B1) en la validación temporal.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.servicios import inferencia  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Entrena y registra el modelo de demanda")
    ap.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 8, 31), help="último día de entrenamiento")
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--sin-activar", action="store_true", help="registrar sin activar aunque mejore")
    args = ap.parse_args()
    r = inferencia.entrenar(args.hasta, args.semilla, activar_si_mejora=not args.sin_activar)
    filas = []
    for parte in ("validacion", "prueba"):
        m = r["metricas"].get(parte) or {}
        for nombre in ("candidato", "b1_manual_8sem", "b2_ultima_semana"):
            if nombre in m:
                x = m[nombre]
                filas.append(
                    f"{parte:10s} {nombre:18s} WAPE {x['wape']:6.2f} %  MAE {x['mae']:7.1f}  RMSE {x['rmse']:7.1f}"
                    f"  pico {x['pico']['wape']:6.2f} %  valle {x['valle']['wape']:6.2f} %"
                    + (f"  cobertura P10-P90 {x['cobertura_p10_p90']:.1f} %" if "cobertura_p10_p90" in x else "")
                )
    print(f"modelo {r['model_id']}  sha256 {r['sha256'][:16]}...  corte {r['data_cutoff']}")
    print("\n".join(filas))
    print(r["decision"])
    print(
        json.dumps(
            {
                p: {
                    n: v["por_ruta"]
                    for n, v in (r["metricas"].get(p) or {}).items()
                    if isinstance(v, dict) and "por_ruta" in v
                }
                for p in ("prueba",)
            },
            ensure_ascii=False,
        )[:1500]
    )


if __name__ == "__main__":
    main()
