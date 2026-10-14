import json, subprocess


def probe(path: str) -> dict:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json",
                                   "-show_streams", "-show_format", str(path)])
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    return {
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "duration": float(data["format"]["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
    }
