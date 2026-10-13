# Real-data validation (your own location history)

Every result elsewhere in this project uses synthetic drivers. This importer checks those results against one real person's travel: it reads your own Google Timeline export, turns each recorded drive into a trip through the same simulator (the real camera positions, matching and sensor noise), and scores the naive baseline and the inference engine against the places your Timeline labels Home and Work.

**Status: built and tested on synthetic exports. It has not yet been run on a real file**, because none was available while this was written. The numbers below come from synthetic exports.

## Privacy

- The file is read on your machine, inside the CLI process. Nothing is uploaded, written to the database, or put in the route cache (`use_cache=False`).
- The report prints counts and distances, never coordinates.
- No plate is involved. The simulated reads use a synthetic `ZZ` plate, as everywhere else.
- Delete the export when you are done if you don't want to keep it. Don't commit it: `data/` is ignored by git, so keep the file there.

## 1. Export your Timeline

Google now keeps Timeline on your phone, so you export it from the phone.

**Android**
1. Open **Settings → Location → Location services → Timeline**.
2. Tap **Export Timeline data**. Save the file (`Timeline.json`) and copy it to your computer.

**iPhone**
1. Open the **Google Maps** app, tap your profile picture, then **Your Timeline**.
2. Tap **⋯ → Location & privacy settings → Export Timeline data**. Save the JSON file and copy it to your computer.

**Older Google Takeout export.** If you still have a Takeout archive from before the move to on-device storage, its `Semantic Location History/YYYY/YYYY_MONTH.json` files work too. Run the tool on one month at a time.

The import is useful only if you drove in or through **Edison or New Brunswick, NJ** during the period. Drives elsewhere are counted and skipped.

## 2. Run it

```bash
docker compose up -d db            # the camera set and road graph come from the usual pipeline
cd backend
python -m platetrail.realdata.validate ../data/Timeline.json --weeks 4
# optional: --start 2025-03-03 (a Monday; default = the last 4 full weeks in the file), --json
```

Example output (from a synthetic export):

```
Timeline (android export), 2 weeks from 2026-10-12
  21 visits at 2 places; 20 drives found (0 assumed from distance), 0 walk/transit gaps
  in period: 20 drives; 0 outside Edison/New Brunswick; 20 simulated
  ground truth: home = confirmed, work = confirmed
  cameras: 60 passes, 28 reads at 3 cameras
  naive baseline:   home no estimate; work no estimate
  inference engine: home off by 0.60 km (high); work no estimate (-)
                    1 regular passes, 0 anomalies flagged
  (nothing was stored; coordinates are not printed)
```

## How it works

| Step | What happens |
|---|---|
| Parse | All three formats (Android `semanticSegments`, iPhone segment list, Takeout `timelineObjects`). Times are converted to local wall-clock time (America/New_York). |
| Places | Visits are grouped by Google place id, otherwise by distance (within 150 m counts as the same place). |
| Drives | A move between two consecutive visits at different places counts as a drive when its activity is a private vehicle (`IN_PASSENGER_VEHICLE`, `DRIVING`, …). Walking, cycling, transit and taxis are skipped. A gap with no recorded activity counts as a drive if the places are more than 1 km apart. |
| Ground truth | Home and work come from places labelled `HOME` / `WORK` (`TYPE_HOME` / `TYPE_WORK` in Takeout); these count as **confirmed**. Google's `INFERRED_HOME` / `INFERRED_WORK` are reported as **google_inferred**. If neither exists, home is the place with the most overnight hours and work is the non-home place with the most weekday daytime hours (**derived**). |
| Simulate | Drives whose two ends are both on the study-area road graph become planned trips at their real departure times. They are routed by the simulator's fastest path (not your recorded GPS path), matched to cameras, and given sensor noise. |
| Score | Naive baseline and inference engine on the read log; home and work error in km against the ground truth. |

## Synthetic check (end to end)

`scripts/validate_synthetic_timeline.py` writes synthetic NHTS drivers as Timeline exports, rotating through all three formats, then runs them back through the importer on the real Edison road graph and cameras (`data/exports/timeline_synthetic.txt`):

| 60 drivers, 4 weeks | Result |
|---|---|
| Drives recovered from the exports | 3,560 of 3,573 planned trips (the other 13 were trips between two visits at the same place) |
| Reads per driver (median) | 19 |
| Engine: home | 60/60 estimated, median error 3.99 km |
| Engine: work | 15 estimated, median error 6.11 km |
| Naive: home | 59/60 estimated, median error 4.16 km |
| Naive: work | 43 estimated, median error 3.40 km |

These numbers agree with the engine evaluation on directly simulated drivers (findings F6), which is what a lossless importer should give.

## What a real file would add

- Real departure times and destinations, rather than NHTS diaries assembled into weeks.
- Real home and work locations relative to the real cameras: whether a camera sits near your street.
- It is still one person. A single run is a case study, not an estimate for the population.

## Limitations

- Routes are fastest paths, not your actual path. If you habitually take a road the router doesn't prefer, real camera exposure differs.
- Short gaps and missing segments in the Timeline can merge or drop trips.
- Ground truth is only as good as your labels. Label Home and Work in Google Maps first for a meaningful score.
