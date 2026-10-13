# Findings

Results recorded as the project is built, with the configuration that
produced them. All drivers are synthetic.

## F1. Coverage is sparse: one commuter's week is about 11 reads, 10 of 12 captures from one camera

**Setup.** One hand-written commuter week (`backend/scripts/demo_week.py`):
home on a residential street off Timber Oaks Rd in Edison, work at Rutgers
College Ave in New Brunswick, a commute every weekday (07:45 and 17:15), and
a Saturday trip to Menlo Park Mall. That is 12 trips and about 162 km.
Cameras: the 56 OSM ALPR cameras in Edison and New Brunswick (46 public road,
10 private lot). Matcher: `rear_plate`, 45° tolerance (`lot_entrance` see below).
Noise: defaults (all assumptions; see README).

**Result** (current model: drive + service-road graph, edge-point attachment,
divided-road snapping with facing check, `lot_entrance=access_road`; 2026-10-12).
Plate `ZZ W65HIB`.

| | Zero noise | Default noise, seed 0 | Default noise, mean of 1,000 seeds |
|---|---|---|---|
| Camera passes | 14 | 14 | 14 |
| True captures (matcher) | 12 | 12 | 12 |
| Reads after noise | 12 | 11 | 11.20 |
| Misread reads | 0 | 0 | 0.43 |
| Lost to downtime | 0 | 0 | 0.21 |
| Lost to missed reads | 0 | 1 | 0.59 |
| Distinct (state, plate) identities | 1 | 1 | 1.42 |

10 of the 12 captures come from Albany St (node 14181989101), read once in
each direction on every weekday commute. The other two come from the Saturday
mall trip: an arrival through Menlo Park Mall's Lafayette Ave entrance
(node 13271071475) and a Parsonage Rd camera (node 13874923001) on the way in.
2 passes are skipped for direction.

How this number changed as the model was fixed (same driver and trips):

| Model state | True captures |
|---|---|
| Steps 4–5 (one carriageway per camera, node-to-node routing) | 6 |
| + divided-road snapping (evening commute now sees Albany St) | 11 |
| + `ZZ` state code | 11 (plate identity change only) |
| + service roads, edge-point attachment, entrance-based lot rule | 12 |
| + opposite carriageway always snapped (`b86ddb4`) | 12 (rerun: every number in the table above unchanged) |

The "all counts identical" check after the `ZZ` change compared against the
11-capture run. The jump from 6 to 11 had come one commit earlier, from the
divided-road fix.

![Morning and evening commute past the Albany St camera](figures/albany_commute.svg)

*Albany St is divided here. The camera faces 238° and 103° and sits 9.6 m from
the westbound carriageway (morning route, red) and 22 m from the eastbound
carriageway (evening route, blue). Green edges are the camera's snaps; before
the fix only the westbound carriageway was snapped.*

**Why it matters.**

- **Linkage and inference.** A read history built mostly from one camera
  reveals a regular crossing point and time of day, not a route. Home and work
  inference will be bounded by which cameras sit between a driver's anchors,
  so results will vary hugely from driver to driver. Report distributions
  across drivers, not a single "typical" driver.
- **Misreads matter more when reads are few.** About 4% of reads are
  misread (0.43 of 11.20 per week), but with only ~11 reads a week, a single
  misread moves about a tenth of that week's reads onto a different plate
  string. The mean of 1.42 distinct identities means roughly two weeks in
  five yield a second plate string for the same car. See the misread limitation in the
  README: this is likely an underestimate.
- **Anchor sampling must not chase cameras.** Results are very sensitive to
  whether a driver's anchors happen to sit behind a camera. Biasing anchors
  toward camera-covered lots or roads would inflate coverage and overstate
  what ALPR reveals. Step 6 samples retail and other anchors at realistic rates,
  with no reference to camera locations.
- **Density scenarios.** The proposal's fallback for sparse data (Edison's 92
  newly approved cameras as a density setting) looks necessary to show how
  conclusions change as networks grow.

**Caveats.** One hand-picked driver is an illustration, not an estimate. The
step 6 routine generator and population runs will replace it with
distributions.

## F2. Across 300 template drivers: median 6 reads a week, 10% never read

**Setup.** `backend/scripts/simulate_drivers.py --drivers 300 --weeks 1 --seed 0`
(2026-10-12, current model as in F1). Drivers come from the step 6 template
generator (183 commuters, 67 students, 50 shift workers). Homes are on
residential streets weighted by length, and anchors are sampled without
reference to cameras. Places more than 100 m from the network are excluded.
Matcher: `rear_plate`, 45° tolerance, `lot_entrance=access_road`. Noise:
defaults (assumptions).

| Template | Drivers | Trips/wk | km/wk | Camera passes | Reads after noise | Distinct cameras | Top camera's share | No reads |
|---|---|---|---|---|---|---|---|---|
Rerun on `b86ddb4` (opposite carriageway always snapped). "Top camera" is
the share of a driver's **reads** from their most-read camera, median across
drivers with at least one read.

