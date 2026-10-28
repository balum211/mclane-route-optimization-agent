"""Builds a plan for a DC and date and compares routing-matrix miles with PC*MILER miles per route.

  uv run python .agents/skills/pcmiler-mileage/scripts/compare_mileage.py --dc DC-TEMPLE-TX --date 2026-10-27
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from route_optimizer.tools import planning_tools  # noqa: E402


class _Ctx:
  state: dict = {}


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--dc", default="DC-TEMPLE-TX")
  ap.add_argument("--date", default="2026-10-27")
  ap.add_argument("--time-limit", type=int, default=5)
  a = ap.parse_args()
  p = planning_tools.optimize_routes(a.dc, a.date, _Ctx(), time_limit_s=a.time_limit)
  print(f"{p['plan_id']}  mileage source: {p['mileage']['source']}  routing type: {p['mileage']['routing_type']}")
  print(f"{'route':<26}{'matrix mi':>10}{'PC*MILER mi':>13}{'diff %':>8}")
  for r in p["routes"]:
    d = 100 * (r["pcmiler_miles"] - r["miles"]) / r["miles"] if r["miles"] else 0
    print(f"{r['route_id']:<26}{r['miles']:>10.1f}{r['pcmiler_miles']:>13.1f}{d:>8.1f}")
  t, b = p["totals"], p["tmw_static_baseline"] or {}
  print(f"{'PLAN':<26}{t['miles']:>10.1f}{t['pcmiler_miles']:>13.1f}")
  print(f"{'TMW STATIC':<26}{b.get('miles', 0):>10.1f}{b.get('pcmiler_miles') or 0:>13.1f}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
