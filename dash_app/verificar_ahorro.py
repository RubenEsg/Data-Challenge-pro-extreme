"""Verifica datos/ahorro_anual.json (lo escribe preparar_datos.py) sin usar el código que lo genera.

1. Identidades dentro del archivo: saldos, pasajes, salidas, sumas por ruta y por hora, palancas.
2. Recalcula con código propio, desde los archivos de resultados del proyecto, cada cifra que el archivo toma o deriva
   (las salidas hora por hora de los parquets de decisiones, los pasajeros en riesgo con la fórmula de la fuente, las filas
   de los CSV de costos/, D5, simulacion_ahorro/ y D6).
3. Compara con el inventario verificado app/DATOS.md: lee los valores de su tabla (aquí no hay cifras escritas a mano) y
   tolera medio dígito del último decimal que muestra. También con datos/cifras_app.json, el mismo inventario con más campos.
4. Busca en documentos/informe_resultados.md las cifras que cita, redondeadas como las cita.
5. Comprueba que las lecturas que la pantalla debe respetar siguen siendo ciertas con estos datos.
6. Cada cifra tiene su origen y los archivos de origen existen.

Uso (desde la carpeta dash_app):
    .venv/Scripts/python.exe verificar_ahorro.py                      # el proyecto está dos carpetas arriba
    .venv/Scripts/python.exe verificar_ahorro.py --proyecto "D:/ruta/al/proyecto"
Imprime OK o FALLA por comprobación y sale con código 1 si alguna falla.
"""
import argparse
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
ARCHIVO = AQUI / "datos" / "ahorro_anual.json"
CIFRAS = AQUI / "datos" / "cifras_app.json"
RUTAS = ["SILENCIO", "CRA 54", "CL 72"]
PLANES = ["hoy", "reasigna", "recorta"]
CUENTA = {"ok": 0, "falla": 0}


# ----------------------------------------------------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------------------------------------------------
def _det(x):
    return f"{x:.10g}" if isinstance(x, (int, float, np.floating, np.integer)) and not isinstance(x, bool) else repr(x)


def informar(nombre, ok, detalle=""):
    CUENTA["ok" if ok else "falla"] += 1
    print(f"{'OK   ' if ok else 'FALLA'}  {nombre}" + (f"  [{detalle}]" if detalle else ""))


def igual(nombre, a, b, rel=1e-9, abs_=1e-9):
    """a (del archivo) frente a b (recalculado o leído de la fuente)."""
    try:
        ok = a is not None and b is not None and abs(float(a) - float(b)) <= max(abs_, rel * abs(float(b)))
    except (TypeError, ValueError):
        ok = False
    informar(nombre, ok, f"{_det(a)} frente a {_det(b)}")


def val(J, ruta):
    """Valor del archivo en la ruta 'a.b.c' (las claves no llevan puntos)."""
    d = J
    for p in ruta.split("."):
        d = d[p]
    return d


def es(x, dec=0, modo=None):
    """Número como lo escribe el informe: 1.234,5; negativos con «−»; modo 'signo' antepone '+'; 'abs' quita el signo;
    'millones' divide entre 1e6; dec < 0 redondea a decenas, centenas..."""
    x = float(x)
    if modo == "abs":
        x = abs(x)
    if modo == "millones":
        x /= 1e6
    if dec < 0:
        x, dec = float(Decimal(str(x)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)), 0
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
    ent, _, frac = f"{abs(q):f}".partition(".")
    s = f"{int(ent):,}".replace(",", ".") + ("," + frac if dec > 0 else "")
    if q < 0:
        return "−" + s
    return ("+" + s) if (modo == "signo" and q > 0) else s


def num_es(s):
    """'1.731,69' → (1731.69, 2); '-2.825,13' → (−2825.13, 2). Devuelve el valor y los decimales que muestra."""
    s = s.strip().replace("−", "-")
    m = re.fullmatch(r"(-?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?", s)
    if not m:
        raise ValueError(f"no es un número en formato español: {s!r}")
    frac = m.group(3) or ""
    return float(f"{m.group(1)}{m.group(2).replace('.', '')}.{frac or '0'}"), len(frac)


def dict_es(s):
    """'{hoy: 11,6709; plan: 6,795}' → {'hoy': (11.6709, 4), 'plan': (6.795, 3)}."""
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        raise ValueError(f"no es un objeto: {s!r}")
    out = {}
    for par in s[1:-1].split(";"):
        k, _, v = par.partition(":")
        out[k.strip()] = num_es(v)
    return out


def tabla_datos_md(texto):
    """Filas de las tablas de app/DATOS.md: id → texto de la columna «valor»."""
    filas = {}
    for linea in texto.splitlines():
        if not linea.startswith("| `"):
            continue
        partes = [p.strip() for p in re.split(r"(?<!\\)\|", linea.strip())[1:-1]]
        if len(partes) >= 8:
            filas[partes[0].strip("`")] = partes[2]
    return filas


def tol_6cs(x):
    """Medio dígito de la última cifra guardada en cifras_app.json (2 decimales desde 1.000, 6 cifras significativas abajo)."""
    x = abs(float(x))
    if x >= 1000:
        return 0.005 + 1e-9
    if x == 0:
        return 1e-12
    return 0.5 * 10 ** (np.floor(np.log10(x)) - 5) + 1e-12


def csv_costos(R, rel):
    return pd.read_csv(R / rel, sep=";", decimal=",", encoding="utf-8-sig")


def una(df, **filtro):
    m = np.ones(len(df), dtype=bool)
    for c, v in filtro.items():
        m &= (df[c] == v).to_numpy()
    if m.sum() != 1:
        raise SystemExit(f"FALLA  se esperaba una fila con {filtro} y hay {int(m.sum())}")
    return df[m].iloc[0]


