"""End-to-end smoke test on a tiny synthetic region, with no network or database.

The region file and sensor CSV live in fixtures/tiny_region: two box towns
(West, East) and six file sensors. The road graph and places are built here:
a 6 x 6 grid of streets 500 m apart with one secondary road (Main St) and
one primary road (Centre Ave). The test runs the same pieces the study uses:
region config -> file sensors -> direction-aware snapping -> routines ->
routing and matching -> noise -> inference, then a small population through
unicity and the policy comparison, and a density scenario in one town.
"""

from datetime import datetime, time, timedelta
from pathlib import Path

import networkx as nx
import pytest
from shapely.geometry import LineString, box

from platetrail.analysis.policies import compare
from platetrail.analysis.unicity import TraceRead, unicity
from platetrail.etl.loaders.file import FileCameraLoader
from platetrail.inference.engine import EngineRead, infer
from platetrail.population import PopulationRequest, simulate_population
from platetrail.region import get_region, load_region
from platetrail.routearea import build_camera_set
from platetrail.routines.places import Place, PlacePool
from platetrail.sim.routing import Router
from platetrail.sim.runner import LocalRunner, SimulationRequest
from test_trip import xy

REGION_FILE = Path(__file__).parent / "fixtures" / "tiny_region" / "region.json"
STEP_M, N = 500, 6  # grid spacing and nodes per side (2.5 km square)
MAIN_NORTH, CENTRE_EAST = 1000, 1500

# (category, east, north): every category the templates draw from, 20 m off the nearest corner.
PLACES = [
    ("work", 2020, 2020), ("work", 520, 2020), ("retail", 1020, 1020), ("grocery", 2020, 520),
    ("grocery", 520, 520), ("food", 1520, 1020), ("food", 20, 1520), ("services", 2020, 1520),
    ("leisure", 1020, 2020), ("worship", 520, 1520), ("university", 520, 20), ("hospital", 2020, 20),
    ("industrial", 2480, 1020),
]


def town_of(east_m: float) -> str:
    return "West" if xy(east_m, 0)[0] < -74.385 else "East"


def grid_graph() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph(crs="EPSG:4326")
    node = {}
    for i in range(N):
        for j in range(N):
            node[i, j] = len(node) + 1
            lon, lat = xy(i * STEP_M, j * STEP_M)
            G.add_node(node[i, j], x=lon, y=lat)

    def road(a, b, along_north):
        if along_north and a[1] * STEP_M == MAIN_NORTH:
            name, highway, kph = "Main St", "secondary", 50
        elif not along_north and a[0] * STEP_M == CENTRE_EAST:
            name, highway, kph = "Centre Ave", "primary", 60
        else:
            name, highway, kph = f"Street {a[0]}-{a[1]}", "residential", 30
        for u, v in ((node[a], node[b]), (node[b], node[a])):
            G.add_edge(u, v, key=0, length=STEP_M, travel_time=STEP_M / (kph / 3.6), name=name, highway=highway)

    for i in range(N):
        for j in range(N):
            if i + 1 < N:
                road((i, j), (i + 1, j), True)
            if j + 1 < N:
                road((i, j), (i, j + 1), False)
    return G


def place_pool(G: nx.MultiDiGraph) -> PlacePool:
    places = [Place(f"place/{k}", cat, *xy(e, n), town_of(e), f"{cat} {k}") for k, (cat, e, n) in enumerate(PLACES)]
    residential = []
    for u, v, k, d in G.edges(keys=True, data=True):
        if d["highway"] == "residential" and u < v:
            a, b = G.nodes[u], G.nodes[v]
            mid_lon = (a["x"] + b["x"]) / 2
            residential.append((f"{u}-{v}-{k}", LineString([(a["x"], a["y"]), (b["x"], b["y"])]), d["length"],
                                "West" if mid_lon < -74.385 else "East"))
    return PlacePool(places, residential)


