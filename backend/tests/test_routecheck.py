from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from platetrail.api.main import app, get_runner
from platetrail.routearea import AreaNetworks, get_area_networks
from platetrail.routecheck import check_route
from platetrail.sim.routing import NoRoute, Router
from test_trip import pair_on_main_st, toy_graph, xy

START, END = xy(100, 5), xy(900, 5)  # both on Main St A-B, either side of the camera pair at 500 m


@pytest.fixture(scope="module")
def toy():
    return SimpleNamespace(router=Router(toy_graph()), cameras=pair_on_main_st())


@pytest.fixture
def client(toy):
    def no_roads(bbox):
        raise NoRoute("no mapped roads")

    app.dependency_overrides[get_runner] = lambda: toy
    app.dependency_overrides[get_area_networks] = lambda: AreaNetworks(fetch_graph=no_roads)
    # No `with`: the app's lifespan (database migrations) is not needed here.
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_each_direction_is_read_by_one_of_the_opposite_pair(toy):
    result = check_route(toy.router, toy.cameras, START, END)
    out, back = result["legs"]
    assert (out["direction"], back["direction"]) == ("outbound", "return")
    for leg in (out, back):
        assert leg["sensors_passed"] == 2 and leg["reads"] == 1
        assert len(leg["steps"]) == 2
    read_out = {s["camera_id"] for s in out["steps"] if s["read"]}
    read_back = {s["camera_id"] for s in back["steps"] if s["read"]}
    assert read_out and read_back and read_out != read_back
    missed = [s for s in out["steps"] if not s["read"]][0]
    assert missed["reason"] == "wrong_direction"
    assert result["stored"] is False


def test_step_offset_and_distance_along_route(toy):
    leg = check_route(toy.router, toy.cameras, START, END, both_ways=False)["legs"]
    assert len(leg) == 1
    step = leg[0]["steps"][0]
    assert step["distance_m"] == pytest.approx(400, abs=1)  # camera at 500 m, route starts at 100 m
    assert step["offset_s"] == pytest.approx(400 / (30 / 3.6), abs=0.5)
    assert step["road_name"] == "Main St" and step["event"] == "road"
    assert leg[0]["length_m"] == pytest.approx(800, abs=1)
    assert leg[0]["geometry"]["type"] == "LineString"


def test_route_past_no_sensors_has_an_empty_timeline(toy):
    leg = check_route(toy.router, toy.cameras, xy(1100, 5), xy(1900, 5), both_ways=False)["legs"][0]
    assert leg["sensors_passed"] == 0 and leg["steps"] == [] and leg["length_m"] > 0


def test_endpoint_is_compute_only(client):
    from platetrail.cache import MemoryCache, reset_cache

    cache = MemoryCache()
    reset_cache(cache)
    try:
        resp = client.post("/route/check", json={"start": {"lon": START[0], "lat": START[1]},
                                                 "end": {"lon": END[0], "lat": END[1]}})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stored"] is False and len(body["legs"]) == 2
        assert body["network"]["region"] == "nj_edison_new_brunswick"
        assert not any(k.startswith("route:") for k in cache._d)  # route cache bypassed
    finally:
        reset_cache(None)


def test_endpoint_explains_routes_outside_the_network(client):
    resp = client.post("/route/check", json={"start": {"lon": 2.35, "lat": 48.85}, "end": {"lon": 2.36, "lat": 48.86}})
    assert resp.status_code == 422
    assert "mapped road" in resp.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"start": {"lon": 0, "lat": 0}},
    {"start": {"lon": 200, "lat": 0}, "end": {"lon": 0, "lat": 0}},
])
def test_endpoint_validation(client, payload):
    assert client.post("/route/check", json=payload).status_code == 422
