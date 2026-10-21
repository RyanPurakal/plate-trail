"""Explore any area: public fixed sensors inside a bounding box.

Unlike the study region (platetrail.region), an area needs no config file. The
box is snapped outward to a GRID_DEG grid so nearby requests share one cached
Overpass response, and a cached response older than MAX_AGE is refetched so
summaries stay reasonably fresh. Only public map data is involved: the box
itself is not personal data and nothing about the request is stored besides
the cached Overpass response.
"""

import logging
import math
from datetime import datetime, timedelta, timezone

import httpx

from platetrail.config import get_settings
from platetrail.etl.cache import RawCache
from platetrail.etl.directions import direction_from_tags, parse_direction
from platetrail.etl.loaders.file import read_rows
from platetrail.etl.loaders.overpass import OverpassClient
from platetrail.region import Region, get_region

log = logging.getLogger(__name__)

GRID_DEG = 0.01
MAX_SPAN_DEG = 0.5
MAX_AGE = timedelta(days=7)

AREA_QUERY_TEMPLATE = """[out:json][timeout:60];
nwr["man_made"="surveillance"]["surveillance:type"~"^alpr$",i]({s},{w},{n},{e});
out center meta;"""

OSM_SOURCE = {
    "id": "osm",
    "name": "OpenStreetMap contributors",
    "license": "ODbL",
    "url": "https://www.openstreetmap.org/copyright",
}


class AreaError(ValueError):
    pass


def parse_bbox(raw: str) -> tuple[float, float, float, float]:
    """'west,south,east,north' -> floats, validated (range, order, size)."""
    try:
        w, s, e, n = (float(v) for v in raw.split(","))
    except ValueError as err:
        raise AreaError("bbox must be four numbers: west,south,east,north") from err
    if not all(math.isfinite(v) for v in (w, s, e, n)):
        raise AreaError("bbox values must be finite")
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise AreaError("bbox needs west < east and south < north, within lon/lat range")
    if e - w > MAX_SPAN_DEG or n - s > MAX_SPAN_DEG:
        raise AreaError(f"bbox can be at most {MAX_SPAN_DEG} degrees on each side")
    return w, s, e, n


