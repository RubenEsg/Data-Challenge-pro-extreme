"""RNF-010: circuit breaker cerrado -> abierto -> semiabierto -> cerrado, con reloj controlado; métricas; los errores
de datos no lo abren; la fuente PostgreSQL y los notificadores pasan por él."""
from unittest import mock

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from app.servicios import circuito as C
from app.servicios import fuentes as F
from app.servicios import notificaciones as N


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _metrica(nombre, integracion, **extra):
    return REGISTRY.get_sample_value(nombre, {"integracion": integracion, **extra})


@pytest.fixture(autouse=True)
def registro_limpio():
    C.reiniciar_todos()
    yield
    C.reiniciar_todos()


def _caida():
    raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))


def test_ciclo_completo_cerrado_abierto_semiabierto_cerrado():
    reloj, llamadas = Reloj(), []
    c = C.Circuito("prueba_ciclo", fallos_max=3, reinicio_s=60, reloj=reloj)

    def fuente():
        llamadas.append(1)
        return _caida()

    for _ in range(3):
        with pytest.raises(OperationalError):
            c.llamar(fuente)
    assert c.estado == C.ABIERTO and _metrica("api_circuito_estado", "prueba_ciclo") == 2
    rechazos = _metrica("api_circuito_rechazos_total", "prueba_ciclo") or 0
    with pytest.raises(C.CircuitoAbierto) as e:
        c.llamar(fuente)                                  # falla rápido: la fuente NO se llama
    assert len(llamadas) == 3 and 0 < e.value.reintentar_en_s <= 60
    assert _metrica("api_circuito_rechazos_total", "prueba_ciclo") == rechazos + 1

    reloj.t += 61                                         # vence el reinicio: el próximo llamado es el ensayo
    assert c.estado == C.SEMIABIERTO
    with pytest.raises(OperationalError):
        c.llamar(fuente)                                  # el ensayo falla -> abierto otra vez
    assert c.estado == C.ABIERTO and len(llamadas) == 4

    reloj.t += 61
    assert c.llamar(lambda: "ok") == "ok"                 # ensayo bien -> cerrado
    assert c.estado == C.CERRADO and _metrica("api_circuito_estado", "prueba_ciclo") == 0
    assert c.resumen()["fallos_seguidos"] == 0
    assert _metrica("api_circuito_transiciones_total", "prueba_ciclo", hacia="abierto") == 2
    assert _metrica("api_circuito_transiciones_total", "prueba_ciclo", hacia="semiabierto") == 2


def test_semiabierto_admite_un_solo_ensayo_a_la_vez():
    reloj = Reloj()
    c = C.Circuito("prueba_ensayo", fallos_max=1, reinicio_s=10, reloj=reloj)
    with pytest.raises(OperationalError):
        c.llamar(_caida)
    reloj.t += 11

    def ensayo_lento():
        with pytest.raises(C.CircuitoAbierto):           # un segundo llamado concurrente se rechaza
            c.llamar(lambda: "no debe correr")
        return "ok"

    assert c.llamar(ensayo_lento) == "ok" and c.estado == C.CERRADO


@pytest.mark.parametrize("error", [ValueError("dato malo"), KeyError("ruta"), F.OperacionNoPermitida("DROP"),
                                   ProgrammingError("SELEC", {}, Exception("syntax")),
                                   IntegrityError("INSERT", {}, Exception("duplicada"))])
def test_errores_de_datos_no_abren_el_circuito(error):
    c = C.Circuito("prueba_datos", fallos_max=1, reinicio_s=60, reloj=Reloj())

    def falla():
        raise error

    for _ in range(5):
        with pytest.raises(type(error)):
            c.llamar(falla)
    assert c.estado == C.CERRADO


@pytest.mark.parametrize("error,esperado", [
    (TimeoutError(), True), (ConnectionResetError(), True), (OperationalError("x", {}, Exception()), True),
    (PermissionError("solo lectura"), False), (F.OperacionNoPermitida("x"), False), (RuntimeError("x"), False)])
def test_clasificacion_de_fallas(error, esperado):
    assert C.es_falla_de_infraestructura(error) is esperado


def test_exito_intermedio_reinicia_la_cuenta():
    c = C.Circuito("prueba_cuenta", fallos_max=3, reinicio_s=60, reloj=Reloj())
    for _ in range(2):
        with pytest.raises(OperationalError):
            c.llamar(_caida)
    c.llamar(lambda: None)
    for _ in range(2):
        with pytest.raises(OperationalError):
            c.llamar(_caida)
    assert c.estado == C.CERRADO


