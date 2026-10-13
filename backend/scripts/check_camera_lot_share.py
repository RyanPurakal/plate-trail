"""Explain the share of errand trips that end inside camera-covered lots.

    python scripts/check_camera_lot_share.py [--seeds 50] [--drivers 300]

Compares, step by step, what fraction of errand destinations fall inside a
lot polygon that has a lot camera:

  A. raw share of errand places (every place equally likely)
  B. + category mix (ERRAND_MIX), still uniform within each category
  C. + distance decay from sampled homes (exp(-d / DECAY_KM)), no habits
  D. the actual generator (decay from each trip's origin, habits, templates),
     with an interval across seeds
  E. what D's realized category mix alone predicts (uniform within category)

Only routines are generated (no routing), so this is fast. Camera locations
are used here to measure the result, never by the generator.
"""

import argparse
from datetime import date

import numpy as np
from shapely.geometry import Point

from platetrail.db import get_engine
from platetrail.routines.places import PlacePool
from platetrail.routines.templates import DECAY_KM, ERRAND_MIX, TemplateRoutineGenerator
from platetrail.sim.trip import load_camera_set

START = date(2026, 10, 12)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--drivers", type=int, default=300)
    ap.add_argument("--home-samples", type=int, default=20000)
    args = ap.parse_args()

    engine = get_engine()
    pool, cameras = PlacePool.from_db(engine), load_camera_set(engine)
    lots = {c.lot_id: c.lot_geom for c in cameras.lots}

    def in_lot(p) -> bool:
        pt = Point(p.lon, p.lat)
        return any(g.covers(pt) for g in lots.values())

    flags = {p.key: in_lot(p) for c in ERRAND_MIX for p in pool.by_category.get(c, [])}
    print("Share of places inside a camera-covered lot, by errand category:")
    shares = {}
    for c, w in ERRAND_MIX.items():
        ps = pool.by_category.get(c, [])
        shares[c] = sum(flags[p.key] for p in ps) / len(ps)
        print(f"  {c:<9} mix {w:.0%}  places {len(ps):>4}  in camera lots {shares[c]:6.1%}")

    a = sum(flags.values()) / len(flags)
    b = sum(w * shares[c] for c, w in ERRAND_MIX.items()) / sum(ERRAND_MIX.values())

    rng = np.random.default_rng(12345)
    cats, weights = list(ERRAND_MIX), np.array(list(ERRAND_MIX.values())) / sum(ERRAND_MIX.values())
    hits = 0
    for _ in range(args.home_samples):
        home = pool.sample_home(rng)
        c = cats[int(rng.choice(len(cats), p=weights))]
        hits += flags[pool.sample(c, rng, near=home, decay_km=DECAY_KM).key]
    c_share = hits / args.home_samples

    gen, per_seed = TemplateRoutineGenerator(pool), []
    realized = {c: 0 for c in ERRAND_MIX}
    for seed in range(args.seeds):
        n = k = 0
        for i in range(args.drivers):
            r = gen.generate(i, START, 1, np.random.default_rng([seed, i]))
            for t in r.trips:
                if t.purpose in ERRAND_MIX:
                    n += 1
                    realized[t.purpose] += 1
                    k += flags.get(t.dest.key, False)
        per_seed.append(k / n)
    d = np.array(per_seed)

    print(f"\nA. raw share of errand places in camera lots:          {a:6.1%}")
    print(f"B. + category mix, uniform within category:            {b:6.1%}")
    print(f"C. + distance decay from homes ({args.home_samples} samples):        {c_share:6.1%}")
    print(f"D. actual generator, {args.seeds} seeds x {args.drivers} drivers: mean {d.mean():6.1%}, "
          f"95% interval {np.percentile(d, 2.5):.1%}-{np.percentile(d, 97.5):.1%} (seed 0: {d[0]:.1%})")
    total = sum(realized.values())
    e = sum(realized[c] / total * shares[c] for c in ERRAND_MIX)
    print(f"E. D's realized category mix, uniform within category:  {e:6.1%}   ("
          + ", ".join(f"{c} {realized[c] / total:.0%}" for c in ERRAND_MIX) + ")")


if __name__ == "__main__":
    main()
