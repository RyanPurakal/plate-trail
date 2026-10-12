"""Routine generator interface.

A RoutineGenerator turns a driver id and a period into a Routine: the
driver's anchors (home, work or school, habitual places) and a list of
planned trips with departure times. Routing, camera matching and noise
happen later, in the simulation.

TemplateRoutineGenerator (routines.templates) implements this with a few
hand-written weekly templates. An NHTS-based generator (routines.nhts) will
implement the same interface, so the simulation doesn't change when it
arrives.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np

from platetrail.routines.places import Place


@dataclass(frozen=True)
class PlannedTrip:
    origin: Place
    dest: Place
    depart: datetime  # planned; the simulation may push it later if the previous trip runs long
    purpose: str  # e.g. "work", "home", "grocery", "school"


@dataclass
class Routine:
    driver_id: int
    template: str
    anchors: dict[str, Place]  # "home", "work"/"school", habitual places
    trips: list[PlannedTrip] = field(default_factory=list)


class RoutineGenerator(ABC):
    @abstractmethod
    def generate(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        """Plan `weeks` weeks of trips starting on `start` (a Monday)."""
