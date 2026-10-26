"""Vehicle routing engine: capacitated VRP with time windows on Google OR-Tools.

Models the constraints a McLane DC dispatcher deals with every night:

* multi-dimensional capacity: total cases, chilled+frozen cases (multi-temp
  trailers), weight and cube
* store / restaurant receiving windows (hard open, soft or hard close)
* learned service (unload) times per customer
* driver hours of service: 14h on-duty span and 11h driving
* site restrictions: liftgate required, maximum vehicle length
* order priority: HOT orders must go, FLEX orders may slide to tomorrow
* traffic and weather disruptions as travel-time multipliers
* in-flight re-optimization from a truck's current position

The LLM never does arithmetic on routes. Agents call tools that call this
module, and the module returns structured, explainable results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .geo import Disruption, Point, TravelMatrix, build_matrix, fmt_time

HORIZON_MIN = 30 * 60  # allow routes to run past midnight


@dataclass
class Stop:
  order_id: str
  customer_id: str
  name: str
  point: Point
  cases: int
  cold_cases: int
  weight_lbs: int
  cube_ft3: float
  window_start: int
  window_end: int
  service_min: int
  priority: str = "STANDARD"  # HOT | STANDARD | FLEX
  priority_tier: int = 3
  requires_liftgate: bool = False
  max_vehicle_length_ft: int = 53
  hard_window: bool = False  # dock appointment: never arrive after close
  # Product already loaded on a truck can only be delivered by that truck.
  pinned_vehicle_id: Optional[str] = None


@dataclass
class Vehicle:
  vehicle_id: str
  tractor_id: str
  trailer_id: str
  driver_id: str
  capacity_cases: int
  capacity_cold_cases: int
  capacity_lbs: int
  capacity_cube: int
  length_ft: int
  has_liftgate: bool
  earliest_start: int
  latest_start: int
  max_duty_min: int = 14 * 60
  max_drive_min: int = 11 * 60
  mpg: float = 6.5
  start_point: Optional[Point] = None  # set for in-flight re-optimization


@dataclass
class CostModel:
  cost_per_mile_usd: float = 0.92
  fuel_price_usd_gal: float = 3.85
  driver_cost_per_hour_usd: float = 38.0
  overtime_multiplier: float = 1.5
  fixed_cost_per_route_usd: float = 185.0
  late_penalty_usd: float = 150.0
  co2_kg_per_gal: float = 10.21


@dataclass
class SolverOptions:
  time_limit_s: int = 10
  allow_late: bool = True            # soft window close with a penalty
  max_late_min: int = 60             # hard cap on lateness when allow_late
  late_penalty_per_min_usd: float = 4.0
  window_extension_min: int = 0      # what-if: stores accept wider windows
  max_vehicles: Optional[int] = None  # what-if: fewer trucks
  flex_drop_penalty_usd: float = 400.0
  standard_drop_penalty_usd: float = 25_000.0
  hot_drop_penalty_usd: float = 1_000_000.0
  service_time_factor: float = 1.0   # what-if: faster unloads
  max_route_duration_min: Optional[int] = None  # policy cap on top of HOS


@dataclass
class PlannedStop:
  seq: int
  order_id: str
  customer_id: str
  name: str
  lat: float
  lon: float
  arrival_min: int
  service_start_min: int
  departure_min: int
  window_start: int
  window_end: int
  miles_from_prev: float
  late_min: int
  wait_min: int
  cases: int
  traffic_events: list[str] = field(default_factory=list)

  def as_dict(self) -> dict:
    return {
        "seq": self.seq,
        "order_id": self.order_id,
        "customer_id": self.customer_id,
        "name": self.name,
        "eta": fmt_time(self.arrival_min),
        "etd": fmt_time(self.departure_min),
        "window": f"{fmt_time(self.window_start)}-{fmt_time(self.window_end)}",
        "late_min": self.late_min,
        "wait_min": self.wait_min,
        "miles_from_prev": round(self.miles_from_prev, 1),
        "cases": self.cases,
        "traffic_events": self.traffic_events,
    }


@dataclass
class RouteResult:
  vehicle: Vehicle
  stops: list[PlannedStop]
  depart_min: int
  return_min: int
  total_miles: float
  drive_min: int
  duration_min: int
  cases: int
  cold_cases: int
  fuel_gal: float
  cost_usd: float
  co2_kg: float
  late_stops: int
  hos_violation: bool

  def summary(self) -> dict:
    return {
        "vehicle_id": self.vehicle.vehicle_id,
        "tractor_id": self.vehicle.tractor_id,
        "trailer_id": self.vehicle.trailer_id,
        "driver_id": self.vehicle.driver_id,
        "depart": fmt_time(self.depart_min),
        "return": fmt_time(self.return_min),
        "stops": len(self.stops),
        "miles": round(self.total_miles, 1),
        "duration_h": round(self.duration_min / 60, 2),
        "drive_h": round(self.drive_min / 60, 2),
        "cases": self.cases,
        "utilization_pct": round(100 * self.cases / max(self.vehicle.capacity_cases, 1), 1),
        "cost_usd": round(self.cost_usd, 2),
        "late_stops": self.late_stops,
        "hos_violation": self.hos_violation,
    }


@dataclass
class PlanResult:
  routes: list[RouteResult]
  dropped: list[Stop]
  status: str
  impacted_legs: int = 0

  @property
  def totals(self) -> dict:
    return {
        "routes": len(self.routes),
        "stops": sum(len(r.stops) for r in self.routes),
        "miles": round(sum(r.total_miles for r in self.routes), 1),
        "drive_hours": round(sum(r.drive_min for r in self.routes) / 60, 1),
        "duty_hours": round(sum(r.duration_min for r in self.routes) / 60, 1),
        "cost_usd": round(sum(r.cost_usd for r in self.routes), 2),
        "fuel_gal": round(sum(r.fuel_gal for r in self.routes), 1),
        "co2_kg": round(sum(r.co2_kg for r in self.routes), 1),
        "late_stops": sum(r.late_stops for r in self.routes),
        "dropped_orders": len(self.dropped),
        "avg_utilization_pct": round(
            100
            * sum(r.cases for r in self.routes)
            / max(sum(r.vehicle.capacity_cases for r in self.routes), 1),
            1,
        ),
    }


# --------------------------------------------------------------------------
# Evaluation: one simulator prices both the TMW static plan and the optimized
# plan, so the comparison the agent reports is apples to apples.
# --------------------------------------------------------------------------


def simulate_route(
    vehicle: Vehicle,
    stops: Sequence[Stop],
    depot: Point,
    matrix: TravelMatrix,
    costs: CostModel,
    depart_min: Optional[int] = None,
    service_time_factor: float = 1.0,
) -> RouteResult:
  origin = vehicle.start_point or depot
  t = vehicle.earliest_start if depart_min is None else depart_min
  depart = t
  prev = origin.key
  miles = 0.0
  drive = 0
  planned: list[PlannedStop] = []
  for seq, s in enumerate(stops, start=1):
    i, j = matrix.index(prev), matrix.index(s.order_id)
    leg_miles = matrix.miles[i][j]
    leg_min = matrix.minutes[i][j]
    arrival = t + leg_min
    start = max(arrival, s.window_start)
    service = int(round(s.service_min * service_time_factor))
    late = max(0, arrival - s.window_end)
    planned.append(
        PlannedStop(
            seq=seq,
            order_id=s.order_id,
            customer_id=s.customer_id,
            name=s.name,
            lat=s.point.lat,
            lon=s.point.lon,
            arrival_min=arrival,
            service_start_min=start,
            departure_min=start + service,
            window_start=s.window_start,
            window_end=s.window_end,
            miles_from_prev=leg_miles,
            late_min=late,
            wait_min=start - arrival,
            cases=s.cases,
            traffic_events=matrix.impacted_legs.get((prev, s.order_id), []),
        )
    )
    miles += leg_miles
    drive += leg_min
    t = start + service
    prev = s.order_id
  i, j = matrix.index(prev), matrix.index(depot.key)
  if stops or vehicle.start_point:
    miles += matrix.miles[i][j]
    drive += matrix.minutes[i][j]
    t += matrix.minutes[i][j]
  duration = t - depart
  fuel = miles / max(vehicle.mpg, 0.1)
  regular = min(duration, 600)
  overtime = max(0, duration - 600)
  driver_cost = (regular + overtime * costs.overtime_multiplier) / 60 * costs.driver_cost_per_hour_usd
  late_stops = sum(1 for p in planned if p.late_min > 0)
  cost = (
      (costs.fixed_cost_per_route_usd if stops else 0)
      + miles * costs.cost_per_mile_usd
      + fuel * costs.fuel_price_usd_gal
      + driver_cost
      + late_stops * costs.late_penalty_usd
  )
  return RouteResult(
      vehicle=vehicle,
      stops=planned,
      depart_min=depart,
      return_min=t,
      total_miles=miles,
      drive_min=drive,
      duration_min=duration,
      cases=sum(s.cases for s in stops),
      cold_cases=sum(s.cold_cases for s in stops),
      fuel_gal=fuel,
      cost_usd=cost,
      co2_kg=fuel * costs.co2_kg_per_gal,
      late_stops=late_stops,
      hos_violation=duration > vehicle.max_duty_min or drive > vehicle.max_drive_min,
  )


# --------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------


def _vehicle_can_serve(v: Vehicle, s: Stop) -> bool:
  if s.pinned_vehicle_id and v.vehicle_id != s.pinned_vehicle_id:
    return False
  if s.requires_liftgate and not v.has_liftgate:
    return False
  if v.length_ft > s.max_vehicle_length_ft:
    return False
  if s.cold_cases > 0 and v.capacity_cold_cases <= 0:
    return False
  return True


def solve(
    depot: Point,
    stops: Sequence[Stop],
    vehicles: Sequence[Vehicle],
    costs: CostModel = CostModel(),
    options: SolverOptions = SolverOptions(),
    disruptions: Sequence[Disruption] = (),
    matrix: Optional[TravelMatrix] = None,
) -> PlanResult:
  if not stops:
    return PlanResult(routes=[], dropped=[], status="NO_ORDERS")
  vehicles = list(vehicles)[: options.max_vehicles or None]
  if not vehicles:
    return PlanResult(routes=[], dropped=list(stops), status="NO_VEHICLES")

  start_points = [v.start_point for v in vehicles if v.start_point is not None]
  # Stops are keyed by order id inside the matrix.
  points = [depot] + start_points + [Point(s.order_id, s.point.lat, s.point.lon) for s in stops]
  if matrix is None:
    lo = min(v.earliest_start for v in vehicles)
    matrix = build_matrix(points, depot, disruptions, (lo, lo + 16 * 60))

  n_extra = len(start_points)
  stop_offset = 1 + n_extra
  n_nodes = len(points)

  starts, ends = [], []
  extra_i = 0
  for v in vehicles:
    if v.start_point is not None:
      starts.append(1 + extra_i)
      extra_i += 1
    else:
      starts.append(0)
    ends.append(0)

  manager = pywrapcp.RoutingIndexManager(n_nodes, len(vehicles), starts, ends)
  routing = pywrapcp.RoutingModel(manager)

  def node_stop(node: int) -> Optional[Stop]:
    return stops[node - stop_offset] if node >= stop_offset else None

  service = [0] * n_nodes
  for k, s in enumerate(stops):
    service[stop_offset + k] = int(round(s.service_min * options.service_time_factor))

  # Arc cost: distance-driven cost in cents. Driver time is priced through the
  # span cost below so waiting at the DC is not paid for.
  avg_mpg = sum(v.mpg for v in vehicles) / len(vehicles)
  cents_per_mile = int(round(100 * (costs.cost_per_mile_usd + costs.fuel_price_usd_gal / avg_mpg)))

  def dist_cb(fi, ti):
    i, j = manager.IndexToNode(fi), manager.IndexToNode(ti)
    return int(round(matrix.miles[i][j] * cents_per_mile))

  dist_idx = routing.RegisterTransitCallback(dist_cb)
  routing.SetArcCostEvaluatorOfAllVehicles(dist_idx)
  routing.SetFixedCostOfAllVehicles(int(costs.fixed_cost_per_route_usd * 100))

  # Capacity dimensions.
  def add_capacity(name: str, demand_of, cap_of):
    def cb(fi):
      s = node_stop(manager.IndexToNode(fi))
      return int(demand_of(s)) if s else 0

    idx = routing.RegisterUnaryTransitCallback(cb)
    routing.AddDimensionWithVehicleCapacity(idx, 0, [int(cap_of(v)) for v in vehicles], True, name)

  add_capacity("Cases", lambda s: s.cases, lambda v: v.capacity_cases)
  add_capacity("Cold", lambda s: s.cold_cases, lambda v: v.capacity_cold_cases)
  add_capacity("Weight", lambda s: s.weight_lbs, lambda v: v.capacity_lbs)
  add_capacity("Cube", lambda s: s.cube_ft3, lambda v: v.capacity_cube)

  # Time dimension: service at origin + travel.
  def time_cb(fi, ti):
    i, j = manager.IndexToNode(fi), manager.IndexToNode(ti)
    return service[i] + matrix.minutes[i][j]

  time_idx = routing.RegisterTransitCallback(time_cb)
  routing.AddDimension(time_idx, 240, HORIZON_MIN, False, "Time")
  time_dim = routing.GetDimensionOrDie("Time")

  # Drive dimension: travel only, capped by the 11 hour driving rule.
  def drive_cb(fi, ti):
    i, j = manager.IndexToNode(fi), manager.IndexToNode(ti)
    return matrix.minutes[i][j]

  drive_idx = routing.RegisterTransitCallback(drive_cb)
  routing.AddDimensionWithVehicleCapacity(
      drive_idx, 0, [v.max_drive_min for v in vehicles], True, "Drive"
  )

  late_cents_per_min = int(options.late_penalty_per_min_usd * 100)
  for k, s in enumerate(stops):
    index = manager.NodeToIndex(stop_offset + k)
    open_ = max(0, s.window_start - options.window_extension_min)
    close = s.window_end + options.window_extension_min
    soft = options.allow_late and not s.hard_window
    hard_close = close + (options.max_late_min if soft else 0)
    time_dim.CumulVar(index).SetRange(open_, hard_close)
    if soft:
      time_dim.SetCumulVarSoftUpperBound(index, close, late_cents_per_min)

    # Site and temperature restrictions. (RemoveValues rather than
    # SetAllowedVehiclesForIndex, whose SWIG binding rejects Python lists in
    # some OR-Tools releases.)
    banned = [vi for vi, v in enumerate(vehicles) if not _vehicle_can_serve(v, s)]
    if banned:
      routing.VehicleVar(index).RemoveValues(banned)

    if s.priority == "HOT":
      penalty = options.hot_drop_penalty_usd
    elif s.priority == "FLEX":
      penalty = options.flex_drop_penalty_usd
    else:
      penalty = options.standard_drop_penalty_usd * (4 - min(max(s.priority_tier, 1), 3))
    routing.AddDisjunction([index], int(penalty * 100))

  driver_cents_per_min = max(1, int(round(costs.driver_cost_per_hour_usd * 100 / 60)))
  for vi, v in enumerate(vehicles):
    start = routing.Start(vi)
    time_dim.CumulVar(start).SetRange(v.earliest_start, max(v.earliest_start, v.latest_start))
    span_cap = v.max_duty_min
    if options.max_route_duration_min:
      span_cap = min(span_cap, options.max_route_duration_min)
    time_dim.SetSpanUpperBoundForVehicle(span_cap, vi)
    time_dim.SetSpanCostCoefficientForVehicle(driver_cents_per_min, vi)
    routing.AddVariableMaximizedByFinalizer(time_dim.CumulVar(start))
    routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(vi)))

  params = pywrapcp.DefaultRoutingSearchParameters()
  params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
  params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
  params.time_limit.seconds = max(1, int(options.time_limit_s))

  solution = routing.SolveWithParameters(params)
  if solution is None:
    return PlanResult(routes=[], dropped=list(stops), status="INFEASIBLE")

  results: list[RouteResult] = []
  served: set[str] = set()
  for vi, v in enumerate(vehicles):
    index = routing.Start(vi)
    seq: list[Stop] = []
    depart = solution.Min(time_dim.CumulVar(index))
    index = solution.Value(routing.NextVar(index))
    while not routing.IsEnd(index):
      s = node_stop(manager.IndexToNode(index))
      if s:
        seq.append(s)
        served.add(s.order_id)
      index = solution.Value(routing.NextVar(index))
    if not seq and v.start_point is None:
      continue
    results.append(
        simulate_route(v, seq, depot, matrix, costs, depart, options.service_time_factor)
    )

  dropped = [s for s in stops if s.order_id not in served]
  return PlanResult(
      routes=results,
      dropped=dropped,
      status="OK",
      impacted_legs=len(matrix.impacted_legs),
  )


def reoptimize_remaining(
    depot: Point,
    current_position: Point,
    current_min: int,
    remaining: Sequence[Stop],
    vehicle: Vehicle,
    costs: CostModel,
    disruptions: Sequence[Disruption],
    options: SolverOptions = SolverOptions(time_limit_s=5),
) -> PlanResult:
  """Re-sequences a truck's remaining stops from where it is right now."""
  live = Vehicle(
      **{
          **vehicle.__dict__,
          "earliest_start": current_min,
          "latest_start": current_min,
          "start_point": current_position,
      }
  )
  points = [depot, current_position] + [
      Point(s.order_id, s.point.lat, s.point.lon) for s in remaining
  ]
  matrix = build_matrix(points, depot, disruptions, (current_min, current_min + 10 * 60))
  return solve(depot, remaining, [live], costs, options, disruptions, matrix)
