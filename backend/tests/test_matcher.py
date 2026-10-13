import pytest

from platetrail.sim.matcher import (
    AmbiguousDirection,
    Facing,
    LotEvent,
    MatchConfig,
    Reason,
    UndirectedMode,
    captured_travel_bearing,
    choose_directions,
    choose_facings,
    edge_decision,
    lot_decision,
)

REAR = MatchConfig(facing=Facing.REAR_PLATE)
ONCOMING = MatchConfig(facing=Facing.ONCOMING)


def captured(dirs, travel, cfg=REAR):
    return edge_decision(dirs, travel, cfg).captured


# ---- facing convention -------------------------------------------------------

def test_captured_travel_bearing():
    assert captured_travel_bearing(90, Facing.REAR_PLATE) == 90
    assert captured_travel_bearing(90, Facing.ONCOMING) == 270
    assert captured_travel_bearing(270, Facing.ONCOMING) == 90
    assert captured_travel_bearing(360, Facing.REAR_PLATE) == 0
    assert captured_travel_bearing(-90, Facing.REAR_PLATE) == 270


def test_rear_plate_captures_travel_in_camera_direction_only():
    assert captured([90], 90, REAR)
    assert not captured([90], 270, REAR)


def test_oncoming_captures_travel_opposite_camera_direction_only():
    assert captured([90], 270, ONCOMING)
    assert not captured([90], 90, ONCOMING)


@pytest.mark.parametrize("facing", list(Facing))
def test_opposite_facing_pair_exactly_one_fires_per_travel_direction(facing):
    cfg = MatchConfig(facing=facing)
    east_cam, west_cam = [90], [270]
    for travel in (90, 270):
        fired = [captured(east_cam, travel, cfg), captured(west_cam, travel, cfg)]
        assert fired.count(True) == 1


def test_conventions_swap_which_camera_of_a_pair_fires():
    # Eastbound travel: rear-plate fires the east-facing camera, oncoming the west-facing one.
    assert captured([90], 90, REAR) and not captured([270], 90, REAR)
    assert captured([270], 90, ONCOMING) and not captured([90], 90, ONCOMING)


# ---- bearing tolerance edge cases ------------------------------------------------

@pytest.mark.parametrize("facing", list(Facing))
def test_tolerance_boundary_is_inclusive(facing):
    cfg = MatchConfig(tolerance_deg=45, facing=facing)
    target = captured_travel_bearing(100, facing)
    assert captured([100], (target + 45) % 360, cfg)
    assert captured([100], (target - 45) % 360, cfg)
    assert not captured([100], (target + 45.001) % 360, cfg)
    assert not captured([100], (target - 45.001) % 360, cfg)


@pytest.mark.parametrize(
    "cam, travel, expected",
    [
        (359, 1, True),  # wraps across north
        (1, 359, True),
        (350, 20, True),  # 30 deg across north
        (10, 300, False),  # 70 deg across north
        (0, 360, True),  # 360 == 0
        (0, 315, True),  # exactly 45 the other way
        (0, 314.9, False),
        (180, 135, True),
        (180, 225, True),
        (180, 225.1, False),
    ],
)
def test_wraparound(cam, travel, expected):
    assert captured([cam], travel, MatchConfig(tolerance_deg=45)) is expected


def test_wraparound_with_oncoming():
    # Camera faces 179 -> captures travel ~359; travel 1 is 2 deg away.
    assert captured([179], 1, MatchConfig(tolerance_deg=5, facing=Facing.ONCOMING))


def test_zero_tolerance_requires_exact_alignment():
    cfg = MatchConfig(tolerance_deg=0)
    assert captured([90], 90, cfg)
    assert not captured([90], 90.01, cfg)


def test_180_tolerance_captures_everything():
    cfg = MatchConfig(tolerance_deg=180)
    assert all(captured([90], t, cfg) for t in range(0, 360, 15))


def test_perpendicular_travel_not_captured_at_default_tolerance():
    assert not captured([0], 90, MatchConfig())
    assert not captured([0], 270, MatchConfig())


@pytest.mark.parametrize("bad", [-1, 180.5, 360])
def test_tolerance_validated(bad):
    with pytest.raises(ValueError):
        MatchConfig(tolerance_deg=bad)


def test_config_accepts_strings():
    cfg = MatchConfig(facing="oncoming", undirected="worst", ambiguous_direction="alternate")
    assert cfg.facing is Facing.ONCOMING
    assert cfg.undirected is UndirectedMode.WORST
    assert cfg.ambiguous_direction is AmbiguousDirection.ALTERNATE
    assert MatchConfig().lot_entrance.value == "access_road"
    assert MatchConfig(lot_entrance="all").lot_entrance.value == "all"
    with pytest.raises(ValueError):
        MatchConfig(facing="sideways")


