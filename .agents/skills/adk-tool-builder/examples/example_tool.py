"""Example: a read-only tool and a confirmed write tool, in this repo's style."""

from google.adk.tools import FunctionTool, ToolContext

from route_optimizer.db.repository import get_repository
from route_optimizer.geo import fmt_time
from route_optimizer.tools._common import ToolError, as_date, new_id, now_ts, q


def get_late_stops(dc_id: str, delivery_date: str, tool_context: ToolContext, plan_id: str = "") -> dict:
  """Lists stops in a plan that are expected outside their receiving window.

  Args:
    dc_id: Distribution center id, e.g. "DC-TEMPLE-TX".
    delivery_date: YYYY-MM-DD.
    plan_id: Plan id. Empty uses the last plan from this session.

  Returns:
    Late stops with route, customer, ETA and window, worst first.
  """
  plan_id = plan_id or tool_context.state.get("last_plan_id", "")
  if not plan_id:
    raise ToolError("No plan yet. Run optimize_routes first.")
  rows = q(
      "SELECT rs.route_id, rs.customer_id, rs.eta_min, c.window_end_min FROM route_stops rs "
      "JOIN routes r ON rs.route_id = r.route_id JOIN customers c ON rs.customer_id = c.customer_id "
      "WHERE r.plan_id = :p AND r.dc_id = :dc AND r.route_date = :d",
      p=plan_id, dc=dc_id, d=as_date(delivery_date),
  )
  late = sorted((r for r in rows if r["eta_min"] and r["eta_min"] > r["window_end_min"]),
                key=lambda r: r["window_end_min"] - r["eta_min"])
  return {"plan_id": plan_id, "late_stops": [
      {"route_id": r["route_id"], "customer_id": r["customer_id"], "eta": fmt_time(r["eta_min"]),
       "window_end": fmt_time(r["window_end_min"]), "late_min": r["eta_min"] - r["window_end_min"]}
      for r in late[:20]]}


def hold_order(order_id: str, reason: str) -> dict:
  """Puts an order on hold so it is not routed today. Requires confirmation.

  Args:
    order_id: Order id.
    reason: Why it is held.

  Returns:
    The hold record.
  """
  get_repository().insert("customer_notifications", [{
      "notification_id": new_id("HLD"), "plan_id": None, "customer_id": None, "channel": "INTERNAL",
      "message": f"Order {order_id} held: {reason}", "status": "SENT", "created_at": now_ts()}])
  return {"order_id": order_id, "status": "HELD"}


hold_order_tool = FunctionTool(hold_order, require_confirmation=True)
