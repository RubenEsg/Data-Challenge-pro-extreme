"""La política de aprendizaje no encola un reentrenamiento cuyo corte no se puede entrenar (RF-018, §9.5), contra la
base LOCAL de pruebas.

El corte del reentrenamiento es el último dato menos 61 días. Al comienzo de la serie ese corte cae antes de los datos
y el entrenamiento falla siempre con «No hay datos suficientes para entrenar y validar con ese corte». La política lo
encolaba igual en cada ciclo con un motivo (deriva frente al modelo vigente): en la prueba de réplicas de 20 días
(scripts/prueba_replicas.py) eran 17 trabajos en error y uno pendiente. Ahora la política pregunta antes con la
partición del entrenamiento (inferencia.corte_sin_datos) y, si el corte no se puede entrenar, no lo encola y lo deja
en los bloqueos de su decisión, que queda en metricas.monitoreo.politica.reentreno de la ejecución.

Cada prueba corre politica.despues_del_ciclo (lo que hace el cierre de cada ciclo diario) dentro de una transacción
que se revierte: la base queda como estaba.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, update

from app.modelos_db import Ejecucion, MonitoreoModelo

SIN_DATOS = "No hay datos suficientes para entrenar y validar con ese corte"


def _entrenamientos_en_cola(s) -> int:
    return s.scalar(select(func.count()).select_from(Ejecucion).where(Ejecucion.tipo == "entrenamiento",
                                                                       Ejecucion.estado == "en_cola"))


@pytest.fixture
def degradado(sesion):
    """Una transacción que se revierte al terminar. Dentro de ella: el registro con su modelo activo, ningún retador
    en sombra ni entrenamiento pendiente (los que hayan dejado otras pruebas se neutralizan solo aquí) y las tres
    últimas filas de monitoreo del activo con el WAPE móvil sobre el umbral: hay motivo para reentrenar."""
    from app.servicios import ejecucion, politica

    s = sesion
    ejecucion.sembrar_registro(s)
    activo = ejecucion.modelo_activo(s)
    if activo is None:
        pytest.skip("el registro de modelos no tiene un modelo activo")
    try:
        s.execute(update(Ejecucion).where(Ejecucion.tipo == "entrenamiento",
                                          Ejecucion.estado.in_(("en_cola", "corriendo"))).values(estado="error"))
        for retador in politica.en_sombra(s):
            retador.metricas = {**retador.metricas, "sombra": {**retador.metricas["sombra"], "estado": "no_aplica"}}
        s.add_all([MonitoreoModelo(model_id=activo.model_id, rol="activo", ventana_dias=28, wape_movil=0.25,
                                   estado="alerta", psi={}, motivos=[], detalle={}) for _ in range(3)])
        s.flush()
        version, umbrales = ejecucion.umbrales_vigentes(s)
        yield s, umbrales, version
    finally:
        s.rollback()


def test_el_ciclo_no_encola_un_reentrenamiento_sin_datos_antes_del_corte_y_deja_el_motivo(degradado):
    """Datos hasta el 2023-01-20: el corte (2022-11-20) cae antes del comienzo de la serie (2023-01-01). El ciclo no
    encola el entrenamiento y la decisión lo dice en sus bloqueos. El trabajo que antes se encolaba habría fallado con
    ese mismo motivo: es la misma partición."""
    from app.servicios import inferencia, politica

    s, umbrales, version = degradado
    r = politica.despues_del_ciclo(s, uuid.uuid4(), {"hasta": "2023-01-20"}, umbrales, version)
    decision = r["reentreno"]
    assert any(m.startswith("degradación") for m in decision["motivos"]), decision
    assert decision["reentrenar"] is False and "entrenamiento_encolado" not in r
    assert (decision["hasta"], decision["datos_hasta"]) == ("2022-11-20", "2023-01-20")
    (bloqueo,) = decision["bloqueos"]
    assert bloqueo.startswith(f"{politica.OMITIDO_SIN_DATOS} 2022-11-20 (la serie validada hasta 2023-01-20 deja 0 "
                              "filas útiles para entrenar y "), bloqueo
    assert _entrenamientos_en_cola(s) == 0
    with pytest.raises(inferencia.CorteSinDatos, match=SIN_DATOS):
        politica.entrenar_candidato({"hasta": decision["hasta"], "datos_hasta": decision["datos_hasta"]})


def test_con_historico_suficiente_el_ciclo_encola_el_reentrenamiento_como_antes(degradado):
    """Datos hasta el 2025-09-20: el corte (2025-07-21) tiene años de serie antes y 61 días de validación después. La
    política decide lo mismo que antes y el ciclo encola el entrenamiento en su transacción, con el corte, el motivo
    y el origen."""
    from app.servicios import politica

    s, umbrales, version = degradado
    eid = uuid.uuid4()
    r = politica.despues_del_ciclo(s, eid, {"hasta": "2025-09-20"}, umbrales, version)
    decision = r["reentreno"]
    assert decision["reentrenar"] is True and decision["bloqueos"] == []
    assert (decision["hasta"], decision["datos_hasta"]) == ("2025-07-21", "2025-09-20")
    e = s.get(Ejecucion, r["entrenamiento_encolado"])
    assert (e.tipo, e.estado, e.correlation_id) == ("entrenamiento", "en_cola", f"politica-{eid}")
    assert (e.parametros["hasta"], e.parametros["datos_hasta"]) == ("2025-07-21", "2025-09-20")
    assert e.parametros["origen"] == "ciclo_diario" and e.parametros["solicitado_por"] == politica.USUARIO_POLITICA
    assert e.parametros["motivo"] == "; ".join(decision["motivos"]) and "degradación" in e.mensaje
    assert _entrenamientos_en_cola(s) == 1
