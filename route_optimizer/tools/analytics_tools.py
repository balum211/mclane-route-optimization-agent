"""Analytics tools: delivery KPIs, plan history and savings."""

from __future__ import annotations

from collections import Counter, defaultdict

from ..otd import segment_group, summarize
from ._common import ToolError, as_date, load_dc, load_learned_service, load_otd_policies, q


def get_delivery_kpis(dc_id: str, start_date: str = "", end_date: str = "") -> dict:
  """Delivery performance KPIs from completed deliveries (last 60 days by default).

  Args:
    dc_id: Distribution center id.
    start_date: Optional YYYY-MM-DD lower bound.
    end_date: Optional YYYY-MM-DD upper bound.

  Returns:
    OTD % (Retail and Restaurant policies), Retail and Restaurant OTD
    against target, exception mix, average dwell, the gap between TMS
    standard unload times and what really happens, and the ten least
    reliable customers.
  """
  dc = load_dc(dc_id)
  sql = "SELECT h.*, c.name, c.std_service_min, c.segment FROM delivery_history h JOIN customers c ON h.customer_id = c.customer_id WHERE h.dc_id = :dc"
  params = {"dc": dc["dc_id"]}
  if start_date:
    sql += " AND h.delivery_date >= :s"
    params["s"] = as_date(start_date)
  if end_date:
    sql += " AND h.delivery_date <= :e"
    params["e"] = as_date(end_date)
  rows = q(sql, **params)
  if not rows:
    raise ToolError("No delivery history in that range.")
  b = lambda v: str(v).lower() in {"1", "true", "t"}
  per_cust = defaultdict(list)
  for r in rows:
    per_cust[(r["customer_id"], r["name"])].append(r)
  worst = sorted(
      (
          {"customer_id": cid, "name": name, "deliveries": len(v),
           "on_time_pct": round(100 * sum(b(x["on_time"]) for x in v) / len(v), 1),
           "top_exception": Counter(x["exception_code"] for x in v if x["exception_code"] != "NONE").most_common(1)}
          for (cid, name), v in per_cust.items()
      ),
      key=lambda x: x["on_time_pct"],
  )[:10]
  learned = load_learned_service(dc["dc_id"])
  std = {r["customer_id"]: int(r["std_service_min"]) for r in rows}
  gaps = [learned[c] - std[c] for c in std if c in learned]
  return {
      "dc_id": dc["dc_id"],
      "deliveries": len(rows),
      "date_range": [min(r["delivery_date"] for r in rows), max(r["delivery_date"] for r in rows)],
      "on_time_pct": round(100 * sum(b(r["on_time"]) for r in rows) / len(rows), 1),
      "otd_by_group": {k: v for k, v in summarize(
          [{"segment": r["segment"], "on_time": b(r["on_time"])} for r in rows], load_otd_policies()).items()
          if k != "by_segment"},
      "exceptions": dict(Counter(r["exception_code"] for r in rows)),
      "avg_dwell_min": round(sum(int(r["dwell_min"]) for r in rows) / len(rows), 1),
      "unload_time_gap": {
          "customers_where_tms_underestimates": sum(1 for g in gaps if g > 5),
          "avg_gap_min": round(sum(gaps) / len(gaps), 1) if gaps else 0,
          "meaning": "Positive gap = real p75 unload time is longer than TMS master data.",
      },
      "least_reliable_customers": worst,
  }


def list_optimization_runs(dc_id: str = "", limit: int = 10) -> dict:
  """Lists recent optimization runs with their savings against TMW static routes.

  Args:
    dc_id: Optional DC filter.
    limit: Max runs to return.

  Returns:
    Plan ids, scenario, routes, miles, cost, baseline cost and savings.
  """
  sql = "SELECT * FROM optimization_runs"
  params = {}
  if dc_id:
    sql += " WHERE dc_id = :dc"
    params["dc"] = dc_id.upper()
  rows = q(sql + " ORDER BY created_at DESC", **params)[: max(1, min(limit, 50))]
  for r in rows:
    if r.get("baseline_cost_usd"):
      r["savings_usd"] = round(float(r["baseline_cost_usd"]) - float(r["total_cost_usd"]), 2)
      r["savings_pct"] = round(100 * r["savings_usd"] / float(r["baseline_cost_usd"]), 1)
    r.pop("parameters", None)
  return {"runs": rows}


