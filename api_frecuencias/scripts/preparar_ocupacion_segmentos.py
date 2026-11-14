"""Ocupación histórica de los buses por segmento, estacionalidad, día de la semana y hora (§10.1; hallazgo H9).

Fuente: las exportaciones del proyecto (carpeta datos/ de la raíz del checkout, git-ignorada; nada se consulta a la
base del reto): timbradas_segmentos (subidas y bajadas por segmento y viaje, 2023-01-01 a 2023-02-27, lo único que
llenaron los triggers de segmentación), rutas_segmentos (idruta, nro_segmento, longitud_m), progvehiculos (hora de
salida, validez, duración y numeropasajeros de cada viaje), conteo_viajes (la ocupación máxima a bordo que da el
dispositivo, solo para validar), rutas y estacionalidades_anio (la estacionalidad vigente: nula para Sobusa, H1).

Método: app/servicios/ocupacion.py (el MISMO que usa el ciclo con la ocupación actual): carga al salir del segmento k
= max(0, carga al salir del segmento k − 1 + subidas_k − bajadas_k) en el orden de nro_segmento, el viaje cuenta entre
el primero y el último segmento que registró y su carga máxima define su segmento crítico.

Viajes que entran al perfil: válidos (finalizado 'S', no cancelados), limpios (R3: 30 a 360 min y 1 a 300 pasajeros),
con salida de 4 a 20 h y que registraron un tramo de al menos COBERTURA_MIN de los segmentos de su ruta.

Salidas:
- datos/ocupacion_segmentos_hora.parquet (versionado): una fila por ruta × segmento × estacionalidad × nivel (día de
  operación ISO, con 7 = domingo o festivo, o tipo de día) × hora de salida, con viajes, días, carga media, P50, P90 y
  máxima y los viajes de los que fue el segmento crítico. Lo lee la API (ocupacion.segmento_critico_historico).
- docs/evidencias/ocupacion/perfil_ocupacion_segmentos.json y .md: la validación del método contra la ocupación
  máxima del dispositivo en los mismos viajes, la comparación con el factor de carga 2025 que usa hoy el optimizador
  (y con el mismo factor medido con el dispositivo en ene-feb de 2023), la cobertura del factor por día de la semana y
  el segmento crítico de las horas pico.

Uso:  python scripts/preparar_ocupacion_segmentos.py [--origen ../../datos]
                                                    [--salida datos/ocupacion_segmentos_hora.parquet]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

COBERTURA_MIN = 0.5            # fracción mínima de los segmentos de la ruta entre el primero y el último registrado
DUR_MIN, DUR_MAX, PAX_MAX = 30, 360, 300     # R3 (Entrega1/codigo/ingenieria_variables.py)
OCUP_MIN = -3                  # R9: contadores consistentes (conteo_viajes.ocupacion_min >= -3)
HORAS = range(4, 21)
ABORDAJES_MIN = 20             # horas con más de 20 abordajes, como el factor de carga 2025
LLAVE_DIA = ["ruta", "idruta", "nro_segmento", "id_estacionalidad", "id_dia_semana", "hora"]
LLAVE_TIPO = ["ruta", "idruta", "nro_segmento", "id_estacionalidad", "tipo_dia", "hora"]
EVIDENCIA = RAIZ / "docs" / "evidencias" / "ocupacion"


def _origen_por_omision() -> Path:
    return Path(os.environ.get("REPLICA_DATOS_DIR") or RAIZ.parents[1] / "datos")


# ---------------------------------------------------------------- lectura de las exportaciones
def cargar_viajes(origen: Path) -> pd.DataFrame:
    """Viajes de las tres rutas con salida de 4 a 20 h y sus marcas (válido, limpio, carga_ok del dispositivo)."""
    from app.servicios import datos, optimizacion

    rutas = {int(r["idruta"]): r["ruta"] for r in datos.catalogo_rutas()}
    pv = pd.read_parquet(origen / "progvehiculos.parquet",
                         columns=["idprogramacion", "idruta", "fechasalida", "fechainicio", "fechafin", "finalizado",
                                  "cancelada", "numeropasajeros"])
    pv = pv[pv["idruta"].isin(rutas)].copy()
    pv["hora"] = pv["fechasalida"].dt.hour
    pv = pv[pv["hora"].isin(HORAS)]
    pv["fecha"] = pv["fechasalida"].dt.date
    pv["ruta"] = pv["idruta"].map(rutas)
    dur = (pv["fechafin"] - pv["fechainicio"]).dt.total_seconds() / 60
    pv["valido"] = (pv["finalizado"] == "S") & (pv["cancelada"] == "N")
    pv["limpio"] = dur.between(DUR_MIN, DUR_MAX) & pv["numeropasajeros"].between(1, PAX_MAX)
    cv = pd.read_parquet(origen / "conteo_viajes.parquet", columns=["idprogramacion", "ocupacion_max", "ocupacion_min",
                                                                    "subidas", "bajadas"])
    cv = cv.rename(columns={"subidas": "subidas_dispositivo", "bajadas": "bajadas_dispositivo"})
    pv = pv.merge(cv, on="idprogramacion", how="left")
    pv["carga_ok"] = pv["limpio"] & (pv["ocupacion_min"] >= OCUP_MIN) & (pv["ocupacion_max"] <= PAX_MAX)
    dias = {f: (optimizacion.tipo_dia_operacion(f), optimizacion.dia_semana_operacion(f)) for f in pv["fecha"].unique()}
    pv["tipo_dia"] = pv["fecha"].map(lambda f: dias[f][0]).astype(int)
    pv["id_dia_semana"] = pv["fecha"].map(lambda f: dias[f][1]).astype(int)
    return pv.rename(columns={"idprogramacion": "id_viaje"})


def cargar_segmentos(origen: Path, viajes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(filas viaje × segmento de timbradas_segmentos de esos viajes, catálogo de segmentos con su sentido)."""
    from app.servicios import ocupacion

    ts = pd.read_parquet(origen / "timbradas_segmentos.parquet", columns=["id_segmento", "id_viaje", "subidas",
                                                                          "bajadas"])
    rs = pd.read_parquet(origen / "rutas_segmentos.parquet", columns=["id", "idruta", "nro_segmento", "longitud_m"])
    rs = rs.rename(columns={"id": "id_segmento"})
    usados = rs[rs["id_segmento"].isin(ts["id_segmento"].unique()) & rs["idruta"].isin(viajes["idruta"].unique())]
    catalogo = ocupacion.sentidos(usados)
    filas = ts[ts["id_viaje"].isin(viajes["id_viaje"])].merge(usados[["id_segmento", "nro_segmento"]],
                                                              on="id_segmento", how="inner")
    return filas, catalogo


