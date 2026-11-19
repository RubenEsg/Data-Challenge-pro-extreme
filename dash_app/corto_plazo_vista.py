"""Pronóstico › «Lo que pide el enunciado»: cuántos pasajeros subirán en los próximos 30, 60 y 120 minutos, por ruta,
sentido y segmento, con lo que ya subió hoy (spec v1.5 §2.2 «horizontes configurables de 30, 60 y 120 minutos»,
RF-005, §3.1 M3 «por ruta, sentido, segmento y franja horaria → pronóstico e intervalo de confianza»).

- La parte interactiva pide a la API el pronóstico del instante elegido (GET /api/v1/predictions/corto-plazo/calcular:
  ruta, sentidos, segmentos, banda P10–P90, líneas base, explicación local y recomendación) y la curva del día (GET
  /api/v1/predictions/corto-plazo/dia). Sin API lo dice y no inventa nada.
- La prueba reservada (julio a diciembre de 2025, calculada una sola vez) sale de datos/corto_plazo.json y se ve sin API.
- «El modelo»: la importancia global, el último monitoreo y quién lo activó (GET /api/v1/predictions/corto-plazo/modelo,
  GET /api/v1/monitoring?familia=corto_plazo); y un aviso cuando la regla de calidad VAL-009 excluyó una celda.
El modelo es el del experimento E14 (pronostico_corto_plazo/), el mismo que sirve la API."""
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, ctx, dcc, html, no_update

import cliente_api as API
import datos_app as D
import ui
from ui import con_signo, num

RUTAS = ["SILENCIO", "CRA 54", "CL 72"]
HORIZONTES = [30, 60, 120]
NIVELES = [("ruta", "Ruta"), ("sentido", "Sentido"), ("segmento", "Segmento")]
PRIMERA, ULTIMA = (4, 0), (21, 0)              # el modelo se eligió y se midió en las medias horas de 04:00 a 21:00
HORAS = [f"{h:02d}:{m:02d}" for h in range(PRIMERA[0], ULTIMA[0] + 1) for m in (0, 30) if (h, m) <= ULTIMA]
FUENTES_API = ["GET /api/v1/predictions/corto-plazo/calcular (ruta, instante, horizonte_min)",
               "GET /api/v1/predictions/corto-plazo/dia (ruta, fecha, horizonte_min)"]
FUENTES_MODELO = ["GET /api/v1/predictions/corto-plazo/modelo", "GET /api/v1/monitoring?familia=corto_plazo"]
VARIABLES_IMPORTANCIA = 8
FACTORES = 5
HORA_INICIAL = "17:00"


def _cp():
    return D.corto_plazo() or {}


def _periodo():
    cp = _cp()
    return (cp.get("periodo") or [None, None])


def _fecha_inicial():
    return (_cp().get("dia_de_ejemplo") or {}).get("fecha") or _periodo()[0]


def _selector_fecha():
    ini, fin = _periodo()
    return html.Div([
        html.Button(ui.icono("chevron-izquierda", "glifo--m"), id="cp-fecha-ant", type="button",
                    className="boton boton--secundario boton--icono", title="Día anterior", **{"aria-label": "Día anterior"}),
        dcc.DatePickerSingle(id="cp-fecha", date=_fecha_inicial(), min_date_allowed=ini, max_date_allowed=fin,
                             display_format="DD/MM/YYYY", month_format="MM/YYYY", first_day_of_week=1, clearable=False,
                             placeholder="dd/mm/aaaa", className="fecha"),
        html.Button(ui.icono("chevron-derecha", "glifo--m"), id="cp-fecha-sig", type="button",
                    className="boton boton--secundario boton--icono", title="Día siguiente", **{"aria-label": "Día siguiente"}),
    ], className="selector-fecha")


