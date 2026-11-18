"""Prueba reservada (2025-07-01 a 2025-12-31): UN SOLO cálculo con lo elegido en la validación (PROTOCOLO.md, sección 6).

Lee resultados/seleccion.json, reentrena lo elegido con todo lo anterior al 1 de julio de 2025 (entrenamiento más
validación), pronostica la prueba y escribe:
  resultados/prueba.json                 todas las cifras: por nivel, horizonte, ruta, franja, sentido, mes y tipo de día,
                                         IC95, banda P10-P90, análisis secundarios, importancia de variables y versiones
  resultados/predicciones_ruta.parquet   por ruta, día, instante y horizonte: real, pronóstico, banda y líneas base
  resultados/predicciones_sentido.parquet  lo mismo por sentido
  resultados/segmentos_prueba.csv        por segmento y horizonte: subidas reales y pronosticadas, sesgo y WAPE
Si resultados/prueba.json ya existe no vuelve a correr (la prueba se calcula una vez); --repetir lo permite y lo anota.

Uso (desde esta carpeta):  python probar.py
"""
from __future__ import annotations

import json
import platform
import sys
import time

import numpy as np
import pandas as pd

import comun as C

BASES = ("promedio_dia_hora", "ultima_semana", "persistencia")
ENTRENAR = ("entrenamiento", "validacion")
TIPOS = {0: "laboral", 1: "sábado", 2: "domingo o festivo"}


def evaluar(y, p, bases: dict, inst, dia, con_franjas: bool = True) -> dict:
    """Métricas del modelo y de las líneas base sobre las mismas celdas, con el IC95 de cada WAPE y de la diferencia."""
    out = {"modelo": C.metricas(y, p), **{b: C.metricas(y, v) for b, v in bases.items()}}
    out["ic95"] = C.bootstrap_wape(dia, y, {"modelo": p, **bases}, ref="promedio_dia_hora")
    if con_franjas:
        out["por_franja"] = {"modelo": C.por_franja(y, p, inst), "promedio_dia_hora": C.por_franja(y, bases["promedio_dia_hora"], inst)}
    return out


