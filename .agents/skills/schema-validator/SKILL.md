---
name: schema-validator
description: Use after editing route_optimizer/db/schema.py, the data generator or rendered SQL, to validate naming, keys, descriptions and that CSVs and DDL match the schema.
---

# Schema validator

## Goal
Catch schema drift before it breaks BigQuery or AlloyDB loads or confuses NL2SQL.

## Instructions
Run `python .agents/skills/schema-validator/scripts/validate_schema.py`.
Exit code 0 means pass; 1 prints every violation. Fix the schema or regenerate data, then re-run.

## Policies enforced
- Table and column names are `snake_case`.
- Every table has a primary key, and every PK column is marked required.
- Every table and column has a description of 3 or more characters.
- Time-of-day columns end in `_min` and are INT.
- Every `data/synthetic/<table>.csv` header equals the schema's columns, in order.
- Rendered `data/schema/*.sql` is up to date with `schema.py`.
- No `DROP TABLE` in rendered SQL.

## Constraints
Do not silence a check; fix the cause.
