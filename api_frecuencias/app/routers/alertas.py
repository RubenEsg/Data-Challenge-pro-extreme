"""Alertas (RF-009..RF-011): consulta por filtros (también espacial), gestión de estado e historial."""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import Select, and_, case, false, func, or_, select, text
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import AlertaSalida, HistorialSalida, Pagina, SolicitudEstadoAlerta
from app.modelos_db import Alerta, HistorialAlerta, punto_geojson
from app.routers.comun import DESPLAZAMIENTO_MAX, ErrorApi, ParametrosPagina, exportar, no_encontrado, paginar
from app.seguridad import Principal, autenticar, usuario_auditoria
from app.servicios.ejecucion import ZONA, ahora, json_seguro

router = APIRouter(prefix="/alerts", tags=["alertas"])

# §3.1 «priorizar»: orden=prioridad = rango de severidad (crítica, preventiva, informativa) y, dentro de cada una, la
# detección más reciente primero. Es el orden por omisión de GET /alerts (la bandeja del operador).
ORDEN_PRIORIDAD = "prioridad"
RANGO_SEVERIDAD = {"critica": 0, "preventiva": 1, "informativa": 2}
IdRuta = Annotated[int | None, Query(ge=1, le=2_147_483_647,
                                     description="Filtro por rutas.idruta de Extreme (§8.3), p. ej. 2")]

CercaDe = Annotated[str | None, Query(pattern=r"^\s*-?\d{1,2}(\.\d+)?\s*,\s*-?\d{1,3}(\.\d+)?\s*$",
                                      description="Filtro espacial: «lat,lon» (WGS84) del centro, p. ej. "
                                                  "10.981,-74.801; se combina con radio_m")]
RadioM = Annotated[float, Query(gt=0, le=50_000, description="Radio del filtro espacial en metros (por omisión 1000)")]
RADIO_TIERRA_M = 6_371_008.8
MAX_CANDIDATAS_SIN_POSTGIS = 50_000
RECURSO = "La alerta"   # sujeto del mensaje 404 uniforme


def _centro(cerca_de: str) -> tuple[float, float]:
    lat, lon = (float(x) for x in cerca_de.split(","))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ErrorApi(422, "validacion", "cerca_de fuera de rango: lat en [-90, 90] y lon en [-180, 180]",
                       [{"campo": "query.cerca_de", "mensaje": "Coordenadas fuera de rango", "tipo": "rango"}])
    return lat, lon


def _distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia del gran círculo (haversine) en metros: respaldo cuando la base no tiene PostGIS."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(a)))


def _con_postgis(sesion: Session) -> bool:
    tipo = sesion.execute(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = "
                               "'ai_frecuencias.alert'::regclass AND attname = 'ubicacion'")).scalar()
    return bool(tipo and tipo.startswith("geography"))


def _ids_cercanos_sin_postgis(sesion: Session, lat: float, lon: float, radio_m: float) -> list:
    """Sin PostGIS la ubicación es EWKT en texto: distancia haversine en Python sobre las alertas con ubicación."""
    candidatas = sesion.execute(select(Alerta.alert_id, Alerta.ubicacion)
                                .where(Alerta.ubicacion.is_not(None))
                                .limit(MAX_CANDIDATAS_SIN_POSTGIS)).all()
    dentro = []
    for alert_id, punto in candidatas:
        geo = punto_geojson(punto)
        if geo and _distancia_m(lat, lon, geo["coordinates"][1], geo["coordinates"][0]) <= radio_m:
            dentro.append(alert_id)
    return dentro


def _filtro_espacial(sesion: Session, consulta: Select, cerca_de: str, radio_m: float) -> Select:
    lat, lon = _centro(cerca_de)
    if _con_postgis(sesion):   # §8.1: geography(Point,4326) con índice GiST ix_alert_ubicacion
        centro = func.ST_GeogFromText(f"SRID=4326;POINT({lon!r} {lat!r})")
        return consulta.where(func.ST_DWithin(Alerta.ubicacion, centro, float(radio_m)))
    return consulta.where(Alerta.alert_id.in_(_ids_cercanos_sin_postgis(sesion, lat, lon, radio_m)))


def _filtro_fechas(consulta: Select, desde: date | None, hasta: date | None) -> Select:
    """Días completos en America/Bogota: desde las 0:00 de `desde` hasta antes de las 0:00 del día siguiente a
    `hasta`."""
    if desde:
        consulta = consulta.where(Alerta.detectada_en >= datetime.combine(desde, time(0), tzinfo=ZONA))
    if hasta:
        consulta = consulta.where(Alerta.detectada_en < datetime.combine(hasta + timedelta(days=1), time(0),
                                                                         tzinfo=ZONA))
    return consulta


