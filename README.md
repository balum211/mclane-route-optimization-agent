# McLane Dynamic Route Optimization Agent

A Google ADK multi-agent system that builds McLane's daily delivery routes and re-plans them in real time when trucks break down, run late, orders change or roads close. Google OR-Tools does the optimization, Gemini orchestrates and explains, and Trimble TMW stays the TMS of record. Data runs on BigQuery or AlloyDB, or offline on SQLite for demos. It deploys to Vertex AI Agent Engine and surfaces in Gemini Enterprise.

> Hackathon use case 1 of 3 (Google hackathon, Oct 27-28 2026). All data is synthetic and every company and person name is fictional.

**Results on the synthetic network** (4 DCs, 2026-10-27, `python scripts/demo_run.py`):

| | TMW static routes | AI optimized | Change |
|---|---|---|---|
| Trucks | 47 | 45 | −2 |
| Miles | 5,240 | 4,582 | −12.6% |
| Cost | $34,313 | $26,321 | **−23.3% ($7,992/day)** |
| On-time stops | 88.0% | 100% | +12 pts |
| Event re-plan latency | | 2 to 8 s | target < 30 s |

## What's inside

```
route_optimizer/            ADK agent package (what `adk web` / `adk deploy` load)
  agent.py                  root coordinator + 5 specialist agents
  prompts.py                agent instructions
  optimizer.py              OR-Tools VRPTW: multi-temp capacity, windows, HOS, pinning
  planning.py               rows to model, learned unload times, TMW static baseline
  geo.py                    travel model, traffic/weather, optional Maps Routes API
  tools/                    ADK function tools (data, planning, events, TMW, comms, analytics)
  db/schema.py              one schema for SQLite / BigQuery / AlloyDB
  db/repository.py          data access for the three backends
  event_bus.py              Pub/Sub publisher and worker
data/                       synthetic data generator, CSVs, DDL, BigQuery and AlloyDB loaders
deployment/                 Agent Engine, Cloud Run, Gemini Enterprise, Pub/Sub scripts
docs/SOLUTION.md            architecture, optimization model, workflow, 5-min demo, risks
antigravity/PROMPTS.md      copy-paste prompts for Google Antigravity (incl. spec-kit flow)
.agents/                    Antigravity rules, skills and workflows
specs/001-*/                spec-kit spec, plan, data model, research, tasks
tests/                      26 offline tests incl. a scripted end-to-end agent run
```

### Agents

| Agent | Does |
|---|---|
| `mclane_route_coordinator` | Routes each request to the right specialist |
| `route_planner_agent` | Demand and fleet checks, optimized plan versus TMW static, what-ifs, route detail |
| `disruption_agent` | Events: trigger, assess, re-plan affected routes only, explain, approve; traffic and weather risk |
| `tms_dispatch_agent` | TMW movement, leg header and stops payloads; submit with confirmation |
| `customer_comms_agent` | ETA notices (EDI 214 or SMS) with confirmation |
| `analytics_agent` | On-time %, unload-time gaps, savings history, network roll-up, BigQuery NL2SQL |

## Quick start (offline, about 5 minutes)

```bash
git clone https://github.com/balum211/mclane-route-optimization-agent && cd mclane-route-optimization-agent
uv sync                                   # or: python -m venv .venv && pip install -r requirements.txt pytest
python data/generate_synthetic_data.py    # CSVs + SQLite + rendered DDL
python -m pytest -q                       # 26 tests, no cloud needed
python scripts/demo_run.py                # before/after KPIs + breakdown + reefer re-plans
```

### Talk to the agent

```bash
cp .env.example route_optimizer/.env      # set GOOGLE_CLOUD_PROJECT; keep DB_BACKEND=sqlite to start
gcloud auth application-default login
adk web .                                 # open http://localhost:8000 and pick route_optimizer
```

Try these prompts:
1. "Which DCs and dates can you plan?"
2. "Build the optimized plan for DC-TEMPLE-TX on 2026-10-27 and compare it with the TMW static routes."
3. "Run the what-if scenarios for Phoenix on 2026-10-27."
4. "Show today's events for DC-DALLAS-TX on 2026-10-27 and handle the reefer alert."
5. "The tractor on route `<route id>` broke down at 07:40. What do we do?"
6. "Preview the TMW update for that change, then notify the affected stores."

## Cloud setup

| Step | Command |
|---|---|
| BigQuery data | `python data/load_bigquery.py --project $GOOGLE_CLOUD_PROJECT --replace`, then `DB_BACKEND=bigquery` |
| AlloyDB data | Set `ALLOYDB_INSTANCE_URI` (or `PG_HOST`), `PG_USER`, `PG_PASSWORD`, run `python data/load_alloydb.py --replace`, then `DB_BACKEND=alloydb` |
| Agent Engine | `bash deployment/deploy_agent_engine.sh` |
| Gemini Enterprise | `GE_APP_ID=… REASONING_ENGINE=projects/…/reasoningEngines/… bash deployment/register_gemini_enterprise.sh`, or in the console: Agents > Add agent > Custom agent via Agent Runtime |
| Cloud Run + UI (alternative) | `bash deployment/deploy_cloud_run.sh` |
| Pub/Sub events | `bash deployment/setup_pubsub.sh`, then `python -m route_optimizer.event_bus worker`, then publish `scripts/sample_events/*.json` |
| Real road times | `TRAVEL_PROVIDER=google_routes` + `GOOGLE_MAPS_API_KEY` |
| Live TMW | `TMW_API_BASE_URL`, `TMW_API_TOKEN` (otherwise messages queue in `tmw_dispatch_queue`) |

All settings are documented in [`.env.example`](.env.example).

## Guardrails

* Hard constraints are enforced by the solver, never by a prompt: capacity in cases, cold cases, weight and cube; temperature zones; HOS (11 h drive, 14 h duty); maximum route duration; dock appointments; liftgate and vehicle length; and product pinned to its truck during re-plans.
* Escalation to a dispatcher happens when an SLA breach is unavoidable, an order cannot be delivered, the cost impact exceeds $750, or a reefer alert is involved.
* TMW submission, customer messages and re-plan approvals are ADK tools with `require_confirmation=True`.
* Audit tables: `optimization_runs`, `event_actions`, `replan_approvals`, `tmw_dispatch_queue`, `customer_notifications`.

## Building with Google Antigravity

Open the repo in Antigravity. `AGENTS.md`, `.agents/rules`, `.agents/skills` (solver, synthetic data, ADK tools, schema validator, TMW integration, GCP deploy) and `.agents/workflows` (`/demo-run`, `/add-event-type`) load automatically. Paste-ready prompts for setup, the spec-kit flow (`specify init --here --integration agy`) and new features are in [`antigravity/PROMPTS.md`](antigravity/PROMPTS.md).

See [`docs/SOLUTION.md`](docs/SOLUTION.md) for the full design and the 5-minute demo script.
