"""Inference engine: what an analyst can infer from one plate's read history.

Input is only what a read log contains: camera location and recorded time.
ALPR reads happen on roads, never at destinations, so stops are inferred
from GAPS between reads:

* A gap of at least STAY_GAP_MIN between consecutive reads is a stay
  somewhere between the camera before and the camera after the gap. Both
  cameras become stay evidence points, tagged by the kind of gap:
  - night: the gap covers 03:00 (overnight), which is evidence of home;
  - day_long: a weekday gap of 3–12 h starting 05:00–14:00, which is
    evidence of work or school;
  - short: anything else.
* Anchors: evidence points are clustered with HDBSCAN (scikit-learn) on
  local metric coordinates. Home is the cluster with the most distinct
  nights of evidence; work is the cluster (other than home) with the most
  distinct long weekday stays. The estimate is the cluster centroid, the
  radius is the cluster spread (at least MIN_RADIUS_M), and confidence comes
  from the number of supporting days and their share.
* Schedule: a regular pass is the same camera at the same time of day
  (within PATTERN_WINDOW_MIN) on at least PATTERN_MIN_DAYS distinct days.
* Anomalies: reads at a camera seen on only one day that belong to no
  regular pass, scored by rarity.

All thresholds are ASSUMPTIONS. They are labelled here and in the README.
Evaluation against ground truth is in evaluate_* below.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sklearn.cluster import HDBSCAN

from platetrail.geo import WGS84

STAY_GAP_MIN = 45
DAY_LONG_MIN_H, DAY_LONG_MAX_H = 3, 12
MIN_RADIUS_M = 500.0
PATTERN_WINDOW_MIN = 45
PATTERN_MIN_DAYS = 3
NIGHT_HOUR = 3


@dataclass(frozen=True)
class EngineRead:
    time: datetime
    camera_label: str
    lon: float
    lat: float


@dataclass(frozen=True)
class Evidence:
    kind: str  # night / day_long / short
    lon: float
    lat: float
    day: str  # ISO date the stay starts
    hours: float


@dataclass
class Anchor:
    kind: str  # home / work
    lon: float
    lat: float
    radius_m: float
    support_days: int
    possible_days: int
    confidence: str  # high / medium / low
    nearest_camera: str

    def error_m(self, lon: float, lat: float) -> float:
        return WGS84.inv(self.lon, self.lat, lon, lat)[2]


@dataclass(frozen=True)
class RegularPass:
    camera_label: str
    minute_of_day: int  # typical time
    days: int  # distinct days seen
    weekdays: tuple[int, ...]  # 0 = Monday


@dataclass(frozen=True)
class Anomaly:
    time: datetime
    camera_label: str
    score: float  # 1.0 = camera seen on this one day only, outside any regular pass


@dataclass
class Inference:
    reads: int
    days_with_reads: int
    home: Anchor | None
    work: Anchor | None
    regular: list[RegularPass] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    conclusions: list[str] = field(default_factory=list)


def _confidence(support: int, possible: int) -> str:
    share = support / possible if possible else 0.0
    if support >= 5 and share >= 0.6:
        return "high"
    if support >= 3 and share >= 0.3:
        return "medium"
    return "low"


def stay_evidence(reads: list[EngineRead]) -> list[Evidence]:
    rs = sorted(reads, key=lambda r: r.time)
    out = []
    for a, b in zip(rs, rs[1:]):
        gap = b.time - a.time
        if gap < timedelta(minutes=STAY_GAP_MIN):
            continue
        hours = gap.total_seconds() / 3600
        night_mark = datetime.combine(a.time.date(), datetime.min.time()) + timedelta(hours=NIGHT_HOUR)
        if night_mark <= a.time:
            night_mark += timedelta(days=1)
        if night_mark < b.time:
            kind = "night"
        elif a.time.weekday() < 5 and DAY_LONG_MIN_H <= hours <= DAY_LONG_MAX_H and 5 <= a.time.hour < 14:
            kind = "day_long"
        else:
            kind = "short"
        for r in (a, b):
            out.append(Evidence(kind, r.lon, r.lat, a.time.date().isoformat(), hours))
    return out


MERGE_M = 400.0  # locations closer than this are one place (fallback and HDBSCAN epsilon)


def _greedy_merge(xy: np.ndarray) -> np.ndarray:
    labels = -np.ones(len(xy), dtype=int)
    nxt = 0
    for i in range(len(xy)):
        if labels[i] >= 0:
            continue
        close = np.where((labels < 0) & (np.hypot(*(xy - xy[i]).T) <= MERGE_M))[0]
        labels[close] = nxt
        nxt += 1
    return labels


def _cluster(evidence: list[Evidence]) -> np.ndarray:
    """Cluster labels per evidence point. Evidence points sit at camera locations, so many coincide;
    HDBSCAN runs on the distinct locations (and falls back to merging within MERGE_M when there are
    too few of them, or if it fails), then labels map back to every point."""
    if not evidence:
        return np.zeros(0, dtype=int)
    lat0 = math.radians(np.mean([e.lat for e in evidence]))
    xy = np.array([[e.lon * 111_320 * math.cos(lat0), e.lat * 110_540] for e in evidence])
    uniq, inverse = np.unique(np.round(xy, 1), axis=0, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)
    if len(uniq) < 4:
        ulabels = _greedy_merge(uniq)
    else:
        try:
            ulabels = HDBSCAN(min_cluster_size=2, min_samples=1, allow_single_cluster=True,
                              cluster_selection_epsilon=MERGE_M, copy=True).fit_predict(uniq)
        except (TypeError, ValueError):
            ulabels = _greedy_merge(uniq)
        # Noise locations become their own clusters so a lone but repeated camera still counts.
        nxt = ulabels.max() + 1
        for i in np.where(ulabels == -1)[0]:
            ulabels[i] = nxt
            nxt += 1
    return ulabels[inverse]


def _anchor(kind: str, pts: list[Evidence], support: int, possible: int, reads: list[EngineRead]) -> Anchor:
    lon = float(np.mean([e.lon for e in pts]))
    lat = float(np.mean([e.lat for e in pts]))
    d = [WGS84.inv(lon, lat, e.lon, e.lat)[2] for e in pts]
    radius = max(MIN_RADIUS_M, float(np.percentile(d, 90)) if d else 0.0)
    cams = {(r.camera_label, r.lon, r.lat) for r in reads}
    nearest = min(cams, key=lambda c: WGS84.inv(lon, lat, c[1], c[2])[2])[0] if cams else ""
    return Anchor(kind, lon, lat, radius, support, possible, _confidence(support, possible), nearest)


def regular_passes(reads: list[EngineRead]) -> list[RegularPass]:
    by_cam: dict[str, list[EngineRead]] = defaultdict(list)
    for r in reads:
        by_cam[r.camera_label].append(r)
    out = []
    for cam, rs in by_cam.items():
        mins = sorted(rs, key=lambda r: r.time.hour * 60 + r.time.minute)
        used = set()
        for i, seed in enumerate(mins):
            if i in used:
                continue
            m0 = seed.time.hour * 60 + seed.time.minute
            group = [j for j, r in enumerate(mins)
                     if j not in used and abs(r.time.hour * 60 + r.time.minute - m0) <= PATTERN_WINDOW_MIN]
            days = {mins[j].time.date() for j in group}
            if len(days) >= PATTERN_MIN_DAYS:
                used.update(group)
                typical = int(np.median([mins[j].time.hour * 60 + mins[j].time.minute for j in group]))
                out.append(RegularPass(cam, typical, len(days), tuple(sorted({d.weekday() for d in days}))))
    return sorted(out, key=lambda p: (p.minute_of_day, p.camera_label))


def anomalies(reads: list[EngineRead], regular: list[RegularPass]) -> list[Anomaly]:
    days_per_cam: dict[str, set] = defaultdict(set)
    for r in reads:
        days_per_cam[r.camera_label].add(r.time.date())

    def in_pattern(r: EngineRead) -> bool:
        m = r.time.hour * 60 + r.time.minute
        return any(p.camera_label == r.camera_label and abs(m - p.minute_of_day) <= PATTERN_WINDOW_MIN for p in regular)

    out = []
    for r in reads:
        n_days = len(days_per_cam[r.camera_label])
        if n_days == 1 and not in_pattern(r):
            out.append(Anomaly(r.time, r.camera_label, 1.0))
    return sorted(out, key=lambda a: a.time)


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _days_text(weekdays: tuple[int, ...]) -> str:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if weekdays == (0, 1, 2, 3, 4):
        return "weekdays"
    return ", ".join(names[d] for d in weekdays)


def infer(reads: list[EngineRead], camera_names: dict[str, str] | None = None) -> Inference:
    names = camera_names or {}
    days = sorted({r.time.date() for r in reads})
    ev = stay_evidence(reads)
    labels = _cluster(ev)
    clusters: dict[int, list[Evidence]] = defaultdict(list)
    for e, lab in zip(ev, labels):
        clusters[int(lab)].append(e)

    nights_possible = max(len(days) - 1, 1)
    weekdays_possible = max(sum(1 for d in days if d.weekday() < 5), 1)

    def support(cluster, kind):
        return len({e.day for e in cluster if e.kind == kind})

    home = work = None
    if clusters:
        hk = max(clusters, key=lambda k: (support(clusters[k], "night"), len(clusters[k])))
        if support(clusters[hk], "night") > 0:
            pts = [e for e in clusters[hk] if e.kind == "night"]
            home = _anchor("home", pts, support(clusters[hk], "night"), nights_possible, reads)
        rest = [k for k in clusters if not home or k != hk]
        if rest:
            wk = max(rest, key=lambda k: (support(clusters[k], "day_long"), len(clusters[k])))
            if support(clusters[wk], "day_long") > 0:
                pts = [e for e in clusters[wk] if e.kind == "day_long"]
                work = _anchor("work", pts, support(clusters[wk], "day_long"), weekdays_possible, reads)

    regular = regular_passes(reads)
    anom = anomalies(reads, regular)
    conclusions = []
    for a, what in ((home, "lives"), (work, "works or studies")):
        if a:
            near = names.get(a.nearest_camera, a.nearest_camera)
            unit = "nights" if a.kind == "home" else "weekdays"
            conclusions.append(f"Likely {what} within ~{a.radius_m / 1000:.1f} km of the camera at {near} "
                               f"({a.confidence} confidence: {a.support_days} of {a.possible_days} {unit}).")
    for p in regular[:5]:
        conclusions.append(f"Regularly passes {names.get(p.camera_label, p.camera_label)} around "
                           f"{_hhmm(p.minute_of_day)} on {_days_text(p.weekdays)} ({p.days} days).")
    if anom:
        conclusions.append(f"{len(anom)} read(s) look out of routine (a camera seen on only one day).")
    if not reads:
        conclusions.append("No reads: nothing can be inferred.")
    elif not home and not work:
        conclusions.append("Too little stay evidence to place home or work.")
    return Inference(len(reads), len(days), home, work, regular, anom, conclusions)


# ---- evaluation against ground truth ---------------------------------------------------


def routine_trips(trips: list[dict], window_min: int = PATTERN_WINDOW_MIN, min_days: int = PATTERN_MIN_DAYS):
    """Ground-truth recurring trips: same origin and destination at a similar departure time on >= min_days days.

    trips: dicts with origin, dest (keys), depart (datetime), trip_id. Returns lists of trip_ids, one per routine.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for t in trips:
        groups[(t["origin"], t["dest"])].append(t)
    routines = []
    for ts in groups.values():
        ts = sorted(ts, key=lambda t: t["depart"].hour * 60 + t["depart"].minute)
        used = set()
        for i, s in enumerate(ts):
            if i in used:
                continue
            m0 = s["depart"].hour * 60 + s["depart"].minute
            g = [j for j, t in enumerate(ts) if j not in used
                 and abs(t["depart"].hour * 60 + t["depart"].minute - m0) <= window_min]
            if len({ts[j]["depart"].date() for j in g}) >= min_days:
                used.update(g)
                routines.append([ts[j]["trip_id"] for j in g])
    return routines


def schedule_recovery(routines: list[list], reads_by_trip: dict, regular: list[RegularPass]) -> tuple[int, int]:
    """(recovered, observable): a routine is observable if any of its trips produced a read, and recovered
    if at least half of its trips produced a read matching an inferred regular pass."""
    recovered = observable = 0
    for trip_ids in routines:
        hits = [reads_by_trip.get(t, []) for t in trip_ids]
        if not any(hits):
            continue
        observable += 1
        matched = 0
        for rs in hits:
            if any(p.camera_label == r.camera_label
                   and abs(r.time.hour * 60 + r.time.minute - p.minute_of_day) <= PATTERN_WINDOW_MIN
                   for r in rs for p in regular):
                matched += 1
        recovered += matched >= len(trip_ids) / 2
    return recovered, observable
