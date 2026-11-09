"""Calibración conformal condicional por grupo (Mondrian) de la banda P10-P90 de un modelo (por defecto, el activo).

Responde a §9.3 («presentar intervalos de confianza o cuantiles»), §9.4 («cobertura de los intervalos») y al criterio
de robustez e incertidumbre de §16. Mide la cobertura P10-P90 y el ancho medio por hora, ruta y tipo de día en la
VALIDACIÓN (la ventana de calibración) y en la prueba RESERVADA (solo se reporta; nunca se ajusta con ella) para:

- «modelo»: la banda de los cuantiles P10 y P90 del HistGradientBoosting, sin calibrar;
- «v1»: la calibración anterior (respaldo con CALIBRACION_BANDA=v1), conformal móvil (CQR) por ruta con los 56 días
  previos a cada día
  (inferencia.cuantiles_conformal_movil, la misma función que usa la API);
- candidatas de Mondrian: un cuantil conformal por grupo (bloque horario, ruta × bloque, ruta × hora, tipo de día ×
  bloque), ajustado solo con días de la validación.

Elección sin mirar la prueba: validación cruzada por semanas dentro de la validación (se ajusta con las semanas ISO
pares y se evalúa en las impares, y al revés). Una candidata se adopta solo si baja la peor desviación de la cobertura
frente al 80 % en los grupos por hora, ruta y tipo de día y no ensancha el intervalo medio (pasajeros) frente a v1.

Con --escribir guarda la calibración adoptada como archivo versionado en la carpeta del modelo (calibracion_v2.json,
con su SHA-256 en manifest.json bajo la clave «calibracion»); nunca toca modelo.joblib ni los .onnx. Siempre escribe
docs/evidencias/modelo/calibracion_condicional.json y .md (con --model-id de un modelo que no es el activo, los archivos
llevan el id, calibracion_condicional_<model_id>.json y .md, y la evidencia del activo no se toca).

El ajuste y la escritura son las mismas funciones que usa el entrenamiento de la API
(inferencia.ajustar_calibracion_grupo, inferencia.calibracion_de_validacion e inferencia.escribir_calibracion): cada
candidato entrenado sale con su calibración por grupo ajustada con su propia validación.

Uso (desde EntregaFinal/api_frecuencias):
  python scripts/calibrar_por_grupo.py                                # solo análisis y evidencia del activo
  python scripts/calibrar_por_grupo.py --escribir                     # además versiona la calibración adoptada
  python scripts/calibrar_por_grupo.py --model-id <id> [--escribir]   # el mismo análisis para otro modelo
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ZONA = ZoneInfo("America/Bogota")
SALIDA = RAIZ / "docs" / "evidencias" / "modelo"
OBJETIVO = 80.0
MIN_GRUPO = 30           # con menos puntajes en un grupo se usa el cuantil global del ajuste
ESPECIALES = ("festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero")
CANDIDATAS = {
    "mondrian_bloque": ("bloque",),
    "mondrian_ruta_bloque": ("ruta", "bloque"),
    "mondrian_ruta_hora": ("ruta", "hora"),
    "mondrian_tipo_bloque": ("tipo", "bloque"),
}
PARTICIONES = ("hora", "ruta", "tipo")


def _grupo(t: pd.DataFrame, claves: tuple[str, ...]) -> np.ndarray:
    """La misma clave de grupo que usa la API al aplicar la calibración (inferencia.grupos_calibracion)."""
    from app.servicios import inferencia

    return inferencia.grupos_calibracion(t, claves)


def ajustar(t: pd.DataFrame, s: np.ndarray, claves: tuple[str, ...], inferencia, cobertura=0.80) -> dict:
    """{grupo: q} con el cuantil conformal de muestra finita de cada grupo; «*» = cuantil global (respaldo). Es la
    misma función del entrenamiento (inferencia.ajustar_calibracion_grupo)."""
    return inferencia.ajustar_calibracion_grupo(t, s, claves, cobertura, MIN_GRUPO)


def q_filas(t: pd.DataFrame, claves: tuple[str, ...], tabla_q: dict) -> np.ndarray:
    g = _grupo(t, claves)
    respaldo = tabla_q["*"]
    return np.array([tabla_q.get(k, respaldo) for k in g], dtype=float)


def medir(t: pd.DataFrame, lo: np.ndarray, hi: np.ndarray) -> dict:
    y = t["pasajeros"].to_numpy(float)
    p = t["p"].to_numpy(float)
    dentro = (y >= lo) & (y <= hi)
    ancho = hi - lo
    rel = ancho / np.maximum(p, 1.0)

    def bloque(m):
        return {"n": int(m.sum()), "cobertura_pct": round(float(dentro[m].mean() * 100), 2),
                "bajo_p10_pct": round(float((y[m] < lo[m]).mean() * 100), 2),
                "sobre_p90_pct": round(float((y[m] > hi[m]).mean() * 100), 2),
                "ancho_medio": round(float(ancho[m].mean()), 1),
                "ancho_relativo_mediano_pct": round(float(np.median(rel[m]) * 100), 1)}

    out = {"global": bloque(np.ones(len(t), dtype=bool))}
    for nombre in PARTICIONES + ("bloque", "especial"):
        col = t[nombre].astype(str).to_numpy()
        out[f"por_{nombre}"] = {k: bloque(col == k) for k in sorted(set(col), key=_orden)}
    devs = [abs(v["cobertura_pct"] - OBJETIVO) for nombre in PARTICIONES for v in out[f"por_{nombre}"].values()]
    out["peor_desviacion_pp"] = round(float(max(devs)), 2)
    out["peor_desviacion_por_particion_pp"] = {
        nombre: round(float(max(abs(v["cobertura_pct"] - OBJETIVO) for v in out[f"por_{nombre}"].values())), 2)
        for nombre in PARTICIONES}
    return out


def _orden(k: str):
    return (0, int(k)) if k.isdigit() else (1, k)


def preparar(inferencia, modelo, desde: date, hasta: date) -> pd.DataFrame:
    t = inferencia._filas_utiles(inferencia.tabla_variables())
    t = t[(t["fecha"] >= desde) & (t["fecha"] <= hasta)].copy()
    p, lo, hi = inferencia._predecir_filas(modelo, t)
    t["p"], t["lo"], t["hi"] = p, lo, hi
    t["s"] = inferencia.puntajes_conformal(p, lo, hi, t["pasajeros"].to_numpy(float))
    t["bloque"] = inferencia.franja_de(t["hora"])
    t["tipo"] = t["tipo_dia"].astype(int).map(inferencia.datos.TIPOS_DIA)
    t["especial"] = np.where(t[list(ESPECIALES)].max(axis=1) > 0, "especial", "normal")
    t["semana"] = pd.to_datetime(t["fecha"]).dt.isocalendar().week.to_numpy() % 2
    return t.reset_index(drop=True)


def banda_v1(inferencia, modelo, t: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, float]:
    """Banda vigente: conformal móvil por ruta (solo días anteriores a cada día), como la API."""
    inferencia._puntajes_conformal(modelo)
    claves = sorted(set(zip(t["ruta"], t["fecha"], strict=False)))
    qs = inferencia.cuantiles_conformal_movil(modelo["_indice_conformal"], claves)
    q = np.array([qs[(r, f)]["q"] if qs[(r, f)]["aplicado"] else 0.0
                  for r, f in zip(t["ruta"], t["fecha"], strict=False)], dtype=float)
    aplicada = np.array([qs[(r, f)]["aplicado"] for r, f in zip(t["ruta"], t["fecha"], strict=False)])
    lo, hi = inferencia.aplicar_conformal(t["p"], t["lo"], t["hi"], q)
    return lo, hi, round(float(aplicada.mean() * 100), 1)


def cruzada(inferencia, t: pd.DataFrame, claves) -> tuple[np.ndarray, np.ndarray]:
    """Validación cruzada por semanas ISO (pares -> impares y al revés) dentro de la validación."""
    lo, hi = t["lo"].to_numpy(float).copy(), t["hi"].to_numpy(float).copy()
    for parte in (0, 1):
        ajuste = t["semana"] != parte
        evalua = ~ajuste
        tq = ajustar(t[ajuste], t.loc[ajuste, "s"].to_numpy(float), claves, inferencia)["q"]
        q = q_filas(t[evalua], claves, tq)
        lo[evalua], hi[evalua] = inferencia.aplicar_conformal(t.loc[evalua, "p"], t.loc[evalua, "lo"],
                                                              t.loc[evalua, "hi"], q)
    return lo, hi


def razon_p90_p50(t: pd.DataFrame, lo: np.ndarray, hi: np.ndarray) -> dict:
    """Razón P90 / P50 de la banda calibrada por ruta a las 6 h y en todas las horas (el caso de las 6 h)."""
    r = hi / np.maximum(t["p"].to_numpy(float), 1.0)
    out = {}
    for ruta in sorted(t["ruta"].unique()):
        m6 = (t["ruta"] == ruta).to_numpy() & (t["hora"] == 6).to_numpy()
        i = int(np.argmax(np.where(m6, r, -1)))
        out[ruta] = {"hora_6": {"mediana": round(float(np.median(r[m6])), 3),
                                "p95": round(float(np.quantile(r[m6], 0.95)), 3),
                                "maximo": round(float(r[i]), 3), "fecha_maximo": str(t.loc[i, "fecha"]),
                                "p50_en_el_maximo": round(float(t.loc[i, "p"]), 1),
                                "p90_en_el_maximo": round(float(hi[i]), 1),
                                "observado_en_el_maximo": float(t.loc[i, "pasajeros"]),
                                "media_observada_6h": round(float(t.loc[m6, "pasajeros"].mean()), 1),
                                "desviacion_observada_6h": round(float(t.loc[m6, "pasajeros"].std()), 1)}}
    grandes = r >= 2.9
    out["horas_con_razon_mayor_o_igual_2_9"] = {
        "n": int(grandes.sum()), "de": int(len(r)),
        "horas": sorted({int(h) for h in t.loc[grandes, "hora"]}),
        "p50_mediano": round(float(np.median(t.loc[grandes, "p"])), 1) if grandes.any() else None,
        "pct_en_dias_especiales": round(float((t.loc[grandes, "especial"] == "especial").mean() * 100), 1)
        if grandes.any() else None}
    return out


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--escribir", action="store_true", help="versiona la calibración adoptada en la carpeta del modelo")
    ap.add_argument("--model-id", default=None, help="modelo a calibrar (por defecto, el activo del registro)")
    ap.add_argument("--salida", type=Path, default=SALIDA)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from app.servicios import datos, inferencia

    t0 = time.perf_counter()
    modelo = inferencia.cargar(args.model_id)
    sufijo = "" if modelo["model_id"] == inferencia.modelo_activo() else f"_{modelo['model_id']}"
    man = modelo["manifiesto"]
    v_desde, v_hasta = (date.fromisoformat(x.strip()) for x in man["particion"]["validacion"].split(" a "))
    p_desde, p_hasta = (date.fromisoformat(x.strip()) for x in man["particion"]["prueba"].split(" a "))
    val = preparar(inferencia, modelo, v_desde, v_hasta)
    pru = preparar(inferencia, modelo, p_desde, p_hasta)

    res: dict = {"validacion": {}, "prueba": {}}
    for nombre, t in (("validacion", val), ("prueba", pru)):
        res[nombre]["modelo"] = medir(t, t["lo"].to_numpy(float), t["hi"].to_numpy(float))
        lo1, hi1, pct = banda_v1(inferencia, modelo, t)
        res[nombre]["v1"] = medir(t, lo1, hi1)
        res[nombre]["v1"]["dias_con_ajuste_pct"] = pct
        if nombre == "validacion":
            for cand, claves in CANDIDATAS.items():
                lo2, hi2 = cruzada(inferencia, t, claves)
                res[nombre][cand] = medir(t, lo2, hi2)
                res[nombre][cand]["esquema"] = "validación cruzada por semanas ISO (pares/impares)"
    v1v = res["validacion"]["v1"]
    decision = []
    for cand in CANDIDATAS:
        c = res["validacion"][cand]
        mejora = c["peor_desviacion_pp"] < v1v["peor_desviacion_pp"]
        no_ensancha = c["global"]["ancho_medio"] <= v1v["global"]["ancho_medio"]
        decision.append({"candidata": cand, "grupos": "×".join(CANDIDATAS[cand]),
                         "peor_desviacion_pp": c["peor_desviacion_pp"], "ancho_medio": c["global"]["ancho_medio"],
                         "cobertura_global_pct": c["global"]["cobertura_pct"], "baja_la_peor_desviacion": mejora,
                         "no_ensancha": no_ensancha, "cumple": bool(mejora and no_ensancha)})
    aptas = sorted([d for d in decision if d["cumple"]], key=lambda d: (d["peor_desviacion_pp"], d["ancho_medio"]))
    elegida = aptas[0]["candidata"] if aptas else None

    calibracion = None
    if elegida:
        claves = CANDIDATAS[elegida]
        ajuste = ajustar(val, val["s"].to_numpy(float), claves, inferencia)
        q = q_filas(pru, claves, ajuste["q"])
        lo2, hi2 = inferencia.aplicar_conformal(pru["p"], pru["lo"], pru["hi"], q)
        res["prueba"]["v2"] = medir(pru, lo2, hi2)
        qv = q_filas(val, claves, ajuste["q"])
        lo2v, hi2v = inferencia.aplicar_conformal(val["p"], val["lo"], val["hi"], qv)
        res["validacion"]["v2_ajuste_completo"] = medir(val, lo2v, hi2v)
        res["validacion"]["v2_ajuste_completo"]["nota"] = "en la misma muestra del ajuste (referencia; la decisión " \
                                                          "usa la validación cruzada)"
        calibracion = inferencia.calibracion_de_validacion(
            modelo["model_id"], val, (val["p"], val["lo"], val["hi"]), claves, script="scripts/calibrar_por_grupo.py",
            evidencia=f"docs/evidencias/modelo/calibracion_condicional{sufijo}.json", ventana=(v_desde, v_hasta))
        if calibracion["q"] != ajuste["q"]:
            raise RuntimeError("el ajuste del análisis y el de la API no coinciden")
    res["caso_6h"] = {"validacion": razon_p90_p50(val, *banda_v1(inferencia, modelo, val)[:2]),
                      "prueba": razon_p90_p50(pru, *banda_v1(inferencia, modelo, pru)[:2])}
    salida = {
        "generado": datetime.now(ZONA).isoformat(timespec="seconds"), "model_id": modelo["model_id"],
        "validacion": f"{v_desde} a {v_hasta}", "prueba_reservada": f"{p_desde} a {p_hasta}",
        "objetivo_cobertura_pct": OBJETIVO, "criterio": (
            "Se adopta una candidata solo si, en la validación cruzada por semanas, baja la peor desviación |cobertura "
            "- 80 %| de los grupos por hora, ruta y tipo de día frente a v1 y su ancho medio (pasajeros) no supera al "
            "de v1. La prueba reservada solo se reporta."),
        "decision": decision, "adoptada": elegida, "calibracion": calibracion, "resultados": res,
        "duracion_s": round(time.perf_counter() - t0, 1), "datos": str(datos.carpeta_datos().name)}
    if args.escribir and calibracion is not None:
        resumen = {
            "validacion_cruzada": {k: res["validacion"][elegida][k] if k == "peor_desviacion_pp" else
                                   res["validacion"][elegida]["global"][k.replace("_global", "")]
                                   for k in ("peor_desviacion_pp", "cobertura_pct", "ancho_medio")},
            "v1_validacion": {"peor_desviacion_pp": v1v["peor_desviacion_pp"],
                              "cobertura_pct": v1v["global"]["cobertura_pct"],
                              "ancho_medio": v1v["global"]["ancho_medio"]},
            "prueba_reservada_solo_reporte": {
                v: {"peor_desviacion_pp": res["prueba"][v]["peor_desviacion_pp"],
                    "cobertura_pct": res["prueba"][v]["global"]["cobertura_pct"],
                    "ancho_medio": res["prueba"][v]["global"]["ancho_medio"]} for v in ("v1", "v2")}}
        salida["archivo"] = escribir_calibracion(modelo, calibracion, resumen)
    elif calibracion is not None and (vigente := calibracion_vigente(modelo)) is not None and \
            vigente["grupos"] == calibracion["grupos"] and vigente["q"] == calibracion["q"]:
        salida["archivo"] = {"archivo": vigente["archivo"], "sha256": vigente["sha256"]}   # ya versionada, igual
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / f"calibracion_condicional{sufijo}.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (args.salida / f"calibracion_condicional{sufijo}.md").write_text(informe(salida), encoding="utf-8")
    print(informe(salida))
    return salida


def calibracion_vigente(modelo: dict) -> dict | None:
    """La calibración ya versionada en la carpeta del modelo (para no reescribirla si el ajuste da lo mismo)."""
    from app.servicios import datos

    carpeta = datos.carpeta_modelos() / modelo["model_id"]
    meta = (modelo.get("manifiesto") or {}).get("calibracion")
    if not meta or not (carpeta / meta["archivo"]).is_file():
        return None
    cal = json.loads((carpeta / meta["archivo"]).read_text(encoding="utf-8"))
    return {"archivo": _relativa(carpeta / meta["archivo"]), "sha256": meta["sha256"],
            "grupos": cal.get("grupos"), "q": cal.get("q")}


def escribir_calibracion(modelo: dict, calibracion: dict, resumen: dict | None = None) -> dict:
    """calibracion_v2.json en la carpeta del modelo + su SHA-256 en manifest.json (clave «calibracion»), con la misma
    función del entrenamiento (inferencia.escribir_calibracion). No toca el artefacto ni los ONNX."""
    from app.servicios import datos, inferencia

    carpeta = datos.carpeta_modelos() / modelo["model_id"]
    meta = inferencia.escribir_calibracion(carpeta, calibracion, resumen)
    return {"archivo": _relativa(carpeta / meta["archivo"]), "sha256": meta["sha256"]}


def _relativa(ruta: Path) -> str:
    """Ruta dentro del repositorio si cae en él; si MODELOS_DIR apunta a otra carpeta, la ruta completa."""
    try:
        return ruta.resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return ruta.as_posix()


def lectura(r: dict) -> list[str]:
    """Lectura en lenguaje operativo, con las cifras de esta misma corrida."""
    val, pru = r["resultados"]["validacion"], r["resultados"]["prueba"]
    v1h = val["v1"]["por_hora"]
    peor = min(v1h, key=lambda h: v1h[h]["cobertura_pct"])
    lin = ["## Lectura", "",
           f"- En la validación, la calibración anterior (v1) deja la hora {peor} en "
           f"{_f(v1h[peor]['cobertura_pct'])} % "
           f"(inicio del servicio) y sobrecubre la mañana (7 h: {_f(v1h['7']['cobertura_pct'])} %, 8 h: "
           f"{_f(v1h['8']['cobertura_pct'])} %): la cobertura global de 80 % esconde errores de hasta "
           f"{_f(val['v1']['peor_desviacion_pp'], 2)} pp por hora."]
    if r["adoptada"] and "v2" in pru:
        c = val[r["adoptada"]]
        lin.append(f"- La calibración por {' × '.join(r['calibracion']['grupos'])} baja esa peor desviación a "
                   f"{_f(c['peor_desviacion_pp'], 2)} pp en la validación cruzada, con un intervalo medio de "
                   f"{_f(c['global']['ancho_medio'], 0)} pasajeros frente a "
                   f"{_f(val['v1']['global']['ancho_medio'], 0)}.")
        p1, p2, pm = pru["v1"], pru["v2"], pru["modelo"]
        h20 = {k: _f(x["por_hora"]["20"]["cobertura_pct"]) for k, x in (("m", pm), ("v1", p1), ("v2", p2))}
        lin.append(f"- En la prueba reservada (solo reporte) la cobertura global queda igual (v1 "
                   f"{_f(p1['global']['cobertura_pct'], 2)} %, v2 {_f(p2['global']['cobertura_pct'], 2)} %) con un "
                   f"intervalo medio más angosto ({_f(p1['global']['ancho_medio'])} → "
                   f"{_f(p2['global']['ancho_medio'])} pasajeros) y la hora 4 pasa de "
                   f"{_f(p1['por_hora']['4']['cobertura_pct'])} % a {_f(p2['por_hora']['4']['cobertura_pct'])} %. "
                   f"La peor desviación no mejora ({_f(p1['peor_desviacion_pp'], 2)} → "
                   f"{_f(p2['peor_desviacion_pp'], 2)} pp): las horas finales quedan bajo el 80 % con cualquier banda "
                   f"(20 h: modelo {h20['m']} %, v1 {h20['v1']} %, v2 {h20['v2']} %) "
                   f"y los días especiales de noviembre y diciembre también (v1 "
                   f"{_f(p1['por_especial']['especial']['cobertura_pct'])} %, v2 "
                   f"{_f(p2['por_especial']['especial']['cobertura_pct'])} %). Es un cambio de temporada que una "
                   "calibración ajustada con septiembre y octubre no puede anticipar; el monitoreo de §9.4 mide la "
                   "cobertura móvil y la política de reentrenamiento la usa como disparador.")
    c6 = r["resultados"]["caso_6h"]
    v6, t6 = c6["validacion"]["CRA 54"]["hora_6"], c6["prueba"]["CRA 54"]["hora_6"]
    g_v, g_t = c6["validacion"]["horas_con_razon_mayor_o_igual_2_9"], c6["prueba"]["horas_con_razon_mayor_o_igual_2_9"]
    lin.append(f"- Las 6 h en CRA 54: la banda horaria es angosta (P90 / P50 mediana {_f(v6['mediana'], 2)} en la "
               f"validación y {_f(t6['mediana'], 2)} en la prueba; máximo {_f(t6['maximo'], 2)} el "
               f"{t6['fecha_maximo']}). La variación real entre días sí es grande "
               f"({_f(v6['media_observada_6h'], 0)} ± {_f(v6['desviacion_observada_6h'], 0)} pasajeros), pero el "
               "modelo la explica con el tipo de día, el calendario y los rezagos. Una razón de 2,9 no aparece a las "
               "6 h en ninguna ruta: solo en "
               f"{g_v['n']} (validación) y {g_t['n']} (prueba) horas de borde ({g_t['horas']}) con P50 mediano de "
               f"{_f(g_t['p50_mediano'], 0)} pasajeros, donde el ajuste se escala con max(P50, 1). No es un artefacto "
               "de la calibración ni justifica ensanchar la banda de los picos.")
    return lin + [""]


def _f(x, d=1):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def _tabla(res: dict, particion: str, variantes: list[str]) -> list[str]:
    cab = "| Grupo | " + " | ".join(f"{v}: cobertura / ancho medio" for v in variantes) + " |"
    lin = [cab, "|---|" + "---|" * len(variantes)]
    grupos = list(res[variantes[0]][f"por_{particion}"])
    for g in grupos:
        celdas = []
        for v in variantes:
            x = res[v][f"por_{particion}"].get(g)
            celdas.append("—" if x is None else f"{_f(x['cobertura_pct'])} % / {_f(x['ancho_medio'], 0)}")
        lin.append(f"| {g} | " + " | ".join(celdas) + " |")
    lin.append("| **Global** | " + " | ".join(
        f"{_f(res[v]['global']['cobertura_pct'])} % / {_f(res[v]['global']['ancho_medio'], 0)}" for v in variantes)
        + " |")
    if particion in PARTICIONES:
        lin.append("| Peor desviación de la partición | " + " | ".join(
            f"{_f(res[v]['peor_desviacion_por_particion_pp'][particion], 2)} pp" for v in variantes) + " |")
    return lin


def informe(r: dict) -> str:
    val, pru = r["resultados"]["validacion"], r["resultados"]["prueba"]
    vv = ["modelo", "v1"] + [c for c in CANDIDATAS if c in val]
    vp = ["modelo", "v1"] + (["v2"] if "v2" in pru else [])
    lin = [f"# Calibración conformal condicional de la banda P10-P90 ({r['model_id']})", "",
           f"Generado {r['generado']} con `scripts/calibrar_por_grupo.py` ({_f(r['duracion_s'])} s). Validación "
           f"(ventana de calibración): {r['validacion']}. Prueba reservada: {r['prueba_reservada']} (solo se reporta; "
           "no se usa para ajustar ni para elegir).", "",
           "Variantes: **modelo** = cuantiles P10/P90 del modelo sin calibrar; **v1** = calibración anterior, que "
           "queda como respaldo con CALIBRACION_BANDA=v1 (conformal móvil por ruta, 56 días previos, la misma función "
           "de la API); **mondrian_*** = un cuantil conformal por "
           "grupo, evaluado con validación cruzada por semanas ISO dentro de la validación. Ancho medio = P90 - P10 en "
           "pasajeros por hora.", "", f"Criterio: {r['criterio']}", "", "## Decisión", "",
           "| Candidata | Grupos | Peor desviación (pp) | Cobertura global | Ancho medio | Baja la peor desviación | "
           "No ensancha | Cumple |", "|---|---|---|---|---|---|---|---|"]
    for d in r["decision"]:
        lin.append(f"| {d['candidata']} | {d['grupos']} | {_f(d['peor_desviacion_pp'], 2)} | "
                   f"{_f(d['cobertura_global_pct'])} % | {_f(d['ancho_medio'], 0)} | "
                   f"{'sí' if d['baja_la_peor_desviacion'] else 'no'} | {'sí' if d['no_ensancha'] else 'no'} | "
                   f"{'sí' if d['cumple'] else 'no'} |")
    v1 = val["v1"]
    lin += ["", f"Referencia v1 en validación: peor desviación {_f(v1['peor_desviacion_pp'], 2)} pp, cobertura "
                f"{_f(v1['global']['cobertura_pct'])} %, ancho medio {_f(v1['global']['ancho_medio'], 0)} "
                f"(ajuste aplicado en el {_f(v1['dias_con_ajuste_pct'])} % de las horas: los primeros 14 días no "
                "tienen historia fuera de muestra).", ""]
    if r["adoptada"]:
        cal = r["calibracion"]
        lin += [f"**Adoptada: {r['adoptada']}** ({cal['nombre']}), ajustada con {cal['ajustado_con']}. "
                + (f"Archivo versionado: `{r['archivo']['archivo']}` (SHA-256 `{r['archivo']['sha256'][:16]}…`, "
                   "registrado en manifest.json, clave «calibracion»)." if r.get("archivo") else
                   "Para versionarla: `python scripts/calibrar_por_grupo.py --escribir`."), ""]
    else:
        lin += ["**Ninguna candidata cumple el criterio: se conserva v1** (el modelo y su calibración no cambian).", ""]
    lin += lectura(r)
    for titulo, res, variantes in (("Validación", val, vv), ("Prueba reservada (solo reporte)", pru, vp)):
        for particion, nombre in (("hora", "hora"), ("ruta", "ruta"), ("tipo", "tipo de día"),
                                  ("especial", "calendario especial")):
            lin += [f"## {titulo}: por {nombre}", ""] + _tabla(res, particion, variantes) + [""]
    lin += ["## El caso de las 6 h", ""]
    for parte in ("validacion", "prueba"):
        c = r["resultados"]["caso_6h"][parte] if "caso_6h" in r["resultados"] else None
        if not c:
            continue
        lin.append(f"**{'Validación' if parte == 'validacion' else 'Prueba reservada'}** (banda v1, razón P90 / P50 "
                   "de la hora):")
        lin.append("")
        lin.append("| Ruta | Mediana a las 6 h | P95 | Máximo | Fecha del máximo | P50 / P90 / real en el máximo | "
                   "Media y desviación observadas a las 6 h |")
        lin.append("|---|---|---|---|---|---|---|")
        for ruta, v in c.items():
            if ruta.startswith("horas_"):
                continue
            x = v["hora_6"]
            lin.append(f"| {ruta} | {_f(x['mediana'], 2)} | {_f(x['p95'], 2)} | {_f(x['maximo'], 2)} | "
                       f"{x['fecha_maximo']} | {_f(x['p50_en_el_maximo'], 0)} / {_f(x['p90_en_el_maximo'], 0)} / "
                       f"{_f(x['observado_en_el_maximo'], 0)} | {_f(x['media_observada_6h'], 0)} ± "
                       f"{_f(x['desviacion_observada_6h'], 0)} |")
        g = c["horas_con_razon_mayor_o_igual_2_9"]
        lin += ["", f"Horas con P90 / P50 ≥ 2,9: {g['n']} de {g['de']} (horas {g['horas']}; P50 mediano "
                    f"{_f(g['p50_mediano'], 1)} pasajeros; {_f(g['pct_en_dias_especiales'])} % en días especiales).",
                ""]
    return "\n".join(lin) + "\n"


if __name__ == "__main__":
    main()
