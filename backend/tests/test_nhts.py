from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from platetrail.routines.nhts import NHTSRoutineGenerator
from platetrail.routines.nhts_data import load_diaries
from platetrail.geo import WGS84
from platetrail.routines.places import (Place, PlacePool, _distance_weights, sample_by_distance,
                                         sample_home_by_distance)

FIXTURE = Path(__file__).parent / "fixtures" / "nhts"
MONDAY = date(2026, 10, 12)


@pytest.fixture(scope="module")
def data():
    return load_diaries(FIXTURE)


def pool():
    rng = np.random.default_rng(0)
    cats = ["grocery", "retail", "food", "services", "leisure", "worship", "work", "university", "hospital", "industrial"]
    places = [Place(f"place/{i}", cats[i % len(cats)], -74.45 + rng.random() * 0.1, 40.48 + rng.random() * 0.1,
                    "New Brunswick" if i % 3 == 0 or cats[i % len(cats)] == "university" else "Edison")
              for i in range(300)]
    streets = [("1-2-0", LineString([(-74.40, 40.55), (-74.39, 40.55)]), 850.0, "Edison"),
               ("3-4-0", LineString([(-74.45, 40.49), (-74.45, 40.50)]), 1110.0, "New Brunswick")]
    return PlacePool(places, streets)


def test_diary_filters(data):
    by_house = {d.weight: d for d in data.diaries}
    # 1: worker, closed, all driving -> usable; 2: usable; 3: transit -> excluded; 4: no trips -> stay home;
    # 5: non-worker usable; 6: student usable; 7: not a driver -> ignored; 8: missing time -> excluded.
    assert len(data.diaries) == 4
    assert {d.persona for d in data.diaries} == {"worker", "non_worker", "student"}
    worker = by_house[100.0]
    assert [(t.start_min, t.why_to) for t in worker.trips] == [(465, 3), (1035, 13), (1080, 1)]
    assert worker.travday == 2


def test_stay_home_and_excluded_shares(data):
    # Monday workers: house 4 (w=100) stayed home; houses 1, 2, 3, 8 traveled (w=600).
    assert data.stay_home[("worker", 2)] == pytest.approx(100 / 700)
    # Travel-days excluded: houses 3 and 8 (w=200) of 850 traveling driver weight (houses 1, 2, 3, 5, 6, 8).
    assert data.excluded_share == pytest.approx(200 / 850)
    assert data.persona_weight["worker"] == pytest.approx(700)


def test_week_is_a_continuous_chain_using_anchors(data):
    gen = NHTSRoutineGenerator(pool(), data, persona="worker")
    r = gen.generate(1, MONDAY, 2, np.random.default_rng(3))
    assert r.template == "nhts_worker" and "work" in r.anchors
    assert r.trips and r.trips[0].origin == r.anchors["home"] and r.trips[-1].dest == r.anchors["home"]
    for a, b in zip(r.trips, r.trips[1:]):
        assert b.origin == a.dest
        assert b.depart > a.depart
    work_trips = [t for t in r.trips if t.purpose == "work"]
    assert work_trips and all(t.dest == r.anchors["work"] for t in work_trips)
    # Diary times come through (Monday-pool diaries depart 07:45 or 08:00 for work, with fallbacks).
    assert {t.depart.strftime("%H:%M") for t in work_trips} <= {"07:45", "08:00", "07:00"}


def test_deterministic_and_persona_validated(data):
    gen = NHTSRoutineGenerator(pool(), data)
    a = gen.generate(1, MONDAY, 1, np.random.default_rng(7))
    b = gen.generate(1, MONDAY, 1, np.random.default_rng(7))
    assert [(t.dest.key, t.depart) for t in a.trips] == [(t.dest.key, t.depart) for t in b.trips]
    with pytest.raises(ValueError):
        NHTSRoutineGenerator(pool(), data, persona="astronaut")
    with pytest.raises(ValueError):
        gen.generate(1, MONDAY + timedelta(days=1), 1, np.random.default_rng(0))


