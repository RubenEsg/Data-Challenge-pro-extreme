"""Horario en vivo: el MILP de D5 se resuelve en el momento (CBC) con la ruta, el día, el pronóstico y los costos elegidos.

Presentación de tablero (DISENO.md; referencia «zentra»): título enorme con los controles en la píldora de la derecha →
panel de parámetros a la izquierda y, a la derecha, la rejilla de tarjetas: chips de estado → seis fichas con su chip de
cambio → «El plan del día» (barras rayadas con la hora pico en foco, la casilla de comparar dentro de la tarjeta) →
carga frente a capacidad y balance del día lado a lado → horario minuto a minuto → «Cómo se calcula». Cada tarjeta lleva
su botón «…» con la tabla gemela y las fuentes. Todo color sale de un rol de ui.py; ninguna cifra se escribe a mano."""
import re
import time

import dash
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, ctx, dcc, html

import ui
from controles import FECHA_INICIAL, mover_fecha, selector_fecha, selector_modelo, selector_ruta
from motor import comun as C
from motor import evaluacion as EV
from motor import plan_base as PB
from ui import NOMBRE_MODELO, ORDEN_MODELOS

dash.register_page(__name__, path="/horario", name="Horario", order=2, title="Horario · Sobusa Despacho")

# --- Parámetros por defecto y textos armados con los datos (DISENO.md §6, regla 12) -----------------------------------
_CF = C.costos_con_fuente()                  # datos/costos_fuente.json (precios 2026)
_CEN = _CF["central"]
_RANGO = _CF["redondeados"]
_P0 = C.param_d5(fuente=True)                # el plan que reasigna (costos con fuente)
_PS = C.param_d5(fuente=False)               # los supuestos iniciales: el plan que recorta
DEF = {"cbh": round(_CEN["bus_hora_conductor"]), "km": round(_CEN["costo_km_evitable"]), "tarifa": round(_CEN["tarifa_efectiva"]),
       "elast": _P0["ELASTICIDAD"], "pen": _P0["PENALIDAD_SOBRECARGA"], "espera": _P0["VALOR_TIEMPO_ESPERA"], "imax": "auto"}
SUPUESTOS = {"cbh": round(_PS["COSTO_BUS_HORA"]), "km": round(_PS["COSTO_KM"]), "tarifa": round(_PS["TARIFA"])}
_BETA = _RANGO["elasticidad_beta"]
BETAS = [_BETA["bajo"], _BETA["central"], _BETA["alto"]]
BETA_INICIAL = _BETA["central"]


def _pasaje():
    """El pasaje de 2026, tal como lo escribe la nota de la tarifa neta en costos_fuente.json."""
    m = re.search(r"Tarifa ([0-9.]+)", str(_RANGO["tarifa_neta_2026"].get("nota", "")))
    return m.group(1).rstrip(".") if m else None


def _rango(clave):
    r = _RANGO[clave]
    return f"{ui.num(r['bajo'])} a {ui.num(r['alto'])}"


def _marcas(valores):
    """Marcas del deslizador en es-CO (las centrales y los supuestos salen de los datos)."""
    return {v: ui.num(v, 0 if float(v).is_integer() else 1) for v in valores}


_PASAJE = _pasaje()
SLIDERS = [
    # id, rótulo, unidad, mínimo, máximo, paso, marcas, decimales
    ("cbh", "Costo por bus-hora", "COP", 10000, 80000, 100, _marcas([10000, DEF["cbh"], SUPUESTOS["cbh"], 80000]), 0),
    ("km", "Costo por km", "COP", 500, 4000, 1, _marcas([1000, DEF["km"], 3000]), 0),
    ("tarifa", "Tarifa neta por pasajero", "COP", 2000, 4500, 1, _marcas([2000, DEF["tarifa"], 4500]), 0),
    ("elast", "Elasticidad del plan", "", 0, 1, 0.05, _marcas([0, DEF["elast"], 1]), 2),
    ("pen", "Penalidad por sobrecarga", "COP por pasajero", 0, 30000, 500, _marcas([0, DEF["pen"], 2 * DEF["pen"], 30000]), 0),
    ("espera", "Valor del tiempo de espera", "COP por hora", 0, 20000, 500, _marcas([0, DEF["espera"], 20000]), 0),
]
AYUDA = {
    "cbh": f"Conductor pagado por hora. Rango del estudio de costos: {_rango('costo_bus_hora')}; supuesto inicial: {ui.num(SUPUESTOS['cbh'])}.",
    "km": f"ACPM, mantenimiento, llantas y lubricantes. Rango: {_rango('costo_km')}; supuesto inicial: {ui.num(SUPUESTOS['km'])}.",
    "tarifa": (f"Lo que retiene Sobusa de un pasaje de {_PASAJE}. " if _PASAJE else "Lo que retiene Sobusa de cada pasaje. ")
              + f"Rango: {_rango('tarifa_neta_2026')}; supuesto inicial: {ui.num(SUPUESTOS['tarifa'])}.",
    "elast": "Peso en el plan del pasaje que se pierde al quitar salidas o se gana al ponerlas.",
    "pen": f"Por cada pasajero sobre los {ui.num(_P0['CAPACIDAD'])} del bus en el punto más lleno.",
    "espera": "Valor de una hora de espera en el paradero.",
}


