"""Análisis POSTERIOR a la prueba (no estaba en el protocolo): cuánto pesa en las cifras un registro imposible.

Al revisar la prueba, el RMSE por ruta salió varias veces mayor que el MAE. La causa es un registro de conteo
imposible: el 5 de julio de 2025 a las 07:45, la base trae 28.782 subidas en un solo segmento de CRA 54 en un bloque
de 15 minutos. Hay otro igual en el entrenamiento (97.157 subidas, el 26 de mayo de 2024). El panel conserva los
registros tal como están en la base y el protocolo no previó filtrarlos, así que las cifras de la prueba
(resultados/prueba.json) lo incluyen y NO se cambian.

Este guion no entrena ni vuelve a pronosticar. Lee las predicciones guardadas por ruta y por sentido y recalcula las
métricas de todos los pronósticos sin los días de la ruta en que un registro imposible entra en el objetivo o en la
referencia de ocho semanas del promedio por día y hora: el día del registro y los ocho mismos días de la semana
siguientes. Se quitan los mismos días a todos los pronósticos. Regla del registro imposible: más de UMBRAL subidas en
un segmento en 15 minutos. Por segmento no se recalcula, porque las predicciones por segmento no se guardan.

Escribe resultados/sensibilidad_registro_anomalo.json.

Uso (desde esta carpeta):  python sensibilidad_registro_anomalo.py
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

import comun as C

UMBRAL = 1000          # subidas en un segmento en 15 minutos: ningún bus las puede recibir
SEMANAS = 8            # las semanas en que el registro sigue dentro del promedio por día y hora
BASES = ("promedio_dia_hora", "ultima_semana", "persistencia")


def registros_imposibles() -> list[dict]:
    out = []
    for idruta in C.RUTAS:
        r = C.cargar_ruta(idruta)
        for d, b, s in zip(*np.nonzero(r.y > UMBRAL), strict=True):
            fecha = C.DIA0 + pd.Timedelta(days=int(d))
            periodo = next((p for p in C.PERIODOS if C.rango_dias(p)[0] <= d <= C.rango_dias(p)[1]), None)
            out.append({"ruta": r.nombre, "fecha": str(fecha.date()), "hora": f"{b // 4:02d}:{b % 4 * 15:02d}",
                        "nro_segmento": int(r.seg["nro_segmento"].iloc[s]), "subidas": int(r.y[d, b, s]),
                        "subidas_de_la_ruta_en_ese_bloque": int(r.y[d, b].sum()), "periodo": periodo,
                        "mediana_de_la_ruta_en_ese_bloque": float(np.median(r.y[:, b].sum(axis=1)))})
    return out


def medir(t: pd.DataFrame, dia0: pd.Timestamp) -> dict:
    """Métricas de cada pronóstico y el IC95 de la diferencia del modelo con el promedio por día y hora."""
    y = t["real"].to_numpy(float)
    preds = {"modelo": t["pronostico"].to_numpy(float), **{b: t[b].to_numpy(float) for b in BASES}}
    out = {k: C.metricas(y, p) for k, p in preds.items()}
    dia = (pd.to_datetime(t["fecha"]) - dia0).dt.days.to_numpy()
    ic = C.bootstrap_wape(dia, y, preds, ref="promedio_dia_hora")
    out["modelo_menos_promedio_dia_hora"] = {"diferencia": round(out["modelo"]["wape"] - out["promedio_dia_hora"]["wape"], 3),
                                             "ic95": ic["modelo_menos_promedio_dia_hora"]["ic95"]}
    return out


def main() -> None:
    pru = json.loads((C.RES / "prueba.json").read_text(encoding="utf-8"))
    a, b = C.rango_dias("prueba")
    dia0 = C.DIA0 + pd.Timedelta(days=a)
    registros = registros_imposibles()
    excluir: set[tuple[str, str]] = set()
    for reg in registros:
        f0 = pd.Timestamp(reg["fecha"])
        for j in range(SEMANAS + 1):
            f = f0 + pd.Timedelta(days=7 * j)
            if a <= (f - C.DIA0).days <= b:
                excluir.add((reg["ruta"], str(f.date())))
    res: dict = {"generado": time.strftime("%Y-%m-%d %H:%M"),
                 "que_es": "análisis posterior a la prueba, no previsto en PROTOCOLO.md; las cifras de resultados/prueba.json no cambian",
                 "regla": f"registro imposible: más de {UMBRAL} subidas en un segmento en 15 minutos",
                 "registros_imposibles": registros,
                 "dias_de_ruta_excluidos": sorted(f"{r} {f}" for r, f in excluir),
                 "por_que_esos_dias": f"el día del registro y los {SEMANAS} mismos días de la semana siguientes: en ellos el registro entra en el "
                                      "objetivo o en el promedio por día y hora",
                 "niveles": {}}
    for nivel in ("ruta", "sentido"):
        t = pd.read_parquet(C.RES / f"predicciones_{nivel}.parquet")
        t["fecha"] = t["fecha"].astype(str)
        fuera = pd.MultiIndex.from_frame(t[["ruta", "fecha"]]).isin(list(excluir))
        res["niveles"][nivel] = {}
        for h in C.HORIZONTES:
            m = (t["horizonte_min"] == h).to_numpy()
            con, sin = medir(t[m], dia0), medir(t[m & ~fuera], dia0)
            oficial = pru["niveles"][nivel][str(h)]["todas_las_rutas"]["modelo"]["wape"]
            if abs(con["modelo"]["wape"] - oficial) > 0.01:
                raise SystemExit(f"{nivel} {h}: las predicciones guardadas dan {con['modelo']['wape']} y prueba.json {oficial}")
            res["niveles"][nivel][str(h)] = {"celdas": int(m.sum()), "celdas_excluidas": int((m & fuera).sum()),
                                             "con_el_registro": con, "sin_esos_dias": sin}
            print(f"{nivel:8s} h={h:3d}: modelo {con['modelo']['wape']:.2f} -> {sin['modelo']['wape']:.2f} · promedio "
                  f"{con['promedio_dia_hora']['wape']:.2f} -> {sin['promedio_dia_hora']['wape']:.2f} · RMSE del modelo "
                  f"{con['modelo']['rmse']:.1f} -> {sin['modelo']['rmse']:.1f} · diferencia {sin['modelo_menos_promedio_dia_hora']}")
    (C.RES / "sensibilidad_registro_anomalo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(registros, ensure_ascii=False, indent=1))
    print("días de ruta excluidos:", len(excluir))


if __name__ == "__main__":
    main()
