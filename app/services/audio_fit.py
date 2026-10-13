import subprocess
from .probe import probe

MAX_SPEEDUP = 1.3


def fit_audio(audio_in: str, video_duration: float, audio_out: str) -> float:
    """Ajusta el audio a la duración del video. Devuelve el factor aplicado."""
    ratio = probe(audio_in)["duration"] / video_duration
    filters = []
    if ratio > 1.0:
        filters.append(f"atempo={min(ratio, MAX_SPEEDUP):.4f}")
    filters.append("apad")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_in, "-af", ",".join(filters),
                    "-t", f"{video_duration:.3f}", "-ar", "44100", "-ac", "2", audio_out], check=True)
    return ratio
