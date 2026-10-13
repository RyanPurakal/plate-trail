"""Submit simulation jobs and read their status; cache identical runs.

A job runs platetrail.worker.simulate_task: on a Celery worker when Redis is
configured, otherwise immediately in-process. Identical requests on the same
camera data are served from the run cache (key: the canonical request JSON
plus the camera load time), because the simulation is deterministic.
"""

import hashlib
import json
import uuid

from sqlalchemy import text

from platetrail.cache import MISSING, get_cache
from platetrail.db import get_engine

_EAGER_JOBS: dict[str, dict] = {}  # job records when running without Redis


def run_cache_key(payload: dict) -> str:
    with get_engine().connect() as conn:
        snapshot = conn.execute(text("SELECT max(loaded_at) FROM cameras")).scalar_one()
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return "run:" + hashlib.sha256(f"{canonical}|{snapshot}".encode()).hexdigest()


def remember_run(key: str, run_id: int) -> None:
    get_cache().set(key, run_id, ttl_s=30 * 86400)


def _cached_run(key: str) -> int | None:
    run_id = get_cache().get(key)
    if run_id is MISSING:
        return None
    with get_engine().connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM runs WHERE id = :i"), {"i": run_id}).first()
    return run_id if exists else None


def _submit(task, payload: dict, cached_result: dict | None = None) -> dict:
    from platetrail.worker import celery_app

    if cached_result is not None:
        job_id = f"cached-{uuid.uuid4()}"
        _EAGER_JOBS[job_id] = {"job_id": job_id, "state": "SUCCESS", **cached_result, "cached": True}
        return _EAGER_JOBS[job_id]
    if celery_app.conf.task_always_eager:
        job_id = f"local-{uuid.uuid4()}"
        try:
            result = task.apply(args=[payload]).get()
            _EAGER_JOBS[job_id] = {"job_id": job_id, "state": "SUCCESS", **result, "cached": False}
        except Exception as e:  # noqa: BLE001 - reported to the client
            _EAGER_JOBS[job_id] = {"job_id": job_id, "state": "FAILURE", "error": str(e)}
        return _EAGER_JOBS[job_id]
    return {"job_id": task.delay(payload).id, "state": "PENDING"}


def submit_simulation(payload: dict) -> dict:
    from platetrail.worker import simulate_task

    cached = _cached_run(run_cache_key(payload))
    return _submit(simulate_task, payload, {"run_id": cached} if cached is not None else None)


def submit_population(payload: dict) -> dict:
    from platetrail.worker import population_task

    return _submit(population_task, payload)


def job_status(job_id: str) -> dict | None:
    if job_id in _EAGER_JOBS:
        return _EAGER_JOBS[job_id]
    if job_id.startswith(("local-", "cached-")):
        return None
    from platetrail.worker import celery_app

    r = celery_app.AsyncResult(job_id)
    out: dict = {"job_id": job_id, "state": r.state}
    if r.state == "PROGRESS" and isinstance(r.info, dict):
        out["progress"] = r.info
    elif r.state == "SUCCESS":
        out.update(r.result)
    elif r.state == "FAILURE":
        out["error"] = str(r.result)
    return out
