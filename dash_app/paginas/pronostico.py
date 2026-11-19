"""Pronóstico: ¿Cuántos pasajeros habrá? Tres partes, cada una con su rótulo (DISENO.md §8):

0. «Lo que pide el enunciado: 30, 60 y 120 minutos» (corto_plazo_vista.py): con lo que ya subió hoy, las subidas de los
   próximos 30, 60 y 120 minutos por ruta, sentido y segmento, con el modelo de corto plazo que sirve la API
   (GET /api/v1/predictions/corto-plazo/calcular y /dia) y las cifras de su prueba reservada (datos/corto_plazo.json).
1. «Modelo horario de la API: el plan del día siguiente»: los pronósticos que guarda la API del reto con el modelo que ejecuta (GET /api/v1/predictions,
   paginado, con los filtros ruta, fecha y horizonte). Muestra la banda P10–P90 calibrada frente a lo real cuando ya se
   conoce (pasajeros validados de 2025 de datos/pronosticos_2025.parquet, con la misma fracción de cada hora que usa la
   API para la ventana), el modelo (model_id), la versión de la calibración y, de la predicción elegida, las variables que
   más la mueven (SHAP, GET /api/v1/predictions/{id}). Exporta CSV y XLSX (GET /api/v1/predictions/export). Sin API, la
   parte lo dice y no inventa nada.
2. «Laboratorio del informe académico: experimento 11 / experimento 12»: los pronósticos fuera de muestra del informe
   (siete días de antelación, todo 2025), de datos/pronosticos_2025.parquet, datos/cifras_app.json y
   datos/ficha_modelos.json. No son el modelo de la API: se explica por qué sus cifras difieren de las del producto."""
import functools

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

import cliente_api as API
import corto_plazo_vista as CPV
import datos_app as D
import ui
from controles import FECHA_INICIAL, mover_fecha, selector_fecha
from ui import NOMBRE_MODELO, con_signo, num

dash.register_page(__name__, path="/pronostico", name="Pronóstico", order=1, title="Pronóstico · Sobusa Despacho")

MODELOS = ["E11", "E12"]                       # el orden fijo de los experimentos del informe
RUTAS = [("Las tres rutas", "todas"), ("SILENCIO", "SILENCIO"), ("CRA 54", "CRA 54"), ("CL 72", "CL 72")]
TIPO_DIA = {"Domingo/festivo": "Domingo o festivo"}
SUJETO = {"E11": "el experimento 11", "E12": "el experimento 12"}
DEL_MODELO = {"E11": "del experimento 11", "E12": "del experimento 12"}
REGLA = "Regla manual (hoy)"
FUENTES = ["datos/pronosticos_2025.parquet",
           "experimentos/E11_modelo_mejorado/predicciones_2025.parquet (real, experimento 11 y regla manual)",
           "experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet (experimento 12)"]
DIA = pd.Timedelta(days=1)

# --- Modelo activo (API) ---------------------------------------------------------------------------------------------
RUTAS_API = ["SILENCIO", "CRA 54", "CL 72"]
HORIZONTES = [30, 60, 120]
POR_PAGINA = 10
TOPE_DIA = 500                                 # pronósticos de un día que se piden para la banda (la API admite 500)
FUENTES_API = ["GET /api/v1/predictions (ruta, desde, hasta, horizonte_min, limite, desplazamiento)",
               "datos/pronosticos_2025.parquet (lo real: pasajeros validados por hora de 2025)"]
FUENTE_DETALLE = "GET /api/v1/predictions/{id} · explicacion_local (SHAP) y variables.calibracion_version"
MAX_FACTORES = 5


def _antelacion():
    """Días de antelación de los pronósticos del informe (el horizonte más corto evaluado en cifras_app.json) y su nombre."""
    h = int(min(D.valor("demanda", "demanda_wape_antelacion")["E11_V4"], key=int))
    return h, ("una semana" if h == 7 else f"{h} días")


def _pliegues():
    return D.valor("modelo", "modelo_final_pliegues")["pliegues_mensuales_2025"]


def _es_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _instante(x):
    t = pd.Timestamp(x)
    return t.tz_convert("America/Bogota") if t.tzinfo is not None else t


def _hhmm(x):
    return f"{_instante(x):%H:%M}" if x else "—"


def _generada(x):
    if not x:
        return "—"
    t = _instante(x)
    return f"{ui.fecha_corta(t)} {t.year} · {t:%H:%M}"


def _calibracion(p):
    return (p.get("variables") or {}).get("calibracion_version") or (p.get("variables") or {}).get("conformal", {}).get("version")


