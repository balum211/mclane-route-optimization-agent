# PRD: Dynamic Route Optimization for McLane (hackathon, Oct 27-28 2026)

## Problem
McLane DCs run fixed, territory-based routes kept in Trimble TMW. Those routes ignore each day's real demand,
receiving windows, true unload times and traffic, so trucks run extra miles, drivers wait at docks, and stores and
restaurants get late deliveries. When something goes wrong mid-route (a breakdown, a late truck, an emergency
order), dispatchers re-plan by phone and spreadsheet.

## Users
- **Night dispatcher** (primary): builds and releases tomorrow's routes; handles exceptions during the run.
- **Transportation manager**: approves costly changes; tracks cost, on-time % and driver hours.
- **Store or restaurant manager** (indirect): needs an accurate ETA.

## User experience
1. The dispatcher asks in Gemini Enterprise: "Plan tomorrow for Temple." The agent summarizes demand and fleet,
   builds the plan, and shows trucks, miles, cost, on-time % and CO2 next to today's TMW routes, with a short
   "why it's better."
2. The dispatcher drills into a route, tries a what-if, and releases the plan to TMW after a confirmation.
3. During the run, events arrive on their own (telematics, driver app, TMW). For each one the agent says what
   happened, which trucks are affected, what it changed, and what it costs. Routine changes are applied
   automatically. Anything that breaks an SLA, costs more than the threshold, or touches food safety waits
   for approval.
4. Affected customers get an updated ETA after the dispatcher confirms.

## Success
- Cost per case and miles per stop below the static routes; on-time % at or above 98%.
- Under 30 seconds from event to proposed change; no hard-constraint violations.
- Dispatchers accept most auto-applied changes without manual rework (track the override rate).

## Out of scope (hackathon)
Live TMW write-back, real telematics, driver mobile app, multi-day planning.
