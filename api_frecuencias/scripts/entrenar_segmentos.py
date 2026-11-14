"""Entrenamiento, elección y evaluación del modelo por segmento y sentido (§9.1, §9.3; §3.1 «pronóstico e intervalo
de confianza» por sentido y segmento). Protocolo fijado antes de mirar la prueba:
docs/evidencias/modelo/segmentos_protocolo.md (constantes en app/servicios/modelo_segmentos.py).

1. Datos: datos/subidas_segmento_hora.parquet (scripts/preparar_segmentos.py) y el calendario de la serie empaquetada.
2. Partición cronológica sin solape (PARTICION): entrenamiento, validación y prueba.
3. Candidatos: B0 (reparto fijo), M1 (HGB Poisson con offset log(T · B0)) y M2 (HGB Poisson con offset log T),
   ajustados con el entrenamiento; la fracción B0 de las filas de entrenamiento es fuera de pliegue.
4. Elección con la regla fija (REGLA_ELECCION) sobre la validación; banda conformal ajustada en la validación.
5. Prueba (una vez; --sin-prueba la omite y no guarda nada): WAPE, MAE y sesgo por segmento, sentido y ruta; cobertura
   y ancho de la banda con el total real y de punta a punta con B2 (pronóstico de ruta fuera de muestra real para 2023);
   sesgo por condición y su composición con el sesgo de la ruta medido en 2025.
6. Producción: el elegido (y B0 como línea base) se reentrena con los 56 días y se registra en
   datos/modelos/segmentos/ (artefacto, manifiesto con SHA-256 y registro). Evidencia: segmentos_modelo.json y .md.

Uso:  python scripts/entrenar_segmentos.py [--sin-prueba] [--salida docs/evidencias/modelo] [--dir-modelos DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.servicios import datos, inferencia  # noqa: E402
from app.servicios import modelo_segmentos as ms  # noqa: E402

ARCHIVO_CELDAS = "subidas_segmento_hora.parquet"
CANDIDATOS = {"B0": ms.TIPO_REPARTO, "M1": ms.TIPO_OFFSET_REPARTO, "M2": ms.TIPO_OFFSET_TOTAL,
              "M3": ms.TIPO_DENTRO_SENTIDO, "M4": ms.TIPO_JERARQUICO}
TIPOS_DIA = {0: "laboral", 1: "sabado", 2: "domingo_festivo"}
MIN_SUBIDAS_SEGMENTO = 50   # segmentos con menos subidas no entran en la mediana del sesgo (ruido de conteo)
CLAVES_SENTIDO = [*ms.CLAVES_HORA, "sentido"]


# ----------------------------------------------------------------------------------------------- datos
def cargar_celdas(archivo: Path | None = None) -> pd.DataFrame:
    archivo = archivo or datos.carpeta_datos() / ARCHIVO_CELDAS
    c = pd.read_parquet(archivo)
    c["fecha"] = pd.to_datetime(c["fecha"]).dt.date
    return c.astype({"hora": int, "tipo_dia": int, "id_segmento": int, "nro_segmento": int, "subidas": float})


def segmentos_de(celdas: pd.DataFrame) -> pd.DataFrame:
    """Metadatos de cada segmento: número, sentido, inicio, longitud y posición relativa del punto medio en el ciclo."""
    s = celdas.drop_duplicates("id_segmento")[["ruta", "id_segmento", "nro_segmento", "sentido", "km_inicio",
                                                "longitud_m"]].copy()
    ciclo = s.groupby("ruta")["longitud_m"].transform("sum")
    s["pos_rel"] = (s["km_inicio"] * 1000 + s["longitud_m"] / 2) / ciclo
    return s.sort_values(["ruta", "nro_segmento"]).reset_index(drop=True)


def ventana(celdas: pd.DataFrame, nombre: str) -> pd.DataFrame:
    desde, hasta = ms.PARTICION[nombre]
    return celdas[(celdas["fecha"] >= desde) & (celdas["fecha"] <= hasta)]


def huella(archivo: Path) -> str:
    return hashlib.sha256(archivo.read_bytes()).hexdigest()


def con_calendario(m: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    return m.merge(cal.drop(columns="tipo_dia"), on="fecha", how="left")


def preparar_ajuste(celdas_ajuste: pd.DataFrame, segs: pd.DataFrame, cal: pd.DataFrame, inicio: date) -> pd.DataFrame:
    """Filas de ajuste (cada hora × segmento) con la fracción B0 calculada fuera de pliegue."""
    m = con_calendario(ms.malla(celdas_ajuste, segs), cal)
    m["pliegue"] = ms.pliegues(m["fecha"], inicio)
    return ms.matriz(m, ms.codificar_fuera_de_pliegue(celdas_ajuste, segs, inicio))


def preparar_evaluacion(celdas_ajuste: pd.DataFrame, celdas_eval: pd.DataFrame, segs: pd.DataFrame,
                        cal: pd.DataFrame) -> pd.DataFrame:
    """Filas a evaluar con la fracción B0 de TODO el ajuste (con respaldo jerárquico si la celda no se vio)."""
    cod = ms.fracciones_base(celdas_ajuste, segs, objetivo=celdas_eval)
    return ms.matriz(con_calendario(ms.malla(celdas_eval, segs), cal), cod)


# ----------------------------------------------------------------------------------------------- métricas
def _pct(num: float, den: float) -> float | None:
    return None if den <= 0 else round(float(num / den * 100), 2) + 0.0   # + 0.0: sin «-0.0»


def _wape(y, p) -> float | None:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return _pct(np.abs(p - y).sum(), y.sum())


def _sesgo(y, p) -> float | None:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return _pct((p - y).sum(), y.sum())


def _sesgo_segmentos(d: pd.DataFrame) -> dict:
    """Mediana y p90 del sesgo absoluto por segmento (segmentos con al menos MIN_SUBIDAS_SEGMENTO subidas)."""
    g = d.groupby(["ruta", "id_segmento", "nro_segmento", "sentido"])[["y", "p"]].sum()
    g = g[g["y"] >= MIN_SUBIDAS_SEGMENTO]
    if g.empty:
        return {"segmentos": 0}
    s = ((g["p"] - g["y"]) / g["y"] * 100).abs()
    mayor = s[g["y"] >= g["y"].median()]
    return {"segmentos": int(len(g)), "sesgo_abs_mediano_pct": round(float(s.median()), 2),
            "sesgo_abs_p90_pct": round(float(s.quantile(0.9)), 2),
            "sesgo_abs_mediano_mitad_mayor_pct": round(float(mayor.median()), 2)}


def metricas(x: pd.DataFrame, f, total: str = "total") -> dict:
    """WAPE, MAE y sesgo por segmento-hora y sentido-hora, sesgo por segmento, por sentido y por ruta (p = T · f)."""
    d = x.assign(p=x[total].to_numpy(float) * np.asarray(f, float))
    sent = d.groupby(CLAVES_SENTIDO, as_index=False)[["y", "p"]].sum()
    out = {"wape_segmento_hora": _wape(d["y"], d["p"]), "wape_sentido_hora": _wape(sent["y"], sent["p"]),
           "mae_segmento_hora": round(float((d["p"] - d["y"]).abs().mean()), 3),
           "sesgo_pct": _sesgo(d["y"], d["p"]), "subidas": int(d["y"].sum()), **_sesgo_segmentos(d)}
    out["por_sentido"] = {f"{r} | {s}": {"wape_hora": _wape(g["y"], g["p"]), "sesgo_pct": _sesgo(g["y"], g["p"]),
                                         "subidas": int(g["y"].sum())}
                          for (r, s), g in sent.groupby(["ruta", "sentido"])}
    out["por_ruta"] = {r: {"wape_segmento_hora": _wape(g["y"], g["p"]),
                           "wape_sentido_hora": _wape(sent.loc[sent["ruta"] == r, "y"],
                                                      sent.loc[sent["ruta"] == r, "p"]),
                           **_sesgo_segmentos(g)} for r, g in d.groupby("ruta")}
    return out


def bootstrap_dias(x: pd.DataFrame, f_cand, f_base, replicas: int, semilla: int) -> dict:
    """IC95 de WAPE(candidato) − WAPE(B0) por segmento y hora, remuestreando días de la ventana."""
    t = x["total"].to_numpy(float)
    d = pd.DataFrame({"fecha": x["fecha"], "y": x["y"], "ec": np.abs(t * np.asarray(f_cand) - x["y"]),
                      "eb": np.abs(t * np.asarray(f_base) - x["y"])}).groupby("fecha")[["y", "ec", "eb"]].sum()
    rng = np.random.default_rng(semilla)
    idx = rng.integers(0, len(d), size=(replicas, len(d)))
    y, ec, eb = (d[c].to_numpy()[idx].sum(1) for c in ("y", "ec", "eb"))
    dif = (ec - eb) / y * 100
    return {"diferencia_pp": round(float((d["ec"].sum() - d["eb"].sum()) / d["y"].sum() * 100), 3),
            "ic95_pp": [round(float(np.quantile(dif, 0.025)), 3), round(float(np.quantile(dif, 0.975)), 3)],
            "dias": int(len(d)), "replicas": int(replicas), "semilla": int(semilla)}


def elegir(val: dict, boot: dict) -> dict:
    """Regla fija (REGLA_ELECCION) sobre la validación: nunca usa la prueba."""
    base = val["B0"]
    tol = ms.REGLA_ELECCION["tolerancia_wape_sentido_pp"]
    detalle = {}
    for c in boot:
        mejora = boot[c]["ic95_pp"][1] < 0
        sentido_ok = val[c]["wape_sentido_hora"] <= base["wape_sentido_hora"] + tol
        detalle[c] = {"mejora_significativa": bool(mejora), "sentido_no_empeora": bool(sentido_ok),
                      "elegible": bool(mejora and sentido_ok), "wape_segmento_hora": val[c]["wape_segmento_hora"]}
    elegibles = [c for c, d in detalle.items() if d["elegible"]]
    elegido = min(elegibles, key=lambda c: val[c]["wape_segmento_hora"]) if elegibles else "B0"
    return {"elegido": elegido, "detalle": detalle, "regla": ms.REGLA_ELECCION["texto"]}


# ----------------------------------------------------------------------------------------------- banda
def por_sentido(x: pd.DataFrame, f, total: str = "total") -> pd.DataFrame:
    """Filas (ruta, fecha, hora, sentido) con y, la fracción prevista del sentido y el total usado."""
    d = x.assign(f=np.asarray(f, float))
    g = d.groupby(CLAVES_SENTIDO, as_index=False).agg(y=("y", "sum"), f=("f", "sum"), total=(total, "first"))
    extra = [c for c in ("tipo_dia", "carnaval", "lo_r", "hi_r") if c in d.columns]
    if extra:
        g = g.merge(d.drop_duplicates(ms.CLAVES_HORA)[[*ms.CLAVES_HORA, *extra]], on=ms.CLAVES_HORA, how="left")
    return g


def calibrar(x_val: pd.DataFrame, f) -> dict:
    """Banda de segmento y de sentido ajustada en la validación con el total real (μ = T · f)."""
    s = por_sentido(x_val, f)
    return {"segmento": ms.calibrar_banda(x_val["y"], x_val["total"] * np.asarray(f, float)),
            "sentido": ms.calibrar_banda(s["y"], s["total"] * s["f"])}


def cobertura(y, lo, hi) -> dict:
    y, lo, hi = (np.asarray(v, float) for v in (y, lo, hi))
    return {"n": int(len(y)), "cobertura_pct": _pct(((y >= lo) & (y <= hi)).sum(), len(y)),
            "bajo_p10_pct": _pct((y < lo).sum(), len(y)), "sobre_p90_pct": _pct((y > hi).sum(), len(y)),
            "ancho_medio": round(float((hi - lo).mean()), 3), "y_medio": round(float(y.mean()), 3)}


def coberturas(x: pd.DataFrame, f, banda: dict, p50: str, lo_r: str, hi_r: str) -> dict:
    """Cobertura de la banda de segmento y de sentido, global y por tramo de μ y por condición."""
    f = np.asarray(f, float)
    y = x["y"].to_numpy(float)
    lo, hi = ms.banda_compuesta(f, x[p50], x[lo_r], x[hi_r], banda["segmento"])
    s = por_sentido(x.assign(lo_r=x[lo_r], hi_r=x[hi_r]), f, total=p50)
    y_s = s["y"].to_numpy(float)
    lo_s, hi_s = ms.banda_compuesta(s["f"], s["total"], s["lo_r"], s["hi_r"], banda["sentido"])
    tramo = ms.tramo_mu(f * x[p50].to_numpy(float))
    out = {"segmento": cobertura(y, lo, hi), "sentido": cobertura(y_s, lo_s, hi_s),
           "segmento_por_tramo_mu": {str(k): cobertura(y[tramo == k], lo[tramo == k], hi[tramo == k])
                                     for k in sorted(set(tramo.tolist()))}}
    cond_s = condiciones(s)
    for nombre, etiqueta in condiciones(x).items():
        for valor in sorted(set(etiqueta)):
            sel, sel_s = etiqueta == valor, cond_s[nombre] == valor
            out[f"{nombre}={valor}"] = {"segmento": cobertura(y[sel], lo[sel], hi[sel])["cobertura_pct"],
                                        "sentido": cobertura(y_s[sel_s], lo_s[sel_s], hi_s[sel_s])["cobertura_pct"]}
    return out


# ----------------------------------------------------------------------------------------------- pronóstico B2
def totales_ruta(celdas: pd.DataFrame) -> pd.DataFrame:
    return celdas.groupby(ms.CLAVES_HORA, as_index=False)["subidas"].sum().rename(columns={"subidas": "total"})


def pronostico_b2(tot: pd.DataFrame) -> pd.DataFrame:
    """B2 (§9.1 línea base «última semana»): total de la misma ruta y hora hace 7 días (14 si falta). Solo usa días
    anteriores: es un pronóstico de ruta fuera de muestra real para ene-feb 2023."""
    idx = tot.set_index(ms.CLAVES_HORA)["total"]
    out = tot.copy()
    for dias in (7, 14):
        previo = [(r, f - timedelta(days=dias), h) for r, f, h in zip(out["ruta"], out["fecha"], out["hora"],
                                                                      strict=True)]
        valor = idx.reindex(pd.MultiIndex.from_tuples(previo)).to_numpy()
        out["b2"] = valor if dias == 7 else out["b2"].fillna(pd.Series(valor, index=out.index))
    return out.dropna(subset=["b2"])


def banda_b2(b2_val: pd.DataFrame) -> dict:
    """Banda conformal relativa de B2 ajustada en la validación: r = (T − T̂) / max(T̂, 1)."""
    r = (b2_val["total"] - b2_val["b2"]) / np.maximum(b2_val["b2"], 1.0)
    q = ms.cuantiles_conformales(r)
    return {"q_lo": round(q[0], 6), "q_hi": round(q[1], 6), "n": int(len(r))}


def con_b2(x: pd.DataFrame, b2: pd.DataFrame, q: dict) -> pd.DataFrame:
    x = x.merge(b2[[*ms.CLAVES_HORA, "b2"]], on=ms.CLAVES_HORA, how="inner")
    esc = np.maximum(x["b2"], 1.0)
    x["b2_lo"] = np.maximum(x["b2"] + q["q_lo"] * esc, 0.0)
    x["b2_hi"] = x["b2"] + q["q_hi"] * esc
    return x


def cobertura_ruta(horas: pd.DataFrame, p50: str, lo: str, hi: str) -> dict:
    """Cobertura de la banda de la ruta, global y por condición (una fila por ruta y hora)."""
    out = {"global": cobertura(horas["total"], horas[lo], horas[hi])}
    for nombre, etiqueta in condiciones(horas).items():
        for valor in sorted(set(etiqueta)):
            g = horas[etiqueta == valor]
            out[f"{nombre}={valor}"] = cobertura(g["total"], g[lo], g[hi])["cobertura_pct"]
    out["ancho_relativo_medio"] = round(float(((horas[hi] - horas[lo]) / np.maximum(horas[p50], 1.0)).mean()), 4)
    return out


# --------------------------------------------------- composición con el modelo de ruta activo (análisis adicional)
REPLICAS_COMPOSICION = 20
PERIODO_RUTA_ACTIVO = (date(2025, 11, 1), date(2025, 12, 31))


def errores_ruta_activo() -> pd.DataFrame:
    """Razones P50/y, P10/y y P90/y del modelo de ruta ACTIVO con su banda calibrada vigente, fuera de muestra
    (nov-dic 2025, la prueba reservada de la ruta, ya consultada: decisión D8), por ruta, tipo de día y hora."""
    modelo = inferencia.cargar()
    t = inferencia._filas_utiles(inferencia.tabla_variables())
    t = t[(t["fecha"] >= PERIODO_RUTA_ACTIVO[0]) & (t["fecha"] <= PERIODO_RUTA_ACTIVO[1]) & (t["pasajeros"] > 0)]
    p, lo, hi = inferencia._predecir_filas(modelo, t)
    if modelo.get("calibracion"):
        lo, hi = inferencia.aplicar_conformal(p, lo, hi, inferencia.q_calibracion(modelo["calibracion"], t)[0])
    y = t["pasajeros"].to_numpy(float)
    return pd.DataFrame({"ruta": t["ruta"].to_numpy(), "tipo_dia": t["tipo_dia"].astype(int).to_numpy(),
                         "hora": t["hora"].astype(int).to_numpy(), "r50": p / y, "r10": lo / y, "r90": hi / y,
                         "model_id": modelo["model_id"]})


def con_errores_ruta(x: pd.DataFrame, errores: pd.DataFrame, semilla: int) -> pd.DataFrame:
    """A cada hora de 2023 le asigna el error de una hora de 2025 del mismo estrato (ruta, tipo de día, hora) tomada
    al azar: P50' = T · r50, P10' = T · r10, P90' = T · r90 (la banda de la ruta conserva su cobertura de 2025)."""
    rng = np.random.default_rng(semilla)
    horas = x.drop_duplicates(ms.CLAVES_HORA)[[*ms.CLAVES_HORA, "tipo_dia", "total"]].reset_index(drop=True)
    grupos = {k: g[["r50", "r10", "r90"]].to_numpy() for k, g in errores.groupby(["ruta", "tipo_dia", "hora"])}
    filas = []
    for r, td, h in zip(horas["ruta"], horas["tipo_dia"], horas["hora"], strict=True):
        g = grupos.get((r, td, h))
        filas.append(g[rng.integers(0, len(g))] if g is not None else (np.nan, np.nan, np.nan))
    horas[["r50", "r10", "r90"]] = np.asarray(filas, dtype=float)
    horas = horas.dropna(subset=["r50"])
    for c, r in (("ra_p50", "r50"), ("ra_lo", "r10"), ("ra_hi", "r90")):
        horas[c] = horas["total"] * horas[r]
    return x.merge(horas[[*ms.CLAVES_HORA, "ra_p50", "ra_lo", "ra_hi"]], on=ms.CLAVES_HORA, how="inner")


