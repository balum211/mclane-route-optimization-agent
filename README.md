# McLane Dynamic Route Optimization Agent

A Google ADK multi-agent system that builds McLane's daily delivery routes and re-plans them in real time when trucks break down, run late, sit too long at a dock, orders change or roads close. Google OR-Tools does the optimization, Gemini orchestrates and explains, Trimble TMW stays the TMS of record and Trimble PC*MILER the mileage of record. GPS and geofences timestamp arrivals and dwell, and on-time delivery is measured the McLane way: Retail against the receiving window, Restaurant against the scheduled time. Data runs on BigQuery or AlloyDB, or offline on SQLite for demos. It deploys to Vertex AI Agent Engine and surfaces in Gemini Enterprise.

> Hackathon use case 1 of 3 (Google hackathon, Oct 27-28 2026). All data is synthetic and every company and person name is fictional.

**Results on the synthetic network** (4 DCs, 2026-10-27, `uv run python scripts/demo_run.py`):

| | TMW static routes | AI optimized | Change |
|---|---|---|---|
| Trucks | 48 | 45 | −3 |
| PC*MILER miles (emulated offline) | 5,235 | 4,212 | −19.5% |
| Cost | $34,902 | $26,300 | **−24.6% ($8,602/day)** |
| On-time stops | 88.0% | 99.5% | +11.5 pts |
| Event re-plan latency | | 2 to 8 s | target < 30 s |

60-day OTD from geofence arrivals: Retail 99.5% (target 95%), Restaurant 83.8% (target 98%).

## McLane specifics

| Need | How it works here |
|---|---|
| **PC*MILER** mileage | Every route, plan, what-if and TMW payload carries PC*MILER practical miles. Set `PCMILER_API_KEY` for PC*MILER Web Services; without it an offline emulation is used and labelled `PCMILER_EMULATED`. `TRAVEL_PROVIDER=pcmiler` also feeds PC*MILER into the solver matrix. (`route_optimizer/pcmiler.py`) |
| **Geolocations** | Customer coordinates carry geocode source and confidence; `validate_customer_geolocations` compares them with where trucks actually park and finds bad geocodes. |
| **Geofence** | A geofence per customer and DC. `detect_geofence_events` turns GPS pings into arrivals, departures and dwell, spots trucks stuck at a dock and raises `DWELL_OVERRUN` events. (`route_optimizer/geofence.py`) |
| **Dwell time change** | `analyze_dwell_time_changes` compares the last 14 days with history and the TMW standard and recommends a new standard. The planner already uses the recent p75. `apply_master_data_updates` (with confirmation) queues the TMW company update. |
| **Retail and Restaurant OTD** | Retail: on time by window close. Restaurant: within ±30 min of the scheduled time and inside the window. Reported in plans, re-plans, today's geofence arrivals and `get_otd_by_segment`. (`route_optimizer/otd.py`, `otd_policies` table) |

## What's inside

```
route_optimizer/            ADK agent package (what `adk web` / `adk deploy` load)
  agent.py                  root coordinator + 6 specialist agents
  prompts.py                agent instructions
  optimizer.py              OR-Tools VRPTW: multi-temp capacity, windows, HOS, pinning
  planning.py               rows to model, recent-first learned dwell, TMW static baseline
  geo.py                    travel matrix (offline, PC*MILER or Maps Routes API), traffic/weather
  pcmiler.py                Trimble PC*MILER mileage: live API or labelled offline emulation
  geofence.py               geofence engine: visits, dwell, stop detection, learned locations
  otd.py                    Retail and Restaurant on-time delivery policies
  tools/                    ADK function tools (data, planning, events, location, TMW, comms, analytics)
  db/schema.py              one schema for SQLite / BigQuery / AlloyDB (23 tables)
  db/repository.py          data access for the three backends
  event_bus.py              Pub/Sub publisher and worker
server.py                   FastAPI server (ADK get_fast_api_app), as in the sdd-adk codelab
tools.yaml                  MCP Toolbox for Databases: read-only AlloyDB / BigQuery tools and toolsets
data/                       synthetic data generator, CSVs, DDL, BigQuery and AlloyDB loaders
deployment/                 Agent Engine, Cloud Run, Gemini Enterprise, Pub/Sub scripts
docs/SOLUTION.md            architecture, optimization model, workflow, 5-min demo, risks
docs/plans/                 PRDs and design notes (YYYY-MM-DD-topic.md)
antigravity/PROMPTS.md      copy-paste prompts for Google Antigravity (incl. spec-kit flow)
antigravity/mcp_config.json ADK Docs MCP + MCP Toolbox servers for Antigravity
.agents/                    Antigravity rules, skills and workflows (incl. /speckit.* commands)
.specify/                   spec-kit constitution, templates and scripts
specs/00x-*/                spec-kit spec, plan, data model, research, tasks per feature
tests/                      38 offline tests incl. a scripted end-to-end agent run
```

