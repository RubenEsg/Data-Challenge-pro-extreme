"""Inicio: ¿Qué proponemos? Un tablero de tarjetas como la referencia (DISENO.md): arriba, la tarjeta protagonista con el
ahorro del plan que reasigna y sus dos saldos (datos/ahorro_anual.json) y, a su lado, las salidas que se mueven y la lectura
por tipo de día; debajo, cuánto se equivoca el pronóstico y cómo cambia el horario (datos/cifras_app.json). El botón «…» de
cada tarjeta guarda su tabla y sus fuentes. Ninguna cifra está escrita a mano.

La tarjeta «Respuesta a la pregunta del reto» lee GET /api/v1/respuesta de la API del reto (cliente_api.py): cada cuánto
despachar, cuántos pasajeros y vehículos se esperan, la flota y el recaudo, y lo que pide atención inmediata, con su
trazabilidad (modelo, versión de variables, corte de datos, umbrales y ejecución). Sin API, o con una clave sin validez,
la tarjeta lo dice y no inventa nada; el resto de Inicio sigue saliendo de datos/."""
import time

import dash
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

import cliente_api as API
import datos_app as D
import ui
from ui import con_signo, num

dash.register_page(__name__, path="/", name="Inicio", order=0, title="Inicio · Sobusa Despacho")

