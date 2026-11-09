"""Configuración de la API (variables de entorno o archivo .env; nunca credenciales en el código)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[1]
ESQUEMA = "ai_frecuencias"


class Ajustes(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(RAIZ / ".env"), env_file_encoding="utf-8", extra="ignore")

    # Base de resultados propia (esquema ai_frecuencias). Se toma de DATABASE_URL.
    database_url: str = "postgresql+psycopg://sobusa@localhost:5433/ai_frecuencias"
    # Fuente de las tablas operacionales: parquet (por defecto) o postgres (solo lectura).
    fuente: str = "parquet"
    fuente_database_url: str = ""
    fuente_statement_timeout_ms: int = 30000
    data_dir: str = ""
    tz: str = "America/Bogota"
    entorno: str = "local"
    docs_habilitados: bool = True
    max_reintentos: int = 3
    reanudar_ejecuciones: bool = True
    log_nivel: str = "INFO"

    @property
    def carpeta_datos(self) -> Path:
        return Path(self.data_dir) if self.data_dir else RAIZ / "datos"


@lru_cache
def obtener_ajustes() -> Ajustes:
    return Ajustes()
