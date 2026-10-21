from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from platetrail import area as area_mod
from platetrail.api.main import app
from platetrail.area import (
    AreaError,
    area_summary,
    build_area_query,
    file_area_features,
    load_area,
    parse_area_response,
    parse_bbox,
    snap_bbox,
)
from platetrail.etl.cache import RawCache
from platetrail.etl.loaders.overpass import OverpassClient
from platetrail.region import parse_region

RESPONSE = {
    "elements": [
        {"type": "node", "id": 2, "lat": 40.52, "lon": -74.41, "timestamp": "2025-03-01T10:00:00Z",
         "user": "someone", "tags": {"man_made": "surveillance", "surveillance:type": "ALPR", "direction": "90"}},
        {"type": "way", "id": 7, "center": {"lat": 40.53, "lon": -74.40}, "timestamp": "2026-01-15T08:00:00Z",
         "tags": {"man_made": "surveillance", "surveillance:type": "alpr"}},
        {"type": "way", "id": 8, "tags": {"man_made": "surveillance"}},  # no center: skipped
    ]
}


def overpass_client(calls: list, status: int = 200) -> OverpassClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=RESPONSE) if status == 200 else httpx.Response(status)

    return OverpassClient(httpx.Client(transport=httpx.MockTransport(handler)), urls=("http://overpass.test",),
                          attempts_per_url=1, backoff_s=0)


def test_parse_bbox_validates():
    assert parse_bbox("-74.5,40.4,-74.3,40.6") == (-74.5, 40.4, -74.3, 40.6)
    for bad in ("1,2,3", "a,b,c,d", "-74.3,40.4,-74.5,40.6", "-74.5,40.6,-74.3,40.4", "-200,0,-199,1",
                "-75,40,-74,40.2", "nan,0,1,1"):
        with pytest.raises(AreaError):
            parse_bbox(bad)


def test_snap_bbox_rounds_outward_and_keeps_grid_values():
    assert snap_bbox((-74.4123, 40.5011, -74.3001, 40.5999)) == (-74.42, 40.5, -74.3, 40.6)
    assert snap_bbox((-74.42, 40.5, -74.3, 40.6)) == (-74.42, 40.5, -74.3, 40.6)
    assert snap_bbox((-180, -90, 180, 90)) == (-180.0, -90.0, 180.0, 90.0)


def test_query_uses_bbox_order_south_west_north_east():
    q = build_area_query((-74.42, 40.5, -74.3, 40.6))
    assert "(40.50,-74.42,40.60,-74.30)" in q
    assert '["surveillance:type"~"^alpr$",i]' in q and "out center meta;" in q


def test_parse_area_response_keeps_public_fields_only():
    feats = parse_area_response(RESPONSE)
    assert [f["properties"]["id"] for f in feats] == ["osm:node/2", "osm:way/7"]
    node, way = feats
    assert node["geometry"]["coordinates"] == [-74.41, 40.52]
    assert node["properties"]["directions_deg"] == [90.0]
    assert way["geometry"]["coordinates"] == [-74.40, 40.53]
    assert way["properties"]["directions_deg"] is None
    assert "user" not in str(feats)  # editor names are not passed on


def test_summary_counts_and_freshness():
    bbox = (-74.42, 40.5, -74.3, 40.6)
    fetched = datetime(2026, 10, 21, tzinfo=timezone.utc)
    s = area_summary(bbox, parse_area_response(RESPONSE), fetched)
    assert s["sensor_count"] == 2 and s["with_direction"] == 1
    assert 100 < s["area_km2"] < 120  # about 10.1 km x 11.1 km
    src = s["sources"][0]
    assert src["id"] == "osm" and src["count"] == 2 and src["license"] == "ODbL"
    assert src["fetched_at"] == fetched.isoformat()
    assert src["latest_edit"] == "2026-01-15T08:00:00Z"
    empty = area_summary(bbox, [], None)
    assert empty["sensor_count"] == 0 and empty["sources"][0]["latest_edit"] is None


