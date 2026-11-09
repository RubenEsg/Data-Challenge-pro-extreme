# Entrega final · ¿Cuántos buses despachar y cada cuánto?

**Data Challenge Pro Extreme – Sobusa 2026** · Machine Learning, Universidad del Norte
**Equipo:** Abrahan Basto Martínez, Rubén Esguerra Fernández y Paula Gómez

> **La propuesta en una frase: no quitar buses, cambiarlos de hora.**
> Un modelo pronostica cuántos pasajeros habrá en cada ruta y hora con una semana de antelación, y un optimizador reparte
> las salidas: menos en el valle y más en los picos, con casi las mismas horas de bus.

## Qué hay en esta entrega

| Archivo o carpeta | Qué es | Cómo se abre |
|---|---|---|
| `Informe_tecnico_Sobusa.pdf` | **Informe técnico** (22 páginas): datos, metodología, resultados, limitaciones, recomendaciones y referencias. | Cualquier lector de PDF. |
| `entrega_final.html` | **Cuaderno final ejecutado**, en HTML: entrena el modelo, lo evalúa, resuelve el despacho de un día y comprueba 151 cifras. | Doble clic (navegador). |
| `entrega_final.ipynb` | El mismo cuaderno, con sus salidas. | Jupyter o VS Code. Para volver a ejecutarlo hace falta el proyecto completo (abajo). |
| `dash_app/` | **Laboratorio del modelo** (Dash, Python): el pronóstico y el optimizador corren en vivo. | En Windows, doble clic en `dash_app/iniciar_dash.bat`; en cualquier sistema, `python app.py` (abajo). |
| `app_sobusa/app.html` | **App «Sobusa Despacho»**: nueve pantallas con todo el proyecto, la consola de despacho y la vista 3D. *Solo en el ZIP completo.* | Doble clic, en Edge o Chrome, sin internet. |
| `api_frecuencias/` | **Backend del reto** (FastAPI + PostgreSQL 14): ejecución incremental, pronóstico a 30/60/120 min, recomendación de frecuencia y flota, alertas y registro de modelos. | Con Docker, dos comandos (abajo). |
| `MATRIZ_CUMPLIMIENTO.md` · `PLAN_EVOLUCION.md` | Cada requisito de la especificación v1.5 con dónde se cumple y su estado; plan de integración, escalabilidad, costos y riesgos. | Cualquier visor de Markdown. |
| `informe/` | Fuentes LaTeX del informe, figuras y `compilar.py`. | `python informe/compilar.py` (usa Tectonic). |
| `requirements_cuaderno.txt` | Versiones exactas con que se ejecutó el cuaderno. | `pip install -r requirements_cuaderno.txt` |

**Orden sugerido:** el informe (10 minutos para el resumen, las tablas 1 y 3 y las recomendaciones), después el laboratorio
Dash para ver el modelo funcionando y la app para recorrer el proyecto entero. El cuaderno es la prueba técnica: cada cifra
se calcula ahí mismo o se lee de su archivo de resultados y se contrasta.

## Cómo correr el laboratorio Dash

Hace falta Python 3.11 o más reciente (probado con 3.13 en Windows 11).

**En Windows:** descomprima el ZIP y dé doble clic en `dash_app/iniciar_dash.bat`. La primera vez crea el entorno `.venv`
e instala las dependencias (alrededor de un minuto, con internet); después abre el navegador solo. Para detener la app,
cierre la ventana negra.

**En cualquier sistema**, desde la carpeta `dash_app`:

```
python -m venv .venv
.venv\Scripts\activate              (Windows)
source .venv/bin/activate           (macOS o Linux)
pip install -r requirements.txt
python app.py
```

Abra **http://127.0.0.1:8050**. No necesita internet ni la base de datos (solo el mapa de calles de la pantalla Despacho se carga de internet): usa los 2,3 MB de `dash_app/datos/`. El
solucionador CBC viene dentro de PuLP. Las seis pantallas: Inicio, Pronóstico (ruta, día y modelo de 2025), **Horario en
vivo** (el optimizador D5 resuelto en el momento, con los costos, la elasticidad y el intervalo que usted elija), El
modelo, Qué gana Sobusa y App completa e informe (abre `app_sobusa/app.html`, este PDF y el cuaderno). Detalle en
`dash_app/README.md`.

## Backend del reto (FastAPI + PostgreSQL)

`api_frecuencias/` es el backend que pide la especificación de Extreme Technologies (Python, FastAPI y PostgreSQL 14 con
PostGIS): lee los datos nuevos por marca de agua, valida su calidad, pronostica la demanda a 30, 60 y 120 minutos con su
banda p10-p90, recomienda headway, buses por hora y vehículos (y dice si la flota alcanza), genera alertas ALT-001 a
ALT-010 explicables y gestionables, y registra cada modelo con su hash para activarlo o revertirlo con auditoría. Guarda
todo en su propio esquema `ai_frecuencias`; por omisión lee los datos del reto ya exportados a Parquet, así que nunca
escribe en la base compartida. Con Docker Desktop abierto, desde `api_frecuencias/`:

