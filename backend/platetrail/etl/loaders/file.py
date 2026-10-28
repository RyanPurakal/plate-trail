"""Fixed sensors from a local GeoJSON or CSV file.

Lets any sensor network be used without OpenStreetMap: a list published by
a planning office, a survey, or a hand-made hypothetical placement.

GeoJSON: a FeatureCollection of Point features. Properties (all optional):
  id         stable id within the file (default: feature index)
  town       a town label of the region; when missing it is the region's
             only town, or the box town (a town given as a bbox) the point
             falls in. Required for a point outside every box town.
  direction  facing bearing(s), same formats as the OSM tag: "90",
             "90;270", "NE", "45-135"; missing = no usable direction
Other properties are kept as tags.

CSV: a header row with lon and lat columns, plus the same optional id, town
and direction columns. Other columns are kept as tags.
"""

import csv
import json
from pathlib import Path
from typing import Any

from platetrail.etl.directions import parse_direction
from platetrail.etl.loaders.base import CameraLoader, CameraRecord
from platetrail.region import Region, get_region

RESERVED = ("id", "town", "direction", "lon", "lat")


class SensorFileError(ValueError):
    pass


def _feature_rows(data: dict) -> list[dict[str, Any]]:
    if data.get("type") != "FeatureCollection":
        raise SensorFileError("GeoJSON sensor file must be a FeatureCollection")
    rows = []
    for i, feat in enumerate(data.get("features", [])):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            raise SensorFileError(f"feature {i}: only Point geometries are supported")
        lon, lat = geom["coordinates"][:2]
        props = dict(feat.get("properties") or {})
        props.setdefault("id", feat.get("id"))
        rows.append({**props, "lon": lon, "lat": lat})
    return rows


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing = {"lon", "lat"} - set(reader.fieldnames or ())
        if missing:
            raise SensorFileError(f"{path.name}: missing column(s) {sorted(missing)}")
        return [{k: v for k, v in row.items() if v not in (None, "")} for row in reader]


def read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in (".geojson", ".json"):
        return _feature_rows(json.loads(path.read_text()))
    if suffix == ".csv":
        return _csv_rows(path)
    raise SensorFileError(f"unsupported sensor file type {suffix!r} (use .geojson, .json or .csv)")


def town_for_point(region: Region, lon: float, lat: float) -> str | None:
    """The town a point belongs to when a file row gives none, or None.

    A one-town region's only town; otherwise the one box town containing the
    point (edges count). Relation towns have no boundary without OSM, so a
    point outside every box, or inside more than one, gets no town.
    """
    if len(region.labels) == 1:
        return region.labels[0]
    hits = [label for label, (w, s, e, n) in region.bboxes.items() if w <= lon <= e and s <= lat <= n]
    return hits[0] if len(hits) == 1 else None


def parse_rows(rows: list[dict[str, Any]], region: Region, source: str) -> list[CameraRecord]:
    records = []
    for i, row in enumerate(rows):
        try:
            lon, lat = float(row["lon"]), float(row["lat"])
        except (KeyError, TypeError, ValueError) as e:
            raise SensorFileError(f"row {i}: invalid lon/lat") from e
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise SensorFileError(f"row {i}: lon/lat out of range ({lon}, {lat})")
        town = row.get("town") or town_for_point(region, lon, lat)
        if town is None:
            raise SensorFileError(
                f"row {i}: no town given and ({lon}, {lat}) is not inside exactly one town box; add a town"
            )
        if town not in region.labels:
            raise SensorFileError(f"row {i}: town {town!r} is not one of the region's towns {list(region.labels)}")
        raw = row.get("direction")
        raw = None if raw is None else str(raw)
        sid = row.get("id")
        records.append(
            CameraRecord(
                source=source,
                source_id=str(i if sid in (None, "") else sid),
                lat=lat,
                lon=lon,
                town=town,
                directions_deg=parse_direction(raw),
                direction_raw=raw,
                direction_key="direction" if raw is not None else None,
                tags={k: v for k, v in row.items() if k not in RESERVED},
            )
        )
    return records


class FileCameraLoader(CameraLoader):
    def __init__(self, path: Path, region: Region | None = None, source: str = "file"):
        self.path = Path(path)
        self.region = region or get_region()
        self.source = source

    def load(self, refresh: bool = False) -> list[CameraRecord]:
        # A local file has no remote copy, so refresh has nothing to refetch.
        if not self.path.is_file():
            raise SensorFileError(f"sensor file not found: {self.path}")
        return parse_rows(read_rows(self.path), self.region, self.source)
