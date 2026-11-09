"""Evaluación sin fuga de los horizontes de 30, 60 y 120 minutos (RF-005, §9.3).

Protocolo (origen móvil):
- Modelo fv2 congelado con datos <= 2024-12-31 (semilla 42, hiperparámetros por defecto).
- Peso del factor intradía (nowcast) calibrado en ene-feb 2025 con inferencia.calibrar_nowcast; evaluación mar-dic 2025.
- Un origen en cada h:00 (h = 6..20): el factor usa solo las horas cerradas h-2 y h-1 (observado / esperado).
  - 60 min: objetivo = pasajeros de la hora h.
  - 120 min: objetivo = horas h y h+1 (h = 6..19).
  - 30 min: objetivo = pasajeros de la hora h x fracción OBSERVADA de subidas de los viajes que salen entre h:00 y
    h:29 ese día (conteo_viajes + progvehiculos de 2025). Es una aproximación: las exportaciones no traen el conteo
    crudo por minuto. El pronóstico reparte la hora con 0,5 (prorrateo anterior) o con el perfil intrahorario de 2024
    (datos/perfil_intrahorario.parquet, sin datos de 2025: no hay fuga).
- B1 (regla manual de 8 semanas) con el mismo reparto, como referencia.

Uso: python scripts/evaluar_horizontes.py [--raiz-proyecto RUTA] [--salida docs/evidencias/modelo]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import datos, inferencia, variables  # noqa: E402


def wape(y, p) -> float | None:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return round(float(np.abs(p - y).sum() / y.sum() * 100), 2) if len(y) and y.sum() > 0 else None


def fraccion_observada(raiz: Path, ids: dict[int, str], anio: int = 2025) -> pd.DataFrame:
    d = raiz / "datos"
    pv = pd.read_parquet(d / "progvehiculos.parquet", columns=["idprogramacion", "idruta", "fechasalida", "cancelada"])
    pv = pv[pv["idruta"].isin(list(ids))]
    pv["fechasalida"] = pd.to_datetime(pv["fechasalida"])
    pv = pv[(pv["fechasalida"] >= f"{anio}-01-01") & (pv["fechasalida"] < f"{anio + 1}-01-01")]
    pv = pv[pv["cancelada"].astype(str).str.upper().ne("S")]
    cv = pd.read_parquet(d / "conteo_viajes.parquet", columns=["idprogramacion", "subidas"])
    v = pv.merge(cv, on="idprogramacion")
    v["ruta"] = v["idruta"].map(ids)
    v["fecha"] = v["fechasalida"].dt.date
    v["hora"] = v["fechasalida"].dt.hour
    v["s1"] = np.where(v["fechasalida"].dt.minute < 30, v["subidas"], 0.0)
    hh = v.groupby(["ruta", "fecha", "hora"], as_index=False).agg(s1=("s1", "sum"), s=("subidas", "sum"))
    hh = hh[hh["s"] > 0]
    hh["fraccion_obs"] = hh["s1"] / hh["s"]
    return hh[["ruta", "fecha", "hora", "fraccion_obs"]]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Evaluación de horizontes 30/60/120 min sin fuga")
    ap.add_argument("--raiz-proyecto", type=Path, default=RAIZ.parents[1])
    ap.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "modelo")
    a = ap.parse_args()
    t0 = time.perf_counter()
    version = variables.FV2
    t = inferencia._filas_utiles(inferencia.tabla_variables()).reset_index(drop=True)
    corte, ini_ev, fin = date(2024, 12, 31), date(2025, 3, 1), date(2025, 12, 31)
    tr = t[t["fecha"] <= corte]
    ev = t[(t["fecha"] > corte) & (t["fecha"] <= fin)].copy()
    hp = dict(inferencia.HIPER_DEFECTO)
    punto = inferencia._modelo_hgb("poisson", 42, hp, version=version).fit(
        variables.matriz_x(tr, version), tr["pasajeros"].to_numpy(float)
    )
    ev["p"] = np.clip(punto.predict(variables.matriz_x(ev, version)), 0, None)
    cal = inferencia.calibrar_nowcast(ev[ev["fecha"] < ini_ev], ev.loc[ev["fecha"] < ini_ev, "p"].to_numpy())
    peso = float(cal["peso"])

    e = ev[ev["fecha"] >= ini_ev][["ruta", "fecha", "hora", "pasajeros", "p", "b8", "tipo_dia"]].rename(
        columns={"pasajeros": "y", "b8": "b1"}
    )
    k = e[["ruta", "fecha", "hora", "y", "p", "b1"]]
    a1 = e.merge(k.assign(hora=k["hora"] + 1), on=["ruta", "fecha", "hora"], how="left", suffixes=("", "_m1"))
    a1 = a1.merge(k.assign(hora=k["hora"] + 2), on=["ruta", "fecha", "hora"], how="left", suffixes=("", "_m2"))
    a1 = a1.merge(k.assign(hora=k["hora"] - 1), on=["ruta", "fecha", "hora"], how="left", suffixes=("", "_s1"))
    obs, esp = a1["y_m1"] + a1["y_m2"], a1["p_m1"] + a1["p_m2"]
    ok = (obs.notna() & (esp >= inferencia.NOWCAST_MIN_ESPERADOS)).to_numpy()
    razon = np.where(ok, obs / esp.where(esp > 0, 1.0), 1.0)
    factor = {
        w: np.where(ok, np.clip(1 + w * (razon - 1), inferencia.NOWCAST_MIN, inferencia.NOWCAST_MAX), 1.0)
        for w in sorted({0.0, peso, 1.0})
    }
    f = factor[peso]
    v60 = a1["hora"].between(6, 20).to_numpy()
    v120 = (a1["hora"].between(6, 19) & a1["y_s1"].notna()).to_numpy()
    res: dict = {
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocolo": __doc__.strip().splitlines()[2:12],
        "modelo": f"fv2 congelado <= {corte} (semilla 42)",
        "peso_nowcast_calibrado_ene_feb_2025": peso,
        "calibracion_wape_por_peso": cal["wape_por_peso"],
        "evaluado": f"{ini_ev} a {fin}",
    }
    y60 = a1.loc[v60, "y"]
    res["h60"] = {
        "n": int(v60.sum()),
        "modelo_sin_ajuste": wape(y60, a1.loc[v60, "p"]),
        "modelo_con_nowcast": wape(y60, (a1["p"] * f)[v60]),
        "modelo_nowcast_peso_1": wape(y60, (a1["p"] * factor[1.0])[v60]),
        "b1": wape(y60, a1.loc[v60, "b1"]),
    }
    y120 = (a1["y"] + a1["y_s1"])[v120]
    p120 = (a1["p"] + a1["p_s1"])[v120]
    res["h120"] = {
        "n": int(v120.sum()),
        "modelo_sin_ajuste": wape(y120, p120),
        "modelo_con_nowcast": wape(y120, (p120 * f[v120])),
        "b1": wape(y120, (a1["b1"] + a1["b1_s1"])[v120]),
    }
    try:
        ids = {int(c["idruta"]): c["ruta"] for c in datos.catalogo_rutas()}
        fo = fraccion_observada(a.raiz_proyecto, ids)
        perfil = inferencia.perfil_intrahorario()
        b = a1[v60].merge(fo, on=["ruta", "fecha", "hora"], how="inner")
        b["fr_perfil"] = [
            perfil.get((r, int(td), int(h)), 0.5) for r, td, h in zip(b["ruta"], b["tipo_dia"], b["hora"], strict=False)
        ]
        fb = np.where(
            (b["y_m1"] + b["y_m2"]).notna() & ((b["p_m1"] + b["p_m2"]) >= inferencia.NOWCAST_MIN_ESPERADOS),
            np.clip(
                1
                + peso
                * ((b["y_m1"] + b["y_m2"]) / (b["p_m1"] + b["p_m2"]).where((b["p_m1"] + b["p_m2"]) > 0, 1.0) - 1),
                inferencia.NOWCAST_MIN,
                inferencia.NOWCAST_MAX,
            ),
            1.0,
        )
        y30 = b["y"] * b["fraccion_obs"]
        res["h30"] = {
            "n": int(len(b)),
            "fraccion_observada_media": round(float(b["fraccion_obs"].mean()), 4),
            "fraccion_perfil_media": round(float(b["fr_perfil"].mean()), 4),
            "modelo_sin_ajuste_prorrateo_0_5": wape(y30, b["p"] * 0.5),
            "modelo_con_nowcast_prorrateo_0_5": wape(y30, b["p"] * 0.5 * fb),
            "modelo_sin_ajuste_perfil": wape(y30, b["p"] * b["fr_perfil"]),
            "modelo_con_nowcast_perfil": wape(y30, b["p"] * b["fr_perfil"] * fb),
            "b1_prorrateo_0_5": wape(y30, b["b1"] * 0.5),
            "b1_perfil": wape(y30, b["b1"] * b["fr_perfil"]),
            "nota": "observado de 30 min = pasajeros de la hora x fracción observada de subidas de los viajes que "
            "salen entre h:00 y h:29 (aproximación: no hay conteo crudo por minuto en las exportaciones)",
        }
    except FileNotFoundError as exc:
        res["h30"] = {"omitido": f"faltan las exportaciones de viajes del proyecto: {exc}"}
    res["segundos"] = round(time.perf_counter() - t0, 1)
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "horizontes.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in res.items() if k.startswith("h") or k.startswith("peso")}, ensure_ascii=False, indent=1
        )
    )


if __name__ == "__main__":
    main()
