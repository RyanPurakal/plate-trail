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


def test_classification_stored_and_loaded_into_camera_set(engine):
    from shapely.geometry import LineString, box

    from platetrail.roads.lots import Classification, LotAssignment, OsmFeature
    from platetrail.roads.run_roads import store_classification
    from platetrail.sim.trip import load_camera_set

    road_cam = CameraRecord("osm", "node/1", 40.50005, -74.399, "Edison", [90.0], "90", "direction")
    lot_cam = CameraRecord("osm", "node/3", 40.5015, -74.3985, "Edison", [321.0], "321", "direction",
                           alt_directions_deg=[137.0])
    run_etl(loaders=[StubLoader([road_cam, lot_cam])], engine=engine)
    G = tiny_graph()
    store_edges(engine, G)
    index = EdgeIndex(ox.project_graph(G))
    cams = {c.label: c for c in load_cameras(engine)}
    results = [snap_camera(index, c) for c in cams.values()]
    store_snaps(engine, [r for r in results if r.camera.label == "node/1"])

    lot_geom = box(-74.3990, 40.5010, -74.3980, 40.5020)
    way = LineString([(-74.3985, 40.5012), (-74.3985, 40.5018)])
    cls = Classification(
        lots={cams["node/3"].camera_id: LotAssignment(
            camera=cams["node/3"],
            lot=OsmFeature("way/500", "retail", {"name": "Plaza"}, lot_geom, lot_geom),
            watched_way=OsmFeature("way/501", "service", {}, way, way),
            facings=["into_lot"], alt_facings=["toward_road"], reason="driveway",
        )},
        snap_ambiguous={cams["node/1"].camera_id: 50.0},
    )
    store_classification(engine, cls)

    cs = load_camera_set(engine)
    road = cs.by_id[cams["node/1"].camera_id]
    lot = cs.by_id[cams["node/3"].camera_id]
    assert road.kind == "public_road" and road.snap_ambiguous and len(road.edges) == 2
    assert lot.kind == "private_lot" and lot.edges == []
    assert lot.alt_directions_deg == [137.0] and lot.direction_ambiguous
    assert lot.facings == ["into_lot"] and lot.alt_facings == ["toward_road"]
    assert lot.lot_name == "Plaza" and lot.lot_geom.equals(lot_geom)
    assert cs.lots == [lot]
    assert set(cs.by_edge) == {(1, 2, 0), (2, 1, 0)}
