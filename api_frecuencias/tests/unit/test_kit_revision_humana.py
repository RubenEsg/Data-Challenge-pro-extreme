"""Kit de revisión doble HUMANA de alertas (§18 «Etiquetas incorrectas → métricas engañosas», fila 18-R2).

conciliar_humanos.py con archivos de etiquetas sintéticos escritos en un directorio temporal (kappa perfecta y un caso
calculado a mano, alertas faltantes, decisiones de conciliación y archivos de salida) y generar_kit.py / revisar.html
(las 96 alertas, sin las etiquetas de la revisión automatizada y sin recursos externos). Nada se escribe en el
repositorio.
"""
from __future__ import annotations

import html
import importlib.util
import json
import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2]
REVISION = API / "docs" / "evidencias" / "alertas" / "revision_doble"
KIT = REVISION / "kit_humano"
DASH = API.parent / "dash_app"
V, F, IND = "verdadera", "falsa", "indeterminada"


def _modulo(nombre: str):
    spec = importlib.util.spec_from_file_location(f"kit_humano_{nombre}", KIT / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


conciliar_humanos = _modulo("conciliar_humanos")
generar_kit = _modulo("generar_kit")
MUESTRA = json.loads((REVISION / "muestra.json").read_text(encoding="utf-8"))["muestra"]
IDS = [x["id"] for x in MUESTRA]


def _variadas() -> dict[str, str]:
    """Las tres categorías repartidas en la muestra (sin ellas la kappa no está definida)."""
    return {i: (V, V, F, IND)[k % 4] for k, i in enumerate(IDS)}


def _archivo(carpeta: Path, revisor: str, etiquetas: dict[str, str], omitir: tuple[str, ...] = ()) -> Path:
    """Archivo con el formato que descarga revisar.html (el de etiquetas_A.json + revisor, fecha y origen)."""
    filas = [{"id": i, "etiqueta": etiquetas[i], "confianza": "media", "razon": f"{revisor} sobre {i}",
              "revisor": revisor, "fecha": f"2026-11-10T19:{k % 60:02d}:00-05:00", "origen": "humano"}
             for k, i in enumerate(IDS) if i not in omitir]
    ruta = carpeta / f"etiquetas_humano_{revisor.split()[0].lower()}.json"
    ruta.write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def _correr(tmp_path: Path, *args: str) -> tuple[int, dict | None, str]:
    salida = tmp_path / "salida"
    codigo = conciliar_humanos.main([*args, "--salida", str(salida), "--reps", "200"])
    ruta = salida / "conciliacion_humana.json"
    datos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
    resumen = (salida / "resumen_humano.md").read_text(encoding="utf-8") if datos else ""
    return codigo, datos, resumen


# --- Kappa ---------------------------------------------------------------------------------------------------------
def test_kappa_caso_pequeno_calculado_a_mano():
    # acuerdo observado 3/4; marginales V 2-1 y F 2-3 → acuerdo por azar (2·1 + 2·3)/16 = 1/2 → kappa = 0,5
    r = conciliar_humanos.CONC.kappa_cohen([V, V, F, F], [V, F, F, F])
    assert r["acuerdo_bruto"] == 0.75 and r["acuerdo_esperado_azar"] == 0.5 and r["kappa"] == 0.5


def test_acuerdo_perfecto_da_kappa_1(tmp_path):
    etiquetas = _variadas()
    a = _archivo(tmp_path, "Ana Prueba", etiquetas)
    b = _archivo(tmp_path, "Beto Prueba", etiquetas)
    codigo, s, resumen = _correr(tmp_path, str(a), str(b))
    assert codigo == 0
    g = s["acuerdo_antes_de_conciliar"]["global"]
    assert g["kappa"] == 1.0 and g["acuerdo_bruto"] == 1.0 and g["coinciden"] == 96
    assert g["kappa_ic95_bootstrap"] == [1.0, 1.0]
    assert s["desacuerdos"] == [] and s["estado"] == "completa"
    assert "no hubo desacuerdos" in resumen


def test_kappa_de_un_caso_conocido_calculado_a_mano(tmp_path):
    # 96 alertas: 60 V/V, 20 F/F, 4 I/I, 6 V/F, 4 F/V y 2 V/I. Acuerdo observado 84/96 = 0,875.
    # Marginales: revisor 1 V 68, F 24, I 4; revisor 2 V 64, F 26, I 6.
    # Acuerdo por azar = (68·64 + 24·26 + 4·6) / 96² = 5000 / 9216.
    # kappa = (8064 − 5000) / (9216 − 5000) = 3064 / 4216 = 383 / 527 ≈ 0,7268
    pares = [(V, V)] * 60 + [(F, F)] * 20 + [(IND, IND)] * 4 + [(V, F)] * 6 + [(F, V)] * 4 + [(V, IND)] * 2
    a = _archivo(tmp_path, "Ana Prueba", {i: p[0] for i, p in zip(IDS, pares, strict=True)})
    b = _archivo(tmp_path, "Beto Prueba", {i: p[1] for i, p in zip(IDS, pares, strict=True)})
    codigo, s, resumen = _correr(tmp_path, str(a), str(b))
    assert codigo == 0
    g = s["acuerdo_antes_de_conciliar"]["global"]
    assert g["coinciden"] == 84 and g["acuerdo_bruto"] == 0.875
    assert g["acuerdo_esperado_azar"] == round(5000 / 9216, 4)
    assert g["kappa"] == round(383 / 527, 4) == 0.7268
    assert g["matriz_filas_columnas"][V] == {V: 60, F: 6, IND: 2}
    assert g["matriz_filas_columnas"][F] == {V: 4, F: 20, IND: 0}
    lo, hi = g["kappa_ic95_bootstrap"]
    assert lo < 0.7268 < hi
    assert len(s["desacuerdos"]) == 12 and s["estado"] == "pendiente"
    assert "**0,727**" in resumen


# --- Validación ----------------------------------------------------------------------------------------------------
def test_detecta_alertas_faltantes(tmp_path, capsys):
    etiquetas = _variadas()
    a = _archivo(tmp_path, "Ana Prueba", etiquetas)
    b = _archivo(tmp_path, "Beto Prueba", etiquetas, omitir=("M005", "M017"))
    codigo, s, _ = _correr(tmp_path, str(a), str(b))
    assert codigo == 2 and s is None
    error = capsys.readouterr().err
    assert "faltan 2 de 96 alertas: M005, M017" in error and b.name in error


def test_rechaza_las_etiquetas_automatizadas_y_el_mismo_revisor(tmp_path, capsys):
    codigo, _, _ = _correr(tmp_path, str(REVISION / "etiquetas_A.json"), str(REVISION / "etiquetas_B.json"))
    assert codigo == 2 and "etiquetas humanas" in capsys.readouterr().err
    a = _archivo(tmp_path, "Ana Prueba", _variadas())
    otra = tmp_path / "copia.json"
    otra.write_text(a.read_text(encoding="utf-8"), encoding="utf-8")
    codigo, _, _ = _correr(tmp_path, str(a), str(otra))
    assert codigo == 2 and "mismo revisor" in capsys.readouterr().err


# --- Conciliación --------------------------------------------------------------------------------------------------
def test_aplica_decisiones_y_escribe_los_archivos(tmp_path):
    etiquetas = _variadas()
    otras = dict(etiquetas)
    distintas = {IDS[0]: F, IDS[1]: IND, IDS[2]: V}            # IDS[0..2] eran V, V y F
    otras.update(distintas)
    a = _archivo(tmp_path, "Ana Prueba", etiquetas)
    b = _archivo(tmp_path, "Beto Prueba", otras)

    # 1) sin decisiones: conciliación pendiente, plantilla para la reunión y nada de la revisión automatizada
    codigo, s, resumen = _correr(tmp_path, str(a), str(b))
    assert codigo == 0 and s["estado"] == "pendiente"
    assert [d["id"] for d in s["desacuerdos"]] == IDS[:3]
    assert s["humano_vs_automatizado"] is None and s["precision_por_codigo"] is None
    assert "Conciliación pendiente" in resumen and "## 5." not in resumen
    plantilla = json.loads((tmp_path / "salida" / "decisiones_plantilla.json").read_text(encoding="utf-8"))
    assert list(plantilla["decisiones"]) == IDS[:3]

    # 2) con las decisiones de la reunión: etiqueta final, precisión y comparación con la automatizada
    decisiones = {"conciliacion": {"fecha": "2026-11-12", "participantes": "Ana, Beto y Caro"},
                  "decisiones": {IDS[0]: {"etiqueta": "falsa", "criterio": "2.2", "motivo": "calendario"},
                                 IDS[1]: {"etiqueta": "indeterminada", "motivo": "la tarjeta no decide"},
                                 IDS[2]: {"etiqueta": "verdadera", "motivo": "ocurrió"}}}
    ruta = tmp_path / "decisiones_conciliacion.json"
    ruta.write_text(json.dumps(decisiones, ensure_ascii=False), encoding="utf-8")
    codigo, s, resumen = _correr(tmp_path, str(a), str(b), "--decisiones", str(ruta))
    assert codigo == 0 and s["estado"] == "completa"
    finales = {f["id"]: f for f in s["etiquetas_finales"]}
    assert [finales[i]["etiqueta_final"] for i in IDS[:3]] == [F, IND, V]
    assert {finales[i]["origen"] for i in IDS[:3]} == {"conciliación"}
    assert all(finales[i]["origen"] == "acuerdo" and finales[i]["etiqueta_final"] == etiquetas[i] for i in IDS[3:])
    pc = s["precision_por_codigo"]
    assert sum(r["n"] for r in pc.values()) == 96
    for r in pc.values():
        decididas = r["verdaderas"] + r["falsas"]
        assert r["precision"] == (round(r["verdaderas"] / decididas, 4) if decididas else None)
        assert r["precision_ic95_wilson"] == conciliar_humanos.CONC.wilson(r["verdaderas"], decididas)
    h = s["humano_vs_automatizado"]["global"]
    assert h["n"] == 96 and -1 <= h["kappa"] <= 1
    assert "Conciliación completa" in resumen and "## 5. Etiqueta humana conciliada frente a la automatizada" in resumen


def test_rechaza_decidir_una_alerta_en_la_que_coinciden(tmp_path, capsys):
    etiquetas = _variadas()
    otras = {**etiquetas, IDS[0]: F}
    a = _archivo(tmp_path, "Ana Prueba", etiquetas)
    b = _archivo(tmp_path, "Beto Prueba", otras)
    ruta = tmp_path / "decisiones.json"
    ruta.write_text(json.dumps({"decisiones": {IDS[5]: {"etiqueta": "falsa", "motivo": "x"}}}), encoding="utf-8")
    codigo, _, _ = _correr(tmp_path, str(a), str(b), "--decisiones", str(ruta))
    assert codigo == 2 and "coinciden" in capsys.readouterr().err


def test_humanos_iguales_a_la_automatizada_dan_kappa_1_frente_a_ella(tmp_path):
    auto = conciliar_humanos.automatizadas(IDS)
    a = _archivo(tmp_path, "Ana Prueba", auto)
    b = _archivo(tmp_path, "Beto Prueba", auto)
    codigo, s, _ = _correr(tmp_path, str(a), str(b))
    assert codigo == 0
    h = s["humano_vs_automatizado"]
    assert h["global"]["kappa"] == 1.0 and h["diferencias"] == []
    assert h["por_revisor"]["revisor_1"]["kappa"] == 1.0


# --- revisar.html --------------------------------------------------------------------------------------------------
def _textos_automatizados() -> list[str]:
    a = json.loads((REVISION / "etiquetas_A.json").read_text(encoding="utf-8"))
    b = json.loads((REVISION / "etiquetas_B.json").read_text(encoding="utf-8"))
    decisiones = conciliar_humanos.CONC.DECISIONES.values()
    return [x["razon"] for x in a] + [x["razon"] for x in b] + [d["motivo"] for d in decisiones]


def _comprobar_pagina(pagina: str) -> None:
    assert re.findall(r'<article class="tarjeta tarjeta-alerta" data-id="(M\d{3})"', pagina) == IDS
    datos = json.loads(re.search(r'<script type="application/json" id="datos-kit">(.*?)</script>', pagina, re.S)[1])
    assert [x["id"] for x in datos["alertas"]] == IDS and datos["kit"] == generar_kit.id_kit(MUESTRA)
    assert not any("etiqueta" in x for x in datos["alertas"])
    # Ciega: ninguna justificación de los revisores automatizados ni del conciliador, en ninguna forma de escape
    for texto in _textos_automatizados():
        formas = (texto, html.escape(texto, quote=False), json.dumps(texto, ensure_ascii=False)[1:-1],
                  generar_kit.json_en_script(texto)[1:-1])
        for forma in formas:
            assert forma not in pagina, texto[:60]
    # Sin recursos externos: nada que se cargue por http(s) ni etiquetas que traigan archivos
    assert not re.search(r"""\b(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", pagina, re.I)
    assert not re.search(r"""url\(\s*["']?\s*(?:https?:)?//""", pagina, re.I)
    assert not re.search(r"<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)\s*=", pagina, re.I)
    assert "@import" not in pagina
    # Colores solo de los tokens del tablero: fuera de :root no hay hexadecimales ni rgb()
    estilos = re.search(r"<style>(.*?)</style>", pagina, re.S)[1]
    fuera_de_root = re.sub(r"@font-face\s*\{[^}]*\}|:root\s*\{[^}]*\}", "", estilos)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", fuera_de_root)


def test_revisar_html_versionado_trae_las_96_alertas_sin_etiquetas_ni_recursos_externos():
    _comprobar_pagina((KIT / "revisar.html").read_text(encoding="utf-8"))


@pytest.mark.skipif(not (DASH / "tokens.py").is_file(),
                    reason="dash_app/ no está en esta copia (la CI solo descarga api_frecuencias/)")
def test_generar_kit_produce_la_pagina_ciega_y_reproducible(tmp_path, monkeypatch):
    leidos = []
    original = Path.read_text

    def registrar(self, *args, **kwargs):
        leidos.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", registrar)
    assert generar_kit.main(["--salida", str(tmp_path / "uno.html")]) == 0
    assert generar_kit.main(["--salida", str(tmp_path / "dos.html")]) == 0
    monkeypatch.undo()
    prohibidos = {"etiquetas_A.json", "etiquetas_B.json", "conciliacion.json", "resumen.md"}
    assert not prohibidos & set(leidos)
    assert "muestra.json" in leidos and "protocolo.md" in leidos and "M001.md" in leidos
    pagina = (tmp_path / "uno.html").read_text(encoding="utf-8")
    _comprobar_pagina(pagina)
    assert (tmp_path / "uno.html").read_bytes() == (tmp_path / "dos.html").read_bytes()


# --- Quién revisa --------------------------------------------------------------------------------------------------
def test_la_revision_la_hacen_dos_personas_del_area_operativa_de_sobusa(tmp_path):
    """INSTRUCCIONES.md: revisan dos personas del área operativa de Sobusa, a ciegas y por separado; no el equipo del
    proyecto. El AVISO lo dice sin afirmar que la revisión ya esté hecha y llega a los dos archivos de salida."""
    aviso = conciliar_humanos.AVISO
    etiquetas = _variadas()
    a = _archivo(tmp_path, "Ana Prueba", etiquetas)
    b = _archivo(tmp_path, "Beto Prueba", etiquetas)
    codigo, s, resumen = _correr(tmp_path, str(a), str(b))
    assert codigo == 0 and s["estado"] == "completa" and "## 5." in resumen
    assert s["aviso"] == aviso and aviso in resumen
    assert not re.search(r"\b(?:etiquetaron|revisaron|hicieron|conciliaron)\b", aviso)
    textos = {
        "AVISO": aviso,
        "docstring de conciliar_humanos.py": conciliar_humanos.__doc__,
        "plantilla/pagina.html": (KIT / "plantilla" / "pagina.html").read_text(encoding="utf-8"),
        "revisar.html": (KIT / "revisar.html").read_text(encoding="utf-8"),
        "resumen_humano.md": resumen,
    }
    for nombre, texto in textos.items():
        assert "área operativa de Sobusa" in texto, nombre
        assert not re.search(r"\bdel equipo\b", texto), nombre
        assert "No es la validación" not in texto, nombre
