import pytest
from fastapi.testclient import TestClient

from platetrail.api.main import app, get_runner

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
    app.dependency_overrides[get_runner] = lambda: toy
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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


def test_simulate_then_fetch_run(client):
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
    {"match": {"tolerance_deg": 200}}, {"match": {"facing": "sideways"}}, {"noise": {"p_miss": 1.5}}, {"seed": -1},
])
def test_simulate_rejects_bad_requests(client, payload):
    assert client.post("/simulate", json=payload).status_code == 422


def test_unknown_run_is_404(client):
    assert client.get("/runs/999999").status_code == 404
