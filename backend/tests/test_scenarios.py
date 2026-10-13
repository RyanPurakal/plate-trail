import pytest
from shapely.geometry import box

from platetrail.geo import WGS84, angle_diff
from platetrail.sim.routing import Router
from platetrail.sim.scenarios import synthetic_cameras
from test_trip import lot_graph, xy

# lot_graph: public tertiary roads 0-1, 1-2, 2-3, 3-4 (3,000 m in total) and service roads 1-10-3.


@pytest.fixture(scope="module")
def router():
    return Router(lot_graph())


def test_places_n_cameras_on_public_roads_with_spacing(router):
    sims, recs = synthetic_cameras(router, 5, seed=1, min_spacing_m=200)
    assert len(sims) == len(recs) == 5
    assert [c.camera_id for c in sims] == [-1, -2, -3, -4, -5]
    assert [c.label for c in sims] == [f"scenario/1/{i}" for i in range(1, 6)]
    for c in sims:
        for ce in c.edges:
            assert router.G[ce.edge[0]][ce.edge[1]][ce.edge[2]]["highway"] == "tertiary"  # never service roads
    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            assert WGS84.inv(a.lon, a.lat, b.lon, b.lat)[2] >= 199  # spacing (geodesic vs projected, small slack)


def test_two_way_road_gets_both_directions_and_one_facing(router):
    sims, _ = synthetic_cameras(router, 3, seed=2, min_spacing_m=200)
    for c in sims:
        assert len(c.edges) == 2  # every public road in lot_graph is two-way
        b1, b2 = (ce.bearing_deg for ce in c.edges)
        assert angle_diff(b1, b2) > 170
        assert min(angle_diff(c.directions_deg[0], b) for b in (b1, b2)) < 1e-6  # faces one travel direction
        assert c.edges[0].fraction_along + c.edges[1].fraction_along == pytest.approx(1.0)


def test_deterministic_per_seed(router):
    a = synthetic_cameras(router, 4, seed=3, min_spacing_m=200)[1]
    b = synthetic_cameras(router, 4, seed=3, min_spacing_m=200)[1]
    c = synthetic_cameras(router, 4, seed=4, min_spacing_m=200)[1]
    assert a == b and a != c


def test_within_polygon_and_existing_cameras_respected(router):
    west_lon, west_lat = xy(-500, -100)
    east_lon, east_lat = xy(10, 100)
    west = box(west_lon, west_lat, east_lon, east_lat)  # covers only road 0-1 (x from -500 to 0)
    _, recs = synthetic_cameras(router, 2, seed=5, within=west, min_spacing_m=100)
    assert all(r.lon <= xy(0, 0)[0] + 1e-9 for r in recs)
    existing = [xy(-250, 0)]
    _, recs2 = synthetic_cameras(router, 1, seed=5, within=west, existing=existing, min_spacing_m=150)
    assert WGS84.inv(recs2[0].lon, recs2[0].lat, *existing[0])[2] >= 149


def test_impossible_spacing_raises(router):
    with pytest.raises(ValueError):
        synthetic_cameras(router, 50, seed=1, min_spacing_m=500)


def test_zero_cameras_is_a_no_op(router):
    assert synthetic_cameras(router, 0, seed=1) == ([], [])
