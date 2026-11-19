"""Macros de LaTeX con las cifras del pronóstico de corto plazo (sección P del informe), leídas de sus archivos de
resultados: ninguna se escribe a mano.

    python EntregaFinal/informe/cifras_corto_plazo.py      -> informe/generado/corto_plazo.tex

Fuentes (en EntregaFinal/pronostico_corto_plazo/): panel/verificacion_extreme.json, panel/revision_sentido.json,
resultados/comprobacion_fuga.json, resultados/validacion.json, resultados/seleccion.json, resultados/prueba.json,
resultados/sensibilidad_registro_anomalo.json, resultados/desglose_domingos_festivos.json y resultados/figuras.json.
Los nombres de las macros no pueden llevar cifras: los horizontes van en romanos (XXX = 30, LX = 60, CXX = 120 minutos).
"""
from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CP = AQUI.parent / "pronostico_corto_plazo"
DESTINO = AQUI / "generado" / "corto_plazo.tex"
ROMANO = {"30": "XXX", "60": "LX", "120": "CXX"}
NIVEL = {"ruta": "Ruta", "sentido": "Sent", "segmento": "Seg"}
RUTA = {"SILENCIO": "Sil", "CRA 54": "Cra", "CL 72": "Cl"}
macros: list[tuple[str, str, str]] = []


