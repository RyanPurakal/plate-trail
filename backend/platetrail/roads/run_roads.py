"""Road network step: build/load the drive graph, store edges, snap cameras.

    python -m platetrail.roads.run_roads             # uses cached graph
    python -m platetrail.roads.run_roads --refresh   # re-download the graph

Run after the camera ETL (reloading cameras clears their snaps).
"""

import argparse
import statistics
from itertools import combinations

import osmnx as ox
from sqlalchemy import Engine, text

from platetrail.db import apply_migrations, get_engine
from platetrail.geo import WGS84, angle_diff
from platetrail.roads.graph import load_or_build_graph, store_edges
from platetrail.roads.snap import (
    MAX_SNAP_M,
    AlignmentFlag,
    CameraInput,
    EdgeIndex,
    SnapResult,
    alignment_flags,
    snap_camera,
)

CLOSE_PAIR_M = 30.0


def load_cameras(engine: Engine) -> list[CameraInput]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, source_id, ST_X(geom) AS lon, ST_Y(geom) AS lat, directions_deg FROM cameras ORDER BY id")
        ).all()
    return [CameraInput(r.id, r.source_id, r.lon, r.lat, list(r.directions_deg) if r.directions_deg else None) for r in rows]


def store_snaps(engine: Engine, results: list[SnapResult]) -> None:
    rows = [
        {
            "cid": s.camera_id,
            "u": s.edge[0],
            "v": s.edge[1],
            "k": s.edge[2],
            "d": s.distance_m,
            "b": s.bearing_deg,
            "f": s.fraction_along,
            "lon": s.snap_lon,
            "lat": s.snap_lat,
        }
        for r in results
        for s in r.snaps
    ]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM camera_edges"))
        if rows:
            conn.execute(
                text(
                    "INSERT INTO camera_edges (camera_id, u, v, key, snap_distance_m, edge_bearing_deg,"
                    " fraction_along, snap_geom) VALUES (:cid, :u, :v, :k, :d, :b, :f,"
                    " ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
                ),
                rows,
            )


def _fmt_dirs(dirs: list[float] | None) -> str:
    return "/".join(f"{d:g}" for d in dirs) if dirs else "none"


def classify_pair(a: SnapResult, b: SnapResult) -> str:
    if a.dropped or b.dropped:
        return "one or both dropped"
    road_a = {frozenset(s.edge[:2]) for s in a.snaps}
    road_b = {frozenset(s.edge[:2]) for s in b.snaps}
    name_a, name_b = a.snaps[0].name or "unnamed", b.snaps[0].name or "unnamed"
    if road_a & road_b:
        da, db = a.camera.directions_deg, b.camera.directions_deg
        if da and db:
            diff = min(angle_diff(x, y) for x in da for y in db)
            if diff >= 135:
                return f"SAME edge ({name_a}), cameras face opposite directions ({diff:.0f} deg apart)"
            if diff <= 45:
                return f"SAME edge ({name_a}), cameras face the same direction ({diff:.0f} deg apart)"
            return f"SAME edge ({name_a}), cameras {diff:.0f} deg apart"
        return f"SAME edge ({name_a})"
    nodes_a = {n for s in a.snaps for n in s.edge[:2]}
    nodes_b = {n for s in b.snaps for n in s.edge[:2]}
    adjacency = "adjacent, share a node" if nodes_a & nodes_b else "not adjacent"
    return f"DIFFERENT edges ({name_a} | {name_b}; {adjacency})"


def summarize(G, n_edges_stored: int, results: list[SnapResult], flags: list[AlignmentFlag]) -> str:
    lines = ["Road network summary", "===================="]
    lines.append(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} directed edges (stored {n_edges_stored:,})")
    snapped = [r for r in results if not r.dropped]
    dropped = [r for r in results if r.dropped]
    lines.append(f"Cameras: {len(results)} total, {len(snapped)} snapped, {len(dropped)} dropped (> {MAX_SNAP_M:g} m)")
    for r in dropped:
        near = f"{r.nearest_m:.1f} m" if r.nearest_m is not None else "n/a"
        lines.append(f"  DROPPED {r.camera.label} (nearest road {near})")

    dists = sorted(r.nearest_m for r in snapped)
    if dists:
        q = statistics.quantiles(dists, n=10, method="inclusive") if len(dists) > 1 else [dists[0]] * 9
        lines.append(
            f"Snap distance (m): min {dists[0]:.1f}, p10 {q[0]:.1f}, p25 {statistics.quantiles(dists, n=4, method='inclusive')[0]:.1f}, "
            f"median {statistics.median(dists):.1f}, p75 {statistics.quantiles(dists, n=4, method='inclusive')[2]:.1f}, "
            f"p90 {q[8]:.1f}, max {dists[-1]:.1f}"
        )
        buckets = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 50)]
        lines.append(
            "  histogram: "
            + ", ".join(f"{lo}-{hi} m: {sum(1 for d in dists if lo <= d < hi)}" for lo, hi in buckets)
        )
    two_way = sum(1 for r in snapped if len(r.snaps) == 2)
    lines.append(f"Snaps: {two_way} cameras on two-way edges (2 directed snaps), {len(snapped) - two_way} on one-way edges")
    ties = [r.camera.label for r in results if r.tie_broken]
    lines.append(f"Intersection ties broken by direction: {len(ties)} {ties or ''}")

    lines.append("")
    lines.append(f"Close pairs (<= {CLOSE_PAIR_M:g} m apart):")
    pairs = []
    for a, b in combinations(results, 2):
        _, _, dist = WGS84.inv(a.camera.lon, a.camera.lat, b.camera.lon, b.camera.lat)
        if dist <= CLOSE_PAIR_M:
            pairs.append((dist, a, b))
    for dist, a, b in sorted(pairs, key=lambda t: t[0]):
        lines.append(
            f"  {a.camera.label} [{_fmt_dirs(a.camera.directions_deg)}] + {b.camera.label} "
            f"[{_fmt_dirs(b.camera.directions_deg)}], {dist:.1f} m: {classify_pair(a, b)}"
        )

    lines.append("")
    lines.append(f"Direction closer to perpendicular than parallel to snapped road: {len(flags)}")
    for f in flags:
        multi = " (multi-direction camera)" if len(f.camera.directions_deg or []) > 1 else ""
        alt = (
            f"; parallel alternative: {f.alternative.name or 'unnamed'} at {f.alternative.distance_m:.1f} m"
            if f.alternative
            else "; no parallel road within 50 m"
        )
        snapped_name = next(r for r in results if r.camera is f.camera).snaps[0].name or "unnamed"
        lines.append(
            f"  {f.camera.label}{multi}: faces {f.direction_deg:g}, road {snapped_name} runs "
            f"{f.road_bearing_deg:.0f}/{(f.road_bearing_deg + 180) % 360:.0f} ({f.axis_diff_deg:.0f} deg off axis){alt}"
        )
    return "\n".join(lines)


def run(refresh: bool = False, engine: Engine | None = None) -> str:
    engine = engine or get_engine()
    apply_migrations(engine)
    G = load_or_build_graph(refresh=refresh)
    n_stored = store_edges(engine, G)
    index = EdgeIndex(ox.project_graph(G))
    results = [snap_camera(index, cam) for cam in load_cameras(engine)]
    store_snaps(engine, results)
    flags = [f for r in results for f in alignment_flags(index, r)]
    return summarize(G, n_stored, results, flags)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="re-download the road graph")
    args = parser.parse_args()
    print(run(refresh=args.refresh))


if __name__ == "__main__":
    main()
