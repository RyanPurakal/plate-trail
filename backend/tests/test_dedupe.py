from platetrail.etl.dedupe import dedupe, directions_compatible
from platetrail.geo import angle_diff
from platetrail.etl.loaders.base import CameraRecord

# ~1 m of latitude in degrees.
M = 1 / 111_195


def rec(source, sid, lat=40.5, lon=-74.4, dirs=None):
    return CameraRecord(source=source, source_id=sid, lat=lat, lon=lon, town="T", directions_deg=dirs, direction_raw=None)


def test_angle_diff_wraps():
    assert angle_diff(359, 1) == 2
    assert angle_diff(0, 180) == 180
    assert angle_diff(90, 90) == 0


def test_directions_compatible():
    assert directions_compatible(None, [90], 30)
    assert directions_compatible([350], [10], 30)
    assert not directions_compatible([90], [270], 30)


def test_duplicate_source_id_dropped():
    cams, stats = dedupe([rec("osm", "n/1"), rec("osm", "n/1")])
    assert len(cams) == 1
    assert stats.duplicate_ids_dropped == ["osm:n/1"]


def test_same_pole_opposite_directions_kept_separate():
    # Two real cameras on one pole covering both directions of a road.
    cams, stats = dedupe([rec("osm", "n/1", dirs=[85]), rec("osm", "n/2", lat=40.5 + 0.5 * M, dirs=[265])])
    assert len(cams) == 2
    assert not stats.merged_within_source


def test_same_source_same_point_same_direction_merged():
    cams, stats = dedupe([rec("osm", "n/1", dirs=[90]), rec("osm", "n/2", lat=40.5 + 0.3 * M, dirs=[90])])
    assert len(cams) == 1
    assert stats.merged_within_source == [("osm:n/1", "osm:n/2")]


def test_same_source_nearby_not_merged():
    cams, _ = dedupe([rec("osm", "n/1", dirs=[90]), rec("osm", "n/2", lat=40.5 + 5 * M, dirs=[90])])
    assert len(cams) == 2


def test_cross_source_merge_prefers_priority_source_position_and_fills_direction():
    osm = rec("osm", "n/1", dirs=None)
    deflock = rec("deflock", "d/9", lat=40.5 + 10 * M, dirs=[180])
    cams, stats = dedupe([deflock, osm], source_priority=("osm", "deflock"))
    assert len(cams) == 1
    cam = cams[0]
    assert cam.primary.key == "osm:n/1"
    assert cam.directions_deg == [180]
    assert cam.sources == ["deflock", "osm"]
    assert stats.merged_cross_source == [("osm:n/1", "deflock:d/9")]


def test_cross_source_not_merged_when_far_or_directions_conflict():
    far = dedupe([rec("osm", "n/1"), rec("deflock", "d/1", lat=40.5 + 40 * M)], source_priority=("osm", "deflock"))
    opposite = dedupe(
        [rec("osm", "n/1", dirs=[0]), rec("deflock", "d/1", lat=40.5 + 3 * M, dirs=[180])],
        source_priority=("osm", "deflock"),
    )
    assert len(far[0]) == 2
    assert len(opposite[0]) == 2


def test_dedupe_is_order_independent():
    recs = [rec("osm", "n/1", dirs=[90]), rec("deflock", "d/1", lat=40.5 + 2 * M, dirs=[95]), rec("osm", "n/3", lat=41)]
    a, _ = dedupe(recs, source_priority=("osm", "deflock"))
    b, _ = dedupe(list(reversed(recs)), source_priority=("osm", "deflock"))
    assert [c.primary.key for c in a] == [c.primary.key for c in b]
