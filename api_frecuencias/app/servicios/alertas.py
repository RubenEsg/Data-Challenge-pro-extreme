"""Motor de reglas de alertas ALT-001..ALT-010 (especificación v1.5, §5) y máquina de estados de una alerta.

Funciones puras: no leen ni escriben la base; el orquestador (ejecucion.py) guarda las alertas y su historial.

contexto (claves usadas; las ausentes desactivan la regla que las necesita):
  ruta, empresa, sentido, viaje, conductor, vehiculo, detectada_en, ventana_inicio, ventana_fin, horizonte_min
  demanda_prevista, p10, p90                      pronóstico puntual e intervalo (pasajeros en la ventana)
  pasajeros_observados, demanda_patron            demanda real consolidada y patrón histórico (p. ej. regla B1)
  capacidad                                       puestos por bus (50 en el proyecto)
  buses_hora_actual, buses_hora_recomendado       oferta vigente y la de optimizacion.recomendar()
  ocupacion_esperada, ocupacion_observada         fracciones (0..1); si falta la esperada se calcula
  salidas_esperadas, salidas_observadas, minutos_desde_ultimo_despacho, headway_programado_min
  consolidado: {subidas, bajadas, nro_viajes, referencia: {campo: (media, desviacion)}}
  minutos_sin_datos, campos_faltantes             frescura e integridad del dato
  wape_movil                                      métrica móvil del modelo frente a lo observado (fracción)
umbrales: los parámetros de §5.1 (UMBRALES_POR_DEFECTO); los que se pasen reemplazan a los de por defecto.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

# Parámetros de §5.1 (valores iniciales sugeridos) y los complementarios que necesita cada regla (documentados).
UMBRALES_POR_DEFECTO = {
    "version": "umbrales-v1",
    "ocupacion_objetivo_min": 0.65,     # §5.1 ocupación objetivo 65 % a 85 %
    "ocupacion_objetivo_max": 0.85,
    "ocupacion_critica": 0.90,          # §5.1 ≥ 90 %
    "baja_utilizacion": 0.30,           # §5.1 < 30 %
    "espera_max_min": 5.0,              # §5.1 espera máxima entre despachos
    "error_pronostico": 0.15,           # §5.1 ≥ 15 %
    "periodos_atraso": 2,               # §5.1 datos atrasados: 2 períodos de ingesta
    "periodo_ingesta_min": 60.0,        # período de ingesta del ciclo (configurable; diario = 1440)
    "caida_demanda": 0.30,              # ALT-005: caída relativa frente al patrón
    "demanda_minima_patron": 10.0,      # ALT-005: no se evalúa con patrones muy bajos (ruido)
    "tolerancia_despacho_min": 5.0,     # ALT-006: minutos de tolerancia sobre el headway programado
    "tolerancia_salidas": 0.20,         # ALT-006: déficit relativo de salidas tolerado
    "z_anomalia": 3.0,                  # ALT-008: |z| del consolidado frente a su referencia
    "wape_max": 0.20,                   # ALT-010: tolerancia del WAPE móvil (≈ WAPE de la regla manual B1, 20,04 %)
}

CATALOGO = {
    "ALT-001": ("Alta demanda prevista", "Aumentar buses por hora o reducir el headway."),
    "ALT-002": ("Sobreocupación", "Programar un despacho adicional y hacer seguimiento a la ocupación."),
    "ALT-003": ("Frecuencia insuficiente", "Aplicar el intervalo recomendado."),
    "ALT-004": ("Frecuencia excesiva", "Evaluar ampliar el intervalo entre despachos."),
    "ALT-005": ("Caída anormal de demanda", "Validar si hay un evento, un problema en la ruta o una falla de captura."),
    "ALT-006": ("Despacho ausente o tardío", "Verificar la disponibilidad del vehículo y la operación del despacho."),
    "ALT-007": ("Desviación del pronóstico", "Revisar la frecuencia y recalibrar el escenario del pronóstico."),
    "ALT-008": ("Consolidado anómalo", "Validar la fuente, el trigger de consolidación y el período afectado."),
    "ALT-009": ("Datos incompletos", "Reprocesar el lote o restablecer la fuente de datos."),
    "ALT-010": ("Modelo degradado", "Suspender la versión del modelo o reentrenarlo."),
}

ESTADOS_ABIERTOS = ("nueva", "reconocida", "asignada")
ESTADOS_FINALES = ("cerrada", "descartada")
# nueva -> reconocida -> asignada -> cerrada | descartada; descartar se permite en cualquier estado abierto (falsa alarma)
# y asignar desde asignada es una reasignación. comentar no cambia el estado y se permite en cualquier estado abierto.
TRANSICIONES = {
    "nueva": {"reconocer": "reconocida", "descartar": "descartada"},
    "reconocida": {"asignar": "asignada", "descartar": "descartada"},
    "asignada": {"asignar": "asignada", "cerrar": "cerrada", "descartar": "descartada"},
    "cerrada": {},
    "descartada": {},
}
ACCIONES = ("reconocer", "asignar", "comentar", "cerrar", "descartar")


class TransicionInvalida(ValueError):
    """Acción no permitida desde el estado actual de la alerta."""


def _ahora():
    return datetime.now(UTC)


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else (None if v is None else str(v))


def _f(x, d=1):
    if x is None:
        return "—"
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x):
    return "—" if x is None else _f(100 * x, 1) + " %"


def _puntaje(observado, umbral, mayor=True):
    """0,5 justo en el umbral y 1,0 cuando el exceso relativo frente al umbral llega a 100 %."""
    try:
        base = abs(float(umbral)) if umbral else 1.0
        exceso = (float(observado) - float(umbral)) / base if mayor else (float(umbral) - float(observado)) / base
    except (TypeError, ValueError):
        return 0.5
    return round(0.5 + 0.5 * min(max(exceso, 0.0), 1.0), 3)


def clave_dedup(codigo, ruta, ventana_inicio, ventana_fin):
    """Clave de deduplicación: código + ruta + ventana analizada."""
    return f"{codigo}|{ruta or '-'}|{_iso(ventana_inicio) or '-'}|{_iso(ventana_fin) or '-'}"


def _alerta(ctx, u, codigo, severidad, observado, esperado, umbral, puntaje, explicacion, variables):
    nombre, recomendacion = CATALOGO[codigo]
    return {
        "id": str(uuid.uuid4()),
        "codigo": codigo,
        "nombre": nombre,
        "empresa": ctx.get("empresa"),
        "ruta": ctx.get("ruta"),
        "sentido": ctx.get("sentido"),
        "viaje": ctx.get("viaje"),
        "conductor": ctx.get("conductor"),
        "vehiculo": ctx.get("vehiculo"),
        "detectada_en": ctx.get("detectada_en") or _ahora(),
        "ventana_inicio": ctx.get("ventana_inicio"),
        "ventana_fin": ctx.get("ventana_fin"),
        "horizonte_min": ctx.get("horizonte_min"),
        "severidad": severidad,
        "estado": "nueva",
        "observado": None if observado is None else round(float(observado), 4),
        "esperado": None if esperado is None else round(float(esperado), 4),
        "umbral": None if umbral is None else round(float(umbral), 4),
        "puntaje": puntaje,
        "explicacion": explicacion,
        "variables": variables,
        "recomendacion": recomendacion,
        "asignado_a": None,
        "comentarios": [],
        "historial": [],
        "version_umbrales": u.get("version"),
        "clave_dedup": clave_dedup(codigo, ctx.get("ruta"), ctx.get("ventana_inicio"), ctx.get("ventana_fin")),
    }


def _capacidad_actual(ctx):
    b, c = ctx.get("buses_hora_actual"), ctx.get("capacidad")
    if b is None or c is None:
        return None
    return float(b) * float(c)


def _ocupacion_esperada(ctx):
    if ctx.get("ocupacion_esperada") is not None:
        return float(ctx["ocupacion_esperada"])
    cap, d = _capacidad_actual(ctx), ctx.get("demanda_prevista")
    if cap and d is not None:
        return float(d) / cap
    return None


# ---------------------------------------------------------------- reglas
def _alt001(ctx, u):
    cap = _capacidad_actual(ctx)
    d, p90 = ctx.get("demanda_prevista"), ctx.get("p90")
    proy = p90 if p90 is not None else d
    if cap is None or proy is None or float(proy) <= cap:
        return None
    critica = d is not None and float(d) > cap
    sev = "critica" if critica else "preventiva"
    expl = (f"La demanda proyectada ({'P90 ' if p90 is not None else ''}{_f(proy)} pasajeros) supera la capacidad disponible "
            f"({_f(cap, 0)} = {_f(ctx['buses_hora_actual'], 0)} buses/h × {_f(ctx['capacidad'], 0)} puestos)"
            + (f"; incluso el pronóstico puntual ({_f(d)}) la supera." if critica else "; el pronóstico puntual "
               f"({_f(d)}) aún cabe, el riesgo está en el intervalo superior."))
    return _alerta(ctx, u, "ALT-001", sev, proy, d, cap, _puntaje(proy, cap), expl,
                   {"p90": p90, "demanda_prevista": d, "buses_hora_actual": ctx.get("buses_hora_actual"),
                    "capacidad": ctx.get("capacidad")})


def _alt002(ctx, u):
    crit = float(u["ocupacion_critica"])
    esp, obs = _ocupacion_esperada(ctx), ctx.get("ocupacion_observada")
    candidatos = [(v, n) for v, n in ((obs, "observada"), (esp, "esperada")) if v is not None]
    if not candidatos:
        return None
    valor, tipo = max(candidatos, key=lambda t: float(t[0]))
    if float(valor) < crit:
        return None
    expl = (f"La ocupación {tipo} ({_pct(valor)}) alcanza o supera el umbral crítico ({_pct(crit)}). "
            f"Esperada: {_pct(esp)}; observada: {_pct(obs)}.")
    return _alerta(ctx, u, "ALT-002", "critica", valor, esp, crit, _puntaje(valor, crit), expl,
                   {"ocupacion_esperada": esp, "ocupacion_observada": obs, "demanda_prevista": ctx.get("demanda_prevista"),
                    "buses_hora_actual": ctx.get("buses_hora_actual")})


def _alt003(ctx, u):
    act, rec = ctx.get("buses_hora_actual"), ctx.get("buses_hora_recomendado")
    if act is None or rec is None or float(act) >= float(rec):
        return None
    h_act = 60.0 / float(act) if float(act) > 0 else None
    h_rec = 60.0 / float(rec)
    expl = (f"La frecuencia actual ({_f(act, 1)} buses/h, cada {_f(h_act, 1)} min) no cubre la demanda con el nivel de "
            f"servicio: se recomiendan {_f(rec, 0)} buses/h (cada {_f(h_rec, 1)} min).")
    return _alerta(ctx, u, "ALT-003", "preventiva", act, rec, rec, _puntaje(rec, act if float(act) > 0 else 1), expl,
                   {"buses_hora_actual": act, "buses_hora_recomendado": rec, "headway_actual_min": h_act,
                    "headway_recomendado_min": h_rec, "demanda_prevista": ctx.get("demanda_prevista"), "p90": ctx.get("p90")})


def _alt004(ctx, u):
    minimo = float(u["baja_utilizacion"])
    esp = _ocupacion_esperada(ctx)
    if esp is None or esp >= minimo:
        return None
    act, rec = ctx.get("buses_hora_actual"), ctx.get("buses_hora_recomendado")
    if act is not None and rec is not None and float(act) <= float(rec):
        return None          # ya está en la oferta mínima recomendada: no hay intervalo que ampliar
    expl = (f"La ocupación prevista ({_pct(esp)}) está por debajo del mínimo de utilización ({_pct(minimo)}) con "
            f"{_f(act, 1)} buses/h" + (f"; la recomendación es {_f(rec, 0)} buses/h." if rec is not None else "."))
    return _alerta(ctx, u, "ALT-004", "informativa", esp, minimo, minimo, _puntaje(esp, minimo, mayor=False), expl,
                   {"ocupacion_esperada": esp, "buses_hora_actual": act, "buses_hora_recomendado": rec,
                    "demanda_prevista": ctx.get("demanda_prevista")})


def _alt005(ctx, u):
    obs = ctx.get("pasajeros_observados")
    patron = ctx.get("demanda_patron", ctx.get("demanda_prevista"))
    if obs is None or patron is None or float(patron) < float(u["demanda_minima_patron"]):
        return None
    limite = float(patron) * (1 - float(u["caida_demanda"]))
    if float(obs) >= limite:
        return None
    caida = 1 - float(obs) / float(patron)
    expl = (f"La demanda real ({_f(obs)} pasajeros) cae {_pct(caida)} frente al patrón histórico ({_f(patron)}); "
            f"el umbral de caída es {_pct(u['caida_demanda'])} (límite {_f(limite)}).")
    return _alerta(ctx, u, "ALT-005", "preventiva", obs, patron, limite, _puntaje(obs, limite, mayor=False), expl,
                   {"pasajeros_observados": obs, "demanda_patron": patron, "caida_relativa": round(caida, 4)})


def _alt006(ctx, u):
    tol = float(u["tolerancia_despacho_min"])
    hprog = ctx.get("headway_programado_min") or u["espera_max_min"]
    minutos = ctx.get("minutos_desde_ultimo_despacho")
    esp, obs = ctx.get("salidas_esperadas"), ctx.get("salidas_observadas")
    por_tiempo = minutos is not None and float(minutos) > float(hprog) + tol
    deficit = (float(esp) - float(obs)) if (esp is not None and obs is not None) else 0.0
    por_conteo = esp is not None and obs is not None and float(esp) > 0 and deficit >= 1 and \
        deficit / float(esp) > float(u["tolerancia_salidas"])
    if not (por_tiempo or por_conteo):
        return None
    partes = []
    if por_tiempo:
        partes.append(f"van {_f(minutos, 0)} min sin despacho, más que el headway programado ({_f(hprog, 1)} min) "
                      f"más la tolerancia ({_f(tol, 0)} min)")
    if por_conteo:
        partes.append(f"salieron {_f(obs, 0)} de {_f(esp, 0)} despachos esperados (déficit {_pct(deficit / float(esp))}, "
                      f"tolerancia {_pct(u['tolerancia_salidas'])})")
    if por_tiempo:
        observado, esperado, umbral = minutos, hprog, float(hprog) + tol
        puntaje = _puntaje(minutos, umbral)
    else:
        observado, esperado = obs, esp
        umbral = float(esp) * (1 - float(u["tolerancia_salidas"]))
        puntaje = _puntaje(obs, umbral if umbral > 0 else 1, mayor=False)
    return _alerta(ctx, u, "ALT-006", "critica", observado, esperado, umbral, puntaje,
                   "Despacho ausente o tardío: " + "; ".join(partes) + ".",
                   {"minutos_desde_ultimo_despacho": minutos, "headway_programado_min": hprog,
                    "salidas_esperadas": esp, "salidas_observadas": obs})


def _alt007(ctx, u):
    obs, d = ctx.get("pasajeros_observados"), ctx.get("demanda_prevista")
    p10, p90 = ctx.get("p10"), ctx.get("p90")
    if obs is None or d is None:
        return None
    err = abs(float(obs) - float(d)) / max(float(d), 1.0)
    if err < float(u["error_pronostico"]):
        return None
    if p10 is not None and p90 is not None and float(p10) <= float(obs) <= float(p90):
        return None          # el error es grande pero lo real cayó dentro del intervalo estimado
    lado = "por encima" if float(obs) > float(d) else "por debajo"
    intervalo = f"[{_f(p10)}, {_f(p90)}]" if p10 is not None and p90 is not None else "sin intervalo"
    expl = (f"La demanda real ({_f(obs)}) quedó {lado} del pronóstico ({_f(d)}), con un error de {_pct(err)} "
            f"(umbral {_pct(u['error_pronostico'])}) y fuera del intervalo P10-P90 {intervalo}.")
    return _alerta(ctx, u, "ALT-007", "preventiva", obs, d, u["error_pronostico"], _puntaje(err, u["error_pronostico"]),
                   expl, {"pasajeros_observados": obs, "demanda_prevista": d, "p10": p10, "p90": p90,
                          "error_relativo": round(err, 4)})


def _alt008(ctx, u):
    cons = ctx.get("consolidado") or {}
    ref = cons.get("referencia") or {}
    zmax, peor, hallazgos = 0.0, None, []
    for campo in ("subidas", "bajadas", "nro_viajes"):
        v, r = cons.get(campo), ref.get(campo)
        if v is None or not r:
            continue
        media, desv = float(r[0]), float(r[1])
        if desv <= 0:
            continue
        z = (float(v) - media) / desv
        if abs(z) >= float(u["z_anomalia"]):
            hallazgos.append(f"{campo} = {_f(v, 0)} frente a una media de {_f(media, 1)} (z = {_f(z, 2)})")
        if abs(z) > abs(zmax):
            zmax, peor = z, (campo, v, media)
    sin_viajes = cons.get("nro_viajes") is not None and float(cons["nro_viajes"]) == 0 and \
        float(cons.get("subidas") or 0) > 0
    if sin_viajes:
        hallazgos.append(f"hay {_f(cons['subidas'], 0)} subidas con nro_viajes = 0")
    if not hallazgos:
        return None
    campo, v, media = peor if peor else ("nro_viajes", cons.get("nro_viajes"), None)
    expl = "Consolidado atípico: " + "; ".join(hallazgos) + f" (umbral |z| ≥ {_f(u['z_anomalia'], 1)})."
    return _alerta(ctx, u, "ALT-008", "preventiva", v, media, u["z_anomalia"],
                   _puntaje(abs(zmax), u["z_anomalia"]) if peor and abs(zmax) >= float(u["z_anomalia"]) else 1.0, expl,
                   {"campo": campo, "z_maximo": round(zmax, 3), "subidas": cons.get("subidas"),
                    "bajadas": cons.get("bajadas"), "nro_viajes": cons.get("nro_viajes")})


def _alt009(ctx, u):
    faltan = list(ctx.get("campos_faltantes") or [])
    minutos = ctx.get("minutos_sin_datos")
    limite = float(u["periodos_atraso"]) * float(u["periodo_ingesta_min"])
    atrasado = minutos is not None and float(minutos) >= limite
    if not faltan and not atrasado:
        return None
    partes = []
    if atrasado:
        partes.append(f"llevan {_f(minutos, 0)} min sin recibir datos (umbral: {_f(u['periodos_atraso'], 0)} períodos de "
                      f"ingesta = {_f(limite, 0)} min)")
    if faltan:
        partes.append("faltan campos obligatorios: " + ", ".join(map(str, faltan)))
    return _alerta(ctx, u, "ALT-009", "critica", minutos if atrasado else len(faltan),
                   u["periodo_ingesta_min"] if atrasado else 0, limite if atrasado else 0,
                   _puntaje(minutos, limite) if atrasado else 1.0, "Datos incompletos o retrasados: " + "; ".join(partes) + ".",
                   {"minutos_sin_datos": minutos, "campos_faltantes": faltan, "periodo_ingesta_min": u["periodo_ingesta_min"]})


def _alt010(ctx, u):
    w = ctx.get("wape_movil")
    tol = float(u["wape_max"])
    if w is None or float(w) <= tol:
        return None
    expl = (f"El WAPE móvil del modelo ({_pct(w)}) supera la tolerancia ({_pct(tol)}) frente a las observaciones"
            + (f" del modelo {ctx['model_id']}." if ctx.get("model_id") else "."))
    return _alerta(ctx, u, "ALT-010", "critica", w, tol, tol, _puntaje(w, tol), expl,
                   {"wape_movil": w, "model_id": ctx.get("model_id")})


REGLAS = {"ALT-001": _alt001, "ALT-002": _alt002, "ALT-003": _alt003, "ALT-004": _alt004, "ALT-005": _alt005,
          "ALT-006": _alt006, "ALT-007": _alt007, "ALT-008": _alt008, "ALT-009": _alt009, "ALT-010": _alt010}


def evaluar_alertas(contexto, umbrales=None):
    """Evalúa las diez reglas sobre `contexto` con `umbrales` (§5.1) y devuelve las alertas disparadas (estructura §5.3),
    a lo sumo una por código; cada una con su clave_dedup (código + ruta + ventana)."""
    u = dict(UMBRALES_POR_DEFECTO)
    u.update({k: v for k, v in (umbrales or {}).items() if v is not None})
    ctx = dict(contexto or {})
    ctx.setdefault("detectada_en", _ahora())
    salida = []
    for regla in REGLAS.values():
        a = regla(ctx, u)
        if a is not None:
            salida.append(a)
    return salida


def deduplicar(alertas, claves_existentes=()):
    """Quita las alertas cuya clave_dedup ya existe (abiertas en la base) o se repite dentro de la lista."""
    vistas = set(claves_existentes or ())
    salida = []
    for a in alertas:
        if a["clave_dedup"] in vistas:
            continue
        vistas.add(a["clave_dedup"])
        salida.append(a)
    return salida


def _estado_de(alerta):
    if isinstance(alerta, str):
        return alerta
    if isinstance(alerta, dict):
        return alerta.get("estado")
    return getattr(alerta, "estado", None)


def _id_de(alerta):
    if isinstance(alerta, dict):
        return alerta.get("id")
    return getattr(alerta, "id", None)


def cambiar_estado(alerta, accion, usuario, comentario=None, asignado_a=None):
    """Aplica `accion` (reconocer|asignar|comentar|cerrar|descartar) y devuelve (estado_nuevo, entrada_historial).

    No modifica `alerta` (dict, objeto con .estado o el estado como texto). Lanza TransicionInvalida si la acción no está
    permitida desde el estado actual y ValueError si faltan datos (usuario, asignado_a para asignar, comentario para
    comentar)."""
    estado = _estado_de(alerta)
    if estado not in TRANSICIONES:
        raise TransicionInvalida(f"Estado desconocido: {estado!r}.")
    if accion not in ACCIONES:
        raise TransicionInvalida(f"Acción desconocida: {accion!r}. Válidas: {', '.join(ACCIONES)}.")
    if not usuario or not str(usuario).strip():
        raise ValueError("Toda acción sobre una alerta requiere el usuario que la hace.")
    if accion == "comentar":
        if estado in ESTADOS_FINALES:
            raise TransicionInvalida(f"No se puede comentar una alerta {estado}.")
        if not comentario or not str(comentario).strip():
            raise ValueError("comentar requiere un comentario.")
        nuevo = estado
    else:
        permitidas = TRANSICIONES[estado]
        if accion not in permitidas:
            raise TransicionInvalida(f"No se puede '{accion}' una alerta en estado '{estado}'. "
                                     f"Permitidas: {', '.join(permitidas) or 'ninguna (estado final)'}.")
        if accion == "asignar" and (not asignado_a or not str(asignado_a).strip()):
            raise ValueError("asignar requiere asignado_a.")
        nuevo = permitidas[accion]
    entrada = {
        "alerta_id": _id_de(alerta),
        "accion": accion,
        "estado_anterior": estado,
        "estado_nuevo": nuevo,
        "usuario": str(usuario),
        "comentario": comentario,
        "asignado_a": asignado_a,
        "fecha": _ahora(),
    }
    return nuevo, entrada
