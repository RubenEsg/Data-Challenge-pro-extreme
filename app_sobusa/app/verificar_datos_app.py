# -*- coding: utf-8 -*-
"""Verifica app/datos_app.js: vuelve a leer cada cifra desde su archivo y su clave y la compara.

Usa código propio (no importa nada de generar_datos_app.py): su propio lector de archivos, su propio intérprete de
claves, agrupa los Parquet con pyarrow y evalúa las fórmulas con un evaluador aritmético mínimo. Además:
  - ids únicos entre pantallas y todos los ids del inventario presentes (salvo los ausentes declarados);
  - toda cifra trae archivo, clave, experimento, verificado (sí | parcial | no) y un origen que cubre cada valor;
  - sin rutas absolutas, carpetas temporales ni correos en el archivo; tamaño ≤ 3 MB;
  - la ficha de los modelos (pantallas.modelo.ficha) pasa las comprobaciones de app/verificar_ficha_modelos.py.

Uso (desde la carpeta del proyecto):  PYTHONIOENCODING=utf-8 python app/verificar_datos_app.py
Sale con código 1 si hay algún fallo.
"""
import ast
import base64
import csv
import gzip
import io
import json
import math
import operator
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq

sys.dont_write_bytecode = True
APP = Path(__file__).resolve().parent
RAIZ = APP.parent
JS = APP / "datos_app.js"
MAX_BYTES = 3 * 1024 * 1024
fallos = []
avisos = []
cuenta = {"cifras": 0, "comparaciones": 0}


def fallo(msg):
    fallos.append(msg)


# ---------------------------------------------------------------------------------------------------------------
# Lector propio de archivos
# ---------------------------------------------------------------------------------------------------------------
_memo = {}


def _celda(txt, decimal_coma):
    if txt == "":
        return None
    if txt == "True":
        return True
    if txt == "False":
        return False
    candidato = txt.replace(",", ".") if decimal_coma else txt
    if re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", candidato):
        return float(candidato)
    return txt


def abrir(rel):
    if rel in _memo:
        return _memo[rel]
    f = RAIZ / rel
    ext = f.suffix.lower()
    if ext == ".json":
        with open(f, encoding="utf-8") as h:
            obj = json.load(h)
    elif ext == ".js":
        s = f.read_text(encoding="utf-8")
        trozos = [t for t in s.split('"') if t.startswith("H4sI")]
        if trozos:
            obj = json.loads(gzip.decompress(base64.b64decode(trozos[-1])).decode("utf-8"))
        else:
            i = s.find("window.")
            i = s.find("=", i) + 1
            while s[i] in " \t\r\n":
                i += 1
            obj = json.JSONDecoder().raw_decode(s[i:])[0]
    elif ext == ".csv":
        crudo = f.read_bytes().decode("utf-8-sig")
        primera = crudo.split("\n", 1)[0]
        punto_coma = primera.count(";") > primera.count(",")
        lineas = list(csv.reader(io.StringIO(crudo), delimiter=";" if punto_coma else ","))
        cab = ["_" if c == "" else c for c in lineas[0]]
        obj = []
        for fila in lineas[1:]:
            if not fila:
                continue
            obj.append({cab[j]: _celda(fila[j], punto_coma) for j in range(len(cab))})
    elif ext == ".parquet":
        obj = pq.read_table(f).to_pylist()
    else:
        obj = f.read_text(encoding="utf-8")
    _memo[rel] = obj
    return obj


# ---------------------------------------------------------------------------------------------------------------
# Intérprete propio de claves
# ---------------------------------------------------------------------------------------------------------------
def partir(clave):
    """Convierte la clave en pasos: ('clave', k) ('pos', i) ('tramo', a, b) ('todos',) ('filtro', conds, todos)."""
    pasos, i, n = [], 0, len(clave)
    while i < n:
        ch = clave[i]
        if ch == ".":
            i += 1
            continue
        if ch == "[":
            if clave.startswith('["', i):
                j = i + 2
                buf = []
                while clave[j] != '"':
                    if clave[j] == "\\":
                        buf.append(clave[j + 1])
                        j += 2
                        continue
                    buf.append(clave[j])
                    j += 1
                if clave[j + 1] != "]":
                    raise ValueError(f"comillas sin cerrar en {clave}")
                pasos.append(("clave", "".join(buf)))
                i = j + 2
                continue
            j = clave.index("]", i)
            dentro = clave[i + 1:j]
            i = j + 1
            if dentro == "*":
                pasos.append(("todos",))
            elif re.fullmatch(r"-?\d+", dentro):
                pasos.append(("pos", int(dentro)))
            elif re.fullmatch(r"-?\d*:-?\d*", dentro):
                a, b = dentro.split(":")
                pasos.append(("tramo", int(a) if a else None, int(b) if b else None))
            elif "=" in dentro:
                todos = i < n and clave[i] == "*"
                if todos:
                    i += 1
                conds = []
                for parte in dentro.split("&"):
                    k, v = parte.split("=", 1)
                    conds.append((k, v))
                pasos.append(("filtro", conds, todos))
            else:
                raise ValueError(f"corchete no reconocido en {clave}: [{dentro}]")
            continue
        j = i
        while j < n and clave[j] not in ".[":
            j += 1
        pasos.append(("clave", clave[i:j]))
        i = j
    return pasos


