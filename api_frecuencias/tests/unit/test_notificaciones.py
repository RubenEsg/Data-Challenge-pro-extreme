"""Pruebas de los notificadores simulados (correo y WhatsApp): configuración por entorno, filtro por severidad y
registro del envío. No hay red: se verifica con unittest.mock que no se abra ningún socket."""
import logging
import socket
from unittest import mock

import pytest

from app.servicios import notificaciones as N

ALERTA = {"id": "a1", "codigo": "ALT-002", "nombre": "Sobreocupación", "ruta": "CRA 54", "severidad": "critica",
          "explicacion": "La ocupación observada (95,0 %) supera el umbral crítico (90,0 %).",
          "recomendacion": "Programar un despacho adicional.", "clave_dedup": "ALT-002|CRA 54|-|-"}


def test_correo_simulado_devuelve_registro_y_escribe_log(caplog):
    n = N.NotificadorCorreo(["operaciones@sobusa.example", "jefe@sobusa.example"], severidad_minima="preventiva")
    with mock.patch.object(socket, "socket", side_effect=AssertionError("no debe abrir red")), \
            caplog.at_level(logging.INFO, logger="ai_frecuencias.notificaciones"):
        r = n.enviar(ALERTA)
    assert r["canal"] == "correo" and r["modo"] == "simulado" and r["estado"] == "simulada"
    assert r["alerta_id"] == "a1" and r["clave_dedup"] == ALERTA["clave_dedup"]
    assert "ALT-002" in r["asunto"] and "CRITICA" in r["asunto"] and r["simulado"] is True
    assert isinstance(r["mensaje"], str) and "Acción sugerida" in r["mensaje"]
    assert r["contenido"]["de"] == "alertas@ai-frecuencias.local"
    assert r["destinatarios"] == ["op***@sobusa.example", "je***@sobusa.example"]      # enmascarados
    assert r["destinatario"] == "op***@sobusa.example, je***@sobusa.example"
    assert "operaciones@" not in caplog.text and "simulada" in caplog.text


def test_whatsapp_simulado_recorta_el_texto():
    n = N.NotificadorWhatsApp(["+573001234567"])
    larga = dict(ALERTA, explicacion="x" * 3000)
    r = n.enviar(larga)
    assert r["canal"] == "whatsapp" and r["estado"] == "simulada"
    assert len(r["mensaje"]) <= N.NotificadorWhatsApp.LIMITE and r["asunto"] is None
    assert r["destinatarios"] == ["+573***67"]
    enviado = N.NotificadorWhatsApp(["+573001234567"]).enviar({"alert_id": "b2", "severidad": "critica"})
    assert enviado["alerta_id"] == "b2"


def test_filtro_por_severidad_y_sin_destinatarios():
    n = N.NotificadorCorreo(["a@b.co"], severidad_minima="critica")
    assert n.enviar(dict(ALERTA, severidad="preventiva"))["estado"] == "omitida"
    assert n.enviar(ALERTA)["estado"] == "simulada"
    assert N.NotificadorCorreo([]).enviar(ALERTA)["estado"] == "omitida"
    assert N.NotificadorCorreo(["a@b.co"], habilitado=False).enviar(ALERTA)["estado"] == "omitida"
    with pytest.raises(ValueError):
        N.NotificadorCorreo(["a@b.co"], severidad_minima="urgente")


def test_configuracion_desde_entorno():
    env = {"NOTIFICACIONES_CANALES": "correo, whatsapp", "NOTIFICACIONES_SEVERIDAD": "preventiva",
           "NOTIF_CORREO_DESTINATARIOS": "a@b.co,c@d.co", "NOTIF_CORREO_REMITENTE": "alertas@x.co",
           "NOTIF_WHATSAPP_NUMEROS": "+573001112233"}
    ns = N.notificadores_desde_entorno(env)
    assert [n.canal for n in ns] == ["correo", "whatsapp"]
    assert ns[0].destinatarios == ["a@b.co", "c@d.co"] and ns[0].remitente == "alertas@x.co"
    assert all(n.severidad_minima == "preventiva" for n in ns)
    registros = N.notificar(dict(ALERTA, severidad="preventiva"), ns)
    assert [r["estado"] for r in registros] == ["simulada", "simulada"]
    assert N.notificadores_desde_entorno({}) == []
    with pytest.raises(ValueError):
        N.notificadores_desde_entorno({"NOTIFICACIONES_CANALES": "telegram"})


