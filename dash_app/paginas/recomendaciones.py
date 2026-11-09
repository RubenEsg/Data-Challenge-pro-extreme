"""Recomendaciones: ¿Cada cuánto debe salir un bus? La frecuencia recomendada por la API frente a la frecuencia actual
(programada), por ruta y franja horaria (RF-007, RF-008, RF-015 a RF-017, §3.1, E06), con el estilo de DISENO.md.

- Cifras de la hora pico: buses por hora recomendados frente a los programados, vehículos requeridos frente a la flota
  disponible y ocupación esperada frente al rango objetivo de los umbrales vigentes (GET /api/v1/thresholds).
- Gráfico y tabla por hora: headway recomendado frente al actual (programado), buses por hora, vehículos, ocupación,
  viabilidad con su motivo y la fórmula que dio la API (GET /api/v1/recommendations).
- «Calcular escenario»: qué pasa si la demanda, la capacidad, el nivel de servicio o los pesos cambian
  (POST /api/v1/recommendations/calculate), al lado de la recomendación vigente, con todo lo que explica la API: la
  función objetivo de §10.2 (α·costo + β·espera + γ·sobreocupación + δ·desviación, cada peso con su fuente), las
  restricciones con su holgura y los límites que mandan, la mezcla de tipologías (§10.1), la frecuencia actual frente a
  la recomendada (RF-008) y, si no es viable, el motivo y la mejor aproximación ejecutable (§18).
- Plan del día por hora (GET /api/v1/recommendations/plan): el MILP de D5 con el pronóstico del modelo activo que persiste
  el ciclo diario, frente a lo programado, con la viabilidad y los límites de cada hora («sin_calcular» si aún no está).
- Exportación CSV y XLSX con los mismos filtros (GET /api/v1/recommendations/export).

«Actual» es siempre la frecuencia programada (frecuencia_actual_min de la API), no el intervalo real observado. Sin
API, la pantalla lo dice y no inventa nada: todas las cifras salen de la API."""
import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

import cliente_api as A
import ui

dash.register_page(__name__, path="/recomendaciones", name="Recomendaciones", order=7,
                   title="Recomendaciones · Sobusa Despacho")

RUTAS = [("SILENCIO", "SILENCIO"), ("CRA 54", "CRA 54"), ("CL 72", "CL 72")]
VIABLE = [("Todas", "todas"), ("Viables", "si"), ("No viables", "no")]
ACTUAL = "Frecuencia actual (programada)"
FUENTES = ["GET /api/v1/recommendations", "GET /api/v1/frequency/executions", "GET /api/v1/thresholds"]
FUENTE_CALC = ["POST /api/v1/recommendations/calculate"]
FUENTE_PLAN = ["GET /api/v1/recommendations/plan"]
CAMBIO = {"ampliar_intervalo": "ampliar el intervalo", "reducir_intervalo": "reducir el intervalo", "mantener": "mantener"}
# §10.2: los cuatro términos de la función objetivo, en su orden, con el peso que los multiplica
TERMINOS = [("costo_operativo", "alfa", "α", "Costo operativo"), ("tiempo_espera", "beta", "β", "Tiempo de espera"),
            ("sobreocupacion", "gamma", "γ", "Sobreocupación"), ("desviacion_frecuencia", "delta", "δ", "Desviación de la frecuencia")]
# El plan del día sale del modelo activo (lo persiste el ciclo diario); el experimento 12 precalculado queda como opción
MODELOS_PLAN = [("Modelo activo (API)", "activo"), ("Experimento 12 (precalculado)", "E12")]
FUENTE_PRONOSTICO = {"modelo_activo": "modelo activo", "E12": "experimento 12 precalculado (opción)"}
COMPONENTES_PLAN = {"op": "Operación (bus-hora y km)", "espera": "Espera valorada", "sobrecarga": "Sobrecarga esperada",
                    "ingreso": "Pasajes ganados (−) o perdidos (+)"}
ANIO_PLAN = 2025   # el año del calendario del plan (los días con variables y datos operativos)


def cabecera(titulo, subtitulo):
    return html.Header(html.Div([ui.cuadro("recomendaciones", "horario", "cuadro-color--cabecera"),
                                 html.H1(titulo, className="cabecera__pregunta"),
                                 html.P(subtitulo, className="cabecera__subtitulo")], className="cabecera__texto"),
                       className="cabecera")


def aviso_api(err):
    """Aviso de la API caída o de la clave sin validez (401) o sin rol (403): título y qué hacer, nunca una traza."""
    return ui.aviso([err, A.ayuda_error(err)], "atencion", A.titulo_error(err), rol="status")


def hora(h):
    return f"{int(h):02d}:00"


def minutos(x, d=1):
    return f"{ui.num(x, d)} min" if x is not None else "—"


def pct(x):
    return f"{ui.num(x * 100, 1)} %" if x is not None else "—"


def chip_viable(v):
    return ui.chip("Viable", "bien") if v else ui.chip("No viable", "critico")


def salida(r):
    """El detalle del cálculo (detalle.salida de la API), con lo que no viene en las columnas."""
    return ((r or {}).get("detalle") or {}).get("salida") or {}


def buses_actuales(r):
    s = salida(r)
    if s.get("buses_hora_actual") is not None:
        return s["buses_hora_actual"]
    f = r.get("frecuencia_actual_min")
    return 60 / f if f else None


def flota(r):
    s = salida(r)
    return s.get("flota_disponible", ((r.get("detalle") or {}).get("entradas") or {}).get("flota_disponible"))


def campo(id_, rotulo, ayuda, minimo=None, maximo=None, paso="any"):
    return html.Div([html.Label(rotulo, htmlFor=id_, className="campo__rotulo"),
                     dcc.Input(id=id_, type="number", min=minimo, max=maximo, step=paso, className="campo", debounce=True),
                     html.P(ayuda, className="campo__ayuda")], className="campo-bloque")


