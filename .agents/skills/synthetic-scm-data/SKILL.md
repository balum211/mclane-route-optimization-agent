---
name: synthetic-scm-data
description: Use when generating, extending or reloading the synthetic McLane logistics dataset (DCs, customers, fleet, drivers, orders, history, traffic/weather, route events) or adding a table or column.
---

# Synthetic SCM data

## Goal
Keep a realistic, deterministic dataset that exercises every constraint and event the agents handle,
loadable into SQLite, BigQuery and AlloyDB from the same definition.

## Instructions
1. The schema lives only in `route_optimizer/db/schema.py`. Add columns there with a clear
   description, because BigQuery column descriptions feed Gemini NL2SQL.
2. Generate data in `data/generate_synthetic_data.py`. Keep it deterministic (`random.Random(seed)`)
   and fictional (no real customer names).
3. Regenerate: `python data/generate_synthetic_data.py`. This writes `data/synthetic/*.csv`,
   `data/mclane_routing.db` and `data/schema/{sqlite,alloydb,bigquery}.sql` plus
   `data/schema/bigquery_json/*.json`.
4. Validate: `python .agents/skills/schema-validator/scripts/validate_schema.py`.
5. Reload cloud copies: `python data/load_bigquery.py --project <p> --replace` and/or
   `python data/load_alloydb.py --replace`.
6. Run `python -m pytest -q`.

## Examples
- Add a `telematics_pings` table (tractor, minute, lat, lon, speed, reefer temp): define it in
  `schema.py`, generate pings along TMW static routes in the generator, and teach `_live()` in
  `tools/event_tools.py` to read the latest ping for truck position.
- Scale up: raise `customers` per DC in `DCS`. The fleet is sized automatically from peak daily cases.

## Constraints
- Times are minutes after midnight in `*_min` INT columns.
- Do not hand-edit CSVs or rendered SQL; regenerate them.
- Keep the 2026-10-27 demo events (`gen_route_events`) working; tests depend on them.
