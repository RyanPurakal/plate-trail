"""Snap cameras to their nearest drive-network edge.

Works on a projected (metric) graph. For each camera:

1. Find the nearest edge geometry within max_distance_m (default 50 m).
   Cameras farther than that are dropped and reported.
2. Direction-aware choice: if the nearest road is not parallel to the
   camera (axis more than 30 deg off) but another road within an extra 10 m
   is, the parallel road wins. Exact ties (camera projects onto an
   intersection node) go to the most parallel road.
3. Every directed edge of the chosen road gets a snap: both directions on a
   two-way road (same geometry, reversed), one on a one-way road. If the
   chosen road is one carriageway of a divided road, the opposite
   carriageway (one-way, parallel, opposite travel, within 30 m of the
   camera) is snapped too, but only if one of the camera's facings is
   within 45 deg of that carriageway's travel bearing (undirected cameras
   always get it). Without this a camera beside, e.g., Albany St's westbound
   carriageway never sees eastbound traffic. Note the facing check assumes
   the rear-plate convention (a camera faces the traffic it reads); under
   the oncoming convention a camera that fails it can't see that
   carriageway.

Cameras snap to public roads only (EdgeIndex(..., public_only=True)).
Service roads are in the graph for routing to places inside lots; cameras
watching lots and driveways are handled as private_lot cameras (roads.lots).
4. Each snap records the travel bearing u->v at the snap point, from the
   edge's own geometry rather than the u->v chord, so curved roads are right.
   Bearings are true-north geodesic azimuths, not UTM grid angles.
"""

from dataclasses import dataclass

import networkx as nx
import osmnx as ox
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, Point

from platetrail.geo import angle_diff, axis_diff, geodesic_bearing

MAX_SNAP_M = 50.0
PREFER_PARALLEL_WITHIN_M = 10.0  # extra distance allowed to reach a parallel road
PARALLEL_DEG = 30.0  # axis difference that counts as "parallel"
TWIN_CARRIAGEWAY_M = 30.0  # max camera distance to the opposite carriageway of a divided road
TWIN_FACING_DEG = 45.0  # a camera facing must be within this of the opposite carriageway's bearing
TIE_TOL_M = 0.01  # distances this close count as the same road geometry
BEARING_STEP_M = 2.0  # half-width of the window used to measure local bearing

EdgeKey = tuple[int, int, int]


@dataclass(frozen=True)
class CameraInput:
    camera_id: int
    label: str  # e.g. OSM id, for reporting
    lon: float
    lat: float
    directions_deg: list[float] | None


@dataclass(frozen=True)
class EdgeSnap:
    camera_id: int
    edge: EdgeKey
    distance_m: float
    bearing_deg: float  # travel bearing along u->v at the snap point
    fraction_along: float
    snap_lon: float
    snap_lat: float
    name: str | None


@dataclass
class SnapResult:
    camera: CameraInput
    snaps: list[EdgeSnap]  # empty when dropped
    nearest_m: float | None  # distance to nearest edge, even if beyond the cutoff
    tie_broken: bool = False
    resnapped_from: str | None = None  # nearest road's name when a farther parallel road won
    twin_added: bool = False  # opposite carriageway of a divided road also snapped

    @property
    def dropped(self) -> bool:
        return not self.snaps


def _road_id(edge: EdgeKey) -> frozenset:
    """Undirected road identity: (u, v) and (v, u) are the same road."""
    u, v, _ = edge
    return frozenset((u, v))


def _name(value) -> str | None:
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    return value if isinstance(value, str) else None


def is_service(highway) -> bool:
    """True for service-road edges (OSMnx merges tags into lists on simplified edges)."""
    values = highway if isinstance(highway, list) else [highway]
    return bool(values) and all(v == "service" for v in values)


