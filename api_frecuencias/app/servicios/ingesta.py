"""Ingesta rápida al histórico propio (RNF-003, §14.1 prueba de volumen, §14.2 carga repetida sin duplicar).

COPY a una tabla temporal y un solo INSERT … ON CONFLICT … DO UPDATE … WHERE … IS DISTINCT FROM, dentro de la MISMA
transacción de la ejecución: si el intento falla o la réplica muere, no queda medio lote. Una carga repetida con la
misma clave (ruta, fecha, hora) no duplica ni reescribe filas iguales (0 filas modificadas), y una recarga con
valores nuevos actualiza solo las filas que cambiaron.

Cada fila guarda además las dimensiones de §8.3 (idruta, idempresa, idproceso, id_dia_semana ISO e
id_estacionalidad): una tabla de paso pequeña trae, por cada (ruta, fecha) distinta del lote, lo que resuelve
app/servicios/dimensiones.py, y el día ISO se calcula en el servidor con la fecha.

Antes: insert().values() de SQLAlchemy en lotes de 5.000 filas. Ahora: COPY de un CSV numérico (pandas lo formatea en
C) + un solo upsert; 111.690 filas en unos 3-4 s en el portátil, 10-15 veces más rápido medido en las mismas
condiciones (docs/evidencias/cola/ingesta.txt, scripts/medir_ingesta.py).
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

log = logging.getLogger("api_frecuencias.ingesta")
ZONA = "America/Bogota"
COLUMNAS = ("ruta", "fecha", "hora", "pasajeros", "salidas", "ultima_actualizacion")
TABLA_PASO = "tmp_ingesta_demanda"
LOTE_COPY = 50_000

# La tabla de paso recibe solo números (días desde 1970 y microsegundos desde la época UTC): pandas los escribe en
# CSV sin trabajo por fila en Python y la conversión a DATE/TIMESTAMPTZ es exacta (aritmética entera en el servidor).
_CREAR_PASO = ("CREATE TEMP TABLE IF NOT EXISTS tmp_ingesta_demanda (ruta TEXT, dias INTEGER, hora INTEGER, "
               "pasajeros DOUBLE PRECISION, salidas INTEGER, ua_us BIGINT) ON COMMIT DROP")
COLUMNAS_PASO = ("ruta", "dias", "hora", "pasajeros", "salidas", "ua_us")
# dimensiones de §8.3 por (ruta, fecha) distinta del lote
_CREAR_DIM = ("CREATE TEMP TABLE IF NOT EXISTS tmp_ingesta_dim (ruta TEXT, dias INTEGER, idruta INTEGER, "
              "idempresa INTEGER, idproceso TEXT, id_estacionalidad INTEGER) ON COMMIT DROP")
_COPY_DIM = "COPY tmp_ingesta_dim (ruta, dias, idruta, idempresa, idproceso, id_estacionalidad) FROM STDIN"
_COPY = ("COPY tmp_ingesta_demanda (ruta, dias, hora, pasajeros, salidas, ua_us) FROM STDIN WITH (FORMAT csv)")
# DISTINCT ON: si el lote trae dos veces la misma clave gana la versión más reciente (ON CONFLICT no admite tocar
# dos veces la misma fila en una sentencia). El WHERE IS DISTINCT FROM evita reescribir filas idénticas.
_UPSERT = """
WITH paso AS (
    SELECT t.ruta, DATE '1970-01-01' + t.dias AS fecha, t.hora, t.pasajeros, t.salidas,
           TIMESTAMPTZ 'epoch' + t.ua_us * INTERVAL '1 microsecond' AS ultima_actualizacion,
           m.idruta, m.idempresa, m.idproceso, m.id_estacionalidad
      FROM tmp_ingesta_demanda t
      LEFT JOIN tmp_ingesta_dim m ON m.ruta = t.ruta AND m.dias = t.dias
), up AS (
    INSERT INTO ai_frecuencias.demanda_observada AS d
           (ruta, fecha, hora, pasajeros, salidas, ultima_actualizacion, execution_id,
            idruta, idempresa, idproceso, id_dia_semana, id_estacionalidad)
    SELECT DISTINCT ON (ruta, fecha, hora) ruta, fecha, hora, pasajeros, salidas, ultima_actualizacion,
           CAST(%(eid)s AS uuid), idruta, idempresa, idproceso, EXTRACT(ISODOW FROM fecha)::integer,
           id_estacionalidad
      FROM paso
     ORDER BY ruta, fecha, hora, ultima_actualizacion DESC NULLS LAST
    ON CONFLICT ON CONSTRAINT ux_demanda_observada_clave DO UPDATE
       SET pasajeros = EXCLUDED.pasajeros, salidas = EXCLUDED.salidas,
           ultima_actualizacion = EXCLUDED.ultima_actualizacion, execution_id = EXCLUDED.execution_id,
           idruta = EXCLUDED.idruta, idempresa = EXCLUDED.idempresa, idproceso = EXCLUDED.idproceso,
           id_dia_semana = EXCLUDED.id_dia_semana, id_estacionalidad = EXCLUDED.id_estacionalidad,
           cargado_en = now()
     WHERE (d.pasajeros, d.salidas, d.ultima_actualizacion)
           IS DISTINCT FROM (EXCLUDED.pasajeros, EXCLUDED.salidas, EXCLUDED.ultima_actualizacion)
    RETURNING (xmax = 0) AS insertada
)
SELECT count(*) FILTER (WHERE insertada), count(*) FILTER (WHERE NOT insertada) FROM up
"""


def _sin_nulos(serie: pd.Series) -> list[Any]:
    """Serie -> lista de objetos Python con None en lugar de NaN/NaT (COPY escribe NULL)."""
    return serie.astype(object).where(serie.notna(), None).tolist()


def normalizar(validos: pd.DataFrame) -> pd.DataFrame:
    """Tipos del histórico, vectorizado con pandas (no fila a fila): fecha sin hora, hora entera, pasajeros float,
    salidas entero con nulos y marcas de tiempo con zona (sin zona = America/Bogota, UTC-5 sin horario de verano,
    igual que ejecucion.a_instante())."""
    d = validos.loc[:, list(COLUMNAS)]
    ua = pd.to_datetime(d["ultima_actualizacion"])
    if getattr(ua.dt, "tz", None) is None:
        ua = ua.dt.tz_localize(ZONA)
    return pd.DataFrame({
        "ruta": d["ruta"].astype(str),
        "fecha": pd.to_datetime(d["fecha"]).dt.normalize(),
        "hora": pd.to_numeric(d["hora"]).astype("int64"),
        "pasajeros": pd.to_numeric(d["pasajeros"], errors="coerce").astype("float64"),
        "salidas": pd.to_numeric(d["salidas"], errors="coerce").round().astype("Int64"),
        "ultima_actualizacion": ua,
    })


def filas_para_copy(validos: pd.DataFrame) -> Iterator[tuple]:
    """El lote validado como tuplas (ruta, fecha, hora, pasajeros, salidas, ultima_actualizacion) de Python."""
    n = normalizar(validos)
    marcas = [None if pd.isna(x) else x.to_pydatetime() for x in n["ultima_actualizacion"]]
    salidas = [None if s is None else int(s) for s in _sin_nulos(n["salidas"])]
    yield from zip(n["ruta"].tolist(), n["fecha"].dt.date.tolist(), n["hora"].tolist(), _sin_nulos(n["pasajeros"]),
                   salidas, marcas, strict=True)


def bloques_csv(validos: pd.DataFrame, tam: int = LOTE_COPY) -> Iterator[str]:
    """El lote en CSV por bloques para COPY … FORMAT csv, con las columnas de la tabla de paso (ruta, días desde
    1970, hora, pasajeros, salidas, microsegundos UTC). Todo numérico salvo la ruta: pandas lo formatea en C, sin
    trabajo por fila en Python. Los nulos van como campo vacío sin comillas, que COPY lee como NULL."""
    n = normalizar(validos)
    ua = n["ultima_actualizacion"]
    microsegundos = ua.dt.tz_convert("UTC").dt.tz_localize(None).values.astype("datetime64[us]").astype("int64")
    paso = pd.DataFrame({
        "ruta": n["ruta"],
        "dias": n["fecha"].values.astype("datetime64[D]").astype("int64"),
        "hora": n["hora"],
        "pasajeros": n["pasajeros"],
        "salidas": n["salidas"],
        "ua_us": pd.array(microsegundos, dtype="Int64"),
    }, index=n.index)
    paso.loc[ua.isna().values, "ua_us"] = pd.NA
    for i in range(0, len(paso), tam):
        yield paso.iloc[i:i + tam].to_csv(index=False, header=False, na_rep="", lineterminator="\n")


def dimensiones_del_lote(validos: pd.DataFrame) -> list[tuple]:
    """(ruta, días desde 1970, idruta, idempresa, idproceso, id_estacionalidad) por cada (ruta, fecha) distinta.
    Si el catálogo no responde, la lista sale vacía y las columnas quedan nulas (la carga no se detiene)."""
    from datetime import date

    from app.servicios import dimensiones

    try:
        n = normalizar(validos)
        pares = n[["ruta", "fecha"]].drop_duplicates()
        salida = []
        for ruta, fecha in pares.itertuples(index=False):
            dia = fecha.date()
            d = dimensiones.dimensiones(ruta, dia)
            salida.append((ruta, (dia - date(1970, 1, 1)).days, d["idruta"], d["idempresa"], d["idproceso"],
                           d["id_estacionalidad"]))
        return salida
    except Exception as exc:  # noqa: BLE001 - sin dimensiones la carga sigue, con las columnas nulas
        log.warning("dimensiones del lote no disponibles: %s", exc)
        return []


def _conexion_psycopg(s: Session):
    """La conexión psycopg de la transacción en curso de la sesión (COPY va en la misma transacción)."""
    s.flush()
    cruda = s.connection().connection.driver_connection
    return cruda if type(cruda).__module__.split(".")[0] == "psycopg" else None


def incorporar(s: Session, validos: pd.DataFrame | None, execution_id: uuid.UUID | None) -> dict[str, Any]:
    """Upsert del lote validado en demanda_observada con COPY, dentro de la transacción de la sesión `s`.

    Devuelve filas del lote, insertadas, actualizadas, sin cambio y los tiempos de COPY y del upsert.
    """
    if validos is None or not len(validos):
        return {"filas": 0, "insertadas": 0, "actualizadas": 0, "sin_cambio": 0, "copy_s": 0.0, "upsert_s": 0.0}
    t0 = time.perf_counter()
    con = _conexion_psycopg(s)
    if con is None:  # pragma: no cover - otro driver: camino lento de respaldo
        return _incorporar_por_lotes(s, validos, execution_id)
    with con.cursor() as cur:
        cur.execute(_CREAR_PASO)
        cur.execute("TRUNCATE tmp_ingesta_demanda")
        with cur.copy(_COPY) as cp:
            for bloque in bloques_csv(validos):
                cp.write(bloque)
        cur.execute(_CREAR_DIM)
        cur.execute("TRUNCATE tmp_ingesta_dim")
        with cur.copy(_COPY_DIM) as cp:
            for fila in dimensiones_del_lote(validos):
                cp.write_row(fila)
        n = len(validos)
        t1 = time.perf_counter()
        cur.execute(_UPSERT, {"eid": str(execution_id) if execution_id else None})
        insertadas, actualizadas = cur.fetchone()
        cur.execute("DROP TABLE IF EXISTS tmp_ingesta_demanda")
        cur.execute("DROP TABLE IF EXISTS tmp_ingesta_dim")
    t2 = time.perf_counter()
    resultado = {"filas": n, "insertadas": int(insertadas), "actualizadas": int(actualizadas),
                 "sin_cambio": n - int(insertadas) - int(actualizadas), "copy_s": round(t1 - t0, 3),
                 "upsert_s": round(t2 - t1, 3)}
    log.info("Ingesta COPY: %s", resultado)
    return resultado


def _incorporar_por_lotes(s: Session, validos: pd.DataFrame, execution_id: uuid.UUID | None) -> dict[str, Any]:
    """Respaldo para drivers sin COPY: upsert por lotes con SQLAlchemy (lento, mismo resultado)."""
    from datetime import date

    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.modelos_db import DemandaObservada

    t0 = time.perf_counter()
    dims = {(r, dias): (idruta, idempresa, idproceso, est)
            for r, dias, idruta, idempresa, idproceso, est in dimensiones_del_lote(validos)}
    filas = []
    for f in filas_para_copy(validos):
        fila = dict(zip(COLUMNAS, f, strict=True), execution_id=execution_id)
        idruta, idempresa, idproceso, est = dims.get((fila["ruta"], (fila["fecha"] - date(1970, 1, 1)).days),
                                                     (None, None, None, None))
        fila.update(idruta=idruta, idempresa=idempresa, idproceso=idproceso,
                    id_dia_semana=fila["fecha"].isoweekday(), id_estacionalidad=est)
        filas.append(fila)
    for i in range(0, len(filas), 5000):
        stmt = pg_insert(DemandaObservada).values(filas[i:i + 5000])
        stmt = stmt.on_conflict_do_update(
            constraint="ux_demanda_observada_clave",
            set_={"pasajeros": stmt.excluded.pasajeros, "salidas": stmt.excluded.salidas,
                  "ultima_actualizacion": stmt.excluded.ultima_actualizacion,
                  "execution_id": stmt.excluded.execution_id, "idruta": stmt.excluded.idruta,
                  "idempresa": stmt.excluded.idempresa, "idproceso": stmt.excluded.idproceso,
                  "id_dia_semana": stmt.excluded.id_dia_semana,
                  "id_estacionalidad": stmt.excluded.id_estacionalidad, "cargado_en": func.now()})
        s.execute(stmt)
    return {"filas": len(filas), "insertadas": None, "actualizadas": None, "sin_cambio": None,
            "copy_s": 0.0, "upsert_s": round(time.perf_counter() - t0, 3)}
