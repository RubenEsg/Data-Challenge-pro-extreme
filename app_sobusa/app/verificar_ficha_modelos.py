"""Contrasta la ficha de los dos modelos que lleva app/datos_app.js (pantallas.modelo.ficha) con sus fuentes
(resultados.json de E11 y E12, metadatos, modelos guardados, código). Lo llama app/verificar_datos_app.py.
Uso: PYTHONIOENCODING=utf-8 python app/verificar_ficha_modelos.py <carpeta del proyecto>
Sale con código 1 si alguna cifra difiere."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PROY = Path(sys.argv[1]).resolve()
AQUI = Path(__file__).resolve().parent
_JS = (AQUI / "datos_app.js").read_text(encoding="utf-8")
F = json.JSONDecoder().raw_decode(_JS[_JS.index("{", _JS.find("window.DATOS_APP")):])[0]["pantallas"]["modelo"]["ficha"]
E11 = json.loads((PROY / "experimentos/E11_modelo_mejorado/resultados.json").read_text(encoding="utf-8"))
E12 = json.loads((PROY / "experimentos/E12_comparacion_modelos/resultados.json").read_text(encoding="utf-8"))
SEL = json.loads((PROY / "experimentos/E11_modelo_mejorado/seleccion.json").read_text(encoding="utf-8"))
META11 = json.loads((PROY / "experimentos/E11_modelo_mejorado/modelos/metadatos.json").read_text(encoding="utf-8"))
META12 = json.loads((PROY / "experimentos/E12_comparacion_modelos/modelos_hibrido/metadatos_pronostico_2026_enero_hibrido.json").read_text(encoding="utf-8"))
EMU = json.loads((PROY / "experimentos/E12_comparacion_modelos/modelos_hibrido/emulacion_produccion_2025.json").read_text(encoding="utf-8"))
FUGA = json.loads((PROY / "experimentos/E12_comparacion_modelos/modelos_hibrido/verificacion_fuga.json").read_text(encoding="utf-8"))
BT_E12 = json.loads((PROY / "experimentos/E12_comparacion_modelos/modelos_hibrido/backtest_2025-03_H7_panel_e12.json").read_text(encoding="utf-8"))
BT_REC = json.loads((PROY / "experimentos/E12_comparacion_modelos/modelos_hibrido/backtest_2025-03_H7.json").read_text(encoding="utf-8"))
VAL24 = json.loads((PROY / "experimentos/E12_comparacion_modelos/modelos_fundacionales/validacion_2024_hibrido.json").read_text(encoding="utf-8"))
RES = PROY / "experimentos/E12_comparacion_modelos/resultados"


def res(nombre):
    return json.loads((RES / f"{nombre}.json").read_text(encoding="utf-8"))


HIB, V4J = res("hibrido_V4_chronos2cov"), res("V4_lightgbm")
fallos = []
n = 0


def ok(nombre, a, b, tol=0.0051):
    """a = ficha, b = fuente."""
    global n
    n += 1
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if abs(float(a) - float(b)) > tol:
            fallos.append(f"{nombre}: ficha {a} frente a fuente {b}")
    elif a != b:
        fallos.append(f"{nombre}: ficha {a!r} frente a fuente {b!r}")


def variante(clave):
    return next(v for v in E11["variantes"] if v["clave"] == clave)


M = F["modelos"]
A, B = M["E11_V4"], M["E12_hibrido"]
C = F["comun"]

# --- E11: global, B1, comparaciones ---
ok("V4 h7 WAPE", A["errores"]["global_h7"]["WAPE"]["valor"], variante("V4_h7")["metricas_global"]["WAPE"], 0.001)
ok("V4 h7 MAE", A["errores"]["global_h7"]["MAE"]["valor"], variante("V4_h7")["metricas_global"]["MAE"], 0.051)
ok("V4 h7 RMSE", A["errores"]["global_h7"]["RMSE"]["valor"], variante("V4_h7")["metricas_global"]["RMSE"], 0.051)
ok("V4 h7 sesgo", A["errores"]["global_h7"]["sesgo_pax_franja"]["valor"], variante("V4_h7")["metricas_global"]["sesgo"], 0.051)
ok("V4 h7 sesgo_pct", A["errores"]["global_h7"]["sesgo_pct"]["valor"], V4J["metricas_global"]["sesgo_pct"], 0.0051)
ok("V4 h7 total diario", A["errores"]["global_h7"]["total_diario_por_ruta_WAPE"]["valor"], V4J["total_diario_por_ruta"]["WAPE"], 0.0051)
ok("V4 h1 WAPE", A["errores"]["global_h1"]["WAPE"]["valor"], variante("V4_h1")["metricas_global"]["WAPE"], 0.001)
ok("B1 h7 WAPE", C["regla_manual_B1"]["wape_h7"]["valor"], E11["horizontes"]["B1_H7"]["global_"]["WAPE"], 0.001)
ok("B1 MAE", C["regla_manual_B1"]["mae_h7"]["valor"], E11["horizontes"]["B1_H7"]["global_"]["MAE"], 0.051)
ok("B1 total diario", C["regla_manual_B1"]["total_diario_por_ruta"]["valor"], variante("B1_h7")["total_diario_por_ruta"]["WAPE"], 0.0051)
cv = E11["comparacion_vs_V0"]["V4_h7"]
ok("V4 vs V0 dif", A["errores"]["frente_a_V0_h7"]["dif_pp"]["valor"], cv["dif_pp"])
ok("V4 vs V0 ic", A["errores"]["frente_a_V0_h7"]["dif_pp"]["ic"][0], cv["ic_inf"], 0.001)
ok("V4 vs V0 ic sup", A["errores"]["frente_a_V0_h7"]["dif_pp"]["ic"][1], cv["ic_sup"], 0.001)
ok("V4 vs V0 sin agosto", A["errores"]["frente_a_V0_h7"]["sin_agosto"]["valor"], cv["dif_pp_sin_mes_mayor_ganancia"])
ok("V4 vs V0 meses", 10, cv["meses_mejor"])
ok("V4 vs V0 p t", 0.10, cv["p_t_pareada"], 0.0051)
ok("V4 vs V0 p wilcoxon", 0.003, cv["p_wilcoxon"], 0.0006)
# por ruta / tipo / franja / mes / antelación / subconjunto / sesgo mensual
for r, v in A["errores"]["por_ruta_h7"]["V4"].items():
    ok(f"V4 ruta {r}", v, E11["horizontes"]["SEL_H7"]["por_ruta"][r]["WAPE"], 0.0051)
for r, v in A["errores"]["por_ruta_h7"]["B1"].items():
    ok(f"B1 ruta {r}", v, E11["horizontes"]["B1_H7"]["por_ruta"][r]["WAPE"], 0.0051)
for r, v in A["errores"]["por_ruta_h7"]["V0"].items():
    ok(f"V0 ruta {r}", v, E11["horizontes"]["V0_H7"]["por_ruta"][r]["WAPE"], 0.0051)
for k, v in A["errores"]["por_tipo_dia_h7"]["V4"].items():
    ok(f"V4 tipo {k}", v, V4J["por_tipo_dia"][k]["WAPE"], 0.0051)
for k, v in A["errores"]["por_franja_h7"]["V4"].items():
    ok(f"V4 franja {k}", v, V4J["por_franja"][k]["WAPE"], 0.0051)
for k, v in A["errores"]["por_mes_h7"]["V4"].items():
    ok(f"V4 mes {k}", v, V4J["por_mes"][k]["WAPE"], 0.0051)
for k, v in A["errores"]["por_mes_h7"]["V0"].items():
    ok(f"V0 mes {k}", v, variante("V0_h7")["metricas_por_mes"][k]["WAPE"] if isinstance(variante("V0_h7")["metricas_por_mes"][k], dict) else variante("V0_h7")["metricas_por_mes"][k], 0.0051)
for k, v in A["errores"]["por_mes_h7"]["B1"].items():
    ok(f"B1 mes {k}", v, variante("B1_h7")["metricas_por_mes"][k]["WAPE"] if isinstance(variante("B1_h7")["metricas_por_mes"][k], dict) else variante("B1_h7")["metricas_por_mes"][k], 0.0051)
for H, v in A["errores"]["por_antelacion"]["V4"].items():
    ok(f"V4 {H}", v, E11["horizontes"][f"SEL_{H}"]["global_"]["WAPE"], 0.0051)
for H, v in A["errores"]["por_antelacion"]["V0"].items():
    ok(f"V0 {H}", v, E11["horizontes"][f"V0_{H}"]["global_"]["WAPE"], 0.0051)
for H, v in A["errores"]["por_antelacion"]["B1"].items():
    ok(f"B1 {H}", v, E11["horizontes"][f"B1_{H}"]["global_"]["WAPE"], 0.0051)
for r, v in A["errores"]["por_antelacion"]["V4_H28_por_ruta"].items():
    ok(f"V4 H28 ruta {r}", v, E11["horizontes"]["SEL_H28"]["por_ruta"][r]["WAPE"], 0.0051)
sub_map = {"vacaciones escolares (85 días)": "vacaciones escolares", "clases escolares (280)": "clases escolares",
           "vacaciones universitarias (134)": "vacaciones universitarias",
           "transición de periodo (159)": "transición de periodo (ventana de rezagos con otro régimen)",
           "días lluviosos ≥ 5 mm (82)": "días lluviosos (>= 5 mm)", "días secos < 1 mm (173)": "días secos (< 1 mm)",
           "días atípicos no predecibles de E10 (4)": "días atípicos no predecibles (E10)",
           "franjas con ≥ 25 % sin registro (475)": "franjas con >= 25 % de viajes sin registro",
           "días normales (362)": "días normales (sin atípicos ni fallas)"}
for k, v in A["errores"]["por_subconjunto_h7"]["V4"].items():
    ok(f"V4 subconjunto {k}", v, V4J["por_subconjunto"][sub_map[k]]["WAPE"], 0.0051)
for k, v in A["errores"]["sesgo"]["por_mes_pct"].items():
    ok(f"V4 sesgo mes {k}", v, E11["sesgo_pct_por_mes_h7"]["V4"][k], 0.0051)
ok("V4 2024 WAPE", A["errores"]["en_2024"]["WAPE"]["valor"], E12["validacion_2024"]["V4"]["WAPE"], 0.001)
# panel, hiperparámetros, importancia, enero 2026
p = E11["panel"]
ok("panel filas", A["datos_entrenamiento"]["filas"]["panel"]["valor"], p["filas"])
ok("panel prueba", A["datos_entrenamiento"]["filas"]["prueba_2025"]["valor"], p["filas_prueba_2025"])
ok("dias atipicos", A["datos_entrenamiento"]["cifras"]["dias_atipicos"]["valor"], p["dias_atipicos_no_predecibles"])
ok("filas peso 0,25", A["datos_entrenamiento"]["cifras"]["filas_peso_0_25"]["valor"], p["filas_con_peso_atipico"])
ok("franjas peso 0,1", A["datos_entrenamiento"]["cifras"]["franjas_peso_0_1"]["valor"], p["franjas_con_fallas_25pct"])
ok("pct franjas fallas", A["datos_entrenamiento"]["cifras"]["pct_franjas_con_fallas"]["valor"], p["pct_franjas_con_fallas_25pct"], 0.001)
for k, v in A["hiperparametros"]["valores"].items():
    if k != "objective":
        ok(f"hiperparámetro {k}", v, SEL["params"][k], 1e-9)
ok("hiperparámetros híbrido = V4", B["hiperparametros"]["valores"], A["hiperparametros"]["valores"])
for k, v in B["hiperparametros"]["valores"].items():
    if k != "objective":
        ok(f"hiperparámetro híbrido {k}", v, META12["params"][k], 1e-9)
ok("ajuste anidado dif", 0.07, E11["ajuste_anidado"]["comparacion_vs_elegida_sin_ajuste"]["dif_pp"], 0.0051)
ok("n variables V4 metadatos", A["variables"]["total"]["valor"], META11["modelos"]["H7"]["n_variables"])
for k, v in A["variables"]["importancia_modelo_final_H7"]["top"].items():
    ok(f"importancia V4 {k}", v, META11["modelos"]["H7"]["importancia_top20"][k], 0.0051)
for r, v in A["produccion"]["pronostico_enero_2026"]["por_ruta"].items():
    ok(f"enero 2026 E11 {r}", v, META11["total_por_ruta"][r], 0.5)
ok("enero 2026 E11 total", A["produccion"]["pronostico_enero_2026"]["total"]["valor"], sum(META11["total_por_ruta"].values()), 0.5)
sem11 = {}
for f in META11["resumen_semanal"]:
    sem11[f["semana"]] = sem11.get(f["semana"], 0) + f["pronostico"]
for k, v in A["produccion"]["pronostico_enero_2026"]["por_semana"].items():
    ok(f"enero 2026 E11 semana {k[0]}", v, sem11[int(k[0])], 1.0)
ok("tiempo corrida completa E11", 1524, E11["tiempo_s_corrida_completa"])
ok("regla E11", E11["mejor_variante"], "V4")

# --- 77 variables desde el código ---
sys.path.insert(0, str(PROY / "experimentos/E11_modelo_mejorado"))
import comun_e11 as C11  # noqa: E402
codigo = C11.variables_variante(C11.VARIANTES["V4"], 7)
ficha_vars = []
for g in A["variables"]["grupos"]:
    ficha_vars += g["variables"]
    ok(f"n grupo {g['nombre']}", g["n"], len(g["variables"]))
ok("77 variables (lista completa, en orden)", ficha_vars, codigo)
ok("variables E1 h7", 67, len(C11.variables_e1(7)))
ok("categóricas", A["variables"]["categoricas"], C11.CATEGORICAS)
ok("H7 real = README − 102", 55436, A["datos_entrenamiento"]["filas"]["produccion_por_H_segun_readme"]["H7"] - 102)
for H in ("H7", "H14", "H21", "H28"):
    ok(f"filas híbrido {H}", B["datos_entrenamiento"]["filas"]["produccion_por_H"][H], META12["modelos"][H]["filas"])
    ok(f"desde híbrido {H}", B["datos_entrenamiento"]["filas"]["desde_por_H"][H], META12["modelos"][H]["desde"])
    ok(f"ganancia chronos {H}", B["variables"]["importancia_modelo_final_H7"]["ganancia_chronos_por_H"][H], META12["modelos"][H]["ganancia_chronos_pct"], 0.051)
    ok(f"filas con chronos {H}", B["datos_entrenamiento"]["filas"]["filas_con_variables_chronos_por_H"][H], sum(META12["modelos"][H]["fuente_chronos_entrenamiento"].values()))
    ok(f"README E11 − 102 = híbrido {H}", A["datos_entrenamiento"]["filas"]["produccion_por_H_segun_readme"][H] - 102, META12["modelos"][H]["filas"])

# --- E12 híbrido ---
g = HIB["metricas_global"]
ok("hib WAPE", B["errores"]["global_2025"]["WAPE"]["valor"], g["WAPE"], 0.001)
ok("hib MAE", B["errores"]["global_2025"]["MAE"]["valor"], g["MAE"], 0.051)
ok("hib RMSE", B["errores"]["global_2025"]["RMSE"]["valor"], g["RMSE"], 0.051)
ok("hib sesgo_pct", B["errores"]["global_2025"]["sesgo_pct"]["valor"], g["sesgo_pct"], 0.0051)
ok("hib total diario", B["errores"]["global_2025"]["total_diario_por_ruta_WAPE"]["valor"], HIB["total_diario_por_ruta"]["WAPE"], 0.0051)
vs = HIB["vs_V4"]
ok("hib dif", B["errores"]["frente_a_V4_2025"]["dif_pp"]["valor"], vs["dif_pp"])
ok("hib ic inf", B["errores"]["frente_a_V4_2025"]["dif_pp"]["ic"][0], vs["ic_inf"], 0.001)
ok("hib ic sup", B["errores"]["frente_a_V4_2025"]["dif_pp"]["ic"][1], vs["ic_sup"], 0.001)
ok("hib meses", 11, vs["meses_mejor"])
ok("hib sin mes mayor", B["errores"]["frente_a_V4_2025"]["sin_mes_de_mayor_ganancia"]["valor"], vs["dif_pp_sin_mes_mayor_ganancia"])
ok("hib p t", 0.0003, vs["p_t_pareada"], 0.00005)
ok("hib p wilcoxon", 0.0015, vs["p_wilcoxon"], 0.0001)
rob = E12["robustez"]["por_modelo"]["hibrido_V4_chronos2cov"]
for r, v in B["errores"]["por_ruta_2025"]["hibrido"].items():
    ok(f"hib ruta {r}", v, rob["por_ruta"][r]["WAPE"])
    ok(f"V4 ruta E12 {r}", B["errores"]["por_ruta_2025"]["V4"][r], rob["por_ruta"][r]["WAPE_V4"])
for r, v in B["errores"]["por_tipo_dia_2025"]["hibrido"].items():
    ok(f"hib tipo {r}", v, rob["por_tipo_dia"][r]["WAPE"])
    ok(f"V4 tipo E12 {r}", B["errores"]["por_tipo_dia_2025"]["V4"][r], rob["por_tipo_dia"][r]["WAPE_V4"])
for r, v in B["errores"]["por_franja_2025"]["hibrido"].items():
    ok(f"hib franja {r}", v, rob["por_franja"][r]["WAPE"])
    ok(f"V4 franja E12 {r}", B["errores"]["por_franja_2025"]["V4"][r], rob["por_franja"][r]["WAPE_V4"])
ok("hib frente a V4 beta", -0.34, rob["frente_a_V4_beta"]["dif_pp"])
for k, v in B["errores"]["por_mes_2025"]["hibrido"].items():
    ok(f"hib mes {k}", v, HIB["por_mes"][k]["WAPE"])
for k, v in B["errores"]["por_mes_2025"]["dif_vs_V4"].items():
    ok(f"hib dif mes {k}", v, vs["dif_por_mes_pp"][k])
for k, v in B["errores"]["sesgo"]["por_mes_pct_2025"].items():
    ok(f"hib sesgo mes {k}", v, HIB["por_mes"][k]["sesgo_pct"])
sub_map2 = {"vacaciones escolares": "vacaciones escolares", "clases escolares": "clases escolares",
            "vacaciones universitarias": "vacaciones universitarias",
            "transición de periodo": "transición de periodo (ventana de rezagos con otro régimen)",
            "días lluviosos ≥ 5 mm": "días lluviosos (>= 5 mm)", "días secos < 1 mm": "días secos (< 1 mm)",
            "días atípicos no predecibles (E10)": "días atípicos no predecibles (E10)",
            "franjas con ≥ 25 % sin registro": "franjas con >= 25 % de viajes sin registro",
            "días normales": "días normales (sin atípicos ni fallas)"}
for k, v in B["errores"]["por_subconjunto_2025"]["hibrido"].items():
    ok(f"hib subconjunto {k}", v, HIB["por_subconjunto"][sub_map2[k]]["WAPE"])
    ok(f"V4 subconjunto E12 {k}", B["errores"]["por_subconjunto_2025"]["V4"][k], V4J["por_subconjunto"][sub_map2[k]]["WAPE"])
ok("chronos2_cov sesgo", 4.1, res("chronos2_cov")["metricas_global"]["sesgo_pct"], 0.051)
# 2024
v24 = E12["validacion_2024"]["candidatos"]["hibrido_V4_chronos2cov"]
ok("hib 2024 WAPE", B["errores"]["en_2024"]["WAPE"]["valor"], v24["WAPE"], 0.001)
ok("hib 2024 WAPE = json fundacionales", VAL24["hibrido"]["WAPE"], v24["WAPE"], 1e-9)
ok("hib 2024 dif", B["errores"]["en_2024"]["dif_pp"]["valor"], v24["dif_pp"])
ok("hib 2024 ic inf", B["errores"]["en_2024"]["dif_pp"]["ic"][0], v24["ic_inf"], 0.001)
ok("hib 2024 ic sup", B["errores"]["en_2024"]["dif_pp"]["ic"][1], v24["ic_sup"], 0.001)
ok("hib 2024 meses", 10, v24["meses_mejor"])
ok("hib 2024 sesgo", B["errores"]["en_2024"]["sesgo_pct"]["valor"], v24["sesgo_pct"])
ok("hib 2024 sin enero", -0.26, v24["sin_enero"]["dif_pp"])
for k, v in B["errores"]["en_2024"]["dif_por_mes"].items():
    ok(f"hib 2024 mes {k}", v, v24["dif_por_mes_pp"][k])
ok("hib 2024 cumple", B["errores"]["en_2024"]["cumple_regla_2024"], v24["cumple_regla_2024"])
# emulación
em = B["errores"]["por_antelacion_modo_produccion_2025"]
for H in ("H7", "H14", "H21", "H28"):
    ok(f"emu hib {H}", em["hibrido"][H], EMU["global"][H]["WAPE_hibrido"])
    ok(f"emu V4 {H}", em["V4"][H], EMU["global"][H]["WAPE_V4"])
    ok(f"emu chronos {H}", em["chronos2_solo"][H], EMU["global"][H]["WAPE_chronos2"])
ok("emu hib total", em["hibrido"]["total"], EMU["global"]["todas"]["WAPE_hibrido"])
ok("emu V4 total", em["V4"]["total"], EMU["global"]["todas"]["WAPE_V4"])
ok("emu chronos total", em["chronos2_solo"]["total"], EMU["global"]["todas"]["WAPE_chronos2"])
ok("emu dif", em["dif_total"]["valor"], EMU["global"]["vs_V4_bootstrap_dias"]["dif_pp"])
ok("emu ic inf", em["dif_total"]["ic"][0], EMU["global"]["vs_V4_bootstrap_dias"]["ic_inf"], 0.001)
ok("emu ic sup", em["dif_total"]["ic"][1], EMU["global"]["vs_V4_bootstrap_dias"]["ic_sup"], 0.001)
ok("emu semanas", 32, EMU["global"]["todas"]["semanas_mejor"])
ok("emu orígenes", 9, EMU["global"]["vs_V4_bootstrap_dias"]["origenes_mejor"])
# producción: tiempos, enero 2026, comprobaciones
cpu = E12["produccion"]["chronos2_cpu"]
ok("chronos cpu s", 228.3, cpu["inferencia_s"], 0.051)
ok("chronos cpu dif media", 0.16, cpu["dif_media_pax"], 0.0051)
ok("chronos cpu dif max", 38.0, cpu["dif_max_pax"], 0.051)
ok("corrida completa 107 s", B["produccion"]["computo"]["tiempos_cpu_2_hilos"]["corrida_completa_4_semanas_s"]["valor"], META12["tiempos_s"]["total"], 0.51)
for r, v in B["produccion"]["pronostico_enero_2026"]["por_ruta"].items():
    ok(f"enero 2026 hib {r}", v, META12["total_por_ruta"]["pasajeros_pred"][r], 0.5)
ok("enero 2026 hib total", B["produccion"]["pronostico_enero_2026"]["total"]["valor"], sum(META12["total_por_ruta"]["pasajeros_pred"].values()), 0.5)
ok("enero 2026 V4 sombra", B["produccion"]["pronostico_enero_2026"]["V4_en_sombra"]["valor"], sum(META12["total_por_ruta"]["pasajeros_pred_V4"].values()), 0.5)
sem12 = {}
for f in META12["resumen_semanal"]:
    sem12[f["semana"]] = sem12.get(f["semana"], 0) + f["pronostico"]
for k, v in B["produccion"]["pronostico_enero_2026"]["por_semana"].items():
    ok(f"enero 2026 hib semana {k[0]}", v, sem12[int(k[0])], 1.0)
tot_e11 = sum(f["pronostico_E11"] for f in META12["resumen_semanal"])
ok("hib frente a E11 %", B["produccion"]["pronostico_enero_2026"]["frente_a_E11"]["valor"], (sum(META12["total_por_ruta"]["pasajeros_pred"].values()) / tot_e11 - 1) * 100, 0.051)
tot_25 = sum(f["real_2025_alineado"] for f in META12["resumen_semanal"])
ok("hib frente a 2025 %", B["produccion"]["pronostico_enero_2026"]["frente_a_2025_alineado"]["valor"], (sum(META12["total_por_ruta"]["pasajeros_pred"].values()) / tot_25 - 1) * 100, 0.051)
ok("E11 frente a 2025 %", A["produccion"]["pronostico_enero_2026"]["frente_a_2025_alineado"]["valor"], (sum(META11["total_por_ruta"].values()) / tot_25 - 1) * 100, 0.051)
tot_e8 = sum(f["E8_ensamble_diario"] for f in META12["resumen_semanal"])
ok("hib frente a E8 %", B["produccion"]["pronostico_enero_2026"]["frente_a_E8"]["valor"], (sum(META12["total_por_ruta"]["pasajeros_pred"].values()) / tot_e8 - 1) * 100, 0.051)
ok("E11 frente a E8 %", A["produccion"]["pronostico_enero_2026"]["frente_a_E8"]["valor"], (sum(META11["total_por_ruta"].values()) / tot_e8 - 1) * 100, 0.051)
ok("backtest panel e12 dif", 0.0, BT_E12["dif_max_pax"], 1e-9)
ok("backtest reconstruido dif media", 1.7, BT_REC["dif_media_pax"], 0.051)
ok("backtest reconstruido dif max", 16.5, BT_REC["dif_max_pax"], 0.051)
ok("backtest WAPE guardado", 14.403, BT_E12["WAPE_hibrido_guardado_E12"], 0.001)
for H in ("H7", "H14", "H21", "H28"):
    ok(f"fuga variables {H}", 0.0, FUGA["variables_V4"][H]["dif_max"], 1e-12)
ok("fuga control lag1", 1377, FUGA["control_lag1_franjas_distintas"])
ok("fuga chronos truncado", 0.0, FUGA["chronos2_truncado_vs_completo_dif_max"], 1e-12)
# ranking y familias
rk = E12["ranking"]
ok("n candidatos", F["comparacion_E12"]["candidatos"]["valor"], rk["n_candidatos"])
ok("n cumplen", 12, rk["n_cumplen"])
ok("n elegibles cumplen", 9, rk["n_elegibles_cumplen"])
ok("sobreviven holm", 11, len(rk["correccion"]["sobreviven_holm"]))
ok("ganador", "ens_conj_c_nnls_todos", rk["ganador"])
ok("recomendación", "hibrido_V4_chronos2cov", E12["produccion"]["recomendacion"])
top = {t["modelo"]: t for t in rk["top"]}
ok("hib posicion", 5, top["hibrido_V4_chronos2cov"]["posicion"])
ok("hib p holm", 0.002, top["hibrido_V4_chronos2cov"]["p_holm"], 0.0001)
ok("hib bonf inf", -0.51, top["hibrido_V4_chronos2cov"]["ic_bonf_inf"])
ok("hib bonf sup", -0.14, top["hibrido_V4_chronos2cov"]["ic_bonf_sup"])
for fam in F["comparacion_E12"]["familias"]:
    for m in fam["mejores"]:
        nombre = m["modelo"].split(" ")[0]
        if isinstance(m["WAPE"], (int, float)) and (RES / f"{nombre}.json").exists():
            ok(f"familia {nombre} WAPE", m["WAPE"], res(nombre)["metricas_global"]["WAPE"], 0.0051)
            d = res(nombre)["vs_V4"]
            txt = m["dif"].replace("−", "-").replace(",", ".").split(" ")[0]
            ok(f"familia {nombre} dif", float(txt), d["dif_pp"], 0.0051)
v24c = E12["validacion_2024"]["candidatos"]
for nombre, esperado in [("lgbm_tweedie", -0.0038), ("catboost_poisson", 0.82), ("autoets_cal", 0.17), ("prophet_semanal", 0.74),
                         ("tft_global", 1.74), ("chronos2_cov", 0.55), ("timesfm25_xreg", 0.72), ("ens_conj_c_nnls_diverso", -0.23),
                         ("ens_conj_a_media_V4_mejor_familia", -0.49), ("ens_adhoc_V4_tft_nnls", -0.10), ("ens_V4_chronos2_cov_nnls", -0.20)]:
    ok(f"2024 {nombre}", esperado, v24c[nombre]["dif_pp"], 0.0051)
corr = E12["robustez"]["correlacion_errores"]["pred_V4"]
ok("correlación híbrido-V4", 0.946, corr["hibrido_V4_chronos2cov"], 0.0005)

# --- importancia del híbrido desde el modelo guardado ---
try:
    import lightgbm as lgb
    import pandas as pd
    for ruta, ficha_imp, n_esp in [(PROY / "experimentos/E12_comparacion_modelos/modelos_hibrido/modelo_hibrido_H7.txt", B["variables"]["importancia_modelo_final_H7"]["top"], 81),
                                   (PROY / "experimentos/E11_modelo_mejorado/modelos/modelo_V4_H7.txt", A["variables"]["importancia_modelo_final_H7"]["top"], 77)]:
        bst = lgb.Booster(model_file=str(ruta))
        imp = pd.Series(bst.feature_importance("gain"), index=bst.feature_name())
        imp = imp / imp.sum() * 100
        ok(f"n variables {ruta.name}", n_esp, len(imp))
        for k, v in ficha_imp.items():
            ok(f"importancia {ruta.name} {k}", v, float(imp[k]), 0.0051)
    bst = lgb.Booster(model_file=str(PROY / "experimentos/E12_comparacion_modelos/modelos_hibrido/modelo_hibrido_H7.txt"))
    imp = pd.Series(bst.feature_importance("gain"), index=bst.feature_name())
    imp = imp / imp.sum() * 100
    ok("suma chronos híbrido", B["variables"]["importancia_modelo_final_H7"]["por_grupo"]["chronos2"], float(imp[["fm_c2", "fm_c2_q10", "fm_c2_q90", "fm_c2_ratio"]].sum()), 0.0051)
    ok("variables híbrido = 77 de V4 + 4", list(bst.feature_name()), codigo + ["fm_c2", "fm_c2_q10", "fm_c2_q90", "fm_c2_ratio"])
except ImportError:
    print("lightgbm no disponible: no se verificó la importancia desde los modelos guardados")

print(f"comprobaciones: {n}; fallos: {len(fallos)}")
for f in fallos:
    print("  FALLO", f)
sys.exit(1 if fallos else 0)
