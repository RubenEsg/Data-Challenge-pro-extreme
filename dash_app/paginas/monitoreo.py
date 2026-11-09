"""Monitoreo: ¿El modelo sigue sirviendo? El monitoreo del modelo en producción y la política de aprendizaje continuo de la
API del reto (§9.4, §9.5, §11.2, RF-016, RF-018, RF-019, §18 «Deriva», E06), con el estilo de DISENO.md.

- Estado general con sus motivos y el error móvil de la ventana: WAPE, MAE y sesgo, y la cobertura del intervalo P10–P90,
  cada uno frente a los umbrales versionados que publica la API (GET /api/v1/monitoring, GET /api/v1/thresholds).
- Deriva de los datos: PSI de cada variable con su umbral de aviso y de alerta y su estado (siempre icono y palabra).
- Volumen de predicciones y porcentaje de alertas descartadas (posibles falsos positivos).
- La decisión de reentrenar con cada disparador, el retador en sombra y los cuatro criterios de su compuerta (o la última
  compuerta decidida) (GET /api/v1/monitoring/policy, GET /api/v1/models).
- Las últimas filas de monitoreo, una por ejecución.

Va en su propia pestaña: con once pestañas la barra compacta cabe a 1280 px (medido con Edge sin interfaz). Sin API, o
con una clave sin validez, la pantalla lo dice y no inventa nada: todas las cifras salen de la API."""
import dash
import pandas as pd
from dash import Input, Output, callback, ctx, dcc, html, no_update

import cliente_api as A
import ui

dash.register_page(__name__, path="/monitoreo", name="Monitoreo", order=9, title="Monitoreo · Sobusa Despacho")

FUENTES_MM = ["GET /api/v1/monitoring", "GET /api/v1/monitoring/policy", "GET /api/v1/models"]
# Estado del monitoreo y de la deriva: siempre icono y palabra (DISENO.md §6)
ESTADO_MON = {"ok": ("Sin novedad", "bien", None), "aviso": ("Aviso", "atencion", None), "alerta": ("Alerta", "critico", None),
              "sin_datos": ("Sin datos", None, "info")}
# Los nombres de las variables son los de la API (app/servicios/inferencia.py, DESCRIPCION_VARIABLES)
NOMBRE_VARIABLE = {"lag7": "La misma hora una semana antes", "b8": "La media de ocho semanas (regla manual)",
                   "m4": "La media de cuatro semanas", "sd8": "La variabilidad de ocho semanas",
                   "nivel_7_34": "El nivel de las cuatro semanas anteriores", "dia_lag7": "El total del día una semana antes",
                   "objetivo": "Pasajeros observados", "prediccion": "Pronóstico del modelo"}
ESTADO_SOMBRA = {"en_sombra": ("En sombra", None, "reloj"), "activado": ("Activado", "bien", None),
                 "aprobado": ("Aprobado", "bien", None), "rechazado": ("Rechazado", "critico", None),
                 "no_aplica": ("Sin sombra", None, "info")}


# --- Formato ----------------------------------------------------------------------------------------------------------
def hora_local(x):
    """Instante de la API en la hora de Bogotá."""
    t = pd.Timestamp(x)
    return t.tz_convert("America/Bogota") if t.tzinfo is not None else t


def fecha(x):
    if not x:
        return "—"
    t = hora_local(x)
    return f"{ui.fecha_corta(t)} {t.year}"


def chip(mapa, valor):
    texto, tipo, icono = mapa.get(valor, (valor or "—", None, "info"))
    return ui.chip(texto, tipo, icono)


def cabecera(titulo, subtitulo):
    return html.Header(html.Div([ui.cuadro("monitoreo", "panel", "cuadro-color--cabecera"),
                                 html.H1(titulo, className="cabecera__pregunta"),
                                 html.P(subtitulo, className="cabecera__subtitulo")], className="cabecera__texto"),
                       className="cabecera")


def aviso_api(err):
    """Aviso de la API caída o de la clave sin validez (401) o sin rol (403): título y qué hacer, nunca una traza."""
    return ui.aviso([err, A.ayuda_error(err)], "atencion", A.titulo_error(err), rol="status")


