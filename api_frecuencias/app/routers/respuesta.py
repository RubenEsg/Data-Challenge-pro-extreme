"""Respuesta a la pregunta final del reto (especificación v1.5, §20): GET /api/v1/respuesta y su cálculo asíncrono.

«¿cada cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos pasajeros y vehículos se esperan, y qué
situaciones requieren atención inmediata?». El cálculo está en app/servicios/respuesta.py y corre en la cola (§7.1):
POST /api/v1/respuesta/calcular encola una ejecución de tipo «respuesta» y responde 202 con su execution_id; el ciclo
diario también deja calculado el día siguiente. GET /api/v1/respuesta y su exportación solo leen la foto guardada en
ai_frecuencias.respuesta_reto; si no existe, 404 «sin_calcular» con la pista del POST.

«Próximas dos horas» (proximas_dos_horas): con el pronóstico de corto plazo (RF-005), las subidas de los próximos 30,
60 y 120 minutos de cada ruta, con su banda, la línea base, la recomendación de §10.2 y los segmentos más cargados, en
el instante de referencia: el pedido, o el último instante con datos leídos (el panel empaquetado y lo que trajo la
lectura incremental) a la hora actual del día.
"""
from __future__ import annotations

import io
import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.routers.comun import ErrorApi

router = APIRouter(tags=["respuesta del reto"])
Ruta = Literal["SILENCIO", "CRA 54", "CL 72"]


class Trazabilidad(BaseModel):
    model_id: str = Field(description="Modelo activo que pronostica los pasajeros y alimenta el plan")
    feature_version: str | None = Field(None, description="Versión de las variables del modelo")
    data_cutoff: str | None = Field(None, description="Fecha de corte de los datos de entrenamiento del modelo")
    calibracion_version: str | None = Field(None, description="Versión de la calibración de la banda P10-P90")
    calibracion_banda: str | None = Field(None, description="Igual a calibracion_version (nombre anterior)")
    fuente_pronostico: str | None = Field(None, description="Pronóstico del plan: «modelo_activo» o «E12»")
    umbrales_version: int | None = Field(None, description="Versión de threshold_config con la que se calculó")
    execution_id: str | None = Field(None, description="Ejecución de la cola que calculó la foto (la más reciente)")
    ejecuciones_por_ruta: dict[str, str | None] | None = Field(None, description="Ejecución que calculó cada ruta")
    ultima_ejecucion_ciclo: str | None = Field(None, description="Último ciclo de frecuencia terminado al calcular")
    datos_hasta: str | None = Field(None, description="Último día con datos (serie empaquetada y demanda_observada)")
    fuentes: list[str] = Field(description="De dónde sale cada cifra (servicio, archivo o tabla)")


class HoraDespacho(BaseModel):
    hora: int = Field(description="Hora de salida (4-20)")
    franja: str
    headway_min: float | None = Field(None, description="Intervalo recomendado (min); null si la hora no tiene salidas")
    buses_hora: int = Field(description="Salidas recomendadas en la hora (plan del día)")
    headway_actual_min: float | None = Field(None, description="Intervalo programado hoy (D1)")
    buses_hora_actual: float | None = Field(None, description="Salidas programadas hoy en los minutos operados")
    viable: bool
    motivo: str | None = None
    limites_activos: Any | None = Field(None, description="Restricciones que limitan la hora (si el plan las trae)")
    demanda_diseno: Any | None = Field(None, description="Demanda de diseño de la hora (si el plan la trae)")
    margen: Any | None = Field(None, description="Margen frente a ±1 salida (si el plan lo trae)")


class FranjaDespacho(BaseModel):
    franja: str
    salidas: int = Field(description="Salidas recomendadas en la franja")
    salidas_programadas: float = Field(description="Salidas programadas hoy en la franja")
    headway_min: float | None = Field(None, description="Minutos operados / salidas recomendadas de la franja")
    headway_actual_min: float | None = Field(None, description="Minutos operados / salidas programadas de la franja")
    horas_no_viables: list[int] = Field(default_factory=list)


