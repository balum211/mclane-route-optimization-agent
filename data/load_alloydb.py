"""Loads the synthetic dataset into AlloyDB for PostgreSQL (or any PostgreSQL).

Connection settings come from the same environment variables the agent uses
(see .env.example): either ALLOYDB_INSTANCE_URI for the AlloyDB Python
Connector, or PG_HOST/PG_PORT for the AlloyDB Auth Proxy or a local Postgres.

Usage:
  python data/load_alloydb.py            # create schema + tables and load CSVs
  python data/load_alloydb.py --replace  # drop the schema first
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from route_optimizer.config import get_settings  # noqa: E402
from route_optimizer.db.schema import TABLES, render_ddl  # noqa: E402


def _coerce(value: str, type_: str):
  if value == "":
    return None
  if type_ == "INT":
    return int(float(value))
  if type_ == "FLOAT":
    return float(value)
  if type_ == "BOOL":
    return value.lower() in {"true", "1", "t"}
  if type_ == "JSON":
    return json.dumps(json.loads(value))
  return value


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--csv-dir", default=str(ROOT / "data" / "synthetic"))
  ap.add_argument("--replace", action="store_true")
  args = ap.parse_args(argv)

  import sqlalchemy

  from route_optimizer.db.repository import AlloyDBRepository

  s = get_settings()
  repo = AlloyDBRepository(s)
  engine = repo._engine  # noqa: SLF001 - loader shares the agent's connection setup
  with engine.begin() as con:
    if args.replace:
      con.execute(sqlalchemy.text(f"DROP SCHEMA IF EXISTS {s.pg_schema} CASCADE"))
    con.execute(sqlalchemy.text(f"CREATE SCHEMA IF NOT EXISTS {s.pg_schema}"))
    con.execute(sqlalchemy.text(f"SET search_path TO {s.pg_schema}"))
    for stmt in [x for x in render_ddl("postgres").split(";\n") if x.strip()]:
      con.execute(sqlalchemy.text(stmt))
  print(f"Schema {s.pg_schema} ready")

  for t in TABLES:
    path = Path(args.csv_dir) / f"{t.name}.csv"
    if not path.exists():
      continue
    types = {c.name: c.type for c in t.columns}
    with path.open() as f:
      rows = [{k: _coerce(v, types[k]) for k, v in r.items()} for r in csv.DictReader(f)]
    if not rows:
      continue
    with engine.begin() as con:
      con.execute(sqlalchemy.text(f"TRUNCATE {t.name}"))
    for i in range(0, len(rows), 2000):
      repo.insert(t.name, rows[i : i + 2000])
    print(f"  {t.name:<24}{len(rows):>8,} rows")


if __name__ == "__main__":
  main()