# ----------------------------------------------------------------------------------------------------------------------
# 1. Identidades dentro del archivo
# ----------------------------------------------------------------------------------------------------------------------
def identidades(J):
    print("\n1. Identidades dentro de ahorro_anual.json")
    c, P = J["convenciones"], J["planes"]
    n, t = c["dias_anio"], c["tarifa_neta_cop"]
    h = P["hoy"]
    ceros = ["quitadas_dia", "puestas_dia", "quitadas_anio", "puestas_anio", "menos_salidas_dia", "menos_salidas_anio",
             "var_salidas_pct", "var_buses_hora_pct", "var_km_pct", "delta_buses_hora_anio", "delta_km_anio", "ahorro_km_Mcop",
             "ahorro_conductor_Mcop", "ahorro_operacion_Mcop", "pax_netos_dia_simetrico", "pasajes_perdidos_Mcop",
             "pasajes_ganados_Mcop", "saldo_conservador_Mcop", "saldo_simetrico_Mcop", "ahorro_pct_costo", "dif_regla_perdidos_Mcop"]
    informar("hoy: todo lo que se mide frente a hoy vale cero",
             all(h[k] == 0 for k in ceros) and all(v == 0 for v in h["pax_en_riesgo_dia"].values())
             and all(v == 0 for v in h["simetrica"].values()))
    igual("hoy: salidas al año = salidas por día × días", h["salidas_anio"], h["salidas_dia"] * n)
    igual("hoy: buses-hora al año = por día × días", h["buses_hora_anio"], h["buses_hora_dia"] * n)
    igual("hoy: km al año = por día × días", h["km_anio"], h["km_dia"] * n)
    igual("hoy: costo de km y conductor = km × costo por km + buses-hora × costo por bus-hora", h["costo_km_conductor_Mcop"],
          (h["km_anio"] * c["costo_km_cop"] + h["buses_hora_anio"] * c["costo_bus_hora_cop"]) / 1e6)
    for nom in ("reasigna", "recorta"):
        p = P[nom]
        s = p["simetrica"]
        igual(f"{nom}: saldo conservador = ahorro en operación − pasajes perdidos", p["saldo_conservador_Mcop"],
              p["ahorro_operacion_Mcop"] - p["pasajes_perdidos_Mcop"], abs_=1e-6)
        igual(f"{nom}: saldo simétrico = saldo conservador + pasajes ganados", p["saldo_simetrico_Mcop"],
              p["saldo_conservador_Mcop"] + p["pasajes_ganados_Mcop"], abs_=1e-6)
        igual(f"{nom}: saldo simétrico = ahorro + ganados − perdidos (desglose simétrico)", p["saldo_simetrico_Mcop"],
              p["ahorro_operacion_Mcop"] + s["ganados_Mcop"] - s["perdidos_Mcop"], abs_=1e-6)
        igual(f"{nom}: pasajes perdidos = pax en riesgo (central) × días × tarifa ÷ 1e6", p["pasajes_perdidos_Mcop"],
              p["pax_en_riesgo_dia"]["central"] * n * t / 1e6)
        igual(f"{nom}: pasajes ganados = (pax netos simétricos + pax en riesgo) × días × tarifa ÷ 1e6",
              p["pasajes_ganados_Mcop"], (p["pax_netos_dia_simetrico"] + p["pax_en_riesgo_dia"]["central"]) * n * t / 1e6)
        igual(f"{nom}: ganados − perdidos de la simétrica = pax netos", s["pax_ganados_dia"] - s["pax_perdidos_dia"],
              p["pax_netos_dia_simetrico"])
        igual(f"{nom}: ganados (M COP) = pax ganados × días × tarifa ÷ 1e6", s["ganados_Mcop"], s["pax_ganados_dia"] * n * t / 1e6)
        igual(f"{nom}: perdidos (M COP) = pax perdidos × días × tarifa ÷ 1e6", s["perdidos_Mcop"], s["pax_perdidos_dia"] * n * t / 1e6)
        igual(f"{nom}: ahorro en operación = km + conductor", p["ahorro_operacion_Mcop"], p["ahorro_km_Mcop"] + p["ahorro_conductor_Mcop"])
        igual(f"{nom}: ahorro en km = km al año × costo por km ÷ 1e6", p["ahorro_km_Mcop"], p["delta_km_anio"] * c["costo_km_cop"] / 1e6)
        igual(f"{nom}: ahorro en conductor = buses-hora al año × costo por bus-hora ÷ 1e6", p["ahorro_conductor_Mcop"],
              p["delta_buses_hora_anio"] * c["costo_bus_hora_cop"] / 1e6)
        igual(f"{nom}: salidas al año = salidas por día × días", p["salidas_anio"], p["salidas_dia"] * n)
        igual(f"{nom}: salidas de menos = quitadas − puestas", p["menos_salidas_anio"], p["quitadas_anio"] - p["puestas_anio"])
        igual(f"{nom}: salidas de menos = salidas de hoy − salidas del plan", p["menos_salidas_anio"], h["salidas_anio"] - p["salidas_anio"])
        igual(f"{nom}: quitadas por día × días = quitadas al año", p["quitadas_dia"] * n, p["quitadas_anio"])
        igual(f"{nom}: puestas por día × días = puestas al año", p["puestas_dia"] * n, p["puestas_anio"])
        igual(f"{nom}: salidas de menos por día × días = al año", p["menos_salidas_dia"] * n, p["menos_salidas_anio"])
        igual(f"{nom}: buses-hora al año = (hoy − plan) × días", p["delta_buses_hora_anio"], (h["buses_hora_dia"] - p["buses_hora_dia"]) * n)
        igual(f"{nom}: % de salidas frente a hoy", p["var_salidas_pct"], (p["salidas_dia"] / h["salidas_dia"] - 1) * 100)
        igual(f"{nom}: % de buses-hora frente a hoy", p["var_buses_hora_pct"], (p["buses_hora_dia"] / h["buses_hora_dia"] - 1) * 100)
        igual(f"{nom}: % de km frente a hoy", p["var_km_pct"], -p["delta_km_anio"] / (h["km_dia"] * n) * 100)
        r = p["pax_en_riesgo_dia"]
        informar(f"{nom}: pax en riesgo bajo ≤ central ≤ alto", r["bajo"] <= r["central"] <= r["alto"],
                 f"{_det(r['bajo'])} ≤ {_det(r['central'])} ≤ {_det(r['alto'])}")
        sb = p["saldo_conservador_por_beta_Mcop"]
        igual(f"{nom}: saldo con β central = saldo conservador", sb["central"], p["saldo_conservador_Mcop"], abs_=1e-6)
        for k in ("bajo", "alto"):
            igual(f"{nom}: saldo con β {k} = ahorro − pax en riesgo {k} × días × tarifa ÷ 1e6", sb[k],
                  p["ahorro_operacion_Mcop"] - r[k] * n * t / 1e6, abs_=1e-6)
        igual(f"{nom}: buses-hora al año = por día × días", p["buses_hora_anio"], p["buses_hora_dia"] * n)
        igual(f"{nom}: km al año = km de hoy − km que deja de recorrer", p["km_anio"], h["km_anio"] - p["delta_km_anio"])
        igual(f"{nom}: costo de km y conductor = km × costo por km + buses-hora × costo por bus-hora", p["costo_km_conductor_Mcop"],
              (p["km_anio"] * c["costo_km_cop"] + p["buses_hora_anio"] * c["costo_bus_hora_cop"]) / 1e6)
        igual(f"{nom}: costo de km y conductor = el de hoy − ahorro en operación", p["costo_km_conductor_Mcop"],
              h["costo_km_conductor_Mcop"] - p["ahorro_operacion_Mcop"], abs_=1e-6)
        igual(f"{nom}: % de ahorro sobre lo que hoy cuestan los km y el conductor", p["ahorro_pct_costo"],
              p["ahorro_operacion_Mcop"] / h["costo_km_conductor_Mcop"] * 100)
        igual(f"{nom}: diferencia de regla = perdidos (conservadora) − perdidos (simétrica)", p["dif_regla_perdidos_Mcop"],
              p["pasajes_perdidos_Mcop"] - s["perdidos_Mcop"], abs_=1e-6)
        igual(f"{nom}: saldo simétrico = saldo conservador + ganados (simétrica) + diferencia de regla", p["saldo_simetrico_Mcop"],
              p["saldo_conservador_Mcop"] + s["ganados_Mcop"] + p["dif_regla_perdidos_Mcop"], abs_=1e-6)
    for nom in PLANES:
        igual(f"por ruta: las tres rutas suman las salidas al año de {nom}",
              sum(J["por_ruta"][r][nom]["salidas_anio"] for r in RUTAS), P[nom]["salidas_anio"])
        igual(f"por ruta: las tres rutas suman las salidas por día de {nom}",
              sum(J["por_ruta"][r][nom]["salidas_dia"] for r in RUTAS), P[nom]["salidas_dia"])
        tot = sum(sum(td[nom]) * td["dias"] for td in J["por_hora"]["tipos_dia"].values())
        igual(f"por hora: medias × días de cada tipo suman las salidas al año de {nom}", tot, P[nom]["salidas_anio"])
    informar("por hora: los tipos de día suman los días del año",
             sum(td["dias"] for td in J["por_hora"]["tipos_dia"].values()) == n)
    informar("por hora: una media por hora en cada serie", all(len(td[nom]) == len(J["por_hora"]["horas"])
                                                               for td in J["por_hora"]["tipos_dia"].values() for nom in PLANES))
    for nom in ("reasigna", "recorta"):
        for k in ("quitadas", "puestas"):
            tot = sum(sum(td[k][nom]) * td["dias"] for td in J["por_hora"]["tipos_dia"].values())
            igual(f"por hora: {k} por hora × días de cada tipo = {k} al año de {nom}", tot, P[nom][f"{k}_anio"], abs_=1e-6)
        informar(f"por hora: totales del día de cada tipo = suma de su serie ({nom})",
                 all(abs(td["salidas_dia"][nom] - sum(td[nom])) < 1e-9 and abs(td["quitadas_dia"][nom] - sum(td["quitadas"][nom])) < 1e-9
                     and abs(td["puestas_dia"][nom] - sum(td["puestas"][nom])) < 1e-9
                     and abs(td["salidas_dia"]["hoy"] - sum(td["hoy"])) < 1e-9 for td in J["por_hora"]["tipos_dia"].values()))
        informar(f"por hora: plan − hoy = puestas − quitadas en cada hora y tipo de día ({nom})",
                 all(abs((td[nom][i] - td["hoy"][i]) - (td["puestas"][nom][i] - td["quitadas"][nom][i])) < 1e-9
                     and td["puestas"][nom][i] >= 0 and td["quitadas"][nom][i] >= 0
                     for td in J["por_hora"]["tipos_dia"].values() for i in range(len(J["por_hora"]["horas"]))))
    d = J["palancas"]["domingos_festivos"]
    ptd = d["plan_recorta_por_tipo_dia"]
    igual("domingos: la palanca es el tramo Domingo/festivo del plan que recorta", d["saldo_conservador_Mcop"],
          ptd["Domingo/festivo"]["saldo_conservador_Mcop"])
    igual("domingos: saldo por día × días = saldo del año", d["saldo_por_dia_Mcop"] * d["dias"], d["saldo_conservador_Mcop"])
    igual("domingos: los tipos de día del plan que recorta suman su saldo anual",
          sum(x["saldo_conservador_Mcop"] for x in ptd.values()), P["recorta"]["saldo_conservador_Mcop"], abs_=1e-6)
    informar("domingos: los tipos de día suman los días del año", sum(x["dias"] for x in ptd.values()) == n)
    for k in ("giro_corto_35", "regularizar_cl72"):
        g = J["palancas"][k]
        igual(f"{k}: saldo = ahorro en operación − pasajes perdidos", g["saldo_conservador_Mcop"],
              g["ahorro_operacion_Mcop"] - g["pasajes_perdidos_Mcop"], abs_=1e-6)
    g = J["palancas"]["regularizar_cl72"]
    igual("regularizar CL 72: cambio de espera = después − hoy", g["delta_espera_min"], g["espera_despues_min"] - g["espera_hoy_min"])
    igual("contexto: pasajeros al año = pasajeros por día × días", J["contexto"]["pax_anio_2025"], J["contexto"]["pax_dia_2025"] * n)


