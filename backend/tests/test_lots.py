import pytest
import shapely
from shapely.geometry import LineString, Polygon

from platetrail.roads.lots import OsmFeature, build_area_query, build_query, classify, facings_for, parse_features
from platetrail.roads.snap import EdgeIndex, snap_camera
from test_snap import X0, Y0, cam, toy_graph  # toy E-W road (0,0)-(200,0) etc., UTM 18N


@pytest.fixture(scope="module")
def index():
    return EdgeIndex(toy_graph())


def feature(index, osm_id, kind, geom_local, tags=None):
    geom = shapely.transform(geom_local, lambda x, y: (x + X0, y + Y0), interleaved=False)
    return OsmFeature(osm_id, kind, tags or {}, shapely.transform(geom, index.to_wgs.transform, interleaved=False), geom)


def square(x, y, half):
    return Polygon([(x - half, y - half), (x + half, y - half), (x + half, y + half), (x - half, y + half)])


def run(index, cams, features, alt=None):
    results = [snap_camera(index, c) for c in cams]
    return classify(results, features, index, alt)


def test_dropped_camera_inside_retail_becomes_lot(index):
    c = cam(100, 300, [0], cid=1)  # 300 m from any road
    retail = feature(index, "way/1", "retail", square(100, 300, 120), {"name": "Mall"})
    cls = run(index, [c], [retail])
    assert list(cls.lots) == [1]
    a = cls.lots[1]
    assert a.reason == "dropped" and a.lot.osm_id == "way/1" and a.lot.name == "Mall"


def test_dropped_camera_without_polygon_stays_unresolved(index):
    cls = run(index, [cam(100, 300, [0], cid=1)], [])
    assert not cls.lots and [c.camera_id for c in cls.unresolved_dropped] == [1]


def test_perpendicular_camera_on_parallel_driveway_becomes_lot(index):
    c = cam(100, 8, [0], cid=2)  # 8 m north of the E-W road, facing north (away from road)
    drive = feature(index, "way/9", "service", LineString([(100, 2), (100, 80)]))
    lot = feature(index, "way/10", "parking", square(100, 60, 25))
    cls = run(index, [c], [drive, lot])
    a = cls.lots[2]
    assert a.reason == "driveway"
    assert a.watched_way.osm_id == "way/9"
    assert a.lot.osm_id == "way/10"  # crossed by the driveway
    assert a.facings == ["into_lot"]


def test_camera_facing_the_road_is_toward_road(index):
    c = cam(100, 8, [180], cid=2)
    drive = feature(index, "way/9", "service", LineString([(100, 2), (100, 80)]))
    cls = run(index, [c], [drive])
    assert cls.lots[2].facings == ["toward_road"]
    assert cls.lots[2].lot is None


def test_driveway_must_be_parallel_and_close(index):
    c = cam(100, 8, [0], cid=2)
    far = feature(index, "way/9", "service", LineString([(115, 2), (115, 80)]))  # 15 m away
    crossing = feature(index, "way/8", "service", LineString([(50, 10), (150, 10)]))  # perpendicular
    cls = run(index, [c], [far, crossing])
    assert not cls.lots
    assert 2 in cls.snap_ambiguous  # still perpendicular to its road


def test_moderately_angled_camera_is_not_flagged(index):
    cls = run(index, [cam(100, 8, [125], cid=3)], [])  # 35 deg off the E-W axis
    assert not cls.lots and not cls.snap_ambiguous


def test_alt_facings_for_ambiguous_camera(index):
    c = cam(100, 8, [0], cid=2)
    drive = feature(index, "way/9", "service", LineString([(100, 2), (100, 80)]))
    cls = run(index, [c], [drive], alt={2: [180.0]})
    assert cls.lots[2].facings == ["into_lot"] and cls.lots[2].alt_facings == ["toward_road"]


def test_lot_preference_containing_then_kind(index):
    c = cam(100, 300, [0], cid=1)
    containing_parking = feature(index, "way/1", "parking", square(100, 300, 20))
    nearby_retail = feature(index, "way/2", "retail", square(100, 380, 30))
    assert run(index, [c], [containing_parking, nearby_retail]).lots[1].lot.osm_id == "way/1"
    containing_retail = feature(index, "way/3", "retail", square(100, 300, 200))
    assert run(index, [c], [containing_parking, containing_retail]).lots[1].lot.osm_id == "way/3"


def test_facings_for():
    assert facings_for([0, 180], outward=180) == ["into_lot", "toward_road"]
    assert facings_for(None, 0) is None


def test_queries():
    q = build_query([(40.5, -74.4)])
    assert 'way(around:60,40.5000000,-74.4000000)["highway"="service"]' in q
    assert "is_in" not in q
    a = build_area_query([(40.5, -74.4), (40.6, -74.3)])
    assert "(40.48000,-74.42000,40.62000,-74.28000)" in a


def test_parse_features_handles_ways_relations_and_skips_open_areas(index):
    sq = [(-74.40, 40.50), (-74.39, 40.50), (-74.39, 40.51), (-74.40, 40.51), (-74.40, 40.50)]
    g = lambda pts: [{"lon": x, "lat": y} for x, y in pts]  # noqa: E731
    resp = {"elements": [
        {"type": "way", "id": 1, "tags": {"highway": "service"}, "geometry": g(sq[:2])},
        {"type": "way", "id": 2, "tags": {"amenity": "parking"}, "geometry": g(sq)},
        {"type": "way", "id": 3, "tags": {"landuse": "retail"}, "geometry": g(sq[:3])},  # not closed
        {"type": "relation", "id": 4, "tags": {"landuse": "industrial", "name": "Park"},
         "members": [{"type": "way", "role": "outer", "geometry": g(sq[:3])},
                     {"type": "way", "role": "outer", "geometry": g(sq[2:])}]},
        {"type": "way", "id": 5, "tags": {"building": "yes"}, "geometry": g(sq)},
    ]}
    feats = {f.osm_id: f for f in parse_features(resp, index.to_proj)}
    assert set(feats) == {"way/1", "way/2", "relation/4"}
    assert feats["way/1"].kind == "service" and feats["way/2"].kind == "parking"
    assert feats["relation/4"].kind == "industrial" and feats["relation/4"].geom_wgs.area > 0
