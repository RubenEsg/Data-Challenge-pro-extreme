"""POST/GET /api/v1/frequency/executions: lectura incremental, predicción y optimización como job.

RNF-005: con particion = «ruta» la ejecución se parte en un trabajo por ruta (la madre cierra lo del modelo cuando
terminan); cada ejecución muestra su ruta (null = todas) y su madre. GET /api/v1/frequency/watermarks lista la marca
de agua de cada proceso y ruta.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import (
    EjecucionCreada,
    EjecucionDetalle,
    EjecucionSalida,
    ErrorCalidadSalida,
    MarcaAguaSalida,
    Pagina,
    SolicitudEjecucion,
    TrabajoEjecucion,
)
from app.modelos_db import Alerta, Ejecucion, ErrorCalidad, MarcaAguaRuta, Prediccion, Recomendacion
from app.routers.comun import ErrorApi, ParametrosPagina, no_encontrado, paginar
from app.servicios import ejecucion as servicio

router = APIRouter(prefix="/frequency/executions", tags=["ejecuciones"])
router_marcas = APIRouter(prefix="/frequency/watermarks", tags=["ejecuciones"])


def _inicio_del_dia(dia: date) -> datetime:
    """00:00 del día en America/Bogota (los filtros de fecha se leen en la zona de la operación, §8.1)."""
    return datetime.combine(dia, time(0), tzinfo=servicio.ZONA)


def _rutas_de_la_particion(rutas: list[str] | None) -> list[str]:
    """Las rutas de los trabajos: las pedidas (sin repetir, en su orden) o todas las del catálogo."""
    from app.servicios import datos

    catalogo = datos.nombres_rutas()
    if not rutas:
        return catalogo
    elegidas = list(dict.fromkeys(rutas))
    desconocidas = [r for r in elegidas if r not in catalogo]
    if desconocidas:
        raise ErrorApi(422, "ruta_desconocida", "Para partir la ejecución por ruta, cada ruta debe estar en el "
                       "catálogo", {"desconocidas": desconocidas[:20], "validas": catalogo})
    return elegidas


@router.post("", response_model=EjecucionCreada, status_code=202,
             summary="Ejecutar lectura incremental, predicción y optimización (job en segundo plano)")
def crear(solicitud: SolicitudEjecucion, tareas: BackgroundTasks, request: Request,
          sesion: Session = Depends(obtener_sesion)):
    parametros = solicitud.model_dump(mode="json", exclude={"particion"})
    correlacion = getattr(request.state, "correlation_id", None)
    if solicitud.particion == servicio.PARTICION_RUTA:
        madre, trabajos = servicio.crear_ejecucion_partida(sesion, parametros, correlacion,
                                                           _rutas_de_la_particion(solicitud.rutas))
        tareas.add_task(servicio.ejecutar, madre.execution_id, [t.execution_id for t in trabajos])
        salida = EjecucionCreada.model_validate(madre)
        salida.trabajos = [TrabajoEjecucion.model_validate(t) for t in trabajos]
        return salida
    e = servicio.crear_ejecucion(sesion, "frecuencia", parametros, correlacion)
    tareas.add_task(servicio.ejecutar, e.execution_id)
    return e


@router.get("", response_model=Pagina[EjecucionSalida], summary="Listar ejecuciones")
def listar(estado: str | None = None, tipo: str | None = None,
           desde: date | None = Query(None, description="Creadas desde este día (incluido, America/Bogota)"),
           hasta: date | None = Query(None, description="Creadas hasta este día (incluido, America/Bogota)"),
           model_id: str | None = Query(None, description="Modelo con el que corrió la ejecución"),
           ruta: str | None = Query(None, description="RNF-005: solo los trabajos de esta ruta"),
           padre_id: uuid.UUID | None = Query(None, description="RNF-005: solo los trabajos de esta ejecución partida"),
           pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    if desde and hasta and desde > hasta:
        raise ErrorApi(422, "rango_invalido", "desde no puede ser posterior a hasta",
                       {"desde": desde.isoformat(), "hasta": hasta.isoformat()})
    consulta = select(Ejecucion)
    for columna, valor in ((Ejecucion.estado, estado), (Ejecucion.tipo, tipo), (Ejecucion.model_id, model_id),
                           (Ejecucion.ruta, ruta), (Ejecucion.padre_id, padre_id)):
        if valor:
            consulta = consulta.where(columna == valor)
    if desde:
        consulta = consulta.where(Ejecucion.creado_en >= _inicio_del_dia(desde))
    if hasta and hasta < date.max:          # 9999-12-31 no tiene día siguiente: equivale a no acotar
        consulta = consulta.where(Ejecucion.creado_en < _inicio_del_dia(hasta + timedelta(days=1)))
    return paginar(sesion, consulta, Ejecucion, pagina, "-creado_en")


def _trabajos(sesion: Session, execution_id: uuid.UUID) -> list[Ejecucion]:
    return list(sesion.scalars(select(Ejecucion).where(Ejecucion.padre_id == execution_id)
                               .order_by(Ejecucion.creado_en, Ejecucion.execution_id)).all())


def _contar(sesion: Session, modelo, ids: list[uuid.UUID]) -> int:
    return sesion.scalar(select(func.count()).select_from(modelo).where(modelo.execution_id.in_(ids))) or 0


@router.get("/{execution_id}", response_model=EjecucionDetalle, summary="Corte, estado, métricas y errores")
def detalle(execution_id: uuid.UUID, sesion: Session = Depends(obtener_sesion)):
    e = sesion.get(Ejecucion, execution_id)
    if e is None:
        raise no_encontrado("La ejecución", execution_id)
    salida = EjecucionDetalle.model_validate(e)
    trabajos = _trabajos(sesion, execution_id)
    salida.trabajos = [TrabajoEjecucion.model_validate(t) for t in trabajos]
    ids = [execution_id, *(t.execution_id for t in trabajos)]      # RNF-005: la madre suma lo de sus trabajos
    salida.errores_por_dimension = dict(sesion.execute(
        select(ErrorCalidad.dimension, func.count()).where(ErrorCalidad.execution_id.in_(ids))
        .group_by(ErrorCalidad.dimension)).all())
    salida.errores_muestra = [ErrorCalidadSalida.model_validate(x) for x in sesion.scalars(
        select(ErrorCalidad).where(ErrorCalidad.execution_id.in_(ids)).order_by(ErrorCalidad.id).limit(20))]
    salida.predicciones = _contar(sesion, Prediccion, ids)
    por_origen = dict(sesion.execute(select(Recomendacion.origen, func.count())
                                     .where(Recomendacion.execution_id.in_(ids))
                                     .group_by(Recomendacion.origen)).all())
    salida.recomendaciones = int(por_origen.get("franja", 0))
    salida.recomendaciones_plan_dia = int(por_origen.get("plan_dia", 0))
    salida.alertas = _contar(sesion, Alerta, ids)
    return salida


@router.get("/{execution_id}/errors", response_model=Pagina[ErrorCalidadSalida],
            summary="Errores de calidad de la ejecución por lote, fila, llave y causa")
def errores(execution_id: uuid.UUID, lote: str | None = None, dimension: str | None = None,
            codigo: str | None = Query(None),
            idruta: int | None = Query(None, ge=0, le=2_147_483_647,
                                       description="Solo los errores de registros de esta ruta (§8.3 idruta)"),
            bloqueante: bool | None = Query(None, description="true: solo los que rechazan la fila"),
            pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    if sesion.get(Ejecucion, execution_id) is None:
        raise no_encontrado("La ejecución", execution_id)
    ids = [execution_id, *(t.execution_id for t in _trabajos(sesion, execution_id))]
    consulta = select(ErrorCalidad).where(ErrorCalidad.execution_id.in_(ids))
    for col, val in ((ErrorCalidad.lote, lote), (ErrorCalidad.dimension, dimension), (ErrorCalidad.codigo, codigo)):
        if val:
            consulta = consulta.where(col == val)
    if bloqueante is not None:
        consulta = consulta.where(ErrorCalidad.bloqueante.is_(bloqueante))
    if idruta is not None:
        # la llave del registro trae el nombre de la ruta (esquema de demanda) o id_ruta (consolidado de Extreme)
        from app.servicios import dimensiones

        nombre = next((r for r, f in dimensiones.mapa_rutas().items() if f["idruta"] == idruta), None)
        condiciones = [ErrorCalidad.llave["id_ruta"].astext == str(idruta),
                       ErrorCalidad.llave["idruta"].astext == str(idruta)]
        if nombre is not None:
            condiciones.append(ErrorCalidad.llave["ruta"].astext == nombre)
        consulta = consulta.where(or_(*condiciones))
    return paginar(sesion, consulta, ErrorCalidad, pagina, "id")


@router_marcas.get("", response_model=list[MarcaAguaSalida],
                   summary="Marca de agua de la lectura incremental por proceso y ruta (RNF-005)")
def marcas_de_agua(proceso: str | None = Query(None, description="Solo este proceso (FUENTE_PROCESO)"),
                   sesion: Session = Depends(obtener_sesion)):
    """Desde dónde leerá cada ruta la próxima ejecución. La fila con ruta «*» es la frontera de las lecturas de todas
    las rutas del proceso (la usa una ruta sin marca propia); las de origen «migracion_0009» heredaron la marca
    global de antes."""
    consulta = select(MarcaAguaRuta).order_by(MarcaAguaRuta.proceso, MarcaAguaRuta.ruta)
    if proceso:
        consulta = consulta.where(MarcaAguaRuta.proceso == proceso)
    return [MarcaAguaSalida(proceso=f.proceso, ruta=f.ruta, marca_agua=f.marca_agua, execution_id=f.execution_id,
                            origen=f.origen, actualizado_en=f.actualizado_en,
                            huellas=len((f.estado_fuente or {}).get("huellas") or {}))
            for f in sesion.scalars(consulta.limit(1000)).all()]