# ----------------------------------------------------------------------------------------------------------------------
# 2. Recalcular desde los archivos del proyecto
# ----------------------------------------------------------------------------------------------------------------------
def fuentes(J, R):
    print("\n2. Recalculado desde los archivos de resultados del proyecto")
    P, c = J["planes"], J["convenciones"]
    pl = json.loads((R / "costos/resultados/costos_para_planificador.json").read_text(encoding="utf-8"))
    un = json.loads((R / "costos/resultados/costos_unitarios.json").read_text(encoding="utf-8"))
    igual("tarifa neta = costos_para_planificador (central)", c["tarifa_neta_cop"], pl["tarifa_neta_2026"]["central"])
    igual("tarifa neta = la que usó costos/reoptimizar_d5.py (costos_unitarios 2026)", c["tarifa_neta_cop"], un["2026"]["tarifa_efectiva"])
    igual("costo por km = costo evitable 2026", c["costo_km_cop"], un["2026"]["costo_km_evitable"])
    igual("costo por bus-hora = conductor por hora 2026", c["costo_bus_hora_cop"], un["2026"]["bus_hora_conductor"])
    for k in ("central", "bajo", "alto"):
        igual(f"β {k} = costos_para_planificador", c["beta"][k], pl["elasticidad_beta"][k])
    d5j = json.loads((R / "experimentos/D5_optimizacion_milp/resultados.json").read_text(encoding="utf-8"))
    for k, kk in (("costo_bus_hora_cop", "COSTO_BUS_HORA"), ("costo_km_cop", "COSTO_KM"), ("tarifa_cop", "TARIFA")):
        igual(f"supuestos iniciales de D5: {kk} = resultados.json parametros", c["supuestos_iniciales"][k], d5j["parametros"][kk])

    # decisiones hora por hora
    a = pd.read_parquet(R / "costos/resultados/d5_reoptimizado_decisiones.parquet")
    b = pd.read_parquet(R / "experimentos/D5_optimizacion_milp/decisiones_2025.parquet",
                        columns=["ruta", "dia", "hora", "tipo_dia", "real", "n_S0", "x_D5"])
    a["dia"], b["dia"] = pd.to_datetime(a["dia"]), pd.to_datetime(b["dia"])
    m = a.merge(b, on=["ruta", "dia", "hora"], suffixes=("", "_b"))
    informar("decisiones: los dos parquets tienen las mismas filas", len(m) == len(a) == len(b), f"{len(m)}, {len(a)}, {len(b)}")
    informar("decisiones: mismo n_S0, mismos pasajeros y mismo tipo de día en los dos",
             bool((m["n_S0"] == m["n_S0_b"]).all() and np.allclose(m["real"], m["real_b"]) and (m["tipo_dia"] == m["tipo_dia_b"]).all()))
    informar("decisiones: x_corrida_0 (D5 original en costos/) = x_D5 de D5 en todas las horas", bool((m["x_corrida_0"] == m["x_D5"]).all()))
    n = m["dia"].nunique()
    igual("días del año", c["dias_anio"], n)
    col = {"hoy": "n_S0", "reasigna": "x_corrida_1", "recorta": "x_D5"}
    n0, pax = m["n_S0"].to_numpy(float), m["real"].to_numpy(float)
    for nom, cx in col.items():
        x = m[cx].to_numpy(float)
        igual(f"{nom}: salidas al año ({cx} → suma)", P[nom]["salidas_anio"], x.sum())
        if nom != "hoy":
            igual(f"{nom}: quitadas al año (max(n_S0 − {cx}, 0))", P[nom]["quitadas_anio"], np.maximum(n0 - x, 0).sum())
            igual(f"{nom}: puestas al año (max({cx} − n_S0, 0))", P[nom]["puestas_anio"], np.maximum(x - n0, 0).sum())
            ratio = np.divide(x, n0, out=np.ones_like(x), where=n0 > 0)
            for k in ("bajo", "central", "alto"):
                bta = pl["elasticidad_beta"][k]
                perd = np.where((n0 > 0) & (x < n0), pax * (1 - np.clip(ratio, 0, 1) ** bta), 0.0).sum() / n
                igual(f"{nom}: pax en riesgo {k} con pax × (1 − (x/n0)^β), β = {bta}", P[nom]["pax_en_riesgo_dia"][k], perd)
            dp = np.where(n0 > 0, pax * pl["elasticidad_beta"]["central"] * (x - n0) / np.where(n0 > 0, n0, 1), 0.0)
            igual(f"{nom}: pax netos simétricos con pax × β × (x − n0)/n0", P[nom]["pax_netos_dia_simetrico"], dp.sum() / n)
            igual(f"{nom}: pax ganados (simétrica)", P[nom]["simetrica"]["pax_ganados_dia"], dp[dp > 0].sum() / n)
            igual(f"{nom}: pax perdidos (simétrica, lineal)", P[nom]["simetrica"]["pax_perdidos_dia"], -dp[dp < 0].sum() / n)
        for r in RUTAS:
            igual(f"{nom}: salidas al año de {r}", J["por_ruta"][r][nom]["salidas_anio"], m.loc[m["ruta"] == r, cx].sum())
        for tdia, td in J["por_hora"]["tipos_dia"].items():
            sub = m[m["tipo_dia"] == tdia]
            nd = sub["dia"].nunique()
            serie = sub.groupby("hora")[cx].sum().reindex(J["por_hora"]["horas"], fill_value=0) / nd
            informar(f"{nom}: salidas medias por hora, {tdia} ({nd} días)",
                     td["dias"] == nd and np.allclose(td[nom], serie.to_numpy(), rtol=1e-12, atol=1e-12))
            if nom != "hoy":
                dd = (sub[cx] - sub["n_S0"]).astype(float)
                qs = (-dd).clip(lower=0).groupby(sub["hora"]).sum().reindex(J["por_hora"]["horas"], fill_value=0) / nd
                ps = dd.clip(lower=0).groupby(sub["hora"]).sum().reindex(J["por_hora"]["horas"], fill_value=0) / nd
                informar(f"{nom}: salidas quitadas y puestas por hora (por ruta y hora), {tdia}",
                         np.allclose(td["quitadas"][nom], qs.to_numpy(), rtol=1e-12, atol=1e-12)
                         and np.allclose(td["puestas"][nom], ps.to_numpy(), rtol=1e-12, atol=1e-12))
    igual("contexto: pasajeros al año (real → suma)", J["contexto"]["pax_anio_2025"], m["real"].sum())

    # filas de los CSV
    reopt = csv_costos(R, "costos/resultados/d5_reoptimizado.csv")
    corr = {"reasigna": "D5 costos nuevos, pago por hora, e=0,5", "recorta": "D5 original (60.000/1.500/3.000, e=0,5)"}
    campos = {"salidas_dia": "salidas_dia", "buses_hora_dia": "buses_hora_dia", "delta_buses_hora_anio": "delta_buses_hora_anual",
              "delta_km_anio": "delta_km_anual", "espera_min": "espera_media_min", "pax_sobre_capacidad_dia": "pax_sobre_capacidad_dia",
              "pct_horas_fc_mayor_1": "pct_horas_fc_mayor_1", "ahorro_operacion_Mcop": "ahorro_operativo_pago_hora_Mcop",
              "saldo_conservador_Mcop": "neto_pago_hora_beta070_Mcop", "saldo_simetrico_Mcop": "neto_simetrico_pago_hora_beta070_Mcop",
              "pax_netos_dia_simetrico": "pax_netos_dia_simetrico_beta070"}
    for nom, cr in corr.items():
        f = una(reopt, corrida=cr)
        for k, cc in campos.items():
            igual(f"{nom}: {k} = d5_reoptimizado.csv [{cr}].{cc}", P[nom][k], f[cc])
        for k in ("bajo", "central", "alto"):
            igual(f"{nom}: pax en riesgo {k} = d5_reoptimizado.csv .pax_perdidos_dia_{k}", P[nom]["pax_en_riesgo_dia"][k], f[f"pax_perdidos_dia_{k}"])
        igual(f"{nom}: costo por km usado en la corrida", c["costo_km_cop"], f["costo_km_usado"])
        igual(f"{nom}: costo por bus-hora usado en la corrida", c["costo_bus_hora_cop"], f["costo_bus_hora_usado"])
    esc = pd.read_csv(R / "experimentos/D5_optimizacion_milp/escenarios.csv", encoding="utf-8-sig")
    s0 = una(esc, ruta="Todas", tipo_dia="Todos", escenario="S0 oferta real")
    d5 = una(esc, ruta="Todas", tipo_dia="Todos", escenario="D5 MILP (pronóstico)")
    for k, cc in [("salidas_dia", "salidas_dia"), ("buses_hora_dia", "buses_hora_dia"), ("km_dia", "km_dia"),
                  ("espera_min", "espera_media_min"), ("pax_sobre_capacidad_dia", "pax_sobre_capacidad_dia"),
                  ("pct_horas_fc_mayor_1", "pct_horas_fc_mayor_1")]:
        igual(f"hoy: {k} = escenarios.csv [S0 oferta real].{cc}", P["hoy"][k], s0[cc])
        if k != "km_dia":
            igual(f"recorta: {k} = escenarios.csv [D5 MILP (pronóstico)].{cc}", P["recorta"][k], d5[cc])
    igual("recorta: km al año = escenarios.csv [D5 MILP (pronóstico)].km_ahorrados_anual", P["recorta"]["delta_km_anio"], d5["km_ahorrados_anual"])
    igual("recorta: buses-hora al año = escenarios.csv .buses_hora_ahorrados_anual", P["recorta"]["delta_buses_hora_anio"],
          d5["buses_hora_ahorrados_anual"])
    aho = csv_costos(R, "costos/resultados/ahorros_por_escenario.csv")
    f = una(aho, clave="D5")
    r = P["recorta"]
    igual("recorta: saldo = ahorros_por_escenario [D5].neto_pago_por_hora × 1e-6", r["saldo_conservador_Mcop"], f["neto_pago_por_hora"] / 1e6)
    igual("recorta: pasajes perdidos = [D5].ingreso_perdido × 1e-6", r["pasajes_perdidos_Mcop"], f["ingreso_perdido"] / 1e6)
    igual("recorta: ahorro en km = [D5].ahorro_por_km × 1e-6", r["ahorro_km_Mcop"], f["ahorro_por_km"] / 1e6)
    igual("recorta: ahorro en conductor = [D5].ahorro_conductor_hora × 1e-6", r["ahorro_conductor_Mcop"], f["ahorro_conductor_hora"] / 1e6)
    igual("recorta: pax en riesgo = [D5].pax_perdidos_dia", r["pax_en_riesgo_dia"]["central"], f["pax_perdidos_dia"])
    igual("recorta: pax netos simétricos = [D5].pax_netos_dia_simetrico", r["pax_netos_dia_simetrico"], f["pax_netos_dia_simetrico"])
    igual("recorta: saldo simétrico = [D5].neto_simetrico_pago_por_hora × 1e-6", r["saldo_simetrico_Mcop"], f["neto_simetrico_pago_por_hora"] / 1e6)
    igual("recorta: β de equilibrio = [D5].beta_equilibrio_pago_por_hora", r["beta_equilibrio"], float(f["beta_equilibrio_pago_por_hora"]))
    beta = csv_costos(R, "costos/resultados/beta_equilibrio.csv")
    igual('recorta: β de equilibrio = beta_equilibrio.csv [D5]["pago por hora"]', r["beta_equilibrio"], float(una(beta, clave="D5")["pago por hora"]))
    sens = csv_costos(R, "simulacion_ahorro/resultados/sensibilidad_beta.csv")
    for nom, letra in (("reasigna", "b"), ("recorta", "a")):
        for k in ("bajo", "central", "alto"):
            fb = sens[(sens["plan"] == letra) & np.isclose(sens["beta"], c["beta"][k])]
            informar(f"{nom}: una fila de sensibilidad_beta.csv con β {k}", len(fb) == 1)
            if len(fb) == 1:
                igual(f"{nom}: saldo con β {k} = sensibilidad_beta.csv [plan={letra}].neto_hora_Mcop",
                      P[nom]["saldo_conservador_por_beta_Mcop"][k], fb["neto_hora_Mcop"].iloc[0])
                igual(f"{nom}: pax en riesgo con β {k} = sensibilidad_beta.csv .pasajeros_en_riesgo_dia",
                      P[nom]["pax_en_riesgo_dia"][k], fb["pasajeros_en_riesgo_dia"].iloc[0])
    # ahorros_por_escenario.csv interpola la pérdida en β (L(β) = A·(1 − c^β)); d5_reoptimizado.csv la calcula hora por hora
    for kj, ka in (("bajo", "pax_perdidos_dia_alto"), ("alto", "pax_perdidos_dia_bajo")):
        d = abs(r["pax_en_riesgo_dia"][kj] - f[ka]) / f[ka] * 100
        print(f"AVISO  recorta: pax en riesgo {kj} {_det(r['pax_en_riesgo_dia'][kj])} (d5_reoptimizado.csv) frente a "
              f"{_det(f[ka])} ([D5].{ka}, interpolado): {d:.3f} %")

    sim = csv_costos(R, "simulacion_ahorro/resultados/simulacion_por_fecha.csv")
    tot = sim[sim["ruta"] == "Total"]
    igual("simulación por fecha: el plan (a) suma el saldo del plan que recorta", tot.loc[tot["plan"] == "a", "neto_hora"].sum() / 1e6,
          r["saldo_conservador_Mcop"], abs_=1e-6)
    igual("simulación por fecha: el plan (b) suma el saldo del plan que reasigna", tot.loc[tot["plan"] == "b", "neto_hora"].sum() / 1e6,
          P["reasigna"]["saldo_conservador_Mcop"], abs_=1e-6)
    dom = tot[(tot["plan"] == "a") & (tot["tipo_dia"] == "Domingo/festivo")]
    d = J["palancas"]["domingos_festivos"]
    igual("domingos: saldo (neto_hora → suma × 1e-6)", d["saldo_conservador_Mcop"], dom["neto_hora"].sum() / 1e6)
    igual("domingos: saldo por día (neto_hora → media × 1e-6)", d["saldo_por_dia_Mcop"], dom["neto_hora"].mean() / 1e6)
    igual("domingos: días (fecha → n)", d["dias"], dom["fecha"].nunique())
    igual("domingos: pax en riesgo por día (pasajeros_en_riesgo → media)", d["pax_en_riesgo_dia"], dom["pasajeros_en_riesgo"].mean())
    for tdia, x in d["plan_recorta_por_tipo_dia"].items():
        st = tot[(tot["plan"] == "a") & (tot["tipo_dia"] == tdia)]
        igual(f"plan que recorta, {tdia}: saldo", x["saldo_conservador_Mcop"], st["neto_hora"].sum() / 1e6)
        igual(f"plan que recorta, {tdia}: pax en riesgo por día", x["pax_en_riesgo_dia"], st["pasajeros_en_riesgo"].mean())

    g, gj = una(aho, clave="GIRO35"), J["palancas"]["giro_corto_35"]
    for kj, v in [("delta_km_anio", g["delta_km_anual"]), ("delta_buses_hora_anio", g["delta_buses_hora_anual"]),
                  ("ahorro_operacion_Mcop", (g["ahorro_por_km"] + g["ahorro_conductor_hora"]) / 1e6),
                  ("pasajes_perdidos_Mcop", g["ingreso_perdido"] / 1e6), ("saldo_conservador_Mcop", g["neto_pago_por_hora"] / 1e6),
                  ("espera_hoy_min", g["espera_min_S0"]), ("espera_despues_min", g["espera_min_esc"]),
                  ("valor_social_espera_Mcop", g["valor_social_espera"] / 1e6)]:
        igual(f"giro corto: {kj} = ahorros_por_escenario [GIRO35]", gj[kj], v)
    igual("giro corto: saldo pesimista = [GIRO35].neto_pago_por_hora_bajo × 1e-6", gj["saldo_rango_Mcop"]["pesimista"], g["neto_pago_por_hora_bajo"] / 1e6)
    igual("giro corto: saldo optimista = [GIRO35].neto_pago_por_hora_alto × 1e-6", gj["saldo_rango_Mcop"]["optimista"], g["neto_pago_por_hora_alto"] / 1e6)
    igual("giro corto: pax en riesgo central = [GIRO35].pax_perdidos_dia", gj["pax_en_riesgo_dia"]["central"], g["pax_perdidos_dia"])
    igual("giro corto: pax en riesgo con β baja = [GIRO35].pax_perdidos_dia_alto (caso optimista)", gj["pax_en_riesgo_dia"]["bajo"], g["pax_perdidos_dia_alto"])
    igual("giro corto: pax en riesgo con β alta = [GIRO35].pax_perdidos_dia_bajo (caso pesimista)", gj["pax_en_riesgo_dia"]["alto"], g["pax_perdidos_dia_bajo"])
    igual('giro corto: β de equilibrio = beta_equilibrio.csv [GIRO35]["pago por hora"]', gj["beta_equilibrio"],
          float(una(beta, clave="GIRO35")["pago por hora"]))
    d6 = json.loads((R / "experimentos/D6_simulador/resultados_escenarios.json").read_text(encoding="utf-8"))
    fil = [x for x in d6["resumen"] if x["ruta"] == "CRA 54" and x["grupo"] == "principal" and x["politica"] == "S0+G"]
    informar("giro corto: una sola fila de D6 (CRA 54, principal, S0+G)", len(fil) == 1)
    if fil:
        igual("giro corto: bajadas forzadas por día = D6 resultados_escenarios.json", gj["bajadas_forzadas_dia"], fil[0]["bajadas_forzadas"])
    rg, rj = una(aho, clave="REG_CL72"), J["palancas"]["regularizar_cl72"]
    for kj, v in [("espera_hoy_min", rg["espera_min_S0"]), ("espera_despues_min", rg["espera_min_esc"]),
                  ("delta_espera_min", rg["delta_espera_min"]), ("delta_km_anio", rg["delta_km_anual"]),
                  ("delta_buses_hora_anio", rg["delta_buses_hora_anual"]),
                  ("ahorro_operacion_Mcop", (rg["ahorro_por_km"] + rg["ahorro_conductor_hora"]) / 1e6),
                  ("pasajes_perdidos_Mcop", rg["ingreso_perdido"] / 1e6), ("saldo_conservador_Mcop", rg["neto_pago_por_hora"] / 1e6),
                  ("pax_en_riesgo_dia", rg["pax_perdidos_dia"]), ("valor_social_espera_Mcop", rg["valor_social_espera"] / 1e6)]:
        igual(f"regularizar CL 72: {kj} = ahorros_por_escenario [REG_CL72]", rj[kj], v)

    lb = csv_costos(R, "costos/resultados/linea_base_2025.csv")
    tres, total = lb[lb["ruta"].isin(RUTAS)], una(lb, ruta="Total")
    cx = J["contexto"]
    informar("contexto: linea_base_2025.csv tiene las tres rutas", len(tres) == 3)
    igual("contexto: costo de operación anual (tres rutas)", cx["costo_operacion_anual_Mcop"], tres["costo_total"].sum() / 1e6)
    igual("contexto: costo de operación anual = fila Total", cx["costo_operacion_anual_Mcop"], total["costo_total"] / 1e6)
    igual("contexto: costos fijos anuales", cx["costos_fijos_anual_Mcop"], tres["fijos"].sum() / 1e6)
    igual("contexto: km al año", cx["km_anio"], tres["km_anual"].sum())
    igual("contexto: buses-hora al año", cx["buses_hora_anio"], tres["buses_hora_anual"].sum())
    d5j = json.loads((R / "experimentos/D5_optimizacion_milp/resultados.json").read_text(encoding="utf-8"))
    igual("contexto: pasajeros por día de 2025 = D5 resultados.json", cx["pax_dia_2025"], d5j["complemento"]["pasajeros_dia_2025"])


