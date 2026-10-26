"""Offline 5-minute demo: network plan vs TMW static, then one live disruption.

Runs the same tools the agents call, without Gemini, and prints the
before/after KPIs used in docs/SOLUTION.md (miles, on-time %, cost, trucks).

  python scripts/demo_run.py [--date 2026-10-27] [--time-limit 15]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from route_optimizer.tools import event_tools, planning_tools  # noqa: E402
from route_optimizer.tools._common import q  # noqa: E402


class _Ctx:
  def __init__(self):
    self.state = {}


def main(argv=None):
  ap = argparse.ArgumentParser()
  ap.add_argument("--date", default="2026-10-27")
  ap.add_argument("--time-limit", type=int, default=15)
  args = ap.parse_args(argv)
  ctx = _Ctx()

  print(f"\n=== 1. Daily plan for {args.date}: TMW static vs AI optimized ===")
  hdr = f"{'DC':<16}{'trucks':>12}{'miles':>18}{'cost $':>22}{'on-time %':>16}"
  print(hdr)
  tot = {k: [0, 0] for k in ("trucks", "miles", "cost", "stops", "late")}
  plans = {}
  for dc in [r["dc_id"] for r in q("SELECT dc_id FROM distribution_centers ORDER BY dc_id")]:
    p = planning_tools.optimize_routes(dc, args.date, ctx, time_limit_s=args.time_limit)
    plans[dc] = p
    b, o = p["tmw_static_baseline"], p["totals"]
    on_b = 100 * (b["stops"] - b["late_stops"]) / max(b["stops"], 1)
    on_o = 100 * (o["stops"] - o["late_stops"]) / max(o["stops"], 1)
    print(f"{dc:<16}{b['routes']:>5} -> {o['routes']:<5}{b['miles']:>8.0f} -> {o['miles']:<7.0f}"
          f"{b['cost_usd']:>10,.0f} -> {o['cost_usd']:<9,.0f}{on_b:>6.1f} -> {on_o:<6.1f}")
    for k, bk, ok in (("trucks", "routes", "routes"), ("miles", "miles", "miles"), ("cost", "cost_usd", "cost_usd"),
                      ("stops", "stops", "stops"), ("late", "late_stops", "late_stops")):
      tot[k][0] += b[bk]
      tot[k][1] += o[ok]
  on = [100 * (tot["stops"][i] - tot["late"][i]) / tot["stops"][i] for i in (0, 1)]
  print(f"{'NETWORK':<16}{tot['trucks'][0]:>5} -> {tot['trucks'][1]:<5}{tot['miles'][0]:>8.0f} -> {tot['miles'][1]:<7.0f}"
        f"{tot['cost'][0]:>10,.0f} -> {tot['cost'][1]:<9,.0f}{on[0]:>6.1f} -> {on[1]:<6.1f}")
  print(f"Savings: ${tot['cost'][0] - tot['cost'][1]:,.0f}/day "
        f"({100 * (tot['cost'][0] - tot['cost'][1]) / tot['cost'][0]:.1f}%), "
        f"{tot['miles'][0] - tot['miles'][1]:,.0f} fewer miles, {tot['trucks'][0] - tot['trucks'][1]} fewer trucks")

  temple = plans["DC-TEMPLE-TX"]
  busiest = max(temple["routes"], key=lambda r: r["stops"])
  print(f"\n=== 2. Disruption: tractor on {busiest['route_id']} breaks down at 07:40 ===")
  out = event_tools.simulate_route_event("BREAKDOWN", busiest["route_id"], "07:40", ctx)
  for line in out["what_changed"]:
    print(" -", line)
  print("KPIs:", out["kpis"])
  print(f"Untouched routes: {out['untouched_routes']}, re-plan latency {out['replan_latency_s']} s, "
        f"approval needed: {out['requires_human_approval']} {out['escalation_reasons']}")

  print("\n=== 3. Reefer failure on a Dallas foodservice truck at 06:50 ===")
  dal = plans["DC-DALLAS-TX"]
  route = max(dal["routes"], key=lambda r: r["stops"])
  out = event_tools.simulate_route_event("REEFER_TEMP_ALERT", route["route_id"], "06:50", ctx, reefer_temp_f=18)
  for line in out["what_changed"]:
    print(" -", line)
  print("KPIs:", out["kpis"], "| approval:", out["escalation_reasons"])


if __name__ == "__main__":
  main()
