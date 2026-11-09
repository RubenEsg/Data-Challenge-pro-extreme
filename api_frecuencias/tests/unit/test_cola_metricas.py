"""Cola: trabajo de tipo «respuesta» y métricas Prometheus de ejecuciones, etapas, reintentos y profundidad."""
from __future__ import annotations

import uuid

from prometheus_client import REGISTRY

from app.servicios import cola, ejecucion


def _muestra(nombre: str, etiquetas: dict) -> float:
    return REGISTRY.get_sample_value(nombre, etiquetas) or 0.0


def test_el_trabajo_respuesta_llama_a_su_ciclo_y_cuenta_el_intento(monkeypatch):
    llamadas = []
    monkeypatch.setattr(ejecucion, "_ciclo_respuesta", lambda eid: llamadas.append(("respuesta", eid)))
    monkeypatch.setattr(ejecucion, "_ciclo_frecuencia", lambda eid: llamadas.append(("frecuencia", eid)))
    antes = _muestra("api_ejecuciones_total", {"tipo": "respuesta", "resultado": "ok"})
    antes_n = _muestra("api_ejecucion_duracion_segundos_count", {"tipo": "respuesta", "resultado": "ok"})
    eid = uuid.uuid4()
    resultado = cola.correr_reclamo(cola.Reclamo(execution_id=eid, tipo="respuesta", intentos=1, worker_id="w:1:a"),
                                    lease_s=3600)
    assert resultado == "ok" and llamadas == [("respuesta", eid)]
    assert _muestra("api_ejecuciones_total", {"tipo": "respuesta", "resultado": "ok"}) == antes + 1
    assert _muestra("api_ejecucion_duracion_segundos_count", {"tipo": "respuesta", "resultado": "ok"}) == antes_n + 1


def test_la_reserva_perdida_tambien_se_cuenta(monkeypatch):
    def pierde(eid):
        raise cola.ReservaPerdida("otra réplica la retomó")

    monkeypatch.setattr(ejecucion, "_ciclo_frecuencia", pierde)
    monkeypatch.setattr(cola, "_cerrar_intento", lambda *a, **k: None)
    antes = _muestra("api_ejecuciones_total", {"tipo": "frecuencia", "resultado": "reserva_perdida"})
    r = cola.Reclamo(execution_id=uuid.uuid4(), tipo="frecuencia", intentos=1, worker_id="w:1:a")
    assert cola.correr_reclamo(r, lease_s=3600) == "reserva_perdida"
    assert _muestra("api_ejecuciones_total", {"tipo": "frecuencia", "resultado": "reserva_perdida"}) == antes + 1


def test_un_fallo_reintentable_cuenta_un_reintento(monkeypatch):
    def falla(eid):
        raise RuntimeError("base caída un momento")

    monkeypatch.setattr(ejecucion, "_ciclo_entrenamiento", falla)
    monkeypatch.setattr(cola, "_registrar_fallo", lambda r, exc, definitiva, espera: "error" if definitiva
                        else "reintento")
    antes = _muestra("api_cola_reintentos_total", {"tipo": "entrenamiento", "motivo": "fallo"})
    r = cola.Reclamo(execution_id=uuid.uuid4(), tipo="entrenamiento", intentos=1, worker_id="w:1:a")
    assert cola.correr_reclamo(r, lease_s=3600, max_reintentos=3) == "reintento"
    assert _muestra("api_cola_reintentos_total", {"tipo": "entrenamiento", "motivo": "fallo"}) == antes + 1
    assert _muestra("api_ejecuciones_total", {"tipo": "entrenamiento", "resultado": "reintento"}) >= 1


def test_las_etapas_se_miden_de_una_a_la_siguiente():
    eid = uuid.uuid4()
    antes = _muestra("api_ejecucion_etapa_segundos_count", {"etapa": "calidad"})
    ejecucion._medir_etapa(eid, "calidad")
    ejecucion._medir_etapa(eid, "prediccion")
    ejecucion.cerrar_etapa(eid)
    assert _muestra("api_ejecucion_etapa_segundos_count", {"etapa": "calidad"}) == antes + 1
    assert eid not in ejecucion._etapas_en_curso