def layout(**_):
    controles = [
        ui.control("Ruta", ui.segmentado("re-ruta", [{"label": a, "value": b} for a, b in RUTAS], RUTAS[0][1], persistir=False)),
        ui.control("Viabilidad", ui.segmentado("re-viable", [{"label": a, "value": b} for a, b in VIABLE], "todas", persistir=False)),
    ]
    origen = [
        ui.control("Ejecución", dcc.Dropdown(id="re-ejecucion", options=[], value=None, clearable=False, searchable=False,
                                             placeholder="Cargando…", className="desplegable-api desplegable-api--ancho")),
        ui.control("Fecha", dcc.Dropdown(id="re-fecha", options=[], value=None, clearable=False, searchable=False,
                                         placeholder="—", className="desplegable-api")),
        html.Div([ui.boton("Exportar CSV", id="re-csv", icono="descargar", pequeno=True),
                  ui.boton("Exportar XLSX", id="re-xlsx", icono="descargar", pequeno=True)], className="botonera"),
    ]
    escenario = html.Div([
        html.Div([campo("re-e-hora", "Hora", "De 0 a 23.", 0, 23, 1),
                  campo("re-e-demanda", "Demanda por hora", "Pasajeros por hora (pronóstico puntual).", 0),
                  campo("re-e-p90", "Demanda P90 (opcional)", "Pasajeros por hora en el escenario alto.", 0),
                  campo("re-e-capacidad", "Capacidad por bus (opcional)", "Puestos; vacío = la de la ruta.", 1, None, 1),
                  campo("re-e-ocupacion", "Ocupación objetivo (opcional)", "En %; vacío = la de los umbrales.", 1, 100),
                  campo("re-e-servicio", "Nivel de servicio (opcional)", "En %; vacío = el de los umbrales.", 50, 99)],
                 className="api-formulario"),
        ui.desplegable("Pesos de la función objetivo (opcional)", [
            ui.nota("Vacío = el peso vigente (umbrales o el valor del código). La API dice de dónde salió cada uno."),
            html.Div([campo(f"re-e-{k}", f"{s} · {n}", "Peso sin unidad (≥ 0).", 0) for _c, k, s, n in TERMINOS],
                     className="api-formulario")], llano=True),
        html.Div(ui.boton("Calcular escenario", id="re-calcular", tipo="primario", icono="play"), className="botonera"),
        html.Div(id="re-escenario", **{"aria-live": "polite"}),
    ])
    plan = [
        ui.fila_controles([
            ui.control("Fecha del plan", dcc.DatePickerSingle(id="re-plan-fecha", date=None, display_format="DD/MM/YYYY",
                                                              month_format="MM/YYYY", first_day_of_week=1, clearable=False,
                                                              min_date_allowed=f"{ANIO_PLAN}-01-01",
                                                              max_date_allowed=f"{ANIO_PLAN}-12-31",
                                                              placeholder="dd/mm/aaaa", className="fecha")),
            ui.control("Pronóstico", ui.segmentado("re-plan-modelo", [{"label": a, "value": b} for a, b in MODELOS_PLAN], "activo",
                                                   persistir=False)),
        ]),
        html.Div(id="re-plan-cifras", **{"aria-live": "polite"}),
        ui.grafico("re-plan-grafico", titulo="Salidas por hora: plan del día frente a lo programado",
                   subtitulo="Salidas de cada hora del día de servicio; la hora con más salidas del plan va sólida.",
                   leyenda=[("Programadas hoy", "hoy", "escalon"), ("Plan del día (MILP de D5)", "modelo", "barra")],
                   alto="bajo", fuentes=FUENTE_PLAN),
        ui.tarjeta(html.Div(id="re-plan-tabla"), titulo="El plan hora por hora",
                   subtitulo="Salidas, intervalo, vehículos y pasajeros previstos; los despachos minuto a minuto en cada fila.",
                   fuentes=FUENTE_PLAN),
    ]
    return ui.pantalla([
        dcc.Store(id="re-filas", data=None),
        dcc.Download(id="re-descarga"),
        ui.arriba(cabecera("Recomendaciones", "Cada cuánto debe salir un bus en cada franja, frente a lo programado hoy."),
                  controles, html.Div([html.Div(id="re-aviso-api")], className="api-respuesta")),
        ui.seccion("Hora pico de la ruta", [ui.fila_controles(origen), html.Div(id="re-export-aviso", **{"aria-live": "polite"}),
                                            html.Div(id="re-cifras")],
                   subtitulo="Recomendado por la API frente a la frecuencia actual (programada), la flota y el objetivo de ocupación.",
                   fuentes=FUENTES),
        ui.seccion("Intervalo entre buses por hora", [
            html.Div(id="re-noviables"),
            ui.grafico("re-grafico", titulo="Headway recomendado frente al actual (programado)",
                       subtitulo="Minutos entre buses en cada franja; menos minutos es más buses por hora.",
                       leyenda=[(ACTUAL, "hoy", "rayada"), ("Recomendado por la API", "modelo", "barra")],
                       alto="bajo", fuentes=FUENTES[:1]),
        ]),
        ui.seccion("Detalle por franja", ui.tarjeta(html.Div(id="re-tabla")),
                   subtitulo="Cada fila es una recomendación de la API con su viabilidad y su motivo.", fuentes=FUENTES[:1]),
        ui.seccion("Calcular escenario", ui.tarjeta(escenario),
                   subtitulo="Qué recomienda la API si cambian la demanda, la capacidad, el nivel de servicio o los pesos "
                             "(POST /api/v1/recommendations/calculate, rol analista).",
                   intro="El escenario queda guardado en la API como una recomendación sin ejecución; la de la ejecución no cambia. "
                         "Debajo, la función objetivo, las restricciones, la mezcla de buses y la comparación con lo programado."),
        ui.seccion("Plan del día por hora", plan,
                   subtitulo="El optimizador de salidas del día (MILP de D5) para la ruta elegida, frente a la frecuencia programada.",
                   fuentes=FUENTE_PLAN),
    ], "pantalla--api")


