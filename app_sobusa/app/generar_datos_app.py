# -*- coding: utf-8 -*-
"""Genera app/datos_app.js (window.DATOS_APP) y app/DATOS.md para la app «Sobusa Despacho».

Cada cifra se lee de su archivo de resultados con una clave que se puede volver a leer: ningún valor está escrito
a mano. Los metadatos de cada cifra (qué es, unidad, experimento, revisión) salen de app/inventario_cifras.json
(el contrato de ids) y la ficha de los dos modelos, de app/ficha_modelos.json. app/verificar_datos_app.py relee
cada cifra con código propio y compara.

Uso (desde la carpeta del proyecto, sin red; tarda menos de un minuto):
    PYTHONIOENCODING=utf-8 python app/generar_datos_app.py

Forma de cada cifra en pantallas.<pantalla>.<id>:
    {valor, unidad, decimales, archivo, clave, experimento, verificado, revision, que_es, tipo, nota?, <extras>?,
     origen: [[ruta dentro de la cifra, referencia], ...]}
Las series por hora y por día van como {columnas, filas} en lugar de valor. La «referencia» dice de dónde se lee
cada parte (DATOS.md explica la gramática de las claves).
"""
import base64
import csv
import datetime as dt
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True
APP = Path(__file__).resolve().parent
PROY = APP.parent
SALIDA_JS = APP / "datos_app.js"
SALIDA_MD = APP / "DATOS.md"
VERSION = 1
LIMITE_BYTES = 3 * 1024 * 1024
INV = json.loads((APP / "inventario_cifras.json").read_text(encoding="utf-8"))
FICHA = json.loads((APP / "ficha_modelos.json").read_text(encoding="utf-8"))

PANTALLAS = ["inicio", "demanda", "modelo", "horario", "despacho", "ciudad", "resultado", "piloto", "metodo"]
NOMBRE_PANTALLA = {"Inicio": "inicio", "Demanda": "demanda", "Modelo": "modelo", "Horario": "horario", "Despacho": "despacho",
                   "Ciudad": "ciudad", "Resultado": "resultado", "Piloto": "piloto", "Método": "metodo"}
META_INV = {}
for _p in INV["pantallas"]:
    for _c in _p["cifras"]:
        META_INV[_c["id"]] = (NOMBRE_PANTALLA[_p["pantalla"]], _c)

# Marcas de revisión corregidas tras la revisión de cifras de la app (prevalecen sobre las del inventario).
# El revisor de simulacion_ahorro comprobó 20 filas (verificacion_contra_informe.csv): solo esas cifras llevan «sí».
_SIN_FILA = ("Sin fila propia en simulacion_ahorro/resultados/verificacion_contra_informe.csv (sus 20 filas no la incluyen); "
             "costos/README.md §11 (06-10-2026): revisión adversarial del archivo, pero el revisor no volvió a correr el optimizador")
_BT_NO = ("Sin revisor independiente: la corrida vigente del backtest (13-10-2026, plan con costos con fuente) reusa el código de la "
          "corrida que sí revisó un revisor independiente (sistema_tiempo_real/README.md §7, 6-oct-2026, plan con los supuestos de D5), "
          "pero no se volvió a revisar; verificar_plan.py (comprobación del autor) reproduce el plan hora a hora")
_P1_NO = ("Sin revisor independiente: la actualización con costos con fuente (06-10-2026) solo tiene la comprobación del propio autor "
          "(validacion_costos_fuente.json: todas las horas iguales al MILP de referencia, HiGHS = CBC)")
CONF = {
    "inicio_salidas_dia_plan": ("sí", "simulacion_ahorro/README.md «Verificación independiente» (07-10-2026): "
                                      "verificacion_contra_informe.csv reproduce las salidas por día del plan (fila 'b: salidas por día', dif. ≤ 6e-15)"),
    "inicio_buses_hora_plan": ("parcial", "Los buses-hora por día no tienen fila propia: el revisor de simulacion_ahorro solo reprodujo el total anual "
                                          "('b: buses-hora ahorrados al año' en verificacion_contra_informe.csv); " + _SIN_FILA.split("; ", 1)[1]),
    "inicio_espera_plan": ("parcial", _SIN_FILA),
    "inicio_sobrecapacidad_plan": ("parcial", _SIN_FILA),
    "resultado_d5_reoptimizado": ("parcial", "Por columna y por corrida: las filas a y b de simulacion_ahorro/resultados/verificacion_contra_informe.csv "
                                             "reproducen buses-hora y km ahorrados al año, pasajeros en riesgo por día, los tres saldos y (en b) las salidas "
                                             "por día (07-10-2026, dif. ≤ 6e-15); las demás columnas y las demás corridas no tienen comprobación "
                                             "independiente (el revisor de costos no volvió a correr el optimizador). «verificado_campos» dice cuál es cuál."),
    "despacho_pantalla_7_30": ("no", "La consola v2 la verificó un revisor independiente (07-10-2026); los datos del 13-10 que muestra no tuvieron revisor"),
}
for _i in ("inicio_backtest_plan_vs_oraculo", "despacho_dia_ejemplo", "despacho_backtest_muestra", "despacho_decision_vs_oraculo_h7",
           "despacho_decision_vs_oraculo_h4", "despacho_nowcast_wape", "despacho_cobertura_intervalo", "despacho_alertas",
           "despacho_metodo_solucion", "despacho_guarda_datos", "despacho_simulador_d6"):
    CONF[_i] = ("no", _BT_NO)
for _i in ("horario_tabla_9_combinaciones", "horario_dia_promedio_2025", "horario_dia_promedio_supuestos", "horario_frase",
           "inicio_salidas_hora_cra54_laboral", "horario_dia_tipico_por_hora"):
    CONF[_i] = ("no", _P1_NO)

# Cifras del inventario que no tienen clave en ningún archivo de resultados (solo aparecen en un README o se calculan
# en vivo en una página): quedan fuera y se listan en DATOS.md.
AUSENTES = {
    "despacho_latencias": "Solo en sistema_tiempo_real/README.md, sección 7: no hay clave en resultados.json.",
    "ciudad_cobertura_trayectorias": "Los porcentajes solo están en el README («Vista 3D»); rutas.js trae los trazados, no la cobertura.",
    "ciudad_alertas_3jun_0730": "La página la calcula en vivo desde las posiciones de los buses; no hay clave guardada.",
}

# ---------------------------------------------------------------------------------------------------------------
# Lectura de archivos (con caché)
# ---------------------------------------------------------------------------------------------------------------
_CACHE = {}


def _numero_csv(texto, coma_decimal):
    t = texto.strip()
    if t == "":
        return None
    if t in ("True", "False"):
        return t == "True"
    try:
        v = float(t.replace(",", ".") if coma_decimal else t)
    except ValueError:
        return texto
    return int(v) if v.is_integer() and abs(v) < 1e15 else v


def leer(rel):
    """Devuelve el contenido de un archivo del proyecto: JSON, objeto de un .js de datos, filas de un CSV, DataFrame o texto."""
    if rel in _CACHE:
        return _CACHE[rel]
    ruta = PROY / rel
    suf = ruta.suffix.lower()
    if suf == ".json":
        obj = json.loads(ruta.read_text(encoding="utf-8"))
    elif suf == ".js":
        s = ruta.read_text(encoding="utf-8")
        m = re.search(r'=\s*"(H4sI[A-Za-z0-9+/=]+)"', s)  # día del replay: gzip + base64 (replay/ESQUEMA.md)
        if m:
            obj = json.loads(gzip.decompress(base64.b64decode(m.group(1))))
        else:
            m = re.search(r"window\.\w+\s*=\s*", s)
            obj, _ = json.JSONDecoder().raw_decode(s, m.end())
    elif suf == ".csv":
        texto = ruta.read_text(encoding="utf-8-sig")
        cab = texto.splitlines()[0]
        sep = ";" if cab.count(";") > cab.count(",") else ","
        lector = csv.reader(texto.splitlines(), delimiter=sep)
        filas = list(lector)
        cols = [c if c != "" else "_" for c in filas[0]]
        obj = [{c: _numero_csv(v, sep == ";") for c, v in zip(cols, f)} for f in filas[1:] if f]
    elif suf == ".parquet":
        obj = pd.read_parquet(ruta)
    else:
        obj = ruta.read_text(encoding="utf-8")
    _CACHE[rel] = obj
    return obj


# ---------------------------------------------------------------------------------------------------------------
# Claves: gramática de rutas dentro de un archivo
#   a.b.c            claves de diccionario (sin punto ni corchetes)
#   ["con espacios.o puntos"]   clave entre comillas
#   [3]  [-1]        índice de lista;  [13:16] tramo de lista
#   [*]              todos los elementos (lo que sigue se aplica a cada uno)
#   [k=v&k2=v2]      el único elemento de la lista que cumple; con * al final, todos los que cumplen
# En un CSV el archivo es la lista de filas (columna sin nombre = «_»).
# ---------------------------------------------------------------------------------------------------------------
_TOKEN = re.compile(r'\["((?:[^"\\]|\\.)*)"\]|\[(-?\d+)\]|\[(-?\d*):(-?\d*)\]|(\[\*\])|\[([^\[\]]*?=[^\[\]]*)\](\*?)|\.?([^.\[\]]+)')


def _tokens(clave):
    out, pos = [], 0
    while pos < len(clave):
        m = _TOKEN.match(clave, pos)
        if not m or m.end() == pos:
            raise ValueError(f"clave mal formada en la posición {pos}: {clave}")
        if m.group(1) is not None:
            out.append(("k", json.loads('"' + m.group(1) + '"')))
        elif m.group(2) is not None:
            out.append(("i", int(m.group(2))))
        elif m.group(3) is not None or m.group(4) is not None:
            a, b = m.group(3), m.group(4)
            out.append(("s", (int(a) if a else None, int(b) if b else None)))
        elif m.group(5):
            out.append(("*", None))
        elif m.group(6) is not None:
            conds = [tuple(x.split("=", 1)) for x in m.group(6).split("&")]
            out.append(("f*" if m.group(7) else "f", conds))
        else:
            out.append(("k", m.group(8)))
        pos = m.end()
    return out


def _igual(valor, texto):
    if valor is None:
        return texto in ("", "None", "null")
    if isinstance(valor, bool):
        return str(valor) == texto
    if isinstance(valor, (int, float)):
        try:
            return abs(float(texto) - float(valor)) < 1e-9
        except ValueError:
            return False
    return str(valor) == texto


def _aplicar(obj, toks, clave):
    if not toks:
        return obj
    tipo, arg = toks[0]
    resto = toks[1:]
    if tipo == "k":
        if not isinstance(obj, dict) or arg not in obj:
            raise KeyError(f"no está la clave {arg!r} en {clave}")
        return _aplicar(obj[arg], resto, clave)
    if tipo == "i":
        return _aplicar(obj[arg], resto, clave)
    if tipo == "s":
        return _aplicar(obj[arg[0]:arg[1]], resto, clave)
    if tipo == "*":
        return [_aplicar(e, resto, clave) for e in obj]
    hallados = [e for e in obj if all(k in e and _igual(e[k], v) for k, v in arg)]
    if tipo == "f*":
        if not hallados:
            raise KeyError(f"ninguna fila cumple el filtro en {clave}")
        return [_aplicar(e, resto, clave) for e in hallados]
    if len(hallados) != 1:
        raise KeyError(f"{len(hallados)} filas cumplen el filtro (se espera 1) en {clave}")
    return _aplicar(hallados[0], resto, clave)


def _op(valor, op):
    if op is None:
        return valor
    if op == "suma":
        return sum(v for v in valor if v is not None)
    if op == "media":
        xs = [v for v in valor if v is not None]
        return sum(xs) / len(xs)
    if op == "n":
        return len(valor)
    if op == "max":
        return max(valor)
    if op == "min":
        return min(valor)
    if op == "claves":
        return list(valor.keys())
    if op == "conteo":
        return dict(Counter(valor))
    if op == "enteros":
        return [int(x) for x in str(valor).split()]
    if op == "positivos":
        return sum(1 for v in valor if v is not None and v > 0)
    raise ValueError(f"operación desconocida {op}")


def _escalar(v, x):
    if x is None:
        return v
    if isinstance(v, list):
        return [_escalar(e, x) for e in v]
    if isinstance(v, dict):
        return {k: _escalar(e, x) for k, e in v.items()}
    return v * x if isinstance(v, (int, float)) and not isinstance(v, bool) else v


# ---------------------------------------------------------------------------------------------------------------
# Referencias: de dónde sale cada parte de una cifra
# ---------------------------------------------------------------------------------------------------------------
class Ref(dict):
    pass


def R(a, c, op=None, x=None, d=None):
    """Valor en el archivo a con la clave c; op opcional (suma, media, n, max, min, claves, conteo, enteros, positivos); x = factor."""
    r = Ref(t="r", a=a, c=c)
    if op:
        r["op"] = op
    if x is not None:
        r["x"] = x
    if d is not None:
        r["d"] = d
    return r


def PQ(a, filtro, col, por=None, op="suma", d=1, parte=None):
    """Parquet: filtra (igualdad por columna), agrupa por las columnas de «por» (en orden ascendente) y suma col.
    op = «suma» (lista de sumas por grupo, o un total sin «por») o «grupos» (la columna «parte» de las claves de grupo)."""
    r = Ref(t="pq", a=a, filtro=filtro, col=col, por=por or [], op=op, d=d)
    if parte is not None:
        r["parte"] = parte
    return r


def MD(a, patron, seccion=None, todos=False):
    """Texto de un Markdown: el grupo 1 de la expresión (con todos=True, la lista de coincidencias), dentro de la
    sección que empieza con la línea «seccion» si se da. Se verifica que el texto esté tal cual en el archivo."""
    r = Ref(t="md", a=a, patron=patron)
    if seccion:
        r["seccion"] = seccion
    if todos:
        r["todos"] = True
    return r


def FO(expr, **v):
    """Fórmula aritmética sobre otras referencias (por ejemplo, ahorro = costo real − costo del plan)."""
    return Ref(t="f", expr=expr, v=v)


def CAL(medida, tipo=None):
    """Recorre los 353 archivos de calles: «negativos» = días con saldo conservador < 0 (real.costo_Mcop − plan.costo_Mcop
    − plan.pasajes_perdidos_Mcop de resumen.dia); «dias» = días leídos; tipo = tipo de día del índice del replay."""
    r = Ref(t="calles", a="sistema_tiempo_real/replay/dias/calles/", medida=medida)
    if tipo:
        r["tipo"] = tipo
    return r


def _seccion_md(texto, seccion):
    lineas = texto.splitlines()
    for i, l in enumerate(lineas):
        if l.strip() == seccion.strip():
            nivel = len(l) - len(l.lstrip("#"))
            fin = len(lineas)
            for j in range(i + 1, len(lineas)):
                lj = lineas[j]
                if lj.startswith("#") and (len(lj) - len(lj.lstrip("#"))) <= nivel:
                    fin = j
                    break
            return "\n".join(lineas[i:fin])
    raise KeyError(f"no está la sección {seccion}")


def _calles():
    if "_calles" in _CACHE:
        return _CACHE["_calles"]
    ind = leer("sistema_tiempo_real/replay/dias/indice.js")
    tipo = {d["fecha"]: d["tipo_dia"] for d in ind["dias"]}
    out = []
    for f in sorted((PROY / "sistema_tiempo_real/replay/dias/calles").glob("2025-*.js")):
        dia = leer(f"sistema_tiempo_real/replay/dias/calles/{f.name}")["resumen"]["dia"]
        saldo = dia["real"]["costo_Mcop"] - dia["plan"]["costo_Mcop"] - dia["plan"]["pasajes_perdidos_Mcop"]
        out.append((f.stem, tipo[f.stem], saldo))
        _CACHE.pop(f"sistema_tiempo_real/replay/dias/calles/{f.name}", None)
    _CACHE["_calles"] = out
    return out


