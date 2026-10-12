import pytest

from platetrail.etl.directions import conflicting_direction_tags, direction_from_tags, parse_direction


@pytest.mark.parametrize(
    "value, expected",
    [
        ("90", [90.0]),
        ("0", [0.0]),
        ("360", [0.0]),
        ("-90", [270.0]),
        ("12.5", [12.5]),
        (" 45 ", [45.0]),
        ("N", [0.0]),
        ("ne", [45.0]),
        ("NNW", [337.5]),
        ("176;270", [176.0, 270.0]),
        ("90;90", [90.0]),  # duplicates collapsed
        ("45-135", [90.0]),  # range midpoint
        ("315-45", [0.0]),  # range across north
        ("350-10", [0.0]),
    ],
)
def test_parse_direction_valid(value, expected):
    assert parse_direction(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "", "   ", "forward", "backward", "north-ish", "90;abc", "NNNE"])
def test_parse_direction_rejects(value):
    assert parse_direction(value) is None


def test_direction_takes_priority_over_camera_direction():
    bearings, raw, key = direction_from_tags({"camera:direction": "137", "direction": "321"})
    assert bearings == [321.0]
    assert raw == "321"
    assert key == "direction"


def test_camera_direction_used_when_direction_absent():
    assert direction_from_tags({"camera:direction": "137"}) == ([137.0], "137", "camera:direction")


def test_no_direction_tags():
    assert direction_from_tags({"man_made": "surveillance"}) == (None, None, None)


def test_conflict_detected_for_opposite_tags():
    tags = {"camera:direction": "137", "direction": "321"}
    assert conflicting_direction_tags(tags) == tags


def test_no_conflict_when_tags_agree_or_single():
    assert conflicting_direction_tags({"camera:direction": "90", "direction": "100"}) is None
    assert conflicting_direction_tags({"direction": "90"}) is None
    assert conflicting_direction_tags({"camera:direction": "90", "direction": "forward"}) is None
