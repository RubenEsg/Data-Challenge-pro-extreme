"""Resultado («¿Qué gana Sobusa?»): cuánto se ahorra en un año con el plan que reasigna (el recomendado), con sus dos saldos y
las salidas que cambian; del ahorro al saldo; dónde se quitan y dónde se ponen; la comparación honesta con el plan que
recorta; las palancas que pagan solas (aparte, sin sumarlas) y cuánto depende todo de β.

Tablero al estilo de la referencia (DISENO.md): encabezado enorme, una rejilla de tarjetas con la protagonista (el ahorro con
sus dos saldos, nunca separados) y la tarjeta de salidas, la cascada con la tarjeta de lectura, y debajo el detalle. Cada
tarjeta lleva su botón «…» con la tabla gemela y las fuentes. Colores solo por rol (ui.traza, ui.leyenda): lo que proponemos
en azul (sólido el foco, rayado lo demás de la familia), el plan que recorta en rosa. Ninguna cifra está escrita a mano: salen
de datos/ahorro_anual.json (preparar_datos.py, cada una con su archivo y su clave en «origen»), de datos/sensibilidad_beta.csv
y de datos/cifras_app.json."""
import math
import re

import dash
import plotly.graph_objects as go
from dash import Input, Output, callback, html

import datos_app as D
import ui
from ui import ROL, con_signo, num

dash.register_page(__name__, path="/resultado", name="Resultado", order=4, title="Resultado · Sobusa Despacho")

PLANES = {"reasigna": "Plan que reasigna", "recorta": "Plan que recorta"}
# Pasos de la cascada: del ahorro en operación al saldo de cada contabilidad (los saldos van sólidos; los pasos, rayados)
PASOS = ["Ahorro en operación", "Pasajes perdidos", "Saldo conservador", "Pasajes ganados", "Ajuste de método (regla lineal)",
         "Saldo simétrico"]
PASOS_EJE = ["Ahorro en<br>operación", "Pasajes<br>perdidos", "Saldo<br>conservador", "Pasajes<br>ganados",
             "Ajuste de método<br>(regla lineal)", "Saldo<br>simétrico"]
ES_SALDO = [False, False, True, False, False, True]
# Constantes de definición (DISENO.md §6, reglas 6 y 10): la lectura de β y la unidad del redondeo a un decimal
QUITA, CADA = 10, 100
REDONDEO = 0.1
UMBRAL_FRANJA = 0.85     # una hora entra en la franja del título si llega a este múltiplo del máximo del día
ALTO_LIENZO = 320        # px: alto de .grafico__lienzo (DISENO.md §7), para que las barras horizontales no pasen de 24 px
# Cómo se nombra cada tipo de día de los datos en una frase (DISENO.md §6, regla 13: «Domingo o festivo»)
UN_DIA = {"Laboral": "un día laboral promedio", "Sábado": "un sábado promedio", "Domingo/festivo": "un domingo o festivo promedio"}
LOS_DIAS = {"Laboral": "los días laborales", "Sábado": "los sábados", "Domingo/festivo": "los domingos y festivos"}


# --- utilidades -----------------------------------------------------------------------------------------------------
def _tipo(t):
    """Rótulo del tipo de día de los datos para la pantalla («Domingo/festivo» → «Domingo o festivo»)."""
    return t.replace("/", " o ")


def _un_dia(t):
    return UN_DIA.get(t, f"un día {_tipo(t).lower()} promedio")


def _los_dias(t):
    return LOS_DIAS.get(t, f"los días de tipo {_tipo(t).lower()}")


def _mayuscula(texto):
    return texto[:1].upper() + texto[1:]


def _rango(texto):
    """Rangos escritos con guion en los datos («7-15 h») con la raya de rango («7–15 h»)."""
    return re.sub(r"(\d)-(\d)", lambda m: f"{m.group(1)}–{m.group(2)}", texto)


def _y(partes):
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def _franjas(valores, horas):
    """Horas en las que `valores` llega a UMBRAL_FRANJA × su máximo, agrupadas en franjas seguidas: «a las 5 h y de 17 a 19 h»."""
    tope = max(valores)
    sel = [int(h) for h, v in zip(horas, valores) if tope > 0 and v >= UMBRAL_FRANJA * tope]
    grupos = []
    for h in sel:
        if grupos and h == grupos[-1][-1] + 1:
            grupos[-1].append(h)
        else:
            grupos.append([h])
    return _y([f"a las {g[0]} h" if len(g) == 1 else f"de {g[0]} a {g[-1]} h" for g in grupos])


def _fuentes(*rutas, otros=()):
    """Rutas de las fuentes de una tarjeta: el archivo que lee la pantalla y los del proyecto de donde salen sus cifras."""
    org = D.ahorro_anual()["origen"]
    archivos = ["datos/ahorro_anual.json"] + D.fuentes_ahorro(*[r for r in rutas if r in org])
    for o in otros:
        if o and o not in archivos:
            archivos.append(o)
    return archivos


def _archivo(pantalla, clave):
    return D.cifra(pantalla, clave).get("archivo", "")


# --- fila 1: el ahorro con sus dos saldos y las salidas -------------------------------------------------------------
def _quien(A, plan="reasigna"):
    """Qué tipos de día ganan salidas y cuáles pierden con el plan («Los días laborales ganan salidas; los sábados … pierden.»)."""
    ganan, pierden = [], []
    for t, td in A["por_hora"]["tipos_dia"].items():
        a, b = td["salidas_dia"]["hoy"], td["salidas_dia"][plan]
        (ganan if b > a else pierden if b < a else []).append(_los_dias(t))
    frases = ([f"{' y '.join(ganan)} ganan salidas"] if ganan else []) + ([f"{' y '.join(pierden)} pierden"] if pierden else [])
    return _mayuscula("; ".join(frases)) + "."


def _tabla_tipos(A, plan="reasigna"):
    """Salidas por día de cada tipo de día, hoy → con el plan, con el cambio en %."""
    filas = []
    for t, td in A["por_hora"]["tipos_dia"].items():
        a, b = td["salidas_dia"]["hoy"], td["salidas_dia"][plan]
        filas.append([_tipo(t), num(a, 1), num(b, 1), f"{con_signo((b - a) / a * CADA, 1)} %"])
    return ui.tabla(["Salidas por día", "Hoy", "Con el plan", "Cambio"], filas, compacta=True)


