"""Ocupación actual por segmento en la réplica (§10.1, §11.2, §11.3; hallazgo H9; app/servicios/ocupacion.py).

- La lectura del ciclo (fuentes.FuentePostgresSoloLectura.leer_carga_segmentos) corre como lector_ia en una
  transacción READ ONLY sobre timbradas_segmentos real (2023-01-01 a 2023-02-27) y entrega, viaje por viaje y segmento
  por segmento, las mismas subidas y bajadas que las exportaciones; la ocupación que se calcula con ellas es la misma.
- Un viaje que llega por el trigger de Extreme (tg_timbrada_segmento) se mide con la misma consulta: se inserta como
  extreme_dba en UNA transacción que se revierte al final (con el candado de las simulaciones de la réplica), así que
  la réplica no cambia. Como escribe (y el INSERT avanza las secuencias de la réplica compartida aunque se revierta),
  solo corre con REPLICA_PRUEBAS_ESCRITURA=1, la misma compuerta de tests/replica/test_llegada.py.
Solo lectura salvo esa transacción revertida; nunca la base compartida del reto.
"""
from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts import replica_comun as rc

psycopg = pytest.importorskip("psycopg")

DIA = date(2023, 2, 8)            # el 07/02 de las rutas 2 y 21 está reservado para simular llegadas (sin segmentos)
FRANJAS = [("SILENCIO", DIA, 7), ("CRA 54", DIA, 7), ("CL 72", DIA, 7), ("CRA 54", DIA, 17)]
ESCRITURA = os.environ.get("REPLICA_PRUEBAS_ESCRITURA") == "1"
requiere_escritura = pytest.mark.skipif(
    not ESCRITURA, reason="escribe en la réplica como extreme_dba (transacción revertida que avanza secuencias): "
                          "REPLICA_PRUEBAS_ESCRITURA=1")


def _url_sa(rol: str) -> str:
    url = rc.url_rol(rol)
    if not url:
        pytest.skip(f"falta la clave de {rol}")
    return url.replace("postgresql://", "postgresql+psycopg://")


def _exportaciones() -> Path:
    carpeta = Path(os.environ.get("REPLICA_DATOS_DIR") or rc.RAIZ.parents[1] / "datos")
    if not (carpeta / "timbradas_segmentos.parquet").exists():
        pytest.skip(f"sin las exportaciones en {carpeta} (REPLICA_DATOS_DIR)")
    return carpeta


def _por_viaje_y_segmento(d: pd.DataFrame) -> pd.DataFrame:
    return (d.groupby(["id_viaje", "nro_segmento"])[["subidas", "bajadas"]].sum().astype(int)
            .sort_index())


def test_la_lectura_del_ciclo_como_lector_ia_trae_lo_mismo_que_las_exportaciones(cargada):
    from app.servicios import ocupacion
    from app.servicios.fuentes import FuentePostgresSoloLectura

    origen = _exportaciones()
    f = FuentePostgresSoloLectura(url=_url_sa("lector_ia"))
    t0 = time.perf_counter()
    d = f.leer_carga_segmentos(FRANJAS)
    segundos = time.perf_counter() - t0
    f._engine().dispose()
    assert len(d) > 1000 and f.resumen_carga["truncada"] is False
    assert {(r, fe, h) for r, fe, h in d[["ruta", "fecha", "hora"]].drop_duplicates().itertuples(index=False)} == \
        set(FRANJAS)
    assert d["conductor"].isna().all() or d["conductor"].dropna().str.startswith("cnd_").all()   # §18
    ts = pd.read_parquet(origen / "timbradas_segmentos.parquet", columns=["id_segmento", "id_viaje", "subidas",
                                                                          "bajadas"])
    rs = pd.read_parquet(origen / "rutas_segmentos.parquet", columns=["id", "nro_segmento"])
    exp = ts[ts["id_viaje"].isin(d["id_viaje"].unique())].merge(rs, left_on="id_segmento", right_on="id")
    assert _por_viaje_y_segmento(d).equals(_por_viaje_y_segmento(exp))
    # la misma ocupación por segmento con lo leído y con lo exportado
    caps = {r: 50.0 for r, _, _ in FRANJAS}
    leida = ocupacion.calcular_observada(d, caps)
    viajes = d.drop_duplicates("id_viaje")[["id_viaje", "ruta", "idruta", "fecha", "hora", "vehiculo", "conductor",
                                            "terminado"]]
    exportada = ocupacion.calcular_observada(exp.merge(viajes, on="id_viaje"), caps)
    columnas = ["ruta", "hora", "nro_segmento", "nro_viajes", "carga_media", "carga_max", "critico"]
    assert leida[columnas].reset_index(drop=True).equals(exportada[columnas].reset_index(drop=True))
    assert leida.groupby(["ruta", "hora"])["critico"].sum().eq(1).all()
    assert segundos < 30, f"la lectura de 4 franjas tardó {segundos:.1f} s"


