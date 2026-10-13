"""Read stored runs back as JSON-ready dicts (GeoJSON for geometry)."""

import json
from datetime import datetime

from sqlalchemy import Engine, text

from platetrail.inference.naive import LogRead, naive_home_work


# A run is stale when cameras were reloaded after it was simulated (camera ids changed).
_STALE = ("(camera_snapshot IS NULL OR camera_snapshot IS DISTINCT FROM"
          " (SELECT max(loaded_at) FROM cameras)) AS stale")


def _iso(v):
    return v.isoformat() if v is not None else None


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, created_at, generator, weeks, start_date, seed, plate, plate_state, summary,"
            f" coalesce((scenario->>'extra_cameras')::int, 0) AS extra_cameras, {_STALE}"
            " FROM runs ORDER BY id DESC LIMIT :n"), {"n": limit}).mappings().all()
    return [{**dict(r), "created_at": _iso(r["created_at"]), "start_date": _iso(r["start_date"])} for r in rows]


def get_run(engine: Engine, run_id: int) -> dict | None:
    with engine.connect() as conn:
        run = conn.execute(text(
            "SELECT id, created_at, generator, weeks, start_date, seed, plate, plate_state, match_config,"
            f" noise_config, anchors, summary, scenario, {_STALE} FROM runs WHERE id = :r"), {"r": run_id}).mappings().first()
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
        coords = {r.source_id: (r.lon, r.lat) for r in conn.execute(text(
            "SELECT source_id, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM cameras"))}
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
    for c in (run.get("scenario") or {}).get("cameras", []):
        coords[c["label"]] = (c["lon"], c["lat"])
    return {
        "run": run,
        "naive_guess": naive_guess(reads, coords, run["anchors"]),
        "inference": inference(reads, coords, run["anchors"], f"{run['plate_state']} {run['plate']}"),
        "trips": {"type": "FeatureCollection", "features": trip_features},
        "passes": [{**dict(p), "time": _iso(p["time"])} for p in passes],
        "reads": [{**dict(r), "time": _iso(r["time"]), "true_time": _iso(r["true_time"])} for r in reads],
        "outages": [{**dict(o), "start_time": _iso(o["start_time"]), "end_time": _iso(o["end_time"])}
                    for o in outages],
    }


def naive_guess(reads, coords: dict, anchors: dict) -> dict:
    """Naive home/work baseline (platetrail.inference.naive) with distance error vs. the true anchors."""
    res = naive_home_work([LogRead(r["time"] if isinstance(r["time"], datetime) else datetime.fromisoformat(r["time"]),
                                   r["camera_label"]) for r in reads], coords)
    truth = {"home": anchors.get("home"), "work": anchors.get("work") or anchors.get("school")}

    def one(kind, g):
        if g is None:
            return None
        t = truth[kind]
        return {
            "camera_label": g.camera_label, "lon": g.lon, "lat": g.lat, "support_days": g.support_days,
            "error_m": round(g.error_m(t["lon"], t["lat"]), 1) if t else None,
            "is_top_camera": g.camera_label == res.top_camera,
            "truth": {"lon": t["lon"], "lat": t["lat"], "name": t.get("name"), "category": t.get("category")} if t else None,
        }

    return {
        "method": "naive baseline: most frequent first/last-read-of-day camera (home) and camera before the "
                  "day's longest gap (work); not the inference engine",
        "possible": res.possible,
        "days_used": res.days_used,
        "top_camera": res.top_camera,
        "home": one("home", res.home),
        "work": one("work", res.work),
    }


def list_populations(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, created_at, drivers, weeks, start_date, seed, generator, summary,"
            " coalesce((scenario->>'extra_cameras')::int, 0) AS extra_cameras,"
            " (camera_snapshot IS NULL OR camera_snapshot IS DISTINCT FROM (SELECT max(loaded_at) FROM cameras)) AS stale"
            " FROM populations ORDER BY id DESC")).mappings().all()
    return [{**dict(r), "created_at": _iso(r["created_at"]), "start_date": _iso(r["start_date"])} for r in rows]


def get_population(engine: Engine, population_id: int) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id, created_at, drivers, weeks, start_date, seed, generator, match_config, noise_config, scenario,"
            " summary FROM populations WHERE id = :p"), {"p": population_id}).mappings().first()
    if row is None:
        return None
    return {**dict(row), "created_at": _iso(row["created_at"]), "start_date": _iso(row["start_date"])}


