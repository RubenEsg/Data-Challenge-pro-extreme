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


def _intradia(monkeypatch, cron="5 6-20 * * *", diaria="15 5 * * *", rutas=None):
    """La tarea intradía con estos crons; devuelve las llamadas a encolar_franja (tipo, franja, parámetros, motivo,
    rutas)."""
    monkeypatch.setattr(p, "obtener_ajustes", lambda: SimpleNamespace(plan_intradia_cron=cron, fuente="postgres",
                                                                      plan_ejecucion_cron=diaria))
    monkeypatch.setattr(p, "rutas_de_la_particion", lambda: rutas)
    llamadas = []
    monkeypatch.setattr(p, "encolar_franja", lambda tipo, franja, parametros, motivo, rutas=None: llamadas.append(
        (tipo, franja, parametros, motivo, rutas)) or "id-intradia")
    return llamadas


def test_tarea_intradia_encola_la_franja_con_su_instante(monkeypatch):
    """§10.1: la franja del cron intradía se encola como una ejecución de frecuencia con instante = la franja (así el
    plan es el del día en curso y la restricción reactiva por ocupación actual actúa) y parametros.intradia."""
    llamadas = _intradia(monkeypatch)
    assert p.tarea_ciclo_intradia(datetime(2026, 3, 2, 7, 5, 9, tzinfo=Z)) == "id-intradia"
    ((tipo, franja, parametros, motivo, rutas),) = llamadas
    assert tipo == "frecuencia" and franja == datetime(2026, 3, 2, 7, 5, tzinfo=Z) and rutas is None
    assert parametros == {"notificar": True, "origen": p.ORIGEN_INTRADIA, "intradia": True,
                          "instante": "2026-03-02T07:05:00-05:00"}
    assert "intradía" in motivo and p._ultimas["frecuencia_intradia"]["execution_id"] == "id-intradia"


def test_el_log_de_una_franja_dice_si_la_encolo_esta_replica_u_otra(monkeypatch, caplog):
    """El mismo texto para las tres tareas que encolan franjas (diaria, intradía y las demás programadas): la
    ejecución que encoló esta réplica o, si la franja ya estaba, que la encoló otra réplica (p.YA_ENCOLADA)."""
    assert p.como_quedo("id-1") == "encolada id-1" and p.como_quedo(None) == p.YA_ENCOLADA
    _intradia(monkeypatch)
    monkeypatch.setattr(p, "encolar_franja", lambda *a, **k: None)          # otra réplica ganó la franja
    with caplog.at_level("INFO", logger=p.log.name):
        assert p.tarea_ciclo_intradia(datetime(2026, 3, 2, 7, 5, 9, tzinfo=Z)) is None
    assert any(p.YA_ENCOLADA in r.getMessage() for r in caplog.records)
    assert p._ultimas["frecuencia_intradia"]["encolada_por_esta_replica"] is False


def test_tarea_intradia_partida_por_ruta_encola_la_madre_con_sus_rutas(monkeypatch):
    llamadas = _intradia(monkeypatch, rutas=["CL 72", "SILENCIO"])
    p.tarea_ciclo_intradia(datetime(2026, 3, 2, 18, 5, 1, tzinfo=Z))
    assert llamadas[0][2]["rutas"] == ["CL 72", "SILENCIO"] and llamadas[0][4] == ["CL 72", "SILENCIO"]
    assert llamadas[0][2]["instante"] == "2026-03-02T18:05:00-05:00"


def test_tarea_intradia_no_toma_la_franja_del_ciclo_diario(monkeypatch):
    """Si los dos crons caen a la misma hora, la franja es del ciclo diario: el índice único (tipo, programada_para)
    se la daría a la primera réplica que llegue, y el ciclo diario quedaría sin correr."""
    llamadas = _intradia(monkeypatch, cron="15 5-20 * * *")
    assert p.tarea_ciclo_intradia(datetime(2026, 3, 2, 5, 15, 2, tzinfo=Z)) is None and llamadas == []
    assert p._ultimas["frecuencia_intradia"]["omitida"].startswith("coincide")
    assert p.tarea_ciclo_intradia(datetime(2026, 3, 2, 6, 15, 2, tzinfo=Z)) == "id-intradia"


@pytest.mark.parametrize("cron, ahora", [("", datetime(2026, 3, 2, 7, 5, tzinfo=Z)),
                                         ("5 6-20 * * *", datetime(2026, 3, 2, 3, 0, tzinfo=Z))])
def test_tarea_intradia_sin_cron_o_sin_franja_no_encola(monkeypatch, cron, ahora):
    llamadas = _intradia(monkeypatch, cron=cron)
    assert p.tarea_ciclo_intradia(ahora) is None and llamadas == []


def test_el_ciclo_intradia_por_omision_cubre_el_servicio_sin_chocar_con_el_diario():
    """PLAN_INTRADIA_CRON por omisión («5 6-20 * * *»): una franja a las :05 de cada hora de 6 a 20 (15 al día),
    ninguna a la hora del ciclo diario (05:15) y la primera cuando ya cerró la primera hora de servicio (4 h)."""
    from app.config import Ajustes

    cron = Ajustes.model_fields["plan_intradia_cron"].default
    diaria = p.disparador(Ajustes.model_fields["plan_ejecucion_cron"].default)
    t, franjas = p.disparador(cron), []
    siguiente = t.get_next_fire_time(None, datetime(2026, 3, 2, 0, 0, tzinfo=Z))
    while siguiente.date() == datetime(2026, 3, 2).date():
        franjas.append(siguiente)
        siguiente = t.get_next_fire_time(siguiente, siguiente + timedelta(seconds=1))
    assert [f.hour for f in franjas] == list(range(6, 21)) and {f.minute for f in franjas} == {5}
    assert diaria.get_next_fire_time(None, datetime(2026, 3, 2, 0, 0, tzinfo=Z)) not in franjas
    trabajos = {i for i, *_ in p.trabajos_programados(SimpleNamespace(
        plan_ejecucion_cron="15 5 * * *", plan_reentrenamiento_cron="0 4 * * 1", plan_intradia_cron=cron,
        fuente="postgres"))}
    assert trabajos == {"ejecucion_diaria", "reentrenamiento", "ciclo_intradia"}


def test_sin_captura_en_vivo_no_hay_ciclo_intradia(monkeypatch):
    """Con la serie empaquetada (FUENTE=parquet, la demostración) no llega nada dentro del día: el trabajo intradía no
    se registra y la tarea no encola (no compite con los ciclos de la demostración por la marca de agua)."""
    aj = SimpleNamespace(plan_ejecucion_cron="15 5 * * *", plan_reentrenamiento_cron="0 4 * * 1",
                         plan_intradia_cron="5 6-20 * * *", fuente="parquet")
    assert "ciclo_intradia" not in {i for i, *_ in p.trabajos_programados(aj)} and not p.intradia_disponible(aj)
    llamadas = _intradia(monkeypatch)
    monkeypatch.setattr(p, "obtener_ajustes", lambda: aj)
    assert p.tarea_ciclo_intradia(datetime(2026, 3, 2, 7, 5, 9, tzinfo=Z)) is None and llamadas == []
    assert p.intradia_disponible(SimpleNamespace(plan_intradia_cron="", fuente="postgres")) is False


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