# ----------------------------------------------------------------------------------------------------------------------
# 3. Inventario verificado (app/DATOS.md y datos/cifras_app.json)
# ----------------------------------------------------------------------------------------------------------------------
DATOS_MD = [  # (id de DATOS.md, subclave del objeto o None, ruta en ahorro_anual.json)
    ("inicio_salidas_dia_hoy", None, "planes.hoy.salidas_dia"),
    ("inicio_salidas_dia_plan", None, "planes.reasigna.salidas_dia"),
    ("inicio_buses_hora_hoy", None, "planes.hoy.buses_hora_dia"),
    ("inicio_buses_hora_plan", None, "planes.reasigna.buses_hora_dia"),
    ("inicio_espera_hoy", None, "planes.hoy.espera_min"),
    ("inicio_espera_plan", None, "planes.reasigna.espera_min"),
    ("inicio_sobrecapacidad_hoy", None, "planes.hoy.pax_sobre_capacidad_dia"),
    ("inicio_sobrecapacidad_plan", None, "planes.reasigna.pax_sobre_capacidad_dia"),
    ("inicio_pax_riesgo_plan", None, "planes.reasigna.pax_en_riesgo_dia.central"),
    ("inicio_pax_netos_simetrica", None, "planes.reasigna.pax_netos_dia_simetrico"),
    ("inicio_saldo_conservador", None, "planes.reasigna.saldo_conservador_Mcop"),
    ("inicio_saldo_simetrico", None, "planes.reasigna.saldo_simetrico_Mcop"),
    ("inicio_ahorro_operativo_plan", None, "planes.reasigna.ahorro_operacion_Mcop"),
    ("inicio_recorte_no_paga_d5", None, "planes.recorta.saldo_conservador_Mcop"),
    ("inicio_domingos_pagan", None, "palancas.domingos_festivos.saldo_conservador_Mcop"),
    ("inicio_beta_equilibrio_d5", None, "planes.recorta.beta_equilibrio"),
    ("inicio_pax_dia_2025", None, "contexto.pax_dia_2025"),
    ("inicio_horas_fc_mayor_1", "hoy", "planes.hoy.pct_horas_fc_mayor_1"),
    ("inicio_horas_fc_mayor_1", "plan", "planes.reasigna.pct_horas_fc_mayor_1"),
    ("inicio_tarifa_neta", None, "convenciones.tarifa_neta_cop"),
    ("inicio_costo_km", None, "convenciones.costo_km_cop"),
    ("inicio_costo_bus_hora", None, "convenciones.costo_bus_hora_cop"),
    ("inicio_beta", None, "convenciones.beta.central"),
    ("inicio_beta_rango", "inf", "convenciones.beta.bajo"),
    ("inicio_beta_rango", "sup", "convenciones.beta.alto"),
    ("inicio_demanda_por_anio", "2025", "contexto.pax_anio_2025"),
]
CIFRAS_EXTRA = [  # (id, campo del objeto en cifras_app.json, ruta en ahorro_anual.json)
    ("inicio_buses_hora_plan", "delta_buses_hora_anual", "planes.reasigna.delta_buses_hora_anio"),
    ("inicio_pax_riesgo_plan", "bajo", "planes.reasigna.pax_en_riesgo_dia.bajo"),
    ("inicio_pax_riesgo_plan", "alto", "planes.reasigna.pax_en_riesgo_dia.alto"),
    ("inicio_domingos_pagan", "por_dia_Mcop", "palancas.domingos_festivos.saldo_por_dia_Mcop"),
    ("inicio_domingos_pagan", "dias", "palancas.domingos_festivos.dias"),
    ("inicio_domingos_pagan", "pax_riesgo_dia", "palancas.domingos_festivos.pax_en_riesgo_dia"),
]


