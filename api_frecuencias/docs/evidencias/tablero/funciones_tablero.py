"""Comprobación de las funciones puras nuevas del tablero (sin servidor): orden de prioridad y chip «Escalada» de
Alertas, el filtro de nombres del informe de El modelo y la lectura de lo real por ventana de Pronóstico."""
import importlib
import os
import sys
from pathlib import Path

# Uso (con el Python del tablero): dash_app/.venv/Scripts/python.exe funciones_tablero.py
DASH = Path(__file__).resolve().parents[4] / "dash_app"
os.chdir(DASH)
sys.path.insert(0, str(DASH))
importlib.import_module("app")   # crea la app y registra las páginas (antes de importarlas)
alertas = importlib.import_module("paginas.alertas")
modelo = importlib.import_module("paginas.modelo")
pronostico = importlib.import_module("paginas.pronostico")

bien = 0


def ok(nombre, cond):
    global bien
    print(("OK    " if cond else "FALLA ") + nombre)
    bien += bool(cond)
    return cond


items = [{"alert_id": "a", "severidad": "informativa", "detectada_en": "2025-09-03T06:00:00-05:00"},
         {"alert_id": "b", "severidad": "critica", "detectada_en": "2025-09-01T06:00:00-05:00"},
         {"alert_id": "c", "severidad": "preventiva", "detectada_en": "2025-09-04T06:00:00-05:00"},
         {"alert_id": "d", "severidad": "critica", "detectada_en": "2025-09-02T06:00:00-05:00"}]
ok("prioridad: críticas primero y, dentro del nivel, la más reciente",
   [a["alert_id"] for a in alertas.ordenar_prioridad(items)] == ["d", "b", "c", "a"])
ok("escalada: una entrada «escalar» en la bitácora", alertas.escalada([{"accion": "crear"}, {"accion": "escalar"}]))
ok("escalada: sin «escalar» no hay chip", not alertas.escalada([{"accion": "crear"}, {"accion": "comentar"}]))
ok("escalada: bitácora vacía o con basura", not alertas.escalada(None) and not alertas.escalada(["x", 3]))
ok("D9: «de E11» → «del experimento 11» y «E12» → «el experimento 12»",
   modelo._d9("el mismo modelo de E11 (variante de E12); E12 gana; E1 no") ==
   "el mismo modelo del experimento 11 (variante del experimento 12); el experimento 12 gana; E1 no")
ok("D9: no toca palabras que contienen «de»", modelo._d9("desde E110") == "desde E110")
p = {"ruta": "CRA 54", "variables": {"por_hora": [{"fecha": "2025-09-04", "hora": 6, "fraccion": 1.0}]}}
real = pronostico._reales()[("CRA 54", "2025-09-04", 6)]
ok("pronóstico: lo real de una ventana de una hora = el real de esa hora", pronostico._real_ventana(p) == real)
p2 = {"ruta": "CRA 54", "variables": {"por_hora": [{"fecha": "2025-09-04", "hora": 6, "fraccion": 0.5},
                                                  {"fecha": "2025-09-04", "hora": 7, "fraccion": 0.5}]}}
r7 = pronostico._reales()[("CRA 54", "2025-09-04", 7)]
ok("pronóstico: una ventana que cruza dos horas suma las fracciones",
   abs(pronostico._real_ventana(p2) - (real + r7) / 2) < 1e-9)
fuera = {"ruta": "CRA 54", "variables": {"por_hora": [{"fecha": "2026-01-01", "hora": 6, "fraccion": 1}]}}
ok("pronóstico: fuera de 2025 lo real no se conoce", pronostico._real_ventana(fuera) is None)
print(f"{bien} de 9 bien")
sys.exit(0 if bien == 9 else 1)
