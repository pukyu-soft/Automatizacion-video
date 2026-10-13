import requests
from ..config import env, TTS_ENGINE


def synthesize(text: str, out_base: str) -> str:
    """Genera la voz y devuelve la ruta del archivo creado."""
    if TTS_ENGINE == "elevenlabs":
        out = out_base + ".mp3"
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{env('ELEVENLABS_VOICE_ID')}",
            headers={"xi-api-key": env("ELEVENLABS_API_KEY")},
            json={"text": text, "model_id": "eleven_multilingual_v2"}, timeout=180)
        r.raise_for_status()
        open(out, "wb").write(r.content)
        return out
    if TTS_ENGINE == "xtts":
        from TTS.api import TTS  # pip install TTS
        out = out_base + ".wav"
        TTS("tts_models/multilingual/multi-dataset/xtts_v2").tts_to_file(
            text=text, speaker_wav=env("XTTS_SPEAKER_WAV"), language=env("LANGUAGE", "es"), file_path=out)
        return out
    raise RuntimeError(f"Motor de voz no válido: {TTS_ENGINE}")
