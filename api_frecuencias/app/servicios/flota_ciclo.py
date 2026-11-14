"""Flota disponible y tiempo de ciclo gobernados por ruta, tipo de día y hora (§3.1 «Gestión operacional»: administrar
los catálogos de vehículo y capacidad; §5.1 «regla de gobierno»; §10.2 «flota disponible» y «duración del ciclo»).

De dónde salen sin ajuste: datos/parametros_operativos_hora.parquet, la mediana 2025 de D1 por ruta, tipo de día y hora
(tiempo_ciclo_min de cada hora y la flota, que es la misma en todas las horas de un tipo de día). Los leen la
recomendación de la franja (optimizacion.contexto_franja) y el plan del día con el modelo activo
(optimizacion._insumos_modelo_activo). La opción de laboratorio E12 del plan usa los de datos/insumos_d5_2025.parquet
(el día de 2025), datos/catalogo_rutas.json trae los del día laboral como respaldo de la franja y
app/servicios/tipologias_flota.json solo reparte la flota de la franja entre tipologías. Cambiarlos exigía regenerar
esos archivos.

Ajuste local versionado, igual que la capacidad (app/servicios/catalogos.py): vive SOLO en ai_frecuencias, como
parámetros del conjunto gobernado threshold_config. Cada cambio crea una versión nueva del conjunto con creado_por,
motivo y creado_en (se aprueba como las demás, con POST /thresholds/{version}/aprobar), y la versión queda en
umbrales_version de cada recomendación y de cada hora del plan.

- flota_override.<idruta>.<TIPO>          vehículos disponibles en ese tipo de día;
- ciclo_override.<idruta>.<TIPO>.<HORA>   minutos de vuelta completa de las salidas de esa hora;

con TIPO = LABORAL, SABADO, DOMINGO_FESTIVO o TODOS y HORA = 4..20 o TODAS. Manda el tipo de día exacto sobre TODOS y,
dentro de cada uno, la hora exacta sobre TODAS; sin ajuste rige el dato empaquetado. Un valor fuera de rango en la
tabla (por ejemplo, escrito a mano con PUT /thresholds) se ignora y queda en el log, como en la capacidad.
"""
from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("api_frecuencias.flota_ciclo")

PREFIJO_FLOTA = "flota_override"
PREFIJO_CICLO = "ciclo_override"
PREFIJOS = (PREFIJO_FLOTA + ".", PREFIJO_CICLO + ".")
TODOS = "TODOS"
TODAS = "TODAS"
TIPOS = {"Laboral": "LABORAL", "Sábado": "SABADO", "Domingo/festivo": "DOMINGO_FESTIVO"}
NOMBRES = {**{token: nombre for nombre, token in TIPOS.items()}, TODOS: TODOS}
HORAS = tuple(range(4, 21))
PARAMETROS = {"flota": PREFIJO_FLOTA, "tiempo_ciclo_min": PREFIJO_CICLO}
LARGO_CLAVE = {PREFIJO_FLOTA: 3, PREFIJO_CICLO: 4}
FLOTA_MIN, FLOTA_MAX = 1, 1000               # vehículos
CICLO_MIN, CICLO_MAX = 10.0, 720.0           # minutos de vuelta completa
CATALOGO = "catalogo"
AJUSTE_LOCAL = "ajuste_local"
FUENTE_CATALOGO = "datos/parametros_operativos_hora.parquet (mediana 2025 de D1 por ruta, tipo de día y hora)"


# ---------------------------------------------------------------- claves
def token_tipo(tipo_dia: str | None) -> str:
    """Laboral, Sábado, Domingo/festivo o TODOS (también su token: LABORAL, SABADO...) -> el token de la clave."""
    texto = (tipo_dia or TODOS).strip()
    token = TIPOS.get(texto, texto.upper())
    if token not in NOMBRES:
        raise ValueError("tipo_dia debe ser Laboral, Sábado, Domingo/festivo o TODOS")
    return token


def token_hora(hora: int | None) -> str:
    """Hora de salida 4..20 -> su texto; sin hora, TODAS (todas las horas de servicio)."""
    if hora is None:
        return TODAS
    if int(hora) not in HORAS:
        raise ValueError("hora debe ser un entero de 4 a 20 (sin hora, todas las horas de servicio)")
    return str(int(hora))


def clave_flota(idruta: int, tipo_dia: str | None = None) -> str:
    return f"{PREFIJO_FLOTA}.{int(idruta)}.{token_tipo(tipo_dia)}"


def clave_ciclo(idruta: int, tipo_dia: str | None = None, hora: int | None = None) -> str:
    return f"{PREFIJO_CICLO}.{int(idruta)}.{token_tipo(tipo_dia)}.{token_hora(hora)}"


