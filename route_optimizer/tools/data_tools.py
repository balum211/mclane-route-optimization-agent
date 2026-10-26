"""Read-only tools: DCs, demand, fleet, customers and disruptions."""

from __future__ import annotations

from collections import Counter

from ..geo import fmt_time, haversine_miles
from ._common import ToolError, as_date, load_dc, load_disruptions, load_learned_service, load_vehicles, q


def list_distribution_centers() -> dict:
  """Lists McLane distribution centers (DCs) available for route planning.

  Returns:
    DC ids, business unit (GROCERY serves convenience/retail stores,
    FOODSERVICE serves restaurant chains), location, dispatch window, and how
    many customers each serves. Use the dc_id in every other tool.
  """
  dcs = q("SELECT * FROM distribution_centers ORDER BY dc_id")
  counts = {r["dc_id"]: r["n"] for r in q("SELECT dc_id, COUNT(*) AS n FROM customers GROUP BY dc_id")}
  dates = q("SELECT DISTINCT delivery_date FROM orders ORDER BY delivery_date")
  return {
      "distribution_centers": [
          {
              "dc_id": d["dc_id"],
              "name": d["name"],
              "business_unit": d["business_unit"],
              "location": f"{d['city']}, {d['state']}",
              "dispatch_window": f"{fmt_time(d['dispatch_start_min'])}-{fmt_time(d['dispatch_end_min'])}",
              "customers": counts.get(d["dc_id"], 0),
          }
          for d in dcs
      ],
      "order_dates_available": [r["delivery_date"] for r in dates],
  }


def get_delivery_demand(dc_id: str, delivery_date: str) -> dict:
  """Summarizes open delivery orders for a DC and date before routing.

  Args:
    dc_id: Distribution center id, e.g. "DC-TEMPLE-TX".
    delivery_date: Delivery date in YYYY-MM-DD format.

  Returns:
    Order and case counts by temperature class (dry, chill, frozen), HOT and
    FLEX orders, customer segment mix, receiving-window mix, and sites that
    need a liftgate or short vehicle.
  """
  dc = load_dc(dc_id)
  date = as_date(delivery_date)
  orders = q(
      "SELECT o.*, c.segment, c.window_start_min, c.window_end_min, c.requires_liftgate, "
      "c.max_vehicle_length_ft, c.priority_tier "
      "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
      "WHERE o.dc_id = :dc_id AND o.delivery_date = :d",
      dc_id=dc["dc_id"],
      d=date,
  )
  if not orders:
    return {"dc_id": dc["dc_id"], "delivery_date": str(date), "orders": 0, "note": "No open orders for this date."}
  windows = Counter(f"{fmt_time(o['window_start_min'])}-{fmt_time(o['window_end_min'])}" for o in orders)
  b = lambda v: str(v).lower() in {"1", "true", "t"}
  return {
      "dc_id": dc["dc_id"],
      "business_unit": dc["business_unit"],
      "delivery_date": str(date),
      "orders": len(orders),
      "cases": {
          "dry": sum(int(o["dry_cases"]) for o in orders),
          "chill": sum(int(o["chill_cases"]) for o in orders),
          "frozen": sum(int(o["frozen_cases"]) for o in orders),
      },
      "total_weight_lbs": sum(int(o["weight_lbs"]) for o in orders),
      "priority": dict(Counter(o["priority"] for o in orders)),
      "segments": dict(Counter(o["segment"] for o in orders)),
      "receiving_windows": dict(windows.most_common(6)),
      "liftgate_required_stops": sum(1 for o in orders if b(o["requires_liftgate"])),
      "short_vehicle_stops": sum(1 for o in orders if int(o["max_vehicle_length_ft"] or 53) < 53),
      "strategic_accounts_tier1": sum(1 for o in orders if int(o["priority_tier"] or 3) == 1),
  }


def get_fleet_availability(dc_id: str) -> dict:
  """Returns dispatchable trucks, trailers and drivers for a DC.

  Args:
    dc_id: Distribution center id.

  Returns:
    Units that can be dispatched (tractor + trailer + driver), capacity by
    trailer type, units in maintenance, drivers on PTO, and drivers with
    reduced hours of service (HOS).
  """
  dc = load_dc(dc_id)
  tractors = q("SELECT * FROM tractors WHERE dc_id = :dc_id", dc_id=dc["dc_id"])
  trailers = q("SELECT * FROM trailers WHERE dc_id = :dc_id", dc_id=dc["dc_id"])
  drivers = q("SELECT * FROM drivers WHERE dc_id = :dc_id", dc_id=dc["dc_id"])
  vehicles = load_vehicles(dc)
  by_type = Counter(t["trailer_type"] for t in trailers if t["status"] == "AVAILABLE")
  return {
      "dc_id": dc["dc_id"],
      "dispatchable_units": len(vehicles),
      "total_case_capacity": sum(v.capacity_cases for v in vehicles),
      "cold_case_capacity": sum(v.capacity_cold_cases for v in vehicles),
      "trailers_available_by_type": dict(by_type),
      "tractors_in_maintenance": [t["tractor_id"] for t in tractors if t["status"] != "AVAILABLE"],
      "drivers_on_pto": [d["driver_id"] for d in drivers if d["status"] != "AVAILABLE"],
      "drivers_with_reduced_hos": [
          {"driver_id": d["driver_id"], "duty_h_left": round(int(d["hos_duty_remaining_min"]) / 60, 1)}
          for d in drivers
          if d["status"] == "AVAILABLE" and int(d["hos_duty_remaining_min"]) < 840
      ],
      "units": [
          {
              "vehicle_id": v.vehicle_id,
              "driver_id": v.driver_id,
              "cases": v.capacity_cases,
              "cold_cases": v.capacity_cold_cases,
              "length_ft": v.length_ft,
              "liftgate": v.has_liftgate,
              "earliest_start": fmt_time(v.earliest_start),
          }
          for v in vehicles
      ],
  }


