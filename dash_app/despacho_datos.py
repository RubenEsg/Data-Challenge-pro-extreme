"""Datos de la pantalla Despacho: un día de 2025 reproducido como si fuera en vivo (los mismos archivos de la consola de
despacho del proyecto, sistema_tiempo_real/replay/dias; su esquema está en sistema_tiempo_real/replay/ESQUEMA.md).

Dónde busca los días, en este orden: SOBUSA_PROYECTO/sistema_tiempo_real/replay/dias, ../app_sobusa/sistema_tiempo_real/
replay/dias (así viene en el ZIP de la entrega), ../../sistema_tiempo_real/replay/dias (el proyecto) y, si no hay ninguno,
los seis días de ejemplo empaquetados en datos/despacho/ (los deja ahí preparar_datos.py).

Regla de la consola: a la hora t del reloj no se devuelve nada que el despachador no pudiera saber a esa hora (ninguna salida
posterior a t, ningún resultado del día antes de las 21:00). Cómo se arma cada lista (igual que consola_despacho.html,
ESQUEMA.md «Cómo los usa la consola»):
  · foto vigente = la última con t ≤ reloj;
  · salidas hoy = salidas_real de la foto + el cambio de cada salida entre la foto y el reloj (las que el motor conoce
    después de la foto, las que se saben fallidas, las fallas por GPS que se revierten);
  · despachos hechos = `hechas` de la foto (menos las que ya se saben fallidas) + las salidas que el motor conoce entre la foto
    y el reloj, de los últimos 15 min; y las que se supieron fallidas en esos 15 min, como «fallida»;
  · próximos = proximas_60 de la foto menos las que ya cubrió una salida posterior a la foto; bus = el primer `programados`
    a ±15 min sin salida (ni arranque antes del reloj); «ajustada» con `ajuste`/`ajuste_motivos`; «atrasada» si pasó más de
    1 min sin salida; con datos_ok falso, el horario del plan semanal de la próxima hora («plan»).
Los vehículos son números internos de bus (no son datos personales); aquí no hay nombres de conductores.
Solo biblioteca estándar (y nada de bases de datos)."""
import base64
import bisect
import gzip
import json
import os
import re
from functools import lru_cache
from pathlib import Path

AQUI = Path(__file__).resolve().parent
EMPAQUE = AQUI / "datos" / "despacho"
RUTAS = ["SILENCIO", "CRA 54", "CL 72"]
INICIO = 4 * 3600                      # 04:00
FIN = 21 * 3600                        # 21:00
VENTANA_HECHOS = 15 * 60               # la lista de hechos muestra los de los últimos 15 min (como la consola)
VENTANA_PROG = 15 * 60                 # programados a ±15 min del despacho
HORIZONTE = 60 * 60                    # próximos de la próxima hora
ATRASO = 60                            # «atrasada»: más de 1 min pasado sin salida
FECHA_INICIAL = "2025-06-03"
OCULTAS_EN_FALLA = {"hueco", "plan", "regularidad"}


# --- Dónde están los días ---------------------------------------------------------------------------------------------
def carpeta_dias():
    """Carpeta de la consola con indice.js, o None si solo están los días empaquetados."""
    cands = []
    if os.environ.get("SOBUSA_PROYECTO"):
        cands.append(Path(os.environ["SOBUSA_PROYECTO"]) / "sistema_tiempo_real" / "replay" / "dias")
    cands += [AQUI.parent / "app_sobusa" / "sistema_tiempo_real" / "replay" / "dias",
              AQUI.parent.parent / "sistema_tiempo_real" / "replay" / "dias"]
    for c in cands:
        if (c / "indice.js").is_file():
            return c
    return None


def _json_de_js(texto):
    """El objeto JSON de «window.X = {…};»."""
    return json.loads(texto[texto.index("{"):texto.rstrip().rstrip(";").rindex("}") + 1])


