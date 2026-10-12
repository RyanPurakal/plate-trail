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
| Commuter | 183 | 18.5 | 138 | 10.4 | 7.2 | 2.1 | 63% | 11% |
| Student | 67 | 15.5 | 74 | 10.5 | 7.0 | 1.9 | 67% | 10% |
| Shift worker | 50 | 11.8 | 104 | 9.7 | 7.2 | 1.7 | 74% | 6% |

Reads per driver-week: median 6, interquartile range 3–10, max 30. 10% of
drivers are never read.

**What it says.** F1 wasn't an unlucky pick. A typical driver is read about 6
times a week by about 2 cameras, and two-thirds or more of their reads come
from one camera. About one driver in ten is never read in a week. Templates
differ little, because coverage depends on where cameras sit relative to a
driver's anchors more than on how much they drive.

**Checks on the generator.**

- **Camera lots** (`scripts/check_camera_lot_share.py`, 50 seeds × 300
  drivers): 6.4% of errand trips end inside a camera-covered lot (95%
  interval 5.3–8.1%), vs 7.3% of errand places lying in one. Breakdown: the
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
  Raritan Center's 2 cameras see 68 events under `access_road` (all at the
  driveway camera 12760383248), vs 788 if both saw every visit. Menlo Park
  Mall: 13271071475 sees 20 and 13370492601 sees 10. 13370466401 sees none in
  this sample, but its entrance carries 2.4% of 2,000 random home-to-mall
  arrivals, so it can fire.

**Caveats.** Template parameters and noise defaults are assumptions, and
coverage depends heavily on the 56 OSM-mapped cameras. Results should be
redone with NHTS routines and with the density scenarios.