class EdgeIndex:
    def __init__(self, G_proj: nx.MultiDiGraph, public_only: bool = False):
        if not G_proj.graph.get("crs") or "4326" in str(G_proj.graph["crs"]):
            raise ValueError("EdgeIndex needs a projected graph (use ox.project_graph)")
        gdf = ox.graph_to_gdfs(G_proj, nodes=False)
        if public_only and "highway" in gdf:
            gdf = gdf[~gdf["highway"].map(is_service)]
        self.keys: list[EdgeKey] = [(int(u), int(v), int(k)) for u, v, k in gdf.index]
        self.geoms: list[LineString] = list(gdf.geometry)
        self.names: list[str | None] = [_name(n) for n in gdf.get("name", [None] * len(gdf))]
        self.tree = STRtree(self.geoms)
        self._directed = {(u, v) for u, v, _ in self.keys}
        self.to_proj = Transformer.from_crs("EPSG:4326", G_proj.graph["crs"], always_xy=True)
        self.to_wgs = Transformer.from_crs(G_proj.graph["crs"], "EPSG:4326", always_xy=True)

    def is_one_way(self, i: int) -> bool:
        u, v, _ = self.keys[i]
        return (v, u) not in self._directed

    def project_point(self, lon: float, lat: float) -> Point:
        return Point(*self.to_proj.transform(lon, lat))

    def bearing_at(self, line: LineString, s: float) -> float:
        """Geodesic travel bearing along `line` at distance s from its start."""
        a = line.interpolate(max(0.0, s - BEARING_STEP_M))
        b = line.interpolate(min(line.length, s + BEARING_STEP_M))
        if a.distance(b) < 1e-6:  # degenerate edge
            a, b = Point(line.coords[0]), Point(line.coords[-1])
        lon1, lat1 = self.to_wgs.transform(a.x, a.y)
        lon2, lat2 = self.to_wgs.transform(b.x, b.y)
        return geodesic_bearing(lon1, lat1, lon2, lat2)

    def edges_within(self, pt: Point, radius_m: float) -> list[tuple[int, float]]:
        """(edge index, distance) for every edge within radius, nearest first."""
        idx = self.tree.query(pt, predicate="dwithin", distance=radius_m)
        return sorted(((int(i), self.geoms[i].distance(pt)) for i in idx), key=lambda t: t[1])

    def make_snap(self, camera_id: int, i: int, pt: Point) -> EdgeSnap:
        line = self.geoms[i]
        s = line.project(pt)
        sp = line.interpolate(s)
        lon, lat = self.to_wgs.transform(sp.x, sp.y)
        return EdgeSnap(
            camera_id=camera_id,
            edge=self.keys[i],
            distance_m=line.distance(pt),
            bearing_deg=self.bearing_at(line, s),
            fraction_along=s / line.length if line.length else 0.0,
            snap_lon=lon,
            snap_lat=lat,
            name=self.names[i],
        )


def _parallelism(index: EdgeIndex, i: int, pt: Point, directions: list[float] | None) -> float:
    """Best (smallest) axis difference between the road at pt and any camera direction."""
    if not directions:
        return 0.0
    line = index.geoms[i]
    road = index.bearing_at(line, line.project(pt))
    return min(axis_diff(road, d) for d in directions)


