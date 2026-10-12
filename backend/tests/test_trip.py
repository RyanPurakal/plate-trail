from datetime import datetime, timedelta

import networkx as nx
import pytest
from shapely.geometry import box

from platetrail.sim.matcher import MatchConfig, Reason
from platetrail.sim.routing import Router
from platetrail.sim.trip import CameraEdge, CameraSet, SimCamera, match_route, simulate_trip

LON0, LAT0 = -74.40, 40.50
M_LON = 1 / 84_650  # degrees of longitude per metre at 40.5 N (approx.)
M_LAT = 1 / 111_000
DEPART = datetime(2026, 10, 12, 8, 0, 0)


def xy(east_m, north_m):
    return (LON0 + east_m * M_LON, LAT0 + north_m * M_LAT)


def add(G, u, v, length, kph, name, two_way=True):
    tt = length / (kph / 3.6)
    G.add_edge(u, v, key=0, length=length, travel_time=tt, name=name)
    if two_way:
        G.add_edge(v, u, key=0, length=length, travel_time=tt, name=name)


def toy_graph():
    """A-B-C main street at 30 km/h, plus a longer 100 km/h bypass A-D-C."""
    G = nx.MultiDiGraph(crs="EPSG:4326")
    for n, (e, nn) in {"A": (0, 0), "B": (1000, 0), "C": (2000, 0), "D": (1000, 800)}.items():
        lon, lat = xy(e, nn)
        G.add_node(n, x=lon, y=lat)
    G = nx.relabel_nodes(G, {"A": 1, "B": 2, "C": 3, "D": 4})
    add(G, 1, 2, 1000, 30, "Main St")
    add(G, 2, 3, 1000, 30, "Main St")
    add(G, 1, 4, 1300, 100, "Bypass")
    add(G, 4, 3, 1300, 100, "Bypass")
    G.add_node(99, x=xy(0, -500)[0], y=xy(0, -500)[1])  # unreachable from the rest
    G.add_edge(99, 1, key=0, length=500, travel_time=60, name="Dead end")  # one-way in only
    return G


@pytest.fixture(scope="module")
def router():
    return Router(toy_graph())


def pair_on_main_st():
    """Opposite-facing pair on A-B, like the College Ave pair: one faces east, one west."""
    east = SimCamera(1, "east-facing", "public_road", [90.0],
                     edges=[CameraEdge((1, 2, 0), 0.5, 90.0), CameraEdge((2, 1, 0), 0.5, 270.0)])
    west = SimCamera(2, "west-facing", "public_road", [270.0],
                     edges=[CameraEdge((1, 2, 0), 0.5, 90.0), CameraEdge((2, 1, 0), 0.5, 270.0)])
    return CameraSet([east, west])


def test_router_prefers_faster_route_over_shorter(router):
    r = router.route(xy(0, 0), xy(2000, 0), DEPART)
    assert [e.edge[:2] for e in r.edges] == [(1, 4), (4, 3)]
    assert r.length_m == pytest.approx(2600)
    assert r.duration_s == pytest.approx(2 * 1300 / (100 / 3.6))
    assert r.arrive == DEPART + timedelta(seconds=r.duration_s)


def test_router_snaps_to_strongly_connected_core(router):
    # Nearest node to this point is the dead-end node 99, which can't be routed from.
    node, dist = router.nearest_node(*xy(0, -490))
    assert node == 1
    assert dist == pytest.approx(490, rel=0.02)


def test_route_edge_offsets_accumulate(router):
    r = router.route(xy(0, 0), xy(1000, 0), DEPART)
    assert [e.edge[:2] for e in r.edges] == [(1, 2)]
    r2 = router.route(xy(0, 0), xy(2000, 0), DEPART)
    assert r2.edges[1].enter_offset_s == pytest.approx(r2.edges[0].travel_time_s)


def test_coords_follow_route(router):
    r = router.route(xy(0, 0), xy(2000, 0), DEPART)
    assert r.coords[0] == pytest.approx(xy(0, 0))
    assert r.coords[-1] == pytest.approx(xy(2000, 0))


@pytest.mark.parametrize(
    "facing, origin, dest, fires",
    [
        ("rear_plate", (0, 0), (1000, 0), "east-facing"),
        ("rear_plate", (1000, 0), (0, 0), "west-facing"),
        ("oncoming", (0, 0), (1000, 0), "west-facing"),
        ("oncoming", (1000, 0), (0, 0), "east-facing"),
    ],
)
def test_opposite_pair_only_one_fires(router, facing, origin, dest, fires):
    result = simulate_trip(router, pair_on_main_st(), xy(*origin), xy(*dest), DEPART, MatchConfig(facing=facing))
    assert len(result.passes) == 2  # both cameras are passed
    assert [p.label for p in result.captured] == [fires]
    skipped = [p for p in result.passes if not p.captured]
    assert len(skipped) == 1 and skipped[0].reason is Reason.WRONG_DIRECTION


def test_pass_time_uses_fraction_along_edge(router):
    result = simulate_trip(router, pair_on_main_st(), xy(0, 0), xy(1000, 0), DEPART)
    half_edge = 500 / (30 / 3.6)
    assert all(p.time == DEPART + timedelta(seconds=half_edge) for p in result.passes)


