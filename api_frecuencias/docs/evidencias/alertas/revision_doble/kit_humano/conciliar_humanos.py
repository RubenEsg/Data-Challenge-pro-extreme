"""Conciliación de la revisión doble HUMANA de alertas (§18 «Etiquetas incorrectas → métricas engañosas», fila 18-R2).

Dos personas del área operativa de Sobusa (INSTRUCCIONES.md) etiquetan por separado y a ciegas las 96 alertas de la
muestra con revisar.html y cada una descarga su archivo (el formato de etiquetas_A.json más revisor, fecha y
origen = "humano"). Este script:

1. valida que los dos archivos cubran las alertas de muestra.json, con etiquetas del protocolo y origen «humano»;
2. calcula el acuerdo bruto y la kappa de Cohen ANTES de conciliar, con su IC 95 % bootstrap (global, por familia y
   por código), y lista los desacuerdos para la reunión de conciliación;
3. con el archivo de decisiones (--decisiones), deja la etiqueta conciliada de cada alerta y calcula la precisión por
   código con IC de Wilson, la precisión global reponderada y el acuerdo entre la etiqueta humana conciliada y la de
   la revisión automatizada (kappa humano frente a automatizado).

Mientras falten decisiones, la salida no muestra nada de la revisión automatizada: así la reunión también es ciega.
Reutiliza las funciones de ../conciliar.py (kappa, bootstrap, Wilson, reponderación y las decisiones automatizadas)
importándolo, sin modificarlo. No se conecta a ninguna base de datos ni a la red.

Escribe en la carpeta del kit (o en --salida): conciliacion_humana.json, resumen_humano.md y, mientras falten
decisiones, decisiones_plantilla.json para llenarla en la reunión.

Uso (desde cualquier carpeta, con el entorno de la API, que trae numpy):
    python -I conciliar_humanos.py etiquetas_humano_revisor_a.json etiquetas_humano_revisor_b.json
    python -I conciliar_humanos.py etiquetas_humano_revisor_a.json etiquetas_humano_revisor_b.json \\
        --decisiones decisiones_conciliacion.json

Formato del archivo de decisiones (JSON; la plantilla sale sola con los desacuerdos y las dos justificaciones):
    {
      "conciliacion": {"fecha": "2026-11-12", "participantes": "…", "notas": "…"},
      "decisiones": {
        "Mxxx": {"etiqueta": "falsa", "criterio": "2.2", "motivo": "…"}
      }
    }
- solo se deciden alertas en desacuerdo: si los dos revisores coinciden, la etiqueta queda (protocolo §2.4);
- etiqueta: verdadera, falsa o indeterminada (vacía = todavía pendiente); motivo: obligatorio; criterio: opcional;
- las claves que empiezan con «_» son contexto de la plantilla y no se leen.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REVISION = AQUI.parent
CONFIANZAS = ("alta", "media", "baja")
CAMPOS = ("id", "etiqueta", "confianza", "razon", "revisor", "fecha", "origen")
FAMILIAS = {"pronostico": "Pronóstico", "observada": "Observadas"}
# Quién revisa, según INSTRUCCIONES.md. Va en conciliacion_humana.json y en resumen_humano.md; no afirma que la
# revisión ya esté hecha ni da por comprobada el área de los revisores, que el script no puede verificar.
AVISO = ("Según INSTRUCCIONES.md, la revisión humana la hacen dos personas del área operativa de Sobusa, cada una por "
         "separado y a ciegas, y sus desacuerdos se concilian en una reunión. Los nombres de los revisores salen de "
         "sus archivos de etiquetas: este script no comprueba a qué área pertenecen.")


def cargar_conciliar():
    """../conciliar.py como módulo, sin ejecutar su main (kappa, bootstrap, Wilson, reponderación, DECISIONES)."""
    spec = importlib.util.spec_from_file_location("conciliar_automatizada", REVISION / "conciliar.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


CONC = cargar_conciliar()
CATEGORIAS = CONC.CATEGORIAS


class ErrorConciliacion(Exception):
    """Un archivo de etiquetas o de decisiones que no se puede usar; el mensaje dice qué corregir."""


# --- Lectura -------------------------------------------------------------------------------------------------------
def leer_json(ruta: Path):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ErrorConciliacion(f"{Path(ruta).name}: no se pudo leer como JSON ({e})") from e


def clave_nombre(nombre: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", str(nombre)).encode("ascii", "ignore").decode("ascii")
    return " ".join(sin_tildes.lower().split())


def leer_muestra() -> dict:
    muestra = CONC.leer_json("muestra.json")
    return {"items": muestra["muestra"], "poblacion": muestra["poblacion"]}


def leer_etiquetas(ruta: Path, ids: list[str]) -> dict:
    """Archivo descargado de revisar.html → {revisor, archivo, etiquetas por id}. Falla si no cubre la muestra."""
    datos = leer_json(ruta)
    nombre = Path(ruta).name
    if not isinstance(datos, list) or not all(isinstance(f, dict) for f in datos):
        raise ErrorConciliacion(f"{nombre}: debe ser una lista de etiquetas (el formato de etiquetas_A.json)")
    if any(f.get("origen") != "humano" for f in datos):
        raise ErrorConciliacion(f"{nombre}: no es un archivo de etiquetas humanas descargado de revisar.html "
                                "(cada fila lleva origen = «humano»)")
    problemas = []
    por_id: dict[str, dict] = {}
    for k, fila in enumerate(datos, 1):
        faltan = [c for c in CAMPOS if c not in fila]
        if faltan:
            problemas.append(f"fila {k} ({fila.get('id', '?')}): faltan {', '.join(faltan)}")
            continue
        i = fila["id"]
        if fila["etiqueta"] not in CATEGORIAS:
            problemas.append(f"{i}: etiqueta «{fila['etiqueta']}» fuera del protocolo")
        if fila["confianza"] is not None and fila["confianza"] not in CONFIANZAS:
            problemas.append(f"{i}: confianza «{fila['confianza']}» (alta, media o baja)")
        if not isinstance(fila["razon"], str):
            problemas.append(f"{i}: la justificación no es texto")
        if i in por_id:
            problemas.append(f"{i}: repetida")
        por_id[i] = fila
    revisores = {str(f.get("revisor", "")).strip() for f in por_id.values()}
    if len(revisores) != 1 or not next(iter(revisores), ""):
        problemas.append("el archivo debe ser de un solo revisor, con su nombre")
    faltan_ids = [i for i in ids if i not in por_id]
    sobran = sorted(set(por_id) - set(ids))
    if faltan_ids:
        problemas.append(f"faltan {len(faltan_ids)} de {len(ids)} alertas: {', '.join(faltan_ids)}")
    if sobran:
        problemas.append(f"alertas que no son de la muestra: {', '.join(sobran)}")
    if problemas:
        extra = f" (y {len(problemas) - 12} problemas más)" if len(problemas) > 12 else ""
        raise ErrorConciliacion(f"{nombre}: " + "; ".join(problemas[:12]) + extra)
    return {"archivo": nombre, "revisor": next(iter(revisores)), "etiquetas": por_id}


def resumen_revisor(r: dict) -> dict:
    """Cobertura y ritmo de un revisor (primera y última etiqueta, minutos entre ellas)."""
    fechas = []
    for f in r["etiquetas"].values():
        try:
            fechas.append(datetime.fromisoformat(str(f["fecha"])))
        except ValueError:
            continue
    try:
        primera, ultima = (min(fechas), max(fechas)) if fechas else (None, None)
    except TypeError:                      # mezcla de fechas con y sin huso horario
        primera = ultima = None
    return {
        "nombre": r["revisor"], "archivo": r["archivo"], "etiquetas": len(r["etiquetas"]),
        "primera": primera.isoformat() if primera else None, "ultima": ultima.isoformat() if ultima else None,
        "minutos_entre_primera_y_ultima": round((ultima - primera).total_seconds() / 60, 1) if primera else None,
        "confianza": {**{c: sum(f["confianza"] == c for f in r["etiquetas"].values()) for c in CONFIANZAS},
                      "sin_indicar": sum(f["confianza"] is None for f in r["etiquetas"].values())},
        "sin_justificacion": sum(not str(f["razon"]).strip() for f in r["etiquetas"].values()),
    }


def leer_decisiones(ruta: Path | None, desacuerdos: list[str], ids: list[str]) -> tuple[dict, dict]:
    """Archivo de decisiones → ({id: {etiqueta, criterio, motivo}}, metadatos). Las vacías siguen pendientes."""
    if ruta is None:
        return {}, {}
    datos = leer_json(ruta)
    nombre = Path(ruta).name
    if not isinstance(datos, dict) or not isinstance(datos.get("decisiones"), dict):
        raise ErrorConciliacion(f"{nombre}: debe ser un objeto con la clave «decisiones» "
                                "(ver decisiones_plantilla.json)")
    decisiones, problemas = {}, []
    for i, d in datos["decisiones"].items():
        if i not in ids:
            problemas.append(f"{i}: no es una alerta de la muestra")
        elif i not in desacuerdos:
            problemas.append(f"{i}: los dos revisores coinciden; esa etiqueta queda (protocolo §2.4) y no se concilia")
        elif not isinstance(d, dict):
            problemas.append(f"{i}: la decisión debe ser un objeto con etiqueta y motivo")
        else:
            etiqueta = str(d.get("etiqueta") or "").strip().lower()
            if not etiqueta:
                continue
            motivo = str(d.get("motivo") or "").strip()
            if etiqueta not in CATEGORIAS:
                problemas.append(f"{i}: etiqueta «{etiqueta}» fuera del protocolo")
            elif not motivo:
                problemas.append(f"{i}: falta el motivo de la decisión")
            else:
                decisiones[i] = {"etiqueta": etiqueta, "criterio": str(d.get("criterio") or "").strip() or None,
                                 "motivo": motivo}
    if problemas:
        raise ErrorConciliacion(f"{nombre}: " + "; ".join(problemas))
    meta = datos.get("conciliacion") if isinstance(datos.get("conciliacion"), dict) else {}
    return decisiones, {"archivo": nombre, **{k: v for k, v in meta.items() if not str(k).startswith("_")}}


def automatizadas(ids: list[str]) -> dict[str, str]:
    """Etiqueta final de la revisión automatizada, con la misma regla de conciliar.py: si A = B queda; si no, decide
    el conciliador (DECISIONES)."""
    a = {x["id"]: x["etiqueta"] for x in CONC.leer_json("etiquetas_A.json")}
    b = {x["id"]: x["etiqueta"] for x in CONC.leer_json("etiquetas_B.json")}
    return {i: CONC.DECISIONES[i]["etiqueta"] if a[i] != b[i] else a[i] for i in ids}


# --- Cálculo -------------------------------------------------------------------------------------------------------
def ic_kappa(x: list[str], y: list[str], reps: int) -> list[float] | None:
    if CONC.kappa_cohen(x, y)["kappa"] is None:
        return None
    try:
        return CONC.kappa_bootstrap(x, y, reps=reps)
    except (IndexError, ValueError):
        return None


def matriz(x: list[str], y: list[str]) -> dict:
    pares = Counter(zip(x, y, strict=True))
    return {a: {b: pares[(a, b)] for b in CATEGORIAS} for a in CATEGORIAS}


def acuerdo(items: list[dict], x: dict[str, str], y: dict[str, str], reps: int) -> dict:
    """Acuerdo bruto y kappa: global (con IC 95 % bootstrap y matriz), por familia y por código."""
    def bloque(filtro) -> dict:
        sel = [it["id"] for it in items if filtro(it)]
        res = CONC.kappa_cohen([x[i] for i in sel], [y[i] for i in sel])
        if res["kappa"] is None:
            res["nota"] = "kappa no definida: las dos fuentes usaron una sola categoría (acuerdo esperado = 1)"
        return res

    ids = [it["id"] for it in items]
    lx, ly = [x[i] for i in ids], [y[i] for i in ids]
    glob = bloque(lambda it: True)
    glob["kappa_ic95_bootstrap"] = ic_kappa(lx, ly, reps)
    glob["matriz_filas_columnas"] = matriz(lx, ly)
    return {
        "global": glob,
        "por_familia": {f: bloque(lambda it, f=f: it["familia"] == f) for f in familias(items)},
        "por_codigo": {c: bloque(lambda it, c=c: it["codigo"] == c) for c in sorted({it["codigo"] for it in items})},
    }


def familias(items: list[dict]) -> list[str]:
    """Familias de la muestra en el orden de resumen.md: pronóstico y después observadas."""
    orden = list(FAMILIAS)
    return sorted({it["familia"] for it in items}, key=lambda f: (orden.index(f) if f in orden else len(orden), f))


def rotulo_familia(familia: str, items: list[dict]) -> str:
    codigos = sorted({it["codigo"] for it in items if it["familia"] == familia})
    rango = codigos[0] if len(codigos) == 1 else f"{codigos[0]} a {codigos[-1]}"
    return f"{FAMILIAS.get(familia, familia)} ({rango})"


def conteo(etiquetas: list[str]) -> dict:
    cnt = Counter(etiquetas)
    v, f = cnt["verdadera"], cnt["falsa"]
    return {"verdaderas": v, "falsas": f, "indeterminadas": cnt["indeterminada"], "n": len(etiquetas),
            "precision": round(v / (v + f), 4) if v + f else None, "precision_ic95_wilson": CONC.wilson(v, v + f)}


def precision_por_codigo(items: list[dict], final: dict[str, str], auto: dict[str, str], poblacion: dict) -> dict:
    out = {}
    for c in sorted(poblacion):
        sub = [it["id"] for it in items if it["codigo"] == c]
        h = conteo([final[i] for i in sub])
        a = conteo([auto[i] for i in sub])
        dec = h["verdaderas"] + h["falsas"]
        out[c] = {
            "poblacion": poblacion[c], **h,
            "tasa_falsas": None if h["precision"] is None else round(1 - h["precision"], 4),
            "tasa_falsas_ic95_wilson": CONC.wilson(h["falsas"], dec),
            "ids_falsas": [i for i in sub if final[i] == "falsa"],
            "ids_indeterminadas": [i for i in sub if final[i] == "indeterminada"],
            "automatizada": {k: a[k] for k in ("verdaderas", "falsas", "indeterminadas", "precision")},
        }
    return out


def reponderada(por_codigo: dict, poblacion: dict) -> dict | None:
    if not any(r["verdaderas"] + r["falsas"] for r in por_codigo.values()):
        return None
    res = CONC.reponderada(por_codigo, poblacion)
    res.pop("nota_intervalo", None)            # la nota de conciliar.py habla de la revisión automatizada
    return res


def conciliar(r1: dict, r2: dict, muestra: dict, decisiones: dict, meta: dict, reps: int) -> dict:
    items, poblacion = muestra["items"], muestra["poblacion"]
    ids = [it["id"] for it in items]
    e1 = {i: r1["etiquetas"][i]["etiqueta"] for i in ids}
    e2 = {i: r2["etiquetas"][i]["etiqueta"] for i in ids}
    desacuerdos = [i for i in ids if e1[i] != e2[i]]
    pendientes = [i for i in desacuerdos if i not in decisiones]
    completa = not pendientes
    por_id = {it["id"]: it for it in items}

    lista_desacuerdos = []
    for i in desacuerdos:
        it, f1, f2 = por_id[i], r1["etiquetas"][i], r2["etiquetas"][i]
        fila = {k: it[k] for k in ("codigo", "familia", "ruta", "fecha", "ventana")}
        for n, f in (("1", f1), ("2", f2)):
            fila |= {f"etiqueta_revisor_{n}": f["etiqueta"], f"confianza_revisor_{n}": f["confianza"],
                     f"razon_revisor_{n}": f["razon"]}
        lista_desacuerdos.append({"id": i, **fila, "decision": decisiones.get(i)})

    salida = {
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "aviso": AVISO,
        "estado": "completa" if completa else "pendiente",
        "revisores": {"revisor_1": resumen_revisor(r1), "revisor_2": resumen_revisor(r2)},
        "familias": {f: rotulo_familia(f, items) for f in familias(items)},
        "conciliacion": {**meta, "desacuerdos": len(desacuerdos), "decididos": len(desacuerdos) - len(pendientes),
                         "pendientes": pendientes},
        "metodo": {
            "acuerdo": ("acuerdo bruto y kappa de Cohen con 3 categorías (verdadera, falsa, indeterminada) ANTES de "
                        f"conciliar; IC 95 % de la kappa global por bootstrap de tarjetas ({reps} réplicas, semilla "
                        f"{CONC.SEMILLA}); funciones de ../conciliar.py"),
            "conciliacion": ("si los dos revisores coinciden la etiqueta queda; si difieren, decide la reunión de "
                             "conciliación con el orden de decisión de protocolo.md §2 (archivo de decisiones)"),
            "precision": "verdaderas / (verdaderas + falsas) por código, indeterminadas aparte; IC 95 % de Wilson",
            "reponderada": ("Σ (población del código / población total) × precisión del código; intervalo de "
                            "credibilidad 95 % Beta(V + 0,5; F + 0,5) por código con 200.000 simulaciones "
                            "(semilla 42)"),
            "humano_vs_automatizado": ("kappa entre la etiqueta humana conciliada y la final de la revisión "
                                       "automatizada (agentes A y B conciliados por conciliar.py); se calcula solo "
                                       "cuando la conciliación humana está completa"),
        },
        "acuerdo_antes_de_conciliar": acuerdo(items, e1, e2, reps),
        "desacuerdos": lista_desacuerdos,
        "etiquetas_finales": None, "precision_por_codigo": None, "precision_global_reponderada": None,
        "precision_global_sin_ponderar": None, "humano_vs_automatizado": None,
    }
    if not completa:
        return salida

    final = {i: e1[i] if e1[i] == e2[i] else decisiones[i]["etiqueta"] for i in ids}
    auto = automatizadas(ids)
    salida["etiquetas_finales"] = [
        {"id": i, "codigo": por_id[i]["codigo"], "familia": por_id[i]["familia"], "ruta": por_id[i]["ruta"],
         "fecha": por_id[i]["fecha"], "ventana": por_id[i]["ventana"], "etiqueta_revisor_1": e1[i],
         "etiqueta_revisor_2": e2[i], "etiqueta_final": final[i],
         "origen": "acuerdo" if e1[i] == e2[i] else "conciliación"}
        for i in ids
    ]
    por_codigo = precision_por_codigo(items, final, auto, poblacion)
    salida["precision_por_codigo"] = por_codigo
    codigos_familia = {f: sorted({it["codigo"] for it in items if it["familia"] == f}) for f in familias(items)}
    salida["precision_global_reponderada"] = {
        "todas": reponderada(por_codigo, poblacion),
        **{f: reponderada({c: por_codigo[c] for c in cods}, poblacion) for f, cods in codigos_familia.items()},
    }
    salida["precision_global_sin_ponderar"] = conteo(list(final.values()))
    hva = acuerdo(items, final, auto, reps)
    hva["por_revisor"] = {"revisor_1": CONC.kappa_cohen([e1[i] for i in ids], [auto[i] for i in ids]),
                          "revisor_2": CONC.kappa_cohen([e2[i] for i in ids], [auto[i] for i in ids])}
    hva["diferencias"] = [{"id": i, "codigo": por_id[i]["codigo"], "humana": final[i], "automatizada": auto[i]}
                          for i in ids if final[i] != auto[i]]
    salida["humano_vs_automatizado"] = hva
    return salida


# --- Salidas -------------------------------------------------------------------------------------------------------
def dec(x, n: int = 3) -> str:
    return "—" if x is None else f"{x:.{n}f}".replace(".", ",").replace("-", "−")


def pct(x, n: int = 1) -> str:
    return "—" if x is None else dec(100 * x, n) + " %"


def intervalo(par, n: int = 3) -> str:
    return "—" if not par else f"{dec(par[0], n)} a {dec(par[1], n)}"


def alerta_texto(d: dict) -> str:
    return f"{d['codigo']} · {d['ruta']} · {d['fecha']} · {d['ventana']}"


def celda(texto) -> str:
    return " ".join(str(texto or "").split()).replace("|", "\\|")


def tabla_acuerdo(bloques: dict, rotulos: dict) -> list[str]:
    g = bloques["global"]
    filas = ["| Bloque | Tarjetas | Coinciden | Acuerdo bruto | Kappa de Cohen |", "|---|---|---|---|---|",
             f"| **Global** | {g['n']} | {g['coinciden']} | **{pct(g['acuerdo_bruto'])}** | **{dec(g['kappa'])}** "
             f"(IC 95 % bootstrap {intervalo(g['kappa_ic95_bootstrap'])}) |"]
    for nombre, r in list(bloques["por_familia"].items()) + list(bloques["por_codigo"].items()):
        kappa = dec(r["kappa"]) if r["kappa"] is not None else "no definida (una sola categoría)"
        filas.append(f"| {rotulos.get(nombre, nombre)} | {r['n']} | {r['coinciden']} | {pct(r['acuerdo_bruto'])} | "
                     f"{kappa} |")
    return filas


def tabla_matriz(m: dict, filas_rotulo: str, columnas_rotulo: str) -> list[str]:
    out = [f"| {filas_rotulo} \\ {columnas_rotulo} | " + " | ".join(CATEGORIAS) + " |", "|---|---|---|---|"]
    out += [f"| {a} | " + " | ".join(str(m[a][b]) for b in CATEGORIAS) + " |" for a in CATEGORIAS]
    return out


def estado_md(s: dict) -> str:
    c = s["conciliacion"]
    if s["estado"] != "completa":
        return (f"**Conciliación pendiente**: faltan {len(c['pendientes'])} de {c['desacuerdos']} decisiones. Las "
                "cifras de precisión y la comparación con la revisión automatizada salen cuando estén todas.")
    if not c["desacuerdos"]:
        return "**Conciliación completa**: no hubo desacuerdos."
    texto = f"**Conciliación completa**: {c['decididos']} desacuerdos decididos en la reunión"
    if c.get("fecha"):
        texto += f" del {c['fecha']}"
    if c.get("participantes"):
        texto += f" ({celda(c['participantes'])})"
    return texto + "."


def periodo_md(r: dict) -> str:
    if not r["primera"]:
        return "—"
    return f"{r['primera'][:16].replace('T', ' ')} a {r['ultima'][11:16]}"


def resumen_md(s: dict, reps: int) -> str:
    r1, r2 = s["revisores"]["revisor_1"], s["revisores"]["revisor_2"]
    n1, n2 = r1["nombre"], r2["nombre"]
    c = s["conciliacion"]
    lineas = [
        "# Revisión doble HUMANA de alertas y conciliación (§18 «Etiquetas incorrectas → métricas engañosas»)",
        "",
        f"> **Revisión humana, a ciegas e independiente.** {celda(n1)} y {celda(n2)} etiquetaron por separado las "
        f"mismas {r1['etiquetas']} alertas con `revisar.html` y el protocolo escrito (`../protocolo.md`). {AVISO} "
        f"Generado por `conciliar_humanos.py` el {s['generado'][:16].replace('T', ' ')}.",
        "",
        estado_md(s),
        "",
        "## 1. Revisores y cobertura",
        "",
        "| Revisor | Archivo | Alertas | Primera y última etiqueta | Minutos entre ellas "
        "| Confianza alta / media / baja | Sin justificación |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in (r1, r2):
        conf = r["confianza"]
        sin = f" ({conf['sin_indicar']} sin indicar)" if conf["sin_indicar"] else ""
        lineas.append(f"| {celda(r['nombre'])} | `{r['archivo']}` | {r['etiquetas']} | {periodo_md(r)} | "
                      f"{dec(r['minutos_entre_primera_y_ultima'], 0)} | {conf['alta']} / {conf['media']} / "
                      f"{conf['baja']}{sin} | {r['sin_justificacion']} |")
    a = s["acuerdo_antes_de_conciliar"]
    lineas += ["", "## 2. Acuerdo entre revisores (antes de conciliar)", "", *tabla_acuerdo(a, s["familias"]), "",
               f"Matriz {n1} (filas) × {n2} (columnas):", "",
               *tabla_matriz(a["global"]["matriz_filas_columnas"], n1, n2), "",
               "## 3. Desacuerdos y conciliación", ""]
    if not s["desacuerdos"]:
        lineas.append("No hubo desacuerdos: la etiqueta de cada alerta es la de los dos revisores.")
    else:
        lineas += [f"| Id | Alerta | {celda(n1)} | {celda(n2)} | Etiqueta final | Motivo de la reunión |",
                   "|---|---|---|---|---|---|"]
        for d in s["desacuerdos"]:
            dd = d["decision"]
            final = f"**{dd['etiqueta']}**" if dd else "pendiente"
            motivo = celda((f"{dd['criterio']}: " if dd and dd["criterio"] else "") + dd["motivo"]) if dd else "—"
            lineas.append(f"| {d['id']} | {alerta_texto(d)} | {d['etiqueta_revisor_1']} ({d['confianza_revisor_1']}) | "
                          f"{d['etiqueta_revisor_2']} ({d['confianza_revisor_2']}) | {final} | {motivo} |")
        lineas += ["", "Justificaciones de cada revisor (para releer la tarjeta en la reunión):", ""]
        for d in s["desacuerdos"]:
            z1 = celda(d["razon_revisor_1"]) or "sin justificación"
            z2 = celda(d["razon_revisor_2"]) or "sin justificación"
            lineas.append(f"- **{d['id']}** ({alerta_texto(d)}). {celda(n1)}: «{z1}». {celda(n2)}: «{z2}».")
        if s["estado"] != "completa":
            lineas += ["", "Para la reunión: copien `decisiones_plantilla.json` como `decisiones_conciliacion.json`, "
                       "relean cada tarjeta en `revisar.html` (pestaña «Lista») con el orden de decisión del protocolo "
                       "(§2), escriban la etiqueta final y el motivo, y vuelvan a correr el script con "
                       "`--decisiones decisiones_conciliacion.json`. Si la tarjeta no permite decidir, queda "
                       "«indeterminada»."]
    if s["estado"] != "completa":
        lineas += ["", "## 4. Precisión y comparación con la revisión automatizada", "",
                   "Se calculan cuando todos los desacuerdos tengan decisión. Hasta entonces este resumen no muestra "
                   "nada de la revisión automatizada, para que la conciliación también sea ciega."]
    else:
        lineas += secciones_finales(s)
    lineas += ["", "## Cómo se reproduce", "",
               "Desde cualquier carpeta, con el entorno de la API (`api_frecuencias/.venv`, que trae numpy):", "",
               "```",
               f"python -I conciliar_humanos.py {r1['archivo']} {r2['archivo']}"
               + (f" --decisiones {c['archivo']}" if c.get("archivo") else ""),
               "```", "",
               f"Los intervalos con remuestreo usan la semilla {CONC.SEMILLA} ({reps} réplicas para la kappa), así "
               "que todo es determinista salvo la fecha de generación.", ""]
    return "\n".join(lineas)


def secciones_finales(s: dict) -> list[str]:
    pc = s["precision_por_codigo"]
    lineas = ["", "## 4. Precisión con las etiquetas conciliadas", "",
              "| Código | Población | Muestra | V | F | I | Precisión | IC 95 % (Wilson) | Tasa de falsas | "
              "Precisión de la revisión automatizada |", "|---|---|---|---|---|---|---|---|---|---|"]
    for cod, r in pc.items():
        lineas.append(f"| {cod} | {r['poblacion']} | {r['n']} | {r['verdaderas']} | {r['falsas']} | "
                      f"{r['indeterminadas']} | **{dec(r['precision'])}** | {intervalo(r['precision_ic95_wilson'])} | "
                      f"{dec(r['tasa_falsas'])} | {dec(r['automatizada']['precision'])} |")
    lineas += ["", "Precisión global reponderada (pesos = población del código / población total; "
               "indeterminadas fuera):",
               "", "| Conjunto | Precisión | Intervalo 95 % (Jeffreys, Monte Carlo) | Tasa de falsas | "
               "Si las indeterminadas fueran falsas / verdaderas |", "|---|---|---|---|---|"]
    for nombre, r in s["precision_global_reponderada"].items():
        rotulo = {"todas": "**Todas**"}.get(nombre, s["familias"].get(nombre, nombre))
        if r is None:
            lineas.append(f"| {rotulo} | — | — | — | — |")
            continue
        lineas.append(f"| {rotulo} | {dec(r['precision'])} | {intervalo(r['intervalo_95_jeffreys_mc'])} | "
                      f"{dec(r['tasa_falsas'])} | {dec(r['cota_indeterminadas_falsas'])} / "
                      f"{dec(r['cota_indeterminadas_verdaderas'])} |")
    sp = s["precision_global_sin_ponderar"]
    lineas += ["", f"Sin reponderar ({sp['verdaderas']} V, {sp['falsas']} F, {sp['indeterminadas']} I) la precisión "
               f"sería {dec(sp['precision'])} ({intervalo(sp['precision_ic95_wilson'])}): la muestra sobrerrepresenta "
               "a las observadas por el mínimo de 8 por código."]
    h = s["humano_vs_automatizado"]
    g = h["global"]
    pr = h["por_revisor"]
    r1, r2 = s["revisores"]["revisor_1"]["nombre"], s["revisores"]["revisor_2"]["nombre"]
    lineas += ["", "## 5. Etiqueta humana conciliada frente a la automatizada", "",
               "La automatizada es la etiqueta final de la revisión hecha por agentes de modelo de lenguaje "
               "(`../conciliacion.json`). Esta comparación mide cuánto se parece el criterio de los agentes al de los "
               "dos revisores humanos, ya conciliado, en la misma muestra.", "",
               *tabla_acuerdo(h, s["familias"]), "",
               f"Cada revisor por separado frente a la automatizada: {celda(r1)} kappa {dec(pr['revisor_1']['kappa'])} "
               f"(acuerdo {pct(pr['revisor_1']['acuerdo_bruto'])}); {celda(r2)} kappa {dec(pr['revisor_2']['kappa'])} "
               f"(acuerdo {pct(pr['revisor_2']['acuerdo_bruto'])}).", "",
               "Matriz humana conciliada (filas) × automatizada (columnas):", "",
               *tabla_matriz(g["matriz_filas_columnas"], "humana", "automatizada"), ""]
    if h["diferencias"]:
        lineas += [f"Alertas donde difieren ({len(h['diferencias'])}):", "",
                   "| Id | Código | Humana conciliada | Automatizada |", "|---|---|---|---|"]
        lineas += [f"| {d['id']} | {d['codigo']} | {d['humana']} | {d['automatizada']} |" for d in h["diferencias"]]
    else:
        lineas.append("La etiqueta humana conciliada coincide con la automatizada en todas las alertas.")
    return lineas


def plantilla(s: dict, decisiones: dict) -> dict:
    n1 = s["revisores"]["revisor_1"]["nombre"]
    n2 = s["revisores"]["revisor_2"]["nombre"]
    return {
        "_instrucciones": ("Copien este archivo como decisiones_conciliacion.json. En cada desacuerdo escriban la "
                           "etiqueta final (verdadera, falsa o indeterminada), el criterio (paso del protocolo §2) y "
                           "el motivo; si la tarjeta no permite decidir, queda indeterminada. Luego corran "
                           "conciliar_humanos.py con --decisiones decisiones_conciliacion.json. Las claves que "
                           "empiezan con «_» no se leen."),
        "conciliacion": {"fecha": "", "participantes": "", "notas": ""},
        "decisiones": {
            d["id"]: {
                "_alerta": alerta_texto(d),
                "_revisor_1": f"{n1}: {d['etiqueta_revisor_1']} ({d['confianza_revisor_1']}). {d['razon_revisor_1']}",
                "_revisor_2": f"{n2}: {d['etiqueta_revisor_2']} ({d['confianza_revisor_2']}). {d['razon_revisor_2']}",
                "etiqueta": decisiones.get(d["id"], {}).get("etiqueta", ""),
                "criterio": decisiones.get(d["id"], {}).get("criterio") or "",
                "motivo": decisiones.get(d["id"], {}).get("motivo", ""),
            }
            for d in s["desacuerdos"]
        },
    }


def escribir(ruta: Path, texto: str) -> None:
    ruta.write_text(texto, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("revisor_1", type=Path, help="archivo de etiquetas del primer revisor (descargado de revisar.html)")
    ap.add_argument("revisor_2", type=Path, help="archivo de etiquetas del segundo revisor")
    ap.add_argument("--decisiones", type=Path, help="decisiones de la reunión de conciliación (JSON)")
    ap.add_argument("--salida", type=Path, default=AQUI, help="carpeta donde se escriben los resultados")
    ap.add_argument("--reps", type=int, default=5000, help="réplicas bootstrap de la kappa (por defecto 5000)")
    args = ap.parse_args(argv)
    try:
        if args.revisor_1.resolve() == args.revisor_2.resolve():
            raise ErrorConciliacion("los dos archivos son el mismo: la revisión doble necesita dos revisores")
        muestra = leer_muestra()
        ids = [it["id"] for it in muestra["items"]]
        r1 = leer_etiquetas(args.revisor_1, ids)
        r2 = leer_etiquetas(args.revisor_2, ids)
        if clave_nombre(r1["revisor"]) == clave_nombre(r2["revisor"]):
            raise ErrorConciliacion(f"los dos archivos son del mismo revisor ({r1['revisor']})")
        desacuerdos = [i for i in ids if r1["etiquetas"][i]["etiqueta"] != r2["etiquetas"][i]["etiqueta"]]
        decisiones, meta = leer_decisiones(args.decisiones, desacuerdos, ids)
    except ErrorConciliacion as e:
        print(f"No se concilió: {e}", file=sys.stderr)
        return 2

    s = conciliar(r1, r2, muestra, decisiones, meta, args.reps)
    args.salida.mkdir(parents=True, exist_ok=True)
    escribir(args.salida / "conciliacion_humana.json", json.dumps(s, ensure_ascii=False, indent=1) + "\n")
    escribir(args.salida / "resumen_humano.md", resumen_md(s, args.reps))
    escritos = ["conciliacion_humana.json", "resumen_humano.md"]
    if s["estado"] != "completa":
        escribir(args.salida / "decisiones_plantilla.json",
                 json.dumps(plantilla(s, decisiones), ensure_ascii=False, indent=2) + "\n")
        escritos.append("decisiones_plantilla.json")

    g = s["acuerdo_antes_de_conciliar"]["global"]
    print(f"{r1['revisor']} y {r2['revisor']}: {g['coinciden']}/{g['n']} iguales, acuerdo {g['acuerdo_bruto']}, "
          f"kappa {g['kappa']} IC {g['kappa_ic95_bootstrap']}")
    for d in s["desacuerdos"]:
        dd = d["decision"]
        print(f"  {d['id']} {alerta_texto(d)}: {d['etiqueta_revisor_1']} / {d['etiqueta_revisor_2']}"
              + (f" -> {dd['etiqueta']}" if dd else " -> pendiente"))
    if s["estado"] == "completa":
        h = s["humano_vs_automatizado"]["global"]
        print(f"conciliación completa; humano frente a automatizado: acuerdo {h['acuerdo_bruto']}, kappa {h['kappa']} "
              f"IC {h['kappa_ic95_bootstrap']}")
    else:
        print(f"conciliación pendiente: faltan {len(s['conciliacion']['pendientes'])} decisiones "
              "(decisiones_plantilla.json)")
    print("escrito en " + str(args.salida) + ": " + ", ".join(escritos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