# --- Pantalla ---------------------------------------------------------------------------------------------------------
def layout(**_):
    return ui.pantalla([
        ui.arriba(cabecera("Monitoreo", "Si el modelo sigue acertando, si los datos cambiaron y cuándo reentrenar."),
                  [html.Div([ui.boton("Actualizar", id="mo-actualizar", icono="reloj", pequeno=True),
                             ui.boton("Exportar CSV", id="mo-csv", icono="descargar", pequeno=True),
                             ui.boton("Exportar XLSX", id="mo-xlsx", icono="descargar", pequeno=True)], className="botonera"),
                   dcc.Download(id="mo-descarga")],
                  html.Div([html.Div(id="mo-estado", **{"aria-live": "polite"}), html.Div(id="mo-export-aviso", **{"aria-live": "polite"})],
                           className="api-respuesta")),
        ui.seccion("Error y cobertura del modelo activo", html.Div(id="mo-cifras"),
                   subtitulo="Ventana móvil de la última ejecución, frente a los umbrales versionados de la API.",
                   fuentes=FUENTES_MM[:1] + ["GET /api/v1/thresholds"]),
        ui.seccion("Deriva y volumen", ui.rejilla([
            ui.tarjeta(html.Div(id="mo-psi"), titulo="Deriva de los datos (PSI por variable)",
                       subtitulo="Índice de estabilidad de cada variable frente a la referencia del modelo, con sus umbrales de "
                                 "aviso y de alerta.", fuentes=FUENTES_MM[:1], id="mo-tarjeta-psi"),
            ui.tarjeta(html.Div(id="mo-volumen"), titulo="Volumen y alertas descartadas",
                       subtitulo="Predicciones de la ejecución y de la ventana, y qué parte de las alertas se descartó.",
                       fuentes=FUENTES_MM[:1]),
        ], "2-1"), subtitulo="Un PSI alto dice que los datos de hoy ya no se parecen a los del entrenamiento."),
        ui.seccion("Aprendizaje continuo", ui.rejilla([
            ui.tarjeta(html.Div(id="mo-politica"), titulo="¿Hay que reentrenar?",
                       subtitulo="La decisión de la política con cada disparador, sus motivos y sus bloqueos.",
                       fuentes=FUENTES_MM[1:2]),
            ui.tarjeta(html.Div(id="mo-sombra"), titulo="Retador en sombra y su compuerta",
                       subtitulo="El candidato predice en paralelo; solo se activa si pasa los cuatro criterios.",
                       fuentes=FUENTES_MM[1:]),
        ], "1-1"), subtitulo="Cuándo se entrena un candidato, cómo se compara con el activo y quién decide su activación."),
        ui.seccion("Historial", ui.tarjeta(html.Div(id="mo-historial"), titulo="Últimas filas de monitoreo",
                                           subtitulo="Una por ejecución: error móvil, cobertura, sesgo, deriva máxima y estado.",
                                           fuentes=FUENTES_MM[:1]),
                   subtitulo="Lo que guarda la API en ai_frecuencias.model_monitoring en cada ejecución con datos nuevos."),
    ], "pantalla--api")

# --- Monitoreo del modelo (§9.4, RF-018, RF-019) -----------------------------------------------------------------------
def _es_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def pct(x, d=1):
    """Fracción de la API (0,8137) → «81,4 %»."""
    return f"{ui.num(x * 100, d)} %" if _es_num(x) else "—"


def _estado_umbral(x, alto=None, aviso=None, bajo=None, aviso_bajo=None, techo=None):
    """Estado de una métrica frente a los umbrales que publica la API: ok, aviso o alerta (mismo criterio que
    app/servicios/monitoreo.py: estado_de)."""
    if not _es_num(x):
        return "sin_datos"
    if (_es_num(alto) and x > alto) or (_es_num(bajo) and x < bajo):
        return "alerta"
    if (_es_num(aviso) and x > aviso) or (_es_num(aviso_bajo) and x < aviso_bajo) or (_es_num(techo) and x > techo):
        return "aviso"
    return "ok"


