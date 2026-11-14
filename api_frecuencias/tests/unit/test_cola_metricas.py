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


def etiquetas_de_etapas() -> set[str]:
    """Las etiquetas «etapa» que tiene hoy la métrica api_ejecucion_etapa_segundos en el registro de Prometheus."""
    return {m.labels["etapa"] for familia in REGISTRY.collect() if familia.name == "api_ejecucion_etapa_segundos"
            for m in familia.samples if "etapa" in m.labels}


def test_la_etiqueta_de_la_etapa_es_su_nombre_sin_el_detalle():
    assert ejecucion.etiqueta_etapa("lectura_fuente 1/2 (2023-01-01 a 2023-01-31)") == "lectura_fuente"
    assert ejecucion.etiqueta_etapa("lectura_fuente (completo, 2 tramos)") == "lectura_fuente"
    assert ejecucion.etiqueta_etapa("simulacion de las filas") == "simulacion"
    assert ejecucion.etiqueta_etapa("calidad") == "calidad"
    for otra in ("alertas: alert", "resultados: prediction", "2023-01-01", "", None, "Calidad", "etapa_nueva"):
        assert ejecucion.etiqueta_etapa(otra) == ejecucion.ETAPA_OTRA, otra


def _etapa_de_la_llamada(nodo, constantes: dict):
    """La etapa de una llamada a _avance(execution_id, progreso, etapa) o a avance(progreso, etapa): un texto literal
    o una constante del módulo (ETAPA_LECTURA); None si no es una de esas llamadas o la etapa llega en una variable."""
    import ast

    funcion = getattr(nodo, "func", None)
    posicion = {"_avance": 2, "avance": 1}.get(getattr(funcion, "attr", None) or getattr(funcion, "id", None))
    if not isinstance(nodo, ast.Call) or posicion is None or len(nodo.args) <= posicion:
        return None
    arg = nodo.args[posicion]
    valor = arg.value if isinstance(arg, ast.Constant) else constantes.get(getattr(arg, "id", None))
    return valor if isinstance(valor, str) else None


def _etapas_en_el_codigo() -> dict[str, set[str]]:
    """Las etapas que el código de app/servicios pasa a ejecucion._avance o al avance del refresco de segmentos y de la
    retención, por archivo. Lo que llega en una variable (el avance que solo reenvía la etapa) no se cuenta."""
    import ast
    from pathlib import Path

    salida: dict[str, set[str]] = {}
    for archivo in sorted(Path(ejecucion.__file__).resolve().parent.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        constantes = {n.targets[0].id: n.value.value for n in arbol.body if isinstance(n, ast.Assign)
                      and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
        etapas = {e for e in (_etapa_de_la_llamada(n, constantes) for n in ast.walk(arbol)) if e is not None}
        if etapas:
            salida[archivo.name] = etapas
    return salida


def test_cada_etapa_del_ciclo_y_de_los_trabajos_es_una_etiqueta_conocida():
    """RNF-006 con el conjunto cerrado: cada etapa que escriben el ciclo de frecuencia (también el intradía, y los
    consolidados, que corren dentro de las etapas del cierre), el entrenamiento, la respuesta, el refresco de segmentos
    y la retención cae en su propio nombre de ETAPAS_METRICA y no en «otra» sin querer. La etapa de cada regla de la
    retención se arma como «grupo: tabla» (un f-string, fuera de esta cuenta) y cuenta en «otra» a propósito."""
    etapas = _etapas_en_el_codigo()
    assert {"ejecucion.py", "segmentos_refresco.py", "retencion.py"} <= set(etapas), etapas
    usadas = set().union(*etapas.values())
    assert {ejecucion.etiqueta_etapa(e) for e in usadas} <= ejecucion.ETAPAS_METRICA, usadas
    assert {"lectura_incremental", "calidad", "prediccion", "alertas", "notificaciones", "plan_dia", "cierre_modelo",
            "lectura_fuente", "agregacion", "registro", "planificacion"} <= {ejecucion.etiqueta_etapa(e)
                                                                              for e in usadas}
    assert ejecucion.etiqueta_etapa("resultados: prediction") == ejecucion.ETAPA_OTRA


def test_etapas_con_fechas_distintas_no_crean_series_nuevas():
    """RNF-006: cada refresco de segmentos con otras fechas pasaba una etiqueta nueva (cardinalidad sin límite); con
    el nombre de la etapa, cien tramos de fechas distintas caen en la misma serie y el conjunto de etiquetas queda
    dentro del conjunto cerrado."""
    from datetime import date, timedelta

    antes = _muestra("api_ejecucion_etapa_segundos_count", {"etapa": "lectura_fuente"})
    eid = uuid.uuid4()
    for i in range(100):
        dia = date(2023, 1, 1) + timedelta(days=i)
        ejecucion._medir_etapa(eid, f"lectura_fuente {i + 1}/100 ({dia} a {dia})")
    ejecucion.cerrar_etapa(eid)
    assert _muestra("api_ejecucion_etapa_segundos_count", {"etapa": "lectura_fuente"}) == antes + 100
    etiquetas = etiquetas_de_etapas()
    assert etiquetas <= ejecucion.ETAPAS_METRICA | {ejecucion.ETAPA_OTRA}, etiquetas
    assert not any(c.isdigit() for e in etiquetas for c in e)


def test_el_avance_guarda_el_detalle_en_la_columna_y_mide_el_nombre(monkeypatch):
    """_avance: la columna etapa de execution_log lleva el nombre y el detalle (el progreso que se consulta), la
    métrica solo el nombre."""
    from contextlib import contextmanager

    sentencias: list = []

    class Sesion:
        def execute(self, consulta):
            sentencias.append(consulta.compile().params)

    @contextmanager
    def sesion():
        yield Sesion()

    monkeypatch.setattr(ejecucion, "sesion_contexto", sesion)
    eid = uuid.uuid4()
    ejecucion._avance(eid, 40, "lectura_fuente", detalle="2/3 (2023-02-01 a 2023-02-28)")
    ejecucion._avance(eid, 90, "agregacion")
    ejecucion.cerrar_etapa(eid)
    assert sentencias[0]["etapa"] == "lectura_fuente 2/3 (2023-02-01 a 2023-02-28)"
    assert sentencias[1]["etapa"] == "agregacion"
    assert "lectura_fuente 2/3 (2023-02-01 a 2023-02-28)" not in etiquetas_de_etapas()


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
