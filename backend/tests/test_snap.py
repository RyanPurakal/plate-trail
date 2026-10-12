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
