"""Disruption tools: measure traffic/weather risk and re-route trucks in flight."""

from __future__ import annotations

from dataclasses import replace

from google.adk.tools import ToolContext

from ..geo import Point, build_matrix, fmt_time, parse_time
from ..optimizer import SolverOptions, simulate_route, solve
from ._common import ToolError, load_problem, new_id, now_ts, q
from ..db.repository import get_repository


def _route_rows(plan_id: str, dc_id: str, date) -> list[dict]:
  if plan_id:
    return q("SELECT * FROM routes WHERE plan_id = :p ORDER BY route_id", p=plan_id)
  return q(
      "SELECT * FROM routes WHERE dc_id = :dc AND route_date = :d AND source = 'TMW_STATIC' ORDER BY route_id",
      dc=dc_id,
      d=date,
  )


def assess_disruption_impact(
    dc_id: str, delivery_date: str, tool_context: ToolContext, plan_id: str = ""
) -> dict:
  """Measures how today's traffic and weather events hit a route plan.

  Each route is simulated twice, with and without the active events, to show
  which trucks and stops pick up delay and which stops become late.

  Args:
    dc_id: Distribution center id.
    delivery_date: YYYY-MM-DD.
    plan_id: Plan to check. Empty uses the last plan from this session, or
      the TMW static routes if none was made.

  Returns:
    Active events and, per affected route, added minutes, stops turned late
    and the events responsible, worst first.
  """
  plan_id = plan_id or tool_context.state.get("last_plan_id", "")
  with_d = load_problem(dc_id, delivery_date, include_disruptions=True)
  if not with_d.disruptions:
    return {"dc_id": with_d.dc["dc_id"], "delivery_date": str(with_d.date), "events": [],
            "message": "No active traffic or weather events near this DC on this date."}
  routes = _route_rows(plan_id, with_d.dc["dc_id"], with_d.date)
  if not routes:
    raise ToolError("No routes found to assess. Run optimize_routes first or check the date.")
  route_ids = [r["route_id"] for r in routes]
  stops = []
  for rid in route_ids:
    stops += q("SELECT * FROM route_stops WHERE route_id = :r ORDER BY stop_seq", r=rid)
  by_order = {s.order_id: s for s in with_d.stops}
  points = [with_d.depot] + [s.point for s in with_d.stops]
  lo = min(v.earliest_start for v in with_d.vehicles)
  m_free = build_matrix(points, with_d.depot, [], (lo, lo + 16 * 60))
  m_live = build_matrix(points, with_d.depot, with_d.disruptions, (lo, lo + 16 * 60))
  by_trailer = {v.trailer_id: v for v in with_d.vehicles}

  impacted = []
  for r in routes:
    seq = [by_order[s["order_id"]] for s in stops if s["route_id"] == r["route_id"] and s["order_id"] in by_order]
    v = by_trailer.get(r["trailer_id"])
    if not seq or v is None:
      continue
    free = simulate_route(v, seq, with_d.depot, m_free, with_d.costs, int(r["depart_min"]))
    live = simulate_route(v, seq, with_d.depot, m_live, with_d.costs, int(r["depart_min"]))
    added = live.duration_min - free.duration_min
    if added <= 0:
      continue
    newly_late = [
        {"customer_id": b.customer_id, "name": b.name, "eta_was": fmt_time(a.arrival_min),
         "eta_now": fmt_time(b.arrival_min), "window_end": fmt_time(b.window_end), "late_min": b.late_min}
        for a, b in zip(free.stops, live.stops)
        if b.late_min > 0 and a.late_min == 0
    ]
    events = sorted({e for p in live.stops for e in p.traffic_events})
    impacted.append({
        "route_id": r["route_id"], "driver_id": r["driver_id"], "added_minutes": added,
        "late_stops_before": free.late_stops, "late_stops_with_events": live.late_stops,
        "stops_turned_late": newly_late, "events": events,
    })
  impacted.sort(key=lambda x: (-len(x["stops_turned_late"]), -x["added_minutes"]))
  return {
      "dc_id": with_d.dc["dc_id"],
      "delivery_date": str(with_d.date),
      "plan_assessed": plan_id or "TMW_STATIC",
      "events": [{"event_id": d.event_id, "multiplier": d.factor, "active": f"{fmt_time(d.start_min)}-{fmt_time(d.end_min)}",
                  "description": d.description} for d in with_d.disruptions],
      "routes_impacted": len(impacted),
      "total_added_minutes": sum(i["added_minutes"] for i in impacted),
      "impacted_routes": impacted[:15],
      "recommendation": (
          "Re-optimize the plan with include_disruptions=True, or re-sequence trucks already on the road "
          "with reoptimize_route_in_flight." if impacted else "Plan is resilient to today's events."
      ),
  }