def test_student_gets_school_anchor(data):
    r = NHTSRoutineGenerator(pool(), data, persona="student").generate(1, MONDAY, 1, np.random.default_rng(1))
    assert r.anchors["school"].category == "university"


def test_distance_matching_prefers_trip_length():
    origin = Place("o", "home", 0.0, 0.0)
    near = Place("near", "grocery", 0.009, 0.0)  # ~1 km
    far = Place("far", "grocery", 0.09, 0.0)  # ~10 km
    p, rng = PlacePool([near, far], []), np.random.default_rng(0)
    short = [sample_by_distance(p, ("grocery",), rng, origin, 1300).key for _ in range(500)]
    long = [sample_by_distance(p, ("grocery",), rng, origin, 13000).key for _ in range(500)]
    assert short.count("near") > 450 and long.count("far") > 450


def test_home_by_distance_matches_per_street_weights():
    # The cached street midpoints and the array distance call give the same draw as computing each street in turn.
    rng = np.random.default_rng(3)
    streets = [(f"{i}-{i + 1}-0", LineString([(-74.45 + rng.random() * 0.1, 40.48 + rng.random() * 0.1),
                                             (-74.45 + rng.random() * 0.1, 40.48 + rng.random() * 0.1)]),
                50.0 + rng.random() * 500, "Edison") for i in range(40)]
    p, origin = PlacePool([], streets), Place("o", "home", -74.41, 40.52)
    mids = [(g.interpolate(0.5, normalized=True).x, g.interpolate(0.5, normalized=True).y) for _, g, _, _ in streets]
    d = np.array([WGS84.inv(origin.lon, origin.lat, x, y)[2] for x, y in mids])
    w = _distance_weights(d, 4000) * np.array([s[2] for s in streets])
    for seed in range(20):
        a, b = np.random.default_rng(seed), np.random.default_rng(seed)
        key, geom, _, _ = streets[int(a.choice(len(w), p=w / w.sum()))]
        pt = geom.interpolate(float(a.random()), normalized=True)
        got = sample_home_by_distance(p, b, origin, 4000)
        assert got.key.startswith(f"home/{key}/") and (got.lon, got.lat) == (pt.x, pt.y)


def test_missing_files_error_is_helpful(tmp_path):
    with pytest.raises(FileNotFoundError, match="--download"):
        load_diaries(tmp_path)


def test_diaries_built_in_code_drive_the_generator():
    # The contract for another routine source (docs/routine_sources.md): diaries, stay-home shares and
    # persona weights built directly, with no survey files and a pool far below MIN_POOL.
    from platetrail.routines.nhts_data import Diary, DiaryTrip, NHTSDiaries

    commute = (DiaryTrip(8 * 60, 3, 6.0), DiaryTrip(17 * 60, 13, 2.0), DiaryTrip(17 * 60 + 40, 1, 4.0))
    errands = (DiaryTrip(10 * 60, 12, 3.0), DiaryTrip(11 * 60, 1, 3.0))
    data = NHTSDiaries(
        diaries=[Diary("worker", 2, 1.0, commute), Diary("worker", 7, 1.0, errands)],
        stay_home={("worker", 1): 1.0},  # nobody drives on Sundays
        persona_weight={"worker": 1.0},
    )
    r = NHTSRoutineGenerator(pool(), data).generate(1, MONDAY, 1, np.random.default_rng(0))
    assert r.template == "nhts_worker"
    assert r.trips[0].origin == r.anchors["home"] and r.trips[-1].dest == r.anchors["home"]
    assert all(t.depart.weekday() != 6 for t in r.trips)
    work = [t for t in r.trips if t.purpose == "work"]
    assert work and {t.depart.strftime("%H:%M") for t in work} == {"08:00"}
