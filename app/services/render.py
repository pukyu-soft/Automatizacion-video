import subprocess
from pathlib import Path
from ..config import CHARACTER_CLIP, FONTS_DIR, MUSIC_DIR, CHARACTERS_DIR, UPLOADS, W, H, TOP_H, MID_H, BOT_H
from .probe import probe


def render(video_in, audio_in, ass_file, duration, out_path, mode="fill", on_progress=None,
           preview=False, character=None, character_path=None, music=None, source_duration=None, cancelled=None,
           video_volume=20, narration_volume=100):
    """mode='fill': recorta para llenar el recuadro central. mode='fit': video completo, sin recortar."""
    ass_file = Path(ass_file)
    scale_mode = "increase" if mode == "fill" else "decrease"
    crop = f",crop={W}:{MID_H}" if mode == "fill" else ""
    source_info = probe(str(video_in))
    source_duration = source_duration or source_info["duration"]
    extra = max(0.0, duration - source_duration)
    pad = f"tpad=stop_mode=clone:stop_duration={extra:.3f}," if extra > 0.01 else ""
    if character_path:
        character_path = Path(character_path).resolve()
        if character_path.parent != UPLOADS.resolve() or not character_path.is_file():
            raise ValueError("No se encontró el video del personaje de este trabajo.")
    elif character:
        character_path = (CHARACTERS_DIR / Path(character).name).resolve()
        if character_path.parent != CHARACTERS_DIR.resolve() or not character_path.is_file():
            raise ValueError("Personaje no válido.")
    else:
        character_path = CHARACTER_CLIP
    # Ruta con barras normales y ":" escapado (necesario en Windows: D\\:/carpeta)
    fdir = FONTS_DIR.as_posix().replace(":", "\\:")
    fonts = f":fontsdir='{fdir}'" if any(FONTS_DIR.glob("*.[ot]tf")) else ""

    if character_path.exists():
        char_in = ["-stream_loop", "-1", "-i", str(character_path)]
    else:  # marcador de posición si aún no pones tu clip
        char_in = ["-f", "lavfi", "-i", f"color=c=0x1b1033:s={W}x{BOT_H}:r=30"]

    fc = (
        f"[0:v]{pad}fps=30,scale={W}:{MID_H}:force_original_aspect_ratio={scale_mode}{crop},"
        f"split=2[mid][bgsrc];"
        f"[bgsrc]scale=2160:1920:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},boxblur=30:5,"
        f"eq=brightness=-0.3[bg];"
        f"[1:v]fps=30,scale={W}:{BOT_H}:force_original_aspect_ratio=increase,crop={W}:{BOT_H}[char];"
        f"[bg][mid]overlay=(W-w)/2:{TOP_H}+({MID_H}-h)/2[t1];"
        f"[t1][char]overlay=0:{TOP_H + MID_H}[t2];"
        f"[t2]ass={ass_file.name}{fonts}{',scale=540:960' if preview else ''}[v]"
    )
    inputs = ["-i", str(video_in), *char_in, "-i", str(audio_in)]
    duration_filter = f"apad,atrim=duration={duration:.3f},asetpts=PTS-STARTPTS"
    audio_filters = [
        f"[2:a]volume={narration_volume / 100:.3f},{duration_filter}[narration]"
    ]
    audio_labels = ["[narration]"]
    if source_info["has_audio"]:
        audio_filters.append(
            f"[0:a:0]volume={video_volume / 100:.3f},{duration_filter}[source_audio]"
        )
        audio_labels.append("[source_audio]")
    if music:
        music_path = (MUSIC_DIR / Path(music).name).resolve()
        if music_path.parent != MUSIC_DIR.resolve() or not music_path.is_file():
            raise ValueError("Pista musical no válida.")
        inputs.extend(["-stream_loop", "-1", "-i", str(music_path)])
        music_index = 3
        audio_filters.append(
            f"[{music_index}:a]volume=0.120,{duration_filter}[music]"
        )
        audio_labels.append("[music]")
    fc += ";" + ";".join(audio_filters)
    fc += (
        ";" + "".join(audio_labels)
        + f"amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.95[a]"
    )

    preset, crf = ("ultrafast", "32") if preview else ("medium", "20")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", preset, "-crf", crf,
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path)]

    p = subprocess.Popen(cmd, cwd=ass_file.parent, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    tail = []
    for line in p.stdout:
        if cancelled and cancelled():
            p.terminate()
            p.wait()
            raise InterruptedError("Trabajo cancelado.")
        line = line.strip()
        if line.startswith("out_time_ms=") and on_progress:
            try:
                on_progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
            except ValueError:
                pass
        elif "=" not in line:
            tail = (tail + [line])[-15:]
    if p.wait() != 0:
        raise RuntimeError("FFmpeg falló:\n" + "\n".join(tail))
