"""Route history: what a read history of one saved route, kept for 1 day up to a year, could suggest.

Takes a route check (platetrail.routecheck) and repeats the drive on a
simple schedule: there at a usual leave time and back at a usual return
time on the chosen days, with a few minutes of variation. Every pass that
would record becomes a read, except a small share missed (the simulator's
default per-read miss rate). For each retention period the reads kept are
run through the inference engine, and the result is put in plain language.

The route's own start and end are used only to say how close an estimate
comes to them; they are returned to the visitor and nothing else. Like the
route check, this is compute-only: nothing is stored, cached or logged.
"""

from datetime import date, datetime, time, timedelta

import numpy as np

from platetrail.geo import WGS84
from platetrail.inference.engine import EngineRead, _days_text, _hhmm, infer
from platetrail.sim.noise import NoiseConfig

# Only times of day and weekdays are reported; this fixed date just anchors the calendar (a Sunday).
REFERENCE_END = date(2026, 12, 27)
JITTER_MIN = 10
RETENTION_DAYS = (7, 30, 365)


def _reads(legs: list[dict], days: int, weekdays: tuple[int, ...], leave_min: int, return_min: int,
           rng: np.random.Generator) -> tuple[list[EngineRead], int]:
    """Reads over the `days` days ending REFERENCE_END, and how many trips were driven."""
    by_dir = {leg["direction"]: leg for leg in legs}
    reads, trips = [], 0
    p_miss = NoiseConfig().p_miss
    for i in range(days):
        d = REFERENCE_END - timedelta(days=days - 1 - i)
        if d.weekday() not in weekdays:
            continue
        for direction, minute in (("outbound", leave_min), ("return", return_min)):
            leg = by_dir.get(direction)
            if leg is None:
                continue
            trips += 1
            depart = datetime.combine(d, time()) + timedelta(minutes=minute + int(rng.integers(-JITTER_MIN,
                                                                                                JITTER_MIN + 1)))
            for s in leg["steps"]:
                if not s["read"] or s["lon"] is None or rng.random() < p_miss:
                    continue
                reads.append(EngineRead(depart + timedelta(seconds=s["offset_s"]), s["label"], s["lon"], s["lat"]))
    return sorted(reads, key=lambda r: r.time), trips


def _place(anchor, what: str, start, end) -> dict | None:
    if anchor is None:
        return None
    d_start = WGS84.inv(anchor.lon, anchor.lat, *start)[2]
    d_end = WGS84.inv(anchor.lon, anchor.lat, *end)[2]
    nearer, dist = ("start", d_start) if d_start <= d_end else ("end", d_end)
    return {"lon": anchor.lon, "lat": anchor.lat, "radius_m": round(anchor.radius_m), "confidence": anchor.confidence,
            "support_days": anchor.support_days, "possible_days": anchor.possible_days, "what": what,
            "nearer_end": nearer, "distance_m": round(dist)}


def _km(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{round(m / 50) * 50:.0f} m"


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _summary(days: int, trips: int, reads: list[EngineRead], inf, places: dict) -> list[str]:
    kept = "a year" if days == 365 else _n(days, "day")
    if not trips:
        return [f"Over {kept}, none of the chosen days come up, so there are no trips and the history would be "
                "empty."]
    if not reads:
        return [f"Over {kept} ({_n(trips, 'trip')}), no sensor on this route would record it, so the history "
                "would be empty."]
    cams = len({r.camera_label for r in reads})
    lines = [f"Over {kept} ({_n(trips, 'trip')}): {_n(len(reads), 'read')} on {_n(inf.days_with_reads, 'day')} at "
             f"{_n(cams, 'sensor')}."]
    if inf.regular:
        p = inf.regular[0]
        more = f", plus {len(inf.regular) - 1} more" if len(inf.regular) > 1 else ""
        lines.append(f"The read times form a regular pattern: {p.camera_label} around {_hhmm(p.minute_of_day)} on "
                     f"{_days_text(p.weekdays)}{more}.")
    else:
        lines.append("Too few days to see a regular pattern in the read times.")
    for key in ("overnight", "daytime"):
        pl = places.get(key)
        if pl:
            lines.append(f"The gaps between reads suggest where the car {pl['what']}: within about "
                         f"{_km(pl['radius_m'])} ({pl['confidence']} confidence), {_km(pl['distance_m'])} from "
                         f"the route's {pl['nearer_end']}.")
    if not places.get("overnight") and not places.get("daytime"):
        lines.append("The gaps between reads are not enough to suggest where the car stays.")
    return lines


def route_history(legs: list[dict], start: tuple[float, float], end: tuple[float, float],
                  weekdays: tuple[int, ...] = (0, 1, 2, 3, 4), leave_min: int = 8 * 60, return_min: int = 17 * 60 + 30,
                  retention_days: tuple[int, ...] = RETENTION_DAYS, seed: int = 0) -> dict:
    """`legs` from check_route; start/end are (lon, lat). One entry per retention period, shortest first.

    Each period is drawn from the same simulated year (the most recent `days` of it), so a longer period
    always contains the shorter ones.
    """
    year, _ = _reads(legs, max(retention_days), weekdays, leave_min, return_min, np.random.default_rng(seed))
    periods = []
    for days in sorted(set(retention_days)):
        cutoff = datetime.combine(REFERENCE_END - timedelta(days=days - 1), time())
        reads = [r for r in year if r.time >= cutoff]
        trips = sum(1 for i in range(days)
                    if (REFERENCE_END - timedelta(days=i)).weekday() in weekdays) * len(legs)
        inf = infer(reads)
        places = {k: v for k, v in (("overnight", _place(inf.home, "stays overnight", start, end)),
                                    ("daytime", _place(inf.work, "stays during the day", start, end))) if v}
        periods.append({
            "days": days,
            "trips": trips,
            "reads": len(reads),
            "days_with_reads": inf.days_with_reads,
            "sensors_read": len({r.camera_label for r in reads}),
            "regular": [{"sensor_label": p.camera_label, "camera_label": p.camera_label, "time": _hhmm(p.minute_of_day), "days": p.days,
                         "weekdays": list(p.weekdays)} for p in inf.regular],
            "places": places,
            "summary": _summary(days, trips, reads, inf, places),
        })
    return {
        "schedule": {"weekdays": list(weekdays), "leave": _hhmm(leave_min), "return": _hhmm(return_min),
                     "variation_min": JITTER_MIN},
        "periods": periods,
        "assumptions": [
            f"The route is driven on the chosen days, leaving within {JITTER_MIN} minutes of the usual times.",
            f"Each pass that would record does so, except about {NoiseConfig().p_miss:.0%} missed reads.",
            "Estimates use the same inference engine as the example study: long gaps between reads are treated "
            "as stays, and repeated reads at similar times as a routine.",
        ],
        "stored": False,
    }