# --- Origen: ejecuciones y fechas ---------------------------------------------------------------------------------------
@callback(Output("re-ejecucion", "options"), Output("re-ejecucion", "value"), Output("re-aviso-api", "children"),
          Input("re-ruta", "value"), State("re-ejecucion", "value"))
def ejecuciones(_ruta, actual):
    datos, err = A.obtener("frequency/executions", tipo="frecuencia", estado="ok", limite=50, orden="-creado_en")
    if err:
        return [], None, aviso_api(err)
    ops = []
    for e in datos["items"]:
        corte = e.get("marca_agua_nueva") or e.get("data_cutoff")
        texto = (f"Datos hasta {ui.fecha_corta(corte)} {pd.Timestamp(corte).year}" if corte else "Sin corte") + \
            f" · {str(e['execution_id'])[:8]}"
        ops.append({"label": texto, "value": e["execution_id"]})
    if not ops:
        return [], None, ui.aviso("La API todavía no tiene ejecuciones terminadas. Corra una desde «Operación».", None,
                                  "Sin ejecuciones", rol="status")
    valores = [o["value"] for o in ops]
    return ops, (actual if actual in valores else valores[0]), None


@callback(Output("re-fecha", "options"), Output("re-fecha", "value"),
          Input("re-ejecucion", "value"), Input("re-ruta", "value"), State("re-fecha", "value"))
def fechas(ejecucion, ruta, actual):
    if not ejecucion:
        return [], None
    datos, err = A.obtener("recommendations", execution_id=ejecucion, ruta=ruta, limite=500, orden="-fecha")
    if err:
        return [], None
    dias = sorted({r["fecha"] for r in datos["items"]}, reverse=True)
    ops = [{"label": ui.fecha_larga(d), "value": d} for d in dias]
    return ops, (actual if actual in dias else (dias[0] if dias else None))


def _filtros(ruta, viable, ejecucion, fecha):
    v = {"si": True, "no": False}.get(viable)
    return {"ruta": ruta, "viable": v, "execution_id": ejecucion, "desde": fecha, "hasta": fecha}


# --- Cifras, gráfico y tabla ----------------------------------------------------------------------------------------------
def _cifras(filas, umbrales):
    pico = max(filas, key=lambda r: (r.get("demanda_hora") or 0))
    actuales = buses_actuales(pico)
    disponible = flota(pico)
    ocupacion = pico.get("ocupacion_esperada")
    lo, hi = (umbrales or {}).get("ocupacion_objetivo_min"), (umbrales or {}).get("ocupacion_objetivo_max")
    dentro = ocupacion is not None and lo is not None and hi is not None and lo <= ocupacion <= hi
    no_viables = sum(1 for r in filas if not r["viable"])
    fichas = [
        ui.cifra(f"Buses por hora a las {hora(pico['hora'])}", ui.num(pico.get("buses_hora")), "buses/h",
                 variacion=f"programados: {ui.num(actuales, 1)} buses/h", flecha=(pico.get("buses_hora") or 0) - (actuales or 0),
                 nota=f"Headway {minutos(pico.get('headway_min'), 2)} · actual (programado) {minutos(pico.get('frecuencia_actual_min'))}"),
        ui.cifra("Vehículos requeridos en la hora pico", ui.num(pico.get("vehiculos_requeridos")), "vehículos",
                 variacion=f"flota disponible: {ui.num(disponible)}" if disponible is not None else None,
                 tono=("bien" if pico["viable"] else "mal") if disponible is not None else None,
                 nota=f"Ciclo de {minutos(salida(pico).get('tiempo_ciclo_min'))}" if salida(pico).get("tiempo_ciclo_min") else None),
        ui.cifra("Ocupación esperada en la hora pico", pct(ocupacion), None,
                 variacion=(f"objetivo {pct(lo)} a {pct(hi)}" if lo is not None and hi is not None else None),
                 tono=("bien" if dentro else None),
                 nota=f"Demanda {ui.num(pico.get('demanda_hora'))} pas/h · P90 {ui.num(pico.get('demanda_p90'))}"),
        ui.cifra("Franjas no viables", ui.num(no_viables), f"de {ui.num(len(filas))}",
                 chip=chip_viable(no_viables == 0) if no_viables == 0 else ui.chip("Revisar", "atencion"),
                 nota="Viable: la flota y el headway mínimo alcanzan para lo recomendado."),
    ]
    return ui.cifras(fichas)


def _figura(filas):
    x = [hora(r["hora"]) for r in filas]
    actual = [r.get("frecuencia_actual_min") for r in filas]
    rec = [r.get("headway_min") for r in filas]
    ancho = ui.ancho_barra(len(x))          # ≤ 24 px por barra; las dos de una franja, juntas
    hueco = ancho * 0.1
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=actual, name=ACTUAL, offset=-ancho - hueco, **ui.traza("hoy", "rayada", ancho=ancho),
                         **ui.hover(ACTUAL, actual, "min", 1)))
    fig.add_trace(go.Bar(x=x, y=rec, name="Recomendado", offset=hueco, **ui.traza("modelo", "barra", ancho=ancho),
                         **ui.hover("Recomendado", rec, "min", 2)))
    tope = max([v for v in actual + rec if v is not None] or [1])
    paso = ui.paso_redondo(tope, 4)
    vals, textos = ui.marcas(0, tope + paso * 0.5, paso)
    fig.update_layout(barmode="overlay", hovermode="x unified",
                      yaxis=dict(tickvals=vals, ticktext=textos, range=[0, max(vals) if vals else tope]))
    ui.unidad_eje(fig, "minutos entre buses")
    return fig


