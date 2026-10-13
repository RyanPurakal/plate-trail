import pytest
from fastapi.testclient import TestClient

from platetrail.api.main import app, get_runner
from platetrail.sim.service import set_runner

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def client(engine):
    from platetrail.routines.places import PlacePool
    from platetrail.sim.routing import Router
    from platetrail.sim.runner import LocalRunner
    from platetrail.sim.trip import CameraSet
    from test_runner_db import PLAZA, FixedGenerator
    from test_trip import lot_camera, pair_on_main_st, toy_graph

    cams = CameraSet(list(pair_on_main_st().by_id.values()) + [lot_camera(["into_lot"])])
    toy = LocalRunner(Router(toy_graph()), cams, PlacePool([PLAZA], []), engine, generator=FixedGenerator())
    toy.make_generator = lambda request: FixedGenerator()  # populations ask the runner for a generator
    app.dependency_overrides[get_runner] = lambda: toy
    set_runner(toy)  # jobs use the shared runner directly
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    set_runner(None)


def test_health_reports_postgis(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok" and resp.json()["postgis"]


def test_cameras_geojson(client, engine):
    from platetrail.etl.loaders.base import CameraRecord
    from platetrail.etl.run_etl import run as run_etl

    class Stub:
        source = "osm"

        def load(self, refresh=False):
            return [CameraRecord("osm", "node/1", 40.5, -74.4, "Edison", [90.0], "90", "direction",
                                 tags={"manufacturer": "Flock Safety"}),
                    CameraRecord("osm", "node/2", 40.6, -74.4, "Edison", None, None)]

    run_etl(loaders=[Stub()], engine=engine)
    fc = client.get("/cameras").json()
    assert fc["type"] == "FeatureCollection"
    props = {f["properties"]["osm_id"]: f["properties"] for f in fc["features"]}
    assert set(props) == {"node/1", "node/2"}
    assert props["node/1"]["directions_deg"] == [90.0] and props["node/1"]["camera_kind"] == "public_road"
    assert props["node/2"]["has_direction"] is False
    with_rays = client.get("/cameras", params={"rays": True}).json()
    assert sum(f["properties"]["kind"] == "direction_ray" for f in with_rays["features"]) == 1


def _load_toy_cameras(engine):
    """Camera rows whose source ids match the toy runner's camera labels, so reads can be located."""
    from platetrail.etl.loaders.base import CameraRecord
    from platetrail.etl.run_etl import run as run_etl
    from test_trip import xy

    class Stub:
        source = "osm"

        def load(self, refresh=False):
            out = []
            for label, (e, n) in {"east-facing": (500, 3), "west-facing": (500, -3), "lot5": (600, 5)}.items():
                lon, lat = xy(e, n)
                out.append(CameraRecord("osm", label, lat, lon, "Edison", [90.0], "90", "direction"))
            return out

    run_etl(loaders=[Stub()], engine=engine)


def test_simulate_then_fetch_run(client, engine):
    _load_toy_cameras(engine)
    resp = client.post("/simulate", json={"weeks": 1, "seed": 7, "zero_noise": True})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    run_id = body["run_id"]
    assert body["plate"].startswith("ZZ ")
    assert body["summary"]["reads"] == body["summary"]["captured"] > 0

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["run"]["id"] == run_id and detail["run"]["plate_state"] == "ZZ"
    assert detail["run"]["match_config"]["facing"] == "rear_plate"
    trips = detail["trips"]["features"]
    assert len(trips) == 10 and all(t["geometry"]["type"] == "LineString" for t in trips)
    assert {"depart", "arrive", "purpose", "length_m"} <= set(trips[0]["properties"])
    pass_ids = {p["id"] for p in detail["passes"]}
    assert all(r["pass_id"] in pass_ids for r in detail["reads"])
    assert all(r["plate_state"] == "ZZ" and r["time"] == r["true_time"] for r in detail["reads"])
    assert len(detail["reads"]) == sum(p["captured"] for p in detail["passes"])

    inf = detail["inference"]
    assert "HDBSCAN" in inf["method"] and inf["reads_used"] == len(detail["reads"])
    assert inf["home"] is not None and inf["home"]["confidence"] in ("high", "medium", "low")
    assert isinstance(inf["conclusions"], list) and inf["conclusions"]
    guess = detail["naive_guess"]
    assert "naive baseline" in guess["method"] and "not the inference engine" in guess["method"]
    assert guess["days_used"] == 5 and guess["possible"]
    for kind in ("home", "work"):
        assert {"camera_label", "lon", "lat", "error_m", "support_days", "is_top_camera", "truth"} <= set(guess[kind])
    assert guess["home"]["error_m"] >= 0
    assert guess["work"]["error_m"] is None and guess["work"]["truth"] is None  # fixed routine has no work anchor

    listed = client.get("/runs").json()
    assert listed[0]["id"] == run_id and listed[0]["plate_state"] == "ZZ"


def test_simulate_passes_match_and_noise_settings(client):
    resp = client.post("/simulate", json={"seed": 2, "match": {"facing": "oncoming", "lot_entrance": "all"},
                                          "noise": {"p_miss": 1.0}})
    assert resp.status_code == 201
    detail = client.get(f"/runs/{resp.json()['run_id']}").json()
    assert detail["run"]["match_config"]["facing"] == "oncoming"
    assert detail["run"]["noise_config"]["p_miss"] == 1.0
    assert detail["reads"] == []
    assert all(p["noise_outcome"] in ("missed", "downtime") for p in detail["passes"] if p["captured"])


@pytest.mark.parametrize("payload", [
    {"weeks": 0}, {"weeks": 9}, {"template": "astronaut"}, {"start": "2026-10-13"},
    {"generator": "nhts", "template": "commuter"}, {"generator": "template", "template": "worker"},
    {"generator": "census"}, {"extra_cameras": 201},
    {"match": {"tolerance_deg": 200}}, {"match": {"facing": "sideways"}}, {"noise": {"p_miss": 1.5}}, {"seed": -1},
])
def test_simulate_rejects_bad_requests(client, payload):
    assert client.post("/simulate", json=payload).status_code == 422


def test_unknown_run_is_404(client):
    assert client.get("/runs/999999").status_code == 404


def test_runs_marked_stale_after_camera_reload(client, engine):
    from sqlalchemy import text

    run_id = client.post("/simulate", json={"seed": 31}).json()["run_id"]
    assert client.get(f"/runs/{run_id}").json()["run"]["stale"] is False
    with engine.begin() as conn:
        conn.execute(text("UPDATE cameras SET loaded_at = now() + interval '1 second'"))
    assert client.get(f"/runs/{run_id}").json()["run"]["stale"] is True
    assert next(r for r in client.get("/runs").json() if r["id"] == run_id)["stale"] is True


def test_simulation_job_runs_and_identical_request_is_cached(client):
    body = {"seed": 77, "weeks": 1}
    first = client.post("/jobs/simulate", json=body)
    assert first.status_code == 202
    job = first.json()
    assert job["state"] == "SUCCESS" and job["run_id"] > 0 and job["cached"] is False
    status = client.get(f"/jobs/{job['job_id']}").json()
    assert status["run_id"] == job["run_id"]
    again = client.post("/jobs/simulate", json=body).json()
    assert again["cached"] is True and again["run_id"] == job["run_id"]
    different = client.post("/jobs/simulate", json={"seed": 78, "weeks": 1}).json()
    assert different["run_id"] != job["run_id"]


def test_unknown_job_is_404(client):
    assert client.get("/jobs/local-does-not-exist").status_code == 404


def test_job_validation_matches_simulate(client):
    assert client.post("/jobs/simulate", json={"weeks": 0}).status_code == 422


def test_population_job_and_unicity_endpoint(client):
    job = client.post("/jobs/population", json={"drivers": 5, "weeks": 1, "seed": 1}).json()
    assert job["state"] == "SUCCESS", job
    pid = job["population_id"]
    assert any(p["id"] == pid for p in client.get("/populations").json())
    assert client.get(f"/populations/{pid}").json()["drivers"] == 5
    u = client.get(f"/populations/{pid}/unicity", params={"p": "1,2", "resolution_min": 60}).json()
    assert [r["p"] for r in u["rows"]] == [1, 2] and all(0 <= r["unique_share"] <= 1 for r in u["rows"])
    sized = client.get(f"/populations/{pid}/unicity", params={"p": "1", "size": "2,5"}).json()
    assert [r["size"] for r in sized["rows"]] == [2, 5]
    assert client.get(f"/populations/{pid}/unicity", params={"p": "0"}).status_code == 422
    assert client.get("/populations/999999").status_code == 404
    pol = client.get(f"/populations/{pid}/policies").json()
    names = [r["policy"] for r in pol["rows"]]
    assert names[0] == "baseline" and "aggregate_only" in names and "round_hour" in names
    assert client.get("/populations/999999/policies").status_code == 404


def test_your_week_is_simulated_and_not_stored(client, engine):
    from sqlalchemy import text

    from platetrail.cache import MemoryCache, reset_cache
    from test_trip import xy

    cache = MemoryCache()
    reset_cache(cache)
    with engine.connect() as conn:
        runs_before = conn.execute(text("SELECT count(*) FROM runs")).scalar_one()
    home, work = xy(100, 5), xy(1900, 5)
    resp = client.post("/yourweek", json={"home": {"lon": home[0], "lat": home[1]},
                                           "work": {"lon": work[0], "lat": work[1]},
                                           "errands_per_week": 0, "weekend_outings": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stored"] is False and body["run"]["generator"] == "your_week"
    assert len(body["trips"]["features"]) == 10  # 5 workdays x 2
    assert body["run"]["anchors"]["home"]["key"] == "you/home"
    assert "inference" in body and "naive_guess" in body
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM runs")).scalar_one() == runs_before
    assert not any(k.startswith("route:") for k in cache._d)  # route cache bypassed
    reset_cache(None)


@pytest.mark.parametrize("payload", [
    {"home": {"lon": 0, "lat": 0}},
    {"home": {"lon": -74.4, "lat": 40.5}, "leave_home": "25:00"},
    {"home": {"lon": -74.4, "lat": 40.5}, "workdays": [7]},
    {"home": {"lon": -74.4, "lat": 40.5}, "weeks": 9},
])
def test_your_week_validation(client, payload):
    assert client.post("/yourweek", json=payload).status_code == 422
