"""scripts/cola_servidor.py: las réplicas reales de las pruebas de cola, réplicas y caída (y la API propia de
scripts/medir_segmentos.py) corren con DATA_DIR y MODELOS_DIR en una COPIA temporal. Un ciclo puede escribir ahí (la
política de aprendizaje entrena un candidato en MODELOS_DIR y cambia registro.json): antes, con --planificador-minutos,
scripts/prueba_replicas.py dejaba ese candidato en datos/modelos del repositorio. Sin procesos ni base: Popen es un
doble que registra el entorno con que arrancaría la réplica."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import cola_servidor as CS

URL_A = "postgresql+psycopg://usuario@localhost:5433/base_a"
URL_B = "postgresql+psycopg://usuario@localhost:5433/base_b"


@pytest.fixture
def origen(tmp_path, monkeypatch) -> Path:
    """Una carpeta de datos «del repositorio» de mentira (DATA_DIR), con su registro de modelos; al terminar se borran
    las copias que haya hecho la prueba."""
    carpeta = tmp_path / "datos"
    (carpeta / "modelos" / "hgb_activo").mkdir(parents=True)
    (carpeta / "demanda_horaria.parquet").write_bytes(b"serie")
    (carpeta / "modelos" / "registro.json").write_text('{"activo": "hgb_activo"}', encoding="utf-8")
    (carpeta / "modelos" / "hgb_activo" / "modelo.joblib").write_bytes(b"modelo")
    monkeypatch.setenv("DATA_DIR", str(carpeta))
    monkeypatch.delenv("MODELOS_DIR", raising=False)
    monkeypatch.setattr(CS, "_COPIAS_DE_DATOS", {})
    yield carpeta
    CS.borrar_copias_de_datos()


def _archivos(carpeta: Path) -> dict[str, bytes]:
    return {p.relative_to(carpeta).as_posix(): p.read_bytes() for p in sorted(carpeta.rglob("*")) if p.is_file()}


def test_las_replicas_de_una_base_comparten_una_copia_temporal_de_los_datos(origen):
    antes = _archivos(origen)
    entorno = CS.datos_de_la_base(URL_A)
    copia = Path(entorno["DATA_DIR"])
    assert set(entorno) == {"DATA_DIR", "MODELOS_DIR"} and Path(entorno["MODELOS_DIR"]) == copia / "modelos"
    assert copia != origen and origen not in copia.parents and _archivos(copia) == antes
    # lo que escribiría un reentrenamiento (el candidato y el registro) queda en la copia: el origen no cambia
    (copia / "modelos" / "hgb_candidato").mkdir()
    (copia / "modelos" / "hgb_candidato" / "modelo.joblib").write_bytes(b"candidato")
    (copia / "modelos" / "registro.json").write_text('{"activo": "hgb_candidato"}', encoding="utf-8")
    assert _archivos(origen) == antes
    # las réplicas de la misma base comparten esa copia (y su registro de modelos); otra base parte de los originales
    assert CS.datos_de_la_base(URL_A) == entorno
    otra = Path(CS.datos_de_la_base(URL_B)["DATA_DIR"])
    assert otra != copia and _archivos(otra) == antes
    CS.borrar_copias_de_datos()
    assert not copia.exists() and not otra.exists() and CS._COPIAS_DE_DATOS == {} and _archivos(origen) == antes


def test_la_copia_trae_los_modelos_aunque_modelos_dir_apunte_a_otra_carpeta(origen, tmp_path, monkeypatch):
    aparte = tmp_path / "modelos_aparte"
    (aparte / "hgb_otro").mkdir(parents=True)
    (aparte / "registro.json").write_text('{"activo": "hgb_otro"}', encoding="utf-8")
    monkeypatch.setenv("MODELOS_DIR", str(aparte))
    entorno = CS.datos_de_la_base(URL_A)
    modelos = Path(entorno["MODELOS_DIR"])
    assert modelos == Path(entorno["DATA_DIR"]) / "modelos" and aparte not in modelos.parents
    assert (modelos / "registro.json").read_text(encoding="utf-8") == '{"activo": "hgb_otro"}'
    assert (modelos / "hgb_otro").is_dir()


class _Proceso:
    def poll(self):
        return None


def test_una_replica_arranca_con_los_datos_en_la_copia_y_no_en_el_repositorio(origen, tmp_path, monkeypatch):
    """Replica.arrancar: el proceso de la API recibe DATA_DIR y MODELOS_DIR de la copia de SU base, nunca datos/ del
    checkout; dos réplicas de la misma base reciben la misma copia."""
    lanzados: list[dict] = []

    def popen(cmd, cwd, env, stdout, stderr):
        lanzados.append(env)
        stdout.close()
        return _Proceso()

    monkeypatch.setattr(CS.subprocess, "Popen", popen)
    monkeypatch.setattr(CS.Replica, "esperar_salud", lambda self, limite_s=120.0: None)
    for nombre, puerto in (("replica-a", 8103), ("replica-b", 8104)):
        CS.Replica(nombre, puerto, URL_A, tmp_path / "logs", SONDEO_COLA_SEGUNDOS="0.5").arrancar()
    a, b = lanzados
    copia = Path(a["DATA_DIR"])
    assert copia == Path(CS.datos_de_la_base(URL_A)["DATA_DIR"]) and a["MODELOS_DIR"] == str(copia / "modelos")
    assert (b["DATA_DIR"], b["MODELOS_DIR"]) == (a["DATA_DIR"], a["MODELOS_DIR"])
    assert copia != origen and copia != CS.RAIZ / "datos" and CS.RAIZ not in copia.parents
    assert a["DATABASE_URL"] == URL_A and a["TRABAJADOR_ID"] == "replica-a" and a["SONDEO_COLA_SEGUNDOS"] == "0.5"
    # quien llama puede elegir otra carpeta de datos para su réplica: lo que pasa a Replica manda
    CS.Replica("replica-c", 8105, URL_A, tmp_path / "logs", DATA_DIR="otra", MODELOS_DIR="otra/modelos").arrancar()
    assert (lanzados[2]["DATA_DIR"], lanzados[2]["MODELOS_DIR"]) == ("otra", "otra/modelos")


def test_la_api_propia_de_medir_segmentos_tambien_corre_sobre_la_copia(origen, monkeypatch):
    import sys

    from scripts import medir_segmentos as MS

    suyo = sys.modules[MS.datos_de_la_base.__module__]     # el cola_servidor que importa el guion (scripts/ en la ruta)
    monkeypatch.setattr(suyo, "_COPIAS_DE_DATOS", {})
    monkeypatch.setattr(MS, "url_lector", lambda: "postgresql+psycopg://lector_ia@localhost:5434/operacional")
    try:
        entorno = MS.ApiPropia(8350, URL_B, "clave-de-prueba", origen.parent).entorno()
        copia = Path(entorno["DATA_DIR"])
        assert entorno["DATA_DIR"] == suyo.datos_de_la_base(URL_B)["DATA_DIR"] and copia != origen
        assert entorno["MODELOS_DIR"] == str(copia / "modelos") and entorno["FUENTE"] == "postgres"
        assert _archivos(copia) == _archivos(origen) and CS.RAIZ not in copia.parents
    finally:
        suyo.borrar_copias_de_datos()


# ---------------------------------------------------------------- la política de aprendizaje durante un lote
class _Resultado:
    def __init__(self, filas):
        self.filas = filas

    def all(self):
        return self.filas

    def scalar(self):
        return self.filas


class _Conexion:
    """Devuelve los entrenamientos por estado y el conteo de reentrenamientos omitidos, y registra las consultas."""

    def __init__(self, entrenamientos, omitidos):
        self.entrenamientos, self.omitidos, self.consultas = entrenamientos, omitidos, []

    def execute(self, sentencia, parametros=None):
        self.consultas.append((str(sentencia), parametros))
        return _Resultado(self.entrenamientos if parametros is None else self.omitidos)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Motor:
    def __init__(self, conexion):
        self.conexion = conexion

    def connect(self):
        return self.conexion


def test_el_informe_de_un_lote_dice_que_hizo_la_politica_de_aprendizaje():
    """Los guiones de réplicas comprueban en la base del lote que la política no dejó entrenamientos en error: al
    comienzo de la serie cada ciclo encolaba uno que siempre fallaba; ahora los omite y deja el motivo."""
    from app.servicios import fuentes, politica

    cx = _Conexion([], 19)
    p = CS.politica_del_lote(_Motor(cx))
    assert p == {"entrenamientos": {}, "omitidos_sin_datos": 19}
    (sql_estados, sin_parametros), (sql_omitidos, parametros) = cx.consultas
    assert sin_parametros is None and "tipo = 'entrenamiento'" in sql_estados
    assert parametros == {"patron": politica.OMITIDO_SIN_DATOS + "%"}
    assert "{monitoreo,politica,reentreno,bloqueos}" in sql_omitidos
    assert all(fuentes.validar_solo_select(sql) for sql in (sql_estados, sql_omitidos))
    regla, ok = CS.regla_de_la_politica(p)
    assert ok and regla == ("política de aprendizaje: ningún entrenamiento en error (encolados: ninguno; ciclos que "
                            "omitieron el reentrenamiento por datos insuficientes antes del corte: 19)")
    # lo que pasaba: 17 entrenamientos en error y uno pendiente
    antes = CS.politica_del_lote(_Motor(_Conexion([("en_cola", 1), ("error", 17)], 0)))
    regla, ok = CS.regla_de_la_politica(antes)
    assert not ok and "encolados: 1 en_cola, 17 error; ciclos" in regla
    # un entrenamiento que sí se puede entrenar (por periodicidad, con histórico) no es una falla
    assert CS.regla_de_la_politica({"entrenamientos": {"ok": 1}, "omitidos_sin_datos": 0})[1]
