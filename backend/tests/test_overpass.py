import json
from pathlib import Path

import httpx
import pytest

from platetrail.etl.cache import RawCache
from platetrail.etl.loaders.overpass import BoundaryNotFound, OverpassLoader, build_query, parse_response

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "overpass_town.json").read_text())


def test_parse_response_normalizes_records():
    recs = {r.source_id: r for r in parse_response("Testville", FIXTURE)}
    assert set(recs) == {"node/101", "node/102", "node/103", "node/104", "way/105"}
    assert recs["node/101"].directions_deg == [90.0]
    assert recs["node/102"].directions_deg == [321.0]  # direction wins
    assert recs["node/102"].direction_key == "direction"
    assert recs["node/102"].alt_directions_deg == [137.0]  # disagreeing camera:direction kept
    assert recs["node/101"].alt_directions_deg is None
    assert recs["node/101"].direction_key == "direction"
    assert recs["node/103"].direction_key is None
    assert recs["node/101"].manufacturer == "Flock Safety"
    assert recs["node/103"].manufacturer is None
    assert recs["node/103"].directions_deg is None and not recs["node/103"].has_direction
    assert recs["node/104"].directions_deg == [176.0, 270.0]
    assert recs["way/105"].lat == 40.54  # way uses its center
    assert recs["way/105"].direction_raw == "forward" and not recs["way/105"].has_direction
    assert all(r.town == "Testville" and r.source == "osm" for r in recs.values())


def test_missing_boundary_fails_loudly():
    no_boundary = {"elements": [e for e in FIXTURE["elements"] if e["type"] != "relation"]}
    with pytest.raises(BoundaryNotFound):
        parse_response("Nowhere", no_boundary)


def test_query_uses_requested_tags():
    q = build_query("Edison")
    assert '["name"="Edison"]' in q
    assert '["man_made"="surveillance"]' in q
    assert '["surveillance:type"~"^alpr$",i]' in q


def _loader(tmp_path, handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OverpassLoader(RawCache(tmp_path), towns={"Testville": "Testville"}, client=client, backoff_s=0, **kw)


def test_cache_prevents_second_request(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=FIXTURE)

    loader = _loader(tmp_path, handler)
    first = loader.load()
    second = loader.load()
    assert len(calls) == 1
    assert [r.key for r in first] == [r.key for r in second]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_refresh_bypasses_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=FIXTURE)

    loader = _loader(tmp_path, handler)
    loader.load()
    loader.load(refresh=True)
    assert len(calls) == 2


def test_retries_then_falls_back_to_mirror(tmp_path):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "primary.test":
            return httpx.Response(504)
        return httpx.Response(200, json=FIXTURE)

    loader = _loader(
        tmp_path, handler, urls=("https://primary.test/api", "https://mirror.test/api"), attempts_per_url=2
    )
    assert len(loader.load()) == 5
    assert hosts == ["primary.test", "primary.test", "mirror.test"]


def test_non_retryable_error_raises_immediately(tmp_path):
    def handler(request):
        return httpx.Response(400, text="bad query")

    loader = _loader(tmp_path, handler, urls=("https://primary.test/api", "https://mirror.test/api"))
    with pytest.raises(httpx.HTTPStatusError):
        loader.load()
    assert not list(tmp_path.glob("*.json"))  # failures are not cached
