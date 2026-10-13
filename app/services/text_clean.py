import re

_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0000FE0F\U0000200D]+",
    flags=re.UNICODE,
)


def clean_script(text: str) -> str:
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_#>`~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()
