"""Route a trip and decide which cameras capture it.

Cameras are held in a CameraSet (indexed by directed edge for
public-road cameras, plus a list of lot cameras with their polygons).
simulate_trip then routes the trip and returns ground-truth camera passes,
each marked captured or not with a reason.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from platetrail.geo import WGS84
from platetrail.sim.matcher import (
    LotEntrance,
    LotEvent,
    MatchConfig,
    Reason,
    choose_directions,
    choose_facings,
    edge_decision,
    lot_decision,
)
from platetrail.sim.routing import EdgeKey, Route, Router


@dataclass(frozen=True)
class CameraEdge:
    edge: EdgeKey
    fraction_along: float
    bearing_deg: float  # travel bearing along the edge at the camera


@dataclass
class SimCamera:
    camera_id: int
    label: str
    kind: str  # public_road / private_lot
    directions_deg: list[float] | None
    alt_directions_deg: list[float] | None = None
    snap_ambiguous: bool = False
    edges: list[CameraEdge] = field(default_factory=list)
    lot_geom: BaseGeometry | None = None
    lot_id: str | None = None  # OSM id of the lot polygon; cameras sharing it share entrances
    access_node: int | None = None  # lot entrance junction the camera watches
    lot_name: str | None = None
    lon: float | None = None
    lat: float | None = None
    facings: list[str] | None = None
    alt_facings: list[str] | None = None

    @property
    def direction_ambiguous(self) -> bool:
        return self.alt_directions_deg is not None


class CameraSet:
    def __init__(self, cameras: list[SimCamera]):
        self.by_id = {c.camera_id: c for c in cameras}
        self.by_edge: dict[EdgeKey, list[tuple[SimCamera, CameraEdge]]] = defaultdict(list)
        for c in cameras:
            for ce in c.edges:
                self.by_edge[ce.edge].append((c, ce))
        self.lots = [c for c in cameras if c.kind == "private_lot" and c.lot_geom is not None]
        self.lot_groups: dict[str, list[SimCamera]] = defaultdict(list)
        for c in self.lots:
            self.lot_groups[c.lot_id or f"camera/{c.camera_id}"].append(c)


@dataclass(frozen=True)
class CameraPass:
    camera_id: int
    label: str
    time: datetime
    event: str  # "road", "arrival", "departure"
    travel_bearing_deg: float | None  # None for lot events
    edge: EdgeKey | None
    road_name: str | None
    captured: bool
    reason: Reason


@dataclass
class TripResult:
    route: Route
    passes: list[CameraPass]

    @property
    def captured(self) -> list[CameraPass]:
        return [p for p in self.passes if p.captured]


def match_route(
    route: Route,
    cameras: CameraSet,
    origin: tuple[float, float],
    dest: tuple[float, float],
    cfg: MatchConfig,
) -> list[CameraPass]:
    passes: list[CameraPass] = []
    for re in route.edges:
        for cam, ce in cameras.by_edge.get(re.edge, []):
            if not re.covers(ce.fraction_along):
                continue  # camera is on the part of the edge not driven (trip starts/ends mid-edge)
            dirs = choose_directions(cam.directions_deg, cam.alt_directions_deg, cfg)
            decision = edge_decision(dirs, ce.bearing_deg, cfg)
            offset = re.enter_offset_s + (ce.fraction_along - re.frac_from) * re.full_travel_time_s
            t = route.depart + timedelta(seconds=offset)
            passes.append(
                CameraPass(cam.camera_id, cam.label, t, "road", ce.bearing_deg, re.edge, re.name,
                           decision.captured, decision.reason)
            )

    events = (
        (LotEvent.DEPARTURE, Point(origin), route.depart, route.coords[0], "origin"),
        (LotEvent.ARRIVAL, Point(dest), route.arrive, route.coords[-1], "dest"),
    )
    for group in cameras.lot_groups.values():
        for event, pt, t, network_end, end in events:
            if not group[0].lot_geom.covers(pt):
                continue
            seen = group
            if cfg.lot_entrance is LotEntrance.ACCESS_ROAD:
                # Only cameras at the entrance the route actually uses (approach direction) see it.
                seen = [c for c in group if c.access_node is not None and c.access_node in _entrance_nodes(route, end)]
            elif cfg.lot_entrance is LotEntrance.NEAREST and len(group) > 1:
                seen = [min(group, key=lambda c: _distance_m(c, network_end))]
            for cam in seen:
                decision = lot_decision(choose_facings(cam.facings, cam.alt_facings, cfg), event, cfg)
                passes.append(
                    CameraPass(cam.camera_id, cam.label, t, event.value, None, None, cam.lot_name,
                               decision.captured, decision.reason)
                )
    return sorted(passes, key=lambda p: (p.time, p.camera_id))


def _entrance_nodes(route: Route, end: str) -> set[int]:
    """Nodes where this end of the route enters the lot.

    Normally the single junction where the route turns from a public road
    onto service roads. If the place sits directly on a public edge (no
    service roads at that end), the endpoints of that edge stand in.
    """
    node = route.lot_entry_node(end)
    if node is not None:
        return {node}
    edge = route.origin.edge if end == "origin" else route.dest.edge
    return {edge[0], edge[1]}


def _distance_m(cam: SimCamera, lonlat: tuple[float, float]) -> float:
    if cam.lon is None:
        return float("inf")
    return WGS84.inv(cam.lon, cam.lat, lonlat[0], lonlat[1])[2]


def simulate_trip(
    router: Router,
    cameras: CameraSet,
    origin: tuple[float, float],
    dest: tuple[float, float],
    depart: datetime,
    cfg: MatchConfig | None = None,
    use_cache: bool = True,
) -> TripResult:
    """origin/dest are (lon, lat)."""
    cfg = cfg or MatchConfig()
    route = router.route(origin, dest, depart, use_cache)
    return TripResult(route, match_route(route, cameras, origin, dest, cfg))
