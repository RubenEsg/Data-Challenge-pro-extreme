"""El modelo: ficha del modelo final (E11, LightGBM V4) y del híbrido (E12, V4 + Chronos-2), desde datos/ficha_modelos.json y
datos/cifras_app.json (DISENO.md §8). Tablero como la referencia: el error de cada uno con la lectura al lado, las dos fichas,
las variables que pesan más (barras rayadas) y por qué se recomienda el híbrido."""
import dash
import plotly.graph_objects as go
from dash import html

import datos_app as D
import ui
from ui import NOMBRE_MODELO, con_signo, num

dash.register_page(__name__, path="/modelo", name="El modelo", order=3, title="El modelo · Sobusa Despacho")

NOMBRES_VAR = {
    "pasajeros_total_m4sem": "Media de las 4 mismas semanas anteriores",
    "pasajeros_total_b1": "Regla manual (8 semanas)",
    "tipo_dia": "Tipo de día", "festivo": "Festivo", "hora": "Hora de salida", "dia_anio": "Día del año",
    "pasajeros_total_roll7_h7": "Media de 7 días (hace una semana)",
    "pasajeros_total_lag7": "Pasajeros hace 7 días", "pasajeros_total_lag14": "Pasajeros hace 14 días",
    "pasajeros_total_lag364": "Pasajeros hace un año", "viajes_validos_m4sem": "Salidas: media de 4 semanas",
    "pasajeros_total_roll28_h7": "Media de 28 días", "pasajeros_total_sd8sem": "Variabilidad de 8 semanas",
    "carnaval_central": "Carnaval (lunes y martes)", "carnaval": "Carnaval", "viajes_validos_b1": "Salidas: regla manual",
    "vac_escolar": "Vacaciones escolares", "viajes_validos_roll28_h7": "Salidas: media de 28 días", "semana_santa": "Semana Santa",
    "dia_semana": "Día de la semana", "tendencia": "Tendencia", "semana_anio": "Semana del año",
    "fm_c2": "Chronos‑2: pronóstico (mediana)", "fm_c2_q10": "Chronos‑2: cuantil 10", "fm_c2_q90": "Chronos‑2: cuantil 90",
    "fm_c2_ratio": "Chronos‑2 / media de 4 semanas",
}
N_VARIABLES = 8          # variables que se muestran en cada tarjeta de importancia
# px: el lienzo más alto en que se dibuja el gráfico de errores (DISENO.md §7), para que ui.ancho_barra no pase de 24 px.
ALTO_BAJO = 260
FUENTES_ERROR = ["datos/cifras_app.json", "experimentos/E11_modelo_mejorado/resultados.json",
                 "experimentos/E12_comparacion_modelos/resultados.json"]
FUENTES_FICHA = ["datos/ficha_modelos.json (app/ficha_modelos.json)", "datos/cifras_app.json",
                 "experimentos/E11_modelo_mejorado", "experimentos/E12_comparacion_modelos"]
FUENTES_IMP = ["datos/cifras_app.json (modelo_final_importancia)", "datos/ficha_modelos.json (importancia del híbrido)",
               "experimentos/E11_modelo_mejorado/modelos/metadatos.json"]


def _antelacion():
    """Días de antelación de la evaluación (el horizonte más corto de cifras_app.json) y su nombre."""
    h = int(min(D.valor("demanda", "demanda_wape_antelacion")["E11_V4"], key=int))
    return h, ("una semana" if h == 7 else f"{h} días")