# ---------------------------------------------------------------- §6.3 reporte de unicidad al responsable
def _error(codigo, fila, ruta="SILENCIO", hora=13):
    return {"lote": "abcd1234:2024-06-12", "fila": fila, "llave": {"ruta": ruta, "fecha": "2024-06-12", "hora": hora},
            "campo": "ruta", "codigo": codigo, "dimension": "unicidad" if codigo == "UNI-001" else "validez"}


ERRORES = [_error("UNI-001", 3), _error("VAL-001", 5), _error("UNI-001", 9), _error("UNI-001", 4, "CL 72", 7),
           _error("UNI-001", 8, "CL 72", 7), _error("UNI-001", 11, "CL 72", 7)]


def test_el_reporte_de_unicidad_agrupa_las_filas_por_llave_y_dice_que_no_se_corrigio():
    r = N.reporte_unicidad(ERRORES, "abcd1234:2024-06-12", "/api/v1/frequency/executions/x/errors?codigo=UNI-001")
    assert r["tipo"] == "reporte_unicidad" and r["codigo"] == "UNI-001" and r["corregido"] is False
    assert r["llaves_duplicadas"] == 2 and r["filas_duplicadas"] == 5 and not r["truncado"]
    assert r["duplicados"] == [{"llave": {"ruta": "SILENCIO", "fecha": "2024-06-12", "hora": 13}, "filas": [3, 9]},
                               {"llave": {"ruta": "CL 72", "fecha": "2024-06-12", "hora": 7}, "filas": [4, 8, 11]}]
    assert r["responsable"] == "responsable del consolidado" and "abcd1234:2024-06-12" in r["asunto"]
    assert "No se corrigió nada" in r["cuerpo"]
    assert "ruta=SILENCIO, fecha=2024-06-12, hora=13: filas 3, 9" in r["cuerpo"]
    assert r["cuerpo"].endswith("errors?codigo=UNI-001")
    assert N.reporte_unicidad([_error("VAL-001", 5)], "lote") is None and N.reporte_unicidad(None, "lote") is None


def test_el_reporte_lista_hasta_el_limite_de_llaves():
    muchas = [_error("UNI-001", i, hora=i) for i in range(N.LIMITE_LLAVES_REPORTE + 3) for _ in (0, 1)]
    r = N.reporte_unicidad(muchas, "lote")
    assert r["llaves_duplicadas"] == N.LIMITE_LLAVES_REPORTE + 3 and r["truncado"]
    assert len(r["duplicados"]) == N.LIMITE_LLAVES_REPORTE and "… y 3 llaves más" in r["cuerpo"]


def test_sin_destinatario_el_reporte_queda_pendiente_y_con_destinatario_se_simula(caplog):
    reporte = N.reporte_unicidad(ERRORES, "abcd1234:2024-06-12")
    pendiente = N.enviar_reporte_unicidad(reporte, env={})
    assert pendiente["estado"] == N.ESTADO_PENDIENTE_DESTINATARIO and pendiente["destinatarios"] == []
    assert pendiente["canal"] == "correo" and pendiente["tipo"] == "reporte_unicidad"
    assert pendiente["lote"] == "abcd1234:2024-06-12" and pendiente["asunto"] == reporte["asunto"]
    with mock.patch.object(socket, "socket", side_effect=AssertionError("no debe abrir red")), \
            caplog.at_level(logging.INFO, logger="ai_frecuencias.notificaciones"):
        enviado = N.enviar_reporte_unicidad(reporte, env={"NOTIF_UNICIDAD_DESTINATARIOS": "consolidado@extreme.example",
                                                          "NOTIF_CORREO_REMITENTE": "calidad@x.co"})
    assert enviado["estado"] == "simulada" and enviado["destinatarios"] == ["co***@extreme.example"]
    assert enviado["contenido"]["de"] == "calidad@x.co" and enviado["mensaje"] == reporte["cuerpo"]
    assert "consolidado@" not in caplog.text