def composicion_con_ruta_activa(modelos: dict, x_pru: pd.DataFrame, bandas: dict, c: str) -> dict:
    """Análisis adicional (no previsto en el protocolo; se agregó después de ver que la banda de B2 se rompe con el
    Carnaval): la banda compuesta con errores REALES del modelo de ruta activo de 2025 sobre las subidas reales de la
    prueba de 2023, promedio de REPLICAS_COMPOSICION asignaciones al azar. Supone independencia entre ambos errores."""
    errores = errores_ruta_activo()
    seg, sen, ruta = [], [], []
    for k in range(REPLICAS_COMPOSICION):
        xr = con_errores_ruta(x_pru, errores, ms.SEMILLA + k)
        cov = coberturas(xr, ms.fracciones_previstas(modelos[c], xr), bandas[c], "ra_p50", "ra_lo", "ra_hi")
        seg.append(cov["segmento"]["cobertura_pct"])
        sen.append(cov["sentido"]["cobertura_pct"])
        h = xr.drop_duplicates(ms.CLAVES_HORA)
        ruta.append(cobertura(h["total"], h["ra_lo"], h["ra_hi"])["cobertura_pct"])
    return {"modelo_ruta": str(errores["model_id"].iloc[0]),
            "periodo_errores": f"{PERIODO_RUTA_ACTIVO[0]} a {PERIODO_RUTA_ACTIVO[1]}", "replicas": REPLICAS_COMPOSICION,
            "cobertura_ruta_pct": round(float(np.mean(ruta)), 2),
            "cobertura_segmento_pct": round(float(np.mean(seg)), 2),
            "cobertura_segmento_rango_pct": [round(float(min(seg)), 2), round(float(max(seg)), 2)],
            "cobertura_sentido_pct": round(float(np.mean(sen)), 2),
            "cobertura_sentido_rango_pct": [round(float(min(sen)), 2), round(float(max(sen)), 2)],
            "nota": "análisis adicional, no previsto en el protocolo: compone errores reales de la ruta de 2025 "
                    "con errores reales del reparto de 2023 (independencia supuesta)"}