def es_clave(nombre: str) -> bool:
    """True si el parámetro de threshold_config es un ajuste de flota o de ciclo."""
    return str(nombre).startswith(PREFIJOS)


def _hora_valida(texto: str) -> bool:
    return texto == TODAS or (texto.isdigit() and int(texto) in HORAS)


def partes(nombre: str) -> tuple[str, int, str, str | None] | None:
    """(parámetro, idruta, token del tipo de día, hora o TODAS) de una clave de ajuste; None si está mal formada.
    El parámetro es «flota» o «tiempo_ciclo_min» (la flota no tiene hora)."""
    trozos = str(nombre).split(".")
    largo = LARGO_CLAVE.get(trozos[0])
    if largo is None or len(trozos) != largo or not trozos[1].isdigit() or trozos[2] not in NOMBRES:
        return None
    hora = trozos[3] if largo == 4 else None
    if hora is not None and not _hora_valida(hora):
        return None
    parametro = "flota" if trozos[0] == PREFIJO_FLOTA else "tiempo_ciclo_min"
    return parametro, int(trozos[1]), trozos[2], hora


# ---------------------------------------------------------------- valores
def valor_valido(parametro: str, valor: Any) -> float | int:
    """El valor del ajuste validado (ValueError con el motivo): la flota, un entero de 1 a 1000 vehículos; el ciclo,
    entre 10 y 720 minutos."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{parametro} debe ser numérico (recibido: {valor!r})") from None
    if parametro == "flota":
        if not (numero.is_integer() and FLOTA_MIN <= numero <= FLOTA_MAX):
            raise ValueError(f"flota debe ser un entero de {FLOTA_MIN} a {FLOTA_MAX} vehículos (recibido: {valor})")
        return int(numero)
    if not (math.isfinite(numero) and CICLO_MIN <= numero <= CICLO_MAX):
        raise ValueError(f"tiempo_ciclo_min debe estar entre {CICLO_MIN:g} y {CICLO_MAX:g} min (recibido: {valor})")
    return numero


def _ajuste_o_nada(nombre: str, valor: Any) -> float | int | None:
    """El valor de un ajuste de la tabla, o None (y una línea en el log) si la clave o el valor no sirven."""
    trozos = partes(nombre)
    try:
        if trozos is None:
            raise ValueError("clave mal formada")
        return valor_valido(trozos[0], valor)
    except ValueError as exc:
        log.warning("Ajuste de flota o ciclo ignorado: %s (%s)", nombre, exc)
        return None


def ajustes(umbrales: dict[str, Any] | None) -> dict[str, float | int]:
    """{clave: valor} de los ajustes de flota y ciclo vigentes y válidos; los inválidos se ignoran y van al log."""
    salida = {}
    for nombre, valor in (umbrales or {}).items():
        if es_clave(nombre) and (bueno := _ajuste_o_nada(nombre, valor)) is not None:
            salida[nombre] = bueno
    return salida


def validar_ajustes(valores: dict[str, Any]) -> None:
    """Valida los ajustes de flota y ciclo que traiga un cambio de umbrales (PUT /thresholds); ValueError si alguno no
    sirve."""
    for nombre, valor in valores.items():
        if not es_clave(nombre):
            continue
        trozos = partes(nombre)
        if trozos is None:
            raise ValueError(f"Ajuste de flota o ciclo mal formado: {nombre}")
        valor_valido(trozos[0], valor)


# ---------------------------------------------------------------- lectura del ajuste vigente
def claves_flota(idruta: int, tipo_dia: str) -> list[str]:
    """Del más específico al más general: el tipo de día y TODOS."""
    return [clave_flota(idruta, tipo_dia), clave_flota(idruta, TODOS)]


def claves_ciclo(idruta: int, tipo_dia: str, hora: int) -> list[str]:
    """Del más específico al más general: tipo de día y hora, tipo de día (todas las horas), TODOS y hora, TODOS. Una
    hora fuera de 4..20 solo toma los ajustes de todas las horas."""
    tipos = (tipo_dia, TODOS)
    horas = (hora, None) if int(hora) in HORAS else (None,)
    return [clave_ciclo(idruta, t, h) for t in tipos for h in horas]


def elegir(aj: dict[str, Any], claves: list[str]) -> dict | None:
    """El primer ajuste vigente de la lista (del más específico al más general), con su clave."""
    clave = next((c for c in claves if c in aj), None)
    return None if clave is None else {"valor": aj[clave], "fuente": AJUSTE_LOCAL, "clave": clave}


def idruta_de(info: dict | None, ruta: str | None = None) -> int | None:
    """idruta de la ruta (el del dict del catálogo o, por el nombre, el del catálogo empaquetado); None si no está."""
    if info and info.get("idruta") is not None:
        return int(info["idruta"])
    from app.servicios import datos

    try:
        return int(datos.ruta_info(str(ruta))["idruta"])
    except (KeyError, TypeError, ValueError):
        return None


def de_la_franja(idruta: int | None, tipo_dia: str, hora: int, umbrales: dict | None,
                 version: int | None) -> dict[str, dict]:
    """Ajustes vigentes de una franja (ruta, tipo de día, hora): {"flota_disponible": {...}, "tiempo_ciclo_min":
    {...}}, solo los que existen, cada uno con valor, fuente «ajuste_local», clave y umbrales_version."""
    aj = ajustes(umbrales)
    if idruta is None or not aj:
        return {}
    elegidos = {"flota_disponible": elegir(aj, claves_flota(idruta, tipo_dia)),
                "tiempo_ciclo_min": elegir(aj, claves_ciclo(idruta, tipo_dia, hora))}
    return {campo: dict(e, umbrales_version=version) for campo, e in elegidos.items() if e}


def del_dia(idruta: int | None, tipo_dia: str, umbrales: dict | None, version: int | None) -> dict | None:
    """Ajustes vigentes de un día para el plan: {"flota": {...} o None, "ciclo": {hora: {...}}, "umbrales_version"};
    None si la ruta no tiene ninguno ese tipo de día."""
    aj = ajustes(umbrales)
    if idruta is None or not aj:
        return None
    flota = elegir(aj, claves_flota(idruta, tipo_dia))
    ciclo = {h: e for h in HORAS if (e := elegir(aj, claves_ciclo(idruta, tipo_dia, h)))}
    if flota is None and not ciclo:
        return None
    return {"flota": flota, "ciclo": ciclo, "umbrales_version": version}


# ---------------------------------------------------------------- vista vigente (GET /catalogos/flota)
def _positivo(valor: Any) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) and numero > 0 else None


def _cifra(base: float | None, elegido: dict | None) -> dict:
    """La cifra vigente: el ajuste local si hay, o el dato empaquetado, con su fuente y su clave."""
    if elegido:
        return {"valor": elegido["valor"], "catalogo": base, "fuente": AJUSTE_LOCAL, "clave": elegido["clave"]}
    return {"valor": base, "catalogo": base, "fuente": CATALOGO, "clave": None}


def _entero(valor: float | None) -> int | None:
    return None if valor is None else int(round(valor))


def _redondo(valor: float | None) -> float | None:
    return None if valor is None else round(float(valor), 2)


def _hora_vigente(idruta: int, tipo_dia: str, hora: int, ciclo_base: float | None, aj: dict) -> dict:
    ciclo = _cifra(ciclo_base, elegir(aj, claves_ciclo(idruta, tipo_dia, hora)))
    return {"hora": hora, "tiempo_ciclo_min": _redondo(ciclo["valor"]),
            "tiempo_ciclo_catalogo_min": _redondo(ciclo["catalogo"]), "fuente": ciclo["fuente"],
            "clave": ciclo["clave"]}


def _tipo_vigente(idruta: int, tipo_dia: str, filas, aj: dict) -> dict:
    """Flota y ciclo por hora de una ruta en un tipo de día (filas de parametros_operativos_hora)."""
    base = _positivo(filas["flota"].max()) if len(filas) else None
    flota = _cifra(base, elegir(aj, claves_flota(idruta, tipo_dia)))
    horas = [_hora_vigente(idruta, tipo_dia, int(f.hora), _positivo(f.tiempo_ciclo_min), aj)
             for f in filas.sort_values("hora").itertuples(index=False)]
    return {"tipo_dia": tipo_dia, "flota": _entero(flota["valor"]), "flota_catalogo": _entero(base),
            "flota_fuente": flota["fuente"], "flota_clave": flota["clave"], "horas": horas}


def _ruta_vigente(info: dict, tipos: list[str], aj: dict, version: int | None) -> dict:
    from app.servicios import datos

    idruta = int(info["idruta"])
    p = datos.parametros_operativos(info["ruta"])
    propios = {k: v for k, v in sorted(aj.items()) if partes(k)[1] == idruta}
    return {"ruta": info["ruta"], "idruta": idruta, "umbrales_version": version,
            "por_tipo_dia": [_tipo_vigente(idruta, t, p[p["tipo_dia"] == t], aj) for t in tipos],
            "ajustes": propios}


def vigente(idruta: int | None = None, tipo_dia: str | None = None, *, umbrales: dict | None,
            umbrales_version: int | None) -> list[dict]:
    """Flota disponible y ciclo vigentes por ruta, tipo de día y hora: el dato empaquetado y, encima, el ajuste local,
    con la fuente y la clave de cada cifra. KeyError si la ruta no existe; ValueError si el tipo de día no es válido."""
    from app.servicios import catalogos

    rutas = [r for r in catalogos.rutas_api() if idruta is None or int(r["idruta"]) == int(idruta)]
    if idruta is not None and not rutas:
        raise KeyError(f"ruta {idruta} no existe en el catálogo")
    token = token_tipo(tipo_dia)
    tipos = list(TIPOS) if token == TODOS else [NOMBRES[token]]
    aj = ajustes(umbrales)
    return [_ruta_vigente(r, tipos, aj, umbrales_version) for r in rutas]


# ---------------------------------------------------------------- cambio versionado e historial
def _descripcion(nombre: str) -> str:
    parametro, idruta, tipo, hora = partes(nombre)
    if parametro == "flota":
        return (f"§3.1 Ajuste local: flota disponible de la ruta {idruta} en {NOMBRES[tipo]} (vehículos; solo en "
                "ai_frecuencias)")
    cuando = "todas las horas" if hora == TODAS else f"las salidas de las {hora} h"
    return (f"§3.1 Ajuste local: tiempo de ciclo de la ruta {idruta} en {NOMBRES[tipo]}, {cuando} (minutos de vuelta "
            "completa; solo en ai_frecuencias)")


def _claves_del_cambio(idruta: int, tipo_dia: str | None, hora: int | None, cambios: dict[str, Any]) -> dict[str, str]:
    """La clave de threshold_config de cada parámetro que cambia (ValueError si el pedido no tiene sentido)."""
    if not cambios or set(cambios) - set(PARAMETROS):
        raise ValueError("indique flota, tiempo_ciclo_min o ambos (null retira el ajuste)")
    if hora is not None and "tiempo_ciclo_min" not in cambios:
        raise ValueError("hora solo aplica al tiempo de ciclo: la flota es la del tipo de día")
    return {"flota": clave_flota(idruta, tipo_dia), "tiempo_ciclo_min": clave_ciclo(idruta, tipo_dia, hora)}


def fijar(sesion, idruta: int, tipo_dia: str | None, hora: int | None, cambios: dict[str, Any], creado_por: str,
          motivo: str) -> int:
    """Registra una versión nueva del conjunto gobernado con la flota y/o el ciclo (`cambios` = {parámetro: valor};
    None retira el ajuste). KeyError si la ruta no existe, LookupError si se retira un ajuste que no está vigente y
    ValueError si el pedido o un valor no sirve. Devuelve la versión nueva."""
    from app.servicios import catalogos

    catalogos.ruta_info(idruta)                  # integridad referencial hacia una ruta autorizada (RF-014)
    if not motivo or not motivo.strip():
        raise ValueError("motivo es obligatorio para un ajuste de flota o de ciclo")
    claves = _claves_del_cambio(idruta, tipo_dia, hora, cambios)
    valores = {claves[p]: None if v is None else valor_valido(p, v) for p, v in cambios.items()}
    return catalogos.versionar_ajustes(sesion, valores, creado_por, motivo, _descripcion)


def _evento(e: dict, nombres_ruta: dict[int, str]) -> dict:
    parametro, idruta, tipo, hora = partes(e["nombre"])
    return {"version": e["version"], "idruta": idruta, "ruta": nombres_ruta.get(idruta), "parametro": parametro,
            "tipo_dia": NOMBRES[tipo], "hora": None if hora in (None, TODAS) else int(hora), "accion": e["accion"],
            "valor_anterior": e["antes"], "valor_nuevo": e["despues"], "creado_por": e["creado_por"],
            "motivo": e["motivo"], "creado_en": e["creado_en"]}


def historial(sesion, idruta: int | None = None) -> list[dict]:
    """Cambios de la flota y del ciclo, versión por versión (creado, cambiado o retirado), con el valor anterior y el
    nuevo, quién y por qué; del más reciente al más antiguo."""
    from app.servicios import catalogos

    nombres_ruta = {int(r["idruta"]): r["ruta"] for r in catalogos.rutas_api()}
    eventos = [e for e in catalogos.eventos_ajustes(sesion, PREFIJOS) if partes(e["nombre"]) is not None]
    salida = [_evento(e, nombres_ruta) for e in eventos]
    return [e for e in reversed(salida) if idruta is None or e["idruta"] == int(idruta)]


__all__ = ["PREFIJO_FLOTA", "PREFIJO_CICLO", "TODOS", "TODAS", "TIPOS", "HORAS", "PARAMETROS", "FLOTA_MIN",
           "FLOTA_MAX", "CICLO_MIN", "CICLO_MAX", "clave_flota", "clave_ciclo", "ajustes", "validar_ajustes",
           "de_la_franja", "del_dia", "vigente", "fijar", "historial", "idruta_de"]