def _chip_mon(estado):
    return chip(ESTADO_MON, estado)


def _fichas_monitoreo(m, u):
    w, c, s = m.get("wape_movil"), m.get("cobertura_p10_p90"), m.get("sesgo_pct")
    ventana = f"{fecha(m.get('desde'))} a {fecha(m.get('hasta'))} · {ui.num(m.get('n_observaciones'))} horas observadas"
    umbral_w = " · ".join(x for x in (f"aviso > {pct(u.get('wape_aviso'))}" if _es_num(u.get("wape_aviso")) else None,
                                      f"máximo {pct(u.get('wape_max'))} (ALT-010)" if _es_num(u.get("wape_max")) else None) if x)
    umbral_c = (f"entre {pct(u.get('cobertura_aviso'), 0)} y {pct(u.get('cobertura_max'), 0)} · mínimo {pct(u.get('cobertura_min'), 0)}"
                if all(_es_num(u.get(k)) for k in ("cobertura_aviso", "cobertura_max", "cobertura_min")) else None)
    return ui.cifras([
        ui.cifra("WAPE móvil", pct(w), None, variacion=umbral_w or None, chip=_chip_mon(_estado_umbral(w, u.get("wape_max"), u.get("wape_aviso"))),
                 nota=ventana),
        ui.cifra("MAE móvil", ui.num(m.get("mae_movil"), 1), "pasajeros por hora", nota="Error absoluto medio de cada franja ruta-hora."),
        ui.cifra("Sesgo", f"{ui.con_signo(s * 100, 2)} %" if _es_num(s) else "—", None,
                 variacion=f"tolerancia ± {pct(u.get('sesgo_max'), 0)}" if _es_num(u.get("sesgo_max")) else None,
                 chip=_chip_mon(_estado_umbral(abs(s), u.get("sesgo_max")) if _es_num(s) else "sin_datos"),
                 nota="Suma de (pronóstico − real) sobre la suma de lo real: + sobrestima, − subestima."),
        ui.cifra("Cobertura P10–P90", pct(c), None, variacion=umbral_c,
                 chip=_chip_mon(_estado_umbral(c, bajo=u.get("cobertura_min"), aviso_bajo=u.get("cobertura_aviso"),
                                               techo=u.get("cobertura_max"))),
                 nota="Parte de lo observado dentro de la banda calibrada: debería rondar ocho de cada diez horas."),
    ])


def _tabla_psi(m):
    psi = m.get("psi") or {}
    if not psi:
        return ui.nota("La fila de monitoreo no trae PSI por variable.")
    filas = []
    for nombre, d in sorted(psi.items(), key=lambda kv: -(kv[1].get("psi") or 0)):
        filas.append([html.Span([html.Span(NOMBRE_VARIABLE.get(nombre, nombre)), html.Span(f" · {nombre}", className="api-tenue")]),
                      ui.num(d.get("psi"), 3), ui.num(d.get("umbral_aviso"), 3), ui.num(d.get("umbral_alerta"), 3),
                      _chip_mon(d.get("nivel")), "Sí" if d.get("dispara_reentreno") else "No (informativa)"])
    variable = m.get("psi_variable_max")
    return [ui.tabla(["Variable", "PSI", "Umbral de aviso", "Umbral de alerta", "Estado", "¿Dispara reentreno?"], filas,
                     compacta=True, num=[False, True, True, True, False, False], ocultar_movil=(2, 3, 5)),
            ui.nota(f"PSI máximo entre las que disparan reentreno: {ui.num(m.get('psi_max'), 3)} en "
                    f"{NOMBRE_VARIABLE.get(variable, variable or '—')}. Umbral efectivo = el mayor entre el fijo y el ruido "
                    "propio de la variable en su referencia.")]