@requiere_escritura
def test_un_viaje_que_llega_por_el_trigger_se_mide_en_una_transaccion_revertida(cargada, admin):
    """El camino completo de la ocupación actual sin confirmar nada: filas crudas de un viaje reservado (fuera de la
    carga) por el trigger de Extreme -> timbradas_segmentos -> la consulta de la lista blanca -> la carga por
    segmento. Σ subidas segmentadas = Σ subidas crudas (cada evento cae en un segmento) y, al revertir, la réplica
    queda igual."""
    from sqlalchemy import create_engine, text

    from app.servicios import fuentes, ocupacion
    from scripts import replica_simular_llegada as sim

    motor = create_engine(_url_sa("extreme_dba"), pool_size=1, max_overflow=0)
    with sim.candado(admin, espera_s=600), motor.connect() as conn:
        tx = conn.begin()
        try:
            viaje = sim.elegir_viajes(conn.connection.cursor(), 1)[0]
            crudas = sim.filas_muestra([viaje], 120)
            columnas = [c for c in sim.columnas_conteo(conn.connection.cursor()) if c in crudas.columns]
            valores = [{c: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for c, v in fila.items()}
                       for fila in crudas[columnas].to_dict("records")]
            conn.execute(text(f"INSERT INTO public.conteo_pasajeros ({', '.join(columnas)}) "  # noqa: S608
                              f"VALUES ({', '.join(':' + c for c in columnas)})"), valores)
            ruta, salida = conn.execute(text("SELECT r.nombre, pv.fechasalida FROM progvehiculos pv JOIN rutas r ON "
                                             "r.idruta = pv.idruta WHERE pv.idprogramacion = :v"), {"v": viaje}).one()
            params = {"rutas": [ruta], "fechas": [salida.date()], "horas": [salida.hour], "proceso": "sobusa",
                      "limite": 500_000}
            leidas = pd.DataFrame(conn.execute(text(fuentes._SQL_CARGA_SEGMENTOS), params).mappings().all())
        finally:
            tx.rollback()
    motor.dispose()
    del_viaje = leidas[leidas["id_viaje"] == viaje]
    assert len(del_viaje) > 0 and int(del_viaje["subidas"].sum()) == int(crudas["cantidad_subida"].sum())
    assert int(del_viaje["bajadas"].sum()) == int(crudas["cantidad_bajada"].sum())
    cargas = ocupacion.cargas_por_segmento(del_viaje)
    assert (cargas["carga"] >= 0).all() and cargas["nro_segmento"].is_monotonic_increasing
    tabla = ocupacion.calcular_observada(fuentes.seudonimizar_conductores(leidas), {ruta: 50.0})
    assert tabla["critico"].sum() == 1 and int(tabla["nro_viajes"].max()) >= 1
    with admin.cursor() as cur:                                      # revertido: la réplica no cambió
        cur.execute("SELECT count(*) FROM public.timbradas_segmentos WHERE id_viaje = %s", (viaje,))
        assert cur.fetchone()[0] == 0