# ---- multi-direction cameras -------------------------------------------------------

def test_multi_direction_camera_captures_either():
    assert captured([176, 270], 176)
    assert captured([176, 270], 270)
    assert not captured([176, 270], 45)


def test_reason_codes():
    assert edge_decision([90], 90, REAR).reason is Reason.CAPTURED
    assert edge_decision([90], 270, REAR).reason is Reason.WRONG_DIRECTION


# ---- undirected cameras ------------------------------------------------------------

@pytest.mark.parametrize("dirs", [None, []])
@pytest.mark.parametrize("facing", list(Facing))
def test_undirected_best_captures_both_directions(dirs, facing):
    cfg = MatchConfig(undirected=UndirectedMode.BEST, facing=facing)
    for travel in (0, 90, 180, 270):
        d = edge_decision(dirs, travel, cfg)
        assert d.captured and d.reason is Reason.UNDIRECTED_BEST


@pytest.mark.parametrize("dirs", [None, []])
@pytest.mark.parametrize("facing", list(Facing))
def test_undirected_worst_captures_neither(dirs, facing):
    cfg = MatchConfig(undirected=UndirectedMode.WORST, facing=facing)
    for travel in (0, 90, 180, 270):
        d = edge_decision(dirs, travel, cfg)
        assert not d.captured and d.reason is Reason.UNDIRECTED_WORST


def test_undirected_mode_does_not_affect_directed_cameras():
    for mode in UndirectedMode:
        cfg = MatchConfig(undirected=mode)
        assert captured([90], 90, cfg) and not captured([90], 270, cfg)


# ---- ambiguous directions --------------------------------------------------------

def test_choose_directions():
    primary, alt = [321.0], [137.0]
    assert choose_directions(primary, alt, MatchConfig()) == primary
    assert choose_directions(primary, alt, MatchConfig(ambiguous_direction="alternate")) == alt
    assert choose_directions(primary, None, MatchConfig(ambiguous_direction="alternate")) == primary


def test_ambiguous_camera_flips_which_direction_is_captured():
    primary, alt = [321.0], [137.0]
    p_cfg, a_cfg = MatchConfig(), MatchConfig(ambiguous_direction="alternate")
    assert captured(choose_directions(primary, alt, p_cfg), 321, p_cfg)
    assert not captured(choose_directions(primary, alt, a_cfg), 321, a_cfg)
    assert captured(choose_directions(primary, alt, a_cfg), 137, a_cfg)


# ---- lot cameras ------------------------------------------------------------------

def lot(facings, event, **cfg):
    return lot_decision(facings, event, MatchConfig(**cfg)).captured


def test_into_lot_camera_rear_plate_captures_arrivals_only():
    assert lot(["into_lot"], LotEvent.ARRIVAL)
    assert not lot(["into_lot"], LotEvent.DEPARTURE)


def test_toward_road_camera_rear_plate_captures_departures_only():
    assert lot(["toward_road"], LotEvent.DEPARTURE)
    assert not lot(["toward_road"], LotEvent.ARRIVAL)


def test_oncoming_flips_lot_events():
    assert lot(["into_lot"], LotEvent.DEPARTURE, facing="oncoming")
    assert not lot(["into_lot"], LotEvent.ARRIVAL, facing="oncoming")
    assert lot(["toward_road"], LotEvent.ARRIVAL, facing="oncoming")


def test_mixed_facing_lot_camera_captures_both():
    for event in LotEvent:
        for facing in Facing:
            assert lot(["into_lot", "toward_road"], event, facing=facing)


def test_undirected_lot_camera_follows_mode():
    for event in LotEvent:
        assert lot(None, event, undirected="best")
        assert not lot(None, event, undirected="worst")


def test_ambiguous_lot_camera_both_readings():
    primary, alt = ["into_lot"], ["toward_road"]
    p_cfg, a_cfg = MatchConfig(), MatchConfig(ambiguous_direction="alternate")
    assert lot_decision(choose_facings(primary, alt, p_cfg), LotEvent.ARRIVAL, p_cfg).captured
    assert not lot_decision(choose_facings(primary, alt, a_cfg), LotEvent.ARRIVAL, a_cfg).captured
    assert lot_decision(choose_facings(primary, alt, a_cfg), LotEvent.DEPARTURE, a_cfg).captured