def _heroe(A):
    h, r = A["planes"]["hoy"], A["planes"]["reasigna"]
    pct = r["ahorro_pct_costo"]
    piloto = D.valor("inicio", "inicio_piloto_resumen")
    # Los dos saldos son los bordes de un rango (ver Inicio): cada uno dice qué supone y el chip va neutro.
    saldos = [
        ui.saldo("Peor caso del año · las salidas nuevas no atraen a nadie", r["saldo_conservador_Mcop"],
                 "Cuenta los pasajes que se pierden donde se quitan salidas y ninguno de los que se ganan donde se ponen "
                 "(contabilidad conservadora). Es un supuesto extremo, no lo que se espera: es el piso.", extremo="peor caso"),
        ui.saldo("Mejor caso del año · las salidas nuevas atraen pasajeros", r["saldo_simetrico_Mcop"],
                 "Cuenta también los que se ganan donde se ponen, con la misma β (que no se ha medido al poner salidas), y "
                 "mide los perdidos con una regla lineal (contabilidad simétrica): es el techo.", extremo="mejor caso"),
    ]
    entre = html.P(f"El saldo del año queda entre esos dos casos, y dónde cae depende de cómo respondan los pasajeros. Por eso la "
                   f"propuesta no es cambiar el horario de una vez: es un piloto de {num(piloto['semanas'])} semanas que lo mide "
                   f"antes. En el piloto se juega un saldo de entre {con_signo(piloto['saldo_min_Mcop'], 1)} y "
                   f"{con_signo(piloto['saldo_max_Mcop'], 1)} M COP, con el {num(piloto['pct_pax_anual_cra54'], 2)} % de los "
                   "pasajeros de un año de CRA 54.", className="heroe__texto")
    pie = ui.nota(f"Lo que Sobusa deja de pagar en kilómetros ({con_signo(r['ahorro_km_Mcop'])} M COP) y en horas de conductor "
                  f"({con_signo(r['ahorro_conductor_Mcop'])} M COP, si al conductor se le paga por hora): el {num(pct, 1)} % de lo "
                  f"que hoy le cuestan ({num(h['costo_km_conductor_Mcop'])} M COP al año). El plan que reasigna frente a hoy: tres "
                  "rutas, salidas de 2025 y precios de 2026.")
    # La misma tarjeta protagonista que Inicio (título y «…» con las fuentes arriba a la derecha): valor con su chip →
    # una línea → los dos saldos → el pie. El ahorro nunca va sin sus saldos.
    principal = html.Div([
        html.P([html.Span(con_signo(r["ahorro_operacion_Mcop"]), className="heroe__numero"),
                html.Span("M COP al año", className="heroe__unidad"),
                ui.chip_cambio(-pct, f"{con_signo(-pct, 1)} % en el costo de km y conductor")], className="heroe__valor"),
        html.P("No es ganancia: falta lo que se juega en pasajes, abajo, entre su peor y su mejor caso.", className="heroe__texto"),
    ], className="heroe__principal")
    fuentes = _fuentes("planes.reasigna.ahorro_operacion_Mcop", "planes.reasigna.ahorro_km_Mcop", "planes.reasigna.ahorro_conductor_Mcop",
                       "planes.hoy.costo_km_conductor_Mcop", "planes.reasigna.ahorro_pct_costo", "planes.reasigna.saldo_conservador_Mcop",
                       "planes.reasigna.saldo_simetrico_Mcop", otros=[_archivo("inicio", "inicio_piloto_resumen")])
    return ui.tarjeta([principal, html.Div(saldos, className="saldos"), html.Div([entre, pie], className="heroe__pie")],
                      titulo="Ahorro en operación · plan que reasigna", fuentes=fuentes, clase="heroe cifra--hero", id="rs-heroe")


def _salidas(A):
    """Tarjeta lateral (como «Gross Volume»): las salidas al año con su chip, las que se quitan y se ponen en barras rayadas
    (partes de las salidas que cambian) y quién gana y quién pierde; en «…», la tabla por tipo de día y las fuentes."""
    h, r = A["planes"]["hoy"], A["planes"]["reasigna"]
    s, q, u = r["menos_salidas_anio"], r["quitadas_anio"], r["puestas_anio"]
    cifra = ui.cifra("Plan que reasigna", con_signo(-s), "frente a hoy",
                     variacion=f"De {num(h['salidas_anio'])} a {num(r['salidas_anio'])}; {con_signo(-r['menos_salidas_dia'], 1)} por día",
                     flecha=-s, chip=ui.chip_cambio(-s, f"{con_signo(r['var_salidas_pct'], 1)} %"), clase="cifra--llana")
    total = q + u
    rayas = html.Div([
        ui.barra_rayas("Se quitan", f"{num(q)} al año · {num(r['quitadas_dia'], 1)} por día", q / total if total else 0, "modelo"),
        ui.barra_rayas("Se ponen", f"{num(u)} al año · {num(r['puestas_dia'], 1)} por día", u / total if total else 0, "modelo"),
    ], className="rayas-lista")
    nota = ui.nota("Las barras reparten las salidas que cambian. Se quitan donde el pronóstico prevé buses más vacíos y se ponen "
                   "donde los prevé más llenos: el plan reasigna, mueve salidas de hora en vez de recortarlas.")
    dias = ui.nota(f"No es igual todos los días. {_quien(A)}")
    return ui.bloque("Salidas al año", [cifra, rayas, nota, dias], detalles=[_tabla_tipos(A)],
                     fuentes=_fuentes("planes.hoy.salidas_anio", "planes.reasigna.salidas_anio", "planes.reasigna.quitadas_anio",
                                      "planes.hoy.km_anio", "planes.reasigna.km_anio", "planes.reasigna.buses_hora_anio",
                                      "planes.hoy.costo_km_conductor_Mcop", "planes.reasigna.ahorro_km_Mcop",
                                      "planes.reasigna.saldo_conservador_Mcop", "por_hora.tipos_dia.Laboral.reasigna"),
                     id="rs-salidas")


def _horas_km(A):
    h, p = A["planes"]["hoy"], A["planes"]["reasigna"]
    bh, km = p["delta_buses_hora_anio"], p["delta_km_anio"]
    return ui.tarjeta(ui.cambios([
        ui.antes_despues("Horas de bus al año", num(h["buses_hora_anio"], 1), num(p["buses_hora_anio"], 1),
                         ui.chip_cambio(-bh, f"{con_signo(-bh, 1)} al año · {con_signo(p['var_buses_hora_pct'], 1)} %")),
        ui.antes_despues("Kilómetros al año", num(h["km_anio"]), num(p["km_anio"]),
                         ui.chip_cambio(-km, f"{con_signo(-km)} al año · {con_signo(p['var_km_pct'], 1)} %")),
    ]), titulo="Horas de bus y kilómetros", subtitulo="Todo el año, hoy y con el plan que reasigna.",
        fuentes=_fuentes("planes.hoy.km_anio", "planes.reasigna.km_anio", "planes.reasigna.buses_hora_anio"))


