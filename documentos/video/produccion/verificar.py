"""Comprueba el MP4 y el SRT del video E11: duración y flujos (ffprobe si existe; si no, ffmpeg -i y conteo de cuadros),
tamaño, nivel del audio (volumedetect), cuadros de muestra para revisarlos a ojo, subtítulos dentro de la duración y
que ninguna clave de API aparezca en los entregables. Uso: python verificar.py <video.mp4> <subtitulos.srt> <carpeta_cuadros>"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

AQUI = Path(__file__).resolve().parent
MP4, SRT, CUADROS = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
CUADROS.mkdir(parents=True, exist_ok=True)
ff = imageio_ffmpeg.get_ffmpeg_exe()
r = {"archivo": MP4.name, "tamano_mb": round(MP4.stat().st_size / 1e6, 2), "ffmpeg": Path(ff).name}

ffprobe = shutil.which("ffprobe")
if ffprobe:
    p = json.loads(subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(MP4)],
                                  capture_output=True, text=True, check=True).stdout)
    r["ffprobe"] = {"duracion_s": float(p["format"]["duration"]),
                    "flujos": [{k: s.get(k) for k in ("codec_name", "codec_type", "width", "height", "r_frame_rate", "sample_rate", "channels")}
                               for s in p["streams"]]}
info = subprocess.run([ff, "-hide_banner", "-i", str(MP4)], capture_output=True, text=True, errors="replace").stderr
r["ffmpeg_i"] = [l.strip() for l in info.splitlines() if re.search(r"Duration|Stream", l)]
cuadros, segs = imageio_ffmpeg.count_frames_and_secs(str(MP4))
r["cuadros"], r["segundos"] = cuadros, round(segs, 3)
vol = subprocess.run([ff, "-hide_banner", "-i", str(MP4), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                     capture_output=True, text=True, errors="replace").stderr
r["audio"] = {k: float(v) for k, v in re.findall(r"(mean_volume|max_volume): (-?[\d.]+) dB", vol)}

plan = json.loads((AQUI / "plan_mezcla.json").read_text(encoding="utf-8"))
r["cuadros_revision"] = []
for e in plan["escenas"]:
    t = e["inicio_final_s"] + e["duracion_s"] * 0.7
    destino = CUADROS / f"cuadro_{e['id']}.png"
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(MP4), "-frames:v", "1",
                    str(destino)], check=True)
    r["cuadros_revision"].append({"escena": e["id"], "t_s": round(t, 2), "png": destino.name})

texto = SRT.read_text(encoding="utf-8")
tiempos = re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", texto)
fin = lambda m: int(m[4]) * 3600 + int(m[5]) * 60 + int(m[6]) + int(m[7]) / 1000
ini = lambda m: int(m[0]) * 3600 + int(m[1]) * 60 + int(m[2]) + int(m[3]) / 1000
r["srt"] = {"subtitulos": len(tiempos), "ultimo_fin_s": fin(tiempos[-1]) if tiempos else None,
            "ordenados_sin_solape": all(ini(tiempos[i + 1]) >= fin(tiempos[i]) for i in range(len(tiempos) - 1)),
            "dentro_del_video": bool(tiempos) and fin(tiempos[-1]) <= segs + 0.01,
            "max_caracteres_linea": max(len(l) for l in texto.splitlines() if l and not re.match(r"^\d+$|^\d\d:", l))}

claves = json.loads((AQUI / "claves.json").read_text(encoding="utf-8")).values()
revisar = [SRT, *(Path(x) for x in sys.argv[4:])]
r["claves_en_entregables"] = sum(1 for f in revisar if f.exists() for c in claves if c in f.read_text(encoding="utf-8", errors="ignore"))
r["cumple"] = {"duracion_max_300_s": segs <= 300, "tamano_max_60_mb": r["tamano_mb"] <= 60,
               "audio_presente": r["audio"].get("max_volume", -91) > -40, "sin_claves": r["claves_en_entregables"] == 0}
(AQUI / "verificacion.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(r, ensure_ascii=False, indent=1))
