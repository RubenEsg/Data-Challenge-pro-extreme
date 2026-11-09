"""Pronóstico: pasajeros reales frente a pronosticados (fuera de muestra, con una semana de antelación) por ruta, día y hora
de 2025. Todo sale de datos/pronosticos_2025.parquet, datos/cifras_app.json y datos/ficha_modelos.json (DISENO.md §8).
Tablero como la referencia: el día hora por hora con su tarjeta de errores al lado y, debajo, el mes con la lectura del año."""
import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, ctx, html

import datos_app as D
import ui
from controles import FECHA_INICIAL, mover_fecha, selector_fecha
from ui import NOMBRE_MODELO, con_signo, num

dash.register_page(__name__, path="/pronostico", name="Pronóstico", order=1, title="Pronóstico · Sobusa Despacho")

MODELOS = ["E11", "E12"]                       # el orden fijo; el híbrido es el recomendado y va elegido
RUTAS = [("Las tres rutas", "todas"), ("SILENCIO", "SILENCIO"), ("CRA 54", "CRA 54"), ("CL 72", "CL 72")]
TIPO_DIA = {"Domingo/festivo": "Domingo o festivo"}
SUJETO = {"E11": "el modelo final", "E12": "el híbrido"}
DEL_MODELO = {"E11": "del modelo final", "E12": "del híbrido"}
REGLA = "Regla manual (hoy)"
FUENTES = ["datos/pronosticos_2025.parquet",
           "experimentos/E11_modelo_mejorado/predicciones_2025.parquet (real, modelo final y regla manual)",
           "experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet (híbrido)"]
DIA = pd.Timedelta(days=1)


def _antelacion():
    """Días de antelación de los pronósticos (el horizonte más corto evaluado en cifras_app.json) y su nombre."""
    h = int(min(D.valor("demanda", "demanda_wape_antelacion")["E11_V4"], key=int))
    return h, ("una semana" if h == 7 else f"{h} días")


def _pliegues():
    return D.valor("modelo", "modelo_final_pliegues")["pliegues_mensuales_2025"]