class ResumenDespacho(BaseModel):
    salidas_dia_recomendadas: int
    salidas_dia_programadas: float | None = None
    headway_pico_min: float | None = Field(None, description="Intervalo recomendado en la hora con más salidas")
    headway_valle_min: float | None = Field(None, description="Mediana del intervalo recomendado de 9 a 16 h")
    hora_pico: int | None = Field(None, description="Hora con más salidas recomendadas")
    por_franja: list[FranjaDespacho] = Field(default_factory=list, description="Cada cuánto despachar por franja")


class PasajerosHora(BaseModel):
    hora: int
    esperado: float
    p10: float
    p90: float


class PasajerosEsperados(BaseModel):
    dia: float
    p10: float = Field(description="Suma de los P10 de cada hora")
    p90: float = Field(description="Suma de los P90 de cada hora")
    por_hora: list[PasajerosHora]


class Vehiculos(BaseModel):
    requeridos_pico: int = Field(description="Máximo de buses en ruta a la vez con el plan (conteo cada 15 min)")
    flota_disponible: int
    hora_pico: int | None = None
    requeridos_pico_10_3: int | None = Field(None, description="Máximo de ceil(ciclo / headway) de §10.3")
    requeridos_programados: int | None = Field(None, description="Máximo de buses en ruta con lo programado hoy")
    nota: str | None = None


class FlotaRecaudo(BaseModel):
    recaudo_esperado_cop: float | None = Field(None, description="Pasajeros esperados × tarifa neta (null sin tarifa)")
    costo_operativo_cop: float | None = Field(None, description="Costo operativo del plan del día (bus-hora + km)")
    vehiculos_hora_ahorrados: float | None = Field(None, description="Programado menos recomendado (negativo: más)")
    nota: str
    tarifa_neta_cop: float | None = None
    costo_operativo_actual_cop: float | None = None
    vehiculos_hora_recomendados: float | None = None
    vehiculos_hora_actuales: float | None = None
    espera_media_min: float | None = None
    espera_media_actual_min: float | None = None
    sobreocupacion_pasajeros: float | None = None
    sobreocupacion_pasajeros_actual: float | None = None
    ingreso_perdido_cop: float | None = Field(None, description="Componente «ingreso» del MILP (+ pierde, - gana)")


class AlertaInmediata(BaseModel):
    alert_id: str
    codigo: str
    severidad: str
    estado: str
    ruta: str | None = None
    origen: str | None = Field(None, description="observada o pronostico")
    alcance: str | None = Field(None, description="«abierta ahora» o «detectada en la fecha consultada»")
    detectada_en: str | None = Field(None, description="Instante de detección en America/Bogota (-05:00)")
    ventana_inicio: str | None = Field(None, description="Inicio de la ventana de la alerta (-05:00)")
    explicacion: str | None = None
    recomendacion: str | None = None


class ResumenAtencion(BaseModel):
    consultado_en: str = Field(description="Instante de la consulta (-05:00): «abiertas ahora» es en este instante")
    abiertas_ahora: int = Field(description="Alertas abiertas ahora de la ruta o generales (todas, sin el límite)")
    abiertas_ahora_por_severidad: dict[str, int] = Field(default_factory=dict)
    de_la_fecha: int = Field(description="Alertas detectadas en la fecha consultada, en cualquier estado")
    de_la_fecha_por_severidad: dict[str, int] = Field(default_factory=dict)
    nota: str


class RespuestaRuta(BaseModel):
    ruta: str
    idruta: int | None = None
    cada_cuanto_despachar: list[HoraDespacho]
    resumen_despacho: ResumenDespacho
    pasajeros_esperados: PasajerosEsperados
    vehiculos: Vehiculos
    flota_y_recaudo: FlotaRecaudo
    atencion_inmediata: list[AlertaInmediata] = Field(
        description="Abiertas ahora (en el momento de la consulta), críticas primero; máximo 10")
    alertas_de_la_fecha: list[AlertaInmediata] = Field(
        default_factory=list, description="Detectadas en la fecha consultada, críticas primero; máximo 10")
    atencion_resumen: ResumenAtencion | None = None


