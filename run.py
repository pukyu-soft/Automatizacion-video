"""Modo consola (sin web). Ejemplo:
   python run.py video.mp4 "Mi título" --audio narracion.m4a
   python run.py video.mp4 "Mi título" --audio narracion.m4a --script "texto de la narración" --mode fit
"""
import argparse, shutil
from pathlib import Path
from app import jobs, pipeline
from app.config import UPLOADS, AUDIO

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("title")
ap.add_argument("--audio"); ap.add_argument("--script", default="")
ap.add_argument("--mode", choices=["fill", "fit"], default="fill")
a = ap.parse_args()

job = jobs.create(title=a.title, mode=a.mode)
jid = job["id"]
v = UPLOADS / f"{jid}{Path(a.video).suffix}"
shutil.copy(a.video, v)
audio = ""
if a.audio:
    audio = str(AUDIO / f"{jid}_guide{Path(a.audio).suffix}")
    shutil.copy(a.audio, audio)
jobs.update(jid, video_path=str(v), audio_path=audio)

if not a.script:
    pipeline.step_transcribe(jid)
    a.script = jobs.get(jid)["script"]
jobs.update(jid, script=a.script)
pipeline.step_generate(jid)

j = jobs.get(jid)
print("ERROR:\n" + j["error"] if j["status"] == "error" else f"Listo: {j['output']}")
