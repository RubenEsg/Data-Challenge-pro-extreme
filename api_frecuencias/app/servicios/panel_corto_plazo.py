"""Lo que alimenta el pronóstico de corto plazo con la lectura incremental (RF-005, RF-013 «en cada ejecución actualiza
las variables y genera nuevas predicciones», §7.3 pasos 2 a 4, §11.2, RF-004 y §6.3).

El modelo de corto plazo trabaja con un panel de 15 minutos: las subidas de cada segmento oficial de 500 m y las salidas
(viajes que iniciaron) de cada ruta, por bloque. El panel empaquetado (datos/corto_plazo) trae 2023-2025, el periodo
con que se eligió y se midió el modelo. Cada ciclo (el diario y los intradía) lee los días que trajo la lectura
incremental y lo deja en el esquema propio (migración 0016):

- ai_frecuencias.lectura_15min: por ruta y día, hasta qué instante se leyó, de qué fuente, en qué ejecución, cuántas
  celdas válidas y cuántas se excluyeron por calidad;
- ai_frecuencias.subidas_15min (ruta, día, bloque, segmento, subidas) y salidas_15min (ruta, día, bloque, salidas): las
  celdas válidas de los días que el panel empaquetado no tiene (los posteriores a su último día). Las de un día del
  panel no se copian: ya están empaquetadas, con la misma regla de calidad al servir, y copiarlas duplicaría 12,3
  millones de celdas en la base y en cada relectura.

De dónde se lee:
- modo integrado (FUENTE=postgres): de timbradas_segmentos, lo que escribe el trigger de conteo de Extreme (subidas
  por viaje, segmento y bloque de 15 minutos; la regla del segmento más cercano es la suya), y de progvehiculos
  (fechainicio), solo SELECT en una transacción READ ONLY (app/servicios/fuentes.py, lista blanca). Se re-agregan los
  días completos que tocó la lectura incremental, con lo que se actualizó antes de la marca de agua de la ejecución.
- modo Parquet (sin la base operacional): del panel empaquetado, los días que trajo la lectura horaria de la ejecución
  (la llegada simulada, como la serie horaria): se validan y se anota hasta dónde se leyeron.

Calidad (VAL-009, dimensión validez): una celda con más subidas que el tope gobernado `cp_tope_subidas_bloque_segmento`
(threshold_config; 1.000 por omisión: un segmento de 500 m en 15 minutos no recibe más de unos 18 buses × 50 puestos)
se excluye (cuenta como no observada) y queda en data_quality_error con su llave (idruta, fecha, bloque, segmento). Con
1.000 solo caen los dos registros imposibles de la base (97.157 subidas el 26-05-2024 y 28.782 el 05-07-2025, los dos
en CRA 54); la celda normal más alta del panel tiene 497. La misma regla se aplica al panel empaquetado al servir; la
reproducción de la prueba reservada la apaga (corto_plazo.sin_calidad), porque esa prueba se midió con los datos tal
cual.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from . import datos

TOPE_POR_OMISION = 1000.0
PARAMETRO_TOPE = "cp_tope_subidas_bloque_segmento"
CODIGO_CALIDAD = "VAL-009"
LOTE = "corto_plazo_15min"
BLOQUES = 96
DESCRIPCION_TOPE = ("Corto plazo (VAL-009): subidas máximas creíbles de un segmento de 500 m en un bloque de 15 "
                    "minutos; una celda por encima se excluye del pronóstico y queda en data_quality_error")
COLUMNAS_CALENDARIO = ["tipo_dia", "festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero",
                       "vac_escolar", "vac_univ"]


# ----------------------------------------------------------------------------------------------- calendario
def pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo anónimo gregoriano)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes = (h + m - 7 * n + 114) // 31
    dia = (h + m - 7 * n + 114) % 31 + 1
    return date(anio, mes, dia)


def _lunes(d: date) -> date:
    """El mismo día si es lunes; si no, el lunes siguiente (Ley Emiliani, Ley 51 de 1983)."""
    return d + timedelta(days=(7 - d.weekday()) % 7)


@lru_cache(maxsize=32)
def festivos(anio: int) -> frozenset[date]:
    """Los festivos de Colombia del año: los fijos, los que se trasladan al lunes y los que dependen de la Pascua
    (Jueves y Viernes Santo; Ascensión, Corpus Christi y Sagrado Corazón, trasladados al lunes)."""
    p = pascua(anio)
    fijos = {date(anio, 1, 1), date(anio, 5, 1), date(anio, 7, 20), date(anio, 8, 7), date(anio, 12, 8),
             date(anio, 12, 25)}
    trasladables = (date(anio, 1, 6), date(anio, 3, 19), date(anio, 6, 29), date(anio, 8, 15), date(anio, 10, 12),
                    date(anio, 11, 1), date(anio, 11, 11))
    de_pascua = {p - timedelta(days=3), p - timedelta(days=2), p + timedelta(days=43), p + timedelta(days=64),
                 p + timedelta(days=71)}
    return frozenset(fijos | {_lunes(d) for d in trasladables} | de_pascua)


def _en_periodos(fecha: date, periodos: list[tuple[date, date]]) -> bool:
    return any(a <= fecha <= b for a, b in periodos)


def calendario(desde: date, hasta: date) -> pd.DataFrame:
    """El calendario del panel de corto plazo para cualquier rango de fechas (las mismas columnas de
    datos/corto_plazo/calendario.csv, con las mismas reglas: una prueba verifica que reproduce 2023-2025 día por día).
    - festivo: los de Colombia; tipo_dia: 2 domingo o festivo, 1 sábado, 0 el resto;
    - carnaval: de sábado a martes antes del Miércoles de Ceniza; semana_santa: de lunes a domingo de Pascua;
    - vacaciones: enero, junio y julio, y del 16 al 31 de diciembre; navidad: 25-dic; primero_enero: 1-ene;
    - vac_escolar y vac_univ: los periodos de datos/calendario_academico.csv (receso escolar; sin clases
      universitarias)."""
    fechas = [desde + timedelta(days=k) for k in range((hasta - desde).days + 1)]
    ac = datos.calendario_academico()
    recesos = [(r.inicio, r.fin) for r in ac.itertuples() if r.tipo == "escolar_receso"]
    clases = [(r.inicio, r.fin) for r in ac.itertuples() if r.tipo == "universitario_clases"]
    filas = []
    for f in fechas:
        p = pascua(f.year)
        festivo = f in festivos(f.year)
        filas.append({
            "fecha": pd.Timestamp(f), "tipo_dia": datos.tipo_dia_de(f, festivo), "festivo": int(festivo),
            "carnaval": int(p - timedelta(days=50) <= f <= p - timedelta(days=47)),
            "semana_santa": int(p - timedelta(days=6) <= f <= p),
            "vacaciones": int(f.month in (1, 6, 7) or (f.month == 12 and f.day >= 16)),
            "navidad": int(f.month == 12 and f.day == 25), "primero_enero": int(f.month == 1 and f.day == 1),
            "vac_escolar": int(_en_periodos(f, recesos)), "vac_univ": int(not _en_periodos(f, clases))})
    return pd.DataFrame(filas, columns=["fecha", *COLUMNAS_CALENDARIO])


# ----------------------------------------------------------------------------------------------- calidad
def tope(umbrales: dict | None) -> float:
    try:
        valor = float((umbrales or {}).get(PARAMETRO_TOPE, TOPE_POR_OMISION))
    except (TypeError, ValueError):
        valor = TOPE_POR_OMISION
    return valor if valor > 0 else TOPE_POR_OMISION


def excluir_imposibles(y: np.ndarray, dia0: date, idruta: int, maximo: float) -> list[dict]:
    """VAL-009 sobre la serie (D, 96, S) de una ruta: pone en 0 (no observada) cada celda por encima del tope y
    devuelve las excluidas con su llave."""
    malas = np.argwhere(y > maximo)
    salida = [{"idruta": int(idruta), "fecha": (dia0 + timedelta(days=int(d))).isoformat(), "bloque": int(b),
               "nro_segmento": int(s) + 1, "subidas": float(y[d, b, s])} for d, b, s in malas]
    if len(malas):
        y[y > maximo] = 0
    return salida


def error_calidad(celda: dict, maximo: float) -> dict:
    """La fila de data_quality_error de una celda excluida (§6.3: la llave lleva al registro exacto)."""
    return {"lote": LOTE, "campo": "subidas", "codigo": CODIGO_CALIDAD, "dimension": "validez", "bloqueante": True,
            "valor": celda["subidas"],
            "llave": {k: celda[k] for k in ("idruta", "fecha", "bloque", "nro_segmento")},
            "detalle": (f"{celda['subidas']:.0f} subidas en un bloque de 15 minutos de un segmento de 500 m: más que "
                        f"el tope de {maximo:.0f} ({PARAMETRO_TOPE}); la celda se excluye del pronóstico de corto "
                        "plazo")}


# ----------------------------------------------------------------------------------------------- lectura de la fuente
def segmentos(idruta: int) -> pd.DataFrame:
    """Los segmentos oficiales de la ruta con su id_segmento de rutas_segmentos (datos/corto_plazo/segmentos.csv)."""
    s = pd.read_csv(datos.carpeta_datos() / "corto_plazo" / "segmentos.csv")
    return s[s["idruta"] == int(idruta)].sort_values("nro_segmento").reset_index(drop=True)


def fin_del_panel() -> date:
    """El último día del panel empaquetado (su calendario)."""
    return _fin_del_panel(str(datos.carpeta_datos() / "corto_plazo" / "calendario.csv"))


@lru_cache(maxsize=4)
def _fin_del_panel(ruta: str) -> date:
    return pd.to_datetime(pd.read_csv(ruta, usecols=["fecha"])["fecha"]).max().date()


def del_panel(idruta: int, fechas: list[date]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Modo Parquet: las celdas del panel empaquetado de esos días (la llegada simulada)."""
    carpeta = datos.carpeta_datos() / "corto_plazo"
    dias = sorted(set(fechas))
    if not dias:
        return _vacio_subidas(), _vacio_salidas()
    filtro = [("idruta", "==", int(idruta)), ("dia", "in", dias)]
    sub = pd.read_parquet(carpeta / "subidas_segmento_15min.parquet", filters=filtro)
    sal = pd.read_parquet(carpeta / "salidas_15min.parquet", filters=filtro)
    sub = sub[sub["nro_segmento"] > 0]
    return (pd.DataFrame({"fecha": pd.to_datetime(sub["dia"]).dt.date, "bloque": sub["bloque"].astype(int),
                          "nro_segmento": sub["nro_segmento"].astype(int), "subidas": sub["subidas"].astype(float)}),
            pd.DataFrame({"fecha": pd.to_datetime(sal["dia"]).dt.date, "bloque": sal["bloque"].astype(int),
                          "salidas": sal["salidas"].astype(float)}))


