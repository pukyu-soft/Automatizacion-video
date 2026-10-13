"""Almacén mínimo de trabajos: un JSON por job en storage/jobs/ (escritura atómica)."""
import json, os, re, threading, time, uuid
from .config import JOBS

_lock = threading.Lock()
_ID = re.compile(r"^[0-9a-f]{32}$")


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
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)


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
