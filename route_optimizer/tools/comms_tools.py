"""Customer communication tools: ETA notices for stores and restaurants."""

from __future__ import annotations

from google.adk.tools import FunctionTool

from ..db.repository import get_repository
from ..geo import fmt_time
from ._common import ToolError, new_id, now_ts, q


def _notices(plan_id: str, customer_id: str = "") -> list[dict]:
  rows = q(
      "SELECT rs.route_id, rs.stop_seq, rs.customer_id, rs.eta_min, rs.window_ok, c.name, c.segment, "
      "c.window_start_min, c.window_end_min, c.key_drop, r.route_date, r.driver_id "
      "FROM route_stops rs JOIN routes r ON rs.route_id = r.route_id "
      "JOIN customers c ON rs.customer_id = c.customer_id WHERE r.plan_id = :p ORDER BY rs.route_id, rs.stop_seq",
      p=plan_id,
  )
  if not rows:
    raise ToolError(f"Plan {plan_id!r} has no stops.")
  out = []
  for r in rows:
    if customer_id and r["customer_id"] != customer_id:
      continue
    eta = int(r["eta_min"])
    lo, hi = max(int(r["window_start_min"]), eta - 30), eta + 30
    late = str(r["window_ok"]).lower() not in {"1", "true", "t"}
    key_drop = str(r["key_drop"]).lower() in {"1", "true", "t"}
    body = (
        f"McLane delivery for {r['name']} on {r['route_date']}: expected {fmt_time(lo)}-{fmt_time(hi)}"
        + (f", later than your {fmt_time(r['window_start_min'])}-{fmt_time(r['window_end_min'])} window. We apologize."
           if late else ".")
        + (" Key-drop delivery, no one needs to be on site." if key_drop else " Please have the back door ready.")
    )
    out.append({
        "customer_id": r["customer_id"], "route_id": r["route_id"], "stop_seq": r["stop_seq"],
        "channel": "EDI_214" if r["segment"] in ("GROCERY", "MASS_MERCHANT") else "SMS",
        "late": late, "message": body,
    })
  return out


def draft_eta_notifications(plan_id: str, only_late: bool = False, customer_id: str = "") -> dict:
  """Drafts arrival-time notices for the stores and restaurants on a plan.

  Grocery and mass-merchant customers get an EDI 214 status message; c-stores
  and restaurants get an SMS. Nothing is sent.

  Args:
    plan_id: Plan id.
    only_late: Only draft notices for stops expected outside their window.
    customer_id: Optional single customer.

  Returns:
    The number of drafts and up to 15 sample messages.
  """
  drafts = _notices(plan_id, customer_id)
  if only_late:
    drafts = [d for d in drafts if d["late"]]
  return {"plan_id": plan_id, "drafts": len(drafts), "late_notices": sum(d["late"] for d in drafts), "samples": drafts[:15]}


def send_eta_notifications(plan_id: str, only_late: bool = False) -> dict:
  """Sends the ETA notices for a plan. Requires dispatcher confirmation.

  Args:
    plan_id: Plan id.
    only_late: Only send notices for stops expected outside their window.

  Returns:
    How many notices were recorded as sent, by channel.
  """
  drafts = _notices(plan_id)
  if only_late:
    drafts = [d for d in drafts if d["late"]]
  rows = [{
      "notification_id": new_id("NTF"), "plan_id": plan_id, "customer_id": d["customer_id"],
      "channel": d["channel"], "message": d["message"], "status": "SENT", "created_at": now_ts(),
  } for d in drafts]
  get_repository().insert("customer_notifications", rows)
  by_channel: dict[str, int] = {}
  for r in rows:
    by_channel[r["channel"]] = by_channel.get(r["channel"], 0) + 1
  return {"plan_id": plan_id, "sent": len(rows), "by_channel": by_channel,
          "note": "Simulated send: messages are recorded in customer_notifications."}


send_eta_notifications_tool = FunctionTool(send_eta_notifications, require_confirmation=True)