def _tabla_prueba(cp):
    """Error (WAPE) de la prueba reservada por nivel y horizonte: el modelo, el promedio por día y hora, la última semana
    y la cobertura de la banda; el mejor de cada fila en negrita."""
    filas, mejor = [], []
    for nivel, nombre in NIVELES:
        for h in HORIZONTES:
            v = cp["niveles"][nivel][str(h)]
            valores = [v["modelo"], v["promedio_dia_hora"], v["ultima_semana"]]
            mejor.append((len(filas), 1 + valores.index(min(valores))))
            filas.append([f"{nombre} · {num(h)} min", f"{num(v['modelo'], 2)} %", f"{num(v['promedio_dia_hora'], 2)} %",
                          f"{num(v['ultima_semana'], 2)} %", f"{num(v['cobertura'], 1)} %"])
    return ui.tabla(["Nivel y horizonte", "Modelo", "Promedio por día y hora", "Última semana", "Cobertura P10–P90"],
                    filas, mejor=mejor, compacta=True)


def _prueba():
    cp = _cp()
    if not cp:
        return ui.aviso("Falta datos/corto_plazo.json: corra «python preparar_datos.py --solo-corto-plazo».", "atencion",
                        "Sin las cifras de la prueba", rol="status")
    ini, fin = cp["periodo"]
    r60 = cp["niveles"]["ruta"]["60"]
    seg = cp["segmentos_60"]
    tabla = ui.tarjeta(_tabla_prueba(cp), titulo="Cómo le fue en la prueba reservada",
                       subtitulo=(f"Error (WAPE, % de las subidas) del {ui.fecha_larga(ini)} al {ui.fecha_larga(fin)}, "
                                  "calculado una sola vez. Se entrenó con lo anterior y se eligió con enero a junio de "
                                  "2025."),
                       detalles=[ui.parrafo("El WAPE suma los errores absolutos y los divide por las subidas reales. La "
                                            "cobertura dice cuántas ventanas reales cayeron dentro de la banda P10–P90 "
                                            "(apunta a ocho de cada diez).")],
                       fuentes=[cp["origen"]["prueba"]])
    dom = cp["tipo_de_dia_60"]["domingo"]
    cra = cp["domingos_cra54_60"]
    fest = cp["tipo_de_dia_60"]["festivo"]
    lectura = ui.tarjeta([
        ui.cifras([
            ui.cifra("Por ruta, a 60 minutos", f"{num(r60['modelo'], 2)} %", "de error", mini=True,
                     variacion=f"El promedio por día y hora: {num(r60['promedio_dia_hora'], 2)} %",
                     nota=(f"Diferencia con IC95 de {con_signo(r60['ic95_diferencia'][0], 2)} a "
                           f"{con_signo(r60['ic95_diferencia'][1], 2)} puntos.")),
            ui.cifra("Segmentos en que gana, a 60 minutos", f"{num(seg['gana'])} de {num(seg['con_subidas'])}", None,
                     mini=True, nota=f"Llevan el {num(seg['subidas_pct'], 1)} % de las subidas."),
        ]),
        ui.aviso(f"En los {num(dom['dias'])} domingos corrientes el modelo no mejora al promedio por día y hora "
                 f"({num(dom['modelo'], 2)} % frente a {num(dom['promedio_dia_hora'], 2)} % por ruta a 60 minutos); la "
                 f"pérdida está en CRA 54 ({num(cra['modelo'], 2)} % frente a {num(cra['promedio_dia_hora'], 2)} %). La "
                 f"ventaja de los domingos y festivos viene de los {num(fest['dias'])} festivos, donde el promedio "
                 f"pronostica un día corriente ({num(fest['promedio_dia_hora'], 2)} %; el modelo, "
                 f"{num(fest['modelo'], 2)} %). No se sabe por qué pasa en CRA 54.", None, "Lo que no funcionó",
                 rol="note"),
    ], titulo="La lectura", subtitulo="Lo que gana el modelo y dónde no.",
        fuentes=[cp["origen"]["prueba"], cp["origen"]["domingos"]])
    return ui.rejilla([tabla, lectura], "2-1")