def inventario(J, R):
    print("\n3. Inventario verificado: app/DATOS.md (valores leídos de su tabla) y datos/cifras_app.json")
    filas = tabla_datos_md((R / "app/DATOS.md").read_text(encoding="utf-8"))
    for clave, sub, ruta in DATOS_MD:
        nombre = f"DATOS.md {clave}{'.' + sub if sub else ''} = {ruta}"
        if clave not in filas:
            informar(nombre, False, "no está en DATOS.md")
            continue
        try:
            x, dec = dict_es(filas[clave])[sub] if sub else num_es(filas[clave])
        except (ValueError, KeyError) as e:
            informar(nombre, False, f"valor ilegible {filas[clave]!r}: {e}")
            continue
        a = val(J, ruta)
        ok = a is not None and abs(a - x) <= 0.5 * 10 ** (-dec) + 1e-12
        informar(nombre, ok, f"archivo {_det(a)}; DATOS.md {filas[clave]}")
    if not CIFRAS.exists():
        informar("datos/cifras_app.json existe", False)
        return
    inicio = json.loads(CIFRAS.read_text(encoding="utf-8"))["pantallas"]["inicio"]
    for clave, campo, ruta in CIFRAS_EXTRA:
        x, a = inicio[clave].get(campo), val(J, ruta)
        ok = x is not None and a is not None and abs(a - x) <= tol_6cs(x)
        informar(f"cifras_app.json {clave}.{campo} = {ruta}", ok, f"archivo {_det(a)}; inventario {_det(x)}")


