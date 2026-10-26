"""Validates route_optimizer/db/schema.py against repo policies. Exit 0 = pass, 1 = fail."""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from route_optimizer.db.schema import TABLES, render_ddl  # noqa: E402

SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def main() -> int:
  errors = []
  for t in TABLES:
    if not SNAKE.match(t.name):
      errors.append(f"{t.name}: table name not snake_case")
    if len(t.description) < 3:
      errors.append(f"{t.name}: missing table description")
    if not t.primary_key:
      errors.append(f"{t.name}: no primary key")
    cols = {c.name: c for c in t.columns}
    for pk in t.primary_key:
      if pk not in cols:
        errors.append(f"{t.name}: PK column {pk} not defined")
      elif not cols[pk].required:
        errors.append(f"{t.name}.{pk}: PK column must be required")
    for c in t.columns:
      if not SNAKE.match(c.name):
        errors.append(f"{t.name}.{c.name}: column not snake_case")
      if len(c.description) < 3:
        errors.append(f"{t.name}.{c.name}: missing description")
      if c.name.endswith("_min") and c.type != "INT":
        errors.append(f"{t.name}.{c.name}: *_min columns must be INT")
    path = ROOT / "data" / "synthetic" / f"{t.name}.csv"
    if path.exists():
      with path.open() as f:
        header = next(csv.reader(f), [])
      if header != t.column_names:
        errors.append(f"{path.name}: header does not match schema (regenerate data)")
  rendered = {
      "sqlite.sql": render_ddl("sqlite"),
      "alloydb.sql": render_ddl("postgres"),
      "bigquery.sql": render_ddl("bigquery", "YOUR_PROJECT.mclane_routing."),
  }
  for name, ddl in rendered.items():
    path = ROOT / "data" / "schema" / name
    if not path.exists() or ddl not in path.read_text():
      errors.append(f"data/schema/{name} is stale: run python data/generate_synthetic_data.py")
    elif "DROP TABLE" in path.read_text().upper():
      errors.append(f"data/schema/{name}: DROP TABLE is not allowed")
  for e in errors:
    print("FAIL", e)
  print("schema OK" if not errors else f"{len(errors)} problem(s)")
  return 1 if errors else 0


if __name__ == "__main__":
  sys.exit(main())
