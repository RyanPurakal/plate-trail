"""Classify cameras that watch private lots rather than public roads.

A camera becomes `private_lot` when either:

* it is more than 50 m from the drive network (dropped by snapping) and a
  parking/retail polygon is nearby, or
* its direction is closer to perpendicular than parallel to its snapped
  public road, and a service road (driveway, lot entrance) within 10 m runs
  parallel to that direction.

Lot cameras get no public-road snap. Each is attached to the lot polygon it
serves and, where there is one, the service road it faces along. Polygons
containing the camera (or crossed by its service road) are preferred, then
by kind: retail, commercial, industrial (e.g. Raritan Center, whose internal
streets are tagged service), parking, shop buildings.

For each camera direction we record whether it points into the lot or
toward the public road. The facing setting then decides at match time
whether the camera captures arrivals or departures. "Toward the road" means
toward the nearest point on the drive network. That is a simplification for
cameras deep inside a lot, where the actual exit may be elsewhere.

Remaining public-road cameras still closer to perpendicular than parallel
to their road after direction-aware snapping are marked snap_ambiguous: they
keep the nearest snap, but it is unclear which street they watch. Cameras
30-45 deg off their road are not flagged; whether they fire depends on the
matcher's bearing tolerance.
"""

from dataclasses import dataclass, field

from pyproj import Transformer
import shapely
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from platetrail.etl.cache import RawCache
from platetrail.etl.loaders.overpass import OverpassClient
from platetrail.geo import angle_diff, axis_diff, geodesic_bearing
from platetrail.roads.snap import PARALLEL_DEG, CameraInput, EdgeIndex, SnapResult, road_axis_offset

PERPENDICULAR_DEG = 45.0
SERVICE_WITHIN_M = 10.0
SERVICE_SEARCH_M = 60
LOT_SEARCH_M = 150
LOT_KIND_PRIORITY = ("retail", "commercial", "industrial", "parking", "shop")


@dataclass
class OsmFeature:
    osm_id: str  # "way/123" or "relation/456"
    kind: str  # service, or one of LOT_KIND_PRIORITY
    tags: dict
    geom_wgs: BaseGeometry
    geom: BaseGeometry  # projected (metres)

    @property
    def name(self) -> str | None:
        return self.tags.get("name") or self.tags.get("brand") or self.tags.get("operator")


@dataclass
class LotAssignment:
    camera: CameraInput
    lot: OsmFeature | None
    watched_way: OsmFeature | None
    facings: list[str]
    alt_facings: list[str] | None
    reason: str  # "dropped" or "driveway"
    access_edge: tuple[int, int, int] | None = None  # nearest public drive edge to the camera
    access_distance_m: float | None = None


@dataclass
class Classification:
    lots: dict[int, LotAssignment] = field(default_factory=dict)  # camera_id -> lot
    snap_ambiguous: dict[int, float] = field(default_factory=dict)  # camera_id -> axis offset
    unresolved_dropped: list[CameraInput] = field(default_factory=list)  # far from roads, no lot found


LANDUSE_FILTER = '["landuse"~"^(retail|commercial|industrial)$"]'
AREA_MARGIN_DEG = 0.02  # ~2 km; large areas must have outline nodes inside the box


def build_query(points: list[tuple[float, float]]) -> str:
    """Service roads and nearby lot polygons around each (lat, lon)."""
    parts = []
    for lat, lon in sorted(points):
        parts.append(f'way(around:{SERVICE_SEARCH_M},{lat:.7f},{lon:.7f})["highway"="service"];')
        for f in ('["amenity"="parking"]', LANDUSE_FILTER, '["shop"]'):
            parts.append(f"wr(around:{LOT_SEARCH_M},{lat:.7f},{lon:.7f}){f};")
    return "[out:json][timeout:90];\n(\n" + "\n".join(parts) + "\n);\nout tags geom;"


def build_area_query(points: list[tuple[float, float]]) -> str:
    """All retail/commercial/industrial polygons in a box around the points.

    `around` measures distance to a polygon's outline, so a camera deep inside
    a large area (e.g. a business park) is missed by build_query. Fetching the
    areas by bounding box and testing containment locally covers that case
    without Overpass's is_in, which public instances often fail on.
    """
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    s, w = min(lats) - AREA_MARGIN_DEG, min(lons) - AREA_MARGIN_DEG
    n, e = max(lats) + AREA_MARGIN_DEG, max(lons) + AREA_MARGIN_DEG
    bbox = f"{s:.5f},{w:.5f},{n:.5f},{e:.5f}"
    return f"[out:json][timeout:90];\n(way({bbox}){LANDUSE_FILTER};rel({bbox}){LANDUSE_FILTER};);\nout tags geom;"


def _kind(tags: dict) -> str | None:
    if tags.get("highway") == "service":
        return "service"
    if tags.get("landuse") in ("retail", "commercial", "industrial"):
        return tags["landuse"]
    if tags.get("amenity") == "parking":
        return "parking"
    if "shop" in tags:
        return "shop"
    return None