def seccion():
    """La sección completa: controles, cifras del instante, la curva del día, el perfil por segmento, por qué sale ese
    número, la prueba reservada y cómo se lee."""
    controles = [
        ui.control("Ruta", ui.segmentado("cp-ruta", RUTAS, "CRA 54", persistir=False)),
        ui.control("Fecha", _selector_fecha()),
        ui.control("Hora", dcc.Dropdown(id="cp-hora", options=HORAS, value=HORA_INICIAL, clearable=False, searchable=False,
                                        className="desplegable-api")),
        ui.control("Horizonte", ui.segmentado("cp-h", [{"label": f"{h} min", "value": h} for h in HORIZONTES], 60,
                                              persistir=False)),
    ]
    dia = ui.grafico("cp-dia", titulo="", subtitulo="", etiqueta="", alto="alto", fuentes=FUENTES_API[1:])
    porque = ui.tarjeta(html.Div(id="cp-porque", **{"aria-live": "polite"}), titulo="Por qué ese número",
                        subtitulo="Las variables que más mueven el pronóstico de la ruta en ese instante.",
                        fuentes=FUENTES_API[:1])
    segmentos = ui.grafico("cp-seg", titulo="", subtitulo="", etiqueta="", alto="alto", fuentes=FUENTES_API[:1])
    sentidos = ui.tarjeta(html.Div(id="cp-sentidos", **{"aria-live": "polite"}), titulo="Por sentido",
                          subtitulo="Ida y regreso: la suma de sus segmentos, con su propia banda; y lo que ya subió.",
                          fuentes=FUENTES_API[:1])
    modelo = ui.tarjeta(html.Div(id="cp-modelo", **{"aria-live": "polite"}), titulo="El modelo",
                        subtitulo=("Lo que más pesa en el pronóstico, cómo le va con lo que ya se leyó y quién lo "
                                   "activó."), fuentes=FUENTES_MODELO)
    como = ui.desplegable("Cómo se lee esta parte", [
        ui.parrafo("En cada instante (cada media hora, de 04:00 a 21:00) el modelo pronostica las subidas de la ventana que "
                   "empieza en ese instante y dura el horizonte. Usa solo lo que pasó antes: lo que subió en los últimos "
                   "minutos y horas, lo acumulado del día frente a lo habitual, las salidas ya despachadas, las mismas "
                   "ventanas de las semanas anteriores y el calendario."),
        ui.parrafo("Hay un modelo por nivel, horizonte y ruta (LightGBM de Poisson). El de cada segmento de 500 m usa "
                   "también lo que subió en los segmentos vecinos; el de cada sentido es la suma de sus segmentos. La "
                   "banda P10–P90 es conformal, ajustada en la validación."),
        ui.parrafo("Las líneas base son las de la especificación: el promedio de la misma ventana en las ocho semanas "
                   "anteriores (mismo día y hora) y la última semana. Lo real está en los datos porque la fecha es "
                   "histórica: se muestra para comparar y el pronóstico no lo usa."),
        ui.parrafo("Las fechas son las de la prueba reservada: el modelo no las vio al entrenar ni al elegirse. La "
                   "recomendación lleva el pronóstico a ritmo por hora y usa el mismo optimizador del resto de la API."),
        ui.fuentes(FUENTES_API + ["datos/corto_plazo.json"]),
    ])
    return ui.seccion("Lo que pide el enunciado: 30, 60 y 120 minutos", [
        html.Div(id="cp-aviso", **{"aria-live": "polite"}),
        html.Div(id="cp-cifras"),
        ui.rejilla([dia, porque], "2-1"),
        ui.rejilla([segmentos, sentidos], "2-1"),
        modelo,
        _prueba(),
        como,
    ], subtitulo=("Con lo que ya subió hoy, cuántos pasajeros subirán en los próximos 30, 60 y 120 minutos, por ruta, "
                  "sentido y segmento. Es el modelo que sirve la API, medido una sola vez en la prueba de julio a "
                  "diciembre de 2025."), controles=controles, id="cp")


