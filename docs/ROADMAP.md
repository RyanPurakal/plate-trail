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
- [ ] Move the remaining NJ town names out of core code into the region file:
      `routines/templates.py` and `routines/nhts.py` (student home/school town),
      `sim/runner.py` and `population.py` (`scenario_town` default),
      `api/schemas.py` comment, `realdata/validate.py` message.
- [ ] Camera list from a file: a `FileCameraLoader` that reads GeoJSON or CSV
      (lon, lat, optional bearing/direction) so any fixed sensor network can be
      used without OSM. Select the loader per region.
- [ ] Map defaults from the region: frontend initial center/zoom and bounds
      served by an API endpoint (`GET /region`) instead of hard-coded values.
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
- [ ] Tests: an end-to-end smoke test on a tiny synthetic region (fixture graph
      + fixture cameras) that does not need network access.
- [ ] Performance: profile the population runner after the C++ router and note
      the next bottleneck in `docs/technical_reference.md`.

## Notes

- 2026-10-20: roadmap created; region config landed. The `.nj` set name in the
  Overpass camera query is kept on purpose (cache keys are the query text).
