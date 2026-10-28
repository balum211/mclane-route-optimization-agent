---
description: Add a new real-time event type to the disruption re-planner end to end (schema, handler, tests, prompt, docs)
---

Input: the event type name and the business rule, e.g. "DRIVER_HOS_WARNING: driver runs out of duty in 60 min".

1. Use the adk-tool-builder and route-optimizer-solver skills.
2. Add the type to `EVENT_TYPES` and document it in the `event_type` column description in
   `route_optimizer/db/schema.py`. Regenerate data.
3. In `route_optimizer/tools/event_tools.py::_handle`, add a branch that builds the affected `Live`
   routes, any new stops or spare vehicles, notes for the explanation, and escalation reasons. Reuse
   the shared re-plan, explain and persist code below the branches. Do not add a second solver path.
4. Add a seed event for 2026-10-27 in `gen_route_events` and a test in `tests/test_tools.py` asserting
   status, latency under 30 s, `untouched_routes > 0` and the escalation rule.
5. Update the event table in `route_optimizer/prompts.py` (DISRUPTION) and `docs/SOLUTION.md` §3.
6. If the event comes from telematics or the geofence engine, put the running `route_id` in the
   payload so `_handle` re-plans the route the truck is actually on. Make sure `otd_impact` still
   reports Retail and Restaurant OTD.
7. Run `uv run pytest -q` and show the new event's output from `simulate_route_event`.