# --- datos y figuras ----------------------------------------------------------------------------------------------------
def _hhmm(iso):
    return f"{pd.Timestamp(iso):%H:%M}"


def _wape(pares):
    reales = sum(r for r, _p in pares)
    return sum(abs(p - r) for r, p in pares) / reales * 100 if reales else None


def _figura_dia(d, r, h):
    puntos = d["instantes"]
    x = [_hhmm(p["instante"]) for p in puntos]
    p50 = [p["pasajeros"] for p in puntos]
    fig = go.Figure()
    ui.banda(fig, x, [p["p10"] for p in puntos], [p["p90"] for p in puntos], "modelo")
    prom = [p["promedio_dia_hora"] for p in puntos]
    fig.add_trace(go.Scatter(x=x, y=prom, name="Promedio por día y hora", **ui.traza("hoy", "punteada"),
                             **ui.hover("Promedio por día y hora", prom, "subidas")))
    fig.add_trace(go.Scatter(x=x, y=p50, name="Pronóstico", **ui.traza("modelo", "linea"),
                             **ui.hover_texto([f"Pronóstico: <b>{num(m)}</b> subidas · banda {num(p['p10'])} a "
                                               f"{num(p['p90'])}" for m, p in zip(p50, puntos)])))
    reales = [p["real"] for p in puntos]
    hay_real = d["dia_con_datos"] and any(v is not None for v in reales)
    if hay_real:
        fig.add_trace(go.Scatter(x=x, y=reales, name="Real", **ui.traza("real", "gruesa"), **ui.hover("Real", reales, "subidas"),
                                 zorder=1))
    ui.referencia(fig, x=_hhmm(r["instante"]))
    fig.update_xaxes(tickvals=x[::4])
    fig.update_yaxes(rangemode="tozero", nticks=5)
    fig.update_layout(hovermode="x unified")
    ui.unidad_eje(fig, f"subidas en los {h} minutos siguientes")
    leyenda = ([("Real", "real", "gruesa")] if hay_real else []) + [
        ("Pronóstico", "modelo", "linea"), ("Banda P10–P90", "modelo", "area"), ("Promedio por día y hora", "hoy", "punteada")]
    fecha = ui.fecha_larga(d["fecha"])
    if hay_real:
        con = [(p["real"], p["pasajeros"], p["promedio_dia_hora"]) for p in puntos if p["real"] is not None
               and p["promedio_dia_hora"] is not None]
        e_m, e_b = _wape([(a, b) for a, b, _c in con]), _wape([(a, c) for a, _b, c in con])
        titulo = (f"{d['ruta']}, {fecha}: en las ventanas del día el modelo se equivoca en {num(e_m, 1)} % y el "
                  f"promedio por día y hora en {num(e_b, 1)} %")
    else:
        titulo = f"{d['ruta']}, {fecha}: el pronóstico de cada media hora (lo real no está en los datos ese día)"
    sub = (f"Subidas de los {h} minutos que empiezan a la hora del eje, en toda la ruta: el pronóstico con su banda, la "
           f"línea base y lo real. La línea vertical marca las {_hhmm(r['instante'])}.")
    filas = [[t, num(p["p10"]), num(p["pasajeros"]), num(p["p90"]), num(p["promedio_dia_hora"]),
              num(p["real"]) if p["real"] is not None else "—"] for t, p in zip(x, puntos)]
    tabla = ui.tabla(["Instante", "P10", "Pronóstico", "P90", "Promedio", "Real"], filas, compacta=True)
    etiqueta = f"{titulo}. " + "; ".join(f"{t}: {num(m)}" for t, m in zip(x, p50))
    return fig, titulo, sub, ui.leyenda(leyenda, ordenar=False), tabla, etiqueta[:1200], None