def _selector_fecha_api():
    """Día anterior → calendario (cualquier día: la API guarda pronósticos de las fechas que pidió el ciclo) → siguiente."""
    return html.Div([
        html.Button(ui.icono("chevron-izquierda", "glifo--m"), id="pr-api-fecha-ant", type="button",
                    className="boton boton--secundario boton--icono", title="Día anterior", **{"aria-label": "Día anterior"}),
        dcc.DatePickerSingle(id="pr-api-fecha", date=None, display_format="DD/MM/YYYY", month_format="MM/YYYY",
                             first_day_of_week=1, clearable=False, placeholder="dd/mm/aaaa", className="fecha"),
        html.Button(ui.icono("chevron-derecha", "glifo--m"), id="pr-api-fecha-sig", type="button",
                    className="boton boton--secundario boton--icono", title="Día siguiente", **{"aria-label": "Día siguiente"}),
    ], className="selector-fecha")


def _seccion_api(P):
    controles = [
        ui.control("Ruta", ui.segmentado("pr-api-ruta", RUTAS_API, "CRA 54", persistir=False)),
        ui.control("Fecha", _selector_fecha_api()),
        ui.control("Horizonte", ui.segmentado("pr-api-h", [{"label": f"{h} min", "value": h} for h in HORIZONTES], 60,
                                              persistir=False)),
        html.Div([ui.boton("Exportar CSV", id="pr-api-csv", icono="descargar", pequeno=True),
                  ui.boton("Exportar XLSX", id="pr-api-xlsx", icono="descargar", pequeno=True)], className="botonera"),
    ]
    banda = ui.grafico("pr-api-banda", titulo="", subtitulo="", etiqueta="", alto="normal", fuentes=FUENTES_API)
    detalle = ui.tarjeta(html.Div(ui.nota("Elija un pronóstico de la lista."), id="pr-api-detalle", **{"aria-live": "polite"}),
                         titulo="Por qué ese pronóstico",
                         subtitulo="Las variables que más mueven el pronóstico elegido (SHAP del modelo activo).",
                         fuentes=[FUENTE_DETALLE], id="pr-api-tarjeta-detalle")
    lista = ui.tarjeta([html.Div(id="pr-api-lista"),
                        html.Div([ui.boton("Anterior", id="pr-api-ant", icono="chevron-izquierda", pequeno=True),
                                  html.Span(id="pr-api-paginas", className="api-paginas"),
                                  ui.boton("Siguiente", id="pr-api-sig", icono="chevron-derecha", pequeno=True)],
                                 className="api-paginacion")],
                       titulo="Pronósticos guardados en la API",
                       subtitulo=f"{num(POR_PAGINA)} por página, en el orden de la ventana. Elija uno para ver sus variables.",
                       fuentes=FUENTES_API[:1], id="pr-api-tarjeta-lista")
    como = ui.desplegable("Cómo se lee esta parte", [
        ui.parrafo("Cada pronóstico es de una ventana que empieza a la hora del instante y dura el horizonte (30, 60 o 120 min). "
                   "La API guarda el pasajero esperado (P50), la banda P10–P90 ya calibrada, el modelo que lo produjo, la versión "
                   "de la calibración, la de las variables y el corte de los datos con que se entrenó."),
        ui.parrafo("Lo real sale de los pasajeros validados de 2025 (datos/pronosticos_2025.parquet): para cada ventana se suman "
                   "las horas que cubre con la misma fracción de la hora que usa la API (variables.por_hora). Si la fecha no "
                   "está en 2025, lo real todavía no se conoce y no se dibuja."),
        ui.parrafo("Las variables del detalle son la explicación local SHAP de la hora principal de la ventana: el pronóstico es "
                   "la base del modelo multiplicada por el factor de cada variable; el efecto reparte en pasajeros lo que cada "
                   "una suma o resta."),
        ui.fuentes(FUENTES_API + [FUENTE_DETALLE]),
    ])
    sub = ("El modelo horario de la API pronostica cada hora con siete días de antelación: sirve para armar el horario del "
           "día siguiente. La banda P10–P90 calibrada frente a lo real.")
    if P:
        sub = (f"El modelo horario de la API ({P['model_id']}) pronostica cada hora con siete días de antelación: sirve para "
               "armar el horario del día siguiente. La banda P10–P90 calibrada frente a lo real cuando ya se conoce, y por "
               "qué sale cada cifra.")
    return ui.seccion("Modelo horario de la API: el plan del día siguiente", [
        html.Div(id="pr-api-aviso", **{"aria-live": "polite"}),
        html.Div(id="pr-api-cifras"),
        ui.rejilla([banda, detalle], "2-1"),
        lista,
        como,
    ], subtitulo=sub, controles=controles, id="pr-api")


