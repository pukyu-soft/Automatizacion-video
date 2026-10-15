import secrets
import logging
import math
import shutil
import hashlib
import hmac
import mimetypes
import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import jobs, pipeline
from .config import (APP_PASSWORD, UPLOADS, AUDIO, CHARACTER_CLIP,
                     MAX_UPLOAD_MB, BASE, OUTPUT, WORK, CHARACTERS_DIR, MUSIC_DIR, FONTS_DIR, LANGUAGE)
from .services.audio_fit import fit_audio
from .services.probe import probe
from .services.text_clean import clean_script
from .services.transcribe import estimate_words, transcribe
from .services.voices import STYLES, list_voices

app = FastAPI(title="VideoStudio")
logger = logging.getLogger(__name__)
pool = ThreadPoolExecutor(max_workers=1)          # un render a la vez
_job_futures: dict[str, Future] = {}
_job_futures_lock = Lock()
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


def _ensure_not_deleting(job: dict) -> None:
    if job.get("delete_requested"):
        raise HTTPException(409, "Este trabajo se está eliminando.")


class SampleIn(BaseModel):
    voice: str = "edge-jorge"
    style: str = "relajado"
    text: str = "Hola, así sonaría tu narración. Con calma, sin prisa."


class LoginIn(BaseModel):
    password: str


class DeleteJobsIn(BaseModel):
    ids: list[str]


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


@app.get("/api/music/{name}")
def music_track(name: str):
    target = (MUSIC_DIR / Path(name).name).resolve()
    if (target.parent != MUSIC_DIR.resolve() or not target.is_file()
            or target.suffix.lower() not in MUSIC_EXT):
        raise HTTPException(404, "Pista de música no encontrada.")
    return FileResponse(target, media_type=mimetypes.guess_type(str(target))[0] or "audio/mpeg")


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
            ("id", "title", "status", "progress", "created_at", "error", "delete_requested")
        })
    return {"jobs": sorted(history, key=lambda j: j["created_at"] or 0, reverse=True)}


def _remove_job_files(job_id: str) -> None:
    for pattern in (f"{job_id}.*", f"{job_id}_character.*"):
        for path in UPLOADS.glob(pattern):
            if path.is_file():
                path.unlink()
    for path in (
        AUDIO / f"{job_id}_fit.wav",
        OUTPUT / f"{job_id}.mp4",
        OUTPUT / f"{job_id}_preview.mp4",
    ):
        path.unlink(missing_ok=True)
    work = WORK / job_id
    if work.exists():
        shutil.rmtree(work)


def _remove_selected_job_files(items: list[dict]) -> None:
    for item in items:
        _remove_job_files(item["id"])


def _finish_requested_delete(job_id: str, future: Future) -> None:
    with _job_futures_lock:
        if _job_futures.get(job_id) is future:
            _job_futures.pop(job_id, None)
    try:
        item = jobs.get(job_id)
        if not item.get("delete_requested"):
            return
        if item.get("status") in jobs.ACTIVE_STATUSES:
            jobs.update(job_id, status="cancelled", progress=0)
        _delete_jobs([job_id])
    except (KeyError, HTTPException):
        return
    except OSError:
        logger.exception("No se pudieron borrar los archivos del trabajo %s", job_id)
        try:
            jobs.update(
                job_id, delete_requested=False, status="error",
                error="No se pudieron borrar todos los archivos. Cierra el video e inténtalo de nuevo.",
            )
        except KeyError:
            pass


def _submit_job(job_id: str, worker, *args) -> None:
    future = pool.submit(worker, *args)
    with _job_futures_lock:
        _job_futures[job_id] = future
    future.add_done_callback(lambda completed: _finish_requested_delete(job_id, completed))