# ----------------------------------------------------------------------------------------------- sesgo por condición
def condiciones(x: pd.DataFrame) -> dict[str, np.ndarray]:
    return {"franja": np.asarray(inferencia.franja_de(x["hora"].to_numpy())),
            "tipo_dia": x["tipo_dia"].map(TIPOS_DIA).to_numpy(),
            "carnaval": np.where(x["carnaval"].to_numpy() == 1, "carnaval", "sin_carnaval")}


def _sesgo_sentidos(d: pd.DataFrame) -> dict:
    sent = d.groupby(CLAVES_SENTIDO, as_index=False)[["y", "p"]].sum()
    return {s: {"sesgo_pct": _sesgo(g["y"], g["p"]), "wape_hora": _wape(g["y"], g["p"]), "subidas": int(g["y"].sum())}
            for s, g in sent.groupby("sentido")}


def sesgo_por_condicion(x: pd.DataFrame, f, total: str) -> dict:
    """§9.3 «sesgo por … sentido, segmento y condición operacional»: por franja, tipo de día y Carnaval."""
    d = x.assign(p=x[total].to_numpy(float) * np.asarray(f, float))
    out = {}
    for nombre, etiqueta in condiciones(d).items():
        for valor in sorted(set(etiqueta)):
            g = d[etiqueta == valor]
            out[f"{nombre}={valor}"] = {"wape_segmento_hora": _wape(g["y"], g["p"]),
                                        "sesgo_pct": _sesgo(g["y"], g["p"]), "por_sentido": _sesgo_sentidos(g),
                                        "segmentos": _sesgo_segmentos(g)}
    return out