def test_cameras_off_route_not_passed(router):
    result = simulate_trip(router, pair_on_main_st(), xy(0, 0), xy(2000, 0), DEPART)  # takes the bypass
    assert result.passes == []


def test_undirected_camera_modes(router):
    cam = SimCamera(3, "undirected", "public_road", None, edges=[CameraEdge((1, 2, 0), 0.5, 90.0)])
    best = simulate_trip(router, CameraSet([cam]), xy(0, 0), xy(1000, 0), DEPART, MatchConfig(undirected="best"))
    worst = simulate_trip(router, CameraSet([cam]), xy(0, 0), xy(1000, 0), DEPART, MatchConfig(undirected="worst"))
    assert [p.reason for p in best.passes] == [Reason.UNDIRECTED_BEST] and best.passes[0].captured
    assert [p.reason for p in worst.passes] == [Reason.UNDIRECTED_WORST] and not worst.passes[0].captured


def lot_camera(facings, alt=None, cid=5, at=(1000, 0)):
    dest_lon, dest_lat = xy(1000, 0)
    lot = box(dest_lon - 0.001, dest_lat - 0.001, dest_lon + 0.001, dest_lat + 0.001)
    lon, lat = xy(*at)
    return SimCamera(cid, f"lot{cid}", "private_lot", [0.0], alt_directions_deg=[180.0] if alt else None,
                     lot_geom=lot, lot_id="way/77", lot_name="Test Plaza", facings=facings, alt_facings=alt,
                     lon=lon, lat=lat)


def test_lot_arrival_captured_at_arrival_time(router):
    cams = CameraSet([lot_camera(["into_lot"])])
    result = simulate_trip(router, cams, xy(0, 0), xy(1000, 0), DEPART)
    assert [(p.event, p.captured) for p in result.passes] == [("arrival", True)]
    assert result.passes[0].time == result.route.arrive
    assert result.passes[0].road_name == "Test Plaza"


def test_lot_departure_needs_toward_road_facing(router):
    cams = CameraSet([lot_camera(["into_lot"])])
    leaving = simulate_trip(router, cams, xy(1000, 0), xy(0, 0), DEPART)
    assert [(p.event, p.captured, p.reason) for p in leaving.passes] == [("departure", False, Reason.WRONG_DIRECTION)]
    oncoming = simulate_trip(router, cams, xy(1000, 0), xy(0, 0), DEPART, MatchConfig(facing="oncoming"))
    assert oncoming.passes[0].captured


def test_ambiguous_lot_camera_alternate_reading(router):
    cams = CameraSet([lot_camera(["into_lot"], alt=["toward_road"])])
    primary = simulate_trip(router, cams, xy(0, 0), xy(1000, 0), DEPART)
    alternate = simulate_trip(router, cams, xy(0, 0), xy(1000, 0), DEPART, MatchConfig(ambiguous_direction="alternate"))
    assert primary.passes[0].captured
    assert not alternate.passes[0].captured


def test_trip_not_touching_lot_has_no_lot_events(router):
    cams = CameraSet([lot_camera(["into_lot", "toward_road"])])
    assert simulate_trip(router, cams, xy(0, 0), xy(2000, 0), DEPART).passes == []


def test_match_route_sorted_by_time(router):
    cams = pair_on_main_st()
    cams2 = CameraSet(list(cams.by_id.values()) + [lot_camera(["into_lot"])])
    route = router.route(xy(0, 0), xy(1000, 0), DEPART)
    passes = match_route(route, cams2, xy(0, 0), xy(1000, 0), MatchConfig())
    assert [p.time for p in passes] == sorted(p.time for p in passes)
    assert passes[-1].event == "arrival"


def test_lot_arrival_uses_only_nearest_entrance_by_default(router):
    # Route arrives at node B (1000, 0). Camera 6 is at the entrance near B; camera 7 is across the lot.
    near = lot_camera(["into_lot"], cid=6, at=(1000, 20))
    far = lot_camera(["into_lot"], cid=7, at=(1080, 80))
    cams = CameraSet([near, far])
    nearest = simulate_trip(router, cams, xy(0, 0), xy(1000, 0), DEPART)
    assert [p.label for p in nearest.passes] == ["lot6"]
    every = simulate_trip(router, cams, xy(0, 0), xy(1000, 0), DEPART, MatchConfig(lot_entrance="all"))
    assert sorted(p.label for p in every.passes) == ["lot6", "lot7"]


def test_nearest_entrance_can_be_a_camera_that_misses(router):
    # The nearest entrance camera faces toward the road: the arrival is passed but not captured,
    # and the farther into-lot camera does not get a second chance.
    near = lot_camera(["toward_road"], cid=6, at=(1000, 20))
    far = lot_camera(["into_lot"], cid=7, at=(1080, 80))
    r = simulate_trip(router, CameraSet([near, far]), xy(0, 0), xy(1000, 0), DEPART)
    assert [(p.label, p.captured) for p in r.passes] == [("lot6", False)]
