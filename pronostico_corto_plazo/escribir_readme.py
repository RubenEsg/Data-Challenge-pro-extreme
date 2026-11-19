"""Escribe README.md con las cifras de panel/ y resultados/: ninguna se escribe a mano. También reescribe, en el
README de la entrega (la carpeta de arriba), la sección «Correcciones tras la retroalimentación del curso», que va
entre las marcas corto_plazo.

Uso (desde esta carpeta):  python escribir_readme.py
"""
from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

import comun as C

MENOS = "−"
MARCA_INI, MARCA_FIN = "<!-- corto_plazo:inicio", "<!-- corto_plazo:fin -->"
# Los tres commits del repositorio de entrega (RubenEsg/Data-Challenge-pro-extreme) que prueban el orden, con su hora
# del 17-11-2026 (hora de Colombia). Se ven con: git log --format="%h %ad %s" -- pronostico_corto_plazo
COMMITS = {"protocolo": ("9844dae", "19:26"), "validacion": ("fa04afb", "20:23"), "prueba": ("546cffa", "21:01")}
NOMBRE_CONJUNTO = {"semanal": "semanal", "con_hoy": "con lo de hoy", "completo": "completo"}
NOMBRE_NIVEL = {"ruta": "Ruta", "sentido": "Sentido", "segmento": "Segmento"}
NOMBRE_HIPER = {"base": "base", "arboles_pequenos": "árboles pequeños", "arboles_grandes": "árboles grandes"}
# qué es cada variable, para las que más pesan (las demás salen con su nombre en el código)
QUE_ES = {"p15": "lo que subió en los 15 minutos anteriores", "p30": "en los 30 anteriores", "p60": "en los 60 anteriores",
          "p120": "en los 120 anteriores", "m8": "el promedio de las 8 semanas anteriores", "m4": "el de las 4 semanas",
          "m7d": "la media de los 7 días anteriores", "l7": "la misma ventana 7 días antes", "ayer": "la misma ventana ayer",
          "hoy": "lo acumulado hoy", "rhoy": "lo acumulado hoy frente a lo habitual", "r120": "las últimas 2 horas frente a lo habitual",
          "sal60": "las salidas de la última hora", "tipo_dia": "el tipo de día", "instante": "la hora"}


