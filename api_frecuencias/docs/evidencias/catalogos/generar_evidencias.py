"""Evidencias de los catálogos operacionales (§3.1 Gestión operacional, §3.2, §8.1, §8.3, RF-014, RF-017, RNF-002).

Uso (desde EntregaFinal/api_frecuencias, con la base local de pruebas y, si se quiere, la réplica arriba):
    .venv\\Scripts\\python docs\\evidencias\\catalogos\\generar_evidencias.py
- La réplica se lee con el rol lector_ia (scripts.replica_comun.url_rol); las claves nunca se imprimen.
- Los resultados propios van a la base de PRUEBAS local (TEST_DATABASE_NAME, por omisión
  ai_frecuencias_pruebas_catalogos), nunca a la del tablero ni a la del reto; nada se escribe en datos/.
Escribe en esta carpeta: catalogos_replica.json, catalogos_archivos.json, fidelidad_y_relaciones.txt,
rendimiento.txt, sin_datos_personales.txt y ajuste_capacidad.txt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
SALIDA = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

CLAVES = {rol: secrets.token_urlsafe(32) for rol in ("operador", "analista", "admin")}
os.environ["API_KEYS"] = json.dumps({hashlib.sha256(c.encode()).hexdigest(): {"usuario": f"evidencia_{r}", "rol": r}
                                     for r, c in CLAVES.items()})
os.environ["AUTH_HABILITADA"] = "true"
os.environ["REANUDAR_EJECUCIONES"] = "false"
os.environ["PLANIFICADOR_HABILITADO"] = "false"


def _url_pruebas() -> str:
    from sqlalchemy.engine import make_url

    from app.config import Ajustes

    url = make_url(os.environ.get("TEST_DATABASE_URL") or Ajustes().database_url)
    if url.host not in {"localhost", "127.0.0.1", "::1", "db"}:
        raise SystemExit("Solo se usa un PostgreSQL local")
    return url.set(database=os.environ.get("TEST_DATABASE_NAME", "ai_frecuencias_pruebas_catalogos")).render_as_string(
        hide_password=False)


os.environ["DATABASE_URL"] = _url_pruebas()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.servicios import catalogos as C  # noqa: E402

RUTAS = ["procesos", "empresas", "rutas", "segmentos?idruta=2&limite=20", "vehiculos?limite=100",
         "vehiculos/tipologias", "viajes?idruta=2&desde=2025-03-03&hasta=2025-03-03&limite=100",
         "despachos?idruta=16&desde=2025-03-03&hasta=2025-03-07&limite=100", "capacidad"]
PLACA = re.compile(r"\b[A-Z]{3}\d{3}\b")


def _cliente(rol="operador") -> TestClient:
    return TestClient(app, headers={"X-API-Key": CLAVES[rol]})


def _muestra(cuerpo):
    if isinstance(cuerpo, dict) and "items" in cuerpo:
        items = cuerpo["items"][:2]
        for it in items:
            if isinstance(it.get("geometria"), dict):
                coords = it["geometria"]["coordinates"]
                it["geometria"] = {"type": it["geometria"]["type"], "coordinates": coords[:2] + [["..."]]}
        return {k: v for k, v in cuerpo.items() if k != "items"} | {"items_muestra": items}
    return cuerpo[:2] if isinstance(cuerpo, list) else cuerpo


def recorrer(modo: str) -> dict:
    os.environ["CATALOGOS_FUENTE"] = modo
    C.limpiar_cache()
    resultado = {"modo": modo, "generado_en": datetime.now(C.ZONA).isoformat(), "catalogos": {}}
    with _cliente() as c:
        for ruta in RUTAS:
            t0 = time.perf_counter()
            r = c.get(f"/api/v1/catalogos/{ruta}")
            frio = (time.perf_counter() - t0) * 1000
            cuerpo = r.json()
            resultado["catalogos"][ruta] = {"estado": r.status_code, "ms_primera": round(frio, 1),
                                            "fuente": cuerpo.get("fuente") if isinstance(cuerpo, dict) else None,
                                            "total": cuerpo.get("total") if isinstance(cuerpo, dict) else len(cuerpo),
                                            "muestra": _muestra(cuerpo)}
    return resultado


def rendimiento(modo: str, n: int = 30) -> list[str]:
    os.environ["CATALOGOS_FUENTE"] = modo
    lineas = [f"Fuente {modo}: {n} peticiones por ruta, caché caliente (tras la primera), TestClient en proceso"]
    with _cliente() as c:
        for ruta in RUTAS:
            c.get(f"/api/v1/catalogos/{ruta}")
            tiempos = []
            for _ in range(n):
                t0 = time.perf_counter()
                assert c.get(f"/api/v1/catalogos/{ruta}").status_code == 200
                tiempos.append((time.perf_counter() - t0) * 1000)
            tiempos.sort()
            p95 = tiempos[int(0.95 * (n - 1))]
            lineas.append(f"  {ruta:<70} p50 {statistics.median(tiempos):7.1f} ms   p95 {p95:7.1f} ms   "
                          f"{'OK' if p95 < 2000 else 'SUPERA 2 s'}")
    return lineas


def fidelidad_y_relaciones() -> list[str]:
    from scripts.replica_comun import url_rol

    url = url_rol("lector_ia")
    lineas = []
    if not url:
        return ["Réplica sin configurar: no se comparó."]
    f = C.FuenteReplica(url)
    s = f.consultar("SELECT current_user AS usuario, current_setting('transaction_read_only') AS solo_lectura, "
                    "current_setting('TimeZone') AS zona, current_setting('statement_timeout') AS timeout")
    lineas.append(f"Sesión de lectura en la réplica: {s.to_dict('records')[0]}")
    lineas.append("Cada consulta: validar_solo_select -> SET TRANSACTION READ ONLY -> SET LOCAL statement_timeout -> "
                  "SELECT -> ROLLBACK (app.servicios.fuentes.FuentePostgresSoloLectura.consultar)")
    lineas.append("")
    lineas.append("Fidelidad réplica frente a exportaciones Parquet (mismas llaves, RF-014):")
    for catalogo, filtros in (("viajes", {"idruta": 2, "desde": date(2025, 3, 3), "hasta": date(2025, 3, 3)}),
                              ("viajes", {"idruta": 16, "desde": date(2024, 1, 1), "hasta": date(2024, 12, 31)}),
                              ("despachos", {"idruta": 21, "desde": date(2025, 1, 1), "hasta": date(2025, 6, 30)}),
                              ("viajes", {}), ("despachos", {})):
        os.environ["CATALOGOS_FUENTE"] = "archivos"
        _, n_arch, _ = C.programacion(catalogo, limite=1, **filtros)
        _, n_rep, _ = C.programacion(catalogo, limite=1, fuente=f, **filtros)
        lineas.append(f"  {catalogo:<10} {json.dumps({k: str(v) for k, v in filtros.items()}):<70} réplica {n_rep:>8} "
                      f"archivos {n_arch:>8}  {'IGUAL' if n_rep == n_arch else 'DISTINTO'}")
    for nombre, funcion in (("procesos", C.procesos), ("rutas", C.rutas), ("vehiculos", C.vehiculos)):
        os.environ["CATALOGOS_FUENTE"] = "archivos"
        a, _ = funcion()
        r, _ = funcion(f)
        igual = "IGUAL" if len(r) == len(a) else "DISTINTO"
        lineas.append(f"  {nombre:<10} réplica {len(r):>8} archivos {len(a):>8}  {igual}")
    segs_r, _ = C.segmentos(f, geometria="ninguna")
    lineas.append(f"  segmentos  réplica {len(segs_r):>8}")
    lineas.append("")
    lineas.append("Relaciones (contexto operativo consistente, §3.1):")
    rel = f.consultar(
        "SELECT (SELECT count(*) FROM progvehiculos) AS viajes, "
        "(SELECT count(*) FROM progvehiculos p WHERE NOT EXISTS (SELECT 1 FROM rutas r WHERE r.idruta = p.idruta)) "
        "AS viajes_sin_ruta, "
        "(SELECT count(*) FROM progvehiculos p WHERE NOT EXISTS (SELECT 1 FROM vehiculos v "
        "WHERE v.idvehiculo = p.idvehiculo)) AS viajes_sin_vehiculo, "
        "(SELECT count(*) FROM rutas_segmentos s WHERE NOT EXISTS (SELECT 1 FROM rutas r WHERE r.idruta = s.idruta)) "
        "AS segmentos_sin_ruta, "
        "(SELECT count(*) FROM rutas_segmentos s WHERE NOT EXISTS (SELECT 1 FROM rutas_segmentos_config c "
        "WHERE c.id = s.id_config)) AS segmentos_sin_config").to_dict("records")[0]
    lineas += [f"  {k}: {v}" for k, v in rel.items()]
    longitudes = f.consultar(
        "SELECT s.idruta, s.id_config, count(*) AS segmentos, round(sum(s.longitud_m)::numeric, 1) AS suma_longitud_m, "
        "round(ST_Length(ST_LineMerge(ST_Collect(s.geom_segmento ORDER BY s.nro_segmento))::geography)::numeric, 1) "
        "AS longitud_geometria_m FROM rutas_segmentos s WHERE s.activo GROUP BY s.idruta, s.id_config "
        "ORDER BY s.idruta, s.id_config")
    lineas.append("  Longitud declarada (suma de longitud_m) frente a la geometría (geography), por config activa:")
    for r in longitudes.to_dict("records"):
        lineas.append(f"    ruta {r['idruta']:>3} config {r['id_config']:>3}: {r['segmentos']:>4} segmentos, "
                      f"{r['suma_longitud_m']} m declarados, {r['longitud_geometria_m']} m de geometría")
    return lineas


def sin_datos_personales() -> list[str]:
    lineas = ["Columnas que nunca salen: " + ", ".join(sorted(C.COLUMNAS_PROHIBIDAS)), ""]
    for modo in ("replica", "archivos"):
        os.environ["CATALOGOS_FUENTE"] = modo
        C.limpiar_cache()
        with _cliente() as c:
            for ruta in ("vehiculos?limite=500", "viajes?limite=500", "despachos?limite=500", "procesos", "empresas"):
                cuerpo = c.get(f"/api/v1/catalogos/{ruta}").json()
                columnas = set().union(*(set(i) for i in cuerpo["items"])) if cuerpo.get("items") else set()
                texto = json.dumps(cuerpo["items"], ensure_ascii=False)
                lineas.append(f"  {modo:<9} {ruta:<24} filas {len(cuerpo['items']):>4}  columnas prohibidas: "
                              f"{sorted(columnas & C.COLUMNAS_PROHIBIDAS) or 'ninguna'}  textos con forma de placa: "
                              f"{len(PLACA.findall(texto))}")
            for formato in ("csv",):
                r = c.get("/api/v1/catalogos/vehiculos/export", params={"formato": formato})
                cabecera = r.content.decode("utf-8-sig").splitlines()[0]
                lineas.append(f"  {modo:<9} vehiculos/export CSV cabecera: {cabecera}")
    return lineas


def ajuste_capacidad() -> list[str]:
    os.environ["CATALOGOS_FUENTE"] = "archivos"
    lineas = []
    with _cliente("admin") as admin, _cliente("operador") as operador, _cliente("analista") as analista:
        antes = admin.get("/api/v1/thresholds").json()
        lineas.append(f"Conjunto gobernado antes: versión {antes['version']}")
        cuerpo = {"idruta": 21, "tipologia": "TODAS", "capacidad": 46,
                  "motivo": "Evidencia: buses de 46 puestos en CL 72", "creado_por": "intento_de_suplantar"}
        for nombre, c in (("operador", operador), ("analista", analista)):
            r = c.put("/api/v1/catalogos/capacidad", json=cuerpo)
            lineas.append(f"PUT /catalogos/capacidad como {nombre}: {r.status_code} {r.json()['error']['codigo']}")
        r = admin.put("/api/v1/catalogos/capacidad", json=cuerpo)
        lineas.append(f"PUT como admin: {r.status_code} {json.dumps(r.json(), ensure_ascii=False)}")
        r = admin.put("/api/v1/catalogos/capacidad", json={"idruta": 21, "tipologia": "BUSETA", "capacidad": 30,
                                                           "motivo": "Evidencia: busetas de 30 puestos"})
        lineas.append(f"PUT tipología BUSETA: {r.status_code} por_tipologia={r.json()['por_tipologia']}")
        from app.db import sesion_contexto
        from app.servicios import optimizacion

        with sesion_contexto() as s:
            cv = C.capacidad_vigente("CL 72", sesion=s)
            cvb = C.capacidad_vigente("CL 72", "BUSETA", sesion=s)
        lineas.append(f"Contrato del optimizador catalogos.capacidad_vigente('CL 72') -> {cv}")
        lineas.append(f"catalogos.capacidad_vigente('CL 72', 'BUSETA') -> capacidad {cvb['capacidad']}")
        for cap in (cv["capacidad_catalogo"], cv["capacidad"], cvb["capacidad"]):
            rec = optimizacion.recomendar("CL 72", 7, demanda_hora=900, capacidad=cap)
            lineas.append(f"  recomendar(CL 72, 7 h, 900 pax/h, capacidad={cap}): buses_hora={rec['buses_hora']} "
                          f"headway={rec['headway_min']} min viable={rec['viable']}")
        for tip in ("BUSETA", "TODAS"):
            admin.put("/api/v1/catalogos/capacidad", json={"idruta": 21, "tipologia": tip, "capacidad": None,
                                                           "motivo": "Evidencia: se retira el ajuste"})
        historial = admin.get("/api/v1/catalogos/capacidad/historial", params={"idruta": 21}).json()
        lineas.append("Historial (más reciente primero):")
        lineas += [f"  v{e['version']} {e['tipologia']:<7} {e['accion']:<9} {e['capacidad_anterior']} -> "
                   f"{e['capacidad_nueva']} por {e['creado_por']} el {e['creado_en']}: {e['motivo']}"
                   for e in historial[:4]]
        despues = admin.get("/api/v1/thresholds").json()
        lineas.append(f"Conjunto gobernado después: versión {despues['version']}; los umbrales de §5.1 no cambiaron: "
                      f"{ {k: v for k, v in despues['valores'].items()} == antes['valores'] }")
    return lineas


def main() -> None:
    from app.servicios.fuentes import validar_solo_select  # noqa: F401 - la guarda que se reutiliza
    from scripts.replica_comun import url_rol

    url = url_rol("lector_ia")
    if url:
        os.environ["CATALOGOS_DATABASE_URL"] = url
        (SALIDA / "catalogos_replica.json").write_text(json.dumps(recorrer("replica"), ensure_ascii=False, indent=1,
                                                                  default=str), encoding="utf-8")
    (SALIDA / "catalogos_archivos.json").write_text(json.dumps(recorrer("archivos"), ensure_ascii=False, indent=1,
                                                               default=str), encoding="utf-8")
    (SALIDA / "fidelidad_y_relaciones.txt").write_text("\n".join(fidelidad_y_relaciones()) + "\n", encoding="utf-8")
    perf = (rendimiento("replica") if url else []) + [""] + rendimiento("archivos")
    (SALIDA / "rendimiento.txt").write_text("RNF-002 (p95 < 2 s) en /api/v1/catalogos\n" + "\n".join(perf) + "\n",
                                            encoding="utf-8")
    (SALIDA / "sin_datos_personales.txt").write_text("\n".join(sin_datos_personales()) + "\n", encoding="utf-8")
    (SALIDA / "ajuste_capacidad.txt").write_text("\n".join(ajuste_capacidad()) + "\n", encoding="utf-8")
    print("Evidencias escritas en", SALIDA.relative_to(RAIZ))


if __name__ == "__main__":
    main()