def _politica_intervalo():
    """«Del día: el de la política de servicio, 10 min laboral y sábado; 15 min domingo o festivo», desde comun.INTERVALO_MAX."""
    grupos = {}
    for tipo, v in C.INTERVALO_MAX.items():
        grupos.setdefault(v, []).append(tipo.replace("/", " o ").lower())
    return "Del día: el de la política de servicio, " + "; ".join(f"{ui.num(v)} min {' y '.join(t)}" for v, t in grupos.items()) + "."


def _nombre_tipo(tipo):
    return str(tipo).replace("/", " o ")


def _con_modelo(m):
    """«la regla manual», «el experimento 1 (primer modelo)», «el experimento 11 (LightGBM)», «el experimento 12 (híbrido)»."""
    n = NOMBRE_MODELO[m]
    return ("la " if m == "B1" else "el ") + n[0].lower() + n[1:]


_SUPUESTOS_TXT = (f"{ui.num(SUPUESTOS['cbh'])} por bus-hora, {ui.num(SUPUESTOS['km'])} por km y tarifa de "
                  f"{ui.num(SUPUESTOS['tarifa'])} COP")
FUENTES_PLAN = ["motor/milp.py", "motor/plan_base.py", "datos/insumos_d5_2025.parquet", "datos/pronosticos_2025.parquet",
                "datos/costos_fuente.json"]
FUENTES_CARGA = ["datos/insumos_d5_2025.parquet", "datos/pronosticos_2025.parquet", "motor/evaluacion.py"]
FUENTES_BALANCE = ["motor/evaluacion.py", "datos/costos_fuente.json"]
FUENTES_HORARIO = ["motor/plan_base.py", "motor/comun.py"]


# --- Pantalla ----------------------------------------------------------------------------------------------------------
def _panel():
    """Panel de parámetros (h2 con el aspecto de --t-l: va antes que la primera sección)."""
    return html.Div([
        html.Div([html.H2("Parámetros del plan", className="panel__titulo"),
                  ui.boton("Restablecer", id="hv-restablecer", tipo="fantasma", icono="canje", pequeno=True)], className="panel__cab"),
        *[ui.deslizador(f"hv-{id_}", rotulo, mn, mx, paso, DEF[id_], marcas=marcas, ayuda=AYUDA[id_])
          for id_, rotulo, _u, mn, mx, paso, marcas, _d in SLIDERS],
        ui.control("Intervalo máximo entre salidas", ui.segmentado(
            "hv-imax", [{"label": "Del día", "value": "auto"}] + [{"label": f"{v}", "value": str(v)} for v in (8, 10, 12, 15, 20)],
            "auto", pequeno=True), ayuda=_politica_intervalo()),
    ], className="panel-parametros")


def _resultados():
    comparar = ui.control("Comparar con", ui.casilla("hv-comparar", [
        {"label": f"Plan que recorta (supuestos iniciales: {_SUPUESTOS_TXT})", "value": "supuestos"},
        {"label": "Oráculo: lo que se habría decidido sabiendo la demanda", "value": "oraculo"}], ["oraculo"], lista=True))
    beta = ui.control("β para el balance", ui.segmentado("hv-beta", [{"label": ui.num(b, 2), "value": b} for b in BETAS],
                                                         BETA_INICIAL, pequeno=True),
                      ayuda="La elasticidad con la que se cuentan los pasajes del balance. No es la «Elasticidad del plan» "
                            "del panel, que es el peso que usa el optimizador para decidir.")
    acciones = [
        ui.boton("Descargar CSV", id="hv-descargar", icono="descargar", pequeno=True),
        dcc.Clipboard(id="hv-copiar", content="", title="Copiar el horario (texto separado por tabuladores)",
                      children=html.Span([ui.icono("tabla", "glifo--s"), "Copiar"], className="boton boton--secundario boton--pequeno"),
                      copied_children=html.Span([ui.icono("bien", "glifo--s"), "Copiado"], className="boton boton--secundario boton--pequeno"),
                      className="copiar"),
    ]
    cap = ui.num(_P0["CAPACIDAD"])
    como = ui.desplegable("Cómo se calcula", [
        html.P(["Para cada ruta y día se resuelve el modelo de optimización de D5 (", html.Code("motor/milp.py"),
                ", copia exacta de ", html.Code("experimentos/D5_optimizacion_milp/milp.py"),
                f"): en cada hora de salida de {C.HORAS[0]} a {C.HORAS[-1]} h elige cuántas salidas hacer, minimizando operación "
                "(bus-hora y km) + espera valorada + sobrecarga esperada + pasajes perdidos o ganados por la elasticidad, con suavidad "
                "entre horas y la flota disponible. Se resuelve con CBC (PuLP) en el momento."], className="parrafo"),
        html.P(["Pronóstico del modelo elegido. D5 se calibró con el pronóstico de E1; la carga del punto más lleno de cada hora "
                "es una lognormal (mu, s). Para planear con otro modelo se usa su pronóstico como pasajeros previstos y se corre la "
                "carga en la misma proporción, hora por hora, como hace ", html.Code("sistema_tiempo_real/motor.py"), ": ",
                html.Code("c = pronóstico del modelo / pronóstico de E1"), ", ", html.Code("mu' = mu + log(c)"),
                " (s no cambia). Con E1, c = 1 y el plan es el publicado (x_corrida_1)."], className="parrafo"),
        html.P("Hoy son las salidas válidas que hizo Sobusa ese día. Las fichas y el balance se cuentan con la demanda que de "
               "verdad llegó (contabilidad ex post de D5): espera = minutos operados / salidas / 2 × (1 + CV²), ponderada por los "
               f"pasajeros reales; pasajeros sobre la capacidad = carga real del punto más lleno − {cap} × salidas.", className="parrafo"),
        html.P("Oráculo: el mismo modelo resuelto con la demanda y la carga que llegaron (no se puede usar para planear; mide "
               "cuánto se acerca el plan a lo mejor posible).", className="parrafo"),
        ui.fuentes(["motor/milp.py", "experimentos/D5_optimizacion_milp/milp.py", "sistema_tiempo_real/motor.py", "motor/evaluacion.py"]),
    ])
    # «El plan del día»: la tarjeta del gráfico (título-mensaje y «…» con la tabla gemela y las fuentes) con la casilla de
    # comparar dentro, entre la cabecera y la leyenda
    salidas = _con_controles(ui.grafico("hv-graf-salidas", "Salidas por hora", None, "Salidas por hora del plan y de hoy.",
                                        fuentes=FUENTES_PLAN), [comparar])
    carga = ui.grafico("hv-graf-carga", "Carga en el punto más lleno", None, "Carga en el punto más lleno frente a la capacidad.",
                       nota="Si la carga del punto más lleno pasa la capacidad que ofrecen los buses de esa hora, esos buses van "
                            "sobrecargados.", alto="alto", fuentes=FUENTES_CARGA)
    # Balance del día (como «Gross Volume»): ahorro en operación en grande y, en la misma tarjeta, sus dos saldos; la tabla
    # del balance va en el «…»
    balance = ui.tarjeta([ui.fila_controles([beta]), html.Div(id="hv-balance", className="panel__grupo")],
                         titulo="Balance del día", subtitulo=html.Span(id="hv-balance-titulo"),
                         detalles=html.Div(id="hv-balance-tabla"), fuentes=FUENTES_BALANCE)
    horario = ui.tarjeta([ui.fila_controles(acciones), html.Div(id="hv-horario", className="resultados")],
                         titulo="Horario minuto a minuto", subtitulo="Salidas válidas equiespaciadas dentro de cada hora.",
                         fuentes=FUENTES_HORARIO)
    return html.Div([
        html.Div([html.Div(id="hv-estado", className="estado-calculo"), html.Div(id="hv-error")]),
        ui.cifras([], clase="cifras--3", id="hv-fichas"),
        salidas,
        ui.rejilla([carga, balance], "1-1"),
        horario,
        como,
        dcc.Download(id="hv-descarga"),
        dcc.Store(id="hv-csv"),
    ], className="resultados")


