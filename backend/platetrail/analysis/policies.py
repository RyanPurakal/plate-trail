"""Policy comparison: how much each agency policy reduces what a read log reveals.

Each policy transforms a population's read log (what an analyst could query).
Then the same measurements run on what remains:

* inference: share of drivers with a home / work estimate, median error, and
  share within 1 km (inference engine and naive baseline), using the reads
  under each driver's true plate;
* unicity at p = 2 and p = 4 (hourly points), with recorded plates as
  identities.

Policies (levers from the proposal):
* retention_<d>d: keep only reads from the last d days before the query
  (the end of the period). Retention longer than the simulated period
  equals keeping everything.
* round_hour: recorded timestamps floored to the hour. Unicity is measured at
  15-minute points both with and without rounding, which shows what rounding
  removes.
* aggregate_only: only hourly counts per camera are released, with no plates.
  Nothing per vehicle can be inferred, and nobody can be singled out.
* window_<h>h: an analyst may search a plate only within +-h/2 hours of an
  incident time (random per driver, seeded), not its whole history.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import numpy as np

from platetrail.analysis.unicity import TraceRead, unicity
from platetrail.inference.engine import EngineRead, infer
from platetrail.inference.naive import LogRead, naive_home_work


@dataclass(frozen=True)
class Policy:
    name: str
    description: str


def retention(reads: list[TraceRead], end: datetime, days: int) -> list[TraceRead]:
    cutoff = end - timedelta(days=days)
    return [r for r in reads if r.time >= cutoff]


def round_hour(reads: list[TraceRead]) -> list[TraceRead]:
    return [replace(r, time=r.time.replace(minute=0, second=0, microsecond=0)) for r in reads]


def search_window(reads: list[TraceRead], start: datetime, end: datetime, hours: float, seed: int = 0):
    rng = np.random.default_rng([seed, int(hours * 10)])
    span = (end - start).total_seconds()
    incident: dict[int, datetime] = {}
    out = []
    for r in reads:
        if r.driver_idx not in incident:
            incident[r.driver_idx] = start + timedelta(seconds=float(rng.random() * span))
        if abs((r.time - incident[r.driver_idx]).total_seconds()) <= hours * 1800:
            out.append(r)
    return out


def _metrics(reads: list[TraceRead], truth_identity: dict[int, str], anchors: dict[int, dict], coords: dict,
             unicity_resolution: int = 60) -> dict:
    by_driver: dict[int, list[TraceRead]] = {d: [] for d in truth_identity}
    for r in reads:
        if r.identity == truth_identity.get(r.driver_idx):
            by_driver[r.driver_idx].append(r)
    res = {"eng_home": [], "eng_work": [], "naive_home": [], "eng_home_n": 0, "eng_work_n": 0, "naive_home_n": 0,
           "with_main": 0}
    for d, rs in by_driver.items():
        er = [EngineRead(r.time, r.camera_label, *coords[r.camera_label]) for r in rs if r.camera_label in coords]
        inf = infer(er)
        naive = naive_home_work([LogRead(r.time, r.camera_label) for r in er], coords)
        home = anchors[d]["home"]
        main = anchors[d].get("work") or anchors[d].get("school")
        res["with_main"] += main is not None
        if inf.home:
            res["eng_home_n"] += 1
            res["eng_home"].append(inf.home.error_m(home["lon"], home["lat"]))
        if inf.work and main:
            res["eng_work_n"] += 1
            res["eng_work"].append(inf.work.error_m(main["lon"], main["lat"]))
        if naive.home:
            res["naive_home_n"] += 1
            res["naive_home"].append(naive.home.error_m(home["lon"], home["lat"]))
    n = len(truth_identity)

    def stat(errs, count, denom):
        return {"estimated": round(count / denom, 4) if denom else 0.0,
                "median_km": round(float(np.median(errs)) / 1000, 3) if errs else None,
                "within_1km": round(float(np.mean([e < 1000 for e in errs])), 4) if errs else 0.0,
                "within_1km_of_all": round(sum(e < 1000 for e in errs) / denom, 4) if denom else 0.0}

    u2 = unicity(reads, truth_identity, 2, unicity_resolution)
    u4 = unicity(reads, truth_identity, 4, unicity_resolution)
    return {
        "reads": len(reads),
        "engine_home": stat(res["eng_home"], res["eng_home_n"], n),
        "engine_work": stat(res["eng_work"], res["eng_work_n"], res["with_main"]),
        "naive_home": stat(res["naive_home"], res["naive_home_n"], n),
        "unicity_p2": round(u2.unique_share * u2.eligible / n, 4) if n else 0.0,  # share of ALL drivers singled out
        "unicity_p4": round(u4.unique_share * u4.eligible / n, 4) if n else 0.0,
        "unicity_resolution_min": unicity_resolution,
    }


def compare(reads: list[TraceRead], truth_identity: dict[int, str], anchors: dict[int, dict], coords: dict,
            start: datetime, end: datetime, seed: int = 0) -> list[dict]:
    """Rows of {policy, description, metrics...}, starting with the unrestricted baseline."""
    days = (end - start).days
    rows = [("baseline", f"all {days} days of reads, exact times", reads, 60)]
    for d in (28, 14, 7, 1):
        if d < days:
            rows.append((f"retention_{d}d", f"keep only the last {d} day(s)", retention(reads, end, d), 60))
    rows.append(("baseline_15min", "all reads, unicity at 15-minute points", reads, 15))
    rows.append(("round_hour", "timestamps rounded to the hour (unicity at 15-minute points)", round_hour(reads), 15))
    rows.append(("window_72h", "plate searchable only within +-36 h of an incident",
                 search_window(reads, start, end, 72, seed), 60))
    rows.append(("window_24h", "plate searchable only within +-12 h of an incident",
                 search_window(reads, start, end, 24, seed), 60))
    out = [{"policy": name, "description": desc, **_metrics(rs, truth_identity, anchors, coords, res)}
           for name, desc, rs, res in rows]
    empty = _metrics([], truth_identity, anchors, coords)
    out.append({"policy": "aggregate_only", "description": "only hourly counts per camera released (no plates)",
                **empty, "reads": 0})
    return out
