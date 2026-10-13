import subprocess
from .probe import probe

MAX_SPEEDUP = 1.3


def fit_audio(audio_in: str, video_duration: float, audio_out: str, overflow: str = "speed") -> tuple[float, float]:
    """Prepara audio sin perder palabras; devuelve factor de velocidad y duración final."""
    audio_duration = probe(audio_in)["duration"]
    if video_duration <= 0:
        raise ValueError("La duración del video debe ser mayor que cero.")
    if overflow not in {"speed", "extend", "shorten"}:
        raise ValueError(f"Política de duración desconocida: {overflow}")

    ratio = audio_duration / video_duration
    if overflow == "shorten" and ratio > 1:
        raise ValueError("El guion es más largo que el video; acórtalo o elige acelerar/extender.")

    filters = []
    if overflow == "speed" and ratio > 1.0:
        filters.append(f"atempo={min(ratio, MAX_SPEEDUP):.4f}")
    filters.append("apad")
    output_duration = max(video_duration, audio_duration / MAX_SPEEDUP) if overflow == "speed" else (
        max(video_duration, audio_duration) if overflow == "extend" else video_duration
    )
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_in, "-af", ",".join(filters),
                    "-t", f"{output_duration:.3f}", "-ar", "44100", "-ac", "2", audio_out], check=True)
    return ratio, output_duration