def _con_controles(figura, controles):
    """Mete una fila de controles en la tarjeta de un gráfico, debajo de su cabecera (como la barra de preguntas dentro de
    «Payments» en la referencia). Solo compone piezas de ui; no añade estilos."""
    partes = list(figura.children)
    figura.children = partes[:1] + [ui.fila_controles(controles)] + partes[1:]
    return figura


def layout(**_):
    controles = [
        ui.control("Ruta", selector_ruta("hv-ruta", "CRA 54")),
        ui.control("Día de 2025", selector_fecha("hv-fecha", FECHA_INICIAL)),
        ui.control("Pronóstico del informe académico", selector_modelo("hv-modelo", modelos=ORDEN_MODELOS, valor="E12",
                                                            nombres={"E1": "Experimento 1 (plan publicado)"})),
    ]
    return ui.pantalla([
        ui.arriba(ui.cabecera("horario", "¿Cuántos buses y cada cuánto?",
                              html.Span("El optimizador de salidas resuelve el día con lo que elijas.", id="hv-respuesta")),
                  controles=controles),
        html.Div([_panel(), dcc.Loading(_resultados(), type="circle", color=ui.ROL["acento"], delay_show=250,
                                        overlay_style={"visibility": "visible", "opacity": 0.45},
                                        parent_className="resultados-carga")], className="laboratorio"),
    ])


# --- valores visibles de los deslizadores ----------------------------------------------------------------------------
@callback([Output(f"hv-{s[0]}-valor", "children") for s in SLIDERS],
          [Input(f"hv-{s[0]}", "drag_value") for s in SLIDERS], [State(f"hv-{s[0]}", "value") for s in SLIDERS])
def mostrar_valores(*args):
    n = len(SLIDERS)
    arrastre, valores = args[:n], args[n:]
    out = []
    for (id_, _r, unidad, *_x, dec), a, v in zip(SLIDERS, arrastre, valores):
        x = a if a is not None else v
        out.append(f"{ui.num(x, dec)} {unidad}".strip() if x is not None else "—")
    return out


@callback([Output(f"hv-{s[0]}", "value") for s in SLIDERS] + [Output("hv-imax", "value")],
          Input("hv-restablecer", "n_clicks"), prevent_initial_call=True)
def restablecer(_n):
    return [DEF[s[0]] for s in SLIDERS] + [DEF["imax"]]


@callback(Output("hv-fecha", "date"), Input("hv-fecha-ant", "n_clicks"), Input("hv-fecha-sig", "n_clicks"),
          State("hv-fecha", "date"), prevent_initial_call=True)
def mover(_a, _s, fecha):
    return mover_fecha(fecha or FECHA_INICIAL, -1 if ctx.triggered_id == "hv-fecha-ant" else +1)