def estacionalidades(origen: Path, viajes: pd.DataFrame) -> pd.Series:
    """id_estacionalidad vigente en cada fecha para el proceso de la ruta (la de vigencia más corta, como
    fn_insert_timbradas_anio); nula si no hay (para Sobusa, hallazgo H1: las filas son de otro proceso)."""
    rutas = pd.read_parquet(origen / "rutas.parquet", columns=["idruta", "proceso"])
    est = pd.read_parquet(origen / "estacionalidades_anio.parquet",
                          columns=["proceso", "id_estacionalidad", "fecha_inicio", "fecha_fin"])
    proceso = dict(zip(rutas["idruta"], rutas["proceso"], strict=True))
    vigencias = [(p, int(i), pd.Timestamp(a).date(), pd.Timestamp(b).date())
                 for p, i, a, b in est.itertuples(index=False)]

    def vigente(idruta: int, fecha: date):
        candidatas = [(b - a, i) for p, i, a, b in vigencias if p == proceso.get(idruta) and a <= fecha <= b]
        return min(candidatas)[1] if candidatas else None

    pares = {(r, f): vigente(r, f) for r, f in viajes[["idruta", "fecha"]].drop_duplicates().itertuples(index=False)}
    return pd.Series([pares[(r, f)] for r, f in zip(viajes["idruta"], viajes["fecha"], strict=True)],
                     index=viajes.index, dtype="Int64")


