"""Route planning tools: optimize, compare against TMW static routes, what-ifs."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from google.adk.tools import ToolContext

from ..config import get_settings
from ..db.repository import get_repository
from ..geo import build_matrix, fmt_time
from ..optimizer import PlanResult, SolverOptions, Stop, simulate_route, solve
from ._common import Problem, ToolError, load_problem, new_id, now_ts, q

MAX_ROUTES_IN_REPLY = 25


def _dropped_reason(s: Stop, problem: Problem) -> str:
  vs = problem.vehicles
  if s.requires_liftgate and not any(v.has_liftgate for v in vs):
    return "needs liftgate, none available"
  if s.max_vehicle_length_ft < min((v.length_ft for v in vs), default=53):
    return f"site limited to {s.max_vehicle_length_ft} ft vehicles"
  if s.priority == "FLEX":
    return "FLEX order deferred: cheaper to deliver on the next scheduled day"
  return "no truck could reach it inside its window within driver hours and capacity"


def evaluate_static_plan(problem: Problem) -> Optional[PlanResult]:
  """Re-prices today's TMW static routes with the same travel and unload model."""
  routes = q(
      "SELECT * FROM routes WHERE dc_id = :dc_id AND route_date = :d AND source = 'TMW_STATIC' ORDER BY route_id",
      dc_id=problem.dc["dc_id"],
      d=problem.date,
  )
  if not routes:
    return None
  stops = q(
      "SELECT rs.* FROM route_stops rs JOIN routes r ON rs.route_id = r.route_id "
      "WHERE r.dc_id = :dc_id AND r.route_date = :d AND r.source = 'TMW_STATIC' ORDER BY rs.route_id, rs.stop_seq",
      dc_id=problem.dc["dc_id"],
      d=problem.date,
  )
  by_order = {s.order_id: s for s in problem.stops}
  points = [problem.depot] + [s.point for s in problem.stops]
  lo = min((v.earliest_start for v in problem.vehicles), default=0)
  matrix = build_matrix(points, problem.depot, problem.disruptions, (lo, lo + 16 * 60))
  by_trailer = {v.trailer_id: v for v in problem.vehicles}
  results, served = [], set()
  for r in routes:
    seq = [by_order[s["order_id"]] for s in stops if s["route_id"] == r["route_id"] and s["order_id"] in by_order]
    v = by_trailer.get(r["trailer_id"]) or (problem.vehicles[0] if problem.vehicles else None)
    if not seq or v is None:
      continue
    served.update(s.order_id for s in seq)
    results.append(simulate_route(v, seq, problem.depot, matrix, problem.costs, int(r["depart_min"])))
  dropped = [s for s in problem.stops if s.order_id not in served]
  return PlanResult(routes=results, dropped=dropped, status="OK", impacted_legs=len(matrix.impacted_legs))


def _savings(base: dict, opt: dict) -> dict:
  out = {}
  for k in ("routes", "miles", "duty_hours", "cost_usd", "co2_kg", "late_stops"):
    b, o = base.get(k, 0), opt.get(k, 0)
    out[k] = {
        "tmw_static": b,
        "optimized": o,
        "change": round(o - b, 1),
        "change_pct": round(100 * (o - b) / b, 1) if b else None,
    }
  return out


def _persist(plan_id: str, scenario: str, problem: Problem, result: PlanResult, params: dict, baseline: Optional[dict]):
  repo = get_repository()
  route_rows, stop_rows = [], []
  for i, r in enumerate(result.routes, start=1):
    rid = f"{plan_id}-R{i:02d}"
    route_rows.append({
        "route_id": rid, "plan_id": plan_id, "source": "AI_OPTIMIZED", "dc_id": problem.dc["dc_id"],
        "route_date": problem.date, "tractor_id": r.vehicle.tractor_id, "trailer_id": r.vehicle.trailer_id,
        "driver_id": r.vehicle.driver_id, "depart_min": r.depart_min, "return_min": r.return_min,
        "stop_count": len(r.stops), "total_miles": round(r.total_miles, 1), "total_duration_min": r.duration_min,
        "total_cases": r.cases, "est_cost_usd": round(r.cost_usd, 2), "late_stops": r.late_stops, "status": "PLANNED",
    })
    for s in r.stops:
      stop_rows.append({
          "route_id": rid, "stop_seq": s.seq, "order_id": s.order_id, "customer_id": s.customer_id,
          "eta_min": s.arrival_min, "etd_min": s.departure_min, "miles_from_prev": round(s.miles_from_prev, 1),
          "window_ok": s.late_min == 0,
      })
  t = result.totals
  repo.insert("routes", route_rows)
  repo.insert("route_stops", stop_rows)
  repo.insert("optimization_runs", [{
      "plan_id": plan_id, "dc_id": problem.dc["dc_id"], "route_date": problem.date, "scenario": scenario,
      "parameters": params, "orders_planned": t["stops"], "orders_dropped": t["dropped_orders"],
      "routes_used": t["routes"], "total_miles": t["miles"], "total_cost_usd": t["cost_usd"],
      "baseline_miles": (baseline or {}).get("miles"), "baseline_cost_usd": (baseline or {}).get("cost_usd"),
      "late_stops": t["late_stops"], "co2_kg": t["co2_kg"], "created_at": now_ts(),
  }])
  return [r["route_id"] for r in route_rows]