def _filtro_idruta(consulta: Select, idruta: int | None) -> Select:
    """§8.3 idruta: la columna alert.idruta (migración 0006) o, en las filas sin ella, el nombre de la ruta que el
    catálogo asocia a ese idruta (app/servicios/dimensiones). Un idruta desconocido no devuelve alertas."""
    if idruta is None:
        return consulta
    try:
        from app.servicios import dimensiones

        nombres = [r for r, f in dimensiones.mapa_rutas().items() if f.get("idruta") == idruta]
    except Exception:  # noqa: BLE001 - sin catálogo solo queda la columna
        nombres = []
    columna = getattr(Alerta, "idruta", None)
    por_nombre = Alerta.ruta.in_(nombres) if nombres else false()
    if columna is None:
        return consulta.where(por_nombre)
    return consulta.where(or_(columna == idruta, and_(columna.is_(None), por_nombre)))


def _filtrar(sesion: Session, estado, severidad, codigo, ruta, desde, hasta, cerca_de, radio_m,
             idruta: int | None = None) -> Select:
    consulta = select(Alerta)
    for col, val in ((Alerta.estado, estado), (Alerta.severidad, severidad), (Alerta.codigo, codigo),
                     (Alerta.ruta, ruta)):
        if val:
            consulta = consulta.where(col == val)
    consulta = _filtro_idruta(consulta, idruta)
    consulta = _filtro_fechas(consulta, desde, hasta)
    if cerca_de:
        consulta = _filtro_espacial(sesion, consulta, cerca_de, radio_m)
    return consulta


def _por_prioridad(consulta: Select) -> Select:
    """Rango de severidad (crítica 0, preventiva 1, informativa 2) y la detección más reciente primero."""
    rango = case(RANGO_SEVERIDAD, value=Alerta.severidad, else_=len(RANGO_SEVERIDAD))
    return consulta.order_by(rango.asc(), Alerta.detectada_en.desc(), Alerta.alert_id.asc())


@router.get("", response_model=Pagina[AlertaSalida], summary="Listar alertas por estado, nivel, ruta, fecha y lugar",
            description="Por omisión las ordena por PRIORIDAD (§3.1): primero las críticas, luego las preventivas y "
                        "las informativas, y dentro de cada severidad la más reciente primero (orden=prioridad). "
                        "orden acepta también cualquier columna, con «-» para descendente (p. ej. -detectada_en). "
                        "idruta filtra por rutas.idruta (§8.3). Con cerca_de=lat,lon y radio_m devuelve las alertas "
                        "cuya ubicación (geography(Point,4326), índice GiST) está a radio_m metros o menos "
                        "(ST_DWithin). Si la base no tiene PostGIS, el mismo filtro se calcula con la distancia "
                        "haversine sobre la ubicación guardada en texto.")
