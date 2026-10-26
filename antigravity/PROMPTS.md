# Google Antigravity prompt playbook: Dynamic Route Optimization

These prompts are ready to paste into Antigravity's agent panel. They follow the codelabs from the hackathon brief (Antigravity basics, Building with Antigravity, spec-driven ADK development with spec-kit, Beyond vibe coding, Antigravity skills). IDE installation steps are left out on purpose.

There are three tracks. Use whichever fits the time you have:

* **Track A, run this repo in about 15 minutes.** Open the repo in Antigravity and let the agent set it up, run it and demo it.
* **Track B, spec-driven rebuild or extension with spec-kit.** Use the spec-kit flow (constitution, specify, clarify, plan, tasks, analyze, implement), with the artifacts already in `specs/001-dynamic-route-optimization/` as the reference answer.
* **Track C, feature prompts** for extending the agent during the hackathon.

The workspace already contains what Antigravity looks for:

| Path | Purpose |
|---|---|
| `AGENTS.md` | Always-on project rules (stack, conventions, "never invent numbers") |
| `.agents/rules/project-context.md` | Repo map and domain glossary (TMW, HOS, multi-temp) |
| `.agents/skills/*/SKILL.md` | Project skills: solver, synthetic data, ADK tools, schema validator, TMW integration, GCP deploy |
| `.agents/workflows/*.md` | `/demo-run`, `/add-event-type` |
| `.specify/memory/constitution.md` | spec-kit constitution |
| `specs/001-dynamic-route-optimization/` | spec, plan, data model, research, tasks |

---

## Track A: run and demo this repo

**A1. Set up**
```
Read AGENTS.md and .agents/rules/project-context.md. Then set up this project:
create a Python 3.12 virtual env with uv, install requirements.txt plus pytest,
generate the synthetic data with data/generate_synthetic_data.py, and run the
test suite. Copy .env.example to route_optimizer/.env, set
GOOGLE_GENAI_USE_VERTEXAI=True and GOOGLE_CLOUD_PROJECT=<my project>, and keep
DB_BACKEND=sqlite for now. Show me the test summary and the row counts the
generator printed.
```

**A2. Offline demo (no Gemini needed)**
```
Run scripts/demo_run.py and turn the output into a short artifact with three
sections: network KPIs before/after (trucks, miles, cost, on-time %), the
breakdown re-plan, and the reefer re-plan. Keep the exact numbers.
```

**A3. Live agent**
```
Start the ADK dev UI with `adk web .` from the repo root (select
route_optimizer), open it in the browser, and run this conversation, taking a
screenshot after each answer:
1. "Which DCs and dates can you plan?"
2. "Build the optimized plan for DC-TEMPLE-TX on 2026-10-27 and compare it with the TMW static routes."
3. "Show route R06 stop by stop."
4. "The tractor on R06 just broke down at 07:40. What do we do?"
5. "Preview the TMW update for that change."
Report anything that looks wrong, such as numbers that don't match tool output.
```

**A4. Move data to BigQuery**
```
Using the gcp-deploy and synthetic-scm-data skills: run data/load_bigquery.py
against project <my project> (dataset mclane_routing, location US), then switch
route_optimizer/.env to DB_BACKEND=bigquery and re-run the Temple optimization
through the agent. Also ask the analytics agent: "Which 5 customers have the
biggest gap between TMS unload time and real unload time?" and confirm it used
the BigQuery execute_sql tool with a read-only SELECT.
```

**A5. Move data to AlloyDB (alternative)**
```
Create an AlloyDB cluster "mclane" and a primary instance in us-central1 with
public IP (hackathon only), a database "mclane", and a password from Secret
Manager. Set ALLOYDB_INSTANCE_URI, PG_USER and PG_PASSWORD in
route_optimizer/.env with DB_BACKEND=alloydb, run data/load_alloydb.py --replace,
and re-run tests/test_tools.py with DB_BACKEND=alloydb. Ask me before creating
billable resources.
```

**A6. Deploy and register in Gemini Enterprise**
```
Follow the gcp-deploy skill: deploy with deployment/deploy_agent_engine.sh
(DB_BACKEND=bigquery), capture the reasoningEngines resource name, then register
it in Gemini Enterprise app <app id> with deployment/register_gemini_enterprise.sh.
Finally create the Pub/Sub topic and subscription with deployment/setup_pubsub.sh
and publish scripts/sample_events/breakdown.json. Ask before each billable step.
```

---