def get_network_savings_summary(delivery_date: str) -> dict:
  """Rolls up the latest BASE plan per DC for a date into a network view.

  Args:
    delivery_date: YYYY-MM-DD.

  Returns:
    Per-DC and total miles, cost, CO2 and late stops, optimized versus
    the TMW static baseline. DCs without a plan for the date are listed.
  """
  date = as_date(delivery_date)
  runs = q("SELECT * FROM optimization_runs WHERE route_date = :d AND scenario = 'BASE' ORDER BY created_at", d=date)
  latest = {}
  for r in runs:
    latest[r["dc_id"]] = r
  all_dcs = [r["dc_id"] for r in q("SELECT dc_id FROM distribution_centers ORDER BY dc_id")]
  rows = []
  for dc in all_dcs:
    r = latest.get(dc)
    if not r:
      continue
    rows.append({
        "dc_id": dc, "plan_id": r["plan_id"], "routes": r["routes_used"], "miles": r["total_miles"],
        "baseline_miles": r["baseline_miles"], "cost_usd": r["total_cost_usd"],
        "baseline_cost_usd": r["baseline_cost_usd"], "late_stops": r["late_stops"], "co2_kg": r["co2_kg"],
    })
  tot = lambda k: round(sum(float(x[k] or 0) for x in rows), 1)
  return {
      "delivery_date": str(date),
      "dcs": rows,
      "missing_plans": [d for d in all_dcs if d not in latest],
      "network": {
          "miles": tot("miles"), "baseline_miles": tot("baseline_miles"),
          "cost_usd": tot("cost_usd"), "baseline_cost_usd": tot("baseline_cost_usd"),
          "savings_usd": round(tot("baseline_cost_usd") - tot("cost_usd"), 2),
      },
  }


def get_otd_by_segment(dc_id: str = "", start_date: str = "", end_date: str = "") -> dict:
  """Retail versus Restaurant on-time delivery (OTD) against target.

  Retail (c-store, grocery, mass merchant) is on time when the truck arrives
  no later than the receiving window close. Restaurant (QSR, casual dining)
  is on time within 30 minutes of the scheduled delivery time and inside the
  window. Arrival is the geofence entry, or the driver app when the geofence
  missed.

  Args:
    dc_id: Optional DC filter. Empty gives the whole network with a per-DC split.
    start_date: Optional YYYY-MM-DD lower bound.
    end_date: Optional YYYY-MM-DD upper bound.

  Returns:
    OTD % and target gap for RETAIL and RESTAURANT, OTD by segment and by
    DC, the main causes of misses per group, early versus late misses for
    restaurants, and the banners with the lowest OTD.
  """
  sql = ("SELECT h.dc_id, h.on_time, h.exception_code, h.actual_arrival_min, h.planned_arrival_min, "
         "h.arrival_source, c.segment, c.banner, c.window_end_min FROM delivery_history h "
         "JOIN customers c ON h.customer_id = c.customer_id WHERE 1 = 1")
  params = {}
  if dc_id:
    sql += " AND h.dc_id = :dc"
    params["dc"] = load_dc(dc_id)["dc_id"]
  if start_date:
    sql += " AND h.delivery_date >= :s"
    params["s"] = as_date(start_date)
  if end_date:
    sql += " AND h.delivery_date <= :e"
    params["e"] = as_date(end_date)
  rows = q(sql, **params)
  if not rows:
    raise ToolError("No delivery history in that range.")
  b = lambda v: str(v).lower() in {"1", "true", "t"}
  policies = load_otd_policies()
  recs = [{"segment": r["segment"], "on_time": b(r["on_time"])} for r in rows]
  out = summarize(recs, policies)
  causes = defaultdict(Counter)
  rest_early = rest_late = 0
  by_banner = defaultdict(list)
  by_dc = defaultdict(list)
  for r in rows:
    g = segment_group(r["segment"])
    by_banner[(g, r["banner"])].append(b(r["on_time"]))
    by_dc[r["dc_id"]].append({"segment": r["segment"], "on_time": b(r["on_time"])})
    if not b(r["on_time"]):
      causes[g][r["exception_code"]] += 1
      if g == "RESTAURANT":
        if int(r["actual_arrival_min"]) < int(r["planned_arrival_min"]):
          rest_early += 1
        else:
          rest_late += 1
  for g in ("RETAIL", "RESTAURANT"):
    out[g]["miss_causes"] = dict(causes[g].most_common(5))
  out["RESTAURANT"]["misses_early_vs_late"] = {"early": rest_early, "late": rest_late}
  out["by_dc"] = {
      d: {k: v["otd_pct"] for k, v in summarize(v, policies).items() if k in ("RETAIL", "RESTAURANT")}
      for d, v in sorted(by_dc.items())
  }
  out["lowest_otd_banners"] = sorted(
      ({"group": g, "banner": bn, "deliveries": len(v), "otd_pct": round(100 * sum(v) / len(v), 1)}
       for (g, bn), v in by_banner.items() if len(v) >= 20),
      key=lambda x: x["otd_pct"],
  )[:6]
  out["date_range"] = [start_date or "all", end_date or "all"]
  out["geofence_arrival_share_pct"] = round(100 * sum(1 for r in rows if r["arrival_source"] == "GEOFENCE") / len(rows), 1)
  return out
