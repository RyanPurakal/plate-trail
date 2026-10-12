"""Simulate one synthetic driver's week and compare zero noise to default noise.

    python scripts/demo_week.py [--seed 0] [--runs 1000]

This uses a single hand-written commuter week (Edison home, New Brunswick
work, a Saturday mall trip) as a stand-in until the step 6 routine generator
exists. The anchors are illustrative points, not sampled places.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta

import numpy as np

from platetrail.db import get_engine
from platetrail.roads.graph import load_or_build_graph
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.noise import NoiseConfig, apply_noise, true_passes
from platetrail.sim.plates import SYNTHETIC_STATE, synthetic_plate
from platetrail.sim.routing import Router
from platetrail.sim.trip import load_camera_set, simulate_trip

HOME = (-74.3775, 40.5860)  # residential street off Timber Oaks Rd, Edison (lon, lat)
WORK = (-74.4474, 40.5009)  # Rutgers College Ave campus, New Brunswick
MALL = (-74.33545, 40.54717)  # Menlo Park Mall
WEEK_START = datetime(2026, 10, 12)  # a Monday


def week_trips() -> list[tuple[str, tuple, tuple, datetime]]:
    trips = []
    for day in range(5):
        d = WEEK_START + timedelta(days=day)
        trips.append(("home->work", HOME, WORK, d.replace(hour=7, minute=45)))
        trips.append(("work->home", WORK, HOME, d.replace(hour=17, minute=15)))
    sat = WEEK_START + timedelta(days=5)
    trips.append(("home->mall", HOME, MALL, sat.replace(hour=13)))
    trips.append(("mall->home", MALL, HOME, sat.replace(hour=15, minute=30)))
    return trips


def summarize(result) -> dict:
    return {
        "reads": len(result.reads),
        "misreads": len(result.misreads),
        "lost_downtime": len(result.dropped_for("downtime")),
        "lost_missed": len(result.dropped_for("missed")),
        "distinct_plates": len({(r.state, r.plate) for r in result.reads}),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--runs", type=int, default=1000, help="noise seeds for the averages")
    args = p.parse_args()

    router = Router(load_or_build_graph())
    cameras = load_camera_set(get_engine())
    cfg = MatchConfig()
    plate = synthetic_plate(np.random.default_rng(args.seed))

    passes, captured = [], []
    for _, o, d, t in week_trips():
        r = simulate_trip(router, cameras, o, d, t, cfg)
        passes += r.passes
        captured += r.captured
    tp = true_passes(captured, plate)
    period = (WEEK_START, WEEK_START + timedelta(weeks=1))
    all_ids = list(cameras.by_id)

    zero = apply_noise(tp, *period, NoiseConfig.noiseless(args.seed), all_ids)
    default = apply_noise(tp, *period, NoiseConfig(seed=args.seed), all_ids)

    print(f"Synthetic plate {SYNTHETIC_STATE} {plate}; match config: facing={cfg.facing.value}, tolerance={cfg.tolerance_deg:g}, "
          f"lot_entrance={cfg.lot_entrance.value}")
    print(f"Trips: {len(week_trips())}   camera passes: {len(passes)}   "
          f"captured by matcher (true passes): {len(tp)}   skipped for direction: "
          f"{sum(1 for x in passes if not x.captured)}")
    print(f"Cameras involved: {dict(Counter(cameras.by_id[x.camera_id].label for x in tp))}\n")

    z, d = summarize(zero), summarize(default)
    print(f"{'':<36}{'zero noise':>12}{'default noise (seed ' + str(args.seed) + ')':>30}")
    for k, label in [("reads", "reads after noise"), ("misreads", "misread reads"),
                     ("lost_downtime", "lost to downtime"), ("lost_missed", "lost to missed reads"),
                     ("distinct_plates", "distinct (state, plate) identities")]:
        print(f"{label:<36}{z[k]:>12}{d[k]:>30}")

    for r in default.misreads:
        print(f"  misread: pass {r.pass_id} at {r.true_time:%a %H:%M} read as {r.plate} (true {r.true_plate})")

    sums = Counter()
    for s in range(args.runs):
        sums.update(summarize(apply_noise(tp, *period, NoiseConfig(seed=s), all_ids)))
    print(f"\nMean over noise seeds 0-{args.runs - 1} (default noise, same trips and plate): "
          + ", ".join(f"{k}={v / args.runs:.2f}" for k, v in sums.items()))


if __name__ == "__main__":
    main()