# ---------------------------------------------------------------- perfil
def viajes_del_perfil(viajes: pd.DataFrame, resumen: pd.DataFrame, catalogo: pd.DataFrame) -> pd.DataFrame:
    """Todos los viajes del periodo con segmentos (los válidos sin segmentos cuentan en las salidas de su hora) y la
    marca en_perfil: válidos, limpios y con un tramo registrado de al menos COBERTURA_MIN de los segmentos de su
    ruta."""
    n = catalogo.groupby("idruta")["nro_segmento"].max()
    con = viajes["id_viaje"].isin(resumen["id_viaje"])
    desde, hasta = viajes.loc[con, "fecha"].min(), viajes.loc[con, "fecha"].max()
    v = viajes[(viajes["fecha"] >= desde) & (viajes["fecha"] <= hasta)].merge(resumen, on="id_viaje", how="left")
    v["cobertura"] = (v["ultimo"] - v["primero"] + 1) / v["idruta"].map(n)
    v["en_perfil"] = v["valido"] & v["limpio"] & (v["cobertura"] >= COBERTURA_MIN)
    return v.reset_index(drop=True)


def _agregar(malla: pd.DataFrame, llave: list[str]) -> pd.DataFrame:
    g = malla.groupby(llave, dropna=False, sort=True)
    return g.agg(nro_viajes=("carga", "size"), dias=("fecha", "nunique"), carga_media=("carga", "mean"),
                 carga_p50=("carga", "median"), carga_p90=("carga", lambda s: s.quantile(0.9)),
                 carga_max=("carga", "max"), viajes_criticos=("critico", "sum")).reset_index()


def perfil(malla: pd.DataFrame, catalogo: pd.DataFrame) -> pd.DataFrame:
    """Las dos tablas del perfil (día de operación y tipo de día) en el formato versionado."""
    dia = _agregar(malla, LLAVE_DIA).assign(nivel="dia_semana")
    dia["tipo_dia"] = np.select([dia["id_dia_semana"] == 7, dia["id_dia_semana"] == 6], [2, 1], 0)
    tipo = _agregar(malla, LLAVE_TIPO).assign(nivel="tipo_dia", id_dia_semana=pd.NA)
    p = pd.concat([dia, tipo], ignore_index=True)
    p = p.merge(catalogo[["idruta", "nro_segmento", "id_segmento", "sentido", "km_inicio", "longitud_m"]],
                on=["idruta", "nro_segmento"], how="left")
    columnas = ["ruta", "idruta", "id_segmento", "nro_segmento", "sentido", "km_inicio", "longitud_m", "nivel",
                "id_estacionalidad", "id_dia_semana", "tipo_dia", "hora", "nro_viajes", "dias", "carga_media",
                "carga_p50", "carga_p90", "carga_max", "viajes_criticos"]
    p = p[columnas].sort_values(["ruta", "nivel", "id_dia_semana", "tipo_dia", "hora", "nro_segmento"],
                                na_position="last").reset_index(drop=True)
    return p.astype({"idruta": "int16", "id_segmento": "int32", "nro_segmento": "int16", "km_inicio": "float32",
                     "longitud_m": "float32", "id_estacionalidad": "Int64", "id_dia_semana": "Int8",
                     "tipo_dia": "int8", "hora": "int8", "nro_viajes": "int32", "dias": "int16",
                     "carga_media": "float32", "carga_p50": "float32", "carga_p90": "float32",
                     "carga_max": "int16", "viajes_criticos": "int32"})