def _rutas(A):
    pr, P = A["por_ruta"], A["planes"]
    gana = [x for x in pr["rutas"] if pr[x]["reasigna"]["salidas_anio"] > pr[x]["hoy"]["salidas_anio"]]
    cede = [x for x in pr["rutas"] if pr[x]["reasigna"]["salidas_anio"] < pr[x]["hoy"]["salidas_anio"]]
    lectura = "; ".join(t for t in (f"{' y '.join(gana)} {'gana' if len(gana) == 1 else 'ganan'} salidas" if gana else "",
                                    f"{' y '.join(cede)} {'cede' if len(cede) == 1 else 'ceden'} salidas" if cede else "") if t)
    filas = []
    for ruta in pr["rutas"]:
        a, b = pr[ruta]["hoy"]["salidas_anio"], pr[ruta]["reasigna"]["salidas_anio"]
        filas.append([ruta, num(a), num(b), ui.chip_cambio(b - a, con_signo(b - a))])
    a, b = P["hoy"]["salidas_anio"], P["reasigna"]["salidas_anio"]
    tabla = ui.tabla(["Ruta", "Hoy", "Con el plan", "Cambio"], filas, total=["Tres rutas", num(a), num(b), ui.chip_cambio(b - a, con_signo(b - a))],
                     muestras=list(pr["rutas"]), ocultar_movil=(1,))
    return ui.tarjeta(tabla, titulo="Por ruta, en todo el año", subtitulo=f"Salidas al año: {lectura}.",
                      fuentes=_fuentes("planes.hoy.salidas_anio", "planes.reasigna.salidas_anio", "por_ruta.SILENCIO.reasigna.salidas_anio"))


# --- fila 2: del ahorro al saldo, y la lectura de β --------------------------------------------------------------------
def _pasos(p):
    return [p["ahorro_operacion_Mcop"], -p["pasajes_perdidos_Mcop"], p["saldo_conservador_Mcop"], p["simetrica"]["ganados_Mcop"],
            p["dif_regla_perdidos_Mcop"], p["saldo_simetrico_Mcop"]]


def _bases(v):
    """Dónde empieza cada barra: los pasos parten de donde llegó el anterior; los saldos, del cero."""
    return [0, v[0], 0, v[2], v[2] + v[3], 0]


def _figura_cascada(A, plan="reasigna"):
    v = _pasos(A["planes"][plan])
    base = _bases(v)
    extremos = [0.0] + [b + x for b, x in zip(base, v)] + base
    lo, hi = min(extremos), max(extremos)
    span = hi - lo
    rango = [lo - 0.45 * span, hi + 0.06 * span]     # aire a la izquierda para el valor de las barras que bajan (también a 400 px)
    paso = ui.paso_redondo(max(abs(lo), abs(hi)), 2)
    vals, textos = ui.marcas(math.ceil(rango[0] / paso) * paso, rango[1], paso, signo=True)
    ancho = ui.ancho_barra(len(PASOS), ALTO_LIENZO)
    fig = go.Figure()
    # los pasos rayados en azul (la familia del plan) y los dos saldos sólidos: son el foco, como la columna de «Payments»
    for es_saldo, forma in ((False, "rayada"), (True, "barra")):
        idx = [i for i, s in enumerate(ES_SALDO) if s == es_saldo]
        fig.add_trace(go.Bar(
            y=[PASOS_EJE[i] for i in idx], x=[v[i] for i in idx], base=[base[i] for i in idx], orientation="h",
            name="Saldos" if es_saldo else "Pasos", **ui.traza("modelo", forma, ancho=ancho),
            text=[con_signo(v[i]) for i in idx], textposition="outside", cliponaxis=False,
            textfont=ui.fuente_svg("tinta" if es_saldo else "tinta_2", "--t-s"),
            **ui.hover("", [v[i] for i in idx], "M COP al año", signo=True, categorias=[PASOS[i] for i in idx])))
    fig.update_layout(barmode="overlay", hovermode="closest", margin_r=ui.MARGEN_ETIQUETAS)
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=PASOS_EJE, showgrid=False,
                     tickfont=ui.fuente_svg("tinta_2"))
    fig.update_xaxes(range=rango, showgrid=True, gridcolor=ROL["rejilla"], showline=False, tickvals=vals, ticktext=textos)
    ui.linea_cero(fig, "x")
    ui.unidad_eje(fig, "M COP al año")
    return fig


def _cascada(A):
    P, beta = A["planes"], A["convenciones"]["beta"]["central"]
    p = P["reasigna"]
    v = _pasos(p)
    w = _pasos(P["recorta"])
    titulo = (f"Del ahorro al saldo: {con_signo(p['saldo_conservador_Mcop'])} M COP con la contabilidad conservadora y "
              f"{con_signo(p['saldo_simetrico_Mcop'])} con la simétrica")
    sub = (f"El ahorro en operación es el mismo en las dos contabilidades; cambia lo que se cuenta en pasajes. Plan que reasigna, en "
           f"M COP al año, con β = {num(beta, 2)}: cada paso suma o resta a partir del ahorro en operación, y los dos saldos parten "
           "del cero.")
    etiqueta = ("Del ahorro al saldo del año, plan que reasigna, en M COP al año: "
                + "; ".join(f"{n} {con_signo(x)}" for n, x in zip(PASOS, v)) + ".")
    lectura = (f"La conservadora se queda en la tercera barra ({num(p['pax_en_riesgo_dia']['central'])} pasajeros por día en riesgo). "
               f"La simétrica suma los pasajes que se ganan donde se ponen salidas ({con_signo(p['pax_netos_dia_simetrico'])} pasajeros "
               "netos por día), con la misma β con que se pierden, y eso no se ha medido; el ajuste de método "
               f"({con_signo(p['dif_regla_perdidos_Mcop'])}) es lo que cuenta de menos la regla lineal, no un efecto del plan.")
    tabla = ui.tabla(["Paso", "Plan que reasigna", "Plan que recorta"],
                     [[n, con_signo(x), con_signo(y)] for n, x, y in zip(PASOS, v, w)], compacta=True)
    return ui.grafico(_figura_cascada(A), titulo, sub, etiqueta, tabla,
                      leyenda=[("Pasos", "modelo", "rayada"), ("Saldos del plan que reasigna", "modelo", "foco")],
                      nota=lectura, resumen_tabla="Ver los datos (los dos planes, M COP al año)", id="rs-cascada",
                      fuentes=_fuentes("planes.reasigna.ahorro_operacion_Mcop", "planes.reasigna.pasajes_perdidos_Mcop",
                                       "planes.reasigna.simetrica.ganados_Mcop", "planes.recorta.simetrica.ganados_Mcop",
                                       "planes.reasigna.dif_regla_perdidos_Mcop"))


