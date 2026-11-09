"""Unidad de la ingesta con COPY (sin base): conversión vectorizada del lote validado a filas de COPY."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.servicios import ingesta

BOGOTA = timezone(timedelta(hours=-5))


def _lote() -> pd.DataFrame:
    return pd.DataFrame({
        "ruta": ["CRA 54", "CL 72", "CL 84"],
        "fecha": ["2025-03-01", date(2025, 3, 2), pd.Timestamp("2025-03-03")],
        "hora": [5.0, 6, np.int64(23)],
        "pasajeros": [12.5, np.nan, 0],
        "salidas": [3.0, None, 7],
        "ultima_actualizacion": ["2025-03-01 22:00:00", "2025-03-02 23:10:00", None],
        "otra_columna": [1, 2, 3],
    })


def test_tipos_y_nulos():
    filas = list(ingesta.filas_para_copy(_lote()))
    assert len(filas) == 3 and all(len(f) == 6 for f in filas)
    ruta, fecha, hora, pasajeros, salidas, ua = filas[0]
    assert (ruta, fecha, hora, pasajeros, salidas) == ("CRA 54", date(2025, 3, 1), 5, 12.5, 3)
    assert type(hora) is int and type(salidas) is int
    assert ua == datetime(2025, 3, 1, 22, 0, tzinfo=BOGOTA)  # sin zona = America/Bogota (UTC-5)
    assert filas[1][3] is None and filas[1][4] is None  # NaN/None -> NULL en COPY
    assert filas[2][1] == date(2025, 3, 3) and filas[2][2] == 23 and filas[2][5] is None


def test_marcas_con_zona_se_respetan():
    lote = _lote().iloc[:1].copy()
    lote["ultima_actualizacion"] = pd.to_datetime(["2025-03-01T03:00:00Z"])
    (fila,) = ingesta.filas_para_copy(lote)
    assert fila[5] == datetime(2025, 3, 1, 3, 0, tzinfo=UTC)


def test_csv_para_copy_con_nulos_y_zona():
    lote = _lote()
    lote.loc[0, "ruta"] = 'CRA "54", norte'  # comillas y coma: el CSV las protege
    (bloque,) = list(ingesta.bloques_csv(lote))
    lineas = bloque.splitlines()

    def dias(d):
        return (d - date(1970, 1, 1)).days

    def us(dt):
        return int(dt.timestamp()) * 1_000_000

    ua0 = us(datetime(2025, 3, 1, 22, 0, tzinfo=BOGOTA))  # sin zona = America/Bogota (UTC-5)
    assert lineas[0] == f'"CRA ""54"", norte",{dias(date(2025, 3, 1))},5,12.5,3,{ua0}'
    ua1 = us(datetime(2025, 3, 2, 23, 10, tzinfo=BOGOTA))
    assert lineas[1] == f"CL 72,{dias(date(2025, 3, 2))},6,,,{ua1}"  # NaN/None -> campo vacío = NULL
    assert lineas[2] == f"CL 84,{dias(date(2025, 3, 3))},23,0.0,7,"
    assert len(list(ingesta.bloques_csv(pd.concat([_lote()] * 5, ignore_index=True), tam=4))) == 4


def test_dimensiones_por_ruta_y_fecha_del_lote(monkeypatch):
    """§8.3: una fila de la tabla de paso por cada (ruta, fecha) distinta, con lo que resuelve dimensiones.py; si el
    catálogo falla, la lista sale vacía y la carga sigue (las columnas quedan nulas)."""
    from app.servicios import dimensiones

    pedidas = []

    def falsa(ruta, dia, **k):
        pedidas.append((ruta, dia))
        return {"idruta": 16 if ruta == "CRA 54" else 21, "idempresa": None, "idproceso": "sobusa",
                "id_dia_semana": dia.isoweekday(), "id_estacionalidad": None}

    monkeypatch.setattr(dimensiones, "dimensiones", falsa)
    lote = pd.concat([_lote().iloc[:2]] * 3, ignore_index=True)       # 6 filas, 2 pares (ruta, fecha)
    filas = ingesta.dimensiones_del_lote(lote)
    dias = (date(2025, 3, 1) - date(1970, 1, 1)).days
    assert filas == [("CRA 54", dias, 16, None, "sobusa", None), ("CL 72", dias + 1, 21, None, "sobusa", None)]
    assert len(pedidas) == 2

    def rota(*a, **k):
        raise RuntimeError("catálogo caído")

    monkeypatch.setattr(dimensiones, "dimensiones", rota)
    assert ingesta.dimensiones_del_lote(lote) == []


def test_lote_vacio_no_toca_la_base():
    assert ingesta.incorporar(None, None, None)["filas"] == 0
    assert ingesta.incorporar(None, pd.DataFrame(columns=list(ingesta.COLUMNAS)), None)["insertadas"] == 0


def test_volumen_conversion_rapida():
    n = 120_000
    lote = pd.DataFrame({"ruta": ["CRA 54"] * n, "fecha": pd.date_range("2000-01-01", periods=n, freq="h").date,
                         "hora": np.arange(n) % 24, "pasajeros": np.random.default_rng(1).random(n) * 100,
                         "salidas": np.arange(n) % 9, "ultima_actualizacion": pd.Timestamp("2025-01-01 00:00")})
    import time

    t0 = time.perf_counter()
    filas = sum(1 for _ in ingesta.filas_para_copy(lote))
    assert filas == n and time.perf_counter() - t0 < 10