def resolver(ref):
    t = ref["t"]
    if t == "r":
        v = _aplicar(leer(ref["a"]), _tokens(ref["c"]), ref["c"])
        v = _op(v, ref.get("op"))
        return _escalar(v, ref.get("x"))
    if t == "pq":
        df = leer(ref["a"])
        for k, v in ref["filtro"].items():
            col = df[k]
            if str(col.dtype).startswith("datetime"):
                df = df[col == pd.Timestamp(v)]
            else:
                df = df[col == v]
        if df.empty:
            raise KeyError(f"filtro vacío en {ref['a']}")
        if not ref["por"]:
            return float(df[ref["col"]].sum()) if ref["op"] == "suma" else df[ref["col"]].tolist()
        g = df.groupby(ref["por"], sort=True)[ref["col"]].sum() if ref["op"] != "grupos" else df.groupby(ref["por"], sort=True).size()
        if ref["op"] == "grupos":
            def fmt(x):
                if hasattr(x, "strftime"):
                    return x.strftime("%Y-%m-%d")
                if isinstance(x, (int, float)) and float(x).is_integer():
                    return int(x)
                return str(x)
            parte = ref.get("parte", 0)
            return [fmt(k[parte]) if isinstance(k, tuple) else fmt(k) for k in g.index]
        return [float(x) for x in g.values]
    if t == "md":
        texto = leer(ref["a"])
        if ref.get("seccion"):
            texto = _seccion_md(texto, ref["seccion"])
        if ref.get("todos"):
            return [m.strip() for m in re.findall(ref["patron"], texto, re.M)]
        m = re.search(ref["patron"], texto, re.M)
        if not m:
            raise KeyError(f"no se encontró el texto en {ref['a']}: {ref['patron']}")
        return m.group(1).strip()
    if t == "f":
        vals = {k: resolver(r) for k, r in ref["v"].items()}
        return eval(ref["expr"], {"__builtins__": {}}, vals)  # noqa: S307 (expresión aritmética escrita en este archivo)
    if t == "calles":
        filas = [f for f in _calles() if not ref.get("tipo") or f[1] == ref["tipo"]]
        return len(filas) if ref["medida"] == "dias" else sum(1 for f in filas if f[2] < 0)
    raise ValueError(t)


