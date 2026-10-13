import secrets
import logging
import shutil
import hashlib
import hmac
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import jobs, pipeline
from .config import (APP_PASSWORD, UPLOADS, AUDIO, CHARACTER_CLIP,
                     MAX_UPLOAD_MB, BASE, OUTPUT, CHARACTERS_DIR, MUSIC_DIR, FONTS_DIR, LANGUAGE)
from .services.audio_fit import fit_audio
from .services.probe import probe
from .services.text_clean import clean_script
from .services.transcribe import estimate_words, transcribe
from .services.voices import STYLES, list_voices

app = FastAPI(title="VideoStudio")
logger = logging.getLogger(__name__)
pool = ThreadPoolExecutor(max_workers=1)          # un render a la vez
STATIC = BASE / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
MUSIC_EXT = {".mp3", ".wav", ".ogg", ".m4a"}
FONT_EXT = {".ttf", ".otf"}


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


class SampleIn(BaseModel):
    voice: str = "edge-jorge"
    style: str = "relajado"
    text: str = "Hola, así sonaría tu narración. Con calma, sin prisa."


class LoginIn(BaseModel):
    password: str


def _valid_session(value: str | None) -> bool:
    if not APP_PASSWORD or not value:
        return not APP_PASSWORD
    try:
        expiry_text, signature = value.split(".", 1)
        expiry = int(expiry_text)
    except (ValueError, TypeError):
        return False
    if expiry < int(time.time()) or expiry > int(time.time()) + 12 * 60 * 60:
        return False
    expected = hmac.new(APP_PASSWORD.encode(), expiry_text.encode(), hashlib.sha256).hexdigest()
    return secrets.compare_digest(signature, expected)


@app.middleware("http")
async def require_login(request: Request, call_next):
    if (not APP_PASSWORD or request.url.path == "/" or request.url.path == "/api/login"
            or request.url.path.startswith("/static/")):
        return await call_next(request)
    if _valid_session(request.cookies.get("videostudio_session")):
        return await call_next(request)
    return JSONResponse({"detail": "Inicia sesión para continuar."}, status_code=401)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/login")
