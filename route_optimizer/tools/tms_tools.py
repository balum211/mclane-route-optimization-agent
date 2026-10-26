"""Trimble TMW integration tools.

Plans are translated into the TMW.Suite object model: one *movement* per
truck, one *leg header* carrying tractor / trailer / driver assignments, and
an ordered list of *stops* (pickup at the DC, then drops) linked back to each
order header. Messages land in ``tmw_dispatch_queue``. When
``TMW_API_BASE_URL`` is set, they are also POSTed there; point it at your
TMW integration endpoint (for example a Trimble integration / REST gateway or
an internal middleware service) and adapt ``_post`` to its contract.
"""

from __future__ import annotations

import datetime as dt

from google.adk.tools import FunctionTool, ToolContext

from ..config import get_settings
from ..db.repository import get_repository
from ._common import ToolError, new_id, now_ts, q


def _iso(date: str, minutes: int) -> str:
  base = dt.datetime.fromisoformat(str(date)[:10])
  return (base + dt.timedelta(minutes=int(minutes))).isoformat(timespec="minutes")


def _payloads(plan_id: str) -> list[dict]:
  routes = q("SELECT * FROM routes WHERE plan_id = :p ORDER BY route_id", p=plan_id)
  if not routes:
    raise ToolError(f"Plan {plan_id!r} has no routes.")
  dc = q("SELECT * FROM distribution_centers WHERE dc_id = :d", d=routes[0]["dc_id"])[0]
  out = []
  for r in routes:
    stops = q(
        "SELECT rs.*, c.tmw_cmp_id, c.name, o.tmw_ord_hdrnumber, o.dry_cases, o.chill_cases, o.frozen_cases, o.weight_lbs "
        "FROM route_stops rs JOIN customers c ON rs.customer_id = c.customer_id "
        "JOIN orders o ON rs.order_id = o.order_id WHERE rs.route_id = :r ORDER BY rs.stop_seq",
        r=r["route_id"],
    )
    date = r["route_date"]
    tmw_stops = [{
        "stp_sequence": 1, "stp_event": "HLT", "stp_type": "PUP", "cmp_id": dc["dc_id"],
        "stp_arrivaldate": _iso(date, int(r["depart_min"]) - 30), "stp_departuredate": _iso(date, int(r["depart_min"])),
    }]
    for s in stops:
      tmw_stops.append({
          "stp_sequence": int(s["stop_seq"]) + 1,
          "stp_event": "DRL",
          "stp_type": "DRP",
          "cmp_id": s["tmw_cmp_id"],
          "cmp_name": s["name"],
          "ord_hdrnumber": s["tmw_ord_hdrnumber"],
          "stp_arrivaldate": _iso(date, s["eta_min"]),
          "stp_departuredate": _iso(date, s["etd_min"]),
          "stp_count": int(s["dry_cases"]) + int(s["chill_cases"]) + int(s["frozen_cases"]),
          "stp_countunit": "CAS",
          "stp_weight": s["weight_lbs"],
          "stp_weightunit": "LBS",
          "stp_ord_mileage": s["miles_from_prev"],
      })
    tmw_stops.append({
        "stp_sequence": len(tmw_stops) + 1, "stp_event": "EMT", "stp_type": "NONE", "cmp_id": dc["dc_id"],
        "stp_arrivaldate": _iso(date, r["return_min"]),
    })
    out.append({
        "route_id": r["route_id"],
        "message_type": "UPDATE_STOPS" if plan_id.startswith(("EVP-", "RPL-")) else "CREATE_MOVEMENT",
        "payload": {
            "movement": {"mov_external_ref": r["route_id"], "plan_id": plan_id, "revtype1": dc["business_unit"]},
            "legheader": {
                "lgh_tractor": r["tractor_id"],
                "lgh_primary_trailer": r["trailer_id"],
                "lgh_driver1": r["driver_id"],
                "lgh_startdate": _iso(date, r["depart_min"]),
                "lgh_enddate": _iso(date, r["return_min"]),
                "lgh_miles": r["total_miles"],
                "lgh_outstatus": "PLN",
            },
            "stops": tmw_stops,
        },
    })
  return out


def build_tmw_dispatch_payload(plan_id: str, route_id: str = "") -> dict:
  """Previews the Trimble TMW messages a plan would create, without sending.

  Args:
    plan_id: Plan id from optimize_routes or reoptimize_route_in_flight.
    route_id: Optional single route to show in full. Empty shows the first one.

  Returns:
    Count of movements, legs and stops, and one full TMW-shaped payload
    (movement, legheader with tractor/trailer/driver, stops with ETAs) for review.
  """
  msgs = _payloads(plan_id)
  sample = next((m for m in msgs if m["route_id"] == route_id), msgs[0])
  return {
      "plan_id": plan_id,
      "movements": len(msgs),
      "drop_stops": sum(len(m["payload"]["stops"]) - 2 for m in msgs),
      "sample_route_id": sample["route_id"],
      "sample_payload": sample["payload"],
      "next_step": "Call submit_plan_to_tmw to queue these for TMW after the dispatcher approves.",
  }


def _post(message: dict) -> str:
  s = get_settings()
  import requests

  resp = requests.post(
      f"{s.tmw_api_base_url.rstrip('/')}/movements",
      json=message["payload"],
      headers={"Authorization": f"Bearer {s.tmw_api_token}"} if s.tmw_api_token else {},
      timeout=30,
  )
  return "SENT" if resp.ok else "FAILED"


def submit_plan_to_tmw(plan_id: str, tool_context: ToolContext) -> dict:
  """Queues every route of an approved plan for dispatch in Trimble TMW.

  This changes the TMS of record, so it always asks the dispatcher to
  confirm first.

  Args:
    plan_id: Plan id to dispatch.

  Returns:
    Message ids written to the TMW dispatch queue and their status.
  """
  already = q("SELECT message_id FROM tmw_dispatch_queue WHERE plan_id = :p", p=plan_id)
  if already:
    return {"plan_id": plan_id, "status": "ALREADY_SUBMITTED", "messages": len(already)}
  msgs = _payloads(plan_id)
  live = bool(get_settings().tmw_api_base_url)
  rows = []
  for m in msgs:
    status = _post(m) if live else "QUEUED"
    rows.append({
        "message_id": new_id("TMW"), "plan_id": plan_id, "route_id": m["route_id"],
        "message_type": m["message_type"], "payload": m["payload"], "status": status, "created_at": now_ts(),
    })
  get_repository().insert("tmw_dispatch_queue", rows)
  tool_context.state["dispatched_plan_id"] = plan_id
  return {
      "plan_id": plan_id,
      "mode": "LIVE_API" if live else "QUEUE_ONLY (set TMW_API_BASE_URL to post to TMW)",
      "messages": [{"message_id": r["message_id"], "route_id": r["route_id"], "status": r["status"]} for r in rows],
  }


def get_dispatch_status(plan_id: str) -> dict:
  """Shows which routes of a plan have been sent to Trimble TMW.

  Args:
    plan_id: Plan id.

  Returns:
    Per-route TMW message status (QUEUED, SENT, ACKED, FAILED).
  """
  rows = q(
      "SELECT message_id, route_id, message_type, status, created_at FROM tmw_dispatch_queue WHERE plan_id = :p ORDER BY route_id",
      p=plan_id,
  )
  return {"plan_id": plan_id, "submitted": bool(rows), "messages": rows}


submit_plan_to_tmw_tool = FunctionTool(submit_plan_to_tmw, require_confirmation=True)
