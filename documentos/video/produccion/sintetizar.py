"""Sintetiza la narración de cada escena del guion con la voz de Windows (System.Speech) y guarda, por escena, el WAV y
el instante de audio en que empieza cada subtítulo (marcas SSML). Uso: python sintetizar.py [id_escena ...]"""
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

AQUI = Path(__file__).resolve().parent
g = json.loads((AQUI / "guion_video.json").read_text(encoding="utf-8"))
out = AQUI / "voz"
out.mkdir(exist_ok=True)
solo = set(sys.argv[1:])
t0 = time.perf_counter()
resumen = json.loads((out / "resumen.json").read_text(encoding="utf-8")) if (out / "resumen.json").exists() else {}
for e in g["escenas"]:
    if solo and e["id"] not in solo:
        continue
    txt = out / f"{e['id']}.txt"
    txt.write_text("\n".join(v for v, _s in e["cues"]) + "\n", encoding="utf-8")
    wav, marcas = out / f"{e['id']}.wav", out / f"{e['id']}.marcas.tsv"
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(AQUI / "narrar2.ps1"),
                    "-Texto", str(txt), "-Salida", str(wav), "-Marcas", str(marcas), "-Tasa", str(g["voz"]["tasa"])],
                   check=True)
    with wave.open(str(wav)) as w:
        dur = w.getnframes() / w.getframerate()
    m = {}
    for linea in marcas.read_text(encoding="utf-8").splitlines():
        if "\t" in linea:
            k, v = linea.split("\t")
            m[k] = float(v) / 1000
    inicios = [m.get(f"c{i}") for i in range(len(e["cues"]))]
    resumen[e["id"]] = {"audio_s": round(dur, 3), "inicios_s": inicios, "fin_marca_s": m.get("fin"),
                        "palabras": sum(len(v.split()) for v, _s in e["cues"])}
    print(f"{e['id']:22s} voz={dur:6.2f}s palabras={resumen[e['id']]['palabras']:3d} marcas={inicios} fin={m.get('fin')}")
(out / "resumen.json").write_text(json.dumps(resumen, indent=1), encoding="utf-8")
total = sum(r["audio_s"] for r in resumen.values())
print(f"voz total={total:.1f}s en {len(resumen)} escenas · síntesis {time.perf_counter() - t0:.1f}s")
