"""Evaluación completa del modelo de demanda (especificación §9.3, criterio «Modelo predictivo»).

Con el MISMO protocolo para todos los modelos (mismas filas: horas con dato real y regla manual disponible):
1. Prueba reservada (días posteriores a la validación del corte 2025-08-31, nov-dic 2025): modelo activo, modelo fv1,
   B1 (regla manual de 8 semanas) y B2 (última semana).
   - MAE, RMSE, WAPE, sMAPE y sesgo: global, por ruta, por franja (04-05, 06-08, 09-16, 17-19, 20), pico frente a
     valle y por condición (laboral, sábado, domingo/festivo, festivo, víspera, día posterior, vacaciones, Navidad,
     Semana Santa, Carnaval, novedad vial, lluvia >= 5 y >= 20 mm, seco). La lluvia es observada y diaria: solo es
     condición de análisis, nunca variable del pronóstico (sería fuga). Se marca n < 100 como «pocas filas».
   - Sesgo por ruta y condición.
   - Bootstrap por bloques móviles de 7 días (B = 2000, semilla 42) del WAPE y de las diferencias frente a B1 y fv1.
   - Cobertura P10-P90 (y % bajo P10 / sobre P90, ancho medio) con la banda del modelo, con la calibración v1
     (conformal móvil por ruta) y con la calibración VIGENTE del modelo (v2: el archivo calibracion_v2.json que la API
     verifica por SHA-256 y aplica en cada predicción), lado a lado.
2. Robustez con modelos congelados un año (fv1 y fv2, semilla 42): <= 2023-12-31 -> 2024 y <= 2024-12-31 -> 2025,
   con WAPE por mes, cobertura de la banda del modelo y calibrada, y fv1 frente a fv2 en las horas afectadas.

Uso:  python scripts/evaluar_modelo.py [--modelo ID] [--fv1 ID] [--salida docs/evidencias/modelo] [--sin-robustez]
Escribe evaluacion_modelo.json y evaluacion_modelo.md y guarda un resumen en manifest["evaluacion"] del modelo.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import datos, inferencia, variables  # noqa: E402

B_BOOT, BLOQUE, SEMILLA = 2000, 7, 42
ZONA = ZoneInfo("America/Bogota")
POCAS_FILAS = 100


def met(y, p) -> dict:
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    if len(y) == 0:
        return {"n": 0}
    e = p - y
    tot = y.sum()
    return {
        "n": int(len(y)),
        "mae": round(float(np.abs(e).mean()), 2),
        "rmse": round(float(np.sqrt((e**2).mean())), 2),
        "wape": round(float(np.abs(e).sum() / tot * 100), 2) if tot > 0 else None,
        "smape": round(float(inferencia.smape(y, p)), 2),
        "sesgo_pct": round(float(e.sum() / tot * 100), 2) if tot > 0 else None,
        **({"pocas_filas": True} if len(y) < POCAS_FILAS else {}),
    }


def cobertura(y, lo, hi) -> dict:
    y, lo, hi = (np.asarray(v, float) for v in (y, lo, hi))
    return {
        "cobertura_pct": round(float(((y >= lo) & (y <= hi)).mean() * 100), 2),
        "bajo_p10_pct": round(float((y < lo).mean() * 100), 2),
        "sobre_p90_pct": round(float((y > hi).mean() * 100), 2),
        "ancho_mediano_rel_pct": round(float(np.median((hi - lo) / np.maximum(1.0, (hi + lo) / 2)) * 100), 1),
        "ancho_medio": round(float((hi - lo).mean()), 1),
    }


def banda_vigente(te: pd.DataFrame, modelo: dict, c: str) -> dict | None:
    """Cobertura con la calibración versionada del modelo (la que usa la API), o None si el modelo no la trae."""
    cal = modelo.get("calibracion")
    if not cal:
        return None
    q = inferencia.q_calibracion(cal, te)[0]
    lo_v, hi_v = inferencia.aplicar_conformal(te[c], te[f"{c}_lo"], te[f"{c}_hi"], q)
    return {
        "calibracion": {"version": cal["version"], "nombre": cal["nombre"], "archivo": cal["archivo"],
                        "sha256": cal["sha256"], "ajustado_con": cal["ajustado_con"]},
        "banda_calibrada_vigente": cobertura(te["y"], lo_v, hi_v),
        "por_ruta_vigente": {
            rr: cobertura(g["y"], lo_v[g.index.map(te.index.get_loc)], hi_v[g.index.map(te.index.get_loc)])[
                "cobertura_pct"
            ]
            for rr, g in te.groupby("ruta")
        },
    }


def bootstrap(df: pd.DataFrame, cols: list[str], bases: list[str]) -> dict:
    """Bootstrap por bloques móviles de días (circular): IC95 del WAPE y de la diferencia frente a cada base."""
    g = (
        df.assign(**{f"ae_{c}": (df[c] - df["y"]).abs() for c in cols})
        .groupby("fecha")[["y"] + [f"ae_{c}" for c in cols]]
        .sum()
    )
    n = len(g)
    rng = np.random.default_rng(SEMILLA)
    nb = int(np.ceil(n / BLOQUE))
    inicios = rng.integers(0, n, size=(B_BOOT, nb))
    idx = ((inicios[:, :, None] + np.arange(BLOQUE)[None, None, :]) % n).reshape(B_BOOT, -1)[:, :n]
    y = g["y"].to_numpy()[idx].sum(1)
    w = {c: g[f"ae_{c}"].to_numpy()[idx].sum(1) / y * 100 for c in cols}
    out = {"dias": n, "bloque_dias": BLOQUE, "B": B_BOOT, "semilla": SEMILLA}
    for c in cols:
        out[c] = {"ic95": [round(float(np.quantile(w[c], 0.025)), 2), round(float(np.quantile(w[c], 0.975)), 2)]}
    for b in bases:
        for c in cols:
            if c != b:
                d = w[c] - w[b]
                out[f"{c}_menos_{b}"] = {
                    "ic95": [round(float(np.quantile(d, 0.025)), 2), round(float(np.quantile(d, 0.975)), 2)],
                    "p_mejora": round(float((d < 0).mean()), 4),
                }
    return out


def tabla_base() -> pd.DataFrame:
    t = inferencia._filas_utiles(inferencia.tabla_variables()).reset_index(drop=True)
    clima = datos.clima_diario()
    if clima is not None:
        t = t.merge(clima[["fecha", "precipitacion_4_21h_mm"]], on="fecha", how="left")
    else:
        t["precipitacion_4_21h_mm"] = np.nan
    t["y"] = t["pasajeros"].astype(float)
    t["b1"] = t["b8"]
    t["b2"] = t["lag7"].fillna(t["b8"])
    t["franja"] = inferencia.franja_de(t["hora"])
    return t


def condiciones(df: pd.DataFrame) -> dict[str, pd.Series]:
    lluvia = df["precipitacion_4_21h_mm"]
    return {
        "laboral": df["tipo_dia"] == 0,
        "sabado": df["tipo_dia"] == 1,
        "domingo_festivo": df["tipo_dia"] == 2,
        "festivo": df["festivo"] == 1,
        "vispera_festivo": df["vispera_festivo"] == 1,
        "post_festivo": df["post_festivo"] == 1,
        "vacaciones": df["vacaciones"] == 1,
        "navidad": df["navidad"] == 1,
        "semana_santa": df["semana_santa"] == 1,
        "carnaval": df["carnaval"] == 1,
        "novedad_vial": df["nov_impacto"] > 0,
        "lluvia_5mm": lluvia >= 5,
        "lluvia_20mm": lluvia >= 20,
        "seco": lluvia < 1,
    }


def resumen(df: pd.DataFrame, modelos: list[str]) -> dict:
    """Métricas de cada columna de pronóstico en `modelos` sobre las mismas filas."""
    out: dict = {"global": {m: met(df["y"], df[m]) for m in modelos}}
    out["por_ruta"] = {r: {m: met(g["y"], g[m]) for m in modelos} for r, g in df.groupby("ruta")}
    out["por_franja"] = {f: {m: met(g["y"], g[m]) for m in modelos} for f, g in df.groupby("franja")}
    pico = df["hora"].isin(datos.HORAS_PICO)
    out["pico_valle"] = {
        "pico": {m: met(df.loc[pico, "y"], df.loc[pico, m]) for m in modelos},
        "valle": {m: met(df.loc[~pico, "y"], df.loc[~pico, m]) for m in modelos},
    }
    conds = condiciones(df)
    out["por_condicion"] = {
        k: {m: met(df.loc[c.fillna(False), "y"], df.loc[c.fillna(False), m]) for m in modelos}
        for k, c in conds.items()
        if c.fillna(False).sum() > 0
    }
    out["sesgo_ruta_condicion"] = {}
    for r, g in df.groupby("ruta"):
        for k, c in condiciones(g).items():
            sel = g[c.fillna(False)]
            if len(sel):
                out["sesgo_ruta_condicion"][f"{r} | {k}"] = {
                    "n": len(sel),
                    **{m: met(sel["y"], sel[m])["sesgo_pct"] for m in modelos},
                }
    return out


def conformal(
    df: pd.DataFrame, puntajes: pd.DataFrame, p: str, lo: str, hi: str
) -> tuple[np.ndarray, np.ndarray, float]:
    claves = list(dict.fromkeys(zip(df["ruta"], df["fecha"], strict=False)))
    qs = inferencia.cuantiles_conformal_movil(puntajes, claves)
    q = np.array(
        [
            qs[(r, f)]["q"] if qs[(r, f)]["q"] is not None else np.nan
            for r, f in zip(df["ruta"], df["fecha"], strict=False)
        ],
        dtype=float,
    )
    ok = ~np.isnan(q)
    pp, ll, hh = df[p].to_numpy(float), df[lo].to_numpy(float), df[hi].to_numpy(float)
    esc = np.maximum(pp, 1.0)
    lo_c = np.where(ok, np.clip(np.minimum(ll - np.nan_to_num(q) * esc, pp), 0, None), ll)
    hi_c = np.where(ok, np.maximum(hh + np.nan_to_num(q) * esc, pp), hh)
    return lo_c, hi_c, float(ok.mean() * 100)


def prueba_reservada(t: pd.DataFrame, activo: str, fv1: str | None) -> dict:
    mod = inferencia.cargar(activo)
    man = mod["manifiesto"]
    desde = date.fromisoformat(man["particion"]["prueba"].split(" a ")[0])
    te = t[t["fecha"] >= desde].copy()
    te["cand"], te["cand_lo"], te["cand_hi"] = inferencia._predecir_filas(mod, te)
    cols, info = ["cand", "b1", "b2"], {"activo": activo, "desde": str(desde), "hasta": str(te["fecha"].max())}
    if fv1:
        m1 = inferencia.cargar(fv1)
        te["fv1"], te["fv1_lo"], te["fv1_hi"] = inferencia._predecir_filas(m1, te)
        cols.insert(1, "fv1")
        info["fv1"] = fv1
    r = {"modelos": info, **resumen(te, cols)}
    r["bootstrap"] = bootstrap(te, cols, ["b1"] + (["fv1"] if fv1 else []))
    r["cobertura"] = {}
    for c, m in (("cand", mod), ("fv1", inferencia.cargar(fv1) if fv1 else None)):
        if m is None:
            continue
        lo_c, hi_c, pct = conformal(te, inferencia._puntajes_conformal(m), c, f"{c}_lo", f"{c}_hi")
        r["cobertura"][c] = {
            "banda_modelo": cobertura(te["y"], te[f"{c}_lo"], te[f"{c}_hi"]),
            "banda_conformal": cobertura(te["y"], lo_c, hi_c),
            "horas_con_ajuste_pct": round(pct, 1),
            "por_ruta_conformal": {
                rr: cobertura(g["y"], lo_c[g.index.map(te.index.get_loc)], hi_c[g.index.map(te.index.get_loc)])[
                    "cobertura_pct"
                ]
                for rr, g in te.groupby("ruta")
            },
            "calibracion_v1": inferencia.CALIBRACION_V1,
        }
        r["cobertura"][c].update(banda_vigente(te, m, c) or {"calibracion": {"version": "v1"}})
    return r


def _ajustar3(tr: pd.DataFrame, version: str):
    hp = dict(inferencia.HIPER_DEFECTO)
    x, y = variables.matriz_x(tr, version), tr["pasajeros"].to_numpy(float)
    return tuple(
        inferencia._modelo_hgb(perd, SEMILLA, hp, q, version=version).fit(x, y)
        for perd, q in (("poisson", None), ("quantile", 0.1), ("quantile", 0.9))
    )


def _pred3(ms, df: pd.DataFrame, version: str):
    x = variables.matriz_x(df, version)
    return inferencia._ordenar(ms[0].predict(x), ms[1].predict(x), ms[2].predict(x))


def robustez(t: pd.DataFrame) -> dict:
    out = {}
    for etq, corte, fin in (
        ("2024", date(2023, 12, 31), date(2024, 12, 31)),
        ("2025", date(2024, 12, 31), date(2025, 12, 31)),
    ):
        tr = t[t["fecha"] <= corte]
        ev = t[(t["fecha"] > corte) & (t["fecha"] <= fin)].copy()
        t0 = time.perf_counter()
        for nombre, version in (("fv1", variables.FV1), ("fv2", variables.FV2)):
            ms = _ajustar3(tr, version)
            ev[nombre], ev[f"{nombre}_lo"], ev[f"{nombre}_hi"] = _pred3(ms, ev, version)
        seg = round(time.perf_counter() - t0, 1)
        r = {
            "entrenado_hasta": str(corte),
            "evaluado": f"{ev['fecha'].min()} a {ev['fecha'].max()}",
            "segundos_entrenar_6_modelos": seg,
        }
        r.update(
            {
                k: v
                for k, v in resumen(ev, ["fv2", "fv1", "b1"]).items()
                if k in ("global", "por_ruta", "pico_valle", "por_franja")
            }
        )
        r["bootstrap"] = bootstrap(ev, ["fv2", "fv1", "b1"], ["fv1", "b1"])
        mes = pd.to_datetime(ev["fecha"]).dt.month
        r["por_mes"] = {}
        r["cobertura"] = {}
        for c in ("fv2", "fv1"):
            pz = pd.DataFrame(
                {
                    "ruta": ev["ruta"],
                    "fecha": ev["fecha"],
                    "s": inferencia.puntajes_conformal(ev[c], ev[f"{c}_lo"], ev[f"{c}_hi"], ev["y"]),
                }
            )
            lo_c, hi_c, pct = conformal(ev, pz, c, f"{c}_lo", f"{c}_hi")
            ev[f"{c}_lo_c"], ev[f"{c}_hi_c"] = lo_c, hi_c
            r["cobertura"][c] = {
                "banda_modelo": cobertura(ev["y"], ev[f"{c}_lo"], ev[f"{c}_hi"]),
                "banda_conformal": cobertura(ev["y"], lo_c, hi_c),
                "horas_con_ajuste_pct": round(pct, 1),
                "por_ruta_conformal": {
                    rr: cobertura(g["y"], g[f"{c}_lo_c"], g[f"{c}_hi_c"])["cobertura_pct"]
                    for rr, g in ev.groupby("ruta")
                },
            }
        for k, g in ev.groupby(mes):
            r["por_mes"][str(k)] = {
                "fv2": met(g["y"], g["fv2"])["wape"],
                "fv1": met(g["y"], g["fv1"])["wape"],
                "b1": met(g["y"], g["b1"])["wape"],
                "cobertura_fv2_modelo": cobertura(g["y"], g["fv2_lo"], g["fv2_hi"])["cobertura_pct"],
                "cobertura_fv2_conformal": cobertura(g["y"], g["fv2_lo_c"], g["fv2_hi_c"])["cobertura_pct"],
            }
        afectadas = {
            "todas": ev["y"].notna(),
            "horas_con_novedad": ev["nov_impacto"] > 0,
            "vispera_festivo": ev["vispera_festivo"] == 1,
            "post_festivo": ev["post_festivo"] == 1,
        }
        r["fv1_vs_fv2_horas_afectadas"] = {
            k: {
                "n": int(m.sum()),
                "fv1": met(ev.loc[m, "y"], ev.loc[m, "fv1"])["wape"],
                "fv2": met(ev.loc[m, "y"], ev.loc[m, "fv2"])["wape"],
                "b1": met(ev.loc[m, "y"], ev.loc[m, "b1"])["wape"],
            }
            for k, m in afectadas.items()
            if m.sum() > 0
        }
        out[etq] = r
    return out


def _fmt(x) -> str:
    return "—" if x is None else f"{x:.2f}".replace(".", ",")


def _fmt1(x) -> str:
    return "—" if x is None else f"{x:.1f}".replace(".", ",")


def markdown(res: dict) -> str:
    pr = res["prueba_reservada"]
    g = pr["global"]
    bs = pr["bootstrap"]
    cols = [c for c in ("cand", "fv1", "b1", "b2") if c in g]
    nombres = {
        "cand": f"activo ({pr['modelos']['activo']})",
        "fv1": f"fv1 ({pr['modelos'].get('fv1')})",
        "b1": "B1 regla manual 8 sem",
        "b2": "B2 última semana",
    }
    lineas = [
        "# Evaluación del modelo de demanda",
        "",
        f"Generado {res['generado_en']} con `scripts/evaluar_modelo.py` (mismo protocolo y mismas filas para todos).",
        "",
        f"## Prueba reservada {pr['modelos']['desde']} a {pr['modelos']['hasta']}",
        "",
        "| Modelo | n | MAE | RMSE | WAPE % | IC95 WAPE (bloques de 7 días) | sMAPE % | Sesgo % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in cols:
        m = g[c]
        ic = bs.get(c, {}).get("ic95", [None, None])
        lineas.append(
            f"| {nombres[c]} | {m['n']} | {_fmt(m['mae'])} | {_fmt(m['rmse'])} | {_fmt(m['wape'])} | "
            f"{_fmt(ic[0])}–{_fmt(ic[1])} | {_fmt(m['smape'])} | {_fmt(m['sesgo_pct'])} |"
        )
    lineas += [
        "",
        "Diferencias de WAPE (puntos porcentuales, IC95 bootstrap; P(mejora) = fracción de réplicas < 0):",
        "",
    ]
    for k, v in bs.items():
        if "_menos_" in k:
            lineas.append(f"- {k}: {_fmt(v['ic95'][0])} a {_fmt(v['ic95'][1])} pp, P(mejora) {v['p_mejora']:.2f}")
    lineas += [
        "",
        "### Por ruta (WAPE %)",
        "",
        "| Ruta | " + " | ".join(nombres[c] for c in cols) + " |",
        "|---" * (len(cols) + 1) + "|",
    ]
    for r, d in pr["por_ruta"].items():
        lineas.append(f"| {r} | " + " | ".join(_fmt(d[c]["wape"]) for c in cols) + " |")
    lineas += [
        "",
        "### Por franja y pico/valle (WAPE % / sesgo % del activo)",
        "",
        "| Franja | n | activo WAPE | activo sesgo | B1 WAPE |",
        "|---|---|---|---|---|",
    ]
    for f, d in list(pr["por_franja"].items()) + list(pr["pico_valle"].items()):
        lineas.append(
            f"| {f} | {d['cand']['n']} | {_fmt(d['cand']['wape'])} | {_fmt(d['cand']['sesgo_pct'])} | "
            f"{_fmt(d['b1']['wape'])} |"
        )
    lineas += [
        "",
        "### Por condición (WAPE %; * = menos de 100 filas)",
        "",
        "| Condición | n | activo | fv1 | B1 | sesgo activo |",
        "|---|---|---|---|---|---|",
    ]
    for k, d in pr["por_condicion"].items():
        marca = "*" if d["cand"].get("pocas_filas") else ""
        lineas.append(
            f"| {k}{marca} | {d['cand']['n']} | {_fmt(d['cand']['wape'])} | "
            f"{_fmt(d.get('fv1', {}).get('wape'))} | {_fmt(d['b1']['wape'])} | "
            f"{_fmt(d['cand']['sesgo_pct'])} |"
        )
    lineas += [
        "",
        "### Cobertura P10-P90 (objetivo 80 %)",
        "",
        "Cobertura % (bajo P10 % / sobre P90 %) y ancho medio P90 - P10 en pasajeros por hora. **v1** = conformal "
        "móvil por ruta (56 días previos); **v2** = calibración versionada del modelo (conformal de Mondrian por "
        "bloque horario ajustado solo con la validación), la que la API aplica hoy en cada predicción.",
        "",
        "| Modelo | Banda del modelo | Calibración v1 | Calibración vigente | Ancho medio: modelo / v1 / vigente |",
        "|---|---|---|---|---|",
    ]
    for c, d in pr["cobertura"].items():
        a, b = d["banda_modelo"], d["banda_conformal"]
        v = d.get("banda_calibrada_vigente")
        version = d["calibracion"]["version"]
        vig = (f"{version}: {_fmt(v['cobertura_pct'])} ({_fmt(v['bajo_p10_pct'])} / {_fmt(v['sobre_p90_pct'])})"
               if v else "v1 (el modelo no trae calibración versionada)")
        lineas.append(
            f"| {nombres[c]} | {_fmt(a['cobertura_pct'])} ({_fmt(a['bajo_p10_pct'])} / {_fmt(a['sobre_p90_pct'])}) | "
            f"{_fmt(b['cobertura_pct'])} ({_fmt(b['bajo_p10_pct'])} / {_fmt(b['sobre_p90_pct'])}) | {vig} | "
            f"{_fmt1(a['ancho_medio'])} / {_fmt1(b['ancho_medio'])} / {_fmt1(v['ancho_medio']) if v else '—'} |"
        )
    vig = pr["cobertura"]["cand"]
    if vig.get("banda_calibrada_vigente"):
        cal = vig["calibracion"]
        lineas += [
            "",
            f"Calibración vigente del activo: {cal['nombre']} ({cal['version']}), archivo `{cal['archivo']}` "
            f"(SHA-256 `{cal['sha256'][:16]}…`, verificado al cargar el modelo), {cal['ajustado_con']}. Cobertura por "
            "ruta con la calibración vigente: "
            + ", ".join(f"{r} {_fmt(x)} %" for r, x in vig["por_ruta_vigente"].items())
            + ". Detalle por hora, ruta y tipo de día: docs/evidencias/modelo/calibracion_condicional.md.",
        ]
    if "robustez" in res:
        lineas += [
            "",
            "## Robustez: modelos congelados un año (semilla 42)",
            "",
            "| Año | fv2 WAPE [IC95] | fv1 WAPE [IC95] | B1 WAPE | fv2 − fv1 IC95 (pp) | cobertura fv2 modelo → "
            "conformal |",
            "|---|---|---|---|---|---|",
        ]
        for etq, r in res["robustez"].items():
            b = r["bootstrap"]
            d = b.get("fv2_menos_fv1", {}).get("ic95", [None, None])
            cb = r["cobertura"]["fv2"]
            lineas.append(
                f"| {etq} | {_fmt(r['global']['fv2']['wape'])} [{_fmt(b['fv2']['ic95'][0])}–"
                f"{_fmt(b['fv2']['ic95'][1])}] | {_fmt(r['global']['fv1']['wape'])} [{_fmt(b['fv1']['ic95'][0])}"
                f"–{_fmt(b['fv1']['ic95'][1])}] | {_fmt(r['global']['b1']['wape'])} | {_fmt(d[0])} a "
                f"{_fmt(d[1])} | {_fmt(cb['banda_modelo']['cobertura_pct'])} → "
                f"{_fmt(cb['banda_conformal']['cobertura_pct'])} |"
            )
        lineas += ["", "Horas afectadas por el contexto (WAPE %, fv1 → fv2):", ""]
        for etq, r in res["robustez"].items():
            for k, v in r["fv1_vs_fv2_horas_afectadas"].items():
                lineas.append(f"- {etq} {k} (n={v['n']}): {_fmt(v['fv1'])} → {_fmt(v['fv2'])} (B1 {_fmt(v['b1'])})")
    lineas += [
        "",
        "Notas: la lluvia (clima_diario) es observada y diaria; aquí solo es condición de análisis. "
        "Las condiciones con menos de 100 filas tienen intervalos amplios.",
        "",
    ]
    return "\n".join(lineas)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Evaluación completa del modelo de demanda")
    ap.add_argument("--modelo", default=None, help="model_id a evaluar (por defecto el activo)")
    ap.add_argument("--fv1", default="hgb_fv1_20250831_s42", help="modelo fv1 de referencia (vacío para omitir)")
    ap.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "modelo")
    ap.add_argument("--sin-robustez", action="store_true")
    a = ap.parse_args()
    t0 = time.perf_counter()
    activo = a.modelo or inferencia.modelo_activo()
    fv1 = a.fv1 or None
    if fv1 == activo:
        fv1 = None
    t = tabla_base()
    res = {
        "generado_en": datetime.now(ZONA).isoformat(timespec="seconds"),
        "protocolo": __doc__.strip().splitlines()[2:6],
    }
    res["prueba_reservada"] = prueba_reservada(t, activo, fv1)
    if not a.sin_robustez:
        res["robustez"] = robustez(t)
    res["segundos"] = round(time.perf_counter() - t0, 1)
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "evaluacion_modelo.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    (a.salida / "evaluacion_modelo.md").write_text(markdown(res), encoding="utf-8")
    # resumen en el manifiesto del modelo evaluado (no cambia el artefacto ni su sha256)
    ruta_man = datos.carpeta_modelos() / activo / "manifest.json"
    if ruta_man.exists():
        man = json.loads(ruta_man.read_text(encoding="utf-8"))
        pr = res["prueba_reservada"]
        man["evaluacion"] = {
            "generado_en": res["generado_en"],
            "evidencia": "docs/evidencias/modelo/evaluacion_modelo.json",
            "prueba_reservada": {
                "desde": pr["modelos"]["desde"],
                "hasta": pr["modelos"]["hasta"],
                "global": pr["global"],
                "bootstrap": pr["bootstrap"],
                "cobertura": pr["cobertura"],
                "calibracion_vigente": pr["cobertura"]["cand"]["calibracion"],
                "por_ruta": pr["por_ruta"],
                "pico_valle": pr["pico_valle"],
            },
            "robustez": {
                k: {"global": v["global"], "cobertura_fv2": v["cobertura"]["fv2"]}
                for k, v in res.get("robustez", {}).items()
            },
        }
        ruta_man.write_text(json.dumps(man, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pr = res["prueba_reservada"]
    print(
        json.dumps(
            {
                "global": {k: v["wape"] for k, v in pr["global"].items()},
                "bootstrap": pr["bootstrap"],
                "cobertura": {
                    k: (v["banda_modelo"]["cobertura_pct"], v["banda_conformal"]["cobertura_pct"],
                        (v.get("banda_calibrada_vigente") or {}).get("cobertura_pct"))
                    for k, v in pr["cobertura"].items()
                },
                "robustez": {
                    k: {m: v["global"][m]["wape"] for m in ("fv2", "fv1", "b1")}
                    for k, v in res.get("robustez", {}).items()
                },
                "segundos": res["segundos"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
