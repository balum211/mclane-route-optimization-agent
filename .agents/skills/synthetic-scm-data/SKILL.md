---
name: synthetic-scm-data
description: Use when generating, extending or reloading the synthetic McLane logistics dataset (DCs, customers, geofences, fleet, drivers, orders, geofence history, GPS pings, traffic/weather, route events, OTD policies) or adding a table or column.
---

# Synthetic SCM data

## Goal
Keep a realistic, deterministic dataset that exercises every constraint and event the agents handle,
loadable into SQLite, BigQuery and AlloyDB from the same definition.

## Instructions
1. The schema lives only in `route_optimizer/db/schema.py`. Add columns there with a clear
   description, because BigQuery column descriptions feed Gemini NL2SQL.
2. Generate data in `data/generate_synthetic_data.py`. Keep it deterministic (`random.Random(seed)`)
   and fictional (no real customer names). Location features (geocodes, dwell shifts, GPS pings) draw
   from a second generator `xr`, so adding them does not reshuffle the base data.
3. Planted patterns the agent must find are written to `data/synthetic/_planted_patterns.json`
   (never loaded into a database): customers with a bad TMW geocode, and customers whose dwell
   changed in the last 14 days. A planted `DWELL_OVERRUN` (EVT-PHO-02) matches the Phoenix GPS pings.
4. Regenerate: `uv run python data/generate_synthetic_data.py`. This writes `data/synthetic/*.csv`,
   `data/mclane_routing.db` and `data/schema/{sqlite,alloydb,bigquery}.sql` plus
   `data/schema/bigquery_json/*.json`.
5. Validate: `uv run python .agents/skills/schema-validator/scripts/validate_schema.py`.
6. Reload cloud copies: `uv run python data/load_bigquery.py --project <p> --replace` and/or
   `uv run python data/load_alloydb.py --replace`.
7. Run `uv run pytest -q`.

## Examples
- Add reefer temperatures to `gps_pings`: add `reefer_temp_f` in `schema.py`, generate it in
  `gen_gps_pings` (drift up after the Dallas reefer event time), and let `detect_geofence_events`
  or a new tool raise `REEFER_TEMP_ALERT` events from it.
- GPS for more days: call `gen_gps_pings` for each `executed` day of `build_static_routes`.
- Scale up: raise `customers` per DC in `DCS`. The fleet is sized automatically from peak daily cases.

## Constraints
- Times are minutes after midnight in `*_min` INT columns.
- Do not hand-edit CSVs or rendered SQL; regenerate them.
- Keep the 2026-10-27 demo events (`gen_route_events`) working; tests depend on them.