def cumple(elem, conds):
    for k, v in conds:
        if not isinstance(elem, dict) or k not in elem:
            return False
        x = elem[k]
        if isinstance(x, bool):
            ok = (v == "True") if x else (v == "False")
        elif isinstance(x, (int, float)):
            try:
                ok = math.isclose(float(v), float(x), rel_tol=0, abs_tol=1e-9)
            except ValueError:
                ok = False
        elif x is None:
            ok = v in ("", "None", "null")
        else:
            ok = x == v
        if not ok:
            return False
    return True


def recorrer(obj, pasos):
    for n, paso in enumerate(pasos):
        tipo = paso[0]
        if tipo == "clave":
            obj = obj[paso[1]]
        elif tipo == "pos":
            obj = obj[paso[1]]
        elif tipo == "tramo":
            obj = obj[paso[1]:paso[2]]
        elif tipo == "todos":
            return [recorrer(e, pasos[n + 1:]) for e in obj]
        else:
            elegidos = [e for e in obj if cumple(e, paso[1])]
            if paso[2]:
                if not elegidos:
                    raise KeyError("filtro sin filas")
                return [recorrer(e, pasos[n + 1:]) for e in elegidos]
            if len(elegidos) != 1:
                raise KeyError(f"el filtro da {len(elegidos)} filas")
            obj = elegidos[0]
    return obj


def operar(v, op):
    if op is None:
        return v
    if op == "suma":
        return math.fsum(x for x in v if x is not None)
    if op == "media":
        xs = [x for x in v if x is not None]
        return math.fsum(xs) / len(xs)
    if op == "n":
        return len(v)
    if op == "max":
        return max(v)
    if op == "min":
        return min(v)
    if op == "claves":
        return list(v)
    if op == "conteo":
        c = {}
        for x in v:
            c[x] = c.get(x, 0) + 1
        return c
    if op == "enteros":
        return [int(t) for t in re.findall(r"-?\d+", str(v))]
    if op == "positivos":
        return len([x for x in v if x is not None and x > 0])
    raise ValueError(f"operación {op}")


def multiplicar(v, x):
    if isinstance(v, list):
        return [multiplicar(e, x) for e in v]
    if isinstance(v, dict):
        return {k: multiplicar(e, x) for k, e in v.items()}
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return v
    return v * x


# ---------------------------------------------------------------------------------------------------------------
# Evaluador aritmético mínimo para las fórmulas
# ---------------------------------------------------------------------------------------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def evaluar(expr, nombres):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            return nombres[n.id]
        raise ValueError(f"expresión no permitida: {expr}")
    return ev(ast.parse(expr, mode="eval"))


# ---------------------------------------------------------------------------------------------------------------
# Parquet: filtrar, agrupar y sumar con Python puro
# ---------------------------------------------------------------------------------------------------------------
def _norm(x):
    if hasattr(x, "strftime"):
        return x.strftime("%Y-%m-%d")
    return x


def parquet(ref):
    filas = abrir(ref["a"])
    sel = [f for f in filas if all(str(_norm(f[k])) == str(v) for k, v in ref["filtro"].items())]
    if not sel:
        raise KeyError("filtro vacío")
    col, por = ref["col"], ref["por"]
    if not por:
        return math.fsum(f[col] for f in sel)
    grupos = {}
    for f in sel:
        k = tuple(_norm(f[c]) for c in por)
        grupos[k] = grupos.get(k, 0.0) + (f[col] or 0.0)
    orden = sorted(grupos)
    if ref["op"] == "grupos":
        return [k[ref.get("parte", 0)] for k in orden]
    return [grupos[k] for k in orden]


# ---------------------------------------------------------------------------------------------------------------
# Markdown y calles
# ---------------------------------------------------------------------------------------------------------------
def _espacios(t):
    return re.sub(r"\s+", " ", t).strip()


