"""Event-driven re-planning: trigger -> assess -> re-plan -> explain -> approve.

Each operational event (from telematics, the driver app, TMW, a traffic feed
or a customer, usually arriving over Pub/Sub) re-plans *only* the routes it
touches. Product already loaded on a truck stays on that truck (stops are
pinned), so in-flight trucks are re-sequenced, while new work (an added
order, cold product re-picked after a reefer failure) can go to a truck that
has not left the DC yet or to a spare unit.

Hard constraints are never relaxed: capacity, temperature (a failed reefer
gets zero cold capacity), hours of service and dock appointments. Ordinary
receiving windows are soft with a lateness penalty.

A change is escalated to a human dispatcher when an SLA breach cannot be
avoided, when it costs more than ESCALATION_COST_USD, or always for food
safety (reefer) events.

DWELL_OVERRUN comes from the geofence engine (a truck still inside a
customer geofence well past its planned unload time) and is re-planned like
a delay from the customer's location. Every re-plan also reports its Retail
and Restaurant OTD impact: restaurants are judged against the ETA they were
already given, retail against the receiving window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from .. import pcmiler
from ..config import get_settings
from ..db.repository import get_repository
from ..geo import Disruption, Point, build_matrix, fmt_time, haversine_miles, parse_time
from ..optimizer import PlanResult, SolverOptions, Stop, Vehicle, simulate_route, solve
from ..otd import is_on_time, segment_group
from ._common import Problem, ToolError, as_date, load_otd_policies, load_problem, new_id, now_ts, q

EVENT_TYPES = ("DELAY", "BREAKDOWN", "ORDER_ADDED", "ORDER_CANCELLED", "ROAD_CLOSURE", "NO_SHOW", "REEFER_TEMP_ALERT",
               "DWELL_OVERRUN")
HOOKUP_MIN = 30        # rescue tractor hook-up at a breakdown
REPICK_MIN = 60        # pick, load and dispatch a spare unit from the DC
FAILED = "FAILED"


@dataclass
class Live:
  """A route as it stands at the moment of the event."""

  route: dict
  done: list[Stop]
  remaining: list[Stop]
  vehicle: Vehicle           # live vehicle: position, time available, hours left
  planned_vehicle: Vehicle   # same truck without the event's delay


def _latest_plan(dc_id: str, date) -> Optional[str]:
  runs = q(
      "SELECT plan_id, created_at FROM optimization_runs WHERE dc_id = :dc AND route_date = :d AND scenario = 'BASE'",
      dc=dc_id, d=date,
  )
  return max(runs, key=lambda r: r["created_at"])["plan_id"] if runs else None


def _plan_routes(plan_id: Optional[str], dc_id: str, date) -> tuple[list[dict], dict[str, list[dict]]]:
  if plan_id:
    routes = q("SELECT * FROM routes WHERE plan_id = :p ORDER BY route_id", p=plan_id)
  else:
    routes = q(
        "SELECT * FROM routes WHERE dc_id = :dc AND route_date = :d AND source = 'TMW_STATIC' ORDER BY route_id",
        dc=dc_id, d=date,
    )
  stops: dict[str, list[dict]] = {r["route_id"]: [] for r in routes}
  for r in routes:
    stops[r["route_id"]] = q("SELECT * FROM route_stops WHERE route_id = :r ORDER BY stop_seq", r=r["route_id"])
  return routes, stops


def _vehicle_for(route: dict, problem: Problem) -> Vehicle:
  for v in problem.vehicles:
    if v.trailer_id == route["trailer_id"] and v.tractor_id == route["tractor_id"]:
      return v
  for v in problem.vehicles:
    if v.trailer_id == route["trailer_id"]:
      return v
  raise ToolError(f"Trailer {route['trailer_id']} on route {route['route_id']} is not in the fleet.")


def _live(route: dict, rstops: list[dict], problem: Problem, now: int, extra_delay: int = 0,
          position: Optional[Point] = None) -> Live:
  by_order = {s.order_id: s for s in problem.stops}
  done = [by_order[s["order_id"]] for s in rstops if int(s["etd_min"]) <= now and s["order_id"] in by_order]
  remaining = [by_order[s["order_id"]] for s in rstops if int(s["etd_min"]) > now and s["order_id"] in by_order]
  depart = int(route["depart_min"])
  base = _vehicle_for(route, problem)
  rid = route["route_id"]
  remaining = [replace(s, pinned_vehicle_id=rid) for s in remaining]
  if position is None and (done or now > depart):
    position = done[-1].point if done else problem.depot
  start_point = Point(f"TRUCK@{rid}", position.lat, position.lon) if position else None

  def at(avail: int) -> Vehicle:
    used = max(0, avail - depart)
    return replace(
        base, vehicle_id=rid, earliest_start=avail, latest_start=avail, start_point=start_point,
        max_duty_min=max(30, base.max_duty_min - used), max_drive_min=max(30, base.max_drive_min - int(used * 0.55)),
    )

  avail = max(now, depart)
  return Live(route, done, remaining, at(avail + extra_delay), at(avail))


def _spare_units(problem: Problem, routes: list[dict], earliest: int, need_cold: bool = False) -> list[Vehicle]:
  used_tr = {r["tractor_id"] for r in routes}
  used_tl = {r["trailer_id"] for r in routes}
  spares = [
      replace(v, vehicle_id=f"SPARE-{v.tractor_id}", earliest_start=earliest, latest_start=earliest + 120)
      for v in problem.vehicles
      if v.tractor_id not in used_tr and v.trailer_id not in used_tl and (v.capacity_cold_cases > 0 or not need_cold)
  ]
  return spares[:2]


def _spare_tractor(dc_id: str, routes: list[dict]) -> Optional[str]:
  used = {r["tractor_id"] for r in routes}
  for t in q("SELECT * FROM tractors WHERE dc_id = :dc AND unit_type = 'TRACTOR' ORDER BY tractor_id", dc=dc_id):
    if t["status"] == "AVAILABLE" and t["tractor_id"] not in used:
      return t["tractor_id"]
  return None


def _route_of(routes, rstops, tractor_id=None, order_id=None, customer_id=None) -> dict:
  for r in routes:
    if tractor_id and r["tractor_id"] == tractor_id:
      return r
    for s in rstops[r["route_id"]]:
      if (order_id and s["order_id"] == order_id) or (customer_id and s["customer_id"] == customer_id):
        return r
  raise ToolError(
      f"No route in this plan uses tractor={tractor_id} order={order_id} customer={customer_id}. "
      "Use simulate_route_event with a route_id from the current plan."
  )


def _seq(stops) -> str:
  return " > ".join(getattr(s, "customer_id", "?") for s in stops) or "(none)"


def _handle(event: dict, plan_id: str = "") -> dict:
  t0 = time.perf_counter()
  s = get_settings()
  etype = event["event_type"]
  now = int(event["event_min"])
  problem = load_problem(event["dc_id"], event["event_date"], include_disruptions=True)
  payload = event.get("payload") or {}
  if isinstance(payload, str):
    import json
    payload = json.loads(payload or "{}")
  # Telematics and geofence events know the route the truck is actually running.
  running = q("SELECT plan_id, source FROM routes WHERE route_id = :r", r=payload["route_id"]) if payload.get("route_id") else []
  if running:
    plan_id = running[0]["plan_id"] or ""
  else:
    plan_id = plan_id or _latest_plan(problem.dc["dc_id"], problem.date) or ""
  routes, rstops = _plan_routes(plan_id or None, problem.dc["dc_id"], problem.date)
  if not routes:
    raise ToolError("No plan or TMW static routes exist for this DC and date.")

  disruptions = list(problem.disruptions)
  lives: dict[str, Live] = {}
  new_stops: list[Stop] = []
  extra_vehicles: list[Vehicle] = []
  removed: set[str] = set()
  escalations: list[str] = []
  notes: list[str] = []
  extra_cost = 0.0  # cost outside the routes themselves (rescue tractor, idle driver time)
  cm = problem.costs

  def live(r, **kw):
    lives[r["route_id"]] = _live(r, rstops[r["route_id"]], problem, now, **kw)
    return lives[r["route_id"]]

  if etype in ("DELAY", "DWELL_OVERRUN"):
    r = _route_of(routes, rstops, tractor_id=event.get("tractor_id"))
    delay = int(event.get("delay_min") or 0)
    if delay < s.delay_trigger_min:
      return _no_action(event, plan_id, f"Delay of {delay} min is under the {s.delay_trigger_min} min re-plan trigger; ETAs updated only.", t0)
    pos = None
    cust = problem.customers.get(event.get("customer_id") or "")
    if etype == "DWELL_OVERRUN" and cust:
      pos = Point("DOCK", float(cust["lat"]), float(cust["lon"]))
    live(r, extra_delay=delay, position=pos)
    extra_cost += delay / 60 * cm.driver_cost_per_hour_usd
    if etype == "DWELL_OVERRUN":
      notes.append(f"Geofence shows the truck on route {r['route_id']} still unloading at "
                   f"{cust['name'] if cust else event.get('customer_id')}, about {delay} min over plan.")
    else:
      notes.append(f"Route {r['route_id']} is running {delay} min behind.")

  elif etype == "BREAKDOWN":
    r = _route_of(routes, rstops, tractor_id=event.get("tractor_id"))
    pos = Point("BRK", float(event["lat"]), float(event["lon"])) if event.get("lat") is not None else None
    spare = _spare_tractor(problem.dc["dc_id"], routes)
    probe = _live(r, rstops[r["route_id"]], problem, now, position=pos)
    here = probe.vehicle.start_point or problem.depot
    rescue_miles = haversine_miles(problem.depot.lat, problem.depot.lon, here.lat, here.lon) * 1.22
    rescue = int(round(rescue_miles / 45 * 60)) + HOOKUP_MIN
    # Rescue driver drives out and back with the broken tractor towed/serviced; stranded driver waits.
    extra_cost += 2 * rescue_miles * (cm.cost_per_mile_usd + cm.fuel_price_usd_gal / 6.5) + 2 * rescue / 60 * cm.driver_cost_per_hour_usd
    if not spare:
      escalations.append("No spare tractor at the DC: a rental or a neighbouring DC unit is needed.")
      rescue += 120
    live(r, extra_delay=rescue, position=pos)
    notes.append(
        f"Tractor {event.get('tractor_id')} is out of service. Spare tractor {spare or '(none)'} leaves the DC and hooks "
        f"to trailer {r['trailer_id']} at the breakdown site, about {rescue} min from now; the product stays on the trailer."
    )

  elif etype == "REEFER_TEMP_ALERT":
    r = _route_of(routes, rstops, tractor_id=event.get("tractor_id"))
    temp = float(payload.get("temp_f", 99))
    if temp <= s.reefer_max_temp_f:
      return _no_action(event, plan_id, f"Reefer at {temp}F is inside the {s.reefer_max_temp_f}F limit; keep monitoring.", t0)
    lv = live(r)
    # Temperature is a hard constraint: the failed trailer carries no cold product from here on.
    lv.vehicle = replace(lv.vehicle, capacity_cold_cases=0)
    stripped = []
    spares = _spare_units(problem, routes, now + REPICK_MIN, need_cold=True)
    for st in lv.remaining:
      if st.cold_cases > 0:
        new_stops.append(replace(st, order_id=f"{st.order_id}-COLD", cases=st.cold_cases, cold_cases=st.cold_cases,
                                 weight_lbs=int(st.weight_lbs * st.cold_cases / max(st.cases, 1)),
                                 cube_ft3=round(st.cube_ft3 * st.cold_cases / max(st.cases, 1), 1),
                                 pinned_vehicle_id=None, service_min=max(10, st.service_min // 2)))
        dry = st.cases - st.cold_cases
        stripped.append(replace(st, cases=dry, cold_cases=0) if dry > 0 else None)
      else:
        stripped.append(st)
    lv.remaining = [x for x in stripped if x is not None]
    extra_vehicles += spares
    escalations.append(f"Food safety: {payload.get('zone', 'cold')} zone at {temp}F. QA must decide on the product on board.")
    notes.append(f"Cold product for {len(new_stops)} remaining stops is re-picked at the DC and sent on a spare reefer unit; "
                 f"route {r['route_id']} continues with dry product only.")

  elif etype in ("ORDER_CANCELLED", "NO_SHOW"):
    r = _route_of(routes, rstops, order_id=event.get("order_id"), customer_id=event.get("customer_id"))
    oid = event.get("order_id") or next(
        x["order_id"] for x in rstops[r["route_id"]] if x["customer_id"] == event.get("customer_id"))
    removed.add(oid)
    lv = live(r)
    if etype == "NO_SHOW":
      cust = problem.customers.get(event.get("customer_id") or "", {})
      pos = Point(f"TRUCK@{r['route_id']}", float(cust.get("lat", problem.depot.lat)), float(cust.get("lon", problem.depot.lon)))
      lv.vehicle = replace(lv.vehicle, start_point=pos)
      notes.append(f"{cust.get('name', oid)} was closed at arrival. Product stays on the truck; order {oid} is rebooked for the next delivery day.")
    else:
      notes.append(f"Order {oid} was cancelled before delivery; it is removed from route {r['route_id']}.")
    lv.remaining = [x for x in lv.remaining if x.order_id != oid]

  elif etype == "ORDER_ADDED":
    cid = event["customer_id"]
    c = problem.customers.get(cid)
    if not c:
      raise ToolError(f"Unknown customer {cid}")
    dry, chill, frozen = (int(payload.get(k, 0)) for k in ("dry_cases", "chill_cases", "frozen_cases"))
    oid = event.get("order_id") or new_id(f"O-ADD-{problem.date:%Y%m%d}")
    order_row = {
        "order_id": oid, "tmw_ord_hdrnumber": None, "dc_id": problem.dc["dc_id"], "customer_id": cid,
        "delivery_date": problem.date, "dry_cases": dry, "chill_cases": chill, "frozen_cases": frozen,
        "weight_lbs": dry * 18 + chill * 20 + frozen * 22, "cube_ft3": round((dry + chill + frozen) * 1.7, 1),
        "priority": payload.get("priority", "HOT"), "status": "OPEN",
    }
    if not q("SELECT order_id FROM orders WHERE order_id = :o", o=oid):
      get_repository().insert("orders", [order_row])
    from ..planning import stops_from_rows
    stop = stops_from_rows([order_row], problem.customers, problem.learned_service)[0]
    new_stops.append(stop)
    problem.stops.append(stop)
    # Only trucks still at the DC can take extra product, plus a spare unit.
    at_dc = [r for r in routes if int(r["depart_min"]) > now + 30]
    at_dc.sort(key=lambda r: min(
        (haversine_miles(float(c["lat"]), float(c["lon"]), x.point.lat, x.point.lon)
         for x in _live(r, rstops[r["route_id"]], problem, now).remaining), default=999))
    for r in at_dc[:2]:
      live(r)
    extra_vehicles += _spare_units(problem, routes, now + REPICK_MIN, need_cold=chill + frozen > 0)[:1]
    notes.append(f"New {order_row['priority']} order {oid} for {c['name']} ({dry + chill + frozen} cases). "
                 f"Candidates: {len(at_dc[:2])} trucks not yet dispatched and {min(1, len(extra_vehicles))} spare unit.")

  elif etype == "ROAD_CLOSURE":
    closure = Disruption(event["event_id"], float(event["lat"]), float(event["lon"]), float(event["radius_miles"] or 3),
                         now, int(payload.get("end_min", now + 300)), float(event["delay_factor"] or 3.0),
                         event.get("description", "Road closure"))
    disruptions.append(closure)
    for r in routes:
      probe = _live(r, rstops[r["route_id"]], problem, now)
      if not probe.remaining:
        continue
      pts = [problem.depot] + ([probe.vehicle.start_point] if probe.vehicle.start_point else []) + [x.point for x in probe.remaining]
      m0 = build_matrix(pts, problem.depot, problem.disruptions, (now, now + 600))
      m1 = build_matrix(pts, problem.depot, disruptions, (now, now + 600))
      a = simulate_route(probe.vehicle, probe.remaining, problem.depot, m0, problem.costs, probe.vehicle.earliest_start)
      b = simulate_route(probe.vehicle, probe.remaining, problem.depot, m1, problem.costs, probe.vehicle.earliest_start)
      if b.duration_min > a.duration_min:
        lives[r["route_id"]] = probe
    notes.append(f"{closure.description}: {len(lives)} routes have remaining legs through the closure.")
  else:
    raise ToolError(f"Unsupported event type {etype}. Supported: {', '.join(EVENT_TYPES)}")

  if not lives and not new_stops:
    return _no_action(event, plan_id, "No route is affected by this event.", t0)
  if not new_stops and not any(lv.remaining for lv in lives.values()):
    return _no_action(event, plan_id, "The affected trucks have already completed their deliveries; "
                      "only the return to the DC is impacted.", t0)

  # ---- re-plan the affected routes only -----------------------------------
  vehicles = [lv.vehicle for lv in lives.values()] + extra_vehicles
  pool = [st for lv in lives.values() for st in lv.remaining] + new_stops
  starts = [v.start_point for v in vehicles if v.start_point]
  pts = [problem.depot] + starts + [st.point if st.point.key == st.order_id else Point(st.order_id, st.point.lat, st.point.lon) for st in pool]
  window = (now, now + 12 * 60)
  m_new = build_matrix(pts, problem.depot, disruptions, window)
  m_old = build_matrix(pts, problem.depot, problem.disruptions, window)
  pool = [replace(st, point=Point(st.order_id, st.point.lat, st.point.lon)) for st in pool]
  by_id = {st.order_id: st for st in pool}

  planned = sum(
      simulate_route(lv.planned_vehicle, [by_id[x.order_id] for x in lv.remaining if x.order_id in by_id],
                     problem.depot, m_old, problem.costs, lv.planned_vehicle.earliest_start).cost_usd
      for lv in lives.values()
  )
  keep = {rid: simulate_route(lv.vehicle, [by_id[x.order_id] for x in lv.remaining], problem.depot, m_new,
                              problem.costs, lv.vehicle.earliest_start) for rid, lv in lives.items()}
  # Stops the driver could only reach by breaking hours of service count as failed.
  hos_fail = {
      rid: sum(1 for p in k.stops if p.departure_min - lives[rid].vehicle.earliest_start > lives[rid].vehicle.max_duty_min)
      for rid, k in keep.items()
  }
  for rid, n in hos_fail.items():
    if n:
      notes.append(f"Keeping route {rid} as planned would push the driver past hours of service for {n} stop(s).")
  late_before = sum(k.late_stops for k in keep.values()) + sum(hos_fail.values()) + len(new_stops)

  # A single truck re-sequence converges in a second or two; multi-truck
  # re-plans get the full budget. Both stay well under the 30 s target.
  budget = 2 if len(vehicles) == 1 and len(pool) <= 12 else s.replan_time_limit_s
  # Product is already loaded, so even FLEX orders should be delivered today
  # unless it is truly impossible.
  opts = SolverOptions(time_limit_s=budget, max_late_min=240, standard_drop_penalty_usd=50_000,
                       flex_drop_penalty_usd=5_000)
  result: PlanResult = solve(problem.depot, pool, vehicles, problem.costs, opts, disruptions, m_new)
  if result.status != "OK":
    raise ToolError(f"Re-plan failed: {result.status}")
  after_cost = sum(r.cost_usd for r in result.routes) + extra_cost
  if extra_cost:
    notes.append(f"Event handling cost outside the routes (rescue unit, idle driver time): ${extra_cost:,.0f}.")
  late_after = sum(r.late_stops for r in result.routes) + len(result.dropped)
  cost_impact = round(after_cost - planned, 2)

  otd = _otd_impact(problem, lives, rstops, keep, result, new_stops)
  if otd["restaurant_eta_moves_over_tolerance"]:
    notes.append(f"{len(otd['restaurant_eta_moves_over_tolerance'])} restaurant stop(s) move more than "
                 f"{otd['restaurant_tolerance_min']} min from the ETA they were given; send them an ETA update.")

  # ---- explain ---------------------------------------------------------
  changes = []
  by_vehicle = {r.vehicle.vehicle_id: r for r in result.routes}
  for rid, lv in lives.items():
    new = by_vehicle.get(rid)
    old = keep[rid]
    if new is None:
      changes.append(f"Route {rid}: no remaining stops.")
      continue
    order_changed = [p.customer_id for p in new.stops] != [p.customer_id for p in old.stops]
    changes.append(
        f"Route {rid} ({lv.route['driver_id']}): "
        + (f"re-sequenced to {_seq(new.stops)} (was {_seq(old.stops)}). " if order_changed else "same stop order. ")
        + f"Back at DC {fmt_time(new.return_min)}, late stops {old.late_stops} -> {new.late_stops}."
    )
  for r in result.routes:
    if r.vehicle.vehicle_id.startswith("SPARE-"):
      changes.append(f"Spare unit {r.vehicle.tractor_id}/{r.vehicle.trailer_id} leaves the DC at {fmt_time(r.depart_min)} "
                     f"for {_seq(r.stops)}.")
  for st in new_stops:
    owner = next((r.vehicle.vehicle_id for r in result.routes if any(p.order_id == st.order_id for p in r.stops)), None)
    if owner and not owner.startswith("SPARE-"):
      changes.append(f"New stop {st.customer_id} added to route {owner}, which has not left the DC yet.")

  hard_breach = [
      p for r in result.routes for p in r.stops
      if p.late_min > 0 and (by_id[p.order_id].hard_window or by_id[p.order_id].priority_tier == 1)
  ]
  if hard_breach:
    escalations.append(
        "SLA breach unavoidable for " + ", ".join(
            f"{p.customer_id}{' cold' if p.order_id.endswith('-COLD') else ''} ({p.late_min} min late)" for p in hard_breach[:5]))
  if result.dropped:
    escalations.append("Cannot deliver today: " + ", ".join(st.customer_id for st in result.dropped[:8]) + " (needs redelivery).")
  if cost_impact > s.escalation_cost_usd:
    escalations.append(f"Cost impact ${cost_impact:,.0f} is above the ${s.escalation_cost_usd:,.0f} approval threshold.")

  latency = round(time.perf_counter() - t0, 2)
  new_plan = new_id("EVP")
  status = "PENDING_APPROVAL" if escalations else "AUTO_APPLIED"
  explanation = " ".join(notes + changes)
  action_id = _persist(event, plan_id, new_plan, problem, result, by_id, lives, cost_impact, late_before,
                       late_after, escalations, status, explanation, latency, len(routes) - len(lives))
  return {
      "action_id": action_id,
      "event": {k: event.get(k) for k in ("event_id", "event_type", "description", "tractor_id", "customer_id", "order_id", "delay_min")}
               | {"time": fmt_time(now)},
      "source_plan_id": plan_id or "TMW_STATIC",
      "new_plan_id": new_plan,
      "status": status,
      "requires_human_approval": bool(escalations),
      "escalation_reasons": escalations,
      "affected_routes": list(lives),
      "spare_units_used": [r.vehicle.vehicle_id for r in result.routes if r.vehicle.vehicle_id.startswith("SPARE-")],
      "untouched_routes": len(routes) - len(lives),
      "kpis": {
          "late_or_failed_stops_if_no_change": late_before,
          "late_or_failed_stops_after_replan": late_after,
          "planned_cost_of_affected_work_usd": round(planned, 2),
          "replanned_cost_usd": round(after_cost, 2),
          "cost_impact_usd": cost_impact,
      },
      "otd_impact": otd,
      "what_changed": notes + changes,
      "replan_latency_s": latency,
      "latency_target_met": latency < 30,
  }


def _otd_impact(problem: Problem, lives: dict, rstops: dict, keep: dict, result: PlanResult, new_stops: list) -> dict:
  """Retail and Restaurant OTD of the affected stops, if nothing changes versus after the re-plan."""
  policies = load_otd_policies()
  promised = {s["order_id"]: int(s["eta_min"]) for rid in lives for s in rstops[rid] if s["eta_min"] is not None}
  def tally(routes):
    out = {}
    for r in routes:
      for p in r.stops:
        oid = p.order_id.removesuffix("-COLD")
        c = problem.customers.get(p.customer_id, {})
        g = segment_group(c.get("segment"))
        ok = is_on_time(policies[g], p.arrival_min, p.window_start, p.window_end, promised.get(oid, p.arrival_min))
        out[p.order_id] = (g, ok, p.arrival_min)
    return out
  before, after = tally(keep.values()), tally(result.routes)
  for st in new_stops:
    before.setdefault(st.order_id, (segment_group(problem.customers.get(st.customer_id, {}).get("segment")), False, None))
  res = {}
  for g in ("RETAIL", "RESTAURANT"):
    b = [v[1] for v in before.values() if v[0] == g]
    a = [v[1] for v in after.values() if v[0] == g]
    if b or a:
      res[g] = {"stops": max(len(b), len(a)), "on_time_if_no_change": sum(b), "on_time_after_replan": sum(a)}
  tol = policies["RESTAURANT"].late_tolerance_min
  moves = []
  for oid, (g, _, arr) in after.items():
    base = promised.get(oid.removesuffix("-COLD"))
    if g == "RESTAURANT" and base is not None and abs(arr - base) > tol:
      cust = next((p.customer_id for r in result.routes for p in r.stops if p.order_id == oid), None)
      moves.append({"customer_id": cust, "promised_eta": fmt_time(base), "new_eta": fmt_time(arr)})
  return {"by_group": res, "restaurant_tolerance_min": tol, "restaurant_eta_moves_over_tolerance": moves}


def _no_action(event: dict, plan_id: str, why: str, t0: float) -> dict:
  latency = round(time.perf_counter() - t0, 2)
  get_repository().insert("event_actions", [{
      "action_id": new_id("ACT"), "event_id": event["event_id"], "source_plan_id": plan_id or "TMW_STATIC",
      "new_plan_id": None, "affected_routes": [], "untouched_routes": None, "cost_impact_usd": 0.0,
      "late_stops_before": 0, "late_stops_after": 0, "requires_approval": False, "escalation_reasons": [],
      "status": "NO_ACTION", "explanation": why, "latency_s": latency, "created_at": now_ts(),
  }])
  return {"event_id": event["event_id"], "status": "NO_ACTION", "explanation": why, "replan_latency_s": latency}


def _persist(event, plan_id, new_plan, problem, result, by_id, lives, cost_impact, late_before, late_after,
             escalations, status, explanation, latency, untouched):
  repo = get_repository()
  pcmiler.stamp_routes(result.routes, problem.depot)
  route_rows, stop_rows = [], []
  for r in result.routes:
    vid = r.vehicle.vehicle_id
    lv = lives.get(vid)
    rid = f"{vid}-{new_plan}" if lv else f"{new_plan}-{vid}"
    depart = int(lv.route["depart_min"]) if lv else r.depart_min
    route_rows.append({
        "route_id": rid, "plan_id": new_plan, "source": "AI_OPTIMIZED", "dc_id": problem.dc["dc_id"],
        "route_date": problem.date, "tractor_id": r.vehicle.tractor_id, "trailer_id": r.vehicle.trailer_id,
        "driver_id": r.vehicle.driver_id, "depart_min": depart, "return_min": r.return_min,
        "stop_count": len(r.stops) + (len(lv.done) if lv else 0), "total_miles": round(r.total_miles, 1),
        "pcmiler_miles": r.pcmiler_miles, "mileage_source": r.mileage_source,
        "total_duration_min": r.return_min - depart, "total_cases": r.cases, "est_cost_usd": round(r.cost_usd, 2),
        "late_stops": r.late_stops, "status": "IN_PROGRESS" if lv else "PLANNED",
    })
    seq = 0
    for d in (lv.done if lv else []):
      seq += 1
      stop_rows.append({"route_id": rid, "stop_seq": seq, "order_id": d.order_id, "customer_id": d.customer_id,
                        "eta_min": None, "etd_min": None, "miles_from_prev": None, "window_ok": True})
    for p in r.stops:
      seq += 1
      stop_rows.append({"route_id": rid, "stop_seq": seq, "order_id": p.order_id.removesuffix("-COLD"),
                        "customer_id": p.customer_id, "eta_min": p.arrival_min, "etd_min": p.departure_min,
                        "miles_from_prev": round(p.miles_from_prev, 1), "pcmiler_leg_miles": p.pcmiler_leg_miles,
                        "window_ok": p.late_min == 0})
  repo.insert("routes", route_rows)
  repo.insert("route_stops", stop_rows)
  t = result.totals
  repo.insert("optimization_runs", [{
      "plan_id": new_plan, "dc_id": problem.dc["dc_id"], "route_date": problem.date, "scenario": "REOPTIMIZE",
      "parameters": {"event_id": event["event_id"], "source_plan_id": plan_id or "TMW_STATIC"},
      "orders_planned": t["stops"], "orders_dropped": t["dropped_orders"], "routes_used": t["routes"],
      "total_miles": t["miles"], "pcmiler_miles": t["pcmiler_miles"], "total_cost_usd": t["cost_usd"],
      "baseline_miles": None, "baseline_pcmiler_miles": None,
      "baseline_cost_usd": round(t["cost_usd"] - cost_impact, 2), "late_stops": t["late_stops"],
      "co2_kg": t["co2_kg"], "created_at": now_ts(),
  }])
  action_id = new_id("ACT")
  repo.insert("event_actions", [{
      "action_id": action_id, "event_id": event["event_id"], "source_plan_id": plan_id or "TMW_STATIC",
      "new_plan_id": new_plan, "affected_routes": list(lives), "untouched_routes": untouched,
      "cost_impact_usd": cost_impact, "late_stops_before": late_before, "late_stops_after": late_after,
      "requires_approval": bool(escalations), "escalation_reasons": escalations, "status": status,
      "explanation": explanation, "latency_s": latency, "created_at": now_ts(),
  }])
  return action_id


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def list_route_events(dc_id: str, delivery_date: str) -> dict:
  """Lists operational events (telematics, driver app, TMS, traffic) for a DC and date.

  Args:
    dc_id: Distribution center id.
    delivery_date: YYYY-MM-DD.

  Returns:
    Events with time, type, truck/customer/order involved and whether the
    agent has already acted on them.
  """
  events = q("SELECT * FROM route_events WHERE dc_id = :dc AND event_date = :d ORDER BY event_min",
             dc=dc_id.upper(), d=as_date(delivery_date))
  acted = {a["event_id"]: a["status"] for a in q("SELECT event_id, status FROM event_actions")}
  return {"events": [
      {"event_id": e["event_id"], "time": fmt_time(e["event_min"]), "type": e["event_type"], "source": e["source"],
       "tractor_id": e["tractor_id"], "customer_id": e["customer_id"], "order_id": e["order_id"],
       "delay_min": e["delay_min"], "description": e["description"], "agent_status": acted.get(e["event_id"], "NEW")}
      for e in events
  ]}


def handle_route_event(event_id: str, tool_context: ToolContext, plan_id: str = "") -> dict:
  """Re-plans the routes affected by one operational event and explains the change.

  Follows trigger -> assess -> re-plan -> explain -> approve. Only affected
  routes change; product on a truck stays on it; capacity, temperature, HOS
  and dock appointments are never violated.

  Args:
    event_id: Event id from list_route_events (or published over Pub/Sub).
    plan_id: Plan being executed. Empty uses the latest saved plan for that
      DC and date, or the TMW static routes.

  Returns:
    Affected and untouched routes, before/after late stops, Retail and
    Restaurant OTD impact (restaurants whose ETA moves more than the
    tolerance), cost impact, plain-language list of what changed, whether a
    human must approve (and why), the new plan id and the re-plan latency.
  """
  rows = q("SELECT * FROM route_events WHERE event_id = :e", e=event_id)
  if not rows:
    raise ToolError(f"Unknown event {event_id!r}")
  ev = rows[0]
  if not plan_id:
    # The session's last plan only applies when it is for the event's DC and date.
    last = tool_context.state.get("last_plan_id", "")
    run = q("SELECT dc_id, route_date FROM optimization_runs WHERE plan_id = :p", p=last) if last else []
    if run and run[0]["dc_id"] == ev["dc_id"] and str(run[0]["route_date"])[:10] == str(ev["event_date"])[:10]:
      plan_id = last
  if plan_id.startswith(("EVP-", "RPL-")):
    plan_id = ""  # events apply to the base plan, not to a previous patch
  out = _handle(ev, plan_id)
  if out.get("new_plan_id"):
    tool_context.state["last_event_plan_id"] = out["new_plan_id"]
  return out


def simulate_route_event(
    event_type: str,
    route_id: str,
    event_time: str,
    tool_context: ToolContext,
    delay_min: int = 0,
    customer_id: str = "",
    cases: int = 0,
    reefer_temp_f: float = 0.0,
) -> dict:
  """Injects a disruption on a route of the current plan and handles it (demo / drills).

  Args:
    event_type: DELAY, BREAKDOWN, ORDER_ADDED, ORDER_CANCELLED, NO_SHOW or REEFER_TEMP_ALERT.
    route_id: Route in the current plan (for ORDER_ADDED, any route of the plan).
    event_time: HH:MM when it happens.
    delay_min: Minutes of delay (DELAY).
    customer_id: Customer for ORDER_ADDED, NO_SHOW or ORDER_CANCELLED. Empty
      picks the truck's next stop for NO_SHOW / ORDER_CANCELLED.
    cases: Cases for ORDER_ADDED (split 60% dry, 25% chill, 15% frozen).
    reefer_temp_f: Reported temperature for REEFER_TEMP_ALERT.

  Returns:
    The same result as handle_route_event.
  """
  etype = event_type.strip().upper()
  if etype not in EVENT_TYPES or etype == "ROAD_CLOSURE":
    raise ToolError(f"event_type must be one of {', '.join(t for t in EVENT_TYPES if t != 'ROAD_CLOSURE')}")
  route = q("SELECT * FROM routes WHERE route_id = :r", r=route_id)
  if not route:
    raise ToolError(f"Unknown route {route_id!r}")
  route = route[0]
  now = parse_time(event_time)
  stops = q("SELECT * FROM route_stops WHERE route_id = :r ORDER BY stop_seq", r=route_id)
  nxt = next((x for x in stops if x["etd_min"] is not None and int(x["etd_min"]) > now), stops[-1] if stops else None)
  ev = {
      "event_id": new_id(f"EVT-SIM"), "dc_id": route["dc_id"], "event_date": route["route_date"], "event_min": now,
      "event_type": etype, "source": "SIMULATION", "tractor_id": route["tractor_id"], "customer_id": None,
      "order_id": None, "delay_min": delay_min or None, "lat": None, "lon": None, "radius_miles": None,
      "delay_factor": None, "payload": None, "description": f"Simulated {etype.lower().replace('_', ' ')} on {route_id}",
  }
  if etype in ("NO_SHOW", "ORDER_CANCELLED"):
    target = next((x for x in stops if x["customer_id"] == customer_id), nxt) if customer_id else nxt
    if not target:
      raise ToolError("Route has no stops left.")
    ev.update(customer_id=target["customer_id"], order_id=target["order_id"], tractor_id=None)
  if etype == "ORDER_ADDED":
    if not customer_id:
      raise ToolError("customer_id is required for ORDER_ADDED.")
    n = max(cases, 20)
    ev.update(customer_id=customer_id, tractor_id=None, payload={
        "dry_cases": int(n * 0.6), "chill_cases": int(n * 0.25), "frozen_cases": n - int(n * 0.6) - int(n * 0.25), "priority": "HOT"})
  if etype == "REEFER_TEMP_ALERT":
    ev["payload"] = {"zone": "FROZEN", "temp_f": reefer_temp_f or 18.0}
  get_repository().insert("route_events", [ev])
  plan_id = route["plan_id"] or ""
  if plan_id.startswith(("EVP-", "RPL-")):
    raise ToolError("Inject events on a base plan route (from optimize_routes), not on an already patched route.")
  out = _handle(ev, plan_id)
  if out.get("new_plan_id"):
    tool_context.state["last_event_plan_id"] = out["new_plan_id"]
  return out


def get_pending_escalations(dc_id: str = "") -> dict:
  """Lists re-plans waiting for a dispatcher decision.

  Args:
    dc_id: Optional DC filter.

  Returns:
    Action id, event, cost impact, late stops and reasons for escalation.
  """
  acts = q("SELECT * FROM event_actions WHERE status = 'PENDING_APPROVAL' ORDER BY created_at")
  decided = {a["action_id"] for a in q("SELECT action_id FROM replan_approvals")}
  events = {e["event_id"]: e for e in q("SELECT event_id, dc_id, event_type, description FROM route_events")}
  out = []
  for a in acts:
    e = events.get(a["event_id"], {})
    if a["action_id"] in decided or (dc_id and e.get("dc_id") != dc_id.upper()):
      continue
    out.append({"action_id": a["action_id"], "event_id": a["event_id"], "event_type": e.get("event_type"),
                "description": e.get("description"), "new_plan_id": a["new_plan_id"],
                "cost_impact_usd": a["cost_impact_usd"], "late_stops_after": a["late_stops_after"],
                "escalation_reasons": a["escalation_reasons"]})
  return {"pending": out}


def decide_replan(action_id: str, approve: bool, notes: str = "") -> dict:
  """Records a dispatcher's approval or rejection of an escalated re-plan.

  Requires confirmation. After approval, hand the new plan to the TMW
  dispatch agent to update the movements in Trimble TMW.

  Args:
    action_id: Action id from handle_route_event or get_pending_escalations.
    approve: True to approve, False to reject.
    notes: Optional reason.

  Returns:
    The decision and the plan id to dispatch when approved.
  """
  acts = q("SELECT * FROM event_actions WHERE action_id = :a", a=action_id)
  if not acts:
    raise ToolError(f"Unknown action {action_id!r}")
  decision = "APPROVED" if approve else "REJECTED"
  get_repository().insert("replan_approvals", [{
      "approval_id": new_id("APR"), "action_id": action_id, "decision": decision, "decided_by": "dispatcher",
      "notes": notes, "created_at": now_ts()}])
  return {"action_id": action_id, "decision": decision, "plan_to_dispatch": acts[0]["new_plan_id"] if approve else None}


decide_replan_tool = FunctionTool(decide_replan, require_confirmation=True)
