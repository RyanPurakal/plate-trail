"""Download, cache, and store the drive network for the study area.

The study area is the union of the configured region's town boundaries or
boxes (platetrail.region; the default is Edison and New Brunswick, NJ), buffered so
routes that briefly leave town (in the default region: Route 1, the Turnpike,
I-287) stay on the graph.

The network is OSMnx's drive network plus service roads, except parking
aisles, drive-throughs, emergency access and private roads (CUSTOM_FILTER).
Service roads are needed to reach places inside large lots and business
parks: Raritan Center's internal streets are all tagged highway=service.
Their speed is set to SERVICE_SPEED_KPH, and the router penalizes them for
through traffic (sim.routing) so routes don't cut through lots. The graph is cached as GraphML; OSMnx's own HTTP cache
also lives under the data dir so a rebuild doesn't refetch.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import MultiPolygon, Polygon, box
from sqlalchemy import Engine, text

from platetrail.config import get_settings
from platetrail.region import DEFAULT_REGION, Region, get_region

NETWORK_TYPE = "drive_service"  # label for the cache file; the actual filter is CUSTOM_FILTER
# OSMnx's drive_service filter, additionally excluding parking aisles and drive-throughs.
CUSTOM_FILTER = (
    '["highway"]["area"!~"yes"]["access"!~"private"]'
    '["highway"!~"abandoned|bridleway|bus_guideway|construction|corridor|cycleway|elevator|escalator|footway|no|'
    'path|pedestrian|planned|platform|proposed|raceway|razed|rest_area|services|steps|track"]'
    '["motor_vehicle"!~"no"]["motorcar"!~"no"]'
    '["service"!~"emergency_access|parking_aisle|private|drive-through|drive_through"]'
)
# ASSUMPTION: free-flow speed on service roads (lot entrances, business-park streets).
SERVICE_SPEED_KPH = 15.0


def _configure_osmnx(data_dir: Path) -> None:
    ox.settings.cache_folder = str(data_dir / "osmnx_cache")
    ox.settings.use_cache = True
    ox.settings.requests_timeout = 300
    ox.settings.log_console = False


def graph_path(data_dir: Path, region_id: str | None = None) -> Path:
    region_id = region_id or get_region().id
    # The default region keeps its original, unsuffixed cache file.
    suffix = "" if region_id == DEFAULT_REGION else f"_{region_id}"
    return data_dir / "graphs" / f"study_area_{NETWORK_TYPE}{suffix}.graphml"


def town_polygons(region: Region | None = None) -> dict[str, Polygon | MultiPolygon]:
    """Town label -> lon/lat outline: its OSM boundary relation, or its box. In region order."""
    region = region or get_region()
    shapes = {label: box(*bbox) for label, bbox in region.bboxes.items()}
    relations = region.relations
    if relations:
        gdf = ox.geocode_to_gdf([f"R{rid}" for rid in relations.values()], by_osmid=True)
        shapes.update(zip(relations, gdf.geometry))
    return {t.label: shapes[t.label] for t in region.towns}


def study_area_polygon(buffer_m: float | None = None) -> Polygon | MultiPolygon:
    region = get_region()
    buffer_m = region.buffer_m if buffer_m is None else buffer_m
    gdf = gpd.GeoDataFrame(geometry=list(town_polygons(region).values()), crs="EPSG:4326")
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

    G = ox.graph_from_polygon(study_area_polygon(), custom_filter=CUSTOM_FILTER, truncate_by_edge=True)
    G = ox.add_edge_speeds(G, hwy_speeds={"service": SERVICE_SPEED_KPH})
    G = ox.add_edge_travel_times(G)
    path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, path)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "built_at": datetime.now(timezone.utc).isoformat(),
                "region": get_region().id,
                "relations": get_region().relations,
                **({"bboxes": get_region().bboxes} if get_region().bboxes else {}),
                "buffer_m": get_region().buffer_m,
                "network_type": NETWORK_TYPE,
                "custom_filter": CUSTOM_FILTER,
                "service_speed_kph": SERVICE_SPEED_KPH,
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
