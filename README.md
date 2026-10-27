# Plate Trail

**A location-privacy check-up for any area and your own routes.**

Plate Trail shows where fixed license plate reader (ALPR) and similar sensors are recorded in public map data, and explains in plain language what a history of their reads could suggest about a regular drive. It is a tool to come back to:
- **Explore any area.** Search a town or address, or draw a box, and see the mapped sensors with a summary of how many there are, how much of the main road network they sit near, and where the data comes from and how fresh it is.
- **Check your own routes, kept on your device.** Add the drives you make (a commute, a school run) by clicking start and end. Routes are saved only in your browser; the server computes a check and keeps nothing. Each route shows the sensors passed, a timeline of where reads would happen, and what a few days to a year of read history could suggest.
- **See what changed since your last visit.** Saved areas and checked routes keep a local snapshot, so on return the app lists sensors newly mapped or no longer listed, and data updates.
- **Compare and drill down.** Two areas or two routes side by side, sensor details, a retention-period slider, and short "Learn more" explainers.

The **example study** behind it measures, for Edison and New Brunswick, NJ, what a read history can reveal about synthetic drivers. It combines the mapped camera locations, travel behaviour from the 2022 National Household Travel Survey (NHTS), and a population-scale analysis of how quickly drivers become uniquely identifiable, then compares retention and access policies by how much each reduces what the data reveals.

No real plate reads are used. Every driver in the study is synthetic, and every plate carries the made-up state code `ZZ`. The app does not suggest routes around sensors and has no information about any real vehicle.

