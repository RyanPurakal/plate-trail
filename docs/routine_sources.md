# Routine sources and the US travel survey

Plate Trail's simulated drivers need a plan of trips: where they live, where
they go, and when. By default that plan comes from the US National Household
Travel Survey (NHTS 2022). This page lists which parts of the app depend on
that US data, which do not, and what a different routine source (another
country's travel survey, a regional diary study, or hand-written patterns)
would need to provide.

## What depends on NHTS

| Part | Uses NHTS? | Notes |
| --- | --- | --- |
| Explore an area (`GET /area`, place search, draw a box) | No | OpenStreetMap and configured sensor files only. |
| My routes: check (`POST /route/check`) | No | Routes the saved start and end on the road network. |
| My routes: read history (`POST /route/history`) | No | Repeats the route on the schedule the visitor sets (days, leave and return times). |
| Since your last visit, compare, sensor details | No | Built on the two above. |
| Your week (`POST /yourweek`) | No | Builds a week from the visitor's own inputs (`yourweek.py`). |
| Example study: one driver (`/simulate`, `/jobs/simulate`) | Default | `generator: "nhts"` is the default; `"template"` avoids NHTS. |
| Example study: populations, unicity, policy comparison | Default | `python -m platetrail.population --generator nhts` is the default; `--generator template` avoids NHTS. |

So the check-up tool works anywhere OpenStreetMap has roads and sensors
mapped. Only the example study's synthetic drivers carry US travel patterns.

## What NHTS supplies

`routines/nhts_data.py` reduces the survey to an `NHTSDiaries` object, and
`routines/nhts.py` (`NHTSRoutineGenerator`) turns that into weeks of trips.
The generator reads only these fields:

- **Diaries** (`Diary`): one person's travel day, with
  - `persona`: `"worker"`, `"student"` or `"non_worker"`;
  - `travday`: day of week, NHTS style (1 = Sunday ... 7 = Saturday);
  - `weight`: a survey weight (any positive number; only ratios matter);
  - `trips`: in order, each a `DiaryTrip` with `start_min` (minutes after
    midnight), `why_to` (trip purpose code, see below) and `miles`
    (trip length in miles).
- **Stay-at-home shares** (`stay_home`): for each `(persona, travday)`, the
  weighted share of drivers who made no trips that day.
- **Persona weights** (`persona_weight`): the weighted number of drivers of
  each persona, used to pick a persona when none is requested.

Each diary must be a closed chain by car with the person driving: it starts
and ends at home, and every trip is a private-vehicle trip as driver. Days
that include transit, walking or riding as a passenger are left out, because
the car's location chain would break.

Purpose codes are NHTS `WHYTO` values. The generator maps them as follows
(`routines/nhts.py`):

| Code(s) | Meaning | Destination |
| --- | --- | --- |
| 1, 2 | Home, work from home | The driver's home |
| 3 | Work | The driver's fixed work place |
| 6 | School | The driver's fixed school |
| 10, 17 | Drop off / pick up someone, visit | Another home |
| 4, 5, 7, 8, 11-16, 18, 19 | Errands, care, health, meals, shopping, recreation, worship | A place of the matching category (`PURPOSE_CATEGORIES`) |
| anything else | | A retail or services place |

Places themselves come from OpenStreetMap (`routines/places.py`) and are not
US-specific. Trip length sets how far away an errand place is chosen
(straight line times a 1.3 circuity factor, an assumption).

## Using a different source

There are two ways in, from least to most code.

**1. Convert your data to `NHTSDiaries`.** If the source is a one-day trip
diary survey, write a loader that builds `Diary` and `DiaryTrip` objects and
the two share tables, then pass the result to `NHTSRoutineGenerator`. You
need to:

- classify each driver as worker, student or non-worker;
- convert days of the week to 1 = Sunday ... 7 = Saturday;
- convert trip purposes to the `WHYTO` codes above (a small lookup table);
- convert distances to miles and departure times to minutes after midnight;
- keep only home-to-home driving days, and count drivers with no trips per
  persona and day for `stay_home`.

The generator works with small pools: for each day it uses the same persona
and weekday if at least 20 diaries match (`MIN_POOL`), then widens to the
same persona and weekday-or-weekend, then any persona on that day, then all
diaries. `tests/test_nhts.py` builds diaries in code with no survey files,
as an example.

**2. Write a new `RoutineGenerator`.** For a source that already describes
whole weeks, or a different model entirely, subclass `RoutineGenerator`
(`routines/base.py`) and return a `Routine`: anchor places (`home` plus
`work` or `school`) and `PlannedTrip`s (origin, destination, departure time,
purpose label) for `weeks` weeks from a Monday. Routing, sensor matching,
noise and inference all run after this step and do not change. To make it
selectable, add its name to `SimulationRunner.make_generator`
(`sim/runner.py`), the `generator` field in `api/schemas.py`, and the
`--generator` choices in `sim/runner.py` and `population.py`.

Either way, sample anchors without looking at sensor locations (the existing
generators never do), so results are not biased toward or away from sensors.

## Things to keep in mind

- **Local fit.** NHTS is national: the example study uses national weights
  with local places, because only 582 usable diaries are from the Middle
  Atlantic. A local survey would fit a region better, but small samples make
  the persona-and-day pools thin; the fallbacks above handle that, at the
  cost of mixing days or personas.
- **Car-only days.** About 39% of US driver travel-days are left out by the
  driving-only filter. In places where mixed trips by car and transit are
  common, that share will be higher, and the remaining diaries less typical.
- **Licences.** Check that a survey's terms allow this use and credit it in
  the README and `docs/assumptions.md`, as NHTS is credited now.
- **Templates as a fallback.** `--generator template` needs no survey at all;
  its times and shares are hand-written assumptions listed in
  `routines/templates.py`.
