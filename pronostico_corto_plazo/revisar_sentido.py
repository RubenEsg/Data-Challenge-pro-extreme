"""¿Qué tan fiable es el sentido (y el segmento) que da la regla del segmento más cercano?

La geometría de cada ruta es el ciclo completo y la regla de Extreme asigna cada subida al segmento más cercano, sin
mirar en qué parte del viaje va el bus. Donde la ida y el regreso pasan por la misma calle, la regla puede dejar la
subida en el sentido contrario. Este guion lo mide de dos maneras, con las exportaciones del proyecto:

1. Geometría: qué parte del recorrido de regreso tiene la ida a menos de 30 metros.
2. Tiempo de viaje: para cada subida, los minutos que lleva el viaje frente a los minutos típicos de su segmento
   (panel/segmentos.csv). Una subida asignada al sentido contrario queda lejos de ese tiempo: se cuenta cuántas quedan
   a más de 45 minutos y cuántas de esas caerían bien en un segmento del otro sentido a menos de 30 metros.

Escribe panel/revision_sentido.json. Usa una muestra de tramos de eventos repartidos en los tres años.
Uso (desde la raíz del proyecto):  python EntregaFinal/pronostico_corto_plazo/revisar_sentido.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import preparar_panel as P  # noqa: E402

CERCA_M = 30
LEJOS_MIN = 45
GRADO_M = 111_000


def main() -> None:
    seg, arboles = P.leer_segmentos()
    seg = seg.merge(pd.read_csv(P.PANEL / "segmentos.csv")[["idruta", "nro_segmento", "minutos_desde_inicio"]],
                    on=["idruta", "nro_segmento"])
    out: dict = {"cerca_m": CERCA_M, "lejos_min": LEJOS_MIN, "geometria": {}, "tiempo_de_viaje": {}}
    otro = {}
    for idruta, (arbol, de, x, y) in arboles.items():
        s = seg[seg["idruta"] == idruta].set_index("nro_segmento")
        regreso = (s["sentido"] == "regreso").reindex(de).to_numpy()
        ida = cKDTree(np.c_[x[~regreso], y[~regreso]])
        d, _ = ida.query(np.c_[x[regreso], y[regreso]], k=1, workers=-1)
        out["geometria"][P.RUTAS[idruta]] = {
            "km_regreso": round(float(regreso.sum() * 0.2 / 1000), 1),
            "regreso_con_la_ida_a_menos_de_30_m_pct": round(float((d * GRADO_M < CERCA_M).mean() * 100), 1)}
        otro[idruta] = (cKDTree(np.c_[x[~regreso], y[~regreso]]), de[~regreso], cKDTree(np.c_[x[regreso], y[regreso]]), de[regreso])

    pv = pd.read_parquet(P.DATOS / "progvehiculos.parquet", columns=["idprogramacion", "idruta", "fechainicio"])
    pv = pv[pv["idruta"].isin(P.RUTAS)]
    ruta_de = pv.set_index("idprogramacion")["idruta"]
    inicio_de = (pv.set_index("idprogramacion")["fechainicio"] - pd.Timestamp("1970-01-01")).dt.total_seconds()
    archivos = sorted((P.DATOS / "eventos_subida").glob("eventos_*.parquet"))[::10]      # 1 de cada 10 tramos
    partes = []
    for f in archivos:
        ev = pd.read_parquet(f)
        ev["idruta"] = ev["idprogramacion"].map(ruta_de)
        ev = ev[ev["idruta"].notna()].astype({"idruta": int})
        ev = P.asignar(ev, arboles)
        ev["minutos"] = (ev["t"] - ev["idprogramacion"].map(inicio_de)) / 60
        partes.append(ev[ev["minutos"].between(0, P.MIN_MAX)])
    ev = pd.concat(partes, ignore_index=True)
    ev = ev.merge(seg[["idruta", "nro_segmento", "sentido", "minutos_desde_inicio"]], on=["idruta", "nro_segmento"])
    ev["desfase"] = ev["minutos"] - ev["minutos_desde_inicio"]
    out["muestra"] = {"tramos": len(archivos), "subidas": int(ev["subidas"].sum())}
    for idruta, g in ev.groupby("idruta"):
        peso = g["subidas"].to_numpy()
        lejos = (g["desfase"].abs() > LEJOS_MIN).to_numpy()
        # de las que quedan lejos: ¿hay un segmento del OTRO sentido a menos de 30 m cuyo tiempo típico sí cuadra?
        a_ida, de_ida, a_reg, de_reg = otro[idruta]
        s = seg[seg["idruta"] == idruta].set_index("nro_segmento")["minutos_desde_inicio"]
        gl = g[lejos]
        es_ida = (gl["sentido"] == "ida").to_numpy()
        cuadra = np.zeros(len(gl), bool)
        for mascara, arbol, de in ((es_ida, a_reg, de_reg), (~es_ida, a_ida, de_ida)):
            if mascara.any():
                d, idx = arbol.query(np.c_[gl.loc[mascara, "lon"], gl.loc[mascara, "lat"]], k=1, workers=-1)
                minutos_otro = s.reindex(de[idx]).to_numpy()
                cuadra[mascara] = (d * GRADO_M < CERCA_M) & (np.abs(gl.loc[mascara, "minutos"].to_numpy() - minutos_otro) <= LEJOS_MIN)
        out["tiempo_de_viaje"][P.RUTAS[int(idruta)]] = {
            "subidas_a_menos_de_15_min_de_lo_tipico_pct": round(float(peso[(g["desfase"].abs() <= 15).to_numpy()].sum() / peso.sum() * 100), 1),
            "subidas_a_menos_de_45_min_pct": round(float(peso[~lejos].sum() / peso.sum() * 100), 1),
            "subidas_a_mas_de_45_min_pct": round(float(peso[lejos].sum() / peso.sum() * 100), 1),
            "de_ellas_cuadran_en_el_otro_sentido_pct_del_total": round(float(gl["subidas"].to_numpy()[cuadra].sum() / peso.sum() * 100), 1)}
    (P.PANEL / "revision_sentido.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
