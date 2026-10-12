from datetime import datetime, timedelta

import numpy as np
import pytest

from platetrail.sim.noise import NoiseConfig, Outage, TruePass, apply_noise, outage_windows, true_passes
from platetrail.sim.plates import LOOKALIKES, PLATE_PATTERN, SYNTHETIC_STATE, misread, synthetic_plate

START = datetime(2026, 10, 12)
END = START + timedelta(weeks=4)
PLATE = "D10BOS"  # every character but nothing exotic; D,1,0,B,O,S all have look-alikes


def passes(n=500, cameras=20, plate=PLATE):
    rng = np.random.default_rng(123)
    span = (END - START).total_seconds()
    times = sorted(START + timedelta(seconds=float(s)) for s in rng.random(n) * span)
    return [TruePass(i, int(rng.integers(cameras)), t, plate) for i, t in enumerate(times)]


def key(result):
    return (
        [(r.read_id, r.pass_id, r.camera_id, r.time, r.plate, r.jitter_s) for r in result.reads],
        [(d.pass_id, d.reason) for d in result.dropped],
        {c: [(o.start, o.end) for o in w] for c, w in result.outages.items()},
    )


# ---- determinism -------------------------------------------------------------

def test_same_seed_identical_output():
    cfg = NoiseConfig(seed=7, p_miss=0.2, p_char_misread=0.1, downtime_rate_per_week=2, jitter_sd_s=5)
    assert key(apply_noise(passes(), START, END, cfg)) == key(apply_noise(passes(), START, END, cfg))


def test_different_seed_different_output():
    a = apply_noise(passes(), START, END, NoiseConfig(seed=1, p_miss=0.2, p_char_misread=0.1))
    b = apply_noise(passes(), START, END, NoiseConfig(seed=2, p_miss=0.2, p_char_misread=0.1))
    assert key(a) != key(b)


def test_input_order_does_not_matter():
    cfg = NoiseConfig(seed=3, p_miss=0.2, p_char_misread=0.1, downtime_rate_per_week=2)
    ps = passes()
    assert key(apply_noise(ps, START, END, cfg)) == key(apply_noise(list(reversed(ps)), START, END, cfg))


def test_changing_p_miss_does_not_move_outages_or_jitter():
    base = NoiseConfig(seed=5, p_miss=0.0, downtime_rate_per_week=2, jitter_sd_s=5)
    more = NoiseConfig(seed=5, p_miss=0.5, downtime_rate_per_week=2, jitter_sd_s=5)
    a, b = apply_noise(passes(), START, END, base), apply_noise(passes(), START, END, more)
    assert key(a)[2] == key(b)[2]  # outages identical
    jitter_a = {r.pass_id: r.jitter_s for r in a.reads}
    assert all(jitter_a[r.pass_id] == r.jitter_s for r in b.reads)  # surviving reads keep their jitter
    assert {r.pass_id for r in b.reads} <= {r.pass_id for r in a.reads}


# ---- zero noise ----------------------------------------------------------------

def test_noiseless_reproduces_true_passes_exactly():
    ps = passes()
    result = apply_noise(ps, START, END, NoiseConfig.noiseless(seed=99))
    assert result.dropped == []
    assert [(r.pass_id, r.camera_id, r.time, r.plate) for r in result.reads] == [
        (p.pass_id, p.camera_id, p.time, p.plate) for p in ps
    ]
    assert all(r.jitter_s == 0 and not r.misread for r in result.reads)


def test_p_miss_zero_no_downtime_keeps_every_pass_even_with_misreads_and_jitter():
    ps = passes()
    result = apply_noise(ps, START, END, NoiseConfig(seed=4, p_miss=0, downtime_rate_per_week=0,
                                                     p_char_misread=0.2, jitter_sd_s=3))
    assert result.dropped == []
    assert sorted(r.pass_id for r in result.reads) == [p.pass_id for p in ps]


# ---- missed reads ------------------------------------------------------------------

def test_p_miss_one_drops_everything():
    result = apply_noise(passes(), START, END, NoiseConfig(p_miss=1.0, downtime_rate_per_week=0))
    assert result.reads == [] and all(d.reason == "missed" for d in result.dropped)


def test_p_miss_rate_roughly_right():
    result = apply_noise(passes(n=4000), START, END, NoiseConfig(seed=1, p_miss=0.1, downtime_rate_per_week=0))
    assert 0.08 < len(result.dropped_for("missed")) / 4000 < 0.12