## Track B: spec-driven development with spec-kit

Initialize spec-kit in the workspace once:

```bash
uv tool install specify-cli
specify init --here --integration agy      # agy = Google Antigravity
```

Then run the slash commands in order in the agent panel. Review each artifact in Antigravity's artifact view and comment inline before moving on.

**B1. Constitution**
```
/speckit.constitution This is a hackathon-grade but production-shaped Google ADK
multi-agent system for McLane, a US grocery and foodservice distributor whose TMS
is Trimble TMW. Principles:
1) Deterministic optimization: routes come from OR-Tools, never from the LLM;
   the LLM only explains numbers returned by tools.
2) Hard constraints are sacred: capacity (cases, weight, cube), temperature
   zones, driver hours of service, dock appointments.
3) Human in the loop: any action that changes TMW or messages customers needs
   explicit confirmation; escalate when an SLA breach is unavoidable or cost
   impact exceeds a threshold.
4) One schema, three backends: SQLite for offline demo, BigQuery for analytics,
   AlloyDB for transactional writes.
5) Every tool is unit-tested against synthetic data; re-plans finish in under 30 s.
```

**B2. Specify**
```
/speckit.specify Build "Dynamic Route Optimization" for McLane DCs. A dispatcher
can (a) see tomorrow's demand and fleet for a DC, (b) get an optimized plan that
assigns orders to trucks and sequences stops to minimize miles + labor + late
penalties while respecting time windows, multi-temp capacity, HOS, liftgate and
vehicle-length limits, (c) compare it with the TMW static routes on trucks,
miles, cost, on-time % and CO2, (d) run what-ifs (fewer trucks, wider windows),
(e) react to live events (delay > 15 min, breakdown, added/cancelled order,
road closure, no-show, reefer temperature alert) by re-planning only affected
routes, with a plain-language explanation and an approval step when an SLA
breach is unavoidable or cost impact exceeds $750, (f) push approved plans to
Trimble TMW and notify stores and restaurants.
```

**B3. Clarify** (optional)
```
/speckit.clarify
```
Answer from `specs/001-dynamic-route-optimization/spec.md` §Clarifications if you want the same decisions as this repo.

**B4. Plan**
```
/speckit.plan Use Python 3.12 and Google ADK (LlmAgent coordinator with sub_agents
route_planner_agent, disruption_agent, tms_dispatch_agent, customer_comms_agent,
analytics_agent), Gemini on Vertex AI (gemini-3.5-flash default), OR-Tools
routing for VRPTW, a repository layer over SQLite / BigQuery
(google-cloud-bigquery, default_dataset) / AlloyDB (SQLAlchemy + pg8000 +
AlloyDB Python Connector), Pub/Sub for events, FunctionTool(require_confirmation=True)
for TMW dispatch, customer messaging and re-plan approval. Deploy to Vertex AI
Agent Engine with `adk deploy agent_engine` and register in Gemini Enterprise.
Use the ADK docs and the skills in .agents/skills.
```

**B5. Tasks, analyze, implement**
```
/speckit.tasks
```
```
/speckit.analyze
```
```
/speckit.implement
```
After implementation, ask for a fresh-context review, the "two reviewer agents" pattern from the Beyond vibe coding codelab:
```
Send out 2 agents with fresh context: one checks every requirement in
specs/001-dynamic-route-optimization/spec.md against the code and tests and
lists gaps; the other reviews code quality and correctness of optimizer.py and
tools/event_tools.py. Merge their findings into one prioritized artifact. Do not
fix anything yet.
```

---

## Track C: feature prompts for the hackathon

**C1. Traffic-aware matrix from the Maps Routes API**
```
Use the route-optimizer-solver skill. Enable TRAVEL_PROVIDER=google_routes with
my GOOGLE_MAPS_API_KEY, switch routingPreference to TRAFFIC_AWARE with a
departureTime equal to the planned dispatch time, cache matrices per DC and date
in BigQuery table travel_matrix_cache, and benchmark plan quality and runtime
against the haversine provider with the skill's benchmark script.
```

**C2. Route consistency**
```
Add a soft objective that prefers yesterday's driver and stop order for each
customer (route consistency), weight configurable with ROUTE_CONSISTENCY_WEIGHT.
Add tests that show the weight trades a few miles for higher consistency.
Update docs/SOLUTION.md section 2.
```