def sesgo_ruta_2025() -> dict:
    """Sesgo del pronóstico de la ruta (modelo activo) medido fuera de muestra en nov-dic 2025, por franja y tipo de
    día (docs/evidencias/modelo/evaluacion_modelo.json, clave prueba_reservada, modelo «cand»)."""
    ev = json.loads((RAIZ / "docs" / "evidencias" / "modelo" / "evaluacion_modelo.json").read_text(encoding="utf-8"))
    pr = ev["prueba_reservada"]
    out = {f"franja={k}": v["cand"]["sesgo_pct"] for k, v in pr["por_franja"].items()}
    out.update({f"tipo_dia={k}": pr["por_condicion"][k]["cand"]["sesgo_pct"] for k in TIPOS_DIA.values()
                if k in pr["por_condicion"]})
    return {"model_id": pr["modelos"]["activo"], "periodo": f"{pr['modelos']['desde']} a {pr['modelos']['hasta']}",
            "sesgo_pct": out}


def componer(reparto: dict, ruta: dict) -> dict:
    """(1 + sesgo de la ruta) · (1 + sesgo del reparto) − 1 por condición y sentido (composición declarada)."""
    out = {}
    for cond, r in ruta["sesgo_pct"].items():
        if cond not in reparto or r is None:
            continue
        out[cond] = {"sesgo_ruta_2025_pct": r, **{
            s: {"sesgo_reparto_pct": v["sesgo_pct"],
                "sesgo_compuesto_pct": round(((1 + r / 100) * (1 + v["sesgo_pct"] / 100) - 1) * 100, 2)}
            for s, v in reparto[cond]["por_sentido"].items() if v["sesgo_pct"] is not None}}
    return out