def _seccion_laboratorio(b1, e12, h, antelacion):
    controles = [
        ui.control("Ruta", ui.segmentado("pr-ruta", [{"label": a, "value": b} for a, b in RUTAS], "CRA 54")),
        ui.control("Día de 2025", selector_fecha("pr-fecha", FECHA_INICIAL)),
        ui.control("Experimento", ui.segmentado("pr-modelo", [{"label": NOMBRE_MODELO[m], "value": m} for m in MODELOS], "E12")),
    ]
    WAPE = D.ficha_modelos()["convenciones"]["WAPE"]["texto"]
    P = D.modelo_producto()
    por_que = ("Sus cifras no se comparan con las del modelo activo: son otra métrica y otro protocolo (pronóstico con "
               f"{antelacion} de antelación, WAPE sobre todo 2025 con {_pliegues()} pliegues mensuales).")
    if P:
        por_que += (f" El modelo activo se mide en la prueba de {ui.fecha_corta(P['prueba']['desde'])} a "
                    f"{ui.fecha_corta(P['prueba']['hasta'])} de 2025 con el protocolo de la API: "
                    f"{num(P['wape_modelo'], 2)} % frente a {num(P['wape_regla_manual'], 2)} % de la regla manual.")
    como = ui.desplegable("Cómo se calcula el laboratorio", [
        ui.parrafo(f"Pronósticos fuera de muestra del informe académico. Cada mes de 2025 se pronosticó con un modelo entrenado solo "
                   f"con los días anteriores a ese mes, y cada día con datos de hasta {h} días antes: el modelo no vio ese mes al "
                   f"entrenar. Son los mismos pronósticos de las tablas del informe ({_pliegues()} pliegues mensuales)."),
        ui.parrafo(f"El error es el WAPE. {WAPE} Se calcula sobre las franjas de ruta, día y hora del periodo: el día, la "
                   "semana de lunes a domingo o el mes. Con «Las tres rutas» se usan las franjas de las tres; los gráficos suman las "
                   "tres rutas en cada hora."),
        ui.parrafo(f"La regla manual es lo que Sobusa hace hoy: {D.valor('inicio', 'inicio_regla_manual_definicion')} Se dibuja "
                   "siempre, en gris punteado, como referencia."),
        ui.parrafo("El experimento elegido va en columnas azules rayadas; la sólida marca la hora pico real del día (en el mes, el "
                   "día elegido). Al comparar, el experimento 12 va en columnas y el experimento 11, en línea azul a trazos. Lo real "
                   "es la línea negra."),
        ui.fuentes(FUENTES + ["datos/cifras_app.json", "datos/ficha_modelos.json"]),
    ])

    # El día hora por hora (con la casilla de comparar junto a su leyenda) y, al lado, la tarjeta de errores del día elegido
    hora = ui.grafico("pr-hora", titulo="", subtitulo="", etiqueta="", alto="alto", fuentes=FUENTES)
    hora.children.insert(2, ui.fila_controles([ui.casilla("pr-comparar", [{"label": "Comparar con el otro experimento", "value": "si"}])]))
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
        num(e12), f"de cada 100 pasajeros de 2025 los estima mal el experimento 12, con {antelacion} de antelación",
        f"La regla manual se equivoca en {num(b1)} de cada 100 con el mismo protocolo. Son pronósticos fuera de muestra del "
        "informe académico, no del modelo que ejecuta la API.", chip_="Informe académico")
    return ui.seccion("Laboratorio del informe académico: experimento 11 / experimento 12", [
        ui.aviso(por_que, None, "No es el modelo de la API", rol="note"),
        html.Div([html.H3("El día, hora por hora", className="oculto"), ui.rejilla([hora, dia], "2-1")]),
        html.Div([html.H3("El mes, día por día", className="oculto"),
                  ui.rejilla([mes, html.Div([error_mes, lectura], className="rejilla")], "2-1")]),
        como,
    ], subtitulo="Los pronósticos fuera de muestra del informe académico (experimentos 11 y 12), con los que se estudió el "
                 "problema; se conservan como laboratorio.", controles=controles, id="pr-laboratorio")


