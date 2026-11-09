"""Unidad del planificador interno (APScheduler): franjas, decisión de reentrenar y arranque/parada limpios."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.servicios import planificador as p

Z = p.ZONA


def test_franja_cada_minuto():
    t = p.disparador("*/1 * * * *")
    assert p.franja_actual(t, datetime(2026, 3, 2, 10, 0, 30, tzinfo=Z)) == datetime(2026, 3, 2, 10, 0, tzinfo=Z)
    assert p.franja_actual(t, datetime(2026, 3, 2, 10, 1, 0, tzinfo=Z)) == datetime(2026, 3, 2, 10, 1, tzinfo=Z)


def test_franja_diaria_y_ventana():
    t = p.disparador("15 5 * * *")
    assert p.franja_actual(t, datetime(2026, 3, 2, 5, 20, tzinfo=Z)) == datetime(2026, 3, 2, 5, 15, tzinfo=Z)
    assert p.franja_actual(t, datetime(2026, 3, 2, 4, 0, tzinfo=Z)) is None  # la de ayer quedó fuera de la ventana
    assert p.franja_actual(t, datetime(2026, 3, 2, 4, 0, tzinfo=Z), ventana=timedelta(days=1)) == \
        datetime(2026, 3, 1, 5, 15, tzinfo=Z)


def test_dos_replicas_calculan_la_misma_franja():
    t = p.disparador("15 5 * * *")
    a = p.franja_actual(t, datetime(2026, 3, 2, 5, 15, 0, 120000, tzinfo=Z))
    b = p.franja_actual(t, datetime(2026, 3, 2, 5, 15, 7, tzinfo=Z))  # la otra réplica dispara 7 s después
    assert a == b == datetime(2026, 3, 2, 5, 15, tzinfo=Z)


def test_dia_de_la_semana_con_numeracion_estandar_de_cron():
    lunes = datetime(2026, 3, 2, 3, 0, tzinfo=Z)  # 2026-03-02 es lunes
    assert p.disparador("0 4 * * 1").get_next_fire_time(None, lunes) == datetime(2026, 3, 2, 4, 0, tzinfo=Z)
    assert p.disparador("0 4 * * 0").get_next_fire_time(None, lunes).weekday() == 6  # domingo
    assert p.disparador("0 4 * * 7").get_next_fire_time(None, lunes).weekday() == 6
    sabado = datetime(2026, 3, 7, 5, 0, tzinfo=Z)
    assert p.disparador("0 4 * * 1-5").get_next_fire_time(None, sabado) == datetime(2026, 3, 9, 4, 0, tzinfo=Z)
    assert p.disparador("*/10 * * * *").get_next_fire_time(None, lunes) == lunes


def test_cron_invalido():
    with pytest.raises(ValueError):
        p.disparador("cada día")


def test_tarea_diaria_encola_la_franja(monkeypatch):
    monkeypatch.setattr(p, "obtener_ajustes", lambda: SimpleNamespace(plan_ejecucion_cron="15 5 * * *"))
    llamadas = []
    monkeypatch.setattr(p, "encolar_franja", lambda tipo, franja, parametros, motivo: llamadas.append(
        (tipo, franja, parametros)) or "id-nuevo")
    assert p.tarea_ejecucion_diaria(datetime(2026, 3, 2, 5, 15, 3, tzinfo=Z)) == "id-nuevo"
    assert llamadas == [("frecuencia", datetime(2026, 3, 2, 5, 15, tzinfo=Z),
                         {"notificar": True, "origen": "planificador"})]


@pytest.mark.parametrize("decision, esperado", [
    ({"reentrenar": False, "motivos": [], "hasta": "2025-10-31"}, None),
    ({"reentrenar": True, "motivos": ["WAPE reciente 21.0% > wape_max 20.0%"], "hasta": "2025-10-31"}, "id-cand"),
])
def test_reentrenamiento_solo_si_hace_falta(monkeypatch, decision, esperado):
    monkeypatch.setattr(p, "obtener_ajustes", lambda: SimpleNamespace(plan_reentrenamiento_cron="0 4 * * 1"))
    monkeypatch.setattr(p, "evaluar_reentrenamiento", lambda: decision)
    llamadas = []
    monkeypatch.setattr(p, "encolar_franja", lambda tipo, franja, parametros, motivo: llamadas.append(
        (tipo, parametros)) or "id-cand")
    assert p.tarea_reentrenamiento(datetime(2026, 3, 2, 4, 0, 5, tzinfo=Z)) == esperado  # lunes 04:00
    if esperado:
        assert llamadas[0][0] == "entrenamiento" and llamadas[0][1]["hasta"] == "2025-10-31"
        assert llamadas[0][1]["solicitado_por"] == "planificador"
    else:
        assert llamadas == []


def test_deshabilitado_por_omision(monkeypatch):
    from app.config import Ajustes

    assert Ajustes.model_fields["planificador_habilitado"].default is False  # se activa por entorno
    monkeypatch.setattr(p, "obtener_ajustes", lambda: SimpleNamespace(planificador_habilitado=False))
    assert p.iniciar() is False


def test_arranca_y_apaga_limpio(monkeypatch):
    aj = SimpleNamespace(planificador_habilitado=True, plan_ejecucion_cron="*/1 * * * *",
                         plan_reentrenamiento_cron="0 4 * * 1")
    monkeypatch.setattr(p, "obtener_ajustes", lambda: aj)
    try:
        assert p.iniciar() is True and p.iniciar() is True  # idempotente
        trabajos = {j.id: j for j in p._planificador.get_jobs()}
        assert set(trabajos) == {"ejecucion_diaria", "reentrenamiento"}
        assert trabajos["ejecucion_diaria"].next_run_time is not None
    finally:
        p.detener()
    assert p._planificador is None
