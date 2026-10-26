# Research notes

## Solver: OR-Tools vs Route Optimization API
- **Decision**: OR-Tools in-process for the hackathon; Route Optimization API as a drop-in behind `solve()` later.
- **Why**: offline and deterministic, sub-second re-plans for single trucks, full control over multi-dimensional
  capacity and pinning. The Route Optimization API adds managed scale and traffic-aware matrices but needs network
  and billing.

## Travel times
- **Decision**: great-circle distance × 1.22 circuity, 52 mph highway and 28 mph urban by default. Optional Maps Routes
  API `computeRouteMatrix` (625 elements per request, so 25×25 blocks).
- Disruptions are travel-time multipliers on legs that cross an event radius, applied when the event overlaps
  the plan. This is conservative.

## Unload time
- TMS master data is a single standard per customer. History shows real dwell is longer for most sites. The p75 of
  observed dwell is used, a simple, explainable estimator that keeps routes on time when a site runs long.

## TMW
- Plans map to movement, leg header (tractor, trailer, driver) and stops (PUP/HLT at the DC, DRP/DRL per drop,
  EMT return). Re-plans send `UPDATE_STOPS`.

## ADK specifics (google-adk 2.13)
- `FunctionTool(fn, require_confirmation=True)` gives built-in human confirmation.
- `{key?}` placeholders inject optional session state into instructions.
- `google.adk.integrations.bigquery.BigQueryToolset` with `WriteMode.BLOCKED` gives read-only NL2SQL.
- `routing.SetAllowedVehiclesForIndex` rejects Python lists in OR-Tools 9.15's SWIG binding; use
  `VehicleVar(i).RemoveValues(banned)`.