def layout(**_):
    b1, e12 = D.valor("inicio", "inicio_error_regla_manual"), D.valor("inicio", "inicio_error_hibrido")
    h, antelacion = _antelacion()
    P = D.modelo_producto()
    cp = D.corto_plazo()
    if cp:
        r60 = cp["niveles"]["ruta"]["60"]
        sub = (f"Con lo que ya subió hoy, la API pronostica los próximos 30, 60 y 120 minutos por ruta, sentido y segmento: a "
               f"60 minutos se equivoca en {num(r60['modelo'], 1)} de cada 100 subidas; el promedio por día y hora, en "
               f"{num(r60['promedio_dia_hora'], 1)}.")
    elif P:
        sub = (f"El modelo activo de la API pronostica cada ruta y ventana con su banda P10–P90: en la prueba de nov–dic 2025 "
               f"se equivoca en {num(P['wape_modelo'])} de cada 100 pasajeros; la regla manual, en {num(P['wape_regla_manual'])}.")
    else:
        sub = "El modelo activo de la API pronostica cada ruta y ventana con su banda P10–P90."
    cabecera = ui.cabecera("pronostico", "¿Cuántos pasajeros habrá?", sub)
    return ui.pantalla([
        dcc.Store(id="pr-api-pagina", data=0),
        dcc.Store(id="pr-api-sel", data=None),
        dcc.Download(id="pr-api-descarga"),
        ui.arriba(cabecera),
        CPV.seccion(),
        _seccion_api(P),
        _seccion_laboratorio(b1, e12, h, antelacion),
    ])


# --- Modelo activo (API): datos ---------------------------------------------------------------------------------------
def _real_ventana(p):
    """Pasajeros validados de la ventana (2025): Σ fracción de la hora × real de esa hora, con las horas que la API usó en
    variables.por_hora. None si alguna hora no está en los datos (fecha fuera de 2025 o sin servicio)."""
    horas = [x for x in (p.get("variables") or {}).get("por_hora") or [] if isinstance(x, dict)]
    if not horas:
        return None
    real = _reales()
    total = 0.0
    for x in horas:
        v = real.get((p["ruta"], str(x.get("fecha"))[:10], int(x.get("hora", -1))))
        if v is None:
            return None
        total += float(x.get("fraccion") or 0) * v
    return total


@functools.lru_cache(maxsize=1)
def _reales():
    """(ruta, «AAAA-MM-DD», hora) → pasajeros validados de 2025 (datos/pronosticos_2025.parquet), una sola vez."""
    p = D.pronosticos()
    return {(r, d.strftime("%Y-%m-%d"), int(h)): float(v)
            for r, d, h, v in zip(p["ruta"], p["dia"], p["hora"], p["real"])}


def _ultimos_por_ventana(items):
    """Si la misma ventana se pronosticó varias veces, el más reciente (generated_at)."""
    por = {}
    for p in items:
        k = p.get("instante")
        if k not in por or str(p.get("generated_at")) > str(por[k].get("generated_at")):
            por[k] = p
    return [por[k] for k in sorted(por, key=lambda s: pd.Timestamp(s))]


def _fecha_reciente(ruta, horizonte):
    d, err = API.obtener("predictions", ruta=ruta, horizonte_min=horizonte, limite=1, orden="-fecha")
    if err or not d or not d.get("items"):
        return None, err
    return d["items"][0]["fecha"], None


def _figura_banda(dia, reales, ruta, fecha, h):
    x = [_hhmm(p["instante"]) for p in dia]
    lo = [p.get("p10") for p in dia]
    hi = [p.get("p90") for p in dia]
    p50 = [p.get("pasajeros") for p in dia]
    fig = go.Figure()
    ui.banda(fig, x, lo, hi, "modelo")
    textos = [f"Pronóstico P50: <b>{num(m)}</b> pasajeros · banda {num(a)} a {num(b)}" for m, a, b in zip(p50, lo, hi)]
    fig.add_trace(go.Scatter(x=x, y=p50, name="Pronóstico (P50)", **ui.traza("modelo", "linea", marcadores=True),
                             **ui.hover_texto(textos)))
    hay_real = any(r is not None for r in reales)
    if hay_real:
        fig.add_trace(go.Scatter(x=x, y=reales, name="Real", **ui.traza("real", "gruesa", marcadores=True),
                                 **ui.hover("Real", reales, "pasajeros"), zorder=1))
    fig.update_yaxes(rangemode="tozero", nticks=5)
    fig.update_layout(hovermode="x unified")
    ui.unidad_eje(fig, f"pasajeros por ventana de {h} min")
    leyenda = [("Real (validaciones de 2025)", "real", "gruesa")] if hay_real else []
    leyenda += [("Pronóstico del modelo activo (P50)", "modelo", "linea"), ("Banda P10–P90 calibrada", "modelo", "area")]
    suma_p = sum(v for v in p50 if _es_num(v))
    conocidos = [(r, a, b) for r, a, b in zip(reales, lo, hi) if r is not None and _es_num(a) and _es_num(b)]
    dentro = sum(1 for r, a, b in conocidos if a <= r <= b)
    fecha_t = ui.fecha_larga(fecha)
    if hay_real:
        suma_r = sum(r for r in reales if r is not None)
        titulo = (f"{ruta}, {fecha_t}: lo real cae dentro de la banda en {num(dentro)} de {num(len(conocidos))} ventanas; "
                  f"se pronosticaron {num(suma_p)} pasajeros y llegaron {num(suma_r)}")
    else:
        titulo = f"{ruta}, {fecha_t}: el modelo activo pronostica {num(suma_p)} pasajeros en {num(len(dia))} ventanas de {h} min"
    sub = (f"Pasajeros por ventana de {h} min que empieza a la hora del eje: el pronóstico P50 del modelo activo, su banda "
           "P10–P90 calibrada y" + (" lo real (pasajeros validados de 2025)." if hay_real else " lo real cuando se conozca."))
    filas = [[t, num(a), num(m), num(b), num(r) if r is not None else "—",
              ("sí" if a <= r <= b else "no") if r is not None and _es_num(a) and _es_num(b) else "—"]
             for t, a, m, b, r in zip(x, lo, p50, hi, reales)]
    tabla = ui.tabla(["Ventana", "P10", "P50", "P90", "Real", "Dentro de la banda"], filas, compacta=True,
                     num=[False, True, True, True, True, False])
    etiqueta = f"{titulo}. " + "; ".join(f"{t}: P50 {num(m)}, banda {num(a)} a {num(b)}" + (f", real {num(r)}" if r is not None else "")
                                         for t, a, m, b, r in zip(x, lo, p50, hi, reales))
    nota = (f"Cobertura del día: {num(dentro)} de {num(len(conocidos))} ventanas dentro de la banda (la calibración apunta a ocho "
            "de cada diez)." if conocidos else "Lo real de esa fecha todavía no se conoce: solo se dibuja el pronóstico.")
    return fig, titulo, sub, ui.leyenda(leyenda, ordenar=False), tabla, etiqueta[:1200], nota


