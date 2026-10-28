---
trigger: always_on
description: Repo map and McLane logistics glossary for the route optimization agent
---

# Project context

## Repo map
| Path | What |
|---|---|
| `route_optimizer/agent.py` | ADK agent tree: `root_agent` coordinator + 6 specialists (incl. `location_intelligence_agent`) |
| `route_optimizer/prompts.py` | All agent instructions (shared ground rules in `SHARED_CONTEXT`) |
| `route_optimizer/optimizer.py` | OR-Tools VRPTW: capacity/cold/weight/cube, time windows, HOS, pinning, `simulate_route` |
| `route_optimizer/planning.py` | Rows to optimizer inputs; recent-first p75 dwell; TMW static baseline builder |
| `route_optimizer/geo.py` | Distances, speeds, disruptions; matrix providers haversine / pcmiler / google_routes |
| `route_optimizer/pcmiler.py` | Trimble PC*MILER mileage of record: live route reports or labelled emulation; `stamp_routes` |
| `route_optimizer/geofence.py` | Geofence engine: visits (arrive/depart/dwell), stop detection, learned locations |
| `route_optimizer/otd.py` | Retail and Restaurant OTD policies, `is_on_time`, `summarize`, `plan_otd` |
| `route_optimizer/tools/` | ADK function tools (data, planning, disruption, event, location, tms, comms, analytics) |
| `route_optimizer/db/` | `schema.py` (single source of truth) and `repository.py` (SQLite / BigQuery / AlloyDB) |
| `route_optimizer/event_bus.py` | Pub/Sub publisher and worker |
| `server.py` | FastAPI app from ADK `get_fast_api_app` (dev UI + REST endpoints) |
| `tools.yaml` | MCP Toolbox for Databases: read-only AlloyDB / BigQuery tools, toolsets `mclane-dispatch`, `mclane-analytics` |
| `antigravity/` | Paste-ready prompts and `mcp_config.json` (ADK Docs MCP + Toolbox) |
| `data/` | Synthetic data generator, CSVs, rendered DDL, BigQuery and AlloyDB loaders |
| `deployment/` | Agent Engine, Cloud Run, Gemini Enterprise registration, Pub/Sub setup |
| `docs/SOLUTION.md` | Architecture, model, workflow, demo script, risks |
| `specs/001-dynamic-route-optimization/`, `specs/002-mclane-location-otd-pcmiler/` | spec-kit artifacts |
| `.specify/` | spec-kit constitution, templates and scripts; `.agents/workflows/speckit.*.md` are the commands |

## Glossary
- **DC**: distribution center. GROCERY DCs serve c-stores, grocery and mass merchants; FOODSERVICE DCs serve QSR and casual-dining restaurants.
- **Trimble TMW / TMW.Suite**: the TMS. Objects: order header (`ord_hdrnumber`), movement, leg header (`lgh_tractor`, `lgh_primary_trailer`, `lgh_driver1`), stops (`stp_type` PUP/DRP), company (`cmp_id`).
- **Static route**: a fixed territory route kept in TMW (the baseline).
- **Multi-temp trailer**: 3-compartment reefer (dry, chill, frozen). Modeled as total cases plus cold cases capacity.
- **HOS**: FMCSA hours of service, 11 h driving and 14 h on duty.
- **Receiving window**: when a store or restaurant accepts deliveries. `hard_window` means a dock appointment.
- **Key drop**: unattended restaurant delivery after hours.
- **HOT / STANDARD / FLEX**: order priority. FLEX may move to the next delivery day.
- **Times** are stored as minutes after midnight (`*_min`); `fmt_time` renders HH:MM.
- **PC*MILER**: Trimble's truck mileage engine; TMW rates, pays and bills on PC*MILER practical miles. `pcmiler_miles` on routes and plans; `mileage_source` PCMILER or PCMILER_EMULATED.
- **Geofence**: circle around a customer dock or DC yard (`geofences`). Entry = arrival, exit = departure, the difference = dwell. `arrival_source` GEOFENCE, or DRIVER_APP when the fence missed.
- **Geocode**: the customer's lat/lon in TMW master data (`geocode_source` ADDRESS_ROOFTOP, ZIP_CENTROID, GPS_LEARNED). A bad geocode makes the geofence miss.
- **Dwell time change**: recent 14-day dwell versus history and the TMW standard (`std_service_min`).
- **OTD**: on-time delivery. Retail (CONVENIENCE, GROCERY, MASS_MERCHANT) by window close; Restaurant (QSR, CASUAL_DINING) within ±30 min of the scheduled time and inside the window. Targets 95% and 98% (`otd_policies`).
- **DWELL_OVERRUN**: route event raised when a truck is still inside a customer geofence 15+ min past the planned unload time.
