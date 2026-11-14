"""Alertas: ¿Qué pide atención ahora? La bandeja de alertas de la API del reto (§3.1 «Consulta y tablero», RF-010, RF-011,
RF-015 a RF-017, E06), con el estilo de DISENO.md.

- Lista paginada con filtros por estado, nivel, ruta, código y fechas (GET /api/v1/alerts), ordenada por prioridad
  (crítica → preventiva → informativa y, dentro de cada nivel, la más reciente primero: orden=prioridad de la API) y con
  el chip «Escalada» cuando la bitácora registra que la alerta subió de nivel al redetectarse (acción «escalar», §7.2).
- Detalle con todos los campos de §5.3 (GET /api/v1/alerts/{id}) y su bitácora (GET /api/v1/alerts/{id}/history):
  origen, tendencia con su pendiente, la serie reciente en un gráfico pequeño (con su tabla gemela en el «…»),
  probabilidad y método del puntaje (§9.4: nunca opaca), las variables influyentes (SHAP del modelo) ordenadas por su
  efecto y la ubicación (coordenadas y enlace al mapa) cuando la fuente la trae.
- Acciones reconocer, asignar, comentar, cerrar y descartar (PATCH /api/v1/alerts/{id}/status) con el usuario de la
  clave configurada (cliente_api: SOBUSA_API_KEY y SOBUSA_USUARIO). Los botones siguen las transiciones de la API; si
  otra persona cambió la alerta antes, la API responde 409 y el aviso lo dice.
- Exportación CSV y XLSX con los mismos filtros (GET /api/v1/alerts/export), descargada a través del servidor del Dash
  para que la clave nunca llegue al navegador.

Sin API, la pantalla muestra «La API no responde en …» y no inventa nada. Todas las cifras salen de la API."""
import dash
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

import cliente_api as A
import ui

dash.register_page(__name__, path="/alertas", name="Alertas", order=6, title="Alertas · Sobusa Despacho")

POR_PAGINA = 20
ESTADOS = [("Todas", "todas"), ("Nueva", "nueva"), ("Reconocida", "reconocida"), ("Asignada", "asignada"),
           ("Cerrada", "cerrada"), ("Descartada", "descartada")]
NIVELES = [("Todos", "todas"), ("Crítica", "critica"), ("Preventiva", "preventiva"), ("Informativa", "informativa")]
RUTAS = [("Todas", "todas"), ("SILENCIO", "SILENCIO"), ("CRA 54", "CRA 54"), ("CL 72", "CL 72")]
CODIGOS = [f"ALT-{i:03d}" for i in range(1, 11)]
# Estado y nivel: siempre icono y palabra (DISENO.md §6)
NIVEL = {"critica": ("Crítica", "critico", None), "preventiva": ("Preventiva", "atencion", None),
         "informativa": ("Informativa", None, "info")}
ESTADO = {"nueva": ("Nueva", None, "alerta"), "reconocida": ("Reconocida", None, "info"),
          "asignada": ("Asignada", None, "equipo"), "cerrada": ("Cerrada", "bien", None),
          "descartada": ("Descartada", None, "cerrar")}
ACCIONES = [("reconocer", "Reconocer", "bien"), ("asignar", "Asignar", "equipo"), ("comentar", "Comentar", "mas"),
            ("cerrar", "Cerrar", "cerrar"), ("descartar", "Descartar", "cerrar")]
# Las mismas transiciones de la API (app/servicios/alertas.py): comentar se permite en cualquier estado abierto
TRANSICIONES = {"nueva": {"reconocer", "descartar"}, "reconocida": {"asignar", "descartar"},
                "asignada": {"asignar", "cerrar", "descartar"}, "cerrada": set(), "descartada": set()}
FINALES = {"cerrada", "descartada"}
NOMBRE_ACCION = {"crear": "Creada", "reconocer": "Reconocida", "asignar": "Asignada", "comentar": "Comentario",
                 "cerrar": "Cerrada", "descartar": "Descartada", "escalar": "Escalada (subió de nivel)",
                 "redeteccion": "Redetectada (el episodio sigue)"}
