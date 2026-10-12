"""Simulate a driver's routine: route and match every planned trip.

Planned departures come from the routine generator. If the previous trip
arrives too late for a planned departure, the trip leaves MIN_STOP after
that arrival instead. Sensor noise is applied afterwards to the captured
passes (see sim.noise).
"""

from dataclasses import dataclass, field
from datetime import timedelta

from platetrail.routines.base import PlannedTrip, Routine
from platetrail.sim.matcher import MatchConfig
from platetrail.sim.routing import AnchorTooFar, Router
from platetrail.sim.trip import CameraPass, CameraSet, TripResult, simulate_trip

MIN_STOP = timedelta(minutes=5)


@dataclass
class SimulatedTrip:
    planned: PlannedTrip
    result: TripResult

    @property
    def delayed_s(self) -> float:
        return (self.result.route.depart - self.planned.depart).total_seconds()


@dataclass
class DriverSimulation:
    routine: Routine
    trips: list[SimulatedTrip] = field(default_factory=list)
    skipped: list[tuple[PlannedTrip, str]] = field(default_factory=list)  # (trip, reason)

    @property
    def passes(self) -> list[CameraPass]:
        return [p for t in self.trips for p in t.result.passes]

    @property
    def captured(self) -> list[CameraPass]:
        return [p for t in self.trips for p in t.result.captured]


def simulate_routine(router: Router, cameras: CameraSet, routine: Routine, cfg: MatchConfig | None = None) -> DriverSimulation:
    cfg = cfg or MatchConfig()
    sim = DriverSimulation(routine)
    ready = None
    for planned in routine.trips:
        depart = planned.depart if ready is None else max(planned.depart, ready)
        try:
            result = simulate_trip(router, cameras, (planned.origin.lon, planned.origin.lat),
                                   (planned.dest.lon, planned.dest.lat), depart, cfg)
        except AnchorTooFar as e:
            sim.skipped.append((planned, str(e)))
            continue
        sim.trips.append(SimulatedTrip(planned, result))
        ready = result.route.arrive + MIN_STOP
    return sim
