"""Parity: the C++ router (platetrail._fastroute) must return exactly what the networkx reference returns.

Not "an equally short path": the identical edge sequence, fractions, timings and polyline, including how ties
between equal-cost paths are broken. Graphs here use small integer travel times so ties are everywhere.
In CI the extension must be built; locally the C++ tests are skipped if it isn't.
"""

import os
import random
from datetime import datetime

import networkx as nx
import pytest

from platetrail.sim import routing
from platetrail.sim.routing import NoRoute, Router
from test_trip import toy_graph, xy

DEPART = datetime(2026, 10, 12, 8, 0)

if os.environ.get("CI"):
    assert routing._fastroute is not None, "CI must build the C++ router (pip install -e .)"
needs_cpp = pytest.mark.skipif(routing._fastroute is None, reason="platetrail._fastroute not built")


def grid_graph(n: int, seed: int) -> nx.MultiDiGraph:
    """n x n street grid, 200 m blocks, integer travel times (lots of equal-cost paths), some one-way streets,
    parallel edges and service roads."""
    rng = random.Random(seed)
    G = nx.MultiDiGraph(crs="EPSG:4326")
    for i in range(n):
        for j in range(n):
            lon, lat = xy(200 * i, 200 * j)
            G.add_node(i * n + j, x=lon, y=lat)
    for i in range(n):
        for j in range(n):
            for di, dj in ((1, 0), (0, 1)):
                if i + di >= n or j + dj >= n:
                    continue
                u, v = i * n + j, (i + di) * n + (j + dj)
                tt = float(rng.choice([10, 10, 20]))
                hw = "service" if rng.random() < 0.1 else "residential"
                directions = [(u, v), (v, u)] if rng.random() > 0.15 else [rng.choice([(u, v), (v, u)])]
                for a, b in directions:
                    G.add_edge(a, b, key=0, length=200.0, travel_time=tt, highway=hw, name=f"St {a}-{b}")
                    if rng.random() < 0.08:  # parallel edge, sometimes the same cost
                        G.add_edge(a, b, key=1, length=200.0, travel_time=tt + rng.choice([0.0, 5.0]),
                                   highway="residential", name=f"Alt {a}-{b}")
    return G


def same_route(a, b):
    assert [(e.edge, e.frac_from, e.frac_to) for e in a.edges] == [(e.edge, e.frac_from, e.frac_to) for e in b.edges]
    assert [(e.length_m, e.travel_time_s, e.enter_offset_s, e.name, e.service) for e in a.edges] == \
           [(e.length_m, e.travel_time_s, e.enter_offset_s, e.name, e.service) for e in b.edges]
    assert a.coords == b.coords
    assert a.duration_s == b.duration_s  # exact, not approx


def test_backend_flag(monkeypatch):
    monkeypatch.setenv("PLATETRAIL_ROUTER", "python")
    assert Router(toy_graph()).backend == "python"
    monkeypatch.setenv("PLATETRAIL_ROUTER", "fortran")
    with pytest.raises(ValueError):
        routing.default_backend()


@needs_cpp
def test_toy_graph_parity():
    py, cpp = Router(toy_graph(), backend="python"), Router(toy_graph(), backend="cpp")
    assert cpp.backend == "cpp"
    pts = [xy(e, n) for e in (0, 150, 500, 990, 1000, 1500, 2000) for n in (0, 20, 300)] + [xy(1000, 800), xy(700, 600)]
    for o in pts:
        for d in pts:
            same_route(py.route(o, d, DEPART, use_cache=False), cpp.route(o, d, DEPART, use_cache=False))


@needs_cpp
@pytest.mark.parametrize("seed", range(4))
def test_grid_parity_with_ties(seed):
    G = grid_graph(9, seed)
    py, cpp = Router(G, backend="python"), Router(G.copy(), backend="cpp")
    rng = random.Random(100 + seed)
    for _ in range(150):
        o = xy(rng.uniform(0, 1600), rng.uniform(0, 1600))
        d = xy(rng.uniform(0, 1600), rng.uniform(0, 1600))
        try:
            ref = py.route(o, d, DEPART, use_cache=False)
        except NoRoute:
            with pytest.raises(NoRoute):
                cpp.route(o, d, DEPART, use_cache=False)
            continue
        same_route(ref, cpp.route(o, d, DEPART, use_cache=False))


@needs_cpp
@pytest.mark.parametrize("seed", range(30))
def test_search_matches_networkx_on_random_multigraphs(seed):
    """The bare C++ search against networkx with the same virtual origin and destination: identical cost and
    path on tie-heavy random multigraphs (weights 0-3, parallel edges, unreachable targets)."""
    rng = random.Random(seed)
    n = rng.randint(2, 40)
    G = nx.MultiDiGraph()
    G.add_nodes_from(range(n))
    for _ in range(rng.randint(0, 4 * n)):
        G.add_edge(rng.randrange(n), rng.randrange(n), _cost=float(rng.randint(0, 3)))
    sources = [(rng.randrange(n), float(rng.randint(0, 3))) for _ in range(rng.randint(1, 3))]
    targets = [(rng.randrange(n), float(rng.randint(0, 3))) for _ in range(rng.randint(1, 3))]

    nodes = list(G.nodes)
    index = {v: i for i, v in enumerate(nodes)}
    indptr, indices, weights = [0], [], []
    for v in nodes:
        for u, keyed in G._adj[v].items():
            indices.append(index[u])
            weights.append(min(d["_cost"] for d in keyed.values()))
        indptr.append(len(indices))
    graph = routing._fastroute.Graph(indptr, indices, weights)

    H = G.copy()
    for v, c in sources:
        H.add_edge("O", v, _cost=c)
    for v, c in targets:
        H.add_edge(v, "D", _cost=c)

    def collapse(edges):
        out = {}
        for v, c in edges:
            out[v] = min(out[v], c) if v in out else c
        return list(out.items())

    got = graph.shortest_path(collapse(sources), collapse(targets))
    try:
        cost, path = nx.single_source_dijkstra(H, "O", "D", weight="_cost")
    except nx.NetworkXNoPath:
        assert got is None
        return
    assert got is not None
    assert got[0] == cost
    assert ["O", *(nodes[i] for i in got[1]), "D"] == path


@needs_cpp
def test_graph_rejects_bad_input():
    with pytest.raises(ValueError):
        routing._fastroute.Graph([0, 1], [5], [1.0])  # neighbour out of range
    with pytest.raises(ValueError):
        routing._fastroute.Graph([0, 1], [0], [-1.0])  # negative weight
