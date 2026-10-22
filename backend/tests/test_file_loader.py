import json

import pytest

from platetrail.etl.loaders.file import FileCameraLoader, SensorFileError
from platetrail.etl.run_etl import default_loaders
from platetrail.etl.loaders.overpass import OverpassLoader
from platetrail.region import CameraSource, Region, RegionConfigError, Town, load_region, parse_region

ONE_TOWN = Region("solo", "Solo", "US-PA", (Town("Solo", "Solo", 1),))
TWO_TOWNS = Region("pair", "Pair", "US-PA", (Town("A", "A", 1), Town("B", "B", 2)))


def _geojson(tmp_path, features):
    path = tmp_path / "sensors.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


def _point(lon, lat, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def test_geojson_points_become_records(tmp_path):
    path = _geojson(tmp_path, [
        _point(-74.4, 40.5, id="s1", direction="NE", note="pole"),
        _point(-74.41, 40.51, direction="90;270"),
        _point(-74.42, 40.52),
    ])
    recs = FileCameraLoader(path, region=ONE_TOWN).load()
    assert [r.source_id for r in recs] == ["s1", "1", "2"]
    assert recs[0].directions_deg == [45.0] and recs[0].direction_key == "direction"
    assert recs[0].tags == {"note": "pole"}
    assert recs[1].directions_deg == [90.0, 270.0]
    assert recs[2].directions_deg is None and recs[2].direction_key is None
    assert all(r.town == "Solo" and r.source == "file" for r in recs)
    assert (recs[0].lon, recs[0].lat) == (-74.4, 40.5)


def test_csv_rows_become_records(tmp_path):
    path = tmp_path / "sensors.csv"
    path.write_text("id,lon,lat,town,direction,kind\na,-74.4,40.5,B,180,fixed\nb,-74.3,40.6,A,,\n")
    recs = FileCameraLoader(path, region=TWO_TOWNS, source="survey").load()
    assert [(r.source_id, r.town, r.directions_deg) for r in recs] == [("a", "B", [180.0]), ("b", "A", None)]
    assert recs[0].tags == {"kind": "fixed"} and recs[1].tags == {}
    assert recs[0].key == "survey:a"


@pytest.mark.parametrize("features", [
    [_point(-74.4, 40.5)],  # no town in a two-town region
    [_point(-74.4, 40.5, town="Elsewhere")],
    [_point(-200, 40.5, town="A")],
    [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}}],
])
def test_bad_rows_fail_loudly(tmp_path, features):
    with pytest.raises(SensorFileError):
        FileCameraLoader(_geojson(tmp_path, features), region=TWO_TOWNS).load()


def test_csv_without_coordinates_fails(tmp_path):
    path = tmp_path / "sensors.csv"
    path.write_text("id,x,y\na,1,2\n")
    with pytest.raises(SensorFileError):
        FileCameraLoader(path, region=ONE_TOWN).load()


def test_missing_file_fails(tmp_path):
    with pytest.raises(SensorFileError):
        FileCameraLoader(tmp_path / "nope.csv", region=ONE_TOWN).load()


def test_default_region_uses_osm_only():
    region = load_region()
    assert region.camera_sources == (CameraSource("osm"),)
    loaders = default_loaders(region)
    assert len(loaders) == 1 and isinstance(loaders[0], OverpassLoader)


def test_region_file_sources_resolve_relative_to_region(tmp_path):
    (tmp_path / "sensors.csv").write_text("lon,lat\n-74.4,40.5\n")
    path = tmp_path / "solo.json"
    path.write_text(json.dumps({
        "id": "solo", "name": "Solo", "parent_iso3166_2": "US-PA",
        "towns": [{"label": "Solo", "osm_name": "Solo", "osm_relation": 1}],
        "camera_sources": [{"type": "file", "path": "sensors.csv", "source": "survey"}, {"type": "osm"}],
    }))
    region = load_region(path)
    assert region.camera_sources[0] == CameraSource("file", tmp_path / "sensors.csv", "survey")
    loaders = default_loaders(region)
    assert [l.source for l in loaders] == ["survey", "osm"]
    assert [r.key for r in loaders[0].load()] == ["survey:0"]


@pytest.mark.parametrize("sources", [
    [],
    [{"type": "vendor"}],
    [{"type": "file"}],
    [{"type": "osm", "source": "other"}],
    [{"type": "file", "path": "a.csv"}, {"type": "file", "path": "b.csv"}],  # both named "file"
])
def test_invalid_camera_sources_are_rejected(sources):
    with pytest.raises(RegionConfigError):
        parse_region({
            "id": "x", "name": "x", "parent_iso3166_2": "US-NJ",
            "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1}],
            "camera_sources": sources,
        })