class RespuestaReto(BaseModel):
    pregunta: str = Field(description="La pregunta final de la especificación v1.5 (§20), literal")
    fecha: str
    tipo_dia: str | None = None
    generado_en: str = Field(description="Instante en que se calculó la foto, en America/Bogota (-05:00)")
    consultado_en: str | None = Field(None, description="Instante de esta consulta (-05:00)")
    trazabilidad: Trazabilidad
    rutas: list[RespuestaRuta]
    limitaciones: list[str]
    proximas_dos_horas: ProximasDosHoras | None = Field(None, description=(
        "Atención inmediata: el pronóstico de corto plazo (30, 60 y 120 min) de cada ruta en el instante de "
        "referencia"))


class ProximasDosHoras(BaseModel):
    """«Qué situaciones requieren atención inmediata»: el pronóstico de corto plazo de cada ruta en el instante de
    referencia."""
    instante: str | None = Field(None, description="Instante de referencia (-05:00)")
    origen_instante: str | None = Field(None, description="pedido, o el último día con datos leídos a la hora actual")
    model_id: str | None = None
    rutas: list[dict] = Field(default_factory=list, description=(
        "Por ruta: el pronóstico de cada horizonte (30, 60 y 120 min) con banda P10-P90, promedio por día y hora, "
        "recomendación de §10.2 (buses/h, headway, vehículos, viabilidad), por sentido, y los 5 segmentos con más "
        "subidas previstas en la próxima hora"))
    nota: str | None = None


class SolicitudCalculo(BaseModel):
    fecha: date | None = Field(None, description="Día a calcular (ISO); sin ella, el día siguiente al último dato")
    rutas: list[Ruta] | None = Field(None, description="Rutas a calcular; sin ellas, las tres")


class CalculoEnCola(BaseModel):
    execution_id: uuid.UUID
    tipo: str
    estado: str
    nueva: bool = Field(description="false si ya había un cálculo igual en cola o corriendo (no se duplica)")
    fecha: str
    rutas: list[str]
    creado_en: str | None = Field(None, description="Instante en que se encoló (-05:00)")
    consultar_estado: str = Field(description="Ruta para seguir la ejecución")
    consultar_respuesta: str = Field(description="Ruta para leer la respuesta cuando termine")


DESCRIPCION = (
    "Contesta la pregunta final de la especificación (§20) con los datos históricos y recientes: por ruta, cada cuánto "
    "despachar por hora y franja (plan del día frente a lo programado, con su viabilidad), cuántos pasajeros se "
    "esperan (modelo activo con P10-P90), cuántos vehículos hacen falta frente a la flota, el balance de flota y "
    "recaudo, y qué requiere atención inmediata: las alertas abiertas ahora (críticas primero) y, aparte, las de la "
    "fecha consultada. Lee la foto calculada en la cola (§7.1); sin `fecha`, el día siguiente al último dato. Sin "
    "`ruta`, las tres. Todos los instantes en America/Bogota. 404 «sin_calcular» si la foto no existe para el modelo "
    "activo y los umbrales vigentes: pídala con POST /api/v1/respuesta/calcular.")


def _leer(sesion: Session, ruta: str | None, fecha: date | None) -> dict:
    from app.servicios import respuesta as servicio

    try:
        return servicio.leer(sesion, ruta=ruta, fecha=fecha)
    except servicio.SinCalcular as exc:
        raise ErrorApi(404, "sin_calcular", str(exc).strip("'\""), exc.detalle) from exc


@router.get("/respuesta", response_model=RespuestaReto, summary="Respuesta a la pregunta final del reto (§20)",
            description=DESCRIPCION)
