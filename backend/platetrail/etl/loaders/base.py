"""Loader interface for camera sources.

Each source (OSM via Overpass, or a local GeoJSON/CSV file) implements
CameraLoader. Loaders only fetch and normalize; cross-source deduplication
happens afterwards in etl.dedupe. A region's camera_sources choose which
loaders run_etl uses, so adding a source type means one loader class and one
branch in run_etl.default_loaders.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CameraRecord:
    source: str  # e.g. "osm"
    source_id: str  # stable id within the source, e.g. "node/123"
    lat: float
    lon: float
    town: str
    directions_deg: list[float] | None  # None = no usable direction
    direction_raw: str | None  # original tag value, kept for auditing
    direction_key: str | None = None  # tag the value came from, e.g. "direction"
    # Reading from a disagreeing lower-priority tag; set only for ambiguous cameras.
    alt_directions_deg: list[float] | None = None
    tags: dict[str, Any] = field(default_factory=dict)

    @property
    def has_direction(self) -> bool:
        return bool(self.directions_deg)

    @property
    def manufacturer(self) -> str | None:
        return self.tags.get("manufacturer")

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"


class CameraLoader(ABC):
    source: str

    @abstractmethod
    def load(self, refresh: bool = False) -> list[CameraRecord]:
        """Return normalized records. Use the on-disk cache unless refresh=True."""