# ----------------------------------------------------------------------------------------------------------------------
# 4. Informe de resultados
# ----------------------------------------------------------------------------------------------------------------------
H, RA, RE = "planes.hoy.", "planes.reasigna.", "planes.recorta."
G, CL, TD = "palancas.giro_corto_35.", "palancas.regularizar_cl72.", "palancas.domingos_festivos.plan_recorta_por_tipo_dia."


def _franja(J, tipo, plan, desde, hasta):
    horas = J["por_hora"]["horas"]
    return sum(v for h, v in zip(horas, J["por_hora"]["tipos_dia"][tipo][plan]) if desde <= h <= hasta)


# (qué se comprueba, texto del informe con {} donde va la cifra y … para «cualquier texto en la misma línea», cifras:
#  (ruta en el archivo o función, decimales, modo))
INFORME = [
    ("resumen: espera y sobrecarga, hoy → plan que reasigna",
     "con menos espera ({} → {} min) y menos sobrecarga ({} → {} pasajeros al día)",
     [(H + "espera_min", 2), (RA + "espera_min", 2), (H + "pax_sobre_capacidad_dia", 0), (RA + "pax_sobre_capacidad_dia", 0)]),
    ("resumen: el plan que recorta: recorte, saldo, ahorro y pasajes",
     "recortaba el {} % de las horas de bus…pierde {} M: lo que ahorra en operación ({} M) no cubre los pasajes perdidos ({} M)",
     [(RE + "var_buses_hora_pct", 1, "abs"), (RE + "saldo_conservador_Mcop", 0, "abs"), (RE + "ahorro_operacion_Mcop", 0),
      (RE + "pasajes_perdidos_Mcop", 0)]),
    ("resumen: β de equilibrio del plan que recorta", "D5 deja de pagar con β mayor que {},", [(RE + "beta_equilibrio", 2)]),
    ("resumen: buses-hora del plan que reasigna", "mantiene los buses-hora de hoy ({} %)", [(RA + "var_buses_hora_pct", 1)]),
    ("resumen: domingos y festivos",
     "el único recorte que paga es el de domingos y festivos ({} M COP al año con pago por hora), y cuesta unos {} pasajeros en riesgo por domingo",
     [("palancas.domingos_festivos.saldo_conservador_Mcop", 0, "signo"), ("palancas.domingos_festivos.pax_en_riesgo_dia", -2)]),
    ("resumen: saldos del plan que reasigna", "(el mismo orden que la sección 4.3: {} y {} M)",
     [(RA + "saldo_conservador_Mcop", 0), (RA + "saldo_simetrico_Mcop", 0, "signo")]),
    ("Tabla 3: S0 oferta real", "| S0 oferta real | {} | {} | {} | {} | {} % |",
     [(H + "salidas_dia", 0), (H + "buses_hora_dia", 0), (H + "espera_min", 2), (H + "pax_sobre_capacidad_dia", 0),
      (H + "pct_horas_fc_mayor_1", 1)]),
    ("Tabla 3: D5 (el plan que recorta)",
     "| **D5 (penalidad 10.000 COP, máx. 10 min)** | **{}** | **{}** | **{}** | **{}** | **{} %** | **{}** | **{}** |",
     [(RE + "salidas_dia", 0), (RE + "buses_hora_dia", 0), (RE + "espera_min", 2), (RE + "pax_sobre_capacidad_dia", 0),
      (RE + "pct_horas_fc_mayor_1", 1), (RE + "saldo_conservador_Mcop", 0), (RE + "beta_equilibrio", 2)]),
    ("Tabla 3: D5 reoptimizado (el plan que reasigna)",
     "| D5 reoptimizado con costos con fuente (e = 0,5) | {} | {} | {} | {} | {} % | {} (simétrica: {}) |",
     [(RA + "salidas_dia", 0), (RA + "buses_hora_dia", 0), (RA + "espera_min", 2), (RA + "pax_sobre_capacidad_dia", 0),
      (RA + "pct_horas_fc_mayor_1", 1), (RA + "saldo_conservador_Mcop", 0), (RA + "saldo_simetrico_Mcop", 0, "signo")]),
    ("§4.3: cuánto recorta D5",
     "programa {} % menos salidas y {} % menos buses-hora ({} al año, y {} millones de km), con la espera de {} a {} min",
     [(RE + "var_salidas_pct", 1, "abs"), (RE + "var_buses_hora_pct", 1, "abs"), (RE + "delta_buses_hora_anio", 0),
      (RE + "delta_km_anio", 2, "millones"), (H + "espera_min", 2), (RE + "espera_min", 2)]),
    ("§4.3: ahorro y pasajes del plan que recorta",
     "ahorra {} M COP al año ({} en km y {} en conductor), pierde {} M en pasajes con β = {} y deja de pagar con β mayor que {}.",
     [(RE + "ahorro_operacion_Mcop", 0), (RE + "ahorro_km_Mcop", 0), (RE + "ahorro_conductor_Mcop", 0),
      (RE + "pasajes_perdidos_Mcop", 0), ("convenciones.beta.central", 2), (RE + "beta_equilibrio", 2)]),
    ("§4.3: el plan que reasigna",
     "D5 programa {} salidas al día con casi los mismos buses-hora de hoy ({} %), menos espera ({} min) y menos sobrecarga ({} pasajeros al día sobre la capacidad; horas con factor de carga > 1 de {} % a {} %)",
     [(RA + "salidas_dia", 0), (RA + "var_buses_hora_pct", 1), (RA + "espera_min", 2), (RA + "pax_sobre_capacidad_dia", 0),
      (H + "pct_horas_fc_mayor_1", 1), (RA + "pct_horas_fc_mayor_1", 1)]),
    ("§4.3: CL 72 y la franja de 13 a 15 h laboral",
     "las pasa a CL 72 (de {} a {} salidas al día) y a la franja de 13 a 15 h de los días laborales (de {} a {} salidas por día laboral en las tres rutas)",
     [("por_ruta.CL 72.hoy.salidas_dia", 0), ("por_ruta.CL 72.reasigna.salidas_dia", 0),
      (lambda J: _franja(J, "Laboral", "hoy", 13, 15), 1), (lambda J: _franja(J, "Laboral", "reasigna", 13, 15), 1)]),
    ("§4.3: saldos del plan que reasigna", "Con la contabilidad conservadora pierde {} M COP al año,…; contándolas, gana {} M.",
     [(RA + "saldo_conservador_Mcop", 0, "abs"), (RA + "saldo_simetrico_Mcop", 0)]),
    ("Tabla 7: D5, km y buses-hora", "| D5 (penalidad 10.000 COP) | {} | {} |", [(RE + "delta_km_anio", 0), (RE + "delta_buses_hora_anio", 0)]),
    ("Tabla 7: D5, ahorro, pasajes y saldo", "| D5 (penalidad 10.000 COP) |…| {} | {} | **{}** [",
     [(RE + "ahorro_operacion_Mcop", 0), (RE + "pasajes_perdidos_Mcop", 0), (RE + "saldo_conservador_Mcop", 0)]),
    ("Tabla 7: giro corto en el punto 35", "| Giro corto en el punto 35, CRA 54 (D6)⁴ | {} | {} |…| {} | {} | **{}** [{}; {}] |",
     [(G + "delta_km_anio", 0), (G + "delta_buses_hora_anio", 0), (G + "ahorro_operacion_Mcop", 0), (G + "pasajes_perdidos_Mcop", 0),
      (G + "saldo_conservador_Mcop", 0, "signo"), (G + "saldo_rango_Mcop.pesimista", 0, "signo"), (G + "saldo_rango_Mcop.optimista", 0, "signo")]),
    ("Tabla 7: regularizar CL 72", "| Regularizar CL 72 (D6) | {} | {} |…| {} | {} | **{}** |",
     [(CL + "delta_km_anio", 0), (CL + "delta_buses_hora_anio", 0), (CL + "ahorro_operacion_Mcop", 0), (CL + "pasajes_perdidos_Mcop", 0),
      (CL + "saldo_conservador_Mcop", 0, "signo")]),
    ("§5: espera de CL 72 regularizada y su valor social", "bajan la espera de {} a {} min, unas…que valen unos {} M COP de valor social",
     [(CL + "espera_hoy_min", 1), (CL + "espera_despues_min", 1), (CL + "valor_social_espera_Mcop", 0)]),
    ("§4.4: bajadas forzadas del giro corto", "obliga a bajarse antes a {} pasajeros al día (D6)", [(G + "bajadas_forzadas_dia", 0)]),
    ("Tabla 7b: laboral", "| Laboral | {} | {} |…| {} |",
     [(TD + "Laboral.dias", 0), (TD + "Laboral.saldo_conservador_Mcop", 0), (TD + "Laboral.pax_en_riesgo_dia", 0)]),
    ("Tabla 7b: sábado", "| Sábado | {} | {} |…| {} |",
     [(TD + "Sábado.dias", 0), (TD + "Sábado.saldo_conservador_Mcop", 0), (TD + "Sábado.pax_en_riesgo_dia", 0)]),
    ("Tabla 7b: domingo y festivo", "| Domingo y festivo | {} | **{}** |…| {} |",
     [(TD + "Domingo/festivo.dias", 0), (TD + "Domingo/festivo.saldo_conservador_Mcop", 0, "signo"),
      (TD + "Domingo/festivo.pax_en_riesgo_dia", 0)]),
    ("Tabla 7b: año (= el plan que recorta)", "| **Año** | {} | **{}** |…| {} |",
     [("convenciones.dias_anio", 0), (RE + "saldo_conservador_Mcop", 0), (RE + "pax_en_riesgo_dia.central", 0)]),
]


