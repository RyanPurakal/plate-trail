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

**About the 92-camera network.** Edison approved 92 more Flock cameras, but their locations are not public. Every "+92" result in this project uses a **hypothetical, simulated placement**: 92 synthetic cameras on Edison arterials (trunk, primary, secondary and tertiary roads), chosen with probability proportional to road length, at least 300 m from every real and other synthetic camera, each reading one travel direction, and drawn anew for each seed (`sim/scenarios.py`). Real locations would change these results.

- **Coverage is sparse today.** A typical driver is read 5 times a week (interquartile range 3–9). About 59% of a driver's reads come from a single camera, and 7% of drivers are never read in a week.
- **Even so, a few sightings identify a car.** In a crowd of 1,000, two (camera, hour) sightings single out 78% of the drivers who have two (3 seeds: 78–79%), and four single out 99.8% of those with four. With four weeks of history, 99% of all drivers are unique at four sightings (3 seeds: 98–99%).
- **Where you live is camera-limited; your schedule is not.** On today's network the inference engine places home no better than a naive guess. On the 271 drivers both methods can place, the median error is 4.02 km for the engine and 4.48 km for the baseline, but the median per-driver difference is 0 km: the engine is closer for 91 drivers, farther for 88, and at the same spot for 92. Its strength is the schedule: 92% of the routines that pass a camera (3 seeds: 92–95%) are recovered as regular, timed patterns. With a hypothetical placement of Edison's 92 approved cameras, 50% of homes are placed within 1 km. That is both the share of drivers with an estimate and the share of all drivers, because all 300 get one (3 seeds: 49–50%).
- **Policies differ a lot.**
  - Short search windows (±12 h around an incident) and aggregate-only release remove most of what can be inferred.
  - Rounding timestamps to the hour changes almost nothing.
  - One week of the hypothetical 92-camera network reveals more than four weeks of today's.

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
| Camera ETL (OSM / DeFlock), dedupe, agency count cross-check, hypothetical density scenario | ✅ |
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
- **Population & policy:** pick a stored population to see unicity curves (share of drivers singled out by *p* sightings, for several crowd sizes). Compare policies by unicity and by how many homes the engine still places within 1 km (as a share of all drivers). Click a bar for detail, or switch to the table view.
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

Values are seed 0. Parentheses give the range over seeds 0, 1 and 2.

| Metric | Naive baseline | Inference engine | Baseline, +92 hypothetical cameras | Engine, +92 hypothetical cameras |
|---|---|---|---|---|
| **Home error, median, on drivers both methods place** (n = 271; +92: 300) | 4.48 km (4.36–4.63) | **4.02 km** (3.75–4.02) | 1.02 km (1.02–1.11) | **1.00 km** (0.99–1.01) |
| Per driver: engine closer / farther / same spot | | 91 / 88 / 92 | | 142 / 134 / 24 |
| Home error, median, every driver each method places (engine n = 299) | 4.48 km (n = 271) | 4.21 km (3.84–4.21) | 1.02 km (n = 300) | 1.00 km (n = 300) |
| Home within 1 km, share of drivers with an estimate | 18% (15–18%) | 17% (15–17%) | 49% (45–49%) | 50% (49–50%) |
| Home within 1 km, share of all 300 drivers | 16% (13–16%) | 17% (15–17%) | 49% (45–49%) | 50% (49–50%) |
| Work/school error, median (drivers with an estimate) | 3.50 km (3.49–3.75) | 5.54 km (5.43–6.17) | 1.11 km (0.89–1.11) | 1.21 km (1.00–1.40) |
| Drivers with no home / work estimate | 10% / 9% | <1% / 56% | 0% / 0% | 0% / 5% |
| Routines recovered | n/a | 302 of 327 (92%; 92–95%) | n/a | 640 of 654 (98%; 98% at all seeds) |
| Anomaly precision / recall | n/a | 57% / 29% (57–63% / 29–30%) | n/a | 50% / 36% (50–55% / 36–40%) |

A *routine* is a trip the driver repeats between the same two places at a similar time (within 45 minutes) on at least 3 days. It is *observable* if any of its trips produced a read, and *recovered* if at least half of its trips produced a read matching a regular pass the engine inferred (same camera, within 45 minutes).

On matched drivers the engine is not better than the baseline. The median per-driver difference is 0 km at every seed, and a sign test on closer vs. farther finds no difference (p = 0.88, 0.32, 0.20 for seeds 0–2). The two methods often name the same camera.

The engine's confidence label measures how consistent the evidence is, not how close the estimate is: "high" confidence homes are still 3.6 km off at the median on today's network.

### Inference on real movement

The importer is built and verified on synthetic Timeline exports. Sixty drivers in all three export formats recovered 3,560 of 3,573 trips, and the scores match the table above ([details](docs/real_data_validation.md)). **It has not been run on a real person's data yet.**

### Unicity (crowd of 1,000, hourly points; F5)

Each cell is the share of eligible drivers who are unique, then the share of all drivers. "Eligible" means at least *p* distinct (camera, hour) points; for *p* = 4 in one week on today's network that is 655 of 1,000 drivers. Values are seed 0, with the 3-seed range in parentheses.

