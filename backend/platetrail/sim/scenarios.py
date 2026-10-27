"""Camera-density scenarios: add synthetic cameras where real locations are unknown.

Some areas have more fixed cameras planned or installed than are publicly
mapped (in the example study, additional cameras in the scenario town whose
locations are not public). A density scenario adds N synthetic cameras at
simulation time. They are never written to the cameras table; they are
stored with the run that used them.

Placement (ASSUMPTION; not based on any actual placement plan):

* Candidate roads: public edges of the given highway types (default: trunk,
  primary, secondary, tertiary, the arterials where fixed plate-reader
  cameras are usually mounted) whose midpoint lies inside the town polygon.
* Each camera picks a road with probability proportional to length and a
  uniform point along it, at least MIN_SPACING_M from every real and every
  other synthetic camera (rejection sampling).
* Each camera faces one travel direction (random on two-way roads, the
  road's direction on one-way roads), like most mapped cameras here. It is
  snapped to both directed edges of a two-way road, like real cameras, and
  the matcher decides captures.
* Synthetic cameras get negative ids and labels "scenario/<seed>/<i>".

The scenario town can be any town of the active region (`density_scenario`);
the region's `scenario_town` is only the default.
"""

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from platetrail.roads.snap import is_service
from platetrail.sim.routing import Router
from platetrail.sim.trip import CameraEdge, CameraSet, SimCamera

ARTERIALS = ("trunk", "primary", "secondary", "tertiary")
MIN_SPACING_M = 300.0
MAX_TRIES_PER_CAMERA = 200
PLACEMENT = "assumption: arterials, length-weighted, >= 300 m apart"


@dataclass(frozen=True)
class ScenarioCamera:
    label: str
    lon: float
    lat: float
    direction_deg: float

    def as_json(self) -> dict:
        return {"label": self.label, "lon": self.lon, "lat": self.lat, "directions_deg": [self.direction_deg]}


def _highways(value) -> set[str]:
    return set(value) if isinstance(value, list) else {value}


def synthetic_cameras(
    router: Router,
    n: int,
    seed: int,
    within: BaseGeometry | None = None,
    existing: list[tuple[float, float]] = (),
    highway_types: tuple[str, ...] | None = ARTERIALS,
    min_spacing_m: float = MIN_SPACING_M,
) -> tuple[list[SimCamera], list[ScenarioCamera]]:
    """Place n synthetic cameras. `within` is a lon/lat polygon; `existing` are real camera (lon, lat)."""
    if n <= 0:
        return [], []
    idx = router.index
    keys_pos = {k: i for i, k in enumerate(idx.keys)}
    candidates = []  # (index into idx, reverse index or None)
    seen_roads = set()
    for i, (u, v, k) in enumerate(idx.keys):
        data = router.G[u][v][k]
        if is_service(data.get("highway")):
            continue
        if highway_types is not None and not (_highways(data.get("highway")) & set(highway_types)):
            continue
        road = frozenset((u, v))
        if road in seen_roads:
            continue
        mid = idx.geoms[i].interpolate(0.5, normalized=True)
        if within is not None and not within.covers(Point(*idx.to_wgs.transform(mid.x, mid.y))):
            continue
        seen_roads.add(road)
        rev = router._reverse((u, v, k))
        candidates.append((i, keys_pos.get(rev) if rev else None))
    if not candidates:
        raise ValueError("no candidate roads for scenario cameras")

    lengths = np.array([idx.geoms[i].length for i, _ in candidates])
    probs = lengths / lengths.sum()
    rng = np.random.default_rng([seed, 7_919, n])
    placed_pts = [idx.project_point(lon, lat) for lon, lat in existing]
    sims, records = [], []
    for c in range(n):
        for _ in range(MAX_TRIES_PER_CAMERA):
            ci = int(rng.choice(len(candidates), p=probs))
            i, ri = candidates[ci]
            frac = float(rng.random())
            pt = idx.geoms[i].interpolate(frac, normalized=True)
            if all(pt.distance(q) >= min_spacing_m for q in placed_pts):
                break
        else:
            raise ValueError(f"could not place scenario camera {c + 1} of {n} with {min_spacing_m:g} m spacing")
        placed_pts.append(pt)
        fwd_bearing = idx.bearing_at(idx.geoms[i], idx.geoms[i].project(pt))
        edges = [CameraEdge(idx.keys[i], frac, fwd_bearing)]
        facing = fwd_bearing
        if ri is not None:
            rgeom = idx.geoms[ri]
            rfrac = 1.0 - frac
            rbearing = idx.bearing_at(rgeom, rfrac * rgeom.length)
            edges.append(CameraEdge(idx.keys[ri], rfrac, rbearing))
            if rng.random() < 0.5:
                facing = rbearing
        lon, lat = idx.to_wgs.transform(pt.x, pt.y)
        label = f"scenario/{seed}/{c + 1}"
        sims.append(SimCamera(camera_id=-(c + 1), label=label, kind="public_road", directions_deg=[facing],
                              edges=edges, lon=lon, lat=lat))
        records.append(ScenarioCamera(label, lon, lat, facing))
    return sims, records


def density_scenario(router: Router, cameras: CameraSet, towns: dict[str, BaseGeometry], n: int, seed: int,
                     town: str | None = None) -> tuple[CameraSet, dict]:
    """Real cameras plus n synthetic ones in `town` (default: the region's scenario_town), and the scenario json.

    `towns` maps town name to a lon/lat polygon. A town missing from a non-empty `towns` is an error rather
    than a silent fallback to the whole network; with no towns loaded at all (toy graphs) cameras go
    anywhere on the network and the scenario's town is None.
    """
    if town is None:
        from platetrail.region import get_region

        town = get_region().scenario_town
    if towns and town not in towns:
        raise ValueError(f"unknown scenario town {town!r}; expected one of {sorted(towns)}")
    within = towns.get(town) if towns else None
    sims, recs = synthetic_cameras(router, n, seed, within=within,
                                   existing=[(c.lon, c.lat) for c in cameras.by_id.values() if c.lon is not None])
    scenario = {"extra_cameras": n, "town": town if within is not None else None, "placement": PLACEMENT,
                "cameras": [r.as_json() for r in recs]}
    return CameraSet(list(cameras.by_id.values()) + sims), scenario
