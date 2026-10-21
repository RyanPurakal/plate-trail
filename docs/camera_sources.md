# Camera sources

Plate Trail uses only public camera data. This note records what each source
offers, how the sources agree, and how the unknown future cameras are
modelled.

## Sources

| Source | What it provides | Used how |
|---|---|---|
| **OpenStreetMap** (Overpass) | Camera locations, facing direction, manufacturer | The camera table: 56 cameras (Edison 41, New Brunswick 15) |
| **DeFlock** | A crowdsourced ALPR map | **Same data as OSM.** DeFlock stores every camera directly in OpenStreetMap ([DeFlock Maps](https://maps.deflock.org/), [deflock-kml-export](https://github.com/daTechGuy/deflock-kml-export)), so a separate loader would only reload the same nodes. |
| **Edison PD Flock transparency portal** | Counts and usage statistics, **no locations** | Count cross-check |
| **New Brunswick** | No Flock transparency portal found; a news report gives a count | Count cross-check |

The loader interface (`platetrail.etl.loaders.base.CameraLoader`) and
cross-source dedupe are in place for any future source that does publish
locations.

## Sensors from a file

Any fixed sensor network can be loaded from a local GeoJSON or CSV file
instead of (or alongside) OpenStreetMap. List the sources in the region file
with `camera_sources`, in source-priority order for dedupe:

```json
"camera_sources": [
  {"type": "file", "path": "my_sensors.csv", "source": "survey"},
  {"type": "osm"}
]
```

A relative `path` is resolved against the region file's folder. The default,
used by the Edison and New Brunswick region, is `[{"type": "osm"}]`.

- **GeoJSON**: a FeatureCollection of Point features. Optional properties
  `id`, `town` (a region town label; required when the region has more than
  one town) and `direction` (same formats as the OSM tag: `90`, `90;270`,
  `NE`, `45-135`).
- **CSV**: a header row with `lon` and `lat`, plus the same optional `id`,
  `town` and `direction` columns.

Other properties or columns are kept as tags. Rows with bad coordinates, an
unknown town or a non-Point geometry stop the ETL with an error rather than
being skipped. See `platetrail.etl.loaders.file`.

## Count cross-check

`python -m platetrail.etl.cross_check` compares counts. Agency figures live in
`backend/platetrail/etl/data/agency_counts.json`, with sources and dates.

| Town | OSM total | OSM Flock (public road / lot or service) | Agency figure |
|---|---|---|---|
| Edison | 41 | 40 (31 / 9) | **24** cameras operated by Edison PD (portal, last updated 2026-10-12); **92** additional approved (proposal) |
| New Brunswick | 15 | 10 (10 / 0) | **11** Flock cameras (news report) |

**Reading the gap.** Agency sources publish no locations, so cameras can't be
matched one to one.
- **Edison:** OSM shows more Flock cameras than the PD operates. The 9 lot
  and service-street cameras are likely privately owned (retail) cameras
  that the PD portal wouldn't count. Even the 31 public-road cameras exceed
  24, which points to cameras run by other agencies (county prosecutor,
  sheriff) or to stale mapping.
- **New Brunswick:** OSM's 10 Flock cameras are close to the reported 11.
  OSM also has 5 other-vendor cameras, which are attributed in public
  records to the county prosecutor, sheriff and Rutgers PD.

Agreement at the level of counts is therefore reasonable for New Brunswick
and over-counted for Edison PD specifically. Results are reported on the
OSM network as mapped.

## Hypothetical density scenario: Edison's 92 approved cameras

The locations of the 92 newly approved Edison cameras are not public, so
every "+92" result uses a **hypothetical, simulated placement**: `platetrail.sim.scenarios` adds *N* synthetic cameras at simulation time
(`extra_cameras` in `POST /simulate`, `--extra-cameras` on the runner CLI).

**Placement (assumption):**
- on Edison arterials (trunk, primary, secondary, tertiary), weighted by
  length;
- at least 300 m from every real and synthetic camera;
- each facing one travel direction, snapped to both directions of two-way
  roads like real cameras;
- seeded per run.

Synthetic cameras are stored with the run (`runs.scenario`), never in the
camera table. They show in the UI as lavender arrows labelled "hypothetical camera (simulated placement)".

**Effect on the demo driver** (4-week commuter, seed 18):

| Cameras | Camera passes | Captures | Reads | Distinct cameras read |
|---|---|---|---|---|
| OSM only (56) | 88 | 60 | 55 | 6 |
| OSM + 92 hypothetical | 492 | 332 | 308 | 20 |