def _cifras_api(dia, reales, h):
    modelos = sorted({p.get("model_id") for p in dia if p.get("model_id")})
    calib = sorted({str(_calibracion(p)) for p in dia if _calibracion(p)})
    fv = sorted({p.get("feature_version") for p in dia if p.get("feature_version")})
    corte = sorted({str(p.get("data_cutoff"))[:10] for p in dia if p.get("data_cutoff")})
    suma_p = sum(p["pasajeros"] for p in dia if _es_num(p.get("pasajeros")))
    conocidos = [(r, p) for r, p in zip(reales, dia) if r is not None]
    fichas = [
        ui.cifra("Modelo que los produjo", ", ".join(modelos) or "—", None, mini=True,
                 chip=ui.chip(f"Calibración {', '.join(calib)}") if calib else None,
                 nota=f"Variables {', '.join(fv) or '—'} · datos hasta el {', '.join(_fecha_corta_anio(c) for c in corte) or '—'}."),
        ui.cifra("Ventanas pronosticadas ese día", num(len(dia)), f"de {h} min", mini=True,
                 nota=f"De {_hhmm(dia[0]['instante'])} a {_hhmm(dia[-1]['instante'])}; la más reciente de cada ventana."),
    ]
    if conocidos:
        suma_r = sum(r for r, _p in conocidos)
        suma_pc = sum(p["pasajeros"] for _r, p in conocidos)
        error = sum(abs(p["pasajeros"] - r) for r, p in conocidos) / suma_r * 100 if suma_r else None
        fichas.append(ui.cifra("Pasajeros de esas ventanas", num(suma_r), "reales", mini=True,
                               variacion=f"Pronóstico P50: {num(suma_pc)} ({con_signo((suma_pc / suma_r - 1) * 100, 1)} %)"
                               if suma_r else None,
                               nota=f"Error (WAPE) de las {num(len(conocidos))} ventanas con dato real: {num(error, 1)} %. "
                                    "Un solo día: la cifra del modelo es la de la prueba de nov–dic 2025 (El modelo)."
                               if error is not None else None))
    else:
        fichas.append(ui.cifra("Pasajeros pronosticados", num(suma_p), "P50", mini=True,
                               nota="Lo real de esa fecha todavía no se conoce."))
    return ui.cifras(fichas)


def _fecha_corta_anio(iso):
    try:
        t = pd.Timestamp(iso)
    except (TypeError, ValueError):
        return str(iso)
    return f"{ui.fecha_corta(t)} {t.year}"


