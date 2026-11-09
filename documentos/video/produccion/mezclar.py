"""Arma el video E11: corta de los videos crudos de Playwright solo el tramo de cada escena, los une, pone la
narración de cada escena al inicio de su tramo y escribe los subtítulos SRT con el instante exacto de cada frase
(marcas SSML de la síntesis). Uso: python mezclar.py <salida.mp4> <salida.srt> [crf]"""
import glob
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg

AQUI = Path(__file__).resolve().parent
SALIDA, SRT = Path(sys.argv[1]), Path(sys.argv[2])
CRF = sys.argv[3] if len(sys.argv) > 3 else "28"
FPS, FS = 30, 22050
F = 16000 / 22050
g = json.loads((AQUI / "guion_video.json").read_text(encoding="utf-8"))
voz = json.loads((AQUI / "voz/resumen.json").read_text(encoding="utf-8"))

# La toma más reciente de cada escena (sin fallo si la hay)
tomas = {}
for archivo in sorted(glob.glob(str(AQUI / "linea_tiempo_*.json"))):
    for e in json.loads(Path(archivo).read_text(encoding="utf-8"))["escenas"]:
        if e.get("fallo") and e["id"] in tomas and not tomas[e["id"]].get("fallo"):
            continue
        tomas[e["id"]] = e
faltan = [e["id"] for e in g["escenas"] if e["id"] not in tomas]
if faltan:
    sys.exit(f"faltan tomas de: {faltan}")

ff = imageio_ffmpeg.get_ffmpeg_exe()
entradas, filtros, pista, srt, plan = [], [], bytearray(), [], []
t_final, n_srt = 0.0, 0


def hms(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def partir(texto, maximo=84):
    """Parte un subtítulo largo en trozos de hasta `maximo` caracteres, por signos de puntuación o espacios."""
    if len(texto) <= maximo:
        return [texto]
    mitad = len(texto) / 2
    cortes = [m.end() for m in re.finditer(r"[,;:?] ", texto)] or [m.end() for m in re.finditer(r" ", texto)]
    c = min(cortes, key=lambda x: abs(x - mitad))
    return partir(texto[:c].strip(), maximo) + partir(texto[c:].strip(), maximo)


def dos_lineas(texto, ancho=46):
    if len(texto) <= ancho:
        return texto
    espacios = [m.start() for m in re.finditer(" ", texto)]
    c = min(espacios, key=lambda x: abs(x - len(texto) / 2))
    return texto[:c] + "\n" + texto[c + 1:]


for k, esc in enumerate(g["escenas"]):
    t = tomas[esc["id"]]
    n = int(round((t["fin_s"] - t["inicio_s"]) * FPS))
    largo = n / FPS
    entradas += ["-ss", f"{t['inicio_s']:.3f}", "-t", f"{largo + 0.5:.3f}", "-i", t["video"]]
    filtros.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={FPS},tpad=stop_mode=clone:stop={FPS},trim=end_frame={n},"
                   f"setpts=PTS-STARTPTS,scale=1920:1080:flags=lanczos,setsar=1[v{k}]")
    with wave.open(str(AQUI / "voz" / f"{esc['id']}.wav")) as w:
        assert w.getframerate() == FS and w.getsampwidth() == 2 and w.getnchannels() == 1
        datos = w.readframes(w.getnframes())
    muestras = int(round(largo * FS))
    datos = datos[: muestras * 2]
    pista += datos + b"\x00\x00" * (muestras - len(datos) // 2)
    v = voz[esc["id"]]
    inicios = [x * F for x in v["inicios_s"]]
    fin_voz = (v["fin_marca_s"] or v["audio_s"] / F) * F
    for i, (_voz, sub) in enumerate(esc["cues"]):
        a = inicios[i]
        b = (inicios[i + 1] - 0.08) if i + 1 < len(inicios) else min(fin_voz + 0.3, largo - 0.05)
        trozos = partir(sub)
        total = sum(len(x) for x in trozos)
        cursor = a
        for tr in trozos:
            d = (b - a) * len(tr) / total
            n_srt += 1
            srt.append(f"{n_srt}\n{hms(t_final + cursor)} --> {hms(t_final + cursor + d - (0.04 if len(trozos) > 1 else 0))}\n{dos_lineas(tr)}\n")
            cursor += d
    plan.append({"id": esc["id"], "inicio_final_s": round(t_final, 3), "duracion_s": round(largo, 3), "cuadros": n,
                 "audio_s": v["audio_s"], "toma": Path(t["video"]).name, "tramo_crudo": [t["inicio_s"], t["fin_s"]]})
    t_final += largo

with wave.open(str(AQUI / "narracion_final.wav"), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(FS)
    w.writeframes(bytes(pista))
SRT.parent.mkdir(parents=True, exist_ok=True)
SRT.write_text("\n".join(srt), encoding="utf-8")

k = len(g["escenas"])
filtro = ";".join(filtros) + ";" + "".join(f"[v{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0[v]"
cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", *entradas, "-i", str(AQUI / "narracion_final.wav"),
       "-filter_complex", filtro, "-map", "[v]", "-map", f"{k}:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", CRF,
       "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "1",
       "-movflags", "+faststart", "-metadata", "title=Sobusa Despacho: demostración E11", "-metadata", "language=spa",
       str(SALIDA)]
SALIDA.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(cmd, check=True)
(AQUI / "plan_mezcla.json").write_text(json.dumps({"escenas": plan, "duracion_s": round(t_final, 3), "crf": CRF,
                                                   "subtitulos": n_srt}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"duración planeada {t_final:.2f} s · {n_srt} subtítulos · {SALIDA.stat().st_size / 1e6:.2f} MB")
