# Roadmap

A prioritized checklist for ongoing work. Each item should fit in one small,
reviewable change. Check items off as they land and add notes or new items
underneath.

Three directions:

1. **Keep improving the app**: correctness, tests, performance, UX, docs.
2. **Make it reusable**: any city or region, any fixed sensor network loaded
   from a file. The Edison and New Brunswick study stays as one example dataset.
3. **Keep it neutral**: educational, evidence-based wording framed as
   privacy-engineering and data-retention analysis. No features that track,
   identify or de-anonymize real people, and no stored real location data.

## Reusability (configurable region and sensors)

- [x] Region config: study-area towns, OSM boundary relations, parent ISO 3166-2
      code and buffer in a JSON file (`backend/platetrail/regions/`), selected
      with `PLATETRAIL_REGION`. Used by the camera ETL, road graph and places.
      The default region's Overpass query text and graph cache file name are
      unchanged, so existing caches stay valid.
- [x] Move the remaining NJ town names out of core code into the region file:
      `student_town`, `student_home_share` and `scenario_town` are optional
      region keys used by both routine generators and the density scenario.
      Default-region routines are byte-identical to before (checked by hashing
      template and NHTS fixture routines over many seeds).
- [ ] `sim/scenarios.py` module docstring still describes the NJ camera
      approval; reword neutrally (covered by the vendor-wording item below).
- [x] Camera list from a file: `FileCameraLoader` reads GeoJSON Points or CSV
      (lon, lat, optional id/town/direction). The region's optional
      `camera_sources` list picks the loaders (`osm`, `file`) in priority
      order; default is OSM only, so the NJ ETL is unchanged. Documented in
      `docs/camera_sources.md`.
- [x] Map defaults from the region: optional `map` block in the region file
      (`center` + `zoom` and/or `bounds`), served by `GET /region`. The
      frontend applies it on load unless a run has already been fitted; the
      old NJ center/zoom stay as a fallback when the API omits it.
- [ ] Frontend: show the region name and town labels from `GET /region` in the
      header and anywhere the UI still names Edison or New Brunswick.
- [ ] Region bounding box option: allow a plain bbox instead of OSM boundary
      relations for areas without clean municipal boundaries.
- [ ] Setup guide `docs/new_region.md`: step-by-step for a new area, with a
      small worked example region file.
- [ ] Generalize the density scenario (`sim/scenarios.py`): synthetic sensors
      placed in any configured town, with neutral wording.
- [ ] Document which parts depend on US data (NHTS trip diaries) and what an
      alternative routine source would need to provide.

## Rescope and neutral framing

- [ ] Wording pass across README, docs and UI: describe the project as a
      location-sensor data-retention and data-minimization simulator, with the
      NJ ALPR study as the example. Keep data-source credits factual.
- [ ] Rename vendor-specific wording in core code comments (e.g. in
      `sim/scenarios.py`) to neutral terms ("additional cameras").
- [ ] Generic "sensor" terminology in new code and API fields where it does
      not break existing endpoints (aliases first, renames later).

## App quality

- [ ] Frontend: run `npm run lint` in CI if not already, fix any warnings.
- [ ] API: validate `extra_cameras` and other scenario inputs against the
      active region.
- [ ] Sensor files: optionally assign `town` by point-in-boundary when a
      multi-town region's file has no town column (needs boundaries without
      OSM, so pairs well with the bbox item).
- [ ] Tests: an end-to-end smoke test on a tiny synthetic region (fixture graph
      + fixture cameras) that does not need network access.
- [ ] Performance: profile the population runner after the C++ router and note
      the next bottleneck in `docs/technical_reference.md`.

## Notes

- 2026-10-20: roadmap created; region config landed. The `.nj` set name in the
  Overpass camera query is kept on purpose (cache keys are the query text).
- 2026-10-20: town roles moved to the region file. A region with no
  `student_town` draws student homes and schools from the whole area.
- 2026-10-21: file sensor loader landed. File sources may set a custom
  `source` name (needed to list two files); the OSM source stays "osm".
- 2026-10-21: `GET /region` and region map defaults landed. `get_region()` is
  cached per process, so changing `PLATETRAIL_REGION` needs an API restart.
