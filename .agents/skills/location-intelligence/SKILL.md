---
name: location-intelligence
description: Use when working on GPS pings, geofences, geofence arrival/departure detection, dwell time or dwell time changes, customer geolocation (geocode) checks, DWELL_OVERRUN events, or Retail and Restaurant OTD measured from geofence arrivals.
---

# Location intelligence (GPS, geofence, dwell, geocodes, OTD)

## Goal
Turn truck GPS into trustworthy arrival, departure and dwell facts, keep customer geolocations and
TMW dwell standards honest, and measure Retail and Restaurant OTD on those facts.

## Instructions
1. Know the pieces before changing any of them:
   - `route_optimizer/geofence.py`: `detect_visits` (entry at the first ping inside the radius, exit
     when a ping is beyond radius x `EXIT_BUFFER`, visits under `MIN_VISIT_MIN` dropped),
     `detect_stops` (stationary runs, independent of geofences), `learned_location` (median).
   - `route_optimizer/otd.py`: `SEGMENT_GROUP`, `DEFAULT_POLICIES`, `is_on_time`, `summarize`,
     `plan_otd`. Policies can be overridden in the `otd_policies` table.
   - `route_optimizer/tools/location_tools.py`: the agent tools, all read-only except
     `apply_master_data_updates` (confirmation required).
   - `planning.learned_service_minutes`: recent-first p75 dwell used by the optimizer.
2. Geofence semantics: `delivery_history.actual_arrival_min` is the geofence entry when
   `arrival_source = 'GEOFENCE'`, else the driver-app tap. Dwell is departure minus arrival.
3. A new geofence for a customer is a new row with `source = 'GPS_LEARNED'`; `_fences()` prefers it
   over the master-data fence. Never update rows in place (BigQuery streaming buffers forbid it).
4. Master-data changes go to `master_data_updates` (status `APPLIED`) and a `COMPANY_UPDATE` message
   in `tmw_dispatch_queue`. `_common.load_customers` overlays them, so planning uses them at once.
5. Run the deterministic report for a DC after any change:
   `uv run python .agents/skills/location-intelligence/scripts/location_report.py --dc DC-PHOENIX-AZ --as-of 10:30`
6. Tests live in `tests/test_location.py`. The generator writes planted ground truth to
   `data/synthetic/_planted_patterns.json` (bad geocodes, dwell changes); detection tests check
   against it.

## Examples
- "Use polygon geofences for big-box lots": add an optional `polygon_wkt` column in `schema.py`,
  point-in-polygon in `geofence._nearest`, keep circles as the fallback.
- "Restaurants with key drops have a 60 min tolerance": add a policy row per segment group or a
  per-customer override column, and pass it through `is_on_time`.

## Constraints
- Do not compute dwell or OTD in prompts; tools return them.
- Keep the Retail and Restaurant definitions in one place (`otd.py` / `otd_policies`).
- Do not let geofence detection or OTD logic depend on the routing-matrix provider.