def snap_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Round outward to the GRID_DEG grid (clamped to valid lon/lat)."""
    w, s, e, n = bbox
    k = 1 / GRID_DEG

    # round() first so values already on the grid don't drift outward from float error
    def down(v: float) -> float:
        return math.floor(round(v * k, 6)) / k

    def up(v: float) -> float:
        return math.ceil(round(v * k, 6)) / k

    return (max(down(w), -180.0), max(down(s), -90.0), min(up(e), 180.0), min(up(n), 90.0))


def build_area_query(bbox: tuple[float, float, float, float]) -> str:
    w, s, e, n = bbox
    return AREA_QUERY_TEMPLATE.format(w=f"{w:.2f}", s=f"{s:.2f}", e=f"{e:.2f}", n=f"{n:.2f}")


def bbox_area_km2(bbox: tuple[float, float, float, float]) -> float:
    w, s, e, n = bbox
    r = 6371.0088
    return r * r * math.radians(e - w) * abs(math.sin(math.radians(n)) - math.sin(math.radians(s)))


def parse_area_response(response: dict) -> list[dict]:
    """Overpass elements -> GeoJSON Point features (public map data only; no editor names)."""
    features = []
    for el in response.get("elements", []):
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        directions, raw, _ = direction_from_tags(el.get("tags", {}))
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": f"osm:{el['type']}/{el['id']}",
                "source": "osm",
                "directions_deg": directions,
                "direction_raw": raw,
                "last_edited": el.get("timestamp"),
            },
        })
    features.sort(key=lambda f: f["properties"]["id"])
    return features


def _in_bbox(lon: float, lat: float, bbox: tuple[float, float, float, float]) -> bool:
    w, s, e, n = bbox
    return w <= lon <= e and s <= lat <= n


def file_area_features(bbox: tuple[float, float, float, float], region: Region) -> tuple[list[dict], list[dict]]:
    """Features from the region's file sources inside bbox, plus one source entry per file.

    Each source entry has the source name and the file's last-modified time.
    A file that is missing or malformed is logged and skipped so one bad
    config file doesn't break exploring other areas.
    """
    features, sources = [], []
    for src in region.camera_sources:
        if src.type != "file" or src.path is None:
            continue
        name = src.source or "file"
        try:
            rows = read_rows(src.path)
            updated = datetime.fromtimestamp(src.path.stat().st_mtime, timezone.utc)
        except (OSError, ValueError) as e:  # SensorFileError and JSON errors are ValueErrors
            log.warning("skipping sensor file %s: %s", src.path, e)
            continue
        for i, row in enumerate(rows):
            try:
                lon, lat = float(row["lon"]), float(row["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            if not _in_bbox(lon, lat, bbox):
                continue
            raw = row.get("direction")
            raw = None if raw is None else str(raw)
            sid = row.get("id")
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "id": f"{name}:{i if sid in (None, '') else sid}",
                    "source": name,
                    "directions_deg": parse_direction(raw),
                    "direction_raw": raw,
                    "last_edited": None,
                },
            })
        sources.append({"id": name, "name": name, "updated_at": updated.isoformat()})
    features.sort(key=lambda f: f["properties"]["id"])
    return features, sources


def area_summary(
    bbox: tuple[float, float, float, float],
    features: list[dict],
    fetched_at: datetime | None,
    file_sources: list[dict] | tuple = (),
) -> dict:
    """Counts and per-source credits. OSM is listed first, then file sources in config order."""
    osm = [f for f in features if f["properties"]["source"] == "osm"]
    edits = [f["properties"]["last_edited"] for f in osm if f["properties"]["last_edited"]]
    area = bbox_area_km2(bbox)
    return {
        "sensor_count": len(features),
        "with_direction": sum(1 for f in features if f["properties"]["directions_deg"]),
        "area_km2": round(area, 2),
        "sensors_per_100km2": round(100 * len(features) / area, 2) if area else None,
        "sources": [{
            **OSM_SOURCE,
            "count": len(osm),
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "latest_edit": max(edits) if edits else None,
        }] + [{
            "id": fs["id"],
            "name": fs["name"],
            "license": None,
            "url": None,
            "count": sum(1 for f in features if f["properties"]["source"] == fs["id"]),
            "fetched_at": fs["updated_at"],  # file's last-modified time
            "latest_edit": None,
        } for fs in file_sources],
    }


def area_cache() -> RawCache:
    return RawCache(get_settings().data_dir / "raw" / "overpass_areas")


def load_area(
    bbox: tuple[float, float, float, float],
    cache: RawCache | None = None,
    client: OverpassClient | None = None,
    now: datetime | None = None,
    region: Region | None = None,
) -> dict:
    """Sensors and summary for a bbox (snapped). Fetches from Overpass if not cached or stale.

    File sensors come from `region` (default: the active region) and are
    included only where they fall inside the snapped box.

    A stale cached response is still used if the refetch fails, so a busy
    Overpass server only delays updates. Without any cached response the
    error propagates (RuntimeError or httpx.HTTPError from OverpassClient).
    """
    snapped = snap_bbox(bbox)
    cache = cache or area_cache()
    query = build_area_query(snapped)
    fetched_at = cache.fetched_at(query)
    now = now or datetime.now(timezone.utc)
    stale = fetched_at is None or now - fetched_at > MAX_AGE
    overpass = client or OverpassClient(attempts_per_url=2, backoff_s=2.0)
    try:
        response = cache.get_or_fetch(query, lambda: overpass.fetch(query), refresh=stale)
    except (RuntimeError, httpx.HTTPError):
        if fetched_at is None:
            raise
        response = cache.get_or_fetch(query, lambda: overpass.fetch(query))
    features = parse_area_response(response)
    file_features, file_sources = file_area_features(snapped, region or get_region())
    features += file_features
    return {
        "bbox": list(snapped),
        "summary": area_summary(snapped, features, cache.fetched_at(query), file_sources),
        "sensors": {"type": "FeatureCollection", "features": features},
    }
