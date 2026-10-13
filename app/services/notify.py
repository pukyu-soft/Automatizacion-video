import os, requests
from ..config import env, PUBLIC_URL


def send_telegram(video_path: str, caption: str, job_id: str):
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    base = f"https://api.telegram.org/bot{token}"
    if os.path.getsize(video_path) <= 49 * 1024 * 1024:
        with open(video_path, "rb") as f:
            requests.post(f"{base}/sendVideo", data={"chat_id": chat, "caption": caption},
                          files={"video": f}, timeout=300)
    else:
        requests.post(f"{base}/sendMessage", data={
            "chat_id": chat, "text": f"{caption}\nListo: {PUBLIC_URL}/api/jobs/{job_id}/download"}, timeout=30)
