"""Loader interface for camera sources.

Each source (OSM via Overpass now; DeFlock exports and agency transparency
portals later) implements CameraLoader. Loaders only fetch and normalize;
cross-source deduplication happens afterwards in etl.dedupe, so adding a
source means adding one loader class and registering it in run_etl.
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