def layout(**_):
    b1, e12 = D.valor("inicio", "inicio_error_regla_manual"), D.valor("inicio", "inicio_error_hibrido")
    h, antelacion = _antelacion()
    cabecera = ui.cabecera("pronostico", "¿Cuántos pasajeros habrá?",
                           f"Con {antelacion} de antelación, el híbrido se equivoca en {num(e12)} de cada 100 pasajeros de 2025; "
                           f"la regla manual, en {num(b1)}.")
    controles = [
        ui.control("Ruta", ui.segmentado("pr-ruta", [{"label": a, "value": b} for a, b in RUTAS], "CRA 54")),
        ui.control("Día de 2025", selector_fecha("pr-fecha", FECHA_INICIAL)),
        ui.control("Modelo de pronóstico", ui.segmentado("pr-modelo", [{"label": NOMBRE_MODELO[m], "value": m} for m in MODELOS], "E12")),
    ]
    WAPE = D.ficha_modelos()["convenciones"]["WAPE"]["texto"]
    como = ui.desplegable("Cómo se calcula", [
        ui.parrafo(f"Pronósticos fuera de muestra. Cada mes de 2025 se pronosticó con un modelo entrenado solo con los días "
                   f"anteriores a ese mes, y cada día con datos de hasta {h} días antes: el modelo no vio ese mes al entrenar. Son los "
                   f"mismos pronósticos de las tablas del informe ({_pliegues()} pliegues mensuales)."),
        ui.parrafo(f"El error es el WAPE. {WAPE} Se calcula sobre las franjas de ruta, día y hora del periodo: el día, la "
                   "semana de lunes a domingo o el mes. Con «Las tres rutas» se usan las franjas de las tres; los gráficos suman las "
                   "tres rutas en cada hora."),
        ui.parrafo(f"La regla manual es lo que Sobusa hace hoy: {D.valor('inicio', 'inicio_regla_manual_definicion')} Se dibuja "
                   "siempre, en gris punteado, como referencia."),
        ui.parrafo("El modelo elegido va en columnas azules rayadas; la sólida marca la hora pico real del día (en el mes, el día "
                   "elegido). Al comparar, el híbrido va en columnas y el modelo final, en línea azul a trazos. Lo real es la línea negra."),
        ui.fuentes(FUENTES + ["datos/cifras_app.json", "datos/ficha_modelos.json"]),
    ])

    # El día hora por hora (con la casilla de comparar junto a su leyenda) y, al lado, la tarjeta de errores del día elegido
    hora = ui.grafico("pr-hora", titulo="", subtitulo="", etiqueta="", alto="alto", fuentes=FUENTES)
    hora.children.insert(2, ui.fila_controles([ui.casilla("pr-comparar", [{"label": "Comparar con el otro modelo", "value": "si"}])]))
    dia = ui.tarjeta(html.Div(id="pr-fichas", className="rayas-lista"), titulo="El día elegido",
                     subtitulo="Error del pronóstico (WAPE) y pasajeros del día",
                     detalles=[ui.parrafo(f"El error es el WAPE. {WAPE}"),
                               ui.parrafo("La semana va de lunes a domingo; el mes, del primer al último día con datos de 2025.")],
                     fuentes=FUENTES + ["datos/cifras_app.json", "datos/ficha_modelos.json"])
    mes = ui.grafico("pr-mes", titulo="", subtitulo="", etiqueta="", alto="alto", fuentes=FUENTES,
                     nota="Toca un día de la serie para verlo hora por hora.")
    error_mes = ui.tarjeta(html.Div(id="pr-mes-error", className="rayas-lista"), titulo="Error del mes",
                           subtitulo="WAPE del mes del día elegido, en % de los pasajeros", fuentes=FUENTES)
    lectura = ui.tarjeta_insight(
        num(e12), f"de cada 100 pasajeros de 2025 los estima mal el híbrido, con {antelacion} de antelación",
        f"La regla manual de hoy se equivoca en {num(b1)} de cada 100. Son pronósticos fuera de muestra: ningún mes se "
        "pronosticó con un modelo que lo hubiera visto al entrenar.")
    return ui.pantalla([
        ui.arriba(cabecera, controles),
        # h2 solo para lectores de pantalla (h1 → h2 → h3 sin saltos); las tarjetas ya llevan su título visible
        html.Section([html.H2("El día, hora por hora", className="oculto"), ui.rejilla([hora, dia], "2-1")]),
        html.Section([html.H2("El mes, día por día", className="oculto"),
                      ui.rejilla([mes, html.Div([error_mes, lectura], className="rejilla")], "2-1")]),
        como,
    ])


def wape(df, col):
    r = df["real"].sum()
    return float((df[col] - df["real"]).abs().sum() / r * 100) if r > 0 else float("nan")


def _sel(ruta):
    p = D.pronosticos()
    return p if ruta == "todas" else p[p["ruta"] == ruta]


def _de_cada_100(w, wr):
    """«13 de cada 100 pasajeros» con enteros; si el entero borra la diferencia con la regla manual, «el 12,94 %» (§6, regla 9)."""
    if max(w, wr) >= 100:   # un día atípico: «106 de cada 100» se lee mal; se dice el porcentaje
        return f"el {num(w)} % de los pasajeros", f"el {num(wr)} %"
    if round(w) != round(wr) or abs(w - wr) < 0.005:
        return f"{num(w)} de cada 100 pasajeros", num(wr)
    return f"el {num(w, 2)} % de los pasajeros", f"el {num(wr, 2)} %"


