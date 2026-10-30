from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from platetrail.api.main import app, get_route_runner
from platetrail.area import AreaError, build_area_query
from platetrail.etl.cache import RawCache
from platetrail.etl.loaders.overpass import OverpassClient
from platetrail.routearea import AreaNetworks, build_camera_set, fetch_sensors, get_area_networks, route_bbox
from platetrail.routecheck import check_route
from platetrail.sim.routing import NoRoute, Router
from test_trip import pair_on_main_st, toy_graph, xy

SHIFT = 1.0  # the "elsewhere" network sits one degree east of the study toy network


def shifted(p):
    return (p[0] + SHIFT, p[1])


def elsewhere_graph():
    G = toy_graph()
    for _, d in G.nodes(data=True):
        d["x"] += SHIFT
    return G


def sensor(id_, lonlat, directions):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(lonlat)},
            "properties": {"id": id_, "source": "osm", "directions_deg": directions,
                           "direction_raw": None, "last_edited": None}}


FEATURES = [
    sensor("osm:node/1", shifted(xy(500, 8)), [90.0]),  # beside Main St, mid A-B
    sensor("osm:node/2", shifted(xy(500, -300)), None),  # 300 m from any road: not on the network
]
SOURCES = [{"id": "osm", "name": "OpenStreetMap contributors", "fetched_at": "2026-10-22T00:00:00+00:00"}]


def networks(**kw):
    calls = []

    def fetch_graph(bbox):
        calls.append(bbox)
        return elsewhere_graph()

    nets = AreaNetworks(fetch_graph=fetch_graph, fetch_features=lambda bbox: (FEATURES, SOURCES), **kw)
    nets.calls = calls
    return nets


def test_route_bbox_pads_snaps_and_limits_size():
    w, s, e, n = route_bbox((-74.40, 40.50), (-74.38, 40.51))
    assert w <= -74.40 - 0.02 and e >= -74.38 + 0.02 and s <= 40.50 - 0.018 and n >= 40.51 + 0.018
    assert all(abs(v * 100 - round(v * 100)) < 1e-6 for v in (w, s, e, n))  # on the 0.01 deg grid
    with pytest.raises(AreaError):
        route_bbox((-74.4, 40.5), (-74.0, 40.5))


def test_camera_set_snaps_sensors_near_roads_only():
    router = Router(elsewhere_graph())
    cameras, on_roads = build_camera_set(router, FEATURES)
    assert on_roads == 1
    (cam,) = cameras.by_id.values()
    assert cam.label == "osm:node/1" and cam.directions_deg == [90.0]
    assert {ce.edge[:2] for ce in cam.edges} == {(1, 2), (2, 1)}  # both directions of Main St


def test_route_elsewhere_passes_the_snapped_sensor():
    net = networks().for_route(shifted(xy(100, 5)), shifted(xy(900, 5)))
    result = check_route(net.router, net.cameras, shifted(xy(100, 5)), shifted(xy(900, 5)))
    for leg in result["legs"]:
        assert leg["sensors_passed"] == 1 and leg["steps"][0]["label"] == "osm:node/1"
    assert sum(leg["reads"] for leg in result["legs"]) == 1  # one-way-facing: read one way only
    assert net.sensors_mapped == 2 and net.sensors_on_roads == 1


def test_networks_are_reused_in_memory_and_evicted():
    nets = networks(size=1)
    a, b = shifted(xy(100, 5)), shifted(xy(900, 5))
    first = nets.for_route(a, b)
    assert nets.for_route(b, a) is first and len(nets.calls) == 1  # same box both ways
    far = (a[0] + 0.2, a[1])
    nets.for_route(far, (far[0] + 0.001, far[1]))
    nets.for_route(a, b)
    assert len(nets.calls) == 3  # the first box was evicted by the second


def test_networks_expire():
    nets = networks(ttl_s=0)
    a, b = shifted(xy(100, 5)), shifted(xy(900, 5))
    nets.for_route(a, b)
    nets.for_route(a, b)
    assert len(nets.calls) == 2


