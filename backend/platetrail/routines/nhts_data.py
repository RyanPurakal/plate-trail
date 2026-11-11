"""Load 2022 NextGen NHTS one-day travel diaries for routine generation.

Source: 2022 NextGen NHTS public-use CSV v2.1 (https://nhts.ornl.gov/downloads),
cached under data/raw/nhts2022/. Codes below are from the 2022 trip/person
codebooks (v2.1, April 2025).

NHTS records ONE travel day per person, so a week is assembled from several
matched diaries (routines.nhts). Here we turn the trip file into diaries:

* Drivers only: DRIVER = 01, age >= 16.
* A usable diary has every trip by private vehicle with the person as
  driver (TRPTRANS in PRIVATE_VEHICLE, DRVR_FLG = 01), starts and ends at
  home (first WHYFROM = 01, last WHYTO = 01), and has no missing times. Days
  with any transit, walking or passenger trip are excluded, because the car's
  location chain would break. About 39% of driver travel-days are excluded
  this way.
* Drivers in the person file with no trips that day are stay-at-home days.
* Persona: worker (WORKER = 01), student (PRMACT = 04, not a worker),
  otherwise non_worker.
* Weights: WTPERFIN (person weight).

    python -m platetrail.routines.nhts_data --download   # fetch + unzip the CSVs (about 4.5 MB)
"""

import argparse
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pandas as pd

from platetrail.config import get_settings

NHTS_URL = "https://nhts.ornl.gov/media/2022/download/csv.zip"
PRIVATE_VEHICLE = {1, 2, 3, 4, 6, 7}  # car, van, SUV, pickup, RV, motorcycle
HOME = 1
DAYS = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday", 5: "Thursday", 6: "Friday", 7: "Saturday"}
PERSONAS = ("worker", "student", "non_worker")


@dataclass(frozen=True)
class DiaryTrip:
    start_min: int  # minutes after midnight (from STRTTIME HHMM)
    why_to: int  # WHYTO code
    miles: float  # TRPMILES


@dataclass(frozen=True)
class Diary:
    persona: str
    travday: int  # 1 = Sunday ... 7 = Saturday
    weight: float
    trips: tuple[DiaryTrip, ...]


@dataclass
class NHTSDiaries:
    diaries: list[Diary]
    # weighted share of driver-days with no trips, by (persona, travday)
    stay_home: dict[tuple[str, int], float] = field(default_factory=dict)
    persona_weight: dict[str, float] = field(default_factory=dict)
    excluded_share: float = 0.0  # weighted share of travel-days dropped by the usability filter

    def by(self, persona: str | None, days: set[int]) -> list[Diary]:
        return [d for d in self.diaries if (persona is None or d.persona == persona) and d.travday in days]


def data_dir() -> Path:
    return get_settings().data_dir / "raw" / "nhts2022"


def download(target: Path | None = None) -> Path:
    target = target or data_dir()
    target.mkdir(parents=True, exist_ok=True)
    if (target / "tripv2pub.csv").exists() and (target / "perv2pub.csv").exists():
        return target
    resp = httpx.get(NHTS_URL, timeout=120, follow_redirects=True, headers={"User-Agent": "PlateTrail/0.1"})
    resp.raise_for_status()
    zipfile.ZipFile(io.BytesIO(resp.content)).extractall(target)
    return target


def _persona(worker, prmact) -> str:
    if worker == 1:
        return "worker"
    if prmact == 4:
        return "student"
    return "non_worker"


def load_diaries(directory: Path | None = None) -> NHTSDiaries:
    directory = directory or data_dir()
    if not (directory / "tripv2pub.csv").exists():
        raise FileNotFoundError(
            f"NHTS files not found in {directory}; run `python -m platetrail.routines.nhts_data --download`")
    persons = pd.read_csv(directory / "perv2pub.csv",
                          usecols=["HOUSEID", "PERSONID", "R_AGE", "DRIVER", "WORKER", "PRMACT", "WTPERFIN", "TRAVDAY"])
    trips = pd.read_csv(directory / "tripv2pub.csv",
                        usecols=["HOUSEID", "PERSONID", "SEQ_TRIPID", "STRTTIME", "WHYFROM", "WHYTO", "TRPTRANS",
                                 "DRVR_FLG", "TRPMILES"])
    drivers = persons[(persons.DRIVER == 1) & (persons.R_AGE >= 16)].copy()
    drivers["persona"] = [_persona(w, p) for w, p in zip(drivers.WORKER, drivers.PRMACT)]
    drivers = drivers.set_index(["HOUSEID", "PERSONID"])

    trips = trips.sort_values(["HOUSEID", "PERSONID", "SEQ_TRIPID"])
    trips["ok"] = (trips.TRPTRANS.isin(PRIVATE_VEHICLE) & (trips.DRVR_FLG == 1) & (trips.STRTTIME >= 0)
                   & (trips.TRPMILES >= 0))
    diaries: list[Diary] = []
    traveled_w, excluded_w = 0.0, 0.0
    travelers = set()
    for key, g in trips.groupby(["HOUSEID", "PERSONID"], sort=False):
        if key not in drivers.index:
            continue
        person = drivers.loc[key]
        travelers.add(key)
        w = float(person.WTPERFIN)
        traveled_w += w
        if not (g.ok.all() and g.WHYFROM.iloc[0] == HOME and g.WHYTO.iloc[-1] == HOME):
            excluded_w += w
            continue
        diaries.append(Diary(
            persona=person.persona, travday=int(person.TRAVDAY), weight=w,
            trips=tuple(DiaryTrip(int(s) // 100 * 60 + int(s) % 100, int(why), float(mi))
                        for s, why, mi in zip(g.STRTTIME, g.WHYTO, g.TRPMILES)),
        ))

    stay: dict[tuple[str, int], float] = {}
    home_days = drivers[~drivers.index.isin(list(travelers))]
    for persona in PERSONAS:
        for day in DAYS:
            zero = home_days[(home_days.persona == persona) & (home_days.TRAVDAY == day)].WTPERFIN.sum()
            moved = drivers[(drivers.persona == persona) & (drivers.TRAVDAY == day)
                            & drivers.index.isin(list(travelers))].WTPERFIN.sum()
            if zero + moved > 0:
                stay[(persona, day)] = float(zero / (zero + moved))
    persona_weight = {p: float(drivers[drivers.persona == p].WTPERFIN.sum()) for p in PERSONAS}
    return NHTSDiaries(diaries, stay, persona_weight, excluded_w / traveled_w if traveled_w else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()
    if args.download:
        print(f"NHTS files in {download()}")
    d = load_diaries()
    total = sum(d.persona_weight.values())
    print(f"{len(d.diaries)} usable driving diaries; {d.excluded_share:.0%} of weighted driver travel-days excluded "
          f"(non-driving trips or not home-to-home)")
    print("Persona shares (weighted drivers): "
          + ", ".join(f"{p} {w / total:.0%}" for p, w in d.persona_weight.items()))
    for p in PERSONAS:
        print(f"  stay-home share {p}: " + ", ".join(f"{DAYS[k][:3]} {d.stay_home.get((p, k), float('nan')):.0%}"
                                                       for k in (2, 3, 4, 5, 6, 7, 1)))


if __name__ == "__main__":
    main()
