import pytest
from sqlalchemy import text

from platetrail.etl.loaders.base import CameraLoader, CameraRecord
from platetrail.etl.run_etl import run

pytestmark = pytest.mark.db


class StubLoader(CameraLoader):
    def __init__(self, source, records):
        self.source = source
        self.records = records

    def load(self, refresh=False):
        return self.records


def rec(source, sid, lat, dirs, town="Edison"):
    return CameraRecord(source=source, source_id=sid, lat=lat, lon=-74.4, town=town, directions_deg=dirs, direction_raw=None)


def test_run_stores_cameras_and_source_records(engine):
    osm = StubLoader("osm", [rec("osm", "node/1", 40.5, [90]), rec("osm", "node/2", 40.6, None, town="New Brunswick")])
    other = StubLoader("deflock", [rec("deflock", "d/1", 40.50005, None)])  # ~5 m from node/1 -> merged
    summary = run(loaders=[osm, other], engine=engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT source_id, town, has_direction, directions_deg, sources FROM cameras ORDER BY source_id")
        ).all()
        n_source_records = conn.execute(text("SELECT count(*) FROM camera_source_records")).scalar_one()

    assert [(r.source_id, r.town, r.has_direction) for r in rows] == [
        ("node/1", "Edison", True),
        ("node/2", "New Brunswick", False),
    ]
    assert rows[0].directions_deg == [90.0]
    assert rows[0].sources == ["deflock", "osm"]
    assert n_source_records == 3
    assert "merged across sources=1" in summary


def test_rerun_replaces_rather_than_duplicates(engine):
    loader = StubLoader("osm", [rec("osm", "node/1", 40.5, [90])])
    run(loaders=[loader], engine=engine)
    run(loaders=[loader], engine=engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM cameras")).scalar_one() == 1
