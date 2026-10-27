from datetime import date, datetime, time, timedelta

import numpy as np
import pytest
from sqlalchemy import text

from platetrail.routines.base import PlannedTrip, Routine, RoutineGenerator
from platetrail.routines.places import Place, PlacePool
from platetrail.sim.noise import NoiseConfig
from platetrail.sim.routing import Router
from platetrail.sim.runner import LocalRunner, SimulationRequest
from platetrail.sim.trip import CameraSet
from test_trip import IN_LOT, lot_camera, pair_on_main_st, toy_graph, xy

pytestmark = pytest.mark.db
MONDAY = date(2026, 10, 12)


def place(key, east, north, cat="test"):
    lon, lat = xy(east, north)
    return Place(key, cat, lon, lat, "Edison")


HOME, PLAZA = place("home/x", 0, 5, "home"), place("place/plaza", *IN_LOT, cat="retail")


class FixedGenerator(RoutineGenerator):
    """Home -> plaza at 08:00 and back at 17:00 every weekday (passes the Main St pair, arrives at the lot)."""

    def generate(self, driver_id, start, weeks, rng):
        trips = []
        for d in (start + timedelta(days=i) for i in range(7 * weeks)):
            if d.weekday() < 5:
                trips.append(PlannedTrip(HOME, PLAZA, datetime.combine(d, time(8)), "retail"))
                trips.append(PlannedTrip(PLAZA, HOME, datetime.combine(d, time(17)), "home"))
        return Routine(driver_id, "fixed", {"home": HOME, "usual_retail": PLAZA}, trips)


@pytest.fixture(scope="module")
def runner(engine):
    cams = CameraSet(list(pair_on_main_st().by_id.values()) + [lot_camera(["into_lot"])])
    return LocalRunner(Router(toy_graph()), cams, PlacePool([PLAZA], []), engine, generator=FixedGenerator())


def rows(engine, run_id, sql):
    with engine.connect() as conn:
        return conn.execute(text(sql), {"r": run_id}).all()


def test_zero_noise_run_stores_ground_truth_and_identical_read_log(runner, engine):
    run_id = runner.run(SimulationRequest(weeks=1, start=MONDAY, seed=3, noise=NoiseConfig.noiseless(3)))
    (run,) = rows(engine, run_id, "SELECT generator, weeks, plate, plate_state, summary, anchors FROM runs WHERE id = :r")
    assert run.generator == "template:fixed" and run.weeks == 1 and run.plate_state == "ZZ"
    assert set(run.anchors) == {"home", "usual_retail"}
    trips = rows(engine, run_id, "SELECT seq, purpose, depart, arrive, ST_NPoints(route_geom) n FROM trips WHERE run_id = :r ORDER BY seq")
    assert len(trips) == 10 and all(t.n >= 2 and t.arrive > t.depart for t in trips)

    passes = rows(engine, run_id, "SELECT id, captured, noise_outcome, time, event, camera_label FROM camera_passes"
                                  " WHERE run_id = :r ORDER BY pass_seq")
    # Per weekday: out-trip passes the pair (1 captured) + lot arrival (captured); return passes the pair
    # (1 captured) + lot departure (seen, into_lot camera -> not captured).
    assert len(passes) == 5 * 6
    captured = [p for p in passes if p.captured]
    assert len(captured) == 5 * 3
    assert all(p.noise_outcome == "read" for p in captured)
    assert all(p.noise_outcome is None for p in passes if not p.captured)

    reads = rows(engine, run_id, "SELECT r.pass_id, r.time, r.plate, r.misread, p.time AS true_time FROM reads r"
                                 " JOIN camera_passes p ON p.id = r.pass_id WHERE r.run_id = :r ORDER BY r.read_seq")
    assert len(reads) == len(captured)
    assert all(r.time == r.true_time and r.plate == run.plate and not r.misread for r in reads)
    assert run.summary["reads"] == len(reads) and run.summary["captured"] == len(captured)