def _tabla(filas):
    cuerpo = []
    for r in filas:
        motivo = r.get("motivo")
        s = salida(r)
        detalle = [html.P(motivo, className="parrafo")] if motivo else []
        if r.get("formula"):
            detalle.append(html.P([html.Span("Fórmula: ", className="api-tenue"), html.Code(r["formula"])], className="api-formula"))
        if s.get("cambio"):
            detalle.append(html.P(f"Cambio frente a lo programado: {CAMBIO.get(s['cambio'], s['cambio'])}.", className="nota"))
        cuerpo.append([hora(r["hora"]), ui.num(r.get("demanda_hora")), ui.num(r.get("demanda_p90")), ui.num(r.get("buses_hora")),
                       minutos(r.get("headway_min"), 2), minutos(r.get("frecuencia_actual_min")),
                       ui.con_signo(r.get("diferencia_min"), 2) if r.get("diferencia_min") is not None else "—",
                       ui.num(r.get("vehiculos_requeridos")), pct(r.get("ocupacion_esperada")), chip_viable(r["viable"]),
                       html.Div(ui.desplegable("Motivo y fórmula" if motivo else "Fórmula", detalle, llano=True, pequeno=True),
                                className="api-motivo")])
    return ui.tabla(["Hora", "Demanda", "P90", "Buses/h", "Headway recomendado", "Headway actual (programado)",
                     "Diferencia (min)", "Vehículos", "Ocupación", "Viable", "Motivo"], cuerpo,
                    num=[False, True, True, True, True, True, True, True, True, False, False], compacta=True,
                    ocultar_movil=(2, 6, 8))


@callback(Output("re-cifras", "children"), Output("re-grafico", "figure"), Output("re-grafico-lienzo", "aria-label"),
          Output("re-grafico-tabla", "children"), Output("re-tabla", "children"), Output("re-noviables", "children"),
          Output("re-filas", "data"),
          Input("re-ruta", "value"), Input("re-viable", "value"), Input("re-ejecucion", "value"), Input("re-fecha", "value"))
def mostrar(ruta, viable, ejecucion, fecha):
    vacio = ui.figura_vacia("Sin datos de la API")
    if not ejecucion:
        return None, vacio, "Sin datos", None, ui.nota("Sin recomendaciones: elija una ejecución."), None, None
    datos, err = A.obtener("recommendations", **_filtros(ruta, viable, ejecucion, fecha), limite=500, orden="hora")
    if err:
        return aviso_api(err), vacio, "Sin datos", None, None, None, None
    filas = sorted(datos["items"], key=lambda r: r["hora"])
    if not filas:
        nada = ui.aviso("Ninguna recomendación cumple estos filtros.", None, "Sin recomendaciones", rol="status")
        return nada, vacio, "Sin datos", None, None, None, None
    u, _err_u = A.obtener("thresholds")
    fig = _figura(filas)
    etiqueta = "; ".join(f"{hora(r['hora'])}: recomendado {minutos(r.get('headway_min'), 2)}, actual "
                         f"{minutos(r.get('frecuencia_actual_min'))}" for r in filas)
    gemela = ui.tabla(["Hora", "Recomendado (min)", "Actual programado (min)"],
                      [[hora(r["hora"]), ui.num(r.get("headway_min"), 2), ui.num(r.get("frecuencia_actual_min"), 1)] for r in filas],
                      compacta=True)
    malas = [r for r in filas if not r["viable"]]
    aviso = None
    if malas:
        aviso = ui.aviso([f"{hora(r['hora'])} · {r.get('motivo') or 'sin motivo'}" for r in malas], "canje",
                         f"{ui.num(len(malas))} de {ui.num(len(filas))} franjas no son viables con la flota y el headway mínimo")
    return (_cifras(filas, (u or {}).get("valores")), fig, f"Headway por hora en {ruta}: {etiqueta}", gemela, _tabla(filas),
            aviso, filas)


# --- Escenario ----------------------------------------------------------------------------------------------------------
@callback(Output("re-e-hora", "value"), Output("re-e-demanda", "value"), Output("re-e-p90", "value"),
          Input("re-filas", "data"))
def prellenar(filas):
    """El escenario parte de la hora pico de la recomendación elegida (cifras de la API, nunca escritas a mano)."""
    if not filas:
        return no_update, no_update, no_update
    pico = max(filas, key=lambda r: (r.get("demanda_hora") or 0))
    return pico["hora"], round(pico.get("demanda_hora") or 0), round(pico.get("demanda_p90") or 0) or None


def _es_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _base_objetivo(r):
    """La evaluación de la solución que la API recomienda (o, si no es viable, la de su mejor aproximación)."""
    if not r.get("viable") and r.get("mejor_aproximacion"):
        return r["mejor_aproximacion"]
    return ((r.get("comparacion_actual") or {}).get("recomendada")) or {}


