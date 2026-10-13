"""Population runs: many synthetic drivers under one configuration.

Each driver i gets its own routine (rng [seed, i]), a unique synthetic plate
(state ZZ) and its own noise stream (seed * 100_000 + i). All drivers share
the cameras, including one density scenario drawn once per population.
Only reads and per-driver ground truth are stored. Trips can be reproduced
from the configuration.

    python -m platetrail.population --drivers 1000 --weeks 1 --seed 0 [--extra-cameras 92]
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
from sqlalchemy import Engine, text

from platetrail.sim.matcher import MatchConfig
from platetrail.sim.noise import NoiseConfig, apply_noise, true_passes
from platetrail.sim.plates import SYNTHETIC_STATE, synthetic_plate
from platetrail.sim.trip import CameraSet


@dataclass(frozen=True)
class PopulationRequest:
    drivers: int = 1000
    weeks: int = 1
    start: date = date(2026, 10, 12)
    seed: int = 0
    generator: str = "nhts"
    match: MatchConfig = field(default_factory=MatchConfig)
    noise: NoiseConfig | None = None  # None: defaults; each driver gets seed * 100_000 + i
    extra_cameras: int = 0
    scenario_town: str = "Edison"


@dataclass
class PopulationDriver:
    idx: int
    persona: str
    plate: str
    anchors: dict
    trips: int
    reads: list  # noise.Read
    sim: object = None  # DriverSimulation, only with keep_sim=True (for evaluation)


def _place_json(p) -> dict:
    return {"key": p.key, "category": p.category, "lon": p.lon, "lat": p.lat, "town": p.town, "name": p.name}


def simulate_population(runner, request: PopulationRequest, progress=None, keep_sim: bool = False):
    """Returns (drivers, cameras used, scenario json or None). `runner` is a LocalRunner."""
    from platetrail.sim.driver import simulate_routine
    from platetrail.sim.runner import SimulationRequest

    report = progress or (lambda stage, done, total: None)
    cameras, scenario = runner.cameras, None
    if request.extra_cameras > 0:
        from platetrail.sim.scenarios import synthetic_cameras

        sims, recs = synthetic_cameras(
            runner.router, request.extra_cameras, request.seed, within=runner.towns.get(request.scenario_town),
            existing=[(c.lon, c.lat) for c in runner.cameras.by_id.values() if c.lon is not None])
        cameras = CameraSet(list(runner.cameras.by_id.values()) + sims)
        scenario = {"extra_cameras": request.extra_cameras, "town": request.scenario_town,
                    "cameras": [r.as_json() for r in recs]}
    gen = runner.make_generator(SimulationRequest(generator=request.generator))
    start = datetime.combine(request.start, time())
    end = start + timedelta(weeks=request.weeks, days=1)  # night shifts may end the following Monday
    base_noise = request.noise or NoiseConfig()
    plates: set[str] = set()
    drivers = []
    for i in range(request.drivers):
        report("drivers", i, request.drivers)
        rng = np.random.default_rng([request.seed, i])
        routine = gen.generate(i, request.start, request.weeks, rng)
        sim = simulate_routine(runner.router, cameras, routine, request.match)
        plate = synthetic_plate(rng)
        while plate in plates:  # unique plates within the population
            plate = synthetic_plate(rng)
        plates.add(plate)
        tp = true_passes(sim.captured, plate)
        noise_cfg = NoiseConfig(**{**base_noise.__dict__, "seed": request.seed * 100_000 + i})
        noisy = apply_noise(tp, start, end, noise_cfg, list(cameras.by_id))
        drivers.append(PopulationDriver(i, routine.template, plate,
                                        {k: _place_json(v) for k, v in routine.anchors.items()},
                                        len(sim.trips), noisy.reads, sim if keep_sim else None))
    report("drivers", request.drivers, request.drivers)
    return drivers, cameras, scenario


def _config_json(cfg) -> dict:
    out = {}
    for k, v in cfg.__dict__.items():
        if k == "extra_read_errors":
            v = [type(e).__name__ for e in v]
        out[k] = v.value if hasattr(v, "value") else v
    return out


def store_population(engine: Engine, request: PopulationRequest, drivers, cameras: CameraSet, scenario) -> int:
    label = {cid: c.label for cid, c in cameras.by_id.items()}
    reads_total = sum(len(d.reads) for d in drivers)
    summary = {
        "drivers": len(drivers),
        "reads": reads_total,
        "reads_per_driver_median": float(np.median([len(d.reads) for d in drivers])) if drivers else 0.0,
        "drivers_never_read": sum(1 for d in drivers if not d.reads),
        "misreads": sum(1 for d in drivers for r in d.reads if r.misread),
    }
    with engine.begin() as conn:
        pid = conn.execute(text(
            "INSERT INTO populations (drivers, weeks, start_date, seed, generator, match_config, noise_config, scenario,"
            " camera_snapshot, summary) VALUES (:n, :w, :s, :seed, :g, CAST(:m AS jsonb), CAST(:nc AS jsonb),"
            " CAST(:scn AS jsonb), (SELECT max(loaded_at) FROM cameras), CAST(:sum AS jsonb)) RETURNING id"),
            {"n": request.drivers, "w": request.weeks, "s": request.start, "seed": request.seed, "g": request.generator,
             "m": json.dumps(_config_json(request.match)), "nc": json.dumps(_config_json(request.noise or NoiseConfig())),
             "scn": json.dumps(scenario) if scenario else None, "sum": json.dumps(summary)}).scalar_one()
        conn.execute(text(
            "INSERT INTO population_drivers (population_id, driver_idx, persona, plate_state, plate, anchors, trips, reads)"
            " VALUES (:p, :i, :persona, :st, :plate, CAST(:a AS jsonb), :t, :r)"),
            [{"p": pid, "i": d.idx, "persona": d.persona, "st": SYNTHETIC_STATE, "plate": d.plate,
              "a": json.dumps(d.anchors), "t": d.trips, "r": len(d.reads)} for d in drivers])
        rows = [{"p": pid, "i": d.idx, "c": label.get(r.camera_id, str(r.camera_id)), "t": r.time,
                 "st": r.state, "pl": r.plate, "m": r.misread} for d in drivers for r in d.reads]
        if rows:
            conn.execute(text(
                "INSERT INTO population_reads (population_id, driver_idx, camera_label, time, plate_state, plate, misread)"
                " VALUES (:p, :i, :c, :t, :st, :pl, :m)"), rows)
    return pid


def run_population(runner, request: PopulationRequest, progress=None) -> int:
    drivers, cameras, scenario = simulate_population(runner, request, progress)
    if progress:
        progress("storing", 0, 1)
    return store_population(runner.engine, request, drivers, cameras, scenario)


def load_population_reads(engine: Engine, population_id: int):
    """(reads as analysis.unicity.TraceRead, {driver_idx: true identity}, drivers rows)."""
    from platetrail.analysis.unicity import TraceRead

    with engine.connect() as conn:
        drivers = conn.execute(text(
            "SELECT driver_idx, persona, plate_state, plate, anchors, trips, reads FROM population_drivers"
            " WHERE population_id = :p ORDER BY driver_idx"), {"p": population_id}).mappings().all()
        reads = [TraceRead(r.driver_idx, f"{r.plate_state} {r.plate}", r.camera_label, r.time)
                 for r in conn.execute(text(
                     "SELECT driver_idx, plate_state, plate, camera_label, time FROM population_reads"
                     " WHERE population_id = :p ORDER BY time"), {"p": population_id})]
    truth = {d["driver_idx"]: f"{d['plate_state']} {d['plate']}" for d in drivers}
    return reads, truth, drivers


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivers", type=int, default=1000)
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--generator", choices=["nhts", "template"], default="nhts")
    ap.add_argument("--extra-cameras", type=int, default=0)
    args = ap.parse_args()
    from platetrail.sim.service import get_local_runner

    req = PopulationRequest(args.drivers, args.weeks, seed=args.seed, generator=args.generator,
                            extra_cameras=args.extra_cameras)
    last = [-1]

    def progress(stage, done, total):
        if stage == "drivers" and done * 10 // max(total, 1) != last[0]:
            last[0] = done * 10 // max(total, 1)
            print(f"  {stage} {done}/{total}", flush=True)

    pid = run_population(get_local_runner(), req, progress)
    print(f"Stored population {pid}")


if __name__ == "__main__":
    main()