def get_customer_profile(customer_id: str) -> dict:
  """Looks up one store or restaurant, with its 60-day delivery performance.

  Args:
    customer_id: Customer id, e.g. "C-TEM-0042".

  Returns:
    Master data from the TMS (window, standard unload time, restrictions),
    plus history: on-time rate, typical arrival delay, learned p75 unload time
    and the most common delivery exceptions.
  """
  rows = q("SELECT * FROM customers WHERE customer_id = :cid", cid=customer_id.strip().upper())
  if not rows:
    raise ToolError(f"Unknown customer {customer_id!r}")
  c = rows[0]
  hist = q(
      "SELECT * FROM delivery_history WHERE customer_id = :cid ORDER BY delivery_date",
      cid=c["customer_id"],
  )
  on_time = [str(h["on_time"]).lower() in {"1", "true", "t"} for h in hist]
  delays = sorted(int(h["actual_arrival_min"]) - int(h["planned_arrival_min"]) for h in hist)
  learned = load_learned_service(c["dc_id"]).get(c["customer_id"])
  exc = Counter(h["exception_code"] for h in hist if h["exception_code"] != "NONE")
  return {
      "customer_id": c["customer_id"],
      "tmw_cmp_id": c["tmw_cmp_id"],
      "name": c["name"],
      "segment": c["segment"],
      "address": f"{c['address']}, {c['city']}, {c['state']}",
      "dc_id": c["dc_id"],
      "receiving_window": f"{fmt_time(c['window_start_min'])}-{fmt_time(c['window_end_min'])}",
      "delivery_days": c["delivery_days"],
      "tms_standard_unload_min": c["std_service_min"],
      "learned_p75_unload_min": learned,
      "requires_liftgate": str(c["requires_liftgate"]).lower() in {"1", "true", "t"},
      "max_vehicle_length_ft": c["max_vehicle_length_ft"],
      "priority_tier": c["priority_tier"],
      "history_deliveries": len(hist),
      "on_time_rate_pct": round(100 * sum(on_time) / len(on_time), 1) if on_time else None,
      "median_arrival_delay_min": delays[len(delays) // 2] if delays else None,
      "top_exceptions": dict(exc.most_common(3)),
  }


def get_active_disruptions(dc_id: str, delivery_date: str) -> dict:
  """Lists traffic incidents and weather alerts near a DC on a date.

  Args:
    dc_id: Distribution center id.
    delivery_date: YYYY-MM-DD.

  Returns:
    Each event with its corridor, active hours, travel-time multiplier, and
    how many of that day's delivery stops sit inside the affected radius.
  """
  dc = load_dc(dc_id)
  date = as_date(delivery_date)
  _, raw = load_disruptions(dc, date)
  stops = q(
      "SELECT c.customer_id, c.lat, c.lon FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
      "WHERE o.dc_id = :dc_id AND o.delivery_date = :d",
      dc_id=dc["dc_id"],
      d=date,
  )
  events = []
  for e in raw:
    lat, lon, r = float(e["lat"]), float(e["lon"]), float(e["radius_miles"])
    inside = sum(1 for s in stops if haversine_miles(float(s["lat"]), float(s["lon"]), lat, lon) <= r)
    events.append({
        "event_id": e["event_id"],
        "kind": e["kind"],
        "type": e.get("event_type") or e.get("alert_type"),
        "where": e.get("corridor") or e.get("severity"),
        "description": e["description"],
        "active": f"{fmt_time(e['start_min'])}-{fmt_time(e['end_min'])}",
        "travel_time_multiplier": float(e.get("delay_factor") or e.get("speed_factor")),
        "radius_miles": r,
        "miles_from_dc": round(haversine_miles(lat, lon, float(dc["lat"]), float(dc["lon"])), 1),
        "stops_inside_radius": inside,
    })
  events.sort(key=lambda e: -e["travel_time_multiplier"])
  return {"dc_id": dc["dc_id"], "delivery_date": str(date), "events": events}
