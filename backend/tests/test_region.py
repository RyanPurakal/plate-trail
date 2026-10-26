import json

import pytest

from platetrail.region import DEFAULT_REGION, RegionConfigError, load_region, parse_region
from platetrail.roads.graph import graph_path


def test_default_region_is_the_nj_study():
    r = load_region()
    assert r.id == DEFAULT_REGION
    assert r.parent_iso3166_2 == "US-NJ"
    assert r.relations == {"Edison": 171019, "New Brunswick": 170536}
    assert r.buffer_m == 2000.0


def test_env_var_selects_region_file(tmp_path, monkeypatch):
    path = tmp_path / "elsewhere.json"
    path.write_text(json.dumps({
        "id": "elsewhere", "name": "Elsewhere", "parent_iso3166_2": "US-PA",
        "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1}],
    }))
    monkeypatch.setenv("PLATETRAIL_REGION", str(path))
    r = load_region()
    assert r.id == "elsewhere"
    assert r.towns[0].admin_level == 8
    assert r.buffer_m == 2000.0


def test_unknown_region_fails():
    with pytest.raises(RegionConfigError):
        load_region("no_such_region")


@pytest.mark.parametrize("bad", [
    {"id": "x", "name": "x", "parent_iso3166_2": "US-NJ", "towns": []},
    {"id": "x", "name": "x", "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1}]},
    {"id": "x", "name": "x", "parent_iso3166_2": "US-NJ",
     "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1}, {"label": "A", "osm_name": "B", "osm_relation": 2}]},
    {"id": "x", "name": "x", "parent_iso3166_2": "US-NJ", "buffer_m": -1,
     "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1}]},
    {"id": "x", "name": "x", "parent_iso3166_2": "US-NJ", "towns": [{"label": "A", "osm_name": "A", "osm_relation": "R1"}]},
])
def test_invalid_configs_are_rejected(bad):
    with pytest.raises(RegionConfigError):
        parse_region(bad)


def test_graph_cache_path_keeps_default_name(tmp_path):
    assert graph_path(tmp_path, DEFAULT_REGION).name == "study_area_drive_service.graphml"
    assert graph_path(tmp_path, "elsewhere").name == "study_area_drive_service_elsewhere.graphml"


def test_default_region_names_student_and_scenario_towns():
    r = load_region()
    assert r.student_town == "New Brunswick"
    assert r.student_home_share == 0.7
    assert r.scenario_town == "Edison"
    assert r.other_towns("New Brunswick") == ("Edison",)


def test_optional_town_roles_default_sensibly():
    r = parse_region({"id": "x", "name": "x", "parent_iso3166_2": "US-PA",
                      "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1},
                                {"label": "B", "osm_name": "B", "osm_relation": 2}]})
    assert r.student_town is None
    assert r.scenario_town == "A"


@pytest.mark.parametrize("extra", [{"student_town": "Z"}, {"scenario_town": "Z"}, {"student_home_share": 1.5}])
def test_town_roles_must_be_valid(extra):
    with pytest.raises(RegionConfigError):
        parse_region({"id": "x", "name": "x", "parent_iso3166_2": "US-PA",
                      "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1}], **extra})


BASE = {"id": "x", "name": "x", "parent_iso3166_2": "US-PA",
        "towns": [{"label": "A", "osm_name": "A", "osm_relation": 1}]}


def test_default_region_map_view():
    m = load_region().map
    assert m.center == (-74.39, 40.53)
    assert m.zoom == 11.6
    assert m.bounds is None


def test_map_view_is_optional_and_parsed():
    assert parse_region(BASE).map.as_dict() == {"center": None, "zoom": None, "bounds": None}
    r = parse_region({**BASE, "map": {"bounds": [-75.2, 39.9, -75.1, 40.0]}})
    assert r.map.bounds == (-75.2, 39.9, -75.1, 40.0)
    assert r.map.center is None


@pytest.mark.parametrize("bad", [
    {"center": [-74.4, 40.5]},  # zoom missing
    {"center": [-74.4], "zoom": 12},
    {"center": [-200, 40.5], "zoom": 12},
    {"center": [-74.4, 40.5], "zoom": 30},
    {"bounds": [-74.3, 40.4, -74.5, 40.6]},  # west > east
    {"bounds": [-74.5, 40.4, -74.3]},
    {"bounds": "nope"},
])
def test_invalid_map_view_is_rejected(bad):
    with pytest.raises(RegionConfigError):
        parse_region({**BASE, "map": bad})


def test_notes_are_optional_and_parsed():
    assert parse_region(BASE).notes == ()
    r = parse_region({**BASE, "notes": {"read_volume": "  A published count.  "}})
    assert dict(r.notes) == {"read_volume": "A published count."}


@pytest.mark.parametrize("bad", [
    {"something_else": "text"},
    {"read_volume": ""},
    {"read_volume": 12},
    ["read_volume"],
])
def test_invalid_notes_are_rejected(bad):
    with pytest.raises(RegionConfigError):
        parse_region({**BASE, "notes": bad})


def _box_region(**town):
    return parse_region({"id": "b", "name": "B", "parent_iso3166_2": "US-PA",
                         "towns": [{"label": "Downtown", **town},
                                   {"label": "A", "osm_name": "A", "osm_relation": 7}]})


def test_town_can_be_a_plain_bbox():
    r = _box_region(bbox=[-75.2, 39.9, -75.1, 40.0])
    assert r.towns[0].bbox == (-75.2, 39.9, -75.1, 40.0)
    assert r.towns[0].osm_relation is None
    assert r.bboxes == {"Downtown": (-75.2, 39.9, -75.1, 40.0)}
    assert r.relations == {"A": 7}
    assert r.labels == ("Downtown", "A")


@pytest.mark.parametrize("town", [
    {"bbox": [-75.1, 39.9, -75.2, 40.0]},  # west > east
    {"bbox": [-75.2, 39.9, -75.1]},
    {"bbox": [-75.2, 39.9, -74.5, 40.0]},  # over the size limit
    {"bbox": [-75.2, 39.9, -75.1, 95.0]},
    {"bbox": [-75.2, 39.9, -75.1, 40.0], "osm_relation": 1, "osm_name": "X"},
    {},  # neither a box nor a relation
])
def test_invalid_bbox_towns_are_rejected(town):
    with pytest.raises(RegionConfigError):
        _box_region(**town)


def test_town_polygons_use_boxes_without_network():
    from platetrail.roads.graph import town_polygons

    r = parse_region({"id": "b", "name": "B", "parent_iso3166_2": "US-PA",
                      "towns": [{"label": "Downtown", "bbox": [-75.2, 39.9, -75.1, 40.0]}]})
    shapes = town_polygons(r)
    assert list(shapes) == ["Downtown"]
    assert shapes["Downtown"].bounds == (-75.2, 39.9, -75.1, 40.0)


def test_places_query_covers_bbox_towns(monkeypatch):
    from platetrail.routines import places

    r = _box_region(bbox=[-75.2, 39.9, -75.1, 40.0])
    monkeypatch.setattr(places, "get_region", lambda: r)
    q = places.build_query()
    assert "area(id:3600000007)->.a;" in q
    assert 'nwr(area.a)["shop"];' in q
    assert 'nwr(39.9,-75.2,40.0,-75.1)["shop"];' in q  # south,west,north,east
    assert q.endswith(");\nout center tags;")
