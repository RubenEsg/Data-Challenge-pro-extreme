# Despliegue · API de frecuencias

## 1. Requisitos

- Docker Desktop (Windows o macOS) o Docker Engine con el plugin `compose` (Linux).
- Puertos libres en el equipo: **8000** (API) y **5433** (PostgreSQL). El 8050 es del laboratorio Dash; la API no lo usa.
- Sin Docker: Python 3.11 o más reciente y un PostgreSQL 14 (con PostGIS si se van a guardar geometrías).

## 2. Primera vez

```
cd api_frecuencias
copy .env.example .env          (macOS o Linux: cp .env.example .env)
```

Edite `.env` y cambie `POSTGRES_PASSWORD` (y, si quiere, `DATABASE_URL` con la misma clave para el modo sin Docker).

```
docker compose up -d --build
docker compose ps                 los dos servicios deben quedar «running»; db, además, «healthy»
```

Al arrancar, el contenedor `api` corre `alembic upgrade head` (crea el esquema `ai_frecuencias`) y luego `uvicorn` en
el puerto 8000. Swagger: http://localhost:8000/docs. Comprobación rápida: http://localhost:8000/health responde
`{"estado": "ok", "base_datos": "ok", ...}` (503 si la base no responde).

## 3. Operación

| Tarea | Comando |
|---|---|
| Ver logs (JSON) | `docker compose logs -f api` |
| Detener sin borrar datos | `docker compose down` |
| Borrar también la base | `docker compose down -v` |
| Actualizar el código | `docker compose up -d --build` (las migraciones nuevas se aplican solas) |
| Respaldo de la base | `docker compose exec db pg_dump -U sobusa -n ai_frecuencias ai_frecuencias > respaldo.sql` |
| Restaurar | `docker compose exec -T db psql -U sobusa ai_frecuencias < respaldo.sql` |
| Volver a una migración anterior | `docker compose exec api alembic downgrade -1` |

## 4. Ejecución diaria (RF-013)

La lectura incremental se dispara con `POST /api/v1/frequency/executions`. Para programarla una vez al día:

- **Linux (cron):** `0 5 * * * curl -s -X POST http://localhost:8000/api/v1/frequency/executions -H "Content-Type: application/json" -d "{}"`
- **Windows (Programador de tareas):** una tarea diaria que ejecute `curl.exe` con la misma petición.

Si una ejecución falla, la marca de agua no avanza y la siguiente vuelve a leer el mismo tramo.

## 5. Sin Docker (entorno local)

```
python -m venv .venv
.venv\Scripts\activate              (Windows)   ·   source .venv/bin/activate   (macOS o Linux)
pip install -r requirements.txt
alembic upgrade head                (usa DATABASE_URL del .env)
uvicorn app.main:app --port 8000
```

## 6. Conectar la fuente de Extreme (producción)

1. Extreme entrega una réplica de lectura y un usuario con `SELECT` sobre las tablas autorizadas.
2. En `.env` (nunca en el repositorio): `FUENTE=postgres` y `FUENTE_DATABASE_URL=postgresql+psycopg://<usuario>@<host>:5432/<base>`
   (la clave por el canal de Extreme). Ajuste `FUENTE_STATEMENT_TIMEOUT_MS` si hace falta.
3. `docker compose up -d` y una ejecución manual; compare los conteos con la fuente Parquet antes de programarla.
4. En producción: `ENTORNO=produccion` y `DOCS_HABILITADOS=false` para no exponer Swagger.

Detalle de las consultas, la marca de agua y los controles de no interferencia: `integracion_postgresql.md`.
