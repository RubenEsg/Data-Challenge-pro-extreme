"""Tipologías de capacidad por ruta (§10.1, «asignación sugerida de capacidad cuando hay tipologías distintas»).

Lee insumos_sobusa/flota_sobusa.csv (reporte de flota de Sobusa sin datos personales: placa, ruta, clase, sentados y de
pie) y escribe app/servicios/tipologias_flota.json, que la API versiona con el código. La salida NO lleva placas: solo
conteos y capacidades agregadas por ruta y tipología.

Reglas (las mismas de insumos_sobusa/analisis_flota.md):
- capacidad = sentados + de pie; se descartan las filas de relleno (capacidad 0, placas «XXX»);
- el reporte es una lista vehículo-conductor: una placa se cuenta una sola vez por ruta (mediana de su capacidad si sus
  filas difieren);
- rutas del reto: «SILENCIO» -> SILENCIO, «KRA. 54 UNINORTE» -> CRA 54, «72» -> CL 72;
- tipologías por rango de capacidad (puestos totales), elegidas en los saltos de la distribución de las tres rutas
  (46-47, 49-52, 55-58 y 70-74 son los grupos que concentran los buses):
  T1 bus corto <= 47, T2 bus estándar 48-52, T3 bus largo 53-62, T4 bus de alta capacidad >= 63.

Uso:  .venv\\Scripts\\python scripts/preparar_tipologias.py [--csv RUTA] [--salida RUTA]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ_API = Path(__file__).resolve().parents[1]
CSV_POR_OMISION = RAIZ_API.parents[1] / "insumos_sobusa" / "flota_sobusa.csv"
SALIDA_POR_OMISION = RAIZ_API / "app" / "servicios" / "tipologias_flota.json"

RUTAS = {"SILENCIO": "SILENCIO", "KRA. 54 UNINORTE": "CRA 54", "72": "CL 72"}
TIPOLOGIAS = [
    {"codigo": "T1", "nombre": "Bus corto", "capacidad_min": 1, "capacidad_max": 47},
    {"codigo": "T2", "nombre": "Bus estándar", "capacidad_min": 48, "capacidad_max": 52},
    {"codigo": "T3", "nombre": "Bus largo", "capacidad_min": 53, "capacidad_max": 62},
    {"codigo": "T4", "nombre": "Bus de alta capacidad", "capacidad_min": 63, "capacidad_max": 999},
]


def _tipologia(capacidad: float) -> str:
    for t in TIPOLOGIAS:
        if t["capacidad_min"] <= capacidad <= t["capacidad_max"]:
            return t["codigo"]
    raise ValueError(f"Capacidad fuera de rango: {capacidad}")


def construir(csv: Path) -> dict:
    crudo = csv.read_bytes()
    d = pd.read_csv(csv, encoding="utf-8", encoding_errors="replace")
    d = d.rename(columns={"Placa": "placa", "Ruta": "ruta_reporte", "Sentados": "sentados", "Pie": "pie"})
    d["ruta"] = d["ruta_reporte"].astype(str).str.strip().map(RUTAS)
    d = d[d["ruta"].notna()].copy()
    d["sentados"] = pd.to_numeric(d["sentados"], errors="coerce").fillna(0)
    d["pie"] = pd.to_numeric(d["pie"], errors="coerce").fillna(0)
    d["capacidad"] = d["sentados"] + d["pie"]
    d = d[(d["capacidad"] > 0) & ~d["placa"].astype(str).str.upper().str.startswith("XXX")]
    # una placa por ruta (la lista es vehículo-conductor)
    v = (d.groupby(["ruta", "placa"], as_index=False)
         .agg(capacidad=("capacidad", "median"), sentados=("sentados", "median"), pie=("pie", "median")))
    v["tipologia"] = v["capacidad"].map(_tipologia)
    rutas: dict[str, list[dict]] = {}
    for ruta, g in v.groupby("ruta"):
        total = len(g)
        filas = []
        for t in TIPOLOGIAS:
            x = g[g["tipologia"] == t["codigo"]]
            if x.empty:
                continue
            filas.append({
                "codigo": t["codigo"], "nombre": t["nombre"], "vehiculos": int(len(x)),
                "participacion": round(len(x) / total, 4),
                "capacidad": int(round(float(x["capacidad"].median()))),
                "capacidad_min": int(x["capacidad"].min()), "capacidad_max": int(x["capacidad"].max()),
                "sentados": int(round(float(x["sentados"].median()))), "de_pie": int(round(float(x["pie"].median()))),
            })
        rutas[str(ruta)] = filas
    return {
        "fuente": "insumos_sobusa/flota_sobusa.csv (reporte de flota de Sobusa, 2-nov-2026, sin datos personales)",
        "sha256_fuente": hashlib.sha256(crudo).hexdigest(),
        "generado": date.today().isoformat(),
        "generado_por": "scripts/preparar_tipologias.py",
        "criterio": ("capacidad = sentados + de pie; una placa por ruta (mediana de sus filas); filas de relleno y "
                     "capacidad 0 descartadas; la capacidad de cada tipología es la mediana de sus vehículos. "
                     "Las placas no se publican."),
        "tipologias": TIPOLOGIAS,
        "rutas": rutas,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--csv", type=Path, default=CSV_POR_OMISION)
    p.add_argument("--salida", type=Path, default=SALIDA_POR_OMISION)
    a = p.parse_args()
    datos = construir(a.csv)
    a.salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for ruta, filas in datos["rutas"].items():
        resumen = ", ".join(f"{f['codigo']} {f['capacidad']} puestos × {f['vehiculos']}" for f in filas)
        print(f"{ruta}: {sum(f['vehiculos'] for f in filas)} vehículos -> {resumen}")
    print(f"Escrito {a.salida}")


if __name__ == "__main__":
    main()
