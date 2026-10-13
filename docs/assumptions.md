# Assumptions

Every modelling choice that is not measured is listed here, with where it lives in the code and whether its effect was tested. In the code each one is marked `ASSUMPTION` (or documented in the module docstring). The **Tested** column points to the robustness sweep (`backend/scripts/sensitivity.py`, findings F8) or to another check.

## Cameras

| Assumption | Value | Where | Tested |
|---|---|---|---|
| OSM (and DeFlock, which stores its data in OSM) is the camera network | 56 cameras in Edison and New Brunswick | `etl/` | Count cross-check against agency figures ([camera_sources.md](camera_sources.md)) |
| A camera with no direction tag captures both directions (`undirected=best`) | best | `sim/matcher.py` | F8: `undirected: worst` |
| When direction tags disagree, use the primary `direction` tag | primary | `sim/matcher.py` | F8: `ambiguous: alternate tag` |
| Cameras read the rear plates of traffic moving away from them (`facing=rear_plate`) | rear plate | `sim/matcher.py` | F8: `capture oncoming` |
| Maximum difference between travel bearing and camera direction | 45° | `sim/matcher.py` | F8: 30° / 60° |
| A lot camera sees only arrivals through the entrance it faces (`lot_entrance=access_road`) | access road | `sim/matcher.py`, `roads/lots.py` | F2 lot-event counts; F8: `lot events: all cameras` |
| A camera snaps to a road within 50 m, preferring a parallel road within 10 m more; a divided road's opposite carriageway is snapped within 30 m | 50 / 10 / 30 m | `roads/snap.py` | F1 model history |
| Edison's 92 approved cameras sit on arterials, length-weighted, at least 300 m apart (locations are not public) | scenario | `sim/scenarios.py` | F5–F8 compare OSM vs. +92 |
| Mobile ALPR (patrol cars) is not modelled | — | — | Limitation |

## Roads and routing

| Assumption | Value | Where | Tested |
|---|---|---|---|
| Drivers take the free-flow fastest path (no congestion, no habit) | — | `sim/routing.py` | Not tested; limitation |
| Service-road speed | 15 km/h | `roads/graph.py` | — |
| Route-choice penalty on service roads (keeps through traffic off lot roads; timestamps use real speed) | ×4 | `sim/routing.py` | — |
| A trip end attaches to the nearest edge within 500 m | 500 m | `sim/routing.py` | F2: median attachment 10 m, p90 38 m |
| Study area: Edison and New Brunswick boundaries plus a 2 km buffer | 2 km | `roads/graph.py` | — |

## Drivers and routines

| Assumption | Value | Where | Tested |
|---|---|---|---|
| National NHTS 2022 behaviour applies to Edison / New Brunswick | — | `routines/nhts.py` | F4 compares against the templates |
| A week is assembled from separate one-day diaries (same persona and weekday, weighted) | — | `routines/nhts.py` | — |
| Diaries with any non-car or passenger trip are excluded (about 39% of driver-days) | — | `routines/nhts_data.py` | — |
| NHTS trip purpose maps to local place categories | `PURPOSE_CATEGORIES` | `routines/nhts.py` | — |
| Road distance ≈ 1.3 × straight-line distance when matching diary trip lengths | 1.3 | `routines/places.py` | — |
| Errands go to the driver's usual place for that category with probability 0.6 | 0.6 | `routines/templates.py` | — |
| Homes are spread in proportion to residential street length (no census weighting) | — | `routines/places.py` | — |
| Anchors are sampled with no reference to camera locations | — | `routines/` | F2 camera-lot check: 5.3% of errands end in a camera lot vs. 6.6% of places |
| Template generator (fallback): errand mix, 4 km distance decay, template shares, 20 min travel buffer | see code | `routines/templates.py` | F4 |

## Sensor noise

| Assumption | Default | Where | Tested |
|---|---|---|---|
| Chance a captured car produces no read | 5% | `sim/noise.py` | F8: 15% |
| Per-character misread chance for look-alike characters (≈ 3–4% of reads wrong) | 1% | `sim/noise.py` | F8: ×3 |
| Which characters OCR confuses | visual look-alikes | `sim/plates.py` | — |
| Camera outages: 0.25 per week, mean 12 h (≈ 1.8% downtime) | — | `sim/noise.py` | F8: ×4 |
| Timestamp jitter, Gaussian SD | 2 s | `sim/noise.py` | — |
| Misreads land on random look-alike strings, never on another real car's plate | — | `sim/noise.py` | Probably an underestimate of harm; see the README limitations |

## Inference engine

All thresholds are in `inference/engine.py`.

| Assumption | Value |
|---|---|
| A gap of at least 45 minutes between reads is a stay | `STAY_GAP_MIN = 45` |
| A gap covering 03:00 is overnight (home evidence) | `NIGHT_HOUR = 3` |
| A weekday gap of 3–12 h starting 05:00–14:00 is a work or school stay | `DAY_LONG_MIN_H, DAY_LONG_MAX_H` |
| Evidence locations within 400 m are one place (HDBSCAN epsilon and fallback merge) | `MERGE_M = 400` |
| Minimum anchor radius | 500 m |
| A regular pass is the same camera within ±45 min on at least 3 days | `PATTERN_WINDOW_MIN`, `PATTERN_MIN_DAYS` |
| Anomaly: a read at a camera seen on only one day that belongs to no regular pass | — |
| Confidence (high / medium / low) comes from supporting days and their share. It measures consistency, not closeness. | F6 |

The analyst queries by the true plate, so misread reads are not part of the history (`api/queries.inference`).

## Unicity

| Assumption | Where |
|---|---|
| A point is (camera, time bin); default bin 60 min, also 15 min | `analysis/unicity.py` |
| An identity is the recorded (state, plate), so misreads split a car's trace | `analysis/unicity.py` |
| The adversary knows p points drawn at random from the car's own trace | `analysis/unicity.py` |
| Smaller crowds are random subsamples of the population; results depend on crowd size, and the Edison PD portal reports 518,797 "unique plate reads" in 30 days from its 24 cameras, far more than any simulated crowd, so simulated unicity is an upper bound | `analysis/unicity.py`, F5 |

## Policies

| Assumption | Where |
|---|---|
| Retention is measured when the query runs at the end of the simulated period; retention longer than the period equals no limit. Periods up to 4 weeks were simulated, so multi-year retention is not measured directly. | `analysis/policies.py` |
| Search window: each driver gets one random incident time (seeded), and only reads within ±h/2 of it are searchable | `analysis/policies.py` |
| Rounding to the hour floors recorded timestamps; unicity is compared at 15-minute points | `analysis/policies.py` |
| Aggregate-only releases hourly counts per camera with no plates, so nothing per vehicle can be computed | `analysis/policies.py` |

## "Your week" and real-data validation

| Assumption | Where |
|---|---|
| Your week: commute times jittered ±10 min; errands drawn from the template errand mix near home; weekday errands around 18:30, weekend outings from 10:30 | `yourweek.py` |
| Timeline import: visits within 150 m (without a place id) are the same place | `realdata/validate.py` |
| Timeline import: a gap with no recorded activity is a drive if the places are more than 1 km apart | `realdata/validate.py` |
| Timeline import: routes are fastest paths, not the recorded GPS path | `realdata/validate.py` |
| Timeline import: home and work come from labelled places (confirmed), else Google's inferred labels, else most overnight / weekday-daytime hours | `realdata/validate.py` |
