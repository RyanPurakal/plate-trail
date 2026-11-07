"""FastAPI application for the Plate Trail check-up.

    GET  /health
    GET  /region           the default region: id, name and initial map view
    GET  /area             public fixed sensors and a summary for any bbox
    POST /geocode          place search (Nominatim) -> boxes to explore; the text is never stored or logged
    POST /route/check      sensors one route passes and where reads would happen, on a road network built around
                           the route; compute-only, never stored
    POST /route/history    what a 1-day to 1-year read history of that route could suggest; compute-only
"""

import httpx
import osmnx as ox
import requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from platetrail.api.schemas import GeocodeBody, RouteCheckBody, RouteHistoryBody
from platetrail.area import AreaError, load_area, parse_bbox
from platetrail.config import get_settings
from platetrail.geocode import ATTRIBUTION, GeocodeError, get_geocoder
from platetrail.region import get_region
from platetrail.routearea import AreaNetworks, get_area_networks
from platetrail.sim.routing import AnchorTooFar, NoRoute

app = FastAPI(title="Plate Trail API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/region")
def region() -> dict:
    """The active region (PLATETRAIL_REGION); the frontend uses `map` for its initial view."""
    r = get_region()
    return {"id": r.id, "name": r.name, "map": r.map.as_dict()}


@app.get("/area")
def area(bbox: str) -> dict:
    """Sensors in `bbox` (west,south,east,north) from OpenStreetMap, snapped to a 0.01 deg grid and cached."""
    try:
        box = parse_bbox(bbox)
    except AreaError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        return load_area(box)
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=503, detail="map data source is busy; try again shortly") from e


@app.post("/geocode")
def geocode(body: GeocodeBody) -> dict:
    """Places matching the search text, each with a box sized for GET /area. Session-only: not stored or logged."""
    try:
        results = get_geocoder().search(body.q)
    except GeocodeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail="place search is busy; try again shortly") from e
    return {"results": results, "attribution": ATTRIBUTION}


def _checked_route(start, end, both_ways: bool, networks: AreaNetworks) -> tuple[dict, dict]:
    """(network, check_route result) on a small network built around the route from public map data
    (held briefly in memory only)."""
    from platetrail.routecheck import check_route

    try:
        net = networks.for_route(start, end)
        result = check_route(net.router, net.cameras, start, end, both_ways)
    except AreaError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (AnchorTooFar, NoRoute) as e:
        raise HTTPException(status_code=422, detail="the start or end is more than 500 m from a mapped road, "
                            "or the two can't be joined by road") from e
    except (RuntimeError, httpx.HTTPError, requests.RequestException, ox._errors.ResponseStatusCodeError) as e:
        raise HTTPException(status_code=503, detail="map data is busy; try again shortly") from e
    network = {
        "kind": "area",
        "name": "OpenStreetMap roads around this route",
        "bbox": list(net.bbox),
        "sensors_mapped": net.sensors_mapped,
        "sensors_on_roads": net.sensors_on_roads,
        "sources": net.sources,
    }
    return network, result


@app.post("/route/check")
def route_check(body: RouteCheckBody, networks: AreaNetworks = Depends(get_area_networks)) -> dict:
    """Sensors a route passes (both ways by default). Session-only: nothing about the route is stored or logged."""
    start, end = (body.start.lon, body.start.lat), (body.end.lon, body.end.lat)
    network, result = _checked_route(start, end, body.both_ways, networks)
    return {"network": network, **result}


@app.post("/route/history")
def route_history(body: RouteHistoryBody, networks: AreaNetworks = Depends(get_area_networks)) -> dict:
    """What a read history of one route, driven on a schedule and kept 1 to 365 days, could suggest.
    Session-only, like /route/check."""
    from platetrail.routehistory import route_history as history

    start, end = (body.start.lon, body.start.lat), (body.end.lon, body.end.lat)
    network, check = _checked_route(start, end, body.both_ways, networks)
    mins = lambda s: int(s[:2]) * 60 + int(s[3:])  # noqa: E731
    result = history(check["legs"], start, end, tuple(body.weekdays), mins(body.leave), mins(body.return_),
                     tuple(body.retention_days))
    return {"network": network, **result}
