"""Load candidate anchor places from OSM and sample anchors for routines.

Places: shops, food, services, leisure, worship, workplaces, the university
and hospitals inside Edison and New Brunswick, from one cached Overpass
query. Each OSM element gets a single category by the priority in
_classify.

Homes are NOT taken from OSM buildings. Building coverage is incomplete and
uneven: 2.37 typed residential buildings per residential street way in
Edison vs 0.63 in New Brunswick (Overpass counts, 2026-10-12). Sampling
buildings would under-represent New Brunswick. Instead a home is a uniform
point on a residential street, with streets weighted by length (ASSUMPTION:
homes are spread in proportion to residential street length). Census
housing counts would be better and can replace this later.

    python -m platetrail.routines.places [--refresh]
"""

import argparse
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
import osmnx as ox
from shapely import wkb
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, unary_union
from sqlalchemy import Engine, text

from platetrail.config import get_settings
from platetrail.db import apply_migrations, get_engine
from platetrail.etl.cache import RawCache
from platetrail.etl.loaders.overpass import OverpassClient
from platetrail.geo import WGS84
from platetrail.region import get_region
from platetrail.roads.graph import _configure_osmnx

# Places farther than this from the drive network (service roads included) are
# not sampled as anchors. The user's requirement: snap or reject anchors more
# than ~100 m from the network. With service roads in the graph only 21 of
# 1,310 places exceed it.
MAX_PLACE_NETWORK_M = 100.0

GROCERY_SHOPS = {"supermarket", "convenience", "greengrocer", "butcher", "bakery", "deli", "grocery"}
FOOD = {"restaurant", "fast_food", "cafe", "bar", "pub", "ice_cream", "food_court"}
SERVICES = {"pharmacy", "bank", "post_office", "library", "townhall", "doctors", "dentist", "clinic"}
LEISURE = {"fitness_centre", "park", "sports_centre", "stadium", "swimming_pool"}
WORK_BUILDINGS = {"commercial", "office", "retail"}
INDUSTRIAL_BUILDINGS = {"industrial", "warehouse"}

# Places where people work. Shops, restaurants etc. employ people too.
WORK_CATEGORIES = ("work", "retail", "grocery", "food", "services", "hospital", "university", "industrial")


def build_query() -> str:
    area = ",".join(str(3600000000 + rid) for rid in get_region().relations.values())
    return f"""[out:json][timeout:180];
area(id:{area})->.a;
(
  nwr(area.a)["shop"];
  nwr(area.a)["amenity"~"^({'|'.join(sorted(FOOD | SERVICES | {'place_of_worship', 'hospital', 'university', 'college'}))})$"];
  nwr(area.a)["leisure"~"^({'|'.join(sorted(LEISURE))})$"];
  nwr(area.a)["office"];
  nwr(area.a)["building"~"^({'|'.join(sorted(WORK_BUILDINGS | INDUSTRIAL_BUILDINGS | {'university', 'college', 'hospital'}))})$"];
);
out center tags;"""


def _classify(tags: dict) -> tuple[str, str] | None:
    amenity, shop, building, leisure = tags.get("amenity"), tags.get("shop"), tags.get("building"), tags.get("leisure")
    # A campus building with its own amenity/shop (e.g. a post office) is classified by that instead.
    if amenity in ("university", "college") or (building in ("university", "college") and not amenity and not shop):
        return "university", amenity or building
    if amenity == "hospital" or building == "hospital":
        return "hospital", "hospital"
    if amenity == "place_of_worship":
        return "worship", tags.get("religion") or "place_of_worship"
    if shop:
        return ("grocery" if shop in GROCERY_SHOPS else "retail"), shop
    if amenity in FOOD:
        return "food", amenity
    if amenity in SERVICES:
        return "services", amenity
    if leisure in LEISURE:
        return "leisure", leisure
    if "office" in tags or building in WORK_BUILDINGS:
        return "work", tags.get("office") or building
    if building in INDUSTRIAL_BUILDINGS:
        return "industrial", building
    return None


