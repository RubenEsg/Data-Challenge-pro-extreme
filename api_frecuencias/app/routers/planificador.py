"""GET /api/v1/scheduler: planificador interno (próximos disparos y últimas franjas) y estado de la cola."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.db import sesion_contexto
from app.servicios import cola, planificador

router = APIRouter(prefix="/scheduler", tags=["planificador"])


@router.get("", summary="Planificador interno: próximas ejecuciones, últimas franjas encoladas y estado de la cola")
def estado() -> dict[str, Any]:
    cuerpo = planificador.estado()
    with sesion_contexto() as s:
        conteo = dict(s.execute(text("SELECT estado, count(*) FROM ai_frecuencias.execution_log "
                                     "GROUP BY estado")).all())
    cuerpo["cola"] = {"por_estado": conteo, **cola.estado_trabajadores()}
    return cuerpo
