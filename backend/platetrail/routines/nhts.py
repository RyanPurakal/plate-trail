"""Placeholder for an NHTS-based routine generator.

The plan (see the proposal): draw weekly activity patterns from National
Household Travel Survey trip diaries (trip purposes, departure times, dwell
times, trip chains), then place each activity at a real Edison/New Brunswick
place using routines.places.PlacePool. It implements the same
RoutineGenerator interface as TemplateRoutineGenerator, so the simulation
doesn't change. NHTS data is not processed yet.
"""

from datetime import date

import numpy as np

from platetrail.routines.base import Routine, RoutineGenerator


class NHTSRoutineGenerator(RoutineGenerator):
    def generate(self, driver_id: int, start: date, weeks: int, rng: np.random.Generator) -> Routine:
        raise NotImplementedError("NHTS routines are planned but not built yet; use TemplateRoutineGenerator")
