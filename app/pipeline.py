import hashlib
import threading
import traceback
import uuid
from pathlib import Path

from . import jobs
from .config import AUDIO, LANGUAGE, OUTPUT, WORK
from .services.audio_fit import fit_audio
from .services.notify import send_telegram
from .services.probe import probe
from .services.render import render
from .services.subtitles import build_ass
from .services.text_clean import clean_script
from .services.transcribe import estimate_words, transcribe
from .services.tts import synthesize
from .services.voices import get_voice

_cancel_lock = threading.Lock()
_cancel_events: dict[str, threading.Event] = {}
_tts_lock = threading.Lock()


def cancel_job(job_id: str) -> None:
    with _cancel_lock:
        _cancel_events.setdefault(job_id, threading.Event()).set()


def reset_cancel(job_id: str) -> None:
    with _cancel_lock:
        _cancel_events[job_id] = threading.Event()


def _cancelled(job_id: str) -> bool:
    with _cancel_lock:
        event = _cancel_events.setdefault(job_id, threading.Event())
    return event.is_set()


def _check_cancel(job_id: str) -> None:
    if _cancelled(job_id):
        raise InterruptedError("Trabajo cancelado.")


def get_tts_audio(script: str, voice: str, style: str = "relajado") -> str:
    script = clean_script(script)
    if not script:
        raise ValueError("Escribe un guion antes de generar la voz.")
    key = hashlib.sha256(f"{voice}|{style}|{script}".encode("utf-8")).hexdigest()[:24]
    suffix = ".wav" if get_voice(voice)["engine"] in {"xtts", "sapi"} else ".mp3"
    path = AUDIO / f"tts_{key}{suffix}"
    with _tts_lock:
        if not path.exists():
            temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp{suffix}")
            try:
                generated = Path(synthesize(script, str(temporary.with_suffix("")), voice, style))
                generated.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return str(path)


def _audio_for(job: dict, script: str) -> str:
    voice = job.get("voice")
    if voice:
        return get_tts_audio(script, voice, job.get("style", "relajado"))
    if job.get("audio_path"):
        return job["audio_path"]
    raise RuntimeError("Elige una voz o sube una narración.")


def _words_for(audio: str, script: str, duration: float) -> list:
    try:
        _, words = transcribe(audio, LANGUAGE)
    except Exception:
        words = []
    return words or estimate_words(script, duration)


def _prepare(job_id: str, job: dict, preview: bool = False) -> tuple[str, Path, float, float]:
    script = clean_script(job.get("script", ""))
    if not script:
        raise RuntimeError("El guion está vacío. Escribe la narración antes de continuar.")
    job = jobs.update(job_id, script=script)
    work = WORK / job_id
    work.mkdir(parents=True, exist_ok=True)
    video_duration = probe(job["video_path"])["duration"]
    _check_cancel(job_id)

    if job.get("voice"):
        jobs.update(job_id, status="tts", progress=20)
    raw = _audio_for(job, script)
    _check_cancel(job_id)
    jobs.update(job_id, status="fitting", progress=40)
    fitted = str(AUDIO / f"{job_id}_fit.wav")
    _, duration = fit_audio(
        raw, video_duration, fitted, job.get("duration_mode", "speed"),
        job.get("narration_speed", 1.0),
        job.get("narration_start", 0.0), job.get("narration_end"),
    )
    if preview:
        duration = min(duration, 10.0)
    jobs.update(job_id, status="subtitles", progress=55)
    words = job.get("subtitle_words") or _words_for(fitted, script, duration)
    _check_cancel(job_id)

    ass = work / "subs.ass"
    build_ass(
        job.get("title", ""), words, duration, str(ass),
        max_words=int(job.get("max_words", 4)),
        style=job.get("subtitle_style", "clasico"),
        font_name=job.get("font_name", "Impact"),
        title_color=job.get("title_color", "verde"),
        title_style=job.get("title_style", "clasico"),
        subtitle_position_x=job.get("subtitle_position_x", 50),
        subtitle_position_y=job.get("subtitle_position_y", 94),
    )
    return fitted, ass, duration, video_duration


def step_transcribe(job_id: str):
    """Transcribe el audio guía, si existe, y deja el trabajo listo para editar."""
    try:
        job = jobs.get(job_id)
        if job.get("audio_path"):
            jobs.update(job_id, status="transcribing", progress=10)
            _check_cancel(job_id)
            try:
                text, _ = transcribe(job["audio_path"], LANGUAGE)
                jobs.update(job_id, script=clean_script(text))
            except Exception as e:
                jobs.update(job_id, notice=f"No pude transcribir ({type(e).__name__}). Escribe el guion a mano.")
        _check_cancel(job_id)
        jobs.update(job_id, status="script_ready", progress=0)
    except InterruptedError:
        jobs.update(job_id, status="cancelled", progress=0)
    except Exception as e:
        jobs.update(job_id, status="error", error=f"{e}\n{traceback.format_exc(limit=3)}")


def step_generate(job_id: str):
    """Genera audio, subtítulos y el render final."""
    try:
        job = jobs.get(job_id)
        jobs.update(job_id, status="analyzing", progress=5)
        fitted, ass, duration, video_duration = _prepare(job_id, job)
        _check_cancel(job_id)

        jobs.update(job_id, status="rendering", progress=70)
        out = OUTPUT / f"{job_id}.mp4"
        render(
            job["video_path"], fitted, ass, duration, out, job.get("mode", "fill"),
            on_progress=lambda p: jobs.update(job_id, progress=int(70 + p * 28)),
            character=job.get("character"), character_path=job.get("character_path"),
            music=job.get("music"),
            video_volume=job.get("video_volume", 20),
            narration_volume=job.get("narration_volume", 100),
            source_duration=video_duration, cancelled=lambda: _cancelled(job_id),
        )
        _check_cancel(job_id)
        jobs.update(job_id, status="done", progress=100, output=str(out))
        try:
            send_telegram(str(out), job["title"], job_id)
        except Exception:
            pass
    except InterruptedError:
        jobs.update(job_id, status="cancelled", progress=0)
    except Exception as e:
        jobs.update(job_id, status="error", error=str(e))


def step_preview(job_id: str):
    """Renderiza los primeros diez segundos en calidad baja para revisión."""
    try:
        job = jobs.get(job_id)
        jobs.update(job_id, status="preview", progress=5, preview_ready=False)
        fitted, ass, duration, video_duration = _prepare(job_id, job, preview=True)
        _check_cancel(job_id)

        jobs.update(job_id, status="preview", progress=70)
        out = OUTPUT / f"{job_id}_preview.mp4"
        render(
            job["video_path"], fitted, ass, duration, out, job.get("mode", "fill"),
            preview=True, character=job.get("character"),
            character_path=job.get("character_path"), music=job.get("music"),
            video_volume=job.get("video_volume", 20),
            narration_volume=job.get("narration_volume", 100),
            source_duration=video_duration, cancelled=lambda: _cancelled(job_id),
        )
        _check_cancel(job_id)
        jobs.update(job_id, status="script_ready", progress=100, preview_ready=True)
    except InterruptedError:
        jobs.update(job_id, status="cancelled", progress=0)
    except Exception as e:
        jobs.update(job_id, status="error", error=str(e))
