"""Shortest-travel-time routing between points on the drive graph.

Origins and destinations snap to the nearest point on an edge (not the
nearest node) inside the largest strongly connected component, so every
pair is routable. The route begins and ends with partial edges. A camera on
an edge counts only if it lies on the part actually driven: a trip starting
mid-block doesn't "pass" a camera behind it.

Points farther than MAX_ATTACH_M from any edge are rejected (AnchorTooFar).
That is a data guard; normal places are within tens of metres.

Service roads (lot entrances, business-park streets) are in the graph so
places inside lots are reachable. Route choice multiplies their travel time
by SERVICE_ROUTING_PENALTY so through traffic stays on public roads and only
uses service roads to get into or out of a place. Timestamps use real
travel times.

Departure time only stamps timestamps; there is no traffic model, so travel
times are free-flow (OSMnx speed_kph from maxspeed tags or highway defaults).
Because routes don't depend on departure time, they are cached by
(origin point, destination point) in platetrail.cache: in-process, or shared
via Redis across API and worker processes. The key includes a fingerprint
of the graph's edges and routing costs.

Two interchangeable search backends find the path (PLATETRAIL_ROUTER, or
Router(G, backend=...)):
* "cpp" (default when built): platetrail._fastroute, a C++ Dijkstra over a CSR
  copy of the graph that reproduces networkx's tie-breaking, so it returns the
  identical path and cost (tests/test_routing_parity.py);
* "python": networkx.single_source_dijkstra, the reference implementation.
Everything around the search (snapping, path assembly, geometry) is shared.
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.ops import substring

from platetrail.cache import MISSING, get_cache
from platetrail.roads.snap import EdgeIndex, is_service

EdgeKey = tuple[int, int, int]
MAX_ATTACH_M = 500.0
# ASSUMPTION: route-choice cost multiplier for service roads (not applied to timestamps).
SERVICE_ROUTING_PENALTY = 4.0
_O, _D = "__origin__", "__dest__"
BACKENDS = ("cpp", "python")
log = logging.getLogger(__name__)

try:
    from platetrail import _fastroute
except ImportError:  # extension not built (e.g. a plain source checkout)
    _fastroute = None


def default_backend() -> str:
    """PLATETRAIL_ROUTER if set, else "cpp" when the extension is available, else "python"."""
    want = os.environ.get("PLATETRAIL_ROUTER", "").strip().lower()
    if want:
        if want not in BACKENDS:
            raise ValueError(f"PLATETRAIL_ROUTER must be one of {BACKENDS}, got {want!r}")
        return want
    return "cpp" if _fastroute is not None else "python"


@dataclass(frozen=True)
class EdgePoint:
    edge: EdgeKey  # directed edge whose geometry the point projects onto
    fraction: float  # 0 at u, 1 at v
    distance_m: float  # from the original point to the edge


@dataclass(frozen=True)
class RouteEdge:
    edge: EdgeKey
    length_m: float  # driven length
    travel_time_s: float  # driven time
    enter_offset_s: float  # seconds after departure when the driven part starts
    name: str | None
    frac_from: float = 0.0  # driven part of the edge, as fractions u->v
    frac_to: float = 1.0
    service: bool = False  # a service road (lot entrance, business-park street)

    @property
    def full_travel_time_s(self) -> float:
        span = self.frac_to - self.frac_from
        return self.travel_time_s / span if span > 0 else 0.0

    def covers(self, fraction: float) -> bool:
        return self.frac_from - 1e-9 <= fraction <= self.frac_to + 1e-9


@dataclass
class Route:
    origin: EdgePoint
    dest: EdgePoint
    depart: datetime
    edges: list[RouteEdge]
    coords: list[tuple[float, float]]  # (lon, lat) polyline

    @property
    def length_m(self) -> float:
        return sum(e.length_m for e in self.edges)

    @property
    def duration_s(self) -> float:
        return sum(e.travel_time_s for e in self.edges)

    @property
    def arrive(self) -> datetime:
        return self.depart + timedelta(seconds=self.duration_s)

    def lot_entry_node(self, end: str) -> int | None:
        """Junction where the route turns from a public road onto service roads to reach ("dest") or
        leave ("origin") the place, i.e. the entrance actually used. None if that end has no service roads."""
        seq = self.edges if end == "origin" else list(reversed(self.edges))
        if not seq or not seq[0].service:
            return None
        for e in seq:
            if not e.service:
                return e.edge[1] if end == "dest" else e.edge[0]
        return None

    @property
    def origin_snap_m(self) -> float:
        return self.origin.distance_m

    @property
    def dest_snap_m(self) -> float:
        return self.dest.distance_m


class NoRoute(RuntimeError):
    pass


class AnchorTooFar(ValueError):
    pass


def _edge_name(data: dict) -> str | None:
    name = data.get("name")
    if isinstance(name, list):
        return ";".join(map(str, name))
    return name if isinstance(name, str) else None


class Router:
    def __init__(self, G: nx.MultiDiGraph, backend: str | None = None):
        """G: unprojected (EPSG:4326) graph with travel_time and length on edges.
        backend: "cpp" or "python" (default: default_backend())."""
        core = max(nx.strongly_connected_components(G), key=len)
        self.G = G.subgraph(core).copy()
        for _, _, d in self.G.edges(data=True):
            d["_svc"] = is_service(d.get("highway"))
            d["_cost"] = float(d["travel_time"]) * (SERVICE_ROUTING_PENALTY if d["_svc"] else 1.0)
        self.index = EdgeIndex(ox.project_graph(self.G))
        h = hashlib.sha1()
        for u, v, k, d in sorted(self.G.edges(keys=True, data=True), key=lambda e: (e[0], e[1], e[2])):
            h.update(f"{u},{v},{k},{d['_cost']:.4f};".encode())
        self.fingerprint = h.hexdigest()[:16]
        self.cache_hits = 0
        self._edge_coords: dict[EdgeKey, list] = {}
        self.backend = backend or default_backend()
        if self.backend not in BACKENDS:
            raise ValueError(f"backend must be one of {BACKENDS}, got {self.backend!r}")
        if self.backend == "cpp" and _fastroute is None:
            log.warning("platetrail._fastroute is not built; routing falls back to the Python backend")
            self.backend = "python"
        self._csr = self._build_csr() if self.backend == "cpp" else None

    def _build_csr(self):
        """CSR copy of the graph for the C++ search: nodes in graph order, each node's neighbours in adjacency
        (insertion) order, parallel edges collapsed to their minimum _cost, exactly as networkx sees them."""
        nodes = list(self.G.nodes)
        index = {n: i for i, n in enumerate(nodes)}
        indptr, indices, weights = [0], [], []
        for n in nodes:
            for nbr, keyed in self.G._adj[n].items():
                indices.append(index[nbr])
                weights.append(min(d["_cost"] for d in keyed.values()))
            indptr.append(len(indices))
        graph = _fastroute.Graph(np.asarray(indptr, dtype=np.int64), np.asarray(indices, dtype=np.int32),
                                 np.asarray(weights, dtype=np.float64))
        return graph, nodes, index

    # ---- snapping ------------------------------------------------------------------

    def snap_point(self, lon: float, lat: float) -> EdgePoint:
        pt = self.index.project_point(lon, lat)
        i = int(self.index.tree.query_nearest(pt)[0])
        line = self.index.geoms[i]
        d = line.distance(pt)
        if d > MAX_ATTACH_M:
            raise AnchorTooFar(f"point ({lon:.5f}, {lat:.5f}) is {d:.0f} m from the nearest edge")
        frac = line.project(pt) / line.length if line.length else 0.0
        return EdgePoint(self.index.keys[i], min(max(frac, 0.0), 1.0), d)

    def nearest_node(self, lon: float, lat: float) -> tuple[int, float]:
        """Nearer endpoint of the snapped edge and its distance (diagnostics only)."""
        pt = self.index.project_point(lon, lat)
        u, v, _ = self.snap_point(lon, lat).edge
        dists = {n: Point(*self.index.to_proj.transform(self.G.nodes[n]["x"], self.G.nodes[n]["y"])).distance(pt)
                 for n in (u, v)}
        n = min(dists, key=dists.get)
        return n, dists[n]

    # ---- geometry helpers ------------------------------------------------------------

    def _data(self, e: EdgeKey) -> dict:
        return self.G[e[0]][e[1]][e[2]]

    def _reverse(self, e: EdgeKey) -> EdgeKey | None:
        """The opposite-direction edge with (nearly) the same geometry, if the road is two-way."""
        u, v, _ = e
        if not self.G.has_edge(v, u):
            return None
        length = self._data(e)["length"]
        k = min(self.G[v][u], key=lambda k: abs(self.G[v][u][k]["length"] - length))
        return (v, u, k) if abs(self.G[v][u][k]["length"] - length) < 1.0 else None

    def _geometry(self, e: EdgeKey) -> LineString:
        geom = self._data(e).get("geometry")
        if isinstance(geom, LineString):
            return geom
        u, v, _ = e
        return LineString([(self.G.nodes[u]["x"], self.G.nodes[u]["y"]), (self.G.nodes[v]["x"], self.G.nodes[v]["y"])])

    def _coords(self, e: EdgeKey) -> list:
        """The edge's coordinates, kept per edge: what substring(geometry, 0, 1) gives for an edge driven end to end."""
        c = self._edge_coords.get(e)
        if c is None:
            c = self._edge_coords[e] = list(self._geometry(e).coords)
        return c

    def _route_edge(self, e: EdgeKey, f0: float, f1: float, offset: float) -> RouteEdge:
        data = self._data(e)
        span = f1 - f0
        return RouteEdge(e, float(data["length"]) * span, float(data["travel_time"]) * span, offset,
                         _edge_name(data), f0, f1, bool(data.get("_svc")))

    # ---- routing -----------------------------------------------------------------------

    def _exits(self, p: EdgePoint) -> list[tuple[EdgeKey, float, float, int]]:
        """Ways to leave an origin point: (edge, frac_from, frac_to, node reached)."""
        out = [(p.edge, p.fraction, 1.0, p.edge[1])]
        rev = self._reverse(p.edge)
        if rev is not None:
            out.append((rev, 1.0 - p.fraction, 1.0, rev[1]))
        return out

    def _entries(self, p: EdgePoint) -> list[tuple[EdgeKey, float, float, int]]:
        """Ways to reach a destination point: (edge, frac_from, frac_to, node entered from)."""
        out = [(p.edge, 0.0, p.fraction, p.edge[0])]
        rev = self._reverse(p.edge)
        if rev is not None:
            out.append((rev, 0.0, 1.0 - p.fraction, rev[0]))
        return out

    def route_points(self, o: EdgePoint, d: EdgePoint, depart: datetime, use_cache: bool = True) -> Route:
        if not use_cache:  # e.g. "your week": user-entered places must not be persisted anywhere
            return self._compute(o, d, depart)
        key = f"route:{self.fingerprint}:{o.edge}:{o.fraction:.6f}:{d.edge}:{d.fraction:.6f}"
        cache = get_cache()
        hit = cache.get(key)
        if hit is not MISSING:
            self.cache_hits += 1
            edges, coords = hit
            return Route(o, d, depart, edges, coords)
        route = self._compute(o, d, depart)
        cache.set(key, (route.edges, route.coords), ttl_s=7 * 86400)
        return route

    def _search_cpp(self, exits, entries) -> tuple[float, list]:
        """C++ backend: the same virtual-origin/destination search as _compute's networkx call."""
        graph, nodes, index = self._csr

        def collapse(items):  # parallel virtual edges -> one edge at minimum cost, first-insertion order
            out: dict[int, float] = {}
            for e, f0, f1, node in items:
                c = self._data(e)["_cost"] * (f1 - f0)
                i = index[node]
                out[i] = min(out[i], c) if i in out else c
            return list(out.items())

        found = graph.shortest_path(collapse(exits), collapse(entries))
        if found is None:
            raise nx.NetworkXNoPath
        cost, path = found
        return cost, [_O, *(nodes[i] for i in path), _D]

    def _compute(self, o: EdgePoint, d: EdgePoint, depart: datetime) -> Route:
        exits, entries = self._exits(o), self._entries(d)
        G = self.G
        try:
            for e, f0, f1, node in exits:
                G.add_edge(_O, node, key=hash((e, "x")), _cost=self._data(e)["_cost"] * (f1 - f0), _via=(e, f0, f1))
            for e, f0, f1, node in entries:
                G.add_edge(node, _D, key=hash((e, "n")), _cost=self._data(e)["_cost"] * (f1 - f0), _via=(e, f0, f1))
            try:
                if self.backend == "cpp":
                    cost, path = self._search_cpp(exits, entries)
                else:
                    cost, path = nx.single_source_dijkstra(G, _O, _D, weight="_cost")
            except nx.NetworkXNoPath as err:
                raise NoRoute(f"no route from {o} to {d}") from err
            first = min(G[_O][path[1]].values(), key=lambda a: a["_cost"])["_via"]
            last = min(G[path[-2]][_D].values(), key=lambda a: a["_cost"])["_via"]
        finally:
            if _O in G:
                G.remove_node(_O)
            if _D in G:
                G.remove_node(_D)

        # Same edge, driving straight from origin to destination, can beat leaving and coming back.
        direct = None
        for e, f0, _, _ in exits:
            for e2, _, f1, _ in entries:
                if e == e2 and f1 >= f0:
                    t = self._data(e)["_cost"] * (f1 - f0)
                    if direct is None or t < direct[0]:
                        direct = (t, e, f0, f1)
        if direct is not None and direct[0] <= cost:
            pieces = [(direct[1], direct[2], direct[3])]
        else:
            pieces = [first]
            for u, v in zip(path[1:-2], path[2:-1]):
                k = min(G[u][v], key=lambda k: G[u][v][k]["_cost"])
                pieces.append(((u, v, k), 0.0, 1.0))
            pieces.append(last)

        edges, coords, t = [], [], 0.0
        for e, f0, f1 in pieces:
            if f1 - f0 <= 1e-9:
                continue  # zero-length partial edge at a node
            re_ = self._route_edge(e, f0, f1, t)
            edges.append(re_)
            t += re_.travel_time_s
            if f0 == 0.0 and f1 == 1.0:  # most edges: no substring needed (callers only copy from the list)
                seg_coords = self._coords(e)
            else:
                seg = substring(self._geometry(e), f0, f1, normalized=True)
                seg_coords = list(seg.coords) if seg.geom_type == "LineString" else [seg.coords[0]]
            coords.extend(seg_coords if not coords else seg_coords[1:])
        if not coords:
            g = self._geometry(o.edge).interpolate(o.fraction, normalized=True)
            coords = [(g.x, g.y)]
        return Route(o, d, depart, edges, coords)

    def route(self, origin: tuple[float, float], dest: tuple[float, float], depart: datetime,
              use_cache: bool = True) -> Route:
        """origin/dest are (lon, lat)."""
        return self.route_points(self.snap_point(*origin), self.snap_point(*dest), depart, use_cache)
