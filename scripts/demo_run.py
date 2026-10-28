"""Offline 5-minute demo: network plan vs TMW static, then one live disruption.

Runs the same tools the agents call, without Gemini, and prints the
before/after KPIs used in docs/SOLUTION.md (PC*MILER miles, on-time %, cost,
trucks, Retail and Restaurant OTD), then the location intelligence story:
geofence dwell overrun, dwell time changes and bad geocodes.

  python scripts/demo_run.py [--date 2026-10-27] [--time-limit 15]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from route_optimizer.tools import analytics_tools, event_tools, location_tools, planning_tools  # noqa: E402
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
  hdr = f"{'DC':<16}{'trucks':>12}{'PC*MILER miles':>18}{'cost $':>22}{'on-time %':>16}"
  print(hdr)
  tot = {k: [0, 0] for k in ("trucks", "miles", "cost", "stops", "late")}
  plans = {}
  for dc in [r["dc_id"] for r in q("SELECT dc_id FROM distribution_centers ORDER BY dc_id")]:
    p = planning_tools.optimize_routes(dc, args.date, ctx, time_limit_s=args.time_limit)
    plans[dc] = p
    b, o = p["tmw_static_baseline"], p["totals"]
    on_b = 100 * (b["stops"] - b["late_stops"]) / max(b["stops"], 1)
    on_o = 100 * (o["stops"] - o["late_stops"]) / max(o["stops"], 1)
    print(f"{dc:<16}{b['routes']:>5} -> {o['routes']:<5}{b['pcmiler_miles']:>8.0f} -> {o['pcmiler_miles']:<7.0f}"
          f"{b['cost_usd']:>10,.0f} -> {o['cost_usd']:<9,.0f}{on_b:>6.1f} -> {on_o:<6.1f}")
    for k, bk, ok in (("trucks", "routes", "routes"), ("miles", "pcmiler_miles", "pcmiler_miles"), ("cost", "cost_usd", "cost_usd"),
                      ("stops", "stops", "stops"), ("late", "late_stops", "late_stops")):
      tot[k][0] += b[bk]
      tot[k][1] += o[ok]
  on = [100 * (tot["stops"][i] - tot["late"][i]) / tot["stops"][i] for i in (0, 1)]
  print(f"{'NETWORK':<16}{tot['trucks'][0]:>5} -> {tot['trucks'][1]:<5}{tot['miles'][0]:>8.0f} -> {tot['miles'][1]:<7.0f}"
        f"{tot['cost'][0]:>10,.0f} -> {tot['cost'][1]:<9,.0f}{on[0]:>6.1f} -> {on[1]:<6.1f}")
  print(f"Savings: ${tot['cost'][0] - tot['cost'][1]:,.0f}/day "
        f"({100 * (tot['cost'][0] - tot['cost'][1]) / tot['cost'][0]:.1f}%), "
        f"{tot['miles'][0] - tot['miles'][1]:,.0f} fewer PC*MILER miles, {tot['trucks'][0] - tot['trucks'][1]} fewer trucks "
        f"(mileage source: {plans['DC-TEMPLE-TX']['mileage']['source']})")
  print("Planned OTD (Retail = by window close, Restaurant = inside window; scheduled-time rule applies once ETAs are promised):")
  for dc, p in plans.items():
    print(f"  {dc:<16}" + "  ".join(
        f"{g} {v['otd_pct']}% (target {v['target_pct']}%)" for g, v in p["planned_otd"]["optimized"].items()))

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

  print("\n=== 4. Geofence: Phoenix at 10:30, a truck is still at the dock ===")
  geo = location_tools.detect_geofence_events("DC-PHOENIX-AZ", args.date, "10:30")
  print(f"Arrivals {geo['arrivals']}, departures {geo['departures']}, overruns:",
        [(r["name"], r["dwell_min"], r["planned_service_min"]) for r in geo["dwell_overruns"]])
  print("Planned stops with no geofence arrival:", [(m["name"], m["geocode_source"]) for m in geo["planned_stops_without_geofence_arrival"]])
  print("Restaurant OTD today so far:", geo["otd_today_so_far"]["RESTAURANT"]["otd_pct"], "%")
  out = event_tools.handle_route_event("EVT-PHO-02", ctx)
  print(f"DWELL_OVERRUN on the route the truck is running ({out['affected_routes']}): {out['status']}, "
        f"latency {out['replan_latency_s']} s")
  for line in out["what_changed"]:
    print(" -", line)
  print("OTD impact:", out["otd_impact"]["by_group"], "| restaurant ETA moves:", out["otd_impact"]["restaurant_eta_moves_over_tolerance"])

  print("\n=== 5. Dwell time change at Temple (last 14 days vs before) ===")
  dw = location_tools.analyze_dwell_time_changes("DC-TEMPLE-TX")
  print(f"{dw['customers_with_dwell_change']} customers changed ({dw['longer']} longer, {dw['shorter']} shorter); "
        f"{dw['weekly_unplanned_minutes_total']} unplanned minutes/week if TMW standards stay as they are")
  for c in dw["changes"][:5]:
    print(f"  {c['name']:<30}{c['direction']:<8}{c['baseline_median_dwell_min']:>6} -> {c['recent_median_dwell_min']:<6} "
          f"TMW std {c['tms_standard_min']} -> recommend {c['recommended_tms_standard_min']}")

  print("\n=== 6. Customer geolocations (TMW geocode vs where trucks park) ===")
  for dc in ("DC-TEMPLE-TX", "DC-PHOENIX-AZ"):
    g = location_tools.validate_customer_geolocations(dc)
    print(f"  {dc}: {g['flagged']} bad geocodes, geofence capture {g['dc_geofence_capture_pct']}%; worst:",
          [(i["name"], i["offset_miles"]) for i in g["issues"][:3]])

  print("\n=== 7. Retail vs Restaurant OTD, last 60 days ===")
  otd = analytics_tools.get_otd_by_segment()
  for grp in ("RETAIL", "RESTAURANT"):
    v = otd[grp]
    print(f"  {grp:<11}{v['otd_pct']}% vs target {v['target_pct']}% ({v['gap_to_target_pts']:+} pts), misses: {v['miss_causes']}")
  print("  Restaurant misses early vs late:", otd["RESTAURANT"]["misses_early_vs_late"])


if __name__ == "__main__":
  main()
