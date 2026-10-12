"""Generate template drivers, simulate them, and summarize coverage per template.

    python scripts/simulate_drivers.py [--drivers 200] [--weeks 1] [--seed 0]

Also prints two checks on the routine generator:
* how far trip endpoints are from the drive network (anchors attach to the
  nearest edge point; more than 100 m is reported);
* whether errand destinations land in camera-covered lots more often than
  places in general do (they shouldn't: sampling never looks at cameras).
"""

import argparse
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import numpy as np
from shapely.geometry import Point

from platetrail.db import get_engine
from platetrail.roads.graph import load_or_build_graph
from platetrail.routines.places import PlacePool
from platetrail.routines.templates import ERRAND_MIX, TEMPLATE_WEIGHTS, TemplateRoutineGenerator
from platetrail.sim.driver import simulate_routine
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.noise import NoiseConfig, apply_noise, true_passes
from platetrail.sim.plates import synthetic_plate
from platetrail.sim.routing import Router
from platetrail.sim.trip import load_camera_set

START = date(2026, 10, 12)  # Monday


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=200)
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    engine = get_engine()
    router, cameras, pool = Router(load_or_build_graph()), load_camera_set(engine), PlacePool.from_db(engine)
    cfg = MatchConfig()
    lot_polys = {c.lot_id: c.lot_geom for c in cameras.lots}
    gen = TemplateRoutineGenerator(pool)
    period = (START, START + timedelta(weeks=args.weeks, days=1))  # +1 day for night shifts ending Monday

    stats = defaultdict(list)
    attach, errand_in_lot, errands = [], 0, 0
    examples = {}
    for i in range(args.drivers):
        rng = np.random.default_rng([args.seed, i])
        routine = gen.generate(i, START, args.weeks, rng)
        sim = simulate_routine(router, cameras, routine, cfg)
        tp = true_passes(sim.captured, synthetic_plate(rng))
        noisy = apply_noise(tp, datetime.combine(period[0], datetime.min.time()),
                            datetime.combine(period[1], datetime.min.time()), NoiseConfig(seed=args.seed * 100_000 + i),
                            list(cameras.by_id))
        cams = Counter(r.camera_id for r in noisy.reads)
        row = {
            "trips": len(sim.trips),
            "km": sum(t.result.route.length_m for t in sim.trips) / 1000,
            "passes": len(sim.passes),
            "captured": len(tp),
            "reads": len(noisy.reads),
            "misreads": len(noisy.misreads),
            "lost_downtime": len(noisy.dropped_for("downtime")),
            "lost_missed": len(noisy.dropped_for("missed")),
            "distinct_cameras": len(cams),
            "top_camera_share": (max(cams.values()) / len(noisy.reads)) if noisy.reads else None,
            "lot_events": sum(1 for p in sim.captured if p.event != "road"),
            "skipped": len(sim.skipped),
        }
        stats[routine.template].append(row)
        examples.setdefault(routine.template, (routine, sim, noisy, row))
        for t in sim.trips:
            attach += [t.result.route.origin.distance_m, t.result.route.dest.distance_m]
            if t.planned.purpose in ERRAND_MIX:
                errands += 1
                pt = Point(t.planned.dest.lon, t.planned.dest.lat)
                errand_in_lot += any(g.covers(pt) for g in lot_polys.values())

    print(f"{args.drivers} drivers x {args.weeks} week(s); match: facing={cfg.facing.value}, "
          f"tolerance={cfg.tolerance_deg:g}, lot_entrance={cfg.lot_entrance.value}; default noise\n")
    keys = ["trips", "km", "passes", "captured", "reads", "misreads", "lost_downtime", "lost_missed",
            "distinct_cameras", "top_camera_share", "lot_events"]
    print(f"{'template':<14}{'n':>5}" + "".join(f"{k[:12]:>14}" for k in keys) + f"{'zero reads':>12}")
    for name in TEMPLATE_WEIGHTS:
        rows = stats.get(name, [])
        if not rows:
            continue
        zero = sum(r["reads"] == 0 for r in rows) / len(rows)
        def mean_of(k):
            vals = [r[k] for r in rows if r[k] is not None]
            return statistics.mean(vals) if vals else float("nan")

        print(f"{name:<14}{len(rows):>5}" + "".join(f"{mean_of(k):>14.2f}" for k in keys) + f"{zero:>11.0%}")
    all_rows = [r for rows in stats.values() for r in rows]
    reads = sorted(r["reads"] for r in all_rows)
    print(f"\nReads per driver-week: median {statistics.median(reads):g}, p25 {np.percentile(reads, 25):g}, "
          f"p75 {np.percentile(reads, 75):g}, max {reads[-1]}; drivers with 0 reads: "
          f"{sum(r == 0 for r in reads) / len(reads):.0%}")
    print(f"Trips skipped (anchor > 500 m from network): {sum(r['skipped'] for r in all_rows)}")
    print("Share of a driver's reads from their single most-read camera (drivers with >= 1 read), median: "
          + ", ".join(
              f"{name} {statistics.median(r['top_camera_share'] for r in stats[name] if r['top_camera_share'] is not None):.0%}"
              for name in TEMPLATE_WEIGHTS if any(r["top_camera_share"] is not None for r in stats.get(name, [])))
          + f"; all {statistics.median(r['top_camera_share'] for r in all_rows if r['top_camera_share'] is not None):.0%}")

    a = np.array(attach)
    print(f"\nAnchor attachment distance to nearest edge (m): median {np.median(a):.0f}, p90 "
          f"{np.percentile(a, 90):.0f}, max {a.max():.0f}; > 100 m: {np.mean(a > 100):.1%} of trip ends")

    places = [p for c in ERRAND_MIX for p in pool.by_category.get(c, [])]
    in_lot = sum(any(g.covers(Point(p.lon, p.lat)) for g in lot_polys.values()) for p in places)
    print(f"Camera-lot check: {errand_in_lot / errands:.1%} of {errands} errand trips end inside a camera-covered lot; "
          f"{in_lot / len(places):.1%} of the {len(places)} errand places lie inside one")

    print("\nOne example driver per template:")
    for name, (routine, sim, noisy, row) in examples.items():
        home, main = routine.anchors["home"], routine.anchors.get("work") or routine.anchors.get("school")
        print(f"  {name} (driver {routine.driver_id}): home {home.town} ({home.lat:.4f},{home.lon:.4f}); "
              f"{'work' if 'work' in routine.anchors else 'school'} {main.category} '{main.name or 'unnamed'}' "
              f"in {main.town}")
        print(f"    trips {row['trips']}, {row['km']:.0f} km, camera passes {row['passes']}, captured {row['captured']}, "
              f"reads after noise {row['reads']}, misreads {row['misreads']}, lost to downtime {row['lost_downtime']}, "
              f"lost to misses {row['lost_missed']}")
        by_cam = Counter(cameras.by_id[p.camera_id].label for p in sim.captured)
        print(f"    captures by camera: {dict(by_cam) or 'none'}")


if __name__ == "__main__":
    main()
