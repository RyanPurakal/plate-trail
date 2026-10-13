"""Cross-check OSM camera counts against published agency figures.

    python -m platetrail.etl.cross_check

Agency sources (etl/data/agency_counts.json) publish counts, not locations,
so this compares counts only. Individual cameras can't be matched. DeFlock
is not a separate source: its map stores cameras directly in OpenStreetMap,
so it is already covered by the OSM loader.
"""

import json
from importlib import resources

from sqlalchemy import Engine, text

from platetrail.db import get_engine


def load_agency_counts() -> list[dict]:
    return json.loads((resources.files("platetrail.etl") / "data" / "agency_counts.json").read_text())


def osm_counts(engine: Engine) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT town, count(*) total,"
            " count(*) FILTER (WHERE manufacturer = 'Flock Safety') flock,"
            " count(*) FILTER (WHERE manufacturer = 'Flock Safety' AND camera_kind = 'public_road') flock_public,"
            " count(*) FILTER (WHERE manufacturer = 'Flock Safety' AND camera_kind <> 'public_road') flock_lot_service"
            " FROM cameras GROUP BY town")).mappings().all()
    return {r["town"]: dict(r) for r in rows}


def report(engine: Engine | None = None) -> str:
    osm = osm_counts(engine or get_engine())
    lines = ["Camera count cross-check (counts only; agency sources publish no locations)", ""]
    lines.append(f"{'Town':<15}{'OSM total':>10}{'OSM Flock':>11}{'public rd':>11}{'lot/svc':>9}   Agency figure")
    for town in sorted(osm):
        o = osm[town]
        figs = [a for a in load_agency_counts() if a["town"] == town]
        first = True
        for a in figs or [None]:
            agency = (f"{a['figure']} = {a['value']} ({a['agency']}, as of {a['as_of'] or 'n/a'})" if a else "none found")
            prefix = (f"{town:<15}{o['total']:>10}{o['flock']:>11}{o['flock_public']:>11}{o['flock_lot_service']:>9}"
                      if first else " " * 56)
            lines.append(f"{prefix}   {agency}")
            first = False
    lines += ["", "Notes:"]
    for a in load_agency_counts():
        lines.append(f"  - {a['town']} / {a['agency']}: {a['source']}. {a['notes']}")
    lines.append("  - DeFlock: stores cameras in OpenStreetMap, so it is the same data as the OSM loader.")
    return "\n".join(lines)


def main() -> None:
    print(report())


if __name__ == "__main__":
    main()