# Prioridad de la bandeja (§3.1 «priorizar»): primero las críticas, después las preventivas y las informativas; dentro de
# cada nivel, la más reciente primero. La API la ordena con orden=prioridad; si una versión anterior no lo admite
# (422 orden_invalido), el tablero ordena las más recientes de esos filtros (hasta TOPE_LOCAL) con la misma regla.
ORDEN_PRIORIDAD = "prioridad"
RANGO_NIVEL = {"critica": 0, "preventiva": 1, "informativa": 2}
TOPE_LOCAL = 500
NO_APLICA = "— no aplica en el nivel ruta-hora"
# §5.3: un viaje, un vehículo o un conductor vacío no siempre es «no aplica». Cada alerta dice en
# variables.identificacion_5_3 a qué campos aplica su regla y qué encontró (resultado); si el campo aplica y quedó vacío,
# el detalle dice ese motivo (ALT-006 y ALT-009 sin viajes en la fuente, por ejemplo).
SIN_IDENTIFICAR = {
    "fuente_sin_viajes": "— sin identificar: la fuente de datos no expone los viajes",
    "fuente_sin_viajes_del_dia": "— sin identificar: la fuente no trae viajes de la ruta en ese día",
    "sin_viaje_cancelado_ni_tardio": "— sin identificar: ningún despacho de la ventana está cancelado ni tardío",
    "sin_viajes_incompletos": "— sin identificar: ningún viaje del día tiene datos faltantes",
    "segmento_sin_viaje": "— sin identificar: el segmento crítico no tiene un viaje medido",
    "solo_frescura": "— no aplica: la alerta es por la frescura de los datos, no por un viaje",
}
FUENTES = ["GET /api/v1/alerts", "GET /api/v1/alerts/{id}", "GET /api/v1/alerts/{id}/history"]
# §5.3: de dónde sale la alerta y hacia dónde va su serie (§9.4); la tendencia no es un estado: icono y palabra, sin color
ORIGEN = {"pronostico": "Pronóstico (antes de que pase)", "observado": "Observado (lo que ya pasó)",
          "calidad_datos": "Calidad de los datos", "modelo": "Desempeño del modelo"}
TENDENCIA = {"al_alza": ("Al alza", "flecha-arriba"), "a_la_baja": ("A la baja", "flecha-abajo"),
             "estable": ("Estable", "igual"), "sin_datos": ("Sin datos para la tendencia", "info")}
FUENTE_VARIABLE = {"shap_modelo": "SHAP del modelo", "importancia_global": "importancia global del modelo",
                   "regla": "dato de la regla"}
MAX_INFLUYENTES = 5
ZOOM_MAPA = 16          # acercamiento del enlace a OpenStreetMap (calle)


# --- Formato ----------------------------------------------------------------------------------------------------------
def hora_local(x):
    """Instante de la API en la hora de Bogotá (la auditoría viene en UTC)."""
    t = pd.Timestamp(x)
    return t.tz_convert("America/Bogota") if t.tzinfo is not None else t


def fecha_hora(x):
    """«9 nov 2026 · 00:32» en la hora de Bogotá (la API ya responde con -05:00)."""
    if not x:
        return "—"
    t = hora_local(x)
    return f"{ui.fecha_corta(t)} {t.year} · {t:%H:%M}"


def fecha_hora_corta(x):
    """«9 nov · 00:32» para la columna de la lista (el año va en el detalle)."""
    if not x:
        return "—"
    t = hora_local(x)
    return f"{ui.fecha_corta(t)} · {t:%H:%M}"


def valor(x):
    """Cifra de la evidencia: enteros sin decimales; dos decimales si es una fracción o un puntaje, uno si es un conteo."""
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "sí" if x else "no"
    if isinstance(x, int) or (isinstance(x, float) and x.is_integer() and abs(x) >= 10):
        return ui.num(x)
    if isinstance(x, float):
        return ui.num(x, 2 if abs(x) < 10 else 1)
    return str(x)


def chip_nivel(sev):
    texto, tipo, icono = NIVEL.get(sev, (sev or "—", None, "info"))
    return ui.chip(texto, tipo, icono)


def chip_estado(est):
    texto, tipo, icono = ESTADO.get(est, (est or "—", None, "info"))
    return ui.chip(texto, tipo, icono)


def cabecera(titulo, subtitulo):
    """La cabecera de ui.cabecera con el icono de la pantalla (el cuadro sale de --pantalla-alertas)."""
    return html.Header(html.Div([ui.cuadro("alertas", "alerta", "cuadro-color--cabecera"),
                                 html.H1(titulo, className="cabecera__pregunta"),
                                 html.P(subtitulo, className="cabecera__subtitulo")], className="cabecera__texto"),
                       className="cabecera")


def aviso_api(err):
    """Aviso de la API caída o de la clave sin validez (401) o sin rol (403): título y qué hacer, nunca una traza."""
    return ui.aviso([err, A.ayuda_error(err)], "atencion", A.titulo_error(err), rol="status")


def chip_salud():
    d, err = A.salud()
    if err or not d:
        return ui.chip("API sin respuesta", "critico")
    if d.get("estado") == "ok":
        return ui.chip(f"API en línea · versión {d.get('version', '—')}", "bien")
    return ui.chip(f"API degradada · base {d.get('base_datos', '—')}", "atencion")


def campo(id_, rotulo, placeholder, tipo="text"):
    return html.Div([html.Label(rotulo, htmlFor=id_, className="campo__rotulo"),
                     dcc.Input(id=id_, type=tipo, placeholder=placeholder, className="campo", debounce=False,
                               autoComplete="off")], className="campo-bloque")


# --- Pantalla ---------------------------------------------------------------------------------------------------------
def _opciones(pares):
    return [{"label": a, "value": b} for a, b in pares]


