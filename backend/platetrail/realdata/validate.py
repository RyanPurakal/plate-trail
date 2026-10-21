"""Real-data validation: run a person's own Google Timeline through the cameras.

The Timeline gives real places and real drive times. Each drive between two
visits becomes a planned trip; the trips are routed and matched against the
real cameras with the usual sensor noise, exactly as for a synthetic driver.
Then the naive baseline and the inference engine run on the resulting read
log, and their home / work estimates are compared with the places the
Timeline labels Home and Work.

Privacy: everything happens in this process. Nothing is written to the
database, the route cache is bypassed (use_cache=False), and the report
prints distances and counts, never coordinates.

    python -m platetrail.realdata.validate path/to/Timeline.json [--weeks 4] [--start 2025-03-03] [--json]

Assumptions (see docs/assumptions.md):
* routes are the simulator's fastest paths between the visit locations, not
  the recorded GPS path;
* a gap between two visits with no activity recorded counts as a drive when
  the visits are more than 1 km apart (UNASSUMED_DRIVE_M);
* a place labelled HOME / WORK (or TYPE_HOME / TYPE_WORK) is "confirmed";
  INFERRED_HOME / INFERRED_WORK is Google's guess and is reported as such; if
  neither exists, home is the place with the most overnight hours and work the
  non-home place with the most weekday daytime hours ("derived").
"""

import argparse
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np

from platetrail.realdata.timeline import Timeline, Visit, load
from platetrail.routines.base import PlannedTrip, Routine, RoutineGenerator
from platetrail.routines.places import Place

SAME_PLACE_M = 150  # visits closer than this (without a place id) are the same place
UNASSUMED_DRIVE_M = 1000


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    dx = (a[0] - b[0]) * 111_320 * math.cos(lat)
    dy = (a[1] - b[1]) * 110_540
    return math.hypot(dx, dy)


@dataclass
class TimelinePlace:
    key: str
    lon: float
    lat: float
    visits: list[Visit] = field(default_factory=list)

    def hours(self, pred) -> float:
        """Hours of this place's visits that fall in hours h of the day for which pred(datetime) is true."""
        total = 0.0
        for v in self.visits:
            t = v.start.replace(minute=0, second=0, microsecond=0)
            while t < v.end:
                nxt = t + timedelta(hours=1)
                if pred(t):
                    total += (min(nxt, v.end) - max(t, v.start)).total_seconds() / 3600
                t = nxt
        return total

    def semantic(self) -> set[str]:
        return {(v.semantic or "").upper() for v in self.visits}


def group_places(visits: list[Visit]) -> tuple[list[TimelinePlace], dict[int, TimelinePlace]]:
    """Places by place id, else by proximity. Returns places and {visit index: place}."""
    places: list[TimelinePlace] = []
    by_id: dict[str, TimelinePlace] = {}
    of: dict[int, TimelinePlace] = {}
    for i, v in enumerate(visits):
        p = by_id.get(v.place_id) if v.place_id else None
        if p is None:
            p = next((q for q in places if _dist_m((q.lon, q.lat), (v.lon, v.lat)) < SAME_PLACE_M), None)
        if p is None:
            p = TimelinePlace(f"timeline/{len(places)}", v.lon, v.lat)
            places.append(p)
        if v.place_id:
            by_id.setdefault(v.place_id, p)
        p.visits.append(v)
        of[i] = p
    return places, of


def _overnight(t: datetime) -> bool:
    return t.hour < 5


def _weekday_day(t: datetime) -> bool:
    return t.weekday() < 5 and 9 <= t.hour < 16


def truth_anchors(places: list[TimelinePlace]) -> dict[str, tuple[TimelinePlace, str]]:
    """{"home"/"work": (place, source)} with source confirmed / google_inferred / derived."""
    out = {}
    for kind, confirmed, inferred in (("home", {"HOME", "TYPE_HOME"}, {"INFERRED_HOME"}),
                                      ("work", {"WORK", "TYPE_WORK"}, {"INFERRED_WORK"})):
        for source, labels in (("confirmed", confirmed), ("google_inferred", inferred)):
            cands = [p for p in places if p.semantic() & labels]
            if cands:
                out[kind] = (max(cands, key=lambda p: len(p.visits)), source)
                break
    if "home" not in out and places:
        best = max(places, key=lambda p: p.hours(_overnight))
        if best.hours(_overnight) > 0:
            out["home"] = (best, "derived")
    if "work" not in out:
        home = out.get("home", (None,))[0]
        cands = [p for p in places if p is not home and len({v.start.date() for v in p.visits if v.start.weekday() < 5}) >= 3]
        if cands:
            best = max(cands, key=lambda p: p.hours(_weekday_day))
            if best.hours(_weekday_day) >= 10:
                out["work"] = (best, "derived")
    return out


