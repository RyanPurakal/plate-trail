# Plate Trail

**What license plate cameras can reconstruct about your week.**

Plate Trail measures what a history of automated license plate reader (ALPR) reads can reveal about a driver. It combines:
- the real camera locations in Edison and New Brunswick, NJ;
- realistic travel behaviour from the 2022 National Household Travel Survey (NHTS);
- a population-scale analysis of how quickly drivers become uniquely identifiable.

It then compares the policies an agency could adopt by how much each one reduces what the data reveals.

No real plate reads are used. Every driver is synthetic, and every plate carries the made-up state code `ZZ`.

| What the cameras saw | What actually happened |
|---|---|
| ![Read log as recorded: reads, the implied sequence, and the naive HOME?/WORK? guess](docs/figures/demo_run8_saw.jpg) | ![Ground truth: true routes, every camera pass, true home and work, and the guess's error](docs/figures/demo_run8_happened.jpg) |

*Demo run #8: a 4-week commuter, plate `ZZ F33PQR`. These screenshots are also the presentation fallback if the live demo fails.*

---

## Why this exists

ALPR networks are expanding fast, and Edison recently approved 92 more Flock cameras. The public debate is stuck between two positions:
- "the cameras only log a plate at a few fixed points";
- "enough reads reveal a person's whole routine".

Neither side usually backs its claim with real camera positions and measured numbers. Courts increasingly ask how complete a picture location data paints (the "mosaic" argument in *Carpenter v. United States*). Plate Trail answers that question with measurements for this specific camera network. It also shows how the answer changes with camera density, retention and policy.

## Headline results

All results come from synthetic drivers on the real camera network. Details and caveats are in [docs/findings.md](docs/findings.md).

- **Coverage is sparse today.** A typical driver is read 5 times a week (interquartile range 3–9). About 59% of a driver's reads come from a single camera, and 7% of drivers are never read in a week.
- **Even so, a few sightings identify a car.** In a crowd of 1,000, two (camera, hour) sightings single out about 80% of drivers, and four single out 99% of those with four. With four weeks of history, 99% of all drivers are unique at four sightings.
- **Where you live is camera-limited; your schedule is not.** On today's network the inference engine's median home estimate is 4.2 km off, no better than a naive guess. But 92% of routine trips that pass a camera are recovered as a regular, timed pattern. With Edison's 92 approved cameras (simulated placement), half of homes are placed within 1 km.
- **Policies differ a lot.**
  - Short search windows (±12 h around an incident) and aggregate-only release remove most of what can be inferred.
  - Rounding timestamps to the hour changes almost nothing.
  - One week of the denser network reveals more than four weeks of today's.

## What it does

1. **Builds the camera network.** It loads ALPR cameras from OpenStreetMap, which is also where DeFlock stores its crowdsourced map, and deduplicates them. It cross-checks the counts against agency transparency figures, then snaps each camera to the road it watches, with its facing direction.
2. **Simulates realistic weeks.** Weekly routines are assembled from NHTS one-day trip diaries and placed at real Edison / New Brunswick places, then routed on the real road network. A hand-written template generator is kept as a fallback.
3. **Decides which cameras see each trip.** Matching is direction-aware, with a sensor model for missed reads, misreads, camera downtime and timestamp jitter.
4. **Infers what an analyst could learn** from the read log alone: likely home and work or school areas, the recurring weekly schedule, and anomalous trips. These are shown as plain-language conclusions with confidence levels, next to a deliberately simple naive baseline.
5. **Measures identifiability across a population.** For 1,000 drivers it computes **unicity**: the share of drivers uniquely matched by *p* of their own sightings, following *Unique in the Crowd* (de Montjoye et al., 2013).
6. **Compares policies:**
   - retention limits;
   - rounding timestamps to the hour;
   - limited search windows;
   - aggregate-only release.

   Each is scored by how much it reduces inference accuracy and unicity.
7. **"Your week" mode.** A visitor describes their typical week and sees what could be inferred about them. Inputs are session-only and never stored.
8. **Real-data validation.** A local importer runs your own Google Timeline export through the same pipeline and scores the inference against your labelled home and work. Nothing is stored or uploaded.

## Status

| Component | Status |
|---|---|
| Camera ETL (OSM / DeFlock), dedupe, agency count cross-check, density scenario | ✅ |
| Road network, direction-aware snapping, lot / service-road cameras | ✅ |
| NHTS-based routine generator (template generator kept as a fallback) | ✅ |
| Routing, direction-aware matching, sensor noise model | ✅ |
| Stored runs: ground truth + noisy read log | ✅ |
| Inference engine: HDBSCAN anchors, schedule reconstruction, anomaly detection | ✅ |
| Population simulation (1,000 drivers) + unicity analysis | ✅ |
| Policy comparison | ✅ |
| Celery queue with progress reporting; Redis route / run / analysis cache | ✅ |
| Frontend: map, read log, step-by-step reveal, unicity and policy charts, "your week" | ✅ |
| Real-data validation (Google Timeline importer) | ✅ built and tested on synthetic exports; **not yet run on a real file** ([open questions](docs/OPEN_QUESTIONS.md)) |

## Architecture

```mermaid
flowchart LR
    subgraph sources["Data sources"]
        OSM["OpenStreetMap<br/>(incl. DeFlock)"]
        AGENCY["Agency portals<br/>(counts)"]
        NHTS["NHTS 2022 diaries"]
    end
    ETL["ETL<br/>camera merge + dedupe<br/>road graph + snapping<br/>places · NHTS"]
    DB[("PostGIS")]
    FE["Next.js + MapLibre"]
    API["FastAPI"]
    REDIS[("Redis<br/>broker + cache")]
    Q["Celery queue"]
    SIM["Simulation worker<br/>routines · routing · matching · noise"]
    INF["Inference + unicity<br/>HDBSCAN · schedule · anomalies<br/>unicity · policy comparison"]
    RES[("Results<br/>population tables<br/>cached analyses")]
    TL["Timeline importer<br/>(local CLI)"]

    OSM --> ETL
    AGENCY --> ETL
    NHTS --> ETL
    ETL --> DB
    FE --> API
    API <--> REDIS
    API --> Q
    Q --> SIM
    SIM --> DB
    SIM --> INF
    INF --> RES
    RES --> API
    TL --> SIM
```

The module map and data flow are in [docs/architecture.md](docs/architecture.md), and module-by-module detail is in [docs/technical_reference.md](docs/technical_reference.md).

## Quick start

Requires Docker. PostGIS is published on host port **5434** (override with `PLATETRAIL_DB_PORT`). Raw data and the road graph are cached under `data/` (gitignored).

```bash
# 1. Start everything: db :5434, redis, api :8000, worker, web :3000
docker compose up -d --build

# 2. Build the data (first run downloads public data; reruns use the data/ caches)
docker compose exec api python -m platetrail.etl.run_etl              # ALPR cameras (Overpass)
docker compose exec api python -m platetrail.roads.run_roads          # road graph + snapping (minutes the first time)
docker compose exec api python -m platetrail.routines.places          # towns + candidate places
docker compose exec api python -m platetrail.routines.nhts_data --download   # NHTS 2022 CSVs (~4.5 MB)
docker compose restart api worker                                     # both cache cameras and the graph

# 3. A population for the charts (also available as POST /jobs/population)
docker compose exec api python -m platetrail.population --drivers 1000 --weeks 1

open http://localhost:3000
```

Rerun the data steps in that order: reloading cameras clears their snaps, so `run_roads` must follow `run_etl`.

## Using it

- **One driver:** pick or simulate a driver, then switch between what the cameras saw and what actually happened. Step through the reveal: reads, then the inferred home and work areas, then the regular schedule, then the anomalies.
- **Population & policy:** pick a stored population to see unicity curves (share of drivers singled out by *p* sightings, for several crowd sizes). Compare policies by unicity and by how many homes the engine still places within 1 km. Click a bar for detail, or switch to the table view.
- **Your week:** place your home (and work) on the map, describe your week, and see what this network could read and infer. Nothing is stored.
- **Your real data:** see [docs/real_data_validation.md](docs/real_data_validation.md).

## Results

### Coverage (population #1: 1,000 NHTS drivers, 1 week, OSM cameras)

| Measure | Result |
|---|---|
| Reads per driver-week, median (IQR) | 5 (3–9) |
| Drivers never read in a week | 7.4% |
| Share of a driver's reads from their top camera, median | 59% |

### Inference on synthetic drivers (300 drivers, 4 weeks, vs. ground truth; F6)

| Metric | Naive baseline | Inference engine | Engine, +92 cameras |
|---|---|---|---|
| Home error, median | 4.48 km | 4.21 km | 1.00 km |
| Home within 1 km | 18% | 17% | 50% |
| Work/school error, median | 3.50 km | 5.54 km | 1.21 km |
| Drivers with no home / work estimate | 10% / 9% | 0% / 56% | 0% / 5% |
| Schedule recovered (observable routine trips) | n/a | 92% | 98% |
| Anomaly precision / recall | n/a | 57% / 29% | 50% / 36% |

The engine's confidence label measures how consistent the evidence is, not how close the estimate is: "high" confidence homes are still 3.6 km off at the median on today's network.

### Inference on real movement

The importer is built and verified on synthetic Timeline exports. Sixty drivers in all three export formats recovered 3,560 of 3,573 trips, and the scores match the table above ([details](docs/real_data_validation.md)). **It has not been run on a real person's data yet.**

### Unicity (crowd of 1,000, hourly points; F5)

Each cell is the share of eligible drivers who are unique, then the share of all drivers.

| Sightings known (*p*) | 1 week, OSM | 4 weeks, OSM | 1 week, +92 cameras | 4 weeks, +92 cameras |
|---|---|---|---|---|
| 1 | 12% / 11% | 12% / 12% | 9% / 9% | 9% / 9% |
| 2 | 78% / 66% | 84% / 84% | 81% / 81% | 89% / 89% |
| 4 | 99.8% / 65% | 99.9% / 99% | 99% / 98% | 99.9% / 99.9% |
| 8 | 100% / 35% | 100% / 91% | 99.9% / 97% | 100% / 100% |

Unicity falls as the crowd grows: at *p* = 2 it is 97% in a crowd of 100 and 78% in a crowd of 1,000. Real Edison volume is far larger, so these are upper bounds.

### Policy comparison (population #2: 4 weeks, OSM cameras; F7)

| Policy | Homes within 1 km | Work estimated | Unique, *p* = 2 | Unique, *p* = 4 |
|---|---|---|---|---|
| No limits (4 weeks kept) | 17% | 45% | 84% | 99% |
| Keep 7 days | 15% | 26% | 67% | 66% |
| Keep 1 day | 0% | 0% | 15% | 4% |
| Round timestamps to the hour | 16% | 47% | 84% (15-min points: 97% → 84%) | 99% |
| Search window ±36 h | 9% | 16% | 56% | 30% |
| Search window ±12 h | 1% | 7% | 24% | 6% |
| Aggregate counts only | 0% | 0% | 0% | 0% |

On the denser network (4 weeks, +92 cameras) 7-day retention still leaves 98% unique at *p* = 4 and 39% of homes within 1 km ([F7](docs/findings.md)). Retention longer than the simulated 4 weeks equals "no limits", so the 4-week row is a lower bound for multi-year retention.

### Robustness

Each matching and noise assumption was varied one at a time on the same 300 drivers ([F8](docs/findings.md#f8-robustness-the-conclusions-survive-every-matching-and-noise-assumption)): capture convention, tolerance, undirected and ambiguous cameras, lot events, miss and misread rates, and downtime.

| | Engine home error (median) | Homes within 1 km | Unique, *p* = 2 (crowd of 300) |
|---|---|---|---|
| Defaults | 3.99 km | 13% | 74% |
| Range across all 10 assumption changes | 3.70–4.22 km | 12–14% | 60–76% |
| +92 scenario cameras | 1.14 km | 44% | 91% |

Camera density changes the results far more than any single modelling assumption. The largest assumption effect is a strict 30° matching tolerance (unicity 74% → 60%).

### Camera data accuracy

OSM maps 40 Flock cameras in Edison against the 24 the PD portal counts. The gap is most likely private and other-agency cameras. New Brunswick's 10 match the reported 11 closely ([camera sources](docs/camera_sources.md)).

## Assumptions and limitations

Every modelling assumption is labelled in the code and listed in [docs/assumptions.md](docs/assumptions.md), with where it was tested. Known limitations:
- NHTS is national, not local, so destinations are placed at real local places.
- Weeks are assembled from one-day diaries.
- Routing is free-flow fastest path, with no congestion or personal habit.
- Misreads are look-alike swaps only, which probably understates their effect.
- Mobile ALPR (patrol cars) is not modelled.
- The 92 new cameras' locations are not public, so their placement is simulated.
- The results describe this camera network, not ALPR everywhere.

Open items and suggested follow-ups are in [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md).

## Ethics

- **No real plate reads are used.** All plates are synthetic, with state `ZZ`, so they cannot match a real registration.
- **Only public camera data is used.**
- **Real location data comes only from the person it describes.** It is processed locally and never stored. "Your week" inputs are session-only: no database writes, no route cache, no logging.
- **The project measures what the data can and cannot reveal rather than advocating a side.** Assumptions are labelled, and results are reported across their ranges.

## Development

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://platetrail:platetrail@localhost:5434/platetrail
.venv/bin/pytest            # unit + db/API tests (db tests use a separate platetrail_test database)
cd ../frontend && npm install && npm run dev
```

Tests marked `db` are skipped when `DATABASE_URL` is unset. CI runs everything against a PostGIS service container on every push.

Reproducing the findings (from `backend/`):

```bash
python scripts/evaluate_inference.py --drivers 300 --weeks 4 [--extra-cameras 92]   # F6
python scripts/policy_report.py <population_id>                                       # F7
python scripts/sensitivity.py --drivers 300 --weeks 1                                 # F8
python scripts/validate_synthetic_timeline.py --drivers 60 --weeks 4                  # importer check
```

## Documentation

| Document | Contents |
|---|---|
| [docs/findings.md](docs/findings.md) | F1–F8, each with setup, results and caveats |
| [docs/assumptions.md](docs/assumptions.md) | every modelling assumption, where it lives, how it was tested |
| [docs/architecture.md](docs/architecture.md) | system diagram, module map, data flow |
| [docs/technical_reference.md](docs/technical_reference.md) | ETL, snapping, matching, generators, noise, API, frontend |
| [docs/camera_sources.md](docs/camera_sources.md) | sources, count cross-check, density scenario |
| [docs/real_data_validation.md](docs/real_data_validation.md) | exporting and validating your own Timeline |
| [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) | open decisions and follow-ups |
| [KTP-Capstone-Proposal-Plate-Trail.md](KTP-Capstone-Proposal-Plate-Trail.md) | the original proposal |

## Credits

KTP Capstone (Computer Science / ITI). Camera data © OpenStreetMap contributors (including DeFlock mappers); road data via OSMnx; travel behaviour from the 2022 NHTS (FHWA / ORNL). Basemap © OpenFreeMap / OpenMapTiles. Unicity method after de Montjoye et al., *Unique in the Crowd* (2013).
