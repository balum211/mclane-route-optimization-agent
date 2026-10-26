"""Analytics tools: delivery KPIs, plan history and savings."""

from __future__ import annotations

from collections import Counter, defaultdict

from ._common import ToolError, as_date, load_dc, load_learned_service, q


def get_delivery_kpis(dc_id: str, start_date: str = "", end_date: str = "") -> dict:
  """Delivery performance KPIs from completed deliveries (last 60 days by default).

  Args:
    dc_id: Distribution center id.
    start_date: Optional YYYY-MM-DD lower bound.
    end_date: Optional YYYY-MM-DD upper bound.

  Returns:
    On-time %, exception mix, average dwell, the gap between TMS standard
    unload times and what really happens, and the ten least reliable
    customers.
  """
  dc = load_dc(dc_id)
  sql = "SELECT h.*, c.name, c.std_service_min FROM delivery_history h JOIN customers c ON h.customer_id = c.customer_id WHERE h.dc_id = :dc"
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
