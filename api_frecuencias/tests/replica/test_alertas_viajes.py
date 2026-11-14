"""§5.3 «viaje, conductor y vehículo»: la lectura de viajes de una ruta (fuentes.FuentePostgresSoloLectura.viajes)
contra la réplica cargada, como lector_ia y en SOLO LECTURA (ninguna de estas pruebas escribe).

- devuelve los viajes de progvehiculos de la ruta y el día, con el conductor solo seudonimizado (§18);
- es la misma realidad que lee el ciclo: en cada hora que entrega demanda_segmentos, los viajes válidos son sus salidas
  y la suma de sus numeropasajeros (válidos, <= 300) son sus pasajeros;
- el ciclo (ejecucion.viajes_del_dia) la usa tal cual para ALT-006 y ALT-009.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts import replica_comun as rc

Z = ZoneInfo("America/Bogota")
DIAS = (("CRA 54", date(2023, 2, 10)), ("SILENCIO", date(2023, 2, 14)))


def _fuente(tabla="demanda_segmentos"):
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = rc.url_rol("lector_ia")
    if not url:
        pytest.skip("falta LECTOR_IA_PASSWORD")
    return FuentePostgresSoloLectura(url=url.replace("postgresql://", "postgresql+psycopg://", 1), tabla=tabla,
                                     statement_timeout_ms=180000)


@pytest.fixture(scope="module")
def demanda(cargada):
    """La lectura del ciclo integrado (demanda_segmentos) de la réplica completa, una sola vez."""
    d, _ = _fuente().leer_incremental(None)
    return d


def _dia(fecha):
    inicio = datetime.combine(fecha, datetime.min.time(), tzinfo=Z)
    return inicio, inicio + timedelta(days=1)


@pytest.mark.parametrize("ruta,fecha", DIAS)
def test_viajes_de_la_replica_seudonimizados_y_coherentes_con_demanda_segmentos(cargada, demanda, monkeypatch,
                                                                               ruta, fecha):
    from app.servicios import alertas

    monkeypatch.setenv("SEUDONIMO_SECRETO", "secreto-de-la-prueba-de-replica")
    d = _fuente().viajes(ruta, *_dia(fecha))
    assert len(d) > 50 and "idconductor" not in d.columns
    assert {"viaje", "vehiculo", "conductor", "salida", "salida_real", "finalizado", "cancelada",
            "excedeplazosalida", "numeropasajeros", "filas_segmento"} <= set(d.columns)
    assert d["conductor"].map(lambda c: bool(alertas.PATRON_SEUDONIMO.match(c))).all()
    viajes = [alertas.viaje_de_fila(f) for f in d.to_dict("records")]
    assert all(v["salida"].date() == fecha for v in viajes)
    horas = demanda[(demanda["ruta"] == ruta) & (demanda["fecha"].astype(str) == str(fecha))]
    assert len(horas) >= 12
    for fila in horas.itertuples(index=False):
        de_la_hora = [v for v in viajes if v["salida"].hour == int(fila.hora)]
        validos = [v for v in de_la_hora if v["estado"] == "valido"]
        assert len(validos) == int(fila.salidas), (ruta, fecha, fila.hora)
        pasajeros = sum(v["pasajeros"] for v in validos if v["pasajeros"] is not None and v["pasajeros"] <= 300)
        assert pasajeros == pytest.approx(float(fila.pasajeros)), (ruta, fecha, fila.hora)
        assert any((v["filas_segmento"] or 0) > 0 for v in de_la_hora)     # la hora llegó: algún viaje segmentado


def test_el_ciclo_integrado_identifica_los_viajes_de_la_replica(cargada):
    from app.servicios import ejecucion

    fallos: list = []
    viajes = ejecucion.viajes_del_dia(_fuente(), "CL 72", date(2023, 2, 21), fallos)
    assert viajes and not fallos
    assert {v["estado"] for v in viajes} <= {"valido", "cancelado", "sin_finalizar"}
    assert all(v["filas_segmento"] is not None for v in viajes)          # la fuente del ciclo cuenta los segmentos
    sin_segmentar = [v for v in viajes if v["estado"] == "valido" and v["filas_segmento"] == 0]
    assert all(v["viaje"] and v["vehiculo"] for v in sin_segmentar)
