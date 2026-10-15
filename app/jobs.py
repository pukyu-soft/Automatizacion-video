"""Almacén mínimo de trabajos: un JSON por job en storage/jobs/ (escritura atómica)."""
import json
import os
import re
import tempfile
import threading
import time
import uuid
from .config import JOBS

_lock = threading.Lock()
_ID = re.compile(r"^[0-9a-f]{32}$")
ACTIVE_STATUSES = {
    "queued", "transcribing", "analyzing", "tts", "fitting", "subtitles",
    "rendering", "preview", "cancelling",
}


def _file(job_id: str):
    if not _ID.match(job_id):
        raise KeyError(job_id)
    return JOBS / f"{job_id}.json"


def _read(job_id: str) -> dict:
    try:
        return json.loads(_file(job_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KeyError(job_id)


def _write(job: dict):
    f = _file(job["id"])
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=JOBS, prefix=f".{job['id']}.", suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(json.dumps(job, ensure_ascii=False))
            tmp_path = tmp.name
        for attempt in range(4):
            try:
                os.replace(tmp_path, f)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def create(**fields) -> dict:
    job = {"id": uuid.uuid4().hex, "status": "created", "progress": 0, "script": "",
           "error": "", "output": "", "created_at": time.time(), **fields}
    with _lock:
        _write(job)
    return job


def get(job_id: str) -> dict:
    with _lock:
        return _read(job_id)


def update(job_id: str, **fields) -> dict:
    with _lock:
        job = _read(job_id)
        job.update(fields)
        _write(job)
    return job


def delete_many(job_ids: list[str], before_delete=None) -> list[dict]:
    with _lock:
        selected = [_read(job_id) for job_id in job_ids]
        if any(job.get("status") in ACTIVE_STATUSES for job in selected):
            raise ValueError("No se pueden eliminar trabajos que siguen ejecutándose.")
        if before_delete:
            before_delete(selected)
        for job_id in job_ids:
            _file(job_id).unlink()
    return selected