def redondear(v, d=None):
    """Redondea para guardar: d decimales si se da; si no, 2 decimales desde 1.000 y 6 cifras significativas por debajo.
    Los enteros quedan enteros."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, int):
            return v
        if v != v:
            return None
        r = round(v, d) if d is not None else (round(v, 2) if abs(v) >= 1000 else float(f"{v:.6g}"))
        return int(r) if float(r).is_integer() and abs(r) < 1e15 else r
    if isinstance(v, list):
        return [redondear(e, d) for e in v]
    if isinstance(v, dict):
        return {k: redondear(e, d) for k, e in v.items()}
    return v


# ---------------------------------------------------------------------------------------------------------------
# Construcción de cifras
# ---------------------------------------------------------------------------------------------------------------
DATOS = {p: {} for p in PANTALLAS}
NUEVOS = {}


def _construir(arbol, ruta, origen):
    if isinstance(arbol, Ref):
        try:
            v = redondear(resolver(arbol), arbol.get("d"))
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"Error en {ruta}: {dict(arbol)} · {type(e).__name__}: {e}") from e
        origen.append([ruta, dict(arbol)])
        return v
    if isinstance(arbol, dict):
        return {k: _construir(e, ruta + [k], origen) for k, e in arbol.items()}
    if isinstance(arbol, list):
        return [_construir(e, ruta + [i], origen) for i, e in enumerate(arbol)]
    raise TypeError(f"valor escrito a mano en {ruta}: {arbol!r}")


def _refs_planas(ref):
    if ref["t"] == "f":
        out = []
        for r in ref["v"].values():
            out += _refs_planas(r)
        return out
    return [ref]


def _texto_clave(r):
    if r["t"] == "r":
        return r["c"] + (f" → {r['op']}" if r.get("op") else "") + (f" × {r['x']:g}" if r.get("x") is not None else "")
    if r["t"] == "pq":
        filtro = ", ".join(f"{k} = {v}" for k, v in r["filtro"].items())
        por = (" por " + ", ".join(r["por"])) if r["por"] else ""
        return f"{r['op']} de {r['col']} [{filtro}]{por}"
    if r["t"] == "md":
        return (r.get("seccion", "") + " · " if r.get("seccion") else "") + "texto: /" + r["patron"] + "/"
    if r["t"] == "calles":
        return "resumen.dia de cada archivo AAAA-MM-DD.js: " + r["medida"] + (f" ({r['tipo']})" if r.get("tipo") else "")
    return ""


def _decimales(unidad, valor):
    u = (unidad or "").lower()
    if not isinstance(valor, (int, float)) or isinstance(valor, bool):
        return 0
    if "%" in u or "puntos" in u or "β" in u or "beta" in u:
        return 2
    if "min" in u or "m cop" in u:
        return 1
    if isinstance(valor, int) or abs(valor) >= 100:
        return 0
    return 2


def C(id_, valor=None, extra=None, dec=None, unidad=None, nota=None, pantalla=None, serie=None, meta=None):
    """Registra una cifra. valor: árbol de Ref; extra: campos adicionales al nivel de la cifra (también Ref);
    serie: {"columnas": [...], "refs": {columna: Ref que devuelve la lista}} para series tabulares."""
    inv = META_INV.get(id_)
    if inv:
        pant, m = inv
        conf = m.get("confianza", {})
        base = {"que_es": m.get("que_es", ""), "tipo": m.get("tipo", "cifra"), "unidad": m.get("unidad", ""),
                "experimento": m.get("experimento", ""), "verificado": conf.get("verificado_independiente", "no"),
                "revision": conf.get("donde", "")}
        if m.get("interruptor"):
            base["interruptor"] = m["interruptor"]
        if m.get("nota"):
            base["nota"] = m["nota"]
    else:
        if not meta:
            raise KeyError(f"{id_} no está en el inventario y no trae metadatos")
        pant = pantalla
        base = dict(meta)
        NUEVOS[id_] = pant
    if id_ in CONF:
        base["verificado"], base["revision"] = CONF[id_]
    pant = pantalla or pant
    origen = []
    cifra = {}
    if serie is not None:
        cols = serie["columnas"]
        listas = {c: _construir(serie["refs"][c], ["columna", c], origen) for c in cols}
        n = len(listas[cols[0]])
        if any(len(v) != n for v in listas.values()):
            raise ValueError(f"{id_}: columnas de distinto largo")
        cifra["columnas"] = cols
        cifra["filas"] = [[listas[c][i] for c in cols] for i in range(n)]
    else:
        cifra["valor"] = _construir(valor, ["valor"], origen)
    for k, r in (extra or {}).items():
        cifra[k] = _construir(r, [k], origen)
    if unidad is not None:
        base["unidad"] = unidad
    if nota:
        base["nota"] = (base.get("nota", "") + " " + nota).strip()
    planas = [r for _, ref in origen for r in _refs_planas(ref)]
    archivos = []
    for r in planas:
        if r["a"] not in archivos:
            archivos.append(r["a"])
    claves = []
    for r in planas:
        t = (r["a"] + ": " if len(archivos) > 1 else "") + _texto_clave(r)
        if t not in claves:
            claves.append(t)
    clave = "; ".join(claves[:6]) + (f"; … ({len(claves)} claves)" if len(claves) > 6 else "")
    v0 = cifra.get("valor")
    out = {"valor": v0} if "valor" in cifra else {}
    out.update({k: v for k, v in cifra.items() if k != "valor"})
    u = base.pop("unidad")
    out.update({
        "unidad": u,
        "decimales": dec if dec is not None else _decimales(u, v0),
        "archivo": "; ".join(archivos),
        "clave": clave,
    })
    out.update(base)
    if len(archivos) > 1:
        out["archivos"] = archivos
    out["origen"] = origen
    if id_ in DATOS[pant] or any(id_ in DATOS[p] for p in PANTALLAS):
        raise KeyError(f"id repetido: {id_}")
    DATOS[pant][id_] = out
    return out


# ---------------------------------------------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------------------------------------------
E11 = "experimentos/E11_modelo_mejorado/resultados.json"
E11T = "experimentos/E11_modelo_mejorado/tabla_variantes.csv"
E11S = "experimentos/E11_modelo_mejorado/seleccion.json"
E11M = "experimentos/E11_modelo_mejorado/modelos/metadatos.json"
E11P = "experimentos/E11_modelo_mejorado/predicciones_2025.parquet"
E11R = "experimentos/E11_modelo_mejorado/README.md"
E12 = "experimentos/E12_comparacion_modelos/resultados.json"
E12R = "experimentos/E12_comparacion_modelos/ranking.csv"
E12T = "experimentos/E12_comparacion_modelos/tabla_modelos.csv"
E12H = "experimentos/E12_comparacion_modelos/resultados/hibrido_V4_chronos2cov.json"
E12M = "experimentos/E12_comparacion_modelos/modelos_hibrido/metadatos_pronostico_2026_enero_hibrido.json"
E12E = "experimentos/E12_comparacion_modelos/modelos_hibrido/emulacion_produccion_2025.json"
E12P = "experimentos/E12_comparacion_modelos/predicciones/hibrido_V4_chronos2cov.parquet"
E12S = "experimentos/E12_comparacion_modelos/pronostico_2026_enero_hibrido_semanal.csv"
E12MD = "experimentos/E12_comparacion_modelos/README.md"
E13 = "experimentos/E13_limpieza_datos/resultados.json"
E1 = "experimentos/E1_lgbm_salida/resultados.json"
E3 = "experimentos/E3_cuantiles_decision/resultados.json"
E5 = "experimentos/E5_plantillas/resumen_wape.csv"
E6 = "experimentos/E6_por_ruta/resultados.json"
E7 = "experimentos/E7_elasticidad/resultados.json"
E8 = "experimentos/E8_validacion_2026/resultados.json"
E8T = "experimentos/E8_validacion_2026/tabla_2026_vs_2025.csv"
E8E = "experimentos/E8_validacion_2026/tabla_errores_modelos.csv"
E9 = "experimentos/E9_clima/resultados.json"
E9D = "experimentos/E9_clima/desvio_demanda_por_lluvia.csv"
E9C = "experimentos/E9_clima/ciclo_y_demanda_por_intensidad.csv"
E10 = "experimentos/E10_dias_atipicos/resultados.json"
D1 = "experimentos/D1_optimizacion/resultados.json"
D2 = "experimentos/D2_flota/resultados.json"
D5 = "experimentos/D5_optimizacion_milp/resultados.json"
D5E = "experimentos/D5_optimizacion_milp/escenarios.csv"
D5H = "experimentos/D5_optimizacion_milp/horario_recomendado.csv"
D6 = "experimentos/D6_simulador/escenarios_resumen.csv"
P1 = "experimentos/P1_planificador/resultados.json"
P1V = "experimentos/P1_planificador/validacion_costos_fuente.json"
P2 = "experimentos/P2_piloto_beta/resultados.json"
P2A = "experimentos/P2_piloto_beta/ejemplo_piloto_sintetico.analisis.csv"
P2P = "experimentos/P2_piloto_beta/planilla_piloto.csv"
P2MD = "experimentos/P2_piloto_beta/README.md"
PROT = "experimentos/protocolo_evaluacion.md"
PLAN = "planificador_datos.js"
DASH = "dashboard_datos.js"
BEQ = "costos/resultados/beta_equilibrio.csv"
REOPT = "costos/resultados/d5_reoptimizado.csv"
CPP = "costos/resultados/costos_para_planificador.json"
CU = "costos/resultados/costos_unitarios.json"
CRS = "costos/resultados/resumen.json"
AHO = "costos/resultados/ahorros_por_escenario.csv"
LB = "costos/resultados/linea_base_2025.csv"
TOR = "costos/resultados/tornado_D5.csv"
VEX = "costos/resultados/verificacion_excel.csv"
SRS = "simulacion_ahorro/resultados/resumen_simulacion.json"
SPF = "simulacion_ahorro/resultados/simulacion_por_fecha.csv"
SPM = "simulacion_ahorro/resultados/simulacion_por_mes.csv"
SSB = "simulacion_ahorro/resultados/sensibilidad_beta.csv"
SCR = "simulacion_ahorro/resultados/conductores_resumen.json"
SVI = "simulacion_ahorro/resultados/verificacion_contra_informe.csv"
RFE = "Entrega1/tablas/resumen_fe.json"
E1MD = "Entrega1/README.md"
INVD = "Entrega1/figuras_etl/inventario_datos.csv"
IND = "sistema_tiempo_real/replay/dias/indice.js"
DIA = "sistema_tiempo_real/replay/dias/2025-06-03.js"
C3 = "sistema_tiempo_real/replay/dias/calles/2025-06-03.js"
CRES = "sistema_tiempo_real/replay/dias/calles/resumen_2025.js"
BT = "sistema_tiempo_real/backtest/resultados.json"
BTD = "sistema_tiempo_real/backtest/decision_vs_oraculo.csv"
BTN = "sistema_tiempo_real/backtest/nowcast_wape.csv"
BTV = "sistema_tiempo_real/backtest/verificacion_plan.csv"
INFORME = "documentos/informe_resultados.md"
README = "README.md"

RUTAS = ["SILENCIO", "CRA 54", "CL 72"]
TIPOS = ["Laboral", "Sábado", "Domingo/festivo"]
HIB = "hibrido_V4_chronos2cov"
CORR_B = "D5 costos nuevos, pago por hora, e=0,5"
S0 = "ruta=Todas&tipo_dia=Todos&escenario=S0 oferta real"
REV_BT = " · Corrida vigente del backtest: 13-10-2026 (plan con costos con fuente), sin revisor independiente."


def ic(a, base):
    """{dif, ic_inf, ic_sup, meses_mejor} de un objeto de comparación con esos campos."""
    return {"dif": R(a, base + ".dif_pp"), "ic_inf": R(a, base + ".ic_inf"), "ic_sup": R(a, base + ".ic_sup")}


def ic_meses(a, base):
    d = ic(a, base)
    d["meses_mejor"] = R(a, base + ".meses_mejor")
    return d


# ===============================================================================================================
# INICIO · ¿Qué proponemos?
# ===============================================================================================================
C("inicio_error_regla_manual", R(E11, "horizontes.B1_H7.global_.WAPE"), dec=2)
C("inicio_error_modelo_final", R(E11, "horizontes.SEL_H7.global_.WAPE"), dec=2)
C("inicio_error_hibrido", R(E12, f"produccion.costos.{HIB}.WAPE_2025"), dec=2)
C("inicio_mejora_hibrido_2025", R(E12, f"produccion.costos.{HIB}.dif_2025[0]"), dec=2,
  extra={"ic_inf": R(E12, f"produccion.costos.{HIB}.dif_2025[1]"), "ic_sup": R(E12, f"produccion.costos.{HIB}.dif_2025[2]"),
         "meses_mejor": R(E12H, "vs_V4.meses_mejor"), "meses": R(E12H, "vs_V4.dif_por_mes_pp", op="n")})
_REF24 = "validacion_2024.referencia_validacion_2024_hibrido"
C("inicio_mejora_hibrido_2024", R(E12, _REF24 + ".dif_pp"), dec=2,
  extra={"ic_inf": R(E12, _REF24 + ".ic_inf"), "ic_sup": R(E12, _REF24 + ".ic_sup"), "meses_mejor": R(E12, _REF24 + ".meses_mejor"),
         "meses": R(E12, f"validacion_2024.candidatos.{HIB}.dif_por_mes_pp", op="n"),
         "wape_hibrido": R(E12, _REF24 + ".hibrido.WAPE"), "wape_V4": R(E12, _REF24 + ".V4.WAPE")})
C("inicio_error_e1", R(E11, "horizontes.V0_H7.global_.WAPE"), dec=2)
_D2C = 'por_ruta["CRA 54"].diario.Laboral.'
C("inicio_salidas_cra54_laboral_hoy", R(D2, _D2C + "salidas"), dec=0)
C("inicio_salidas_cra54_laboral_necesarias", R(D2, _D2C + "salidas_nec"), dec=0)
C("inicio_salidas_sobran_cra54", R(D2, _D2C + "salidas_exceso"), dec=0)
C("inicio_salidas_faltan_cra54", R(D2, _D2C + "salidas_deficit"), dec=0)
C("inicio_beta", R(E7, "sintesis.beta_central"), dec=2)
C("inicio_beta_rango", {"inf": R(E7, "sintesis.beta_rango[0]"), "sup": R(E7, "sintesis.beta_rango[1]")}, dec=2)
C("inicio_beta_hora", R(E7, "diseno_A[0].beta_vi"), dec=2,
  extra={"ic_inf": R(E7, "diseno_A[0].ic95_vi[0]"), "ic_sup": R(E7, "diseno_A[0].ic95_vi[1]")})
C("inicio_beta_derrame", {"bruto_pct": R(E7, "diseno_B.absorcion.Todas.num4", x=100),
                          "corregido_pct": R(E7, "diseno_B.absorcion.Todas.num4_corr", x=100),
                          "pax_esperados_viaje_fallido": R(E7, "diseno_B.absorcion.Todas.pax_esperados_viaje_fallido")}, dec=1)
C("inicio_beta_origen", R(E7, "clasificacion_viajes.fallas_reales"), dec=0,
  extra={"pct": R(E7, "clasificacion_viajes.pct_fallas_reales"), "viajes_registrados": R(E7, "clasificacion_viajes.viajes_registrados")})
C("inicio_beta_equilibrio_d5", R(BEQ, '[clave=D5]["pago por hora"]'), dec=2)
C("inicio_salidas_dia_hoy", R(D5E, f"[{S0}].salidas_dia"), dec=0)
C("inicio_salidas_dia_plan", R(REOPT, f"[corrida={CORR_B}].salidas_dia"), dec=0)
C("inicio_buses_hora_hoy", R(D5E, f"[{S0}].buses_hora_dia"), dec=0)
C("inicio_buses_hora_plan", R(REOPT, f"[corrida={CORR_B}].buses_hora_dia"), dec=0,
  extra={"delta_buses_hora_anual": R(REOPT, f"[corrida={CORR_B}].delta_buses_hora_anual")})
C("inicio_espera_hoy", R(D5E, f"[{S0}].espera_media_min"), dec=1)
C("inicio_espera_plan", R(REOPT, f"[corrida={CORR_B}].espera_media_min"), dec=1)
C("inicio_sobrecapacidad_hoy", R(D5E, f"[{S0}].pax_sobre_capacidad_dia"), dec=0)
C("inicio_sobrecapacidad_plan", R(REOPT, f"[corrida={CORR_B}].pax_sobre_capacidad_dia"), dec=0)
C("inicio_horas_fc_mayor_1", {"hoy": R(D5E, f"[{S0}].pct_horas_fc_mayor_1"), "plan": R(REOPT, f"[corrida={CORR_B}].pct_horas_fc_mayor_1")}, dec=1)
C("inicio_pax_riesgo_plan", R(REOPT, f"[corrida={CORR_B}].pax_perdidos_dia_central"), dec=0,
  extra={"bajo": R(REOPT, f"[corrida={CORR_B}].pax_perdidos_dia_bajo"), "alto": R(REOPT, f"[corrida={CORR_B}].pax_perdidos_dia_alto")})
C("inicio_pax_netos_simetrica", R(REOPT, f"[corrida={CORR_B}].pax_netos_dia_simetrico_beta070"), dec=0)
C("inicio_saldo_conservador", R(REOPT, f"[corrida={CORR_B}].neto_pago_hora_beta070_Mcop"), dec=0)
C("inicio_saldo_simetrico", R(REOPT, f"[corrida={CORR_B}].neto_simetrico_pago_hora_beta070_Mcop"), dec=0)
C("inicio_ahorro_operativo_plan", R(REOPT, f"[corrida={CORR_B}].ahorro_operativo_pago_hora_Mcop"), dec=0)
C("inicio_pax_dia_2025", R(D5, "complemento.pasajeros_dia_2025"), dec=0)
C("inicio_costo_bus_hora", R(CPP, "costo_bus_hora.central"), dec=0,
  extra={"bajo": R(CPP, "costo_bus_hora.bajo"), "alto": R(CPP, "costo_bus_hora.alto"), "exacto": R(CU, '["2026"].bus_hora_conductor')})
C("inicio_costo_km", R(CPP, "costo_km.central"), dec=0,
  extra={"bajo": R(CPP, "costo_km.bajo"), "alto": R(CPP, "costo_km.alto"), "exacto": R(CU, '["2026"].costo_km_evitable')})
C("inicio_tarifa_neta", R(CPP, "tarifa_neta_2026.central"), dec=0,
  extra={"bajo": R(CPP, "tarifa_neta_2026.bajo"), "alto": R(CPP, "tarifa_neta_2026.alto")})
C("inicio_demanda_por_anio", R(DASH, "kpis.pasajeros_por_anio"), dec=0)
_OA = 'objetivos_por_anio["{}"].{}'
C("inicio_caida_anual", {
    f"{a}_{t}": FO("(a / b - 1) * 100", a=R(RFE, _OA.format(a, t)), b=R(RFE, _OA.format(a - 1, t)))
    for a in (2024, 2025) for t in ("original", "corregido")}, dec=1, unidad="% frente al año anterior")
C("inicio_recorte_no_paga_d5", R(AHO, "[clave=D5].neto_pago_por_hora", x=1e-6), dec=0, unidad="M COP/año",
  extra={"bajo": R(AHO, "[clave=D5].neto_pago_por_hora_bajo", x=1e-6), "alto": R(AHO, "[clave=D5].neto_pago_por_hora_alto", x=1e-6)})
C("inicio_recorte_no_paga_s1", R(AHO, "[clave=S1].neto_pago_por_hora", x=1e-6), dec=0, unidad="M COP/año",
  extra={"bajo": R(AHO, "[clave=S1].neto_pago_por_hora_bajo", x=1e-6), "alto": R(AHO, "[clave=S1].neto_pago_por_hora_alto", x=1e-6)})
_DOM = "[ruta=Total&plan=a&tipo_dia=Domingo/festivo]*."
C("inicio_domingos_pagan", R(SPF, _DOM + "neto_hora", op="suma", x=1e-6), dec=0, unidad="M COP/año",
  extra={"por_dia_Mcop": R(SPF, _DOM + "neto_hora", op="media", x=1e-6), "dias": R(SPF, _DOM + "fecha", op="n"),
         "pax_riesgo_dia": R(SPF, _DOM + "pasajeros_en_riesgo", op="media")})
_T = "total.{}.total.{}"
_PP = {
    "ahorro_operacion_Mcop": FO("r - p", r=R(CRES, _T.format("real", "costo_Mcop")), p=R(CRES, _T.format("plan", "costo_Mcop"))),
    "pasajes_perdidos_Mcop": R(CRES, _T.format("plan", "pasajes_perdidos_Mcop")),
    "saldo_conservador_Mcop": FO("r - p - l", r=R(CRES, _T.format("real", "costo_Mcop")), p=R(CRES, _T.format("plan", "costo_Mcop")),
                                 l=R(CRES, _T.format("plan", "pasajes_perdidos_Mcop"))),
    "ganados_simetrico_pax": R(CRES, _T.format("plan", "ganados_simetrico")),
    "valor_ganados_Mcop": FO("g * t / 1e6", g=R(CRES, _T.format("plan", "ganados_simetrico")), t=R(CRES, "plan_meta.tarifa")),
    "saldo_simetrico_Mcop": FO("r - p - l + g * t / 1e6", r=R(CRES, _T.format("real", "costo_Mcop")), p=R(CRES, _T.format("plan", "costo_Mcop")),
                               l=R(CRES, _T.format("plan", "pasajes_perdidos_Mcop")), g=R(CRES, _T.format("plan", "ganados_simetrico")),
                               t=R(CRES, "plan_meta.tarifa")),
}
C("inicio_persona_a_persona_saldo", _PP, dec=1, extra={"dias": R(CRES, "dias")})
_RD = "resumen.dia.{}.{}"
C("inicio_hallazgo_3jun", {
    "salidas_real": R(C3, _RD.format("real", "salidas")), "salidas_validas_real": R(C3, _RD.format("real", "salidas_validas")),
    "salidas_plan": R(C3, _RD.format("plan", "salidas")), "salidas_programar": R(C3, _RD.format("plan", "salidas_programar")),
    "perdidos_beta": R(C3, _RD.format("plan", "perdidos_beta")), "perdidos_sin_bus": R(C3, _RD.format("plan", "perdidos_sin_bus")),
    "sobre_capacidad_real": R(C3, _RD.format("real", "sobre_capacidad")), "sobre_capacidad_plan": R(C3, _RD.format("plan", "sobre_capacidad")),
    "balance_dia_Mcop": FO("r - p - l", r=R(C3, _RD.format("real", "costo_Mcop")), p=R(C3, _RD.format("plan", "costo_Mcop")),
                           l=R(C3, _RD.format("plan", "pasajes_perdidos_Mcop"))),
    "pasajes_perdidos_Mcop": R(C3, _RD.format("plan", "pasajes_perdidos_Mcop")),
    "ahorro_operacion_Mcop": FO("r - p", r=R(C3, _RD.format("real", "costo_Mcop")), p=R(C3, _RD.format("plan", "costo_Mcop"))),
}, dec=0, extra={"dia": R(C3, "fecha")})
_BT7 = "[grupo=Todos&horas_desde=7&escenario={}].{}"
C("inicio_backtest_plan_vs_oraculo", {
    "plan_error_salidas_h": R(BTD, _BT7.format("Plan semanal (D5 con pronóstico a 7 días)", "error_abs_medio_salidas_hora")),
    "plan_pct_horas_exactas": R(BTD, _BT7.format("Plan semanal (D5 con pronóstico a 7 días)", "pct_horas_exactas")),
    "real_error_salidas_h": R(BTD, _BT7.format("Oferta real 2025 (S0)", "error_abs_medio_salidas_hora")),
    "real_pct_horas_exactas": R(BTD, _BT7.format("Oferta real 2025 (S0)", "pct_horas_exactas")),
    "motor_error_salidas_h": R(BTD, _BT7.format("Dinámico con nowcast (motor)", "error_abs_medio_salidas_hora")),
    "motor_pct_horas_exactas": R(BTD, _BT7.format("Dinámico con nowcast (motor)", "pct_horas_exactas")),
}, dec=2, extra={"dias": R(BTD, _BT7.format("Plan semanal (D5 con pronóstico a 7 días)", "dias"))}, nota=REV_BT.strip(" ·"))
_TP = "riesgo_costo.totales_piloto."
C("inicio_piloto_resumen", {
    "semanas": R(P2, "parametros.semanas_piloto"),
    "ee_simulado": R(P2, 'simulacion.ee_analitico_vs_empirico["recorte conjunta"].ee_empirico_simulacion'),
    "ee_analitico": R(P2, 'simulacion.ee_analitico_vs_empirico["recorte conjunta"].ee_analitico_2025'),
    "potencia_simulada": R(P2, "simulacion.resumen[escenario=principal&beta_verdadero=0.7&franja=recorte conjunta&estimador=VI (asignación)].potencia_beta_mayor_053"),
    "potencia_analitica": R(P2, 'potencia.diseno_propuesto["recorte conjunta"].potencia_070_vs_053_una_cola'),
    "pax_riesgo": R(P2, _TP + "pax_riesgo_piloto_beta070"),
    "pct_pax_anual_cra54": R(P2, _TP + "pax_riesgo_piloto_pct_pax_anual_cra54"),
    "saldo_min_Mcop": R(P2, _TP + "neto_total_piloto_Mcop_conservador"),
    "saldo_max_Mcop": R(P2, _TP + "neto_total_piloto_Mcop_simetrico"),
}, dec=2)
C("inicio_2026_mas_viajes", {"viajes_pct": R(E8T, "[_=TOTAL].var_viajes_2026_vs_2025_pct"), "subidas_pct": R(E8T, "[_=TOTAL].var_2026_vs_2025_pct")}, dec=1)
C("inicio_dias_gps_2025", R(IND, "meta.por_dia.previstos"), dec=0, extra={"sin_gps": R(IND, "sin_gps", op="n")})
_CV = "clasificacion_viajes."
C("inicio_cancelados_que_corrieron", {
    "canceladas_bandera": R(E7, _CV + "canceladas_bandera"), "canceladas_que_si_operaron": R(E7, _CV + "canceladas_que_si_operaron"),
    "pct": R(E7, _CV + "pct_canceladas_que_si_operaron"), "pasajeros": R(E7, _CV + "pasajeros_en_canceladas_operadas"),
    "pct_pasajeros_totales": R(E7, _CV + "pct_pasajeros_totales_en_canceladas_operadas")}, dec=0)
C("inicio_rutas", R(DASH, "meta.rutas"))
C("inicio_regla_manual_definicion", MD(PROT, r"^- \*\*B1 manual\*\*: (.+)$"))
C("inicio_equipo", MD(E1MD, r"^\| ([A-ZÁÉÍÓÚÑ][^|@ ]+(?: [^|@ ]+)+) \| [^|]*\|$", seccion="## Equipo", todos=True),
  nota="Solo los nombres: el generador no copia los correos de la tabla.")

# Serie por hora de CRA 54 laboral: hoy (mediana 2025), plan con costos con fuente (P1, juego por hora, e = 0,5) y D5 original.
_PJ = leer(PLAN)
_CAMPOS = _PJ["campos_hora"]


def _col_plan(ruta, tipo, campo):
    return R(PLAN, f'rutas["{ruta}"].tipos["{tipo}"].horas[*][{_CAMPOS.index(campo)}]')


def _x_p1(ruta, tipo, juego="hora", e=0.5, campo="x_planificador"):
    return R(P1V, f"casos[juego={juego}&elasticidad={e}&ruta={ruta}&tipo_dia={tipo}].{campo}", op="enteros")


C("inicio_salidas_hora_cra54_laboral", {
    "horas": _col_plan("CRA 54", "Laboral", "hora"),
    "hoy": _col_plan("CRA 54", "Laboral", "salidas_actuales"),
    "plan": _x_p1("CRA 54", "Laboral"),
    "d5_original": _col_plan("CRA 54", "Laboral", "solucion_D5"),
}, dec=0, pantalla="inicio", extra={
    "total_hoy": R(P1V, "casos[juego=hora&elasticidad=0.5&ruta=CRA 54&tipo_dia=Laboral].salidas_hoy"),
    "total_plan": R(P1V, "casos[juego=hora&elasticidad=0.5&ruta=CRA 54&tipo_dia=Laboral].salidas_plan")},
  meta={"que_es": "Salidas por hora de CRA 54 en un día laboral típico: hoy (mediana de 2025 por hora de salida), con el plan de costos con fuente (P1, conductor por hora, e = 0,5) y con D5 original (supuestos 60.000 / 1.500 / 3.000)",
        "tipo": "serie", "unidad": "salidas por hora", "experimento": "P1 (insumos de D5) y validacion_costos_fuente.py",
        "verificado": "parcial", "revision": "validacion_costos_fuente.json: 153 de 153 horas iguales al MILP de referencia; sin revisor independiente de la actualización del 06-10-2026",
        "interruptor": "hoy / modelo"})

# ===============================================================================================================
# DEMANDA · ¿Cuántos pasajeros habrá?
# ===============================================================================================================
_MOD = {"B1": "B1", "E1_V0": "V0", "E11_V4": "SEL"}
C("demanda_wape_por_ruta", dict(
    {m: {r: R(E11, f"horizontes.{h}_H7.por_ruta.{r}.WAPE") for r in RUTAS} for m, h in _MOD.items()},
    hibrido={r: R(E12H, f"por_ruta.{r}.WAPE") for r in RUTAS}), dec=2)
_VAR = {"B1": "B1_h7", "E1_V0": "V0_h7", "E11_V4": "V4_h7"}
C("demanda_wape_por_tipo_dia", dict(
    {m: {t: R(E11, f"variantes[clave={v}].metricas_por_tipo_dia.{t}.WAPE") for t in TIPOS} for m, v in _VAR.items()},
    hibrido={t: R(E12H, f"por_tipo_dia.{t}.WAPE") for t in TIPOS}), dec=2)
_FR = {"4-8 h": "4-8 h", "9-15 h": "9-15 h", "16-20 h": "16-21 h"}
C("demanda_wape_por_franja", dict(
    {m: {f: R(E11, f"variantes[clave={v}].metricas_por_franja.{fe}.WAPE") for f, fe in _FR.items()} for m, v in _VAR.items()},
    hibrido={f: R(E12H, f"por_franja.{f}.WAPE") for f in _FR}), dec=2)
C("demanda_wape_antelacion", {m: {str(h): R(E11, f"horizontes.{p}_H{h}.global_.WAPE") for h in (7, 14, 21, 28)} for m, p in _MOD.items()}, dec=2)
_G = "global."
C("demanda_hibrido_antelacion_emulacion", dict(
    {f"H{h}": {"hibrido": R(E12E, f"{_G}H{h}.WAPE_hibrido"), "V4": R(E12E, f"{_G}H{h}.WAPE_V4"),
               "semanas_mejor": R(E12E, f"{_G}H{h}.semanas_mejor"), "semanas": R(E12E, f"{_G}H{h}.semanas")} for h in (7, 14, 21, 28)},
    total={"hibrido": R(E12E, _G + "todas.WAPE_hibrido"), "V4": R(E12E, _G + "todas.WAPE_V4"),
           "semanas_mejor": R(E12E, _G + "todas.semanas_mejor"), "semanas": R(E12E, _G + "todas.semanas"),
           "dif": R(E12E, _G + "vs_V4_bootstrap_dias.dif_pp"), "ic_inf": R(E12E, _G + "vs_V4_bootstrap_dias.ic_inf"),
           "ic_sup": R(E12E, _G + "vs_V4_bootstrap_dias.ic_sup"), "origenes_mejor": R(E12E, _G + "vs_V4_bootstrap_dias.origenes_mejor"),
           "origenes": R(E12E, _G + "vs_V4_bootstrap_dias.dif_por_origen_pp", op="n")}), dec=2)
C("demanda_wape_h1", {"B1": R(E11, "variantes[clave=B1_h1].metricas_global.WAPE"), "E1_V0": R(E11, "variantes[clave=V0_h1].metricas_global.WAPE"),
                      "E11_V4": R(E11, "variantes[clave=V4_h1].metricas_global.WAPE")}, dec=2)


def _sesgo_pct(col):
    return FO("(p / r - 1) * 100", p=PQ(E11P, {"horizonte": 7}, col, op="suma", d=None), r=PQ(E11P, {"horizonte": 7}, "real", op="suma", d=None))


C("demanda_sesgo", {
    "E11_V4_pct": _sesgo_pct("prediccion"), "E11_V4_pax_franja": R(E11, "variantes[clave=V4_h7].metricas_global.sesgo"),
    "B1_pct": _sesgo_pct("pred_B1_manual"), "B1_pax_franja": R(E11, "variantes[clave=B1_h7].metricas_global.sesgo"),
    "E1_V0_pct": _sesgo_pct("pred_V0_E1"), "E1_V0_pax_franja": R(E11, "variantes[clave=V0_h7].metricas_global.sesgo"),
    "hibrido_pct": R(E12T, f"[modelo={HIB}].sesgo_pct")}, dec=2)
C("demanda_wape_total_diario", {"B1": R(E11T, "[variante=B1&horizonte=7].WAPE_total_diario"), "E1_V0": R(E11T, "[variante=V0&horizonte=7].WAPE_total_diario"),
                                "E11_V4": R(E11T, "[variante=V4&horizonte=7].WAPE_total_diario"), "hibrido": R(E12T, f"[modelo={HIB}].WAPE_total_diario")}, dec=2)
_DE = "verificacion_independiente.dias_especiales_h7."
C("demanda_festivos", {"modelo_E1": R(E1, _DE + "festivos_17_dias.lgbm"), "B1": R(E1, _DE + "festivos_17_dias.B1"),
                       "carnaval_modelo": R(E1, _DE + "carnaval_4_dias.lgbm"), "carnaval_B1": R(E1, _DE + "carnaval_4_dias.B1"),
                       "semana_santa_modelo": R(E1, _DE + "semana_santa_7_dias.lgbm"), "semana_santa_B1": R(E1, _DE + "semana_santa_7_dias.B1")}, dec=1)
_F7 = {"horizonte": 7}
C("demanda_serie_diaria_2025", serie={
    "columnas": ["ruta", "dia", "real", "B1", "E1_V0", "E11_V4", "hibrido"],
    "refs": {"ruta": PQ(E11P, _F7, "real", por=["ruta", "dia"], op="grupos", parte=0),
             "dia": PQ(E11P, _F7, "real", por=["ruta", "dia"], op="grupos", parte=1),
             "real": PQ(E11P, _F7, "real", por=["ruta", "dia"], d=0), "B1": PQ(E11P, _F7, "pred_B1_manual", por=["ruta", "dia"], d=0),
             "E1_V0": PQ(E11P, _F7, "pred_V0_E1", por=["ruta", "dia"], d=0), "E11_V4": PQ(E11P, _F7, "prediccion", por=["ruta", "dia"], d=0),
             "hibrido": PQ(E12P, _F7, "prediccion", por=["ruta", "dia"], d=0)}},
  extra={"total_2025": {"real": PQ(E11P, _F7, "real", op="suma", d=0), "B1": PQ(E11P, _F7, "pred_B1_manual", op="suma", d=0),
                        "E1_V0": PQ(E11P, _F7, "pred_V0_E1", op="suma", d=0), "E11_V4": PQ(E11P, _F7, "prediccion", op="suma", d=0),
                        "hibrido": PQ(E12P, _F7, "prediccion", op="suma", d=0)}},
  dec=0, unidad="pasajeros por día (suma de las 17 horas de salida)")
_FD = {"horizonte": 7, "dia": "2025-06-03"}
C("demanda_serie_hora_ejemplo", serie={
    "columnas": ["ruta", "hora", "real", "B1", "E1_V0", "E11_V4", "hibrido"],
    "refs": {"ruta": PQ(E11P, _FD, "real", por=["ruta", "hora"], op="grupos", parte=0),
             "hora": PQ(E11P, _FD, "real", por=["ruta", "hora"], op="grupos", parte=1),
             "real": PQ(E11P, _FD, "real", por=["ruta", "hora"]), "B1": PQ(E11P, _FD, "pred_B1_manual", por=["ruta", "hora"]),
             "E1_V0": PQ(E11P, _FD, "pred_V0_E1", por=["ruta", "hora"]), "E11_V4": PQ(E11P, _FD, "prediccion", por=["ruta", "hora"]),
             "hibrido": PQ(E12P, _FD, "prediccion", por=["ruta", "hora"])}},
  extra={"dia": R(DIA, "fecha")}, dec=0, unidad="pasajeros por hora de salida")
_S = "[*]."
C("demanda_pronostico_2026_enero", {
    "hibrido": R(E12S, _S + "pronostico", op="suma"), "E11_V4": R(E12S, _S + "pronostico_E11", op="suma"),
    "V4_sombra": R(E12S, _S + "pronostico_V4_sombra", op="suma"), "E8_ensamble": R(E12S, _S + "E8_ensamble_diario", op="suma"),
    "real_2025_alineado": R(E12S, _S + "real_2025_alineado", op="suma"),
    "hibrido_vs_E11_pct": FO("(h / e - 1) * 100", h=R(E12S, _S + "pronostico", op="suma"), e=R(E12S, _S + "pronostico_E11", op="suma")),
    "E11_vs_2025_pct": FO("(e / r - 1) * 100", e=R(E12S, _S + "pronostico_E11", op="suma"), r=R(E12S, _S + "real_2025_alineado", op="suma")),
    "hibrido_vs_2025_pct": FO("(h / r - 1) * 100", h=R(E12S, _S + "pronostico", op="suma"), r=R(E12S, _S + "real_2025_alineado", op="suma")),
}, dec=0, extra={"semanas": R(E12S, "[*]")})
_R25, _R24 = "resultados_2025.{}.corregido.global_.WAPE", "resultados_2024.{}.corregido.global_.WAPE"
_M13 = {"V4": "V4", "V4_reescalado": "V4_esc", "V4c_reentrenado": "V4c", "hibrido_V4c": "hib_V4c"}
C("demanda_objetivo_corregido", {
    "2025": {k: R(E13, _R25.format(v)) for k, v in _M13.items()},
    "2024": {k: R(E13, _R24.format(v)) for k, v in _M13.items()},
    "ganancia_V4c_vs_V4_reescalado_2025": ic_meses(E13, 'comparaciones_2025["corregido|V4_esc|V4c"]'),
    "ganancia_hibrido_vs_V4c_2025": ic_meses(E13, 'comparaciones_2025["corregido|V4c|hib_V4c"]')}, dec=2)
_FAC = "resultados_2025.{}.corregido.faciles.{}"
_M13b = {"V4": "V4", "V4_reescalado": "V4_esc", "V4c": "V4c", "hibrido_V4c": "hib_V4c"}
C("demanda_error_total_diario_corregido", {k: R(E13, _FAC.format(v, "total_diario_error_medio_pct")) for k, v in _M13b.items()}, dec=1)
C("demanda_horas_faltan_buses", {k: R(E13, _FAC.format(v, "buses_pct_horas_suboferta")) for k, v in _M13b.items()}, dec=1)
C("demanda_horas_buses_exactos", {k: R(E13, _FAC.format(v, "buses_pct_horas_exactas")) for k, v in _M13b.items()}, dec=1)
_O25 = 'objetivos_por_anio["2025"].'
C("demanda_pax_cancelados_corrieron_2025", {
    "pasajeros": R(RFE, _O25 + "pax_cancelados_corrieron"),
    "pct_del_corregido": FO("a / b * 100", a=R(RFE, _O25 + "pax_cancelados_corrieron"), b=R(RFE, _O25 + "corregido")),
    "corregido_sobre_original_pct": R(RFE, _O25 + "corregido_sobre_original_pct"), "total_corregido_2025": R(RFE, _O25 + "corregido"),
    "total_original_2025": R(RFE, _O25 + "original")}, dec=0)
_DIAS13 = {"algun_problema": "algun_problema", "mas_10pct_pax_en_cancelados_que_corrieron": "cancel_10", "atipicos_E10_no_calendario": "atipico_E10",
           "falla_registro_mas_10pct": "falla_registro_10", "fin_de_mes_sin_gps": "fin_mes", "calendario": "calendario"}
C("demanda_dias_con_problema_datos", {k: {"dias": R(E13, f"diagnostico.dias.{v}.dias"), "pct": R(E13, f"diagnostico.dias.{v}.pct_dias")}
                                      for k, v in _DIAS13.items()}, dec=1,
  extra={"textos": {k: R(E13, f"diagnostico.dias.{v}.texto") for k, v in _DIAS13.items() if v != "algun_problema"}})
_E8F = ["SILENCIO", "CRA 54", "CL 72", "TOTAL"]
C("demanda_2026_variacion", {
    "subidas_pct": {r: R(E8T, f"[_={r}].var_2026_vs_2025_pct") for r in _E8F},
    "viajes_pct": {r: R(E8T, f"[_={r}].var_viajes_2026_vs_2025_pct") for r in _E8F},
    "error_ENS_2026_pct": R(E8E, "[etapa=validacion_2026&calibracion=pred_cal&modelo=ENS_M2_M3_M4].error_total_pct"),
    "retroprueba_2025_error_pct": R(E8E, "[etapa=retroprueba_2025&calibracion=pred_cal&modelo=ENS_M2_M3_M4].error_total_pct")}, dec=1)
C("demanda_elasticidad_aparente_2026", R(E8, 'elasticidad_aparente_2026["SILENCIO+CL 72 vs CRA 54"]'), dec=2,
  extra={"por_par": R(E8, "elasticidad_aparente_2026")})
_LL = "[exposicion=hora o 3 previas (máximo)&clase=Moderada&ruta=Todas&tipo_dia=Todos&variable=pasajeros_total]."
C("demanda_lluvia", {
    "r2_variacion_diaria": R(E9, "variacion_explicada.diaria_vs_linea_base.r2"),
    "desvio_pax_lluvia_moderada_pct": R(E9D, _LL + "desvio"),
    "desvio_pax_lluvia_moderada_ic95": [R(E9D, _LL + "ic_inf"), R(E9D, _LL + "ic_sup")],
    "ciclo_pct_por_intensidad": {"intensidad": R(E9C, "[ruta=Todas]*.intensidad"), "desvio_ciclo_pct": R(E9C, "[ruta=Todas]*.desvio", d=2)},
    "mejor_variante": R(E9, "mejor_variante")}, dec=2)
C("demanda_correlacion_rutas", {
    "corr_SIL_CRA54": R(E6, "correlaciones.diaria_niveles[0][1]"), "corr_SIL_CL72": R(E6, "correlaciones.diaria_niveles[0][2]"),
    "corr_CRA54_CL72": R(E6, "correlaciones.diaria_niveles[1][2]"),
    "pct_var_componente_comun": R(E6, "choques_comunes.pct_var_componente_comun_desvio")}, dec=3)
C("demanda_un_modelo_por_ruta", {"dif_media_mensual_pp": R(E6, 'comparacion_pliegues["V2 frente a V1, h=7"].dif_media_pp'),
                                 "p_t_pareada": R(E6, 'comparacion_pliegues["V2 frente a V1, h=7"].p_t_pareada'),
                                 "meses_mejor": R(E6, 'comparacion_pliegues["V2 frente a V1, h=7"].meses_mejor')}, dec=2)
C("demanda_otras_rutas_como_variable", {"dif_media_mensual_pp": R(E6, 'comparacion_pliegues["V4 frente a V1, h=7"].dif_media_pp'),
                                        "p_t_pareada": R(E6, 'comparacion_pliegues["V4 frente a V1, h=7"].p_t_pareada'),
                                        "meses_mejor": R(E6, 'comparacion_pliegues["V4 frente a V1, h=7"].meses_mejor')}, dec=2)
C("demanda_lo_que_no_ayuda", {
    "calendarios_V1_vs_V0": ic(E11, "comparacion_vs_V0.V1_h7"), "climatologia_V2_vs_V0": ic(E11, "comparacion_vs_V0.V2_h7"),
    "lluvia_observada_N_vs_V3": ic(E11, "comparacion_en_cadena.N_vs_V3_h7"), "recencia_V5_vs_V3": ic(E11, "comparacion_en_cadena.V5_vs_V3_h7"),
    "ajuste_hiperparametros": ic(E11, "ajuste_anidado.comparacion_vs_elegida_sin_ajuste")}, dec=2)
C("demanda_lo_que_si_ayuda", {
    "V3_vs_V2": ic_meses(E11, "comparacion_en_cadena.V3_vs_V2_h7"), "V4_vs_V0": ic_meses(E11, "comparacion_vs_V0.V4_h7"),
    "sin_agosto": R(E11, "comparacion_vs_V0.V4_h7.dif_pp_sin_mes_mayor_ganancia"), "mes_mayor_ganancia": R(E11, "comparacion_vs_V0.V4_h7.mes_mayor_ganancia"),
    "agosto_sesgo_V0_pct": R(E11, 'sesgo_pct_por_mes_h7.V0["8"]'), "agosto_sesgo_V4_pct": R(E11, 'sesgo_pct_por_mes_h7.V4["8"]')}, dec=2)
C("demanda_dias_atipicos", {
    "dias_tres_rutas_bajo_10_fuera_calendario": R(E10, "parte_a.dias_tres_rutas_bajo_10_fuera_de_calendario"),
    "dias_investigados": R(E10, "parte_a.dias_seleccionados"), "confianza": R(E10, "parte_a.por_confianza"),
    "no_predecibles_peso_025": R(E11, "panel.dias_atipicos_no_predecibles"), "filas_con_peso": R(E11, "panel.filas_con_peso_atipico")}, dec=0)
C("demanda_protocolo", {"pliegues": R(E11, "variantes[clave=V4_h7].metricas_por_mes", op="n"), "franjas_prueba": R(E11, "panel.filas_prueba_2025"),
                        "franjas_panel": R(E11, "panel.filas"), "horizontes_E11": R(E11, "variantes[*].horizonte", op="conteo"),
                        "metrica": MD(PROT, r"^- (`MAE`, `RMSE`, `WAPE` = .+)$")}, dec=0)
C("demanda_otros_metodos", {
    "clasicos_E4_mejor": R(E12R, "[modelo=E4_E_GLM_SARIMA].WAPE"), "cuantiles_E3_p50": R(E3, "variantes[0].metricas_global.WAPE"),
    "plantillas_E5_k4": R(E5, "[nombre=Plantilla k=4 + nivel reciente del grupo × calendario (N5)].WAPE"),
    "chronos2_solo": R(E12R, "[modelo=chronos2_cov].WAPE"), "timesfm25_xreg": R(E12R, "[modelo=timesfm25_xreg].WAPE"),
    "tft": R(E12R, "[modelo=tft_global].WAPE")}, dec=2)
C("demanda_intervalo_e3", {"cobertura_p10_p90_pct": R(E3, 'intervalos["pasajeros_total h=7"].global.cobertura_p10_p90'),
                           "pct_bajo_p10": R(E3, 'intervalos["pasajeros_total h=7"].global.pct_bajo_p10'),
                           "pct_sobre_p90": R(E3, 'intervalos["pasajeros_total h=7"].global.pct_sobre_p90')}, dec=1)

# ===============================================================================================================
# MODELO · ¿Qué modelo es y por qué?
# ===============================================================================================================
C("modelo_final_nombre", R(E11S, "nombre"), extra={"descripcion": R(E11S, "configuracion.desc"), "hiperparametros": R(E11S, "hiperparametros")})
C("modelo_final_variables", {"E11_h7": R(E11M, "modelos.H7.n_variables"), "E11_h1": R(RFE, "variables.h1"), "E1_h7": R(RFE, "variables.e1_h7"),
                             "E1_h1": R(RFE, "variables.e1_h1")}, dec=0)
C("modelo_final_hiperparametros", R(E11S, "params"))
C("modelo_final_pliegues", {"pliegues_mensuales_2025": R(E11, "variantes[clave=V4_h7].metricas_por_mes", op="n"),
                            "franjas_prueba": R(E11, "panel.filas_prueba_2025"), "filas_panel": R(E11, "panel.filas"), "dias": R(DASH, "kpis.dias")}, dec=0)
_ENTRENA = r"^- (Genera un modelo por horizonte en .+? filas\. Tarda \d+ s\.)$"
C("modelo_final_horizontes", {"archivos": {f"H{h}": R(E11M, f"modelos.H{h}.archivo") for h in (7, 14, 21, 28)},
                              "texto_filas": MD(E11R, _ENTRENA)},
  nota="Las filas de entrenamiento de cada horizonte solo están en el README de E11 (§4 a); se copian tal cual del texto.")
C("modelo_final_tiempo_entrenamiento", {"evaluacion_completa_s": R(E11, "tiempo_s_corrida_completa"),
                                        "por_reentrenamiento": R(E12, "produccion.costos.V4_lightgbm.entrenamiento"),
                                        "texto_produccion": MD(E11R, _ENTRENA)}, dec=0)
C("modelo_final_pesos", {"dias_atipicos_no_predecibles": R(E11, "panel.dias_atipicos_no_predecibles"), "filas_peso_0_25": R(E11, "panel.filas_con_peso_atipico"),
                         "franjas_con_fallas_peso_0_1": R(E11, "panel.franjas_con_fallas_25pct"), "pct_franjas_con_fallas": R(E11, "panel.pct_franjas_con_fallas_25pct")}, dec=0)
C("modelo_final_candidatos", {"variantes": R(E11, "variantes[horizonte=7]*.nombre"), "regla": R(E11S, "regla"),
                              "significativas": R(E11S, "variantes_significativas")})
C("modelo_final_seleccion", R(E11, "comparacion_vs_V0.V4_h7.dif_pp"), dec=2,
  extra={k: R(E11, f"comparacion_vs_V0.V4_h7.{k}") for k in ("ic_inf", "ic_sup", "meses_mejor", "meses_peor", "p_wilcoxon", "p_t_pareada")})
C("modelo_final_importancia", R(E11M, "modelos.H7.importancia_top20"), dec=2)
C("modelo_final_2024", R(E12, "validacion_2024.V4.WAPE"), dec=2, extra={"franjas": R(E12, "validacion_2024.V4.n")})
C("modelo_final_produccion", {"entrenamiento": MD(E11R, r"^- (Lee `seleccion\.json` .+)$"),
                              "pronostico": MD(E11R, r"^- (Cada fecha d usa el modelo .+)$"),
                              "calendarios": MD(E11R, r"^- (Los festivos salen del paquete .+)$")})
C("modelo_hibrido_nombre", R(E12M, "descripcion"), extra={"variables_extra": R(E12M, "variables_extra"), "repo_chronos": R(E12M, "repo_chronos"),
                                                          "params": R(E12M, "params")})
_PC = f"produccion.costos.{HIB}."
C("modelo_hibrido_wape_2025", {"WAPE": R(E12, _PC + "WAPE_2025"), "dif": R(E12, _PC + "dif_2025[0]"), "ic_inf": R(E12, _PC + "dif_2025[1]"),
                               "ic_sup": R(E12, _PC + "dif_2025[2]"), "meses_mejor": R(E12H, "vs_V4.meses_mejor"),
                               "meses": R(E12H, "vs_V4.dif_por_mes_pp", op="n")}, dec=2)
C("modelo_hibrido_wape_2024", {"WAPE_hibrido": R(E12, _REF24 + ".hibrido.WAPE"), "WAPE_V4": R(E12, _REF24 + ".V4.WAPE"),
                               "dif": R(E12, _REF24 + ".dif_pp"), "ic_inf": R(E12, _REF24 + ".ic_inf"), "ic_sup": R(E12, _REF24 + ".ic_sup"),
                               "meses_mejor": R(E12, _REF24 + ".meses_mejor"), "franjas": R(E12, _REF24 + ".franjas")}, dec=2)
C("modelo_hibrido_sesgo", {"2025_pct": R(E12T, f"[modelo={HIB}].sesgo_pct"), "2024_pct": R(E12, f"validacion_2024.candidatos.{HIB}.sesgo_pct")}, dec=2)
C("modelo_hibrido_ganancia_chronos", R(E12M, "modelos.H7.ganancia_chronos_pct"), dec=1)
_CPU = "produccion.chronos2_cpu."
C("modelo_hibrido_costo_cpu", {"inferencia_s": R(E12, _CPU + "inferencia_s"), "dif_media_pax_vs_gpu": R(E12, _CPU + "dif_media_pax"),
                               "dif_max_pax": R(E12, _CPU + "dif_max_pax"), "media_prediccion": R(E12, _CPU + "media_prediccion"),
                               "wape_cpu_vs_gpu_pct": R(E12, _CPU + "wape_cpu_vs_gpu_pct"), "franjas": R(E12, _CPU + "franjas")}, dec=1)
C("modelo_hibrido_tiempos", R(E12M, "tiempos_s"), dec=1, unidad="segundos (corrida de enero de 2026)",
  nota="Se leen de metadatos_pronostico_2026_enero_hibrido.json (tiempos_s), no de la tabla del README.")
_VS = _G + "vs_V4_bootstrap_dias."
C("modelo_hibrido_emulacion", {"hibrido": R(E12E, _G + "todas.WAPE_hibrido"), "V4": R(E12E, _G + "todas.WAPE_V4"),
                               "dif": R(E12E, _VS + "dif_pp"), "ic_inf": R(E12E, _VS + "ic_inf"), "ic_sup": R(E12E, _VS + "ic_sup"),
                               "semanas_mejor": R(E12E, _G + "todas.semanas_mejor"), "semanas": R(E12E, _G + "todas.semanas"),
                               "origenes_mejor": R(E12E, _VS + "origenes_mejor"), "origenes": R(E12E, _VS + "dif_por_origen_pp", op="n")}, dec=2)
C("modelo_comparacion_51", {
    "candidatos": R(E12, "ranking.n_candidatos"), "resultados": R(E12, "ranking.n_resultados"), "elegibles": R(E12, "ranking.n_elegibles"),
    "cumplen_regla": R(E12, "ranking.n_cumplen"), "elegibles_cumplen": R(E12, "ranking.n_elegibles_cumplen"), "ganador_formal": R(E12, "ranking.ganador"),
    "ganador_WAPE": R(E12, "ranking.top[0].WAPE"), "ganador_dif": R(E12, "ranking.top[0].dif_vs_V4_pp"), "ganador_ic_inf": R(E12, "ranking.top[0].ic_inf"),
    "ganador_ic_sup": R(E12, "ranking.top[0].ic_sup"), "ganador_meses_mejor": R(E12, "ranking.top[0].meses_mejor")}, dec=2)


def _fila_rk(m, con24=True):
    d = {"WAPE": R(E12R, f"[modelo={m}].WAPE"), "dif": R(E12R, f"[modelo={m}].dif_vs_V4_pp"), "ic_inf": R(E12R, f"[modelo={m}].ic_inf"),
         "ic_sup": R(E12R, f"[modelo={m}].ic_sup"), "elegible": R(E12R, f"[modelo={m}].elegible")}
    if con24:
        c = f"validacion_2024.candidatos.{m}."
        d.update({"dif_2024": R(E12, c + "dif_pp"), "ic_inf_2024": R(E12, c + "ic_inf"), "ic_sup_2024": R(E12, c + "ic_sup"),
                  "cumple_2024": R(E12, c + "cumple_regla_2024")})
    return d


C("modelo_finalistas", {m: _fila_rk(m) for m in ("ens_conj_c_nnls_diverso", "ens_conj_a_media_V4_mejor_familia", HIB, "ens_adhoc_V4_tft_nnls")}, dec=2)
C("modelo_otros_arboles", {m: R(E12R, f"[modelo={m}].WAPE") for m in ("lgbm_tweedie", "lgbm_v4_bag5", "hgb_poisson", "xgboost_poisson",
                                                                       "catboost_poisson", "extra_trees", "ens_arboles_media_gbm", "V4_lightgbm")}, dec=2)
C("modelo_redes", {"tft_global": _fila_rk("tft_global", con24=False), "cnn_cuadricula": R(E12R, "[modelo=cnn_cuadricula].WAPE"),
                   "nhits_global": R(E12R, "[modelo=nhits_global].WAPE")}, dec=2)
C("modelo_fundacionales", {"chronos2_cov": _fila_rk("chronos2_cov", con24=False), "timesfm25_xreg": _fila_rk("timesfm25_xreg"),
                           "timesfm25_sin_calendario": R(E12R, "[modelo=timesfm25].WAPE")}, dec=2)
C("modelo_clasicos", {m: R(E12R, f"[modelo={m}].WAPE") for m in ("autoets_cal", "prophet_semanal", "E4_E_GLM_SARIMA")}, dec=2)
C("modelo_correccion_multiple", {k: R(E12R, f"[modelo={HIB}].{k}") for k in ("p_holm", "ic_bonf_inf", "ic_bonf_sup", "sobrevive_bonferroni", "sobrevive_holm")}, dec=3)
C("modelo_regla_seleccion_e12", R(E12, "ranking.regla"))
C("modelo_por_que_hibrido", R(E12, "produccion.motivo"), extra={"recomendacion": R(E12, "produccion.recomendacion")})
C("modelo_e13_recomendacion", {"hibrido_V4c_2025": R(E13, _R25.format("hib_V4c")), "hibrido_V4c_2024": R(E13, _R24.format("hib_V4c")),
                               "V4c_2025": R(E13, _R25.format("V4c")), "V4c_2024": R(E13, _R24.format("V4c"))}, dec=2)
C("modelo_e13_imputar_empeora", {"imputacion_2025": ic_meses(E13, 'comparaciones_2025["corregido|V4c|V4c_imp"]'),
                                 "registro_parcial_2025": ic_meses(E13, 'comparaciones_2025["corregido|V4c|V4c_imp_parcial"]'),
                                 "anomalias_automaticas_vs_E10_2025": ic_meses(E13, 'comparaciones_2025["corregido|V4c|V4c_auto"]')}, dec=2)
C("modelo_fugas", {"prueba_empirica_hibrido": MD(E12MD, r"^- \*\*Prueba empírica\*\* (.+)$"),
                   "diseno_y_fugas": MD(E12MD, r"^- \*\*Diseño y fugas\.\*\* (.+)$"),
                   "ensambles_sin_fuga": MD(E12MD, r"^- \*\*Ensambles sin fuga\.\*\* (.+)$"),
                   "prueba_fugas_panel": R(RFE, "prueba_fugas")})
C("modelo_plantillas_hoja_calculo", R(E5, "[nombre=Plantilla k=4 + nivel reciente del grupo × calendario (N5)].WAPE"), dec=2)
C("modelo_limite_nivel_2026", MD(E12MD, r"^\s*- \*\*Lo que implica para enero\.\*\* (.+)$"))
C("modelo_entorno", {"hibrido_python": MD(E12MD, r"^- \*\*Python\.\*\* (.+)$"), "hibrido_sin_gpu": MD(E12MD, r"^- \*\*Sin GPU\.\*\* (.+)$"),
                     "e12_entorno_aparte": MD(README, r"^(La comparación de modelos .+)$")})

# ===============================================================================================================
# HORARIO · ¿Cuántos buses y cada cuánto?
# ===============================================================================================================
C("horario_tabla_9_combinaciones", R(P1V, "tabla_juego_a_e05"), dec=0, extra={"supuestos_D5": R(P1V, "tabla_juego_c_e05")})
C("horario_dia_promedio_2025", R(P1V, "dia_promedio_2025[0]"), dec=1, extra={"con_e07": R(P1V, "dia_promedio_2025[1]"),
                                                                         "producido_e05": R(P1V, "dia_promedio_2025[2]")})
C("horario_dia_promedio_supuestos", R(P1V, "dia_promedio_2025[4]"), dec=1)
C("horario_frase", R(P1V, "frase_diapositiva"))
C("horario_juegos_de_costos", R(P1V, "juegos_de_costos_pagina"))
C("horario_parametros_milp", R(P1V, "parametros_D5_comunes"))
C("horario_datos_planificador_js", {"campos_hora": R(PLAN, "campos_hora"), "rutas": R(PLAN, "rutas", op="claves"), "param": R(PLAN, "param"),
                                    "fuentes_param": R(PLAN, "fuentes_param")})
C("horario_validacion_planificador", {"dia_tipico_por_defecto": R(P1, "validacion_D5_dia_tipico_por_defecto"),
                                      "elasticidades_D5": R(P1, "validacion_elasticidades_D5"), "MILP_aleatoria": R(P1, "validacion_MILP_aleatoria"),
                                      "costos_con_fuente": R(P1V, "resumen")})
C("horario_aviso_flota", R(P1, "interfaz.aviso_flota_por_defecto"))
C("horario_recomendado_minuto_a_minuto", {"filas": R(D5H, "[*].n", op="n"), "resumen": R(D5, "resumen_horario")}, dec=0,
  extra={"cra54_laboral": R(D5H, "[ruta=CRA 54&tipo_dia=Laboral]*.hora_salida")})
C("horario_dia_tipico_d5", R(D5, "dia_tipico_salidas_dia"), dec=0)
C("horario_escenarios_d5", R(D5E, "[ruta=Todas&tipo_dia=Todos]*"), dec=2)
C("horario_calidad_decision_d5", R(D5, "calidad_decision_vs_oraculo"), dec=2)
C("horario_beta_equilibrio_asimetrica_d5", R(D5, "complemento.elasticidad_equilibrio_asimetrica"), dec=3)
C("horario_calidad_decision_d1", R(D1, "calidad_decision"), dec=2)
C("horario_picos_y_valles_cra54", {"faltan_demanda": R(D1, "top_deficit_demanda"), "faltan": R(D1, "top_deficit"), "sobran": R(D1, "top_exceso")}, dec=1)
C("horario_flota_d2", {"pico_buses_oper_laboral_mediana": {r: R(D2, f"por_ruta.{r}.pico_buses_oper_laboral.mediana") for r in RUTAS},
                       "vehiculos_distintos_dia_laboral": {r: R(D2, f"por_ruta.{r}.vehiculos_distintos_dia.Laboral") for r in RUTAS},
                       "flota_requerida_85_laboral": {r: R(D2, f"por_ruta.{r}.flota_requerida_85_laboral") for r in RUTAS}}, dec=1)
C("horario_exceso_deficit_d2", {r: {"diario": R(D2, f"por_ruta.{r}.diario"), "horas_exceso_laboral": R(D2, f"por_ruta.{r}.horas_exceso_laboral"),
                                    "horas_deficit_laboral": R(D2, f"por_ruta.{r}.horas_deficit_laboral")} for r in RUTAS}, dec=0)
_D6C = ["etiqueta", "salidas", "espera_media", "espera_media_p5", "espera_media_p95", "espera_p90", "pct_viajes_llenos", "pct_dejados",
        "buses_hora", "km", "buses_en_ruta_pico", "ciclo_mediano", "cv_medio"]
_D6F = [f for f in leer(D6) if f["grupo"] == "principal"]
C("horario_simulador_d6", {
    r: {f["politica"]: {c: R(D6, f"[ruta={r}&grupo=principal&politica={f['politica']}].{c}") for c in _D6C} for f in _D6F if f["ruta"] == r}
    for r in sorted({f["ruta"] for f in _D6F})}, dec=2)
_HT = {}
for _r in RUTAS:
    for _t in TIPOS:
        _HT[f"{_r} | {_t}"] = {"horas": _col_plan(_r, _t, "hora"), "pasajeros_p10": _col_plan(_r, _t, "pasajeros_p10"),
                               "pasajeros_p50": _col_plan(_r, _t, "pasajeros_p50"), "pasajeros_p90": _col_plan(_r, _t, "pasajeros_p90"),
                               "salidas_hoy": _col_plan(_r, _t, "salidas_actuales"), "plan_fuente": _x_p1(_r, _t),
                               "plan_fuente_e07": _x_p1(_r, _t, e=0.7), "d5_supuestos": _col_plan(_r, _t, "solucion_D5")}
C("horario_dia_tipico_por_hora", _HT, dec=0, pantalla="horario",
  meta={"que_es": "Día típico por ruta y tipo de día, hora a hora (4-20 h): pasajeros previstos (p10, p50, p90), salidas de hoy (mediana 2025), plan con costos con fuente (P1, conductor por hora, e = 0,5 y 0,7) y D5 con los supuestos iniciales",
        "tipo": "serie", "unidad": "pasajeros y salidas por hora", "experimento": "P1 / D5 (planificador_datos.js y validacion_costos_fuente.json)",
        "verificado": "parcial", "revision": "Insumos de D5 verificados en P1 (05-10-2026); el plan con costos con fuente reproduce el MILP en 153 de 153 horas (validacion_costos_fuente.json, 06-10-2026), sin revisor independiente de esa actualización",
        "interruptor": "hoy / modelo"})

# ===============================================================================================================
# DESPACHO · ¿Qué hago ahora?
# ===============================================================================================================
C("despacho_indice_replay", {"por_dia": R(IND, "meta.por_dia"), "plan_param": R(IND, "meta.plan_param"), "sin_gps": R(IND, "sin_gps"),
                             "tipo_dia": R(IND, "dias[*].tipo_dia", op="conteo"), "grupo": R(IND, "dias[*].grupo", op="conteo"),
                             "generado": R(IND, "meta.generado")})
C("despacho_dia_ejemplo", {
    "fecha": R(DIA, "fecha"), "etiqueta": R(DIA, "etiqueta"), "descripcion": R(DIA, "descripcion"), "tipo_dia": R(DIA, "tipo_dia"),
    "plan_param": R(DIA, "plan_param"), "instantaneas": R(DIA, "snapshots", op="n"),
    "plan": {r: {k: R(DIA, f'plan["{r}"].{k}') for k in ("salidas_hora", "oraculo_hora", "pax_plan_hora", "flota")} for r in RUTAS},
    "real": {r: {k: R(DIA, f'real["{r}"].{k}') for k in ("salidas_hora", "pax_hora", "salidas")} for r in RUTAS}}, dec=0)
C("despacho_backtest_muestra", {"muestra": R(BT, "muestra"), "plan_param": R(BT, "plan_param")}, nota=REV_BT.strip(" ·"))
_DECK = {"error_salidas_h": "error_abs_medio_salidas_hora", "pct_exactas": "pct_horas_exactas", "pct_sobre": "pct_sobreoferta", "pct_sub": "pct_suboferta",
         "salidas_dia": "salidas_dia", "buses_hora_dia": "buses_hora_dia", "espera_min": "espera_media_min", "sobrecap_dia": "pax_sobre_capacidad_dia",
         "pct_horas_fc_mayor_1": "pct_horas_fc_mayor_1", "costo_Mcop_dia": "costo_generalizado_Mcop_dia", "dias": "dias"}
_ESC = sorted({f["escenario"] for f in leer(BTD)})
for _h in (7, 4):
    C(f"despacho_decision_vs_oraculo_h{_h}", {e: {k: R(BTD, f"[grupo=Todos&horas_desde={_h}&escenario={e}].{c}") for k, c in _DECK.items()} for e in _ESC},
      dec=2, extra={"por_grupo": R(BTD, f"[horas_desde={_h}]*")}, nota=REV_BT.strip(" ·"))
C("despacho_nowcast_wape", R(BTN, "[grupo=Todos]*"), dec=2, extra={"por_grupo": R(BTN, "[modo=calibrado]*")}, nota=REV_BT.strip(" ·"))
C("despacho_cobertura_intervalo", R(BT, "cobertura_intervalo_80_hora_pct"), dec=1, nota=REV_BT.strip(" ·"))
C("despacho_alertas", {"por_tipo": R(BT, "alertas_por_ruta_dia_cada_15_min"), "subtipos": R(BT, "alertas_por_subtipo")}, dec=2, nota=REV_BT.strip(" ·"))
C("despacho_metodo_solucion", R(BT, "metodo_solucion_pct"), dec=1, nota=REV_BT.strip(" ·"))
C("despacho_guarda_datos", R(BT, "guarda_datos_corridas"), nota=REV_BT.strip(" ·"))
C("despacho_simulador_d6", {"promedio": R(BT, "simulador_d6.promedio"), "por_tipo": R(BT, "simulador_d6.por_tipo")}, dec=2, nota=REV_BT.strip(" ·"))
_VPF = "[fuente=costos con fuente (2026)]*."
C("despacho_verificacion_plan", {"ruta_dias": R(BTV, _VPF + "ruta", op="n"), "horas_iguales": R(BTV, _VPF + "horas_iguales", op="suma"),
                                 "salidas_plan": R(BTV, _VPF + "salidas_plan", op="suma"), "salidas_ref": R(BTV, _VPF + "salidas_ref", op="suma"),
                                 "filas_por_fuente": R(BTV, "[*].fuente", op="conteo")}, dec=0)
_SN = "snapshots[t=07:30].rutas"
C("despacho_pantalla_7_30", {r: {k: R(DIA, f'{_SN}["{r}"].{k}') for k in ("en_ruta", "en_patio", "flota", "salidas_real", "salidas_plan",
                                                                           "ultima_salida", "pax_obs", "pax_esp", "factor", "f10", "f90")} for r in RUTAS},
  dec=0, extra={"hora": R(DIA, "snapshots[t=07:30].t")})

# ===============================================================================================================
# CIUDAD · ¿Cómo se ve en la calle?
# ===============================================================================================================
C("ciudad_3jun_real", R(C3, "resumen.dia.real"), dec=1)
C("ciudad_3jun_plan", R(C3, "resumen.dia.plan"), dec=1)
C("ciudad_3jun_balance", {
    "ahorro_operacion_Mcop": FO("r - p", r=R(C3, _RD.format("real", "costo_Mcop")), p=R(C3, _RD.format("plan", "costo_Mcop"))),
    "pasajes_perdidos_Mcop": R(C3, _RD.format("plan", "pasajes_perdidos_Mcop")),
    "saldo_conservador_Mcop": FO("r - p - l", r=R(C3, _RD.format("real", "costo_Mcop")), p=R(C3, _RD.format("plan", "costo_Mcop")),
                                 l=R(C3, _RD.format("plan", "pasajes_perdidos_Mcop"))),
    "valor_ganados_Mcop": FO("g * t / 1e6", g=R(C3, _RD.format("plan", "ganados_simetrico")), t=R(C3, "plan_meta.tarifa")),
    "saldo_simetrico_Mcop": FO("r - p - l + g * t / 1e6", r=R(C3, _RD.format("real", "costo_Mcop")), p=R(C3, _RD.format("plan", "costo_Mcop")),
                               l=R(C3, _RD.format("plan", "pasajes_perdidos_Mcop")), g=R(C3, _RD.format("plan", "ganados_simetrico")),
                               t=R(C3, "plan_meta.tarifa"))}, dec=2)
C("ciudad_3jun_pronostico", R(C3, "resumen.dia.pronostico"), dec=0)
C("ciudad_3jun_por_hora", R(C3, "resumen.por_hora"), dec=1)
C("ciudad_3jun_cra54_17_19", {"horas": R(PLAN, 'rutas["CRA 54"].tipos.Laboral.horas[13:16][*][0]'),
                              "plan": R(DIA, 'plan["CRA 54"].salidas_hora[13:16]'),
                              "salidas_real_registradas": R(DIA, 'real["CRA 54"].salidas_hora[13:16]')}, dec=0,
  nota="Las salidas válidas reales por ruta y hora no están en ningún archivo: se muestran las salidas registradas del archivo del día.")
C("ciudad_plan_meta", R(C3, "plan_meta"))
C("ciudad_2025_real", {"por_dia": R(CRES, "total.real.por_dia"), "totales": R(CRES, "total.real.total"), "dias": R(CRES, "total.dias")}, dec=1)
C("ciudad_2025_plan", {"por_dia": R(CRES, "total.plan.por_dia"), "totales": R(CRES, "total.plan.total"), "dias": R(CRES, "total.dias")}, dec=1)
_TPL = "total.plan.total."
C("ciudad_2025_saldo", dict(_PP, **{
    "pasajeros_en_riesgo_dia": FO("(b + s) / d", b=R(CRES, _TPL + "perdidos_beta"), s=R(CRES, _TPL + "perdidos_sin_bus"), d=R(CRES, "dias")),
    "perdidos_beta_dia": FO("b / d", b=R(CRES, _TPL + "perdidos_beta"), d=R(CRES, "dias")),
    "perdidos_sin_bus_dia": FO("s / d", s=R(CRES, _TPL + "perdidos_sin_bus"), d=R(CRES, "dias")),
    "pasajeros_netos_dia_simetrico": FO("(g - b - s) / d", g=R(CRES, _TPL + "ganados_simetrico"), b=R(CRES, _TPL + "perdidos_beta"),
                                        s=R(CRES, _TPL + "perdidos_sin_bus"), d=R(CRES, "dias")),
    "dias": R(CRES, "dias"), "salidas_dia_real": R(CRES, "total.real.por_dia.salidas"), "salidas_dia_plan": R(CRES, "total.plan.por_dia.salidas"),
    "version": R(CRES, "version"), "generado": R(CRES, "generado")}), dec=1)
_PT = 'por_tipo_dia["{}"].{}'
C("ciudad_2025_por_tipo_dia", R(CRES, "por_tipo_dia"), dec=1, extra={"saldo_conservador_Mcop_dia": {
    t: FO("(r - p - l) / d", r=R(CRES, _PT.format(t, "real.total.costo_Mcop")), p=R(CRES, _PT.format(t, "plan.total.costo_Mcop")),
          l=R(CRES, _PT.format(t, "plan.total.pasajes_perdidos_Mcop")), d=R(CRES, _PT.format(t, "dias"))) for t in TIPOS}})
C("ciudad_2025_por_hora", R(CRES, "por_hora"), dec=1)
C("ciudad_dias_saldo_negativo", dict({"total": CAL("negativos"), "de": CAL("dias")},
                                     **{t: {"negativos": CAL("negativos", t), "dias": CAL("dias", t)} for t in TIPOS}), dec=0,
  nota="Se recalcula en cada generación recorriendo resumen.dia de los 353 archivos de calles (saldo conservador = costo real − costo del plan − pasajes perdidos < 0).")
C("ciudad_version_calles", {"version": R(CRES, "version"), "generado": R(CRES, "generado"), "dias": R(CRES, "dias"), "pendientes": R(CRES, "pendientes")})

# ===============================================================================================================
# RESULTADO · ¿Qué gana Sobusa?  (formas iguales a las que usa pantallas/resultado.js)
# ===============================================================================================================
_LBT = "[ruta=Total]."
_LB_CAMPOS = {"km_anual": ("km_anual", None), "buses_hora_anual": ("buses_hora_anual", None), "pasajeros_anual": ("pasajeros_anual", None),
              "galones_anual": ("galones_anual", None), "co2_t_anual": ("co2_t_anual", None), "costo_total_Mcop": ("costo_total", 1e-6),
              "costo_por_pasajero": ("costo_por_pasajero", None), "costo_por_km": ("costo_por_km", None), "ingreso_pasajes_Mcop": ("ingreso_pasajes", 1e-6),
              "margen_Mcop": ("margen_aprox", 1e-6), "margen_pct": ("margen_pct", None), "flota_equivalente": ("flota_equivalente", None),
              "conductor_Mcop": ("conductor", 1e-6), "fijos_Mcop": ("fijos", 1e-6)}
_LB_RUTA = {"km_anual": ("km_anual", None), "buses_hora_anual": ("buses_hora_anual", None), "pasajeros_anual": ("pasajeros_anual", None),
            "costo_total_Mcop": ("costo_total", 1e-6), "costo_por_pasajero": ("costo_por_pasajero", None), "margen_pct": ("margen_pct", None)}
C("resultado_linea_base_2025", dict({k: R(LB, _LBT + c, x=x) for k, (c, x) in _LB_CAMPOS.items()},
                                    por_ruta={r: {k: R(LB, f"[ruta={r}].{c}", x=x) for k, (c, x) in _LB_RUTA.items()} for r in RUTAS}), dec=0)
_CU = '["2026"].'
C("resultado_costos_unitarios_2026", dict(
    {k: R(CU, _CU + c) for k, c in {"combustible_km": "combustible_km", "mant_km": "mant_km", "llantas_km": "llantas_km", "lub_km": "lub_km",
                                    "costo_km_evitable": "costo_km_evitable", "hora_conductor": "hora_conductor", "bus_hora_conductor": "bus_hora_conductor",
                                    "tarifa_efectiva": "tarifa_efectiva", "rendimiento_km_gal": "rendimiento_sistema", "fijo_bus_anio": "fijo_bus_anio"}.items()},
    **{k: R(CRS, f"P.{k}") for k in ("precio_acpm_2026", "smmlv_2026", "tarifa_2026", "factor_ingreso", "horas_mes_2026", "factor_horas_pagadas",
                                     "multiplo_salario", "factor_prestacional", "valor_espera", "beta")}), dec=0)
C("resultado_demanda_dia_d5", R(CRS, "info.pax_dia_total_D5"), dec=0, extra={"n_dias": R(CRS, "info.n_dias"), "dias_laborales": R(CRS, "info.dias_laborales")})
_AHO_C = {"neto_pago_por_hora": ("neto_pago_por_hora", 1e-6), "neto_producido": ("neto_pago_por_producido", 1e-6),
          "neto_simetrico": ("neto_simetrico_pago_por_hora", 1e-6), "pax_perdidos_dia": ("pax_perdidos_dia", None),
          "ingreso_perdido": ("ingreso_perdido", 1e-6), "ahorro_km": ("ahorro_por_km", 1e-6), "ahorro_conductor": ("ahorro_conductor_hora", 1e-6),
          "co2_t": ("co2_t_evitado", None), "galones": ("galones_ahorrados", None), "delta_espera_min": ("delta_espera_min", None),
          "valor_social_espera": ("valor_social_espera", 1e-6)}
C("resultado_ahorros_por_escenario", {
    f["clave"]: dict({"escenario": R(AHO, f"[clave={f['clave']}].escenario"),
                      "rango": [R(AHO, f"[clave={f['clave']}].neto_pago_por_hora_bajo", x=1e-6), R(AHO, f"[clave={f['clave']}].neto_pago_por_hora_alto", x=1e-6)]},
                     **{k: R(AHO, f"[clave={f['clave']}].{c}", x=x) for k, (c, x) in _AHO_C.items()})
    for f in leer(AHO)}, dec=1)
C("resultado_beta_equilibrio", {f["clave"]: {"hora": R(BEQ, f'[clave={f["clave"]}]["pago por hora"]'),
                                             "producido": R(BEQ, f'[clave={f["clave"]}]["pago por producido"]'),
                                             "supuestos_D5": R(BEQ, f'[clave={f["clave"]}]["supuestos D5 (60.000/1.500/3.000)"]')} for f in leer(BEQ)}, dec=2)
_TOR_C = {"parametro": ("parametro", None), "clave": ("clave", None), "valor_bajo": ("valor_bajo", None), "valor_alto": ("valor_alto", None),
          "neto_con_bajo_Mcop": ("neto_con_bajo", 1e-6), "neto_con_alto_Mcop": ("neto_con_alto", 1e-6), "rango_Mcop": ("rango", 1e-6),
          "neto_central_Mcop": ("neto_central", 1e-6)}
C("resultado_tornado_d5", {"filas": [{k: R(TOR, f"[clave={f['clave']}].{c}", x=x) for k, (c, x) in _TOR_C.items()} for f in leer(TOR)],
                           "neto_central_Mcop": R(TOR, f"[clave={leer(TOR)[0]['clave']}].neto_central", x=1e-6)}, dec=0)
_RE_C = {"corrida": "corrida", "salidas_dia": "salidas_dia", "buses_hora_dia": "buses_hora_dia", "delta_buses_hora_anual": "delta_buses_hora_anual",
         "delta_km_anual": "delta_km_anual", "espera_min": "espera_media_min", "sobrecap_dia": "pax_sobre_capacidad_dia",
         "pct_horas_fc_mayor_1": "pct_horas_fc_mayor_1", "pax_perdidos_bajo": "pax_perdidos_dia_bajo", "pax_perdidos_dia": "pax_perdidos_dia_central",
         "pax_perdidos_alto": "pax_perdidos_dia_alto", "ahorro_operativo_Mcop": "ahorro_operativo_pago_hora_Mcop",
         "neto_pago_hora_Mcop": "neto_pago_hora_beta070_Mcop", "neto_producido_Mcop": "neto_producido_beta070_Mcop",
         "pax_netos_simetrico_dia": "pax_netos_dia_simetrico_beta070", "neto_simetrico_Mcop": "neto_simetrico_pago_hora_beta070_Mcop",
         "costo_km_usado": "costo_km_usado", "costo_bus_hora_usado": "costo_bus_hora_usado"}
_CORRIDAS = [f["corrida"] for f in leer(REOPT)]


def _corrida(nombre, rango=False):
    d = {k: R(REOPT, f"[corrida={nombre}].{c}") for k, c in _RE_C.items()}
    if rango:
        d["rango_pax"] = [R(REOPT, f"[corrida={nombre}].pax_perdidos_dia_bajo"), R(REOPT, f"[corrida={nombre}].pax_perdidos_dia_alto")]
    return d


C("resultado_d5_reoptimizado", {"a_D5_original": _corrida(_CORRIDAS[0], rango=True), "b_D5_reoptimizado_e05": _corrida(CORR_B, rango=True),
                                "otras_corridas": {n: _corrida(n) for n in _CORRIDAS if n not in (_CORRIDAS[0], CORR_B)},
                                "corridas": [_corrida(n) for n in _CORRIDAS], "propuesta": R(REOPT, f"[corrida={CORR_B}].corrida")}, dec=0)
# Qué columnas de las corridas a y b reprodujo el revisor de simulacion_ahorro: se lee de las etiquetas de
# verificacion_contra_informe.csv («a: km ahorrados al año», «b: neto, pago por hora (M COP)», …).
_ETQ_VCI = {"buses-hora ahorrados al año": "delta_buses_hora_anual", "km ahorrados al año": "delta_km_anual",
            "pasajeros en riesgo por día": "pax_perdidos_dia", "neto, pago por hora": "neto_pago_hora_Mcop",
            "neto, pago por producido": "neto_producido_Mcop", "neto simétrico, pago por hora": "neto_simetrico_Mcop",
            "salidas por día": "salidas_dia"}
_VCI_OK = {"a": set(), "b": set()}
for _f in leer(SVI):
    _plan, _resto = str(_f["comparacion"]).split(": ", 1)
    _campo = _ETQ_VCI.get(_resto.split(" (")[0])
    if _campo and _plan in _VCI_OK:
        _VCI_OK[_plan].add(_campo)
_vc = {"a_D5_original": {k: ("sí" if k in _VCI_OK["a"] else "parcial") for k in _RE_C if k != "corrida"},
       "b_D5_reoptimizado_e05": {k: ("sí" if k in _VCI_OK["b"] else "parcial") for k in _RE_C if k != "corrida"},
       "otras_corridas": "no"}
DATOS["resultado"]["resultado_d5_reoptimizado"]["verificado_campos"] = _vc
_PLAN_R = {"salidas_dia_real": ("salidas_dia_real", None), "salidas_dia_plan": ("salidas_dia_plan", None), "buses_hora_real": ("buses_hora_dia_real", None),
           "buses_hora_plan": ("buses_hora_dia_plan", None), "km_dia_real": ("km_dia_real", None), "km_dia_plan": ("km_dia_plan", None),
           "galones_anio_ahorrados": ("galones_anio_ahorrados", None), "conductores_dia_real": ("conductores_dia_real", None),
           "conductores_dia_plan": ("conductores_dia_plan", None), "conductores_observados_dia": ("conductores_observados_dia", None),
           "cota_baja": ("conductores_observados_dia_cota_baja", None), "cota_alta": ("conductores_observados_dia_cota_alta", None),
           "plantilla_real": ("plantilla_real", None), "plantilla_plan": ("plantilla_plan", None), "pasajeros_en_riesgo_dia": ("pasajeros_en_riesgo_dia", None),
           "pasajeros_netos_simetrica_dia": ("pasajeros_netos_simetrica_dia", None), "sobre_capacidad_real": ("sobre_capacidad_dia_real", None),
           "sobre_capacidad_plan": ("sobre_capacidad_dia_plan", None), "espera_real_min": ("espera_real_min", None), "espera_plan_min": ("espera_plan_min", None),
           "ahorro_por_km_Mcop": ("ahorro_por_km", 1e-6), "ahorro_conductores_hora_Mcop": ("ahorro_conductores_hora", 1e-6),
           "valor_pasajes_Mcop": ("valor_pasajes_hora", 1e-6), "neto_hora_Mcop": ("neto_hora", 1e-6), "neto_hora_dia_Mcop": ("neto_hora_dia", 1e-6),
           "neto_plantilla_Mcop": ("neto_plantilla", 1e-6), "neto_producido_Mcop": ("neto_producido", 1e-6),
           "neto_hora_simetrica_Mcop": ("neto_hora_simetrica", 1e-6), "neto_plantilla_legal_Mcop": ("neto_plantilla_legal", 1e-6),
           "dias_con_neto_positivo_hora": ("dias_con_neto_positivo_hora", None), "conductores_dia_real_legal": ("conductores_dia_real_legal", None),
           "conductores_dia_plan_legal": ("conductores_dia_plan_legal", None), "plantilla_real_legal": ("plantilla_real_legal", None),
           "plantilla_plan_legal": ("plantilla_plan_legal", None)}
for _p in ("a", "b"):
    C(f"resultado_simulacion_plan_{_p}", {k: R(SRS, f"resumen_anual.{_p}.{c}", x=x) for k, (c, x) in _PLAN_R.items()}, dec=0)
C("resultado_costo_conductor", {"costo_mes_conductor": R(SRS, "costo_mes_conductor"), "costo_bus_hora": R(SRS, "costo_bus_hora"),
                                "costo_conductor_dia_salario_fijo": {"observadas": R(SRS, "costo_conductor_dia_salario_fijo.observadas"),
                                                                     "legal": R(SRS, "costo_conductor_dia_salario_fijo.legal")},
                                "costo_fijo_bus_anio": R(CU, '["2026"].fijo_bus_anio')}, dec=0)
_PT_TIPO = {}
for _p in ("a", "b"):
    _PT_TIPO[_p] = {}
    for _t in TIPOS:
        _f = f"[ruta=Total&plan={_p}&tipo_dia={_t}]*."
        _PT_TIPO[_p][_t] = {"dias": R(SPF, _f + "fecha", op="n"), "neto_anual_Mcop": R(SPF, _f + "neto_hora", op="suma", x=1e-6),
                            "neto_dia_Mcop": R(SPF, _f + "neto_hora", op="media", x=1e-6),
                            "neto_simetrico_anual_Mcop": R(SPF, _f + "neto_hora_simetrica", op="suma", x=1e-6),
                            "pax_riesgo_dia": R(SPF, _f + "pasajeros_en_riesgo", op="media"), "dias_positivos": R(SPF, _f + "neto_hora", op="positivos")}
C("resultado_por_tipo_dia", _PT_TIPO, dec=1, nota="Claves por tipo de día sin el número de días en el nombre: el número está en «dias».")
_PM = {}
for _p in ("a", "b"):
    _f = f"[ruta=Total&plan={_p}]*."
    _PM[_p] = {"mes": R(SPM, _f + "mes"), "dias": R(SPM, _f + "dias"), "neto_hora_Mcop": R(SPM, _f + "neto_hora", x=1e-6),
               "neto_hora_simetrica_Mcop": R(SPM, _f + "neto_hora_simetrica", x=1e-6), "neto_producido_Mcop": R(SPM, _f + "neto_producido", x=1e-6),
               "pasajeros_en_riesgo": R(SPM, _f + "pasajeros_en_riesgo")}
C("resultado_por_mes", _PM, dec=1, pantalla="resultado",
  meta={"que_es": "Saldo del plan por mes de 2025 (ruta Total): neto con pago por hora, simétrico y con pago por producido; pasajeros en riesgo del mes (divídalo entre «dias» para el promedio diario)",
        "tipo": "tabla", "unidad": "M COP por mes", "experimento": "simulacion_ahorro (simulacion_por_fecha.py)", "verificado": "sí",
        "revision": "simulacion_ahorro/README.md «Verificación independiente» (07-10-2026): los agregados salen del mismo cálculo por fecha cuyas 20 cifras anuales coinciden con costos/ (dif. ≤ 6e-15); la tabla mensual no se comparó aparte"})
_SB = {}
for _p in ("a", "b"):
    _f = f"[plan={_p}]*."
    _SB[_p] = {k: R(SSB, _f + k) for k in ("beta", "neto_hora_Mcop", "neto_plantilla_Mcop", "neto_producido_Mcop", "neto_plantilla_legal_Mcop", "pasajeros_en_riesgo_dia")}
C("resultado_sensibilidad_beta", _SB, dec=1)
C("resultado_conductores_2025", {
    "conductores_identificados_2025": R(SCR, "conductores_identificados_2025"), "con_menos_de_10_viajes": R(SCR, "conductores_con_menos_de_10_viajes"),
    "conductores_por_dia": {"identificados_media": R(SCR, "conductores_por_dia.identificados.media"), "cota_baja": R(SCR, "conductores_por_dia.cota_baja.media"),
                            "cota_alta": R(SCR, "conductores_por_dia.cota_alta.media"), "estimados": R(SCR, "conductores_por_dia.estimados.media")},
    "plantilla_mensual_identificada": R(SCR, "plantilla_mensual_identificada"),
    "horas_ruta_por_conductor_dia": {"media": R(SCR, "horas_ruta_por_conductor_dia.media"), "mediana": R(SCR, "horas_ruta_por_conductor_dia.mediana")},
    "jornada_por_conductor_dia": {"media": R(SCR, "jornada_por_conductor_dia.media"), "mediana": R(SCR, "jornada_por_conductor_dia.mediana")},
    "viajes_por_conductor_dia_mediana": R(SCR, "viajes_por_conductor_dia.mediana"), "dias_trabajados_mes_media": R(SCR, "dias_trabajados_por_conductor_mes.media"),
    "relevos_entre_identificados_vehiculo_dias": R(SCR, "relevos.vehiculo_dias_con_relevo_entre_identificados"),
    "codigo_generico": {"viajes": R(SCR, "codigos_genericos[0].viajes"), "pct_viajes": R(SCR, "codigos_genericos[0].pct_viajes")},
    "por_ruta_horas_ruta_media": R(SCR, "por_ruta[*].horas_ruta_media"), "por_ruta_conductores_distintos": R(SCR, "por_ruta[*].conductores_distintos_2025"),
    "por_ruta_nombres": R(SCR, "por_ruta[*].ruta"),
    "mes_regulares": {"ruta_mediana_h": R(SCR, "jornada_frente_a_la_ley.mes_regulares.ruta_mediana"),
                      "pct_ruta_mayor_182": R(SCR, "jornada_frente_a_la_ley.mes_regulares.pct_ruta_mayor_182"),
                      "pct_ruta_mayor_195": R(SCR, "jornada_frente_a_la_ley.mes_regulares.pct_ruta_mayor_195"),
                      "jornada_mediana_h": R(SCR, "jornada_frente_a_la_ley.mes_regulares.jornada_mediana")},
    "despachadores_codigos_2025": R(SCR, "despachadores.codigos_2025")}, dec=1,
  nota="Solo conteos y promedios: ningún código ni dato de un conductor.")
C("resultado_verificaciones_costos", {"celdas_excel": R(VEX, "[*].dif_relativa", op="n"), "dif_relativa_max_excel": R(VEX, "[*].dif_relativa", op="max"),
                                      "cifras_informe": R(SVI, "[*].diferencia_relativa", op="n"), "dif_relativa_max_informe": R(SVI, "[*].diferencia_relativa", op="max")})
C("resultado_e7_netos_supuestos", {"netos": R(E7, "sintesis.neto_central"), "simetrico": R(E7, "sintesis.neto_simetrico_central")}, dec=0)

# ===============================================================================================================
# PILOTO · ¿Cómo lo comprobamos?
# ===============================================================================================================
C("piloto_parametros", R(P2, "parametros"), extra={"fin": R(P2, "calendario.fin")})
C("piloto_franjas", R(P2, "franjas_piloto"))
C("piloto_potencia", R(P2, "potencia.diseno_propuesto"), dec=3, extra={"factor_calibracion": R(P2, "potencia.factor_calibracion_ee_empirico_sobre_analitico")})
C("piloto_simulacion", {"resumen": R(P2, "simulacion.resumen"), "ee_analitico_vs_empirico": R(P2, "simulacion.ee_analitico_vs_empirico")}, dec=3)
C("piloto_calendario", R(P2, "calendario"))
C("piloto_riesgo_por_franja", R(P2, "riesgo_costo.por_franja"), dec=1)
C("piloto_totales", R(P2, "riesgo_costo.totales_piloto"), dec=1)
C("piloto_reglas_de_parada", R(P2, "riesgo_costo.reglas_de_parada"))
C("piloto_planilla", R(P2, "planilla"), extra={"filas_csv": R(P2P, "[*].hora", op="n")})
C("piloto_ejemplo_analisis", R(P2A, "[*]"), dec=3)
C("piloto_por_que", MD(P2MD, r"^- \*\*E7 midió fallas, no recortes\.\*\* (.+)$"))

# ===============================================================================================================
# MÉTODO Y DATOS · ¿De dónde sale todo?
# ===============================================================================================================
C("metodo_datos_crudos", R(DASH, "kpis"), dec=0, extra={"periodo": R(DASH, "meta.periodo"), "notas": R(DASH, "meta.notas")},
  nota="«conductores» es el número de códigos distintos de conductor; no se publica ningún código.")
C("metodo_tablas_exportadas", R(INVD, "[*]"))
C("metodo_reglas_limpieza", {"reglas": MD(README, r"^- (.+)$", seccion="## Reglas de limpieza adoptadas", todos=True),
                             "unidad": R(RFE, "unidad"), "filas": R(RFE, "filas"), "columnas": R(RFE, "columnas"), "viajes": R(RFE, "viajes")})
C("metodo_protocolo", {"lineas_base": MD(PROT, r"^- (.+)$", seccion="## Líneas base obligatorias", todos=True),
                       "metricas": MD(PROT, r"^- (.+)$", seccion="## Métricas", todos=True),
                       "franjas_prueba": R(E11, "panel.filas_prueba_2025"),
                       "bases_WAPE": {"B1": R(E5, "[nombre=B1 manual (8 semanas)].WAPE"), "B2": R(E5, "[nombre=B2 ingenua (hace 7 días)].WAPE"),
                                      "B3": R(E5, "[nombre=B3 perfil histórico].WAPE")}})
C("metodo_variables", {"por_familia": R(RFE, "variables_por_familia"), "conteos": R(RFE, "variables")}, dec=0)
_EXPS = sorted(p.parent.name for p in (PROY / "experimentos").glob("*/resultados.json"))
_VER = {}
for _e in _EXPS:
    _j = leer(f"experimentos/{_e}/resultados.json")
    _clave = "verificacion" if isinstance(_j.get("verificacion"), dict) and _j["verificacion"] else (
        "verificacion_independiente" if isinstance(_j.get("verificacion_independiente"), dict) else None)
    if _clave:
        _VER[_e] = {k: R(f"experimentos/{_e}/resultados.json", f"{_clave}.{k}") for k in ("fecha", "veredicto") if k in _j[_clave]}
C("metodo_experimentos", {k: v for k, v in _VER.items() if v},
  nota="Fecha y veredicto de la revisión independiente que guarda cada resultados.json (los que no traen esa clave no aparecen).")
C("metodo_rondas_verificacion", MD(INFORME, r"^\*\*Verificación\.\*\* (.+)$"))
C("metodo_equipo", MD(E1MD, r"^\| ([A-ZÁÉÍÓÚÑ][^|@ ]+(?: [^|@ ]+)+) \| [^|]*\|$", seccion="## Equipo", todos=True),
  nota="Solo los nombres: el generador no copia los correos de la tabla.")
C("metodo_herramientas", {"python": MD(E1MD, r"^(Python 3\.13\.3 .+)$"), "e12": MD(README, r"^(La comparación de modelos .+)$")})
C("metodo_pesos_entrenamiento", R(RFE, "pesos"), dec=0, extra={"dias_atipicos_no_predecibles_E11": R(E11, "panel.dias_atipicos_no_predecibles")})
C("metodo_sin_fugas", R(RFE, "prueba_fugas"))
# Insumos del 2 de noviembre de 2026 (insumos_sobusa/): la capacidad real de la flota según el reporte de Sobusa (resumen de
# analizar_flota.py, porque el reporte original trae datos personales y no se versiona) y el estado del último día de cada mes.
FLOTA = "insumos_sobusa/analisis_flota.json"
ESTADO_BASE = "insumos_sobusa/estado_base_2026-11-02.json"
C("metodo_capacidad_flota", {k: R(FLOTA, f"capacidad_vehiculos_2025.{k}")
                             for k in ("mediana_total", "media_sentados", "media_depie", "vehiculos_con_dato", "vehiculos_2025")},
  dec=1, extra={"p25_p75": [R(FLOTA, "capacidad_vehiculos_2025.p25"), R(FLOTA, "capacidad_vehiculos_2025.p75")],
                "mediana_parquet_D1": R(FLOTA, "capacidad_vehiculos_2025.mediana_parquet_mismos_vehiculos"),
                "capacidad_usada_en_D1_D5": R(FLOTA, "capacidad_vehiculos_2025.capacidad_usada_en_D1_D5")})
C("metodo_ultimo_dia_mes", {"cargados": R(ESTADO_BASE, "cargados"), "pendientes": R(ESTADO_BASE, "pendientes"),
                            "fecha_comprobacion": R(ESTADO_BASE, "fecha_comprobacion")},
  dec=0, extra={"dias_cargados": R(ESTADO_BASE, "dias_cargados"), "dias_pendientes": R(ESTADO_BASE, "dias_pendientes"),
                "viajes_31_enero": R(ESTADO_BASE, "detalle_2025_01_31")})

# ---------------------------------------------------------------------------------------------------------------
# Comprobaciones de cobertura del inventario y salida
# ---------------------------------------------------------------------------------------------------------------
faltan = [i for i in META_INV if i not in AUSENTES and not any(i in DATOS[p] for p in PANTALLAS)]
if faltan:
    raise SystemExit(f"Faltan ids del inventario sin generar: {faltan}")
DATOS["modelo"]["ficha"] = FICHA

ahora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
SALIDA = {
    "meta": {
        "generado": ahora, "version": VERSION, "generador": "app/generar_datos_app.py", "verificador": "app/verificar_datos_app.py",
        "contrato": "app/inventario_cifras.json", "provisional": False,
        "notas": [
            "Cada cifra se lee de su archivo con la clave que trae; «origen» dice de dónde sale cada parte del valor.",
            "Cifras oficiales del modelo con el objetivo original (viajes válidos), horizonte principal h = 7 días. E13 (objetivo corregido) es el siguiente paso y va aparte.",
            "El backtest del sistema en tiempo real es la corrida del 13-10-2026 (plan con costos con fuente), sin revisor independiente.",
            "verificado: «sí» = recalculado por un revisor independiente; «parcial» = archivo revisado pero no esa cifra o esa corrida; «no» = sin revisor.",
        ],
        "ausentes": [{"id": k, "motivo": v} for k, v in AUSENTES.items()],
        "nuevos": [{"id": k, "pantalla": v} for k, v in NUEVOS.items()],
    },
    "pantallas": DATOS,
    "contradicciones": INV["contradicciones"],
}
texto = json.dumps(SALIDA, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
cabecera = ("// Sobusa Despacho · datos de la app. Archivo generado por app/generar_datos_app.py: no editar a mano.\n"
            "// Verificación: PYTHONIOENCODING=utf-8 python app/verificar_datos_app.py\n")
SALIDA_JS.write_text(cabecera + "window.DATOS_APP = " + texto + ";\n", encoding="utf-8")
tam = SALIDA_JS.stat().st_size
if tam > LIMITE_BYTES:
    raise SystemExit(f"datos_app.js pesa {tam} bytes (> 3 MB)")


# ---------------------------------------------------------------------------------------------------------------
# DATOS.md
# ---------------------------------------------------------------------------------------------------------------
def _num(v):
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, float):
        s = f"{v:,.4f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.1f}"
        return s.replace(",", "§").replace(".", ",").replace("§", ".")
    return str(v)


def _corto(c):
    if "filas" in c and "columnas" in c:
        return f"serie: {len(c['filas'])} filas × {len(c['columnas'])} columnas"
    v = c.get("valor")
    if isinstance(v, (int, float, bool)):
        return _num(v)
    if isinstance(v, str):
        return (v[:90] + "…") if len(v) > 90 else v
    if isinstance(v, dict):
        partes = []
        for k, e in list(v.items())[:4]:
            partes.append(f"{k}: {_num(e)}" if isinstance(e, (int, float, bool)) else f"{k}: …")
        return "{" + "; ".join(partes) + ("; …" if len(v) > 4 else "") + "}"
    if isinstance(v, list):
        return f"lista de {len(v)}"
    return ""


def _celda(t):
    return str(t).replace("|", "\\|").replace("\n", " ")


TITULOS = {"inicio": "Inicio · ¿Qué proponemos?", "demanda": "Demanda · ¿Cuántos pasajeros habrá?", "modelo": "Modelo · ¿Qué modelo es y por qué?",
           "horario": "Horario · ¿Cuántos buses y cada cuánto?", "despacho": "Despacho · ¿Qué hago ahora?", "ciudad": "Ciudad · ¿Cómo se ve en la calle?",
           "resultado": "Resultado · ¿Qué gana Sobusa?", "piloto": "Piloto · ¿Cómo lo comprobamos?", "metodo": "Método y datos · ¿De dónde sale todo?"}
md = ["# Datos de la app «Sobusa Despacho»", "",
      f"Generado el {ahora} por `app/generar_datos_app.py` (versión {VERSION}) a partir de los archivos de resultados del proyecto. "
      "Ninguna cifra está escrita a mano: cada una se lee de su archivo con la clave que se indica, y `app/verificar_datos_app.py` "
      "la vuelve a leer con código propio y la compara.", "",
      f"- Archivo: `app/datos_app.js` ({tam / 1024:.0f} KB), objeto `window.DATOS_APP = {{meta, pantallas, contradicciones}}`.",
      "- Contrato de ids: `app/inventario_cifras.json`. La ficha de los dos modelos va en `pantallas.modelo.ficha` (de `app/ficha_modelos.json`).",
      "- Verificación: `PYTHONIOENCODING=utf-8 python app/verificar_datos_app.py` (sale con código 1 si algo no coincide).", "",
      "## Cómo leer una clave", "",
      "- `a.b.c`: claves anidadas; `[\"texto\"]`: clave con espacios o puntos; `[3]`: posición; `[13:16]`: tramo; `[*]`: cada elemento.",
      "- `[columna=valor&otra=valor]`: la única fila (o elemento) que cumple; con `*` al final, todas las que cumplen.",
      "- En un CSV, el archivo es la lista de filas (la columna sin nombre se llama `_`). Los de `costos/`, `simulacion_ahorro/` y "
      "`replay/dias/calles/` usan `;` y coma decimal; el resto, `,` y punto.",
      "- `→ suma`, `→ media`, `→ n`… es la operación sobre la lista; `× 1e-06` pasa COP a millones de COP.",
      "- Los Parquet se filtran, se agrupan y se suman (por ejemplo, la serie diaria de 2025 suma las 17 horas de cada día).",
      "- Los textos de un README se copian tal cual (el verificador comprueba que estén en el archivo).", "",
      "Valores guardados con 2 decimales desde 1.000 y 6 cifras significativas por debajo (las series, con los decimales que se "
      "indican); la app redondea al mostrar con `decimales`.", ""]
for p in PANTALLAS:
    ids = [k for k in DATOS[p] if k != "ficha"]
    md += [f"## {TITULOS[p]} ({len(ids)} cifras)", "",
           "| id | qué es | valor | unidad | archivo | clave | experimento | verificación |", "|---|---|---|---|---|---|---|---|"]
    for k in ids:
        c = DATOS[p][k]
        md.append("| " + " | ".join(_celda(x) for x in (f"`{k}`", c.get("que_es", ""), _corto(c), c.get("unidad", ""), f"`{c['archivo']}`",
                                                           c["clave"][:220] + ("…" if len(c["clave"]) > 220 else ""), c.get("experimento", ""),
                                                           c.get("verificado", ""))) + " |")
    md.append("")
md += ["## Contradicciones entre fuentes (inventario de cifras) y cuál prevalece", "", "| id | tema | fuentes | prevalece |", "|---|---|---|---|"]
for c in INV["contradicciones"]:
    md.append("| " + " | ".join(_celda(c.get(k, "")) for k in ("id", "tema", "fuentes", "prevalece")) + " |")
md += ["", "## Cifras ausentes", "", "Están en el inventario pero no tienen clave en ningún archivo de resultados; la app no las muestra.", "",
       "| id | motivo |", "|---|---|"]
md += [f"| `{k}` | {_celda(v)} |" for k, v in AUSENTES.items()]
md += ["", "## Ids nuevos (no estaban en el inventario)", ""]
md += [f"- `{k}` (pantalla {v}): {DATOS[v][k]['que_es']}" for k, v in NUEVOS.items()]
md.append("")
SALIDA_MD.write_text("\n".join(md), encoding="utf-8")

n = sum(len([k for k in DATOS[p] if k != "ficha"]) for p in PANTALLAS)
print(f"datos_app.js: {tam / 1024:.0f} KB · {n} cifras · ausentes {len(AUSENTES)} · nuevas {len(NUEVOS)}")
for p in PANTALLAS:
    print(f"  {p}: {len([k for k in DATOS[p] if k != 'ficha'])}")
