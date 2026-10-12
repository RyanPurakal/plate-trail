# Architecture

The full planned system from the proposal. **Solid** boxes and arrows are
built in this slice; **dashed** ones are planned. Today `POST /simulate`
runs the simulation in-process (`LocalRunner`) and writes straight to
PostGIS. The Celery queue, workers and Redis cache will slot in behind the
`SimulationRunner` interface without changing the API.

```mermaid
flowchart LR
    %% ---------- sources ----------
    subgraph sources["Data sources"]
        OSM["OpenStreetMap<br/>Overpass API<br/>(ALPR cameras, places, lots)"]
        OSMNX["OpenStreetMap road network<br/>(via OSMnx)"]
        DEFLOCK["DeFlock export"]:::planned
        AGENCY["Agency transparency portals"]:::planned
        NHTS["NHTS trip diaries"]:::planned
    end

    %% ---------- ETL ----------
    subgraph etl["ETL"]
        CAMETL["Camera ETL<br/>loaders + dedupe<br/>(cached raw responses)"]
        ROADS["Road graph + snapping<br/>lot / service-road cameras"]
        PLACES["Places + towns<br/>anchor candidates"]
        NHTSETL["NHTS processing"]:::planned
    end

    DB[("PostGIS<br/>cameras · road_edges · camera_edges<br/>camera_lots · places · runs · trips<br/>camera_passes · reads · camera_outages")]

    %% ---------- app ----------
    FE["Frontend<br/>Next.js + MapLibre"]
    API["FastAPI<br/>/cameras · /simulate · /runs"]
    LOCAL["LocalRunner (in-process)<br/>routines → routing → matching<br/>→ sensor noise → store"]
    REDIS[("Redis<br/>graph / coverage / run cache")]:::planned
    QUEUE["Celery queue<br/>(progress reporting)"]:::planned
    SIMW["Simulation worker<br/>routines, routing, camera matching,<br/>sensor noise, read logs"]:::planned
    INFW["Inference + unicity worker<br/>HDBSCAN anchors, schedule, anomalies,<br/>population unicity, policy comparison"]:::planned
    RESULTS[("Results store<br/>inference, unicity, policy results")]:::planned

    OSM --> CAMETL
    OSM --> PLACES
    OSM --> ROADS
    OSMNX --> ROADS
    DEFLOCK -.-> CAMETL
    AGENCY -.-> CAMETL
    NHTS -.-> NHTSETL
    CAMETL --> DB
    ROADS --> DB
    PLACES --> DB
    NHTSETL -.-> DB

    FE --> API
    API --> LOCAL
    LOCAL --> DB
    API --> DB

    API -.-> REDIS
    REDIS -.-> QUEUE
    API -.-> QUEUE
    QUEUE -.-> SIMW
    SIMW -.-> INFW
    SIMW -.-> DB
    INFW -.-> RESULTS
    RESULTS -.-> API

    classDef planned stroke-dasharray: 6 4,fill:#f6f6f6,color:#555;
```

## What runs where

| Component | Module | Status |
|---|---|---|
| Camera ETL (Overpass loader, dedupe, direction parsing) | `backend/platetrail/etl/` | Built |
| Road graph, camera snapping, lot / service-road classification | `backend/platetrail/roads/` | Built |
| Places, home sampling, routine templates (NHTS stub) | `backend/platetrail/routines/` | Built (NHTS planned) |
| Routing, matcher, noise, driver simulation, runner | `backend/platetrail/sim/` | Built |
| API | `backend/platetrail/api/` | Built |
| Schema (ordered SQL migrations) | `backend/platetrail/sql/` | Built |
| Frontend | `frontend/` | In progress |
| Celery queue, Redis cache, workers, results store | — | Planned |

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