def malla_del_perfil(filas: pd.DataFrame, v: pd.DataFrame) -> pd.DataFrame:
    """Carga de cada viaje del perfil en cada segmento de su tramo, con su franja y si es su segmento crítico."""
    from app.servicios import ocupacion

    dentro = v[v["en_perfil"]].set_index("id_viaje")
    cargas = ocupacion.cargas_por_segmento(filas[filas["id_viaje"].isin(dentro.index)])
    malla = ocupacion.cargas_en_el_tramo(cargas)
    malla = malla.join(dentro[["ruta", "idruta", "fecha", "hora", "tipo_dia", "id_dia_semana", "id_estacionalidad",
                               "nro_segmento_critico"]], on="id_viaje")
    malla["critico"] = malla["nro_segmento"] == malla["nro_segmento_critico"]
    return malla


# ---------------------------------------------------------------- validación y comparación (evidencia)
def _comparar(a: pd.Series, b: pd.Series) -> dict:
    x = pd.DataFrame({"a": a, "b": b}).dropna()
    x = x[x["b"] > 0]
    return {"viajes": int(len(x)), "correlacion": round(float(x["a"].corr(x["b"])), 4),
            "razon_mediana": round(float((x["a"] / x["b"]).median()), 4),
            "diferencia_percentiles_5_25_50_75_95": [round(float(q), 1) for q in
                                                    np.percentile(x["a"] - x["b"], [5, 25, 50, 75, 95])]}


def validar(filas: pd.DataFrame, v: pd.DataFrame) -> dict:
    """Carga máxima por viaje (acotada en cada segmento y la variante literal max(0, Σ)) frente a la ocupación máxima
    a bordo del dispositivo (conteo_viajes.ocupacion_max, hora a hora del evento) en los MISMOS viajes."""
    d = filas.groupby(["id_viaje", "nro_segmento"], as_index=False)[["subidas", "bajadas"]].sum()
    d["s"] = (d["subidas"] - d["bajadas"]).groupby(d["id_viaje"]).cumsum()
    literal = d.groupby("id_viaje")["s"].agg(lambda s: max(float(s.max()), 0.0)).rename("literal")
    minimo = d.groupby("id_viaje")["s"].min().rename("minimo")
    x = v[v["en_perfil"] & v["carga_ok"]].set_index("id_viaje").join(literal).join(minimo)
    todos = v[v["en_perfil"]]
    return {"criterio": "viajes del perfil con contadores consistentes en el dispositivo (R9)",
            "acotada_en_cada_segmento": _comparar(x["carga_max"], x["ocupacion_max"]),
            "literal_max_0_suma": _comparar(x["literal"], x["ocupacion_max"]),
            "viajes_con_suma_bajo_menos_3": round(float((x["minimo"] < OCUP_MIN).mean()), 4),
            "dispositivo_con_ocupacion_min_bajo_menos_3_en_viajes_limpios": round(float(
                (v.loc[v["valido"] & v["limpio"], "ocupacion_min"] < OCUP_MIN).mean()), 4),
            "subidas_y_bajadas_de_los_segmentos_frente_al_dispositivo": {
                "subidas_segmentos": int(todos["subidas"].sum()),
                "subidas_dispositivo": int(todos["subidas_dispositivo"].sum()),
                "bajadas_segmentos": int(todos["bajadas"].sum()),
                "bajadas_dispositivo": int(todos["bajadas_dispositivo"].sum())}}


