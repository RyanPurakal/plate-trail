"""Route a few demo trips and show which cameras capture them.

    python scripts/sample_trips.py [--facing rear_plate|oncoming] [--tolerance 45]

Needs the camera ETL and roads step to have run (uses the cached graph).
Trip endpoints are offsets from real camera positions so routes pass the
same-road opposite-facing pairs.
"""

import argparse
from datetime import datetime

from platetrail.db import get_engine
from platetrail.etl.export_geojson import destination
from platetrail.roads.graph import load_or_build_graph
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.routing import Router
from platetrail.sim.trip import load_camera_set, simulate_trip


def along(lat, lon, bearing, m):
    lat2, lon2 = destination(lat, lon, bearing, m)
    return (lon2, lat2)


COLLEGE_AVE = (40.50505, -74.45383)  # nodes 14133888238 (faces 330) / 14133888239 (faces 125)
TIMBER_OAKS = (40.58614, -74.37354)  # nodes 13326897023 (85) / 13326897024 (255)
MONTROSE = (40.54795, -74.39828)  # nodes 14157962802 (313) / 14157982302 (144)
MENLO_PARK_MALL = (-74.33545, 40.54717)  # inside the retail polygon (lon, lat)

TRIPS = [
    ("College Ave, south-east bound", along(*COLLEGE_AVE, 322, 350), along(*COLLEGE_AVE, 142, 350), 8),
    ("College Ave, north-west bound", along(*COLLEGE_AVE, 142, 350), along(*COLLEGE_AVE, 322, 350), 17),
    ("Timber Oaks Rd, eastbound", along(*TIMBER_OAKS, 267, 300), along(*TIMBER_OAKS, 93, 300), 7),
    ("Montrose Rd, south-east bound", along(*MONTROSE, 328, 300), along(*MONTROSE, 148, 300), 9),
    ("Timber Oaks -> Menlo Park Mall", along(*TIMBER_OAKS, 267, 300), MENLO_PARK_MALL, 13),
    ("Menlo Park Mall -> Timber Oaks", MENLO_PARK_MALL, along(*TIMBER_OAKS, 267, 300), 15),
    ("Edison (Montrose) -> New Brunswick (College Ave)", along(*MONTROSE, 328, 300), along(*COLLEGE_AVE, 142, 350), 8),
]


def fmt_dirs(cam):
    return "/".join(f"{d:g}" for d in cam.directions_deg) if cam.directions_deg else "none"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--facing", default="rear_plate", choices=["rear_plate", "oncoming"])
    p.add_argument("--tolerance", type=float, default=45.0)
    p.add_argument("--undirected", default="best", choices=["best", "worst"])
    p.add_argument("--ambiguous", default="primary", choices=["primary", "alternate"])
    p.add_argument("--lot-entrance", default="nearest", choices=["nearest", "all"])
    args = p.parse_args()
    cfg = MatchConfig(args.tolerance, args.facing, args.undirected, args.ambiguous, args.lot_entrance)

    router = Router(load_or_build_graph())
    cameras = load_camera_set(get_engine())
    print(f"Config: facing={cfg.facing.value}, tolerance={cfg.tolerance_deg:g}, "
          f"undirected={cfg.undirected.value}, ambiguous={cfg.ambiguous_direction.value}, "
          f"lot_entrance={cfg.lot_entrance.value}\n")

    for name, origin, dest, hour in TRIPS:
        r = simulate_trip(router, cameras, origin, dest, datetime(2026, 10, 12, hour, 0), cfg)
        rt = r.route
        roads = []
        for e in rt.edges:
            if e.name and (not roads or roads[-1] != e.name):
                roads.append(e.name)
        print(f"== {name}")
        print(f"   {rt.length_m / 1000:.2f} km, {rt.duration_s / 60:.1f} min, departs {rt.depart:%H:%M}, "
              f"{len(r.passes)} camera(s) passed, {len(r.captured)} captured")
        print(f"   via: {' > '.join(roads[:8])}{' > ...' if len(roads) > 8 else ''}")
        print(f"   origin/dest snapped {rt.origin_snap_m:.0f} m / {rt.dest_snap_m:.0f} m to the network")
        for ps in r.passes:
            cam = cameras.by_id[ps.camera_id]
            where = ps.road_name or "unnamed"
            travel = f"travel {ps.travel_bearing_deg:5.1f}" if ps.travel_bearing_deg is not None else f"{ps.event:>12}"
            mark = "CAPTURED" if ps.captured else f"skipped ({ps.reason.value})"
            flags = "".join([" [snap_ambiguous]" if cam.snap_ambiguous else "",
                             " [direction_ambiguous]" if cam.direction_ambiguous else ""])
            print(f"   {ps.time:%H:%M:%S}  {ps.label:<17} {where[:24]:<24} faces {fmt_dirs(cam):<8} {travel}  {mark}{flags}")
        print()


if __name__ == "__main__":
    main()
