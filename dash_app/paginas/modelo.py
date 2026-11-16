"""El modelo: primero el modelo del PRODUCTO, el que ejecuta la API (datos/modelo_producto.json y, en vivo, GET
/api/v1/models/{id}/importance); después, en su propia sección rotulada, los experimentos del informe académico
(experimento 11: LightGBM V4; experimento 12: V4 + Chronos-2), desde datos/ficha_modelos.json y datos/cifras_app.json
(DISENO.md §8). Las cifras de los dos no se comparan: son otro protocolo, y la pantalla lo dice."""
import re

import dash
import plotly.graph_objects as go
from dash import Input, Output, callback, html

import cliente_api as API
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
# Variables del modelo activo (fv2), con las mismas descripciones que usa la API en sus explicaciones
NOMBRES_FV2 = {
    "b8": "Media de 8 semanas (regla manual)", "m4": "Media de 4 semanas", "lag7": "La misma hora hace 7 días",
    "lag14": "La misma hora hace 14 días", "sd8": "Variabilidad de 8 semanas", "nivel_7_13": "Nivel de la semana anterior",
    "nivel_7_34": "Nivel de las 4 semanas anteriores", "dia_lag7": "Total del día hace 7 días", "hora": "Hora",
    "dia_semana": "Día de la semana", "mes": "Mes", "ruta_cod": "Ruta", "tipo_dia": "Tipo de día", "festivo": "Festivo",
    "carnaval": "Carnaval", "semana_santa": "Semana Santa", "vacaciones": "Vacaciones", "navidad": "Navidad",
    "primero_enero": "Primero de enero", "nov_impacto": "Novedad vial (% de impacto)", "nov_sube": "Novedad marcada SUBE",
    "vispera_festivo": "Víspera de festivo", "post_festivo": "Día posterior a festivo",
}
N_VARIABLES = 8          # variables que se muestran en cada tarjeta de importancia
# px: el lienzo más alto en que se dibuja el gráfico de errores (DISENO.md §7), para que ui.ancho_barra no pase de 24 px.
ALTO_BAJO = 260
FUENTES_ERROR = ["datos/cifras_app.json", "experimentos/E11_modelo_mejorado/resultados.json",
                 "experimentos/E12_comparacion_modelos/resultados.json"]
FUENTES_FICHA = ["datos/ficha_modelos.json (app/ficha_modelos.json)", "datos/cifras_app.json",
                 "experimentos/E11_modelo_mejorado", "experimentos/E12_comparacion_modelos"]
FUENTES_IMP = ["datos/cifras_app.json (modelo_final_importancia)", "datos/ficha_modelos.json (importancia del experimento 12)",
               "experimentos/E11_modelo_mejorado/modelos/metadatos.json"]
FUENTE_IMP_API = "GET /api/v1/models/{id}/importance (media de |SHAP| y permutación)"


def _antelacion():
    """Días de antelación de la evaluación del informe (el horizonte más corto de cifras_app.json) y su nombre."""
    h = int(min(D.valor("demanda", "demanda_wape_antelacion")["E11_V4"], key=int))
    return h, ("una semana" if h == 7 else f"{h} días")


