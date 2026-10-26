# AGENTS.md: rules for AI coding agents (Google Antigravity, Gemini CLI, others)

## What this repo is
A Google ADK multi-agent system that plans and re-plans McLane delivery routes.
OR-Tools does the optimization, Gemini explains and orchestrates, and Trimble TMW is the TMS of record.
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
- Style: 2-space indentation, type hints, Google-style docstrings (ADK turns docstrings into tool
  descriptions, so write them for the model).
- Save plans and design docs to `docs/plans/YYYY-MM-DD-<topic>.md`.
- Never commit `.env`, credentials or the generated `data/mclane_routing.db`.

## Commands
```bash
uv sync                      # or: pip install -r requirements.txt pytest
python data/generate_synthetic_data.py
python -m pytest -q
adk web .                    # dev UI, pick route_optimizer
python scripts/demo_run.py   # offline before/after KPIs + disruption demo
```