def factores_2023(v: pd.DataFrame) -> pd.DataFrame:
    """Factor de carga por franja de ene-feb 2023: mediana de la carga máxima por viaje × viajes válidos / abordajes,
    con la carga de los segmentos (los viajes del perfil) y con la del dispositivo (los viajes carga_ok, como 2025)."""
    llave = ["ruta", "fecha", "hora"]
    val = v[v["valido"]]
    fr = pd.DataFrame({
        "viajes": val.groupby(llave).size(),
        "real": val[val["numeropasajeros"] <= PAX_MAX].groupby(llave)["numeropasajeros"].sum(),
        "seg": val[val["en_perfil"]].groupby(llave)["carga_max"].median(),
        "dev": val[val["carga_ok"]].groupby(llave)["ocupacion_max"].median(),
        "seg_igual": val[val["en_perfil"] & val["carga_ok"]].groupby(llave)["carga_max"].median(),
        "dev_igual": val[val["en_perfil"] & val["carga_ok"]].groupby(llave)["ocupacion_max"].median()}).reset_index()
    fr = fr[fr["real"] > ABORDAJES_MIN]
    for c in ("seg", "dev", "seg_igual", "dev_igual"):
        fr[f"f_{c}"] = fr[c] * fr["viajes"] / fr["real"]
    dias = v.drop_duplicates("fecha").set_index("fecha")[["tipo_dia", "id_dia_semana"]]
    return fr.join(dias, on="fecha")


def factores_2025() -> pd.DataFrame:
    from app.servicios import optimizacion

    d = optimizacion._cargas_2025()
    d["tipo_dia"] = d["t"].map({"L": 0, "S": 1, "D": 2})
    d["mes"] = pd.to_datetime(d["dia"]).dt.month
    return d


def comparar_factores(fr: pd.DataFrame, f25: pd.DataFrame) -> dict:
    """Por ruta × tipo de día × hora (lo comparable): mediana del factor de 2023 con segmentos y con el dispositivo,
    y del factor 2025 que usa hoy el optimizador (todo el año y solo ene-feb)."""
    llave = ["ruta", "tipo_dia", "hora"]
    t = fr.groupby(llave).agg(f_seg=("f_seg", "median"), f_dev=("f_dev", "median"),
                              f_seg_igual=("f_seg_igual", "median"), f_dev_igual=("f_dev_igual", "median"),
                              dias_2023=("f_seg", "size"))
    t = t.join(f25.groupby(llave)["f"].median().rename("f_2025"))
    t = t.join(f25[f25["mes"] <= 2].groupby(llave)["f"].median().rename("f_2025_ene_feb"))
    pares = {}
    for a, b in (("f_seg_igual", "f_dev_igual"), ("f_seg", "f_dev"), ("f_dev", "f_2025_ene_feb"), ("f_dev", "f_2025"),
                 ("f_seg", "f_2025"), ("f_2025_ene_feb", "f_2025")):
        x = t[[a, b]].dropna()
        pares[f"{a} vs {b}"] = {"franjas": int(len(x)),
                                "error_absoluto_medio": round(float((x[a] - x[b]).abs().mean()), 4),
                                "sesgo": round(float((x[a] - x[b]).mean()), 4),
                                "correlacion": round(float(x[a].corr(x[b])), 3)}
    por_tipo = t.groupby(level=["ruta", "tipo_dia"]).median().round(3).reset_index()
    return {"pares": pares, "medianas_por_ruta_y_tipo_de_dia": por_tipo.to_dict("records"),
            "por_franja": t.round(4).reset_index().to_dict("records")}


def cobertura_factor_dia(f25: pd.DataFrame) -> dict:
    """El factor 2025 por día de la semana de operación: celdas con al menos 10 días y cuánto cambia entre días."""
    from app.servicios import optimizacion

    dia = optimizacion._factores_carga_dia()
    tipo = optimizacion._factores_carga_hora()
    rango = {}
    for (ruta, d, h), (m, _) in dia.items():
        if d <= 5:
            rango.setdefault((ruta, h), []).append(m)
    amplitud = [max(x) - min(x) for x in rango.values() if len(x) >= 2]
    return {"celdas_dia_semana_con_10_dias": len(dia), "celdas_tipo_de_dia_con_10_dias": len(tipo),
            "franjas_laborales_comparables": len(amplitud),
            "amplitud_entre_dias_laborales": {"media": round(float(np.mean(amplitud)), 4),
                                              "mediana": round(float(np.median(amplitud)), 4),
                                              "maxima": round(float(np.max(amplitud)), 4)},
            "fuente": optimizacion.FUENTE_FACTOR_DIA}