def _partir(texto, largo=26):
    """Rótulo largo del eje en dos líneas, cortado en el espacio más cercano a la mitad: a 400 px no se corta."""
    cortes = [i for i, ch in enumerate(texto) if ch == " "]
    if len(texto) <= largo or not cortes:
        return texto
    i = min(cortes, key=lambda c: abs(c - len(texto) // 2))
    return texto[:i] + "<br>" + texto[i + 1:]


def _errores_fig(nombres, vals):
    """Barras horizontales del error de 2025 en el orden fijo: las referencias rayadas en gris; nuestros modelos en azul,
    el modelo final rayado y el híbrido (el recomendado) sólido, como la columna en foco de la referencia."""
    ys = [_partir(n) for n in nombres]
    ancho = ui.ancho_barra(len(nombres), ALTO_BAJO)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=vals[:2], y=ys[:2], orientation="h", name="Referencias", **ui.traza("hoy", "rayada", ancho=ancho),
                         text=[f"{num(v, 2)} %" for v in vals[:2]], **ui.hover("", vals[:2], "%", 2, categorias=nombres[:2])))
    fig.add_trace(go.Bar(x=vals[2:], y=ys[2:], orientation="h", name="Nuestros modelos", **ui.barras_foco("modelo", ys[2:], foco=ys[3], ancho=ancho),
                         text=[f"{num(v, 2)} %" for v in vals[2:]], **ui.hover("", vals[2:], "%", 2, categorias=nombres[2:])))
    fig.update_layout(barmode="overlay", hovermode="closest", showlegend=False,
                      margin=dict(l=ui.px("--e-1"), r=ui.MARGEN_ETIQUETAS, t=ui.px("--e-1"), b=ui.px("--e-1")))
    fig.update_xaxes(visible=False, range=[0, max(vals) * 1.05])
    fig.update_yaxes(autorange="reversed", showgrid=False, categoryorder="array", categoryarray=ys,
                     tickfont=ui.fuente_svg("tinta_2"), ticklabelstandoff=ui.px("--e-2"))
    return fig


def _importancia(clave, imp, h):
    """Tarjeta de las variables con más peso: barras rayadas en azul (partes del 100 % de la importancia) con el valor a la
    derecha; la tabla gemela y las fuentes van en el «…»."""
    items = sorted(imp.items(), key=lambda kv: kv[1], reverse=True)[:N_VARIABLES]
    nombres = [NOMBRES_VAR.get(k, k) for k, _ in items]
    valores = [v for _, v in items]
    corto = "el híbrido" if clave == "E12" else "el modelo final"
    titulo = f"En {corto} pesa más «{nombres[0]}» ({num(valores[0], 1)} %)"
    sub = (f"{NOMBRE_MODELO[clave]}: las {len(items)} variables con más peso, en % de la importancia de los árboles (cuánto "
           f"reduce el error cada variable; modelo de producción con {h} días de antelación).")
    tabla = ui.tabla(["Variable", "Peso (% de la importancia)"], [[n, f"{num(v, 1)} %"] for n, v in zip(nombres, valores)], compacta=True)
    barras = html.Div([ui.barra_rayas(n, f"{num(v, 1)} %", v / 100, "modelo") for n, v in zip(nombres, valores)], className="rayas-lista")
    return ui.tarjeta(barras, titulo=titulo, subtitulo=sub, detalles=tabla, fuentes=FUENTES_IMP)


def _resumen(M, w25, b1):
    """El resumen de la ficha; en el modelo final, su última frase se arma con los datos para que «de cada 100» vaya con
    enteros, como en el resto de la pantalla."""
    texto = M["resumen_para_jurado"]
    corte = texto.find(" Se equivoca en ")
    if corte > 0 and b1 is not None:
        texto = texto[:corte] + f" Se equivoca en {num(w25)} de cada 100 pasajeros a una semana; la regla manual de Sobusa, en {num(b1)}."
    return texto


