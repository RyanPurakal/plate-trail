"""Route check: which fixed sensors one saved route passes, and where reads would happen.

The visitor's route (start and end, kept in their browser) is driven on the
study region's road network and matched against its cameras with the
default, direction-aware matching. By default the route is checked both
ways, since a sensor facing one direction of traffic may read the trip
there but not the trip back.

Like "your week", this is compute-only: no database writes, the route cache
is bypassed (so the points never reach Redis), nothing is cached and the
inputs are not logged. The response exists only in the HTTP reply.
"""

from datetime import datetime

from platetrail.sim.matcher import MatchConfig
from platetrail.sim.routing import Route, Router
from platetrail.sim.trip import CameraPass, CameraSet, match_route

# Only offsets from departure are reported; this fixed time just anchors the arithmetic.
REFERENCE_DEPART = datetime(2026, 1, 5, 8, 0)


def _distance_along(route: Route, p: CameraPass, offset_s: float) -> float:
    """Metres from the start of the route to where the pass happens."""
    if p.event == "departure":
        return 0.0
    if p.event == "arrival":
        return route.length_m
    before = 0.0
    for re in route.edges:
        end = re.enter_offset_s + re.travel_time_s
        if re.edge == p.edge and re.enter_offset_s - 1e-6 <= offset_s <= end + 1e-6:
            share = (offset_s - re.enter_offset_s) / re.travel_time_s if re.travel_time_s else 0.0
            return before + share * re.length_m
        before += re.length_m
    return before


def check_leg(router: Router, cameras: CameraSet, start: tuple[float, float], end: tuple[float, float],
              cfg: MatchConfig | None = None) -> dict:
    """One direction of a route: geometry, length, duration and a step per sensor passed, in order.

    A step with `read: false` is a sensor the route passes that would not
    record this trip under the matching assumptions (e.g. it faces the other
    direction of traffic); `reason` says which.
    """
    route = router.route(start, end, REFERENCE_DEPART, use_cache=False)
    passes = match_route(route, cameras, start, end, cfg or MatchConfig())
    steps = []
    for p in passes:
        cam = cameras.by_id.get(p.camera_id)
        offset = (p.time - route.depart).total_seconds()
        steps.append({
            "camera_id": p.camera_id,
            "label": p.label,
            "lon": cam.lon if cam else None,
            "lat": cam.lat if cam else None,
            "event": p.event,
            "offset_s": round(offset, 1),
            "distance_m": round(_distance_along(route, p, offset), 1),
            "road_name": p.road_name,
            "travel_bearing_deg": p.travel_bearing_deg,
            "read": p.captured,
            "reason": p.reason.value,
        })
    return {
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in route.coords]},
        "length_m": round(route.length_m, 1),
        "duration_s": round(route.duration_s, 1),
        "sensors_passed": len({s["camera_id"] for s in steps}),
        "reads": sum(1 for s in steps if s["read"]),
        "steps": steps,
    }


def check_route(router: Router, cameras: CameraSet, start: tuple[float, float], end: tuple[float, float],
                both_ways: bool = True) -> dict:
    """start/end are (lon, lat). Raises AnchorTooFar or NoRoute if the points are off the road network."""
    legs = [{"direction": "outbound", **check_leg(router, cameras, start, end)}]
    if both_ways:
        legs.append({"direction": "return", **check_leg(router, cameras, end, start)})
    return {"legs": legs, "stored": False}
