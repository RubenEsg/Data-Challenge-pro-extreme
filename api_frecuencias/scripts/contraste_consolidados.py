"""Evidencia de los consolidados de Extreme en el ciclo con los datos reales de la réplica LOCAL, en solo lectura
(lector_ia; §5.2 ALT-008, §6.1, §6.3, §7.3 paso 3, §11.2).

Cada consulta pasa por FuentePostgresSoloLectura.consultar (un único SELECT, transacción READ ONLY, statement_timeout y
ROLLBACK) y usa las mismas funciones del ciclo (app/servicios/consolidados.py y app/servicios/calidad.py). Escribe en
docs/evidencias/consolidados/ (nunca en datos/ ni en la réplica):

  contraste_consolidados.json y .md
      - timbradas_consolidado (las 10.731 filas): lectura incremental desde la carga, calidad de §6.3 con los catálogos
        de la réplica (CONS-001, VAL-007, VAL-008, REL-001 a REL-007), segunda lectura con las huellas (H7) y contraste
        con el histórico propio por ruta × día ISO × estacionalidad. El histórico es la serie empaquetada 2023-2025
        (pasajeros, salidas y bajadas_viajes, la misma de la lectura integrada; tests/replica la compara con la
        réplica) con el día ISO y la estacionalidad vigente de la réplica: lo que tendría demanda_observada tras
        cargar ese período;
      - por qué no por hora (H10): el promedio por viaje del consolidado por ruta × día × hora frente a los viajes
        válidos por hora de SALIDA y por hora de FIN del viaje;
      - de dónde salen las diferencias groseras de viajes por día (H17): los festivos de un día con más de
        una fila en estacionalidades_anio y los viajes que timbradas_anio guarda con cada una, y timbradas_anio frente
        a los viajes aptos por fecha de fin, por ruta y año, en total y en los días corrientes;
      - timbradas_segmentos_anio y timbradas_segmentos_consolidado: sin filas en la réplica (hallazgo H4), y el
        grano con que el ciclo las contrasta cuando las tengan (sin la hora del bloque de Extreme, H10).
  definicion_bajadas.json y .md
      en el solape de timbradas_segmentos (2023-01-01 a 2023-02-27), Σ bajadas de los segmentos frente a Σ
      numerobajadas de los viajes válidos: en los mismos viajes y por cobertura (la razón de bajadas_viajes).

Nunca se conecta a la base compartida del reto: replica_comun solo acepta servidores locales.
Uso (desde EntregaFinal/api_frecuencias):  python -m scripts.contraste_consolidados
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts import replica_comun as rc  # noqa: E402

SALIDA = RAIZ / "docs" / "evidencias" / "consolidados"
ZONA = ZoneInfo("America/Bogota")
PROCESO = "sobusa"

# H10: el consolidado por ruta × día × hora frente a los viajes válidos asignados por hora de salida o por hora de fin
SQL_CONSOLIDADO_HORA = """
SELECT id_ruta AS idruta, id_dia_semana AS dia, CAST(EXTRACT(HOUR FROM hora_inicio) AS integer) AS hora,
       SUM(subidas) AS subidas, SUM(bajadas) AS bajadas, SUM(nro_viajes) AS n
  FROM timbradas_consolidado
 WHERE proceso = :proceso
 GROUP BY 1, 2, 3
"""
SQL_VIAJES_SALIDA = """
SELECT idruta, CAST(EXTRACT(ISODOW FROM fechasalida) AS integer) AS dia,
       CAST(EXTRACT(HOUR FROM fechasalida) AS integer) AS hora, COUNT(*) AS n,
       SUM(numeropasajeros) FILTER (WHERE numeropasajeros <= 300) AS subidas,
       SUM(numerobajadas) FILTER (WHERE numerobajadas <= 300) AS bajadas
  FROM progvehiculos
 WHERE finalizado = 'S' AND cancelada = 'N' AND fechasalida >= :desde AND fechasalida < :hasta
 GROUP BY 1, 2, 3
"""
SQL_VIAJES_FIN = """
SELECT idruta, CAST(EXTRACT(ISODOW FROM COALESCE(fecha_fin_liquidacion, fechafin)) AS integer) AS dia,
       CAST(EXTRACT(HOUR FROM COALESCE(fecha_fin_liquidacion, fechafin)) AS integer) AS hora, COUNT(*) AS n,
       SUM(numeropasajeros) FILTER (WHERE numeropasajeros <= 300) AS subidas,
       SUM(numerobajadas) FILTER (WHERE numerobajadas <= 300) AS bajadas
  FROM progvehiculos
 WHERE finalizado = 'S' AND cancelada = 'N' AND fechasalida >= :desde AND fechasalida < :hasta
   AND COALESCE(fecha_fin_liquidacion, fechafin) IS NOT NULL
 GROUP BY 1, 2, 3