def test_fuente_postgres_pasa_por_el_circuito_y_falla_rapido():
    motor = mock.MagicMock()
    motor.connect.side_effect = OperationalError("connect", {}, ConnectionRefusedError("refused"))
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://lector@host-falso/db", motor=motor)
    for _ in range(3):                                     # fuente_postgres: fallos_max=3 por omisión
        with pytest.raises(OperationalError):
            f.consultar("SELECT 1")
    with pytest.raises(C.CircuitoAbierto):
        f.consultar("SELECT 1")
    assert motor.connect.call_count == 3                   # abierto: ni siquiera se intenta conectar
    with pytest.raises(F.OperacionNoPermitida):            # el SQL prohibido se rechaza antes del circuito
        f.consultar("DELETE FROM rutas")
    assert C.estados()["fuente_postgres"]["estado"] == C.ABIERTO


def _motor_que_agota_el_tiempo():
    import psycopg.errors

    motor = mock.MagicMock()
    conexion = motor.connect.return_value.__enter__.return_value

    def ejecutar(sentencia, parametros=None):
        if "timbradas_segmentos" in str(sentencia):
            raise OperationalError("SELECT", {}, psycopg.errors.QueryCanceled("canceling statement due to statement "
                                                                              "timeout"))
        return mock.MagicMock()

    conexion.execute.side_effect = ejecutar
    return motor


def test_tiempo_agotado_abre_el_circuito_salvo_con_cancelacion_responde():
    """Por omisión un statement_timeout (QueryCanceled, SQLSTATE 57014) cuenta como falla de infraestructura, como
    siempre. Con cancelacion_responde=True (la fuente de la capa de segmentos, que parte la lectura) sube como
    SentenciaCancelada, con la excepción original en __cause__, y el circuito sigue cerrado."""
    sql = "SELECT 1 FROM timbradas_segmentos"
    partidora = F.FuentePostgresSoloLectura(url="postgresql+psycopg://l@h/db", motor=_motor_que_agota_el_tiempo(),
                                            tabla="timbradas_segmentos", cancelacion_responde=True)
    for _ in range(5):
        with pytest.raises(F.SentenciaCancelada) as error:
            partidora.consultar(sql)
        assert isinstance(error.value.__cause__, OperationalError) and "statement timeout" in str(error.value)
    assert C.estados()["fuente_postgres"]["estado"] == C.CERRADO
    normal = F.FuentePostgresSoloLectura(url="postgresql+psycopg://l@h/db", motor=_motor_que_agota_el_tiempo(),
                                         tabla="timbradas_segmentos")
    for _ in range(3):
        with pytest.raises(OperationalError):
            normal.consultar(sql)
    assert C.estados()["fuente_postgres"]["estado"] == C.ABIERTO


class _CorreoCaido(N.NotificadorCorreo):
    intentos = 0

    def _entregar(self, registro):
        type(self).intentos += 1
        raise ConnectionError("proveedor de correo caído")


ALERTA = {"id": "a1", "codigo": "ALT-002", "nombre": "Sobreocupación", "ruta": "CRA 54", "severidad": "critica"}


def test_notificador_registra_fallida_y_luego_omitida_por_circuito_abierto():
    n = _CorreoCaido(["despacho@example.com"])
    estados = [n.enviar(ALERTA)["estado"] for _ in range(7)]
    assert estados == ["fallida"] * 5 + ["omitida_circuito_abierto"] * 2   # notif_*: fallos_max=5
    assert _CorreoCaido.intentos == 5                     # con el circuito abierto ya no se intenta
    r = n.enviar(ALERTA)
    assert r["estado"] == "omitida_circuito_abierto" and "abierto" in r["error"] and r["alerta_id"] == "a1"
    assert C.estados()["notif_correo"]["estado"] == C.ABIERTO
    assert N.NotificadorWhatsApp(["+573001234567"]).enviar(ALERTA)["estado"] == "simulada"   # otro canal, otro circuito


def test_registro_expone_las_integraciones_conocidas():
    C.registrar_integraciones()
    assert set(C.estados()) >= {"fuente_postgres", "notif_correo", "notif_whatsapp"}
    assert all(v["estado"] == C.CERRADO for v in C.estados().values())