def parse_features(response: dict, to_proj: Transformer) -> list[OsmFeature]:
    project = lambda g: shapely.transform(g, to_proj.transform, interleaved=False)  # noqa: E731
    features = []
    for el in response.get("elements", []):
        tags = el.get("tags", {})
        kind = _kind(tags)
        if kind is None:
            continue
        geom: BaseGeometry | None = None
        if el["type"] == "way" and len(el.get("geometry", [])) >= 2:
            coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if kind == "service":
                geom = LineString(coords)
            elif len(coords) >= 4 and coords[0] == coords[-1]:
                geom = Polygon(coords)
        elif el["type"] == "relation" and kind != "service":
            outers = [
                LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                for m in el.get("members", [])
                if m.get("type") == "way" and m.get("role") == "outer" and len(m.get("geometry", [])) >= 2
            ]
            polys = list(polygonize(outers))
            if polys:
                geom = unary_union(polys)
        if geom is None or geom.is_empty or not geom.is_valid:
            continue
        features.append(OsmFeature(f"{el['type']}/{el['id']}", kind, tags, geom, project(geom)))
    return features


def fetch_lot_features(
    cameras: list[CameraInput], cache: RawCache, index: EdgeIndex, overpass: OverpassClient | None = None,
    refresh: bool = False,
) -> list[OsmFeature]:
    if not cameras:
        return []
    points = [(c.lat, c.lon) for c in cameras]
    client = overpass or OverpassClient()
    features: dict[str, OsmFeature] = {}
    for query in (build_query(points), build_area_query(points)):
        response = cache.get_or_fetch(query, lambda q=query: client.fetch(q), refresh=refresh)
        for f in parse_features(response, index.to_proj):
            features.setdefault(f.osm_id, f)
    return list(features.values())


def _local_axis(line: LineString, pt: Point, index: EdgeIndex) -> float:
    return index.bearing_at(line, line.project(pt))


def access_edge(index: EdgeIndex, cam: CameraInput) -> tuple[tuple[int, int, int], float]:
    """The public drive edge nearest the camera: where its driveway meets the road network."""
    pt = index.project_point(cam.lon, cam.lat)
    i = int(index.tree.query_nearest(pt)[0])
    return index.keys[i], index.geoms[i].distance(pt)


def outward_bearing(index: EdgeIndex, cam: CameraInput) -> float:
    """Bearing from the camera to the nearest point on the public drive network."""
    pt = index.project_point(cam.lon, cam.lat)
    i = int(index.tree.query_nearest(pt)[0])
    line = index.geoms[i]
    target = line.interpolate(line.project(pt))
    lon, lat = index.to_wgs.transform(target.x, target.y)
    return geodesic_bearing(cam.lon, cam.lat, lon, lat)


def facings_for(directions: list[float] | None, outward: float) -> list[str] | None:
    if not directions:
        return None
    return ["toward_road" if angle_diff(d, outward) < 90 else "into_lot" for d in directions]


def _pick_lot(pt: Point, polygons: list[OsmFeature], watched: OsmFeature | None) -> OsmFeature | None:
    def score(f: OsmFeature):
        touches = f.geom.contains(pt) or (watched is not None and f.geom.intersects(watched.geom))
        return (0 if touches else 1, LOT_KIND_PRIORITY.index(f.kind), f.geom.distance(pt))

    near = [f for f in polygons if f.geom.distance(pt) <= LOT_SEARCH_M]
    return min(near, key=score) if near else None


def classify(
    results: list[SnapResult],
    features: list[OsmFeature],
    index: EdgeIndex,
    alt_directions: dict[int, list[float]] | None = None,
) -> Classification:
    alt_directions = alt_directions or {}
    service = [f for f in features if f.kind == "service"]
    polygons = [f for f in features if f.kind in LOT_KIND_PRIORITY]
    service_tree = STRtree([f.geom for f in service]) if service else None
    out = Classification()

    for r in results:
        cam = r.camera
        pt = index.project_point(cam.lon, cam.lat)
        offset = road_axis_offset(r)

        watched = None
        if cam.directions_deg and service_tree is not None:
            near = [service[int(i)] for i in service_tree.query(pt, predicate="dwithin", distance=SERVICE_WITHIN_M)]
            parallel = [
                f for f in near
                if min(axis_diff(_local_axis(f.geom, pt, index), d) for d in cam.directions_deg) <= PARALLEL_DEG
            ]
            watched = min(parallel, key=lambda f: f.geom.distance(pt)) if parallel else None

        if r.dropped:
            lot = _pick_lot(pt, polygons, watched)
            if lot is None:
                out.unresolved_dropped.append(cam)
                continue
            reason = "dropped"
        elif offset is not None and offset > PERPENDICULAR_DEG and watched is not None:
            lot = _pick_lot(pt, polygons, watched)
            reason = "driveway"
        else:
            if offset is not None and offset > PERPENDICULAR_DEG:
                out.snap_ambiguous[cam.camera_id] = offset
            continue

        outward = outward_bearing(index, cam)
        edge, edge_d = access_edge(index, cam)
        out.lots[cam.camera_id] = LotAssignment(
            camera=cam,
            lot=lot,
            watched_way=watched,
            facings=facings_for(cam.directions_deg, outward) or [],
            alt_facings=facings_for(alt_directions.get(cam.camera_id), outward),
            reason=reason,
            access_edge=edge,
            access_distance_m=edge_d,
        )
    return out
