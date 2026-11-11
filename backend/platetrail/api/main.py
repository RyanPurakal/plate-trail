"""FastAPI application.

    GET  /health
    GET  /region           active study area: id, name, town labels, initial map view, dataset notes
    GET  /area             public fixed sensors and a summary for any bbox (no region file needed)
    POST /geocode          place search (Nominatim) -> boxes to explore; the text is never stored or logged
    POST /route/check      sensors one route passes and where reads would happen, on the study roads or a
                           network built around the route; compute-only, never stored
    POST /route/history    what a 1-day to 1-year read history of that route could suggest; compute-only
    GET  /cameras          camera GeoJSON (kind, directions, lot info; optional direction rays)
    POST /simulate         simulate one synthetic driver for N weeks and store the run (synchronous)
    POST /jobs/simulate    same, as a queued job; GET /jobs/{id} for progress and the run id
    GET  /runs             stored runs, newest first
    GET  /runs/{run_id}    one run: trips (GeoJSON), every camera pass, the noisy read log, outages

POST /simulate runs in the API process through the shared runner
(sim.service). POST /jobs/simulate runs on a Celery worker when Redis is
configured (platetrail.worker, platetrail.jobs), with progress and a run cache.

The check-up endpoints (/region, /area, /geocode, /route/*) work with no database;
the example study's endpoints answer 503 until one is reachable.
"""

import logging
from contextlib import asynccontextmanager

import httpx
import osmnx as ox
import requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from platetrail.api.queries import (
    get_population,
    get_run,
    list_populations,
    list_runs,
    population_policies,
    population_unicity_rows,
)
from platetrail.api.schemas import GeocodeBody, PopulationRequestBody, RouteCheckBody, RouteHistoryBody, SimulateRequest, YourWeekBody
from platetrail.area import AreaError, load_area, parse_bbox
from platetrail.config import get_settings
from platetrail.db import apply_migrations, get_engine
from platetrail.geocode import ATTRIBUTION, GeocodeError, get_geocoder
from platetrail.etl.export_geojson import cameras_feature_collection
from platetrail.jobs import job_status, submit_population, submit_simulation
from platetrail.region import get_region
from platetrail.routearea import AreaNetworks, get_area_networks
from platetrail.sim.routing import AnchorTooFar, NoRoute
from platetrail.sim.runner import SimulationRunner
from platetrail.sim.service import get_local_runner, get_study_runner

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        apply_migrations(get_engine())
    except OperationalError:
        logger.warning("No database reachable: the check-up works, the example study does not. "
                       "Start the database, then restart the API.")
    yield


app = FastAPI(title="Plate Trail API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
def database_unavailable(request, exc: OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={
        "detail": "The example study's database isn't available. Exploring areas and checking routes still work."})


def get_runner() -> SimulationRunner:
    """The process-wide runner; loads the road graph and cameras on first use (several seconds)."""
    return get_local_runner()


def get_route_runner() -> SimulationRunner | None:
    """The study network for route checks, or None if its data isn't there (routes then use a network around them)."""
    return get_study_runner()


def _check_density_scenario(body: SimulateRequest | PopulationRequestBody, runner: SimulationRunner | None = None):
    """422 now if the scenario's extra cameras can't be placed, instead of a failed run or job later.

    Placement is seeded by the request, so trying it here gives the same answer the run would.
    """
    if body.extra_cameras <= 0:
        return
    from platetrail.sim.scenarios import density_scenario

    runner = runner or get_runner()
    try:
        density_scenario(runner.router, runner.cameras, runner.towns, body.extra_cameras, body.seed,
                         body.scenario_town)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"extra_cameras: {e}; try fewer extra cameras") from e


@app.get("/health")
def health() -> dict:
    with get_engine().connect() as conn:
        postgis = conn.execute(text("SELECT postgis_lib_version()")).scalar_one()
    return {"status": "ok", "postgis": postgis}


@app.get("/region")
def region() -> dict:
    """The active region (PLATETRAIL_REGION); the frontend uses `map` for its initial view."""
    r = get_region()
    return {
        "id": r.id,
        "name": r.name,
        "towns": list(r.labels),
        "student_town": r.student_town,
        "scenario_town": r.scenario_town,
        "map": r.map.as_dict(),
        "notes": dict(r.notes),
    }


@app.get("/area")
def area(bbox: str) -> dict:
    """Sensors in `bbox` (west,south,east,north) from OpenStreetMap, snapped to a 0.01 deg grid and cached."""
    try:
        box = parse_bbox(bbox)
    except AreaError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        return load_area(box)
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=503, detail="map data source is busy; try again shortly") from e


