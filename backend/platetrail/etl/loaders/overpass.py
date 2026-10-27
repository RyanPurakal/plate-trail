"""ALPR cameras from OpenStreetMap via the Overpass API.

One query per town of the configured region (platetrail.region). Each query
for a boundary-relation town also returns the relation so a misspelled or
missing boundary fails loudly instead of looking like a town with zero
cameras. A town given as a plain box is queried by that box.
"""

import time

import httpx

from platetrail.etl.cache import RawCache
from platetrail.etl.directions import DIRECTION_TAGS, conflicting_direction_tags, direction_from_tags, parse_direction
from platetrail.etl.loaders.base import CameraLoader, CameraRecord
from platetrail.region import Region, get_region

# Main instance first, then public mirrors. Overpass often answers 429/504
# under load, so each endpoint gets a few attempts with backoff.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
RETRYABLE_STATUS = {429, 502, 503, 504}
USER_AGENT = "PlateTrail/0.1 (privacy-audit research; synthetic drivers only)"

QUERY_TEMPLATE = """[out:json][timeout:90];
area["ISO3166-2"="{parent}"]["admin_level"="4"]->.nj;
rel(area.nj)["boundary"="administrative"]["admin_level"="{admin_level}"]["name"="{name}"]->.boundary;
.boundary out tags;
.boundary map_to_area->.town;
nwr(area.town)["man_made"="surveillance"]["surveillance:type"~"^alpr$",i];
out center tags;"""


BBOX_QUERY_TEMPLATE = """[out:json][timeout:90];
nwr({south},{west},{north},{east})["man_made"="surveillance"]["surveillance:type"~"^alpr$",i];
out center tags;"""


class BoundaryNotFound(RuntimeError):
    pass


def build_query(osm_name: str, parent_iso3166_2: str = "US-NJ", admin_level: int = 8) -> str:
    # The parent area keeps its original ".nj" set name so cached responses for
    # the default region (keyed on the query text) stay valid.
    return QUERY_TEMPLATE.format(name=osm_name, parent=parent_iso3166_2, admin_level=admin_level)


def build_bbox_query(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    return BBOX_QUERY_TEMPLATE.format(west=west, south=south, east=east, north=north)


def towns_for(region: Region) -> dict[str, tuple[str, int]]:
    """Town label -> (OSM boundary name, admin_level), for towns defined by a relation."""
    return {t.label: (t.osm_name, t.admin_level) for t in region.towns if t.osm_relation is not None}


def town_queries(region: Region) -> dict[str, tuple[str, bool]]:
    """Town label -> (Overpass query, whether the response must hold a boundary relation). In region order."""
    return {
        t.label: (build_bbox_query(t.bbox), False) if t.bbox is not None
        else (build_query(t.osm_name, region.parent_iso3166_2, t.admin_level), True)
        for t in region.towns
    }


def parse_response(town: str, response: dict, expect_boundary: bool = True) -> list[CameraRecord]:
    elements = response.get("elements", [])
    if expect_boundary and not any(e.get("type") == "relation" and e.get("tags", {}).get("boundary") == "administrative" for e in elements):
        raise BoundaryNotFound(f"Overpass returned no boundary relation for {town!r}; check the OSM name")

    records = []
    for el in elements:
        tags = el.get("tags", {})
        if tags.get("man_made") != "surveillance":
            continue  # the boundary relation
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        directions, raw, key = direction_from_tags(tags)
        alt = alternate_directions(tags, key)
        records.append(
            CameraRecord(
                source="osm",
                source_id=f"{el['type']}/{el['id']}",
                lat=lat,
                lon=lon,
                town=town,
                directions_deg=directions,
                direction_raw=raw,
                direction_key=key,
                alt_directions_deg=alt,
                tags=tags,
            )
        )
    return records


def alternate_directions(tags: dict[str, str], used_key: str | None) -> list[float] | None:
    """Bearings from a lower-priority direction tag that disagrees with the one used.

    Such a camera is direction-ambiguous; the matcher can be configured to use
    either reading.
    """
    if used_key is None or not conflicting_direction_tags(tags):
        return None
    for key in DIRECTION_TAGS:
        if key != used_key and key in tags and (parsed := parse_direction(tags[key])):
            return parsed
    return None


class OverpassClient:
    """POSTs queries to Overpass with retries and mirror fallback."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        urls: tuple[str, ...] = OVERPASS_URLS,
        attempts_per_url: int = 3,
        backoff_s: float = 10.0,
    ):
        self.client = client or httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT})
        self.urls = urls
        self.attempts_per_url = attempts_per_url
        self.backoff_s = backoff_s

    def fetch(self, query: str) -> dict:
        last_error: Exception | None = None
        for url in self.urls:
            for attempt in range(self.attempts_per_url):
                try:
                    resp = self.client.post(url, data={"data": query})
                    if resp.status_code in RETRYABLE_STATUS:
                        raise httpx.HTTPStatusError(f"{resp.status_code} from {url}", request=resp.request, response=resp)
                    resp.raise_for_status()
                    return resp.json()
                except (httpx.HTTPStatusError, httpx.TransportError) as e:
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    if status is not None and status not in RETRYABLE_STATUS:
                        raise
                    last_error = e
                    if attempt < self.attempts_per_url - 1:
                        time.sleep(self.backoff_s * (attempt + 1))
        raise RuntimeError(f"All Overpass endpoints failed; last error: {last_error}") from last_error


class OverpassLoader(CameraLoader):
    source = "osm"

    def __init__(
        self,
        cache: RawCache,
        region: Region | None = None,
        client: httpx.Client | None = None,
        urls: tuple[str, ...] = OVERPASS_URLS,
        attempts_per_url: int = 3,
        backoff_s: float = 10.0,
    ):
        self.cache = cache
        self.region = region or get_region()
        self.overpass = OverpassClient(client, urls, attempts_per_url, backoff_s)

    def load(self, refresh: bool = False) -> list[CameraRecord]:
        records: list[CameraRecord] = []
        for town, (query, expect_boundary) in town_queries(self.region).items():
            response = self.cache.get_or_fetch(query, lambda q=query: self.overpass.fetch(q), refresh=refresh)
            records.extend(parse_response(town, response, expect_boundary))
        return records
