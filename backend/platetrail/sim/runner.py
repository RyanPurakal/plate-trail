"""Run and store a simulation: one synthetic driver over N weeks.

A SimulationRunner takes a SimulationRequest and returns a stored run id.
LocalRunner does the work synchronously in-process. A queue-backed runner
(Celery, planned) will implement the same interface so the API doesn't
change.

Pipeline: generate routine -> route and match every trip -> number all
camera passes in time order -> apply sensor noise to the captured ones ->
store run, trips, passes, reads and outages in one transaction.

Reproducibility: everything derives from request.seed. The routine uses
rng [seed, 1], the plate uses [seed, 2], and noise uses seed directly with
its own per-camera and per-pass streams. The same request on the same data
gives the same stored run (apart from row ids and created_at).

    python -m platetrail.sim.runner --template commuter --weeks 4 --seed 1
"""

import argparse
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
from shapely.geometry import LineString
from sqlalchemy import Engine, text

from platetrail.db import apply_migrations, get_engine
from platetrail.routines.base import RoutineGenerator
from platetrail.routines.places import Place, PlacePool
from platetrail.routines.templates import TemplateRoutineGenerator
from platetrail.sim.driver import DriverSimulation, simulate_routine
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.noise import NoiseConfig, NoiseResult, TruePass, apply_noise
from platetrail.sim.plates import SYNTHETIC_STATE, synthetic_plate
from platetrail.sim.routing import Router
from platetrail.sim.trip import CameraPass, CameraSet


@dataclass(frozen=True)
class SimulationRequest:
    template: str | None = None  # None: drawn from TEMPLATE_WEIGHTS
    weeks: int = 1
    start: date = date(2026, 10, 12)  # a Monday
    seed: int = 0
    match: MatchConfig = field(default_factory=MatchConfig)
    noise: NoiseConfig | None = None  # None: defaults with seed = request seed

    def noise_config(self) -> NoiseConfig:
        return self.noise if self.noise is not None else NoiseConfig(seed=self.seed)


class SimulationRunner(ABC):
    @abstractmethod
    def run(self, request: SimulationRequest) -> int:
        """Simulate and store; return the run id."""


@dataclass
class SimulationOutput:
    """Everything a run produces, before storage."""

    request: SimulationRequest
    generator: str
    plate: str
    sim: DriverSimulation
    passes: list[tuple[int, int, CameraPass]]  # (pass_seq, trip index, pass), time-ordered
    noise: NoiseResult
    period: tuple[datetime, datetime]


def _config_json(cfg) -> dict:
    out = {}
    for k, v in asdict(cfg).items():
        if k == "extra_read_errors":
            v = [type(e).__name__ for e in getattr(cfg, k)]
        out[k] = v.value if hasattr(v, "value") else v
    return out


def _place_json(p: Place) -> dict:
    return {"key": p.key, "category": p.category, "lon": p.lon, "lat": p.lat, "town": p.town, "name": p.name}


class LocalRunner(SimulationRunner):
    def __init__(self, router: Router, cameras: CameraSet, pool: PlacePool, engine: Engine,
                 generator: RoutineGenerator | None = None):
        self.router, self.cameras, self.pool, self.engine = router, cameras, pool, engine
        self.generator = generator

    @classmethod
    def from_db(cls, engine: Engine | None = None) -> "LocalRunner":
        from platetrail.roads.graph import load_or_build_graph
        from platetrail.sim.trip import load_camera_set

        engine = engine or get_engine()
        apply_migrations(engine)
        return cls(Router(load_or_build_graph()), load_camera_set(engine), PlacePool.from_db(engine), engine)

    def simulate(self, request: SimulationRequest) -> SimulationOutput:
        if request.weeks < 1:
            raise ValueError("weeks must be >= 1")
        gen = self.generator or TemplateRoutineGenerator(self.pool, request.template)
        routine = gen.generate(0, request.start, request.weeks, np.random.default_rng([request.seed, 1]))
        plate = synthetic_plate(np.random.default_rng([request.seed, 2]))
        sim = simulate_routine(self.router, self.cameras, routine, request.match)

        ordered = sorted(
            ((ti, p) for ti, t in enumerate(sim.trips) for p in t.result.passes),
            key=lambda x: (x[1].time, x[0], x[1].camera_id),
        )
        passes = [(seq, ti, p) for seq, (ti, p) in enumerate(ordered)]
        true = [TruePass(seq, p.camera_id, p.time, plate, SYNTHETIC_STATE) for seq, _, p in passes if p.captured]

        start = datetime.combine(request.start, time())
        last = max([t.result.route.arrive for t in sim.trips], default=start)
        end = max(start + timedelta(weeks=request.weeks), last + timedelta(minutes=1))
        noise = apply_noise(true, start, end, request.noise_config(), list(self.cameras.by_id))
        return SimulationOutput(request, f"template:{routine.template}", plate, sim, passes, noise, (start, end))

    def run(self, request: SimulationRequest) -> int:
        return store(self.engine, self.simulate(request), self.cameras)


def summarize(out: SimulationOutput) -> dict:
    n = out.noise
    return {
        "trips": len(out.sim.trips),
        "trips_skipped": len(out.sim.skipped),
        "km": round(sum(t.result.route.length_m for t in out.sim.trips) / 1000, 2),
        "camera_passes": len(out.passes),
        "captured": sum(1 for _, _, p in out.passes if p.captured),
        "reads": len(n.reads),
        "misreads": len(n.misreads),
        "lost_downtime": len(n.dropped_for("downtime")),
        "lost_missed": len(n.dropped_for("missed")),
        "distinct_cameras_read": len({r.camera_id for r in n.reads}),
    }


