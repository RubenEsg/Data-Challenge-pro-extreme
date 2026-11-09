"""Integración (§6.3, §7.3 paso 3, §14.2 «errores de datos consultables por lote, con causa y fila»; RF-004):
una ejecución con un lote malo a propósito y la consulta de sus errores por la API.

El lote es un tramo real del histórico empaquetado (CRA 54, CL 72 y SILENCIO, 10 a 12-06-2024) con siete defectos
inyectados, uno por regla. La fuente de la prueba no mueve la marca de agua y al final se borra lo que guardó la
ejecución, para no alterar a las demás pruebas de la sesión. La prueba comprueba que
GET /api/v1/frequency/executions/{id}/errors devuelve, para cada defecto, el lote, la fila, la llave del registro
(ruta, fecha, hora), el campo, el valor, el código, la dimensión, la causa y si bloquea la fila; que las filas
bloqueadas no llegan al histórico y que las demás sí.

Evidencia: docs/evidencias/datos/errores_lote.txt (se regenera con GENERAR_EVIDENCIAS=1).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.modelos_db import DemandaObservada, ErrorCalidad
from tests.evidencia import guardar_evidencia

HASTA = "2024-06-12"
DIA = date(2024, 6, 12)
EJECUCIONES: list = []


class FuenteLoteMalo:
    """Entrega siempre el mismo lote y devuelve la marca de agua recibida (no la mueve)."""

    def __init__(self, df):
        self.df = df

    def leer_incremental(self, marca_agua=None, hasta=None):
        return self.df.copy(), marca_agua


def _limpiar(sesion, ids: list) -> None:
    from sqlalchemy import delete

    from app.modelos_db import Alerta, Ejecucion, Prediccion, Recomendacion

    sesion.rollback()
    for modelo in (DemandaObservada, Alerta, Recomendacion, Prediccion, ErrorCalidad, Ejecucion):
        sesion.execute(delete(modelo).where(modelo.execution_id.in_(ids)))
    sesion.commit()
    ids.clear()


def _fila(tramo: pd.DataFrame, ruta: str, hora: int) -> int:
    i = tramo.index[(tramo["ruta"] == ruta) & (tramo["fecha"] == DIA) & (tramo["hora"] == hora)]
    assert len(i) == 1
    return int(i[0])


@pytest.fixture
def lote_malo(monkeypatch, sesion):
    """Tramo real con defectos: vacío, negativo, hora imposible, ruta inexistente, duplicado, pasajeros sin salidas y
    marca en el futuro (esta última no bloquea)."""
    from app.servicios import datos, ejecucion

    tramo = datos.demanda_horaria(desde=date(2024, 6, 10), hasta=DIA).reset_index(drop=True)
    tramo["pasajeros"] = tramo["pasajeros"].astype("float64")
    defectos = {}
    i = _fila(tramo, "CRA 54", 7)
    tramo.loc[i, "pasajeros"] = None
    defectos["COMP-001"] = ("CRA 54", 7)
    i = _fila(tramo, "CRA 54", 8)
    tramo.loc[i, "pasajeros"] = -5
    defectos["VAL-001"] = ("CRA 54", 8)
    i = _fila(tramo, "CL 72", 9)
    tramo.loc[i, "hora"] = 25
    defectos["VAL-002"] = ("CL 72", 25)
    i = _fila(tramo, "CL 72", 10)
    tramo.loc[i, "ruta"] = "RUTA FANTASMA"
    defectos["REL-001"] = ("RUTA FANTASMA", 10)
    i = _fila(tramo, "SILENCIO", 11)
    tramo.loc[i, "salidas"] = 0
    defectos["CONS-002"] = ("SILENCIO", 11)
    i = _fila(tramo, "SILENCIO", 12)
    tramo.loc[i, "ultima_actualizacion"] = pd.Timestamp("2099-01-01 00:00", tz="America/Bogota")
    defectos["OPOR-002"] = ("SILENCIO", 12)
    duplicada = tramo.loc[[_fila(tramo, "SILENCIO", 13)]]
    tramo = pd.concat([tramo, duplicada], ignore_index=True)
    defectos["UNI-001"] = ("SILENCIO", 13)
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: FuenteLoteMalo(tramo))
    try:
        yield defectos
    finally:
        _limpiar(sesion, EJECUCIONES)


def test_errores_del_lote_por_api_con_lote_fila_llave_campo_valor_codigo_y_causa(cliente, lote_malo, sesion):
    from app.esquemas import ErrorCalidadSalida

    r = cliente.post("/api/v1/frequency/executions", json={"hasta": HASTA})
    assert r.status_code == 202, r.text
    eid = r.json()["execution_id"]
    EJECUCIONES.append(eid)
    detalle = cliente.get(f"/api/v1/frequency/executions/{eid}").json()
    assert detalle["estado"] == "ok", detalle.get("mensaje")

    pagina = cliente.get(f"/api/v1/frequency/executions/{eid}/errors", params={"limite": 200})
    assert pagina.status_code == 200, pagina.text
    items = pagina.json()["items"]
    por_codigo: dict[str, list[dict]] = {}
    for e in items:
        por_codigo.setdefault(e["codigo"], []).append(e)
    assert set(lote_malo) <= set(por_codigo), sorted(por_codigo)

    # la API expone la llave, el valor y si bloquea (migración 0006); si el esquema de salida aún no los trae, se leen
    # de la tabla data_quality_error, que los guarda
    en_api = {"llave", "valor", "bloqueante"} <= set(ErrorCalidadSalida.model_fields)
    filas_db = {e.id: e for e in sesion.scalars(select(ErrorCalidad).where(ErrorCalidad.execution_id == eid))}
    lineas = [f"Ejecución {eid} · lote {items[0]['lote']} · {len(items)} errores devueltos por "
              f"GET /api/v1/frequency/executions/{{id}}/errors",
              "codigo | dimension | lote | fila | llave | campo | valor | bloqueante | causa"]
    for codigo, (ruta, hora) in sorted(lote_malo.items()):
        for e in por_codigo[codigo]:
            extra = e if en_api else {"llave": filas_db[e["id"]].llave, "valor": filas_db[e["id"]].valor,
                                      "bloqueante": filas_db[e["id"]].bloqueante}
            assert e["lote"] and e["fila"] is not None and e["campo"] and e["dimension"] and e["detalle"]
            assert extra["llave"]["ruta"] == ruta and extra["llave"]["hora"] == hora, (codigo, extra)
            assert extra["llave"]["fecha"] == DIA.isoformat()
            assert extra["bloqueante"] is (not codigo.startswith("OPOR")), codigo
            lineas.append(" | ".join(str(x) for x in (codigo, e["dimension"], e["lote"], e["fila"], extra["llave"],
                                                         e["campo"], extra["valor"], extra["bloqueante"],
                                                         e["detalle"])))
    assert len(por_codigo["UNI-001"]) == 2                     # las dos filas del grupo duplicado, sin elegir una
    assert sorted(por_codigo) == sorted(lote_malo) and len(items) == 8       # nada más: ni duplicados ni ruido
    assert "OPOR-001" not in por_codigo                         # la marca futura no se cuenta además como tardía
    nulo = por_codigo["COMP-001"][0]
    assert (nulo if en_api else {"valor": filas_db[nulo["id"]].valor})["valor"] is None
    negativo = por_codigo["VAL-001"][0]
    assert (negativo if en_api else {"valor": filas_db[negativo["id"]].valor})["valor"] == "-5"

    filtrado = cliente.get(f"/api/v1/frequency/executions/{eid}/errors", params={"codigo": "UNI-001"}).json()
    assert filtrado["total"] == 2 and {e["codigo"] for e in filtrado["items"]} == {"UNI-001"}

    # lo bloqueado no entra al histórico; la fila con marca futura (no bloqueante) sí
    def en_historico(ruta, hora):
        return sesion.scalar(select(func.count()).select_from(DemandaObservada).where(
            DemandaObservada.ruta == ruta, DemandaObservada.fecha == DIA, DemandaObservada.hora == hora))

    assert en_historico("CRA 54", 7) == 0 and en_historico("CRA 54", 8) == 0 and en_historico("SILENCIO", 13) == 0
    assert en_historico("SILENCIO", 12) == 1 and en_historico("CRA 54", 9) == 1
    lineas.append("")
    lineas.append(f"Bloqueadas fuera del histórico: CRA 54 7 h y 8 h, SILENCIO 13 h (×2), CL 72 hora 25, RUTA FANTASMA "
                  f"10 h y SILENCIO 11 h; la fila con marca futura (OPOR-002, no bloqueante) sí entró. "
                  f"Errores por dimensión: {detalle['errores_por_dimension']}.")
    guardar_evidencia("datos/errores_lote.txt", "\n".join(lineas) + "\n")
