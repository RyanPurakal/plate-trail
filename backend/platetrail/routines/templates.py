"""Hand-written weekly routine templates: commuter, student, shift worker.

A stand-in until the NHTS generator. Every number below (times, spreads,
probabilities, errand mix, distance decay) is an ASSUMPTION chosen to look
plausible, not a measured value.

Anchor sampling never looks at camera locations:

* Home: a point on a residential street, weighted by street length
  (PlacePool.sample_home).
* Work, school: uniform over places of the right kind.
* Errands: pick a category from ERRAND_MIX, then a place in it, weighted by
  exp(-distance / DECAY_KM) from where the trip starts. A mall with many
  shops is picked more often because it has more shops, not because it has
  cameras.
* Habits: each driver keeps a "usual" place per errand category and reuses it
  with probability HABIT_P, since people revisit places.
"""

from datetime import date, datetime, time, timedelta

import numpy as np

from platetrail.routines.base import PlannedTrip, Routine, RoutineGenerator
from platetrail.region import Region, get_region
from platetrail.routines.places import WORK_CATEGORIES, Place, PlacePool

# ASSUMPTION: share of errand trips by destination category.
ERRAND_MIX = {"grocery": 0.28, "retail": 0.22, "food": 0.25, "services": 0.15, "leisure": 0.10}
# ASSUMPTION: distance decay scale for choosing errand destinations (km).
DECAY_KM = 4.0
# ASSUMPTION: probability an errand goes to the driver's usual place for that category.
HABIT_P = 0.6
# ASSUMPTION: share of each template when none is requested.
TEMPLATE_WEIGHTS = {"commuter": 0.6, "student": 0.2, "shift_worker": 0.2}
# ASSUMPTION: minutes allowed for driving between chained stops when planning.
TRAVEL_BUFFER_MIN = 20
# Minimum gap between consecutive planned departures (drive + shortest stop).
MIN_GAP = timedelta(minutes=30)


class _Planner:
    """Helper holding one driver's anchors, habits and trip list while planning."""

    def __init__(self, pool: PlacePool, rng: np.random.Generator, home: Place):
        self.pool, self.rng, self.home = pool, rng, home
        self.habits: dict[str, Place] = {}
        self.trips: list[PlannedTrip] = []

    def at(self, day: date, hour: float, sd_min: float) -> datetime:
        """Normal around hour (decimal hours), clipped to +-2.5 sd, rounded to the minute."""
        z = float(np.clip(self.rng.standard_normal(), -2.5, 2.5))
        minutes = round(hour * 60 + z * sd_min)
        return datetime.combine(day, time()) + timedelta(minutes=minutes)

    def dwell(self, lo: int, hi: int) -> timedelta:
        return timedelta(minutes=int(self.rng.integers(lo, hi + 1)))

    def errand_place(self, near: Place, categories: dict[str, float] | None = None) -> tuple[Place, str]:
        mix = categories or ERRAND_MIX
        cats = list(mix)
        cat = cats[int(self.rng.choice(len(cats), p=np.array(list(mix.values())) / sum(mix.values())))]
        if cat in self.habits and self.rng.random() < HABIT_P:
            return self.habits[cat], cat
        place = self.pool.sample(cat, self.rng, near=near, decay_km=DECAY_KM)
        self.habits.setdefault(cat, place)
        return place, cat

    def trip(self, origin: Place, dest: Place, depart: datetime, purpose: str) -> None:
        """Append a trip, keeping departures in planning order at least MIN_GAP apart."""
        if self.trips and depart < self.trips[-1].depart + MIN_GAP:
            depart = self.trips[-1].depart + MIN_GAP
        self.trips.append(PlannedTrip(origin, dest, depart, purpose))

    def errand_chain(self, start: datetime, n: int, categories: dict[str, float] | None = None) -> None:
        """home -> n errands -> home, each stop's departure after a dwell and a travel buffer."""
        here, t = self.home, start
        for _ in range(n):
            place, cat = self.errand_place(here, categories)
            self.trip(here, place, t, cat)
            t = t + timedelta(minutes=TRAVEL_BUFFER_MIN) + self.dwell(30, 90)
            here = place
        self.trip(here, self.home, t, "home")


