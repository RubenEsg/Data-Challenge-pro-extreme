"""Conciliación de la revisión doble de alertas (§18 «Etiquetas incorrectas → métricas engañosas»).

Revisión AUTOMATIZADA: los revisores A y B y el conciliador son agentes de modelo de lenguaje que siguen
protocolo.md. No es una revisión humana; la validación por el área de operaciones de Sobusa está pendiente.

Lee muestra.json, etiquetas_A.json, etiquetas_B.json y las tarjetas muestra/<id>.md (solo para las marcas de
calendario), aplica las decisiones del conciliador a los desacuerdos (DECISIONES, abajo) y escribe
conciliacion.json. No se conecta a ninguna base de datos.

Uso (desde cualquier carpeta):  python -I conciliar.py
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
CATEGORIAS = ("verdadera", "falsa", "indeterminada")
Z95 = 1.959963984540054
SEMILLA = 42
FESTIVOS_2025 = {"2025-10-13", "2025-11-03", "2025-11-17", "2025-12-08", "2025-12-25"}
AVISO = (
    "Revisión automatizada: los revisores A y B y el conciliador son agentes de modelo de lenguaje que siguen "
    "protocolo.md (no es una revisión humana). La validación por el área de operaciones de Sobusa está pendiente: "
    "hasta entonces estas etiquetas son una estimación reproducible, no la verdad operativa."
)

# Decisiones del conciliador (tercer revisor, agente de modelo de lenguaje) para cada desacuerdo A/B.
# Se tomaron releyendo la tarjeta y las dos justificaciones con el orden de decisión de protocolo.md §2.
DECISIONES = {
    "M048": {
        "etiqueta": "indeterminada",
        "criterio": "2.5 · ALT-006 indeterminada (2.1 y 2.2 no deciden)",
        "motivo": (
            "Las cifras cumplen la definición de verdadera (4 de 31 salidas en 14-20 h, déficit 87,1 %, con demanda "
            "y acumulación en 15-16 h: 338 y 226 subidas con 2 y 1 salidas, unas 169 y 226 por salida frente a "
            "82-109 en los días de vacaciones previos), y el paso 2.1 no aplica porque la 14 h en cero va seguida "
            "de acumulación y el bloque 17-19 h es el final del día, no un hueco entre horas normales. La falsa (c) "
            "de A exige salidas parecidas a las de días previos del mismo tipo o calendario y la tarjeta no las "
            "muestra (4 frente a 10 el 24-dic y 28-34 el 26, 29 y 30-dic); pero el 24-dic también cerró temprano "
            "(18 h en cero), así que separar un cierre programado de víspera de Año Nuevo de una falla de despacho "
            "depende del plan de operación del 31-dic, que la tarjeta no trae. Queda indeterminada, como propuso B; "
            "si Sobusa confirma un cierre planeado pasa a falsa (c), si no, a verdadera."
        ),
    },
    "M092": {
        "etiqueta": "verdadera",
        "criterio": "2.4 · ALT-008 verdadera (a); la excepción de calendario no aplica",
        "motivo": (
            "El día es atípico (10.686 subidas y 134 viajes, z -6,73 y -6,91) y la serie horaria muestra la causa "
            "en el dato: corte abrupto de 461 subidas a las 16 h a 0 pasajeros y 0 salidas en 17-20 h, con 2 a 5 "
            "salidas por hora desde las 12 h frente a 17-19 programadas. La falsa por calendario de ALT-008 (31 de "
            "diciembre incluido) exige un perfil horario completo y normal para ese día, y la indeterminada también "
            "supone perfil completo; aquí faltan 4 horas (el 24-dic tuvo sus 17 horas con servicio). Que el corte "
            "sea un cierre de víspera o un hueco de la fuente no cambia la etiqueta: para ALT-008 el problema del "
            "dato es la situación y la acción de §5.2 («validar fuente, trigger y período afectado») es justo la que "
            "separa los dos casos. Queda verdadera, como propuso B. Es coherente con M053 (ALT-005, misma ruta y "
            "día), que ambos revisores marcaron falsa porque para ALT-005 esas horas en cero son un artefacto."
        ),
    },
}

# Precisión aproximada que informa el backtest del commit 3d6781d (la misma población que la muestra para las
# observadas; para las de pronóstico, la corrida de las 05:03:33 con 288 y 278 alertas, frente a 295 y 282 del
# código congelado). lift = precisión proxy / tasa base de la condición en una hora cualquiera.
BACKTEST = {
    "ALT-001": {"alertas_backtest": 288, "precision_proxy": 0.924, "tasa_base": 0.821, "lift": 1.12,
                "proxy": "demanda real de la hora > capacidad programada (buses/h × 50)",
                "fuente": "backtest_alertas_pronostico.md del commit 3d6781d (05:03:33, variante «ahora»)"},
    "ALT-002": {"alertas_backtest": 278, "precision_proxy": 0.968, "tasa_base": 0.849, "lift": 1.14,
                "proxy": "ocupación real de la hora ≥ 90 %",
                "fuente": "backtest_alertas_pronostico.md del commit 3d6781d (05:03:33, variante «ahora»)"},
    "ALT-003": {"alertas_backtest": None, "precision_proxy": None, "tasa_base": None, "lift": None,
                "proxy": "no evaluado en el backtest del commit 3d6781d",
                "fuente": "backtest_alertas_pronostico.md del commit 3d6781d"},
    "ALT-005": {"alertas_backtest": 46, "precision_proxy": 0.359, "tasa_base": 0.077, "lift": 4.69,
                "proxy": "el episodio sigue en la hora siguiente a la detección",
                "fuente": "backtest_alertas.md del commit 3d6781d (04:58:11); igual en la versión de las 06:26"},
    "ALT-006": {"alertas_backtest": 41, "precision_proxy": 0.390, "tasa_base": 0.047, "lift": 8.30,
                "proxy": "el episodio sigue en la hora siguiente a la detección",
                "fuente": "backtest_alertas.md del commit 3d6781d (04:58:11); igual en la versión de las 06:26"},
    "ALT-007": {"alertas_backtest": 66, "precision_proxy": 0.270, "tasa_base": 0.202, "lift": 1.34,
                "proxy": "el episodio sigue en la hora siguiente a la detección",
                "fuente": "backtest_alertas.md del commit 3d6781d (04:58:11); igual en la versión de las 06:26"},
    "ALT-008": {"alertas_backtest": 20, "precision_proxy": 0.700, "tasa_base": 0.185, "lift": 3.78,
                "proxy": "el día está marcado como especial o excluido",
                "fuente": "backtest_alertas.md del commit 3d6781d (04:58:11); igual en la versión de las 06:26"},
}


def leer_json(nombre: str):
    return json.loads((AQUI / nombre).read_text(encoding="utf-8"))


def kappa_cohen(x: list[str], y: list[str]) -> dict:
    n = len(x)
    p_o = sum(a == b for a, b in zip(x, y, strict=True)) / n
    ca, cb = Counter(x), Counter(y)
    p_e = sum((ca[k] / n) * (cb[k] / n) for k in CATEGORIAS)
    kappa = None if p_e >= 1 - 1e-12 else (p_o - p_e) / (1 - p_e)
    return {"n": n, "coinciden": sum(a == b for a, b in zip(x, y, strict=True)), "acuerdo_bruto": round(p_o, 4),
            "acuerdo_esperado_azar": round(p_e, 4), "kappa": None if kappa is None else round(kappa, 4)}


def kappa_bootstrap(x: list[str], y: list[str], reps: int = 5000) -> list[float]:
    rng = np.random.default_rng(SEMILLA)
    n, vals = len(x), []
    for _ in range(reps):
        idx = rng.integers(0, n, n)
        k = kappa_cohen([x[i] for i in idx], [y[i] for i in idx])["kappa"]
        if k is not None:
            vals.append(k)
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)]


def wilson(exitos: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    p = exitos / n
    den = 1 + Z95**2 / n
    centro = (p + Z95**2 / (2 * n)) / den
    medio = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n * n)) / den
    return [round(max(0.0, centro - medio), 4), round(min(1.0, centro + medio), 4)]


def marcas_calendario(tarjeta: Path) -> str:
    texto = tarjeta.read_text(encoding="utf-8")
    m = re.search(r"Marcas de calendario del día:\s*(.+?)\.\s*$", texto, flags=re.M)
    return m.group(1).strip() if m else "?"


def dia_especial(fecha: str, marcas: str) -> bool:
    """Domingo, festivo, 24 o 31 de diciembre, o cualquier marca de calendario en la tarjeta."""
    d = date.fromisoformat(fecha)
    return (d.weekday() == 6 or fecha in FESTIVOS_2025 or fecha[5:] in ("12-24", "12-31")
            or marcas not in ("ninguna", "?"))


def reponderada(estratos: dict, poblacion: dict, reps: int = 200_000) -> dict:
    """Precisión global reponderada por población/muestra (indeterminadas fuera) con intervalo de Jeffreys
    por Monte Carlo y cotas si todas las indeterminadas fueran falsas o verdaderas."""
    codigos = [c for c in estratos if estratos[c]["verdaderas"] + estratos[c]["falsas"] > 0]
    total = sum(poblacion[c] for c in codigos)
    pesos = {c: poblacion[c] / total for c in codigos}
    punto = sum(pesos[c] * estratos[c]["verdaderas"] / (estratos[c]["verdaderas"] + estratos[c]["falsas"])
                for c in codigos)
    peor = sum(pesos[c] * estratos[c]["verdaderas"] / estratos[c]["n"] for c in codigos)
    mejor = sum(pesos[c] * (estratos[c]["verdaderas"] + estratos[c]["indeterminadas"]) / estratos[c]["n"]
                for c in codigos)
    rng = np.random.default_rng(SEMILLA)
    sim = np.zeros(reps)
    for c in codigos:
        sim += pesos[c] * rng.beta(estratos[c]["verdaderas"] + 0.5, estratos[c]["falsas"] + 0.5, reps)
    return {
        "codigos": codigos, "poblacion": total, "pesos": {c: round(w, 4) for c, w in pesos.items()},
        "precision": round(punto, 4),
        "intervalo_95_jeffreys_mc": [round(float(np.percentile(sim, 2.5)), 4),
                                     round(float(np.percentile(sim, 97.5)), 4)],
        "mediana_jeffreys_mc": round(float(np.median(sim)), 4),
        "nota_intervalo": ("asimétrico: con 26 de 26 verdaderas en ALT-002 la estimación puntual (1,0) queda en el "
                           "borde y la distribución de Jeffreys la corre hacia abajo"),
        "tasa_falsas": round(1 - punto, 4),
        "cota_indeterminadas_falsas": round(peor, 4), "cota_indeterminadas_verdaderas": round(mejor, 4),
    }


def main() -> None:
    muestra = leer_json("muestra.json")
    items = muestra["muestra"]
    poblacion = muestra["poblacion"]
    A = {x["id"]: x for x in leer_json("etiquetas_A.json")}
    B = {x["id"]: x for x in leer_json("etiquetas_B.json")}
    ids = [x["id"] for x in items]
    assert set(ids) == set(A) == set(B) and len(ids) == 96, "las etiquetas no cubren la misma muestra"
    for fuente in (A, B):
        assert all(v["etiqueta"] in CATEGORIAS for v in fuente.values()), "etiqueta fuera del protocolo"

    desacuerdos = [i for i in ids if A[i]["etiqueta"] != B[i]["etiqueta"]]
    assert set(desacuerdos) == set(DECISIONES), f"desacuerdos {desacuerdos} sin decisión o decisiones de más"

    # Acuerdo antes de conciliar.
    def bloque(filtro) -> dict:
        sel = [x["id"] for x in items if filtro(x)]
        res = kappa_cohen([A[i]["etiqueta"] for i in sel], [B[i]["etiqueta"] for i in sel])
        if res["kappa"] is None:
            res["nota"] = "kappa no definida: los dos revisores usaron una sola categoría (acuerdo esperado = 1)"
        return res

    acuerdo = {"global": bloque(lambda x: True)}
    acuerdo["global"]["kappa_ic95_bootstrap"] = kappa_bootstrap([A[i]["etiqueta"] for i in ids],
                                                                [B[i]["etiqueta"] for i in ids])
    acuerdo["global"]["matriz_A_filas_B_columnas"] = {
        a: {b: sum(1 for i in ids if A[i]["etiqueta"] == a and B[i]["etiqueta"] == b) for b in CATEGORIAS}
        for a in CATEGORIAS
    }
    acuerdo["por_familia"] = {f: bloque(lambda x, f=f: x["familia"] == f)
                              for f in sorted({x["familia"] for x in items})}
    acuerdo["por_codigo"] = {c: bloque(lambda x, c=c: x["codigo"] == c) for c in sorted(poblacion)}
    acuerdo["confianza_A"] = dict(Counter(v.get("confianza") for v in A.values()))
    acuerdo["confianza_B"] = dict(Counter(v.get("confianza") for v in B.values()))

    # Etiquetas finales.
    finales = []
    for x in items:
        i = x["id"]
        marcas = marcas_calendario(AQUI / x["tarjeta"])
        fila = {
            "id": i, "codigo": x["codigo"], "familia": x["familia"], "ruta": x["ruta"], "fecha": x["fecha"],
            "ventana": x["ventana"], "marcas_calendario": marcas,
            "dia_especial": dia_especial(x["fecha"], marcas),
            "etiqueta_A": A[i]["etiqueta"], "etiqueta_B": B[i]["etiqueta"],
            "criterio_B": B[i].get("criterio"),
        }
        if i in DECISIONES:
            fila.update({"etiqueta_final": DECISIONES[i]["etiqueta"], "origen": "conciliador",
                         "criterio_final": DECISIONES[i]["criterio"], "motivo_conciliacion": DECISIONES[i]["motivo"],
                         "razon_A": A[i]["razon"], "razon_B": B[i]["razon"]})
        else:
            fila.update({"etiqueta_final": A[i]["etiqueta"], "origen": "acuerdo A=B", "razon_B": B[i]["razon"]})
        finales.append(fila)

    # Precisión por código.
    por_codigo = {}
    for c in sorted(poblacion):
        sub = [f for f in finales if f["codigo"] == c]
        cnt = Counter(f["etiqueta_final"] for f in sub)
        v, fa, ind = cnt["verdadera"], cnt["falsa"], cnt["indeterminada"]
        dec = v + fa
        prec = v / dec if dec else None
        bt = BACKTEST[c]
        esp = [f for f in sub if f["dia_especial"]]
        nesp = [f for f in sub if not f["dia_especial"]]
        por_codigo[c] = {
            "poblacion": poblacion[c], "n": len(sub), "verdaderas": v, "falsas": fa, "indeterminadas": ind,
            "precision": None if prec is None else round(prec, 4), "precision_ic95_wilson": wilson(v, dec),
            "tasa_falsas": None if prec is None else round(1 - prec, 4),
            "tasa_falsas_ic95_wilson": wilson(fa, dec),
            "falsas_sobre_revisadas": round(fa / len(sub), 4),
            "dias_especiales": {"n": len(esp), "falsas": sum(f["etiqueta_final"] == "falsa" for f in esp)},
            "dias_comunes": {"n": len(nesp), "falsas": sum(f["etiqueta_final"] == "falsa" for f in nesp)},
            "backtest": bt,
            "lift_implicito": (None if prec is None or not bt["tasa_base"] else round(prec / bt["tasa_base"], 2)),
            "proxy_dentro_del_ic": (None if bt["precision_proxy"] is None or prec is None
                                    else wilson(v, dec)[0] <= bt["precision_proxy"] <= wilson(v, dec)[1]),
            "ids_falsas": [f["id"] for f in sub if f["etiqueta_final"] == "falsa"],
            "ids_indeterminadas": [f["id"] for f in sub if f["etiqueta_final"] == "indeterminada"],
        }

    familias = {
        "pronostico": [c for c in por_codigo if c in ("ALT-001", "ALT-002", "ALT-003")],
        "observada": [c for c in por_codigo if c in ("ALT-005", "ALT-006", "ALT-007", "ALT-008")],
    }
    global_rep = {"todas": reponderada(por_codigo, poblacion)}
    for f, cods in familias.items():
        global_rep[f] = reponderada({c: por_codigo[c] for c in cods}, poblacion)
    cnt_tot = Counter(f["etiqueta_final"] for f in finales)
    sin_ponderar = {"verdaderas": cnt_tot["verdadera"], "falsas": cnt_tot["falsa"],
                    "indeterminadas": cnt_tot["indeterminada"],
                    "precision": round(cnt_tot["verdadera"] / (cnt_tot["verdadera"] + cnt_tot["falsa"]), 4),
                    "ic95_wilson": wilson(cnt_tot["verdadera"], cnt_tot["verdadera"] + cnt_tot["falsa"])}

    salida = {
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "aviso": AVISO,
        "revisores": {
            "A": "agente de modelo de lenguaje que sigue protocolo.md (etiquetas_A.json)",
            "B": "agente de modelo de lenguaje que sigue protocolo.md (etiquetas_B.json)",
            "conciliador": ("agente de modelo de lenguaje (tercer revisor) que relee la tarjeta y las dos "
                            "justificaciones con el orden de decisión de protocolo.md §2"),
            "validacion_humana": "pendiente: área de operaciones de Sobusa",
        },
        "instantanea": muestra.get("instantanea"), "periodo": muestra.get("periodo"),
        "model_id": muestra.get("model_id"),
        "metodo": {
            "acuerdo": ("acuerdo bruto y kappa de Cohen con 3 categorías (verdadera, falsa, indeterminada) ANTES "
                        "de conciliar; IC 95 % de la kappa global por bootstrap de tarjetas (5.000 réplicas, "
                        "semilla 42)"),
            "conciliacion": ("si A = B la etiqueta queda; si difieren decide el conciliador (DECISIONES en "
                             "conciliar.py)"),
            "precision": "verdaderas / (verdaderas + falsas) por código, indeterminadas aparte; IC 95 % de Wilson",
            "tasa_falsas": ("falsas / (verdaderas + falsas) = 1 - precisión (proporción de alertas que no debían "
                            "salir). La tasa de falsos positivos clásica (falsas / casos sin incidente) no se puede "
                            "calcular: solo se revisaron alertas, no horas sin alerta"),
            "reponderada": ("Σ (población del código / población total) × precisión del código; intervalo de "
                            "credibilidad 95 % con Beta(V + 0,5; F + 0,5) por código (Jeffreys) y 200.000 "
                            "simulaciones (semilla 42); cotas con todas las indeterminadas como falsas o como "
                            "verdaderas"),
            "lift_implicito": ("precisión conciliada / tasa base que informa el backtest para su condición proxy "
                               "(indicativo: la verdad del protocolo y el proxy del backtest no son la misma "
                               "condición)"),
            "dia_especial": ("domingo, festivo, 24 o 31 de diciembre, o cualquier marca de calendario en la tarjeta "
                             "(vacaciones incluidas)"),
        },
        "acuerdo_antes_de_conciliar": acuerdo,
        "desacuerdos": [{k: f[k] for k in ("id", "codigo", "ruta", "fecha", "ventana", "etiqueta_A", "etiqueta_B",
                                            "razon_A", "razon_B", "etiqueta_final", "criterio_final",
                                            "motivo_conciliacion")}
                        for f in finales if f["origen"] == "conciliador"],
        "precision_por_codigo": por_codigo,
        "precision_global_reponderada": global_rep,
        "precision_global_sin_ponderar": sin_ponderar,
        "etiquetas_finales": finales,
    }
    (AQUI / "conciliacion.json").write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # Resumen en pantalla.
    g = acuerdo["global"]
    print(f"acuerdo bruto {g['acuerdo_bruto']:.4f} ({g['coinciden']}/{g['n']}), "
          f"kappa {g['kappa']} IC {g['kappa_ic95_bootstrap']}")
    for f, r in acuerdo["por_familia"].items():
        print(f"  familia {f}: {r['coinciden']}/{r['n']} acuerdo {r['acuerdo_bruto']} kappa {r['kappa']}")
    for c, r in acuerdo["por_codigo"].items():
        print(f"  {c}: {r['coinciden']}/{r['n']} kappa {r['kappa']}")
    print("desacuerdos:", desacuerdos)
    for c, r in por_codigo.items():
        print(f"{c}: N={r['poblacion']} n={r['n']} V={r['verdaderas']} F={r['falsas']} I={r['indeterminadas']} "
              f"prec={r['precision']} IC={r['precision_ic95_wilson']} proxy={r['backtest']['precision_proxy']} "
              f"lift_bt={r['backtest']['lift']} lift_impl={r['lift_implicito']} "
              f"proxy_en_IC={r['proxy_dentro_del_ic']} "
              f"esp={r['dias_especiales']} com={r['dias_comunes']} falsas={r['ids_falsas']} "
              f"ind={r['ids_indeterminadas']}")
    for k, r in global_rep.items():
        print(f"reponderada {k}: {r['precision']} IC {r['intervalo_95_jeffreys_mc']} "
              f"cotas [{r['cota_indeterminadas_falsas']}, {r['cota_indeterminadas_verdaderas']}] "
              f"FP {r['tasa_falsas']}")
    print("sin ponderar:", sin_ponderar)


if __name__ == "__main__":
    main()