def _partir(texto, largo=26):
    """Rótulo largo del eje en dos líneas, cortado en el espacio más cercano a la mitad: a 400 px no se corta."""
    cortes = [i for i, ch in enumerate(texto) if ch == " "]
    if len(texto) <= largo or not cortes:
        return texto
    i = min(cortes, key=lambda c: abs(c - len(texto) // 2))
    return texto[:i] + "<br>" + texto[i + 1:]


# --- El modelo del producto ---------------------------------------------------------------------------------------------
def _candidato(P):
    """Tarjeta del candidato registrado sin activar (fv3): su error con el mismo protocolo que el activo, en los dos
    años congelados y en la prueba de nov–dic 2025, y por qué no está activo. None si no hay candidato evaluado."""
    C = (P or {}).get("candidato")
    if not C:
        return None
    fichas = []
    for anio in ("2025", "2024"):
        r = C["robustez"].get(anio)
        if not r:
            continue
        dif, ic = r["wape"] - r["wape_activo"], r["ic95_diferencia"]
        fichas.append(ui.cifra(
            f"Error en {anio}, entrenado hasta el {ui.fecha_corta(r['entrenado_hasta'])} de {r['entrenado_hasta'][:4]}",
            num(r["wape"], 2), "%",
            tono="bien" if ic[1] < 0 else None, flecha=dif,
            variacion=ui.pegar(f"{con_signo(dif, 2)} puntos frente al activo ({num(r['wape_activo'], 2)} %)"),
            nota=ui.pegar(f"Intervalo del 95 % de la diferencia: {con_signo(ic[0], 2)} a {con_signo(ic[1], 2)} puntos; "
                          f"mejora en {num(r['meses_mejor'])} de {num(r['meses'])} meses.")))
    icp = C["ic95_prueba"]
    fichas.append(ui.cifra("Error en la prueba de nov–dic 2025", num(C["wape_prueba"], 2), "%",
                           nota=ui.pegar(f"Intervalo del 95 %: {num(icp[0], 2)} a {num(icp[1], 2)} %; el activo, "
                                         f"{num(P['wape_modelo'], 2)} %. Es informativa, como la del activo.")))
    cuerpo = [html.Div([ui.chip("Candidato, sin activar"), ui.chip_valor("model_id:", C["model_id"])], className="chips"),
              ui.parrafo("El mismo modelo con el calendario escolar y universitario: los recesos de los colegios oficiales "
                         "de Barranquilla, los periodos de clases de las universidades y cuánto de eso hay en las semanas que "
                         "toma de referencia. Donde más mejora es en los recesos escolares."),
              ui.cifras(fichas),
              ui.aviso(["No está activo: activarlo cambiaría los pronósticos con los que se midieron el ciclo diario, las "
                        "alertas y las respuestas de esta entrega.",
                        "La API lo pone primero en sombra y su compuerta decide; para volver atrás basta con reactivar el "
                        "modelo de hoy."], None, "Por qué no está activo")]
    return ui.tarjeta(cuerpo, titulo=f"Candidato: {C['model_id']}",
                      subtitulo="Un modelo mejor, registrado y evaluado con el mismo protocolo, a la espera de la sombra.",
                      fuentes=D.fuentes_producto("candidato"), id="mo-candidato")


def _producto(P):
    """Tarjeta del modelo que ejecuta la API: error en la prueba de nov–dic 2025 frente a la regla manual, intervalo
    bootstrap, cobertura de la banda calibrada y la declaración honesta del uso de esa prueba."""
    if not P:
        return ui.tarjeta(ui.aviso("Falta datos/modelo_producto.json: corra python preparar_datos.py --solo-producto.",
                                   "atencion", "Sin la ficha del modelo activo"), titulo=ui.NOMBRE_PRODUCTO, id="mo-producto")
    ic, icd = P["ic95_modelo"], P["ic95_diferencia"]
    dif = P["wape_modelo"] - P["wape_regla_manual"]
    periodo = f"del {ui.fecha_corta(P['prueba']['desde'])} al {ui.fecha_corta(P['prueba']['hasta'])} de 2025"
    cifras = ui.cifras([
        ui.cifra("Error en la prueba de nov–dic 2025", num(P["wape_modelo"], 2), "%", tono="bien", flecha=dif,
                 variacion=f"{con_signo(dif, 2)} puntos frente a la regla manual",
                 nota=f"WAPE; intervalo del 95 %: {num(ic[0], 2)} a {num(ic[1], 2)} % (bootstrap por bloques de "
                      f"{num(P['bootstrap']['bloque_dias'])} días, {num(P['bootstrap']['B'])} réplicas)."),
        ui.cifra("Regla manual en la misma prueba", num(P["wape_regla_manual"], 2), "%", hoy=True,
                 nota=f"La diferencia, con su intervalo del 95 %: {con_signo(icd[0], 2)} a {con_signo(icd[1], 2)} puntos."),
        ui.cifra("Cobertura de la banda P10–P90", num(P["cobertura_v2"], 2), "%",
                 nota=f"Con la calibración v2 (la v1 daba {num(P['cobertura_v1'], 2)} %); objetivo {num(P['cobertura_objetivo'])} %. "
                      f"Ancho medio: {num(P['ancho_v2'])} pasajeros por hora."),
        ui.cifra("Versión anterior de las variables", num(P["wape_modelo_anterior"], 2), "%",
                 nota=f"{P.get('modelo_anterior') or '—'} en la misma prueba: la que reemplazó."),
    ])
    honesto = ui.aviso(
        [f"La prueba {periodo} ({num(P['prueba']['franjas'])} franjas de ruta, día y hora) se consultó al elegir esta versión de "
         "las variables frente a la anterior, así que ya no es una prueba nunca vista: queda como reporte informativo.",
         "El criterio de selección es la validación y los backtests congelados de 2024 y 2025. Se pidió a Extreme un periodo "
         "de 2026 como prueba limpia."], "canje", "Cómo leer esta cifra")
    cuerpo = [html.Div([ui.chip("En la API", "acento"), ui.chip_valor("model_id:", P["model_id"])], className="chips"),
              ui.parrafo("HistGradientBoosting con cuantiles P10, P50 y P90 por ruta y hora, con las variables de demanda "
                         "reciente y del calendario, y una banda P10–P90 recalibrada (conformal) para que lo real caiga dentro "
                         "ocho de cada diez veces. Es el modelo que la API usa para pronosticar, recomendar y alertar."),
              cifras, honesto]
    return ui.tarjeta(cuerpo, titulo=f"{ui.NOMBRE_PRODUCTO}: {P['model_id']}",
                      subtitulo=f"El que ejecuta el producto, medido en la prueba {periodo} con el protocolo de la API.",
                      fuentes=D.fuentes_producto(), id="mo-producto")


@callback(Output("mo-producto-imp", "children"), Input("mo-producto-imp", "id"))
def importancia_producto(_id):
    """Las variables que más pesan en el modelo activo, leídas en vivo de la API (media de |SHAP| en escala log)."""
    P = D.modelo_producto()
    if not P:
        return ui.nota("Sin la ficha del modelo activo.")
    d, err = API.obtener(f"models/{P['model_id']}/importance")
    if err:
        return ui.aviso([err, API.ayuda_error(err)], "atencion", API.titulo_error(err), rol="status")
    shap = [x for x in ((d.get("shap") or {}).get("media_abs_shap_log") or []) if isinstance(x, dict)]
    if shap:
        total = sum(float(x.get("media_abs") or 0) for x in shap) or 1.0
        top = sorted(shap, key=lambda x: float(x.get("media_abs") or 0), reverse=True)[:N_VARIABLES]
        filas = [(NOMBRES_FV2.get(x["variable"], x["variable"]), float(x["media_abs"]) / total * 100) for x in top]
        unidad, que = "%", "de la media de |SHAP| (cuánto mueve cada variable el pronóstico, en escala log)"
    else:
        perm = [x for x in (d.get("permutacion") or []) if isinstance(x, dict)]
        total = sum(max(float(x.get("aumento_mae") or 0), 0) for x in perm) or 1.0
        top = sorted(perm, key=lambda x: float(x.get("aumento_mae") or 0), reverse=True)[:N_VARIABLES]
        filas = [(NOMBRES_FV2.get(x["variable"], x["variable"]), max(float(x["aumento_mae"]), 0) / total * 100) for x in top]
        unidad, que = "%", "del aumento del error al permutar cada variable"
    if not filas:
        return ui.nota("La API no trae la importancia de este modelo.")
    barras = html.Div([ui.barra_rayas(n, f"{num(v, 1)} {unidad}", v / 100, "modelo") for n, v in filas], className="rayas-lista")
    return [html.H4(f"Pesa más «{filas[0][0]}» ({num(filas[0][1], 1)} %)", className="api-grupo__titulo"),
            ui.nota(f"Las {num(len(filas))} variables con más peso, en % {que}. Leído de la API para {d.get('model_id')}."),
            barras]


# --- Los experimentos del informe académico -------------------------------------------------------------------------------
def _errores_fig(nombres, vals):
    """Barras horizontales del error de 2025 en el orden fijo: las referencias rayadas en gris; los experimentos en azul,
    el 11 rayado y el 12 (el que recomendaba el informe) sólido, como la columna en foco de la referencia."""
    ys = [_partir(n) for n in nombres]
    ancho = ui.ancho_barra(len(nombres), ALTO_BAJO)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=vals[:2], y=ys[:2], orientation="h", name="Referencias", **ui.traza("hoy", "rayada", ancho=ancho),
                         text=[f"{num(v, 2)} %" for v in vals[:2]], **ui.hover("", vals[:2], "%", 2, categorias=nombres[:2])))
    fig.add_trace(go.Bar(x=vals[2:], y=ys[2:], orientation="h", name="Experimentos", **ui.barras_foco("modelo", ys[2:], foco=ys[3], ancho=ancho),
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
    corto = "el experimento 12" if clave == "E12" else "el experimento 11"
    titulo = f"En {corto} pesa más «{nombres[0]}» ({num(valores[0], 1)} %)"
    sub = (f"{NOMBRE_MODELO[clave]}: las {len(items)} variables con más peso, en % de la importancia de los árboles (cuánto "
           f"reduce el error cada variable; con {h} días de antelación).")
    tabla = ui.tabla(["Variable", "Peso (% de la importancia)"], [[n, f"{num(v, 1)} %"] for n, v in zip(nombres, valores)], compacta=True)
    barras = html.Div([ui.barra_rayas(n, f"{num(v, 1)} %", v / 100, "modelo") for n, v in zip(nombres, valores)], className="rayas-lista")
    return ui.tarjeta(barras, titulo=titulo, subtitulo=sub, detalles=tabla, fuentes=FUENTES_IMP)


def _d9(texto):
    """Los textos del informe nombran «E11» y «E12» a secas, que chocan con los entregables E11 y E12: aquí se leen
    «experimento 11» y «experimento 12»."""
    texto = re.sub(r"\bde (E1[12])\b", lambda m: f"del experimento {m.group(1)[1:]}", texto or "")
    return re.sub(r"\b(E1[12])\b", lambda m: f"el experimento {m.group(1)[1:]}", texto)


def _resumen(M, w25, b1):
    """El resumen de la ficha; en el experimento 11, su última frase se arma con los datos para que «de cada 100» vaya con
    enteros, como en el resto de la pantalla."""
    texto = _d9(M["resumen_para_jurado"])
    corte = texto.find(" Se equivoca en ")
    if corte > 0 and b1 is not None:
        texto = texto[:corte] + f" Se equivoca en {num(w25)} de cada 100 pasajeros a una semana; la regla manual de Sobusa, en {num(b1)}."
    return texto


def _tarjeta_modelo(M, clave, rol, chip, w25, w24, sesgo, n_var, nota_var, pliegues, h, b1=None):
    hijos = []
    if chip:
        hijos.append(html.Div(ui.chip("El que recomendaba el informe", "acento"), className="chips"))
    hijos += [
        ui.parrafo(_resumen(M, w25, b1)),
        ui.cifras([
            ui.cifra("Error en 2025", num(w25, 2), "%", nota=f"WAPE, {pliegues} pliegues, h = {h} días", mini=True),
            ui.cifra("Error en 2024", num(w24, 2), "%", nota="Prueba fuera de la muestra de selección", mini=True),
            ui.cifra("Sesgo", con_signo(sesgo, 2), "%", nota="Del total de pasajeros de 2025", mini=True),
            ui.cifra("Variables", num(n_var), None, nota=nota_var, mini=True),
        ]),
    ]
    return ui.tarjeta(hijos, titulo=NOMBRE_MODELO[clave], subtitulo=rol,
                      detalles=[html.P("Qué es, con más detalle", className="mas__titulo"), ui.parrafo(_d9(M["que_es"]["texto"]))],
                      fuentes=FUENTES_FICHA)


def _laboratorio(P):
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

    # --- cuánto se equivoca cada uno: orden fijo; referencias rayadas en gris, el 11 rayado y el 12 sólido -----------------
    nombres = [NOMBRE_MODELO[m] for m in ui.ORDEN_MODELOS]
    vals = [b1, e1, w25_11, w25_12]
    errores = ui.grafico(
        _errores_fig(nombres, vals),
        titulo=f"En el informe, el experimento 12 se equivoca en {num(w25_12)} de cada 100 pasajeros; la regla manual, en {num(b1)}",
        subtitulo=f"Pasajeros mal estimados de cada 100 en 2025 (WAPE), con {antelacion} de antelación. Menos es mejor. El mismo "
                  "protocolo para todos: cada mes de 2025 se pronosticó con lo anterior a ese mes.",
        etiqueta="Error de 2025 (WAPE) en el informe académico: " + "; ".join(f"{n}, {num(v, 2)} %" for n, v in zip(nombres, vals)) + ".",
        tabla=(["Modelo", "Error en 2025 (WAPE)"], [[n, f"{num(v, 2)} %"] for n, v in zip(nombres, vals)]),
        leyenda=[("Experimento 12 (híbrido), el que recomendaba el informe", "modelo", "foco"),
                 ("Experimento 11 (LightGBM)", "modelo", "rayada"),
                 ("Referencias: la regla manual de hoy y el primer modelo", "hoy", "rayada")],
        nota=f"WAPE de 2025 en {num(franjas)} franjas de ruta, día y hora, {pliegues} pliegues mensuales, fuera de muestra.",
        alto="bajo", fuentes=FUENTES_ERROR)

    lectura = ui.tarjeta_insight(
        con_signo(dif25, 2), "puntos de error del experimento 12 frente al 11 en 2025",
        f"En 2024, un año que no se usó para escogerlo, vuelve a bajar: {con_signo(h24['dif'], 2)} puntos. Es la única mejora "
        "frente al experimento 11 que se confirmó fuera de la muestra de selección.", chip_="Informe académico")

    modelos = ui.rejilla([
        _tarjeta_modelo(M11, "E11", "Experimento 11 del informe (modelo_final.py)", False, w25_11, w24_11, s11, n11,
                        "Calendario, demanda y oferta rezagadas", pliegues, h, b1=b1),
        _tarjeta_modelo(M12, "E12", "Experimento 12 del informe (modelo_final_hibrido.py)", True, w25_12, h24["WAPE_hibrido"],
                        sesgo["2025_pct"], n12, f"Las {num(n11)} del experimento 11 y {num(n12 - n11)} de Chronos‑2", pliegues, h),
    ], "1-1")

    importancia = ui.rejilla([_importancia("E11", imp11, h), _importancia("E12", imp12, h)], "1-1")

    no_api = ("El producto no lo ejecuta: la API usa el modelo activo de arriba, que corre sin GPU dentro del ciclo diario y "
              "se gobierna con el registro de modelos.")
    if P:
        no_api = f"El producto no lo ejecuta: la API usa {P['model_id']}, que corre sin GPU dentro del ciclo diario y se gobierna con el registro de modelos."
    tarjeta_por_que = ui.tarjeta([
        ui.aviso(f"El experimento 12 añade una pieza al experimento 11: Chronos-2. {no_api}", "canje", "Una pieza más"),
        ui.cifras([
            ui.cifra("Error frente al experimento 11, 2025", con_signo(dif25, 2), "puntos", variacion="Baja el error", tono="bien",
                     flecha=dif25, nota=f"Intervalo del 95 %: {con_signo(h25['ic_inf'], 2)} a {con_signo(h25['ic_sup'], 2)}; "
                                        f"mejor en {meses_25}."),
            ui.cifra("Error frente al experimento 11, 2024", con_signo(h24["dif"], 2), "puntos", variacion="Baja el error", tono="bien",
                     flecha=h24["dif"], nota=f"Intervalo del 95 %: {con_signo(h24['ic_inf'], 2)} a {con_signo(h24['ic_sup'], 2)}; "
                                            f"mejor en {h24['meses_mejor']} de {h25['meses']} meses."),
        ]),
        ui.parrafo("En el informe es la única mejora frente al experimento 11 que se confirmó fuera de la muestra con la que se "
                   "eligió: baja el error en 2025 y vuelve a bajarlo en 2024, un año que no se usó para escogerlo. Otros candidatos "
                   "rindieron igual con más piezas y más sesgo, o no repitieron su ventaja en 2024."),
        ui.desplegable("Motivo tal como lo dejó el experimento 12", ui.parrafo(_d9(por_que)), llano=True),
    ], titulo="Por qué el informe recomendaba el experimento 12",
        subtitulo="La única mejora que se sostuvo fuera de la muestra de selección, dentro del informe académico.",
        fuentes=["datos/cifras_app.json (modelo_hibrido_wape_2025, modelo_hibrido_wape_2024, modelo_por_que_hibrido)",
                 "experimentos/E12_comparacion_modelos/resultados.json"])

    intro = (f"Con estos experimentos se estudió el problema. Sus cifras no se comparan con las del modelo activo: son otra "
             f"métrica y otro protocolo (pronóstico con {antelacion} de antelación y WAPE sobre todo 2025, {pliegues} pliegues "
             "mensuales), mientras el modelo activo se mide en la prueba de nov–dic 2025 con el protocolo de la API.")
    return ui.seccion("Laboratorio del informe académico: experimentos 11 y 12", [
        html.Div([html.H3("Cuánto se equivoca cada uno", className="oculto"), ui.rejilla([errores, lectura], "2-1")]),
        html.Div([html.H3("Los dos experimentos", className="oculto"), modelos]),
        html.Div([html.H3("Qué variables pesan más", className="oculto"), importancia]),
        tarjeta_por_que,
    ], subtitulo="Los modelos del informe académico, conservados como laboratorio; no son los que ejecuta la API.",
        intro=intro, id="mo-laboratorio")


def layout(**_):
    P = D.modelo_producto()
    if P:
        sub = (f"El modelo activo de la API se equivoca en el {num(P['wape_modelo'], 2)} % de los pasajeros en la prueba de "
               f"nov–dic 2025; la regla manual, en el {num(P['wape_regla_manual'], 2)} %. Los experimentos del informe van aparte.")
    else:
        sub = "El modelo activo de la API y, aparte, los experimentos del informe académico."
    cabecera = ui.cabecera("modelo", "¿Qué modelo es y por qué?", sub)
    imp = ui.tarjeta(html.Div(ui.nota("Consultando la API del reto…"), id="mo-producto-imp", **{"aria-live": "polite"}),
                     titulo="Qué variables pesan en el modelo activo",
                     subtitulo="La importancia global que calcula la API para el modelo que ejecuta.", fuentes=[FUENTE_IMP_API])
    return ui.pantalla([
        ui.arriba(cabecera),
        ui.seccion("El modelo del producto", [ui.rejilla([_producto(P), imp], "2-1")]
                   + ([_candidato(P)] if _candidato(P) else []),
                   subtitulo="El que la API usa para pronosticar, recomendar y alertar, y el candidato que espera la sombra.",
                   id="mo-del-producto"),
        _laboratorio(P),
    ])
