"""Export stored cameras as GeoJSON for eyeballing in geojson.io or QGIS.

    python -m platetrail.etl.export_geojson [--out PATH] [--ray-m 30]

Each camera is a Point with its attributes. Each direction it faces also gets
a short LineString ray (kind="direction_ray") so facing is visible on maps
that can't rotate point symbols.
"""

import argparse
import json
import math
from pathlib import Path

from sqlalchemy import Engine, text

from platetrail.config import get_settings
from platetrail.db import get_engine

EARTH_RADIUS_M = 6_371_008.8


def destination(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """Point dist_m from (lat, lon) along bearing (great-circle)."""
    lat1, lon1, brg = math.radians(lat), math.radians(lon), math.radians(bearing_deg)
    d = dist_m / EARTH_RADIUS_M
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))
    lon2 = lon1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def cameras_feature_collection(engine: Engine, ray_m: float = 30.0) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.id, source, source_id, town, ST_Y(geom) AS lat, ST_X(geom) AS lon, directions_deg,"
                " has_direction, direction_key, direction_raw, manufacturer, sources, camera_kind,"
                " snap_ambiguous, direction_ambiguous, alt_directions_deg,"
                " l.lot_osm_id, l.lot_kind, l.lot_name, l.watched_way_osm_id, l.facings, l.alt_facings"
                " FROM cameras c LEFT JOIN camera_lots l ON l.camera_id = c.id ORDER BY c.id"
            )
        ).mappings()
        features = []
        for r in rows:
            props = {
                "kind": "camera",
                "camera_id": r["id"],
                "osm_id": r["source_id"] if r["source"] == "osm" else None,
                "source": r["source"],
                "sources": r["sources"],
                "town": r["town"],
                "has_direction": r["has_direction"],
                "directions_deg": r["directions_deg"],
                "direction_key": r["direction_key"],
                "direction_raw": r["direction_raw"],
                "manufacturer": r["manufacturer"],
                "camera_kind": r["camera_kind"],
                "snap_ambiguous": r["snap_ambiguous"],
                "direction_ambiguous": r["direction_ambiguous"],
                "alt_directions_deg": r["alt_directions_deg"],
                "lot_osm_id": r["lot_osm_id"],
                "lot_kind": r["lot_kind"],
                "lot_name": r["lot_name"],
                "watched_way_osm_id": r["watched_way_osm_id"],
                "lot_facings": r["facings"],
                "lot_alt_facings": r["alt_facings"],
                # geojson.io styling: red public road, blue private lot, orange service road, grey undirected
                "marker-color": "#7f8c8d" if not r["has_direction"]
                else {"private_lot": "#2471a3", "service_road": "#d68910"}.get(r["camera_kind"], "#c0392b"),
            }
            features.append(
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}, "properties": props}
            )
            for brg in r["directions_deg"] or []:
                lat2, lon2 = destination(r["lat"], r["lon"], brg, ray_m)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[r["lon"], r["lat"]], [lon2, lat2]]},
                        "properties": {
                            "kind": "direction_ray",
                            "camera_id": r["id"],
                            "bearing_deg": brg,
                            "stroke": "#c0392b",
                            "stroke-width": 3,
                        },
                    }
                )
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=get_settings().data_dir / "exports" / "cameras.geojson")
    parser.add_argument("--ray-m", type=float, default=30.0, help="length of direction rays in meters")
    args = parser.parse_args()
    fc = cameras_feature_collection(get_engine(), args.ray_m)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fc, indent=1))
    n_cams = sum(1 for f in fc["features"] if f["properties"]["kind"] == "camera")
    print(f"Wrote {n_cams} cameras ({len(fc['features']) - n_cams} direction rays) to {args.out}")


if __name__ == "__main__":
    main()
