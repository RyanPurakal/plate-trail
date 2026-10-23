"""Place search for the Explore view: a town or address -> a box to explore.

Queries go to OpenStreetMap Nominatim (https://nominatim.org) and follow its
usage policy: an identifying User-Agent, at most one request per second from
this server, and repeated queries answered from a cache.

A query can be someone's home address, so it is treated like the "your week"
anchors: it arrives in a POST body (not the URL, which access logs record), is
never logged, and is never written to disk. The cache lives in process memory
only, holds a bounded number of entries for a limited time, and is gone on
restart.
"""

import logging
import threading
import time
from collections import OrderedDict

import httpx

from platetrail.area import MAX_SPAN_DEG

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "PlateTrail/0.1 (location-privacy check-up; +https://github.com/RyanPurakal/plate-trail)"
ATTRIBUTION = "Search by OpenStreetMap Nominatim, data © OpenStreetMap contributors (ODbL)"
MIN_INTERVAL_S = 1.0
MAX_RESULTS = 5
MAX_QUERY_LEN = 200
CACHE_SIZE = 256
CACHE_TTL_S = 24 * 3600
# An address or a single building gives a tiny box; widen it to a neighbourhood.
MIN_SPAN_DEG = 0.04


class GeocodeError(ValueError):
    pass


class _DropNominatimRequests(logging.Filter):
    """httpx logs each request URL at INFO; the URL holds the search text, so drop those records."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "nominatim" not in record.getMessage()


logging.getLogger("httpx").addFilter(_DropNominatimRequests())


def normalize_query(q: str) -> str:
    q = " ".join(q.split())
    if not q:
        raise GeocodeError("enter a town, place or address")
    if len(q) > MAX_QUERY_LEN:
        raise GeocodeError(f"search text can be at most {MAX_QUERY_LEN} characters")
    return q


def explore_bbox(lat: float, lon: float, nominatim_bbox: list) -> list[float]:
    """Nominatim's [south, north, west, east] -> [w, s, e, n] sized for GET /area.

    Spans are clamped between MIN_SPAN_DEG and a little under MAX_SPAN_DEG
    around the box centre (or the result point if the box is missing), so a
    big county shows its middle and a street address shows its surroundings.
    """
    try:
        s, n, w, e = (float(v) for v in nominatim_bbox)
        cx, cy = (w + e) / 2, (s + n) / 2
        span_x, span_y = e - w, n - s
    except (TypeError, ValueError):
        cx, cy, span_x, span_y = lon, lat, 0.0, 0.0
    limit = MAX_SPAN_DEG - 0.02  # room for the API's outward snapping
    half_x = min(max(span_x, MIN_SPAN_DEG), limit) / 2
    half_y = min(max(span_y, MIN_SPAN_DEG), limit) / 2
    box = [max(cx - half_x, -180.0), max(cy - half_y, -90.0), min(cx + half_x, 180.0), min(cy + half_y, 90.0)]
    return [round(v, 4) for v in box]


def parse_results(response: list) -> list[dict]:
    results = []
    for item in response[:MAX_RESULTS]:
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        results.append({
            "name": item.get("display_name") or item.get("name") or f"{lat:.4f}, {lon:.4f}",
            "kind": item.get("addresstype") or item.get("type"),
            "lat": lat,
            "lon": lon,
            "bbox": explore_bbox(lat, lon, item.get("boundingbox")),
        })
    return results


class Geocoder:
    def __init__(self, client: httpx.Client | None = None, url: str = NOMINATIM_URL,
                 min_interval_s: float = MIN_INTERVAL_S, clock=time.monotonic, sleep=time.sleep):
        self.client = client or httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT})
        self.url = url
        self.min_interval_s = min_interval_s
        self.clock = clock
        self.sleep = sleep
        self._cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self._lock = threading.Lock()
        self._last_request = float("-inf")

    def _cached(self, key: str) -> list[dict] | None:
        hit = self._cache.get(key)
        if hit is None:
            return None
        if self.clock() - hit[0] > CACHE_TTL_S:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return hit[1]

    def search(self, q: str) -> list[dict]:
        q = normalize_query(q)
        key = q.casefold()
        with self._lock:  # one request at a time keeps the rate limit simple
            hit = self._cached(key)
            if hit is not None:
                return hit
            wait = self._last_request + self.min_interval_s - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last_request = self.clock()
            resp = self.client.get(self.url, params={"q": q, "format": "jsonv2", "limit": MAX_RESULTS},
                                   headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            results = parse_results(resp.json())
            self._cache[key] = (self.clock(), results)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
            return results


_geocoder: Geocoder | None = None


def get_geocoder() -> Geocoder:
    global _geocoder
    if _geocoder is None:
        _geocoder = Geocoder()
    return _geocoder
