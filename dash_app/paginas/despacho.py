"""Despacho en vivo: un día de 2025 repetido como si fuera hoy (la consola de despacho del proyecto, en el Dash).

Un reloj avanza (en tiempo real, con segundos, o a x60, x300 o x900) y la pantalla va diciendo qué buses salieron, cuáles salen en la próxima hora y en qué
bus, qué vehículos están en la calle y con cuántos pasajeros, y qué alertas tiene el motor. A la hora del reloj nunca se
muestra nada que el despachador no pudiera saber a esa hora (despacho_datos.py, ESQUEMA.md de la consola).

Consola de una sola pantalla (DISENO.md; referencia «zentra»), sin desplazar la página desde 1100 px de ancho: arriba el
título y los mandos (Día, Ruta, seguir o pausar, velocidad y la barra de la hora) → tres columnas a todo lo alto: el reloj,
las cuatro fichas y «Salidas por hora» | el mapa en vivo con las alertas debajo | «Próximos despachos» y «Últimos
despachos» (o, con el selector, «Vehículos en la calle»), cada lista con su propio desplazamiento. En el teléfono las
columnas se apilan. Cada tarjeta lleva su «…» con la tabla gemela y las fuentes. Todo color sale de un rol de ui.py;
ninguna cifra se escribe a mano (todas salen de los datos).

Rendimiento: el reloj vive en el navegador (un paso por segundo, sin esperar al servidor); el servidor responde una vez por
paso con lo que cambió (fichas y listas). El mapa (calles de OpenStreetMap y CARTO con MapLibre: go.Scattermap) se arma una
sola vez (rutas fijas por las calles, uirevision constante) y en cada paso del reloj solo se parchan los puntos de los buses, que avanzan por el trazado de su ruta (dias/calles/ de la consola; dash.Patch); «Salidas por hora» se rehace solo al cambiar la hora, el día o
la ruta y, dentro de la hora, se parchan sus barras."""
import functools
import math

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, Patch, State, callback, clientside_callback, ctx, dcc, html
from dash.exceptions import PreventUpdate

import despacho_datos as DD
import ui

dash.register_page(__name__, path="/despacho", name="Despacho", order=3, title="Despacho · Sobusa Despacho")

TITULO = "Despacho en vivo"
# §3.2 excluye el control de despachos: la consola repite un día de 2025 y solo muestra; no manda nada a la operación
SUBTITULO = ("Repetición de un día de 2025 como si fuera hoy. Muestra lo que vería el despachador; no despacha ni "
             "cambia la operación.")
VELOCIDADES = [1, 60, 300, 900]                   # segundos del día por segundo de reloj (1 = tiempo real)
VEL_INICIAL = 60
# Calles claras de CARTO sobre OpenStreetMap (estilo vectorial «carto-positron» de MapLibre). Las teselas ráster de CARTO
# (light_all) ya piden clave y salen con marca de agua, por eso no se usan
ESTILO_MAPA = "carto-positron"
ATRIBUCION = "© OpenStreetMap, © CARTO"
NOTA_MAPA = ("El mapa de calles necesita internet (estilo y calles de CARTO sobre OpenStreetMap); sin conexión el lienzo del "
             "mapa puede quedar vacío, y el resto de la pantalla sigue igual.")
HORA_INICIAL = 5 * 3600 + 30 * 60                 # 05:30: la lista ya se mueve desde el primer segundo
RUTAS_SEL = [("Todas", "todas")] + [(r, r) for r in DD.RUTAS]
FUENTES = ["sistema_tiempo_real/replay/dias/AAAA-MM-DD.js (o datos/despacho/AAAA-MM-DD.json.gz)",
           "sistema_tiempo_real/replay/ESQUEMA.md", "dash_app/despacho_datos.py"]
_VH = DD.VENTANA_HECHOS // 60                   # minutos de la lista de hechos (15)
_VP = DD.VENTANA_PROG // 60
_PASO = DD.indice()["meta"].get("paso_min", 5)
_NR = len(DD.RUTAS)
_MIN = 60                                        # segundos por minuto y por hora (el reloj del navegador arma «HH:MM»)
_HORA = 60 * _MIN
NIVEL = {"alta": ("Alta", "critico", None), "media": ("Media", "atencion", None), "info": ("Aviso", None, "info")}


# --- Piezas fijas -------------------------------------------------------------------------------------------------------
def _selector_dia(fechas, valor):
    """Día anterior → calendario (solo los días con datos) → día siguiente, con las clases del selector de las otras pantallas."""
    dias = pd.to_datetime(fechas)
    hay = set(fechas)
    faltan = [d.strftime("%Y-%m-%d") for d in pd.date_range(dias.min(), dias.max()) if d.strftime("%Y-%m-%d") not in hay]
    return html.Div([
        html.Button(ui.icono("chevron-izquierda", "glifo--m"), id="desp-fecha-ant", type="button",
                    className="boton boton--secundario boton--icono", title="Día anterior", **{"aria-label": "Día anterior"}),
        dcc.DatePickerSingle(id="desp-fecha", date=valor, min_date_allowed=dias.min().date(), max_date_allowed=dias.max().date(),
                             disabled_days=faltan, display_format="DD/MM/YYYY", month_format="MM/YYYY", first_day_of_week=1,
                             clearable=False, placeholder="Elige un día", className="fecha"),
        html.Button(ui.icono("chevron-derecha", "glifo--m"), id="desp-fecha-sig", type="button",
                    className="boton boton--secundario boton--icono", title="Día siguiente", **{"aria-label": "Día siguiente"}),
    ], className="selector-fecha")


