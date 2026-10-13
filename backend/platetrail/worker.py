"""Celery app and tasks: heavy simulation work runs here, off the API process.

    celery -A platetrail.worker worker --loglevel=info

With REDIS_URL set, Redis is the broker and result backend. Without it
(tests, CI, a laptop without Redis), tasks run eagerly in-process.
"""

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL")

celery_app = Celery("platetrail", broker=REDIS_URL or "memory://", backend=REDIS_URL or "cache+memory://")
celery_app.conf.update(
    task_always_eager=not REDIS_URL,
    task_track_started=True,
    worker_prefetch_multiplier=1,  # long tasks: don't hoard
    result_expires=7 * 86400,
)


@celery_app.task(bind=True, name="platetrail.simulate")
def simulate_task(self, payload: dict) -> dict:
    """payload: an api.schemas.SimulateRequest as JSON. Returns {"run_id": ...}."""
    from platetrail.api.schemas import SimulateRequest
    from platetrail.jobs import remember_run, run_cache_key
    from platetrail.sim.service import get_local_runner

    def progress(stage: str, done: int, total: int) -> None:
        if not celery_app.conf.task_always_eager:
            self.update_state(state="PROGRESS", meta={"stage": stage, "done": done, "total": total})

    request = SimulateRequest(**payload).to_request()
    run_id = get_local_runner().run(request, progress=progress)
    remember_run(run_cache_key(payload), run_id)
    return {"run_id": run_id}


@celery_app.task(bind=True, name="platetrail.population")
def population_task(self, payload: dict) -> dict:
    """payload: an api.schemas.PopulationRequestBody as JSON. Returns {"population_id": ...}."""
    from platetrail.api.schemas import PopulationRequestBody
    from platetrail.population import run_population
    from platetrail.sim.service import get_local_runner

    def progress(stage: str, done: int, total: int) -> None:
        if not celery_app.conf.task_always_eager and (done % 10 == 0 or done == total):
            self.update_state(state="PROGRESS", meta={"stage": stage, "done": done, "total": total})

    pid = run_population(get_local_runner(), PopulationRequestBody(**payload).to_request(), progress)
    return {"population_id": pid}
