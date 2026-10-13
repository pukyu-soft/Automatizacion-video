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
    segments, _ = _get_model().transcribe(str(audio_path), language=language, word_timestamps=True)
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
