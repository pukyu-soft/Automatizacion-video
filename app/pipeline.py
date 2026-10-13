import traceback
from . import jobs
from .config import AUDIO, WORK, OUTPUT, TTS_ENGINE, LANGUAGE
from .services.probe import probe
from .services.transcribe import transcribe, estimate_words
from .services.tts import synthesize
from .services.audio_fit import fit_audio
from .services.subtitles import build_ass
from .services.render import render
from .services.notify import send_telegram


def step_transcribe(job_id: str):
    """Paso 1: transcribe tu audio guía para que puedas editar el guion."""
    try:
        job = jobs.get(job_id)
        if job.get("audio_path"):
            jobs.update(job_id, status="transcribing", progress=10)
            try:
                text, _ = transcribe(job["audio_path"], LANGUAGE)
                jobs.update(job_id, script=text)
            except Exception as e:  # sin Whisper: escribes el guion a mano
                jobs.update(job_id, notice=f"No pude transcribir ({type(e).__name__}). Escribe el guion a mano.")
        jobs.update(job_id, status="script_ready", progress=0)
    except Exception as e:
        jobs.update(job_id, status="error", error=f"{e}\n{traceback.format_exc(limit=3)}")


def step_generate(job_id: str):
    """Paso 2: voz → ajuste → tiempos → subtítulos → render → entrega."""
    try:
        job = jobs.get(job_id)
        script = job["script"].strip()
        work = WORK / job_id
        work.mkdir(exist_ok=True)

        jobs.update(job_id, status="analyzing", progress=5)
        duration = probe(job["video_path"])["duration"]

        if TTS_ENGINE != "none" and script:
            jobs.update(job_id, status="tts", progress=20)
            raw = synthesize(script, str(AUDIO / f"{job_id}_tts"))
        elif job.get("audio_path"):
            raw = job["audio_path"]
        else:
            raise RuntimeError("No hay audio: graba tu narración o configura TTS_ENGINE.")

        jobs.update(job_id, status="fitting", progress=40)
        fitted = str(AUDIO / f"{job_id}_fit.wav")
        fit_audio(raw, duration, fitted)

        jobs.update(job_id, status="subtitles", progress=55)
        try:
            _, words = transcribe(fitted, LANGUAGE)
        except Exception:
            words = []
        if not words:                                   # plan B sin Whisper
            words = estimate_words(script, duration)
        ass = work / "subs.ass"
        build_ass(job["title"], words, duration, str(ass))

        jobs.update(job_id, status="rendering", progress=70)
        out = OUTPUT / f"{job_id}.mp4"
        render(job["video_path"], fitted, ass, duration, out, job.get("mode", "fill"),
               on_progress=lambda p: jobs.update(job_id, progress=int(70 + p * 28)))

        jobs.update(job_id, status="done", progress=100, output=str(out))
        try:
            send_telegram(str(out), job["title"], job_id)
        except Exception:
            pass
    except Exception as e:
        jobs.update(job_id, status="error", error=str(e))