def _figura_segmentos(r, h):
    segs = r["segmentos"]
    x = [s["km_inicio"] for s in segs]
    p50 = [s["pasajeros"] for s in segs]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=p50, name="Pronóstico", **ui.traza("modelo", "barra", ancho=0.4),
                         **ui.hover_texto([f"Segmento {num(s['nro_segmento'])} ({s['sentido']}, km {num(s['km_inicio'], 1)}): "
                                           f"<b>{num(s['pasajeros'], 1)}</b> subidas · banda {num(s['p10'], 1)} a "
                                           f"{num(s['p90'], 1)}" for s in segs])))
    reales = [s["real"] for s in segs]
    hay_real = r["dia_con_datos"] and any(v is not None for v in reales)
    if hay_real:
        fig.add_trace(go.Scatter(x=x, y=reales, name="Real", **ui.traza("real", "punto"),
                                 **ui.hover("Real", reales, "subidas", 1)))
    regreso = next((s["km_inicio"] for s in segs if s["sentido"] == "regreso"), None)
    if regreso is not None:
        ui.referencia(fig, x=regreso)
    fig.update_yaxes(rangemode="tozero", nticks=5)
    fig.update_xaxes(ticksuffix=" km")
    ui.unidad_eje(fig, f"subidas en los {h} minutos siguientes, por segmento de 500 m")
    mayor = max(segs, key=lambda s: s["pasajeros"] or 0)
    titulo = (f"A lo largo de la ruta: el segmento {num(mayor['nro_segmento'])} (km {num(mayor['km_inicio'], 1)}, "
              f"{mayor['sentido']}) es el de más subidas previstas, {num(mayor['pasajeros'], 1)}")
    sub = (f"Subidas previstas en cada segmento de 500 m en los {h} minutos desde las {_hhmm(r['instante'])}, en el orden del "
           "recorrido" + (", y lo real" if hay_real else "") + ". La línea vertical marca dónde empieza el regreso.")
    filas = [[num(s["nro_segmento"]), s["sentido"], num(s["km_inicio"], 1), num(s["p10"], 1), num(s["pasajeros"], 1),
              num(s["p90"], 1), num(s["real"]) if s["real"] is not None else "—"] for s in segs]
    tabla = ui.tabla(["Segmento", "Sentido", "Km", "P10", "Pronóstico", "P90", "Real"], filas, compacta=True,
                     num=[True, False, True, True, True, True, True])
    leyenda = ([("Real", "real", "punto")] if hay_real else []) + [("Pronóstico", "modelo", "barra")]
    etiqueta = f"{titulo}. " + "; ".join(f"segmento {num(s['nro_segmento'])}: {num(s['pasajeros'], 1)}" for s in segs[:40])
    return fig, titulo, sub, ui.leyenda(leyenda, ordenar=False), tabla, etiqueta[:1200], None


