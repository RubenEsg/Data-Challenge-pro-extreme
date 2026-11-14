"""Configuración de la API (variables de entorno o archivo .env; nunca credenciales en el código)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[1]
ESQUEMA = "ai_frecuencias"


class Ajustes(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(RAIZ / ".env"), env_file_encoding="utf-8", extra="ignore")

    # Base de resultados propia (esquema ai_frecuencias). Se toma SOLO de DATABASE_URL (entorno o .env): no hay URL por
    # omisión en el código (SonarQube python:S2115); si falta, app.db.motor() falla con un mensaje que lo explica.
    # repr=False: las URL llevan la clave y no deben salir en logs ni en trazas de error.
    database_url: str = Field("", repr=False)
    # Fuente de las tablas operacionales: parquet (por defecto) o postgres (solo lectura).
    fuente: str = "parquet"
    fuente_database_url: str = Field("", repr=False)
    fuente_statement_timeout_ms: int = 30000
    # [catalogos] /api/v1/catalogos (§3.1): auto | replica | archivos, URL SELECT propia y archivos offline.
    catalogos_fuente: str = "auto"
    catalogos_database_url: str = Field("", repr=False)
    catalogos_datos_dir: str = ""
    catalogos_flota_csv: str = ""
    catalogos_cache_s: float = 300.0
    # Lectura que alimenta el ciclo con FUENTE=postgres: solo demanda_segmentos (timbradas_segmentos del trigger de
    # Extreme convertidas a demanda horaria, pasajeros = Σ numeropasajeros de los viajes válidos) llega de punta a
    # punta; otro valor detiene el arranque con un error claro. Proceso (operador) que se lee («*» = todos) y ventana
    # de solape de la marca de agua en minutos.
    fuente_tabla: str = "demanda_segmentos"
    fuente_proceso: str = "sobusa"
    fuente_solape_min: int = 15

    @field_validator("fuente_tabla")
    @classmethod
    def _fuente_tabla_soportada(cls, valor: str) -> str:
        from app.servicios.fuentes import validar_tabla_ciclo

        return validar_tabla_ciclo(valor.strip())
    data_dir: str = ""
    tz: str = "America/Bogota"
    entorno: str = "local"
    # Swagger UI y /openapi.json (§12.1): None = según ENTORNO (solo local, pruebas, demo o desarrollo).
    docs_habilitados: bool | None = None
    # Seguridad (§7.2): X-API-Key con roles; las claves solo llegan por entorno (API_KEYS o API_KEY_<ROL>).
    auth_habilitada: bool = True
    metricas_publicas: bool = True
    # Circuit breaker (RNF-010): fallos de conexión seguidos antes de abrir y segundos hasta el ensayo semiabierto.
    circuito_fuente_fallos_max: int = 3
    circuito_fuente_reinicio_s: float = 60.0
    circuito_notif_fallos_max: int = 5
    circuito_notif_reinicio_s: float = 120.0
    # Observabilidad (RNF-006): exportador de trazas ninguno | consola | otlp (OTEL_EXPORTER_OTLP_ENDPOINT).
    otel_exportador: str = "ninguno"
    otel_service_name: str = "api-frecuencias"
    max_reintentos: int = 3
    reanudar_ejecuciones: bool = True
    log_nivel: str = "INFO"
    # Cola de trabajos (RNF-005): hilos que consumen la cola en esta réplica (0 = la ejecución se procesa en la
    # misma petición que la crea), reserva que vence si la réplica muere y sondeo de la cola.
    trabajadores: int = 1
    lease_segundos: float = 30.0
    sondeo_cola_segundos: float = 1.0
    trabajador_id: str = ""  # identidad estable de la réplica (por omisión, el nombre del equipo/contenedor)
    # Planificador interno (§7.2): encola una fila por franja; idempotente con N réplicas.
    planificador_habilitado: bool = False
    plan_ejecucion_cron: str = "15 5 * * *"
    plan_reentrenamiento_cron: str = "0 4 * * 1"   # qué decide la revisión: politica.decidir_reentreno
    # §10.1 ocupación actual en la operación programada (planificador.tarea_ciclo_intradia): ciclos intradía con
    # instante = la franja, para que la restricción reactiva por ocupación actúe en el plan del día en curso y en las
    # recomendaciones de 30, 60 y 120 min. Vacío = apagados. Valor por omisión y medición: docs/ocupacion_segmentos.md.
    plan_intradia_cron: str = "5 6-20 * * *"
    # Agregación materializada de segmentos (§6.1, RNF-002, RNF-004; app/servicios/segmentos_refresco.py): cron del
    # refresco programado (solo con FUENTE_DATABASE_URL), días de timbradas_segmentos por lectura (cada una cabe en
    # FUENTE_STATEMENT_TIMEOUT_MS; si no, se parte sola) y días máximos entre dos refrescos completos.
    plan_segmentos_cron: str = "45 5 * * *"
    segmentos_dias_por_lote: int = Field(31, ge=1, le=366)
    segmentos_completo_dias: int = Field(7, ge=1, le=366)
    # §18 retención (app/servicios/retencion.py): cron de la corrida programada de la política (vacío = no se programa;
    # los meses y si aplica o solo simula son parámetros gobernados de threshold_config, migración 0012).
    plan_retencion_cron: str = "30 3 * * 0"
    # RNF-005: «ruta» parte la ejecución programada en un trabajo por ruta del catálogo (las réplicas los reparten);
    # «ninguna» (por omisión) la deja en un solo trabajo de todas las rutas, como hasta ahora.
    plan_particion: str = "ninguna"

    @field_validator("plan_particion")
    @classmethod
    def _plan_particion_valida(cls, valor: str) -> str:
        valor = (valor or "ninguna").strip().lower()
        if valor not in ("ninguna", "ruta"):
            raise ValueError("PLAN_PARTICION debe ser «ninguna» o «ruta»")
        return valor

    # motor de inferencia (§9.2): sklearn (joblib) u onnx (onnxruntime, exige scripts/exportar_onnx.py)
    motor_inferencia: str = "sklearn"
    # §7.3 paso 4: la foto de variables (§11.2) guarda también una fila por segmento y sentido de cada predicción
    # (modelo de segmentos activo; unas 130 filas por ruta y horizonte). FOTO_SEGMENTOS=false la apaga.
    foto_segmentos: bool = True

    @property
    def trabajadores_efectivos(self) -> int:
        """REANUDAR_EJECUCIONES=false (pruebas, scripts de una sola vez) apaga el consumo en segundo plano."""
        return max(0, self.trabajadores) if self.reanudar_ejecuciones else 0

    @property
    def docs_efectivos(self) -> bool:
        if self.docs_habilitados is not None:
            return self.docs_habilitados
        return self.entorno.strip().lower() in ("local", "pruebas", "demo", "desarrollo")

    @property
    def carpeta_datos(self) -> Path:
        return Path(self.data_dir) if self.data_dir else RAIZ / "datos"


@lru_cache
def obtener_ajustes() -> Ajustes:
    return Ajustes()
