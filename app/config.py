import os
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _path(key: str, default: Path) -> Path:
    p = Path(env(key, str(default)))
    return p if p.is_absolute() else (BASE / p).resolve()


STORAGE = _path("STORAGE_DIR", BASE / "storage")
UPLOADS, AUDIO, WORK, OUTPUT, JOBS = (STORAGE / d for d in ("uploads", "audio", "work", "output", "jobs"))
for d in (UPLOADS, AUDIO, WORK, OUTPUT, JOBS):
    d.mkdir(parents=True, exist_ok=True)

CHARACTER_CLIP = _path("CHARACTER_CLIP", BASE / "assets" / "personaje_loop.mp4")
FONTS_DIR = BASE / "assets" / "fonts"
CHARACTERS_DIR = BASE / "assets" / "characters"
MUSIC_DIR = BASE / "assets" / "music"
FONT_NAME = env("FONT_NAME", "Impact")

APP_PASSWORD = env("APP_PASSWORD")
TTS_ENGINE = env("TTS_ENGINE", "none").lower()
LANGUAGE = env("LANGUAGE", "es")
PUBLIC_URL = env("PUBLIC_URL", "http://localhost:8000")
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "500"))

# Lienzo final 9:16
W, H = 1080, 1920
TOP_H, MID_H, BOT_H = 330, 960, 630   # suman 1920
