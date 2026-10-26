import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from platetrail.etl.cache import RawCache
from platetrail.etl.loaders.overpass import BoundaryNotFound, OverpassLoader, build_query, parse_response
from platetrail.region import Region, Town

TESTVILLE = Region("testville", "Testville", "US-NJ", (Town("Testville", "Testville", 1),))

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


def test_default_query_text_is_unchanged():
    # Raw responses are cached by query text; the region config must not change it for NJ.
    assert build_query("Edison") == (
        '[out:json][timeout:90];\n'
        'area["ISO3166-2"="US-NJ"]["admin_level"="4"]->.nj;\n'
        'rel(area.nj)["boundary"="administrative"]["admin_level"="8"]["name"="Edison"]->.boundary;\n'
        '.boundary out tags;\n'
        '.boundary map_to_area->.town;\n'
        'nwr(area.town)["man_made"="surveillance"]["surveillance:type"~"^alpr$",i];\n'
        'out center tags;'
    )


def test_query_uses_region_parent_and_admin_level():
    q = build_query("Springfield", "US-IL", 7)
    assert '["ISO3166-2"="US-IL"]' in q
    assert '["admin_level"="7"]["name"="Springfield"]' in q


def _loader(tmp_path, handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OverpassLoader(RawCache(tmp_path), region=TESTVILLE, client=client, backoff_s=0, **kw)


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


def test_bbox_town_is_queried_by_box_without_boundary(tmp_path):
    region = Region("boxville", "Boxville", "US-PA",
                    (Town("Boxville", bbox=(-75.2, 39.9, -75.1, 40.0)), Town("Testville", "Testville", 1)))
    queries = []
    no_boundary = {"elements": [e for e in FIXTURE["elements"] if e["type"] != "relation"]}

    def handler(request):
        q = parse_qs(request.content.decode())["data"][0]
        queries.append(q)
        return httpx.Response(200, json=no_boundary if "39.9" in q else FIXTURE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    loader = OverpassLoader(RawCache(tmp_path), region=region, client=client, backoff_s=0)
    records = loader.load()
    assert len(queries) == 2
    assert 'nwr(39.9,-75.2,40.0,-75.1)["man_made"="surveillance"]' in queries[0]
    assert "boundary" not in queries[0]
    assert {r.town for r in records} == {"Boxville", "Testville"}
    assert sum(r.town == "Boxville" for r in records) == 5
