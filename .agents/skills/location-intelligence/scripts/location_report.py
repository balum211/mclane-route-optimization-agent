"""Deterministic location report for one DC: geofence events, dwell changes, geocodes, OTD.

  uv run python .agents/skills/location-intelligence/scripts/location_report.py --dc DC-PHOENIX-AZ --as-of 10:30
Exit code 0 when every tool ran, 1 otherwise.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from route_optimizer.tools import analytics_tools, location_tools  # noqa: E402


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--dc", default="DC-PHOENIX-AZ")
  ap.add_argument("--date", default="2026-10-27")
  ap.add_argument("--as-of", default="10:30")
  a = ap.parse_args()
  try:
    geo = location_tools.detect_geofence_events(a.dc, a.date, a.as_of)
    dwell = location_tools.analyze_dwell_time_changes(a.dc)
    codes = location_tools.validate_customer_geolocations(a.dc)
    otd = analytics_tools.get_otd_by_segment(a.dc)
  except Exception as e:  # report and fail
    print(f"FAILED: {e}")
    return 1
  print(json.dumps({
      "geofence": {k: geo[k] for k in ("arrivals", "departures", "dwell_overruns", "planned_stops_without_geofence_arrival")},
      "dwell_changes": {k: dwell[k] for k in ("customers_with_dwell_change", "longer", "shorter", "weekly_unplanned_minutes_total")},
      "geocodes": {k: codes[k] for k in ("flagged", "dc_geofence_capture_pct")},
      "otd": {g: otd[g]["otd_pct"] for g in ("RETAIL", "RESTAURANT")},
  }, indent=2, default=str))
  return 0


if __name__ == "__main__":
  sys.exit(main())
