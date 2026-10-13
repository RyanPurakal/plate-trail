import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString

from platetrail.geo import angle_diff, axis_diff, geodesic_bearing
from platetrail.roads.snap import CameraInput, EdgeIndex, alignment_flags, snap_camera

CRS = "EPSG:32618"  # UTM 18N, covers Edison / New Brunswick
X0, Y0 = 545_000.0, 4_484_000.0
to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)


def add_edge(G, u, v, coords, two_way=False):
    geom = LineString([(X0 + x, Y0 + y) for x, y in coords])
    G.add_edge(u, v, key=0, geometry=geom, name=f"{u}-{v}")
    if two_way:
        G.add_edge(v, u, key=0, geometry=LineString(geom.coords[::-1]), name=f"{u}-{v}")


def toy_graph():
    G = nx.MultiDiGraph(crs=CRS)
    pts = {1: (0, 0), 2: (200, 0), 3: (300, -100), 4: (300, 100), 5: (500, 0), 6: (600, 100),
           7: (800, 0), 8: (900, 0), 9: (800, 100)}
    for n, (x, y) in pts.items():
        G.add_node(n, x=X0 + x, y=Y0 + y)
    add_edge(G, 1, 2, [(0, 0), (200, 0)], two_way=True)             # straight E-W two-way
    add_edge(G, 3, 4, [(300, -100), (300, 100)])                    # one-way northbound
    add_edge(G, 5, 6, [(500, 0), (600, 0), (600, 100)])             # L-shaped one-way
    add_edge(G, 7, 8, [(800, 0), (900, 0)], two_way=True)           # intersection: east arm
    add_edge(G, 7, 9, [(800, 0), (800, 100)], two_way=True)         # intersection: north arm
    # Divided road: westbound carriageway at y=1000, eastbound at y=1020, plus a
    # same-direction one-way at y=1040 that must not count as a twin.
    for n, (x, y) in {20: (0, 1000), 21: (200, 1000), 22: (0, 1020), 23: (200, 1020),
                      24: (0, 1040), 25: (200, 1040)}.items():
        G.add_node(n, x=X0 + x, y=Y0 + y)
    add_edge(G, 21, 20, [(200, 1000), (0, 1000)])                  # westbound
    add_edge(G, 22, 23, [(0, 1020), (200, 1020)])                  # eastbound
    add_edge(G, 25, 24, [(200, 1040), (0, 1040)])                  # westbound again
    return G


@pytest.fixture(scope="module")
def index():
    return EdgeIndex(toy_graph())


def cam(x, y, dirs=None, cid=1):
    lon, lat = to_wgs.transform(X0 + x, Y0 + y)
    return CameraInput(camera_id=cid, label=f"cam{cid}", lon=lon, lat=lat, directions_deg=dirs)


def test_axis_diff():
    assert axis_diff(0, 180) == 0
    assert axis_diff(10, 350) == 20
    assert axis_diff(0, 90) == 90
    assert axis_diff(45, 270) == 45


def test_rejects_unprojected_graph():
    G = toy_graph()
    G.graph["crs"] = "EPSG:4326"
    with pytest.raises(ValueError):
        EdgeIndex(G)


def test_two_way_road_gives_both_directions_with_opposite_bearings(index):
    r = snap_camera(index, cam(100, 10, [90]))
    assert not r.dropped
    assert {s.edge for s in r.snaps} == {(1, 2, 0), (2, 1, 0)}
    by_edge = {s.edge: s for s in r.snaps}
    assert angle_diff(by_edge[(1, 2, 0)].bearing_deg, 90) < 1.0  # eastbound
    assert angle_diff(by_edge[(2, 1, 0)].bearing_deg, 270) < 1.0  # westbound
    assert by_edge[(1, 2, 0)].distance_m == pytest.approx(10, abs=0.05)
    assert by_edge[(1, 2, 0)].fraction_along == pytest.approx(0.5, abs=0.01)
    assert by_edge[(2, 1, 0)].fraction_along == pytest.approx(0.5, abs=0.01)


def test_one_way_road_gives_single_snap(index):
    r = snap_camera(index, cam(310, 0, [0]))
    assert [s.edge for s in r.snaps] == [(3, 4, 0)]
    assert angle_diff(r.snaps[0].bearing_deg, 0) < 1.0


def test_curved_edge_uses_local_bearing_not_chord(index):
    # On the northbound leg of the L; the 5->6 chord would be ~45 deg.
    r = snap_camera(index, cam(605, 60, [0]))
    assert [s.edge for s in r.snaps] == [(5, 6, 0)]
    assert angle_diff(r.snaps[0].bearing_deg, 0) < 1.0
    r = snap_camera(index, cam(540, 5, [90]))
    assert angle_diff(r.snaps[0].bearing_deg, 90) < 1.0


