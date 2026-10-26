"""Solver unit tests on tiny hand-made problems."""

from route_optimizer.geo import Disruption, Point
from route_optimizer.optimizer import CostModel, SolverOptions, Stop, Vehicle, solve

DEPOT = Point("DC", 31.10, -97.34)


def stop(i, lat, lon, cases=100, cold=0, ws=300, we=900, **kw):
  return Stop(f"O{i}", f"C{i}", f"Store {i}", Point(f"O{i}", lat, lon), cases, cold, cases * 18, cases * 1.5,
              ws, we, 20, **kw)


def truck(i, cold=900, cases=1500, liftgate=False, length=53, start=240):
  return Vehicle(f"V{i}", f"T{i}", f"L{i}", f"D{i}", cases, cold, 42000, 3300, length, liftgate, start, start + 300)


def test_all_stops_served_and_capacity_respected():
  stops = [stop(i, 31.10 + 0.05 * i, -97.34 + 0.03 * (i % 3), cases=400) for i in range(8)]
  plan = solve(DEPOT, stops, [truck(1), truck(2), truck(3)], CostModel(), SolverOptions(time_limit_s=2))
  assert plan.status == "OK"
  assert not plan.dropped
  for r in plan.routes:
    assert r.cases <= r.vehicle.capacity_cases


def test_cold_product_never_on_dry_van():
  stops = [stop(1, 31.2, -97.3, cold=50), stop(2, 31.25, -97.35, cold=0)]
  dry = truck(1, cold=0)
  reefer = truck(2, cold=900)
  plan = solve(DEPOT, stops, [dry, reefer], CostModel(), SolverOptions(time_limit_s=2))
  for r in plan.routes:
    if r.vehicle.capacity_cold_cases == 0:
      assert all(s.order_id != "O1" for s in r.stops)


def test_liftgate_and_length_restrictions():
  s = stop(1, 31.2, -97.3, requires_liftgate=True, max_vehicle_length_ft=28)
  plan = solve(DEPOT, [s], [truck(1), truck(2, liftgate=True, length=26)], CostModel(), SolverOptions(time_limit_s=2))
  assert plan.routes[0].vehicle.vehicle_id == "V2"


def test_hard_window_is_never_violated():
  far = stop(1, 32.4, -97.34, ws=240, we=250, hard_window=True)
  plan = solve(DEPOT, [far], [truck(1, start=240)], CostModel(), SolverOptions(time_limit_s=2))
  assert plan.dropped and not any(r.stops for r in plan.routes)


def test_pinned_stop_stays_on_its_truck():
  s = stop(1, 31.2, -97.3, pinned_vehicle_id="V2")
  plan = solve(DEPOT, [s], [truck(1), truck(2)], CostModel(), SolverOptions(time_limit_s=2))
  assert [r.vehicle.vehicle_id for r in plan.routes if r.stops] == ["V2"]


def test_disruption_slows_legs():
  s = [stop(1, 31.5, -97.15)]
  calm = solve(DEPOT, s, [truck(1)], CostModel(), SolverOptions(time_limit_s=1))
  jam = solve(DEPOT, s, [truck(1)], CostModel(), SolverOptions(time_limit_s=1),
              [Disruption("X", 31.3, -97.25, 15, 0, 1440, 2.5)])
  assert jam.routes[0].drive_min > calm.routes[0].drive_min
  assert jam.impacted_legs > 0