def population_unicity_rows(engine: Engine, population_id: int, ps, resolution_min: int, sizes, samples: int):
    from platetrail.analysis.unicity import unicity_table
    from platetrail.cache import MISSING, get_cache
    from platetrail.population import load_population_reads

    key = f"unicity:{population_id}:{resolution_min}:{ps}:{sizes}:{samples}"
    cached = get_cache().get(key)
    if cached is not MISSING:
        return cached
    if get_population(engine, population_id) is None:
        return None
    reads, truth, _ = load_population_reads(engine, population_id)
    result = {
        "population_id": population_id,
        "method": "share of drivers whose recorded trace is the only one containing p random (camera, time-bin) points "
                  "of it (de Montjoye et al. 2013); identity = recorded plate, so misreads split traces",
        "rows": unicity_table(reads, truth, ps, resolution_min, sizes, samples),
    }
    get_cache().set(key, result, ttl_s=30 * 86400)
    return result


def inference(reads, coords: dict, anchors: dict, identity: str) -> dict:
    """Inference engine on the reads recorded under the run's plate (an analyst queries by plate, so
    misread reads are not part of this history), with errors against the true anchors."""
    from platetrail.inference.engine import EngineRead, infer

    mine = [EngineRead(r["time"] if isinstance(r["time"], datetime) else datetime.fromisoformat(r["time"]),
                       r["camera_label"], *coords[r["camera_label"]])
            for r in reads if f"{r['plate_state']} {r['plate']}" == identity and r["camera_label"] in coords]
    inf = infer(mine)
    truth = {"home": anchors.get("home"), "work": anchors.get("work") or anchors.get("school")}

    def anchor(a):
        if a is None:
            return None
        t = truth.get(a.kind)
        return {"lon": a.lon, "lat": a.lat, "radius_m": round(a.radius_m), "confidence": a.confidence,
                "support_days": a.support_days, "possible_days": a.possible_days, "nearest_camera": a.nearest_camera,
                "error_m": round(a.error_m(t["lon"], t["lat"]), 1) if t else None}

    return {
        "method": "inference engine: stays from read gaps clustered with HDBSCAN; regular passes; rarity anomalies",
        "reads_used": inf.reads,
        "home": anchor(inf.home),
        "work": anchor(inf.work),
        "regular": [{"camera_label": p.camera_label, "minute_of_day": p.minute_of_day, "days": p.days,
                     "weekdays": list(p.weekdays)} for p in inf.regular],
        "anomalies": [{"time": a.time.isoformat(), "camera_label": a.camera_label, "score": a.score}
                      for a in inf.anomalies],
        "conclusions": inf.conclusions,
    }


def population_policies(engine: Engine, population_id: int) -> dict | None:
    """Policy comparison (analysis.policies) on a stored population; cached."""
    from datetime import datetime, time, timedelta

    from platetrail.analysis.policies import compare
    from platetrail.cache import MISSING, get_cache
    from platetrail.population import load_population_reads

    key = f"policies:v1:{population_id}"
    cached = get_cache().get(key)
    if cached is not MISSING:
        return cached
    pop = get_population(engine, population_id)
    if pop is None:
        return None
    reads, truth, drivers = load_population_reads(engine, population_id)
    with engine.connect() as conn:
        coords = {r.source_id: (r.lon, r.lat) for r in conn.execute(text(
            "SELECT source_id, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM cameras"))}
    for c in (pop.get("scenario") or {}).get("cameras", []):
        coords[c["label"]] = (c["lon"], c["lat"])
    start = datetime.combine(datetime.fromisoformat(pop["start_date"]).date(), time())
    end = start + timedelta(weeks=pop["weeks"])
    anchors = {d["driver_idx"]: d["anchors"] for d in drivers}
    result = {"population_id": population_id, "drivers": pop["drivers"], "weeks": pop["weeks"],
              "extra_cameras": (pop.get("scenario") or {}).get("extra_cameras", 0),
              "rows": compare(reads, truth, anchors, coords, start, end, seed=pop["seed"])}
    get_cache().set(key, result, ttl_s=30 * 86400)
    return result
