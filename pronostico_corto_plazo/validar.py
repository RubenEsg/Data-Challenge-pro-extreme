"""Validación (2025-01-01 a 2025-06-30): líneas base del enunciado, variantes del modelo y ELECCIÓN. No toca la prueba.

Todo se entrena con 2023-01-01 a 2024-12-31 y se mide en la validación. Las reglas de elección están en PROTOCOLO.md
(sección 5) y se aplican aquí tal cual:
  A. Conjunto de información por nivel (semanal, con_hoy, completo): el de menor WAPE medio de los tres horizontes.
  B. Hiperparámetros por nivel, entre las tres configuraciones de REJILLA: la de menor WAPE medio.
  C. Estructura: sentido directo o suma de segmentos; segmento directo o conciliado con el pronóstico de la ruta.
  D. Banda P10-P90: cuantiles conformales por tramo del pronóstico, ajustados con los errores de la validación.
Escribe resultados/validacion.json (todas las cifras) y resultados/seleccion.json (lo elegido, que probar.py lee).

Uso (desde esta carpeta):  python validar.py            python validar.py --rapido  (solo comprueba que corre)
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np

import comun as C

SUBMUESTRA = {"ruta": 1.0, "sentido": 1.0, "segmento": 0.5}     # en A y B el nivel de segmento usa la mitad de las filas
REJILLA = {
    "base": {},
    "arboles_pequenos": {"num_leaves": 31, "min_child_samples": 200, "n_estimators": 600},
    "arboles_grandes": {"num_leaves": 127, "min_child_samples": 50, "n_estimators": 300},
}
BASES = ("promedio_dia_hora", "ultima_semana", "persistencia")
RAPIDO = "--rapido" in sys.argv


def juntar(pred: dict, nivel: str, h: int, clave: str, campo: str = "p"):
    """Lo real y un pronóstico de las tres rutas, aplanados (solo celdas evaluables), con instante y día."""
    ys, ps, ins, ds = [], [], [], []
    for idruta in C.RUTAS:
        o = pred[(nivel, h, clave, idruta)]
        y, p, inst, dia = C.aplanar(o["y"], o["p"] if campo == "p" else o["base"][campo])
        ys.append(y), ps.append(p), ins.append(inst), ds.append(dia)
    return np.concatenate(ys), np.concatenate(ps), np.concatenate(ins), np.concatenate(ds)


def resumen(pred: dict, nivel: str, h: int, clave: str, campo: str = "p") -> dict:
    y, p, _, _ = juntar(pred, nivel, h, clave, campo)
    out = C.metricas(y, p)
    out["por_ruta_wape"] = {}
    for idruta, nombre in C.RUTAS.items():
        o = pred[(nivel, h, clave, idruta)]
        yy, pp, _, _ = C.aplanar(o["y"], o["p"] if campo == "p" else o["base"][campo])
        out["por_ruta_wape"][nombre] = C.metricas(yy, pp).get("wape")
    return out


def wape_medio(tabla: dict) -> float:
    return round(float(np.mean([tabla[str(h)]["wape"] for h in C.HORIZONTES])), 4)


def main() -> None:
    t0 = time.time()
    C.RES.mkdir(exist_ok=True)
    rutas = {i: C.cargar_ruta(i) for i in C.RUTAS}
    horizontes = [60] if RAPIDO else list(C.HORIZONTES)
    niveles = C.NIVELES
    res: dict = {"generado": time.strftime("%Y-%m-%d %H:%M"), "periodos": C.PERIODOS, "instantes": "04:00 a 21:00 cada 30 min",
                 "hiper_base": C.HIPER, "rejilla": REJILLA, "submuestra_en_A_y_B": SUBMUESTRA,
                 "dias_con_datos": {r.nombre: {p: int(r.ok[slice(C.rango_dias(p)[0], C.rango_dias(p)[1] + 1)].sum())
                                               for p in C.PERIODOS} for r in rutas.values()},
                 "A_conjunto": {}, "B_hiper": {}, "C_estructura": {}, "lineas_base": {}}
    pred: dict = {}

    def correr(nivel, h, conjunto, hiper_nombre="base", sub=None, clave=None):
        clave = clave or conjunto
        for idruta, r in rutas.items():
            o = C.pronosticar(r, nivel, h, conjunto, hiper=REJILLA[hiper_nombre],
                              submuestra=(SUBMUESTRA[nivel] if sub is None else sub) * (0.2 if RAPIDO else 1.0))
            pred[(nivel, h, clave, idruta)] = o
            print(f"  {nivel:9s} h={h:3d} {clave:28s} {r.nombre:9s} filas {o['n_entrenamiento']:>9,} "
                  f"variables {o['n_variables']:2d}  {o['segundos']:6.1f} s", flush=True)

    # ---------------------------------------------------------------- A. conjunto de información
    for nivel in niveles:
        res["A_conjunto"][nivel] = {}
        res["lineas_base"][nivel] = {}
        for b in BASES:
            res["lineas_base"][nivel][b] = {}
        for conjunto in C.CONJUNTOS:
            res["A_conjunto"][nivel][conjunto] = {}
            for h in horizontes:
                correr(nivel, h, conjunto)
                res["A_conjunto"][nivel][conjunto][str(h)] = resumen(pred, nivel, h, conjunto)
                if conjunto == C.CONJUNTOS[0]:      # las líneas base son las mismas con cualquier conjunto
                    for b in BASES:
                        res["lineas_base"][nivel][b][str(h)] = resumen(pred, nivel, h, conjunto, b)
                soltar(pred, nivel, h, conjunto)
        if not RAPIDO:
            for conjunto in C.CONJUNTOS:
                res["A_conjunto"][nivel][conjunto]["wape_medio"] = wape_medio(res["A_conjunto"][nivel][conjunto])
            for b in BASES:
                res["lineas_base"][nivel][b]["wape_medio"] = wape_medio(res["lineas_base"][nivel][b])
        tabla = res["A_conjunto"][nivel]
        print(f"A {nivel}: " + ", ".join(f"{c} {tabla[c].get('wape_medio', tabla[c][str(horizontes[0])]['wape'])}"
                                         for c in C.CONJUNTOS), flush=True)
        guardar_parcial(res)
    if RAPIDO:
        print(json.dumps({n: {c: v[str(60)]["wape"] for c, v in res["A_conjunto"][n].items()} for n in niveles}, indent=1))
        print({n: {b: res["lineas_base"][n][b]["60"]["wape"] for b in BASES} for n in niveles})
        print(f"listo (rápido) en {time.time() - t0:.0f} s")
        return
    elegido = {n: min(C.CONJUNTOS, key=lambda c: res["A_conjunto"][n][c]["wape_medio"]) for n in niveles}

    # ---------------------------------------------------------------- B. hiperparámetros
    hiper = {}
    for nivel in niveles:
        res["B_hiper"][nivel] = {"base": {str(h): res["A_conjunto"][nivel][elegido[nivel]][str(h)] for h in horizontes}}
        for nombre in REJILLA:
            if nombre == "base":
                continue
            res["B_hiper"][nivel][nombre] = {}
            for h in horizontes:
                correr(nivel, h, elegido[nivel], nombre, clave=f"hiper:{nombre}")
                res["B_hiper"][nivel][nombre][str(h)] = resumen(pred, nivel, h, f"hiper:{nombre}")
                soltar(pred, nivel, h, f"hiper:{nombre}")
        for nombre in REJILLA:
            res["B_hiper"][nivel][nombre]["wape_medio"] = wape_medio(res["B_hiper"][nivel][nombre])
        hiper[nivel] = min(REJILLA, key=lambda k: res["B_hiper"][nivel][k]["wape_medio"])
        print(f"B {nivel}: " + ", ".join(f"{k} {res['B_hiper'][nivel][k]['wape_medio']}" for k in REJILLA), flush=True)
        guardar_parcial(res)

    # ---------------------------------------------------------------- modelos elegidos, con todas las filas
    final = {}
    for nivel in niveles:
        clave = "final"
        for h in horizontes:
            if SUBMUESTRA[nivel] < 1:
                correr(nivel, h, elegido[nivel], hiper[nivel], sub=1.0, clave=clave)
            else:
                origen = elegido[nivel] if hiper[nivel] == "base" else f"hiper:{hiper[nivel]}"
                for idruta in C.RUTAS:
                    pred[(nivel, h, clave, idruta)] = pred[(nivel, h, origen, idruta)]
        final[nivel] = {str(h): resumen(pred, nivel, h, clave) for h in horizontes}
        final[nivel]["wape_medio"] = wape_medio(final[nivel])
    res["elegidos_con_todas_las_filas"] = final

    # ---------------------------------------------------------------- C. estructura
    # sentido: directo frente a la suma de los segmentos de cada sentido
    estr = {"sentido": {"directo": final["sentido"], "suma_de_segmentos": {}},
            "segmento": {"directo": final["segmento"], "conciliado_con_la_ruta": {}, "reparto_fijo_de_la_ruta": {}}}
    for h in horizontes:
        for idruta, r in rutas.items():
            seg = pred[("segmento", h, "final", idruta)]
            ida = (r.seg["sentido"] == "ida").to_numpy()
            suma = np.stack([seg["p"][:, :, ida].sum(axis=2), seg["p"][:, :, ~ida].sum(axis=2)], axis=2)
            sen = pred[("sentido", h, "final", idruta)]
            pred[("sentido", h, "suma", idruta)] = {"y": sen["y"], "p": np.where(np.isnan(sen["y"]), np.nan, suma), "base": sen["base"]}
            rut = pred[("ruta", h, "final", idruta)]["p"]                       # (días, instantes, 1)
            total = seg["p"].sum(axis=2, keepdims=True)
            with np.errstate(invalid="ignore", divide="ignore"):
                conc = np.where(total > 0, seg["p"] * rut / total, seg["p"])
                m8 = seg["base"]["promedio_dia_hora"]
                tm8 = np.nansum(m8, axis=2, keepdims=True)
                fijo = np.where(tm8 > 0, rut * m8 / tm8, m8)
            sin = np.isnan(seg["y"])
            pred[("segmento", h, "conciliado", idruta)] = {"y": seg["y"], "p": np.where(sin, np.nan, conc), "base": seg["base"]}
            pred[("segmento", h, "reparto_fijo", idruta)] = {"y": seg["y"], "p": np.where(sin, np.nan, fijo), "base": seg["base"]}
        estr["sentido"]["suma_de_segmentos"][str(h)] = resumen(pred, "sentido", h, "suma")
        estr["segmento"]["conciliado_con_la_ruta"][str(h)] = resumen(pred, "segmento", h, "conciliado")
        estr["segmento"]["reparto_fijo_de_la_ruta"][str(h)] = resumen(pred, "segmento", h, "reparto_fijo")
    for nivel in estr:
        for k in estr[nivel]:
            estr[nivel][k]["wape_medio"] = wape_medio(estr[nivel][k])
    res["C_estructura"] = estr
    estructura = {"sentido": min(("directo", "suma_de_segmentos"), key=lambda k: estr["sentido"][k]["wape_medio"]),
                  "segmento": min(("directo", "conciliado_con_la_ruta"), key=lambda k: estr["segmento"][k]["wape_medio"])}
    clave_de = {"directo": "final", "suma_de_segmentos": "suma", "conciliado_con_la_ruta": "conciliado"}

    # ---------------------------------------------------------------- D. banda conformal con los errores de la validación
    banda = {}
    res["D_banda_en_validacion"] = {}
    for nivel in niveles:
        clave = "final" if nivel == "ruta" else clave_de[estructura[nivel]]
        banda[nivel] = {}
        res["D_banda_en_validacion"][nivel] = {}
        for h in horizontes:
            banda[nivel][str(h)] = {}
            cob = []
            for idruta, nombre in C.RUTAS.items():
                o = pred[(nivel, h, clave, idruta)]
                y, p, _, _ = C.aplanar(o["y"], o["p"])
                cal = C.conformal_ajustar(y, p)
                banda[nivel][str(h)][nombre] = cal
                lo, hi = C.conformal_aplicar(p, cal)
                cob.append(C.cobertura(y, lo, hi)["cobertura_pct"])
            res["D_banda_en_validacion"][nivel][str(h)] = {"cobertura_pct_por_ruta": cob}

    seleccion = {"generado": res["generado"], "conjunto": elegido,
                 "hiper": {n: {"nombre": hiper[n], "valores": dict(C.HIPER, **REJILLA[hiper[n]])} for n in niveles},
                 "estructura": estructura, "banda": banda,
                 "regla": "PROTOCOLO.md, sección 5; todo se eligió con la validación (2025-01-01 a 2025-06-30)"}
    res["seleccion"] = {k: seleccion[k] for k in ("conjunto", "estructura")} | {"hiper": {n: hiper[n] for n in niveles}}
    res["segundos"] = round(time.time() - t0, 1)
    (C.RES / "validacion.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (C.RES / "seleccion.json").write_text(json.dumps(seleccion, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["seleccion"], ensure_ascii=False, indent=1))
    print(f"listo en {(time.time() - t0) / 60:.1f} min")


def soltar(pred: dict, nivel: str, h: int, clave: str) -> None:
    """Libera los pronósticos por segmento de una variante ya medida (lo elegido se vuelve a entrenar con todas las
    filas); los de ruta y sentido son pequeños y se conservan."""
    if nivel == "segmento":
        for idruta in C.RUTAS:
            pred.pop((nivel, h, clave, idruta), None)


def guardar_parcial(res: dict) -> None:
    (C.RES / "validacion_parcial.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