def test_noisy_run_links_every_read_to_a_captured_pass(runner, engine):
    noisy = NoiseConfig(seed=5, p_miss=0.3, p_char_misread=0.3, downtime_rate_per_week=5, downtime_mean_hours=12,
                        jitter_sd_s=10)
    run_id = runner.run(SimulationRequest(weeks=2, start=MONDAY, seed=5, noise=noisy))
    (run,) = rows(engine, run_id, "SELECT plate, summary FROM runs WHERE id = :r")
    outcomes = rows(engine, run_id, "SELECT noise_outcome, count(*) n FROM camera_passes WHERE run_id = :r AND captured"
                                    " GROUP BY 1")
    counts = {o.noise_outcome: o.n for o in outcomes}
    reads = rows(engine, run_id, "SELECT r.plate, r.misread, p.captured, p.noise_outcome FROM reads r"
                                 " JOIN camera_passes p ON p.id = r.pass_id WHERE r.run_id = :r")
    assert len(reads) == counts.get("read", 0)
    assert all(r.captured and r.noise_outcome == "read" for r in reads)
    assert all(r.misread == (r.plate != run.plate) for r in reads)
    assert counts.get("missed", 0) > 0 and any(r.misread for r in reads)
    assert run.summary["lost_downtime"] == counts.get("downtime", 0)
    assert rows(engine, run_id, "SELECT count(*) n FROM camera_outages WHERE run_id = :r")[0].n > 0


def test_same_request_stores_identical_run(runner, engine):
    req = SimulationRequest(weeks=1, start=MONDAY, seed=11)
    a, b = runner.run(req), runner.run(req)
    q_reads = "SELECT read_seq, camera_label, time, plate, jitter_s FROM reads WHERE run_id = :r ORDER BY read_seq"
    q_passes = "SELECT pass_seq, camera_label, time, captured, noise_outcome FROM camera_passes WHERE run_id = :r ORDER BY pass_seq"
    assert rows(engine, a, q_reads) == rows(engine, b, q_reads)
    assert rows(engine, a, q_passes) == rows(engine, b, q_passes)
    assert rows(engine, a, "SELECT plate, summary FROM runs WHERE id = :r") == \
           rows(engine, b, "SELECT plate, summary FROM runs WHERE id = :r")


def test_runs_survive_camera_reload(runner, engine):
    run_id = runner.run(SimulationRequest(weeks=1, start=MONDAY, seed=1))
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE cameras RESTART IDENTITY CASCADE"))
    assert rows(engine, run_id, "SELECT count(*) n FROM reads WHERE run_id = :r")[0].n > 0


def test_weeks_validated(runner):
    with pytest.raises(ValueError):
        runner.run(SimulationRequest(weeks=0))


def test_density_scenario_stored_with_run(engine):
    from test_trip import toy_graph

    G = toy_graph()
    for _, _, d in G.edges(data=True):
        d["highway"] = "tertiary"
    cams = CameraSet(list(pair_on_main_st().by_id.values()))
    runner = LocalRunner(Router(G), cams, PlacePool([PLAZA], []), engine, generator=FixedGenerator())
    base = runner.run(SimulationRequest(weeks=1, start=MONDAY, seed=4, noise=NoiseConfig.noiseless(4)))
    dense = runner.run(SimulationRequest(weeks=1, start=MONDAY, seed=4, noise=NoiseConfig.noiseless(4),
                                         extra_cameras=3))
    (scn,) = rows(engine, dense, "SELECT scenario FROM runs WHERE id = :r")
    assert scn.scenario["extra_cameras"] == 3 and len(scn.scenario["cameras"]) == 3
    assert scn.scenario["town"] is None  # no town polygons on the toy runner: whole network
    assert rows(engine, base, "SELECT scenario FROM runs WHERE id = :r")[0].scenario is None
    labels = {r.camera_label for r in rows(engine, dense, "SELECT camera_label FROM camera_passes WHERE run_id = :r")}
    real = {r.camera_label for r in rows(engine, base, "SELECT camera_label FROM camera_passes WHERE run_id = :r")}
    assert real <= labels  # real cameras still passed
    assert all(l in real or l.startswith("scenario/4/") for l in labels)