def bloque_objetivo(r):
    """§10.2: min α·costo + β·espera + γ·sobreocupación + δ·desviación, término por término (COP por hora), con el peso,
    su fuente y el valor ponderado; las partes en barras rayadas de un total positivo."""
    obj = r.get("objetivo") or {}
    pesos = obj.get("pesos") or {}
    base = _base_objetivo(r)
    comp = base.get("componentes_cop") or {}
    total = base.get("total_ponderado_cop")
    if not comp:
        return ui.nota("La API no devolvió los componentes de la función objetivo para este cálculo.")
    filas, partes = [], []
    for clave, k, simbolo, nombre in TERMINOS:
        p = pesos.get(k) or {}
        v, w = comp.get(clave), p.get("valor")
        ponderado = w * v if _es_num(w) and _es_num(v) else None
        partes.append((f"{simbolo} · {nombre}", ponderado))
        termino = html.Span([html.Span(f"{simbolo} · {nombre}"), html.Br(),
                             html.Span(f"peso: {p.get('fuente') or '—'}", className="api-tenue")])
        filas.append([termino, ui.num(w, 2), ui.num(v), ui.num(ponderado)])
    suma = sum(x for _n, x in partes if _es_num(x) and x > 0) or 1
    barras = [ui.barra_rayas(n, f"{ui.num(x)} COP/h", x / suma, "modelo") for n, x in partes if _es_num(x) and x >= 0]
    tabla = ui.tabla(["Término y fuente del peso", "Peso", "Componente", "Ponderado"], filas,
                     total=["Total ponderado (COP/h)", "", "", ui.num(total)], compacta=True,
                     num=[False, True, True, True], ocultar_movil=(2,))
    definiciones = obj.get("definiciones") or {}
    parametros = obj.get("parametros") or {}
    detalle = [html.P([html.Span(f"{k}: ", className="api-tenue"), html.Code(v)], className="api-formula")
               for k, v in definiciones.items()]
    detalle += [html.P(f"{k.replace('_', ' ')}: {ui.num(v.get('valor'), 2)} · {v.get('fuente') or '—'}", className="nota")
                for k, v in parametros.items() if isinstance(v, dict)]
    rotulo = "de la mejor aproximación ejecutable" if not r.get("viable") and r.get("mejor_aproximacion") else "de la solución recomendada"
    return [ui.nota(f"{obj.get('expresion') or 'Función objetivo de §10.2'} · valores {rotulo}."),
            html.Div(barras, className="rayas-lista"), tabla,
            ui.desplegable("Qué mide cada término y con qué costos", detalle, llano=True) if detalle else None]


def bloque_restricciones(r):
    """Restricciones de la franja con su valor, su límite y su holgura, y los límites que mandan (activos)."""
    restr = r.get("restricciones") or []
    activos = r.get("limites_activos") or []
    chips = [ui.chip(nombre.replace("_", " "), None, "alerta") for nombre in activos] or [ui.chip("Ninguno activo", None, "info")]
    filas = []
    for x in restr:
        unidad = x.get("unidad") or ""
        estado = ui.chip("Activa: manda", None, "alerta") if x.get("activa") else ui.chip("Con holgura", None, "bien")
        valor = f"{ui.num(x.get('valor'), 2)}" if _es_num(x.get("valor")) else "—"
        limite = f"{ui.num(x.get('limite'), 2)}" if _es_num(x.get("limite")) else "sin límite fijo"
        filas.append([html.Div([html.Span(x.get("descripcion") or x.get("nombre") or "—"),
                                html.Span(f" · {x.get('nombre')}", className="api-tenue"), html.Div(estado)]),
                      html.Span([valor, html.Br(), html.Span(f"límite {limite} {unidad}".strip(), className="api-tenue")]),
                      ui.num(x.get("holgura"), 2) if _es_num(x.get("holgura")) else "—"])
    return [html.Div([html.Span("Límites que mandan:", className="api-tenue")] + chips, className="api-chips"),
            ui.tabla(["Restricción", "Valor y límite", "Holgura"], filas, compacta=True, num=[False, True, True]) if filas else
            ui.nota("La API no devolvió restricciones para este cálculo.")]


def bloque_tipologias(r):
    """§10.1: cuántos buses por hora de cada tipología propone la API y con cuántos vehículos."""
    t = r.get("tipologias") or {}
    asign = t.get("asignacion") or (r.get("mejor_aproximacion") or {}).get("asignacion") or []
    if not asign:
        return ui.nota("Este cálculo no asignó tipologías (la API usa la capacidad única de la ruta).")
    filas = [[f"{x.get('codigo')} · {x.get('nombre')}", ui.num(x.get("capacidad")), ui.num(x.get("buses_hora")),
              ui.num(x.get("vehiculos")), ui.num(x.get("disponibles")), ui.num(x.get("maximo_buses_hora"))] for x in asign]
    total_b = sum(x.get("buses_hora") or 0 for x in asign)
    total_v = sum(x.get("vehiculos") or 0 for x in asign)
    return [ui.tabla(["Tipología", "Puestos", "Buses/h", "Vehículos", "Disponibles", "Máximo buses/h"], filas,
                     total=["Total", "", ui.num(total_b), ui.num(total_v), "", ""], compacta=True, ocultar_movil=(4, 5)),
            ui.nota(f"Fuente: {t.get('fuente') or 'la flota registrada de la ruta'}.")]