@lru_cache(maxsize=1)
def indice():
    """{meta, mapa, dias, origen}: el índice de la consola (o el empaquetado). `dias` solo trae los días cuyo archivo existe."""
    c = carpeta_dias()
    if c is not None:
        ind = _json_de_js((c / "indice.js").read_text(encoding="utf-8"))
        dias = [d for d in ind["dias"] if (c / f"{d['fecha']}.js").is_file()]
        return {"meta": ind["meta"], "mapa": ind["mapa"], "dias": dias, "origen": str(c)}
    p = EMPAQUE / "indice.json"
    if not p.is_file():
        return {"meta": {"capacidad": 50, "rutas": [{"nombre": r} for r in RUTAS]}, "mapa": {"rutas": {}, "puntos": {}}, "dias": [],
                "origen": None}
    ind = json.loads(p.read_text(encoding="utf-8"))
    dias = [d for d in ind["dias"] if (EMPAQUE / f"{d['fecha']}.json.gz").is_file()]
    return {"meta": ind["meta"], "mapa": ind["mapa"], "dias": dias, "origen": "datos/despacho"}


def hay_datos():
    return bool(indice()["dias"])


def capacidad():
    return int(indice()["meta"].get("capacidad", 50))


def mapa():
    """{rutas: {nombre: [[lat, lon], …]}, puntos: {nombre: [{id, lat, lon, minuto}]}} del índice."""
    return indice()["mapa"]


def dias_disponibles():
    """[{fecha, etiqueta, tipo_dia, ejemplo}] en orden de fecha. La etiqueta es la que se sabe antes de que empiece el día
    (etiqueta_previa: «Receso escolar», no «Caída inesperada»)."""
    return [{"fecha": d["fecha"], "etiqueta": d.get("etiqueta_previa") or d.get("etiqueta"), "tipo_dia": d.get("tipo_dia"),
             "ejemplo": bool(d.get("ejemplo"))} for d in indice()["dias"]]


def fecha_inicial():
    dias = dias_disponibles()
    if any(d["fecha"] == FECHA_INICIAL for d in dias):
        return FECHA_INICIAL
    ej = [d["fecha"] for d in dias if d["ejemplo"]]
    return ej[0] if ej else (dias[0]["fecha"] if dias else None)


def leer_dia_crudo(fecha):
    """El objeto de día tal cual (ESQUEMA.md, sección «dias»)."""
    c = carpeta_dias()
    if c is not None and (c / f"{fecha}.js").is_file():
        s = (c / f"{fecha}.js").read_text(encoding="utf-8")
        return json.loads(gzip.decompress(base64.b64decode(re.findall(r'"([A-Za-z0-9+/=]{100,})"', s)[-1])))
    p = EMPAQUE / f"{fecha}.json.gz"
    if p.is_file():
        return json.loads(gzip.decompress(p.read_bytes()))
    raise FileNotFoundError(f"no hay datos de despacho para {fecha}")


# --- Buses por las calles (dias/calles/, ESQUEMA.md «Buses por las calles») ---------------------------------------------
# El trazado de cada ruta por las calles (rutas.js: lat, lon y metros desde el patio en cada vértice) y, por día, la distancia
# recorrida de cada viaje en el tiempo (AAAA-MM-DD.js: [t0, s0, t1, s1, …], nudos en la salida y en cada punto de control).
# Igual que la consola, la posición entre dos nudos se interpola para dibujar el bus sobre su ruta. Sin estos archivos,
# las funciones devuelven None y la pantalla usa la posición de la foto del motor.
def _carpeta_calles():
    c = carpeta_dias()
    return c / "calles" if c is not None and (c / "calles" / "rutas.js").is_file() else None


@lru_cache(maxsize=1)
def calles_rutas():
    """{nombre: {lat, lon, s, largo_m}}: el trazado de cada ruta por las calles; None si no está."""
    c = _carpeta_calles()
    try:
        if c is not None:
            o = _json_de_js((c / "rutas.js").read_text(encoding="utf-8"))
        elif (EMPAQUE / "calles" / "rutas.json").is_file():
            o = json.loads((EMPAQUE / "calles" / "rutas.json").read_text(encoding="utf-8"))
        else:
            return None
    except (OSError, ValueError):
        return None
    rutas = {r: {"lat": v["lat"], "lon": v["lon"], "s": v["s"], "largo_m": v.get("largo_m")}
             for r, v in (o.get("rutas") or {}).items() if v.get("lat") and len(v["lat"]) == len(v.get("s") or [])}
    return rutas or None


