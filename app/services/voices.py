"""Voces y estilos disponibles para la narración."""
import base64
import json
import logging
import os
import re
import subprocess
from functools import lru_cache

from ..config import TTS_ENGINE, env

logger = logging.getLogger(__name__)

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


@lru_cache(maxsize=1)
def _windows_voices() -> list[dict]:
    if os.name != "nt":
        return []
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$voices = $s.GetInstalledVoices() | ForEach-Object { "
        "[PSCustomObject]@{name=$_.VoiceInfo.Name; culture=$_.VoiceInfo.Culture.Name; "
        "gender=$_.VoiceInfo.Gender.ToString()} } | ConvertTo-Json -Compress; "
        "[Console]::Write([Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($voices)))"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
        if not result.stdout.strip():
            return []
        installed_json = base64.b64decode(result.stdout).decode("utf-16-le")
        installed = json.loads(installed_json)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        logger.warning("No se pudieron consultar las voces locales de Windows: %s", error)
        return []

    if isinstance(installed, dict):
        installed = [installed]
    voices = []
    for item in installed:
        name = item["name"]
        culture = item["culture"]
        gender = item["gender"].lower()
        suffix = {"male": "hombre", "female": "mujer"}.get(gender, "voz local")
        if name == "Microsoft Sabina Desktop":
            voice_id = "sapi-sabina"
        elif name == "Microsoft Helena Desktop":
            voice_id = "sapi-helena"
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            voice_id = f"sapi-{culture.lower()}-{slug}"
        label_name = name.removeprefix("Microsoft ").removesuffix(" Desktop")
        voices.append({
            "id": voice_id,
            "label": f"{label_name} · {culture} ({suffix}, local)",
            "engine": "sapi",
            "voice": name,
        })
    return voices


def list_voices() -> list[dict]:
    voices = []
    if os.name == "nt":
        voices.extend(_windows_voices())
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