def _lectura(A):
    """La tarjeta de lectura (una por pantalla): de qué depende dónde cae el saldo entre los dos, con β y el piloto."""
    r, b = A["planes"]["reasigna"], A["convenciones"]["beta"]
    semanas = D.valor("inicio", "inicio_piloto_resumen")["semanas"]
    texto = (f"β es la elasticidad medida de los pasajeros a las salidas (rango creíble {num(b['bajo'], 2)} a {num(b['alto'], 2)}). "
             f"Con ella, el saldo real queda entre los dos: la conservadora ({con_signo(r['saldo_conservador_Mcop'])} M COP) es el piso "
             f"y la simétrica ({con_signo(r['saldo_simetrico_Mcop'])} M COP), el techo. Dónde cae depende de cómo responden los "
             "pasajeros: cuántos dejan de viajar donde se quitan salidas y si las que se ponen atraen viajeros. Eso es lo que "
             f"mediría el piloto de {semanas} semanas.")
    return ui.tarjeta_insight(f"β = {num(b['central'], 2)}", "El saldo depende de cómo responden los pasajeros.", texto,
                              chip_="Lectura", id="rs-lectura")


# --- dónde se quitan y dónde se ponen ------------------------------------------------------------------------------------
def _figura_horas(A, tipo, plan="reasigna"):
    ph = A["por_hora"]
    td = ph["tipos_dia"][tipo]
    x = [f"{h} h" for h in ph["horas"]]
    q, u, hoy, pl = td["quitadas"][plan], td["puestas"][plan], td["hoy"], td[plan]
    # el mismo eje para los tres tipos de día (el cambio se ve en las barras, no en el eje)
    tope = max(max(max(t["quitadas"][plan]), max(t["puestas"][plan])) for t in ph["tipos_dia"].values())
    paso = ui.paso_redondo(tope)
    lim = math.ceil(tope / paso) * paso
    vals, textos = ui.marcas(-lim, lim, paso, signo=True)
    ancho = ui.ancho_barra(len(x))
    fig = go.Figure()
    # las dos son del plan: lo que se pone, sólido (el foco); lo que se quita, rayado en el mismo azul
    fig.add_trace(go.Bar(x=x, y=u, name="Se ponen", **ui.traza("modelo", "barra", ancho=ancho),
                         **ui.hover_texto([f"Se ponen: <b>{num(b, 1)}</b> salidas<br>Hoy {num(c, 1)} → con el plan {num(d, 1)}"
                                           for b, c, d in zip(u, hoy, pl)])))
    fig.add_trace(go.Bar(x=x, y=[-v for v in q], name="Se quitan", **ui.traza("modelo", "rayada", ancho=ancho),
                         **ui.hover("Se quitan", q, "salidas", 1)))
    # la banda clara de la referencia, detrás de la hora que más cambia (la de más salidas puestas o quitadas)
    foco = max(range(len(x)), key=lambda i: max(u[i], q[i]))
    ui.banda_foco(fig, x[foco], x)
    fig.update_layout(barmode="relative", hovermode="x unified")
    fig.update_xaxes(tickvals=x[::2])
    fig.update_yaxes(range=[-lim * 1.04, lim * 1.04], tickvals=vals, ticktext=textos)
    ui.linea_cero(fig)
    ui.unidad_eje(fig, f"salidas en la hora ({_un_dia(tipo)[3:]})")
    return fig


def _horas(A, tipo, plan="reasigna"):
    """Figura, título-mensaje, subtítulo, tabla gemela y aria-label del gráfico por hora para un tipo de día."""
    ph = A["por_hora"]
    td = ph["tipos_dia"][tipo]
    q, u = td["quitadas"][plan], td["puestas"][plan]
    horas = ph["horas"]
    hq, hu = horas[q.index(max(q))], horas[u.index(max(u))]
    qd, ud = td["quitadas_dia"][plan], td["puestas_dia"][plan]
    a, b = td["salidas_dia"]["hoy"], td["salidas_dia"][plan]
    if qd > ud:
        titulo = (f"{_mayuscula(_los_dias(tipo))} el plan quita más salidas de las que pone: {num(qd, 1)} frente "
                  f"a {num(ud, 1)} al día ({con_signo((b - a) / a * CADA, 1)} %)")
    else:
        titulo = f"Se ponen salidas {_franjas(u, horas)} y se quitan {_franjas(q, horas)}"
    sub = (f"{_mayuscula(_un_dia(tipo))} de 2025 ({td['dias']} días), tres rutas: se quitan {num(qd, 1)} salidas y "
           f"se ponen {num(ud, 1)}; el día pasa de {num(a, 1)} a {num(b, 1)} salidas.")
    etiqueta = (f"Salidas que el plan que reasigna quita y pone en cada hora de {_un_dia(tipo)} de 2025, tres rutas. Se quitan "
                f"{num(qd, 1)} y se ponen {num(ud, 1)} por día. Donde más se quitan es a las {hq} h ({num(max(q), 1)}) y donde más se "
                f"ponen, a las {hu} h ({num(max(u), 1)}).")
    filas = [[f"{h} h", num(c, 1), num(d, 1), num(e, 1), num(f, 1)] for h, c, d, e, f in zip(horas, td["hoy"], td[plan], q, u)]
    tabla = ui.tabla(["Hora", "Hoy", "Con el plan", "Se quitan", "Se ponen"], filas,
                     total=["Todo el día", num(a, 1), num(b, 1), num(qd, 1), num(ud, 1)], compacta=True)
    return _figura_horas(A, tipo, plan), titulo, sub, tabla, etiqueta