def test_la_profundidad_de_la_cola_no_rompe_metrics_sin_base(monkeypatch):
    class SinBase:
        def __enter__(self):
            raise ConnectionError("sin base")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cola, "sesion_contexto", lambda: SinBase())
    (familia,) = list(cola.ColectorCola(ttl_s=0).collect())
    assert familia.name == "api_cola_trabajos" and familia.samples == []


def test_el_trabajo_respuesta_sin_datos_no_se_reintenta(monkeypatch):
    """Un día sin variables (respuesta.SinDatos) o una ruta inválida (ValueError) no mejoran con un reintento: el
    trabajo «respuesta» falla de forma definitiva con su motivo (ErrorNoReintentable)."""
    import pytest

    from app.servicios import respuesta

    for error in (respuesta.SinDatos("sin variables para el 2030-01-01"), ValueError("ruta inválida")):
        def falla(_eid, error=error):
            raise error

        monkeypatch.setattr(ejecucion, "_foto_de_la_respuesta_en_cola", falla)
        with pytest.raises(ejecucion.ErrorNoReintentable) as info:
            ejecucion._ciclo_respuesta(uuid.uuid4())
        assert str(error) in str(info.value) and info.value.__cause__ is error


def test_la_serie_diaria_de_la_ruptura_se_memoriza_por_ruta_dia_y_huella(monkeypatch):
    """RF-009 en el ciclo: la serie diaria (56 días × 17 h de pronóstico) se calcula una vez por ruta, día, modelo y
    huella de lo observado; si llega o se corrige un dato de la ventana, la huella cambia y se recalcula. La duración
    queda en api_serie_diaria_segundos y una falla no detiene el ciclo."""
    from contextlib import nullcontext
    from datetime import date
    from types import SimpleNamespace

    from app.servicios import alertas

    class SesionFalsa:
        def __init__(self):
            self.huella = (100, 5000, None)

        def begin_nested(self):
            return nullcontext()

        def execute(self, _consulta):
            return SimpleNamespace(one=lambda: self.huella)

    llamadas = []

    def serie(s, ruta, hasta, model_id=None, *, dias=56, nuevas=()):
        llamadas.append((ruta, hasta, model_id, dias))
        return [{"fecha": hasta, "observado": 10.0, "esperado": 9.0, "nueva": True}]

    ejecucion.limpiar_series_diarias()
    monkeypatch.setattr(alertas, "serie_diaria_ruta", serie)
    s, dia = SesionFalsa(), date(2025, 8, 30)
    antes = _muestra("api_serie_diaria_segundos_count", {"memoria": "si"})
    primera = ejecucion.serie_diaria_memorizada(s, "CL 72", dia, "m1", {dia})
    segunda = ejecucion.serie_diaria_memorizada(s, "CL 72", dia, "m1", {dia})
    assert primera == segunda and len(llamadas) == 1 and llamadas[0][3] == ejecucion.SERIE_DIARIA_DIAS
    assert _muestra("api_serie_diaria_segundos_count", {"memoria": "si"}) == antes + 1
    s.huella = (101, 5010, None)                       # llegó un dato de la ventana: se recalcula
    ejecucion.serie_diaria_memorizada(s, "CL 72", dia, "m1", {dia})
    assert len(llamadas) == 2

    def falla(*_a, **_k):
        raise RuntimeError("sin modelo")

    monkeypatch.setattr(alertas, "serie_diaria_ruta", falla)
    fallos: list = []
    assert ejecucion.serie_diaria_memorizada(s, "CRA 54", dia, "m1", {dia}, fallos) == []
    assert fallos and fallos[0]["etapa"] == "serie_diaria" and fallos[0]["ruta"] == "CRA 54"
    ejecucion.limpiar_series_diarias()