### Agents

| Agent | Does |
|---|---|
| `mclane_route_coordinator` | Routes each request to the right specialist |
| `route_planner_agent` | Demand and fleet checks, optimized plan versus TMW static, what-ifs, route detail |
| `disruption_agent` | Events: trigger, assess, re-plan affected routes only, explain, approve; traffic and weather risk |
| `tms_dispatch_agent` | TMW movement, leg header and stops payloads with PC*MILER miles; submit with confirmation |
| `customer_comms_agent` | ETA notices (EDI 214 or SMS) with confirmation |
| `location_intelligence_agent` | Truck positions, geofence arrivals and dwell, dwell changes, geocode checks, TMW master-data fixes |
| `analytics_agent` | Retail and Restaurant OTD, unload-time gaps, savings history, network roll-up, BigQuery NL2SQL, Toolbox SQL |

## Quick start (offline, about 5 minutes)

Same flow as the Antigravity codelabs: `uv sync`, then `uv run`.

```bash
git clone https://github.com/balum211/mclane-route-optimization-agent && cd mclane-route-optimization-agent
uv sync                                          # or: python -m venv .venv && pip install -r requirements.txt pytest
uv run python data/generate_synthetic_data.py    # CSVs + SQLite + rendered DDL
uv run pytest -q                                 # 38 tests, no cloud needed
uv run python scripts/demo_run.py                # KPIs, disruptions, geofence, dwell change, geocodes, OTD
```

### Talk to the agent

```bash
cp .env.example route_optimizer/.env      # set GOOGLE_CLOUD_PROJECT; keep DB_BACKEND=sqlite to start
gcloud auth application-default login
uv run adk web .                          # open http://localhost:8000 and pick route_optimizer
# or the codelab-style server: uv run uvicorn server:app --host 0.0.0.0 --port 8080
```

Try these prompts:
1. "Which DCs and dates can you plan?"
2. "Build the optimized plan for DC-TEMPLE-TX on 2026-10-27 and compare it with the TMW static routes, in PC*MILER miles."
3. "Where are the Phoenix trucks at 10:30 on 2026-10-27? Is anyone stuck at a dock?"
4. "Handle the dwell overrun and tell me which restaurants need a new ETA."
5. "Which Temple customers changed dwell time in the last two weeks? What should their TMW standard be?"
6. "Which customers have bad geocodes in Phoenix?"
7. "Compare Retail and Restaurant OTD for the network over the last 60 days."
8. "The tractor on route `<route id>` broke down at 07:40. What do we do?"
9. "Preview the TMW update for that change, then notify the affected stores."

## Cloud setup