def test_load_area_caches_and_refetches_when_stale(tmp_path):
    cache, calls = RawCache(tmp_path), []
    client = overpass_client(calls)
    box = (-74.4123, 40.5011, -74.3001, 40.5999)
    first = load_area(box, cache=cache, client=client)
    assert first["bbox"] == [-74.42, 40.5, -74.3, 40.6]
    assert first["summary"]["sensor_count"] == 2 and len(calls) == 1
    # a nearby box on the same grid reuses the cached response
    load_area((-74.415, 40.502, -74.305, 40.598), cache=cache, client=client)
    assert len(calls) == 1
    later = datetime.now(timezone.utc) + area_mod.MAX_AGE + timedelta(hours=1)
    load_area(box, cache=cache, client=client, now=later)
    assert len(calls) == 2


def test_load_area_uses_stale_cache_when_overpass_fails(tmp_path):
    cache, calls = RawCache(tmp_path), []
    box = (-74.42, 40.5, -74.3, 40.6)
    load_area(box, cache=cache, client=overpass_client(calls))
    later = datetime.now(timezone.utc) + area_mod.MAX_AGE + timedelta(days=1)
    result = load_area(box, cache=cache, client=overpass_client(calls, status=504), now=later)
    assert result["summary"]["sensor_count"] == 2
    with pytest.raises(RuntimeError):
        load_area((0.0, 0.0, 0.1, 0.1), cache=cache, client=overpass_client(calls, status=504))


def test_area_endpoint(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(area_mod, "area_cache", lambda: RawCache(tmp_path))
    real_load = area_mod.load_area
    monkeypatch.setattr("platetrail.api.main.load_area", lambda box: real_load(box, client=overpass_client(calls)))
    client = TestClient(app)
    body = client.get("/area", params={"bbox": "-74.42,40.5,-74.3,40.6"}).json()
    assert body["summary"]["sensor_count"] == 2
    assert body["sensors"]["type"] == "FeatureCollection"
    assert client.get("/area", params={"bbox": "-74,40,-73,41"}).status_code == 422
    assert client.get("/area").status_code == 422

    def busy(box):
        raise RuntimeError("All Overpass endpoints failed")

    monkeypatch.setattr("platetrail.api.main.load_area", busy)
    assert client.get("/area", params={"bbox": "-74.42,40.5,-74.3,40.6"}).status_code == 503


def file_region(tmp_path, extra_sources=()):
    (tmp_path / "survey.csv").write_text(
        "id,lon,lat,direction,note\n"
        "a,-74.41,40.55,90,inside\n"
        "b,-74.00,40.55,,outside\n"
        ",-74.35,40.58,,inside no id\n"
    )
    return parse_region({
        "id": "t", "name": "T", "parent_iso3166_2": "US-NJ",
        "towns": [{"label": "T", "osm_name": "T", "osm_relation": 1}],
        "camera_sources": [{"type": "osm"}, {"type": "file", "path": "survey.csv", "source": "survey"},
                           *extra_sources],
    }, base_dir=tmp_path)


def test_file_area_features_filters_to_bbox_and_credits_source(tmp_path):
    region = file_region(tmp_path, [{"type": "file", "path": "missing.geojson", "source": "gone"}])
    feats, sources = file_area_features((-74.42, 40.5, -74.3, 40.6), region)
    assert [f["properties"]["id"] for f in feats] == ["survey:2", "survey:a"]
    a = feats[1]
    assert a["geometry"]["coordinates"] == [-74.41, 40.55]
    assert a["properties"]["source"] == "survey" and a["properties"]["directions_deg"] == [90.0]
    assert "note" not in a["properties"]  # extra columns are not passed on
    assert [s["id"] for s in sources] == ["survey"]  # the missing file is skipped
    assert sources[0]["updated_at"]


def test_load_area_includes_file_sensors(tmp_path):
    calls = []
    region = file_region(tmp_path)
    result = load_area((-74.42, 40.5, -74.3, 40.6), cache=RawCache(tmp_path / "cache"),
                       client=overpass_client(calls), region=region)
    summary = result["summary"]
    assert summary["sensor_count"] == 4 and summary["with_direction"] == 2
    osm, survey = summary["sources"]
    assert osm["id"] == "osm" and osm["count"] == 2 and osm["latest_edit"] == "2026-01-15T08:00:00Z"
    assert survey["id"] == "survey" and survey["count"] == 2 and survey["latest_edit"] is None
    assert survey["fetched_at"] is not None
    ids = [f["properties"]["id"] for f in result["sensors"]["features"]]
    assert ids == ["osm:node/2", "osm:way/7", "survey:2", "survey:a"]
