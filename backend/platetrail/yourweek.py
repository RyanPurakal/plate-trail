""""Your week" mode: simulate a week the visitor describes, without storing anything.

The visitor gives home and (optionally) work locations, workdays, usual leave
times and how many errands and weekend outings they make. A routine is built
from that, simulated on the real cameras with default matching and noise,
and analysed with the naive baseline and the inference engine.

Nothing is persisted: no database writes, the route cache is bypassed (so
the visitor's places never reach Redis), there is no run cache, and inputs
are not logged. The response exists only in the HTTP reply.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np

from platetrail.routines.base import PlannedTrip, Routine, RoutineGenerator
from platetrail.routines.places import Place, PlacePool
from platetrail.routines.templates import DECAY_KM, ERRAND_MIX, MIN_GAP


@dataclass(frozen=True)
class WeekInput:
    home: tuple[float, float]  # (lon, lat)
    work: tuple[float, float] | None
    workdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # 0 = Monday
    leave_home_min: int = 7 * 60 + 45
    leave_work_min: int = 17 * 60 + 15
    errands_per_week: int = 3
    weekend_outings: int = 2


class YourWeekGenerator(RoutineGenerator):
    def __init__(self, pool: PlacePool, week: WeekInput):
        self.pool, self.week = pool, week

    def generate(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        w = self.week
        home = Place("you/home", "home", w.home[0], w.home[1], name="your home")
        anchors = {"home": home}
        if w.work:
            anchors["work"] = Place("you/work", "work", w.work[0], w.work[1], name="your work")
        trips: list[PlannedTrip] = []

        def add(o, d, t, purpose):
            if trips and t < trips[-1].depart + MIN_GAP:
                t = trips[-1].depart + MIN_GAP
            trips.append(PlannedTrip(o, d, t, purpose))

        cats, probs = list(ERRAND_MIX), np.array(list(ERRAND_MIX.values())) / sum(ERRAND_MIX.values())
        for wk in range(weeks):
            week_start = start + timedelta(weeks=wk)
            weekday_errands = sorted(rng.choice(5, size=min(w.errands_per_week, 5), replace=False).tolist())
            weekend_days = [5 + int(x) for x in rng.choice(2, size=w.weekend_outings, replace=True)]
            for i in range(7):
                d = week_start + timedelta(days=i)
                day0 = datetime.combine(d, time())
                if "work" in anchors and i in w.workdays:
                    jitter = lambda: timedelta(minutes=int(rng.integers(-10, 11)))  # noqa: E731
                    add(home, anchors["work"], day0 + timedelta(minutes=w.leave_home_min) + jitter(), "work")
                    add(anchors["work"], home, day0 + timedelta(minutes=w.leave_work_min) + jitter(), "home")
                outings = (i in weekday_errands) + weekend_days.count(i)
                for k in range(outings):
                    cat = cats[int(rng.choice(len(cats), p=probs))]
                    place = self.pool.sample(cat, rng, near=home, decay_km=DECAY_KM)
                    hour = 18.5 if i < 5 else 10.5 + 3 * k
                    t = day0 + timedelta(minutes=int(hour * 60 + rng.integers(-30, 31)))
                    add(home, place, t, cat)
                    add(place, home, t + timedelta(minutes=int(rng.integers(40, 91))), "home")
        return Routine(driver_id, "your_week", anchors, trips)


def simulate_week(runner, week: WeekInput, weeks: int = 1, seed: int = 0) -> dict:
    """Run-like response (same shape as GET /runs/{id}) built only in memory."""
    from platetrail.api.queries import inference, naive_guess, sensor_names
    from platetrail.sim.runner import SimulationRequest

    out = runner.simulate(SimulationRequest(weeks=weeks, seed=seed), generator=YourWeekGenerator(runner.pool, week),
                          use_cache=False)
    cams = out.cameras or runner.cameras
    label = {cid: c.label for cid, c in cams.by_id.items()}
    coords = {c.label: (c.lon, c.lat) for c in cams.by_id.values() if c.lon is not None}
    outcome = {r.pass_id: "read" for r in out.noise.reads}
    outcome.update({d.pass_id: d.reason for d in out.noise.dropped})
    passes = [sensor_names({"id": seq, "trip_seq": ti, "pass_seq": seq, "camera_id": p.camera_id, "camera_label": label.get(p.camera_id, ""),
               "time": p.time.isoformat(), "event": p.event, "travel_bearing_deg": p.travel_bearing_deg,
               "road_name": p.road_name, "captured": p.captured, "match_reason": p.reason.value,
               "noise_outcome": outcome.get(seq) if p.captured else None}) for seq, ti, p in out.passes]
    reads = [sensor_names({"id": r.read_id, "read_seq": r.read_id, "pass_id": r.pass_id, "camera_id": r.camera_id,
              "camera_label": label.get(r.camera_id, ""), "time": r.time.isoformat(), "true_time": r.true_time.isoformat(),
              "plate_state": r.state, "plate": r.plate, "misread": r.misread, "jitter_s": r.jitter_s})
             for r in out.noise.reads]
    anchors = {k: {"key": p.key, "category": p.category, "lon": p.lon, "lat": p.lat, "town": p.town, "name": p.name}
               for k, p in out.sim.routine.anchors.items()}
    trips = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": t.result.route.coords},
              "properties": {"id": i, "seq": i, "purpose": t.planned.purpose, "origin_key": t.planned.origin.key,
                             "dest_key": t.planned.dest.key, "dest_category": t.planned.dest.category,
                             "planned_depart": t.planned.depart.isoformat(), "depart": t.result.route.depart.isoformat(),
                             "arrive": t.result.route.arrive.isoformat(), "length_m": t.result.route.length_m,
                             "duration_s": t.result.route.duration_s}}
             for i, t in enumerate(out.sim.trips)]
    from platetrail.sim.runner import summarize

    run = {"id": 0, "generator": "your_week", "weeks": weeks, "start_date": out.request.start.isoformat(), "seed": seed,
           "plate": out.plate, "plate_state": "ZZ", "anchors": anchors, "summary": summarize(out), "stale": False,
           "scenario": None, "match_config": {}, "noise_config": {}, "created_at": None}
    return {
        "run": run,
        "naive_guess": naive_guess(reads, coords, anchors),
        "inference": inference(reads, coords, anchors, f"ZZ {out.plate}"),
        "trips": {"type": "FeatureCollection", "features": trips},
        "passes": passes,
        "reads": reads,
        "outages": [],
        "stored": False,
    }