@lru_cache(maxsize=4)
def _calles_dia(fecha):
    """{ruta: [(clave, vehiculo, minuto de salida, [t…], [s…])]} del día; None si falta su archivo."""
    c = _carpeta_calles()
    try:
        if c is not None and (c / f"{fecha}.js").is_file():
            s = (c / f"{fecha}.js").read_text(encoding="utf-8")
            o = json.loads(gzip.decompress(base64.b64decode(re.findall(r'"([A-Za-z0-9+/=]{100,})"', s)[-1])))
        elif (EMPAQUE / "calles" / f"{fecha}.json.gz").is_file():
            o = json.loads(gzip.decompress((EMPAQUE / "calles" / f"{fecha}.json.gz").read_bytes()))
        else:
            return None
    except (OSError, ValueError, IndexError):
        return None
    out = {}
    for r, viajes in (o.get("rutas") or {}).items():
        lista = []
        for clave, trays in viajes.items():
            veh, _, minuto = clave.partition("|")
            for tr in trays:
                if len(tr) >= 4:
                    lista.append((clave, veh, int(minuto) if minuto.isdigit() else None, tr[0::2], tr[1::2]))
        out[r] = lista
    return out


def _interp(x, xs, ys):
    """Interpolación lineal de x en (xs, ys), con xs creciente (como numpy.interp, en la biblioteca estándar)."""
    i = bisect.bisect_right(xs, x)
    if i <= 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1 = xs[i - 1], xs[i]
    return ys[i - 1] if x1 == x0 else ys[i - 1] + (ys[i] - ys[i - 1]) * (x - x0) / (x1 - x0)


def posiciones_calles(fecha, seg, ruta=None):
    """[{vehiculo, ruta, lat, lon, s, salida}] de los viajes en curso en el segundo `seg` (t0 ≤ seg ≤ último t), sobre el
    trazado de su ruta; None si faltan los archivos de calles (la pantalla usa entonces la foto del motor)."""
    R, V = calles_rutas(), _calles_dia(fecha)
    if not R or V is None:
        return None
    t = float(seg)
    out = []
    for r in (RUTAS if ruta in (None, "todas") else [ruta]):
        g = R.get(r)
        if not g:
            continue
        vistos = set()
        for clave, veh, minuto, ts, ss in V.get(r) or []:
            if clave in vistos or not (ts[0] <= t <= ts[-1]):
                continue
            vistos.add(clave)          # despacho duplicado: una sola trayectoria por clave
            s = _interp(t, ts, ss)
            out.append({"vehiculo": veh, "ruta": r, "lat": _interp(s, g["s"], g["lat"]), "lon": _interp(s, g["s"], g["lon"]),
                        "s": s, "salida": hhmm(minuto * 60 if minuto is not None else ts[0])})
    return out


# --- Preparación de un día (una vez por día) --------------------------------------------------------------------------
def _seg(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


def hhmm(seg):
    seg = int(seg)
    return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}"


