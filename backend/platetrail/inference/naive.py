"""Naive home/work guess from a read log. A BASELINE, not the inference engine.

This is the simplest thing an analyst could do with a plate's read history,
for comparison with the planned inference engine (HDBSCAN anchors, schedule
reconstruction, anomaly detection), which is not built yet. It uses only
what a read log contains: camera and recorded time.

Rules:

* Group reads by calendar day of the recorded time. Days with fewer than
  MIN_READS_PER_DAY reads are ignored.
* Home: the camera that most often records the day's first or last read
  (a day starts and ends at home).
* Work: the camera that most often records the read just before the day's
  longest gap between consecutive reads (the arrival before the day's main
  stay).
* A guess needs at least MIN_DAYS qualifying days; otherwise there is no
  guess ("too few reads").
* The guessed location is the camera's location. Ties go to the camera seen
  first.

Known blind spots: night-shift days split at midnight; a camera far from
home (the only one on the route) becomes the "home" guess anyway.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from platetrail.geo import WGS84

MIN_READS_PER_DAY = 2
MIN_DAYS = 2


@dataclass(frozen=True)
class LogRead:
    time: datetime
    camera_label: str


@dataclass(frozen=True)
class Guess:
    camera_label: str
    lon: float
    lat: float
    support_days: int  # days that voted for this camera
    days_used: int

    def error_m(self, lon: float, lat: float) -> float:
        return WGS84.inv(self.lon, self.lat, lon, lat)[2]


@dataclass(frozen=True)
class NaiveResult:
    home: Guess | None
    work: Guess | None
    days_used: int
    top_camera: str | None  # the camera with the most reads overall

    @property
    def possible(self) -> bool:
        return self.home is not None


def _mode(votes: list[str]) -> tuple[str, int]:
    counts = Counter(votes)
    first_seen = {c: i for i, c in reversed(list(enumerate(votes)))}
    best = max(counts, key=lambda c: (counts[c], -first_seen[c]))
    return best, counts[best]


def naive_home_work(reads: list[LogRead], camera_coords: dict[str, tuple[float, float]]) -> NaiveResult:
    """camera_coords maps camera_label -> (lon, lat). Reads with unknown cameras are ignored."""
    usable = sorted((r for r in reads if r.camera_label in camera_coords), key=lambda r: r.time)
    top = _mode([r.camera_label for r in usable])[0] if usable else None

    by_day: dict = defaultdict(list)
    for r in usable:
        by_day[r.time.date()].append(r)
    days = [rs for _, rs in sorted(by_day.items()) if len(rs) >= MIN_READS_PER_DAY]
    if len(days) < MIN_DAYS:
        return NaiveResult(None, None, len(days), top)

    home_votes, work_votes = [], []
    for rs in days:
        home_votes += [rs[0].camera_label, rs[-1].camera_label]
        gaps = [(rs[i + 1].time - rs[i].time, i) for i in range(len(rs) - 1)]
        _, i = max(gaps, key=lambda g: (g[0], -g[1]))
        work_votes.append(rs[i].camera_label)

    def guess(votes: list[str], per_day: int) -> Guess:
        label, n = _mode(votes)
        lon, lat = camera_coords[label]
        return Guess(label, lon, lat, n if per_day == 1 else sum(
            1 for rs in days if label in (rs[0].camera_label, rs[-1].camera_label)), len(days))

    return NaiveResult(guess(home_votes, 2), guess(work_votes, 1), len(days), top)
