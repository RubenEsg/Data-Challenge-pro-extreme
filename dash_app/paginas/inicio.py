"""Inicio: ¿Qué proponemos? Un tablero de tarjetas como la referencia (DISENO.md): arriba, la tarjeta protagonista con el
ahorro del plan que reasigna y sus dos saldos (datos/ahorro_anual.json) y, a su lado, las salidas que se mueven y la lectura
por tipo de día; debajo, cuánto se equivoca el pronóstico y cómo cambia el horario (datos/cifras_app.json). El botón «…» de
cada tarjeta guarda su tabla y sus fuentes. Ninguna cifra está escrita a mano."""
import dash
from dash import dcc, html

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
    """Tres fichas en el orden fijo (regla manual → modelo final → híbrido); la regla manual en gris tenue y el híbrido con
    «Recomendado para producción»."""
    b1 = D.valor("inicio", "inicio_error_regla_manual")
    e11 = D.valor("inicio", "inicio_error_modelo_final")
    e12 = D.valor("inicio", "inicio_error_hibrido")
    regla = D.valor("inicio", "inicio_regla_manual_definicion")
    pl = D.valor("modelo", "modelo_final_pliegues")
    hibrido = ui.cifra(ui.NOMBRE_MODELO["E12"], num(e12, 2), "%", variacion=f"{con_signo(e12 - e11, 2)} puntos frente al modelo final",
                       tono="bien", flecha=e12 - e11, nota="El mismo LightGBM con el pronóstico de Chronos-2 como variable.")
    # «Recomendado para producción» va al pie de su ficha: junto a la etiqueta se parte en dos líneas y desalinea los tres valores
    hibrido.children.append(html.Div(ui.chip("Recomendado para producción", "acento")))
    fichas = ui.cifras([
        ui.cifra(ui.NOMBRE_MODELO["B1"], num(b1, 2), "%", nota=regla[0].upper() + regla[1:], hoy=True),
        ui.cifra(ui.NOMBRE_MODELO["E11"], num(e11, 2), "%", variacion=f"{con_signo(e11 - b1, 2)} puntos frente a la regla manual",
                 tono="bien", flecha=e11 - b1, nota="LightGBM con calendario y demanda reciente."),
        hibrido,
    ], clase="cifras--3")
    nota = ui.nota(f"Pasajeros mal estimados de cada {CADA}, con una semana de antelación: error (WAPE) de 2025 en "
                   f"{num(pl['pliegues_mensuales_2025'])} pliegues mensuales y {num(pl['franjas_prueba'])} franjas de ruta, día y hora, "
                   "fuera de muestra. Las diferencias se calculan con las cifras sin redondear.")
    fuentes = _rutas(_archivo("inicio", "inicio_error_regla_manual"), _archivo("inicio", "inicio_error_modelo_final"),
                     _archivo("inicio", "inicio_error_hibrido"), _archivo("modelo", "modelo_final_pliegues"),
                     _archivo("inicio", "inicio_regla_manual_definicion"))
    return ui.tarjeta([fichas, nota], titulo="El pronóstico se equivoca menos",
                      subtitulo="Cuántos pasajeros mal estima cada forma de pronosticar la semana siguiente, de la regla manual "
                                "de hoy al híbrido recomendado.",
                      fuentes=fuentes, id="inicio-errores")


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


def layout(**_):
    A = D.ahorro_anual()
    b1 = D.valor("inicio", "inicio_error_regla_manual")
    e12 = D.valor("inicio", "inicio_error_hibrido")
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
                      f"pasajeros (la regla manual, en {num(b1)})."),
        # h2 solo para lectores de pantalla: las tarjetas llevan h3 y así no se salta de h1 a h3
        html.H2("Lo que cambia en un año", className="oculto"),
        ui.rejilla([_heroe(A, fuentes_heroe),
                    html.Div([_salidas(A, fuentes_salidas), _lectura(A)], className="rejilla")], "2-1", id="inicio-tablero"),
        _errores(),
        _forma(A, fuentes_forma),
        ui.seccion("Qué puedes hacer aquí", [ui.destinos([
            ui.destino("/pronostico", "pronostico", "Pronóstico",
                       "Elige ruta, día y modelo: pasajeros reales frente a pronosticados, hora por hora, y el error del día, la semana "
                       "y el mes."),
            ui.destino("/horario", "horario", "Horario",
                       "El optimizador corre en el momento: mueve el costo por bus-hora o cambia de modelo y mira cómo cambian las salidas."),
            ui.destino("/despacho", "despacho", "Despacho",
                       "Un día de 2025 repetido como si fuera hoy: el reloj avanza y la lista va diciendo qué bus salió, cuál sale "
                       "ahora y qué vehículos van en la calle."),
            ui.destino("/modelo", "modelo", "Modelo",
                       "Qué son el modelo final y el híbrido, con qué variables aprenden y cuánto se equivocan en 2025 y en 2024."),
            ui.destino("/resultado", "resultado", "Resultado",
                       "Cuánto se ahorra al año, dónde se mueven las salidas, qué se juega en pasajeros y qué pasaría si se recortara."),
        ])], "Aquí el pronóstico y el optimizador corren de verdad: tú eliges la ruta, el día, el modelo y los costos, y el "
             "horario se recalcula en un segundo.",
            intro="Un modelo pronostica cuántos pasajeros habrá en cada ruta y hora con una semana de antelación, y un "
                  "optimizador reparte las salidas: menos en el valle, más en los picos, con casi las mismas horas de bus."),
        ui.pie([
            html.P(["Cifras leídas de ", html.Code("datos/ahorro_anual.json"), " (lo escribe ", html.Code("preparar_datos.py"),
                    ") y de ", html.Code("datos/cifras_app.json"), " (copia de ", html.Code("app/datos_app.js"),
                    "): cada una trae su archivo y su clave de origen en el proyecto."]),
            html.P(f"Equipo: {_y(equipo)} · Universidad del Norte · Data Challenge Pro Extreme – Sobusa 2026."),
        ]),
    ])