@lru_cache(maxsize=4)
def dia(fecha):
    """El día preparado: fotos con su segundo, salidas reales con el segundo en que el motor las conoce (c) y en que las
    sabe fallidas (hasta), las fallas por GPS que se revierten (g0, g1) y el horario del plan en segundos."""
    D = leer_dia_crudo(fecha)
    tiempos = [_seg(s["t"]) for s in D["snapshots"]]
    salidas, fallaDe, horario = {}, {}, {}
    for r in RUTAS:
        re_ = (D.get("real") or {}).get(r) or {}
        sl, ss, sc = re_.get("salidas") or [], re_.get("salidas_seg"), re_.get("salidas_conoce")
        temp = {(x[0], x[1]): x for x in re_.get("fallas_temporales") or []}
        lista = []
        for i, x in enumerate(sl):
            s = ss[i] if ss and i < len(ss) and ss[i] is not None else _seg(x[0])
            c = max(s, sc[i]) if sc and i < len(sc) and sc[i] is not None else s
            lista.append({"s": s, "c": c, "veh": str(x[1]), "hasta": float("inf"), "fallida": False})
        for x in re_.get("fallidas") or []:
            c = max(x[2], x[4]) if len(x) > 4 and x[4] is not None else x[2]
            lista.append({"s": x[2], "c": c, "veh": str(x[1]), "hasta": x[3], "fallida": True})
        lista.sort(key=lambda x: (x["c"], x["s"]))
        for x in lista:
            g = temp.get((x["s"], x["veh"]))
            if g:
                x["g0"], x["g1"] = g[2], g[3]
        salidas[r] = lista
        fallaDe[r] = {(x["s"], x["veh"]): x["hasta"] for x in lista if x["fallida"]}
        horario[r] = [_seg(h) for h in ((D.get("plan") or {}).get(r) or {}).get("horario") or []]
    falla_desde, ini = [], None
    for k, s in enumerate(D["snapshots"]):
        if s.get("datos_ok") is False:
            ini = tiempos[k] if ini is None else ini
            falla_desde.append(ini)
        else:
            ini = None
            falla_desde.append(None)
    return {"D": D, "tiempos": tiempos, "salidas": salidas, "c": {r: [x["c"] for x in salidas[r]] for r in RUTAS},
            "fallaDe": fallaDe, "horario": horario, "falla_desde": falla_desde}


def _cuenta(x, t):
    """¿El motor cuenta la salida x como hecha en el segundo t?"""
    return x["c"] <= t < x["hasta"] and not ("g0" in x and x["g0"] <= t < x["g1"])


def _falla(P, k):
    S = P["D"]["snapshots"][k]
    if S.get("datos_ok") is not False:
        return None
    registro = any(a[0] == "datos" and re.match(r"^Solo \d+ salidas registradas", a[2])
                   for r in RUTAS for a in ((S["rutas"].get(r) or {}).get("alertas") or []))
    desde = P["falla_desde"][k] if P["falla_desde"][k] is not None else P["tiempos"][k]
    gps = S.get("cobertura") is not None and S["cobertura"] < 0.5
    if gps:
        texto = f"No llegan los datos de GPS desde las {hhmm(desde)}"
    elif registro:
        texto = f"No llegan los registros de despacho desde las {hhmm(desde)}"
    else:
        texto = (f"Los pasajeros contados no cuadran con lo esperado desde las {hhmm(desde)} (posible falla de los contadores; "
                 "los despachos sí se registran)")
    return {"desde": hhmm(desde), "gps": gps, "registro": registro, "texto": texto + ": despache según el horario del plan semanal."}


def _vacio():
    return [0] * 17


def limpiar_buses(texto):
    """«SOBUSA585» → «585» en los textos del motor (como limpiarVeh de la consola): en la pantalla el bus es «Bus 585»."""
    return re.sub(r"\bSOBUSA0*(\d+)", r"\1", str(texto))


