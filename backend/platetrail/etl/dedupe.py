"""Merge camera records that describe the same physical device.

Rules, deliberately conservative because a pole often carries several real
cameras facing different ways:

* The same source id appearing twice is dropped as a duplicate.
* Within one source, records are merged only if they are effectively at the
  same point (<= same_point_m) with the same directions. That is a
  double-mapped node, not two devices.
* Across sources, records within cross_source_m are merged if their
  directions are compatible (either side unknown, or some pair within
  direction_tol_deg).

The surviving camera takes its position from the highest-priority source and
its direction from the first member that has one.
"""

import math
from dataclasses import dataclass, field

from platetrail.etl.loaders.base import CameraRecord

EARTH_RADIUS_M = 6_371_008.8


def distance_m(a: CameraRecord, b: CameraRecord) -> float:
    # Equirectangular approximation; accurate to well under 1% at town scale.
    lat0 = math.radians((a.lat + b.lat) / 2)
    dx = math.radians(b.lon - a.lon) * math.cos(lat0)
    dy = math.radians(b.lat - a.lat)
    return EARTH_RADIUS_M * math.hypot(dx, dy)


def angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def directions_compatible(a: list[float] | None, b: list[float] | None, tol: float) -> bool:
    if not a or not b:
        return True
    return any(angle_diff(x, y) <= tol for x in a for y in b)


def same_directions(a: list[float] | None, b: list[float] | None, tol: float = 1.0) -> bool:
    if not a and not b:
        return True
    if not a or not b or len(a) != len(b):
        return False
    return all(angle_diff(x, y) <= tol for x, y in zip(sorted(a), sorted(b)))


@dataclass
class MergedCamera:
    primary: CameraRecord
    members: list[CameraRecord]

    @property
    def _direction_member(self) -> CameraRecord:
        """First member with a usable direction, else the primary."""
        return next((m for m in [self.primary, *self.members] if m.has_direction), self.primary)

    @property
    def directions_deg(self) -> list[float] | None:
        return self._direction_member.directions_deg

    @property
    def direction_raw(self) -> str | None:
        return self._direction_member.direction_raw

    @property
    def direction_key(self) -> str | None:
        return self._direction_member.direction_key

    @property
    def manufacturer(self) -> str | None:
        return next((m.manufacturer for m in [self.primary, *self.members] if m.manufacturer), None)

    @property
    def sources(self) -> list[str]:
        return sorted({m.source for m in self.members})


@dataclass
class DedupeStats:
    input_records: int = 0
    duplicate_ids_dropped: list[str] = field(default_factory=list)
    merged_within_source: list[tuple[str, str]] = field(default_factory=list)  # (kept, merged)
    merged_cross_source: list[tuple[str, str]] = field(default_factory=list)
    output_cameras: int = 0


def dedupe(
    records: list[CameraRecord],
    source_priority: tuple[str, ...] = ("osm",),
    same_point_m: float = 1.0,
    cross_source_m: float = 15.0,
    direction_tol_deg: float = 30.0,
) -> tuple[list[MergedCamera], DedupeStats]:
    stats = DedupeStats(input_records=len(records))

    unique: list[CameraRecord] = []
    seen: set[str] = set()
    for r in records:
        if r.key in seen:
            stats.duplicate_ids_dropped.append(r.key)
            continue
        seen.add(r.key)
        unique.append(r)

    def rank(r: CameraRecord) -> tuple[int, int, str]:
        prio = source_priority.index(r.source) if r.source in source_priority else len(source_priority)
        return (prio, 0 if r.has_direction else 1, r.key)

    unique.sort(key=rank)

    # Union-find over pairwise matches; n is small (hundreds), so O(n^2) is fine.
    parent = list(range(len(unique)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(unique):
        for j in range(i + 1, len(unique)):
            b = unique[j]
            d = distance_m(a, b)
            if a.source == b.source:
                match = d <= same_point_m and same_directions(a.directions_deg, b.directions_deg)
            else:
                match = d <= cross_source_m and directions_compatible(
                    a.directions_deg, b.directions_deg, direction_tol_deg
                )
            if match:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)  # lower index = higher rank wins

    groups: dict[int, list[CameraRecord]] = {}
    for i, r in enumerate(unique):
        groups.setdefault(find(i), []).append(r)

    merged: list[MergedCamera] = []
    for root in sorted(groups):
        members = groups[root]
        primary = members[0]
        for m in members[1:]:
            bucket = stats.merged_within_source if m.source == primary.source else stats.merged_cross_source
            bucket.append((primary.key, m.key))
        merged.append(MergedCamera(primary=primary, members=members))

    stats.output_cameras = len(merged)
    return merged, stats
