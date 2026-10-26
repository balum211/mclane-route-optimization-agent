# Implementation Plan: Dynamic Route Optimization

**Branch**: `001-dynamic-route-optimization` | **Spec**: [spec.md](spec.md)

## Technical context
- **Language**: Python 3.11+ (tested on 3.13)
- **Agents**: Google ADK `LlmAgent` coordinator with 5 `sub_agents` (LLM-driven delegation via `transfer_to_agent`)
- **Model**: Gemini on Vertex AI (`gemini-3.5-flash` default; override per role with `COORDINATOR_MODEL` and `SPECIALIST_MODEL`)
- **Solver**: OR-Tools routing (`pywrapcp`), PARALLEL_CHEAPEST_INSERTION then GUIDED_LOCAL_SEARCH
- **Storage**: SQLite (demo) / BigQuery (`google-cloud-bigquery`, default dataset) / AlloyDB (SQLAlchemy + pg8000 + AlloyDB Python Connector)
- **Events**: Pub/Sub (`google-cloud-pubsub`)
- **Testing**: pytest, offline; a scripted `BaseLlm` drives an end-to-end ADK run
- **Targets**: Vertex AI Agent Engine (`adk deploy agent_engine`), Cloud Run (`adk deploy cloud_run`), Gemini Enterprise

## Constitution check
| Principle | How the design satisfies it |
|---|---|
| I. Deterministic optimization | All numbers come from `optimizer.solve` and `simulate_route`; prompts forbid unsourced figures |
| II. Hard constraints | Dimensions and vehicle bans in the solver; reefer failure sets cold capacity to 0 |
| III. Human in the loop | `FunctionTool(require_confirmation=True)` for TMW submit, customer send, re-plan decision |
| IV. Minimal disruption | `_handle` re-plans only `lives` (affected routes); pinned stops; latency measured |
| V. One schema | `db/schema.py` renders all DDL; repository uses portable SQL |
| VI. Test-first | 26 offline tests including the agent flow |

## Project structure
```
route_optimizer/            ADK agent package (adk web / adk deploy target)
  agent.py prompts.py config.py geo.py optimizer.py planning.py event_bus.py
  db/schema.py db/repository.py
  tools/{data,planning,disruption,event,tms,comms,analytics}_tools.py
data/                       generator, CSVs, rendered DDL, loaders
deployment/                 Agent Engine, Cloud Run, Gemini Enterprise, Pub/Sub scripts
tests/                      optimizer, tools, agent flow
docs/SOLUTION.md            architecture, model, workflow, demo, risks
antigravity/PROMPTS.md      prompt playbook
.agents/                    Antigravity rules, skills, workflows
```

## Phases
0. Research: solver choice, TMW object model, ADK confirmation and state (see `research.md`)
1. Data model and synthetic generator (see `data-model.md`)
2. Solver and baseline simulator
3. Read and planning tools, then the agent tree
4. Event re-planner, escalation, approvals
5. TMW, comms, analytics tools
6. Backends (BigQuery, AlloyDB), Pub/Sub, deployment
7. Docs, Antigravity assets, demo script
