# Plate Trail

> **Draft of the finished README.** It shows what the README should look like
> once every component in the proposal is built. Sections for unbuilt parts
> describe the planned design. Results not produced yet are marked
> **[TBD]**: no numbers are invented. Results that already exist are marked
> *(current slice)* and will be rerun on the final system.

**What license plate cameras can reconstruct about your week.**

Plate Trail measures what a history of automated license plate reader (ALPR)
reads can reveal about a driver. It uses real camera locations in Edison and
New Brunswick, NJ, realistic travel behaviour from the National Household
Travel Survey (NHTS), and a population-scale analysis of how quickly drivers
become uniquely identifiable. It then ranks the policies an agency could
adopt by how much each one reduces what the data reveals.

No real plate reads are used. Every driver is synthetic, and every plate
carries the made-up state code `ZZ`.

| What the cameras saw | What actually happened |
|---|---|
| ![Read log as recorded](docs/figures/demo_run8_saw.jpg) | ![Ground truth](docs/figures/demo_run8_happened.jpg) |

---

## Why this exists

ALPR networks are expanding fast; Edison recently approved 92 more Flock
cameras. The public debate is stuck between two positions:
- "the cameras only log a plate at a few fixed points";
- "enough reads reveal a person's whole routine".

Neither side usually backs its claim with real camera positions and measured
numbers. Courts increasingly ask how complete a picture location data paints
(the "mosaic" argument in *Carpenter v. United States*). Plate Trail answers
that question with measurements for this specific camera network, and shows
how the answer changes with density, retention and policy.

## What it does

1. **Builds the camera network.** It merges OpenStreetMap, DeFlock and agency
   transparency portal data, deduplicates and cross-checks the sources, and
   snaps each camera to the road it watches, with its facing direction.
2. **Simulates realistic weeks.** Weekly routines come from NHTS trip diaries
   and are placed at real Edison / New Brunswick places, then routed on the
   real road network.
3. **Decides which cameras see each trip.** Matching is direction-aware, with
   a sensor model for missed reads, misreads, camera downtime and timestamp
   jitter.
4. **Infers what an analyst could learn** from the read log alone: likely home
   and work or school areas, the recurring weekly schedule, and anomalous
   trips. These are shown as plain-language conclusions with confidence levels.
5. **Measures identifiability across a population.** For about 1,000 drivers
   it computes **unicity**: the share of drivers uniquely matched by *p* of
   their own reads (following *Unique in the Crowd*, de Montjoye et al., 2013).
6. **Compares policies.** It ranks agency levers by how much each reduces
   inference accuracy and unicity:
   - retention from 7 days to 3 years;
   - rounding timestamps to the hour;
   - aggregate-only results;
   - limited search windows.
7. **"Your week" mode.** A visitor describes their typical week and sees what
   could be inferred about them. Inputs are session-only and never stored.

## Status

| Component | Status |
|---|---|
| Multi-source camera ETL (OSM, DeFlock, agency portals) with dedupe + cross-check | ✅ |
| Road network, direction-aware snapping, lot / service-road cameras | ✅ |
| NHTS-based routine generator (template generator kept as a fallback) | ✅ |
| Routing, direction-aware matching, sensor noise model | ✅ |
| Stored runs: ground truth + noisy read log | ✅ |
| Inference engine: HDBSCAN anchors, schedule reconstruction, anomaly detection | ✅ |
| Population simulation (~1,000 drivers) + unicity analysis | ✅ |
| Policy comparison | ✅ |
| Celery queue with progress reporting; Redis graph / coverage / run cache | ✅ |
| Frontend: map, read log, step-by-step reveal, unicity charts, policy controls, "your week" | ✅ |
| Validation on real location-history exports from consenting volunteers | ✅ |

## Architecture

```mermaid
flowchart LR
    subgraph sources["Data sources"]
        OSM["OpenStreetMap"]
        DEFLOCK["DeFlock export"]
        AGENCY["Agency transparency portals"]
        NHTS["NHTS trip diaries"]
    end
    ETL["ETL<br/>camera merge + dedupe<br/>road graph + snapping<br/>NHTS processing"]
    DB[("PostGIS")]
    FE["Next.js + MapLibre"]
    API["FastAPI"]
    REDIS[("Redis cache")]
    Q["Celery queue"]
    SIM["Simulation worker<br/>routines · routing · matching · noise"]
    INF["Inference + unicity worker<br/>HDBSCAN · schedule · anomalies<br/>unicity · policy comparison"]
    RES[("Results store")]

    OSM --> ETL
    DEFLOCK --> ETL
    AGENCY --> ETL
    NHTS --> ETL
    ETL --> DB
    FE --> API
    API <--> REDIS
    API --> Q
    Q --> SIM
    SIM --> INF
    SIM --> DB
    INF --> RES
    RES --> API
```