def _delete_jobs(job_ids: list[str]) -> dict:
    if not job_ids or len(job_ids) > 100 or len(set(job_ids)) != len(job_ids):
        raise HTTPException(400, "Selecciona entre 1 y 100 elementos distintos.")
    selected = [_job(job_id) for job_id in job_ids]
    active = []
    for item in selected:
        if item.get("status") not in jobs.ACTIVE_STATUSES:
            continue
        with _job_futures_lock:
            future = _job_futures.get(item["id"])
        if future and not future.done():
            jobs.update(item["id"], delete_requested=True)
            pipeline.cancel_job(item["id"])
            future.cancel()
            active.append(item["id"])
        else:
            jobs.update(item["id"], status="cancelled", progress=0)
    ready_ids = [item["id"] for item in selected if item["id"] not in active]
    if not ready_ids:
        return {"deleted": 0, "deleting": active}
    try:
        deleted = jobs.delete_many(
            ready_ids, before_delete=_remove_selected_job_files
        )
    except KeyError:
        raise HTTPException(404, "Trabajo no encontrado")
    except ValueError as error:
        raise HTTPException(409, str(error))
    except OSError as error:
        logger.exception("No se pudieron borrar todos los archivos del historial")
        raise HTTPException(
            500, "No se pudieron borrar todos los archivos. Cierra el video si está abierto e inténtalo de nuevo."
        ) from error
    return {"deleted": len(deleted), "deleting": active}


@app.delete("/api/jobs")
def delete_selected_jobs(body: DeleteJobsIn):
    return _delete_jobs(body.ids)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    return _delete_jobs([job_id])


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
    _submit_job(jid, pipeline.step_transcribe, jid)
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
    narration_speed: float = 1.0
    video_volume: float = 20
    narration_volume: float = 100
    narration_start: float = 0
    narration_end: float | None = None
    subtitle_position_x: float = 50
    subtitle_position_y: float = 94


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
    if any(
        not math.isfinite(volume) or not 0 <= volume <= 200
        for volume in (body.video_volume, body.narration_volume)
    ):
        raise HTTPException(400, "Los volúmenes deben estar entre 0 % y 200 %.")
    if any(
        not math.isfinite(position) or not 5 <= position <= 95
        for position in (body.subtitle_position_x, body.subtitle_position_y)
    ):
        raise HTTPException(400, "La posición de los subtítulos debe estar entre 5 % y 95 %.")
    if not math.isfinite(body.narration_speed) or not 0.75 <= body.narration_speed <= 1.25:
        raise HTTPException(400, "La velocidad de narración debe estar entre 0,75× y 1,25×.")
    if (not math.isfinite(body.narration_start) or body.narration_start < 0
            or (body.narration_end is not None and
                (not math.isfinite(body.narration_end)
                 or body.narration_end - body.narration_start < 0.05))):
        raise HTTPException(400, "El recorte de narración no es válido.")
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
    fingerprint = _caption_fingerprint(body, script)
    current = _job(job_id)
    saved_words = (
        current.get("subtitle_words")
        if current.get("caption_fingerprint") == fingerprint else None
    )
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
        narration_speed=body.narration_speed,
        video_volume=body.video_volume,
        narration_volume=body.narration_volume,
        subtitle_position_x=body.subtitle_position_x,
        subtitle_position_y=body.subtitle_position_y,
        narration_start=body.narration_start,
        narration_end=body.narration_end,
        subtitle_words=saved_words,
        caption_fingerprint=fingerprint if saved_words else None,
        **({"title": body.title.strip()[:120]} if body.title and body.title.strip() else {}),
    )
    return script


@app.post("/api/jobs/{job_id}/generate")
def generate(job_id: str, body: GenerateIn):
    job = _job(job_id)
    _ensure_not_deleting(job)
    if job["status"] not in ("script_ready", "error", "done"):
        raise HTTPException(409, "El trabajo aún no está listo")
    if (job.get("caption_fingerprint") != _caption_fingerprint(body, clean_script(body.script))
            or not job.get("subtitle_words")):
        raise HTTPException(409, "Ajusta el recorte y genera los subtítulos antes del render.")
    script = _save_generation_options(job_id, body)
    if not script:
        raise HTTPException(400, "Escribe el guion de la narración.")
    if not body.voice:
        raise HTTPException(400, "Elige una voz para generar la narración.")
    pipeline.reset_cancel(job_id)
    jobs.update(job_id, status="queued", error="", progress=0)
    _submit_job(job_id, pipeline.step_generate, job_id)
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
    info = probe(_job(job_id)["video_path"])
    return {"duration": info["duration"], "has_audio": info["has_audio"]}


