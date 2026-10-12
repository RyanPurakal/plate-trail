"""Shortest-travel-time routing on the drive graph.

Origins and destinations snap to the nearest graph node inside the largest
strongly connected component, so every origin/destination pair is routable.
Departure time only stamps timestamps; there is no traffic model, so travel
times are free-flow (OSMnx speed_kph from maxspeed tags or highway-type
defaults).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import networkx as nx
import osmnx as ox
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, Point

EdgeKey = tuple[int, int, int]


@dataclass(frozen=True)
class RouteEdge:
    edge: EdgeKey
    length_m: float
    travel_time_s: float
    enter_offset_s: float  # seconds after departure when the edge is entered
    name: str | None


@dataclass
class Route:
    origin_node: int
    dest_node: int
    origin_snap_m: float
    dest_snap_m: float
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


class NoRoute(RuntimeError):
    pass


def _edge_name(data: dict) -> str | None:
    name = data.get("name")
    if isinstance(name, list):
        return ";".join(map(str, name))
    return name if isinstance(name, str) else None


class Router:
    def __init__(self, G: nx.MultiDiGraph):
        """G: unprojected (EPSG:4326) graph with travel_time and length on edges."""
        self.G = G
        crs = ox.projection.project_gdf(ox.graph_to_gdfs(G, edges=False).head(1)).crs
        self.to_proj = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        core = max(nx.strongly_connected_components(G), key=len)
        self.nodes = sorted(core)
        self.node_points = [Point(*self.to_proj.transform(G.nodes[n]["x"], G.nodes[n]["y"])) for n in self.nodes]
        self.node_tree = STRtree(self.node_points)

    def nearest_node(self, lon: float, lat: float) -> tuple[int, float]:
        pt = Point(*self.to_proj.transform(lon, lat))
        i = int(self.node_tree.query_nearest(pt)[0])
        return self.nodes[i], self.node_points[i].distance(pt)

    def _best_key(self, u: int, v: int) -> tuple[int, dict]:
        return min(self.G[u][v].items(), key=lambda kv: kv[1]["travel_time"])

    def _edge_coords(self, u: int, v: int, data: dict) -> list[tuple[float, float]]:
        geom = data.get("geometry")
        if isinstance(geom, LineString):
            return list(geom.coords)
        return [(self.G.nodes[u]["x"], self.G.nodes[u]["y"]), (self.G.nodes[v]["x"], self.G.nodes[v]["y"])]

    def route(self, origin: tuple[float, float], dest: tuple[float, float], depart: datetime) -> Route:
        """origin/dest are (lon, lat)."""
        o, o_m = self.nearest_node(*origin)
        d, d_m = self.nearest_node(*dest)
        try:
            path = nx.shortest_path(self.G, o, d, weight="travel_time")
        except nx.NetworkXNoPath as e:  # shouldn't happen inside one SCC
            raise NoRoute(f"no route from {o} to {d}") from e

        edges, coords, t = [], [(self.G.nodes[o]["x"], self.G.nodes[o]["y"])], 0.0
        for u, v in zip(path, path[1:]):
            k, data = self._best_key(u, v)
            edges.append(
                RouteEdge((u, v, k), float(data["length"]), float(data["travel_time"]), t, _edge_name(data))
            )
            t += float(data["travel_time"])
            coords.extend(self._edge_coords(u, v, data)[1:])
        return Route(o, d, o_m, d_m, depart, edges, coords)