def bloque_comparacion(r):
    """RF-008: la frecuencia actual (programada) frente a la recomendada, con sus costos y si cumplen el servicio."""
    c = r.get("comparacion_actual") or {}
    act, rec, dif = c.get("actual") or {}, c.get("recomendada") or {}, c.get("diferencia") or {}
    if not act and not rec:
        return ui.nota("La API no devolvió la comparación con la frecuencia actual (falta la frecuencia programada de la franja).")

    def si_no(x):
        if x is None:
            return "—"
        return ui.chip("Sí", "bien") if x else ui.chip("No", "critico")

    def pct(x):
        return f"{ui.num(x * 100, 1)} %" if _es_num(x) else "—"

    filas = [
        ["Intervalo entre buses", minutos(act.get("frecuencia_min"), 2), minutos(rec.get("frecuencia_min"), 2), "—"],
        ["Buses por hora", ui.num(act.get("buses_hora"), 1), ui.num(rec.get("buses_hora"), 1), ui.con_signo(dif.get("buses_hora"), 1)],
        ["Vehículos requeridos", ui.num(act.get("vehiculos_requeridos")), ui.num(rec.get("vehiculos_requeridos")),
         ui.con_signo(dif.get("vehiculos_requeridos"))],
        ["Capacidad ofrecida (puestos/h)", ui.num(act.get("capacidad_ofrecida")), ui.num(rec.get("capacidad_ofrecida")), "—"],
        ["Ocupación esperada", pct(act.get("ocupacion_esperada")), pct(rec.get("ocupacion_esperada")), "—"],
        ["Espera media (min)", ui.num(act.get("espera_media_min"), 2), ui.num(rec.get("espera_media_min"), 2),
         ui.con_signo(dif.get("espera_media_min"), 2)],
        ["Pasajeros sobre la capacidad", ui.num(act.get("sobrecarga_esperada_pax"), 1), ui.num(rec.get("sobrecarga_esperada_pax"), 1),
         ui.con_signo(dif.get("sobrecarga_esperada_pax"), 1)],
        ["Costo ponderado (COP/h)", ui.num(act.get("total_ponderado_cop")), ui.num(rec.get("total_ponderado_cop")),
         ui.con_signo(dif.get("total_ponderado_cop"))],
        ["Cumple el nivel de servicio", si_no(act.get("cumple_nivel_servicio")), si_no(rec.get("cumple_nivel_servicio")), ""],
        ["Cabe en la flota", si_no(act.get("cabe_en_la_flota")), si_no(rec.get("cabe_en_la_flota")), ""],
    ]
    return [ui.tabla(["", ACTUAL, "Recomendada", "Diferencia"], filas, compacta=True, num=[False, True, True, True]),
            ui.nota(f"Conclusión de la API: {c['conclusion']}") if c.get("conclusion") else None]


def bloque_no_viable(r):
    """§18 «Recomendación inviable»: el motivo con sus cifras y la mejor aproximación ejecutable, a la vista."""
    if r.get("viable"):
        return None
    m = r.get("mejor_aproximacion") or {}
    texto = [r.get("motivo") or "La API no dio el motivo."]
    if m:
        cobertura = m.get("cobertura_nivel_servicio")
        texto.append(f"Mejor aproximación ejecutable: {ui.num(m.get('buses_hora'))} buses/h cada {minutos(m.get('headway_min'), 2)}, "
                     f"{ui.num(m.get('vehiculos_requeridos'))} vehículos y {ui.num(m.get('capacidad_efectiva_pasajeros_h'))} "
                     f"pasajeros/h de capacidad efectiva"
                     + (f" ({ui.num(cobertura * 100, 1)} % de la carga del nivel de servicio)." if _es_num(cobertura) else "."))
        if m.get("aviso"):
            texto.append(m["aviso"])
    else:
        texto.append("No hay una aproximación ejecutable: la API no fuerza cifras.")
    return ui.aviso(texto, "critico", "El escenario no es viable")


@callback(Output("re-escenario", "children"), Input("re-calcular", "n_clicks"),
          State("re-ruta", "value"), State("re-e-hora", "value"), State("re-e-demanda", "value"), State("re-e-p90", "value"),
          State("re-e-capacidad", "value"), State("re-e-ocupacion", "value"), State("re-e-servicio", "value"),
          *[State(f"re-e-{k}", "value") for _c, k, _s, _n in TERMINOS], State("re-filas", "data"),
          prevent_initial_call=True)
def calcular(clic, ruta, h, demanda, p90, capacidad, ocupacion, servicio, alfa, beta, gamma, delta, filas):
    if not clic:
        return no_update
    if h is None or demanda is None:
        return ui.aviso("Indique la hora y la demanda por hora.", "atencion", "Faltan datos", rol="status")
    cuerpo = {"ruta": ruta, "hora": int(h), "demanda_hora": float(demanda)}
    fecha_vigente = next((f.get("fecha") for f in (filas or []) if f.get("fecha")), None)
    if fecha_vigente:
        cuerpo["fecha"] = fecha_vigente
    if p90 not in (None, ""):
        cuerpo["demanda_p90"] = float(p90)
    if capacidad not in (None, ""):
        cuerpo["capacidad"] = int(capacidad)
    if ocupacion not in (None, ""):
        cuerpo["ocupacion_objetivo"] = float(ocupacion) / 100
    if servicio not in (None, ""):
        cuerpo["nivel_servicio"] = float(servicio) / 100
    pesos = {k: float(v) for (_c, k, _s, _n), v in zip(TERMINOS, (alfa, beta, gamma, delta), strict=True)
             if v not in (None, "")}
    if pesos:
        cuerpo["pesos"] = pesos
    r, err = A.enviar("POST", "recommendations/calculate", cuerpo)
    if err:
        return ui.aviso([err, A.ayuda_error(err)] if A.titulo_error(err) != "La API respondió con un error" else err,
                        "atencion", "La API no calculó el escenario", rol="status")
    vigente = next((f for f in (filas or []) if f["hora"] == r["hora"]), None)

    def col(x):
        if x is None:
            return ["—"] * 6
        return [ui.num(x.get("demanda_hora")), ui.num(x.get("buses_hora")), minutos(x.get("headway_min"), 2),
                ui.num(x.get("vehiculos_requeridos")), pct(x.get("ocupacion_esperada")), chip_viable(x["viable"])]

    rotulos = ["Demanda (pas/h)", "Buses por hora", "Headway", "Vehículos requeridos", "Ocupación esperada", "Viable"]
    a, b = col(vigente), col(r)
    tabla = ui.tabla(["", f"Vigente a las {hora(r['hora'])}", "Escenario"], [[rotulos[i], a[i], b[i]] for i in range(6)],
                     compacta=True, num=[False, True, True])
    partes = [bloque_no_viable(r), tabla,
              ui.rejilla([ui.tarjeta(bloque_objetivo(r), titulo="Función objetivo (§10.2)",
                                     subtitulo="α·costo operativo + β·tiempo de espera + γ·sobreocupación + δ·desviación de la "
                                               "frecuencia, en COP por hora; cada peso con su fuente.", fuentes=FUENTE_CALC),
                          ui.tarjeta(bloque_restricciones(r), titulo="Restricciones y límites que mandan",
                                     subtitulo="Valor, límite y holgura de cada restricción; las activas son las que fijan la respuesta.",
                                     fuentes=FUENTE_CALC)], "1-1"),
              ui.rejilla([ui.tarjeta(bloque_tipologias(r), titulo="Mezcla de tipologías (§10.1)",
                                     subtitulo="Buses por hora de cada tipo de bus y los vehículos que ocupan en el ciclo.",
                                     fuentes=FUENTE_CALC),
                          ui.tarjeta(bloque_comparacion(r), titulo="Actual frente a recomendada (RF-008)",
                                     subtitulo="La frecuencia programada de la franja frente a la que recomienda la API.",
                                     fuentes=FUENTE_CALC)], "1-1")]
    explicacion = [html.Li(t) for t in (r.get("explicacion") or [])]
    if explicacion or r.get("formula"):
        partes.append(ui.desplegable("Cómo lo calculó la API", [html.Ul(explicacion, className="api-lista") if explicacion else None,
                                                                 html.P(html.Code(r["formula"]), className="api-formula")
                                                                 if r.get("formula") else None], llano=True))
    solver = r.get("solver") or {}
    partes.append(ui.nota(f"Guardado como {str(r['recommendation_id'])[:8]} · umbrales versión {ui.num(r.get('umbrales_version'))}"
                          + (f" · {solver.get('formulacion')}: {solver.get('estado')} en {ui.num(solver.get('segundos'), 2)} s"
                             if solver.get("formulacion") else "")))
    return html.Div([p for p in partes if p is not None], className="api-escenario")


