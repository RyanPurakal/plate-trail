from datetime import datetime, timedelta

import pytest

from platetrail.analysis.unicity import TraceRead, to_points, unicity

T0 = datetime(2026, 10, 12, 8, 0)


def r(driver, cam, minutes, ident=None):
    return TraceRead(driver, ident or f"ZZ D{driver}", cam, T0 + timedelta(minutes=minutes))


def test_identical_traces_are_never_unique():
    reads = [r(d, cam, m) for d in (1, 2) for cam, m in (("A", 0), ("B", 60), ("C", 120))]
    res = unicity(reads, {1: "ZZ D1", 2: "ZZ D2"}, p=2)
    assert res.eligible == 2 and res.unique_share == 0.0


def test_disjoint_traces_are_unique_with_one_point():
    reads = [r(1, "A", 0), r(1, "B", 60), r(2, "C", 0), r(2, "D", 60)]
    assert unicity(reads, {1: "ZZ D1", 2: "ZZ D2"}, p=1).unique_share == 1.0


def test_more_points_increase_unicity():
    # Both pass camera A at 08:00; only their second points differ.
    reads = [r(1, "A", 0), r(1, "B", 60), r(2, "A", 0), r(2, "C", 60)]
    truth = {1: "ZZ D1", 2: "ZZ D2"}
    one = unicity(reads, truth, p=1, samples=200)
    two = unicity(reads, truth, p=2, samples=5)
    assert 0.3 < one.unique_share < 0.7  # unique only when the B/C point is drawn
    assert two.unique_share == 1.0


def test_coarser_time_bins_reduce_unicity():
    # Same camera, 20 minutes apart: distinct at 15-min bins, identical at 60-min bins.
    reads = [r(1, "A", 0), r(2, "A", 20)]
    truth = {1: "ZZ D1", 2: "ZZ D2"}
    assert unicity(reads, truth, p=1, resolution_min=15).unique_share == 1.0
    assert unicity(reads, truth, p=1, resolution_min=60).unique_share == 0.0


def test_drivers_with_too_few_points_are_not_eligible():
    reads = [r(1, "A", 0), r(1, "B", 60), r(2, "A", 0)]
    res = unicity(reads, {1: "ZZ D1", 2: "ZZ D2", 3: "ZZ D3"}, p=2)
    assert res.eligible == 1 and res.drivers == 3 and res.eligible_share == pytest.approx(1 / 3)


def test_misread_fragments_are_separate_identities():
    reads = [r(1, "A", 0), r(1, "B", 60, ident="ZZ D1X"), r(1, "C", 120)]
    traces = to_points(reads, 60)
    assert set(traces) == {"ZZ D1", "ZZ D1X"}
    assert len(traces["ZZ D1"]) == 2
