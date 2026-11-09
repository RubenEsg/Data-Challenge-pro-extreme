"""Viabilidad de la recomendación por ruta, hora y tipo de día en 2025, con la condición que la impide (§10.3 último
párrafo, §16 «viabilidad de la recomendación» y §18 «recomendación inviable»).

Dos partes, con el código y los umbrales de producción (headway 2-10 min, espera máxima 5 min, ocupación 65-85 %,
nivel de servicio 0,90) y el pronóstico horario del modelo activo (P10/P50/P90 con h = 60, sin factor intradía):

A. La franja del ciclo diario: la hora de las 6, que el ciclo recomienda a las 06:00 en los tres horizontes, de cada día
   del backtest de alertas (15-sep a 31-dic de 2025, 3 rutas). Es la cifra de «recomendaciones viables» de
   docs/evidencias/alertas/backtest_alertas_pronostico.md.
B. Todas las horas de servicio (4-20 h) de semanas representativas de 2025 (miércoles, sábado y domingo), para la
   franja de §10.2 y para el plan del día (MILP de D5).

Para cada franja inviable se resuelve otra vez cambiando UNA condición a la vez; la causa es la condición que, sola,
la vuelve viable:
- «reparto por tipología»: la flota total como única cota, sin el reparto fijo entre tipologías;
- «banda P90»: dimensionar con la demanda puntual (sin la banda calibrada);
- «ciclo mediano»: el ciclo del percentil 25 de 2025 en lugar de la mediana;
- «headway mínimo»: 1 min en lugar de 2.
Si ninguna sola alcanza, la causa es «combinada».

Solo LEE datos/; escribe docs/evidencias/optimizacion/viabilidad.json y viabilidad.md (o --salida DIR).
Uso:  .venv\\Scripts\\python scripts/viabilidad.py [--semanas 2025-03-12,2025-11-19] [--salida DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import datos, inferencia  # noqa: E402
from app.servicios import optimizacion as O  # noqa: E402
from app.servicios.ejecucion import ZONA, json_seguro  # noqa: E402

UMBRALES = {"ocupacion_objetivo_min": 0.65, "ocupacion_objetivo_max": 0.85, "headway_minimo_min": 2.0,
            "headway_maximo_min": 10.0, "espera_max_min": 5.0, "ocupacion_critica": 0.90}
RUTAS = ("SILENCIO", "CRA 54", "CL 72")
INICIO_A, FIN_A = date(2025, 9, 15), date(2025, 12, 31)
SEMANAS = (date(2025, 3, 12), date(2025, 6, 11), date(2025, 9, 10), date(2025, 11, 19))
CAUSAS = {"reparto_tipologia": "reparto por tipología", "banda_p90": "banda P90",
          "ciclo_mediano": "ciclo mediano", "headway_minimo": "headway mínimo"}
CLAVES_OPT = ("capacidad", "ocupacion_objetivo", "tiempo_ciclo_min", "flota_disponible", "headway_min", "headway_max",
              "frecuencia_actual_min", "ocupacion_critica", "factor_carga")


def _f(x, d=1):
    if x is None:
        return "—"
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pronosticos(ruta: str, inicios: list[datetime]) -> list[dict]:
    salidas = inferencia.predecir_horas(ruta, inicios, horizonte_min=60, usar_nowcast=False)
    return [{"p10": float(r["p10"]), "p50": float(r["pasajeros"]), "p90": float(r["p90"])} for r in salidas]


def _ciclo_p25() -> dict:
    import pandas as pd

    from app.servicios.motor_d5 import comun as C

    d = pd.read_parquet(C.DATOS / O.ARCHIVO_INSUMOS_D5, columns=["ruta", "tipo_dia", "hora", "ciclo"])
    d["t"] = d["tipo_dia"].astype(str).str[:1]
    return {(r, t, int(h)): float(v) for (r, t, h), v in d.groupby(["ruta", "t", "hora"])["ciclo"].quantile(0.25)
            .items()}


def _contrafactuales(ruta: str, hora: int, fecha: date, dem: dict, trazas: dict, p25: dict) -> dict:
    """Viabilidad de la franja cambiando una condición a la vez."""
    kw = {k: trazas[k] for k in CLAVES_OPT if trazas.get(k) is not None}
    kw.update(ruta=ruta, hora=hora, demanda_hora=dem["p50"], demanda_p90=dem["p90"], demanda_p10=dem["p10"],
              parametros=trazas["parametros_objetivo"])
    tipos = O.tipologias_ruta(ruta, kw.get("flota_disponible"))
    variantes = {
        "reparto_tipologia": dict(kw, tipologias=[dict(t, disponibles=None) for t in tipos]),
        "banda_p90": dict(kw, tipologias=tipos, demanda_p90=None, demanda_p10=None),
        "ciclo_mediano": dict(kw, tipologias=tipos, tiempo_ciclo_min=p25.get(
            (ruta, "LSD"[O.tipo_dia_operacion(fecha)], hora), kw.get("tiempo_ciclo_min"))),
        "headway_minimo": dict(kw, tipologias=tipos, headway_min=1.0),
    }
    return {n: bool(O.optimizar(**v)["viable"]) for n, v in variantes.items()}


def _vehiculos(trazas: dict) -> int | None:
    """Vehículos que pide la frecuencia programada con el ciclo de la hora: ceil(ciclo × buses/h / 60)."""
    ciclo, prog = trazas.get("tiempo_ciclo_min"), trazas.get("frecuencia_actual_min")
    if not ciclo or not prog:
        return None
    return int(math.ceil(ciclo * (60.0 / prog) / 60.0 - 1e-9))


def franja(ruta: str, fecha: date, hora: int, dem: dict, p25: dict) -> dict:
    r, trazas = O.recomendacion_franja(datos.ruta_info(ruta), UMBRALES, 1, hora=hora, fecha=fecha,
                                       demanda_hora=dem["p50"], demanda_p90=dem["p90"], demanda_p10=dem["p10"])
    fila = {"ruta": ruta, "fecha": fecha.isoformat(), "tipo_dia": O.TIPOS_DIA[O.tipo_dia_operacion(fecha)],
            "hora": hora, "p50": round(dem["p50"], 1), "p90": round(dem["p90"], 1), "viable": bool(r["viable"]),
            "buses_hora": r["buses_hora"], "limites_activos": r.get("limites_activos") or [],
            "sobreoferta": r.get("sobreoferta"), "programada_buses_h": (round(60 / trazas["frecuencia_actual_min"], 1)
                                                                        if trazas.get("frecuencia_actual_min")
                                                                        else None),
            "ciclo_min": trazas.get("tiempo_ciclo_min"), "flota": trazas.get("flota_disponible"),
            "vehiculos_programada": _vehiculos(trazas),
            "cobertura_aproximacion": (r.get("mejor_aproximacion") or {}).get("cobertura_nivel_servicio"),
            "motivo": r.get("motivo")}
    if not r["viable"]:
        cf = _contrafactuales(ruta, hora, fecha, dem, trazas, p25)
        fila["contrafactuales"] = cf
        fila["causas"] = [n for n, ok in cf.items() if ok] or ["combinada"]
    return fila


def parte_a(p25: dict) -> dict:
    dias = [INICIO_A + timedelta(days=i) for i in range((FIN_A - INICIO_A).days + 1)]
    filas = []
    for ruta in RUTAS:
        inicios = [datetime(d.year, d.month, d.day, 6, tzinfo=ZONA) for d in dias]
        for d, dem in zip(dias, pronosticos(ruta, inicios), strict=True):
            filas.append(franja(ruta, d, 6, dem, p25))
    return {"periodo": f"{INICIO_A} a {FIN_A}", "hora": 6, "franjas": len(filas), "filas": filas}


def parte_b(semanas, p25: dict) -> dict:
    franjas, planes = [], []
    for miercoles in semanas:
        for d in (miercoles, miercoles + timedelta(days=3), miercoles + timedelta(days=4)):
            for ruta in RUTAS:
                inicios = [datetime(d.year, d.month, d.day, h, tzinfo=ZONA) for h in datos.HORAS_SERVICIO]
                pron = pronosticos(ruta, inicios)
                for h, dem in zip(datos.HORAS_SERVICIO, pron, strict=True):
                    franjas.append(franja(ruta, d, h, dem, p25))
                horario = [{"hora": h, **dem} for h, dem in zip(datos.HORAS_SERVICIO, pron, strict=True)]
                plan = O.plan_dia(d, ruta, umbrales=UMBRALES, umbrales_version=1, pronostico_horario=horario)
                for x in plan["horas"]:
                    planes.append({"ruta": ruta, "fecha": d.isoformat(), "tipo_dia": plan["tipo_dia"],
                                   "hora": x["hora"], "salidas": x["salidas"], "viable": x["viable"],
                                   "limitada_por_headway_minimo": x["limitada_por_headway_minimo"],
                                   "flota_insuficiente": "flota" in (x["motivo"] or "").lower(),
                                   "limites_activos": x["limites_activos"], "sobreoferta": x["sobreoferta"],
                                   "cobertura_demanda_diseno": x["margen"].get("cobertura_demanda_diseno"),
                                   "motivo": x["motivo"]})
    return {"semanas": [s.isoformat() for s in semanas], "franjas": franjas, "plan": planes}


def _resumen(filas: list[dict], llaves: tuple) -> list[dict]:
    grupos = defaultdict(list)
    for f in filas:
        grupos[tuple(f[k] for k in llaves)].append(f)
    salida = []
    for clave, g in sorted(grupos.items(), key=lambda x: tuple(str(v) for v in x[0])):
        causas = Counter(c for f in g if not f["viable"] for c in f.get("causas") or [])
        salida.append({**dict(zip(llaves, clave, strict=True)), "n": len(g),
                       "viables": sum(1 for f in g if f["viable"]),
                       "porcentaje_viable": round(100 * sum(1 for f in g if f["viable"]) / len(g), 1),
                       "causas": dict(causas)})
    return salida


def correr(salida: Path, semanas) -> dict:
    t0 = time.perf_counter()
    p25 = _ciclo_p25()
    a, b = parte_a(p25), parte_b(semanas, p25)
    res = {"generado": datetime.now(ZONA).isoformat(timespec="seconds"), "umbrales": UMBRALES,
           "modelo": inferencia.modelo_activo(), "causas": CAUSAS,
           "a_ciclo": dict(a, resumen_ruta_tipo=_resumen(a["filas"], ("ruta", "tipo_dia")),
                           resumen_ruta=_resumen(a["filas"], ("ruta",))),
           "b_semanas": dict(b, resumen_franja=_resumen(b["franjas"], ("ruta", "tipo_dia", "hora")),
                             resumen_plan=_resumen(b["plan"], ("ruta", "tipo_dia", "hora")))}
    res["segundos"] = round(time.perf_counter() - t0, 1)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "viabilidad.json").write_text(json.dumps(json_seguro(res), ensure_ascii=False, indent=1) + "\n",
                                            encoding="utf-8")
    (salida / "viabilidad.md").write_text(markdown(res), encoding="utf-8")
    return res


def _pct(g: list[dict]) -> str:
    n = len(g)
    v = sum(1 for f in g if f["viable"])
    return f"{_f(100 * v / n, 1)} % ({v} de {n})" if n else "—"


def _causas_txt(c: dict) -> str:
    return ", ".join(f"{CAUSAS.get(k, k)} {v}" for k, v in sorted(c.items(), key=lambda x: -x[1])) or "—"


def _lectura_a(grupos: list[dict]) -> str:
    """Lectura de la parte A en palabras, con las cifras de la tabla."""
    llenos = [g for g in grupos if g["porcentaje_viable"] == 100]
    malos = [g for g in grupos if g["porcentaje_viable"] < 100]
    n_malas = sum(g["n"] - g["viables"] for g in malos)
    partes = [f"**Lectura.** Las {n_malas} franjas no viables están en "
              + ", ".join(f"{g['ruta']} {g['tipo_dia'].lower()} ({g['n'] - g['viables']})" for g in malos)
              + "; " + ", ".join(f"{g['ruta']} {g['tipo_dia'].lower()}" for g in llenos) + " son viables en todos "
              "los días."]
    for g in malos:
        c = g["causas"]
        if c.get("reparto_tipologia", 0) >= 0.9 * (g["n"] - g["viables"]):
            partes.append(f"En {g['ruta']} {g['tipo_dia'].lower()} manda el reparto fijo de la flota entre "
                          f"tipologías: con la flota total como única cota se vuelven viables "
                          f"{c['reparto_tipologia']} de {g['n'] - g['viables']}.")
        elif c.get("combinada", 0) >= 0.5 * (g["n"] - g["viables"]):
            partes.append(f"En {g['ruta']} {g['tipo_dia'].lower()} ninguna condición sola alcanza en "
                          f"{c['combinada']} de {g['n'] - g['viables']}: la hora pide más capacidad de la que "
                          "sostienen juntas la flota, el ciclo y el headway mínimo (ver la hora pico de CRA 54).")
    return " ".join(partes)


def markdown(res: dict) -> str:
    a, b = res["a_ciclo"], res["b_semanas"]
    filas_a = a["filas"]
    L = ["# Viabilidad de la recomendación por ruta, hora y tipo de día (2025)", "",
         f"Generado por `scripts/viabilidad.py` el {res['generado']} ({res['segundos']} s) con el modelo activo "
         f"`{res['modelo']}` (P10/P50/P90 por hora, h = 60, sin factor intradía) y los umbrales de producción: "
         "headway 2 a 10 min (el máximo es min(headway_maximo_min, 2 × espera_max_min) con espera de 5 min), "
         "ocupación objetivo 65 % a 85 %, nivel de servicio 0,90 (P90 calibrado). Ciclo, flota e intervalo "
         "programado: mediana 2025 por ruta, tipo de día y hora (`datos/parametros_operativos_hora.parquet`); "
         "tipologías de `tipologias_flota.json`.",
         "",
         "Una franja es **no viable** cuando ninguna mezcla de buses cumple a la vez el headway mínimo y máximo, la "
         "flota (repartida por tipología) con el ciclo de la hora y la capacidad para la carga crítica del P90 "
         "(§10.2). Entonces se informa la mejor aproximación ejecutable y su cobertura (§10.3, §18). Para cada franja "
         "no viable se cambia UNA condición a la vez; la causa es la que, sola, la vuelve viable:", ""]
    L += [f"- **{v}**: " + {"reparto_tipologia": "la flota total como única cota, sin el reparto fijo entre "
                                                 "tipologías de `tipologias_ruta`;",
                            "banda_p90": "dimensionar con la demanda puntual en lugar del P90 calibrado;",
                            "ciclo_mediano": "el ciclo del percentil 25 de 2025 en lugar de la mediana;",
                            "headway_minimo": "headway mínimo de 1 min en lugar de 2."}[k] for k, v in CAUSAS.items()]
    L += ["- **combinada**: ninguna condición sola alcanza.", "",
          "Una franja puede resolverse con más de una causa: por eso las causas pueden sumar más que las franjas.", "",
          "## A. La franja del ciclo diario (hora de las 6, 15-sep a 31-dic de 2025)", "",
          f"El ciclo diario recomienda a las 06:00 la hora de las 6 en los tres horizontes. Sobre {a['franjas']} "
          f"franjas (3 rutas × {a['franjas'] // 3} días) es viable el **{_pct(filas_a)}**. El backtest de alertas "
          "(`docs/evidencias/alertas/backtest_alertas_pronostico.md`) informa 46,0 % con su propio pronóstico de "
          "ventana; esta tabla explica de dónde sale.", "",
          "| Ruta | Tipo de día | Franjas | Viables | Causa de las no viables (franjas que la causa sola resuelve) |",
          "|---|---|---|---|---|"]
    for g in a["resumen_ruta_tipo"]:
        L.append(f"| {g['ruta']} | {g['tipo_dia']} | {g['n']} | {_f(g['porcentaje_viable'], 1)} % | "
                 f"{_causas_txt(g['causas'])} |")
    por_ruta = {g["ruta"]: g for g in a["resumen_ruta"]}
    L += ["", "Por ruta: " + "; ".join(f"{r} {_f(g['porcentaje_viable'], 1)} %" for r, g in por_ruta.items()) + ".",
          "", _lectura_a(a["resumen_ruta_tipo"]), ""]
    no_viables = [f for f in filas_a if not f["viable"]]
    if no_viables:
        cob = sorted(f["cobertura_aproximacion"] for f in no_viables if f.get("cobertura_aproximacion") is not None)
        if cob:
            L.append(f"En las {len(no_viables)} franjas no viables la mejor aproximación ejecutable cubre en mediana "
                     f"el {_f(100 * cob[len(cob) // 2], 1)} % de la carga del nivel de servicio (mínimo "
                     f"{_f(100 * cob[0], 1)} %).")
        L.append("")
    L += ["## B. Todas las horas de servicio, semanas representativas", "",
          "Semanas del " + ", ".join(b["semanas"]) + " (miércoles, sábado y domingo de cada una).", "",
          "### Franja de §10.2 por hora", "",
          "| Ruta | Tipo de día | Horas viables | Horas no viables y causa |", "|---|---|---|---|"]
    por_rt = defaultdict(list)
    for g in b["resumen_franja"]:
        por_rt[(g["ruta"], g["tipo_dia"])].append(g)
    for (ruta, tipo), gs in sorted(por_rt.items()):
        n = sum(g["n"] for g in gs)
        v = sum(g["viables"] for g in gs)
        malas = [f"{g['hora']} h ({_f(g['porcentaje_viable'], 0)} % viable; {_causas_txt(g['causas'])})"
                 for g in gs if g["porcentaje_viable"] < 100]
        L.append(f"| {ruta} | {tipo} | {_f(100 * v / n, 1)} % ({v} de {n}) | {'; '.join(malas) or '—'} |")
    L += ["", "### Plan del día (MILP de D5) por hora", "",
          "En el plan la capacidad no es una restricción dura (la sobrecarga esperada se penaliza en el costo): una "
          "hora es no viable si la demanda pide más salidas de las que permite el headway mínimo o si la flota no "
          "sostiene las salidas mínimas.", "",
          "| Ruta | Tipo de día | Horas viables | Horas no viables | Horas con sobreoferta |", "|---|---|---|---|---|"]
    por_rt_p = defaultdict(list)
    for x in b["plan"]:
        por_rt_p[(x["ruta"], x["tipo_dia"])].append(x)
    for (ruta, tipo), xs in sorted(por_rt_p.items()):
        malas = sorted({x["hora"] for x in xs if not x["viable"]})
        sobre = sorted({x["hora"] for x in xs if x["sobreoferta"]})
        L.append(f"| {ruta} | {tipo} | {_pct(xs)} | {', '.join(f'{h} h' for h in malas) or '—'} | "
                 f"{', '.join(f'{h} h' for h in sobre) or '—'} |")
    L += ["", "## La hora pico de CRA 54 (hallazgo H13)", ""]
    pico = [f for f in b["franjas"] if f["ruta"] == "CRA 54" and f["hora"] in (6, 7)]
    for f in pico:
        L.append(f"- {f['fecha']} ({f['tipo_dia']}) {f['hora']} h: P50 {_f(f['p50'], 0)}, P90 {_f(f['p90'], 0)}; "
                 f"programada {_f(f['programada_buses_h'], 1)} buses/h, que con el ciclo de "
                 f"{_f(f['ciclo_min'], 1)} min pide {f['vehiculos_programada']} vehículos; flota "
                 f"{f['flota']}; {'viable' if f['viable'] else 'no viable'}"
                 + (f" (causa: {', '.join(CAUSAS.get(c, c) for c in f['causas'])})" if not f["viable"] else "")
                 + ".")
    sin_cupo = [f for f in pico if f.get("vehiculos_programada") and f.get("flota")
                and f["vehiculos_programada"] > f["flota"]]
    flotas = sorted({int(f["flota"]) for f in sin_cupo})
    pide = sorted(f["vehiculos_programada"] for f in sin_cupo)
    cifra = (f"pide de {pide[0]} a {pide[-1]} vehículos frente a una flota de "
             f"{' y '.join(str(x) for x in flotas)}" if sin_cupo else "no supera la flota")
    L += ["", f"La programación vigente de CRA 54 en la hora pico no cabe en la flota con el ciclo mediano: buses/h × "
              f"ciclo / 60 {cifra} (H13, `docs/hallazgos_extreme.md`). Por eso la franja sale no "
              "viable aunque la operación la corre hoy: o el ciclo real de la hora pico es más corto que la mediana "
              "de 2025, o hay más vehículos que los de la flota registrada. Se pide a Extreme el ciclo por franja y "
              "la flota disponible por tipo de día (§19).", ""]
    return "\n".join(L) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "optimizacion")
    p.add_argument("--semanas", default=",".join(s.isoformat() for s in SEMANAS),
                   help="miércoles de las semanas de la parte B, separados por coma")
    p.add_argument("--solo-markdown", action="store_true", help="rehace viabilidad.md desde viabilidad.json")
    a = p.parse_args()
    if a.solo_markdown:
        res = json.loads((a.salida / "viabilidad.json").read_text(encoding="utf-8"))
        (a.salida / "viabilidad.md").write_text(markdown(res), encoding="utf-8")
        return
    semanas = [date.fromisoformat(s) for s in a.semanas.split(",") if s]
    res = correr(a.salida, semanas)
    print(f"A: {res['a_ciclo']['franjas']} franjas; B: {len(res['b_semanas']['franjas'])} franjas y "
          f"{len(res['b_semanas']['plan'])} horas de plan; {res['segundos']} s")


if __name__ == "__main__":
    main()
