---
trigger: always_on
description: Repo map and McLane logistics glossary for the route optimization agent
---

# Project context

## Repo map
| Path | What |
|---|---|
| `route_optimizer/agent.py` | ADK agent tree: `root_agent` coordinator + 5 specialists |
| `route_optimizer/prompts.py` | All agent instructions (shared ground rules in `SHARED_CONTEXT`) |
| `route_optimizer/optimizer.py` | OR-Tools VRPTW: capacity/cold/weight/cube, time windows, HOS, pinning, `simulate_route` |
| `route_optimizer/planning.py` | Rows to optimizer inputs; learned p75 unload time; TMW static baseline builder |
| `route_optimizer/geo.py` | Distances, speeds, disruptions, optional Google Maps Routes API matrix |
| `route_optimizer/tools/` | ADK function tools (data, planning, disruption, event, tms, comms, analytics) |
| `route_optimizer/db/` | `schema.py` (single source of truth) and `repository.py` (SQLite / BigQuery / AlloyDB) |
| `route_optimizer/event_bus.py` | Pub/Sub publisher and worker |
| `data/` | Synthetic data generator, CSVs, rendered DDL, BigQuery and AlloyDB loaders |
| `deployment/` | Agent Engine, Cloud Run, Gemini Enterprise registration, Pub/Sub setup |
| `docs/SOLUTION.md` | Architecture, model, workflow, demo script, risks |
| `specs/001-dynamic-route-optimization/` | spec-kit artifacts |

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