"""
# Definición de bajadas: en el solape, por ruta, los mismos viajes válidos con timbradas y todos los viajes válidos
SQL_DEFINICION_BAJADAS = """
WITH seg AS (
    SELECT id_viaje, SUM(subidas) AS subidas, SUM(bajadas) AS bajadas FROM timbradas_segmentos GROUP BY id_viaje
)
SELECT pv.idruta, COUNT(*) AS viajes_validos, COUNT(s.id_viaje) AS viajes_con_timbradas,
       COUNT(*) FILTER (WHERE pv.numerobajadas IS NULL) AS viajes_sin_numerobajadas,
       SUM(s.bajadas) AS bajadas_segmentos,
       SUM(pv.numerobajadas) FILTER (WHERE s.id_viaje IS NOT NULL AND pv.numerobajadas <= 300)
           AS bajadas_viajes_mismos_viajes,
       SUM(s.bajadas) FILTER (WHERE pv.numerobajadas IS NOT NULL AND pv.numerobajadas <= 300)
           AS bajadas_segmentos_mismos_viajes,
       SUM(pv.numerobajadas) FILTER (WHERE pv.numerobajadas <= 300) AS bajadas_viajes_todos
  FROM progvehiculos pv
  LEFT JOIN seg s ON s.id_viaje = pv.idprogramacion
 WHERE pv.finalizado = 'S' AND pv.cancelada = 'N' AND pv.fechasalida >= :desde AND pv.fechasalida < :hasta
 GROUP BY pv.idruta
 ORDER BY pv.idruta
"""


# H17: de dónde salen las diferencias groseras de viajes por día. Festivos de un día con más de una fila en
# estacionalidades_anio, los viajes que timbradas_anio guarda con cada una y los viajes aptos de esa fecha de fin.
SQL_FESTIVOS_REPETIDOS = """
SELECT fecha_inicio AS fecha, COUNT(*) AS filas,
       array_agg(id_estacionalidad_anio ORDER BY id_estacionalidad_anio) AS ids,
       array_agg(id_estacionalidad ORDER BY id_estacionalidad_anio) AS estacionalidades
  FROM estacionalidades_anio
 WHERE proceso = :proceso AND fecha_inicio = fecha_fin
 GROUP BY fecha_inicio
HAVING COUNT(*) > 1
 ORDER BY fecha_inicio
"""
SQL_VIAJES_POR_ESTACIONALIDAD_ANIO = """
SELECT id_estacionalidad_anio, SUM(nro_viajes) AS viajes
  FROM timbradas_anio
 WHERE proceso = :proceso AND id_estacionalidad_anio = ANY(CAST(:ids AS bigint[]))
 GROUP BY id_estacionalidad_anio
"""
SQL_APTOS_POR_FECHA_DE_FIN = """
SELECT CAST(COALESCE(pv.fecha_fin_liquidacion, pv.fechafin) AS date) AS fecha, COUNT(*) AS aptos
  FROM progvehiculos pv
  JOIN rutas r ON r.idruta = pv.idruta
 WHERE r.proceso = :proceso AND pv.apto_estadisticas_historicas IS TRUE
   AND CAST(COALESCE(pv.fecha_fin_liquidacion, pv.fechafin) AS date) = ANY(CAST(:fechas AS date[]))
 GROUP BY 1
"""
# timbradas_anio frente a los viajes aptos por fecha de fin (la fecha de fn_insert_timbradas_anio), por ruta y año, en
# total y en los días corrientes (estacionalidad vigente de período más corto = DIAS_CORRIENTES)
SQL_APTOS_POR_RUTA_Y_ANO = """
WITH vigente AS (
    SELECT CAST(d AS date) AS fecha,
           (SELECT e.id_estacionalidad FROM estacionalidades_anio e
             WHERE e.proceso = :proceso AND e.fecha_inicio <= CAST(d AS date) AND e.fecha_fin >= CAST(d AS date)
             ORDER BY (e.fecha_fin - e.fecha_inicio), e.fecha_inicio DESC, e.id_estacionalidad_anio DESC
             LIMIT 1) AS est
      FROM generate_series(CAST(:desde AS date), CAST(:hasta AS date), interval '1 day') d
), aptos AS (
    SELECT pv.idruta, CAST(COALESCE(pv.fecha_fin_liquidacion, pv.fechafin) AS date) AS fecha, COUNT(*) AS n
      FROM progvehiculos pv
      JOIN rutas r ON r.idruta = pv.idruta
     WHERE r.proceso = :proceso AND pv.apto_estadisticas_historicas IS TRUE
     GROUP BY 1, 2
)
SELECT a.idruta, CAST(EXTRACT(YEAR FROM v.fecha) AS integer) AS ano, SUM(a.n) AS aptos,
       SUM(a.n) FILTER (WHERE v.est = :corriente) AS aptos_corrientes
  FROM vigente v
  JOIN aptos a ON a.fecha = v.fecha
 GROUP BY 1, 2
