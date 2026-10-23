import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from platetrail import geocode as geocode_mod
from platetrail.api.main import app
from platetrail.area import parse_bbox
from platetrail.geocode import GeocodeError, Geocoder, explore_bbox, normalize_query, parse_results

RESPONSE = [
    {"display_name": "Edison, Middlesex County, New Jersey, United States", "addresstype": "town",
     "lat": "40.5187", "lon": "-74.4121", "boundingbox": ["40.4800", "40.6000", "-74.4600", "-74.3300"]},
    {"display_name": "1 Main Street, Somewhere", "addresstype": "building",
     "lat": "40.5000", "lon": "-74.4000", "boundingbox": ["40.4999", "40.5001", "-74.4001", "-74.3999"]},
    {"display_name": "Bad row", "lat": "x", "lon": "y"},
]


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def geocoder(calls: list, clock: FakeClock, status: int = 200) -> Geocoder:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=RESPONSE) if status == 200 else httpx.Response(status)

    return Geocoder(httpx.Client(transport=httpx.MockTransport(handler)), url="http://nominatim.test/search",
                    clock=clock, sleep=clock.sleep)


def test_normalize_query():
    assert normalize_query("  Edison,   NJ ") == "Edison, NJ"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(GeocodeError):
            normalize_query(bad)


def test_explore_bbox_clamps_span_and_is_valid_for_area():
    town = explore_bbox(40.5, -74.4, ["40.48", "40.60", "-74.46", "-74.33"])
    assert town == [-74.46, 40.48, -74.33, 40.6]
    house = explore_bbox(40.5, -74.4, ["40.4999", "40.5001", "-74.4001", "-74.3999"])
    assert house == [-74.42, 40.48, -74.38, 40.52]
    county = explore_bbox(40.0, -74.0, ["39.0", "41.0", "-75.0", "-73.0"])
    assert county[2] - county[0] == pytest.approx(0.48) and county[3] - county[1] == pytest.approx(0.48)
    missing = explore_bbox(40.5, -74.4, None)
    assert missing == [-74.42, 40.48, -74.38, 40.52]
    for box in (town, house, county, missing):
        parse_bbox(",".join(map(str, box)))  # accepted by GET /area


def test_parse_results_skips_bad_rows():
    results = parse_results(RESPONSE)
    assert [r["kind"] for r in results] == ["town", "building"]
    assert results[0]["name"].startswith("Edison") and results[0]["lat"] == 40.5187


def test_search_sends_user_agent_and_caches_by_normalized_text():
    calls, clock = [], FakeClock()
    g = geocoder(calls, clock)
    first = g.search("Edison NJ")
    assert g.search("  edison   nj ") == first
    assert len(calls) == 1
    assert calls[0].url.params["q"] == "Edison NJ" and calls[0].url.params["format"] == "jsonv2"
    assert calls[0].headers["user-agent"].startswith("PlateTrail/")


def test_search_waits_between_requests_and_cache_expires():
    calls, clock = [], FakeClock()
    g = geocoder(calls, clock)
    g.search("Edison")
    clock.t += 0.25
    g.search("New Brunswick")
    assert clock.slept == [pytest.approx(0.75)]
    clock.t += geocode_mod.CACHE_TTL_S + 1
    g.search("Edison")
    assert len(calls) == 3


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(geocode_mod, "CACHE_SIZE", 2)
    calls, clock = [], FakeClock()
    g = geocoder(calls, clock)
    for q in ("a", "b", "c"):
        g.search(q)
    assert list(g._cache) == ["b", "c"]


def test_httpx_request_log_for_nominatim_is_dropped(caplog):
    logger = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        logger.info("HTTP Request: GET https://nominatim.openstreetmap.org/search?q=1+Main+St")
        logger.info("HTTP Request: GET https://overpass-api.de/api/interpreter")
    assert [r.getMessage() for r in caplog.records] == ["HTTP Request: GET https://overpass-api.de/api/interpreter"]


def test_geocode_endpoint(monkeypatch):
    calls, clock = [], FakeClock()
    monkeypatch.setattr(geocode_mod, "_geocoder", geocoder(calls, clock))
    client = TestClient(app)
    r = client.post("/geocode", json={"q": "Edison"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2 and "Nominatim" in body["attribution"]
    assert client.post("/geocode", json={"q": "   "}).status_code == 422
    assert client.post("/geocode", json={"q": ""}).status_code == 422


def test_geocode_endpoint_busy(monkeypatch):
    calls, clock = [], FakeClock()
    monkeypatch.setattr(geocode_mod, "_geocoder", geocoder(calls, clock, status=429))
    r = TestClient(app).post("/geocode", json={"q": "Edison"})
    assert r.status_code == 503 and "busy" in r.json()["detail"]