def texto_md(ref, valor):
    """Comprueba que el texto guardado esté tal cual en el archivo (y en su sección, si se indica)."""
    t = abrir(ref["a"])
    if ref.get("seccion"):
        lineas = t.split("\n")
        ini = next((i for i, l in enumerate(lineas) if l.strip() == ref["seccion"].strip()), None)
        if ini is None:
            return f"no está la sección {ref['seccion']}"
        nivel = len(ref["seccion"]) - len(ref["seccion"].lstrip("#"))
        fin = next((j for j in range(ini + 1, len(lineas)) if re.match(r"#{1,%d}\s" % nivel, lineas[j])), len(lineas))
        t = "\n".join(lineas[ini:fin])
    plano = _espacios(t)
    trozos = valor if isinstance(valor, list) else [valor]
    if not trozos:
        return "lista vacía"
    for v in trozos:
        if not isinstance(v, str) or not v or _espacios(v) not in plano:
            return f"el texto no está en el archivo: {str(v)[:80]}"
    return None


def calles(ref):
    ind = abrir("sistema_tiempo_real/replay/dias/indice.js")
    tipos = {d["fecha"]: d["tipo_dia"] for d in ind["dias"]}
    if "_calles" not in _memo:
        res = []
        for f in sorted((RAIZ / ref["a"]).glob("2025-*.js")):
            s = f.read_text(encoding="utf-8")
            b64 = [t for t in s.split('"') if t.startswith("H4sI")][-1]
            dia = json.loads(gzip.decompress(base64.b64decode(b64)))["resumen"]["dia"]
            res.append((f.stem, dia["real"]["costo_Mcop"] - dia["plan"]["costo_Mcop"] - dia["plan"]["pasajes_perdidos_Mcop"]))
        _memo["_calles"] = res
    sel = [s for fecha, s in _memo["_calles"] if not ref.get("tipo") or tipos[fecha] == ref["tipo"]]
    return len(sel) if ref["medida"] == "dias" else len([s for s in sel if s < 0])


def leer_ref(ref):
    t = ref["t"]
    if t == "r":
        v = operar(recorrer(abrir(ref["a"]), partir(ref["c"])), ref.get("op"))
        return multiplicar(v, ref["x"]) if "x" in ref else v
    if t == "pq":
        return parquet(ref)
    if t == "f":
        return evaluar(ref["expr"], {k: leer_ref(r) for k, r in ref["v"].items()})
    if t == "calles":
        return calles(ref)
    raise ValueError(t)


# ---------------------------------------------------------------------------------------------------------------
# Comparación con tolerancia de redondeo
# ---------------------------------------------------------------------------------------------------------------
def tolerancia(guardado, fuente):
    dec = -Decimal(repr(float(guardado))).as_tuple().exponent if isinstance(guardado, float) else 0
    return max(0.5 * 10 ** (-max(dec, 0)) * (1 + 1e-9), 6e-6 * abs(fuente)) + 1e-12


def comparar(g, f, donde):
    if isinstance(f, float) and math.isnan(f):
        f = None
    if isinstance(g, bool) or isinstance(f, bool):
        if g != f:
            return f"{donde}: {g!r} frente a {f!r} en la fuente"
        return None
    if isinstance(g, (int, float)) and isinstance(f, (int, float)):
        cuenta["comparaciones"] += 1
        if abs(g - f) > tolerancia(g, f):
            return f"{donde}: {g} frente a {f} en la fuente"
        return None
    if isinstance(f, dict) and isinstance(g, dict):
        if set(f) != set(g):
            return f"{donde}: claves distintas ({sorted(set(f) ^ set(g))[:5]})"
        for k in f:
            r = comparar(g[k], f[k], f"{donde}.{k}")
            if r:
                return r
        return None
    if isinstance(f, (list, tuple)) and isinstance(g, list):
        if len(f) != len(g):
            return f"{donde}: {len(g)} elementos frente a {len(f)}"
        for i, (a, b) in enumerate(zip(g, f)):
            r = comparar(a, b, f"{donde}[{i}]")
            if r:
                return r
        return None
    cuenta["comparaciones"] += 1
    if g != f:
        return f"{donde}: {str(g)[:60]!r} frente a {str(f)[:60]!r}"
    return None


def en_ruta(cifra, ruta):
    if ruta[0] == "columna":
        j = cifra["columnas"].index(ruta[1])
        return [fila[j] for fila in cifra["filas"]]
    v = cifra
    for k in ruta:
        v = v[k]
    return v


