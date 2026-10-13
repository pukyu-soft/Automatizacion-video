import math
import subprocess
from .probe import probe

MAX_SPEEDUP = 1.3
MIN_NARRATION_SPEED = 0.75
MAX_NARRATION_SPEED = 1.25


def fit_audio(
    audio_in: str,
    video_duration: float,
    audio_out: str,
    overflow: str = "speed",
    narration_speed: float = 1.0,
) -> tuple[float, float]:
    """Prepara audio sin perder palabras; devuelve factor de velocidad y duración final."""
    if video_duration <= 0:
        raise ValueError("La duración del video debe ser mayor que cero.")
    if overflow not in {"speed", "extend", "shorten"}:
        raise ValueError(f"Política de duración desconocida: {overflow}")
    if not math.isfinite(narration_speed) or not MIN_NARRATION_SPEED <= narration_speed <= MAX_NARRATION_SPEED:
        raise ValueError(
            f"La velocidad de narración debe estar entre {MIN_NARRATION_SPEED:.2f}× "
            f"y {MAX_NARRATION_SPEED:.2f}×."
        )

    audio_duration = probe(audio_in)["duration"] / narration_speed
    ratio = audio_duration / video_duration
    if overflow == "shorten" and ratio > 1:
        raise ValueError("El guion es más largo que el video; acórtalo o elige acelerar/extender.")

    filters = []
    if narration_speed != 1.0:
        filters.append(f"atempo={narration_speed:.4f}")
    if overflow == "speed" and ratio > 1.0:
        filters.append(f"atempo={min(ratio, MAX_SPEEDUP):.4f}")
    filters.append("apad")
    output_duration = max(video_duration, audio_duration / MAX_SPEEDUP) if overflow == "speed" else (
        max(video_duration, audio_duration) if overflow == "extend" else video_duration
    )
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_in, "-af", ",".join(filters),
                    "-t", f"{output_duration:.3f}", "-ar", "44100", "-ac", "2", audio_out], check=True)
    return ratio, output_duration