| Template | Drivers | Trips/wk | km/wk | Camera passes | Reads after noise | Distinct cameras | Top camera (median) | No reads |
|---|---|---|---|---|---|---|---|---|
| Commuter | 183 | 18.5 | 138 | 10.5 | 7.2 | 2.1 | 70% | 11% |
| Student | 67 | 15.5 | 74 | 10.5 | 7.0 | 1.8 | 71% | 10% |
| Shift worker | 50 | 11.8 | 104 | 9.9 | 7.2 | 1.7 | 86% | 6% |

Reads per driver-week: median 6, interquartile range 3–10, max 30. 10% of
drivers are never read. **Across all drivers, the median driver gets 73% of
their reads from a single camera.**

Change from the previous run: camera passes rose slightly (commuter 10.39 →
10.54, shift worker 9.70 → 9.94), because passes on the newly snapped
opposite carriageways are recorded and then skipped for direction under
`rear_plate`. Captures, reads and the share of unread drivers are identical.
The previous "top camera's share" column (63% / 67% / 74%) was a mean over
true captures; it is now a median over reads.

**After deep-lot cameras and building outlines** (2026-10-12). The 4 cameras
deep inside lots are now road cameras on the service streets they watch, and
18 of 21 large buildings attach at their outline instead of being excluded.
Same command and seed:

| Template | Camera passes | Captures | Reads after noise | Top camera (median) | No reads |
|---|---|---|---|---|---|
| Commuter | 10.5 → 11.5 | 7.7 → 8.1 | 7.2 → 7.6 | 70% → 71% | 11% → 12% |
| Student | 10.5 → 10.5 | 7.5 → 7.6 | 7.0 → 7.1 | 71% → 75% | 10% → 9% |
| Shift worker | 9.9 → 9.4 | 7.7 → 7.3 | 7.2 → 6.9 | 86% → 88% | 6% → 4% |

Reads per driver-week: median 6 → **7**, interquartile range 3–10 → 3–10.25,
max 30 → 32; no reads 10% → 10%. **Median share of reads from one camera:
73% → 75%.** Across all 300 drivers, captures by camera kind: 2,294 public
road, 46 private lot, 21 service road (the 4 re-modelled cameras). Some
template rows shift because the place pool changed (18 places added), which
changes which anchors each seed draws. That's sampling variation, not a
model effect for that template.

**What it says.** F1 wasn't an unlucky pick. A typical driver is read about 6
times a week by about 2 cameras, and for the median driver 73% of reads come
from one camera. About one driver in ten is never read in a week. Templates
differ little, because coverage depends on where cameras sit relative to a
driver's anchors more than on how much they drive.

**Checks on the generator.**

- **Camera lots** (`scripts/check_camera_lot_share.py`, 50 seeds × 300
  drivers): 6.4% of errand trips end inside a camera-covered lot (95%
  interval 5.3–8.1%), vs 7.3% of errand places lying in one. After the
  deep-lot cameras became service-road cameras, fewer lots count as
  camera-covered: 5.3% (4.0–6.7%) vs 6.6% of places, and the realized
  category mix predicts 5.6%. Same explanation as below. Breakdown: the
  configured category mix gives 7.4%, and adding distance decay from homes
  gives 7.9%. The templates' realized mix (evening outings push food to 34%
  and leisure to 16%; leisure has no places in camera lots, retail has 18%)
  predicts 6.6%, matching the observed 6.4%. So the gap comes from the
  category mix, not a bias against camera lots, and the interval contains
  the raw share.
- **Anchor attachment**: median 10 m to the nearest edge, p90 38 m, max 95 m;
  no trip end is more than 100 m away (was 7.2% before service roads were
  added).
- **Lot-camera events** (`scripts/lot_events_by_mode.py`, 300 drivers): 110
  under `access_road` (default), 622 under `nearest`, 1,440 under `all`.
  After the deep-lot change (6 lot cameras left): 75 / 534 / 742. Raritan
  Center's remaining lot camera (12760383248) sees 40 events; the other one
  (14174561401) is now a service-road camera on Mayfield Ave.
  Raritan Center's 2 cameras see 68 events under `access_road` (all at the
  driveway camera 12760383248), vs 788 if both saw every visit. Menlo Park
  Mall: 13271071475 sees 20 and 13370492601 sees 10. 13370466401 sees none in
  this sample, but its entrance carries 2.4% of 2,000 random home-to-mall
  arrivals, so it can fire.

**Caveats.** Template parameters and noise defaults are assumptions, and
coverage depends heavily on the 56 OSM-mapped cameras. Results should be
redone with NHTS routines and with the density scenarios.

## F3. A naive home/work guess: half of drivers can't be guessed in a week, and the guess is mostly the top camera

> **Naive baseline, not the planned inference engine.** This measures the
> simplest thing an analyst could do with a read log. The inference engine
> (HDBSCAN anchors, schedule reconstruction, anomaly detection) is planned
> and will be compared against this.

**Method** (`backend/platetrail/inference/naive.py`). Using only the noisy read
log (camera + recorded time), days with at least 2 reads are used:

