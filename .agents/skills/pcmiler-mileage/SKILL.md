---
name: pcmiler-mileage
description: Use when touching mileage: Trimble PC*MILER miles on routes, plans or TMW payloads, the PC*MILER Web Services client, the offline PC*MILER emulation, TRAVEL_PROVIDER=pcmiler, or comparing matrix miles with PC*MILER miles.
---

# PC*MILER mileage

## Goal
PC*MILER is McLane's mileage of record in TMW (rating, driver pay, billing). Every route the agent
saves or sends carries PC*MILER miles, computed the same way for the optimized plan and the TMW
static baseline, and clearly labelled when emulated.

## Instructions
1. Code lives in `route_optimizer/pcmiler.py`:
   - `route_mileage(points)`: one request per stop sequence (DC, stops, DC), cached.
   - `stamp_routes(routes, depot)`: sets `RouteResult.pcmiler_miles`, `mileage_source` and each
     stop's `pcmiler_leg_miles`. Called in `planning_tools._run`, `event_tools._persist` and the
     data generator.
   - `matrix(points)`: pairwise matrix for `TRAVEL_PROVIDER=pcmiler` (capped by
     `PCMILER_MATRIX_MAX_POINTS`, beyond which it uses the emulation).
2. Live mode needs `PCMILER_API_KEY`. Request and response fields are in
   `references/pcmiler_api.md`; confirm them against the account's PC*MILER Web Services version and
   adjust `_live_route` / `_parse_report` only there.
3. Emulation: great-circle miles x `CIRCUITY[routing_type]` x a deterministic +-4% lane factor.
   Its output is always `PCMILER_EMULATED`. Do not tune it to "look like" real PC*MILER output.
4. TMW: `tms_tools._payloads` writes `lgh_miles` (route PC*MILER miles), `stp_lgh_mileage` per stop
   including the empty return leg, `mileage_type` and `mileage_source`.
5. Compare matrix and PC*MILER miles for a plan:
   `uv run python .agents/skills/pcmiler-mileage/scripts/compare_mileage.py --dc DC-TEMPLE-TX`

## Constraints
- Never fail a plan because PC*MILER is down: fall back to the emulation and label it.
- Never present emulated miles as PC*MILER miles in prompts, docs or payloads.
- Do not call PC*MILER per pair for mileage of record; one route report per route.
