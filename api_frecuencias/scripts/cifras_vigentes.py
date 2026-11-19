"""Cifras vigentes de la entrega, leídas de la evidencia (una sola fuente para la matriz, los README y los documentos).

    python scripts/cifras_vigentes.py             -> bloque Markdown con cada cifra y el archivo del que sale
    python scripts/cifras_vigentes.py --json      -> las mismas cifras en JSON

Nunca inventa un valor: si falta un archivo de evidencia, la cifra sale como «sin evidencia» con la ruta esperada.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET  # nosec B405  # solo lee JUnit/coverage de la propia suite  # noqa: S405
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
EVID = RAIZ / "docs" / "evidencias"
SIN = "sin evidencia"


def _json(rel: str) -> dict | None:
    p = EVID / rel
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _junit(rel: str) -> dict | None:
    p = EVID / rel
    if not p.is_file():
        return None
    raiz = ET.parse(p).getroot()  # nosec B314  # XML local generado por pytest en esta entrega  # noqa: S314
    suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
    tot = {"casos": 0, "fallas": 0, "errores": 0, "omitidas": 0}
    for s in suites:
        tot["casos"] += int(s.get("tests", 0))
        tot["fallas"] += int(s.get("failures", 0))
        tot["errores"] += int(s.get("errors", 0))
        tot["omitidas"] += int(s.get("skipped", 0))
    tot["aprobadas"] = tot["casos"] - tot["fallas"] - tot["errores"] - tot["omitidas"]
    return tot


def _cobertura(rel: str) -> float | None:
    p = EVID / rel
    if not p.is_file():
        return None
    raiz = ET.parse(p).getroot()  # nosec B314  # XML local generado por coverage.py en esta entrega  # noqa: S314
    tasa = raiz.get("line-rate")
    return round(float(tasa) * 100, 2) if tasa is not None else None


def _pct(x: float | None, dec: int = 2) -> str:
    return SIN if x is None else f"{x:.{dec}f}".replace(".", ",") + " %"


def _num(x: float | None, dec: int = 3) -> str:
    return SIN if x is None else f"{x:.{dec}f}".replace(".", ",")


def _mil(x: float | None, dec: int = 1) -> str:
    """Número en formato español, con punto de miles y coma decimal (1.163,1); el signo menos es «−»."""
    if x is None:
        return SIN
    entero, _, frac = f"{x:,.{dec}f}".partition(".")
    return (entero.replace(",", ".") + ("," + frac if frac else "")).replace("-", "−")


def _pct_mitad(x: float | None) -> str:
    """Dos decimales con la mitad hacia arriba sobre el decimal escrito (8,715 → 8,72), la regla de E14."""
    from decimal import ROUND_HALF_UP, Decimal

    return SIN if x is None else f"{Decimal(str(x)).quantize(Decimal('0.01'), ROUND_HALF_UP)}".replace(".", ",") + " %"


PRUEBA_E14 = RAIZ.parent / "pronostico_corto_plazo" / "resultados" / "prueba.json"


def _corto_plazo(c: list) -> None:
    """El pronóstico pedido (RF-005): la prueba reservada de E14 (julio a diciembre de 2025, calculada una sola vez), la
    reproducción de esa prueba por la API, la exportación a ONNX y la regla de calidad VAL-009."""
    try:
        prueba = __import__("json").loads(PRUEBA_E14.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prueba = {}
    rel_prueba = "../../pronostico_corto_plazo/resultados/prueba.json"
    niveles = prueba.get("niveles") or {}
    for nivel, nombre in (("ruta", "por ruta"), ("sentido", "por sentido"), ("segmento", "por segmento")):
        partes = []
        for h in ("30", "60", "120"):
            t_ = ((niveles.get(nivel) or {}).get(h) or {}).get("todas_las_rutas") or {}
            m, b = (t_.get("modelo") or {}).get("wape"), (t_.get("promedio_dia_hora") or {}).get("wape")
            partes.append(SIN if m is None or b is None else f"{h} min {_pct_mitad(m)} frente a {_pct_mitad(b)}")
        c.append((f"WAPE del pronóstico de corto plazo {nombre} en la prueba reservada (jul–dic 2025), modelo "
                  "cp_lgbm_20250630_s42 frente al promedio por día y hora", "; ".join(partes), rel_prueba))
    rel = "modelo/corto_plazo_reproduccion.json"
    rep_ = _json(rel) or {}
    pred = rep_.get("predicciones") or {}
    filas = sum(int((pred.get(n) or {}).get("filas_api") or 0) for n in ("ruta", "sentido"))
    dif = max([float(((pred.get(n) or {}).get("pronostico") or {}).get("diferencia_maxima") or 0) for n in pred] or [0])
    c.append(("La API reproduce la prueba reservada del corto plazo (predicciones por ruta y por sentido)",
              SIN if not rep_ else f"{_mil(filas, 0)} predicciones, diferencia máxima {_num(dif, 4)}; coincide: "
                                   f"{'sí' if rep_.get('coincide') else 'no'}", rel))
    rel = "modelo/corto_plazo_onnx.json"
    onx = _json(rel) or {}
    arts = (onx.get("artefactos") or {}).values()
    peor = max([float(a.get("diferencia_relativa_maxima") or 0) for a in arts] or [0])
    n = sum(int(a.get("filas_paridad") or 0) for a in arts)
    tol = float(onx.get("tolerancia_relativa") or 0)
    c.append(("ONNX del corto plazo: paridad con LightGBM de los 18 artefactos",
              SIN if not onx else (f"{_mil(n, 0)} filas, diferencia relativa máxima {f'{peor:.1e}'.replace('.', ',')} "
                                   f"(tolerancia {tol:.0e}); paridad: {'sí' if onx.get('paridad') else 'no'}"), rel))


def _modelo(c: list) -> None:
    ev = _json("modelo/evaluacion_modelo.json")
    g = (ev or {}).get("prueba_reservada", {}).get("global", {})
    for clave, nombre in (("cand", "modelo activo hgb_fv2_20250831_s42"), ("b1", "línea base B1 (regla manual)"),
                          ("anterior", "versión anterior fv1")):
        w = (g.get(clave) or {}).get("wape")
        c.append((f"WAPE en la prueba reservada (nov–dic 2025), {nombre}", _pct(w), "modelo/evaluacion_modelo.json"))
    # el candidato registrado sin activar (fv3), con el mismo protocolo (modelo/decision_fv3.md)
    rel = "modelo/candidato_fv3/evaluacion_modelo.json"
    cand = _json(rel) or {}
    pr = cand.get("prueba_reservada") or {}
    mid = (pr.get("modelos") or {}).get("activo", "?")
    w = ((pr.get("global") or {}).get("cand") or {}).get("wape")
    c.append((f"WAPE en la prueba reservada (nov–dic 2025), candidato sin activar {mid}", _pct(w), rel))
    for anio, r in (cand.get("robustez") or {}).items():
        g_r, b_r = r.get("global") or {}, (r.get("bootstrap") or {}).get("cand_menos_anterior") or {}
        a, b = (g_r.get("cand") or {}).get("wape"), (g_r.get("anterior") or {}).get("wape")
        ic = b_r.get("ic95") or [None, None]
        txt = SIN if a is None or b is None else (f"{_pct(a)} frente a {_pct(b)} (diferencia "
                                                  f"{_num(ic[0], 2)} a {_num(ic[1], 2)} pp)".replace("-", "−"))
        c.append((f"WAPE de {anio} con modelos congelados un año antes, candidato fv3 frente a fv2", txt, rel))
    prueba = ((_json("modelo/calibracion_condicional.json") or {}).get("resultados") or {}).get("prueba") or {}
    for version in ("v2", "v1"):
        glob = (prueba.get(version) or {}).get("global") or {}
        c.append((f"Cobertura P10–P90 en la prueba reservada, calibración {version} (ancho medio "
                  f"{_num(glob.get('ancho_medio'), 1)} pasajeros)", _pct(glob.get("cobertura_pct")),
                  "modelo/calibracion_condicional.json"))


def _modelo_segmentos(c: list) -> None:
    """Modelo por segmento y sentido (§3.1, §9.1, §9.3): su prueba única de feb-2023 y la banda P10–P90."""
    rel = "modelo/segmentos_modelo.json"
    ev = _json(rel) or {}
    prueba = ev.get("prueba") or {}
    periodo = (ev.get("particion") or {}).get("prueba", "?")
    activo = (ev.get("activacion") or {}).get("activo", "?")
    for clave, nombre in (("M4", f"modelo de segmentos activo {activo}"), ("B0", "línea base B0 (reparto fijo)")):
        m = (prueba.get("metricas") or {}).get(clave) or {}
        seg, sen = m.get("wape_segmento_hora"), m.get("wape_sentido_hora")
        txt = SIN if seg is None or sen is None else f"{_pct(seg)} (por sentido y hora, {_pct(sen)})"
        c.append((f"WAPE por segmento y hora en la prueba ({periodo}), {nombre}", txt, rel))
    ic = (_json("modelo/segmentos_banda_ventanas.json") or {}).get("ic95_prueba_wape_segmento_hora_vs_B0") or {}
    dif, lim = ic.get("diferencia_pp"), ic.get("ic95_pp") or []
    txt = SIN if dif is None or len(lim) != 2 else (f"{_mil(dif, 3)} pp (IC95 {_mil(lim[0], 3)} a "
                                                     f"{_mil(lim[1], 3)})")
    c.append(("Diferencia de WAPE por segmento y hora del modelo de segmentos frente a B0 en la prueba (IC95 bootstrap "
              "por días)", txt, "modelo/segmentos_banda_ventanas.json"))
    m4 = prueba.get("M4") or {}
    for clave, nombre in (("banda_total_real", "con el total real de la ruta"),
                          ("banda_punta_a_punta_b2", "de punta a punta con el pronóstico de ruta B2")):
        banda = m4.get(clave) or {}
        seg = (banda.get("segmento") or {}).get("cobertura_pct")
        sen = (banda.get("sentido") or {}).get("cobertura_pct")
        txt = SIN if seg is None or sen is None else f"{_pct(seg)} / {_pct(sen)}"
        c.append((f"Cobertura P10–P90 del modelo de segmentos en la prueba, {nombre} (por segmento / por sentido)",
                  txt, rel))
    comp = prueba.get("composicion_con_ruta_activa") or {}
    seg, sen = comp.get("cobertura_segmento_pct"), comp.get("cobertura_sentido_pct")
    txt = SIN if seg is None or sen is None else f"{_pct(seg)} / {_pct(sen)}"
    c.append((f"Cobertura P10–P90 del modelo de segmentos con errores reales del modelo de ruta "
              f"{comp.get('modelo_ruta', '?')} (análisis posterior a la prueba; por segmento / por sentido)", txt, rel))


CODIGOS_PRONOSTICO = ("ALT-001", "ALT-002", "ALT-003", "ALT-004")


def _pronostico_por_ruta_dia(pro: dict) -> float | None:
    """Alertas de pronóstico ALT-001..ALT-004 por ruta y día del backtest del ciclo de las 6:00: el total de alertas
    entre los días-ruta (no la suma de las cifras redondeadas de cada código). None si falta un código o los días."""
    por = ((pro.get("variantes") or {}).get("franja") or {}).get("por_codigo") or {}
    dias = pro.get("dias_ruta")
    if not dias or any((por.get(cod) or {}).get("alertas") is None for cod in CODIGOS_PRONOSTICO):
        return None
    return sum(int(por[cod]["alertas"]) for cod in CODIGOS_PRONOSTICO) / int(dias)


def _total_alertas(c: list, obs: dict, pro: dict) -> None:
    """§18 «Alertas excesivas»: el volumen total que recibe el operador por ruta y día, observadas (backtest_alertas
    .json) más las de pronóstico (backtest_alertas_pronostico.json), en el mismo periodo. Sin evidencia si falta uno de
    los dos archivos; si los periodos no coinciden, lo dice."""
    observadas = (obs.get("por_defecto") or {}).get("observadas_por_ruta_dia")
    pronostico = _pronostico_por_ruta_dia(pro)
    periodos = [obs.get("periodo"), pro.get("periodo")]
    if observadas is None or pronostico is None:
        txt = SIN
    else:
        txt = (f"{_num(observadas + pronostico)} ({_num(observadas)} observadas + {_num(pronostico)} de pronóstico"
               + ("" if periodos[0] == periodos[1] else f"; periodos distintos: {periodos[0]} y {periodos[1]}") + ")")
    c.append(("Alertas por ruta y día para el operador, observadas + pronóstico (15-sep a 31-dic-2025)", txt,
              "alertas/backtest_alertas.json y alertas/backtest_alertas_pronostico.json"))


def _alertas(c: list) -> None:
    obs = _json("alertas/backtest_alertas.json") or {}
    pd_ = obs.get("por_defecto", {})
    c.append(("Alertas observadas por ruta y día (15-sep a 31-dic-2025)", _num(pd_.get("observadas_por_ruta_dia")),
              "alertas/backtest_alertas.json"))
    pro = _json("alertas/backtest_alertas_pronostico.json") or {}
    por = (pro.get("variantes", {}).get("franja", {}) or {}).get("por_codigo", {})
    for cod in CODIGOS_PRONOSTICO:
        d = por.get(cod) or {}
        c.append((f"{cod} de pronóstico por ruta y día (lift {_num(d.get('lift'), 2)})", _num(d.get("por_ruta_dia")),
                  "alertas/backtest_alertas_pronostico.json"))
    _total_alertas(c, obs, pro)
    con = _json("alertas/revision_doble/conciliacion.json") or {}
    kappa = (con.get("acuerdo_antes_de_conciliar", {}).get("global", {}) or {}).get("kappa")
    c.append(("Revisión doble de 96 alertas: kappa entre revisores (automatizados)", _num(kappa),
              "alertas/revision_doble/conciliacion.json"))


NIVELES = (("unit", "unitarias"), ("integracion", "integración"), ("replica", "réplica"), ("contrato", "contrato"),
           ("datos_ml", "datos y ML"))


def _niveles(rel: str) -> str:
    """Casos del JUnit por carpeta de tests/ (el nivel de la pirámide de §14.1); las subpruebas cuentan como casos."""
    p = EVID / rel
    if not p.is_file():
        return SIN
    raiz = ET.parse(p).getroot()  # nosec B314  # XML local generado por pytest en esta entrega  # noqa: S314
    por_nivel: dict[str, int] = {}
    for caso in raiz.iter("testcase"):
        partes = (caso.get("classname") or "").split(".")
        nivel = partes[1] if len(partes) > 1 and partes[0] == "tests" else "otros"
        por_nivel[nivel] = por_nivel.get(nivel, 0) + 1
    if not por_nivel:
        return SIN
    conocidos = [f"{nombre} {_mil(por_nivel.pop(clave), 0)}" for clave, nombre in NIVELES if clave in por_nivel]
    return ", ".join(conocidos + [f"{clave} {_mil(n, 0)}" for clave, n in sorted(por_nivel.items())])


def _calidad(c: list) -> None:
    for rel, nombre in (("pruebas/suite_final.xml", "Suite completa final"),
                        ("pruebas/ci/pytest.xml", "CI en copia limpia")):
        j = _junit(rel)
        txt = SIN if j is None else (f"{j['casos']} casos: {j['aprobadas']} aprobados, {j['fallas']} fallas, "
                                     f"{j['errores']} errores, {j['omitidas']} omitidos")
        c.append((nombre, txt, rel))
    c.append(("Suite completa final, casos por nivel", _niveles("pruebas/suite_final.xml"), "pruebas/suite_final.xml"))
    for rel, nombre in (("pruebas/coverage_final.xml", "Cobertura de app/ (suite final)"),
                        ("pruebas/ci/coverage.xml", "Cobertura de app/ (CI en copia limpia)")):
        c.append((nombre, _pct(_cobertura(rel)), rel))
    qg = _json("sonarqube/quality_gate.json") or {}
    med = (_json("sonarqube/measures.json") or {}).get("medidas", {})
    estado = (qg.get("estado") or {}).get("status", SIN)
    detalle = (f"{estado} (vulnerabilidades {med.get('vulnerabilities', '?')}, bugs {med.get('bugs', '?')}, "
               f"críticos {med.get('critical_violations', '?')}, bloqueantes {med.get('blocker_violations', '?')}, "
               f"cobertura {med.get('coverage', '?')} %)")
    c.append(("SonarQube, puerta «Reto Sobusa v1.5»", detalle, "sonarqube/quality_gate.json"))
    ci = EVID / "pruebas" / "ci_github.txt"
    c.append(("GitHub Actions (runner limpio)", ci.read_text(encoding="utf-8").splitlines()[0] if ci.is_file() else SIN,
              "pruebas/ci_github.txt"))


def _carga(c: list) -> None:
    """Las dos corridas anteriores de la carga (un mes y un año de resultados). La vigente, con el volumen sembrado
    desde el ciclo final, es la de _segmentos (k6_segmentos_consultas.json)."""
    for rel, nombre in (("pruebas/k6_consultas.json", "k6, consultas paginadas con un mes de resultados (corrida "
                                                     "anterior)"),
                        ("pruebas/k6_volumen.json", "k6 con un año de resultados")):
        k = _json(rel) or {}
        if k.get("fecha"):
            nombre += f" (corrida anterior, del {k['fecha']})"
        if "metrics" not in k and isinstance(k.get("carga"), dict):   # k6_volumen.json guarda el resumen en «carga»
            k = k["carga"]
        m = k.get("metrics", {})
        dur = m.get("http_req_duration") or {}
        fal = (m.get("http_req_failed") or {}).get("value")
        txt = SIN if not dur else f"p95 {_num(dur.get('p(95)'), 1)} ms, errores {_pct((fal or 0) * 100, 2)}"
        c.append((nombre, txt, rel))


def _k6(rel: str) -> dict:
    """Métricas del resumen de k6 (--summary-export) de un archivo de evidencia; {} si no está."""
    return (_json(rel) or {}).get("metrics") or {}


def _p95(m: dict, clave: str) -> float | None:
    return (m.get(clave) or {}).get("p(95)")


def _errores(m: dict, clave: str = "http_req_failed") -> str:
    tasa = (m.get(clave) or {}).get("value")
    return SIN if tasa is None else _pct(tasa * 100, 2)


def _segmentos(c: list) -> None:
    """Capa de segmentos y carga con el volumen acordado (RNF-002, RNF-004, §7.1, §14.1): k6 sobre la agregación
    materializada. Los cinco pasos salen de una misma corrida de scripts/medir_segmentos.py (k6_segmentos.txt); la
    carpeta revision_segmentos/ guarda una corrida anterior de los pasos en frío y con el refresco."""
    rel = "pruebas/k6_segmentos_resumen.json"
    rutas = ((_json(rel) or {}).get("en_frio") or {}).get("rutas") or {}
    est = rutas.get("segmentos_estadisticas") or {}
    frio, caliente = (est.get("frio") or [None, None])[-1], (est.get("caliente") or [None, None])[-1]
    txt = SIN if frio is None or caliente is None else f"{_mil(frio)} ms / {_mil(caliente)} ms"
    c.append(("k6, GET /segmentos/estadisticas con la API recién arrancada: primera petición / segunda", txt, rel))
    rel = "pruebas/k6_segmentos_en_frio.json"
    m = _k6(rel)
    p_frio, p_cal = _p95(m, "http_req_duration{pasada:frio,clase:consulta}"), _p95(
        m, "http_req_duration{pasada:caliente,clase:consulta}")
    consultas = sum(1 for r in rutas if not r.endswith("_export")) or "?"
    txt = SIN if p_frio is None or p_cal is None else (f"{_mil(p_frio)} ms / {_mil(p_cal)} ms, errores "
                                                       f"{_errores(m)}")
    c.append((f"k6, {consultas} consultas paginadas con la API recién arrancada: p95 de la primera pasada / de la "
              "segunda", txt, rel))
    rel = "pruebas/k6_segmentos_carga.json"
    m = _k6(rel)
    p95 = _p95(m, "http_req_duration{tipo:consulta}")
    peor = max((v.get("p(95)") or 0 for k, v in m.items() if k.startswith("http_req_duration{consulta:")),
               default=None)
    txt = SIN if p95 is None else f"p95 {_mil(p95)} ms (la consulta más lenta, {_mil(peor)} ms), errores {_errores(m)}"
    c.append(("k6, capa de segmentos con 50 usuarios durante un refresco completo", txt, rel))
    rel = "pruebas/k6_segmentos_consultas.json"
    m = _k6(rel)
    p95 = _p95(m, "http_req_duration")
    c.append(("k6, consultas paginadas con el volumen acordado (50 usuarios; corrida vigente)",
              SIN if p95 is None else f"p95 {_mil(p95)} ms, errores {_errores(m)}", rel))
    rel = "pruebas/k6_segmentos_ingesta.json"
    m = _k6(rel)
    p95 = _p95(m, "http_req_duration{fase:durante_ingesta}")
    ok = (m.get("ingesta_ok") or {}).get("value")
    filas = (m.get("ingesta_filas_leidas") or {}).get("count")
    dur = _p95(m, "ingesta_duracion_ms")
    if p95 is None or filas is None or dur is None:
        txt = SIN
    else:
        txt = (f"p95 {_mil(p95)} ms, errores {_errores(m, 'http_req_failed{fase:durante_ingesta}')}; ingesta "
               f"{'ok' if ok == 1 else 'que no terminó ok'} con {_mil(filas, 0)} filas en {_mil(dur / 1000)} s")
    c.append(("k6, 30 usuarios durante una ingesta incremental desde la réplica", txt, rel))


def _refresco_sin_cambios(c: list) -> None:
    """Refresco incremental de la agregación de segmentos sin filas nuevas (RNF-004, migración 0012): sin las huellas
    de la ventana de solape y con ellas, medido en la réplica."""
    rel = "pruebas/segmentos_sin_cambios.json"
    r = _json(rel) or {}
    corridas = [r.get("antes_sin_huellas") or {}, r.get("ahora_con_huellas") or {}]
    if any(x.get(k) is None for x in corridas for k in ("fechas_releidas", "filas_leidas", "segundos")):
        txt = SIN
    else:
        txt = " / ".join(f"{_mil(x['fechas_releidas'], 0)} fechas, {_mil(x['filas_leidas'], 0)} filas, "
                         f"{_mil(x['segundos'])} s" for x in corridas)
    c.append(("Refresco incremental de segmentos sin filas nuevas en la réplica: fechas releídas, filas leídas y "
              "duración, sin huellas / con las huellas del refresco anterior", txt, rel))


def _particion(c: list) -> None:
    """Partición del ciclo por ruta (RNF-005): dos réplicas reales y la lectura por ruta en la réplica."""
    rel = "cola/replicas_por_ruta.json"
    r = _json(rel)
    if r is None:
        txt = SIN
    else:
        comparada = "reloj_lote_sin_partir_s" in r
        txt = (f"{'TODO OK' if r.get('ok') else 'con fallas'}: {r.get('trabajos', '?')} trabajos de ruta y "
               f"{r.get('madres', '?')} madres; {r.get('pares_cruzados', '?')} pares de rutas distintas a la vez y "
               f"{r.get('pares_misma_ruta', '?')} cruces de la misma ruta")
        if comparada:
            txt += (f"; {'las mismas' if r.get('ok') else 'otras'} salidas que sin partir; lote en "
                    f"{_mil(r.get('reloj_lote_s'))} s partido y {_mil(r.get('reloj_lote_sin_partir_s'))} s sin partir")
    c.append(("RNF-005, dos réplicas con la ejecución partida por ruta", txt, rel))
    rel = "cola/lectura_por_ruta_replica.json"
    lec = (_json(rel) or {}).get("rutas") or {}
    planes = [p for x in lec.values() for p in (x.get("desde_marca_intermedia") or {}, x.get("desde_la_marca_mayor")
                                                or {})]
    tiempos = {k: [(p.get(k) or {}).get("ms_ejecucion") for p in planes] for k in ("explain_todas", "explain_ruta")}
    if not planes or any(v is None for t in tiempos.values() for v in t):
        txt = SIN
    else:
        iguales = all((x.get("carga_inicial") or {}).get("iguales") and p.get("iguales") for x in lec.values()
                      for p in (x.get("desde_marca_intermedia") or {}, x.get("desde_la_marca_mayor") or {}))
        media = {k: sum(v) / len(v) for k, v in tiempos.items()}
        txt = (f"{_mil(media['explain_todas'], 0)} ms / {_mil(media['explain_ruta'], 0)} ms; cada ruta lee lo mismo "
               f"que la lectura completa filtrada: {'sí' if iguales else 'no'}")
    c.append(("Lectura incremental en la réplica, sin los índices propuestos: SELECT medio de todas las rutas / de una "
              "ruta", txt, rel))


def _ocupacion(c: list) -> None:
    """Ocupación por segmento (§10.1): la validación del perfil histórico, la cobertura del factor de carga por día de
    la semana y el backtest de la restricción reactiva (con los viajes completos y con los viajes en curso)."""
    rel = "ocupacion/perfil_ocupacion_segmentos.json"
    p = _json(rel) or {}
    val = (p.get("validacion") or {}).get("acotada_en_cada_segmento") or {}
    viajes = (p.get("viajes") or {}).get("en_perfil")
    if viajes is None or any(val.get(k) is None for k in ("viajes", "correlacion", "razon_mediana")):
        txt = SIN
    else:
        txt = (f"{_mil(viajes, 0)} viajes en el perfil; correlación {_num(val['correlacion'])} y razón mediana "
               f"{_num(val['razon_mediana'])} en {_mil(val['viajes'], 0)} viajes")
    c.append((f"Perfil histórico de ocupación por segmento ({p.get('periodo', '?')}): carga máxima de cada viaje "
              "frente a la ocupación máxima del dispositivo en los mismos viajes", txt, rel))
    fac = p.get("factor_dia_semana_2025") or {}
    dia, tipo = fac.get("celdas_dia_semana_con_10_dias"), fac.get("celdas_tipo_de_dia_con_10_dias")
    c.append(("Factor de carga crítica 2025: celdas ruta × día de operación × hora con al menos 10 días (por tipo de "
              "día)", SIN if dia is None or tipo is None else f"{_mil(dia, 0)} ({_mil(tipo, 0)})", rel))
    rel = "ocupacion/backtest_restriccion_reactiva.json"
    b = _json(rel) or {}
    op = b.get("frente_a_la_operacion") or {}
    claves = ("disparos", "salidas_agregadas", "salidas_agregadas_donde_no_hacia_falta",
              "horas_siguientes_sobre_umbral_sin_regla", "horas_siguientes_sobre_umbral_con_regla")
    if any(op.get(k) is None for k in claves):
        txt = SIN
    else:
        txt = (f"{_mil(op['disparos'], 0)} disparos; {_mil(op['salidas_agregadas'], 0)} salidas más "
               f"({_mil(op['salidas_agregadas_donde_no_hacia_falta'], 0)} donde no hacía falta); horas siguientes "
               f"sobre el umbral: {_mil(op['horas_siguientes_sobre_umbral_sin_regla'], 0)} sin la regla y "
               f"{_mil(op['horas_siguientes_sobre_umbral_con_regla'], 0)} con ella")
    c.append((f"Restricción reactiva de ocupación, backtest {b.get('periodo', '?')} con los viajes completos (cota "
              "superior)", txt, rel))
    cortes = (b.get("frente_al_tiempo_real") or {}).get("cortes") or []
    claves = ("corte", "de_esos_disparan_en_tiempo_real", "disparos_con_viajes_completos",
              "piso_en_tiempo_real_sobre_piso_completo")
    if not cortes or any(k.get(x) is None for k in cortes for x in claves):
        txt = SIN
    else:
        txt = "; ".join(f"a las {k['corte']}, {_mil(k['de_esos_disparan_en_tiempo_real'], 0)} de "
                        f"{_mil(k['disparos_con_viajes_completos'], 0)} con un piso de "
                        f"{_num(k['piso_en_tiempo_real_sobre_piso_completo'], 2)} veces el completo" for k in cortes)
    c.append(("Restricción reactiva con los viajes todavía en curso (ciclo intradía): disparos que siguen y piso "
              "frente al de los viajes completos", txt, rel))


def _faltan(d: dict, claves: tuple[str, ...]) -> bool:
    return any(d.get(k) is None for k in claves)


def _ciclo_intradia_fuente(c: list) -> None:
    """Carga en la base de Extreme del ciclo intradía (§10.1, 10.1-d, PLAN_INTRADIA_CRON) frente al diario, medida en la
    réplica como lector_ia (scripts/medir_ciclo_intradia.py), y su estimación para el histórico completo sin los
    índices de H12, que no es una medición."""
    rel = "ocupacion/ciclo_intradia_fuente.json"
    est = (_json(rel) or {}).get("estimacion") or {}
    txt = SIN if _faltan(est, ("intradia_s", "fraccion_de_la_hora_intradia", "intradia_dia_s")) else (
        f"{_num(est['intradia_s'], 2)} s ({_pct(100 * est['fraccion_de_la_hora_intradia'])} de la hora); "
        f"{_mil(est['intradia_dia_s'])} s al día con el cron por omisión")
    c.append(("Ciclo intradía (PLAN_INTRADIA_CRON) en la réplica: lectura de la fuente por ciclo y fracción de la "
              "hora; todos los ciclos del día", txt, rel))
    txt = SIN if _faltan(est, ("diario_s", "dia_con_intradia_sobre_dia_sin_intradia")) else (
        f"{_num(est['diario_s'], 2)} s; el día con los ciclos intradía lee "
        f"{_mil(est['dia_con_intradia_sobre_dia_sin_intradia'])} veces lo que lee solo con el diario")
    c.append(("Ciclo diario en la réplica: lectura de la fuente por ciclo", txt, rel))
    proy = est.get("proyeccion_historico_completo") or {}
    txt = SIN if _faltan(proy, ("intradia_s", "fraccion_de_la_hora_intradia", "factor_filas")) else (
        f"{_mil(proy['intradia_s'])} s por ciclo ({_pct(100 * proy['fraccion_de_la_hora_intradia'])} de la hora), con "
        f"{_mil(proy['factor_filas'])} veces las filas de la réplica")
    c.append(("Ciclo intradía con el histórico completo y sin los índices de H12: lectura de la fuente estimada por "
              "ciclo (proyección lineal, no medición)", txt, rel))


def _ciclo_intradia_programado(c: list) -> None:
    """El ciclo intradía programado con el planificador y la cola reales en un día comprimido, con una captura en vivo
    de prueba (scripts/evidencia_planificador_intradia.py): la duración de cada ciclo y el p95 de la consulta paginada
    con un ciclo en curso (RNF-002)."""
    rel = "ocupacion/planificador_intradia.json"
    p = _json(rel) or {}
    duraciones = [f.get("duracion_s") for f in p.get("franjas") or []]
    txt = SIN if not duraciones or None in duraciones else (
        f"de {_num(min(duraciones), 2)} a {_num(max(duraciones), 2)} s por ciclo ({len(duraciones)} ciclos)")
    c.append(("Ciclo intradía programado en un día comprimido (planificador y cola reales, captura de prueba): "
              "duración de cada ciclo", txt, rel))
    lat = p.get("latencia_consulta_paginada") or {}
    con, sin_ciclo = lat.get("con_ciclo_en_curso") or {}, lat.get("sin_ciclo") or {}
    if _faltan(con, ("p95_s", "n")) or _faltan(sin_ciclo, ("p95_s", "n")) or _faltan(lat, ("respuestas_no_200",)):
        txt = SIN
    else:
        txt = (f"p95 {_num(con['p95_s'])} s con un ciclo en curso ({_mil(con['n'], 0)} consultas) y "
               f"{_num(sin_ciclo['p95_s'])} s sin ciclo ({_mil(sin_ciclo['n'], 0)}); respuestas distintas de 200: "
               f"{_mil(lat['respuestas_no_200'], 0)}")
    c.append(("Consulta paginada GET /api/v1/recommendations (50 filas) durante los ciclos intradía programados",
              txt, rel))


def _ciclo_diario(c: list) -> None:
    """El ciclo diario de §14.2 de punta a punta (scripts/medir_ciclo.py): la carga inicial, un día nuevo y la
    repetición del mismo día, con las filas leídas de cada corrida."""
    rel = "rendimiento/ciclo_final.json"
    corridas = {x.get("corrida"): x for x in (_json(rel) or {}).get("corridas") or []}
    partes = []
    for clave in ("carga_inicial", "dia_nuevo", "repeticion"):
        x = corridas.get(clave) or {}
        if x.get("estado") != "ok" or _faltan(x, ("segundos_peticion", "filas_leidas")):
            partes = []
            break
        partes.append(f"{_mil(x['segundos_peticion'])} s ({_mil(x['filas_leidas'], 0)} filas)")
    c.append(("Ciclo diario de punta a punta (lectura, calidad, predicción, plan y alertas): carga inicial / día nuevo "
              "/ repetición del mismo día", " / ".join(partes) or SIN, rel))


def _contraste_de(tabla: dict) -> str | None:
    """El contraste por segmento de una tabla de Extreme con filas reales de la liquidación; None si falta un campo."""
    ciclo, hora = tabla.get("contraste_del_ciclo") or {}, tabla.get("con_la_hora_en_el_grano") or {}
    if _faltan(ciclo, ("llaves", "comparadas", "diferencias", "groseras", "llaves_bloqueadas")) or _faltan(
            hora, ("groseras", "llaves_bloqueadas")):
        return None
    return (f"{_mil(ciclo['comparadas'], 0)} de {_mil(ciclo['llaves'], 0)} llaves comparadas, "
            f"{_mil(ciclo['diferencias'], 0)} diferencias no bloqueantes, {_mil(ciclo['groseras'], 0)} groseras y "
            f"{_mil(ciclo['llaves_bloqueadas'], 0)} llaves bloqueadas; con la hora del bloque en el grano serían "
            f"{_mil(hora['groseras'], 0)} groseras y {_mil(hora['llaves_bloqueadas'], 0)} llaves bloqueadas")


def _contraste_segmentos(c: list) -> None:
    """Contraste de las tablas por segmento de Extreme con filas reales de la liquidación (6.1-16, 6.1-18, 11.2-05):
    lo escribe tests/replica/test_consolidados_segmentos.py en una transacción revertida, con los viajes que simula y
    contraste_viajes_minimos = 1. Si las dos tablas dan lo mismo sale una vez; si no, cada una con su nombre."""
    rel = "consolidados/segmentos_filas_reales.json"
    r = _json(rel) or {}
    textos = {nombre: _contraste_de(t) for nombre, t in (r.get("tablas") or {}).items()}
    if not textos or None in textos.values():
        txt = SIN
    elif len(set(textos.values())) == 1:
        txt = f"en cada tabla, {next(iter(textos.values()))}"
    else:
        txt = "; ".join(f"{nombre}: {t}" for nombre, t in textos.items())
    viajes = len(r.get("viajes") or []) or "?"
    c.append((f"Contraste por segmento con filas reales de la liquidación en la réplica ({viajes} viajes, "
              "contraste_viajes_minimos = 1; transacción revertida)", txt, rel))


LECTURAS_INDICES = (("demanda_segmentos_bloque", "bloque de llegada"),
                    ("demanda_segmentos_sin_novedades", "sin novedades"), ("viajes_de_una_ruta", "viajes de una ruta"))


def _indices(c: list) -> None:
    """La propuesta de índices para Extreme (H12, §8.3, §11.3) aplicada entera con ANALYZE en la réplica, en una
    transacción que se revierte (scripts/replica_indices_candidatos.py): tres lecturas de la API sin y con ella, y
    cuántas lecturas empeoran."""
    rel = "replica/indices_candidatos.json"
    r = _json(rel) or {}
    comp = (r.get("propuesta_entera") or {}).get("comparacion") or {}
    empeoran = (r.get("veredicto") or {}).get("empeoran")
    filas = [comp.get(clave) or {} for clave, _ in LECTURAS_INDICES]
    if empeoran is None or any(_faltan(f, ("ms_sin", "ms_con")) for f in filas):
        txt = SIN
    else:
        txt = "; ".join(f"{nombre}, {_mil(f['ms_sin'])} → {_mil(f['ms_con'])} ms"
                        for (_, nombre), f in zip(LECTURAS_INDICES, filas, strict=True))
        txt += f"; lecturas de la API que empeoran: {len(empeoran)}"
    c.append(("Propuesta de índices entera con ANALYZE en la réplica (transacción revertida): lectura incremental de la"
              " demanda por segmentos y lectura de viajes, sin → con los índices", txt, rel))


def cifras() -> list[tuple[str, str, str]]:
    c: list[tuple[str, str, str]] = []
    _corto_plazo(c)
    _modelo(c)
    _modelo_segmentos(c)
    _alertas(c)
    _calidad(c)
    _carga(c)
    _segmentos(c)
    _refresco_sin_cambios(c)
    _particion(c)
    _ocupacion(c)
    _ciclo_intradia_fuente(c)
    _ciclo_intradia_programado(c)
    _ciclo_diario(c)
    _contraste_segmentos(c)
    _indices(c)
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    filas = cifras()
    if a.json:
        print(json.dumps([{"cifra": n, "valor": v, "evidencia": _rutas(r, "docs/evidencias/", "{}")}
                          for n, v, r in filas], ensure_ascii=False, indent=1))
        return 0
    print("| Cifra | Valor | Evidencia |")
    print("|---|---|---|")
    for n, v, r in filas:
        print(f"| {n} | {v} | {_rutas(r, 'api_frecuencias/docs/evidencias/', '`{}`')} |")
    return 0


def _rutas(rel: str, prefijo: str, formato: str) -> str:
    """La evidencia de una cifra con su prefijo; una cifra que sale de dos archivos los nombra a los dos («a y b»)."""
    return " y ".join(formato.format(r[len("../../"):] if r.startswith("../../") else prefijo + r)
                      for r in rel.split(" y "))


if __name__ == "__main__":
    sys.exit(main())