def test_beyond_50m_is_dropped_with_nearest_distance(index):
    r = snap_camera(index, cam(100, 80))
    assert r.dropped
    assert r.nearest_m == pytest.approx(80, abs=0.1)


def test_exactly_at_cutoff_is_kept(index):
    assert not snap_camera(index, cam(100, 49.9)).dropped
    assert snap_camera(index, cam(100, 50.1)).dropped


def test_intersection_tie_broken_by_direction(index):
    # South-west of the node: equidistant to both arms' endpoint at node 7.
    northish = snap_camera(index, cam(790, -10, [5]))
    eastish = snap_camera(index, cam(790, -10, [85]))
    assert northish.tie_broken and eastish.tie_broken
    assert {s.edge for s in northish.snaps} == {(7, 9, 0), (9, 7, 0)}
    assert {s.edge for s in eastish.snaps} == {(7, 8, 0), (8, 7, 0)}


def test_bearing_is_true_north_not_utm_grid():
    # A road along a meridian: true bearing 0, but in UTM 18N it is tilted by
    # meridian convergence (~0.4 deg here), so a grid angle would be off.
    a = to_utm.transform(-74.40, 40.50)
    b = to_utm.transform(-74.40, 40.51)
    G = nx.MultiDiGraph(crs=CRS)
    G.add_node(1, x=a[0], y=a[1])
    G.add_node(2, x=b[0], y=b[1])
    G.add_edge(1, 2, key=0, geometry=LineString([a, b]))
    idx = EdgeIndex(G)
    r = snap_camera(idx, CameraInput(1, "c", -74.4001, 40.505, [0]))
    import math

    grid = math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360
    assert angle_diff(grid, 0) > 0.2  # the trap is real
    assert angle_diff(r.snaps[0].bearing_deg, 0) < 0.05


def test_geodesic_bearing_cardinals():
    assert geodesic_bearing(-74.4, 40.5, -74.4, 40.6) == pytest.approx(0, abs=1e-6)
    assert geodesic_bearing(-74.4, 40.5, -74.4, 40.4) == pytest.approx(180, abs=1e-6)
    assert angle_diff(geodesic_bearing(-74.4, 40.5, -74.3, 40.5), 90) < 0.1


def test_parallel_camera_not_flagged(index):
    r = snap_camera(index, cam(100, 10, [270]))
    assert alignment_flags(index, r) == []


def test_perpendicular_camera_flagged_with_parallel_alternative(index):
    # 5 m from the east arm but facing north; the north arm is 30 m away.
    r = snap_camera(index, cam(830, 5, [0]))
    assert {s.edge for s in r.snaps} == {(7, 8, 0), (8, 7, 0)}
    flags = alignment_flags(index, r)
    assert len(flags) == 1
    assert flags[0].axis_diff_deg > 80
    assert flags[0].alternative is not None
    assert flags[0].alternative.edge in {(7, 9, 0), (9, 7, 0)}
    assert flags[0].alternative.distance_m == pytest.approx(30, abs=0.1)


def test_perpendicular_without_alternative(index):
    r = snap_camera(index, cam(100, 10, [0]))
    flags = alignment_flags(index, r)
    assert len(flags) == 1 and flags[0].alternative is None


def test_undirected_camera_never_flagged(index):
    assert alignment_flags(index, snap_camera(index, cam(100, 10, None))) == []


def test_multi_direction_camera_flags_only_off_axis_direction(index):
    flags = alignment_flags(index, snap_camera(index, cam(100, 10, [90, 0])))
    assert [f.direction_deg for f in flags] == [0]


def test_direction_aware_snap_prefers_parallel_road_within_10m(index):
    # 5 m from the E-W east arm, 8 m from the N-S north arm (within +10 m), facing north.
    r = snap_camera(index, cam(808, 5, [0]))
    assert {s.edge for s in r.snaps} == {(7, 9, 0), (9, 7, 0)}
    assert r.resnapped_from == "7-8"


def test_direction_aware_snap_keeps_nearest_when_parallel_road_too_far(index):
    r = snap_camera(index, cam(830, 5, [0]))  # north arm 30 m away
    assert {s.edge for s in r.snaps} == {(7, 8, 0), (8, 7, 0)}
    assert r.resnapped_from is None


def test_direction_aware_snap_ignores_undirected(index):
    r = snap_camera(index, cam(808, 5, None))
    assert {s.edge for s in r.snaps} == {(7, 8, 0), (8, 7, 0)}


