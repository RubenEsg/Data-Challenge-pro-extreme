"""La URL de la base de resultados solo llega por DATABASE_URL: sin valor por omisión en el código (SonarQube S2115)."""
from __future__ import annotations

import pytest

from app import config, db


@pytest.fixture
def ajustes_frescos(monkeypatch):
    """Cada prueba relee el entorno (se vacía la caché de obtener_ajustes) y deja el motor global como estaba."""
    monkeypatch.setattr(db, "_motor", None)
    monkeypatch.setattr(db, "_fabrica", None)
    config.obtener_ajustes.cache_clear()
    yield monkeypatch
    config.obtener_ajustes.cache_clear()  # la prueba siguiente vuelve a leer el entorno real


def test_ajustes_sin_url_por_omision(ajustes_frescos):
    ajustes_frescos.setenv("DATABASE_URL", "")
    assert config.Ajustes().database_url == ""
    assert config.Ajustes.model_fields["database_url"].default == ""


def test_motor_sin_database_url_falla_con_mensaje(ajustes_frescos):
    ajustes_frescos.setenv("DATABASE_URL", "   ")
    with pytest.raises(RuntimeError, match="Falta DATABASE_URL") as exc:
        db.motor()
    assert ".env.example" in str(exc.value)
    assert db._motor is None


def test_url_resultados_devuelve_la_del_entorno(ajustes_frescos):
    ajustes_frescos.setenv("DATABASE_URL", "postgresql+psycopg://usuario@localhost:1/base_de_prueba")
    assert db.url_resultados() == "postgresql+psycopg://usuario@localhost:1/base_de_prueba"