def _run(
    dc_id: str,
    delivery_date: str,
    scenario: str,
    max_trucks: int,
    window_extension_min: int,
    allow_late: bool,
    use_learned_service_times: bool,
    include_disruptions: bool,
    time_limit_s: int,
    persist: bool = True,
) -> dict:
  problem = load_problem(dc_id, delivery_date, use_learned_service_times, include_disruptions)
  if not problem.stops:
    raise ToolError(f"No open orders for {problem.dc['dc_id']} on {problem.date}.")
  if window_extension_min > 0:
    # Stores agreed to wider windows, so lateness is measured against those.
    problem.stops = [
        replace(s, window_start=max(0, s.window_start - window_extension_min), window_end=s.window_end + window_extension_min)
        for s in problem.stops
    ]
  opts = SolverOptions(
      time_limit_s=time_limit_s or get_settings().solver_time_limit_s,
      allow_late=allow_late,
      max_vehicles=max_trucks if max_trucks and max_trucks > 0 else None,
      max_route_duration_min=int(get_settings().max_route_hours * 60),
  )
  result = solve(problem.depot, problem.stops, problem.vehicles, problem.costs, opts, problem.disruptions)
  if result.status != "OK":
    raise ToolError(f"Solver returned {result.status}. Try allow_late=True, more trucks or wider windows.")
  baseline = evaluate_static_plan(problem)
  base_totals = baseline.totals if baseline else None
  plan_id = new_id(f"PLN-{problem.dc['dc_id'].split('-')[1][:3]}")
  params = {
      "scenario": scenario, "max_trucks": max_trucks, "window_extension_min": window_extension_min,
      "allow_late": allow_late, "learned_service_times": use_learned_service_times,
      "disruptions": include_disruptions, "time_limit_s": opts.time_limit_s,
  }
  route_ids = _persist(plan_id, scenario, problem, result, params, base_totals) if persist else []
  routes = []
  for rid, r in zip(route_ids or [None] * len(result.routes), result.routes):
    summary = r.summary()
    summary["route_id"] = rid
    summary["stop_sequence"] = [s.customer_id for s in r.stops]
    routes.append(summary)
  return {
      "plan_id": plan_id,
      "dc_id": problem.dc["dc_id"],
      "delivery_date": str(problem.date),
      "scenario": scenario,
      "parameters": params,
      "totals": result.totals,
      "tmw_static_baseline": base_totals,
      "vs_baseline": _savings(base_totals, result.totals) if base_totals else None,
      "disruptions_applied": [
          {"event_id": d.event_id, "multiplier": d.factor, "description": d.description} for d in problem.disruptions
      ],
      "legs_slowed_by_disruptions": result.impacted_legs,
      "dropped_orders": [
          {"order_id": s.order_id, "customer_id": s.customer_id, "name": s.name, "priority": s.priority,
           "reason": _dropped_reason(s, problem)}
          for s in result.dropped
      ],
      "routes": routes[:MAX_ROUTES_IN_REPLY],
      "routes_truncated": max(0, len(routes) - MAX_ROUTES_IN_REPLY),
  }


def optimize_routes(
    dc_id: str,
    delivery_date: str,
    tool_context: ToolContext,
    max_trucks: int = 0,
    window_extension_min: int = 0,
    allow_late: bool = True,
    use_learned_service_times: bool = True,
    include_disruptions: bool = True,
    time_limit_s: int = 0,
) -> dict:
  """Builds an optimized delivery plan for one DC and date and saves it.

  Solves a vehicle routing problem with multi-temperature capacity, receiving
  windows, learned unload times, driver hours of service, site restrictions
  and live traffic/weather, then compares it with today's TMW static routes.

  Args:
    dc_id: Distribution center id, e.g. "DC-TEMPLE-TX".
    delivery_date: YYYY-MM-DD.
    max_trucks: Cap on trucks to dispatch. 0 means use the whole available fleet.
    window_extension_min: Minutes to widen every receiving window (what-if).
    allow_late: Allow arrivals up to 60 minutes past window close, penalized.
    use_learned_service_times: Use p75 unload time from history instead of TMS master data.
    include_disruptions: Apply traffic and weather events for that date.
    time_limit_s: Solver time budget in seconds. 0 uses the configured default.

  Returns:
    plan_id, totals (routes, miles, cost, CO2, late stops), the same metrics
    for the TMW static plan with deltas, dropped orders with reasons, and one
    summary per route.
  """
  out = _run(dc_id, delivery_date, "BASE", max_trucks, window_extension_min, allow_late,
             use_learned_service_times, include_disruptions, time_limit_s)
  tool_context.state["last_plan_id"] = out["plan_id"]
  tool_context.state["last_dc_id"] = out["dc_id"]
  tool_context.state["last_delivery_date"] = out["delivery_date"]
  return out


