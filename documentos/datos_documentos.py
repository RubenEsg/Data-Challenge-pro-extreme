"""Cifras y figuras de los documentos de entrega (E01, E02 y la presentación), leídas de las evidencias.

    python EntregaFinal/documentos/datos_documentos.py

Escribe:
  - generado/cifras.tex: una macro por cifra (\\WAPEact, \\AlertasAhora, …). Cada macro lleva en un comentario el archivo
    de evidencia del que sale; si el archivo falta, la macro dice «s. d.» y el guion lo avisa (código 1 con --estricto).
  - figuras/*.pdf y figuras/*.png: los gráficos, con los colores por rol del tablero (dash_app/tokens.py) y la letra
    Inter de documentos/fuentes.

Ninguna cifra se escribe a mano aquí: todas salen de api_frecuencias/docs/evidencias/ (rutas en FUENTES).
Necesita matplotlib (requisitos_documentos.txt). No escribe fuera de documentos/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ENTREGA = AQUI.parent
API = ENTREGA / "api_frecuencias"
EVID = API / "docs" / "evidencias"
GENERADO = AQUI / "generado"
FIGURAS = AQUI / "figuras"

# La corrida completa de pruebas que citan los documentos. La ruta estable es la corrida final de la suite
# (pruebas/suite_final.xml y pruebas/coverage_final.xml); mientras no exista, se usa la última corrida completa
# versionada (contrato/suite_completa_junit.xml) con la cobertura de esa misma época (sonarqube/coverage.xml), y los
# documentos dicen cuál es. Las variables EVIDENCIA_PRUEBAS y EVIDENCIA_COBERTURA fuerzan otra.
EVIDENCIA_PRUEBAS = EVID / "pruebas" / "suite_final.xml"
EVIDENCIA_COBERTURA = EVID / "pruebas" / "coverage_final.xml"
RESPALDO_PRUEBAS = EVID / "contrato" / "suite_completa_junit.xml"
RESPALDO_COBERTURA = EVID / "sonarqube" / "coverage.xml"
CI_GITHUB = Path(os.environ.get("EVIDENCIA_CI_GITHUB", EVID / "pruebas" / "ci_github.txt"))
PLAN_EVOLUCION = ENTREGA / "PLAN_EVOLUCION.md"
HALLAZGOS = API / "docs" / "hallazgos_extreme.md"


def _elegir(variable: str, final: Path, respaldo: Path) -> tuple[Path, bool]:
    if os.environ.get(variable):
        return Path(os.environ[variable]), True
    return (final, True) if final.exists() else (respaldo, False)


JUNIT, JUNIT_ES_FINAL = _elegir("EVIDENCIA_PRUEBAS", EVIDENCIA_PRUEBAS, RESPALDO_PRUEBAS)
COBERTURA, COBERTURA_ES_FINAL = _elegir("EVIDENCIA_COBERTURA", EVIDENCIA_COBERTURA, RESPALDO_COBERTURA)

FUENTES = {
    "modelo": EVID / "modelo" / "evaluacion_modelo.json",
    "candidato": EVID / "modelo" / "candidato_fv3" / "evaluacion_modelo.json",   # registrado sin activar
    "alertas": EVID / "alertas" / "backtest_alertas.json",
    "alertas2024": EVID / "alertas" / "backtest_alertas_corte_2024-12-31.json",
    "alertas_pron": EVID / "alertas" / "backtest_alertas_pronostico.json",
    "k6": EVID / "pruebas" / "k6_segmentos_consultas.json",        # corrida vigente, con el volumen de un año
    "k6ingesta": EVID / "pruebas" / "k6_segmentos_ingesta.json",
    "rendimiento": EVID / "rendimiento.txt",
    "compuerta": EVID / "monitoreo" / "compuerta_ejemplo.json",
    "onnx": EVID / "monitoreo" / "onnx_paridad.json",
    "monitoreo": EVID / "monitoreo" / "monitoreo_2025.json",
    "junit": JUNIT,
    "cobertura": COBERTURA,
}

sys.path.insert(0, str(ENTREGA / "dash_app"))
import tokens

ROL = tokens.ROL
avisos: list[str] = []


# --- Formato es-CO ----------------------------------------------------------------------------------------------------
def num(x, dec=2) -> str:
    """14.77 -> «14,77»; 3111 -> «3.111»; negativo con el signo menos tipográfico.

    Una sola regla de redondeo para todos los documentos: la mitad hacia arriba sobre la cifra decimal escrita en la
    evidencia (14,665 -> «14,67», no el 14,66 que daría el binario de 14.665)."""
    if x is None:
        return "s.\\,d."
    d = Decimal(str(x)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
    s = f"{abs(d):,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return ("−" if d < 0 else "") + s


def rel(p: Path) -> str:
    """Ruta de la evidencia relativa a EntregaFinal/ (la que se cita en el texto)."""
    try:
        return Path(p).resolve().relative_to(ENTREGA).as_posix()
    except ValueError:
        return Path(p).as_posix()


def leer_json(clave):
    p = FUENTES[clave]
    if not p.exists():
        avisos.append(f"falta {rel(p)}")
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# --- Macros -----------------------------------------------------------------------------------------------------------
macros: list[tuple[str, str, str]] = []      # (nombre, valor, fuente)


def macro(nombre: str, valor: str, fuente: Path | str):
    if not re.fullmatch(r"[A-Za-z]+", nombre):
        raise ValueError(f"nombre de macro inválido: {nombre}")
    macros.append((nombre, valor, rel(Path(fuente)) if not isinstance(fuente, str) else fuente))


def g(d, *ruta, defecto=None):
    for k in ruta:
        if not isinstance(d, dict) or k not in d:
            return defecto
        d = d[k]
    return d


def cifras_modelo():
    e = leer_json("modelo")
    f = FUENTES["modelo"]
    pr = g(e, "prueba_reservada") or {}
    glob = g(pr, "global") or {}
    boot = g(pr, "bootstrap") or {}
    cob = g(pr, "cobertura", "cand") or {}
    macro("ModeloActivo", str(g(pr, "modelos", "activo", defecto="s. d.")).replace("_", "\\_"), f)
    macro("PruebaDesde", str(g(pr, "modelos", "desde", defecto="s. d.")), f)
    macro("PruebaHasta", str(g(pr, "modelos", "hasta", defecto="s. d.")), f)
    macro("Nprueba", num(g(glob, "cand", "n"), 0), f)
    for nombre, k in (("act", "cand"), ("fvuno", "anterior"), ("buno", "b1"), ("bdos", "b2")):
        macro(f"WAPE{nombre}", num(g(glob, k, "wape")), f)
        macro(f"MAE{nombre}", num(g(glob, k, "mae")), f)
        ic = g(boot, k, "ic95") or [None, None]
        macro(f"WAPE{nombre}IC", f"{num(ic[0])}--{num(ic[1])}", f)
    macro("SesgoAct", num(g(glob, "cand", "sesgo_pct")), f)
    d = g(boot, "cand_menos_b1", "ic95") or [None, None]
    macro("DifActBunoIC", f"{num(d[0])} a {num(d[1])}", f)
    macro("PmejoraActBuno", num(g(boot, "cand_menos_b1", "p_mejora"), 2), f)
    w, b = g(glob, "cand", "wape"), g(glob, "b1", "wape")
    macro("MejoraRelBuno", num(100 * (b - w) / b, 0) if w and b else "s.\\,d.", f)
    macro("CobModelo", num(g(cob, "banda_modelo", "cobertura_pct")), f)
    macro("CobConformal", num(g(cob, "banda_conformal", "cobertura_pct")), f)
    macro("BajoPdiez", num(g(cob, "banda_conformal", "bajo_p10_pct")), f)
    macro("SobrePnoventa", num(g(cob, "banda_conformal", "sobre_p90_pct")), f)
    for franja, nombre in (("pico", "Pico"), ("valle", "Valle")):
        macro(f"WAPE{nombre}", num(g(pr, "pico_valle", franja, "cand", "wape") or g(pr, "pico_valle", franja, "activo_wape")), f)
    for ruta, nombre in (("SILENCIO", "Silencio"), ("CRA 54", "Cra"), ("CL 72", "Cl")):
        macro(f"WAPERuta{nombre}", num(g(pr, "por_ruta", ruta, "cand", "wape")), f)
        macro(f"WAPERuta{nombre}Buno", num(g(pr, "por_ruta", ruta, "b1", "wape")), f)
    for anio, nombre in (("2024", "Dosmilveinticuatro"), ("2025", "Dosmilveinticinco")):
        rob = g(e, "robustez", anio) or {}
        macro(f"Rob{nombre}", num(g(rob, "global", "cand", "wape")), f)
        ic = g(rob, "bootstrap", "cand", "ic95") or [None, None]
        macro(f"Rob{nombre}IC", f"{num(ic[0])}--{num(ic[1])}", f)
        macro(f"Rob{nombre}Buno", num(g(rob, "global", "b1", "wape")), f)
    cifras_candidato()
    return e


def cifras_candidato():
    """El candidato fv3, registrado sin activar: su id, su prueba reservada (informativa) y los dos años congelados
    frente al activo, con el IC95 de la diferencia y los meses en que mejora (candidato_fv3/evaluacion_modelo.json)."""
    e = leer_json("candidato")
    f = FUENTES["candidato"]
    pr = g(e, "prueba_reservada") or {}
    macro("ModeloCand", str(g(pr, "modelos", "activo", defecto="s. d.")).replace("_", "\\_"), f)
    macro("WAPEcand", num(g(pr, "global", "cand", "wape")), f)
    ic = g(pr, "bootstrap", "cand", "ic95") or [None, None]
    macro("WAPEcandIC", f"{num(ic[0])}--{num(ic[1])}", f)
    for anio, nombre in (("2024", "Dosmilveinticuatro"), ("2025", "Dosmilveinticinco")):
        rob = g(e, "robustez", anio) or {}
        macro(f"RobCand{nombre}", num(g(rob, "global", "cand", "wape")), f)
        d = g(rob, "bootstrap", "cand_menos_anterior", "ic95") or [None, None]
        macro(f"RobCand{nombre}DifIC", f"{num(d[0])} a {num(d[1])}", f)
        macro(f"RobCand{nombre}Meses", num(g(rob, "meses_cand_mejor_que_anterior"), 0), f)


def cifras_calibracion():
    """Calibración conformal versionada vigente (v2) frente a la v1, en la prueba reservada."""
    p = EVID / "modelo" / "calibracion_condicional.json"
    c = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not c:
        avisos.append(f"falta {rel(p)}")
    for version, nombre in (("v2", "Vdos"), ("v1", "Vuno")):
        glob = g(c, "resultados", "prueba", version, "global") or {}
        macro(f"Cob{nombre}", num(glob.get("cobertura_pct")), p)
        macro(f"BajoPdiez{nombre}", num(glob.get("bajo_p10_pct")), p)
        macro(f"SobrePnoventa{nombre}", num(glob.get("sobre_p90_pct")), p)
        macro(f"Ancho{nombre}", num(glob.get("ancho_medio"), 1), p)
    elegida = next((d for d in (c.get("decision") or []) if d.get("candidata") == c.get("adoptada")), {})
    macro("CalibPeorDesv", num(elegida.get("peor_desviacion_pp")), p)


def cifras_horizontes():
    p = EVID / "modelo" / "horizontes.json"
    h = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not h:
        avisos.append(f"falta {rel(p)}")
    for clave, nombre, mod, base in (("h30", "Treinta", "modelo_con_nowcast_perfil", "b1_perfil"),
                                     ("h60", "Sesenta", "modelo_con_nowcast", "b1"),
                                     ("h120", "Cientoveinte", "modelo_con_nowcast", "b1")):
        macro(f"Hor{nombre}", num(g(h, clave, mod)), p)
        macro(f"Hor{nombre}Buno", num(g(h, clave, base)), p)
    macro("HorEvaluado", str(h.get("evaluado", "s. d.")), p)


def cifras_alertas():
    a = leer_json("alertas")
    f = FUENTES["alertas"]
    # La comparación antes/después es sobre las mismas familias (ALT-005 a ALT-009); el total observado suma además
    # ALT-002 observada y las rupturas (RF-009), si el backtest las trae.
    def obs(clave):
        return g(a, clave, "observadas_por_ruta_dia_005_009") or g(a, clave, "observadas_por_ruta_dia")
    macro("AlertasAhora", num(obs("por_defecto"), 2), f)
    macro("AlertasAntes", num(obs("reglas_anteriores"), 2), f)
    macro("AlertasObsTodas", num(g(a, "por_defecto", "observadas_por_ruta_dia"), 2), f)
    macro("DiasRuta", num(g(a, "por_defecto", "dias_ruta"), 0), f)
    per = g(a, "periodo") or ["s. d.", "s. d."]
    macro("AlertasDesde", str(per[0]), f)
    macro("AlertasHasta", str(per[-1]), f)
    for cod, nombre in (("ALT-005", "Cinco"), ("ALT-006", "Seis"), ("ALT-007", "Siete"), ("ALT-008", "Ocho")):
        macro(f"Lift{nombre}", num(g(a, "por_defecto", "por_codigo", cod, "lift")), f)
        macro(f"LiftAntes{nombre}", num(g(a, "reglas_anteriores", "por_codigo", cod, "lift")), f)
        macro(f"Prec{nombre}", num(g(a, "por_defecto", "por_codigo", cod, "precision_proxy"), 2), f)
    # Umbrales vigentes con los que corrió el backtest (los mismos de threshold_config)
    u = g(a, "umbrales_por_defecto") or {}
    for clave, nombre, dec in (("ocupacion_critica", "UOcupCritica", 2), ("baja_utilizacion", "UBajaUtil", 2),
                               ("caida_demanda", "UCaida", 2), ("persistencia_horas", "UPersistencia", 0),
                               ("error_pronostico", "UErrorPron", 2), ("z_anomalia", "UZ", 1),
                               ("tolerancia_despacho_min", "UTolDespacho", 0), ("tolerancia_salidas", "UTolSalidas", 2),
                               ("periodos_atraso", "UAtraso", 0), ("wape_max", "UWapeMax", 2),
                               ("semanas_referencia", "USemanasRef", 0)):
        macro(nombre, num(u.get(clave), dec), f)
    tol = u.get("tolerancia_salidas")
    macro("UTolSalidasPct", num(100 * tol, 0) if tol is not None else "s.\\,d.", f)
    caida = u.get("caida_demanda")
    macro("UUnoMenosCaida", num(1 - caida, 2) if caida is not None else "s.\\,d.", f)
    b = leer_json("alertas2024")
    macro("AlertasAhoraDosmil", num(g(b, "por_defecto", "observadas_por_ruta_dia"), 2), FUENTES["alertas2024"])
    macro("AlertasAntesDosmil", num(g(b, "reglas_anteriores", "observadas_por_ruta_dia"), 2), FUENTES["alertas2024"])
    # Alertas de pronóstico (ALT-001 a ALT-004) del backtest del ciclo diario: con las observadas dan el volumen total
    # que vería el despachador (§18 «alertas excesivas»).
    fp = FUENTES["alertas_pron"]
    p = leer_json("alertas_pron")
    por_codigo = (g(p, "por_codigo") or g(p, "ahora", "por_codigo") or g(p, "variantes", "franja", "por_codigo")
                  or {})
    pron = {c: g(por_codigo, c, "por_ruta_dia") for c in ("ALT-001", "ALT-002", "ALT-003", "ALT-004")}
    if None in pron.values():
        avisos.append(f"{rel(fp)} sin las alertas de pronóstico por ruta y día")
    for cod, nombre in (("ALT-001", "Uno"), ("ALT-002", "Dos"), ("ALT-003", "Tres"), ("ALT-004", "Cuatro")):
        macro(f"AlertasPron{nombre}", num(pron[cod], 2), fp)
    obs = g(a, "por_defecto", "observadas_por_ruta_dia")                 # todas las observadas
    suma = None if None in pron.values() else sum(pron.values())
    macro("AlertasPronostico", num(suma, 2), fp)
    macro("AlertasTotal", num(None if suma is None or obs is None else suma + obs, 2), fp)
    macro("ViablesBacktest", num(g(p, "recomendaciones_viables_pct"), 1), fp)
    # Mínimo de probabilidad de ALT-003 con que corrió el backtest (alt003_probabilidad_minima, migración 0014)
    macro("UProbMinTres", num(g(p, "alt003_probabilidad_minima"), 2), fp)
    # Muestra etiquetada dos veces (§18 «etiquetas incorrectas»): el kappa global entre los dos revisores antes de
    # conciliar (conciliacion.json, acuerdo_antes_de_conciliar.global.kappa, la cifra del README y de la matriz). Si
    # no está ahí, el primero que se encuentre en los JSON de la carpeta.
    carpeta = EVID / "alertas" / "revision_doble"
    kappa, origen = None, carpeta
    conciliacion = carpeta / "conciliacion.json"
    if conciliacion.exists():
        try:
            k = g(json.loads(conciliacion.read_text(encoding="utf-8")), "acuerdo_antes_de_conciliar", "global",
                  "kappa")
        except ValueError:
            k = None
        if isinstance(k, (int, float)):
            kappa, origen = k, conciliacion
    for q in sorted(carpeta.glob("*.json")) if carpeta.exists() and kappa is None else []:
        try:
            pila = [json.loads(q.read_text(encoding="utf-8"))]
        except ValueError:
            continue
        while pila and kappa is None:
            o = pila.pop()
            if isinstance(o, dict):
                for k, v in o.items():
                    if re.fullmatch(r"(?i)kappa(_cohen)?(_global)?", k) and isinstance(v, (int, float)):
                        kappa, origen = v, q
                        break
                    pila.append(v)
            elif isinstance(o, list):
                pila.extend(o)
    macro("RevisionDoble", "dos revisores automatizados con un protocolo escrito"
          + (f", conciliación y kappa de Cohen de {num(kappa, 2)}" if kappa is not None else ""), origen)
    return a


def cifras_k6():
    k = leer_json("k6")
    f = FUENTES["k6"]
    m = g(k, "metrics") or {}
    macro("Kpnoventaycinco", num(g(m, "http_req_duration", "p(95)"), 0), f)
    macro("Kpnoventaynueve", num(g(m, "http_req_duration", "p(99)"), 0), f)
    macro("Kpeticiones", num(g(m, "http_reqs", "count"), 0), f)
    macro("Ktasa", num(g(m, "http_reqs", "rate"), 1), f)
    fallos = g(m, "http_req_failed", "value")
    macro("Kerrores", num(100 * fallos, 2) if fallos is not None else "s.\\,d.", f)
    macro("Kvus", num(g(m, "vus_max", "max") or g(m, "vus_max", "value"), 0), f)
    ki = leer_json("k6ingesta")
    mi = g(ki, "metrics") or {}
    p95 = None
    for nombre, val in mi.items():
        if nombre.startswith("http_req_duration{") and "ingesta" in nombre and "sin" not in nombre:
            p95 = g(val, "p(95)")
    macro("Kingesta", num(p95, 0), FUENTES["k6ingesta"])
    return k


def _leer(p: Path) -> dict:
    """JSON de una evidencia; {} y un aviso si falta o no es JSON válido."""
    if not p.exists():
        avisos.append(f"falta {rel(p)}")
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        avisos.append(f"{rel(p)} no es JSON válido")
        return {}


def cifras_segmentos():
    """Capa de segmentos materializada (migración 0008), modelo por segmento y sentido, foto de variables por segmento
    y partición por ruta (migración 0009). La carga con k6 es la medición vigente (pruebas/k6_segmentos_*.json), la
    misma que citan la matriz y el README; el «antes» es la medición con la agregación en cada petición
    (pruebas/k6_volumen.txt)."""
    p = EVID / "pruebas" / "k6_segmentos_resumen.json"
    r = _leer(p)
    est = g(r, "en_frio", "rutas", "segmentos_estadisticas") or {}
    frio, caliente = (est.get("frio") or [None, None])[-1], (est.get("caliente") or [None, None])[-1]
    macro("SegFrio", num(frio, 1), p)
    macro("SegCaliente", num(caliente, 1), p)
    macro("SegCarga", num(g(r, "segmentos", "p95", "http_req_duration{tipo:consulta}"), 1), p)
    pt = p.parent / "k6_segmentos.txt"
    t = pt.read_text(encoding="utf-8", errors="replace") if pt.exists() else ""
    m = re.search(r"MIENTRAS corre un refresco completo.*?rampa [\d >-]*?(\d+) usuarios", t, flags=re.DOTALL)
    macro("SegCargaUsuarios", m.group(1) if m else "s.\\,d.", pt)
    pc = p.parent / "k6_segmentos_carga.json"
    fallos = g(_leer(pc), "metrics", "http_req_failed", "value")
    macro("SegCargaErrores", num(100 * fallos, 2) if fallos is not None else "s.\\,d.", pc)
    pv = EVID / "pruebas" / "k6_volumen.txt"
    tv = pv.read_text(encoding="utf-8", errors="replace") if pv.exists() else ""
    m = re.search(r"GET /api/v1/segmentos/estadisticas\?limite=50\s+\d+\s+([\d.]+)\s+([\d.]+)", tv)
    macro("SegAntesFrio", num(float(m.group(1)) / 1000, 1) if m else "s.\\,d.", pv)
    macro("SegAntesCaliente", num(float(m.group(2)) / 1000, 1) if m else "s.\\,d.", pv)
    if not (frio and m):
        avisos.append("sin las cifras de GET /segmentos/estadisticas (antes o después de la agregación)")
    # Modelo por segmento y sentido: la prueba única del protocolo (modelo/segmentos_modelo.json) y el IC95 de la
    # diferencia con el reparto fijo B0 (modelo/segmentos_banda_ventanas.json).
    pm = EVID / "modelo" / "segmentos_modelo.json"
    s = _leer(pm)
    cand = g(s, "activacion", "activo_candidato") or "M4"
    macro("SegModeloActivo", str(g(s, "activacion", "activo", defecto="s. d.")).replace("_", "\\_"), pm)
    prueba = str(g(s, "particion", "prueba", defecto="s. d. a s. d.")).split(" a ")
    macro("SegPruebaDesde", prueba[0], pm)
    macro("SegPruebaHasta", prueba[-1], pm)
    macro("SegWAPEact", num(g(s, "prueba", "metricas", cand, "wape_segmento_hora")), pm)
    macro("SegWAPEbcero", num(g(s, "prueba", "metricas", "B0", "wape_segmento_hora")), pm)
    macro("SegCobSegmento", num(g(s, "prueba", cand, "banda_total_real", "segmento", "cobertura_pct")), pm)
    macro("SegCobSentido", num(g(s, "prueba", cand, "banda_total_real", "sentido", "cobertura_pct")), pm)
    pb = EVID / "modelo" / "segmentos_banda_ventanas.json"
    ic = g(_leer(pb), "ic95_prueba_wape_segmento_hora_vs_B0", "ic95_pp") or [None, None]
    macro("SegDifIC", f"{num(ic[0])} a {num(ic[-1])}", pb)
    # Foto de variables por segmento y sentido de una ejecución (§7.3 paso 4).
    pf = EVID / "monitoreo" / "foto_segmentos.json"
    f = _leer(pf)
    macro("FotoFilasSegmento", num(f.get("filas_segmento"), 0), pf)
    b = f.get("bytes_datos_segmento")
    macro("FotoMBEjecucion", num(b / 1e6, 2) if b is not None else "s.\\,d.", pf)
    macro("FotoMBMes", num(f.get("megabytes_mes_una_ejecucion_diaria"), 0), pf)
    # Partición por ruta con dos réplicas reales (RNF-005).
    pr = EVID / "cola" / "replicas_por_ruta.json"
    rr = _leer(pr)
    macro("ParticionTrabajos", num(rr.get("trabajos"), 0), pr)
    macro("ParticionPares", num(rr.get("pares_cruzados"), 0), pr)
    macro("ParticionMismaRuta", num(rr.get("pares_misma_ruta"), 0), pr)
    macro("ParticionRelojPartida", num(rr.get("reloj_lote_s"), 1), pr)
    macro("ParticionRelojSinPartir", num(rr.get("reloj_lote_sin_partir_s"), 1), pr)
    # Refresco incremental sin filas nuevas con las huellas de la ventana de solape (migración 0012, RNF-004): lo que
    # relee y escribe sin huellas comparables (como cada ciclo hasta la 0011) y con ellas.
    psc = EVID / "pruebas" / "segmentos_sin_cambios.json"
    sc = _leer(psc)
    macro("SegSinCambiosFechasAntes", num(g(sc, "antes_sin_huellas", "fechas_releidas"), 0), psc)
    macro("SegSinCambiosFilasAntes", num(g(sc, "antes_sin_huellas", "filas_leidas"), 0), psc)
    macro("SegSinCambiosFechas", num(g(sc, "ahora_con_huellas", "fechas_releidas"), 0), psc)
    escritas = g(sc, "ahora_con_huellas", "versiones_de_fila_escritas_o_quitadas") or {}
    macro("SegSinCambiosEscritas", num(sum(escritas.values()), 0) if escritas else "s.\\,d.", psc)


def cifras_ocupacion():
    """Ocupación por segmento (§10.1, migración 0011): la validación del método contra la ocupación máxima del
    dispositivo en los mismos viajes (ocupacion/perfil_ocupacion_segmentos.json) y el efecto de la restricción
    reactiva con datos reales de ene.-feb. 2023 (ocupacion/backtest_restriccion_reactiva.json)."""
    pp = EVID / "ocupacion" / "perfil_ocupacion_segmentos.json"
    p = _leer(pp)
    macro("OcupViajesPerfil", num(g(p, "viajes", "en_perfil"), 0), pp)
    macro("OcupCorrelacion", num(g(p, "validacion", "acotada_en_cada_segmento", "correlacion"), 3), pp)
    macro("OcupViajesValidacion", num(g(p, "validacion", "acotada_en_cada_segmento", "viajes"), 0), pp)
    pb = EVID / "ocupacion" / "backtest_restriccion_reactiva.json"
    b = _leer(pb)
    op = g(b, "frente_a_la_operacion") or {}
    macro("OcupDisparos", num(op.get("disparos"), 0), pb)
    persistencia, base = op.get("persistencia_hora_siguiente_sobre_umbral_si_dispara"), op.get(
        "tasa_base_hora_siguiente_sobre_umbral")
    macro("OcupPersistencia", num(100 * persistencia, 1) if persistencia is not None else "s.\\,d.", pb)
    macro("OcupTasaBase", num(100 * base, 1) if base is not None else "s.\\,d.", pb)
    macro("OcupSalidasAgregadas", num(op.get("salidas_agregadas"), 0), pb)
    macro("OcupSalidasSinFalta", num(op.get("salidas_agregadas_donde_no_hacia_falta"), 0), pb)
    corte = (g(b, "frente_al_tiempo_real", "cortes") or [{}])[0]
    macro("OcupCorteTiempoReal", str(corte.get("corte", "s. d.")), pb)
    macro("OcupDisparosTiempoReal", num(corte.get("de_esos_disparan_en_tiempo_real"), 0), pb)


def cifras_retencion():
    """Retención automática (§18, migración 0012): los meses en caliente de la política con que corrió la evidencia
    (retencion/corrida_aplicada.json, los mismos que siembra la migración)."""
    pr = EVID / "retencion" / "corrida_aplicada.json"
    r = _leer(pr)
    macro("RetencionMeses", num(g(r, "politica", "retencion_meses_foto"), 0), pr)


def _pct(x, dec=1) -> str:
    """Fracción de la evidencia (0,0139) en por ciento con la regla de num() (1,4); «s. d.» si falta."""
    return num(Decimal(str(x)) * 100, dec) if isinstance(x, (int, float)) else "s.\\,d."


def cifras_consolidados():
    """Consolidados de Extreme en el ciclo (migración 0013): lectura incremental, calidad y contraste de
    timbradas_consolidado con la agregación propia en la réplica, y las tablas por segmento sin filas de Sobusa (H4)
    (consolidados/contraste_consolidados.json); por qué el histórico guarda bajadas_viajes
    (consolidados/definicion_bajadas.json)."""
    pc = EVID / "consolidados" / "contraste_consolidados.json"
    c = _leer(pc)
    ruta = g(c, "ruta") or {}
    contraste = ruta.get("contraste") or {}
    macro("ConsFilas", num(ruta.get("filas"), 0), pc)
    macro("ConsValidas", num(g(ruta, "calidad", "validas"), 0), pc)
    macro("ConsDescartadasHuella", num(g(ruta, "segunda_lectura_con_huellas", "repetidas_solape"), 0), pc)
    macro("ConsLlaves", num(contraste.get("llaves"), 0), pc)
    macro("ConsComparadas", num(contraste.get("comparadas"), 0), pc)
    macro("ConsIncidencias", num(contraste.get("diferencias"), 0), pc)
    macro("ConsGroseras", num(contraste.get("groseras"), 0), pc)
    tol = contraste.get("tolerancias") or {}
    macro("ConsTolerancia", _pct(tol.get("contraste_tolerancia"), 0), pc)
    macro("ConsTolGrosera", _pct(tol.get("contraste_tolerancia_grosera"), 0), pc)
    macro("ConsMedianaSubidas", _pct(g(ruta, "distribucion_diferencias", "promedio_subidas", "mediana")), pc)
    # Bajadas de CL 72 (id_ruta 21) en el consolidado frente a las del histórico propio (H17)
    cl72 = g(ruta, "totales_por_ruta", "21") or {}
    ext, propia = cl72.get("bajadas_extreme"), cl72.get("bajadas_propia")
    macro("ConsBajadasClDif", _pct(ext / propia - 1, 0) if ext and propia else "s.\\,d.", pc)
    seg = g(c, "segmentos") or {}
    filas_seg = [g(seg, tabla, "filas_del_proceso")
                 for tabla in ("timbradas_segmentos_anio", "timbradas_segmentos_consolidado")]
    macro("ConsFilasSegmentos", num(sum(filas_seg), 0) if None not in filas_seg else "s.\\,d.", pc)
    pb = EVID / "consolidados" / "definicion_bajadas.json"
    total = g(_leer(pb), "total") or {}
    macro("BajadasDifMismos", _pct(total.get("diferencia_mismos_viajes")), pb)
    macro("BajadasDifTotal", _pct(total.get("diferencia_total")), pb)
    if not ruta or not total:
        avisos.append("sin las cifras de los consolidados (consolidados/contraste_consolidados.json o "
                      "definicion_bajadas.json)")


def cifras_rendimiento():
    p = FUENTES["rendimiento"]
    t = p.read_text(encoding="utf-8") if p.exists() else ""
    m = re.search(r"Lote: ([\d,]+) filas", t)
    macro("IngestaFilas", num(int(m.group(1).replace(",", "")), 0) if m else "s.\\,d.", p)
    m = re.search(r"ingesta \(COPY \+ upsert\)\s+([\d.]+) s\s+->\s+([\d,]+) filas/s", t)
    macro("IngestaSegundos", num(float(m.group(1)), 2) if m else "s.\\,d.", p)
    macro("IngestaTasa", num(int(m.group(2).replace(",", "")), 0) if m else "s.\\,d.", p)
    m = re.search(r"Memoria pico: tracemalloc (\d+) MiB", t)
    macro("IngestaMemoria", m.group(1) if m else "s.\\,d.", p)
    if not m:
        avisos.append("rendimiento.txt sin las cifras de ingesta esperadas")


def _casos(junit: Path):
    """(nivel, nombre de la prueba, estado) de cada caso de un JUnit; estado: ok, falla u omitida."""
    raiz = ET.parse(junit).getroot()
    for tc in raiz.iter("testcase"):
        partes = tc.get("classname", "").split(".")
        nivel = partes[1] if len(partes) > 1 and partes[0] == "tests" else partes[0]
        if tc.find("failure") is not None or tc.find("error") is not None:
            estado = "falla"
        elif tc.find("skipped") is not None:
            estado = "omitida"
        else:
            estado = "ok"
        yield nivel, tc.get("name", ""), estado


def _intentos_de_escritura():
    """Intentos de escritura indebida en la réplica (§11.3), contados por caso aprobado del JUnit: lector_ia (16 tipos
    de sentencia en dos modos de sesión) y escritor_ia (sentencias sobre las 14 tablas de Extreme). Si la corrida
    elegida no tuvo la réplica (en GitHub se omite), se cuentan en la última corrida completa con réplica."""
    patrones = {"lector": r"^test_lector_no_escribe_", "escritor": r"^test_escritor_ia_no_puede_escribir_ni_alterar"}
    for junit in (JUNIT, RESPALDO_PRUEBAS):
        if not junit.exists():
            continue
        cuenta = Counter()
        for nivel, nombre, estado in _casos(junit):
            for clave, patron in patrones.items():
                if nivel == "replica" and estado == "ok" and re.match(patron, nombre):
                    cuenta[clave] += 1
        if cuenta["lector"] and cuenta["escritor"]:
            return cuenta, junit
    return Counter(), JUNIT


def cifras_pruebas():
    if not JUNIT.exists():
        avisos.append(f"falta {rel(JUNIT)}")
        return {}
    if not JUNIT_ES_FINAL:
        avisos.append(f"no existe {rel(EVIDENCIA_PRUEBAS)}: los documentos citan {rel(JUNIT)} (última corrida completa)")
    total, fallas, omitidas = Counter(), Counter(), Counter()
    for nivel, _nombre, estado in _casos(JUNIT):
        total[nivel] += 1
        if estado == "falla":
            fallas[nivel] += 1
        elif estado == "omitida":
            omitidas[nivel] += 1
    n, nf, ns = sum(total.values()), sum(fallas.values()), sum(omitidas.values())
    macro("Ntotal", num(n, 0), JUNIT)
    macro("Npasan", num(n - nf - ns, 0), JUNIT)
    macro("Nfallan", num(nf, 0), JUNIT)
    macro("Nomitidas", num(ns, 0), JUNIT)
    for nivel, nombre in (("unit", "Unit"), ("integracion", "Integ"), ("replica", "Replica"), ("contrato", "Contrato"),
                          ("datos_ml", "Datos")):
        macro(f"N{nombre}", num(total.get(nivel, 0), 0), JUNIT)
    # Testcontainers necesita Docker y corre en su propio trabajo del CI: si la corrida elegida no lo trae, se cuenta
    # en la corrida del CI (pruebas/ci/pytest.xml) y el texto lo dice.
    ci_junit = EVID / "pruebas" / "ci" / "pytest.xml"
    tcont, fuente_tc, nota_tc = total.get("testcontainers", 0), JUNIT, ""
    if not tcont and ci_junit.exists():
        tcont = sum(1 for nivel, _n, estado in _casos(ci_junit) if nivel == "testcontainers" and estado == "ok")
        fuente_tc, nota_tc = ci_junit, " (en su trabajo del CI)"
    macro("NTcont", num(tcont, 0), fuente_tc)
    macro("NTcontNota", nota_tc, fuente_tc)
    total_fig = Counter(total)
    total_fig["testcontainers"] = tcont
    raiz = ET.parse(JUNIT).getroot()
    ts = raiz if raiz.tag == "testsuite" else raiz.find("testsuite")
    fecha = (ts.get("timestamp", "") if ts is not None else "")[:16].replace("T", " ")
    macro("FechaPruebas", fecha or "s.\\,d.", JUNIT)
    # Qué corrida es: la final o la última completa versionada (el texto lo dice, sin «s. d.»).
    if JUNIT_ES_FINAL:
        macro("CorridaPruebas", f"corrida final de la suite completa ({fecha})", JUNIT)
    else:
        macro("CorridaPruebas", f"última corrida completa versionada ({fecha}; la corrida final se publica en "
              f"\\path{{{rel(EVIDENCIA_PRUEBAS)}}})", JUNIT)
    if COBERTURA.exists():
        c = ET.parse(COBERTURA).getroot()
        macro("Cobertura", num(100 * float(c.get("line-rate", 0)), 1), COBERTURA)
        if not COBERTURA_ES_FINAL:
            avisos.append(f"no existe {rel(EVIDENCIA_COBERTURA)}: la cobertura sale de {rel(COBERTURA)}")
    else:
        avisos.append(f"falta {rel(COBERTURA)}")
        macro("Cobertura", "s.\\,d.", COBERTURA)
    intentos, origen = _intentos_de_escritura()
    if not intentos:
        avisos.append("ningún JUnit trae los intentos de escritura de tests/replica")
    macro("NIntentosLector", num(intentos.get("lector"), 0) if intentos else "s.\\,d.", origen)
    macro("NIntentosEscritor", num(intentos.get("escritor"), 0) if intentos else "s.\\,d.", origen)
    macro("NIntentosTotal", num(sum(intentos.values()), 0) if intentos else "s.\\,d.", origen)
    macro("FuenteIntentos", f"\\path{{{rel(origen)}}}", origen)
    return {"total": total_fig, "fallas": fallas, "omitidas": omitidas}


def estado_ci():
    """Línea del estado de la integración continua: la primera línea no vacía de pruebas/ci_github.txt (la escribe
    quien integra después del run real en GitHub Actions); si no existe, el flujo está reproducido en local."""
    if CI_GITHUB.exists():
        linea = next((x.strip() for x in CI_GITHUB.read_text(encoding="utf-8", errors="replace").splitlines()
                      if x.strip()), "")
        linea = linea.lstrip("#").strip()
        if linea:
            corta = linea if len(linea) <= 60 else linea[:58].rsplit(" ", 1)[0] + "…"   # E01 tiene una línea libre
            macro("EstadoCI", latex_de_md(linea[:160]), CI_GITHUB)
            macro("EstadoCICorto", latex_de_md(corta), CI_GITHUB)
            return
    macro("EstadoCI", "reproducida en local con \\path{scripts/ci_local.py} (\\path{pruebas/ci_local.txt}); "
          "el run de GitHub Actions se agrega en \\path{pruebas/ci_github.txt}", EVID / "pruebas" / "ci_local.txt")
    macro("EstadoCICorto", "reproducida en local", EVID / "pruebas" / "ci_local.txt")


# --- Texto de los Markdown de la entrega (PLAN_EVOLUCION.md, hallazgos) ---------------------------------------------
def latex_de_md(t: str) -> str:
    """Texto en línea de Markdown a LaTeX: escapa los especiales, `código` -> \\texttt, **negrita** -> \\textbf y quita
    los enlaces. Los rangos «3-6» quedan con raya corta."""
    partes = re.split(r"(`[^`]*`)", t)
    salida = []
    for p in partes:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            salida.append("\\path{" + p[1:-1].replace("{", "").replace("}", "") + "}")
            continue
        p = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", p)
        for a, b in (("\\", "\\textbackslash{}"), ("&", "\\&"), ("%", "\\%"), ("$", "\\$"), ("#", "\\#"),
                     ("_", "\\_"), ("{", "\\{"), ("}", "\\}")):
            p = p.replace(a, b)
        p = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", p)
        p = p.replace("~", "\\textasciitilde{}").replace("≤", "\\ensuremath{\\le}").replace("≥", "\\ensuremath{\\ge}")
        salida.append(p)
    return "".join(salida).strip()


def _filas_md(texto: str, encabezado: str) -> list[list[str]]:
    """Filas de la primera tabla Markdown que sigue al encabezado dado (líneas «| … |»)."""
    m = re.search(r"^#+ .*" + re.escape(encabezado) + r".*$", texto, flags=re.MULTILINE)
    if not m:
        return []
    filas, dentro = [], False
    for linea in texto[m.end():].splitlines():
        if linea.startswith("|"):
            dentro = True
            celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", c) for c in celdas):
                filas.append(celdas)
        elif dentro or linea.startswith("#"):
            break
    return filas[1:]                                            # sin la fila de encabezado


def _semanas(celda: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d+)\s*(?:[-–]\s*(\d+))?", celda.replace("*", "").strip())
    return (int(m.group(1)), int(m.group(2) or m.group(1))) if m else None


def cifras_plan():
    """Calendario, criterio de salida del modo sombra y costos: una sola fuente, PLAN_EVOLUCION.md (§1.1 y §3.1)."""
    t = PLAN_EVOLUCION.read_text(encoding="utf-8") if PLAN_EVOLUCION.exists() else ""
    if not t:
        avisos.append(f"falta {rel(PLAN_EVOLUCION)}")
    pasos = _filas_md(t, "1.1")
    sombra = next((f for f in pasos if len(f) >= 4 and re.search(r"(?i)modo sombra", f[1])), None)
    piloto = next((f for f in pasos if len(f) >= 4 and re.search(r"(?i)piloto", f[1])), None)
    s, p = (_semanas(sombra[0]) if sombra else None), (_semanas(piloto[0]) if piloto else None)
    if not (s and p):
        avisos.append("PLAN_EVOLUCION.md §1.1 sin las filas «Modo sombra» y «Piloto» con sus semanas")

    def rango(a, b):
        return f"{a}" if a == b else f"{a}--{b}"
    macro("PlanSemanasConexion", rango(1, s[0] - 1) if s and s[0] > 1 else "s.\\,d.", PLAN_EVOLUCION)
    macro("PlanSemanasSombra", rango(*s) if s else "s.\\,d.", PLAN_EVOLUCION)
    macro("PlanSemanasPiloto", rango(*p) if p else "s.\\,d.", PLAN_EVOLUCION)
    macro("PlanSemanasSombraTexto", (f"las semanas {s[0]} a {s[1]}" if s else "s.\\,d."), PLAN_EVOLUCION)
    macro("PlanSemanasPilotoTexto", (f"las semanas {p[0]} a {p[1]}" if p else "s.\\,d."), PLAN_EVOLUCION)
    # Hallazgos más urgentes (fila de la semana 1 de §1.1): «Las más urgentes son H3 (...), H6 (...) ... y H14 (...)».
    urgentes = next((re.findall(r"\bH(\d+)\b", m.group(1)) for f in pasos
                     for m in [re.search(r"(?i)más urgentes son (.*?)\.\s*(?:\||$)", f[1])] if m), [])
    codigos = [f"H{u}" for u in urgentes]
    macro("PlanHallazgosUrgentes", (", ".join(codigos[:-1]) + " y " + codigos[-1]) if len(codigos) > 1
          else (codigos[0] if codigos else "s.\\,d."), PLAN_EVOLUCION)
    # Criterio de salida del modo sombra: las metas de WAPE por horizonte de la tabla de §6.3 y el tope de alertas
    # descartadas de la fila «Modo sombra» de §1.1. Si §6.3 no trae la tabla, se usa el texto de la celda de §1.1.
    celda = sombra[3] if sombra else ""
    metas = []
    for f in _filas_md(t, "6.3"):
        h = re.match(r"\s*(\d+)\s*min", f[0]) if f else None
        meta = next((c for c in f[1:] if re.fullmatch(r"[≤<]\s*\d+(?:,\d+)?\s*%", c.strip())), None) if h else None
        if h and meta:
            metas.append((int(h.group(1)), meta.strip()))
    descartadas = re.search(r"<\s*(\d+)\s*%\s*de alertas descartadas", celda)
    if metas:
        orden = sorted(metas, key=lambda m: (m[0] != 60, m[0]))     # primero el de 60 min, el del plan
        partes = [f"{meta} a {h} min" for h, meta in orden]
        criterio = ("WAPE " + (", ".join(partes[:-1]) + " y " + partes[-1] if len(partes) > 1 else partes[0])
                    + ", y por debajo de B1, en las cuatro semanas"
                    + (f"; menos del {descartadas.group(1)} % de alertas descartadas" if descartadas else ""))
    else:
        criterio = re.sub(r"\s*\((?:sección|ver)[^)]*\)\s*\.?$", "", celda).rstrip(". ")
    macro("PlanCriterioSombra", latex_de_md(criterio) if criterio else "s.\\,d.", PLAN_EVOLUCION)
    costos = _filas_md(t, "3.1")

    def usd(patron):
        f = next((f for f in costos if len(f) >= 3 and re.search(patron, f[0])), None)
        return latex_de_md(f[2].replace("**", "")).replace("–", "--") if f else "s.\\,d."
    macro("PlanCostoComputo", usd(r"(?i)^cómputo"), PLAN_EVOLUCION)
    macro("PlanCostoBase", usd(r"(?i)^postgresql"), PLAN_EVOLUCION)
    macro("PlanCostoReplica", usd(r"(?i)^réplica"), PLAN_EVOLUCION)
    macro("PlanCostoTotalA", usd(r"(?i)total, escenario a"), PLAN_EVOLUCION)
    macro("PlanCostoTotalB", usd(r"(?i)total, escenario b"), PLAN_EVOLUCION)
    if any(v == "s.\\,d." for n, v, _ in macros if n.startswith("PlanCosto")):
        avisos.append("PLAN_EVOLUCION.md §3.1 sin alguna fila de costos esperada")


NUMEROS = {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho", 9: "nueve",
           10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince", 16: "dieciséis",
           17: "diecisiete", 18: "dieciocho", 19: "diecinueve", 20: "veinte"}


def cifras_hallazgos():
    """Rango vigente de hallazgos (H1 a Hn) de la tabla de docs/hallazgos_extreme.md."""
    t = HALLAZGOS.read_text(encoding="utf-8") if HALLAZGOS.exists() else ""
    ids = sorted({int(m.group(1)) for m in re.finditer(r"^\| H(\d+) \|", t, flags=re.MULTILINE)})
    if not ids:
        avisos.append(f"sin hallazgos en {rel(HALLAZGOS)}")
    n = ids[-1] if ids else None
    macro("HallazgosRango", f"H1--H{n}" if n else "s.\\,d.", HALLAZGOS)
    macro("NHallazgos", str(n) if n else "s.\\,d.", HALLAZGOS)
    macro("NHallazgosTexto", NUMEROS.get(n, str(n)) if n else "s.\\,d.", HALLAZGOS)


FRANJAS_RESPUESTA = (("pico mañana", "PicoManana"), ("valle", "Valle"), ("pico tarde", "PicoTarde"))


def _franja(rd: dict, nombre: str) -> dict:
    """Franja de resumen_despacho.por_franja cuyo nombre empieza por «pico mañana», «valle» o «pico tarde»: el
    headway de la franja = minutos operados / salidas (la misma definición de documentos/respuesta_pregunta_reto.md)."""
    return next((f for f in rd.get("por_franja") or [] if str(f.get("franja", "")).startswith(nombre)), {})


def _no_viables(r: dict) -> list[int]:
    horas = [int(h["hora"]) for h in r.get("cada_cuanto_despachar") or [] if h.get("viable") is False]
    if not horas:
        for f in (r.get("resumen_despacho") or {}).get("por_franja") or []:
            horas += [int(h) for h in f.get("horas_no_viables") or []]
    return sorted(set(horas))


def _texto_alerta(a: dict) -> str:
    texto = str(a.get("explicacion", ""))
    for x, y in (("\\", ""), ("%", "\\%"), ("_", "\\_"), ("&", "\\&"), ("#", "\\#"), ("$", "\\$")):
        texto = texto.replace(x, y)
    if len(texto) > 170:
        corte = texto[:170]
        fin = corte.rfind(". ")
        texto = corte[:fin + 1] if fin > 60 else corte.rsplit(" ", 1)[0] + "…"
    severidad = {"critica": "crítica"}.get(a.get("severidad"), a.get("severidad"))
    recomendacion = str(a.get("recomendacion", "")).rstrip(".").replace("%", "\\%").replace("_", "\\_")
    return f"{a.get('codigo')} {severidad}, «{texto}» Recomendación: {recomendacion}."


def respuesta_reto():
    """Tabla de la diapositiva «respuesta a la pregunta» y el ejemplo de E01, desde la evidencia de GET /api/v1/respuesta
    (docs/evidencias/respuesta/respuesta_<fecha>.json). Por omisión toma el día laboral, el mismo de la «respuesta
    corta» de documentos/respuesta_pregunta_reto.md; RESPUESTA_FECHA fija otro."""
    carpeta = EVID / "respuesta"
    archivos = sorted(carpeta.glob("respuesta_*.json")) if carpeta.exists() else []
    datos = []
    for p in archivos:
        try:
            datos.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except ValueError:
            avisos.append(f"{rel(p)} no es JSON válido")
    fecha = os.environ.get("RESPUESTA_FECHA")
    elegido = next(((p, d) for p, d in datos if fecha and fecha in p.name), None) \
        or next(((p, d) for p, d in datos if str(d.get("tipo_dia", "")).lower().startswith("laboral")), None) \
        or (datos[0] if datos else None)
    destino = GENERADO / "respuesta_tabla.tex"
    GENERADO.mkdir(exist_ok=True)
    if elegido is None:
        avisos.append("sin evidencia de GET /api/v1/respuesta en docs/evidencias/respuesta/")
        destino.write_text("\\newcommand{\\RespuestaDisponible}{0}\n", encoding="utf-8")
        return
    elegido, d = elegido
    filas, rutas = [], {r.get("ruta"): r for r in d.get("rutas", [])}
    for r in d.get("rutas", []):
        rd, pe, ve = r.get("resumen_despacho", {}), r.get("pasajeros_esperados", {}), r.get("vehiculos", {})
        fr = r.get("flota_y_recaudo", {})
        # Dos decimales, como las tablas de documentos/respuesta_pregunta_reto.md.
        hw = " / ".join(num(_franja(rd, n).get("headway_min"), 2) for n, _ in FRANJAS_RESPUESTA)
        hoy = " / ".join(num(_franja(rd, n).get("headway_actual_min"), 2) for n, _ in FRANJAS_RESPUESTA)
        nv = _no_viables(r)
        filas.append(
            f"{r.get('ruta')} & {num(rd.get('salidas_dia_recomendadas'), 0)} / {num(rd.get('salidas_dia_programadas'), 1)}"
            f" & {hw}\\newline\\textcolor{{rol-tinta-3}}{{hoy {hoy}}}"
            f" & {(', '.join(f'{h}~h' for h in nv)) if nv else 'ninguna'}"
            f" & {num(pe.get('dia'), 0)} ({num(pe.get('p10'), 0)}--{num(pe.get('p90'), 0)})"
            f" & {num(ve.get('requeridos_pico'), 0)} / {num(ve.get('flota_disponible'), 0)}"
            f" & {num((fr.get('recaudo_esperado_cop') or 0) / 1e6, 1)} / {num((fr.get('costo_operativo_cop') or 0) / 1e6, 1)}"
            " \\\\")
    tz = d.get("trazabilidad", {})
    no_viables_total = sum(len(_no_viables(r)) for r in d.get("rutas", []))
    horas_total = sum(len(r.get("cada_cuanto_despachar") or []) for r in d.get("rutas", []))
    lineas = [
        f"% Generado por documentos/datos_documentos.py desde {rel(elegido)}. No editar a mano.",
        "\\newcommand{\\RespuestaDisponible}{1}",
        f"\\newcommand{{\\RespuestaFecha}}{{{d.get('fecha', 's. d.')}}}",
        f"\\newcommand{{\\RespuestaTipoDia}}{{{d.get('tipo_dia', 's. d.')}}}",
        f"\\newcommand{{\\RespuestaModelo}}{{{str(tz.get('model_id', 's. d.')).replace('_', chr(92) + '_')}}}",
        f"\\newcommand{{\\RespuestaFuentePronostico}}{{{latex_de_md(str(tz.get('fuente_pronostico') or 'modelo activo')).replace('_', ' ')}}}",
        f"\\newcommand{{\\RespuestaFuente}}{{\\path{{{elegido.name}}}}}",
        f"\\newcommand{{\\RespuestaNoViables}}{{{no_viables_total}}}",
        f"\\newcommand{{\\RespuestaHoras}}{{{horas_total}}}",
        "\\newcommand{\\RespuestaFilas}{%",
        *filas,
        "}",
    ]
    # Ejemplo del despacho para E01: CRA 54 (la ruta más cargada) o la primera, con su headway por franja.
    ej = rutas.get("CRA 54") or (d.get("rutas") or [{}])[0]
    rd = ej.get("resumen_despacho", {})
    nv = _no_viables(ej)
    lineas += [
        f"\\newcommand{{\\RespEjRuta}}{{{ej.get('ruta', 's. d.')}}}",
        f"\\newcommand{{\\RespEjSalidas}}{{{num(rd.get('salidas_dia_recomendadas'), 0)}}}",
        f"\\newcommand{{\\RespEjProgramadas}}{{{num(rd.get('salidas_dia_programadas'), 1)}}}",
        *(f"\\newcommand{{\\RespEj{m}}}{{{num(_franja(rd, n).get('headway_min'), 2)}}}" for n, m in FRANJAS_RESPUESTA),
        "\\newcommand{\\RespEjNoViables}{" + ((("a las " + ", ".join(f"{h}~h" for h in nv)) +
                                                " la hora sale \\emph{no viable}, con su motivo y la mejor aproximación"
                                                " ejecutable") if nv else "todas las horas son viables") + "}",
    ]
    # Ejemplo de atención inmediata: la primera alerta (críticas primero) de la misma respuesta; si la evidencia sin
    # base no trae alertas, la de la llamada por HTTP del mismo día (api_respuesta_<RUTA>_<fecha>.json).
    ejemplo = None
    for r in sorted(d.get("rutas", []), key=lambda x: x.get("ruta") != ej.get("ruta")):   # primero la del ejemplo
        if (r.get("atencion_inmediata") or []) and ejemplo is None:
            ejemplo = (r.get("ruta"), r["atencion_inmediata"][0], elegido)
    for p in sorted(carpeta.glob(f"api_respuesta_*{d.get('fecha', '')}*.json")) if ejemplo is None else []:
        try:
            dv = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for r in dv.get("rutas", []):
            if (r.get("atencion_inmediata") or []) and ejemplo is None:
                ejemplo = (r.get("ruta"), r["atencion_inmediata"][0], p)
    if ejemplo:
        ruta, a, p = ejemplo
        lineas.append(f"\\newcommand{{\\RespuestaEjemplo}}{{{ruta}: {_texto_alerta(a)}}}")
        lineas.append(f"\\newcommand{{\\RespuestaEjemploFuente}}{{\\path{{{p.name}}}}}")
    else:
        avisos.append("sin un ejemplo de alerta en la evidencia de la respuesta")
        lineas.append("\\newcommand{\\RespuestaEjemplo}{s.\\,d.}")
        lineas.append("\\newcommand{\\RespuestaEjemploFuente}{}")
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def cifras_demo():
    """Ciclo de §14.2 contra la API desplegada (scripts/demo_ciclo_api.py): despliegue/demo_ciclo_api.txt."""
    p = EVID / "despliegue" / "demo_ciclo_api.txt"
    t = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    if not t:
        avisos.append(f"falta {rel(p)}")

    def busca(patron, grupo=1, defecto="s.\\,d."):
        m = re.search(patron, t, flags=re.DOTALL)
        return m.group(grupo) if m else defecto

    # Formato vigente de la lectura incremental: «<etapa> marca de agua A -> B: filas leídas N» (carga inicial, día
    # nuevo, días nuevos y repetición, en ese orden); el formato anterior era «filas leídas N, válidas M; marca A -> B».
    vigentes = re.findall(r"(carga inicial|día nuevo|días nuevos|repetición)\s+marca de agua (\S+) -> (\S+?): "
                          r"filas leídas (\d+)", t)
    if vigentes:
        por_etapa = {e: (int(n), a, b) for e, a, b, n in vigentes}
        filas = [por_etapa.get(e) for e in ("carga inicial", "día nuevo", "repetición")]
        filas = [(str(f[0]), f[1], f[2]) for f in filas if f is not None]
    else:
        filas = re.findall(r"filas leídas (\d+), válidas \d+; marca de agua (\S+) -> (\S+)", t)
    macro("DemoFilasInicial", num(int(filas[0][0]), 0) if len(filas) > 0 else "s.\\,d.", p)
    macro("DemoFilasNuevas", num(int(filas[1][0]), 0) if len(filas) > 1 else "s.\\,d.", p)
    macro("DemoFilasRepeticion", num(int(filas[2][0]), 0) if len(filas) > 2 else "s.\\,d.", p)
    macro("DemoMarcaAntes", filas[1][1][:10] if len(filas) > 1 else "s.\\,d.", p)
    macro("DemoMarcaDespues", filas[1][2][:10] if len(filas) > 1 else "s.\\,d.", p)
    w = busca(r"Modelo activo (?:sobre|en) lo recién llegado[^:]*: WAPE ([\d.]+) %")
    macro("DemoWapeNuevo", num(float(w), 1) if w[0].isdigit() else w, p)
    macro("DemoCandidato", busca(r"Candidato (\S+) registrado").replace("_", "\\_"), p)
    s = busca(r"entrenamiento ok en ([\d.]+) s")
    macro("DemoEntrenoSeg", num(float(s), 0) if s[0].isdigit() else s, p)
    wc = busca(r"candidato \S+: WAPE ([\d.]+) %")
    wa = busca(r"activo\s+\S+: WAPE ([\d.]+) %")
    macro("DemoWapeCand", num(float(wc), 2) if wc[0].isdigit() else wc, p)
    macro("DemoWapeAct", num(float(wa), 2) if wa[0].isdigit() else wa, p)
    ventana = busca(r"Misma ventana para los dos: (\d{4}-\d\d-\d\d \.\. \d{4}-\d\d-\d\d)")
    if not ventana[0].isdigit():
        ventana = busca(r"posterior al corte del candidato: (\S+ \.\. \S+)")
    macro("DemoVentana", ventana.replace(" .. ", " a "), p)
    decision = "rechazado" if "RECHAZADO" in t else ("activado" if re.search(r"ACTIVADO", t) else "s.\\,d.")
    macro("DemoDecision", decision, p)
    total = busca(r"Ciclo completo en (\d+) s")
    macro("DemoTotalSeg", total, p)


def cifras_sonar():
    """Resumen de SonarQube si su evidencia existe (respuestas JSON de la API web de SonarQube: measures y
    project_status). Sin evidencia, la macro lo dice: el texto nunca afirma un resultado que no está en disco."""
    carpeta = EVID / "sonarqube"
    medidas, estado, origen = {}, None, carpeta
    # Fuente principal: measures.json (las medidas del último análisis, con alert_status = estado de la puerta).
    principal = carpeta / "measures.json"
    if principal.exists():
        try:
            m = json.loads(principal.read_text(encoding="utf-8"))
            medidas = {k: v for k, v in (m.get("medidas") or {}).items() if v is not None}
            estado = medidas.get("alert_status")
            origen = principal
        except ValueError:
            avisos.append(f"{rel(principal)} no es JSON válido")
    for p in (sorted(carpeta.glob("**/*.json")) if carpeta.exists() and not medidas else []):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        pila = [d]
        while pila:
            o = pila.pop()
            if isinstance(o, dict):
                if "metric" in o and "value" in o and o["metric"] not in medidas:
                    medidas[o["metric"]] = o["value"]
                    origen = p
                if isinstance(o.get("projectStatus"), dict) and estado is None:
                    estado = o["projectStatus"].get("status")
                    origen = p
                pila.extend(o.values())
            elif isinstance(o, list):
                pila.extend(o)
    if not medidas and estado is None:
        avisos.append("sin evidencia de SonarQube en docs/evidencias/sonarqube/")
        macro("SonarResumen", "análisis de SonarQube: la evidencia se agrega en "
              "\\path{api_frecuencias/docs/evidencias/sonarqube/}", carpeta)
        macro("SonarCorto", "SonarQube: ver \\path{docs/evidencias/sonarqube/}", carpeta)
        return
    resumen = carpeta / "resumen.md"
    if estado is None and resumen.exists():
        m = re.search(r"Puerta de calidad[^\n]*\*\*(\w+)\*\*", resumen.read_text(encoding="utf-8"))
        estado = m.group(1) if m else None
    partes = []
    for metrica, texto in (("vulnerabilities", "vulnerabilidades"), ("bugs", "errores"),
                           ("blocker_violations", "bloqueantes"), ("critical_violations", "críticos"),
                           ("duplicated_lines_density", "duplicación")):
        if metrica in medidas:
            v = medidas[metrica]
            valor = f"{num(float(v), 1)}~\\%" if metrica == "duplicated_lines_density" else str(v)
            partes.append(f"{texto}: {valor}")
    puerta = ("puerta de calidad aprobada" if estado == "OK" else f"puerta de calidad en {estado}") if estado else ""
    if "coverage" in medidas or "line_coverage" in medidas:
        cob = medidas.get("coverage") or medidas.get("line_coverage")
        partes.append(f"cobertura: {num(float(cob), 1)}~\\%")
    macro("SonarResumen", "SonarQube: " + puerta + (" (" + "; ".join(partes) + ")" if partes else ""), origen)
    macro("SonarCorto", "SonarQube: " + puerta + (" (" + "; ".join(partes[:4]) + ")" if partes else ""), origen)
    macro("SonarPuerta", puerta or "s.\\,d.", origen)
    macro("SonarPruebas", num(float(medidas["tests"]), 0) if "tests" in medidas else "s.\\,d.", origen)


def cifras_optimizacion():
    p = EVID / "optimizacion" / "sensibilidad.md"
    filas = []
    if p.exists():
        for linea in p.read_text(encoding="utf-8").splitlines():
            if re.match(r"\| (SILENCIO|CRA 54|CL 72) \|", linea):
                filas.append([c.strip() for c in linea.strip("|").split("|")])
    else:
        avisos.append(f"falta {rel(p)}")
    macro("FranjasTotal", num(len(filas), 0), p)
    macro("FranjasViables", num(sum(1 for f in filas if f[5] == "sí"), 0), p)
    macro("FranjasMilpIgual", num(sum(1 for f in filas if f[-1] == "sí"), 0), p)
    no_viables = [f"{f[0]} ({f[1].split()[0].lower()}, {f[2]}~h)" for f in filas if f[5] != "sí"]
    macro("FranjasNoViables", (", ".join(no_viables[:-1]) + " y " + no_viables[-1]) if len(no_viables) > 1
          else (no_viables[0] if no_viables else "ninguna"), p)
    plan_p = EVID / "optimizacion" / "ejemplo_plan_d5.json"
    plan = json.loads(plan_p.read_text(encoding="utf-8")) if plan_p.exists() else {}
    horas = plan.get("horas") or []
    macro("PlanRuta", str(plan.get("ruta", "s. d.")), plan_p)
    macro("PlanFecha", str(plan.get("fecha", "s. d.")), plan_p)
    macro("PlanSalidas", num(plan.get("salidas_dia"), 0), plan_p)
    macro("PlanProgramadas", num(plan.get("salidas_programadas_dia"), 1), plan_p)
    if horas:
        pico = max(horas, key=lambda h: h.get("pasajeros_previstos") or 0)
        macro("PlanHoraPico", f"{int(pico['hora'])}", plan_p)
        macro("PlanHeadwayPico", num(pico.get("headway_min"), 1), plan_p)
        macro("PlanSalidasPico", num(pico.get("salidas"), 0), plan_p)
        macro("PlanHeadwayMax", num(max(h.get("headway_min") or 0 for h in horas), 1), plan_p)


def cifras_monitoreo():
    c = leer_json("compuerta")
    f = FUENTES["compuerta"]
    macro("GateCandidato", str(g(c, "candidato", defecto="s. d.")).replace("_", "\\_"), f)
    macro("GateWAPECand", num(g(c, "metricas_candidato", "wape")), f)
    macro("GateWAPEAct", num(g(c, "metricas_activo", "wape")), f)
    macro("GateDecision", "aprobado" if g(c, "aprobado") else "rechazado", f)
    v = g(c, "ventana") or {}
    macro("GateVentana", f"{v.get('desde')} a {v.get('hasta')}" if v.get("desde") and v.get("hasta") else "s.\\,d.", f)
    o = leer_json("onnx")
    fo = FUENTES["onnx"]
    macro("NVariables", num(len(g(o, "columnas") or []), 0), fo)
    macro("FeatureVersion", str(g(o, "feature_version", defecto="s. d.")), fo)
    macro("OnnxDifMax", num(g(o, "paridad", "punto", "max_abs"), 4), fo)
    macro("OnnxMsFila", num(g(o, "paridad", "punto", "ms_fila_onnx"), 2), fo)
    macro("SklearnMsFila", num(g(o, "paridad", "punto", "ms_fila_sklearn"), 1), fo)


# --- Figuras ----------------------------------------------------------------------------------------------------------
def preparar_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for ttf in (AQUI / "fuentes").glob("Inter-*.ttf"):
        font_manager.fontManager.addfont(str(ttf))
    plt.rcParams.update({
        "font.family": "Inter Sobusa", "font.size": 9, "axes.edgecolor": ROL["eje"], "axes.linewidth": 0.8,
        "axes.labelcolor": ROL["tinta_3"], "xtick.color": ROL["tinta_3"], "ytick.color": ROL["tinta_3"],
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": ROL["rejilla"],
        "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white",
        "hatch.linewidth": 0.8, "legend.frameon": False, "axes.unicode_minus": True, "pdf.fonttype": 42,
    })
    return plt


def guardar(fig, nombre):
    FIGURAS.mkdir(exist_ok=True)
    fig.savefig(FIGURAS / f"{nombre}.pdf", bbox_inches="tight")
    fig.savefig(FIGURAS / f"{nombre}.png", bbox_inches="tight", dpi=200)


def fig_wape(plt, e):
    pr = g(e, "prueba_reservada") or {}
    filas = [("Modelo activo fv2", "cand", "modelo", True), ("Modelo anterior fv1", "anterior", "modelo", False),
             ("B1 · regla manual 8 semanas", "b1", "hoy", True), ("B2 · última semana", "b2", "hoy", False)]
    fig, ax = plt.subplots(figsize=(6.2, 2.3))
    for i, (txt, k, rol, lleno) in enumerate(filas):
        w = g(pr, "global", k, "wape")
        ic = g(pr, "bootstrap", k, "ic95")
        if w is None or not ic:
            continue
        y = len(filas) - 1 - i
        ax.plot(ic, [y, y], color=ROL[rol], linewidth=2.2, solid_capstyle="round")
        ax.plot([w], [y], "o", markersize=8, color=ROL[rol], markerfacecolor=ROL[rol] if lleno else "white",
                markeredgewidth=1.8)
        ax.text(ic[1] + 0.5, y, f"{num(w)} %  [{num(ic[0])}–{num(ic[1])}]", va="center", fontsize=8.5,
                color=ROL["tinta"])
    ax.set_yticks(range(len(filas)), [f[0] for f in reversed(filas)])
    ax.set_xlim(10, 36)
    ax.xaxis.set_major_formatter(lambda v, _: f"{num(v, 0)} %")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0, labelcolor=ROL["tinta"])
    guardar(fig, "wape_modelos")
    plt.close(fig)


def fig_rutas(plt, e):
    import numpy as np
    pr = g(e, "prueba_reservada") or {}
    rutas = ["SILENCIO", "CRA 54", "CL 72"]
    act = [g(pr, "por_ruta", r, "cand", "wape") for r in rutas]
    b1 = [g(pr, "por_ruta", r, "b1", "wape") for r in rutas]
    if None in act or None in b1:
        return
    x = np.arange(len(rutas))
    fig, ax = plt.subplots(figsize=(4.6, 2.4))
    ax.bar(x - 0.19, b1, 0.36, color=ROL["hoy_tinte"], edgecolor=ROL["hoy"], hatch="////", linewidth=0.8,
           label="B1 · regla manual")
    ax.bar(x + 0.19, act, 0.36, color=ROL["modelo"], label="Modelo activo fv2")
    for xi, v in zip(x - 0.19, b1):
        ax.text(xi, v + 0.5, num(v, 1), ha="center", fontsize=8, color=ROL["tinta_2"])
    for xi, v in zip(x + 0.19, act):
        ax.text(xi, v + 0.5, num(v, 1), ha="center", fontsize=8, color=ROL["tinta"])
    ax.set_xticks(x, rutas)
    ax.yaxis.set_major_formatter(lambda v, _: f"{num(v, 0)} %")
    ax.set_ylim(0, 30)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", ncols=2, fontsize=8, handlelength=1.2)
    guardar(fig, "wape_rutas")
    plt.close(fig)


def fig_alertas(plt, a):
    import numpy as np
    codigos = ["ALT-005", "ALT-006", "ALT-007", "ALT-008"]
    antes = [g(a, "reglas_anteriores", "por_codigo", c, "por_ruta_dia") for c in codigos]
    ahora = [g(a, "por_defecto", "por_codigo", c, "por_ruta_dia") for c in codigos]
    if None in antes or None in ahora:
        return
    x = np.arange(len(codigos))
    fig, ax = plt.subplots(figsize=(4.6, 2.4))
    ax.bar(x - 0.19, antes, 0.36, color=ROL["hoy_tinte"], edgecolor=ROL["hoy"], hatch="////", linewidth=0.8,
           label="Reglas sin persistencia")
    ax.bar(x + 0.19, ahora, 0.36, color=ROL["modelo"], label="Reglas versionadas actuales")
    for xi, v in zip(x - 0.19, antes):
        ax.text(xi, v + 0.05, num(v, 2), ha="center", fontsize=7.5, color=ROL["tinta_2"])
    for xi, v in zip(x + 0.19, ahora):
        ax.text(xi, v + 0.05, num(v, 2), ha="center", fontsize=7.5, color=ROL["tinta"])
    ax.set_xticks(x, codigos)
    ax.set_ylim(0, max(antes) * 1.25)
    ax.yaxis.set_major_formatter(lambda v, _: num(v, 1))
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", fontsize=8, handlelength=1.2)
    guardar(fig, "alertas_por_ruta_dia")
    plt.close(fig)


def fig_k6(plt, k):
    m = g(k, "metrics") or {}
    recursos = ["predictions", "alerts", "recommendations", "executions", "models"]
    vals = [g(m, f"http_req_duration{{recurso:{r}}}", "p(95)") for r in recursos]
    if None in vals:
        return
    fig, ax = plt.subplots(figsize=(4.6, 2.3))
    y = list(range(len(recursos)))[::-1]
    ax.barh(y, vals, 0.55, color=ROL["modelo"])
    for yi, v in zip(y, vals):
        ax.text(v + 30, yi, f"{num(v, 0)} ms", va="center", fontsize=8, color=ROL["tinta"])
    ax.axvline(2000, color=ROL["referencia"], linewidth=1)
    ax.text(1980, max(y) + 0.55, "límite RNF-002: 2.000 ms", ha="right", fontsize=7.5, color=ROL["tinta_2"])
    ax.set_yticks(y, [f"GET /{r}" for r in recursos])
    ax.set_xlim(0, 2150)
    ax.xaxis.set_major_formatter(lambda v, _: num(v, 0))
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0, labelcolor=ROL["tinta"])
    guardar(fig, "k6_p95")
    plt.close(fig)


def fig_pruebas(plt, conteo):
    total = conteo.get("total") or {}
    if not total:
        return
    niveles = [("unit", "Unitarias"), ("integracion", "Integración"), ("replica", "Réplica"), ("contrato", "Contrato"),
               ("datos_ml", "Datos/ML"), ("testcontainers", "Testcontainers")]
    vals = [total.get(k, 0) for k, _ in niveles]
    fig, ax = plt.subplots(figsize=(4.6, 2.3))
    y = list(range(len(niveles)))[::-1]
    ax.barh(y, vals, 0.55, color=ROL["modelo"])
    for yi, v in zip(y, vals):
        ax.text(v + 6, yi, num(v, 0), va="center", fontsize=8, color=ROL["tinta"])
    ax.set_yticks(y, [t for _, t in niveles])
    ax.set_xlim(0, max(vals) * 1.15)
    ax.xaxis.set_major_formatter(lambda v, _: num(v, 0))
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0, labelcolor=ROL["tinta"])
    guardar(fig, "pruebas_por_nivel")
    plt.close(fig)


def fig_plan_reasigna(plt):
    """Salidas por hora: hoy frente al plan que reasigna (la misma figura del informe, §4, con los roles del tablero).
    Lee costos/resultados/d5_reoptimizado_decisiones.parquet, como informe/figuras_extra.py: n_S0 = salidas reales
    de 2025 y x_corrida_1 = plan con costos con fuente; promedio por día, por ruta y tipo de día."""
    fuente = ENTREGA.parent / "costos" / "resultados" / "d5_reoptimizado_decisiones.parquet"
    if not fuente.exists():
        avisos.append(f"falta {fuente.as_posix()}: la presentación usa la figura del informe")
        return
    import numpy as np
    import pandas as pd
    d = pd.read_parquet(fuente, columns=["ruta", "dia", "hora", "tipo_dia", "n_S0", "x_corrida_1"])
    rutas = ["SILENCIO", "CRA 54", "CL 72"]
    tipos = [("Laboral", "Día laboral"), ("Domingo/festivo", "Domingo o festivo")]
    horas = np.arange(4, 21)
    fig, ejes = plt.subplots(2, 3, figsize=(6.6, 4.2), sharex=True)
    for fila, (tipo, etiqueta) in enumerate(tipos):
        sub = d[d["tipo_dia"] == tipo]
        n_dias = sub["dia"].nunique()
        for col, ruta in enumerate(rutas):
            ax = ejes[fila, col]
            r = sub[sub["ruta"] == ruta].groupby("hora")[["n_S0", "x_corrida_1"]].sum().reindex(horas) / n_dias
            ax.step(horas, r["n_S0"], where="mid", color=ROL["hoy"], linewidth=1.6, label="Hoy (oferta real 2025)")
            ax.step(horas, r["x_corrida_1"], where="mid", color=ROL["modelo"], linewidth=2.0,
                    label="Plan que reasigna")
            ax.set_ylim(0, None)
            ax.set_xticks([4, 8, 12, 16, 20])
            ax.set_title(ruta, fontsize=9, color=ROL["tinta"])
            ax.yaxis.set_major_formatter(lambda v, _: num(v, 0))
            if col == 0:
                ax.set_ylabel(f"{etiqueta}\nsalidas por hora", fontsize=8)
            if fila == 1:
                ax.set_xlabel("Hora de salida", fontsize=8)
    manijas, etiquetas = ejes[0, 0].get_legend_handles_labels()
    fig.legend(manijas, etiquetas, loc="upper center", ncols=2, frameon=False, bbox_to_anchor=(0.5, 1.03),
               fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    guardar(fig, "plan_reasigna")
    plt.close(fig)


def main():
    estricto = "--estricto" in sys.argv
    e = cifras_modelo()
    cifras_calibracion()
    cifras_horizontes()
    a = cifras_alertas()
    k = cifras_k6()
    cifras_segmentos()
    cifras_ocupacion()
    cifras_retencion()
    cifras_consolidados()
    cifras_rendimiento()
    conteo = cifras_pruebas()
    estado_ci()
    cifras_monitoreo()
    cifras_optimizacion()
    cifras_sonar()
    cifras_demo()
    cifras_plan()
    cifras_hallazgos()
    respuesta_reto()
    GENERADO.mkdir(exist_ok=True)
    lineas = ["% Generado por documentos/datos_documentos.py: no editar a mano. Cada cifra con su evidencia.", ""]
    for nombre, valor, fuente in macros:
        lineas.append(f"\\newcommand{{\\{nombre}}}{{{valor}}}% {fuente}")
    lineas.append(f"\\newcommand{{\\FuentePruebas}}{{\\path{{{rel(JUNIT)}}}}}")
    lineas.append(f"\\newcommand{{\\FuenteCobertura}}{{\\path{{{rel(COBERTURA)}}}}}")
    (GENERADO / "cifras.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    # Colores por rol del tablero (dash_app/assets/estilos.css vía tokens.py): los documentos no escriben ningún hex.
    colores = ["% Generado por documentos/datos_documentos.py desde dash_app/tokens.py (roles de DISENO.md §2)."]
    for rol, valor in ROL.items():
        r, gg, b, alfa = tokens.rgba(valor)
        if alfa >= 1:
            colores.append(f"\\definecolor{{rol-{rol.replace('_', '-')}}}{{RGB}}{{{r},{gg},{b}}}")
    (GENERADO / "colores.tex").write_text("\n".join(colores) + "\n", encoding="utf-8")
    plt = preparar_matplotlib()
    if e:
        fig_wape(plt, e)
        fig_rutas(plt, e)
    if a:
        fig_alertas(plt, a)
    if k:
        fig_k6(plt, k)
    fig_pruebas(plt, conteo)
    fig_plan_reasigna(plt)
    print(f"cifras.tex: {len(macros)} macros; figuras en {rel(FIGURAS)}")
    for av in avisos:
        print("AVISO:", av)
    if estricto and avisos:
        sys.exit(1)


if __name__ == "__main__":
    main()
