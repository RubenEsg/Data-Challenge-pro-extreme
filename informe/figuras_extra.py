"""Prepara la carpeta figuras/ del informe técnico final.

    python EntregaFinal/informe/figuras_extra.py        (desde cualquier carpeta; segundos)

1. Copia las figuras que el informe reutiliza tal cual: las tres de la sección de metodología
   (documentos/metodologia/figures/*.pdf), la de la ablación de E11 y la de potencia del piloto P2.
2. Genera la única figura nueva, fig_plan_reasigna.pdf: salidas válidas por hora, hoy frente al plan que
   reasigna (D5 reoptimizado con costos con fuente, e = 0,5), promedio por día de 2025, por ruta y tipo de día.
   Lee solo un archivo de resultados: costos/resultados/d5_reoptimizado_decisiones.parquet (columnas n_S0 =
   salidas válidas reales y x_corrida_1 = plan «D5 costos nuevos, pago por hora, e=0,5», el de 450,9 salidas
   por día de costos/resultados/d5_reoptimizado.csv). No consulta la base de datos.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
PROYECTO = AQUI.parents[1]                                   # carpeta DATA CHALLENGE/
FIGURAS = AQUI / "figuras"

# Figuras reutilizadas: nombre en figuras/ -> archivo de origen (relativo a la carpeta del proyecto).
COPIAS = {
    "fig_demand_profile.pdf": "documentos/metodologia/figures/fig_demand_profile.pdf",
    "fig_rolling_folds.pdf": "documentos/metodologia/figures/fig_rolling_folds.pdf",
    "fig_model_pipeline.pdf": "documentos/metodologia/figures/fig_model_pipeline.pdf",
    "e11_wape_variantes_ruta.png": "experimentos/E11_modelo_mejorado/fig1_wape_variantes_ruta.png",
    "p2_potencia.png": "experimentos/P2_piloto_beta/fig2_potencia.png",
}

DECISIONES = PROYECTO / "costos" / "resultados" / "d5_reoptimizado_decisiones.parquet"

# Mismo estilo que documentos/metodologia/figuras.py (sans-serif, líneas de 2 pt, PDF con fuentes TrueType).
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Latin Modern Sans", "DejaVu Sans"],
    "font.size": 11,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 11,
    "lines.linewidth": 2.0,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "pdf.fonttype": 42,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
})
NAVY, GRIS = "#1F3A5F", "#9A9A9A"


def copiar() -> None:
    FIGURAS.mkdir(exist_ok=True)
    for destino, origen in COPIAS.items():
        shutil.copy2(PROYECTO / origen, FIGURAS / destino)
        print(f"copiada  {origen} -> figuras/{destino}")


def fig_plan_reasigna() -> None:
    d = pd.read_parquet(DECISIONES, columns=["ruta", "dia", "hora", "tipo_dia", "n_S0", "x_corrida_1"])
    rutas = ["SILENCIO", "CRA 54", "CL 72"]
    tipos = [("Laboral", "Día laboral"), ("Domingo/festivo", "Domingo o festivo")]
    horas = np.arange(4, 21)

    fig, ejes = plt.subplots(2, 3, figsize=(6.6, 4.4), sharex=True)
    for fila, (tipo, etiqueta) in enumerate(tipos):
        sub = d[d["tipo_dia"] == tipo]
        n_dias = sub["dia"].nunique()
        for col, ruta in enumerate(rutas):
            ax = ejes[fila, col]
            r = sub[sub["ruta"] == ruta].groupby("hora")[["n_S0", "x_corrida_1"]].sum().reindex(horas) / n_dias
            ax.step(horas, r["n_S0"], where="mid", color=GRIS, label="Hoy (oferta real 2025)")
            ax.step(horas, r["x_corrida_1"], where="mid", color=NAVY, label="Plan que reasigna")
            ax.set_ylim(0, None)
            ax.set_xticks([4, 8, 12, 16, 20])
            ax.set_title(ruta, fontsize=10)
            if col == 0:
                ax.set_ylabel(f"{etiqueta}\nsalidas por hora")
            if fila == 1:
                ax.set_xlabel("Hora de salida")
    manijas, etiquetas = ejes[0, 0].get_legend_handles_labels()
    fig.legend(manijas, etiquetas, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 1.04))
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    ruta = FIGURAS / "fig_plan_reasigna.pdf"
    fig.savefig(ruta)
    plt.close(fig)
    print(f"generada figuras/{ruta.name}")


if __name__ == "__main__":
    copiar()
    fig_plan_reasigna()