def _seccion_horas(A):
    tipos = list(A["por_hora"]["tipos_dia"])
    fig, titulo, sub, tabla, etiqueta = _horas(A, tipos[0])
    grafico = ui.grafico(fig, titulo, sub, etiqueta, tabla,
                         leyenda=[("Se ponen (hacia arriba)", "modelo", "foco"), ("Se quitan (hacia abajo)", "modelo", "rayada")],
                         nota=f"La banda clara marca la hora que más cambia. Promedios por día con un decimal: una fila o el total pueden "
                              f"diferir en {num(REDONDEO, 1)} por el redondeo.",
                         id="rs-horas", resumen_tabla="Ver los datos (salidas en cada hora del día promedio)",
                         fuentes=_fuentes("por_hora.tipos_dia.Laboral.quitadas.reasigna", "por_hora.tipos_dia.Laboral.reasigna"))
    control = ui.control("Tipo de día", ui.segmentado("rs-tipo", [{"label": _tipo(t), "value": t} for t in tipos], tipos[0]))
    return ui.seccion("Dónde se quitan y dónde se ponen salidas", grafico,
                      "Cada barra suma las tres rutas: en una misma hora el plan puede quitar en una ruta y poner en otra.",
                      controles=control)


# --- reasignar o recortar ------------------------------------------------------------------------------------------------
def _comparacion(A):
    P = A["planes"]
    h, r, c = P["hoy"], P["reasigna"], P["recorta"]
    filas = [
        # rótulo, valores (hoy, reasigna, recorta; None = no aplica), decimales, con signo, cuál es mejor
        ("Salidas al año", (h["salidas_anio"], r["salidas_anio"], c["salidas_anio"]), 0, False, None),
        ("Horas de bus al año", (h["buses_hora_anio"], r["buses_hora_anio"], c["buses_hora_anio"]), 1, False, None),
        ("Kilómetros al año", (h["km_anio"], r["km_anio"], c["km_anio"]), 0, False, None),
        ("Ahorro en operación, M COP al año", (None, r["ahorro_operacion_Mcop"], c["ahorro_operacion_Mcop"]), 0, True, "max"),
        ("Pasajeros por día en riesgo donde se quitan salidas", (None, r["pax_en_riesgo_dia"]["central"], c["pax_en_riesgo_dia"]["central"]),
         0, False, "min"),
        ("Pasajeros netos por día, contabilidad simétrica", (None, r["pax_netos_dia_simetrico"], c["pax_netos_dia_simetrico"]), 0, True, "max"),
        ("Pasajeros por día por encima de la capacidad", (h["pax_sobre_capacidad_dia"], r["pax_sobre_capacidad_dia"],
                                                          c["pax_sobre_capacidad_dia"]), 0, False, "min"),
        ("Espera media, min", (h["espera_min"], r["espera_min"], c["espera_min"]), 2, False, "min"),
        ("Saldo del año en el peor caso (contabilidad conservadora), M COP", (None, r["saldo_conservador_Mcop"], c["saldo_conservador_Mcop"]), 0, True, "max"),
        ("Saldo del año en el mejor caso (contabilidad simétrica), M COP", (None, r["saldo_simetrico_Mcop"], c["saldo_simetrico_Mcop"]), 0, True, "max"),
    ]
    cuerpo = []
    for rotulo, vals, d, signo, criterio in filas:
        validos = [round(x, d) for x in vals if x is not None]
        objetivo = (max(validos) if criterio == "max" else min(validos)) if criterio else None
        unico = criterio and validos.count(objetivo) == 1
        celdas = []
        for x in vals:
            texto = "—" if x is None else con_signo(x, d) if signo else num(x, d)
            # el mejor de la fila lleva la palabra, no un color (el azul es la serie del plan que reasigna); «mejor» va en
            # una segunda línea para que la columna Recorta siga cabiendo a 400 px
            if x is not None and unico and round(x, d) == objetivo:
                texto = html.Span([html.Strong(texto), html.Br(), html.Span("mejor", className="tabla__mejor-txt")])
            celdas.append(texto)
        cuerpo.append([rotulo] + celdas)
    # «(recomendado)» en una segunda línea del mismo tamaño: así la columna Recorta cabe a 400 px sin desplazarse
    return ui.tabla(["", "Hoy", ["Reasigna", html.Br(), "(recomendado)"], "Recorta"], cuerpo, ocultar_movil=(1,), compacta=True)


def _gana_pierde(v):
    return f"gana {num(v)}" if v > 0 else f"pierde {num(-v)}" if v < 0 else "queda igual"


def _honesto(A):
    P, conv = A["planes"], A["convenciones"]
    h, r, c = P["hoy"], P["reasigna"], P["recorta"]
    pm = D.valor("horario", "horario_parametros_milp")
    mejor_caja = c["saldo_conservador_Mcop"] > r["saldo_conservador_Mcop"] and c["saldo_simetrico_Mcop"] > r["saldo_simetrico_Mcop"]
    caja = "en caja su saldo es mejor en las dos contabilidades" if mejor_caja else "en caja su saldo se compara así"
    texto = [
        f"El plan que recorta ahorra más en operación ({con_signo(c['ahorro_operacion_Mcop'])} frente a "
        f"{con_signo(r['ahorro_operacion_Mcop'])} M COP al año, con {num(c['menos_salidas_anio'])} salidas menos al año frente a "
        f"{num(r['menos_salidas_anio'])}) y {caja}: {con_signo(c['saldo_conservador_Mcop'])} frente a "
        f"{con_signo(r['saldo_conservador_Mcop'])} con la conservadora y {con_signo(c['saldo_simetrico_Mcop'])} frente a "
        f"{con_signo(r['saldo_simetrico_Mcop'])} con la simétrica (M COP al año). Esa ventaja supone que al conductor se le paga por "
        f"hora: de los {con_signo(c['ahorro_operacion_Mcop'])} M COP del plan que recorta, {con_signo(c['ahorro_conductor_Mcop'])} son "
        f"horas de conductor (en el que reasigna, {con_signo(r['ahorro_conductor_Mcop'])}); si se le paga por producido, Sobusa no se "
        "ahorra esa parte.",
        f"Lo paga con pasajeros: aun con la contabilidad simétrica {_gana_pierde(c['pax_netos_dia_simetrico'])} pasajeros por día "
        f"(el que reasigna {_gana_pierde(r['pax_netos_dia_simetrico'])}), deja {num(c['pax_sobre_capacidad_dia'])} pasajeros por día "
        f"por encima de la capacidad (hoy {num(h['pax_sobre_capacidad_dia'])}; el que reasigna, {num(r['pax_sobre_capacidad_dia'])}) "
        f"y lleva la espera media a {num(c['espera_min'], 2)} min (hoy {num(h['espera_min'], 2)}; el que reasigna, "
        f"{num(r['espera_min'], 2)}).",
        f"El optimizador valora, además de la operación, la espera y el hacinamiento de los pasajeros, con supuestos del equipo "
        f"({num(pm['VALOR_TIEMPO_ESPERA'])} COP por hora de espera y {num(pm['PENALIDAD_SOBRECARGA'])} COP por pasajero sobre la "
        "capacidad). Con los costos de operación de 2026, de fuentes públicas, elige reasignar; con los costos supuestos al inicio "
        f"({num(conv['supuestos_iniciales']['costo_bus_hora_cop'])} COP por bus-hora) elegía recortar. Cuánto pesan la espera y el "
        "hacinamiento frente a la caja lo decide la gerencia.",
    ]
    return ui.aviso(texto, "canje", "Por qué se recomienda reasignar aunque recortar deje más caja")


