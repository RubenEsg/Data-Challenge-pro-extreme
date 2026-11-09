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
