import pytest
from sqlalchemy import text

from platetrail.routines.places import PlacePool, attach_far_places_by_outline, store_places

pytestmark = pytest.mark.db


class FakeCache:
    """Returns a canned Overpass response for any query."""

    def __init__(self, response):
        self.response = response

    def get_or_fetch(self, key, fetch, refresh=False):
        return self.response


def test_large_building_attaches_at_outline(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE road_edges CASCADE"))
        conn.execute(text("TRUNCATE places RESTART IDENTITY"))  # earlier runs reference the test town
        conn.execute(text("DELETE FROM towns WHERE name = 'Testtown'"))
        conn.execute(text("INSERT INTO towns (name, osm_id, geom) VALUES ('Testtown', 'relation/1',"
                          " ST_Multi(ST_MakeEnvelope(-74.5, 40.4, -74.3, 40.6, 4326)))"))
        # A road along latitude 40.5000.
        conn.execute(text("INSERT INTO road_edges (u, v, key, length_m, geom) VALUES (1, 2, 0, 1700,"
                          " ST_GeomFromText('LINESTRING(-74.41 40.5, -74.39 40.5)', 4326))"))
    # A ~300 m warehouse whose southern wall is 5 m north of the road; its centre is ~150 m from it.
    s, n = 40.500045, 40.502745
    store_places(engine, [
        {"osm_id": "way/900", "category": "industrial", "subcategory": "warehouse", "name": "Big Warehouse",
         "lon": -74.40, "lat": (s + n) / 2},
        {"osm_id": "node/901", "category": "food", "subcategory": "cafe", "name": "Cafe", "lon": -74.40, "lat": 40.5003},
    ])
    ring = [(-74.402, s), (-74.398, s), (-74.398, n), (-74.402, n), (-74.402, s)]
    response = {"elements": [{"type": "way", "id": 900, "geometry": [{"lon": x, "lat": y} for x, y in ring]}]}
    changed = attach_far_places_by_outline(engine, FakeCache(response))

    assert [c["name"] for c in changed] == ["Big Warehouse"]
    assert changed[0]["before_m"] > 100 and changed[0]["after_m"] == pytest.approx(5, abs=1)
    with engine.connect() as conn:
        rows = {r.osm_id: r for r in conn.execute(text(
            "SELECT osm_id, attach_method, network_distance_m, ST_Y(attach_geom) lat FROM places"))}
    assert rows["way/900"].attach_method == "outline" and rows["way/900"].lat == pytest.approx(s, abs=1e-6)
    assert rows["node/901"].attach_method == "centre"
    pool = PlacePool.from_db(engine)
    warehouse = next(p for p in pool.places if p.osm_id == "way/900")
    assert warehouse.lat == pytest.approx(s, abs=1e-6)  # sampled at the outline point, so it's routable