def _cupo(A):
    pp = D.cifra("inicio", "inicio_persona_a_persona_saldo")
    v = pp["valor"]
    hoy = D.valor("ciudad", "ciudad_2025_real")["por_dia"]["sobre_capacidad"]
    plan = D.valor("ciudad", "ciudad_2025_plan")["por_dia"]["sobre_capacidad"]
    texto = (f"Estas cifras reparten la carga de cada hora entre todos sus buses. Seguido pasajero por pasajero en los {pp['dias']} "
             f"días de 2025 con GPS, el plan deja {num(plan)} personas por día por encima de la capacidad ({num(hoy)} con el horario "
             f"real, con el mismo cálculo) y el saldo del año queda entre {con_signo(v['saldo_conservador_Mcop'])} y "
             f"{con_signo(v['saldo_simetrico_Mcop'])} M COP. Antes de llevar el plan a la calle hay que añadir al optimizador un cupo "
             "por bus. Este cálculo no tuvo revisión independiente.")
    return ui.aviso(texto, "atencion", "Falta un cupo por bus")


def _seccion_comparar(A):
    tarjeta = ui.tarjeta(_comparacion(A), titulo="Hoy, reasignar y recortar",
                         subtitulo="2025, tres rutas; cada fila dice si es al año o por día. El mejor valor de cada fila va en negrita "
                                   "y dice «mejor»; salidas, horas de bus y kilómetros no son mejores ni peores por sí solos.",
                         fuentes=_fuentes("planes.recorta.salidas_anio", "planes.recorta.saldo_conservador_Mcop", "planes.hoy.espera_min",
                                          "planes.recorta.ahorro_conductor_Mcop", "convenciones.supuestos_iniciales.costo_bus_hora_cop",
                                          otros=(_archivo("horario", "horario_parametros_milp"),
                                                 _archivo("inicio", "inicio_persona_a_persona_saldo"),
                                                 _archivo("ciudad", "ciudad_2025_plan"))),
                         id="rs-comparar")
    return ui.seccion("¿Y si se recorta en vez de reasignar?", [tarjeta, ui.rejilla([_honesto(A), _cupo(A)], "2-1")],
                      "Los dos planes salen del mismo optimizador y se evalúan igual, con los costos de 2026: el que recorta es el "
                      "que elegía con los costos supuestos al inicio.")


# --- palancas ---------------------------------------------------------------------------------------------------------------
def _variacion_saldo(v):
    return ("saldo positivo", "bien") if v > 0 else ("saldo negativo", "mal") if v < 0 else ("saldo nulo", None)


def _seccion_palancas(A):
    pal, beta_c, h = A["palancas"], A["convenciones"]["beta"]["central"], A["planes"]["hoy"]
    d, g, rg = pal["domingos_festivos"], pal["giro_corto_35"], pal["regularizar_cl72"]
    otros = " y ".join(f"{_los_dias(t)[4:]} {con_signo(x['saldo_conservador_Mcop'])}"
                       for t, x in d["plan_recorta_por_tipo_dia"].items() if t != d["tipo_dia"])
    m = re.search(r"\((.*)\)", g["escenario"])
    detalle = _rango(m.group(1)) if m else ""
    nombre_giro = g["escenario"].split(" (")[0].replace(", ", " de ")
    nombre_giro = nombre_giro[:1].lower() + nombre_giro[1:]
    vd, vg = _variacion_saldo(d["saldo_conservador_Mcop"]), _variacion_saldo(g["saldo_conservador_Mcop"])
    fichas = [
        ui.cifra(f"Saldo conservador · {_los_dias(d['tipo_dia'])[4:]} (plan que recorta)", con_signo(d["saldo_conservador_Mcop"]),
                 "M COP al año de saldo", variacion=vd[0], tono=vd[1],
                 nota=f"Recortar solo los {d['dias']} {_los_dias(d['tipo_dia'])[4:]} del año (β = {num(beta_c, 2)}), con "
                      f"{num(d['pax_en_riesgo_dia'])} pasajeros por día en riesgo. Es la única parte de ese plan que paga; en los demás "
                      f"días pierde ({otros} M COP al año)."),
        ui.cifra(f"Saldo conservador · {nombre_giro}", con_signo(g["saldo_conservador_Mcop"]), "M COP al año de saldo",
                 variacion=vg[0], tono=vg[1],
                 nota=f"Buses que regresan antes del final ({detalle}). Entre {con_signo(g['saldo_rango_Mcop']['pesimista'])} y "
                      f"{con_signo(g['saldo_rango_Mcop']['optimista'])} M COP al año entre el escenario pesimista y el optimista "
                      f"(costos, tarifa y β a la vez). {num(g['bajadas_forzadas_dia'])} pasajeros por día laboral tendrían que bajarse "
                      f"antes (no se valoran) y la espera media sube de {num(g['espera_hoy_min'], 2)} a {num(g['espera_despues_min'], 2)} min."),
        ui.cifra("Despacho regular en CL 72", f"{num(rg['espera_hoy_min'], 2)} → {num(rg['espera_despues_min'], 2)}",
                 "min de espera", variacion=f"{con_signo(rg['delta_espera_min'], 2)} min de espera", tono="bien" if rg["delta_espera_min"] < 0 else None,
                 flecha=rg["delta_espera_min"],
                 nota=f"Las mismas salidas de cada día, equiespaciadas, sin pasajeros en riesgo. En caja casi no cambia "
                      f"({con_signo(rg['saldo_conservador_Mcop'])} M COP al año); el tiempo de espera que se ahorra vale "
                      f"{num(rg['valor_social_espera_Mcop'])} M COP al año para los pasajeros, no para Sobusa. Es la simulación del "
                      "despacho día a día en los días laborales de CL 72: no se compara con la espera media de las tres rutas "
                      f"({num(h['espera_min'], 2)} min)."),
    ]
    return ui.seccion("Otras palancas que pagan solas", ui.cifras(fichas),
                      "Cada una se evaluó por separado: no se suman entre sí ni con el plan. El informe trae otra que también paga: "
                      "fijar por escrito un intervalo máximo más largo entre salidas, a cambio de más espera.",
                      fuentes=_fuentes("palancas.domingos_festivos.saldo_conservador_Mcop", "palancas.giro_corto_35.saldo_conservador_Mcop",
                                       "palancas.giro_corto_35.bajadas_forzadas_dia", "palancas.regularizar_cl72.espera_despues_min"))


