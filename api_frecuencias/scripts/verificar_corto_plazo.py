"""Comprueba que la API sirve el mismo modelo de corto plazo que se midió en la prueba reservada de E14 (spec v1.5 §9.2
«el preprocesamiento del entrenamiento se reproduce exactamente en Python», §9.3, RNF-011).

Con el código de la API (app/servicios/variables_corto_plazo.py y corto_plazo.py) y sus artefactos
(datos/modelos/corto_plazo), pronostica otra vez julio-diciembre de 2025 y lo compara con lo que guardó el experimento
la única vez que corrió su prueba (pronostico_corto_plazo/resultados): las predicciones por ruta y por sentido, los
totales por segmento y el WAPE de cada nivel y horizonte. No elige nada ni cambia ninguna cifra: si algo no coincide,
el script falla. Además comprueba que el camino de un día que usa la API (los 56 días anteriores y el día) da lo mismo
que el cálculo del periodo entero.

Uso (desde api_frecuencias/):  python scripts/verificar_corto_plazo.py [--resultados CARPETA] [--salida CARPETA]
Escribe docs/evidencias/modelo/corto_plazo_reproduccion.json y .md, y datos/corto_plazo/muestra_prueba_e14.csv: una
muestra fija (semilla 42) de las predicciones guardadas de la prueba, que tests/datos_ml/test_corto_plazo_modelo.py
vuelve a calcular en cada corrida de las pruebas (la integración continua no tiene la carpeta del experimento).
Con --solo-muestra escribe solo la muestra.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import corto_plazo as CP  # noqa: E402
from app.servicios import variables_corto_plazo as V  # noqa: E402

RESULTADOS = RAIZ.parent / "pronostico_corto_plazo" / "resultados"
TOLERANCIA = 0.006          # las predicciones guardadas están redondeadas a 2 decimales (float32)
DIAS_MUESTRA = 12
FILAS_MUESTRA = 20          # por ruta y nivel
COLUMNAS_MUESTRA = ["nivel", "ruta", "sentido", "fecha", "instante", "horizonte_min", "real", "pronostico", "p10",
                    "p90", "promedio_dia_hora"]


def escribir_muestra(resultados: Path) -> Path:
    """Una muestra fija de las predicciones que guardó la prueba de E14, por ruta y nivel (ruta y sentido)."""
    partes = []
    for nivel in ("ruta", "sentido"):
        g = pd.read_parquet(resultados / f"predicciones_{nivel}.parquet")
        if nivel == "ruta":
            g["sentido"] = None
        for _r, x in g.groupby("ruta", sort=True):
            partes.append(x.sample(FILAS_MUESTRA, random_state=V.SEMILLA).assign(nivel=nivel))
    m = pd.concat(partes, ignore_index=True)[COLUMNAS_MUESTRA].sort_values(["nivel", "ruta", "fecha", "instante"])
    destino = CP.carpeta_datos() / "muestra_prueba_e14.csv"
    m.to_csv(destino, index=False, lineterminator=chr(10))
    return destino


def pronostico_del_periodo(modelo: dict, r: V.Ruta, h: int) -> dict:
    """Ruta, segmento y sentido de toda la prueba con el código y los artefactos de la API."""
    a, b = V.rango_dias("prueba")
    b = min(b, len(r.cal) - 1)
    rr = r.recorte(a - V.ARRANQUE, b)
    man = modelo["manifiesto"]
    n_dias, i = b - a + 1, len(V.INSTANTES)
    out = {}
    for nivel in CP.NIVELES_CON_MODELO:
        v = V.variables(rr, nivel, h, man["conjunto"][nivel])
        g = v["forma"][2]
        ult = slice(len(v["y"]) - n_dias * i * g, len(v["y"]))
        p = np.clip(modelo["arboles"][CP.clave_artefacto(nivel, h, r.idruta)].predict(v["x"][ult]), 0,
                    None).astype(np.float32)
        vale = (v["ok"][ult] & ~np.isnan(v["base"]["promedio_dia_hora"][ult]))
        lo, hi = V.conformal_aplicar(p, man["banda"]["calibracion"][nivel][str(h)][r.nombre])
        out[nivel] = {"p": p.reshape(n_dias, i, g), "y": v["y"][ult].reshape(n_dias, i, g),
                      "vale": vale.reshape(n_dias, i, g), "p10": lo.reshape(n_dias, i, g),
                      "p90": hi.reshape(n_dias, i, g),
                      "base": {k: x[ult].reshape(n_dias, i, g) for k, x in v["base"].items()}}
    ida = (r.seg["sentido"] == "ida").to_numpy()
    seg = out["segmento"]

    def suma(x):
        return np.stack([x[:, :, ida].sum(axis=2), x[:, :, ~ida].sum(axis=2)], axis=2)

    p_sen = suma(seg["p"])
    lo, hi = V.conformal_aplicar(p_sen.reshape(-1), man["banda"]["calibracion"]["sentido"][str(h)][r.nombre])
    out["sentido"] = {"p": p_sen, "y": suma(seg["y"]), "vale": seg["vale"][:, :, :2], "p10": lo.reshape(p_sen.shape),
                      "p90": hi.reshape(p_sen.shape), "base": {k: suma(x) for k, x in seg["base"].items()}}
    out["fechas"] = pd.date_range(V.DIA0 + pd.Timedelta(days=int(a)), periods=n_dias, freq="D").date
    out["a"] = a
    return out


def tabla(o: dict, nivel: str, r: V.Ruta, h: int) -> pd.DataFrame:
    x = o[nivel]
    d, i, g = x["p"].shape
    t = pd.DataFrame({"ruta": r.nombre, "fecha": np.repeat(o["fechas"], i * g),
                      "instante": np.tile(np.repeat(V.INSTANTES, g), d), "horizonte_min": h,
                      "real_api": x["y"].reshape(-1), "pronostico_api": x["p"].reshape(-1),
                      "p10_api": x["p10"].reshape(-1), "p90_api": x["p90"].reshape(-1),
                      "promedio_api": x["base"]["promedio_dia_hora"].reshape(-1), "vale": x["vale"].reshape(-1)})
    if nivel == "sentido":
        t.insert(1, "sentido", np.tile(np.array(list(CP.SENTIDOS)), d * i))
    return t[t["vale"]].drop(columns="vale")


def comparar(api: pd.DataFrame, guardado: pd.DataFrame, llaves: list[str]) -> dict:
    m = guardado.merge(api, on=llaves, how="outer", indicator=True)
    solo = m["_merge"].value_counts().to_dict()
    ambos = m[m["_merge"] == "both"]
    out = {"filas_guardadas": int(len(guardado)), "filas_api": int(len(api)),
           "filas_en_las_dos": int(solo.get("both", 0)), "solo_guardadas": int(solo.get("left_only", 0)),
           "solo_api": int(solo.get("right_only", 0))}
    for col, col_api in (("real", "real_api"), ("pronostico", "pronostico_api"), ("p10", "p10_api"),
                         ("p90", "p90_api"), ("promedio_dia_hora", "promedio_api")):
        dif = (ambos[col].astype(float) - ambos[col_api].astype(float)).abs()
        out[col] = {"diferencia_maxima": round(float(dif.max()), 4),
                    "filas_fuera_de_tolerancia": int((dif > TOLERANCIA + 1e-6 * ambos[col].abs()).sum())}
    out["coincide"] = (out["solo_guardadas"] == 0 and out["solo_api"] == 0
                       and all(out[c]["filas_fuera_de_tolerancia"] == 0 for c in ("real", "pronostico", "p10", "p90",
                                                                                   "promedio_dia_hora")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--resultados", type=Path, default=RESULTADOS)
    ap.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "modelo")
    ap.add_argument("--solo-muestra", action="store_true")
    a = ap.parse_args()
    print(f"muestra: {escribir_muestra(a.resultados)}")
    if a.solo_muestra:
        return
    t0 = time.time()
    modelo = CP.cargar()
    prueba = json.loads((a.resultados / "prueba.json").read_text(encoding="utf-8"))
    guardado = {n: pd.read_parquet(a.resultados / f"predicciones_{n}.parquet") for n in ("ruta", "sentido")}
    seg_guardado = pd.read_csv(a.resultados / "segmentos_prueba.csv")
    tablas = {"ruta": [], "sentido": []}
    seg_api, por_nivel = [], {n: {} for n in V.NIVELES}
    celdas: dict = {n: {h: ([], []) for h in V.HORIZONTES} for n in V.NIVELES}
    muestra = {"dias": [], "coincide": True, "diferencia_maxima": 0.0}
    rng = np.random.default_rng(V.SEMILLA)
    for idruta in V.RUTAS:
        r = CP.serie(idruta)
        dias_prueba = np.flatnonzero(r.ok[V.rango_dias("prueba")[0]:]) + V.rango_dias("prueba")[0]
        elegidos = sorted(rng.choice(dias_prueba, DIAS_MUESTRA // len(V.RUTAS), replace=False).tolist())
        for h in V.HORIZONTES:
            o = pronostico_del_periodo(modelo, r, h)
            for nivel in ("ruta", "sentido"):
                tablas[nivel].append(tabla(o, nivel, r, h))
            for nivel in V.NIVELES:
                x = o[nivel]
                celdas[nivel][h][0].append(x["y"][x["vale"]])
                celdas[nivel][h][1].append(x["p"][x["vale"]])
            s = o["segmento"]
            vale = s["vale"]
            real = np.where(vale, s["y"], 0).sum(axis=(0, 1))
            pron = np.where(vale, s["p"], 0).sum(axis=(0, 1))
            seg_api.append(pd.DataFrame({"ruta": r.nombre, "nro_segmento": r.seg["nro_segmento"], "horizonte_min": h,
                                         "subidas_reales_api": real, "subidas_pronosticadas_api": pron}))
            for d in elegidos:     # el camino de un día de la API frente al periodo entero
                dia = CP._dia(modelo["model_id"], idruta, int(d), h)
                k = int(d) - o["a"]
                dif = max(float(np.nanmax(np.abs(dia[n]["p"] - o[n]["p"][k]))) for n in V.NIVELES)
                muestra["diferencia_maxima"] = max(muestra["diferencia_maxima"], dif)
                muestra["coincide"] &= dif == 0.0
                if h == 60:
                    muestra["dias"].append(f"{r.nombre} {CP.fecha_de_dia(int(d))}")
        print(f"  {r.nombre}: listo ({time.time() - t0:.0f} s)", flush=True)
    res: dict = {"generado_en": datetime.now(UTC).isoformat(timespec="seconds"), "model_id": modelo["model_id"],
                 "tolerancia": TOLERANCIA, "predicciones": {}, "wape": {}, "segmentos": {}, "camino_de_un_dia": muestra}
    llaves = {"ruta": ["ruta", "fecha", "instante", "horizonte_min"],
              "sentido": ["ruta", "sentido", "fecha", "instante", "horizonte_min"]}
    for nivel in ("ruta", "sentido"):
        api = pd.concat(tablas[nivel], ignore_index=True)
        res["predicciones"][nivel] = comparar(api, guardado[nivel], llaves[nivel])
    for nivel in V.NIVELES:
        for h in V.HORIZONTES:
            y = np.concatenate(celdas[nivel][h][0])
            p = np.concatenate(celdas[nivel][h][1])
            w_api = V.metricas(y, p)["wape"]
            w_pru = prueba["niveles"][nivel][str(h)]["todas_las_rutas"]["modelo"]["wape"]
            por_nivel[nivel][str(h)] = {"wape_api": w_api, "wape_prueba": w_pru,
                                        "coincide": abs(w_api - w_pru) <= 0.001}
    res["wape"] = por_nivel
    s = pd.concat(seg_api, ignore_index=True).merge(seg_guardado, on=["ruta", "nro_segmento", "horizonte_min"])
    dif = (s["subidas_pronosticadas_api"].round(1) - s["subidas_pronosticadas"]).abs()
    res["segmentos"] = {"filas": int(len(s)), "diferencia_maxima_total_pronosticado": round(float(dif.max()), 2),
                        "reales_iguales": bool((s["subidas_reales_api"] - s["subidas_reales"]).abs().max() < 0.5),
                        "coincide": bool(dif.max() <= 0.15)}
    res["coincide"] = (all(x["coincide"] for x in res["predicciones"].values())
                       and all(x["coincide"] for n in por_nivel.values() for x in n.values())
                       and res["segmentos"]["coincide"] and muestra["coincide"])
    res["segundos"] = round(time.time() - t0, 1)
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "corto_plazo_reproduccion.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
    (a.salida / "corto_plazo_reproduccion.md").write_text(markdown(res), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("coincide", "segundos")}, ensure_ascii=False))
    if not res["coincide"]:
        sys.exit("La API NO reproduce la prueba reservada de E14: ver corto_plazo_reproduccion.json")


def markdown(res: dict) -> str:
    def f(x, dec=2):
        return f"{x:,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")

    lineas = ["# La API reproduce la prueba reservada del pronóstico de corto plazo", "",
              f"Generado por `scripts/verificar_corto_plazo.py` el {res['generado_en'][:10]} con el modelo "
              f"`{res['model_id']}` (datos/modelos/corto_plazo). Detalle en `corto_plazo_reproduccion.json`.", "",
              "Con el código de variables de la API y sus artefactos se pronosticó otra vez julio-diciembre de 2025 "
              "y se comparó con lo que guardó el experimento E14 la única vez que corrió su prueba "
              "(`pronostico_corto_plazo/resultados`). No se eligió nada con esto ni cambió ninguna cifra.", "",
              f"**Resultado: {'todo coincide' if res['coincide'] else 'NO coincide'}.**", "",
              "| Comparación | Filas | Diferencia máxima | Coincide |", "|---|---|---|---|"]
    for nivel, x in res["predicciones"].items():
        lineas.append(f"| Predicciones por {nivel} (pronóstico, P10, P90, real y promedio) | "
                      f"{f(x['filas_en_las_dos'], 0)} "
                      f"de {f(x['filas_guardadas'], 0)} | {f(x['pronostico']['diferencia_maxima'], 4)} subidas | "
                      f"{'sí' if x['coincide'] else 'no'} |")
    s = res["segmentos"]
    lineas.append(f"| Total pronosticado por segmento y horizonte | {f(s['filas'], 0)} | "
                  f"{f(s['diferencia_maxima_total_pronosticado'], 2)} subidas | {'sí' if s['coincide'] else 'no'} |")
    m = res["camino_de_un_dia"]
    lineas.append(f"| Camino de un día de la API frente al periodo entero ({len(m['dias'])} días) | — | "
                  f"{f(m['diferencia_maxima'], 4)} | {'sí' if m['coincide'] else 'no'} |")
    lineas += ["", "| Nivel | Horizonte | WAPE con la API (%) | WAPE de la prueba (%) | Coincide |",
               "|---|---|---|---|---|"]
    for nivel, por_h in res["wape"].items():
        for h, x in por_h.items():
            lineas.append(f"| {nivel} | {h} min | {f(x['wape_api'], 3)} | {f(x['wape_prueba'], 3)} | "
                          f"{'sí' if x['coincide'] else 'no'} |")
    lineas += ["", f"Tolerancia de las predicciones: {f(res['tolerancia'], 3)} subidas (el experimento las guardó "
               "redondeadas a dos decimales). Días del camino de un día: " + ", ".join(m["dias"]) + ".", ""]
    return "\n".join(lineas)


if __name__ == "__main__":
    with CP.sin_calidad():      # la prueba se midió con los datos tal cual: sin la regla VAL-009 de la API
        main()