def parse_places(response: dict) -> list[dict]:
    out = []
    for el in response.get("elements", []):
        tags = el.get("tags", {})
        cls = _classify(tags)
        if cls is None:
            continue
        if el["type"] == "node":
            lon, lat = el["lon"], el["lat"]
        elif "center" in el:
            lon, lat = el["center"]["lon"], el["center"]["lat"]
        else:
            continue
        out.append({"osm_id": f"{el['type']}/{el['id']}", "category": cls[0], "subcategory": cls[1],
                    "name": tags.get("name") or tags.get("brand"), "lon": lon, "lat": lat})
    return out


def load_towns(engine: Engine) -> None:
    _configure_osmnx(get_settings().data_dir)
    relations = get_region().relations
    gdf = ox.geocode_to_gdf([f"R{rid}" for rid in relations.values()], by_osmid=True)
    with engine.begin() as conn:
        for (name, rid), geom in zip(relations.items(), gdf.geometry):
            mp = geom if isinstance(geom, MultiPolygon) else MultiPolygon([geom])
            conn.execute(
                text("INSERT INTO towns (name, osm_id, geom) VALUES (:n, :o, ST_GeomFromText(:w, 4326))"
                     " ON CONFLICT (name) DO UPDATE SET osm_id = EXCLUDED.osm_id, geom = EXCLUDED.geom"),
                {"n": name, "o": f"relation/{rid}", "w": mp.wkt},
            )


def store_places(engine: Engine, places: list[dict]) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE places RESTART IDENTITY"))
        if places:
            conn.execute(
                text("INSERT INTO places (osm_id, category, subcategory, name, geom)"
                     " VALUES (:osm_id, :category, :subcategory, :name, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
                     " ON CONFLICT (osm_id) DO NOTHING"),
                places,
            )
        conn.execute(text("UPDATE places p SET town = t.name FROM towns t WHERE ST_Covers(t.geom, p.geom)"))
        conn.execute(text("DELETE FROM places WHERE town IS NULL"))
        conn.execute(text(
            "UPDATE places p SET attach_geom = p.geom, attach_method = 'centre', network_distance_m ="
            " (SELECT ST_Distance(p.geom::geography, e.geom::geography) FROM road_edges e"
            " ORDER BY e.geom <-> p.geom LIMIT 1)"))


def _outline(el: dict):
    """Polygon (or line) for an Overpass way/relation returned with `out geom`."""
    if el["type"] == "way" and len(el.get("geometry", [])) >= 2:
        coords = [(q["lon"], q["lat"]) for q in el["geometry"]]
        return Polygon(coords) if len(coords) >= 4 and coords[0] == coords[-1] else LineString(coords)
    if el["type"] == "relation":
        outers = [LineString([(q["lon"], q["lat"]) for q in m["geometry"]])
                  for m in el.get("members", []) if m.get("role") == "outer" and len(m.get("geometry", [])) >= 2]
        polys = list(polygonize(outers))
        return unary_union(polys) if polys else None
    return None


def attach_far_places_by_outline(engine: Engine, cache: RawCache, refresh: bool = False) -> list[dict]:
    """Re-attach places whose centre point is > MAX_PLACE_NETWORK_M from the network via their outline.

    Very large buildings (warehouses, fulfilment centres) have an OSM centre
    point deep inside the footprint, though they front a road. Their
    attachment point becomes the point on the outline nearest the network.
    Returns one row per re-attached place (name, category, before/after distance).
    """
    with engine.connect() as conn:
        far = conn.execute(text(
            "SELECT id, osm_id, name, category, network_distance_m d FROM places"
            " WHERE network_distance_m > :m AND osm_id !~ '^node/' ORDER BY id"), {"m": MAX_PLACE_NETWORK_M}).all()
    if not far:
        return []
    ways = [r.osm_id.split("/")[1] for r in far if r.osm_id.startswith("way/")]
    rels = [r.osm_id.split("/")[1] for r in far if r.osm_id.startswith("relation/")]
    parts = ([f"way(id:{','.join(ways)});"] if ways else []) + ([f"relation(id:{','.join(rels)});"] if rels else [])
    query = "[out:json][timeout:90];\n(" + "".join(parts) + ");\nout geom;"
    response = cache.get_or_fetch(query, lambda: OverpassClient().fetch(query), refresh=refresh)
    outlines = {f"{el['type']}/{el['id']}": g for el in response.get("elements", []) if (g := _outline(el)) is not None}

    changed = []
    with engine.begin() as conn:
        for r in far:
            g = outlines.get(r.osm_id)
            if g is None:
                continue
            boundary = g.boundary if g.geom_type in ("Polygon", "MultiPolygon") else g
            row = conn.execute(text(
                "WITH b AS (SELECT ST_GeomFromText(:w, 4326) g), e AS (SELECT geom FROM road_edges, b"
                " ORDER BY road_edges.geom <-> b.g LIMIT 1)"
                " SELECT ST_AsText(ST_ClosestPoint(b.g, e.geom)) pt,"
                " ST_Distance(ST_ClosestPoint(b.g, e.geom)::geography, e.geom::geography) d FROM b, e"),
                {"w": boundary.wkt}).one()
            conn.execute(text("UPDATE places SET attach_geom = ST_GeomFromText(:pt, 4326), attach_method = 'outline',"
                              " network_distance_m = :d WHERE id = :id"), {"pt": row.pt, "d": row.d, "id": r.id})
            changed.append({"name": r.name, "category": r.category, "before_m": r.d, "after_m": row.d})
    return changed


