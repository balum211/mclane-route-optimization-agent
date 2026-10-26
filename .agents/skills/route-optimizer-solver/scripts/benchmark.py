"""Benchmarks optimized plans against TMW static routes for every DC on a date.

Exit code 1 if any DC's optimized cost is not below the baseline, or a plan
has HOS violations, so it can gate a solver change.

  python .agents/skills/route-optimizer-solver/scripts/benchmark.py --date 2026-10-27 --time-limit 10
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from route_optimizer.tools import planning_tools  # noqa: E402
from route_optimizer.tools._common import q  # noqa: E402


class Ctx:
  state = {}


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--date", default="2026-10-27")
  ap.add_argument("--time-limit", type=int, default=10)
  a = ap.parse_args()
  ok = True
  print(f"{'DC':<16}{'sec':>6}{'trucks':>12}{'miles':>16}{'cost $':>20}{'late':>10}{'dropped':>9}")
  for dc in [r["dc_id"] for r in q("SELECT dc_id FROM distribution_centers ORDER BY dc_id")]:
    t0 = time.time()
    p = planning_tools.optimize_routes(dc, a.date, Ctx(), time_limit_s=a.time_limit)
    b, o = p["tmw_static_baseline"], p["totals"]
    hos = any(r["hos_violation"] for r in p["routes"])
    ok &= o["cost_usd"] < b["cost_usd"] and not hos
    print(f"{dc:<16}{time.time() - t0:>6.1f}{b['routes']:>5} > {o['routes']:<4}{b['miles']:>7.0f} > {o['miles']:<6.0f}"
          f"{b['cost_usd']:>9,.0f} > {o['cost_usd']:<8,.0f}{b['late_stops']:>4} > {o['late_stops']:<3}{o['dropped_orders']:>7}"
          + ("  HOS VIOLATION" if hos else ""))
  sys.exit(0 if ok else 1)


if __name__ == "__main__":
  main()
