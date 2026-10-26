# Tasks: Dynamic Route Optimization

Legend: [P] = can run in parallel. All tasks are done in this branch.

## Phase 1: Setup
- [x] T001 Project skeleton, `pyproject.toml`, `requirements.txt`, `.env.example`, `AGENTS.md`
- [x] T002 [P] Single schema definition `route_optimizer/db/schema.py` with DDL renderers
- [x] T003 [P] Repository layer for SQLite, BigQuery and AlloyDB (`db/repository.py`)

## Phase 2: Foundational
- [x] T004 Synthetic generator: DCs, customers, fleet sized to demand, orders, history, traffic, weather, events
- [x] T005 Travel model and disruptions (`geo.py`), optional Routes API matrix
- [x] T006 OR-Tools VRPTW (`optimizer.py`) and shared `simulate_route`
- [x] T007 TMW static baseline builder (`planning.static_tmw_plan`)
- [x] T008 [P] Solver unit tests (`tests/test_optimizer.py`)

## Phase 3: US1, daily plan
- [x] T009 Data tools: DCs, demand, fleet, customer profile, disruptions
- [x] T010 `optimize_routes` with baseline comparison and persistence
- [x] T011 `run_what_if_scenarios`, `get_route_plan`
- [x] T012 Route planner agent and coordinator (`agent.py`, `prompts.py`)

## Phase 4: US2 and US3, events and escalation
- [x] T013 `route_events`, `event_actions`, `replan_approvals` tables and seed events
- [x] T014 `_handle` with 7 event types, pinning, spare units, rescue tractor, reefer split
- [x] T015 Escalation rules and `decide_replan` (confirmation)
- [x] T016 `simulate_route_event`, `list_route_events`, `get_pending_escalations`
- [x] T017 Tests for every seed event, latency, reefer escalation, NO_ACTION

## Phase 5: US4 and US5
- [x] T018 [P] TMW payloads, `submit_plan_to_tmw` (confirmation), status
- [x] T019 [P] ETA notices draft and send (confirmation)
- [x] T020 [P] Analytics tools and optional BigQuery NL2SQL toolset

## Phase 6: Platform
- [x] T021 BigQuery and AlloyDB loaders (AlloyDB verified on PostgreSQL 16)
- [x] T022 Pub/Sub event bus (publish, worker, local)
- [x] T023 Agent Engine, Cloud Run, Gemini Enterprise and Pub/Sub scripts
- [x] T024 Scripted-LLM end-to-end ADK test

## Phase 7: Polish
- [x] T025 `docs/SOLUTION.md` in the hackathon output format
- [x] T026 Antigravity prompts, skills, workflows, spec-kit artifacts
- [x] T027 `scripts/demo_run.py` offline demo

## Next (not started)
- [ ] T028 Telematics pings table and GPS-based truck position
- [ ] T029 DC dock-door capacity constraint
- [ ] T030 Route-consistency objective
- [ ] T031 Traffic-aware Routes API matrix with caching
