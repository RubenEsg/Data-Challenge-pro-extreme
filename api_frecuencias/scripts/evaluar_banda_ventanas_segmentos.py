"""Cobertura de la banda P10-P90 por segmento y sentido en ventanas de 1, 2 y 3 horas de la prueba (§3.1 «por ruta,
sentido, segmento y franja horaria → pronóstico e intervalo de confianza», §9.3) e IC95 bootstrap por días de la
diferencia de WAPE del modelo activo frente a B0 en la prueba.

La banda se ajustó en la validación con filas de UNA hora (scripts/entrenar_segmentos.py), pero GET
/api/v1/predictions/segmentos la aplica a ventanas de 30, 60 y 120 minutos que pueden cruzar 2 o 3 horas: μ = fracción
de la ventana × pronóstico de la ruta en la ventana. Aquí se mide esa misma regla en ventanas de horas consecutivas de
la prueba, con el total real de la ruta (error del reparto solo). Los modelos se ajustan SOLO con el entrenamiento y la
banda es la de la validación (se comprueba que sea la misma de segmentos_modelo.json). Las ventanas de 30 minutos no se
pueden medir: las subidas por segmento son por hora de salida.

Análisis posterior a la prueba, agregado en la revisión del paquete: no cambia la elección, la activación ni la banda.

Uso:  python scripts/evaluar_banda_ventanas_segmentos.py [--salida docs/evidencias/modelo/segmentos_banda_ventanas.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.servicios import modelo_segmentos as ms  # noqa: E402
from scripts import entrenar_segmentos as es  # noqa: E402

HORAS_VENTANA = (1, 2, 3)
EVIDENCIA = RAIZ / "docs" / "evidencias" / "modelo"


def ventanas(x: pd.DataFrame, f, horas: int) -> pd.DataFrame:
    """Suma, por ruta, fecha y segmento, las subidas reales (y), las previstas (μ = T · f) y el total de la ruta de
    cada ventana de `horas` horas consecutivas que empieza en una hora de servicio; solo ventanas con todas sus horas
    (la malla tiene una fila por segmento en cada hora con subidas de la ruta)."""
    d = x.assign(mu=x["total"].to_numpy(float) * np.asarray(f, float))
    claves = ["ruta", "fecha", "id_segmento", "sentido"]
    partes = []
    for h0 in range(min(ms.datos.HORAS_SERVICIO), max(ms.datos.HORAS_SERVICIO) - horas + 2):
        sel = d[(d["hora"] >= h0) & (d["hora"] < h0 + horas)]
        g = sel.groupby(claves, as_index=False).agg(y=("y", "sum"), mu=("mu", "sum"), total=("total", "sum"),
                                                    horas=("hora", "nunique"))
        partes.append(g[g["horas"] == horas].assign(h0=h0))
    return pd.concat(partes, ignore_index=True)


def _banda(y, mu, total, banda: dict) -> dict:
    t = np.asarray(total, float)
    f = np.asarray(mu, float) / np.where(t > 0, t, 1.0)
    lo, hi = ms.banda_compuesta(f, t, t, t, banda)
    return es.cobertura(y, lo, hi)


def cobertura_ventanas(v: pd.DataFrame, bandas: dict) -> dict:
    """Cobertura de la banda (la de la API, con el total real) por segmento y por sentido en las ventanas `v`."""
    s = v.groupby(["ruta", "fecha", "h0", "sentido"], as_index=False).agg(y=("y", "sum"), mu=("mu", "sum"),
                                                                          total=("total", "first"))
    return {"segmento": _banda(v["y"], v["mu"], v["total"], bandas["segmento"]),
            "sentido": _banda(s["y"], s["mu"], s["total"], bandas["sentido"])}


def evaluar(celdas: pd.DataFrame, activo: str, ev_modelo: dict) -> dict:
    """Ajusta B0 y el candidato activo con el entrenamiento, calibra su banda en la validación y mide la prueba."""
    segs = es.segmentos_de(celdas)
    cal = ms.calendario_serie(min(celdas["fecha"]), max(celdas["fecha"]))
    ent = es.ventana(celdas, "entrenamiento")
    x_ent = es.preparar_ajuste(ent, segs, cal, ms.PARTICION["entrenamiento"][0])
    x_val = es.preparar_evaluacion(ent, es.ventana(celdas, "validacion"), segs, cal)
    x_pru = es.preparar_evaluacion(ent, es.ventana(celdas, "prueba"), segs, cal)
    candidatos = list(dict.fromkeys(["B0", activo]))
    modelos = {c: {"tipo": es.CANDIDATOS[c], **ms.ajustar(es.CANDIDATOS[c], x_ent)} for c in candidatos}
    bandas = {c: es.calibrar(x_val, ms.fracciones_previstas(m, x_val)) for c, m in modelos.items()}
    f_pru = {c: ms.fracciones_previstas(m, x_pru) for c, m in modelos.items()}
    regla = ms.REGLA_ELECCION
    return {"bandas_iguales_a_segmentos_modelo": all(bandas[c] == ev_modelo["bandas"][c] for c in candidatos),
            "ic95_prueba_wape_segmento_hora_vs_B0": es.bootstrap_dias(x_pru, f_pru[activo], f_pru["B0"],
                                                                      regla["bootstrap_replicas"], regla["semilla"]),
            "cobertura": {c: {f"{h}h": cobertura_ventanas(ventanas(x_pru, f_pru[c], h), bandas[c])
                              for h in HORAS_VENTANA} for c in candidatos}}


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=EVIDENCIA / "segmentos_banda_ventanas.json")
    a = p.parse_args(argv)
    ev_modelo = json.loads((EVIDENCIA / "segmentos_modelo.json").read_text(encoding="utf-8"))
    activo = ev_modelo["activacion"]["activo_candidato"]
    out = {"requisito": "§3.1 pronóstico e intervalo de confianza por sentido, segmento y franja horaria; §9.3",
           "script": "scripts/evaluar_banda_ventanas_segmentos.py",
           "particion": ev_modelo["particion"], "activo": ev_modelo["activacion"]["activo"],
           "activo_candidato": activo, "cobertura_objetivo": ms.COBERTURA_OBJETIVO,
           "metodo": "modelos ajustados solo con el entrenamiento, banda de la validación aplicada como en la API "
                     "(μ = fracción de la ventana × total real de la ruta en la ventana) a ventanas de horas "
                     "consecutivas de la prueba que empiezan en cada hora de servicio",
           **evaluar(es.cargar_celdas(), activo, ev_modelo),
           "nota": "análisis posterior a la prueba (revisión): no cambia la elección, la activación ni la banda; las "
                   "ventanas de 30 min no se pueden medir porque las subidas por segmento son por hora de salida"}
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({c: {h: (v["segmento"]["cobertura_pct"], v["sentido"]["cobertura_pct"]) for h, v in d.items()}
                      for c, d in out["cobertura"].items()}, ensure_ascii=False))
    return out


if __name__ == "__main__":
    main()
