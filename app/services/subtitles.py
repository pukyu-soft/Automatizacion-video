"""Genera un .ass con título y una única línea de subtítulos karaoke abajo."""
from ..config import FONT_NAME, W, H, TOP_H

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Titulo,{font},84,{title_colour},{title_colour},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{title_outline},{title_shadow},5,60,60,0,1
Style: Karaoke,{font},66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,5,50,50,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

POS_TITLE = (W // 2, TOP_H // 2)
POS_KARAOKE = (W // 2, H - 120)


def _t(sec: float) -> str:
    cs = max(0, round(sec * 100))
    return f"{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"


def _clean(s: str) -> str:
    return s.replace("{", "(").replace("}", ")").replace("\\", "").strip()


def _ev(start, end, style, pos, text):
    return f"Dialogue: 0,{_t(start)},{_t(end)},{style},,0,0,0,,{{\\an5\\pos({pos[0]},{pos[1]})}}{text}"


def build_ass(title: str, words: list, duration: float, out_path: str, max_words: int = 4,
              style: str = "clasico", font_name: str = FONT_NAME,
              title_color: str = "verde", title_style: str = "clasico"):
    if style not in {"clasico", "compacto", "alto_contraste"}:
        raise ValueError(f"Estilo de subtítulos desconocido: {style}")
    colors = {
        "verde": "&H0000FF00", "amarillo": "&H0000FFFF", "blanco": "&H00FFFFFF",
        "cian": "&H00FFFF00", "rosa": "&H00FF66FF",
    }
    title_styles = {"clasico": ("5", "0"), "contorno": ("8", "0"), "sombra": ("3", "5")}
    if title_color not in colors or title_style not in title_styles:
        raise ValueError("Color o estilo del título no válido.")
    font = font_name.replace(",", "")
    title_outline, title_shadow = title_styles[title_style]
    header = HEADER.format(
        w=W, h=H, font=font,
        title_colour=colors[title_color],
        title_outline=title_outline,
        title_shadow=title_shadow,
    )
    if style == "compacto":
        header = header.replace("66,", "56,")
        max_words = min(max_words, 3)
    elif style == "alto_contraste":
        header = header.replace("&H00FFFFFF", "&H0000FFFF")
    lines = [_ev(0, duration, "Titulo", POS_TITLE, "{\\fad(400,0)}" + _clean(title))]
    for i in range(0, len(words), max_words):
        g = words[i:i + max_words]
        for j, w in enumerate(g):               # una línea por palabra activa (amarillo)
            end = g[j + 1]["start"] if j + 1 < len(g) else w["end"]
            parts = [("{\\c&H00FFFF&}" + _clean(x["word"]).upper() + "{\\r}") if k == j
                     else _clean(x["word"]).upper() for k, x in enumerate(g)]
            lines.append(_ev(w["start"], max(end, w["start"] + 0.05), "Karaoke", POS_KARAOKE, " ".join(parts)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
