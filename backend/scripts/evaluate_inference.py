"""Evaluate the inference engine against ground truth and the naive baseline.

    python scripts/evaluate_inference.py [--drivers 300] [--weeks 4] [--seed 0] [--extra-cameras 0]

Drivers are regenerated in memory (same per-driver seeding as populations) so
every read can be traced to its trip. For each driver, both methods see only
the reads recorded under the true plate (an analyst queries by plate).

* home / work error: distance from the estimate to the true anchor;
* schedule recovered: share of observable routine trips (same origin and
  destination at a similar time on >= 3 days, with >= 1 read) whose reads
  match an inferred regular pass on at least half of the trips;
* anomaly precision / recall: true anomalous trips go to a destination
  visited once in the period that is not home, work or school.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date

import numpy as np

from platetrail.inference.engine import EngineRead, infer, routine_trips, schedule_recovery
from platetrail.inference.naive import LogRead, naive_home_work
from platetrail.population import PopulationRequest, simulate_population
from platetrail.sim.service import get_local_runner


def pct(v, q):
    return float(np.percentile(v, q)) if v else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=300)
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--extra-cameras", type=int, default=0)
    ap.add_argument("--generator", choices=["nhts", "template"], default="nhts")
    args = ap.parse_args()

    runner = get_local_runner()
    req = PopulationRequest(args.drivers, args.weeks, date(2026, 10, 12), args.seed, args.generator,
                            extra_cameras=args.extra_cameras)
    drivers, cameras, _ = simulate_population(runner, req, keep_sim=True)
    coords = {c.label: (c.lon, c.lat) for c in cameras.by_id.values()}
    label = {cid: c.label for cid, c in cameras.by_id.items()}

    stats = defaultdict(list)
    sched_rec = sched_obs = 0
    anom_tp = anom_flag = anom_true_seen = anom_true_found = 0
    conf = Counter()
    for d in drivers:
        sim = d.sim
        ordered = sorted(((p, ti) for ti, t in enumerate(sim.trips) for p in t.result.captured),
                         key=lambda x: (x[0].time, x[0].camera_id))
        trip_of_pass = {i: ti for i, (_, ti) in enumerate(ordered)}
        mine = [r for r in d.reads if not r.misread]
        reads = [EngineRead(r.time, label[r.camera_id], *coords[label[r.camera_id]]) for r in mine]
        inf = infer(reads)
        naive = naive_home_work([LogRead(r.time, r.camera_label) for r in reads], coords)
        home = d.anchors["home"]
        main_anchor = d.anchors.get("work") or d.anchors.get("school")
        row = {"persona": d.persona, "reads": len(reads)}
        for kind, est, truth in (("home", inf.home, home), ("work", inf.work, main_anchor)):
            row[f"eng_{kind}"] = est.error_m(truth["lon"], truth["lat"]) if est and truth else None
            row[f"conf_{kind}"] = est.confidence if est else None
            if est:
                conf[(kind, est.confidence)] += 1
        row["naive_home"] = naive.home.error_m(home["lon"], home["lat"]) if naive.home else None
        row["naive_work"] = (naive.work.error_m(main_anchor["lon"], main_anchor["lat"])
                             if naive.work and main_anchor else None)
        row["has_main"] = main_anchor is not None
        stats["all"].append(row)

        # schedule
        trips = [{"trip_id": ti, "origin": t.planned.origin.key, "dest": t.planned.dest.key,
                  "depart": t.result.route.depart} for ti, t in enumerate(sim.trips)]
        reads_by_trip = defaultdict(list)
        for r, er in zip(mine, reads):
            reads_by_trip[trip_of_pass[r.pass_id]].append(er)
        rec, obs = schedule_recovery(routine_trips(trips), reads_by_trip, inf.regular)
        sched_rec += rec
        sched_obs += obs

        # anomalies
        dest_count = Counter(t.planned.dest.key for t in sim.trips)
        anchor_keys = {a["key"] for a in d.anchors.values()}
        true_anom = {ti for ti, t in enumerate(sim.trips)
                     if dest_count[t.planned.dest.key] == 1 and t.planned.dest.key not in anchor_keys}
        flagged_trips = set()
        flagged_times = {(a.time, a.camera_label) for a in inf.anomalies}
        for r, er in zip(mine, reads):
            if (er.time, er.camera_label) in flagged_times:
                anom_flag += 1
                ti = trip_of_pass[r.pass_id]
                flagged_trips.add(ti)
                anom_tp += ti in true_anom
        seen = {ti for ti in true_anom if reads_by_trip.get(ti)}
        anom_true_seen += len(seen)
        anom_true_found += len(seen & flagged_trips)

    rows = stats["all"]
    n = len(rows)

    def summary(key, need_main=False):
        pool = [r for r in rows if r["has_main"]] if need_main else rows
        vals = [r[key] / 1000 for r in pool if r[key] is not None]
        return (f"no estimate {1 - len(vals) / len(pool):.0%}, median {pct(vals, 50):.2f} km, p75 {pct(vals, 75):.2f} km, "
                f"within 1 km {np.mean([v < 1 for v in vals]) if vals else float('nan'):.0%}")

    print(f"Inference evaluation: {n} drivers x {args.weeks} week(s), {args.generator}, seed {args.seed}, "
          f"+{args.extra_cameras} scenario cameras, default noise\n")
    print(f"Home  - engine: {summary('eng_home')}")
    print(f"        naive : {summary('naive_home')}")
    print(f"Work  - engine: {summary('eng_work', True)}   (drivers with a work/school anchor)")
    print(f"        naive : {summary('naive_work', True)}")
    print(f"Schedule recovered: {sched_rec} of {sched_obs} observable routine trips "
          f"({sched_rec / sched_obs if sched_obs else float('nan'):.0%})")
    print(f"Anomalies: precision {anom_tp / anom_flag if anom_flag else float('nan'):.0%} ({anom_tp}/{anom_flag} flagged reads), "
          f"recall {anom_true_found / anom_true_seen if anom_true_seen else float('nan'):.0%} "
          f"({anom_true_found}/{anom_true_seen} observable one-off trips)")
    print("Confidence of estimates: " + ", ".join(f"{k[0]} {k[1]}={v}" for k, v in sorted(conf.items())))
    for kind in ("home", "work"):
        parts = []
        for level in ("high", "medium", "low"):
            v = [r[f"eng_{kind}"] / 1000 for r in rows if r.get(f"conf_{kind}") == level and r[f"eng_{kind}"] is not None]
            if v:
                parts.append(f"{level}: n={len(v)}, median {pct(v, 50):.2f} km")
        print(f"Engine {kind} error by confidence - " + "; ".join(parts))
    print(f"Median reads per driver: {np.median([r['reads'] for r in rows]):.0f}")


if __name__ == "__main__":
    main()