def de_la_fuente(fuente, idruta: int, fechas: list[date], hasta: datetime | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Modo integrado: re-agrega los días completos de timbradas_segmentos (lo actualizado antes de `hasta`) y las
    salidas de progvehiculos, en solo lectura. Un id_segmento que no es de los segmentos oficiales de la ruta se
    descarta (no tiene número de segmento en el modelo)."""
    seg = segmentos(idruta)
    sub, sal = fuente.leer_panel_15min(int(idruta), [int(x) for x in seg["id_segmento"]], sorted(set(fechas)), hasta)
    nro = dict(zip(seg["id_segmento"].astype(int), seg["nro_segmento"].astype(int), strict=True))
    if len(sub):
        sub = sub.assign(nro_segmento=sub["id_segmento"].astype(int).map(nro))
        sub = sub[sub["nro_segmento"].notna()]
    return (pd.DataFrame({"fecha": pd.to_datetime(sub["fecha"]).dt.date if len(sub) else [],
                          "bloque": sub["bloque"].astype(int) if len(sub) else [],
                          "nro_segmento": sub["nro_segmento"].astype(int) if len(sub) else [],
                          "subidas": sub["subidas"].astype(float) if len(sub) else []}),
            pd.DataFrame({"fecha": pd.to_datetime(sal["fecha"]).dt.date if len(sal) else [],
                          "bloque": sal["bloque"].astype(int) if len(sal) else [],
                          "salidas": sal["salidas"].astype(float) if len(sal) else []}))


def _vacio_subidas() -> pd.DataFrame:
    return pd.DataFrame({"fecha": pd.Series(dtype=object), "bloque": pd.Series(dtype=int),
                         "nro_segmento": pd.Series(dtype=int), "subidas": pd.Series(dtype=float)})


def _vacio_salidas() -> pd.DataFrame:
    return pd.DataFrame({"fecha": pd.Series(dtype=object), "bloque": pd.Series(dtype=int),
                         "salidas": pd.Series(dtype=float)})


# ----------------------------------------------------------------------------------------------- guardado
def guardar_dias(s, idruta: int, sub: pd.DataFrame, sal: pd.DataFrame, hastas: dict[date, datetime],
                 fuente: str, execution_id, maximo: float) -> tuple[dict, list[dict]]:
    """Anota hasta dónde se leyó cada día de la ruta ({fecha: instante}) y guarda las celdas válidas de los días que el
    panel empaquetado no tiene (las de un día del panel ya están empaquetadas). Devuelve el resumen y los errores de
    calidad (VAL-009) para data_quality_error. Todo en lote: una sola pasada por las celdas, un borrado y una
    inserción por tabla."""
    fechas = sorted(hastas)
    resumen = {"dias": 0, "celdas": 0, "subidas": 0.0, "excluidas": 0, "guardadas": 0}
    if not fechas:
        return resumen, []
    sub = sub[sub["fecha"].isin(fechas)]
    sal = sal[sal["fecha"].isin(fechas) & (sal["salidas"] > 0)]
    validas = sub["subidas"] <= maximo
    errores = [error_calidad({"idruta": int(idruta), "fecha": c.fecha.isoformat(), "bloque": int(c.bloque),
                              "nro_segmento": int(c.nro_segmento), "subidas": float(c.subidas)}, maximo)
               for c in sub[~validas].itertuples()]
    buenas = sub[validas & (sub["subidas"] > 0)]
    # las celdas de los días que el panel empaquetado no tiene; las de un día del panel se borran (una copia anterior)
    fin = fin_del_panel()
    nuevas = buenas[buenas["fecha"] > fin]
    _reemplazar_celdas(s, idruta, fechas, nuevas, sal[sal["fecha"] > fin])
    filas = _lecturas(idruta, fechas, hastas, buenas, sub[~validas], fuente, execution_id)
    _guardar_lecturas(s, filas)
    for k in ("celdas", "subidas", "excluidas"):
        resumen[k] = sum(f[k] for f in filas)
    resumen["dias"] = len(filas)
    resumen["guardadas"] = int(len(nuevas))
    _LEIDOS.invalidar()
    return resumen, errores


def _reemplazar_celdas(s, idruta: int, fechas: list[date], sub: pd.DataFrame, sal: pd.DataFrame) -> None:
    """Borra las celdas guardadas de esos días de la ruta e inserta las nuevas, en lote."""
    from sqlalchemy import delete
    from sqlalchemy.dialects.postgresql import insert

    from app.modelos_db import Salidas15Min, Subidas15Min

    for i in range(0, len(fechas), 500):
        lote = fechas[i:i + 500]
        for tabla in (Subidas15Min, Salidas15Min):
            s.execute(delete(tabla).where(tabla.idruta == int(idruta), tabla.fecha.in_(lote)))
    if len(sub):
        s.execute(insert(Subidas15Min), [{"idruta": int(idruta), "fecha": r.fecha, "bloque": int(r.bloque),
                                          "nro_segmento": int(r.nro_segmento), "subidas": float(r.subidas)}
                                         for r in sub.itertuples()])
    if len(sal):
        s.execute(insert(Salidas15Min), [{"idruta": int(idruta), "fecha": r.fecha, "bloque": int(r.bloque),
                                          "salidas": float(r.salidas)} for r in sal.itertuples()])


def _lecturas(idruta: int, fechas: list[date], hastas: dict, buenas: pd.DataFrame, malas: pd.DataFrame, fuente: str,
              execution_id) -> list[dict]:
    """Una fila de lectura_15min por día: hasta dónde se leyó, cuántas celdas válidas, cuántas subidas y cuántas
    excluidas."""
    por_dia = buenas.groupby("fecha")["subidas"].agg(["size", "sum"]) if len(buenas) else pd.DataFrame(
        columns=["size", "sum"])
    excluidas = malas.groupby("fecha").size() if len(malas) else pd.Series(dtype=int)
    ahora = datetime.now().astimezone()
    filas = []
    for f in fechas:
        celdas = int(por_dia.at[f, "size"]) if f in por_dia.index else 0
        filas.append({"idruta": int(idruta), "fecha": f, "hasta": hastas[f], "fuente": fuente,
                      "execution_id": execution_id, "celdas": celdas,
                      "subidas": float(por_dia.at[f, "sum"]) if celdas else 0.0,
                      "excluidas": int(excluidas.get(f, 0)), "leido_en": ahora})
    return filas


def _guardar_lecturas(s, filas: list[dict]) -> None:
    from sqlalchemy.dialects.postgresql import insert

    from app.modelos_db import Lectura15Min

    for i in range(0, len(filas), 500):
        q = insert(Lectura15Min).values(filas[i:i + 500])
        s.execute(q.on_conflict_do_update(index_elements=["idruta", "fecha"], set_={
            k: q.excluded[k] for k in ("hasta", "fuente", "execution_id", "celdas", "subidas", "excluidas",
                                       "leido_en")}))


# ----------------------------------------------------------------------------------------------- lo leído, en memoria
@dataclass(frozen=True)
class Leidos:
    """Lo leído de una ruta: las celdas por día y hasta dónde se leyó cada día."""
    version: str
    subidas: pd.DataFrame        # fecha, bloque, nro_segmento, subidas
    salidas: pd.DataFrame        # fecha, bloque, salidas
    hasta: dict                  # {fecha: instante leído}


class _CacheLeidos:
    """Lo leído por ruta, se relee de la base solo si cambió (versión = filas y última lectura de lectura_15min)."""

    def __init__(self):
        self._candado = threading.Lock()
        self._datos: dict[tuple[str, int], Leidos] = {}

    def invalidar(self) -> None:
        with self._candado:
            self._datos.clear()

    def de(self, s, idruta: int) -> Leidos:
        from sqlalchemy import func, select

        from app.modelos_db import Lectura15Min, Salidas15Min, Subidas15Min

        n, ultima = s.execute(select(func.count(), func.max(Lectura15Min.leido_en))
                              .where(Lectura15Min.idruta == int(idruta))).one()
        version = f"{n}|{ultima.isoformat() if ultima else '-'}"
        clave = (str(s.get_bind().url), int(idruta))
        with self._candado:
            previo = self._datos.get(clave)
        if previo is not None and previo.version == version:
            return previo
        if not n:
            leidos = Leidos(version, _vacio_subidas(), _vacio_salidas(), {})
        else:
            sub = pd.DataFrame(s.execute(select(Subidas15Min.fecha, Subidas15Min.bloque, Subidas15Min.nro_segmento,
                                                Subidas15Min.subidas).where(Subidas15Min.idruta == int(idruta))).all(),
                               columns=["fecha", "bloque", "nro_segmento", "subidas"])
            sal = pd.DataFrame(s.execute(select(Salidas15Min.fecha, Salidas15Min.bloque, Salidas15Min.salidas)
                                         .where(Salidas15Min.idruta == int(idruta))).all(),
                               columns=["fecha", "bloque", "salidas"])
            hasta = dict(s.execute(select(Lectura15Min.fecha, Lectura15Min.hasta)
                                   .where(Lectura15Min.idruta == int(idruta))).all())
            leidos = Leidos(version, sub, sal, hasta)
        with self._candado:
            self._datos[clave] = leidos
        return leidos


_LEIDOS = _CacheLeidos()


def leidos(s, idruta: int) -> Leidos:
    return _LEIDOS.de(s, idruta)


def _dias_desde(fechas, dia0: date) -> np.ndarray:
    """Cada fecha como número de día desde dia0 (vectorizado)."""
    if not len(fechas):
        return np.zeros(0, int)
    return ((pd.to_datetime(pd.Series(list(fechas))) - pd.Timestamp(dia0)).dt.days).to_numpy()


def unir(base, lei: Leidos, dia0: date):
    """La serie de la ruta con lo leído: un día con celdas guardadas reemplaza al del panel empaquetado (si lo había),
    un día del panel leído sin celdas guardadas queda como en el panel (con la misma regla de calidad), y los días
    posteriores al panel extienden la serie, con su calendario, más un día vacío después del último leído (su primer
    instante, a las 04:00, solo usa días anteriores). Devuelve (Ruta, fechas leídas)."""
    from . import variables_corto_plazo as V

    if not lei.hasta:
        return base, []
    n0 = len(base.cal)
    ultimo = (max(lei.hasta) - dia0).days
    n = max(n0, ultimo + 2 if ultimo >= n0 - 1 else n0)
    y = np.zeros((n, BLOQUES, base.y.shape[2]), np.float32)
    sal = np.zeros((n, BLOQUES), np.float32)
    y[:n0], sal[:n0] = base.y, base.sal
    d_sub, d_sal = _dias_desde(lei.subidas["fecha"], dia0), _dias_desde(lei.salidas["fecha"], dia0)
    dias = np.unique(np.concatenate([d_sub, d_sal]).astype(int))
    dias = dias[(dias >= 0) & (dias < n)]
    y[dias], sal[dias] = 0, 0
    if len(lei.subidas):
        m = (d_sub >= 0) & (lei.subidas["nro_segmento"].to_numpy() <= base.y.shape[2])
        np.add.at(y, (d_sub[m], lei.subidas["bloque"].to_numpy()[m], lei.subidas["nro_segmento"].to_numpy()[m] - 1),
                  lei.subidas["subidas"].to_numpy()[m])
    if len(lei.salidas):
        m = d_sal >= 0
        np.add.at(sal, (d_sal[m], lei.salidas["bloque"].to_numpy()[m]), lei.salidas["salidas"].to_numpy()[m])
    cal = base.cal
    if n > n0:
        extra = calendario(dia0 + timedelta(days=n0), dia0 + timedelta(days=n - 1))
        extra["dia_semana"] = extra["fecha"].dt.dayofweek
        extra["mes"] = extra["fecha"].dt.month
        extra["dia_mes"] = extra["fecha"].dt.day
        cal = pd.concat([base.cal, extra[base.cal.columns]], ignore_index=True)
    return V.Ruta(base.idruta, base.nombre, y, sal, base.seg, cal, V.dias_con_datos(y.sum(axis=(1, 2)))), \
        sorted(lei.hasta)