def informe(J, R):
    print("\n4. documentos/informe_resultados.md (cifras del archivo redondeadas como las cita el informe)")
    texto = (R / "documentos/informe_resultados.md").read_text(encoding="utf-8")
    for nombre, plantilla, cifras in INFORME:
        trozos = plantilla.split("{}")
        textos = []
        for spec in cifras:
            ruta, dec, modo = (list(spec) + [None])[:3]
            x = ruta(J) if callable(ruta) else val(J, ruta)
            textos.append(es(x, dec, modo))
        patron = ""
        for i, t in enumerate(trozos):
            patron += r"[^\n]*?".join(re.escape(p) for p in t.split("…"))
            if i < len(textos):
                patron += re.escape(textos[i])
        informar(nombre, re.search(patron, texto) is not None, " · ".join(textos))


# ----------------------------------------------------------------------------------------------------------------------
# 5. Lecturas que la pantalla debe respetar
# ----------------------------------------------------------------------------------------------------------------------
def lecturas(J):
    print("\n5. Lecturas que la pantalla debe respetar (si una falla, hay que revisar el texto de la pantalla)")
    h, a, r = (J["planes"][k] for k in PLANES)
    informar("el plan que reasigna pierde con la contabilidad conservadora y gana con la simétrica",
             a["saldo_conservador_Mcop"] < 0 < a["saldo_simetrico_Mcop"])
    informar("el plan que recorta ahorra más en operación que el que reasigna", r["ahorro_operacion_Mcop"] > a["ahorro_operacion_Mcop"] > 0)
    informar("en caja, el plan que recorta queda mejor que el que reasigna en las DOS contabilidades",
             r["saldo_conservador_Mcop"] > a["saldo_conservador_Mcop"] and r["saldo_simetrico_Mcop"] > a["saldo_simetrico_Mcop"])
    informar("el plan que recorta pierde pasajeros aun con la simétrica; el que reasigna los gana",
             r["pax_netos_dia_simetrico"] < 0 < a["pax_netos_dia_simetrico"])
    informar("sobrecarga: reasigna < hoy < recorta", a["pax_sobre_capacidad_dia"] < h["pax_sobre_capacidad_dia"] < r["pax_sobre_capacidad_dia"])
    informar("espera: reasigna < hoy < recorta", a["espera_min"] < h["espera_min"] < r["espera_min"])
    informar("con costos centrales, la β de equilibrio del plan que recorta queda por debajo del rango de β",
             r["beta_equilibrio"] < J["convenciones"]["beta"]["bajo"],
             f"{_det(r['beta_equilibrio'])} < {_det(J['convenciones']['beta']['bajo'])}")
    informar("con la contabilidad conservadora, los dos planes pierden con cualquier β del rango",
             all(J["planes"][k]["saldo_conservador_por_beta_Mcop"][b] < 0 for k in ("reasigna", "recorta")
                 for b in ("bajo", "central", "alto")))
    informar("el plan que reasigna mueve más salidas de las que ahorra (quitadas + puestas > salidas de menos)",
             a["quitadas_anio"] + a["puestas_anio"] > a["menos_salidas_anio"] > 0)
    informar("domingos y festivos: el único tramo positivo del plan que recorta",
             [k for k, x in J["palancas"]["domingos_festivos"]["plan_recorta_por_tipo_dia"].items() if x["saldo_conservador_Mcop"] > 0]
             == ["Domingo/festivo"])
    informar("giro corto: paga en todo el rango (pesimista > 0)", J["palancas"]["giro_corto_35"]["saldo_rango_Mcop"]["pesimista"] > 0)


