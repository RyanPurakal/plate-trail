"""Camera ETL: load all sources, dedupe, replace the cameras table, print a summary.

    python -m platetrail.etl.run_etl            # uses cached raw responses
    python -m platetrail.etl.run_etl --refresh  # refetch from sources
"""

import argparse
import json
from collections import Counter

from sqlalchemy import Engine, text

from platetrail.config import get_settings
from platetrail.db import apply_migrations, get_engine
from platetrail.etl.cache import RawCache
from platetrail.etl.directions import conflicting_direction_tags
from platetrail.etl.dedupe import DedupeStats, MergedCamera, dedupe
from platetrail.etl.loaders.base import CameraLoader, CameraRecord
from platetrail.etl.loaders.file import FileCameraLoader
from platetrail.etl.loaders.overpass import OverpassLoader
from platetrail.region import Region, get_region


def default_loaders(region: Region | None = None) -> list[CameraLoader]:
    """One loader per camera source of the region. Order = source priority."""
    region = region or get_region()
    data_dir = get_settings().data_dir
    loaders: list[CameraLoader] = []
    for src in region.camera_sources:
        if src.type == "osm":
            loaders.append(OverpassLoader(RawCache(data_dir / "raw" / "overpass"), region=region))
        else:
            loaders.append(FileCameraLoader(src.path, region=region, source=src.source or "file"))
    return loaders


def store(engine: Engine, cameras: list[MergedCamera]) -> None:
    """Replace all cameras. The ETL is the source of truth for this table."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE cameras RESTART IDENTITY CASCADE"))
        for cam in cameras:
            p = cam.primary
            camera_id = conn.execute(
                text(
                    "INSERT INTO cameras (geom, town, directions_deg, has_direction, direction_raw,"
                    " direction_key, alt_directions_deg, direction_ambiguous, manufacturer, source, source_id,"
                    " sources, tags)"
                    " VALUES (ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :town, :dirs, :has_dir, :raw,"
                    " :dir_key, :alt_dirs, :ambiguous, :manufacturer, :source, :source_id, :sources,"
                    " CAST(:tags AS jsonb)) RETURNING id"
                ),
                {
                    "lon": p.lon,
                    "lat": p.lat,
                    "town": p.town,
                    "dirs": cam.directions_deg,
                    "has_dir": bool(cam.directions_deg),
                    "raw": cam.direction_raw,
                    "dir_key": cam.direction_key,
                    "alt_dirs": cam.alt_directions_deg,
                    "ambiguous": cam.alt_directions_deg is not None,
                    "manufacturer": cam.manufacturer,
                    "source": p.source,
                    "source_id": p.source_id,
                    "sources": cam.sources,
                    "tags": json.dumps(p.tags),
                },
            ).scalar_one()
            for m in cam.members:
                conn.execute(
                    text(
                        "INSERT INTO camera_source_records (camera_id, source, source_id, geom,"
                        " directions_deg, direction_raw, direction_key, tags)"
                        " VALUES (:cid, :source, :source_id, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),"
                        " :dirs, :raw, :dir_key, CAST(:tags AS jsonb))"
                    ),
                    {
                        "cid": camera_id,
                        "source": m.source,
                        "source_id": m.source_id,
                        "lon": m.lon,
                        "lat": m.lat,
                        "dirs": m.directions_deg,
                        "raw": m.direction_raw,
                        "dir_key": m.direction_key,
                        "tags": json.dumps(m.tags),
                    },
                )


def summarize(records: list[CameraRecord], cameras: list[MergedCamera], stats: DedupeStats) -> str:
    lines = ["Camera ETL summary", "=================="]
    by_source = Counter(r.source for r in records)
    lines.append("Raw records by source: " + ", ".join(f"{s}={n}" for s, n in sorted(by_source.items())))
    lines.append("")
    lines.append(f"{'Town':<16}{'cameras':>8}{'directed':>10}{'undirected':>12}")
    towns = sorted({c.primary.town for c in cameras} | {r.town for r in records})
    for town in towns:
        cams = [c for c in cameras if c.primary.town == town]
        directed = sum(1 for c in cams if c.directions_deg)
        lines.append(f"{town:<16}{len(cams):>8}{directed:>10}{len(cams) - directed:>12}")
    total_dir = sum(1 for c in cameras if c.directions_deg)
    lines.append(f"{'TOTAL':<16}{len(cameras):>8}{total_dir:>10}{len(cameras) - total_dir:>12}")
    lines.append("")
    keys = Counter(c.direction_key or "(none)" for c in cameras)
    lines.append("Direction value taken from: " + ", ".join(f"{k}={n}" for k, n in sorted(keys.items())))
    present = Counter(
        "+".join(k for k in ("direction", "camera:direction") if k in r.tags) or "neither" for r in records
    )
    lines.append("Direction tags present: " + ", ".join(f"{k}={n}" for k, n in sorted(present.items())))
    no_mfr = sum(1 for c in cameras if not c.manufacturer)
    lines.append(f"Cameras without manufacturer tag: {no_mfr}")
    unparsed = sorted({r.direction_raw for r in records if r.direction_raw and not r.has_direction})
    lines.append(f"Direction tags present but unparseable: {len(unparsed)} distinct value(s) {unparsed or ''}")
    conflicts = [(r.key, c) for r in records if (c := conflicting_direction_tags(r.tags))]
    lines.append(f"Conflicting direction tags (first listed key used): {len(conflicts)}")
    for key, tags in conflicts:
        lines.append(f"  {key}: " + ", ".join(f"{k}={v}" for k, v in tags.items()))
    lines.append(
        f"Dedupe: {stats.input_records} in -> {stats.output_cameras} out; "
        f"duplicate ids dropped={len(stats.duplicate_ids_dropped)}, "
        f"merged within source={len(stats.merged_within_source)}, "
        f"merged across sources={len(stats.merged_cross_source)}"
    )
    for kept, gone in stats.merged_within_source + stats.merged_cross_source:
        lines.append(f"  merged {gone} into {kept}")
    for key in stats.duplicate_ids_dropped:
        lines.append(f"  dropped duplicate id {key}")
    return "\n".join(lines)


def run(refresh: bool = False, loaders: list[CameraLoader] | None = None, engine: Engine | None = None) -> str:
    loaders = loaders if loaders is not None else default_loaders()
    records: list[CameraRecord] = []
    for loader in loaders:
        records.extend(loader.load(refresh=refresh))
    cameras, stats = dedupe(records, source_priority=tuple(l.source for l in loaders))
    engine = engine or get_engine()
    apply_migrations(engine)
    store(engine, cameras)
    return summarize(records, cameras, stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="ignore the raw cache and refetch")
    args = parser.parse_args()
    print(run(refresh=args.refresh))


if __name__ == "__main__":
    main()
