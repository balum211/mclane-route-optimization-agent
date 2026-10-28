# Research: McLane location intelligence, OTD and PC*MILER

## PC*MILER Web Services
- Decision: `GET .../Service.svc/route/routeReports` with `reports=Mileage`, `stops=lon,lat;...`,
  `Authorization: <key>` header; parse `ReportLines[].LMiles` and `THours`, accept `TDistance` / `TMinutes`.
- Rationale: one request prices a whole route; matches how TMW stores leg and stop mileage.
- Open item: confirm parameter names (`routeType`, `vehType`, `dataVer`, `region`) for McLane's PC*MILER version.
- Alternative: pairwise matrix from PC*MILER for the solver; offered behind `TRAVEL_PROVIDER=pcmiler` with a size cap
  because it costs n² calls.

## Geofence detection
- Decision: circle geofences with exit hysteresis (×1.3) and a 3-minute minimum visit.
- Rationale: GPS jitter of 10 to 30 m at the fence edge otherwise splits one stop into two; drive-bys are short.
- Alternative: polygons for big lots (future, see Antigravity prompt D3).

## Dwell change
- Decision: medians for detection (robust to one long DOCK_BUSY visit), p75 for the recommended standard
  (matches the planner). Thresholds 8 min and 25% chosen on planted data: precision 0.88, recall 0.82
  (5 min / 15% gave 0.53 / 0.93).

## OTD definitions
- Retail measured against the receiving window; early arrivals wait and are not misses.
- Restaurant measured against the scheduled time ±30 min because crews are scheduled around the truck.
- A new plan has no promised time yet, so planned OTD uses windows; re-plans use the ETAs already given.

## MCP Toolbox format
- The sdd-adk-antigravity starter uses the multi-document `kind: source` / `kind: tool` / `kind: toolset` format with
  `type:`. AlloyDB source fields: project, region, cluster, instance, database, user, password, optional ipType.
