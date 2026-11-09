"""Reparto histórico de la demanda de cada ruta por segmento y sentido (§9.1 «ruta, sentido, segmento», §9.3 sesgo).

Fuente: las exportaciones del proyecto (carpeta datos/ de la raíz; nada se consulta a la base del reto):
timbradas_segmentos (subidas por segmento y viaje, 2023-01-01 a 2023-02-27, lo único que llenaron los triggers de
segmentación), rutas_segmentos (idruta, idrutageo, nro_segmento, longitud_m) y progvehiculos (hora de salida del viaje,
la misma «hora» del pronóstico por ruta).

Reparto: fracción de las subidas de la ruta en cada segmento por (ruta, tipo de día, hora de salida), con respaldo
(ruta, tipo de día) y (ruta) cuando la celda tiene menos de MIN_SUBIDAS. Suma 1 en cada celda, así que la suma de los
segmentos es exactamente el pronóstico de la ruta.

Sentido: las exportaciones NO traen columna de sentido y la geometría de cada ruta (idrutageo, compartida por varias
variantes de ruta) es el ciclo completo. Se aproxima: «ida» = segmentos cuyo punto medio cae en la primera mitad de la
longitud acumulada del ciclo, «regreso» = el resto. Es una aproximación declarada, no un dato de Extreme.

Evaluación (sin fuga): reparto con enero de 2023 aplicado al total real de cada ruta-hora de febrero de 2023 (el error
es solo del reparto, con el total de la ruta perfecto): WAPE y sesgo por segmento, por sentido y por ruta.

Salidas: datos/reparto_segmentos.parquet (lo usa GET /api/v1/predictions/segmentos) y
docs/evidencias/monitoreo/desagregacion_segmentos.json.

Uso:  python scripts/preparar_segmentos.py [--origen ../../datos] [--salida datos/reparto_segmentos.parquet]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
MIN_SUBIDAS = 200
CORTE_EVAL = date(2023, 2, 1)


def cargar(origen: Path) -> pd.DataFrame:
    from app.servicios import datos

    cat = {int(r["idruta"]): r["ruta"] for r in datos.catalogo_rutas()}
    ts = pd.read_parquet(origen / "timbradas_segmentos.parquet",
                         columns=["id_segmento", "id_viaje", "fecha", "subidas"])
    rs = pd.read_parquet(origen / "rutas_segmentos.parquet",
                         columns=["id", "idruta", "idrutageo", "nro_segmento", "longitud_m"])
    pv = pd.read_parquet(origen / "progvehiculos.parquet", columns=["idprogramacion", "fechasalida"])
    rs = rs[rs["idruta"].isin(cat)]
    d = ts.merge(rs, left_on="id_segmento", right_on="id", how="inner")
    d = d.merge(pv, left_on="id_viaje", right_on="idprogramacion", how="left")
    d["ruta"] = d["idruta"].map(cat)
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    salida = pd.to_datetime(d["fechasalida"])
    d["hora"] = salida.dt.hour
    d = d[d["hora"].between(4, 20)]
    festivos = set(datos.demanda_horaria().query("festivo == 1")["fecha"])
    d["tipo_dia"] = [datos.tipo_dia_de(f, f in festivos) for f in d["fecha"]]
    return d


def sentidos(rs: pd.DataFrame) -> pd.DataFrame:
    """ida / regreso por la mitad de la longitud acumulada del ciclo (aproximación declarada)."""
    out = []
    for ruta, g in rs.sort_values(["ruta", "nro_segmento"]).groupby("ruta"):
        acum = g["longitud_m"].cumsum()
        medio = acum - g["longitud_m"] / 2
        total = g["longitud_m"].sum()
        out.append(g.assign(sentido=np.where(medio <= total / 2, "ida", "regreso"),
                            km_inicio=(acum - g["longitud_m"]) / 1000, ruta=ruta))
    return pd.concat(out, ignore_index=True)


def fracciones(d: pd.DataFrame) -> pd.DataFrame:
    """Fracción por (ruta, tipo_dia, hora, segmento) con respaldo jerárquico; suma 1 por (ruta, tipo_dia, hora)."""
    segs = d[["ruta", "id_segmento", "nro_segmento"]].drop_duplicates()
    celdas = d[["ruta", "tipo_dia", "hora"]].drop_duplicates()
    base = celdas.merge(segs, on="ruta")
    n3 = d.groupby(["ruta", "tipo_dia", "hora", "id_segmento"])["subidas"].sum().rename("s3")
    t3 = d.groupby(["ruta", "tipo_dia", "hora"])["subidas"].sum().rename("t3")
    n2 = d.groupby(["ruta", "tipo_dia", "id_segmento"])["subidas"].sum().rename("s2")
    t2 = d.groupby(["ruta", "tipo_dia"])["subidas"].sum().rename("t2")
    n1 = d.groupby(["ruta", "id_segmento"])["subidas"].sum().rename("s1")
    t1 = d.groupby(["ruta"])["subidas"].sum().rename("t1")
    b = (base.join(n3, on=["ruta", "tipo_dia", "hora", "id_segmento"]).join(t3, on=["ruta", "tipo_dia", "hora"])
         .join(n2, on=["ruta", "tipo_dia", "id_segmento"]).join(t2, on=["ruta", "tipo_dia"])
         .join(n1, on=["ruta", "id_segmento"]).join(t1, on="ruta")).fillna({"s3": 0, "s2": 0, "s1": 0})
    nivel = np.where(b["t3"] >= MIN_SUBIDAS, "ruta_tipo_dia_hora",
                     np.where(b["t2"] >= MIN_SUBIDAS, "ruta_tipo_dia", "ruta"))
    frac = np.where(nivel == "ruta_tipo_dia_hora", b["s3"] / b["t3"],
                    np.where(nivel == "ruta_tipo_dia", b["s2"] / b["t2"], b["s1"] / b["t1"]))
    b["fraccion"] = frac
    b["nivel"] = nivel
    b["fraccion"] = b["fraccion"] / b.groupby(["ruta", "tipo_dia", "hora"])["fraccion"].transform("sum")
    b["subidas_celda"] = b["t3"].fillna(0).astype(int)
    return b[["ruta", "tipo_dia", "hora", "id_segmento", "nro_segmento", "fraccion", "nivel", "subidas_celda"]]


def _wape(y, p) -> float | None:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return None if y.sum() <= 0 else round(float(np.abs(p - y).sum() / y.sum() * 100), 2)


def _sesgo(y, p) -> float | None:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return None if y.sum() <= 0 else round(float((p - y).sum() / y.sum() * 100), 2)


def evaluar(d: pd.DataFrame, rs: pd.DataFrame) -> dict:
    ent, pru = d[d["fecha"] < CORTE_EVAL], d[d["fecha"] >= CORTE_EVAL]
    fr = fracciones(ent)
    real = pru.groupby(["ruta", "fecha", "tipo_dia", "hora", "id_segmento"])["subidas"].sum().rename("y").reset_index()
    tot = pru.groupby(["ruta", "fecha", "tipo_dia", "hora"])["subidas"].sum().rename("total").reset_index()
    malla = tot.merge(fr, on=["ruta", "tipo_dia", "hora"], how="left")
    malla = malla.merge(real, on=["ruta", "fecha", "tipo_dia", "hora", "id_segmento"], how="left").fillna({"y": 0})
    malla["p"] = malla["total"] * malla["fraccion"].fillna(0)
    malla = malla.merge(rs[["id_segmento", "sentido"]], on="id_segmento", how="left")
    por_seg = malla.groupby(["ruta", "nro_segmento", "sentido"]).apply(
        lambda g: pd.Series({"y": g["y"].sum(), "wape": _wape(g["y"], g["p"]), "sesgo_pct": _sesgo(g["y"], g["p"])}),
        include_groups=False).reset_index()
    por_sentido = malla.groupby(["ruta", "sentido"]).apply(
        lambda g: pd.Series({"wape_segmento_hora": _wape(g["y"], g["p"]), "sesgo_pct": _sesgo(g["y"], g["p"]),
                             "subidas": int(g["y"].sum())}), include_groups=False).reset_index()
    sent = malla.groupby(["ruta", "fecha", "hora", "sentido"])[["y", "p"]].sum().reset_index()
    por_ruta = {}
    for ruta, g in malla.groupby("ruta"):
        s = sent[sent["ruta"] == ruta]
        ps = por_seg[por_seg["ruta"] == ruta]
        grandes = ps[ps["y"] >= ps["y"].quantile(0.5)]
        por_ruta[ruta] = {
            "wape_segmento_hora": _wape(g["y"], g["p"]),
            "wape_sentido_hora": _wape(s["y"], s["p"]),
            "segmentos": int(ps["nro_segmento"].nunique()),
            "sesgo_abs_mediano_segmentos_pct": round(float(ps["sesgo_pct"].abs().median()), 2),
            "sesgo_abs_p90_segmentos_pct": round(float(ps["sesgo_pct"].abs().quantile(0.9)), 2),
            "sesgo_abs_mediano_mitad_con_mas_subidas_pct": round(float(grandes["sesgo_pct"].abs().median()), 2),
            "peores_segmentos_por_sesgo": ps.reindex(ps["sesgo_pct"].abs().sort_values(ascending=False).index)
            .head(5)[["nro_segmento", "sentido", "y", "sesgo_pct"]].to_dict("records"),
        }
    return {"entrenamiento": f"{ent['fecha'].min()} a {ent['fecha'].max()}",
            "prueba": f"{pru['fecha'].min()} a {pru['fecha'].max()}",
            "metodo": "fracciones de enero aplicadas al total REAL de cada ruta-hora de febrero "
                      "(error solo del reparto)",
            "global": {"wape_segmento_hora": _wape(malla["y"], malla["p"]), "subidas_prueba": int(malla["y"].sum()),
                       "suma_reparto_igual_total": bool(np.allclose(
                           malla.groupby(["ruta", "fecha", "hora"])["p"].sum().to_numpy(),
                           malla.groupby(["ruta", "fecha", "hora"])["total"].first().to_numpy()))},
            "por_ruta": por_ruta, "por_sentido": por_sentido.to_dict("records")}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--origen", type=Path, default=RAIZ.parents[1] / "datos")
    p.add_argument("--salida", type=Path, default=RAIZ / "datos" / "reparto_segmentos.parquet")
    p.add_argument("--evidencia", type=Path,
                   default=RAIZ / "docs" / "evidencias" / "monitoreo" / "desagregacion_segmentos.json")
    a = p.parse_args()
    d = cargar(a.origen)
    rs = sentidos(d[["ruta", "idruta", "idrutageo", "id_segmento", "nro_segmento", "longitud_m"]]
                  .drop_duplicates("id_segmento"))
    ev = evaluar(d, rs)
    fr = fracciones(d).merge(rs[["id_segmento", "idruta", "idrutageo", "sentido", "longitud_m", "km_inicio"]],
                             on="id_segmento", how="left")
    fr["periodo"] = f"{d['fecha'].min()} a {d['fecha'].max()}"
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    fr.to_parquet(a.salida, index=False)
    ev.update({"filas_reparto": int(len(fr)), "periodo_reparto": fr["periodo"].iloc[0],
               "subidas_usadas": int(d["subidas"].sum()), "viajes": int(d["id_viaje"].nunique()),
               "segmentos_por_ruta": d.groupby("ruta")["id_segmento"].nunique().to_dict(),
               "sentido": "aproximado: mitad de la longitud acumulada del ciclo (las exportaciones no traen sentido)",
               "limitaciones": [
                   "timbradas_segmentos solo cubre 2023-01-01 a 2023-02-27 (los triggers de segmentación no se han "
                   "vuelto a ejecutar): el reparto es de hace casi tres años y no ve cambios de ruta posteriores",
                   "ene-feb incluye vacaciones y el inicio del año escolar; no hay Semana Santa ni diciembre",
                   "no hay modelo por segmento: es una desagregación del pronóstico de la ruta",
                   "el sentido es una aproximación geométrica, no un campo de Extreme"]})
    a.evidencia.parent.mkdir(parents=True, exist_ok=True)
    a.evidencia.write_text(json.dumps(ev, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: ev[k] for k in ("global", "filas_reparto", "segmentos_por_ruta")}, ensure_ascii=False,
                     default=str))
    for ruta, r in ev["por_ruta"].items():
        print(ruta, {k: r[k] for k in ("wape_segmento_hora", "wape_sentido_hora", "sesgo_abs_mediano_segmentos_pct")})


if __name__ == "__main__":
    main()
