"""Sensor noise: turns ground-truth captures into a noisy read log.

Input is the list of true passes, i.e. camera passes the matcher marked
captured. For each one, in this order:

1. Downtime: if the camera has an outage window covering the pass time, the
   pass is dropped (reason "downtime"). Outages are per camera and drawn
   once for the whole simulation period.
2. Missed read: dropped with probability p_miss (reason "missed").
3. Otherwise a read is recorded. Each plate character may be swapped for a
   look-alike (plates.LOOKALIKES) with probability p_char_misread, and the
   timestamp gets Gaussian jitter.
4. Extra read errors (`NoiseConfig.extra_read_errors`), applied in order to
   the plate string. This is the hook for error types not modelled yet:
   dropped or extra characters, wrong state, partial reads.

Every read keeps `pass_id`, the link to the true pass, so later analysis can
measure how misreads break linking reads to one driver.

Reproducibility: all randomness derives from `seed`. Outages use one stream
per camera and noise uses one stream per pass, both keyed by stable ids
(camera_id, pass_id). Changing one setting, e.g. p_miss, therefore doesn't
reshuffle the random draws behind the others. Each extra read error draws
from its own stream ([seed, error.stream, pass_id]), so adding one leaves
every existing draw, and thus every existing read, unchanged except for
what that error itself does.

Every default below is an ASSUMPTION, not a measured value; see the README.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np

from platetrail.sim.plates import misread

_STREAM_OUTAGE = 1
_STREAM_PASS = 2
# Stream ids >= this are for ReadError implementations; ids below are reserved.
EXTRA_ERROR_STREAM_MIN = 100


class ReadError(Protocol):
    """A read error applied to the plate string after look-alike swaps.

    `stream` must be unique per error type and >= EXTRA_ERROR_STREAM_MIN.
    `apply` receives a generator dedicated to (seed, stream, pass_id).
    """

    stream: int

    def apply(self, plate: str, rng: np.random.Generator) -> str: ...


@dataclass(frozen=True)
class NoiseConfig:
    seed: int = 0
    # ASSUMPTION: chance a captured vehicle produces no read (occlusion,
    # glare, dirty plate, frame drop). Not from a published per-read rate.
    p_miss: float = 0.05
    # ASSUMPTION: per-character chance that a character with a look-alike is
    # misread. With ~3-4 confusable characters per plate, roughly 3-4% of
    # reads come out with a wrong plate string.
    p_char_misread: float = 0.01
    # ASSUMPTION: outages per camera per week (Poisson) and mean outage length
    # in hours (exponential). Defaults give ~1.8% expected downtime per camera.
    downtime_rate_per_week: float = 0.25
    downtime_mean_hours: float = 12.0
    # ASSUMPTION: standard deviation of timestamp error in seconds (clock
    # drift, processing delay), Gaussian around the true pass time.
    jitter_sd_s: float = 2.0
    # Hook for error types not modelled yet (see ReadError). Empty by default.
    extra_read_errors: tuple = ()

    def __post_init__(self):
        for name in ("p_miss", "p_char_misread"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {v}")
        for name in ("downtime_rate_per_week", "downtime_mean_hours", "jitter_sd_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        streams = [e.stream for e in self.extra_read_errors]
        if any(s < EXTRA_ERROR_STREAM_MIN for s in streams) or len(set(streams)) != len(streams):
            raise ValueError(f"extra_read_errors need unique streams >= {EXTRA_ERROR_STREAM_MIN}, got {streams}")

    @classmethod
    def noiseless(cls, seed: int = 0) -> "NoiseConfig":
        return cls(seed=seed, p_miss=0.0, p_char_misread=0.0, downtime_rate_per_week=0.0,
                   downtime_mean_hours=0.0, jitter_sd_s=0.0)


@dataclass(frozen=True)
class TruePass:
    pass_id: int
    camera_id: int
    time: datetime
    plate: str


@dataclass(frozen=True)
class Outage:
    camera_id: int
    start: datetime
    end: datetime

    def covers(self, t: datetime) -> bool:
        return self.start <= t < self.end


@dataclass(frozen=True)
class Read:
    read_id: int
    pass_id: int  # link to the true pass
    camera_id: int
    time: datetime  # as recorded (jittered)
    plate: str  # as recorded (possibly misread)
    true_plate: str  # kept for evaluation only; not part of what a camera reports
    true_time: datetime
    jitter_s: float

    @property
    def misread(self) -> bool:
        return self.plate != self.true_plate


@dataclass(frozen=True)
class DroppedPass:
    pass_id: int
    camera_id: int
    time: datetime
    reason: str  # "downtime" or "missed"


@dataclass
class NoiseResult:
    reads: list[Read]
    dropped: list[DroppedPass]
    outages: dict[int, list[Outage]] = field(default_factory=dict)

    def dropped_for(self, reason: str) -> list[DroppedPass]:
        return [d for d in self.dropped if d.reason == reason]

    @property
    def misreads(self) -> list[Read]:
        return [r for r in self.reads if r.misread]


def outage_windows(
    camera_ids: list[int], start: datetime, end: datetime, cfg: NoiseConfig
) -> dict[int, list[Outage]]:
    """Outage windows per camera over [start, end)."""
    weeks = (end - start).total_seconds() / (7 * 86400)
    out: dict[int, list[Outage]] = {}
    for cid in sorted(set(camera_ids)):
        windows: list[Outage] = []
        if cfg.downtime_rate_per_week > 0 and cfg.downtime_mean_hours > 0 and weeks > 0:
            rng = np.random.default_rng([cfg.seed, _STREAM_OUTAGE, cid])
            n = int(rng.poisson(cfg.downtime_rate_per_week * weeks))
            span_s = (end - start).total_seconds()
            for s, dur_h in zip(rng.random(n) * span_s, rng.exponential(cfg.downtime_mean_hours, n)):
                t0 = start + timedelta(seconds=float(s))
                windows.append(Outage(cid, t0, t0 + timedelta(hours=float(dur_h))))
        out[cid] = sorted(windows, key=lambda o: o.start)
    return out


def apply_noise(
    passes: list[TruePass],
    period_start: datetime,
    period_end: datetime,
    cfg: NoiseConfig,
    camera_ids: list[int] | None = None,
) -> NoiseResult:
    """camera_ids: every camera to draw outages for (defaults to those passed)."""
    outages = outage_windows(camera_ids or [p.camera_id for p in passes], period_start, period_end, cfg)
    reads, dropped = [], []
    for p in sorted(passes, key=lambda p: p.pass_id):
        rng = np.random.default_rng([cfg.seed, _STREAM_PASS, p.pass_id])
        # Fixed draw order per pass: miss uniform, jitter normal, then plate characters.
        u_miss = rng.random()
        z = rng.standard_normal()
        plate = misread(p.plate, rng, cfg.p_char_misread)

        if any(o.covers(p.time) for o in outages.get(p.camera_id, [])):
            dropped.append(DroppedPass(p.pass_id, p.camera_id, p.time, "downtime"))
            continue
        if u_miss < cfg.p_miss:
            dropped.append(DroppedPass(p.pass_id, p.camera_id, p.time, "missed"))
            continue
        for err in cfg.extra_read_errors:
            plate = err.apply(plate, np.random.default_rng([cfg.seed, err.stream, p.pass_id]))
        jitter = z * cfg.jitter_sd_s
        reads.append(Read(0, p.pass_id, p.camera_id, p.time + timedelta(seconds=jitter), plate, p.plate, p.time, jitter))

    reads.sort(key=lambda r: (r.time, r.pass_id))
    reads = [Read(i, r.pass_id, r.camera_id, r.time, r.plate, r.true_plate, r.true_time, r.jitter_s)
             for i, r in enumerate(reads)]
    return NoiseResult(reads, dropped, outages)


def true_passes(captured: list, plate: str, first_id: int = 0) -> list[TruePass]:
    """Number captured CameraPass objects (any order) into TruePasses for one vehicle."""
    ordered = sorted(captured, key=lambda p: (p.time, p.camera_id))
    return [TruePass(first_id + i, p.camera_id, p.time, plate) for i, p in enumerate(ordered)]
