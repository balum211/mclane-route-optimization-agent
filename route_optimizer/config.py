"""Runtime configuration, read from environment variables (or ``.env``)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent


def _env(name: str, default: str = "") -> str:
  return os.getenv(name, default).strip()


def _default_sqlite() -> str:
  # A copy bundled inside the package (see deployment/deploy_agent_engine.sh)
  # wins, so a demo deployment works without a cloud database.
  bundled = PACKAGE_DIR / "mclane_routing.db"
  return str(bundled if bundled.exists() else REPO_ROOT / "data" / "mclane_routing.db")


@dataclass(frozen=True)
class Settings:
  # Models. Planner/coordinator benefit from a stronger reasoning model; the
  # narrow specialists run fine on Flash.
  coordinator_model: str = field(default_factory=lambda: _env("COORDINATOR_MODEL", _env("GEMINI_MODEL", "gemini-3.5-flash")))
  specialist_model: str = field(default_factory=lambda: _env("SPECIALIST_MODEL", _env("GEMINI_MODEL", "gemini-3.5-flash")))

  # Data backend: sqlite (local demo) | bigquery | alloydb
  db_backend: str = field(default_factory=lambda: _env("DB_BACKEND", "sqlite").lower())
  sqlite_path: str = field(default_factory=lambda: _env("SQLITE_PATH", _default_sqlite()))

  bq_project: str = field(default_factory=lambda: _env("BQ_PROJECT", _env("GOOGLE_CLOUD_PROJECT")))
  bq_dataset: str = field(default_factory=lambda: _env("BQ_DATASET", "mclane_routing"))
  bq_location: str = field(default_factory=lambda: _env("BQ_LOCATION", "US"))

  # AlloyDB: either the instance URI (uses the AlloyDB Python Connector) or a
  # host/port pair (AlloyDB Auth Proxy, or any PostgreSQL for local testing).
  alloydb_instance_uri: str = field(default_factory=lambda: _env("ALLOYDB_INSTANCE_URI"))
  alloydb_ip_type: str = field(default_factory=lambda: _env("ALLOYDB_IP_TYPE", "PUBLIC"))
  pg_host: str = field(default_factory=lambda: _env("PG_HOST"))
  pg_port: int = field(default_factory=lambda: int(_env("PG_PORT", "5432")))
  pg_database: str = field(default_factory=lambda: _env("PG_DATABASE", "mclane"))
  pg_user: str = field(default_factory=lambda: _env("PG_USER", "postgres"))
  pg_password: str = field(default_factory=lambda: _env("PG_PASSWORD"))
  pg_schema: str = field(default_factory=lambda: _env("PG_SCHEMA", "mclane_routing"))

  solver_time_limit_s: int = field(default_factory=lambda: int(_env("SOLVER_TIME_LIMIT_S", "15")))
  max_route_hours: float = field(default_factory=lambda: float(_env("MAX_ROUTE_HOURS", "13")))

  # Event-driven re-planning guardrails (see docs/SOLUTION.md).
  replan_time_limit_s: int = field(default_factory=lambda: int(_env("REPLAN_TIME_LIMIT_S", "8")))
  delay_trigger_min: int = field(default_factory=lambda: int(_env("DELAY_TRIGGER_MIN", "15")))
  escalation_cost_usd: float = field(default_factory=lambda: float(_env("ESCALATION_COST_USD", "750")))
  reefer_max_temp_f: float = field(default_factory=lambda: float(_env("REEFER_MAX_TEMP_F", "10")))
  pubsub_topic: str = field(default_factory=lambda: _env("PUBSUB_TOPIC", "mclane-route-events"))
  pubsub_subscription: str = field(default_factory=lambda: _env("PUBSUB_SUBSCRIPTION", "mclane-route-events-agent"))
  # Trimble PC*MILER (mileage of record). No key = labelled offline emulation.
  pcmiler_api_key: str = field(default_factory=lambda: _env("PCMILER_API_KEY"))
  pcmiler_routing_type: str = field(default_factory=lambda: _env("PCMILER_ROUTING_TYPE", "PRACTICAL").upper())
  # Optional MCP Toolbox for Databases server (tools.yaml) for read-only SQL tools.
  toolbox_url: str = field(default_factory=lambda: _env("TOOLBOX_URL"))
  toolbox_toolset: str = field(default_factory=lambda: _env("TOOLBOX_TOOLSET", "mclane-analytics"))
  tmw_api_base_url: str = field(default_factory=lambda: _env("TMW_API_BASE_URL"))
  tmw_api_token: str = field(default_factory=lambda: _env("TMW_API_TOKEN"))


def get_settings() -> Settings:
  return Settings()