def test_divided_road_snaps_both_carriageways(index):
    r = snap_camera(index, cam(100, 1008, [260, 80]))  # 8 m from westbound, 12 m from eastbound
    assert {s.edge for s in r.snaps} == {(21, 20, 0), (22, 23, 0)}
    assert r.twin_added
    by_edge = {s.edge: s for s in r.snaps}
    assert angle_diff(by_edge[(21, 20, 0)].bearing_deg, 270) < 1
    assert angle_diff(by_edge[(22, 23, 0)].bearing_deg, 90) < 1


def test_twin_must_run_opposite_and_be_close(index):
    # 5 m from the eastbound carriageway (y=1020); westbound one-ways at 15 m (y=1040)
    # and 25 m (y=1000). The nearer opposite carriageway is the twin; the camera faces both ways.
    r = snap_camera(index, cam(100, 1025, [80, 260]))
    assert {s.edge for s in r.snaps} == {(22, 23, 0), (25, 24, 0)}
    far = snap_camera(index, cam(100, 975, [260]))  # 25 m from westbound, eastbound 45 m away
    assert {s.edge for s in far.snaps} == {(21, 20, 0)} and not far.twin_added


def test_two_way_road_gets_no_twin(index):
    r = snap_camera(index, cam(100, 10, [90]))
    assert not r.twin_added and len(r.snaps) == 2


def test_twin_attached_regardless_of_facing(index):
    # 8 m from the westbound carriageway; the eastbound one is 12 m away. The camera faces 260 (along
    # its own carriageway) but snapping ignores facing: both carriageways are attached.
    for dirs in ([260], [80], [175], [260, 80]):
        r = snap_camera(index, cam(100, 1008, dirs))
        assert {s.edge for s in r.snaps} == {(21, 20, 0), (22, 23, 0)} and r.twin_added


@pytest.mark.parametrize("facing, captured_edge", [("rear_plate", (21, 20, 0)), ("oncoming", (22, 23, 0))])
def test_matcher_not_snapping_decides_which_carriageway_is_captured(index, facing, captured_edge):
    from platetrail.sim.matcher import MatchConfig, edge_decision

    r = snap_camera(index, cam(100, 1008, [260]))  # faces west, along the westbound carriageway
    cfg = MatchConfig(facing=facing)
    captured = [s.edge for s in r.snaps if edge_decision([260], s.bearing_deg, cfg).captured]
    assert captured == [captured_edge]


def test_undirected_camera_gets_twin(index):
    assert snap_camera(index, cam(100, 1008, None)).twin_added


def test_public_only_index_skips_service_edges():
    G = toy_graph()
    for _, _, d in G.edges(data=True):
        d["highway"] = "residential"
    G.add_node(30, x=X0 + 100, y=Y0 + 3)
    G.add_node(31, x=X0 + 150, y=Y0 + 3)
    G.add_edge(30, 31, key=0, geometry=LineString([(X0 + 100, Y0 + 3), (X0 + 150, Y0 + 3)]), highway="service")
    full, public = EdgeIndex(G), EdgeIndex(G, public_only=True)
    c = cam(120, 4, [90])
    assert snap_camera(full, c).snaps[0].edge == (30, 31, 0)
    assert {s.edge for s in snap_camera(public, c).snaps} == {(1, 2, 0), (2, 1, 0)}


def test_is_service():
    from platetrail.roads.snap import is_service
    assert is_service("service") and is_service(["service", "service"])
    assert not is_service("residential") and not is_service(["service", "residential"])


def test_deep_lot_camera_falls_back_to_service_street():
    from platetrail.roads.snap import snap_with_service_fallback

    G = toy_graph()
    for _, _, d in G.edges(data=True):
        d["highway"] = "residential"
    # A service street 200 m north of the E-W road, far from every public edge.
    G.add_node(40, x=X0 + 50, y=Y0 + 200)
    G.add_node(41, x=X0 + 150, y=Y0 + 200)
    for a, b in ((40, 41), (41, 40)):
        G.add_edge(a, b, key=0, highway="service",
                   geometry=LineString([(X0 + G.nodes[a]["x"] - X0, Y0 + 200), (X0 + G.nodes[b]["x"] - X0, Y0 + 200)]))
    public, service = EdgeIndex(G, public_only=True), EdgeIndex(G, service_only=True)
    deep = cam(100, 206, [90], cid=1)  # 6 m from the service street, 194 m from the public road
    near_public = cam(100, 10, [90], cid=2)  # ordinary public-road camera
    nowhere = cam(600, 600, [90], cid=3)  # far from everything
    results, on_service = snap_with_service_fallback(public, service, [deep, near_public, nowhere])
    assert on_service == {1}
    assert {s.edge for s in results[0].snaps} == {(40, 41, 0), (41, 40, 0)}
    assert {s.edge for s in results[1].snaps} == {(1, 2, 0), (2, 1, 0)}
    assert results[2].dropped
