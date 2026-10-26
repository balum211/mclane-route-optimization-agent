---
name: route-optimizer-solver
description: Use when changing the OR-Tools routing model (objective, constraints, time windows, capacity, HOS, disruptions, travel matrix) in route_optimizer/optimizer.py or geo.py, or when benchmarking plan quality.
---

# Route optimizer solver

## Goal
Change the vehicle routing model safely: hard constraints stay hard, the plan still beats the TMW
static baseline, and runtimes stay inside budget (15 s daily, under 30 s for re-plans).

## Instructions
1. Read `route_optimizer/optimizer.py` top to bottom first. Know the dimensions: `Cases`, `Cold`,
   `Weight`, `Cube` (capacity), `Time` (service + travel, soft or hard windows, span cost = driver
   pay), `Drive` (travel only, capped at remaining 11 h).
2. Put new **hard** rules in the model (dimension bounds, `VehicleVar(...).RemoveValues`, span caps),
   not in prompts. Put new **soft** preferences in the objective as cents.
3. Use `routing.VehicleVar(index).RemoveValues(banned)` for vehicle restrictions. In this OR-Tools
   build, `SetAllowedVehiclesForIndex` rejects Python lists.
4. Keep `simulate_route` as the single source for reported KPIs, so baseline and optimized plans are
   priced the same way. If you add a cost term, add it in both places.
5. Run the benchmark before and after the change:
   `python .agents/skills/route-optimizer-solver/scripts/benchmark.py --time-limit 10`
6. Add a focused test in `tests/test_optimizer.py` using tiny hand-made problems.

## Examples
- "Add dock-door capacity at the DC": add a cumulative constraint over start cumul vars, binned by
  30-minute slots, with `dock_doors` from `distribution_centers`.
- "Prefer the same driver as yesterday": add a per-(stop, vehicle) penalty with
  `routing.AddDisjunction`-style soft costs or a small arc cost bonus, weight from config.

## Constraints
- Do not remove or weaken capacity, cold capacity, HOS, `hard_window` or `pinned_vehicle_id` handling.
- Do not let total solver time for an event re-plan exceed 30 s.
- Do not change the meaning of `*_min` columns (minutes after midnight).
