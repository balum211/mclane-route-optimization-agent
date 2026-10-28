# Tasks: McLane location intelligence, OTD and PC*MILER

Legend: [P] = can run in parallel. All tasks are done in this branch.

## Phase 1: Foundations
- [x] T001 Schema: new tables and columns in `route_optimizer/db/schema.py`; regenerate DDL
- [x] T002 [P] `otd.py`: segment groups, policies, `is_on_time`, `summarize`, `plan_otd`
- [x] T003 [P] `geofence.py`: visits with hysteresis, stop detection, learned location
- [x] T004 [P] `pcmiler.py`: live route reports, emulation, matrix, `stamp_routes`
- [x] T005 Generator: geocodes (7% ZIP centroid), geofences, dwell shifts (13%), geofenced history, GPS pings, DWELL_OVERRUN seed

## Phase 2: US1 PC*MILER
- [x] T006 Stamp plans and baselines in `planning_tools._run`; persist route and stop miles
- [x] T007 Stamp re-plans in `event_tools._persist`
- [x] T008 TMW payload `lgh_miles`, `stp_lgh_mileage` (incl. empty return), `mileage_type`, `mileage_source`
- [x] T009 `TRAVEL_PROVIDER=pcmiler` in `geo.build_matrix`

## Phase 3: US2 geofence
- [x] T010 `get_vehicle_locations`, `detect_geofence_events` (idempotent, raises DWELL_OVERRUN)
- [x] T011 `DWELL_OVERRUN` branch in `_handle`; telematics events re-plan the running route
- [x] T012 OTD impact in every re-plan; restaurants whose ETA moves > 30 min

## Phase 4: US3-US5
- [x] T013 Recent-first p75 in `learned_service_minutes`
- [x] T014 `analyze_dwell_time_changes`, `validate_customer_geolocations`, `apply_master_data_updates` (confirmation)
- [x] T015 `get_otd_by_segment`; OTD by group in `get_delivery_kpis`; planned OTD in plans
- [x] T016 `location_intelligence_agent`; prompts updated for PC*MILER, geofence, OTD

## Phase 5: Antigravity and polish
- [x] T017 `/speckit.*` workflows, `.specify/templates` and scripts from the codelab starter
- [x] T018 Root `tools.yaml` (new Toolbox format), `server.py`, `antigravity/mcp_config.json`, `uv.lock`
- [x] T019 Skills: location-intelligence, pcmiler-mileage, mcp-toolbox-alloydb, repo-research; `/daily-ops-review`
- [x] T020 Tests `tests/test_location.py`; docs, README, PROMPTS, constitution v1.1.0
