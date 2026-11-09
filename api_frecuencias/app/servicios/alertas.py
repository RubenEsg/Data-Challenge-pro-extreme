"""Motor de reglas de alertas ALT-001..ALT-010 (especificación v1.5, §5) y máquina de estados de una alerta.

Funciones puras: no leen ni escriben la base; el orquestador (ejecucion.py) guarda las alertas y su historial.

Dos entradas:
- evaluar_alertas(contexto): una ventana (pronóstico de un horizonte o un contexto plano). Claves usadas (las ausentes
  desactivan la regla que las necesita):
    ruta, empresa, sentido, viaje, conductor, vehiculo, detectada_en, ventana_inicio, ventana_fin, horizonte_min
    demanda_prevista, p10, p90                      pronóstico puntual e intervalo en PASAJEROS POR HORA de la franja
                                                    [ventana_inicio, ventana_fin), las unidades de la capacidad por
                                                    hora (contexto_pronostico los toma de la hora recomendada)
    demanda_ventana, p10_ventana, p90_ventana       la demanda de la ventana de 30/60/120 min (trazabilidad y tendencia)
    pasajeros_observados, demanda_patron            demanda real consolidada y patrón (pronóstico del modelo)
    capacidad                                       puestos por bus (50 en el proyecto)
    buses_hora_actual, buses_hora_recomendado       oferta vigente y la de optimizacion.recomendacion_franja()
    factor_carga                                    carga crítica / abordajes de la franja (el del optimizador); sin
                                                    él vale 1 (se compara la demanda completa)
    cumple_nivel_servicio, carga_critica_diseno     comparacion_actual.actual del optimizador (ALT-003)
    ocupacion_esperada, ocupacion_observada         fracciones (0..1); si falta la esperada se calcula con el factor
    salidas_esperadas, salidas_observadas, minutos_desde_ultimo_despacho, headway_programado_min
    consolidado: {subidas, bajadas, nro_viajes, referencia: {campo: (centro, escala)}}
    minutos_sin_datos, campos_faltantes, horas_faltantes   frescura e integridad del dato
    wape_movil                                      métrica móvil del modelo frente a lo observado (fracción)
    serie_tendencia, variables_influyentes, ubicacion, origen   (opcionales; §9.4 y §5.3)
- evaluar_pronostico(contextos): las de todas las predicciones de una ejecución; los horizontes que caen en la misma
  franja dan una sola alerta.
- evaluar_observadas(contexto): ALT-002 (ocupación observada) y ALT-005..ALT-009 con DATOS OBSERVADOS, hora a hora
  sobre las horas cerradas que trajo la ejecución, con persistencia, episodios (una alerta por episodio, no por hora)
  y supresión entre reglas (§18 «Alertas excesivas»); con una serie diaria, también la ruptura de comportamiento
  (RF-009, CUSUM sobre los residuos diarios). Ver su docstring.

Ocupación y capacidad (ALT-001, ALT-002 y ALT-004) se miden igual que en el optimizador: carga crítica = factor de
carga de la franja × demanda por hora, frente a la capacidad ofrecida = buses/h × puestos. Así una alerta y la
recomendación de la misma franja dicen la misma ocupación.

Ninguna alerta es una etiqueta opaca (§9.4): todas llevan valor real, esperado, umbral, tendencia, recomendación,
puntaje con su método y las variables influyentes.

umbrales: los parámetros de §5.1 (UMBRALES_POR_DEFECTO); los que se pasen reemplazan a los de por defecto. Los valores
vigentes viven versionados en ai_frecuencias.threshold_config (migraciones 0001 y 0003).
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import statistics
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Parámetros de §5.1 (valores iniciales sugeridos) y los complementarios que necesita cada regla (documentados).
# Los marcados «backtest» se afinaron con scripts/backtest_alertas.py sobre 2025 (docs/evidencias/alertas/).
UMBRALES_POR_DEFECTO = {
    "version": "umbrales-v2",
    "ocupacion_objetivo_min": 0.65,     # §5.1 ocupación objetivo 65 % a 85 %
    "ocupacion_objetivo_max": 0.85,
    "ocupacion_critica": 0.90,          # §5.1 ≥ 90 %
    "baja_utilizacion": 0.30,           # §5.1 < 30 %
    "espera_max_min": 5.0,              # §5.1 espera máxima entre despachos
    "error_pronostico": 0.15,           # §5.1 ≥ 15 %
    "periodos_atraso": 2,               # §5.1 datos atrasados: 2 períodos de ingesta
    "periodo_ingesta_min": 1440.0,      # período de ingesta del ciclo diario (el mismo valor de threshold_config)
    "salidas_minimas_ocupacion": 2,     # ALT-002 observada: salidas mínimas en la hora para medir la ocupación
    "persistencia_ocupacion_horas": 2,  # ALT-002 observada: horas seguidas sobre el umbral crítico (backtest)
    "ruptura_k": 0.5,                   # RF-009 ruptura: holgura k del CUSUM (en desviaciones robustas)
    "ruptura_h": 6.0,                   # RF-009 ruptura: umbral h del CUSUM (backtest: falsas alarmas sin cambio)
    "ruptura_dias_referencia": 28,      # RF-009 ruptura: días de referencia para la media y la escala robustas
    "ruptura_cambio_minimo": 0.08,      # RF-009 ruptura: |cambio medio| mínimo del residuo relativo (backtest)
    "ruptura_dias_reinicio": 7,         # RF-009 ruptura: días de espera tras detectar, antes de fijar el nivel nuevo
    "caida_demanda": 0.30,              # ALT-005: caída relativa frente al patrón
    "demanda_minima_patron": 10.0,      # ALT-005/ALT-007 observadas: no se evalúa con patrones muy bajos (ruido)
    "alt005_exigir_p10": 1,             # ALT-005: además, la demanda real bajo el P10 calibrado (backtest)
    "persistencia_horas": 2,            # ALT-005/ALT-007 observadas: horas seguidas en el mismo sentido (backtest)
    "tolerancia_despacho_min": 5.0,     # ALT-006: minutos sobre el headway si Procesos.toleranciatiempo es 0 o falta
    "tolerancia_salidas": 0.50,         # ALT-006: déficit relativo de salidas tolerado (backtest; antes 0,20)
    "salidas_minimas_esperadas": 2,     # ALT-006: el déficit por conteo no se evalúa en bordes del servicio
    "z_anomalia": 3.5,                  # ALT-008: |z robusto| del consolidado (backtest; antes 3,0)
    "escala_minima_z": 0.05,            # ALT-008: escala mínima del z robusto (fracción de la mediana)
    "semanas_referencia": 8,            # ALT-008: semanas previas del mismo tipo de día
    "minimo_dias_referencia": 4,        # ALT-008: días mínimos en la referencia
    "pendiente_tendencia": 0.05,        # §9.4: cambio relativo por hora para declarar tendencia
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
ORIGEN_POR_CODIGO = {"ALT-001": "pronostico", "ALT-002": "pronostico", "ALT-003": "pronostico",
                     "ALT-004": "pronostico", "ALT-005": "observado", "ALT-006": "observado",
                     "ALT-007": "observado", "ALT-008": "observado", "ALT-009": "calidad_datos",
                     "ALT-010": "modelo"}
METODO_PUNTAJE = {
    "exceso": "exceso relativo sobre el umbral: 0,5 en el umbral y 1,0 con un exceso del 100 %",
    "z_robusto": "|z robusto| = |x - mediana| / max(1,4826·MAD, escala mínima) del mismo tipo de día; 0,5 en el umbral",
    "cusum": ("CUSUM tabular de dos lados sobre el residuo diario relativo (real - pronóstico) / pronóstico, "
              "estandarizado con la mediana y 1,4826·MAD de los días de referencia: S = max(0, S + z - k); alerta "
              "cuando S supera h; 0,5 en el umbral y 1,0 con S = 2h"),
}
CAPACIDAD_POR_OMISION = 50.0     # puestos por bus del catálogo del proyecto cuando el contexto no la trae

ESTADOS_ABIERTOS = ("nueva", "reconocida", "asignada")
ESTADOS_FINALES = ("cerrada", "descartada")
# nueva -> reconocida -> asignada -> cerrada | descartada; descartar se permite en cualquier estado abierto
# (falsa alarma)
# y asignar desde asignada es una reasignación. comentar no cambia el estado y se permite en cualquier estado abierto.
TRANSICIONES = {
    "nueva": {"reconocer": "reconocida", "descartar": "descartada"},
    "reconocida": {"asignar": "asignada", "descartar": "descartada"},
    "asignada": {"asignar": "asignada", "cerrar": "cerrada", "descartar": "descartada"},
    "cerrada": {},
    "descartada": {},
}
ACCIONES = ("reconocer", "asignar", "comentar", "cerrar", "descartar")
PATRON_SEUDONIMO = re.compile(r"^cnd_[0-9a-f]{24}$")
Z_P90 = 1.2815515655446004   # cuantil 0,9 de la normal estándar
HORAS_BORDE = (4, 20)        # primera y última hora de salidas (datos.HORAS_SERVICIO = 4..20): servicio parcial
ZONA = ZoneInfo("America/Bogota")
UNIDAD_DEMANDA_HORA = "pasajeros/h"
# Un factor de carga a menos de esto de 1 no cambia la carga comparada: se trata como neutro y el texto no lo muestra.
TOLERANCIA_FACTOR_NEUTRO = 1e-9


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


def _hora(t):
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)


def _hora_legible(v):
    """«15/10/2025 14:00» desde un instante ISO (las variables guardan el ISO con la zona de Bogotá)."""
    try:
        return datetime.fromisoformat(str(v)).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(v)


def _puntaje(observado, umbral, mayor=True):
    """0,5 justo en el umbral y 1,0 cuando el exceso relativo frente al umbral llega a 100 %."""
    try:
        base = abs(float(umbral)) if umbral else 1.0
        exceso = (float(observado) - float(umbral)) / base if mayor else (float(umbral) - float(observado)) / base
    except (TypeError, ValueError):
        return 0.5
    return round(0.5 + 0.5 * min(max(exceso, 0.0), 1.0), 3)


# ---------------------------------------------------------------- §18 seudonimización, §9.4 tendencia, probabilidad
def seudonimo_conductor(valor, secreto=None):
    """Referencia seudonimizada del conductor (§18): «cnd_» + 24 hex de HMAC-SHA256(secreto, id). Sin secreto en el
    entorno (SEUDONIMO_SECRETO) o sin valor devuelve None: nunca se guarda el dato en claro. Un seudónimo ya válido
    se conserva."""
    if valor is None or str(valor).strip() == "":
        return None
    texto = str(valor).strip()
    if PATRON_SEUDONIMO.match(texto):
        return texto
    clave = secreto if secreto is not None else os.environ.get("SEUDONIMO_SECRETO", "")
    if not clave:
        return None
    return "cnd_" + hmac.new(str(clave).encode(), texto.encode(), hashlib.sha256).hexdigest()[:24]


def tendencia(valores, umbral_pendiente=0.05):
    """(etiqueta, pendiente relativa por paso) de una serie cronológica (§9.4).

    Pendiente de mínimos cuadrados dividida por la media absoluta de la serie: al_alza si supera +umbral, a_la_baja
    si baja de -umbral, estable entre ambos y sin_datos con menos de 2 valores."""
    v = [float(x) for x in (valores or []) if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(v) < 2:
        return "sin_datos", None
    n = len(v)
    xm, ym = (n - 1) / 2.0, sum(v) / n
    den = sum((i - xm) ** 2 for i in range(n))
    pend = sum((i - xm) * (y - ym) for i, y in enumerate(v)) / den
    escala = max(sum(abs(y) for y in v) / n, 1e-9)
    rel = pend / escala
    if rel > umbral_pendiente:
        etiqueta = "al_alza"
    elif rel < -umbral_pendiente:
        etiqueta = "a_la_baja"
    else:
        etiqueta = "estable"
    return etiqueta, round(rel, 4)


def probabilidad_supera(media, p10, p90, limite):
    """P(X > limite) con X ~ Normal(media, σ), σ = (P90 - P10) / (2·1,2816): aproximación con la banda calibrada."""
    if media is None or limite is None:
        return None
    if p10 is None or p90 is None or float(p90) <= float(p10):
        return 1.0 if float(media) > float(limite) else 0.0
    sigma = (float(p90) - float(p10)) / (2 * Z_P90)
    z = (float(limite) - float(media)) / sigma
    return round(0.5 * math.erfc(z / math.sqrt(2)), 4)


def z_robusto(valor, referencia, escala_minima=0.05):
    """(z, mediana, escala) con la mediana y 1,4826·MAD de `referencia`; la escala nunca baja de escala_minima ×
    |mediana| ni de 1."""
    ref = [float(x) for x in referencia if x is not None]
    if not ref or valor is None:
        return None, None, None
    med = statistics.median(ref)
    mad = statistics.median([abs(x - med) for x in ref])
    escala = max(1.4826 * mad, float(escala_minima) * abs(med), 1.0)
    return (float(valor) - med) / escala, med, escala


def variables_desde_shap(explicacion_local, maximo=5):
    """[{variable, descripcion, valor, efecto_pasajeros, factor}] desde la explicación local SHAP de una predicción."""
    if not isinstance(explicacion_local, dict):
        return []
    salida = []
    for f in (explicacion_local.get("factores") or [])[:maximo]:
        salida.append({"variable": f.get("variable"), "descripcion": f.get("descripcion"), "valor": f.get("valor"),
                       "efecto_pasajeros": f.get("efecto_pasajeros"), "factor": f.get("factor_multiplicativo"),
                       "fuente": "shap_modelo"})
    if not salida:
        for f in (explicacion_local.get("importancia_global") or [])[:maximo]:
            salida.append({"variable": f.get("variable"), "importancia": f.get("importancia") or f.get("valor"),
                           "fuente": "importancia_global"})
    return salida


def _influyentes_de_regla(variables, maximo=6):
    return [{"variable": k, "valor": v, "fuente": "regla"} for k, v in list((variables or {}).items())[:maximo]
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def clave_dedup(codigo, ruta, ventana_inicio, ventana_fin):
    """Clave de deduplicación: código + ruta + ventana analizada."""
    return f"{codigo}|{ruta or '-'}|{_iso(ventana_inicio) or '-'}|{_iso(ventana_fin) or '-'}"


def clave_episodio(codigo, ruta, inicio_episodio, sufijo="obs"):
    """Clave de una alerta observada: código + ruta + inicio del episodio (estable mientras el episodio crece en
    ejecuciones sucesivas) + «obs», que la distingue de las de pronóstico (horizonte 0)."""
    return f"{codigo}|{ruta or '-'}|{_iso(inicio_episodio) or '-'}|{sufijo}"


def _alerta(ctx, u, codigo, severidad, observado, esperado, umbral, puntaje, explicacion, variables, *,
            probabilidad=None, metodo="exceso", serie=None, influyentes=None):
    nombre, recomendacion = CATALOGO[codigo]
    serie_t = ctx.get("serie_tendencia") if serie is None else serie
    etiqueta, pendiente = tendencia(serie_t, float(u.get("pendiente_tendencia", 0.05)))
    infl = influyentes if influyentes is not None else (ctx.get("variables_influyentes") or [])
    infl = list(infl) + [x for x in _influyentes_de_regla(variables) if x["variable"] not in
                         {i.get("variable") for i in infl}]
    return {
        "id": str(uuid.uuid4()),
        "codigo": codigo,
        "nombre": nombre,
        "origen": ctx.get("origen") or ORIGEN_POR_CODIGO[codigo],
        "empresa": ctx.get("empresa"),
        "ruta": ctx.get("ruta"),
        "sentido": ctx.get("sentido"),
        "viaje": None if ctx.get("viaje") is None else str(ctx.get("viaje")),
        "conductor": seudonimo_conductor(ctx.get("conductor")),
        "vehiculo": None if ctx.get("vehiculo") is None else str(ctx.get("vehiculo")),
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
        "probabilidad": probabilidad,
        "metodo_puntaje": METODO_PUNTAJE.get(metodo, metodo),
        "tendencia": etiqueta,
        "tendencia_pendiente": pendiente,
        "serie_reciente": list(ctx.get("serie_reciente") or []),
        "explicacion": explicacion,
        "variables": variables,
        "variables_influyentes": infl,
        "recomendacion": recomendacion,
        "ubicacion": ctx.get("ubicacion"),
        "asignado_a": None,
        "comentarios": [],
        "historial": [],
        "version_umbrales": u.get("version"),
        "clave_dedup": ctx.get("clave_dedup") or clave_dedup(codigo, ctx.get("ruta"), ctx.get("ventana_inicio"),
                                                             ctx.get("ventana_fin")),
    }


def _capacidad_actual(ctx):
    """Capacidad ofrecida por hora: buses/h actuales × puestos por bus (la capacidad_ofrecida del optimizador)."""
    b, c = ctx.get("buses_hora_actual"), ctx.get("capacidad")
    if b is None or c is None:
        return None if ctx.get("capacidad_ofrecida") is None else float(ctx["capacidad_ofrecida"])
    return float(b) * float(c)


def _factor(ctx):
    """Factor de carga crítica de la franja (carga del tramo más cargado / abordajes de la hora), el mismo que usa el
    optimizador; 1 si el contexto no lo trae (se compara la demanda completa con la capacidad)."""
    try:
        f = float(ctx.get("factor_carga"))
    except (TypeError, ValueError):
        return 1.0
    return f if 0 < f <= 1.5 else 1.0


def _con_factor(ctx):
    """El contexto trae un factor de carga válido que sí cambia la carga (se aparta de 1 más que
    TOLERANCIA_FACTOR_NEUTRO): solo entonces el texto muestra «× factor de carga»."""
    return ctx.get("factor_carga") is not None and abs(_factor(ctx) - 1.0) > TOLERANCIA_FACTOR_NEUTRO


def _ocupacion_esperada(ctx):
    """Ocupación esperada de la oferta actual = factor de carga × demanda por hora / capacidad ofrecida (la
    comparacion_actual del optimizador si el contexto la trae)."""
    if ctx.get("ocupacion_esperada") is not None:
        return float(ctx["ocupacion_esperada"])
    cap, d = _capacidad_actual(ctx), ctx.get("demanda_prevista")
    if cap and d is not None:
        return _factor(ctx) * float(d) / cap
    return None


def _texto_carga(ctx, demanda):
    """«1.450,0 pasajeros/h × factor de carga 0,453 = 656,9 pasajeros/h en el tramo más cargado» o, sin factor,
    «1.450,0 pasajeros/h»."""
    if not _con_factor(ctx):
        return f"{_f(demanda)} {UNIDAD_DEMANDA_HORA}"
    return (f"{_f(demanda)} {UNIDAD_DEMANDA_HORA} × factor de carga {_f(_factor(ctx), 3)} = "
            f"{_f(_factor(ctx) * float(demanda))} {UNIDAD_DEMANDA_HORA} en el tramo más cargado")


def _local(t):
    return t.astimezone(ZONA) if getattr(t, "tzinfo", None) is not None else t


def _unidades_pronostico(ctx):
    """La unidad de la demanda comparada y la demanda de la ventana del horizonte, cuando el contexto las trae."""
    return {k: ctx[k] for k in ("unidad_demanda", "demanda_ventana") if ctx.get(k) is not None}


def _franja_txt(ctx):
    """« en la franja 06:00-07:00» (hora de Bogotá) cuando la ventana trae instantes; vacío si no."""
    ini, fin = ctx.get("ventana_inicio"), ctx.get("ventana_fin")
    if hasattr(ini, "strftime") and hasattr(fin, "strftime"):
        return f" en la franja {_hora(_local(ini))}-{_hora(_local(fin))}"
    return ""


# ---------------------------------------------------------------- reglas
METODO_ALT001 = ("exceso relativo de la carga crítica proyectada (P90 calibrado de la demanda por hora × factor de "
                 "carga de la franja, el mismo del optimizador) sobre la capacidad por hora ofrecida (buses/h × "
                 "puestos); probabilidad con Normal(pronóstico, σ de la banda P10-P90 calibrada). Es un pronóstico: "
                 "no hay valor observado")


def _variables_carga(ctx):
    """Las cifras de la carga crítica que comparten ALT-001..ALT-004 (trazabilidad con el optimizador)."""
    v = {"factor_carga": _factor(ctx) if ctx.get("factor_carga") is not None else None,
         "fuente_factor_carga": ctx.get("fuente_factor_carga"),
         "capacidad_ofrecida": _capacidad_actual(ctx), "buses_hora_actual": ctx.get("buses_hora_actual"),
         "capacidad": ctx.get("capacidad"), "recomendacion_viable": ctx.get("recomendacion_viable")}
    return {k: x for k, x in v.items() if x is not None}


def _alt001(ctx, u):
    """Carga crítica proyectada POR HORA (factor de carga × P90 o puntual de la franja) frente a la capacidad POR HORA
    ofrecida (buses/h × puestos). Preventiva si la supera la del P90; crítica si también la del pronóstico puntual.
    observado queda vacío: es un pronóstico; la proyección va en esperado y en las variables."""
    cap = _capacidad_actual(ctx)
    d, p90 = ctx.get("demanda_prevista"), ctx.get("p90")
    proy = p90 if p90 is not None else d
    if cap is None or proy is None:
        return None
    f = _factor(ctx)
    carga_proy = f * float(proy)
    if carga_proy <= cap:
        return None
    carga_d = None if d is None else f * float(d)
    critica = carga_d is not None and carga_d > cap
    sev = "critica" if critica else "preventiva"
    prob = probabilidad_supera(d, ctx.get("p10"), p90, cap / f) if d is not None else None
    expl = (f"La carga crítica proyectada{_franja_txt(ctx)} ({'P90 ' if p90 is not None else ''}"
            f"{_texto_carga(ctx, proy)}) supera la capacidad por hora disponible ({_f(cap, 0)} puestos/h = "
            f"{_f(ctx.get('buses_hora_actual'), 1)} buses/h × {_f(ctx.get('capacidad'), 0)} puestos)"
            + (f"; incluso con el pronóstico puntual ({_texto_carga(ctx, d)}) la supera." if critica else
               f"; con el pronóstico puntual ({_texto_carga(ctx, d)}) aún cabe, el riesgo está en el intervalo "
               "superior.")
            + (f" Probabilidad estimada de superarla: {_pct(prob)}." if prob is not None else "")
            + (" Es la misma carga crítica con la que el optimizador recomienda esta franja." if _con_factor(ctx)
               else ""))
    return _alerta(ctx, u, "ALT-001", sev, None, carga_proy, cap, _puntaje(carga_proy, cap), expl,
                   {"p90": p90, "demanda_prevista": d, "p10": ctx.get("p10"),
                    "carga_critica_proyectada": round(carga_proy, 2),
                    "carga_critica_puntual": None if carga_d is None else round(carga_d, 2),
                    "ocupacion_proyectada_p90": round(carga_proy / cap, 4) if cap else None,
                    "valor_observado": "no aplica: alerta de pronóstico", **_variables_carga(ctx),
                    **_unidades_pronostico(ctx)},
                   probabilidad=prob, metodo=METODO_ALT001)


def _calculo_002(ctx, esp):
    """«(= 0,453 × 1.200,0 pasajeros/h ÷ 1.000 puestos/h en la franja …)» de la ocupación esperada."""
    cap, d = _capacidad_actual(ctx), ctx.get("demanda_prevista")
    if esp is None or not cap or d is None:
        return ""
    if not _con_factor(ctx):
        return f" (= {_f(d)} {UNIDAD_DEMANDA_HORA} ÷ {_f(cap, 0)} puestos/h{_franja_txt(ctx)})"
    return (f" (= factor de carga {_f(_factor(ctx), 3)} × {_f(d)} {UNIDAD_DEMANDA_HORA} ÷ {_f(cap, 0)} puestos/h"
            f"{_franja_txt(ctx)}, la misma ocupación que calcula el optimizador para la frecuencia actual)")


def _alt002(ctx, u):
    """Ocupación esperada (factor de carga × demanda / capacidad ofrecida) u observada ≥ ocupacion_critica. observado
    lleva solo la ocupación OBSERVADA (nunca un pronóstico)."""
    crit = float(u["ocupacion_critica"])
    esp, obs = _ocupacion_esperada(ctx), ctx.get("ocupacion_observada")
    candidatos = [(v, n) for v, n in ((obs, "observada"), (esp, "esperada")) if v is not None]
    if ctx.get("solo_observada"):          # la variante observada se decide (y se explica) solo con lo observado
        candidatos = [(v, n) for v, n in candidatos if n == "observada"]
    if not candidatos:
        return None
    valor, tipo = max(candidatos, key=lambda t: float(t[0]))
    if float(valor) < crit:
        return None
    cap, d = _capacidad_actual(ctx), ctx.get("demanda_prevista")
    prob = (probabilidad_supera(d, ctx.get("p10"), ctx.get("p90"), crit * cap / _factor(ctx))
            if tipo == "esperada" and cap and d is not None else None)
    calc_obs = f" ({ctx['calculo_ocupacion_observada']})" if ctx.get("calculo_ocupacion_observada") else ""
    expl = (f"La ocupación {tipo} ({_pct(valor)}) alcanza o supera el umbral crítico ({_pct(crit)}). "
            f"Esperada: {_pct(esp)}{_calculo_002(ctx, esp)}; observada: {_pct(obs)}{calc_obs}.")
    return _alerta(ctx, u, "ALT-002", "critica", obs, esp, crit, _puntaje(valor, crit), expl,
                   {"ocupacion_esperada": esp, "ocupacion_observada": obs, "tipo_ocupacion": tipo,
                    "demanda_prevista": ctx.get("demanda_prevista"), **_variables_carga(ctx),
                    **_unidades_pronostico(ctx), **(ctx.get("variables_ocupacion") or {})},
                   probabilidad=prob,
                   metodo=("exceso relativo de la ocupación sobre el umbral crítico; ocupación = factor de carga × "
                           "pasajeros por hora / (buses/h × puestos), como en el optimizador"))


def _nivel_servicio_actual(ctx, u):
    """(cumple, carga de diseño, capacidad efectiva actual, fuente) del nivel de servicio de la frecuencia ACTUAL:
    capacidad ofrecida × ocupación objetivo máxima ≥ carga crítica de diseño. Usa comparacion_actual del optimizador
    si el contexto la trae; si no, la carga de diseño es factor de carga × P90 (el cuantil 0,90 de la carga crítica
    con la banda calibrada). None si faltan datos."""
    cap = _capacidad_actual(ctx)
    occ = float(ctx.get("ocupacion_objetivo_max") or u["ocupacion_objetivo_max"])
    if ctx.get("cumple_nivel_servicio") is not None:
        carga = ctx.get("carga_critica_diseno")
        return (bool(ctx["cumple_nivel_servicio"]), None if carga is None else float(carga),
                None if cap is None else cap * occ, "optimizador (comparacion_actual de la franja)")
    proy = ctx.get("p90") if ctx.get("p90") is not None else ctx.get("demanda_prevista")
    if cap is None or proy is None:
        return None
    carga = _factor(ctx) * float(proy)
    return cap * occ >= carga - 1e-7, carga, cap * occ, "factor de carga × P90 frente a la capacidad efectiva"


def _texto_003(act, cap_ef, carga, occ, necesarios, rec, viable):
    h_act = 60.0 / float(act) if act and float(act) > 0 else None
    texto = (f"La frecuencia actual ({_f(act, 1)} buses/h, cada {_f(h_act, 1)} min) no cubre la demanda con el nivel "
             f"de servicio: con la ocupación objetivo máxima ({_pct(occ)}) lleva {_f(cap_ef, 0)} pasajeros/h en el "
             f"tramo más cargado, menos que la carga crítica de diseño ({_f(carga, 0)} pasajeros/h, P90)")
    if necesarios is not None:
        texto += f"; se necesitan al menos {_f(necesarios, 1)} buses/h"
    if viable is False:
        return texto + (f". La recomendación no es viable con la flota y el ciclo de la franja (mejor aproximación: "
                        f"{_f(rec, 0)} buses/h): hay que escalar el caso a la operación.")
    if rec is not None:
        return texto + f"; se recomiendan {_f(rec, 0)} buses/h (cada {_f(60.0 / float(rec), 1)} min)."
    return texto + "."


def _alt003(ctx, u):
    """ALT-003 por NIVEL DE SERVICIO, no por número de buses: la capacidad efectiva de la frecuencia actual no cubre
    la carga crítica de diseño (comparacion_actual.actual.cumple_nivel_servicio = False). Se dispara también cuando la
    recomendación no es viable (entonces lo dice y pide escalar)."""
    ns = _nivel_servicio_actual(ctx, u)
    act = ctx.get("buses_hora_actual")
    if ns is None or ns[0] or act is None:
        return None
    _, carga, cap_ef, fuente = ns
    occ = float(ctx.get("ocupacion_objetivo_max") or u["ocupacion_objetivo_max"])
    c = ctx.get("capacidad")
    necesarios = carga / (occ * float(c)) if carga is not None and c else None
    rec, viable = ctx.get("buses_hora_recomendado"), ctx.get("recomendacion_viable")
    esperado = rec if viable is not False and rec is not None else necesarios
    umbral = necesarios if necesarios is not None else esperado
    puntaje = _puntaje(umbral, act) if umbral is not None and float(act) > 0 else 1.0
    return _alerta(ctx, u, "ALT-003", "preventiva", act, esperado, umbral, puntaje,
                   _texto_003(act, cap_ef, carga, occ, necesarios, rec, viable),
                   {"buses_hora_actual": act, "buses_hora_recomendado": rec,
                    "buses_hora_necesarios_nivel_servicio": None if necesarios is None else round(necesarios, 2),
                    "headway_actual_min": 60.0 / float(act) if float(act) > 0 else None,
                    "capacidad_efectiva_actual": None if cap_ef is None else round(cap_ef, 1),
                    "carga_critica_diseno": carga, "cumple_nivel_servicio": False, "fuente_nivel_servicio": fuente,
                    "demanda_prevista": ctx.get("demanda_prevista"), "p90": ctx.get("p90"),
                    **_variables_carga(ctx)},
                   metodo="exceso relativo de los buses/h necesarios para el nivel de servicio sobre los actuales")


def _alt004(ctx, u):
    """Ocupación prevista (factor de carga × demanda / capacidad ofrecida) < baja_utilizacion, solo si el optimizador
    recomienda menos buses que los actuales. observado queda vacío: es un pronóstico."""
    minimo = float(u["baja_utilizacion"])
    esp = _ocupacion_esperada(ctx)
    if esp is None or esp >= minimo:
        return None
    act, rec = ctx.get("buses_hora_actual"), ctx.get("buses_hora_recomendado")
    if act is not None and rec is not None and float(act) <= float(rec):
        return None          # ya está en la oferta mínima recomendada: no hay intervalo que ampliar
    expl = (f"La ocupación prevista ({_pct(esp)}{_calculo_002(ctx, esp)}) está por debajo del mínimo de utilización "
            f"({_pct(minimo)}) con {_f(act, 1)} buses/h"
            + (f"; la recomendación es {_f(rec, 0)} buses/h." if rec is not None else "."))
    return _alerta(ctx, u, "ALT-004", "informativa", None, esp, minimo, _puntaje(esp, minimo, mayor=False), expl,
                   {"ocupacion_esperada": esp, "buses_hora_recomendado": rec,
                    "demanda_prevista": ctx.get("demanda_prevista"), **_variables_carga(ctx)})


def _cumple_005(obs, patron, p10, u):
    """Condición de ALT-005 en una ventana: patrón suficiente, real < (1 - caída) × patrón y, si se exige,
    real < P10."""
    if obs is None or patron is None or float(patron) < float(u["demanda_minima_patron"]):
        return False
    if float(obs) >= float(patron) * (1 - float(u["caida_demanda"])):
        return False
    if int(float(u.get("alt005_exigir_p10", 0))) and p10 is not None and float(obs) >= float(p10):
        return False
    return True


def _alt005(ctx, u):
    obs = ctx.get("pasajeros_observados")
    patron = ctx.get("demanda_patron", ctx.get("demanda_prevista"))
    if not _cumple_005(obs, patron, ctx.get("p10"), u):
        return None
    limite = float(patron) * (1 - float(u["caida_demanda"]))
    caida = 1 - float(obs) / float(patron)
    p10 = ctx.get("p10")
    con_p10 = int(float(u.get("alt005_exigir_p10", 0))) and p10 is not None
    expl = (f"La demanda real ({_f(obs)} pasajeros) cae {_pct(caida)} frente al patrón del modelo ({_f(patron)}); "
            f"el umbral de caída es {_pct(u['caida_demanda'])} (límite {_f(limite)})"
            + (f" y además queda bajo el P10 calibrado ({_f(p10)})." if con_p10 else "."))
    return _alerta(ctx, u, "ALT-005", "preventiva", obs, patron, limite, _puntaje(obs, limite, mayor=False), expl,
                   {"pasajeros_observados": obs, "demanda_patron": patron, "p10": p10,
                    "caida_relativa": round(caida, 4)})


def _tolerancia_despacho(ctx, u):
    """Procesos.toleranciatiempo (minutos) si viene y es > 0; si no, el umbral tolerancia_despacho_min."""
    t = ctx.get("tolerancia_tiempo_min")
    if t is not None and float(t) > 0:
        return float(t), "Procesos.toleranciatiempo"
    return float(u["tolerancia_despacho_min"]), "threshold_config.tolerancia_despacho_min"


def _deficit_salidas(esperadas, observadas, u, minimo):
    """True si faltan al menos 1 salida y más de tolerancia_salidas de las esperadas, con al menos `minimo`
    salidas esperadas."""
    if esperadas is None or observadas is None:
        return False
    e, o = float(esperadas), float(observadas)
    return e >= float(minimo) and e > 0 and e - o >= 1 and (e - o) / e > float(u["tolerancia_salidas"])


def _texto_006_tiempo(ctx, minutos, hprog, tol, fuente_tol):
    es_cota = ctx.get("minutos_es_cota")
    cota = " (cota inferior: horas cerradas sin salidas)" if es_cota else ""
    return (f"van {'al menos ' if es_cota else ''}{_f(minutos, 0)} min sin despacho{cota}, más que el headway "
            f"programado ({_f(hprog, 1)} min) más la tolerancia ({_f(tol, 0)} min, {fuente_tol})")


def _texto_006_conteo(obs, esp, u):
    deficit = float(esp) - float(obs)
    return (f"salieron {_f(obs, 0)} de {_f(esp, 0)} despachos esperados (déficit {_pct(deficit / float(esp))}, "
            f"tolerancia {_pct(u['tolerancia_salidas'])})")


def _medida_006(por_tiempo, minutos, hprog, tol, salidas, u):
    """(observado, esperado, umbral, puntaje) de ALT-006: en minutos si se cumplió por tiempo; si no, en salidas.
    salidas = (observadas, esperadas)."""
    if por_tiempo:
        umbral = float(hprog) + tol
        return minutos, hprog, umbral, _puntaje(minutos, umbral)
    obs, esp = salidas
    umbral = float(esp) * (1 - float(u["tolerancia_salidas"]))
    return obs, esp, umbral, _puntaje(obs, umbral if umbral > 0 else 1, mayor=False)


def _alt006(ctx, u):
    tol, fuente_tol = _tolerancia_despacho(ctx, u)
    hprog = ctx.get("headway_programado_min") or u["espera_max_min"]
    minutos = ctx.get("minutos_desde_ultimo_despacho")
    esp, obs = ctx.get("salidas_esperadas"), ctx.get("salidas_observadas")
    por_tiempo = minutos is not None and float(minutos) > float(hprog) + tol
    por_conteo = _deficit_salidas(esp, obs, u, u.get("salidas_minimas_esperadas", 0))
    if not (por_tiempo or por_conteo):
        return None
    partes = [_texto_006_tiempo(ctx, minutos, hprog, tol, fuente_tol)] if por_tiempo else []
    if por_conteo:
        partes.append(_texto_006_conteo(obs, esp, u))
    observado, esperado, umbral, puntaje = _medida_006(por_tiempo, minutos, hprog, tol, (obs, esp), u)
    return _alerta(ctx, u, "ALT-006", "critica", observado, esperado, umbral, puntaje,
                   "Despacho ausente o tardío: " + "; ".join(partes) + ".",
                   {"minutos_desde_ultimo_despacho": minutos, "headway_programado_min": hprog,
                    "tolerancia_min": tol, "fuente_tolerancia": fuente_tol,
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


def _z_por_campo(cons):
    """[(campo, valor, centro, z)] de subidas, bajadas y nro_viajes con referencia (centro, escala > 0)."""
    ref = cons.get("referencia") or {}
    salida = []
    for campo in ("subidas", "bajadas", "nro_viajes"):
        v, r = cons.get(campo), ref.get(campo)
        if v is None or not r:
            continue
        centro, escala = float(r[0]), float(r[1])
        if escala > 0:
            salida.append((campo, v, centro, (float(v) - centro) / escala))
    return salida


def _hallazgos_008(cons, zs, umbral_z):
    hallazgos = [f"{campo} = {_f(v, 0)} frente a {cons.get('nombre_centro', 'una media')} de {_f(centro, 1)} "
                 f"(z = {_f(z, 2)})" for campo, v, centro, z in zs if abs(z) >= umbral_z]
    if cons.get("nro_viajes") is not None and float(cons["nro_viajes"]) == 0 and float(cons.get("subidas") or 0) > 0:
        hallazgos.append(f"hay {_f(cons['subidas'], 0)} subidas con nro_viajes = 0")
    return hallazgos


def _peor_z(zs):
    """(z, (campo, valor, centro)) del primer campo con el mayor |z| (> 0); (0.0, None) si no hay."""
    zmax, peor = 0.0, None
    for campo, v, centro, z in zs:
        if abs(z) > abs(zmax):
            zmax, peor = z, (campo, v, centro)
    return zmax, peor


def _alt008(ctx, u):
    cons = ctx.get("consolidado") or {}
    zs = _z_por_campo(cons)
    hallazgos = _hallazgos_008(cons, zs, float(u["z_anomalia"]))
    if not hallazgos:
        return None
    zmax, peor = _peor_z(zs)
    campo, v, media = peor if peor else ("nro_viajes", cons.get("nro_viajes"), None)
    expl = "Consolidado atípico: " + "; ".join(hallazgos) + f" (umbral |z| ≥ {_f(u['z_anomalia'], 1)})."
    if cons.get("descripcion_referencia"):
        expl += " Referencia: " + str(cons["descripcion_referencia"]) + "."
    puntaje = _puntaje(abs(zmax), u["z_anomalia"]) if peor and abs(zmax) >= float(u["z_anomalia"]) else 1.0
    return _alerta(ctx, u, "ALT-008", "preventiva", v, media, u["z_anomalia"], puntaje, expl,
                   {"campo": campo, "z_maximo": round(zmax, 3), "subidas": cons.get("subidas"),
                    "bajadas": cons.get("bajadas"), "nro_viajes": cons.get("nro_viajes")},
                   metodo=cons.get("metodo") or "exceso")


def _alt009(ctx, u):
    faltan = list(ctx.get("campos_faltantes") or [])
    horas = list(ctx.get("horas_faltantes") or [])
    minutos = ctx.get("minutos_sin_datos")
    limite = float(u["periodos_atraso"]) * float(u["periodo_ingesta_min"])
    atrasado = minutos is not None and float(minutos) >= limite
    if not faltan and not horas and not atrasado:
        return None
    partes = []
    if atrasado:
        partes.append(f"llevan {_f(minutos, 0)} min sin recibir datos "
                      f"(umbral: {_f(u['periodos_atraso'], 0)} períodos de "
                      f"ingesta = {_f(limite, 0)} min)")
    if faltan:
        partes.append("faltan campos obligatorios: " + ", ".join(map(str, faltan)))
    if horas:
        partes.append(f"faltan {len(horas)} hora(s) de servicio sin registro: "
                      + ", ".join(map(_hora_legible, horas[:8])) + ("…" if len(horas) > 8 else ""))
    if atrasado:
        observado, esperado, umbral, puntaje = minutos, u["periodo_ingesta_min"], limite, _puntaje(minutos, limite)
    else:
        observado, esperado, umbral, puntaje = len(faltan) + len(horas), 0, 0, 1.0
    return _alerta(ctx, u, "ALT-009", "critica", observado, esperado, umbral, puntaje,
                   "Datos incompletos o retrasados: " + "; ".join(partes) + ".",
                   {"minutos_sin_datos": minutos, "campos_faltantes": faltan, "horas_faltantes": horas,
                    "periodo_ingesta_min": u["periodo_ingesta_min"], "periodos_atraso": u["periodos_atraso"],
                    "ultima_llegada": _iso(ctx.get("ultima_llegada"))})


def _alt010(ctx, u):
    w = ctx.get("wape_movil")
    tol = float(u["wape_max"])
    if w is None or float(w) <= tol:
        return None
    expl = (f"El WAPE móvil del modelo ({_pct(w)}) supera la tolerancia ({_pct(tol)}) frente a las observaciones"
            + (f" del modelo {ctx['model_id']}." if ctx.get("model_id") else "."))
    # la degradación es del modelo, no de una ventana: un episodio por (modelo, ruta) mientras siga abierta
    return _alerta(dict(ctx, clave_dedup=clave_modelo(ctx.get("model_id"), ctx.get("ruta"))), u, "ALT-010", "critica",
                   w, tol, tol, _puntaje(w, tol), expl, {"wape_movil": w, "model_id": ctx.get("model_id")})


def clave_modelo(model_id, ruta):
    """Clave de ALT-010: un episodio por modelo y ruta (no por ventana de pronóstico)."""
    return f"ALT-010|{model_id or '-'}|{ruta or '-'}|episodio"


REGLAS = {"ALT-001": _alt001, "ALT-002": _alt002, "ALT-003": _alt003, "ALT-004": _alt004, "ALT-005": _alt005,
          "ALT-006": _alt006, "ALT-007": _alt007, "ALT-008": _alt008, "ALT-009": _alt009, "ALT-010": _alt010}


def _umbrales(umbrales):
    u = dict(UMBRALES_POR_DEFECTO)
    u.update({k: v for k, v in (umbrales or {}).items() if v is not None})
    return u


def evaluar_alertas(contexto, umbrales=None):
    """Evalúa las diez reglas sobre `contexto` con `umbrales` (§5.1) y devuelve las alertas disparadas
    (estructura §5.3),
    a lo sumo una por código; cada una con su clave_dedup (código + ruta + ventana)."""
    u = _umbrales(umbrales)
    ctx = dict(contexto or {})
    ctx.setdefault("detectada_en", _ahora())
    salida = []
    for regla in REGLAS.values():
        a = regla(ctx, u)
        if a is not None:
            salida.append(a)
    return _sin_redundantes(salida)


def _sin_redundantes(alertas):
    """§18, una alerta por fenómeno: si en la misma franja sale ALT-001 (la carga crítica proyectada supera la
    capacidad), ALT-003 (no cubre el nivel de servicio, que es la capacidad × 85 %) dice lo mismo con menos fuerza: no
    se emite y ALT-001 lo anota en sus variables y en la explicación."""
    a001 = next((a for a in alertas if a["codigo"] == "ALT-001"), None)
    a003 = next((a for a in alertas if a["codigo"] == "ALT-003"), None)
    if a001 is None or a003 is None:
        return alertas
    necesarios = a003["variables"].get("buses_hora_necesarios_nivel_servicio")
    a001["variables"]["incluye_alt003"] = {"buses_hora_necesarios_nivel_servicio": necesarios,
                                           "recomendacion_viable": a003["variables"].get("recomendacion_viable")}
    if necesarios is not None:
        a001["explicacion"] += (f" La frecuencia actual tampoco cubre el nivel de servicio: se necesitan al menos "
                                f"{_f(necesarios, 1)} buses/h (frecuencia insuficiente, ALT-003, incluida aquí).")
    return [a for a in alertas if a is not a003]


# ---------------------------------------------------------------- ALT-001..ALT-004 y ALT-010 del ciclo (pronóstico)
def _inicio_franja(franja):
    fecha = franja["fecha"]
    fecha = fecha if isinstance(fecha, date) else date.fromisoformat(str(fecha)[:10])
    return datetime.combine(fecha, time(int(franja["hora"])), tzinfo=ZONA)


def contexto_pronostico(ruta, horizonte_min, franja, prediccion, entradas, recomendacion, **extra):
    """Contexto de las alertas de pronóstico de UNA predicción del ciclo, con demanda y capacidad POR HORA.

    La capacidad es por hora (buses/h × puestos por bus), así que la demanda que se le compara también lo es: la de
    la franja que se recomienda (franja = predicciones._franja_de_la_prediccion: la hora con más peso en la ventana,
    con su demanda y su banda P10-P90 calibrada por hora). La ventana de la alerta es esa hora, la misma de la
    recomendación, para los tres horizontes. La demanda de la ventana de horizonte_min (30/60/120 min) queda en
    demanda_ventana, p10_ventana y p90_ventana (trazabilidad y tendencia por horizonte).

    prediccion: salida de inferencia.predecir (pasajeros, p10, p90 y model_id de la ventana).
    entradas, recomendacion: entradas y salida de optimizacion.recomendacion_franja (capacidad,
    frecuencia_actual_min y buses_hora).
    extra: otras claves del contexto (empresa, detectada_en, wape_movil, variables_influyentes, …)."""
    inicio = _inicio_franja(franja)
    frec = entradas.get("frecuencia_actual_min")
    ctx = {"ruta": ruta, "ventana_inicio": inicio, "ventana_fin": inicio + timedelta(hours=1),
           "horizonte_min": int(horizonte_min),
           "demanda_prevista": franja.get("demanda_hora"), "p10": franja.get("p10_hora"),
           "p90": franja.get("p90_hora"), "unidad_demanda": UNIDAD_DEMANDA_HORA,
           "fuente_demanda": franja.get("fuente"),
           "demanda_ventana": prediccion.get("pasajeros"), "p10_ventana": prediccion.get("p10"),
           "p90_ventana": prediccion.get("p90"),
           "capacidad": entradas.get("capacidad"),
           "buses_hora_actual": (60.0 / float(frec)) if frec else None,
           "buses_hora_recomendado": recomendacion.get("buses_hora"), "model_id": prediccion.get("model_id")}
    ctx.update(_carga_del_optimizador(recomendacion, entradas))
    ctx.update(extra)
    return ctx


def _carga_del_optimizador(recomendacion, entradas):
    """Lo que el optimizador ya calculó para la franja (recommendation.detalle): el factor de carga crítica, la
    ocupación y el nivel de servicio de la frecuencia ACTUAL (comparacion_actual.actual), la carga crítica de diseño y
    la viabilidad. Así ALT-001..ALT-004 miden la ocupación igual que la recomendación de la misma franja."""
    rec = recomendacion or {}
    dem = rec.get("demanda") or {}
    actual = (rec.get("comparacion_actual") or {}).get("actual") or {}
    carga = ((rec.get("contexto_franja") or {}).get("factor_carga") or {})
    factor = rec.get("factor_carga", dem.get("factor_carga", (entradas or {}).get("factor_carga")))
    valores = {"factor_carga": factor,
               "fuente_factor_carga": carga.get("fuente") if isinstance(carga, dict) else None,
               "ocupacion_esperada": actual.get("ocupacion_esperada"),
               "capacidad_ofrecida": actual.get("capacidad_ofrecida"),
               "cumple_nivel_servicio": actual.get("cumple_nivel_servicio"),
               "carga_critica_diseno": dem.get("carga_critica_diseno"),
               "ocupacion_objetivo_max": (rec.get("parametros") or {}).get("ocupacion_objetivo"),
               "recomendacion_viable": rec.get("viable")}
    return {k: v for k, v in valores.items() if v is not None}


def _horizonte(a):
    h = a.get("horizonte_min")
    return math.inf if h is None else h


def evaluar_pronostico(contextos, umbrales=None):
    """Alertas de pronóstico de todas las predicciones de una ejecución (cada ruta con sus horizontes).

    Los horizontes cuya franja es la misma hora dan la misma alerta (misma clave_dedup: código + ruta + franja): queda
    una sola, la del horizonte más corto (el pronóstico más cercano a esa hora), y variables.horizontes_min dice en qué
    horizontes se cumplió la condición. Así una hora con riesgo es una alerta, no una por horizonte (§18)."""
    por_clave: dict[str, dict] = {}
    for ctx in contextos or []:
        for a in evaluar_alertas(ctx, umbrales):
            _fusionar_por_franja(por_clave, a)
    return list(por_clave.values())


def _fusionar_por_franja(por_clave, a):
    """Guarda `a` por su clave_dedup: queda la del horizonte más corto, con todos los horizontes que la cumplieron."""
    previa = por_clave.get(a["clave_dedup"])
    horizontes = set() if previa is None else set(previa["variables"]["horizontes_min"])
    if a.get("horizonte_min") is not None:
        horizontes.add(a["horizonte_min"])
    if previa is None or _horizonte(a) < _horizonte(previa):
        por_clave[a["clave_dedup"]] = a
    por_clave[a["clave_dedup"]]["variables"]["horizontes_min"] = sorted(horizontes)


# ---------------------------------------------------------------- ALT-005..ALT-009 con datos observados
def _contiguas(a, b):
    return a.get("fin") is not None and b.get("inicio") is not None and a["fin"] == b["inicio"]


def _signo_007(h, u):
    """+1 / -1 si la hora queda sobre P90 / bajo P10 con un error relativo ≥ error_pronostico; 0 si no."""
    obs, esp, p10, p90 = h.get("observado"), h.get("esperado"), h.get("p10"), h.get("p90")
    if obs is None or esp is None or float(esp) < float(u["demanda_minima_patron"]):
        return 0
    err = abs(float(obs) - float(esp)) / max(float(esp), 1.0)
    if err < float(u["error_pronostico"]):
        return 0
    if p90 is not None and float(obs) > float(p90):
        return 1
    if p10 is not None and float(obs) < float(p10):
        return -1
    if p10 is None or p90 is None:
        return 1 if float(obs) > float(esp) else -1
    return 0


def _episodios(marcas):
    """[(i0, i1)] de las rachas de índices marcados (True) consecutivos."""
    salida, i0 = [], None
    for i, m in enumerate(marcas + [False]):
        if m and i0 is None:
            i0 = i
        elif not m and i0 is not None:
            salida.append((i0, i - 1))
            i0 = None
    return salida


def _rachas(cond, horas, k):
    """Marca la hora i si cond[i-k+1..i] son iguales y no nulas, en horas contiguas. Devuelve (marcas, inicio_racha)."""
    marcas, inicio = [False] * len(cond), [None] * len(cond)
    largo = 0
    for i, c in enumerate(cond):
        if c and i > 0 and largo and cond[i - 1] == c and _contiguas(horas[i - 1], horas[i]):
            largo += 1
        else:
            largo = 1 if c else 0
        if c:
            inicio[i] = i - largo + 1
        marcas[i] = bool(c) and largo >= k
    return marcas, inicio


def _serie(horas, i0, i1, ventana=6):
    a = max(0, i0 - 2)
    return [{"inicio": _iso(h.get("inicio")), "observado": h.get("observado"), "esperado": h.get("esperado"),
             "p10": h.get("p10"), "p90": h.get("p90"), "salidas_observadas": h.get("salidas_observadas"),
             "salidas_esperadas": h.get("salidas_esperadas")} for h in horas[a:i1 + 1]][-ventana:]


def _razones(horas, i0, i1, clave_obs="observado", clave_esp="esperado"):
    a = max(0, i0 - 2)
    out = []
    for h in horas[a:i1 + 1]:
        o, e = h.get(clave_obs), h.get(clave_esp)
        if o is not None and e is not None and float(e) > 0:
            out.append(float(o) / float(e))
    return out


def _sumar(horas, i0, i1, campo):
    vals = [h.get(campo) for h in horas[i0:i1 + 1]]
    return None if any(v is None for v in vals) else float(sum(float(v) for v in vals))


def _base_ctx(ctx, horas, i0, i1, codigo, ini_racha):
    return {"ruta": ctx.get("ruta"), "empresa": ctx.get("empresa"), "sentido": ctx.get("sentido"),
            "viaje": ctx.get("viaje"), "conductor": ctx.get("conductor"), "vehiculo": ctx.get("vehiculo"),
            "detectada_en": ctx.get("detectada_en"), "ventana_inicio": horas[i0]["inicio"],
            "ventana_fin": horas[i1]["fin"], "horizonte_min": 0, "origen": ORIGEN_POR_CODIGO[codigo],
            "serie_reciente": _serie(horas, i0, i1),
            "clave_dedup": clave_episodio(codigo, ctx.get("ruta"), horas[ini_racha]["inicio"])}


def _episodios_nuevos(horas, marcas):
    """Episodios con al menos una hora llegada en esta ejecución (las demás solo dan contexto)."""
    return [(i0, i1) for i0, i1 in _episodios(marcas) if any(h.get("nueva", True) for h in horas[i0:i1 + 1])]


def _tramo(horas, r0, i1):
    return f"{_hora(horas[r0]['inicio'])}-{_hora(horas[i1]['fin'])}"


def _alerta_005_episodio(ep, u, k, demanda):
    """ALT-005 de un episodio: demanda = (real, esperado, p10) sumados en sus horas."""
    obs, esp, p10 = demanda
    limite = esp * (1 - float(u["caida_demanda"]))
    caida = 1 - obs / esp if esp else 0.0
    expl = (f"Durante {ep['n_h']} hora(s) seguidas ({ep['tramo']}) la demanda real ({_f(obs, 0)} pasajeros) cayó "
            f"{_pct(caida)} frente al patrón del modelo ({_f(esp, 0)}); el umbral de caída es "
            f"{_pct(u['caida_demanda'])} (límite {_f(limite, 0)})"
            + (f" y quedó bajo el P10 calibrado ({_f(p10, 0)})" if p10 is not None else "")
            + f"; persistencia exigida: {k} h.")
    return _alerta(ep["base"], u, "ALT-005", "preventiva", obs, esp, limite, _puntaje(obs, limite, mayor=False), expl,
                   {"pasajeros_observados": obs, "demanda_patron": esp, "p10": p10,
                    "caida_relativa": round(caida, 4), "horas_seguidas": ep["n_h"], "persistencia_horas": k},
                   serie=ep["serie"], influyentes=ep["infl"])


def _alerta_007_episodio(ep, u, k, demanda, arriba):
    """ALT-007 de un episodio: demanda = (real, esperado, p10, p90) sumados; arriba = sobre el P90."""
    obs, esp, p10, p90 = demanda
    limite = p90 if arriba else p10
    err = abs(obs - esp) / max(esp, 1.0)
    expl = (f"Durante {ep['n_h']} hora(s) seguidas ({ep['tramo']}) la demanda real ({_f(obs, 0)}) quedó "
            f"{'por encima del P90' if arriba else 'por debajo del P10'} del intervalo calibrado "
            f"({_f(limite, 0)}); pronóstico {_f(esp, 0)}, error {_pct(err)} (umbral "
            f"{_pct(u['error_pronostico'])}); persistencia exigida: {k} h.")
    return _alerta(ep["base"], u, "ALT-007", "preventiva", obs, esp, limite,
                   _puntaje(obs, limite, mayor=arriba) if limite else 1.0, expl,
                   {"pasajeros_observados": obs, "demanda_prevista": esp, "p10": p10, "p90": p90,
                    "error_relativo": round(err, 4), "sentido_desviacion": "+" if arriba else "-",
                    "horas_seguidas": ep["n_h"], "persistencia_horas": k},
                   serie=ep["serie"], influyentes=ep["infl"])


def _alerta_demanda_episodio(ctx, horas, u, k, codigo, tramo, s007):
    """La alerta ALT-005 o ALT-007 del episodio horas[r0..i1] (tramo = (r0, i1)); None si falta el real o el
    esperado en alguna hora."""
    r0, i1 = tramo
    obs, esp = _sumar(horas, r0, i1, "observado"), _sumar(horas, r0, i1, "esperado")
    p10, p90 = _sumar(horas, r0, i1, "p10"), _sumar(horas, r0, i1, "p90")
    if obs is None or esp is None:
        return None
    ep = {"base": _base_ctx(ctx, horas, r0, i1, codigo, r0), "infl": horas[i1].get("variables_influyentes") or [],
          "n_h": i1 - r0 + 1, "tramo": _tramo(horas, r0, i1), "serie": _razones(horas, r0, i1)}
    if codigo == "ALT-005":
        return _alerta_005_episodio(ep, u, k, (obs, esp, p10))
    return _alerta_007_episodio(ep, u, k, (obs, esp, p10, p90), s007[i1] > 0)


def _observadas_005_007(ctx, horas, u, k):
    """ALT-005 (caída) y ALT-007 (fuera de banda) con persistencia y episodios; la parte de ALT-007 por debajo se
    suprime en las horas que ya cubre ALT-005."""
    c005 = [1 if _cumple_005(h.get("observado"), h.get("esperado"), h.get("p10"), u) else 0 for h in horas]
    m005, ini005 = _rachas(c005, horas, k)
    s007 = [_signo_007(h, u) for h in horas]
    m007, ini007 = _rachas(s007, horas, k)
    m007 = [m and not (s007[i] < 0 and m005[i]) for i, m in enumerate(m007)]
    salida = []
    for codigo, marcas, inicios in (("ALT-005", m005, ini005), ("ALT-007", m007, ini007)):
        for i0, i1 in _episodios_nuevos(horas, marcas):
            a = _alerta_demanda_episodio(ctx, horas, u, k, codigo, (inicios[i0], i1), s007)
            if a is not None:
                salida.append(a)
    return salida


def _ceros_seguidos(horas, i, ceros):
    """Horas cerradas seguidas sin salidas que terminan en la hora i (0 si en la hora i hubo salidas o no hay dato)."""
    so = horas[i].get("salidas_observadas")
    if so is None or float(so) != 0:
        return 0
    if i > 0 and _contiguas(horas[i - 1], horas[i]):
        return ceros + 1
    return 1


def _minutos_sin_despacho(h, ceros):
    """(minutos, es_cota): los minutos desde el último despacho si la fuente los da; si no, la cota inferior
    60 × horas cerradas seguidas sin salidas, cuando se esperaba al menos una salida."""
    minutos = h.get("minutos_desde_ultimo_despacho")
    se = h.get("salidas_esperadas")
    if minutos is None and ceros and se is not None and float(se) >= 1:
        return 60.0 * ceros, True
    return minutos, False


def _marcas_006(horas, u, tol):
    """Por hora: cumple por tiempo, cumple por conteo (1/0) y (minutos, es_cota). Las horas de borde del servicio
    (servicio parcial) no se evalúan."""
    por_tiempo, por_conteo, detalle = [], [], []
    ceros = 0
    for i, h in enumerate(horas):
        ceros = _ceros_seguidos(horas, i, ceros)
        minutos, es_cota = _minutos_sin_despacho(h, ceros)
        borde = bool(h.get("borde_servicio"))
        hprog = h.get("headway_programado_min") or u["espera_max_min"]
        por_tiempo.append(not borde and minutos is not None and float(minutos) > float(hprog) + tol)
        c_ok = not borde and _deficit_salidas(h.get("salidas_esperadas"), h.get("salidas_observadas"), u,
                                              u["salidas_minimas_esperadas"])
        por_conteo.append(1 if c_ok else 0)
        detalle.append((minutos, es_cota))
    return por_tiempo, por_conteo, detalle


def _inicio_episodio_006(i0, por_tiempo, ini_conteo):
    """Primera hora del episodio: i0 si empieza por tiempo; si no, el inicio de la racha del déficit por conteo."""
    if por_tiempo[i0] or ini_conteo[i0] is None:
        return i0
    return ini_conteo[i0]


def _alerta_006_episodio(ctx, horas, u, k, episodio, marcas):
    """La alerta ALT-006 del episodio (i0, i1); marcas = (por_tiempo, inicio de la racha por conteo, detalle)."""
    i0, i1 = episodio
    por_tiempo, ini_conteo, detalle = marcas
    r0 = _inicio_episodio_006(i0, por_tiempo, ini_conteo)
    i_t = next((i for i in range(i1, i0 - 1, -1) if por_tiempo[i]), None)
    minutos, es_cota = detalle[i_t] if i_t is not None else (None, False)
    so, se = _sumar(horas, r0, i1, "salidas_observadas"), _sumar(horas, r0, i1, "salidas_esperadas")
    hprog = horas[i_t if i_t is not None else i1].get("headway_programado_min") or u["espera_max_min"]
    hctx = {"salidas_observadas": so, "salidas_esperadas": se,
            "minutos_desde_ultimo_despacho": minutos, "minutos_es_cota": es_cota,
            "headway_programado_min": hprog, "tolerancia_tiempo_min": ctx.get("tolerancia_tiempo_min")}
    a_ep = _alt006(hctx, dict(u, salidas_minimas_esperadas=0))
    if a_ep is None:
        return None
    base = _base_ctx(ctx, horas, r0, i1, "ALT-006", r0)
    base["ubicacion"] = ctx.get("ubicacion")
    expl = (f"En {_tramo(horas, r0, i1)} ({i1 - r0 + 1} h): salieron {_f(so, 0)} de {_f(se, 0)} despachos esperados "
            f"(60 / intervalo programado). " + a_ep["explicacion"])
    variables = dict(a_ep["variables"], horas_episodio=i1 - r0 + 1, persistencia_horas_conteo=k,
                     por_tiempo=i_t is not None)
    return _alerta(base, u, "ALT-006", "critica", a_ep["observado"], a_ep["esperado"], a_ep["umbral"],
                   a_ep["puntaje"], expl, variables,
                   serie=_razones(horas, r0, i1, "salidas_observadas", "salidas_esperadas"), influyentes=[])


def _observadas_006(ctx, horas, u, k):
    """ALT-006: despacho ausente o tardío, hora a hora y agrupado en episodios, solo en horas de servicio completas:
    la primera y la última hora (borde_servicio) tienen servicio parcial y 60 / intervalo las sobrestima."""
    tol, _ = _tolerancia_despacho(ctx, u)
    por_tiempo, por_conteo, detalle = _marcas_006(horas, u, tol)
    m_conteo, ini_conteo = _rachas(por_conteo, horas, k)   # el déficit por conteo exige la misma persistencia
    m006 = [t or c for t, c in zip(por_tiempo, m_conteo, strict=False)]
    salida = []
    for episodio in _episodios_nuevos(horas, m006):
        a = _alerta_006_episodio(ctx, horas, u, k, episodio, (por_tiempo, ini_conteo, detalle))
        if a is not None:
            salida.append(a)
    return salida


def _referencia_robusta(cons, u):
    """({campo: (mediana, escala)}, {campo: z}) de los campos con al menos minimo_dias_referencia días de
    referencia."""
    ref, zs = {}, {}
    for campo, valores in (cons.get("referencia_valores") or {}).items():
        if cons.get(campo) is None or len(valores or []) < int(float(u["minimo_dias_referencia"])):
            continue
        z, med, esc = z_robusto(cons[campo], valores, float(u["escala_minima_z"]))
        if z is not None:
            ref[campo], zs[campo] = (med, esc), z
    return ref, zs


def _base_008(ctx, cons, ref):
    return {"ruta": ctx.get("ruta"), "empresa": ctx.get("empresa"), "sentido": ctx.get("sentido"),
            "detectada_en": ctx.get("detectada_en"), "ventana_inicio": cons.get("inicio"),
            "ventana_fin": cons.get("fin"), "horizonte_min": 0, "origen": "observado",
            "serie_tendencia": cons.get("serie"), "serie_reciente": cons.get("serie_detalle") or [],
            "clave_dedup": clave_episodio("ALT-008", ctx.get("ruta"), cons.get("inicio"), "dia"),
            "consolidado": {"subidas": cons.get("subidas"), "nro_viajes": cons.get("nro_viajes"),
                            "referencia": ref, "nombre_centro": "la mediana", "metodo": "z_robusto",
                            "descripcion_referencia": cons.get("descripcion_referencia")}}


def _umbral_en_unidades_008(a, ref, zs, u):
    """Umbral en las unidades del valor real (§9.4): mediana ± z_anomalia × escala del campo con mayor |z|."""
    campo = a["variables"].get("campo")
    if campo not in ref:
        return
    med, esc = ref[campo]
    signo = 1.0 if zs[campo] >= 0 else -1.0
    a["umbral"] = round(med + signo * float(u["z_anomalia"]) * esc, 4)
    a["explicacion"] += (f" Límite para {campo}: {_f(a['umbral'], 0)} (mediana {_f(med, 0)} "
                         f"{'+' if signo > 0 else '-'} {_f(u['z_anomalia'], 1)} × {_f(esc, 1)}).")


def _observadas_008(ctx, u):
    """ALT-008: consolidado del día con z robusto frente al mismo tipo de día."""
    cons = ctx.get("consolidado") or {}
    if not (cons and cons.get("referencia_valores")):
        return []
    ref, zs = _referencia_robusta(cons, u)
    if not (ref or (cons.get("nro_viajes") == 0 and (cons.get("subidas") or 0) > 0)):
        return []
    a = _alt008(_base_008(ctx, cons, ref), u)
    if a is None:
        return []
    _umbral_en_unidades_008(a, ref, zs, u)
    a["variables"].update({"umbral_z": float(u["z_anomalia"]),
                           "z_por_campo": {c: round(z, 3) for c, z in zs.items()},
                           "referencia_mediana_escala": {c: [round(m, 2), round(e, 2)] for c, (m, e) in ref.items()},
                           "fecha": _iso(cons.get("fecha"))})
    return [a]


def _observadas_009(ctx, u):
    """ALT-009: datos incompletos o retrasados (una por ruta y día con faltantes; una por ruta si solo hay atraso)."""
    dat = ctx.get("datos") or {}
    if not dat:
        return []
    base = {"ruta": ctx.get("ruta"), "empresa": ctx.get("empresa"), "detectada_en": ctx.get("detectada_en"),
            "ventana_inicio": dat.get("ultima_llegada"), "ventana_fin": dat.get("referencia"),
            "horizonte_min": 0, "origen": "calidad_datos", "minutos_sin_datos": dat.get("minutos_sin_datos"),
            "campos_faltantes": dat.get("campos_faltantes"), "horas_faltantes": dat.get("horas_faltantes"),
            "ultima_llegada": dat.get("ultima_llegada")}
    con_faltantes = bool(dat.get("campos_faltantes") or dat.get("horas_faltantes"))
    base["clave_dedup"] = clave_episodio("ALT-009", ctx.get("ruta"), dat.get("fecha") if con_faltantes else None,
                                         "faltantes" if con_faltantes else "frescura")
    a = _alt009(base, u)
    return [] if a is None else [a]


# ---------------------------------------------------------------- ALT-002 con la ocupación OBSERVADA
def _factor_de_la_hora(ctx, h):
    """Factor de carga de la hora: el que trae la hora o el contexto; si no, el del optimizador para la ruta, el tipo
    de día y la hora (optimizacion.factor_carga_franja, mediana 2025). (factor, fuente) o (None, None)."""
    if h.get("factor_carga") is not None:
        return float(h["factor_carga"]), h.get("fuente_factor_carga") or "contexto de la hora"
    por_hora = ctx.get("factor_carga_por_hora") or {}
    ini = h.get("inicio")
    if not hasattr(ini, "hour"):
        return None, None
    loc = _local(ini)
    if loc.hour in por_hora:
        return float(por_hora[loc.hour]), ctx.get("fuente_factor_carga") or "contexto de la ruta"
    try:
        from app.servicios import optimizacion

        fc = optimizacion.factor_carga_franja(ctx.get("ruta"), loc.date(), loc.hour)
    except Exception:  # noqa: BLE001 - sin factor de la franja la hora no evalúa la ocupación observada
        return None, None
    return (None, None) if not fc else (float(fc["factor_carga"]), fc.get("fuente"))


def _capacidad_de_la_ruta(ctx):
    """(puestos por bus, fuente): los del contexto o los del catálogo de rutas; 50 si ninguno los trae."""
    if ctx.get("capacidad") is not None:
        return float(ctx["capacidad"]), "contexto (catálogo de la ruta)"
    try:
        from app.servicios import datos

        info = {r["ruta"]: r for r in datos.catalogo_rutas()}.get(ctx.get("ruta")) or {}
    except Exception:  # noqa: BLE001 - sin catálogo rige la capacidad por omisión
        info = {}
    if info.get("capacidad"):
        return float(info["capacidad"]), "datos/catalogo_rutas.json"
    return CAPACIDAD_POR_OMISION, "capacidad por omisión del proyecto (50 puestos)"


def ocupacion_observada_hora(h, factor, capacidad, minimo_salidas):
    """Ocupación observada de una hora cerrada = factor de carga × pasajeros observados / (salidas observadas ×
    puestos). None si faltan datos, es una hora de borde (servicio parcial) o salieron menos de minimo_salidas buses."""
    obs, so = h.get("observado"), h.get("salidas_observadas")
    if obs is None or so is None or factor is None or not capacidad or h.get("borde_servicio"):
        return None
    if float(so) < max(float(minimo_salidas), 1.0):
        return None
    return float(factor) * float(obs) / (float(so) * float(capacidad))


def _ocupaciones_observadas(ctx, horas, u):
    """[(ocupación, factor, fuente)] por hora; la ocupación es None donde no se puede medir."""
    capacidad, _ = _capacidad_de_la_ruta(ctx)
    salida = []
    for h in horas:
        factor, fuente = _factor_de_la_hora(ctx, h) if h.get("observado") is not None else (None, None)
        salida.append((ocupacion_observada_hora(h, factor, capacidad, u["salidas_minimas_ocupacion"]), factor,
                       fuente))
    return salida


def _alerta_002_observada(ctx, horas, u, tramo, medidas):
    """ALT-002 de un episodio de horas con ocupación observada ≥ umbral crítico (la peor hora manda)."""
    r0, i1 = tramo
    capacidad, fuente_cap = _capacidad_de_la_ruta(ctx)
    i_max = max(range(r0, i1 + 1), key=lambda i: medidas[i][0] or 0.0)
    occ, factor, fuente = medidas[i_max]
    h = horas[i_max]
    base = _base_ctx(ctx, horas, r0, i1, "ALT-002", r0)
    base.update({"origen": "observado", "ocupacion_observada": occ, "factor_carga": factor, "capacidad": capacidad,
                 "fuente_factor_carga": fuente, "solo_observada": True,
                 "buses_hora_actual": h.get("salidas_observadas"),
                 "calculo_ocupacion_observada": (
                     f"= factor de carga {_f(factor, 3)} × {_f(h.get('observado'), 0)} pasajeros ÷ "
                     f"({_f(h.get('salidas_observadas'), 0)} salidas × {_f(capacidad, 0)} puestos) en "
                     f"{_tramo(horas, i_max, i_max)}"),
                 "variables_ocupacion": {
                     "horas_episodio": i1 - r0 + 1, "hora_pico": _iso(h.get("inicio")),
                     "pasajeros_observados": h.get("observado"), "salidas_observadas": h.get("salidas_observadas"),
                     "salidas_programadas": h.get("salidas_esperadas"), "fuente_capacidad": fuente_cap,
                     "ocupacion_por_hora": {_hora(horas[i]["inicio"]): round(medidas[i][0], 4)
                                            for i in range(r0, i1 + 1) if medidas[i][0] is not None},
                     "persistencia_horas": int(float(u["persistencia_ocupacion_horas"]))}})
    # la esperada: el pronóstico de esa hora con la oferta PROGRAMADA (60 / intervalo), como en el optimizador
    if h.get("esperado") is not None and h.get("salidas_esperadas"):
        base["ocupacion_esperada"] = factor * float(h["esperado"]) / (float(h["salidas_esperadas"]) * capacidad)
    a = _alt002(base, u)
    if a is not None:
        a["serie_reciente"] = [{"inicio": _iso(horas[i]["inicio"]), "ocupacion_observada": medidas[i][0],
                                "pasajeros": horas[i].get("observado"),
                                "salidas_observadas": horas[i].get("salidas_observadas")}
                               for i in range(max(0, r0 - 2), i1 + 1)][-6:]
    return a


def _observadas_002(ctx, horas, u):
    """ALT-002 con la ocupación OBSERVADA de cada hora cerrada (§5.2 «ocupación esperada u observada»): factor de
    carga de la franja × pasajeros / (salidas × puestos) ≥ ocupacion_critica, en episodios de horas seguidas."""
    if not horas:
        return []
    medidas = _ocupaciones_observadas(ctx, horas, u)
    crit = float(u["ocupacion_critica"])
    cond = [1 if m[0] is not None and m[0] >= crit else 0 for m in medidas]
    k = max(1, int(float(u["persistencia_ocupacion_horas"])))
    marcas, inicios = _rachas(cond, horas, k)
    salida = []
    for i0, i1 in _episodios_nuevos(horas, marcas):
        a = _alerta_002_observada(ctx, horas, u, (inicios[i0], i1), medidas)
        if a is not None:
            salida.append(a)
    return salida


# ---------------------------------------------------------------- RF-009: ruptura de comportamiento (CUSUM)
def residuos_diarios(serie):
    """[(fecha, residuo relativo)] de una serie diaria [{fecha, observado, esperado}]: (real - pronóstico) / pronóstico,
    en orden cronológico; se omiten los días sin dato o con pronóstico ≤ 0."""
    salida = []
    for d in sorted(serie or [], key=lambda x: str(x.get("fecha"))):
        o, e = d.get("observado"), d.get("esperado")
        if o is None or e is None or float(e) <= 0:
            continue
        salida.append((d.get("fecha"), (float(o) - float(e)) / float(e)))
    return salida


def _inicio_del_cambio(valores, desde, hasta, centro, escala, k, lado):
    """Primer día del tramo [desde, hasta] que ya se aparta más de k desviaciones en el sentido detectado."""
    return next((j for j in range(desde, hasta + 1) if lado * (float(valores[j]) - centro) / escala > k), desde)


def _paso_cusum(acumulado, inicio, i, z, k):
    """Un paso de un lado del CUSUM tabular, S = max(0, S + z - k). Si el acumulado estaba en su piso (S nunca es
    negativo por el max, así que «≤ 0» es «vale 0»), el tramo acumulado empieza en el día i.
    Devuelve (S nuevo, inicio del tramo)."""
    if acumulado <= 0.0:
        inicio = i
    return max(0.0, acumulado + z - k), inicio


def cusum(valores, centro, escala, k=0.5, h=5.0, reinicio=7):
    """CUSUM tabular de dos lados sobre z = (x - centro) / escala.

    Devuelve las detecciones [{indice, lado (+1/-1), estadistico, inicio, centro_anterior, centro_nuevo}]: inicio es
    el cambio estimado (primer día del tramo acumulado que se aparta más de k) y centro_nuevo el nivel medio del tramo
    hasta la detección. Tras cada detección vienen `reinicio` días de espera (sin detecciones) y el centro pasa al
    nivel medio desde el inicio del cambio hasta el fin de la espera: un cambio que se sostiene es UNA ruptura y no una
    alerta cada pocos días (§18). Es causal: una detección posterior solo usa días anteriores a ella."""
    c = float(centro)
    s_pos = s_neg = 0.0
    ini_pos = ini_neg = 0
    detecciones = []
    espera_hasta, ini_cambio = -1, None
    for i, x in enumerate(valores):
        if i <= espera_hasta:
            if i == espera_hasta:
                c = statistics.fmean(float(v) for v in valores[ini_cambio:i + 1])
            continue
        z = (float(x) - c) / escala
        s_pos, ini_pos = _paso_cusum(s_pos, ini_pos, i, z, k)     # hacia arriba: max(0, S + z - k)
        s_neg, ini_neg = _paso_cusum(s_neg, ini_neg, i, -z, k)    # hacia abajo: max(0, S - z - k)
        if s_pos <= h and s_neg <= h:
            continue
        lado, estadistico, ini_lado = (1, s_pos, ini_pos) if s_pos > h else (-1, s_neg, ini_neg)
        ini = _inicio_del_cambio(valores, ini_lado, i, c, escala, k, lado)
        nuevo = statistics.fmean(float(v) for v in valores[ini:i + 1])
        detecciones.append({"indice": i, "lado": lado, "estadistico": round(estadistico, 3),
                            "inicio": ini, "centro_anterior": c, "centro_nuevo": nuevo})
        c, s_pos, s_neg = nuevo, 0.0, 0.0
        espera_hasta, ini_cambio = min(i + int(reinicio), len(valores) - 1), ini
    return detecciones


def detectar_rupturas(serie, umbrales=None):
    """Rupturas de comportamiento (RF-009) en una serie diaria de una ruta: cambios sostenidos de nivel del residuo
    relativo real - pronóstico. La referencia (mediana y 1,4826·MAD, con piso de 0,02) son los primeros
    ruptura_dias_referencia días; el CUSUM corre sobre los siguientes. Una detección cuenta solo si el cambio medio
    entre su inicio y la detección llega a ruptura_cambio_minimo. Devuelve {referencia, detecciones: [...]}."""
    u = _umbrales(umbrales)
    res = residuos_diarios(serie)
    n_ref = int(float(u["ruptura_dias_referencia"]))
    if len(res) <= n_ref:
        return {"referencia": None, "detecciones": []}
    ref = [r for _, r in res[:n_ref]]
    centro = statistics.median(ref)
    escala = max(1.4826 * statistics.median([abs(r - centro) for r in ref]), 0.02)
    vigilados = res[n_ref:]
    salida = []
    for d in cusum([r for _, r in vigilados], centro, escala, float(u["ruptura_k"]), float(u["ruptura_h"]),
                   int(float(u["ruptura_dias_reinicio"]))):
        cambio = d["centro_nuevo"] - d["centro_anterior"]
        if abs(cambio) < float(u["ruptura_cambio_minimo"]):
            continue
        salida.append({"fecha_deteccion": vigilados[d["indice"]][0], "fecha_inicio": vigilados[d["inicio"]][0],
                       "dias": d["indice"] - d["inicio"] + 1, "lado": d["lado"], "estadistico": d["estadistico"],
                       "cambio_medio": round(cambio, 4), "residuo_medio_tramo": round(d["centro_nuevo"], 4),
                       "nivel_anterior": round(d["centro_anterior"], 4)})
    return {"referencia": {"centro": round(centro, 4), "escala": round(escala, 4), "dias": n_ref,
                           "desde": res[0][0], "hasta": res[n_ref - 1][0]}, "detecciones": salida}


def _dia_inicio(fecha):
    f = fecha if isinstance(fecha, date) else date.fromisoformat(str(fecha)[:10])
    return datetime.combine(f, time(0), tzinfo=ZONA)


def _alerta_ruptura(ctx, u, det, ref):
    """La alerta ALT-007, variante «ruptura de comportamiento», de una detección del CUSUM."""
    arriba = det["lado"] > 0
    h = float(u["ruptura_h"])
    ini, fin = _dia_inicio(det["fecha_inicio"]), _dia_inicio(det["fecha_deteccion"]) + timedelta(days=1)
    base = {"ruta": ctx.get("ruta"), "empresa": ctx.get("empresa"), "detectada_en": ctx.get("detectada_en"),
            "ventana_inicio": ini, "ventana_fin": fin, "horizonte_min": 0, "origen": "observado",
            "clave_dedup": clave_episodio("ALT-007", ctx.get("ruta"), ini, "ruptura"),
            "serie_reciente": [{"fecha": str(d.get("fecha")), "observado": d.get("observado"),
                                "esperado": d.get("esperado")} for d in (ctx.get("serie_diaria") or [])][-14:]}
    expl = (f"Ruptura de comportamiento: desde el {_dia_inicio(det['fecha_inicio']):%d/%m/%Y} la demanda real "
            f"diaria quedó {'por encima' if arriba else 'por debajo'} del pronóstico de forma sostenida "
            f"({det['dias']} {'día' if det['dias'] == 1 else 'días'} hasta la detección; residuo medio "
            f"{_pct(det['residuo_medio_tramo'])} frente a "
            f"{_pct(det.get('nivel_anterior', ref['centro']))} del nivel anterior (referencia de {ref['dias']} días: "
            f"{_pct(ref['centro'])}), cambio {_pct(det['cambio_medio'])}). "
            f"El CUSUM llegó a {_f(det['estadistico'], 2)} con umbral h = {_f(h, 1)} (k = {_f(u['ruptura_k'], 1)}). "
            "No es una hora aislada: cambió el nivel de la demanda frente al patrón del modelo.")
    # observado, esperado y umbral en las mismas unidades (residuo relativo): el nivel nuevo, el anterior y el anterior
    # ± el cambio mínimo; el estadístico del CUSUM y su h van en el puntaje y en las variables
    anterior = det.get("nivel_anterior", ref["centro"])
    umbral = anterior + (1 if arriba else -1) * float(u["ruptura_cambio_minimo"])
    return _alerta(base, u, "ALT-007", "preventiva", det["residuo_medio_tramo"], anterior, umbral,
                   _puntaje(det["estadistico"], h), expl,
                   {"variante": "ruptura_comportamiento", "metodo": "CUSUM tabular de dos lados (Page, 1954)",
                    "sentido_desviacion": "+" if arriba else "-", "fecha_inicio_cambio": str(det["fecha_inicio"]),
                    "fecha_deteccion": str(det["fecha_deteccion"]), "dias_tramo": det["dias"],
                    "cambio_medio": det["cambio_medio"], "residuo_medio_tramo": det["residuo_medio_tramo"],
                    "estadistico_cusum": det["estadistico"], "k": float(u["ruptura_k"]), "h": h,
                    "referencia_centro": ref["centro"], "referencia_escala": ref["escala"],
                    "referencia_dias": ref["dias"], "cambio_minimo": float(u["ruptura_cambio_minimo"])},
                   metodo="cusum", serie=[d.get("observado") for d in (ctx.get("serie_diaria") or [])][-14:],
                   influyentes=[])


def serie_diaria_ruta(sesion, ruta, hasta, model_id=None, *, dias=56, nuevas=()):
    """serie_diaria de la ruptura (RF-009) para el contexto observado del ciclo: real (demanda_observada) y pronóstico
    del modelo (inferencia.predecir_horas en un solo lote, h = 60 desde cada hora) por día COMPLETO de los últimos
    `dias` días hasta `hasta`; nueva = el día está en `nuevas`. Lista vacía si falta algo: la regla no se evalúa y el
    ciclo sigue (no es una función pura: lee la base y el modelo)."""
    try:
        from sqlalchemy import select

        from app.modelos_db import DemandaObservada
        from app.servicios import datos, inferencia

        horas_servicio = list(datos.HORAS_SERVICIO)
        filas = sesion.execute(select(DemandaObservada.fecha, DemandaObservada.hora, DemandaObservada.pasajeros)
                               .where(DemandaObservada.ruta == ruta, DemandaObservada.fecha <= hasta,
                                      DemandaObservada.fecha > hasta - timedelta(days=int(dias)),
                                      DemandaObservada.hora.in_(horas_servicio))).all()
        por_dia: dict = {}
        for f, h, p in filas:
            if p is not None:
                por_dia.setdefault(f, {})[int(h)] = float(p)
        completos = sorted(f for f, hs in por_dia.items() if len(hs) >= len(horas_servicio))
        if not completos:
            return []
        inicios = [datetime.combine(f, time(h), tzinfo=ZONA) for f in completos for h in horas_servicio]
        preds = inferencia.predecir_horas(ruta, inicios, model_id, horizonte_min=60, usar_nowcast=False,
                                          sesion=sesion)
    except Exception:  # noqa: BLE001 - sin serie la ruptura no se evalúa en esta ejecución
        return []
    esperado: dict = {}
    for ini, r in zip(inicios, preds, strict=False):
        esperado[ini.date()] = esperado.get(ini.date(), 0.0) + float(r.get("pasajeros") or 0.0)
    nuevas = {str(x) for x in nuevas}
    return [{"fecha": f, "observado": sum(por_dia[f].values()), "esperado": esperado.get(f),
             "nueva": str(f) in nuevas} for f in completos]


def _observadas_ruptura(ctx, u):
    """RF-009 «rupturas de comportamiento»: con una serie diaria de la ruta (serie_diaria: [{fecha, observado,
    esperado, nueva}]) alerta la última detección del CUSUM si cae en un día nuevo de la ejecución."""
    serie = ctx.get("serie_diaria") or []
    if not serie:
        return []
    r = detectar_rupturas(serie, u)
    if not r["detecciones"]:
        return []
    nuevas = {str(d.get("fecha")) for d in serie if d.get("nueva", True)}
    det = r["detecciones"][-1]
    if str(det["fecha_deteccion"]) not in nuevas:
        return []
    return [_alerta_ruptura(ctx, u, det, r["referencia"])]


def evaluar_observadas(contexto, umbrales=None):
    """ALT-005..ALT-009 con datos OBSERVADOS (§5.2, RF-009, RF-010) para una ruta.

    contexto:
      ruta, empresa, sentido, detectada_en, ubicacion (GeoJSON del punto de despacho, opcional)
      tolerancia_tiempo_min        Procesos.toleranciatiempo (min); 0 o ausente = umbral tolerancia_despacho_min
      horas: lista CRONOLÓGICA de horas cerradas de la ruta [{inicio, fin, observado, esperado, p10, p90,
             salidas_observadas, salidas_esperadas, headway_programado_min, nueva, variables_influyentes}]
             (esperado/p10/p90 = pronóstico del modelo y banda calibrada para esa hora; nueva = llegó en esta
             ejecución). Las horas no nuevas solo sirven de contexto para la persistencia y la tendencia.
      consolidado: {fecha, inicio, fin, subidas, nro_viajes, referencia_valores: {campo: [valores de los días del
             mismo tipo en las semanas previas]}, serie: [totales diarios cronológicos], descripcion_referencia}
      datos: {minutos_sin_datos, ultima_llegada, referencia, campos_faltantes, horas_faltantes, fecha}

    Reglas (umbrales versionados en threshold_config):
      ALT-005  real < (1 - caida_demanda) × esperado y real < P10, sostenido persistencia_horas horas seguidas.
      ALT-007  real fuera de [P10, P90] con |error| ≥ error_pronostico, en el MISMO sentido persistencia_horas horas;
               la parte por debajo se suprime en las horas que ya cubre ALT-005 (una sola alerta por fenómeno).
      ALT-006  por tiempo: minutos sin despacho (o su cota inferior, 60 × horas cerradas seguidas sin salidas) >
               headway programado + tolerancia (Procesos.toleranciatiempo); por conteo: déficit de salidas frente a
               60 / intervalo programado > tolerancia_salidas durante persistencia_horas horas. No se evalúa en la
               primera ni en la última hora de servicio (servicio parcial).
      ALT-008  |z robusto| ≥ z_anomalia en subidas o número de viajes del día frente al mismo tipo de día.
      ALT-009  datos atrasados (≥ periodos_atraso × periodo_ingesta_min), campos obligatorios u horas faltantes.
      ALT-002  ocupación OBSERVADA = factor de carga de la franja × pasajeros / (salidas × puestos) ≥ ocupacion_critica
               en horas con al menos salidas_minimas_ocupacion salidas (no en las de borde), origen «observado».
      ALT-007  variante «ruptura de comportamiento» (RF-009) si el contexto trae serie_diaria: CUSUM de dos lados
               sobre el residuo diario relativo (detectar_rupturas).
    Las horas que cumplen se agrupan en episodios: UNA alerta por episodio, con clave estable (código + ruta +
    inicio del episodio + «obs») para que una ejecución posterior la actualice en lugar de duplicarla.
    Opcionales del contexto: capacidad (puestos por bus; si falta, la del catálogo), factor_carga_por_hora
    ({hora: factor}; si falta, optimizacion.factor_carga_franja) y serie_diaria.
    """
    u = _umbrales(umbrales)
    ctx = dict(contexto or {})
    ctx.setdefault("detectada_en", _ahora())
    horas = [dict(h) for h in (ctx.get("horas") or [])]
    k = max(1, int(float(u["persistencia_horas"])))
    return (_observadas_002(ctx, horas, u) + _observadas_005_007(ctx, horas, u, k) + _observadas_006(ctx, horas, u, k)
            + _observadas_008(ctx, u) + _observadas_009(ctx, u) + _observadas_ruptura(ctx, u))


def contexto_hora(inicio, observado, esperado=None, p10=None, p90=None, salidas_observadas=None,
                  salidas_esperadas=None, headway_programado_min=None, nueva=True, variables_influyentes=None,
                  borde_servicio=None):
    """Una hora cerrada del contexto observado (ayuda para el ciclo, el backtest y las pruebas). borde_servicio: la
    primera o la última hora de servicio (4 h y 20 h), con servicio parcial; por omisión se deduce de la hora."""
    if borde_servicio is None:
        borde_servicio = getattr(inicio, "hour", None) in HORAS_BORDE
    return {"inicio": inicio, "fin": inicio + timedelta(hours=1), "observado": observado, "esperado": esperado,
            "p10": p10, "p90": p90, "salidas_observadas": salidas_observadas, "salidas_esperadas": salidas_esperadas,
            "headway_programado_min": headway_programado_min, "nueva": nueva, "borde_servicio": bool(borde_servicio),
            "variables_influyentes": variables_influyentes or []}


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


def _vacio(texto):
    return not texto or not str(texto).strip()


def _validar_accion(estado, accion, usuario):
    if estado not in TRANSICIONES:
        raise TransicionInvalida(f"Estado desconocido: {estado!r}.")
    if accion not in ACCIONES:
        raise TransicionInvalida(f"Acción desconocida: {accion!r}. Válidas: {', '.join(ACCIONES)}.")
    if _vacio(usuario):
        raise ValueError("Toda acción sobre una alerta requiere el usuario que la hace.")


def _estado_al_comentar(estado, comentario):
    """comentar no cambia el estado; no se permite en un estado final ni sin texto."""
    if estado in ESTADOS_FINALES:
        raise TransicionInvalida(f"No se puede comentar una alerta {estado}.")
    if _vacio(comentario):
        raise ValueError("comentar requiere un comentario.")
    return estado


def _estado_tras_transicion(estado, accion, asignado_a):
    permitidas = TRANSICIONES[estado]
    if accion not in permitidas:
        raise TransicionInvalida(f"No se puede '{accion}' una alerta en estado '{estado}'. "
                                 f"Permitidas: {', '.join(permitidas) or 'ninguna (estado final)'}.")
    if accion == "asignar" and _vacio(asignado_a):
        raise ValueError("asignar requiere asignado_a.")
    return permitidas[accion]


def cambiar_estado(alerta, accion, usuario, comentario=None, asignado_a=None):
    """Aplica `accion` (reconocer|asignar|comentar|cerrar|descartar) y devuelve (estado_nuevo, entrada_historial).

    No modifica `alerta` (dict, objeto con .estado o el estado como texto). Lanza TransicionInvalida si la acción
    no está
    permitida desde el estado actual y ValueError si faltan datos (usuario, asignado_a para asignar, comentario para
    comentar)."""
    estado = _estado_de(alerta)
    _validar_accion(estado, accion, usuario)
    if accion == "comentar":
        nuevo = _estado_al_comentar(estado, comentario)
    else:
        nuevo = _estado_tras_transicion(estado, accion, asignado_a)
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