```
copy .env.example .env               (y cambie POSTGRES_PASSWORD; en macOS o Linux: cp)
docker compose up -d --build
```

Swagger queda en **http://localhost:8000/docs**. Detalle, endpoints y el ciclo de la demostración en
`api_frecuencias/README.md`; estado de cada requisito en `MATRIZ_CUMPLIMIENTO.md`.

## Las cifras principales

| | Hoy (regla manual) | Con el modelo |
|---|---|---|
| Error del pronóstico a 7 días (WAPE, 2025) | 20,04 % | 13,94 % modelo final (E11) · **13,62 % híbrido (E12), recomendado** |
| Salidas válidas por día (tres rutas) | 460 | 451 |
| Horas de bus por día | 1.732 | 1.723 (−0,5 %) |
| Espera media | 4,43 min | 4,30 min |
| Pasajeros por día sobre la capacidad (50 por bus) | 317 | 267 |

El plan que reasigna ahorra poco en operación (+501 M COP al año); lo que decide si paga es cuántos pasajeros se pierden
donde se quitan salidas y cuántos se ganan donde se ponen. Con la elasticidad medida (β = 0,70, rango 0,55–0,90) el saldo
anual va de **−2.825 M COP** (contando solo los pasajeros perdidos: 2.864 al día en riesgo) a **+1.600 M COP** (contando
también los ganados: +946 netos al día). Por eso la recomendación incluye un **piloto de ocho semanas** en CRA 54 y CL 72
que mide β con días sorteados (potencia 0,89; arriesga 22.904 pasajeros, el 0,30 % del año de CRA 54).

El plan que recorta (quita 31.267 salidas al año y pone 13.519 en otras horas: 9,6 % menos horas de bus) ahorra más
en operación (+3.695 M COP al año) y deja más caja que reasignar en las dos contabilidades: **−1.029 M COP** contando
solo los perdidos (frente a −2.825; deja de pagar con β > 0,53) y **+1.939 M COP** contando también los ganados
(frente a +1.600). Pero aun contando los ganados pierde 1.512 pasajeros netos al día, tiene casi el doble de pasajeros
sobre la capacidad que el plan que reasigna (530 al día frente a 267; hoy, 317) y sube la espera a 4,74 min. Con los
costos con fuente, el optimizador, que también valora la espera y el hacinamiento (con supuestos del equipo), elige
reasignar.

## Lo que hay que saber

- El plan anual de 2025 se calculó con el pronóstico del primer modelo (E1, 14,40 %), no con el final ni con el híbrido:
  el optimizador se construyó antes. Con el pronóstico final sería algo mejor; el laboratorio Dash permite planear con
  cualquiera de los cuatro pronósticos.
- El modelo persona a persona de la vista 3D, que no limita el cupo de cada bus, da saldos más extremos en las dos
  contabilidades (−3.212 M COP contando solo los perdidos y +2.312 contando también los ganados, en los 353 días de 2025
  con GPS, frente a −2.825 y +1.600 del optimizador en los 365 días) y muestra dónde el plan se queda corto: deja 2.742
  personas por día por encima de la capacidad (388
  con el horario real). Hace falta una restricción de cupo por bus antes de llevar el plan a la calle.
- El backtest en tiempo real (13 de octubre de 2026) y el modelo persona a persona no tuvieron revisor independiente.
- Los pasajeros que ganan los buses añadidos no se han medido; de ellos depende el signo del saldo. Eso mide el piloto.

## Reproducir

Todo se reproduce sin consultar la base del reto (compartida y de solo lectura): los datos se exportaron una vez a Parquet
(`datos/`, que no viaja en esta entrega por su tamaño y se regenera con `scripts/exportar_tablas.py`). El proyecto completo
está en el repositorio privado del equipo en GitHub; ahí:

```
cd EntregaFinal
pip install -r requirements_cuaderno.txt
python -m nbconvert --to notebook --execute --inplace entrega_final.ipynb      (unos 20 s)
python dash_app/preparar_datos.py                                              (vuelve a copiar los datos del Dash)
python informe/compilar.py                                                     (informe en PDF)
python empaquetar_entrega.py                                                   (este ZIP)
```

Ninguna cifra está escrita a mano: `app/generar_datos_app.py` lee 202 cifras de los resultados, cada una con su archivo y su
clave (`app/DATOS.md`), y `app/verificar_datos_app.py` las comprueba; el cuaderno contrasta 151 de ellas al ejecutarse.
Semilla 42 en todo el proyecto. Ningún archivo de la entrega trae credenciales ni datos personales de conductores.
