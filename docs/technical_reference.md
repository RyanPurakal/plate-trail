# Technical reference

Module-by-module detail moved from the original README: camera ETL, road network and snapping, routing and matching, routine generators, noise model, stored runs, frontend, naive baseline and API. For the overview see the [README](../README.md); for the module map see [architecture.md](architecture.md); for every assumption see [assumptions.md](assumptions.md).

## Camera ETL

See [camera_sources.md](camera_sources.md) for sources, the
OSM-vs-agency count cross-check (`python -m platetrail.etl.cross_check`), and
the hypothetical density scenario (`extra_cameras`: synthetic cameras with a simulated placement).

```bash
cd backend
DATABASE_URL=postgresql+psycopg://platetrail:platetrail@localhost:5434/platetrail \
  .venv/bin/python -m platetrail.etl.run_etl            # add --refresh to refetch
```

Pulls ALPR cameras (`man_made=surveillance` + `surveillance:type=ALPR`) for
Edison and New Brunswick from OpenStreetMap via Overpass. Raw responses are
cached in `data/raw/overpass/`, so reruns don't hit Overpass. Direction comes
from `camera:direction`, falling back to `direction`. When both are present and
disagree, the summary lists the camera. New sources plug in as additional
`CameraLoader`s and go through the same deduplication step.

Export the stored cameras for a quick look in [geojson.io](https://geojson.io)
or QGIS. Each camera is a point, plus a 30 m ray for each direction it faces:

```bash
.venv/bin/python -m platetrail.etl.export_geojson   # -> data/exports/cameras.geojson
```

## Road network and snapping

```bash
.venv/bin/python -m platetrail.roads.run_roads      # add --refresh to re-download
```

Downloads the road graph for Edison + New Brunswick, buffered by 2 km, and
caches it as GraphML under `data/graphs/`. The first download takes several
minutes. The graph is OSMnx's drive network **plus service roads**, except
parking aisles, drive-throughs, emergency access and private roads. Service
roads are needed to reach places inside lots and business parks: Raritan
Center's internal streets are all `highway=service`. That gives 22,261 nodes
and 55,421 directed edges, 21,775 of them service roads. Service roads get
15 km/h (**assumption**), and route choice multiplies their travel time by 4
(**assumption**; timestamps use real times) so through traffic doesn't cut
through lots. Edges are stored in `road_edges`. Each camera is snapped to its
nearest **public** (non-service) edge within 50 m. On a two-way road it gets one `camera_edges` row
per direction, with that direction's true-north bearing taken at the snap
point. The summary lists dropped cameras, snap distances, close camera pairs,
and cameras whose direction is closer to perpendicular than parallel to their
road. Rerun this after the camera ETL, because reloading cameras clears the
snaps.

### Camera kinds

- **public_road**: snapped to a drive-network edge, as above.
- **service_road**: more than 50 m from any public road (deep inside a lot or
  business park). Snapped to the internal service street it watches and
  matched like a road camera (4 cameras, including Raritan Center's
  14174561401 on Mayfield Ave).
- **private_lot**: the camera watches a lot's driveway from beside a public
  road. It faces closer to perpendicular than parallel to that road, with a
  parallel service road within 10 m. It is
  attached to its lot polygon (retail > commercial > industrial > parking >
  shop) and gets no road snap. Each of its directions is recorded as pointing
  `into_lot` or `toward_road`. There are 6 such cameras, including 3 at Menlo
  Park Mall and 1 in Raritan Center.
- **snap_ambiguous** (flag): a public-road camera still more than 45° off its
  road axis after direction-aware snapping, so it is unclear which street it
  watches. It keeps the nearest snap (3 cameras).
- **direction_ambiguous** (flag): a camera whose direction tags disagree. The
  alternate reading is kept in `alt_directions_deg` (1 camera, node
  13271071475).

Divided roads: when a camera snaps to one carriageway of a divided road, the
opposite carriageway (one-way, parallel, opposite travel, within 30 m) is
**always** snapped too (5 cameras). Without this, a camera beside Albany St's
westbound carriageway never registered eastbound traffic. Snapping ignores
which way the camera faces. Which carriageway's traffic is actually captured
is decided by the matcher's bearing test under the capture convention (see
below), so the stored snaps don't encode either convention.

