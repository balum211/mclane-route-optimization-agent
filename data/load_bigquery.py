"""Loads the synthetic dataset into BigQuery.

Creates the dataset and every table (with column descriptions, which Gemini
uses for NL2SQL) and loads the CSVs from data/synthetic.

Usage:
  gcloud auth application-default login
  python data/load_bigquery.py --project YOUR_PROJECT [--dataset mclane_routing] [--location US]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from route_optimizer.db.schema import TABLES, render_ddl  # noqa: E402


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--project", required=True)
  ap.add_argument("--dataset", default="mclane_routing")
  ap.add_argument("--location", default="US")
  ap.add_argument("--csv-dir", default=str(ROOT / "data" / "synthetic"))
  ap.add_argument("--replace", action="store_true", help="Drop and recreate tables first")
  args = ap.parse_args(argv)

  from google.cloud import bigquery

  client = bigquery.Client(project=args.project, location=args.location)
  ds = bigquery.Dataset(f"{args.project}.{args.dataset}")
  ds.location = args.location
  ds.description = "Synthetic McLane SCM logistics data for dynamic route optimization (hackathon)."
  client.create_dataset(ds, exists_ok=True)

  if args.replace:
    for t in TABLES:
      client.delete_table(f"{args.project}.{args.dataset}.{t.name}", not_found_ok=True)

  ddl = render_ddl("bigquery", f"{args.project}.{args.dataset}.")
  for stmt in [s for s in ddl.split(";\n") if s.strip()]:
    client.query(stmt).result()
  print(f"Created {len(TABLES)} tables in {args.project}.{args.dataset}")

  for t in TABLES:
    path = Path(args.csv_dir) / f"{t.name}.csv"
    if not path.exists() or path.stat().st_size == 0:
      continue
    table = client.get_table(f"{args.project}.{args.dataset}.{t.name}")
    cfg = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=table.schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_quoted_newlines=True,
    )
    with path.open("rb") as f:
      job = client.load_table_from_file(f, table, job_config=cfg)
    job.result()
    print(f"  {t.name:<24}{client.get_table(table).num_rows:>8,} rows")


if __name__ == "__main__":
  main()