def criticos_pico(p: pd.DataFrame) -> list[dict]:
    """Segmento crítico (mayor carga media) de cada ruta en las horas pico de los días laborales (lunes a viernes)."""
    from app.servicios import ocupacion

    salida = []
    dias = p[(p["nivel"] == "dia_semana") & (p["id_dia_semana"].astype(float) <= 5) & p["hora"].isin([6, 7, 17, 18])]
    for (ruta, dia, hora), g in dias.groupby(["ruta", "id_dia_semana", "hora"]):
        f = g.loc[g["carga_media"].idxmax()]
        salida.append({"ruta": ruta, "id_dia_semana": int(dia), "dia": ocupacion.DIAS[int(dia)], "hora": int(hora),
                       "nro_segmento": int(f["nro_segmento"]), "sentido": f["sentido"],
                       "km_inicio": round(float(f["km_inicio"]), 1),
                       "carga_media": round(float(f["carga_media"]), 1), "carga_p90": round(float(f["carga_p90"]), 1),
                       "ocupacion_media": round(float(f["carga_media"]) / ocupacion.CAPACIDAD_POR_OMISION, 3),
                       "ocupacion_p90": round(float(f["carga_p90"]) / ocupacion.CAPACIDAD_POR_OMISION, 3),
                       "viajes": int(f["nro_viajes"]), "dias": int(f["dias"]),
                       "fraccion_viajes_criticos": round(float(f["viajes_criticos"]) / int(f["nro_viajes"]), 3)})
    return salida


def sentido_de_los_criticos(v: pd.DataFrame, catalogo: pd.DataFrame) -> dict:
    """Fracción de los viajes del perfil cuyo segmento crítico está en la ida o en el regreso, por ruta."""
    sentidos = catalogo[["idruta", "nro_segmento", "sentido"]].rename(columns={"nro_segmento": "nro_segmento_critico"})
    x = v[v["en_perfil"]].merge(sentidos, on=["idruta", "nro_segmento_critico"], how="left")
    return {r: g["sentido"].value_counts(normalize=True).round(3).to_dict() for r, g in x.groupby("ruta")}