def _marcas_reloj():
    """Cada 4 horas desde el inicio y el cierre del día (sin una marca pegada al cierre, que en el teléfono se monta)."""
    paso = 4 * 3600
    marcas = {s: DD.hhmm(s) for s in range(DD.INICIO, DD.FIN - paso // 2, paso)}
    marcas[DD.FIN] = DD.hhmm(DD.FIN)
    return marcas


def _boton_play():
    return html.Button([html.Span([ui.icono("pausa", "glifo--m"), html.Span("Pausar")], className="desp-play__pausa"),
                        html.Span([ui.icono("play", "glifo--m"), html.Span("Seguir")], className="desp-play__play")],
                       id="desp-play", type="button", className="boton boton--primario desp-play desp-play--jugando",
                       title="Pausar o seguir el reloj")


def _cabecera(fechas, f0):
    """Título (más pequeño que el de las otras pantallas) y los mandos en una o dos filas."""
    vel = ui.segmentado("desp-vel", [{"label": "Tiempo real" if v == 1 else f"x{v}", "value": v} for v in VELOCIDADES],
                        VEL_INICIAL, pequeno=True, persistir=False)
    ruta = ui.segmentado("desp-ruta", [{"label": a, "value": b} for a, b in RUTAS_SEL], "todas", pequeno=True)
    pista = html.Div(dcc.Slider(id="desp-slider", min=DD.INICIO, max=DD.FIN, step=60, value=HORA_INICIAL, marks=_marcas_reloj(),
                                updatemode="mouseup", allow_direct_input=False, className="deslizador"), className="desp-pista",
                     title="Mueve el reloj a otra hora del día")
    return html.Div([
        html.Div([html.H1(TITULO, className="desp-titulo"), html.P(SUBTITULO, className="nota desp-subtitulo")],
                 className="desp-titulos"),
        html.Div([ui.control("Día", _selector_dia(fechas, f0)), ui.control("Ruta", ruta), _boton_play(),
                  ui.control("Velocidad", vel), pista], className="desp-mandos"),
    ], className="desp-cab")


def _tarjeta_reloj():
    cuerpo = [
        html.Div([html.P(DD.hhmm(HORA_INICIAL), id="desp-hora", className="desp-reloj__hora", **{"aria-live": "off"}),
                  html.Div(id="desp-estado", className="desp-reloj__estado")], className="desp-reloj__fila"),
        html.P(id="desp-dia-texto", className="desp-reloj__dia"),
        html.P(id="desp-sub", className="oculto", **{"aria-live": "polite"}),
    ]
    velocidades = "Tiempo real: un segundo del día por cada segundo (la hora lleva segundos); " + "; ".join(
        f"x{v}: {ui.num(v / 60)} min del día por cada segundo" for v in VELOCIDADES if v > 1)
    notas = [ui.nota(velocidades + "."),
             ui.nota(f"La foto del motor es cada {_PASO} min; entre fotos, las salidas aparecen en su segundo exacto. Nunca se "
                     f"muestra algo que el despachador no supiera a la hora del reloj; el resumen del día llega a las {DD.hhmm(DD.FIN)}.")]
    return ui.tarjeta(cuerpo, titulo="Reloj del día", clase="desp-reloj", detalles=notas, fuentes=FUENTES)


_HALO = _NR                                      # traza del halo de los buses (debajo de los puntos)
_BUS0 = _NR + 1                                  # primera traza de buses (una por ruta)


def _vista_mapa(ancho=520, alto=272):
    """Centro y zoom que encuadran las tres rutas (sus extremos y un margen) en un lienzo de unos ancho×alto px: Web
    Mercator con mundo de 512·2^z px (MapLibre). Fijo: el mapa no salta al cambiar de ruta ni al moverse los buses."""
    pts = [p for r in DD.RUTAS for p in (DD.mapa().get("rutas", {}).get(r) or [])]
    if not pts:
        return {"lat": 10.98, "lon": -74.8}, 11
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    y = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    dlon = max(max(lons) - min(lons), 1e-3)
    dy = max(y(max(lats)) - y(min(lats)), 1e-5)
    zoom = min(math.log2(ancho * 360 / (512 * dlon)), math.log2(alto * 2 * math.pi / (512 * dy))) - 0.15
    yc = (y(max(lats)) + y(min(lats))) / 2
    lat_c = math.degrees(2 * math.atan(math.exp(yc)) - math.pi / 2)
    return {"lat": lat_c, "lon": (max(lons) + min(lons)) / 2}, round(zoom, 2)


def _estilo(rol, forma):
    """ui.traza llevado a Scattermap (MapLibre no tiene anillo ni forma de línea): solo modo, color y ancho o tamaño."""
    t = ui.traza(rol, forma)
    if forma == "punto":
        return {"mode": "markers", "marker": {"size": t["marker"]["size"] + 1, "color": t["marker"]["color"]}}
    return {"mode": "lines", "line": {"color": t["line"]["color"], "width": t["line"]["width"] + 1}}


@functools.lru_cache(maxsize=1)
def _fig_mapa_base():
    """El mapa se arma una vez, sobre las calles (Scattermap con «carto-positron»): las tres rutas (trazas 0–2, fijas), el
    halo de los buses (traza 3) y los buses de cada ruta (trazas 4–6); en cada foto solo se parchan el halo y los buses."""
    m = DD.mapa()
    calles = DD.calles_rutas() or {}
    fig = go.Figure()
    for r in DD.RUTAS:
        if calles.get(r):                      # el trazado por las calles (el mismo sobre el que se mueven los buses)
            lat, lon = calles[r]["lat"], calles[r]["lon"]
        else:
            pts = m.get("rutas", {}).get(r) or []
            lat, lon = [p[0] for p in pts], [p[1] for p in pts]
        fig.add_trace(go.Scattermap(lat=lat, lon=lon, name=r, hoverinfo="skip", **_estilo(r, "linea")))
    fig.add_trace(go.Scattermap(lat=[], lon=[], name="Halo", hoverinfo="skip", mode="markers",
                                marker={"size": ui.MARCADOR + 1 + 2 * ui.ANILLO, "color": ui.ROL["superficie"]}))
    for r in DD.RUTAS:
        fig.add_trace(go.Scattermap(lat=[], lon=[], name=f"Buses {r}", **_estilo(r, "punto"), **ui.hover_texto([])))
    centro, zoom = _vista_mapa()
    fig.update_layout(map={"style": ESTILO_MAPA, "center": centro, "zoom": zoom}, hovermode="closest",
                      margin=dict(l=0, r=0, t=0, b=0), showlegend=False, uirevision="mapa")
    return fig


def _con_rueda(comp):
    """El dcc.Graph del mapa acepta la rueda del ratón para acercar (las demás figuras no)."""
    if isinstance(comp, dcc.Graph):
        comp.config = {**ui.GRAF_CONFIG, "scrollZoom": True}
        return comp
    hijos = getattr(comp, "children", None)
    for h in (hijos if isinstance(hijos, (list, tuple)) else [hijos]):
        if h is not None and not isinstance(h, (str, int, float)):
            _con_rueda(h)
    return comp


def layout(**_):
    fechas = [d["fecha"] for d in DD.dias_disponibles()]
    if not fechas:
        return ui.pantalla([ui.encabezado(TITULO, "Faltan los días de la consola de despacho."),
                            ui.aviso(["No encuentro sistema_tiempo_real/replay/dias del proyecto ni datos/despacho/.",
                                      "Genéralos con «python preparar_datos.py --solo-despacho» desde el proyecto completo."],
                                     "critico", "Sin datos de despacho")])
    f0 = DD.fecha_inicial()
    horas = ui.grafico("desp-horas", "Salidas por hora", "Plan semanal (rayado), hechas y lo que falta reoptimizado (sólido)",
                       etiqueta="Salidas por hora", tabla=html.Div(), fuentes=FUENTES,
                       leyenda=[("Hechas", "real", "barra"), ("Plan semanal", "modelo", "rayada"), ("Lo que falta", "modelo", "barra")])
    izq = html.Div([_tarjeta_reloj(), html.Div(id="desp-cifras", className="cifras desp-cifras"), horas], className="desp-col desp-izq")
    mapa = _con_rueda(ui.grafico(_fig_mapa_base(), "Mapa en vivo", f"Cada punto es un bus sobre las calles de su ruta · calles {ATRIBUCION}",
                                 etiqueta="Mapa de calles con las rutas y los buses en la calle", tabla=html.Div(ui.nota(NOTA_MAPA)),
                                 id="desp-mapa", leyenda=[(r, r, "linea") for r in DD.RUTAS], fuentes=FUENTES))
    alertas = ui.tarjeta(html.Div(id="desp-alertas", className="desp-alertas-cuerpo"), titulo="Alertas",
                         detalles=ui.nota("Alta, media o aviso, con el texto del motor de despacho (sistema_tiempo_real), en la "
                                          "foto vigente."), fuentes=FUENTES, clase="desp-tarjeta-alertas")
    centro = html.Div([mapa, alertas], className="desp-col desp-centro")
    vista = ui.segmentado("desp-vista", [{"label": "Despachos", "value": "despachos"}, {"label": "Vehículos", "value": "vehiculos"}],
                          "despachos", pequeno=True, persistir=False, clase="desp-vista")
    proximos = ui.tarjeta(
        html.Div(id="desp-proximos", className="desp-lista"), titulo="Próximos despachos",
        subtitulo="La próxima hora: hora recomendada y bus",
        detalles=[ui.nota("Por salir: la hora que recomienda el motor; ajustada: movida para separar buses pegados o porque el "
                          "último iba lleno; atrasada: pasó más de un minuto sin salida; plan: con los datos caídos se sigue el "
                          "plan semanal."),
                  ui.nota(f"El bus es el que Sobusa ya programó a ±{_VP} min de esa hora; si no hay, «sin asignar».")],
        fuentes=FUENTES, clase="desp-tarjeta-lista desp-tarjeta-proximos")
    ultimos = ui.tarjeta(
        html.Div(id="desp-ultimos", className="desp-lista"), titulo="Últimos despachos",
        subtitulo=f"Los que salieron en los últimos {_VH} min",
        detalles=ui.nota("Salió: el motor ya vio la salida (registro de Sobusa o GPS). Si después sabe que no hizo el recorrido, "
                         "la quita de la lista y deja de contarla, como la consola."),
        fuentes=FUENTES, clase="desp-tarjeta-lista desp-tarjeta-ultimos")
    vehiculos = ui.tarjeta(
        html.Div(id="desp-vehiculos", className="desp-lista"), titulo="Vehículos en la calle",
        subtitulo=f"Cada bus en la ruta y sus pasajeros a bordo, en la foto del motor (cada {_PASO} min)",
        detalles=ui.nota("Ocupación: pasajeros a bordo según el contador al pasar por el último punto de control, "
                         "frente a la capacidad del bus (sentados y de pie). La tabla y las alertas cambian con "
                         "cada foto del motor; el mapa, las fichas y las listas de despachos, con cada paso del reloj."),
        fuentes=FUENTES, clase="desp-tarjeta-lista desp-tarjeta-veh")
    der = html.Div([vista,
                    html.Div([proximos, ultimos], id="desp-panel-despachos", className="desp-panel"),
                    html.Div(vehiculos, id="desp-panel-vehiculos", className="desp-panel desp-panel--oculto")],
                   className="desp-col desp-der")
    return ui.pantalla([
        dcc.Store(id="desp-reloj", data={"seg": HORA_INICIAL, "jugando": True}),
        dcc.Store(id="desp-foto", data=None),
        dcc.Store(id="desp-clave", data=None),
        dcc.Store(id="desp-horas-clave", data=None),
        dcc.Store(id="desp-mapa-listo", data=False),
        dcc.Interval(id="desp-tic", interval=1000, disabled=False),
        _cabecera(fechas, f0),
        html.H2("El despacho a la hora del reloj", className="oculto"),
        html.Div([izq, centro, der], className="desp-consola"),
    ], clase="pantalla--despacho")


# --- Reloj (en el navegador: un paso por segundo, sin ir al servidor) ----------------------------------------------------
clientside_callback(
    """function (n, clics, deslizador, vel, reloj) {
        var INI = %d, FIN = %d, VEL0 = %d, HORA = %d, MIN = %d;
        var r = Object.assign({seg: %d, jugando: true}, reloj || {});
        var disp = (window.dash_clientside.callback_context.triggered || []).map(function (t) { return t.prop_id; });
        var nada = window.dash_clientside.no_update, v = vel || VEL0;
        var dos = function (x) { return ('0' + x).slice(-2); };
        var texto = function (seg) {   // «HH:MM»; en tiempo real, «HH:MM:SS»
            var s = Math.max(INI, Math.min(FIN, seg)), h = Math.floor(s / HORA), m = Math.floor((s %% HORA) / MIN);
            return dos(h) + ':' + dos(m) + (v === 1 ? ':' + dos(s %% MIN) : '');
        };
        if (disp.indexOf('desp-vel.value') >= 0) {
            return [nada, nada, nada, texto(r.seg)];   // otra velocidad: solo cambia cómo se escribe la hora
        }
        if (disp.indexOf('desp-play.n_clicks') >= 0) {
            r.jugando = !r.jugando;
            if (r.jugando && r.seg >= FIN) { r.seg = INI; }
        } else if (disp.indexOf('desp-slider.value') >= 0 && deslizador != null) {
            // la barra va de minuto en minuto: su eco del minuto en curso no mueve el reloj (en tiempo real lleva segundos)
            if (deslizador === r.seg || deslizador === r.seg - (r.seg %% MIN)) { return [nada, nada, nada, nada]; }
            r.seg = deslizador;
        } else if (disp.indexOf('desp-tic.n_intervals') >= 0) {
            // en pausa el paso no cambia nada (ni va al servidor); el intervalo sigue vivo para que «Seguir» arranque al instante
            if (!r.jugando) { return [nada, nada, nada, nada]; }
            r.seg = Math.min(FIN, r.seg + v);
        }
        if (r.seg >= FIN) { r.jugando = false; }
        var pista = r.seg - (r.seg %% MIN);
        var clase = 'boton boton--primario desp-play' + (r.jugando ? ' desp-play--jugando' : '');
        return [r, pista === deslizador ? nada : pista, clase, texto(r.seg)];
    }""" % (DD.INICIO, DD.FIN, VEL_INICIAL, _HORA, _MIN, HORA_INICIAL),
    Output("desp-reloj", "data"), Output("desp-slider", "value"), Output("desp-play", "className"), Output("desp-hora", "children"),
    Input("desp-tic", "n_intervals"), Input("desp-play", "n_clicks"), Input("desp-slider", "value"),
    Input("desp-vel", "value"), State("desp-reloj", "data"))

# El mapa queda «listo» cuando MapLibre terminó de cargar el estilo de calles (en frío tarda más que el primer paso del
# reloj). Hasta entonces no se le manda ningún parche: parchar antes rompe con «Style is not done loading».
clientside_callback(
    """function (n, listo) {
        if (listo) { return window.dash_clientside.no_update; }
        var cont = document.getElementById('desp-mapa');
        var gd = cont && (cont.classList.contains('js-plotly-plot') ? cont : cont.querySelector('.js-plotly-plot'));
        var sub = gd && gd._fullLayout && gd._fullLayout.map && gd._fullLayout.map._subplot;
        var m = sub && sub.map;
        return (m && typeof m.isStyleLoaded === 'function' && m.isStyleLoaded()) ? true : window.dash_clientside.no_update;
    }""",
    Output("desp-mapa-listo", "data"), Input("desp-tic", "n_intervals"), State("desp-mapa-listo", "data"))

# «Despachos | Vehículos»: solo cambia qué panel se ve (en el navegador)
clientside_callback(
    """function (v) {
        var o = 'desp-panel', x = ' desp-panel--oculto';
        return v === 'vehiculos' ? [o + x, o] : [o, o + x];
    }""",
    Output("desp-panel-despachos", "className"), Output("desp-panel-vehiculos", "className"), Input("desp-vista", "value"))


@callback(Output("desp-fecha", "date"), Input("desp-fecha-ant", "n_clicks"), Input("desp-fecha-sig", "n_clicks"),
          State("desp-fecha", "date"), prevent_initial_call=True)
def mover_dia(_a, _s, fecha):
    fechas = [d["fecha"] for d in DD.dias_disponibles()]
    paso = -1 if ctx.triggered_id == "desp-fecha-ant" else 1
    f = str(fecha)[:10]
    if f not in fechas:
        return fechas[0]
    i = min(max(fechas.index(f) + paso, 0), len(fechas) - 1)
    return fechas[i]


# --- Pintar el estado a la hora del reloj (un solo cálculo por paso) -----------------------------------------------------
def _min(n):
    return f"{ui.num(n)} min"


def _cuando(dif):
    """«hace 3 min» / «en 5 min» / «ahora» (dif en segundos, positivo = en el futuro)."""
    m = int(abs(dif) // 60)
    if m == 0:
        return "ahora"
    return f"en {_min(m)}" if dif > 0 else f"hace {_min(m)}"


def _chip_estado(f):
    est = f["estado"]
    if est == "hecha":
        return ui.chip("Salió", "bien")
    if est == "fallida":
        return ui.chip("Fallida", "critico")
    if est == "ajustada":
        return ui.chip("Ajustada", "atencion")
    if est == "atrasada":
        return ui.chip("Atrasada", "critico")
    if est == "plan":
        return ui.chip("Plan semanal", None, icono="calendario")
    return ui.chip("Por salir", None, icono="reloj")


def _motivo(f):
    partes = []
    if f.get("retraso"):
        partes.append(f"retrasada {ui.num(f['retraso'], 1)} min")
    if f.get("adelanto"):
        partes.append(f"adelantada {ui.num(f['adelanto'], 1)} min")
    texto = " y ".join(partes)
    if f.get("motivos"):
        texto += ": " + "; ".join(str(m) for m in f["motivos"])
    if f.get("hueco"):
        texto = (texto + ". " if texto else "") + str(f["hueco"])
    return texto or None


def _fila(f, t, chip=True):
    """Una fila de despacho (html.Div simple): hora y «en/hace N min» → ruta y bus → chip de estado (con icono y palabra)."""
    bus = f.get("vehiculo")
    hijos = [html.Div([html.Span(f["hora"], className="desp-fila__hora"), html.Span(_cuando(f["seg"] - t), className="desp-fila__cuando")],
                      className="desp-fila__tiempo"),
             html.Div([ui.clave(f["ruta"], f["ruta"]),
                       html.Span(f"Bus {bus}" if bus else "sin asignar", className="desp-fila__bus" + ("" if bus else " desp-fila__bus--sin"))],
                      className="desp-fila__que")]
    if chip:
        hijos.append(_chip_estado(f))
    if f["estado"] == "ajustada" or f.get("hueco"):
        m = _motivo(f)
        if m:
            hijos.append(html.Span(m, className="desp-fila__motivo"))
    return html.Div(hijos, className=f"desp-fila desp-fila--{f['estado']}" + ("" if chip else " desp-fila--sin-chip"), role="listitem")


def _proximos(e):
    t, prox = e["seg"], e["proximos"]
    partes = [ui.aviso(e["aviso"], "atencion")] if e["aviso"] else []
    if prox:
        partes.append(html.Div([_fila(f, t) for f in prox], className="desp-filas", role="list"))
    else:
        partes.append(ui.nota("El motor no recomienda más salidas en la próxima hora." if not e["fin_dia"] else "El día terminó."))
    return partes


def _ultimos(e):
    t, hechos = e["seg"], e["hechos"]
    if not hechos:
        return [ui.nota(f"Ninguna salida en los últimos {_VH} min.")]
    return [html.Div([_fila(f, t, chip=False) for f in hechos], className="desp-filas", role="list", **{"aria-live": "polite"})]


def _ocupacion(v, cap):
    o = v["ocupacion"]
    if o is None:
        return html.Span("sin lectura", className="desp-ocup__sin")
    barra = html.Span(html.Span(className="rayas__relleno", style={"--p": f"{min(1.0, o / cap) * 100:.0f}%", "--c": ui.VAR["real"]}),
                      className="rayas__pista desp-ocup__pista", role="img", **{"aria-label": f"{ui.num(o)} de {ui.num(cap)} pasajeros"})
    texto = [html.Span(f"{ui.num(o)} de {ui.num(cap)}", className="desp-ocup__num")]
    if o > cap:
        texto.append(ui.chip("sobrecupo", "critico"))
    return html.Span([barra] + texto, className="desp-ocup")


def _vehiculos(e):
    vs = sorted(e["vehiculos"], key=lambda v: (v["min_en_ruta"], DD.RUTAS.index(v["ruta"])))
    tot = e["total"] if len(e["rutas"]) > 1 else next(iter(e["rutas"].values()))
    cab = html.P([html.Span(f"Foto de las {e['hora']}: ", className="desp-veh__foto"),
                  html.Span(f"{ui.num(tot['en_ruta'])} en la calle", className="desp-veh__n"),
                  html.Span(f" · {ui.num(tot['en_patio'])} en el patio · flota de {ui.num(tot['flota'])}")], className="desp-veh__cab")
    if not vs:
        return [cab, ui.nota("No hay buses en la calle a esta hora.")]
    cap = e["capacidad"]
    filas = [[f"Bus {v['vehiculo']}", ui.clave(v["ruta"], v["ruta"]), v["salida"],
              _ocupacion(v, cap), "—" if v["ultimo_punto"] is None else f"Punto {ui.num(v['ultimo_punto'])}"] for v in vs]
    return [cab, ui.tabla(["Bus", "Ruta", "Salió", "Ocupación", "Punto"], filas, compacta=True,
                          num=[False, False, True, False, False], ocultar_movil=(4,))]


def _alertas(e):
    if not e["alertas"]:
        return [ui.chip("Sin alertas en la foto vigente", "bien")]
    items = []
    orden = {"alta": 0, "media": 1, "info": 2}
    for a in sorted(e["alertas"], key=lambda a: (orden.get(a["nivel"], 3), DD.RUTAS.index(a["ruta"]))):
        texto, tipo, icono = NIVEL.get(a["nivel"], ("Aviso", None, "info"))
        items.append(html.Li([ui.chip(texto, tipo, icono=icono), ui.clave(a["ruta"], a["ruta"]),
                              html.Span(a["mensaje"], className="desp-alerta__texto", title=a["mensaje"])], className="desp-alerta"))
    return [html.Ul(items, className="desp-alertas")]


def _cifras(e):
    r = e["total"] if len(e["rutas"]) > 1 else next(iter(e["rutas"].values()))
    fichas = []
    if r["salidas_hoy"] is None:
        fichas.append(ui.cifra("Salidas hoy", "sin datos", variacion=f"el plan llevaba {ui.num(r['salidas_plan'])}"))
    else:
        d = r["salidas_hoy"] - r["salidas_plan"]
        fichas.append(ui.cifra("Salidas hoy", ui.num(r["salidas_hoy"]), f"de {ui.num(r['salidas_plan'])}",
                               variacion=f"{ui.con_signo(d)} frente al plan", flecha=d))
    fichas.append(ui.cifra("Buses en la calle", ui.num(r["en_ruta"]), f"de {ui.num(r['flota'])}",
                           variacion=f"{ui.num(r['en_patio'])} en el patio"))
    p = e["proximos"][0] if e["proximos"] else None
    if p:
        bus = f"Bus {p['vehiculo']}" if p["vehiculo"] else "sin asignar"
        if p["estado"] == "atrasada":
            fichas.append(ui.cifra("Próximo despacho", p["hora"], p["ruta"], variacion=f"{bus} · desde {_cuando(p['seg'] - e['seg'])}",
                                   chip=ui.chip("Atrasada", "atencion")))
        else:
            fichas.append(ui.cifra("Próximo despacho", p["hora"], p["ruta"], variacion=f"{bus} · {_cuando(p['seg'] - e['seg'])}"))
    else:
        fichas.append(ui.cifra("Próximo despacho", "—", variacion="ninguno en la próxima hora"))
    if r["pax_esp"]:
        dp = (r["pax_obs"] / r["pax_esp"] - 1) * 100
        fichas.append(ui.cifra("Pasajeros vistos", ui.num(r["pax_obs"]), f"de {ui.num(r['pax_esp'])}",
                               variacion=f"{ui.con_signo(dp, 1)} % vs. esperado", flecha=dp))
    else:
        fichas.append(ui.cifra("Pasajeros vistos", ui.num(r["pax_obs"]), variacion="todavía no se esperaba nadie"))
    return fichas


def _series_horas(e):
    ph = e["por_hora"]
    ha = ph["hora_actual"]
    # hechas (casi negro) hasta la hora en curso; en la hora en curso, encima, lo que falta del reoptimizado (azul sólido)
    hechas = [ph["real"][i] if i <= ha else 0 for i in range(17)]
    faltan = [max(ph["reopt"][i] - ph["real"][i], 0) if i == ha else (ph["reopt"][i] if i > ha else 0) for i in range(17)]
    return ph["horas"], ha, ph["plan"], ph["reopt"], hechas, faltan


def _fig_horas(e):
    horas, ha, plan, _reopt, hechas, faltan = _series_horas(e)
    ancho = ui.ancho_barra(34)
    fig = go.Figure()
    fig.add_bar(x=horas, y=plan, name="Plan semanal", offsetgroup="plan", **ui.traza("modelo", "rayada", ancho=ancho),
                **ui.hover("Plan semanal", plan, "salidas"))
    fig.add_bar(x=horas, y=hechas, name="Salidas hechas", offsetgroup="hecho", **ui.traza("real", "barra", ancho=ancho),
                **ui.hover("Salidas hechas", hechas, "salidas"))
    fig.add_bar(x=horas, y=faltan, base=hechas, name="Reoptimizado (lo que falta)", offsetgroup="hecho",
                **ui.traza("modelo", "barra", ancho=ancho), **ui.hover("Lo que falta (reoptimizado)", faltan, "salidas"))
    ui.banda_foco(fig, horas[ha])
    fig.update_layout(barmode="group", hovermode="x unified", margin=dict(t=8, b=24), uirevision="horas")
    fig.update_xaxes(tickvals=horas[::2], ticktext=[f"{h}" for h in horas[::2]])
    ui.unidad_eje(fig, "salidas · hora de salida")
    return fig


def _tabla_horas(e):
    horas, ha, plan, reopt, hechas, faltan = _series_horas(e)
    tabla = ui.tabla(["Hora", "Plan semanal", "Reoptimizado", "Hechas", "Faltan"],
                     [[f"{h}:00", ui.num(plan[i]), ui.num(reopt[i]), ui.num(hechas[i]) if i <= ha else "—",
                       ui.num(faltan[i]) if i >= ha else "—"] for i, h in enumerate(horas)], compacta=True)
    etiqueta = (f"Salidas por hora hasta la foto de las {e['hora']}: el plan semanal suma {ui.num(sum(plan))} y el "
                f"reoptimizado {ui.num(sum(reopt))}; van {ui.num(sum(hechas))} hechas y faltan {ui.num(sum(faltan))}")
    return tabla, etiqueta


def _texto_bus(v, cap):
    """«Bus 585 · CRA 54 · 34 de 50 · salió 07:12» (lo que dice el punto al pasar el puntero)."""
    o = "recién salido, sin lectura" if v["recien"] else ("sin lectura" if v["ocupacion"] is None else f"{ui.num(v['ocupacion'])} de {ui.num(cap)}")
    return f"Bus {v['vehiculo']} · {v['ruta']} · {o} · salió {v['salida']}"


def _parche_mapa(e, rutas):
    """Solo los buses (x, y, texto) y qué rutas se ven: la geometría de las rutas nunca se reenvía."""
    p = Patch()
    cap = e["capacidad"]
    todos = []
    calles = DD.posiciones_calles(e["fecha"], e["seg"], None) is not None   # con calles, los buses los mueve mover_buses
    for i, r in enumerate(DD.RUTAS):
        vis = r in rutas
        p["data"][i]["visible"] = vis
        if calles:
            continue
        vs = [v for v in e["vehiculos"] if v["ruta"] == r and v["lat"] is not None] if vis else []
        todos += vs
        p["data"][_BUS0 + i]["lat"] = [v["lat"] for v in vs]
        p["data"][_BUS0 + i]["lon"] = [v["lon"] for v in vs]
        p["data"][_BUS0 + i]["customdata"] = [[_texto_bus(v, cap)] for v in vs]
    if not calles:
        p["data"][_HALO]["lat"] = [v["lat"] for v in todos]
        p["data"][_HALO]["lon"] = [v["lon"] for v in todos]
    cuenta = [[r, ui.num(sum(1 for v in e["vehiculos"] if v["ruta"] == r))] for r in rutas]
    tabla = html.Div([ui.tabla(["Ruta", "Buses en el mapa"], cuenta, compacta=True, muestras=list(rutas)), ui.nota(NOTA_MAPA)])
    etiqueta = "Mapa de calles: " + ", ".join(f"{r} con {n} buses en la calle" for r, n in cuenta)
    return p, tabla, etiqueta


def _fecha_ruta(fecha, ruta):
    fechas = [d["fecha"] for d in DD.dias_disponibles()]
    fecha = str(fecha or DD.fecha_inicial())[:10]
    return (fecha if fecha in fechas else DD.fecha_inicial()), (ruta or "todas")


@functools.lru_cache(maxsize=64)
def _estado(fecha, seg, ruta):
    return DD.estado(fecha, seg, ruta)


# Cada paso del reloj (ligero): el estado de los datos, las fichas y las dos listas. La hora la pinta el navegador. La tabla
# de vehículos, el mapa, las alertas y las salidas por hora solo cambian con la foto del motor (cada 5 min del día).
@callback(
    Output("desp-estado", "children"), Output("desp-dia-texto", "children"), Output("desp-sub", "children"),
    Output("desp-cifras", "children"), Output("desp-proximos", "children"), Output("desp-ultimos", "children"),
    Output("desp-foto", "data"), Output("desp-clave", "data"),
    Input("desp-reloj", "data"), Input("desp-fecha", "date"), Input("desp-ruta", "value"), State("desp-foto", "data"),
    State("desp-vel", "value"), State("desp-clave", "data"))
def pintar(reloj, fecha, ruta, foto, vel, clave):
    fecha, ruta = _fecha_ruta(fecha, ruta)
    seg = int((reloj or {}).get("seg", HORA_INICIAL))
    e = _estado(fecha, seg, ruta)
    nueva = {"fecha": fecha, "ruta": ruta, "seg": e["foto_seg"]}
    # la foto se repinta como mucho cada 5 s de reloj mientras corre (a x300 y x900 cada paso es otra foto); al pausar, al
    # cambiar de día o de ruta, o al volver atrás, se repinta enseguida: nunca queda una foto posterior a la hora del reloj
    corre = bool((reloj or {}).get("jugando"))
    salto = _PASO * 60 if not corre else max(_PASO * 60, (vel or VEL_INICIAL) * 5)
    if foto and foto.get("fecha") == fecha and foto.get("ruta") == ruta and (
            nueva["seg"] == foto.get("seg") or (corre and 0 < nueva["seg"] - foto.get("seg", 0) < salto)):
        nueva = dash.no_update
    # en tiempo real cada paso es un segundo: solo se repinta si cambió algo visible (una salida en su segundo exacto, un
    # «en N min» que bajó, las fichas); la firma cabe en 32 bits para volver igual desde el navegador
    t0 = e["seg"]
    rr = e["total"] if ruta == "todas" else e["rutas"][ruta]
    firma = hash((tuple((f["hora"], f["estado"], f.get("vehiculo"), _cuando(f["seg"] - t0)) for f in e["proximos"] + e["hechos"]),
                  rr["salidas_hoy"], rr["en_ruta"], rr["pax_obs"], e["aviso"])) & 0xFFFFFFFF
    k = {"fecha": fecha, "ruta": ruta, "min": e["seg"] // 60, "ok": e["datos_ok"], "fin": e["fin_dia"], "firma": firma}
    if clave == k and nueva is dash.no_update:
        raise PreventUpdate          # el mismo minuto y la misma foto: nada cambió
    mismo_dia = bool(clave) and all(clave.get(c) == k[c] for c in ("fecha", "ok", "fin"))
    if mismo_dia:
        estado = dia_txt = dash.no_update
    else:
        estado = (ui.chip("Datos al día", "bien") if e["datos_ok"] else ui.chip("Datos caídos: plan semanal", "atencion"))
        if e["fin_dia"]:
            estado = html.Span([estado, ui.chip("Día cerrado", None, icono="reloj")], className="desp-reloj__chips")
        info = e["dia"]
        dia_txt = f"{ui.fecha_larga(fecha)} · {info['etiqueta']}" + (f" · {info['descripcion']}" if info.get("descripcion") else "")
    r = e["total"] if ruta == "todas" else e["rutas"][ruta]
    p = e["proximos"][0] if e["proximos"] else None
    if r["salidas_hoy"] is None:
        sub = f"A las {e['hora']} no llegan bien los datos: se despacha con el plan semanal."
    else:
        sub = f"A las {e['hora']} van {ui.num(r['salidas_hoy'])} salidas de {ui.num(r['salidas_plan'])} del plan"
        if p:
            cuando = (f"; la próxima, atrasada desde las {p['hora']}," if p["estado"] == "atrasada"
                      else f"; la próxima sale a las {p['hora']}")
            sub += f"{cuando} por {p['ruta']}" + (f" en el bus {p['vehiculo']}." if p["vehiculo"] else ", sin bus asignado.")
        else:
            sub += "."
    return (estado, dia_txt, sub, _cifras(e), _proximos(e), _ultimos(e), nueva, k)


@callback(
    Output("desp-vehiculos", "children"), Output("desp-alertas", "children"),
    Output("desp-mapa", "figure"), Output("desp-mapa-tabla", "children"), Output("desp-mapa-lienzo", "aria-label"),
    Output("desp-horas", "figure"), Output("desp-horas-tabla", "children"), Output("desp-horas-lienzo", "aria-label"),
    Output("desp-horas-clave", "data"),
    Input("desp-foto", "data"), Input("desp-vista", "value"), Input("desp-mapa-listo", "data"),
    State("desp-horas-clave", "data"))
def pintar_foto(foto, vista, listo, hclave):
    """A la hora exacta de la foto vigente (nunca después): lo que el motor sabía en esa foto. Solo se envía lo que cambió."""
    if not foto:
        raise PreventUpdate
    fecha, ruta = _fecha_ruta(foto.get("fecha"), foto.get("ruta"))
    e = _estado(fecha, int(foto.get("seg", HORA_INICIAL)), ruta)
    rutas = DD.RUTAS if ruta == "todas" else [ruta]
    veh = _vehiculos(e) if vista == "vehiculos" else dash.no_update
    if ctx.triggered_id == "desp-vista":
        # solo cambió el panel de la derecha: el mapa, las alertas y las barras ya están al día
        return (veh,) + (dash.no_update,) * 8
    fm, tm, em = _parche_mapa(e, rutas)
    if not listo:
        fm = dash.no_update                    # el estilo del mapa aún carga: el parche llega cuando quede listo
    horas, ha, plan, _reopt, hechas, faltan = _series_horas(e)
    llave = [fecha, ruta, ha]
    valores = [plan, hechas, faltan]
    if not hclave or hclave.get("k") != llave:
        fh = _fig_horas(e)                     # otra hora, otro día u otra ruta: la figura completa (17 barras)
    elif hclave.get("v") != valores:
        fh = Patch()                           # dentro de la hora: solo las alturas de las barras
        fh["data"][0]["y"] = plan
        fh["data"][1]["y"] = hechas
        fh["data"][2]["y"] = faltan
        fh["data"][2]["base"] = hechas
        fh["data"][0]["customdata"] = ui.hover("Plan semanal", plan, "salidas")["customdata"]
        fh["data"][1]["customdata"] = ui.hover("Salidas hechas", hechas, "salidas")["customdata"]
        fh["data"][2]["customdata"] = ui.hover("Lo que falta (reoptimizado)", faltan, "salidas")["customdata"]
    else:
        fh = dash.no_update
    th, eh = _tabla_horas(e)
    return (veh, _alertas(e), fm, tm, em, fh, th, eh, {"k": llave, "v": valores})


# Cada paso del reloj: los buses por las calles (dias/calles/ de la consola), sobre el trazado de su ruta. Solo se parchan
# los puntos de los buses y su halo; la ocupación es la del mismo bus en la foto vigente, si está.
@callback(Output("desp-mapa", "figure", allow_duplicate=True),
          Input("desp-reloj", "data"), Input("desp-fecha", "date"), Input("desp-ruta", "value"),
          Input("desp-mapa-listo", "data"), prevent_initial_call="initial_duplicate")
def mover_buses(reloj, fecha, ruta, listo):
    if not listo:
        raise PreventUpdate               # el estilo del mapa aún carga (ver el callback de «desp-mapa-listo»)
    fecha, ruta = _fecha_ruta(fecha, ruta)
    seg = int((reloj or {}).get("seg", HORA_INICIAL))
    pos = DD.posiciones_calles(fecha, seg, ruta)
    if pos is None:
        raise PreventUpdate               # sin archivos de calles: los buses son los de la foto (pintar_foto)
    e = _estado(fecha, seg, ruta)
    cap = e["capacidad"]
    foto = {(v["ruta"], v["vehiculo"]): v for v in e["vehiculos"]}
    p = Patch()
    todos = []
    for i, r in enumerate(DD.RUTAS):
        vs = [v for v in pos if v["ruta"] == r]
        todos += vs
        textos = []
        for v in vs:
            f = foto.get((r, v["vehiculo"]))
            o = "sin lectura" if not f or f["ocupacion"] is None else f"{ui.num(f['ocupacion'])} de {ui.num(cap)}"
            textos.append([f"Bus {v['vehiculo']} · {r} · {o} · salió {v['salida']} · km {ui.num(v['s'] / 1000, 1)}"])
        p["data"][_BUS0 + i]["lat"] = [round(v["lat"], 6) for v in vs]
        p["data"][_BUS0 + i]["lon"] = [round(v["lon"], 6) for v in vs]
        p["data"][_BUS0 + i]["customdata"] = textos
    p["data"][_HALO]["lat"] = [round(v["lat"], 6) for v in todos]
    p["data"][_HALO]["lon"] = [round(v["lon"], 6) for v in todos]
    return p