# --- Estado a la hora del reloj ---------------------------------------------------------------------------------------
def estado(fecha, seg, ruta=None):
    """Estado de la consola a la hora `seg` (segundos del día, 04:00–21:00) del día `fecha`; `ruta` None o «todas» = las tres.
    Devuelve solo lo que se sabe a esa hora (ver el docstring del módulo)."""
    P = dia(fecha)
    D = P["D"]
    t = int(min(max(seg, INICIO), FIN))
    k = max(0, bisect.bisect_right(P["tiempos"], t) - 1)
    S, tk = D["snapshots"][k], P["tiempos"][k]
    falla = _falla(P, k)
    rutas = RUTAS if ruta in (None, "todas") else [ruta]
    cap = capacidad()
    pos0 = {r: (mapa().get("puntos", {}).get(r) or [{}])[0] for r in RUTAS}
    hechos, proximos, vehiculos, alertas, por_ruta = [], [], [], [], {}
    hora_actual = min(16, max(0, t // 3600 - 4))
    plan_h, reopt_h, real_h = _vacio(), _vacio(), _vacio()
    for r in rutas:
        e = S["rutas"].get(r) or {}
        sal, cs = P["salidas"][r], P["c"][r]
        iT = bisect.bisect_right(cs, t)
        iK = min(bisect.bisect_right(cs, tk), iT)
        tras = [sal[i] for i in range(iK, iT) if _cuenta(sal[i], t)]
        fd = P["fallaDe"][r]
        vivas = []
        for h in e.get("hechas") or []:
            hasta = h[2] if len(h) > 2 and h[2] is not None else fd.get((h[0], str(h[1])), float("inf"))
            vivas.append({"s": h[0], "veh": str(h[1]), "hasta": hasta})
        vivas = [x for x in vivas if x["hasta"] > t]
        delta = sum((1 if _cuenta(sal[i], t) else 0) - (1 if _cuenta(sal[i], tk) else 0) for i in range(iT))
        hechos_hoy = (e.get("salidas_real") or 0) + delta
        nuevas = [x for x in tras if x["s"] > tk]
        # despachos hechos de los últimos 15 min; como la consola, una salida que el motor ya sabe fallida sale de la lista
        vistos = set()
        for x in [v for v in vivas if t - v["s"] <= VENTANA_HECHOS] + [v for v in tras if t - v["s"] <= VENTANA_HECHOS]:
            if (x["s"], x["veh"]) in vistos or x["s"] > t:
                continue
            vistos.add((x["s"], x["veh"]))
            hechos.append({"seg": x["s"], "hora": hhmm(x["s"]), "ruta": r, "vehiculo": x["veh"], "estado": "hecha"})
        # próximos despachos
        salieron = {str(h[1]) for h in e.get("hechas") or []} | {x["veh"] for x in tras if x["s"] > tk - VENTANA_HECHOS}
        prog = [{"s": _seg(p[0]), "hhmm": p[0], "veh": str(p[1])} for p in e.get("programados") or []
                if str(p[1]) not in salieron and not (len(p) > 2 and p[2] is not None and p[2] <= t)]
        pend = []
        if falla:
            hor = P["horario"][r]
            for s in hor[bisect.bisect_right(hor, t - 60):]:
                if s > t + HORIZONTE:
                    break
                pend.append({"seg": s, "ruta": r, "estado": "plan"})
        else:
            recs = [_seg(h) for h in (e.get("proximas_60") or e.get("proximas") or [])]
            n_cons = min(len(nuevas), len(recs))
            aj = e.get("ajuste") or [0, 0]
            ret, ade = (aj[0] or 0), (aj[1] or 0)
            motivos = (e["ajuste_motivos"] if e.get("ajuste_motivos") is not None
                       else [a[2] for a in e.get("alertas") or [] if a[0] == "regularidad"])
            motivos = [limpiar_buses(m) for m in motivos]
            hueco = next((limpiar_buses(a[2]) for a in e.get("alertas") or [] if a[0] == "hueco"), None)
            for i, s in enumerate(recs[n_cons:]):
                f = {"seg": s, "ruta": r, "estado": "recomendada"}
                if i == 0 and n_cons == 0:
                    if ret > 0 or ade > 0:
                        f.update(estado="ajustada", retraso=ret, adelanto=ade, motivos=list(motivos))
                    if hueco:
                        f["hueco"] = hueco
                if t - s >= ATRASO:
                    f["estado"] = "atrasada"
                pend.append(f)
        usado = [False] * len(prog)
        for f in pend:
            f["hora"], f["vehiculo"], f["programado"] = hhmm(f["seg"]), None, None
            for j, p in enumerate(prog):
                if not usado[j] and abs(p["s"] - f["seg"]) <= VENTANA_PROG:
                    usado[j] = True
                    f["vehiculo"], f["programado"] = p["veh"], p["hhmm"]
                    break
        proximos += pend
        # vehículos en la calle: los de la foto y los que salieron después de la foto (todavía en el patio de salida)
        en_calle = {str(b[0]) for b in e.get("buses") or []}
        for b in e.get("buses") or []:
            vehiculos.append({"vehiculo": str(b[0]), "ruta": r, "lat": b[1], "lon": b[2], "ocupacion": b[3], "ultimo_punto": b[4],
                              "salida": hhmm(b[5] * 60), "min_en_ruta": max(0, t // 60 - b[5]), "recien": False})
        recien = [x for x in nuevas if x["veh"] not in en_calle]
        for x in recien:
            vehiculos.append({"vehiculo": x["veh"], "ruta": r, "lat": pos0[r].get("lat"), "lon": pos0[r].get("lon"), "ocupacion": None,
                              "ultimo_punto": pos0[r].get("id"), "salida": hhmm(x["s"]), "min_en_ruta": max(0, (t - x["s"]) // 60),
                              "recien": True})
        # alertas de la foto (con datos malos, sin las que dependen del registro)
        for a in e.get("alertas") or []:
            if falla and (a[0] in OCULTAS_EN_FALLA or (a[0] == "flota" and re.match(r"^Flota al l[ií]mite", a[2]))):
                continue
            alertas.append({"ruta": r, "tipo": a[0], "nivel": a[1], "mensaje": limpiar_buses(a[2])})
        # salidas por hora: plan semanal, reoptimizado de la foto y lo hecho hasta el reloj
        pl = ((D.get("plan") or {}).get(r) or {}).get("salidas_hora") or _vacio()
        ro = e.get("salidas_reopt_hora") or pl
        # lo hecho por hora = el de la foto + el mismo delta que «salidas hoy» (nuevas, fallidas sabidas y registros tardíos)
        rh = list(e.get("salidas_real_hora") or _vacio())
        for i in range(iT):
            d = (1 if _cuenta(sal[i], t) else 0) - (1 if _cuenta(sal[i], tk) else 0)
            h = sal[i]["s"] // 3600 - 4
            if d and 0 <= h < 17:
                rh[h] += d
        for i in range(17):
            plan_h[i] += pl[i]
            reopt_h[i] += ro[i]
            real_h[i] += rh[i]
        hor = P["horario"][r]
        plan_hasta = (e.get("salidas_plan") or 0) + (bisect.bisect_right(hor, t) - bisect.bisect_right(hor, tk))
        en_ruta = (e.get("en_ruta") or 0) + len(recien)
        por_ruta[r] = {"salidas_hoy": None if falla else hechos_hoy, "salidas_plan": plan_hasta, "en_ruta": en_ruta,
                       "en_patio": max(0, (e.get("en_patio") or 0) - len(recien)), "flota": e.get("flota") or 0,
                       "pax_obs": e.get("pax_obs") or 0, "pax_esp": e.get("pax_esp") or 0, "factor": e.get("factor"),
                       "salidas_foto": e.get("salidas_real") or 0, "ultima": max([x["s"] for x in vivas + tras], default=None)}
    hechos.sort(key=lambda f: (-f["seg"], RUTAS.index(f["ruta"])))
    proximos.sort(key=lambda f: (f["seg"], RUTAS.index(f["ruta"])))
    total = {c: sum(v[c] for v in por_ruta.values()) for c in ("salidas_plan", "en_ruta", "en_patio", "flota", "pax_obs", "pax_esp")}
    total["salidas_hoy"] = None if falla else sum(v["salidas_hoy"] for v in por_ruta.values())
    total["factor"] = (total["pax_obs"] / total["pax_esp"]) if total["pax_esp"] else None
    fin_dia = t >= FIN
    info = {"etiqueta": D.get("etiqueta_previa") or D.get("etiqueta"), "descripcion": D.get("descripcion_previa") or ""}
    if fin_dia:
        info = {"etiqueta": D.get("etiqueta"), "descripcion": D.get("descripcion") or ""}
    return {"fecha": fecha, "seg": t, "hora": hhmm(t), "foto": S["t"], "foto_seg": tk, "datos_ok": S.get("datos_ok") is not False,
            "cobertura": S.get("cobertura"), "aviso": falla["texto"] if falla else None, "falla": falla, "rutas": por_ruta, "total": total,
            "hechos": hechos, "proximos": proximos, "vehiculos": vehiculos, "alertas": alertas, "capacidad": cap,
            "por_hora": {"horas": list(range(4, 21)), "plan": plan_h, "reopt": reopt_h, "real": real_h, "hora_actual": hora_actual},
            "fin_dia": fin_dia, "dia": info, "tipo_dia": D.get("tipo_dia"), "dia_semana": D.get("dia_semana")}
