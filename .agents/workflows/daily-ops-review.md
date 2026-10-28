---
description: Morning operations review for one DC: truck positions, geofence arrivals and dwell overruns, re-plans, dwell changes, bad geocodes and Retail/Restaurant OTD
---

Input: a DC id, an operating date and a time, e.g. "DC-PHOENIX-AZ 2026-10-27 10:30". Use the
location-intelligence and pcmiler-mileage skills.

1. Run `uv run python .agents/skills/location-intelligence/scripts/location_report.py --dc <DC> --date <date> --as-of <time>`.
   Stop and report if it fails.
2. For every DWELL_OVERRUN event of that DC and date (seeded, or new ones listed in the report), run
   `event_tools.handle_route_event` through a short Python snippet and keep what_changed, otd_impact
   and replan_latency_s.
3. Run `uv run python .agents/skills/pcmiler-mileage/scripts/compare_mileage.py --dc <DC> --date <date>`.
4. Create an artifact "Daily ops review <DC> <date>" with sections: Trucks stuck on site, Re-plans
   (with restaurants whose ETA moved more than 30 min), Planned stops without geofence arrival,
   Dwell changes and recommended TMW standards, Bad geocodes, Retail and Restaurant OTD versus
   target, PC*MILER versus matrix miles. Use the exact numbers from the outputs.
5. Do not apply master-data updates or send anything to TMW. List them as recommendations for the
   dispatcher to approve in the agent (apply_master_data_updates asks for confirmation).
