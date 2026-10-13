"""Parse a Google Timeline export into visits and moves.

Three export formats are accepted (all JSON):

* on-device Timeline.json (Android, 2024+): {"semanticSegments": [...]} with
  visit.topCandidate.placeLocation.latLng = "40.52°, -74.36°";
* iPhone export (Google Maps app): a top-level list of segments with
  visit.topCandidate.placeLocation = "geo:40.52,-74.36" and activity.start/end;
* legacy Takeout Semantic Location History: {"timelineObjects": [...]} with
  placeVisit / activitySegment and latitudeE7 / longitudeE7.

Times are converted to local wall-clock time (America/New_York, naive), which
is what the simulation uses. Nothing here touches the network or a database.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("America/New_York")

# Activity types that mean the person was driving (or riding in) a private car. A taxi or bus is not
# their plate, so those count as "other".
VEHICLE = ("PASSENGER_VEHICLE", "IN_VEHICLE", "DRIVING", "IN_CAR", "MOTORCYCLING", "IN PASSENGER VEHICLE")


@dataclass(frozen=True)
class Visit:
    start: datetime
    end: datetime
    lon: float
    lat: float
    semantic: str | None = None  # raw semantic type, e.g. "HOME", "INFERRED_WORK", "TYPE_HOME"
    place_id: str | None = None


@dataclass(frozen=True)
class Move:
    start: datetime
    end: datetime
    mode: str  # "drive", "other" or "unknown"
    raw_type: str | None = None


@dataclass
class Timeline:
    format: str
    visits: list[Visit] = field(default_factory=list)
    moves: list[Move] = field(default_factory=list)


def _time(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):  # legacy *TimestampMs
        dt = datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    else:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL)
    return dt.astimezone(LOCAL).replace(tzinfo=None)


_NUM = r"(-?\d+(?:\.\d+)?)"


def _latlng(v) -> tuple[float, float] | None:
    """(lon, lat) from "40.5°, -74.3°", "geo:40.5,-74.3", {"latLng": ...} or {"latitudeE7", "longitudeE7"}."""
    if v is None:
        return None
    if isinstance(v, dict):
        if "latLng" in v:
            return _latlng(v["latLng"])
        if "latitudeE7" in v and "longitudeE7" in v:
            return v["longitudeE7"] / 1e7, v["latitudeE7"] / 1e7
        if "point" in v:
            return _latlng(v["point"])
        return None
    m = re.search(_NUM + r"\s*°?\s*,\s*" + _NUM, str(v))
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return lon, lat


def _mode(raw: str | None) -> str:
    if not raw:
        return "unknown"
    up = raw.upper().replace(" ", "_")
    if any(k.replace(" ", "_") in up for k in VEHICLE):
        return "drive"
    if up in ("UNKNOWN_ACTIVITY_TYPE", "UNKNOWN"):
        return "unknown"
    return "other"


def _segments(tl: Timeline, segs: list[dict]) -> None:
    """New-style segments (Android semanticSegments or the iPhone list): visit / activity / timelinePath."""
    for s in segs:
        start, end = _time(s.get("startTime")), _time(s.get("endTime"))
        if start is None or end is None:
            continue
        if "visit" in s:
            cand = s["visit"].get("topCandidate", {})
            ll = _latlng(cand.get("placeLocation"))
            if ll:
                tl.visits.append(Visit(start, end, ll[0], ll[1], cand.get("semanticType"),
                                       cand.get("placeId") or cand.get("placeID")))
        elif "activity" in s:
            cand = s["activity"].get("topCandidate", {})
            raw = cand.get("type")
            tl.moves.append(Move(start, end, _mode(raw), raw))


def _legacy(tl: Timeline, objs: list[dict]) -> None:
    for o in objs:
        if "placeVisit" in o:
            pv = o["placeVisit"]
            loc, dur = pv.get("location", {}), pv.get("duration", {})
            ll = _latlng(loc)
            start = _time(dur.get("startTimestamp") or dur.get("startTimestampMs"))
            end = _time(dur.get("endTimestamp") or dur.get("endTimestampMs"))
            if ll and start and end:
                tl.visits.append(Visit(start, end, ll[0], ll[1], loc.get("semanticType"), loc.get("placeId")))
        elif "activitySegment" in o:
            a = o["activitySegment"]
            dur = a.get("duration", {})
            start = _time(dur.get("startTimestamp") or dur.get("startTimestampMs"))
            end = _time(dur.get("endTimestamp") or dur.get("endTimestampMs"))
            if start and end:
                tl.moves.append(Move(start, end, _mode(a.get("activityType")), a.get("activityType")))


def parse(data) -> Timeline:
    """Parse a loaded export (dict or list). Raises ValueError if the shape isn't recognised."""
    if isinstance(data, dict) and "semanticSegments" in data:
        tl = Timeline("android")
        _segments(tl, data["semanticSegments"])
    elif isinstance(data, list):
        tl = Timeline("iphone")
        _segments(tl, data)
    elif isinstance(data, dict) and "timelineObjects" in data:
        tl = Timeline("takeout")
        _legacy(tl, data["timelineObjects"])
    else:
        raise ValueError("not a recognised Google Timeline export (expected semanticSegments, a segment list, "
                         "or timelineObjects)")
    tl.visits.sort(key=lambda v: v.start)
    tl.moves.sort(key=lambda m: m.start)
    return tl


def load(path: str | Path) -> Timeline:
    with open(path, encoding="utf-8") as f:
        return parse(json.load(f))
