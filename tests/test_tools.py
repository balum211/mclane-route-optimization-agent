"""Tool-level tests against the synthetic SQLite database (no LLM)."""

import pytest

from route_optimizer.tools import analytics_tools, comms_tools, data_tools, disruption_tools, event_tools, planning_tools, tms_tools
from route_optimizer.tools._common import ToolError

DC, DAY = "DC-TEMPLE-TX", "2026-10-27"


def test_list_dcs():
  out = data_tools.list_distribution_centers()
  assert len(out["distribution_centers"]) == 4
  assert DAY in out["order_dates_available"]


def test_unknown_dc_is_a_clear_error():
  with pytest.raises(ToolError, match="Known DCs"):
    data_tools.get_delivery_demand("DC-NOWHERE", DAY)


@pytest.fixture(scope="module")
def plan():
  class TC:
    state = {}

  return planning_tools.optimize_routes(DC, DAY, TC(), time_limit_s=4)


def test_optimized_plan_beats_tmw_static(plan):
  assert plan["totals"]["dropped_orders"] == 0
  vs = plan["vs_baseline"]
  assert vs["cost_usd"]["optimized"] < vs["cost_usd"]["tmw_static"]
  assert vs["late_stops"]["optimized"] <= vs["late_stops"]["tmw_static"]
  assert all(not r["hos_violation"] for r in plan["routes"])


def test_route_detail_and_dispatch(plan, tool_context):
  rid = plan["routes"][0]["route_id"]
  detail = planning_tools.get_route_plan(plan["plan_id"], rid)
  assert detail["stops"]
  preview = tms_tools.build_tmw_dispatch_payload(plan["plan_id"])
  assert preview["movements"] == plan["totals"]["routes"]
  stops = preview["sample_payload"]["stops"]
  assert stops[0]["stp_type"] == "PUP" and stops[1]["stp_type"] == "DRP"
  assert tms_tools.submit_plan_to_tmw_tool._require_confirmation is True
  sent = tms_tools.submit_plan_to_tmw(plan["plan_id"], tool_context)
  assert len(sent["messages"]) == plan["totals"]["routes"]
  assert tms_tools.submit_plan_to_tmw(plan["plan_id"], tool_context)["status"] == "ALREADY_SUBMITTED"


def test_comms(plan):
  drafts = comms_tools.draft_eta_notifications(plan["plan_id"])
  assert drafts["drafts"] == plan["totals"]["stops"]


def test_disruption_assessment(plan, tool_context):
  out = disruption_tools.assess_disruption_impact(DC, DAY, tool_context, plan_id=plan["plan_id"])
  assert out["events"]


@pytest.mark.parametrize("event_id", ["EVT-TEM-01", "EVT-TEM-02", "EVT-TEM-03", "EVT-TEM-04", "EVT-DAL-01", "EVT-DAL-02", "EVT-PHO-01", "EVT-CON-01"])
def test_seed_events_replan_under_30s(event_id, tool_context):
  out = event_tools.handle_route_event(event_id, tool_context)
  assert out["status"] in {"AUTO_APPLIED", "PENDING_APPROVAL", "NO_ACTION"}
  assert out["replan_latency_s"] < 30
  if out["status"] != "NO_ACTION":
    assert out["what_changed"]
    assert out["untouched_routes"] > 0


def test_reefer_alert_always_escalates_and_moves_cold_product(tool_context):
  out = event_tools.handle_route_event("EVT-DAL-02", tool_context)
  assert out["requires_human_approval"]
  assert any("Food safety" in r for r in out["escalation_reasons"])
  assert out["spare_units_used"]


def test_small_delay_is_no_action(plan, tool_context):
  rid = plan["routes"][0]["route_id"]
  out = event_tools.simulate_route_event("DELAY", rid, "07:00", tool_context, delay_min=5)
  assert out["status"] == "NO_ACTION"


def test_simulated_breakdown_on_optimized_plan(plan, tool_context):
  rid = plan["routes"][1]["route_id"]
  out = event_tools.simulate_route_event("BREAKDOWN", rid, "07:30", tool_context)
  assert out["affected_routes"] == [rid]
  assert out["untouched_routes"] == plan["totals"]["routes"] - 1
  pending = event_tools.get_pending_escalations()
  assert isinstance(pending["pending"], list)


def test_analytics(plan):
  k = analytics_tools.get_delivery_kpis(DC)
  assert 0 < k["on_time_pct"] <= 100
  assert analytics_tools.list_optimization_runs(DC)["runs"]
  assert analytics_tools.get_network_savings_summary(DAY)["dcs"]