Snapping is direction-aware: if the nearest road isn't parallel to the camera
(more than 30° off) but a parallel road is at most 10 m farther, the parallel
road wins.

## Routing and camera matching

`platetrail.sim` routes a trip (origin, destination, departure time) by
shortest free-flow travel time and decides which cameras capture it. Matcher
settings (`MatchConfig`):

| Setting | Default | Meaning |
|---|---|---|
| `facing` | `rear_plate` | **Assumption:** a camera's direction tag is the way it faces, and it reads the rear plates of vehicles travelling that way. It captures travel bearing = camera direction. `oncoming` instead assumes it faces oncoming traffic (front plates) and captures camera direction + 180. |
| `tolerance_deg` | 45 | **Assumption.** Maximum difference between the travel bearing and the captured bearing |
| `undirected` | `best` | **Assumption.** Cameras without a direction capture both ways (`best`) or neither (`worst`) |
| `ambiguous_direction` | `primary` | For cameras with disagreeing tags, use `direction` (`primary`) or the other tag (`alternate`) |
| `lot_entrance` | `access_road` | A vehicle uses one lot entrance: the junction where its route turns between a public road and the lot's service roads (approach direction). A lot camera sees an arrival or departure only if that junction is the camera's entrance, i.e. the junction of the driveway it sits on (parallel to its facing; for a service road linking two junctions, the one behind an into-lot camera or ahead of a toward-road one). `nearest` instead picks the lot camera nearest the route's end; `all` lets every camera at the lot see it (an upper bound). |

**Capture convention (assumption).** `rear_plate` is a default assumption,
not something established from the data. OSM documents `direction` as the
way a camera faces, but it doesn't say which plate the camera reads. The
convention is applied in exactly one place, the matcher's bearing test.
Snapping, lot classification and the stored camera data are
convention-neutral, so switching `facing` changes only which passes count as
captured. Results should be reported under both settings.

Private-lot cameras see arrivals and departures at their lot. Under
`rear_plate`, an `into_lot` direction captures arrivals and a `toward_road`
direction captures departures; `oncoming` flips both.

```bash
.venv/bin/python scripts/sample_trips.py [--facing oncoming] [--tolerance 30] [--lot-entrance all]
```

Trip endpoints attach to the **nearest point on an edge**, not the nearest
intersection. The route starts and ends with partial edges, and a camera
counts only if it is on the part actually driven.

### C++ router (pybind11)

Routing is the hot path. A cProfile run of a 1,000-driver, 1-week population
job (2026-10-13) put 92.5% of the job in `Router._compute`, 81% of it inside
networkx's Dijkstra. Camera matching, noise and storage were each under 1%.
Without the profiler, a second identical run in the same process (every
route already cached) took 40 s against 486 s cold, so routing is about 91%
of a cold job. The unicity and policy analyses took 3.9 s in total and were
not worth porting.

**What was ported.** Only the search: `nx.single_source_dijkstra` inside
`Router._compute`. `backend/src/fastroute.cpp` (module
`platetrail._fastroute`) runs Dijkstra over a CSR copy of the graph that the
`Router` builds once at startup. Snapping, the virtual origin and destination
edges, path assembly and geometry stay in Python and are shared by both
backends. The C++ search reproduces networkx 3.x's tie-breaking so it
returns the **identical** path, not just an equally short one:
- heap order by (distance, push counter);
- neighbours in adjacency insertion order;
- parallel edges collapsed to their minimum cost;
- replace only on a strict improvement, and keep the last improver as
  predecessor;
- stop when the target is popped.

Costs are IEEE doubles summed in the same order, and the module is built
without `-ffast-math`.

**Switching.** `PLATETRAIL_ROUTER=cpp|python`, or `Router(G, backend=...)`.
The default is `cpp` when the extension is built and `python` otherwise
(with a logged warning). The networkx path is the reference implementation.

**Build.** `backend/pyproject.toml` uses scikit-build-core with pybind11
(`backend/CMakeLists.txt`), so `pip install -e ".[dev]"` compiles the module.
It needs a C++17 compiler; scikit-build-core fetches CMake and Ninja itself.
The Docker image installs `g++`. CI builds it on every push.

