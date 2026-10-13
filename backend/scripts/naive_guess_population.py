"""Naive home/work baseline across the F2 driver population.

    python scripts/naive_guess_population.py [--drivers 300] [--weeks 1] [--seed 0]

Same drivers as simulate_drivers.py (rng [seed, driver]) and default noise.
For each driver, applies platetrail.inference.naive to the noisy read log and
measures the distance from each guess to the true home and work/school
anchor. A naive baseline, not the planned inference engine.
"""

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np

from platetrail.db import get_engine
from platetrail.inference.naive import MIN_DAYS, LogRead, naive_home_work
from platetrail.roads.graph import load_or_build_graph
from platetrail.routines.places import PlacePool
from platetrail.routines.templates import TEMPLATE_WEIGHTS, TemplateRoutineGenerator
from platetrail.sim.driver import simulate_routine
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.noise import NoiseConfig, apply_noise, true_passes
from platetrail.sim.plates import synthetic_plate
from platetrail.sim.routing import Router
from platetrail.sim.trip import load_camera_set

START = date(2026, 10, 12)


def pct(vals, q):
    return float(np.percentile(vals, q)) if vals else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=300)
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    engine = get_engine()
    router, cameras, pool = Router(load_or_build_graph()), load_camera_set(engine), PlacePool.from_db(engine)
    coords = {c.label: (c.lon, c.lat) for c in cameras.by_id.values()}
    label = {cid: c.label for cid, c in cameras.by_id.items()}
    gen = TemplateRoutineGenerator(pool)
    t0 = datetime.combine(START, datetime.min.time())
    t1 = t0 + timedelta(weeks=args.weeks, days=1)

    rows = defaultdict(list)
    for i in range(args.drivers):
        rng = np.random.default_rng([args.seed, i])
        routine = gen.generate(i, START, args.weeks, rng)
        sim = simulate_routine(router, cameras, routine, MatchConfig())
        tp = true_passes(sim.captured, synthetic_plate(rng))
        noisy = apply_noise(tp, t0, t1, NoiseConfig(seed=args.seed * 100_000 + i), list(cameras.by_id))
        res = naive_home_work([LogRead(r.time, label[r.camera_id]) for r in noisy.reads], coords)
        home = routine.anchors["home"]
        main_anchor = routine.anchors.get("work") or routine.anchors.get("school")
        rows[routine.template].append({
            "reads": len(noisy.reads),
            "possible": res.possible,
            "home_err": res.home.error_m(home.lon, home.lat) if res.home else None,
            "work_err": res.work.error_m(main_anchor.lon, main_anchor.lat) if res.work else None,
            "home_is_top": bool(res.home and res.home.camera_label == res.top_camera),
            "work_is_top": bool(res.work and res.work.camera_label == res.top_camera),
            "same_camera": bool(res.home and res.work and res.home.camera_label == res.work.camera_label),
        })

    print(f"Naive baseline (NOT the inference engine): {args.drivers} drivers x {args.weeks} week(s), seed {args.seed}, "
          f"default noise; a guess needs >= {MIN_DAYS} days with >= 2 reads\n")
    hdr = (f"{'template':<14}{'n':>5}{'no guess':>10}{'home med km':>13}{'home p75':>10}{'work med km':>13}"
           f"{'work p75':>10}{'home=top':>10}{'work=top':>10}{'home=work':>11}{'home<1km':>10}{'work<1km':>10}")
    print(hdr)
    for name in list(TEMPLATE_WEIGHTS) + ["ALL"]:
        rs = [r for n in TEMPLATE_WEIGHTS for r in rows[n]] if name == "ALL" else rows.get(name, [])
        if not rs:
            continue
        g = [r for r in rs if r["possible"]]
        he = [r["home_err"] / 1000 for r in g]
        we = [r["work_err"] / 1000 for r in g if r["work_err"] is not None]
        share = lambda k: sum(r[k] for r in g) / len(g) if g else float("nan")  # noqa: E731
        print(f"{name:<14}{len(rs):>5}{1 - len(g) / len(rs):>10.0%}{pct(he, 50):>13.2f}{pct(he, 75):>10.2f}"
              f"{pct(we, 50):>13.2f}{pct(we, 75):>10.2f}{share('home_is_top'):>10.0%}{share('work_is_top'):>10.0%}"
              f"{share('same_camera'):>11.0%}{(sum(e < 1 for e in he) / len(he) if he else float('nan')):>10.0%}"
              f"{(sum(e < 1 for e in we) / len(we) if we else float('nan')):>10.0%}")
    print("\nErrors are over drivers with a guess. 'home=top' / 'work=top': the guess is simply the driver's "
          "most-read camera. 'home=work': both guesses are the same camera.")


if __name__ == "__main__":
    main()
