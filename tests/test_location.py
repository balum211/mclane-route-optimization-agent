"""PC*MILER, geofences, dwell time change, geocodes and Retail/Restaurant OTD (no LLM)."""

import json
import os
from pathlib import Path

import pytest

from route_optimizer import pcmiler
from route_optimizer.geo import Point
from route_optimizer.geofence import Geofence, Ping, detect_visits
from route_optimizer.otd import DEFAULT_POLICIES, is_on_time, segment_group
from route_optimizer.tools import analytics_tools, location_tools
from route_optimizer.tools._common import ToolError, load_customers

PHX, TEM, DAY = "DC-PHOENIX-AZ", "DC-TEMPLE-TX", "2026-10-27"


def planted(synthetic_db):
  return json.loads((Path(synthetic_db).parent / "csv" / "_planted_patterns.json").read_text())


# --- PC*MILER -------------------------------------------------------------


def test_pcmiler_emulation_is_labelled_and_deterministic(monkeypatch):
  monkeypatch.delenv("PCMILER_API_KEY", raising=False)
  pts = [Point("DC", 31.0982, -97.3428), Point("A", 31.5493, -97.1467), Point("DC", 31.0982, -97.3428)]
  a, b = pcmiler.route_mileage(pts), pcmiler.route_mileage(pts)
  assert a == b and a.source == "PCMILER_EMULATED" and a.routing_type == "PRACTICAL"
  assert len(a.leg_miles) == 2 and 30 < a.leg_miles[0] < 45  # Temple to Waco is about 35 road miles
  assert pcmiler.route_mileage(pts, "SHORTEST").total_miles < a.total_miles


def test_pcmiler_parses_mileage_report():
  report = [{"ReportLines": [{"LMiles": "0.000", "THours": "0:00"}, {"LMiles": "35.2", "THours": "0:41"},
                             {"LMiles": "1,034.8", "THours": "16:10"}]}]
  legs, hours = pcmiler._parse_report(report)
  assert legs == [35.2, 1034.8] and abs(hours - (16 + 10 / 60)) < 1e-9


def test_pcmiler_live_falls_back_when_service_fails(monkeypatch):
  monkeypatch.setenv("PCMILER_API_KEY", "test-key")
  monkeypatch.setenv("PCMILER_BASE_URL", "https://127.0.0.1:9")  # nothing listens here
  pcmiler._live_route.cache_clear()
  m = pcmiler.route_mileage([Point("A", 33.4, -112.3), Point("B", 33.5, -112.0)])
  assert m.source == "PCMILER_EMULATED" and m.total_miles > 0


# --- Geofence engine --------------------------------------------------------


def test_geofence_visit_with_jitter_is_one_visit():
  g = Geofence("GF-1", "CUSTOMER", "C1", 33.0, -112.0, 150)
  pings = [Ping("T1", 0, 33.02, -112.0, 45)]
  # Parked at the dock with GPS jitter near the edge of the fence, then leaves.
  pings += [Ping("T1", m, 33.0 + (0.0012 if m % 10 else 0.0), -112.0, 0) for m in range(5, 50, 5)]
  pings += [Ping("T1", 55, 33.03, -112.0, 40)]
  visits = detect_visits(pings, [g])
  assert len(visits) == 1
  assert (visits[0].arrive_min, visits[0].depart_min, visits[0].dwell_min) == (5, 45, 40)
  still = detect_visits(pings, [g], as_of_min=30)
  assert still[0].depart_min is None and still[0].dwell_min == 25


def test_vehicle_locations_and_geofence_events():
  locs = location_tools.get_vehicle_locations(PHX, DAY, "10:30")
  stuck = next(t for t in locs["trucks"] if t["tractor_id"] == "TRC-PHO-002")
  assert stuck["status"] == "STOPPED" and stuck["inside_geofence"]["type"] == "CUSTOMER"

  out = location_tools.detect_geofence_events(PHX, DAY, "10:30")
  assert out["arrivals"] > 20 and out["saved_visits"] > 0
  assert any(r["tractor_id"] == "TRC-PHO-002" and r["depart"] is None for r in out["dwell_overruns"])
  # The planted overrun is already a seeded event, so no duplicate is raised.
  assert out["new_dwell_overrun_events"] == []
  # Missed arrivals are the bad geocodes.
  assert out["planned_stops_without_geofence_arrival"]
  assert all(m["geocode_source"] == "ZIP_CENTROID" for m in out["planned_stops_without_geofence_arrival"])
  assert out["otd_today_so_far"]["RESTAURANT"]["deliveries"] > 0
  again = location_tools.detect_geofence_events(PHX, DAY, "10:30")
  assert again["saved_visits"] == 0  # idempotent


