# Setting up a new region

The check-up (Explore, My routes, Compare) works for any area without a
region file: `GET /area` fetches sensors and main roads for whatever box you
look at, and route checks download roads around a route on demand. A region
file is only needed to run the **example study** (one driver, population and
policy, your week) somewhere else, or to add your own sensor list to Explore.

This guide walks through a worked example in
[`docs/examples/new_region/`](examples/new_region/): a single box-shaped
town around Princeton, NJ, with OpenStreetMap sensors plus a small file of
hypothetical sensor placements. The file sensors are made up for the
example; they are not real camera locations.

## 1. Write the region file

A region is a JSON file. The fields are documented in
`backend/platetrail/region.py`; the ones you need first are:

| Field | Required | What it does |
|---|---|---|
| `id` | yes | Short id; also names the road-graph cache file. |
| `name` | yes | Shown in the page header and labels. |
| `parent_iso3166_2` | yes | ISO 3166-2 code of the state or province (e.g. `US-NJ`), used to find towns by name in OpenStreetMap. |
| `towns` | yes | One or more towns, each an OSM boundary relation or a plain box (below). Labels must be unique. |
| `buffer_m` | no (2000) | How far beyond the towns the road graph reaches, in meters. |
| `camera_sources` | no (`[{"type": "osm"}]`) | Where sensors come from, in priority order for dedupe. |
| `map` | no | Initial map view: `bounds` `[w, s, e, n]`, or `center` `[lon, lat]` with `zoom`. |
| `student_town`, `student_home_share`, `scenario_town` | no | Town roles for student routines and the density scenario; default to the whole region and the first town. |
| `notes` | no | Short dataset sentences shown next to results: `unlisted_sensors`, `read_volume`. |

**Towns.** Use an OSM boundary relation when the town has a clean
municipal boundary:

```json
{"label": "Edison", "osm_name": "Edison", "osm_relation": 171019, "admin_level": 8}
```

Find the relation id by searching the town on
[openstreetmap.org](https://www.openstreetmap.org) and opening its boundary
relation; `osm_name` is that relation's `name` tag. Where boundaries are
missing or awkward, use a box instead (at most 0.5 deg a side):

```json
{"label": "Princeton", "bbox": [-74.69, 40.33, -74.62, 40.38]}
```

The two kinds can be mixed in one region. The worked example uses one box
town, so it needs no relation lookup:

```json
{
  "id": "example_princeton_box",
  "name": "Princeton, New Jersey (worked example)",
  "parent_iso3166_2": "US-NJ",
  "buffer_m": 1500,
  "towns": [
    {"label": "Princeton", "bbox": [-74.69, 40.33, -74.62, 40.38]}
  ],
  "camera_sources": [
    {"type": "file", "path": "example_sensors.csv", "source": "example-hypothetical"},
    {"type": "osm"}
  ],
  "map": {"bounds": [-74.69, 40.33, -74.62, 40.38]}
}
```

## 2. Add a sensor file (optional)

With only `{"type": "osm"}`, sensors come from OpenStreetMap's
`surveillance:type=ALPR` nodes. To add a list from elsewhere (a public
planning document, a survey, or a hypothetical placement), point a `file`
source at a CSV or GeoJSON file. A relative path is resolved against the
region file's folder. The example's CSV:

```csv
id,lon,lat,town,direction,note
ex-1,-74.6590,40.3500,Princeton,NE,hypothetical placement for the worked example
ex-2,-74.6672,40.3573,Princeton,90;270,hypothetical placement for the worked example
ex-3,-74.6455,40.3445,Princeton,,hypothetical placement for the worked example
```

`town` must be one of the region's labels. It may be left out when the
region has one town, or when the point lies inside exactly one town given
as a box. `direction` takes the OSM tag formats (`90`, `90;270`,
`NE`, `45-135`) or can be empty. Other columns are kept as tags. Give each
file a distinct `source` name; it is the credit shown in Explore. Full
format notes are in [camera_sources.md](camera_sources.md#sensors-from-a-file).

## 3. Check the file

The region is validated when it loads, and errors name the field:

```bash
cd backend
PLATETRAIL_REGION=../docs/examples/new_region/example_region.json \
  python -c "from platetrail.region import get_region; r = get_region(); print(r.name, r.labels)"
```

`backend/tests/test_region.py` loads the worked example the same way, so it
stays valid as the format changes.

## 4. Build the data

`PLATETRAIL_REGION` takes a bundled id (a file in
`backend/platetrail/regions/`) or a path ending in `.json`. One database
holds one region at a time: the camera step replaces the camera table.

Locally:

```bash
cd backend
export PLATETRAIL_REGION=../docs/examples/new_region/example_region.json
python -m platetrail.etl.run_etl          # sensors: file + OpenStreetMap
python -m platetrail.roads.run_roads      # road graph and snapping
python -m platetrail.routines.places      # towns and candidate places
```

With Docker, put the region folder under `data/` (mounted at `/data`) and
pass the in-container path:

```bash
mkdir -p data/regions && cp -r docs/examples/new_region data/regions/
export PLATETRAIL_REGION=/data/regions/new_region/example_region.json
docker compose up -d --build
docker compose exec api python -m platetrail.etl.run_etl
docker compose exec api python -m platetrail.roads.run_roads
docker compose exec api python -m platetrail.routines.places
docker compose restart api worker
```

Run the steps in that order: reloading sensors clears their snaps, so
`run_roads` must follow `run_etl`. The road graph is cached as
`data/graphs/study_area_drive_service_<id>.graphml`, so switching back to the NJ
study reuses its own cache. Then run a population as in the README
(`python -m platetrail.population --drivers 1000 --weeks 1`).

## 5. Look at it

Open the page. The header and labels use the region's `name` and town
labels, the study map opens on `map`, and Explore lists file sensors that
fall in the explored box alongside OpenStreetMap, each credited by source.

## What still assumes the US

Routines come from the US National Household Travel Survey (NHTS 2022) trip
diaries, so simulated drivers keep US travel patterns wherever the region
is. The template generator (`--generator template`) avoids NHTS, but its
times and shares are hand-written assumptions. Places come from OpenStreetMap and work
anywhere it has shops, schools and workplaces mapped. The Explore and My routes views
do not use NHTS at all. [routine_sources.md](routine_sources.md) lists what
depends on it and what another routine source would need to provide.