def _series(modelo, comparar):
    """(columna, nombre, rol, forma) de cada serie en el orden de la leyenda (así sale también el texto al pasar el puntero):
    lo real en negro (se dibuja encima con zorder), la regla manual en gris punteado, el modelo en columnas (rayadas, la de
    foco sólida) y, al comparar, el modelo final a trazos."""
    if comparar:
        modelos = [("E12", NOMBRE_MODELO["E12"], "modelo", "columnas"), ("E11", NOMBRE_MODELO["E11"], "modelo_final", "trazos")]
    else:
        modelos = [(modelo, NOMBRE_MODELO[modelo], "modelo", "columnas")]
    return [("real", "Real", "real", "gruesa"), ("B1", REGLA, "hoy", "punteada")] + modelos


def _leyenda(series, foco=None):
    items = []
    for _c, nombre, rol, forma in series:
        if forma == "columnas":
            items.append((nombre, rol, "rayada"))
            if foco:
                items.append((foco, rol, "foco"))
        else:
            items.append((nombre, rol, forma))
    return ui.leyenda(items)


def _columnas(series):
    """Columnas de la tabla gemela en el orden fijo: real, regla manual, modelo final, híbrido."""
    orden = {"real": 0, "B1": 1, "E11": 2, "E12": 3}
    return sorted([(c, n) for c, n, _r, _f in series], key=lambda x: orden[x[0]])


def _trazas(fig, x, datos, series, foco=None, ancho=None):
    for col, nombre, rol, forma in series:
        y = list(datos[col])
        if forma == "columnas":
            fig.add_trace(go.Bar(x=x, y=y, name=nombre, **ui.barras_foco(rol, x, foco=foco, ancho=ancho),
                                 **ui.hover(nombre, y, "pasajeros")))
        else:
            fig.add_trace(go.Scatter(x=x, y=y, name=nombre, **ui.traza(rol, forma), **ui.hover(nombre, y, "pasajeros"),
                                     zorder=1 if col == "real" else 0))
    return fig


def _rayas(titulo, df, modelo):
    """Subtítulo del periodo y sus dos barras rayadas: el modelo (azul) y la regla manual (gris), en % de los pasajeros."""
    w, wb = wape(df, modelo), wape(df, "B1")
    return [html.P(titulo, className="cifra__etiqueta"),
            ui.barra_rayas(NOMBRE_MODELO[modelo], f"{num(w, 2)} %", w / 100, "modelo"),
            ui.barra_rayas(REGLA, f"{num(wb, 2)} %", wb / 100, "hoy")]