def snap_camera(
    index: EdgeIndex,
    cam: CameraInput,
    max_distance_m: float = MAX_SNAP_M,
    prefer_parallel_within_m: float = PREFER_PARALLEL_WITHIN_M,
    parallel_deg: float = PARALLEL_DEG,
) -> SnapResult:
    pt = index.project_point(cam.lon, cam.lat)
    nearest_i, nearest_d = index.tree.query_nearest(pt, return_distance=True)
    nearest_m = float(nearest_d[0]) if len(nearest_d) else None
    if nearest_m is None or nearest_m > max_distance_m:
        return SnapResult(camera=cam, snaps=[], nearest_m=nearest_m)

    # Group candidate edges into undirected roads, keeping each road's distance.
    roads: dict[frozenset, list[int]] = {}
    road_dist: dict[frozenset, float] = {}
    for i, d in index.edges_within(pt, nearest_m + prefer_parallel_within_m):
        r = _road_id(index.keys[i])
        roads.setdefault(r, []).append(i)
        road_dist[r] = min(road_dist.get(r, d), d)

    def par(r: frozenset) -> float:
        return _parallelism(index, roads[r][0], pt, cam.directions_deg)

    tied = [r for r in roads if road_dist[r] <= nearest_m + TIE_TOL_M]
    tie_broken = len(tied) > 1
    chosen = min(tied, key=lambda r: (par(r), sorted(r)))

    resnapped_from = None
    if cam.directions_deg and par(chosen) > parallel_deg:
        parallel = [r for r in roads if par(r) <= parallel_deg]
        if parallel:
            resnapped_from = index.names[roads[chosen][0]] or "unnamed"
            chosen = min(parallel, key=lambda r: (road_dist[r], sorted(r)))

    chosen_edges = list(roads[chosen])
    twin = _twin_carriageway(index, pt, chosen_edges, max_distance_m, cam.directions_deg)
    if twin is not None:
        chosen_edges.append(twin)
    snaps = sorted((index.make_snap(cam.camera_id, i, pt) for i in chosen_edges), key=lambda s: s.edge)
    return SnapResult(camera=cam, snaps=snaps, nearest_m=nearest_m, tie_broken=tie_broken,
                      resnapped_from=resnapped_from, twin_added=twin is not None)


def _twin_carriageway(
    index: EdgeIndex, pt: Point, chosen: list[int], max_distance_m: float, directions: list[float] | None
) -> int | None:
    """Nearest opposite-direction one-way edge parallel to a one-way chosen edge that a facing points along."""
    if len(chosen) != 1 or not index.is_one_way(chosen[0]):
        return None
    line = index.geoms[chosen[0]]
    bearing = index.bearing_at(line, line.project(pt))
    own = _road_id(index.keys[chosen[0]])
    for i, _ in index.edges_within(pt, min(TWIN_CARRIAGEWAY_M, max_distance_m)):
        if _road_id(index.keys[i]) == own or not index.is_one_way(i):
            continue
        other = index.bearing_at(index.geoms[i], index.geoms[i].project(pt))
        if angle_diff(bearing, other) < 180.0 - PARALLEL_DEG:
            continue
        if directions and min(angle_diff(d, other) for d in directions) > TWIN_FACING_DEG:
            return None  # nearest opposite carriageway, but no facing points along it
        return i
    return None


def road_axis_offset(result: SnapResult) -> float | None:
    """Smallest axis difference between the camera's directions and its snapped road."""
    if result.dropped or not result.camera.directions_deg:
        return None
    return min(axis_diff(result.snaps[0].bearing_deg, d) for d in result.camera.directions_deg)


@dataclass(frozen=True)
class AlignmentFlag:
    camera: CameraInput
    direction_deg: float
    road_bearing_deg: float
    axis_diff_deg: float
    # Nearest alternative road within the snap radius that runs parallel to this direction.
    alternative: EdgeSnap | None


def alignment_flags(
    index: EdgeIndex,
    result: SnapResult,
    perpendicular_above_deg: float = 45.0,
    parallel_within_deg: float = 30.0,
    max_distance_m: float = MAX_SNAP_M,
) -> list[AlignmentFlag]:
    """Camera directions closer to perpendicular than parallel to the snapped road."""
    if result.dropped or not result.camera.directions_deg:
        return []
    road_bearing = result.snaps[0].bearing_deg
    pt = index.project_point(result.camera.lon, result.camera.lat)
    snapped_road = _road_id(result.snaps[0].edge)
    flags = []
    for d in result.camera.directions_deg:
        diff = axis_diff(road_bearing, d)
        if diff <= perpendicular_above_deg:
            continue
        alternative = None
        for i, _ in index.edges_within(pt, max_distance_m):
            if _road_id(index.keys[i]) == snapped_road:
                continue
            if _parallelism(index, i, pt, [d]) <= parallel_within_deg:
                alternative = index.make_snap(result.camera.camera_id, i, pt)
                break
        flags.append(AlignmentFlag(result.camera, d, road_bearing, diff, alternative))
    return flags
