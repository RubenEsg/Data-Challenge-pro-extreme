"""Mide el ciclo diario (POST /api/v1/frequency/executions) con cortes fijos en una base local desechable.

Reproduce la secuencia de la demostración de §14.2 sin la pila de contenedores:
  1) carga inicial: todo el histórico hasta --hasta, sin marca de agua;
  2) día nuevo: el día siguiente (solo lo posterior a la marca de agua);
  3) repetición del mismo corte (0 filas nuevas).
Para cada ejecución guarda la duración total, la duración de cada etapa del ciclo y las cifras de la ejecución.
Además guarda el resultado completo (predicciones, recomendaciones, alertas e historial) sin los campos que cambian
de una corrida a otra (identificadores, marcas de tiempo de creación, latencias), con su SHA-256: dos corridas con
el mismo código y los mismos datos deben dar el mismo SHA-256.

Uso:
  python scripts/medir_ciclo.py --etiqueta despues --salida docs/evidencias/rendimiento/ciclo_despues.json
         [--perfil docs/evidencias/rendimiento/perfil_despues.txt] [--raiz <carpeta de la API>] [--hasta 2025-08-30]
  python scripts/medir_ciclo.py --comparar antes.json despues.json

Seguridad e higiene:
- solo acepta un servidor PostgreSQL local (localhost o 127.0.0.1); la base de medición (TEST_DATABASE_NAME, por
  omisión ai_frecuencias_pruebas_ciclo_4) se borra y se crea de nuevo en cada corrida;
- no escribe en datos/: el ciclo trabaja sobre una copia temporal de la carpeta (DATA_DIR y MODELOS_DIR);
- la fuente es la serie empaquetada (FUENTE=parquet), sin red y sin notificaciones reales.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import os
import pstats
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

RAIZ_SCRIPT = Path(__file__).resolve().parents[1]
HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1"}
PREFIJO_BASES = "ai_frecuencias_pruebas"
BASE_POR_OMISION = "ai_frecuencias_pruebas_ciclo_4"
RUTA_EJECUCIONES = "/api/v1/frequency/executions"
# campos que cambian de una corrida a otra sin que cambie el resultado: marcas de tiempo del reloj, latencias,
# tiempo del solver e identificadores seriales de la base
VOLATILES = {"generated_at", "latencia_ms", "duracion_s", "tiempo_s", "tiempo_solver_s", "segundos",
             "ultima_deteccion", "id"}
PATRON_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PATRON_LOTE = re.compile(r"^[0-9a-f]{8}:")


def _url_local() -> str:
    """DATABASE_URL del entorno o del .env de la API, con la base de medición; falla si el servidor no es local."""
    from sqlalchemy.engine import make_url

    valor = os.environ.get("DATABASE_URL", "")
    archivo = RAIZ_SCRIPT / ".env"
    if not valor and archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.strip().startswith("DATABASE_URL="):
                valor = linea.split("=", 1)[1].strip().strip('"').strip("'")
    if not valor:
        raise SystemExit("Falta DATABASE_URL (entorno o .env de la API).")
    url = make_url(valor)
    if url.host not in HOSTS_LOCALES:
        raise SystemExit("medir_ciclo.py solo trabaja contra un servidor PostgreSQL local.")
    nombre = os.environ.get("TEST_DATABASE_NAME", BASE_POR_OMISION)
    if not nombre.startswith(PREFIJO_BASES):
        raise SystemExit(f"La base de medición se borra en cada corrida: su nombre debe empezar por {PREFIJO_BASES}.")
    return url.set(database=nombre).render_as_string(hide_password=False)


def _base_nueva(url: str) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{u.database}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{u.database}"'))
    admin.dispose()


def _migrar(raiz: Path, url: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def _preparar_entorno(raiz: Path, datos_origen: Path, url: str) -> Path:
    temporal = Path(tempfile.mkdtemp(prefix="medir_ciclo_"))
    shutil.copytree(datos_origen, temporal / "datos")
    repo = RAIZ_SCRIPT.parents[1]
    os.environ.update({
        "DATABASE_URL": url, "DATA_DIR": str(temporal / "datos"), "MODELOS_DIR": str(temporal / "datos" / "modelos"),
        "FUENTE": "parquet", "FUENTE_DATABASE_URL": "", "REANUDAR_EJECUCIONES": "false", "TRABAJADORES": "0",
        "AUTH_HABILITADA": "false", "NOTIFICACIONES": "ninguna", "PLANIFICADOR_HABILITADO": "false",
        "OTEL_EXPORTADOR": "ninguno", "ENTORNO": "pruebas", "CATALOGOS_FUENTE": "archivos",
        "CATALOGOS_DATABASE_URL": "",
        "CATALOGOS_DATOS_DIR": os.environ.get("CATALOGOS_DATOS_DIR") or str(repo / "datos"),
        "CATALOGOS_FLOTA_CSV": (os.environ.get("CATALOGOS_FLOTA_CSV")
                                or str(repo / "insumos_sobusa" / "flota_sobusa.csv")),
    })
    sys.path.insert(0, str(raiz))
    os.chdir(raiz)
    return temporal


def _normalizar(valor):
    """Valor comparable entre corridas: sin identificadores ni marcas de tiempo de creación (claves *_en)."""
    if isinstance(valor, dict):
        return {str(k): _normalizar(v) for k, v in sorted(valor.items(), key=lambda kv: str(kv[0]))
                if str(k) not in VOLATILES and not str(k).endswith("_en")}
    if isinstance(valor, (list, tuple)):
        return [_normalizar(v) for v in valor]
    if isinstance(valor, UUID):
        return "<uuid>"
    if isinstance(valor, str) and PATRON_LOTE.match(valor):
        return "<lote>" + valor[8:]
    if isinstance(valor, str):
        return PATRON_UUID.sub("<uuid>", valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, float):
        return round(valor, 9)
    return valor


def _filas(sesion, modelo, orden: tuple[str, ...]) -> list[dict]:
    from sqlalchemy import select

    columnas = [c.key for c in modelo.__table__.columns]
    filas = [_normalizar({c: getattr(f, c) for c in columnas}) for f in sesion.scalars(select(modelo)).all()]
    return sorted(filas, key=lambda f: json.dumps([f.get(c) for c in orden], default=str)
                  + json.dumps(f, sort_keys=True, default=str))


def _resultado_completo() -> dict:
    from app.db import sesion_contexto
    from app.modelos_db import Alerta, HistorialAlerta, Prediccion, Recomendacion

    with sesion_contexto() as s:
        return {
            "predicciones": _filas(s, Prediccion, ("ruta", "instante", "horizonte_min")),
            "recomendaciones": _filas(s, Recomendacion, ("ruta", "fecha", "hora", "demanda_hora")),
            "alertas": _filas(s, Alerta, ("codigo", "ruta", "ventana_inicio")),
            "historial_alertas": _filas(s, HistorialAlerta, ("accion",)),
        }


def _sha(objeto) -> str:
    return hashlib.sha256(json.dumps(objeto, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
                          ).hexdigest()


def _con_etapas():
    """Envuelve ejecucion._avance para medir cuánto dura cada etapa del ciclo."""
    from app.servicios import ejecucion

    marcas: list[tuple[str, float]] = []
    original = ejecucion._avance

    def _avance(execution_id, progreso, etapa, **campos):
        marcas.append((etapa, time.perf_counter()))
        return original(execution_id, progreso, etapa, **campos)

    ejecucion._avance = _avance
    return marcas


def _etapas(marcas: list[tuple[str, float]], fin: float) -> dict[str, float]:
    puntos = marcas + [("fin", fin)]
    return {e: round(puntos[i + 1][1] - t, 3) for i, (e, t) in enumerate(puntos[:-1])}


def _correr(cliente, cortes: list[tuple[str, date]], marcas: list) -> list[dict]:
    corridas = []
    for nombre, hasta in cortes:
        marcas.clear()
        t0 = time.perf_counter()
        r = cliente.post(RUTA_EJECUCIONES, json={"hasta": hasta.isoformat(), "notificar": False})
        r.raise_for_status()
        e = cliente.get(f"{RUTA_EJECUCIONES}/{r.json()['execution_id']}").json()
        fin = time.perf_counter()
        m = e.get("metricas") or {}
        corridas.append({"corrida": nombre, "hasta": hasta.isoformat(), "estado": e.get("estado"),
                         "segundos_peticion": round(fin - t0, 2), "duracion_ciclo_s": m.get("duracion_s"),
                         "etapas_s": _etapas(list(marcas), fin), "filas_leidas": e.get("filas_leidas"),
                         "predicciones": m.get("predicciones"), "recomendaciones": m.get("recomendaciones"),
                         "alertas_nuevas": m.get("alertas_nuevas"), "alertas_repetidas": m.get("alertas_repetidas"),
                         "fallos": len(m.get("fallos") or []), "metricas": _normalizar(m)})
        print(f"{nombre:<14} hasta {hasta}  {e.get('estado')}  {fin - t0:7.1f} s  filas={e.get('filas_leidas')}  "
              f"pred={m.get('predicciones')}  rec={m.get('recomendaciones')}  alertas={m.get('alertas_nuevas')}",
              flush=True)
    return corridas


def _perfil_texto(perfil: cProfile.Profile, raiz: Path) -> str:
    salida = io.StringIO()
    for orden in ("cumulative", "tottime"):
        salida.write(f"===== 25 funciones con más tiempo ({orden}) =====\n")
        st = pstats.Stats(perfil, stream=salida)
        st.strip_dirs().sort_stats(orden).print_stats(25)
    return salida.getvalue().replace(str(raiz), "<api>")


def medir(a: argparse.Namespace) -> None:
    raiz = Path(a.raiz).resolve() if a.raiz else RAIZ_SCRIPT
    url = _url_local()
    temporal = _preparar_entorno(raiz, Path(a.datos).resolve() if a.datos else RAIZ_SCRIPT / "datos", url)
    try:
        _base_nueva(url)
        _migrar(raiz, url)
        from fastapi.testclient import TestClient

        from app.main import app

        marcas = _con_etapas()
        cortes = [("carga_inicial", a.hasta), ("dia_nuevo", a.hasta + timedelta(days=1)),
                  ("repeticion", a.hasta + timedelta(days=1))]
        perfil = cProfile.Profile() if a.perfil else None
        with TestClient(app) as cliente:
            if perfil:
                perfil.enable()
            corridas = _correr(cliente, cortes, marcas)
            if perfil:
                perfil.disable()
        resultado = _resultado_completo()
        informe = {"etiqueta": a.etiqueta, "medido_el": datetime.now().isoformat(timespec="seconds"),
                   "con_perfilador": bool(perfil), "corridas": corridas,
                   "conteos": {k: len(v) for k, v in resultado.items()},
                   "sha256_resultado": {k: _sha(v) for k, v in resultado.items()} | {"total": _sha(resultado)},
                   "resultado": resultado}
        Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
        Path(a.salida).write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        if perfil:
            Path(a.perfil).write_text(_perfil_texto(perfil, raiz), encoding="utf-8")
            perfil.dump_stats(str(Path(a.perfil).with_suffix(".prof")))
        print("sha256 del resultado:", informe["sha256_resultado"]["total"])
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def _diferencias(a, b, ruta: str = "", salida: list | None = None, maximo: int = 40) -> list[str]:
    salida = [] if salida is None else salida
    if len(salida) >= maximo:
        return salida
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            _diferencias(a.get(k), b.get(k), f"{ruta}.{k}", salida, maximo)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _diferencias(x, y, f"{ruta}[{i}]", salida, maximo)
    elif a != b:
        salida.append(f"{ruta}: {str(a)[:120]} != {str(b)[:120]}")
    return salida


def comparar(antes: Path, despues: Path) -> int:
    a = json.loads(antes.read_text(encoding="utf-8"))
    b = json.loads(despues.read_text(encoding="utf-8"))
    print(f"{'corrida':<14}{'antes (s)':>12}{'después (s)':>14}")
    for x, y in zip(a["corridas"], b["corridas"], strict=False):
        print(f"{x['corrida']:<14}{x['segundos_peticion']:>12.1f}{y['segundos_peticion']:>14.1f}")
    iguales = a["sha256_resultado"]["total"] == b["sha256_resultado"]["total"]
    metricas = [_diferencias(x["metricas"], y["metricas"]) for x, y in zip(a["corridas"], b["corridas"], strict=False)]
    print("resultado idéntico (SHA-256):", iguales)
    for parte in a["resultado"]:
        print(f"  {parte}: {a['conteos'][parte]} filas, iguales = "
              f"{a['sha256_resultado'][parte] == b['sha256_resultado'][parte]}")
    if not iguales:
        for d in _diferencias(a["resultado"], b["resultado"]):
            print("   ", d)
    for x, d in zip(a["corridas"], metricas, strict=False):
        print(f"  métricas de {x['corrida']}: {'iguales' if not d else d[:10]}")
    return 0 if iguales and not any(metricas) else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--etiqueta", default="medicion")
    p.add_argument("--salida", help="JSON con tiempos, etapas y resultado normalizado")
    p.add_argument("--perfil", help="texto con las 25 funciones más costosas (cProfile)")
    p.add_argument("--raiz", help="carpeta de la API que se mide (por omisión, la de este script)")
    p.add_argument("--datos", help="carpeta de datos que se copia (por omisión, datos/ de la API)")
    p.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 8, 30))
    p.add_argument("--comparar", nargs=2, metavar=("ANTES", "DESPUES"))
    a = p.parse_args()
    if a.comparar:
        return comparar(Path(a.comparar[0]), Path(a.comparar[1]))
    if not a.salida:
        p.error("--salida es obligatorio para medir")
    medir(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
