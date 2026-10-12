from datetime import timedelta

from platetrail.routines.base import PlannedTrip, Routine
from platetrail.routines.places import Place
from platetrail.sim.driver import MIN_STOP, simulate_routine
from platetrail.sim.routing import Router
from test_trip import DEPART, pair_on_main_st, toy_graph, xy


def place(key, east, north):
    lon, lat = xy(east, north)
    return Place(key, "test", lon, lat)


HOME, WORK, FAR = place("home", 0, 5), place("work", 2000, 5), place("far", 0, 5000)


def test_departure_pushed_after_late_arrival_and_on_time_otherwise():
    router = Router(toy_graph())
    trips = [
        PlannedTrip(HOME, WORK, DEPART, "work"),
        PlannedTrip(WORK, HOME, DEPART + timedelta(seconds=30), "home"),  # planned before the first arrives
        PlannedTrip(HOME, WORK, DEPART + timedelta(hours=5), "work"),  # comfortably later
    ]
    sim = simulate_routine(router, pair_on_main_st(), Routine(1, "test", {"home": HOME}, trips))
    first, second, third = sim.trips
    assert first.result.route.depart == DEPART
    assert second.result.route.depart == first.result.route.arrive + MIN_STOP
    assert second.delayed_s > 0
    assert third.result.route.depart == DEPART + timedelta(hours=5) and third.delayed_s == 0


def test_far_anchor_trip_skipped_and_reported():
    router = Router(toy_graph())
    trips = [PlannedTrip(HOME, FAR, DEPART, "errand"), PlannedTrip(HOME, WORK, DEPART + timedelta(hours=1), "work")]
    sim = simulate_routine(router, pair_on_main_st(), Routine(1, "test", {"home": HOME}, trips))
    assert len(sim.trips) == 1 and len(sim.skipped) == 1
    assert sim.skipped[0][0].dest is FAR


def test_passes_and_captured_aggregate_across_trips():
    router = Router(toy_graph())
    a, b = place("a", 100, 5), place("b", 900, 5)
    trips = [PlannedTrip(a, b, DEPART, "x"), PlannedTrip(b, a, DEPART + timedelta(hours=1), "y")]
    sim = simulate_routine(router, pair_on_main_st(), Routine(1, "test", {"home": a}, trips))
    assert len(sim.passes) == 4  # both cameras passed on each trip
    assert sorted(p.label for p in sim.captured) == ["east-facing", "west-facing"]