def _volumen(m, u):
    tot, desc, p = m.get("alertas_total"), m.get("alertas_descartadas"), m.get("pct_descartadas")
    limite = u.get("descartadas_aviso")
    filas = [["Predicciones de la ejecución", ui.num(m.get("n_predicciones"))],
             ["Predicciones en la ventana", ui.num(m.get("predicciones_ventana"))],
             ["Horas observadas en la ventana", ui.num(m.get("n_observaciones"))],
             ["Alertas creadas en la ventana", ui.num(tot)],
             ["Alertas descartadas", ui.num(desc)]]
    return [ui.tabla(["Volumen", "Cantidad"], filas, compacta=True),
            ui.barra_rayas("Alertas descartadas (posibles falsos positivos)", pct(p), p or 0, "hoy"),
            ui.nota(f"Aviso si pasa de {pct(limite, 0)} con al menos {ui.num(u.get('descartadas_minimo'))} alertas."
                    if _es_num(limite) and _es_num(u.get("descartadas_minimo")) else
                    "La API avisa cuando la mayoría de las alertas de la ventana se descartan.")]


def _politica(pol, m=None):
    """La decisión de GET /monitoring/policy: ¿reentrenar?, con cada disparador, su regla y su valor de ahora."""
    d = (pol or {}).get("decision") or {}
    m = m or {}
    reentrenar = bool(d.get("reentrenar"))
    chips = [ui.chip("Reentrenar ahora", "atencion") if reentrenar else ui.chip("No hace falta reentrenar", "bien"),
             ui.chip_valor("Modelo activo:", d.get("modelo_activo") or "—"),
             ui.chip_valor("Datos hasta:", fecha(d.get("datos_hasta")) if d.get("datos_hasta") else "—")]
    u = d.get("umbrales") or {}
    dias = d.get("dias_desde_ultimo_entrenamiento")
    visto = f" (el último modelo ya vio datos hasta el {fecha(d.get('ultimo_dato_visto'))})" if d.get("ultimo_dato_visto") else ""
    filas = [["Periodicidad", f"cada {ui.num(u.get('reentreno_periodicidad_dias'))} días de datos nuevos"
              if _es_num(u.get("reentreno_periodicidad_dias")) else "—",
              (f"{ui.num(dias)} días" + visto) if _es_num(dias) else "—"],
             ["Degradación", f"WAPE móvil > {pct(u.get('wape_max'), 0)} en {ui.num(u.get('reentreno_dias_degradacion'))} ejecuciones seguidas"
              if _es_num(u.get("wape_max")) and _es_num(u.get("reentreno_dias_degradacion")) else "—",
              f"WAPE móvil {pct(m.get('wape_movil'))}" if _es_num(m.get("wape_movil")) else "—"],
             ["Deriva", "PSI en alerta en una variable que dispara reentreno",
              f"PSI máximo {ui.num(m.get('psi_max'), 3)} ({m.get('psi_variable_max') or '—'})" if _es_num(m.get("psi_max")) else "—"],
             ["Cobertura", f"cobertura P10–P90 < {pct(u.get('cobertura_min'), 0)}" if _es_num(u.get("cobertura_min")) else "—",
              f"cobertura {pct(m.get('cobertura_p10_p90'))}" if _es_num(m.get("cobertura_p10_p90")) else "—"]]
    partes = [html.Div(chips, className="api-chips"),
              ui.tabla(["Disparador", "Regla", "Ahora"], filas, compacta=True, num=[False, False, False])]
    motivos = [html.Li(x) for x in d.get("motivos") or []]
    bloqueos = [html.Li(x) for x in d.get("bloqueos") or []]
    partes.append(html.Div([html.P("Motivos", className="api-grupo__titulo"),
                            html.Ul(motivos, className="api-lista") if motivos else ui.nota("Ninguno: no se cumple ningún disparador.")]))
    if bloqueos:
        partes.append(html.Div([html.P("Bloqueos", className="api-grupo__titulo"), html.Ul(bloqueos, className="api-lista")]))
    if d.get("hasta"):
        partes.append(ui.nota(f"Si reentrena: corte de entrenamiento {fecha(d['hasta'])} y validación hasta {fecha(d.get('datos_hasta'))}."))
    return partes


