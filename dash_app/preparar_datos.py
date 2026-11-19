"""Copia a dash_app/datos/ los archivos pequeños que necesita el laboratorio, para que la carpeta funcione sola.

Uso (desde la carpeta dash_app, con el proyecto completo al lado):
    python preparar_datos.py                       # el proyecto está dos carpetas arriba (EntregaFinal/..)
    python preparar_datos.py --proyecto "D:/ruta/al/proyecto"

No consulta la base de datos: solo lee resultados ya guardados en el proyecto. No copia datos personales (todo son
agregados por ruta, día y hora). Deja además datos/origen.json con el archivo de origen, las filas y el tamaño de cada uno.
También escribe los íconos de assets/iconos/ a partir de app/iconos.js (la misma familia de la app HTML).

Archivos que produce:
- pronosticos_2025.parquet: pasajeros reales y pronósticos fuera de muestra (h = 7 días) por ruta x día x hora de 2025 de la
  regla manual (B1), E1, el modelo final (E11, LightGBM V4) y el híbrido (E12, LightGBM V4 + Chronos-2).
  Fuentes: experimentos/E11_modelo_mejorado/predicciones_2025.parquet (real, prediccion = V4, pred_B1_manual; horizonte 7),
  experimentos/E1_lgbm_salida/predicciones_2025.parquet (prediccion, horizonte 7) y
  experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet (horizonte 7; el mismo que usa
  app/generar_datos_app.py).
- insumos_d5_2025.parquet: insumos del MILP de D5 por ruta x día x hora, con las mismas uniones que
  sistema_tiempo_real/plan_base.py (_decisiones): decisiones_2025.parquet de D5 + pred_viajes_validos de E1 (h = 7) como k0_plan
  + capacidad y dist de D1 (parametros_operativos.parquet) + x_corrida_1 de costos/resultados/d5_reoptimizado_decisiones.parquet.
- costos_fuente.json: costos unitarios con fuente (precios 2026) de costos/resultados/costos_unitarios.json y su rango de
  costos/resultados/costos_para_planificador.json.
- cifras_app.json: el objeto window.DATOS_APP de app/datos_app.js (cada cifra con su archivo y clave de origen).
- ficha_modelos.json: copia de app/ficha_modelos.json.
- corto_plazo.json: las cifras de la prueba reservada del pronóstico de corto plazo (30, 60 y 120 minutos por ruta,
  sentido y segmento; experimento E14, el modelo que sirve la API en /api/v1/predictions/corto-plazo), de
  EntregaFinal/pronostico_corto_plazo/resultados/prueba.json, desglose_domingos_festivos.json y figuras.json.
- sensibilidad_beta.csv y beta_equilibrio.csv: copias de simulacion_ahorro/resultados/ y costos/resultados/.
- ahorro_anual.json: salidas, horas de bus, km, costo de km y conductor, ahorro en operación y pasajes en juego al año de
  hoy, del plan que reasigna (el recomendado) y del que recorta; por ruta, por hora y tipo de día (con las salidas que se
  quitan y se ponen en cada hora), contexto y tres palancas que se muestran aparte. Cada cifra lleva
  su archivo y su clave en «origen». Fuentes: costos/resultados/d5_reoptimizado.csv y d5_reoptimizado_decisiones.parquet,
  experimentos/D5_optimizacion_milp/escenarios.csv, decisiones_2025.parquet y resultados.json, costos/resultados/
  costos_para_planificador.json, costos_unitarios.json, ahorros_por_escenario.csv, beta_equilibrio.csv y linea_base_2025.csv,
  simulacion_ahorro/resultados/simulacion_por_fecha.csv y sensibilidad_beta.csv, y experimentos/D6_simulador/
  resultados_escenarios.json.
  Lo comprueba verificar_ahorro.py.
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
DESTINO = AQUI / "datos"
ICONOS = AQUI / "assets" / "iconos"
CLAVE = ["ruta", "tipo_dia", "hora"]


def leer_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", default=str(AQUI.parent.parent), help="carpeta raíz del proyecto (por defecto, dos arriba)")
    ap.add_argument("--solo-despacho", action="store_true",
                    help="solo los días de ejemplo de la pantalla Despacho (datos/despacho/) y su entrada en origen.json")
    ap.add_argument("--solo-producto", action="store_true",
                    help="solo datos/modelo_producto.json (el modelo activo de la API) y su entrada en origen.json")
    ap.add_argument("--solo-ahorro", action="store_true",
                    help="solo datos/ahorro_anual.json (las cifras de «¿Qué gana Sobusa?») y su entrada en origen.json")
    ap.add_argument("--solo-corto-plazo", action="store_true",
                    help="solo datos/corto_plazo.json (la prueba reservada del pronóstico a 30, 60 y 120 minutos)")
    return ap.parse_args()


# --- Pantalla Despacho: los 6 días de ejemplo de la consola (sistema_tiempo_real/replay/dias) ---------------------------
F_REPLAY = "sistema_tiempo_real/replay/dias"


def despacho(R):
    """Copia a datos/despacho/ los días de ejemplo del índice de la consola (ejemplo = true) como <fecha>.json.gz (el mismo
    gzip que traen los archivos por día, sin la envoltura base64 de JS) y un indice.json con meta, mapa y la lista de esos
    días. Así la pantalla Despacho funciona sin el proyecto al lado (el ZIP liviano). Devuelve [(nombre, fuentes)]."""
    import base64
    import gzip
    carpeta = R / F_REPLAY
    texto = (carpeta / "indice.js").read_text(encoding="utf-8")
    ind = json.loads(texto[texto.index("{"):texto.rstrip().rstrip(";").rindex("}") + 1])
    ejemplos = [d for d in ind["dias"] if d.get("ejemplo")]
    destino = DESTINO / "despacho"
    destino.mkdir(parents=True, exist_ok=True)
    hechos = []
    for d in ejemplos:
        s = (carpeta / f"{d['fecha']}.js").read_text(encoding="utf-8")
        crudo = base64.b64decode(re.findall(r'"([A-Za-z0-9+/=]{100,})"', s)[-1])
        dia = json.loads(gzip.decompress(crudo))
        if dia.get("fecha") != d["fecha"] or len(dia.get("snapshots", [])) < 2:
            sys.exit(f"El día {d['fecha']} de {F_REPLAY} no se pudo leer bien.")
        (destino / f"{d['fecha']}.json.gz").write_bytes(crudo)
        hechos.append((f"despacho/{d['fecha']}.json.gz", [f"{F_REPLAY}/{d['fecha']}.js"]))
        # los buses por las calles de ese día (calles/AAAA-MM-DD.js, el mismo gzip sin la envoltura de JS)
        fc = carpeta / "calles" / f"{d['fecha']}.js"
        if fc.is_file():
            (destino / "calles").mkdir(parents=True, exist_ok=True)
            sc = fc.read_text(encoding="utf-8")
            (destino / "calles" / f"{d['fecha']}.json.gz").write_bytes(
                base64.b64decode(re.findall(r'"([A-Za-z0-9+/=]{100,})"', sc)[-1]))
            hechos.append((f"despacho/calles/{d['fecha']}.json.gz", [f"{F_REPLAY}/calles/{d['fecha']}.js"]))
    fr = carpeta / "calles" / "rutas.js"
    if fr.is_file():
        (destino / "calles").mkdir(parents=True, exist_ok=True)
        tr = fr.read_text(encoding="utf-8")
        (destino / "calles" / "rutas.json").write_text(tr[tr.index("{"):tr.rstrip().rstrip(";").rindex("}") + 1], encoding="utf-8")
        hechos.append(("despacho/calles/rutas.json", [f"{F_REPLAY}/calles/rutas.js"]))
    meta = {k: v for k, v in ind["meta"].items() if k != "por_dia"}
    (destino / "indice.json").write_text(json.dumps({"meta": meta, "mapa": ind["mapa"], "dias": ejemplos}, ensure_ascii=False),
                                         encoding="utf-8")
    hechos.insert(0, ("despacho/indice.json", [f"{F_REPLAY}/indice.js (meta, mapa y los días con ejemplo = true)"]))
    return hechos


def solo_despacho(R):
    """Escribe solo datos/despacho/ y actualiza sus entradas en datos/origen.json (sin tocar las demás)."""
    p = DESTINO / "origen.json"
    org = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"generador": "dash_app/preparar_datos.py", "archivos": {}}
    org["archivos"] = {k: v for k, v in org.get("archivos", {}).items() if not k.startswith("despacho/")}
    for nombre, fuentes in despacho(R):
        tam = (DESTINO / nombre).stat().st_size
        org["archivos"][nombre] = {"fuentes": fuentes, "filas": None, "bytes": tam}
        print(f"  {nombre:28s} {tam / 1024:8.1f} KB")
    org["generado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    org["total_bytes"] = sum(v["bytes"] for v in org["archivos"].values())
    p.write_text(json.dumps(org, ensure_ascii=False, indent=1), encoding="utf-8")


# --- El modelo del producto (el que ejecuta la API) ----------------------------------------------------------------------
F_EVAL = "EntregaFinal/api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.json"
F_CAL = "EntregaFinal/api_frecuencias/docs/evidencias/modelo/calibracion_condicional.json"
F_REG = "EntregaFinal/api_frecuencias/datos/modelos/registro.json"
# el candidato registrado sin activar (fv3), evaluado con el mismo protocolo frente al activo
F_CAND = "EntregaFinal/api_frecuencias/docs/evidencias/modelo/candidato_fv3/evaluacion_modelo.json"


def modelo_producto(R):
    """datos/modelo_producto.json: el modelo activo de la API (registro.json), su error en la prueba de nov–dic 2025 frente
    a la regla manual con el intervalo bootstrap (evaluacion_modelo.json) y la cobertura de la banda P10–P90 con la
    calibración v2 y la v1 (calibracion_condicional.json). Cada cifra lleva su archivo y su clave en «origen»."""
    ev = json.loads((R / F_EVAL).read_text(encoding="utf-8"))
    cal = json.loads((R / F_CAL).read_text(encoding="utf-8"))
    reg = json.loads((R / F_REG).read_text(encoding="utf-8"))
    pr = ev["prueba_reservada"]
    activo = pr["modelos"]["activo"]
    if reg.get("activo") != activo or cal.get("model_id") != activo:
        sys.exit(f"El modelo activo de {F_REG} ({reg.get('activo')}) no es el evaluado en {F_EVAL} ({activo}) "
                 f"ni el calibrado en {F_CAL} ({cal.get('model_id')}).")
    res = cal["resultados"]["prueba"]
    v2, v1 = res["v2"]["global"], res["v1"]["global"]
    out = {
        "model_id": activo,
        "modelo_anterior": pr["modelos"].get("anterior"),
        "prueba": {"desde": pr["modelos"]["desde"], "hasta": pr["modelos"]["hasta"], "franjas": pr["global"]["cand"]["n"],
                   "dias": pr["bootstrap"]["dias"]},
        "wape_modelo": pr["global"]["cand"]["wape"], "wape_regla_manual": pr["global"]["b1"]["wape"],
        "wape_modelo_anterior": pr["global"]["anterior"]["wape"],
        "ic95_modelo": pr["bootstrap"]["cand"]["ic95"], "ic95_diferencia": pr["bootstrap"]["cand_menos_b1"]["ic95"],
        "sesgo_pct": pr["global"]["cand"]["sesgo_pct"], "mae": pr["global"]["cand"]["mae"],
        "cobertura_v2": v2["cobertura_pct"], "cobertura_v1": v1["cobertura_pct"],
        "cobertura_objetivo": cal["objetivo_cobertura_pct"], "ancho_v2": v2["ancho_medio"], "ancho_v1": v1["ancho_medio"],
        "bootstrap": {"B": pr["bootstrap"]["B"], "bloque_dias": pr["bootstrap"]["bloque_dias"]},
        "generado_evaluacion": ev.get("generado_en"), "generado_calibracion": cal.get("generado"),
    }
    out["origen"] = {
        "model_id": {"archivo": F_REG, "clave": "activo"},
        "wape_modelo": {"archivo": F_EVAL, "clave": "prueba_reservada.global.cand.wape"},
        "wape_regla_manual": {"archivo": F_EVAL, "clave": "prueba_reservada.global.b1.wape"},
        "wape_modelo_anterior": {"archivo": F_EVAL, "clave": "prueba_reservada.global.anterior.wape"},
        "ic95_modelo": {"archivo": F_EVAL, "clave": "prueba_reservada.bootstrap.cand.ic95"},
        "ic95_diferencia": {"archivo": F_EVAL, "clave": "prueba_reservada.bootstrap.cand_menos_b1.ic95"},
        "cobertura_v2": {"archivo": F_CAL, "clave": "resultados.prueba.v2.global.cobertura_pct"},
        "cobertura_v1": {"archivo": F_CAL, "clave": "resultados.prueba.v1.global.cobertura_pct"},
    }
    candidato = _candidato(R, reg, activo)
    if candidato:
        out["candidato"] = candidato
        out["origen"]["candidato"] = {"archivo": F_CAND, "clave": "prueba_reservada y robustez (cand frente a anterior)"}
    return out


def _candidato(R, reg, activo):
    """El candidato registrado sin activar: su error con el mismo protocolo que el activo (los dos años congelados y
    la prueba de nov–dic 2025) y su validación. None si no hay evaluación del candidato. Se detiene si la evaluación
    no lo compara con el activo o si el candidato ya es el activo."""
    f = R / F_CAND
    if not f.is_file():
        return None
    ev = json.loads(f.read_text(encoding="utf-8"))
    pr = ev["prueba_reservada"]
    mid = pr["modelos"]["activo"]
    if mid == activo or pr["modelos"].get("anterior") != activo:
        sys.exit(f"{F_CAND} evalúa {mid} frente a {pr['modelos'].get('anterior')}, no un candidato frente al activo {activo}.")
    rob = {a: {"wape": r["global"]["cand"]["wape"], "wape_activo": r["global"]["anterior"]["wape"],
               "ic95_diferencia": r["bootstrap"]["cand_menos_anterior"]["ic95"],
               "meses_mejor": r["meses_cand_mejor_que_anterior"], "meses": len(r["por_mes"]),
               "entrenado_hasta": r["entrenado_hasta"]}
           for a, r in ev["robustez"].items()}
    return {"model_id": mid, "estado": reg["modelos"].get(mid, {}).get("estado"),
            "version": pr["modelos"]["version_activo"],
            "wape_validacion": reg["modelos"].get(mid, {}).get("wape_validacion"),
            "wape_validacion_activo": reg["modelos"].get(activo, {}).get("wape_validacion"),
            "wape_prueba": pr["global"]["cand"]["wape"], "ic95_prueba": pr["bootstrap"]["cand"]["ic95"],
            "ic95_diferencia_prueba": pr["bootstrap"]["cand_menos_anterior"]["ic95"], "robustez": rob,
            "decision": "EntregaFinal/api_frecuencias/docs/evidencias/modelo/decision_fv3.md"}


# --- Pronóstico de corto plazo (experimento E14, el que sirve la API en /predictions/corto-plazo) -----------------------
F_CP = "EntregaFinal/pronostico_corto_plazo/resultados"
FUENTES_CP = [f"{F_CP}/prueba.json", f"{F_CP}/desglose_domingos_festivos.json", f"{F_CP}/figuras.json"]


def corto_plazo(R):
    """Las cifras de la prueba reservada (julio a diciembre de 2025, calculada una sola vez) por nivel y horizonte: WAPE
    del modelo y de las tres líneas base, IC95 de la diferencia con el promedio, cobertura de la banda P10–P90, por ruta
    a 60 minutos, los segmentos en que gana y el desglose de domingos y festivos (lo que no funcionó)."""
    base = R / F_CP
    pru = json.loads((base / "prueba.json").read_text(encoding="utf-8"))
    dom = json.loads((base / "desglose_domingos_festivos.json").read_text(encoding="utf-8"))
    fig = json.loads((base / "figuras.json").read_text(encoding="utf-8"))
    niveles = {}
    for nivel, por_h in pru["niveles"].items():
        niveles[nivel] = {}
        for h, b in por_h.items():
            t = b["todas_las_rutas"]
            niveles[nivel][h] = {"modelo": t["modelo"]["wape"], "promedio_dia_hora": t["promedio_dia_hora"]["wape"],
                                 "ultima_semana": t["ultima_semana"]["wape"], "persistencia": t["persistencia"]["wape"],
                                 "ic95_diferencia": t["ic95"]["modelo_menos_promedio_dia_hora"]["ic95"],
                                 "cobertura": b["banda_p10_p90"]["todas_las_rutas"]["cobertura_pct"],
                                 "celdas": t["modelo"]["n"],
                                 "por_ruta": {r: [v["modelo"]["wape"], v["promedio_dia_hora"]["wape"]]
                                              for r, v in b["por_ruta"].items()}}
    seg = pru["por_segmento"]["60"]
    tipos = dom["horizontes"]["60"]["todas_las_rutas"]
    return {"periodo": pru["periodos"]["prueba"], "entrenado_con": pru["entrenado_con"],
            "dias": pru["dias_del_periodo"], "repetida": pru["repetida"], "niveles": niveles,
            "segmentos_60": {"gana": seg["segmentos_en_que_gana_al_promedio"], "con_subidas": seg["segmentos_con_subidas"],
                             "subidas_pct": seg["subidas_en_segmentos_en_que_gana_pct"]},
            "tipo_de_dia_60": {k: {"modelo": v["modelo"], "promedio_dia_hora": v["promedio_dia_hora"], "dias": v["dias"],
                                   "gana": v["gana_el_modelo"]} for k, v in tipos.items()},
            "domingos_cra54_60": dom["horizontes"]["60"]["por_ruta"]["CRA 54"]["domingo"],
            "dia_de_ejemplo": dict(fig["dia_de_ejemplo"], ruta="CRA 54"),
            "origen": {"prueba": f"{F_CP}/prueba.json", "domingos": f"{F_CP}/desglose_domingos_festivos.json",
                       "dia_de_ejemplo": f"{F_CP}/figuras.json"}}


def solo_corto_plazo(R):
    """Escribe solo datos/corto_plazo.json y su entrada en datos/origen.json (sin tocar las demás)."""
    (DESTINO / "corto_plazo.json").write_text(json.dumps(corto_plazo(R), ensure_ascii=False, indent=1), encoding="utf-8")
    p = DESTINO / "origen.json"
    org = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"generador": "dash_app/preparar_datos.py", "archivos": {}}
    tam = (DESTINO / "corto_plazo.json").stat().st_size
    org.setdefault("archivos", {})["corto_plazo.json"] = {"fuentes": FUENTES_CP, "filas": None, "bytes": tam}
    org["generado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    org["total_bytes"] = sum(v["bytes"] for v in org["archivos"].values())
    p.write_text(json.dumps(org, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {'corto_plazo.json':28s} {tam / 1024:8.1f} KB")


def solo_producto(R):
    """Escribe solo datos/modelo_producto.json y actualiza su entrada en datos/origen.json (sin tocar las demás)."""
    (DESTINO / "modelo_producto.json").write_text(json.dumps(modelo_producto(R), ensure_ascii=False, indent=1), encoding="utf-8")
    p = DESTINO / "origen.json"
    org = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"generador": "dash_app/preparar_datos.py", "archivos": {}}
    tam = (DESTINO / "modelo_producto.json").stat().st_size
    org.setdefault("archivos", {})["modelo_producto.json"] = {"fuentes": [F_REG, F_EVAL, F_CAL, F_CAND], "filas": None,
                                                              "bytes": tam}
    org["generado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    org["total_bytes"] = sum(v["bytes"] for v in org["archivos"].values())
    p.write_text(json.dumps(org, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {'modelo_producto.json':28s} {tam / 1024:8.1f} KB")


def pronosticos(R):
    e11 = pd.read_parquet(R / "experimentos/E11_modelo_mejorado/predicciones_2025.parquet",
                          columns=["idruta", "ruta", "dia", "hora", "tipo_dia", "real", "prediccion", "pred_B1_manual", "horizonte"])
    e11 = e11[e11["horizonte"] == 7].drop(columns="horizonte").rename(columns={"prediccion": "E11", "pred_B1_manual": "B1"})
    e1 = pd.read_parquet(R / "experimentos/E1_lgbm_salida/predicciones_2025.parquet", columns=["ruta", "dia", "hora", "prediccion", "horizonte"])
    e1 = e1[e1["horizonte"] == 7].drop(columns="horizonte").rename(columns={"prediccion": "E1"})
    hib = pd.read_parquet(R / "experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet",
                          columns=["ruta", "dia", "hora", "real", "prediccion", "horizonte"])
    hib = hib[hib["horizonte"] == 7].drop(columns="horizonte").rename(columns={"prediccion": "E12", "real": "real_e12"})
    p = e11.merge(e1, on=["ruta", "dia", "hora"], how="left").merge(hib, on=["ruta", "dia", "hora"], how="left")
    dif = float((p["real"] - p["real_e12"]).abs().max())
    if dif > 1e-9:
        sys.exit(f"Los pasajeros reales de E11 y E12 no coinciden (diferencia máxima {dif}).")
    p = p.drop(columns="real_e12")
    for c in ["real", "B1", "E1", "E11", "E12"]:
        p[c] = p[c].astype("float32")
    p["hora"] = p["hora"].astype("int8")
    p["idruta"] = p["idruta"].astype("int8")
    return p.sort_values(["dia", "ruta", "hora"]).reset_index(drop=True)


def insumos_d5(R):
    cols = ["ruta", "dia", "hora", "tipo_dia", "real", "prediccion", "L_real", "mu", "s", "n_S0", "x_D5", "x_D5_oraculo",
            "nmin", "nmax", "minutos", "ciclo", "cv_d4", "flota_disp", "tasa_no_valido"]
    d = pd.read_parquet(R / "experimentos/D5_optimizacion_milp/decisiones_2025.parquet", columns=cols)
    e1 = pd.read_parquet(R / "experimentos/E1_lgbm_salida/predicciones_2025.parquet",
                         columns=["ruta", "dia", "hora", "horizonte", "pred_viajes_validos"])
    e1 = e1[e1["horizonte"] == 7].drop(columns="horizonte")
    par = pd.read_parquet(R / "experimentos/D1_optimizacion/parametros_operativos.parquet")[CLAVE + ["capacidad", "dist"]]
    d = d.merge(e1, on=["ruta", "dia", "hora"], how="left").merge(par, on=CLAVE, how="left")
    d["k0_plan"] = d["pred_viajes_validos"].clip(lower=1)
    d = d.drop(columns="pred_viajes_validos")
    ref = pd.read_parquet(R / "costos/resultados/d5_reoptimizado_decisiones.parquet", columns=["ruta", "dia", "hora", "x_corrida_1"])
    ref = ref.rename(columns={"x_corrida_1": "x_D5_fuente"})
    ref["dia"] = pd.to_datetime(ref["dia"])
    d = d.merge(ref, on=["ruta", "dia", "hora"], how="left")
    # comprobación: la cota mínima guardada es la de la política de intervalo máximo por tipo de día (D5, run.py)
    imax = d["tipo_dia"].map({"Laboral": 10.0, "Sábado": 10.0, "Domingo/festivo": 15.0})
    nmin = np.where(d["minutos"] > 0, np.ceil(d["minutos"] / imax - 1e-9), 0).astype(int)
    if (nmin != d["nmin"].values).any():
        print(f"aviso: {(nmin != d['nmin'].values).sum()} filas con nmin distinto de la política de intervalo máximo")
    return d.sort_values(["dia", "ruta", "hora"]).reset_index(drop=True)


def costos(R):
    u = json.loads((R / "costos/resultados/costos_unitarios.json").read_text(encoding="utf-8"))
    pl = json.loads((R / "costos/resultados/costos_para_planificador.json").read_text(encoding="utf-8"))
    claves = ["bus_hora_conductor", "costo_km_evitable", "tarifa_efectiva"]
    tarifa = pl["tarifa_neta_2026"]                      # el rango de la tarifa solo está en costos_para_planificador.json
    return {
        "descripcion": "Costos unitarios con fuente, precios 2026 (costos/README.md). central = el plan que reasigna (x_corrida_1).",
        "central": {k: float(u["2026"][k]) for k in claves},
        "bajo": {**{k: float(u["2026_bajo"][k]) for k in claves[:2]}, "tarifa_efectiva": float(tarifa["bajo"])},
        "alto": {**{k: float(u["2026_alto"][k]) for k in claves[:2]}, "tarifa_efectiva": float(tarifa["alto"])},
        "redondeados": {"costo_bus_hora": pl["costo_bus_hora"], "costo_km": pl["costo_km"], "tarifa_neta_2026": pl["tarifa_neta_2026"],
                        "elasticidad_beta": pl["elasticidad_beta"]},
        "fuente": "costos/resultados/costos_unitarios.json (claves 2026, 2026_bajo, 2026_alto); costos/resultados/costos_para_planificador.json",
    }


def datos_app(R):
    t = (R / "app/datos_app.js").read_text(encoding="utf-8")
    return json.loads(t[t.index("{"): t.rindex("}") + 1])


def iconos(R):
    t = (R / "app/iconos.js").read_text(encoding="utf-8")
    ICONOS.mkdir(parents=True, exist_ok=True)
    n = 0
    for nombre, trazos in re.findall(r"^\s*'?([a-z-]+)'?:\s*'(.+?)',\s*$", t, flags=re.M):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="2" '
               f'stroke-linecap="round" stroke-linejoin="round">{trazos}</svg>\n')
        (ICONOS / f"{nombre}.svg").write_text(svg, encoding="utf-8")
        n += 1
    return n


# ----------------------------------------------------------------------------------------------------------------------
# Ahorro anual (pantalla «¿Qué gana Sobusa?»)
# ----------------------------------------------------------------------------------------------------------------------
F_REOPT = "costos/resultados/d5_reoptimizado.csv"
F_DEC_R = "costos/resultados/d5_reoptimizado_decisiones.parquet"
F_ESC = "experimentos/D5_optimizacion_milp/escenarios.csv"
F_DEC_D5 = "experimentos/D5_optimizacion_milp/decisiones_2025.parquet"
F_D5J = "experimentos/D5_optimizacion_milp/resultados.json"
F_PLAN = "costos/resultados/costos_para_planificador.json"
F_UNIT = "costos/resultados/costos_unitarios.json"
F_AHO = "costos/resultados/ahorros_por_escenario.csv"
F_BETA = "costos/resultados/beta_equilibrio.csv"
F_LB = "costos/resultados/linea_base_2025.csv"
F_SIM = "simulacion_ahorro/resultados/simulacion_por_fecha.csv"
F_SENS = "simulacion_ahorro/resultados/sensibilidad_beta.csv"
F_D6 ="experimentos/D6_simulador/resultados_escenarios.json"
F_INFORME = "documentos/informe_resultados.md"
F_E8 = "experimentos/E8_validacion_2026/resultados.json"
F_P2 = "experimentos/P2_piloto_beta/resultados.json"
# los archivos de los que sale datos/ahorro_anual.json (su entrada en datos/origen.json)
FUENTES_AHORRO = [F_REOPT, F_DEC_R, F_ESC, F_DEC_D5, F_D5J, F_PLAN, F_UNIT, F_AHO, F_BETA, F_LB, F_SIM, F_SENS, F_D6, F_INFORME, F_E8, F_P2]
# la fila de la Tabla 2 del informe de resultados que cita la elasticidad de la literatura (el número va en el grupo 1)
PATRON_LITERATURA = r"^\| Literatura \(TCRP Report 95\) \| ≈ (\d+,\d+) \|"
# corridas de costos/reoptimizar_d5.py: el plan recomendado (reasigna) y D5 original revalorado con costos con fuente (recorta)
CORRIDA = {"reasigna": "D5 costos nuevos, pago por hora, e=0,5", "recorta": "D5 original (60.000/1.500/3.000, e=0,5)"}
ESCENARIO_HOY = "S0 oferta real"
RUTAS = ["SILENCIO", "CRA 54", "CL 72"]
ORDEN_TIPOS = ["Laboral", "Sábado", "Domingo/festivo"]
# columna de las salidas de cada plan en la tabla de decisiones unida (y de qué archivo y columna sale)
COL_PLAN = {"hoy": (F_DEC_R, "n_S0"), "reasigna": (F_DEC_R, "x_corrida_1"), "recorta": (F_DEC_D5, "x_D5")}

CAMPOS = {
    "salidas_dia": "Salidas válidas por día: promedio de los días de 2025, tres rutas (salidas/día)",
    "salidas_anio": "Salidas válidas en todo 2025, tres rutas (salidas/año)",
    "quitadas_dia": "Salidas por día que el plan quita donde hoy hay más: suma de max(hoy − plan, 0) por ruta × día × hora ÷ días",
    "puestas_dia": "Salidas por día que el plan añade donde hoy hay menos: suma de max(plan − hoy, 0) por ruta × día × hora ÷ días",
    "quitadas_anio": "Salidas al año que el plan quita: suma de max(hoy − plan, 0) por ruta × día × hora",
    "puestas_anio": "Salidas al año que el plan añade: suma de max(plan − hoy, 0) por ruta × día × hora",
    "menos_salidas_dia": "Salidas netas por día que el plan deja de hacer frente a hoy (quitadas − puestas)",
    "menos_salidas_anio": "Salidas netas al año que el plan deja de hacer frente a hoy (quitadas − puestas)",
    "var_salidas_pct": "Cambio de las salidas frente a hoy, en % (negativo = menos que hoy)",
    "buses_hora_dia": "Horas de bus en ruta por día (buses-hora/día)",
    "var_buses_hora_pct": "Cambio de los buses-hora frente a hoy, en % (negativo = menos que hoy)",
    "km_dia": "Km por día de la oferta de hoy en la base de los escenarios de D5 (solo en planes.hoy)",
    "var_km_pct": "Cambio de los km frente a hoy, en % (negativo = menos que hoy), sobre planes.hoy.km_dia",
    "delta_buses_hora_anio": "Buses-hora al año que el plan deja de recorrer frente a hoy (positivo = menos que hoy)",
    "delta_km_anio": "Km al año que el plan deja de recorrer frente a hoy (positivo = menos que hoy)",
    "buses_hora_anio": "Horas de bus en ruta al año: buses_hora_dia × días del año (buses-hora/año)",
    "km_anio": "Km al año en la base de los escenarios de D5: hoy = km_dia × días del año; cada plan = hoy − delta_km_anio (km/año)",
    "costo_km_conductor_Mcop": "Lo que cuestan al año los km (costo evitable por km) y las horas de conductor (pagado por hora) del plan, a precios 2026 y en la misma base que el ahorro: km_anio × costo por km + buses_hora_anio × costo por bus-hora (M COP/año). No incluye costos fijos: no es el costo total de operación",
    "ahorro_pct_costo": "ahorro_operacion_Mcop como % de planes.hoy.costo_km_conductor_Mcop (lo que hoy cuestan los km y las horas de conductor)",
    "dif_regla_perdidos_Mcop": "Pasajes perdidos de la contabilidad conservadora (forma de potencia) menos los de la simétrica (forma lineal): pasajes_perdidos_Mcop − simetrica.perdidos_Mcop (M COP/año). saldo_conservador + simetrica.ganados_Mcop + dif_regla_perdidos_Mcop = saldo_simetrico",
    "por_hora.quitadas": "Salidas medias por día de ese tipo que el plan quita, por hora de salida: suma de max(hoy − plan, 0) por ruta y hora ÷ días del tipo (tres rutas)",
    "por_hora.puestas": "Salidas medias por día de ese tipo que el plan añade, por hora de salida: suma de max(plan − hoy, 0) por ruta y hora ÷ días del tipo (tres rutas)",
    "por_hora.salidas_dia": "Salidas medias por día de ese tipo de cada plan, tres rutas (suma de su serie por hora)",
    "por_hora.quitadas_dia": "Salidas medias por día de ese tipo que el plan quita (suma de su serie «quitadas»)",
    "por_hora.puestas_dia": "Salidas medias por día de ese tipo que el plan añade (suma de su serie «puestas»)",
    "convenciones.supuestos_iniciales": "Costos supuestos con los que D5 eligió el plan que recorta: COP por bus-hora, COP por km y tarifa en COP",
    "ahorro_km_Mcop": "Parte del ahorro en operación que viene de los km: delta_km_anio × costo evitable por km (M COP/año)",
    "ahorro_conductor_Mcop": "Parte del ahorro en operación que viene del conductor pagado por hora: delta_buses_hora_anio × costo por bus-hora (M COP/año)",
    "ahorro_operacion_Mcop": "Lo que Sobusa deja de pagar al año en km y en horas de conductor pagado por hora (M COP/año, precios 2026). No es ganancia: no descuenta los pasajes en juego",
    "espera_min": "Espera media estimada por pasajero (min)",
    "pax_sobre_capacidad_dia": "Pasajeros por día por encima de la capacidad del bus en el tramo crítico",
    "pct_horas_fc_mayor_1": "Horas con factor de carga mayor que 1 (% de las horas)",
    "pax_en_riesgo_dia": "Pasajeros por día que se pueden perder donde se quitan salidas (contabilidad conservadora): central con la β central; bajo y alto con los extremos del rango de β (convenciones.beta)",
    "pax_netos_dia_simetrico": "Pasajeros netos por día si los ganados donde se añaden salidas cuentan igual que los perdidos (contabilidad simétrica, β central)",
    "pasajes_perdidos_Mcop": "Valor al año de pax_en_riesgo_dia.central: pasajeros/día × días del año × tarifa neta (M COP/año)",
    "pasajes_ganados_Mcop": "Lo que la contabilidad simétrica suma a la conservadora: saldo_simetrico − saldo_conservador (M COP/año). Son los ganados donde se añaden salidas más la diferencia entre la pérdida conservadora (forma de potencia) y la lineal de la simétrica; el desglose de la fuente está en «simetrica»",
    "saldo_conservador_Mcop": "ahorro_operacion_Mcop − pasajes_perdidos_Mcop (M COP/año)",
    "saldo_simetrico_Mcop": "saldo_conservador_Mcop + pasajes_ganados_Mcop = ahorro_operacion_Mcop + simetrica.ganados_Mcop − simetrica.perdidos_Mcop (M COP/año)",
    "saldo_conservador_por_beta_Mcop": "Saldo conservador del plan con cada β del rango (convenciones.beta), conductor por hora (M COP/año). La fuente no tiene el saldo simétrico con otras β",
    "simetrica": "La contabilidad simétrica de la fuente separada en pasajeros ganados (donde se añaden salidas) y perdidos (donde se quitan), con la forma lineal de costos/reoptimizar_d5.py (pasajeros/día y M COP/año)",
    "beta_equilibrio": "β por encima de la cual el saldo conservador del plan es negativo (pago por hora); null si la fuente no la calcula",
    "respuesta_equilibrio": "Respuesta de los pasajeros a las salidas que se ponen (cuánto suben, en proporción, los pasajeros de una hora cuando suben sus salidas) desde la que el plan deja de perder en el año: con ella, el ahorro en operación más los pasajes ganados iguala los pasajes perdidos. Nunca se ha medido, así que va en tres formas de cuenta, todas con la pérdida al quitar de la β central. «lineal»: perdidos y ganados con la regla lineal de la contabilidad simétrica = (simetrica.perdidos_Mcop − ahorro_operacion_Mcop) × β central ÷ simetrica.ganados_Mcop. «mixta»: perdidos con la forma de potencia de la contabilidad conservadora y ganados lineales = −saldo_conservador_Mcop × β central ÷ simetrica.ganados_Mcop. «potencia»: perdidos y ganados con la forma de potencia, que es la elasticidad que estima el piloto = la r que anula saldo_conservador_Mcop + Σ real × ((x ÷ n_S0)^r − 1) × tarifa en las horas donde el plan pone salidas. «por_beta» repite las tres con la pérdida de los extremos del rango de β: la lineal escala los perdidos lineales (× β ÷ β central) y la mixta y la de potencia usan saldo_conservador_por_beta_Mcop. Un valor de cero o menos quiere decir que, con esa cuenta, el plan no pierde aunque las salidas que se ponen no atraigan a nadie. Es el umbral de todo el plan del año en las tres rutas; el 0,62 del informe (sección del piloto) es otra cuenta, la de un día de piloto en CRA 54 que pasa salidas de 9-11 h a 14-15 h. null si el saldo conservador no es negativo o el plan no pone salidas",
    "saldo_respuesta_central_Mcop": "Saldo del año si las salidas que se ponen atraen pasajeros con la β central, la medida al quitar, en las tres formas de cuenta de respuesta_equilibrio (M COP/año): «lineal» es saldo_simetrico_Mcop; «mixta» = saldo_conservador_Mcop + simetrica.ganados_Mcop; «potencia» = saldo_conservador_Mcop + Σ real × ((x ÷ n_S0)^β − 1) × tarifa. null donde respuesta_equilibrio es null",
    "pistas_respuesta": "Lo poco que se sabe de la respuesta de los pasajeros a las salidas que se ponen, que nunca se ha medido en Sobusa. «literatura»: la elasticidad de los pasajeros a las salidas que cita el informe de resultados (TCRP Report 95, promedio internacional). «aparente_2026»: la asociación entre rutas de E8 (en 2026 hubo más viajes y más subidas), que es descriptiva, no causal y frágil; «aparente_2026_por_ruta», su mínimo y su máximo mirando cada ruta sin comparar, y «aparente_2026_sin_limpiar», la misma antes de limpiar las bandas corruptas de CRA 54; «reserva_2026» es la reserva que E8 anota sobre esa lectura (en los días especiales los viajes suben y las subidas no). No son una medición ni dan una probabilidad",
    "piloto": "El piloto de P2 dicho en saldo (M COP en sus 8 semanas). «saldo_sin_respuesta_Mcop»: lo que deja si las salidas que se ponen no atraen a nadie = ahorro de los recortes − pasajeros en riesgo × tarifa neta − costo de los refuerzos, con los pasajeros en riesgo de la β central («central»: es el saldo conservador de P2), de la β alta del rango («alto») y de la pérdida proporcional, β = 1, que es el tope de pasajeros de la regla de parada 3 («tope»: si se pierden más, el piloto se detiene). «saldo_respuesta_central_Mcop»: lo que deja si atraen con la β central (el saldo simétrico de P2). «pax_en_riesgo»: los pasajeros en riesgo de cada caso",
    "por_ruta": "Salidas por día y por año de cada plan en cada ruta",
    "por_hora": "Salidas medias por día de cada tipo de día, por hora de salida, tres rutas sumadas; «dias» = días de ese tipo en 2025",
    "contexto": "Línea base de 2025 (precios 2025, conductor por hora; incluye los viajes marcados cancelados que corrieron) y pasajeros de 2025. No es la base de las comparaciones de los planes",
    "palancas": "Medidas que se miden aparte de los planes. No se suman entre sí ni a un plan",
    "palancas.domingos_festivos": "El plan que recorta aplicado solo a domingos y festivos (simulación por fecha, plan a). Es una parte del saldo anual del plan que recorta (plan_recorta_por_tipo_dia suma ese saldo), no algo que se le añade",
    "palancas.giro_corto_35": "Giro corto en el punto 35 de CRA 54 sobre la oferta de hoy; bajadas_forzadas_dia (simulador D6, día laboral típico de CRA 54) no se valoran en el saldo; valor_social_espera_Mcop es tiempo de los pasajeros valorado, no caja",
    "palancas.regularizar_cl72": "Las mismas salidas de cada día de CL 72, equiespaciadas; valor_social_espera_Mcop es tiempo de espera de los pasajeros valorado, no caja de Sobusa",
}


def _csv_costos(R, rel):
    """CSV de costos/ y simulacion_ahorro/: ';' y coma decimal."""
    return pd.read_csv(R / rel, sep=";", decimal=",", encoding="utf-8-sig")


def _fila(df, **filtro):
    """La única fila que cumple el filtro; si hay cero o varias, se detiene."""
    m = np.ones(len(df), dtype=bool)
    for col, v in filtro.items():
        m &= (df[col] == v).to_numpy()
    if m.sum() != 1:
        sys.exit(f"Se esperaba una fila con {filtro} y hay {int(m.sum())}.")
    return df[m].iloc[0]


def _num(v):
    """Tipos de Python para el JSON (sin numpy) y sin el −0,0 que dejan las restas."""
    if isinstance(v, (list, tuple, np.ndarray, pd.Series)):
        return [_num(x) for x in v]
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_)):
        return int(v)
    f = float(v)
    return 0.0 if f == 0 else f


def _entero(x, nombre):
    """Conteo guardado en float (salidas): se exige que sea entero."""
    if abs(x - round(x)) > 1e-6:
        sys.exit(f"{nombre} debería ser un número entero de salidas y es {x}.")
    return int(round(x))


def _comprobar(nombre, a, b, tol=1e-6):
    """Identidad que debe cumplirse al escribir ahorro_anual.json (tolerancia relativa)."""
    if not abs(a - b) <= tol * max(1.0, abs(b)):
        sys.exit(f"Comprobación fallida en ahorro_anual.json: {nombre}: {a} frente a {b}.")


def ahorro_anual(R):
    """Cifras de «¿Qué gana Sobusa?» con el origen de cada una.

    hoy = oferta real de 2025 (S0, salidas válidas); reasigna = D5 reoptimizado con costos con fuente (e = 0,5, conductor
    pagado por hora), el plan recomendado; recorta = D5 original (supuestos 60.000 / 1.500 / 3.000) con sus decisiones
    revaloradas con costos con fuente. β central, precios 2026 y la convención de costos/reoptimizar_d5.py: pasajes =
    pasajeros/día × 365 × tarifa neta. Contabilidad conservadora: solo cuentan los pasajeros perdidos donde se quitan
    salidas, pax × (1 − (x/n0)^β); simétrica: también los ganados donde se añaden, con la forma lineal pax × β × (x − n0)/n0.
    """
    out = {"descripcion": ("Ahorro anual frente a hoy (2025, tres rutas): el plan que reasigna (recomendado) y el que recorta, "
                           "con los pasajes en juego en las dos contabilidades. Las palancas van aparte y no se suman."),
           "convenciones": {}, "planes": {"hoy": {}, "reasigna": {}, "recorta": {}}, "por_ruta": {}, "por_hora": {},
           "contexto": {}, "pistas_respuesta": {}, "piloto": {}, "palancas": {}}
    org = {}

    def poner(ruta, valor, archivo, clave, calculo=None):
        """Guarda valor en out en la ruta 'a.b.c' y anota su archivo y su clave (y el cálculo, si es derivado)."""
        d = out
        *padres, hoja = ruta.split(".")
        for p in padres:
            d = d.setdefault(p, {})
        d[hoja] = _num(valor)
        org[ruta] = {"archivo": archivo, "clave": clave, **({"calculo": calculo} if calculo else {})}
        return d[hoja]

    reopt = _csv_costos(R, F_REOPT)
    esc = pd.read_csv(R / F_ESC, encoding="utf-8-sig")
    hoy = _fila(esc, ruta="Todas", tipo_dia="Todos", escenario=ESCENARIO_HOY)
    pl = json.loads((R / F_PLAN).read_text(encoding="utf-8"))
    un = json.loads((R / F_UNIT).read_text(encoding="utf-8"))

    # decisiones por ruta x día x hora de 2025: n_S0 (hoy) y x_corrida_1 (reasigna) de costos/; x_D5 (recorta) de D5
    a = pd.read_parquet(R / F_DEC_R, columns=["ruta", "dia", "hora", "tipo_dia", "real", "n_S0", "x_corrida_0", "x_corrida_1"])
    b = pd.read_parquet(R / F_DEC_D5, columns=["ruta", "dia", "hora", "tipo_dia", "n_S0", "x_D5"])
    for t in (a, b):
        t["dia"] = pd.to_datetime(t["dia"])
    dec = a.merge(b, on=["ruta", "dia", "hora"], how="outer", suffixes=("", "_d5"), indicator=True)
    if ((dec["_merge"] != "both").any() or not (dec["n_S0"] == dec["n_S0_d5"]).all()
            or not (dec["tipo_dia"] == dec["tipo_dia_d5"]).all()):
        sys.exit("Los dos archivos de decisiones de 2025 no tienen las mismas filas, el mismo n_S0 o el mismo tipo de día.")
    if not (dec["x_corrida_0"] == dec["x_D5"]).all():   # reoptimizar_d5.py reproduce a D5 original hora por hora
        sys.exit("x_corrida_0 (D5 original en costos/) no coincide con x_D5 de D5.")
    dec = dec.rename(columns={"n_S0": "hoy", "x_corrida_1": "reasigna", "x_D5": "recorta"})
    n_dias = int(dec["dia"].nunique())

    # convenciones
    c = "convenciones."
    poner(c + "dias_anio", n_dias, F_DEC_R, "dia → n distintos")
    tarifa = poner(c + "tarifa_neta_cop", pl["tarifa_neta_2026"]["central"], F_PLAN, "tarifa_neta_2026.central")
    _comprobar("tarifa neta igual a la que usó costos/reoptimizar_d5.py", tarifa, un["2026"]["tarifa_efectiva"])
    fr = _fila(reopt, corrida=CORRIDA["reasigna"])
    kf = f"[corrida={CORRIDA['reasigna']}]"
    poner(c + "costo_km_cop", fr["costo_km_usado"], F_REOPT, kf + ".costo_km_usado")
    poner(c + "costo_bus_hora_cop", fr["costo_bus_hora_usado"], F_REOPT, kf + ".costo_bus_hora_usado")
    for k in ("central", "bajo", "alto"):
        poner(c + f"beta.{k}", pl["elasticidad_beta"][k], F_PLAN, f"elasticidad_beta.{k}")
    beta_c = out["convenciones"]["beta"]["central"]
    out["convenciones"]["precios"] = "2026"
    out["convenciones"]["pago_conductor"] = "por hora"

    # hoy: la referencia (todo lo que se mide frente a hoy vale cero)
    p, kh = "planes.hoy.", f"[ruta=Todas&tipo_dia=Todos&escenario={ESCENARIO_HOY}]"
    poner(p + "salidas_dia", hoy["salidas_dia"], F_ESC, kh + ".salidas_dia")
    s_hoy = poner(p + "salidas_anio", _entero(dec["hoy"].sum(), "salidas de hoy"), F_DEC_R, "n_S0 → suma")
    _comprobar("hoy: salidas al año = salidas por día × días", s_hoy, hoy["salidas_dia"] * n_dias)
    for col in ["quitadas_dia", "puestas_dia", "quitadas_anio", "puestas_anio", "menos_salidas_dia", "menos_salidas_anio",
                "var_salidas_pct"]:
        poner(p + col, 0, "definición", "hoy es la referencia")
    poner(p + "buses_hora_dia", hoy["buses_hora_dia"], F_ESC, kh + ".buses_hora_dia")
    poner(p + "km_dia", hoy["km_dia"], F_ESC, kh + ".km_dia")
    for col in ["var_buses_hora_pct", "var_km_pct", "delta_buses_hora_anio", "delta_km_anio", "ahorro_km_Mcop",
                "ahorro_conductor_Mcop", "ahorro_operacion_Mcop"]:
        poner(p + col, 0, "definición", "hoy es la referencia")
    poner(p + "espera_min", hoy["espera_media_min"], F_ESC, kh + ".espera_media_min")
    poner(p + "pax_sobre_capacidad_dia", hoy["pax_sobre_capacidad_dia"], F_ESC, kh + ".pax_sobre_capacidad_dia")
    poner(p + "pct_horas_fc_mayor_1", hoy["pct_horas_fc_mayor_1"], F_ESC, kh + ".pct_horas_fc_mayor_1")
    for col in ["pax_en_riesgo_dia.central", "pax_en_riesgo_dia.bajo", "pax_en_riesgo_dia.alto", "pax_netos_dia_simetrico",
                "pasajes_perdidos_Mcop", "pasajes_ganados_Mcop", "saldo_conservador_Mcop", "saldo_simetrico_Mcop",
                "saldo_conservador_por_beta_Mcop.bajo", "saldo_conservador_por_beta_Mcop.central",
                "saldo_conservador_por_beta_Mcop.alto", "simetrica.pax_ganados_dia", "simetrica.pax_perdidos_dia", "simetrica.ganados_Mcop", "simetrica.perdidos_Mcop"]:
        poner(p + col, 0, "definición", "hoy es la referencia")
    poner(p + "beta_equilibrio", None, "definición", "hoy es la referencia")
    poner(p + "respuesta_equilibrio", None, "definición", "hoy es la referencia")
    poner(p + "saldo_respuesta_central_Mcop", None, "definición", "hoy es la referencia")
    # lo que hoy cuestan los km y las horas de conductor (precios 2026, la misma base del ahorro): base del % de ahorro
    ckm, cbh = out["convenciones"]["costo_km_cop"], out["convenciones"]["costo_bus_hora_cop"]
    bh_hoy = poner(p + "buses_hora_anio", hoy["buses_hora_dia"] * n_dias, F_ESC, kh + ".buses_hora_dia",
                   "buses_hora_dia × convenciones.dias_anio")
    km_hoy = poner(p + "km_anio", hoy["km_dia"] * n_dias, F_ESC, kh + ".km_dia", "km_dia × convenciones.dias_anio")
    costo_hoy = poner(p + "costo_km_conductor_Mcop", (km_hoy * ckm + bh_hoy * cbh) / 1e6, f"{F_ESC}; {F_REOPT}",
                      f"{kh}.km_dia, buses_hora_dia; {kf}.costo_km_usado, costo_bus_hora_usado",
                      "(km_anio × convenciones.costo_km_cop + buses_hora_anio × convenciones.costo_bus_hora_cop) × 1e-06")
    poner(p + "ahorro_pct_costo", 0, "definición", "hoy es la referencia")
    poner(p + "dif_regla_perdidos_Mcop", 0, "definición", "hoy es la referencia")

    # los dos planes: cifras de su fila de d5_reoptimizado.csv y salidas hora por hora de sus decisiones
    n0, pax = dec["hoy"].to_numpy(), dec["real"].to_numpy()
    beta = _csv_costos(R, F_BETA)
    sens = _csv_costos(R, F_SENS)
    for nombre in ("reasigna", "recorta"):
        f, kf = _fila(reopt, corrida=CORRIDA[nombre]), f"[corrida={CORRIDA[nombre]}]"
        arch_x, col_x = COL_PLAN[nombre]
        p = f"planes.{nombre}."
        x = dec[nombre].to_numpy()
        quit, pue = float(np.clip(n0 - x, 0, None).sum()), float(np.clip(x - n0, 0, None).sum())
        poner(p + "salidas_dia", f["salidas_dia"], F_REOPT, kf + ".salidas_dia")
        s = poner(p + "salidas_anio", _entero(x.sum(), f"salidas de {nombre}"), arch_x, f"{col_x} → suma")
        _comprobar(f"{nombre}: salidas al año = salidas por día × días", s, f["salidas_dia"] * n_dias)
        kq = f"{F_DEC_R} (n_S0)" + ("" if arch_x == F_DEC_R else f"; {arch_x} ({col_x})")
        poner(p + "quitadas_dia", quit / n_dias, kq, f"max(n_S0 − {col_x}, 0) → suma", "quitadas_anio ÷ convenciones.dias_anio")
        poner(p + "puestas_dia", pue / n_dias, kq, f"max({col_x} − n_S0, 0) → suma", "puestas_anio ÷ convenciones.dias_anio")
        q = poner(p + "quitadas_anio", _entero(quit, "quitadas"), kq, f"max(n_S0 − {col_x}, 0) → suma")
        u = poner(p + "puestas_anio", _entero(pue, "puestas"), kq, f"max({col_x} − n_S0, 0) → suma")
        poner(p + "menos_salidas_dia", (q - u) / n_dias, kq, "quitadas − puestas",
              "(quitadas_anio − puestas_anio) ÷ convenciones.dias_anio")
        m = poner(p + "menos_salidas_anio", q - u, kq, "quitadas − puestas", "quitadas_anio − puestas_anio")
        _comprobar(f"{nombre}: quitadas − puestas = salidas de hoy − salidas del plan", m, s_hoy - s)
        poner(p + "var_salidas_pct", (f["salidas_dia"] / hoy["salidas_dia"] - 1) * 100, f"{F_REOPT}; {F_ESC}",
              f"{kf}.salidas_dia; {kh}.salidas_dia", "(salidas_dia ÷ planes.hoy.salidas_dia − 1) × 100")
        poner(p + "buses_hora_dia", f["buses_hora_dia"], F_REOPT, kf + ".buses_hora_dia")
        poner(p + "var_buses_hora_pct", (f["buses_hora_dia"] / hoy["buses_hora_dia"] - 1) * 100, f"{F_REOPT}; {F_ESC}",
              f"{kf}.buses_hora_dia; {kh}.buses_hora_dia", "(buses_hora_dia ÷ planes.hoy.buses_hora_dia − 1) × 100")
        poner(p + "var_km_pct", -f["delta_km_anual"] / (hoy["km_dia"] * n_dias) * 100, f"{F_REOPT}; {F_ESC}",
              f"{kf}.delta_km_anual; {kh}.km_dia", "−delta_km_anio ÷ (planes.hoy.km_dia × convenciones.dias_anio) × 100")
        poner(p + "delta_buses_hora_anio", f["delta_buses_hora_anual"], F_REOPT, kf + ".delta_buses_hora_anual")
        _comprobar(f"{nombre}: buses-hora al año = (hoy − plan) × días", f["delta_buses_hora_anual"],
                   (hoy["buses_hora_dia"] - f["buses_hora_dia"]) * n_dias)
        poner(p + "delta_km_anio", f["delta_km_anual"], F_REOPT, kf + ".delta_km_anual")
        ah_km = poner(p + "ahorro_km_Mcop", f["delta_km_anual"] * f["costo_km_usado"] / 1e6, F_REOPT,
                      kf + ".delta_km_anual × costo_km_usado × 1e-06")
        ah_co = poner(p + "ahorro_conductor_Mcop", f["delta_buses_hora_anual"] * f["costo_bus_hora_usado"] / 1e6, F_REOPT,
                      kf + ".delta_buses_hora_anual × costo_bus_hora_usado × 1e-06")
        ahorro = poner(p + "ahorro_operacion_Mcop", f["ahorro_operativo_pago_hora_Mcop"], F_REOPT,
                       kf + ".ahorro_operativo_pago_hora_Mcop")
        _comprobar(f"{nombre}: ahorro en operación = km + conductor", ahorro, ah_km + ah_co)
        _comprobar(f"{nombre}: costo por km igual al de convenciones", f["costo_km_usado"], ckm)
        _comprobar(f"{nombre}: costo por bus-hora igual al de convenciones", f["costo_bus_hora_usado"], cbh)
        bh = poner(p + "buses_hora_anio", f["buses_hora_dia"] * n_dias, F_REOPT, kf + ".buses_hora_dia",
                   "buses_hora_dia × convenciones.dias_anio")
        km = poner(p + "km_anio", km_hoy - f["delta_km_anual"], f"{F_ESC}; {F_REOPT}", f"{kh}.km_dia; {kf}.delta_km_anual",
                   "planes.hoy.km_anio − delta_km_anio")
        costo = poner(p + "costo_km_conductor_Mcop", (km * ckm + bh * cbh) / 1e6, f"{F_ESC}; {F_REOPT}",
                      f"{kh}.km_dia; {kf}.delta_km_anual, buses_hora_dia, costo_km_usado, costo_bus_hora_usado",
                      "(km_anio × convenciones.costo_km_cop + buses_hora_anio × convenciones.costo_bus_hora_cop) × 1e-06")
        _comprobar(f"{nombre}: costo de km y conductor = el de hoy − ahorro en operación", costo, costo_hoy - ahorro)
        poner(p + "ahorro_pct_costo", ahorro / costo_hoy * 100, f"{F_REOPT}; {F_ESC}",
              f"{kf}.ahorro_operativo_pago_hora_Mcop; {kh}.km_dia, buses_hora_dia",
              "ahorro_operacion_Mcop ÷ planes.hoy.costo_km_conductor_Mcop × 100")
        poner(p + "espera_min", f["espera_media_min"], F_REOPT, kf + ".espera_media_min")
        poner(p + "pax_sobre_capacidad_dia", f["pax_sobre_capacidad_dia"], F_REOPT, kf + ".pax_sobre_capacidad_dia")
        poner(p + "pct_horas_fc_mayor_1", f["pct_horas_fc_mayor_1"], F_REOPT, kf + ".pct_horas_fc_mayor_1")
        for k in ("central", "bajo", "alto"):
            poner(p + f"pax_en_riesgo_dia.{k}", f[f"pax_perdidos_dia_{k}"], F_REOPT, kf + f".pax_perdidos_dia_{k}")
        netos = poner(p + "pax_netos_dia_simetrico", f["pax_netos_dia_simetrico_beta070"], F_REOPT,
                      kf + ".pax_netos_dia_simetrico_beta070")
        perd = poner(p + "pasajes_perdidos_Mcop", f["pax_perdidos_dia_central"] * n_dias * tarifa / 1e6, f"{F_REOPT}; {F_PLAN}",
                     f"{kf}.pax_perdidos_dia_central; tarifa_neta_2026.central",
                     "pax_en_riesgo_dia.central × convenciones.dias_anio × convenciones.tarifa_neta_cop × 1e-06")
        cons = poner(p + "saldo_conservador_Mcop", f["neto_pago_hora_beta070_Mcop"], F_REOPT, kf + ".neto_pago_hora_beta070_Mcop")
        _comprobar(f"{nombre}: saldo conservador = ahorro − pasajes perdidos", cons, ahorro - perd)
        sim = poner(p + "saldo_simetrico_Mcop", f["neto_simetrico_pago_hora_beta070_Mcop"], F_REOPT,
                    kf + ".neto_simetrico_pago_hora_beta070_Mcop")
        gan = poner(p + "pasajes_ganados_Mcop", (netos + f["pax_perdidos_dia_central"]) * n_dias * tarifa / 1e6,
                    f"{F_REOPT}; {F_PLAN}", f"{kf}.pax_netos_dia_simetrico_beta070; {kf}.pax_perdidos_dia_central; "
                    "tarifa_neta_2026.central", "(pax_netos_dia_simetrico + pax_en_riesgo_dia.central) × "
                    "convenciones.dias_anio × convenciones.tarifa_neta_cop × 1e-06 = saldo_simetrico − saldo_conservador")
        _comprobar(f"{nombre}: saldo simétrico = saldo conservador + pasajes ganados", sim, cons + gan)
        # desglose de la contabilidad simétrica con la fórmula lineal de costos/reoptimizar_d5.py (n0 = 0 no suma)
        with np.errstate(divide="ignore", invalid="ignore"):
            dP = np.where(n0 > 0, pax * beta_c * (x - n0) / np.where(n0 > 0, n0, 1), 0.0)
        g, l = float(dP[dP > 0].sum()), float(-dP[dP < 0].sum())
        kd = f"{F_DEC_R} (real, n_S0)" + (f"; {arch_x} ({col_x})" if arch_x != F_DEC_R else f" ({col_x})")
        cal = f"real × β central × ({col_x} − n_S0) ÷ n_S0 donde n_S0 > 0"
        poner(p + "simetrica.pax_ganados_dia", g / n_dias, kd, cal + ", parte positiva → suma ÷ días")
        poner(p + "simetrica.pax_perdidos_dia", l / n_dias, kd, cal + ", parte negativa → −suma ÷ días")
        g_m = poner(p + "simetrica.ganados_Mcop", g * tarifa / 1e6, f"{kd}; {F_PLAN}", cal + ", parte positiva → suma",
                    "× convenciones.tarifa_neta_cop × 1e-06")
        l_m = poner(p + "simetrica.perdidos_Mcop", l * tarifa / 1e6, f"{kd}; {F_PLAN}", cal + ", parte negativa → −suma",
                    "× convenciones.tarifa_neta_cop × 1e-06")
        _comprobar(f"{nombre}: ganados − perdidos (simétrica) = pasajeros netos", (g - l) / n_dias, netos)
        _comprobar(f"{nombre}: ahorro + ganados − perdidos = saldo simétrico", ahorro + g_m - l_m, sim)
        # lo que separa las dos contabilidades además de los ganados: la pérdida de potencia frente a la lineal
        dif = poner(p + "dif_regla_perdidos_Mcop", perd - l_m, f"{F_REOPT}; {kd}; {F_PLAN}",
                    f"{kf}.pax_perdidos_dia_central; {cal}, parte negativa", "pasajes_perdidos_Mcop − simetrica.perdidos_Mcop")
        _comprobar(f"{nombre}: saldo conservador + ganados (simétrica) + diferencia de regla = saldo simétrico",
                   cons + g_m + dif, sim)
        # saldo conservador con cada β del rango (sensibilidad_beta.csv: plan a = recorta, plan b = reasigna)
        letra = {"reasigna": "b", "recorta": "a"}[nombre]
        for k in ("bajo", "central", "alto"):
            bk = out["convenciones"]["beta"][k]
            fb = sens[(sens["plan"] == letra) & np.isclose(sens["beta"], bk)]
            if len(fb) != 1:
                sys.exit(f"sensibilidad_beta.csv no tiene una fila para el plan {letra} con β = {bk}.")
            fb = fb.iloc[0]
            _comprobar(f"{nombre}: pasajeros en riesgo con β {k} iguales en las dos fuentes", fb["pasajeros_en_riesgo_dia"],
                       f[f"pax_perdidos_dia_{k}"])
            poner(p + f"saldo_conservador_por_beta_Mcop.{k}", fb["neto_hora_Mcop"], F_SENS,
                  f"[beta={k} (convenciones.beta.{k})&plan={letra}].neto_hora_Mcop")
        _comprobar(f"{nombre}: saldo con β central = saldo conservador", out["planes"][nombre]["saldo_conservador_por_beta_Mcop"]["central"], cons)
        if nombre == "recorta":
            poner(p + "beta_equilibrio", float(_fila(beta, clave="D5")["pago por hora"]), F_BETA, '[clave=D5]["pago por hora"]')
        else:
            poner(p + "beta_equilibrio", None, "sin fuente",
                  "costos/ no calcula la β de equilibrio del plan que reasigna (la Tabla 3 del informe deja «—»)")
        # Desde qué respuesta a las salidas que se ponen deja de perder el plan en el año. Esa respuesta no se ha medido, y el
        # umbral cambia con la forma de la cuenta: lineal al quitar y al poner (la simétrica de punta a punta), mixta (la
        # pérdida de potencia de la conservadora y la ganancia lineal) y de potencia en los dos lados (la que estima el piloto)
        sube = (n0 > 0) & (x > n0)
        razon, pax_sube = x[sube] / n0[sube], pax[sube]

        def ganados_potencia(r):
            """Pasajes al año (M COP) que se ganan donde el plan pone salidas si los pasajeros suben como (x ÷ n0)^r."""
            return float((pax_sube * (razon ** r - 1)).sum()) * tarifa / 1e6

        def raiz(saldo):
            """La r que anula saldo + ganados_potencia(r), por bisección (los ganados crecen con r y el saldo es negativo)."""
            lo, hi = 0.0, 4.0
            if saldo + ganados_potencia(hi) < 0:
                sys.exit(f"{nombre}: ni con una respuesta de {hi} cubren los pasajes ganados un saldo de {saldo} M COP.")
            for _ in range(100):
                medio = (lo + hi) / 2
                lo, hi = (medio, hi) if saldo + ganados_potencia(medio) < 0 else (lo, medio)
            return (lo + hi) / 2

        pe, ps = p + "respuesta_equilibrio.", p + "saldo_respuesta_central_Mcop."
        ksube = f"real, n_S0 y {col_x} donde {col_x} > n_S0 > 0"
        if cons < 0 and g_m > 0 and pax_sube.size:
            poner(pe + "lineal", (l_m - ahorro) * beta_c / g_m, f"{F_REOPT}; {kd}; {F_PLAN}",
                  "ahorro_operacion_Mcop; simetrica.perdidos_Mcop; simetrica.ganados_Mcop; convenciones.beta.central",
                  "(simetrica.perdidos_Mcop − ahorro_operacion_Mcop) × convenciones.beta.central ÷ simetrica.ganados_Mcop")
            poner(pe + "mixta", -cons * beta_c / g_m, f"{F_REOPT}; {kd}; {F_PLAN}",
                  "saldo_conservador_Mcop; simetrica.ganados_Mcop; convenciones.beta.central",
                  "−saldo_conservador_Mcop × convenciones.beta.central ÷ simetrica.ganados_Mcop")
            poner(pe + "potencia", raiz(cons), f"{F_REOPT}; {kd}; {F_PLAN}", f"saldo_conservador_Mcop; {ksube}",
                  "la r que anula saldo_conservador_Mcop + Σ real × ((x ÷ n_S0)^r − 1) × convenciones.tarifa_neta_cop × 1e-06 "
                  "(bisección)")
            for k in ("bajo", "alto"):
                sk = out["planes"][nombre]["saldo_conservador_por_beta_Mcop"][k]
                if sk >= 0:
                    sys.exit(f"{nombre}: el saldo conservador con β {k} no es negativo; revise respuesta_equilibrio.por_beta.")
                # la pérdida lineal es proporcional a β: con la β del extremo vale simetrica.perdidos × β ÷ β central
                bk = out["convenciones"]["beta"][k]
                poner(pe + f"por_beta.{k}.lineal", (l_m * bk / beta_c - ahorro) * beta_c / g_m, f"{F_REOPT}; {kd}; {F_PLAN}",
                      f"ahorro_operacion_Mcop; simetrica.perdidos_Mcop; simetrica.ganados_Mcop; convenciones.beta.{k}; "
                      "convenciones.beta.central",
                      f"(simetrica.perdidos_Mcop × convenciones.beta.{k} ÷ convenciones.beta.central − ahorro_operacion_Mcop) × "
                      "convenciones.beta.central ÷ simetrica.ganados_Mcop")
                poner(pe + f"por_beta.{k}.mixta", -sk * beta_c / g_m, f"{F_SENS}; {kd}; {F_PLAN}",
                      f"saldo_conservador_por_beta_Mcop.{k}; simetrica.ganados_Mcop; convenciones.beta.central",
                      f"−saldo_conservador_por_beta_Mcop.{k} × convenciones.beta.central ÷ simetrica.ganados_Mcop")
                poner(pe + f"por_beta.{k}.potencia", raiz(sk), f"{F_SENS}; {kd}; {F_PLAN}",
                      f"saldo_conservador_por_beta_Mcop.{k}; {ksube}",
                      f"la r que anula saldo_conservador_por_beta_Mcop.{k} + Σ real × ((x ÷ n_S0)^r − 1) × "
                      "convenciones.tarifa_neta_cop × 1e-06 (bisección)")
            poner(ps + "lineal", sim, F_REOPT, kf + ".neto_simetrico_pago_hora_beta070_Mcop", "= saldo_simetrico_Mcop")
            poner(ps + "mixta", cons + g_m, f"{F_REOPT}; {kd}; {F_PLAN}", "saldo_conservador_Mcop; simetrica.ganados_Mcop",
                  "saldo_conservador_Mcop + simetrica.ganados_Mcop")
            poner(ps + "potencia", cons + ganados_potencia(beta_c), f"{F_REOPT}; {kd}; {F_PLAN}",
                  f"saldo_conservador_Mcop; {ksube}; convenciones.beta.central",
                  "saldo_conservador_Mcop + Σ real × ((x ÷ n_S0)^β central − 1) × convenciones.tarifa_neta_cop × 1e-06")
        else:
            for campo in ("respuesta_equilibrio", "saldo_respuesta_central_Mcop"):
                poner(p + campo, None, "definición", "el saldo conservador no es negativo o el plan no pone salidas")

    # por ruta
    for ruta in RUTAS:
        sub = dec[dec["ruta"] == ruta]
        if sub.empty:
            sys.exit(f"No hay decisiones de la ruta {ruta}.")
        for nombre, (arch, col) in COL_PLAN.items():
            s = _entero(sub[nombre].sum(), f"salidas de {ruta}")
            poner(f"por_ruta.{ruta}.{nombre}.salidas_anio", s, arch, f"[ruta={ruta}]*.{col} → suma")
            poner(f"por_ruta.{ruta}.{nombre}.salidas_dia", s / n_dias, arch, f"[ruta={ruta}]*.{col} → suma",
                  "salidas_anio ÷ convenciones.dias_anio")
    out["por_ruta"] = {"rutas": RUTAS, **out["por_ruta"]}

    # por hora y tipo de día: salidas medias por día de ese tipo (tres rutas sumadas)
    horas = sorted(int(h) for h in dec["hora"].unique())
    presentes = set(dec["tipo_dia"])
    tipos = [t for t in ORDEN_TIPOS if t in presentes] + sorted(presentes - set(ORDEN_TIPOS))
    poner("por_hora.horas", horas, F_DEC_R, "hora → valores distintos")
    for t in tipos:
        sub = dec[dec["tipo_dia"] == t]
        nd = int(sub["dia"].nunique())
        poner(f"por_hora.tipos_dia.{t}.dias", nd, F_DEC_R, f"[tipo_dia={t}]*.dia → n distintos")
        suma = sub.groupby("hora")[list(COL_PLAN)].sum().reindex(horas, fill_value=0)
        for nombre, (arch, col) in COL_PLAN.items():
            poner(f"por_hora.tipos_dia.{t}.{nombre}", (suma[nombre] / nd).tolist(), arch,
                  f"[tipo_dia={t}]*.{col} → suma por hora", "÷ por_hora.tipos_dia.<tipo>.dias")
            poner(f"por_hora.tipos_dia.{t}.salidas_dia.{nombre}", suma[nombre].sum() / nd, arch, f"[tipo_dia={t}]*.{col} → suma",
                  "÷ por_hora.tipos_dia.<tipo>.dias")
        # salidas que cada plan quita y pone en cada hora (por ruta y hora, como quitadas_anio y puestas_anio)
        for nombre in ("reasigna", "recorta"):
            arch, col = COL_PLAN[nombre]
            kq = f"{F_DEC_R} (n_S0)" + ("" if arch == F_DEC_R else f"; {arch} ({col})")
            d_h = sub[nombre] - sub["hoy"]
            qh = (-d_h).clip(lower=0).groupby(sub["hora"]).sum().reindex(horas, fill_value=0) / nd
            ph = d_h.clip(lower=0).groupby(sub["hora"]).sum().reindex(horas, fill_value=0) / nd
            poner(f"por_hora.tipos_dia.{t}.quitadas.{nombre}", qh.tolist(), kq,
                  f"[tipo_dia={t}]*: max(n_S0 − {col}, 0) → suma por hora", "÷ por_hora.tipos_dia.<tipo>.dias")
            poner(f"por_hora.tipos_dia.{t}.puestas.{nombre}", ph.tolist(), kq,
                  f"[tipo_dia={t}]*: max({col} − n_S0, 0) → suma por hora", "÷ por_hora.tipos_dia.<tipo>.dias")
            poner(f"por_hora.tipos_dia.{t}.quitadas_dia.{nombre}", qh.sum(), kq, f"[tipo_dia={t}]*: max(n_S0 − {col}, 0) → suma",
                  "÷ por_hora.tipos_dia.<tipo>.dias")
            poner(f"por_hora.tipos_dia.{t}.puestas_dia.{nombre}", ph.sum(), kq, f"[tipo_dia={t}]*: max({col} − n_S0, 0) → suma",
                  "÷ por_hora.tipos_dia.<tipo>.dias")
    for nombre in ("reasigna", "recorta"):
        for k in ("quitadas", "puestas"):
            tot = sum(sum(out["por_hora"]["tipos_dia"][t][k][nombre]) * out["por_hora"]["tipos_dia"][t]["dias"] for t in tipos)
            _comprobar(f"{nombre}: {k} por hora × días de cada tipo = {k} al año", tot, out["planes"][nombre][f"{k}_anio"])

    # contexto: línea base de costos 2025 y pasajeros de 2025
    lb = _csv_costos(R, F_LB)
    tres = lb[lb["ruta"].isin(RUTAS)]
    if len(tres) != len(RUTAS):
        sys.exit("linea_base_2025.csv no tiene una fila por ruta.")
    kt = "[ruta=SILENCIO|CRA 54|CL 72]*"
    costo = poner("contexto.costo_operacion_anual_Mcop", tres["costo_total"].sum() / 1e6, F_LB, kt + ".costo_total → suma × 1e-06")
    _comprobar("costo anual de las tres rutas = fila Total", costo, _fila(lb, ruta="Total")["costo_total"] / 1e6)
    poner("contexto.costos_fijos_anual_Mcop", tres["fijos"].sum() / 1e6, F_LB, kt + ".fijos → suma × 1e-06")
    poner("contexto.km_anio", tres["km_anual"].sum(), F_LB, kt + ".km_anual → suma")
    poner("contexto.buses_hora_anio", tres["buses_hora_anual"].sum(), F_LB, kt + ".buses_hora_anual → suma")
    out["contexto"]["precios"] = "2025"
    d5j = json.loads((R / F_D5J).read_text(encoding="utf-8"))
    pd25 = poner("contexto.pax_dia_2025", d5j["complemento"]["pasajeros_dia_2025"], F_D5J, "complemento.pasajeros_dia_2025")
    pa25 = poner("contexto.pax_anio_2025", _entero(dec["real"].sum(), "pasajeros"), F_DEC_R, "real → suma")
    _comprobar("pasajeros al año = pasajeros por día × días", pa25, pd25 * n_dias)
    # los costos supuestos con los que D5 eligió el plan que recorta (para decir con qué costos elegía recortar)
    for k, kk in (("costo_bus_hora_cop", "COSTO_BUS_HORA"), ("costo_km_cop", "COSTO_KM"), ("tarifa_cop", "TARIFA")):
        poner(f"convenciones.supuestos_iniciales.{k}", d5j["parametros"][kk], F_D5J, f"parametros.{kk}")

    # lo poco que se sabe de la respuesta a las salidas que se ponen (nunca se ha medido): la literatura que cita el informe
    # de resultados y la asociación entre rutas de 2026 de E8, que es descriptiva y frágil
    q = "pistas_respuesta."
    lit = re.search(PATRON_LITERATURA, (R / F_INFORME).read_text(encoding="utf-8"), re.M)
    if not lit:
        sys.exit(f"No encuentro la fila «Literatura (TCRP Report 95)» en {F_INFORME}.")
    poner(q + "literatura", float(lit.group(1).replace(",", ".")), F_INFORME,
          "Tabla 2 (elasticidad de los pasajeros a las salidas), fila «Literatura (TCRP Report 95)»")
    e8 = json.loads((R / F_E8).read_text(encoding="utf-8"))
    ap, kap = e8["elasticidad_aparente_2026"], "elasticidad_aparente_2026"
    poner(q + "aparente_2026", ap["SILENCIO+CL 72 vs CRA 54"], F_E8, kap + '["SILENCIO+CL 72 vs CRA 54"]')
    poner(q + "aparente_2026_por_ruta.min", min(ap["pendiente_simple_por_ruta"].values()), F_E8,
          kap + ".pendiente_simple_por_ruta → mínimo")
    poner(q + "aparente_2026_por_ruta.max", max(ap["pendiente_simple_por_ruta"].values()), F_E8,
          kap + ".pendiente_simple_por_ruta → máximo")
    poner(q + "aparente_2026_sin_limpiar", e8["verificacion"]["confirmado"]["elasticidad_sin_limpiar_bandas"], F_E8,
          "verificacion.confirmado.elasticidad_sin_limpiar_bandas")
    reservas = [t for t in e8["verificacion"]["correcciones"] if "elasticidad aparente es casi nula" in t]
    if len(reservas) != 1:
        sys.exit(f"No encuentro la reserva de E8 sobre los días especiales en {F_E8} (verificacion.correcciones).")
    poner(q + "reserva_2026", reservas[0], F_E8, "verificacion.correcciones: la que dice «elasticidad aparente es casi nula»")

    # el piloto dicho en saldo: lo que deja si las salidas que se ponen no atraen a nadie, con la pérdida medida (el saldo
    # conservador de P2), con la del extremo alto del rango de β y con la proporcional (β = 1: el tope de la regla de parada
    # 3); y lo que deja si atraen como se midió al quitar (el saldo simétrico de P2)
    p2 = json.loads((R / F_P2).read_text(encoding="utf-8"))
    rc, q = p2["riesgo_costo"], "piloto."
    tot, kp = rc["totales_piloto"], "riesgo_costo.totales_piloto."
    tarifa_p2 = p2["parametros"]["tarifa_neta"]
    _comprobar("la tarifa neta del piloto es la de las convenciones", tarifa_p2, tarifa)
    _comprobar("la β del piloto es la central", p2["parametros"]["beta_e7"], beta_c)
    _comprobar("el extremo alto de β del piloto es el de las convenciones", p2["parametros"]["beta_rango_e7"][1],
               out["convenciones"]["beta"]["alto"])
    recortes = [f for f in rc["por_franja"] if f["rol"] == "recorte"]
    en_riesgo = {"central": (tot["pax_riesgo_piloto_beta070"], kp + "pax_riesgo_piloto_beta070"),
                 "alto": (sum(f["pax_riesgo_dia_beta090"] * f["dias_tratados_piloto"] for f in recortes),
                          "riesgo_costo.por_franja[rol=recorte]: pax_riesgo_dia_beta090 × dias_tratados_piloto → suma"),
                 "tope": (tot["pax_riesgo_piloto_beta100"], kp + "pax_riesgo_piloto_beta100")}
    for k, (pax_k, clave_k) in en_riesgo.items():
        poner(q + f"pax_en_riesgo.{k}", pax_k, F_P2, clave_k)
        poner(q + f"saldo_sin_respuesta_Mcop.{k}",
              tot["ahorro_operativo_recortes_piloto_Mcop"] - pax_k * tarifa_p2 / 1e6 - tot["costo_extra_refuerzos_piloto_Mcop"], F_P2,
              f"{kp}ahorro_operativo_recortes_piloto_Mcop; {clave_k}; parametros.tarifa_neta; {kp}costo_extra_refuerzos_piloto_Mcop",
              "ahorro de los recortes − pasajeros en riesgo × tarifa neta × 1e-06 − costo de los refuerzos")
    _comprobar("piloto: el saldo sin respuesta con la β central es el saldo conservador de P2",
               out["piloto"]["saldo_sin_respuesta_Mcop"]["central"], tot["neto_total_piloto_Mcop_conservador"])
    poner(q + "saldo_respuesta_central_Mcop", tot["neto_total_piloto_Mcop_simetrico"], F_P2, kp + "neto_total_piloto_Mcop_simetrico")

    # palancas que pagan solas (se muestran aparte; no se suman entre sí ni a un plan)
    simf = _csv_costos(R, F_SIM)
    sa = simf[(simf["ruta"] == "Total") & (simf["plan"] == "a")]
    q, kd = "palancas.domingos_festivos.", "[ruta=Total&plan=a&tipo_dia=Domingo/festivo]*"
    dom = sa[sa["tipo_dia"] == "Domingo/festivo"]
    out["palancas"]["domingos_festivos"] = {"plan": "recorta", "tipo_dia": "Domingo/festivo"}
    poner(q + "saldo_conservador_Mcop", dom["neto_hora"].sum() / 1e6, F_SIM, kd + ".neto_hora → suma × 1e-06")
    poner(q + "saldo_por_dia_Mcop", dom["neto_hora"].mean() / 1e6, F_SIM, kd + ".neto_hora → media × 1e-06")
    poner(q + "dias", len(dom), F_SIM, kd + ".fecha → n")
    poner(q + "pax_en_riesgo_dia", dom["pasajeros_en_riesgo"].mean(), F_SIM, kd + ".pasajeros_en_riesgo → media")
    for t in tipos:
        st, kt = sa[sa["tipo_dia"] == t], f"[ruta=Total&plan=a&tipo_dia={t}]*"
        r = q + f"plan_recorta_por_tipo_dia.{t}."
        poner(r + "dias", len(st), F_SIM, kt + ".fecha → n")
        poner(r + "saldo_conservador_Mcop", st["neto_hora"].sum() / 1e6, F_SIM, kt + ".neto_hora → suma × 1e-06")
        poner(r + "pax_en_riesgo_dia", st["pasajeros_en_riesgo"].mean(), F_SIM, kt + ".pasajeros_en_riesgo → media")
    _comprobar("la simulación por fecha (plan a) suma el saldo conservador del plan que recorta", sa["neto_hora"].sum() / 1e6,
               out["planes"]["recorta"]["saldo_conservador_Mcop"])

    aho = _csv_costos(R, F_AHO)
    g, kg, q = _fila(aho, clave="GIRO35"), "[clave=GIRO35]", "palancas.giro_corto_35."
    poner(q + "escenario", g["escenario"], F_AHO, kg + ".escenario")
    poner(q + "delta_km_anio", g["delta_km_anual"], F_AHO, kg + ".delta_km_anual")
    poner(q + "delta_buses_hora_anio", g["delta_buses_hora_anual"], F_AHO, kg + ".delta_buses_hora_anual")
    ah = poner(q + "ahorro_operacion_Mcop", (g["ahorro_por_km"] + g["ahorro_conductor_hora"]) / 1e6, F_AHO,
               kg + ".ahorro_por_km + ahorro_conductor_hora → × 1e-06")
    pp = poner(q + "pasajes_perdidos_Mcop", g["ingreso_perdido"] / 1e6, F_AHO, kg + ".ingreso_perdido × 1e-06")
    sc = poner(q + "saldo_conservador_Mcop", g["neto_pago_por_hora"] / 1e6, F_AHO, kg + ".neto_pago_por_hora × 1e-06")
    _comprobar("giro corto: saldo = ahorro − pasajes perdidos", sc, ah - pp)
    # en ahorros_por_escenario.csv «bajo» es el caso pesimista (β = 0,90) y «alto» el optimista (β = 0,55)
    poner(q + "saldo_rango_Mcop.pesimista", g["neto_pago_por_hora_bajo"] / 1e6, F_AHO, kg + ".neto_pago_por_hora_bajo × 1e-06")
    poner(q + "saldo_rango_Mcop.optimista", g["neto_pago_por_hora_alto"] / 1e6, F_AHO, kg + ".neto_pago_por_hora_alto × 1e-06")
    poner(q + "pax_en_riesgo_dia.central", g["pax_perdidos_dia"], F_AHO, kg + ".pax_perdidos_dia")
    poner(q + "pax_en_riesgo_dia.bajo", g["pax_perdidos_dia_alto"], F_AHO, kg + ".pax_perdidos_dia_alto (β baja: caso optimista)")
    poner(q + "pax_en_riesgo_dia.alto", g["pax_perdidos_dia_bajo"], F_AHO, kg + ".pax_perdidos_dia_bajo (β alta: caso pesimista)")
    poner(q + "espera_hoy_min", g["espera_min_S0"], F_AHO, kg + ".espera_min_S0")
    poner(q + "espera_despues_min", g["espera_min_esc"], F_AHO, kg + ".espera_min_esc")
    poner(q + "valor_social_espera_Mcop", g["valor_social_espera"] / 1e6, F_AHO, kg + ".valor_social_espera × 1e-06")
    bg = _fila(beta, clave="GIRO35")["pago por hora"]
    poner(q + "beta_equilibrio", float(bg), F_BETA, '[clave=GIRO35]["pago por hora"] (mayor que el rango de β: paga con cualquiera)')
    d6 = json.loads((R / F_D6).read_text(encoding="utf-8"))
    fil = [x for x in d6["resumen"] if x["ruta"] == "CRA 54" and x["grupo"] == "principal" and x["politica"] == "S0+G"]
    if len(fil) != 1:
        sys.exit("No encuentro una única fila del giro corto sobre la oferta de hoy en CRA 54 (D6).")
    poner(q + "bajadas_forzadas_dia", fil[0]["bajadas_forzadas"], F_D6,
          "resumen[ruta=CRA 54&grupo=principal&politica=S0+G].bajadas_forzadas")

    rg, kr, q = _fila(aho, clave="REG_CL72"), "[clave=REG_CL72]", "palancas.regularizar_cl72."
    poner(q + "escenario", rg["escenario"], F_AHO, kr + ".escenario")
    poner(q + "espera_hoy_min", rg["espera_min_S0"], F_AHO, kr + ".espera_min_S0")
    poner(q + "espera_despues_min", rg["espera_min_esc"], F_AHO, kr + ".espera_min_esc")
    de = poner(q + "delta_espera_min", rg["delta_espera_min"], F_AHO, kr + ".delta_espera_min")
    _comprobar("regularizar CL 72: cambio de espera = después − hoy", de, rg["espera_min_esc"] - rg["espera_min_S0"])
    poner(q + "delta_km_anio", rg["delta_km_anual"], F_AHO, kr + ".delta_km_anual")
    poner(q + "delta_buses_hora_anio", rg["delta_buses_hora_anual"], F_AHO, kr + ".delta_buses_hora_anual")
    ah = poner(q + "ahorro_operacion_Mcop", (rg["ahorro_por_km"] + rg["ahorro_conductor_hora"]) / 1e6, F_AHO,
               kr + ".ahorro_por_km + ahorro_conductor_hora → × 1e-06")
    pp = poner(q + "pasajes_perdidos_Mcop", rg["ingreso_perdido"] / 1e6, F_AHO, kr + ".ingreso_perdido × 1e-06")
    sc = poner(q + "saldo_conservador_Mcop", rg["neto_pago_por_hora"] / 1e6, F_AHO, kr + ".neto_pago_por_hora × 1e-06")
    _comprobar("regularizar CL 72: saldo = ahorro − pasajes perdidos", sc, ah - pp)
    poner(q + "pax_en_riesgo_dia", rg["pax_perdidos_dia"], F_AHO, kr + ".pax_perdidos_dia")
    poner(q + "valor_social_espera_Mcop", rg["valor_social_espera"] / 1e6, F_AHO, kr + ".valor_social_espera × 1e-06")

    out["campos"] = CAMPOS
    out["origen"] = org
    return out


def solo_ahorro(R):
    """Escribe solo datos/ahorro_anual.json y actualiza su entrada en datos/origen.json (sin tocar las demás)."""
    destino = DESTINO / "ahorro_anual.json"
    destino.write_text(json.dumps(ahorro_anual(R), ensure_ascii=False, indent=1), encoding="utf-8")
    p = DESTINO / "origen.json"
    org = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"generador": "dash_app/preparar_datos.py", "archivos": {}}
    tam = destino.stat().st_size
    org.setdefault("archivos", {})["ahorro_anual.json"] = {"fuentes": FUENTES_AHORRO, "filas": None, "bytes": tam}
    org["generado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    org["total_bytes"] = sum(v["bytes"] for v in org["archivos"].values())
    p.write_text(json.dumps(org, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {'ahorro_anual.json':28s} {tam / 1024:8.1f} KB")


def main():
    a = leer_args()
    R = Path(a.proyecto).resolve()
    if a.solo_despacho:
        if not (R / F_REPLAY / "indice.js").is_file():
            sys.exit(f"No encuentro {F_REPLAY}/indice.js en {R}. Use --proyecto.")
        DESTINO.mkdir(exist_ok=True)
        print(f"Proyecto: {R} (solo Despacho)")
        solo_despacho(R)
        return
    if a.solo_producto:
        DESTINO.mkdir(exist_ok=True)
        print(f"Proyecto: {R} (solo el modelo del producto)")
        solo_producto(R)
        return
    if a.solo_corto_plazo:
        DESTINO.mkdir(exist_ok=True)
        print(f"Proyecto: {R} (solo el pronóstico de corto plazo)")
        solo_corto_plazo(R)
        return
    if a.solo_ahorro:
        if not (R / "experimentos").is_dir():
            sys.exit(f"No encuentro la carpeta del proyecto en {R} (falta experimentos/). Use --proyecto.")
        DESTINO.mkdir(exist_ok=True)
        print(f"Proyecto: {R} (solo el ahorro anual)")
        solo_ahorro(R)
        return
    if not (R / "experimentos").is_dir():
        sys.exit(f"No encuentro la carpeta del proyecto en {R} (falta experimentos/). Use --proyecto.")
    DESTINO.mkdir(exist_ok=True)
    origen = {}

    def anotar(nombre, fuentes, filas=None):
        p = DESTINO / nombre
        origen[nombre] = {"fuentes": fuentes, "filas": filas, "bytes": p.stat().st_size}
        print(f"  {nombre:28s} {p.stat().st_size / 1024:8.1f} KB" + (f"  {filas} filas" if filas else ""))

    print(f"Proyecto: {R}")
    p = pronosticos(R)
    p.to_parquet(DESTINO / "pronosticos_2025.parquet", index=False, compression="zstd")
    anotar("pronosticos_2025.parquet", ["experimentos/E11_modelo_mejorado/predicciones_2025.parquet",
                                        "experimentos/E1_lgbm_salida/predicciones_2025.parquet",
                                        "experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet"], len(p))
    d = insumos_d5(R)
    d.to_parquet(DESTINO / "insumos_d5_2025.parquet", index=False, compression="zstd")
    anotar("insumos_d5_2025.parquet", ["experimentos/D5_optimizacion_milp/decisiones_2025.parquet",
                                       "experimentos/E1_lgbm_salida/predicciones_2025.parquet",
                                       "experimentos/D1_optimizacion/parametros_operativos.parquet",
                                       "costos/resultados/d5_reoptimizado_decisiones.parquet"], len(d))
    (DESTINO / "costos_fuente.json").write_text(json.dumps(costos(R), ensure_ascii=False, indent=1), encoding="utf-8")
    anotar("costos_fuente.json", ["costos/resultados/costos_unitarios.json", "costos/resultados/costos_para_planificador.json"])
    (DESTINO / "cifras_app.json").write_text(json.dumps(datos_app(R), ensure_ascii=False), encoding="utf-8")
    anotar("cifras_app.json", ["app/datos_app.js (window.DATOS_APP, generado por app/generar_datos_app.py)"])
    for rel, nombre in [("app/ficha_modelos.json", "ficha_modelos.json"),
                        ("simulacion_ahorro/resultados/sensibilidad_beta.csv", "sensibilidad_beta.csv"),
                        ("costos/resultados/beta_equilibrio.csv", "beta_equilibrio.csv")]:
        shutil.copyfile(R / rel, DESTINO / nombre)
        anotar(nombre, [rel])
    (DESTINO / "ahorro_anual.json").write_text(json.dumps(ahorro_anual(R), ensure_ascii=False, indent=1), encoding="utf-8")
    anotar("ahorro_anual.json", FUENTES_AHORRO)
    (DESTINO / "modelo_producto.json").write_text(json.dumps(modelo_producto(R), ensure_ascii=False, indent=1), encoding="utf-8")
    anotar("modelo_producto.json", [F_REG, F_EVAL, F_CAL])
    (DESTINO / "corto_plazo.json").write_text(json.dumps(corto_plazo(R), ensure_ascii=False, indent=1), encoding="utf-8")
    anotar("corto_plazo.json", FUENTES_CP)
    if (R / F_REPLAY / "indice.js").is_file():
        for nombre, fuentes in despacho(R):
            anotar(nombre, fuentes)
    else:
        print(f"  (sin {F_REPLAY}: la pantalla Despacho usará los días que ya estén en datos/despacho/)")
    n = iconos(R)
    print(f"  {n} íconos en assets/iconos/ (de app/iconos.js)")
    total = sum(v["bytes"] for v in origen.values())
    (DESTINO / "origen.json").write_text(json.dumps({"generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                     "generador": "dash_app/preparar_datos.py", "archivos": origen,
                                                     "total_bytes": total}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Total: {total / 1024 / 1024:.2f} MB en {DESTINO}")


if __name__ == "__main__":
    main()
