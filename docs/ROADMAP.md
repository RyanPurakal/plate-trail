# Roadmap

A prioritized checklist for ongoing work. Each item should fit in one small,
reviewable change. Check items off as they land and add notes or new items
underneath.

## Product direction: location-privacy check-up (from 2026-10-21)

Plate Trail is becoming a practical tool people come back to: a
location-privacy check-up for any area and for your own routes. It is not a
game (no scores, streaks, levels, leaderboards or guessing challenges).
Wording stays neutral and educational, with data-source credits only. No
camera-avoidance routing, nothing about specific real vehicles or plates,
nothing that helps track or identify real people, and no real location data
stored server-side. The Edison and New Brunswick study stays as the
"Example study".

### 1. Explore any area

- [x] Backend `GET /area?bbox=w,s,e,n`: public fixed sensors from
      OpenStreetMap (`surveillance:type=ALPR`) for any box up to 0.5 deg a side,
      snapped outward to a 0.01 deg grid so nearby requests share a disk cache
      (refetched after 7 days). Returns GeoJSON plus a summary (sensor count,
      how many have a known direction, sources with fetch time and latest OSM
      edit). No region file needed.
- [x] Include configured file sensors (region `camera_sources` of type `file`)
      that fall in the box, credited by source name.
- [x] Frontend "Explore" view: map + area summary card from `GET /area`, area
      in the URL (`?bbox=...`), good empty and error states. "Explore an area"
      tab with its own map (`AreaMap`): explore the current view (shrunk around
      its centre if over the size limit), the snapped box goes in the URL, and
      a `?bbox=` link opens straight into it. Clicking a sensor shows source,
      direction and last OSM edit. The default tab is still "One driver"
      until the check-up becomes the home page (section 5).
- [ ] Place search: geocode a town or address to a box (Nominatim, with
      attribution and rate limit, cached server-side by query text only).
- [ ] Draw a box on the map to explore it.
- [ ] Main-road coverage in the summary: share of primary/secondary road length
      within a short distance of a sensor (needs a road fetch for the box).
- [ ] Sensor detail panel: source, direction if known, last edited in OSM.

### 2. My routes, kept on your device

- [ ] Route storage in localStorage only (name, start, end); add/rename/delete.
- [ ] Add a route by clicking start and end on the map.
- [ ] `POST /route/check`: route + sensors passed + read timeline for one route;
      compute-only, never stored, cached or logged (same rule as `/yourweek`).
- [ ] Route timeline: where reads would happen along the drive; click a step
      to show it on the map.
- [ ] What a 7-day / 30-day / 1-year read history could suggest for a route
      (reuse the simulator and inference engine), in plain language.

### 3. What changed since your last visit

- [ ] Local snapshot (localStorage) of sensor ids for saved areas and routes,
      with the fetch date.
- [ ] "Since your last visit" panel: new or removed sensors on saved routes or
      areas, and data-update dates.

### 4. Compare and drill down

- [ ] Side-by-side comparison of two areas or two routes.
- [ ] Retention-period slider that updates route results live.

### 5. Learn more panels

- [ ] Short neutral explainers: what fixed sensors record, how retention
      length changes what can be inferred, the unicity finding. Link them from
      where they are relevant.
- [ ] Move the NJ study (map run, log table, population view, your week) to an
      "Example study" section; the check-up becomes the home page.
- [ ] Wording pass across README, docs and UI: describe the project as a
      location-privacy check-up, with the NJ ALPR study as the example. The
      masthead kicker still says "ALPR privacy audit". Keep data-source
      credits factual.

### 6. Polish

- [ ] Mobile layout, keyboard and screen-reader access for the new views.
- [ ] Fast loading: lazy-load the example study; skeletons for the area card.
- [ ] Docker setup still works with the new views (data dir for the area
      cache mounted).

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
- [x] Frontend: show the region name and town labels from `GET /region` in the
      header and anywhere the UI still names Edison or New Brunswick. The lede,
      hypothetical-camera tooltip, map popup and population notes use
      `name`/`scenario_town`; NJ-only published figures (92 approved cameras,
      the agency's 30-day read count) show only for the example region.
- [ ] Optional region `notes` (or similar) so dataset-specific comparison
      figures live in the region file instead of being gated by region id in
      `PopulationView.tsx`.
- [ ] Region bounding box option: allow a plain bbox instead of OSM boundary
      relations for areas without clean municipal boundaries.
- [ ] Setup guide `docs/new_region.md`: step-by-step for a new area, with a
      small worked example region file.
- [ ] Generalize the density scenario (`sim/scenarios.py`): synthetic sensors
      placed in any configured town, with neutral wording.
- [ ] Document which parts depend on US data (NHTS trip diaries) and what an
      alternative routine source would need to provide.

## Neutral wording in code

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
- 2026-10-21: frontend labels come from `GET /region`; fallbacks in
  `lib/api.ts` keep the NJ text if the API is unreachable. The masthead kicker
  still says "ALPR privacy audit" (left for the wording pass).
- 2026-10-21: product direction changed to a location-privacy check-up tool;
  roadmap restructured with the new direction on top. The older "Rescope"
  wording item moved under Learn more. `GET /area` landed: Overpass bbox
  query with `out center meta` (per-sensor last-edit time, no editor names
  exposed); cache in `data/raw/overpass_areas`.
- 2026-10-21: `GET /area` now adds the active region's file sensors inside
  the snapped box, ids `<source>:<row id>`, with one summary source entry per
  file (`fetched_at` is the file's modified time, no license/url). Not
  deduplicated against OSM; a missing or malformed file is logged and
  skipped. Extra file columns are not returned.
