"""Every test runs against a freshly generated SQLite copy of the dataset."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def synthetic_db(tmp_path_factory):
  out = tmp_path_factory.mktemp("data")
  db = out / "mclane_routing.db"
  subprocess.run(
      [sys.executable, str(ROOT / "data" / "generate_synthetic_data.py"), "--out", str(out / "csv"), "--sqlite", str(db)],
      check=True, capture_output=True,
  )
  # generate_synthetic_data also refreshes data/schema; that is harmless.
  os.environ["DB_BACKEND"] = "sqlite"
  os.environ["SQLITE_PATH"] = str(db)
  os.environ["SOLVER_TIME_LIMIT_S"] = "3"
  os.environ["REPLAN_TIME_LIMIT_S"] = "3"
  from route_optimizer.db.repository import get_repository

  get_repository.cache_clear()
  yield db
  shutil.rmtree(out, ignore_errors=True)


class FakeToolContext:
  def __init__(self):
    self.state = {}


@pytest.fixture
def tool_context():
  return FakeToolContext()