# ----------------------------------------------------------------------------------------------------------------------
# 6. Origen de cada cifra
# ----------------------------------------------------------------------------------------------------------------------
def origen(J, R):
    print("\n6. Origen de cada cifra")
    org = J.get("origen", {})
    faltan = []

    def recorrer(o, ruta):
        if isinstance(o, dict):
            for k, v in o.items():
                recorrer(v, f"{ruta}.{k}" if ruta else k)
        elif isinstance(o, list):
            if o and not isinstance(o[0], str) and ruta not in org:
                faltan.append(ruta)
        elif not isinstance(o, str) and ruta not in org:
            faltan.append(ruta)

    for sec in ("convenciones", "planes", "por_ruta", "por_hora", "contexto", "palancas"):
        recorrer(J[sec], sec)
    informar("cada cifra del archivo tiene su entrada en «origen»", not faltan, ", ".join(faltan[:8]))
    sobran = [k for k in org if not _existe(J, k)]
    informar("cada entrada de «origen» corresponde a una cifra del archivo", not sobran, ", ".join(sobran[:8]))
    archivos = set()
    for o in org.values():
        for a in str(o.get("archivo", "")).split(";"):
            a = re.sub(r"\s*\(.*\)$", "", a.strip())
            if a and a not in ("definición", "sin fuente"):
                archivos.add(a)
    informar("cada origen tiene archivo y clave", all(o.get("archivo") and o.get("clave") for o in org.values()))
    no = sorted(a for a in archivos if not (R / a).exists())
    informar(f"los {len(archivos)} archivos de origen existen en el proyecto", not no, ", ".join(no))


def _existe(J, ruta):
    try:
        val(J, ruta)
        return True
    except (KeyError, TypeError):
        return False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8" if not sys.stdout.isatty() else sys.stdout.encoding, errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", default=str(AQUI.parent.parent), help="carpeta raíz del proyecto (por defecto, dos arriba)")
    R = Path(ap.parse_args().proyecto).resolve()
    if not ARCHIVO.exists():
        print(f"FALLA  no existe {ARCHIVO} (corra preparar_datos.py)")
        sys.exit(1)
    J = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    print(f"Archivo: {ARCHIVO}\nProyecto: {R}")
    identidades(J)
    fuentes(J, R)
    inventario(J, R)
    informe(J, R)
    lecturas(J)
    origen(J, R)
    print(f"\n{CUENTA['ok']} OK, {CUENTA['falla']} FALLA")
    sys.exit(1 if CUENTA["falla"] else 0)


if __name__ == "__main__":
    main()