**Parity tests** (`tests/test_routing_parity.py`, run in CI; in CI they fail
rather than skip if the extension didn't build):
- every route on the toy graph between 23 points, compared field by field:
  edges, fractions, timings, names, polyline, and exact duration;
- 600 random routes on four 9×9 grids with integer travel times (so
  equal-cost paths are everywhere), one-way streets, parallel edges and
  service roads;
- the bare C++ search against `nx.single_source_dijkstra` on 30 random
  multigraphs (weights 0–3, self-loops, unreachable targets);
- input validation.

The full suite also passes with either backend forced.

**Benchmark** (`backend/scripts/benchmark_router.py`, 2026-10-13, Apple
Silicon, 11 cores; the job is single-threaded):
- a 1,000-driver, 1-week NHTS population job (simulate every driver and
  store, which is what the worker does for `POST /jobs/population`);
- each run is a fresh process with no Redis, so the route cache starts
  empty;
- the backends alternate (python, cpp, python, …), 3 runs each, with no
  other jobs running;
- startup (graph and cameras, plus the CSR copy for cpp) is timed
  separately because the worker pays it once.

| Backend | Job time, median (3 runs) | Range | Startup, median |
|---|---|---|---|
| Python (networkx) | 466.9 s (7.8 min) | 456.8–491.7 s | 9.4 s |
| C++ (pybind11) | **89.3 s (1.5 min)** | 86.1–90.3 s | 9.7 s |
| **Speedup** | **5.23×** | | |

All six runs produced the same digest over every trip's route edges and
timings and every read (14,930 trips, 6,572 reads), so the speedup changes
nothing in the results. The read count matches population #1 in the
findings.

The speedup is bounded by what wasn't ported. The warm-cache run above,
which does no routing at all, took 40 s, measured in a separate session. So
most of the C++ job time is the unported work: routine generation, route
geometry (shapely), matching, noise and storage. This split is an inference
from the two measurements, not a profile of the C++ run.

```bash
python scripts/benchmark_router.py --drivers 1000 --weeks 1 --repeats 3   # needs DATABASE_URL and the graph cache
```

## Routine generator

`platetrail.routines` plans each synthetic driver's trips behind a
`RoutineGenerator` interface. There are two generators: **NHTS** (the default
for `/simulate` and the runner CLI) and the hand-written **templates**.

### NHTS (`routines/nhts.py`, `routines/nhts_data.py`)

The source is the 2022 NextGen NHTS public-use CSV v2.1
([nhts.ornl.gov/downloads](https://nhts.ornl.gov/downloads), about 4.5 MB,
cached in `data/raw/nhts2022/`; fetch with
`python -m platetrail.routines.nhts_data --download`).

- **One day per person.** NHTS records a single travel day per person, so a
  week is assembled from matched one-day diaries.
- **Persona:** worker / student / non-worker, drawn from NHTS driver weights
  (65% / 3% / 33%).
- **Each day:** a stay-at-home day with the weighted NHTS share for that
  persona and weekday (workers about 15% of weekdays, non-workers about 35%),
  or a diary drawn from matching drivers (weighted by `WTPERFIN`).
- **Usable diaries:** 5,397. A usable diary is all private-vehicle trips as
  driver, home to home, with valid times. That excludes 39% of weighted
  driver travel-days (transit, walking or passenger trips), which would
  break the car's location chain.
- **Diary trips keep their NHTS departure time and purpose.** Destinations
  are local Edison / New Brunswick places chosen by purpose (work and school
  are the driver's fixed anchors; drop-offs and visits go to other homes) at
  a distance matching the diary's trip length (straight line × 1.3
  circuity, an **assumption**).
- **NHTS is national, not local.** Only 582 usable diaries are from the
  Middle Atlantic, too few to split by persona and day, so national weights
  are used with local places, as the proposal planned.

### Templates (`routines/templates.py`)

```bash
.venv/bin/python -m platetrail.routines.places          # load towns + candidate places from OSM (cached)
.venv/bin/python scripts/simulate_drivers.py --drivers 300
```

- **Templates** (`routines/templates.py`): commuter (weekday work trips,
  sometimes an errand on the way home, Saturday errand chains, Sunday worship
  or errand), student (Rutgers building, Mon–Thu plus some Fridays, evening
  food), shift worker (4 fixed night shifts a week at a hospital or
  industrial site, errands on off days). Every time, probability and spread
  is an **assumption**.
- **Homes** are uniform points on residential streets, weighted by street
  length, not OSM buildings. Building coverage is uneven: 2.37 typed
  residential buildings per residential street in Edison vs 0.63 in New
  Brunswick, so building sampling would under-represent New Brunswick.
  **Assumption:** homes are spread in proportion to residential street length.
  This ignores housing density: a street of apartment blocks gets the same
  weight per metre as a street of single-family houses, so dense areas
  (e.g. downtown New Brunswick) are likely under-represented. Census housing
  counts would fix this.
- **Places** (1,310) are OSM shops, food, services, leisure, worship,
  workplaces, university and hospitals inside the two towns. A place
  attaches to the network at its OSM centre point. If that is more than
  100 m from the network, it attaches at the **point on its building outline
  nearest the network** instead. That brings back 18 of 21 such places,
  including Amazon LGA5, LGA9 and DJE1, Macy's Logistics, Arizona Beverages,
  Europastry, C+A Global and CarMax. Places still more than **100 m** away are
  not sampled (3).
- **Errands** pick a category from a fixed mix (grocery 28%, retail 22%,
  food 25%, services 15%, leisure 10%; **assumption**), then a place in it,
  weighted by `exp(-distance / 4 km)` from the trip's origin. Drivers reuse a
  "usual" place per category 60% of the time. **Camera locations are never
  used.** Check (`scripts/check_camera_lot_share.py`): 5.3% of errand trips
  end inside a camera-covered lot (95% interval 4.0–6.7% across 50 seeds), vs
  6.6% of errand places lying inside one. The gap comes from the category mix
  the templates actually produce. Evening outings are food/leisure, which
  raises food to 34% and leisure to 16% of errands, and leisure has no places
  in camera lots while retail has the most. That realized mix alone predicts
  5.6%. So it isn't a bias against camera lots.

## Sensor noise model

`platetrail.sim.noise` turns the matcher's captures into a noisy read log.
For each true pass, in order:

1. **Downtime:** each camera has its own outage windows over the simulation
   period. A pass inside an outage is dropped, not delayed.
2. **Missed read:** the pass is dropped with probability `p_miss`.
3. **Read:** each plate character that has a look-alike (`0/O/D/Q`, `1/I/7`,
   `2/Z`, `5/S`, `6/G`, `8/B`) is swapped with probability `p_char_misread`.
   The timestamp gets Gaussian jitter.

Every read keeps `pass_id`, the link back to its true pass, so later analysis
can measure how misreads break linking reads to one driver. All randomness
comes from `seed`, with separate streams per camera (outages) and per pass
(noise). The same seed always gives the same read log, and changing one
setting doesn't reshuffle the others.

| Setting | Default | Status |
|---|---|---|
| `p_miss` | 0.05 | **Assumption**, not measured |
| `p_char_misread` | 0.01 per confusable character (~3–4% of reads) | **Assumption**, not measured |
| look-alike table | see above | **Assumption** (visual similarity), not a measured confusion matrix |
| `downtime_rate_per_week` | 0.25 outages per camera (Poisson) | **Assumption**, not measured |
| `downtime_mean_hours` | 12 (exponential); ~1.8% downtime | **Assumption**, not measured |
| `jitter_sd_s` | 2 s (Gaussian) | **Assumption**, not measured |

I found no published per-read rate that maps directly onto these settings.
For context only: Potts (2018) reports that in a Vallejo, CA randomized trial,
"35 percent of all hits were misreads for the mobile readers, with a similar
number (37 percent) for the fixed readers"
([*Research in Brief: Assessing the Effectiveness of Automatic License Plate Readers*, The Police Chief, IACP](https://www.theiacp.org/sites/default/files/2018-08/March%202018%20RIB.pdf)).
That figure is a share of hotlist **alerts**, a sample skewed toward misreads,
not a share of all reads, so it isn't used as a default. Results should be
reported across a range of these settings.

**Synthetic plates** are random strings in the current NJ passenger shape
(`A12BCD`: letter, two digits, three letters), so misreads exercise a
realistic letter/digit mix. That shape is still issued in NJ
([Wikipedia](https://en.wikipedia.org/wiki/Vehicle_registration_plates_of_New_Jersey)
lists `A12-BCD` as the passenger format since July 2010). NJ MVC publishes no
list of unused layouts; its
[Advisory 2010-005](https://nj.gov/mvc/pdf/about/advisories/advisory-2010-005.pdf)
says passenger plates can begin with any letter, including S, T and X. So no
string in this shape is guaranteed unissued. Instead, every synthetic plate
carries the made-up jurisdiction code **`ZZ`** (`SYNTHETIC_STATE`; not a USPS
or ISO 3166-2:US code). A plate's identity is `(state, plate)`, which can't
collide with a real registration. A read with the wrong state counts as a
misread, ready for a future wrong-state error type.

Every read may also pass through `extra_read_errors`, a hook for error types
not modelled yet. Each error type draws from its own random stream, so adding
one changes only what that error does and leaves every other read and drop
identical.

## Stored runs (read log)

`platetrail.sim.runner` simulates one synthetic driver for N weeks and stores
everything in PostGIS in one transaction:

```bash
.venv/bin/python -m platetrail.sim.runner --template commuter --weeks 4 --seed 1 [--zero-noise]
```

| Table | Contents |
|---|---|
| `runs` | generator, weeks, start date, seed, synthetic plate (`ZZ` state), match and noise config (JSON), anchors, summary counts |
| `trips` | ground truth: purpose, origin and destination, planned vs actual departure, arrival, length, route geometry |
| `camera_passes` | every camera the route passed: time, event (road / arrival / departure), travel bearing, matcher decision and reason, noise outcome (`read` / `missed` / `downtime`) |
| `reads` | the noisy read log: recorded time and plate, `misread` flag, jitter; `pass_id` links each read to its true pass |
| `camera_outages` | the outage windows drawn for the run |

Times are local New Jersey wall-clock time, stored as `timestamp` without
time zone. Camera references store the id and the stable OSM id
(`camera_label`) with no foreign key, so rerunning the camera ETL (which
renumbers cameras) doesn't delete stored runs. Runs are reproducible: the
same request on the same data stores the same run. `SimulationRunner` is the
seam for a future Celery-backed runner; `LocalRunner` runs synchronously.

## Frontend

Next.js + MapLibre on `:3000` (OpenFreeMap dark basemap, OpenStreetMap
data, no API key). Pick a stored run, then switch between:

- **What the cameras saw:** only the read log as recorded. Each read is a
  mark at its camera (size = count), joined in time order by a dashed
  "implied sequence": everything an analyst would have. The table lists
  each read with recorded time, camera and plate (`ZZ` state shown).
- **What actually happened:** the true routes and every camera passed, as
  rings: read, captured but lost (missed or camera down), or skipped for
  wrong direction. The table lists every pass with its outcome, including
  misreads.

Day chips filter both views; clicking a table row flies to that camera.

Three tabs:

- **One driver:** the views above, plus the naive baseline card and a
  step-by-step reveal of the inference engine (1 reads, 2 places: estimated
  home and work areas with radius and confidence, 3 schedule: regular passes
  ringed on the map, 4 anomalies: one-off reads in red), with plain-language
  conclusions.
- **Population & policy:** pick a stored population. A line chart shows
  unicity by number of known sightings for crowds of 100, 300 and N cars.
  Two bar charts compare policies (two-point unicity, and homes placed within
  1 km as a share of all drivers). Click a bar for detail; there is also a table view.
- **Your week:** place home (and optionally work) on the map, set workdays,
  leave times, errands and weeks, and see the same driver views for a
  simulated version of that week. Nothing is stored (`POST /yourweek`).
Cameras are arrows pointing the way they face: bone = public road, blue =
private lot, orange = service street; hollow circle = no direction.

MapLibre GL 6 loads its web worker from a path that Next.js bundling
breaks, so `npm run build`/`dev` copies the worker into `public/` first
(`scripts/copy-maplibre-worker.mjs`).

## Naive home/work baseline

`platetrail.inference.naive` guesses a driver's home and work from the read
log alone. It is a **naive baseline for comparison, not the planned
inference engine**:

- home = the camera that most often records a day's first or last read;
- work = the camera that most often records the read before the day's
  longest gap;
- no guess unless at least 2 days have 2 or more reads.

`GET /runs/{id}` returns the guess with its distance error against the true
anchors (`naive_guess`). The UI shows it as a card and as HOME? / WORK?
markers, plus the true anchors and error lines in "what actually happened".
Population results are finding F3 (`scripts/naive_guess_population.py`).

## API

FastAPI on `:8000` (interactive docs at `/docs`):

| Endpoint | Returns |
|---|---|
| `GET /health` | status and PostGIS version |
| `GET /cameras[?rays=true]` | cameras as GeoJSON: kind (`public_road` / `private_lot` / `service_road`), directions, ambiguity flags, lot info; optional 30 m direction rays |
| `POST /simulate` | simulates and stores one driver. Body: `template`, `weeks` (1–8), `start` (a Monday), `seed`, `zero_noise`, `match` {`tolerance_deg`, `facing`, `undirected`, `ambiguous_direction`, `lot_entrance`}, `noise` {`p_miss`, `p_char_misread`, `downtime_rate_per_week`, `downtime_mean_hours`, `jitter_sd_s`}. Returns `run_id`, summary, plate. |
| `POST /jobs/simulate` | the same request as `/simulate`, queued on the Celery worker; returns `job_id` (or the cached run if an identical request already ran on the same camera data) |
| `GET /jobs/{id}` | `state` (`PENDING` / `STARTED` / `PROGRESS` / `SUCCESS` / `FAILURE`), `progress` {stage, done, total}, `run_id` |
| `GET /runs` | stored runs, newest first; `stale` = cameras were reloaded since the run |
| `GET /runs/{id}` | the run (config, anchors, summary, `stale`), the naive home/work guess and the inference engine result (`inference`) with distance errors, trips as GeoJSON, every camera pass (matcher decision and noise outcome), the read log (`plate_state` + `plate`, recorded and true time), outages |
| `POST /jobs/population` | queues a population run: `drivers` (2–2,000), `weeks`, `seed`, `generator`, `extra_cameras`; returns `job_id` |
| `GET /populations` | stored populations with summary and `stale` |
| `GET /populations/{id}` | one population: config, summary, per-persona counts |
| `GET /populations/{id}/unicity?p=1,2,4&size=100,1000&resolution=60` | unicity rows {size, p, eligible_share, unique_share}; cached in Redis |
| `GET /populations/{id}/policies` | policy comparison rows (retention, rounding, windows, aggregate-only); cached in Redis |
| `POST /yourweek` | "your week" simulation (home/work points, workdays, leave times, errands, weeks). Returns a run-shaped result with `stored: false`. Nothing is written to the database or the route cache. |

`/simulate` runs synchronously in the API process. `/jobs/simulate` runs on
the Celery worker (Redis broker), which the UI uses, with progress by stage
and trip. Each process loads the road graph and cameras once, on first use
(about 5–10 s).

**Caching (Redis):**
- **routes** are cached by (origin point, destination point) with a graph
  fingerprint. Routes don't depend on departure time, so repeated commutes
  and population runs reuse them.
- **runs** are cached by (request, camera load time). Simulations are
  deterministic, so an identical request returns the stored run.

Without `REDIS_URL` (tests, CI), jobs run in-process and the cache lives in
memory.

## Known limitations

- **Misreads are look-alike swaps only.** Real ALPR errors also include
  dropped or extra characters, wrong state, and partial reads. The current
  model therefore likely **understates** how often misreads break linking
  reads to one driver. The `extra_read_errors` hook in `platetrail.sim.noise`
  is where these will go.
- **Noise defaults are assumptions.** See the table above; none comes from a
  published per-read rate.
- **Free-flow routing.** No traffic model, so departure time only stamps
  timestamps.
- **Private (`access=private`) service roads are excluded**, including 92
  ways in Raritan Center.
- **Facing convention is unverified.** `rear_plate` is a default assumption;
  report results under both settings.
