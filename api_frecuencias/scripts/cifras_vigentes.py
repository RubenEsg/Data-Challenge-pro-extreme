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


def _modelo(c: list) -> None:
    ev = _json("modelo/evaluacion_modelo.json")
    g = (ev or {}).get("prueba_reservada", {}).get("global", {})
    for clave, nombre in (("cand", "modelo activo hgb_fv2_20250831_s42"), ("b1", "línea base B1 (regla manual)"),
                          ("fv1", "versión anterior fv1")):
        w = (g.get(clave) or {}).get("wape")
        c.append((f"WAPE en la prueba reservada (nov–dic 2025), {nombre}", _pct(w), "modelo/evaluacion_modelo.json"))
    prueba = ((_json("modelo/calibracion_condicional.json") or {}).get("resultados") or {}).get("prueba") or {}
    for version in ("v2", "v1"):
        glob = (prueba.get(version) or {}).get("global") or {}
        c.append((f"Cobertura P10–P90 en la prueba reservada, calibración {version} (ancho medio "
                  f"{_num(glob.get('ancho_medio'), 1)} pasajeros)", _pct(glob.get("cobertura_pct")),
                  "modelo/calibracion_condicional.json"))


def _alertas(c: list) -> None:
    obs = _json("alertas/backtest_alertas.json") or {}
    pd_ = obs.get("por_defecto", {})
    c.append(("Alertas observadas por ruta y día (15-sep a 31-dic-2025)", _num(pd_.get("observadas_por_ruta_dia")),
              "alertas/backtest_alertas.json"))
    pro = _json("alertas/backtest_alertas_pronostico.json") or {}
    por = (pro.get("variantes", {}).get("franja", {}) or {}).get("por_codigo", {})
    for cod in ("ALT-001", "ALT-002", "ALT-003", "ALT-004"):
        d = por.get(cod) or {}
        c.append((f"{cod} de pronóstico por ruta y día (lift {_num(d.get('lift'), 2)})", _num(d.get("por_ruta_dia")),
                  "alertas/backtest_alertas_pronostico.json"))
    con = _json("alertas/revision_doble/conciliacion.json") or {}
    kappa = (con.get("acuerdo_antes_de_conciliar", {}).get("global", {}) or {}).get("kappa")
    c.append(("Revisión doble de 96 alertas: kappa entre revisores (automatizados)", _num(kappa),
              "alertas/revision_doble/conciliacion.json"))


def _calidad(c: list) -> None:
    for rel, nombre in (("pruebas/suite_final.xml", "Suite completa final"),
                        ("pruebas/ci/pytest.xml", "CI en copia limpia")):
        j = _junit(rel)
        txt = SIN if j is None else (f"{j['casos']} casos: {j['aprobadas']} aprobados, {j['fallas']} fallas, "
                                     f"{j['errores']} errores, {j['omitidas']} omitidos")
        c.append((nombre, txt, rel))
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
    for rel, nombre in (("pruebas/k6_consultas.json", "k6, consultas paginadas"),
                        ("pruebas/k6_volumen.json", "k6 con un año de resultados")):
        k = _json(rel) or {}
        if "metrics" not in k and isinstance(k.get("carga"), dict):   # k6_volumen.json guarda el resumen en «carga»
            k = k["carga"]
        m = k.get("metrics", {})
        dur = m.get("http_req_duration") or {}
        fal = (m.get("http_req_failed") or {}).get("value")
        txt = SIN if not dur else f"p95 {_num(dur.get('p(95)'), 1)} ms, errores {_pct((fal or 0) * 100, 2)}"
        c.append((nombre, txt, rel))


def cifras() -> list[tuple[str, str, str]]:
    c: list[tuple[str, str, str]] = []
    _modelo(c)
    _alertas(c)
    _calidad(c)
    _carga(c)
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    filas = cifras()
    if a.json:
        print(json.dumps([{"cifra": n, "valor": v, "evidencia": f"docs/evidencias/{r}"} for n, v, r in filas],
                         ensure_ascii=False, indent=1))
        return 0
    print("| Cifra | Valor | Evidencia |")
    print("|---|---|---|")
    for n, v, r in filas:
        print(f"| {n} | {v} | `api_frecuencias/docs/evidencias/{r}` |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