def main() -> None:
    t0 = time.time()
    destino = C.RES / "prueba.json"
    repetida = destino.exists()
    if repetida and "--repetir" not in sys.argv:
        sys.exit("resultados/prueba.json ya existe: la prueba se calcula una sola vez (use --repetir solo si cambió el código "
                 "por un error y anótelo en el README)")
    sel = json.loads((C.RES / "seleccion.json").read_text(encoding="utf-8"))
    rutas = {i: C.cargar_ruta(i) for i in C.RUTAS}
    a, b = C.rango_dias("prueba")
    fechas = pd.date_range(C.DIA0 + pd.Timedelta(days=a), periods=b - a + 1, freq="D")
    pred: dict = {}
    importancia: dict = {}
    res: dict = {"generado": time.strftime("%Y-%m-%d %H:%M"), "repetida": repetida, "periodos": C.PERIODOS,
                 "entrenado_con": "2023-01-01 a 2025-06-30 (entrenamiento más validación)",
                 "seleccion": {k: sel[k] for k in ("conjunto", "estructura")},
                 "hiper": {n: sel["hiper"][n]["nombre"] for n in C.NIVELES},
                 "dias_con_datos_en_la_prueba": {r.nombre: int(r.ok[a:b + 1].sum()) for r in rutas.values()},
                 "dias_del_periodo": int(b - a + 1), "niveles": {}}

    def correr(nivel, h, conjunto, clave, latencia=0, guardar_importancia=False):
        hp = {k: v for k, v in sel["hiper"][nivel]["valores"].items() if k not in C.HIPER or C.HIPER[k] != v}
        for idruta, r in rutas.items():
            o = C.pronosticar(r, nivel, h, conjunto, entrenar=ENTRENAR, predecir="prueba", hiper=hp, latencia=latencia,
                              con_modelo=guardar_importancia)
            if guardar_importancia:
                m = o.pop("modelo")
                g = m.booster_.feature_importance(importance_type="gain")
                importancia.setdefault((nivel, h), {})[r.nombre] = dict(zip(o["nombres"], (g / g.sum()).round(5).tolist(), strict=True))
            pred[(nivel, h, clave, idruta)] = o
            print(f"  {nivel:9s} h={h:3d} {clave:12s} {r.nombre:9s} filas {o['n_entrenamiento']:>9,}  {o['segundos']:6.1f} s", flush=True)

    # ------------------------------------------------------------------ lo elegido, en los tres niveles
    for nivel in C.NIVELES:
        for h in C.HORIZONTES:
            correr(nivel, h, sel["conjunto"][nivel], "final", guardar_importancia=True)
    # estructura elegida: sentido como suma de segmentos y segmento conciliado con la ruta, si así se eligió. La suma
    # va primero y usa el modelo directo por segmento, que es exactamente lo que midió validar.py.
    for h in C.HORIZONTES:
        for idruta, r in rutas.items():
            seg, rut = pred[("segmento", h, "final", idruta)], pred[("ruta", h, "final", idruta)]
            if sel["estructura"]["sentido"] == "suma_de_segmentos":
                ida = (r.seg["sentido"] == "ida").to_numpy()
                sen = pred[("sentido", h, "final", idruta)]
                suma = np.stack([seg["p"][:, :, ida].sum(axis=2), seg["p"][:, :, ~ida].sum(axis=2)], axis=2)
                sen["p"] = np.where(np.isnan(sen["y"]), np.nan, suma)
            if sel["estructura"]["segmento"] == "conciliado_con_la_ruta":
                total = seg["p"].sum(axis=2, keepdims=True)
                with np.errstate(invalid="ignore", divide="ignore"):
                    seg["p"] = np.where(np.isnan(seg["y"]), np.nan, np.where(total > 0, seg["p"] * rut["p"] / total, seg["p"]))

    def celdas(nivel, h, idruta, clave="final"):
        o = pred[(nivel, h, clave, idruta)]
        y, p, b1, b2, b3, inst, dia = C.aplanar(o["y"], o["p"], *(o["base"][k] for k in BASES))
        return y, p, dict(zip(BASES, (b1, b2, b3), strict=True)), inst, dia

    def juntar(nivel, h, clave="final"):
        partes = [celdas(nivel, h, i, clave) for i in C.RUTAS]
        return (np.concatenate([x[0] for x in partes]), np.concatenate([x[1] for x in partes]),
                {k: np.concatenate([x[2][k] for x in partes]) for k in BASES},
                np.concatenate([x[3] for x in partes]), np.concatenate([x[4] for x in partes]))

    # ------------------------------------------------------------------ métricas por nivel y horizonte
    for nivel in C.NIVELES:
        res["niveles"][nivel] = {}
        for h in C.HORIZONTES:
            y, p, bases, inst, dia = juntar(nivel, h)
            bloque = {"todas_las_rutas": evaluar(y, p, bases, inst, dia), "por_ruta": {}, "banda_p10_p90": {}}
            los, his, ys = [], [], []
            for idruta, nombre in C.RUTAS.items():
                yy, pp, bb, ii, dd = celdas(nivel, h, idruta)
                bloque["por_ruta"][nombre] = evaluar(yy, pp, bb, ii, dd)
                lo, hi = C.conformal_aplicar(pp, sel["banda"][nivel][str(h)][nombre])
                bloque["banda_p10_p90"][nombre] = C.cobertura(yy, lo, hi)
                los.append(lo), his.append(hi), ys.append(yy)
            bloque["banda_p10_p90"]["todas_las_rutas"] = C.cobertura(np.concatenate(ys), np.concatenate(los), np.concatenate(his))
            # por mes y por tipo de día (análisis secundario 3)
            mes = fechas.month.to_numpy()[dia]
            tipo = np.concatenate([rutas[i].cal["tipo_dia"].to_numpy()[a:b + 1][celdas(nivel, h, i)[4]] for i in C.RUTAS])
            bloque["por_mes"] = {str(m): {"modelo": C.metricas(y[mes == m], p[mes == m]).get("wape"),
                                          "promedio_dia_hora": C.metricas(y[mes == m], bases["promedio_dia_hora"][mes == m]).get("wape")}
                                 for m in sorted(set(mes))}
            prom = bases["promedio_dia_hora"]
            bloque["por_tipo_de_dia"] = {TIPOS[t]: {"modelo": C.metricas(y[tipo == t], p[tipo == t]).get("wape"),
                                                     "promedio_dia_hora": C.metricas(y[tipo == t], prom[tipo == t]).get("wape"),
                                                     "n": int((tipo == t).sum())} for t in sorted(set(tipo))}
            res["niveles"][nivel][str(h)] = bloque
            m = bloque["todas_las_rutas"]
            print(f"{nivel} h={h}: modelo {m['modelo']['wape']} · promedio {m['promedio_dia_hora']['wape']} · última semana "
                  f"{m['ultima_semana']['wape']} · persistencia {m['persistencia']['wape']} · banda "
                  f"{bloque['banda_p10_p90']['todas_las_rutas']['cobertura_pct']}", flush=True)

    # ------------------------------------------------------------------ por sentido y por segmento
    res["por_sentido"], filas_seg = {}, []
    for h in C.HORIZONTES:
        res["por_sentido"][str(h)] = {}
        for idruta, r in rutas.items():
            o = pred[("sentido", h, "final", idruta)]
            for j, nombre in enumerate(("ida", "regreso")):
                y, p, b1, _, _ = C.aplanar(o["y"][:, :, j:j + 1], o["p"][:, :, j:j + 1], o["base"]["promedio_dia_hora"][:, :, j:j + 1])
                res["por_sentido"][str(h)][f"{r.nombre} · {nombre}"] = {"modelo": C.metricas(y, p), "promedio_dia_hora": C.metricas(y, b1)}
            s = pred[("segmento", h, "final", idruta)]
            vale = ~np.isnan(s["y"])
            n = vale.sum(axis=(0, 1))
            real, pron = np.nansum(s["y"], axis=(0, 1)), np.nansum(s["p"], axis=(0, 1))
            err = np.nansum(np.abs(s["p"] - s["y"]), axis=(0, 1))
            err_b = np.nansum(np.abs(s["base"]["promedio_dia_hora"] - s["y"]), axis=(0, 1))
            for j in range(len(r.seg)):
                filas_seg.append({"ruta": r.nombre, "nro_segmento": int(r.seg["nro_segmento"].iloc[j]), "sentido": r.seg["sentido"].iloc[j],
                                  "km_inicio": float(r.seg["km_inicio"].iloc[j]), "horizonte_min": h, "celdas": int(n[j]),
                                  "subidas_reales": float(real[j]), "subidas_pronosticadas": round(float(pron[j]), 1),
                                  "sesgo_pct": round(float((pron[j] / real[j] - 1) * 100), 2) if real[j] > 0 else None,
                                  "wape": round(float(err[j] / real[j] * 100), 2) if real[j] > 0 else None,
                                  "wape_promedio_dia_hora": round(float(err_b[j] / real[j] * 100), 2) if real[j] > 0 else None})
    seg_df = pd.DataFrame(filas_seg)
    seg_df.to_csv(C.RES / "segmentos_prueba.csv", index=False, lineterminator="\n")
    res["por_segmento"] = {}
    for h in C.HORIZONTES:
        g = seg_df[(seg_df["horizonte_min"] == h) & seg_df["sesgo_pct"].notna()]
        peso = g["subidas_reales"] / g["subidas_reales"].sum()
        gana = g["wape"] < g["wape_promedio_dia_hora"]
        res["por_segmento"][str(h)] = {
            "segmentos_con_subidas": int(len(g)), "segmentos": int((seg_df["horizonte_min"] == h).sum()),
            "sesgo_pct_cuartiles": [round(float(q), 2) for q in g["sesgo_pct"].quantile([0.1, 0.25, 0.5, 0.75, 0.9])],
            "sesgo_abs_mediano_pct": round(float(g["sesgo_pct"].abs().median()), 2),
            "sesgo_abs_medio_ponderado_pct": round(float((g["sesgo_pct"].abs() * peso).sum()), 2),
            "segmentos_con_sesgo_abs_menor_de_5_pct": int((g["sesgo_pct"].abs() < 5).sum()),
            "segmentos_en_que_gana_al_promedio": int(gana.sum()),
            "subidas_en_segmentos_en_que_gana_pct": round(float(peso[gana].sum() * 100), 2),
        }

    # ------------------------------------------------------------------ análisis secundarios (ruta)
    sec: dict = {"informacion_del_dia": {}, "retraso_de_la_captura": {}}
    for h in C.HORIZONTES:
        correr("ruta", h, "semanal", "semanal")
        y, p, bases, inst, dia = juntar("ruta", h, "semanal")
        yf, pf, _, _, diaf = juntar("ruta", h)
        sec["informacion_del_dia"][str(h)] = {
            "semanal": C.metricas(y, p), "elegido": C.metricas(yf, pf),
            "ic95": C.bootstrap_wape(dia, y, {"elegido": pf, "semanal": p}, ref="semanal")}
        sec["retraso_de_la_captura"][str(h)] = {"0": C.metricas(yf, pf).get("wape")}
        if sel["conjunto"]["ruta"] != "semanal":
            for lat in (1, 2):
                correr("ruta", h, sel["conjunto"]["ruta"], f"retraso{lat}", latencia=lat)
                yl, pl, _, _, _ = juntar("ruta", h, f"retraso{lat}")
                sec["retraso_de_la_captura"][str(h)][str(lat * 15)] = C.metricas(yl, pl).get("wape")
    res["secundarios"] = sec

    # ------------------------------------------------------------------ importancia de variables (ganancia, media de las rutas)
    res["importancia"] = {}
    for (nivel, h), por_ruta in importancia.items():
        media = pd.DataFrame(por_ruta).mean(axis=1).sort_values(ascending=False)
        res["importancia"].setdefault(nivel, {})[str(h)] = {k: round(float(v), 4) for k, v in media.head(12).items()}

    # ------------------------------------------------------------------ predicciones para las figuras y el cuaderno
    for nivel in ("ruta", "sentido"):
        tablas = []
        for h in C.HORIZONTES:
            for idruta, r in rutas.items():
                o = pred[(nivel, h, "final", idruta)]
                d, i, g = o["y"].shape
                t = pd.DataFrame({"ruta": r.nombre, "fecha": np.repeat(fechas, i * g), "instante": np.tile(np.repeat(C.INSTANTES, g), d),
                                  "horizonte_min": h, "real": o["y"].reshape(-1), "pronostico": o["p"].reshape(-1),
                                  **{k: o["base"][k].reshape(-1) for k in BASES}})
                if nivel == "sentido":
                    t.insert(1, "sentido", np.tile(np.array(["ida", "regreso"]), d * i))
                t = t[t["real"].notna()].copy()
                lo, hi = C.conformal_aplicar(t["pronostico"].to_numpy(float), sel["banda"][nivel][str(h)][r.nombre])
                t["p10"], t["p90"] = lo, hi
                tablas.append(t)
        out = pd.concat(tablas, ignore_index=True)
        for c in ("real", "pronostico", "p10", "p90", *BASES):
            out[c] = out[c].astype(np.float32).round(2)
        out["fecha"] = out["fecha"].dt.date
        out.to_parquet(C.RES / f"predicciones_{nivel}.parquet", index=False, compression="zstd")

    import lightgbm
    import sklearn

    res["versiones"] = {"python": platform.python_version(), "lightgbm": lightgbm.__version__, "numpy": np.__version__,
                        "pandas": pd.__version__, "scikit-learn": sklearn.__version__}
    res["semilla"] = C.SEMILLA
    res["segundos"] = round(time.time() - t0, 1)
    destino.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"listo en {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
