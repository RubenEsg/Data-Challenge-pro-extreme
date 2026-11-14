"""Retención automática de datos (§18 «Exposición de datos → retención») contra la base LOCAL de pruebas.

Siembra filas y particiones a ambos lados del corte (13 meses antes de ahora) en el esquema ai_frecuencias y unas
tablas centinela con los mismos nombres en otro esquema, y prueba que la tarea:
- en simulación no borra nada y deja en la bitácora (retencion_registro) lo que borraría;
- aplicada borra SOLO lo anterior al corte y SOLO en ai_frecuencias: las particiones mensuales viejas de
  feature_snapshot con DETACH y DROP (o archivadas), los resultados, las alertas cerradas y las ejecuciones que ya no
  sostienen nada; conserva las alertas abiertas, lo que sostiene una marca de agua, un modelo o un resultado nuevo,
  la última marca de los refrescos y las madres de una ejecución partida con trabajos que se conservan;
- pospone una partición si un ciclo tiene sus candados (lock_timeout) y la separa en la corrida siguiente, y en un
  interbloqueo con un ciclo cede ella (lock_timeout menor que deadlock_timeout): PostgreSQL no aborta al ciclo;
- archiva una partición sin sus llaves foráneas, así que borrar su predicción vieja no vacía el archivo, y si el
  mismo mes se vuelve a archivar el archivo nuevo no choca con el anterior (<partición>_archivo_2);
- conserva la partición vieja con una foto de una predicción que la regla de resultados conserva (una foto vive lo
  que vive su predicción) y la separa cuando esa predicción ya no se conserva;
- es un trabajo de la cola (202 con el execution_id, rol admin), lo programa el planificador y sus parámetros se
  gobiernan en threshold_config (PUT /thresholds los valida; con retencion_aplicar_programada = 0 la corrida
  programada solo simula; la prueba deja threshold_config como lo encontró); y la migración 0012 sube y baja.
"""
from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

from app.modelos_db import Ejecucion, RegistroRetencion, Umbral
from tests.evidencia import guardar_evidencia
from tests.integracion.conftest import restituir_umbrales

E = "ai_frecuencias"
CENTINELA = "retencion_centinela"
AHORA = datetime.now(UTC)
VIEJO = AHORA - timedelta(days=430)            # antes del corte de 13 meses
NUEVO = AHORA - timedelta(days=330)            # después del corte
SOLO_FOTO = {"retencion_meses_foto": 13, "retencion_meses_resultados": 0, "retencion_meses_alertas": 0,
             "retencion_meses_ejecuciones": 0, "retencion_archivar_particiones": 0, "retencion_aplicar_programada": 1}


def _politica(**cambios) -> dict[str, int]:
    from app.servicios import retencion

    return {**retencion.politica_de(None), **cambios}


# ---------------------------------------------------------------- siembra
class Siembra:
    """Filas sembradas con una etiqueta propia (ruta, correlation_id, proceso o model_id) para encontrarlas y
    borrarlas."""

    def __init__(self, s):
        self.s = s
        self.tag = uuid.uuid4().hex[:8]
        self.ruta = f"RET-{self.tag}"
        self.ids: dict[str, object] = {}

    def ejecucion(self, nombre: str, creado_en: datetime, estado: str = "ok", tipo: str = "frecuencia", **extra):
        eid = uuid.uuid4()
        self.s.execute(text(
            f"INSERT INTO {E}.execution_log (execution_id, tipo, estado, progreso, intentos, parametros, metricas, "
            "correlation_id, creado_en, padre_id, particion, ruta, disponible_desde) VALUES (:i, :t, :e, 0, 0, "
            "CAST(:par AS jsonb), '{}'::jsonb, :c, :f, :padre, :particion, :ruta, :disp)"),
            {"i": eid, "t": tipo, "e": estado, "c": f"retencion-{self.tag}", "f": creado_en,
             "par": json.dumps(extra.get("parametros") or {}), "padre": extra.get("padre_id"),
             "particion": extra.get("particion"), "ruta": extra.get("ruta"), "disp": extra.get("disponible_desde")})
        self.ids[nombre] = eid
        return eid

    def prediccion(self, nombre: str, creado_en: datetime, execution_id=None, instante: datetime | None = None):
        pid = uuid.uuid4()
        instante = instante or creado_en
        self.s.execute(text(
            f"INSERT INTO {E}.prediction (prediction_id, execution_id, ruta, instante, horizonte_min, objetivo, fecha, "
            "hora, pasajeros, model_id, generated_at, creado_en) VALUES (:p, :e, :r, :i, 60, :o, :d, 7, 10, 'ret', :i, "
            ":c)"), {"p": pid, "e": execution_id, "r": self.ruta, "i": instante, "o": instante + timedelta(hours=1),
                     "d": instante.date(), "c": creado_en})
        self.ids[nombre] = pid
        return pid

    def foto(self, prediction_id, ventana_inicio: datetime, creado_en: datetime) -> None:
        self.s.execute(text(f"SELECT {E}.asegurar_particion_feature_snapshot(:t)"), {"t": ventana_inicio})
        self.s.execute(text(
            f"INSERT INTO {E}.feature_snapshot (prediction_id, ruta, ventana_inicio, ventana_fin, fecha, hora, "
            "features, feature_version, creado_en) VALUES (:p, :r, :v, :v, :d, 7, '{}'::jsonb, 'fv-ret', :c)"),
            {"p": prediction_id, "r": self.ruta, "v": ventana_inicio, "d": ventana_inicio.date(), "c": creado_en})

    def recomendacion(self, nombre: str, creado_en: datetime, prediction_id=None, execution_id=None) -> None:
        rid = uuid.uuid4()
        self.s.execute(text(
            f"INSERT INTO {E}.recommendation (recommendation_id, execution_id, prediction_id, ruta, fecha, hora, "
            "creado_en) VALUES (:i, :e, :p, :r, :d, 7, :c)"),
            {"i": rid, "e": execution_id, "p": prediction_id, "r": self.ruta, "d": creado_en.date(), "c": creado_en})
        self.ids[nombre] = rid

    def alerta(self, nombre: str, estado: str, actualizado_en: datetime, execution_id=None):
        aid = uuid.uuid4()
        self.s.execute(text(
            f"INSERT INTO {E}.alert (alert_id, codigo, execution_id, ruta, detectada_en, severidad, estado, "
            "clave_dedup, creado_en, actualizado_en) VALUES (:a, 'ALT-002', :e, :r, :f, 'critica', :s, :k, :f, :f)"),
            {"a": aid, "e": execution_id, "r": self.ruta, "f": actualizado_en, "s": estado,
             "k": f"ret|{self.tag}|{nombre}"})
        self.s.execute(text(f"INSERT INTO {E}.alert_history (alert_id, accion, estado_nuevo, usuario, creado_en) "
                            "VALUES (:a, 'crear', :s, 'retencion', :f)"), {"a": aid, "s": estado, "f": actualizado_en})
        self.ids[nombre] = aid
        return aid

    def notificacion(self, nombre: str, creado_en: datetime, alert_id=None, execution_id=None) -> None:
        nid = self.s.execute(text(
            f"INSERT INTO {E}.notification_log (execution_id, alert_id, canal, asunto, creado_en) "
            "VALUES (:e, :a, 'correo', :t, :c) RETURNING id"),
            {"e": execution_id, "a": alert_id, "t": f"retencion-{self.tag}", "c": creado_en}).scalar()
        self.ids[nombre] = nid

    def respuesta(self, nombre: str, generado_en: datetime) -> None:
        qid = self.s.execute(text(
            f"INSERT INTO {E}.respuesta_reto (fecha, ruta, payload, model_id, generado_en) VALUES "
            "(:f, :r, '{}'::jsonb, :m, :g) RETURNING id"),
            {"f": generado_en.date(), "r": self.ruta, "m": f"ret-{nombre}", "g": generado_en}).scalar()
        self.ids[nombre] = qid

    def refresco(self, nombre: str, modo: str, actualizado_en: datetime) -> None:
        rid = self.s.execute(text(
            f"INSERT INTO {E}.segmento_estadistica_refresco (modo, actualizado_en, huella_catalogos) "
            "VALUES (:m, :a, :h) RETURNING id"), {"m": modo, "a": actualizado_en, "h": f"ret-{self.tag}"}).scalar()
        self.ids[nombre] = rid

    def marca(self, execution_id) -> None:
        self.s.execute(text(f"INSERT INTO {E}.marca_agua_ruta (proceso, ruta, marca_agua, execution_id) VALUES "
                            "(:p, :r, :m, :e)"), {"p": f"ret-{self.tag}", "r": str(execution_id), "m": VIEJO,
                                                  "e": execution_id})

    def modelo(self, execution_id) -> None:
        self.s.execute(text(f"INSERT INTO {E}.model_registry (model_id, version, tipo, artefacto, sha256, "
                            "feature_version, estado, execution_id) VALUES (:m, 'v', 'candidato', 'x', 'x', 'fv', "
                            "'candidato', :e)"), {"m": f"ret-{self.tag}", "e": execution_id})

    def limpiar(self) -> None:
        s = self.s
        s.rollback()
        for sql in (f"DELETE FROM {E}.notification_log WHERE asunto = :t",
                    f"DELETE FROM {E}.recommendation WHERE ruta = :r", f"DELETE FROM {E}.alert WHERE ruta = :r",
                    f"DELETE FROM {E}.feature_snapshot WHERE ruta = :r", f"DELETE FROM {E}.prediction WHERE ruta = :r",
                    f"DELETE FROM {E}.respuesta_reto WHERE ruta = :r",
                    f"DELETE FROM {E}.segmento_estadistica_refresco WHERE huella_catalogos = :h",
                    f"DELETE FROM {E}.marca_agua_ruta WHERE proceso = :p", f"DELETE FROM {E}.model_registry "
                    "WHERE model_id = :p", f"DELETE FROM {E}.execution_log WHERE correlation_id = :c"):
            s.execute(text(sql), {"t": f"retencion-{self.tag}", "r": self.ruta, "h": f"ret-{self.tag}",
                                  "p": f"ret-{self.tag}", "c": f"retencion-{self.tag}"})
        s.commit()