# ----------------------------------------------------------------------------------------------- protocolo
def ajustar_candidatos(x_ent: pd.DataFrame) -> dict:
    t0 = time.perf_counter()
    modelos = {c: {"tipo": t, **ms.ajustar(t, x_ent)} for c, t in CANDIDATOS.items()}
    print(f"candidatos ajustados en {time.perf_counter() - t0:.1f} s")
    return modelos


def fracciones(modelos: dict, x: pd.DataFrame) -> dict:
    return {c: ms.fracciones_previstas(m, x) for c, m in modelos.items()}


def validar(modelos: dict, x_val: pd.DataFrame) -> tuple[dict, dict, dict]:
    f = fracciones(modelos, x_val)
    val = {c: metricas(x_val, f[c]) for c in modelos}
    boot = {c: bootstrap_dias(x_val, f[c], f["B0"], ms.REGLA_ELECCION["bootstrap_replicas"],
                              ms.REGLA_ELECCION["semilla"]) for c in modelos if c != "B0"}
    return f, val, {"metricas": val, "bootstrap": boot, "eleccion": elegir(val, boot)}


def evaluar_prueba(modelos: dict, x_pru: pd.DataFrame, bandas: dict, b2: pd.DataFrame, q_b2: dict,
                   elegido: str) -> dict:
    """La prueba, una sola vez: métricas de todos, banda (total real y B2) y sesgo por condición del elegido y B0."""
    f = fracciones(modelos, x_pru)
    xb = con_b2(x_pru, b2, q_b2)
    fb = fracciones(modelos, xb)
    ruta_2025 = sesgo_ruta_2025()
    horas = xb.drop_duplicates(ms.CLAVES_HORA)
    out = {"metricas": {c: metricas(x_pru, f[c]) for c in modelos},
           "metricas_punta_a_punta_b2": {c: metricas(xb, fb[c], total="b2") for c in modelos},
           "cobertura_ruta_b2": cobertura(horas["total"], horas["b2_lo"], horas["b2_hi"]),
           "cobertura_ruta_b2_por_condicion": cobertura_ruta(horas, "b2", "b2_lo", "b2_hi"),
           "sesgo_ruta_2025": ruta_2025,
           "composicion_con_ruta_activa": composicion_con_ruta_activa(modelos, x_pru, bandas, elegido)}
    for c in dict.fromkeys(["B0", elegido]):
        out[c] = {"banda_total_real": coberturas(x_pru, f[c], bandas[c], "total", "total", "total"),
                  "banda_punta_a_punta_b2": coberturas(xb, fb[c], bandas[c], "b2", "b2_lo", "b2_hi"),
                  "sesgo_por_condicion": sesgo_por_condicion(x_pru, f[c], "total"),
                  "sesgo_por_condicion_b2": sesgo_por_condicion(xb, fb[c], "b2")}
        out[c]["sesgo_compuesto_con_ruta_2025"] = componer(out[c]["sesgo_por_condicion"], ruta_2025)
    return out


def activar_elegido(eleccion: dict, prueba: dict | None) -> tuple[str, str]:
    """Salvaguarda declarada: si el elegido es peor que B0 en la prueba, sigue B0."""
    elegido = eleccion["elegido"]
    if elegido == "B0":
        return "B0", "ningún candidato cumple la regla en la validación: sigue el reparto fijo"
    if prueba is not None:
        w = prueba["metricas"]
        if w[elegido]["wape_segmento_hora"] > w["B0"]["wape_segmento_hora"]:
            return "B0", f"{elegido} ganó en la validación pero es peor que B0 en la prueba (salvaguarda): sigue B0"
    return elegido, f"{elegido} cumple la regla en la validación y no empeora a B0 en la prueba"


# ----------------------------------------------------------------------------------------------- producción
def model_id_de(tipo: str, fin: date) -> str:
    return f"seg_{tipo}_{fin:%Y%m%d}" + ("" if tipo == ms.TIPO_REPARTO else f"_s{ms.SEMILLA}")


def objetivo_inferencia(segs: pd.DataFrame) -> pd.DataFrame:
    """Todas las celdas (ruta, tipo de día, hora de servicio) que puede pedir la inferencia."""
    return pd.DataFrame([(r, td, h) for r in sorted(segs["ruta"].unique()) for td in TIPOS_DIA
                         for h in datos.HORAS_SERVICIO], columns=ms.CLAVES_CELDA)