def num(x, dec: int = 2) -> str:
    """12.345 -> «12,35»; 44871165 -> «44.871.165»; los negativos, con el signo menos de modo matemático."""
    if x is None:
        return "s.\\,d."
    d = Decimal(str(x)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
    s = f"{abs(d):,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return ("$-$" if d < 0 else "") + s


def macro(nombre: str, valor: str, fuente: str) -> None:
    if not nombre.isalpha():
        raise ValueError(f"nombre de macro inválido: {nombre}")
    macros.append((nombre, valor, fuente))


def leer(rel: str) -> dict:
    return json.loads((CP / rel).read_text(encoding="utf-8"))


def main() -> None:
    ver, sen = leer("panel/verificacion_extreme.json"), leer("panel/revision_sentido.json")
    val, sel, pru = leer("resultados/validacion.json"), leer("resultados/seleccion.json"), leer("resultados/prueba.json")
    fig = leer("resultados/figuras.json")

    f = "panel/verificacion_extreme.json"
    macro("CPEventos", num(ver["eventos"]["eventos"], 0), f)
    macro("CPSubidas", num(ver["panel"]["subidas"], 0), f)
    macro("CPCeldas", num(ver["panel"]["filas"], 0), f)
    v = ver["verificacion_extreme"]
    macro("CPVerSubidas", num(v["subidas_extreme"], 0), f)
    macro("CPVerViajes", num(v["viajes_en_la_tabla_de_extreme"], 0), f)
    macro("CPVerMismoSegmento", num(v["subidas_en_el_mismo_segmento_pct"], 3), f)
    macro("CPVerCeldasIguales", num(v["celdas_identicas_pct"], 2), f)
    macro("CPVerMismoTotal", num(v["viajes_con_el_mismo_total_pct"], 0), f)
    f = "panel/revision_sentido.json"
    for ruta, r in RUTA.items():
        macro(f"CPSentCerca{r}", num(sen["geometria"][ruta]["regreso_con_la_ida_a_menos_de_30_m_pct"], 0), f)
        macro(f"CPSentBien{r}", num(sen["tiempo_de_viaje"][ruta]["subidas_a_menos_de_45_min_pct"], 0), f)
        macro(f"CPSentOtro{r}", num(sen["tiempo_de_viaje"][ruta]["de_ellas_cuadran_en_el_otro_sentido_pct_del_total"], 0), f)

    fuga = leer("resultados/comprobacion_fuga.json")
    f = "resultados/comprobacion_fuga.json"
    macro("CPFugaComprobaciones", num(fuga["comprobaciones"], 0), f)
    macro("CPFugaValores", num(fuga["valores_comparados"], 0), f)
    macro("CPFugaDiferencias", num(fuga["diferencias"], 0), f)

    # la API reproduce la prueba (api_frecuencias/scripts/verificar_corto_plazo.py)
    repro = json.loads((AQUI.parent / "api_frecuencias" / "docs" / "evidencias" / "modelo"
                        / "corto_plazo_reproduccion.json").read_text(encoding="utf-8"))
    if not repro["coincide"]:
        raise SystemExit("La API no reproduce la prueba: no se puede decir que sirve el mismo modelo")
    f = "../api_frecuencias/docs/evidencias/modelo/corto_plazo_reproduccion.json"
    macro("CPReproFilas", num(sum(x["filas_en_las_dos"] for x in repro["predicciones"].values()), 0), f)

    f = "resultados/validacion.json"
    for nivel, n in NIVEL.items():
        for conjunto, c in (("semanal", "Semanal"), ("con_hoy", "ConHoy"), ("completo", "Completo")):
            macro(f"CPVal{n}{c}", num(val["A_conjunto"][nivel][conjunto]["wape_medio"]), f)
        macro(f"CPVal{n}Prom", num(val["lineas_base"][nivel]["promedio_dia_hora"]["wape_medio"]), f)
        macro(f"CPVal{n}Final", num(val["elegidos_con_todas_las_filas"][nivel]["wape_medio"]), f)
    estr = val["C_estructura"]
    macro("CPValSentDirecto", num(estr["sentido"]["directo"]["wape_medio"]), f)
    macro("CPValSentSuma", num(estr["sentido"]["suma_de_segmentos"]["wape_medio"]), f)
    macro("CPValSegDirecto", num(estr["segmento"]["directo"]["wape_medio"]), f)
    macro("CPValSegConciliado", num(estr["segmento"]["conciliado_con_la_ruta"]["wape_medio"]), f)
    macro("CPValSegReparto", num(estr["segmento"]["reparto_fijo_de_la_ruta"]["wape_medio"]), f)
    # Lo elegido, en palabras: las frases se arman aquí para que el texto diga exactamente lo que dice seleccion.json.
    conjunto = {"semanal": "el conjunto semanal", "con_hoy": "el conjunto con lo observado en el día",
                "completo": "el conjunto más completo (con las salidas ya despachadas)"}
    hiper = {"base": "la configuración base", "arboles_pequenos": "la de árboles pequeños", "arboles_grandes": "la de árboles grandes"}
    estructura = {"directo": "el modelo directo", "suma_de_segmentos": "la suma de los segmentos",
                  "conciliado_con_la_ruta": "el modelo conciliado con el pronóstico de la ruta"}
    f = "resultados/seleccion.json"

    def frase(elegido: dict, nombres: dict) -> str:
        """«en los tres niveles X» si coinciden; si no, «X por ruta, Y por sentido y Z por segmento»."""
        ruta, sentido, segmento = (nombres[elegido[n]] for n in NIVEL)
        if ruta == sentido == segmento:
            return f"en los tres niveles {ruta}"
        return f"{ruta} por ruta, {sentido} por sentido y {segmento} por segmento"

    macro("CPEligeConjuntos", frase(sel["conjunto"], conjunto), f)
    macro("CPEligeHiper", frase({n: sel["hiper"][n]["nombre"] for n in NIVEL}, hiper), f)
    macro("CPEligeSentEstructura", estructura[sel["estructura"]["sentido"]], f)
    macro("CPEligeSegEstructura", estructura[sel["estructura"]["segmento"]], f)

    f = "resultados/prueba.json"
    macro("CPDiasPrueba", num(pru["dias_del_periodo"], 0), f)
    macro("CPDiasPruebaConDatos", num(min(pru["dias_con_datos_en_la_prueba"].values()), 0), f)
    for nivel, n in NIVEL.items():
        for h, rom in ROMANO.items():
            b = pru["niveles"][nivel][h]
            t = b["todas_las_rutas"]
            for clave, c in (("modelo", "Mod"), ("promedio_dia_hora", "Prom"), ("ultima_semana", "Sem"), ("persistencia", "Pers")):
                macro(f"CP{n}{c}{rom}", num(t[clave]["wape"]), f)
            m = t["modelo"]
            macro(f"CP{n}MAE{rom}", num(m["mae"]), f)
            macro(f"CP{n}RMSE{rom}", num(m["rmse"]), f)
            macro(f"CP{n}SMAPE{rom}", num(m["smape"]), f)
            macro(f"CP{n}Sesgo{rom}", num(m["sesgo_pct"]), f)
            macro(f"CP{n}Media{rom}", num(m["media_real"], 1), f)
            macro(f"CP{n}Filas{rom}", num(m["n"], 0), f)
            ic = t["ic95"]
            macro(f"CP{n}ModIC{rom}", f"{num(ic['modelo']['ic95'][0])}--{num(ic['modelo']['ic95'][1])}", f)
            d = ic["modelo_menos_promedio_dia_hora"]["ic95"]
            macro(f"CP{n}DifIC{rom}", f"{num(d[0])} a {num(d[1])}", f)
            macro(f"CP{n}DifFrase{rom}", "queda entero bajo cero" if d[1] < 0 else "incluye el cero", f)
            # la diferencia, con los decimales escritos en el archivo (no en binario): la misma que da el README
            macro(f"CP{n}Dif{rom}", num(Decimal(str(m["wape"])) - Decimal(str(t["promedio_dia_hora"]["wape"]))), f)
            macro(f"CP{n}Quita{rom}", num((1 - m["wape"] / t["promedio_dia_hora"]["wape"]) * 100, 0), f)
            macro(f"CP{n}Cob{rom}", num(b["banda_p10_p90"]["todas_las_rutas"]["cobertura_pct"], 1), f)
            fr = t["por_franja"]
            for franja, c in (("pico", "Pico"), ("valle", "Valle")):
                macro(f"CP{n}{c}Mod{rom}", num(fr["modelo"][franja]["wape"]), f)
                macro(f"CP{n}{c}Prom{rom}", num(fr["promedio_dia_hora"][franja]["wape"]), f)
            if nivel == "ruta":
                for ruta, r in RUTA.items():
                    macro(f"CP{r}Mod{rom}", num(b["por_ruta"][ruta]["modelo"]["wape"]), f)
                    macro(f"CP{r}Prom{rom}", num(b["por_ruta"][ruta]["promedio_dia_hora"]["wape"]), f)
                    macro(f"CP{r}MAE{rom}", num(b["por_ruta"][ruta]["modelo"]["mae"], 1), f)
                    macro(f"CP{r}Media{rom}", num(b["por_ruta"][ruta]["modelo"]["media_real"], 0), f)
                tipos = b["por_tipo_de_dia"]
                for tipo, c in (("laboral", "Lab"), ("sábado", "Sab"), ("domingo o festivo", "Dom")):
                    macro(f"CPRuta{c}Mod{rom}", num(tipos[tipo]["modelo"]), f)
                    macro(f"CPRuta{c}Prom{rom}", num(tipos[tipo]["promedio_dia_hora"]), f)
                meses = [v["modelo"] for v in b["por_mes"].values()]
                macro(f"CPRutaMesMin{rom}", num(min(meses)), f)
                macro(f"CPRutaMesMax{rom}", num(max(meses)), f)
    for h, rom in ROMANO.items():
        s = pru["por_segmento"][h]
        macro(f"CPSegConSubidas{rom}", num(s["segmentos_con_subidas"], 0), f)
        macro(f"CPSegSesgoMediano{rom}", num(s["sesgo_abs_mediano_pct"], 1), f)
        macro(f"CPSegSesgoPonderado{rom}", num(s["sesgo_abs_medio_ponderado_pct"], 1), f)
        macro(f"CPSegSesgoMenorCinco{rom}", num(s["segmentos_con_sesgo_abs_menor_de_5_pct"], 0), f)
        macro(f"CPSegGana{rom}", num(s["segmentos_en_que_gana_al_promedio"], 0), f)
        macro(f"CPSegGanaSubidas{rom}", num(s["subidas_en_segmentos_en_que_gana_pct"], 1), f)
        sec = pru["secundarios"]
        macro(f"CPSemanal{rom}", num(sec["informacion_del_dia"][h]["semanal"]["wape"]), f)
        d = sec["informacion_del_dia"][h]["ic95"]["elegido_menos_semanal"]["ic95"]
        macro(f"CPSemanalDifIC{rom}", f"{num(d[0])} a {num(d[1])}", f)
        for lat, c in (("15", "Quince"), ("30", "Treinta")):
            macro(f"CPRetraso{c}{rom}", num(sec["retraso_de_la_captura"][h].get(lat)), f)
        for clave, v in pru["por_sentido"][h].items():
            ruta, sentido = clave.split(" · ")
            macro(f"CP{RUTA[ruta]}{sentido.capitalize()}Mod{rom}", num(v["modelo"]["wape"]), f)
            macro(f"CP{RUTA[ruta]}{sentido.capitalize()}Prom{rom}", num(v["promedio_dia_hora"]["wape"]), f)
    imp = pru["importancia"]["ruta"]["60"]
    primera = next(iter(imp))
    macro("CPImportanciaPrimera", primera.replace("_", "\\_"), f)
    macro("CPImportanciaPrimeraPct", num(imp[primera] * 100, 0), f)
    macro("CPLightgbm", pru["versiones"]["lightgbm"], f)
    # El registro imposible de la prueba y el análisis posterior sin los días que toca (no estaba en el protocolo).
    f = "resultados/sensibilidad_registro_anomalo.json"
    sen_a = leer(f)
    nombres_mes = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")

    def fecha_larga(iso: str) -> str:
        a, m, d = (int(x) for x in iso.split("-"))
        return f"{d} de {nombres_mes[m - 1]} de {a}"

    en_prueba = next(r for r in sen_a["registros_imposibles"] if r["periodo"] == "prueba")
    otro = next(r for r in sen_a["registros_imposibles"] if r["periodo"] != "prueba")
    macro("CPAnomSubidas", num(en_prueba["subidas"], 0), f)
    macro("CPAnomFecha", fecha_larga(en_prueba["fecha"]), f)
    macro("CPAnomHora", en_prueba["hora"], f)
    macro("CPAnomSegmento", num(en_prueba["nro_segmento"], 0), f)
    macro("CPAnomRuta", en_prueba["ruta"].replace(" ", "~"), f)
    macro("CPAnomMediana", num(en_prueba["mediana_de_la_ruta_en_ese_bloque"], 0), f)
    macro("CPAnomOtroSubidas", num(otro["subidas"], 0), f)
    macro("CPAnomOtroFecha", fecha_larga(otro["fecha"]), f)
    macro("CPAnomDias", num(len(sen_a["dias_de_ruta_excluidos"]), 0), f)
    for nivel, n in (("ruta", "Ruta"), ("sentido", "Sent")):
        for h, rom in ROMANO.items():
            sin = sen_a["niveles"][nivel][h]["sin_esos_dias"]
            macro(f"CPSin{n}Mod{rom}", num(sin["modelo"]["wape"]), f)
            macro(f"CPSin{n}Prom{rom}", num(sin["promedio_dia_hora"]["wape"]), f)
            macro(f"CPSin{n}RMSE{rom}", num(sin["modelo"]["rmse"], 1), f)
            macro(f"CPSin{n}Dif{rom}", num(sin["modelo_menos_promedio_dia_hora"]["diferencia"]), f)
            ic = sin["modelo_menos_promedio_dia_hora"]["ic95"]
            macro(f"CPSin{n}DifIC{rom}", f"{num(ic[0])} a {num(ic[1])}", f)

    # Domingos y festivos por separado (análisis posterior a la prueba, con las predicciones guardadas).
    f = "resultados/desglose_domingos_festivos.json"
    des = leer(f)["horizontes"]
    for h, rom in ROMANO.items():
        todas = des[h]["todas_las_rutas"]
        for grupo, c in (("domingo", "DomSolo"), ("festivo", "Fest")):
            macro(f"CP{c}Mod{rom}", num(todas[grupo]["modelo"]), f)
            macro(f"CP{c}Prom{rom}", num(todas[grupo]["promedio_dia_hora"]), f)
        macro(f"CPDomSoloCraMod{rom}", num(des[h]["por_ruta"]["CRA 54"]["domingo"]["modelo"]), f)
        macro(f"CPDomSoloCraProm{rom}", num(des[h]["por_ruta"]["CRA 54"]["domingo"]["promedio_dia_hora"]), f)
    macro("CPDomSoloDias", num(des["60"]["todas_las_rutas"]["domingo"]["dias"], 0), f)
    macro("CPFestDias", num(des["60"]["todas_las_rutas"]["festivo"]["dias"], 0), f)

    f = "resultados/figuras.json"
    d = fig["dia_de_ejemplo"]
    macro("CPEjemploFecha", "{2}-{1}-{0}".format(*d["fecha"].split("-")), f)
    macro("CPEjemploMod", num(d["wape_modelo"], 1), f)
    macro("CPEjemploProm", num(d["wape_promedio_ese_dia"], 1), f)

    DESTINO.parent.mkdir(exist_ok=True)
    lineas = ["% Generado por informe/cifras_corto_plazo.py: no editar a mano.",
              "% Cada macro lleva al final el archivo de pronostico_corto_plazo/ del que sale."]
    lineas += [f"\\newcommand{{\\{n}}}{{{v}}}% {f}" for n, v, f in macros]
    DESTINO.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"{DESTINO.relative_to(AQUI.parent)}: {len(macros)} macros")


if __name__ == "__main__":
    main()