def _existe(s, tabla: str, llave: str, valor) -> bool:
    return s.execute(text(f"SELECT count(*) FROM {E}.{tabla} WHERE {llave} = :v"), {"v": valor}).scalar() == 1


def _particion(s, nombre: str) -> tuple[bool, bool]:
    """(existe la tabla, es partición de feature_snapshot). Lee pg_class con una instantánea nueva (to_regclass puede
    responder con la caché de catálogo de la sesión, sin ver un DROP que otra sesión acaba de confirmar)."""
    existe = s.execute(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = :e AND c.relname = :n"), {"e": E, "n": nombre}).scalar() == 1
    adjunta = s.execute(text("SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                             "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'feature_snapshot' "
                             "AND c.relname = :n AND c.relnamespace = CAST(:e AS regnamespace)"),
                        {"n": nombre, "e": E}).scalar() == 1
    return bool(existe), adjunta


def _borrar_particion(s, nombre: str) -> None:
    s.rollback()
    s.execute(text(f'DROP TABLE IF EXISTS {E}."{nombre}"'))
    s.commit()


@pytest.fixture
def centinela(migrada):
    """Tablas con los mismos nombres en otro esquema (con filas y una partición viejas): la retención no las toca."""
    motor = create_engine(migrada)
    with motor.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {CENTINELA} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {CENTINELA}"))
        c.execute(text(f"CREATE TABLE {CENTINELA}.execution_log (execution_id uuid PRIMARY KEY, estado text, "
                       f"creado_en timestamptz); CREATE TABLE {CENTINELA}.prediction (prediction_id uuid PRIMARY KEY, "
                       f"creado_en timestamptz); CREATE TABLE {CENTINELA}.feature_snapshot (id bigint, ventana_inicio "
                       f"timestamptz, creado_en timestamptz) PARTITION BY RANGE (ventana_inicio); CREATE TABLE "
                       f"{CENTINELA}.feature_snapshot_201901 PARTITION OF {CENTINELA}.feature_snapshot FOR VALUES "
                       "FROM ('2019-01-01 00:00+00') TO ('2019-02-01 00:00+00')"))
        c.execute(text(f"INSERT INTO {CENTINELA}.execution_log VALUES (:i, 'ok', :f)"), {"i": uuid.uuid4(), "f": VIEJO})
        c.execute(text(f"INSERT INTO {CENTINELA}.prediction VALUES (:i, :f)"), {"i": uuid.uuid4(), "f": VIEJO})
        c.execute(text(f"INSERT INTO {CENTINELA}.feature_snapshot VALUES (1, '2019-01-15 00:00+00', :f)"),
                  {"f": VIEJO})
    yield motor
    with motor.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {CENTINELA} CASCADE"))
    motor.dispose()


def _filas_centinela(motor) -> tuple[int, int, int, bool]:
    with motor.connect() as c:
        return (c.execute(text(f"SELECT count(*) FROM {CENTINELA}.execution_log")).scalar(),
                c.execute(text(f"SELECT count(*) FROM {CENTINELA}.prediction")).scalar(),
                c.execute(text(f"SELECT count(*) FROM {CENTINELA}.feature_snapshot")).scalar(),
                c.execute(text(f"SELECT to_regclass('{CENTINELA}.feature_snapshot_201901') IS NOT NULL")).scalar())


def _sembrar_todo(s) -> Siembra:
    """Un caso de cada regla a cada lado del corte (ver el docstring del módulo). Las marcas de refresco de otras
    pruebas se quitan antes: la última marca y la del último completo deben ser las sembradas."""
    s.execute(text(f"DELETE FROM {E}.segmento_estadistica_refresco"))
    x = Siembra(s)
    viejo_ok = x.ejecucion("ejecucion_vieja", VIEJO)                       # la sostiene una predicción vieja
    x.ejecucion("ejecucion_vieja_error", VIEJO, estado="error")
    x.ejecucion("ejecucion_vieja_en_cola", VIEJO, estado="en_cola", tipo="respuesta",
                disponible_desde=datetime(2099, 1, 1, tzinfo=UTC))
    x.marca(x.ejecucion("ejecucion_con_marca", VIEJO))
    x.modelo(x.ejecucion("ejecucion_con_modelo", VIEJO))
    con_resultado = x.ejecucion("ejecucion_con_resultado_nuevo", VIEJO)
    x.ejecucion("ejecucion_nueva", NUEVO)
    madre = x.ejecucion("madre_borrable", VIEJO, particion="ruta")
    x.ejecucion("trabajo_borrable_1", VIEJO, padre_id=madre, ruta="SILENCIO")
    x.ejecucion("trabajo_borrable_2", VIEJO, padre_id=madre, ruta="CL 72")
    otra_madre = x.ejecucion("madre_con_trabajo_protegido", VIEJO, particion="ruta")
    x.marca(x.ejecucion("trabajo_con_marca", VIEJO, padre_id=otra_madre, ruta="SILENCIO"))
    x.ejecucion("trabajo_borrable_3", VIEJO, padre_id=otra_madre, ruta="CL 72")
    # resultados
    vieja = x.prediccion("prediccion_vieja", VIEJO, viejo_ok, instante=datetime(2019, 1, 15, 7, tzinfo=UTC))
    x.foto(vieja, datetime(2019, 1, 15, 7, tzinfo=UTC), VIEJO)                 # partición 2019-01: entera vieja
    x.recomendacion("recomendacion_vieja", VIEJO, vieja, viejo_ok)
    sostenida = x.prediccion("prediccion_vieja_con_recomendacion_nueva", VIEJO)
    x.recomendacion("recomendacion_nueva", NUEVO, sostenida)
    nueva = x.prediccion("prediccion_nueva", NUEVO, con_resultado, instante=datetime(2019, 2, 15, 7, tzinfo=UTC))
    x.foto(nueva, datetime(2019, 2, 15, 7, tzinfo=UTC), NUEVO)               # partición 2019-02: una fila reciente
    x.respuesta("respuesta_vieja", VIEJO)
    x.respuesta("respuesta_nueva", NUEVO)
    x.refresco("ultimo_completo_viejo", "completo", VIEJO - timedelta(days=2))
    x.refresco("refresco_viejo", "incremental", VIEJO)
    x.refresco("refresco_nuevo", "incremental", NUEVO)
    # alertas
    x.alerta("alerta_cerrada_vieja", "cerrada", VIEJO)
    x.alerta("alerta_abierta_vieja", "nueva", VIEJO)
    x.alerta("alerta_cerrada_nueva", "descartada", NUEVO)
    con_aviso = x.alerta("alerta_cerrada_vieja_con_notificacion_nueva", "cerrada", VIEJO)
    x.notificacion("notificacion_vieja", VIEJO)
    x.notificacion("notificacion_nueva", NUEVO, con_aviso)
    s.commit()
    return x


BORRADAS = {"execution_log": ["ejecucion_vieja", "ejecucion_vieja_error", "madre_borrable", "trabajo_borrable_1",
                              "trabajo_borrable_2", "trabajo_borrable_3"],
            "prediction": ["prediccion_vieja"], "recommendation": ["recomendacion_vieja"],
            "respuesta_reto": ["respuesta_vieja"], "segmento_estadistica_refresco": ["refresco_viejo"],
            "alert": ["alerta_cerrada_vieja"], "notification_log": ["notificacion_vieja"]}
CONSERVADAS = {"execution_log": ["ejecucion_vieja_en_cola", "ejecucion_con_marca", "ejecucion_con_modelo",
                                 "ejecucion_con_resultado_nuevo", "ejecucion_nueva", "madre_con_trabajo_protegido",
                                 "trabajo_con_marca"],
               "prediction": ["prediccion_vieja_con_recomendacion_nueva", "prediccion_nueva"],
               "recommendation": ["recomendacion_nueva"], "respuesta_reto": ["respuesta_nueva"],
               "segmento_estadistica_refresco": ["ultimo_completo_viejo", "refresco_nuevo"],
               "alert": ["alerta_abierta_vieja", "alerta_cerrada_nueva", "alerta_cerrada_vieja_con_notificacion_nueva"],
               "notification_log": ["notificacion_nueva"]}
LLAVES = {"execution_log": "execution_id", "prediction": "prediction_id", "recommendation": "recommendation_id",
          "respuesta_reto": "id", "segmento_estadistica_refresco": "id", "alert": "alert_id", "notification_log": "id"}


def _evidencia(nombre: str, r: dict, x: Siembra, borradas: bool) -> None:
    """La corrida (resumen de la tarea) y lo que pasó con cada fila sembrada, en docs/evidencias/retencion/."""
    sembradas = {tabla: {n: ("borrada" if borradas else "conservada") for n in nombres}
                 for tabla, nombres in BORRADAS.items()}
    for tabla, nombres in CONSERVADAS.items():
        sembradas.setdefault(tabla, {}).update(dict.fromkeys(nombres, "conservada"))
    acciones = [a for a in r["acciones"] if not str(a["objeto"]).startswith("feature_snapshot_2")
                or a["objeto"] in ("feature_snapshot_201901", "feature_snapshot_201902")]
    guardar_evidencia(f"retencion/{nombre}.json", {
        "prueba": f"tests/integracion/test_retencion.py ({nombre})", "ahora": AHORA, "sembrado_viejo": VIEJO,
        "sembrado_nuevo": NUEVO, "simulado": r["simulado"], "cortes": r["cortes"], "politica": r["politica"],
        "totales": {k: r[k] for k in ("filas", "particiones", "filas_particiones", "bytes_particiones", "pospuestas")},
        "acciones": acciones, "filas_sembradas": sembradas,
        "centinela": "las tablas execution_log, prediction y feature_snapshot (con su partición 201901) del esquema "
                     f"{CENTINELA} quedaron intactas"})


def _registro(s, execution_id) -> list[RegistroRetencion]:
    s.expire_all()
    return list(s.scalars(select(RegistroRetencion).where(RegistroRetencion.execution_id == execution_id)
                          .order_by(RegistroRetencion.id)).all())


# ---------------------------------------------------------------- simulación y aplicación
def test_simulacion_no_borra_nada_y_deja_en_la_bitacora_lo_que_borraria(sesion, centinela):
    from app.servicios import retencion

    x = _sembrar_todo(sesion)
    corrida = uuid.uuid4()
    try:
        r = retencion.aplicar(_politica(), simular=True, ahora=AHORA, execution_id=corrida)
        assert r["simulado"] and r["filas"] >= sum(len(v) for v in BORRADAS.values()) and r["particiones"] >= 1
        for tabla, nombres in {**BORRADAS, **CONSERVADAS}.items():
            for nombre in nombres:
                assert _existe(sesion, tabla, LLAVES[tabla], x.ids[nombre]), (tabla, nombre)
        assert _particion(sesion, "feature_snapshot_201901") == (True, True)
        bitacora = _registro(sesion, corrida)
        assert bitacora and all(f.simulado for f in bitacora)
        por_objeto = {f.objeto: f for f in bitacora}
        assert por_objeto["feature_snapshot_201901"].accion == "separar_y_borrar"
        assert por_objeto["feature_snapshot_201901"].filas == 1 and por_objeto["feature_snapshot_201901"].bytes > 0
        assert por_objeto["feature_snapshot_201902"].accion == "conservar"          # tiene una fila reciente
        # la simulación cuenta también la ejecución que solo queda libre al borrar su predicción vieja
        assert por_objeto["execution_log"].filas >= len(BORRADAS["execution_log"])
        assert por_objeto["segmento_estadistica_dia"].accion == "conservar"
        assert por_objeto["segmento_estadistica_dia"].grupo == "derivada"
        assert _filas_centinela(centinela) == (1, 1, 1, True)
        _evidencia("corrida_simulada", r, x, borradas=False)
    finally:
        x.limpiar()
        _borrar_particion(sesion, "feature_snapshot_201901")
        _borrar_particion(sesion, "feature_snapshot_201902")


def test_aplicada_borra_solo_lo_anterior_al_corte_y_solo_en_ai_frecuencias(sesion, centinela, monkeypatch):
    """La prueba central de 18-R8: con lotes de una fila (para ejercitar el orden: la madre de una ejecución partida se
    borra en un lote posterior al de sus trabajos), todo lo anterior al corte que no sostiene nada desaparece; lo
    posterior, lo abierto y lo que sostiene algo se conserva; las tablas centinela de otro esquema quedan intactas."""
    from app.servicios import retencion

    monkeypatch.setattr(retencion, "LOTE_FILAS", 1)
    x = _sembrar_todo(sesion)
    corrida = uuid.uuid4()
    try:
        antes = sesion.execute(text(f"SELECT count(*) FROM {E}.alert_history h JOIN {E}.alert a USING (alert_id) "
                                    "WHERE a.ruta = :r"), {"r": x.ruta}).scalar()
        r = retencion.aplicar(_politica(), simular=False, ahora=AHORA, execution_id=corrida)
        assert not r["simulado"] and r["pospuestas"] == 0
        for tabla, nombres in BORRADAS.items():
            for nombre in nombres:
                assert not _existe(sesion, tabla, LLAVES[tabla], x.ids[nombre]), (tabla, nombre)
        for tabla, nombres in CONSERVADAS.items():
            for nombre in nombres:
                assert _existe(sesion, tabla, LLAVES[tabla], x.ids[nombre]), (tabla, nombre)
        assert _particion(sesion, "feature_snapshot_201901") == (False, False)        # DETACH y DROP
        assert _particion(sesion, "feature_snapshot_201902") == (True, True)          # su predicción se conserva
        despues = sesion.execute(text(f"SELECT count(*) FROM {E}.alert_history h JOIN {E}.alert a USING (alert_id) "
                                      "WHERE a.ruta = :r"), {"r": x.ruta}).scalar()
        assert despues == antes - 1                     # el historial se fue con su alerta cerrada
        assert sesion.execute(text(f"SELECT count(*) FROM {E}.feature_snapshot WHERE ruta = :r"),
                              {"r": x.ruta}).scalar() == 1
        bitacora = {f.objeto: f for f in _registro(sesion, corrida)}
        assert not any(f.simulado for f in bitacora.values())
        assert bitacora["feature_snapshot_201901"].accion == "separar_y_borrar"
        assert bitacora["execution_log"].filas >= len(BORRADAS["execution_log"])
        assert bitacora["execution_log"].detalle["lotes"] >= len(BORRADAS["execution_log"])
        assert all(f.corte is None or f.corte < AHORA - timedelta(days=390) for f in bitacora.values())
        assert _filas_centinela(centinela) == (1, 1, 1, True)
        _evidencia("corrida_aplicada", r, x, borradas=True)
        repetida = retencion.aplicar(_politica(), simular=False, ahora=AHORA, execution_id=uuid.uuid4())
        assert repetida["particiones"] == 0                                           # idempotente
        for tabla, nombres in CONSERVADAS.items():
            for nombre in nombres:
                assert _existe(sesion, tabla, LLAVES[tabla], x.ids[nombre]), (tabla, nombre)
    finally:
        x.limpiar()
        _borrar_particion(sesion, "feature_snapshot_201901")
        _borrar_particion(sesion, "feature_snapshot_201902")


def test_las_filas_de_los_ciclos_intradia_se_borran_por_antiguedad_como_las_del_diario(sesion):
    """§18 con el volumen de los ciclos intradía (10.1-d, PLAN_INTRADIA_CRON): un ciclo intradía (parametros.intradia)
    escribe su foto de variables, sus predicciones y sus recomendaciones en las mismas tablas que el diario, y las
    reglas por antigüedad no miran el origen: lo anterior al corte se borra (la partición de la foto, entera vieja,
    con DETACH y DROP), lo posterior se conserva y la ejecución vieja se va cuando ya no sostiene nada."""
    from app.servicios import retencion

    x = Siembra(sesion)
    ventanas = {"vieja": datetime(2019, 3, 15, 8, 5, tzinfo=UTC), "nueva": datetime(2019, 4, 15, 8, 5, tzinfo=UTC)}
    for nombre, creado in (("vieja", VIEJO), ("nueva", NUEVO)):
        eid = x.ejecucion(f"intradia_{nombre}", creado,
                          parametros={"intradia": True, "instante": ventanas[nombre].isoformat()})
        pid = x.prediccion(f"prediccion_intradia_{nombre}", creado, eid, instante=ventanas[nombre])
        x.foto(pid, ventanas[nombre], creado)
        x.recomendacion(f"recomendacion_intradia_{nombre}", creado, pid, eid)
    sesion.commit()
    try:
        r = retencion.aplicar(_politica(), simular=False, ahora=AHORA, execution_id=uuid.uuid4())
        assert not r["simulado"] and r["pospuestas"] == 0
        for tabla, llave, nombre in (("recommendation", "recommendation_id", "recomendacion_intradia"),
                                     ("prediction", "prediction_id", "prediccion_intradia"),
                                     ("execution_log", "execution_id", "intradia")):
            assert not _existe(sesion, tabla, llave, x.ids[f"{nombre}_vieja"]), tabla
            assert _existe(sesion, tabla, llave, x.ids[f"{nombre}_nueva"]), tabla
        assert _particion(sesion, "feature_snapshot_201903") == (False, False)
        assert _particion(sesion, "feature_snapshot_201904") == (True, True)
        assert sesion.execute(text(f"SELECT count(*) FROM {E}.feature_snapshot WHERE ruta = :r"),
                              {"r": x.ruta}).scalar() == 1
    finally:
        x.limpiar()
        _borrar_particion(sesion, "feature_snapshot_201903")
        _borrar_particion(sesion, "feature_snapshot_201904")


def test_archivar_separa_la_particion_y_la_deja_para_pg_dump(sesion):
    """Con la política completa (todos los grupos en 13 meses), la regla de resultados borra en la MISMA corrida la
    predicción vieja de la foto archivada. El archivo se queda sin las llaves foráneas que clonó de feature_snapshot
    (ON DELETE CASCADE a prediction y a execution_log): con ellas, esa predicción borrada vaciaba el archivo."""
    from app.servicios import retencion

    x = Siembra(sesion)
    vieja = x.prediccion("vieja", VIEJO, instante=datetime(2019, 3, 10, tzinfo=UTC))
    x.foto(vieja, datetime(2019, 3, 10, tzinfo=UTC), VIEJO)
    sesion.commit()
    try:
        r = retencion.aplicar(_politica(retencion_archivar_particiones=1), simular=False, ahora=AHORA)
        accion = next(a for a in r["acciones"] if a["objeto"] == "feature_snapshot_201903")
        assert accion["accion"] == "separar_y_archivar" and accion["filas"] == 1
        assert sorted(accion["detalle"]["llaves_foraneas_quitadas"]) == ["feature_snapshot_execution_id_fkey",
                                                                         "feature_snapshot_prediction_id_fkey"]
        assert _particion(sesion, "feature_snapshot_201903") == (False, False)
        assert _particion(sesion, "feature_snapshot_201903_archivo") == (True, False)    # separada, con sus filas
        assert not _existe(sesion, "prediction", "prediction_id", vieja)           # la regla de resultados la borró
        assert sesion.execute(text(f"SELECT count(*) FROM {E}.feature_snapshot_201903_archivo")).scalar() == 1
        assert sesion.execute(text("SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND conrelid = "
                                   f"CAST('{E}.feature_snapshot_201903_archivo' AS regclass)")).scalar() == 0
    finally:
        _borrar_particion(sesion, "feature_snapshot_201903_archivo")
        x.limpiar()
        _borrar_particion(sesion, "feature_snapshot_201903")


def _filas_y_llaves(s, tabla: str) -> tuple[int, int]:
    """(filas, llaves foráneas) de una tabla de ai_frecuencias, con una instantánea nueva."""
    s.expire_all()
    filas = s.execute(text(f'SELECT count(*) FROM {E}."{tabla}"')).scalar()
    llaves = s.execute(text("SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND conrelid = "
                            "CAST(:t AS regclass)"), {"t": f'{E}."{tabla}"'}).scalar()
    return int(filas), int(llaves)


def test_el_mismo_mes_archivado_dos_veces_no_choca_con_su_archivo(sesion):
    """Se reprocesan datos viejos: la partición de un mes ya archivado se vuelve a crear y a envejecer. El RENAME a
    <partición>_archivo chocaría con el archivo anterior (la acción quedaría «pospuesta» en cada corrida); el segundo
    archivo es <partición>_archivo_2, con sus filas y sin llaves foráneas, y el primero queda intacto."""
    from app.servicios import retencion

    politica = _politica(retencion_archivar_particiones=1)
    x = Siembra(sesion)
    mes = "feature_snapshot_201907"
    try:
        x.foto(x.prediccion("primera", VIEJO, instante=datetime(2019, 7, 10, tzinfo=UTC)),
               datetime(2019, 7, 10, tzinfo=UTC), VIEJO)
        sesion.commit()
        primera = next(a for a in retencion.aplicar(politica, simular=False, ahora=AHORA)["acciones"]
                       if a["objeto"] == mes)
        assert primera["accion"] == "separar_y_archivar" and primera["detalle"]["archivo"] == f"{mes}_archivo"
        x.foto(x.prediccion("segunda", VIEJO, instante=datetime(2019, 7, 20, tzinfo=UTC)),     # vuelve la partición
               datetime(2019, 7, 20, tzinfo=UTC), VIEJO)
        x.foto(None, datetime(2019, 7, 21, tzinfo=UTC), VIEJO)
        sesion.commit()
        assert _particion(sesion, mes) == (True, True)
        r = retencion.aplicar(politica, simular=False, ahora=AHORA)
        segunda = next(a for a in r["acciones"] if a["objeto"] == mes)
        assert segunda["accion"] == "separar_y_archivar" and r["pospuestas"] == 0, segunda
        assert segunda["detalle"]["archivo"] == f"{mes}_archivo_2" and segunda["filas"] == 2
        assert _particion(sesion, mes) == (False, False)
        assert _particion(sesion, f"{mes}_archivo_2") == (True, False)
        assert _filas_y_llaves(sesion, f"{mes}_archivo") == (1, 0)
        assert _filas_y_llaves(sesion, f"{mes}_archivo_2") == (2, 0)
        guardar_evidencia("retencion/archivo_repetido.json", {
            "prueba": "tests/integracion/test_retencion.py::test_el_mismo_mes_archivado_dos_veces_no_choca_con_su_"
                      "archivo", "particion": mes, "primera": primera, "segunda": segunda,
            "archivos": {f"{mes}_archivo": "1 fila, sin llaves foráneas", f"{mes}_archivo_2": "2 filas, sin llaves "
                                                                                          "foráneas"}})
    finally:
        for nombre in (f"{mes}_archivo_2", f"{mes}_archivo"):
            _borrar_particion(sesion, nombre)
        x.limpiar()
        _borrar_particion(sesion, mes)


def test_la_foto_de_una_prediccion_que_se_conserva_conserva_su_particion(sesion):
    """Una foto vive lo que vive su predicción. Una predicción vieja que sostiene una recomendación posterior al corte
    la conserva la regla de resultados; su partición vieja (todas sus filas creadas antes del corte) se conserva entera,
    con el motivo, y su foto sigue ahí. Cuando la recomendación también es anterior al corte, la misma corrida borra la
    recomendación y la predicción, y separa la partición."""
    from app.servicios import retencion

    x = Siembra(sesion)
    mes, instante = "feature_snapshot_201908", datetime(2019, 8, 10, 7, tzinfo=UTC)
    sostenida = x.prediccion("sostenida", VIEJO, instante=instante)
    x.foto(sostenida, instante, VIEJO)
    x.foto(None, instante + timedelta(days=1), VIEJO)
    x.recomendacion("recomendacion_nueva", NUEVO, sostenida)
    sesion.commit()
    try:
        r = retencion.aplicar(_politica(), simular=False, ahora=AHORA)
        accion = next(a for a in r["acciones"] if a["objeto"] == mes)
        assert accion["accion"] == "conservar" and accion["filas"] == 2, accion
        assert accion["detalle"]["fotos_de_predicciones_conservadas"] == 1
        assert "una foto vive lo que vive su predicción" in accion["detalle"]["motivo"]
        assert _existe(sesion, "prediction", "prediction_id", sostenida) and _particion(sesion, mes) == (True, True)
        assert sesion.execute(text(f"SELECT count(*) FROM {E}.feature_snapshot WHERE prediction_id = :p"),
                              {"p": sostenida}).scalar() == 1
        # la recomendación sale del corte: la predicción ya no se conserva y la partición se separa en la misma corrida
        sesion.execute(text(f"UPDATE {E}.recommendation SET creado_en = :v WHERE recommendation_id = :r"),
                       {"v": VIEJO, "r": x.ids["recomendacion_nueva"]})
        sesion.commit()
        r = retencion.aplicar(_politica(), simular=False, ahora=AHORA)
        assert next(a for a in r["acciones"] if a["objeto"] == mes)["accion"] == "separar_y_borrar"
        assert not _existe(sesion, "prediction", "prediction_id", sostenida)
        assert _particion(sesion, mes) == (False, False)
        guardar_evidencia("retencion/foto_de_prediccion_conservada.json", {
            "prueba": "tests/integracion/test_retencion.py::test_la_foto_de_una_prediccion_que_se_conserva_conserva_"
                      "su_particion", "particion": mes, "con_recomendacion_posterior_al_corte": accion,
            "sin_ella": next(a for a in r["acciones"] if a["objeto"] == mes)})
    finally:
        x.limpiar()
        _borrar_particion(sesion, mes)


def test_una_particion_con_candados_ocupados_se_pospone_y_se_separa_despues(sesion, migrada, monkeypatch):
    """Separar una partición pide un candado exclusivo sobre feature_snapshot. Si un ciclo lo tiene (aquí, una
    transacción abierta que lee la tabla), la acción queda «pospuesta» en ESPERA_CANDADO, sin bloquear al ciclo; la
    corrida siguiente la separa."""
    from app.servicios import retencion

    monkeypatch.setattr(retencion, "ESPERA_CANDADO", "300ms")
    x = Siembra(sesion)
    # foto sin predicción: con SOLO_FOTO (retencion_meses_resultados = 0) toda predicción se conserva, y su foto también
    x.foto(None, datetime(2019, 4, 10, tzinfo=UTC), VIEJO)
    sesion.commit()
    otro = create_engine(migrada)
    try:
        with otro.connect() as ciclo:
            ciclo.execute(text(f"LOCK TABLE {E}.feature_snapshot IN ACCESS SHARE MODE"))   # transacción abierta
            r = retencion.aplicar(_politica(**SOLO_FOTO), simular=False, ahora=AHORA)
            pospuesta = next(a for a in r["acciones"] if a["objeto"] == "feature_snapshot_201904")
            assert pospuesta["accion"] == "pospuesta" and r["pospuestas"] == 1
            assert "lock" in pospuesta["detalle"]["motivo"].lower()
            assert pospuesta["detalle"]["accion_pedida"] == "separar_y_borrar"
            ciclo.rollback()
        assert _particion(sesion, "feature_snapshot_201904") == (True, True)
        r = retencion.aplicar(_politica(**SOLO_FOTO), simular=False, ahora=AHORA)
        assert next(a for a in r["acciones"] if a["objeto"] == "feature_snapshot_201904")["accion"] == \
            "separar_y_borrar"
        assert _particion(sesion, "feature_snapshot_201904") == (False, False)
    finally:
        otro.dispose()
        x.limpiar()
        _borrar_particion(sesion, "feature_snapshot_201904")


def _milisegundos(valor: str) -> float:
    """'500ms' -> 500.0; '2s' -> 2000.0 (el formato de ESPERA_CANDADO)."""
    numero = float(re.match(r"[0-9.]+", valor).group(0))
    return numero if valor.endswith("ms") else numero * 1000


SQL_RETENCION_TIENE_LA_FOTO = text(
    "SELECT count(*) FROM pg_locks l WHERE l.relation = CAST('ai_frecuencias.feature_snapshot' AS regclass) "
    "AND l.mode = 'AccessExclusiveLock' AND l.granted AND l.pid <> pg_backend_pid()")


def test_separar_cede_ante_un_ciclo_sin_que_postgresql_lo_aborte(sesion, migrada, monkeypatch):
    """Interbloqueo con un ciclo: el DETACH toma ShareRowExclusive sobre prediction y execution_log y el DROP pide
    AccessExclusive sobre las mismas tablas. Un ciclo que ya leyó execution_log (su transacción sigue abierta) y quiere
    insertar su predicción entre los dos pasos espera a la retención, y la retención al ciclo: PostgreSQL aborta al
    primero que cumple deadlock_timeout. Con ESPERA_CANDADO menor que deadlock_timeout cede la retención (la partición
    queda «pospuesta») y el ciclo inserta su predicción; con 2 s el ciclo caía por «deadlock detected». Una pausa entre
    el DETACH y el DROP deja que el ciclo espere primero (el peor caso)."""
    from app.servicios import retencion

    deadlock_ms = float(sesion.execute(text("SELECT setting FROM pg_settings WHERE name = 'deadlock_timeout'"))
                        .scalar())
    assert _milisegundos(retencion.ESPERA_CANDADO) < deadlock_ms
    x = Siembra(sesion)
    x.foto(None, datetime(2019, 5, 10, tzinfo=UTC), VIEJO)            # sin predicción (ver la prueba anterior)
    sesion.commit()
    original = retencion.ddl_particion
    monkeypatch.setattr(retencion, "ddl_particion", lambda nombre, archivar, *resto: [
        original(nombre, archivar, *resto)[0], "SELECT pg_sleep(0.3)", *original(nombre, archivar, *resto)[1:]])
    otro = create_engine(migrada)
    ciclo = otro.connect()
    resultado: dict[str, str] = {}

    def insertar_su_prediccion() -> None:
        limite = time.monotonic() + 10
        while not ciclo.execute(SQL_RETENCION_TIENE_LA_FOTO).scalar():     # espera a que el DETACH tenga la foto
            if time.monotonic() > limite:
                resultado["ciclo"] = "la retención nunca separó la partición"
                return
            time.sleep(0.02)
        try:
            ciclo.execute(text(f"INSERT INTO {E}.prediction (prediction_id, ruta, instante, horizonte_min, objetivo, "
                               "fecha, hora, pasajeros, model_id, generated_at) VALUES (:p, :r, now(), 60, now(), "
                               "current_date, 7, 1, 'ret', now())"), {"p": uuid.uuid4(), "r": x.ruta})
            resultado["ciclo"] = "ok"
        except DBAPIError as exc:
            resultado["ciclo"] = str(exc.orig).splitlines()[0]

    try:
        ciclo.execute(text(f"SELECT 1 FROM {E}.execution_log LIMIT 1")).all()     # el ciclo leyó su ejecución
        hilo = threading.Thread(target=insertar_su_prediccion)
        hilo.start()
        r = retencion.aplicar(_politica(**SOLO_FOTO), simular=False, ahora=AHORA)
        hilo.join(15)
        assert resultado.get("ciclo") == "ok", resultado                       # PostgreSQL no abortó al ciclo
        accion = next(a for a in r["acciones"] if a["objeto"] == "feature_snapshot_201905")
        assert accion["accion"] == "pospuesta" and "lock timeout" in accion["detalle"]["motivo"], accion
        assert _particion(sesion, "feature_snapshot_201905") == (True, True)
    finally:
        ciclo.rollback()
        ciclo.close()
        otro.dispose()
        x.limpiar()
        _borrar_particion(sesion, "feature_snapshot_201905")


def test_sin_la_reserva_de_la_cola_no_hace_nada_y_la_cola_lo_ve_como_reserva_perdida(sesion, monkeypatch):
    """Antes de cada acción se verifica que el trabajo sigue reservado por esta réplica (worker_id y estado
    «corriendo»). Si otra lo retomó, esta no borra ni anota nada, y el trabajo de la cola lo informa como
    cola.ReservaPerdida (el intento se cierra como «reserva_perdida», sin cerrar el trabajo dos veces)."""
    from app.servicios import cola, retencion

    x = Siembra(sesion)
    ajena = x.ejecucion("retencion_ajena", AHORA, estado="corriendo", tipo="retencion")   # sin worker_id propio
    vieja = x.ejecucion("vieja", VIEJO, estado="error")
    x.ejecucion("nueva", NUEVO, estado="error")
    sesion.commit()
    try:
        with pytest.raises(retencion.ReservaPerdida):
            retencion.aplicar(_politica(), simular=False, ahora=AHORA, execution_id=ajena,
                              trabajador="otra-replica:1:abc")
        assert _existe(sesion, "execution_log", "execution_id", vieja) and not _registro(sesion, ajena)

        def perdida(*_a, **_k):
            raise retencion.ReservaPerdida("otra réplica la retomó")

        monkeypatch.setattr(retencion, "aplicar", perdida)
        with pytest.raises(cola.ReservaPerdida):
            retencion.ciclo_retencion(ajena)
    finally:
        x.limpiar()


def test_una_particion_vieja_con_nombre_no_estandar_se_conserva_para_el_dba(sesion):
    """Solo se separan las particiones que crea asegurar_particion_feature_snapshot (feature_snapshot_AAAAMM): una que
    alguien adjuntó con otro nombre queda «conservar» con el motivo, aunque sea anterior al corte."""
    from app.servicios import retencion

    nombre = "fs_dba_201801"
    sesion.execute(text(f"CREATE TABLE {E}.{nombre} PARTITION OF {E}.feature_snapshot FOR VALUES FROM "
                        "('2018-01-01 00:00+00') TO ('2018-02-01 00:00+00')"))
    sesion.commit()
    try:
        r = retencion.aplicar(_politica(**SOLO_FOTO), simular=False, ahora=AHORA)
        accion = next(a for a in r["acciones"] if a["objeto"] == nombre)
        assert accion["accion"] == "conservar" and "nombre no estándar" in accion["detalle"]["motivo"]
        assert _particion(sesion, nombre) == (True, True)
    finally:
        _borrar_particion(sesion, nombre)


def test_cero_meses_no_recorta_ese_grupo(sesion):
    from app.servicios import retencion

    x = Siembra(sesion)
    vieja = x.ejecucion("vieja", VIEJO, estado="error")
    x.ejecucion("nueva", NUEVO, estado="error")          # la última de su tipo nunca se borra: esta es más nueva
    sesion.commit()
    try:
        r = retencion.aplicar(_politica(retencion_meses_foto=0, retencion_meses_resultados=0,
                                        retencion_meses_alertas=0, retencion_meses_ejecuciones=0),
                              simular=False, ahora=AHORA)
        assert r["filas"] == 0 and r["particiones"] == 0 and set(r["cortes"].values()) == {None}
        assert {a["grupo"] for a in r["acciones"]} == {"derivada"}
        assert _existe(sesion, "execution_log", "execution_id", vieja)
    finally:
        x.limpiar()


# ---------------------------------------------------------------- la cola, la API, el planificador y el gobierno
def _detalle(cliente, execution_id) -> dict:
    return cliente.get(f"/api/v1/frequency/executions/{execution_id}").json()


def test_post_aplicar_es_un_trabajo_de_la_cola_y_simula_por_omision(cliente, sesion):
    """POST /api/v1/retencion/aplicar (rol admin) responde 202 con el execution_id; el trabajo corre en la cola (aquí,
    sin hilos, al terminar la petición), termina «ok», simula por omisión y deja su bitácora, que GET
    /api/v1/retencion muestra con la política vigente."""
    x = Siembra(sesion)
    vieja = x.ejecucion("vieja", VIEJO, estado="error")
    x.ejecucion("nueva", NUEVO, estado="error")          # la última de su tipo nunca se borra: esta es más nueva
    sesion.commit()
    try:
        r = cliente.post("/api/v1/retencion/aplicar", json={"motivo": "prueba de la retención"})
        assert r.status_code == 202, r.text
        cuerpo = r.json()
        assert cuerpo["tipo"] == "retencion" and cuerpo["nueva"] and cuerpo["simular"] is True
        assert cuerpo["consultar_estado"] == f"/api/v1/frequency/executions/{cuerpo['execution_id']}"
        detalle = _detalle(cliente, cuerpo["execution_id"])
        assert detalle["estado"] == "ok" and detalle["metricas"]["simulado"] is True, detalle
        assert detalle["mensaje"].startswith("Retención simulada") and detalle["umbrales_version"]
        assert _existe(sesion, "execution_log", "execution_id", vieja)                 # simulación: nada se borró
        politica = cliente.get("/api/v1/retencion").json()
        assert politica["ultima_corrida"] and {f["execution_id"] for f in politica["ultima_corrida"]} == {
            cuerpo["execution_id"]}
        assert all(f["simulado"] for f in politica["ultima_corrida"])
        reglas = {f["tabla"]: f for f in politica["reglas"]}
        assert reglas["feature_snapshot"]["meses"] == politica["parametros"]["retencion_meses_foto"]
        assert reglas["feature_snapshot"]["corte"].endswith("-05:00")
        assert reglas["demanda_observada"]["accion"] == "conservar"
        aplicada = cliente.post("/api/v1/retencion/aplicar", json={"simular": False}).json()
        assert aplicada["nueva"] and aplicada["simular"] is False
        assert _detalle(cliente, aplicada["execution_id"])["metricas"]["simulado"] is False
        assert not _existe(sesion, "execution_log", "execution_id", vieja)            # anterior al corte: se borró
    finally:
        x.limpiar()
        sesion.execute(text(f"DELETE FROM {E}.execution_log WHERE tipo = 'retencion'"))
        sesion.commit()


def test_post_aplicar_no_duplica_una_corrida_en_cola_y_exige_admin(cliente, sesion, monkeypatch, claves_prueba):
    from app.config import obtener_ajustes
    from app.servicios import ejecucion

    monkeypatch.setattr(ejecucion, "ejecutar", lambda *a, **k: None)          # queda en cola sin procesarse
    try:
        primero = cliente.post("/api/v1/retencion/aplicar", json={"simular": True}).json()
        segundo = cliente.post("/api/v1/retencion/aplicar", json={"simular": False}).json()
        assert primero["nueva"] and not segundo["nueva"] and segundo["execution_id"] == primero["execution_id"]
        assert segundo["simular"] is True                                       # el de la corrida que ya estaba
        malo = cliente.post("/api/v1/retencion/aplicar", json={"simular": "quizas", "motivo": "x" * 600})
        assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "validacion"
        monkeypatch.setattr(obtener_ajustes(), "auth_habilitada", True)
        for rol in ("operador", "analista"):
            r = cliente.post("/api/v1/retencion/aplicar", json={}, headers={"X-API-Key": claves_prueba[rol]})
            assert r.status_code == 403 and r.json()["error"]["detalle"]["rol_requerido"] == "admin", rol
        assert cliente.get("/api/v1/retencion", headers={"X-API-Key": claves_prueba["operador"]}).status_code == 200
    finally:
        sesion.execute(text(f"DELETE FROM {E}.execution_log WHERE tipo = 'retencion'"))
        sesion.commit()


def _poner_umbrales(cliente, valores: dict) -> int:
    r = cliente.put("/api/v1/thresholds", json={"valores": valores, "motivo": "prueba de la retención"})
    assert r.status_code == 200, r.text
    return r.json()["version"]


def test_la_politica_se_gobierna_en_threshold_config_y_la_corrida_programada_la_respeta(cliente, sesion, monkeypatch):
    """Los parámetros son de threshold_config: PUT /thresholds los valida (1 mes rompería el monitoreo: 422) y los
    versiona; con retencion_aplicar_programada = 0 la corrida que encola el planificador solo simula; con 1 aplica.
    Al terminar, threshold_config queda como estaba (restituir_umbrales: sin las versiones que creó y con la anterior
    vigente), así que las pruebas de bajada de las migraciones pueden correr después en cualquier orden."""
    from app.servicios import cola, planificador

    inicial = cliente.get("/api/v1/thresholds").json()["version"]
    malo = cliente.put("/api/v1/thresholds", json={"valores": {"retencion_meses_foto": 1}, "motivo": "prueba"})
    assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "umbral_invalido"
    assert "retencion_meses_foto" in malo.json()["error"]["mensaje"]
    x = Siembra(sesion)
    vieja = x.ejecucion("vieja", VIEJO, estado="error")
    x.ejecucion("nueva", NUEVO, estado="error")          # la última de su tipo nunca se borra: esta es más nueva
    sesion.commit()
    aj = planificador.obtener_ajustes()
    monkeypatch.setattr(aj, "plan_retencion_cron", "30 3 * * 0")
    primero_de_junio = date(2031, 6, 1)
    domingo = datetime.combine(primero_de_junio + timedelta(days=(6 - primero_de_junio.weekday()) % 7),
                               datetime.min.time(), tzinfo=planificador.ZONA).replace(hour=3, minute=31)
    try:
        version = _poner_umbrales(cliente, {"retencion_aplicar_programada": 0})
        primero = planificador.tarea_retencion(domingo)
        assert primero is not None and planificador.tarea_retencion(domingo + timedelta(seconds=20)) is None
        assert cola.procesar(primero) == "ok"
        detalle = _detalle(cliente, primero)
        assert detalle["metricas"]["simulado"] is True and detalle["umbrales_version"] == version
        assert _existe(sesion, "execution_log", "execution_id", vieja)
        _poner_umbrales(cliente, {"retencion_aplicar_programada": 1})
        segundo = planificador.tarea_retencion(domingo + timedelta(days=7))
        assert cola.procesar(segundo) == "ok" and _detalle(cliente, segundo)["metricas"]["simulado"] is False
        assert not _existe(sesion, "execution_log", "execution_id", vieja)
        assert "retencion" in {t[0] for t in planificador.trabajos_programados(aj)}
    finally:
        x.limpiar()
        sesion.execute(text(f"DELETE FROM {E}.execution_log WHERE tipo = 'retencion'"))
        sesion.commit()
        restituir_umbrales(sesion, inicial)
    assert cliente.get("/api/v1/thresholds").json()["version"] == inicial


def test_todos_los_parametros_de_la_retencion_estan_vigentes_con_su_descripcion(migrada, sesion):
    from app.servicios import retencion

    vigentes = {f.nombre: f for f in sesion.scalars(select(Umbral).where(Umbral.vigente))}
    for nombre, (valor, descripcion) in retencion.PARAMETROS.items():
        assert nombre in vigentes and vigentes[nombre].descripcion, nombre
        assert descripcion.startswith("§18")


# ---------------------------------------------------------------- migración 0012
def _migracion_0012():
    from tests.integracion.conftest import RAIZ

    spec = importlib.util.spec_from_file_location(
        "m0012", RAIZ / "alembic" / "versions" / "0012_retencion_y_ventana_segmentos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_migracion_0012_sube_y_baja(migrada, sesion):
    """La 0012 agrega el tipo de trabajo «retencion» a la restricción vigente, la bitácora, la columna de huellas del
    refresco de segmentos y UNA versión nueva de threshold_config con los parámetros de la política; bajarla quita todo
    eso (y solo sus filas de threshold_config)."""
    from tests.integracion.conftest import _alembic

    m = _migracion_0012()

    def estado() -> dict:
        sesion.expire_all()
        with sesion.get_bind().connect() as c:
            return {"tabla": c.execute(text(f"SELECT to_regclass('{E}.retencion_registro') IS NOT NULL")).scalar(),
                    "columna": c.execute(text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_schema = :e AND table_name = "
                        "'segmento_estadistica_refresco' AND column_name = 'huellas_solape'"), {"e": E}).scalar() == 1,
                    "tipos": c.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                                            "WHERE conname = 'ck_execution_log_tipo'")).scalar(),
                    "filas": c.execute(text(f"SELECT count(*) FROM {E}.threshold_config WHERE creado_por = :c"),
                                       {"c": m.CREADO_POR}).scalar(),
                    "vigentes": set(c.execute(text(f"SELECT nombre FROM {E}.threshold_config WHERE vigente"))
                                    .scalars())}

    arriba = estado()
    assert arriba["tabla"] and arriba["columna"]
    assert "'retencion'" in arriba["tipos"] and "'segmentos'" in arriba["tipos"]
    assert {n for n, _v, _d in m.PARAMETROS_0012} <= arriba["vigentes"]
    sesion.commit()
    try:
        _alembic("downgrade", m.down_revision)
        abajo = estado()
        assert not abajo["tabla"] and not abajo["columna"] and abajo["filas"] == 0
        assert "'retencion'" not in abajo["tipos"] and "'segmentos'" in abajo["tipos"] and abajo["vigentes"]
    finally:
        sesion.rollback()
        _alembic("upgrade", "head")
    otra_vez = estado()
    assert otra_vez["tabla"] and otra_vez["columna"] and "'retencion'" in otra_vez["tipos"]
    assert otra_vez["filas"] == len(abajo["vigentes"] | {n for n, _v, _d in m.PARAMETROS_0012})   # UNA versión
    assert sesion.scalar(select(func.count()).select_from(Ejecucion).where(Ejecucion.tipo == "retencion")) == 0


def test_la_bitacora_guarda_fechas_y_detalle_en_json(sesion):
    """retencion_registro guarda el corte con zona y el detalle como JSONB (los instantes en ISO)."""
    from app.servicios import retencion

    corrida = uuid.uuid4()
    retencion.aplicar(_politica(**SOLO_FOTO), simular=True, ahora=AHORA, execution_id=corrida)
    filas = _registro(sesion, corrida)
    try:
        assert filas and {f.grupo for f in filas} >= {"derivada"}
        derivada = next(f for f in filas if f.objeto == "segmento_estadistica_dia")
        json.dumps(derivada.detalle)                                   # serializable
        assert derivada.detalle["motivo"].startswith("derivada de timbradas_segmentos")
        assert isinstance(derivada.creado_en, datetime) and derivada.creado_en.tzinfo is not None
        assert {"fecha_min", "fecha_max", "motivo"} <= set(derivada.detalle)
    finally:
        sesion.execute(text(f"DELETE FROM {E}.retencion_registro WHERE execution_id = :e"), {"e": corrida})
        sesion.commit()
