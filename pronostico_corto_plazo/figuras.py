"""Figuras del pronóstico de corto plazo, a partir de resultados/ (no entrena nada). PNG para el README y el cuaderno y
PDF para el informe, con el estilo de informe/figuras_extra.py (azul = modelo, gris = referencia).

  fig_cp_niveles       WAPE del modelo y del promedio por día y hora, por nivel y horizonte, con su IC95
  fig_cp_dia           un día de la prueba: real, pronóstico a 60 minutos con su banda P10-P90 y promedio por día y hora
  fig_cp_instante      WAPE a 60 minutos según la hora del día
  fig_cp_segmentos     subidas reales y pronosticadas por segmento a lo largo de cada ruta (60 minutos)
  fig_cp_informacion   cuánto aporta lo observado en el día y cuánto cuesta que la captura llegue tarde

Uso (desde esta carpeta):  python figuras.py
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import comun as C

FIG = C.AQUI / "figuras"
plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Latin Modern Sans", "DejaVu Sans"], "font.size": 10,
    "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 9, "legend.fontsize": 9, "lines.linewidth": 2.0,
    "axes.grid": True, "grid.alpha": 0.3, "pdf.fonttype": 42, "savefig.bbox": "tight", "axes.spines.top": False,
    "axes.spines.right": False, "axes.titlesize": 10, "legend.frameon": False,
})
NAVY, GRIS, TINTA = "#1F3A5F", "#9A9A9A", "#222222"
AZULES = ["#1F3A5F", "#5B7BA6", "#9DB3D0"]          # misma familia, de oscuro a claro: sin retraso, 15 y 30 minutos
NOMBRE_NIVEL = {"ruta": "Por ruta", "sentido": "Por sentido", "segmento": "Por segmento"}


def num(x: float, dec: int = 1) -> str:
    return f"{x:,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def guardar(fig, nombre: str) -> None:
    FIG.mkdir(exist_ok=True)
    fig.savefig(FIG / f"{nombre}.png", dpi=160)
    fig.savefig(FIG / f"{nombre}.pdf")
    plt.close(fig)
    print("figura", nombre)


def hora_de(instante) -> str:
    return f"{int(instante) // 4:02d}:{(int(instante) % 4) * 15:02d}"


def fig_niveles(res: dict) -> None:
    fig, ejes = plt.subplots(1, 3, figsize=(7.4, 2.9))
    x = np.arange(3)
    for eje, nivel in zip(ejes, C.NIVELES, strict=True):
        for j, (clave, color, nombre) in enumerate((("promedio_dia_hora", GRIS, "Promedio por día y hora"), ("modelo", NAVY, "Modelo"))):
            w, lo, hi = [], [], []
            for h in C.HORIZONTES:
                b = res["niveles"][nivel][str(h)]["todas_las_rutas"]
                w.append(b[clave]["wape"])
                ic = b["ic95"][clave]["ic95"]
                lo.append(b[clave]["wape"] - ic[0]), hi.append(ic[1] - b[clave]["wape"])
            pos = x + (j - 0.5) * 0.36
            eje.bar(pos, w, 0.32, color=color, label=nombre)
            eje.errorbar(pos, w, yerr=[lo, hi], fmt="none", ecolor=TINTA, elinewidth=0.9, capsize=2)
            for xi, wi, hi_i in zip(pos, w, hi, strict=True):
                eje.text(xi, wi + hi_i + max(w) * 0.02, num(wi), ha="center", va="bottom", fontsize=8, color=TINTA)
        eje.set_xticks(x, [f"{h} min" for h in C.HORIZONTES])
        eje.set_title(NOMBRE_NIVEL[nivel], loc="left")
        eje.set_ylim(0, eje.get_ylim()[1] * 1.12)       # aire para los rótulos de las barras más altas
        eje.grid(axis="x", visible=False)
    ejes[0].set_ylabel("WAPE (%)")
    ejes[0].legend(loc="upper center", bbox_to_anchor=(1.7, -0.14), ncol=2)
    guardar(fig, "fig_cp_niveles")


def fig_dia(pr: pd.DataFrame) -> dict:
    """Día laboral de la prueba con el WAPE mediano del modelo en CRA 54 a 60 minutos (regla fija, para no elegir a ojo)."""
    d = pr[(pr["ruta"] == "CRA 54") & (pr["horizonte_min"] == 60)].copy()
    d["fecha"] = pd.to_datetime(d["fecha"])
    lab = d[d["fecha"].dt.dayofweek < 5]
    por_dia = lab.groupby("fecha").apply(lambda g: np.abs(g["pronostico"] - g["real"]).sum() / g["real"].sum() * 100, include_groups=False)
    dia = (por_dia - por_dia.median()).abs().idxmin()
    g = d[d["fecha"] == dia].sort_values("instante")
    t = g["instante"].to_numpy() / 4
    fig, eje = plt.subplots(figsize=(7.0, 3.0))
    eje.fill_between(t, g["p10"], g["p90"], color=NAVY, alpha=0.15, lw=0, label="Banda P10–P90")
    eje.plot(t, g["promedio_dia_hora"], color=GRIS, ls="--", lw=1.6, label="Promedio por día y hora")
    eje.plot(t, g["pronostico"], color=NAVY, label="Pronóstico a 60 minutos")
    eje.plot(t, g["real"], color=TINTA, lw=1.2, marker="o", ms=3, label="Lo que subió")
    eje.set_xticks(range(4, 23, 2), [f"{h}:00" for h in range(4, 23, 2)])
    eje.set_xlabel("Instante del pronóstico")
    eje.set_ylabel("Subidas en los 60 minutos siguientes")
    eje.set_ylim(0, None)
    eje.legend(ncol=2, loc="lower center", fontsize=8)
    guardar(fig, "fig_cp_dia")
    return {"fecha": str(dia.date()), "wape_modelo": round(float(por_dia[dia]), 2), "wape_mediano": round(float(por_dia.median()), 2),
            "wape_promedio_ese_dia": round(float(np.abs(g["promedio_dia_hora"] - g["real"]).sum() / g["real"].sum() * 100), 2)}


def fig_instante(pr: pd.DataFrame) -> None:
    d = pr[pr["horizonte_min"] == 60]
    filas = []
    for inst, g in d.groupby("instante"):
        filas.append((inst / 4, np.abs(g["pronostico"] - g["real"]).sum() / g["real"].sum() * 100,
                      np.abs(g["promedio_dia_hora"] - g["real"]).sum() / g["real"].sum() * 100))
    t, m, b = (np.array(v) for v in zip(*filas, strict=True))
    fig, eje = plt.subplots(figsize=(7.0, 2.8))
    eje.plot(t, b, color=GRIS, label="Promedio por día y hora")
    eje.plot(t, m, color=NAVY, label="Modelo")
    eje.set_xticks(range(4, 22, 2), [f"{h}:00" for h in range(4, 22, 2)])
    eje.set_xlabel("Instante del pronóstico")
    eje.set_ylabel("WAPE a 60 minutos (%)")
    eje.set_ylim(0, None)
    eje.legend(loc="upper center", ncol=2)
    guardar(fig, "fig_cp_instante")


def fig_segmentos(seg: pd.DataFrame) -> None:
    d = seg[seg["horizonte_min"] == 60]
    rutas = list(C.RUTAS.values())
    fig, ejes = plt.subplots(3, 1, figsize=(7.2, 6.0))
    for eje, ruta in zip(ejes, rutas, strict=True):
        g = d[d["ruta"] == ruta].sort_values("nro_segmento")
        dias = max(g["celdas"].max() / len(C.INSTANTES), 1)
        km = g["km_inicio"].to_numpy() + 0.25
        eje.bar(km, g["subidas_reales"] / g["celdas"].clip(lower=1), 0.42, color=GRIS, label="Lo que subió")
        eje.plot(km, g["subidas_pronosticadas"] / g["celdas"].clip(lower=1), color=NAVY, lw=1.4, label="Pronóstico")
        corte = g.loc[g["sentido"] == "regreso", "km_inicio"].min()
        eje.axvline(corte, color=TINTA, lw=0.8, ls=":")
        tope = eje.get_ylim()[1]
        eje.text(corte / 2, tope * 0.93, "ida", ha="center", fontsize=8, color=TINTA)
        eje.text(corte + (km.max() - corte) / 2, tope * 0.93, "regreso", ha="center", fontsize=8, color=TINTA)
        eje.set_title(f"{ruta} · {len(g)} segmentos de 500 m · {int(round(dias))} días", loc="left")
        eje.set_ylabel("Subidas por\nventana de 60 min")
        eje.grid(axis="x", visible=False)
    ejes[-1].set_xlabel("Kilómetro del recorrido")
    ejes[0].legend(loc="upper right", ncol=2, fontsize=8, bbox_to_anchor=(1.0, 1.32))
    fig.tight_layout()
    guardar(fig, "fig_cp_segmentos")


def fig_informacion(res: dict) -> None:
    sec = res["secundarios"]
    hs = list(C.HORIZONTES)
    fig, eje = plt.subplots(figsize=(5.6, 3.0))
    base = [res["niveles"]["ruta"][str(h)]["todas_las_rutas"]["promedio_dia_hora"]["wape"] for h in hs]
    eje.plot(hs, base, color=GRIS, ls="--", marker="o", ms=4, label="Promedio por día y hora")
    eje.plot(hs, [sec["informacion_del_dia"][str(h)]["semanal"]["wape"] for h in hs], color=GRIS, marker="o", ms=4,
             label="Modelo con lo que se sabe 7 días antes")
    for lat, color, nombre in ((30, AZULES[2], "… con 30 min de retraso"), (15, AZULES[1], "… con 15 min de retraso"),
                               (0, AZULES[0], "Modelo con lo observado hasta el instante")):
        valores = [sec["retraso_de_la_captura"][str(h)].get(str(lat)) for h in hs]
        if all(v is not None for v in valores):
            eje.plot(hs, valores, color=color, marker="o", ms=4, label=nombre)
    eje.set_xticks(hs, [f"{h} min" for h in hs])
    eje.set_xlabel("Horizonte del pronóstico")
    eje.set_ylabel("WAPE por ruta (%)")
    eje.set_ylim(0, None)
    manijas, rotulos = eje.get_legend_handles_labels()
    eje.legend(manijas[::-1], rotulos[::-1], loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
    guardar(fig, "fig_cp_informacion")


def main() -> None:
    res = json.loads((C.RES / "prueba.json").read_text(encoding="utf-8"))
    pr = pd.read_parquet(C.RES / "predicciones_ruta.parquet")
    seg = pd.read_csv(C.RES / "segmentos_prueba.csv")
    fig_niveles(res)
    dia = fig_dia(pr)
    fig_instante(pr)
    fig_segmentos(seg)
    fig_informacion(res)
    (C.RES / "figuras.json").write_text(json.dumps({"dia_de_ejemplo": dia}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(dia)


if __name__ == "__main__":
    main()
