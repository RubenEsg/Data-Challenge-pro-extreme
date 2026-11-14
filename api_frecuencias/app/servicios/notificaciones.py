"""Notificación de alertas por correo y WhatsApp y reporte de calidad al responsable del consolidado (envío
SIMULADO: solo registro en el log y en notification_log).

Configuración por variables de entorno (ninguna es secreta; no hay credenciales de envío en el repositorio):
  NOTIFICACIONES_CANALES      canales activos separados por coma: correo,whatsapp (vacío = ninguno)
  NOTIFICACIONES_SEVERIDAD    severidad mínima que se notifica: informativa | preventiva | critica (por defecto critica)
  NOTIF_CORREO_DESTINATARIOS  correos separados por coma
  NOTIF_CORREO_REMITENTE      remitente (por defecto alertas@ai-frecuencias.local)
  NOTIF_WHATSAPP_NUMEROS      números E.164 separados por coma
  NOTIF_UNICIDAD_DESTINATARIOS  correos del responsable del consolidado para el reporte de duplicados del lote (§6.3).
                              Vacío por omisión: el responsable lo define Extreme (§19, responsables técnicos); sin él,
                              el reporte queda registrado en notification_log con estado «pendiente_destinatario».
El modo es siempre «simulado»: se arma el mensaje, se escribe en el log (con los destinatarios enmascarados) y se
devuelve un registro para guardar en la bitácora de la ejecución. Un envío real se conectaría aquí con el proveedor.

§6.3 «Unicidad: reportar al responsable del consolidado; no corregir directamente»: reporte_unicidad arma, con los
errores UNI-001 de un lote, el reporte de las llaves duplicadas (cada llave con sus filas del lote) y
enviar_reporte_unicidad lo manda por el canal de correo existente (NotificadorReporteCalidad). La calidad no corrige
nada: las filas del grupo duplicado se rechazan del análisis y del histórico, y el reporte lo dice.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

log = logging.getLogger("ai_frecuencias.notificaciones")

ORDEN_SEVERIDAD = {"informativa": 0, "preventiva": 1, "critica": 2}
CODIGO_UNICIDAD = "UNI-001"
ESTADO_PENDIENTE_DESTINATARIO = "pendiente_destinatario"
RESPONSABLE_CONSOLIDADO = "responsable del consolidado"
LIMITE_LLAVES_REPORTE = 200          # llaves listadas en el reporte (el total siempre va completo)


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


# ---------------------------------------------------------------- §6.3 reporte de unicidad del lote
class NotificadorReporteCalidad(NotificadorCorreo):
    """Correo (simulado) de un reporte de calidad al responsable del consolidado. Sin destinatario el reporte no se
    pierde: queda registrado en notification_log con estado «pendiente_destinatario» (consultable, con el reporte
    completo en el detalle). No se reenvía solo: los reportes de los lotes siguientes salen al destinatario cuando
    Extreme lo defina (NOTIF_UNICIDAD_DESTINATARIOS)."""

    def __init__(self, destinatarios=None, remitente=None):
        super().__init__(destinatarios, remitente, severidad_minima="informativa")

    def _mensaje(self, reporte):
        return {"de": self.remitente, "asunto": reporte["asunto"], "cuerpo": reporte["cuerpo"]}

    def enviar(self, reporte):
        registro = super().enviar(reporte)
        if not self.destinatarios:
            registro["estado"] = ESTADO_PENDIENTE_DESTINATARIO
        registro.update(tipo=reporte["tipo"], responsable=RESPONSABLE_CONSOLIDADO, lote=reporte["lote"])
        return registro


def _grupos_duplicados(errores) -> list[dict]:
    """Llaves duplicadas (UNI-001) con las filas del lote de cada una, en orden de primera aparición."""
    grupos: dict[str, dict] = {}
    for e in errores:
        if e.get("codigo") != CODIGO_UNICIDAD:
            continue
        llave = e.get("llave") or {}
        grupo = grupos.setdefault(json.dumps(llave, sort_keys=True, default=str), {"llave": llave, "filas": []})
        grupo["filas"].append(e.get("fila"))
    return list(grupos.values())


def _llaves(n: int) -> str:
    return f"{n} llave duplicada" if n == 1 else f"{n} llaves duplicadas"


def _texto_reporte(lote: str, grupos: list[dict], filas: int) -> str:
    lineas = [f"Lote {lote}: {_llaves(len(grupos))} (llave natural) en {filas} filas (UNI-001, §6.3).",
              "No se corrigió nada: las filas de cada llave duplicada se rechazaron del análisis y del histórico; "
              "corrija el consolidado en la fuente y la ejecución siguiente las leerá de nuevo.", ""]
    for g in grupos[:LIMITE_LLAVES_REPORTE]:
        llave = ", ".join(f"{k}={v}" for k, v in g["llave"].items())
        lineas.append(f"- {llave}: filas {', '.join(str(f) for f in g['filas'])} del lote")
    if len(grupos) > LIMITE_LLAVES_REPORTE:
        lineas.append(f"… y {len(grupos) - LIMITE_LLAVES_REPORTE} llaves más (consulte el lote en la API).")
    return "\n".join(lineas)


def reporte_unicidad(errores, lote: str, consulta: str | None = None) -> dict | None:
    """§6.3: el reporte de las llaves duplicadas del lote para el responsable del consolidado; None si el lote no tiene
    errores UNI-001. Cada llave va con sus filas del lote; `consulta` es la ruta de la API que lista los errores."""
    grupos = _grupos_duplicados(errores or [])
    if not grupos:
        return None
    filas = sum(len(g["filas"]) for g in grupos)
    cuerpo = _texto_reporte(lote, grupos, filas)
    if consulta:
        cuerpo += f"\n\nDetalle por fila y causa: {consulta}"
    return {"tipo": "reporte_unicidad", "codigo": CODIGO_UNICIDAD, "severidad": "informativa", "lote": lote,
            "responsable": RESPONSABLE_CONSOLIDADO, "llaves_duplicadas": len(grupos), "filas_duplicadas": filas,
            "duplicados": grupos[:LIMITE_LLAVES_REPORTE], "truncado": len(grupos) > LIMITE_LLAVES_REPORTE,
            "corregido": False, "consulta": consulta,
            "asunto": f"[CALIDAD §6.3] {_llaves(len(grupos))} en el lote {lote}", "cuerpo": cuerpo}


def enviar_reporte_unicidad(reporte: dict, env=None) -> dict:
    """Envía (simulado) el reporte por correo a NOTIF_UNICIDAD_DESTINATARIOS; sin destinatario, el registro queda
    «pendiente_destinatario». Devuelve el registro para notification_log."""
    env = os.environ if env is None else env
    notificador = NotificadorReporteCalidad(_lista(env.get("NOTIF_UNICIDAD_DESTINATARIOS")),
                                            env.get("NOTIF_CORREO_REMITENTE") or None)
    return notificador.enviar(reporte)
