# Feature Specification: McLane location intelligence, OTD and PC*MILER

**Feature Branch**: `002-mclane-location-otd-pcmiler`
**Created**: 2026-10-28
**Status**: Implemented (hackathon MVP)
**Input**: "McLane uses PCMiler, Dwell Time Change, Retail & Restaurant Ontime Delivery (OTD), Geofence, Geo locations" (Bala Mallampati, 2026-10-28)

## User Scenarios & Testing

### User Story 1: PC*MILER is the mileage of record (Priority: P1)
A transportation manager compares the optimized plan with the TMW static routes in the miles TMW pays and bills on.

**Independent test**: `optimize_routes` returns `pcmiler_miles` for both plans and every route, `mileage.source`
is `PCMILER_EMULATED` offline, and the TMW payload's `lgh_miles` equals the route's PC*MILER miles with stop
mileages adding up to it.

**Acceptance scenarios**
1. **Given** no PC*MILER key, **when** a plan is built, **then** every route carries emulated PC*MILER miles,
   labelled `PCMILER_EMULATED`.
2. **Given** a PC*MILER key and a reachable service, **when** a plan is built, **then** each route is priced with one
   route report and labelled `PCMILER`.
3. **Given** the service fails, **when** a plan is built, **then** planning succeeds with the emulation and says so.

### User Story 2: Geofence arrivals, dwell and stuck trucks (Priority: P1)
A dispatcher sees where every truck is, which stops have been reached, and which truck has sat at a dock too long.

**Independent test**: `detect_geofence_events("DC-PHOENIX-AZ", "2026-10-27", "10:30")` reports TRC-PHO-002 still
inside a customer geofence 29 minutes over plan; `handle_route_event("EVT-PHO-02")` re-plans route
R-20261027-PHO-S02 in under 30 s and lists restaurants whose ETA moved more than 30 minutes.

**Acceptance scenarios**
1. **Given** GPS jitter at the edge of a geofence, **when** visits are detected, **then** one stop is one visit.
2. **Given** a truck inside a customer geofence 15+ minutes past the planned unload time, **when** the engine runs,
   **then** a `DWELL_OVERRUN` event exists for it (seeded or new, never duplicated).
3. **Given** a planned stop with no geofence arrival, **when** reported, **then** its geocode source is shown.

### User Story 3: Dwell time change (Priority: P2)
A master-data analyst learns which customers' dwell changed and what the TMW standard should be.

**Independent test**: `analyze_dwell_time_changes("DC-TEMPLE-TX")` finds most planted dwell shifts with the right
direction; `apply_master_data_updates(..., "DWELL", [...])` changes the standard used for planning and queues a
`COMPANY_UPDATE`.

### User Story 4: Geolocations (Priority: P2)
**Independent test**: `validate_customer_geolocations("DC-PHOENIX-AZ")` flags every planted bad geocode; applying
a GEOCODE fix moves the planning point and adds a GPS-learned geofence.

### User Story 5: Retail and Restaurant OTD (Priority: P1)
**Independent test**: `get_otd_by_segment()` returns RETAIL and RESTAURANT OTD with targets 95% and 98%, per DC
and segment, miss causes, and restaurant early versus late misses. Plans and re-plans report OTD by group.

### Edge cases
- Customers with fewer than 3 recent or 5 baseline visits are not judged for dwell change.
- A geofence visit still open at `as_of` is never saved (insert-only tables); it is reported as on site.
- Telematics events carry the running `route_id`, so a newer plan for the day does not hijack them.

## Requirements

### Functional
- **FR-001** Every persisted route, plan, what-if and TMW payload carries PC*MILER miles and a mileage source.
- **FR-002** `TRAVEL_PROVIDER=pcmiler` builds the solver matrix from PC*MILER, capped in size.
- **FR-003** Geofence per customer and DC; visits from GPS with exit hysteresis and a minimum dwell.
- **FR-004** `DWELL_OVERRUN` events re-plan from the customer's location like a delay.
- **FR-005** Planning uses the recent (14-day) p75 dwell when there are at least 4 recent visits.
- **FR-006** Dwell change detection with recommended TMW standard and weekly minutes at stake.
- **FR-007** Geocode validation against observed parking positions.
- **FR-008** Master-data fixes need confirmation, are insert-only, apply to planning at once and queue `COMPANY_UPDATE`.
- **FR-009** Retail and Restaurant OTD policies in one module and table; reported in plans, re-plans, today's arrivals and history.

### Key entities
`geofences`, `gps_pings`, `geofence_events`, `otd_policies`, `master_data_updates`; new columns on `customers`
(geocode source and confidence), `delivery_history` (arrival source, departure, GPS stop point, tractor),
`routes` / `route_stops` / `optimization_runs` (PC*MILER miles).

## Success criteria
- **SC-001** 38 offline tests pass, including planted-pattern detection.
- **SC-002** Dwell-change detection precision ≥ 0.85 and recall ≥ 0.8 on the planted shifts (measured 0.88 / 0.82).
- **SC-003** Every planted bad geocode is flagged.
- **SC-004** DWELL_OVERRUN re-plan latency under 30 s (measured 2.0 s).

## Clarifications
- Q: What is Restaurant OTD measured against? A: The scheduled delivery time ±30 min, and never after the window.
- Q: Is early delivery a Retail miss? A: No. Early is fine for Retail; late after window close is a miss.
- Q: Which PC*MILER routing type? A: Practical, configurable with `PCMILER_ROUTING_TYPE`.
- Q: Should master-data fixes write to TMW directly? A: No. Queue `COMPANY_UPDATE` after confirmation.
