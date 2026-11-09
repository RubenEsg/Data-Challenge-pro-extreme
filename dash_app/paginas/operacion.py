"""Operación: ¿Cómo está corriendo el sistema? El ciclo de §14.2 visto y operado desde el tablero (RF-013, RF-018, RF-019,
§5.1 regla de gobierno, RNF-004, RNF-006, RNF-011, E06), con el estilo de DISENO.md. Cuatro vistas:

- Ejecuciones: marca de agua anterior → nueva, corte, filas, métricas, errores por lote y fila
  (GET /api/v1/frequency/executions, /{id} y /{id}/errors) y «Ejecutar día siguiente» (POST /frequency/executions).
- Modelos: registro con comparación de métricas, activación auditada (el 409 «activacion_rechazada» se muestra con su
  motivo), reversión y entrenamiento de un candidato (GET /models, POST /models/{id}/activate, /models/rollback,
  /models/train).
- Umbrales: versión vigente, historial por nombre y una versión nueva con su motivo (GET/PUT /thresholds,
  GET /thresholds/history).
- Salud del servicio: /health, /metrics (peticiones, errores y p95 aproximado por ruta), alertas nuevas por nivel y el
  error del pronóstico frente a su tolerancia. El monitoreo del modelo (deriva, error móvil, política de
  reentrenamiento y retador en sombra) tiene su propia pantalla: paginas/monitoreo.py.

Los trabajos largos nunca bloquean un callback: la ejecución y el entrenamiento son jobs de la API (POST → 202) que se
siguen con un dcc.Interval de 2 s; la activación y la reversión corren en un hilo del servidor del Dash y el mismo
Interval recoge su resultado. Sin API, la pantalla lo dice y no inventa nada."""
import threading
import uuid
from datetime import timedelta

import dash
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

import cliente_api as A
import ui

dash.register_page(__name__, path="/operacion", name="Operación", order=8, title="Operación · Sobusa Despacho")

VISTAS = [("Ejecuciones", "ejecuciones"), ("Modelos", "modelos"), ("Umbrales", "umbrales"), ("Salud del servicio", "monitoreo")]
ESTADO_EJEC = {"en_cola": ("En cola", None, "reloj"), "corriendo": ("Corriendo", "atencion", "play"), "ok": ("Terminada", "bien", None),
               "error": ("Con error", "critico", None)}
ESTADO_MODELO = {"activo": ("Activo", "bien", None), "candidato": ("Candidato", None, "info"),
                 "rechazado": ("Rechazado", "critico", None), "retirado": ("Retirado", None, "cerrar")}
NIVELES = [("critica", "Críticas", "critico"), ("preventiva", "Preventivas", "atencion"), ("informativa", "Informativas", None)]
FINALES = {"ok", "error"}
FUENTES_E = ["GET /api/v1/frequency/executions", "GET /api/v1/frequency/executions/{id}/errors"]
FUENTES_M = ["GET /api/v1/models", "POST /api/v1/models/{id}/activate", "POST /api/v1/models/rollback"]
FUENTES_U = ["GET /api/v1/thresholds", "GET /api/v1/thresholds/history", "PUT /api/v1/thresholds"]
FUENTES_S = ["GET /health", "GET /metrics", "GET /api/v1/alerts"]

# Resultados de lo que corre en un hilo aparte (activar, revertir): el Interval los recoge por su ficha
_TRABAJOS = {}
_CANDADO = threading.Lock()