def layout(**_):
    filtros = [
        ui.control("Estado", ui.segmentado("al-estado", _opciones(ESTADOS), "nueva", persistir=False)),
        ui.control("Nivel", ui.segmentado("al-nivel", _opciones(NIVELES), "todas", persistir=False)),
        ui.control("Ruta", ui.segmentado("al-ruta", _opciones(RUTAS), "todas", persistir=False)),
    ]
    mas_filtros = [
        ui.control("Código", dcc.Dropdown(id="al-codigo", options=CODIGOS, value=None, placeholder="Todos", clearable=True,
                                          searchable=False, className="desplegable-api")),
        ui.control("Desde", dcc.DatePickerSingle(id="al-desde", date=None, display_format="DD/MM/YYYY", month_format="MM/YYYY",
                                                 first_day_of_week=1, clearable=True, placeholder="dd/mm/aaaa", className="fecha")),
        ui.control("Hasta", dcc.DatePickerSingle(id="al-hasta", date=None, display_format="DD/MM/YYYY", month_format="MM/YYYY",
                                                 first_day_of_week=1, clearable=True, placeholder="dd/mm/aaaa", className="fecha")),
        html.Div([ui.boton("Exportar CSV", id="al-csv", icono="descargar", pequeno=True),
                  ui.boton("Exportar XLSX", id="al-xlsx", icono="descargar", pequeno=True)], className="botonera"),
    ]
    usuario = [ui.chip_valor("Usuario:", A.USUARIO),
               ui.nota("La API registra la acción con la clave configurada (SOBUSA_API_KEY)." if A.con_clave() else
                       "Sin clave configurada: la API corre sin autenticación y registra el usuario del tablero.")]
    acciones = html.Div([
        html.H4("Acciones", className="api-grupo__titulo"),
        html.Div(usuario, className="api-usuario"),
        campo("al-asignado", "Asignar a", "Persona o equipo"),
        campo("al-comentario", "Comentario", "Qué se hizo o por qué"),
        html.Div([ui.boton(t, id=f"al-{a}", icono=i, tipo="primario" if a == "reconocer" else "secundario", pequeno=True)
                  for a, t, i in ACCIONES], className="botonera", role="group", **{"aria-label": "Acciones sobre la alerta"}),
        html.Div(id="al-resultado", **{"aria-live": "polite"}),
    ], className="api-acciones")
    return ui.pantalla([
        dcc.Store(id="al-pagina", data=0),
        dcc.Store(id="al-total", data=0),
        dcc.Store(id="al-sel", data=None),
        dcc.Store(id="al-refresco", data=0),
        dcc.Download(id="al-descarga"),
        ui.arriba(cabecera("Alertas", "Lo que pide atención, con su evidencia, las acciones del despacho y su bitácora."),
                  filtros, html.Div([html.Div(id="al-salud"), html.Div(id="al-aviso-api")], className="api-respuesta")),
        ui.seccion("Bandeja de alertas", [
            ui.fila_controles(mas_filtros),
            html.Div(id="al-export-aviso", **{"aria-live": "polite"}),
            ui.rejilla([
                ui.tarjeta([html.Div(id="al-lista"),
                            html.Div([ui.boton("Anterior", id="al-ant", icono="chevron-izquierda", pequeno=True),
                                      html.Span(id="al-paginas", className="api-paginas"),
                                      ui.boton("Siguiente", id="al-sig", icono="chevron-derecha", pequeno=True)],
                                     className="api-paginacion")],
                           titulo="Alertas", subtitulo="Elija una alerta para ver su detalle y actuar.", fuentes=FUENTES[:1]),
                ui.tarjeta([html.Div(id="al-detalle"), acciones, html.Div(id="al-campos")], titulo="Detalle",
                           subtitulo="Todos los campos de la alerta (§5.3).", fuentes=FUENTES[1:2], id="al-tarjeta-detalle"),
            ], "2-1"),
        ], subtitulo=f"Ordenadas por prioridad: primero las críticas, después las preventivas y las informativas; dentro de "
                     f"cada nivel, de la más reciente a la más antigua. {ui.num(POR_PAGINA)} por página.", id="al-bandeja"),
        ui.seccion("Bitácora de la alerta", ui.tarjeta(html.Div(id="al-historial")),
                   subtitulo="Quién hizo qué y cuándo, con el estado anterior y el nuevo.", fuentes=FUENTES[2:]),
    ], "pantalla--api")


# --- Lista ------------------------------------------------------------------------------------------------------------
def _filtros(estado, nivel, ruta, codigo, desde, hasta):
    return {"estado": estado, "severidad": nivel, "ruta": ruta, "codigo": codigo, "desde": desde, "hasta": hasta}


FILTROS = [Input("al-estado", "value"), Input("al-nivel", "value"), Input("al-ruta", "value"), Input("al-codigo", "value"),
           Input("al-desde", "date"), Input("al-hasta", "date")]
IDS_FILTROS = {"al-estado", "al-nivel", "al-ruta", "al-codigo", "al-desde", "al-hasta"}