@app.post("/api/jobs/{job_id}/preview")
def make_preview(job_id: str, body: GenerateIn):
    job = _job(job_id)
    _ensure_not_deleting(job)
    if job["status"] not in ("script_ready", "error"):
        raise HTTPException(409, "El trabajo aún no está listo")
    if (job.get("caption_fingerprint") != _caption_fingerprint(body, clean_script(body.script))
            or not job.get("subtitle_words")):
        raise HTTPException(409, "Ajusta el recorte y genera los subtítulos antes de la muestra.")
    script = _save_generation_options(job_id, body)
    if not script:
        raise HTTPException(400, "Escribe el guion de la narración.")
    if not body.voice:
        raise HTTPException(400, "Elige una voz para generar la narración.")
    pipeline.reset_cancel(job_id)
    jobs.update(job_id, status="queued", error="", progress=0, preview_ready=False)
    _submit_job(job_id, pipeline.step_preview, job_id)
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
    _ensure_not_deleting(job)
    _validate_options(body)
    script = clean_script(body.script)
    if not script:
        raise HTTPException(400, "Escribe el guion de la narración.")
    video_duration = probe(job["video_path"])["duration"]
    if not body.voice:
        raise HTTPException(400, "Elige una voz para generar la narración.")
    raw = pipeline.get_tts_audio(script, body.voice, body.style)
    duration = probe(raw)["duration"]
    if body.narration_end is None:
        values = body.model_dump()
        values["narration_end"] = duration
        body = GenerateIn(**values)
    _save_generation_options(job_id, body)
    return {
        "duration": duration,
        "video_duration": video_duration,
        "audio_url": f"/api/jobs/{job_id}/narration-source",
    }


def _caption_fingerprint(body: GenerateIn, script: str) -> str:
    key = {
        "script": script, "voice": body.voice, "style": body.style,
        "duration_mode": body.duration_mode, "speed": body.narration_speed,
        "start": body.narration_start, "end": body.narration_end,
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()


@app.get("/api/jobs/{job_id}/narration-source")
def narration_source(job_id: str):
    job = _job(job_id)
    _ensure_not_deleting(job)
    if not job.get("voice"):
        raise HTTPException(400, "Selecciona una voz para generar la narración.")
    path = pipeline.get_tts_audio(
        job.get("script", ""), job["voice"], job.get("style", "relajado")
    )
    return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "audio/mpeg")


@app.post("/api/jobs/{job_id}/captions")
def generate_captions(job_id: str, body: GenerateIn):
    job = _job(job_id)
    _ensure_not_deleting(job)
    _validate_options(body)
    if job["status"] not in {"script_ready", "error", "done"}:
        raise HTTPException(409, "El trabajo aún no está listo.")
    script = clean_script(body.script)
    if not script:
        raise HTTPException(400, "Escribe el guion de la narración.")
    if not body.voice:
        raise HTTPException(400, "Elige una voz para generar la narración.")
    raw = pipeline.get_tts_audio(script, body.voice, body.style)
    source_duration = probe(raw)["duration"]
    end = source_duration if body.narration_end is None else body.narration_end
    if end > source_duration or body.narration_start >= end:
        raise HTTPException(400, "El recorte ya no coincide con la duración del audio.")
    values = body.model_dump()
    values["narration_end"] = end
    body = GenerateIn(**values)
    _save_generation_options(job_id, body)
    video_duration = probe(job["video_path"])["duration"]
    fitted = str(AUDIO / f"{job_id}_fit.wav")
    try:
        _, duration = fit_audio(
            raw, video_duration, fitted, body.duration_mode,
            body.narration_speed, body.narration_start, end,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    try:
        _, words = transcribe(fitted, LANGUAGE)
    except Exception as error:
        raise HTTPException(503, f"No se pudieron transcribir los subtítulos: {error}") from error
    if not words:
        if body.narration_start > 0 or end < source_duration - 0.05:
            raise HTTPException(503, "No se detectó voz en el recorte para generar subtítulos.")
        words = estimate_words(script, duration)
    fingerprint = _caption_fingerprint(body, script)
    jobs.update(
        job_id, narration_end=end, subtitle_words=words,
        caption_fingerprint=fingerprint,
    )
    return {"words": words, "duration": duration}


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
    _ensure_not_deleting(job)
    if job["status"] in {"done", "error", "cancelled"}:
        raise HTTPException(409, "El trabajo ya terminó.")
    pipeline.cancel_job(job_id)
    jobs.update(job_id, status="cancelling")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    job = _job(job_id)
    _ensure_not_deleting(job)
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
    _submit_job(
        job_id, pipeline.step_generate if job.get("script") else pipeline.step_transcribe, job_id
    )
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