See [docs/architecture.md](docs/architecture.md) for the module map and data flow.

## Quick start

Requires Docker.

```bash
docker compose up -d --build                     # db, redis, api, worker, web
docker compose exec api python -m platetrail.etl.run_all    # cameras (all sources), roads, places, NHTS
open http://localhost:3000
```

The first run downloads public data and caches it under `data/`.
Population and policy runs are queued jobs; progress shows in the UI.

## Using it

- **Explore a driver:** pick or simulate a driver, then switch between what
  the cameras saw and what actually happened. Step through the reveal: reads,
  then the inferred anchors, then the inferred schedule, then the anomalies.
- **Population:** run a 1,000-driver population and view unicity curves (share
  of drivers unique by *p* reads) under any camera density and noise setting.
- **Policies:** pick retention, timestamp rounding, aggregation and search
  window, and see the effect on inference accuracy and unicity.
- **Your week:** describe your week to see what this network could infer
  about you. Nothing is stored.

## Results

> Results from the final system go here. Placeholders show the planned
> tables.

### Coverage

| Measure | Result |
|---|---|
| Reads per driver-week (median, IQR) | **[TBD]** · *(current slice: 6–7, IQR 3–10)* |
| Drivers never read in a week | **[TBD]** · *(current slice: 10%)* |
| Share of a driver's reads from their top camera (median) | **[TBD]** · *(current slice: 75%)* |

### Inference on synthetic drivers (vs. ground truth)

| Metric | Naive baseline | Inference engine |
|---|---|---|
| Home error, median | *(current slice, 1 wk: 2.9 km)* | **[TBD]** |
| Work/school error, median | *(current slice, 1 wk: 1.5 km)* | **[TBD]** |
| Drivers with no estimate | *(current slice, 1 wk: 50%)* | **[TBD]** |
| Schedule recovered | n/a | **[TBD]** |
| Anomaly precision / recall | n/a | **[TBD]** |

### Inference on real movement (consenting volunteers)

| Metric | Result |
|---|---|
| Home / work error vs. each person's confirmed places | **[TBD]** |
| Schedule recovered | **[TBD]** |

### Unicity

| Reads known (*p*) | Share of drivers uniquely identified |
|---|---|
| 1 | **[TBD]** |
| 2 | **[TBD]** |
| 4 | **[TBD]** |
| 8 | **[TBD]** |

### Policy comparison

| Policy | Inference accuracy change | Unicity change |
|---|---|---|
| Retention 7 days (vs. 3 years) | **[TBD]** | **[TBD]** |
| Timestamps rounded to the hour | **[TBD]** | **[TBD]** |
| Aggregate-only results | **[TBD]** | **[TBD]** |
| Limited search windows | **[TBD]** | **[TBD]** |

### Robustness

Sensitivity sweeps over noise, camera density (including Edison's 92 newly
approved cameras) and direction assumptions, with best and worst case for
unknown directions: **[TBD]**.

### Camera data accuracy

Agreement rate between OSM, DeFlock and agency records, with documented
discrepancies: **[TBD]**.

Full write-ups: [docs/findings.md](docs/findings.md).

## Assumptions and limitations

Every modelling assumption is labelled in code and listed in
[docs/assumptions.md](docs/assumptions.md), and results are reported across
their ranges:
- the capture convention (rear-plate vs. oncoming);
- matching tolerance;
- noise rates;
- routine parameters;
- home placement;
- free-flow routing.

Known limitations include:
- NHTS is national, not local, so destinations are placed at real local places;
- mobile ALPR (patrol cars) is not modelled;
- the results describe this camera network, not ALPR everywhere.

## Ethics

- **No real plate reads are used.** All plates are synthetic, with state `ZZ`.
- **Only public camera data is used.**
- **Real location data comes only from consenting individuals**, is processed
  locally, and is never stored. "Your week" inputs are session-only.
- **The project measures what the data can and cannot reveal rather than
  advocating a side.**

## Development

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://platetrail:platetrail@localhost:5434/platetrail
.venv/bin/pytest                    # unit + API integration tests (CI runs them on every push)
cd ../frontend && npm install && npm run dev
```

## Credits

KTP Capstone (Computer Science / ITI). Camera data © OpenStreetMap
contributors and DeFlock; road data via OSMnx; travel behaviour from the NHTS.
Unicity method after de Montjoye et al., *Unique in the Crowd* (2013).