# ---- misreads ----------------------------------------------------------------------

def test_misreads_only_use_lookalike_swaps():
    rng = np.random.default_rng(0)
    plates = [synthetic_plate(rng) for _ in range(2000)]
    for plate in plates:
        out = misread(plate, rng, p_char=0.5)
        assert len(out) == len(plate)
        for orig, new in zip(plate, out):
            assert new == orig or new in LOOKALIKES[orig]


def test_p_char_one_swaps_every_confusable_character_and_nothing_else():
    rng = np.random.default_rng(1)
    out = misread("D10BOS", rng, 1.0)
    assert all(a != b for a, b in zip("D10BOS", out))
    assert misread("AHKMXW", rng, 1.0) == "AHKMXW"  # no look-alikes defined


def test_misread_reads_have_different_plate_and_keep_link():
    ps = passes()
    result = apply_noise(ps, START, END, NoiseConfig(seed=2, p_miss=0, downtime_rate_per_week=0, p_char_misread=0.3))
    assert result.misreads, "expected some misreads at p_char=0.3"
    by_id = {p.pass_id: p for p in ps}
    for r in result.misreads:
        assert r.plate != r.true_plate == by_id[r.pass_id].plate
        assert r.camera_id == by_id[r.pass_id].camera_id


def test_synthetic_plate_shape():
    rng = np.random.default_rng(0)
    for _ in range(100):
        p = synthetic_plate(rng)
        assert len(p) == len(PLATE_PATTERN)
        assert all((c.isalpha() if k == "L" else c.isdigit()) for c, k in zip(p, PLATE_PATTERN))


# ---- downtime ----------------------------------------------------------------------

def test_reads_during_outage_dropped_not_delayed():
    cfg = NoiseConfig(seed=11, p_miss=0, p_char_misread=0, jitter_sd_s=0,
                      downtime_rate_per_week=3, downtime_mean_hours=24)
    ps = passes()
    result = apply_noise(ps, START, END, cfg)
    down = result.dropped_for("downtime")
    assert down, "expected some passes inside outages"
    for d in down:
        assert any(o.covers(d.time) for o in result.outages[d.camera_id])
    # every surviving read is at its true time, outside any outage
    for r in result.reads:
        assert r.time == r.true_time
        assert not any(o.covers(r.time) for o in result.outages[r.camera_id])
    assert len(result.reads) + len(down) == len(ps)


def test_outages_are_per_camera_and_deterministic():
    cfg = NoiseConfig(seed=8, downtime_rate_per_week=2)
    a = outage_windows([1, 2, 3], START, END, cfg)
    b = outage_windows([3], START, END, cfg)
    assert a[3] == b[3]  # camera 3's outages don't depend on which other cameras exist
    assert a[1] != a[2]
    assert all(o.camera_id == c for c, ws in a.items() for o in ws)


def test_expected_downtime_fraction():
    cfg = NoiseConfig(seed=0)  # defaults: 0.25/week x 12 h -> ~1.8%
    ws = outage_windows(list(range(2000)), START, END, cfg)
    total_h = sum((o.end - o.start).total_seconds() / 3600 for w in ws.values() for o in w)
    frac = total_h / (2000 * 4 * 168)
    assert 0.013 < frac < 0.023


def test_outage_boundaries():
    o = Outage(1, START, START + timedelta(hours=1))
    assert o.covers(START) and not o.covers(START + timedelta(hours=1))


# ---- jitter ----------------------------------------------------------------------------

def test_jitter_sd_roughly_right():
    result = apply_noise(passes(n=4000), START, END, NoiseConfig(seed=1, p_miss=0, downtime_rate_per_week=0, jitter_sd_s=2))
    js = np.array([r.jitter_s for r in result.reads])
    assert abs(js.mean()) < 0.15 and 1.85 < js.std() < 2.15


def test_read_log_sorted_by_recorded_time_with_sequential_ids():
    result = apply_noise(passes(), START, END, NoiseConfig(seed=1, jitter_sd_s=30))
    assert [r.time for r in result.reads] == sorted(r.time for r in result.reads)
    assert [r.read_id for r in result.reads] == list(range(len(result.reads)))


# ---- config ------------------------------------------------------------------------------

@pytest.mark.parametrize("kw", [{"p_miss": -0.1}, {"p_miss": 1.1}, {"p_char_misread": 2}, {"jitter_sd_s": -1},
                                {"downtime_rate_per_week": -1}])
