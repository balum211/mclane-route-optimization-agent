"""Generates a synthetic McLane-style SCM logistics dataset.

Four distribution centers (two grocery/convenience, two foodservice), their
stores and restaurants, fleet, drivers with hours of service, 7 days of open
orders, 60 days of delivery history, traffic and weather events, the cost
model, and the fixed "TMW static" routes the optimizer is benchmarked against.

Everything is deterministic for a given --seed. All names are fictional.

Usage:
  python data/generate_synthetic_data.py                 # CSVs + SQLite
  python data/generate_synthetic_data.py --start 2026-10-27 --days 7 --seed 7
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from route_optimizer.db.schema import TABLES, TABLES_BY_NAME, bigquery_schema_json, render_ddl  # noqa: E402
from route_optimizer.planning import (  # noqa: E402
    cost_model_from_row,
    depot_point,
    disruptions_from_rows,
    learned_service_minutes,
    static_tmw_plan,
    stops_from_rows,
    vehicles_from_rows,
)

DAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

DCS = [
    {
        "dc_id": "DC-TEMPLE-TX", "name": "McLane Temple (Grocery)", "business_unit": "GROCERY",
        "city": "Temple", "state": "TX", "lat": 31.0982, "lon": -97.3428, "dock_doors": 64,
        "dispatch_start_min": 120, "dispatch_end_min": 600, "timezone": "America/Chicago",
        "towns": [("Temple", 31.0982, -97.3428), ("Killeen", 31.1171, -97.7278), ("Waco", 31.5493, -97.1467),
                  ("Belton", 31.0560, -97.4645), ("Georgetown", 30.6333, -97.6770), ("Round Rock", 30.5083, -97.6789),
                  ("Austin", 30.2672, -97.7431), ("Bryan", 30.6744, -96.3700), ("Hillsboro", 32.0110, -97.1300),
                  ("Lampasas", 31.0638, -98.1817), ("Gatesville", 31.4352, -97.7439), ("Cameron", 30.8533, -96.9769)],
        "metro": ("Austin", 30.2672, -97.7431), "customers": 110,
    },
    {
        "dc_id": "DC-DALLAS-TX", "name": "McLane Foodservice Dallas", "business_unit": "FOODSERVICE",
        "city": "Carrollton", "state": "TX", "lat": 32.9537, "lon": -96.8903, "dock_doors": 48,
        "dispatch_start_min": 0, "dispatch_end_min": 480, "timezone": "America/Chicago",
        "towns": [("Dallas", 32.7767, -96.7970), ("Fort Worth", 32.7555, -97.3308), ("Plano", 33.0198, -96.6989),
                  ("Frisco", 33.1507, -96.8236), ("Denton", 33.2148, -97.1331), ("Arlington", 32.7357, -97.1081),
                  ("McKinney", 33.1972, -96.6398), ("Garland", 32.9126, -96.6389), ("Irving", 32.8140, -96.9489),
                  ("Mesquite", 32.7668, -96.5992), ("Rockwall", 32.9312, -96.4597), ("Mansfield", 32.5632, -97.1417)],
        "metro": ("Dallas", 32.7767, -96.7970), "customers": 95,
    },
    {
        "dc_id": "DC-CONCORD-NC", "name": "McLane Concord (Grocery)", "business_unit": "GROCERY",
        "city": "Concord", "state": "NC", "lat": 35.4088, "lon": -80.5795, "dock_doors": 56,
        "dispatch_start_min": 120, "dispatch_end_min": 600, "timezone": "America/New_York",
        "towns": [("Charlotte", 35.2271, -80.8431), ("Gastonia", 35.2621, -81.1873), ("Salisbury", 35.6709, -80.4742),
                  ("Statesville", 35.7826, -80.8873), ("Monroe", 34.9854, -80.5495), ("Rock Hill", 34.9249, -81.0251),
                  ("Hickory", 35.7332, -81.3412), ("Albemarle", 35.3501, -80.2001), ("Mooresville", 35.5849, -80.8101),
                  ("Lexington", 35.8240, -80.2534), ("High Point", 35.9557, -80.0053), ("Concord", 35.4088, -80.5795)],
        "metro": ("Charlotte", 35.2271, -80.8431), "customers": 105,
    },
    {
        "dc_id": "DC-PHOENIX-AZ", "name": "McLane Foodservice Phoenix", "business_unit": "FOODSERVICE",
        "city": "Goodyear", "state": "AZ", "lat": 33.4353, "lon": -112.3577, "dock_doors": 40,
        "dispatch_start_min": 0, "dispatch_end_min": 480, "timezone": "America/Phoenix",
        "towns": [("Phoenix", 33.4484, -112.0740), ("Scottsdale", 33.4942, -111.9261), ("Mesa", 33.4152, -111.8315),
                  ("Chandler", 33.3062, -111.8413), ("Glendale", 33.5387, -112.1860), ("Peoria", 33.5806, -112.2374),
                  ("Tempe", 33.4255, -111.9400), ("Gilbert", 33.3528, -111.7890), ("Surprise", 33.6292, -112.3679),
                  ("Buckeye", 33.3703, -112.5838), ("Casa Grande", 32.8795, -111.7573), ("Avondale", 33.4356, -112.3496)],
        "metro": ("Phoenix", 33.4484, -112.0740), "customers": 90,
    },
]

# Segment profiles: banners, receiving window, unload time, order size, temp mix.
SEGMENTS = {
    "CONVENIENCE": {
        "banners": ["Lone Star Fuel & Go", "Speedy Mart", "Corner Pantry", "Route 9 Express", "QuikFill"],
        "window": [(300, 720), (360, 840), (420, 900)], "service": (18, 30), "cases": (60, 180),
        "mix": (0.70, 0.20, 0.10), "days": [["MON", "WED", "FRI"], ["TUE", "THU", "SAT"]], "share": 0.62,
    },
    "GROCERY": {
        "banners": ["FreshWay Market", "Hometown Grocer", "Prairie Foods"],
        "window": [(240, 660), (300, 600)], "service": (35, 55), "cases": (280, 650),
        "mix": (0.55, 0.30, 0.15), "days": [["MON", "TUE", "WED", "THU", "FRI"]], "share": 0.23,
    },
    "MASS_MERCHANT": {
        "banners": ["ValueMax Supercenter", "BigBox Depot"],
        "window": [(180, 540)], "service": (45, 70), "cases": (450, 900),
        "mix": (0.75, 0.15, 0.10), "days": [["MON", "WED", "FRI"], ["TUE", "THU", "SAT"]], "share": 0.15,
    },
    "QSR": {
        "banners": ["Burger Ranch", "Taco Trail", "Coop Chicken Express", "Pizza Barn", "Sub Station 66"],
        "window": [(120, 480), (300, 600), (360, 660)], "service": (25, 45), "cases": (140, 360),
        "mix": (0.35, 0.30, 0.35), "days": [["MON", "WED", "FRI"], ["TUE", "THU", "SAT"]], "share": 0.78,
    },
    "CASUAL_DINING": {
        "banners": ["Mesquite Grill House", "Harbor Fish Co.", "Sunset Cantina"],
        "window": [(420, 660), (480, 720)], "service": (35, 55), "cases": (180, 420),
        "mix": (0.30, 0.40, 0.30), "days": [["TUE", "FRI"], ["MON", "THU"]], "share": 0.22,
    },
}

STREETS = ["Main St", "Commerce Dr", "Industrial Blvd", "Oak Ave", "Highway 6", "Market St",
           "Elm St", "Loop 340", "Parkway Dr", "Ranch Rd", "Central Expy", "Broadway"]
FIRST = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Drew", "Quinn",
         "Reese", "Cameron", "Logan", "Parker", "Rowan", "Sawyer", "Emerson", "Hayden", "Kendall", "Skyler"]
LAST = ["Garcia", "Johnson", "Nguyen", "Smith", "Patel", "Brown", "Lopez", "Williams", "Davis", "Martinez",
        "Wilson", "Anderson", "Thomas", "Moore", "Jackson", "White", "Harris", "Clark", "Lewis", "Young"]


def offset(lat: float, lon: float, miles: float, bearing_deg: float) -> tuple[float, float]:
  d = miles / 3958.8
  b = math.radians(bearing_deg)
  la1, lo1 = math.radians(lat), math.radians(lon)
  la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
  lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
  return round(math.degrees(la2), 6), round(math.degrees(lo2), 6)


def short(dc_id: str) -> str:
  return dc_id.split("-")[1][:3]


def gen_customers(rng: random.Random, dc: dict) -> list[dict]:
  segs = ["CONVENIENCE", "GROCERY", "MASS_MERCHANT"] if dc["business_unit"] == "GROCERY" else ["QSR", "CASUAL_DINING"]
  weights = [SEGMENTS[s]["share"] for s in segs]
  rows = []
  for i in range(1, dc["customers"] + 1):
    seg = rng.choices(segs, weights)[0]
    prof = SEGMENTS[seg]
    town, tlat, tlon = rng.choice(dc["towns"])
    lat, lon = offset(tlat, tlon, rng.uniform(0.3, 4.5), rng.uniform(0, 360))
    ws, we = rng.choice(prof["window"])
    banner = rng.choice(prof["banners"])
    store_no = rng.randint(100, 9999)
    urban = town == dc["metro"][0]
    rows.append({
        "customer_id": f"C-{short(dc['dc_id'])}-{i:04d}",
        "tmw_cmp_id": f"{''.join(w[0] for w in banner.split())[:4].upper()}{store_no:04d}"[:8],
        "dc_id": dc["dc_id"],
        "name": f"{banner} #{store_no}",
        "banner": banner,
        "segment": seg,
        "address": f"{rng.randint(100, 9800)} {rng.choice(STREETS)}",
        "city": town,
        "state": dc["state"],
        "lat": lat,
        "lon": lon,
        "window_start_min": ws,
        "window_end_min": we,
        "std_service_min": rng.randint(*prof["service"]),
        "hard_window": False,
        "key_drop": seg == "QSR" and rng.random() < 0.3,
        "requires_liftgate": seg in ("QSR", "CASUAL_DINING") and urban and rng.random() < 0.35,
        "max_vehicle_length_ft": 28 if (urban and rng.random() < 0.15) else 53,
        "priority_tier": rng.choices([1, 2, 3], [0.12, 0.28, 0.60])[0],
        "delivery_days": ",".join(rng.choice(prof["days"])),
    })
    # Big-box and strategic grocery accounts book dock appointments.
    r = rows[-1]
    r["hard_window"] = seg == "MASS_MERCHANT" or (seg == "GROCERY" and r["priority_tier"] == 1)
  return rows


def gen_fleet(rng: random.Random, dc: dict, peak_daily_cases: int):
  """Fleet sized so the busiest day fits at ~80% trailer fill, plus spares."""
  code = short(dc["dc_id"])
  foodservice = dc["business_unit"] == "FOODSERVICE"
  n_straight = 4 if foodservice else 2
  n_road = math.ceil(max(0, peak_daily_cases - n_straight * 500) / 1200) + 3
  tractors, trailers, drivers = [], [], []
  for i in range(1, n_road + 1):
    tractors.append({"tractor_id": f"TRC-{code}-{i:03d}", "dc_id": dc["dc_id"], "unit_type": "TRACTOR",
                     "mpg": round(rng.uniform(6.2, 7.6), 2),
                     "status": "MAINTENANCE" if i == n_road else "AVAILABLE"})
  for i in range(1, n_straight + 1):
    tractors.append({"tractor_id": f"STR-{code}-{i:03d}", "dc_id": dc["dc_id"], "unit_type": "STRAIGHT_TRUCK",
                     "mpg": round(rng.uniform(8.5, 10.5), 2), "status": "AVAILABLE"})
  n_multi = n_road - 2 if foodservice else n_road - 4
  for i in range(1, n_road + 1):
    multi = i <= n_multi
    trailers.append({"trailer_id": f"TRL-{code}-{i:03d}", "dc_id": dc["dc_id"],
                     "trailer_type": "MULTI_TEMP" if multi else "DRY", "length_ft": 53,
                     "capacity_cases": 1500 if multi else 1700, "capacity_cold_cases": 900 if multi else 0,
                     "capacity_lbs": 42000 if multi else 45000, "capacity_cube": 3300 if multi else 3800,
                     "has_liftgate": False, "status": "AVAILABLE"})
  for i in range(1, n_straight + 1):
    trailers.append({"trailer_id": f"BOX-{code}-{i:03d}", "dc_id": dc["dc_id"], "trailer_type": "STRAIGHT_REEFER",
                     "length_ft": 26, "capacity_cases": 650, "capacity_cold_cases": 450, "capacity_lbs": 16000,
                     "capacity_cube": 1500, "has_liftgate": True, "status": "AVAILABLE"})
  for i in range(1, n_road + n_straight + 3):
    partial = rng.random() < 0.15
    drivers.append({"driver_id": f"DRV-{code}-{i:03d}", "dc_id": dc["dc_id"],
                    "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                    "hos_drive_remaining_min": 540 if partial else 660,
                    "hos_duty_remaining_min": 720 if partial else 840,
                    "shift_start_min": dc["dispatch_start_min"] + rng.choice([0, 0, 30, 60, 120]),
                    "cdl_class": "A" if i <= n_road + 1 else "B",
                    "status": "PTO" if rng.random() < 0.08 else "AVAILABLE"})
  return tractors, trailers, drivers


def gen_orders(rng: random.Random, dc: dict, customers: list[dict], start: dt.date, days: int, seq: list[int]):
  rows = []
  code = short(dc["dc_id"])
  for d in range(days):
    date = start + dt.timedelta(days=d)
    day = DAY_CODES[date.weekday()]
    n = 0
    for c in customers:
      if day not in c["delivery_days"].split(","):
        continue
      prof = SEGMENTS[c["segment"]]
      total = rng.randint(*prof["cases"])
      dry_r, chill_r, _ = prof["mix"]
      if c["segment"] == "CONVENIENCE" and rng.random() < 0.45:
        dry, chill, frozen = total, 0, 0  # ambient-only replenishment
      else:
        jitter = rng.uniform(-0.08, 0.08)
        dry = int(total * max(0.1, dry_r + jitter))
        chill = int(total * chill_r)
        frozen = max(0, total - dry - chill)
      n += 1
      seq[0] += 1
      rows.append({
          "order_id": f"O-{date:%Y%m%d}-{code}-{n:04d}",
          "tmw_ord_hdrnumber": seq[0],
          "dc_id": dc["dc_id"],
          "customer_id": c["customer_id"],
          "delivery_date": date.isoformat(),
          "dry_cases": dry,
          "chill_cases": chill,
          "frozen_cases": frozen,
          "weight_lbs": int(dry * rng.uniform(14, 22) + chill * rng.uniform(16, 24) + frozen * rng.uniform(18, 28)),
          "cube_ft3": round(total * rng.uniform(1.4, 2.0), 1),
          "priority": rng.choices(["STANDARD", "HOT", "FLEX"], [0.85, 0.05, 0.10])[0],
          "status": "OPEN",
      })
  return rows


def gen_history(rng: random.Random, dc: dict, customers: list[dict], end: dt.date, days: int):
  rows = []
  # Each customer has a "true" dwell that differs from TMS master data, which
  # is the gap learned_service_minutes() closes.
  truth = {c["customer_id"]: c["std_service_min"] * rng.uniform(0.85, 1.6) for c in customers}
  dock_busy = {c["customer_id"]: rng.random() < 0.12 for c in customers}
  n = 0
  for d in range(days, 0, -1):
    date = end - dt.timedelta(days=d)
    day = DAY_CODES[date.weekday()]
    for c in customers:
      if day not in c["delivery_days"].split(","):
        continue
      n += 1
      planned = rng.randint(c["window_start_min"], max(c["window_start_min"], c["window_end_min"] - 60))
      exc = rng.choices(["NONE", "TRAFFIC", "WEATHER", "DOCK_BUSY", "LATE_DISPATCH", "REFUSED"],
                        [0.78, 0.09, 0.03, 0.06 + (0.1 if dock_busy[c["customer_id"]] else 0), 0.035, 0.005])[0]
      delay = {"NONE": rng.gauss(0, 12), "TRAFFIC": rng.uniform(20, 95), "WEATHER": rng.uniform(15, 80),
               "DOCK_BUSY": rng.uniform(5, 40), "LATE_DISPATCH": rng.uniform(30, 120), "REFUSED": rng.uniform(0, 20)}[exc]
      actual = int(planned + delay)
      dwell = int(max(8, rng.gauss(truth[c["customer_id"]], truth[c["customer_id"]] * 0.18)
                      + (rng.uniform(10, 35) if exc == "DOCK_BUSY" else 0)))
      prof = SEGMENTS[c["segment"]]
      rows.append({
          "delivery_id": f"H-{short(dc['dc_id'])}-{date:%Y%m%d}-{n:06d}",
          "customer_id": c["customer_id"],
          "dc_id": dc["dc_id"],
          "delivery_date": date.isoformat(),
          "planned_arrival_min": planned,
          "actual_arrival_min": actual,
          "dwell_min": dwell,
          "cases": rng.randint(*prof["cases"]),
          "on_time": c["window_start_min"] <= actual <= c["window_end_min"],
          "exception_code": exc,
      })
  return rows


def gen_events(start: dt.date, days: int):
  d = lambda k: (start + dt.timedelta(days=k)).isoformat()
  traffic = [
      ("TRF-0001", d(0), "CLOSURE", "I-35 N", "Bridge inspection closes northbound lanes south of Waco", 31.47, -97.17, 7, 300, 630, 2.4),
      ("TRF-0002", d(0), "ACCIDENT", "I-635 E", "Multi-vehicle crash near Garland, 2 right lanes blocked", 32.91, -96.66, 5, 360, 540, 1.9),
      ("TRF-0003", d(0), "CONSTRUCTION", "I-10 E", "Night paving between Tempe and Chandler running late", 33.37, -111.92, 5, 240, 600, 1.5),
      ("TRF-0004", d(1), "CONGESTION", "I-85 S", "Heavy congestion through Charlotte, event traffic", 35.25, -80.82, 9, 360, 600, 1.6),
      ("TRF-0005", d(1), "ACCIDENT", "SH-121", "Overturned trailer near Frisco", 33.12, -96.82, 4, 330, 510, 2.1),
      ("TRF-0006", d(2), "CLOSURE", "US-190", "Full closure for utility work between Killeen and Belton", 31.09, -97.60, 5, 240, 720, 2.2),
      ("TRF-0007", d(3), "CONSTRUCTION", "Loop 202", "Lane restrictions near Gilbert", 33.36, -111.77, 4, 300, 660, 1.4),
  ]
  # Weekday morning rush in each metro core.
  metros = [(dc["dc_id"], dc["metro"]) for dc in DCS]
  k = 8
  for day in range(days):
    date = start + dt.timedelta(days=day)
    if date.weekday() >= 5:
      continue
    for _, (city, lat, lon) in metros:
      k += 1
      traffic.append((f"TRF-{k:04d}", date.isoformat(), "CONGESTION", f"{city} core",
                      f"Recurring AM peak congestion in {city}", lat, lon, 9, 390, 540, 1.35))
  weather = [
      ("WX-0001", d(1), "THUNDERSTORM", "WARNING", "Severe storms with hail, Austin to Round Rock", 30.45, -97.70, 18, 300, 600, 1.35),
      ("WX-0002", d(0), "WIND", "ADVISORY", "Dense fog along I-85 corridor until mid-morning", 35.30, -80.95, 22, 180, 570, 1.25),
      ("WX-0003", d(2), "WIND", "WARNING", "Dust storm (haboob) west Valley, visibility near zero", 33.45, -112.45, 15, 420, 600, 1.6),
      ("WX-0004", d(3), "FLOOD", "WATCH", "Flash flood watch Dallas-Fort Worth", 32.80, -97.10, 20, 0, 720, 1.2),
  ]
  t_cols = TABLES_BY_NAME["traffic_events"].column_names
  w_cols = TABLES_BY_NAME["weather_events"].column_names
  return [dict(zip(t_cols, t)) for t in traffic], [dict(zip(w_cols, w)) for w in weather]


def gen_route_events(dc: dict, customers: list[dict], orders: list[dict], start: dt.date) -> list[dict]:
  """Day-one disruption scenarios that the event handler re-plans around."""
  code = short(dc["dc_id"])
  date = start.isoformat()
  today = [o for o in orders if o["delivery_date"] == date]
  ordering = {o["customer_id"] for o in today}
  idle = [c for c in customers if c["customer_id"] not in ordering]
  base = {"dc_id": dc["dc_id"], "event_date": date, "tractor_id": None, "customer_id": None, "order_id": None,
          "delay_min": None, "lat": None, "lon": None, "radius_miles": None, "delay_factor": None, "payload": None}
  ev = []

  def add(n, minute, etype, source, description, **kw):
    ev.append({**base, "event_id": f"EVT-{code}-{n:02d}", "event_min": minute, "event_type": etype,
               "source": source, "description": description, **kw})

  if code == "TEM":
    add(1, 465, "BREAKDOWN", "TELEMATICS", "Air-brake fault code, unit out of service on US-190 near Belton",
        tractor_id=f"TRC-{code}-003", lat=31.07, lon=-97.45)
    add(2, 435, "DELAY", "TELEMATICS", "Truck stopped in I-35 N closure queue south of Waco",
        tractor_id=f"TRC-{code}-005", delay_min=45)
    if idle:
      c = idle[0]
      add(3, 380, "ORDER_ADDED", "TMS", f"Emergency fill-in order from {c['name']} (cooler failure, needs product today)",
          customer_id=c["customer_id"], payload={"dry_cases": 60, "chill_cases": 45, "frozen_cases": 20, "priority": "HOT"})
    if today:
      add(4, 330, "ORDER_CANCELLED", "CUSTOMER", "Store closed for remodel, order cancelled", order_id=today[-1]["order_id"],
          customer_id=today[-1]["customer_id"])
  elif code == "DAL":
    if today:
      add(1, 420, "NO_SHOW", "DRIVER_APP", "Restaurant not open at arrival, no key-drop on file",
          customer_id=today[0]["customer_id"], order_id=today[0]["order_id"])
    add(2, 410, "REEFER_TEMP_ALERT", "TELEMATICS", "Frozen compartment reading 18F and rising (setpoint -10F)",
        tractor_id=f"TRC-{code}-002", payload={"zone": "FROZEN", "temp_f": 18, "setpoint_f": -10})
  elif code == "PHO":
    add(1, 390, "ROAD_CLOSURE", "TRAFFIC_FEED", "US-60 closed both directions at Mesa Dr after a fuel spill",
        lat=33.40, lon=-111.83, radius_miles=4.0, delay_factor=3.0)
  elif code == "CON":
    add(1, 480, "DELAY", "DRIVER_APP", "Dock congestion at previous stop, driver waiting for a door",
        tractor_id=f"TRC-{code}-004", delay_min=25)
  return ev


def gen_costs(dc: dict, rng: random.Random) -> dict:
  return {
      "dc_id": dc["dc_id"],
      "cost_per_mile_usd": round(rng.uniform(0.85, 1.05), 2),
      "fuel_price_usd_gal": round(rng.uniform(3.55, 4.25), 2),
      "driver_cost_per_hour_usd": round(rng.uniform(34, 44), 2),
      "overtime_multiplier": 1.5,
      "fixed_cost_per_route_usd": 185.0,
      "late_penalty_usd": 150.0 if dc["business_unit"] == "GROCERY" else 225.0,
      "co2_kg_per_gal": 10.21,
  }


def build_static_routes(dc, customers, fleet, orders, history, traffic, weather, costs, start, days):
  tractors, trailers, drivers = fleet
  by_id = {c["customer_id"]: c for c in customers}
  service = {c["customer_id"]: c["std_service_min"] for c in customers}  # TMW uses master data
  vehicles = vehicles_from_rows(dc, tractors, trailers, drivers)
  route_rows, stop_rows = [], []
  for k in range(days):
    date = (start + dt.timedelta(days=k)).isoformat()
    day_orders = [o for o in orders if o["delivery_date"] == date]
    if not day_orders:
      continue
    stops = stops_from_rows(day_orders, by_id, service)
    dis = disruptions_from_rows([t for t in traffic if t["event_date"] == date],
                                [w for w in weather if w["event_date"] == date])
    plan = static_tmw_plan(depot_point(dc), stops, vehicles, cost_model_from_row(costs), dis)
    for i, r in enumerate(plan.routes, start=1):
      rid = f"R-{date.replace('-', '')}-{short(dc['dc_id'])}-S{i:02d}"
      route_rows.append({
          "route_id": rid, "plan_id": None, "source": "TMW_STATIC", "dc_id": dc["dc_id"], "route_date": date,
          "tractor_id": r.vehicle.tractor_id, "trailer_id": r.vehicle.trailer_id, "driver_id": r.vehicle.driver_id,
          "depart_min": r.depart_min, "return_min": r.return_min, "stop_count": len(r.stops),
          "total_miles": round(r.total_miles, 1), "total_duration_min": r.duration_min, "total_cases": r.cases,
          "est_cost_usd": round(r.cost_usd, 2), "late_stops": r.late_stops, "status": "PLANNED",
      })
      for s in r.stops:
        stop_rows.append({
            "route_id": rid, "stop_seq": s.seq, "order_id": s.order_id, "customer_id": s.customer_id,
            "eta_min": s.arrival_min, "etd_min": s.departure_min, "miles_from_prev": round(s.miles_from_prev, 1),
            "window_ok": s.late_min == 0,
        })
  return route_rows, stop_rows


def write_csv(path: Path, table: str, rows: list[dict]):
  cols = TABLES_BY_NAME[table].column_names
  with path.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
      w.writerow({
          k: ("true" if v is True else "false" if v is False else json.dumps(v) if isinstance(v, (dict, list)) else v)
          for k, v in r.items()
      })


def write_sqlite(path: Path, data: dict[str, list[dict]]):
  if path.exists():
    path.unlink()
  con = sqlite3.connect(path)
  con.executescript(render_ddl("sqlite"))
  for table in TABLES:
    rows = data.get(table.name, [])
    if not rows:
      continue
    cols = table.column_names
    con.executemany(
        f"INSERT INTO {table.name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [[(json.dumps(r.get(c)) if isinstance(r.get(c), (dict, list)) else r.get(c)) for c in cols] for r in rows],
    )
  con.commit()
  con.close()


def write_schema_files(folder: Path):
  """Renders DDL for every engine plus BigQuery JSON schemas from schema.py."""
  folder.mkdir(parents=True, exist_ok=True)
  (folder / "sqlite.sql").write_text(render_ddl("sqlite"))
  (folder / "alloydb.sql").write_text(
      "CREATE SCHEMA IF NOT EXISTS mclane_routing;\nSET search_path TO mclane_routing;\n\n" + render_ddl("postgres"))
  (folder / "bigquery.sql").write_text(
      "-- Replace YOUR_PROJECT with your project id, or run data/load_bigquery.py which does it for you.\n"
      "CREATE SCHEMA IF NOT EXISTS `YOUR_PROJECT.mclane_routing` OPTIONS(location='US');\n\n"
      + render_ddl("bigquery", "YOUR_PROJECT.mclane_routing."))
  json_dir = folder / "bigquery_json"
  json_dir.mkdir(exist_ok=True)
  for t in TABLES:
    (json_dir / f"{t.name}.json").write_text(json.dumps(bigquery_schema_json(t), indent=2) + "\n")


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--start", default="2026-10-27", help="First delivery date of the planning horizon")
  ap.add_argument("--days", type=int, default=7, help="Days of open orders")
  ap.add_argument("--history-days", type=int, default=60)
  ap.add_argument("--seed", type=int, default=27)
  ap.add_argument("--out", default=str(ROOT / "data" / "synthetic"))
  ap.add_argument("--sqlite", default=str(ROOT / "data" / "mclane_routing.db"))
  args = ap.parse_args(argv)

  rng = random.Random(args.seed)
  start = dt.date.fromisoformat(args.start)
  out = Path(args.out)
  out.mkdir(parents=True, exist_ok=True)

  data: dict[str, list[dict]] = {t.name: [] for t in TABLES}
  traffic, weather = gen_events(start, args.days)
  data["traffic_events"], data["weather_events"] = traffic, weather
  seq = [5_100_000]
  for dc in DCS:
    dc_row = {k: v for k, v in dc.items() if k in TABLES_BY_NAME["distribution_centers"].column_names}
    data["distribution_centers"].append(dc_row)
    customers = gen_customers(rng, dc)
    orders = gen_orders(rng, dc, customers, start, args.days, seq)
    daily: dict[str, int] = {}
    for o in orders:
      daily[o["delivery_date"]] = daily.get(o["delivery_date"], 0) + o["dry_cases"] + o["chill_cases"] + o["frozen_cases"]
    fleet = gen_fleet(rng, dc, max(daily.values()))
    history = gen_history(rng, dc, customers, start, args.history_days)
    costs = gen_costs(dc, rng)
    routes, stops = build_static_routes(dc_row, customers, fleet, orders, history, traffic, weather, costs, start, args.days)
    data["customers"] += customers
    data["tractors"] += fleet[0]
    data["trailers"] += fleet[1]
    data["drivers"] += fleet[2]
    data["orders"] += orders
    data["delivery_history"] += history
    data["cost_parameters"].append(costs)
    data["route_events"] += gen_route_events(dc, customers, orders, start)
    data["routes"] += routes
    data["route_stops"] += stops

  for name, rows in data.items():
    write_csv(out / f"{name}.csv", name, rows)
  write_sqlite(Path(args.sqlite), data)
  write_schema_files(ROOT / "data" / "schema")

  print(f"Wrote {sum(len(v) for v in data.values()):,} rows to {out} and {args.sqlite}")
  for name, rows in data.items():
    print(f"  {name:<24}{len(rows):>8,}")


if __name__ == "__main__":
  main()