# ---------------------------------------------------------------- informe
def informe_md(ev: dict) -> str:
    val, comp, cob = ev["validacion"], ev["comparacion_factor_2025"]["pares"], ev["factor_dia_semana_2025"]
    a, lit = val["acotada_en_cada_segmento"], val["literal_max_0_suma"]
    lineas = [
        "# Ocupación histórica por segmento (§10.1)", "",
        f"Generado por `scripts/preparar_ocupacion_segmentos.py` el {ev['generado_en']} con las exportaciones de "
        f"{ev['periodo']} (timbradas_segmentos). Método: `app/servicios/ocupacion.py` (el mismo del ciclo).", "",
        "## Datos", "",
        f"- Viajes con segmentos: {ev['viajes']['con_segmentos']}; en el perfil (válidos, limpios y con un tramo de "
        f"al menos {int(100 * COBERTURA_MIN)} % de la ruta): {ev['viajes']['en_perfil']}.",
        f"- Filas del perfil: {ev['filas_perfil']} ({ev['filas_por_nivel']}).",
        "- Estacionalidad: nula en todas las filas (hallazgo H1: `estacionalidades_anio` es de otro proceso). El "
        "código agrupa por ella, así que el perfil se separa por estacionalidad cuando Extreme la entregue.", "",
        "## Validación del método frente a la ocupación máxima del dispositivo (mismos viajes)", "",
        "| Variante | Viajes | Correlación | Razón mediana | Diferencia p5 / p50 / p95 |", "|---|---|---|---|---|",
        f"| Acotada en 0 en cada segmento (la que usa la API) | {a['viajes']} | {_c(a['correlacion'])} | "
        f"{_c(a['razon_mediana'])} | {_d(a)} |",
        f"| Literal max(0, Σ subidas − bajadas) | {lit['viajes']} | {_c(lit['correlacion'])} | "
        f"{_c(lit['razon_mediana'])} | {_d(lit)} |", "",
        f"Con el orden de `nro_segmento`, la suma sin acotar baja de −3 en el "
        f"{_c(100 * val['viajes_con_suma_bajo_menos_3'], 1)} % de los viajes (en el dispositivo, ordenado por hora "
        f"del evento, en el {_c(100 * val['dispositivo_con_ocupacion_min_bajo_menos_3_en_viajes_limpios'], 1)} %). "
        f"Σ subidas de los segmentos = Σ subidas del dispositivo en los mismos viajes "
        f"({val['subidas_y_bajadas_de_los_segmentos_frente_al_dispositivo']['subidas_segmentos']} = "
        f"{val['subidas_y_bajadas_de_los_segmentos_frente_al_dispositivo']['subidas_dispositivo']}): el trigger asigna "
        "cada evento al segmento más cercano y en un ciclo de ida y regreso por la misma vía eso desordena algunos "
        "eventos. Acotar en cada segmento evita que esa bajada de más se arrastre y por eso se acerca más al "
        "dispositivo.", "",
        "## Comparación con el factor de carga 2025 (ruta × tipo de día × hora)", "",
        "| Comparación | Franjas | Error absoluto medio | Sesgo | Correlación |", "|---|---|---|---|---|"]
    lineas += [f"| {k} | {x['franjas']} | {_c(x['error_absoluto_medio'], 3)} | {_c(x['sesgo'], 3)} | "
               f"{_c(x['correlacion'], 3)} |" for k, x in comp.items()]
    lineas += ["", "f_seg: factor con la carga de los segmentos (ene-feb 2023); f_dev: el mismo factor con la "
               "ocupación máxima del dispositivo (ene-feb 2023, viajes con contadores consistentes, como 2025); "
               "«_igual»: los mismos viajes en los dos; f_2025: el factor que usa hoy el optimizador.", "",
               "## Factor 2025 por día de la semana", "",
               f"- Celdas ruta × día de operación × hora con al menos 10 días: {cob['celdas_dia_semana_con_10_dias']} "
               f"(por tipo de día: {cob['celdas_tipo_de_dia_con_10_dias']}).",
               f"- Entre los días laborales de una misma ruta y hora el factor cambia en promedio "
               f"{_c(cob['amplitud_entre_dias_laborales']['media'], 3)} (máximo "
               f"{_c(cob['amplitud_entre_dias_laborales']['maxima'], 3)}).", "",
               "## Segmento crítico en las horas pico laborales", "",
               "| Ruta | Día | Hora | Segmento | Sentido | Carga media | Ocupación media | Ocupación P90 | Viajes |",
               "|---|---|---|---|---|---|---|---|---|"]
    lineas += [f"| {c['ruta']} | {c['dia']} | {c['hora']} | {c['nro_segmento']} | {c['sentido']} | "
               f"{_c(c['carga_media'], 1)} | {_c(100 * c['ocupacion_media'], 0)} % | "
               f"{_c(100 * c['ocupacion_p90'], 0)} % | {c['viajes']} |" for c in ev["criticos_pico_laboral"]]
    lineas += ["", "## Limitaciones", ""] + [f"- {x}" for x in ev["limitaciones"]]
    return "\n".join(lineas) + "\n"


def _c(x, d=2) -> str:
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _d(r: dict) -> str:
    p = r["diferencia_percentiles_5_25_50_75_95"]
    return f"{_c(p[0], 1)} / {_c(p[2], 1)} / {_c(p[4], 1)}"


