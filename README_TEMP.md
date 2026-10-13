# Plate Trail (temporary README)

> A short overview for now. The full documentation is in [README.md](README.md),
> [docs/architecture.md](docs/architecture.md) and [docs/findings.md](docs/findings.md).

Plate Trail is a privacy-audit tool that measures what a history of automated
license plate reader (ALPR) reads could reveal about a driver. It combines
real camera locations in Edison and New Brunswick, NJ (OpenStreetMap) with
**synthetic drivers only**. No real plate data is used: every plate carries
the made-up state code `ZZ`.

## What works today (first vertical slice, about 1/3 of the proposal)

- **Cameras:** 56 OSM ALPR cameras, with direction tags. They're classed as
  public-road (46), private-lot (6) or service-street (4) cameras.
- **Roads:** an OSMnx drive + service-road graph. Cameras are snapped with
  direction awareness, and both carriageways of divided roads are snapped.
- **Simulation:** template drivers (commuter, student, shift worker) are
  routed by travel time. Direction-aware matching uses a configurable capture
  convention and tolerance. Sensor noise adds missed reads, look-alike
  misreads, camera downtime and timestamp jitter.
- **Stored runs:** ground-truth trips and passes, plus the noisy read log.
  Each read links to its true pass.
- **API:** `/cameras`, `/simulate`, `/runs`, `/runs/{id}`.
- **Frontend:** a map with a **"what the cameras saw" vs. "what actually
  happened"** toggle, a read-log table, and a naive home/work guess.

## Run it

```bash
docker compose up -d --build                                    # db :5434, api :8000, web :3000
docker compose exec api python -m platetrail.etl.run_etl        # cameras (cached after first run)
docker compose exec api python -m platetrail.roads.run_roads    # road graph + snapping
docker compose exec api python -m platetrail.routines.places    # anchor places
docker compose restart api
open http://localhost:3000                                      # opens on demo run #8
```

Simulate a new driver from the UI ("Simulate a new driver") or:

```bash
curl -X POST localhost:8000/simulate -H 'content-type: application/json' \
     -d '{"template": "commuter", "weeks": 4, "seed": 18}'
```

## Demo

**Run #8:** a 4-week commuter, plate `ZZ F33PQR`.
- 74 trips and 88 camera passes, 28 of them skipped for direction.
- 55 reads from 6 cameras, including 1 misread.
- The naive guess puts home and work at the same camera: 0.18 km from work,
  13.6 km from home.

If the live demo fails, use the fallback screenshots:
`docs/figures/demo_run8_saw.jpg` and `docs/figures/demo_run8_happened.jpg`.

## Key findings so far

| | Result |
|---|---|
| **F1:** one commuter's week | 12 captures, 10 of them from a single camera |
| **F2:** 300 synthetic drivers, 1 week | median 6–7 reads; 10% never read; 75% of a driver's reads come from one camera |
| **F3:** naive home/work guess | impossible for 50% of drivers in a week (17% in 4 weeks); median home error ~3 km; 81% of guesses are just the top camera |

At current camera density, an analyst mostly learns a corridor, not an
address. The naive guess is a **baseline, not the planned inference engine**.

## Assumptions to keep in mind

The noise rates, the `rear_plate` capture convention, the 45° tolerance, the
template routine parameters and home placement by street length are all
**assumptions**, labelled as such in code and in README.md. Report results
across their ranges.

## Not built yet

NHTS routines, DeFlock and agency camera sources, the camera-density
scenarios, the Celery/Redis queue, population unicity, the HDBSCAN inference
engine, policy comparison, "your week" mode, and real-data validation.

## Ethics

No real plate reads. Only public camera data. Real location data (planned)
only from consenting people, processed locally and never stored. The project
measures what the data can and can't reveal rather than advocating a side.