def _cifras(r, h):
    real = r.get("real")
    fichas = [
        ui.cifra(f"Subirán en los próximos {h} min", num(r["pasajeros"]), "subidas", mini=True,
                 variacion=f"Banda P10–P90: {num(r['p10'])} a {num(r['p90'])}",
                 nota=f"Desde las {_hhmm(r['instante'])} en toda la ruta ({r.get('franja') or '—'})."),
        ui.cifra("Promedio por día y hora", num(r.get("promedio_dia_hora")), "subidas", mini=True,
                 variacion=(f"La última semana: {num(r.get('ultima_semana'))}" if r.get("ultima_semana") is not None
                            else None),
                 nota="Las líneas base de la especificación (§9.1)."),
    ]
    if real is not None and r.get("dia_con_datos"):
        e_m = abs(r["pasajeros"] - real) / real * 100 if real else None
        e_b = abs(r["promedio_dia_hora"] - real) / real * 100 if real and r.get("promedio_dia_hora") is not None else None
        fichas.append(ui.cifra("Lo que pasó", num(real), "subidas", mini=True,
                               variacion=(f"Error del modelo {num(e_m, 1)} %; del promedio {num(e_b, 1)} %"
                                          if e_m is not None and e_b is not None else None),
                               nota="Para comparar: el pronóstico no lo usa."))
    else:
        fichas.append(ui.cifra("Lo que pasó", "—", None, mini=True, nota="Ese día no trae eventos de conteo."))
    rec = r.get("recomendacion") or {}
    if rec.get("viable"):
        fichas.append(ui.cifra("Con este pronóstico", num(rec.get("buses_hora")), "buses por hora", mini=True,
                               variacion=(f"Cada {num(rec.get('headway_min'), 1)} min · "
                                          f"{num(rec.get('vehiculos_requeridos'))} vehículos"),
                               nota=f"Recomendación de §10.2 para la hora de las {num(rec.get('hora'))}."))
    elif rec:
        motivo = str(rec.get("motivo") or "")
        fichas.append(ui.cifra("Con este pronóstico", "No viable", None, mini=True,
                               variacion=f"Para la hora de las {num(rec.get('hora'))}",
                               nota=(motivo.split(". ")[0].rstrip(".") + ".") if motivo else None))
    return ui.cifras(fichas)


def _porque(r):
    exp = r.get("explicacion") or {}
    filas = []
    for i, f in enumerate((exp.get("factores") or [])[:FACTORES], 1):
        desc = f.get("descripcion") or f.get("variable")
        filas.append([num(i), html.Span([html.Span(desc[0].upper() + desc[1:]), html.Br(),
                                         html.Span(f"{f['variable']} = {num(f.get('valor'), 1)}", className="api-tenue")]),
                      f"× {num(f.get('factor'), 3)}", f.get("sentido")])
    return html.Div([
        html.H4(f"Base del modelo {num(exp.get('valor_base'))} → pronóstico {num(r['pasajeros'])} subidas",
                className="api-grupo__titulo"),
        ui.tabla(["#", "Variable", "Factor", "Efecto"], filas, compacta=True, num=[True, False, True, False]),
        ui.nota("Contribuciones exactas de los árboles (TreeSHAP de LightGBM): el pronóstico es la base multiplicada por el "
                "factor de cada variable."),
        html.P([ui.chip_valor("Modelo:", r["model_id"]), " ", ui.chip_valor("Datos de entrenamiento hasta:", r["data_cutoff"])],
               className="api-chips"),
    ], className="api-resumen")


def _sentidos(r):
    con_real = r.get("dia_con_datos")
    fichas = []
    for s in r["sentidos"]:
        real = f" · real {num(s['real'])}" if s["real"] is not None and con_real else ""
        fichas.append(ui.cifra(s["sentido"].capitalize(), num(s["pasajeros"]), "subidas", mini=True,
                               variacion=f"Banda P10–P90: {num(s['p10'])} a {num(s['p90'])}",
                               nota=f"Promedio por día y hora: {num(s['promedio_dia_hora'])}{real}."))
    tabla = ui.cifras(fichas)
    obs = r.get("observado") or {}
    chips = html.Div([ui.chip_valor("Últimos 15 min:", num(obs.get("ultimos_15_min"))),
                      ui.chip_valor("Últimos 60 min:", num(obs.get("ultimos_60_min"))),
                      ui.chip_valor("Acumulado hoy:", num(obs.get("acumulado_hoy"))),
                      ui.chip_valor("Lo habitual a esta hora:", num(obs.get("habitual_acumulado")))], className="api-chips")
    return html.Div([tabla,
                     ui.nota("El sentido se aproxima por la mitad del ciclo de la ruta (supuesto S9): los datos no lo traen."),
                     html.H4(f"Lo que ya subió en toda la ruta hasta las {_hhmm(r['instante'])}",
                             className="api-grupo__titulo"),
                     chips], className="api-resumen")


