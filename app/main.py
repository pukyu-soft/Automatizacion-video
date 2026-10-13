import secrets, shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import jobs, pipeline
from .config import (APP_PASSWORD, UPLOADS, AUDIO, CHARACTER_CLIP, TTS_ENGINE,
                     MAX_UPLOAD_MB, BASE)

security = HTTPBasic(auto_error=False)


def auth(c: HTTPBasicCredentials = Depends(security)):
    if APP_PASSWORD and not (c and secrets.compare_digest(c.password, APP_PASSWORD)):
        raise HTTPException(401, "No autorizado", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="VideoStudio", dependencies=[Depends(auth)])
pool = ThreadPoolExecutor(max_workers=1)          # un render a la vez
STATIC = BASE / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
AUDIO_EXT = {".webm", ".m4a", ".mp3", ".wav", ".ogg", ".aac", ".mp4"}


def _save(up: UploadFile, folder: Path, name: str, allowed: set) -> str:
    ext = Path(up.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Formato no permitido: {ext or 'desconocido'}")
    dest = folder / f"{name}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(up.file, f)
    if dest.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
        dest.unlink()
        raise HTTPException(413, f"Máximo {MAX_UPLOAD_MB} MB")
    return str(dest)


def _job(job_id: str) -> dict:
    try:
        return jobs.get(job_id)
    except KeyError:
        raise HTTPException(404, "Trabajo no encontrado")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config():
    return {"tts_engine": TTS_ENGINE, "has_character": CHARACTER_CLIP.exists()}


@app.post("/api/jobs")
def create_job(title: str = Form(...), mode: str = Form("fill"),
               video: UploadFile = File(...), audio: UploadFile | None = File(None)):
    job = jobs.create(title=title.strip()[:120], mode="fit" if mode == "fit" else "fill")
    jid = job["id"]
    vpath = _save(video, UPLOADS, jid, VIDEO_EXT)
    apath = _save(audio, AUDIO, f"{jid}_guide", AUDIO_EXT) if audio and audio.filename else ""
    jobs.update(jid, video_path=vpath, audio_path=apath, status="queued")
    pool.submit(pipeline.step_transcribe, jid)
    return {"id": jid}


class GenerateIn(BaseModel):
    script: str = ""
    title: str | None = None


@app.post("/api/jobs/{job_id}/generate")
def generate(job_id: str, body: GenerateIn):
    job = _job(job_id)
    if job["status"] not in ("script_ready", "error", "done"):
        raise HTTPException(409, "El trabajo aún no está listo")
    jobs.update(job_id, script=body.script, status="queued", error="", progress=0,
                **({"title": body.title.strip()[:120]} if body.title else {}))
    pool.submit(pipeline.step_generate, job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}")
def status(job_id: str):
    j = _job(job_id)
    return {k: j.get(k) for k in ("id", "title", "status", "progress", "script", "error", "notice")} | {
        "done": j["status"] == "done"}


@app.get("/api/jobs/{job_id}/video")
def video(job_id: str):
    j = _job(job_id)
    if not j.get("output"):
        raise HTTPException(404, "Aún no hay video")
    return FileResponse(j["output"], media_type="video/mp4")


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    j = _job(job_id)
    if not j.get("output"):
        raise HTTPException(404, "Aún no hay video")
    return FileResponse(j["output"], media_type="video/mp4", filename=f"{j['title'] or 'video'}.mp4")