def _tabla_lista(items, sel, reales_por_id):
    filas = []
    for p in items:
        actual = p["prediction_id"] == sel
        ventana = f"{_hhmm(p['instante'])}–{_hhmm(p['objetivo'])}"
        boton = html.Button(ventana, id={"tipo": "pr-api-fila", "id": p["prediction_id"]}, type="button",
                            className="api-fila" + (" api-fila--activa" if actual else ""),
                            title=f"Ver por qué el pronóstico de {ventana}", **{"aria-pressed": "true" if actual else "false"})
        r = reales_por_id.get(p["prediction_id"])
        filas.append([boton, num(p.get("pasajeros")), f"{num(p.get('p10'))} a {num(p.get('p90'))}",
                      num(r) if r is not None else "—", html.Span(p.get("model_id") or "—", className="api-nowrap"),
                      str(_calibracion(p) or "—"), html.Span(_generada(p.get("generated_at")), className="api-nowrap")])
    return ui.tabla(["Ventana", "P50", "Banda P10–P90", "Real", "Modelo", "Calibración", "Generado"], filas, compacta=True,
                    num=[False, True, True, True, False, False, False], ocultar_movil=(4, 6))


@callback(Output("pr-api-fecha", "date"), Output("pr-api-aviso", "children"), Output("pr-api-cifras", "children"),
          Output("pr-api-banda", "figure"), Output("pr-api-banda-titulo", "children"), Output("pr-api-banda-sub", "children"),
          Output("pr-api-banda-leyenda", "children"), Output("pr-api-banda-tabla", "children"),
          Output("pr-api-banda-lienzo", "aria-label"), Output("pr-api-banda-nota", "children"),
          Output("pr-api-lista", "children"), Output("pr-api-paginas", "children"), Output("pr-api-ant", "disabled"),
          Output("pr-api-sig", "disabled"), Output("pr-api-pagina", "data"), Output("pr-api-sel", "data"),
          Input("pr-api-ruta", "value"), Input("pr-api-fecha", "date"), Input("pr-api-h", "value"),
          Input("pr-api-fecha-ant", "n_clicks"), Input("pr-api-fecha-sig", "n_clicks"),
          Input("pr-api-ant", "n_clicks"), Input("pr-api-sig", "n_clicks"),
          State("pr-api-pagina", "data"), State("pr-api-sel", "data"))