def ordenar_prioridad(items):
    """Nivel (crítica → preventiva → informativa) y, dentro de cada nivel, la más reciente primero."""
    recientes = sorted(items, key=lambda a: str(a.get("detectada_en") or ""), reverse=True)
    return sorted(recientes, key=lambda a: RANGO_NIVEL.get(a.get("severidad"), len(RANGO_NIVEL)))


def pagina_por_prioridad(filtros, pagina):
    """Una página de la bandeja en orden de prioridad → (datos, error). Pide orden=prioridad a la API; si esa versión no lo
    admite (422 orden_invalido), trae las más recientes de esos filtros y las ordena aquí con la misma regla."""
    datos, err, codigo = A.obtener_con_codigo("alerts", **filtros, limite=POR_PAGINA, desplazamiento=pagina * POR_PAGINA,
                                              orden=ORDEN_PRIORIDAD)
    if codigo != "orden_invalido":
        return datos, err
    todo, err = A.obtener("alerts", **filtros, limite=TOPE_LOCAL, desplazamiento=0, orden="-detectada_en")
    if err:
        return None, err
    items = ordenar_prioridad(todo["items"])
    return {"total": todo["total"], "items": items[pagina * POR_PAGINA:(pagina + 1) * POR_PAGINA]}, None


def escalada(historia):
    """True si la bitácora tiene una entrada «escalar» (la redetección subió el nivel, §7.2)."""
    return any(isinstance(h, dict) and h.get("accion") == "escalar" for h in (historia or []))


def escaladas(items):
    """alert_id de las alertas de la página que subieron de nivel. Solo puede escalar una alerta redetectada (ocurrencias
    > 1), así que solo de esas se lee la bitácora."""
    out = set()
    for a in items:
        if (a.get("ocurrencias") or 0) > 1 or a.get("escalada"):
            h, err = A.obtener(f"alerts/{a['alert_id']}/history")
            if not err and escalada(h):
                out.add(a["alert_id"])
    return out


def chip_escalada():
    return ui.chip("Escalada", "atencion", "flecha-arriba")


@callback(Output("al-lista", "children"), Output("al-aviso-api", "children"), Output("al-salud", "children"),
          Output("al-paginas", "children"), Output("al-ant", "disabled"), Output("al-sig", "disabled"),
          Output("al-pagina", "data"), Output("al-sel", "data"),
          *FILTROS, Input("al-ant", "n_clicks"), Input("al-sig", "n_clicks"), Input("al-refresco", "data"),
          State("al-pagina", "data"), State("al-sel", "data"))
