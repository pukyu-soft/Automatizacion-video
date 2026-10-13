# VideoStudio (versión mínima)

Sube un video, graba tu narración y presiona **Generar**. Obtienes un video vertical 1080x1920:

```
┌────────────────────┐  0-330     Título (verde) sobre el mismo video con blur
├────────────────────┤  330-1290  Video original (recortado o completo) + subtítulos
├────────────────────┤  1290-1920 Tu personaje en loop + subtítulos karaoke (palabra activa en amarillo)
└────────────────────┘
```

## Inicio rápido

```bash
# 1. Requisitos del sistema
sudo apt install -y ffmpeg python3-venv        # Ubuntu/Debian

# 2. Entorno
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Configuración
cp .env.example .env                           # edítalo si quieres voz clonada, Telegram, etc.

# 4. Tu clip de personaje (loop, de preferencia 1080x630 o más ancho)
cp /ruta/a/tu_clip.mp4 assets/personaje_loop.mp4

# 5. Arrancar
uvicorn app.main:app --host 127.0.0.1 --port 8000
# abre http://localhost:8000
```

Sin `assets/personaje_loop.mp4` el sistema usa un fondo morado liso en esa zona, así puedes probar todo antes de tener el clip.

## Uso por consola (sin web)

```bash
python run.py video.mp4 "Mi título" --audio narracion.m4a
python run.py video.mp4 "Mi título" --audio narracion.m4a --script "Texto de la narración" --mode fit
```

## Estructura

```
videostudio/
├── app/
│   ├── main.py            API FastAPI + login básico (APP_PASSWORD)
│   ├── pipeline.py        Flujo: transcribir → voz → ajuste → subtítulos → render → Telegram
│   ├── jobs.py            Trabajos guardados como JSON en storage/jobs
│   ├── config.py          Variables de entorno y medidas del lienzo
│   └── services/
│       ├── probe.py       ffprobe (duración, resolución)
│       ├── transcribe.py  faster-whisper (+ plan B sin Whisper)
│       ├── tts.py         ElevenLabs / XTTS
│       ├── audio_fit.py   Ajusta el audio a la duración del video
│       ├── subtitles.py   Genera el .ass (título + 2 subtítulos)
│       ├── render.py      Comando FFmpeg final
│       └── notify.py      Envío por Telegram
├── static/                Interfaz: index.html, style.css, app.js
├── assets/                personaje_loop.mp4 y fonts/ (aquí pon Impact .ttf si quieres)
├── storage/               uploads, audio, work, output, jobs
├── run.py                 Modo consola
└── .env.example
```

## Cómo funciona el flujo web

1. **Paso 1**: eliges el video, escribes el título y el modo (*Recortar y llenar* o *Completo*).
2. **Paso 2**: grabas tu narración en el navegador o subes un audio (opcional).
3. Se transcribe con Whisper y aparece el **guion editable**. Si Whisper no está disponible, escribes el guion a mano.
4. **Generar**: se crea la voz (según `TTS_ENGINE`), se ajusta al largo del video, se calculan los tiempos por palabra, se arma el `.ass` y se renderiza.
5. El video aparece en la vista previa 9:16 con botón de descarga; si configuraste Telegram, también te llega allí.

## Voz (`TTS_ENGINE`)

| Valor | Qué hace |
|-------|----------|
| `none` | Usa tu audio grabado tal cual (ideal para empezar y probar). |
| `elevenlabs` | Convierte el guion a tu voz clonada. Requiere `ELEVENLABS_API_KEY` y `ELEVENLABS_VOICE_ID`. |
| `xtts` | Voz clonada local y gratis. `pip install TTS` y una muestra limpia en `XTTS_SPEAKER_WAV`. Pesado: conviene GPU. |

## Notas importantes

- **Micrófono en el navegador**: solo funciona en `localhost` o con HTTPS.
- **Fuente**: el estilo usa `Impact`. Si no está instalada, FFmpeg usa otra. Copia un `.ttf` a `assets/fonts/` y pon su nombre en `FONT_NAME`.
- **Subtítulos karaoke**: cada palabra activa se resalta con una línea propia en amarillo (más fiable que `\k` de ASS).
- **Audio más largo que el video**: se acelera hasta 1.3x como máximo; si aún sobra, se corta. Acorta el guion si lo notas.
- **Un render a la vez**: `ThreadPoolExecutor(max_workers=1)` en `app/main.py`.
- **Seguridad**: pon `APP_PASSWORD` en `.env` antes de exponerlo en tu dominio (y usa HTTPS con Nginx).
- **Derechos de autor**: clips de series pueden activar Content ID en las plataformas.

## Siguientes pasos sugeridos

- Despliegue: Nginx + HTTPS + servicio systemd (ver la guía `PROYECTO_VideoStudio.md`).
- Música de fondo con volumen bajo.
- Varias plantillas de personaje o fondo.
- Lip-sync del personaje (Wav2Lip / LivePortrait).