# --- Plan del día (D5) ------------------------------------------------------------------------------------------------
@callback(Output("re-plan-fecha", "date"), Input("re-fecha", "value"), State("re-plan-fecha", "date"))
def fecha_plan(fecha, actual):
    """El plan arranca en la fecha de la recomendación elegida (si es de 2025, el año con insumos de D5)."""
    if fecha and str(fecha).startswith(str(ANIO_PLAN)):
        return fecha
    return actual or no_update


def _figura_plan(horas):
    x = [hora(h["hora"]) for h in horas]
    plan = [h.get("salidas") for h in horas]
    prog = [h.get("salidas_programadas") for h in horas]
    foco = x[plan.index(max(plan))] if plan and any(_es_num(v) for v in plan) else None
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=plan, name="Plan del día", **ui.barras_foco("modelo", x, foco, ancho=ui.ancho_barra(len(x))),
                         **ui.hover("Plan del día", plan, "salidas")))
    fig.add_trace(go.Scatter(x=x, y=prog, name="Programadas hoy", **ui.traza("hoy", "escalon"),
                             **ui.hover("Programadas hoy", prog, "salidas", 1)))
    if foco is not None:
        ui.banda_foco(fig, foco, x)
    tope = max([v for v in plan + prog if _es_num(v)] or [1])
    paso = ui.paso_redondo(tope, 4)
    vals, textos = ui.marcas(0, tope + paso * 0.5, paso)
    fig.update_layout(yaxis=dict(tickvals=vals, ticktext=textos, range=[0, max(vals) if vals else tope]))
    ui.unidad_eje(fig, "salidas por hora")
    return fig


@callback(Output("re-plan-cifras", "children"), Output("re-plan-grafico", "figure"), Output("re-plan-grafico-lienzo", "aria-label"),
          Output("re-plan-grafico-tabla", "children"), Output("re-plan-tabla", "children"),
          Input("re-ruta", "value"), Input("re-plan-fecha", "date"), Input("re-plan-modelo", "value"))
