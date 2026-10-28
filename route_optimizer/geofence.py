"""Geofences and GPS: arrivals, departures, dwell and learned dock locations.

A geofence is a circle around a delivery point (or the DC yard). The engine
walks each truck's GPS pings in time order and opens a *visit* when a ping
falls inside a geofence and closes it when the truck is clearly outside
(exit radius = radius x EXIT_BUFFER, so GPS jitter at the edge does not split
one stop into two). Dwell is exit minus entry.

Telematics stop detection (``detect_stops``) is independent of geofences: it
finds where a truck actually stood still. Comparing those points with the
TMW master-data coordinates is how bad geocodes are found
(``learned_location``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Mapping, Optional, Sequence

from .geo import haversine_miles

METERS_PER_MILE = 1609.344
EXIT_BUFFER = 1.3        # exit radius multiplier (hysteresis)
MIN_VISIT_MIN = 3        # shorter visits are drive-throughs, not stops
STOPPED_MPH = 3.0        # at or below this speed the truck is standing still


@dataclass(frozen=True)
class Geofence:
  geofence_id: str
  entity_type: str   # CUSTOMER | DC
  entity_id: str
  lat: float
  lon: float
  radius_m: int


@dataclass(frozen=True)
class Ping:
  tractor_id: str
  minute: int
  lat: float
  lon: float
  speed_mph: float = 0.0
  route_id: Optional[str] = None


@dataclass
class Visit:
  tractor_id: str
  route_id: Optional[str]
  geofence: Geofence
  arrive_min: int
  depart_min: Optional[int]   # None while the truck is still inside
  last_seen_min: int

  @property
  def dwell_min(self) -> int:
    return (self.depart_min if self.depart_min is not None else self.last_seen_min) - self.arrive_min


def meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  return haversine_miles(lat1, lon1, lat2, lon2) * METERS_PER_MILE


def geofences_from_rows(rows: Iterable[Mapping]) -> list[Geofence]:
  return [
      Geofence(r["geofence_id"], r["entity_type"], r["entity_id"], float(r["center_lat"]), float(r["center_lon"]),
               int(r["radius_m"]))
      for r in rows
      if str(r.get("active", True)).lower() not in {"0", "false", "f"}
  ]


def pings_from_rows(rows: Iterable[Mapping]) -> list[Ping]:
  return [
      Ping(r["tractor_id"], int(r["ping_min"]), float(r["lat"]), float(r["lon"]), float(r.get("speed_mph") or 0),
           r.get("route_id"))
      for r in rows
  ]


def _nearest(p: Ping, fences: Sequence[Geofence], scale: float = 1.0) -> Optional[Geofence]:
  best, best_d = None, None
  for g in fences:
    # Cheap bounding check before the trig.
    if abs(p.lat - g.lat) > 0.05 or abs(p.lon - g.lon) > 0.06:
      continue
    d = meters(p.lat, p.lon, g.lat, g.lon)
    if d <= g.radius_m * scale and (best_d is None or d < best_d):
      best, best_d = g, d
  return best


def detect_visits(pings: Iterable[Ping], fences: Sequence[Geofence], as_of_min: Optional[int] = None) -> list[Visit]:
  """Geofence entries and exits per truck.

  A visit still open at the last ping (or at ``as_of_min``) has
  ``depart_min = None``: the truck is on site right now.
  """
  by_truck: dict[str, list[Ping]] = {}
  for p in pings:
    if as_of_min is None or p.minute <= as_of_min:
      by_truck.setdefault(p.tractor_id, []).append(p)
  visits: list[Visit] = []
  for tractor, seq in by_truck.items():
    seq.sort(key=lambda p: p.minute)
    current: Optional[Visit] = None
    for p in seq:
      if current is not None:
        g = current.geofence
        if meters(p.lat, p.lon, g.lat, g.lon) <= g.radius_m * EXIT_BUFFER:
          current.last_seen_min = p.minute
          continue
        current.depart_min = current.last_seen_min
        visits.append(current)
        current = None
      g = _nearest(p, fences)
      if g is not None:
        current = Visit(tractor, p.route_id, g, p.minute, None, p.minute)
    if current is not None:
      visits.append(current)
  return [v for v in visits if v.depart_min is None or v.dwell_min >= MIN_VISIT_MIN]


def detect_stops(pings: Sequence[Ping], min_minutes: int = 8) -> list[dict]:
  """Places where a truck stood still for at least ``min_minutes`` (any location)."""
  out = []
  seq = sorted(pings, key=lambda p: (p.tractor_id, p.minute))
  run: list[Ping] = []

  def flush():
    if run and run[-1].minute - run[0].minute >= min_minutes:
      out.append({
          "tractor_id": run[0].tractor_id, "start_min": run[0].minute, "end_min": run[-1].minute,
          "lat": median(p.lat for p in run), "lon": median(p.lon for p in run),
      })

  for p in seq:
    if run and (p.tractor_id != run[0].tractor_id or p.speed_mph > STOPPED_MPH):
      flush()
      run = []
    if p.speed_mph <= STOPPED_MPH:
      run.append(p)
  flush()
  return out


def learned_location(points: Sequence[tuple[float, float]]) -> Optional[tuple[float, float]]:
  """Median of observed parking positions, robust to the odd off-site stop."""
  if not points:
    return None
  return median(p[0] for p in points), median(p[1] for p in points)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
  x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
       - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1)))
  return (math.degrees(math.atan2(y, x)) + 360) % 360
