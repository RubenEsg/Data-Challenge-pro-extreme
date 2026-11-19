"""Integración de ALT-003 de pronóstico con su mínimo de probabilidad gobernado (§5.1, §5.2, RNF-005).

1. La migración 0014 versiona alt003_probabilidad_minima (versión PROPUESTA, sin aprobar), PUT /thresholds valida que
   sea una fracción y bajarla borra solo sus filas.
2. Con la ejecución partida por ruta, las reglas de alertas de la madre y de todos sus trabajos usan la versión de
   umbrales fijada al crearla, aunque un PUT /thresholds cambie alt003_probabilidad_minima a mitad.

Cada prueba deja la base como la encontró: borra sus ejecuciones y las versiones de threshold_config que creó con PUT
/thresholds, y vuelve vigente la de antes (las pruebas de bajada de las migraciones suponen que la versión vigente es
la de una migración).
"""
from __future__ import annotations

import importlib.util
import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from tests.integracion.conftest import restituir_umbrales
from tests.integracion.test_alertas_identificacion import _limpiar

E = "ai_frecuencias"


def _migracion_0014():
    from tests.integracion.conftest import RAIZ

    spec = importlib.util.spec_from_file_location(
        "m0014", RAIZ / "alembic" / "versions" / "0014_alt003_probabilidad_minima.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_migracion_0014_versiona_el_minimo_de_alt003_como_propuesta_y_baja(migrada, sesion, cliente):
    from app.modelos_db import Umbral
    from app.servicios.alertas import UMBRALES_POR_DEFECTO
    from tests.integracion.conftest import _alembic

    m = _migracion_0014()
    assert {n: v for n, v, _d in m.UMBRALES_0014} == {"alt003_probabilidad_minima":
                                                       UMBRALES_POR_DEFECTO["alt003_probabilidad_minima"]}

    def vigentes():
        sesion.expire_all()
        return {f.nombre: f for f in sesion.scalars(select(Umbral).where(Umbral.vigente))}

    def de_la_0014():
        return sesion.scalar(select(func.count()).select_from(Umbral).where(Umbral.creado_por == m.CREADO_POR))

    sesion.commit()
    try:
        _alembic("downgrade", m.down_revision)
        assert de_la_0014() == 0
        antes = vigentes()
        assert antes and len({f.version for f in antes.values()}) == 1
    finally:
        sesion.rollback()
        _alembic("upgrade", "head")
    despues = vigentes()
    fila = despues["alt003_probabilidad_minima"]
    # la 0016 (el tope VAL-009 del corto plazo) crea otra versión del conjunto completo encima de la de la 0014 y
    # conserva el valor que dejó la 0014
    assert fila.valor == 0.30 and fila.creado_por in (m.CREADO_POR, "migracion_0016") and fila.aprobado_por is None
    assert len({f.version for f in despues.values()}) == 1 and set(antes) <= set(despues)
    assert de_la_0014() == len(set(antes) | {"alt003_probabilidad_minima"})      # el conjunto completo, UNA versión
    api = cliente.get("/api/v1/thresholds").json()
    assert api["valores"]["alt003_probabilidad_minima"] == 0.30 and api["estado"] == "propuesta"
    malo = cliente.put("/api/v1/thresholds", json={"valores": {"alt003_probabilidad_minima": 0},
                                                   "motivo": "inválido"})
    assert malo.status_code == 422


@pytest.fixture
def fuente_partida(monkeypatch, sesion):
    """Fuente Parquet real (un tramo de marzo de 2025) con un proceso propio: las marcas por ruta empiezan de cero."""
    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 3, 1), hasta=date(2025, 3, 4))
    proceso = f"prueba-alt003-{uuid.uuid4().hex[:8]}"

    def obtener():
        f = fuentes.FuenteParquet(cargador=lambda: tramo.copy())
        f.proceso = proceso
        return f

    monkeypatch.setattr(ejecucion, "obtener_fuente", obtener)
    ids: list = []
    try:
        yield ids
    finally:
        _limpiar(sesion, ids)


def test_ejecucion_partida_usa_el_minimo_de_alt003_de_su_version(cliente, fuente_partida, monkeypatch, sesion):
    """RNF-005 con §5.1: las reglas de alertas de cada trabajo por ruta y de la madre reciben los umbrales de la
    versión fijada al crear la ejecución, aunque un PUT /thresholds cambie alt003_probabilidad_minima a mitad."""
    from app.servicios import alertas, cola, ejecucion

    vistos: list[tuple] = []
    originales = (alertas.evaluar_pronostico, alertas.evaluar_observadas)

    def espia_pronostico(contextos, umbrales=None):
        vistos.append(("pronostico", umbrales.get("version"), umbrales.get("alt003_probabilidad_minima")))
        return originales[0](contextos, umbrales)

    def espia_observadas(contexto, umbrales=None):
        vistos.append(("observadas", umbrales.get("version"), umbrales.get("alt003_probabilidad_minima")))
        return originales[1](contexto, umbrales)

    monkeypatch.setattr(alertas, "evaluar_pronostico", espia_pronostico)
    monkeypatch.setattr(alertas, "evaluar_observadas", espia_observadas)
    inicial = cliente.get("/api/v1/thresholds").json()["version"]
    try:
        fijada = cliente.put("/api/v1/thresholds", json={"valores": {"alt003_probabilidad_minima": 0.25},
                                                         "motivo": "prueba: versión fijada"}).json()["version"]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ejecucion, "ejecutar", lambda *a, **k: None)       # crear sin procesar
            r = cliente.post("/api/v1/frequency/executions", json={"hasta": "2025-03-03", "particion": "ruta"})
        assert r.status_code == 202, r.text
        creada = r.json()
        fuente_partida.append(uuid.UUID(creada["execution_id"]))
        trabajos = [t["execution_id"] for t in creada["trabajos"]]
        assert cola.procesar(uuid.UUID(trabajos[0])) == "ok"
        nueva = cliente.put("/api/v1/thresholds", json={"valores": {"alt003_probabilidad_minima": 0.45},
                                                        "motivo": "prueba: cambio a mitad"}).json()["version"]
        assert nueva > fijada
        for t in trabajos[1:]:
            assert cola.procesar(uuid.UUID(t)) == "ok"
        assert cola.procesar(uuid.UUID(creada["execution_id"])) == "ok"
        assert {"pronostico", "observadas"} <= {v[0] for v in vistos}
        assert {(v[1], v[2]) for v in vistos} == {(fijada, 0.25)}
    finally:
        restituir_umbrales(sesion, inicial)
    assert cliente.get("/api/v1/thresholds").json()["version"] == inicial
