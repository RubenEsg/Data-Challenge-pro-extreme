"""Entrena y registra el modelo de corto plazo que sirve la API (spec v1.5 §2.2, RF-005, §9.1, §9.2, §9.3, RF-018).

Es lo elegido en la validación del experimento E14 (pronostico_corto_plazo/resultados/seleccion.json de la entrega),
reentrenado exactamente como en su prueba reservada: con todo lo anterior al 1 de julio de 2025 (entrenamiento
2023-2024 más validación enero-junio de 2025), las mismas variables, los mismos hiperparámetros y la misma semilla.
Así el modelo de la API es el que se midió una sola vez en julio-diciembre de 2025, y las cifras de esa prueba son
las suyas (scripts/verificar_corto_plazo.py lo comprueba contra las predicciones guardadas de la prueba).

Se entrenan dos niveles por horizonte (30, 60 y 120 minutos) y ruta: «ruta» (la ruta entera) y «segmento» (los
segmentos oficiales de 500 m). El sentido es la suma de sus segmentos, la estructura elegida en la validación, así
que no tiene modelo propio. Cada árbol se guarda en el formato de texto de LightGBM, comprimido, con su SHA-256 en el
manifiesto, que app/servicios/corto_plazo.py verifica antes de usarlo.

Uso (desde api_frecuencias/):
    python scripts/entrenar_corto_plazo.py                       # panel y selección del experimento de la entrega
    python scripts/entrenar_corto_plazo.py --solo-registrar      # rehace manifiesto y registro sin reentrenar
Opciones: --panel CARPETA (panel de 15 minutos; se copia a datos/corto_plazo), --seleccion y --prueba (resultados del
experimento), --model-id.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import corto_plazo as CP  # noqa: E402
from app.servicios import variables_corto_plazo as V  # noqa: E402

EXPERIMENTO = RAIZ.parent / "pronostico_corto_plazo"
NIVELES_CON_MODELO = ("ruta", "segmento")
ENTRENAR = ("entrenamiento", "validacion")


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def copiar_panel(origen: Path, destino: Path) -> dict:
    """Copia los archivos del panel a datos/corto_plazo (si cambiaron) y devuelve el SHA-256 de cada uno."""
    destino.mkdir(parents=True, exist_ok=True)
    version = {}
    for nombre in V.ARCHIVOS_PANEL:
        src, dst = origen / nombre, destino / nombre
        if src.resolve() != dst.resolve() and (not dst.exists() or sha256_archivo(src) != sha256_archivo(dst)):
            shutil.copyfile(src, dst)
        version[nombre] = sha256_archivo(dst)
    return version


def hora_bogota(texto: str | None) -> str | None:
    """«2026-11-17 20:23» (hora local del experimento) en ISO-8601 con la zona de Bogotá, como todo instante (§8.1)."""
    if not texto:
        return texto
    from zoneinfo import ZoneInfo

    return datetime.fromisoformat(texto).replace(tzinfo=ZoneInfo("America/Bogota")).isoformat()


def ajustar(x: np.ndarray, y: np.ndarray, hiper: dict):
    import lightgbm as lgb

    modelo = lgb.LGBMRegressor(**dict(V.HIPER, **hiper), random_state=V.SEMILLA, n_jobs=V.HILOS, verbose=-1,
                               deterministic=True, force_row_wise=True)
    return modelo.fit(x, y)


def resumen_prueba(prueba: dict) -> dict:
    """Las cifras de la prueba reservada (una sola vez, 2025-07-01 a 2025-12-31) por nivel y horizonte."""
    out = {}
    for nivel in V.NIVELES:
        out[nivel] = {}
        for h in V.HORIZONTES:
            b = prueba["niveles"][nivel][str(h)]
            t = b["todas_las_rutas"]
            out[nivel][str(h)] = {
                "wape_modelo": t["modelo"]["wape"], "wape_promedio_dia_hora": t["promedio_dia_hora"]["wape"],
                "wape_ultima_semana": t["ultima_semana"]["wape"], "wape_persistencia": t["persistencia"]["wape"],
                "mae": t["modelo"]["mae"], "rmse": t["modelo"]["rmse"], "smape": t["modelo"]["smape"],
                "sesgo_pct": t["modelo"]["sesgo_pct"], "celdas": t["modelo"]["n"],
                "ic95_diferencia_con_el_promedio_pp": t["ic95"]["modelo_menos_promedio_dia_hora"]["ic95"],
                "cobertura_p10_p90_pct": b["banda_p10_p90"]["todas_las_rutas"]["cobertura_pct"],
                "wape_por_ruta": {r: v["modelo"]["wape"] for r, v in b["por_ruta"].items()}}
    seg = prueba["por_segmento"]["60"]
    out["segmentos_en_que_gana_al_promedio_60"] = [seg["segmentos_en_que_gana_al_promedio"],
                                                   seg["segmentos_con_subidas"]]
    return out


def entrenar(model_id: str, sel: dict, dir_modelo: Path, carpeta_panel: Path) -> dict:
    artefactos = {}
    for idruta in V.RUTAS:
        r = V.cargar_ruta(idruta, carpeta_panel)
        for nivel in NIVELES_CON_MODELO:
            hiper = sel["hiper"][nivel]["valores"]
            for h in V.HORIZONTES:
                t0 = time.time()
                v = V.variables(r, nivel, h, sel["conjunto"][nivel])
                tr = np.zeros(len(v["y"]), bool)
                for per in ENTRENAR:
                    tr |= V.filas(v, per)
                idx = np.flatnonzero(tr)
                modelo = ajustar(v["x"][idx], v["y"][idx], hiper)
                clave = CP.clave_artefacto(nivel, h, idruta)
                texto = modelo.booster_.model_to_string().encode("utf-8")
                archivo = dir_modelo / f"{clave}.txt.gz"
                archivo.write_bytes(gzip.compress(texto, compresslevel=9, mtime=0))
                g = modelo.booster_.feature_importance(importance_type="gain")
                artefactos[clave] = {"archivo": archivo.name, "sha256": sha256_archivo(archivo), "nivel": nivel,
                                     "horizonte_min": h, "idruta": idruta, "ruta": V.RUTAS[idruta],
                                     "filas_entrenamiento": int(len(idx)), "variables": v["nombres"],
                                     "importancia_ganancia": dict(zip(v["nombres"], (g / g.sum()).round(5).tolist(),
                                                                       strict=True))}
                mb = archivo.stat().st_size / 1e6
                print(f"  {clave:22s} filas {len(idx):>9,}  {time.time() - t0:6.1f} s  {mb:5.1f} MB", flush=True)
                del v, modelo
    return artefactos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--panel", type=Path, default=EXPERIMENTO / "panel")
    ap.add_argument("--seleccion", type=Path, default=EXPERIMENTO / "resultados" / "seleccion.json")
    ap.add_argument("--prueba", type=Path, default=EXPERIMENTO / "resultados" / "prueba.json")
    ap.add_argument("--model-id", default=CP.MODEL_ID_E14)
    ap.add_argument("--solo-registrar", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    sel = json.loads(a.seleccion.read_text(encoding="utf-8"))
    prueba = json.loads(a.prueba.read_text(encoding="utf-8"))
    if sel["estructura"] != {"sentido": "suma_de_segmentos", "segmento": "directo"}:
        sys.exit(f"La API implementa la estructura elegida en E14 (sentido = suma de segmentos, segmento directo); "
                 f"la selección trae {sel['estructura']}")
    carpeta_panel = CP.carpeta_datos()
    version_datos = copiar_panel(a.panel, carpeta_panel)
    dir_modelo = CP.carpeta_modelos() / a.model_id
    dir_modelo.mkdir(parents=True, exist_ok=True)
    previo = dir_modelo / CP.ARCHIVO_MANIFIESTO
    if a.solo_registrar:
        artefactos = json.loads(previo.read_text(encoding="utf-8"))["artefactos"]
    else:
        artefactos = entrenar(a.model_id, sel, dir_modelo, carpeta_panel)
    import lightgbm

    man = {
        "model_id": a.model_id, "tipo": CP.TIPO, "feature_version": V.VERSION_VARIABLES,
        "descripcion": "LightGBM Poisson por nivel (ruta y segmento), horizonte y ruta; sentido = suma de segmentos",
        "data_cutoff": V.PERIODOS["validacion"][1],
        "entrenado_con": "2023-01-01 a 2025-06-30 (entrenamiento más validación)",
        "periodos": V.PERIODOS, "semilla": V.SEMILLA, "conjunto": sel["conjunto"], "estructura": sel["estructura"],
        "hiperparametros": {n: sel["hiper"][n] for n in NIVELES_CON_MODELO},
        "banda": {"metodo": "conformal de Mondrian por tramo del pronóstico, puntaje (y - p) / raíz(p + 1), cuantiles "
                            "10 % y 90 % ajustados en la validación (enero-junio de 2025)",
                  "calibracion": sel["banda"]},
        "artefactos": artefactos, "version_datos": version_datos,
        "origen": {"seleccion": {"archivo": "pronostico_corto_plazo/resultados/seleccion.json",
                                 "sha256": sha256_archivo(a.seleccion)},
                   "prueba": {"archivo": "pronostico_corto_plazo/resultados/prueba.json",
                              "sha256": sha256_archivo(a.prueba), "generado": hora_bogota(prueba.get("generado")),
                              "repetida": prueba.get("repetida")},
                   "protocolo": "pronostico_corto_plazo/PROTOCOLO.md (commits 9844dae → fa04afb → 546cffa)"},
        "metricas_prueba": resumen_prueba(prueba), "huella_codigo": CP.huellas_codigo(),
        "versiones": {"python": platform.python_version(), "lightgbm": lightgbm.__version__, "numpy": np.__version__,
                      "pandas": pd.__version__},
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    previo.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    CP.registrar(man, activar=True, motivo="modelo elegido en la validación de E14 y medido una vez en su prueba "
                                           "reservada (julio-diciembre de 2025)")
    origen = {"generado_en": man["generado_en"], "script": "scripts/entrenar_corto_plazo.py",
              "fuente": "pronostico_corto_plazo/panel (experimento E14): eventos de conteo con subidas 2023-2025, "
                        "exportados en solo lectura y asignados al segmento oficial de 500 m con la regla de Extreme",
              "archivos": {k: {"sha256": s} for k, s in version_datos.items()}}
    (carpeta_panel / "origen.json").write_text(json.dumps(origen, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"listo en {(time.time() - t0) / 60:.1f} min: {len(artefactos)} artefactos en {dir_modelo}")


if __name__ == "__main__":
    main()
