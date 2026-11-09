"""Integración de la ingesta con COPY (RNF-003, §14.2): idempotencia, recarga con cambios, transacción y volumen.

Usa rutas sintéticas («PRUEBA-COPY-…») para no chocar con las claves de las demás pruebas.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

E = "ai_frecuencias"
BOGOTA = timezone(timedelta(hours=-5))


def _lote(ruta: str, dias: int = 3) -> pd.DataFrame:
    filas = []
    for d in range(dias):
        for h in range(5, 23):
            filas.append({"ruta": ruta, "fecha": date(2024, 1, 1) + timedelta(days=d), "hora": h,
                          "pasajeros": float(10 * h + d), "salidas": h % 7,
                          "ultima_actualizacion": datetime(2024, 1, 1, 23, tzinfo=BOGOTA) + timedelta(days=d)})
    return pd.DataFrame(filas)


def _contar(sesion, ruta: str) -> int:
    return sesion.execute(text(f"SELECT count(*) FROM {E}.demanda_observada WHERE ruta = :r"), {"r": ruta}).scalar()


def test_recarga_identica_no_modifica_filas(migrada, sesion):
    from app.servicios import ingesta

    ruta = f"PRUEBA-COPY-{uuid.uuid4().hex[:6]}"
    lote = _lote(ruta)
    r1 = ingesta.incorporar(sesion, lote, None)
    sesion.commit()
    r2 = ingesta.incorporar(sesion, lote, None)
    sesion.commit()
    assert r1["insertadas"] == len(lote) and r1["actualizadas"] == 0
    assert r2["insertadas"] == 0 and r2["actualizadas"] == 0 and r2["sin_cambio"] == len(lote)
    assert _contar(sesion, ruta) == len(lote)


def test_recarga_con_cambios_actualiza(migrada, sesion):
    from app.servicios import ejecucion, ingesta

    ruta = f"PRUEBA-COPY-{uuid.uuid4().hex[:6]}"
    lote = _lote(ruta)
    ingesta.incorporar(sesion, lote, None)
    sesion.commit()
    e = ejecucion.crear_ejecucion(sesion, "frecuencia", {"prueba": "ingesta"}, None)
    cambiado = lote.copy()
    cambiado.loc[:4, "pasajeros"] += 1  # 5 filas con valores nuevos
    nuevas = _lote(ruta, dias=4).iloc[len(lote):]  # y un día más
    r = ingesta.incorporar(sesion, pd.concat([cambiado, nuevas], ignore_index=True), e.execution_id)
    sesion.commit()
    assert (r["insertadas"], r["actualizadas"], r["sin_cambio"]) == (len(nuevas), 5, len(lote) - 5)
    n_ejec = sesion.execute(text(f"SELECT count(*) FROM {E}.demanda_observada WHERE ruta = :r AND execution_id = :e"),
                            {"r": ruta, "e": e.execution_id}).scalar()
    assert n_ejec == len(nuevas) + 5  # solo las filas tocadas quedan ligadas a la nueva ejecución
    sesion.execute(text(f"UPDATE {E}.execution_log SET estado = 'error' WHERE execution_id = :e"),
                   {"e": e.execution_id})
    sesion.commit()


def test_lote_con_clave_repetida_gana_la_mas_reciente(migrada, sesion):
    from app.servicios import ingesta

    ruta = f"PRUEBA-COPY-{uuid.uuid4().hex[:6]}"
    lote = _lote(ruta, dias=1).iloc[:2]
    viejo = lote.iloc[[0]].assign(pasajeros=1.0, ultima_actualizacion=datetime(2023, 1, 1, tzinfo=BOGOTA))
    r = ingesta.incorporar(sesion, pd.concat([viejo, lote], ignore_index=True), None)
    sesion.commit()
    assert r["insertadas"] == 2
    valor = sesion.execute(text(f"SELECT pasajeros FROM {E}.demanda_observada WHERE ruta = :r AND hora = 5"),
                           {"r": ruta}).scalar()
    assert valor == lote.iloc[0]["pasajeros"]


def test_ingesta_va_en_la_transaccion_de_la_ejecucion(migrada, sesion):
    from app.servicios import ingesta

    ruta = f"PRUEBA-COPY-{uuid.uuid4().hex[:6]}"
    ingesta.incorporar(sesion, _lote(ruta), None)
    sesion.rollback()  # el intento falló: no queda medio lote
    assert _contar(sesion, ruta) == 0
    ingesta.incorporar(sesion, _lote(ruta), None)  # dos cargas en la misma transacción (tabla de paso recreada)
    ingesta.incorporar(sesion, _lote(ruta), None)
    sesion.commit()
    assert _contar(sesion, ruta) == len(_lote(ruta))


def test_volumen_100k_filas_rapido(migrada, sesion):
    from app.servicios import ingesta

    n = 100_800
    ruta = np.array([f"PRUEBA-VOL-{i % 7}" for i in range(n)])
    lote = pd.DataFrame({"ruta": ruta, "fecha": [date(2000, 1, 1) + timedelta(days=(i // 7) // 18) for i in range(n)],
                         "hora": [5 + (i // 7) % 18 for i in range(n)], "pasajeros": np.arange(n) % 300 * 1.0,
                         "salidas": np.arange(n) % 9, "ultima_actualizacion": datetime(2024, 6, 1, tzinfo=BOGOTA)})
    t0 = time.perf_counter()
    r = ingesta.incorporar(sesion, lote, None)
    dur = time.perf_counter() - t0
    sesion.rollback()  # no deja las 100.800 filas en la base de pruebas
    assert r["insertadas"] == n and dur < 30, (r, dur)