def _lanzar(funcion, *args, **kwargs):
    ficha = uuid.uuid4().hex
    with _CANDADO:
        _TRABAJOS[ficha] = None

    def correr():
        try:
            res = funcion(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - el hilo nunca muere en silencio
            res = (None, f"Error inesperado en el tablero: {exc.__class__.__name__}")
        with _CANDADO:
            _TRABAJOS[ficha] = res

    threading.Thread(target=correr, daemon=True, name=f"op-{ficha[:8]}").start()
    return ficha


def _recoger(ficha):
    with _CANDADO:
        if ficha not in _TRABAJOS or _TRABAJOS[ficha] is None:
            return None
        return _TRABAJOS.pop(ficha)


# --- Formato ----------------------------------------------------------------------------------------------------------
def hora_local(x):
    """Instante de la API en la hora de Bogotá (la auditoría viene en UTC)."""
    t = pd.Timestamp(x)
    return t.tz_convert("America/Bogota") if t.tzinfo is not None else t


def fecha_hora(x):
    if not x:
        return "—"
    t = hora_local(x)
    return f"{ui.fecha_corta(t)} {t.year} · {t:%H:%M}"


def fecha_hora_corta(x):
    """«31 ago 23:59» para la marca de agua en la tabla (el año completo va en el detalle)."""
    if not x:
        return "—"
    t = hora_local(x)
    return f"{ui.fecha_corta(t)} {t:%H:%M}"


def fecha(x):
    if not x:
        return "—"
    t = hora_local(x)
    return f"{ui.fecha_corta(t)} {t.year}"


def chip(mapa, valor):
    texto, tipo, icono = mapa.get(valor, (valor or "—", None, "info"))
    return ui.chip(texto, tipo, icono)


def wape(x):
    """La API da el WAPE en % (12,9) o como fracción (0,129): siempre en %."""
    if x is None:
        return "—"
    return f"{ui.num(x * 100 if x <= 1.5 else x, 1)} %"


def cabecera(titulo, subtitulo):
    return html.Header(html.Div([ui.cuadro("operacion", "panel", "cuadro-color--cabecera"),
                                 html.H1(titulo, className="cabecera__pregunta"),
                                 html.P(subtitulo, className="cabecera__subtitulo")], className="cabecera__texto"),
                       className="cabecera")


def aviso_api(err):
    """Aviso de la API caída o de la clave sin validez (401) o sin rol (403): título y qué hacer, nunca una traza."""
    return ui.aviso([err, A.ayuda_error(err)], "atencion", A.titulo_error(err), rol="status")


def campo(id_, rotulo, placeholder="", tipo="text", ayuda=None):
    hijos = [html.Label(rotulo, htmlFor=id_, className="campo__rotulo"),
             dcc.Input(id=id_, type=tipo, placeholder=placeholder, className="campo", debounce=False, autoComplete="off")]
    if ayuda:
        hijos.append(html.P(ayuda, className="campo__ayuda"))
    return html.Div(hijos, className="campo-bloque")


def selector(id_, rotulo, ancho=False):
    return ui.control(rotulo, dcc.Dropdown(id=id_, options=[], value=None, clearable=False, searchable=False, placeholder="—",
                                           className="desplegable-api" + (" desplegable-api--ancho" if ancho else "")))


def fecha_sel(id_):
    return dcc.DatePickerSingle(id=id_, date=None, display_format="DD/MM/YYYY", month_format="MM/YYYY", first_day_of_week=1,
                                clearable=True, placeholder="dd/mm/aaaa", className="fecha")


# --- Pantalla ---------------------------------------------------------------------------------------------------------
def _vista_ejecuciones():
    return html.Div([
        ui.seccion("Ejecuciones de frecuencia y entrenamiento", [
            ui.fila_controles([ui.boton("Ejecutar día siguiente", id="op-ejecutar", tipo="primario", icono="play"),
                               html.Span(id="op-siguiente", className="nota")]),
            ui.tarjeta(html.Div(id="op-ejecuciones"), titulo="Últimas ejecuciones",
                       subtitulo="Marca de agua, corte de datos, filas y lo producido: predicciones · recomendaciones · alertas nuevas, "
                                "o el modelo entrenado.", fuentes=FUENTES_E[:1]),
        ], subtitulo="Cada ejecución procesa solo lo nuevo desde la marca de agua anterior (RF-013)."),
        ui.seccion("Detalle de la ejecución", [
            ui.fila_controles([selector("op-ejec", "Ejecución", ancho=True)]),
            ui.rejilla([ui.tarjeta(html.Div(id="op-ejec-detalle"), titulo="Evaluación del error",
                                   subtitulo="WAPE y cobertura del intervalo P10–P90 del modelo usado."),
                        ui.tarjeta([html.Div([campo("op-f-lote", "Lote", "id:AAAA-MM-DD"),
                                              campo("op-f-dimension", "Dimensión", "completitud, validez…"),
                                              campo("op-f-codigo", "Código", "DQ-…")], className="api-formulario"),
                                    html.Div(id="op-errores")], titulo="Errores de calidad por lote y fila",
                                   fuentes=FUENTES_E[1:])], "1-1"),
        ]),
    ], id="op-v-ejecuciones", className="api-vista")


def _vista_modelos():
    acciones = html.Div([
        ui.fila_controles([selector("op-modelo", "Modelo", ancho=True)]),
        html.Div([campo("op-m-motivo", "Motivo", "Por qué se activa o se revierte"),
                  html.Div([html.Label("Validación desde", htmlFor="op-m-desde", className="campo__rotulo"), fecha_sel("op-m-desde")],
                           className="campo-bloque"),
                  html.Div([html.Label("Validación hasta", htmlFor="op-m-hasta", className="campo__rotulo"), fecha_sel("op-m-hasta")],
                           className="campo-bloque")], className="api-formulario"),
        ui.nota("Sin fechas, la API valida las cuatro semanas siguientes al corte del modelo. La regla de §5.1: solo se activa "
                "si su WAPE no es peor que el del activo en la misma ventana."),
        html.Div([ui.boton("Activar", id="op-activar", tipo="primario", icono="bien"),
                  ui.boton("Revertir al anterior", id="op-revertir", icono="flecha-abajo"),
                  ui.boton("Entrenar candidato", id="op-entrenar", icono="modelo")], className="botonera"),
        html.P(id="op-m-usuario", className="nota"),
    ], className="api-acciones")
    return html.Div([
        ui.seccion("Registro de modelos", [
            ui.tarjeta(html.Div(id="op-modelos"), titulo="Versiones registradas",
                       subtitulo="Estado, corte, versión de variables, huella del artefacto y quién lo aprobó.", fuentes=FUENTES_M[:1]),
            ui.rejilla([ui.tarjeta(acciones, titulo="Activar, revertir o entrenar", fuentes=FUENTES_M[1:]),
                        ui.tarjeta(html.Div(id="op-auditoria"), titulo="Auditoría del modelo",
                                   subtitulo="Cada evento con su fecha, usuario y motivo.")], "1-1"),
            ui.tarjeta(html.Div(id="op-comparacion"), titulo="Comparación en la validación temporal",
                       subtitulo="WAPE total, en pico y en valle y por ruta del modelo elegido frente a las líneas base."),
        ], subtitulo="El modelo activo es el que usan las ejecuciones; cambiarlo queda auditado (RF-018, RNF-011)."),
    ], id="op-v-modelos", className="api-vista", hidden=True)


def _vista_umbrales():
    return html.Div([
        ui.seccion("Umbrales por versión", [
            ui.tarjeta(html.Div(id="op-umbrales"), titulo="Versión vigente", fuentes=FUENTES_U[:1]),
            ui.rejilla([
                ui.tarjeta([ui.fila_controles([selector("op-u-nombre", "Umbral", ancho=True)]), html.Div(id="op-u-historial")],
                           titulo="Historial del umbral", fuentes=FUENTES_U[1:2]),
                ui.tarjeta([html.Div([campo("op-u-valor", "Valor nuevo", "", "number"),
                                      campo("op-u-motivo", "Motivo", "Por qué cambia")], className="api-formulario"),
                            html.Div(ui.boton("Guardar como versión nueva", id="op-u-guardar", tipo="primario"), className="botonera"),
                            html.Div(id="op-u-resultado", **{"aria-live": "polite"})],
                           titulo="Cambiar el umbral elegido", subtitulo="Crea una versión nueva del conjunto; la anterior queda en el historial.",
                           fuentes=FUENTES_U[2:]),
            ], "1-1"),
        ], subtitulo="Las ejecuciones siguientes usan la versión vigente; cada cambio deja quién y por qué (§5.1)."),
    ], id="op-v-umbrales", className="api-vista", hidden=True)


def _vista_monitoreo():
    return html.Div([
        ui.seccion("Salud del servicio", [
            ui.fila_controles([ui.boton("Actualizar", id="op-s-actualizar", icono="reloj", pequeno=True),
                               ui.boton("Monitoreo del modelo", href="/monitoreo", icono="chevron-derecha", pequeno=True)]),
            html.Div(id="op-salud"),
            ui.rejilla([ui.tarjeta(html.Div(id="op-metricas"), titulo="Peticiones por ruta",
                                   subtitulo="Conteo, errores y p95 aproximado del histograma de latencia.", fuentes=FUENTES_S[1:2]),
                        ui.tarjeta(html.Div(id="op-abiertas"), titulo="Alertas nuevas por nivel",
                                   subtitulo="Lo que nadie ha reconocido todavía.", fuentes=FUENTES_S[2:])], "2-1"),
        ], subtitulo="/health, /metrics en formato Prometheus y el error del pronóstico frente a su tolerancia.", fuentes=FUENTES_S[:1]),
    ], id="op-v-monitoreo", className="api-vista", hidden=True)


def layout(**_):
    return ui.pantalla([
        dcc.Store(id="op-trabajo", data=None),
        dcc.Store(id="op-refresco", data=0),
        dcc.Interval(id="op-tic", interval=2000, disabled=True),
        ui.arriba(cabecera("Operación", "Ejecuciones, modelos, umbrales y salud del servicio, con lo que cada acción deja auditado."),
                  [ui.control("Vista", ui.segmentado("op-vista", [{"label": a, "value": b} for a, b in VISTAS], "ejecuciones",
                                                     persistir=False))],
                  html.Div([html.Div(id="op-aviso-api"), html.Div(id="op-job", **{"aria-live": "polite"})], className="api-respuesta")),
        _vista_ejecuciones(), _vista_modelos(), _vista_umbrales(), _vista_monitoreo(),
    ], "pantalla--api")


@callback(*[Output(f"op-v-{v}", "hidden") for _a, v in VISTAS], Input("op-vista", "value"))
def cambiar_vista(vista):
    return [v != vista for _a, v in VISTAS]


# --- Ejecuciones ------------------------------------------------------------------------------------------------------
def _siguiente_dia(items):
    """El día que sigue a la última marca de agua de una ejecución de frecuencia terminada (sale de la API)."""
    for e in items:
        if e["tipo"] == "frecuencia" and e["estado"] == "ok" and e.get("marca_agua_nueva"):
            return (pd.Timestamp(e["marca_agua_nueva"]).date() + timedelta(days=1)).isoformat()
    return None


def _tabla_ejecuciones(items):
    filas = []
    for e in items:
        m = e.get("metricas") or {}
        marca = f"{fecha_hora_corta(e.get('marca_agua_anterior'))} → {fecha_hora_corta(e.get('marca_agua_nueva'))}"
        producido = (f"{ui.num(m.get('predicciones'))} · {ui.num(m.get('recomendaciones'))} · {ui.num(m.get('alertas_nuevas'))}"
                     if m.get("predicciones") is not None else (e.get("model_id") or "—"))
        filas.append([html.Code(str(e["execution_id"])[:8], className="api-nowrap"), chip(ESTADO_EJEC, e["estado"]),
                      e["tipo"], html.Span(f"{ui.num(e.get('progreso'))} %", className="api-nowrap"),
                      html.Span(marca, className="api-marca"), html.Span(fecha(e.get("data_cutoff")), className="api-nowrap"),
                      html.Span(f"{ui.num(e.get('filas_leidas'))} / {ui.num(e.get('filas_validas'))}", className="api-nowrap"),
                      producido,
                      html.Span(f"{ui.num(m.get('duracion_s'), 1)} s" if m.get("duracion_s") is not None else "—", className="api-nowrap")])
    return ui.tabla(["Ejecución", "Estado", "Tipo", "Progreso", "Marca de agua (anterior → nueva)", "Corte", "Filas leídas / válidas",
                     "Producido", "Duración"],
                    filas, num=[False, False, False, True, False, False, True, True, True], compacta=True,
                    ocultar_movil=(2, 3, 5, 7))


@callback(Output("op-ejecuciones", "children"), Output("op-siguiente", "children"), Output("op-ejecutar", "disabled"),
          Output("op-ejec", "options"), Output("op-ejec", "value"), Output("op-aviso-api", "children"),
          Input("op-refresco", "data"), Input("op-vista", "value"), State("op-ejec", "value"))
def ejecuciones(_refresco, _vista, actual):
    datos, err = A.obtener("frequency/executions", limite=20, orden="-creado_en")
    if err:
        return ui.nota("Sin datos: la API no está disponible."), None, True, [], None, aviso_api(err)
    items = datos["items"]
    sig = _siguiente_dia(items)
    texto = f"Procesará los datos hasta el {ui.fecha_larga(sig)}." if sig else "Primera ejecución: la API toma los datos disponibles."
    ops = [{"label": f"{str(e['execution_id'])[:8]} · {e['tipo']} · {ESTADO_EJEC.get(e['estado'], (e['estado'],))[0].lower()} · "
                     f"{fecha_hora(e['creado_en'])}", "value": str(e["execution_id"])} for e in items]
    valores = [o["value"] for o in ops]
    # Por omisión, la última ejecución de frecuencia terminada (la que trae evaluación del error y errores de calidad)
    defecto = next((str(e["execution_id"]) for e in items if e["tipo"] == "frecuencia" and e["estado"] == "ok"), valores[0] if valores else None)
    tabla = _tabla_ejecuciones(items) if items else ui.nota("La API no tiene ejecuciones todavía.")
    return tabla, texto, False, ops, (actual if actual in valores else defecto), None


def _evaluacion(ev):
    if not ev:
        return ui.nota("Esta ejecución no trae evaluación del error (las de entrenamiento la dejan en el registro de modelos).")
    fichas = ui.cifras([
        ui.cifra("WAPE", wape(ev.get("wape")), None, nota=f"{ui.num(ev.get('n'))} horas · {fecha(ev.get('desde'))} a {fecha(ev.get('hasta'))}"),
        ui.cifra("Cobertura P10–P90", f"{ui.num(ev.get('cobertura_p10_p90'), 1)} %", None, nota="Parte de lo observado dentro del intervalo."),
        ui.cifra("MAE", ui.num(ev.get("mae"), 1), "pasajeros", nota=f"RMSE {ui.num(ev.get('rmse'), 1)} · sesgo {ui.num(ev.get('sesgo_pct'), 2)} %"),
    ])
    filas = [[r, wape(v.get("wape")), ui.num(v.get("mae"), 1), ui.num(v.get("n"))] for r, v in (ev.get("por_ruta") or {}).items()]
    for clave, nombre in (("pico", "Hora pico"), ("valle", "Valle")):
        if ev.get(clave):
            filas.append([nombre, wape(ev[clave].get("wape")), ui.num(ev[clave].get("mae"), 1), ui.num(ev[clave].get("n"))])
    return [fichas, ui.tabla(["Segmento", "WAPE", "MAE", "Horas"], filas, compacta=True) if filas else None,
            ui.nota(f"Modelo evaluado: {ev.get('model_id') or '—'}")]


@callback(Output("op-ejec-detalle", "children"), Output("op-errores", "children"),
          Input("op-ejec", "value"), Input("op-f-lote", "value"), Input("op-f-dimension", "value"), Input("op-f-codigo", "value"))
def detalle_ejecucion(ejec, lote, dimension, codigo):
    if not ejec:
        return ui.nota("Elija una ejecución."), None
    d, err = A.obtener(f"frequency/executions/{ejec}")
    if err:
        return ui.aviso(err, "atencion", "No se pudo leer la ejecución", rol="status"), None
    m = d.get("metricas") or {}
    partes = [html.Div([chip(ESTADO_EJEC, d["estado"]), ui.chip_valor("Lote:", m.get("lote") or "—"),
                        ui.chip_valor("Modelo:", d.get("model_id") or "—"), ui.chip_valor("Umbrales:", f"versión {ui.num(d.get('umbrales_version'))}" if d.get("umbrales_version") else "—"),
                        ui.chip_valor("Intentos:", ui.num(d.get("intentos")))],
                       className="api-chips")]
    partes.append(ui.nota(" · ".join(x for x in (d.get("mensaje"), d.get("etapa") and f"etapa {d['etapa']}",
                                                  d.get("correlation_id") and f"correlation_id {d['correlation_id']}") if x)))
    partes += _lista(_evaluacion(m.get("evaluacion_error")))
    errores, err_e = A.obtener(f"frequency/executions/{ejec}/errors", lote=(lote or "").strip() or None,
                               dimension=(dimension or "").strip() or None, codigo=(codigo or "").strip() or None, limite=50)
    if err_e:
        tabla_e = ui.aviso(err_e, "atencion", "No se pudieron leer los errores", rol="status")
    else:
        resumen = d.get("errores_por_dimension") or {}
        cab = ui.nota(f"{ui.num(errores['total'])} errores con estos filtros" +
                      (" · por dimensión: " + ", ".join(f"{k} {ui.num(v)}" for k, v in resumen.items()) if resumen else ""))
        filas = [[x["lote"], ui.num(x.get("fila")), x.get("campo") or "—", x["codigo"], x["dimension"], x.get("detalle") or "—"]
                 for x in errores["items"]]
        tabla_e = [cab, ui.tabla(["Lote", "Fila", "Campo", "Código", "Dimensión", "Detalle"], filas, compacta=True,
                                 num=[False, True, False, False, False, False]) if filas else
                   ui.aviso("La ejecución no dejó errores de calidad con estos filtros.", "bien", "Sin errores", rol="status")]
    return partes, tabla_e


def _lista(x):
    return x if isinstance(x, list) else [x]


# --- Modelos ----------------------------------------------------------------------------------------------------------
def _wape_validacion(m):
    met = m.get("metricas") or {}
    v = (met.get("validacion_activacion") or {}).get("candidato") or (met.get("validacion") or {}).get("candidato") or {}
    return wape(v.get("wape")) if v else "—"


@callback(Output("op-modelos", "children"), Output("op-modelo", "options"), Output("op-modelo", "value"),
          Output("op-m-usuario", "children"),
          Input("op-refresco", "data"), Input("op-vista", "value"), State("op-modelo", "value"))
def modelos(_refresco, vista, actual):
    if vista != "modelos":
        return no_update, no_update, no_update, no_update
    datos, err = A.obtener("models", limite=50, orden="-creado_en")
    if err:
        return aviso_api(err), [], None, None
    items = datos["items"]
    def corto(x, clase="api-nowrap"):
        return html.Span(x, className=clase)

    filas = [[m["model_id"], m.get("tipo") or "—", chip(ESTADO_MODELO, m["estado"]), corto(fecha(m.get("data_cutoff"))),
              corto(m.get("feature_version") or "—"), html.Code((m.get("sha256") or "—")[:12], className="api-nowrap"),
              _wape_validacion(m), m.get("aprobado_por") or "—", corto(fecha_hora(m.get("activado_en"))),
              m.get("anterior_model_id") or "—"] for m in items]
    tabla = ui.tabla(["Modelo (versión)", "Tipo", "Estado", "Corte", "Variables", "sha256", "WAPE de validación", "Aprobado por",
                      "Activado", "Anterior"], filas, compacta=True, num=[False] * 6 + [True] + [False] * 3,
                     ocultar_movil=(1, 4, 5, 7, 9))
    ops = [{"label": f"{m['model_id']} · {ESTADO_MODELO.get(m['estado'], (m['estado'],))[0].lower()}", "value": m["model_id"]}
           for m in items]
    valores = [o["value"] for o in ops]
    activo = next((m["model_id"] for m in items if m["estado"] == "activo"), None)
    usuario = f"Las acciones se registran a nombre de {A.USUARIO}" + (" (clave SOBUSA_API_KEY)." if A.con_clave() else ".")
    return tabla, ops, (actual if actual in valores else (activo or (valores[0] if valores else None))), usuario


def _comparacion(m):
    met = m.get("metricas") or {}
    bloque = met.get("validacion_activacion") or met.get("validacion")
    if not bloque:
        return ui.nota("Este modelo todavía no tiene una validación registrada (se crea al entrenarlo o al intentar activarlo).")
    filas, totales, rutas = [], [], []
    for nombre, v in bloque.items():
        if not isinstance(v, dict) or "wape" not in v:
            continue
        por_ruta = v.get("por_ruta") or {}
        rutas = rutas or list(por_ruta)
        etiqueta = m["model_id"] if nombre == "candidato" else (bloque.get("activo_model_id") if nombre == "activo" else nombre)
        filas.append([etiqueta or nombre, wape(v.get("wape")), wape((v.get("pico") or {}).get("wape")),
                      wape((v.get("valle") or {}).get("wape"))] + [wape((por_ruta.get(r) or {}).get("wape")) for r in rutas])
        totales.append(float(v["wape"]))
    if not filas:
        return ui.nota("La validación registrada no trae métricas comparables.")
    ventana = bloque.get("ventana") or {"desde": bloque.get("desde"), "hasta": bloque.get("hasta")}
    mejor = totales.index(min(totales))
    return [ui.nota(f"Ventana de validación: {fecha(ventana.get('desde'))} a {fecha(ventana.get('hasta'))} · el WAPE más bajo "
                    "va resaltado."),
            ui.tabla(["Modelo", "WAPE", "Pico", "Valle"] + rutas, filas, compacta=True, mejor=[(mejor, 1)])]


def _auditoria(m):
    eventos = m.get("auditoria") or []
    if not eventos:
        return ui.nota("Sin eventos.")
    items = []
    for ev in reversed(eventos):
        detalle = " · ".join(x for x in (ev.get("usuario"), ev.get("motivo"), ev.get("reemplazado_por") and f"reemplazado por {ev['reemplazado_por']}",
                                         ev.get("vuelve_a") and f"vuelve a {ev['vuelve_a']}", ev.get("desde") and f"desde {ev['desde']}") if x)
        items.append(html.Li([html.Span(fecha_hora(ev.get("en")), className="api-tenue"), " ",
                              html.Strong(ev.get("evento", "—").replace("_", " ")), html.Span(f" · {detalle}" if detalle else "")],
                             className="api-linea__evento"))
    return html.Ol(items, className="api-linea")


@callback(Output("op-auditoria", "children"), Output("op-comparacion", "children"),
          Input("op-modelo", "value"), Input("op-refresco", "data"))
def ficha_modelo(model_id, _refresco):
    if not model_id:
        return ui.nota("Elija un modelo."), None
    m, err = A.obtener(f"models/{model_id}")
    if err:
        return ui.aviso(err, "atencion", "No se pudo leer el modelo", rol="status"), None
    return _auditoria(m), _comparacion(m)


# --- Trabajos: ejecutar, entrenar, activar y revertir (POST y luego el Interval) ---------------------------------------
@callback(Output("op-trabajo", "data"), Output("op-tic", "disabled"), Output("op-job", "children"),
          Input("op-ejecutar", "n_clicks"), Input("op-entrenar", "n_clicks"), Input("op-activar", "n_clicks"),
          Input("op-revertir", "n_clicks"),
          State("op-modelo", "value"), State("op-m-motivo", "value"),
          State("op-m-desde", "date"), State("op-m-hasta", "date"), State("op-trabajo", "data"),
          prevent_initial_call=True)
def lanzar(_e, _t, _a, _r, modelo, motivo, desde, hasta, trabajo):
    if not ctx.triggered[0].get("value"):
        return no_update, no_update, no_update
    if trabajo:
        return no_update, no_update, ui.aviso("Ya hay un trabajo en curso: espere a que termine.", "atencion", "Un trabajo a la vez",
                                              rol="status")
    quien = ctx.triggered_id
    if quien in ("op-ejecutar", "op-entrenar"):
        lista, err = A.obtener("frequency/executions", limite=20, orden="-creado_en")
        if err:
            return no_update, no_update, aviso_api(err)
        sig = _siguiente_dia(lista["items"])
        if quien == "op-ejecutar":
            r, err = A.enviar("POST", "frequency/executions", {"hasta": sig} if sig else {})
            nombre = "Ejecución del día siguiente"
        else:
            corte = (pd.Timestamp(sig).date() - timedelta(days=1)).isoformat() if sig else None
            if not corte:
                return no_update, no_update, ui.aviso("Corra primero una ejecución: el entrenamiento usa su corte de datos.",
                                                      "atencion", "Sin corte de datos", rol="status")
            r, err = A.enviar("POST", "models/train", {"hasta": corte, "solicitado_por": A.USUARIO})
            nombre = "Entrenamiento de un candidato"
        if err:
            return no_update, no_update, ui.aviso(err, "atencion", "La API no aceptó el trabajo", rol="status")
        return ({"tipo": "api", "id": str(r["execution_id"]), "nombre": nombre}, False,
                _progreso(nombre, r))
    if not modelo and quien == "op-activar":
        return no_update, no_update, ui.aviso("Elija el modelo que quiere activar.", "atencion", "Falta el modelo", rol="status")
    if quien == "op-activar":
        cuerpo = {"aprobado_por": A.USUARIO, "motivo": (motivo or "").strip() or None, "validacion_desde": desde, "validacion_hasta": hasta}
        ficha = _lanzar(A.enviar, "POST", f"models/{modelo}/activate", {k: v for k, v in cuerpo.items() if v}, tiempo=A.TIEMPO_LARGO)
        nombre = f"Activación de {modelo}"
    else:
        cuerpo = {"usuario": A.USUARIO, "motivo": (motivo or "").strip() or None}
        ficha = _lanzar(A.enviar, "POST", "models/rollback", {k: v for k, v in cuerpo.items() if v}, tiempo=A.TIEMPO_LARGO)
        nombre = "Reversión al modelo anterior"
    return {"tipo": "hilo", "id": ficha, "nombre": nombre}, False, ui.aviso("La API está validando…", None, nombre, rol="status")


def _progreso(nombre, e):
    p = float(e.get("progreso") or 0) / 100
    return html.Div([
        ui.barra_rayas(f"{nombre} · {e.get('etapa') or ESTADO_EJEC.get(e['estado'], (e['estado'],))[0]}",
                       f"{ui.num(e.get('progreso'))} %", p, "modelo"),
        html.Div([chip(ESTADO_EJEC, e["estado"]), ui.chip_valor("Ejecución:", str(e["execution_id"])[:8])], className="api-chips"),
    ], className="api-trabajo")


@callback(Output("op-job", "children", allow_duplicate=True), Output("op-tic", "disabled", allow_duplicate=True),
          Output("op-trabajo", "data", allow_duplicate=True), Output("op-refresco", "data"),
          Input("op-tic", "n_intervals"), State("op-trabajo", "data"), State("op-refresco", "data"), prevent_initial_call=True)
def seguir(_n, trabajo, refresco):
    if not trabajo:
        return no_update, True, no_update, no_update
    if trabajo["tipo"] == "hilo":
        res = _recoger(trabajo["id"])
        if res is None:
            return no_update, False, no_update, no_update
        datos, err = res
        if err:
            return (ui.aviso(err, "critico" if "rechazada" in err else "atencion", f"{trabajo['nombre']}: la API no la aplicó"),
                    True, None, (refresco or 0) + 1)
        texto = f"Modelo activo: {datos.get('model_id')} · aprobado por {datos.get('aprobado_por') or A.USUARIO}"
        return ui.aviso(texto, "bien", f"{trabajo['nombre']}: hecha", rol="status"), True, None, (refresco or 0) + 1
    e, err = A.obtener(f"frequency/executions/{trabajo['id']}")
    if err:
        return aviso_api(err), False, no_update, no_update
    if e["estado"] not in FINALES:
        return _progreso(trabajo["nombre"], e), False, no_update, no_update
    if e["estado"] == "error":
        return ui.aviso(e.get("mensaje") or "La ejecución terminó con error.", "critico", f"{trabajo['nombre']}: con error"), True, None, \
            (refresco or 0) + 1
    m = e.get("metricas") or {}
    resumen = (f"{e.get('mensaje') or 'Terminada'} · {ui.num(m.get('duracion_s'), 1)} s"
               + (f" · {ui.num(m.get('predicciones'))} predicciones, {ui.num(m.get('recomendaciones'))} recomendaciones y "
                  f"{ui.num(m.get('alertas_nuevas'))} alertas nuevas" if m.get("predicciones") is not None else "")
               + (f" · modelo {e.get('model_id')}" if e["tipo"] == "entrenamiento" and e.get("model_id") else ""))
    return ui.aviso(resumen, "bien", f"{trabajo['nombre']}: terminada", rol="status"), True, None, (refresco or 0) + 1


# --- Umbrales ---------------------------------------------------------------------------------------------------------
def _valor_umbral(v):
    return ui.num(v, 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


@callback(Output("op-umbrales", "children"), Output("op-u-nombre", "options"), Output("op-u-nombre", "value"),
          Input("op-refresco", "data"), Input("op-vista", "value"), State("op-u-nombre", "value"))
def umbrales(_refresco, vista, actual):
    if vista != "umbrales":
        return no_update, no_update, no_update
    u, err = A.obtener("thresholds")
    if err:
        return aviso_api(err), [], None
    filas = [[d["nombre"], _valor_umbral(d["valor"]), d.get("descripcion") or "—", ui.num(d.get("version")), d.get("creado_por") or "—",
              fecha_hora(d.get("creado_en"))] for d in u["detalle"]]
    cuerpo = [html.Div([ui.chip_valor("Versión vigente:", ui.num(u["version"])), ui.chip_valor("Umbrales:", ui.num(len(filas)))],
                       className="api-chips"),
              ui.tabla(["Umbral", "Valor", "Qué controla", "Versión", "Creado por", "Desde"], filas, compacta=True,
                       num=[False, True, False, True, False, False], ocultar_movil=(2, 4, 5))]
    nombres = [d["nombre"] for d in u["detalle"]]
    return cuerpo, [{"label": n, "value": n} for n in nombres], (actual if actual in nombres else (nombres[0] if nombres else None))


@callback(Output("op-u-historial", "children"), Output("op-u-valor", "placeholder"),
          Input("op-u-nombre", "value"), Input("op-refresco", "data"))
def historial_umbral(nombre, _refresco):
    if not nombre:
        return ui.nota("Elija un umbral."), ""
    h, err = A.obtener("thresholds/history", nombre=nombre)
    if err:
        return ui.aviso(err, "atencion", "No se pudo leer el historial", rol="status"), ""
    filas = [[ui.num(x["version"]), _valor_umbral(x["valor"]), ui.chip("Vigente", "bien") if x["vigente"] else ui.chip("Anterior", None, "reloj"),
              x.get("creado_por") or "—", x.get("motivo") or "—", fecha_hora(x.get("creado_en"))] for x in sorted(h, key=lambda x: -x["version"])]
    vigente = next((x for x in h if x["vigente"]), None)
    return (ui.tabla(["Versión", "Valor", "Estado", "Creado por", "Motivo", "Fecha"], filas, compacta=True,
                     num=[True, True, False, False, False, False], ocultar_movil=(3, 5)),
            f"Vigente: {_valor_umbral(vigente['valor'])}" if vigente else "")


@callback(Output("op-u-resultado", "children"), Output("op-refresco", "data", allow_duplicate=True),
          Input("op-u-guardar", "n_clicks"), State("op-u-nombre", "value"), State("op-u-valor", "value"),
          State("op-u-motivo", "value"), State("op-refresco", "data"), prevent_initial_call=True)
def guardar_umbral(clic, nombre, valor, motivo, refresco):
    if not clic:
        return no_update, no_update
    if not nombre or valor in (None, ""):
        return ui.aviso("Elija el umbral y escriba el valor nuevo.", "atencion", "Faltan datos", rol="status"), no_update
    r, err = A.enviar("PUT", "thresholds", {"valores": {nombre: valor}, "creado_por": A.USUARIO, "motivo": (motivo or "").strip() or None})
    if err:
        return ui.aviso(err, "atencion", "La API no guardó el umbral", rol="status"), no_update
    return (ui.aviso(f"{nombre} = {_valor_umbral(r['valores'].get(nombre))} · versión {ui.num(r['version'])} · por {A.USUARIO}", "bien",
                     "Versión nueva guardada", rol="status"), (refresco or 0) + 1)


# --- Monitoreo --------------------------------------------------------------------------------------------------------
def _p95(cubetas):
    """p95 aproximado de un histograma Prometheus: el límite de la primera cubeta que llega al 95 % (en ms)."""
    total = max((c for _le, c in cubetas), default=0)
    if not total:
        return None
    for le, c in sorted(cubetas):
        if c >= 0.95 * total:
            return le * 1000 if le != float("inf") else None
    return None


def _tabla_metricas(texto):
    series = A.parsear_metricas(texto)
    por_ruta = {}
    for nombre, et, v in series:
        ruta = et.get("ruta")
        if not ruta:
            continue
        d = por_ruta.setdefault(ruta, {"n": 0.0, "err": 0.0, "cubetas": {}})
        if nombre == "api_peticiones_total":
            d["n"] += v
            if et.get("estado", "").startswith(("4", "5")):
                d["err"] += v
        elif nombre == "api_latencia_segundos_bucket":
            le = float("inf") if et.get("le") == "+Inf" else float(et.get("le", "inf"))
            d["cubetas"][le] = d["cubetas"].get(le, 0.0) + v
    filas = []
    for ruta, d in sorted(por_ruta.items(), key=lambda x: -x[1]["n"]):
        p = _p95(list(d["cubetas"].items()))
        filas.append([ruta, ui.num(d["n"]), ui.num(d["err"]), f"≤ {ui.num(p)} ms" if p is not None else "—"])
    if not filas:
        return ui.nota("/metrics no trae peticiones por ruta todavía.")
    n = sum(d["n"] for d in por_ruta.values())
    e = sum(d["err"] for d in por_ruta.values())
    return [ui.nota(f"{ui.num(n)} peticiones desde el arranque · {ui.num(e)} con estado 4xx o 5xx"),
            ui.tabla(["Ruta", "Peticiones", "Errores", "p95 aproximado"], filas[:15], compacta=True)]


@callback(Output("op-salud", "children"), Output("op-metricas", "children"), Output("op-abiertas", "children"),
          Input("op-s-actualizar", "n_clicks"), Input("op-vista", "value"), Input("op-refresco", "data"))
def monitoreo(_clic, vista, _refresco):
    if vista != "monitoreo":
        return no_update, no_update, no_update
    s, err = A.salud()
    if err:
        return aviso_api(err), None, None
    ok = s.get("estado") == "ok"
    chips = html.Div([ui.chip("Servicio en línea" if ok else "Servicio degradado", "bien" if ok else "atencion"),
                      ui.chip(f"Base de datos: {s.get('base_datos', '—')}", "bien" if s.get("base_datos") == "ok" else "critico"),
                      ui.chip_valor("Versión:", s.get("version") or "—"), ui.chip_valor("Fuente:", s.get("fuente") or "—")],
                     className="api-chips")
    fichas = []
    lista, err_l = A.obtener("frequency/executions", tipo="frecuencia", estado="ok", limite=1, orden="-creado_en")
    u, err_u = A.obtener("thresholds")
    if not err_l and lista["items"] and not err_u:
        ev = (lista["items"][0].get("metricas") or {}).get("evaluacion_error") or {}
        tol = (u.get("valores") or {}).get("wape_max")
        w = ev.get("wape")
        if w is not None and tol is not None:
            w_frac = w / 100 if w > 1.5 else w
            dentro = w_frac <= float(tol)
            fichas.append(ui.cifra("Error del pronóstico (WAPE móvil)", wape(w), None,
                                   variacion=f"tolerancia {wape(tol)} (ALT-010)", tono="bien" if dentro else "mal",
                                   chip=ui.chip("Dentro" if dentro else "Fuera", "bien" if dentro else "critico"),
                                   nota=f"Última ejecución · {fecha(ev.get('desde'))} a {fecha(ev.get('hasta'))}"))
    texto, err_m = A.metricas_texto()
    metricas = ui.aviso(err_m, "atencion", "No se pudo leer /metrics", rol="status") if err_m else _tabla_metricas(texto)
    filas = []
    for sev, nombre, tipo in NIVELES:
        d, err_a = A.obtener("alerts", estado="nueva", severidad=sev, limite=1)
        filas.append([ui.chip(nombre, tipo, None if tipo else "info"), ui.num(d["total"]) if not err_a else "—"])
    abiertas = ui.tabla(["Nivel", "Alertas nuevas"], filas, compacta=True)
    salud = html.Div([chips] + ([ui.cifras(fichas)] if fichas else []), className="api-resumen")
    return salud, metricas, html.Div([abiertas, ui.boton("Ir a Alertas", href="/alertas", icono="alerta", pequeno=True)],
                                     className="api-resumen")

