"""Route checks anywhere: a small drive network built around one route, on demand.

There is no prebuilt road graph or camera table, so the check builds both for
a box around the route's two ends:

* roads: OSMnx drive network for the box (filter and speeds from
  platetrail.roads.graph), fetched with OSMnx's disk cache and logging
  switched off;
* sensors: the same public sensors GET /area serves (OSM plus the region's
  file sources), snapped to those roads with direction-aware snapping
  (platetrail.roads.snap).

The box follows the visitor's route, so it is treated like the route
itself: nothing about it is written to disk or logged. A fresh /area cache
entry for the box is read if one exists (it is never created or refreshed
here), and built networks are held in memory only, a few at a time for an
hour, so checking a route and its return trip doesn't refetch the roads.
Checks that need the same uncached box at the same time share one build.
"""

import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import httpx
import networkx as nx
import osmnx as ox

from platetrail.area import (
    MAX_AGE,
    OSM_SOURCE,
    AreaError,
    area_cache,
    build_area_query,
    file_area_features,
    merge_listed_twice,
    parse_area_response,
    source_priority,
    snap_bbox,
)
from platetrail.etl.cache import RawCache
from platetrail.etl.loaders.overpass import OverpassClient
from platetrail.region import get_region
from platetrail.roads.graph import CUSTOM_FILTER, SERVICE_SPEED_KPH
from platetrail.roads.snap import CameraInput, EdgeIndex, snap_with_service_fallback
from platetrail.sim.routing import NoRoute, Router
from platetrail.sim.trip import CameraEdge, CameraSet, SimCamera

BBox = tuple[float, float, float, float]

ROUTE_PAD_M = 2000.0  # roads this far beyond the route's ends are included, for detours
MAX_ROUTE_SPAN_DEG = 0.3  # about 25-33 km; larger boxes make the road download too slow
NETWORK_CACHE_SIZE = 4
NETWORK_CACHE_TTL_S = 3600.0
_OSMNX_LOCK = threading.Lock()  # ox.settings is global; keep the switch-off atomic
_OSMNX_OFF = ("use_cache", "log_file", "log_console")  # settings held off while fetching a route box


@dataclass
class AreaNetwork:
    bbox: BBox
    router: Router
    cameras: CameraSet
    sensors_mapped: int  # public sensors in the box
    sensors_on_roads: int  # of those, within snapping distance of a road (the rest can't be passed)
    sources: list[dict]


def route_bbox(start: tuple[float, float], end: tuple[float, float], pad_m: float = ROUTE_PAD_M) -> BBox:
    """Box around both (lon, lat) ends, padded and snapped to the /area grid. AreaError if too large."""
    lat_mid = (start[1] + end[1]) / 2
    dlat = pad_m / 110_540.0
    dlon = pad_m / (111_320.0 * max(math.cos(math.radians(lat_mid)), 0.01))
    w, e = min(start[0], end[0]) - dlon, max(start[0], end[0]) + dlon
    s, n = min(start[1], end[1]) - dlat, max(start[1], end[1]) + dlat
    bbox = snap_bbox((max(w, -180.0), max(s, -90.0), min(e, 180.0), min(n, 90.0)))
    if bbox[2] - bbox[0] > MAX_ROUTE_SPAN_DEG or bbox[3] - bbox[1] > MAX_ROUTE_SPAN_DEG:
        raise AreaError("this route is too long to check; "
                        "routes up to about 25 km end to end are supported")
    return bbox


def fetch_drive_graph(bbox: BBox) -> nx.MultiDiGraph:
    """OSMnx drive network for bbox, with OSMnx's disk cache and logging off. NoRoute if the box has no roads.

    OSMnx logs each Overpass query in full (box included) when log_file or
    log_console is on, so both are switched off for the fetch like the cache.
    """
    with _OSMNX_LOCK:
        previous = {name: getattr(ox.settings, name) for name in _OSMNX_OFF}
        for name in _OSMNX_OFF:
            setattr(ox.settings, name, False)
        try:
            G = ox.graph_from_bbox(bbox, custom_filter=CUSTOM_FILTER, truncate_by_edge=True)
        except (ox._errors.InsufficientResponseError, ValueError) as e:
            raise NoRoute("no mapped roads near this route") from e
        finally:
            for name, value in previous.items():
                setattr(ox.settings, name, value)
    G = ox.add_edge_speeds(G, hwy_speeds={"service": SERVICE_SPEED_KPH})
    return ox.add_edge_travel_times(G)