def reoptimize_route_in_flight(
    route_id: str, current_time: str, tool_context: ToolContext, completed_stops: int = -1
) -> dict:
  """Re-sequences the remaining stops of a truck that is already on the road.

  Uses the truck's position (its last completed stop), the time now, the
  driver's remaining hours and live traffic/weather to find the best order
  for the stops left, and compares it with staying on the current sequence.

  Args:
    route_id: Route to re-plan (from a plan or a TMW static route).
    current_time: Time now as HH:MM, e.g. "08:15".
    completed_stops: Stops already delivered. -1 infers it from planned ETDs.

  Returns:
    New stop order with ETAs, the ETAs if the driver kept the old order,
    late stops under each, and a new plan id when the change is saved.
  """
  routes = q("SELECT * FROM routes WHERE route_id = :r", r=route_id)
  if not routes:
    raise ToolError(f"Unknown route {route_id!r}")
  route = routes[0]
  rstops = q("SELECT * FROM route_stops WHERE route_id = :r ORDER BY stop_seq", r=route_id)
  now = parse_time(current_time)
  if completed_stops < 0:
    completed_stops = sum(1 for s in rstops if int(s["etd_min"]) <= now)
  completed_stops = min(completed_stops, len(rstops))
  if completed_stops >= len(rstops):
    return {"route_id": route_id, "message": "All stops on this route are already complete."}

  problem = load_problem(route["dc_id"], route["route_date"], include_disruptions=True,
                         order_ids=[s["order_id"] for s in rstops])
  by_order = {s.order_id: s for s in problem.stops}
  done = [by_order[s["order_id"]] for s in rstops[:completed_stops] if s["order_id"] in by_order]
  remaining = [by_order[s["order_id"]] for s in rstops[completed_stops:] if s["order_id"] in by_order]
  here = done[-1].point if done else problem.depot
  truck = Point(f"TRUCK@{route_id}", here.lat, here.lon)

  base_v = next((v for v in problem.vehicles if v.trailer_id == route["trailer_id"]), None)
  if base_v is None:
    raise ToolError(f"Trailer {route['trailer_id']} is not in the available fleet.")
  used = max(0, now - int(route["depart_min"]))
  live_v = replace(
      base_v, earliest_start=now, latest_start=now, start_point=truck,
      max_duty_min=max(60, base_v.max_duty_min - used), max_drive_min=max(60, base_v.max_drive_min - int(used * 0.6)),
  )
  points = [problem.depot, truck] + [s.point for s in remaining]
  matrix = build_matrix(points, problem.depot, problem.disruptions, (now, now + 10 * 60))

  keep = simulate_route(live_v, remaining, problem.depot, matrix, problem.costs, now)
  new = solve(problem.depot, remaining, [live_v], problem.costs, SolverOptions(time_limit_s=5, max_late_min=240),
              problem.disruptions, matrix)
  if new.status != "OK" or not new.routes:
    raise ToolError(f"Re-optimization failed: {new.status}")
  best = new.routes[0]
  improved = (best.late_stops, best.cost_usd) < (keep.late_stops, keep.cost_usd)

  result = {
      "route_id": route_id,
      "current_time": fmt_time(now),
      "truck_position": {"after_stop": done[-1].customer_id if done else "DC", "lat": here.lat, "lon": here.lon},
      "completed_stops": completed_stops,
      "events_considered": [d.event_id for d in problem.disruptions],
      "keep_current_sequence": {
          "late_stops": keep.late_stops, "miles": round(keep.total_miles, 1), "return": fmt_time(keep.return_min),
          "stops": [s.as_dict() for s in keep.stops],
      },
      "reoptimized": {
          "late_stops": best.late_stops, "miles": round(best.total_miles, 1), "return": fmt_time(best.return_min),
          "stops": [s.as_dict() for s in best.stops],
          "orders_that_cannot_fit": [s.order_id for s in new.dropped],
      },
      "recommendation": "Switch to the re-optimized sequence." if improved else "Keep the current sequence.",
  }

  if improved:
    plan_id = new_id("RPL")
    new_route_id = f"{route_id}-V2"
    repo = get_repository()
    repo.insert("routes", [{
        **{k: route[k] for k in ("dc_id", "route_date", "tractor_id", "trailer_id", "driver_id")},
        "route_id": new_route_id, "plan_id": plan_id, "source": "AI_OPTIMIZED", "depart_min": route["depart_min"],
        "return_min": best.return_min, "stop_count": len(rstops), "total_miles": round(best.total_miles, 1),
        "total_duration_min": best.return_min - int(route["depart_min"]), "total_cases": best.cases,
        "est_cost_usd": round(best.cost_usd, 2), "late_stops": best.late_stops, "status": "IN_PROGRESS",
    }])
    stop_rows = [
        {"route_id": new_route_id, "stop_seq": i + 1, "order_id": s["order_id"], "customer_id": s["customer_id"],
         "eta_min": s["eta_min"], "etd_min": s["etd_min"], "miles_from_prev": s["miles_from_prev"], "window_ok": s["window_ok"]}
        for i, s in enumerate(rstops[:completed_stops])
    ] + [
        {"route_id": new_route_id, "stop_seq": completed_stops + p.seq, "order_id": p.order_id,
         "customer_id": p.customer_id, "eta_min": p.arrival_min, "etd_min": p.departure_min,
         "miles_from_prev": round(p.miles_from_prev, 1), "window_ok": p.late_min == 0}
        for p in best.stops
    ]
    repo.insert("route_stops", stop_rows)
    repo.insert("optimization_runs", [{
        "plan_id": plan_id, "dc_id": route["dc_id"], "route_date": route["route_date"], "scenario": "REOPTIMIZE",
        "parameters": {"route_id": route_id, "current_time": fmt_time(now), "completed_stops": completed_stops},
        "orders_planned": len(best.stops), "orders_dropped": len(new.dropped), "routes_used": 1,
        "total_miles": round(best.total_miles, 1), "total_cost_usd": round(best.cost_usd, 2),
        "baseline_miles": round(keep.total_miles, 1), "baseline_cost_usd": round(keep.cost_usd, 2),
        "late_stops": best.late_stops, "co2_kg": round(best.co2_kg, 1), "created_at": now_ts(),
    }])
    result["saved_plan_id"] = plan_id
    result["saved_route_id"] = new_route_id
    tool_context.state["last_plan_id"] = plan_id
  return result