@callback(
    Output("pr-fecha", "date"), Output("pr-fichas", "children"),
    Output("pr-hora", "figure"), Output("pr-hora-titulo", "children"), Output("pr-hora-sub", "children"),
    Output("pr-hora-leyenda", "children"), Output("pr-hora-tabla", "children"), Output("pr-hora-lienzo", "aria-label"),
    Output("pr-hora-nota", "children"),
    Output("pr-mes", "figure"), Output("pr-mes-titulo", "children"), Output("pr-mes-sub", "children"),
    Output("pr-mes-leyenda", "children"), Output("pr-mes-tabla", "children"), Output("pr-mes-lienzo", "aria-label"),
    Output("pr-mes-error", "children"),
    Input("pr-ruta", "value"), Input("pr-fecha", "date"), Input("pr-modelo", "value"), Input("pr-comparar", "value"),
    Input("pr-mes", "clickData"), Input("pr-fecha-ant", "n_clicks"), Input("pr-fecha-sig", "n_clicks"),
)
def actualizar(ruta, fecha, modelo, comparar, click, _a, _s):
    disparo = ctx.triggered_id
    fecha = fecha or FECHA_INICIAL
    if disparo == "pr-mes" and click and click.get("points"):
        fecha = str(click["points"][0].get("x", fecha))[:10]
    elif disparo == "pr-fecha-ant":
        fecha = mover_fecha(fecha, -1)
    elif disparo == "pr-fecha-sig":
        fecha = mover_fecha(fecha, +1)
    f = pd.Timestamp(fecha).normalize()
    modelo = modelo if modelo in MODELOS else "E12"
    comparar = bool(comparar)
    h, antelacion = _antelacion()
    p = _sel(ruta or "CRA 54")
    series = _series(modelo, comparar)
    cols = ["real", "B1"] + MODELOS

    dia = p[p["dia"] == f]
    if dia.empty:
        vacia = ui.figura_vacia("Sin datos para ese día")
        aviso = [ui.aviso("No hay pronósticos para ese día. Prueba otra fecha.", "atencion")]
        return (fecha, aviso, vacia, "Sin datos para ese día", "", None, None, "Sin datos para ese día", None,
                vacia, "Sin datos para ese mes", "", None, None, "Sin datos para ese mes", None)
    horas = list(range(int(p["hora"].min()), int(p["hora"].max()) + 1))
    por_hora = dia.groupby("hora")[cols].sum().reindex(horas, fill_value=0)
    lunes = f - pd.Timedelta(days=f.dayofweek)
    semana = p[(p["dia"] >= lunes) & (p["dia"] <= lunes + pd.Timedelta(days=6))]
    mes = p[p["dia"].dt.month == f.month]
    tipo = TIPO_DIA.get(dia["tipo_dia"].iloc[0], dia["tipo_dia"].iloc[0])
    lugar = "Las tres rutas" if ruta == "todas" else ruta
    nombre_mes = ui.MESES[f.month - 1]

    # --- tarjeta del día: el error con dos decimales; la regla manual es una referencia neutra (sin tono) -----------------
    w_d, wb_d = wape(dia, modelo), wape(dia, "B1")
    real_d, pred_d = float(dia["real"].sum()), float(dia[modelo].sum())
    fin_sem = min(lunes + pd.Timedelta(days=6), pd.Timestamp("2025-12-31"))
    ini_sem = max(lunes, pd.Timestamp("2025-01-01"))
    cambio = f" ({con_signo((pred_d / real_d - 1) * 100, 1)} %)" if real_d else ""
    principal = html.Div([
        html.Div([html.P(f"Error del día · {NOMBRE_MODELO[modelo]}", className="cifra__etiqueta")]
                 + ([ui.chip("Recomendado", "acento")] if modelo == "E12" else []), className="chips"),
        html.P([html.Span(num(w_d, 2)), html.Span("%", className="heroe__unidad")], className="heroe__valor"),
        html.Div([ui.chip_valor("Regla manual:", f"{num(wb_d, 2)} %")], className="chips"),
        ui.nota(f"{ui.fecha_larga(f)} · {tipo}"),
    ], className="heroe__principal")
    pasajeros = ui.cifra("Pasajeros del día", num(real_d), None, mini=True, clase="cifra--llana",
                         variacion=f"Pronóstico {DEL_MODELO[modelo]}: {num(pred_d)}{cambio}",
                         nota=f"Suma de las {len(horas)} horas de salida ({horas[0]}–{horas[-1]} h)" + (", tres rutas." if ruta == "todas" else "."))
    rayas = html.Div(_rayas(f"Error de la semana · del {ui.fecha_corta(ini_sem)} al {ui.fecha_corta(fin_sem)}", semana, modelo),
                     className="rayas-lista")
    error_mes = _rayas(f"{nombre_mes.capitalize()} de 2025, {num(mes['dia'].nunique())} días", mes, modelo)
    fichas = [principal, pasajeros, rayas]

    # --- el día, hora por hora: el modelo en columnas (la hora pico real, sólida y con su banda) ---------------------------
    a, b = _de_cada_100(w_d, wb_d)
    x = [f"{hh} h" for hh in horas]
    pico = x[int(por_hora["real"].to_numpy().argmax())]
    fig = go.Figure()
    ui.banda_foco(fig, pico, x)
    _trazas(fig, x, por_hora, series, foco=pico, ancho=ui.ancho_barra(len(x)))
    fig.update_xaxes(tickvals=[t for hh, t in zip(horas, x) if hh % 2 == 0])
    fig.update_yaxes(rangemode="tozero", nticks=5)
    fig.update_layout(hovermode="x unified")
    ui.unidad_eje(fig, "pasajeros por hora")
    titulo_h = f"{lugar}, {ui.fecha_larga(f)}: {SUJETO[modelo]} se equivoca en {a}; la regla manual, en {b}"
    sub_h = (f"Pasajeros por hora de salida, {tipo.lower()}: lo real frente a lo pronosticado con {antelacion} de antelación"
             + (" (suma de las tres rutas)." if ruta == "todas" else "."))
    columnas = _columnas(series)
    tabla_h = ui.tabla(["Hora"] + [n for _c, n in columnas],
                       [[t] + [num(por_hora.loc[hh, c]) for c, _n in columnas] for hh, t in zip(horas, x)],
                       total=["Total del día"] + [num(por_hora[c].sum()) for c, _n in columnas], compacta=True)
    etiqueta_h = (f"{titulo_h}. Pasajeros del día: {num(real_d)} reales y {num(pred_d)} pronosticados; error del día "
                  f"{num(w_d, 2)} % y {num(wb_d, 2)} % la regla manual.")
    nota_h = (f"Fuera de muestra: cada mes de 2025 se pronosticó con un modelo entrenado solo con los días anteriores a ese mes, "
              f"y cada día con datos de hasta {h} días antes.")

    # --- el mes, día por día: la columna del día elegido, sólida y con su banda ------------------------------------------
    dm = mes.groupby("dia")[cols].sum()
    fx = list(dm.index)
    w_m, wb_m = wape(mes, modelo), wape(mes, "B1")
    a, b = _de_cada_100(w_m, wb_m)
    fm = go.Figure()
    ui.franja(fm, f - DIA / 2, f + DIA / 2)
    foco_m = f if f in dm.index else None
    _trazas(fm, fx, dm, series, foco=foco_m, ancho=ui.ancho_barra(len(fx)) * DIA.total_seconds() * 1000)
    ticks = [d for d in fx if d.dayofweek == 0] or fx[::7]
    fm.update_xaxes(tickvals=ticks, ticktext=[ui.fecha_corta(d) for d in ticks], hoverformat=f"%-d de {nombre_mes}")
    fm.update_yaxes(rangemode="tozero", nticks=5)
    fm.update_layout(hovermode="x unified")
    ui.unidad_eje(fm, "pasajeros por día")
    en = "en las tres rutas" if ruta == "todas" else f"en {ruta}"
    titulo_m = f"En {nombre_mes} de 2025 {en}, {SUJETO[modelo]} se equivoca en {a}; la regla manual, en {b}"
    sub_m = (f"Pasajeros por día (suma de las {len(horas)} horas de salida), con {antelacion} de antelación; la columna sólida "
             f"y la franja marcan el {ui.fecha_larga(f)}.")
    tabla_m = ui.tabla(["Día"] + [n for _c, n in columnas],
                       [[f"{ui.DIAS[d.dayofweek][:3]} {ui.fecha_corta(d)}"] + [num(dm.loc[d, c]) for c, _n in columnas] for d in fx],
                       total=[f"Total de {nombre_mes}"] + [num(dm[c].sum()) for c, _n in columnas], compacta=True)
    etiqueta_m = (f"{titulo_m}. Pasajeros reales del mes: {num(dm['real'].sum())}; pronosticados: {num(dm[modelo].sum())}. "
                  f"Error del mes {num(w_m, 2)} % y {num(wb_m, 2)} % la regla manual.")

    return (f.strftime("%Y-%m-%d"), fichas,
            fig, titulo_h, sub_h, _leyenda(series, f"Hora pico real ({pico})"), tabla_h, etiqueta_h, nota_h,
            fm, titulo_m, sub_m, _leyenda(series, "Día elegido" if foco_m is not None else None), tabla_m, etiqueta_m, error_mes)
