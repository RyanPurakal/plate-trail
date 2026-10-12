# Plate Trail

A privacy-audit tool that measures what a history of automated license plate
reader (ALPR) reads could reveal about a driver, using only public camera
locations and synthetic drivers. See
[the proposal](KTP-Capstone-Proposal-Plate-Trail.md).

Setup instructions, ethics statement, and build status are added as the
project is built.

## Quick start (development)

Requires Docker. PostGIS is published on host port **5434** (override with
`PLATETRAIL_DB_PORT`) to avoid clashing with other local Postgres instances.

```bash
docker compose up -d --build      # db :5434, api :8000, web :3000
curl localhost:8000/health
```

Backend tests locally (Python 3.12):

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker compose up -d db
DATABASE_URL=postgresql+psycopg://platetrail:platetrail@localhost:5434/platetrail .venv/bin/pytest
```

Tests marked `db` are skipped when `DATABASE_URL` is unset. CI always runs them
against a PostGIS service container.

## Camera ETL

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

Downloads the OSMnx `drive` graph for Edison + New Brunswick, buffered by
2 km, and caches it as GraphML under `data/graphs/`. The first download takes
several minutes. Edges are stored in `road_edges`. Each camera is snapped to
its nearest edge within 50 m. On a two-way road it gets one `camera_edges` row
per direction, with that direction's true-north bearing taken at the snap
point. The summary lists dropped cameras, snap distances, close camera pairs,
and cameras whose direction is closer to perpendicular than parallel to their
road. Rerun this after the camera ETL, because reloading cameras clears the
snaps.

### Camera kinds

- **public_road**: snapped to a drive-network edge, as above.
- **private_lot**: the camera watches a parking/retail lot or its driveway,
  not a public road. A camera counts as private_lot if it is more than 50 m
  from the drive network, or if it faces closer to perpendicular than
  parallel to its road with a parallel service road within 10 m. It is
  attached to its lot polygon (retail > commercial > industrial > parking >
  shop) and gets no public-road snap. Each of its directions is recorded as
  pointing `into_lot` or `toward_road`. There are 10 such cameras, including
  4 at Menlo Park Mall and 2 in Raritan Center.
- **snap_ambiguous** (flag): a public-road camera still more than 45° off its
  road axis after direction-aware snapping, so it is unclear which street it
  watches. It keeps the nearest snap (3 cameras).
- **direction_ambiguous** (flag): a camera whose direction tags disagree. The
  alternate reading is kept in `alt_directions_deg` (1 camera, node
  13271071475).

Divided roads: when a camera snaps to one carriageway of a divided road, the
opposite carriageway (one-way, parallel, opposite travel, within 30 m) is
snapped too. Without this, a camera beside Albany St's westbound carriageway
never registered eastbound traffic (5 cameras affected).

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
| `tolerance_deg` | 45 | Maximum difference between the travel bearing and the captured bearing |
| `undirected` | `best` | Cameras without a direction capture both ways (`best`) or neither (`worst`) |
| `ambiguous_direction` | `primary` | For cameras with disagreeing tags, use `direction` (`primary`) or the other tag (`alternate`) |
| `lot_entrance` | `access_road` | A vehicle uses one lot entrance. A lot camera sees an arrival or departure only if the trip's lot-side edge (the edge the place attaches to) is the camera's access road, the public road nearest the camera. `nearest` instead picks the lot camera nearest the route's end; `all` lets every camera at the lot see it (an upper bound). |

The rear-plate default is an assumption, not something established from the
data. OSM documents `direction` as the way a camera faces, but it doesn't
say which plate the camera reads. Results should be reported under both
settings.

Private-lot cameras see arrivals and departures at their lot. Under
`rear_plate`, an `into_lot` direction captures arrivals and a `toward_road`
direction captures departures; `oncoming` flips both.

```bash
.venv/bin/python scripts/sample_trips.py [--facing oncoming] [--tolerance 30] [--lot-entrance all]
```

Trip endpoints attach to the **nearest point on an edge**, not the nearest
intersection. The route starts and ends with partial edges, and a camera
counts only if it is on the part actually driven.

## Routine generator

`platetrail.routines` plans each synthetic driver's trips. It is behind a
`RoutineGenerator` interface so an NHTS-based generator (stubbed in
`routines/nhts.py`) can replace it without changing the simulation.

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
- **Places** (1,310) are OSM shops, food, services, leisure, worship,
  workplaces, university and hospitals inside the two towns. 207 are more
  than 100 m from the drive network (mostly inside Raritan Center and large
  retail lots) and attach to the nearest edge point. 6 are more than 500 m
  away and are excluded.
- **Errands** pick a category from a fixed mix (grocery 28%, retail 22%,
  food 25%, services 15%, leisure 10%; **assumption**), then a place in it,
  weighted by `exp(-distance / 4 km)` from the trip's origin. Drivers reuse a
  "usual" place per category 60% of the time. **Camera locations are never
  used.** In a 300-driver run, 5.5% of errand trips end inside a camera-covered
  lot, vs 7.3% of errand places lying inside one, so there is no bias toward
  camera lots.

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
- **Private service roads aren't in the drive graph.** Places inside Raritan
  Center and big retail lots attach to the nearest public edge, up to 500 m
  away, and the drive through the lot isn't modelled.
- **One entrance per place.** A place always uses the public road nearest to
  it, so a lot camera whose driveway meets a road no shop is nearest to (two
  Menlo Park Mall cameras) never fires under `access_road`.
- **Facing convention is unverified.** `rear_plate` is a default assumption;
  report results under both settings.

## Findings

Results recorded as the project is built are in
[docs/findings.md](docs/findings.md): F1 (one commuter's week is about 10
reads, over 90% from one camera) and F2 (across 300 template drivers, median
6 reads per week and 11% of drivers never read).

```bash
.venv/bin/python scripts/demo_week.py [--seed 0] [--runs 1000]
```
