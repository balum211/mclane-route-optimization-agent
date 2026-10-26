---
description: Regenerate data, run tests and the offline 5-minute demo, and summarize KPIs as an artifact
---

1. Run `python data/generate_synthetic_data.py` and confirm the row counts.
2. Run `python .agents/skills/schema-validator/scripts/validate_schema.py`. Stop if it fails.
3. Run `python -m pytest -q`. Stop and report if anything fails.
4. Run `python scripts/demo_run.py --time-limit 15`.
5. Create an artifact "Demo KPIs" with: the network before/after table (trucks, miles, cost, on-time %),
   the breakdown re-plan (what changed, KPIs, latency, approval) and the reefer re-plan. Use the exact numbers.
6. If `GOOGLE_CLOUD_PROJECT` is set in `route_optimizer/.env`, start `adk web .` and run the 6 prompts
   in docs/SOLUTION.md §4, taking a screenshot after each answer.
