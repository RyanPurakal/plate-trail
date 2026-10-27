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
- [x] Place search: `POST /geocode` sends a town or address to Nominatim
      (identifying User-Agent, one request per second, attribution shown) and
      returns up to 5 matches, each with a box sized for `GET /area`. Search box
      and result list in the Explore sidebar; picking a match loads that area
      and only the box goes in the URL. Because a query can be a home address,
      it travels in the POST body (not the logged URL), the httpx request log
      line is filtered out, and the cache is in memory only (256 entries, 24 h)
      rather than on disk as first planned.
- [x] Draw a box on the map to explore it. "Draw a box" in the Explore
      sidebar switches the map to draw mode (press and drag with mouse or one
      finger; panning is paused, Esc or the button cancels). Drags under about
      200 m are ignored as clicks; a box over the size limit is shrunk around
      its centre, like the view.
- [x] Main-road coverage in the summary: share of main-road length
      (motorway, trunk, primary, secondary) within 100 m of a mapped sensor.
      Roads come from a second Overpass query for the snapped box (`out skel
      geom`), cached and refreshed like the sensors; measured in 20 m pieces
      clipped to the box. If roads can't be loaded, `main_roads` is null and
      the card just leaves the row out.
- [x] Sensor detail panel: clicking a sensor rings it on the map and opens a
      sidebar card (replacing the map popup) with direction as a compass word
      and bearing, location, source and licence, last OSM edit, data fetch or
      file date, a neutral note on what the direction does and does not say,
      and a link to the OSM object. Previous/Next and "Step through sensors"
      reach every sensor from the keyboard; the map eases to off-screen ones.

### 2. My routes, kept on your device

- [x] Route storage in localStorage only (name, start, end); add/rename/delete.
      `lib/routes.ts` keeps up to 20 routes under `platetrail.routes.v1`,
      points rounded to 4 decimals (about 10 m), malformed entries dropped on
      load; edits in another tab are picked up via the `storage` event. "My
      routes" card in the Explore sidebar with rename, two-step delete and
      "Remove all from this device"; a note says routes never leave the browser.
- [x] Add a route by clicking start and end on the map. "Add a route" puts
      the Explore map in placing mode (crosshair, Esc cancels); the two points
      and a dotted straight line are drawn until routing lands. Clicking a
      saved route shows it and fits the map if it is off screen.
- [x] `POST /route/check`: route + sensors passed + read timeline for one route;
      compute-only, never stored, cached or logged (same rule as `/yourweek`).
      Checked both ways by default (a sensor facing one direction of traffic
      may read the trip there but not the trip back); each step has the
      offset and distance from the start and whether, and why not, it would
      record. Uses the study region's road graph and cameras for now; ends
      more than 500 m from those roads get a 422 saying so.
- [x] Routing for any area: build a small drive graph for the route's box
      from Overpass (held in memory only, since the box follows the route)
      and match against `GET /area` sensors, so saved routes outside the
      study region can be checked too. `platetrail/routearea.py`: routes off
      the study roads fall back to a box around both ends (2 km padding,
      0.01 deg grid, at most 0.3 deg a side, about 25 km); roads via OSMnx
      with its disk cache switched off, sensors snapped with the study
      snapping rules. A fresh `/area` cache entry is read but never written
      for a route box. Networks are kept in memory (4, for an hour) so the
      return leg and re-checks are quick. A first check of a new area can
      take a while (the road download); the frontend should say so.
- [x] Frontend: "Check this route" on each saved route calls
      `/route/check` and draws the driven route; friendly message for routes
      outside the covered network. The shown route gets a "Check this route"
      button; results (per direction: km and minutes by road, sensors passed,
      passes that would record the trip) are held in page memory only, keyed
      by route id, and dropped on reload or delete. The map draws the drive
      there (solid) and back (fainter) in place of the straight line, rings
      each sensor passed (amber if it would record either way, grey if not)
      and fits to the route. A loading note says a first check outside the
      study area downloads roads; 422s read "This route can't be checked: ...".
- [x] Route timeline: where reads would happen along the drive; click a step
      to show it on the map. Each checked direction lists Leave, every sensor
      passed (minutes:seconds from leaving, road, km in, "Would record" or
      "Passes, not recorded" with the reason in plain words) and Arrive.
      Clicking a step rings that sensor on the map and eases to it (zoom 14 or
      closer); clicking again clears it. Focus lives in page memory and resets
      when the route or its check changes.
