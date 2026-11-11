"""Robustness: rerun the same drivers under each matching / noise assumption, one change at a time.

    python scripts/sensitivity.py [--drivers 300] [--weeks 1] [--seed 0]

Every row uses the same routines (same seeds); only the named assumption differs from the defaults. Columns:
reads per driver (median), share never read, inference-engine home error (median, share within 1 km of all drivers),
and unicity at p = 2 hourly points in this crowd (share of all drivers singled out).
"""

import argparse
from dataclasses import replace
from datetime import date

import numpy as np

from platetrail.analysis.unicity import TraceRead, unicity
from platetrail.inference.engine import EngineRead, infer
from platetrail.population import PopulationRequest, simulate_population
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.noise import NoiseConfig
from platetrail.sim.service import get_local_runner

BASE_M, BASE_N = MatchConfig(), NoiseConfig()
VARIANTS = [
    ("defaults", BASE_M, BASE_N, 0),
    ("tolerance 30°", replace(BASE_M, tolerance_deg=30.0), BASE_N, 0),
    ("tolerance 60°", replace(BASE_M, tolerance_deg=60.0), BASE_N, 0),
    ("capture oncoming", replace(BASE_M, facing="oncoming"), BASE_N, 0),
    ("undirected: worst", replace(BASE_M, undirected="worst"), BASE_N, 0),
    ("ambiguous: alternate tag", replace(BASE_M, ambiguous_direction="alternate"), BASE_N, 0),
    ("lot events: all cameras", replace(BASE_M, lot_entrance="all"), BASE_N, 0),
    ("noise off", BASE_M, NoiseConfig.noiseless(0), 0),
    ("miss rate 15%", BASE_M, replace(BASE_N, p_miss=0.15), 0),
    ("misreads x3", BASE_M, replace(BASE_N, p_char_misread=0.03), 0),
    ("downtime x4", BASE_M, replace(BASE_N, downtime_rate_per_week=1.0), 0),
    ("+92 scenario cameras", BASE_M, BASE_N, 92),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=300)
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    runner = get_local_runner()
    print(f"Sensitivity: {args.drivers} NHTS drivers x {args.weeks} week(s), seed {args.seed}; one change per row\n")
    print(f"{'assumption':<26}{'reads med':>10}{'never read':>12}{'eng home med':>14}{'home <1km':>11}{'unique p2':>11}")
    for name, match, noise, extra in VARIANTS:
        req = PopulationRequest(args.drivers, args.weeks, date(2026, 10, 12), args.seed, "nhts", match=match,
                                noise=noise, extra_cameras=extra)
        drivers, cameras, _ = simulate_population(runner, req)
        label = {cid: c.label for cid, c in cameras.by_id.items()}
        coords = {c.label: (c.lon, c.lat) for c in cameras.by_id.values()}
        errs, traces = [], []
        truth = {d.idx: f"ZZ {d.plate}" for d in drivers}
        for d in drivers:
            traces += [TraceRead(d.idx, f"{r.state} {r.plate}", label[r.camera_id], r.time) for r in d.reads]
            mine = [EngineRead(r.time, label[r.camera_id], *coords[label[r.camera_id]]) for r in d.reads if not r.misread]
            inf = infer(mine)
            if inf.home:
                errs.append(inf.home.error_m(d.anchors["home"]["lon"], d.anchors["home"]["lat"]))
        n = len(drivers)
        u = unicity(traces, truth, 2, 60)
        print(f"{name:<26}{np.median([len(d.reads) for d in drivers]):>10.0f}"
              f"{sum(not d.reads for d in drivers) / n:>12.0%}"
              f"{(np.median(errs) / 1000 if errs else float('nan')):>11.2f} km"
              f"{sum(e < 1000 for e in errs) / n:>11.0%}{u.unique_share * u.eligible / n:>11.0%}", flush=True)


if __name__ == "__main__":
    main()
