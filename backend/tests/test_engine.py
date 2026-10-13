from datetime import datetime, timedelta

import pytest

from platetrail.inference.engine import (
    EngineRead,
    infer,
    regular_passes,
    routine_trips,
    schedule_recovery,
    stay_evidence,
)

HOME_CAM = ("home_cam", -74.400, 40.550)
WORK_CAM = ("work_cam", -74.450, 40.500)
ODD_CAM = ("odd_cam", -74.300, 40.600)
MON = datetime(2026, 10, 12)


def rd(day, h, m, cam):
    return EngineRead(MON + timedelta(days=day, hours=h, minutes=m), cam[0], cam[1], cam[2])


def commuter(weeks=2, odd=False):
    out = []
    for day in range(7 * weeks):
        if (day % 7) < 5:
            out += [rd(day, 7, 50, HOME_CAM), rd(day, 8, 10, WORK_CAM), rd(day, 17, 5, WORK_CAM), rd(day, 17, 30, HOME_CAM)]
    if odd:
        out.append(rd(5, 13, 0, ODD_CAM))
    return out


def test_stay_evidence_kinds():
    ev = stay_evidence(commuter(weeks=1))
    kinds = {e.kind for e in ev}
    assert kinds == {"night", "day_long"}
    assert all(e.kind != "day_long" or 8.5 < e.hours < 9.5 for e in ev)


def test_commuter_home_and_work_found_with_confidence():
    inf = infer(commuter(weeks=2))
    assert inf.home and inf.work
    assert inf.home.error_m(*HOME_CAM[1:]) < 50 and inf.work.error_m(*WORK_CAM[1:]) < 50
    assert inf.home.confidence == "high" and inf.work.confidence == "high"
    assert inf.home.radius_m >= 500 and inf.home.nearest_camera == "home_cam"
    assert any("Likely lives" in c for c in inf.conclusions)


def test_regular_passes_and_weekday_text():
    reg = regular_passes(commuter(weeks=2))
    assert {(p.camera_label, p.weekdays) for p in reg} == {("home_cam", (0, 1, 2, 3, 4)), ("work_cam", (0, 1, 2, 3, 4))}
    assert any(p.minute_of_day == 7 * 60 + 50 and p.days == 10 for p in reg)
    assert any("on weekdays" in c for c in infer(commuter()).conclusions)


def test_one_off_read_is_an_anomaly():
    inf = infer(commuter(weeks=2, odd=True))
    assert [a.camera_label for a in inf.anomalies] == ["odd_cam"]


def test_empty_and_sparse_logs():
    assert infer([]).home is None and "No reads" in infer([]).conclusions[-1]
    sparse = infer([rd(0, 8, 0, HOME_CAM)])
    assert sparse.home is None and sparse.work is None


def test_low_confidence_with_little_support():
    reads = [rd(0, 18, 0, HOME_CAM), rd(1, 8, 0, HOME_CAM)]  # one night
    inf = infer(reads)
    assert inf.home and inf.home.confidence == "low"


def test_routine_trips_and_schedule_recovery():
    trips = [{"trip_id": f"{d}a", "origin": "H", "dest": "W", "depart": MON + timedelta(days=d, hours=7, minutes=45)}
             for d in range(5)]
    trips.append({"trip_id": "x", "origin": "H", "dest": "S", "depart": MON + timedelta(hours=12)})
    routines = routine_trips(trips)
    assert routines == [[f"{d}a" for d in range(5)]]
    reads_by_trip = {f"{d}a": [rd(d, 7, 50, HOME_CAM)] for d in range(5)}
    regular = regular_passes([r for rs in reads_by_trip.values() for r in rs])
    assert schedule_recovery(routines, reads_by_trip, regular) == (1, 1)
    assert schedule_recovery(routines, {}, regular) == (0, 0)  # unobservable routine


def test_clustering_handles_coincident_and_nearby_points():
    from platetrail.inference.engine import Evidence, _cluster

    same = [Evidence("night", -74.4, 40.5, "2026-10-12", 10.0)] * 6
    assert len(set(_cluster(same))) == 1
    near_far = [Evidence("night", -74.4, 40.5, "d", 1), Evidence("night", -74.4001, 40.5, "d", 1),
                Evidence("night", -74.3, 40.6, "d", 1)]
    labels = _cluster(near_far)
    assert labels[0] == labels[1] != labels[2]
    many = [Evidence("short", -74.4 + i * 0.02, 40.5, "d", 1) for i in range(8)] * 2
    assert len(_cluster(many)) == 16
