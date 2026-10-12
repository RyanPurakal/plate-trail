"""Request models for the API (responses are plain JSON / GeoJSON dicts)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from platetrail.sim.matcher import MatchConfig
from platetrail.sim.noise import NoiseConfig
from platetrail.sim.runner import SimulationRequest

MAX_WEEKS = 8  # keeps a synchronous request to a few seconds


class MatchSettings(BaseModel):
    tolerance_deg: float = Field(45.0, ge=0, le=180)
    facing: Literal["rear_plate", "oncoming"] = "rear_plate"
    undirected: Literal["best", "worst"] = "best"
    ambiguous_direction: Literal["primary", "alternate"] = "primary"
    lot_entrance: Literal["access_road", "nearest", "all"] = "access_road"


class NoiseSettings(BaseModel):
    p_miss: float = Field(0.05, ge=0, le=1)
    p_char_misread: float = Field(0.01, ge=0, le=1)
    downtime_rate_per_week: float = Field(0.25, ge=0)
    downtime_mean_hours: float = Field(12.0, ge=0)
    jitter_sd_s: float = Field(2.0, ge=0)


class SimulateRequest(BaseModel):
    template: Literal["commuter", "student", "shift_worker"] | None = None
    weeks: int = Field(1, ge=1, le=MAX_WEEKS)
    start: date = date(2026, 10, 12)
    seed: int = Field(0, ge=0)
    zero_noise: bool = False
    match: MatchSettings = MatchSettings()
    noise: NoiseSettings = NoiseSettings()

    @field_validator("start")
    @classmethod
    def _monday(cls, v: date) -> date:
        if v.weekday() != 0:
            raise ValueError("start must be a Monday")
        return v

    def to_request(self) -> SimulationRequest:
        noise = (NoiseConfig.noiseless(self.seed) if self.zero_noise
                 else NoiseConfig(seed=self.seed, **self.noise.model_dump()))
        return SimulationRequest(self.template, self.weeks, self.start, self.seed,
                                 MatchConfig(**self.match.model_dump()), noise)
