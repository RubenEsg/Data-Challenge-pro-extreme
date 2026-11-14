"""Aprendizaje continuo controlado (RF-018, RF-019, §9.5, §18 «Deriva: champion/challenger y rollback»).

1. Decidir si reentrenar (decidir_reentreno), con umbrales versionados en threshold_config:
   - periodicidad: han llegado `reentreno_periodicidad_dias` días de datos desde lo último que vio un modelo
     (validación incluida: corte + 61 días, o el fin de la serie con la que se entrenó);
   - degradación: las últimas `reentreno_dias_degradacion` filas de monitoreo del activo tienen WAPE móvil > wape_max
     (la misma tolerancia de ALT-010);
   - deriva: alguna variable disparadora con PSI sobre su umbral de alerta (monitoreo.DISPARADORES_PSI);
   - cobertura: cobertura P10-P90 calibrada < cobertura_min.
   No reentrena si ya hay un entrenamiento en cola o corriendo, o un retador en sombra. Tampoco si el corte no se
   puede entrenar: la partición del entrenamiento (inferencia.corte_sin_datos) no deja filas útiles para entrenar
   hasta el corte o para validar después, como al comienzo de la serie. Queda en los bloqueos de la decisión, con
   «reentrenamiento omitido: datos insuficientes antes del corte» (_bloqueo_sin_datos).
2. Entrenar el candidato con el histórico VALIDADO (ai_frecuencias.demanda_observada, que reemplaza a la serie
   empaquetada en las claves que comparten) hasta `datos_hasta`; corte = datos_hasta - 61 días, de modo que la
   validación temporal son los últimos 61 días de datos reales y no se usa nada posterior a datos_hasta.
   Nunca pisa el modelo activo: si el id coincide, el artefacto nuevo lleva sufijo _r2, _r3...
   El candidato sale con su propia calibración por grupo de la banda P10-P90 (v2, el mismo esquema de grupos que la
   del activo), ajustada con SU validación y versionada junto a su artefacto con su SHA-256: la sombra y la compuerta
   comparan banda calibrada con banda calibrada.
3. Sombra: el candidato queda «en_sombra» `sombra_dias` días: en cada ciclo predice lo mismo que el activo (sin usarse
   para decidir) y se monitorea con las mismas métricas. Al completar la ventana pasa la compuerta en ESA ventana:
   WAPE ≤ WAPE del activo, WAPE ≤ wape_max, cobertura calibrada en [cobertura_aviso, cobertura_max] y
   |sesgo| ≤ sesgo_max. Si pasa y activacion_automatica = 1 se activa (auditado, aprobado_por = politica_automatica);
   con 0 queda «aprobado» para que un admin lo active con POST /models/{id}/activate. Si no pasa: «rechazado» con el
   motivo. La decisión completa queda en model_registry.metricas['decision_sombra'] y en la auditoría.
4. Reversión automática: si en los `reversion_ventana_dias` días de datos posteriores a una activación el WAPE del
   nuevo modelo supera wape_max y es peor que el del anterior en esos mismos días, se vuelve al anterior (auditado).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

LOG = logging.getLogger("api_frecuencias.politica")
UMBRALES_DEFECTO: dict[str, float] = {
    "reentreno_periodicidad_dias": 28,
    "reentreno_dias_degradacion": 3,
    "reentreno_en_ciclo": 1,
    "sombra_dias": 14,
    "sesgo_max": 0.05,
    "activacion_automatica": 1,
    "reversion_ventana_dias": 7,
    "reversion_minimo_dias": 3,
    "wape_max": 0.20,
    "cobertura_min": 0.70,
    "cobertura_aviso": 0.75,
    "cobertura_max": 0.90,
}
DIAS_VALIDACION = 61
USUARIO_POLITICA = "politica_automatica"


def umbrales_politica(umbrales: dict | None) -> dict:
    u = dict(UMBRALES_DEFECTO)
    for k, v in (umbrales or {}).items():
        try:
            u[k] = float(v)
        except (TypeError, ValueError):
            continue
    return u


def _fecha(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        from app.servicios.ejecucion import ZONA

        return v.astimezone(ZONA).date() if v.tzinfo else v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _auditar(modelo, evento: str, **datos) -> None:
    from app.servicios.ejecucion import ahora, json_seguro

    modelo.auditoria = [*(modelo.auditoria or []), json_seguro({"evento": evento, "en": ahora().isoformat(), **datos})]


def _wape(m: dict | None) -> float | None:
    if not m or m.get("wape") is None:
        return None
    w = float(m["wape"])
    return w / 100.0 if w > 1.5 else w


# ----------------------------------------------------------------------------------------------- consultas
def en_sombra(s) -> list:
    from sqlalchemy import select

    from app.modelos_db import RegistroModelo

    filas = s.scalars(select(RegistroModelo).where(RegistroModelo.estado == "candidato")).all()
    return [f for f in filas if ((f.metricas or {}).get("sombra") or {}).get("estado") == "en_sombra"]


def datos_vistos_hasta(modelo) -> date | None:
    """Último día de datos que vio un modelo: el fin de su serie (sombra.datos_hasta) o corte + 61 días."""
    sombra = (modelo.metricas or {}).get("sombra") or {}
    if sombra.get("datos_hasta"):
        return _fecha(sombra["datos_hasta"])
    corte = _fecha(modelo.data_cutoff)
    return corte + timedelta(days=DIAS_VALIDACION) if corte else None


def _ultimas_filas_monitoreo(s, model_id: str, n: int) -> list:
    from sqlalchemy import select

    from app.modelos_db import MonitoreoModelo

    return list(s.scalars(select(MonitoreoModelo).where(MonitoreoModelo.model_id == model_id,
                                                        MonitoreoModelo.rol == "activo")
                          .order_by(MonitoreoModelo.creado_en.desc(), MonitoreoModelo.id.desc()).limit(n)).all())


RELOJ_ANTIGUEDAD = ("días de datos en el calendario de America/Bogota: datos_hasta (última marca de agua) menos el "
                    "último día de datos que vio un modelo (fin de su serie o corte + 61 días); 0 si ese día es "
                    "posterior a datos_hasta")


def decidir_reentreno(s, umbrales: dict | None, hasta: date | None = None) -> dict[str, Any]:
    """¿Hay que entrenar un candidato? Devuelve motivos, el corte de entrenamiento y la fecha final de los datos."""
    from app.servicios import ejecucion

    u = umbrales_politica(umbrales)
    activo = ejecucion.modelo_activo(s)
    if hasta is None:
        hasta = _fecha(ejecucion.ultima_marca_agua(s))
    out: dict[str, Any] = {"reentrenar": False, "motivos": [], "bloqueos": [], "datos_hasta": hasta,
                           "modelo_activo": activo.model_id if activo else None,
                           "umbrales": {k: u[k] for k in ("reentreno_periodicidad_dias", "reentreno_dias_degradacion",
                                                          "wape_max", "cobertura_min")}}
    if activo is None or hasta is None:
        out["bloqueos"].append("sin modelo activo o sin datos procesados")
        return out
    out.update(antiguedad_de_datos(s, activo, hasta))
    out["motivos"] += _motivo_periodicidad(out, u) + _motivos_monitoreo(s, activo.model_id, u)
    out["bloqueos"] += _bloqueos_reentreno(s)
    corte = hasta - timedelta(days=DIAS_VALIDACION)
    out["hasta"] = corte.isoformat()
    out["datos_hasta"] = hasta.isoformat()
    if out["motivos"] and not out["bloqueos"]:       # solo si lo iba a pedir: la partición recorre toda la serie
        out["bloqueos"] += _bloqueo_sin_datos(s, corte, hasta)
    out["reentrenar"] = bool(out["motivos"]) and not out["bloqueos"]
    return out


OMITIDO_SIN_DATOS = "reentrenamiento omitido: datos insuficientes antes del corte"


def _bloqueo_sin_datos(s, corte: date, datos_hasta: date) -> list[str]:
    """No se pide un reentrenamiento cuyo corte no se puede entrenar. Lo decide la partición del entrenamiento
    (inferencia.corte_sin_datos, la misma función que usa entrenar) sobre la serie validada hasta datos_hasta, la que
    usaría entrenar_candidato: si no deja filas útiles para entrenar hasta el corte o para validar después, el trabajo
    fallaría siempre. Pasaba al comienzo de la serie: cada ciclo veía deriva frente al modelo vigente y encolaba un
    entrenamiento con el corte 61 días antes, anterior a los datos. El motivo queda en los bloqueos de la decisión
    (metricas.monitoreo.politica.reentreno de la ejecución, GET /monitoring/policy y la revisión del planificador)."""
    from app.servicios import inferencia

    serie, _info = serie_validada(s, datos_hasta)
    falta = inferencia.corte_sin_datos(serie, corte)
    if falta is None:
        return []
    bloqueo = (f"{OMITIDO_SIN_DATOS} {corte} (la serie validada hasta {datos_hasta} deja "
               f"{falta['filas_entrenamiento']} filas útiles para entrenar y {falta['filas_validacion']} para validar)")
    LOG.info("política de aprendizaje: %s", bloqueo)
    return [bloqueo]


def antiguedad_de_datos(s, activo, hasta: date) -> dict[str, Any]:
    """Días de datos nuevos desde el último día que vio un modelo (el activo o un candidato), medidos en el mismo
    reloj que datos_hasta (fechas de datos de America/Bogota). Nunca es negativo: si un modelo ya vio datos posteriores
    a datos_hasta (p. ej. su validación llega más lejos que la última ejecución), no hay días nuevos."""
    from sqlalchemy import select

    from app.modelos_db import RegistroModelo

    otros = s.scalars(select(RegistroModelo).where(RegistroModelo.tipo == "candidato")).all()
    vistos = [d for d in (datos_vistos_hasta(m) for m in [activo, *otros]) if d is not None]
    if not vistos:
        return {"ultimo_dato_visto": None}
    ultimo = max(vistos)
    out: dict[str, Any] = {"ultimo_dato_visto": ultimo,
                           "dias_desde_ultimo_entrenamiento": max((hasta - ultimo).days, 0),
                           "reloj_antiguedad": RELOJ_ANTIGUEDAD}
    if ultimo > hasta:
        out["nota_antiguedad"] = (f"un modelo ya vio datos hasta {ultimo}, posteriores a datos_hasta ({hasta}): "
                                  "no hay días de datos nuevos")
    return out


def _motivo_periodicidad(antiguedad: dict, u: dict) -> list[str]:
    dias = antiguedad.get("dias_desde_ultimo_entrenamiento")
    if dias is None or dias < u["reentreno_periodicidad_dias"]:
        return []
    return [f"periodicidad: {dias} días de datos nuevos desde {antiguedad['ultimo_dato_visto']} "
            f"(cada {int(u['reentreno_periodicidad_dias'])})"]


def _degradado(filas: list, n: int, wape_max: float) -> bool:
    """Las últimas n filas de monitoreo del activo tienen WAPE móvil sobre wape_max."""
    return len(filas) >= n and n > 0 and all(f.wape_movil is not None and f.wape_movil > wape_max for f in filas)


def _motivos_monitoreo(s, model_id: str, u: dict) -> list[str]:
    """Degradación, deriva (PSI de una variable disparadora en alerta) y cobertura P10-P90 baja, con el monitoreo."""
    n = int(u["reentreno_dias_degradacion"])
    filas = _ultimas_filas_monitoreo(s, model_id, max(n, 1))
    motivos = []
    if _degradado(filas, n, u["wape_max"]):
        motivos.append(f"degradación: WAPE móvil > {u['wape_max']:.0%} en las últimas {n} ejecuciones "
                       f"({', '.join(f'{f.wape_movil:.1%}' for f in filas)})")
    if not filas:
        return motivos
    ult = filas[0]
    deriva = [k for k, d in (ult.psi or {}).items() if d.get("dispara_reentreno") and d.get("nivel") == "alerta"]
    if deriva:
        motivos.append("deriva: " + ", ".join(f"{k} PSI {ult.psi[k]['psi']:.3f}" for k in deriva))
    if ult.cobertura_p10_p90 is not None and ult.cobertura_p10_p90 < u["cobertura_min"]:
        motivos.append(f"cobertura P10-P90 {ult.cobertura_p10_p90:.1%} < {u['cobertura_min']:.0%}")
    return motivos


def _bloqueos_reentreno(s) -> list[str]:
    """No se reentrena con un entrenamiento en cola o corriendo, ni con un retador en sombra."""
    from sqlalchemy import func, select

    from app.modelos_db import Ejecucion

    bloqueos = []
    pendientes = s.scalar(select(func.count()).select_from(Ejecucion).where(
        Ejecucion.tipo == "entrenamiento", Ejecucion.estado.in_(("en_cola", "corriendo")))) or 0
    if pendientes:
        bloqueos.append(f"{pendientes} entrenamiento(s) en cola o corriendo")
    sombra = [c.model_id for c in en_sombra(s)]
    if sombra:
        bloqueos.append(f"retador en sombra: {', '.join(sombra)}")
    return bloqueos


def encolar_entrenamiento(s, decision: dict, origen: str, correlation_id: str | None = None) -> uuid.UUID | None:
    """Encola el entrenamiento en la transacción de `s` (queda confirmado junto con los resultados del ciclo)."""
    from app.modelos_db import Ejecucion
    from app.servicios.ejecucion import json_seguro

    if not decision.get("reentrenar"):
        return None
    e = Ejecucion(execution_id=uuid.uuid4(), tipo="entrenamiento", estado="en_cola", progreso=0, intentos=0,
                  parametros=json_seguro({"hasta": decision["hasta"], "datos_hasta": decision["datos_hasta"],
                                          "semilla": 42, "solicitado_por": USUARIO_POLITICA, "origen": origen,
                                          "motivo": "; ".join(decision["motivos"])}),
                  metricas={}, correlation_id=correlation_id or f"politica-{origen}",
                  mensaje="Reentrenamiento por política: " + "; ".join(decision["motivos"]))
    s.add(e)
    s.flush()
    return e.execution_id


# ----------------------------------------------------------------------------------------------- serie validada
COLUMNAS_OBSERVADAS = ["ruta", "fecha", "hora", "pasajeros", "salidas"]


def huella_observados(s) -> tuple:
    """Huella barata del histórico validado (filas, último día, última carga y suma de pasajeros): cambia cuando un
    ciclo incorpora o corrige horas, también dentro de la transacción de `s` antes del commit. La inferencia la usa
    como llave de su caché de variables."""
    from sqlalchemy import func, select

    from app.modelos_db import DemandaObservada as D

    n, ultimo, cargado, suma = s.execute(select(func.count(), func.max(D.fecha), func.max(D.cargado_en),
                                                func.sum(D.pasajeros))).one()
    return int(n or 0), str(ultimo), str(cargado), round(float(suma or 0.0), 6)


def observados_validados(s, datos_hasta: date | None = None) -> pd.DataFrame:
    """Horas de ai_frecuencias.demanda_observada (solo entran las filas que pasaron la calidad del lote)."""
    from sqlalchemy import select

    from app.modelos_db import DemandaObservada

    consulta = select(DemandaObservada.ruta, DemandaObservada.fecha, DemandaObservada.hora,
                      DemandaObservada.pasajeros, DemandaObservada.salidas)
    if datos_hasta is not None:
        consulta = consulta.where(DemandaObservada.fecha <= datos_hasta)
    obs = pd.DataFrame(s.execute(consulta).all(), columns=COLUMNAS_OBSERVADAS)
    if len(obs):
        obs["fecha"] = pd.to_datetime(obs["fecha"]).dt.date
        obs["hora"] = obs["hora"].astype(int)
    return obs


def serie_validada(s, datos_hasta: date | None = None) -> tuple[pd.DataFrame, dict]:
    """Serie de entrenamiento: la empaquetada con los valores VALIDADOS de demanda_observada encima (misma clave
    ruta-fecha-hora) más las horas que solo están en demanda_observada; truncada en datos_hasta si se indica.
    La misma unión alimenta las variables de la inferencia, la evaluación, el monitoreo y la compuerta
    (inferencia.tabla_variables con la sesión)."""
    from app.servicios import datos

    base = datos.demanda_horaria(hasta=datos_hasta)
    serie, info = superponer_observados(base, observados_validados(s, datos_hasta))
    tocadas = info.pop("fechas_tocadas")
    info.update(dias_con_valor_nuevo=len(tocadas), primer_dia_nuevo=str(tocadas[0]) if tocadas else None,
                ultimo_dia_nuevo=str(tocadas[-1]) if tocadas else None,
                datos_hasta=None if datos_hasta is None else datos_hasta.isoformat())
    return serie, info


def superponer_observados(base: pd.DataFrame, obs: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """La serie empaquetada con las horas validadas encima (función pura, sin base de datos). `info` dice cuántas
    filas se reemplazaron o agregaron y `fechas_tocadas`: los días cuyo valor cambió o que son nuevos (a partir de
    ellos hay que recalcular los rezagos)."""
    info: dict[str, Any] = {"filas_demanda_observada": int(len(obs)), "filas_empaquetadas": int(len(base)),
                            "fechas_tocadas": []}
    if obs.empty:
        info["origen"] = "serie empaquetada (demanda_observada vacía)"
        return base, info
    obs = obs.copy()
    obs["fecha"] = pd.to_datetime(obs["fecha"]).dt.date
    obs["hora"] = obs["hora"].astype(int)
    m = base.merge(obs, on=["ruta", "fecha", "hora"], how="outer", suffixes=("", "_obs"), indicator=True)
    con_obs = m["pasajeros_obs"].notna()
    info["filas_reemplazadas"] = int((con_obs & (m["_merge"] == "both")).sum())
    info["filas_solo_observadas"] = int((m["_merge"] == "right_only").sum())
    distinto = con_obs & ((m["_merge"] == "right_only") | m["pasajeros"].isna()
                          | ((m["pasajeros"].astype(float) - m["pasajeros_obs"].astype(float)).abs() > 1e-9))
    info["filas_con_valor_distinto"] = int(distinto.sum())
    info["fechas_tocadas"] = sorted(set(m.loc[distinto, "fecha"]))
    m.loc[con_obs, "pasajeros"] = m.loc[con_obs, "pasajeros_obs"].astype(float)
    if "salidas" in m.columns:
        m["salidas"] = m["salidas"].where(m["salidas_obs"].isna(), m["salidas_obs"])
    cal = [c for c in ("tipo_dia", "festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero")
           if c in base.columns]
    if cal and info["filas_solo_observadas"]:
        por_fecha = base.drop_duplicates("fecha").set_index("fecha")[cal]
        solo = m["_merge"] == "right_only"
        for c in cal:
            m.loc[solo, c] = m.loc[solo, "fecha"].map(por_fecha[c])
    if "excluido" in m.columns:
        m["excluido"] = m["excluido"].fillna(0)
    serie = m.drop(columns=[c for c in m.columns if c.endswith("_obs")] + ["_merge"])
    info["origen"] = "demanda_observada (validada) sobre la serie empaquetada"
    info["filas_serie"] = int(len(serie))
    return serie.sort_values(["ruta", "fecha", "hora"]).reset_index(drop=True), info


def grupos_calibracion_del_activo(s) -> tuple[str, ...]:
    """Esquema de grupos de la calibración versionada del activo. El candidato se calibra con el mismo esquema (y con
    su propia validación), así la sombra y la compuerta comparan bandas del mismo tipo; sin calibración versionada en
    el activo se usa el esquema por defecto (bloque horario)."""
    from app.servicios import ejecucion, inferencia

    activo = ejecucion.modelo_activo(s)
    cal = None
    if activo is not None:
        try:
            cal = inferencia.cargar(activo.model_id).get("calibracion")
        except (inferencia.ModeloNoEncontrado, inferencia.ErrorIntegridadModelo, OSError, ValueError) as exc:
            LOG.warning("sin la calibración del activo %s: %s", activo.model_id, exc)
    return tuple(cal["grupos"]) if cal else tuple(inferencia.CALIBRACION_GRUPOS_DEFECTO)


def entrenar_candidato(parametros: dict) -> dict:
    """Entrena para _ciclo_entrenamiento: histórico validado, corte pedido y sin pisar el modelo activo. El candidato
    sale con su propia calibración por grupo (v2), ajustada con su validación y versionada con su SHA-256."""
    from sqlalchemy import select

    from app.db import sesion_contexto
    from app.modelos_db import RegistroModelo
    from app.servicios import inferencia

    datos_hasta = _fecha(parametros.get("datos_hasta"))
    with sesion_contexto() as s:
        serie, info_serie = serie_validada(s, datos_hasta)
        protegidos = set(s.scalars(select(RegistroModelo.model_id).where(RegistroModelo.estado == "activo")).all())
        grupos = grupos_calibracion_del_activo(s)
    info = inferencia.entrenar(date.fromisoformat(str(parametros["hasta"])[:10]),
                               semilla=int(parametros.get("semilla", 42)), serie=serie, ids_protegidos=protegidos,
                               calibrar=True, calibracion_grupos=grupos)
    info["serie"] = info_serie
    info["datos_hasta"] = (datos_hasta or max(serie["fecha"])).isoformat()
    info["sombra_aplica"] = datos_hasta is not None   # manual sin datos_hasta: gobierna POST /models/{id}/activate
    return info


def iniciar_sombra(registro, info: dict, umbrales: dict | None) -> None:
    """El candidato recién registrado queda en sombra desde el día siguiente al último dato que vio. creado_en va en
    America/Bogota (-05:00, §8.1) y la sombra registra la calibración con la que el candidato produce su banda."""
    from app.servicios.ejecucion import ZONA, ahora, json_seguro

    if registro.estado != "candidato":
        return

    if not info.get("sombra_aplica", True):
        registro.metricas = json_seguro({**(registro.metricas or {}), "serie": info.get("serie"), "sombra": {
            "estado": "no_aplica", "datos_hasta": info.get("datos_hasta"),
            "motivo": "entrenamiento manual sin datos_hasta: la activación pasa por POST /models/{id}/activate"}})
        return
    u = umbrales_politica(umbrales)
    fin = _fecha(info.get("datos_hasta"))
    inicio = fin + timedelta(days=1) if fin else None
    registro.metricas = {**(registro.metricas or {}), "serie": info.get("serie"), "sombra": {
        "estado": "en_sombra", "datos_hasta": fin, "inicio": inicio, "dias": int(u["sombra_dias"]),
        "fin": inicio + timedelta(days=int(u["sombra_dias"]) - 1) if inicio else None,
        "calibracion": info.get("calibracion"),
        "creado_en": ahora().astimezone(ZONA).isoformat(timespec="seconds")}}
    registro.metricas = json_seguro(registro.metricas)
    _auditar(registro, "sombra_iniciada", desde=inicio, dias=int(u["sombra_dias"]))


# ----------------------------------------------------------------------------------------------- sombra y compuerta
def compuerta(cand_id: str, activo_id: str | None, desde: date, hasta: date, umbrales: dict | None,
              sesion=None) -> dict:
    """Compara candidato y activo en la MISMA ventana temporal y aplica los criterios documentados. Con `sesion`
    (o dentro de inferencia.con_sesion) los valores reales son los validados de la base (serie_validada)."""
    from app.servicios import inferencia

    if sesion is not None:
        with inferencia.con_sesion(sesion):
            return compuerta(cand_id, activo_id, desde, hasta, umbrales)
    u = umbrales_politica(umbrales)
    m_c = inferencia.evaluar(cand_id, desde, hasta)
    m_a = inferencia.evaluar(activo_id, desde, hasta) if activo_id else None
    w_c, w_a = _wape(m_c), _wape(m_a)
    cob = m_c.get("cobertura_p10_p90_conformal", m_c.get("cobertura_p10_p90"))
    cob = None if cob is None else float(cob) / 100.0
    sesgo = None if m_c.get("sesgo_pct") is None else float(m_c["sesgo_pct"]) / 100.0
    criterios = [
        {"criterio": "WAPE del candidato ≤ WAPE del activo",
         "ok": w_a is None or (w_c is not None and w_c <= w_a + 1e-12),
         "candidato": w_c, "referencia": w_a},
        {"criterio": f"WAPE ≤ wape_max ({u['wape_max']:.0%})", "ok": w_c is not None and w_c <= u["wape_max"],
         "candidato": w_c, "referencia": u["wape_max"]},
        {"criterio": f"cobertura P10-P90 en [{u['cobertura_aviso']:.0%}, {u['cobertura_max']:.0%}]",
         "ok": cob is not None and u["cobertura_aviso"] <= cob <= u["cobertura_max"], "candidato": cob,
         "referencia": [u["cobertura_aviso"], u["cobertura_max"]]},
        {"criterio": f"|sesgo| ≤ sesgo_max ({u['sesgo_max']:.0%})",
         "ok": sesgo is not None and abs(sesgo) <= u["sesgo_max"],
         "candidato": sesgo, "referencia": u["sesgo_max"]},
    ]
    return {"ventana": {"desde": desde, "hasta": hasta}, "candidato": cand_id, "activo": activo_id,
            "aprobado": all(c["ok"] for c in criterios), "criterios": criterios,
            "calibracion": _calibraciones_comparadas(m_c, m_a),
            "metricas_candidato": {k: m_c.get(k) for k in CLAVES_METRICAS_COMPUERTA},
            "metricas_activo": None if m_a is None else {k: m_a.get(k) for k in CLAVES_METRICAS_COMPUERTA}}


CLAVES_METRICAS_COMPUERTA = ("wape", "mae", "rmse", "sesgo_pct", "cobertura_p10_p90", "cobertura_p10_p90_conformal",
                             "cobertura_p10_p90_conformal_v1", "calibracion_version", "n")


def _calibraciones_comparadas(m_c: dict, m_a: dict | None) -> dict:
    """Qué banda calibrada midió la compuerta en cada modelo: cada uno con SU calibración versionada (v2, ajustada con
    su propia validación) o, si no la trae, con el conformal móvil por ruta (v1)."""
    v_c = m_c.get("calibracion_version")
    v_a = None if m_a is None else m_a.get("calibracion_version")
    return {"candidato": v_c, "activo": v_a, "misma_version": m_a is None or v_c == v_a}


def activar_modelo(s, cand, activo, usuario: str, motivo: str, comparacion: dict, datos_hasta: date | None) -> None:
    """Misma mecánica que POST /models/{id}/activate (un solo activo, el anterior queda retirado y reversible)."""
    from app.servicios.ejecucion import ahora, json_seguro

    if activo is not None:
        activo.estado = "retirado"
        _auditar(activo, "retirado", reemplazado_por=cand.model_id, usuario=usuario)
        s.flush()
    cand.estado = "activo"
    cand.aprobado_por = usuario
    cand.activado_en = ahora()
    cand.anterior_model_id = activo.model_id if activo else cand.anterior_model_id
    cand.motivo = motivo
    cand.metricas = json_seguro({**(cand.metricas or {}), "validacion_activacion": comparacion,
                                 "activacion": {"datos_hasta": datos_hasta, "por": usuario}})
    _auditar(cand, "activado", usuario=usuario, motivo=motivo, comparacion=comparacion)
    s.flush()


def _decidir_sombra(s, cand, sm: dict, comp: dict, activo, u: dict, hasta: date, motivo_activacion: str) -> str:
    """Aplica al candidato la decisión de la compuerta de sombra: activado (activación automática), aprobado (espera a
    un admin) o rechazado (con los criterios que fallaron). Devuelve la decisión."""
    from app.servicios.ejecucion import json_seguro

    if comp["aprobado"] and u["activacion_automatica"] >= 1:
        sm["estado"] = "activado"
        cand.metricas = json_seguro({**(cand.metricas or {}), "sombra": sm, "decision_sombra": comp})
        activar_modelo(s, cand, activo, USUARIO_POLITICA, motivo_activacion, comp, hasta)
        return "activado"
    if comp["aprobado"]:
        sm["estado"] = "aprobado"
        cand.metricas = json_seguro({**(cand.metricas or {}), "sombra": sm, "decision_sombra": comp})
        _auditar(cand, "compuerta_aprobada", usuario=USUARIO_POLITICA, comparacion=comp,
                 nota="activacion_automatica = 0: espera la aprobación de un admin")
        return "aprobado"
    sm["estado"] = "rechazado"
    fallidos = [c["criterio"] for c in comp["criterios"] if not c["ok"]]
    cand.estado = "rechazado"
    cand.motivo = "compuerta de sombra no aprobada: " + "; ".join(fallidos)
    cand.metricas = json_seguro({**(cand.metricas or {}), "sombra": sm, "decision_sombra": comp})
    _auditar(cand, "activacion_rechazada", usuario=USUARIO_POLITICA, motivo=cand.motivo, comparacion=comp)
    return "rechazado"


def revisar_sombra(s, hasta: date, umbrales: dict | None, umbrales_version: int | None) -> list[dict]:
    from app.servicios import ejecucion

    u = umbrales_politica(umbrales)
    salida = []
    for cand in en_sombra(s):
        sm = dict((cand.metricas or {}).get("sombra") or {})
        inicio = _fecha(sm.get("inicio"))
        dias = int(sm.get("dias") or u["sombra_dias"])
        if inicio is None:
            continue
        fin = inicio + timedelta(days=dias - 1)
        observados = (hasta - inicio).days + 1
        if hasta < fin:
            salida.append({"model_id": cand.model_id, "estado": "en_sombra", "dias_observados": max(observados, 0),
                           "dias_requeridos": dias})
            continue
        activo = ejecucion.modelo_activo(s)
        comp = compuerta(cand.model_id, activo.model_id if activo else None, inicio, fin, u)
        comp["umbrales_version"] = umbrales_version
        decision = _decidir_sombra(s, cand, sm, comp, activo, u, hasta,
                                   f"compuerta de sombra aprobada ({inicio}..{fin}, umbrales v{umbrales_version})")
        salida.append({"model_id": cand.model_id, "estado": decision, "compuerta": comp})
    return salida


def revisar_reversion(s, monitoreo: dict, umbrales: dict | None) -> dict | None:
    """Vuelve al modelo anterior si el recién activado se degrada en los días posteriores a su activación."""
    from sqlalchemy import select

    from app.modelos_db import RegistroModelo
    from app.servicios import ejecucion, inferencia

    u = umbrales_politica(umbrales)
    activo = ejecucion.modelo_activo(s)
    if activo is None or not activo.anterior_model_id:
        return None
    act = (activo.metricas or {}).get("activacion") or {}
    desde_act = _fecha(act.get("datos_hasta"))
    hasta = _fecha(monitoreo.get("hasta"))
    if desde_act is None or hasta is None:
        return None
    dias = (hasta - desde_act).days
    if dias < u["reversion_minimo_dias"] or dias > u["reversion_ventana_dias"]:
        return {"revisada": False, "dias_desde_activacion": dias}
    desde = desde_act + timedelta(days=1)
    w_n = _wape(inferencia.evaluar(activo.model_id, desde, hasta))
    previo = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == activo.anterior_model_id))
    if previo is None:
        return None
    w_p = _wape(inferencia.evaluar(previo.model_id, desde, hasta))
    out = {"revisada": True, "ventana": {"desde": desde, "hasta": hasta}, "wape_nuevo": w_n, "wape_anterior": w_p,
           "wape_max": u["wape_max"], "revertido": False}
    if w_n is not None and w_n > u["wape_max"] and w_p is not None and w_p < w_n:
        motivo = (f"reversión automática: WAPE {w_n:.1%} > {u['wape_max']:.0%} y peor que el anterior "
                  f"{previo.model_id} ({w_p:.1%}) en {desde}..{hasta}")
        activo.estado = "retirado"
        _auditar(activo, "revertido", usuario=USUARIO_POLITICA, motivo=motivo, vuelve_a=previo.model_id)
        s.flush()
        previo.estado = "activo"
        previo.aprobado_por = USUARIO_POLITICA
        previo.activado_en = ejecucion.ahora()
        _auditar(previo, "reactivado_por_reversion", usuario=USUARIO_POLITICA, motivo=motivo, desde=activo.model_id)
        s.flush()
        out.update(revertido=True, motivo=motivo, activo=previo.model_id)
    return out


def predecir_en_sombra(s, execution_id, sombra: dict, ejecuciones: list | None = None) -> int:
    """El retador predice lo mismo que el activo en esta ejecución; se guarda en su fila de monitoreo (no decide).
    En una ejecución partida por ruta (RNF-005), `ejecuciones` son sus trabajos: el retador predice lo que ellos."""
    from sqlalchemy import select

    from app.modelos_db import MonitoreoModelo, Prediccion
    from app.servicios import inferencia
    from app.servicios.ejecucion import json_seguro

    fila = s.get(MonitoreoModelo, sombra["id"])
    if fila is None:
        return 0
    filas = []
    ids = list(ejecuciones) if ejecuciones else [execution_id]
    with inferencia.con_sesion(s):   # las mismas variables (serie validada) que vio el activo en este ciclo
        for p in s.scalars(select(Prediccion).where(Prediccion.execution_id.in_(ids))).all():
            r = inferencia.predecir(p.ruta, p.instante, p.horizonte_min, model_id=sombra["model_id"])
            filas.append({"ruta": p.ruta, "horizonte_min": p.horizonte_min, "instante": p.instante,
                          "pasajeros": r["pasajeros"], "p10": r["p10"], "p90": r["p90"],
                          "activo_model_id": p.model_id, "activo_pasajeros": p.pasajeros})
    fila.detalle = json_seguro({**(fila.detalle or {}), "predicciones_sombra": filas})
    fila.n_predicciones = len(filas)
    return len(filas)


def despues_del_ciclo(s, execution_id, monitoreo: dict, umbrales: dict | None, umbrales_version: int | None) -> dict:
    """Reversión, compuerta de sombra y decisión de reentreno al final de cada ciclo diario (misma transacción). La
    reversión y la compuerta miden el error sobre la serie validada de `s` (lo que llegó y pasó la calidad)."""
    from app.servicios import inferencia

    u = umbrales_politica(umbrales)
    hasta = _fecha(monitoreo.get("hasta"))
    with inferencia.con_sesion(s):
        out: dict[str, Any] = {"reversion": revisar_reversion(s, monitoreo, u),
                               "sombra": revisar_sombra(s, hasta, u, umbrales_version)}
    dec = decidir_reentreno(s, u, hasta)
    out["reentreno"] = dec
    if dec["reentrenar"] and u["reentreno_en_ciclo"] >= 1:
        out["entrenamiento_encolado"] = encolar_entrenamiento(s, dec, "ciclo_diario", f"politica-{execution_id}")
    return out


def resumen_json(obj: Any) -> str:
    from app.servicios.ejecucion import json_seguro

    return json.dumps(json_seguro(obj), ensure_ascii=False)
