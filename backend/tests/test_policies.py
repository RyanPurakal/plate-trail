from datetime import datetime, timedelta

from platetrail.analysis.policies import compare, retention, round_hour, search_window
from platetrail.analysis.unicity import TraceRead

START = datetime(2026, 10, 12)
END = START + timedelta(weeks=2)
COORDS = {"H1": (-74.40, 40.55), "W1": (-74.45, 40.50), "H2": (-74.30, 40.60), "W2": (-74.35, 40.52)}


def driver_reads(d, home_cam, work_cam):
    out = []
    for day in range(14):
        if day % 7 < 5:
            base = START + timedelta(days=day)
            for h, m, cam in ((7, 50 + d, home_cam), (8, 10 + d, work_cam), (17, 5 + d, work_cam), (17, 30 + d, home_cam)):
                out.append(TraceRead(d, f"ZZ D{d}", cam, base + timedelta(hours=h, minutes=m)))
    return out


READS = driver_reads(1, "H1", "W1") + driver_reads(2, "H2", "W2")
TRUTH = {1: "ZZ D1", 2: "ZZ D2"}
ANCHORS = {1: {"home": {"lon": -74.40, "lat": 40.55}, "work": {"lon": -74.45, "lat": 40.50}},
           2: {"home": {"lon": -74.30, "lat": 40.60}, "work": {"lon": -74.35, "lat": 40.52}}}


def test_retention_keeps_recent_reads_only():
    kept = retention(READS, END, 7)
    assert kept and all(r.time >= END - timedelta(days=7) for r in kept) and len(kept) < len(READS)


def test_round_hour_and_window():
    assert all(r.time.minute == 0 for r in round_hour(READS))
    w = search_window(READS, START, END, 24, seed=1)
    for d in (1, 2):
        times = [r.time for r in w if r.driver_idx == d]
        assert not times or max(times) - min(times) <= timedelta(hours=24)


def test_compare_rows_and_ordering_of_effects():
    rows = {r["policy"]: r for r in compare(READS, TRUTH, ANCHORS, COORDS, START, END)}
    assert {"baseline", "retention_7d", "retention_1d", "round_hour", "window_24h", "aggregate_only"} <= set(rows)
    base, agg = rows["baseline"], rows["aggregate_only"]
    assert base["engine_home"]["estimated"] == 1.0 and base["engine_home"]["median_km"] < 0.1
    assert agg["engine_home"]["estimated"] == 0.0 and agg["unicity_p2"] == 0.0 and agg["reads"] == 0
    assert rows["retention_1d"]["reads"] < rows["retention_7d"]["reads"] < base["reads"]
    assert base["unicity_p2"] == 1.0  # the two drivers use disjoint cameras
