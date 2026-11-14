"""Catálogos operacionales (§3.1 «Gestión operacional»): empresa, proceso, ruta, segmento, vehículo, capacidad, viaje
y despacho, de solo lectura desde la réplica (o los archivos offline), con filtros, paginación, orden y exportación
CSV/XLSX (§12.1, RF-016, RF-017). Lo que se administra son los parámetros operativos propios: la capacidad por ruta y
tipología y la flota disponible y el tiempo de ciclo por ruta, tipo de día y hora. Viven solo en ai_frecuencias como
parámetros gobernados y versionados (§3.2, §5.1, §8.3), con auditoría e historial; cambiarlos exige el rol admin.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.routers.comun import ErrorApi, ParametrosPagina
from app.seguridad import Principal, autenticar, usuario_auditoria
from app.servicios import catalogos as C
from app.servicios import flota_ciclo as F
from app.servicios.ejecucion import umbrales_vigentes

router = APIRouter(prefix="/catalogos", tags=["catálogos"])
T = TypeVar("T")
Formato = Literal["csv", "xlsx"]
Geometria = Literal["simplificada", "completa", "ninguna"]
# Filtros acotados: un valor fuera de rango es un 422 (nunca un desbordamiento en pandas ni en PostgreSQL).
MAX_ID = 2_147_483_647
IdRuta = Annotated[int | None, Query(ge=0, le=MAX_ID, description="idruta de la tabla rutas")]
IdConfig = Annotated[int | None, Query(ge=0, le=MAX_ID, description="id de rutas_segmentos_config")]
NroSegmento = Annotated[int | None, Query(ge=0, le=1_000_000)]
IdVehiculo = Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
Retraso = Annotated[float | None, Query(ge=-100_000, le=100_000, description="Minutos (salida real - programada)")]
Texto = Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[^\x00]+$")]
Limite = Annotated[int, Query(ge=1, le=500, description="Tamaño de página")]
Desplazamiento = Annotated[int, Query(ge=0, le=1_000_000, description="Eventos a saltar")]
TipoDia = Literal["Laboral", "Sábado", "Domingo/festivo", "TODOS"]


class PaginaCatalogo(BaseModel, Generic[T]):
    total: int
    limite: int
    desplazamiento: int
    fuente: str = Field(..., description="replica (solo lectura), archivos (exportaciones Parquet) o flota_csv")
    consultado_en: datetime
    items: list[T]


class ProcesoSalida(BaseModel):
    proceso: str
    nombre: str | None = None
    estado: str | None = None
    toleranciatiempo: int | None = None
    multaatraso: int | None = None
    multaadelanto: int | None = None
    penaliza: str | None = None
    maneja_capac_veh: bool | None = None
    maneja_hora_pico: bool | None = None
    id_estacionalidad: int | None = None
    ultima_estacionalidad: date | None = None
    rutas: int = 0


class EmpresaSalida(BaseModel):
    idempresa: int | None = None
    proceso: str | None = None
    proceso_nombre: str | None = None
    rutas: int
    idrutas: list[int]


class RutaSalida(BaseModel):
    idruta: int
    ruta: str
    codigo: str | None = None
    nombre: str | None = None
    proceso: str | None = None
    idempresa: int | None = None
    estado_ruta: str | None = None
    frecuenciadespachos: str | None = Field(None, description="Frecuencia vigente de la tabla rutas (texto original)")
    frecuenciadespachos_min: float | None = None
    primerdespacho: str | None = None
    tolsalida: int | None = None
    tolerancia: int | None = None
    tiempoplazosalida: int | None = None
    distancia_global: float | None = None
    tiempo_global: float | None = None
    flotadisp_prog: str | None = None
    capacidad: float | None = Field(None, description="Capacidad nominal por bus (tabla rutas o regla del reto)")
    cap_min_autorizada: float | None = Field(None, description="Si la tabla rutas la trae (§6.1)")
    cap_max_autorizada: float | None = Field(None, description="Si la tabla rutas la trae (§6.1)")
    capacidad_vigente: int
    capacidad_fuente: str
    tiempo_ciclo_min: float | None = Field(None, description="Referencia del catálogo empaquetado (mediana de día "
                                                             "laboral de D1); el ciclo vigente por tipo de día y hora, "
                                                             "con el ajuste local, está en GET /catalogos/flota")
    flota: int | None = Field(None, description="Referencia del catálogo empaquetado (día laboral de D1); la flota "
                                                "vigente por tipo de día, con el ajuste local, está en GET "
                                                "/catalogos/flota")
    frecuencia_actual_min: float | None = None
    por_tipo_dia: dict[str, Any] = Field(default_factory=dict)


class RutaDetalle(RutaSalida):
    parametros_por_hora: list[dict[str, Any]] = Field(default_factory=list)
    capacidad_detalle: dict[str, Any] = Field(default_factory=dict)
    flota_y_ciclo: dict[str, Any] = Field(default_factory=dict,
                                          description="Flota disponible y tiempo de ciclo vigentes por tipo de día y "
                                                      "hora, con su fuente (catálogo o ajuste local; ver GET "
                                                      "/catalogos/flota)")


class SegmentoSalida(BaseModel):
    id: int
    id_config: int | None = None
    idruta: int
    ruta: str | None = None
    idrutageo: int | None = None
    nro_segmento: int
    activo: bool | None = None
    longitud_m: float | None = None
    vertices_original: int | None = None
    vertices: int | None = None
    geometria: dict[str, Any] | None = Field(None, description="GeoJSON LineString (EPSG:4326)")


class VehiculoSalida(BaseModel):
    idvehiculo: str | None = None
    idruta: int | None = None
    ruta: str | None = None
    tipologia: str
    tipovehiculo: int | None = None
    carroceria: str | None = None
    marca: str | None = None
    modelo: str | None = None
    n_sentados: int | None = None
    n_depie: int | None = None
    capacidad_total: float | None = Field(None, description="Sentados + de pie")
    activo: bool | None = None
    despacho_habilitado: bool | None = None


class TipologiaSalida(BaseModel):
    idruta: int | None = None
    ruta: str | None = None
    tipologia: str
    vehiculos: int
    capacidad_mediana: float
    capacidad_min: float
    capacidad_max: float
    sentados_mediana: float | None = None
    depie_mediana: float | None = None


class ViajeSalida(BaseModel):
    idprogramacion: int
    idruta: int | None = None
    ruta: str | None = None
    idvehiculo: str | None = None
    fecha: date | None = None
    hora_programada: datetime | None = None
    registrado_en: datetime | None = None
    estado: str
    cancelada: bool | None = None
    finalizado: bool | None = None


class DespachoSalida(BaseModel):
    idprogramacion: int
    idruta: int | None = None
    ruta: str | None = None
    idvehiculo: str | None = None
    fecha: date | None = None
    hora_programada: datetime | None = None
    salida_real: datetime
    llegada: datetime | None = None
    retraso_min: float | None = Field(None, description="salida real - hora programada (min)")
    duracion_min: float | None = None
    pasajeros: int | None = None
    finalizado: bool | None = None


class CapacidadSalida(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    ruta: str
    idruta: int
    tipologia: str
    capacidad: int
    capacidad_catalogo: int
    fuente: str
    clave: str | None = None
    umbrales_version: int | None = None
    por_tipologia: dict[str, int] = Field(default_factory=dict)


class SolicitudCapacidad(BaseModel):
    idruta: int = Field(..., description="idruta de la tabla rutas (llave sin cambiar su semántica, RF-014)")
    tipologia: str = Field(C.TIPOLOGIA_TODAS, description="TODAS (toda la ruta) o una tipología, p. ej. BUSETA")
    capacidad: int | None = Field(..., ge=C.CAPACIDAD_MIN, le=C.CAPACIDAD_MAX,
                                  description="Pasajeros por bus; null retira el ajuste")
    motivo: str = Field(..., min_length=3)
    creado_por: str | None = Field(None, description="Se ignora con autenticación: firma el principal")


class EventoCapacidad(BaseModel):
    version: int
    idruta: int
    ruta: str | None = None
    tipologia: str
    accion: str
    capacidad_anterior: Any = None
    capacidad_nueva: Any = None
    creado_por: str
    motivo: str | None = None
    creado_en: datetime | None = None


class CicloHora(BaseModel):
    hora: int = Field(..., description="Hora de salida (4 a 20)")
    tiempo_ciclo_min: float | None = Field(None, description="Vigente: el ajuste local o, si no hay, el del catálogo")
    tiempo_ciclo_catalogo_min: float | None = Field(None, description="Dato empaquetado (mediana 2025 de D1)")
    fuente: str = Field(..., description="catalogo o ajuste_local")
    clave: str | None = Field(None, description="Parámetro de threshold_config que manda (ciclo_override…)")


class FlotaTipoDia(BaseModel):
    tipo_dia: str
    flota: int | None = Field(None, description="Flota disponible vigente (vehículos)")
    flota_catalogo: int | None = Field(None, description="Dato empaquetado (mediana 2025 de D1)")
    flota_fuente: str = Field(..., description="catalogo o ajuste_local")
    flota_clave: str | None = Field(None, description="Parámetro de threshold_config que manda (flota_override…)")
    horas: list[CicloHora] = Field(default_factory=list)


class FlotaCicloSalida(BaseModel):
    ruta: str
    idruta: int
    umbrales_version: int | None = Field(None, description="Versión de threshold_config con la que se leyó")
    por_tipo_dia: list[FlotaTipoDia]
    ajustes: dict[str, float] = Field(default_factory=dict, description="Ajustes locales vigentes de la ruta")


class SolicitudFlotaCiclo(BaseModel):
    idruta: int = Field(..., ge=0, le=MAX_ID, description="idruta de la tabla rutas (llave sin cambiar su semántica)")
    tipo_dia: TipoDia = Field("TODOS", description="Tipo de día del ajuste; TODOS vale para los tres")
    flota: int | None = Field(None, ge=F.FLOTA_MIN, le=F.FLOTA_MAX,
                              description="Vehículos disponibles. null retira el ajuste de flota; si el campo no "
                                          "viene, la flota no cambia")
    tiempo_ciclo_min: float | None = Field(None, ge=F.CICLO_MIN, le=F.CICLO_MAX,
                                           description="Minutos de vuelta completa. null retira el ajuste de ciclo; "
                                                       "si el campo no viene, el ciclo no cambia")
    hora: int | None = Field(None, ge=4, le=20, description="Hora de salida del ajuste de ciclo (4 a 20); sin hora, "
                                                            "todas las horas de servicio")
    motivo: str = Field(..., min_length=3)
    creado_por: str | None = Field(None, description="Se ignora con autenticación: firma el principal")


class EventoFlotaCiclo(BaseModel):
    version: int
    idruta: int
    ruta: str | None = None
    parametro: Literal["flota", "tiempo_ciclo_min"]
    tipo_dia: str
    hora: int | None = Field(None, description="Hora del ajuste de ciclo; null = todas las horas (o la flota)")
    accion: str = Field(..., description="creado, cambiado o retirado")
    valor_anterior: float | None = None
    valor_nuevo: float | None = None
    creado_por: str
    motivo: str | None = None
    creado_en: datetime | None = None


class IndiceCatalogos(BaseModel):
    fuente: str
    solo_lectura: bool = True
    catalogos: list[dict[str, str]]


# ---------------------------------------------------------------- utilidades
def _ahora() -> datetime:
    return datetime.now(C.ZONA)


def _ejecutar(funcion, *args, **kwargs):
    """Errores del servicio -> respuesta uniforme (§12.1).

    Política de degradación, la misma en todos los catálogos (RNF-010): si la fuente no existe en esta máquina (sin
    réplica configurada y sin las exportaciones Parquet) o la réplica no responde (conexión rechazada, tiempo de
    espera o circuito abierto), la respuesta es un 503 declarado en el OpenAPI con el error uniforme y la razón
    («catalogo_no_disponible» o «fuente_no_disponible»). Nunca un 500."""
    from app.servicios.circuito import CircuitoAbierto, es_falla_de_infraestructura
    from app.servicios.fuentes import OperacionNoPermitida

    try:
        return funcion(*args, **kwargs)
    except C.FiltroInvalido as exc:
        raise ErrorApi(422, "filtro_invalido", str(exc)) from exc
    except C.CatalogoNoDisponible as exc:
        raise ErrorApi(503, "catalogo_no_disponible", str(exc)) from exc
    except CircuitoAbierto as exc:
        raise ErrorApi(503, "fuente_no_disponible", "La réplica no responde (circuito abierto); reintente luego",
                       {"integracion": "fuente_postgres"}) from exc
    except OperacionNoPermitida as exc:          # no debería pasar: las consultas son fijas
        raise ErrorApi(500, "operacion_no_permitida", str(exc)) from exc
    except Exception as exc:
        if not es_falla_de_infraestructura(exc):
            raise
        # réplica configurada pero inalcanzable, antes de que el circuito llegue a abrirse
        raise ErrorApi(503, "fuente_no_disponible", "La réplica no respondió (conexión o tiempo de espera); "
                       "reintente luego", {"integracion": "fuente_postgres", "error": type(exc).__name__}) from exc


def _pagina(df, catalogo: str, fuente: str, pagina: ParametrosPagina, total: int | None = None) -> dict:
    if total is None:
        df, total = _ejecutar(C.paginar, df, catalogo, pagina.orden, pagina.limite, pagina.desplazamiento)
    return {"total": int(total), "limite": pagina.limite, "desplazamiento": pagina.desplazamiento, "fuente": fuente,
            "consultado_en": _ahora(), "items": C.registros(df, C.COLUMNAS[catalogo])}


def _archivo(df, catalogo: str, formato: str, orden: str | None, columnas: list[str] | None = None) -> Response:
    if orden is not None or catalogo in C.ORDEN_POR_DEFECTO:
        df, _ = _ejecutar(C.paginar, df, catalogo, orden, C.LIMITE_EXPORTACION, 0)
    contenido, media, nombre = C.exportar(df, columnas or C.COLUMNAS[catalogo], formato, catalogo)
    return Response(contenido, media_type=media, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _umbrales(sesion: Session) -> tuple[int | None, dict]:
    try:
        return umbrales_vigentes(sesion)
    except Exception:  # noqa: BLE001 - sin base de resultados: capacidad del catálogo (queda en el log)
        C.log.warning("No se pudieron leer los umbrales vigentes; se usa la capacidad del catálogo")
        return None, {}


# ---------------------------------------------------------------- índice
@router.get("", response_model=IndiceCatalogos, summary="Catálogos disponibles y fuente configurada")
def indice():
    fuente = _ejecutar(C.modo)
    nombres = {"procesos": "Procesos (raíz de las relaciones) y sus parámetros operativos",
               "empresas": "Empresas (idempresa) por proceso",
               "rutas": "Rutas con frecuencia, capacidad, ciclo y flota",
               "segmentos": "Segmentos de ruta con longitud y geometría GeoJSON",
               "vehiculos": "Vehículos con capacidad sentados + de pie y tipología (sin datos personales)",
               "viajes": "Programación de viajes (progvehiculos)", "despachos": "Despachos reales (salida y llegada)",
               "capacidad": "Capacidad vigente por ruta y tipología (ajuste local versionado)",
               "flota": "Flota disponible y tiempo de ciclo vigentes por ruta, tipo de día y hora (ajuste local "
                        "versionado)"}
    return {"fuente": fuente, "catalogos": [{"nombre": n, "descripcion": d, "ruta": f"/api/v1/catalogos/{n}"}
                                            for n, d in nombres.items()]}


# ---------------------------------------------------------------- procesos y empresas
@router.get("/procesos", response_model=PaginaCatalogo[ProcesoSalida], summary="Procesos (empresa operadora)")
def listar_procesos(estado: Texto = None, pagina: ParametrosPagina = Depends()):
    d, fuente = _ejecutar(C.procesos)
    return _pagina(_ejecutar(C.filtrar, d, estado=estado), "procesos", fuente, pagina)


@router.get("/procesos/export", summary="Exportar procesos (CSV o XLSX)", response_class=Response)
def exportar_procesos(formato: Formato = "csv", estado: Texto = None, orden: Texto = None):
    d, _ = _ejecutar(C.procesos)
    return _archivo(_ejecutar(C.filtrar, d, estado=estado), "procesos", formato, orden)


@router.get("/empresas", response_model=PaginaCatalogo[EmpresaSalida], summary="Empresas por proceso")
def listar_empresas(proceso: Texto = None, pagina: ParametrosPagina = Depends()):
    d, fuente = _ejecutar(C.empresas)
    return _pagina(_ejecutar(C.filtrar, d, proceso=proceso), "empresas", fuente, pagina)


@router.get("/empresas/export", summary="Exportar empresas (CSV o XLSX)", response_class=Response)
def exportar_empresas(formato: Formato = "csv", proceso: Texto = None, orden: Texto = None):
    d, _ = _ejecutar(C.empresas)
    return _archivo(_ejecutar(C.filtrar, d, proceso=proceso), "empresas", formato, orden)


# ---------------------------------------------------------------- rutas
@router.get("/rutas", response_model=PaginaCatalogo[RutaSalida],
            summary="Rutas: frecuencia vigente, capacidad (y cap_min/cap_max si existen), ciclo y flota")
def listar_rutas(proceso: Texto = None, estado_ruta: Texto = None, pagina: ParametrosPagina = Depends(),
                 sesion: Session = Depends(obtener_sesion)):
    _, umbrales = _umbrales(sesion)
    d, fuente = _ejecutar(C.rutas, umbrales=umbrales)
    return _pagina(_ejecutar(C.filtrar, d, proceso=proceso, estado_ruta=estado_ruta), "rutas", fuente, pagina)


@router.get("/rutas/export", summary="Exportar rutas (CSV o XLSX)", response_class=Response)
def exportar_rutas(formato: Formato = "csv", proceso: Texto = None, orden: Texto = None,
                   sesion: Session = Depends(obtener_sesion)):
    _, umbrales = _umbrales(sesion)
    d, _ = _ejecutar(C.rutas, umbrales=umbrales)
    return _archivo(_ejecutar(C.filtrar, d, proceso=proceso), "rutas", formato, orden)


@router.get("/rutas/{idruta}", response_model=RutaDetalle, summary="Una ruta con sus parámetros por hora")
def una_ruta(idruta: Annotated[int, Path(ge=0, le=MAX_ID)], sesion: Session = Depends(obtener_sesion)):
    version, umbrales = _umbrales(sesion)
    d, _ = _ejecutar(C.rutas, umbrales=umbrales)
    fila = d[d["idruta"] == idruta]
    if not len(fila):
        raise ErrorApi(404, "no_encontrado", f"ruta {idruta} no existe en el catálogo")
    item = C.registros(fila, C.COLUMNAS["rutas"])[0]
    item["parametros_por_hora"] = C.parametros_por_hora(idruta)
    item["capacidad_detalle"] = C.capacidad_vigente(idruta, umbrales=umbrales, umbrales_version=version)
    item["flota_y_ciclo"] = F.vigente(idruta, None, umbrales=umbrales, umbrales_version=version)[0]
    return item


# ---------------------------------------------------------------- segmentos
def _filtrar_segmentos(d, idruta, id_config, activo, nro_desde, nro_hasta):
    d = _ejecutar(C.filtrar, d, idruta=idruta, id_config=id_config, activo=activo)
    if nro_desde is not None:
        d = d[d["nro_segmento"] >= nro_desde]
    if nro_hasta is not None:
        d = d[d["nro_segmento"] <= nro_hasta]
    return d


def _segmentos(idruta, id_config, activo, nro_desde, nro_hasta, geometria):
    d, fuente = _ejecutar(C.segmentos, geometria=geometria, idruta=idruta)
    return _filtrar_segmentos(d, idruta, id_config, activo, nro_desde, nro_hasta), fuente


@router.get("/segmentos", response_model=PaginaCatalogo[SegmentoSalida],
            summary="Segmentos de ruta (rutas_segmentos) con longitud y geometría GeoJSON")
def listar_segmentos(idruta: IdRuta = None, id_config: IdConfig = None, activo: bool | None = None,
                     nro_desde: NroSegmento = None, nro_hasta: NroSegmento = None,
                     geometria: Geometria = Query("simplificada", description="simplificada (~1 m), completa o "
                                                                              "ninguna"),
                     pagina: ParametrosPagina = Depends()):
    # RNF-002: se filtra y pagina sin geometría; la geometría (y los vértices de la original) se arma solo para los
    # segmentos de esta página, no para los 2.695 de la tabla
    d, fuente = _ejecutar(C.segmentos_listado, idruta=idruta)
    respuesta = _pagina(_filtrar_segmentos(d, idruta, id_config, activo, nro_desde, nro_hasta), "segmentos", fuente,
                        pagina)
    geos = _ejecutar(C.geometria_de_pagina, [it["id"] for it in respuesta["items"]], geometria)
    for it in respuesta["items"]:
        it.update(geos.get(it["id"], {"geometria": None, "vertices": 0}))
    return respuesta


@router.get("/segmentos/export", summary="Exportar segmentos (CSV o XLSX; geometría simplificada como GeoJSON)",
            response_class=Response)
def exportar_segmentos(formato: Formato = "csv", idruta: IdRuta = None, id_config: IdConfig = None,
                       activo: bool | None = None,
                       geometria: Literal["simplificada", "ninguna"] = "ninguna", orden: Texto = None):
    d, _ = _segmentos(idruta, id_config, activo, None, None, geometria)
    return _archivo(d, "segmentos", formato, orden)


# ---------------------------------------------------------------- vehículos
def _vehiculos(idruta, tipologia, activo, despacho_habilitado):
    d, fuente = _ejecutar(C.vehiculos)
    return _ejecutar(C.filtrar, d, idruta=idruta, tipologia=tipologia, activo=activo,
                     despacho_habilitado=despacho_habilitado), fuente


@router.get("/vehiculos", response_model=PaginaCatalogo[VehiculoSalida],
            summary="Vehículos: capacidad sentados + de pie y tipología (sin placa, conductor ni propietario)")
def listar_vehiculos(idruta: IdRuta = None, tipologia: Texto = None, activo: bool | None = None,
                     despacho_habilitado: bool | None = None, pagina: ParametrosPagina = Depends()):
    d, fuente = _vehiculos(idruta, tipologia, activo, despacho_habilitado)
    return _pagina(d, "vehiculos", fuente, pagina)


@router.get("/vehiculos/export", summary="Exportar vehículos (CSV o XLSX)", response_class=Response)
def exportar_vehiculos(formato: Formato = "csv", idruta: IdRuta = None, tipologia: Texto = None,
                       activo: bool | None = None, despacho_habilitado: bool | None = None,
                       orden: Texto = None):
    d, _ = _vehiculos(idruta, tipologia, activo, despacho_habilitado)
    return _archivo(d, "vehiculos", formato, orden)


@router.get("/vehiculos/tipologias", response_model=list[TipologiaSalida],
            summary="Capacidad por ruta y tipología (vehículos, mediana, mínimo y máximo)")
def listar_tipologias(idruta: IdRuta = None):
    d, _ = _ejecutar(C.tipologias)
    d = _ejecutar(C.filtrar, d, idruta=idruta)
    return C.registros(d, list(TipologiaSalida.model_fields))


# ---------------------------------------------------------------- viajes y despachos
@router.get("/viajes", response_model=PaginaCatalogo[ViajeSalida],
            summary="Programación de viajes (idprogramacion, ruta, hora programada y vehículo)")
def listar_viajes(idruta: IdRuta = None, desde: date | None = None, hasta: date | None = None,
                  idvehiculo: IdVehiculo = None,
                  estado: Literal["programado", "cancelado", "finalizado"] | None = None,
                  pagina: ParametrosPagina = Depends()):
    d, total, fuente = _ejecutar(C.programacion, "viajes", idruta=idruta, desde=desde, hasta=hasta,
                                 idvehiculo=idvehiculo, estado=estado, orden=pagina.orden, limite=pagina.limite,
                                 desplazamiento=pagina.desplazamiento)
    return _pagina(d, "viajes", fuente, pagina, total=total)


@router.get("/viajes/export", summary="Exportar viajes filtrados (CSV o XLSX)", response_class=Response)
def exportar_viajes(formato: Formato = "csv", idruta: IdRuta = None, desde: date | None = None,
                    hasta: date | None = None, idvehiculo: IdVehiculo = None,
                    estado: Literal["programado", "cancelado", "finalizado"] | None = None,
                    orden: Texto = None):
    d, _, _ = _ejecutar(C.programacion, "viajes", idruta=idruta, desde=desde, hasta=hasta, idvehiculo=idvehiculo,
                        estado=estado, orden=orden, limite=C.LIMITE_EXPORTACION, desplazamiento=0)
    contenido, media, nombre = C.exportar(d, C.COLUMNAS["viajes"], formato, "viajes")
    return Response(contenido, media_type=media, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/despachos", response_model=PaginaCatalogo[DespachoSalida],
            summary="Despachos reales: salida y llegada, retraso frente a la hora programada")
def listar_despachos(idruta: IdRuta = None, desde: date | None = None, hasta: date | None = None,
                     idvehiculo: IdVehiculo = None, retraso_minimo: Retraso = None,
                     pagina: ParametrosPagina = Depends()):
    d, total, fuente = _ejecutar(C.programacion, "despachos", idruta=idruta, desde=desde, hasta=hasta,
                                 idvehiculo=idvehiculo, retraso_minimo=retraso_minimo, orden=pagina.orden,
                                 limite=pagina.limite, desplazamiento=pagina.desplazamiento)
    return _pagina(d, "despachos", fuente, pagina, total=total)


@router.get("/despachos/export", summary="Exportar despachos filtrados (CSV o XLSX)", response_class=Response)
def exportar_despachos(formato: Formato = "csv", idruta: IdRuta = None, desde: date | None = None,
                       hasta: date | None = None, idvehiculo: IdVehiculo = None,
                       retraso_minimo: Retraso = None, orden: Texto = None):
    d, _, _ = _ejecutar(C.programacion, "despachos", idruta=idruta, desde=desde, hasta=hasta, idvehiculo=idvehiculo,
                        retraso_minimo=retraso_minimo, orden=orden, limite=C.LIMITE_EXPORTACION, desplazamiento=0)
    contenido, media, nombre = C.exportar(d, C.COLUMNAS["despachos"], formato, "despachos")
    return Response(contenido, media_type=media, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# ---------------------------------------------------------------- capacidad (ajuste local versionado)
@router.get("/capacidad", response_model=list[CapacidadSalida],
            summary="Capacidad vigente por ruta (catálogo o ajuste local) y ajustes por tipología")
def capacidad(idruta: IdRuta = None, tipologia: Texto = None, sesion: Session = Depends(obtener_sesion)):
    version, umbrales = _umbrales(sesion)
    rutas = [r for r in C.rutas_api() if idruta is None or int(r["idruta"]) == idruta]
    if idruta is not None and not rutas:
        raise ErrorApi(404, "no_encontrado", f"ruta {idruta} no existe en el catálogo")
    try:
        return [C.capacidad_vigente(r["idruta"], tipologia, umbrales=umbrales, umbrales_version=version)
                for r in rutas]
    except ValueError as exc:
        raise ErrorApi(422, "tipologia_invalida", str(exc)) from exc


def _registrar_version(sesion: Session, fijar, *args, invalido: str) -> None:
    """Versión nueva de un ajuste local (fijar = la función del servicio) con los errores en el formato uniforme: ruta
    desconocida (422), retiro de un ajuste que no está vigente (404) o valor inválido (422 con el código `invalido`).
    Ante cualquiera de ellos se revierte la transacción: el conjunto vigente no cambia."""
    try:
        fijar(sesion, *args)
    except KeyError as exc:
        sesion.rollback()
        raise ErrorApi(422, "ruta_desconocida", str(exc).strip("'\"")) from exc
    except LookupError as exc:
        sesion.rollback()
        raise ErrorApi(404, "ajuste_inexistente", str(exc)) from exc
    except ValueError as exc:
        sesion.rollback()
        raise ErrorApi(422, invalido, str(exc)) from exc


def _pagina_de_eventos(response: Response, eventos: list[dict], limite: int, desplazamiento: int) -> list[dict]:
    """Una página del historial (del más reciente al más antiguo) con el total en la cabecera X-Total-Count."""
    response.headers["X-Total-Count"] = str(len(eventos))
    return eventos[desplazamiento:desplazamiento + limite]


@router.put("/capacidad", response_model=CapacidadSalida,
            summary="Ajustar la capacidad operativa de una ruta o tipología (admin; versión nueva y auditada)")
def ajustar_capacidad(solicitud: SolicitudCapacidad, sesion: Session = Depends(obtener_sesion),
                      principal: Principal = Depends(autenticar)):
    creado_por = usuario_auditoria(principal, solicitud.creado_por)      # RNF-011: firma el autenticado
    _registrar_version(sesion, C.fijar_capacidad, solicitud.idruta, solicitud.tipologia, solicitud.capacidad,
                       creado_por, solicitud.motivo, invalido="capacidad_invalida")
    version, umbrales = umbrales_vigentes(sesion)
    tip = None if solicitud.tipologia.strip().upper() == C.TIPOLOGIA_TODAS else solicitud.tipologia
    return C.capacidad_vigente(solicitud.idruta, tip, umbrales=umbrales, umbrales_version=version)


@router.get("/capacidad/historial", response_model=list[EventoCapacidad],
            summary="Historial de ajustes de capacidad (versión, acción, valor anterior y nuevo, quién y por qué)",
            description="Del más reciente al más antiguo, paginado con limite y desplazamiento; el total de eventos "
                        "va en la cabecera X-Total-Count.")
def historial_capacidad(response: Response, idruta: IdRuta = None, limite: Limite = 100,
                        desplazamiento: Desplazamiento = 0, sesion: Session = Depends(obtener_sesion)):
    return _pagina_de_eventos(response, C.historial_capacidad(sesion, idruta), limite, desplazamiento)


# ---------------------------------------------------------------- flota y tiempo de ciclo (ajuste local versionado)
DESCRIPCION_FLOTA = (
    "§3.1 «Gestión operacional» y §10.2: flota disponible por ruta y tipo de día y tiempo de ciclo por ruta, tipo de "
    "día y hora de salida. Sin ajuste rige el dato empaquetado (datos/parametros_operativos_hora.parquet, mediana 2025 "
    "de D1); el ajuste local vive en threshold_config (flota_override y ciclo_override), se versiona y se audita como "
    "los umbrales, y lo usan la recomendación de la franja y el plan del día desde la versión siguiente, sin "
    "reiniciar.")


@router.get("/flota", response_model=list[FlotaCicloSalida],
            summary="Flota disponible y tiempo de ciclo vigentes por ruta, tipo de día y hora (catálogo o ajuste "
                    "local)", description=DESCRIPCION_FLOTA)
def flota_y_ciclo(idruta: IdRuta = None,
                  tipo_dia: Annotated[TipoDia | None, Query(description="Un tipo de día; sin él, los tres")] = None,
                  sesion: Session = Depends(obtener_sesion)):
    version, umbrales = _umbrales(sesion)
    try:
        return F.vigente(idruta, tipo_dia, umbrales=umbrales, umbrales_version=version)
    except KeyError as exc:
        raise ErrorApi(404, "no_encontrado", f"ruta {idruta} no existe en el catálogo") from exc


@router.put("/flota", response_model=FlotaCicloSalida,
            summary="Registrar una versión nueva de la flota o del tiempo de ciclo de una ruta (admin; versión nueva y "
                    "auditada)",
            description=DESCRIPCION_FLOTA + " El cuerpo trae flota, tiempo_ciclo_min o ambos (null retira el ajuste; "
                        "un campo que no viene no cambia); hora acota el ajuste de ciclo a una hora de salida. Firma "
                        "el usuario autenticado y el motivo es obligatorio. Responde la flota y el ciclo vigentes de "
                        "la ruta con la versión nueva.")
def ajustar_flota_y_ciclo(solicitud: SolicitudFlotaCiclo, sesion: Session = Depends(obtener_sesion),
                          principal: Principal = Depends(autenticar)):
    creado_por = usuario_auditoria(principal, solicitud.creado_por)      # RNF-011: firma el autenticado
    cambios = {c: getattr(solicitud, c) for c in F.PARAMETROS if c in solicitud.model_fields_set}
    _registrar_version(sesion, F.fijar, solicitud.idruta, solicitud.tipo_dia, solicitud.hora, cambios, creado_por,
                       solicitud.motivo, invalido="ajuste_invalido")
    version, umbrales = umbrales_vigentes(sesion)
    return F.vigente(solicitud.idruta, None, umbrales=umbrales, umbrales_version=version)[0]


@router.get("/flota/historial", response_model=list[EventoFlotaCiclo],
            summary="Historial de la flota y del tiempo de ciclo (versión, acción, valor anterior y nuevo, quién y por "
                    "qué)",
            description="Del más reciente al más antiguo, paginado con limite y desplazamiento; el total de eventos "
                        "va en la cabecera X-Total-Count.")
def historial_flota_y_ciclo(response: Response, idruta: IdRuta = None, limite: Limite = 100,
                            desplazamiento: Desplazamiento = 0, sesion: Session = Depends(obtener_sesion)):
    return _pagina_de_eventos(response, F.historial(sesion, idruta), limite, desplazamiento)
