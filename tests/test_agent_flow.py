"""End-to-end ADK run with a scripted model: proves agent wiring, delegation
and tool execution without calling Gemini."""

import asyncio
import json
from typing import AsyncGenerator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types


class ScriptedLlm(BaseLlm):
  """Root transfers to the planner; the planner calls optimize_routes, then summarizes."""

  model: str = "scripted"

  async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
    tools = set(llm_request.tools_dict)
    last = llm_request.contents[-1].parts[-1] if llm_request.contents else None
    if last is not None and last.function_response and last.function_response.name == "optimize_routes":
      r = last.function_response.response
      text = f"Plan {r['plan_id']}: {r['totals']['routes']} trucks, ${r['totals']['cost_usd']}"
      yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))
    elif "optimize_routes" in tools:
      call = types.FunctionCall(name="optimize_routes", args={"dc_id": "DC-PHOENIX-AZ", "delivery_date": "2026-10-27", "time_limit_s": 2})
      yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))
    else:
      call = types.FunctionCall(name="transfer_to_agent", args={"agent_name": "route_planner_agent"})
      yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))


def _set_model(agent, model):
  agent.model = model
  for sub in agent.sub_agents:
    _set_model(sub, model)


def test_root_delegates_and_plans():
  from route_optimizer.agent import root_agent

  _set_model(root_agent, ScriptedLlm())
  runner = InMemoryRunner(agent=root_agent, app_name="test")

  async def run():
    session = await runner.session_service.create_session(app_name="test", user_id="u")
    texts, calls = [], []
    async for ev in runner.run_async(user_id="u", session_id=session.id,
                                     new_message=types.Content(role="user", parts=[types.Part(text="Plan Phoenix")])):
      for p in (ev.content.parts if ev.content else []):
        if p.function_call:
          calls.append(p.function_call.name)
        if p.text:
          texts.append(p.text)
    state = (await runner.session_service.get_session(app_name="test", user_id="u", session_id=session.id)).state
    return texts, calls, state

  texts, calls, state = asyncio.run(run())
  assert calls[:2] == ["transfer_to_agent", "optimize_routes"]
  assert texts and texts[-1].startswith("Plan PLN-PHO-")
  assert state["last_plan_id"].startswith("PLN-PHO-")


def test_agent_tree():
  from route_optimizer.agent import root_agent

  names = {a.name for a in root_agent.sub_agents}
  assert names == {"route_planner_agent", "disruption_agent", "tms_dispatch_agent", "customer_comms_agent",
                   "location_intelligence_agent", "analytics_agent"}
