# VideoStudio (versión mínima)

Sube el video original y el clip de tu personaje, escribe un guion y presiona **Generar**. VideoStudio crea la narración desde el texto y produce un video vertical 1080x1920:

```
┌────────────────────┐  0-330     Título con color y estilo seleccionables
├────────────────────┤  330-1290  Video original (recortado o completo) + subtítulos
├────────────────────┤  1290-1920 Tu personaje en loop + subtítulos karaoke (palabra activa en amarillo)
└────────────────────┘
```

## Inicio rápido

```bash
# 1. Requisitos del sistema
sudo apt install -y ffmpeg python3-venv        # Ubuntu/Debian

# 2. Entorno
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Ubuntu/Debian: source .venv/bin/activate
python -m pip install -r requirements.txt

# 3. Configuración
cp .env.example .env                           # edítalo si quieres voz clonada, Telegram, etc.

# 4. Arrancar
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# abre http://localhost:8000
```

En Windows, ejecuta la app con el mismo entorno donde instalaste sus dependencias: activa `.venv\Scripts\Activate.ps1` y arranca con `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. La voz local de Sabina está seleccionada primero; Edge TTS queda disponible como alternativa. Si la página conserva voces o pasos antiguos, reinicia el servidor desde `.venv` y recarga el navegador.

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

1. **Paso 1**: eliges el video original y el clip del personaje que aparecerá debajo; el teléfono muestra ambos clips recortados en el diseño final. Define el título y su modo de encuadre.
2. **Paso 2**: escribe el guion, elige una voz y configura subtítulos y duración. Pulsa **Vista instantánea** para escuchar la narración con el audio del video y la música seleccionada. En la línea de tiempo puedes buscar y arrastrar los extremos para recortar; ajusta la velocidad y el volumen de la narración, el volumen del video central y la posición de los subtítulos en la vista. Después pulsa **Generar subtítulos del recorte** para sincronizarlos con el audio editado.
3. **Generar**: cuando la narración y sus subtítulos estén listos, puedes renderizar una muestra o generar el video. El render utiliza el recorte, velocidad, mezcla y posición de subtítulos elegidos en la vista previa.
4. El resultado aparece en la vista previa 9:16 con botón de descarga; si configuraste Telegram, también te llega allí. En el historial puedes eliminar individualmente o seleccionar varios trabajos, incluso los que aún se están ejecutando: se cancelan y se borran sus archivos cuando dejan de usarlos. Puedes volver al primer paso con **Anterior**.

## Voz (`TTS_ENGINE`)

| Valor | Qué hace |
|-------|----------|
| Windows local | Muestra las voces instaladas en Windows; no requiere conexión (el idioma y género disponibles dependen de las voces instaladas). |
| `edge` | Voz generada desde el guion con `edge-tts` (incluido en `requirements.txt`). |
| `elevenlabs` | Convierte el guion a tu voz clonada. Requiere `ELEVENLABS_API_KEY` y `ELEVENLABS_VOICE_ID`. |
| `xtts` | Voz clonada local y gratis. `pip install TTS` y una muestra limpia en `XTTS_SPEAKER_WAV`. Pesado: conviene GPU. |

## Notas importantes

- **Narración**: se crea directamente desde el guion con la voz seleccionada; no se pide un archivo de audio. Los niveles iniciales son 100 % para narración y 20 % para el audio original del video central. Las voces Edge requieren conexión; en Windows también aparecen las voces locales instaladas, incluidas las masculinas disponibles.
- **Fuente**: el estilo usa `Impact`. Si no está instalada, FFmpeg usa otra. Copia un `.ttf` a `assets/fonts/` y pon su nombre en `FONT_NAME`.
- **Subtítulos karaoke**: solo se muestra una línea sincronizada con la narración; la palabra activa se resalta en amarillo (más fiable que `\k` de ASS). Su posición se ajusta en la vista previa y también se aplica al video generado.
- **Audio más largo que el video**: se acelera hasta 1.3x como máximo; si aún sobra, se corta. Acorta el guion si lo notas.
- **Un render a la vez**: `ThreadPoolExecutor(max_workers=1)` en `app/main.py`.
- **Seguridad**: pon `APP_PASSWORD` en `.env` antes de exponerlo en tu dominio (y usa HTTPS con Nginx).
- **Derechos de autor**: clips de series pueden activar Content ID en las plataformas.

## Siguientes pasos sugeridos

- Despliegue: Nginx + HTTPS + servicio systemd (ver la guía `PROYECTO_VideoStudio.md`).
- Música de fondo con volumen bajo.
- Varias plantillas de personaje o fondo.
- Lip-sync del personaje (Wav2Lip / LivePortrait).