def respuesta_reto(ruta: Ruta | None = Query(None, description="SILENCIO, CRA 54 o CL 72; sin ella, las tres"),
                   fecha: date | None = Query(None, description="Día (ISO); sin ella, el siguiente al último dato"),
                   instante: datetime | None = Query(None, description=(
                       "Instante de referencia de «próximas dos horas» (sin él, el último día con datos leídos a la "
                       "hora actual)")),
                   corto_plazo: bool = Query(True, description="Incluir «próximas dos horas»"),
                   sesion: Session = Depends(obtener_sesion)):
    salida = _leer(sesion, ruta, fecha)
    if corto_plazo:
        salida["proximas_dos_horas"] = proximas_dos_horas(sesion, [ruta] if ruta else list(RUTAS_RESPUESTA),
                                                          instante)
    return salida


RUTAS_RESPUESTA = ("SILENCIO", "CRA 54", "CL 72")


def _instante_de_referencia(instante: datetime | None) -> tuple[datetime, str]:
    """El pedido o el último día con datos leídos, a la hora actual del día (entre 04:00 y 21:00)."""
    from app.servicios import corto_plazo as cp
    from app.servicios import ejecucion

    if instante is not None:
        return instante, "pedido"
    sc = cp.serie_completa(2)
    hay = [k for k in range(len(sc.ruta.cal) - 1, -1, -1) if bool(sc.ruta.ok[k])]
    ultimo = cp.fecha_de_dia(hay[0]) if hay else cp.fecha_de_dia(sc.fin_panel)
    ahora = ejecucion.ahora().astimezone(cp.ZONA)
    hora = min(max(ahora.hour, 4), 20)
    ref = datetime(ultimo.year, ultimo.month, ultimo.day, hora, 30 if ahora.minute >= 30 else 0, tzinfo=cp.ZONA)
    limite = cp.limite_lectura(sc, ultimo)
    if limite is not None and ref > limite:
        ref = limite.replace(minute=30 if limite.minute >= 30 else 0, second=0, microsecond=0)
    return ref, "último día con datos leídos, a la hora actual del día"


def proximas_dos_horas(sesion: Session, rutas: list[str], instante: datetime | None) -> dict:
    """§20 «situaciones que requieren atención inmediata» con el pronóstico de corto plazo de cada ruta."""
    from app.routers.pronostico_corto_plazo import modelo_de_la_familia
    from app.servicios import corto_plazo as cp
    from app.servicios import datos

    try:
        mid = modelo_de_la_familia(sesion, None)
        with cp.con_sesion(sesion):
            ref, origen = _instante_de_referencia(instante)
            salida = {"instante": ref.astimezone(cp.ZONA).isoformat(timespec="minutes"), "origen_instante": origen,
                      "model_id": None, "rutas": []}
            for ruta in rutas:
                info = datos.ruta_info(ruta)
                horizontes = []
                segmentos = []
                for h in (30, 60, 120):
                    r = cp.pronosticar(ruta, ref, h, model_id=mid, incluir_segmentos=(h == 60))
                    rec = cp.recomendacion(sesion, r, info)
                    salida["model_id"] = r["model_id"]
                    horizontes.append({
                        "horizonte_min": h, "ventana": r["ventana"], "pasajeros": r["pasajeros"], "p10": r["p10"],
                        "p90": r["p90"], "promedio_dia_hora": r["promedio_dia_hora"], "real": r["real"],
                        "sentidos": r["sentidos"], "buses_hora": rec.get("buses_hora"),
                        "headway_min": rec.get("headway_min"), "vehiculos_requeridos": rec.get("vehiculos_requeridos"),
                        "viable": rec.get("viable"), "motivo": rec.get("motivo"),
                        "frecuencia_actual_min": rec.get("frecuencia_actual_min"),
                        "explicacion": [f["descripcion"] for f in r["explicacion"]["factores"][:3]]})
                    if h == 60:
                        segmentos = sorted(r.get("segmentos") or [], key=lambda s: -(s["pasajeros"] or 0))[:5]
                salida["rutas"].append({"ruta": ruta, "datos_hasta": r.get("datos_hasta"), "horizontes": horizontes,
                                        "segmentos_mas_cargados_60_min": segmentos, "calidad": r.get("calidad")})
        return salida
    except Exception as exc:  # noqa: BLE001 - la respuesta del reto se entrega aunque el corto plazo no esté
        return {"instante": None, "rutas": [], "nota": f"pronóstico de corto plazo no disponible: {exc}"}


