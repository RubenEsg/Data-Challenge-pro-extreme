"""Lo que alimenta el corto plazo con la lectura incremental (RF-004, RF-005, RF-013, §6.3): el calendario de fechas
nuevas, la regla de calidad VAL-009, la unión del panel con lo leído y hasta dónde se puede pronosticar un día leído.
Con datos sintéticos y el calendario empaquetado, sin base de datos."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.servicios import corto_plazo as cp
from app.servicios import datos
from app.servicios import panel_corto_plazo as P
from app.servicios import variables_corto_plazo as V

BOGOTA = ZoneInfo("America/Bogota")


def test_el_calendario_reproduce_el_del_panel_dia_por_dia():
    """La misma regla que armó datos/corto_plazo/calendario.csv (2023-2025), para poder extenderlo a fechas nuevas."""
    empaquetado = pd.read_csv(datos.carpeta_datos() / "corto_plazo" / "calendario.csv", parse_dates=["fecha"])
    mio = P.calendario(date(2023, 1, 1), date(2025, 12, 31))
    assert (mio["fecha"].to_numpy() == empaquetado["fecha"].to_numpy()).all()
    assert (mio[P.COLUMNAS_CALENDARIO].to_numpy() == empaquetado[P.COLUMNAS_CALENDARIO].to_numpy()).all()


def test_festivos_y_fechas_moviles_de_2026():
    f = P.festivos(2026)
    assert P.pascua(2026) == date(2026, 4, 5)
    for d in (date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2), date(2026, 4, 3),
              date(2026, 5, 18), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 29), date(2026, 8, 17),
              date(2026, 10, 12), date(2026, 11, 2), date(2026, 11, 16), date(2026, 12, 8), date(2026, 12, 25)):
        assert d in f, d
    c = P.calendario(date(2026, 2, 13), date(2026, 2, 18)).set_index("fecha")
    assert c.loc[pd.Timestamp("2026-02-14"):pd.Timestamp("2026-02-17"), "carnaval"].tolist() == [1, 1, 1, 1]
    assert c.loc[pd.Timestamp("2026-02-18"), "carnaval"] == 0          # Miércoles de Ceniza
    assert P.calendario(date(2026, 3, 23), date(2026, 3, 23))["tipo_dia"].iloc[0] == 2   # lunes festivo


def test_la_regla_de_calidad_excluye_y_deja_la_llave():
    y = np.zeros((3, V.BLOQUES, 4), np.float32)
    y[1, 30, 2] = 28_782
    y[2, 40, 0] = 497            # alto pero creíble
    excluidas = P.excluir_imposibles(y, date(2025, 7, 4), 16, 1000.0)
    assert excluidas == [{"idruta": 16, "fecha": "2025-07-05", "bloque": 30, "nro_segmento": 3, "subidas": 28782.0}]
    assert y[1, 30, 2] == 0 and y[2, 40, 0] == 497
    e = P.error_calidad(excluidas[0], 1000.0)
    assert e["codigo"] == "VAL-009" and e["bloqueante"] and e["llave"]["nro_segmento"] == 3
    assert P.tope({"cp_tope_subidas_bloque_segmento": 500}) == 500 and P.tope({}) == P.TOPE_POR_OMISION
    assert P.tope({"cp_tope_subidas_bloque_segmento": -1}) == P.TOPE_POR_OMISION


def _base(dias: int = 70, segmentos: int = 4) -> V.Ruta:
    y = np.ones((dias, V.BLOQUES, segmentos), np.float32)
    sal = np.ones((dias, V.BLOQUES), np.float32)
    seg = pd.DataFrame({"nro_segmento": np.arange(1, segmentos + 1), "sentido": ["ida", "ida", "regreso", "regreso"]})
    fechas = pd.date_range(V.DIA0, periods=dias, freq="D")
    cal = P.calendario(fechas[0].date(), fechas[-1].date())
    cal["dia_semana"], cal["mes"], cal["dia_mes"] = fechas.dayofweek, fechas.month, fechas.day
    return V.Ruta(2, "SILENCIO", y, sal, seg, cal, V.dias_con_datos(y.sum(axis=(1, 2))))


def test_lo_leido_reemplaza_el_dia_y_extiende_la_serie():
    base = _base()
    dia0 = V.DIA0.date()
    ultimo = dia0 + timedelta(days=69)
    nuevo, otro = ultimo + timedelta(days=1), dia0 + timedelta(days=10)
    sub = pd.DataFrame({"fecha": [nuevo, nuevo, otro], "bloque": [20, 21, 30], "nro_segmento": [1, 4, 2],
                        "subidas": [5.0, 7.0, 9.0]})
    sal = pd.DataFrame({"fecha": [nuevo], "bloque": [20], "salidas": [3.0]})
    solo_leido = dia0 + timedelta(days=12)      # un día del panel leído sin celdas guardadas (modo Parquet)
    lei = P.Leidos("v1", sub, sal, {nuevo: datetime(nuevo.year, nuevo.month, nuevo.day, 23, 59, 59, tzinfo=BOGOTA),
                                     otro: datetime(otro.year, otro.month, otro.day, 23, 59, 59, tzinfo=BOGOTA),
                                     solo_leido: datetime(solo_leido.year, solo_leido.month, solo_leido.day, 23, 59,
                                                          59, tzinfo=BOGOTA)})
    r, fechas = P.unir(base, lei, dia0)
    assert len(r.cal) == 72                     # el día leído y uno vacío después (su primer instante)
    assert r.y[70, 20, 0] == 5 and r.y[70, 21, 3] == 7 and r.y[70].sum() == 12 and r.sal[70, 20] == 3
    assert r.y[71].sum() == 0
    assert r.y[10].sum() == 9                   # el día del panel con celdas guardadas queda como se guardó
    assert r.y[12].sum() == base.y[12].sum()    # el día del panel leído sin celdas guardadas, como en el panel
    assert r.y[11].sum() == base.y[11].sum()    # los demás, como estaban
    assert r.cal["fecha"].iloc[-1] == pd.Timestamp(nuevo + timedelta(days=1)) and fechas == sorted(lei.hasta)
    assert base.y.shape[0] == 70                # el panel no se toca


def test_hasta_donde_se_puede_pronosticar_un_dia_leido():
    fin = date(2025, 12, 31)
    nuevo = date(2026, 1, 1)
    sc = cp.Serie(ruta=None, version="x", excluidas=(), fin_panel=cp.dia_de_fecha(fin),
                  hasta={nuevo: datetime(2026, 1, 1, 9, 4, tzinfo=BOGOTA)})
    assert cp.limite_lectura(sc, fin) is None                               # un día del panel: sin límite
    assert cp.limite_lectura(sc, nuevo) == datetime(2026, 1, 1, 9, 4, tzinfo=BOGOTA)
    # el día siguiente a uno leído a medias no se puede pronosticar todavía
    assert cp.limite_lectura(sc, date(2026, 1, 2)) == datetime(2026, 1, 2, tzinfo=BOGOTA)
    completo = cp.Serie(ruta=None, version="x", excluidas=(), fin_panel=cp.dia_de_fecha(fin),
                        hasta={nuevo: datetime(2026, 1, 1, 23, 59, 59, tzinfo=BOGOTA)})
    assert cp.limite_lectura(completo, date(2026, 1, 2)) == datetime(2026, 1, 2, 4, tzinfo=BOGOTA)
    # el primer día después del panel, sin nada leído: su primer instante
    assert cp.limite_lectura(cp.Serie(None, "x", (), {}, cp.dia_de_fecha(fin)), nuevo) == \
        datetime(2026, 1, 1, 4, tzinfo=BOGOTA)
    assert cp.bloques_leidos(nuevo, None) is None
    assert cp.bloques_leidos(nuevo, datetime(2025, 12, 31, 23, 59, 59, tzinfo=BOGOTA)) == 0
    assert cp.bloques_leidos(nuevo, datetime(2026, 1, 1, 23, 59, 59, tzinfo=BOGOTA)) is None
    assert cp.bloques_leidos(nuevo, datetime(2026, 1, 2, 1, tzinfo=BOGOTA)) is None


def test_la_migracion_0016_versiona_el_mismo_tope_del_codigo():
    """El tope VAL-009 está copiado en la migración 0016 (una migración no depende del código que evoluciona): tiene
    que ser el mismo valor y la misma descripción que usa app/servicios/panel_corto_plazo.py."""
    import importlib.util
    from pathlib import Path

    ruta = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0016_corto_plazo_en_vivo.py"
    spec = importlib.util.spec_from_file_location("migracion_0016", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.UMBRALES_0016 == [(P.PARAMETRO_TOPE, P.TOPE_POR_OMISION, P.DESCRIPCION_TOPE)]
