# Implementation Plan: McLane location intelligence, OTD and PC*MILER

**Branch**: `002-mclane-location-otd-pcmiler` | **Spec**: `spec.md` | **Date**: 2026-10-28

## Summary
Add three deterministic modules (`pcmiler.py`, `geofence.py`, `otd.py`), one tool module
(`tools/location_tools.py`), one specialist agent (`location_intelligence_agent`) and one analytics tool
(`get_otd_by_segment`). Extend the schema and generator, and stamp PC*MILER miles wherever routes are saved.

## Technical context
Python 3.11+, Google ADK 2.x `LlmAgent` / `FunctionTool`, OR-Tools, SQLite / BigQuery / AlloyDB through the
existing repository, `requests` for PC*MILER Web Services, optional `toolbox-core` for MCP Toolbox.

## Constitution check
- I Deterministic: geofence, dwell, OTD and mileage are tools; prompts only explain. ✓
- II Hard constraints: unchanged; DWELL_OVERRUN reuses the shared re-plan path. ✓
- III Human in the loop: `apply_master_data_updates` is `require_confirmation=True`. ✓
- IV Minimal disruption: telematics events re-plan the running route only. ✓
- V One schema: all new tables in `schema.py`; insert-only writes. ✓
- VI Tests offline: `tests/test_location.py`, planted ground truth. ✓
- VII McLane measures: PC*MILER labelled, OTD defined once. ✓

## Design
| Piece | Decision |
|---|---|
| PC*MILER mileage of record | One route report per final route (`stamp_routes`), cached; matrix only on request |
| Emulation | Great-circle × routing-type circuity × deterministic ±4% lane factor, always labelled |
| Geofence | Circles; entry inside radius, exit beyond radius × 1.3, visits under 3 min dropped |
| Dwell for planning | Recent 14-day p75 when ≥ 4 visits, else 60-day p75 |
| Dwell change | Median recent vs baseline, thresholds 8 min and 25%; recommended standard = recent p75 rounded to 5 |
| Geocodes | Median of telematics stop points per customer vs TMW point, flag ≥ 250 m |
| OTD | Retail: arrival ≤ window close. Restaurant: |arrival − scheduled| ≤ 30 and ≤ window close |
| Master data | Insert-only `master_data_updates` overlay in `load_customers`; `COMPANY_UPDATE` queue message |
| Toolbox | Root `tools.yaml` in `kind: source` / `kind: tool` format; optional toolset load when `TOOLBOX_URL` set |

## Project structure (new or changed)
```
route_optimizer/pcmiler.py, geofence.py, otd.py
route_optimizer/tools/location_tools.py
route_optimizer/tools/{planning,event,tms,analytics,data}_tools.py, _common.py
route_optimizer/{agent,prompts,config,planning,optimizer,geo}.py, db/schema.py
data/generate_synthetic_data.py
tests/test_location.py
tools.yaml, server.py, antigravity/mcp_config.json
.agents/skills/{location-intelligence,pcmiler-mileage,mcp-toolbox-alloydb,repo-research}/
.agents/workflows/{speckit.*,daily-ops-review}.md
```
