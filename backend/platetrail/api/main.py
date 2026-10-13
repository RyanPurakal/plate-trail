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

from platetrail.api.queries import (
    get_population,
    get_run,
    list_populations,
    list_runs,
    population_unicity_rows,
)
from platetrail.api.schemas import PopulationRequestBody, SimulateRequest
from platetrail.config import get_settings
from platetrail.db import apply_migrations, get_engine
from platetrail.etl.export_geojson import cameras_feature_collection
from platetrail.jobs import job_status, submit_population, submit_simulation
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


@app.post("/jobs/population", status_code=202)
def submit_population_job(body: PopulationRequestBody) -> dict:
    """Queue a population run (many drivers, one configuration); poll GET /jobs/{id} for population_id."""
    return submit_population(body.model_dump(mode="json"))


@app.get("/populations")
def populations() -> list[dict]:
    return list_populations(get_engine())


@app.get("/populations/{population_id}")
def population_detail(population_id: int) -> dict:
    pop = get_population(get_engine(), population_id)
    if pop is None:
        raise HTTPException(status_code=404, detail=f"population {population_id} not found")
    return pop


@app.get("/populations/{population_id}/unicity")
def population_unicity(population_id: int, resolution_min: int = 60, p: str = "1,2,3,4,6,8", size: str | None = None,
                       samples: int = 5) -> dict:
    """Unicity curve: share of drivers singled out by p (camera, time-bin) points. `size` subsamples the crowd."""
    try:
        ps = [int(x) for x in p.split(",") if x]
        sizes = [int(x) for x in size.split(",")] if size else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail="p and size are comma-separated integers") from e
    if not 1 <= resolution_min <= 24 * 60 or not ps or min(ps) < 1 or max(ps) > 20 or not 1 <= samples <= 50:
        raise HTTPException(status_code=422, detail="resolution_min 1-1440, p 1-20, samples 1-50")
    result = population_unicity_rows(get_engine(), population_id, ps, resolution_min, sizes, samples)
    if result is None:
        raise HTTPException(status_code=404, detail=f"population {population_id} not found")
    return result


@app.get("/runs")
def runs(limit: int = 100) -> list[dict]:
    return list_runs(get_engine(), min(max(limit, 1), 500))


@app.get("/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    run = get_run(get_engine(), run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return run
