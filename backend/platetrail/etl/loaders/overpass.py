"""ALPR cameras from OpenStreetMap via the Overpass API.

One query per town. Each query also returns the town's boundary relation so
a misspelled or missing boundary fails loudly instead of looking like a town
with zero cameras.
"""

import time

import httpx

from platetrail.etl.cache import RawCache
from platetrail.etl.directions import direction_from_tags
from platetrail.etl.loaders.base import CameraLoader, CameraRecord

# Main instance first, then public mirrors. Overpass often answers 429/504
# under load, so each endpoint gets a few attempts with backoff.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
RETRYABLE_STATUS = {429, 502, 503, 504}
USER_AGENT = "PlateTrail/0.1 (privacy-audit research; synthetic drivers only)"

# Town label -> OSM boundary name (admin_level 8 municipality within NJ).
TOWNS: dict[str, str] = {
    "Edison": "Edison",
    "New Brunswick": "New Brunswick",
}

QUERY_TEMPLATE = """[out:json][timeout:90];
area["ISO3166-2"="US-NJ"]["admin_level"="4"]->.nj;
rel(area.nj)["boundary"="administrative"]["admin_level"="8"]["name"="{name}"]->.boundary;
.boundary out tags;
.boundary map_to_area->.town;
nwr(area.town)["man_made"="surveillance"]["surveillance:type"~"^alpr$",i];
out center tags;"""


class BoundaryNotFound(RuntimeError):
    pass


def build_query(osm_name: str) -> str:
    return QUERY_TEMPLATE.format(name=osm_name)


def parse_response(town: str, response: dict) -> list[CameraRecord]:
    elements = response.get("elements", [])
    if not any(e.get("type") == "relation" and e.get("tags", {}).get("boundary") == "administrative" for e in elements):
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
        directions, raw = direction_from_tags(tags)
        records.append(
            CameraRecord(
                source="osm",
                source_id=f"{el['type']}/{el['id']}",
                lat=lat,
                lon=lon,
                town=town,
                directions_deg=directions,
                direction_raw=raw,
                tags=tags,
            )
        )
    return records


class OverpassLoader(CameraLoader):
    source = "osm"

    def __init__(
        self,
        cache: RawCache,
        towns: dict[str, str] = TOWNS,
        client: httpx.Client | None = None,
        urls: tuple[str, ...] = OVERPASS_URLS,
        attempts_per_url: int = 3,
        backoff_s: float = 10.0,
    ):
        self.cache = cache
        self.towns = towns
        self.client = client or httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT})
        self.urls = urls
        self.attempts_per_url = attempts_per_url
        self.backoff_s = backoff_s

    def _fetch(self, query: str) -> dict:
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

    def load(self, refresh: bool = False) -> list[CameraRecord]:
        records: list[CameraRecord] = []
        for town, osm_name in self.towns.items():
            query = build_query(osm_name)
            response = self.cache.get_or_fetch(query, lambda q=query: self._fetch(q), refresh=refresh)
            records.extend(parse_response(town, response))
        return records
