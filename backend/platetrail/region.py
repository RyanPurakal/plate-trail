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
      "scenario_town": "Example",
      "camera_sources": [{"type": "file", "path": "example_sensors.geojson"}],
      "map": {"center": [-74.4, 40.5], "zoom": 12}
    }

student_town (optional) is the town with the main university campus: student
routines study there and live there with probability student_home_share.
Without it, students' homes and schools are drawn from the whole region.
scenario_town is where the density scenario adds synthetic sensors; it
defaults to the first town.

camera_sources (optional) lists where the fixed sensors come from, in source
priority order for deduplication: {"type": "osm"} queries OpenStreetMap per
town; {"type": "file", "path": ..., "source": ...} reads a GeoJSON or CSV
file (see platetrail.etl.loaders.file), with a relative path resolved against
the region file's folder. The default is [{"type": "osm"}].

map (optional) sets the frontend's initial view, served by GET /region:
"center" as [lon, lat] with "zoom", and/or "bounds" as [west, south, east,
north] (fitted on load, taking precedence over center/zoom). Without it the
frontend falls back to its own default view.
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
class CameraSource:
    type: str  # "osm" or "file"
    path: Path | None = None  # file sources only
    source: str | None = None  # record source name for file sources; defaults to the type


SOURCE_TYPES = ("osm", "file")


@dataclass(frozen=True)
class MapDefaults:
    center: tuple[float, float] | None = None  # (lon, lat)
    zoom: float | None = None
    bounds: tuple[float, float, float, float] | None = None  # (west, south, east, north)

    def as_dict(self) -> dict:
        return {
            "center": list(self.center) if self.center else None,
            "zoom": self.zoom,
            "bounds": list(self.bounds) if self.bounds else None,
        }


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
    camera_sources: tuple[CameraSource, ...] = (CameraSource("osm"),)
    map: MapDefaults = MapDefaults()

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(t.label for t in self.towns)

    def other_towns(self, label: str) -> tuple[str, ...]:
        return tuple(t for t in self.labels if t != label)

    @property
    def relations(self) -> dict[str, int]:
        """Town label -> OSM boundary relation id."""
        return {t.label: t.osm_relation for t in self.towns}


def _parse_sources(raw: list | None, base_dir: Path | None) -> tuple[CameraSource, ...]:
    if raw is None:
        return (CameraSource("osm"),)
    sources = []
    for s in raw:
        kind = str(s["type"])
        if kind not in SOURCE_TYPES:
            raise ValueError(f"unknown camera source type {kind!r}")
        path = None
        if kind == "osm" and s.get("source") is not None:
            raise ValueError("an osm camera source cannot be renamed")
        if kind == "file":
            path = Path(s["path"])
            if not path.is_absolute() and base_dir is not None:
                path = base_dir / path
        sources.append(CameraSource(kind, path, None if s.get("source") is None else str(s["source"])))
    return tuple(sources)


def _valid_lonlat(lon: float, lat: float) -> bool:
    return -180 <= lon <= 180 and -90 <= lat <= 90


def _parse_map(raw: dict | None) -> MapDefaults:
    if raw is None:
        return MapDefaults()
    center, zoom, bounds = raw.get("center"), raw.get("zoom"), raw.get("bounds")
    if center is not None and len(center) != 2:
        raise ValueError("map.center must be [lon, lat]")
    if bounds is not None and len(bounds) != 4:
        raise ValueError("map.bounds must be [west, south, east, north]")
    if (center is None) != (zoom is None):
        raise ValueError("map.center and map.zoom go together")
    view = MapDefaults(
        center=None if center is None else (float(center[0]), float(center[1])),
        zoom=None if zoom is None else float(zoom),
        bounds=None if bounds is None else tuple(float(v) for v in bounds),
    )
    if view.center is not None and not _valid_lonlat(*view.center):
        raise ValueError("map.center is out of range")
    if view.zoom is not None and not 0 <= view.zoom <= 22:
        raise ValueError("map.zoom must be in [0, 22]")
    if view.bounds is not None:
        w, s, e, n = view.bounds
        if not (_valid_lonlat(w, s) and _valid_lonlat(e, n) and w < e and s < n):
            raise ValueError("map.bounds needs west < east and south < north, in range")
    return view


def parse_region(data: dict, base_dir: Path | None = None) -> Region:
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
            camera_sources=_parse_sources(data.get("camera_sources"), base_dir),
            map=_parse_map(data.get("map")),
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
    if not region.camera_sources:
        raise RegionConfigError(f"region {region.id!r}: camera_sources is empty")
    names = [s.source or s.type for s in region.camera_sources]
    if len(set(names)) != len(names):
        raise RegionConfigError(f"region {region.id!r}: camera source names must be unique (set 'source')")
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
    return parse_region(json.loads(path.read_text()), base_dir=path.parent)


@lru_cache(maxsize=1)
def get_region() -> Region:
    return load_region()