def _sombra(pol, modelos, sombra_mon):
    en_sombra = (pol or {}).get("en_sombra") or []
    u = (pol or {}).get("umbrales") or {}
    partes = []
    if en_sombra:
        filas = []
        for c in en_sombra:
            s = c.get("sombra") or {}
            filas.append([c.get("model_id") or "—", chip(ESTADO_SOMBRA, s.get("estado")),
                          f"{fecha(s.get('inicio'))} → {fecha(s.get('fin'))}", ui.num(s.get("dias")), fecha(s.get("datos_hasta"))])
        partes.append(ui.tabla(["Retador", "Estado", "Sombra", "Días", "Datos hasta"], filas, compacta=True,
                               num=[False, False, False, True, False], ocultar_movil=(3, 4)))
    else:
        partes.append(ui.nota("No hay retador en sombra ahora."))
    if sombra_mon:
        m = sombra_mon
        partes.append(ui.nota(f"Último monitoreo del retador ({m.get('model_id')}, hasta {fecha(m.get('hasta'))}): WAPE {pct(m.get('wape_movil'))}, "
                              f"cobertura {pct(m.get('cobertura_p10_p90'))}, sesgo {pct(m.get('sesgo_pct'), 2)}."))
    criterios = ["WAPE del retador ≤ WAPE del activo en la misma ventana",
                 f"WAPE ≤ wape_max ({pct(u.get('wape_max'), 0)})" if _es_num(u.get("wape_max")) else "WAPE ≤ wape_max",
                 (f"Cobertura P10–P90 entre {pct(u.get('cobertura_aviso'), 0)} y {pct(u.get('cobertura_max'), 0)}"
                  if _es_num(u.get("cobertura_aviso")) and _es_num(u.get("cobertura_max")) else "Cobertura P10–P90 en su rango"),
                 f"|sesgo| ≤ sesgo_max ({pct(u.get('sesgo_max'), 0)})" if _es_num(u.get("sesgo_max")) else "|sesgo| ≤ sesgo_max"]
    decididos = [m for m in modelos or [] if (m.get("metricas") or {}).get("decision_sombra")]
    if decididos:
        m = decididos[0]
        comp = m["metricas"]["decision_sombra"]
        filas = [[c.get("criterio"), ui.chip("Cumple", "bien") if c.get("ok") else ui.chip("No cumple", "critico"),
                  pct(c.get("candidato"), 2) if _es_num(c.get("candidato")) else "—",
                  pct(c.get("referencia"), 2) if _es_num(c.get("referencia")) else
                  " a ".join(pct(x, 0) for x in c.get("referencia")) if isinstance(c.get("referencia"), list) else "—"]
                 for c in comp.get("criterios") or []]
        ventana = comp.get("ventana") or {}
        partes += [html.P(f"Última compuerta: {m.get('model_id')} · {fecha(ventana.get('desde'))} a {fecha(ventana.get('hasta'))}",
                          className="api-grupo__titulo"),
                   html.Div([ui.chip("Aprobada", "bien") if comp.get("aprobado") else ui.chip("Rechazada", "critico")], className="api-chips"),
                   ui.tabla(["Criterio", "Resultado", "Retador", "Referencia"], filas, compacta=True, num=[False, False, True, True])]
    else:
        partes += [html.P("Compuerta (al terminar la sombra)", className="api-grupo__titulo"),
                   html.Ol([html.Li(x) for x in criterios], className="api-lista"),
                   ui.nota("Si pasa los cuatro, se activa (activación automática) y se revierte solo si se degrada en sus primeros "
                           f"{ui.num(u.get('reversion_ventana_dias'))} días." if _es_num(u.get("reversion_ventana_dias")) else
                           "Si pasa los cuatro, se activa y queda auditado.")]
    return partes