def _modelo(ficha, monitoreo, h):
    """La importancia global (ganancia de LightGBM a nivel de ruta, para el horizonte elegido), el último monitoreo del
    corto plazo y el ciclo de vida (el activo del registro de modelos y su historial)."""
    imp = (((ficha.get("importancia_global") or {}).get("por_nivel") or {}).get("ruta") or {}).get(str(h)) or []
    filas = [[num(i), html.Span([html.Span(x["descripcion"][0].upper() + x["descripcion"][1:]), html.Br(),
                                  html.Span(x["variable"], className="api-tenue")]), f"{num(100 * x['ganancia'], 1)} %"]
             for i, x in enumerate(imp[:VARIABLES_IMPORTANCIA], 1)]
    partes = [html.H4(f"Lo que más pesa a {h} minutos (toda la ruta)", className="api-grupo__titulo"),
              ui.tabla(["#", "Variable", "Peso"], filas, compacta=True, num=[True, False, True]) if filas else
              ui.nota("Sin importancia publicada."),
              ui.nota("Ganancia de LightGBM de cada variable, normalizada y promediada en las tres rutas.")]
    mon = ((monitoreo or {}).get("items") or [None])[0]
    if mon:
        partes += [html.H4(f"Cómo le va: los {num(mon.get('ventana_dias'))} días hasta el {ui.fecha_larga(mon.get('hasta'))}",
                           className="api-grupo__titulo"),
                   html.Div([ui.chip_valor("Estado:", mon.get("estado") or "—"),
                             ui.chip_valor("WAPE móvil:", f"{num(100 * (mon.get('wape_movil') or 0), 1)} %"),
                             ui.chip_valor("Cobertura P10–P90:", f"{num(100 * (mon.get('cobertura_p10_p90') or 0), 1)} %"),
                             ui.chip_valor("PSI máximo:", f"{num(mon.get('psi_max'), 3)} ({mon.get('psi_variable_max') or '—'})"),
                             ui.chip_valor("Pronósticos guardados:", num(mon.get("predicciones_ventana")))],
                            className="api-chips")]
    else:
        partes.append(ui.nota("Todavía no hay monitoreo del corto plazo: lo deja cada ciclo diario con datos nuevos."))
    hist = ficha.get("historial_activacion") or []
    ultimo = hist[-1] if hist else {}
    partes += [html.H4("Quién lo activó", className="api-grupo__titulo"),
               html.P([ui.chip_valor("Activo:", ficha.get("activo") or "—"),
                       ui.chip_valor("Motor:", ficha.get("motor") or "—"),
                       ui.chip_valor("Activado:", (ultimo.get("en") or "—")[:10]),
                       ui.chip_valor("Motivo:", ultimo.get("motivo") or "—")], className="api-chips"),
               ui.nota("Se activa y se revierte con la misma compuerta de cuatro criterios del modelo horario "
                       "(POST /api/v1/models/{model_id}/activate y /models/rollback con familia=corto_plazo).")]
    return html.Div(partes, className="api-resumen")


def _aviso_calidad(r):
    c = r.get("calidad") or {}
    celdas = c.get("celdas_excluidas") or []
    if not celdas:
        return None
    textos = [f"{ui.fecha_larga(x['fecha'])}, segmento {num(x['nro_segmento'])}: {num(x['subidas'])} subidas en 15 minutos"
              for x in celdas[:3]]
    return ui.aviso(f"La regla de calidad VAL-009 excluyó {num(len(celdas))} celda(s) imposible(s) de lo que usa este "
                    f"pronóstico ({'; '.join(textos)}): cuentan como no observadas.", None, "Datos excluidos",
                    rol="status")