def fetch_sensors(bbox: BBox, cache: RawCache | None = None, client: OverpassClient | None = None,
                  now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Public sensors in bbox (GeoJSON features) and source credits, without writing any cache.

    A fresh /area cache entry is used as is; otherwise Overpass is asked
    directly, falling back to a stale entry if that fails.
    """
    cache = cache or area_cache()
    now = now or datetime.now(timezone.utc)
    query = build_area_query(bbox)
    fetched_at = cache.fetched_at(query)
    if fetched_at is not None and now - fetched_at <= MAX_AGE:
        response = cache.get_or_fetch(query, _never)  # an existing entry is only read
    else:
        try:
            response = (client or OverpassClient(attempts_per_url=2, backoff_s=2.0)).fetch(query)
            fetched_at = now
        except (RuntimeError, httpx.HTTPError):
            if fetched_at is None:
                raise
            response = cache.get_or_fetch(query, _never)
    region = get_region()
    file_features, file_sources = file_area_features(bbox, region)
    # a sensor listed by OSM and a file is one sensor, as in GET /area
    features, _ = merge_listed_twice(parse_area_response(response) + file_features, source_priority(region))
    sources = [{**OSM_SOURCE, "fetched_at": fetched_at.isoformat()}]
    sources += [{"id": fs["id"], "name": fs["name"], "license": None, "url": None, "fetched_at": fs["updated_at"]}
                for fs in file_sources]
    return features, sources


def _never():
    raise RuntimeError("cache entry disappeared")


def build_camera_set(router: Router, features: list[dict]) -> tuple[CameraSet, int]:
    """Snap sensor features to the router's roads; returns the set and how many sensors snapped."""
    inputs = [
        CameraInput(i, f["properties"]["id"], *f["geometry"]["coordinates"], f["properties"]["directions_deg"])
        for i, f in enumerate(features, start=1)
    ]
    G_proj = ox.project_graph(router.G)
    results, _ = snap_with_service_fallback(EdgeIndex(G_proj, public_only=True),
                                            EdgeIndex(G_proj, service_only=True), inputs)
    cameras = [
        SimCamera(
            camera_id=r.camera.camera_id,
            label=r.camera.label,
            kind="public_road",
            directions_deg=r.camera.directions_deg,
            edges=[CameraEdge(s.edge, s.fraction_along, s.bearing_deg) for s in r.snaps],
            lon=r.camera.lon,
            lat=r.camera.lat,
        )
        for r in results
        if not r.dropped
    ]
    return CameraSet(cameras), len(cameras)


class _Build:
    """One network build in progress; checks for the same box wait on it."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.network: AreaNetwork | None = None
        self.error: BaseException | None = None


class AreaNetworks:
    """Builds route networks on demand and keeps the last few in memory (never on disk).

    Route checks run in FastAPI's thread pool, so a route's two directions,
    a compare of two nearby routes or a re-check from another tab can ask for
    the same uncached box at once. Only the first builds it (one road
    download, one sensor fetch); the others wait and share its network or
    its error, which is not cached, so a later check tries again.
    """

    def __init__(
        self,
        fetch_graph: Callable[[BBox], nx.MultiDiGraph] = fetch_drive_graph,
        fetch_features: Callable[[BBox], tuple[list[dict], list[dict]]] = fetch_sensors,
        size: int = NETWORK_CACHE_SIZE,
        ttl_s: float = NETWORK_CACHE_TTL_S,
    ):
        self.fetch_graph = fetch_graph
        self.fetch_features = fetch_features
        self.size = size
        self.ttl_s = ttl_s
        self._cache: OrderedDict[BBox, tuple[float, AreaNetwork]] = OrderedDict()
        self._lock = threading.Lock()
        self._building: dict[BBox, _Build] = {}

    def for_route(self, start: tuple[float, float], end: tuple[float, float]) -> AreaNetwork:
        bbox = route_bbox(start, end)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(bbox)
            if hit and now - hit[0] <= self.ttl_s:
                self._cache.move_to_end(bbox)
                return hit[1]
            build = self._building.get(bbox)
            leader = build is None
            if leader:
                build = self._building[bbox] = _Build()
        if not leader:
            build.done.wait()
            if build.error is not None:
                raise build.error
            return build.network
        try:
            build.network = self.build(bbox)
        except BaseException as e:
            build.error = e
            raise
        finally:
            with self._lock:
                del self._building[bbox]
                if build.network is not None:
                    self._cache[bbox] = (now, build.network)
                    self._cache.move_to_end(bbox)
                    while len(self._cache) > self.size:
                        self._cache.popitem(last=False)
            build.done.set()
        return build.network

    def build(self, bbox: BBox) -> AreaNetwork:
        router = Router(self.fetch_graph(bbox))
        features, sources = self.fetch_features(bbox)
        cameras, on_roads = build_camera_set(router, features)
        return AreaNetwork(bbox, router, cameras, len(features), on_roads, sources)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


_networks: AreaNetworks | None = None


def get_area_networks() -> AreaNetworks:
    global _networks
    if _networks is None:
        _networks = AreaNetworks()
    return _networks
