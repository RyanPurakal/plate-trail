"""Print the policy comparison for a stored population.

    python scripts/policy_report.py <population_id>
"""

import sys

from platetrail.api.queries import population_policies
from platetrail.db import get_engine


def fmt(x, pct=True):
    if x is None:
        return "—"
    return f"{x:.0%}" if pct else f"{x:.2f}"


def main() -> None:
    pid = int(sys.argv[1])
    res = population_policies(get_engine(), pid)
    print(f"Population {pid}: {res['drivers']} drivers x {res['weeks']} week(s), +{res['extra_cameras']} scenario cameras\n")
    print(f"{'policy':<16}{'reads':>8}{'eng home est':>14}{'med km':>8}{'<1km all':>10}{'eng work est':>14}"
          f"{'naive home est':>16}{'naive med':>10}{'uniq p2':>9}{'uniq p4':>9}{'res':>5}")
    for r in res["rows"]:
        print(f"{r['policy']:<16}{r['reads']:>8}{fmt(r['engine_home']['estimated']):>14}"
              f"{fmt(r['engine_home']['median_km'], False):>8}{fmt(r['engine_home']['within_1km_of_all']):>10}"
              f"{fmt(r['engine_work']['estimated']):>14}{fmt(r['naive_home']['estimated']):>16}"
              f"{fmt(r['naive_home']['median_km'], False):>10}{fmt(r['unicity_p2']):>9}{fmt(r['unicity_p4']):>9}"
              f"{r['unicity_resolution_min']:>5}")
    print("\nunicity = share of ALL drivers singled out by p hourly (or 15-min) points; '<1km all' = share of all "
          "drivers whose home estimate is within 1 km")


if __name__ == "__main__":
    main()
