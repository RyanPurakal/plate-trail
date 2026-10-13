"""FastAPI application.

    GET  /health
    GET  /cameras          camera GeoJSON (kind, directions, lot info; optional direction rays)
    POST /simulate         simulate one synthetic driver for N weeks and store the run (synchronous)
    POST /jobs/simulate    same, as a queued job; GET /jobs/{id} for progress and the run id
    GET  /runs             stored runs, newest first
    GET  /runs/{run_id}    one run: trips (GeoJSON), every camera pass, the noisy read log, outages

POST /simulate runs in the API process through the shared runner
(sim.service). POST /jobs/simulate runs on a Celery worker when Redis is
configured (platetrail.worker, platetrail.jobs), with progress and a run cache.
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from platetrail.api.queries import get_run, list_runs
from platetrail.api.schemas import SimulateRequest
from platetrail.config import get_settings
from platetrail.db import apply_migrations, get_engine
from platetrail.etl.export_geojson import cameras_feature_collection
from platetrail.jobs import job_status, submit_simulation
from platetrail.sim.routing import AnchorTooFar, NoRoute
from platetrail.sim.runner import SimulationRunner
from platetrail.sim.service import get_local_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_migrations(get_engine())
    yield


app = FastAPI(title="Plate Trail API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_runner() -> SimulationRunner:
    """The process-wide runner; loads the road graph and cameras on first use (several seconds)."""
    return get_local_runner()


@app.get("/health")
def health() -> dict:
    with get_engine().connect() as conn:
        postgis = conn.execute(text("SELECT postgis_lib_version()")).scalar_one()
    return {"status": "ok", "postgis": postgis}


@app.get("/cameras")
def cameras(rays: bool = False) -> dict:
    """All cameras as GeoJSON points; `rays=true` adds a 30 m LineString per direction."""
    fc = cameras_feature_collection(get_engine())
    if not rays:
        fc["features"] = [f for f in fc["features"] if f["properties"]["kind"] == "camera"]
    return fc


@app.post("/simulate", status_code=201)
def simulate(body: SimulateRequest, runner: SimulationRunner = Depends(get_runner)) -> dict:
    try:
        run_id = runner.run(body.to_request())
    except (AnchorTooFar, NoRoute) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    run = get_run(get_engine(), run_id)
    return {"run_id": run_id, "summary": run["run"]["summary"], "plate": f"{run['run']['plate_state']} "
            f"{run['run']['plate']}"}


@app.post("/jobs/simulate", status_code=202)
def submit_simulate_job(body: SimulateRequest) -> dict:
    """Queue a simulation (Celery worker if Redis is configured, else in-process); poll GET /jobs/{id}."""
    return submit_simulation(body.model_dump(mode="json"))


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    status = job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return status


@app.get("/runs")
def runs(limit: int = 100) -> list[dict]:
    return list_runs(get_engine(), min(max(limit, 1), 500))


@app.get("/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    run = get_run(get_engine(), run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return run
