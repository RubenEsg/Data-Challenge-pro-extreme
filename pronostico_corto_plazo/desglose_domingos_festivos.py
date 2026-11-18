"""Análisis POSTERIOR a la prueba (no estaba en el protocolo): el error por tipo de día, separando domingos y festivos.

El protocolo declaró el error por tipo de día con tres grupos: laboral, sábado y «domingo o festivo». En ese último
grupo el promedio por día y hora falla muchísimo y el modelo no, pero el grupo mezcla dos cosas distintas: los festivos,
en que el promedio de las ocho semanas anteriores pronostica un día corriente, y los domingos corrientes, en que ese
promedio sí sirve. Este guion los separa para ver dónde gana el modelo y dónde no.

No entrena ni vuelve a pronosticar: lee las predicciones guardadas por ruta (resultados/predicciones_ruta.parquet) y el
calendario (panel/calendario.csv). Un día es «festivo» si el calendario lo marca como festivo, sea cual sea el día de la
semana; si no, es domingo, sábado o laboral. Las cifras de resultados/prueba.json no cambian.

Escribe resultados/desglose_domingos_festivos.json.

Uso (desde esta carpeta):  python desglose_domingos_festivos.py
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

import comun as C

GRUPOS = ("laboral", "sábado", "domingo", "festivo")


def medir(g: pd.DataFrame) -> dict:
    y = g["real"].to_numpy(float)
    m, p = C.metricas(y, g["pronostico"].to_numpy(float)), C.metricas(y, g["promedio_dia_hora"].to_numpy(float))
    return {"celdas": int(len(g)), "dias": int(g["fecha"].nunique()), "modelo": m.get("wape"), "promedio_dia_hora": p.get("wape"),
            "sesgo_del_modelo_pct": m.get("sesgo_pct"), "gana_el_modelo": bool(m.get("wape") < p.get("wape"))}


def main() -> None:
    t = pd.read_parquet(C.RES / "predicciones_ruta.parquet")
    t["fecha"] = pd.to_datetime(t["fecha"])
    cal = pd.read_csv(C.PANEL / "calendario.csv", parse_dates=["fecha"])[["fecha", "festivo"]]
    t = t.merge(cal, on="fecha", how="left", validate="many_to_one")
    dia = t["fecha"].dt.dayofweek
    t["grupo"] = np.select([t["festivo"] == 1, dia == 6, dia == 5], ["festivo", "domingo", "sábado"], "laboral")
    res: dict = {"generado": time.strftime("%Y-%m-%d %H:%M"),
                 "que_es": "análisis posterior a la prueba, no previsto en PROTOCOLO.md; las cifras de resultados/prueba.json no cambian",
                 "grupos": "festivo: el calendario lo marca como festivo (cualquier día de la semana); si no, domingo, sábado o laboral",
                 "nivel": "ruta", "horizontes": {}}
    for h in C.HORIZONTES:
        d = t[t["horizonte_min"] == h]
        bloque = {"todas_las_rutas": {g: medir(d[d["grupo"] == g]) for g in GRUPOS}, "por_ruta": {}}
        for ruta in C.RUTAS.values():
            bloque["por_ruta"][ruta] = {g: medir(d[(d["ruta"] == ruta) & (d["grupo"] == g)]) for g in GRUPOS}
        bloque["grupos_y_rutas_en_que_no_gana"] = [f"{ruta} · {g}" for ruta, x in bloque["por_ruta"].items() for g, v in x.items()
                                                   if not v["gana_el_modelo"]]
        res["horizontes"][str(h)] = bloque
        fila = bloque["todas_las_rutas"]
        print(f"h={h:3d}: " + " · ".join(f"{g} {fila[g]['modelo']:.2f} / {fila[g]['promedio_dia_hora']:.2f}" for g in GRUPOS)
              + f" · no gana en: {bloque['grupos_y_rutas_en_que_no_gana']}")
    (C.RES / "desglose_domingos_festivos.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
