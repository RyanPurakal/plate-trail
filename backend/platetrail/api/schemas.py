"""Request models for the API (responses are plain JSON dicts)."""

from pydantic import BaseModel, Field, field_validator


class AnyLonLat(BaseModel):
    """A point anywhere; the endpoint decides whether it is covered."""
    lon: float = Field(ge=-180.0, le=180.0)
    lat: float = Field(ge=-90.0, le=90.0)


class GeocodeBody(BaseModel):
    """Place search text; in the body so it never appears in access logs. Never stored."""
    q: str = Field(..., min_length=1, max_length=200)


class RouteCheckBody(BaseModel):
    """One saved route's end points, from the visitor's browser. Session-only; never stored."""
    start: AnyLonLat
    end: AnyLonLat
    both_ways: bool = True


class RouteHistoryBody(RouteCheckBody):
    """A saved route plus a simple driving schedule. Session-only; never stored."""
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    leave: str = Field("08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    return_: str = Field("17:30", alias="return", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    retention_days: list[int] = Field(default_factory=lambda: [7, 30, 365], min_length=1, max_length=12)

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, v):
        if not v or any(d not in range(7) for d in v):
            raise ValueError("weekdays are 0 (Monday) to 6 (Sunday), at least one")
        return sorted(set(v))

    @field_validator("retention_days")
    @classmethod
    def _retention(cls, v):
        if any(d < 1 or d > 365 for d in v):
            raise ValueError("retention periods are 1 to 365 days")
        return sorted(set(v))
