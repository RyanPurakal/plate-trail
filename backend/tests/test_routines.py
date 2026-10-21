from datetime import date, timedelta

import numpy as np
import pytest
from shapely.geometry import LineString

from platetrail.routines.base import RoutineGenerator
from platetrail.routines.nhts import NHTSRoutineGenerator
from platetrail.routines.places import Place, PlacePool, _classify
from platetrail.routines.templates import MIN_GAP, TEMPLATE_WEIGHTS, TemplateRoutineGenerator

MONDAY = date(2026, 10, 12)


def pool():
    rng = np.random.default_rng(0)
    places = []
    cats = ["grocery", "retail", "food", "services", "leisure", "worship", "work", "university", "hospital", "industrial"]
    for i in range(300):
        cat = cats[i % len(cats)]
        town = "New Brunswick" if cat == "university" or i % 3 == 0 else "Edison"
        places.append(Place(f"place/{i}", cat, -74.45 + rng.random() * 0.1, 40.48 + rng.random() * 0.1, town))
    streets = [
        ("1-2-0", LineString([(-74.40, 40.55), (-74.39, 40.55)]), 850.0, "Edison"),
        ("3-4-0", LineString([(-74.45, 40.49), (-74.45, 40.50)]), 1110.0, "New Brunswick"),
        ("5-6-0", LineString([(-74.38, 40.56), (-74.38, 40.561)]), 111.0, "Edison"),
    ]
    return PlacePool(places, streets)


@pytest.mark.parametrize("template", list(TEMPLATE_WEIGHTS))
def test_routine_is_a_continuous_chain_from_home(template):
    r = TemplateRoutineGenerator(pool(), template).generate(1, MONDAY, 2, np.random.default_rng(3))
    assert r.template == template and r.trips
    assert r.trips[0].origin == r.anchors["home"]
    for a, b in zip(r.trips, r.trips[1:]):
        assert b.origin == a.dest, "each trip starts where the previous one ended"
        assert b.depart >= a.depart + MIN_GAP
    assert r.trips[-1].dest == r.anchors["home"]


@pytest.mark.parametrize("template", list(TEMPLATE_WEIGHTS))
def test_same_seed_same_routine(template):
    gen = TemplateRoutineGenerator(pool(), template)
    a = gen.generate(1, MONDAY, 2, np.random.default_rng(42))
    b = gen.generate(1, MONDAY, 2, np.random.default_rng(42))
    assert [(t.origin.key, t.dest.key, t.depart, t.purpose) for t in a.trips] == \
           [(t.origin.key, t.dest.key, t.depart, t.purpose) for t in b.trips]


def test_commuter_week_shape():
    r = TemplateRoutineGenerator(pool(), "commuter").generate(1, MONDAY, 1, np.random.default_rng(5))
    work_trips = [t for t in r.trips if t.purpose == "work"]
    assert len(work_trips) == 5
    assert all(t.depart.weekday() < 5 and 6 <= t.depart.hour <= 9 for t in work_trips)
    assert all(t.dest == r.anchors["work"] for t in work_trips)


def test_student_school_is_university_in_new_brunswick():
    r = TemplateRoutineGenerator(pool(), "student").generate(1, MONDAY, 1, np.random.default_rng(1))
    assert r.anchors["school"].category == "university" and r.anchors["school"].town == "New Brunswick"
    assert sum(t.purpose == "school" for t in r.trips) >= 4


def test_shift_worker_nights_cross_midnight():
    r = TemplateRoutineGenerator(pool(), "shift_worker").generate(1, MONDAY, 1, np.random.default_rng(2))
    to_work = [t for t in r.trips if t.purpose == "work"]
    assert len(to_work) == 4
    assert all(17 <= t.depart.hour <= 19 for t in to_work)
    back = [t for t in r.trips if t.origin == r.anchors["work"]]
    assert all(b.depart.date() == w.depart.date() + timedelta(days=1) for w, b in zip(to_work, back))
    assert r.anchors["work"].category in ("hospital", "industrial")


def test_start_must_be_monday():
    with pytest.raises(ValueError):
        TemplateRoutineGenerator(pool(), "commuter").generate(1, MONDAY + timedelta(days=1), 1, np.random.default_rng(0))


def test_unknown_template_rejected():
    with pytest.raises(ValueError):
        TemplateRoutineGenerator(pool(), "astronaut")


