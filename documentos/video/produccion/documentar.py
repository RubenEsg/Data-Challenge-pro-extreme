"""Escribe el guion del video (documentos/video/guion.md) y el registro de producción
(api_frecuencias/docs/evidencias/video/registro.txt) a partir del guion, la síntesis, las tomas, la mezcla y la
verificación. Uso: python documentar.py <guion.md> <registro.txt> <versiones.json> <revision_cuadros.json>"""
import glob
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
GUION_MD, REGISTRO = Path(sys.argv[1]), Path(sys.argv[2])
VERS = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
REV = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
g = json.loads((AQUI / "guion_video.json").read_text(encoding="utf-8"))
voz = json.loads((AQUI / "voz/resumen.json").read_text(encoding="utf-8"))
plan = json.loads((AQUI / "plan_mezcla.json").read_text(encoding="utf-8"))
ver = json.loads((AQUI / "verificacion.json").read_text(encoding="utf-8"))
semb = json.loads((AQUI / "sembrar.json").read_text(encoding="utf-8"))
ali = json.loads((AQUI / "alineacion.json").read_text(encoding="utf-8")) if (AQUI / "alineacion.json").exists() else None
tomas = [json.loads(Path(a).read_text(encoding="utf-8")) for a in sorted(glob.glob(str(AQUI / "linea_tiempo_*.json")))]
api_vivo = next((t["api"] for t in reversed(tomas) if t.get("api", {}).get("ejecucion")), {})
P = {e["id"]: e for e in plan["escenas"]}