def run_what_if_scenarios(dc_id: str, delivery_date: str, tool_context: ToolContext) -> dict:
  """Runs a standard set of what-if scenarios for a DC and date and compares them.

  Scenarios: BASE (current constraints), FEWER_TRUCKS (two fewer units than
  BASE used), WIDER_WINDOWS (stores accept +30 minutes), TMS_UNLOAD_TIMES
  (plan with TMS master-data unload times instead of learned ones) and
  NO_DISRUPTIONS (ignore traffic/weather, shows the cost of the disruptions).

  Args:
    dc_id: Distribution center id.
    delivery_date: YYYY-MM-DD.

  Returns:
    A comparison table of trucks, miles, cost, late stops and dropped orders
    per scenario. Only BASE is saved as a plan.
  """
  t = 6
  base = _run(dc_id, delivery_date, "BASE", 0, 0, True, True, True, t)
  used = base["totals"]["routes"]
  scenarios = {
      "BASE": base,
      "FEWER_TRUCKS": _run(dc_id, delivery_date, "WHAT_IF", max(1, used - 2), 0, True, True, True, t, persist=False),
      "WIDER_WINDOWS": _run(dc_id, delivery_date, "WHAT_IF", 0, 30, True, True, True, t, persist=False),
      "TMS_UNLOAD_TIMES": _run(dc_id, delivery_date, "WHAT_IF", 0, 0, True, False, True, t, persist=False),
      "NO_DISRUPTIONS": _run(dc_id, delivery_date, "WHAT_IF", 0, 0, True, True, False, t, persist=False),
  }
  tool_context.state["last_plan_id"] = base["plan_id"]
  table = []
  for name, r in scenarios.items():
    tt = r["totals"]
    table.append({
        "scenario": name, "trucks": tt["routes"], "miles": tt["miles"], "cost_usd": tt["cost_usd"],
        "late_stops": tt["late_stops"], "dropped_orders": tt["dropped_orders"],
        "avg_utilization_pct": tt["avg_utilization_pct"],
    })
  return {
      "dc_id": base["dc_id"],
      "delivery_date": base["delivery_date"],
      "saved_plan_id": base["plan_id"],
      "tmw_static_baseline": base["tmw_static_baseline"],
      "scenarios": table,
      "notes": [
          "TMS_UNLOAD_TIMES looks cheaper on paper because master-data unload times are optimistic; "
          "plans built on them run late in practice.",
          "NO_DISRUPTIONS minus BASE is the cost of today's traffic and weather.",
          "A scenario with dropped orders looks cheaper only because undelivered orders carry no cost here; "
          "those customers would need another truck or a next-day delivery.",
      ],
  }


def get_route_plan(plan_id: str, route_id: str = "") -> dict:
  """Returns a saved plan, or one route of it with stop-by-stop ETAs.

  Args:
    plan_id: Plan id returned by optimize_routes.
    route_id: Optional route id inside the plan. Empty returns all route headers.

  Returns:
    Plan header and route headers, or for a single route every stop with
    ETA, ETD, receiving window and whether the stop is on time.
  """
  runs = q("SELECT * FROM optimization_runs WHERE plan_id = :p", p=plan_id)
  if not runs:
    raise ToolError(f"Unknown plan {plan_id!r}")
  routes = q("SELECT * FROM routes WHERE plan_id = :p ORDER BY route_id", p=plan_id)
  if not route_id:
    return {
        "plan": runs[0],
        "routes": [
            {k: r[k] for k in ("route_id", "tractor_id", "trailer_id", "driver_id", "stop_count",
                               "total_miles", "total_cases", "late_stops", "est_cost_usd", "status")}
            | {"depart": fmt_time(r["depart_min"]), "return": fmt_time(r["return_min"])}
            for r in routes
        ],
    }
  match = [r for r in routes if r["route_id"] == route_id]
  if not match:
    raise ToolError(f"Route {route_id!r} is not in plan {plan_id}")
  stops = q(
      "SELECT rs.*, c.name, c.city, c.window_start_min, c.window_end_min FROM route_stops rs "
      "JOIN customers c ON rs.customer_id = c.customer_id WHERE rs.route_id = :r ORDER BY rs.stop_seq",
      r=route_id,
  )
  return {
      "route": match[0] | {"depart": fmt_time(match[0]["depart_min"]), "return": fmt_time(match[0]["return_min"])},
      "stops": [
          {
              "seq": s["stop_seq"], "order_id": s["order_id"], "customer_id": s["customer_id"],
              "name": s["name"], "city": s["city"], "eta": fmt_time(s["eta_min"]), "etd": fmt_time(s["etd_min"]),
              "window": f"{fmt_time(s['window_start_min'])}-{fmt_time(s['window_end_min'])}",
              "on_time": str(s["window_ok"]).lower() in {"1", "true", "t"},
              "miles_from_prev": s["miles_from_prev"],
          }
          for s in stops
      ],
  }
