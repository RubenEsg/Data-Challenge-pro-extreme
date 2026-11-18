"""Comprueba que ninguna variable usa información posterior al instante del pronóstico (§9.3 de la especificación).

Para varios días e instantes t elegidos con semilla, cambia todo lo que ocurre de t en adelante (las subidas de todos
los segmentos y las salidas, ese día y los siguientes) y vuelve a calcular las variables. Tienen que quedar idénticas,
valor por valor, las variables y las tres líneas base de las filas de ese día hasta el instante t y de todos los días
anteriores, en los tres niveles, los tres horizontes y los tres conjuntos de información, sin retraso y con 30 minutos
de retraso en la captura. El objetivo de la fila del instante t sí tiene que cambiar: así se sabe que el cambio se
aplicó. No entrena nada y no mira ningún resultado.

Para acotar la memoria, el nivel de segmento se comprueba con uno de cada seis segmentos de la ruta (el código de las
variables es el mismo). Escribe resultados/comprobacion_fuga.json y termina con código 1 si encuentra diferencias.

Uso (desde esta carpeta):  python comprobar_fuga.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time

import numpy as np
import pandas as pd

import comun as C

N_CAMBIOS = 3          # días e instantes alterados por ruta
PASO_SEGMENTOS = 6     # en el nivel de segmento se usa uno de cada seis
LATENCIAS = (0, 2)     # bloques de 15 minutos de retraso en la captura


def alterar(r: C.Ruta, dia: int, bloque: int) -> C.Ruta:
    """La misma ruta con otro futuro: cambia las subidas y las salidas del día `dia` desde el bloque `bloque` y las
    de todos los días siguientes. Lo anterior queda intacto."""
    y, sal = r.y.copy(), r.sal.copy()
    y[dia, bloque:, :] = y[dia, bloque:, :] * 3 + 7
    y[dia + 1:] = y[dia + 1:] * 2 + 5
    sal[dia, bloque:] = sal[dia, bloque:] * 2 + 3
    sal[dia + 1:] = sal[dia + 1:] + 2
    return dataclasses.replace(r, y=y, sal=sal, ok=C.dias_con_datos(y.sum(axis=(1, 2))))


def iguales(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Igualdad exacta, con NaN igual a NaN."""
    return (a == b) | (np.isnan(a) & np.isnan(b))


def main() -> None:
    t0 = time.time()
    rng = np.random.default_rng(C.SEMILLA)
    res = {"generado": time.strftime("%Y-%m-%d %H:%M"), "cambios_por_ruta": N_CAMBIOS, "latencias_min": [15 * x for x in LATENCIAS],
           "segmentos_en_el_nivel_de_segmento": f"uno de cada {PASO_SEGMENTOS}", "comprobaciones": 0, "filas_comparadas": 0,
           "valores_comparados": 0, "diferencias": 0, "objetivo_sin_cambiar": 0, "cambios": {}, "detalle": []}
    for idruta in C.RUTAS:
        completa = C.cargar_ruta(idruta)
        y_rala = completa.y[:, :, ::PASO_SEGMENTOS].copy()
        rala = dataclasses.replace(completa, y=y_rala, seg=completa.seg.iloc[::PASO_SEGMENTOS].reset_index(drop=True),
                                   ok=C.dias_con_datos(y_rala.sum(axis=(1, 2))))
        con_datos = np.flatnonzero(completa.ok[C.ARRANQUE:-1] & rala.ok[C.ARRANQUE:-1]) + C.ARRANQUE
        cambios = [(int(rng.choice(con_datos)), int(rng.choice(C.INSTANTES))) for _ in range(N_CAMBIOS)]
        res["cambios"][completa.nombre] = [{"dia": str((C.DIA0 + pd.Timedelta(days=d)).date()), "bloque": b,
                                            "hora": f"{b // 4:02d}:{b % 4 * 15:02d}"} for d, b in cambios]
        for nivel in C.NIVELES:
            r = rala if nivel == "segmento" else completa
            otros = [alterar(r, dia, bloque) for dia, bloque in cambios]
            for h in C.HORIZONTES:
                for conjunto in C.CONJUNTOS:
                    for latencia in LATENCIAS:
                        a = C.variables(r, nivel, h, conjunto, latencia)
                        for (dia, bloque), otro in zip(cambios, otros, strict=True):
                            b = C.variables(otro, nivel, h, conjunto, latencia)
                            antes = (a["dia"] < dia) | ((a["dia"] == dia) & (a["instante"] <= bloque))
                            dif = int((~iguales(a["x"][antes], b["x"][antes])).sum())
                            for nombre in a["base"]:
                                dif += int((~iguales(a["base"][nombre][antes], b["base"][nombre][antes])).sum())
                            fila_t = (a["dia"] == dia) & (a["instante"] == bloque)
                            cambia = bool((a["y"][fila_t] != b["y"][fila_t]).any())
                            res["comprobaciones"] += 1
                            res["filas_comparadas"] += int(antes.sum())
                            res["valores_comparados"] += int(antes.sum()) * (a["x"].shape[1] + len(a["base"]))
                            res["diferencias"] += dif
                            res["objetivo_sin_cambiar"] += int(not cambia)
                            if dif or not cambia:
                                columnas = [n for j, n in enumerate(a["nombres"])
                                            if (~iguales(a["x"][antes, j], b["x"][antes, j])).any()]
                                res["detalle"].append({"ruta": r.nombre, "nivel": nivel, "horizonte": h, "conjunto": conjunto,
                                                       "latencia_min": 15 * latencia, "dia": dia, "bloque": bloque,
                                                       "diferencias": dif, "variables": columnas, "objetivo_cambia": cambia})
            print(f"{completa.nombre:9s} {nivel:9s} comprobaciones {res['comprobaciones']:4d} · diferencias {res['diferencias']}", flush=True)
    res["segundos"] = round(time.time() - t0, 1)
    res["conclusion"] = ("ninguna variable ni línea base cambia al alterar el futuro"
                         if not res["diferencias"] and not res["objetivo_sin_cambiar"] else "HAY DIFERENCIAS: revisar «detalle»")
    (C.RES / "comprobacion_fuga.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "detalle"}, ensure_ascii=False, indent=1))
    if res["diferencias"] or res["objetivo_sin_cambiar"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
