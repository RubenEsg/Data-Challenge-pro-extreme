"""Demostración del ciclo completo de la especificación (§14.2 «Demostración») contra la API en marcha.

Línea de tiempo con los valores por omisión (los mismos que pasa scripts/verificar_despliegue.py):
  modelo activo   hgb_fv2_20250831_s42: corte 2025-08-31; sus 61 días de validación (con ellos se calibró su banda
                  P10-P90) terminan el 2025-10-31, así que hasta esa fecha todo está «dentro de su muestra».
  (1) llegada de información nueva     carga inicial hasta --hasta (2025-08-30); llega un día (2025-08-31) y después
                                        los días hasta la marca de agua M = --corte + 61 días (2025-11-30).
  (2) lectura incremental              cada ejecución lee solo lo posterior a su marca de agua; repetirla no lee nada.
  (3) evaluación del error             error del modelo activo en los días recién llegados y monitoreo (§9.4).
  (4) modelo candidato                 entrenamiento (job) con datos_hasta = M y corte M - 61 días = --corte: el
                                        candidato solo ve lo que llegó. Si la política de aprendizaje continuo ya lo
                                        encoló al cerrar la ejecución (periodicidad, degradación, deriva o cobertura),
                                        se espera ese mismo job en lugar de duplicarlo con POST /models/train.
  (5) comparación con el activo        el candidato queda en sombra los `sombra_dias` días siguientes a M; llegan esos
                                        días y los dos modelos se miden en la MISMA ventana, fuera de la muestra de los
                                        dos (posterior a M y al 2025-10-31) y con datos reales en la serie empaquetada
                                        (llega hasta el 2025-12-31).
  (6) decisión                         la compuerta de cuatro criterios (politica.compuerta) activa al candidato
                                        (auditado; --revertir lo deshace con POST /models/rollback) o lo rechaza con
                                        los criterios que fallaron; un rechazado no se activa sin forzar=true.

Uso:  set SOBUSA_API_URL=http://127.0.0.1:8000 & set SOBUSA_API_KEY=<clave admin>
      python scripts/demo_ciclo_api.py --hasta 2025-08-30 --corte 2025-09-30 [--revertir] [--salida archivo.txt]
La clave llega SOLO por el entorno (activar o revertir un modelo exige el rol admin). La base debe estar recién
migrada (sin ejecuciones previas): la primera ejecución es la carga inicial. El cliente HTTP es el de
scripts/cliente_http.py (keep-alive corto y un reintento solo en GET y HEAD).
Este guion solo habla por HTTP: no escribe en datos/. Quien escribe es la API que atiende: el entrenamiento del paso
(4) deja el candidato en su MODELOS_DIR. Con la pila de Docker eso queda dentro del contenedor
(scripts/verificar_despliegue.py). Si la API es un uvicorn de este checkout, arránquela con DATA_DIR y MODELOS_DIR en
una copia de datos/, para que el repositorio quede igual.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliente_http import cabeceras_api, crear_cliente  # noqa: E402

ZONA = ZoneInfo("America/Bogota")
API = "/api/v1"
DIAS_VALIDACION = 61             # app/servicios/politica.py: el candidato valida (y calibra) con 61 días tras su corte
FIN_SERIE = date(2025, 12, 31)   # último día de datos/demanda_horaria.parquet, la serie empaquetada
_LINEAS: list[str] = []
_NOTIFICACIONES = {"simulada": 0, "omitida": 0}


def decir(*partes) -> None:
    linea = " ".join(str(p) for p in partes)
    _LINEAS.append(linea)
    print(linea, flush=True)


def titulo(numero: int, texto: str) -> None:
    decir(f"\n({numero}) {texto}")


def fecha(valor) -> date | None:
    """Día de datos (America/Bogota) de un valor de la API: «2025-08-31T00:00:00-05:00» o «2025-08-31»."""
    if not valor:
        return None
    texto = str(valor)
    if "T" in texto:
        instante = datetime.fromisoformat(texto)
        return (instante.astimezone(ZONA) if instante.tzinfo else instante).date()
    return date.fromisoformat(texto[:10])


def pct(x) -> str:
    """Las métricas de la compuerta y del monitoreo son fracciones (0,147 = 14,7 %)."""
    if x is None:
        return "sin dato"
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(pct(v) for v in x) + "]"
    return f"{float(x) * 100:.2f} %"


def esperar(c: httpx.Client, execution_id: str, limite_s: int = 1800) -> dict:
    fin = time.time() + limite_s
    ultimo = ""
    while time.time() < fin:
        d = c.get(f"{API}/frequency/executions/{execution_id}").json()
        if d["estado"] in ("ok", "error"):
            return d
        estado = f"{d.get('etapa') or d['estado']} {float(d.get('progreso') or 0):.0f} %"
        if estado != ultimo:
            decir(f"    ... {estado}")
            ultimo = estado
        time.sleep(1)
    raise TimeoutError(execution_id)


def notificaciones(d: dict) -> tuple[int, int]:
    """metricas.notificaciones_por_estado: «simulada» (enviada al canal simulado) u «omitida» (bajo la severidad)."""
    por_estado = (d.get("metricas") or {}).get("notificaciones_por_estado") or {}
    return int(por_estado.get("simulada", 0)), int(por_estado.get("omitida", 0))


def ejecutar(c: httpx.Client, hasta: date, etiqueta: str) -> dict:
    t0 = time.time()
    r = c.post(f"{API}/frequency/executions", json={"hasta": hasta.isoformat()},
               headers={"X-Correlation-Id": f"demo-{etiqueta}-{hasta.isoformat()}"})
    r.raise_for_status()
    d = esperar(c, r.json()["execution_id"])
    simuladas, omitidas = notificaciones(d)
    _NOTIFICACIONES["simulada"] += simuladas
    _NOTIFICACIONES["omitida"] += omitidas
    decir(f"    ejecución {d['execution_id']} ({etiqueta}, hasta {hasta}): {d['estado']} en {time.time() - t0:.1f} s; "
          f"filas leídas {d['filas_leidas']}, válidas {d['filas_validas']}")
    decir(f"    predicciones {d['predicciones']}, recomendaciones {d['recomendaciones']}, alertas {d['alertas']}; "
          f"notificaciones simuladas {simuladas}, omitidas {omitidas}")
    decir_corto_plazo(d.get("metricas") or {})
    if d["estado"] != "ok":
        decir("    MENSAJE:", d.get("mensaje"))
    return d


def decir_corto_plazo(m: dict) -> None:
    """RF-005 en el ciclo: lo leído en bloques de 15 minutos (y lo excluido por VAL-009), los pronósticos de 30, 60 y
    120 min con su recomendación y el monitoreo del modelo de corto plazo."""
    lec, cp, mon = (m.get("lectura_corto_plazo") or {}), (m.get("corto_plazo") or {}), (m.get("monitoreo_corto_plazo")
                                                                                         or {})
    if lec:
        decir(f"    corto plazo · lectura ({lec.get('fuente') or '—'}): {lec.get('dias', 0)} días-ruta, "
              f"{lec.get('celdas', 0)} celdas válidas, {lec.get('excluidas', 0)} excluidas por VAL-009, "
              f"{lec.get('guardadas', 0)} guardadas en subidas_15min (las de un día del panel ya están empaquetadas)")
    if cp:
        decir(f"    corto plazo · pronósticos {cp.get('pronosticos', 0)} ({cp.get('model_id') or '—'}, instante "
              f"{(cp.get('instante') or '—')[:16]}), recomendaciones {cp.get('recomendaciones', 0)}, "
              f"omitidos {len(cp.get('omitidos') or [])}")
    if mon.get("estado"):
        w, cob = mon.get("wape_movil"), mon.get("cobertura_p10_p90")
        decir(f"    corto plazo · monitoreo {mon['estado']}: WAPE móvil "
              f"{'—' if w is None else f'{100 * w:.2f} %'}, cobertura P10-P90 "
              f"{'—' if cob is None else f'{100 * cob:.1f} %'} ({mon.get('desde')} a {mon.get('hasta')})")


def duracion(d: dict) -> str:
    """Lo que tardó el job en el trabajador (iniciado_en -> terminado_en), no lo que esperó este script."""
    try:
        s = (datetime.fromisoformat(d["terminado_en"]) - datetime.fromisoformat(d["iniciado_en"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return "sin dato"
    return f"{s:.1f} s"


def metricas_cortas(m: dict | None) -> str:
    if not m:
        return "sin datos"
    partes = [f"WAPE {m.get('wape')} %", f"MAE {m.get('mae')}"]
    if m.get("sesgo_pct") is not None:
        partes.append(f"sesgo {m.get('sesgo_pct')} %")
    cobertura = m.get("cobertura_p10_p90_conformal", m.get("cobertura_p10_p90"))
    if cobertura is not None:
        partes.append(f"cobertura P10-P90 {cobertura} %")
    if m.get("n") is not None:
        partes.append(f"n = {m.get('n')}")
    return ", ".join(partes)


def politica_de(d: dict) -> dict:
    """Lo que decidió la política al cerrar el ciclo (reversión, sombra, reentreno), en metricas.monitoreo.politica."""
    return ((d.get("metricas") or {}).get("monitoreo") or {}).get("politica") or {}


def modelo_activo(c: httpx.Client, familia: str = "horario") -> dict | None:
    """El activo de la familia (cada familia tiene a lo sumo uno): el ciclo de §14.2 es el del modelo horario; el de
    corto plazo se monitorea en cada ciclo y tiene su propia compuerta."""
    for m in c.get(f"{API}/models", params={"limite": 100, "familia": familia}).json().get("items", []):
        if m["estado"] == "activo" and m.get("familia", familia) == familia:
            return m
    return None


def limite_en_muestra(m: dict) -> date | None:
    """Último día que un modelo ya vio: su corte + 61 días de validación, o el fin de la serie de su sombra."""
    corte = fecha(m.get("data_cutoff"))
    limite = corte + timedelta(days=DIAS_VALIDACION) if corte else None
    sombra = (m.get("metricas") or {}).get("sombra") or {}
    if sombra.get("datos_hasta") and sombra.get("estado") not in (None, "no_aplica"):
        limite = max(filter(None, (limite, fecha(sombra["datos_hasta"]))))
    return limite


def evaluar_ventana(c: httpx.Client, model_id: str, desde: date, hasta: date) -> dict | None:
    r = c.get(f"{API}/models/{model_id}/evaluation", params={"desde": desde.isoformat(), "hasta": hasta.isoformat()})
    return r.json().get("ventana") if r.status_code == 200 else None


def imprimir_criterios(criterios: list[dict]) -> None:
    for crit in criterios:
        decir(f"    [{'cumple' if crit.get('ok') else 'NO cumple'}] {crit.get('criterio')}: candidato "
              f"{pct(crit.get('candidato'))}, referencia {pct(crit.get('referencia'))}")


def argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default=os.environ.get("SOBUSA_API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 8, 30),
                   help="fecha de la carga inicial; lo posterior es la información nueva")
    p.add_argument("--corte", type=date.fromisoformat, default=date(2025, 9, 30),
                   help="corte de entrenamiento del candidato; la información nueva llega hasta corte + 61 días, que "
                        "es su datos_hasta")
    p.add_argument("--aprobado-por", default="comite_operacion")
    p.add_argument("--revertir", action="store_true",
                   help="si el candidato queda activo, demostrar la reversión con POST /models/rollback")
    p.add_argument("--salida", type=Path, help="copia de la salida en este archivo (UTF-8)")
    return p.parse_args()


def guardar(a: argparse.Namespace, codigo: int) -> int:
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    return codigo


def main() -> int:  # noqa: C901, PLR0912, PLR0915 - el guion sigue los seis pasos de §14.2 en orden
    a = argumentos()
    c = crear_cliente(a.base, timeout=300, headers=cabeceras_api())
    inicio = datetime.now(ZONA)
    decir(f"=== Ciclo completo de la especificación v1.5 §14.2 «Demostración» · API {a.base} · "
          f"{inicio:%Y-%m-%d %H:%M:%S %z} (America/Bogota) ===")
    decir("Estado: GET /health ->", c.get("/health").json())
    activo0 = modelo_activo(c)
    if activo0 is None:
        decir("No hay modelo activo en el registro: no se puede demostrar el ciclo.")
        return guardar(a, 1)
    umbrales = c.get(f"{API}/thresholds").json()
    valores = umbrales.get("valores") or {}
    sombra_dias = int(float(valores.get("sombra_dias", 14)))
    marca_objetivo = a.corte + timedelta(days=DIAS_VALIDACION)
    limite_activo = limite_en_muestra(activo0)
    ventana = (marca_objetivo + timedelta(days=1), marca_objetivo + timedelta(days=sombra_dias))
    decir(f"Modelo activo al empezar: {activo0['model_id']} (variables {activo0.get('feature_version')}, corte "
          f"{fecha(activo0.get('data_cutoff'))}; vio datos hasta {limite_activo}: corte + {DIAS_VALIDACION} días de "
          "validación, con los que se calibró su banda P10-P90)")
    decir(f"Umbrales v{umbrales.get('version')} ({umbrales.get('estado')}): sombra_dias {sombra_dias}, "
          f"activacion_automatica {valores.get('activacion_automatica')}, reentreno_en_ciclo "
          f"{valores.get('reentreno_en_ciclo')}, reentreno_periodicidad_dias "
          f"{valores.get('reentreno_periodicidad_dias')}, wape_max {valores.get('wape_max')}")
    decir(f"Línea de tiempo: carga inicial hasta {a.hasta}; la información nueva llega hasta {marca_objetivo} "
          f"(corte del candidato {a.corte} + {DIAS_VALIDACION} días); sombra y comparación "
          f"{ventana[0]} .. {ventana[1]}.")
    problemas = []
    if marca_objetivo <= a.hasta + timedelta(days=1):
        problemas.append(f"--corte + {DIAS_VALIDACION} días ({marca_objetivo}) debe ser posterior a {a.hasta} + 1 día")
    if ventana[1] > FIN_SERIE:
        problemas.append(f"la ventana de comparación termina el {ventana[1]}, después del último día de la serie "
                         f"empaquetada ({FIN_SERIE}); use un --corte anterior")
    if problemas:
        decir("Fechas incoherentes:", "; ".join(problemas))
        return guardar(a, 1)
    if limite_activo and ventana[0] <= limite_activo:
        decir(f"Aviso: la ventana empieza dentro de la muestra del activo (hasta {limite_activo}); la comparación "
              "favorecería al activo. Use un --corte posterior.")

    titulo(1, "Llegada de información nueva")
    decir(f"    Carga inicial: el histórico disponible hasta {a.hasta} (primera ejecución, sin marca de agua).")
    e0 = ejecutar(c, a.hasta, "carga-inicial")
    nuevo = a.hasta + timedelta(days=1)
    decir(f"    Llega un día nuevo: {nuevo} queda disponible en la fuente.")
    e1 = ejecutar(c, nuevo, "dia-nuevo")
    decir(f"    Siguen llegando días: {nuevo + timedelta(days=1)} .. {marca_objetivo}, hasta la marca de agua con la "
          f"que se entrenará el candidato (su corte {a.corte} más {DIAS_VALIDACION} días de validación).")
    e2 = ejecutar(c, marca_objetivo, "dias-nuevos")
    if any(e["estado"] != "ok" for e in (e0, e1, e2)):
        decir("    Alguna ejecución no terminó bien; se detiene la demostración.")
        return guardar(a, 1)

    titulo(2, "Lectura incremental")
    decir(f"    POST {API}/frequency/executions lee SOLO lo posterior a la marca de agua (solo lectura de la fuente):")
    for etiqueta, e in (("carga inicial", e0), ("día nuevo", e1), ("días nuevos", e2)):
        decir(f"    {etiqueta:13s} marca de agua {e['marca_agua_anterior']} -> {e['marca_agua_nueva']}: filas leídas "
              f"{e['filas_leidas']}, válidas {e['filas_validas']}")
    decir("    Repetición sin datos nuevos (la misma fecha): no relee ni duplica nada")
    rep = ejecutar(c, marca_objetivo, "repeticion")
    decir(f"    repetición    marca de agua {rep['marca_agua_anterior']} -> {rep['marca_agua_nueva']}: filas leídas "
          f"{rep['filas_leidas']}, predicciones {rep['predicciones']}")
    if politica_de(e2).get("entrenamiento_encolado"):
        decir("    (la repetición esperó en la cola detrás del entrenamiento que encoló la política, ver (3) y (4))")

    titulo(3, "Evaluación del error")
    for etiqueta, e, desde in (("día nuevo", e1, nuevo), ("días nuevos", e2, nuevo + timedelta(days=1))):
        ev = (e.get("metricas") or {}).get("evaluacion_error") or {}
        decir(f"    Modelo activo en lo recién llegado, {etiqueta} ({desde} .. {fecha(e['marca_agua_nueva'])}): "
              f"{metricas_cortas(ev) if ev else 'sin observaciones'}")
    if limite_activo and limite_activo < marca_objetivo:
        fuera = evaluar_ventana(c, activo0["model_id"], limite_activo + timedelta(days=1), marca_objetivo)
        decir(f"    De esos días, los posteriores a su muestra ({limite_activo + timedelta(days=1)} .. "
              f"{marca_objetivo}): {metricas_cortas(fuera)}")
    for f in c.get(f"{API}/monitoring", params={"limite": 3}).json().get("items", []):
        decir(f"    monitoreo {f['hasta']} {f['model_id']} ({f['rol']}): {f['estado']}; WAPE móvil "
              f"{pct(f['wape_movil'])}, cobertura P10-P90 {pct(f['cobertura_p10_p90'])}, PSI máx {f['psi_max']} "
              f"({f['psi_variable_max']})")
    pol = politica_de(e2)
    reentreno = pol.get("reentreno") or {}
    decir(f"    política de aprendizaje continuo al cerrar la ejecución hasta {marca_objetivo}: reentrenar "
          f"{reentreno.get('reentrenar')}, motivos {reentreno.get('motivos')}, bloqueos {reentreno.get('bloqueos')}")

    titulo(4, "Modelo candidato")
    encolado = pol.get("entrenamiento_encolado")
    if encolado:
        decir(f"    La política ya encoló el entrenamiento al cerrar la ejecución (job {encolado}, hasta "
              f"{reentreno.get('hasta')}, datos_hasta {reentreno.get('datos_hasta')}): es el mismo trabajo que "
              f"POST {API}/models/train con esos parámetros, así que se espera ese job en vez de duplicarlo.")
        ident = str(encolado)
    else:
        cuerpo = {"hasta": a.corte.isoformat(), "datos_hasta": marca_objetivo.isoformat(),
                  "solicitado_por": a.aprobado_por}
        r = c.post(f"{API}/models/train", json=cuerpo)
        r.raise_for_status()
        decir(f"    POST {API}/models/train {cuerpo} -> {r.status_code} (job asíncrono con progreso)")
        ident = r.json()["execution_id"]
    e = esperar(c, ident)
    decir(f"    entrenamiento {e['estado']} en {duracion(e)} (trabajador de la cola): {e.get('mensaje')}")
    if e["estado"] != "ok" or not e.get("model_id"):
        return guardar(a, 1)
    candidato = e["model_id"]
    ficha = c.get(f"{API}/models/{candidato}").json()
    sombra = (ficha.get("metricas") or {}).get("sombra") or {}
    serie = (ficha.get("metricas") or {}).get("serie") or {}
    decir(f"    candidato {candidato}: estado {ficha['estado']}, variables {ficha.get('feature_version')}, corte "
          f"{fecha(ficha.get('data_cutoff'))}, datos hasta {sombra.get('datos_hasta') or serie.get('datos_hasta')}, "
          f"sha256 {str(ficha.get('sha256'))[:12]}…")
    cal = sombra.get("calibracion") or {}
    decir(f"    sombra: {sombra.get('estado')} del {sombra.get('inicio')} al {sombra.get('fin')} "
          f"({sombra.get('dias')} días); banda P10-P90 con su propia calibración {cal.get('version')} por "
          f"{cal.get('grupos')}, {cal.get('ajustado_con')}")
    if sombra.get("estado") != "en_sombra":
        decir("    El candidato no quedó en sombra: falta la ventana de comparación.")
        return guardar(a, 1)

    titulo(5, "Comparación con el modelo activo")
    desde, hasta = fecha(sombra.get("inicio")), fecha(sombra.get("fin"))
    limite_cand = limite_en_muestra(ficha)
    decir(f"    Misma ventana para los dos: {desde} .. {hasta}. Por qué estas fechas: el candidato vio datos hasta "
          f"{limite_cand} (corte {fecha(ficha.get('data_cutoff'))} + {DIAS_VALIDACION} días) y el activo hasta "
          f"{limite_activo}; la ventana empieza después de los dos (fuera de la muestra de ambos) y termina antes del "
          f"{FIN_SERIE}, el último día de la serie empaquetada, así que hay datos reales para medirlos.")
    decir(f"    Llegan los {sombra.get('dias')} días de la sombra: en ese ciclo el candidato predice lo mismo que el "
          "activo (sin decidir nada) y, al completarse la ventana, la compuerta compara a los dos en ella.")
    e3 = ejecutar(c, hasta, "sombra")
    for etiqueta, mid in (("candidato", candidato), ("activo", activo0["model_id"])):
        decir(f"    {etiqueta:9s} {mid}: {metricas_cortas(evaluar_ventana(c, mid, desde, hasta))}")
    for s in politica_de(e3).get("sombra") or []:
        decir(f"    compuerta de sombra de {s.get('model_id')}: {s.get('estado')}")

    titulo(6, "Decisión de activarlo o rechazarlo")
    ficha = c.get(f"{API}/models/{candidato}").json()
    metricas = ficha.get("metricas") or {}
    decision = metricas.get("decision_sombra") or {}
    estado_sombra = (metricas.get("sombra") or {}).get("estado")
    codigo = 0
    if decision:
        v = decision.get("ventana") or {}
        cal = decision.get("calibracion") or {}
        decir(f"    Compuerta de cuatro criterios (politica.compuerta) en {v.get('desde')} .. {v.get('hasta')}, "
              f"umbrales v{decision.get('umbrales_version')}, banda calibrada {cal.get('candidato')} del candidato "
              f"frente a {cal.get('activo')} del activo:")
        imprimir_criterios(decision.get("criterios") or [])
    if ficha["estado"] == "activo":
        decir(f"    ACTIVADO {candidato} por la compuerta (aprobado por {ficha.get('aprobado_por')}, anterior "
              f"{ficha.get('anterior_model_id')}, activado el {ficha.get('activado_en')}); queda auditado.")
        if a.revertir:
            rb = c.post(f"{API}/models/rollback", json={"usuario": a.aprobado_por,
                                                         "motivo": "demostración del mecanismo de reversión"})
            decir(f"    Reversión (POST {API}/models/rollback): {rb.status_code} -> activo "
                  f"{rb.json().get('model_id') if rb.status_code == 200 else rb.text[:200]}")
            codigo = 0 if rb.status_code == 200 else 1
    elif estado_sombra == "aprobado":
        decir("    La compuerta aprobó y activacion_automatica = 0: lo activa un admin con la misma compuerta en la "
              "misma ventana.")
        r = c.post(f"{API}/models/{candidato}/activate",
                   json={"aprobado_por": a.aprobado_por, "motivo": "ciclo de demostración §14.2",
                         "validacion_desde": desde.isoformat(), "validacion_hasta": hasta.isoformat()})
        decir(f"    POST {API}/models/{candidato}/activate -> {r.status_code} "
              f"{r.json().get('estado') if r.status_code == 200 else (r.json().get('error') or {}).get('mensaje')}")
        codigo = 0 if r.status_code in (200, 409) else 1   # 409 = la compuerta lo rechazó: también es decisión
        if r.status_code == 200 and a.revertir:
            rb = c.post(f"{API}/models/rollback", json={"usuario": a.aprobado_por,
                                                         "motivo": "demostración del mecanismo de reversión"})
            decir(f"    Reversión (POST {API}/models/rollback): {rb.status_code} -> activo "
                  f"{rb.json().get('model_id') if rb.status_code == 200 else rb.text[:200]}")
            codigo = 0 if rb.status_code == 200 else 1
    elif ficha["estado"] == "rechazado":
        decir(f"    RECHAZADO {candidato}: {ficha.get('motivo')}. El activo {activo0['model_id']} sigue.")
        r = c.post(f"{API}/models/{candidato}/activate", json={"aprobado_por": a.aprobado_por,
                                                               "motivo": "intento de activar un rechazado"})
        err = r.json().get("error", {}) if r.status_code != 200 else {}
        decir(f"    Intento de activarlo sin forzar (POST {API}/models/{candidato}/activate): {r.status_code} "
              f"{err.get('codigo')}: la gobernanza no se salta sin forzar=true y un motivo auditado.")
        if a.revertir:
            decir("    --revertir: no hay nada que revertir, el candidato no llegó a activarse.")
        codigo = 0 if r.status_code == 409 else 1
    else:
        decir(f"    Sin decisión: el candidato sigue {ficha['estado']} (sombra {estado_sombra}); fallos de la "
              f"ejecución: {(e3.get('metricas') or {}).get('fallos')}")
        codigo = 1
    decir("    registro de modelos:", [(m["model_id"], m.get("familia"), m["estado"])
                                       for m in c.get(f"{API}/models", params={"limite": 100}).json()["items"]])
    decir(f"\nNotificaciones de las ejecuciones (metricas.notificaciones_por_estado): simuladas "
          f"{_NOTIFICACIONES['simulada']}, omitidas {_NOTIFICACIONES['omitida']}.")
    decir(f"Ciclo completo en {(datetime.now(ZONA) - inicio).total_seconds():.0f} s.")
    return guardar(a, codigo)


if __name__ == "__main__":
    sys.exit(main())