# --- cálculo ---------------------------------------------------------------------------------------------------------
def construir_P(cbh, km, tarifa, elast, pen, espera):
    P = C.param_d5(fuente=True)
    exacto = lambda v, ref: float(ref) if v is not None and abs(float(v) - round(ref)) < 0.5 else float(v)  # noqa: E731
    P["COSTO_BUS_HORA"] = exacto(cbh, _CEN["bus_hora_conductor"])
    P["COSTO_KM"] = exacto(km, _CEN["costo_km_evitable"])
    P["TARIFA"] = exacto(tarifa, _CEN["tarifa_efectiva"])
    P["ELASTICIDAD"], P["PENALIDAD_SOBRECARGA"], P["VALOR_TIEMPO_ESPERA"] = float(elast), float(pen), float(espera)
    costos = (round(P["COSTO_BUS_HORA"]), round(P["COSTO_KM"]), round(P["TARIFA"]))
    if costos == (DEF["cbh"], DEF["km"], DEF["tarifa"]):
        P["FUENTE"] = C.FUENTE_COSTOS
    elif costos == (SUPUESTOS["cbh"], SUPUESTOS["km"], SUPUESTOS["tarifa"]):
        P["FUENTE"] = C.FUENTE_SUPUESTOS
    else:
        P["FUENTE"] = "parámetros elegidos"
    return P


def _var(plan, hoy, d=0):
    """Texto de la variación frente a hoy y el número cuyo signo elige la flecha (None si no se puede calcular). La
    diferencia es la resta de las dos cifras ya redondeadas, para que cuadre con lo que se lee (585 − 312 = +273)."""
    dif = round(float(plan), d) - round(float(hoy), d)
    if not np.isfinite(dif):
        return None, None
    if abs(dif) < 10 ** (-d) / 2:
        return f"igual que hoy ({ui.num(hoy, d)})", 0
    return f"{ui.con_signo(dif, d)} frente a hoy ({ui.num(hoy, d)})", dif


def _horas_x():
    return [f"{h} h" for h in C.HORAS]


# Salidas del callback principal, en orden (cada una con su valor cuando no se puede calcular)
_SALIDAS = [("hv-respuesta", "children", "No se pudo calcular el plan de este día."), ("hv-estado", "children", None),
            ("hv-error", "children", None), ("hv-fichas", "children", None),
            ("hv-graf-salidas", "figure", "vacia"), ("hv-graf-salidas-titulo", "children", "Salidas por hora"),
            ("hv-graf-salidas-sub", "children", ""), ("hv-graf-salidas-leyenda", "children", None),
            ("hv-graf-salidas-tabla", "children", None), ("hv-graf-salidas-lienzo", "aria-label", "Sin datos."),
            ("hv-graf-salidas-nota", "children", None),
            ("hv-graf-carga", "figure", "vacia"), ("hv-graf-carga-titulo", "children", "Carga en el punto más lleno"),
            ("hv-graf-carga-sub", "children", ""), ("hv-graf-carga-leyenda", "children", None),
            ("hv-graf-carga-tabla", "children", None), ("hv-graf-carga-lienzo", "aria-label", "Sin datos."),
            ("hv-balance-titulo", "children", ""), ("hv-balance", "children", None), ("hv-balance-tabla", "children", None),
            ("hv-horario", "children", None), ("hv-csv", "data", None), ("hv-copiar", "content", "")]


def _salida(**valores):
    out = []
    for id_, _prop, defecto in _SALIDAS:
        clave = id_.replace("hv-", "").replace("-", "_")
        if clave in valores:
            out.append(valores[clave])
        else:
            out.append(ui.figura_vacia("") if defecto == "vacia" else defecto)
    return tuple(out)


def _fallo(titulo, e):
    return ui.aviso([html.Span(f"{e}. "), html.Span("Prueba otra fecha o restablece los parámetros.")], "critico", titulo)


@callback(
    *[Output(i, p) for i, p, _d in _SALIDAS],
    Input("hv-ruta", "value"), Input("hv-fecha", "date"), Input("hv-modelo", "value"),
    *[Input(f"hv-{s[0]}", "value") for s in SLIDERS], Input("hv-imax", "value"), Input("hv-comparar", "value"),
    Input("hv-beta", "value"),
)
def calcular(ruta, fecha, modelo, cbh, km, tarifa, elast, pen, espera, imax, comparar, beta):
    try:
        return _calcular(ruta, fecha, modelo, cbh, km, tarifa, elast, pen, espera, imax, comparar, beta)
    except Exception as e:  # noqa: BLE001  (cualquier falla se muestra como aviso, no como pantalla rota)
        return _salida(error=_fallo("No se pudo calcular el plan", e))