def plan_dia(ruta, fecha, modelo):
    vacio = ui.figura_vacia("Sin plan")
    if not fecha:
        return (ui.nota(f"Elija una fecha de {ANIO_PLAN} (el año con los insumos del optimizador)."), vacio, "Sin datos", None, None)
    modelo = modelo if modelo in {b for _a, b in MODELOS_PLAN} else "activo"
    p, err, codigo = A.obtener_con_codigo("recommendations/plan", ruta=ruta, fecha=str(fecha)[:10], pronostico=modelo)
    if err:
        if codigo == "sin_calcular":   # §7.1: el GET solo lee el plan que dejó el ciclo diario
            aviso = ui.aviso([err, "El ciclo diario calcula el plan del día siguiente al cerrar; para otro día, la respuesta "
                                   "del reto lo pide con POST /api/v1/respuesta/calcular (Inicio lo hace solo)."],
                             None, "El plan de ese día todavía no está calculado", rol="status")
        elif codigo == "plan_no_disponible":
            aviso = ui.aviso(err, None, "No hay plan para esa fecha", rol="status")
        else:
            aviso = aviso_api(err)
        return aviso, vacio, "Sin datos", None, None
    horas = sorted(p.get("horas") or [], key=lambda h: h["hora"])
    if not horas:
        return ui.aviso("La API no devolvió horas para ese plan.", None, "Plan vacío", rol="status"), vacio, "Sin datos", None, None
    pico = max(horas, key=lambda h: h.get("salidas") or 0)
    comp = p.get("componentes_costo_cop") or {}
    flota_d = p.get("flota_disponible")
    dif_dia = (p.get("salidas_dia") or 0) - (p.get("salidas_programadas_dia") or 0) if _es_num(p.get("salidas_programadas_dia")) else None
    fichas = ui.cifras([
        ui.cifra("Salidas del día con el plan", ui.num(p.get("salidas_dia")), "salidas",
                 variacion=f"programadas: {ui.num(p.get('salidas_programadas_dia'), 1)}", flecha=dif_dia,
                 nota=f"{ui.fecha_larga(p['fecha'])} · {p.get('tipo_dia') or '—'}"),
        ui.cifra(f"Hora con más salidas: {hora(pico['hora'])}", ui.num(pico.get("salidas")), "salidas",
                 variacion=f"cada {minutos(pico.get('headway_min'), 2)} · programado cada {minutos(pico.get('frecuencia_actual_min'), 2)}",
                 nota=f"{ui.num(pico.get('pasajeros_previstos'))} pasajeros previstos en esa hora"),
        ui.cifra("Vehículos en la hora pico", ui.num(p.get("vehiculos_hora_pico")), "vehículos",
                 variacion=f"flota disponible: {ui.num(flota_d)}" if _es_num(flota_d) else None,
                 nota="Vehículos requeridos = techo(ciclo / headway) en la hora de más carga."),
        ui.cifra("Costo del día del plan", ui.num((p.get("costo_total_cop") or 0) / 1e6, 1) if _es_num(p.get("costo_total_cop")) else "—",
                 "M COP", nota=" · ".join(f"{COMPONENTES_PLAN.get(k, k)} {ui.num(v / 1e6, 1)}" for k, v in comp.items() if _es_num(v))
                 or None),
    ])
    fuente = p.get("fuente_pronostico")
    pron = FUENTE_PRONOSTICO.get(fuente) or ui.NOMBRE_MODELO.get(p.get("modelo"), p.get("modelo") or "—")
    estado = html.Div([ui.chip_valor("Solver:", p.get("estado_solver") or "—"), ui.chip_valor("Pronóstico:", pron)]
                      + ([ui.chip_valor("Modelo:", p["model_id"])] if p.get("model_id") else [])
                      + ([ui.chip_valor("Calibración:", p["calibracion_version"])] if p.get("calibracion_version") else [])
                      + ([ui.chip("Plan del día no viable en alguna hora", "atencion")] if p.get("viable") is False else [])
                      + [ui.chip_valor("Costos:", p.get("fuente_costos") or "—")], className="api-chips")
    formulacion = ui.desplegable("Cómo se resuelve el plan", html.P(p.get("formulacion") or "—", className="parrafo"), llano=True)
    fig = _figura_plan(horas)
    etiqueta = f"Salidas por hora en {ruta} el {ui.fecha_larga(p['fecha'])}: " + "; ".join(
        f"{hora(h['hora'])} plan {ui.num(h.get('salidas'))}, programadas {ui.num(h.get('salidas_programadas'), 1)}" for h in horas)
    gemela = ui.tabla(["Hora", "Plan (salidas)", "Programadas"],
                      [[hora(h["hora"]), ui.num(h.get("salidas")), ui.num(h.get("salidas_programadas"), 1)] for h in horas], compacta=True)
    filas = []
    for h in horas:
        desp = h.get("despachos") or []
        filas.append([hora(h["hora"]), ui.num(h.get("salidas")), ui.num(h.get("salidas_programadas"), 1),
                      ui.con_signo(h.get("diferencia_salidas"), 1) if _es_num(h.get("diferencia_salidas")) else "—",
                      minutos(h.get("headway_min"), 2), minutos(h.get("frecuencia_actual_min"), 2),
                      ui.num(h.get("vehiculos_requeridos")), _pasajeros_hora(h), _viable_hora(h),
                      ui.desplegable(f"{ui.num(len(desp))} despachos", html.P(" · ".join(desp), className="api-formula"),
                                     llano=True, pequeno=True) if desp else "—"])
    tabla = ui.tabla(["Hora", "Salidas", "Programadas", "Diferencia", "Headway", "Headway programado", "Vehículos",
                      "Pasajeros previstos", "Viable y límites", "Despachos"], filas, compacta=True,
                     num=[False, True, True, True, True, True, True, True, False, False], ocultar_movil=(2, 5, 7, 9))
    return [fichas, estado, formulacion], fig, etiqueta, gemela, tabla


def _pasajeros_hora(h):
    """P50 de la hora y, si la API la trae, su banda P10–P90 del modelo activo."""
    if _es_num(h.get("pasajeros_p10")) and _es_num(h.get("pasajeros_p90")):
        return html.Span([html.Span(ui.num(h.get("pasajeros_previstos"))), html.Br(),
                          html.Span(f"{ui.num(h['pasajeros_p10'])} a {ui.num(h['pasajeros_p90'])}", className="api-tenue")])
    return ui.num(h.get("pasajeros_previstos"))


def _viable_hora(h):
    """La viabilidad de la hora con su motivo y los límites que mandan (§10.1–§10.3)."""
    if h.get("viable") is None and not h.get("limites_activos"):
        return "—"
    partes = [chip_viable(h.get("viable") is not False)]
    if h.get("limites_activos"):
        partes += [html.Br(), html.Span("Mandan: " + ", ".join(str(x) for x in h["limites_activos"]), className="api-tenue")]
    if h.get("viable") is False and h.get("motivo"):
        partes += [html.Br(), html.Span(h["motivo"], className="api-tenue")]
    return html.Span(partes)


# --- Exportación ------------------------------------------------------------------------------------------------------
@callback(Output("re-descarga", "data"), Output("re-export-aviso", "children"),
          Input("re-csv", "n_clicks"), Input("re-xlsx", "n_clicks"),
          State("re-ruta", "value"), State("re-viable", "value"), State("re-ejecucion", "value"), State("re-fecha", "value"),
          prevent_initial_call=True)
def exportar(_csv, _xlsx, ruta, viable, ejecucion, fecha):
    if not ctx.triggered[0].get("value"):
        return no_update, no_update
    formato = "xlsx" if ctx.triggered_id == "re-xlsx" else "csv"
    archivo, err = A.descargar("recommendations", formato, **_filtros(ruta, viable, ejecucion, fecha), orden="hora")
    if err:
        return no_update, ui.aviso(err, "atencion", "No se pudo exportar", rol="status")
    contenido, nombre = archivo
    return dcc.send_bytes(contenido, nombre), None