| What the cameras saw | What actually happened |
|---|---|
| ![Read log as recorded: reads, the implied sequence, and the naive HOME?/WORK? guess](docs/figures/demo_run8_saw.jpg) | ![Ground truth: true routes, every camera pass, true home and work, and the guess's error](docs/figures/demo_run8_happened.jpg) |

*Example study, demo run #8: a 4-week commuter, plate `ZZ F33PQR`. These screenshots are also the presentation fallback if the live demo fails.*

---

## Why this exists

Fixed sensors that read license plates are common on public roads, and their locations are often recorded in public map data. What is harder to picture is what a history of reads adds up to: a single read places a car at one point, while many reads over weeks can show a routine. How much they show depends on where the sensors are, which way they face, and how long reads are kept.

Plate Trail makes that concrete for the places a person actually lives and drives, using only public sensor locations and simulated reads. The example study adds measured numbers for one network, including how the answer changes with sensor density, retention and access policy. The question of how complete a picture location data paints also comes up in courts (the "mosaic" argument in *Carpenter v. United States*); the project reports measurements rather than taking a side.

## Example study: headline results

All results come from synthetic drivers on the mapped camera network in Edison and New Brunswick, NJ. Details and caveats are in [docs/findings.md](docs/findings.md).

**About the 92-camera network.** Edison approved 92 additional cameras, but their locations are not public. Every "+92" result in this project uses a **hypothetical, simulated placement**: 92 synthetic cameras on Edison arterials (trunk, primary, secondary and tertiary roads), chosen with probability proportional to road length, at least 300 m from every real and other synthetic camera, each reading one travel direction, and drawn anew for each seed (`sim/scenarios.py`). Real locations would change these results.

- **Coverage is sparse today.** A typical driver is read 5 times a week (interquartile range 3–9). About 59% of a driver's reads come from a single camera, and 7% of drivers are never read in a week.
- **Even so, a few sightings identify a car.** In a crowd of 1,000, two (camera, hour) sightings single out 78% of the drivers who have two (3 seeds: 78–79%), and four single out 99.8% of those with four. With four weeks of history, 99% of all drivers are unique at four sightings (3 seeds: 98–99%).
- **Where you live is camera-limited; your schedule is not.** On today's network the inference engine places home no better than a naive guess. On the 271 drivers both methods can place, the median error is 4.02 km for the engine and 4.48 km for the baseline, but the median per-driver difference is 0 km: the engine is closer for 91 drivers, farther for 88, and at the same spot for 92. Its strength is the schedule: 92% of the routines that pass a camera (3 seeds: 92–95%) are recovered as regular, timed patterns. With a hypothetical placement of Edison's 92 approved cameras, 50% of homes are placed within 1 km. That is both the share of drivers with an estimate and the share of all drivers, because all 300 get one (3 seeds: 49–50%).
- **Policies differ a lot.**
  - Short search windows (±12 h around an incident) and aggregate-only release remove most of what can be inferred.
  - Rounding timestamps to the hour changes almost nothing.
  - One week of the hypothetical 92-camera network reveals more than four weeks of today's.

## What it does

### Check-up

1. **Loads public sensor locations for any box** (`GET /area`): OpenStreetMap nodes tagged `surveillance:type=ALPR`, plus any sensor files configured for the region, cached on disk and refreshed after 7 days. No region file is needed for an ad-hoc area. Place search goes through Nominatim (`POST /geocode`), with the query sent in the request body and not logged or stored.
2. **Summarizes the area:** sensor count and density, how many have a known facing direction, the share of main-road length within 100 m of a sensor, and each data source with its fetch date and latest map edit.
3. **Checks a route** (`POST /route/check`): routes the drive both ways on the study road network, or on a road network built around the route elsewhere, and lists each sensor passed with whether its direction would record the trip. Compute-only: nothing is stored, cached or logged.
4. **Says what a read history could suggest** (`POST /route/history`): repeats the route on a weekly schedule, applies the sensor noise model and runs the study's inference engine on 1 day to 1 year of reads, then reports regular passes and suggested overnight and daytime areas in plain sentences. Also compute-only.
5. **Keeps everything personal in the browser:** saved routes, saved areas and the last-look snapshots behind "Since your last visit" live in `localStorage`. Area links hold only map coordinates.

### Example study

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
| Check-up: explore any area (search, draw a box, summary card, sensor details) | ✅ |
| Check-up: my routes on this device (route check, read timeline, read-history periods with retention slider) | ✅ |
| Check-up: since your last visit, compare areas and routes, Learn more explainers | ✅ |
| Check-up: mobile and accessibility polish, lazy-loaded example study | in progress ([roadmap](docs/ROADMAP.md)) |
| Camera ETL (OSM / DeFlock), dedupe, agency count cross-check, hypothetical density scenario | ✅ |
| Road network, direction-aware snapping, lot / service-road cameras | ✅ |
| NHTS-based routine generator (template generator kept as a fallback) | ✅ |
| Routing, direction-aware matching, sensor noise model | ✅ |
| Stored runs: ground truth + noisy read log | ✅ |
| Inference engine: HDBSCAN anchors, schedule reconstruction, anomaly detection | ✅ |
| Population simulation (1,000 drivers) + unicity analysis | ✅ |
| Policy comparison | ✅ |
| Celery queue with progress reporting; Redis route / run / analysis cache | ✅ |
| Example study frontend: map, read log, step-by-step reveal, unicity and policy charts, "your week" | ✅ |
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

**Check-up in Docker.** Exploring an area needs only step 1. Sensors and main roads for each explored box are fetched from OpenStreetMap on demand and cached under `data/raw/overpass_areas/` (mounted at `/data`, refetched after 7 days), so the first look at a new area can take a minute or two while Overpass answers. Route checks use the study road graph from step 2 when a route lies on it; other routes get roads downloaded around them and held in memory only. Nothing about a route is written to `data/` or to the API log.

**Study area.** The towns covered by the data steps come from a region file in `backend/platetrail/regions/`. The default, `nj_edison_new_brunswick`, is the NJ study. Set `PLATETRAIL_REGION` to another bundled id or to the path of a JSON file (towns as OSM boundary relations or plain boxes, optional sensor files, map view and notes) to build sensors, the road graph and places for a different area; Docker passes it through to the api and worker. [docs/new_region.md](docs/new_region.md) walks through a worked example.

## Using it

The page opens on the **Check-up** tab. The example study's sections follow an "Example study" label in the tab bar.

- **Explore an area:** search a town or address, draw a box, or explore the current map view, and load the fixed sensors recorded there in public map data (OpenStreetMap, plus any configured sensor files). The summary card lists the count, density, how many have a known direction, main-road coverage, and each source with its fetch date. Click a sensor for details, or step through them from the keyboard. Save an area to open it again later. The area is kept in the address (`?bbox=west,south,east,north`), so the page can be bookmarked or shared; it holds only map coordinates.
- **My routes:** "Add a route", then click start and end on the map. "Check this route" draws the drive both ways, rings the sensors passed and lists a read timeline; click a step to see it on the map. Below it, pick the days and times you usually drive and move the retention slider to see what 1 day to 1 year of reads could suggest. Routes stay in this browser; "Remove all from this device" clears them.
- **Since your last visit:** when you come back, saved areas are re-checked and any newly listed or no longer listed sensors and data updates are shown at the top. Routes you checked before can be re-checked with one button.
- **Compare:** pick two saved areas or two saved routes to see them side by side.
- **Learn more:** short explainers on what fixed sensors record, how retention length changes what can be inferred, and the study's unicity finding, linked from the cards they explain.

Example study (`?study=driver|population|yourweek` links straight to a section):

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
- **Real location data comes only from the person it describes.** It is processed locally and never stored. Saved routes and areas live only in the browser. Route checks, read-history requests and "Your week" inputs are compute-only: no database writes, no route cache, no logging. Place searches are not logged or written to disk.
- **No avoidance routing and nothing about real vehicles.** The app explains what sensors could record; it does not plan routes around them or look up plates.
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
| [docs/findings.md](docs/findings.md) | example study F1–F8, each with setup, results and caveats |
| [docs/assumptions.md](docs/assumptions.md) | every modelling assumption, where it lives, how it was tested |
| [docs/architecture.md](docs/architecture.md) | system diagram, module map, data flow |
| [docs/technical_reference.md](docs/technical_reference.md) | ETL, snapping, matching, generators, noise, API, frontend |
| [docs/camera_sources.md](docs/camera_sources.md) | sources, count cross-check, hypothetical density scenario |
| [docs/real_data_validation.md](docs/real_data_validation.md) | exporting and validating your own Timeline |
| [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) | open decisions and follow-ups |
| [docs/ROADMAP.md](docs/ROADMAP.md) | prioritized plan: the check-up tool, reusability, neutral wording |
| [Plate-Trail-Proposal.md](Plate-Trail-Proposal.md) | the original capstone proposal (the example study) |

## Credits

Capstone project (Computer Science / ITI). Camera data © OpenStreetMap contributors (including DeFlock mappers); place search by Nominatim (OpenStreetMap data); road data via OSMnx; travel behaviour from the 2022 NHTS (FHWA / ORNL). Basemap © OpenFreeMap / OpenMapTiles. Unicity method after de Montjoye et al., *Unique in the Crowd* (2013).
