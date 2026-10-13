"""Plot routes past one camera as an SVG: nearby roads, each route, the camera and its snaps.

    python scripts/plot_camera_routes.py --camera node/14181989101 --out ../data/exports/albany.svg

Routes are the demo commute (scripts/demo_week.py) on one weekday.
"""

import argparse
import math
from datetime import datetime
from pathlib import Path

import osmnx as ox
from shapely.geometry import box
from sqlalchemy import text

from platetrail.db import get_engine
from platetrail.etl.export_geojson import destination
from platetrail.roads.graph import load_or_build_graph
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.routing import Router
from platetrail.sim.trip import load_camera_set, match_route

from demo_week import HOME, WORK

ROUTE_COLORS = {"morning (home -> work)": "#c0392b", "evening (work -> home)": "#2471a3"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--camera", default="node/14181989101")
    p.add_argument("--radius", type=float, default=180.0, help="half-width of the view in metres")
    p.add_argument("--out", type=Path, default=Path("../data/exports/camera_routes.svg"))
    args = p.parse_args()

    engine = get_engine()
    with engine.connect() as conn:
        cam = conn.execute(text("SELECT id, ST_X(geom) lon, ST_Y(geom) lat, directions_deg FROM cameras"
                                " WHERE source_id = :s"), {"s": args.camera}).one()
        snapped = {(r.u, r.v, r.key) for r in conn.execute(
            text("SELECT u, v, key FROM camera_edges WHERE camera_id = :c"), {"c": cam.id})}

    kx = 111_320 * math.cos(math.radians(cam.lat))
    ky = 110_540
    R, W = args.radius, 900
    scale = W / (2 * R)

    def xy(lon, lat):
        return ((lon - cam.lon) * kx + R) * scale, (R - (lat - cam.lat) * ky) * scale

    def path(coords):
        return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(*c) for c in coords))

    G = load_or_build_graph()
    view = box(cam.lon - R / kx * 1.2, cam.lat - R / ky * 1.2, cam.lon + R / kx * 1.2, cam.lat + R / ky * 1.2)
    edges = ox.graph_to_gdfs(G, nodes=False)
    edges = edges[edges.intersects(view)]

    colors = {"snap": "#27ae60", "cam": "#111111", **{k: v for k, v in zip(["r0", "r1"], ROUTE_COLORS.values())}}
    markers = "".join(
        f'<marker id="arr-{k}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" '
        f'markerUnits="strokeWidth" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
        for k, c in colors.items()
    )
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{W}" font-family="Helvetica" font-size="13">',
           f'<rect width="{W}" height="{W}" fill="#fbfbf8"/>', f"<defs>{markers}</defs>"]
    labelled = set()
    for (u, v, k), row in edges.iterrows():
        snap = (u, v, k) in snapped
        arrow = ' marker-end="url(#arr-snap)"' if snap else ""
        svg.append(f'<path d="{path(row.geometry.coords)}" fill="none" stroke="{"#27ae60" if snap else "#c8c8c0"}" '
                   f'stroke-width="{7 if snap else 4}" stroke-linecap="round" opacity="0.9"{arrow}/>')
        name = row.get("name")
        name = ";".join(name) if isinstance(name, list) else name
        if isinstance(name, str) and name not in labelled:
            mid = row.geometry.interpolate(0.5, normalized=True)
            x, y = xy(mid.x, mid.y)
            if 20 < x < W - 120 and 20 < y < W - 20:
                svg.append(f'<text x="{x + 6:.0f}" y="{y - 6:.0f}" fill="#555">{name}</text>')
                labelled.add(name)

    router, cameras = Router(G), load_camera_set(engine)
    day = datetime(2026, 10, 13)
    legend = []
    for n, ((label, color), (o, d, hhmm)) in enumerate(
        zip(ROUTE_COLORS.items(), [(HOME, WORK, (7, 45)), (WORK, HOME, (17, 15))])
    ):
        r = router.route(o, d, day.replace(hour=hhmm[0], minute=hhmm[1]))
        passes = [ps for ps in match_route(r, cameras, o, d, MatchConfig()) if ps.camera_id == cam.id]
        outcome = ", ".join(f"{'CAPTURED' if ps.captured else 'skipped: ' + ps.reason.value} at {ps.travel_bearing_deg:.0f} deg"
                            for ps in passes) or "not passed"
        svg.append(f'<path d="{path(r.coords)}" fill="none" stroke="{color}" stroke-width="3" '
                   f'stroke-dasharray="8 5"/>')
        # direction chevrons along the route inside the view
        for a, b in zip(r.coords, r.coords[1:]):
            (x1, y1), (x2, y2) = xy(*a), xy(*b)
            if 0 < x1 < W and 0 < y1 < W and math.hypot(x2 - x1, y2 - y1) > 60:
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                svg.append(f'<path d="M {x1:.1f},{y1:.1f} L {mx:.1f},{my:.1f}" stroke="{color}" stroke-width="3" '
                           f'fill="none" marker-end="url(#arr-r{n})"/>')
        legend.append((color, f"{label}: {r.length_m / 1000:.2f} km, camera {outcome}"))

    cx, cy = xy(cam.lon, cam.lat)
    for d in cam.directions_deg or []:
        lat2, lon2 = destination(cam.lat, cam.lon, d, 40)
        x2, y2 = xy(lon2, lat2)
        svg.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#111" stroke-width="3" '
                   f'marker-end="url(#arr-cam)"/>')
    svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="#111"/>')
    svg.append(f'<text x="{cx - 60:.0f}" y="{cy - 16:.0f}" font-weight="bold">{args.camera} faces '
               f'{"/".join(f"{d:g}" for d in cam.directions_deg or [])}</text>')

    y0 = W - 110
    svg.append(f'<rect x="10" y="{y0 - 20}" width="{W - 20}" height="112" fill="#ffffff" stroke="#ddd"/>')
    for i, (color, text_) in enumerate(legend):
        svg.append(f'<line x1="20" y1="{y0 + i * 24}" x2="60" y2="{y0 + i * 24}" stroke="{color}" stroke-width="3" stroke-dasharray="8 5"/>')
        svg.append(f'<text x="70" y="{y0 + i * 24 + 4}">{text_}</text>')
    svg.append(f'<line x1="20" y1="{y0 + 48}" x2="60" y2="{y0 + 48}" stroke="#27ae60" stroke-width="7"/>'
               f'<text x="70" y="{y0 + 52}">edges the camera is snapped to (arrows = travel direction)</text>')
    svg.append(f'<text x="20" y="{y0 + 78}" fill="#777">{2 * R:.0f} m across; grey = other drive-network edges</text>')
    svg.append("</svg>")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(svg))
    print(f"Wrote {args.out}")
    for _, t in legend:
        print(" ", t)


if __name__ == "__main__":
    main()
