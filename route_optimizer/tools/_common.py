"""Shared loaders used by the agent tools."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

from ..db.repository import get_repository
from ..geo import Disruption, Point, haversine_miles
from ..optimizer import CostModel, Stop, Vehicle
from ..planning import (
    cost_model_from_row,
    depot_point,
    disruptions_from_rows,
    learned_service_minutes,
    stops_from_rows,
    vehicles_from_rows,
)

DISRUPTION_RADIUS_MILES = 220  # events farther than this from the DC are ignored


class ToolError(ValueError):
  """Raised for bad tool input; the message is returned to the model."""


def as_date(value: str) -> dt.date:
  try:
    return dt.date.fromisoformat(str(value).strip()[:10])
  except ValueError as e:
    raise ToolError(f"Expected a date like 2026-10-27, got {value!r}") from e


def new_id(prefix: str) -> str:
  return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def now_ts() -> str:
  return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def q(sql: str, **params):
  return get_repository().query(sql, params)


def load_dc(dc_id: str) -> dict:
  rows = q("SELECT * FROM distribution_centers WHERE dc_id = :dc_id", dc_id=dc_id.strip().upper())
  if not rows:
    known = [r["dc_id"] for r in q("SELECT dc_id FROM distribution_centers ORDER BY dc_id")]
    raise ToolError(f"Unknown DC {dc_id!r}. Known DCs: {', '.join(known)}")
  return rows[0]


def load_customers(dc_id: str) -> dict[str, dict]:
  return {r["customer_id"]: r for r in q("SELECT * FROM customers WHERE dc_id = :dc_id", dc_id=dc_id)}


def load_learned_service(dc_id: str) -> dict[str, int]:
  return learned_service_minutes(
      q("SELECT customer_id, dwell_min FROM delivery_history WHERE dc_id = :dc_id", dc_id=dc_id)
  )


def load_disruptions(dc: dict, date: dt.date) -> tuple[list[Disruption], list[dict]]:
  traffic = q("SELECT * FROM traffic_events WHERE event_date = :d", d=date)
  weather = q("SELECT * FROM weather_events WHERE event_date = :d", d=date)
  near = lambda r: haversine_miles(float(r["lat"]), float(r["lon"]), float(dc["lat"]), float(dc["lon"])) <= DISRUPTION_RADIUS_MILES
  traffic = [t for t in traffic if near(t)]
  weather = [w for w in weather if near(w)]
  raw = [{"kind": "traffic", **t} for t in traffic] + [{"kind": "weather", **w} for w in weather]
  return disruptions_from_rows(traffic, weather), raw


def load_costs(dc_id: str) -> CostModel:
  rows = q("SELECT * FROM cost_parameters WHERE dc_id = :dc_id", dc_id=dc_id)
  return cost_model_from_row(rows[0] if rows else None)


def load_vehicles(dc: dict) -> list[Vehicle]:
  p = {"dc_id": dc["dc_id"]}
  return vehicles_from_rows(
      dc,
      q("SELECT * FROM tractors WHERE dc_id = :dc_id", **p),
      q("SELECT * FROM trailers WHERE dc_id = :dc_id", **p),
      q("SELECT * FROM drivers WHERE dc_id = :dc_id", **p),
  )


@dataclass
class Problem:
  dc: dict
  date: dt.date
  depot: Point
  customers: dict[str, dict]
  orders: list[dict]
  stops: list[Stop]
  vehicles: list[Vehicle]
  costs: CostModel
  disruptions: list[Disruption]
  disruption_rows: list[dict]
  learned_service: dict[str, int]


def load_problem(
    dc_id: str,
    delivery_date: str,
    use_learned_service_times: bool = True,
    include_disruptions: bool = True,
    order_ids: Optional[list[str]] = None,
) -> Problem:
  dc = load_dc(dc_id)
  date = as_date(delivery_date)
  customers = load_customers(dc["dc_id"])
  orders = q(
      "SELECT * FROM orders WHERE dc_id = :dc_id AND delivery_date = :d ORDER BY order_id",
      dc_id=dc["dc_id"],
      d=date,
  )
  if order_ids is not None:
    wanted = set(order_ids)
    orders = [o for o in orders if o["order_id"] in wanted]
  learned = load_learned_service(dc["dc_id"]) if use_learned_service_times else {}
  if not use_learned_service_times:
    learned = {cid: int(c["std_service_min"]) for cid, c in customers.items()}
  disruptions, raw = load_disruptions(dc, date) if include_disruptions else ([], [])
  return Problem(
      dc=dc,
      date=date,
      depot=depot_point(dc),
      customers=customers,
      orders=orders,
      stops=stops_from_rows(orders, customers, learned),
      vehicles=load_vehicles(dc),
      costs=load_costs(dc["dc_id"]),
      disruptions=disruptions,
      disruption_rows=raw,
      learned_service=learned,
  )