@pytest.fixture(scope="module")
def world():
    """The tiny region as the active region, with a runner built from its file sensors."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PLATETRAIL_REGION", str(REGION_FILE))
        get_region.cache_clear()
        region = get_region()
        (source,) = region.camera_sources
        records = FileCameraLoader(source.path, region, source.source).load()
        router = Router(grid_graph())
        features = [{"properties": {"id": r.source_id, "directions_deg": r.directions_deg},
                     "geometry": {"coordinates": [r.lon, r.lat]}} for r in records]
        cameras, snapped = build_camera_set(router, features)
        towns = {label: box(*bb) for label, bb in region.bboxes.items()}
        runner = LocalRunner(router, cameras, place_pool(router.G), engine=None, towns=towns)
        yield {"region": region, "records": records, "snapped": snapped, "runner": runner}
    get_region.cache_clear()


def engine_reads(runner: LocalRunner, reads, cameras=None) -> list[EngineRead]:
    by_id = (cameras or runner.cameras).by_id
    return [EngineRead(r.time, by_id[r.camera_id].label, by_id[r.camera_id].lon, by_id[r.camera_id].lat)
            for r in reads]


def test_region_file_and_sensors_load_and_snap(world):
    region, records = world["region"], world["records"]
    assert region.labels == ("West", "East") and region.scenario_town == "East"
    assert load_region(REGION_FILE) == region
    assert [r.key for r in records] == [f"tiny-fixture:t-{i}" for i in range(1, 7)]
    assert [r.town for r in records] == ["West", "West", "East", "East", "East", "East"]
    assert records[5].directions_deg is None
    assert world["snapped"] == 6
    cams = {c.label: c for c in world["runner"].cameras.by_id.values()}
    G = world["runner"].router.G
    assert {G[u][v][k]["name"] for u, v, k in (e.edge for e in cams["t-1"].edges)} == {"Main St"}
    assert {G[u][v][k]["name"] for u, v, k in (e.edge for e in cams["t-4"].edges)} == {"Centre Ave"}


def test_one_driver_from_routine_to_inference(world):
    runner = world["runner"]
    request = SimulationRequest(template="commuter", weeks=3, seed=4)
    out = runner.simulate(request)
    assert out.sim.trips and not out.sim.skipped
    assert out.noise.reads, "the commuter should pass at least one sensor"
    assert all(out.period[0] <= r.time <= out.period[1] for r in out.noise.reads)
    again = runner.simulate(request)
    assert [(r.camera_id, r.time, r.plate) for r in again.noise.reads] == \
           [(r.camera_id, r.time, r.plate) for r in out.noise.reads]

    inf = infer(engine_reads(runner, out.noise.reads))
    assert inf.reads == len(out.noise.reads) and inf.conclusions
    assert inf.regular, "a three-week commute should show regular passes"
    home = out.sim.routine.anchors["home"]
    assert inf.home is not None and inf.home.error_m(home.lon, home.lat) < 1500  # about 0.8 km with this seed


def test_population_unicity_and_policy_comparison(world):
    request = PopulationRequest(drivers=12, weeks=2, seed=1, generator="template")
    drivers, cameras, scenario = simulate_population(world["runner"], request)
    assert scenario is None and len({d.plate for d in drivers}) == 12
    labels = {c.camera_id: c.label for c in cameras.by_id.values()}
    reads = [TraceRead(d.idx, f"{r.state} {r.plate}", labels[r.camera_id], r.time) for d in drivers for r in d.reads]
    truth = {d.idx: f"ZZ {d.plate}" for d in drivers}
    assert reads

    res = unicity(reads, truth, p=2)
    assert res.drivers == 12 and res.eligible > 0 and 0.0 <= res.unique_share <= 1.0

    start = datetime.combine(request.start, time())
    end = start + timedelta(weeks=request.weeks)
    coords = {c.label: (c.lon, c.lat) for c in cameras.by_id.values()}
    rows = {row["policy"]: row for row in compare(reads, truth, {d.idx: d.anchors for d in drivers}, coords,
                                                  start, end, seed=1)}
    assert {"baseline", "retention_7d", "retention_1d", "round_hour", "aggregate_only"} <= set(rows)
    assert rows["retention_1d"]["reads"] <= rows["retention_7d"]["reads"] <= rows["baseline"]["reads"] == len(reads)
    assert rows["aggregate_only"]["reads"] == 0


def test_density_scenario_places_sensors_in_the_region_town(world):
    runner = world["runner"]
    out = runner.simulate(SimulationRequest(template="commuter", weeks=1, seed=2, extra_cameras=2))
    assert out.scenario["town"] == "East" and len(out.scenario["cameras"]) == 2
    east = box(*world["region"].bboxes["East"])
    assert all(east.covers(box(c["lon"], c["lat"], c["lon"], c["lat"])) for c in out.scenario["cameras"])
    assert len(out.cameras.by_id) == 8
