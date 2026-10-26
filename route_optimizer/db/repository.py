"""Data access for SQLite (local demo), BigQuery and AlloyDB for PostgreSQL.

All agent tools speak to one small interface:

  repo.query(sql, params)   -> list[dict]   (named parameters as ``:name``)
  repo.insert(table, rows)  -> None

Queries use unqualified table names. BigQuery resolves them through the job's
default dataset and PostgreSQL through ``search_path``, so the same SQL text
runs everywhere. Keep SQL portable: plain SELECT / WHERE / GROUP BY, no
engine-specific date functions.
"""

from __future__ import annotations

import datetime as dt
import decimal
import functools
import json
import re
import sqlite3
import threading
from typing import Any, Iterable, Mapping, Protocol

from ..config import Settings, get_settings
from .schema import TABLES_BY_NAME

_PARAM = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


def _normalize(value: Any) -> Any:
  if isinstance(value, (dt.datetime, dt.date)):
    return value.isoformat()
  if isinstance(value, decimal.Decimal):
    return float(value)
  return value


def _row(d: Mapping) -> dict:
  return {k: _normalize(v) for k, v in d.items()}


class Repository(Protocol):
  backend: str

  def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]: ...

  def insert(self, table: str, rows: Iterable[Mapping[str, Any]]) -> None: ...


class SQLiteRepository:
  backend = "sqlite"

  def __init__(self, path: str):
    self._path = path
    self._lock = threading.Lock()
    self._con = sqlite3.connect(path, check_same_thread=False)
    self._con.row_factory = sqlite3.Row

  def query(self, sql, params=None):
    params = {k: _normalize(v) for k, v in (params or {}).items()}
    with self._lock:
      return [_row(dict(r)) for r in self._con.execute(sql, params).fetchall()]

  def insert(self, table, rows):
    rows = list(rows)
    if not rows:
      return
    cols = TABLES_BY_NAME[table].column_names
    values = [
        [json.dumps(r.get(c)) if isinstance(r.get(c), (dict, list)) else _normalize(r.get(c)) for c in cols]
        for r in rows
    ]
    with self._lock:
      self._con.executemany(
          f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", values
      )
      self._con.commit()


class BigQueryRepository:
  backend = "bigquery"

  def __init__(self, project: str, dataset: str, location: str):
    from google.cloud import bigquery

    self._bq = bigquery
    self._client = bigquery.Client(project=project or None, location=location)
    self._dataset = f"{self._client.project}.{dataset}"

  def _param(self, name: str, value: Any):
    bq = self._bq
    if isinstance(value, bool):
      return bq.ScalarQueryParameter(name, "BOOL", value)
    if isinstance(value, int):
      return bq.ScalarQueryParameter(name, "INT64", value)
    if isinstance(value, float):
      return bq.ScalarQueryParameter(name, "FLOAT64", value)
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
      return bq.ScalarQueryParameter(name, "DATE", value)
    if isinstance(value, (list, tuple)):
      return bq.ArrayQueryParameter(name, "STRING", [str(v) for v in value])
    return bq.ScalarQueryParameter(name, "STRING", None if value is None else str(value))

  def query(self, sql, params=None):
    params = dict(params or {})
    bq_sql = _PARAM.sub(lambda m: f"@{m.group(1)}", sql)
    cfg = self._bq.QueryJobConfig(
        default_dataset=self._dataset,
        query_parameters=[self._param(k, v) for k, v in params.items()],
        labels={"app": "mclane-route-optimizer"},
    )
    return [_row(dict(r.items())) for r in self._client.query(bq_sql, job_config=cfg).result()]

  def insert(self, table, rows):
    rows = [
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else _normalize(v)) for k, v in r.items()}
        for r in rows
    ]
    if not rows:
      return
    errors = self._client.insert_rows_json(f"{self._dataset}.{table}", rows)
    if errors:
      raise RuntimeError(f"BigQuery insert into {table} failed: {errors[:3]}")


class AlloyDBRepository:
  """AlloyDB (or any PostgreSQL) through SQLAlchemy + pg8000."""

  backend = "alloydb"

  def __init__(self, s: Settings):
    import sqlalchemy

    self._sa = sqlalchemy
    if s.alloydb_instance_uri:
      from google.cloud.alloydbconnector import Connector, IPTypes

      connector = Connector()

      def getconn():
        return connector.connect(
            s.alloydb_instance_uri,
            "pg8000",
            user=s.pg_user,
            password=s.pg_password,
            db=s.pg_database,
            ip_type=getattr(IPTypes, s.alloydb_ip_type.upper(), IPTypes.PUBLIC),
        )

      self._engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn, pool_pre_ping=True)
    else:
      url = sqlalchemy.engine.URL.create(
          "postgresql+pg8000",
          username=s.pg_user,
          password=s.pg_password,
          host=s.pg_host or "127.0.0.1",
          port=s.pg_port,
          database=s.pg_database,
      )
      self._engine = sqlalchemy.create_engine(url, pool_pre_ping=True)
    self._schema = s.pg_schema

    @sqlalchemy.event.listens_for(self._engine, "connect")
    def _set_search_path(dbapi_conn, _):
      # Run outside a transaction so the pool's reset-on-return rollback
      # doesn't undo it.
      dbapi_conn.autocommit = True
      cur = dbapi_conn.cursor()
      cur.execute(f"SET search_path TO {self._schema}, public")
      cur.close()
      dbapi_conn.autocommit = False

  def query(self, sql, params=None):
    with self._engine.connect() as con:
      res = con.execute(self._sa.text(sql), dict(params or {}))
      return [_row(dict(r._mapping)) for r in res]

  def insert(self, table, rows):
    rows = [
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()} for r in rows
    ]
    if not rows:
      return
    cols = TABLES_BY_NAME[table].column_names
    stmt = self._sa.text(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    )
    with self._engine.begin() as con:
      con.execute(stmt, [{c: r.get(c) for c in cols} for r in rows])


@functools.lru_cache(maxsize=1)
def get_repository() -> Repository:
  s = get_settings()
  if s.db_backend == "bigquery":
    return BigQueryRepository(s.bq_project, s.bq_dataset, s.bq_location)
  if s.db_backend in ("alloydb", "postgres"):
    return AlloyDBRepository(s)
  return SQLiteRepository(s.sqlite_path)
