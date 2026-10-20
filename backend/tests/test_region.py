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
