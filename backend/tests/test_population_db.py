from datetime import date

import pytest
from sqlalchemy import text

from platetrail.analysis.unicity import unicity
from platetrail.population import PopulationRequest, load_population_reads, run_population
from platetrail.routines.places import PlacePool
from platetrail.sim.noise import NoiseConfig
from platetrail.sim.routing import Router
from platetrail.sim.runner import LocalRunner
from platetrail.sim.trip import CameraSet
from test_runner_db import PLAZA, FixedGenerator
from test_trip import pair_on_main_st, toy_graph

pytestmark = pytest.mark.db


class Toy(LocalRunner):
    def make_generator(self, request):
        return FixedGenerator()


@pytest.fixture(scope="module")
def runner(engine):
    return Toy(Router(toy_graph()), CameraSet(list(pair_on_main_st().by_id.values())), PlacePool([PLAZA], []), engine)


def test_population_stores_drivers_and_reads(runner, engine):
    req = PopulationRequest(drivers=6, weeks=1, start=date(2026, 10, 12), seed=2, noise=NoiseConfig.noiseless())
    seen = []
    pid = run_population(runner, req, progress=lambda s, d, t: seen.append((s, d, t)))
    reads, truth, drivers = load_population_reads(engine, pid)
    assert len(drivers) == 6 and len(truth) == 6
    assert len({d["plate"] for d in drivers}) == 6  # unique plates
    assert all(d["plate_state"] == "ZZ" for d in drivers)
    # Fixed routine: each weekday out and back past the Main St pair -> 2 captures/day, 10/week per driver.
    assert all(d["reads"] == 10 for d in drivers) and len(reads) == 60
    assert ("drivers", 6, 6) in seen
    with engine.connect() as conn:
        summary = conn.execute(text("SELECT summary FROM populations WHERE id = :p"), {"p": pid}).scalar_one()
    assert summary["drivers"] == 6 and summary["reads"] == 60 and summary["drivers_never_read"] == 0


def test_identical_routines_are_not_unique(runner, engine):
    # All drivers drive the same fixed routine at the same times: nobody can be singled out.
    pid = run_population(runner, PopulationRequest(drivers=4, weeks=1, start=date(2026, 10, 12), seed=3,
                                                   noise=NoiseConfig.noiseless()))
    reads, truth, _ = load_population_reads(engine, pid)
    assert unicity(reads, truth, p=2).unique_share == 0.0
