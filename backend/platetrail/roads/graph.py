"""Download, cache, and store the drive network for the study area.

The study area is the union of the Edison and New Brunswick boundaries,
buffered so routes that briefly leave town (Route 1, the Turnpike, I-287)
stay on the graph. The graph is cached as GraphML; OSMnx's own HTTP cache
also lives under the data dir so a rebuild doesn't refetch.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import osmnx as ox
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import Engine, text

from platetrail.config import get_settings

# OSM boundary relations (confirmed by the camera ETL's Overpass responses).
STUDY_AREA_RELATIONS = {"Edison": 171019, "New Brunswick": 170536}
BUFFER_M = 2000.0
NETWORK_TYPE = "drive"


def _configure_osmnx(data_dir: Path) -> None:
    ox.settings.cache_folder = str(data_dir / "osmnx_cache")
    ox.settings.use_cache = True
    ox.settings.requests_timeout = 300
    ox.settings.log_console = False


def graph_path(data_dir: Path) -> Path:
    return data_dir / "graphs" / f"study_area_{NETWORK_TYPE}.graphml"


def study_area_polygon(buffer_m: float = BUFFER_M) -> Polygon | MultiPolygon:
    gdf = ox.geocode_to_gdf([f"R{rid}" for rid in STUDY_AREA_RELATIONS.values()], by_osmid=True)
    utm = gdf.to_crs(gdf.estimate_utm_crs())
    area = utm.union_all().buffer(buffer_m)
    return utm.__class__(geometry=[area], crs=utm.crs).to_crs("EPSG:4326").geometry.iloc[0]


def load_or_build_graph(refresh: bool = False, data_dir: Path | None = None) -> nx.MultiDiGraph:
    """Unprojected (EPSG:4326) drive graph with speed_kph and travel_time on edges."""
    data_dir = data_dir or get_settings().data_dir
    _configure_osmnx(data_dir)
    path = graph_path(data_dir)
    if path.exists() and not refresh:
        return ox.load_graphml(path)

    G = ox.graph_from_polygon(study_area_polygon(), network_type=NETWORK_TYPE, truncate_by_edge=True)
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, path)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "built_at": datetime.now(timezone.utc).isoformat(),
                "relations": STUDY_AREA_RELATIONS,
                "buffer_m": BUFFER_M,
                "network_type": NETWORK_TYPE,
                "osmnx_version": ox.__version__,
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
            },
            indent=1,
        )
    )
    return G


def _as_text(value) -> str | None:
    """OSMnx merges attributes into lists on simplified edges; flatten for storage."""
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return None
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    return str(value)


def store_edges(engine: Engine, G: nx.MultiDiGraph) -> int:
    """Replace road_edges (and, by cascade, camera_edges) with G's edges."""
    edges = ox.graph_to_gdfs(G, nodes=False).reset_index()
    rows = [
        {
            "u": int(r.u),
            "v": int(r.v),
            "key": int(r.key),
            "osmid": _as_text(r.osmid),
            "name": _as_text(getattr(r, "name", None)),
            "highway": _as_text(r.highway),
            "oneway": bool(r.oneway),
            "length_m": float(r.length),
            "speed_kph": float(r.speed_kph),
            "travel_time_s": float(r.travel_time),
            "wkt": r.geometry.wkt,
        }
        for r in edges.itertuples(index=False)
    ]
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE road_edges CASCADE"))
        conn.execute(
            text(
                "INSERT INTO road_edges (u, v, key, osmid, name, highway, oneway, length_m, speed_kph,"
                " travel_time_s, geom) VALUES (:u, :v, :key, :osmid, :name, :highway, :oneway, :length_m,"
                " :speed_kph, :travel_time_s, ST_GeomFromText(:wkt, 4326))"
            ),
            rows,
        )
    return len(rows)
