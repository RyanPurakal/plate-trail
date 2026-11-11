"""Count lot-camera events per camera under each lot_entrance mode.

    python scripts/lot_events_by_mode.py [--drivers 300] [--seed 0]

Uses the same template drivers as simulate_drivers.py (rng seeded by
[seed, driver]). An event is an arrival or departure the camera sees,
whether or not its facing captures it.
"""

import argparse
from collections import Counter
from datetime import date

import numpy as np
from shapely.geometry import Point

from platetrail.db import get_engine
from platetrail.roads.graph import load_or_build_graph
from platetrail.routines.places import PlacePool
from platetrail.routines.templates import TemplateRoutineGenerator
from platetrail.sim.matcher import LotEntrance, MatchConfig
from platetrail.sim.routing import Router
from platetrail.sim.trip import load_camera_set, match_route


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    engine = get_engine()
    router, cams, pool = Router(load_or_build_graph()), load_camera_set(engine), PlacePool.from_db(engine)
    gen = TemplateRoutineGenerator(pool)
    modes = [m.value for m in LotEntrance]
    seen = {m: Counter() for m in modes}
    captured = {m: Counter() for m in modes}
    arrivals = Counter()
    lot_name = {c.lot_id: c.lot_name or c.lot_id for c in cams.lots}
    lot_geom = {c.lot_id: c.lot_geom for c in cams.lots}

    for i in range(args.drivers):
        routine = gen.generate(i, date(2026, 10, 12), 1, np.random.default_rng([args.seed, i]))
        for t in routine.trips:
            o, d = (t.origin.lon, t.origin.lat), (t.dest.lon, t.dest.lat)
            route = router.route(o, d, t.depart)
            for lid, g in lot_geom.items():
                arrivals[lid] += g.covers(Point(d))
            for m in modes:
                for p in match_route(route, cams, o, d, MatchConfig(lot_entrance=m)):
                    if p.event != "road":
                        seen[m][p.label] += 1
                        captured[m][p.label] += p.captured

    print(f"{args.drivers} drivers x 1 week; events seen (captured) per lot camera\n")
    print(f"{'camera':<18}{'lot':<30}" + "".join(f"{m:>20}" for m in modes))
    for c in sorted(cams.lots, key=lambda c: (lot_name[c.lot_id], c.label)):
        print(f"{c.label:<18}{lot_name[c.lot_id][:28]:<30}"
              + "".join(f"{f'{seen[m][c.label]} ({captured[m][c.label]})':>20}" for m in modes))
    print(f"{'TOTAL':<48}" + "".join(f"{f'{sum(seen[m].values())} ({sum(captured[m].values())})':>20}" for m in modes))
    print("\nArrivals into each camera lot: " + ", ".join(f"{lot_name[k]}={v}" for k, v in arrivals.items()))


if __name__ == "__main__":
    main()