@app.post("/geocode")
def geocode(body: GeocodeBody) -> dict:
    """Places matching the search text, each with a box sized for GET /area. Session-only: not stored or logged."""
    try:
        results = get_geocoder().search(body.q)
    except GeocodeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail="place search is busy; try again shortly") from e
    return {"results": results, "attribution": ATTRIBUTION}


def _checked_route(start, end, both_ways: bool, runner: SimulationRunner | None,
                   networks: AreaNetworks) -> tuple[dict, dict]:
    """(network, check_route result). Routes on the study region's roads use its network when it is loaded; others
    get a small network built around the route from public map data (held briefly in memory only)."""
    from platetrail.routecheck import check_route

    if runner is not None:
        r = get_region()
        try:
            result = check_route(runner.router, runner.cameras, start, end, both_ways)
            return {"kind": "region", "region": r.id, "name": r.name}, result
        except (AnchorTooFar, NoRoute):
            pass  # not on the study roads: check it on a network built around the route

    try:
        net = networks.for_route(start, end)
        result = check_route(net.router, net.cameras, start, end, both_ways)
    except AreaError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (AnchorTooFar, NoRoute) as e:
        raise HTTPException(status_code=422, detail="the start or end is more than 500 m from a mapped road, "
                            "or the two can't be joined by road") from e
    except (RuntimeError, httpx.HTTPError, requests.RequestException, ox._errors.ResponseStatusCodeError) as e:
        raise HTTPException(status_code=503, detail="map data is busy; try again shortly") from e
    network = {
        "kind": "area",
        "region": None,
        "name": "OpenStreetMap roads around this route",
        "bbox": list(net.bbox),
        "sensors_mapped": net.sensors_mapped,
        "sensors_on_roads": net.sensors_on_roads,
        "sources": net.sources,
    }
    return network, result


@app.post("/route/check")
def route_check(body: RouteCheckBody, runner: SimulationRunner | None = Depends(get_route_runner),
                networks: AreaNetworks = Depends(get_area_networks)) -> dict:
    """Sensors a route passes (both ways by default). Session-only: nothing about the route is stored or logged."""
    start, end = (body.start.lon, body.start.lat), (body.end.lon, body.end.lat)
    network, result = _checked_route(start, end, body.both_ways, runner, networks)
    return {"network": network, **result}


@app.post("/route/history")
def route_history(body: RouteHistoryBody, runner: SimulationRunner | None = Depends(get_route_runner),
                  networks: AreaNetworks = Depends(get_area_networks)) -> dict:
    """What a read history of one route, driven on a schedule and kept 1 to 365 days, could suggest.
    Session-only, like /route/check."""
    from platetrail.routehistory import route_history as history

    start, end = (body.start.lon, body.start.lat), (body.end.lon, body.end.lat)
    network, check = _checked_route(start, end, body.both_ways, runner, networks)
    mins = lambda s: int(s[:2]) * 60 + int(s[3:])  # noqa: E731
    result = history(check["legs"], start, end, tuple(body.weekdays), mins(body.leave), mins(body.return_),
                     tuple(body.retention_days))
    return {"network": network, **result}


@app.get("/cameras")
def cameras(rays: bool = False) -> dict:
    """All cameras as GeoJSON points; `rays=true` adds a 30 m LineString per direction."""
    fc = cameras_feature_collection(get_engine())
    if not rays:
        fc["features"] = [f for f in fc["features"] if f["properties"]["kind"] == "camera"]
    return fc


@app.post("/simulate", status_code=201)
def simulate(body: SimulateRequest, runner: SimulationRunner = Depends(get_runner)) -> dict:
    _check_density_scenario(body, runner)
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
    _check_density_scenario(body)
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
    _check_density_scenario(body)
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


@app.get("/populations/{population_id}/policies")
def population_policy_comparison(population_id: int) -> dict:
    """Inference accuracy and unicity under each policy (retention, rounding, aggregation, search windows)."""
    result = population_policies(get_engine(), population_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"population {population_id} not found")
    return result


@app.post("/yourweek")
def your_week(body: YourWeekBody, runner: SimulationRunner = Depends(get_runner)) -> dict:
    """Simulate the week a visitor describes. Session-only: nothing is stored, cached or logged."""
    from platetrail.yourweek import simulate_week

    try:
        return simulate_week(runner, body.to_input(), body.weeks)
    except (AnchorTooFar, NoRoute) as e:
        raise HTTPException(status_code=422, detail="that location is too far from the road network") from e


@app.get("/runs")
def runs(limit: int = 100) -> list[dict]:
    return list_runs(get_engine(), min(max(limit, 1), 500))


@app.get("/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    run = get_run(get_engine(), run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return run
