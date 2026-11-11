"""Write a synthetic routine as a Google Timeline export, for testing the importer.

Visits are the time between arriving at a place and leaving it; arrival is
the departure plus a travel time at 30 km/h straight-line (min 5 minutes).
The first visit starts at midnight on the first day.
"""

import math
from datetime import datetime, timedelta

from platetrail.realdata.timeline import LOCAL
from platetrail.routines.base import Routine

LABELS = {
    "android": {"home": "HOME", "work": "WORK", None: "UNKNOWN"},
    "iphone": {"home": "Home", "work": "Work", None: "Unknown"},
    "takeout": {"home": "TYPE_HOME", "work": "TYPE_WORK", None: None},
}


def _travel(o, d) -> timedelta:
    lat = math.radians((o.lat + d.lat) / 2)
    m = math.hypot((o.lon - d.lon) * 111_320 * math.cos(lat), (o.lat - d.lat) * 110_540)
    return timedelta(minutes=max(5.0, m / 500))


def _iso(t: datetime) -> str:
    return t.replace(tzinfo=LOCAL).isoformat(timespec="milliseconds")


def routine_to_timeline(routine: Routine, fmt: str = "android"):
    kind = {p.key: k for k, p in routine.anchors.items() if k in ("home", "work")}
    trips = sorted(routine.trips, key=lambda t: t.depart)
    if not trips:
        return {"semanticSegments": []} if fmt == "android" else [] if fmt == "iphone" else {"timelineObjects": []}
    segs = []
    here = trips[0].origin
    since = trips[0].depart.replace(hour=0, minute=0, second=0, microsecond=0)
    for t in trips:
        depart = max(t.depart, since + timedelta(minutes=1))
        arrive = depart + _travel(t.origin, t.dest)
        segs.append(("visit", here, since, depart))
        segs.append(("drive", None, depart, arrive))
        here, since = t.dest, arrive
    segs.append(("visit", here, since, since + timedelta(hours=8)))

    def label(p):
        return LABELS[fmt][kind.get(p.key)]

    if fmt == "android":
        out = []
        for typ, p, s, e in segs:
            seg = {"startTime": _iso(s), "endTime": _iso(e)}
            if typ == "visit":
                seg["visit"] = {"hierarchyLevel": 0, "probability": 0.9, "topCandidate": {
                    "placeId": p.key, "semanticType": label(p), "probability": 0.8,
                    "placeLocation": {"latLng": f"{p.lat:.7f}°, {p.lon:.7f}°"}}}
            else:
                seg["activity"] = {"topCandidate": {"type": "IN_PASSENGER_VEHICLE", "probability": 0.9}}
            out.append(seg)
        return {"semanticSegments": out, "rawSignals": [], "userLocationProfile": {}}
    if fmt == "iphone":
        out = []
        for typ, p, s, e in segs:
            seg = {"startTime": _iso(s), "endTime": _iso(e)}
            if typ == "visit":
                seg["visit"] = {"hierarchyLevel": "0", "probability": "0.9", "topCandidate": {
                    "placeID": p.key, "semanticType": label(p), "probability": "0.8",
                    "placeLocation": f"geo:{p.lat:.6f},{p.lon:.6f}"}}
            else:
                seg["activity"] = {"start": "geo:0,0", "end": "geo:0,0",
                                   "topCandidate": {"type": "in passenger vehicle", "probability": "0.9"}}
            out.append(seg)
        return out
    objs = []
    for typ, p, s, e in segs:
        dur = {"startTimestamp": s.replace(tzinfo=LOCAL).astimezone().isoformat(),
               "endTimestamp": e.replace(tzinfo=LOCAL).astimezone().isoformat()}
        if typ == "visit":
            loc = {"latitudeE7": round(p.lat * 1e7), "longitudeE7": round(p.lon * 1e7), "placeId": p.key}
            if label(p):
                loc["semanticType"] = label(p)
            objs.append({"placeVisit": {"location": loc, "duration": dur}})
        else:
            objs.append({"activitySegment": {"activityType": "IN_PASSENGER_VEHICLE", "duration": dur}})
    return {"timelineObjects": objs}