def hojas(v, ruta):
    if isinstance(v, dict):
        for k, e in v.items():
            yield from hojas(e, ruta + [k])
    elif isinstance(v, list):
        for i, e in enumerate(v):
            yield from hojas(e, ruta + [i])
    else:
        yield ruta


METADATOS = {"valor", "columnas", "filas", "unidad", "decimales", "archivo", "archivos", "clave", "experimento", "verificado", "revision",
             "que_es", "tipo", "interruptor", "nota", "origen", "verificado_campos"}


def verificar_cifra(pantalla, ident, c):
    cuenta["cifras"] += 1
    for campo in ("archivo", "clave", "experimento", "verificado", "origen"):
        if not c.get(campo):
            fallo(f"{ident}: falta «{campo}»")
    if c.get("verificado") not in ("sí", "parcial", "no"):
        fallo(f"{ident}: verificado = {c.get('verificado')!r}")
    if not isinstance(c.get("decimales"), int):
        fallo(f"{ident}: decimales no es entero")
    if "valor" not in c and not ("filas" in c and "columnas" in c):
        fallo(f"{ident}: sin valor ni filas")
    origen = c.get("origen") or []
    rutas = [tuple(r) for r, _ in origen]
    # Cobertura: cada valor guardado tiene una referencia (la suya o la de un nivel superior)
    partes = [k for k in c if k not in METADATOS] + (["valor"] if "valor" in c else [])
    for k in partes:
        for h in hojas(c[k], [k]):
            if not any(tuple(h[:len(r)]) == r for r in rutas):
                fallo(f"{ident}: el valor en {'.'.join(map(str, h))} no tiene referencia")
                break
    if "filas" in c and "columnas" in c:
        for col in c["columnas"]:
            if ("columna", col) not in rutas:
                fallo(f"{ident}: la columna {col} no tiene referencia")
    archivos = set(a for a in (c.get("archivos") or [c.get("archivo", "")]))
    for ruta, ref in origen:
        planas = [ref] if ref["t"] != "f" else list(_planas(ref))
        for r in planas:
            if r["a"] not in archivos and r["a"] not in c.get("archivo", ""):
                fallo(f"{ident}: la referencia lee {r['a']}, que no figura en «archivo»")
        try:
            guardado = en_ruta(c, ruta)
        except (KeyError, IndexError, ValueError) as e:
            fallo(f"{ident}: no se encuentra {ruta} en la cifra ({e})")
            continue
        try:
            if ref["t"] == "md":
                err = texto_md(ref, guardado)
                cuenta["comparaciones"] += 1
            else:
                err = comparar(guardado, leer_ref(ref), f"{ident}:{'.'.join(map(str, ruta))}")
        except Exception as e:  # noqa: BLE001
            err = f"{ident}:{'.'.join(map(str, ruta))}: no se pudo releer ({type(e).__name__}: {e})"
        if err:
            fallo(err if err.startswith(ident) else f"{ident}:{'.'.join(map(str, ruta))}: {err}")


def _planas(ref):
    if ref["t"] == "f":
        for r in ref["v"].values():
            yield from _planas(r)
    else:
        yield ref


