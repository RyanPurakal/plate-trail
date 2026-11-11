"""Timeline importer: parsing all three export formats, and a synthetic round trip through the simulator."""

from datetime import date, datetime, time, timedelta

import numpy as np
import pytest

from platetrail.realdata.synthetic import routine_to_timeline
from platetrail.realdata.timeline import parse
from platetrail.realdata.validate import build_routine, evaluate
from platetrail.routines.base import PlannedTrip, Routine
from platetrail.routines.places import Place, PlacePool
from platetrail.sim.noise import NoiseConfig
from platetrail.sim.routing import Router
from platetrail.sim.runner import LocalRunner
from platetrail.sim.trip import CameraSet
from test_trip import IN_LOT, lot_camera, pair_on_main_st, toy_graph, xy

MONDAY = date(2026, 10, 12)


def place(key, east, north, cat):
    lon, lat = xy(east, north)
    return Place(key, cat, lon, lat, "Edison")


HOME, WORK = place("home/x", 0, 5, "home"), place("place/plaza", *IN_LOT, cat="work")


def commute(weeks=2) -> Routine:
    trips = []
    for d in (MONDAY + timedelta(days=i) for i in range(7 * weeks)):
        if d.weekday() < 5:
            trips.append(PlannedTrip(HOME, WORK, datetime.combine(d, time(8)), "work"))
            trips.append(PlannedTrip(WORK, HOME, datetime.combine(d, time(17)), "home"))
    return Routine(0, "fixed", {"home": HOME, "work": WORK}, trips)


@pytest.mark.parametrize("fmt", ["android", "iphone", "takeout"])
def test_round_trip_recovers_drives_and_labels(fmt):
    tl = parse(routine_to_timeline(commute(), fmt))
    assert tl.format == fmt
    assert len(tl.visits) == 21 and len(tl.moves) == 20 and all(m.mode == "drive" for m in tl.moves)
    assert tl.visits[1].start.hour == 8  # local wall-clock time survives the offset round trip
    routine, truth, counts = build_routine(tl, MONDAY, 2, lambda ll: True)
    assert counts["drives_total"] == 20 and counts["drives_assumed"] == 0 and counts["drives_simulated"] == 20
    assert {k: v[2] for k, v in truth.items()} == {"home": "confirmed", "work": "confirmed"}
    assert abs(truth["home"][0] - HOME.lon) < 1e-5 and abs(truth["work"][1] - WORK.lat) < 1e-5
    assert [t.depart for t in routine.trips] == [t.depart for t in commute().trips]
    assert [t.dest.category for t in routine.trips[:2]] == ["work", "home"]


def test_coordinate_and_mode_parsing():
    tl = parse({"semanticSegments": [
        {"startTime": "2026-10-12T00:00:00.000-04:00", "endTime": "2026-10-12T07:50:00.000-04:00",
         "visit": {"topCandidate": {"semanticType": "INFERRED_HOME", "placeLocation": {"latLng": "40.5200000°, -74.3600000°"}}}},
        {"startTime": "2026-10-12T07:50:00.000-04:00", "endTime": "2026-10-12T08:20:00.000-04:00",
         "activity": {"topCandidate": {"type": "WALKING"}}},
        {"startTime": "2026-10-12T12:20:00Z", "endTime": "2026-10-12T20:00:00Z",
         "visit": {"topCandidate": {"semanticType": "UNKNOWN", "placeLocation": {"latLng": "40.5300000°, -74.3300000°"}}}},
        {"timelinePath": [{"point": "40.5°, -74.3°", "time": "2026-10-12T08:00:00Z"}]},
    ]})
    assert (tl.visits[0].lon, tl.visits[0].lat) == (-74.36, 40.52)
    assert tl.visits[1].start == datetime(2026, 10, 12, 8, 20)  # UTC -> EDT
    assert tl.moves[0].mode == "other"
    routine, truth, counts = build_routine(tl, MONDAY, 1, lambda ll: True)
    assert counts["walk_or_transit_gaps"] == 1 and not routine.trips  # walked, so no drive
    assert truth["home"][2] == "google_inferred"


def test_unrecorded_gap_is_a_drive_only_when_far():
    seg = lambda s, e, lat, lon: {"startTime": s, "endTime": e, "visit": {"topCandidate": {  # noqa: E731
        "placeLocation": f"geo:{lat},{lon}"}}}
    tl = parse([seg("2026-10-12T00:00:00-04:00", "2026-10-12T08:00:00-04:00", 40.52, -74.36),
                seg("2026-10-12T08:30:00-04:00", "2026-10-12T09:00:00-04:00", 40.5205, -74.3605),  # ~70 m: same place
                seg("2026-10-12T09:30:00-04:00", "2026-10-12T17:00:00-04:00", 40.54, -74.33)])     # ~3 km
    routine, truth, counts = build_routine(tl, MONDAY, 1, lambda ll: True)
    assert counts["places"] == 2 and counts["drives_assumed"] == 1
    assert routine.trips[0].depart == datetime(2026, 10, 12, 9)
    assert truth["home"][2] == "derived"  # most overnight hours


def test_unrecognised_file_is_rejected():
    with pytest.raises(ValueError):
        parse({"locations": []})


def test_evaluate_scores_engine_and_baseline_without_storing():
    cams = CameraSet(list(pair_on_main_st().by_id.values()) + [lot_camera(["into_lot"])])

    class NoDB:
        def __getattr__(self, name):
            raise AssertionError("realdata must not touch the database")

    runner = LocalRunner(Router(toy_graph()), cams, PlacePool([WORK], []), NoDB())
    tl = parse(routine_to_timeline(commute(), "android"))
    # Noise is part of the simulation; seed fixed so the result is stable.
    r = evaluate(runner, tl, weeks=2, start=MONDAY, seed=1)
    assert r["counts"]["drives_simulated"] == 20 and r["truth_sources"]["home"] == "confirmed"
    assert r["simulation"]["reads"] > 0
    assert set(r["engine"]) >= {"home_error_km", "work_error_km", "home_confidence"}

    def keys(o):
        return set(o) | set().union(*(keys(v) for v in o.values() if isinstance(v, dict))) if isinstance(o, dict) else set()

    assert not keys(r) & {"lon", "lat", "coords"}  # the report carries no coordinates
