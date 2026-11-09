"""Genera app/muestra_datos.js, los datos de ejemplo reales de app/muestra.html (la muestra de componentes).

Ninguna cifra de la muestra se escribe a mano: todas salen de los archivos de resultados de los experimentos y cada
una lleva archivo, clave, experimento, si tiene revisor independiente (sí / parcial / no, según el inventario de cifras
de la app) y la revisión que lo respalda. Solo lee archivos locales; no toca la base de datos.

Uso, desde la carpeta del proyecto:  PYTHONIOENCODING=utf-8 python app/generar_muestra_datos.py
"""
import csv
import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "app" / "muestra_datos.js"

# Revisiones independientes que respaldan cada archivo (ver la sección «Verificación» de cada README).
REV_E11 = ("sí", "E11 README §8, revisión adversarial del 05-10-2026: recalculado con código propio desde predicciones_2025.parquet")
REV_E12 = ("sí", "E12 README «Verificación» del 07-10-2026: 55 resultados recalculados con código propio, diferencia menor que 1e-9")
REV_D5 = ("sí", "D5 README §8 del 05-10-2026: tabla de escenarios recalculada desde decisiones_2025.parquet")
REV_COSTOS = ("parcial", "costos/README.md §11 del 06-10-2026 (revisión adversarial con scripts propios); la corrección de jornada se aplicó después y el revisor no volvió a correr el optimizador")
REV_SIM = ("sí", "simulacion_ahorro/README.md «Verificación independiente» del 07-10-2026: 20 cifras reproducidas con diferencia menor que 6e-15")
REV_E7 = ("sí", "E7 README §9: β recalculada desde datos crudos (0,726, IC 0,698-0,754)")
REV_BT = ("parcial", "sistema_tiempo_real/README.md §7: la corrida del 07-10 tuvo revisor; la del 13-10 (vigente) reusa el mismo código; verificar_plan.py reproduce el plan en 4.029 de 4.029 horas")
REV_P1 = ("parcial", "validacion_costos_fuente.json: 153 de 153 horas iguales al MILP de referencia; sin revisor independiente de la actualización del 06-10-2026")
REV_P2 = ("no", "P2 README §10: 269 de 269 cifras comprobadas por un script del autor; sin revisor adversarial independiente")


def leer_json(ruta):
    return json.loads((RAIZ / ruta).read_text(encoding="utf-8"))


def leer_csv_pc(ruta):
    """CSV con ';' y coma decimal (costos/ y simulacion_ahorro/)."""
    return pd.read_csv(RAIZ / ruta, sep=";", decimal=",", encoding="utf-8-sig")


def fuente(archivo, clave, experimento, revision, nota=None):
    d = {"archivo": archivo, "clave": clave, "experimento": experimento, "verificado": revision[0], "revision": revision[1]}
    if nota:
        d["nota"] = nota
    return d


def cifra(valor, unidad, decimales, archivo, clave, experimento, revision, nota=None):
    d = {"valor": float(valor), "unidad": unidad, "decimales": decimales}
    d.update(fuente(archivo, clave, experimento, revision, nota))
    return d