def test_config_validation(kw):
    with pytest.raises(ValueError):
        NoiseConfig(**kw)


def test_true_passes_numbering():
    class P:
        def __init__(self, t, c):
            self.time, self.camera_id = t, c
    ps = true_passes([P(START + timedelta(hours=2), 5), P(START, 9)], "A12BCD", first_id=10)
    assert [(p.pass_id, p.camera_id, p.plate) for p in ps] == [(10, 9, "A12BCD"), (11, 5, "A12BCD")]
    assert all(p.state == SYNTHETIC_STATE == "ZZ" for p in ps)


def test_reads_carry_synthetic_state_and_state_errors_count_as_misreads():
    result = apply_noise(passes(n=50), START, END, NoiseConfig.noiseless())
    assert all(r.state == r.true_state == "ZZ" and not r.misread for r in result.reads)
    from dataclasses import replace
    wrong_state = replace(result.reads[0], state="NJ")
    assert wrong_state.misread and wrong_state.plate == wrong_state.true_plate


def test_noiseless_pipeline_equals_matcher_output_end_to_end():
    from test_trip import DEPART, lot_camera, pair_on_main_st, toy_graph, xy

    from platetrail.sim.routing import Router
    from platetrail.sim.trip import CameraSet, simulate_trip

    router = Router(toy_graph())
    cams = CameraSet(list(pair_on_main_st().by_id.values()) + [lot_camera(["into_lot"])])
    trips = [((0, 0), (1000, 0)), ((1000, 0), (0, 0)), ((0, 0), (1000, 0))]
    captured = []
    for i, (o, d) in enumerate(trips):
        captured += simulate_trip(router, cams, xy(*o), xy(*d), DEPART + timedelta(hours=3 * i)).captured
    assert len(captured) == 5  # 1 road capture per trip + 2 lot arrivals

    tp = true_passes(captured, "A12BCD")
    result = apply_noise(tp, DEPART, DEPART + timedelta(days=1), NoiseConfig(seed=0, p_miss=0, p_char_misread=0,
                         downtime_rate_per_week=0, jitter_sd_s=0))
    expected = sorted((p.time, p.camera_id) for p in captured)
    assert [(r.time, r.camera_id) for r in result.reads] == expected
    assert all(r.plate == "A12BCD" for r in result.reads)


# ---- extra read error hook -------------------------------------------------------------

class DropLastChar:
    """Test-only error: drops the final character with probability p."""

    def __init__(self, p, stream=100):
        self.p, self.stream = p, stream

    def apply(self, plate, rng):
        return plate[:-1] if rng.random() < self.p else plate


def test_extra_error_with_no_effect_leaves_output_identical():
    base = NoiseConfig(seed=9, p_miss=0.2, p_char_misread=0.1, downtime_rate_per_week=2, jitter_sd_s=5)
    hooked = NoiseConfig(seed=9, p_miss=0.2, p_char_misread=0.1, downtime_rate_per_week=2, jitter_sd_s=5,
                         extra_read_errors=(DropLastChar(0.0),))
    assert key(apply_noise(passes(), START, END, base)) == key(apply_noise(passes(), START, END, hooked))


def test_extra_error_changes_only_plates_not_existing_draws():
    base = NoiseConfig(seed=9, p_miss=0.2, p_char_misread=0.1, downtime_rate_per_week=2, jitter_sd_s=5)
    hooked = NoiseConfig(seed=9, p_miss=0.2, p_char_misread=0.1, downtime_rate_per_week=2, jitter_sd_s=5,
                         extra_read_errors=(DropLastChar(1.0),))
    a, b = apply_noise(passes(), START, END, base), apply_noise(passes(), START, END, hooked)
    assert [(r.pass_id, r.time, r.jitter_s) for r in a.reads] == [(r.pass_id, r.time, r.jitter_s) for r in b.reads]
    assert key(a)[1:] == key(b)[1:]  # same drops, same outages
    assert all(rb.plate == ra.plate[:-1] for ra, rb in zip(a.reads, b.reads))
    assert all(r.misread for r in b.reads)  # a dropped character counts as a misread


@pytest.mark.parametrize("streams", [(1,), (2,), (100, 100)])
def test_extra_error_streams_validated(streams):
    with pytest.raises(ValueError):
        NoiseConfig(extra_read_errors=tuple(DropLastChar(0.5, s) for s in streams))