def _calcular(ruta, fecha, modelo, cbh, km, tarifa, elast, pen, espera, imax, comparar, beta):
    try:
        fecha = pd.Timestamp(fecha or FECHA_INICIAL).normalize()
        modelo = modelo or "E12"
        comparar = comparar or []
        imax_v = None if imax in (None, "auto") else float(imax)
        P = construir_P(cbh, km, tarifa, elast, pen, espera)
        rutas = C.ORDEN if ruta == "todas" else [ruta]
        ver_or = "oraculo" in comparar
        ver_sup = "supuestos" in comparar

        t0 = time.perf_counter()
        planes, sup = {}, {}
        for r in rutas:
            planes[r] = PB.plan_ruta(fecha, r, P, modelo=modelo, imax=imax_v, oraculo=ver_or)
            if ver_sup:
                sup[r] = PB.plan_ruta(fecha, r, C.param_d5(fuente=False), modelo=modelo, imax=imax_v)
        seg = time.perf_counter() - t0
        n_milp = len(rutas) * (2 if ver_sup else 1)
        todo_cache = all(v["de_cache"] for v in planes.values()) and all(v["de_cache"] for v in sup.values())
        estados = {v["estado"] for v in planes.values()} | {v["estado"] for v in sup.values()}
        holgura = sum(v["holgura"] for v in planes.values())
    except Exception as e:  # noqa: BLE001  (se muestra al usuario en vez de romper la página)
        return _salida(error=_fallo("El optimizador no terminó", f"No se pudo resolver el día: {e}"))

    base = pd.concat([planes[r]["tabla"] for r in rutas], ignore_index=True)
    base["n_hoy"] = base["n_S0"].fillna(0)
    ev_plan = EV.evaluar(base, base["x_plan"], P)
    ev_hoy = EV.evaluar(base, base["n_hoy"], P)
    nombre = "las tres rutas" if ruta == "todas" else ruta
    Nombre = nombre[0].upper() + nombre[1:]
    dia = ui.fecha_larga(fecha)

    # --- estado del cálculo y verificación -------------------------------------------------------------------------
    tipo = _nombre_tipo(planes[rutas[0]]["tipo_dia"])
    if todo_cache:
        primera = sum(v["segundos"] for v in planes.values()) + sum(v["segundos"] for v in sup.values())
        txt_t = f"Resuelto con CBC en {ui.num(primera, 2)} s · combinación ya calculada, se reutiliza"
    else:
        txt_t = f"Resuelto en {ui.num(seg, 2)} s · {n_milp} {'problema' if n_milp == 1 else 'problemas'} con CBC"
    ok = estados <= {"Optimal"}
    chips = [ui.chip("Óptimo", "bien") if ok else ui.chip("Estado: " + ", ".join(sorted(estados)), "atencion"),
             ui.chip(txt_t, icono="reloj"),
             ui.chip(f"{dia} · {tipo}", icono="calendario")]
    publicado = (modelo == "E1" and imax_v is None and P["FUENTE"] in (C.FUENTE_COSTOS, C.FUENTE_SUPUESTOS)
                 and P["ELASTICIDAD"] == DEF["elast"] and P["PENALIDAD_SOBRECARGA"] == DEF["pen"] and P["VALOR_TIEMPO_ESPERA"] == DEF["espera"])
    if publicado:
        col_ref = "x_D5_fuente" if P["FUENTE"] == C.FUENTE_COSTOS else "x_D5"
        nombre_ref = "el plan que reasigna" if col_ref == "x_D5_fuente" else "el plan que recorta"
        iguales = int((base["x_plan"] == base[col_ref]).sum())
        chips.append(ui.chip(f"Reproduce el plan publicado ({nombre_ref}): {ui.num(iguales)} de {ui.num(len(base))} horas",
                             "bien" if iguales == len(base) else "atencion"))
    if holgura > 1e-6:
        chips.append(ui.chip("La flota no alcanza: se usó holgura", "atencion"))
    estado = html.Div(chips, className="chips")

    # --- balance del día (va antes que las fichas: la ficha del costo lleva los dos saldos, DISENO.md §9 regla 15) ----
    beta = float(beta if beta is not None else BETA_INICIAL)
    Pb = dict(P, ELASTICIDAD=beta)
    eb = EV.evaluar(base, base["x_plan"], Pb)
    ahorro = ev_hoy["costo_operativo"] - ev_plan["costo_operativo"]
    perdidos, ganados = eb["pax_perdidos"], eb["pax_ganados_bruto"]
    cons = ahorro - perdidos * P["TARIFA"]
    sim = ahorro + (ganados - perdidos) * P["TARIFA"]
    cons_t, sim_t, beta_t = ui.con_signo(cons / 1e6, 2), ui.con_signo(sim / 1e6, 2), ui.num(beta, 2)

    # --- fichas -------------------------------------------------------------------------------------------------------
    def ficha(etq, clave, d, unidad, tono=False, escala=1.0, nota=None):
        """Ficha con el chip de cambio de la referencia («▲ 15%»): triángulo según el signo y la diferencia frente a hoy.
        El triángulo va en verde o rojo solo donde el sentido es inequívoco (espera y pasajeros sobre la capacidad)."""
        a, b = ev_plan[clave] / escala, ev_hoy[clave] / escala
        v, dif = _var(a, b, d)
        t = None
        if tono and dif:
            t = "bien" if dif < 0 else "critico"      # menos espera y menos pasajeros sobre la capacidad es mejor
        return ui.cifra(etq, ui.num(a, d), unidad, nota=nota, chip=ui.chip_cambio(dif, v, t) if v is not None else None)

    fichas = [
        ficha("Salidas válidas", "salidas", 0, "salidas",
              nota=f"A programar: {ui.num(ev_plan['programadas'])} (incluye las que no se completan)."),
        ficha("Horas de bus", "buses_hora", 0, "buses-hora", nota="Salidas × duración del recorrido de esa hora."),
        ficha("Kilómetros", "km", 0, "km"),
        ficha("Costo de operación", "costo_operativo", 2, "M COP", escala=1e6,
              nota=f"Millones de pesos (M COP). No es ganancia: con lo que se juega en pasajes, el saldo del día va de "
                   f"{cons_t} a {sim_t} M COP según cuántos pasajeros atraigan las salidas nuevas (β = {beta_t})."),
        ficha("Espera media estimada", "espera_media_min", 2, "min", tono=True, nota="Ponderada por los pasajeros que llegaron ese día."),
        ficha("Sobre la capacidad", "pax_sobre_capacidad", 0, "pasajeros", tono=True,
              nota="Pasajeros por encima de la capacidad en el punto más lleno, con la carga real del día."),
    ]

    # --- gráfico de salidas por hora (como «Payments»): barras rayadas del plan con la hora pico sólida y su franja,
    # el valor encima de cada columna, escalón gris de hoy, el plan que recorta en rosa rayado y el oráculo a trazos -----
    x = _horas_x()
    g = base.groupby("hora")
    hoy_h = g["n_hoy"].sum().reindex(C.HORAS, fill_value=0)
    plan_h = g["x_plan"].sum().reindex(C.HORAS, fill_value=0)
    h_max = int(plan_h.idxmax())
    foco = f"{h_max} h"
    ancho = ui.ancho_barra(len(x))
    hueco = ancho / 8
    # El valor del plan encima de cada columna (gris; el de la hora pico en tinta), como en «Payments». Va como texto de
    # la barra y no como anotación para que Plotly lo esconda solo cuando la columna es más angosta que el número (en el
    # teléfono las 17 cifras se pegarían). Con el plan que recorta al lado no se ponen: no se sabría de cuál barra son.
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=plan_h, name="Con el plan", offset=-ancho - hueco / 2 if ver_sup else -ancho / 2,
                         **ui.barras_foco("modelo", x, foco=foco, ancho=ancho), **ui.hover("Con el plan", plan_h, "salidas")))
    ui.banda_foco(fig, foco, x)
    ley = [("Hoy (salidas de 2025)", "hoy", "escalon"), ("Con el plan", "modelo", "rayada"),
           (f"Con el plan, a las {foco}: la hora con más salidas", "modelo", "foco")]
    enc = ["Hora", "Hoy", "Con el plan"]
    cols = [hoy_h, plan_h]
    titulo_s = f"El plan hace {ui.num(plan_h.sum())} salidas; hoy se hicieron {ui.num(hoy_h.sum())}"
    if ver_sup:
        sup_base = pd.concat([sup[r]["tabla"] for r in rutas], ignore_index=True)
        sup_h = sup_base.groupby("hora")["x_plan"].sum().reindex(C.HORAS, fill_value=0)
        fig.add_trace(go.Bar(x=x, y=sup_h, name="Plan que recorta", offset=hueco / 2,
                             **ui.traza("recorta", "rayada", ancho=ancho), **ui.hover("Plan que recorta", sup_h, "salidas")))
        ley.append(("Plan que recorta (supuestos iniciales)", "recorta", "rayada"))
        enc.append("Plan que recorta")
        cols.append(sup_h)
        titulo_s += f" y el plan que recorta haría {ui.num(sup_h.sum())}"
    fig.add_trace(go.Scatter(x=x, y=hoy_h, name="Hoy", **ui.traza("hoy", "escalon"),
                             **ui.hover("Hoy (salidas de 2025)", hoy_h, "salidas")))
    or_h = None
    if ver_or and "x_oraculo" in base:
        or_h = g["x_oraculo"].sum().reindex(C.HORAS, fill_value=0)
        fig.add_trace(go.Scatter(x=x, y=or_h, name="Oráculo", **ui.traza("oraculo"), **ui.hover("Oráculo", or_h, "salidas")))
        ley.append(("Oráculo", "oraculo", "trazos"))
        enc.append("Oráculo")
        cols.append(or_h)
    if not ver_sup:
        # El valor del plan encima de cada columna, en una fila por encima de todas las series (gris; el de la hora pico en
        # tinta), como en «Payments». Es el texto de unas barras transparentes y no una anotación para que Plotly lo esconda
        # solo cuando la columna es más angosta que el número (en el teléfono las 17 cifras se pegarían). Con el plan que
        # recorta al lado no se pone: no se sabría de cuál de las dos barras es.
        tope = max(float(plan_h.max()), float(hoy_h.max()), float(or_h.max()) if or_h is not None else 0.0) or 1.0
        fig.add_trace(go.Bar(x=x, y=[tope * 1.1] * len(x), name="Salidas del plan (rótulos)", offset=-ancho / 2, width=ancho,
                             marker={"color": ui.TRANSPARENTE, "line": {"width": 0}}, hoverinfo="skip", showlegend=False,
                             cliponaxis=False, text=[ui.num(v) for v in plan_h], texttemplate="%{text}", textposition="outside",
                             textfont=dict(ui.fuente_svg("tinta_3", "--t-s"),
                                           color=[ui.ROL["tinta"] if c == foco else ui.ROL["tinta_3"] for c in x])))
        fig.update_yaxes(range=[0, tope * 1.28])
    fig.update_layout(barmode="overlay", uniformtext_minsize=ui.px("--t-xs"), uniformtext_mode="hide")
    fig.update_xaxes(tickvals=x[::2])
    ui.unidad_eje(fig, "salidas por hora")
    tabla_s = ui.tabla(enc, [[x[i]] + [ui.num(c.iloc[i]) for c in cols] for i in range(len(x))], compacta=True)
    etiqueta_s = (f"{titulo_s}. Salidas por hora de {x[0]} a {x[-1]}; el plan hace más salidas a las {h_max} h "
                  f"({ui.num(plan_h.max())}).")
    sub_s = f"{Nombre} · {dia} · pronóstico: {NOMBRE_MODELO[modelo]}. Salidas válidas por hora de salida."
    nota_s = [ui.chip_valor("Hora con más salidas del plan:", f"{foco} ({ui.num(plan_h.max())})"),
              html.Span(" es la columna sólida, con la franja detrás.")]

    # --- gráfico de carga frente a capacidad -------------------------------------------------------------------------
    cap = base["capacidad"].iloc[0]
    L = g["L_real"].sum(min_count=1).reindex(C.HORAS)
    Lp = base.assign(Lp=np.exp(base["mu"])).groupby("hora")["Lp"].sum().reindex(C.HORAS)
    rol_prev = "previsto_hoy" if modelo in ("B1", "E1") else "previsto_modelo"
    prev_txt = f"Carga prevista con {_con_modelo(modelo)}"
    u = "pasajeros por hora"
    fc = go.Figure()
    # Capacidad con el plan: escalón azul con relleno de rayas verticales (el de «Retention»), centrado en cada hora como
    # el escalón gris de hoy
    t_cap = ui.traza("modelo", "escalon_rayado")
    t_cap["line"] = dict(t_cap["line"], shape="hvh")
    fc.add_trace(go.Scatter(x=x, y=plan_h * cap, name="Capacidad con el plan", **t_cap,
                            **ui.hover("Capacidad con el plan", plan_h * cap, u)))
    fc.add_trace(go.Scatter(x=x, y=hoy_h * cap, name="Capacidad hoy", **ui.traza("hoy", "escalon"),
                            **ui.hover("Capacidad hoy", hoy_h * cap, u)))
    fc.add_trace(go.Scatter(x=x, y=Lp, name="Carga prevista", **ui.traza(rol_prev, "punteada"), **ui.hover(prev_txt, Lp, u)))
    fc.add_trace(go.Scatter(x=x, y=L, name="Carga real", **ui.traza("real"), **ui.hover("Carga real", L, u)))
    # media hora de aire a cada lado: el «0» del eje no cae sobre «4 h» y «20 h» no se sale del lienzo
    fc.update_xaxes(tickvals=x[::2], range=[-0.5, len(x) - 0.5])
    fc.update_yaxes(rangemode="tozero")
    ui.unidad_eje(fc, u)
    ley_c = [("Carga real", "real", "gruesa"), (prev_txt, rol_prev, "punteada"),
             ("Capacidad con el plan", "modelo", "escalon_rayado"), ("Capacidad hoy", "hoy", "escalon")]
    tabla_c = ui.tabla(["Hora", "Carga real", "Carga prevista", "Capacidad con el plan", "Capacidad hoy"],
                       [[x[i], ui.num(L.iloc[i]), ui.num(Lp.iloc[i]), ui.num(plan_h.iloc[i] * cap), ui.num(hoy_h.iloc[i] * cap)]
                        for i in range(len(x))], compacta=True)
    titulo_c = (f"Con el plan, {ui.num(ev_plan['pax_sobre_capacidad'])} pasajeros por encima de la capacidad "
                f"(hoy, {ui.num(ev_hoy['pax_sobre_capacidad'])})")
    pico = L.idxmax() if L.notna().any() else None
    etiqueta_c = titulo_c + (f". La carga real más alta es de {ui.num(L.max())} pasajeros a las {int(pico)} h, con capacidad para "
                             f"{ui.num(plan_h.loc[pico] * cap)} con el plan y {ui.num(hoy_h.loc[pico] * cap)} hoy." if pico is not None else ".")
    sub_c = f"Pasajeros por hora en el tramo más cargado de la ruta y capacidad ofrecida ({ui.num(cap)} por bus). {Nombre} · {dia}."

    # --- balance del día --------------------------------------------------------------------------------------------
    dec_b = 0 if float(beta * 10).is_integer() else 1
    tabla_b = ui.tabla(["", "Sin pasajeros nuevos (conservadora)", "Con pasajeros nuevos (simétrica)"], [
        ["Ahorro en operación", f"{ui.con_signo(ahorro / 1e6, 2)} M COP", f"{ui.con_signo(ahorro / 1e6, 2)} M COP"],
        ["Pasajeros en riesgo donde se quitan salidas", ui.num(perdidos), ui.num(perdidos)],
        ["Pasajeros ganados donde se ponen salidas", "no cuentan", ui.num(ganados)],
    ], total=["Saldo del día", f"{cons_t} M COP", f"{sim_t} M COP"])
    # Como «Gross Volume»: el ahorro en operación en grande con sus dos chips (lo que se juega en pasajeros) → línea →
    # los dos saldos, siempre juntos → la nota de β. La tabla completa va en el «…» de la tarjeta.
    balance = [
        html.Div([html.P("Ahorro en operación del día", className="cifra__etiqueta"),
                  html.P([html.Span(ui.con_signo(ahorro / 1e6, 2), className="heroe__numero"),
                          html.Span("M COP", className="heroe__unidad")], className="heroe__valor"),
                  html.Div([ui.chip_valor("Pasajeros en riesgo donde se quitan salidas:", ui.num(perdidos)),
                            ui.chip_valor("Ganados donde se ponen (con la misma β):", ui.num(ganados))], className="chips")],
                 className="heroe__principal"),
        # Dos supuestos sobre algo que no se ha medido (cuántos pasajeros atraen las salidas nuevas), no dos resultados que se
        # promedian: cada ficha dice qué supone y el chip va neutro, con el nombre de su contabilidad. Inicio y Resultado
        # cuentan el año como la decisión que se propone, en tres pasos (ui.decision_piloto)
        html.Div([ui.saldo("Si las salidas nuevas no atraen a nadie", cons / 1e6,
                           "Contabilidad conservadora: solo cuenta los pasajes que se pierden donde se quitan salidas.", "M COP", 2,
                           extremo="conservadora"),
                  ui.saldo("Si las salidas nuevas atraen lo mismo que se pierde al quitar", sim / 1e6,
                           "Contabilidad simétrica: también cuenta los que se ganan donde se ponen, con la misma β, que al poner "
                           "salidas no se ha medido.", "M COP", 2, extremo="simétrica")],
                 className="saldos"),
        ui.nota(f"β = {beta_t}: si se quitan {ui.num(10)} de cada {ui.num(100)} salidas de una hora, se pierden "
                f"{ui.num(beta * 10, dec_b)} de cada {ui.num(100)} pasajeros de esa hora (rango creíble: {ui.num(_BETA['bajo'], 2)} a "
                f"{ui.num(_BETA['alto'], 2)}). Cada pasaje vale {ui.num(P['TARIFA'])} COP. Dónde queda el saldo entre esos dos "
                "supuestos depende de cuántos pasajeros atraen las salidas nuevas, que no se ha medido: por eso el plan no se "
                "aplica sin el piloto (Inicio)."),
    ]
    titulo_b = f"Saldo del día: de {cons_t} a {sim_t} M COP, según cuántos pasajeros atraigan las salidas nuevas"

    # --- horario minuto a minuto ------------------------------------------------------------------------------------
    filas_csv, bloques, texto = [], [], ["ruta\thora\tsalida\thora_salida\tintervalo_min"]
    for r in rutas:
        pl = planes[r]
        tb = pl["tabla"].set_index("hora")
        hor = pl["horario"]
        por_h = {}
        for m in hor:
            por_h.setdefault(int(m // 60), []).append(m)
        filas = []
        for h in C.HORAS:
            xs = int(tb.loc[h, "x_plan"])
            n0 = int(np.nan_to_num(tb.loc[h, "n_S0"]))
            ms = por_h.get(int(h), [])
            inter = tb.loc[h, "minutos"] / xs if xs else np.nan
            for i, m in enumerate(ms, 1):
                filas_csv.append({"ruta": r, "hora": int(h), "salida": i, "hora_salida": C.hhmm(m), "intervalo_min": round(float(inter), 1)})
                texto.append(f"{r}\t{int(h)}\t{i}\t{C.hhmm(m)}\t{ui.num(inter, 1)}")
            filas.append([f"{int(h):02d} h", ui.num(xs), html.Span(ui.num(n0), className="tinta-3"), ui.delta(xs - n0),
                          html.Span(ui.num(inter, 1) if xs else "—", className="tinta-3"),
                          html.Div([ui.hora_chip(C.hhmm(m)) for m in ms], className="horas") if ms else html.Span("sin salidas", className="tinta-3")])
        resumen = (f"{ui.num(len(hor))} salidas · primera {C.hhmm(hor[0]) if hor else '—'} · última {C.hhmm(hor[-1]) if hor else '—'}")
        # una ruta: su nombre con la muestra y el resumen → la tabla en su marco blanco (sin otra tarjeta dentro de la tarjeta)
        bloques.append(html.Div([html.P([ui.clave(r, r), html.Span(f" · {resumen}")], className="tarjeta__sub"),
                                 ui.tabla(["Hora", "Plan", "Hoy", "Cambio", "Cada (min)", "Salidas"], filas, compacta=True, alta=True,
                                          num=[False, True, True, True, True, False])], className="panel__grupo"))

    fuente_txt = {C.FUENTE_COSTOS: "Con los costos de 2026", C.FUENTE_SUPUESTOS: "Con los supuestos iniciales"}.get(P["FUENTE"],
                                                                                                                "Con los parámetros elegidos")
    respuesta = (f"{fuente_txt}, el plan de {nombre} para el {dia} hace {ui.num(ev_plan['salidas'])} salidas "
                 f"(hoy, {ui.num(ev_hoy['salidas'])}).")
    csv = {"filas": filas_csv, "nombre": f"horario_{'tres_rutas' if ruta == 'todas' else ruta.replace(' ', '')}_{fecha:%Y-%m-%d}_{modelo}.csv"}
    return _salida(respuesta=respuesta, estado=estado, error=None, fichas=fichas,
                   graf_salidas=fig, graf_salidas_titulo=titulo_s, graf_salidas_sub=sub_s, graf_salidas_leyenda=ui.leyenda(ley),
                   graf_salidas_tabla=tabla_s, graf_salidas_lienzo=etiqueta_s, graf_salidas_nota=nota_s,
                   graf_carga=fc, graf_carga_titulo=titulo_c, graf_carga_sub=sub_c, graf_carga_leyenda=ui.leyenda(ley_c),
                   graf_carga_tabla=tabla_c, graf_carga_lienzo=etiqueta_c,
                   balance_titulo=titulo_b, balance=balance, balance_tabla=tabla_b, horario=bloques, csv=csv,
                   copiar="\n".join(texto))


@callback(Output("hv-descarga", "data"), Input("hv-descargar", "n_clicks"), State("hv-csv", "data"), prevent_initial_call=True)
def descargar(_n, datos):
    if not datos or not datos.get("filas"):
        return dash.no_update
    df = pd.DataFrame(datos["filas"])
    return dcc.send_data_frame(df.to_csv, datos["nombre"], index=False, sep=";", decimal=",", encoding="utf-8-sig")
