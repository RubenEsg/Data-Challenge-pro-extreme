"""Notificación de alertas por correo y WhatsApp (envío SIMULADO: solo registro en el log).

Configuración por variables de entorno (ninguna es secreta; no hay credenciales de envío en el repositorio):
  NOTIFICACIONES_CANALES      canales activos separados por coma: correo,whatsapp (vacío = ninguno)
  NOTIFICACIONES_SEVERIDAD    severidad mínima que se notifica: informativa | preventiva | critica (por defecto critica)
  NOTIF_CORREO_DESTINATARIOS  correos separados por coma
  NOTIF_CORREO_REMITENTE      remitente (por defecto alertas@ai-frecuencias.local)
  NOTIF_WHATSAPP_NUMEROS      números E.164 separados por coma
El modo es siempre «simulado»: se arma el mensaje, se escribe en el log (con los destinatarios enmascarados) y se
devuelve un registro para guardar en la bitácora de la ejecución. Un envío real se conectaría aquí con el proveedor.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

log = logging.getLogger("ai_frecuencias.notificaciones")

ORDEN_SEVERIDAD = {"informativa": 0, "preventiva": 1, "critica": 2}


def _lista(valor):
    return [x.strip() for x in (valor or "").split(",") if x.strip()]


def _enmascarar(destino):
    destino = str(destino)
    if "@" in destino:
        usuario, dominio = destino.split("@", 1)
        return (usuario[:2] + "***@" + dominio) if usuario else "***@" + dominio
    return destino[:4] + "***" + destino[-2:] if len(destino) > 6 else "***"


def _texto(alerta):
    ruta = alerta.get("ruta") or "-"
    return (f"[{alerta.get('codigo')}] {alerta.get('nombre', '')} - ruta {ruta} - severidad {alerta.get('severidad')}. "
            f"{alerta.get('explicacion', '')} Acción sugerida: {alerta.get('recomendacion', '')}")


class _Notificador:
    canal = "base"
    modo = "simulado"

    def __init__(self, destinatarios=None, severidad_minima="critica", habilitado=True):
        if severidad_minima not in ORDEN_SEVERIDAD:
            raise ValueError(f"severidad_minima inválida: {severidad_minima!r}.")
        self.destinatarios = list(destinatarios or [])
        self.severidad_minima = severidad_minima
        self.habilitado = bool(habilitado)

    def debe_notificar(self, alerta):
        sev = ORDEN_SEVERIDAD.get(alerta.get("severidad"), -1)
        return self.habilitado and bool(self.destinatarios) and sev >= ORDEN_SEVERIDAD[self.severidad_minima]

    def _mensaje(self, alerta):
        raise NotImplementedError

    def enviar(self, alerta):
        """Simula el envío y devuelve el registro (canal, destinatarios enmascarados, mensaje, estado, fecha)."""
        if not self.debe_notificar(alerta):
            estado = "omitida"
        else:
            estado = "simulada"
        contenido = self._mensaje(alerta)
        destinatarios = [_enmascarar(d) for d in self.destinatarios]
        registro = {
            "canal": self.canal,
            "modo": self.modo,
            "simulado": True,
            "estado": estado,
            "alerta_id": alerta.get("id") or alerta.get("alert_id"),
            "codigo": alerta.get("codigo"),
            "clave_dedup": alerta.get("clave_dedup"),
            "severidad": alerta.get("severidad"),
            "destinatarios": destinatarios,
            "destinatario": ", ".join(destinatarios) or None,
            "asunto": contenido.get("asunto"),
            "mensaje": contenido.get("cuerpo") or contenido.get("texto"),     # texto plano (columna Text)
            "contenido": contenido,
            "fecha": datetime.now(UTC),
        }
        if estado == "simulada":
            # RNF-010: la entrega pasa por el circuit breaker del canal. Abierto -> no se intenta y la notificación
            # queda registrada como omitida (la alerta ya está en la base); un fallo de red queda como «fallida».
            from app.servicios import circuito

            try:
                circuito.obtener(f"notif_{self.canal}").llamar(self._entregar, registro)
            except circuito.CircuitoAbierto as exc:
                registro.update(estado="omitida_circuito_abierto", error=str(exc))
                log.warning("Notificación %s omitida: %s", self.canal, exc)
            except Exception as exc:  # noqa: BLE001 - un canal caído no detiene la ejecución ni pierde el registro
                registro.update(estado="fallida", error=f"{type(exc).__name__}: {exc}"[:300])
                log.warning("Notificación %s fallida: %s", self.canal, registro["error"])
        return registro

    def _entregar(self, registro):
        """Entrega al proveedor. En modo simulado solo escribe el log (destinatarios enmascarados)."""
        log.info("Notificación %s simulada para %s: %s", self.canal, registro["destinatarios"], registro["codigo"])


class NotificadorCorreo(_Notificador):
    canal = "correo"

    def __init__(self, destinatarios=None, remitente=None, severidad_minima="critica", habilitado=True):
        super().__init__(destinatarios, severidad_minima, habilitado)
        self.remitente = remitente or "alertas@ai-frecuencias.local"

    def _mensaje(self, alerta):
        return {"de": self.remitente,
                "asunto": f"[{(alerta.get('severidad') or '').upper()}] {alerta.get('codigo')} "
                          f"{alerta.get('nombre', '')} - {alerta.get('ruta') or '-'}",
                "cuerpo": _texto(alerta)}


class NotificadorWhatsApp(_Notificador):
    canal = "whatsapp"
    LIMITE = 1000            # los mensajes de WhatsApp se recortan

    def _mensaje(self, alerta):
        t = _texto(alerta)
        return {"texto": t if len(t) <= self.LIMITE else t[: self.LIMITE - 1] + "…"}


def notificadores_desde_entorno(env=None):
    """Instancia los notificadores activos según las variables de entorno (modo simulado)."""
    env = os.environ if env is None else env
    canales = [c.lower() for c in _lista(env.get("NOTIFICACIONES_CANALES"))]
    sev = (env.get("NOTIFICACIONES_SEVERIDAD") or "critica").strip().lower()
    salida = []
    for c in canales:
        if c == "correo":
            salida.append(NotificadorCorreo(_lista(env.get("NOTIF_CORREO_DESTINATARIOS")),
                                            env.get("NOTIF_CORREO_REMITENTE") or None, sev))
        elif c == "whatsapp":
            salida.append(NotificadorWhatsApp(_lista(env.get("NOTIF_WHATSAPP_NUMEROS")), sev))
        else:
            raise ValueError(f"Canal de notificación desconocido: {c!r} (use correo o whatsapp).")
    return salida


def notificar(alerta, notificadores):
    """Envía (simulado) la alerta por cada notificador y devuelve los registros."""
    return [n.enviar(alerta) for n in notificadores]