# Constantes de definición (DISENO.md §6.12): el error se lee «de cada 100 pasajeros» y β, «si se quitan 10 de cada 100 salidas»
CADA = 100
QUITA = 10
# Tipos de día de ahorro_anual.json, con su nombre en la frase
TIPOS_DIA = [("Laboral", "los días laborales"), ("Sábado", "los sábados"), ("Domingo/festivo", "los domingos y festivos")]
_LETRAS = ["ninguna", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"]


def _letras(n):
    """Un conteo en palabras (femenino: «tres rutas»), o en cifras si pasa de diez."""
    return _LETRAS[n] if 0 <= n < len(_LETRAS) else num(n)


def _y(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]


def _rutas(*grupos):
    """Rutas de archivo sin repetir y en orden, para el «…» de una tarjeta."""
    vistas = []
    for g in grupos:
        for r in ([g] if isinstance(g, str) else g):
            for a in str(r).split(";"):
                a = a.strip()
                if a and a not in vistas:
                    vistas.append(a)
    return vistas


def _de_ahorro(*claves):
    """Archivos del proyecto de donde salen esas cifras de ahorro_anual.json (las claves que no estén se ignoran)."""
    org = D.ahorro_anual()["origen"]
    return D.fuentes_ahorro(*[c for c in claves if c in org])


def _archivo(pantalla, clave):
    return D.cifra(pantalla, clave).get("archivo", "")


def _tipos_dia(A):
    """Salidas por día de cada tipo de día, hoy y con el plan que reasigna: (clave, nombre, hoy, plan, variación %)."""
    td = A["por_hora"]["tipos_dia"]
    filas = []
    for t, nombre in TIPOS_DIA:
        s = td[t]["salidas_dia"]
        filas.append((t, nombre, s["hoy"], s["reasigna"], (s["reasigna"] / s["hoy"] - 1) * 100))
    return filas


# --- Fila 1, tarjeta ancha: el ahorro con sus dos saldos (como «Gross Volume») -------------------------------------------
def _heroe(A, fuentes):
    """+501 M COP de ahorro en operación y, justo debajo de la línea, sus dos saldos (nunca va solo); después, de qué sale
    el ahorro, β y el enlace. Orden del DOM: título, valor, saldos, texto, β, enlace."""
    h, r = A["planes"]["hoy"], A["planes"]["reasigna"]
    b, conv = A["convenciones"]["beta"], A["convenciones"]
    semanas = D.valor("inicio", "inicio_piloto_resumen")["semanas"]
    rutas = D.valor("inicio", "inicio_rutas")
    costo_op = A["contexto"]["costo_operacion_anual_Mcop"]

    valor = html.Div(html.P([
        html.Span(con_signo(r["ahorro_operacion_Mcop"]), className="heroe__numero"),
        html.Span("M COP al año", className="heroe__unidad"),
        ui.chip_cambio(r["costo_km_conductor_Mcop"] - h["costo_km_conductor_Mcop"],
                       f"{con_signo(-r['ahorro_pct_costo'], 1)} % de costo"),
    ], className="heroe__valor"), className="heroe__principal")

    saldos = html.Div([
        ui.saldo("Saldo del año · contabilidad conservadora", r["saldo_conservador_Mcop"],
                 "Solo cuenta los pasajes que se pierden donde se quitan salidas: es el piso."),
        ui.saldo("Saldo del año · contabilidad simétrica", r["saldo_simetrico_Mcop"],
                 "También cuenta los que se ganan donde se ponen, con la misma β (que no se ha medido), y mide los perdidos "
                 "con una regla lineal: es el techo."),
    ], className="saldos")

    texto = (f"El ahorro es lo que Sobusa deja de pagar en kilómetros ({con_signo(r['ahorro_km_Mcop'])} M COP) y en horas de "
             f"conductor ({con_signo(r['ahorro_conductor_Mcop'])}, si al conductor se le paga {conv.get('pago_conductor', 'por hora')}): "
             f"lo que hoy cuestan los kilómetros y las horas de conductor pasa de {num(h['costo_km_conductor_Mcop'])} a "
             f"{num(r['costo_km_conductor_Mcop'])} M COP al año (de un costo de operación de {num(costo_op)} M COP al año), un "
             f"{num(r['ahorro_pct_costo'], 1)} % menos. No es ganancia: falta lo que se juega en pasajes.")
    beta = (f"β = {num(b['central'], 2)}: si se quitan {QUITA} de cada {CADA} salidas de una hora, se pierden "
            f"{num(b['central'] * QUITA)} de cada {CADA} pasajeros de esa hora (rango creíble: {num(b['bajo'], 2)} a "
            f"{num(b['alto'], 2)}). Cuál de los dos saldos se acerca más a la realidad lo mediría el piloto de {num(semanas)} semanas.")
    # De qué sale el ahorro, como las barras rayadas de la referencia: partes de un total positivo (si alguna fuera
    # negativa, no se dibujan: una barra nunca lleva un saldo con signo)
    partes = [("Ahorro en kilómetros", r["ahorro_km_Mcop"]), ("Ahorro en horas de conductor", r["ahorro_conductor_Mcop"])]
    total = r["ahorro_operacion_Mcop"]
    rayas = []
    if total > 0 and all(v >= 0 for _, v in partes):
        rayas = [html.Div([ui.barra_rayas(et, f"{con_signo(v)} M COP", v / total, "modelo") for et, v in partes],
                          className="rayas-lista")]
    pie = html.Div(rayas + [
        html.P(texto, className="heroe__texto"),
        ui.nota(beta),
        # El enlace en píldora blanca, como los botones de la referencia (sin subrayado; navega dentro de la app)
        html.Div(dcc.Link(["Ver qué gana Sobusa", ui.icono("chevron-derecha", "glifo--s")], href="/resultado",
                          className="boton boton--secundario"), className="botonera"),
    ], className="heroe__pie")

    tarjeta = ui.tarjeta([valor, saldos, pie], titulo="Ahorro en operación al año",
                         subtitulo=f"Plan que reasigna frente a hoy, en millones de pesos (M COP): {_letras(len(rutas))} rutas, "
                                   "salidas de 2025 y precios de 2026.",
                         fuentes=fuentes, clase="heroe cifra--hero", id="inicio-heroe")
    # La rejilla estira la tarjeta hasta el alto de la columna de al lado; .tarjeta lleva align-content: start en
    # estilos.css, así el espacio sobrante va al final y no entre la cifra y sus saldos.
    return tarjeta


# --- Fila 1, columna angosta: las salidas que se mueven y la lectura por tipo de día ---------------------------------------
def _salidas(A, fuentes):
    """«Salidas al año» como la tarjeta de la referencia: la cifra con su variación y dos barras rayadas (lo que se quita, en
    gris de hoy; lo que se pone, en azul del plan), con la tabla por tipo de día en el «…»."""
    h, r = A["planes"]["hoy"], A["planes"]["reasigna"]
    tope = max(r["quitadas_anio"], r["puestas_anio"]) or 1
    filas = [[t, num(s0, 1), num(s1, 1), f"{con_signo(v, 1)} %"] for t, _, s0, s1, v in _tipos_dia(A)]
    detalles = [ui.tabla(["Tipo de día", "Hoy", "Con el plan", "Cambio"], filas, compacta=True),
                ui.nota("Salidas por día, hoy → con el plan que reasigna (promedio de 2025).")]
    cuerpo = [
        ui.cifra("Plan que reasigna frente a hoy", con_signo(-r["menos_salidas_anio"]), "salidas",
                 variacion=f"{con_signo(r['var_salidas_pct'], 1)} % frente a hoy ({num(h['salidas_anio'])} → {num(r['salidas_anio'])})",
                 flecha=-r["menos_salidas_anio"], clase="cifra--llana"),
        html.Div([
            ui.barra_rayas("Quita", f"{num(r['quitadas_anio'])} al año ({num(r['quitadas_dia'], 1)} por día)",
                           r["quitadas_anio"] / tope, "hoy"),
            ui.barra_rayas("Pone", f"{num(r['puestas_anio'])} al año ({num(r['puestas_dia'], 1)} por día)",
                           r["puestas_anio"] / tope, "modelo"),
        ], className="rayas-lista"),
        ui.nota("Quita donde el pronóstico prevé buses más vacíos y pone donde los prevé más llenos: reasigna en vez de recortar."),
    ]
    return ui.tarjeta(cuerpo, titulo="Salidas al año", detalles=detalles, fuentes=fuentes, id="inicio-salidas")


def _lectura(A):
    """La tarjeta de lectura (degradado): el tipo de día que más cambia y, en el texto, los otros dos. El neto del año
    esconde que el plan pone salidas entre semana y las quita el fin de semana."""
    tipos = _tipos_dia(A)
    t, nombre, s0, s1, v = max(tipos, key=lambda f: abs(f[4]))
    verbo = (lambda x: "ganan" if x > 0 else "pierden" if x < 0 else "no cambian")
    otros = [f"{n} {verbo(x)} ({con_signo(x, 1)} %, {num(a, 1)} → {num(b_, 1)})" for _, n, a, b_, x in tipos if _ != t]
    titulo = f"{nombre[0].upper() + nombre[1:]} {verbo(v)} salidas: de {num(s0, 1)} a {num(s1, 1)} por día."
    texto = f"No es igual todos los días (salidas por día, hoy → con el plan): {_y(otros)}."
    return ui.tarjeta_insight(f"{con_signo(v, 1)} %", titulo, texto, chip_="Por tipo de día", id="inicio-lectura")


# --- Fila 2: el pronóstico se equivoca menos ------------------------------------------------------------------------------
def _errores():
    """El error del pronóstico del producto: la regla manual frente al modelo activo de la API en la prueba de nov–dic 2025,
    con su intervalo y la cobertura de su banda (datos/modelo_producto.json). Los experimentos del informe académico van
    aparte, en una nota que dice por qué sus cifras no se comparan con las del producto."""
    P = D.modelo_producto()
    b1 = D.valor("inicio", "inicio_error_regla_manual")
    e11 = D.valor("inicio", "inicio_error_modelo_final")
    e12 = D.valor("inicio", "inicio_error_hibrido")
    regla = D.valor("inicio", "inicio_regla_manual_definicion")
    pl = D.valor("modelo", "modelo_final_pliegues")
    fuentes_lab = _rutas(_archivo("inicio", "inicio_error_regla_manual"), _archivo("inicio", "inicio_error_modelo_final"),
                         _archivo("inicio", "inicio_error_hibrido"), _archivo("modelo", "modelo_final_pliegues"),
                         _archivo("inicio", "inicio_regla_manual_definicion"))
    laboratorio = ui.nota(
        f"En el informe académico, el experimento 11 (LightGBM) se equivoca en el {num(e11, 2)} % y el experimento 12 (híbrido), "
        f"en el {num(e12, 2)} % (la regla manual, {num(b1, 2)} %). No se comparan con las cifras de arriba: es otro protocolo "
        f"(pronóstico con una semana de antelación y WAPE sobre todo 2025, {num(pl['pliegues_mensuales_2025'])} pliegues "
        "mensuales). La API ejecuta el modelo activo; los experimentos quedan como laboratorio (Pronóstico y El modelo).")
    if not P:
        return ui.tarjeta([ui.aviso("Falta datos/modelo_producto.json (python preparar_datos.py --solo-producto).", "atencion",
                                    "Sin la ficha del modelo activo"), laboratorio],
                          titulo="El pronóstico se equivoca menos", fuentes=fuentes_lab, id="inicio-errores")
    ic = P["ic95_modelo"]
    dif = P["wape_modelo"] - P["wape_regla_manual"]
    fichas = ui.cifras([
        ui.cifra(ui.NOMBRE_MODELO["B1"], num(P["wape_regla_manual"], 2), "%", nota=regla[0].upper() + regla[1:], hoy=True),
        ui.cifra(ui.NOMBRE_PRODUCTO, num(P["wape_modelo"], 2), "%", variacion=f"{con_signo(dif, 2)} puntos frente a la regla manual",
                 tono="bien", flecha=dif, nota=f"{P['model_id']} · intervalo del 95 %: {num(ic[0], 2)} a {num(ic[1], 2)} %."),
        ui.cifra("Banda P10–P90 calibrada", num(P["cobertura_v2"], 2), "%",
                 nota=f"De lo real cae dentro de la banda (objetivo {num(P['cobertura_objetivo'])} %), con la calibración v2."),
    ], clase="cifras--3")
    nota = ui.nota(f"Pasajeros mal estimados de cada {CADA} en la prueba del {ui.fecha_corta(P['prueba']['desde'])} al "
                   f"{ui.fecha_corta(P['prueba']['hasta'])} de 2025 ({num(P['prueba']['franjas'])} franjas de ruta, día y hora). Es un "
                   "reporte informativo: esa prueba se consultó al elegir entre dos versiones de las variables; el criterio de selección "
                   "es la validación y los backtests congelados de 2024 y 2025, y se pidió a Extreme un periodo de 2026 como prueba limpia.")
    return ui.tarjeta([fichas, nota, laboratorio], titulo="El pronóstico se equivoca menos",
                      subtitulo="Cuántos pasajeros mal estima el modelo que ejecuta la API frente a la regla manual de hoy.",
                      fuentes=_rutas(D.fuentes_producto(), fuentes_lab), id="inicio-errores")


# --- Fila 2: el horario cambia de forma, no de tamaño ---------------------------------------------------------------------
def _forma(A, fuentes):
    """Dos antes → después (pasajeros por encima de la capacidad y espera), con chip de estado: el sentido es inequívoco."""
    h, r = A["planes"]["hoy"], A["planes"]["reasigna"]
    sc0, sc1 = h["pax_sobre_capacidad_dia"], r["pax_sobre_capacidad_dia"]
    es0, es1 = h["espera_min"], r["espera_min"]
    tono = (lambda d: "bien" if d < 0 else "critico" if d > 0 else None)
    cuerpo = ui.cambios([
        ui.antes_despues("Pasajeros por encima de la capacidad, por día", num(sc0), num(sc1),
                         ui.chip_cambio(sc1 - sc0, f"{con_signo(sc1 - sc0)} por día", tono(sc1 - sc0)),
                         "En el tramo más lleno de cada ruta, promedio de 2025."),
        ui.antes_despues("Espera media por pasajero, min", num(es0, 2), num(es1, 2),
                         ui.chip_cambio(es1 - es0, f"{con_signo(es1 - es0, 2)} min", tono(es1 - es0)),
                         f"Baja aun con {num(r['menos_salidas_anio'])} salidas menos al año ({con_signo(r['var_salidas_pct'], 1)} %)."),
    ])
    return ui.tarjeta(cuerpo, titulo="El horario cambia de forma, no de tamaño",
                      subtitulo="Casi las mismas salidas, puestas donde van los pasajeros: menos espera y menos gente apretada en "
                                "el tramo más lleno de cada hora. Aún falta un cupo por bus: seguido pasajero por pasajero, el "
                                "plan llena de más algunos buses.",
                      fuentes=fuentes, id="inicio-forma")


# --- La pregunta del reto, respondida por la API (GET /api/v1/respuesta) --------------------------------------------------
RUTAS_RESPUESTA = ["SILENCIO", "CRA 54", "CL 72"]
FUENTE_RESPUESTA = "GET /api/v1/respuesta"
MAX_ATENCION = 3
# §7.1: GET /respuesta solo lee la foto que dejó el ciclo; si no existe (404 «sin_calcular»), la tarjeta pide el cálculo
# con POST /respuesta/calcular (la clave del tablero es de analista) y vuelve a consultar cada ESPERA_S segundos, hasta TOPE_S
ESPERA_S = 3
TOPE_S = 60
FUENTE_PRONOSTICO = {"modelo_activo": "el pronóstico hora por hora del modelo activo",
                     "E12": "el pronóstico precalculado del experimento 12 del informe (opción, no el modelo activo)"}
NIVEL_ALERTA = {"critica": ("Crítica", "critico", None), "preventiva": ("Preventiva", "atencion", None),
                "informativa": ("Informativa", None, "info")}


def _es_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _min(x, d=1):
    return f"{num(x, d)} min" if _es_num(x) else "—"


def _hora(h):
    return f"{int(h):02d}:00" if _es_num(h) else str(h or "—")


def _instante(x):
    """ISO-8601 de la API (ya en -05:00) → «9 nov 2026 · 03:30» en la hora de Bogotá."""
    if not x:
        return "—"
    t = pd.Timestamp(x)
    t = t.tz_convert("America/Bogota") if t.tzinfo is not None else t
    return f"{ui.fecha_corta(t)} {t.year} · {t:%H:%M}"


def _dia(x):
    """Fecha de la API («2025-08-31» o un instante) → «31 ago 2025»."""
    if not x:
        return "—"
    t = pd.Timestamp(str(x)[:10])
    return f"{ui.fecha_corta(t)} {t.year}"


def _respuesta():
    """La tarjeta con la respuesta de la API a la pregunta final de la especificación; la llena el callback."""
    control = ui.fila_controles([ui.control("Ruta", ui.segmentado("in-resp-ruta", RUTAS_RESPUESTA, RUTAS_RESPUESTA[0],
                                                                  persistir=False)),
                                 html.Div([ui.boton("Exportar CSV", id="in-resp-csv", icono="descargar", pequeno=True),
                                           ui.boton("Exportar XLSX", id="in-resp-xlsx", icono="descargar", pequeno=True)],
                                          className="botonera"),
                                 dcc.Download(id="in-resp-descarga")])
    cuerpo = [control, html.Div(id="in-resp-export-aviso", **{"aria-live": "polite"}),
              dcc.Store(id="in-resp-calculo", data=None),
              dcc.Interval(id="in-resp-reloj", interval=ESPERA_S * 1000, disabled=True),
              html.Div(ui.nota("Consultando la API del reto…"), id="in-resp-cuerpo", **{"aria-live": "polite"})]
    return ui.tarjeta(cuerpo, titulo="Respuesta a la pregunta del reto",
                      subtitulo="La API del reto la responde con su modelo activo, el plan del día y las alertas abiertas: cada "
                                "cuánto despachar, cuántos pasajeros y vehículos, y qué pide atención inmediata.",
                      detalles=html.Div(ui.nota("Sin datos todavía."), id="in-resp-tabla"), fuentes=[FUENTE_RESPUESTA],
                      id="inicio-respuesta")


def _aviso_respuesta(err, codigo):
    if codigo == "sin_datos":
        return ui.aviso(err, None, "Todavía no hay plan para esa fecha", rol="status")
    if codigo == "no_encontrado":
        return ui.aviso([f"La API en {API.BASE} todavía no publica {FUENTE_RESPUESTA}.",
                         "Actualice la API a la versión de la entrega y vuelva a abrir Inicio; el resto de la pantalla sale de datos/."],
                        None, "La respuesta todavía no está en esta API", rol="status")
    return ui.aviso([err, API.ayuda_error(err)], "atencion", API.titulo_error(err), rol="status")


def _chip_nivel(sev):
    texto, tipo, icono = NIVEL_ALERTA.get(sev, (sev or "—", None, "info"))
    return ui.chip(texto, tipo, icono)


def _fichas_respuesta(r, fuente=None):
    res = r.get("resumen_despacho") or {}
    pax = r.get("pasajeros_esperados") or {}
    veh = r.get("vehiculos") or {}
    fr = r.get("flota_y_recaudo") or {}
    horas = r.get("cada_cuanto_despachar") or []
    pico = next((h for h in horas if h.get("hora") == res.get("hora_pico")), None) or {}
    programadas = res.get("salidas_dia_programadas")
    recomendadas = res.get("salidas_dia_recomendadas")
    dif = recomendadas - programadas if _es_num(recomendadas) and _es_num(programadas) else None
    recaudo, costo = fr.get("recaudo_esperado_cop"), fr.get("costo_operativo_cop")
    ahorro_vh = fr.get("vehiculos_hora_ahorrados")
    if _es_num(ahorro_vh):
        vh = (f"{num(abs(ahorro_vh), 1)} vehículos-hora {'menos' if ahorro_vh > 0 else 'más'} que lo programado."
              if ahorro_vh else "Los mismos vehículos-hora que lo programado.")
    else:
        vh = None
    return ui.cifras([
        ui.cifra(f"Despachar en la hora pico ({_hora(res.get('hora_pico'))})", f"cada {num(res.get('headway_pico_min'), 1)}", "min",
                 variacion=f"{num(recomendadas)} salidas en el día frente a {num(programadas)} programadas", flecha=dif,
                 nota=f"En el valle, cada {_min(res.get('headway_valle_min'))}; en la hora pico hoy se programa cada "
                      f"{_min(pico.get('headway_actual_min'))}."),
        ui.cifra("Pasajeros esperados en el día", num(pax.get("dia")), "pasajeros",
                 variacion=f"banda P10–P90: {num(pax.get('p10'))} a {num(pax.get('p90'))}",
                 nota=("Pronóstico precalculado del experimento 12 del informe (opción del plan), sumado hora por hora."
                       if fuente == "E12" else "Pronóstico del modelo activo, sumado hora por hora.")),
        ui.cifra(f"Vehículos en la hora pico ({_hora(veh.get('hora_pico'))})", num(veh.get("requeridos_pico")), "vehículos",
                 variacion=f"flota disponible: {num(veh.get('flota_disponible'))}" if _es_num(veh.get("flota_disponible")) else None,
                 tono=("bien" if veh.get("requeridos_pico") <= veh.get("flota_disponible") else "mal")
                 if _es_num(veh.get("requeridos_pico")) and _es_num(veh.get("flota_disponible")) else None,
                 nota="Máximo de buses en ruta a la vez con el plan del día."
                      + (f" Con lo programado hoy: {num(veh['requeridos_programados'])}." if _es_num(veh.get("requeridos_programados"))
                         else "")),
        ui.cifra("Recaudo esperado del día", num(recaudo / 1e6, 1) if _es_num(recaudo) else "—", "M COP",
                 variacion=f"costo operativo del plan: {num(costo / 1e6, 1)} M COP" if _es_num(costo) else None, nota=vh),
    ])


def _como_se_calcula(r):
    """Las notas largas de la API (vehículos, flota y recaudo) van plegadas debajo de las fichas, completas."""
    notas = [x for x in ((r.get("vehiculos") or {}).get("nota"), (r.get("flota_y_recaudo") or {}).get("nota")) if x]
    if not notas:
        return None
    return ui.desplegable("Cómo calcula la API los vehículos y el recaudo", [html.P(x, className="nota") for x in notas], llano=True)


def _atencion(r):
    alertas = r.get("atencion_inmediata") or []
    if not alertas:
        return ui.aviso("Ninguna alerta abierta de nivel crítico o preventivo para esta ruta.", "bien", "Nada pide atención inmediata",
                        rol="status")
    items = []
    for a in alertas[:MAX_ATENCION]:
        items.append(html.Div([html.Div([_chip_nivel(a.get("severidad")), ui.chip_valor("Código:", a.get("codigo") or "—"),
                                        ui.chip_valor("Detectada:", _instante(a.get("detectada_en")))], className="api-chips"),
                              html.P(a.get("explicacion") or "Sin explicación.", className="parrafo"),
                              html.P([html.Span("Qué hacer: ", className="api-tenue"), a.get("recomendacion") or "—"], className="nota")],
                             className="api-resumen"))
    resto = len(alertas) - MAX_ATENCION
    return [html.Div(items, className="api-resumen"),
            html.Div([ui.nota(f"Y {num(resto)} más en la bandeja." if resto > 0 else "Todas las de la ruta están arriba."),
                      ui.boton("Ir a Alertas", href="/alertas", icono="alerta", pequeno=True)], className="botonera")]


def _tabla_respuesta(r):
    """La tabla gemela del «…»: hora por hora, cada cuánto despachar frente a lo programado y los pasajeros esperados."""
    por_hora = {p.get("hora"): p for p in (r.get("pasajeros_esperados") or {}).get("por_hora") or []}
    filas = []
    for h in r.get("cada_cuanto_despachar") or []:
        p = por_hora.get(h.get("hora")) or {}
        filas.append([_hora(h.get("hora")), num(p.get("esperado")),
                      f"{num(p.get('p10'))} a {num(p.get('p90'))}" if _es_num(p.get("p10")) else "—",
                      _min(h.get("headway_min")), num(h.get("buses_hora")), _min(h.get("headway_actual_min")),
                      num(h.get("buses_hora_actual"), 1), "sí" if h.get("viable") else f"no · {h.get('motivo') or ''}".strip(" ·")])
    if not filas:
        return ui.nota("La API no trae el detalle por hora.")
    return ui.tabla(["Hora", "Pasajeros", "P10 a P90", "Cada cuánto", "Buses/h", "Programado", "Buses/h programados", "Viable"],
                    filas, compacta=True, num=[False, True, True, True, True, True, True, False])


def _traza(d, r):
    """La trazabilidad de la respuesta: modelo, calibración de la banda, fuente del pronóstico del plan, variables, corte,
    umbrales, ejecución y cuándo se generó (de la respuesta o de la ruta, lo que traiga la API)."""
    t = dict(d.get("trazabilidad") or {})
    for k, v in (r.get("trazabilidad") or {}).items():
        t.setdefault(k, v)
    fuente = t.get("fuente_pronostico") or r.get("fuente_pronostico")
    partes = (
        f"modelo {t.get('model_id')}" if t.get("model_id") else None,
        f"calibración de la banda {t.get('calibracion_version')}" if t.get("calibracion_version") else None,
        f"plan con {FUENTE_PRONOSTICO.get(fuente, fuente)}" if fuente else None,
        f"variables {t.get('feature_version')}" if t.get("feature_version") else None,
        f"corte de datos {_dia(t.get('data_cutoff'))}" if t.get("data_cutoff") else None,
        f"umbrales versión {num(t.get('umbrales_version'))}" if _es_num(t.get("umbrales_version")) else None,
        f"ejecución {str(t.get('execution_id'))[:8]}" if t.get("execution_id") else None,
        f"generada el {_instante(d.get('generado_en') or t.get('generado_en'))}"
        if d.get("generado_en") or t.get("generado_en") else None)
    return " · ".join(x for x in partes if x), t, fuente


def _cuerpo_respuesta(d, ruta):
    """La tarjeta llena con la respuesta de la API (y su tabla gemela del «…»)."""
    rutas = d.get("rutas") or []
    r = next((x for x in rutas if x.get("ruta") == ruta), rutas[0] if rutas else None)
    if r is None:
        return ui.aviso("La API respondió sin rutas.", None, "Sin respuesta para esa ruta", rol="status"), None
    traza, t, fuente = _traza(d, r)
    limitaciones = [html.Li(x) for x in d.get("limitaciones") or []]
    fecha_txt = ui.fecha_larga(d["fecha"]) if d.get("fecha") else "—"
    cuerpo = [
        html.P([html.Span("La pregunta: ", className="api-tenue"), d.get("pregunta") or "—"], className="parrafo"),
        html.Div([ui.chip_valor("Fecha del plan:", fecha_txt), ui.chip_valor("Tipo de día:", d.get("tipo_dia") or "—"),
                  ui.chip_valor("Ruta:", r.get("ruta") or ruta)], className="api-chips"),
        _fichas_respuesta(r, fuente),
        _como_se_calcula(r),
        html.Div([html.H4("Atención inmediata · alertas abiertas ahora", className="api-grupo__titulo"),
                  ui.nota("Las alertas críticas y preventivas que están abiertas en este momento en la API para la ruta, no "
                          "solo las del día del plan.")] + ui._lista(_atencion(r)), className="api-grupo"),
        ui.nota(f"Trazabilidad: {traza}." if traza else "La API no trajo la trazabilidad."),
    ]
    if limitaciones:
        cuerpo.append(ui.desplegable("Limitaciones que declara la API", html.Ul(limitaciones, className="api-lista"), llano=True))
    fuentes_api = [x for x in (t.get("fuentes") or []) if isinstance(x, str)]
    if fuentes_api:
        cuerpo.append(ui.fuentes([FUENTE_RESPUESTA] + fuentes_api))
    return html.Div([c for c in cuerpo if c is not None], className="api-resumen"), _tabla_respuesta(r)


def _calculando(ruta, calculo, segundos, progreso=""):
    eid = str(calculo.get("execution_id") or "")[:8]
    texto = (f"La API calcula la respuesta de {ruta} con el modelo activo" + (f" (ejecución {eid}{progreso})" if eid else "")
             + f". La tarjeta vuelve a consultar cada {num(ESPERA_S)} s, hasta {num(TOPE_S)} s; van {num(segundos)} s.")
    return ui.aviso(texto, None, "Calculando…", rol="status", id="in-resp-calculando")


def _pedir_calculo(ruta, detalle):
    """POST /respuesta/calcular (rol analista) → (dict con execution_id, error)."""
    cuerpo = {"rutas": [ruta]}
    fecha = (detalle or {}).get("fecha")
    if fecha:
        cuerpo["fecha"] = str(fecha)[:10]
    return API.enviar("POST", "respuesta/calcular", cuerpo)


@callback(Output("in-resp-cuerpo", "children"), Output("in-resp-tabla", "children"), Output("in-resp-reloj", "disabled"),
          Output("in-resp-calculo", "data"),
          Input("in-resp-ruta", "value"), Input("in-resp-reloj", "n_intervals"), State("in-resp-calculo", "data"))
def respuesta_reto(ruta, _n, calculo):
    """Lee la foto de la respuesta; si la API dice «sin_calcular», pide el cálculo una vez y consulta cada 3 s, hasta 60 s."""
    if ctx.triggered_id != "in-resp-reloj" or not calculo or calculo.get("ruta") != ruta:
        calculo = None
    d, err, codigo, detalle = API.obtener_con_detalle("respuesta", tiempo_espera=API.TIEMPO_RESPUESTA, ruta=ruta)
    if not err:
        cuerpo, tabla = _cuerpo_respuesta(d, ruta)
        return cuerpo, tabla, True, None
    if codigo != "sin_calcular":
        return _aviso_respuesta(err, codigo), ui.nota("Sin datos: la API no respondió."), True, None
    ahora = time.time()
    if calculo is None:
        pedido, err_p = _pedir_calculo(ruta, detalle)
        if err_p:
            return (ui.aviso([err, f"Al pedir el cálculo (POST /respuesta/calcular): {err_p}", API.ayuda_error(err_p)],
                             "atencion", "La respuesta todavía no está calculada", rol="status"),
                    ui.nota("Sin datos: la respuesta no está calculada."), True, None)
        calculo = {"ruta": ruta, "inicio": ahora, "execution_id": (pedido or {}).get("execution_id")}
    segundos = ahora - calculo["inicio"]
    if segundos >= TOPE_S:
        eid = str(calculo.get("execution_id") or "")[:8]
        return (ui.aviso(f"La API no terminó el cálculo de {ruta} en {num(TOPE_S)} s" + (f" (ejecución {eid}, sigue en la cola)"
                         if eid else "") + ". Vuelva a abrir Inicio en un momento: la respuesta queda guardada cuando termine.",
                         "atencion", "El cálculo tarda más de lo previsto", rol="status"),
                ui.nota("Sin datos todavía."), True, None)
    progreso = ""
    if calculo.get("execution_id"):
        e, _e = API.obtener(f"frequency/executions/{calculo['execution_id']}")
        if e and e.get("estado") in ("error", "fallida", "cancelada"):
            return (ui.aviso(f"La ejecución {str(calculo['execution_id'])[:8]} terminó en «{e.get('estado')}»: "
                             f"{e.get('mensaje') or 'sin mensaje'}.", "atencion", "No se pudo calcular la respuesta", rol="status"),
                    ui.nota("Sin datos."), True, None)
        if e:
            progreso = f" · {str(e.get('etapa') or e.get('estado') or '—').replace('_', ' ')}"
    return _calculando(ruta, calculo, segundos, progreso), ui.nota("Calculando…"), False, calculo



@callback(Output("in-resp-descarga", "data"), Output("in-resp-export-aviso", "children"),
          Input("in-resp-csv", "n_clicks"), Input("in-resp-xlsx", "n_clicks"), State("in-resp-ruta", "value"),
          prevent_initial_call=True)
def exportar_respuesta(_csv, _xlsx, ruta):
    """La respuesta por ruta y hora en CSV o XLSX (GET /api/v1/respuesta/export), por el servidor del Dash."""
    if not ctx.triggered[0].get("value"):
        return no_update, no_update
    formato = "xlsx" if ctx.triggered_id == "in-resp-xlsx" else "csv"
    archivo, err = API.descargar("respuesta", formato, ruta=ruta)
    if err:
        return no_update, ui.aviso(err, "atencion", "No se pudo exportar", rol="status")
    contenido, nombre = archivo
    return dcc.send_bytes(contenido, nombre), None

def layout(**_):
    A = D.ahorro_anual()
    P = D.modelo_producto()
    b1 = P.get("wape_regla_manual", D.valor("inicio", "inicio_error_regla_manual"))
    e12 = P.get("wape_modelo", D.valor("inicio", "inicio_error_hibrido"))
    equipo = D.valor("inicio", "inicio_equipo")

    fuentes_heroe = _rutas("datos/ahorro_anual.json", _de_ahorro(
        "planes.reasigna.ahorro_operacion_Mcop", "planes.reasigna.ahorro_km_Mcop", "planes.reasigna.ahorro_conductor_Mcop",
        "planes.hoy.costo_km_conductor_Mcop", "planes.reasigna.costo_km_conductor_Mcop", "planes.reasigna.saldo_conservador_Mcop",
        "planes.reasigna.saldo_simetrico_Mcop", "contexto.costo_operacion_anual_Mcop", "convenciones.beta.central"),
        _archivo("inicio", "inicio_piloto_resumen"))
    fuentes_salidas = _rutas("datos/ahorro_anual.json", _de_ahorro(
        "planes.hoy.salidas_anio", "planes.reasigna.salidas_anio", "planes.reasigna.quitadas_anio", "planes.reasigna.puestas_anio",
        "por_hora.tipos_dia.Laboral.salidas_dia.reasigna"))
    fuentes_forma = _rutas("datos/ahorro_anual.json", _de_ahorro(
        "planes.hoy.pax_sobre_capacidad_dia", "planes.reasigna.pax_sobre_capacidad_dia", "planes.hoy.espera_min",
        "planes.reasigna.espera_min"))

    return ui.pantalla([
        ui.encabezado("¿Qué proponemos?",
                      f"No quitar buses: cambiarlos de hora, con un pronóstico que se equivoca en {num(e12)} de cada {CADA} "
                      f"pasajeros (la regla manual, en {num(b1)})" + (" en la prueba de nov–dic 2025." if P else ".")),
        # h2 solo para lectores de pantalla: las tarjetas llevan h3 y así no se salta de h1 a h3
        html.H2("Lo que cambia en un año", className="oculto"),
        ui.rejilla([_heroe(A, fuentes_heroe),
                    html.Div([_salidas(A, fuentes_salidas), _lectura(A)], className="rejilla")], "2-1", id="inicio-tablero"),
        _respuesta(),
        _errores(),
        _forma(A, fuentes_forma),
        ui.seccion("Qué puedes hacer aquí", [ui.destinos([
            ui.destino("/pronostico", "pronostico", "Pronóstico",
                       "Los pronósticos que guarda la API con su banda P10–P90 frente a lo real y por qué sale cada uno; aparte, el "
                       "laboratorio del informe académico."),
            ui.destino("/horario", "horario", "Horario",
                       "El optimizador corre en el momento: mueve el costo por bus-hora o cambia de modelo y mira cómo cambian las salidas."),
            ui.destino("/despacho", "despacho", "Despacho",
                       "Un día de 2025 repetido como si fuera hoy: el reloj avanza y la lista va diciendo qué bus salió, cuál sale "
                       "ahora y qué vehículos van en la calle."),
            ui.destino("/modelo", "modelo", "Modelo",
                       "El modelo activo de la API: cuánto se equivoca, su banda calibrada y qué variables pesan; aparte, los "
                       "experimentos del informe académico."),
            ui.destino("/resultado", "resultado", "Resultado",
                       "Cuánto se ahorra al año, dónde se mueven las salidas, qué se juega en pasajeros y qué pasaría si se recortara."),
        ])], "Aquí el pronóstico y el optimizador corren de verdad: tú eliges la ruta, el día, el modelo y los costos, y el "
             "horario se recalcula en un segundo.",
            intro="El modelo activo de la API pronostica cuántos pasajeros habrá en cada ruta y hora, con su banda P10–P90, y "
                  "un optimizador reparte las salidas: menos en el valle, más en los picos, con casi las mismas horas de bus."),
        ui.pie([
            html.P(["Cifras leídas de ", html.Code("datos/ahorro_anual.json"), " (lo escribe ", html.Code("preparar_datos.py"),
                    ") y de ", html.Code("datos/cifras_app.json"), " (copia de ", html.Code("app/datos_app.js"),
                    "): cada una trae su archivo y su clave de origen en el proyecto."]),
            html.P(f"Equipo: {_y(equipo)} · Universidad del Norte · Data Challenge Pro Extreme – Sobusa 2026."),
        ]),
    ])
