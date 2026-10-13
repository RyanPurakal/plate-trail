import re

from platetrail.roads.graph import CUSTOM_FILTER, SERVICE_SPEED_KPH


def _service_exclusions():
    m = re.search(r'\["service"!~"([^"]+)"\]', CUSTOM_FILTER)
    return set(m.group(1).split("|"))


def test_service_roads_included_except_parking_aisles_and_drive_throughs():
    highway_exclusions = re.search(r'\["highway"!~"([^"]+)"\]', CUSTOM_FILTER).group(1).split("|")
    assert "service" not in highway_exclusions  # service roads are in
    excl = _service_exclusions()
    assert {"parking_aisle", "drive-through", "drive_through"} <= excl
    assert {"driveway", "alley", "parking"}.isdisjoint(excl)  # these service kinds stay
    assert '["access"!~"private"]' in CUSTOM_FILTER


def test_service_speed_is_slow():
    assert 5 <= SERVICE_SPEED_KPH <= 25
