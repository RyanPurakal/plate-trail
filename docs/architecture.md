# Architecture

Plate Trail is a location-privacy check-up built on the example study's pipeline. The check-up endpoints
(`/area`, `/geocode`, `/route/check`, `/route/history`) reuse the camera loaders, snapping, routing, matcher, noise
model and inference engine below. Saved routes, saved areas and last-look snapshots stay in the browser; route checks
are compute-only and write nothing to PostGIS or Redis.

The full system from the proposal (the example study) is built. `POST /jobs/simulate` and `POST /jobs/population`
run on the Celery worker through Redis, with progress reporting and route/run caching. Unicity and policy analyses run
on request and are cached in Redis; populations are stored in PostGIS.

```mermaid
flowchart LR
    %% ---------- sources ----------
    subgraph sources["Data sources"]
        OSM["OpenStreetMap<br/>Overpass API<br/>(ALPR cameras, places, lots)"]
        OSMNX["OpenStreetMap road network<br/>(via OSMnx)"]
        DEFLOCK["DeFlock<br/>(= OSM data)"]
        AGENCY["Agency transparency portals<br/>(counts only)"]
        NHTS["NHTS 2022 trip diaries"]
    end

    %% ---------- ETL ----------
    subgraph etl["ETL"]
        CAMETL["Camera ETL<br/>loaders + dedupe<br/>(cached raw responses)"]
        ROADS["Road graph + snapping<br/>lot / service-road cameras"]
        PLACES["Places + towns<br/>anchor candidates"]
        NHTSETL["NHTS diaries<br/>(routines.nhts_data)"]
    end

    DB[("PostGIS<br/>cameras · road_edges · camera_edges<br/>camera_lots · places · runs · trips<br/>camera_passes · reads · camera_outages<br/>populations · population_drivers · population_reads")]

    %% ---------- app ----------
    FE["Frontend<br/>Next.js + MapLibre"]
    API["FastAPI<br/>/region · /area · /geocode · /cameras · /simulate · /runs · /jobs<br/>/populations · /yourweek · /route/check · /route/history"]
    LOCAL["LocalRunner (in-process)<br/>routines → routing → matching<br/>→ sensor noise → store"]
    REDIS[("Redis<br/>broker · route cache · run cache<br/>unicity + policy results")]
    QUEUE["Celery queue<br/>(progress reporting)"]
    SIMW["Simulation worker<br/>routines, routing, camera matching,<br/>sensor noise, read logs"]
    INFW["Inference + unicity worker<br/>HDBSCAN anchors, schedule, anomalies,<br/>population unicity, policy comparison"]
    RESULTS[("Results store<br/>population tables (PostGIS)<br/>cached analyses (Redis)")]
    TIMELINE["Timeline importer (CLI, local only)<br/>realdata: Google Timeline → trips → scores"]

    OSM --> CAMETL
    OSM --> PLACES
    OSM --> ROADS
    OSMNX --> ROADS
    DEFLOCK --> CAMETL
    AGENCY --> CAMETL
    NHTS --> NHTSETL
    CAMETL --> DB
    ROADS --> DB
    PLACES --> DB
    NHTSETL --> SIMW

    FE --> API
    API --> LOCAL
    LOCAL --> DB
    API --> DB

    API --> REDIS
    REDIS --> QUEUE
    API --> QUEUE
    QUEUE --> SIMW
    SIMW --> INFW
    SIMW --> DB
    INFW --> RESULTS
    RESULTS --> API
    TIMELINE --> SIMW
```

## What runs where

| Component | Module | Status |
|---|---|---|
| Camera ETL (Overpass loader, dedupe, direction parsing) | `backend/platetrail/etl/` | Built |
| Road graph, camera snapping, lot / service-road classification | `backend/platetrail/roads/` | Built |
| Places, home sampling, NHTS and template routine generators | `backend/platetrail/routines/` | Built |
| Routing, matcher, noise, driver simulation, runner | `backend/platetrail/sim/` | Built |
| API | `backend/platetrail/api/` | Built |
| Schema (ordered SQL migrations) | `backend/platetrail/sql/` | Built |
| Frontend | `frontend/` | Built |
| Celery app, tasks, jobs + run cache | `backend/platetrail/worker.py`, `jobs.py`, `cache.py` | Built |
| Population runs + unicity | `backend/platetrail/population.py`, `analysis/unicity.py` | Built |
| Inference engine (stays, HDBSCAN anchors, regular passes, anomalies) | `backend/platetrail/inference/engine.py` | Built |
| Policy comparison | `backend/platetrail/analysis/policies.py` | Built |
| "Your week" (session-only, nothing stored) | `backend/platetrail/yourweek.py` | Built |
| Route check for "My routes" (compute-only, nothing stored) | `backend/platetrail/routecheck.py` | Built (study region's roads) |
| Route networks for any area (roads + sensors around one route, memory only) | `backend/platetrail/routearea.py` | Built |
| Read history for a route (simulated schedule + inference, compute-only) | `backend/platetrail/routehistory.py` | Built |
| Real-data validation (Google Timeline importer, local only) | `backend/platetrail/realdata/` | Built; not yet run on a real file |

## Data flow for one simulation

1. `POST /simulate` validates the request (template, weeks, seed, match and
   noise settings).
2. The routine generator plans the driver's trips. Anchors are sampled with
   no reference to camera locations.
3. Each trip is routed (shortest free-flow time; service roads penalized for
   through traffic). Every camera on the driven edges, and every lot camera
   at the entrance used, is a *pass*. The matcher marks it captured or not
   (direction, capture convention, tolerance).
4. Sensor noise turns captured passes into reads: missed reads, look-alike
   misreads, per-camera downtime, timestamp jitter. Every read links to its
   pass.
5. The run, trips, passes, reads and outages are stored in one transaction,
   and `GET /runs/{id}` serves them back.