# --- β ------------------------------------------------------------------------------------------------------------------------
def _beta_tabla():
    s = D.sensibilidad_beta()
    a = s[s["plan"] == "a"].sort_values("beta")       # plan que recorta
    b = s[s["plan"] == "b"].sort_values("beta")       # plan que reasigna
    return list(b["beta"]), list(b["neto_hora_Mcop"]), list(a["neto_hora_Mcop"])


def _grafico_beta(betas, reasigna, recorta):
    beta_c = D.valor("inicio", "inicio_beta")
    rango = D.valor("inicio", "inicio_beta_rango")
    eq = D.valor("inicio", "inicio_beta_equilibrio_d5")
    fig = go.Figure()
    ui.franja(fig, rango["inf"], rango["sup"])
    ui.linea_cero(fig)
    ui.referencia(fig, x=beta_c, texto=f"β central {num(beta_c, 2)}")
    fig.add_trace(go.Scatter(x=betas, y=recorta, name="Plan que recorta", **ui.traza("recorta", "linea", marcadores=True),
                             **ui.hover("Plan que recorta", recorta, "M COP al año", signo=True)))
    fig.add_trace(go.Scatter(x=betas, y=reasigna, name="Plan que reasigna", **ui.traza("modelo", "linea", marcadores=True),
                             **ui.hover("Plan que reasigna", reasigna, "M COP al año", signo=True)))
    fig.add_trace(go.Scatter(x=[eq], y=[0], name="Equilibrio", **ui.traza("recorta", "punto"),
                             **ui.hover_texto([f"Equilibrio del plan que recorta: β = {num(eq, 2)}"])))
    # rótulo del equilibrio abajo a la izquierda del punto: ahí no hay líneas (el plan que recorta va por encima del cero y el
    # que reasigna, muy abajo) y no choca con el rótulo del β central ni con la unidad, también a 400 px
    fig.add_annotation(x=eq, y=0, text=f"equilibrio<br>β = {num(eq, 2)}", showarrow=True, arrowhead=0, ax=-10, ay=14,
                       xanchor="right", yanchor="top", align="right", font=ui.fuente_svg("tinta_2"), arrowcolor=ROL["tinta_3"])
    # el rótulo de la franja, abajo a la derecha dentro de ella: así no cruza la línea del β central ni a 400 px (los extremos
    # del rango están en las marcas del eje, en la ficha de β y en el subtítulo de la sección)
    fig.add_annotation(x=rango["sup"], y=0, yref="paper", text="rango creíble", xanchor="right", yanchor="bottom",
                       xshift=-ui.px("--e-1"), font=ui.fuente_svg("tinta_2"))
    valores = list(reasigna) + list(recorta)
    lo, hi = min(valores), max(valores)
    paso = ui.paso_redondo(max(abs(lo), abs(hi)), 4)
    vals, textos = ui.marcas(math.floor(lo / paso) * paso, math.ceil(hi / paso) * paso, paso, signo=True)
    margen = (max(betas) - min(betas)) * 0.06
    # marcas en los extremos, en los bordes del rango creíble y en el β central (0,50 y 0,55 se pisan a 400 px); los cinco
    # valores de β están en los marcadores, en el texto al pasar el puntero y en la tabla gemela
    marcas_x = sorted({round(x, 4) for x in (min(betas), rango["inf"], beta_c, rango["sup"], max(betas))})
    fig.update_xaxes(tickvals=marcas_x, ticktext=[num(x, 2) for x in marcas_x], range=[min(betas) - margen, max(betas) + margen],
                     hoverformat=".2f")
    fig.update_yaxes(tickvals=vals, ticktext=textos, range=[vals[0] - paso * 0.15, vals[-1] + paso * 0.15])
    ui.unidad_eje(fig, "M COP al año")
    return fig