@dataclass
class TimelineTrips:
    trips: list[tuple[TimelinePlace, TimelinePlace, datetime, str]]  # origin, dest, depart, basis
    walked_or_transit: int = 0
    assumed: int = 0  # no activity recorded, treated as a drive by distance


def drives(tl: Timeline, of: dict[int, TimelinePlace]) -> TimelineTrips:
    """Drives between consecutive visits: a vehicle activity in the gap, or (none recorded) > 1 km apart."""
    out = TimelineTrips([])
    mi = 0
    for i in range(len(tl.visits) - 1):
        a, b = tl.visits[i], tl.visits[i + 1]
        pa, pb = of[i], of[i + 1]
        if pa is pb:
            continue
        while mi < len(tl.moves) and tl.moves[mi].end <= a.start:
            mi += 1
        gap = [m for m in tl.moves[mi:] if m.start < b.start + timedelta(minutes=5) and m.end > a.end - timedelta(minutes=5)]
        if any(m.mode == "drive" for m in gap):
            depart = min(m.start for m in gap if m.mode == "drive")
            out.trips.append((pa, pb, max(depart, a.start), "vehicle"))
        elif any(m.mode == "other" for m in gap):
            out.walked_or_transit += 1
        elif _dist_m((pa.lon, pa.lat), (pb.lon, pb.lat)) > UNASSUMED_DRIVE_M:
            out.trips.append((pa, pb, a.end, "assumed"))
            out.assumed += 1
    return out


