# McLane Dynamic Route Optimization Constitution

## Core Principles

### I. Deterministic optimization, explained by AI
Routes, ETAs, costs and savings are computed by OR-Tools and deterministic tools. Gemini agents orchestrate,
ask clarifying questions and explain results, and must never state a number that no tool returned.

### II. Hard constraints are never traded away
Capacity (cases, cold cases, weight, cube), temperature zones, driver hours of service (11 h drive, 14 h duty),
dock appointments, site restrictions and product-on-truck pinning are solver constraints. Receiving windows are
soft with explicit penalties unless marked hard.

### III. Human in the loop for consequential actions
Writing to Trimble TMW, messaging customers and approving escalated re-plans require explicit confirmation.
Re-plans escalate when an SLA breach is unavoidable, an order cannot be delivered, the cost impact exceeds the
configured threshold, or food safety is involved.

### IV. Minimal disruption, fast reaction
An event re-plans only the routes it touches. Every re-plan reports untouched routes, before and after KPIs,
cost impact and latency, and finishes in under 30 seconds.

### V. One schema, portable data
A single schema definition renders SQLite (offline demo), BigQuery (analytics and NL2SQL) and AlloyDB
(transactional) DDL. SQL stays portable. Synthetic data is deterministic and fictional.

### VI. Test-first, offline by default
Every tool and event type has tests that run offline against synthetic data, with no LLM calls. Agent wiring
is tested with a scripted model.

### VII. McLane measures of record
Mileage is Trimble PC*MILER (practical) wherever it reaches TMW, pay or billing, and offline estimates are
labelled `PCMILER_EMULATED`. Arrival, departure and dwell come from geofences (driver app as the fallback).
On-time delivery is reported separately for Retail (receiving-window close) and Restaurant (scheduled time
±30 min, inside the window), defined once in `otd.py` / `otd_policies`. Customer master-data changes
(dwell standard, geocode) need confirmation, are insert-only and are queued to TMW.

## Operational constraints
- Python 3.11+, Google ADK, Gemini on Vertex AI, OR-Tools. Deploy to Vertex AI Agent Engine and register in
  Gemini Enterprise.
- Every plan, event action, approval, TMW message and customer notice is logged for audit.
- No secrets in the repo. Use Secret Manager in cloud deployments.

## Governance
This constitution overrides conflicting guidance in specs or prompts. Amendments need a note in the PR
description explaining the principle changed and why.

**Version**: 1.1.0 | **Ratified**: 2026-10-26 | **Last Amended**: 2026-10-28 (added VII for PC*MILER, geofence and OTD)