def api_pronosticos(ruta, fecha, h, _fa, _fs, _pa, _ps, pagina, sel):
    disparo = ctx.triggered_id
    ruta = ruta if ruta in RUTAS_API else "CRA 54"
    h = h if h in HORIZONTES else 60
    pagina = pagina or 0
    vacia = ui.figura_vacia("Sin pronósticos")
    sin = (vacia, "Sin pronósticos para mostrar", "", None, None, "Sin pronósticos", None)

    def salida(fecha_, aviso, cifras=None, graf=sin, lista=None, paginas="", ant=True, sig=True, pag=0, sel_=None):
        return (fecha_, aviso, cifras, *graf, lista, paginas, ant, sig, pag, sel_)

    if not fecha:
        fecha, err = _fecha_reciente(ruta, h)
        if err:
            return salida(no_update, ui.aviso([err, API.ayuda_error(err)], "atencion", API.titulo_error(err), rol="status"),
                          lista=ui.nota("Sin datos: la API no está disponible."))
        if not fecha:
            return salida(no_update, ui.aviso(f"La API todavía no guarda pronósticos de {ruta} con {h} min de horizonte. Corra "
                                              "el ciclo diario (Operación › Ejecutar día siguiente) o POST /predictions/run.",
                                              None, "Sin pronósticos todavía", rol="status"))
    elif disparo in ("pr-api-fecha-ant", "pr-api-fecha-sig"):
        fecha = (pd.Timestamp(fecha) + pd.Timedelta(days=-1 if disparo == "pr-api-fecha-ant" else 1)).strftime("%Y-%m-%d")
    fecha = str(fecha)[:10]
    if disparo in ("pr-api-ruta", "pr-api-h", "pr-api-fecha", "pr-api-fecha-ant", "pr-api-fecha-sig"):
        pagina = 0
    elif disparo == "pr-api-ant":
        pagina = max(0, pagina - 1)
    elif disparo == "pr-api-sig":
        pagina += 1

    todo, err = API.obtener("predictions", ruta=ruta, desde=fecha, hasta=fecha, horizonte_min=h, limite=TOPE_DIA, orden="instante")
    if err:
        return salida(fecha, ui.aviso([err, API.ayuda_error(err)], "atencion", API.titulo_error(err), rol="status"),
                      lista=ui.nota("Sin datos: la API no está disponible."))
    if not todo["items"]:
        reciente, _e = _fecha_reciente(ruta, h)
        pista = f" El más reciente de {ruta} con {h} min es del {_fecha_corta_anio(reciente)}." if reciente else ""
        return salida(fecha, ui.aviso(f"La API no guarda pronósticos de {ruta} con {h} min de horizonte para el "
                                      f"{ui.fecha_larga(fecha)}.{pista}", None, "Sin pronósticos ese día", rol="status"),
                      lista=ui.nota("Ningún pronóstico con estos filtros."))
    dia = _ultimos_por_ventana(todo["items"])
    reales = [_real_ventana(p) for p in dia]
    graf = _figura_banda(dia, reales, ruta, fecha, h)
    cifras = _cifras_api(dia, reales, h)

    pag, err = API.obtener("predictions", ruta=ruta, desde=fecha, hasta=fecha, horizonte_min=h, limite=POR_PAGINA,
                           desplazamiento=pagina * POR_PAGINA, orden="instante")
    if err:
        return salida(fecha, ui.aviso(err, "atencion", API.titulo_error(err), rol="status"), cifras, graf)
    total = pag["total"]
    paginas = max(1, -(-total // POR_PAGINA))
    items = pag["items"]
    reales_id = {p["prediction_id"]: _real_ventana(p) for p in items}
    ids = [p["prediction_id"] for p in items]
    nuevo_sel = sel if sel in ids else (ids[0] if ids else None)
    texto = f"Página {num(pagina + 1)} de {num(paginas)} · {num(total)} pronósticos de {ruta} con {h} min el {_fecha_corta_anio(fecha)}"
    aviso = None
    if todo["total"] > len(todo["items"]):
        aviso = ui.aviso(f"La banda usa los primeros {num(len(todo['items']))} de {num(todo['total'])} pronósticos del día.", None,
                         "Día con muchos pronósticos", rol="status")
    return salida(fecha, aviso, cifras, graf, _tabla_lista(items, nuevo_sel, reales_id), texto, pagina == 0,
                  pagina >= paginas - 1, pagina, nuevo_sel)


@callback(Output("pr-api-sel", "data", allow_duplicate=True), Input({"tipo": "pr-api-fila", "id": ALL}, "n_clicks"),
          prevent_initial_call=True)
def api_elegir(clics):
    if not ctx.triggered_id or not any(clics or []):
        return no_update
    return ctx.triggered_id["id"]


# Resalta la fila elegida sin volver a pedir la lista
dash.clientside_callback(
    """function (sel) {
        document.querySelectorAll('#pr-api-lista .api-fila').forEach(function (b) {
            var mia = b.id && sel && b.id.indexOf(sel) >= 0;
            b.classList.toggle('api-fila--activa', !!mia);
            b.setAttribute('aria-pressed', mia ? 'true' : 'false');
        });
        return window.dash_clientside.no_update;
    }""", Output("pr-api-tarjeta-detalle", "className"), Input("pr-api-sel", "data"), prevent_initial_call=True)


def _factores(local):
    """Tabla de las variables SHAP de la hora principal: descripción, valor, factor multiplicativo y efecto en pasajeros."""
    factores = [f for f in (local.get("factores") or []) if isinstance(f, dict)][:MAX_FACTORES]
    filas = []
    for i, f in enumerate(factores, 1):
        desc = f.get("descripcion") or f.get("variable") or "—"
        nombre = html.Span([html.Span(desc[0].upper() + desc[1:]), html.Br(),
                            html.Span(f"{f.get('variable')} = {num(f.get('valor'), 1) if _es_num(f.get('valor')) else '—'}",
                                      className="api-tenue")])
        filas.append([num(i), nombre, f"× {num(f.get('factor_multiplicativo'), 3)}",
                      f"{con_signo(f.get('efecto_pasajeros'), 1)} pas." if _es_num(f.get("efecto_pasajeros")) else "—"])
    return ui.tabla(["#", "Variable", "Factor", "Efecto"], filas, compacta=True, num=[True, False, True, True])


@callback(Output("pr-api-detalle", "children"), Input("pr-api-sel", "data"))
def api_detalle(sel):
    if not sel:
        return ui.nota("Elija un pronóstico de la lista.")
    p, err = API.obtener(f"predictions/{sel}")
    if err:
        return ui.aviso(err, "atencion", "No se pudo leer el pronóstico", rol="status")
    local = p.get("explicacion_local") or (p.get("variables") or {}).get("explicacion_local") or {}
    chips = html.Div([ui.chip_valor("Ventana:", f"{_hhmm(p['instante'])}–{_hhmm(p['objetivo'])}"),
                      ui.chip_valor("Modelo:", p.get("model_id") or "—"),
                      ui.chip_valor("Calibración:", str(_calibracion(p) or "—"))], className="api-chips")
    cuerpo = [chips,
              ui.cifra("Pasajeros esperados en la ventana", num(p.get("pasajeros")), "P50", mini=True, clase="cifra--llana",
                       variacion=f"banda P10–P90: {num(p.get('p10'))} a {num(p.get('p90'))}",
                       nota=f"Sin calibrar: {num(p.get('p10_modelo'))} a {num(p.get('p90_modelo'))} · ajuste conformal "
                            f"{num(p.get('ajuste_conformal'), 3)} · {num(p.get('latencia_ms'), 1)} ms.")]
    if local.get("metodo") == "shap_tree_exacto":
        cuerpo += [html.H4(f"Hora principal {num(local.get('hora'))} h: base {num(local.get('base_pasajeros'))} → "
                           f"{num(local.get('pronostico_hora'))} pasajeros", className="api-grupo__titulo"),
                   _factores(local),
                   ui.nota(f"El resto de las variables: × {num(local.get('factor_resto'), 3)} "
                           f"({con_signo(local.get('efecto_resto_pasajeros'), 1)} pasajeros). Método: SHAP exacto de los árboles.")]
    elif local.get("importancia_global"):
        imp = [x for x in local["importancia_global"] if isinstance(x, dict)][:MAX_FACTORES]
        cuerpo += [ui.nota(local.get("motivo") or "Sin explicación local: importancia global del modelo."),
                   ui.tabla(["Variable", "Importancia"], [[x.get("variable") or "—", num(x.get("aumento_mae") or x.get("importancia"), 1)]
                                                         for x in imp], compacta=True)]
    else:
        cuerpo.append(ui.nota("La API no trae la explicación local de este pronóstico."))
    frases = [x for x in (p.get("explicacion") or []) if isinstance(x, str)][:2]
    if frases:
        cuerpo.append(ui.desplegable("La explicación de la API", [html.P(x, className="nota") for x in frases], llano=True))
    return html.Div(cuerpo, className="api-resumen")


@callback(Output("pr-api-descarga", "data"), Output("pr-api-aviso", "children", allow_duplicate=True),
          Input("pr-api-csv", "n_clicks"), Input("pr-api-xlsx", "n_clicks"),
          State("pr-api-ruta", "value"), State("pr-api-fecha", "date"), State("pr-api-h", "value"), prevent_initial_call=True)
def api_exportar(_csv, _xlsx, ruta, fecha, h):
    """Los pronósticos de esos filtros en CSV o XLSX (GET /api/v1/predictions/export), por el servidor del Dash."""
    if not ctx.triggered[0].get("value"):
        return no_update, no_update
    formato = "xlsx" if ctx.triggered_id == "pr-api-xlsx" else "csv"
    f = str(fecha)[:10] if fecha else None
    archivo, err = API.descargar("predictions", formato, ruta=ruta, desde=f, hasta=f, horizonte_min=h, orden="instante")
    if err:
        return no_update, ui.aviso(err, "atencion", "No se pudo exportar", rol="status")
    contenido, nombre = archivo
    return dcc.send_bytes(contenido, nombre), no_update


# --- Laboratorio del informe académico ----------------------------------------------------------------------------------
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
    lo real en negro (se dibuja encima con zorder), la regla manual en gris punteado, el experimento en columnas (rayadas,
    la de foco sólida) y, al comparar, el experimento 11 a trazos."""
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
    """Columnas de la tabla gemela en el orden fijo: real, regla manual, experimento 11, experimento 12."""
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
    """Subtítulo del periodo y sus dos barras rayadas: el experimento (azul) y la regla manual (gris), en % de los pasajeros."""
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
    cambio = f" ({con_signo((pred_d / real_d - 1) * 100, 1)} %)" if real_d else ""
    principal = html.Div([
        html.Div([html.P(f"Error del día · {NOMBRE_MODELO[modelo]}", className="cifra__etiqueta")], className="chips"),
        html.P([html.Span(num(w_d, 2)), html.Span("%", className="heroe__unidad")], className="heroe__valor"),
        html.Div([ui.chip_valor("Regla manual:", f"{num(wb_d, 2)} %")], className="chips"),
        ui.nota(f"{ui.fecha_larga(f)} · {tipo}"),
    ], className="heroe__principal")
    pasajeros = ui.cifra("Pasajeros del día", num(real_d), None, mini=True, clase="cifra--llana",
                         variacion=f"Pronóstico {DEL_MODELO[modelo]}: {num(pred_d)}{cambio}",
                         nota=f"Suma de las {len(horas)} horas de salida ({horas[0]}–{horas[-1]} h)" + (", tres rutas." if ruta == "todas" else "."))
    rayas = html.Div(_rayas(f"Error de la semana · del {ui.fecha_corta(ini_sem)} al {ui.fecha_corta(fin_sem)}", semana, modelo),
                     className="rayas-lista")
    error_mes = _rayas(f"{nombre_mes.capitalize()} de 2025, {num(mes['dia'].nunique())} días", mes, modelo)
    fichas = [principal, pasajeros, rayas]

    # --- el día, hora por hora: el experimento en columnas (la hora pico real, sólida y con su banda) ----------------------
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