class TimelineGenerator(RoutineGenerator):
    """Returns the fixed routine built from the timeline (ignores rng)."""

    def __init__(self, routine: Routine):
        self.routine = routine

    def generate(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        return self.routine


def _place(p: TimelinePlace, category: str) -> Place:
    return Place(p.key, category, p.lon, p.lat, name=category)


def default_start(tl: Timeline, weeks: int) -> date:
    """Monday such that [start, start + weeks) ends at the last full week of the timeline."""
    last = max(v.end for v in tl.visits).date()
    end_monday = last - timedelta(days=last.weekday())  # Monday of the last (partial) week
    return end_monday - timedelta(weeks=weeks)


def build_routine(tl: Timeline, start: date, weeks: int, in_area) -> tuple[Routine, dict, dict]:
    """(routine, truth {kind: (lon, lat, source)}, counts). in_area((lon, lat)) -> bool."""
    places, of = group_places(tl.visits)
    truth = truth_anchors(places)
    found = drives(tl, of)
    t0, t1 = datetime.combine(start, time()), datetime.combine(start + timedelta(weeks=weeks), time())
    cat = {id(p): kind for kind, (p, _) in truth.items()}
    trips, outside = [], 0
    in_period = [t for t in found.trips if t0 <= t[2] < t1]
    for o, d, depart, _ in in_period:
        if not (in_area((o.lon, o.lat)) and in_area((d.lon, d.lat))):
            outside += 1
            continue
        trips.append(PlannedTrip(_place(o, cat.get(id(o), "other")), _place(d, cat.get(id(d), "other")), depart,
                                 cat.get(id(d), "other")))
    anchors = {kind: _place(p, kind) for kind, (p, _) in truth.items()}
    counts = {"visits": len(tl.visits), "places": len(places), "drives_total": len(found.trips),
              "drives_assumed": found.assumed, "walk_or_transit_gaps": found.walked_or_transit,
              "drives_in_period": len(in_period), "drives_outside_area": outside, "drives_simulated": len(trips)}
    truth_out = {kind: (p.lon, p.lat, source) for kind, (p, source) in truth.items()}
    return Routine(0, "timeline", anchors, trips), truth_out, counts


def evaluate(runner, tl: Timeline, weeks: int = 4, start: date | None = None, seed: int = 0) -> dict:
    """Simulate the timeline's drives on the cameras and score the analyses. Stores nothing."""
    from platetrail.api.queries import inference, naive_guess
    from platetrail.sim.routing import AnchorTooFar
    from platetrail.sim.runner import SimulationRequest, summarize

    if not tl.visits:
        raise ValueError("timeline has no visits")
    start = start or default_start(tl, weeks)
    if start.weekday() != 0:
        start -= timedelta(days=start.weekday())

    def in_area(ll):
        try:
            runner.router.snap_point(*ll)
            return True
        except AnchorTooFar:
            return False

    routine, truth, counts = build_routine(tl, start, weeks, in_area)
    report = {"format": tl.format, "period": {"start": start.isoformat(), "weeks": weeks}, "counts": counts,
              "truth_sources": {k: v[2] for k, v in truth.items()}}
    if not routine.trips:
        report["note"] = "no drives inside the study area in this period; nothing to simulate"
        return report
    out = runner.simulate(SimulationRequest(weeks=weeks, start=start, seed=seed),
                          generator=TimelineGenerator(routine), use_cache=False)
    cams = out.cameras or runner.cameras
    label = {cid: c.label for cid, c in cams.by_id.items()}
    coords = {c.label: (c.lon, c.lat) for c in cams.by_id.values() if c.lon is not None}
    reads = [{"camera_label": label.get(r.camera_id, ""), "time": r.time, "plate_state": r.state, "plate": r.plate}
             for r in out.noise.reads]
    anchors = {k: {"lon": v[0], "lat": v[1], "name": k, "category": k} for k, v in truth.items()}
    naive = naive_guess(reads, coords, anchors)
    eng = inference(reads, coords, anchors, f"ZZ {out.plate}")

    def km(x):
        return None if x is None or x.get("error_m") is None else round(x["error_m"] / 1000, 2)

    report["simulation"] = summarize(out)
    report["naive"] = {"possible": naive["possible"], "home_error_km": km(naive["home"]), "work_error_km": km(naive["work"])}
    report["engine"] = {
        "reads_used": eng["reads_used"],
        "home_error_km": km(eng["home"]), "home_confidence": (eng["home"] or {}).get("confidence"),
        "work_error_km": km(eng["work"]), "work_confidence": (eng["work"] or {}).get("confidence"),
        "regular_passes": len(eng["regular"]), "anomalies": len(eng["anomalies"]),
        "conclusions": len(eng["conclusions"]),
    }
    return report


def format_report(r: dict) -> str:
    c = r["counts"]
    lines = [
        f"Timeline ({r['format']} export), {r['period']['weeks']} weeks from {r['period']['start']}",
        f"  {c['visits']} visits at {c['places']} places; {c['drives_total']} drives found "
        f"({c['drives_assumed']} assumed from distance), {c['walk_or_transit_gaps']} walk/transit gaps",
        f"  in period: {c['drives_in_period']} drives; {c['drives_outside_area']} outside the study area; "
        f"{c['drives_simulated']} simulated",
        "  ground truth: " + (", ".join(f"{k} = {v}" for k, v in r["truth_sources"].items()) or "none found"),
    ]
    if "note" in r:
        return "\n".join(lines + ["  " + r["note"]])
    s, n, e = r["simulation"], r["naive"], r["engine"]

    def f(v):
        return "no estimate" if v is None else f"off by {v:.2f} km"

    lines += [
        f"  cameras: {s['camera_passes']} passes, {s['reads']} reads at {s['distinct_cameras_read']} cameras",
        f"  naive baseline:   home {f(n['home_error_km'])}; work {f(n['work_error_km'])}",
        f"  inference engine: home {f(e['home_error_km'])} ({e['home_confidence'] or '-'}); "
        f"work {f(e['work_error_km'])} ({e['work_confidence'] or '-'})",
        f"                    {e['regular_passes']} regular passes, {e['anomalies']} anomalies flagged",
        "  (nothing was stored; coordinates are not printed)",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--start", type=date.fromisoformat, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    from platetrail.sim.service import get_local_runner

    report = evaluate(get_local_runner(), load(args.path), args.weeks, args.start, args.seed)
    print(json.dumps(report, indent=2) if args.json else format_report(report))


if __name__ == "__main__":
    main()
