# AGENTS.md: rules for AI coding agents (Google Antigravity, Gemini CLI, others)

## What this repo is
A Google ADK multi-agent system that plans and re-plans McLane delivery routes.
OR-Tools does the optimization, Gemini explains and orchestrates, Trimble TMW is the TMS of record and
Trimble PC*MILER the mileage of record. GPS pings and geofences timestamp arrivals, departures and dwell;
on-time delivery is reported separately for Retail and Restaurant customers.
Read `.agents/rules/project-context.md` for the repo map and domain glossary.

## Ground rules
- **The LLM never computes routes or numbers.** Any figure an agent states must come from a tool
  result. New capabilities go in deterministic tools (`route_optimizer/tools/`), not in prompts.
- **Hard constraints live in the solver** (`route_optimizer/optimizer.py`): capacity (cases, cold
  cases, weight, cube), HOS (span and drive dimensions), dock appointments (`hard_window`), site
  restrictions, product pinned to its truck. Never move a hard constraint into a prompt.
- **Human in the loop.** Tools that change TMW, message customers or approve escalations are
  `FunctionTool(..., require_confirmation=True)`.
- **One schema.** Add or change columns only in `route_optimizer/db/schema.py`, then regenerate data
  (`python data/generate_synthetic_data.py`), which also rewrites `data/schema/*.sql`.
- **Portable SQL.** Use named params `:name` and unqualified table names. No engine-specific date
  functions. Pass dates as `datetime.date` (use `as_date`).
- **Tests first.** `python -m pytest -q` must pass. It runs offline on SQLite with no Gemini calls.
  Add a test for every new tool or event type.
- **Latency.** Event re-plans must finish under 30 s. Keep solver time limits in config.
- **Mileage of record is PC*MILER.** Anything saved or sent to TMW carries `pcmiler_miles` from
  `route_optimizer/pcmiler.py`. Offline output is labelled `PCMILER_EMULATED`; never present it as
  real PC*MILER output.
- **OTD has two definitions.** Retail by receiving-window close, Restaurant by scheduled time ±30 min
  and inside the window. Both live only in `route_optimizer/otd.py` and the `otd_policies` table.
- **Geofence facts come from tools.** Arrivals, departures and dwell come from `geofence.py` and
  `location_tools.py`, never from prompt reasoning. Master-data fixes go through
  `apply_master_data_updates` (confirmation required) and are insert-only.
- Style: 2-space indentation, type hints, Google-style docstrings (ADK turns docstrings into tool
  descriptions, so write them for the model).
- Save plans and design docs to `docs/plans/YYYY-MM-DD-<topic>.md`.
- Never commit `.env`, credentials or the generated `data/mclane_routing.db`.

- Use spec-kit for new features: `/speckit.specify`, `/speckit.plan`, `/speckit.tasks`,
  `/speckit.implement` (workflows in `.agents/workflows/`), artifacts in `specs/<NNN-feature>/`.
- When asked to ask questions, use the ask_question tool.

## Commands
```bash
uv sync                                   # or: pip install -r requirements.txt pytest
uv run python data/generate_synthetic_data.py
uv run pytest -q
uv run adk web .                          # dev UI, pick route_optimizer
uv run uvicorn server:app --port 8080     # FastAPI server with the ADK endpoints
uv run python scripts/demo_run.py         # offline KPIs, disruptions, geofence, dwell, geocodes, OTD
toolbox --tools-file tools.yaml           # optional MCP Toolbox (read-only SQL tools)
```