# ---------------------------------------------------------------------------------------------------------------
def main():
    texto = JS.read_text(encoding="utf-8")
    tam = JS.stat().st_size
    if tam > MAX_BYTES:
        fallo(f"datos_app.js pesa {tam} bytes (> 3 MB)")
    k = texto.find("window.DATOS_APP")
    datos = json.JSONDecoder().raw_decode(texto[texto.index("{", k):])[0]
    for patron, que in [(r"[A-Za-z]:\\\\", "ruta absoluta de Windows"), (r"/Users/|/home/", "ruta absoluta"),
                        (r"AppData|scratchpad|[Tt]emp[\\/]", "carpeta temporal"), (r"[\w.+-]+@[\w-]+\.[\w.]+", "correo"),
                        (r"idconductor", "idconductor")]:
        m = re.search(patron, texto)
        if m:
            fallo(f"datos_app.js contiene {que}: …{texto[max(0, m.start() - 40):m.end() + 40]}…")

    pantallas = datos.get("pantallas", {})
    esperadas = ["inicio", "demanda", "modelo", "horario", "despacho", "ciudad", "resultado", "piloto", "metodo"]
    if list(pantallas) != esperadas:
        fallo(f"pantallas: {list(pantallas)}")
    vistos = {}
    for p, ids in pantallas.items():
        for ident, c in ids.items():
            if ident == "ficha":
                continue
            if ident in vistos:
                fallo(f"id repetido: {ident} en {vistos[ident]} y {p}")
            vistos[ident] = p
            verificar_cifra(p, ident, c)

    inv = json.loads((APP / "inventario_cifras.json").read_text(encoding="utf-8"))
    ausentes = {a["id"] for a in datos["meta"].get("ausentes", [])}
    for pant in inv["pantallas"]:
        for c in pant["cifras"]:
            if c["id"] not in vistos and c["id"] not in ausentes:
                fallo(f"falta la cifra del inventario {c['id']}")
            if c["id"] in vistos and c["id"] in ausentes:
                fallo(f"{c['id']} figura como ausente pero está en los datos")
    nuevos = {n["id"] for n in datos["meta"].get("nuevos", [])}
    ids_inv = {c["id"] for pant in inv["pantallas"] for c in pant["cifras"]}
    for ident in vistos:
        if ident not in ids_inv and ident not in nuevos:
            fallo(f"{ident} no está en el inventario ni en meta.nuevos")
    if len(datos.get("contradicciones", [])) != len(inv["contradicciones"]):
        fallo("faltan contradicciones del inventario")

    # Marcas por columna de las corridas del optimizador: cada «sí» debe tener en verificacion_contra_informe.csv
    # una fila del mismo plan cuyo valor (en COP o en M COP) sea el de la cifra (la app guarda dos decimales: tolerancia 0,01).
    reopt = pantallas.get("resultado", {}).get("resultado_d5_reoptimizado", {})
    vc = reopt.get("verificado_campos")
    if not isinstance(vc, dict):
        fallo("resultado_d5_reoptimizado: falta verificado_campos")
    else:
        filas_vci = []
        for linea_csv in (RAIZ / "simulacion_ahorro/resultados/verificacion_contra_informe.csv").read_text(encoding="utf-8-sig").splitlines()[1:]:
            partes_csv = linea_csv.split(";")
            if len(partes_csv) >= 2 and ": " in partes_csv[0]:
                filas_vci.append((partes_csv[0].split(": ", 1)[0], float(partes_csv[1].replace(",", "."))))
        for clave_plan, plan in (("a_D5_original", "a"), ("b_D5_reoptimizado_e05", "b")):
            fila_app = (reopt.get("valor") or {}).get(clave_plan, {})
            for campo, marca in (vc.get(clave_plan) or {}).items():
                if marca not in ("sí", "parcial", "no"):
                    fallo(f"verificado_campos.{clave_plan}.{campo} = {marca!r}")
                if marca != "sí":
                    continue
                v = fila_app.get(campo)
                if not isinstance(v, (int, float)) or not any(p == plan and any(abs(v - x * f) <= max(0.01, 1e-6 * abs(v)) for f in (1.0, 1e-6))
                                                              for p, x in filas_vci):
                    fallo(f"verificado_campos.{clave_plan}.{campo} = «sí» sin fila que lo reproduzca en verificacion_contra_informe.csv")
                cuenta["comparaciones"] += 1

    # Ficha de los modelos
    ficha = pantallas.get("modelo", {}).get("ficha")
    disco = json.loads((APP / "ficha_modelos.json").read_text(encoding="utf-8"))
    if ficha != disco:
        fallo("pantallas.modelo.ficha no es igual a app/ficha_modelos.json")
    r = subprocess.run([sys.executable, str(APP / "verificar_ficha_modelos.py"), str(RAIZ)], capture_output=True, text=True, encoding="utf-8")
    linea = [l for l in r.stdout.splitlines() if l.startswith("comprobaciones:")]
    print("Ficha de los modelos:", linea[-1] if linea else r.stdout.strip()[-200:])
    if r.returncode != 0:
        fallo("la ficha de los modelos no pasa verificar_ficha_modelos.py:\n" + r.stdout[-2000:] + r.stderr[-1000:])

    print(f"datos_app.js: {tam / 1024:.0f} KB · generado {datos['meta'].get('generado')}")
    print(f"Cifras: {cuenta['cifras']} en {len(pantallas)} pantallas · comparaciones: {cuenta['comparaciones']} · ausentes declaradas: {len(ausentes)}")
    for p, ids in pantallas.items():
        print(f"  {p}: {len([i for i in ids if i != 'ficha'])}")
    if fallos:
        print(f"FALLOS: {len(fallos)}")
        for f in fallos[:200]:
            print("  ✗", f)
        sys.exit(1)
    print("Todo coincide: 0 fallos.")


if __name__ == "__main__":
    main()
