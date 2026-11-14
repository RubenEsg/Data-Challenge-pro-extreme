"""Análisis de sensibilidad de la recomendación (§10.3: «mejorar el cálculo con la incertidumbre de la demanda, las
restricciones reales y el análisis de sensibilidad») y escenarios RF-008, con casos reales.

Para cada ruta y franja (día laboral y sábado de 2025, horas pico y valle):
- demanda POR HORA y banda P10-P90 calibrada del modelo activo (inferencia.predecir, desglose por hora);
- ciclo, flota e intervalo programado de la hora (datos/parametros_operativos_hora.parquet, D1);
- tipologías de capacidad de la ruta (app/servicios/tipologias_flota.json, de flota_sobusa.csv sin placas);
- recomendación de §10.2 (MILP de la franja, verificado contra la enumeración exacta), línea base de §10.3,
  frecuencia actual programada frente a recomendada y 23 variaciones de un parámetro a la vez.

Solo LEE datos/ (modelos y parquets); escribe docs/evidencias/optimizacion/sensibilidad.json y sensibilidad.md.
Uso:  .venv\\Scripts\\python scripts/sensibilidad.py [--salida DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import datos, inferencia  # noqa: E402
from app.servicios import optimizacion as O  # noqa: E402
from app.servicios.ejecucion import ZONA, json_seguro  # noqa: E402

UMBRALES = {"ocupacion_objetivo_min": 0.65, "ocupacion_objetivo_max": 0.85, "headway_minimo_min": 2.0,
            "headway_maximo_min": 10.0, "espera_max_min": 5.0,
            "ocupacion_critica": 0.90}            # versión 1 de threshold_config (migración 0001)
CASOS = [(ruta, fecha, hora) for ruta in ("SILENCIO", "CRA 54", "CL 72")
         for fecha, hora in ((date(2025, 3, 11), 7), (date(2025, 3, 11), 11), (date(2025, 3, 11), 17),
                             (date(2025, 3, 15), 7))]
# festivo entre semana (lunes 17-nov-2025): se compara con la programación de domingo o festivo, como el plan D5
CASOS.append(("SILENCIO", date(2025, 11, 17), 7))
DIA_CICLO = date(2025, 11, 19)          # día laboral de la prueba reservada para medir la memoria del MILP
SIN_TIEMPOS = ("segundos",)


def _f(x, d=1):
    if x is None:
        return "—"
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def demanda_hora(ruta: str, fecha: date, hora: int) -> dict:
    """Pronóstico de la hora completa con su banda calibrada (ventana de 60 min que empieza a la hora en punto)."""
    instante = datetime(fecha.year, fecha.month, fecha.day, hora, 0, tzinfo=ZONA)
    r = inferencia.predecir(ruta, instante, 60)
    fila = next((h for h in r["variables"].get("por_hora") or [] if int(h["hora"]) == hora), None)
    if fila is None:
        return {"demanda_hora": r["pasajeros"], "p10_hora": r["p10"], "p90_hora": r["p90"], "model_id": r["model_id"]}
    return {"demanda_hora": float(fila["pasajeros_hora"]), "p10_hora": fila.get("p10_hora"),
            "p90_hora": fila.get("p90_hora"), "model_id": r["model_id"]}


def _sin_tiempos(x):
    """La salida sin los tiempos de cálculo, para comparar dos corridas."""
    if isinstance(x, dict):
        return {k: _sin_tiempos(v) for k, v in x.items() if k not in SIN_TIEMPOS}
    if isinstance(x, list):
        return [_sin_tiempos(v) for v in x]
    return x


def _pasada_ciclo(franjas: list[tuple]) -> tuple[float, list]:
    t = time.perf_counter()
    salidas = [O.recomendacion_franja(datos.ruta_info(ruta), UMBRALES, 1, hora=hora, fecha=DIA_CICLO,
                                      demanda_hora=d["demanda_hora"], demanda_p90=d["p90_hora"],
                                      demanda_p10=d["p10_hora"]) for ruta, hora, d in franjas]
    return time.perf_counter() - t, json.dumps(json_seguro(_sin_tiempos(salidas)), sort_keys=True)


def memoria_milp() -> dict:
    """Las 51 franjas de un día del ciclo (3 rutas × 17 horas) dos veces: en frío (memoria del MILP vacía) y de nuevo
    (la misma franja reutiliza la solución). Los resultados deben ser idénticos; solo cambia el tiempo."""
    franjas = [(ruta, hora, demanda_hora(ruta, DIA_CICLO, hora)) for ruta in ("SILENCIO", "CRA 54", "CL 72")
               for hora in range(4, 21)]
    O.limpiar_memoria_milp()
    frio, a = _pasada_ciclo(franjas)
    caliente, b = _pasada_ciclo(franjas)
    res = {"dia": DIA_CICLO.isoformat(), "franjas": len(franjas), "segundos_en_frio": round(frio, 2),
           "segundos_con_memoria": round(caliente, 2), "aceleracion": round(frio / max(caliente, 1e-9), 1),
           "resultados_identicos": a == b}
    print(f"memoria del MILP: {len(franjas)} franjas, {frio:.2f} s en frío y {caliente:.2f} s con memoria; "
          f"idénticos: {a == b}")
    return res


def correr(salida: Path) -> dict:
    t0 = time.perf_counter()
    casos = []
    for ruta, fecha, hora in CASOS:
        info = datos.ruta_info(ruta)
        d = demanda_hora(ruta, fecha, hora)
        t1 = time.perf_counter()
        r, entradas = O.recomendacion_franja(info, UMBRALES, 1, hora=hora, fecha=fecha,
                                             demanda_hora=d["demanda_hora"], demanda_p90=d["p90_hora"],
                                             demanda_p10=d["p10_hora"], incluir_sensibilidad=True)
        seg = time.perf_counter() - t1
        kw = dict(ruta=ruta, hora=hora, demanda_hora=d["demanda_hora"], demanda_p90=d["p90_hora"],
                  demanda_p10=d["p10_hora"], parametros=entradas["parametros_objetivo"],
                  tipologias=O.tipologias_ruta(ruta, entradas["flota_disponible"]),
                  **{k: entradas[k] for k in ("capacidad", "ocupacion_objetivo", "tiempo_ciclo_min", "flota_disponible",
                                              "headway_min", "headway_max", "frecuencia_actual_min",
                                              "ocupacion_critica")}, factor_carga=entradas.get("factor_carga"))
        verif = O.optimizar(**kw, verificar=True)["solver"]["verificacion_enumeracion"]
        casos.append({"ruta": ruta, "fecha": fecha.isoformat(), "tipo_dia": (r.get("contexto_franja") or {})
                      .get("tipo_dia"), "hora": hora, "demanda": d, "entradas": entradas, "resultado": r,
                      "verificacion_milp_vs_enumeracion": verif, "segundos_con_sensibilidad": round(seg, 2)})
        print(f"{ruta:<9} {fecha} {hora:>2} h: demanda {d['demanda_hora']:.0f} (P90 {d['p90_hora']:.0f}) -> "
              f"{r['buses_hora']} buses/h viable={r['viable']} | base §10.3 {r['linea_base_10_3']['buses_hora']} | "
              f"{r['sensibilidad']['resumen']} | MILP=enumeración: {verif.get('coinciden')} ({seg:.1f} s)")
    resultado = {"generado": datetime.now(ZONA).isoformat(timespec="seconds"), "umbrales": UMBRALES,
                 "parametros_objetivo": {n: v for n, (v, _d) in O.PARAMETROS_OBJETIVO.items()},
                 "variaciones": [list(v) for v in O.VARIACIONES_SENSIBILIDAD], "casos": casos,
                 "memoria_milp": memoria_milp(),
                 "segundos_total": round(time.perf_counter() - t0, 1)}
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "sensibilidad.json").write_text(json.dumps(json_seguro(resultado), ensure_ascii=False, indent=1) + "\n",
                                              encoding="utf-8")
    (salida / "sensibilidad.md").write_text(markdown(resultado), encoding="utf-8")
    return resultado


def markdown(res: dict) -> str:
    L = ["# Sensibilidad de la recomendación de frecuencia (§10.2, §10.3, RF-008)", "",
         f"Generado por `scripts/sensibilidad.py` el {res['generado']} ({res['segundos_total']} s). Datos: pronóstico "
         "por hora y banda P10-P90 calibrada del modelo activo; ciclo, flota e intervalo programado de la hora (D1); "
         "factor de carga crítica por ruta, día de la semana y hora (mediana 2025 de los insumos de D5); tipologías "
         "de `tipologias_flota.json`; umbrales de la versión 1 y pesos por omisión del código.", "",
         "## Formulación", "",
         "min α·costo_operativo + β·tiempo_espera + γ·penalización_sobreocupación + δ·desviación_frecuencia, con "
         "(montos en COP por hora):", "",
         "- costo_operativo = Σ_t n_t × (ciclo/60 × costo_bus_hora + km_ciclo × costo_km);",
         "- tiempo_espera = pasajeros/h × (60/k)/2 × (1 + cv²) / 60 × valor_tiempo_espera;",
         "- penalización = penalidad × E[(L − C × ocupación_crítica)+], L lognormal con mediana factor × demanda y "
         "dispersión del P90 calibrado;",
         "- desviación = costo_cambio × |k − k_programado|.", "",
         "Sujeto a: k = Σ_t n_t entre ceil(60/headway_max) y floor(60/headway_min); capacidad efectiva "
         "C × ocupación_objetivo ≥ cuantil del nivel de servicio de la carga crítica (0,90 = P90); vehículos "
         "Σ_t ceil(ciclo × n_t / 60) ≤ flota y n_t ≤ disponibles_t × 60 / ciclo por tipología. MILP de PuLP/CBC "
         "con una binaria por nivel k (espera) y cortes tangentes de la sobrecarga (convexa) en todas las capacidades "
         "alcanzables, verificado contra la enumeración exacta.", "",
         "## Casos", "",
         "Dos líneas base de §10.3: la **literal** (ceil(demanda puntual / capacidad efectiva), factor 1) y la "
         "**ajustada** (carga crítica = factor de carga × P90 calibrado, la que se compara con §10.2). El headway "
         "máximo es el efectivo, min(headway_maximo_min, 2 × espera_max_min) = 10 min; «sobreoferta» marca una "
         "ocupación esperada menor que ocupacion_objetivo_min (65 %).", "",
         "| Ruta | Día | Hora | Demanda/h (P90) | Recomendada §10.2 | Viable | Límites que mandan | §10.3 literal | "
         "§10.3 ajustada | Sobreoferta | Programada | Variaciones que cambian | MILP = enumeración |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in res["casos"]:
        r = c["resultado"]
        b = r["linea_base_10_3"]
        lit = r.get("linea_base_10_3_literal") or {}
        lit_txt = (f"{lit['buses_hora']} buses/h ({'viable' if lit['viable'] else 'no viable'})" if lit else "—")
        prog = c["entradas"].get("frecuencia_actual_min")
        rec = (f"{r['buses_hora']} buses/h · {_f(r['headway_min'], 2)} min · {r['vehiculos_requeridos']} veh."
               if r["buses_hora"] is not None else "—")
        cambian = sum(1 for v in r["sensibilidad"]["variaciones"] if v.get("cambia_la_recomendacion"))
        L.append(f"| {c['ruta']} | {c['tipo_dia']} {c['fecha']} | {c['hora']} | {_f(c['demanda']['demanda_hora'], 0)} "
                 f"({_f(c['demanda']['p90_hora'], 0)}) | {rec} | {'sí' if r['viable'] else 'no'} | "
                 f"{', '.join(r.get('limites_activos') or []) or '—'} | {lit_txt} | {b['buses_hora']} buses/h "
                 f"({'viable' if b['viable'] else 'no viable'}) | {'sí' if r.get('sobreoferta') else 'no'} | "
                 f"{_f(60 / prog, 1) + ' buses/h' if prog else '—'} | {cambian} de "
                 f"{len(r['sensibilidad']['variaciones'])} | "
                 f"{'sí' if (c['verificacion_milp_vs_enumeracion'] or {}).get('coinciden') else 'no'} |")
    L += ["", "## Efecto de cada variación (buses/h; «nv» = no viable)", ""]
    nombres = [v["variacion"] for v in res["casos"][0]["resultado"]["sensibilidad"]["variaciones"]]
    L.append("| Variación | " + " | ".join(f"{c['ruta']} {c['hora']} h {c['fecha'][5:]}" for c in res["casos"])
             + " |")
    L.append("|---|" + "---|" * len(res["casos"]))
    L.append("| base | " + " | ".join(str(c["resultado"]["buses_hora"]) + ("" if c["resultado"]["viable"] else " nv")
                                       for c in res["casos"]) + " |")
    for i, nombre in enumerate(nombres):
        celdas = []
        for c in res["casos"]:
            v = c["resultado"]["sensibilidad"]["variaciones"][i]
            celdas.append("error" if "error" in v else f"{v['buses_hora']}{'' if v['viable'] else ' nv'}")
        L.append(f"| {nombre} | " + " | ".join(celdas) + " |")
    m = res.get("memoria_milp") or {}
    if m:
        L += ["", "## Tiempo de cálculo: memoria de soluciones del MILP", "",
              f"Las {m['franjas']} franjas de un día del ciclo ({m['dia']}, 3 rutas × 17 horas, demanda y banda del "
              f"modelo activo) se resolvieron dos veces con `recomendacion_franja`: {_f(m['segundos_en_frio'], 2)} s "
              f"en frío y {_f(m['segundos_con_memoria'], 2)} s cuando cada franja ya estaba resuelta "
              f"({_f(m['aceleracion'], 1)} veces más rápido). Resultados idénticos (sin contar los tiempos): "
              f"{'sí' if m['resultados_identicos'] else 'NO'}. Casi todo el tiempo de una franja es arrancar el "
              "proceso de CBC; la memoria guarda la solución por los datos exactos del problema (límites, demanda, "
              "banda, flota, tipologías, pesos y costos) y solo los estados que no dependen del tiempo (óptimo o "
              "infactible)."]
    L += ["", "## Lectura", "",
          "- Una franja no viable sale «no viable» con su motivo; sus cifras son la mejor aproximación ejecutable "
          "(respeta flota, ciclo y headway) y se informa qué parte del nivel de servicio cubre.",
          "- Un festivo entre semana (17-nov-2025) usa el ciclo, la flota, el intervalo programado y el factor de "
          "carga de domingo o festivo, el mismo tipo de día con el que D5 planea ese día.",
          "- El nivel de servicio usa el P90 calibrado del modelo: con bandas anchas la recomendación se vuelve "
          "conservadora, y la sensibilidad a «nivel_servicio» muestra cuánto pesa esa decisión.",
          "- β (valor del tiempo de espera) y α (costo operativo) son los pesos que más mueven la frecuencia; "
          "δ ancla la recomendación a la programación vigente sin cruzar el nivel de servicio.",
          "- Los pesos y costos se cambian con PUT /api/v1/thresholds (versión nueva) o por solicitud en "
          "POST /api/v1/recommendations/calculate (campo «pesos»).", ""]
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "optimizacion")
    correr(p.parse_args().salida)


if __name__ == "__main__":
    main()