def test_template_mix_when_unspecified():
    gen = TemplateRoutineGenerator(pool())
    names = [gen.generate(i, MONDAY, 1, np.random.default_rng(i)).template for i in range(300)]
    assert 0.5 < names.count("commuter") / 300 < 0.7


def test_nhts_generator_implements_the_same_interface():
    from pathlib import Path

    from platetrail.routines.nhts_data import load_diaries

    gen = NHTSRoutineGenerator(pool(), load_diaries(Path(__file__).parent / "fixtures" / "nhts"))
    assert isinstance(gen, RoutineGenerator)
    r = gen.generate(1, MONDAY, 1, np.random.default_rng(0))
    assert r.template.startswith("nhts_") and r.anchors["home"].category == "home"


# ---- place pool -------------------------------------------------------------------------

def test_home_sampling_weighted_by_street_length_and_on_street():
    p, rng = pool(), np.random.default_rng(0)
    homes = [p.sample_home(rng, town="Edison") for _ in range(4000)]
    long_street = sum(h.key.startswith("home/1-2-0/") for h in homes) / len(homes)
    assert 0.85 < long_street < 0.92  # 850 / (850 + 111) = 0.885
    assert all(h.category == "home" and h.town == "Edison" for h in homes)
    on_long = [h for h in homes if h.key.startswith("home/1-2-0/")]
    assert all(h.lat == pytest.approx(40.55) and -74.40 <= h.lon <= -74.39 for h in on_long)


def test_errand_sampling_distance_decay():
    near = Place("x", "grocery", 0.0, 0.0)
    far = Place("y", "grocery", 0.1, 0.0)  # ~11 km away
    p, rng = PlacePool([near, far], []), np.random.default_rng(0)
    origin = Place("h", "home", 0.0, 0.0)
    picks = [p.sample("grocery", rng, near=origin, decay_km=4).key for _ in range(2000)]
    assert picks.count("x") / 2000 > 0.9  # exp(-11/4) ~ 0.06 relative weight for the far one
    uniform = [p.sample("grocery", rng).key for _ in range(2000)]
    assert 0.45 < uniform.count("x") / 2000 < 0.55


@pytest.mark.parametrize("tags, expected", [
    ({"shop": "supermarket"}, "grocery"),
    ({"shop": "clothes"}, "retail"),
    ({"amenity": "fast_food"}, "food"),
    ({"amenity": "pharmacy"}, "services"),
    ({"leisure": "fitness_centre"}, "leisure"),
    ({"amenity": "place_of_worship", "religion": "christian"}, "worship"),
    ({"office": "company"}, "work"),
    ({"building": "warehouse"}, "industrial"),
    ({"amenity": "university", "building": "university"}, "university"),
    ({"amenity": "hospital"}, "hospital"),
    ({"building": "industrial", "shop": "car_repair"}, "retail"),  # shop wins over building type
    ({"building": "house"}, None),
    ({"building": "university", "amenity": "post_office"}, "services"),
    ({"building": "university"}, "university"),
])
def test_classify(tags, expected):
    got = _classify(tags)
    assert (got[0] if got else None) == expected


def test_region_without_student_town_draws_students_region_wide():
    from platetrail.region import parse_region

    region = parse_region({"id": "x", "name": "x", "parent_iso3166_2": "US-NJ",
                           "towns": [{"label": "Edison", "osm_name": "Edison", "osm_relation": 1},
                                     {"label": "New Brunswick", "osm_name": "New Brunswick", "osm_relation": 2}]})
    gen = TemplateRoutineGenerator(pool(), "student", region=region)
    homes = {gen.generate(1, MONDAY, 1, np.random.default_rng(s)).anchors["home"].town for s in range(40)}
    assert homes == {"Edison", "New Brunswick"}


def test_student_town_comes_from_region():
    from platetrail.region import parse_region

    region = parse_region({"id": "x", "name": "x", "parent_iso3166_2": "US-NJ", "student_town": "Edison",
                           "student_home_share": 1.0,
                           "towns": [{"label": "Edison", "osm_name": "Edison", "osm_relation": 1},
                                     {"label": "New Brunswick", "osm_name": "New Brunswick", "osm_relation": 2}]})
    p = pool()
    p.by_category["university"].append(Place("place/uni-e", "university", -74.40, 40.55, "Edison"))
    for s in range(10):
        r = TemplateRoutineGenerator(p, "student", region=region).generate(1, MONDAY, 1, np.random.default_rng(s))
        assert r.anchors["home"].town == "Edison"
        assert r.anchors["school"].town == "Edison"