def run(refresh: bool = False, engine: Engine | None = None) -> str:
    engine = engine or get_engine()
    apply_migrations(engine)
    load_towns(engine)
    cache = RawCache(get_settings().data_dir / "raw" / "overpass_places")
    query = build_query()
    response = cache.get_or_fetch(query, lambda: OverpassClient().fetch(query), refresh=refresh)
    store_places(engine, parse_places(response))
    changed = attach_far_places_by_outline(engine, cache, refresh=refresh)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT town, category, count(*) n FROM places GROUP BY 1, 2 ORDER BY 1, 2")).all()
    lines = ["Places loaded (category counts per town):"]
    for town in sorted({r.town for r in rows}):
        lines.append(f"  {town}: " + ", ".join(f"{r.category}={r.n}" for r in rows if r.town == town))
    with engine.connect() as conn:
        far = conn.execute(text(
            "SELECT count(*) FILTER (WHERE network_distance_m > 100) gt100,"
            " count(*) FILTER (WHERE network_distance_m > :m) excluded, count(*) n FROM places"),
            {"m": MAX_PLACE_NETWORK_M}).one()
    back = [c for c in changed if c["after_m"] <= MAX_PLACE_NETWORK_M]
    lines.append(f"Re-attached by building outline: {len(changed)} places whose centre was > {MAX_PLACE_NETWORK_M:g} m "
                 f"away; {len(back)} now within {MAX_PLACE_NETWORK_M:g} m")
    for c in sorted(changed, key=lambda c: c["before_m"], reverse=True):
        lines.append(f"  {c['category']:<10} {c['name'] or '(unnamed)':<38} centre {c['before_m']:5.0f} m -> "
                     f"outline {c['after_m']:5.1f} m")
    lines.append(f"Excluded from sampling (more than {MAX_PLACE_NETWORK_M:g} m from the drive network): "
                 f"{far.excluded} of {far.n}")
    return "\n".join(lines)


# ---- sampling -----------------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    key: str  # "place/<id>" or "home/<edge>/<fraction>"
    category: str
    lon: float
    lat: float
    town: str | None = None
    name: str | None = None
    osm_id: str | None = None


def distance_m(a: Place | tuple[float, float], b: Place) -> float:
    lon, lat = (a.lon, a.lat) if isinstance(a, Place) else a
    return WGS84.inv(lon, lat, b.lon, b.lat)[2]