def codigo_sha256() -> dict:
    """SHA-256 (con LF) del código del modelo y del script; el de modelo_segmentos.py también sin su docstring (lo
    que define el preprocesamiento: la documentación puede cambiar sin cambiar la huella)."""
    modulo = RAIZ / "app" / "servicios" / "modelo_segmentos.py"
    archivos = {"modelo_segmentos.py": modulo, "entrenar_segmentos.py": Path(__file__).resolve()}
    out = {k: inferencia.sha256_codigo(v.read_text(encoding="utf-8")) for k, v in archivos.items()}
    out["modelo_segmentos.py_sin_docstring"] = inferencia.sha256_codigo(
        inferencia.sin_docstring_de_modulo(modulo.read_text(encoding="utf-8")))
    return out


def _resumen_metricas(m: dict | None) -> dict | None:
    if not m:
        return None
    claves = ("wape_segmento_hora", "wape_sentido_hora", "mae_segmento_hora", "sesgo_pct", "sesgo_abs_mediano_pct")
    return {k: m.get(k) for k in claves}


def manifiesto_de(c: str, tipo: str, ctx: dict) -> dict:
    """Manifiesto (§9.3 «registrar semilla, versión de datos, hiperparámetros, código y artefacto»)."""
    prueba = ctx.get("prueba") or {}
    banda_p = (prueba.get(c) or {}).get("banda_total_real", {})
    banda_b2 = (prueba.get(c) or {}).get("banda_punta_a_punta_b2", {})
    activa = prueba.get("composicion_con_ruta_activa") or {}
    es_elegido = c == ctx["eleccion"]["elegido"]
    return {
        "model_id": model_id_de(tipo, ctx["fin"]), "tipo": tipo, "candidato": c,
        "algoritmo": ms.DESCRIPCIONES[tipo],
        "periodo_datos": f"{ctx['inicio']} a {ctx['fin']}",
        "entrenado_con": "los 56 días con datos (reentrenado con la configuración elegida en la validación)",
        "semilla": ms.SEMILLA, "hiperparametros": None if tipo == ms.TIPO_REPARTO else ms.HIPER_DEFECTO,
        "hiperparametros_sentido": ms.HIPER_SENTIDO if tipo == ms.TIPO_JERARQUICO else None,
        "variables": ms.COLUMNAS, "variables_sentido": ms.COLUMNAS_SENTIDO if tipo == ms.TIPO_JERARQUICO else None,
        "min_subidas": ms.MIN_SUBIDAS, "dias_pliegue": ms.DIAS_PLIEGUE,
        "particion_evaluacion": {k: f"{a} a {b}" for k, (a, b) in ms.PARTICION.items()},
        "regla_eleccion": ms.REGLA_ELECCION, "eleccion": ctx["eleccion"],
        "metricas_validacion": _resumen_metricas(ctx["validacion"]["metricas"].get(c)),
        "metricas_prueba": _resumen_metricas((prueba.get("metricas") or {}).get(c)),
        "banda": {"metodo": ms.METODO_BANDA, "ajustada_con": "validación {} a {}".format(*ms.PARTICION["validacion"]),
                  "cobertura_prueba_pct": (banda_p.get("segmento") or {}).get("cobertura_pct"),
                  "cobertura_prueba_sentido_pct": (banda_p.get("sentido") or {}).get("cobertura_pct"),
                  "cobertura_prueba_b2_pct": (banda_b2.get("segmento") or {}).get("cobertura_pct"),
                  "cobertura_prueba_b2_sentido_pct": (banda_b2.get("sentido") or {}).get("cobertura_pct"),
                  "cobertura_compuesta_ruta_activa_pct": activa.get("cobertura_segmento_pct") if es_elegido else None,
                  "cobertura_compuesta_ruta_activa_sentido_pct":
                      activa.get("cobertura_sentido_pct") if es_elegido else None},
        "version_datos": ctx["version_datos"], "codigo_sha256": codigo_sha256(),
        "codigo_normalizacion": inferencia.NORMALIZACION_CODIGO,
        "creado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "evaluacion": "docs/evidencias/modelo/segmentos_modelo.md"}


def produccion(celdas: pd.DataFrame, segs: pd.DataFrame, cal: pd.DataFrame, activo: str, motivo: str, ctx: dict,
               dir_modelos: Path | None) -> list[dict]:
    """Reentrena B0 y el activo con los 56 días y los registra (B0 queda como línea base si no es el activo)."""
    x_todo = preparar_ajuste(celdas, segs, cal, ctx["inicio"])
    cod = ms.fracciones_base(celdas, segs, objetivo=objetivo_inferencia(segs))
    guardados = []
    for c in dict.fromkeys(["B0", activo]):
        tipo = CANDIDATOS[c]
        contenido = {"tipo": tipo, **ms.ajustar(tipo, x_todo), "codificacion": cod, "segmentos": segs,
                     "banda": ctx["bandas"][c], "columnas": ms.COLUMNAS, "columnas_sentido": ms.COLUMNAS_SENTIDO,
                     "version_variables": ms.VERSION_VARIABLES}
        man = ms.guardar(contenido, manifiesto_de(c, tipo, ctx), dir_modelos)
        ms.registrar(man, activar=(c == activo), motivo=motivo, dir_modelos=dir_modelos)
        guardados.append({"model_id": man["model_id"], "sha256": man["sha256"], "activo": c == activo})
    return guardados


# ----------------------------------------------------------------------------------------------- evidencia
def _celda(v) -> str:
    return "—" if v is None else (f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                                  if isinstance(v, float) else str(v))


def _tabla(filas: list[list], cabecera: list[str]) -> list[str]:
    return ["| " + " | ".join(cabecera) + " |", "|" + "---|" * len(cabecera)] + [
        "| " + " | ".join(_celda(v) for v in f) + " |" for f in filas]


def _tabla_metricas(m: dict, boot: dict | None = None) -> list[str]:
    filas = []
    for c, v in m.items():
        b = (boot or {}).get(c)
        filas.append([c, CANDIDATOS[c], v["wape_segmento_hora"], v["wape_sentido_hora"], v["mae_segmento_hora"],
                      v.get("sesgo_abs_mediano_pct"), v.get("sesgo_abs_p90_pct"),
                      "—" if b is None else f"{_celda(b['diferencia_pp'])} [{_celda(b['ic95_pp'][0])}; "
                                            f"{_celda(b['ic95_pp'][1])}]"])
    return _tabla(filas, ["Modelo", "Tipo", "WAPE segmento-hora %", "WAPE sentido-hora %", "MAE segmento-hora",
                          "Sesgo absoluto mediano por segmento %", "Sesgo absoluto p90 por segmento %",
                          "Δ WAPE vs B0 (IC95, pp)"])


def _tabla_bandas(prueba: dict, c: str) -> list[str]:
    filas = []
    for etiqueta, clave in (("Total real de la ruta (solo reparto)", "banda_total_real"),
                            ("De punta a punta con B2 (ruta fuera de muestra)", "banda_punta_a_punta_b2")):
        for nivel in ("segmento", "sentido"):
            v = prueba[c][clave][nivel]
            filas.append([etiqueta, nivel, v["n"], v["cobertura_pct"], v["bajo_p10_pct"], v["sobre_p90_pct"],
                          v["ancho_medio"], v["y_medio"]])
    return _tabla(filas, ["Pronóstico de la ruta", "Nivel", "Filas", "Cobertura %", "Bajo P10 %", "Sobre P90 %",
                          "Ancho medio", "Subidas medias"])


def _tabla_condiciones(prueba: dict, c: str) -> list[str]:
    filas = []
    comp = prueba[c]["sesgo_compuesto_con_ruta_2025"]
    for cond, v in prueba[c]["sesgo_por_condicion"].items():
        s = v["por_sentido"]
        b2 = prueba[c]["sesgo_por_condicion_b2"].get(cond, {}).get("por_sentido", {})
        filas.append([cond, v["wape_segmento_hora"], (s.get("ida") or {}).get("sesgo_pct"),
                      (s.get("regreso") or {}).get("sesgo_pct"), v["segmentos"].get("sesgo_abs_mediano_pct"),
                      (b2.get("ida") or {}).get("sesgo_pct"), (b2.get("regreso") or {}).get("sesgo_pct"),
                      (comp.get(cond) or {}).get("sesgo_ruta_2025_pct"),
                      ((comp.get(cond) or {}).get("ida") or {}).get("sesgo_compuesto_pct"),
                      ((comp.get(cond) or {}).get("regreso") or {}).get("sesgo_compuesto_pct")])
    return _tabla(filas, ["Condición", "WAPE segmento-hora %", "Sesgo ida %", "Sesgo regreso %",
                          "Sesgo absoluto mediano por segmento %", "Ida con B2 %", "Regreso con B2 %",
                          "Sesgo ruta 2025 %", "Ida compuesto %", "Regreso compuesto %"])


def _texto_bandas_ruta(pr: dict) -> list[str]:
    b2, ra = pr["cobertura_ruta_b2_por_condicion"], pr["composicion_con_ruta_activa"]
    seg, sen = ra["cobertura_segmento_rango_pct"], ra["cobertura_sentido_rango_pct"]
    return [f"La banda de la ruta B2 (conformal relativa ajustada en la validación) cubre "
            f"{_celda(b2['global']['cobertura_pct'])} % de las {b2['global']['n']} horas de la prueba "
            f"({_celda(b2.get('carnaval=carnaval'))} % en Carnaval y {_celda(b2.get('carnaval=sin_carnaval'))} % "
            "fuera de él: B2 es la misma hora de la semana anterior, así que sobreestima los días de Carnaval y "
            "subestima la semana siguiente). La banda compuesta hereda ese defecto de la ruta; la del reparto sola, "
            "con el total real, es la de las dos primeras filas de la tabla.", "",
            "**Análisis adicional (no previsto en el protocolo).** Con errores reales del modelo de ruta activo "
            f"({ra['modelo_ruta']}, banda calibrada vigente, fuera de muestra {ra['periodo_errores']}) asignados al "
            f"azar a cada hora de la prueba dentro del mismo estrato (ruta, tipo de día, hora), {ra['replicas']} "
            f"réplicas: la banda de la ruta cubre {_celda(ra['cobertura_ruta_pct'])} % y la compuesta cubre "
            f"{_celda(ra['cobertura_segmento_pct'])} % por segmento (rango {_celda(seg[0])} a {_celda(seg[1])}) y "
            f"{_celda(ra['cobertura_sentido_pct'])} % por sentido (rango {_celda(sen[0])} a {_celda(sen[1])}). "
            "Supone independencia entre el error de la ruta y el del reparto."]


def markdown(ev: dict) -> str:
    val, act = ev["validacion"], ev["activacion"]
    lineas = ["# Modelo por segmento y sentido: resultados", "",
              "Generado por `scripts/entrenar_segmentos.py` con el protocolo de `segmentos_protocolo.md` (fijado antes "
              "de mirar la prueba). Detalle completo en `segmentos_modelo.json`.", "",
              f"Datos: `{ev['datos']['archivo']}` ({ev['datos']['filas']} filas, {ev['datos']['subidas']} subidas, "
              f"SHA-256 `{ev['datos']['sha256'][:16]}…`). Partición: "
              + "; ".join(f"{k} {v}" for k, v in ev["particion"].items()) + ".", "",
              "## Validación (elige el modelo)", "", *_tabla_metricas(val["metricas"], val["bootstrap"]), "",
              f"Regla: {val['eleccion']['regla']}", "",
              f"**Elegido en la validación: {val['eleccion']['elegido']}. Activo: {act['activo']}** ({act['motivo']}).",
              ""]
    if ev.get("prueba"):
        pr, c = ev["prueba"], act["activo_candidato"]
        lineas += ["## Prueba (una sola vez)", "", "Con el total real de la ruta (error del reparto):", "",
                   *_tabla_metricas(pr["metricas"]), "",
                   "De punta a punta con B2 (pronóstico de ruta de la misma hora hace 7 días, fuera de muestra):", "",
                   *_tabla_metricas(pr["metricas_punta_a_punta_b2"]), "",
                   f"## Banda P10-P90 del activo ({c}) en la prueba", "", *_tabla_bandas(pr, c), "",
                   *_texto_bandas_ruta(pr), "",
                   f"## Sesgo por sentido, segmento y condición del activo ({c}) en la prueba (§9.3)", "",
                   *_tabla_condiciones(pr, c), "",
                   "Sesgo = Σ(p − y)/Σ y. «Con B2»: de punta a punta con el pronóstico B2 de la ruta. «Compuesto»: "
                   "(1 + sesgo de la ruta) · (1 + sesgo del reparto) − 1, con el sesgo del modelo de ruta activo "
                   f"({pr['sesgo_ruta_2025']['model_id']}) medido fuera de muestra en "
                   f"{pr['sesgo_ruta_2025']['periodo']} por franja y tipo de día; es una composición declarada, no "
                   "una medición conjunta (no hay subidas por segmento en 2025).", ""]
    lineas += ["## Limitaciones", "", *[f"- {x}" for x in ev["limitaciones"]], ""]
    return "\n".join(lineas)


LIMITACIONES = [
    "Las subidas por segmento solo existen del 2023-01-01 al 2023-02-27 (los triggers de segmentación no se volvieron "
    "a ejecutar): el modelo se aplica a fechas posteriores sin poder medir su error en ellas.",
    "El sentido es una aproximación geométrica (supuesto S9): mitad de la longitud acumulada del ciclo.",
    "No hay pronósticos fuera de muestra del modelo de ruta activo para 2023: la cobertura de punta a punta se midió "
    "con B2 y la composición con el sesgo de la ruta usa el medido en 2025.",
    "El Carnaval (18 a 21 de febrero) solo está en la prueba: ningún modelo lo vio al entrenar."]


# ----------------------------------------------------------------------------------------------- principal
def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--celdas", type=Path, default=None, help="por omisión datos/" + ARCHIVO_CELDAS)
    p.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "modelo")
    p.add_argument("--dir-modelos", type=Path, default=None, help="por omisión datos/modelos/segmentos")
    p.add_argument("--sin-prueba", action="store_true", help="solo entrenamiento y validación; no guarda nada")
    a = p.parse_args(argv)
    t0 = time.perf_counter()
    archivo = a.celdas or datos.carpeta_datos() / ARCHIVO_CELDAS
    celdas = cargar_celdas(archivo)
    segs = segmentos_de(celdas)
    cal = ms.calendario_serie(min(celdas["fecha"]), max(celdas["fecha"]))
    inicio = ms.PARTICION["entrenamiento"][0]
    ent = ventana(celdas, "entrenamiento")
    x_ent = preparar_ajuste(ent, segs, cal, inicio)
    x_val = preparar_evaluacion(ent, ventana(celdas, "validacion"), segs, cal)
    modelos = ajustar_candidatos(x_ent)
    f_val, _, validacion = validar(modelos, x_val)
    elegido = validacion["eleccion"]["elegido"]
    bandas = {c: calibrar(x_val, f_val[c]) for c in dict.fromkeys(["B0", elegido])}
    b2 = pronostico_b2(totales_ruta(celdas))
    desde_v, hasta_v = ms.PARTICION["validacion"]
    q_b2 = banda_b2(b2[(b2["fecha"] >= desde_v) & (b2["fecha"] <= hasta_v)])
    ev = {"protocolo": "docs/evidencias/modelo/segmentos_protocolo.md",
          "particion": {k: f"{x} a {y}" for k, (x, y) in ms.PARTICION.items()},
          "datos": {"archivo": f"datos/{archivo.name}", "sha256": huella(archivo), "filas": int(len(celdas)),
                    "subidas": int(celdas["subidas"].sum()), "segmentos_por_ruta":
                    segs.groupby("ruta").size().to_dict(), "filas_por_ventana": {
                        "entrenamiento": int(len(x_ent)), "validacion": int(len(x_val))}},
          "variables": ms.COLUMNAS, "hiperparametros": ms.HIPER_DEFECTO, "validacion": validacion,
          "bandas": bandas, "banda_b2": q_b2, "limitaciones": LIMITACIONES}
    if a.sin_prueba:
        print(json.dumps({c: _resumen_metricas(m) for c, m in validacion["metricas"].items()}, ensure_ascii=False))
        print(json.dumps(validacion["eleccion"], ensure_ascii=False))
        return ev
    x_pru = preparar_evaluacion(ent, ventana(celdas, "prueba"), segs, cal)
    ev["datos"]["filas_por_ventana"]["prueba"] = int(len(x_pru))
    ev["prueba"] = evaluar_prueba(modelos, x_pru, bandas, b2, q_b2, elegido)
    activo, motivo = activar_elegido(validacion["eleccion"], ev["prueba"])
    ev["activacion"] = {"activo_candidato": activo, "activo": model_id_de(CANDIDATOS[activo], max(celdas["fecha"])),
                        "motivo": motivo}
    ctx = {"inicio": min(celdas["fecha"]), "fin": max(celdas["fecha"]), "eleccion": validacion["eleccion"],
           "validacion": validacion, "prueba": ev["prueba"], "bandas": bandas,
           "version_datos": {k: ev["datos"][k] for k in ("archivo", "sha256", "filas", "subidas")}}
    ev["produccion"] = produccion(celdas, segs, cal, activo, motivo, ctx, a.dir_modelos)
    ev["segundos"] = round(time.perf_counter() - t0, 1)
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "segmentos_modelo.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1, default=str),
                                                    encoding="utf-8")
    (a.salida / "segmentos_modelo.md").write_text(markdown(ev), encoding="utf-8")
    print(json.dumps({"activo": ev["activacion"], "produccion": ev["produccion"]}, ensure_ascii=False))
    return ev


if __name__ == "__main__":
    main()
