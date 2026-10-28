"""Location intelligence: GPS positions, geofences, dwell time and geocodes.

* ``get_vehicle_locations``: where every truck is right now, from telematics.
* ``detect_geofence_events``: geofence arrivals and departures from GPS
  pings, dwell per stop versus what the plan allowed, today's Retail and
  Restaurant OTD, and DWELL_OVERRUN events for trucks stuck at a dock.
* ``analyze_dwell_time_changes``: customers whose dwell moved recently
  versus their own history and the TMW standard, with a recommended new
  standard.
* ``validate_customer_geolocations``: TMW coordinates versus where trucks
  actually park, so bad geocodes (and the geofences that miss because of
  them) get fixed.
* ``apply_master_data_updates``: applies the recommended dwell standards or
  geocodes for planning and queues COMPANY_UPDATE messages for TMW. Needs
  confirmation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from google.adk.tools import FunctionTool

from ..config import get_settings
from ..db.repository import get_repository
from ..geo import fmt_time, haversine_miles, parse_time
from ..geofence import METERS_PER_MILE, detect_visits, geofences_from_rows, learned_location, meters, pings_from_rows
from ..otd import is_on_time, segment_group, summarize
from ..planning import percentile
from ._common import ToolError, as_date, load_customers, load_dc, load_otd_policies, new_id, now_ts, q

MAX_ROWS = 25


def _fences(dc_id: str):
  """Active geofences, a GPS-learned fence replacing the master-data one for the same customer."""
  rows = q("SELECT * FROM geofences WHERE dc_id = :dc", dc=dc_id)
  best: dict[str, dict] = {}
  for r in rows:
    cur = best.get(r["entity_id"])
    if cur is None or (r["source"] == "GPS_LEARNED" and cur["source"] != "GPS_LEARNED"):
      best[r["entity_id"]] = r
  return geofences_from_rows(best.values())


def _round5(x: float) -> int:
  return int(5 * round(x / 5))


def get_vehicle_locations(dc_id: str, delivery_date: str, as_of: str) -> dict:
  """Latest GPS position of every truck out of a DC, from telematics pings.

  Args:
    dc_id: Distribution center id.
    delivery_date: YYYY-MM-DD operating date.
    as_of: HH:MM local time to report positions at.

  Returns:
    Per tractor: route, last ping time, lat/lon, speed, MOVING or STOPPED,
    the geofence it is inside (customer or DC) if any, and miles from the DC.
  """
  dc = load_dc(dc_id)
  date = as_date(delivery_date)
  now = parse_time(as_of)
  rows = q(
      "SELECT * FROM gps_pings WHERE dc_id = :dc AND ping_date = :d AND ping_min <= :m ORDER BY tractor_id, ping_min",
      dc=dc["dc_id"], d=date, m=now,
  )
  if not rows:
    raise ToolError(f"No GPS pings for {dc['dc_id']} on {date} up to {fmt_time(now)}.")
  last: dict[str, dict] = {}
  for r in rows:
    last[r["tractor_id"]] = r
  fences = _fences(dc["dc_id"])
  customers = load_customers(dc["dc_id"])
  trucks = []
  for tid, r in sorted(last.items()):
    lat, lon = float(r["lat"]), float(r["lon"])
    inside = next((g for g in fences if meters(lat, lon, g.lat, g.lon) <= g.radius_m), None)
    trucks.append({
        "tractor_id": tid, "route_id": r["route_id"], "last_ping": fmt_time(r["ping_min"]),
        "minutes_since_ping": now - int(r["ping_min"]), "lat": round(lat, 5), "lon": round(lon, 5),
        "speed_mph": r["speed_mph"], "status": "MOVING" if float(r["speed_mph"] or 0) > 3 else "STOPPED",
        "inside_geofence": (
            None if inside is None
            else {"geofence_id": inside.geofence_id, "type": inside.entity_type,
                  "name": customers.get(inside.entity_id, {}).get("name", inside.entity_id)}
        ),
        "miles_from_dc": round(haversine_miles(lat, lon, float(dc["lat"]), float(dc["lon"])), 1),
    })
  stale = [t["tractor_id"] for t in trucks if t["minutes_since_ping"] > 20]
  return {"dc_id": dc["dc_id"], "as_of": fmt_time(now), "trucks": trucks,
          "stale_gps": stale, "note": "stale_gps lists trucks with no ping in the last 20 minutes."}


def detect_geofence_events(dc_id: str, delivery_date: str, as_of: str) -> dict:
  """Runs the geofence engine on today's GPS pings: arrivals, departures, dwell and OTD.

  Saves completed visits to geofence_events. A truck still inside a customer
  geofence longer than the planned unload time plus the delay trigger
  (default 15 min) raises a DWELL_OVERRUN route event that the disruption
  agent can re-plan with handle_route_event.

  Args:
    dc_id: Distribution center id.
    delivery_date: YYYY-MM-DD operating date.
    as_of: HH:MM local time; pings after it are ignored.

  Returns:
    Counts of arrivals and departures, stops where the dwell ran over plan,
    trucks on site right now, planned stops with no geofence arrival (often a
    bad geocode), today's OTD for Retail and Restaurant so far, and new
    DWELL_OVERRUN event ids.
  """
  s = get_settings()
  dc = load_dc(dc_id)
  date = as_date(delivery_date)
  now = parse_time(as_of)
  pings = pings_from_rows(q(
      "SELECT * FROM gps_pings WHERE dc_id = :dc AND ping_date = :d AND ping_min <= :m", dc=dc["dc_id"], d=date, m=now))
  if not pings:
    raise ToolError(f"No GPS pings for {dc['dc_id']} on {date} up to {fmt_time(now)}.")
  customers = load_customers(dc["dc_id"])
  policies = load_otd_policies()
  visits = [v for v in detect_visits(pings, _fences(dc["dc_id"]), now) if v.geofence.entity_type == "CUSTOMER"]

  route_ids = sorted({p.route_id for p in pings if p.route_id})
  planned: dict[tuple[str, str], dict] = {}
  for rid in route_ids:
    for st in q("SELECT * FROM route_stops WHERE route_id = :r", r=rid):
      if st["eta_min"] is None:
        continue
      c = customers.get(st["customer_id"], {})
      start = max(int(st["eta_min"]), int(c.get("window_start_min") or 0))
      planned[(rid, st["customer_id"])] = st | {"service": int(st["etd_min"]) - start}

  repo = get_repository()
  known = {r["geofence_event_id"] for r in q(
      "SELECT geofence_event_id FROM geofence_events WHERE dc_id = :dc AND event_date = :d", dc=dc["dc_id"], d=date)}
  rows, overruns, on_site, otd_recs = [], [], [], []
  for v in visits:
    cid = v.geofence.entity_id
    plan = planned.get((v.route_id, cid))
    service = plan["service"] if plan else int(customers.get(cid, {}).get("std_service_min") or 30)
    vid = f"GV-{v.tractor_id}-{date:%Y%m%d}-{v.arrive_min:04d}"
    c = customers.get(cid, {})
    if plan:
      pol = policies[segment_group(c.get("segment"))]
      otd_recs.append({"segment": c.get("segment"), "on_time": is_on_time(
          pol, v.arrive_min, int(c["window_start_min"]), int(c["window_end_min"]), int(plan["eta_min"]))})
    rec = {"customer_id": cid, "name": c.get("name"), "tractor_id": v.tractor_id, "route_id": v.route_id,
           "arrive": fmt_time(v.arrive_min), "depart": fmt_time(v.depart_min) if v.depart_min is not None else None,
           "dwell_min": v.dwell_min, "planned_service_min": service, "over_plan_min": v.dwell_min - service}
    if v.depart_min is None:
      on_site.append(rec)
    if v.dwell_min - service >= s.delay_trigger_min:
      overruns.append(rec)
    if v.depart_min is not None and vid not in known:
      rows.append({"geofence_event_id": vid, "dc_id": dc["dc_id"], "event_date": date, "tractor_id": v.tractor_id,
                   "route_id": v.route_id, "geofence_id": v.geofence.geofence_id, "entity_type": "CUSTOMER",
                   "entity_id": cid, "arrive_min": v.arrive_min, "depart_min": v.depart_min,
                   "dwell_min": v.dwell_min, "planned_service_min": service, "created_at": now_ts()})
  if rows:
    repo.insert("geofence_events", rows)

  # Trucks stuck on site now become DWELL_OVERRUN events for the re-planner.
  existing = {e["event_id"] for e in q(
      "SELECT event_id FROM route_events WHERE dc_id = :dc AND event_date = :d", dc=dc["dc_id"], d=date)}
  new_events = []
  for rec in overruns:
    if rec["depart"] is not None:
      continue
    eid = f"EVT-GF-{rec['tractor_id']}-{rec['arrive'].replace(':', '')}"
    seeded = q("SELECT event_id FROM route_events WHERE event_type = 'DWELL_OVERRUN' AND tractor_id = :t "
               "AND customer_id = :c AND event_date = :d", t=rec["tractor_id"], c=rec["customer_id"], d=date)
    if eid in existing or seeded:
      continue
    new_events.append({
        "event_id": eid, "dc_id": dc["dc_id"], "event_date": date, "event_min": now, "event_type": "DWELL_OVERRUN",
        "source": "GEOFENCE", "tractor_id": rec["tractor_id"], "customer_id": rec["customer_id"], "order_id": None,
        "delay_min": max(s.delay_trigger_min, rec["over_plan_min"]), "lat": None, "lon": None, "radius_miles": None,
        "delay_factor": None, "payload": {"planned_service_min": rec["planned_service_min"], "dwell_min": rec["dwell_min"],
                    "route_id": rec["route_id"]},
        "description": f"Truck {rec['tractor_id']} inside the geofence at {rec['name']} for {rec['dwell_min']} min "
                       f"(plan allowed {rec['planned_service_min']} min)",
    })
  if new_events:
    repo.insert("route_events", new_events)

  visited = {(v.route_id, v.geofence.entity_id) for v in visits}
  missed = [
      {"customer_id": cid, "name": customers.get(cid, {}).get("name"), "route_id": rid,
       "planned_eta": fmt_time(p["eta_min"]),
       "geocode_source": customers.get(cid, {}).get("geocode_source")}
      for (rid, cid), p in planned.items()
      if int(p["eta_min"]) + p["service"] + 30 < now and (rid, cid) not in visited
  ]
  return {
      "dc_id": dc["dc_id"], "as_of": fmt_time(now), "pings_processed": len(pings),
      "arrivals": len(visits), "departures": sum(1 for v in visits if v.depart_min is not None),
      "saved_visits": len(rows),
      "dwell_overruns": sorted(overruns, key=lambda r: -r["over_plan_min"])[:MAX_ROWS],
      "trucks_on_site_now": on_site,
      "planned_stops_without_geofence_arrival": missed[:MAX_ROWS],
      "otd_today_so_far": summarize(otd_recs, policies),
      "new_dwell_overrun_events": [e["event_id"] for e in new_events],
      "next_step": "Hand new DWELL_OVERRUN events to handle_route_event; check missed arrivals with "
                   "validate_customer_geolocations.",
  }


def _dwell_changes(dc_id: str, recent_days: int, min_change_min: int, min_change_pct: float) -> tuple[list[dict], dict]:
  rows = q(
      "SELECT h.customer_id, h.delivery_date, h.dwell_min, h.exception_code, h.arrival_source "
      "FROM delivery_history h WHERE h.dc_id = :dc", dc=dc_id)
  if not rows:
    raise ToolError("No delivery history for that DC.")
  customers = load_customers(dc_id)
  last = max(str(r["delivery_date"])[:10] for r in rows)
  import datetime as dt

  cutoff = (dt.date.fromisoformat(last) - dt.timedelta(days=recent_days - 1)).isoformat()
  span_days = (dt.date.fromisoformat(last) - dt.date.fromisoformat(min(str(r["delivery_date"])[:10] for r in rows))).days + 1
  by = defaultdict(lambda: {"recent": [], "base": [], "exc": Counter()})
  for r in rows:
    k = "recent" if str(r["delivery_date"])[:10] >= cutoff else "base"
    by[r["customer_id"]][k].append(int(r["dwell_min"]))
    if k == "recent" and r["exception_code"] != "NONE":
      by[r["customer_id"]]["exc"][r["exception_code"]] += 1
  out = []
  for cid, d in by.items():
    if len(d["recent"]) < 3 or len(d["base"]) < 5:
      continue
    c = customers.get(cid, {})
    base, recent = median(d["base"]), median(d["recent"])
    change = recent - base
    pct = 100 * change / base if base else 0
    if abs(change) < min_change_min or abs(pct) < min_change_pct:
      continue
    std = int(c.get("std_service_min") or 0)
    rec_std = _round5(percentile(d["recent"], 0.75))
    per_week = len(d["recent"]) / recent_days * 7
    out.append({
        "customer_id": cid, "name": c.get("name"), "segment": c.get("segment"), "otd_group": segment_group(c.get("segment")),
        "tmw_cmp_id": c.get("tmw_cmp_id"), "direction": "LONGER" if change > 0 else "SHORTER",
        "baseline_median_dwell_min": round(base, 1), "recent_median_dwell_min": round(recent, 1),
        "change_min": round(change, 1), "change_pct": round(pct, 1),
        "tms_standard_min": std, "recommended_tms_standard_min": rec_std,
        "deliveries_per_week": round(per_week, 1),
        "weekly_minutes_unplanned_if_unchanged": round(max(0, rec_std - std) * per_week),
        "recent_exceptions": dict(d["exc"].most_common(2)),
    })
  out.sort(key=lambda r: -abs(r["change_min"]))
  stale = []
  for cid, d in by.items():
    vals = d["base"] + d["recent"]
    std = int(customers.get(cid, {}).get("std_service_min") or 0)
    if len(vals) >= 8 and percentile(vals, 0.75) - std >= 10:
      stale.append(cid)
  meta = {"history_days": span_days, "recent_window": [cutoff, last], "customers_analyzed": len(by),
          "stale_tms_standards": len(stale)}
  return out, meta


def analyze_dwell_time_changes(dc_id: str, recent_days: int = 14, min_change_min: int = 8,
                               min_change_pct: float = 25.0) -> dict:
  """Finds customers whose dwell (time on site, from geofence entry to exit) changed recently.

  Compares the median dwell of the last ``recent_days`` with the customer's
  earlier history, and both with the TMW standard unload time. The planner
  already switches to the recent p75 for these customers; this tool explains
  the change and recommends the new TMW standard.

  Args:
    dc_id: Distribution center id.
    recent_days: Length of the recent window in days.
    min_change_min: Ignore changes smaller than this many minutes.
    min_change_pct: Ignore changes smaller than this percentage.

  Returns:
    Customers with LONGER or SHORTER dwell, baseline and recent medians, the
    TMW standard and recommended standard (recent p75 rounded to 5 min),
    weekly minutes that would go unplanned without the update, recent
    exception codes, and how many TMW standards are stale overall.
  """
  dc = load_dc(dc_id)
  changes, meta = _dwell_changes(dc["dc_id"], recent_days, min_change_min, min_change_pct)
  longer = [c for c in changes if c["direction"] == "LONGER"]
  return {
      "dc_id": dc["dc_id"], **meta,
      "customers_with_dwell_change": len(changes),
      "longer": len(longer), "shorter": len(changes) - len(longer),
      "weekly_unplanned_minutes_total": sum(c["weekly_minutes_unplanned_if_unchanged"] for c in changes),
      "changes": changes[:MAX_ROWS],
      "next_step": "apply_master_data_updates with update_type DWELL updates the TMW standards (asks for confirmation).",
  }


def _geocode_issues(dc_id: str, min_offset_m: float) -> list[dict]:
  customers = load_customers(dc_id)
  rows = q("SELECT customer_id, gps_stop_lat, gps_stop_lon, arrival_source FROM delivery_history WHERE dc_id = :dc",
           dc=dc_id)
  pts, src = defaultdict(list), defaultdict(Counter)
  for r in rows:
    if r["gps_stop_lat"] is not None:
      pts[r["customer_id"]].append((float(r["gps_stop_lat"]), float(r["gps_stop_lon"])))
    src[r["customer_id"]][r["arrival_source"]] += 1
  out = []
  for cid, p in pts.items():
    c = customers.get(cid)
    if not c or len(p) < 3:
      continue
    lat, lon = learned_location(p)
    off = meters(float(c["lat"]), float(c["lon"]), lat, lon)
    if off < min_offset_m:
      continue
    n = sum(src[cid].values())
    out.append({
        "customer_id": cid, "name": c["name"], "tmw_cmp_id": c["tmw_cmp_id"], "address": f"{c['address']}, {c['city']}",
        "geocode_source": c.get("geocode_source"), "tmw_lat": c["lat"], "tmw_lon": c["lon"],
        "observed_lat": round(lat, 6), "observed_lon": round(lon, 6),
        "offset_miles": round(off / METERS_PER_MILE, 2), "gps_visits": len(p),
        "geofence_capture_pct": round(100 * src[cid]["GEOFENCE"] / n, 1) if n else None,
    })
  out.sort(key=lambda r: -r["offset_miles"])
  return out


def validate_customer_geolocations(dc_id: str, min_offset_m: int = 250) -> dict:
  """Checks TMW customer coordinates against where trucks actually park (GPS stop detection).

  A geocode that is off (often a ZIP centroid) makes the geofence miss, so
  arrival and dwell fall back to driver taps, ETAs are wrong and the
  optimizer plans to the wrong spot.

  Args:
    dc_id: Distribution center id.
    min_offset_m: Flag customers whose TMW point is at least this many
      meters from the observed parking spot.

  Returns:
    Flagged customers with TMW and observed coordinates, offset in miles,
    number of GPS visits, geofence capture rate, plus the DC-wide capture
    rate.
  """
  dc = load_dc(dc_id)
  issues = _geocode_issues(dc["dc_id"], min_offset_m)
  cap = q("SELECT arrival_source, COUNT(*) AS n FROM delivery_history WHERE dc_id = :dc GROUP BY arrival_source",
          dc=dc["dc_id"])
  tot = sum(int(r["n"]) for r in cap) or 1
  geo = sum(int(r["n"]) for r in cap if r["arrival_source"] == "GEOFENCE")
  return {
      "dc_id": dc["dc_id"],
      "customers_checked": len(load_customers(dc["dc_id"])),
      "flagged": len(issues),
      "dc_geofence_capture_pct": round(100 * geo / tot, 1),
      "issues": issues[:MAX_ROWS],
      "next_step": "apply_master_data_updates with update_type GEOCODE moves the point and geofence to the observed "
                   "location and queues the TMW company update (asks for confirmation).",
  }


def apply_master_data_updates(dc_id: str, update_type: str, customer_ids: list[str]) -> dict:
  """Applies recommended customer master-data fixes and queues them for Trimble TMW.

  DWELL sets the TMW standard unload time to the recommended value from
  analyze_dwell_time_changes. GEOCODE moves the customer point to the
  observed parking location from validate_customer_geolocations and adds a
  GPS-learned geofence there. Planning uses the change immediately; TMW gets
  a COMPANY_UPDATE message. Requires confirmation.

  Args:
    dc_id: Distribution center id.
    update_type: DWELL or GEOCODE.
    customer_ids: Customers to update. Empty list means every flagged customer.

  Returns:
    Updates applied with old and new values, and the TMW message ids queued.
  """
  dc = load_dc(dc_id)
  kind = update_type.strip().upper()
  if kind == "DWELL":
    found = {r["customer_id"]: r for r in _dwell_changes(dc["dc_id"], 14, 8, 25.0)[0]}
  elif kind == "GEOCODE":
    found = {r["customer_id"]: r for r in _geocode_issues(dc["dc_id"], 250)}
  else:
    raise ToolError("update_type must be DWELL or GEOCODE.")
  wanted = [c.strip().upper() for c in customer_ids] or list(found)
  unknown = [c for c in wanted if c not in found]
  if unknown:
    raise ToolError(f"No {kind} recommendation for {', '.join(unknown)}. Run the analysis tool first.")
  repo, updates, msgs, fences = get_repository(), [], [], []
  for cid in wanted:
    r = found[cid]
    if kind == "DWELL":
      field, old, new = "std_service_min", str(r["tms_standard_min"]), str(r["recommended_tms_standard_min"])
      reason = f"Dwell {r['direction'].lower()} by {abs(r['change_min'])} min in the last 14 days"
      company = {"cmp_id": r["tmw_cmp_id"], "standard_stop_minutes": int(new)}
    else:
      field = "lat_lon"
      old, new = f"{r['tmw_lat']},{r['tmw_lon']}", f"{r['observed_lat']},{r['observed_lon']}"
      reason = f"TMW geocode ({r['geocode_source']}) is {r['offset_miles']} mi from where trucks park"
      # TMW company profiles hold coordinates in seconds (cmp_latseconds / cmp_longseconds).
      company = {"cmp_id": r["tmw_cmp_id"], "cmp_latseconds": round(r["observed_lat"] * 3600),
                 "cmp_longseconds": round(abs(r["observed_lon"]) * 3600)}
      fences.append({"geofence_id": f"GF-{cid}-GPS", "entity_type": "CUSTOMER", "entity_id": cid, "dc_id": dc["dc_id"],
                     "center_lat": r["observed_lat"], "center_lon": r["observed_lon"], "radius_m": 150,
                     "source": "GPS_LEARNED", "active": True})
    uid = new_id("MDU")
    updates.append({"update_id": uid, "dc_id": dc["dc_id"], "customer_id": cid, "field": field, "old_value": old,
                    "new_value": new, "reason": reason, "evidence": r, "status": "APPLIED", "created_at": now_ts()})
    msgs.append({"message_id": new_id("TMW"), "plan_id": None, "route_id": None, "message_type": "COMPANY_UPDATE",
                 "payload": {"company": company, "reason": reason, "update_id": uid}, "status": "QUEUED",
                 "created_at": now_ts()})
  repo.insert("master_data_updates", updates)
  repo.insert("tmw_dispatch_queue", msgs)
  if fences:
    repo.insert("geofences", fences)
  return {
      "dc_id": dc["dc_id"], "update_type": kind, "applied": len(updates),
      "updates": [{"customer_id": u["customer_id"], "field": u["field"], "old": u["old_value"], "new": u["new_value"],
                   "reason": u["reason"]} for u in updates][:MAX_ROWS],
      "tmw_messages_queued": [m["message_id"] for m in msgs][:MAX_ROWS],
  }


apply_master_data_updates_tool = FunctionTool(apply_master_data_updates, require_confirmation=True)