def mmss(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def coma(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


CIFRAS = [
    ("51 filas leídas y válidas del día nuevo; marca de agua anterior y nueva", "respuesta de GET /api/v1/frequency/executions/{id} durante la grabación (api_frecuencias/docs/evidencias/video/registro.txt, «Ejecución en vivo») y api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt, paso (2)"),
    ("WAPE 14,77 % del modelo activo frente a 21,18 % de la regla manual (prueba reservada 2025-11-01 a 2025-12-31)", "api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.md, filas «activo (hgb_fv2_20250831_s42)» y «B1 regla manual 8 sem»"),
    ("Cobertura de la banda P10–P90 de 77,8 % en la prueba reservada (calibración v2: 77,82 %)", "api_frecuencias/docs/evidencias/modelo/calibracion_condicional.md"),
    ("Gradient Boosting con pérdida Poisson", "api_frecuencias/docs/evidencias/modelo/resumen_modelo.md"),
    ("Alertas por ruta y día: 6,08 con las reglas anteriores → 0,53 con las reglas sobre datos observados", "api_frecuencias/docs/evidencias/alertas/backtest_alertas.md («Reglas anteriores: 6,083» y «Alertas observadas por ruta y día (todas): 0.534»)"),
    ("14 días en sombra y compuerta de cuatro criterios", "política de monitoreo de la API (GET /api/v1/monitoring/policy, umbral sombra_dias = 14) y pantalla Monitoreo"),
    ("Ciclo §14.2, llegada y lectura incremental: 49.623 filas de carga inicial, 51 de un día nuevo y 4.641 más; la repetición de la misma fecha lee 0", "api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt, pasos (1) y (2)"),
    ("Ciclo §14.2, comparación y decisión: en la misma ventana 2025-12-01 a 2025-12-14, fuera de la muestra de ambos, WAPE 14,108 % del candidato frente a 13,982 % del activo; la compuerta de cuatro criterios lo rechaza y el activo sigue", "api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt, pasos (3) a (6), y demo_esperado.md"),
    ("1.060 pruebas automáticas sin fallas (0 fallas, 0 errores, 5 omitidas)", "api_frecuencias/docs/evidencias/pruebas/suite_final.xml"),
    ("94,3 % de cobertura y puerta «Reto Sobusa v1.5» de SonarQube aprobada: 0 bugs, 0 vulnerabilidades, 0 críticos, 0 bloqueantes", "api_frecuencias/docs/evidencias/sonarqube/quality_gate.json (status OK; coverage 94.3)"),
    ("Integración continua en verde en GitHub, en un runner limpio", "api_frecuencias/docs/evidencias/pruebas/ci_github.txt"),
    ("k6 con 50 usuarios virtuales: p95 451,3 ms en consultas y 627,5 ms con un año de resultados, 0,00 % de errores", "api_frecuencias/docs/evidencias/pruebas/k6_consultas.json y api_frecuencias/docs/evidencias/pruebas/k6_volumen.json"),
    ("Docker Compose desde volúmenes nuevos, con la comprobación completa en OK", "api_frecuencias/docs/evidencias/despliegue/arranque_limpio.txt («Resultado global: OK»)"),
    ("Plan: 4 semanas de conexión, 4 en modo sombra y piloto de 8 semanas en CRA 54 y CL 72", "documentos/notas_orador.txt (diapositiva 14) y PLAN_EVOLUCION.md"),
]

# --- guion.md ------------------------------------------------------------------------------------------------------
L = ["# Video de demostración (E11): guion", "",
     f"Video: `E11_video_demostracion.mp4` ({coma(ver['segundos'], 1)} s, {coma(ver['tamano_mb'], 1)} MB, 1920×1080, H.264 a 30 cuadros/s y "
     "audio AAC). Subtítulos en español: `E11_video_demostracion.srt` (archivo aparte; el video no los lleva quemados, "
     "el reproductor los carga si tienen el mismo nombre y están en la misma carpeta).", "",
     "La narración es una voz sintética de Windows (Microsoft Sabina, español de México). Todo lo que se ve es la "
     "aplicación real: la API (FastAPI + PostgreSQL) en su página /docs y el tablero Dash, grabados con Edge y "
     "Playwright, más tres páginas que muestran literalmente las líneas de los archivos de evidencia que respaldan las "
     "cifras narradas. La clave de API nunca aparece en pantalla. El registro de producción, con herramientas, "
     "versiones, duraciones y comprobaciones, está en `api_frecuencias/docs/evidencias/video/registro.txt`.", "",
     *([VERS["regrabacion_guion"], ""] if VERS.get("regrabacion_guion") else []),
     "## Escenas", "", "| # | Escena | Inicio | Segundos | Pantalla |", "|---|---|---|---|---|"]
for i, e in enumerate(g["escenas"], 1):
    p = P[e["id"]]
    L.append(f"| {i} | {e['titulo']} | {mmss(p['inicio_final_s'])} | {coma(p['duracion_s'])} | {e['pantalla']} |")
L += ["", f"Duración total medida: {coma(ver['segundos'], 2)} s (límite de la especificación: 300 s).", ""]
for i, e in enumerate(g["escenas"], 1):
    p = P[e["id"]]
    L += [f"### {i}. {e['titulo']} ({mmss(p['inicio_final_s'])}–{mmss(p['inicio_final_s'] + p['duracion_s'])}, {coma(p['duracion_s'])} s)", "",
          f"**En pantalla.** {e['pantalla']}", "", "**Narración.**", ""]
    L += [f"> {s}" for _v, s in e["cues"]]
    L += ["", "**Evidencia.** " + "; ".join(f"`{x}`" for x in e["evidencia"]), ""]
L += ["## De dónde sale cada cifra narrada", "", "| Cifra | Archivo de evidencia |", "|---|---|"]
L += [f"| {c} | {f} |" for c, f in CIFRAS]
L += ["", "Las cifras del tablero que se ven en pantalla (respuesta del día, plan, alertas, monitoreo) son las que "
      "devolvió la API durante la grabación; la narración no las repite para no depender de una corrida concreta.", ""]
L += ["## Cómo se produjo y cómo se repite", "",
      "Los programas están en `documentos/video/produccion/` y corren con el entorno virtual de la API (Playwright, "
      "httpx e imageio-ffmpeg) en Windows con Edge y la voz Microsoft Sabina instalada:", "",
      "1. Levantar la API con autenticación y una base PostgreSQL propia (migraciones con `alembic upgrade head` y una "
      "copia temporal de `datos/`), y el tablero apuntando a ella con una clave de analista. Las claves de prueba van en "
      "`claves.json` junto a los programas (no se versiona) y la API solo recibe sus hashes en `API_KEYS`.",
      "2. `python sembrar.py`: tres ejecuciones diarias y un candidato que queda en sombra.",
      "3. `python sintetizar.py`: narración por escena con las marcas de cada subtítulo.",
      "4. `python visores.py`: páginas que muestran las líneas de evidencia citadas.",
      "5. `python grabar.py 2025-09-05`: grabación con Edge; la clave viaja como cabecera y nunca se ve.",
      "6. `python mezclar.py E11_video_demostracion.mp4 E11_video_demostracion.srt 28`: corte, unión, audio y subtítulos.",
      "7. `python verificar.py ...` y `python documentar.py ...`: comprobaciones, este guion y el registro.", ""]
GUION_MD.parent.mkdir(parents=True, exist_ok=True)
GUION_MD.write_text("\n".join(L), encoding="utf-8")

# --- registro.txt --------------------------------------------------------------------------------------------------
R = [f"Registro de producción del video E11 «Video de máximo 5 minutos» · {VERS['fecha']}", "",
     "Entregables", f"  documentos/video/E11_video_demostracion.mp4  ({coma(ver['segundos'], 2)} s, {coma(ver['tamano_mb'], 2)} MB)",
     f"  documentos/video/E11_video_demostracion.srt  ({ver['srt']['subtitulos']} subtítulos)",
     "  documentos/video/guion.md                    (escena, segundos, narración, pantalla y evidencia)", "",
     "Herramientas y versiones"]
R += [f"  {k}: {v}" for k, v in VERS["herramientas"].items()]
R += ["", "Entorno de la grabación (aislado)",
      f"  Código: instantánea del commit {VERS['commit']} (árbol de trabajo separado), sin cambios.",
      "  API: uvicorn en 127.0.0.1 con una base PostgreSQL 14 propia en el servidor local (migraciones al día con",
      "  alembic upgrade head) y una copia temporal de datos/; nunca se escribió en api_frecuencias/datos/.",
      "  Autenticación encendida: tres claves de prueba (operador, analista, admin) creadas solo para la grabación;",
      "  la API recibe únicamente sus hashes (API_KEYS). El tablero usa la clave de analista. En el navegador, la clave",
      "  viaja como cabecera X-API-Key agregada por Playwright: no se escribe en ningún campo y no aparece en pantalla.",
      "  Sin conexión a la base del reto: la fuente es el histórico en parquet de la entrega.", "",
      "Siembra del ciclo de demostración (antes de grabar)"]
for x in semb["ejecuciones"]:
    R.append(f"  POST /api/v1/frequency/executions hasta {x['hasta']}: {x['estado']} en {coma(x['segundos'])} s · filas leídas "
             f"{x['filas_leidas']}, válidas {x['filas_validas']} · marca {x['marca_agua_anterior'] or '(sin marca: carga inicial)'} -> {x['marca_agua_nueva']} · "
             f"predicciones {x['predicciones']}, recomendaciones {x['recomendaciones']}, alertas {x['alertas']}")
if semb.get("entrenamiento"):
    t = semb["entrenamiento"]
    R.append(f"  POST /api/v1/models/train (hasta 2025-07-03, datos_hasta 2025-09-03): {t['estado']} en {coma(t['segundos'])} s · {t['mensaje']}")
pol = semb.get("politica", {}).get("decision", {})
R += [f"  GET /api/v1/monitoring/policy: reentrenar = {'sí' if pol.get('reentrenar') else 'no'} · bloqueos: {'; '.join(pol.get('bloqueos') or []) or 'ninguno'}", "",
      "Ensayo previo: antes de la toma final se grabaron de prueba las escenas 3, 4 y 8 (día 2025-09-04 y una alerta ALT-005",
      "cerrada); esa toma no se usa en el video. La toma final usa el día 2025-09-05. Las escenas 5 y 12 se regrabaron",
      "(segunda toma) después de corregir sus páginas de evidencia: la tabla del modelo mostraba una fila de otra tabla de",
      "evaluacion_modelo.md bajo la cabecera de WAPE, y las líneas de k6 se partían a mitad de cifra.", ""]
if VERS.get("regrabacion"):
    R += VERS["regrabacion"] + [""]
if api_vivo:
    e = api_vivo["ejecucion"]
    R += ["Ejecución en vivo (escenas 3 y 4, desde Swagger /docs)",
          f"  POST con {{\"hasta\": \"{api_vivo['respuesta_post']['parametros']['hasta']}\"}} -> 202 «{api_vivo['respuesta_post']['estado']}», execution_id {e['execution_id']}",
          f"  GET -> estado {e['estado']} ({e['mensaje']}) · filas leídas {e['filas_leidas']}, válidas {e['filas_validas']} · marca de agua "
          f"{e['marca_agua_anterior']} -> {e['marca_agua_nueva']} · métricas {e['metricas']}",
          f"  Alertas cerradas desde el tablero (reconocer, asignar y cerrar): " + "; ".join(f"{a['codigo']} {a['alert_id']} -> {a['estado']}, asignada a {a['asignado_a']}" for a in api_vivo.get('alertas_cerradas') or []) + " (la ALT-003 es la de la toma final; la ALT-005, la del ensayo)", ""]
R += ["Narración", f"  Voz {g['voz']['nombre']}, SpeechSynthesizer.Rate = {g['voz']['tasa']} (la velocidad va por la propiedad Rate;",
      "  el SSML solo lleva la voz y una marca <mark> por subtítulo). WAV 22,05 kHz, 16 bits, mono.",
      "  Las marcas de System.Speech informan la posición en la escala de 16 kHz: se multiplican por 16000/22050;",
      "  comprobado en cada escena: la marca final queda 0,19 s antes del final del WAV (silencio de cierre).",
      f"  Voz total {coma(sum(v['audio_s'] for v in voz.values()))} s en {len(voz)} escenas.", "",
      "Escenas (tiempo en el video final)",
      "  #  escena               inicio   video_s  voz_s   toma cruda (tramo)                      errores de consola"]
tom_por_id = {}
for t in tomas:
    for e in t["escenas"]:
        tom_por_id[e["id"]] = e
for i, e in enumerate(plan["escenas"], 1):
    t = tom_por_id.get(e["id"], {})
    R.append(f"  {i:<2} {e['id']:<20} {mmss(e['inicio_final_s']):>6}  {coma(e['duracion_s'], 2):>7}  {coma(e['audio_s'], 2):>6}  "
             f"{e['toma'][:24]}… [{coma(e['tramo_crudo'][0], 1)}–{coma(e['tramo_crudo'][1], 1)}]  {len(t.get('errores_consola', []))}"
             + (f" · fallo: {t['fallo']}" if t.get("fallo") else "") + (f" · ajuste: {t['ajuste']}" if t.get("ajuste") else ""))
R += ["", "Mezcla", f"  ffmpeg ({ver['ffmpeg']}): cada tramo se corta de la toma cruda (VP8/webm 1600×900, device_scale_factor 1),",
      "  se lleva a 30 cuadros/s con un número exacto de cuadros, se escala a 1920×1080 con lanczos y se une; la",
      f"  narración de cada escena empieza con su tramo. H.264 CRF {plan['crf']} (preset medium, yuv420p), AAC 128 kb/s 48 kHz,",
      "  +faststart. Subtítulos: SRT aparte, con el instante de cada frase tomado de las marcas de la síntesis.", "",
      "Comprobaciones"]
if ver.get("ffprobe"):
    R.append(f"  ffprobe: duración {ver['ffprobe']['duracion_s']} s · flujos {ver['ffprobe']['flujos']}")
else:
    R.append("  ffprobe no está instalado en el equipo; la duración y los flujos se leen con «ffmpeg -i» y el conteo de cuadros:")
R += [f"  {l}" for l in ver["ffmpeg_i"]]
R += [f"  cuadros {ver['cuadros']} · {coma(ver['segundos'], 3)} s (límite 300 s: {'cumple' if ver['cumple']['duracion_max_300_s'] else 'NO cumple'})",
      f"  tamaño {coma(ver['tamano_mb'], 2)} MB (límite 60 MB: {'cumple' if ver['cumple']['tamano_max_60_mb'] else 'NO cumple'})",
      f"  audio presente: volumedetect media {coma(ver['audio'].get('mean_volume'))} dB, máximo {coma(ver['audio'].get('max_volume'))} dB",
      f"  subtítulos: {ver['srt']['subtitulos']}, ordenados y sin solaparse: {'sí' if ver['srt']['ordenados_sin_solape'] else 'NO'}, el último termina en "
      f"{coma(ver['srt']['ultimo_fin_s'], 3)} s (dentro del video: {'sí' if ver['srt']['dentro_del_video'] else 'NO'}), máximo {ver['srt']['max_caracteres_linea']} caracteres por línea",
      f"  claves de API en el SRT, el guion y este registro: {ver['claves_en_entregables']}",
      *([f"  alineación de subtítulos: {ali['subtitulos_con_inicio_de_voz_a_menos_de_1_s']} de {ali['subtitulos']} empiezan a menos de 1 s de un inicio de voz; "
         f"desfase mediano {coma(ali['mediana_s'], 2)} s, p90 {coma(ali['p90_s'], 2)} s, máximo {coma(ali['max_s'], 2)} s ({ali['metodo']}; {ali['nota']})"] if ali else []), "",
      "Cuadros revisados a ojo (extraídos del MP4 final al 70 % de cada escena)"]
R += [f"  {x['escena']} (t = {coma(x['t_s'], 1)} s): {REV.get(x['escena'], 'sin revisar')}" for x in ver["cuadros_revision"]]
R += ["", "Cifras narradas y su evidencia"] + [f"  - {c}: {f}" for c, f in CIFRAS] + [""]
REGISTRO.parent.mkdir(parents=True, exist_ok=True)
REGISTRO.write_text("\n".join(R), encoding="utf-8")
print("escrito:", GUION_MD, REGISTRO)
