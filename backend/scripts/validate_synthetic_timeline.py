"""End-to-end importer check on synthetic data: NHTS drivers -> Timeline export -> importer -> scores.

Each synthetic routine is written as a Google Timeline export (cycling through the three formats), parsed back by
platetrail.realdata, and evaluated exactly as a real file would be. Since the Timeline drives are the routine's own
trips, the importer should recover every drive, and the scores show what to expect from a real file.

    python scripts/validate_synthetic_timeline.py --drivers 50 --weeks 4
"""

import argparse
from datetime import date

import numpy as np

from platetrail.realdata.synthetic import routine_to_timeline
from platetrail.realdata.timeline import parse
from platetrail.realdata.validate import evaluate
from platetrail.sim.runner import SimulationRequest
from platetrail.sim.service import get_local_runner

FORMATS = ("android", "iphone", "takeout")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=50)
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    runner = get_local_runner()
    gen = runner.make_generator(SimulationRequest(generator="nhts"))
    start = date(2026, 10, 12)
    rows = []
    for i in range(args.drivers):
        routine = gen.generate(i, start, args.weeks, np.random.default_rng([args.seed, i]))
        tl = parse(routine_to_timeline(routine, FORMATS[i % 3]))
        r = evaluate(runner, tl, args.weeks, start, seed=args.seed * 1000 + i)
        r["planned"] = len(routine.trips)
        rows.append(r)

    def med(xs):
        xs = [x for x in xs if x is not None]
        return f"{np.median(xs):.2f} km" if xs else "-"

    recovered = sum(r["counts"]["drives_total"] for r in rows)
    planned = sum(r["planned"] for r in rows)
    sim = [r for r in rows if "engine" in r]
    print(f"{args.drivers} synthetic NHTS drivers, {args.weeks} weeks, formats {', '.join(FORMATS)}")
    print(f"  drives recovered from the exports: {recovered}/{planned} planned trips")
    print("  (a trip between two visits at the same place, e.g. a round trip with no stop, is not a drive)")
    print(f"  drivers with drives in the study area: {len(sim)}")
    print(f"  reads per driver, median: {np.median([r['simulation']['reads'] for r in sim]):.0f}")
    for name, key in (("engine", "engine"), ("naive", "naive")):
        h = [r[key]["home_error_km"] for r in sim]
        w = [r[key]["work_error_km"] for r in sim]
        print(f"  {name:6} home: {sum(x is not None for x in h)}/{len(sim)} estimated, median error {med(h)}; "
              f"work: {sum(x is not None for x in w)} estimated, median error {med(w)}")
    print("  truth sources:", {s: sum(r["truth_sources"].get("home") == s for r in rows)
                                for s in ("confirmed", "google_inferred", "derived")})


if __name__ == "__main__":
    main()
