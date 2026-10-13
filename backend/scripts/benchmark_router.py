"""End-to-end benchmark: a 1,000-driver population job with the Python vs. C++ router.

    python scripts/benchmark_router.py [--drivers 1000] [--weeks 1] [--repeats 3]

Each run is a fresh subprocess with PLATETRAIL_ROUTER set and REDIS_URL unset, so the route cache starts empty
(the situation for any new population). Runs alternate python, cpp, python, cpp, ... so drift in machine load
affects both alike. The timed job is what the worker does for POST /jobs/population: simulate every driver and
store the population. Startup (loading the road graph and cameras, and for cpp building the CSR copy) is timed
separately, because the worker does it once per process.

Each run also hashes everything it produced (every trip's route edges and timings, every read), so the benchmark
doubles as a full-scale parity check: both backends must give the same digest. The stored population is deleted
after each run. Needs DATABASE_URL (cameras + places) and the road graph cache. Run with nothing else on the
machine.
"""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time


def child(drivers: int, weeks: int) -> None:
    t0 = time.perf_counter()
    from sqlalchemy import text

    from platetrail.population import PopulationRequest, simulate_population, store_population
    from platetrail.sim.service import get_local_runner

    runner = get_local_runner()
    startup = time.perf_counter() - t0
    req = PopulationRequest(drivers=drivers, weeks=weeks, seed=0)
    t1 = time.perf_counter()
    pop, cameras, scenario = simulate_population(runner, req, keep_sim=True)
    pid = store_population(runner.engine, req, pop, cameras, scenario)
    job = time.perf_counter() - t1

    h = hashlib.sha256()
    for d in pop:
        for t in d.sim.trips:
            r = t.result.route
            h.update(repr([(e.edge, e.frac_from, e.frac_to, e.travel_time_s) for e in r.edges]).encode())
            h.update(repr((r.depart, len(r.coords))).encode())
        for rd in d.reads:
            h.update(repr((d.idx, rd.camera_id, rd.time, rd.state, rd.plate, rd.misread)).encode())
    with runner.engine.begin() as c:
        c.execute(text("DELETE FROM populations WHERE id = :p"), {"p": pid})
    print(json.dumps({"backend": runner.router.backend, "startup_s": round(startup, 2), "job_s": round(job, 2),
                      "trips": sum(len(d.sim.trips) for d in pop), "reads": sum(len(d.reads) for d in pop),
                      "digest": h.hexdigest()[:16]}), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=1000)
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        child(args.drivers, args.weeks)
        return

    env = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
    results = {"python": [], "cpp": []}
    for i in range(args.repeats):
        for backend in ("python", "cpp"):
            out = subprocess.run([sys.executable, __file__, "--child", "--drivers", str(args.drivers),
                                  "--weeks", str(args.weeks)], env={**env, "PLATETRAIL_ROUTER": backend},
                                 capture_output=True, text=True, check=True)
            r = json.loads(out.stdout.strip().splitlines()[-1])
            assert r["backend"] == backend, r
            results[backend].append(r)
            print(f"run {i + 1} {backend:<6} job {r['job_s']:8.1f} s  startup {r['startup_s']:5.1f} s  "
                  f"trips {r['trips']}  reads {r['reads']}  digest {r['digest']}", flush=True)

    digests = {r["digest"] for rs in results.values() for r in rs}
    med = {b: statistics.median(r["job_s"] for r in rs) for b, rs in results.items()}
    print(f"\n{args.drivers} drivers x {args.weeks} week(s), {args.repeats} runs each, cold route cache")
    for b in ("python", "cpp"):
        js = [r["job_s"] for r in results[b]]
        su = statistics.median(r["startup_s"] for r in results[b])
        print(f"  {b:<6} median job {med[b]:8.1f} s (range {min(js):.1f}-{max(js):.1f}), median startup {su:.1f} s")
    print(f"  speedup (median job time): {med['python'] / med['cpp']:.2f}x")
    print(f"  outputs identical across all runs: {'yes' if len(digests) == 1 else 'NO: ' + ', '.join(sorted(digests))}")


if __name__ == "__main__":
    main()
