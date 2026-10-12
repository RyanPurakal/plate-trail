"""Read stored runs back as JSON-ready dicts (GeoJSON for geometry)."""

import json

from sqlalchemy import Engine, text


def _iso(v):
    return v.isoformat() if v is not None else None


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, created_at, generator, weeks, start_date, seed, plate, plate_state, summary"
            " FROM runs ORDER BY id DESC LIMIT :n"), {"n": limit}).mappings().all()
    return [{**dict(r), "created_at": _iso(r["created_at"]), "start_date": _iso(r["start_date"])} for r in rows]


def get_run(engine: Engine, run_id: int) -> dict | None:
    with engine.connect() as conn:
        run = conn.execute(text(
            "SELECT id, created_at, generator, weeks, start_date, seed, plate, plate_state, match_config,"
            " noise_config, anchors, summary FROM runs WHERE id = :r"), {"r": run_id}).mappings().first()
        if run is None:
            return None
        trips = conn.execute(text(
            "SELECT id, seq, purpose, origin_key, origin_category, dest_key, dest_category, planned_depart, depart,"
            " arrive, length_m, duration_s, ST_AsGeoJSON(route_geom, 6) AS route FROM trips WHERE run_id = :r"
            " ORDER BY seq"), {"r": run_id}).mappings().all()
        passes = conn.execute(text(
            "SELECT p.id, t.seq AS trip_seq, p.pass_seq, p.camera_id, p.camera_label, p.time, p.event,"
            " p.travel_bearing_deg, p.road_name, p.captured, p.match_reason, p.noise_outcome"
            " FROM camera_passes p JOIN trips t ON t.id = p.trip_id WHERE p.run_id = :r ORDER BY p.pass_seq"),
            {"r": run_id}).mappings().all()
        reads = conn.execute(text(
            "SELECT r.id, r.read_seq, r.pass_id, r.camera_id, r.camera_label, r.time, r.plate_state, r.plate,"
            " r.misread, r.jitter_s, p.time AS true_time FROM reads r JOIN camera_passes p ON p.id = r.pass_id"
            " WHERE r.run_id = :r ORDER BY r.read_seq"), {"r": run_id}).mappings().all()
        outages = conn.execute(text(
            "SELECT camera_id, camera_label, start_time, end_time FROM camera_outages WHERE run_id = :r"
            " ORDER BY start_time"), {"r": run_id}).mappings().all()

    run = dict(run)
    run["created_at"], run["start_date"] = _iso(run["created_at"]), _iso(run["start_date"])
    trip_features = [
        {
            "type": "Feature",
            "geometry": json.loads(t["route"]),
            "properties": {k: (_iso(v) if k in ("planned_depart", "depart", "arrive") else v)
                           for k, v in t.items() if k != "route"},
        }
        for t in trips
    ]
    return {
        "run": run,
        "trips": {"type": "FeatureCollection", "features": trip_features},
        "passes": [{**dict(p), "time": _iso(p["time"])} for p in passes],
        "reads": [{**dict(r), "time": _iso(r["time"]), "true_time": _iso(r["true_time"])} for r in reads],
        "outages": [{**dict(o), "start_time": _iso(o["start_time"]), "end_time": _iso(o["end_time"])}
                    for o in outages],
    }
