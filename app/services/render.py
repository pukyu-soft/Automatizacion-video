import subprocess
from pathlib import Path
from ..config import CHARACTER_CLIP, FONTS_DIR, W, H, TOP_H, MID_H, BOT_H


def render(video_in, audio_in, ass_file, duration, out_path, mode="fill", on_progress=None):
    """mode='fill': recorta para llenar el recuadro central. mode='fit': video completo, sin recortar."""
    ass_file = Path(ass_file)
    scale_mode = "increase" if mode == "fill" else "decrease"
    crop = f",crop={W}:{MID_H}" if mode == "fill" else ""
    # Ruta con barras normales y ":" escapado (necesario en Windows: D\\:/carpeta)
    fdir = FONTS_DIR.as_posix().replace(":", "\\:")
    fonts = f":fontsdir='{fdir}'" if any(FONTS_DIR.glob("*.[ot]tf")) else ""

    if CHARACTER_CLIP.exists():
        char_in = ["-stream_loop", "-1", "-i", str(CHARACTER_CLIP)]
    else:  # marcador de posición si aún no pones tu clip
        char_in = ["-f", "lavfi", "-i", f"color=c=0x1b1033:s={W}x{BOT_H}:r=30"]

    fc = (
        f"[0:v]fps=30,split=2[a][b];"
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=30:5,eq=brightness=-0.3[bg];"
        f"[b]scale={W}:{MID_H}:force_original_aspect_ratio={scale_mode}{crop}[mid];"
        f"[1:v]fps=30,scale={W}:{BOT_H}:force_original_aspect_ratio=increase,crop={W}:{BOT_H}[char];"
        f"[bg][mid]overlay=(W-w)/2:{TOP_H}+({MID_H}-h)/2[t1];"
        f"[t1][char]overlay=0:{TOP_H + MID_H}[t2];"
        f"[t2]ass={ass_file.name}{fonts}[v]"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-i", str(video_in), *char_in, "-i", str(audio_in),
           "-filter_complex", fc, "-map", "[v]", "-map", "2:a",
           "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path)]

    p = subprocess.Popen(cmd, cwd=ass_file.parent, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    tail = []
    for line in p.stdout:
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
