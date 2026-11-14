"""/api/v1/retencion: política de retención de datos (§18 «Exposición de datos → retención») y su tarea automática.

GET /retencion (rol operador, como toda lectura) muestra la política vigente tabla por tabla, con los parámetros
gobernados de threshold_config, el corte de hoy de cada grupo y la bitácora de la última corrida (retencion_registro).
POST /retencion/aplicar (rol admin) encola la tarea en la cola de trabajos (tipo «retencion») y responde 202 con el
execution_id; por omisión SIMULA (calcula lo que se borraría sin borrar nada) y solo aplica con «simular»: false. La
corrida programada la encola el planificador (PLAN_RETENCION_CRON). El servicio es app/servicios/retencion.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import Salida
from app.seguridad import Principal, autenticar, usuario_auditoria
from app.servicios import retencion as servicio

router = APIRouter(prefix="/retencion", tags=["retención"])
RUTA_EJECUCIONES = "/api/v1/frequency/executions"


class SolicitudRetencion(BaseModel):
    simular: bool = Field(True, description="true (por omisión): solo calcula lo que se borraría y lo deja en la "
                                            "bitácora con simulado = true; false: aplica la política")
    motivo: str | None = Field(None, max_length=500, description="Constancia de por qué se corre a mano")


class RetencionEnCola(BaseModel):
    execution_id: uuid.UUID
    tipo: str
    estado: str
    nueva: bool = Field(description="false si ya había una corrida en cola o corriendo (no se duplica; trae su "
                                    "propio «simular»)")
    simular: bool | None = Field(None, description="Si esa corrida simula (null: la programada, que decide "
                                                   "retencion_aplicar_programada al correr)")
    creado_en: str | None = Field(None, description="Instante en que se encoló (-05:00)")
    consultar_estado: str = Field(description="Ruta para seguir el progreso y el resumen de la corrida")
    consultar_politica: str = Field(description="Ruta con la política y la bitácora de la última corrida")


class ReglaRetencion(Salida):
    grupo: str = Field(description="foto, resultados, alertas, ejecuciones, derivada o conservada")
    tabla: str
    accion: str = Field(description="separar_y_borrar, separar_y_archivar, borrar_filas o conservar")
    parametro: str | None = Field(None, description="Parámetro de threshold_config con los meses en caliente")
    meses: int | None = Field(None, description="Meses en caliente (0 = no se recorta)")
    corte: datetime | None = Field(None, description="Lo anterior a este instante se borra (-05:00)")
    descripcion: str


class RegistroRetencionSalida(Salida):
    id: int
    execution_id: uuid.UUID | None = None
    simulado: bool
    grupo: str
    objeto: str = Field(description="Tabla o partición")
    accion: str = Field(description="separar_y_borrar, separar_y_archivar, borrar_filas, conservar o pospuesta")
    corte: datetime | None = None
    filas: int
    bytes: int | None = None
    umbrales_version: int | None = None
    detalle: dict[str, Any] = Field(default_factory=dict)
    creado_en: datetime


class PoliticaRetencion(Salida):
    umbrales_version: int = Field(description="Versión de threshold_config de los parámetros")
    ahora: datetime
    parametros: dict[str, int] = Field(description="Parámetros gobernados de la política (PUT /thresholds los cambia)")
    aplicar_programada: bool = Field(description="Si la corrida del planificador aplica (true) o solo simula")
    reglas: list[ReglaRetencion]
    ultima_corrida: list[RegistroRetencionSalida] = Field(description="Bitácora de la corrida más reciente")


def _en_cola(e, nueva: bool) -> dict:
    from app.servicios.respuesta import instante_bogota

    p = e.parametros or {}
    return {"execution_id": e.execution_id, "tipo": e.tipo, "estado": e.estado, "nueva": nueva,
            "simular": p.get("simular"), "creado_en": instante_bogota(e.creado_en),
            "consultar_estado": f"{RUTA_EJECUCIONES}/{e.execution_id}", "consultar_politica": "/api/v1/retencion"}


@router.get("", response_model=PoliticaRetencion,
            summary="Política de retención vigente (§18) y bitácora de la última corrida",
            description="Qué hace la retención con cada tabla del esquema ai_frecuencias: meses en caliente "
                        "(parámetros gobernados de threshold_config; PUT /api/v1/thresholds los cambia), el corte de "
                        "hoy y la acción (separar y borrar las particiones mensuales viejas de feature_snapshot, "
                        "borrar filas o conservar). Trae la bitácora de la corrida más reciente (retencion_registro).")
def politica(sesion: Session = Depends(obtener_sesion)):
    return servicio.describir(sesion)


@router.post("/aplicar", response_model=RetencionEnCola, status_code=202,
             summary="Correr la retención bajo demanda (job en la cola, rol admin)",
             description="Encola un trabajo «retencion» que aplica la política de §18 con los parámetros vigentes y "
                         "responde 202 con el execution_id; el progreso y el resumen se ven en GET "
                         "/api/v1/frequency/executions/{id} y la bitácora en GET /api/v1/retencion. Por omisión SIMULA "
                         "(«simular»: true): calcula las filas y las particiones que se borrarían sin borrar nada. Con "
                         "«simular»: false las borra. Si ya hay una corrida en cola o corriendo, devuelve esa.")
def aplicar(tareas: BackgroundTasks, request: Request, solicitud: SolicitudRetencion | None = None,
            sesion: Session = Depends(obtener_sesion), principal: Principal = Depends(autenticar)):
    from app.servicios import ejecucion

    solicitud = solicitud or SolicitudRetencion()
    parametros = {"simular": solicitud.simular, "motivo": solicitud.motivo, "origen": "api",
                  "solicitado_por": usuario_auditoria(principal)}
    e, nueva = servicio.solicitar(sesion, parametros, getattr(request.state, "correlation_id", None))
    if nueva:
        tareas.add_task(ejecucion.ejecutar, e.execution_id)
    return _en_cola(e, nueva)