| Sightings known (*p*) | 1 week, OSM | 4 weeks, OSM | 1 week, +92 hypothetical | 4 weeks, +92 hypothetical |
|---|---|---|---|---|
| 1 | 12% / 11% (12–15 / 11–14) | 12% / 12% (12–14 / 12–14) | 9% / 9% (9–11 / 9–11) | 9% / 9% (9–11 / 9–11) |
| 2 | 78% / 66% (78–79 / 66–68) | 84% / 84% (83–84 / 82–84) | 81% / 81% (81–85 / 81–84) | 89% / 89% (89–90 / 89–90) |
| 4 | 99.8% / 65% (99.6–99.8 / 65–65) | 99.9% / 99% (99.9–99.9 / 98–99) | 99% / 98% (99.2–99.5 / 97.9–98.1) | 99.9% / 99.9% (99.9–100 / 99.9–100) |
| 8 | 100% / 35% (100 / 30–35) | 100% / 91% (100 / 89–91) | 99.9% / 97% (99.9–100 / 96–97) | 100% / 100% (100 / 100) |

Unicity falls as the crowd grows: at *p* = 2 it is 97% in a crowd of 100 (3 seeds: 96–99%) and 78% in a crowd of 1,000. Real Edison volume is far larger, so these are upper bounds.

### Policy comparison (1,000 drivers, 4 weeks, OSM cameras; F7)

Values are seed 0, with the 3-seed range in parentheses. "Homes within 1 km" is given both ways: as a share of the drivers the engine can still place, and as a share of all 1,000 drivers. When few homes can be estimated, as with the ±12 h window, the first share rests on very few drivers.

| Policy | Homes estimated | Homes within 1 km, of those estimated | Homes within 1 km, of all drivers | Work estimated | Unique, *p* = 2 | Unique, *p* = 4 |
|---|---|---|---|---|---|---|
| No limits (4 weeks kept) | 99% | 17% (16–17%) | 17% (16–17%) | 45% (41–45%) | 84% (82–84%) | 99% (98–99%) |
| Keep 7 days | 78% | 19% (17–21%) | 15% (13–16%) | 26% (21–26%) | 67% (66–68%) | 66% (63–66%) |
| Keep 1 day | 0% | — | 0% | 0% | 15% (13–15%) | 4% (3–4%) |
| Round timestamps to the hour | 99% | 17% (15–18%) | 16% (15–17%) | 47% (43–47%) | 84% (83–84%); at 15-min points 97% → 84% | 99% (98–99%) |
| Search window ±36 h | 43% | 22% (18–24%) | 9% (8–10%) | 16% (12–16%) | 56% (56–58%) | 30% (27–30%) |
| Search window ±12 h | 3% | 38% (17–38%) | 1% (0–1%) | 7% (5–7%) | 24% (22–24%) | 6% (4–6%) |
| Aggregate counts only | 0% | — | 0% | 0% | 0% | 0% |

On the hypothetical 92-camera network (4 weeks), 7-day retention still leaves 98% unique at *p* = 4 (3 seeds: 98–99%). It also places 39% of all drivers' homes within 1 km (37–46%), which is 40% of the 98% it can place (38–47%) ([F7](docs/findings.md)). Over a 12-week history (seed 0), keeping 28 days still leaves 98% unique at *p* = 4 (100% with no limit), and keeping 7 days leaves 67%; work estimates fall from 68% (no limit) to 43% (28 days) and 22% (7 days) ([F7](docs/findings.md)). A retention row is only computed when the limit is shorter than the history, so the 7-day rows are never measured on 1-week data. Retention longer than the simulated history equals "no limits", so multi-year retention is not measured directly; the 12-week row is a lower bound for it.

### Robustness

Each matching and noise assumption was varied one at a time on the same 300 drivers ([F8](docs/findings.md#f8-robustness-the-conclusions-survive-every-matching-and-noise-assumption)): capture convention, tolerance, undirected and ambiguous cameras, lot events, miss and misread rates, and downtime.

One week, seed 0. In one week the engine places 215 of the 300 homes under the defaults.

| | Engine home error (median, drivers with an estimate) | Homes within 1 km, of those estimated | Homes within 1 km, of all drivers | Unique, *p* = 2 (crowd of 300) |
|---|---|---|---|---|
| Defaults | 3.99 km | 17.7% (n = 215) | 13% | 74% |
| Range across all 10 assumption changes | 3.70–4.22 km | 16.7–21.6% | 12–14% | 60–76% |
| +92 hypothetical cameras | 1.14 km | 44.7% (n = 293) | 44% | 91% |

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
- The 92 new cameras' locations are not public, so every "+92" result uses a hypothetical, simulated placement (see the note under Headline results).
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

The backend includes a C++ routing module (pybind11, built by `pip install -e .`), so a C++17 compiler is required. Routing uses it by default; `PLATETRAIL_ROUTER=python` selects the networkx reference. It returns identical routes about 5× faster end to end ([details](docs/technical_reference.md#c-router-pybind11)). Tests marked `db` are skipped when `DATABASE_URL` is unset. CI runs everything against a PostGIS service container on every push.

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
| [docs/camera_sources.md](docs/camera_sources.md) | sources, count cross-check, hypothetical density scenario |
| [docs/real_data_validation.md](docs/real_data_validation.md) | exporting and validating your own Timeline |
| [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) | open decisions and follow-ups |
| [Plate-Trail-Proposal.md](Plate-Trail-Proposal.md) | the original proposal |

## Credits

Capstone project (Computer Science / ITI). Camera data © OpenStreetMap contributors (including DeFlock mappers); road data via OSMnx; travel behaviour from the 2022 NHTS (FHWA / ORNL). Basemap © OpenFreeMap / OpenMapTiles. Unicity method after de Montjoye et al., *Unique in the Crowd* (2013).
