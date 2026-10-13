import asyncio
import importlib
import os
import subprocess
import tempfile
from pathlib import Path

import requests

from ..config import env
from .voices import STYLES, get_voice


def synthesize(text: str, out_base: str, voice_id: str = "edge-jorge", style: str = "relajado") -> str:
    """Genera una narración y devuelve la ruta del archivo creado."""
    if style not in STYLES:
        raise ValueError(f"Estilo desconocido: {style}")
    voice = get_voice(voice_id)
    settings = STYLES[style]
    out = Path(out_base + ".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)

    if voice["engine"] == "sapi":
        if os.name != "nt":
            raise RuntimeError("Las voces locales de Windows solo están disponibles en Windows.")
        output = Path(out_base + ".wav")
        rate = {"relajado": -1, "normal": 0, "energico": 2}[style]
        with tempfile.TemporaryDirectory(prefix="videostudio-tts-") as temp_dir:
            temp = Path(temp_dir)
            text_file = temp / "script.txt"
            script_file = temp / "speak.ps1"
            text_file.write_text(text, encoding="utf-8")
            script_file.write_text(
                "param([string]$TextPath,[string]$OutputPath,[string]$VoiceName,[int]$Rate)\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "$synth.SelectVoice($VoiceName)\n"
                "$synth.Rate = $Rate\n"
                "$synth.SetOutputToWaveFile($OutputPath)\n"
                "$synth.Speak([System.IO.File]::ReadAllText($TextPath))\n"
                "$synth.Dispose()\n",
                encoding="utf-8",
            )
            try:
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                     "Bypass", "-File", str(script_file), str(text_file), str(output),
                     voice["voice"], str(rate)],
                    check=True, capture_output=True, text=True, timeout=120,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                output.unlink(missing_ok=True)
                detail = (error.stderr or "").strip() if isinstance(error, subprocess.CalledProcessError) else "tiempo de espera agotado"
                raise RuntimeError(f"No se pudo generar la voz local de Windows: {detail}") from error
        return str(output)

    if voice["engine"] == "edge":
        import edge_tts

        asyncio.run(edge_tts.Communicate(
            text, voice["voice"], rate=settings["rate"], pitch=settings["pitch"]
        ).save(str(out)))
        return str(out)

    if voice["engine"] == "elevenlabs":
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice['voice']}",
            headers={"xi-api-key": env("ELEVENLABS_API_KEY")},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": settings["stability"],
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "speed": settings["speed"],
                },
            },
            timeout=180,
        )
        response.raise_for_status()
        out.write_bytes(response.content)
        return str(out)

    if voice["engine"] == "xtts":
        TTS = importlib.import_module("TTS.api").TTS
        output = Path(out_base + ".wav")
        TTS("tts_models/multilingual/multi-dataset/xtts_v2").tts_to_file(
            text=text,
            speaker_wav=voice["voice"],
            language=env("LANGUAGE", "es"),
            file_path=str(output),
        )
        return str(output)

    raise RuntimeError(f"Motor de voz no soportado: {voice['engine']}")
