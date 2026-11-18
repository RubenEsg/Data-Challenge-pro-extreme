"""Arma el panel de demanda por ruta, sentido, segmento y bloque de 15 minutos de 2023 a 2025 (capa analítica propia).

Por qué: la tabla `timbradas_segmentos` de la base del reto solo trae enero y febrero de 2023 (58 días). Con la misma
regla con que Extreme la llena (scripts de Extreme, «5. cargue inicial timbradas_segmentos.sql» y «7. trigger de
conteo.sql»: cada evento de conteo va al segmento activo MÁS CERCANO de su ruta), aquí se asigna cada evento de subida
de los tres años a uno de los 386 segmentos oficiales de 500 m (`rutas_segmentos`) y se suma por el instante en que
ocurrió la subida (bloques de 15 minutos, como el disparador en vivo de Extreme).

Entradas (exportaciones de solo lectura de la base del reto; no viajan en la entrega):
  datos/eventos_subida/eventos_*.parquet   eventos de conteo con cantidad_subida > 0 (exportar_eventos_subida.py)
  datos/rutas_segmentos.parquet            los segmentos oficiales con su geometría
  datos/progvehiculos.parquet              la ruta y los instantes de cada viaje
  datos/timbradas_segmentos.parquet        la tabla de Extreme (58 días), solo para verificar la regla
Salidas (en panel/, sí viajan en la entrega):
  subidas_segmento_15min.parquet  idruta, dia, bloque (0-95, bloque de 15 min del instante de la subida), nro_segmento,
                                  subidas (solo celdas con subidas; las demás valen 0)
  segmentos.csv                   idruta, ruta, id_segmento, nro_segmento, sentido, km_inicio, longitud_m, lat, lon y
                                  minutos_desde_inicio (mediana, entre las subidas de 2023 y 2024, del tiempo que
                                  lleva el viaje cuando pasa por el segmento: sirve para saber qué salidas ya
                                  hechas llegarán al segmento en la ventana que se pronostica)
  salidas_15min.parquet           idruta, dia, bloque, salidas (viajes que iniciaron en el bloque: oferta ya observada)
  calendario.csv                  por fecha: tipo de día, festivos, Carnaval, Semana Santa, vacaciones y calendario académico
  verificacion_extreme.json       la asignación propia frente a timbradas_segmentos, viaje por viaje, y los totales

El sentido no viene en los datos: la geometría de cada ruta es el ciclo completo. Como en la API, «ida» son los
segmentos cuyo punto medio cae en la primera mitad de la longitud del ciclo y «regreso» el resto (aproximación declarada).

Uso (desde la raíz del proyecto):  python EntregaFinal/pronostico_corto_plazo/preparar_panel.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

AQUI = Path(__file__).resolve().parent
PROYECTO = AQUI.parents[1]
DATOS = PROYECTO / "datos"
API_DATOS = AQUI.parent / "api_frecuencias" / "datos"
PANEL = AQUI / "panel"
RUTAS = {2: "SILENCIO", 16: "CRA 54", 21: "CL 72"}
DESDE, HASTA = pd.Timestamp("2023-01-01"), pd.Timestamp("2025-12-31")
FIN_ENTRENAMIENTO = pd.Timestamp("2024-12-31")   # lo que se estima de los datos (tiempos de viaje) usa solo hasta aquí
MIN_MAX = 480                                      # minutos de viaje que se consideran (un ciclo dura unas 4 horas)


def leer_segmentos() -> tuple[pd.DataFrame, dict]:
    """Los segmentos activos de las tres rutas con su sentido, y un árbol de vértices por ruta (cada vértice sabe de qué
    segmento es). Las geometrías traen un vértice cada 20 cm, así que el vértice más cercano es el punto más cercano
    de la línea con un error de 10 cm como mucho."""
    rs = pd.read_parquet(DATOS / "rutas_segmentos.parquet")
    rs = rs[rs["idruta"].isin(RUTAS) & rs["activo"]].sort_values(["idruta", "nro_segmento"])
    filas, arboles = [], {}
    for idruta, g in rs.groupby("idruta"):
        acum = g["longitud_m"].cumsum().to_numpy()
        largo = g["longitud_m"].to_numpy()
        medio, total = acum - largo / 2, largo.sum()
        xs, ys, de = [], [], []
        for i, r in enumerate(g.itertuples()):
            texto = r.geom_segmento[r.geom_segmento.index("(") + 1: r.geom_segmento.rindex(")")].replace("(", "").replace(")", "")
            xy = np.array([p.split() for p in texto.split(",")], dtype=float)
            xs.append(xy[:, 0])
            ys.append(xy[:, 1])
            de.append(np.full(len(xy), r.nro_segmento, dtype=np.int16))
            filas.append({"idruta": int(idruta), "ruta": RUTAS[int(idruta)], "id_segmento": int(r.id),
                          "nro_segmento": int(r.nro_segmento), "sentido": "ida" if medio[i] <= total / 2 else "regreso",
                          "km_inicio": round(float(acum[i] - largo[i]) / 1000, 3), "longitud_m": round(float(largo[i]), 1),
                          "lat": round(float(xy[len(xy) // 2, 1]), 6), "lon": round(float(xy[len(xy) // 2, 0]), 6)})
        x, y = np.concatenate(xs), np.concatenate(ys)
        arboles[int(idruta)] = (cKDTree(np.c_[x, y]), np.concatenate(de), x, y)
    return pd.DataFrame(filas), arboles


def asignar(ev: pd.DataFrame, arboles: dict) -> pd.DataFrame:
    """nro_segmento del segmento más cercano (la regla de Extreme: distancia plana en grados, como `<->` de PostGIS
    sobre geometrías 4326) y la distancia en metros al vértice más cercano."""
    ev = ev.copy()
    ev["nro_segmento"] = np.int16(-1)
    ev["dist_m"] = np.nan
    for idruta, (arbol, de, x, y) in arboles.items():
        m = (ev["idruta"] == idruta).to_numpy() & ev["lat"].notna().to_numpy()
        if not m.any():
            continue
        lon, lat = ev.loc[m, "lon"].to_numpy(), ev.loc[m, "lat"].to_numpy()
        _, idx = arbol.query(np.c_[lon, lat], k=1, workers=-1)
        ev.loc[m, "nro_segmento"] = de[idx]
        dx = (lon - x[idx]) * 111_320 * np.cos(np.radians(lat))
        dy = (lat - y[idx]) * 110_574
        ev.loc[m, "dist_m"] = np.hypot(dx, dy)
    return ev


def calendario() -> pd.DataFrame:
    """El calendario por fecha de la API (tipo de día, festivo, Carnaval, Semana Santa, vacaciones, Navidad, 1 de enero)
    y el calendario académico (receso escolar y vacaciones universitarias) de datos/calendario_academico.csv."""
    d = pd.read_parquet(API_DATOS / "demanda_horaria.parquet")
    cols = ["tipo_dia", "festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero"]
    cal = d.drop_duplicates("fecha")[["fecha"] + cols].copy()
    cal["fecha"] = pd.to_datetime(cal["fecha"])
    cal = cal.set_index("fecha").reindex(pd.date_range(DESDE, HASTA, freq="D"))
    if cal[cols].isna().any().any():
        sys.exit("el calendario de la API no cubre todas las fechas")
    ac = pd.read_csv(API_DATOS / "calendario_academico.csv", parse_dates=["inicio", "fin"])
    cal["vac_escolar"], cal["vac_univ"] = 0, 1
    for r in ac.itertuples():
        en = (cal.index >= r.inicio) & (cal.index <= r.fin)
        if r.tipo == "escolar_receso":
            cal.loc[en, "vac_escolar"] = 1
        elif r.tipo == "universitario_clases":
            cal.loc[en, "vac_univ"] = 0
    return cal.astype(int).rename_axis("fecha").reset_index()


def main() -> None:
    t0 = time.time()
    PANEL.mkdir(exist_ok=True)
    seg, arboles = leer_segmentos()
    pv = pd.read_parquet(DATOS / "progvehiculos.parquet", columns=["idprogramacion", "idruta", "fechainicio", "fechafin"])
    pv = pv[pv["idruta"].isin(RUTAS)]
    ruta_de = pv.set_index("idprogramacion")["idruta"]
    inicio_de = (pv.set_index("idprogramacion")["fechainicio"] - pd.Timestamp("1970-01-01")).dt.total_seconds()
    n_seg = seg.groupby("idruta")["nro_segmento"].max().to_dict()
    histo = {r: np.zeros((n + 1, MIN_MAX + 1), dtype=np.int64) for r, n in n_seg.items()}   # [segmento, minuto]
    ts = pd.read_parquet(DATOS / "timbradas_segmentos.parquet", columns=["id_segmento", "id_viaje", "fecha", "subidas"])
    viajes_ext = set(ts["id_viaje"].unique())

    archivos = sorted((DATOS / "eventos_subida").glob("eventos_*.parquet"))
    if not archivos:
        sys.exit("faltan los eventos: corra exportar_eventos_subida.py")
    partes, propias = [], []
    tot = {"eventos": 0, "subidas": 0, "sin_ruta": 0, "sin_posicion": 0, "fuera_de_fechas": 0, "a_mas_de_100_m": 0,
           "a_mas_de_500_m": 0}
    huella = hashlib.sha256()
    for i, f in enumerate(archivos, 1):
        ev = pd.read_parquet(f)
        huella.update(f.name.encode() + str(len(ev)).encode() + str(int(ev["subidas"].sum())).encode())
        ev["idruta"] = ev["idprogramacion"].map(ruta_de)
        tot["eventos"] += len(ev)
        tot["subidas"] += int(ev["subidas"].sum())
        tot["sin_ruta"] += int(ev.loc[ev["idruta"].isna(), "subidas"].sum())
        ev = ev[ev["idruta"].notna()].copy()
        ev["idruta"] = ev["idruta"].astype(int)
        ev = asignar(ev, arboles)
        tot["sin_posicion"] += int(ev.loc[ev["nro_segmento"] < 0, "subidas"].sum())
        tot["a_mas_de_100_m"] += int(ev.loc[ev["dist_m"] > 100, "subidas"].sum())
        tot["a_mas_de_500_m"] += int(ev.loc[ev["dist_m"] > 500, "subidas"].sum())
        cuando = pd.to_datetime(ev["t"], unit="s")
        ev["dia"] = cuando.dt.normalize()
        ev["bloque"] = ((cuando.dt.hour * 60 + cuando.dt.minute) // 15).astype(np.int8)
        en = ev["dia"].between(DESDE, HASTA)
        tot["fuera_de_fechas"] += int(ev.loc[~en, "subidas"].sum())
        ev = ev[en]
        # tiempo de viaje hasta cada segmento (solo con el periodo de entrenamiento)
        tv = ev[(ev["dia"] <= FIN_ENTRENAMIENTO) & (ev["nro_segmento"] > 0)]
        minutos = (tv["t"] - tv["idprogramacion"].map(inicio_de)) / 60
        tv = tv[minutos.between(0, MIN_MAX)].assign(minuto=minutos[minutos.between(0, MIN_MAX)].astype(int))
        for r, g in tv.groupby("idruta"):
            np.add.at(histo[int(r)], (g["nro_segmento"].to_numpy(), g["minuto"].to_numpy()), g["subidas"].to_numpy())
        partes.append(ev.groupby(["idruta", "dia", "bloque", "nro_segmento"], as_index=False)["subidas"].sum())
        mios = ev[ev["idprogramacion"].isin(viajes_ext)]
        if len(mios):
            propias.append(mios.groupby(["idprogramacion", "idruta", "nro_segmento"], as_index=False)["subidas"].sum())
        if i % 10 == 0 or i == len(archivos):
            print(f"[{i}/{len(archivos)}] {tot['subidas']:,} subidas en {time.time() - t0:.0f} s", flush=True)

    panel = pd.concat(partes).groupby(["idruta", "dia", "bloque", "nro_segmento"], as_index=False)["subidas"].sum()
    panel = panel.sort_values(["idruta", "dia", "bloque", "nro_segmento"]).reset_index(drop=True)
    panel = panel.astype({"idruta": np.int8, "bloque": np.int8, "nro_segmento": np.int16, "subidas": np.int32})
    panel["dia"] = panel["dia"].dt.date
    panel.to_parquet(PANEL / "subidas_segmento_15min.parquet", index=False, compression="zstd")
    # mediana ponderada del tiempo de viaje hasta el segmento; los segmentos con pocas subidas se interpolan por km
    seg["minutos_desde_inicio"] = np.nan
    for r, h in histo.items():
        acum = h.cumsum(axis=1)
        total = acum[:, -1]
        med = (acum >= (total[:, None] + 1) // 2).argmax(axis=1).astype(float)
        med[total < 50] = np.nan
        m = (seg["idruta"] == r).to_numpy()
        v = pd.Series(med[seg.loc[m, "nro_segmento"].to_numpy()], index=seg.loc[m, "km_inicio"].to_numpy())
        seg.loc[m, "minutos_desde_inicio"] = v.interpolate(method="index", limit_direction="both").to_numpy()
    seg["minutos_desde_inicio"] = seg["minutos_desde_inicio"].round(1)
    seg.to_csv(PANEL / "segmentos.csv", index=False, lineterminator="\n")

    # oferta ya observada: viajes que iniciaron en cada bloque (instante real de inicio)
    ini = pv[pv["fechainicio"].notna()].copy()
    ini["dia"] = ini["fechainicio"].dt.normalize()
    ini["bloque"] = ((ini["fechainicio"].dt.hour * 60 + ini["fechainicio"].dt.minute) // 15).astype(np.int8)
    ini = ini[ini["dia"].between(DESDE, HASTA)]
    sal = ini.groupby(["idruta", "dia", "bloque"], as_index=False).size().rename(columns={"size": "salidas"})
    sal = sal.astype({"idruta": np.int8, "salidas": np.int16})
    sal["dia"] = sal["dia"].dt.date
    sal.to_parquet(PANEL / "salidas_15min.parquet", index=False, compression="zstd")
    calendario().to_csv(PANEL / "calendario.csv", index=False, lineterminator="\n")

    # verificación de la regla contra la tabla de Extreme (58 días): mismo viaje, mismo segmento, mismas subidas
    mio = pd.concat(propias).groupby(["idprogramacion", "idruta", "nro_segmento"], as_index=False)["subidas"].sum()
    ext = ts.merge(seg[["id_segmento", "idruta", "nro_segmento"]], on="id_segmento", how="inner")
    ext = ext.groupby(["id_viaje", "idruta", "nro_segmento"], as_index=False)["subidas"].sum()
    ext = ext.rename(columns={"id_viaje": "idprogramacion", "subidas": "extreme"})
    c = mio.rename(columns={"subidas": "propia"}).merge(ext, on=["idprogramacion", "idruta", "nro_segmento"], how="outer")
    c[["propia", "extreme"]] = c[["propia", "extreme"]].fillna(0)
    con = c[(c["propia"] > 0) | (c["extreme"] > 0)]
    por_viaje = c.groupby("idprogramacion")[["propia", "extreme"]].sum()
    ver = {
        "regla": "cada evento de subida va al segmento activo más cercano de su ruta (distancia plana en grados)",
        "periodo_tabla_extreme": [str(ts["fecha"].min()), str(ts["fecha"].max())],
        "viajes_en_la_tabla_de_extreme": int(len(viajes_ext)),
        "viajes_con_eventos_propios": int(mio["idprogramacion"].nunique()),
        "subidas_extreme": int(c["extreme"].sum()), "subidas_propias_en_esos_viajes": int(c["propia"].sum()),
        "celdas_viaje_segmento_con_subidas": int(len(con)),
        "celdas_identicas": int((con["propia"] == con["extreme"]).sum()),
        "celdas_identicas_pct": round(float((con["propia"] == con["extreme"]).mean() * 100), 3),
        "subidas_en_el_mismo_segmento_pct": round(float(np.minimum(con["propia"], con["extreme"]).sum()
                                                        / max(c["extreme"].sum(), 1) * 100), 3),
        "viajes_con_el_mismo_total_pct": round(float((por_viaje["propia"] == por_viaje["extreme"]).mean() * 100), 3),
        "por_ruta": {RUTAS[int(r)]: {"subidas_extreme": int(g["extreme"].sum()), "subidas_propias": int(g["propia"].sum()),
                                     "en_el_mismo_segmento_pct": round(float(np.minimum(g["propia"], g["extreme"]).sum()
                                                                            / max(g["extreme"].sum(), 1) * 100), 3)}
                     for r, g in c.groupby("idruta")},
    }
    dias = panel.groupby(["idruta", "dia"])["subidas"].sum().unstack(0)
    resumen = {
        "generado": time.strftime("%Y-%m-%d %H:%M"),
        "eventos": tot, "huella_eventos_sha256": huella.hexdigest(),
        "panel": {"filas": int(len(panel)), "subidas": int(panel["subidas"].sum()),
                  "desde": str(panel["dia"].min()), "hasta": str(panel["dia"].max()),
                  "dias_con_subidas_por_ruta": {RUTAS[int(r)]: int(dias[r].notna().sum()) for r in dias.columns},
                  "segmentos": {RUTAS[int(r)]: int(n) for r, n in seg.groupby("idruta").size().items()}},
        "verificacion_extreme": ver, "segundos": round(time.time() - t0, 1),
    }
    (PANEL / "verificacion_extreme.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
