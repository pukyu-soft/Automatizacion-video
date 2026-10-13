"""Voces y estilos disponibles para la narración."""
import os

from ..config import TTS_ENGINE, env

STYLES = {
    "relajado": {"rate": "-10%", "pitch": "-5Hz", "stability": 0.75, "speed": 0.90},
    "normal": {"rate": "+0%", "pitch": "+0Hz", "stability": 0.50, "speed": 1.00},
    "energico": {"rate": "+8%", "pitch": "+2Hz", "stability": 0.35, "speed": 1.08},
}

VOICES = [
    {"id": "edge-jorge", "label": "Jorge · México (hombre)", "engine": "edge", "voice": "es-MX-JorgeNeural"},
    {"id": "edge-alvaro", "label": "Álvaro · España (hombre)", "engine": "edge", "voice": "es-ES-AlvaroNeural"},
    {"id": "edge-tomas", "label": "Tomás · Argentina (hombre)", "engine": "edge", "voice": "es-AR-TomasNeural"},
    {"id": "edge-gonzalo", "label": "Gonzalo · Colombia (hombre)", "engine": "edge", "voice": "es-CO-GonzaloNeural"},
]


def list_voices() -> list[dict]:
    voices = []
    if os.name == "nt":
        voices.extend([
            {"id": "sapi-sabina", "label": "Sabina · México (local)", "engine": "sapi",
             "voice": "Microsoft Sabina Desktop"},
            {"id": "sapi-helena", "label": "Helena · España (local)", "engine": "sapi",
             "voice": "Microsoft Helena Desktop"},
        ])
    voices.extend(VOICES)
    if env("ELEVENLABS_API_KEY") and env("ELEVENLABS_VOICE_ID"):
        voices.append({
            "id": "eleven-custom",
            "label": "Mi voz (ElevenLabs)",
            "engine": "elevenlabs",
            "voice": env("ELEVENLABS_VOICE_ID"),
        })
    if TTS_ENGINE == "xtts" and env("XTTS_SPEAKER_WAV"):
        voices.append({
            "id": "xtts-local",
            "label": "Voz local (XTTS-v2)",
            "engine": "xtts",
            "voice": env("XTTS_SPEAKER_WAV"),
        })
    return voices


def get_voice(voice_id: str) -> dict:
    for voice in list_voices():
        if voice["id"] == voice_id:
            return voice
    raise ValueError(f"Voz desconocida: {voice_id}")
