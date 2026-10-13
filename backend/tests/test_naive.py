from datetime import datetime, timedelta

import pytest

from platetrail.inference.naive import LogRead, naive_home_work

CAMS = {"near_home": (-74.40, 40.50), "near_work": (-74.45, 40.50), "elsewhere": (-74.42, 40.55)}
MON = datetime(2026, 10, 12)


def commute_day(day: int, extra=()):
    d = MON + timedelta(days=day)
    reads = [LogRead(d.replace(hour=7, minute=50), "near_home"), LogRead(d.replace(hour=8, minute=5), "near_work"),
             LogRead(d.replace(hour=17, minute=10), "near_work"), LogRead(d.replace(hour=17, minute=30), "near_home")]
    return reads + [LogRead(d.replace(hour=h, minute=m), c) for h, m, c in extra]


def test_commuter_week_guesses_home_and_work():
    reads = [r for day in range(5) for r in commute_day(day)]
    res = naive_home_work(reads, CAMS)
    assert res.possible and res.days_used == 5
    assert res.home.camera_label == "near_home" and res.home.support_days == 5
    assert res.work.camera_label == "near_work" and res.work.support_days == 5
    assert res.home.error_m(-74.40, 40.50) == pytest.approx(0, abs=1)
    assert res.work.error_m(-74.40, 40.50) == pytest.approx(4234, rel=0.01)  # ~0.05 deg lon at 40.5 N


def test_too_few_days_means_no_guess():
    one_day = commute_day(0)
    single_reads = [LogRead(MON + timedelta(days=d, hours=8), "near_home") for d in range(5)]  # 1 read per day
    for reads in (one_day, single_reads, []):
        res = naive_home_work(reads, CAMS)
        assert not res.possible and res.home is None and res.work is None


def test_unknown_cameras_ignored_and_input_order_irrelevant():
    reads = [r for day in range(3) for r in commute_day(day)] + [LogRead(MON.replace(hour=12), "ghost")]
    a = naive_home_work(reads, CAMS)
    b = naive_home_work(list(reversed(reads)), CAMS)
    assert (a.home, a.work) == (b.home, b.work)
    assert a.home.camera_label == "near_home"


def test_top_camera_and_ties_go_to_first_seen():
    reads = [LogRead(MON.replace(hour=8), "elsewhere"), LogRead(MON.replace(hour=18), "near_home"),
             LogRead(MON.replace(day=13, hour=8), "near_home"), LogRead(MON.replace(day=13, hour=18), "elsewhere")]
    res = naive_home_work(reads, CAMS)
    assert res.home.camera_label == "elsewhere"  # 2 votes each; "elsewhere" was seen first
    assert res.top_camera == "elsewhere"


def test_single_camera_driver_gets_same_camera_for_both():
    reads = [LogRead(MON + timedelta(days=d, hours=h), "near_work") for d in range(4) for h in (8, 17)]
    res = naive_home_work(reads, CAMS)
    assert res.home.camera_label == res.work.camera_label == res.top_camera == "near_work"