| Step | Command |
|---|---|
| BigQuery data | `uv run python data/load_bigquery.py --project $GOOGLE_CLOUD_PROJECT --replace`, then `DB_BACKEND=bigquery` |
| AlloyDB data | Set `ALLOYDB_INSTANCE_URI` (or `PG_HOST`), `PG_USER`, `PG_PASSWORD`, run `uv run python data/load_alloydb.py --replace`, then `DB_BACKEND=alloydb` |
| Agent Engine | `bash deployment/deploy_agent_engine.sh` |
| Gemini Enterprise | `GE_APP_ID=… REASONING_ENGINE=projects/…/reasoningEngines/… bash deployment/register_gemini_enterprise.sh`, or in the console: Agents > Add agent > Custom agent via Agent Runtime |
| Cloud Run + UI (alternative) | `bash deployment/deploy_cloud_run.sh` |
| Pub/Sub events | `bash deployment/setup_pubsub.sh`, then `uv run python -m route_optimizer.event_bus worker`, then publish `scripts/sample_events/*.json` |
| PC*MILER | `PCMILER_API_KEY` (optional `PCMILER_ROUTING_TYPE`, `PCMILER_BASE_URL`); `TRAVEL_PROVIDER=pcmiler` to use it for the matrix too |
| Real road times | `TRAVEL_PROVIDER=google_routes` + `GOOGLE_MAPS_API_KEY` |
| MCP Toolbox SQL tools | `toolbox --tools-file tools.yaml`, `uv sync --extra toolbox`, `TOOLBOX_URL=http://127.0.0.1:5000` |
| Live TMW | `TMW_API_BASE_URL`, `TMW_API_TOKEN` (otherwise messages queue in `tmw_dispatch_queue`) |

All settings are documented in [`.env.example`](.env.example).

## Guardrails

* Hard constraints are enforced by the solver, never by a prompt: capacity in cases, cold cases, weight and cube; temperature zones; HOS (11 h drive, 14 h duty); maximum route duration; dock appointments; liftgate and vehicle length; and product pinned to its truck during re-plans.
* Escalation to a dispatcher happens when an SLA breach is unavoidable, an order cannot be delivered, the cost impact exceeds $750, or a reefer alert is involved.
* TMW submission, customer messages, re-plan approvals and master-data updates are ADK tools with `require_confirmation=True`.
* Offline PC*MILER miles are always labelled `PCMILER_EMULATED`, so nobody mistakes them for licensed PC*MILER output.
* Audit tables: `optimization_runs`, `event_actions`, `replan_approvals`, `geofence_events`, `master_data_updates`, `tmw_dispatch_queue`, `customer_notifications`.

## Building with Google Antigravity

The repo follows the layout of the [sdd-adk-antigravity starter](https://github.com/alphinside/sdd-adk-antigravity-starter): agent package with its own `.env`, `uv sync` / `uv run adk web .`, `server.py`, `tools.yaml`, `.agents/` and `.specify/`.

* `AGENTS.md` and `.agents/rules/project-context.md` load as always-on context.
* `.agents/skills/` (each a folder with `SKILL.md` frontmatter): route-optimizer-solver, location-intelligence, pcmiler-mileage, synthetic-scm-data, adk-tool-builder, schema-validator, tmw-integration, gcp-deploy, mcp-toolbox-alloydb, repo-research.
* `.agents/workflows/`: `/speckit.constitution`, `/speckit.specify`, `/speckit.clarify`, `/speckit.plan`, `/speckit.tasks`, `/speckit.analyze`, `/speckit.implement`, `/speckit.checklist`, plus `/demo-run`, `/add-event-type` and `/daily-ops-review`.
* `antigravity/mcp_config.json` adds the ADK Docs MCP server (`mcpdoc` over `https://adk.dev/llms.txt`) and the MCP Toolbox server. Merge it into `~/.gemini/config/mcp_config.json` (or Settings > Customizations > Open MCP Config).

Paste-ready prompts for setup, the spec-kit flow and new features are in [`antigravity/PROMPTS.md`](antigravity/PROMPTS.md). See [`docs/SOLUTION.md`](docs/SOLUTION.md) for the full design and the 5-minute demo script.

Third-party files (spec-kit workflows and templates, codelab skills) are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