def _historial_monitoreo(items):
    filas = [[fecha(m.get("hasta")), m.get("model_id") or "—", "Sombra" if m.get("rol") == "sombra" else "Activo", pct(m.get("wape_movil")),
              pct(m.get("cobertura_p10_p90")), f"{ui.con_signo((m.get('sesgo_pct') or 0) * 100, 2)} %" if _es_num(m.get("sesgo_pct")) else "—",
              f"{ui.num(m.get('psi_max'), 3)} · {m.get('psi_variable_max') or '—'}" if _es_num(m.get("psi_max")) else "—",
              _chip_mon(m.get("estado"))] for m in items]
    return ui.tabla(["Fin de la ventana", "Modelo", "Rol", "WAPE", "Cobertura", "Sesgo", "PSI máximo", "Estado"], filas, compacta=True,
                    num=[False, False, False, True, True, True, True, False], ocultar_movil=(1, 2, 5, 6))


@callback(Output("mo-estado", "children"), Output("mo-cifras", "children"), Output("mo-psi", "children"),
          Output("mo-volumen", "children"), Output("mo-politica", "children"), Output("mo-sombra", "children"),
          Output("mo-historial", "children"),
          Input("mo-actualizar", "n_clicks"))
def monitoreo_modelo(_clic):
    datos, err = A.obtener("monitoring", limite=10, orden="-creado_en")
    if err:
        return aviso_api(err), None, None, None, None, None, None
    items = datos.get("items") or []
    pol, err_p = A.obtener("monitoring/policy")
    u_thr, _err_u = A.obtener("thresholds")
    u = dict((pol or {}).get("umbrales") or {})
    u.update({k: v for k, v in ((u_thr or {}).get("valores") or {}).items() if _es_num(v)})
    activos = [m for m in items if m.get("rol") != "sombra"]
    sombra_mon = next((m for m in items if m.get("rol") == "sombra"), None)
    modelos, _err_m = A.obtener("models", limite=50, orden="-creado_en")
    m = activos[0] if activos else {}
    politica = aviso_api(err_p) if err_p else _politica(pol, m)
    sombra = aviso_api(err_p) if err_p else _sombra(pol, (modelos or {}).get("items"), sombra_mon)
    if not activos:
        nada = ui.aviso("La API todavía no tiene filas de monitoreo: se crean en cada ejecución de frecuencia con datos nuevos.",
                        None, "Sin monitoreo todavía", rol="status")
        return nada, None, None, None, politica, sombra, None
    motivos = m.get("motivos") or []
    estado = html.Div([
        html.Div([_chip_mon(m.get("estado")), ui.chip_valor("Modelo:", m.get("model_id") or "—"),
                  ui.chip_valor("Ventana:", f"{ui.num(m.get('ventana_dias'))} días hasta {fecha(m.get('hasta'))}"),
                  ui.chip_valor("Umbrales:", f"versión {ui.num(m.get('umbrales_version'))}" if m.get("umbrales_version") else "—")],
                 className="api-chips"),
        html.Ul([html.Li(x) for x in motivos], className="api-lista") if motivos else
        ui.nota("Sin motivos: el error, la cobertura, la deriva y las alertas descartadas están dentro de sus umbrales."),
    ], className="api-resumen")
    return (estado, _fichas_monitoreo(m, u), _tabla_psi(m), _volumen(m, u), politica, sombra, _historial_monitoreo(items))


# --- Exportación (RF-017): las mismas filas de monitoreo en CSV o XLSX, por el servidor del Dash (la clave no sale) -------
@callback(Output("mo-descarga", "data"), Output("mo-export-aviso", "children"),
          Input("mo-csv", "n_clicks"), Input("mo-xlsx", "n_clicks"), prevent_initial_call=True)
def exportar(_csv, _xlsx):
    if not ctx.triggered[0].get("value"):
        return no_update, no_update
    formato = "xlsx" if ctx.triggered_id == "mo-xlsx" else "csv"
    archivo, err = A.descargar("monitoring", formato, orden="-creado_en")
    if err:
        return no_update, ui.aviso(err, "atencion", "No se pudo exportar", rol="status")
    contenido, nombre = archivo
    return dcc.send_bytes(contenido, nombre), None