class TemplateRoutineGenerator(RoutineGenerator):
    def __init__(self, pool: PlacePool, template: str | None = None, region: Region | None = None):
        if template is not None and template not in TEMPLATE_WEIGHTS:
            raise ValueError(f"unknown template {template!r}; choose from {sorted(TEMPLATE_WEIGHTS)}")
        self.pool = pool
        self.template = template
        self.region = region or get_region()

    def generate(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        if start.weekday() != 0:
            raise ValueError("start must be a Monday")
        name = self.template or list(TEMPLATE_WEIGHTS)[
            int(rng.choice(len(TEMPLATE_WEIGHTS), p=list(TEMPLATE_WEIGHTS.values())))
        ]
        return getattr(self, f"_{name}")(driver_id, start, weeks, rng)

    # ---- templates -----------------------------------------------------------------------

    def _commuter(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        home = self.pool.sample_home(rng)
        p = _Planner(self.pool, rng, home)
        work = self.pool.sample(WORK_CATEGORIES, rng)
        for d in (start + timedelta(days=i) for i in range(7 * weeks)):
            if d.weekday() < 5:
                p.trip(home, work, p.at(d, 7.67, 20), "work")
                leave = p.at(d, 17.25, 30)
                if rng.random() < 0.30:  # errand on the way home
                    place, cat = p.errand_place(work)
                    p.trip(work, place, leave, cat)
                    p.trip(place, home, leave + timedelta(minutes=TRAVEL_BUFFER_MIN) + p.dwell(20, 45), "home")
                else:
                    p.trip(work, home, leave, "home")
                if rng.random() < 0.20:  # evening outing
                    t = p.at(d, 19.25, 30)
                    place, cat = p.errand_place(home, {"food": 0.6, "leisure": 0.4})
                    p.trip(home, place, t, cat)
                    p.trip(place, home, t + timedelta(minutes=TRAVEL_BUFFER_MIN) + p.dwell(60, 120), "home")
            elif d.weekday() == 5:
                p.errand_chain(p.at(d, 10.5, 60), int(rng.integers(1, 4)))
            else:
                self._sunday(p, d)
        return Routine(driver_id, "commuter", {"home": home, "work": work, **_habit_anchors(p)}, p.trips)

    def _student(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        uni = self.region.student_town
        near_campus = rng.random() < self.region.student_home_share
        home = self.pool.sample_home(rng, town=None if uni is None else uni if near_campus else self.region.other_towns(uni))
        p = _Planner(self.pool, rng, home)
        school = self.pool.sample("university", rng, town=uni)
        for d in (start + timedelta(days=i) for i in range(7 * weeks)):
            wd = d.weekday()
            if wd < 4 or (wd == 4 and rng.random() < 0.5):
                p.trip(home, school, p.at(d, 9.5, 60), "school")
                p.trip(school, home, p.at(d, 16.5, 90), "home")
                if rng.random() < 0.35:
                    t = p.at(d, 19.5, 45)
                    place, cat = p.errand_place(home, {"food": 0.7, "leisure": 0.3})
                    p.trip(home, place, t, cat)
                    p.trip(place, home, t + timedelta(minutes=TRAVEL_BUFFER_MIN) + p.dwell(60, 90), "home")
            elif wd == 5:
                p.errand_chain(p.at(d, 12.0, 90), int(rng.integers(1, 3)))
            elif wd == 6 and rng.random() < 0.5:
                p.errand_chain(p.at(d, 14.0, 60), 1)
        return Routine(driver_id, "student", {"home": home, "school": school, **_habit_anchors(p)}, p.trips)

    def _shift_worker(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        home = self.pool.sample_home(rng)
        p = _Planner(self.pool, rng, home)
        work = self.pool.sample("hospital" if rng.random() < 0.5 else "industrial", rng)
        shift_days = set(int(x) for x in rng.choice(7, size=4, replace=False))  # fixed weekly night shifts
        for d in (start + timedelta(days=i) for i in range(7 * weeks)):
            if d.weekday() in shift_days:
                p.trip(home, work, p.at(d, 18.5, 10), "work")  # 19:00-07:00 night shift
                p.trip(work, home, p.at(d + timedelta(days=1), 7.25, 10), "home")
            elif rng.random() < 0.6:
                p.errand_chain(p.at(d, 13.0, 90), 1)
        return Routine(driver_id, "shift_worker", {"home": home, "work": work, **_habit_anchors(p)}, p.trips)

    def _sunday(self, p: _Planner, d: date) -> None:
        if p.rng.random() < 0.4:
            if "worship" not in p.habits:
                p.habits["worship"] = p.pool.sample("worship", p.rng, near=p.home, decay_km=DECAY_KM)
            t = p.at(d, 10.0, 15)
            p.trip(p.home, p.habits["worship"], t, "worship")
            p.trip(p.habits["worship"], p.home, t + timedelta(minutes=TRAVEL_BUFFER_MIN) + p.dwell(60, 90), "home")
        if p.rng.random() < 0.5:
            p.errand_chain(p.at(d, 14.0, 60), 1)


def _habit_anchors(p: _Planner) -> dict[str, Place]:
    return {f"usual_{k}": v for k, v in p.habits.items()}
