"""Retail and Restaurant on-time delivery (OTD).

McLane measures the two customer groups differently:

* **Retail** (convenience stores, grocery, mass merchants) is measured against
  the store's receiving window. Arriving early is fine (the driver waits or
  the store takes the load early); arriving after the window closes is a miss.
* **Restaurant** (QSR and casual dining) is measured against the scheduled
  delivery time the restaurant planned its crew around, within a tolerance
  (default plus or minus 30 minutes), and never after the receiving window.

Arrival is the geofence entry when the geofence fired, otherwise the driver
app timestamp. The policies live in the ``otd_policies`` table so each
business can tune them; the defaults below are used when the table is empty.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

SEGMENT_GROUP = {
    "CONVENIENCE": "RETAIL",
    "GROCERY": "RETAIL",
    "MASS_MERCHANT": "RETAIL",
    "QSR": "RESTAURANT",
    "CASUAL_DINING": "RESTAURANT",
}


@dataclass(frozen=True)
class OtdPolicy:
  segment_group: str
  measure_against: str            # RECEIVING_WINDOW | SCHEDULED_TIME
  early_tolerance_min: Optional[int]
  late_tolerance_min: int
  target_pct: float
  description: str = ""


DEFAULT_POLICIES = {
    "RETAIL": OtdPolicy(
        "RETAIL", "RECEIVING_WINDOW", None, 0, 95.0,
        "On time when the truck arrives (geofence entry) no later than the receiving window close. Early is fine.",
    ),
    "RESTAURANT": OtdPolicy(
        "RESTAURANT", "SCHEDULED_TIME", 30, 30, 98.0,
        "On time when the truck arrives within 30 minutes either side of the scheduled delivery time and "
        "before the receiving window closes.",
    ),
}


def segment_group(segment: Optional[str]) -> str:
  return SEGMENT_GROUP.get((segment or "").upper(), "RETAIL")


def policies_from_rows(rows: Iterable[Mapping]) -> dict[str, OtdPolicy]:
  out = dict(DEFAULT_POLICIES)
  for r in rows:
    early = r.get("early_tolerance_min")
    out[r["segment_group"]] = OtdPolicy(
        r["segment_group"], r["measure_against"], None if early in (None, "") else int(early),
        int(r.get("late_tolerance_min") or 0), float(r.get("target_pct") or 0), r.get("description") or "",
    )
  return out


def policy_rows() -> list[dict]:
  """Default policies as rows for the ``otd_policies`` table."""
  segs = defaultdict(list)
  for s, g in SEGMENT_GROUP.items():
    segs[g].append(s)
  return [
      {"segment_group": p.segment_group, "segments": ",".join(segs[p.segment_group]),
       "measure_against": p.measure_against, "early_tolerance_min": p.early_tolerance_min,
       "late_tolerance_min": p.late_tolerance_min, "target_pct": p.target_pct,
       "arrival_event": "GEOFENCE_ENTRY, else DRIVER_APP", "description": p.description}
      for p in DEFAULT_POLICIES.values()
  ]


def is_on_time(
    policy: OtdPolicy,
    arrival_min: int,
    window_start: int,
    window_end: int,
    scheduled_min: Optional[int] = None,
) -> bool:
  """Applies one OTD policy to one delivery."""
  if policy.measure_against == "SCHEDULED_TIME" and scheduled_min is not None:
    if arrival_min > window_end:
      return False
    early = policy.early_tolerance_min
    if early is not None and arrival_min < scheduled_min - early:
      return False
    return arrival_min <= scheduled_min + policy.late_tolerance_min
  if policy.early_tolerance_min is not None and arrival_min < window_start - policy.early_tolerance_min:
    return False
  return arrival_min <= window_end + policy.late_tolerance_min


def summarize(records: Iterable[Mapping], policies: Mapping[str, OtdPolicy] = DEFAULT_POLICIES) -> dict:
  """OTD per segment group and per segment.

  Each record needs ``segment`` and ``on_time`` (bool).
  """
  groups: dict[str, list[bool]] = defaultdict(list)
  segs: dict[str, list[bool]] = defaultdict(list)
  for r in records:
    ok = bool(r["on_time"])
    groups[segment_group(r.get("segment"))].append(ok)
    segs[(r.get("segment") or "UNKNOWN").upper()].append(ok)

  def pct(v):
    return round(100 * sum(v) / len(v), 1) if v else None

  out = {}
  for g in ("RETAIL", "RESTAURANT"):
    v = groups.get(g, [])
    p = policies.get(g, DEFAULT_POLICIES[g])
    otd = pct(v)
    out[g] = {
        "deliveries": len(v),
        "on_time": sum(v),
        "otd_pct": otd,
        "target_pct": p.target_pct,
        "gap_to_target_pts": round(otd - p.target_pct, 1) if otd is not None else None,
        "definition": p.description,
    }
  out["by_segment"] = {s: {"deliveries": len(v), "otd_pct": pct(v)} for s, v in sorted(segs.items())}
  return out


def plan_otd(routes, customers: Mapping[str, Mapping], policies: Mapping[str, OtdPolicy] = DEFAULT_POLICIES,
             scheduled: Optional[Mapping[str, int]] = None) -> dict:
  """Planned OTD of a plan, per segment group.

  ``routes`` are optimizer RouteResults. For restaurants the scheduled time is
  the ETA already promised (``scheduled``, by order id) when given, otherwise
  the plan's own ETA, so a new plan is judged on its receiving windows.
  """
  scheduled = scheduled or {}
  recs = []
  for r in routes:
    for s in r.stops:
      c = customers.get(s.customer_id, {})
      seg = c.get("segment")
      pol = policies.get(segment_group(seg), DEFAULT_POLICIES[segment_group(seg)])
      sched = scheduled.get(s.order_id.removesuffix("-COLD"), s.arrival_min)
      recs.append({"segment": seg, "on_time": is_on_time(pol, s.arrival_min, s.window_start, s.window_end, sched)})
  return summarize(recs, policies)