- [x] `POST /route/history`: what a 7-day / 30-day / 1-year read history
      could suggest for a route, in plain language. `platetrail/routehistory.py`
      repeats the checked route on a schedule (weekdays, leave 08:00, back
      17:30 by default, +/-10 min), drops the simulator's default 5% of reads,
      and runs the inference engine on the reads kept for each period (all cut
      from one simulated year, so longer periods contain shorter ones). Each
      period returns reads, days, regular passes, where the car seems to stay
      overnight / during the day (radius, confidence, distance from the
      route's nearer end) and summary sentences. Compute-only like
      `/route/check` (same network fallback, shared `_checked_route` helper).
- [x] Frontend: "What a read history could suggest" for a checked route
      (7 days / 30 days / 1 year tabs or cards from `/route/history`, schedule
      inputs, the assumptions list), results in page memory only.
      `components/RouteHistory.tsx` appears under a successful check: day
      checkboxes (weekdays by default), leave and back times, then 7 days /
      30 days / 1 year buttons showing the summary sentences, trips, reads,
      days and sensors with reads, regular passes and suggested overnight /
      daytime stays (radius, confidence, distance from the saved start or
      end), with the assumptions in a collapsible list. Schedule and results
      reset when the route is hidden or another route is shown.

### 3. What changed since your last visit

- [x] Local snapshot (localStorage) of sensor ids for saved areas and routes,
      with the fetch date. `lib/snapshots.ts` keeps, under
      `platetrail.snapshots.v1`, the sorted sensor ids, per-source data dates
      (latest OSM edit, or a file's modified time) and the look time for each
      explored box (`area:<bbox>`, last 10 boxes) and each checked route
      (`route:<id>`; no coordinates, dropped when the route is deleted). Each
      area load or route check compares with the stored look and replaces it;
      the area card and route result show "Since your last look": sensors
      newly listed / no longer listed, updated sources, and buttons to show
      new area sensors. "Forget past looks at areas" clears area entries.
- [x] Save an area. `lib/areas.ts` keeps up to 20 named boxes (the snapped
      `GET /area` box, no search text) under `platetrail.areas.v1`, one per
      box; "My areas" card in the Explore sidebar with "Save this area",
      open, rename, two-step delete, "Remove all from this device" and the
      date of the last look at each. Saved areas' snapshots are exempt from
      the last-10 area pruning (`putSnapshot`'s `pinned` set).
- [x] "Since your last visit" panel: on return, re-check saved areas (and
      already-checked routes) without a click and list new or removed sensors
      and data-update dates in one panel at the top of Explore.
      `components/SinceLastVisit.tsx` re-checks saved areas one at a time when
      Explore opens (once per page load, after any `?bbox=` area has loaded),
      skipping areas looked at in the last hour, and lists each with what
      changed since its last look; clicking one opens it. Routes checked
      before (they have a stored look) are re-checked only on a button, since
      that uses the compute-only `/route/check`. Removed sensors are counted,
      not drawn.

### 4. Compare and drill down

- [x] Compare two saved areas side by side. `components/CompareAreas.tsx`
      in the Explore sidebar (under My areas): pick Area A and B from saved
      areas, "Compare" fetches both from `GET /area` and shows sensors mapped,
      area, per 100 km², direction known, main roads near a sensor, latest map
      edit and data fetch date, with an Open button per column. Results are in
      component memory only and do not replace the stored last look.
- [x] Compare two checked routes side by side (sensors passed, passes that
      would record, each way), from the page-memory route checks.
      `components/CompareRoutes.tsx` in the Explore sidebar (under My
      routes): pick Route A and B from saved routes; "Compare" checks any not
      yet checked (one at a time, via the same compute-only `/route/check`
      path as "Check this route", so it also records a last look) and shows
      km and minutes, sensors passed and passes that would record for each
      direction, different sensors passed and which roads were used, with a
      Show button per column. Columns follow the latest check of each route.
- [x] Retention-period slider that updates route results live.
      "What a read history could suggest" now asks `/route/history` for ten
      periods at once (1, 3, 7, 14, 30, 60, 90, 180, 270, 365 days; the API
      takes up to 12), so the slider moves between them with no new request;
      7 days / 30 days / 1 year stay as quick buttons. Summaries say "1 day",
      "1 read" etc., and a period with none of the chosen days says there
      were no trips rather than that no sensor would record the route.

### 5. Learn more panels

- [x] Short neutral explainers: what fixed sensors record, how retention
      length changes what can be inferred, the unicity finding. Link them from
      where they are relevant. `components/LearnMore.tsx` holds the three
      texts and renders each as a "Learn more: ..." disclosure (native
      `<details>`, keyboard and screen-reader friendly). Linked from the area
      summary and sensor detail cards (sensors), under route read-history
      results (retention, unicity) and under the example study's unicity
      chart. Unicity figures quote docs/findings.md F5.
- [x] Move the NJ study (map run, log table, population view, your week) to an
      "Example study" section; the check-up becomes the home page. The page
      now opens on Explore (tab "Check-up"); One driver, Population & policy
      and Your week sit after an "Example study" label in the tab bar, with
      their own heading and lede. `?study=driver|population|yourweek` links
      straight to a study section (it replaces `?bbox=` while one is open);
      the masthead kicker reads "location-privacy check-up".
- [x] Wording pass across README and docs: describe the project as a
      location-privacy check-up, with the NJ ALPR study as the example. Keep
      data-source credits factual. (UI masthead done with the home-page move.)
      README opens with the check-up (explore, my routes, since your last
      visit, compare), "Why this exists" is reworded neutrally, results and
      the old feature list sit under "Example study", "Using it" covers the
      Check-up tab, and Ethics notes on-device storage and no avoidance
      routing. architecture.md and findings.md say how the study relates to
      the check-up; the proposal carries a note that it is kept for reference.
      Camera-count tables still name the manufacturer where it is the OSM tag
      or a source's own count.

### 6. Polish

- [x] Mobile layout, keyboard and screen-reader access for the new views.
      - [x] Tab bars (section tabs, the study's reveal steps and saw/happened
            switch) follow the WAI-ARIA tabs pattern: arrow keys, Home and End
            move between tabs and select them, and only the selected tab is a
            Tab stop (`lib/tabs.ts`).
      - [x] Mobile pass over the Explore sidebar cards (compare tables, route
            timeline, read-history slider) at phone width. Compare tables no
            longer pick up the study log's sticky, no-wrap, clickable-row
            styles, so long route names and road lists wrap. Under 520 px the
            side gutters drop from 26 to 16 px, the compare pickers stack,
            fields use 16 px text (no zoom on focus in mobile browsers) and
            the draw hint wraps. On touch screens buttons, timeline steps,
            day toggles, disclosures and the retention slider get about 40 px
            tap targets. Checked at 375 px with no sideways scroll.
      - [x] Screen-reader pass: live-region announcements for area loads and
            route checks; map focus handling when a sensor or step is chosen.
            One hidden `role="status"` region on the page reads a short line
            (`lib/announce.ts`) when an area starts and finishes loading
            (sensor count, main-road share, changes since the last look) and
            when a route check starts and finishes (sensors passed and passes
            that would record, per direction). The area card, sensor card and
            route result are no longer live regions, so a load is not read as
            the whole card. Picking a sensor on the map or with "Step through
            sensors" moves focus to the sensor card (labelled "Selected
            sensor, n of m"); Previous/Next keep focus; closing the card puts
            focus back on "Step through sensors". Timeline steps keep focus on
            the step button, which reports its state with `aria-pressed`.
- [x] Fast loading: lazy-load the example study (the page still fetches
      cameras and runs on load, even on Explore); skeletons for the area card.
      Cameras and runs are fetched the first time a study tab opens (retried
      on the next study tab if the API was unreachable); `PopulationView`,
      `YourWeek` and `LogTable` load as separate chunks via `next/dynamic`.
      Only `GET /region` runs on load. The area card shows a pulsing
      placeholder while the first area loads.
- [x] Docker setup still works with the new views (data dir for the area
      cache mounted). Checked 2026-10-26 with a fresh `docker compose up
      --build` (separate project name and ports): `/region`, a cached and an
      uncached `/area` (about 2 minutes for Overpass; sensor and road cache
      files land in `data/raw/overpass_areas/` on the host), `/route/check`
      on the study graph and on roads fetched around a route outside it,
      `/route/history`, and the web image opening a `?bbox=` link and
      checking a saved route in the browser. Route checks wrote nothing to
      `data/` and the API log shows only paths. README has a short
      "Check-up in Docker" note.

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
- [x] `sim/scenarios.py` module docstring still describes the NJ camera
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
- [x] Optional region `notes` (or similar) so dataset-specific comparison
      figures live in the region file instead of being gated by region id in
      `PopulationView.tsx`. The region file's optional `notes` object takes
      `unlisted_sensors` (shown with the density scenario) and `read_volume`
      (shown under the unicity chart) as plain text; other keys are rejected.
      `GET /region` serves them and the frontend shows them where present,
      with a generic upper-bound sentence when `read_volume` is missing. The
      NJ figures now live in `nj_edison_new_brunswick.json`; the frontend no
      longer checks the region id.
- [x] Region bounding box option: allow a plain bbox instead of OSM boundary
      relations for areas without clean municipal boundaries. A town may be
      `{"label": ..., "bbox": [west, south, east, north]}` (at most 0.5 deg a
      side, like `GET /area`) instead of an OSM relation; the two kinds mix
      in one region. Box towns query cameras and places by the box (no
      boundary check), feed the study-area polygon as plain rectangles
      (`roads.graph.town_polygons`) and are stored in `towns` with an
      `osm_id` of `bbox/w,s,e,n`. The default region's Overpass query texts
      are unchanged, so existing caches stay valid.
- [x] Setup guide `docs/new_region.md`: step-by-step for a new area, with a
      small worked example region file. The example in
      `docs/examples/new_region/` is one box town (Princeton, NJ) with
      OpenStreetMap plus a CSV of three hypothetical sensor placements;
      `test_region.py` loads it and its file sensors so it stays valid. The
      guide covers fields, towns as relations or boxes, sensor files,
      checking the file, building data locally and in Docker (compose now
      passes `PLATETRAIL_REGION` through to the api and worker), and the
      NHTS caveat. The README's study-area paragraph links to it.
- [x] Generalize the density scenario (`sim/scenarios.py`): synthetic sensors
      placed in any configured town, with neutral wording. `density_scenario`
      (shared by single runs and populations) places them in any town of the
      active region; `/simulate`, `/jobs/simulate` and `/jobs/population`
      take an optional `scenario_town`, rejected with a 422 unless it is one
      of the region's towns (default: the region's `scenario_town`). A town
      with no polygon loaded is now an error instead of a silent spread over
      the whole network (a runner with no towns at all, like the test toy
      graphs, still places anywhere and records `town: null`). Both CLIs take
      `--scenario-town`. `GET /populations` returns `scenario_town`, and the
      study view labels hypothetical cameras with the town a run or
      population actually used. No town picker in the UI yet.
- [x] Document which parts depend on US data (NHTS trip diaries) and what an
      alternative routine source would need to provide.
      `docs/routine_sources.md`: only the example study's drivers use NHTS
      (Explore, routes, read history and Your week do not); the fields
      `NHTSRoutineGenerator` reads, the purpose-code mapping, converting
      another survey to `NHTSDiaries` or writing a new `RoutineGenerator`,
      and caveats. `test_nhts.py` builds diaries in code with no survey files.
      Linked from `docs/new_region.md`.

## Neutral wording in code

- [x] Rename vendor-specific wording in core code comments (e.g. in
      `sim/scenarios.py`) to neutral terms ("additional cameras"). The
      scenario docstring now speaks of additional cameras without public
      locations and "fixed plate-reader cameras" on arterials. Manufacturer
      names left in `etl/cross_check.py` and `etl/directions.py` are OSM tag
      values and source credits (DeFlock), so they stay.
- [ ] Generic "sensor" terminology in new code and API fields where it does
      not break existing endpoints (aliases first, renames later).

## App quality

- [ ] Frontend: run `npm run lint` in CI if not already, fix any warnings.
- [x] Upgrade Next.js past the flagged advisory so `next build` stops failing
      intermittently on its security check. `next` is now ^16.4.3 (16.0.0
      through 16.4.0 are flagged by `npm audit`; 16.4.3 reports 0
      vulnerabilities). Only Next's own packages changed in the lockfile;
      typecheck and two back-to-back builds passed with no advisory notice.
- [x] API: validate `extra_cameras` and other scenario inputs against the
      active region. `scenario_town` is checked in the request model; for
      `extra_cameras` the API tries the seeded placement before queuing
      (`POST /simulate`, `/jobs/simulate`, `/jobs/population`), so a count
      that can't fit the town's arterials at 300 m spacing is a 422 with the
      reason instead of a failed job. Same seed, same answer as the run.
- [x] Study view: a town picker for hypothetical cameras in the driver and
      population forms when the region has more than one town. The "One
      driver" form shows an "in <town>" select next to "+hypothetical cams"
      when the count is above 0 and `GET /region` lists more than one town
      (default: the region's `scenario_town`); the pick is sent as
      `scenario_town` and named in the tooltip. Populations are only built
      from the CLI (`--scenario-town`), so there is no population form to
      add it to.
- [ ] Sensor files: optionally assign `town` by point-in-boundary when a
      multi-town region's file has no town column (needs boundaries without
      OSM, so pairs well with the bbox item).
- [x] Tests: an end-to-end smoke test on a tiny synthetic region (fixture graph
      + fixture cameras) that does not need network access.
      `tests/test_smoke_region.py` makes `tests/fixtures/tiny_region` (two box
      towns, six CSV sensors) the active region and builds a 6 x 6 street grid
      with one primary and one secondary road plus a place of every category
      in code. It runs region config -> file sensors -> direction-aware
      snapping -> commuter routine -> routing, matching and noise ->
      inference (home placed within 1.5 km, regular passes found), a
      12-driver population through unicity and the policy comparison, and a
      2-sensor density scenario in the East town. No database or network;
      about a second.
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
- 2026-10-22: `summary.main_roads` landed (road_km, near_sensor_km, share,
  within_m). Distance only: the card says direction and lanes matter. The
  live Overpass check timed out during the run, so the road query is covered
  by mocked tests only; check it against a real box when Overpass is idle.
- 2026-10-22: sensor detail card landed (frontend only; `lib/area.ts` gained
  `compassWord`, `osmUrl`, `parseDirections`). Checked by typecheck and build,
  not yet clicked through in a browser against live Overpass data.
- 2026-10-22: My routes (local storage, add by clicking start and end) landed.
  Frontend only, no API calls yet. The storage helpers were checked with a
  throwaway Node script and the page with typecheck and build; there is no
  frontend test runner yet, and it has not been clicked through in a browser.
- 2026-10-23: route check in the Explore sidebar and map landed (frontend
  only). Checked by typecheck, build and backend tests; not yet clicked
  through in a browser against a live API. The build warns that the
  installed Next.js version has a published security advisory; upgrading it
  is left for a separate change.
- 2026-10-23: `POST /route/history` landed (backend only). Tested on the toy
  graph; not yet run against the live study network. The schedule is one
  round trip per chosen day; errands and other trips are not modelled, so
  results describe this route on its own.
- 2026-10-23: local look snapshots landed (frontend only). Checked with
  typecheck, build and a throwaway Node script over the snapshot helpers; not
  yet clicked through in a browser. A look is replaced as soon as the change
  is shown, so reloading shows "no change" rather than the same change again.
- 2026-10-23: saved areas landed (frontend only). Checked by typecheck, build
  and a node check of `parseAreas`/`addArea`/pinned pruning; not yet clicked
  through in a browser. `next build` prints a Next.js security advisory
  notice for 16.4.0 (build still succeeds); worth a dependency bump.
- 2026-10-24: "Since your last visit" panel landed (frontend only; the
  area snapshot helper moved to `areaSnapshot` in `lib/snapshots.ts`).
  Checked by typecheck, build and backend tests; not yet clicked through in a
  browser. Because a re-check replaces the stored look, opening a changed
  area afterwards shows "no change" in its own card; the panel is where the
  change is shown.
- 2026-10-24: area comparison landed (frontend only). Checked by typecheck,
  build and backend tests; not yet clicked through in a browser. Comparing
  deliberately skips `recordLook`, so it never hides a change from the
  "Since your last visit" panel.
- 2026-10-24: route comparison landed. `next build` sometimes exits 1 from
  Next.js's security-advisory check (`SecurityFatalError`) after a successful
  compile and typecheck; it happens with or without the change. Upgrading Next
  is worth its own item.
- 2026-10-27: driver-form town picker landed (frontend only). Checked by
  typecheck, build and backend tests; not clicked through in a browser.