def _seccion_beta(A):
    b, c = A["convenciones"]["beta"], A["planes"]["recorta"]
    semanas = D.valor("inicio", "inicio_piloto_resumen")["semanas"]
    eq = D.valor("inicio", "inicio_beta_equilibrio_d5")
    betas, reasigna, recorta = _beta_tabla()
    fichas = ui.cifras([
        ui.cifra("Elasticidad β", num(b["central"], 2), None, nota=f"Rango creíble: {num(b['bajo'], 2)} a {num(b['alto'], 2)}.", mini=True),
        ui.cifra("β de equilibrio del plan que recorta", num(c["beta_equilibrio"], 2), None,
                 nota="Por encima de este valor su saldo conservador es negativo.", mini=True),
    ])
    etiqueta = ("Saldo conservador del año según β, en M COP al año. Plan que reasigna: "
                + "; ".join(f"{con_signo(y)} con β {num(x, 2)}" for x, y in zip(betas, reasigna))
                + ". Plan que recorta: " + "; ".join(f"{con_signo(y)} con β {num(x, 2)}" for x, y in zip(betas, recorta))
                + f"; deja de pagar desde β = {num(eq, 2)}.")
    tabla = ui.tabla(["β", "Plan que reasigna", "Plan que recorta"],
                     [[num(x, 2), con_signo(y), con_signo(z)] for x, y, z in zip(betas, reasigna, recorta)], compacta=True)
    grafico = ui.grafico(_grafico_beta(betas, reasigna, recorta),
                         f"El saldo conservador baja con β: el plan que recorta deja de pagar desde β = {num(eq, 2)}",
                         "Saldo del año con la contabilidad conservadora y el conductor pagado por hora, en M COP al año, para cada β "
                         "(eje horizontal). La franja es el rango creíble de β; la línea vertical, el valor central.",
                         etiqueta, tabla,
                         leyenda=[("Plan que reasigna (recomendado)", "modelo", "linea"), ("Plan que recorta", "recorta", "linea")],
                         nota="La fuente no calcula el saldo simétrico con otras β.", resumen_tabla="Ver los datos (M COP al año)",
                         id="rs-beta",
                         fuentes=_fuentes("convenciones.beta.central", "planes.recorta.beta_equilibrio",
                                          otros=("datos/sensibilidad_beta.csv", _archivo("inicio", "inicio_beta_rango"),
                                                 _archivo("inicio", "inicio_piloto_resumen"))))
    falta = ui.aviso("β se midió con salidas que fallaron sin aviso, que dejan un hueco doble entre buses, no con recortes planificados y "
                     "parejos: un recorte planificado podría perder menos pasajeros (β menor) y, si parte de esas fallas fueron viajes "
                     "que sí corrieron sin registro, β estaría más cerca de 1. Por eso el proyecto propone un piloto de "
                     f"{semanas} semanas en la calle, con días sorteados, para medirla antes de cambiar el horario de toda la flota.",
                     "atencion", "Lo que falta saber")
    sub = (f"β = {num(b['central'], 2)}: si se quitan {QUITA} de cada {CADA} salidas de una hora, se pierden "
           f"{num(b['central'] * QUITA)} de cada {CADA} pasajeros de esa hora (rango creíble: {num(b['bajo'], 2)} a {num(b['alto'], 2)}). "
           "Con β más alta se pierden más pasajeros donde se quitan salidas.")
    lado = html.Div([fichas, falta], className="rejilla")
    return ui.seccion("Cuánto depende de β", ui.rejilla([grafico, lado], "2-1"), sub)


# --- qué mide cada cifra -----------------------------------------------------------------------------------------------------
def _glosario(A):
    c, h, ctx = A["convenciones"], A["planes"]["hoy"], A["contexto"]
    pm = D.valor("horario", "horario_parametros_milp")
    return ui.desplegable("Qué mide cada cifra", [
        ui.parrafo(f"M COP = millones de pesos. Los costos de operación son de 2026 y de fuentes públicas, no los propios de Sobusa: "
                   f"{num(c['costo_km_cop'])} COP por km (combustible, mantenimiento, llantas y lubricantes) y "
                   f"{num(c['costo_bus_hora_cop'])} COP por hora de bus, con el conductor pagado por hora. Cada pasaje vale "
                   f"{num(c['tarifa_neta_cop'])} COP netos para Sobusa. La espera ({num(pm['VALOR_TIEMPO_ESPERA'])} COP por hora) y el "
                   f"hacinamiento ({num(pm['PENALIDAD_SOBRECARGA'])} COP por pasajero sobre la capacidad) son supuestos del equipo."),
        ui.parrafo(f"Hoy son las salidas válidas de 2025 en las tres rutas ({num(c['dias_anio'])} días); los planes se comparan en esa "
                   "misma base, día por día y hora por hora."),
        ui.parrafo(f"Ahorro en operación: los kilómetros y las horas de conductor que se dejan de pagar. El porcentaje se calcula sobre "
                   f"lo que hoy cuestan esos kilómetros y horas ({num(h['costo_km_conductor_Mcop'])} M COP al año). No es el costo total: "
                   f"operar las tres rutas costó {num(ctx['costo_operacion_anual_Mcop'])} M COP en 2025 (precios de 2025, otra base), "
                   f"con {num(ctx['costos_fijos_anual_Mcop'])} M COP de costos fijos que ningún plan cambia."),
        ui.parrafo("Pasajeros en riesgo: los que pueden dejar de viajar donde se quitan salidas; cuántos, lo dice β. Contabilidad "
                   "conservadora: solo cuenta los pasajes que se pierden donde se quitan salidas; es el piso. Contabilidad simétrica: "
                   "también cuenta los que se ganan donde se ponen, con la misma β (que no se ha medido), y mide los perdidos con una "
                   "regla lineal, β por la fracción de salidas que se quitan; es el techo."),
        ui.parrafo("Cada cifra de esta pantalla sale de datos/ahorro_anual.json, que escribe preparar_datos.py con el archivo y la clave "
                   "de cada una y comprueba verificar_ahorro.py; la sensibilidad a β, de datos/sensibilidad_beta.csv, y lo demás, de "
                   "datos/cifras_app.json."),
    ])


def layout(**_):
    A = D.ahorro_anual()
    r = A["planes"]["reasigna"]
    arriba = ui.encabezado("¿Qué gana Sobusa?",
                           f"El plan que reasigna ahorra {con_signo(r['ahorro_operacion_Mcop'])} millones de pesos (M COP) al año en "
                           f"operación; con lo que se juega en pasajes, el saldo del año queda entre {con_signo(r['saldo_conservador_Mcop'])} "
                           f"y {con_signo(r['saldo_simetrico_Mcop'])} M COP.", pantalla="resultado")
    # el tablero: filas de tarjetas a 24 px entre sí (la protagonista con sus dos saldos y las salidas; la cascada y la lectura;
    # las horas de bus y los km y las rutas). Debajo, el detalle por secciones.
    # el h2 del tablero queda solo para lectores de pantalla (h1 → h2 → h3 de las tarjetas, sin saltos)
    tablero = html.Div([
        html.H2("Lo que se ahorra en un año con el plan recomendado", className="oculto"),
        ui.rejilla([_heroe(A), _salidas(A)], "2-1", id="rs-fila-1"),
        ui.rejilla([_cascada(A), _lectura(A)], "2-1", id="rs-fila-2"),
        ui.rejilla([_horas_km(A), _rutas(A)], "1-1", id="rs-fila-3"),
    ], className="rejilla")
    return ui.pantalla([arriba, tablero, _seccion_horas(A), _seccion_comparar(A), _seccion_palancas(A), _seccion_beta(A), _glosario(A)])


@callback(Output("rs-horas", "figure"), Output("rs-horas-titulo", "children"), Output("rs-horas-sub", "children"),
          Output("rs-horas-tabla", "children"), Output("rs-horas-lienzo", "aria-label"), Input("rs-tipo", "value"))
def cambiar_tipo(tipo):
    A = D.ahorro_anual()
    if tipo not in A["por_hora"]["tipos_dia"]:
        tipo = next(iter(A["por_hora"]["tipos_dia"]))
    return _horas(A, tipo)
