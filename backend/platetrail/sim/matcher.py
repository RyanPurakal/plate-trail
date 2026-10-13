"""Direction-aware capture decisions. Pure functions; no I/O.

A public-road camera captures a vehicle when the route traverses the
camera's directed edge and the vehicle's travel bearing at the camera is
within `tolerance_deg` of the travel direction the camera captures.

Which travel direction a camera captures depends on the facing convention:

* REAR_PLATE (default): the camera faces the way traffic travels and reads
  rear plates, so it captures travel bearing == camera direction.
* ONCOMING: the camera faces oncoming traffic and reads front plates, so it
  captures travel bearing == camera direction + 180.

Cameras with no direction tag capture everything (UndirectedMode.BEST) or
nothing (UndirectedMode.WORST).

Cameras whose direction tags disagree (direction_ambiguous) use their primary
reading or the alternate one, per AmbiguousDirection.

Private-lot cameras capture arrivals or departures at their lot. Each of
their directions points into the lot or toward the road. Under REAR_PLATE an
"into_lot" direction captures arrivals; ONCOMING flips it. A vehicle uses one
entrance. By default (LotEntrance.ACCESS_ROAD) a lot camera sees an
arrival/departure only if the route turns between the public road and the
lot's service roads at the camera's entrance: the public/service junction
node nearest the camera. So a place with several entrances uses the one
the route actually approaches from.
NEAREST picks the lot camera nearest the route's end instead; ALL lets every
camera at the lot see the event, as an upper bound.
"""

from dataclasses import dataclass
from enum import Enum

from platetrail.geo import angle_diff


class Facing(str, Enum):
    REAR_PLATE = "rear_plate"
    ONCOMING = "oncoming"


class UndirectedMode(str, Enum):
    BEST = "best"  # undirected cameras capture both directions
    WORST = "worst"  # undirected cameras capture neither


class AmbiguousDirection(str, Enum):
    PRIMARY = "primary"  # use the value from the primary tag (`direction`)
    ALTERNATE = "alternate"  # use the disagreeing lower-priority tag


class LotEntrance(str, Enum):
    ACCESS_ROAD = "access_road"  # only lot cameras at the entrance junction the route uses
    NEAREST = "nearest"  # only the lot camera nearest the route's lot-side end
    ALL = "all"  # every camera at the lot sees the event (upper bound)


class LotEvent(str, Enum):
    ARRIVAL = "arrival"
    DEPARTURE = "departure"


class Reason(str, Enum):
    CAPTURED = "captured"
    WRONG_DIRECTION = "wrong_direction"
    UNDIRECTED_BEST = "captured_undirected_best"
    UNDIRECTED_WORST = "missed_undirected_worst"


@dataclass(frozen=True)
class MatchConfig:
    # ASSUMPTION: maximum difference between travel bearing and captured bearing.
    tolerance_deg: float = 45.0
    # ASSUMPTION: cameras face the traffic whose rear plates they read (see Facing).
    facing: Facing = Facing.REAR_PLATE
    # ASSUMPTION: cameras without a direction tag capture both directions.
    undirected: UndirectedMode = UndirectedMode.BEST
    ambiguous_direction: AmbiguousDirection = AmbiguousDirection.PRIMARY
    lot_entrance: LotEntrance = LotEntrance.ACCESS_ROAD

    def __post_init__(self):
        if not 0.0 <= self.tolerance_deg <= 180.0:
            raise ValueError(f"tolerance_deg must be in [0, 180], got {self.tolerance_deg}")
        # Accept plain strings from API/config files.
        object.__setattr__(self, "facing", Facing(self.facing))
        object.__setattr__(self, "undirected", UndirectedMode(self.undirected))
        object.__setattr__(self, "ambiguous_direction", AmbiguousDirection(self.ambiguous_direction))
        object.__setattr__(self, "lot_entrance", LotEntrance(self.lot_entrance))


@dataclass(frozen=True)
class Decision:
    captured: bool
    reason: Reason


def captured_travel_bearing(camera_direction: float, facing: Facing) -> float:
    """Travel bearing a camera facing `camera_direction` captures."""
    return camera_direction % 360.0 if facing is Facing.REAR_PLATE else (camera_direction + 180.0) % 360.0


def choose_directions(
    primary: list[float] | None, alternate: list[float] | None, cfg: MatchConfig
) -> list[float] | None:
    if alternate and cfg.ambiguous_direction is AmbiguousDirection.ALTERNATE:
        return alternate
    return primary


def choose_facings(primary: list[str] | None, alternate: list[str] | None, cfg: MatchConfig) -> list[str] | None:
    """Lot-camera facings for the configured reading of an ambiguous camera."""
    if alternate and cfg.ambiguous_direction is AmbiguousDirection.ALTERNATE:
        return alternate
    return primary


def _undirected(cfg: MatchConfig) -> Decision:
    if cfg.undirected is UndirectedMode.BEST:
        return Decision(True, Reason.UNDIRECTED_BEST)
    return Decision(False, Reason.UNDIRECTED_WORST)


def edge_decision(directions: list[float] | None, travel_bearing: float, cfg: MatchConfig) -> Decision:
    """Does a camera with `directions` capture a vehicle travelling at `travel_bearing`?"""
    if not directions:
        return _undirected(cfg)
    for d in directions:
        if angle_diff(captured_travel_bearing(d, cfg.facing), travel_bearing) <= cfg.tolerance_deg:
            return Decision(True, Reason.CAPTURED)
    return Decision(False, Reason.WRONG_DIRECTION)


def lot_decision(facings: list[str] | None, event: LotEvent, cfg: MatchConfig) -> Decision:
    """Does a lot camera with these facings capture an arrival/departure?"""
    if not facings:
        return _undirected(cfg)
    # Under REAR_PLATE, a camera pointing into the lot sees vehicles driving in.
    wanted = "into_lot" if event is LotEvent.ARRIVAL else "toward_road"
    if cfg.facing is Facing.ONCOMING:
        wanted = "toward_road" if wanted == "into_lot" else "into_lot"
    if wanted in facings:
        return Decision(True, Reason.CAPTURED)
    return Decision(False, Reason.WRONG_DIRECTION)
