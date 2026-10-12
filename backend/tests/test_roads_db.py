import networkx as nx
import osmnx as ox
import pytest
from sqlalchemy import text

from platetrail.etl.loaders.base import CameraRecord
from platetrail.etl.run_etl import run as run_etl
from platetrail.roads.graph import store_edges
from platetrail.roads.run_roads import load_cameras, store_snaps
from platetrail.roads.snap import EdgeIndex, snap_camera

pytestmark = pytest.mark.db


class StubLoader:
    source = "osm"

    def __init__(self, records):
        self.records = records

    def load(self, refresh=False):
        return self.records


def tiny_graph():
    """Two-way road along a parallel plus a one-way spur, in EPSG:4326 like OSMnx output."""
    G = nx.MultiDiGraph(crs="EPSG:4326")
    G.add_node(1, x=-74.400, y=40.500)
    G.add_node(2, x=-74.398, y=40.500)
    G.add_node(3, x=-74.398, y=40.502)
    common = dict(highway="residential", speed_kph=40.0)
    G.add_edge(1, 2, key=0, osmid=[10, 11], name="Main St", oneway=False, length=170.0, travel_time=15.3, **common)
    G.add_edge(2, 1, key=0, osmid=[10, 11], name="Main St", oneway=False, length=170.0, travel_time=15.3, **common)
    G.add_edge(2, 3, key=0, osmid=12, oneway=True, length=222.0, travel_time=20.0, **common)  # unnamed
    return G


def test_store_edges_and_snaps(engine):
    camera = CameraRecord("osm", "node/1", 40.50005, -74.399, "Edison", [90.0], "90", "direction")
    far = CameraRecord("osm", "node/2", 40.51, -74.399, "Edison", [90.0], "90", "direction")
    run_etl(loaders=[StubLoader([camera, far])], engine=engine)

    G = tiny_graph()
    assert store_edges(engine, G) == 3

    index = EdgeIndex(ox.project_graph(G))
    results = [snap_camera(index, c) for c in load_cameras(engine)]
    store_snaps(engine, results)

    with engine.connect() as conn:
        edges = conn.execute(text("SELECT u, v, osmid, name, oneway FROM road_edges ORDER BY u, v")).all()
        snaps = conn.execute(
            text(
                "SELECT c.source_id, ce.u, ce.v, ce.edge_bearing_deg, ce.snap_distance_m FROM camera_edges ce"
                " JOIN cameras c ON c.id = ce.camera_id ORDER BY ce.u"
            )
        ).all()

    assert [(e.u, e.v) for e in edges] == [(1, 2), (2, 1), (2, 3)]
    assert edges[0].osmid == "10;11" and edges[0].name == "Main St" and edges[0].oneway is False
    assert edges[2].name is None
    assert [(s.source_id, s.u, s.v) for s in snaps] == [("node/1", 1, 2), ("node/1", 2, 1)]
    assert abs(snaps[0].edge_bearing_deg - 90) < 1 and abs(snaps[1].edge_bearing_deg - 270) < 1
    assert snaps[0].snap_distance_m == pytest.approx(5.6, abs=0.3)


def test_reloading_cameras_clears_snaps(engine):
    run_etl(loaders=[StubLoader([CameraRecord("osm", "node/9", 40.5, -74.399, "Edison", None, None)])], engine=engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM camera_edges")).scalar_one() == 0