def listar(estado: str | None = None, severidad: str | None = None, codigo: str | None = None,
           ruta: str | None = None, idruta: IdRuta = None, desde: date | None = None, hasta: date | None = None,
           cerca_de: CercaDe = None, radio_m: RadioM = 1000.0,
           pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar(sesion, estado, severidad, codigo, ruta, desde, hasta, cerca_de, radio_m, idruta)
    if (pagina.orden or ORDEN_PRIORIDAD) != ORDEN_PRIORIDAD:
        return paginar(sesion, consulta, Alerta, pagina, "-detectada_en")
    total = sesion.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    filas = sesion.scalars(_por_prioridad(consulta).limit(pagina.limite).offset(pagina.desplazamiento)).all()
    return {"total": total or 0, "limite": pagina.limite, "desplazamiento": pagina.desplazamiento, "items": filas}


# RF-016/RF-017: exportación con los mismos filtros de GET /alerts. Va ANTES de /{alert_id}: si no, «export» se lee como
# un UUID y FastAPI responde 422.
@router.get("/export", summary="Exportar alertas filtradas (CSV o XLSX)", response_class=Response)
def exportar_alertas(formato: Literal["csv", "xlsx"] = "csv", estado: str | None = None, severidad: str | None = None,
                     codigo: str | None = None, ruta: str | None = None, idruta: IdRuta = None,
                     desde: date | None = None,
                     hasta: date | None = None, cerca_de: CercaDe = None, radio_m: RadioM = 1000.0,
                     orden: str | None = None, sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar(sesion, estado, severidad, codigo, ruta, desde, hasta, cerca_de, radio_m, idruta)
    if orden == ORDEN_PRIORIDAD:
        consulta, orden = _por_prioridad(consulta), "-detectada_en"   # el desempate de ordenar() ya no cambia nada
    return exportar(sesion, consulta, Alerta, formato, "alertas", orden, "-detectada_en")


@router.get("/{alert_id}", response_model=AlertaSalida, summary="Una alerta")
def una(alert_id: uuid.UUID, sesion: Session = Depends(obtener_sesion)):
    a = sesion.get(Alerta, alert_id)
    if a is None:
        raise no_encontrado(RECURSO, alert_id)
    return a


@router.patch("/{alert_id}/status", response_model=AlertaSalida,
              summary="Reconocer, asignar, comentar, cerrar o descartar (queda en la bitácora)")
def cambiar(alert_id: uuid.UUID, solicitud: SolicitudEstadoAlerta, sesion: Session = Depends(obtener_sesion),
            principal: Principal = Depends(autenticar)):
    from app.servicios import alertas

    usuario = usuario_auditoria(principal, solicitud.usuario)   # RNF-011: quién decide es el autenticado
    a = sesion.get(Alerta, alert_id, with_for_update=True)
    if a is None:
        raise no_encontrado(RECURSO, alert_id)
    try:
        nuevo, entrada = alertas.cambiar_estado({"id": str(a.alert_id), "estado": a.estado}, solicitud.accion,
                                                usuario, solicitud.comentario, solicitud.asignado_a)
    except alertas.TransicionInvalida as exc:
        raise ErrorApi(409, "transicion_invalida", str(exc), {"estado_actual": a.estado}) from exc
    except ValueError as exc:
        raise ErrorApi(422, "datos_incompletos", str(exc)) from exc
    anterior = a.estado
    a.estado = nuevo
    if solicitud.accion == "asignar":
        a.asignado_a = solicitud.asignado_a
    # §8.1: las columnas guardan el instante en UTC y la respuesta lo presenta en America/Bogota; el comentario, que
    # vive dentro del JSON, se guarda ya en -05:00 (igual que lo verá el operador en la API y en la exportación)
    instante = ahora()
    if solicitud.comentario:
        a.comentarios = [*a.comentarios, {"usuario": usuario, "comentario": solicitud.comentario,
                                          "accion": solicitud.accion, "en": instante.astimezone(ZONA).isoformat()}]
    a.actualizado_en = instante
    sesion.add(HistorialAlerta(alert_id=a.alert_id, accion=solicitud.accion, estado_anterior=anterior,
                               estado_nuevo=nuevo, usuario=usuario, comentario=solicitud.comentario,
                               asignado_a=solicitud.asignado_a, detalle=json_seguro(entrada)))
    sesion.commit()
    return a


@router.get("/{alert_id}/history", response_model=list[HistorialSalida], summary="Bitácora de cambios de la alerta",
            description="Paginada (§12.1): limite y desplazamiento, orden cronológico (creado_en) o inverso "
                        "(-creado_en) y filtro por acción (crear, redeteccion, escalar, reconocer, asignar, comentar, "
                        "cerrar, descartar). El cuerpo sigue siendo la lista de entradas; el total va en el encabezado "
                        "X-Total-Count.")
def historial(alert_id: uuid.UUID, response: Response, sesion: Session = Depends(obtener_sesion),
              limite: int = Query(500, ge=1, le=1000, description="Tamaño de página"),
              desplazamiento: int = Query(0, ge=0, le=DESPLAZAMIENTO_MAX, description="Registros a saltar"),
              orden: Literal["creado_en", "-creado_en"] = Query("creado_en", description="Orden cronológico"),
              accion: str | None = Query(None, max_length=40, description="Solo las entradas de esta acción")):
    if sesion.get(Alerta, alert_id) is None:
        raise no_encontrado(RECURSO, alert_id)
    consulta = select(HistorialAlerta).where(HistorialAlerta.alert_id == alert_id)
    if accion:
        consulta = consulta.where(HistorialAlerta.accion == accion)
    total = sesion.scalar(select(func.count()).select_from(consulta.subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    if orden == "-creado_en":
        consulta = consulta.order_by(HistorialAlerta.creado_en.desc(), HistorialAlerta.id.desc())
    else:
        consulta = consulta.order_by(HistorialAlerta.creado_en, HistorialAlerta.id)
    return sesion.scalars(consulta.limit(limite).offset(desplazamiento)).all()
