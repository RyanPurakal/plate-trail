"""Unicity of read traces (after de Montjoye et al., "Unique in the Crowd", 2013).

A trace is the set of points a data holder sees for one recorded identity.
Here an identity is the recorded (state, plate), so misreads split a car
into separate fragments. A point is (camera, time bin), with a configurable
bin width (resolution).

For a driver with at least p points in their main trace (the one under their
true plate), draw p distinct points at random. The driver is unique if their
trace is the only one containing all p points. Unicity(p) is the share of
eligible drivers who are unique, averaged over `samples` random draws per
driver.

What it means: in a dataset whose plates were pseudonymized or hashed, p
known sightings (camera + hour) of a car would single out its record. The
result depends strongly on the size of the crowd, so report it alongside
the population size.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import numpy as np

Point = tuple[str, int]  # (camera_label, time bin index)


@dataclass(frozen=True)
class TraceRead:
    driver_idx: int  # ground truth
    identity: str  # recorded "state plate"
    camera_label: str
    time: datetime


@dataclass(frozen=True)
class UnicityResult:
    p: int
    resolution_min: int
    eligible: int  # drivers with >= p distinct points in their main trace
    drivers: int
    unique_share: float  # among eligible

    @property
    def eligible_share(self) -> float:
        return self.eligible / self.drivers if self.drivers else 0.0


def to_points(reads: list[TraceRead], resolution_min: int) -> dict[str, set[Point]]:
    epoch = datetime(2000, 1, 1)
    traces: dict[str, set[Point]] = defaultdict(set)
    for r in reads:
        traces[r.identity].add((r.camera_label, int((r.time - epoch).total_seconds() // (resolution_min * 60))))
    return traces


def unicity(
    reads: list[TraceRead],
    true_identity: dict[int, str],
    p: int,
    resolution_min: int = 60,
    samples: int = 5,
    seed: int = 0,
) -> UnicityResult:
    """true_identity: driver_idx -> their true "state plate" (main trace)."""
    traces = to_points(reads, resolution_min)
    holders: dict[Point, set[str]] = defaultdict(set)
    for ident, pts in traces.items():
        for pt in pts:
            holders[pt].add(ident)
    rng = np.random.default_rng([seed, p, resolution_min])
    eligible, unique_total = 0, 0.0
    for driver, ident in sorted(true_identity.items()):
        pts = sorted(traces.get(ident, ()))
        if len(pts) < p:
            continue
        eligible += 1
        hits = 0
        for _ in range(samples):
            chosen = [pts[i] for i in rng.choice(len(pts), size=p, replace=False)]
            matches = set.intersection(*(holders[pt] for pt in chosen))
            hits += matches == {ident}
        unique_total += hits / samples
    return UnicityResult(p, resolution_min, eligible, len(true_identity),
                         unique_total / eligible if eligible else 0.0)


def subsample(reads: list[TraceRead], true_identity: dict[int, str], n: int, seed: int = 0):
    """Restrict to n random drivers (targets and crowd alike), to see how unicity depends on crowd size."""
    drivers = sorted(true_identity)
    if n >= len(drivers):
        return reads, true_identity
    keep = set(np.random.default_rng([seed, n]).choice(drivers, size=n, replace=False).tolist())
    return [r for r in reads if r.driver_idx in keep], {d: i for d, i in true_identity.items() if d in keep}


def unicity_table(reads, true_identity, ps=(1, 2, 3, 4, 6, 8), resolution_min=60, sizes=None, samples=5, seed=0):
    """Rows of {size, p, resolution_min, eligible, eligible_share, unique_share}."""
    sizes = sizes or [len(true_identity)]
    rows = []
    for n in sizes:
        r, t = subsample(reads, true_identity, n, seed)
        for p in ps:
            res = unicity(r, t, p, resolution_min, samples, seed)
            rows.append({"size": len(t), "p": p, "resolution_min": resolution_min, "eligible": res.eligible,
                         "eligible_share": round(res.eligible_share, 4), "unique_share": round(res.unique_share, 4)})
    return rows
