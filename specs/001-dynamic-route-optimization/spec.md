# Feature Specification: Dynamic Route Optimization

**Feature Branch**: `001-dynamic-route-optimization`
**Created**: 2026-10-26
**Status**: Implemented (hackathon MVP)
**Input**: "Build an agentic system that creates the daily route plan and re-optimizes it in real time when disruptions occur" (McLane hackathon brief, use case 1)

## User Scenarios & Testing

### User Story 1: Daily optimized plan (Priority: P1)
A night dispatcher at a McLane DC asks for tomorrow's plan and gets trucks, stop sequences and ETAs that
respect every constraint, with a comparison against the TMW static routes.

**Independent test**: `optimize_routes("DC-TEMPLE-TX", "2026-10-27")` returns a plan with no HOS violations,
no dropped HOT orders, and lower cost than the TMW static baseline.

**Acceptance scenarios**
1. **Given** open orders and an available fleet, **when** the dispatcher asks for a plan, **then** every order is
   assigned or listed as dropped with a reason, and totals (trucks, miles, cost, CO2, late stops, utilization) are
   shown next to the TMW static plan.
2. **Given** an order with chilled or frozen cases, **when** planned, **then** it never rides on a dry van.
3. **Given** a site that needs a liftgate or a 28 ft maximum vehicle, **when** planned, **then** only a compatible
   truck serves it.

### User Story 2: Real-time re-plan on events (Priority: P1)
When a truck is delayed, breaks down, an order is added or cancelled, a road closes, a store is closed, or a
reefer fails, the system re-plans only the affected routes and explains the change.

**Independent test**: each seeded event `EVT-*` on 2026-10-27 returns `what_changed`, KPIs before and after,
`untouched_routes > 0` and `replan_latency_s < 30`.

**Acceptance scenarios**
1. **Given** a delay under 15 minutes, **then** no re-plan happens (`NO_ACTION`) and the decision is logged.
2. **Given** a breakdown, **then** a spare tractor is assigned, the remaining stops are re-sequenced from the
   breakdown point, and the rescue cost is included.
3. **Given** a reefer temperature above 10°F, **then** the trailer gets zero cold capacity, cold product moves to a
   spare reefer unit, and the change is always escalated.
4. **Given** an added HOT order, **then** only trucks still at the DC or a spare unit may take it.

### User Story 3: Escalation and approval (Priority: P1)
**Given** an unavoidable SLA breach, an undeliverable order, a cost impact above $750 or a food-safety event,
**then** the re-plan is `PENDING_APPROVAL` with reasons, and the dispatcher approves or rejects it through a
confirmation step.

### User Story 4: Dispatch to TMW and notify customers (Priority: P2)
The dispatcher previews the TMW movement, leg header and stops, confirms, and the plan is queued (or posted) to
TMW. Stores and restaurants receive ETA notices by EDI 214 or SMS after confirmation.

### User Story 5: What-ifs and analytics (Priority: P3)
Scenarios (fewer trucks, wider windows, TMS unload times, no disruptions) and KPIs (on-time %, unload-time gap,
savings history, network roll-up), plus read-only BigQuery NL2SQL.

### Edge cases
- Unknown DC or date: a clear error listing valid values.
- No spare tractor for a breakdown: escalate and add a 2-hour delay for a rental unit.
- Event on a truck that has finished its stops: `NO_ACTION`.
- Replaying an already submitted plan to TMW: `ALREADY_SUBMITTED`.

## Requirements

### Functional
- **FR-001** Plan per DC and date with capacity (cases, cold, weight, cube), windows, HOS, max route duration,
  site restrictions and priorities.
- **FR-002** Compare with the TMW static routes using one shared cost and travel simulator.
- **FR-003** Use learned p75 unload times from 60 days of history by default.
- **FR-004** Apply traffic and weather disruptions as travel-time multipliers.
- **FR-005** Handle 7 event types and re-plan only affected routes. Product on a truck stays on that truck.
- **FR-006** Explain every change in plain language with time and cost impact.
- **FR-007** Escalate per the rules in User Story 3. Record approvals.
- **FR-008** Translate plans into TMW objects. Submission requires confirmation.
- **FR-009** Customer ETA notices, sent only after confirmation.
- **FR-010** Pub/Sub ingestion of events.
- **FR-011** SQLite, BigQuery and AlloyDB backends from one schema.
- **FR-012** Deployable to Agent Engine and registrable in Gemini Enterprise.

### Key entities
DC, Customer, Tractor, Trailer, Driver, Order, Route, RouteStop, DeliveryHistory, TrafficEvent, WeatherEvent,
RouteEvent, EventAction, ReplanApproval, OptimizationRun, TmwDispatchMessage, CustomerNotification
(see `data-model.md`).

## Success criteria
- **SC-001** Network cost at least 10% below the TMW static plan on the synthetic 2026-10-27 day (achieved: 23%).
- **SC-002** Zero hard-constraint violations in optimized plans.
- **SC-003** Event re-plan latency under 30 s (achieved: 2 to 8 s).
- **SC-004** 100% of re-plans carry an explanation and an audit row.

## Clarifications
- Q: Are time windows hard? A: Soft (60 minutes, penalized) unless `hard_window` (dock appointment).
- Q: Can stops move between trucks already on the road? A: No. Product is loaded, so stops are pinned to their truck.
- Q: Approval threshold? A: $750 cost impact (configurable `ESCALATION_COST_USD`).
- Q: Delay trigger? A: 15 minutes (`DELAY_TRIGGER_MIN`).
- Q: Real TMW API? A: Out of scope for the hackathon. A queue table plus an optional REST POST behind `TMW_API_BASE_URL`.