def main():
    # --- Error del pronóstico (E11 y E12) ---------------------------------------------------------------------------
    e11 = leer_json("experimentos/E11_modelo_mejorado/resultados.json")
    e12 = leer_json("experimentos/E12_comparacion_modelos/resultados.json")
    hib = leer_json("experimentos/E12_comparacion_modelos/resultados/hibrido_V4_chronos2cov.json")
    h = e11["horizontes"]
    hibrido_prod = e12["produccion"]["costos"]["hibrido_V4_chronos2cov"]
    A_E11, A_E12 = "experimentos/E11_modelo_mejorado/resultados.json", "experimentos/E12_comparacion_modelos/resultados.json"
    cifras = {
        "error_regla_manual": cifra(h["B1_H7"]["global_"]["WAPE"], "%", 2, A_E11, "horizontes.B1_H7.global_.WAPE", "E11 (B1 del protocolo)", REV_E11),
        "error_e1": cifra(h["V0_H7"]["global_"]["WAPE"], "%", 2, A_E11, "horizontes.V0_H7.global_.WAPE", "E1 / E11 (V0 reproduce E1)", REV_E11),
        "error_modelo_final": cifra(h["SEL_H7"]["global_"]["WAPE"], "%", 2, A_E11, "horizontes.SEL_H7.global_.WAPE", "E11", REV_E11),
        "error_hibrido": cifra(hibrido_prod["WAPE_2025"], "%", 2, A_E12, "produccion.costos.hibrido_V4_chronos2cov.WAPE_2025", "E12", REV_E12),
    }
    cifras["error_hibrido"]["ic_dif_vs_final"] = [round(x, 3) for x in hibrido_prod["dif_2025"]]
    cifras["error_hibrido"]["clave_ic"] = "produccion.costos.hibrido_V4_chronos2cov.dif_2025"

    # --- Salidas, buses-hora, espera y sobrecapacidad: hoy (D5 S0) y con el plan (costos) ---------------------------
    esc = pd.read_csv(RAIZ / "experimentos/D5_optimizacion_milp/escenarios.csv", encoding="utf-8")
    s0 = esc[(esc["ruta"] == "Todas") & (esc["tipo_dia"] == "Todos") & (esc["escenario"] == "S0 oferta real")].iloc[0]
    reo = leer_csv_pc("costos/resultados/d5_reoptimizado.csv")
    plan = reo[reo["corrida"] == "D5 costos nuevos, pago por hora, e=0,5"].iloc[0]
    A_D5, A_REO = "experimentos/D5_optimizacion_milp/escenarios.csv", "costos/resultados/d5_reoptimizado.csv"
    F_S0 = "fila ruta = 'Todas', tipo_dia = 'Todos', escenario = 'S0 oferta real', columna "
    F_PL = "fila corrida = 'D5 costos nuevos, pago por hora, e=0,5', columna "
    cifras.update({
        "salidas_dia_hoy": cifra(s0["salidas_dia"], "salidas/día", 0, A_D5, F_S0 + "salidas_dia", "D5", REV_D5),
        "salidas_dia_plan": cifra(plan["salidas_dia"], "salidas/día", 0, A_REO, F_PL + "salidas_dia", "costos (reoptimizar_d5.py)", REV_SIM),
        "buses_hora_hoy": cifra(s0["buses_hora_dia"], "buses-hora/día", 0, A_D5, F_S0 + "buses_hora_dia", "D5", REV_D5),
        "buses_hora_plan": cifra(plan["buses_hora_dia"], "buses-hora/día", 0, A_REO, F_PL + "buses_hora_dia", "costos", REV_COSTOS),
        "espera_hoy": cifra(s0["espera_media_min"], "min", 2, A_D5, F_S0 + "espera_media_min", "D5", REV_D5),
        "espera_plan": cifra(plan["espera_media_min"], "min", 2, A_REO, F_PL + "espera_media_min", "costos", REV_COSTOS),
        "sobrecapacidad_hoy": cifra(s0["pax_sobre_capacidad_dia"], "pasajeros/día", 0, A_D5, F_S0 + "pax_sobre_capacidad_dia", "D5", REV_D5),
        "sobrecapacidad_plan": cifra(plan["pax_sobre_capacidad_dia"], "pasajeros/día", 0, A_REO, F_PL + "pax_sobre_capacidad_dia", "costos", REV_COSTOS),
        "pax_riesgo_plan": cifra(plan["pax_perdidos_dia_central"], "pasajeros/día", 0, A_REO, F_PL + "pax_perdidos_dia_central", "costos", REV_SIM),
        "ahorro_operativo_plan": cifra(plan["ahorro_operativo_pago_hora_Mcop"], "M COP/año", 0, A_REO, F_PL + "ahorro_operativo_pago_hora_Mcop", "costos", REV_SIM),
        "saldo_conservador": cifra(plan["neto_pago_hora_beta070_Mcop"], "M COP/año", 0, A_REO, F_PL + "neto_pago_hora_beta070_Mcop", "costos", REV_SIM),
        "saldo_simetrico": cifra(plan["neto_simetrico_pago_hora_beta070_Mcop"], "M COP/año", 0, A_REO, F_PL + "neto_simetrico_pago_hora_beta070_Mcop", "costos", REV_SIM),
    })

    # --- β y backtest -----------------------------------------------------------------------------------------------
    e7 = leer_json("experimentos/E7_elasticidad/resultados.json")
    cifras["beta"] = cifra(e7["sintesis"]["beta_central"], "", 2, "experimentos/E7_elasticidad/resultados.json", "sintesis.beta_central", "E7", REV_E7)
    filas = list(csv.DictReader(open(RAIZ / "sistema_tiempo_real/backtest/decision_vs_oraculo.csv", encoding="utf-8")))
    todos = [r for r in filas if r.get("grupo") == "Todos" and str(r.get("horas_desde")) == "7"]

    def fila(sub):
        return next(r for r in todos if sub in r["escenario"])

    bt = {k: fila(v) for k, v in {"plan": "Plan semanal", "real": "Oferta real", "motor": "Dinámico con nowcast"}.items()}
    cifras["backtest"] = {
        "plan_error_salidas_h": round(float(bt["plan"]["error_abs_medio_salidas_hora"]), 2),
        "plan_pct_horas_exactas": round(float(bt["plan"]["pct_horas_exactas"]), 1),
        "real_error_salidas_h": round(float(bt["real"]["error_abs_medio_salidas_hora"]), 2),
        "real_pct_horas_exactas": round(float(bt["real"]["pct_horas_exactas"]), 1),
        "motor_error_salidas_h": round(float(bt["motor"]["error_abs_medio_salidas_hora"]), 2),
    }
    cifras["backtest"].update(fuente("sistema_tiempo_real/backtest/decision_vs_oraculo.csv",
                                     "filas grupo = 'Todos', horas_desde = 7; columnas error_abs_medio_salidas_hora y pct_horas_exactas",
                                     "sistema_tiempo_real (backtest.py, corrida del 13-10-2026)", REV_BT))

    # --- WAPE por ruta ----------------------------------------------------------------------------------------------
    rutas = ["SILENCIO", "CRA 54", "CL 72"]
    wape_por_ruta = {
        "rutas": rutas,
        "regla_manual": {r: round(h["B1_H7"]["por_ruta"][r]["WAPE"], 2) for r in rutas},
        "e1": {r: round(h["V0_H7"]["por_ruta"][r]["WAPE"], 2) for r in rutas},
        "modelo_final": {r: round(h["SEL_H7"]["por_ruta"][r]["WAPE"], 2) for r in rutas},
        "hibrido": {r: round(hib["por_ruta"][r]["WAPE"], 2) for r in rutas},
        "global": {"regla_manual": round(h["B1_H7"]["global_"]["WAPE"], 2), "e1": round(h["V0_H7"]["global_"]["WAPE"], 2),
                   "modelo_final": round(h["SEL_H7"]["global_"]["WAPE"], 2), "hibrido": round(hibrido_prod["WAPE_2025"], 2)},
        "fuente": fuente(A_E11 + " y experimentos/E12_comparacion_modelos/resultados/hibrido_V4_chronos2cov.json",
                         "horizontes.{B1_H7, V0_H7, SEL_H7}.por_ruta.<ruta>.WAPE; híbrido: por_ruta.<ruta>.WAPE", "E11 / E12",
                         ("sí", REV_E11[1] + "; " + REV_E12[1])),
    }

    # --- Serie diaria de CRA 54, mayo y junio de 2025 ----------------------------------------------------------------
    pred = pd.read_parquet(RAIZ / "experimentos/E11_modelo_mejorado/predicciones_2025.parquet")
    sel = pred[(pred["horizonte"] == 7) & (pred["variante"] == "V4") & (pred["ruta"] == "CRA 54")].copy()
    sel["dia"] = pd.to_datetime(sel["dia"]).dt.date
    g = sel.groupby("dia").agg(real=("real", "sum"), b1=("pred_B1_manual", "sum"), v4=("prediccion", "sum"), tipo_dia=("tipo_dia", "first")).reset_index()
    hp = pd.read_parquet(RAIZ / "experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet")
    hp = hp[(hp["ruta"] == "CRA 54") & (hp["horizonte"] == 7)].copy()
    hp["dia"] = pd.to_datetime(hp["dia"]).dt.date
    g = g.merge(hp.groupby("dia").agg(hibrido=("prediccion", "sum")).reset_index(), on="dia", how="left")
    v = g[(g["dia"] >= dt.date(2025, 5, 1)) & (g["dia"] <= dt.date(2025, 6, 30))]
    serie_diaria = {
        "titulo": "CRA 54, pasajeros por día, mayo y junio de 2025",
        "dias": [d.isoformat() for d in v["dia"]],
        "tipo_dia": [str(t) for t in v["tipo_dia"]],
        "real": [int(round(x)) for x in v["real"]],
        "regla_manual": [int(round(x)) for x in v["b1"]],
        "modelo_final": [int(round(x)) for x in v["v4"]],
        "hibrido": [int(round(x)) if pd.notna(x) else None for x in v["hibrido"]],
        "fuente": fuente(
            "experimentos/E11_modelo_mejorado/predicciones_2025.parquet y experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet",
            "horizonte == 7, variante == 'V4', ruta == 'CRA 54'; suma por día de real, pred_B1_manual y prediccion; híbrido: suma por día de prediccion",
            "E11 / E12", ("sí", REV_E11[1] + "; " + REV_E12[1]),
            "Sumas diarias (las 17 horas de salida). El error oficial (WAPE) se mide por franja de hora, no sobre estas sumas."),
    }

    # --- Salidas por hora de CRA 54 en día laboral: hoy y con el plan (costos con fuente) ----------------------------
    texto = (RAIZ / "planificador_datos.js").read_text(encoding="utf-8")
    plan_js = json.loads(texto[texto.index("{"):texto.rstrip().rstrip(";").rfind("}") + 1])
    lab = plan_js["rutas"]["CRA 54"]["tipos"]["Laboral"]["horas"]
    campos = plan_js["campos_hora"]
    horas = [int(f[campos.index("hora")]) for f in lab]
    hoy = [int(round(f[campos.index("salidas_actuales")])) for f in lab]
    d5_original = [int(f[campos.index("solucion_D5")]) for f in lab]
    p1 = leer_json("experimentos/P1_planificador/validacion_costos_fuente.json")
    caso = next(c for c in p1["casos"] if c["juego"] == "hora" and c["elasticidad"] == 0.5 and c["ruta"] == "CRA 54" and c["tipo_dia"] == "Laboral")
    xp = caso["x_planificador"]
    plan_horas = [int(x) for x in (re.split(r"\s+", xp.strip()) if isinstance(xp, str) else xp)]
    assert len(plan_horas) == len(horas) == 17, (len(plan_horas), len(horas))
    assert sum(hoy) == round(caso["salidas_hoy"]) and sum(plan_horas) == caso["salidas_plan"], (sum(hoy), caso["salidas_hoy"], sum(plan_horas), caso["salidas_plan"])
    salidas_hora = {
        "titulo": "CRA 54, día laboral típico: salidas por hora",
        "horas": horas, "hoy": hoy, "plan": plan_horas, "d5_original": d5_original,
        "total_hoy": sum(hoy), "total_plan": sum(plan_horas),
        "fuente_hoy": fuente("planificador_datos.js", "rutas['CRA 54'].tipos.Laboral.horas[].salidas_actuales (mediana de 2025 por hora de salida)",
                             "P1 (insumos de D5)", REV_D5),
        "fuente_plan": fuente("experimentos/P1_planificador/validacion_costos_fuente.json",
                              "casos[juego = 'hora', elasticidad = 0.5, ruta = 'CRA 54', tipo_dia = 'Laboral'].x_planificador",
                              "P1 (validacion_costos_fuente.py, 06-10-2026)", REV_P1),
    }

    # --- Piloto (P2): calendario -------------------------------------------------------------------------------------
    p2 = leer_json("experimentos/P2_piloto_beta/resultados.json")
    cal = p2["calendario"]
    inicio = dt.date.fromisoformat(cal["inicio"])
    piloto = {
        "inicio": cal["inicio"], "fin": cal["fin"], "semanas": cal["semanas"], "dias_laborales": cal["dias_laborales"],
        "festivos_dentro": cal["festivos_dentro"], "domingos": cal["domingos"],
        "cierres_bloques": [(inicio + dt.timedelta(days=14 * k - 1)).isoformat() for k in range(1, cal["semanas"] // 2 + 1)],
        "fuente": fuente("experimentos/P2_piloto_beta/resultados.json",
                         "calendario.{inicio, fin, semanas, dias_laborales, festivos_dentro, domingos}; cierres = inicio + 14 k − 1 días", "P2", REV_P2),
    }

    datos = {
        "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "generador": "app/generar_muestra_datos.py",
        "cifras": cifras, "wape_por_ruta": wape_por_ruta, "serie_diaria": serie_diaria, "salidas_hora": salidas_hora, "piloto": piloto,
    }
    SALIDA.write_text("// Generado por app/generar_muestra_datos.py a partir de los resultados de los experimentos. No editar a mano.\n"
                      "window.MUESTRA_DATOS = " + json.dumps(datos, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print("escrito", SALIDA.relative_to(RAIZ), f"({SALIDA.stat().st_size // 1024} KB)")
    for k, c in cifras.items():
        if "valor" in c:
            print(f"  {k:24s} {c['valor']:>12.3f} {c['unidad']}  revisor: {c['verificado']}")
    print("  backtest", {k: v for k, v in cifras["backtest"].items() if isinstance(v, (int, float))})
    print("  serie_diaria:", len(serie_diaria["dias"]), "días; salidas_hora:", salidas_hora["total_hoy"], "→", salidas_hora["total_plan"], "; piloto:", piloto["inicio"], "→", piloto["fin"])


if __name__ == "__main__":
    main()