RESPONSE = {"elements": [{"type": "node", "id": 5, "lat": 40.5, "lon": -74.4, "tags": {"direction": "90"}}]}
BBOX = (-74.42, 40.48, -74.38, 40.52)


def client_for(calls, status=200):
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=RESPONSE)
    return OverpassClient(httpx.Client(transport=httpx.MockTransport(handler)), urls=("http://overpass.test",),
                          attempts_per_url=1, backoff_s=0)


def test_fetch_sensors_never_writes_the_cache(tmp_path):
    cache, calls = RawCache(tmp_path / "areas"), []
    features, sources = fetch_sensors(BBOX, cache, client_for(calls))
    assert [f["properties"]["id"] for f in features] == ["osm:node/5"] and len(calls) == 1
    assert sources[0]["id"] == "osm" and sources[0]["fetched_at"]
    assert not (tmp_path / "areas").exists()


def test_fetch_sensors_reads_a_fresh_area_cache_entry(tmp_path):
    cache, calls = RawCache(tmp_path / "areas"), []
    cache.get_or_fetch(build_area_query(BBOX), lambda: RESPONSE)  # as GET /area would have stored it
    files = sorted(p.read_text() for p in (tmp_path / "areas").iterdir())
    features, _ = fetch_sensors(BBOX, cache, client_for(calls))
    assert len(features) == 1 and calls == []
    later = datetime.now(timezone.utc) + timedelta(days=8)  # stale: ask Overpass, fall back to the entry
    features, _ = fetch_sensors(BBOX, cache, client_for(calls, status=500), now=later)
    assert len(features) == 1 and len(calls) == 1
    assert sorted(p.read_text() for p in (tmp_path / "areas").iterdir()) == files  # untouched


@pytest.fixture
def client():
    nets = networks()
    app.dependency_overrides[get_route_runner] = lambda: SimpleNamespace(router=Router(toy_graph()),
                                                                   cameras=pair_on_main_st())
    app.dependency_overrides[get_area_networks] = lambda: nets
    yield TestClient(app), nets
    app.dependency_overrides.clear()


def post(c, a, b):
    return c.post("/route/check", json={"start": {"lon": a[0], "lat": a[1]}, "end": {"lon": b[0], "lat": b[1]}})


def test_endpoint_without_study_data_uses_a_network_around_the_route(client):
    c, nets = client
    app.dependency_overrides[get_route_runner] = lambda: None
    resp = post(c, shifted(xy(100, 5)), shifted(xy(900, 5)))
    assert resp.status_code == 200 and resp.json()["network"]["kind"] == "area"
    assert len(nets.calls) == 1


def test_endpoint_uses_study_roads_when_possible(client):
    c, nets = client
    resp = post(c, xy(100, 5), xy(900, 5))
    assert resp.status_code == 200 and resp.json()["network"]["kind"] == "region"
    assert nets.calls == []


def test_endpoint_builds_a_network_for_routes_elsewhere(client):
    c, nets = client
    resp = post(c, shifted(xy(100, 5)), shifted(xy(900, 5)))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    net = body["network"]
    assert net["kind"] == "area" and net["region"] is None
    assert net["sensors_mapped"] == 2 and net["sensors_on_roads"] == 1
    assert net["sources"][0]["id"] == "osm"
    assert body["stored"] is False and [leg["sensors_passed"] for leg in body["legs"]] == [1, 1]


def test_endpoint_errors_for_routes_elsewhere(client):
    c, nets = client
    a = shifted(xy(100, 5))
    assert post(c, a, (a[0] + 0.5, a[1])).status_code == 422  # too long

    def no_roads(bbox):
        raise NoRoute("no mapped roads")
    nets.fetch_graph = no_roads
    resp = post(c, (2.35, 48.85), (2.36, 48.86))
    assert resp.status_code == 422 and "mapped road" in resp.json()["detail"]

    def busy(bbox):
        raise httpx.ConnectError("down")
    nets.fetch_graph = busy
    assert post(c, (2.35, 48.85), (2.36, 48.86)).status_code == 503