LIMITACIONES = [
    "timbradas_segmentos solo trae 2023-01-01 a 2023-02-27: el perfil es de enero (vacaciones escolares) y febrero "
    "(inicio de clases y Carnaval); no ve Semana Santa, mitad de año ni diciembre, ni los cambios de ruta posteriores.",
    "La hora es la de salida del viaje (la franja que decide el despacho), no la hora en que el bus pasa por el "
    "segmento: los segmentos del regreso se recorren una hora o más después de la salida.",
    "El trigger de Extreme asigna cada evento al segmento más cercano: en los tramos donde la ida y el regreso van por "
    "la misma vía algunos eventos caen en el segmento del otro sentido (ver la validación).",
    "El sentido es una aproximación geométrica (mitad de la longitud del ciclo), no un campo de Extreme.",
    "La ocupación es carga / 50 puestos (el catálogo del reto); la API la recalcula con la capacidad gobernada.",
    "La estacionalidad oficial es nula para Sobusa (H1); el perfil se separará por ella cuando Extreme la entregue.",
]


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--origen", type=Path, default=_origen_por_omision())
    p.add_argument("--salida", type=Path, default=RAIZ / "datos" / "ocupacion_segmentos_hora.parquet")
    p.add_argument("--evidencia", type=Path, default=EVIDENCIA)
    a = p.parse_args(argv)
    from app.servicios import ocupacion

    viajes = cargar_viajes(a.origen)
    filas, catalogo = cargar_segmentos(a.origen, viajes)
    resumen = ocupacion.resumen_viajes(ocupacion.cargas_por_segmento(filas))
    v = viajes_del_perfil(viajes, resumen, catalogo)
    v["id_estacionalidad"] = estacionalidades(a.origen, v)
    tabla = perfil(malla_del_perfil(filas, v), catalogo)
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_parquet(a.salida, index=False)
    f25 = factores_2025()
    fechas = v.loc[v["en_perfil"], "fecha"]
    ev = {"generado_en": datetime.now().astimezone().isoformat(timespec="seconds"),
          "script": "scripts/preparar_ocupacion_segmentos.py", "metodo": ocupacion.METODO,
          "periodo": f"{fechas.min()} a {fechas.max()}",
          "viajes": {"del_periodo": int(len(v)), "con_segmentos": int(v["primero"].notna().sum()),
                     "en_perfil": int(v["en_perfil"].sum()),
                     "criterio": f"válidos, limpios (R3) y tramo registrado >= {COBERTURA_MIN} de la ruta"},
          "filas_perfil": int(len(tabla)), "filas_por_nivel": tabla["nivel"].value_counts().to_dict(),
          "estacionalidad_no_nula": int(tabla["id_estacionalidad"].notna().sum()),
          "validacion": validar(filas, v),
          "comparacion_factor_2025": comparar_factores(factores_2023(v), f25),
          "factor_dia_semana_2025": cobertura_factor_dia(f25),
          "criticos_pico_laboral": criticos_pico(tabla),
          "sentido_del_segmento_critico_por_ruta": sentido_de_los_criticos(v, catalogo),
          "limitaciones": LIMITACIONES}
    a.evidencia.mkdir(parents=True, exist_ok=True)
    (a.evidencia / "perfil_ocupacion_segmentos.json").write_text(
        json.dumps(ev, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (a.evidencia / "perfil_ocupacion_segmentos.md").write_text(informe_md(ev), encoding="utf-8")
    print(f"{a.salida.name}: {len(tabla)} filas; viajes en el perfil {ev['viajes']['en_perfil']}")
    print(json.dumps({"validacion": ev["validacion"], "pares": ev["comparacion_factor_2025"]["pares"]},
                     ensure_ascii=False, indent=1))
    return ev


if __name__ == "__main__":
    main()
