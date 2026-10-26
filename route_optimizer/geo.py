"""Travel model: distances, drive times and traffic/weather impact.

The default provider estimates road miles from great-circle distance with a
circuity factor and applies a speed profile. That keeps the demo fully offline
and deterministic. Set ``TRAVEL_PROVIDER=google_routes`` (plus
``GOOGLE_MAPS_API_KEY``) to pull real road distances and durations from the
Google Maps Routes API ``computeRouteMatrix`` endpoint instead.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

EARTH_RADIUS_MILES = 3958.8
ROAD_CIRCUITY = 1.22          # road miles per straight-line mile
HIGHWAY_MPH = 52.0            # loaded tractor on interstate / US highways
URBAN_MPH = 28.0              # inside the metro core
URBAN_RADIUS_MILES = 12.0     # distance from a DC treated as metro core


@dataclass(frozen=True)
class Point:
  key: str
  lat: float
  lon: float


@dataclass(frozen=True)
class Disruption:
  """A traffic or weather event that slows travel inside a radius."""

  event_id: str
  lat: float
  lon: float
  radius_miles: float
  start_min: int
  end_min: int
  factor: float  # travel-time multiplier (>1 slows down)
  description: str = ""


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  p1, p2 = math.radians(lat1), math.radians(lat2)
  dp = p2 - p1
  dl = math.radians(lon2 - lon1)
  a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
  return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def road_miles(a: Point, b: Point) -> float:
  return haversine_miles(a.lat, a.lon, b.lat, b.lon) * ROAD_CIRCUITY


def base_drive_minutes(a: Point, b: Point, depot: Point | None = None) -> float:
  """Free-flow drive time, slower for legs that start or end in the metro core."""
  miles = road_miles(a, b)
  if miles == 0:
    return 0.0
  speed = HIGHWAY_MPH
  if depot is not None:
    near = [
        haversine_miles(p.lat, p.lon, depot.lat, depot.lon) < URBAN_RADIUS_MILES
        for p in (a, b)
    ]
    if all(near):
      speed = URBAN_MPH
    elif any(near):
      speed = (URBAN_MPH + HIGHWAY_MPH) / 2
  return miles / speed * 60.0


def _segment_hits(a: Point, b: Point, d: Disruption) -> bool:
  """True when the straight segment a->b passes within the disruption radius."""
  for t in (0.0, 0.25, 0.5, 0.75, 1.0):
    lat = a.lat + (b.lat - a.lat) * t
    lon = a.lon + (b.lon - a.lon) * t
    if haversine_miles(lat, lon, d.lat, d.lon) <= d.radius_miles:
      return True
  return False


def disruption_factor(
    a: Point,
    b: Point,
    disruptions: Iterable[Disruption],
    planning_window: tuple[int, int] = (0, 24 * 60),
) -> tuple[float, list[str]]:
  """Worst travel-time multiplier for a leg and the events that caused it.

  Disruptions are applied when their active window overlaps the planning
  window. The solver uses static arc costs, so a disruption slows every
  overlapping leg rather than only the minutes it is active; that is a
  deliberately conservative choice for dispatch planning.
  """
  factor = 1.0
  hits: list[str] = []
  lo, hi = planning_window
  for d in disruptions:
    if d.end_min < lo or d.start_min > hi:
      continue
    if _segment_hits(a, b, d):
      hits.append(d.event_id)
      factor = max(factor, d.factor)
  return factor, hits


@dataclass
class TravelMatrix:
  keys: list[str]
  miles: list[list[float]]
  minutes: list[list[int]]
  impacted_legs: dict[tuple[str, str], list[str]]

  def index(self, key: str) -> int:
    return self.keys.index(key)


def build_matrix(
    points: Sequence[Point],
    depot: Point,
    disruptions: Sequence[Disruption] = (),
    planning_window: tuple[int, int] = (0, 24 * 60),
) -> TravelMatrix:
  provider = os.getenv("TRAVEL_PROVIDER", "haversine").lower()
  if provider == "google_routes":
    miles, minutes = _google_routes_matrix(points)
  else:
    n = len(points)
    miles = [[0.0] * n for _ in range(n)]
    minutes = [[0.0] * n for _ in range(n)]
    for i, a in enumerate(points):
      for j, b in enumerate(points):
        if i != j:
          miles[i][j] = road_miles(a, b)
          minutes[i][j] = base_drive_minutes(a, b, depot)

  impacted: dict[tuple[str, str], list[str]] = {}
  int_minutes = []
  for i, a in enumerate(points):
    row = []
    for j, b in enumerate(points):
      m = minutes[i][j]
      if i != j and disruptions:
        f, hits = disruption_factor(a, b, disruptions, planning_window)
        if hits:
          impacted[(a.key, b.key)] = hits
          m *= f
      row.append(int(round(m)))
    int_minutes.append(row)
  return TravelMatrix(
      keys=[p.key for p in points],
      miles=[[round(x, 2) for x in r] for r in miles],
      minutes=int_minutes,
      impacted_legs=impacted,
  )


def _google_routes_matrix(points: Sequence[Point]):
  """Road distance/duration matrix from the Google Maps Routes API.

  computeRouteMatrix accepts up to 625 elements per request, so the matrix is
  fetched in 25x25 blocks. Traffic-aware routing is left off to keep results
  stable for planning; flip ``routingPreference`` to ``TRAFFIC_AWARE`` for
  live re-optimization.
  """
  import requests  # imported lazily so the offline path has no dependency

  api_key = os.environ["GOOGLE_MAPS_API_KEY"]
  url = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
  headers = {
      "X-Goog-Api-Key": api_key,
      "X-Goog-FieldMask": "originIndex,destinationIndex,distanceMeters,duration,condition",
      "Content-Type": "application/json",
  }
  n = len(points)
  miles = [[0.0] * n for _ in range(n)]
  minutes = [[0.0] * n for _ in range(n)]

  def wp(p: Point):
    return {"waypoint": {"location": {"latLng": {"latitude": p.lat, "longitude": p.lon}}}}

  block = 25
  for oi in range(0, n, block):
    for di in range(0, n, block):
      origins = points[oi : oi + block]
      dests = points[di : di + block]
      body = {
          "origins": [wp(p) for p in origins],
          "destinations": [wp(p) for p in dests],
          "travelMode": "DRIVE",
          "routingPreference": "TRAFFIC_UNAWARE",
      }
      resp = requests.post(url, json=body, headers=headers, timeout=60)
      resp.raise_for_status()
      for el in resp.json():
        i = oi + el.get("originIndex", 0)
        j = di + el.get("destinationIndex", 0)
        if el.get("condition") != "ROUTE_EXISTS":
          miles[i][j] = road_miles(points[i], points[j])
          minutes[i][j] = miles[i][j] / HIGHWAY_MPH * 60
          continue
        miles[i][j] = el.get("distanceMeters", 0) / 1609.344
        minutes[i][j] = float(el.get("duration", "0s").rstrip("s")) / 60.0
  return miles, minutes


def fmt_time(minutes: int | float | None) -> str:
  """Minutes after midnight -> HH:MM (handles past-midnight values)."""
  if minutes is None:
    return "--:--"
  m = int(round(minutes))
  day, m = divmod(m, 24 * 60)
  s = f"{m // 60:02d}:{m % 60:02d}"
  return s + (f" (+{day}d)" if day else "")


def parse_time(value: str | int) -> int:
  """HH:MM or minutes -> minutes after midnight."""
  if isinstance(value, int):
    return value
  value = str(value).strip()
  if value.isdigit():
    return int(value)
  hh, mm = value.split(":")[:2]
  return int(hh) * 60 + int(mm)