def _tarjeta_modelo(M, rol, chip, w25, w24, sesgo, n_var, nota_var, pliegues, h, b1=None):
    hijos = []
    if chip:
        hijos.append(html.Div(ui.chip("Recomendado para producción", "acento"), className="chips"))
    hijos += [
        ui.parrafo(_resumen(M, w25, b1)),
        ui.cifras([
            ui.cifra("Error en 2025", num(w25, 2), "%", nota=f"WAPE, {pliegues} pliegues, h = {h} días", mini=True),
            ui.cifra("Error en 2024", num(w24, 2), "%", nota="Prueba fuera de la muestra de selección", mini=True),
            ui.cifra("Sesgo", con_signo(sesgo, 2), "%", nota="Del total de pasajeros de 2025", mini=True),
            ui.cifra("Variables", num(n_var), None, nota=nota_var, mini=True),
        ]),
    ]
    return ui.tarjeta(hijos, titulo=M["nombre"], subtitulo=rol,
                      detalles=[html.P("Qué es, con más detalle", className="mas__titulo"), ui.parrafo(M["que_es"]["texto"])],
                      fuentes=FUENTES_FICHA)


def layout(**_):
    F = D.ficha_modelos()
    M11, M12 = F["modelos"]["E11_V4"], F["modelos"]["E12_hibrido"]
    w25_11 = D.valor("inicio", "inicio_error_modelo_final")
    w25_12 = D.valor("inicio", "inicio_error_hibrido")
    w24_11 = D.valor("modelo", "modelo_final_2024")
    h24 = D.valor("modelo", "modelo_hibrido_wape_2024")
    h25 = D.valor("modelo", "modelo_hibrido_wape_2025")
    sesgo = D.valor("modelo", "modelo_hibrido_sesgo")
    imp11 = D.valor("modelo", "modelo_final_importancia")
    imp12 = M12["variables"]["importancia_modelo_final_H7"]["top"]
    b1 = D.valor("inicio", "inicio_error_regla_manual")
    e1 = D.valor("inicio", "inicio_error_e1")
    por_que = D.valor("modelo", "modelo_por_que_hibrido")
    meses_25 = M12["errores"]["frente_a_V4_2025"]["meses_mejor"]
    s11 = M11["errores"]["global_h7"]["sesgo_pct"]["valor"]
    pl = D.valor("modelo", "modelo_final_pliegues")
    pliegues, franjas = pl["pliegues_mensuales_2025"], pl["franjas_prueba"]
    n11, n12 = M11["variables"]["total"]["valor"], M12["variables"]["total"]["valor"]
    h, antelacion = _antelacion()
    dif25 = D.valor("inicio", "inicio_mejora_hibrido_2025")

    cabecera = ui.cabecera("modelo", "¿Qué modelo es y por qué?",
                           f"El híbrido (E12) se equivoca en el {num(w25_12, 2)} % de los pasajeros de 2025, y el modelo final "
                           f"(E11), en el {num(w25_11, 2)} %" + ("; el híbrido vuelve a ganar en 2024." if h24["dif"] < 0 else "."))

    # --- cuánto se equivoca cada uno: orden fijo; referencias rayadas en gris, el modelo final rayado y el híbrido sólido --
    nombres = [NOMBRE_MODELO[m] for m in ui.ORDEN_MODELOS]
    vals = [b1, e1, w25_11, w25_12]
    errores = ui.grafico(
        _errores_fig(nombres, vals),
        titulo=f"El híbrido se equivoca en {num(w25_12)} de cada 100 pasajeros; la regla manual, en {num(b1)}",
        subtitulo=f"Pasajeros mal estimados de cada 100 en 2025 (WAPE), con {antelacion} de antelación. Menos es mejor. El mismo "
                  "protocolo para todos: cada mes de 2025 se pronosticó con lo anterior a ese mes.",
        etiqueta="Error de 2025 (WAPE): " + "; ".join(f"{n}, {num(v, 2)} %" for n, v in zip(nombres, vals)) + ".",
        tabla=(["Modelo", "Error en 2025 (WAPE)"], [[n, f"{num(v, 2)} %"] for n, v in zip(nombres, vals)]),
        leyenda=[("Híbrido (E12), el recomendado", "modelo", "foco"), ("Modelo final (E11)", "modelo", "rayada"),
                 ("Referencias: la regla manual de hoy y el primer modelo", "hoy", "rayada")],
        nota=f"WAPE de 2025 en {num(franjas)} franjas de ruta, día y hora, {pliegues} pliegues mensuales, fuera de muestra.",
        alto="bajo", fuentes=FUENTES_ERROR)

    lectura = ui.tarjeta_insight(
        con_signo(dif25, 2), "puntos de error del híbrido frente al modelo final en 2025",
        f"En 2024, un año que no se usó para escogerlo, vuelve a bajar: {con_signo(h24['dif'], 2)} puntos. Es la única mejora "
        "frente al modelo final que se confirmó fuera de la muestra de selección.")

    modelos = ui.rejilla([
        _tarjeta_modelo(M11, "Respaldo en producción (modelo_final.py)", False, w25_11, w24_11, s11, n11,
                        "Calendario, demanda y oferta rezagadas", pliegues, h, b1=b1),
        _tarjeta_modelo(M12, "Pipeline de producción: modelo_final_hibrido.py", True, w25_12, h24["WAPE_hibrido"], sesgo["2025_pct"],
                        n12, f"Las {num(n11)} del modelo final y {num(n12 - n11)} de Chronos‑2", pliegues, h),
    ], "1-1")

    importancia = ui.rejilla([_importancia("E11", imp11, h), _importancia("E12", imp12, h)], "1-1")

    por_que = ui.tarjeta([
        ui.aviso(f"El híbrido añade una pieza al modelo final: Chronos-2. Si Chronos-2 falla, el modelo final de E11 sigue "
                 f"entrenado al lado como respaldo.", "canje", "Una pieza más, con respaldo"),
        ui.cifras([
            ui.cifra("Error frente al modelo final, 2025", con_signo(dif25, 2), "puntos", variacion="Baja el error", tono="bien",
                     flecha=dif25, nota=f"Intervalo del 95 %: {con_signo(h25['ic_inf'], 2)} a {con_signo(h25['ic_sup'], 2)}; "
                                        f"mejor en {meses_25}."),
            ui.cifra("Error frente al modelo final, 2024", con_signo(h24["dif"], 2), "puntos", variacion="Baja el error", tono="bien",
                     flecha=h24["dif"], nota=f"Intervalo del 95 %: {con_signo(h24['ic_inf'], 2)} a {con_signo(h24['ic_sup'], 2)}; "
                                            f"mejor en {h24['meses_mejor']} de {h25['meses']} meses."),
        ]),
        ui.parrafo("Es la única mejora frente al modelo final que se confirmó fuera de la muestra con la que se eligió: baja el error "
                   "en 2025 y vuelve a bajarlo en 2024, un año que no se usó para escogerlo. Cuesta casi lo mismo que el modelo final "
                   "y corre sin GPU. Otros candidatos de E12 rindieron igual con más piezas y más sesgo, o no repitieron su ventaja "
                   "en 2024."),
        ui.desplegable("Motivo tal como lo dejó E12", ui.parrafo(por_que), llano=True),
    ], titulo="Por qué se recomienda el híbrido", subtitulo="La única mejora que se sostuvo fuera de la muestra de selección.",
        fuentes=["datos/cifras_app.json (modelo_hibrido_wape_2025, modelo_hibrido_wape_2024, modelo_por_que_hibrido)",
                 "experimentos/E12_comparacion_modelos/resultados.json"])

    return ui.pantalla([
        ui.arriba(cabecera),
        # h2 solo para lectores de pantalla (h1 → h2 → h3 sin saltos); las tarjetas ya llevan su título visible
        html.Section([html.H2("Cuánto se equivoca cada uno", className="oculto"), ui.rejilla([errores, lectura], "2-1")]),
        html.Section([html.H2("Los dos modelos", className="oculto"), modelos]),
        html.Section([html.H2("Qué variables pesan más", className="oculto"), importancia]),
        html.Section([html.H2("La recomendación", className="oculto"), por_que]),
    ])
