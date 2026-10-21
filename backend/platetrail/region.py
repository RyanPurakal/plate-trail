"""Study-area (region) configuration.

A region is the set of municipalities the simulation covers: their labels,
OSM boundary relations, and the parent area (ISO 3166-2 code) used to look
them up by name in Overpass. Regions are JSON files; the bundled ones live in
platetrail/regions/. Select one with PLATETRAIL_REGION, either a bundled id
(e.g. "nj_edison_new_brunswick", the default) or a path to a JSON file.

Example file:

    {
      "id": "my_region",
      "name": "Example Town",
      "parent_iso3166_2": "US-NJ",
      "buffer_m": 2000,
      "towns": [{"label": "Example", "osm_name": "Example", "osm_relation": 123, "admin_level": 8}],
      "student_town": "Example",
      "student_home_share": 0.7,
      "scenario_town": "Example"
    }

student_town (optional) is the town with the main university campus: student
routines study there and live there with probability student_home_share.
Without it, students' homes and schools are drawn from the whole region.
scenario_town is where the density scenario adds synthetic sensors; it
defaults to the first town.
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REGIONS_DIR = Path(__file__).resolve().parent / "regions"
DEFAULT_REGION = "nj_edison_new_brunswick"


class RegionConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Town:
    label: str  # name used in the database and UI
    osm_name: str  # boundary relation's name tag in OSM
    osm_relation: int
    admin_level: int = 8


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    parent_iso3166_2: str
    towns: tuple[Town, ...]
    buffer_m: float = 2000.0
    student_town: str | None = None
    student_home_share: float = 0.7
    scenario_town: str | None = None  # resolved to the first town by parse_region

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(t.label for t in self.towns)

    def other_towns(self, label: str) -> tuple[str, ...]:
        return tuple(t for t in self.labels if t != label)

    @property
    def relations(self) -> dict[str, int]:
        """Town label -> OSM boundary relation id."""
        return {t.label: t.osm_relation for t in self.towns}


def parse_region(data: dict) -> Region:
    try:
        towns = tuple(
            Town(str(t["label"]), str(t["osm_name"]), int(t["osm_relation"]), int(t.get("admin_level", 8)))
            for t in data["towns"]
        )
        region = Region(
            id=str(data["id"]),
            name=str(data["name"]),
            parent_iso3166_2=str(data["parent_iso3166_2"]),
            towns=towns,
            buffer_m=float(data.get("buffer_m", 2000.0)),
            student_town=None if data.get("student_town") is None else str(data["student_town"]),
            student_home_share=float(data.get("student_home_share", 0.7)),
            scenario_town=str(data.get("scenario_town") or towns[0].label) if towns else None,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise RegionConfigError(f"invalid region config: {e!r}") from e
    if not towns:
        raise RegionConfigError(f"region {region.id!r} has no towns")
    labels = [t.label for t in towns]
    if len(set(labels)) != len(labels):
        raise RegionConfigError(f"region {region.id!r} has duplicate town labels")
    if region.buffer_m < 0:
        raise RegionConfigError(f"region {region.id!r} has a negative buffer_m")
    for key in ("student_town", "scenario_town"):
        value = getattr(region, key)
        if value is not None and value not in labels:
            raise RegionConfigError(f"region {region.id!r}: {key} {value!r} is not one of its towns")
    if not 0 <= region.student_home_share <= 1:
        raise RegionConfigError(f"region {region.id!r}: student_home_share must be in [0, 1]")
    return region


def load_region(ref: str | Path | None = None) -> Region:
    """Load a region by bundled id or file path; defaults to PLATETRAIL_REGION, then DEFAULT_REGION."""
    ref = ref or os.environ.get("PLATETRAIL_REGION") or DEFAULT_REGION
    path = Path(ref)
    if path.suffix != ".json":
        path = REGIONS_DIR / f"{ref}.json"
    if not path.is_file():
        raise RegionConfigError(f"region config not found: {path}")
    return parse_region(json.loads(path.read_text()))


@lru_cache(maxsize=1)
def get_region() -> Region:
    return load_region()
