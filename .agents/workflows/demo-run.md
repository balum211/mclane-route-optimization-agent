---
description: Regenerate data, run tests and the offline 5-minute demo, and summarize KPIs as an artifact
---

1. Run `uv run python data/generate_synthetic_data.py` and confirm the row counts.
2. Run `uv run python .agents/skills/schema-validator/scripts/validate_schema.py`. Stop if it fails.
3. Run `uv run pytest -q`. Stop and report if anything fails.
4. Run `uv run python scripts/demo_run.py --time-limit 15`.
5. Create an artifact "Demo KPIs" with: the network before/after table (trucks, PC*MILER miles, cost,
   on-time %), planned Retail and Restaurant OTD, the breakdown and reefer re-plans, the Phoenix
   geofence dwell overrun and its re-plan, the Temple dwell changes, the bad geocodes and the 60-day
   Retail versus Restaurant OTD. Use the exact numbers and say that miles are emulated PC*MILER.
6. If `GOOGLE_CLOUD_PROJECT` is set in `route_optimizer/.env`, start `uv run adk web .` and run the
   prompts in docs/SOLUTION.md §4, taking a screenshot after each answer.