"""
SQL_ANIO_POR_RUTA_Y_ANO = """
SELECT ta.id_ruta AS idruta, ta.ano, SUM(ta.nro_viajes) AS viajes,
       SUM(ta.nro_viajes) FILTER (WHERE ea.id_estacionalidad = :corriente) AS viajes_corrientes
  FROM timbradas_anio ta
  JOIN estacionalidades_anio ea ON ea.id_estacionalidad_anio = ta.id_estacionalidad_anio
 WHERE ta.proceso = :proceso AND ta.ano BETWEEN :primero AND :ultimo
 GROUP BY 1, 2
"""
SQL_DIAS_CORRIENTES = ("SELECT min(id_estacionalidad) AS id FROM estacionalidades "
                       "WHERE proceso = :proceso AND estacionalidad = 'DIAS_CORRIENTES'")


def fuente():
    """La lectura de solo lectura de la réplica (lector_ia) con el proceso de Sobusa."""
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = rc.url_rol("lector_ia")
    if not url:
        raise SystemExit("Falta LECTOR_IA_PASSWORD (réplica local no configurada)")
    return FuentePostgresSoloLectura(url=url.replace("postgresql://", "postgresql+psycopg://"),
                                     tabla="timbradas_segmentos", proceso=PROCESO, statement_timeout_ms=120000)


# ---------------------------------------------------------------- histórico propio de la serie empaquetada
def historico_empaquetado(vigencias: list[tuple], periodo: tuple[date, date]) -> pd.DataFrame:
    """Lo que tendría demanda_observada tras cargar la serie empaquetada del período: Σ pasajeros, Σ bajadas_viajes,
    Σ salidas y las fechas propias por ruta × día ISO × estacionalidad vigente (la de período más corto)."""
    from app.servicios import datos

    s = datos.con_bajadas(datos.demanda_horaria(desde=periodo[0], hasta=periodo[1]))
    idruta = {r["ruta"]: int(r["idruta"]) for r in datos.catalogo_rutas()}
    estacion = {d: next((e for e, a, b in vigencias if a <= d <= b), None) for d in sorted(set(s["fecha"]))}
    s = s.assign(id_ruta=s["ruta"].map(idruta), id_dia_semana=[d.isoweekday() for d in s["fecha"]],
                 id_estacionalidad=s["fecha"].map(estacion))
    g = s.groupby(["id_ruta", "id_dia_semana", "id_estacionalidad"], dropna=False)
    propia = pd.DataFrame({"subidas": g["pasajeros"].sum(), "bajadas": g["bajadas_viajes"].sum(),
                           "n": g["salidas"].sum().astype(float), "dias": g["fecha"].nunique()}).reset_index()
    propia["n_bajadas"] = propia["n"]
    return propia


def distribucion(ext: pd.DataFrame, propia: pd.DataFrame, cfg, minimos: float) -> dict:
    """Mediana, p90 y máximo de la diferencia relativa de cada medida en las llaves comparables."""
    from app.servicios import consolidados as C

    m = C.normalizar_lado(ext, cfg.grano, False).merge(C.normalizar_lado(propia, cfg.grano, True),
                                                       on=list(cfg.grano), suffixes=("_ext", "_propia"))
    m = m[(m["n_ext"] >= minimos) & (m["n_propia"] >= minimos)]
    salida = {}
    for med in cfg.medidas:
        e = m[f"{med.numerador}_ext"] / m[f"{med.denominador}_ext"]
        p = m[f"{med.numerador}_propia"] / m[f"{med.denominador}_propia"]
        rel = ((e - p).abs() / p.abs().clip(lower=med.piso)).dropna()
        salida[med.campo] = {"llaves": int(len(rel)), "mediana": round(float(rel.median()), 4),
                             "p90": round(float(rel.quantile(0.9)), 4), "maximo": round(float(rel.max()), 4)}
    return salida


def _incidencias_resumidas(incidencias: list[dict]) -> list[dict]:
    return [{"llave": {k: v for k, v in i["llave"].items() if k != "proceso"}, "campo": i["campo"],
             "valor_extreme": float(i["valor"]), "bloqueante": i["bloqueante"], "detalle": i["detalle"]}
            for i in sorted(incidencias, key=lambda i: (not i["bloqueante"], str(i["llave"]), i["campo"]))]


def contraste_ruta(f) -> dict:
    """timbradas_consolidado de la réplica por el mismo camino del ciclo (sin escribir): lectura, calidad, huellas y
    contraste con el histórico de la serie empaquetada."""
    from app.servicios import calidad, fuentes
    from app.servicios import consolidados as C

    fc = f.para_tabla(C.TABLA_RUTA)
    df, marca = fuentes.leer_con_estado(fc, None, None, None)
    lectura = dict(fc.resumen_lectura)
    estado = fc.estado_incremental
    _, segunda = fuentes.leer_con_estado(fc, marca, None, estado), fc.resumen_lectura
    catalogos, vigencias = C._catalogos(fc)
    validos, errores = calidad.validar_lote(df, "real", esquema="consolidado", catalogos=catalogos)
    cfg = C.CONFIG[C.TABLA_RUTA]
    ids = sorted({int(x) for x in df["id_ruta"]})
    ext = C._agregado_fuente(fc, cfg, ids)
    periodo = C._periodo(fc, cfg, ext)
    propia = historico_empaquetado(vigencias, periodo)
    C._con_dias(ext, cfg, periodo, vigencias)
    tol = dict(C.TOLERANCIAS_POR_DEFECTO)
    r = C.contrastar(ext, propia, cfg, tol, "real:timbradas_consolidado", PROCESO)
    totales = ext.groupby("id_ruta")[["subidas", "bajadas", "n"]].sum().join(
        propia.groupby("id_ruta")[["subidas", "bajadas", "n"]].sum(), lsuffix="_extreme", rsuffix="_propia")
    return {"filas": int(len(df)), "marca": str(marca), "lectura": {k: lectura.get(k) for k in (
                "leidas", "entregadas", "nuevas", "modificadas", "truncada")},
            "segunda_lectura_con_huellas": {k: segunda.get(k) for k in ("leidas", "entregadas", "repetidas_solape")},
            "calidad": {"validas": int(len(validos)), "errores_por_codigo": dict(Counter(e["codigo"] for e in errores)),
                        "catalogos": sorted(catalogos)},
            "periodo": [str(p) for p in periodo], "contraste": r.resumen,
            "distribucion_diferencias": distribucion(ext, propia, cfg, tol["contraste_viajes_minimos"]),
            "incidencias": _incidencias_resumidas(r.incidencias),
            "totales_por_ruta": {int(k): {c: float(v) for c, v in fila.items()} for k, fila in totales.iterrows()}}


# Filas del proceso en las tablas por segmento (H4). Solo para esta evidencia: el ciclo ya no cuenta filas (la lectura
# desde la marca inicial dice si hay alguna, app/servicios/consolidados.py::_sin_filas).
SQL_FILAS_DEL_PROCESO = {
    "timbradas_segmentos_anio": "SELECT count(*) AS filas FROM timbradas_segmentos_anio WHERE proceso = :proceso",
    "timbradas_segmentos_consolidado": ("SELECT count(*) AS filas FROM timbradas_segmentos_consolidado "
                                        "WHERE proceso = :proceso"),
}


def segmentos_sin_filas(f) -> dict:
    from app.servicios import consolidados as C

    salida = {}
    for tabla in (C.TABLA_SEGMENTOS_ANIO, C.TABLA_SEGMENTOS):
        conteo = f.para_tabla(tabla).consultar(SQL_FILAS_DEL_PROCESO[tabla], {"proceso": PROCESO})
        cfg = C.CONFIG[tabla]
        salida[tabla] = {"filas_del_proceso": int(conteo["filas"].iloc[0]), "resultado_del_ciclo": "sin_filas_fuente",
                         "motivo": C.H4, "grano_del_contraste": list(cfg.grano),
                         "grano_del_rango": list(cfg.grano_rango), "nota_del_grano": cfg.nota}
    return salida


def _rel(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a - b).abs() / b.abs().clip(lower=1)


def analisis_h10(f, periodo: tuple[date, date]) -> dict:
    """Promedio por viaje del consolidado por ruta × día × hora frente a los viajes válidos por hora de salida y por
    hora de fin: la asignación del consolidado es la del fin del viaje (H10)."""
    params = {"desde": datetime.combine(periodo[0], datetime.min.time(), tzinfo=ZONA),
              "hasta": datetime.combine(date(periodo[1].year + 1, 1, 1), datetime.min.time(), tzinfo=ZONA)}
    cons = f.consultar(SQL_CONSOLIDADO_HORA, {"proceso": PROCESO})
    salida = {}
    for nombre, sql in (("por_hora_de_salida", SQL_VIAJES_SALIDA), ("por_hora_de_fin", SQL_VIAJES_FIN)):
        v = f.consultar(sql, params)
        m = cons.merge(v, on=["idruta", "dia", "hora"], suffixes=("_c", "_v"))
        for c in m.columns.difference(["idruta", "dia", "hora"]):
            m[c] = pd.to_numeric(m[c], errors="coerce")
        m = m[(m["n_c"] >= 30) & (m["n_v"] >= 30)]
        salida[nombre] = {
            "celdas": int(len(m)),
            "promedio_subidas": _cuantiles(_rel(m["subidas_c"] / m["n_c"], m["subidas_v"] / m["n_v"])),
            "promedio_bajadas": _cuantiles(_rel(m["bajadas_c"] / m["n_c"], m["bajadas_v"] / m["n_v"]))}
    return salida


def _enteros(d: pd.DataFrame) -> list[dict]:
    return [{k: (int(v) if pd.notna(v) else None) for k, v in x.items()} for x in d.to_dict("records")]


def festivos_repetidos(f) -> list[dict]:
    """H17: cada festivo de un día con más de una fila en estacionalidades_anio, los viajes que timbradas_anio guarda
    con cada fila y los viajes aptos de esa fecha de fin (todas las rutas del proceso)."""
    rep = f.consultar(SQL_FESTIVOS_REPETIDOS, {"proceso": PROCESO})
    if not len(rep):
        return []
    ids = sorted({int(i) for fila in rep["ids"] for i in fila})
    viajes = f.consultar(SQL_VIAJES_POR_ESTACIONALIDAD_ANIO, {"proceso": PROCESO, "ids": ids})
    por_id = {int(i): int(v) for i, v in zip(viajes["id_estacionalidad_anio"], viajes["viajes"], strict=True)}
    aptos = f.consultar(SQL_APTOS_POR_FECHA_DE_FIN, {"proceso": PROCESO, "fechas": [str(x) for x in rep["fecha"]]})
    por_fecha = {str(x): int(n) for x, n in zip(aptos["fecha"], aptos["aptos"], strict=True)}
    return [{"fecha": str(x["fecha"]), "ids": [int(i) for i in x["ids"]],
             "estacionalidades": [int(e) for e in x["estacionalidades"]],
             "viajes_timbradas_anio": {int(i): por_id.get(int(i), 0) for i in x["ids"]},
             "aptos_fecha_de_fin": por_fecha.get(str(x["fecha"]), 0)} for x in rep.to_dict("records")]


def anio_frente_a_aptos(f, periodo: tuple[date, date]) -> list[dict]:
    """H17: viajes de timbradas_anio frente a los viajes aptos por fecha de fin, por ruta y año, en total y en los días
    corrientes (estacionalidad vigente de período más corto = DIAS_CORRIENTES)."""
    corriente = int(f.consultar(SQL_DIAS_CORRIENTES, {"proceso": PROCESO})["id"].iloc[0])
    aptos = f.consultar(SQL_APTOS_POR_RUTA_Y_ANO, {"proceso": PROCESO, "corriente": corriente,
                                                   "desde": periodo[0], "hasta": periodo[1]})
    anio = f.consultar(SQL_ANIO_POR_RUTA_Y_ANO, {"proceso": PROCESO, "corriente": corriente,
                                                 "primero": periodo[0].year, "ultimo": periodo[1].year})
    m = _numeros(anio).merge(_numeros(aptos), on=["idruta", "ano"], how="outer").sort_values(["idruta", "ano"])
    return _enteros(m)


def _numeros(d: pd.DataFrame) -> pd.DataFrame:
    for c in d.columns:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def _cuantiles(s: pd.Series) -> dict:
    s = s.dropna()
    return {"mediana": round(float(s.median()), 4), "p90": round(float(s.quantile(0.9)), 4)}


def definicion_bajadas(f) -> dict:
    """En el solape de timbradas_segmentos: Σ bajadas de los segmentos frente a Σ numerobajadas de los viajes válidos,
    en los mismos viajes y en todos (cobertura)."""
    params = {"desde": datetime(2023, 1, 1, tzinfo=ZONA), "hasta": datetime(2023, 2, 28, tzinfo=ZONA)}
    d = f.consultar(SQL_DEFINICION_BAJADAS, params)
    for c in d.columns:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    filas = []
    for x in d.to_dict("records"):
        mismos = x["bajadas_viajes_mismos_viajes"]
        filas.append({**{k: int(v) for k, v in x.items()},
                      "diferencia_mismos_viajes": round((x["bajadas_segmentos_mismos_viajes"] - mismos) / mismos, 5),
                      "diferencia_total": round((x["bajadas_segmentos"] - x["bajadas_viajes_todos"])
                                                / x["bajadas_viajes_todos"], 5)})
    tot = {k: int(d[k].sum()) for k in d.columns if k != "idruta"}
    mismos = tot["bajadas_viajes_mismos_viajes"]
    tot["diferencia_mismos_viajes"] = round((tot["bajadas_segmentos_mismos_viajes"] - mismos) / mismos, 5)
    tot["diferencia_total"] = round((tot["bajadas_segmentos"] - tot["bajadas_viajes_todos"])
                                    / tot["bajadas_viajes_todos"], 5)
    return {"periodo": ["2023-01-01", "2023-02-27"], "por_ruta": filas, "total": tot}


# ---------------------------------------------------------------- informes
def _pct(x) -> str:
    return "—" if x is None else f"{100 * float(x):.1f} %".replace(".", ",")


def _miles(x) -> str:
    return f"{float(x):,.0f}".replace(",", ".")


def informe_contraste(r: dict) -> str:
    c, ruta = r["ruta"]["contraste"], r["ruta"]
    lin = ["# Consolidados de Extreme en el ciclo: lectura, calidad y contraste con la agregación propia", "",
           f"Generado {r['generado']} con `python -m scripts.contraste_consolidados` sobre la réplica local, en solo "
           "lectura (lector_ia), con las funciones del ciclo (`app/servicios/consolidados.py`).", "",
           "## timbradas_consolidado", "",
           f"- Lectura incremental desde la carga: {ruta['lectura']['leidas']} filas leídas y "
           f"{ruta['lectura']['entregadas']} entregadas (marca {ruta['marca']}). Segunda lectura con las huellas "
           f"(misma marca, ventana de solape): {ruta['segunda_lectura_con_huellas']['entregadas']} entregadas y "
           f"{ruta['segunda_lectura_con_huellas']['repetidas_solape']} descartadas por huella (H7).",
           f"- Calidad (§6.3, con los catálogos de la réplica: {', '.join(ruta['calidad']['catalogos'])}): "
           f"{ruta['calidad']['validas']} válidas; errores: {ruta['calidad']['errores_por_codigo'] or 'ninguno'}.",
           f"- Contraste con el histórico propio por {' × '.join(c['grano'])} en {ruta['periodo'][0]} a "
           f"{ruta['periodo'][1]} (años cerrados que suma el consolidado): {c['llaves']} llaves, {c['comparadas']} "
           f"comparadas, {c['sin_agregacion_propia']} sin histórico propio y {c['pocos_viajes']} con menos de "
           f"{int(c['tolerancias']['contraste_viajes_minimos'])} viajes. Incidencias: {c['diferencias']} "
           f"({c['groseras']} groseras, bloqueantes) con tolerancia {_pct(c['tolerancias']['contraste_tolerancia'])} y "
           f"grosera {_pct(c['tolerancias']['contraste_tolerancia_grosera'])}.", "",
           "| Medida | Llaves | Mediana | p90 | Máximo |", "|---|---|---|---|---|"]
    for campo, d in ruta["distribucion_diferencias"].items():
        lin.append(f"| {campo} | {d['llaves']} | {_pct(d['mediana'])} | {_pct(d['p90'])} | {_pct(d['maximo'])} |")
    lin += ["", "Totales 2023-2025 por ruta (Extreme frente al histórico propio):", "",
            "| id_ruta | Subidas Extreme | Subidas propias | Bajadas Extreme | Bajadas propias | Viajes Extreme | "
            "Viajes propios |", "|---|---|---|---|---|---|---|"]
    for k, t in ruta["totales_por_ruta"].items():
        lin.append(f"| {k} | {_miles(t['subidas_extreme'])} | {_miles(t['subidas_propia'])} | "
                   f"{_miles(t['bajadas_extreme'])} | {_miles(t['bajadas_propia'])} | {_miles(t['n_extreme'])} | "
                   f"{_miles(t['n_propia'])} |")
    lin += ["", "Incidencias (las que el ciclo guarda en data_quality_error con lote, llave, valor y bloqueante):", "",
            "| Llave | Campo | Valor de Extreme | Bloqueante | Detalle |", "|---|---|---|---|---|"]
    for i in ruta["incidencias"]:
        llave = ", ".join(f"{k}={v}" for k, v in i["llave"].items())
        lin.append(f"| {llave} | {i['campo']} | {i['valor_extreme']:.2f} | {'sí' if i['bloqueante'] else 'no'} | "
                   f"{i['detalle']} |")
    lin += _informe_h17(r.get("h17"))
    h = r["h10"]
    lin += ["", "## Por qué no por hora (hallazgo H10)", "",
            "Promedio por viaje del consolidado por ruta × día ISO × hora frente a los viajes válidos de 2023-2025 "
            "asignados a la hora de SALIDA (la del histórico propio) o a la de FIN del viaje (la de "
            "fn_insert_timbradas_anio), en las celdas con al menos 30 viajes de cada lado:", "",
            "| Asignación | Celdas | Subidas: mediana | Subidas: p90 | Bajadas: mediana | Bajadas: p90 |",
            "|---|---|---|---|---|---|"]
    for nombre, d in h.items():
        lin.append(f"| {nombre.replace('_', ' ')} | {d['celdas']} | {_pct(d['promedio_subidas']['mediana'])} | "
                   f"{_pct(d['promedio_subidas']['p90'])} | {_pct(d['promedio_bajadas']['mediana'])} | "
                   f"{_pct(d['promedio_bajadas']['p90'])} |")
    lin += ["", "Por hora de fin, el consolidado se reproduce casi exacto; por hora de salida, no, sin error de nadie. "
                "Por eso el ciclo contrasta por ruta × día ISO × estacionalidad, donde las dos asignaciones coinciden."]
    lin += _informe_segmentos(r["segmentos"])
    return "\n".join(lin) + "\n"


def _informe_segmentos(segmentos: dict) -> list[str]:
    """Sección del informe: las dos tablas por segmento sin filas del proceso (H4) y el grano con que el ciclo las
    contrasta cuando las tengan (sin la hora del bloque de Extreme, H10)."""
    lin = ["", "## timbradas_segmentos_anio y timbradas_segmentos_consolidado", ""]
    for tabla, d in segmentos.items():
        lin.append(f"- {tabla}: {d['filas_del_proceso']} filas del proceso {PROCESO!r} → el ciclo registra "
                   f"«{d['resultado_del_ciclo']}» en metricas.calidad.consolidados ({d['motivo']}). Cuando las tenga, "
                   f"la comparación que puede bloquear (CONTR-002) va por {' × '.join(d['grano_del_contraste'])}, y "
                   f"el rango (CONTR-003, no bloqueante), por {' × '.join(d['grano_del_rango'])}.")
    notas = sorted({d["nota_del_grano"] for d in segmentos.values()})
    lin += ["", f"El grano que puede bloquear: {'; '.join(notas)}. Medido con filas reales de la liquidación, en una "
                "transacción que se revierte: `segmentos_filas_reales.json` "
                "(`tests/replica/test_consolidados_segmentos.py`)."]
    return lin


def _dif(a, b) -> str:
    return "—" if a is None or not b else _pct((a - b) / b)


def _informe_h17(h: dict | None) -> list[str]:
    """Sección del informe: de dónde salen las diferencias groseras de viajes por día (H17)."""
    if not h:
        return []
    lin = ["", "## De dónde salen las diferencias groseras de viajes por día (H17)", "",
           "Festivos de un día con más de una fila en estacionalidades_anio: viajes que timbradas_anio guarda con "
           "cada fila frente a los viajes aptos (apto_estadisticas_historicas) con esa fecha de fin, todas las rutas:",
           "", "| Fecha | id_estacionalidad_anio (id_estacionalidad) | Viajes en timbradas_anio por fila | "
               "Viajes aptos |", "|---|---|---|---|"]
    for x in h["festivos_repetidos"]:
        ids = ", ".join(f"{i} ({e})" for i, e in zip(x["ids"], x["estacionalidades"], strict=True))
        viajes = ", ".join(f"{i}: {_miles(v)}" for i, v in x["viajes_timbradas_anio"].items())
        lin.append(f"| {x['fecha']} | {ids} | {viajes} | {_miles(x['aptos_fecha_de_fin'])} |")
    lin += ["", "timbradas_anio frente a los viajes aptos por fecha de fin, por ruta y año (DIAS_CORRIENTES: la "
                "estacionalidad vigente de período más corto, la regla de fn_insert_timbradas_anio):", "",
            "| idruta | Año | Viajes timbradas_anio | Aptos | Diferencia | DIAS_CORRIENTES en timbradas_anio | "
            "Aptos en días corrientes | Diferencia |", "|---|---|---|---|---|---|---|---|"]
    for x in h["anio_frente_a_aptos"]:
        lin.append(f"| {x['idruta']} | {x['ano']} | {_miles(x['viajes'] or 0)} | {_miles(x['aptos'] or 0)} | "
                   f"{_dif(x['viajes'], x['aptos'])} | {_miles(x['viajes_corrientes'] or 0)} | "
                   f"{_miles(x['aptos_corrientes'] or 0)} | {_dif(x['viajes_corrientes'], x['aptos_corrientes'])} |")
    lin += ["", "Un viaje cuenta una vez con la regla de fn_insert_timbradas_anio (una sola estacionalidad por viaje, "
                "la de período más corto). En la exportación de timbradas_anio, los festivos con dos filas aparecen "
                "con las dos y los días corrientes suman más viajes que los aptos de esas fechas: son preguntas para "
                "Extreme, no diferencias del contraste."]
    return lin


def informe_bajadas(d: dict) -> str:
    t = d["total"]
    lin = ["# Definición de bajadas en el histórico (§6.1 «Bajadas: descensos consolidados»)", "",
           f"Generado {d['generado']} con `python -m scripts.contraste_consolidados` sobre la réplica local, en solo "
           f"lectura (lector_ia), en el solape de timbradas_segmentos ({d['periodo'][0]} a {d['periodo'][1]}).", "",
           "| idruta | Viajes válidos | Con timbradas | Sin numerobajadas | Σ bajadas segmentos (mismos viajes) | "
           "Σ numerobajadas (mismos viajes) | Diferencia | Σ numerobajadas (todos) | Diferencia total |",
           "|---|---|---|---|---|---|---|---|---|"]
    for x in [*d["por_ruta"], {**t, "idruta": "Total"}]:
        lin.append(f"| {x['idruta']} | {_miles(x['viajes_validos'])} | {_miles(x['viajes_con_timbradas'])} | "
                   f"{_miles(x['viajes_sin_numerobajadas'])} | {_miles(x['bajadas_segmentos_mismos_viajes'])} | "
                   f"{_miles(x['bajadas_viajes_mismos_viajes'])} | {_pct(x['diferencia_mismos_viajes'])} | "
                   f"{_miles(x['bajadas_viajes_todos'])} | {_pct(x['diferencia_total'])} |")
    lin += ["", f"- En los mismos viajes, las bajadas de los segmentos y numerobajadas difieren "
                f"{_pct(t['diferencia_mismos_viajes'])}: miden lo mismo.",
            f"- En total difieren {_pct(t['diferencia_total'])}: la diferencia es de cobertura (viajes válidos sin "
            "timbradas), como la de pasajeros (definicion_pasajeros.md).",
            "- Decisión (aplicada en la migración 0013): el histórico guarda bajadas_viajes = Σ numerobajadas de los "
            "viajes válidos (dato <= 300, ceros incluidos), la definición de pasajeros, que cubre todo 2023-2025 y es "
            "la que usan ALT-008, su backtest y el contraste con timbradas_consolidado; las bajadas y subidas de los "
            "segmentos quedan también en el histórico (columnas bajadas, subidas y viajes_con_timbradas)."]
    return "\n".join(lin) + "\n"


def correr() -> dict:
    f = fuente()
    generado = datetime.now(ZONA).isoformat(timespec="seconds")
    ruta = contraste_ruta(f)
    periodo = tuple(date.fromisoformat(p) for p in ruta["periodo"])
    r = {"generado": generado, "ruta": ruta, "segmentos": segmentos_sin_filas(f), "h10": analisis_h10(f, periodo),
         "h17": {"festivos_repetidos": festivos_repetidos(f), "anio_frente_a_aptos": anio_frente_a_aptos(f, periodo)}}
    b = dict(definicion_bajadas(f), generado=generado)
    f._engine().dispose()
    return {"contraste": r, "bajadas": b}


def main() -> None:
    r = correr()
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "contraste_consolidados.json").write_text(json.dumps(r["contraste"], ensure_ascii=False, indent=1,
                                                                   default=str), encoding="utf-8")
    (SALIDA / "contraste_consolidados.md").write_text(informe_contraste(r["contraste"]), encoding="utf-8")
    (SALIDA / "definicion_bajadas.json").write_text(json.dumps(r["bajadas"], ensure_ascii=False, indent=1,
                                                               default=str), encoding="utf-8")
    (SALIDA / "definicion_bajadas.md").write_text(informe_bajadas(r["bajadas"]), encoding="utf-8")
    print(informe_contraste(r["contraste"]))
    print(informe_bajadas(r["bajadas"]))


if __name__ == "__main__":
    main()
