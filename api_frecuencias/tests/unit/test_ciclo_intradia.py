"""§10.1 «ocupación actual» en la operación programada: el ciclo intradía y los bordes del día en curso.

- Horas cerradas y completas: una hora entra a las alertas observadas cuando ya salieron todos sus viajes (cerrada) y
  sus conteos cuentan cuando sus viajes terminaron (con los viajes del día) o pasó la duración máxima de un viaje.
- La ocupación actual solo mide las horas cerradas a la referencia del ciclo.
- La restricción reactiva del plan llega también a la recomendación de la franja de 30, 60 y 120 min de la misma hora:
  el MILP de la franja recibe el piso (optimizar(buses_minimos=...)) y la recomendación dice si lo aplicó y por qué.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.servicios import ejecucion, ocupacion
from app.servicios import optimizacion as O

Z = ZoneInfo("America/Bogota")
DIA = date(2025, 10, 22)
ENTRADAS = {"capacidad": 50, "ocupacion_objetivo": 0.85, "headway_min": 2.0}


def _viaje(hora: int, minuto: int, estado: str) -> dict:
    return {"salida": datetime(2025, 10, 22, hora, minuto, tzinfo=Z), "estado": estado}


# ---------------------------------------------------------------- horas cerradas y completas
def test_una_hora_es_completa_cuando_sus_viajes_terminaron_o_paso_la_duracion_maxima():
    ref = datetime(2025, 10, 22, 10, 5, tzinfo=Z)
    viajes = [_viaje(8, 10, "valido"), _viaje(8, 40, "cancelado"), _viaje(9, 0, "valido"),
              _viaje(9, 30, "sin_finalizar")]
    assert ejecucion.hora_completa(DIA, 8, ref, viajes)                  # terminados o cancelados
    assert not ejecucion.hora_completa(DIA, 9, ref, viajes)              # uno sigue en curso
    assert not ejecucion.hora_completa(DIA, 10, ref, viajes)             # la hora en curso nunca
    assert not ejecucion.hora_completa(DIA, 8, ref, None)                # sin viajes: la duración máxima
    assert not ejecucion.hora_completa(DIA, 8, ref, [])
    tarde = ejecucion.fin_de_la_hora(DIA, 9) + ejecucion.DURACION_MAXIMA_VIAJE
    assert ejecucion.hora_completa(DIA, 9, tarde, viajes) and ejecucion.hora_completa(DIA, 9, tarde, None)
    assert not ejecucion.hora_completa(DIA, 9, tarde - timedelta(minutes=1), None)
    assert ejecucion.hora_completa(DIA, 7, ref, viajes)                  # sin viajes en esa hora: nada que esperar


def test_un_episodio_cerrado_solo_se_salta_si_la_deteccion_no_le_agrega_nada():
    """episodio_ya_cerrado (§18 «sin duplicar»): solo para alertas observadas o de calidad de datos. ALT-009 cerrada
    con las mismas horas y campos que faltan no se reabre; con otras, sí. Una observada cerrada cuya ventana ya cubre la
    nueva no se reabre; si el episodio sigue (la ventana pasa la cerrada) o hay una abierta con la clave, se guarda."""
    from types import SimpleNamespace

    def sesion(*alertas):
        return SimpleNamespace(scalars=lambda _consulta: SimpleNamespace(all=lambda: list(alertas)))

    fin = datetime(2025, 10, 22, 9, 0, tzinfo=Z)
    faltan = {"horas_faltantes": ["2025-10-22T06:00:00-05:00"], "campos_faltantes": []}
    nueve = {"origen": "calidad_datos", "clave_dedup": "k9", "variables": faltan}
    assert ejecucion.episodio_ya_cerrado(sesion(), {"origen": "pronostico", "clave_dedup": "k"}) is False
    assert ejecucion.episodio_ya_cerrado(sesion(), dict(nueve, variables={})) is False      # solo atraso: nuevo
    cerrada_9 = SimpleNamespace(estado="cerrada", variables=faltan, ventana_fin=None)
    assert ejecucion.episodio_ya_cerrado(sesion(cerrada_9), nueve) is True
    otra_hora = dict(nueve, variables={"horas_faltantes": ["2025-10-22T07:00:00-05:00"]})
    assert ejecucion.episodio_ya_cerrado(sesion(cerrada_9), otra_hora) is False
    obs = {"origen": "observado", "clave_dedup": "k2", "ventana_fin": fin.isoformat()}
    cerrada = SimpleNamespace(estado="cerrada", variables={}, ventana_fin=fin)
    assert ejecucion.episodio_ya_cerrado(sesion(cerrada), obs) is True
    assert ejecucion.episodio_ya_cerrado(sesion(cerrada), dict(obs, ventana_fin=(fin + timedelta(hours=1))
                                                                .isoformat())) is False
    abierta = SimpleNamespace(estado="abierta", variables={}, ventana_fin=fin)
    assert ejecucion.episodio_ya_cerrado(sesion(cerrada, abierta), obs) is False


def test_el_mismo_episodio_con_otro_inicio_toma_la_clave_de_la_alerta_que_ya_lo_tiene():
    """clave_del_episodio (§18 «sin duplicar»): una detección observada sin alerta abierta con su clave toma la de la
    alerta del mismo código y ruta cuya ventana se cruza con la suya (el episodio de las 7 h que el ciclo siguiente
    detecta desde las 8 h); con una abierta con su propia clave, sin ninguna que se cruce o si no es observada, la suya.
    La consulta de la que se cruza pide el mismo código, la misma ruta y ventanas que se tocan."""
    import uuid

    from sqlalchemy.dialects import postgresql

    a = {"codigo": "ALT-002", "ruta": "CL 72", "origen": "observado", "clave_dedup": "ALT-002|CL 72|08|obs",
         "ventana_inicio": datetime(2025, 10, 22, 8, 0, tzinfo=Z),
         "ventana_fin": datetime(2025, 10, 22, 10, 0, tzinfo=Z)}
    s = _SesionEscalar(None, "ALT-002|CL 72|07|obs")
    assert ejecucion.clave_del_episodio(s, a) == "ALT-002|CL 72|07|obs"
    sql = str(s.sentencias[-1].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "alert.codigo = 'ALT-002'" in sql and "alert.ruta = 'CL 72'" in sql and "alert.origen = 'observado'" in sql
    assert "alert.ventana_inicio <=" in sql and "alert.ventana_fin >=" in sql
    assert ejecucion.clave_del_episodio(_SesionEscalar(uuid.uuid4()), a) == a["clave_dedup"]      # ya tiene la suya
    assert ejecucion.clave_del_episodio(_SesionEscalar(None, None), a) == a["clave_dedup"]        # ninguna se cruza
    for otra in (dict(a, origen="pronostico"), dict(a, origen="calidad_datos"), dict(a, ventana_fin=None)):
        assert ejecucion.clave_del_episodio(_SesionEscalar(), otra) == a["clave_dedup"]           # ni consulta


def test_un_episodio_que_crece_hacia_atras_mueve_el_inicio_de_su_alerta():
    """_actualizar_episodio: la alerta abierta del episodio de las 8 a las 10 h y una detección del mismo episodio que
    ahora empieza a las 7 h (clave_del_episodio la junta con la abierta), con el mismo valor: la ventana pasa a ser la
    unión, de 7 a 10 h, y la bitácora guarda el inicio de antes y el de ahora. Una detección dentro de la ventana y con
    el mismo valor no cambia nada ni deja otra entrada."""
    import uuid
    from unittest import mock

    from app.modelos_db import Alerta

    def h(hora):
        return datetime(2025, 10, 22, hora, tzinfo=Z)

    abierta = Alerta(alert_id=uuid.uuid4(), codigo="ALT-002", origen="observado", estado="nueva", ventana_inicio=h(8),
                     ventana_fin=h(10), observado=1.0)
    a = {"ventana_inicio": h(7).isoformat(), "ventana_fin": h(9).isoformat(), "observado": 1.0, "variables": {},
         "explicacion": "el episodio empieza antes"}
    sesion = mock.MagicMock()
    ejecucion._actualizar_episodio(sesion, abierta, a, None, 1)
    assert (abierta.ventana_inicio, abierta.ventana_fin) == (h(7), h(10))
    (entrada,), _ = sesion.add.call_args
    assert entrada.accion == "redeteccion"
    assert (entrada.detalle["antes"]["ventana_inicio"], entrada.detalle["despues"]["ventana_inicio"]) == (
        h(8).isoformat(), h(7).isoformat())
    sesion.reset_mock()
    ejecucion._actualizar_episodio(sesion, abierta, dict(a, ventana_inicio=h(8).isoformat()), None, 1)
    assert sesion.add.call_count == 0 and (abierta.ventana_inicio, abierta.ventana_fin) == (h(7), h(10))
    assert ejecucion._inicio_anterior(Alerta(ventana_inicio=None), a) == h(7)          # sin inicio, el de la detección


def test_alt002_con_la_hora_pico_de_un_ciclo_anterior_identifica_el_viaje_con_los_viajes_del_dia():
    """§5.3 con la ocupación guardada: ai_frecuencias.ocupacion_segmento guarda solo el id del viaje más cargado
    (id_viaje_max = progvehiculos.idprogramacion). Si la hora pico del episodio la midió un ciclo anterior, ALT-002 lo
    identifica con los viajes del día que el ciclo ya leyó (ctx["viajes"], conductor ya seudonimizado): su vehículo y
    el seudónimo de su conductor. Sin ese viaje entre los del día, «segmento_sin_viaje» como antes; la hora medida por
    este ciclo trae su viaje y no se busca."""
    from app.servicios import alertas

    seudonimo = "cnd_" + "a" * 24
    guardada = {"nro_segmento": 34, "id_segmento": 4321, "sentido": "ida", "nro_viajes": 10, "carga_media": 50.0,
                "carga_max": 53.0, "viaje": None, "id_viaje_max": 90_000_707}
    del_dia = [alertas.viaje_de_fila({"viaje": 90_000_706.0, "vehiculo": 706, "conductor": "cnd_" + "b" * 24}),
               alertas.viaje_de_fila({"viaje": 90_000_707.0, "vehiculo": "VH707", "conductor": seudonimo})]

    def con_viaje(seg, viajes):
        base = {"variables_ocupacion": {}}
        alertas._con_viaje_critico(base, seg, viajes)
        return base

    base = con_viaje(guardada, del_dia)
    assert (base["viaje"], base["vehiculo"], base["conductor"]) == (90_000_707, "VH707", seudonimo)
    ident = base["variables_ocupacion"]["identificacion_5_3"]
    assert (ident["resultado"], ident["viaje_medido_por"]) == ("identificado", "ciclo_anterior")
    assert base["variables_ocupacion"]["carga_viaje_critico"] == 53.0
    for viajes in (None, [], del_dia[:1]):                        # sin ese viaje entre los del día
        sin = con_viaje(guardada, viajes)
        assert sin["viaje"] is None and sin["variables_ocupacion"]["identificacion_5_3"]["resultado"] == (
            "segmento_sin_viaje")
    medida = dict(guardada, viaje={"id_viaje": 1, "vehiculo": "V1", "conductor": seudonimo, "carga": 50.0})
    assert con_viaje(medida, del_dia)["viaje"] == 1                 # la de este ciclo trae su viaje
    assert "viaje_medido_por" not in con_viaje(medida, del_dia)["variables_ocupacion"]["identificacion_5_3"]


def test_la_ocupacion_del_dia_es_la_guardada_con_la_del_ciclo_encima(monkeypatch):
    """ocupacion_del_dia (§10.1, ALT-002): las horas que midieron los ciclos anteriores (ocupacion.observada_guardada,
    sin el viaje) con encima las que midió este ciclo (con el viaje más cargado); sin día, la del ciclo; si la lectura
    falla, la del ciclo; sin ninguna, None."""
    from contextlib import nullcontext
    from types import SimpleNamespace

    guardada = {(DIA, 7): {"ocupacion_media": 1.0, "viaje": None}, (DIA, 8): {"ocupacion_media": 0.5, "viaje": None}}
    del_ciclo = {(DIA, 8): {"ocupacion_media": 1.0, "viaje": {"id_viaje": 1}}}
    pedidas = []

    def leer(s, ruta, fecha, medida_hasta):
        pedidas.append((ruta, fecha))
        return dict(guardada)

    def falla(*_args):
        raise RuntimeError("sin la tabla")

    s = SimpleNamespace(begin_nested=nullcontext)
    monkeypatch.setattr(ocupacion, "observada_guardada", leer)
    dia = ejecucion.ocupacion_del_dia(s, "CL 72", DIA, del_ciclo)
    assert dia == {(DIA, 7): guardada[(DIA, 7)], (DIA, 8): del_ciclo[(DIA, 8)]} and pedidas == [("CL 72", DIA)]
    assert ejecucion.ocupacion_del_dia(s, "CL 72", None, del_ciclo) is del_ciclo and len(pedidas) == 1
    monkeypatch.setattr(ocupacion, "observada_guardada", falla)
    assert ejecucion.ocupacion_del_dia(s, "CL 72", DIA, del_ciclo) == del_ciclo
    assert ejecucion.ocupacion_del_dia(s, "CL 72", DIA, None) is None


def test_contexto_observado_es_el_del_ultimo_dia_que_se_evalua(monkeypatch):
    """contexto_observado (el nombre de siempre) devuelve el último de contextos_observados, con la frescura."""
    llamadas = []

    def contextos(*args, **kwargs):
        llamadas.append((args, kwargs))
        return [{"fecha": DIA - timedelta(days=1)}, {"fecha": DIA}]

    monkeypatch.setattr(ejecucion, "contextos_observados", contextos)
    ref = datetime(2025, 10, 22, 9, 5, tzinfo=Z)
    assert ejecucion.contexto_observado(None, "CL 72", None, [], "m", ref, {}) == {"fecha": DIA}
    assert llamadas[0][0][1] == "CL 72" and llamadas[0][1]["fallos"] is None


def test_es_intradia_solo_con_la_marca_del_planificador():
    assert ejecucion.es_intradia({"intradia": True, "instante": "2025-10-22T09:05:00-05:00"})
    assert not ejecucion.es_intradia({"instante": "2025-10-22T09:05:00-05:00"})   # un POST con instante no lo es
    assert not ejecucion.es_intradia(None)


class _SesionEscalar:
    """Doble de Session.scalar: devuelve en orden los valores dados y anota cada consulta y sus parámetros."""

    def __init__(self, *valores):
        self.valores, self.consultas, self.sentencias = list(valores), [], []

    def scalar(self, consulta, parametros=None):
        self.consultas.append(parametros)
        self.sentencias.append(consulta)
        return self.valores.pop(0)


def test_la_franja_posterior_en_la_cola_solo_se_busca_para_un_ciclo_intradia():
    """franja_posterior_en_cola: un ciclo que no es intradía nunca se omite; el intradía busca una franja planificada
    posterior a la suya o, si es el trabajo de una ruta, a la de su madre."""
    import uuid
    from types import SimpleNamespace

    franja = datetime(2025, 10, 22, 9, 5, tzinfo=Z)
    posterior = franja + timedelta(hours=1)

    def e(parametros, programada=None, padre=None):
        return SimpleNamespace(parametros=parametros, programada_para=programada, padre_id=padre)

    assert ejecucion.franja_posterior_en_cola(_SesionEscalar(), e({}, franja)) is None
    s = _SesionEscalar(posterior)
    assert ejecucion.franja_posterior_en_cola(s, e({"intradia": True}, franja)) == posterior
    assert s.consultas == [{"franja": franja}]
    s = _SesionEscalar(franja, None)                    # el trabajo de una ruta: la franja es la de su madre
    assert ejecucion.franja_posterior_en_cola(s, e({"intradia": True}, padre=uuid.uuid4())) is None
    assert s.consultas[-1] == {"franja": franja}
    assert ejecucion.franja_posterior_en_cola(_SesionEscalar(None), e({"intradia": True}, padre=uuid.uuid4())) is None


def test_la_franja_vieja_se_cierra_ok_sin_leer_ni_mover_la_marca(monkeypatch):
    """_omitida_por_franja_posterior cierra «ok» con la cerca de la cola (cola.cerrar_ok), sin filas ni marcas de agua
    y diciendo qué franja la reemplaza; _ciclo_frecuencia entonces no lee el lote. Sin franja posterior, sigue."""
    import uuid
    from contextlib import contextmanager
    from types import SimpleNamespace

    from app.servicios import cola

    posterior = datetime(2025, 10, 22, 10, 5, tzinfo=Z)
    e = SimpleNamespace(parametros={"intradia": True, "instante": "2025-10-22T09:05:00-05:00"},
                        programada_para=posterior - timedelta(hours=1), padre_id=None)
    cierres, respuestas = [], [posterior]

    @contextmanager
    def sesion():
        yield SimpleNamespace(get=lambda _modelo, _id: e, scalar=lambda *_a: respuestas.pop(0))

    monkeypatch.setattr(ejecucion, "sesion_contexto", sesion)
    monkeypatch.setattr(cola, "cerrar_ok", lambda s, eid, valores: cierres.append(valores))
    eid = uuid.uuid4()
    assert ejecucion._omitida_por_franja_posterior(eid) is True
    (valores,) = cierres
    assert (valores["estado"], valores["filas_leidas"], valores["filas_validas"]) == ("ok", 0, 0)
    assert "marca_agua_nueva" not in valores and valores["mensaje"].startswith("Franja intradía omitida")
    assert valores["metricas"]["intradia"]["franja_posterior"] == posterior.isoformat()
    respuestas.append(None)                                         # sin franja posterior: el ciclo sigue
    assert ejecucion._omitida_por_franja_posterior(eid) is False and len(cierres) == 1
    leidos = []
    monkeypatch.setattr(ejecucion, "_es_madre", lambda _eid: False)
    monkeypatch.setattr(ejecucion, "_omitida_por_franja_posterior", lambda _eid: True)
    monkeypatch.setattr(ejecucion, "_leer_lote", lambda s, _eid: leidos.append(_eid))
    ciclo_frecuencia = getattr(ejecucion._ciclo_frecuencia, "_otel_original", ejecucion._ciclo_frecuencia)
    ciclo_frecuencia(eid)
    assert leidos == []                                             # omitida: no lee el lote


class _SesionFilas:
    """Doble de Session.execute(...).mappings().all() con filas fijas; anota los parámetros de la consulta."""

    def __init__(self, filas):
        self.filas, self.parametros = filas, None

    def execute(self, _consulta, parametros):
        self.parametros = parametros
        return self

    def mappings(self):
        return self

    def all(self):
        return self.filas


def test_la_ocupacion_guardada_es_la_del_ciclo_y_solo_la_medida_antes_del_instante():
    """POST /predictions/run (ocupacion.reactiva_guardada): la ocupación que guardó el ciclo se lee como la del ciclo
    (resumen_por_hora: carga crítica = carga media × viajes medidos) pidiendo solo lo medido hasta el instante, y arma
    la misma restricción reactiva. Sin instante o sin nada medido, ninguna."""
    medida, instante = datetime(2025, 10, 22, 9, 6, tzinfo=Z), datetime(2025, 10, 22, 9, 10, tzinfo=Z)
    fila = {"hora": 8, "nro_segmento": 34, "id_segmento": 4321, "sentido": "ida", "nro_viajes": 12,
            "carga_media": 50.0, "carga_max": 52.0, "capacidad": 50.0, "ocupacion_media": 1.0, "ocupacion_max": 1.04,
            "actualizado_en": medida}
    s = _SesionFilas([fila])
    r = ocupacion.observada_guardada(s, "CL 72", DIA, instante)[(DIA, 8)]
    assert s.parametros == {"ruta": "CL 72", "fecha": DIA, "medida_hasta": instante}
    assert (r["carga_total"], r["nro_viajes"], r["medida_en"], r["viaje"]) == (600.0, 12, medida, None)
    assert r["id_viaje_max"] is None                       # la fila no trae el id: ninguno
    con_id = ocupacion.observada_guardada(_SesionFilas([dict(fila, id_viaje_max=90_000_812)]), "CL 72", DIA, instante)
    assert con_id[(DIA, 8)]["id_viaje_max"] == 90_000_812 and con_id[(DIA, 8)]["viaje"] is None
    reactiva = ocupacion.reactiva_guardada(_SesionFilas([fila]), "CL 72", DIA, instante, {})
    assert reactiva["aplica"] is True and (reactiva["hora_cerrada"], reactiva["hora_aplica"]) == (8, 9)
    assert reactiva["carga_critica_pax_h"] == 600.0 and reactiva["fecha_plan"] == DIA.isoformat()
    assert ocupacion.reactiva_guardada(_SesionFilas([fila]), "CL 72", DIA, None, {}) is None
    assert ocupacion.reactiva_guardada(_SesionFilas([]), "CL 72", DIA, instante, {}) is None


def test_la_ocupacion_actual_solo_mide_las_horas_cerradas():
    lote = pd.DataFrame([{"ruta": "CL 72", "fecha": DIA, "hora": h} for h in (7, 8, 9)])
    todas = ocupacion.franjas_del_lote(lote)
    assert [h for _, _, h in todas] == [7, 8, 9]
    a_las_930 = ocupacion.franjas_del_lote(lote, datetime(2025, 10, 22, 9, 30, tzinfo=Z))
    assert [h for _, _, h in a_las_930] == [7, 8]
    assert ocupacion.franjas_del_lote(lote, datetime(2025, 10, 22, 10, 0, tzinfo=Z)) == todas
    utc = datetime(2025, 10, 22, 14, 30, tzinfo=ZoneInfo("UTC"))            # 9:30 en Bogotá
    assert ocupacion.franjas_del_lote(lote, utc) == a_las_930


# ---------------------------------------------------------------- piso de la franja
def _reactiva(hora_aplica=9, carga=900.0, aplica=True, fecha=DIA) -> dict:
    return {"aplica": aplica, "hora_aplica": hora_aplica, "hora_cerrada": hora_aplica - 1, "segmento": 34,
            "sentido": "ida", "ocupacion_observada": 0.97, "carga_critica_pax_h": carga,
            "fecha_plan": fecha.isoformat(), "fuente": ocupacion.FUENTE_ACTUAL}


def test_el_piso_de_la_franja_es_el_del_plan_con_la_hora_entera():
    piso = ocupacion.piso_de_la_franja(_reactiva(), DIA, 9, ENTRADAS)
    assert piso["salidas_minimas"] == 22 and piso["salidas_pedidas"] == 22      # ceil(900 / (50 × 0,85))
    assert "ceil(900,0 / (50 × 0,85)) = 22" in piso["formula"] and piso["hora_cerrada"] == 8
    acotado = ocupacion.piso_de_la_franja(_reactiva(carga=2000.0), DIA, 9, dict(ENTRADAS, headway_min=3.0))
    assert (acotado["salidas_pedidas"], acotado["salidas_minimas"]) == (48, 20)
    assert acotado["limitada_por_headway_minimo"] and "headway mínimo a 20" in acotado["formula"]
    for reactiva, fecha, hora in ((_reactiva(), DIA, 10), (_reactiva(), DIA + timedelta(days=1), 9),
                                  (_reactiva(aplica=False), DIA, 9), (None, DIA, 9)):
        assert ocupacion.piso_de_la_franja(reactiva, fecha, hora, ENTRADAS) is None


def test_el_piso_de_la_franja_no_pasa_de_lo_que_la_flota_sostiene_con_el_ciclo():
    """El MILP de la franja dimensiona la flota en régimen (vehículos = ceil(ciclo × buses/h / 60) <= flota): con 30
    vehículos y un ciclo de 150 min la franja sostiene 12 buses/h, así que el piso de 22 queda en 12 y lo dice."""
    con_flota = dict(ENTRADAS, flota_disponible=30, tiempo_ciclo_min=150.0)
    piso = ocupacion.piso_de_la_franja(_reactiva(), DIA, 9, con_flota)
    assert (piso["salidas_pedidas"], piso["salidas_minimas"], piso["tope_por_flota"]) == (22, 12, 12)
    assert piso["limitada_por_flota"] and not piso["limitada_por_headway_minimo"]
    assert piso["formula"].endswith("acotado por la flota disponible y el ciclo a 12")
    holgada = ocupacion.piso_de_la_franja(_reactiva(), DIA, 9, dict(ENTRADAS, flota_disponible=90,
                                                                    tiempo_ciclo_min=150.0))
    assert holgada["salidas_minimas"] == 22 and not holgada["limitada_por_flota"]


def test_el_milp_de_la_franja_respeta_el_piso_de_la_ocupacion_observada():
    """optimizar(buses_minimos=k): la cota inferior pasa a k, la restricción «ocupacion_observada» aparece y manda;
    el headway máximo de la política sigue igual. Sin piso, el resultado es el de siempre (paridad)."""
    comun = dict(capacidad=50, ocupacion_objetivo=0.85, tiempo_ciclo_min=None, headway_min=2.0, headway_max=10.0)
    sin = O.optimizar("CL 72", 9, 200.0, 250.0, 150.0, **comun)
    assert sin["viable"] and sin["buses_hora"] < 20
    assert O.optimizar("CL 72", 9, 200.0, 250.0, 150.0, **comun, buses_minimos=None) == sin
    con = O.optimizar("CL 72", 9, 200.0, 250.0, 150.0, **comun, buses_minimos=20)
    assert con["viable"] and con["buses_hora"] == 20 and "ocupacion_observada" in con["limites_activos"]
    filas = {f["nombre"]: f for f in con["restricciones"]}
    assert filas["ocupacion_observada"]["limite"] == 20 and filas["ocupacion_observada"]["holgura"] == 0
    assert filas["headway_maximo"]["limite"] == 10.0 and not filas["headway_maximo"]["activa"]
    assert any("ocupación observada" in t for t in con["explicacion"])
    holgado = O.optimizar("CL 72", 9, 200.0, 250.0, 150.0, **comun, buses_minimos=1)
    assert holgado["buses_hora"] == sin["buses_hora"] and "ocupacion_observada" not in holgado["limites_activos"]


class _Optimizacion:
    """Doble de optimizacion.recomendacion_franja: sin piso, `base` buses/h; con piso, el piso si es ejecutable (hasta
    `maximo` buses/h; None = cualquiera)."""

    def __init__(self, base=8, viable_con_piso=True, maximo=None):
        self.base, self.viable_con_piso, self.maximo, self.llamadas = base, viable_con_piso, maximo, []

    def __call__(self, info, umbrales, version, *, buses_minimos=None, **franja):
        self.llamadas.append(buses_minimos)
        if buses_minimos is None:
            return {"buses_hora": self.base, "viable": True, "explicacion": ["base"]}, dict(ENTRADAS)
        viable = self.viable_con_piso and (self.maximo is None or buses_minimos <= self.maximo)
        return ({"buses_hora": buses_minimos, "viable": viable, "explicacion": ["con piso"]},
                dict(ENTRADAS, buses_minimos=buses_minimos))


def _franja(hora=9) -> dict:
    return {"fecha": DIA, "hora": hora, "demanda_hora": 300.0, "p90_hora": 360.0, "p10_hora": 240.0}


def test_la_recomendacion_de_la_franja_usa_la_restriccion_reactiva_de_la_hora(monkeypatch):
    doble = _Optimizacion(base=8)
    monkeypatch.setattr(O, "recomendacion_franja", doble)
    rec, entradas = ejecucion.recomendacion_con_ocupacion({"ruta": "CL 72"}, _franja(), {}, 3, _reactiva())
    assert doble.llamadas == [None, 22] and rec["buses_hora"] == 22
    r = rec["restriccion_reactiva"]
    assert r["aplicada"] is True and r["buses_hora_sin_piso"] == 8 and r["salidas_minimas"] == 22
    assert rec["explicacion"][-1].startswith("Restricción reactiva de ocupación observada (§10.1)")
    assert entradas["restriccion_reactiva"]["aplicada"] is True


def test_con_la_flota_de_cada_tipologia_la_franja_toma_el_mayor_piso_ejecutable(monkeypatch):
    """El MILP de la franja no es viable con 22 buses/h (la flota de cada tipología con el ciclo): toma el mayor piso
    que sí lo es (12) y lo dice en la fórmula y en limitada_por_flota."""
    doble = _Optimizacion(base=8, maximo=12)
    monkeypatch.setattr(O, "recomendacion_franja", doble)
    rec, _ = ejecucion.recomendacion_con_ocupacion({"ruta": "CL 72"}, _franja(), {}, 3, _reactiva())
    assert doble.llamadas == [None, *range(22, 11, -1)] and rec["buses_hora"] == 12
    r = rec["restriccion_reactiva"]
    assert r["aplicada"] and r["salidas_pedidas"] == 22 and r["salidas_minimas"] == 12 and r["limitada_por_flota"]
    assert r["formula"].endswith("acotado por la flota disponible de cada tipología y el ciclo a 12")


@pytest.mark.parametrize("base, viable, hora, llamadas, aplicada", [
    (25, True, 9, [None], False),                          # ya cumple el piso
    (8, False, 9, [None, *range(22, 8, -1)], False),       # ni un bus más es ejecutable: queda la de siempre
    (8, True, 10, [None], None),                           # otra hora: la restricción no la toca
])
def test_la_franja_no_cambia_si_ya_cumple_si_no_se_puede_o_si_es_otra_hora(monkeypatch, base, viable, hora,
                                                                           llamadas, aplicada):
    doble = _Optimizacion(base=base, viable_con_piso=viable)
    monkeypatch.setattr(O, "recomendacion_franja", doble)
    rec, _ = ejecucion.recomendacion_con_ocupacion({"ruta": "CL 72"}, _franja(hora), {}, 3, _reactiva())
    assert doble.llamadas == llamadas and rec["buses_hora"] == base
    assert (rec.get("restriccion_reactiva") or {}).get("aplicada") is aplicada
    if aplicada is False:
        assert rec["restriccion_reactiva"]["motivo"]


def test_una_franja_que_no_es_viable_ni_sin_piso_se_informa_como_esta(monkeypatch):
    """Si el MILP de la franja ya no es viable sin el piso, la restricción no se aplica y la recomendación (con su
    motivo de inviabilidad) queda igual: no se busca un piso ejecutable."""
    llamadas = []

    def no_viable(info, umbrales, version, *, buses_minimos=None, **franja):
        llamadas.append(buses_minimos)
        return {"buses_hora": 8, "viable": False, "motivo": "flota insuficiente"}, dict(ENTRADAS)

    monkeypatch.setattr(O, "recomendacion_franja", no_viable)
    rec, _ = ejecucion.recomendacion_con_ocupacion({"ruta": "CL 72"}, _franja(), {}, 3, _reactiva())
    assert llamadas == [None] and rec["buses_hora"] == 8 and rec["restriccion_reactiva"]["aplicada"] is False
    assert rec["restriccion_reactiva"]["motivo"].startswith("la franja no es viable ni sin el piso")


def test_si_la_flota_ya_no_deja_subir_la_franja_lo_dice(monkeypatch):
    doble = _Optimizacion(base=12)
    monkeypatch.setattr(O, "recomendacion_franja", lambda *a, **k: (
        doble(*a, **k)[0], dict(ENTRADAS, flota_disponible=30, tiempo_ciclo_min=150.0)))
    rec, _ = ejecucion.recomendacion_con_ocupacion({"ruta": "CL 72"}, _franja(), {}, 3, _reactiva())
    assert rec["buses_hora"] == 12 and rec["restriccion_reactiva"]["aplicada"] is False
    assert rec["restriccion_reactiva"]["motivo"].startswith("la flota disponible no deja subir más")


def test_sin_ocupacion_observada_la_franja_es_la_de_siempre(monkeypatch):
    doble = _Optimizacion(base=8)
    monkeypatch.setattr(O, "recomendacion_franja", doble)
    rec, _ = ejecucion.recomendacion_con_ocupacion({"ruta": "CL 72"}, _franja(), {}, 3, None)
    assert doble.llamadas == [None] and "restriccion_reactiva" not in rec