**C3. DC dock-door capacity**
```
Model the DC's outbound dock doors: at most dock_doors trucks can load in the
same 30-minute slot before departure. Implement it as a cumulative constraint
in optimizer.py, add a test, and expose the dispatch-wave schedule in
optimize_routes output.
```

**C4. New event type**
```
/add-event-type DRIVER_HOS_WARNING: the ELD reports a driver will run out of
on-duty time in 60 minutes. Re-plan so the remaining stops either fit or move
to a spare unit; always escalate if a stop cannot be served.
```

**C5. Looker / BigQuery dashboard**
```
Write BigQuery views over optimization_runs, event_actions and delivery_history:
daily savings vs TMW static by DC, on-time % trend, events by type with average
re-plan latency and approval rate. Put them in data/schema/views.sql and add a
one-page Looker Studio setup guide to docs/.
```

**C6. Gemini Enterprise agent card**
```
Write the Gemini Enterprise agent description and 6 starter prompts for
dispatchers (plain business language, no ids), and add them to
deployment/register_gemini_enterprise.sh and docs/SOLUTION.md.
```

---

## Hackathon brief prompt, filled in for this repo

This is the use-case 1 prompt from the brief, with the placeholders filled from the synthetic dataset. It works as a design prompt in Gemini or Vertex AI Studio, and as the opening message of an Antigravity planning session.

```
<role>You are a senior logistics optimization engineer for a foodservice and convenience distributor (McLane) operating a private fleet.</role>
<context>- Network: 4 DCs (Temple TX and Concord NC grocery; Dallas TX and Phoenix AZ foodservice), 81 trucks, ~180-250 daily stops (1,256 orders over 7 days).
- Constraints: delivery time windows (dock appointments are hard at mass merchants and tier-1 grocery), truck capacity (cases / weight / cube / temperature zone: dry, chilled, frozen on 3-compartment trailers), driver HOS limits (11 h drive / 14 h duty), liftgate and vehicle-length limits, max route duration 13 hrs.
- Live signals: traffic, weather, road closures, vehicle telematics (GPS, reefer temp), order changes, cancellations, no-shows.
- TMS of record: Trimble TMW; current routes are static territory routes.</context>
<task>Build an agentic system that creates the daily route plan and re-optimizes it in real time when disruptions occur.
1. Initial plan: assign stops to trucks and sequence them to minimize total cost (miles + labor + late penalties) subject to all constraints.
2. Dynamic re-route: on each event (delay >15 min, breakdown, added/cancelled order, closure), re-plan only the affected routes with minimal disruption to unaffected ones.
3. Explain every change in plain language for dispatchers (what changed, why, cost/time impact).
4. Escalate to a human when an SLA breach is unavoidable or a change exceeds $750 cost.</task>
<tools_and_data>Use: Google Maps Routes API (traffic-aware ETAs), Google OR-Tools (solver; Route Optimization API as an alternative), BigQuery or AlloyDB (orders, fleet, history), Pub/Sub (event stream), Gemini via Google ADK on Vertex AI Agent Engine, surfaced in Gemini Enterprise.
Sample data: data/synthetic/*.csv in this repo (schema in route_optimizer/db/schema.py).</tools_and_data>
<requirements>- Deliver: architecture diagram, solver approach, event-handling flow, working demo with 1 disruption scenario.
- Re-optimization latency target: <30 seconds.
- Never violate hard constraints (capacity, HOS, temperature). Treat time windows as soft with penalties unless marked hard.
- State assumptions explicitly; if data is missing, ask or use stated defaults.</requirements>
<output_format>1. Solution architecture (bullets + diagram description)
2. Optimization model: objective, hard/soft constraints
3. Agent workflow: trigger -> assess -> re-plan -> explain -> approve
4. Demo script (5 min) with before/after KPIs: miles, on-time %, cost, trucks used
5. Risks and next steps</output_format>
```

The repo's answer to this prompt is [`docs/SOLUTION.md`](../docs/SOLUTION.md).

---

## Agent instructions (if you rebuild the agents by hand)

The production instructions are in `route_optimizer/prompts.py`: `COORDINATOR`, `ROUTE_PLANNER`, `DISRUPTION`, `TMS_DISPATCH`, `CUSTOMER_COMMS` and `ANALYTICS`, with shared ground rules in `SHARED_CONTEXT`. To build the same agent in a no-code agent designer (for example Gemini Enterprise Agent Designer), paste `COORDINATOR` as the main instruction and each specialist prompt as a sub-agent instruction, and attach the matching tools from the table in `docs/SOLUTION.md` §1.