SIN = (ui.figura_vacia("Sin pronóstico"), "Sin pronóstico", "", None, None, "Sin pronóstico", None)


@callback(Output("cp-fecha", "date"), Output("cp-aviso", "children"), Output("cp-cifras", "children"),
          Output("cp-dia", "figure"), Output("cp-dia-titulo", "children"), Output("cp-dia-sub", "children"),
          Output("cp-dia-leyenda", "children"), Output("cp-dia-tabla", "children"), Output("cp-dia-lienzo", "aria-label"),
          Output("cp-dia-nota", "children"),
          Output("cp-seg", "figure"), Output("cp-seg-titulo", "children"), Output("cp-seg-sub", "children"),
          Output("cp-seg-leyenda", "children"), Output("cp-seg-tabla", "children"), Output("cp-seg-lienzo", "aria-label"),
          Output("cp-seg-nota", "children"), Output("cp-porque", "children"), Output("cp-sentidos", "children"),
          Output("cp-modelo", "children"),
          Input("cp-ruta", "value"), Input("cp-fecha", "date"), Input("cp-hora", "value"), Input("cp-h", "value"),
          Input("cp-fecha-ant", "n_clicks"), Input("cp-fecha-sig", "n_clicks"))
def actualizar(ruta, fecha, hora, h, _ant, _sig):
    ruta = ruta if ruta in RUTAS else "CRA 54"
    h = h if h in HORIZONTES else 60
    hora = hora if hora in HORAS else HORA_INICIAL
    ini, fin = _periodo()
    fecha = str(fecha or _fecha_inicial())[:10]
    salida_fecha = no_update
    if ctx.triggered_id in ("cp-fecha-ant", "cp-fecha-sig"):
        paso = -1 if ctx.triggered_id == "cp-fecha-ant" else 1
        nueva = pd.Timestamp(fecha) + pd.Timedelta(days=paso)
        if ini and fin:
            nueva = min(max(nueva, pd.Timestamp(ini)), pd.Timestamp(fin))
        fecha = salida_fecha = nueva.strftime("%Y-%m-%d")

    def vacio(aviso):
        nada = ui.nota("Sin datos: la API no está disponible.")
        return (salida_fecha, aviso, None, *SIN, *SIN, nada, nada, nada)

    instante = f"{fecha}T{hora}:00-05:00"
    r, err = API.obtener("predictions/corto-plazo/calcular", ruta=ruta, instante=instante, horizonte_min=h)
    if err:
        return vacio(ui.aviso([err, API.ayuda_error(err)], "atencion", API.titulo_error(err), rol="status"))
    d, err = API.obtener("predictions/corto-plazo/dia", ruta=ruta, fecha=fecha, horizonte_min=h)
    if err:
        return vacio(ui.aviso([err, API.ayuda_error(err)], "atencion", API.titulo_error(err), rol="status"))
    ficha, _e1 = API.obtener("predictions/corto-plazo/modelo")
    monitoreo, _e2 = API.obtener("monitoring", familia="corto_plazo", limite=1, orden="-creado_en")
    aviso = _aviso_calidad(r)          # la regla de calidad primero: cambia lo que usa el pronóstico
    if aviso is None and not r.get("dia_con_datos"):
        aviso = ui.aviso(f"El {ui.fecha_larga(fecha)} no trae eventos de conteo de {ruta}: el pronóstico sale, pero no hay "
                         "con qué compararlo.", None, "Día sin datos", rol="status")
    elif aviso is None and r.get("en_muestra"):
        aviso = ui.aviso("Esa fecha está dentro del periodo de entrenamiento del modelo.", None, "Dentro de la muestra",
                         rol="status")
    return (salida_fecha, aviso, _cifras(r, h), *_figura_dia(d, r, h), *_figura_segmentos(r, h), _porque(r),
            _sentidos(r), _modelo(ficha or {}, monitoreo, h))

