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
| `lot_entrance` | `nearest` | A vehicle uses one lot entrance, so only the lot camera nearest where the route meets the lot sees the event. `all` lets every camera at the lot see it (an upper bound). |

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