@router.post("/respuesta/calcular", response_model=CalculoEnCola, status_code=202,
             summary="Calcular la respuesta del reto para una fecha (job en la cola, rol analista)",
             description="Encola una ejecución de tipo «respuesta» que pronostica cada hora con el modelo activo, "
                         "resuelve el plan del día con los umbrales vigentes y guarda la foto que lee "
                         "GET /api/v1/respuesta. Responde 202 con el execution_id; si ya hay un cálculo igual en "
                         "cola o corriendo, devuelve ese. 404 «sin_datos» si la fecha está fuera de los días que "
                         "se pueden calcular (antes del primer dato o después de los días con variables).")
def calcular_respuesta(tareas: BackgroundTasks, request: Request, solicitud: SolicitudCalculo | None = None,
                       sesion: Session = Depends(obtener_sesion)):
    from app.servicios import ejecucion
    from app.servicios import respuesta as servicio

    solicitud = solicitud or SolicitudCalculo()
    try:
        e, nueva = servicio.solicitar_calculo(sesion, solicitud.fecha, solicitud.rutas,
                                              getattr(request.state, "correlation_id", None))
    except servicio.SinDatos as exc:
        primera, ultima = servicio.rango_calculable(sesion)
        raise ErrorApi(404, "sin_datos", str(exc).strip("'\""),
                       {"fecha": solicitud.fecha.isoformat() if solicitud.fecha else None,
                        "primera_fecha": primera.isoformat(), "ultima_fecha": ultima.isoformat()}) from exc
    if nueva:
        tareas.add_task(ejecucion.ejecutar, e.execution_id)
    p = e.parametros or {}
    return {"execution_id": e.execution_id, "tipo": e.tipo, "estado": e.estado, "nueva": nueva, "fecha": p["fecha"],
            "rutas": p.get("rutas") or list(servicio.RUTAS), "creado_en": servicio.instante_bogota(e.creado_en),
            "consultar_estado": f"/api/v1/frequency/executions/{e.execution_id}",
            "consultar_respuesta": f"/api/v1/respuesta?fecha={p['fecha']}"}


@router.get("/respuesta/export", summary="Exportar la respuesta del reto por ruta y hora (CSV o XLSX)",
            response_class=Response,
            description="La misma foto de GET /api/v1/respuesta en una tabla plana: una fila por ruta y hora. 404 "
                        "«sin_calcular» si la foto no existe.")
def exportar_respuesta(formato: Literal["csv", "xlsx"] = Query("csv"),
                       ruta: Ruta | None = Query(None, description="SILENCIO, CRA 54 o CL 72; sin ella, las tres"),
                       fecha: date | None = Query(None, description="Día (ISO); sin ella, el siguiente al último dato"),
                       sesion: Session = Depends(obtener_sesion)):
    import pandas as pd

    from app.servicios import respuesta as servicio
    from app.servicios.ejecucion import ZONA

    datos = _leer(sesion, ruta, fecha)
    df = pd.DataFrame(servicio.tabla_plana(datos))
    marca = datetime.now(ZONA).strftime("%Y%m%d_%H%M%S")
    nombre = f"respuesta_{datos['fecha']}_{marca}"
    if formato == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
            df.to_excel(escritor, index=False, sheet_name="respuesta")
        return Response(buffer.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nombre}.xlsx"'})
    return Response(df.to_csv(index=False).encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'})
