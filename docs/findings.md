# Findings

Results recorded as the project is built, with the configuration that
produced them. All drivers are synthetic.

## F1. Coverage is sparse: one commuter's week is about 10 reads, over 90% from one camera

**Setup.** One hand-written commuter week (`backend/scripts/demo_week.py`):
home on a residential street off Timber Oaks Rd in Edison, work at Rutgers
College Ave in New Brunswick, a commute every weekday (07:45 and 17:15), and
a Saturday trip to Menlo Park Mall. That is 12 trips and about 172 km.
Cameras: the 56 OSM ALPR cameras in Edison and New Brunswick (46 public road,
10 private lot). Matcher: `rear_plate`, 45° tolerance (`lot_entrance` see below).
Noise: defaults (all assumptions; see README).

**Result** (after the divided-road snapping fix, 2026-10-12):

| | Zero noise | Default noise, mean of 1,000 seeds |
|---|---|---|
| Camera passes | 12 | — |
| True captures | 11 | — |
| Reads | 11 | 10.27 |
| Misread reads | 0 | 0.39 |
| Lost to downtime | 0 | 0.19 |
| Lost to missed reads | 0 | 0.54 |

10 of the 11 captures come from a single camera, Albany St (node 14181989101),
read once in each direction of every weekday commute. The other one is a mall
arrival (node 13370492601 under `lot_entrance=access_road`, the step 6
default; node 13370466401 under the earlier `nearest` rule; counts are the
same either way). The 14 km commute passes no other camera. Before
the fix, which snaps both carriageways of divided roads, the evening commute
registered no passes at all and the week had 6 captures.

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
  misread (0.39 of 10.27 per week), but with only ~10 reads a week, a single
  misread moves about a tenth of that week's reads onto a different plate
  string. The `distinct_plates` mean of 1.38 means roughly one week in three
  yields a second plate string for the same car. See the misread limitation in the
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

## F2. Across 300 template drivers: median 6 reads a week, 11% never read

**Setup.** `backend/scripts/simulate_drivers.py --drivers 300 --weeks 1 --seed 0`
(2026-10-12). Drivers come from the step 6 template generator (183
commuters, 67 students, 50 shift workers). Homes are on residential streets
weighted by length, and anchors are sampled without reference to cameras.
Matcher: `rear_plate`, 45° tolerance, `lot_entrance=access_road`. Noise:
defaults (assumptions).

| Template | Drivers | Trips/wk | km/wk | Camera passes | Reads after noise | Distinct cameras | Top camera's share | No reads |
|---|---|---|---|---|---|---|---|---|
| Commuter | 183 | 18.5 | 127 | 10.3 | 6.7 | 2.1 | 64% | 11% |
| Student | 67 | 15.5 | 66 | 11.3 | 7.1 | 2.0 | 67% | 9% |
| Shift worker | 50 | 11.8 | 97 | 9.4 | 6.2 | 1.7 | 69% | 14% |

Reads per driver-week: median 6, interquartile range 2–10, max 26.

**What it says.** F1 wasn't an unlucky pick. A typical driver is read about
6 times a week by about 2 cameras, and two-thirds of their reads come from a
single camera. About one driver in nine is never read in a week. Templates
differ little, because coverage is driven by where cameras are relative to a
driver's anchors more than by how much they drive.

**Checks on the generator.**

- Camera lots: 5.5% of 1,231 errand trips end inside a camera-covered lot, vs
  7.3% of errand places lying in one. There is no bias toward camera lots.
- Anchor attachment: median 15 m to the nearest edge, p90 84 m; 7.2% of trip
  ends attach more than 100 m away (inside large lots and Raritan Center).
- Lot-camera events across the 300 drivers by `lot_entrance` mode: 216
  (`access_road`, default), 570 (`nearest`), 1,304 (`all`). Raritan Center's
  2 cameras see 80 events under `access_road`, vs 772 if both saw every
  visit.

**Caveats.** Template parameters and noise defaults are assumptions, and
coverage depends heavily on the 56 OSM-mapped cameras. Results should be
redone with NHTS routines and with the density scenarios.