- **Home** = the camera that most often records a day's first or last read.
- **Work** = the camera that most often records the read just before the
  day's longest gap (the arrival before the day's main stay).
- No guess unless at least 2 days qualify. The guessed location is the
  camera's location; the error is the distance to the driver's true home and
  work (or school, for students).

**Setup.** The F2 population: `backend/scripts/naive_guess_population.py
--drivers 300 --seed 0` (2026-10-12, same drivers, matcher and default noise
as F2).

**1 week** (as F2):

| Template | Drivers | No guess | Home error median / p75 | Work error median / p75 | Home guess = top camera | Work guess = top camera | Home = work camera |
|---|---|---|---|---|---|---|---|
| Commuter | 183 | 49% | 3.7 / 8.4 km | 2.1 / 6.0 km | 80% | 71% | 72% |
| Student | 67 | 39% | 1.6 / 3.2 km | 0.9 / 1.4 km | 83% | 80% | 73% |
| Shift worker | 50 | 66% | 4.4 / 10.8 km | 1.8 / 11.0 km | 82% | 76% | 65% |
| **All** | **300** | **50%** | **2.9 / 7.8 km** | **1.5 / 5.4 km** | **81%** | **74%** | **72%** |

Errors are over drivers with a guess. Within 1 km: home 26%, work 40%.

**4 weeks** (same drivers, longer history):

| Template | Drivers | No guess | Home error median / p75 | Work error median / p75 | Home guess = top camera | Work guess = top camera | Home = work camera |
|---|---|---|---|---|---|---|---|
| Commuter | 183 | 17% | 4.5 / 8.5 km | 3.3 / 5.9 km | 80% | 69% | 74% |
| Student | 67 | 7% | 1.2 / 2.5 km | 1.1 / 1.5 km | 81% | 77% | 76% |
| Shift worker | 50 | 28% | 4.5 / 10.0 km | 1.6 / 8.2 km | 81% | 72% | 75% |
| **All** | **300** | **17%** | **3.3 / 8.1 km** | **1.8 / 5.3 km** | **80%** | **72%** | **74%** |

Within 1 km: home 24%, work 33%. **More history makes a guess possible far
more often (no guess 50% → 17%) but doesn't make it more accurate.** The
error stays at about 3 km because the limit is where the cameras are, not
how many reads there are.

**What it says.**

- **A week of reads is often not enough to guess anything.** Half of drivers
  never have two days with two or more reads. Shift workers fare worst (66%),
  partly because their night-shift days split at midnight, which this
  baseline can't handle.
- **When a guess exists, it is mostly the driver's single most-read camera**
  (81% for home), and home and work are the same camera for 72% of guessed
  drivers. With sparse coverage (F1, F2) the read log rarely separates the
  two ends of a commute. The baseline is really answering "which camera does
  this car pass most?"
- **Work looks better than home** because workplaces and campuses cluster
  in New Brunswick near the cameras that do exist (Albany St, College Ave),
  while homes are spread across residential Edison. Demo run #8 shows this:
  both guesses are the Albany St camera, 0.18 km from work but 13.6 km from
  home.
- This sets the bar the inference engine has to beat. It also shows that
  "a camera sees you often" is not the same as "a camera reveals where you
  live". With the current camera density, an analyst gets a corridor, not an
  address, unless a camera happens to sit near the home.

**Caveats.** Template routines, noise defaults and camera positions shape
these numbers. The baseline ignores time of day beyond first/last and gap
ordering, and it can't place an anchor away from a camera.

## F4. NHTS routines vs. templates: fewer, more scattered reads; the conclusions hold

**Setup.** Same 300 drivers, seed, matcher, noise and cameras as F2/F3, with
routines from the 2022 NHTS generator (`--generator nhts`) instead of the
hand-written templates (2026-10-13). NHTS personas: 200 workers, 93
non-workers, 7 students.

| | Templates (F2/F3) | NHTS |
|---|---|---|
| Trips per week (worker / non-worker) | 18.5 commuter | 16.3 / 12.2 |
| Reads per driver-week, median (IQR) | 7 (3–10.25) | 5 (2–9.25) |
| Drivers never read | 10% | 10% |
| Share of reads from top camera, median | 75% | 60% |
| Errand trips ending in camera-covered lots (vs. 6.6% of places) | 5.3% | 7.4% |
| Naive guess: no guess possible (1 week) | 50% | 51% |
| Naive home error, median / p75 | 2.9 / 7.8 km | 3.7 / 8.8 km |
| Naive work error, median / p75 | 1.5 / 5.4 km | 2.7 / 7.4 km |
| Naive home guess = top camera | 81% | 85% |

**What it says.** Real trip diaries give drivers more varied destinations and
stay-at-home days (about 15% of worker weekdays, 35% of non-worker days). That
means slightly fewer reads, spread over more cameras. The headline findings
don't depend on the routine source: about one driver in ten is never read in
a week, half can't be placed even naively, and naive guesses are a few
kilometres off, mostly at the driver's top camera.
