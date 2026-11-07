# Plate Trail

**A location-privacy check-up for any area and your own routes.**

Plate Trail shows where fixed license plate reader (ALPR) and similar sensors are recorded in public map data, and explains in plain language what a history of their reads could suggest about a regular drive.

- **Explore any area.** Search a town or address, or draw a box, and see the mapped sensors with a summary: how many there are, how many have a known facing direction, how much of the main road network they sit near, and where the data comes from and how fresh it is.
- **Check your own routes, kept on your device.** Add the drives you make by clicking start and end. Routes are saved only in your browser; the server computes a check and keeps nothing. Each route shows the sensors passed, a timeline of where reads would happen, and what 1 day to 1 year of read history could suggest.
- **See what changed since your last visit.** Saved areas and checked routes keep a local snapshot, so on return the app lists sensors newly mapped or no longer listed.
- **Compare and drill down.** Two areas or two routes side by side, sensor details, a retention slider and short "Learn more" explainers.

The app has no information about any real vehicle and does not suggest routes around sensors.

## How it works

1. **Sensors for any box** (`GET /area`): OpenStreetMap nodes tagged `surveillance:type=ALPR` (which includes DeFlock's crowdsourced map), plus any sensor files configured for the region. Results are deduplicated, cached on disk and refreshed after 7 days. Place search goes through Nominatim (`POST /geocode`); the query is sent in the request body and is not logged or stored.
2. **Route check** (`POST /route/check`): downloads the roads around the route with OSMnx, snaps the sensors to the road they watch with their facing direction, routes the drive both ways and lists each sensor passed with whether its direction would record the trip. Compute-only: nothing is stored, cached or logged.
3. **Read history** (`POST /route/history`): repeats the route on a weekly schedule (departures varied by up to 10 minutes, about 5% of reads missed) and runs an inference engine (HDBSCAN clustering of where reads stop and resume) on 1 day to 1 year of reads. It reports regular passes and likely overnight and daytime areas in plain sentences. Also compute-only.
4. **Everything personal stays in the browser:** saved routes, saved areas and the snapshots behind "Since your last visit" live in `localStorage`. Area links hold only map coordinates.

## Tech stack

| Layer | Tools |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, MapLibre GL (OpenFreeMap tiles) |
| Backend | Python 3.12, FastAPI, Pydantic, Uvicorn |
| Geo | OSMnx, NetworkX, Shapely, pyproj |
| Inference | scikit-learn (HDBSCAN), NumPy |
| Data | OpenStreetMap via Overpass, Nominatim |
| Ops | Docker Compose, GitHub Actions |

## Quick start

```bash
docker compose up -d --build     # api :8000, web :3000
open http://localhost:3000
```

No database or data-build step is needed. Sensors and roads for each area are fetched from OpenStreetMap on demand and cached under `data/` (gitignored), so the first look at a new area can take a minute while Overpass answers.

**Region.** The initial map view and any extra sensor files come from a region file in `backend/platetrail/regions/` (default: Edison and New Brunswick, NJ). Set `PLATETRAIL_REGION` to another bundled id or to a JSON file path; `docs/examples/new_region/` has a worked example with a sensor CSV.

## Development

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/uvicorn platetrail.api.main:app --reload

cd ../frontend && npm install && npm run dev
npm run typecheck && npm test
```

CI runs the backend tests and the frontend typecheck, tests and build on every push.

## Privacy

- Only public sensor data is used.
- Saved routes and areas live only in the browser. Route checks and read-history requests are compute-only: no route cache, no logging. Place searches are not logged or written to disk.
- No avoidance routing and nothing about real vehicles. The app explains what sensors could record; it does not plan routes around them or look up plates.

## Credits

Capstone project (Computer Science / ITI). Sensor data © OpenStreetMap contributors (including DeFlock mappers); place search by Nominatim; road data via OSMnx. Basemap © OpenFreeMap / OpenMapTiles. The unicity explainer follows de Montjoye et al., *Unique in the Crowd* (2013). The original proposal is in [Plate-Trail-Proposal.md](Plate-Trail-Proposal.md).