def login(body: LoginIn, response: Response, request: Request):
    if not APP_PASSWORD or not secrets.compare_digest(body.password, APP_PASSWORD):
        raise HTTPException(401, "Contraseña incorrecta.")
    expiry_text = str(int(time.time()) + 12 * 60 * 60)
    signature = hmac.new(APP_PASSWORD.encode(), expiry_text.encode(), hashlib.sha256).hexdigest()
    response.set_cookie(
        "videostudio_session", f"{expiry_text}.{signature}",
        max_age=12 * 60 * 60, httponly=True, secure=request.url.scheme == "https",
        samesite="strict", path="/",
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("videostudio_session", path="/")
    return {"ok": True}


@app.get("/api/config")
def config():
    characters = sorted(
        p.name for p in CHARACTERS_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXT
    ) if CHARACTERS_DIR.exists() else []
    music = sorted(
        p.name for p in MUSIC_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in MUSIC_EXT
    ) if MUSIC_DIR.exists() else []
    fonts = sorted(p.stem for p in FONTS_DIR.glob("*") if p.is_file() and p.suffix.lower() in FONT_EXT)
    return {
        "tts_engine": "voces locales de Windows, Edge TTS y ElevenLabs (si está configurado)",
        "requires_login": bool(APP_PASSWORD),
        "has_character": CHARACTER_CLIP.exists() or bool(characters),
        "voices": [{"id": v["id"], "label": v["label"]} for v in list_voices()],
        "styles": list(STYLES),
        "characters": characters,
        "music": music,
        "fonts": fonts,
    }


@app.get("/api/voices")
def voices():
    return {
        "voices": [{"id": v["id"], "label": v["label"]} for v in list_voices()],
        "styles": list(STYLES),
    }


@app.post("/api/voices/sample")
def voice_sample(body: SampleIn):
    text = clean_script(body.text[:300])
    if not text:
        text = "Hola, así sonaría tu narración. Con calma, sin prisa."
    try:
        path = pipeline.get_tts_audio(text, body.voice, body.style)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ImportError as e:
        logger.exception("Falta una dependencia al generar la muestra de voz %s", body.voice)
        raise HTTPException(
            503,
            "Falta edge-tts en el entorno que está ejecutando VideoStudio. "
            "Instala requirements.txt con ese mismo Python y reinicia el servidor.",
        ) from e
    except Exception as e:
        logger.exception("Falló la generación de la muestra de voz %s", body.voice)
        raise HTTPException(
            502, f"No se pudo generar la muestra con la voz seleccionada: {e}"
        ) from e
    media_type = mimetypes.guess_type(path)[0] or "audio/mpeg"
    return FileResponse(path, media_type=media_type)


@app.get("/api/jobs")
def list_jobs():
    history = []
    for file in jobs.JOBS.glob("*.json"):
        try:
            item = jobs.get(file.stem)
        except (KeyError, ValueError):
            continue
        history.append({
            key: item.get(key) for key in
            ("id", "title", "status", "progress", "created_at", "error")
        })
    return {"jobs": sorted(history, key=lambda j: j["created_at"] or 0, reverse=True)}


@app.post("/api/jobs")
def create_job(title: str = Form(...), mode: str = Form("fill"),
               video: UploadFile = File(...), character_video: UploadFile = File(...)):
    if not title.strip():
        raise HTTPException(400, "Escribe un título.")
    job = jobs.create(title=title.strip()[:120], mode="fit" if mode == "fit" else "fill")
    jid = job["id"]
    vpath = cpath = None
    try:
        vpath = _save(video, UPLOADS, jid, VIDEO_EXT)
        cpath = _save(character_video, UPLOADS, f"{jid}_character", VIDEO_EXT)
        if not probe(vpath)["width"] or not probe(cpath)["width"]:
            raise HTTPException(400, "Los dos archivos deben contener un video válido.")
    except HTTPException:
        for path in (vpath, cpath):
            if path and Path(path).exists():
                Path(path).unlink()
        jobs.update(jid, status="error")
        raise
    except Exception:
        for path in (vpath, cpath):
            if path and Path(path).exists():
                Path(path).unlink()
        jobs.update(jid, status="error")
        raise HTTPException(400, "No se pudieron leer los videos. Comprueba que no estén dañados.")
    jobs.update(jid, video_path=vpath, character_path=cpath, audio_path="", status="queued")
    pool.submit(pipeline.step_transcribe, jid)
    return {"id": jid}


class GenerateIn(BaseModel):
    script: str = ""
    title: str | None = None
    mode: str = "fill"
    voice: str | None = None
    style: str = "relajado"
    duration_mode: str = "speed"
    title_color: str = "verde"
    title_style: str = "clasico"
    music: str | None = None
    subtitle_style: str = "clasico"
    font_name: str = "Impact"
    max_words: int = 4


def _validate_options(body: GenerateIn) -> None:
    valid_voices = {v["id"] for v in list_voices()}
    if body.voice and body.voice not in valid_voices:
        raise HTTPException(400, "Voz no válida.")
    if body.style not in STYLES:
        raise HTTPException(400, "Estilo de voz no válido.")
    if body.duration_mode not in {"speed", "extend", "shorten"}:
        raise HTTPException(400, "Opción de duración no válida.")
    if body.mode not in {"fill", "fit"}:
        raise HTTPException(400, "Ajuste del video no válido.")
    if body.subtitle_style not in {"clasico", "compacto", "alto_contraste"}:
        raise HTTPException(400, "Estilo de subtítulos no válido.")
    if not 1 <= body.max_words <= 8:
        raise HTTPException(400, "La cantidad de palabras debe estar entre 1 y 8.")
    fonts = {p.stem for p in FONTS_DIR.glob("*") if p.is_file() and p.suffix.lower() in FONT_EXT}
    if body.font_name != "Impact" and body.font_name not in fonts:
        raise HTTPException(400, "Fuente no disponible.")
    if body.title_color not in {"verde", "amarillo", "blanco", "cian", "rosa"}:
        raise HTTPException(400, "Color del título no válido.")
    if body.title_style not in {"clasico", "contorno", "sombra"}:
        raise HTTPException(400, "Estilo del título no válido.")
    if body.music:
        valid = {p.name for p in MUSIC_DIR.glob("*") if p.is_file() and p.suffix.lower() in MUSIC_EXT}
        if body.music not in valid:
            raise HTTPException(400, "Pista de música no disponible.")


def _save_generation_options(job_id: str, body: GenerateIn) -> str:
    _validate_options(body)
    script = clean_script(body.script)
    jobs.update(
        job_id,
        script=script,
        mode=body.mode,
        voice=body.voice,
        style=body.style,
        duration_mode=body.duration_mode,
        title_color=body.title_color,
        title_style=body.title_style,
        music=body.music,
        subtitle_style=body.subtitle_style,
        font_name=body.font_name,
        max_words=body.max_words,
        **({"title": body.title.strip()[:120]} if body.title and body.title.strip() else {}),
    )
    return script


@app.post("/api/jobs/{job_id}/generate")
def generate(job_id: str, body: GenerateIn):
    job = _job(job_id)
    if job["status"] not in ("script_ready", "error", "done"):
        raise HTTPException(409, "El trabajo aún no está listo")
    script = _save_generation_options(job_id, body)
    if not script:
        raise HTTPException(400, "Escribe el guion de la narración.")
    if not body.voice:
        raise HTTPException(400, "Elige una voz para generar la narración.")
    pipeline.reset_cancel(job_id)
    jobs.update(job_id, status="queued", error="", progress=0)
    pool.submit(pipeline.step_generate, job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}")
def status(job_id: str):
    j = _job(job_id)
    return {k: j.get(k) for k in (
        "id", "title", "status", "progress", "script", "error", "notice",
        "preview_ready", "created_at", "duration_mode"
    )} | {
        "done": j["status"] == "done"}


@app.get("/api/jobs/{job_id}/duration")
def job_duration(job_id: str):
    return {"duration": probe(_job(job_id)["video_path"])["duration"]}


@app.post("/api/jobs/{job_id}/preview")
def make_preview(job_id: str, body: GenerateIn):
    job = _job(job_id)
    if job["status"] not in ("script_ready", "error"):
        raise HTTPException(409, "El trabajo aún no está listo")
    script = _save_generation_options(job_id, body)
    if not script:
        raise HTTPException(400, "Escribe el guion de la narración.")
    if not body.voice:
        raise HTTPException(400, "Elige una voz para generar la narración.")
    pipeline.reset_cancel(job_id)
    jobs.update(job_id, status="queued", error="", progress=0, preview_ready=False)
    pool.submit(pipeline.step_preview, job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/preview.mp4")
def preview_video(job_id: str):
    p = OUTPUT / f"{_job(job_id)['id']}_preview.mp4"
    if not p.exists():
        raise HTTPException(404, "Aún no hay vista previa")
    return FileResponse(p, media_type="video/mp4")


@app.post("/api/jobs/{job_id}/preview-data")
def preview_data(job_id: str, body: GenerateIn):
    job = _job(job_id)
    _save_generation_options(job_id, body)
    script = clean_script(body.script)
    if not script:
        raise HTTPException(400, "Escribe el guion de la narración.")
    video_duration = probe(job["video_path"])["duration"]
    if not body.voice:
        raise HTTPException(400, "Elige una voz para generar la narración.")
    if not job.get("character_path") and not job.get("character"):
        raise HTTPException(400, "Este trabajo no tiene un video de personaje. Crea un trabajo nuevo y súbelo.")
    raw = pipeline.get_tts_audio(script, body.voice, body.style)
    fitted = str(AUDIO / f"{job_id}_fit.wav")
    try:
        _, duration = fit_audio(raw, video_duration, fitted, body.duration_mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        _, words = transcribe(fitted, LANGUAGE)
    except Exception:
        words = []
    words = words or estimate_words(script, duration)
    return {"duration": duration, "video_duration": video_duration, "words": words}


@app.get("/api/jobs/{job_id}/source")
def source_video(job_id: str):
    return FileResponse(_job(job_id)["video_path"])


@app.get("/api/jobs/{job_id}/character")
def job_character_video(job_id: str):
    path = _job(job_id).get("character_path")
    if not path or not Path(path).is_file():
        raise HTTPException(404, "No se encontró el video del personaje para este trabajo.")
    return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "video/mp4")


@app.get("/api/character")
def character(name: str | None = None):
    if name:
        target = (CHARACTERS_DIR / Path(name).name).resolve()
        if target.parent != CHARACTERS_DIR.resolve() or not target.is_file():
            raise HTTPException(404, "Personaje no encontrado")
    else:
        target = CHARACTER_CLIP
    if not target.exists():
        raise HTTPException(404, "Falta el clip de personaje en assets/")
    return FileResponse(target, media_type=mimetypes.guess_type(str(target))[0] or "video/mp4")


@app.get("/api/jobs/{job_id}/audio-fit")
def audio_fit(job_id: str):
    path = AUDIO / f"{_job(job_id)['id']}_fit.wav"
    if not path.exists():
        raise HTTPException(404, "Aún no hay audio preparado")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = _job(job_id)
    if job["status"] in {"done", "error", "cancelled"}:
        raise HTTPException(409, "El trabajo ya terminó.")
    pipeline.cancel_job(job_id)
    jobs.update(job_id, status="cancelling")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    job = _job(job_id)
    if job["status"] not in {"error", "cancelled"}:
        raise HTTPException(409, "Solo se pueden reintentar trabajos con error o cancelados.")
    if not job.get("video_path"):
        raise HTTPException(409, "El trabajo no conserva el video original.")
    if not job.get("character_path"):
        raise HTTPException(
            409,
            "Este trabajo es anterior al clip de personaje por proyecto. Crea un trabajo nuevo y adjunta ese video.",
        )
    pipeline.reset_cancel(job_id)
    jobs.update(job_id, status="queued", error="", progress=0)
    pool.submit(pipeline.step_generate if job.get("script") else pipeline.step_transcribe, job_id)
    return {"ok": True}


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
