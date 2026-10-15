import subprocess

import numpy as np

from ..config import env

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # import perezoso
        _model = WhisperModel(env("WHISPER_MODEL", "small"),
                              device=env("WHISPER_DEVICE", "cpu"),
                              compute_type=env("WHISPER_COMPUTE", "int8"))
    return _model


def transcribe(audio_path: str, language: str = "es"):
    """Devuelve (texto, [{word,start,end}, ...])."""
    decoded = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(audio_path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if decoded.returncode:
        detail = decoded.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"No se pudo decodificar el audio: {detail[-1000:]}")
    audio = np.frombuffer(decoded.stdout, dtype=np.float32)
    if not audio.size:
        raise ValueError("El archivo no contiene audio que se pueda transcribir.")

    segments, _ = _get_model().transcribe(
        audio, language=language, word_timestamps=True
    )
    words, text = [], []
    for seg in segments:
        text.append(seg.text.strip())
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    return " ".join(text).strip(), words


def estimate_words(text: str, duration: float):
    """Plan B sin Whisper: reparte las palabras en el tiempo según su largo."""
    toks = text.split()
    if not toks:
        return []
    weights = [len(t) + 2 for t in toks]
    total, t, out = sum(weights), 0.0, []
    for tok, wt in zip(toks, weights):
        d = duration * wt / total
        out.append({"word": tok, "start": t, "end": t + d})
        t += d
    return out
