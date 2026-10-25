from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from platetrail.api.main import app, get_runner
from platetrail.routearea import AreaNetworks, get_area_networks
from platetrail.routecheck import check_route
from platetrail.routehistory import route_history
from platetrail.sim.routing import NoRoute, Router
from test_trip import pair_on_main_st, toy_graph, xy

START, END = xy(100, 5), xy(900, 5)  # either side of the camera pair at 500 m on Main St


@pytest.fixture(scope="module")
def toy():
    cameras = pair_on_main_st()
    for cam in cameras.by_id.values():
        cam.lon, cam.lat = xy(500, 5)  # the engine needs sensor locations
    return SimpleNamespace(router=Router(toy_graph()), cameras=cameras)


@pytest.fixture(scope="module")
def legs(toy):
    return check_route(toy.router, toy.cameras, START, END)["legs"]


def test_longer_retention_reveals_more(legs):
    out = route_history(legs, START, END)
    week, month, year = out["periods"]
    assert [p["days"] for p in out["periods"]] == [7, 30, 365]
    assert week["trips"] == 10 and year["trips"] == 2 * 260  # 260 weekdays in the 365 days to a Sunday, both ways
    assert week["reads"] < month["reads"] < year["reads"]
    assert year["reads"] <= year["trips"]  # one sensor reads each direction; a few reads are missed
    assert year["sensors_read"] == 2
    assert year["regular"] and year["regular"][0]["weekdays"] == [0, 1, 2, 3, 4]
    assert "overnight" in year["places"]
    assert year["places"]["overnight"]["distance_m"] < 1000
    assert all(isinstance(s, str) for s in year["summary"]) and "a year" in year["summary"][0]
    assert out["stored"] is False


def test_same_inputs_same_answer(legs):
    assert route_history(legs, START, END) == route_history(legs, START, END)


def test_route_past_no_sensors_has_an_empty_history(toy):
    a, b = xy(1100, 5), xy(1900, 5)
    out = route_history(check_route(toy.router, toy.cameras, a, b)["legs"], a, b, retention_days=(30,))
    (p,) = out["periods"]
    assert p["reads"] == 0 and p["places"] == {} and "empty" in p["summary"][0]


def test_slider_stops_grow_and_read_naturally(legs):
    stops = (1, 3, 7, 14, 30, 60, 90, 180, 270, 365)
    out = route_history(legs, START, END, retention_days=stops)
    assert [p["days"] for p in out["periods"]] == list(stops)
    reads = [p["reads"] for p in out["periods"]]
    assert reads == sorted(reads)  # each period is the most recent part of the same year
    day = out["periods"][0]  # the reference end is a Sunday, so one weekday schedule day has no trips
    assert day["trips"] == 0 and "no trips" in day["summary"][0] and "1 day," in day["summary"][0]
    assert not any("1 days" in line for p in out["periods"] for line in p["summary"])


def test_weekend_only_schedule(legs):
    out = route_history(legs, START, END, weekdays=(5, 6), retention_days=(7,))
    assert out["periods"][0]["trips"] == 4
    assert out["schedule"]["weekdays"] == [5, 6]


@pytest.fixture
def client(toy):
    def no_roads(bbox):
        raise NoRoute("no mapped roads")

    app.dependency_overrides[get_runner] = lambda: toy
    app.dependency_overrides[get_area_networks] = lambda: AreaNetworks(fetch_graph=no_roads)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_endpoint_is_compute_only(client):
    from platetrail.cache import MemoryCache, reset_cache

    cache = MemoryCache()
    reset_cache(cache)
    try:
        resp = client.post("/route/history", json={"start": {"lon": START[0], "lat": START[1]},
                                                   "end": {"lon": END[0], "lat": END[1]},
                                                   "leave": "07:30", "return": "16:45", "retention_days": [30, 7]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stored"] is False and body["network"]["kind"] == "region"
        assert [p["days"] for p in body["periods"]] == [7, 30]
        assert body["schedule"]["leave"] == "07:30" and body["schedule"]["return"] == "16:45"
        assert not cache._d  # nothing cached
    finally:
        reset_cache(None)


@pytest.mark.parametrize("extra", [{"weekdays": []}, {"weekdays": [7]}, {"retention_days": [0]},
                                   {"retention_days": [400]}, {"retention_days": list(range(1, 14))},
                                   {"leave": "25:00"}])
def test_endpoint_validation(client, extra):
    payload = {"start": {"lon": START[0], "lat": START[1]}, "end": {"lon": END[0], "lat": END[1]}, **extra}
    assert client.post("/route/history", json=payload).status_code == 422