def listar(estado, nivel, ruta, codigo, desde, hasta, _ant, _sig, _refresco, pagina, sel):
    disparo = ctx.triggered_id
    pagina = pagina or 0
    if disparo in IDS_FILTROS:
        pagina = 0
    elif disparo == "al-ant":
        pagina = max(0, pagina - 1)
    elif disparo == "al-sig":
        pagina += 1
    datos, err = pagina_por_prioridad(_filtros(estado, nivel, ruta, codigo, desde, hasta), pagina)
    salud = chip_salud()
    if err:
        return (ui.nota("Sin datos: la API no está disponible."), aviso_api(err), salud, "", True, True, 0, None)
    total, items = datos["total"], datos["items"]
    paginas = max(1, -(-total // POR_PAGINA))
    if pagina >= paginas and total:
        pagina = paginas - 1
    if not items:
        return (ui.aviso("Ninguna alerta cumple estos filtros. Cambie el estado, el nivel, la ruta o las fechas.", None,
                         "Sin alertas", rol="status"), None, salud,
                f"{ui.num(total)} alertas", True, True, pagina, sel if disparo == "al-refresco" else None)
    ids = [a["alert_id"] for a in items]
    subieron = escaladas(items)
    filas = []
    for a in items:
        actual = a["alert_id"] == sel
        boton = html.Button(a["codigo"], id={"tipo": "al-fila", "id": a["alert_id"]}, type="button",
                            className="api-fila" + (" api-fila--activa" if actual else ""),
                            title=f"Ver el detalle de {a['codigo']}", **{"aria-pressed": "true" if actual else "false"})
        nivel_ = html.Span([chip_nivel(a["severidad"])] + ([chip_escalada()] if a["alert_id"] in subieron else []),
                           className="api-chips")
        filas.append([boton, nivel_, chip_estado(a["estado"]), html.Span(a.get("ruta") or "—", className="api-nowrap"),
                      html.Span(fecha_hora_corta(a["detectada_en"]), className="api-nowrap", title=fecha_hora(a["detectada_en"])),
                      valor(a.get("observado")), valor(a.get("esperado")),
                      ui.num(a.get("ocurrencias"))])
    tabla = ui.tabla(["Código", "Nivel", "Estado", "Ruta", "Detectada", "Observado", "Esperado", "Veces"], filas,
                     num=[False, False, False, False, False, True, True, True], compacta=True, ocultar_movil=(4, 6))
    texto = f"Página {ui.num(pagina + 1)} de {ui.num(paginas)} · {ui.num(total)} alertas con estos filtros"
    # Tras una acción, la alerta sigue elegida aunque ya no cumpla el filtro (p. ej. «Nueva» → reconocida); con otro
    # filtro u otra página se elige la primera de la lista.
    nuevo_sel = sel if (sel in ids or (disparo == "al-refresco" and sel)) else ids[0]
    return tabla, None, salud, texto, pagina == 0, pagina >= paginas - 1, pagina, nuevo_sel


@callback(Output("al-sel", "data", allow_duplicate=True), Input({"tipo": "al-fila", "id": ALL}, "n_clicks"),
          prevent_initial_call=True)
def elegir(clics):
    if not ctx.triggered_id or not any(clics or []):
        return no_update
    return ctx.triggered_id["id"]


# Resalta la fila elegida sin volver a pedir la lista
dash.clientside_callback(
    """function (sel) {
        document.querySelectorAll('.api-fila').forEach(function (b) {
            var mia = b.id && b.id.indexOf(sel) >= 0;
            b.classList.toggle('api-fila--activa', !!mia);
            b.setAttribute('aria-pressed', mia ? 'true' : 'false');
        });
        return window.dash_clientside.no_update;
    }""", Output("al-tarjeta-detalle", "className"), Input("al-sel", "data"), prevent_initial_call=True)


# --- Detalle ----------------------------------------------------------------------------------------------------------
def _par(rotulo, contenido):
    return html.Div([html.Dt(rotulo), html.Dd(contenido)], className="api-campos__fila")


def _grupo(titulo, pares):
    return html.Div([html.H4(titulo, className="api-grupo__titulo"), html.Dl([_par(r, c) for r, c in pares], className="api-campos")],
                    className="api-grupo")


def _o_no_aplica(x):
    return x if x not in (None, "") else NO_APLICA


def _campo_5_3(a, campo):
    """Un campo de identificación de §5.3. Si viene vacío y la regla de la alerta lo aplica (identificacion_5_3.aplica),
    dice el motivo real (identificacion_5_3.resultado); si la regla no lo aplica, «no aplica»."""
    x = a.get(campo)
    if x not in (None, ""):
        return x
    ident = (a.get("variables") or {}).get("identificacion_5_3") or {}
    if campo not in (ident.get("aplica") or []):
        return NO_APLICA
    resultado = ident.get("resultado") or "sin motivo declarado"
    return SIN_IDENTIFICAR.get(resultado, f"— sin identificar ({resultado})")


def _variables(v):
    if not v:
        return ui.nota("Sin variables.")
    filas = [[k, valor(x) if not isinstance(x, (dict, list)) else str(x)] for k, x in v.items()]
    return ui.tabla(["Variable", "Valor"], filas, compacta=True, num=[False, True])


def _comentarios(lista):
    if not lista:
        return "—"
    return html.Ul([html.Li([html.Span(f"{c.get('usuario', '—')} · {fecha_hora(c.get('en'))}: ", className="api-tenue"),
                             html.Span(c.get("comentario") or "")]) for c in lista], className="api-lista")


def _numero(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def chip_tendencia(a):
    """Tendencia de §9.4 con su icono y su palabra (no es un estado: sin color)."""
    texto, icono = TENDENCIA.get(a.get("tendencia"), (a.get("tendencia") or "Sin tendencia", "info"))
    return ui.chip(f"Tendencia: {texto.lower()}" if a.get("tendencia") in TENDENCIA else texto, None, icono)


def texto_pendiente(a):
    p = a.get("tendencia_pendiente")
    if not _numero(p):
        return "—"
    return f"{ui.con_signo(p * 100, 1)} % por paso de la serie (pendiente relativa de mínimos cuadrados)"


def _hora_corta(x):
    if not x:
        return "—"
    t = hora_local(x)
    return f"{ui.fecha_corta(t)} {t:%H:%M}"


def serie_alerta(a):
    """serie_reciente de la API → (categorías, [(nombre, rol, forma, valores, unidad, decimales)]). La forma depende del
    código: horas observadas (observado frente a esperado), horizontes del pronóstico (30, 60 y 120 min) o días del mismo
    tipo (subidas del día). None si la API no trae serie."""
    s = [p for p in (a.get("serie_reciente") or []) if p is not None]
    if not s:
        return None
    if all(_numero(p) for p in s):
        return [ui.num(i + 1) for i in range(len(s))], [("Valor de la serie", "real", "gruesa", s, "", 1)]
    s = [p for p in s if isinstance(p, dict)]
    if not s:
        return None
    if any("observado" in p or "esperado" in p for p in s):
        x = [_hora_corta(p.get("inicio")) for p in s]
        return x, [("Observado", "real", "gruesa", [p.get("observado") for p in s], "pasajeros", 0),
                   ("Esperado por el modelo", "modelo", "linea", [p.get("esperado") for p in s], "pasajeros", 0)]
    if any("pasajeros_por_hora" in p for p in s):
        x = [f"{ui.num(p.get('horizonte_min'))} min" for p in s]
        return x, [("Demanda prevista por hora", "modelo", "linea", [p.get("pasajeros_por_hora") for p in s], "pasajeros/h", 0)]
    if any("subidas" in p for p in s):
        x = [ui.fecha_corta(p["fecha"]) if p.get("fecha") else "—" for p in s]
        return x, [("Subidas del día", "real", "gruesa", [p.get("subidas") for p in s], "pasajeros", 0)]
    claves = [k for k, v in s[0].items() if _numero(v)]
    if not claves:
        return None
    return [ui.num(i + 1) for i in range(len(s))], [(claves[0], "real", "gruesa", [p.get(claves[0]) for p in s], "", 1)]


def grafico_serie(a):
    """La serie reciente en un gráfico pequeño (como un sparkline, con marcadores) y su tabla gemela en el «…»."""
    datos = serie_alerta(a)
    if datos is None:
        return ui.nota("La API no trae serie reciente para esta alerta.")
    x, series = datos
    fig = go.Figure()
    valores = []
    for nombre, rol, forma, ys, unidad, d in series:
        fig.add_trace(go.Scatter(x=x, y=ys, name=nombre, **ui.traza(rol, forma, marcadores=True), **ui.hover(nombre, ys, unidad, d)))
        valores += [v for v in ys if _numero(v)]
    tope = max(valores or [1])
    paso = ui.paso_redondo(tope, 3)
    vals, textos = ui.marcas(0, tope + paso * 0.25, paso)
    fig.update_layout(yaxis=dict(tickvals=vals, ticktext=textos, range=[0, max(vals[-1], tope * 1.08)]), hovermode="x unified")
    ui.unidad_eje(fig, series[0][4] or "valor")
    filas = [[x[i]] + [ui.num(ys[i], d) if i < len(ys) else "—" for _n, _r, _f, ys, _u, d in series] for i in range(len(x))]
    etiqueta = "; ".join(f"{nombre}: " + ", ".join(f"{x[i]} {ui.num(ys[i], d)}" for i in range(len(x)) if i < len(ys))
                         for nombre, _r, _f, ys, _u, d in series)
    leyenda = [(n, r, f) for n, r, f, _y, _u, _d in series] if len(series) > 1 else None
    return ui.grafico(fig, titulo="Serie reciente", subtitulo="Lo que analizó la regla, en orden; con ella se mide la tendencia.",
                      etiqueta=f"Serie reciente de la alerta. {etiqueta}", leyenda=leyenda, alto="bajo",
                      tabla=(["Punto"] + [n for n, *_ in series], filas), fuentes=["GET /api/v1/alerts/{id} · serie_reciente"])


def _influyentes(lista):
    """Las variables influyentes de §5.3, de la que más mueve el pronóstico a la que menos (SHAP del modelo; si falta, la
    importancia global). Las de la regla ya están en «Variables»: aquí solo se cuentan."""
    lista = [v for v in (lista or []) if isinstance(v, dict)]
    del_modelo = [v for v in lista if v.get("fuente") != "regla"]
    de_regla = [v for v in lista if v.get("fuente") == "regla"]
    if not del_modelo:
        texto = "La API no trae variables del modelo para esta alerta"
        return ui.nota(texto + (f"; los {ui.num(len(de_regla))} datos de la regla están en «Variables»." if de_regla else "."))

    def peso(v):
        for k in ("efecto_pasajeros", "importancia"):
            if _numero(v.get(k)):
                return abs(float(v[k]))
        return -1.0

    orden = sorted(del_modelo, key=peso, reverse=True)[:MAX_INFLUYENTES]
    filas = []
    for i, v in enumerate(orden, 1):
        rotulo = v.get("descripcion") or v.get("variable") or "—"
        detalle = " · ".join(x for x in (v.get("variable") if v.get("descripcion") else None,
                                         f"valor {valor(v.get('valor'))}" if _numero(v.get("valor")) else None) if x)
        nombre = html.Span([html.Span(rotulo)] + ([html.Br(), html.Span(detalle, className="api-tenue")] if detalle else []))
        if _numero(v.get("efecto_pasajeros")):
            efecto = [html.Span(f"{ui.con_signo(v['efecto_pasajeros'], 1)} pas.")]
            if _numero(v.get("factor")):
                efecto += [html.Br(), html.Span(f"× {ui.num(v['factor'], 3)}", className="api-tenue")]
        elif _numero(v.get("importancia")):
            efecto = f"importancia {ui.num(v['importancia'], 3)}"
        else:
            efecto = "—"
        filas.append([ui.num(i), nombre, efecto])
    fuentes = sorted({FUENTE_VARIABLE.get(v.get("fuente"), v.get("fuente") or "—") for v in orden})
    nota = ui.nota(f"Fuente: {', '.join(fuentes)}. Efecto: cuántos pasajeros suma o resta la variable al pronóstico de esa franja "
                   "(× el factor multiplicativo)." + (f" Además, {ui.num(len(de_regla))} datos de la regla (en «Variables»)."
                                                      if de_regla else ""))
    return [ui.tabla(["#", "Variable", "Efecto"], filas, compacta=True, num=[True, False, True]), nota]


def _ubicacion(u):
    """GeoJSON Point (lon, lat) de §8.1 → coordenadas y enlace al mapa; sin ubicación, lo dice."""
    coords = (u or {}).get("coordinates") if isinstance(u, dict) else None
    if not coords or len(coords) < 2 or not all(_numero(c) for c in coords[:2]):
        return "— la fuente no trae coordenadas para esta alerta"
    lon, lat = float(coords[0]), float(coords[1])
    enlace = f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map={ZOOM_MAPA}/{lat:.6f}/{lon:.6f}"
    return html.Span([f"latitud {ui.num(lat, 5)} · longitud {ui.num(lon, 5)} · ",
                      html.A(["Ver en el mapa", ui.icono("externo", "glifo--s")], href=enlace, target="_blank", rel="noopener")])


def campos(a):
    """Los campos de §5.3 agrupados: identificación, contexto, tiempo, evidencia (con probabilidad y método del puntaje),
    tendencia, variables influyentes, explicación y gestión."""
    puntaje = a.get("puntaje")
    prob = a.get("probabilidad")
    evidencia = [("Observado", valor(a.get("observado"))), ("Esperado", valor(a.get("esperado"))),
                 ("Umbral", valor(a.get("umbral"))),
                 ("Puntaje", ui.barra_rayas("Puntaje de la alerta", valor(puntaje), puntaje or 0, "modelo")
                  if puntaje is not None else "—"),
                 ("Probabilidad", ui.barra_rayas("Probabilidad del evento", f"{ui.num(prob * 100, 1)} %", prob, "modelo")
                  if _numero(prob) else "— no aplica a este código"),
                 ("Método del puntaje", a.get("metodo_puntaje") or "—")]
    return [
        _grupo("Identificación", [("alert_id", html.Code(a["alert_id"])), ("Código", a["codigo"]),
                                  ("Origen", ORIGEN.get(a.get("origen"), a.get("origen") or "—")),
                                  ("Clave de deduplicación", html.Code(a.get("clave_dedup") or "—")),
                                  ("Ocurrencias", ui.num(a.get("ocurrencias"))),
                                  ("execution_id", html.Code(a.get("execution_id") or "—"))]),
        _grupo("Contexto", [("Empresa", _o_no_aplica(a.get("empresa"))), ("Ruta", _o_no_aplica(a.get("ruta"))),
                            ("Sentido", _campo_5_3(a, "sentido")), ("Viaje", _campo_5_3(a, "viaje")),
                            ("Conductor (seudónimo)", _campo_5_3(a, "conductor")),
                            ("Vehículo", _campo_5_3(a, "vehiculo")), ("Ubicación", _ubicacion(a.get("ubicacion")))]),
        _grupo("Tiempo", [("Detectada", fecha_hora(a.get("detectada_en"))),
                          ("Ventana", f"{fecha_hora(a.get('ventana_inicio'))} → {fecha_hora(a.get('ventana_fin'))}"),
                          ("Horizonte", f"{ui.num(a.get('horizonte_min'))} min" if a.get("horizonte_min") is not None else "—"),
                          ("Última detección", fecha_hora(a.get("ultima_deteccion"))),
                          ("Actualizada", fecha_hora(a.get("actualizado_en")))]),
        _grupo("Evidencia", evidencia),
        html.Div([html.H4("Tendencia", className="api-grupo__titulo"),
                  html.Div([chip_tendencia(a)], className="api-chips"),
                  html.Dl([_par("Pendiente", texto_pendiente(a))], className="api-campos"),
                  grafico_serie(a)], className="api-grupo"),
        html.Div([html.H4("Variables influyentes", className="api-grupo__titulo"), html.Div(_influyentes(a.get("variables_influyentes")))],
                 className="api-grupo"),
        html.Div([html.H4("Variables", className="api-grupo__titulo"), _variables(a.get("variables"))], className="api-grupo"),
        _grupo("Gestión", [("Estado", chip_estado(a["estado"])), ("Nivel", chip_nivel(a["severidad"])),
                           ("Asignada a", a.get("asignado_a") or "—"), ("Comentarios", _comentarios(a.get("comentarios")))]),
    ]


def resumen(a, subio=False):
    return html.Div([
        html.Div([chip_nivel(a["severidad"])] + ([chip_escalada()] if subio else [])
                 + [chip_estado(a["estado"]), ui.chip_valor("Ruta:", a.get("ruta") or "—"), chip_tendencia(a)]
                 + ([ui.chip_valor("Probabilidad:", f"{ui.num(a['probabilidad'] * 100, 1)} %")]
                    if _numero(a.get("probabilidad")) else []),
                 className="api-chips"),
        html.P([html.Span("Origen: ", className="api-tenue"), ORIGEN.get(a.get("origen"), a.get("origen") or "—")],
               className="api-titular"),
        html.P([html.Span(a["codigo"], className="api-codigo"), " · ", fecha_hora(a.get("detectada_en"))], className="api-titular"),
        html.P(a.get("explicacion") or "Sin explicación.", className="parrafo"),
        ui.aviso(a.get("recomendacion") or "Sin recomendación.", "canje", "Recomendación"),
    ], className="api-resumen")


def historial(lista):
    if not lista:
        return ui.nota("La alerta todavía no tiene movimientos.")
    filas = [[fecha_hora(h.get("creado_en")), h.get("usuario") or "—", NOMBRE_ACCION.get(h.get("accion"), h.get("accion")),
              f"{ESTADO.get(h.get('estado_anterior'), (h.get('estado_anterior') or '—',))[0]} → "
              f"{ESTADO.get(h.get('estado_nuevo'), (h.get('estado_nuevo') or '—',))[0]}",
              h.get("asignado_a") or "—", h.get("comentario") or "—"] for h in lista]
    return ui.tabla(["Fecha", "Usuario", "Acción", "Estado", "Asignada a", "Comentario"], filas,
                    num=[False] * 6, compacta=True, ocultar_movil=(4,))


@callback(Output("al-detalle", "children"), Output("al-campos", "children"), Output("al-historial", "children"),
          *[Output(f"al-{a}", "disabled") for a, _t, _i in ACCIONES],
          Input("al-sel", "data"), Input("al-refresco", "data"))
def detalle(sel, _refresco):
    todos = [True] * len(ACCIONES)
    if not sel:
        return ui.nota("Elija una alerta de la lista."), None, ui.nota("Sin alerta elegida."), *todos
    a, err = A.obtener(f"alerts/{sel}")
    if err:
        return ui.aviso(err, "atencion", "No se pudo leer la alerta", rol="status"), None, None, *todos
    h, err_h = A.obtener(f"alerts/{sel}/history")
    hist = ui.aviso(err_h, "atencion", "No se pudo leer la bitácora", rol="status") if err_h else historial(h)
    permitidas = TRANSICIONES.get(a["estado"], set()) | (set() if a["estado"] in FINALES else {"comentar"})
    return (resumen(a, subio=not err_h and escalada(h)), campos(a), hist,
            *[acc not in permitidas for acc, _t, _i in ACCIONES])


# --- Acciones ---------------------------------------------------------------------------------------------------------
@callback(Output("al-resultado", "children"), Output("al-refresco", "data"), Output("al-comentario", "value"),
          *[Input(f"al-{a}", "n_clicks") for a, _t, _i in ACCIONES],
          State("al-sel", "data"), State("al-asignado", "value"), State("al-comentario", "value"), State("al-refresco", "data"),
          prevent_initial_call=True)
def actuar(*args):
    sel, asignado, comentario, refresco = args[-4:]
    accion = (ctx.triggered_id or "").removeprefix("al-")
    if not sel or accion not in {a for a, _t, _i in ACCIONES} or not ctx.triggered[0].get("value"):
        return no_update, no_update, no_update
    r, err = A.cambiar_estado(sel, accion, comentario=comentario, asignado_a=asignado if accion == "asignar" else None)
    if err:
        return ui.aviso(err, "atencion", "La API no aplicó la acción", rol="status"), (refresco or 0) + 1, no_update
    # Quién la hizo lo dice la bitácora de la API (con autenticación, el usuario de la clave; sin ella, el del tablero)
    h, _err_h = A.obtener(f"alerts/{sel}/history")
    quien = (h[-1].get("usuario") if h else None) or A.USUARIO
    texto = f"{NOMBRE_ACCION.get(accion, accion)} por {quien} · estado actual: {ESTADO.get(r['estado'], (r['estado'],))[0].lower()}"
    return ui.aviso(texto, "bien", "Acción registrada", rol="status"), (refresco or 0) + 1, ""


# --- Exportación ------------------------------------------------------------------------------------------------------
@callback(Output("al-descarga", "data"), Output("al-export-aviso", "children"),
          Input("al-csv", "n_clicks"), Input("al-xlsx", "n_clicks"),
          State("al-estado", "value"), State("al-nivel", "value"), State("al-ruta", "value"), State("al-codigo", "value"),
          State("al-desde", "date"), State("al-hasta", "date"), prevent_initial_call=True)
def exportar(_csv, _xlsx, estado, nivel, ruta, codigo, desde, hasta):
    if not ctx.triggered[0].get("value"):
        return no_update, no_update
    formato = "xlsx" if ctx.triggered_id == "al-xlsx" else "csv"
    filtros = _filtros(estado, nivel, ruta, codigo, desde, hasta)
    archivo, err = A.descargar("alerts", formato, **filtros, orden=ORDEN_PRIORIDAD)
    if err and err.startswith("orden_invalido"):   # una API anterior sin orden=prioridad: el mismo archivo, por fecha
        archivo, err = A.descargar("alerts", formato, **filtros, orden="-detectada_en")
    if err:
        return no_update, ui.aviso(err, "atencion", "No se pudo exportar", rol="status")
    contenido, nombre = archivo
    return dcc.send_bytes(contenido, nombre), None