class PlacePool:
    """In-memory places plus residential streets for home sampling.

    Sampling never looks at camera locations.
    """

    def __init__(self, places: list[Place], residential: list[tuple[str, LineString, float, str]]):
        self.places = places
        self.by_category: dict[str, list[Place]] = {}
        for p in places:
            self.by_category.setdefault(p.category, []).append(p)
        self.residential = residential  # (edge key, geometry 4326, length_m, town)

    @classmethod
    def from_db(cls, engine: Engine) -> "PlacePool":
        with engine.connect() as conn:
            places = [
                Place(f"place/{r.id}", r.category, r.lon, r.lat, r.town, r.name, r.osm_id)
                for r in conn.execute(text(
                    "SELECT id, category, ST_X(coalesce(attach_geom, geom)) lon, ST_Y(coalesce(attach_geom, geom)) lat,"
                    " town, name, osm_id FROM places"
                    " WHERE network_distance_m IS NULL OR network_distance_m <= :m ORDER BY id"),
                    {"m": MAX_PLACE_NETWORK_M})
            ]
            # One direction per street so two-way streets aren't counted twice.
            residential = [
                (f"{r.u}-{r.v}-{r.key}", wkb.loads(bytes(r.g)), r.length_m, r.town)
                for r in conn.execute(text(
                    "SELECT e.u, e.v, e.key, ST_AsBinary(e.geom) g, e.length_m, t.name town FROM road_edges e"
                    " JOIN towns t ON ST_Covers(t.geom, ST_LineInterpolatePoint(e.geom, 0.5))"
                    " WHERE e.highway ~ '(^|;)(residential|living_street)(;|$)'"
                    " AND (e.oneway OR e.u < e.v) ORDER BY e.u, e.v, e.key"))
            ]
        return cls(places, residential)

    def sample_home(self, rng: np.random.Generator, town: str | tuple[str, ...] | None = None) -> Place:
        towns = (town,) if isinstance(town, str) else town
        streets = [s for s in self.residential if towns is None or s[3] in towns]
        if not streets:
            raise ValueError(f"no residential streets in {town!r}")
        lengths = np.array([s[2] for s in streets])
        key, geom, _, t = streets[int(rng.choice(len(streets), p=lengths / lengths.sum()))]
        frac = float(rng.random())
        pt = geom.interpolate(frac, normalized=True)
        return Place(f"home/{key}/{frac:.4f}", "home", pt.x, pt.y, t)

    def sample(
        self,
        categories: str | tuple[str, ...],
        rng: np.random.Generator,
        near: Place | None = None,
        decay_km: float | None = None,
        town: str | None = None,
    ) -> Place:
        """Uniform over places in the categories, optionally weighted by exp(-d / decay_km) from `near`."""
        cats = (categories,) if isinstance(categories, str) else categories
        pool = [p for c in cats for p in self.by_category.get(c, []) if town is None or p.town == town]
        if not pool:
            raise ValueError(f"no places for {cats} in {town!r}")
        if near is None or not decay_km:
            return pool[int(rng.integers(len(pool)))]
        w = np.array([math.exp(-distance_m(near, p) / (decay_km * 1000)) for p in pool])
        return pool[int(rng.choice(len(pool), p=w / w.sum()))]


# ASSUMPTION: road distance is about this multiple of straight-line distance.
CIRCUITY = 1.3


def _distance_weights(distances_m: np.ndarray, target_m: float) -> np.ndarray:
    """Prefer candidates whose road distance (straight line x CIRCUITY) is close to target_m."""
    spread = max(800.0, 0.35 * target_m)
    w = np.exp(-np.abs(distances_m * CIRCUITY - target_m) / spread)
    return w / w.sum() if w.sum() > 0 else np.full(len(w), 1 / len(w))


def sample_by_distance(pool: "PlacePool", categories: tuple[str, ...], rng: np.random.Generator,
                       origin: Place, target_m: float) -> Place:
    """A place in the categories whose distance from origin best matches a trip length (NHTS TRPMILES)."""
    cands = [p for c in categories for p in pool.by_category.get(c, [])]
    if not cands:
        raise ValueError(f"no places for {categories}")
    d = np.array([distance_m(origin, p) for p in cands])
    return cands[int(rng.choice(len(cands), p=_distance_weights(d, target_m)))]


def sample_home_by_distance(pool: "PlacePool", rng: np.random.Generator, origin: Place, target_m: float) -> Place:
    """Another residence (for drop-offs and visits), at a distance matching the trip length."""
    mids = np.array([[g.interpolate(0.5, normalized=True).x, g.interpolate(0.5, normalized=True).y]
                     for _, g, _, _ in pool.residential])
    d = np.array([WGS84.inv(origin.lon, origin.lat, x, y)[2] for x, y in mids])
    lengths = np.array([s[2] for s in pool.residential])
    w = _distance_weights(d, target_m) * lengths
    key, geom, _, town = pool.residential[int(rng.choice(len(w), p=w / w.sum()))]
    frac = float(rng.random())
    pt = geom.interpolate(frac, normalized=True)
    return Place(f"home/{key}/{frac:.4f}", "other_home", pt.x, pt.y, town)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true")
    print(run(refresh=parser.parse_args().refresh))


if __name__ == "__main__":
    main()
