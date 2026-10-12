"""Snap cameras to their nearest drive-network edge.

Works on a projected (metric) graph. For each camera:

1. Find the nearest edge geometry within max_distance_m (default 50 m).
   Cameras farther than that are dropped and reported.
2. Every directed edge at that same distance gets a snap: on a two-way road
   that is both directions (same geometry, reversed), on a one-way road just
   one. If several *different* roads tie (the camera projects onto an
   intersection node), the road most parallel to the camera's direction wins.
3. Each snap records the travel bearing u->v at the snap point, from the
   edge's own geometry rather than the u->v chord, so curved roads are right.
   Bearings are true-north geodesic azimuths, not UTM grid angles.
"""

from dataclasses import dataclass

import networkx as nx
import osmnx as ox
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, Point

from platetrail.geo import axis_diff, geodesic_bearing

MAX_SNAP_M = 50.0
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


class EdgeIndex:
    def __init__(self, G_proj: nx.MultiDiGraph):
        if not G_proj.graph.get("crs") or "4326" in str(G_proj.graph["crs"]):
            raise ValueError("EdgeIndex needs a projected graph (use ox.project_graph)")
        gdf = ox.graph_to_gdfs(G_proj, nodes=False)
        self.keys: list[EdgeKey] = [(int(u), int(v), int(k)) for u, v, k in gdf.index]
        self.geoms: list[LineString] = list(gdf.geometry)
        self.names: list[str | None] = [_name(n) for n in gdf.get("name", [None] * len(gdf))]
        self.tree = STRtree(self.geoms)
        self.to_proj = Transformer.from_crs("EPSG:4326", G_proj.graph["crs"], always_xy=True)
        self.to_wgs = Transformer.from_crs(G_proj.graph["crs"], "EPSG:4326", always_xy=True)

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


def snap_camera(index: EdgeIndex, cam: CameraInput, max_distance_m: float = MAX_SNAP_M) -> SnapResult:
    pt = index.project_point(cam.lon, cam.lat)
    nearest_i, nearest_d = index.tree.query_nearest(pt, return_distance=True)
    nearest_m = float(nearest_d[0]) if len(nearest_d) else None
    if nearest_m is None or nearest_m > max_distance_m:
        return SnapResult(camera=cam, snaps=[], nearest_m=nearest_m)

    tied = [(i, d) for i, d in index.edges_within(pt, nearest_m + TIE_TOL_M) if d <= nearest_m + TIE_TOL_M]
    roads: dict[frozenset, list[int]] = {}
    for i, _ in tied:
        roads.setdefault(_road_id(index.keys[i]), []).append(i)

    tie_broken = len(roads) > 1
    if tie_broken:
        best_road = min(roads, key=lambda r: (_parallelism(index, roads[r][0], pt, cam.directions_deg), sorted(r)))
    else:
        best_road = next(iter(roads))

    snaps = sorted((index.make_snap(cam.camera_id, i, pt) for i in roads[best_road]), key=lambda s: s.edge)
    return SnapResult(camera=cam, snaps=snaps, nearest_m=nearest_m, tie_broken=tie_broken)


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
