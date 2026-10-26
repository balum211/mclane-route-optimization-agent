"""Domain layer: turns database rows into optimizer inputs and back.

Kept free of any database client so the synthetic data generator, the agent
tools and the tests all share exactly the same rules.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from .geo import Disruption, Point, build_matrix
from .optimizer import CostModel, PlanResult, Stop, Vehicle, simulate_route

COLD_TRAILERS = {"MULTI_TEMP", "STRAIGHT_REEFER"}


def _b(v) -> bool:
  if isinstance(v, str):
    return v.strip().lower() in {"1", "true", "t", "yes"}
  return bool(v)


def depot_point(dc: Mapping) -> Point:
  return Point(dc["dc_id"], float(dc["lat"]), float(dc["lon"]))


def learned_service_minutes(history_rows: Iterable[Mapping]) -> dict[str, int]:
  """75th percentile of observed dwell per customer.

  TMS master data usually carries one standard unload time per customer. The
  history shows what really happens at the dock, and planning on the p75 is
  what keeps a route on time when one store runs long.
  """
  by_cust: dict[str, list[int]] = defaultdict(list)
  for r in history_rows:
    if r.get("dwell_min") is not None:
      by_cust[r["customer_id"]].append(int(r["dwell_min"]))
  out = {}
  for cid, vals in by_cust.items():
    vals.sort()
    k = max(0, math.ceil(0.75 * len(vals)) - 1)
    out[cid] = vals[k]
  return out


def stops_from_rows(
    orders: Sequence[Mapping],
    customers: Mapping[str, Mapping],
    learned_service: Mapping[str, int] | None = None,
) -> list[Stop]:
  learned_service = learned_service or {}
  stops = []
  for o in orders:
    c = customers[o["customer_id"]]
    dry, chill, frozen = int(o["dry_cases"]), int(o["chill_cases"]), int(o["frozen_cases"])
    std = int(c["std_service_min"])
    learned = learned_service.get(c["customer_id"], std)
    stops.append(
        Stop(
            order_id=o["order_id"],
            customer_id=c["customer_id"],
            name=c["name"],
            point=Point(o["order_id"], float(c["lat"]), float(c["lon"])),
            cases=dry + chill + frozen,
            cold_cases=chill + frozen,
            weight_lbs=int(o["weight_lbs"]),
            cube_ft3=float(o["cube_ft3"]),
            window_start=int(c["window_start_min"]),
            window_end=int(c["window_end_min"]),
            service_min=max(10, int(learned)),
            priority=o.get("priority") or "STANDARD",
            priority_tier=int(c.get("priority_tier") or 3),
            requires_liftgate=_b(c.get("requires_liftgate")),
            max_vehicle_length_ft=int(c.get("max_vehicle_length_ft") or 53),
            hard_window=_b(c.get("hard_window")),
        )
    )
  return stops


def vehicles_from_rows(
    dc: Mapping,
    tractors: Sequence[Mapping],
    trailers: Sequence[Mapping],
    drivers: Sequence[Mapping],
) -> list[Vehicle]:
  """Pairs available tractors, trailers and drivers into dispatchable units.

  Straight trucks get straight reefer bodies; road tractors get 53' trailers,
  multi-temp first. Drivers with the most hours left go first.
  """
  avail = lambda rows: [r for r in rows if (r.get("status") or "AVAILABLE") == "AVAILABLE"]
  t_road = [t for t in avail(tractors) if t["unit_type"] == "TRACTOR"]
  t_straight = [t for t in avail(tractors) if t["unit_type"] == "STRAIGHT_TRUCK"]
  tr_53 = sorted(
      [t for t in avail(trailers) if t["trailer_type"] in {"MULTI_TEMP", "DRY"}],
      key=lambda t: (t["trailer_type"] != "MULTI_TEMP", t["trailer_id"]),
  )
  tr_box = [t for t in avail(trailers) if t["trailer_type"] == "STRAIGHT_REEFER"]
  drv = sorted(avail(drivers), key=lambda d: -int(d["hos_duty_remaining_min"]))

  units = list(zip(t_road, tr_53)) + list(zip(t_straight, tr_box))
  vehicles = []
  for (tractor, trailer), driver in zip(units, drv):
    start = max(int(dc["dispatch_start_min"]), int(driver["shift_start_min"]))
    vehicles.append(
        Vehicle(
            vehicle_id=f"{tractor['tractor_id']}/{trailer['trailer_id']}",
            tractor_id=tractor["tractor_id"],
            trailer_id=trailer["trailer_id"],
            driver_id=driver["driver_id"],
            capacity_cases=int(trailer["capacity_cases"]),
            capacity_cold_cases=int(trailer["capacity_cold_cases"]),
            capacity_lbs=int(trailer["capacity_lbs"]),
            capacity_cube=int(trailer["capacity_cube"]),
            length_ft=int(trailer["length_ft"]),
            has_liftgate=_b(trailer["has_liftgate"]),
            earliest_start=start,
            latest_start=max(start, int(dc["dispatch_end_min"])),
            max_duty_min=int(driver["hos_duty_remaining_min"]),
            max_drive_min=int(driver["hos_drive_remaining_min"]),
            mpg=float(tractor["mpg"]),
        )
    )
  return vehicles


def disruptions_from_rows(
    traffic: Iterable[Mapping] = (), weather: Iterable[Mapping] = ()
) -> list[Disruption]:
  out = []
  for t in traffic:
    out.append(
        Disruption(
            t["event_id"], float(t["lat"]), float(t["lon"]), float(t["radius_miles"]),
            int(t["start_min"]), int(t["end_min"]), float(t["delay_factor"]),
            f"{t['event_type']} {t['corridor']}: {t['description']}",
        )
    )
  for w in weather:
    out.append(
        Disruption(
            w["event_id"], float(w["lat"]), float(w["lon"]), float(w["radius_miles"]),
            int(w["start_min"]), int(w["end_min"]), float(w["speed_factor"]),
            f"{w['severity']} {w['alert_type']}: {w['description']}",
        )
    )
  return out


def cost_model_from_row(row: Mapping | None) -> CostModel:
  if not row:
    return CostModel()
  return CostModel(
      cost_per_mile_usd=float(row["cost_per_mile_usd"]),
      fuel_price_usd_gal=float(row["fuel_price_usd_gal"]),
      driver_cost_per_hour_usd=float(row["driver_cost_per_hour_usd"]),
      overtime_multiplier=float(row["overtime_multiplier"]),
      fixed_cost_per_route_usd=float(row["fixed_cost_per_route_usd"]),
      late_penalty_usd=float(row["late_penalty_usd"]),
      co2_kg_per_gal=float(row["co2_kg_per_gal"]),
  )


def static_tmw_plan(
    depot: Point,
    stops: Sequence[Stop],
    vehicles: Sequence[Vehicle],
    costs: CostModel,
    disruptions: Sequence[Disruption] = (),
    depart_min: int | None = None,
) -> PlanResult:
  """Reproduces how fixed TMW routes are typically built today.

  Stops are swept by compass bearing from the DC (a "territory" route), cut
  into trucks when a capacity limit is reached, and driven in bearing order.
  Every truck leaves at the start of the dispatch window. This is the
  baseline the optimized plan is compared against.
  """
  if not stops or not vehicles:
    return PlanResult(routes=[], dropped=list(stops), status="NO_ORDERS")

  def bearing(s: Stop) -> float:
    return math.atan2(s.point.lat - depot.lat, s.point.lon - depot.lon)

  ordered = sorted(stops, key=bearing)
  points = [depot] + [s.point for s in stops]
  lo = min(v.earliest_start for v in vehicles)
  matrix = build_matrix(points, depot, disruptions, (lo, lo + 16 * 60))

  def depart_for(v: Vehicle, load: list[Stop]) -> int:
    """Dispatcher-set departure: arrive at the first stop as it opens."""
    if depart_min is not None:
      return depart_min
    if not load:
      return v.earliest_start
    first = load[0]
    lead = matrix.minutes[matrix.index(depot.key)][matrix.index(first.order_id)]
    return min(max(v.earliest_start, first.window_start - lead), v.latest_start)

  def compatible(v: Vehicle, s: Stop) -> bool:
    if s.requires_liftgate and not v.has_liftgate:
      return False
    if v.length_ft > s.max_vehicle_length_ft:
      return False
    return not (s.cold_cases > 0 and v.capacity_cold_cases <= 0)

  def fits(v: Vehicle, load: list[Stop], s: Stop) -> bool:
    trial = load + [s]
    if (
        sum(x.cases for x in trial) > v.capacity_cases
        or sum(x.cold_cases for x in trial) > v.capacity_cold_cases
        or sum(x.weight_lbs for x in trial) > v.capacity_lbs
        or len(trial) > 14
    ):
      return False
    r = simulate_route(v, trial, depot, matrix, costs, depart_for(v, trial))
    return not r.hos_violation

  # Each unit takes the next contiguous slice of the sweep it can carry.
  # Stops it can't serve (cold on a dry van, liftgate, length) wait for a
  # later unit.
  routes = []
  pending = ordered
  for v in vehicles:
    if not pending:
      break
    load, rest, closed = [], [], False
    for s in pending:
      if closed or not compatible(v, s):
        rest.append(s)
      elif fits(v, load, s):
        load.append(s)
      else:
        closed = True
        rest.append(s)
    if load:
      routes.append(simulate_route(v, load, depot, matrix, costs, depart_for(v, load)))
    pending = rest
  return PlanResult(routes=routes, dropped=pending, status="OK", impacted_legs=len(matrix.impacted_legs))
