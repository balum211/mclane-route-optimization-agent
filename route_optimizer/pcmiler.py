"""Trimble PC*MILER mileage: the mileage of record for McLane in TMW.

TMW rates, pays drivers and bills on PC*MILER miles, so every route the agent
saves or sends to TMW carries PC*MILER miles next to the optimizer's own
matrix miles.

Two modes:

* **Live** (``PCMILER_API_KEY`` set): calls PC*MILER Web Services
  ``route/routeReports`` with a Mileage report for the full stop sequence,
  one request per route. Responses are cached per stop sequence.
* **Emulated** (no key, the default): an offline estimate of PC*MILER
  practical miles, great-circle distance times a truck-route circuity factor
  with a small deterministic per-lane adjustment. Good enough for the demo
  and tests. It is labelled ``PCMILER_EMULATED`` everywhere so nobody
  mistakes it for real PC*MILER output.

``TRAVEL_PROVIDER=pcmiler`` additionally builds the solver's distance matrix
from PC*MILER (pairwise, cached; capped at ``PCMILER_MATRIX_MAX_POINTS``).

Check the request and response fields against the PC*MILER Web Services
developer guide for your account (https://developer.trimblemaps.com/restful-apis/)
before going live; adapt ``_parse_report`` if your version differs.
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Sequence

from .geo import Point, haversine_miles

DEFAULT_BASE_URL = "https://pcmiler.alk.com/apis/rest/v1.0/Service.svc"
# Truck-route circuity per routing type (road miles per straight-line mile).
CIRCUITY = {"PRACTICAL": 1.20, "SHORTEST": 1.14, "FASTEST": 1.24}
PRACTICAL_MPH = 47.0


@dataclass(frozen=True)
class Mileage:
  total_miles: float
  leg_miles: tuple[float, ...]
  total_hours: Optional[float]
  source: str            # PCMILER | PCMILER_EMULATED
  routing_type: str


def routing_type() -> str:
  return os.getenv("PCMILER_ROUTING_TYPE", "PRACTICAL").strip().upper() or "PRACTICAL"


def is_live() -> bool:
  return bool(os.getenv("PCMILER_API_KEY", "").strip())


def _lane_adjustment(a: Point, b: Point) -> float:
  """Deterministic +-4% per lane, so emulated miles are not a pure scalar of haversine."""
  key = f"{a.lat:.4f},{a.lon:.4f}>{b.lat:.4f},{b.lon:.4f}".encode()
  h = int(hashlib.blake2b(key, digest_size=4).hexdigest(), 16) / 0xFFFFFFFF
  return 0.96 + 0.08 * h


def emulated_leg_miles(a: Point, b: Point, rtype: str = "PRACTICAL") -> float:
  d = haversine_miles(a.lat, a.lon, b.lat, b.lon)
  if d == 0:
    return 0.0
  return d * CIRCUITY.get(rtype, CIRCUITY["PRACTICAL"]) * _lane_adjustment(a, b)


def _hours(text) -> Optional[float]:
  """PC*MILER reports time as 'h:mm' strings; accept numbers too."""
  if text is None:
    return None
  if isinstance(text, (int, float)):
    return float(text)
  s = str(text).strip()
  if ":" in s:
    h, m = s.split(":")[:2]
    return int(h) + int(m) / 60
  try:
    return float(s)
  except ValueError:
    return None


def _parse_report(data) -> tuple[list[float], Optional[float]]:
  """Leg miles and total hours from a routeReports Mileage response."""
  reports = data if isinstance(data, list) else [data]
  for rep in reports:
    lines = rep.get("ReportLines") or []
    if lines:
      legs = [float(str(x.get("LMiles", 0)).replace(",", "")) for x in lines][1:]
      return legs, _hours(lines[-1].get("THours"))
    if "TDistance" in rep:
      return [float(rep["TDistance"])], float(rep.get("TMinutes", 0)) / 60
  raise ValueError("PC*MILER response has no ReportLines or TDistance")


@lru_cache(maxsize=4096)
def _live_route(coords: tuple[tuple[float, float], ...], rtype: str) -> tuple[tuple[float, ...], Optional[float]]:
  import requests  # lazy: the offline path has no network dependency

  base = os.getenv("PCMILER_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
  params = {
      "stops": ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords),
      "reports": "Mileage",
      "routeType": rtype.title(),
      "vehType": "Truck",
      "region": os.getenv("PCMILER_REGION", "NA"),
      "dataVer": os.getenv("PCMILER_DATA_VERSION", "Current"),
  }
  resp = requests.get(f"{base}/route/routeReports", params=params,
                      headers={"Authorization": os.environ["PCMILER_API_KEY"]}, timeout=30)
  resp.raise_for_status()
  legs, hours = _parse_report(resp.json())
  return tuple(legs), hours


def route_mileage(points: Sequence[Point], rtype: Optional[str] = None) -> Mileage:
  """PC*MILER miles for a stop sequence (DC, stops..., DC)."""
  rtype = (rtype or routing_type()).upper()
  if len(points) < 2:
    return Mileage(0.0, (), 0.0, "PCMILER" if is_live() else "PCMILER_EMULATED", rtype)
  if is_live():
    try:
      legs, hours = _live_route(tuple((p.lat, p.lon) for p in points), rtype)
      if len(legs) == len(points) - 1:
        return Mileage(round(sum(legs), 1), tuple(round(x, 1) for x in legs), hours, "PCMILER", rtype)
    except Exception:  # never fail a plan on the mileage service; fall back and label it
      pass
  legs = tuple(round(emulated_leg_miles(a, b, rtype), 1) for a, b in zip(points, points[1:]))
  return Mileage(round(sum(legs), 1), legs, round(sum(legs) / PRACTICAL_MPH, 2), "PCMILER_EMULATED", rtype)


def matrix(points: Sequence[Point], rtype: Optional[str] = None) -> tuple[list[list[float]], list[list[float]]]:
  """Pairwise PC*MILER miles and minutes for the solver (TRAVEL_PROVIDER=pcmiler)."""
  rtype = (rtype or routing_type()).upper()
  n = len(points)
  miles = [[0.0] * n for _ in range(n)]
  minutes = [[0.0] * n for _ in range(n)]
  cap = int(os.getenv("PCMILER_MATRIX_MAX_POINTS", "60"))
  pairs = [(i, j) for i in range(n) for j in range(n) if i != j]

  def one(ij):
    i, j = ij
    if is_live() and n <= cap:
      m = route_mileage([points[i], points[j]], rtype)
    else:
      d = emulated_leg_miles(points[i], points[j], rtype)
      m = Mileage(d, (d,), d / PRACTICAL_MPH, "PCMILER_EMULATED", rtype)
    return i, j, m

  with ThreadPoolExecutor(max_workers=8 if is_live() else 1) as pool:
    for i, j, m in pool.map(one, pairs):
      miles[i][j] = m.total_miles
      minutes[i][j] = (m.total_hours if m.total_hours is not None else m.total_miles / PRACTICAL_MPH) * 60
  return miles, minutes


def stamp_routes(routes, depot: Point) -> None:
  """Sets ``pcmiler_miles`` on each RouteResult and ``pcmiler_leg_miles`` on its stops."""
  for r in routes:
    origin = r.vehicle.start_point or depot
    pts = [origin] + [Point(s.order_id, s.lat, s.lon) for s in r.stops] + [depot]
    m = route_mileage(pts)
    r.pcmiler_miles = m.total_miles
    r.mileage_source = m.source
    for s, leg in zip(r.stops, m.leg_miles):
      s.pcmiler_leg_miles = leg
