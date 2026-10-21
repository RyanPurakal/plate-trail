"""Routine generator from 2022 NHTS one-day travel diaries.

NHTS gives each person a single travel day, so a synthetic driver's week is
assembled day by day:

1. The persona (worker / student / non_worker) comes from NHTS driver weights,
   unless one is requested.
2. For each day of the week, the day is a stay-at-home day with the weighted
   NHTS share for that persona and weekday. Otherwise a usable diary is drawn,
   weighted by WTPERFIN, from the same persona and weekday. If fewer than
   MIN_POOL diaries match, it falls back to the same persona and day type
   (weekday / weekend), then any persona on that day, then all diaries
   (using the first non-empty pool if none reaches MIN_POOL).
3. Each diary trip keeps its NHTS departure time and purpose. Destinations are
   local places chosen by purpose, at a distance matching the diary's trip
   length (straight line x CIRCUITY; see routines.places):
   home -> home; work -> the driver's fixed work place; school -> the fixed
   school; drop-offs and visits -> another residence; other purposes -> a
   place category (PURPOSE_CATEGORIES). Errand places are reused with
   probability HABIT_P, like the templates.
4. Diaries are closed home-to-home chains, so each day starts and ends at home.

Anchors are sampled without reference to camera locations: home on residential
streets weighted by length; work and school uniform over places of the right
kind. Assumptions: CIRCUITY, HABIT_P, the purpose -> category mapping, and that
national NHTS behaviour applies locally.
"""

from datetime import date, datetime, time, timedelta

import numpy as np

from platetrail.region import Region, get_region
from platetrail.routines.base import PlannedTrip, Routine, RoutineGenerator
from platetrail.routines.nhts_data import PERSONAS, Diary, NHTSDiaries
from platetrail.routines.places import (
    WORK_CATEGORIES,
    Place,
    PlacePool,
    sample_by_distance,
    sample_home_by_distance,
)
from platetrail.routines.templates import HABIT_P, MIN_GAP

MIN_POOL = 20
MILE_M = 1609.344

# ASSUMPTION: NHTS trip purpose (WHYTO) -> local place categories.
PURPOSE_CATEGORIES: dict[int, tuple[str, ...]] = {
    4: WORK_CATEGORIES,  # work activity: drop-off/pickup
    5: WORK_CATEGORIES,  # other work-related
    7: ("services",),  # childcare / adult care
    8: ("worship", "services"),  # volunteering
    11: ("services", "hospital"),  # health care
    12: ("food",),
    13: ("grocery", "retail"),
    14: ("services",),
    15: ("leisure",),
    16: ("leisure",),
    18: ("leisure",),
    19: ("worship",),
}
PURPOSE_LABELS = {4: "work_errand", 5: "work_errand", 7: "care", 8: "volunteer", 11: "health", 12: "meal",
                  13: "shopping", 14: "errand", 15: "recreation", 16: "exercise", 18: "recreation", 19: "worship"}
HOME_PURPOSES = {1, 2}  # regular home activities, work from home
WORK_PURPOSES = {3}
SCHOOL_PURPOSES = {6}
OTHER_HOME_PURPOSES = {10, 17}  # drop off / pick up someone, visit friends or relatives
FALLBACK_CATEGORIES = ("retail", "services")

# Python weekday (Mon=0) -> NHTS TRAVDAY (Sun=1 ... Sat=7)
TRAVDAY = {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 1}


class NHTSRoutineGenerator(RoutineGenerator):
    def __init__(self, pool: PlacePool, diaries: NHTSDiaries, persona: str | None = None, region: Region | None = None):
        if persona is not None and persona not in PERSONAS:
            raise ValueError(f"unknown persona {persona!r}; choose from {PERSONAS}")
        self.pool, self.data, self.persona = pool, diaries, persona
        self.region = region or get_region()

    def _pick_persona(self, rng: np.random.Generator) -> str:
        if self.persona:
            return self.persona
        names = list(PERSONAS)
        w = np.array([self.data.persona_weight.get(p, 0.0) for p in names])
        return names[int(rng.choice(len(names), p=w / w.sum()))]

    def _diary(self, persona: str, travday: int, rng: np.random.Generator) -> Diary:
        weekend = {1, 7}
        group = weekend if travday in weekend else {2, 3, 4, 5, 6}
        tiers = [self.data.by(persona, {travday}), self.data.by(persona, group), self.data.by(None, {travday}),
                 self.data.diaries]
        cands = next((t for t in tiers if len(t) >= MIN_POOL), None) or next(t for t in tiers if t)
        w = np.array([d.weight for d in cands])
        return cands[int(rng.choice(len(cands), p=w / w.sum()))]

    def generate(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        if start.weekday() != 0:
            raise ValueError("start must be a Monday")
        persona = self._pick_persona(rng)
        student = persona == "student"
        uni = self.region.student_town
        near_campus = student and uni is not None and rng.random() < self.region.student_home_share
        home = self.pool.sample_home(rng, town=uni if near_campus else None)
        anchors: dict[str, Place] = {"home": home}
        if persona == "worker":
            anchors["work"] = self.pool.sample(WORK_CATEGORIES, rng)
        if student:
            anchors["school"] = self.pool.sample("university", rng, town=uni)
        habits: dict[tuple[str, ...], Place] = {}
        trips: list[PlannedTrip] = []

        def add(origin: Place, dest: Place, depart: datetime, purpose: str) -> None:
            if trips and depart < trips[-1].depart + MIN_GAP:
                depart = trips[-1].depart + MIN_GAP
            trips.append(PlannedTrip(origin, dest, depart, purpose))

        def destination(why: int, origin: Place, target_m: float) -> tuple[Place, str]:
            if why in HOME_PURPOSES:
                return home, "home"
            if why in WORK_PURPOSES:
                return (anchors["work"], "work") if "work" in anchors else (
                    sample_by_distance(self.pool, WORK_CATEGORIES, rng, origin, target_m), "work")
            if why in SCHOOL_PURPOSES:
                return (anchors["school"], "school") if "school" in anchors else (
                    sample_by_distance(self.pool, ("university",), rng, origin, target_m), "school")
            if why in OTHER_HOME_PURPOSES:
                return sample_home_by_distance(self.pool, rng, origin, target_m), (
                    "drop_off" if why == 10 else "visit")
            cats = PURPOSE_CATEGORIES.get(why, FALLBACK_CATEGORIES)
            label = PURPOSE_LABELS.get(why, "other")
            if cats in habits and rng.random() < HABIT_P:
                return habits[cats], label
            place = sample_by_distance(self.pool, cats, rng, origin, target_m)
            habits.setdefault(cats, place)
            return place, label

        for d in (start + timedelta(days=i) for i in range(7 * weeks)):
            travday = TRAVDAY[d.weekday()]
            if rng.random() < self.data.stay_home.get((persona, travday), 0.0):
                continue
            here = home
            for trip in self._diary(persona, travday, rng).trips:
                dest, purpose = destination(trip.why_to, here, trip.miles * MILE_M)
                if dest is here:
                    continue  # e.g. home -> home loop trips
                add(here, dest, datetime.combine(d, time()) + timedelta(minutes=trip.start_min), purpose)
                here = dest
            if here is not home:  # diaries are home-to-home, but guard anyway
                add(here, home, trips[-1].depart + MIN_GAP, "home")
        return Routine(driver_id, f"nhts_{persona}", anchors, trips)
