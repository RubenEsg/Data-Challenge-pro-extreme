# API de frecuencias Sobusa: imagen reproducible (spec v1.5 §7.1, RNF-008, E09).
#  - Python 3.11 (python:3.11-slim) y solo las dependencias de EJECUCIÓN (requirements.txt, versiones exactas);
#    las herramientas de pruebas y análisis no entran (requirements-dev.txt).
#  - Usuario sin privilegios (uid 10001): el código queda de solo lectura y solo datos/ (modelos entrenados) es
#    escribible por la API.
#  - HEALTHCHECK contra GET /health; zona horaria America/Bogota (§8.1).
#  - Sin secretos: claves, URL y API keys llegan por variables de entorno (docker-compose.yml y .env local).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Bogota \
    DATA_DIR=/app/datos

WORKDIR /app

# libgomp1: el runtime de OpenMP que usa LightGBM (pronóstico de corto plazo); la imagen slim no lo trae.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Ruedas binarias únicamente (sin compilar nada en la imagen); la caché de pip vive fuera de la capa.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --only-binary=:all: -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
# Modelo activo, registro y Parquet de ejecución (el .dockerignore deja fuera pruebas, evidencias y cachés)
COPY datos ./datos
# Segunda copia de los modelos, de solo lectura: al actualizar una instalación, el volumen «modelos» tapa
# /app/datos/modelos, y la API copia de aquí lo que le falta (app/servicios/modelos_imagen.py)
COPY datos/modelos ./modelos_imagen

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin sobusa \
    && chown -R sobusa:sobusa /app/datos
USER sobusa

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Con «docker run» suelto, migra y arranca; en docker compose la migración la hace una sola vez el servicio «migrar».
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