def test_geofence_raises_dwell_overrun_events_for_new_stuck_trucks():
  out = location_tools.detect_geofence_events(TEM, DAY, "12:00")
  for eid in out["new_dwell_overrun_events"]:
    assert eid.startswith("EVT-GF-")


# --- Dwell time change ------------------------------------------------------


def test_dwell_change_finds_planted_shifts(synthetic_db):
  truth = {c["customer_id"]: c for c in planted(synthetic_db)["dwell_changes_last_14_days"] if c["customer_id"].startswith("C-TEM")}
  out = location_tools.analyze_dwell_time_changes(TEM)
  found = {c["customer_id"]: c for c in out["changes"]}
  assert out["customers_with_dwell_change"] >= 5
  big = [cid for cid, c in truth.items() if c["factor"] >= 1.35 or c["factor"] <= 0.8]
  hits = [cid for cid in big if cid in found]
  assert len(hits) >= 0.6 * min(len(big), len(found))
  for cid in hits:
    assert found[cid]["direction"] == ("LONGER" if truth[cid]["factor"] > 1 else "SHORTER")


def test_apply_dwell_update_changes_planning_inputs_and_queues_tmw():
  out = location_tools.analyze_dwell_time_changes(TEM)
  target = out["changes"][0]
  assert location_tools.apply_master_data_updates_tool._require_confirmation is True
  res = location_tools.apply_master_data_updates(TEM, "DWELL", [target["customer_id"]])
  assert res["applied"] == 1 and res["tmw_messages_queued"]
  assert load_customers(TEM)[target["customer_id"]]["std_service_min"] == target["recommended_tms_standard_min"]
  with pytest.raises(ToolError):
    location_tools.apply_master_data_updates(TEM, "COLOR", [])


# --- Geolocations -----------------------------------------------------------


def test_geocode_validation_finds_bad_geocodes(synthetic_db):
  bad = {c for c in planted(synthetic_db)["bad_geocodes"] if c.startswith("C-PHO")}
  out = location_tools.validate_customer_geolocations(PHX)
  flagged = {r["customer_id"] for r in out["issues"]}
  assert bad and bad <= flagged  # every planted bad geocode is flagged
  assert out["flagged"] == len(flagged)
  assert all(r["offset_miles"] >= 0.15 for r in out["issues"])
  worst = out["issues"][0]
  res = location_tools.apply_master_data_updates(PHX, "GEOCODE", [worst["customer_id"]])
  c = load_customers(PHX)[worst["customer_id"]]
  assert (round(c["lat"], 6), c["geocode_source"]) == (worst["observed_lat"], "GPS_LEARNED")
  assert res["updates"][0]["field"] == "lat_lon"


# --- OTD --------------------------------------------------------------------


def test_otd_policies():
  retail, rest = DEFAULT_POLICIES["RETAIL"], DEFAULT_POLICIES["RESTAURANT"]
  assert segment_group("QSR") == "RESTAURANT" and segment_group("CONVENIENCE") == "RETAIL"
  assert is_on_time(retail, 200, 300, 600)            # early is fine for retail
  assert not is_on_time(retail, 601, 300, 600)
  assert is_on_time(rest, 420, 300, 600, scheduled_min=400)
  assert not is_on_time(rest, 431, 300, 600, scheduled_min=400)   # 31 min after the scheduled time
  assert not is_on_time(rest, 360, 300, 600, scheduled_min=400)   # 40 min early: crew not there
  assert not is_on_time(rest, 610, 300, 600, scheduled_min=590)   # after the window


def test_otd_by_segment():
  out = analytics_tools.get_otd_by_segment()
  assert out["RETAIL"]["deliveries"] and out["RESTAURANT"]["deliveries"]
  assert out["RETAIL"]["target_pct"] == 95.0 and out["RESTAURANT"]["target_pct"] == 98.0
  assert set(out["by_dc"]) == {"DC-CONCORD-NC", "DC-DALLAS-TX", "DC-PHOENIX-AZ", "DC-TEMPLE-TX"}
  dal = analytics_tools.get_otd_by_segment("DC-DALLAS-TX", "2026-10-01", "2026-10-26")
  assert dal["RETAIL"]["deliveries"] == 0 and dal["RESTAURANT"]["deliveries"] > 0
  assert sum(dal["RESTAURANT"]["misses_early_vs_late"].values()) == dal["RESTAURANT"]["deliveries"] - dal["RESTAURANT"]["on_time"]