def store(engine: Engine, out: SimulationOutput, cameras: CameraSet) -> int:
    req, sim = out.request, out.sim
    label = {cid: c.label for cid, c in cameras.by_id.items()}
    outcome: dict[int, str] = {r.pass_id: "read" for r in out.noise.reads}
    outcome.update({d.pass_id: d.reason for d in out.noise.dropped})

    with engine.begin() as conn:
        run_id = conn.execute(
            text("INSERT INTO runs (generator, weeks, start_date, seed, plate, plate_state, match_config,"
                 " noise_config, anchors, summary) VALUES (:g, :w, :s, :seed, :plate, :state, CAST(:m AS jsonb),"
                 " CAST(:n AS jsonb), CAST(:a AS jsonb), CAST(:sum AS jsonb)) RETURNING id"),
            {"g": out.generator, "w": req.weeks, "s": req.start, "seed": req.seed, "plate": out.plate,
             "state": SYNTHETIC_STATE, "m": json.dumps(_config_json(req.match)),
             "n": json.dumps(_config_json(req.noise_config())),
             "a": json.dumps({k: _place_json(p) for k, p in sim.routine.anchors.items()}),
             "sum": json.dumps(summarize(out))},
        ).scalar_one()

        trip_ids = []
        for seq, t in enumerate(sim.trips):
            route = t.result.route
            coords = route.coords if len(route.coords) >= 2 else route.coords * 2
            trip_ids.append(conn.execute(
                text("INSERT INTO trips (run_id, seq, purpose, origin_key, origin_category, dest_key, dest_category,"
                     " planned_depart, depart, arrive, length_m, duration_s, origin_geom, dest_geom, route_geom)"
                     " VALUES (:r, :seq, :purpose, :ok, :oc, :dk, :dc, :pd, :d, :a, :len, :dur,"
                     " ST_SetSRID(ST_MakePoint(:olon, :olat), 4326), ST_SetSRID(ST_MakePoint(:dlon, :dlat), 4326),"
                     " ST_GeomFromText(:wkt, 4326)) RETURNING id"),
                {"r": run_id, "seq": seq, "purpose": t.planned.purpose, "ok": t.planned.origin.key,
                 "oc": t.planned.origin.category, "dk": t.planned.dest.key, "dc": t.planned.dest.category,
                 "pd": t.planned.depart, "d": route.depart, "a": route.arrive, "len": route.length_m,
                 "dur": route.duration_s, "olon": t.planned.origin.lon, "olat": t.planned.origin.lat,
                 "dlon": t.planned.dest.lon, "dlat": t.planned.dest.lat, "wkt": LineString(coords).wkt},
            ).scalar_one())

        pass_row: dict[int, int] = {}
        for seq, ti, p in out.passes:
            pass_row[seq] = conn.execute(
                text("INSERT INTO camera_passes (run_id, trip_id, pass_seq, camera_id, camera_label, time, event,"
                     " travel_bearing_deg, road_name, captured, match_reason, noise_outcome) VALUES (:r, :t, :seq,"
                     " :cid, :lab, :time, :event, :brg, :road, :cap, :reason, :outcome) RETURNING id"),
                {"r": run_id, "t": trip_ids[ti], "seq": seq, "cid": p.camera_id, "lab": label.get(p.camera_id, ""),
                 "time": p.time, "event": p.event, "brg": p.travel_bearing_deg, "road": p.road_name,
                 "cap": p.captured, "reason": p.reason.value, "outcome": outcome.get(seq) if p.captured else None},
            ).scalar_one()

        if out.noise.reads:
            conn.execute(
                text("INSERT INTO reads (run_id, read_seq, pass_id, camera_id, camera_label, time, plate, plate_state,"
                     " misread, jitter_s) VALUES (:r, :seq, :pid, :cid, :lab, :time, :plate, :state, :mis, :jit)"),
                [{"r": run_id, "seq": rd.read_id, "pid": pass_row[rd.pass_id], "cid": rd.camera_id,
                  "lab": label.get(rd.camera_id, ""), "time": rd.time, "plate": rd.plate, "state": rd.state,
                  "mis": rd.misread, "jit": rd.jitter_s} for rd in out.noise.reads],
            )
        outages = [o for ws in out.noise.outages.values() for o in ws]
        if outages:
            conn.execute(
                text("INSERT INTO camera_outages (run_id, camera_id, camera_label, start_time, end_time)"
                     " VALUES (:r, :cid, :lab, :s, :e)"),
                [{"r": run_id, "cid": o.camera_id, "lab": label.get(o.camera_id, ""), "s": o.start, "e": o.end}
                 for o in outages],
            )
    return run_id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", choices=["commuter", "student", "shift_worker"])
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 12))
    ap.add_argument("--zero-noise", action="store_true", help="store the noiseless read log")
    args = ap.parse_args()
    runner = LocalRunner.from_db()
    req = SimulationRequest(args.template, args.weeks, args.start, args.seed,
                            noise=NoiseConfig.noiseless(args.seed) if args.zero_noise else None)
    run_id = runner.run(req)
    with runner.engine.connect() as conn:
        summary, gen, state, plate = conn.execute(
            text("SELECT summary, generator, plate_state, plate FROM runs WHERE id = :i"), {"i": run_id}).one()
    print(f"Stored run {run_id} ({gen}, plate {state} {plate}, {args.weeks} week(s), seed {args.seed}): {summary}")


if __name__ == "__main__":
    main()