def num(x, dec: int = 2, signo: bool = False) -> str:
    """Formato es-CO. Una sola regla de redondeo, la del informe: la mitad hacia arriba sobre el decimal escrito en el
    archivo de resultados (8.715 -> «8,72», no el 8,71 que daría el binario de 8.715)."""
    if x is None:
        return "—"
    x = Decimal(str(x)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
    s = f"{abs(x):,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    cero = not (set(s) - set("0,."))
    return (MENOS if x < 0 and not cero else "+" if signo and x > 0 and not cero else "") + s


def resta(a, b) -> Decimal:
    """a − b con los decimales tal como están escritos en el archivo (sin el error del binario)."""
    return Decimal(str(a)) - Decimal(str(b))


def pct(x, dec: int = 2) -> str:
    return num(x, dec) + " %"


def leer(rel: str) -> dict:
    return json.loads((C.AQUI / rel).read_text(encoding="utf-8"))


REPRODUCCION = C.AQUI.parent / "api_frecuencias" / "docs" / "evidencias" / "modelo" / "corto_plazo_reproduccion.json"


def reproduccion() -> dict | None:
    """La comprobación de que la API reproduce esta prueba (api_frecuencias/scripts/verificar_corto_plazo.py)."""
    if not REPRODUCCION.exists():
        return None
    r = json.loads(REPRODUCCION.read_text(encoding="utf-8"))
    return dict(r, filas=sum(x["filas_en_las_dos"] for x in r["predicciones"].values()))


def main() -> None:
    ver, sen = leer("panel/verificacion_extreme.json"), leer("panel/revision_sentido.json")
    val, sel, pru = leer("resultados/validacion.json"), leer("resultados/seleccion.json"), leer("resultados/prueba.json")
    fig = leer("resultados/figuras.json")["dia_de_ejemplo"]
    v = ver["verificacion_extreme"]
    niv = pru["niveles"]
    r60 = niv["ruta"]["60"]
    m60, p60 = r60["todas_las_rutas"]["modelo"], r60["todas_las_rutas"]["promedio_dia_hora"]
    ic60 = r60["todas_las_rutas"]["ic95"]["modelo_menos_promedio_dia_hora"]["ic95"]
    seg60, s60 = niv["segmento"]["60"]["todas_las_rutas"], pru["por_segmento"]["60"]
    sec = pru["secundarios"]
    geo, tv = sen["geometria"], sen["tiempo_de_viaje"]
    L: list[str] = []
    a = L.append

    a("# Pronóstico de corto plazo por ruta, sentido y segmento")
    a("")
    a("Este es el pronóstico que pide el enunciado: las subidas de los siguientes **30, 60 y 120 minutos**, por **ruta, sentido "
      "y segmento**, con lo observado hasta el instante del pronóstico. Se eligió con unos meses y se reportó, una sola vez, con "
      "otros.")
    a("")
    a(f"**Resultado principal** (prueba de julio a diciembre de 2025, por ruta, a 60 minutos): el modelo se equivoca en "
      f"**{pct(m60['wape'])}** de las subidas y el promedio por día y hora, la línea base del enunciado, en {pct(p60['wape'])}. "
      f"La diferencia es de {num(resta(m60['wape'], p60['wape']), 2, True)} puntos, con IC del 95 % de {num(ic60[0], 2, True)} a "
      f"{num(ic60[1], 2, True)}.")
    a("")
    a("## Por qué existe")
    a("")
    a("La retroalimentación del curso del 17 de noviembre de 2026 señaló tres cosas de la entrega. Esto es lo que se hizo con "
      "cada una:")
    a("")
    a("| Lo que se señaló | Lo que pide la especificación v1.5 | Lo que se hizo |")
    a("|---|---|---|")
    a("| El pronóstico era a siete días por ruta y hora de salida: no es el problema pedido, y sus cifras no se comparan con "
      "las de otros equipos | «Predecir la demanda para horizontes configurables de 30, 60 y 120 minutos» (§2.2, RF-005) "
      "«por ruta, sentido, segmento y franja horaria» (§3.1, §9.1) | Cada media hora se pronostican las subidas de los "
      "siguientes 30, 60 y 120 minutos, en los tres niveles, con MAE, RMSE, WAPE y sMAPE por ruta y franja |")
    a("| Los modelos se eligieron y se reportaron sobre los mismos meses de 2025 | «División cronológica en entrenamiento, "
      "validación y prueba reservada» (§9.3) | Se entrena con 2023 y 2024, se elige con enero a junio de 2025 y se reporta "
      "una vez con julio a diciembre de 2025. El protocolo se confirmó en git antes de correr la validación |")
    a(f"| El modelo por segmento se entrenó con 37 días: lo espacial no quedó validado | Pronóstico y sesgo «por ruta, sentido, "
      f"segmento» (§9.1, §9.3) | Subidas por segmento de los tres años con la regla de Extreme, verificada contra su tabla. El "
      f"modelo por segmento se entrena con más de dos años y se prueba en seis meses: {num(seg60['modelo']['n'], 0)} celdas de "
      f"segmento e instante |")
    a("")
    a("El pronóstico a siete días del informe se conserva: es el que usa la programación semanal. Sus cifras no se comparan "
      "con las de aquí, porque son otro objetivo (pasajeros por hora de salida) y otro horizonte.")
    a("")
    a("## El problema")
    a("")
    a("- **Qué se pronostica.** En cada instante *t* (cada media hora, de 04:00 a 21:00: 35 instantes por día), las subidas de "
      "las ventanas [*t*, *t* + 30), [*t*, *t* + 60) y [*t*, *t* + 120).")
    a("- **A qué nivel.** La ruta (3), el sentido (ida y regreso) y el segmento: los 386 segmentos oficiales de 500 m de "
      "`rutas_segmentos` (135 en SILENCIO, 123 en CRA 54 y 128 en CL 72).")
    fuga = leer("resultados/comprobacion_fuga.json") if (C.AQUI / "resultados" / "comprobacion_fuga.json").exists() else None
    a("- **Con qué información.** Solo lo ocurrido antes de *t* y el calendario. Ninguna variable usa nada de *t* en adelante."
      + (f" Se comprobó cambiando el futuro: en {num(fuga['comprobaciones'], 0)} comprobaciones "
         f"({num(fuga['valores_comparados'], 0)} valores comparados), las variables y las líneas base de las filas anteriores "
         f"al cambio tuvieron {num(fuga['diferencias'], 0)} diferencias (`comprobar_fuga.py`, "
         f"`resultados/comprobacion_fuga.json`)." if fuga else ""))
    a("- **Qué cuenta como subida.** Cada evento de conteo con subidas, en el bloque de 15 minutos del instante en que "
      "ocurrió, de todos los viajes.")
    a("")
    a("## Los datos")
    a("")
    a(f"La tabla `timbradas_segmentos` de la base del reto solo cubre del {v['periodo_tabla_extreme'][0]} al "
      f"{v['periodo_tabla_extreme'][1]}. Para tener los tres años se exportaron, en solo lectura, los "
      f"{num(ver['eventos']['eventos'], 0)} eventos de conteo con subidas (`exportar_eventos_subida.py`) y a cada uno se le "
      f"asignó el segmento con la regla de Extreme: el segmento activo más cercano de su ruta (`preparar_panel.py`).")
    a("")
    a("**La regla propia reproduce la tabla de Extreme** en los 58 días que la base trae (`panel/verificacion_extreme.json`):")
    a("")
    a("| Comprobación | Resultado |")
    a("|---|---|")
    a(f"| Subidas de los {num(v['viajes_en_la_tabla_de_extreme'], 0)} viajes de la tabla | {num(v['subidas_extreme'], 0)} en la "
      f"tabla de Extreme y {num(v['subidas_propias_en_esos_viajes'], 0)} con la regla propia |")
    a(f"| Subidas que caen en el mismo segmento | {pct(v['subidas_en_el_mismo_segmento_pct'], 3)} |")
    a(f"| Celdas de viaje y segmento idénticas | {pct(v['celdas_identicas_pct'], 3)} de {num(v['celdas_viaje_segmento_con_subidas'], 0)} |")
    a(f"| Viajes con el mismo total | {pct(v['viajes_con_el_mismo_total_pct'], 0)} |")
    a("")
    a(f"El panel (`panel/subidas_segmento_15min.parquet`) tiene {num(ver['panel']['subidas'], 0)} subidas en "
      f"{num(ver['panel']['filas'], 0)} celdas de ruta, día, bloque de 15 minutos y segmento, del {ver['panel']['desde']} al "
      f"{ver['panel']['hasta']}.")
    a("")
    a("- **Días sin datos.** Un día de una ruta con menos del 5 % de las subidas habituales no se entrena ni se evalúa. Son "
      "11 días por ruta: el último día de cada mes de febrero a diciembre de 2025, que la base no trae.")
    a(f"- **Sentido.** No viene en los datos. «Ida» es la primera mitad del ciclo y «regreso» la segunda, como en la API. "
      f"En el {pct(min(g['regreso_con_la_ida_a_menos_de_30_m_pct'] for g in geo.values()), 0)}–"
      f"{pct(max(g['regreso_con_la_ida_a_menos_de_30_m_pct'] for g in geo.values()), 0)} del regreso la ida pasa a menos de "
      f"30 m, y la regla del segmento más cercano no mira en qué parte del viaje va el bus. Se midió cuánto afecta "
      f"(`revisar_sentido.py`, `panel/revision_sentido.json`):")
    a("")
    a("| Ruta | Regreso con la ida a menos de 30 m | Subidas en un segmento coherente con el tiempo de viaje (±45 min) | "
      "Subidas que quedarían mejor en el otro sentido |")
    a("|---|---|---|---|")
    for ruta in C.RUTAS.values():
        a(f"| {ruta} | {pct(geo[ruta]['regreso_con_la_ida_a_menos_de_30_m_pct'], 1)} | "
          f"{pct(tv[ruta]['subidas_a_menos_de_45_min_pct'], 1)} | "
          f"{pct(tv[ruta]['de_ellas_cuadran_en_el_otro_sentido_pct_del_total'], 1)} |")
    a("")
    a("Se conserva la regla de Extreme porque es la definición oficial de la tabla. Las cifras por sentido llevan esa "
      "aproximación.")
    a("")
    a("## Protocolo")
    a("")
    a("Está en [`PROTOCOLO.md`](PROTOCOLO.md), escrito y confirmado en git antes de correr la validación; hasta entonces solo "
      "se había comprobado que el código corría (`validar.py --rapido`: el 20 % de las filas, a 60 minutos, en la validación). "
      "En resumen:")
    a("")
    a("| Parte | Fechas | Para qué |")
    a("|---|---|---|")
    for nombre, (d, h) in C.PERIODOS.items():
        uso = {"entrenamiento": "ajustar los modelos", "validacion": "elegir todo", "prueba": "reportar, una sola vez"}[nombre]
        a(f"| {nombre.capitalize()} | {d} a {h} | {uso} |")
    a("")
    a("El orden quedó en el historial de git del repositorio de entrega, en tres commits del 17 de noviembre de 2026 "
      "(`git log -- pronostico_corto_plazo`):")
    a("")
    a(f"1. `{COMMITS['protocolo'][0]}` ({COMMITS['protocolo'][1]}): el protocolo, el código y el panel, sin resultados;")
    a(f"2. `{COMMITS['validacion'][0]}` ({COMMITS['validacion'][1]}): la validación y lo elegido "
      "(`resultados/validacion.json` y `resultados/seleccion.json`);")
    a(f"3. `{COMMITS['prueba'][0]}` ({COMMITS['prueba'][1]}): la prueba (`resultados/prueba.json`), calculada una sola vez "
      "con lo elegido y reentrenado con todo lo anterior al "
      "1 de julio de 2025.")
    a("")
    a("**Lo que hay que decir de 2025.** El equipo ya había usado esos meses en experimentos anteriores, con otro objetivo "
      "(pasajeros por hora de salida, a siete días). Ninguna decisión de este experimento usa julio a diciembre, pero no es "
      "una prueba ciega en sentido estricto. Se pidió a Extreme un periodo de 2026 para tenerla.")
    a("")
    a("## Lo que se eligió, con la validación")
    a("")
    a("Líneas base: el **promedio por día y hora** (la misma ventana en el mismo día de la semana de las 8 semanas "
      "anteriores) y la **última semana**, que son las del enunciado, y la **persistencia** (lo que subió en los mismos "
      "minutos justo antes). Candidato: LightGBM con pérdida de Poisson, un modelo por nivel, ruta y horizonte.")
    a("")
    a("WAPE medio de los tres horizontes en la validación, en %:")
    a("")
    a("| Nivel | Promedio por día y hora | Modelo: semanal | Modelo: con lo de hoy | Modelo: completo | Elegido |")
    a("|---|---|---|---|---|---|")
    for nivel in C.NIVELES:
        t = val["A_conjunto"][nivel]
        a(f"| {NOMBRE_NIVEL[nivel]} | {num(val['lineas_base'][nivel]['promedio_dia_hora']['wape_medio'])} | "
          f"{num(t['semanal']['wape_medio'])} | {num(t['con_hoy']['wape_medio'])} | {num(t['completo']['wape_medio'])} | "
          f"{NOMBRE_CONJUNTO[sel['conjunto'][nivel]]} |")
    a("")
    a("- `semanal`: calendario y la misma ventana de las semanas anteriores. Es lo que se sabe con siete días de antelación.")
    a("- `con lo de hoy`: además, ayer, la última semana y lo observado hoy hasta el instante.")
    a("- `completo`: además, las salidas ya despachadas y, por segmento, lo observado en los segmentos vecinos y las "
      "salidas que llegarán al segmento en la ventana.")
    a("")
    e = val["C_estructura"]
    a("- **Hiperparámetros** (tres configuraciones fijadas de antemano): "
      + "; ".join(f"{NOMBRE_NIVEL[n].lower()}, «{NOMBRE_HIPER[sel['hiper'][n]['nombre']]}»" for n in C.NIVELES) + ".")
    a(f"- **Sentido:** {'la suma de sus segmentos' if sel['estructura']['sentido'] == 'suma_de_segmentos' else 'modelo directo'} "
      f"(directo {pct(e['sentido']['directo']['wape_medio'])}; suma de segmentos {pct(e['sentido']['suma_de_segmentos']['wape_medio'])}).")
    a(f"- **Segmento:** {'conciliado con el pronóstico de la ruta' if sel['estructura']['segmento'] == 'conciliado_con_la_ruta' else 'modelo directo'} "
      f"(directo {pct(e['segmento']['directo']['wape_medio'])}; conciliado {pct(e['segmento']['conciliado_con_la_ruta']['wape_medio'])}; "
      f"repartir el pronóstico de la ruta con las fracciones históricas, {pct(e['segmento']['reparto_fijo_de_la_ruta']['wape_medio'])}).")
    a("- **Banda P10–P90:** cuantiles conformales por tramo del pronóstico, ajustados con los errores de la validación.")
    a("")
    a("## Resultados de la prueba")
    a("")
    a(f"Julio a diciembre de 2025: {pru['dias_del_periodo']} días, de los que {min(pru['dias_con_datos_en_la_prueba'].values())} "
      f"tienen datos en cada ruta. Todas las cifras salen de `resultados/prueba.json`.")
    a("")
    a("![WAPE por nivel y horizonte](figuras/fig_cp_niveles.png)")
    a("")
    a("**WAPE (%) de cada pronóstico sobre las mismas celdas**, con el IC del 95 % de la diferencia entre el modelo y el "
      "promedio por día y hora (bootstrap de bloques de 7 días, 2.000 réplicas) y la cobertura de la banda P10–P90 (objetivo: 80 %):")
    a("")
    a("| Nivel | Horizonte | Promedio por día y hora | Última semana | Persistencia | **Modelo** | Modelo − promedio [IC 95 %] | Cobertura P10–P90 |")
    a("|---|---|---|---|---|---|---|---|")
    for nivel in C.NIVELES:
        for h in C.HORIZONTES:
            b = niv[nivel][str(h)]
            t = b["todas_las_rutas"]
            ic = t["ic95"]["modelo_menos_promedio_dia_hora"]["ic95"]
            a(f"| {NOMBRE_NIVEL[nivel]} | {h} min | {num(t['promedio_dia_hora']['wape'])} | {num(t['ultima_semana']['wape'])} | "
              f"{num(t['persistencia']['wape'])} | **{num(t['modelo']['wape'])}** | "
              f"{num(resta(t['modelo']['wape'], t['promedio_dia_hora']['wape']), 2, True)} [{num(ic[0], 2, True)}; {num(ic[1], 2, True)}] | "
              f"{pct(b['banda_p10_p90']['todas_las_rutas']['cobertura_pct'], 1)} |")
    a("")
    a("**Por ruta** (modelo; entre paréntesis, el promedio por día y hora):")
    a("")
    a("| Ruta | Subidas medias en 60 min | WAPE 30 min | WAPE 60 min | WAPE 120 min | MAE 60 min | RMSE 60 min | sMAPE 60 min | Sesgo 60 min |")
    a("|---|---|---|---|---|---|---|---|---|")
    for ruta in C.RUTAS.values():
        celdas = []
        for h in C.HORIZONTES:
            x = niv["ruta"][str(h)]["por_ruta"][ruta]
            celdas.append(f"{num(x['modelo']['wape'])} ({num(x['promedio_dia_hora']['wape'])})")
        x = niv["ruta"]["60"]["por_ruta"][ruta]["modelo"]
        a(f"| {ruta} | {num(x['media_real'], 0)} | " + " | ".join(celdas) + f" | {num(x['mae'], 1)} | {num(x['rmse'], 1)} | "
          f"{pct(x['smape'], 1)} | {num(x['sesgo_pct'], 2, True)} % |")
    a("")
    a("**Por franja, a 60 minutos y por ruta** (las tres rutas juntas):")
    a("")
    a("| Franja | Modelo | Promedio por día y hora | Sesgo del modelo |")
    a("|---|---|---|---|")
    fr = r60["todas_las_rutas"]["por_franja"]
    for nombre in [f[0] for f in C.FRANJAS] + ["pico", "valle"]:
        etiqueta = {"pico": "**Pico** (06–08 y 17–19)", "valle": "**Valle** (el resto)"}.get(nombre, nombre)
        a(f"| {etiqueta} | {pct(fr['modelo'][nombre]['wape'])} | {pct(fr['promedio_dia_hora'][nombre]['wape'])} | "
          f"{num(fr['modelo'][nombre]['sesgo_pct'], 2, True)} % |")
    a("")
    tipos = r60["por_tipo_de_dia"]
    meses = r60["por_mes"]
    a("- **Por tipo de día** (60 minutos, por ruta): "
      + "; ".join(f"{k}, {pct(x['modelo'])} frente a {pct(x['promedio_dia_hora'])}" for k, x in tipos.items()) + ".")
    a("- **Por mes** (60 minutos, por ruta): el modelo va de "
      f"{pct(min(x['modelo'] for x in meses.values()))} a {pct(max(x['modelo'] for x in meses.values()))} y gana al promedio en "
      f"{sum(x['modelo'] < x['promedio_dia_hora'] for x in meses.values())} de los {len(meses)} meses.")
    a("")
    domingos(a)
    a("![Un día de la prueba](figuras/fig_cp_dia.png)")
    a("")
    a(f"El día de la figura es el {'{2}-{1}-{0}'.format(*fig['fecha'].split('-'))}: el día laboral de la prueba con el error "
      f"mediano del modelo en CRA 54 a 60 minutos ({pct(fig['wape_modelo'], 1)}; ese día el promedio por día y hora falla "
      f"{pct(fig['wape_promedio_ese_dia'], 1)}). Se eligió con esa regla para no escogerlo a ojo.")
    a("")
    a("![Error según la hora](figuras/fig_cp_instante.png)")
    a("")
    a("## Lo espacial: por sentido y por segmento")
    a("")
    a("![Subidas reales y pronosticadas por segmento](figuras/fig_cp_segmentos.png)")
    a("")
    a(f"- **Por segmento.** En las {num(seg60['modelo']['n'], 0)} celdas de segmento e instante de la prueba, a 60 minutos, el "
      f"modelo se equivoca en {pct(seg60['modelo']['wape'])} y el promedio por día y hora en {pct(seg60['promedio_dia_hora']['wape'])}. "
      f"El error es alto en los dos porque cada celda trae pocas subidas: {num(seg60['modelo']['media_real'], 1)} en promedio.")
    a(f"- **Dónde gana.** El modelo gana al promedio en {s60['segmentos_en_que_gana_al_promedio']} de los "
      f"{s60['segmentos_con_subidas']} segmentos con subidas, que llevan el {pct(s60['subidas_en_segmentos_en_que_gana_pct'], 1)} "
      f"de las subidas.")
    a(f"- **Sesgo por segmento.** Su valor absoluto mediano es {pct(s60['sesgo_abs_mediano_pct'], 1)}; ponderado por subidas, "
      f"{pct(s60['sesgo_abs_medio_ponderado_pct'], 1)}. En {s60['segmentos_con_sesgo_abs_menor_de_5_pct']} segmentos queda por "
      f"debajo del 5 %. El detalle de cada segmento está en `resultados/segmentos_prueba.csv`.")
    a("")
    a("**Por sentido, a 60 minutos:**")
    a("")
    a("| Ruta y sentido | Modelo | Promedio por día y hora | Sesgo del modelo |")
    a("|---|---|---|---|")
    for clave, x in pru["por_sentido"]["60"].items():
        a(f"| {clave} | {pct(x['modelo']['wape'])} | {pct(x['promedio_dia_hora']['wape'])} | {num(x['modelo']['sesgo_pct'], 2, True)} % |")
    a("")
    a("## Cuánto aporta lo observado en el día y cuánto cuesta que la captura llegue tarde")
    a("")
    a("Dos análisis que el protocolo declaró de antemano, por ruta (WAPE en %):")
    a("")
    a("| Horizonte | Promedio por día y hora | Modelo con lo que se sabe 7 días antes | Modelo elegido | … con 15 min de retraso | … con 30 min de retraso |")
    a("|---|---|---|---|---|---|")
    for h in C.HORIZONTES:
        ret = sec["retraso_de_la_captura"][str(h)]
        a(f"| {h} min | {num(niv['ruta'][str(h)]['todas_las_rutas']['promedio_dia_hora']['wape'])} | "
          f"{num(sec['informacion_del_dia'][str(h)]['semanal']['wape'])} | **{num(ret['0'])}** | {num(ret.get('15'))} | {num(ret.get('30'))} |")
    a("")
    a("![Información del día y retraso de la captura](figuras/fig_cp_informacion.png)")
    a("")
    i60 = sec["informacion_del_dia"]["60"]
    a(f"- El mismo modelo con solo lo que se sabe una semana antes falla un {pct(i60['semanal']['wape'])} a 60 minutos; con lo "
      f"observado hasta el instante, un {pct(i60['elegido']['wape'])}. Esa diferencia es lo que le faltaba al pronóstico a "
      f"siete días para ser el del enunciado.")
    if sec["retraso_de_la_captura"]["60"].get("30") is not None:
        a(f"- Con 30 minutos de retraso en la captura, el error a 60 minutos es de "
          f"{pct(sec['retraso_de_la_captura']['60']['30'])}; con 15 minutos, de {pct(sec['retraso_de_la_captura']['60'].get('15'))}.")
    imp = pru["importancia"]["ruta"]["60"]
    a("- Las variables que más pesan en el modelo de ruta a 60 minutos (parte de la ganancia de los árboles): "
      + "; ".join(f"`{k}` ({QUE_ES.get(k, k)}), {pct(x * 100, 0)}" for k, x in list(imp.items())[:5]) + ".")
    a("")
    anomalo(a, pru)
    a("## Limitaciones")
    a("")
    a("- **El sentido es una aproximación** (la mitad del ciclo) y la regla del segmento más cercano deja una parte de las "
      "subidas en el sentido contrario (tabla de «Los datos»).")
    a("- **La prueba no es ciega en sentido estricto:** 2025 se conocía por los experimentos anteriores, aunque con otro "
      "objetivo.")
    a("- **Las subidas son demanda observada.** Dependen de los buses que pasaron: si no pasa bus, no hay subida. El "
      "modelo pronostica lo que se va a contar, no la gente que espera.")
    a("- **Supone que el conteo llega en vivo.** La especificación lo prevé (el disparador de conteo), pero la latencia real "
      "de la captura no se conoce; por eso se midió el efecto de 15 y 30 minutos de retraso.")
    rep = reproduccion()
    if rep and rep["coincide"]:
        a("- **Lee el panel empaquetado, no la captura en vivo.** La API ya sirve este modelo "
          "(`POST /api/v1/predictions/corto-plazo`) y reproduce las "
          f"{num(rep['filas'], 0)} predicciones guardadas de esta prueba "
          "(`../api_frecuencias/docs/evidencias/modelo/corto_plazo_reproduccion.md`), pero pronostica con este panel de "
          "2023 a 2025. Alimentarlo con la lectura incremental es el primer pendiente de `../PLAN_EVOLUCION.md` (sección 7).")
    else:
        a("- **No está integrado en la API.** La API pronostica hoy por hora de salida con su propio modelo. Llevar este a "
          "la API es el siguiente paso (`../PLAN_EVOLUCION.md`, sección 7).")
    a("- **En los domingos corrientes el modelo no mejora al promedio por día y hora** (tabla de «Domingos y festivos por "
      "separado»).")
    a("- **Once días de 2025 sin eventos** (los últimos de mes) quedan fuera del entrenamiento y de la evaluación.")
    if (C.AQUI / "resultados" / "sensibilidad_registro_anomalo.json").exists():
        a("- **Los registros imposibles siguen en los datos.** El protocolo no previó filtrarlos: uno cae en el entrenamiento y "
          "otro en la prueba. Su efecto en la prueba está medido arriba; filtrarlos antes de entrenar es un pendiente.")
    a("")
    a("## Cómo reproducirlo")
    a("")
    a("Con las versiones de `../requirements_cuaderno.txt` (LightGBM " + pru["versiones"]["lightgbm"] + ", semilla 42), desde esta carpeta:")
    a("")
    a("```")
    a("python validar.py           # elige con la validación: resultados/validacion.json y seleccion.json")
    a("python probar.py --repetir  # recalcula la prueba con lo elegido: resultados/prueba.json")
    a("python comprobar_fuga.py    # comprueba que ninguna variable usa el futuro: resultados/comprobacion_fuga.json")
    a("python sensibilidad_registro_anomalo.py   # análisis posterior: sin los días que toca el registro imposible")
    a("python desglose_domingos_festivos.py      # análisis posterior: domingos y festivos por separado")
    a("python figuras.py           # figuras/")
    a("python escribir_readme.py   # este archivo")
    a("```")
    a("")
    a("`validar.py` y `probar.py` solo leen `panel/`, que viaja en la entrega. `exportar_eventos_subida.py` y "
      "`preparar_panel.py` arman `panel/` desde la base del reto y necesitan el acceso de solo lectura.")
    a("")
    a("| Archivo | Qué es |")
    a("|---|---|")
    a("| `PROTOCOLO.md` | El problema, la partición, las reglas de elección y lo que se reporta, escrito antes de la validación |")
    a("| `exportar_eventos_subida.py` | Exporta de la base, en solo lectura y por tramos, los eventos de conteo con subidas |")
    a("| `preparar_panel.py` | Asigna cada subida a su segmento y arma `panel/`; verifica contra la tabla de Extreme |")
    a("| `revisar_sentido.py` | Mide cuánto confunde el sentido la regla del segmento más cercano |")
    a("| `comprobar_fuga.py` | Cambia el futuro y comprueba que ninguna variable ni línea base anterior al cambio se mueve |")
    a("| `sensibilidad_registro_anomalo.py` | Análisis posterior a la prueba: las métricas sin los días que toca un registro imposible |")
    a("| `desglose_domingos_festivos.py` | Análisis posterior a la prueba: el error por tipo de día, con domingos y festivos por separado |")
    a("| `comun.py` | Datos, variables, líneas base, modelo, métricas e intervalos |")
    a("| `validar.py` · `probar.py` | La elección con la validación y el único cálculo de la prueba |")
    a("| `figuras.py` · `escribir_readme.py` | Las figuras y este archivo, desde `resultados/` |")
    a("| `panel/` | Subidas por segmento y bloque de 15 minutos, salidas, segmentos, calendario y las dos verificaciones |")
    a("| `resultados/` | `validacion.json`, `seleccion.json`, `prueba.json`, las predicciones por ruta y por sentido y el detalle por segmento |")
    a("")
    (C.AQUI / "README.md").write_text("\n".join(L), encoding="utf-8")
    print("README.md:", len(L), "líneas")
    actualizar_entrega(bloque_entrega(ver, val, pru))


def domingos(a) -> None:
    """Domingos y festivos por separado, si existe resultados/desglose_domingos_festivos.json."""
    ruta = C.AQUI / "resultados" / "desglose_domingos_festivos.json"
    if not ruta.exists():
        return
    d = json.loads(ruta.read_text(encoding="utf-8"))["horizontes"]
    a("**Domingos y festivos por separado** (análisis posterior a la prueba; `desglose_domingos_festivos.py`). El grupo "
      "«domingo o festivo» mezcla dos casos distintos. WAPE por ruta, modelo frente a promedio por día y hora:")
    a("")
    a("| Horizonte | Laboral | Sábado | Domingo corriente | Festivo |")
    a("|---|---|---|---|---|")
    for h in C.HORIZONTES:
        x = d[str(h)]["todas_las_rutas"]
        a(f"| {h} min | " + " | ".join(
            ("" if x[g]["gana_el_modelo"] else "**") + f"{num(x[g]['modelo'])} frente a {num(x[g]['promedio_dia_hora'])}"
            + ("" if x[g]["gana_el_modelo"] else "**") for g in ("laboral", "sábado", "domingo", "festivo")) + " |")
    a("")
    x = d["60"]
    dom, fes = x["todas_las_rutas"]["domingo"], x["todas_las_rutas"]["festivo"]
    cra = x["por_ruta"]["CRA 54"]["domingo"]
    otras = "; ".join(f"{r}, {num(v['domingo']['modelo'])} frente a {num(v['domingo']['promedio_dia_hora'])}"
                      for r, v in x["por_ruta"].items() if r != "CRA 54")
    a(f"- **En los festivos** ({fes['dias']} días) el promedio de las ocho semanas pronostica un día corriente y falla "
      f"{pct(fes['promedio_dia_hora'])}; el modelo, {pct(fes['modelo'])}. De ahí sale casi toda la ventaja del grupo.")
    a(f"- **En los domingos corrientes** ({dom['dias']} días) **el modelo no mejora al promedio**: {pct(dom['modelo'])} frente a "
      f"{pct(dom['promedio_dia_hora'])} a 60 minutos, y a 120 minutos la diferencia es mayor (tabla). La pérdida está en CRA 54 "
      f"({num(cra['modelo'])} frente a {num(cra['promedio_dia_hora'])}); en las otras dos rutas el modelo sí gana ({otras}).")
    a("- No sabemos por qué pasa en CRA 54. Una posibilidad es el registro imposible del domingo 26-05-2024, que está en el "
      "entrenamiento de esa ruta (abajo); comprobarlo exige otro experimento, con su propio protocolo.")
    a("")


def anomalo(a, pru: dict) -> None:
    """La sección del registro imposible, si existe resultados/sensibilidad_registro_anomalo.json."""
    ruta = C.AQUI / "resultados" / "sensibilidad_registro_anomalo.json"
    if not ruta.exists():
        return
    s = json.loads(ruta.read_text(encoding="utf-8"))
    en_prueba = [r for r in s["registros_imposibles"] if r["periodo"] == "prueba"]
    otros = [r for r in s["registros_imposibles"] if r["periodo"] != "prueba"]
    if not en_prueba:
        return

    def fecha(x: str) -> str:
        return "{2}-{1}-{0}".format(*x.split("-"))

    r = en_prueba[0]
    r60 = pru["niveles"]["ruta"]["60"]["todas_las_rutas"]["modelo"]
    a("## Un registro imposible en los datos (análisis posterior a la prueba)")
    a("")
    a(f"Al revisar la prueba, el RMSE por ruta salió varias veces mayor que el MAE (a 60 minutos, {num(r60['rmse'], 1)} frente a "
      f"{num(r60['mae'], 1)} subidas). La causa es un registro de conteo imposible que está en la base: el {fecha(r['fecha'])} a las "
      f"{r['hora']}, **{num(r['subidas'], 0)} subidas en un solo segmento de {r['ruta']} en 15 minutos** (lo habitual en toda la ruta en "
      f"ese bloque son {num(r['mediana_de_la_ruta_en_ese_bloque'], 0)})."
      + (" Hay otro en el entrenamiento: " + "; ".join(f"{num(o['subidas'], 0)} subidas en {o['ruta']} el {fecha(o['fecha'])}" for o in otros) + "."
         if otros else "")
      + " El panel conserva los registros tal como están en la base y el protocolo no previó filtrarlos, así que **las cifras de "
        "arriba lo incluyen y no se cambian**.")
    a("")
    a(f"Para saber cuánto pesa, `sensibilidad_registro_anomalo.py` recalcula las métricas con las predicciones guardadas, sin entrenar "
      f"ni pronosticar de nuevo. Les quita a todos los pronósticos los {len(s['dias_de_ruta_excluidos'])} días de {r['ruta']} en que el "
      f"registro entra en el objetivo o en el promedio de ocho semanas: el {fecha(r['fecha'])} y los ocho mismos días de la semana "
      f"siguientes. No estaba en el protocolo: es un análisis posterior (`resultados/sensibilidad_registro_anomalo.json`).")
    a("")
    a("| Nivel | Horizonte | Modelo: con el registro → sin esos días | Promedio por día y hora: con → sin | Modelo − promedio sin esos días [IC 95 %] | RMSE del modelo: con → sin |")
    a("|---|---|---|---|---|---|")
    for nivel in ("ruta", "sentido"):
        for h in C.HORIZONTES:
            x = s["niveles"][nivel][str(h)]
            con, sin = x["con_el_registro"], x["sin_esos_dias"]
            d = sin["modelo_menos_promedio_dia_hora"]
            a(f"| {NOMBRE_NIVEL[nivel]} | {h} min | {num(con['modelo']['wape'])} → **{num(sin['modelo']['wape'])}** | "
              f"{num(con['promedio_dia_hora']['wape'])} → {num(sin['promedio_dia_hora']['wape'])} | "
              f"{num(d['diferencia'], 2, True)} [{num(d['ic95'][0], 2, True)}; {num(d['ic95'][1], 2, True)}] | "
              f"{num(con['modelo']['rmse'], 1)} → {num(sin['modelo']['rmse'], 1)} |")
    a("")
    x = s["niveles"]["ruta"]["60"]
    con_dif = resta(x["con_el_registro"]["modelo"]["wape"], x["con_el_registro"]["promedio_dia_hora"]["wape"])
    a(f"La conclusión no cambia. Sin esos días bajan el error del modelo y el del promedio, y la diferencia por ruta a 60 minutos "
      f"queda en {num(x['sin_esos_dias']['modelo_menos_promedio_dia_hora']['diferencia'], 2, True)} puntos (con el registro, "
      f"{num(con_dif, 2, True)}). El RMSE sí cambia mucho, porque un solo error de unas {num(round(r['subidas'], -3), 0)} subidas pesa más que "
      f"todos los demás juntos. Por segmento no se recalculó, porque las predicciones por segmento no se guardan; el registro está en "
      f"el segmento {r['nro_segmento']} de {r['ruta']} y se ve en `resultados/segmentos_prueba.csv`.")
    a("")


def vineta_domingos() -> list[str]:
    """La viñeta de los domingos corrientes para el README de la entrega (vacía si no hay análisis)."""
    ruta = C.AQUI / "resultados" / "desglose_domingos_festivos.json"
    if not ruta.exists():
        return []
    x = json.loads(ruta.read_text(encoding="utf-8"))["horizontes"]["60"]
    dom, fes, cra = x["todas_las_rutas"]["domingo"], x["todas_las_rutas"]["festivo"], x["por_ruta"]["CRA 54"]["domingo"]
    return [f"- **Donde no gana: los domingos corrientes.** Por ruta a 60 minutos, el modelo falla {pct(dom['modelo'])} y el promedio "
            f"por día y hora {pct(dom['promedio_dia_hora'])}; la pérdida está en CRA 54 ({num(cra['modelo'])} frente a "
            f"{num(cra['promedio_dia_hora'])}). La ventaja del grupo «domingo o festivo» viene de los festivos, en que el promedio "
            f"falla {pct(fes['promedio_dia_hora'])} y el modelo {pct(fes['modelo'])} "
            f"(`pronostico_corto_plazo/resultados/desglose_domingos_festivos.json`, análisis posterior a la prueba)."]


def vineta_anomalo() -> list[str]:
    """La viñeta del registro imposible para el README de la entrega (vacía si no hay análisis)."""
    ruta = C.AQUI / "resultados" / "sensibilidad_registro_anomalo.json"
    if not ruta.exists():
        return []
    s = json.loads(ruta.read_text(encoding="utf-8"))
    en_prueba = [r for r in s["registros_imposibles"] if r["periodo"] == "prueba"]
    if not en_prueba:
        return []
    r, x = en_prueba[0], s["niveles"]["ruta"]["60"]
    con, sin = x["con_el_registro"], x["sin_esos_dias"]
    return [f"- **Un registro imposible en la prueba.** La base trae {num(r['subidas'], 0)} subidas en un solo segmento de {r['ruta']} en "
            f"15 minutos ({'{2}-{1}-{0}'.format(*r['fecha'].split('-'))}, {r['hora']}). El protocolo no previó filtrarlo, así que las "
            f"cifras de la tabla lo incluyen; infla sobre todo el RMSE ({num(con['modelo']['rmse'], 1)} por ruta a 60 minutos). En un "
            f"análisis posterior, sin los {len(s['dias_de_ruta_excluidos'])} días que toca, el modelo falla {pct(sin['modelo']['wape'])} "
            f"y el promedio {pct(sin['promedio_dia_hora']['wape'])}, con un RMSE de {num(sin['modelo']['rmse'], 1)} "
            f"(`pronostico_corto_plazo/resultados/sensibilidad_registro_anomalo.json`)."]


def bloque_entrega(ver: dict, val: dict, pru: dict) -> list[str]:
    """La sección «Correcciones tras la retroalimentación del curso» del README de la entrega, con sus cifras."""
    niv = pru["niveles"]

    def fila(nivel: str, h: int) -> dict:
        return niv[nivel][str(h)]["todas_las_rutas"]

    def frente(nivel: str, h: int) -> str:
        t = fila(nivel, h)
        return f"{pct(t['modelo']['wape'])} frente a {pct(t['promedio_dia_hora']['wape'])}"

    r60 = fila("ruta", 60)
    ic = r60["ic95"]["modelo_menos_promedio_dia_hora"]["ic95"]
    s60 = pru["por_segmento"]["60"]
    v = ver["verificacion_extreme"]
    val60 = val["elegidos_con_todas_las_filas"]["ruta"]["60"]["wape"]
    base_val60 = val["lineas_base"]["ruta"]["promedio_dia_hora"]["60"]["wape"]
    sem60 = pru["secundarios"]["informacion_del_dia"]["60"]["semanal"]["wape"]
    rep = reproduccion()
    return [
        MARCA_INI + " (bloque generado por pronostico_corto_plazo/escribir_readme.py: no editar a mano) -->",
        "## Correcciones tras la retroalimentación del curso (17 de noviembre de 2026)",
        "",
        "La retroalimentación señaló tres faltas de la entrega. Las tres se corrigieron en la carpeta "
        "[`pronostico_corto_plazo/`](pronostico_corto_plazo/README.md), que resuelve el problema tal como lo pide la "
        "especificación: **el pronóstico de las subidas de los siguientes 30, 60 y 120 minutos por ruta, sentido y "
        "segmento**. En el informe y en el cuaderno es la sección P"
        + ("; desde el 18 de noviembre lo sirve la API (`POST /api/v1/predictions/corto-plazo`) y es lo primero de la "
           "pantalla Pronóstico del tablero." if rep and rep["coincide"] else "."),
        "",
        "| Lo que se señaló | Lo que se hizo | Resultado | Evidencia |",
        "|---|---|---|---|",
        "| Se pronosticaba a siete días por ruta y hora de salida: no es el problema que se pidió, y las cifras no se "
        "pueden comparar con las de otros equipos | Cada media hora, de 04:00 a 21:00, se pronostican las subidas de los "
        "siguientes 30, 60 y 120 minutos, con MAE, RMSE, WAPE y sMAPE por ruta y franja y frente a las líneas base del "
        "enunciado (promedio por día y hora y última semana) | Por ruta, en la prueba: WAPE de "
        f"**{frente('ruta', 60)}** del promedio por día y hora a 60 minutos (diferencia con IC del 95 % de "
        f"{num(ic[0], 2, True)} a {num(ic[1], 2, True)} puntos); {frente('ruta', 30)} a 30 minutos y {frente('ruta', 120)} "
        "a 120 | `pronostico_corto_plazo/resultados/prueba.json` |",
        "| Los modelos se eligieron y se reportaron sobre los mismos meses de 2025 | El protocolo se confirmó en git antes "
        "de correr la validación: se entrena con 2023 y 2024, **se elige todo con enero a junio de 2025** y **se reporta una sola vez "
        "con julio a diciembre de 2025**, en tres commits ordenados del 17-11-2026: protocolo "
        f"(`{COMMITS['protocolo'][0]}`, {COMMITS['protocolo'][1]}), validación (`{COMMITS['validacion'][0]}`, "
        f"{COMMITS['validacion'][1]}) y prueba (`{COMMITS['prueba'][0]}`, {COMMITS['prueba'][1]}) | En la validación, el "
        f"modelo elegido falla {pct(val60)} por ruta a 60 minutos (el promedio, {pct(base_val60)}); en la prueba, que no se "
        f"usó para elegir nada, {pct(r60['modelo']['wape'])} (el promedio, {pct(r60['promedio_dia_hora']['wape'])}) | "
        "`pronostico_corto_plazo/PROTOCOLO.md`, `pronostico_corto_plazo/resultados/validacion.json`, "
        "`pronostico_corto_plazo/resultados/seleccion.json` y el historial de git |",
        "| El modelo por segmento se entrenó con 37 días: lo espacial no quedó validado | Se asignaron a su segmento las "
        f"subidas de los tres años ({num(ver['panel']['subidas'], 0)}) con la regla de Extreme, que reproduce su tabla "
        f"en los 58 días que la base trae (el {pct(v['subidas_en_el_mismo_segmento_pct'], 3)} de las subidas en el mismo "
        "segmento). El modelo por segmento se entrena con más de dos años y se prueba en seis meses | A 60 minutos: por "
        f"sentido, {frente('sentido', 60)}; por segmento, {frente('segmento', 60)}, en "
        f"{num(fila('segmento', 60)['modelo']['n'], 0)} celdas de segmento e instante. El modelo gana al promedio en "
        f"{s60['segmentos_en_que_gana_al_promedio']} de los {s60['segmentos_con_subidas']} segmentos con subidas | "
        "`pronostico_corto_plazo/panel/verificacion_extreme.json`, `pronostico_corto_plazo/resultados/segmentos_prueba.csv` |",
        "",
        "Lo que se conserva y lo que falta:",
        "",
        "- **El pronóstico a siete días se conserva** porque es el que usa la programación semanal, pero ya no se presenta "
        "como el del enunciado. Con el protocolo nuevo, el modelo que solo usa lo que se sabe una semana antes falla "
        f"{pct(sem60)} por ruta a 60 minutos en la prueba; con lo observado en el mismo día, {pct(r60['modelo']['wape'])}.",
        "- **La prueba no es ciega en sentido estricto:** los meses de 2025 se conocían por los experimentos anteriores, con "
        "otro objetivo. Ninguna decisión del experimento nuevo usa julio a diciembre.",
        "- **El sentido es una aproximación** (la mitad del ciclo), y se midió cuánto afecta "
        "(`pronostico_corto_plazo/panel/revision_sentido.json`).",
        *vineta_domingos(),
        *vineta_anomalo(),
        *vineta_api(rep),
        "",
        MARCA_FIN,
    ]


def vineta_api(rep: dict | None) -> list[str]:
    """La viñeta de la API: ya lo sirve y reproduce la prueba (o, si no se ha comprobado, que falta llevarlo)."""
    if not rep or not rep["coincide"]:
        return ["- **Falta llevarlo a la API.** La API sigue pronosticando por hora de salida, y su modelo por segmento es "
                "el de 37 días. Integrar este pronóstico es el primer pendiente de `PLAN_EVOLUCION.md` (sección 7)."]
    return ["- **Ya está en la API y en el tablero** (18 de noviembre de 2026). `POST /api/v1/predictions/corto-plazo` lo "
            "calcula y lo guarda por ruta, sentido y segmento, con su banda, sus líneas base, su explicación y la "
            "recomendación de §10.2; el ciclo diario también lo genera. La API usa los mismos árboles, verificados con "
            f"SHA-256, y reproduce las {num(rep['filas'], 0)} predicciones guardadas de la prueba "
            "(`api_frecuencias/docs/evidencias/modelo/corto_plazo_reproduccion.md`). En el tablero es lo primero de "
            "Pronóstico. Falta alimentarlo con la captura en vivo: hoy lee el panel de 2023 a 2025 "
            "(`PLAN_EVOLUCION.md`, sección 7)."]


def actualizar_entrega(lineas: list[str]) -> None:
    """Reescribe, en el README de la entrega (la carpeta de arriba), el bloque que va entre las marcas corto_plazo."""
    ruta = C.AQUI.parent / "README.md"
    if not ruta.exists():
        return
    crudo = ruta.read_bytes()
    fin = "\r\n" if b"\r\n" in crudo else "\n"
    texto = crudo.decode("utf-8").replace("\r\n", "\n")
    a, b = texto.find(MARCA_INI), texto.find(MARCA_FIN)
    if a < 0 or b < a:
        print("README de la entrega: no tiene las marcas corto_plazo; no se toca")
        return
    texto = texto[:a] + "\n".join(lineas) + texto[b + len(MARCA_FIN):]
    ruta.write_bytes(texto.replace("\n", fin).encode("utf-8"))
    print("README de la entrega: bloque de correcciones actualizado")


if __name__ == "__main__":
    main()
